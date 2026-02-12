#!/usr/bin/env python3
"""
Auction.com scraper — two modes:

1. **Local data file** (data_auctioncom.json):
   Browse auction.com, copy property details into the JSON file, and they'll
   appear in the dashboard.  No API key needed.  This is the reliable path
   since Auction.com's Incapsula WAF blocks automated scraping.

2. **Apify cloud** (ParseForge PPE actor):
   Sends Auction.com URLs to Apify's headless browser.  Requires an
   apify_token in .api_keys.json.  Note: as of Feb 2026, the PPE actor
   has a "Invalid user session" bug that often returns 0 items.  The local
   data file is used as fallback when Apify returns nothing.

Data flow:
  search_auctions(state, ...) → List[Dict]  (raw property dicts)
  ↓
  Fed into auction_fetcher._build_property_from_raw() via source="auctioncom"

To update listings:
  1. Browse https://www.auction.com/residential/or/deschutes-county
  2. Edit data_auctioncom.json with current listings
  3. Run: python3 main.py --auction-com
"""

import json
import os
import ssl
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Try to import config for API token
try:
    import config as _cfg
    APIFY_TOKEN = _cfg.API_KEYS.get("apify_token", "")
    TIMEOUT = getattr(_cfg, "AUCTIONCOM_TIMEOUT", 120)
    MAX_ITEMS = getattr(_cfg, "AUCTIONCOM_MAX_ITEMS", 100)
except ImportError:
    APIFY_TOKEN = ""
    TIMEOUT = 120
    MAX_ITEMS = 100

# Local data file path
LOCAL_DATA_FILE = Path(__file__).parent / "data_auctioncom.json"

# Apify REST API base
APIFY_BASE = "https://api.apify.com/v2"

# Actor ID — tilde format required for API calls
ACTOR_ID = "parseforge~auction-com-property-scraper-ppe"

# State abbreviation → full name
STATE_ABBREV = {
    "OR": "Oregon", "TX": "Texas", "WA": "Washington", "FL": "Florida",
    "AZ": "Arizona", "GA": "Georgia", "NC": "North Carolina", "OH": "Ohio",
    "TN": "Tennessee", "CA": "California",
}

# Auction.com state URL patterns
AUCTION_STATE_URLS = {
    "Oregon": "https://www.auction.com/residential/or/",
    "Texas": "https://www.auction.com/residential/tx/",
    "Washington": "https://www.auction.com/residential/wa/",
    "Florida": "https://www.auction.com/residential/fl/",
    "Arizona": "https://www.auction.com/residential/az/",
    "Georgia": "https://www.auction.com/residential/ga/",
    "North Carolina": "https://www.auction.com/residential/nc/",
    "Ohio": "https://www.auction.com/residential/oh/",
    "Tennessee": "https://www.auction.com/residential/tn/",
    "California": "https://www.auction.com/residential/ca/",
}


def is_configured() -> bool:
    """Check if any Auction.com data source is available."""
    return bool(APIFY_TOKEN) or LOCAL_DATA_FILE.exists()


def search_auctions(states: List[str] = None,
                     counties: List[tuple] = None,
                     max_items: int = None,
                     timeout: int = None,
                     progress: bool = True) -> List[Dict]:
    """
    Search Auction.com for foreclosure properties.

    Strategy:
      1. Try Apify cloud scraper (if token configured)
      2. Fall back to local data file (data_auctioncom.json)

    Args:
        states: List of full state names (e.g., ["Oregon"]).
        counties: List of (county_slug, state_abbrev) tuples.
        max_items: Max properties per Apify run
        timeout: Seconds to wait for each Apify run
        progress: Print progress
    """
    if max_items is None:
        max_items = MAX_ITEMS
    if timeout is None:
        timeout = TIMEOUT

    all_results = []

    # --- Strategy 1: Try Apify cloud scraper ---
    if APIFY_TOKEN:
        apify_results = _search_via_apify(states, counties, max_items, timeout, progress)
        all_results.extend(apify_results)

    # --- Strategy 2: Load from local data file ---
    if not all_results and LOCAL_DATA_FILE.exists():
        local_results = _load_local_data(counties, states, progress)
        all_results.extend(local_results)

    if progress:
        print(f"      Auction.com total: {len(all_results)} properties returned")

    return all_results


