#!/usr/bin/env python3
"""
Redfin Stingray API scraper for real MLS-listed foreclosures.

Uses the public (unofficial) gis-csv endpoint with lat/lng bounding box
(poly parameter) to fetch foreclosure and bank-owned listings.
No API key required.

IMPORTANT: The Redfin `region_id` parameter uses Redfin's internal IDs,
NOT ZIP codes. So we use the `poly` parameter (lat/lng bounding box)
instead, derived from city center coordinates in config.CITY_COORDINATES.

Rate-limited to 3 seconds between requests to be respectful.
Circuit breaker stops after consecutive failures (site may be blocking).

Data flow:
  search_foreclosures_by_area(lat, lng, ...) → List[Dict]  (raw property dicts)
  ↓
  Fed into auction_fetcher._build_property_from_raw() via source="redfin"
"""

import csv
import io
import time
import random
import ssl
from typing import List, Dict, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError

# Try to import config for settings; fall back to defaults
try:
    import config as _cfg
    RATE_LIMIT = getattr(_cfg, "REDFIN_RATE_LIMIT", 3)
    MAX_RETRIES = getattr(_cfg, "REDFIN_MAX_RETRIES", 2)
    TIMEOUT = getattr(_cfg, "REDFIN_TIMEOUT", 15)
    CIRCUIT_BREAKER_LIMIT = getattr(_cfg, "REDFIN_CIRCUIT_BREAKER", 3)
    USER_AGENT = getattr(_cfg, "REDFIN_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36")
except ImportError:
    RATE_LIMIT = 3
    MAX_RETRIES = 2
    TIMEOUT = 15
    CIRCUIT_BREAKER_LIMIT = 3
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

REDFIN_CSV_URL = "https://www.redfin.com/stingray/api/gis-csv"

# Redfin market slugs — map state to market name for the API
# The market parameter helps Redfin route the request but isn't strictly required
STATE_TO_MARKET = {
    "Oregon": "portland",
    "Texas": "austin",
    "Washington": "seattle",
    "Florida": "tampa",
    "Arizona": "phoenix",
    "Georgia": "atlanta",
    "North Carolina": "charlotte",
    "Ohio": "columbus",
    "Tennessee": "nashville",
    "California": "sacramento",
}

# State abbreviation → full name mapping (Redfin returns abbreviations in CSV)
STATE_ABBREV_TO_FULL = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# Track consecutive failures for circuit breaker
_consecutive_failures = 0


def search_foreclosures_by_zip(zip_code: str,
                                max_results: int = 350,
                                timeout: int = None,
                                city_hint: str = None,
                                state_hint: str = None) -> List[Dict]:
    """
    Search Redfin for foreclosure/bank-owned listings near a ZIP code.

    Uses city coordinates from config.CITY_COORDINATES to build a bounding box,
    since Redfin's region_id parameter uses internal IDs (not ZIP codes).

    Args:
        zip_code: 5-digit ZIP code (used to look up city coordinates)
        max_results: Maximum listings to return per area
        timeout: HTTP timeout in seconds
        city_hint: City name (helps resolve coordinates)
        state_hint: State name (helps resolve coordinates)

    Returns:
        List of raw property dicts, or empty list on failure
    """
    # Look up coordinates for this city/ZIP
    lat, lng = _resolve_coordinates(zip_code, city_hint, state_hint)
    if lat is None or lng is None:
        return []

    # Determine Redfin market slug
    market = STATE_TO_MARKET.get(state_hint, "")

    return search_foreclosures_by_area(
        lat, lng,
        radius_deg=0.15,  # ~10 miles
        market=market,
        max_results=max_results,
        timeout=timeout,
    )


def search_foreclosures_by_area(lat: float, lng: float,
                                  radius_deg: float = 0.15,
                                  market: str = "",
                                  max_results: int = 350,
                                  timeout: int = None) -> List[Dict]:
    """
    Search Redfin for foreclosure/bank-owned listings in a bounding box.

    Args:
        lat: Center latitude
        lng: Center longitude
        radius_deg: Half-width of bounding box in degrees (~0.15 ≈ 10 miles)
        market: Redfin market slug (e.g., "portland", "austin")
        max_results: Maximum listings per request
        timeout: HTTP timeout in seconds

    Returns:
        List of raw property dicts compatible with _build_property_from_raw()
    """
    global _consecutive_failures

    if _consecutive_failures >= CIRCUIT_BREAKER_LIMIT:
        return []  # Circuit breaker tripped

    if timeout is None:
        timeout = TIMEOUT

    # Build bounding box polygon: "lng1 lat1, lng2 lat1, lng2 lat2, lng1 lat2, lng1 lat1"
    poly = _make_bounding_box(lat, lng, radius_deg)

    # --- Step 1: Try sf=2 (foreclosures only) ---
    results = _fetch_and_parse_poly(poly, market=market, sf="2",
                                      max_results=max_results, timeout=timeout)

    # --- Step 2: Fallback — fetch all sale types, filter locally ---
    if not results:
        all_results = _fetch_and_parse_poly(poly, market=market,
                                              sf="1,2,3,5,6,7",
                                              max_results=max_results,
                                              timeout=timeout)
        if all_results:
            results = [
                r for r in all_results
                if _is_foreclosure_type(r.get("sale_type", ""))
            ]

    # Rate limiting — respect Redfin servers
    time.sleep(RATE_LIMIT + random.uniform(0, 1))

    return results


