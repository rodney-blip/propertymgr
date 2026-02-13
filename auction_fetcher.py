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
_redfin = None
_sheriff = None
_auctioncom = None
_zillow = None


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


def _get_redfin():
    """Lazy-load the Redfin scraper module."""
    global _redfin
    if _redfin is None:
        try:
            import scraper_redfin
            _redfin = scraper_redfin
        except ImportError:
            _redfin = False  # Mark as unavailable
    return _redfin if _redfin is not False else None


def _get_sheriff():
    """Lazy-load the Oregon Sheriff's Sales scraper module."""
    global _sheriff
    if _sheriff is None:
        try:
            import scraper_orsheriff
            _sheriff = scraper_orsheriff
        except ImportError:
            _sheriff = False  # Mark as unavailable
    return _sheriff if _sheriff is not False else None


def _get_auctioncom():
    """Lazy-load the Auction.com scraper module (via Apify)."""
    global _auctioncom
    if _auctioncom is None:
        try:
            import scraper_auctioncom
            _auctioncom = scraper_auctioncom
        except ImportError:
            _auctioncom = False
    return _auctioncom if _auctioncom is not False else None


def _get_zillow():
    """Lazy-load the Zillow Zestimate scraper module (via Apify)."""
    global _zillow
    if _zillow is None:
        try:
            import scraper_zillow
            _zillow = scraper_zillow
        except ImportError:
            _zillow = False
    return _zillow if _zillow is not False else None


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
    addr = " ".join(address.upper().split())
    # Expand common abbreviations for better dedup
    _abbrevs = {
        " CIR ": " CIRCLE ", " DR ": " DRIVE ", " ST ": " STREET ",
        " AVE ": " AVENUE ", " RD ": " ROAD ", " LN ": " LANE ",
        " CT ": " COURT ", " PL ": " PLACE ", " BLVD ": " BOULEVARD ",
        " HWY ": " HIGHWAY ", " PKY ": " PARKWAY ", " TRL ": " TRAIL ",
    }
    addr = addr + " "  # pad end so trailing abbrevs match
    for abbr, full in _abbrevs.items():
        addr = addr.replace(abbr, full)
    return addr.strip()


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

    # Normalize city to title case for config lookup (Auction.com returns "BEND", config has "Bend")
    city_lookup = city.title() if city else city

    # Determine region from config lookup, fallback to hint
    region = config.CITY_TO_REGION.get((state, city_lookup), region_hint)

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

    # Estimated ARV: use best available data source
    # Auction.com provides est_resale_value (their own ARV estimate)
    estimated_arv = (
        raw.get("estimated_value")   # Auction.com est_resale_value
        or raw.get("market_value")
        or raw.get("assessed_value")
    )
    if estimated_arv:
        estimated_arv = float(estimated_arv)
        # Only markup non-Auction.com values (Auction.com's estimate is already market value)
        if source != "auctioncom":
            estimated_arv *= 1.1
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
    # Repairs removed — unknowable without physical inspection.
    # Set to 0; users budget repairs separately after their own walkthrough.
    estimated_repairs = 0.0

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

    # Auction date handling
    auction_date = raw.get("auction_date")  # explicit auction date from API
    auction_date_is_past = False
    today = datetime.now().date()

    if auction_date:
        try:
            parsed = datetime.strptime(str(auction_date)[:10], "%Y-%m-%d").date()
            if parsed < today:
                auction_date_is_past = True
                # Keep the real date — don't fake it. Mark as past auction.
        except (ValueError, TypeError):
            auction_date = None

    if not auction_date:
        if source in ("auctioncom", "sheriff", "redfin"):
            # Real data sources: leave blank rather than fabricate
            auction_date = ""
        else:
            # Mock/API sources: project a future date
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

    # Determine source platform / data origin
    platform = "ATTOM Property"
    data_source_tag = "attom"
    if source == "batchdata":
        platform = "BatchData Pre-Foreclosure"
        data_source_tag = "batchdata"
    elif source == "attom_sale":
        sale_type = raw.get("sale_type", "")
        if sale_type and "foreclosure" in str(sale_type).lower():
            platform = "ATTOM Foreclosure"
        elif sale_type and "reo" in str(sale_type).lower():
            platform = "ATTOM REO"
        else:
            platform = "ATTOM Sale"
        data_source_tag = "attom"
    elif source == "attom_prop":
        platform = "ATTOM Property"
        data_source_tag = "attom"
    elif source == "redfin":
        sale_type_str = raw.get("sale_type", "")
        if sale_type_str and "bank" in sale_type_str.lower():
            platform = "Redfin MLS Bank-Owned"
        else:
            platform = "Redfin MLS Foreclosure"
        data_source_tag = "redfin"
        # Redfin provides real foreclosure context
        if not foreclosing_entity:
            foreclosing_entity = "Listed on MLS"
        if not foreclosure_stage:
            foreclosure_stage = "MLS Listed"
    elif source == "sheriff":
        platform = "Oregon Sheriff Sale"
        data_source_tag = "sheriff"
        # Sheriff sales have real foreclosure context from case title
        if not foreclosure_stage:
            foreclosure_stage = raw.get("foreclosure_stage", "Sheriff Sale Scheduled")
    elif source == "auctioncom":
        auction_type = raw.get("auction_type", "Foreclosure")
        if "bank" in auction_type.lower():
            platform = "Auction.com Bank-Owned"
        else:
            platform = "Auction.com Foreclosure"
        data_source_tag = "auctioncom"
        if not foreclosure_stage:
            foreclosure_stage = "Auction Scheduled"
        if not foreclosing_entity:
            foreclosing_entity = "Listed on Auction.com"

    # Build a useful search URL.
    # For Redfin properties, use the actual listing URL from the CSV data.
    # For Sheriff sales, use the listing detail page or PDF.
    # For other sources, use Zillow address search.
    import urllib.parse
    if source == "redfin" and raw.get("property_url"):
        property_url = raw["property_url"]
    elif source == "sheriff" and raw.get("listing_url"):
        property_url = raw["listing_url"]
    elif source == "auctioncom" and raw.get("property_url"):
        property_url = raw["property_url"]
    else:
        search_addr = f"{address}, {city}, {state} {zip_code}"
        property_url = "https://www.zillow.com/homes/" + urllib.parse.quote(search_addr) + "_rb/"

    # Bank contact URL
    bank_contact_url = None
    if foreclosing_entity and foreclosing_entity != "Listed on MLS":
        bank_contact_url = config.BANK_CONTACT_URLS.get(foreclosing_entity)

    # Neighborhood score placeholder (will be enriched by Census)
    neighborhood_score = 5

    # Use real HOA data from Redfin if available
    hoa_monthly_val = None
    if source == "redfin" and raw.get("hoa_monthly"):
        hoa_monthly_val = raw["hoa_monthly"]

    # Use real lat/lng from Redfin if available
    latitude_val = raw.get("latitude") if source == "redfin" else None
    longitude_val = raw.get("longitude") if source == "redfin" else None

    # Days on market info for Redfin properties
    days_on_market = raw.get("days_on_market", 0) if source == "redfin" else 0

    if source == "auctioncom":
        atype = raw.get("auction_type", "Foreclosure")
        description = (
            f"Auction.com {atype.lower()} in {city}, {state}. "
            f"Real auction listing data via Apify."
        )
        if raw.get("auction_date"):
            description += f" Auction date: {raw['auction_date']}."
    elif source == "sheriff":
        county_name = raw.get("county", "")
        description = (
            f"Sheriff's sale in {city}, {state}. "
            f"Judicial foreclosure — {county_name} County courthouse auction."
        )
        if raw.get("foreclosing_entity"):
            description += f" Plaintiff: {raw['foreclosing_entity']}."
        if raw.get("pdf_url"):
            description += f" Notice of Sale PDF available."
    elif source == "redfin":
        description = (
            f"MLS-listed foreclosure in {city}, {state}. "
            f"Real listing data from Redfin."
        )
        if days_on_market:
            description += f" {days_on_market} days on market."
        if raw.get("mls_number"):
            description += f" MLS# {raw['mls_number']}."
    else:
        description = (
            f"Real {source} listing in {city}, {state}. "
            f"{'Pre-foreclosure' if foreclosure_stage else 'Distressed sale'} opportunity."
        )

    # ID prefix based on data source
    if source == "auctioncom":
        id_prefix = "AUCT"
    elif source == "sheriff":
        id_prefix = "SHRF"
    elif source == "redfin":
        id_prefix = "RDFN"
    else:
        id_prefix = "REAL"

    try:
        prop = Property(
            id=f"{id_prefix}-{index:04d}",
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
            data_source=data_source_tag,
        )
        # Mark past auctions
        if auction_date_is_past:
            prop.auction_date_is_past = True

        # Add optional fields from specific sources
        if source in ("sheriff", "auctioncom"):
            county_val = raw.get("county")
            if county_val:
                prop.county = county_val

        # Occupancy status from any real source
        occupancy_val = raw.get("occupancy_status")
        if occupancy_val:
            prop.occupancy_status = occupancy_val

        # Image URL from Auction.com
        image_val = raw.get("image_url")
        if image_val:
            prop.image_url = image_val

        if hoa_monthly_val:
            prop.hoa_monthly = hoa_monthly_val
        if latitude_val and latitude_val != 0:
            prop.latitude = latitude_val
        if longitude_val and longitude_val != 0:
            prop.longitude = longitude_val
        prop.calculate_metrics()
        return prop
    except Exception as e:
        print(f"   Error building property from {source}: {e}")
        return None