def _search_via_apify(states, counties, max_items, timeout, progress):
    """Search Auction.com via Apify cloud actor."""
    all_results = []

    if counties:
        for county_slug, state_abbrev in counties:
            url = f"https://www.auction.com/residential/{state_abbrev.lower()}/{county_slug.lower()}-county"
            label = f"{county_slug.title()} County, {state_abbrev.upper()}"

            if progress:
                print(f"      Searching {label} on Auction.com via Apify...")

            actor_input = {
                "startUrl": url,
                "maxItems": max_items,
            }

            raw_items = _run_actor_async(actor_input, timeout, progress)

            count = 0
            for item in raw_items:
                parsed = _parse_apify_result(item)
                if parsed:
                    all_results.append(parsed)
                    count += 1

            if progress:
                print(f"      {label}: {count} listings from Apify")
    else:
        if states is None:
            states = ["Oregon"]

        for state in states:
            url = AUCTION_STATE_URLS.get(state)
            if not url:
                continue

            if progress:
                print(f"      Searching {state} on Auction.com via Apify...")

            actor_input = {
                "startUrl": url,
                "maxItems": max_items,
            }

            raw_items = _run_actor_async(actor_input, timeout, progress)

            for item in raw_items:
                parsed = _parse_apify_result(item)
                if parsed:
                    all_results.append(parsed)

            if progress:
                print(f"      {state}: {len(raw_items)} Apify listings")

    if not all_results and progress:
        print("      ⚠ Apify returned 0 results (known session bug)")
        print("        Falling back to local data file...")

    return all_results


def _load_local_data(counties: List[tuple] = None,
                      states: List[str] = None,
                      progress: bool = True) -> List[Dict]:
    """
    Load Auction.com property data from local JSON file.

    The file format matches what a user would manually enter after
    browsing auction.com.  Fields use Auction.com's naming convention.
    """
    if not LOCAL_DATA_FILE.exists():
        if progress:
            print("      No local data file found (data_auctioncom.json)")
        return []

    try:
        data = json.loads(LOCAL_DATA_FILE.read_text())
    except (json.JSONDecodeError, IOError) as e:
        if progress:
            print(f"      ⚠ Error reading {LOCAL_DATA_FILE.name}: {e}")
        return []

    raw_properties = data.get("properties", [])
    if not raw_properties:
        if progress:
            print("      Local data file has no properties")
        return []

    updated = data.get("_updated", "unknown")
    if progress:
        print(f"      Loading {len(raw_properties)} properties from local data (updated: {updated})")

    # Filter by county/state if specified
    target_counties = set()
    target_states = set()
    if counties:
        for slug, st in counties:
            target_counties.add(slug.lower())
            target_states.add(st.upper())
    if states:
        for s in states:
            # Convert full state name to abbreviation for matching
            for abbr, full in STATE_ABBREV.items():
                if full == s:
                    target_states.add(abbr)

    results = []
    today = datetime.now().date()

    for item in raw_properties:
        # Filter by geography if targets specified
        if target_counties:
            item_county = (item.get("county") or "").lower()
            if item_county and item_county not in target_counties:
                continue
        if target_states and not target_counties:
            item_state = (item.get("state") or "").upper()
            if item_state and item_state not in target_states:
                continue

        parsed = _parse_local_item(item, today)
        if parsed:
            results.append(parsed)

    if progress:
        print(f"      Local data: {len(results)} properties after filtering")

    return results


