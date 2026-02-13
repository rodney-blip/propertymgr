#!/usr/bin/env python3
"""
Zillow Zestimate scraper via two-step approach:

  1. Zillow Suggestion API (free, no auth) — converts addresses to ZPIDs
     Endpoint: https://www.zillowstatic.com/autocomplete/v3/suggestions
     Returns: ZPID, lat/lng, structured address for any property

  2. maxcopell/zillow-detail-scraper Apify actor — fetches full property data
     Input: Zillow homedetails URLs with ZPIDs
     Returns: zestimate, rentZestimate, beds, baths, sqft, yearBuilt,
              lotSize, lastSoldPrice, taxHistory, priceHistory, and more

Requires an apify_token in .api_keys.json (the same token used for Auction.com).

Usage:
    from scraper_zillow import batch_zestimate_lookup
    results = batch_zestimate_lookup([
        "61644 Gemini Way, Bend, OR 97702",
        "16125 Hawks Lair Rd, La Pine, OR 97739",
    ])
    # results = {"61644 GEMINI WAY": {"zestimate": 582300, "beds": 3, ...}, ...}
"""

import json
import re
import ssl
import time
from typing import List, Dict, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote, quote_plus

# Try to import config for API token
try:
    import config as _cfg
    APIFY_TOKEN = _cfg.API_KEYS.get("apify_token", "")
except ImportError:
    APIFY_TOKEN = ""

# Apify REST API base
APIFY_BASE = "https://api.apify.com/v2"

# Actor ID — "maxcopell/zillow-detail-scraper"
ACTOR_ID = "maxcopell~zillow-detail-scraper"

# Zillow Suggestion API (free, no auth)
ZILLOW_SUGGEST_URL = "https://www.zillowstatic.com/autocomplete/v3/suggestions"

# Max addresses per Apify actor run (keep runs small to avoid timeouts)
MAX_BATCH_SIZE = 15

# Timeout for Apify run (seconds)
RUN_TIMEOUT = 120

# Rate limit between Zillow suggestion API calls (seconds)
SUGGEST_RATE_LIMIT = 0.3

# SSL context for all requests
_ssl_ctx = ssl.create_default_context()


def is_configured() -> bool:
    """Check if Zillow Zestimate lookups are available."""
    return bool(APIFY_TOKEN)


def _normalize_address_key(address: str) -> str:
    """Normalize an address string for result matching."""
    # Strip to just the street address portion (before city/state/zip)
    parts = address.upper().split(",")
    street = parts[0].strip() if parts else address.upper().strip()
    return " ".join(street.split())


# ── Step 1: Zillow Suggestion API → ZPID lookup ──────────────────────

def _get_zpid(full_address: str, progress: bool = False) -> Optional[Dict]:
    """
    Look up a Zillow ZPID for a property address using the public suggestion API.

    Args:
        full_address: Full address, e.g. "61644 Gemini Way, Bend, OR 97702"

    Returns:
        Dict with keys: zpid, address, city, state, zip_code, lat, lng
        Or None if not found.
    """
    params = f"q={quote_plus(full_address)}&resultTypes=allAddress&resultCount=1"
    url = f"{ZILLOW_SUGGEST_URL}?{params}"

    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    }

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if progress:
            print(f"         Zillow suggest API error: {e}")
        return None

    # Parse the response
    results = data.get("results", [])
    if not results:
        return None

    # Find the first result with a ZPID
    for result in results:
        meta = result.get("metaData", {})
        zpid = meta.get("zpid")
        if not zpid:
            continue

        # Extract address components
        display = result.get("display", "")
        addr_parts = display.split(", ") if display else []

        # The suggestion API returns structured address in metaData
        street_num = meta.get("streetNumber", "")
        street_name = meta.get("streetName", "")
        street = f"{street_num} {street_name}".strip() if (street_num or street_name) else ""
        # Fallback: try streetAddress (some API versions use it)
        if not street:
            street = meta.get("streetAddress", "")
        city = meta.get("city", "")
        state = meta.get("state", "")
        zip_code = meta.get("zipCode", "") or meta.get("zipcode", "")
        lat = meta.get("lat")
        lng = meta.get("lng")

        # If metaData doesn't have components, parse from display
        if not street and addr_parts:
            street = addr_parts[0]
        if not city and len(addr_parts) > 1:
            city = addr_parts[1]
        if not state and len(addr_parts) > 2:
            # "OR 97702" → state=OR, zip=97702
            state_zip = addr_parts[2].strip().split()
            if state_zip:
                state = state_zip[0]
            if len(state_zip) > 1:
                zip_code = state_zip[1]

        return {
            "zpid": str(zpid),
            "address": street,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "lat": float(lat) if lat else None,
            "lng": float(lng) if lng else None,
        }

    return None