def _make_bounding_box(lat: float, lng: float, radius: float) -> str:
    """
    Create a bounding box polygon string for the Redfin poly parameter.

    Format: "lng1 lat1,lng2 lat1,lng2 lat2,lng1 lat2,lng1 lat1"
    (closed polygon, 5 points, counterclockwise)
    """
    lat_min = lat - radius
    lat_max = lat + radius
    lng_min = lng - radius
    lng_max = lng + radius

    return (
        f"{lng_min} {lat_min},"
        f"{lng_max} {lat_min},"
        f"{lng_max} {lat_max},"
        f"{lng_min} {lat_max},"
        f"{lng_min} {lat_min}"
    )


def _resolve_coordinates(zip_code: str, city_hint: str = None,
                          state_hint: str = None) -> Tuple[Optional[float], Optional[float]]:
    """
    Look up lat/lng for a city/ZIP from config.CITY_COORDINATES.

    Falls back to scanning all coordinates for the state if city not found.
    """
    try:
        coords = _cfg.CITY_COORDINATES
    except (NameError, AttributeError):
        return None, None

    # Direct lookup by (city, state)
    if city_hint and state_hint:
        key = (city_hint, state_hint)
        if key in coords:
            return coords[key]

    # Try to find any city in the same state
    if state_hint:
        for (city, state), (lat, lng) in coords.items():
            if state == state_hint:
                return lat, lng

    # Last resort: no coordinates found
    return None, None


def _fetch_and_parse_poly(poly: str, market: str = "",
                           sf: str = "2", max_results: int = 350,
                           timeout: int = 15) -> List[Dict]:
    """
    Fetch CSV from Redfin using a polygon bounding box and parse results.
    """
    global _consecutive_failures

    params = {
        "al": "1",
        "sf": sf,
        "status": "1",
        "uipt": "1",
        "num_homes": str(max_results),
        "poly": poly,
    }
    if market:
        params["market"] = market

    url = f"{REDFIN_CSV_URL}?{urlencode(params)}"

    csv_text = _fetch_csv(url, timeout)
    if csv_text is None:
        return []

    # Parse CSV — Redfin sometimes prepends a notice line
    properties = []
    try:
        # Filter out non-CSV lines (like the MLS notice)
        lines = csv_text.strip().split("\n")
        csv_lines = [l for l in lines if not l.startswith('"In accordance')]
        clean_text = "\n".join(csv_lines)

        reader = csv.DictReader(io.StringIO(clean_text))
        for row in reader:
            parsed = _parse_csv_row(row)
            if parsed is not None:
                properties.append(parsed)
    except Exception as e:
        print(f"    ⚠ Redfin CSV parse error: {e}")
        return []

    # Reset circuit breaker on success (even with 0 results — the API worked)
    _consecutive_failures = 0
    return properties


def _fetch_csv(url: str, timeout: int) -> Optional[str]:
    """
    Fetch CSV content from Redfin with browser-like headers and retry logic.

    Returns CSV text string, or None on failure.
    """
    global _consecutive_failures

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.redfin.com/",
        "DNT": "1",
    }

    ctx = ssl.create_default_context()

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                status = resp.getcode()
                if status != 200:
                    print(f"    ⚠ Redfin returned HTTP {status}")
                    _consecutive_failures += 1
                    return None

                raw = resp.read()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")

                # Empty or error response
                if not text.strip() or text.strip().startswith("<!"):
                    _consecutive_failures += 1
                    return None

                return text

        except HTTPError as e:
            if e.code in (403, 429):
                _consecutive_failures += 1
                if attempt < MAX_RETRIES:
                    wait = RATE_LIMIT * (attempt + 2)
                    time.sleep(wait)
                    continue
                else:
                    return None
            else:
                _consecutive_failures += 1
                return None

        except (URLError, TimeoutError, OSError):
            if attempt < MAX_RETRIES:
                time.sleep(RATE_LIMIT)
                continue
            _consecutive_failures += 1
            return None

        except Exception:
            _consecutive_failures += 1
            return None

    return None