def _parse_local_item(item: dict, today) -> Optional[Dict]:
    """
    Convert a local data file entry into our standard raw property dict.

    Local items use Auction.com field names directly (address, city, state,
    opening_bid, est_resale_value, beds, baths, sqft, etc.)
    """
    address = (item.get("address") or "").strip()
    if not address:
        return None

    city = (item.get("city") or "").strip()
    raw_state = (item.get("state") or "").strip()
    state = STATE_ABBREV.get(raw_state.upper(), raw_state)
    zip_code = str(item.get("zip_code") or "").strip()
    county = (item.get("county") or "").strip()

    # Price — use opening_bid or estimate from est_resale_value
    opening_bid = _safe_float(item.get("opening_bid"))
    est_resale = _safe_float(item.get("est_resale_value"))

    # If no opening bid, estimate it as 40-60% of resale value
    if opening_bid <= 0 and est_resale > 0:
        opening_bid = round(est_resale * 0.50, 2)  # Estimate: 50% of market value

    if opening_bid <= 0 and est_resale <= 0:
        return None  # No price data at all

    # Property details
    beds = _safe_int(item.get("beds"))
    baths = _safe_float(item.get("baths"))
    sqft = _safe_int(item.get("sqft"))
    lot_size = _safe_float(item.get("lot_sqft"))
    year_built = _safe_int(item.get("year_built"))

    # Auction date — compute from "auction_starts_in_days" if no explicit date
    auction_date = (item.get("auctionDate") or "").strip()
    if not auction_date:
        starts_in = _safe_int(item.get("auction_starts_in_days"))
        if starts_in > 0:
            auction_date = (today + timedelta(days=starts_in)).strftime("%Y-%m-%d")

    auction_time = (item.get("auctionTime") or "").strip()
    auction_location = (item.get("auctionLocation") or "Online").strip()
    sale_type = (item.get("saleType") or "Foreclosure").strip()
    occupancy = (item.get("occupancy_status") or "").strip()
    property_url = (item.get("url") or "").strip()
    photo_url = (item.get("primary_photo_url") or "").strip()

    return {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "county": county,
        "sale_amount": opening_bid,
        "estimated_value": est_resale,
        "bedrooms": beds,
        "bathrooms": baths,
        "sqft": sqft,
        "lot_size": lot_size,
        "year_built": year_built,
        "auction_date": auction_date,
        "auction_time": auction_time,
        "auction_location": auction_location,
        "auction_type": sale_type,
        "sale_type": sale_type,
        "occupancy_status": occupancy,
        "property_url": property_url,
        "image_url": photo_url,
        "source_name": "Auction.com (manual data)",
    }


def _run_actor_async(actor_input: dict, timeout: int, progress: bool) -> List[Dict]:
    """
    Run actor asynchronously: start run, poll for completion, fetch dataset.
    """
    ctx = ssl.create_default_context()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Step 1: Start the run
    start_url = f"{APIFY_BASE}/acts/{ACTOR_ID}/runs?token={APIFY_TOKEN}"
    body = json.dumps(actor_input).encode("utf-8")

    try:
        req = Request(start_url, data=body, method="POST", headers=headers)
        with urlopen(req, timeout=30, context=ctx) as resp:
            run_data = json.loads(resp.read().decode("utf-8"))
            run_id = run_data.get("data", {}).get("id")
            dataset_id = run_data.get("data", {}).get("defaultDatasetId")
            if not run_id:
                if progress:
                    print("      ⚠ Failed to start Apify run")
                return []
            if progress:
                print(f"      Run started: {run_id}")
    except HTTPError as e:
        if e.code == 402:
            if progress:
                print("      ⚠ Apify: Free credits exhausted")
                print("        Top up at: https://console.apify.com/billing")
            return []
        body = ""
        try:
            body = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        if progress:
            print(f"      ⚠ Apify HTTP {e.code}: {body}")
        return []
    except Exception as e:
        if progress:
            print(f"      ⚠ Failed to start Apify run: {e}")
        return []

    # Step 2: Poll for completion
    poll_url = f"{APIFY_BASE}/acts/{ACTOR_ID}/runs/{run_id}?token={APIFY_TOKEN}"
    start_time = time.time()
    poll_interval = 5

    while time.time() - start_time < timeout:
        time.sleep(poll_interval)
        try:
            req = Request(poll_url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15, context=ctx) as resp:
                status_data = json.loads(resp.read().decode("utf-8"))
                run_info = status_data.get("data", {})
                status = run_info.get("status", "")
                cost = run_info.get("usageTotalUsd", 0)
                if progress:
                    elapsed = int(time.time() - start_time)
                    print(f"      Polling... {elapsed}s, status: {status}, cost: ${cost:.4f}")
                if status == "SUCCEEDED":
                    dataset_id = run_info.get("defaultDatasetId", dataset_id)
                    break
                elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    if progress:
                        print(f"      ⚠ Apify run {status}")
                    return []
        except Exception:
            pass  # Polling error — retry
    else:
        if progress:
            print(f"      ⚠ Apify run timed out after {timeout}s")
        return []

    # Step 3: Fetch dataset items
    if not dataset_id:
        return []

    items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items?token={APIFY_TOKEN}&format=json"
    try:
        req = Request(items_url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=30, context=ctx) as resp:
            items = json.loads(resp.read().decode("utf-8"))
            return items if isinstance(items, list) else []
    except Exception as e:
        if progress:
            print(f"      ⚠ Failed to fetch results: {e}")
        return []