def fetch_real_properties(limit: int = 75,
                           max_zips: int = 12,
                           enrich_neighborhood: bool = True,
                           progress: bool = True,
                           sources: List[str] = None) -> List[Property]:
    """
    Fetch real properties from ATTOM, BatchData, and/or Redfin.

    Args:
        limit: Maximum number of properties to return
        max_zips: Number of ZIP codes to sample from config regions
        enrich_neighborhood: Whether to run Census API for neighborhood scores
        progress: Print progress updates
        sources: Which data sources to use. None = all available.
                 Options: ["attom", "batchdata", "redfin"]

    Returns:
        List of Property objects with metrics calculated
    """
    has_attom = bool(config.API_KEYS.get("attom_rapidapi"))
    has_batchdata = bool(config.API_KEYS.get("batchdata"))
    has_redfin = _get_redfin() is not None
    has_sheriff = _get_sheriff() is not None
    has_auctioncom = _get_auctioncom() is not None and _get_auctioncom().is_configured()

    # ATTOM enrichment is always available (for AVM, property detail, mortgage)
    # regardless of which search sources are active. Keep a separate flag.
    has_attom_enrich = has_attom

    # If sources specified, filter to only those (for SEARCH, not enrichment)
    if sources:
        if "attom" not in sources:
            has_attom = False
        if "batchdata" not in sources:
            has_batchdata = False
        if "redfin" not in sources:
            has_redfin = False
        if "sheriff" not in sources:
            has_sheriff = False
        if "auctioncom" not in sources:
            has_auctioncom = False

    if not has_attom and not has_batchdata and not has_redfin and not has_sheriff and not has_auctioncom:
        if sources and "redfin" in sources:
            print("   ⚠️  Redfin scraper module not found (scraper_redfin.py)")
        elif sources and "sheriff" in sources:
            print("   ⚠️  Sheriff scraper module not found (scraper_orsheriff.py)")
        elif sources and "auctioncom" in sources:
            print("   ⚠️  Auction.com requires an Apify API token")
            print("      Sign up free: https://console.apify.com/sign-up")
            print("      Add 'apify_token' to .api_keys.json")
        else:
            print("   ⚠️  No data sources available. Set API keys in .api_keys.json or use --scrape for Redfin")
        return []

    # Reset circuit breakers at the start of each run
    if has_redfin:
        redfin_mod = _get_redfin()
        redfin_mod.reset_circuit_breaker()
    if has_sheriff:
        sheriff_mod = _get_sheriff()
        sheriff_mod.reset_circuit_breaker()

    zip_sample = _pick_zip_sample(max_zips)

    if progress:
        print(f"   Searching {len(zip_sample)} ZIP codes across active regions...")
        active_sources = []
        if has_batchdata:
            active_sources.append("BatchData")
        if has_attom:
            active_sources.append("ATTOM")
        if has_redfin:
            active_sources.append("Redfin MLS")
        if has_sheriff:
            active_sources.append("OR Sheriff Sales")
        if has_auctioncom:
            active_sources.append("Auction.com (Apify)")
        print(f"   Data sources: {', '.join(active_sources)}")

    # Collect raw results, keyed by normalized address for dedup
    seen_addresses: Set[str] = set()
    raw_results: List[tuple] = []  # (raw_dict, source_str, city, state, zip, region)

    # --- Auction.com via Apify (county or state-based, runs before ZIP loop) ---
    if has_auctioncom:
        ac_mod = _get_auctioncom()
        ac_counties = getattr(config, "AUCTIONCOM_COUNTIES", [])
        ac_states = getattr(config, "AUCTIONCOM_STATES", ["Oregon"])
        ac_max = getattr(config, "AUCTIONCOM_MAX_ITEMS", 50)
        if ac_counties:
            county_labels = [f"{c[0].title()} Co, {c[1].upper()}" for c in ac_counties]
            if progress:
                print(f"   Fetching Auction.com listings via Apify ({', '.join(county_labels)})...")
            ac_results = ac_mod.search_auctions(
                counties=ac_counties, max_items=ac_max, progress=progress
            )
        else:
            if progress:
                print(f"   Fetching Auction.com listings via Apify ({', '.join(ac_states)})...")
            ac_results = ac_mod.search_auctions(
                states=ac_states, max_items=ac_max, progress=progress
            )
        for r in ac_results:
            addr_key = _normalize_address(r.get("address", ""))
            if addr_key and addr_key not in seen_addresses:
                seen_addresses.add(addr_key)
                raw_results.append((
                    r, "auctioncom",
                    r.get("city", ""),
                    r.get("state", ""),
                    r.get("zip_code", ""),
                    "",  # region will be resolved in _build_property_from_raw
                ))
        if progress and ac_results:
            print(f"      Total: {len(ac_results)} Auction.com listings\n")

    # --- Oregon Sheriff's Sales (county-based, runs before ZIP loop) ---
    if has_sheriff:
        sheriff_mod = _get_sheriff()
        counties = getattr(config, "SHERIFF_COUNTIES", ["deschutes"])
        if progress:
            print(f"   Scraping Oregon sheriff's sales ({len(counties)} counties)...")
        sheriff_results = sheriff_mod.scrape_all_counties(
            counties=counties, progress=progress
        )
        for r in sheriff_results:
            addr_key = _normalize_address(r.get("address", ""))
            if addr_key and addr_key not in seen_addresses:
                seen_addresses.add(addr_key)
                raw_results.append((
                    r, "sheriff",
                    r.get("city", ""),
                    r.get("state", "Oregon"),
                    r.get("zip_code", ""),
                    r.get("region", "Central Oregon"),
                ))
        if progress and sheriff_results:
            print(f"      Total: {len(sheriff_results)} sheriff's sale listings\n")

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

        # --- Redfin: MLS-listed foreclosures ---
        if has_redfin:
            redfin_mod = _get_redfin()
            if redfin_mod and not redfin_mod.get_circuit_breaker_status()["tripped"]:
                try:
                    redfin_results = redfin_mod.search_foreclosures_by_zip(
                        zip_code, city_hint=city, state_hint=state
                    )
                    added = 0
                    for r in redfin_results:
                        addr_key = _normalize_address(r.get("address", ""))
                        if addr_key and addr_key not in seen_addresses:
                            seen_addresses.add(addr_key)
                            raw_results.append((r, "redfin", city, state, zip_code, region))
                            added += 1
                    if progress and added > 0:
                        print(f"      Redfin: {added} MLS foreclosures")
                except Exception as e:
                    if progress:
                        print(f"      Redfin error: {e}")
            elif redfin_mod and redfin_mod.get_circuit_breaker_status()["tripped"]:
                if progress and i == len([k for k in range(len(zip_sample)) if True]):
                    print("      ⚠️ Redfin circuit breaker tripped — skipping remaining ZIPs")

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

            # Skip past auctions — no point showing expired listings
            if getattr(prop, 'auction_date_is_past', False):
                continue

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
    redfin_idx = 0
    sheriff_idx = 0
    auctioncom_idx = 0
    real_idx = 0
    for prop in properties:
        ds = getattr(prop, 'data_source', '')
        if ds == 'auctioncom':
            auctioncom_idx += 1
            prop.id = f"AUCT-{auctioncom_idx:04d}"
        elif ds == 'sheriff':
            sheriff_idx += 1
            prop.id = f"SHRF-{sheriff_idx:04d}"
        elif ds == 'redfin':
            redfin_idx += 1
            prop.id = f"RDFN-{redfin_idx:04d}"
        else:
            real_idx += 1
            prop.id = f"REAL-{real_idx:04d}"

    if progress:
        print(f"   Properties after filtering: {len(properties)}")

    # --- Enrich with Zillow Zestimates (batch lookup) ---
    # Replaces the $/sqft estimation with real Zestimate data.
    # Uses the same Apify token as Auction.com scraping.
    zillow_mod = _get_zillow()
    has_zillow = zillow_mod is not None and zillow_mod.is_configured()
    if has_zillow and properties:
        if progress:
            print("   Looking up Zillow Zestimates...")

        # Build address list for batch lookup
        addr_list = []
        for prop in properties:
            full_addr = f"{prop.address}, {prop.city}, {prop.state} {prop.zip_code}"
            addr_list.append(full_addr)

        zestimate_results = zillow_mod.batch_zestimate_lookup(
            addr_list, progress=progress
        )

        if zestimate_results:
            zest_count = 0
            for prop in properties:
                addr_key = zillow_mod._normalize_address_key(prop.address)
                zdata = zestimate_results.get(addr_key)
                if zdata and zdata.get("zestimate"):
                    old_arv = prop.estimated_arv
                    prop.estimated_arv = float(zdata["zestimate"])
                    prop.valuation_source = "zillow"

                    # Also update property details if Zillow has better data
                    if zdata.get("beds") and prop.bedrooms == 3:  # Replace default
                        prop.bedrooms = int(zdata["beds"])
                    if zdata.get("baths") and prop.bathrooms == 2.0:  # Replace default
                        prop.bathrooms = float(zdata["baths"])
                    if zdata.get("sqft") and prop.sqft == 1800:  # Replace default
                        prop.sqft = int(float(zdata["sqft"]))
                    if zdata.get("year_built") and prop.year_built == 1990:  # Replace default
                        prop.year_built = int(zdata["year_built"])
                    if zdata.get("lot_size"):
                        try:
                            prop.lot_size = float(zdata["lot_size"])
                        except (ValueError, TypeError):
                            pass
                    if zdata.get("zestimate_rent"):
                        try:
                            prop.estimated_monthly_rent = float(zdata["zestimate_rent"])
                        except (ValueError, TypeError):
                            pass

                    # Tax data from Zillow
                    if zdata.get("annual_tax") and not prop.annual_property_tax:
                        try:
                            prop.annual_property_tax = float(zdata["annual_tax"])
                        except (ValueError, TypeError):
                            pass

                    # Last sale from Zillow
                    if zdata.get("last_sold_price") and not prop.last_sale_price:
                        try:
                            prop.last_sale_price = float(zdata["last_sold_price"])
                        except (ValueError, TypeError):
                            pass

                    prop.calculate_metrics()
                    zest_count += 1

            if progress:
                print(f"   Enriched {zest_count}/{len(properties)} properties with Zillow Zestimates")

    # --- Enrich with ATTOM mortgage/debt + property data ---
    # Uses expandedprofile (paid tier: mortgage, lender, sale history)
    # and property/detail + AVM (free tier: real valuation, beds/baths/sqft).
    # Falls back to generated context only when ATTOM key isn't available.
    # Note: has_attom_enrich is independent of search sources — always enrich
    # when an ATTOM key is available, even for Auction.com/Redfin/Sheriff data.
    if has_attom_enrich and properties:
        attom = _get_attom()
        enriched_count = 0
        mortgage_count = 0
        enrich_limit = 30  # Limit API calls to conserve free-tier quota

        if progress:
            print("   Enriching with ATTOM property data...")

        for prop in properties:
            if enriched_count >= enrich_limit:
                break

            try:
                city_state_zip = f"{prop.city}, {prop.state} {prop.zip_code}"
                mtg = attom.get_mortgage_info(prop.address, city_state_zip)
                if mtg:
                    # --- Mortgage data (paid tier — may be empty on free tier) ---
                    if mtg.get("mortgage_balance"):
                        prop.mortgage_balance = mtg["mortgage_balance"]
                        prop.total_debt = mtg["mortgage_balance"]
                        mortgage_count += 1
                    if mtg.get("mortgage_lender"):
                        prop.mortgage_lender = mtg["mortgage_lender"]
                        if not prop.foreclosing_entity:
                            prop.foreclosing_entity = mtg["mortgage_lender"]
                            prop.bank_contact_url = config.BANK_CONTACT_URLS.get(
                                mtg["mortgage_lender"]
                            )
                    if mtg.get("mortgage_date"):
                        prop.mortgage_date = mtg["mortgage_date"]
                    if mtg.get("mortgage_interest_rate"):
                        prop.mortgage_interest_rate = mtg["mortgage_interest_rate"]

                    # Last sale history
                    if mtg.get("last_sale_amount") and not prop.last_sale_price:
                        prop.last_sale_price = mtg["last_sale_amount"]
                    if mtg.get("last_sale_date") and not prop.last_sale_date:
                        prop.last_sale_date = mtg["last_sale_date"]

                    # Tax data
                    if mtg.get("tax_amount") and not prop.annual_property_tax:
                        prop.annual_property_tax = mtg["tax_amount"]

                    # Foreclosure flags
                    if mtg.get("is_foreclosure") or mtg.get("is_distressed"):
                        if not prop.foreclosure_stage:
                            if mtg.get("is_reo"):
                                prop.foreclosure_stage = "REO / Bank Owned"
                            elif mtg.get("is_foreclosure"):
                                prop.foreclosure_stage = "Foreclosure"
                            elif mtg.get("is_distressed"):
                                prop.foreclosure_stage = "Distressed Sale"

                    if mtg.get("seller_name") and not prop.foreclosing_entity:
                        prop.foreclosing_entity = mtg["seller_name"]

                    # --- Free-tier data: real AVM valuation ---
                    # Only override if Zillow Zestimate hasn't already set it
                    if mtg.get("avm_value") and getattr(prop, 'valuation_source', None) != 'zillow':
                        prop.estimated_arv = mtg["avm_value"]
                        prop.valuation_source = "attom_avm"
                        prop.calculate_metrics()  # Recalculate with real value

                    # --- Free-tier data: real property details ---
                    if mtg.get("sqft") and prop.sqft == 1800:  # Replace default
                        prop.sqft = int(mtg["sqft"])
                    if mtg.get("bedrooms") and prop.bedrooms == 3:  # Replace default
                        prop.bedrooms = int(mtg["bedrooms"])
                    if mtg.get("bathrooms") and prop.bathrooms == 2.0:  # Replace default
                        prop.bathrooms = float(mtg["bathrooms"])
                    if mtg.get("lot_size"):
                        prop.lot_size = float(mtg["lot_size"])

                    enriched_count += 1
            except Exception as e:
                if progress:
                    print(f"      ATTOM enrichment error for {prop.address}: {e}")

        if progress and enriched_count > 0:
            parts = [f"{enriched_count} properties with ATTOM data"]
            if mortgage_count > 0:
                parts.append(f"{mortgage_count} with mortgage/debt info")
            else:
                parts.append("AVM + property details (mortgage data requires paid tier)")
            print(f"   Enriched {' | '.join(parts)}")

    # --- Fallback: generate context for properties without mortgage data ---
    # Only used when ATTOM key is unavailable or didn't return mortgage data
    _MAJOR_LENDERS = list(config.BANK_CONTACT_URLS.keys())
    _LOAN_TYPES = ["Conventional", "FHA", "VA", "USDA", "Jumbo", "ARM", "Fixed 30yr", "Fixed 15yr"]
    _STAGES = ["Pre-Foreclosure", "Notice of Default", "Lis Pendens",
               "Auction Scheduled", "REO / Bank Owned", "Short Sale"]

    fc_count = 0
    for prop in properties:
        if prop.foreclosing_entity:
            continue  # Already has real or enriched data
        if getattr(prop, 'data_source', '') in ('redfin', 'sheriff', 'auctioncom'):
            continue  # These sources have real data — don't add fake context

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
        print(f"   Added generated foreclosure context to {fc_count} properties (no ATTOM mortgage data)")

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
            if has_redfin and len(properties) == 0:
                print("   ℹ️  No MLS-listed foreclosures found in your target regions.")
                print("      This is normal — foreclosure inventory on MLS varies by area.")
                print("      Try expanding ACTIVE_REGIONS in config.py or running --mock for testing.")
            if not has_attom_enrich and not (sources and "redfin" in sources):
                print("   ℹ️  No ATTOM API key — add attom_rapidapi to .api_keys.json")
            elif has_attom_enrich and len(properties) == 0:
                print("   ℹ️  ATTOM may be rate-limited (500 calls/day on free tier)")
                print("      Rate limits reset daily. Try again later.")
            if has_batchdata:
                # Check if sandbox
                try:
                    from api_batchdata import search_properties_by_area
                    test = search_properties_by_area("Portland, OR", take=1)
                    if test and len(test) == 1 and test[0].get("state") not in config.TARGET_STATES:
                        print("   ℹ️  BatchData key appears to be a sandbox/demo token.")
                        print("      Upgrade at https://app.batchdata.com for real property data.")
                except Exception:
                    pass

    return properties
