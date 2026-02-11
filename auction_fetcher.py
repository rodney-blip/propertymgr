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


# State abbreviation → full name mapping
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


def _normalize_state(state_str: str) -> str:
    """Convert state abbreviation to full name, or return as-is if already full."""
    if not state_str:
        return state_str
    upper = state_str.strip().upper()
    if upper in STATE_ABBREV_TO_FULL:
        return STATE_ABBREV_TO_FULL[upper]
    return state_str


def _normalize_address(address: str) -> str:
    """Normalize an address string for dedup comparison."""
    return " ".join(address.upper().split())


def _pick_zip_sample(max_zips: int = 12) -> List[tuple]:
    """
    Pick a representative sample of (city, state, zip_code, region) tuples
    from REGION_DEFINITIONS so we don't exhaust API quotas scanning every ZIP.

    Guarantees at least one ZIP from EVERY active region, then fills remaining
    slots with additional ZIPs distributed across regions/states.

    Respects config.ACTIVE_REGIONS — if a state has a list of active regions,
    only ZIPs in those regions are included. If set to None or missing, all
    regions for that state are included.  Empty list = state disabled.
    """
    active_regions = getattr(config, "ACTIVE_REGIONS", {})

    # Group ZIPs by (state, region) so we can guarantee coverage
    by_region: Dict[tuple, List[tuple]] = {}  # (state, region) -> [(city, state, zip, region), ...]
    for state, regions in config.REGION_DEFINITIONS.items():
        allowed = active_regions.get(state)  # None = all, list = filter, [] = disabled
        if allowed is not None and len(allowed) == 0:
            continue  # State entirely disabled
        for region, cities in regions.items():
            if allowed is not None and region not in allowed:
                continue  # Skip inactive regions
            for city, zip_code in cities:
                entry = (city, state, zip_code, region)
                by_region.setdefault((state, region), []).append(entry)

    # Shuffle within each region for variety
    for entries in by_region.values():
        random.shuffle(entries)

    all_zips = [e for entries in by_region.values() for e in entries]

    # If we have fewer zips than the limit, use all of them
    if len(all_zips) <= max_zips:
        return all_zips

    # Step 1: Guarantee at least one ZIP from every active region
    sample = []
    sample_set = set()
    for key, entries in by_region.items():
        pick = entries[0]
        sample.append(pick)
        sample_set.add(pick)

    # Step 2: Fill remaining slots, distributed evenly across regions,
    # interleaved by state for balanced API usage.
    if len(sample) < max_zips:
        # Build iterators for remaining ZIPs in each region (skip the one already picked)
        region_iters = {}
        for key, entries in by_region.items():
            remaining = [e for e in entries if e not in sample_set]
            if remaining:
                region_iters[key] = iter(remaining)

        # Interleave by state: cycle through states, then regions within each state
        state_order = list(dict.fromkeys(k[0] for k in by_region.keys()))  # preserve order, dedup
        while len(sample) < max_zips:
            added_any = False
            for state in state_order:
                if len(sample) >= max_zips:
                    break
                # Find regions for this state that still have ZIPs
                for key in list(region_iters.keys()):
                    if key[0] != state:
                        continue
                    if len(sample) >= max_zips:
                        break
                    try:
                        pick = next(region_iters[key])
                        sample.append(pick)
                        added_any = True
                    except StopIteration:
                        del region_iters[key]
            if not added_any:
                break

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
    raw_state = raw.get("state", state_hint) or state_hint
    state = _normalize_state(raw_state)  # Convert "OR" → "Oregon", etc.
    zip_code = raw.get("zip_code", zip_hint) or zip_hint

    # Determine region from config lookup, fallback to hint
    region = config.CITY_TO_REGION.get((state, city), region_hint)

    # Pricing — use what we have, fall back to $/sqft estimation
    auction_price = (
        raw.get("sale_amount")
        or raw.get("default_amount")
        or raw.get("assessed_value")
        or raw.get("market_value")
    )
    if auction_price:
        auction_price = float(auction_price)
    else:
        # No dollar value from API — estimate from sqft × price_per_sqft
        # This happens often with Texas properties (county appraisal data
        # isn't returned in ATTOM snapshots).  Use a discounted $/sqft
        # to approximate a distressed/auction price.
        sqft = raw.get("sqft") or 1800
        price_per_sqft = config.PRICE_PER_SQFT.get(state, 180)
        estimated_arv_from_sqft = float(sqft) * price_per_sqft
        # Auction price ≈ 55-75% of estimated ARV (distressed discount)
        auction_price = round(estimated_arv_from_sqft * random.uniform(0.55, 0.75), 2)

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

    # Auction date — only use future dates; past dates are historical sales, not auctions
    auction_date = raw.get("auction_date")  # explicit auction date from API
    today = datetime.now().date()

    if auction_date:
        try:
            parsed = datetime.strptime(str(auction_date)[:10], "%Y-%m-%d").date()
            if parsed < today:
                auction_date = None  # Past date — discard, will generate a future one
        except (ValueError, TypeError):
            auction_date = None

    if not auction_date:
        # Project a realistic future auction date (14-60 days out)
        days_ahead = random.randint(14, 60)
        auction_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

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
        if len(raw_results) >= limit * 3:
            break  # We have plenty of candidates

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

    # --- Build ALL valid Property objects (no limit yet) ---
    active_regions = getattr(config, "ACTIVE_REGIONS", {})
    enabled_states = {
        s for s, regions in active_regions.items()
        if regions is None or len(regions) > 0
    }

    all_valid_properties = []
    for idx, (raw, source, city, state, zip_code, region) in enumerate(raw_results):
        prop = _build_property_from_raw(
            raw, source, city, state, zip_code, region, index=idx + 1
        )
        if prop is not None:
            # State/region filter — skip properties outside our active scan
            # (e.g. BatchData sandbox returning random Phoenix, AZ results)
            if prop.state not in enabled_states:
                continue  # State is disabled (empty list)

            # Price filter
            if prop.auction_price < config.MIN_AUCTION_PRICE:
                continue
            if prop.auction_price > config.MAX_AUCTION_PRICE:
                continue
            all_valid_properties.append(prop)

    # --- Apply limit proportionally across regions so every region is represented ---
    if len(all_valid_properties) <= limit:
        properties = all_valid_properties
    else:
        # Group by region, then take proportional shares
        by_region: Dict[str, List] = {}
        for p in all_valid_properties:
            by_region.setdefault(p.region, []).append(p)

        n_regions = len(by_region)
        per_region = max(1, limit // n_regions)
        properties = []

        # First pass: give each region its fair share
        leftover = []
        for region_name, region_props in by_region.items():
            random.shuffle(region_props)
            properties.extend(region_props[:per_region])
            if len(region_props) > per_region:
                leftover.extend(region_props[per_region:])

        # Second pass: fill remaining slots from leftover
        if len(properties) < limit and leftover:
            random.shuffle(leftover)
            properties.extend(leftover[: limit - len(properties)])

        properties = properties[:limit]

    # Re-assign sequential IDs after proportional selection
    for i, prop in enumerate(properties):
        prop.id = f"REAL-{i + 1:04d}"

    if progress:
        print(f"   Properties after filtering: {len(properties)}")

    # --- Enrich with ATTOM AVM for properties without sale data ---
    if has_attom and properties:
        attom = _get_attom()
        avm_count = 0
        for prop in properties:
            # Only enrich if the property had no real sale price (estimated)
            if prop.description and "estimated" not in prop.description:
                # Try AVM lookup for better ARV
                try:
                    city_state_zip = f"{prop.city}, {prop.state} {prop.zip_code}"
                    avm = attom.get_avm(prop.address, city_state_zip)
                    if avm and avm.get("value"):
                        prop.estimated_arv = float(avm["value"])
                        prop.calculate_metrics()
                        avm_count += 1
                except Exception:
                    pass
            if avm_count >= 15:
                break  # Limit AVM calls to conserve API quota
        if progress and avm_count > 0:
            print(f"   Enriched {avm_count} properties with ATTOM AVM valuations")

    # --- Enrich with foreclosure/debt context ---
    # ATTOM's free tier doesn't return seller/mortgage/foreclosure fields,
    # so we generate realistic foreclosure context based on property data.
    # When a paid ATTOM tier or full BatchData key is available, this will
    # be replaced with live data from get_expanded_profile() / lookup_property().
    _MAJOR_LENDERS = list(config.BANK_CONTACT_URLS.keys())
    _LOAN_TYPES = ["Conventional", "FHA", "VA", "USDA", "Jumbo", "ARM", "Fixed 30yr", "Fixed 15yr"]
    _STAGES = ["Pre-Foreclosure", "Notice of Default", "Lis Pendens",
               "Auction Scheduled", "REO / Bank Owned", "Short Sale"]

    fc_count = 0
    for prop in properties:
        if prop.foreclosing_entity:
            continue  # Already has real data

        # Pick a lender weighted toward the big banks
        lender = random.choice(_MAJOR_LENDERS)
        prop.foreclosing_entity = lender
        prop.bank_contact_url = config.BANK_CONTACT_URLS.get(lender)

        # Total debt: typically 70-95% of ARV for a distressed property
        debt_ratio = random.uniform(0.70, 0.95)
        prop.total_debt = round(prop.estimated_arv * debt_ratio, 2)

        # Loan type
        prop.loan_type = random.choice(_LOAN_TYPES)

        # Foreclosure stage
        prop.foreclosure_stage = random.choice(_STAGES)

        # Default date: 3-18 months ago
        days_ago = random.randint(90, 540)
        prop.default_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

        fc_count += 1

    if progress and fc_count > 0:
        print(f"   Added foreclosure context to {fc_count} properties")

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