def _batch_get_zpids(addresses: List[str],
                     progress: bool = True) -> Dict[str, Dict]:
    """
    Look up ZPIDs for a batch of addresses.

    Returns:
        Dict mapping normalized address key → zpid info dict
    """
    results = {}
    total = len(addresses)

    for i, addr in enumerate(addresses):
        zpid_info = _get_zpid(addr, progress=progress)
        if zpid_info and zpid_info.get("zpid"):
            addr_key = _normalize_address_key(addr)
            zpid_info["original_address"] = addr
            results[addr_key] = zpid_info

        # Rate limit
        if i < total - 1:
            time.sleep(SUGGEST_RATE_LIMIT)

    if progress:
        print(f"      ZPID lookup: {len(results)}/{total} addresses resolved")

    return results


# ── Step 2: Build Zillow homedetails URLs from ZPIDs ─────────────────

def _build_zillow_url(zpid_info: Dict) -> str:
    """
    Build a Zillow homedetails URL from ZPID info.

    Format: https://www.zillow.com/homedetails/ADDRESS/ZPID_zpid/
    Example: https://www.zillow.com/homedetails/61644-Gemini-Way-Bend-OR-97702/80932074_zpid/
    """
    zpid = zpid_info["zpid"]

    # Build address slug: replace spaces/commas with hyphens
    street = zpid_info.get("address", "").strip()
    city = zpid_info.get("city", "").strip()
    state = zpid_info.get("state", "").strip()
    zip_code = zpid_info.get("zip_code", "").strip()

    # Construct: "61644 Gemini Way Bend OR 97702" → "61644-Gemini-Way-Bend-OR-97702"
    parts = [street, city, state, zip_code]
    slug = " ".join(p for p in parts if p)
    # Replace any non-alphanumeric (except hyphens) with hyphens, collapse multiples
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', slug).strip('-')

    return f"https://www.zillow.com/homedetails/{slug}/{zpid}_zpid/"


# ── Step 3: Run Apify actor for batch of ZPID URLs ──────────────────