def _parse_csv_row(row: dict) -> Optional[Dict]:
    """
    Convert a Redfin CSV row dict into the raw property format expected by
    auction_fetcher._build_property_from_raw().

    Returns None if row is missing critical data (address or price).
    """
    address = (row.get("ADDRESS") or "").strip()
    price_str = (row.get("PRICE") or "").strip()

    # Skip rows without address or price
    if not address or not price_str:
        return None

    price = _safe_float(price_str)
    if price <= 0:
        return None

    # Normalize state
    raw_state = (row.get("STATE OR PROVINCE") or "").strip()
    state = _normalize_state(raw_state)

    city = (row.get("CITY") or "").strip()
    zip_code = (row.get("ZIP OR POSTAL CODE") or "").strip()

    # Extract the real Redfin listing URL
    property_url = ""
    for key in row:
        if key and key.startswith("URL"):
            property_url = (row[key] or "").strip()
            break

    # Lot size: Redfin reports in sqft, convert to acres
    lot_sqft = _safe_float(row.get("LOT SIZE"))
    lot_acres = round(lot_sqft / 43560, 3) if lot_sqft > 0 else 0.0

    # HOA
    hoa_str = (row.get("HOA/MONTH") or "").strip()
    hoa_monthly = None
    if hoa_str and hoa_str not in ("", "—", "-", "N/A"):
        hoa_val = _safe_float(hoa_str.replace("$", "").replace(",", ""))
        if hoa_val > 0:
            hoa_monthly = hoa_val

    sale_type = (row.get("SALE TYPE") or "").strip()

    return {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "sale_amount": price,
        "bedrooms": _safe_int(row.get("BEDS")),
        "bathrooms": _safe_float(row.get("BATHS")),
        "sqft": _safe_int(row.get("SQUARE FEET")),
        "lot_size": lot_acres,
        "year_built": _safe_int(row.get("YEAR BUILT")),
        "property_url": property_url,
        "latitude": _safe_float(row.get("LATITUDE")),
        "longitude": _safe_float(row.get("LONGITUDE")),
        "sale_type": sale_type,
        "days_on_market": _safe_int(row.get("DAYS ON MARKET")),
        "hoa_monthly": hoa_monthly,
        "mls_number": (row.get("MLS#") or "").strip(),
        "price_per_sqft": _safe_float(row.get("$/SQUARE FEET")),
        "property_type": (row.get("PROPERTY TYPE") or "Single Family").strip(),
        "source_name": (row.get("SOURCE") or "").strip(),
    }


def _normalize_state(raw: str) -> str:
    """Convert state abbreviation to full name, or return as-is if already full."""
    raw = raw.strip()
    upper = raw.upper()
    if upper in STATE_ABBREV_TO_FULL:
        return STATE_ABBREV_TO_FULL[upper]
    if raw and len(raw) > 2:
        return raw.title()
    return raw


def _is_foreclosure_type(sale_type: str) -> bool:
    """Check if a SALE TYPE value indicates foreclosure/bank-owned/REO."""
    st = sale_type.lower()
    return any(kw in st for kw in [
        "foreclosure", "bank owned", "bank-owned", "reo",
        "short sale", "auction", "hud",
    ])


def _safe_int(val, default: int = 0) -> int:
    """Safely convert a string value to int."""
    if val is None:
        return default
    try:
        cleaned = str(val).replace(",", "").strip()
        if not cleaned or cleaned in ("—", "-", "N/A"):
            return default
        return int(float(cleaned))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert a string value to float."""
    if val is None:
        return default
    try:
        cleaned = str(val).replace(",", "").replace("$", "").strip()
        if not cleaned or cleaned in ("—", "-", "N/A"):
            return default
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def reset_circuit_breaker():
    """Reset the circuit breaker counter (call between full runs)."""
    global _consecutive_failures
    _consecutive_failures = 0


def get_circuit_breaker_status() -> dict:
    """Return current circuit breaker state for diagnostics."""
    return {
        "consecutive_failures": _consecutive_failures,
        "limit": CIRCUIT_BREAKER_LIMIT,
        "tripped": _consecutive_failures >= CIRCUIT_BREAKER_LIMIT,
    }


# --- CLI test ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2:
        # Direct lat/lng test
        lat, lng = float(sys.argv[1]), float(sys.argv[2])
        market = sys.argv[3] if len(sys.argv) > 3 else ""
        print(f"Searching Redfin foreclosures near ({lat}, {lng})...")
        results = search_foreclosures_by_area(lat, lng, market=market)
    elif len(sys.argv) > 1:
        # ZIP code test
        zip_code = sys.argv[1]
        print(f"Searching Redfin foreclosures for ZIP {zip_code}...")
        results = search_foreclosures_by_zip(zip_code)
    else:
        # Default: Portland, OR bounding box test
        print("Searching Redfin foreclosures in Portland, OR area...")
        results = search_foreclosures_by_area(
            45.5152, -122.6784,  # Portland center
            radius_deg=0.15,
            market="portland",
        )

    if not results:
        print("\nNo foreclosure listings found.")
        print("This is normal — foreclosure inventory on MLS varies by area.")
    else:
        print(f"\nFound {len(results)} foreclosure/bank-owned listings:\n")
        for i, prop in enumerate(results, 1):
            print(f"  {i}. {prop['address']}, {prop['city']}, {prop['state']} {prop['zip_code']}")
            price = prop['sale_amount']
            print(f"     Price: ${price:,.0f}  |  "
                  f"{prop['bedrooms']}bd/{prop['bathrooms']}ba  |  "
                  f"{prop['sqft']:,} sqft  |  Built {prop['year_built']}")
            if prop.get("property_url"):
                print(f"     URL: {prop['property_url']}")
            print()

    print(f"Circuit breaker: {get_circuit_breaker_status()}")