def _parse_apify_result(item: dict) -> Optional[Dict]:
    """
    Convert an Apify Auction.com result into our standard raw property dict.

    Real field names from the API (as of Feb 2026):
      street_description, municipality, country_primary_subdivision, postal_code,
      opening_bid, est_resale_value, starting_bid_amount, beds, baths, sqft,
      lot_sqft, year_built, property_type, saleType, auctionDate, auctionTime,
      auctionLocation, url, occupancy_status, country_secondary_subdivision, etc.
    """
    # Street address — use street_description (just the street) or full address
    street = (item.get("street_description") or "").strip()
    full_address = (item.get("address") or "").strip()

    if not street and not full_address:
        return None

    # Use street_description for the address field (cleaner)
    address = street if street else full_address

    # City
    city = (item.get("municipality") or "").strip()

    # State — comes as abbreviation (OR, TX, etc.)
    raw_state = (item.get("country_primary_subdivision") or "").strip()
    state = STATE_ABBREV.get(raw_state.upper(), raw_state)

    # ZIP
    zip_code = str(item.get("postal_code") or "").strip()

    # County
    county = (item.get("country_secondary_subdivision") or "").strip()

    # Price — use opening_bid (what you'd actually bid)
    price = (
        item.get("opening_bid")
        or item.get("starting_bid_amount")
        or 0
    )
    price = _safe_float(price)

    # Estimated resale value (Auction.com provides this — great for ARV)
    est_resale = _safe_float(item.get("est_resale_value"))

    # If no opening bid, estimate as 50% of resale value (common for foreclosures)
    if price <= 0 and est_resale > 0:
        price = round(est_resale * 0.50, 2)

    if price <= 0 and est_resale <= 0:
        return None  # No price data at all

    # Property details
    beds = _safe_int(item.get("beds"))
    baths = _safe_float(item.get("baths"))
    sqft = _safe_int(item.get("sqft"))
    lot_size = _safe_float(item.get("lot_sqft"))
    year_built = _safe_int(item.get("year_built"))

    # Auction details
    auction_date = (item.get("auctionDate") or "").strip()
    auction_time = (item.get("auctionTime") or "").strip()
    auction_location = (item.get("auctionLocation") or "").strip()
    sale_type = (item.get("saleType") or "Foreclosure").strip()

    # Occupancy
    occupancy = (item.get("occupancy_status") or "").strip()

    # URL
    property_url = (item.get("url") or "").strip()

    # Photo
    photo_url = (item.get("primary_photo_url") or "").strip()

    return {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "county": county,
        "sale_amount": price,
        "estimated_value": est_resale,
        "bedrooms": beds,
        "bathrooms": baths,
        "sqft": sqft,
        "lot_size": lot_size,
        "year_built": year_built,
        "auction_date": auction_date,
        "auction_time": auction_time,
        "auction_location": auction_location,
        "auction_type": sale_type,
        "sale_type": sale_type,
        "occupancy_status": occupancy,
        "property_url": property_url,
        "image_url": photo_url,
        "source_name": "Auction.com via Apify",
    }


