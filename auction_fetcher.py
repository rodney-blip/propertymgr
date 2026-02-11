"""
Real Auction Property Fetcher

Discovers actual foreclosure / pre-foreclosure / distressed properties
using ATTOM and BatchData APIs, then enriches them with valuations and
neighborhood scores.

Data flow:
    1. For each target city/zip in config.REGION_DEFINITIONS:
       a. BatchData property/search → find pre-foreclosure filings
       b. ATTOM sale/snapshot       → find recent distressed sales
       c. ATTOM property/snapshot   → discover properties in the area
    2. De-duplicate by address
    3. Enrich each property with AVM (ATTOM), foreclosure context (BatchData),
       and neighborhood score (Census)
    4. Build Property objects with calculate_metrics()

Usage:
    from auction_fetcher import fetch_real_properties
    properties = fetch_real_properties()          # all target cities
    properties = fetch_real_properties(limit=50)  # cap total results
"""

import time
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from models import Property
import config

# Lazy imports to avoid loading modules when keys aren't set
_attom = None
_batchdata = None
_census = None


def _get_attom():
    global _attom
    if _attom is None:
        import api_attom
        _attom = api_attom
    return _attom


def _get_batchdata():
    global _batchdata
    if _batchdata is None:
        import api_batchdata
        _batchdata = api_batchdata
    return _batchdata


def _get_census():
    global _census
    if _census is None:
        import api_census
        _census = api_census
    return _census


def _normalize_address(address: str) -> str:
    """Normalize an address string for dedup comparison."""
    return " ".join(address.upper().split())


