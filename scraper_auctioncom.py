#!/usr/bin/env python3
"""
Auction.com scraper via Apify's ParseForge PPE (Pay Per Event) actor.

Auction.com blocks all direct scraping (Incapsula WAF), so we use the
Apify cloud platform to run a headless browser that bypasses the WAF.

Cost: ~$0.08 per run (5 properties) on free tier.
Free tier gives $5 in credits — enough for ~60 runs / ~300 properties.

Requires an Apify API token stored in .api_keys.json as "apify_token"
or set as the APIFY_TOKEN environment variable.

Sign up free at: https://console.apify.com/sign-up
Get your token at: https://console.apify.com/account/integrations

API notes:
  - Actor ID uses tilde format: parseforge~auction-com-property-scraper-ppe
  - Input field is "startUrl" (singular string), NOT "startUrls" (array)
  - Returns fields: street_description, municipality, country_primary_subdivision,
    postal_code, opening_bid, est_resale_value, beds, baths, sqft, etc.

Data flow:
  search_auctions(state, ...) → List[Dict]  (raw property dicts)
  ↓
  Fed into auction_fetcher._build_property_from_raw() via source="auctioncom"

REST API docs: https://docs.apify.com/api/v2
Actor: https://apify.com/parseforge/auction-com-property-scraper-ppe
"""

import json
import ssl
import time
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
    """Check if Apify API token is configured."""
    return bool(APIFY_TOKEN)


def search_auctions(states: List[str] = None,
                     counties: List[tuple] = None,
                     max_items: int = None,
                     timeout: int = None,
                     progress: bool = True) -> List[Dict]:
    """
    Search Auction.com for foreclosure properties via Apify.

    The PPE actor accepts one URL per run via "startUrl" (singular).

    If `counties` is provided, runs county-level URLs (cheaper & more targeted).
    Otherwise falls back to state-level URLs.

    Args:
        states: List of full state names (e.g., ["Oregon"]).  Fallback if no counties.
        counties: List of (county_slug, state_abbrev) tuples.
                  e.g., [("deschutes", "or"), ("jackson", "or")]
                  URL: https://www.auction.com/residential/{st}/{county}-county
        max_items: Max properties per Apify run
        timeout: Seconds to wait for each Apify run
        progress: Print progress
    """
    if not APIFY_TOKEN:
        if progress:
            print("      ⚠ No Apify API token configured")
            print("        Sign up free: https://console.apify.com/sign-up")
            print("        Add 'apify_token' to .api_keys.json")
        return []

    if max_items is None:
        max_items = MAX_ITEMS

    if timeout is None:
        timeout = TIMEOUT

    all_results = []

    # Prefer county-level URLs (cheaper, more targeted)
    if counties:
        for county_slug, state_abbrev in counties:
            url = f"https://www.auction.com/residential/{state_abbrev.lower()}/{county_slug.lower()}-county"
            state_full = STATE_ABBREV.get(state_abbrev.upper(), state_abbrev)
            label = f"{county_slug.title()} County, {state_abbrev.upper()}"

            if progress:
                print(f"      Searching {label} on Auction.com...")

            actor_input = {
                "startUrl": url,
                "maxItems": max_items,
            }

            raw_items = _run_actor_async(actor_input, timeout, progress)

            count = 0
            for item in raw_items:
                parsed = _parse_result(item)
                if parsed:
                    all_results.append(parsed)
                    count += 1

            if progress:
                print(f"      {label}: {count} listings")
    else:
        # Fallback: state-level URLs (broader, more expensive)
        if states is None:
            states = ["Oregon"]

        for state in states:
            url = AUCTION_STATE_URLS.get(state)
            if not url:
                continue

            if progress:
                print(f"      Searching {state} on Auction.com...")

            actor_input = {
                "startUrl": url,
                "maxItems": max_items,
            }

            raw_items = _run_actor_async(actor_input, timeout, progress)

            for item in raw_items:
                parsed = _parse_result(item)
                if parsed:
                    all_results.append(parsed)

            if progress:
                print(f"      {state}: {len(raw_items)} Auction.com listings")

    if progress:
        print(f"      Auction.com total: {len(all_results)} properties returned")

    return all_results


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


def _parse_result(item: dict) -> Optional[Dict]:
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
    if price <= 0:
        return None

    # Estimated resale value (Auction.com provides this — great for ARV)
    est_resale = _safe_float(item.get("est_resale_value"))

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
    """Check Apify API configuration and credit balance."""
    if not APIFY_TOKEN:
        return {"configured": False, "message": "No API token set"}

    ctx = ssl.create_default_context()
    try:
        url = f"{APIFY_BASE}/users/me?token={APIFY_TOKEN}"
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            user = data.get("data", {})
            plan = user.get("plan", {}).get("id", "unknown")
            return {
                "configured": True,
                "username": user.get("username", ""),
                "plan": plan,
                "message": f"Connected as {user.get('username', '?')} ({plan} plan)",
            }
    except HTTPError as e:
        if e.code == 401:
            return {"configured": False, "message": "Invalid API token"}
        return {"configured": False, "message": f"API error: {e.code}"}
    except Exception as e:
        return {"configured": False, "message": f"Connection error: {e}"}


# --- CLI test ---
if __name__ == "__main__":
    import sys

    if not APIFY_TOKEN:
        print("No Apify API token configured!")
        print()
        print("To set up:")
        print("  1. Sign up free: https://console.apify.com/sign-up")
        print("  2. Get your token: https://console.apify.com/account/integrations")
        print("  3. Add to .api_keys.json:  {\"apify_token\": \"your_token_here\"}")
        print("  OR set env var:  export APIFY_TOKEN=your_token_here")
        sys.exit(1)

    status = get_status()
    print(f"Apify status: {status['message']}")
    print()

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
            print(f"     Bid: ${prop['sale_amount']:,.0f}  |  "
                  f"Est Value: ${prop.get('estimated_value', 0):,.0f}  |  "
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