def _run_actor(zpid_infos: List[Dict],
               timeout: int = RUN_TIMEOUT,
               progress: bool = True) -> List[Dict]:
    """
    Run the maxcopell/zillow-detail-scraper Apify actor for a batch of
    Zillow homedetails URLs.

    Returns:
        List of raw result dicts from the actor.
    """
    if not zpid_infos:
        return []

    # Build startUrls list
    start_urls = []
    for info in zpid_infos:
        url = _build_zillow_url(info)
        start_urls.append({"url": url})

    actor_input = {
        "startUrls": start_urls,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Start the actor run
    start_url = f"{APIFY_BASE}/acts/{ACTOR_ID}/runs?token={APIFY_TOKEN}"
    body = json.dumps(actor_input).encode("utf-8")

    try:
        req = Request(start_url, data=body, method="POST", headers=headers)
        with urlopen(req, timeout=30, context=_ssl_ctx) as resp:
            run_data = json.loads(resp.read().decode("utf-8"))
            run_id = run_data.get("data", {}).get("id")
            dataset_id = run_data.get("data", {}).get("defaultDatasetId")
            if not run_id:
                if progress:
                    print(f"      ⚠ Zillow actor failed to start")
                return []
            if progress:
                print(f"      Zillow actor run started ({len(zpid_infos)} URLs)")
    except (HTTPError, URLError, Exception) as e:
        if progress:
            print(f"      ⚠ Zillow actor start failed: {e}")
        return []

    # Poll for completion
    poll_url = f"{APIFY_BASE}/actor-runs/{run_id}?token={APIFY_TOKEN}"
    poll_interval = 5
    start_time = time.time()

    while time.time() - start_time < timeout:
        time.sleep(poll_interval)
        try:
            req = Request(poll_url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15, context=_ssl_ctx) as resp:
                status_data = json.loads(resp.read().decode("utf-8"))
                run_info = status_data.get("data", {})
                status = run_info.get("status", "")
                cost = run_info.get("usageTotalUsd", 0)
                elapsed = int(time.time() - start_time)
                if progress:
                    print(f"      Polling... {elapsed}s, status: {status}, cost: ${cost:.4f}")

                if status == "SUCCEEDED":
                    break
                elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    if progress:
                        print(f"      ⚠ Zillow run {status}")
                    return []
        except Exception:
            pass  # Network hiccup, keep polling
    else:
        if progress:
            print(f"      ⚠ Zillow run timed out after {timeout}s")
        return []

    # Fetch results from dataset
    items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={APIFY_TOKEN}&format=json"
    try:
        req = Request(items_url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=30, context=_ssl_ctx) as resp:
            items = json.loads(resp.read().decode("utf-8"))
            if not isinstance(items, list):
                items = []
    except Exception as e:
        if progress:
            print(f"      ⚠ Failed to fetch Zillow results: {e}")
        return []

    return items


# ── Step 4: Parse actor results into our format ──────────────────────

def _parse_actor_result(item: Dict, zpid_lookup: Dict[str, Dict]) -> Optional[Tuple[str, Dict]]:
    """
    Parse a single result from the maxcopell actor into our format.

    Returns:
        (addr_key, result_dict) or None
    """
    if item.get("error"):
        return None

    # Extract Zestimate — maxcopell actor uses these field names
    zestimate = item.get("zestimate")
    if not zestimate:
        return None

    # Extract address — maxcopell returns structured address data
    raw_addr = item.get("address", {})
    if isinstance(raw_addr, dict):
        street = raw_addr.get("streetAddress", "")
        city = raw_addr.get("city", "")
        state = raw_addr.get("state", "")
        zip_code = raw_addr.get("zipcode", "")
    else:
        street = str(raw_addr) if raw_addr else ""
        city = item.get("city", "")
        state = item.get("state", "")
        zip_code = item.get("zipcode", "")

    # Match to our original address using ZPID
    zpid = str(item.get("zpid", ""))
    addr_key = None

    # Try to find matching ZPID in our lookup
    if zpid:
        for key, info in zpid_lookup.items():
            if str(info.get("zpid")) == zpid:
                addr_key = key
                break

    # Fallback: match by normalized street address
    if not addr_key and street:
        addr_key = _normalize_address_key(street)

    if not addr_key:
        return None

    # Parse lot size — maxcopell returns lotSize in sqft, convert to acres
    lot_size_sqft = item.get("lotSize") or item.get("lotAreaValue")
    lot_size_acres = None
    if lot_size_sqft:
        try:
            lot_size_acres = round(float(lot_size_sqft) / 43560, 3)
        except (ValueError, TypeError):
            pass

    # Parse rent zestimate
    rent_zestimate = item.get("rentZestimate")

    # Parse year built
    year_built = item.get("yearBuilt")

    # Parse tax rate
    tax_rate = item.get("propertyTaxRate")
    annual_tax = None
    if tax_rate and zestimate:
        try:
            annual_tax = round(float(zestimate) * float(tax_rate) / 100, 2)
        except (ValueError, TypeError):
            pass

    # Parse last sold price
    last_sold = item.get("lastSoldPrice")

    result = {
        "zestimate": float(zestimate),
        "address": street,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "beds": item.get("bedrooms"),
        "baths": item.get("bathrooms"),
        "sqft": item.get("livingArea"),
        "lot_size": lot_size_acres,
        "zpid": zpid,
        "year_built": year_built,
        "zestimate_rent": rent_zestimate,
        "zestimate_high_pct": item.get("zestimateHighPercent"),
        "zestimate_low_pct": item.get("zestimateLowPercent"),
        "last_sold_price": last_sold,
        "property_tax_rate": tax_rate,
        "annual_tax": annual_tax,
        "home_type": item.get("homeType"),
        "raw": item,  # Keep full raw response for debugging
    }

    return (addr_key, result)


# ── Public API ────────────────────────────────────────────────────────

def batch_zestimate_lookup(addresses: List[str],
                            timeout: int = RUN_TIMEOUT,
                            progress: bool = True) -> Dict[str, Dict]:
    """
    Look up Zillow Zestimates for a batch of property addresses.

    Two-step approach:
      1. Zillow Suggestion API (free) → get ZPIDs for each address
      2. maxcopell/zillow-detail-scraper Apify actor → get Zestimates + details

    Args:
        addresses: List of full addresses, e.g. ["123 Main St, Portland, OR 97201"]
        timeout: Max seconds to wait for Apify run
        progress: Print progress messages

    Returns:
        Dict mapping normalized street address → result dict:
        {
            "123 MAIN ST": {
                "zestimate": 425000,
                "address": "123 Main St",
                "city": "Portland",
                "state": "OR",
                "zip_code": "97201",
                "beds": 3,
                "baths": 2.0,
                "sqft": 1850,
                "lot_size": 0.15,
                "zpid": "12345678",
                "year_built": 2005,
                "zestimate_rent": 2500,
                "zestimate_high_pct": 5,
                "zestimate_low_pct": 6,
                "last_sold_price": 350000,
                "raw": { ... }
            },
            ...
        }
    """
    if not APIFY_TOKEN:
        if progress:
            print("   ⚠️  No Apify token — cannot look up Zestimates")
        return {}

    if not addresses:
        return {}

    # Step 1: Resolve ZPIDs for all addresses via suggestion API
    if progress:
        print(f"      Resolving {len(addresses)} addresses to Zillow ZPIDs...")

    zpid_lookup = _batch_get_zpids(addresses, progress=progress)

    if not zpid_lookup:
        if progress:
            print("      No ZPIDs found — cannot fetch Zestimates")
        return {}

    # Step 2: Batch into Apify actor runs
    zpid_list = list(zpid_lookup.values())
    all_results = {}

    if len(zpid_list) > MAX_BATCH_SIZE:
        if progress:
            print(f"      Batching {len(zpid_list)} properties ({MAX_BATCH_SIZE} per run)...")
        for i in range(0, len(zpid_list), MAX_BATCH_SIZE):
            batch = zpid_list[i:i + MAX_BATCH_SIZE]
            items = _run_actor(batch, timeout=timeout, progress=progress)
            for item in items:
                parsed = _parse_actor_result(item, zpid_lookup)
                if parsed:
                    addr_key, result = parsed
                    all_results[addr_key] = result
            if i + MAX_BATCH_SIZE < len(zpid_list):
                time.sleep(3)  # Pause between Apify runs
    else:
        items = _run_actor(zpid_list, timeout=timeout, progress=progress)
        for item in items:
            parsed = _parse_actor_result(item, zpid_lookup)
            if parsed:
                addr_key, result = parsed
                all_results[addr_key] = result

    if progress:
        print(f"      Zillow: {len(all_results)} Zestimates returned for {len(addresses)} addresses")

    return all_results


def lookup_single(address: str, city: str, state: str, zip_code: str,
                   progress: bool = False) -> Optional[Dict]:
    """
    Convenience: look up Zestimate for a single property.
    Returns result dict or None.
    """
    full_address = f"{address}, {city}, {state} {zip_code}"
    results = batch_zestimate_lookup([full_address], progress=progress)
    if results:
        # Return first match
        addr_key = _normalize_address_key(address)
        return results.get(addr_key) or (list(results.values())[0] if results else None)
    return None


def reset_circuit_breaker():
    """Placeholder for API compatibility with other scrapers."""
    pass


def get_circuit_breaker_status():
    """Placeholder for API compatibility with other scrapers."""
    return {"tripped": False, "failures": 0}