def _pick_zip_sample(max_zips: int = 12) -> List[tuple]:
    """
    Pick a representative sample of (city, state, zip_code, region) tuples
    from REGION_DEFINITIONS so we don't exhaust API quotas scanning every ZIP.
    """
    all_zips = []
    for state, regions in config.REGION_DEFINITIONS.items():
        for region, cities in regions.items():
            for city, zip_code in cities:
                all_zips.append((city, state, zip_code, region))

    # If we have fewer zips than the limit, use all of them
    if len(all_zips) <= max_zips:
        return all_zips

    # Otherwise, take a balanced sample across states
    by_state = {}
    for entry in all_zips:
        by_state.setdefault(entry[1], []).append(entry)

    sample = []
    per_state = max(1, max_zips // len(by_state))
    for state, entries in by_state.items():
        random.shuffle(entries)
        sample.extend(entries[:per_state])

    # Fill remaining slots
    remaining = [e for e in all_zips if e not in sample]
    random.shuffle(remaining)
    sample.extend(remaining[: max_zips - len(sample)])

    return sample[:max_zips]


def _search_batchdata_foreclosures(city: str, state: str,
                                    min_value: int = None,
                                    max_value: int = None) -> List[Dict]:
    """Search BatchData for pre-foreclosure properties in a city."""
    bd = _get_batchdata()
    if not config.API_KEYS.get("batchdata"):
        return []

    # Use both the foreclosure-specific search and general area search
    results = bd.search_foreclosures(city, state, min_value, max_value) or []

    # Also try the general property search by area
    area_results = bd.search_properties_by_area(f"{city}, {state}", take=25)
    if area_results:
        results.extend(area_results)

    return results


def _search_attom_sales(zip_code: str,
                         min_price: int = None,
                         max_price: int = None) -> List[Dict]:
    """Search ATTOM for recent sales (including distressed/REO) in a ZIP."""
    attom = _get_attom()
    if not config.API_KEYS.get("attom_rapidapi"):
        return []

    results = attom.search_sales_by_zip(
        zip_code, min_price=min_price, max_price=max_price, page_size=20
    )
    return results or []


def _search_attom_properties(zip_code: str) -> List[Dict]:
    """Search ATTOM for properties in a ZIP code."""
    attom = _get_attom()
    if not config.API_KEYS.get("attom_rapidapi"):
        return []

    results = attom.search_properties_by_zip(zip_code, page_size=20)
    return results or []


def _build_property_from_raw(raw: Dict, source: str,
                               city_hint: str, state_hint: str,
                               zip_hint: str, region_hint: str,
                               index: int) -> Optional[Property]:
    """
    Convert a raw API result dict into a Property object.
    Fills in reasonable defaults for any missing fields.
    """
    address = raw.get("address", "").strip()
    if not address:
        return None

    city = raw.get("city", city_hint) or city_hint
    state = raw.get("state", state_hint) or state_hint
    zip_code = raw.get("zip_code", zip_hint) or zip_hint

    # Determine region from config lookup, fallback to hint
    region = config.CITY_TO_REGION.get((state, city), region_hint)

    # Pricing — use what we have, mark for enrichment later
    auction_price = (
        raw.get("sale_amount")
        or raw.get("default_amount")
        or raw.get("assessed_value")
        or raw.get("market_value")
    )
    if auction_price:
        auction_price = float(auction_price)
    else:
        # Can't price this property at all — skip it
        return None

    # Estimated ARV: if we have market_value, use it; otherwise estimate
    estimated_arv = raw.get("market_value") or raw.get("assessed_value")
    if estimated_arv:
        estimated_arv = float(estimated_arv) * 1.1  # small markup for ARV
    else:
        # Rough estimate from $/sqft for the state
        sqft = raw.get("sqft") or 1800
        price_per_sqft = config.PRICE_PER_SQFT.get(state, 180)
        estimated_arv = float(sqft) * price_per_sqft

    # Repair estimate based on age and a percentage of price
    year_built = raw.get("year_built") or 1990
    if isinstance(year_built, str):
        try:
            year_built = int(year_built)
        except ValueError:
            year_built = 1990
    age = datetime.now().year - year_built
    if age > 40:
        repair_pct = 0.20
    elif age > 25:
        repair_pct = 0.15
    elif age > 10:
        repair_pct = 0.10
    else:
        repair_pct = 0.05
    estimated_repairs = auction_price * repair_pct

    # Property details
    bedrooms = raw.get("bedrooms") or 3
    bathrooms = raw.get("bathrooms") or 2.0
    sqft = raw.get("sqft") or 1800
    lot_size = raw.get("lot_size") or 0.20

    if isinstance(bedrooms, str):
        try: bedrooms = int(bedrooms)
        except: bedrooms = 3
    if isinstance(bathrooms, str):
        try: bathrooms = float(bathrooms)
        except: bathrooms = 2.0
    if isinstance(sqft, str):
        try: sqft = int(float(sqft))
        except: sqft = 1800
    if isinstance(lot_size, str):
        try: lot_size = float(lot_size)
        except: lot_size = 0.20

    # Auction date — use what's in the data, or project forward
    auction_date = raw.get("auction_date") or raw.get("sale_date")
    if not auction_date:
        days_ahead = random.randint(7, 45)
        auction_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # Foreclosure context
    foreclosing_entity = raw.get("foreclosing_entity") or raw.get("seller_name") or raw.get("lender_name")
    total_debt = raw.get("total_debt") or raw.get("default_amount") or raw.get("mortgage_amount")
    if total_debt:
        total_debt = float(total_debt)
    loan_type = raw.get("loan_type")
    default_date = raw.get("default_date") or raw.get("recording_date")
    foreclosure_stage = raw.get("foreclosure_stage") or raw.get("filing_type")

    # Determine source platform
    platform = "Bank Foreclosure"
    if source == "batchdata":
        platform = "BatchData Pre-Foreclosure"
    elif source == "attom_sale":
        sale_type = raw.get("sale_type", "")
        if sale_type and "foreclosure" in str(sale_type).lower():
            platform = "Bank Foreclosure"
        elif sale_type and "reo" in str(sale_type).lower():
            platform = "Bank Foreclosure"
        else:
            platform = "Auction.com"  # likely auction source
    elif source == "attom_prop":
        platform = "Auction.com"

    # Determine platform URL
    platform_url = config.AUCTION_PLATFORM_URLS.get(platform)
    property_url = f"{platform_url}/listing/REAL-{index}" if platform_url else None

    # Bank contact URL
    bank_contact_url = None
    if foreclosing_entity:
        bank_contact_url = config.BANK_CONTACT_URLS.get(foreclosing_entity)

    # Neighborhood score placeholder (will be enriched by Census)
    neighborhood_score = 5

    description = (
        f"Real {source} listing in {city}, {state}. "
        f"{'Pre-foreclosure' if foreclosure_stage else 'Distressed sale'} opportunity."
    )

    try:
        prop = Property(
            id=f"REAL-{index:04d}",
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            region=region,
            auction_price=round(auction_price, 2),
            estimated_arv=round(estimated_arv, 2),
            estimated_repairs=round(estimated_repairs, 2),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sqft=sqft,
            lot_size=lot_size,
            year_built=year_built,
            property_type="Single Family",
            auction_date=auction_date,
            auction_platform=platform,
            description=description,
            neighborhood_score=neighborhood_score,
            foreclosing_entity=foreclosing_entity,
            total_debt=total_debt,
            loan_type=loan_type,
            default_date=default_date,
            foreclosure_stage=foreclosure_stage,
            property_url=property_url,
            bank_contact_url=bank_contact_url,
        )
        prop.calculate_metrics()
        return prop
    except Exception as e:
        print(f"   Error building property from {source}: {e}")
        return None


def fetch_real_properties(limit: int = 75,
                           max_zips: int = 12,
                           enrich_neighborhood: bool = True,
                           progress: bool = True) -> List[Property]:
    """
    Fetch real properties from ATTOM and BatchData APIs.

    Args:
        limit: Maximum number of properties to return
        max_zips: Number of ZIP codes to sample from config regions
        enrich_neighborhood: Whether to run Census API for neighborhood scores
        progress: Print progress updates

    Returns:
        List of Property objects with metrics calculated
    """
    has_attom = bool(config.API_KEYS.get("attom_rapidapi"))
    has_batchdata = bool(config.API_KEYS.get("batchdata"))

    if not has_attom and not has_batchdata:
        print("   ⚠️  No API keys configured for real data. Set attom_rapidapi or batchdata in .api_keys.json")
        return []

    zip_sample = _pick_zip_sample(max_zips)

    if progress:
        print(f"   Searching {len(zip_sample)} ZIP codes across {len(config.TARGET_STATES)} states...")
        sources = []
        if has_batchdata:
            sources.append("BatchData")
        if has_attom:
            sources.append("ATTOM")
        print(f"   Data sources: {', '.join(sources)}")

    # Collect raw results, keyed by normalized address for dedup
    seen_addresses: Set[str] = set()
    raw_results: List[tuple] = []  # (raw_dict, source_str, city, state, zip, region)

    for i, (city, state, zip_code, region) in enumerate(zip_sample):
        if len(raw_results) >= limit * 2:
            break  # We have enough candidates

        if progress:
            print(f"   [{i+1}/{len(zip_sample)}] Scanning {city}, {state} ({zip_code})...")

        # --- BatchData: pre-foreclosure search ---
        if has_batchdata:
            try:
                bd_results = _search_batchdata_foreclosures(
                    city, state,
                    min_value=config.MIN_AUCTION_PRICE,
                    max_value=config.MAX_AUCTION_PRICE,
                )
                for r in bd_results:
                    addr_key = _normalize_address(r.get("address", ""))
                    if addr_key and addr_key not in seen_addresses:
                        seen_addresses.add(addr_key)
                        raw_results.append((r, "batchdata", city, state, zip_code, region))
                if progress and bd_results:
                    print(f"      BatchData: {len(bd_results)} pre-foreclosure listings")
            except Exception as e:
                print(f"      BatchData error: {e}")

        # --- ATTOM: recent sales in ZIP ---
        if has_attom:
            try:
                sale_results = _search_attom_sales(
                    zip_code,
                    min_price=config.MIN_AUCTION_PRICE,
                    max_price=config.MAX_AUCTION_PRICE,
                )
                for r in sale_results:
                    addr_key = _normalize_address(r.get("address", ""))
                    if addr_key and addr_key not in seen_addresses:
                        seen_addresses.add(addr_key)
                        raw_results.append((r, "attom_sale", city, state, zip_code, region))
                if progress and sale_results:
                    print(f"      ATTOM sales: {len(sale_results)} recent sales")
            except Exception as e:
                print(f"      ATTOM sale error: {e}")

            # --- ATTOM: property snapshot (all properties in ZIP) ---
            try:
                prop_results = _search_attom_properties(zip_code)
                for r in prop_results:
                    addr_key = _normalize_address(r.get("address", ""))
                    if addr_key and addr_key not in seen_addresses:
                        seen_addresses.add(addr_key)
                        raw_results.append((r, "attom_prop", city, state, zip_code, region))
                if progress and prop_results:
                    print(f"      ATTOM properties: {len(prop_results)} in ZIP")
            except Exception as e:
                print(f"      ATTOM property error: {e}")

    if progress:
        print(f"\n   Raw candidates found: {len(raw_results)}")

    # --- Build Property objects ---
    properties = []
    for idx, (raw, source, city, state, zip_code, region) in enumerate(raw_results):
        if len(properties) >= limit:
            break

        prop = _build_property_from_raw(
            raw, source, city, state, zip_code, region, index=idx + 1
        )
        if prop is not None:
            # Price filter
            if prop.auction_price < config.MIN_AUCTION_PRICE:
                continue
            if prop.auction_price > config.MAX_AUCTION_PRICE:
                continue
            properties.append(prop)

    if progress:
        print(f"   Properties after filtering: {len(properties)}")

    # --- Enrich with Census neighborhood scores ---
    if enrich_neighborhood and properties:
        if progress:
            print("   Enriching with Census neighborhood scores...")
        census = _get_census()
        cache: Dict[str, Optional[int]] = {}
        for prop in properties:
            if prop.zip_code in cache:
                score = cache[prop.zip_code]
            else:
                score = census.calculate_neighborhood_score(prop.zip_code)
                cache[prop.zip_code] = score
            if score is not None:
                prop.neighborhood_score = score
                prop.calculate_metrics()

    if progress:
        print(f"   ✅ Fetched {len(properties)} real properties")

    # If we didn't get enough properties (e.g. rate limits, sandbox),
    # explain what happened
    if len(properties) < limit // 2:
        if progress:
            print()
            if not has_attom:
                print("   ℹ️  No ATTOM API key — add attom_rapidapi to .api_keys.json")
            elif len(properties) == 0:
                print("   ℹ️  ATTOM may be rate-limited (500 calls/day on free tier)")
                print("      Rate limits reset daily. Try again later.")
            if has_batchdata:
                # Check if sandbox
                from api_batchdata import search_properties_by_area
                test = search_properties_by_area("Portland, OR", take=1)
                if test and len(test) == 1 and test[0].get("state") not in config.TARGET_STATES:
                    print("   ℹ️  BatchData key appears to be a sandbox/demo token.")
                    print("      Upgrade at https://app.batchdata.com for real property data.")

    return properties