def _safe_int(val, default=0):
    if val is None:
        return default
    try:
        return int(float(str(val).replace(",", "").strip()))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return default


def get_status() -> dict:
    """Check Auction.com data source configuration."""
    sources = []

    if APIFY_TOKEN:
        ctx = ssl.create_default_context()
        try:
            url = f"{APIFY_BASE}/users/me?token={APIFY_TOKEN}"
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                user = data.get("data", {})
                plan = user.get("plan", {}).get("id", "unknown")
                sources.append(f"Apify ({user.get('username', '?')}, {plan})")
        except HTTPError as e:
            if e.code == 401:
                sources.append("Apify (invalid token)")
            else:
                sources.append(f"Apify (error: {e.code})")
        except Exception as e:
            sources.append(f"Apify (error: {e})")

    if LOCAL_DATA_FILE.exists():
        try:
            data = json.loads(LOCAL_DATA_FILE.read_text())
            count = len(data.get("properties", []))
            updated = data.get("_updated", "unknown")
            sources.append(f"Local file ({count} properties, updated {updated})")
        except Exception:
            sources.append("Local file (error reading)")

    if sources:
        return {
            "configured": True,
            "message": "Sources: " + " + ".join(sources),
        }
    else:
        return {
            "configured": False,
            "message": "No Apify token and no local data file",
        }


# --- CLI test ---
if __name__ == "__main__":
    import sys

    status = get_status()
    print(f"Auction.com status: {status['message']}")
    print()

    if not status["configured"]:
        print("No Auction.com data sources available!")
        print()
        print("Option 1 (recommended):")
        print("  1. Browse https://www.auction.com/residential/or/deschutes-county")
        print("  2. Add property data to data_auctioncom.json")
        print("  3. Run: python3 main.py --auction-com")
        print()
        print("Option 2 (Apify cloud):")
        print("  1. Sign up free: https://console.apify.com/sign-up")
        print("  2. Get your token: https://console.apify.com/account/integrations")
        print("  3. Add to .api_keys.json:  {\"apify_token\": \"your_token_here\"}")
        sys.exit(1)

    states = sys.argv[1:] if len(sys.argv) > 1 else ["Oregon"]
    print(f"Searching Auction.com for: {', '.join(states)}")
    print(f"Max properties: {MAX_ITEMS}")
    print()

    results = search_auctions(states=states, progress=True)

    if not results:
        print("\nNo properties returned from Auction.com.")
    else:
        print(f"\nFound {len(results)} Auction.com properties:\n")
        for i, prop in enumerate(results[:10], 1):
            print(f"  {i}. {prop['address']}, {prop['city']}, {prop['state']} {prop['zip_code']}")
            bid_str = f"${prop['sale_amount']:,.0f}" if prop['sale_amount'] else "N/A"
            est_str = f"${prop.get('estimated_value', 0):,.0f}" if prop.get('estimated_value') else "N/A"
            print(f"     Bid: {bid_str}  |  "
                  f"Est Value: {est_str}  |  "
                  f"{prop['bedrooms']}bd/{prop['bathrooms']}ba  |  "
                  f"{prop['sqft']:,} sqft")
            if prop.get("auction_date"):
                print(f"     Auction: {prop['auction_date']}  |  Type: {prop.get('auction_type', 'N/A')}")
            if prop.get("occupancy_status"):
                print(f"     Occupancy: {prop['occupancy_status']}")
            if prop.get("property_url"):
                print(f"     URL: {prop['property_url']}")
            print()
        if len(results) > 10:
            print(f"  ... and {len(results) - 10} more")
