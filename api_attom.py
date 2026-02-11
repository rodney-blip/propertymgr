"""
ATTOM Data API client for property valuations, details, and foreclosure data.

Uses ATTOM's direct gateway: https://api.gateway.attomdata.com
Documentation: https://api.developer.attomdata.com
Free trial: 30 days, 500 calls/day

Endpoints used:
  - /avm/detail              — Automated Valuation Model (ARV estimation)
  - /property/detail          — Full property details (beds, baths, sqft, etc.)
  - /saleshistory/detail      — Sales history for comps
  - /sale/snapshot            — Recent sales in an area (search by postal code)
  - /property/snapshot        — Properties in an area (search by postal code)
  - /saleshistory/expandedprofile — Expanded sale/foreclosure/loan history
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, Dict, List
import config


# ATTOM direct API gateway
API_BASE = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"

# Rate limiting: be polite to the API
_last_request_time = 0.0
_REQUEST_INTERVAL = 0.5  # seconds between requests (direct API allows ~200/min)


def _make_request(endpoint: str, params: Dict) -> Optional[Dict]:
    """Make an authenticated GET request to ATTOM's direct gateway."""
    global _last_request_time

    api_key = config.API_KEYS.get("attom_rapidapi")
    if not api_key:
        return None

    # Rate limiting
    elapsed = time.time() - _last_request_time
    if elapsed < _REQUEST_INTERVAL:
        time.sleep(_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()

    query = urllib.parse.urlencode(params)
    url = f"{API_BASE}/{endpoint}?{query}"

    req = urllib.request.Request(url, headers={
        "apikey": api_key,
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"   ATTOM API rate limited (429) — daily quota may be exhausted")
        elif e.code == 401:
            print(f"   ATTOM API 401 — API key may be invalid or expired")
        elif e.code == 404:
            print(f"   ATTOM API 404 — endpoint '{endpoint}' not found or no results")
        else:
            print(f"   ATTOM API error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"   ATTOM API error: {e}")
        return None


def get_avm(address: str, city_state_zip: str) -> Optional[Dict]:
    """
    Get Automated Valuation Model (AVM) for a property.

    Args:
        address: Street address, e.g. "123 Main St"
        city_state_zip: e.g. "Austin, TX 78701"

    Returns:
        Dict with keys: value, high, low (dollar amounts) or None
    """
    data = _make_request("avm/detail", {
        "address1": address,
        "address2": city_state_zip,
    })

    if not data or "property" not in data:
        return None

    try:
        prop = data["property"][0]
        avm = prop.get("avm", {}).get("amount", {})
        return {
            "value": avm.get("value"),
            "high": avm.get("high"),
            "low": avm.get("low"),
        }
    except (IndexError, KeyError):
        return None


def get_property_detail(address: str, city_state_zip: str) -> Optional[Dict]:
    """
    Get detailed property information.

    Returns:
        Dict with property details or None
    """
    data = _make_request("property/detail", {
        "address1": address,
        "address2": city_state_zip,
    })

    if not data or "property" not in data:
        return None

    try:
        prop = data["property"][0]
        building = prop.get("building", {})
        size = building.get("size", {})
        rooms = building.get("rooms", {})
        assessment = prop.get("assessment", {})
        tax_info = assessment.get("tax", {})
        market = assessment.get("market", {})

        return {
            "sqft": size.get("universalsize"),
            "bedrooms": rooms.get("beds"),
            "bathrooms": rooms.get("bathstotal"),
            "year_built": building.get("summary", {}).get("yearbuilt"),
            "lot_size": prop.get("lot", {}).get("lotsize1"),
            "assessed_value": assessment.get("assessed", {}).get("assdttlvalue"),
            "market_value": market.get("mktttlvalue"),
            "tax_amount": tax_info.get("taxamt"),
            "attom_id": prop.get("identifier", {}).get("attomId"),
        }
    except (IndexError, KeyError):
        return None


def get_sales_history(address: str, city_state_zip: str) -> Optional[list]:
    """
    Get comparable sales / sales history for a property.

    Returns:
        List of sale records or None
    """
    data = _make_request("saleshistory/detail", {
        "address1": address,
        "address2": city_state_zip,
    })

    if not data or "property" not in data:
        return None

    try:
        sales = []
        for prop in data["property"]:
            sale = prop.get("sale", {})
            sales.append({
                "sale_amount": sale.get("amount", {}).get("saleamt"),
                "sale_date": sale.get("salesSearchDate"),
            })
        return sales if sales else None
    except (IndexError, KeyError):
        return None


def enrich_property_arv(address: str, city: str, state: str, zip_code: str) -> Optional[float]:
    """
    Convenience: get just the AVM value for ARV estimation.
    Returns the estimated value in dollars or None.
    """
    city_state_zip = f"{city}, {state} {zip_code}"
    avm = get_avm(address, city_state_zip)
    if avm and avm.get("value"):
        return float(avm["value"])
    return None


# ---------------------------------------------------------------------------
# Area-based search endpoints — find real properties in a geography
# ---------------------------------------------------------------------------

def search_properties_by_zip(postal_code: str,
                              min_price: int = None,
                              max_price: int = None,
                              page: int = 1,
                              page_size: int = 25) -> Optional[List[Dict]]:
    """
    Search for properties in a ZIP code using the /property/snapshot endpoint.

    Returns a list of property dicts with address, beds, baths, sqft, etc.
    This gives us REAL addresses we can then enrich with AVM & foreclosure data.
    """
    params = {
        "postalcode": postal_code,
        "page": str(page),
        "pagesize": str(page_size),
        "propertytype": "SFR",  # Single Family Residential
    }
    if min_price is not None:
        params["minSaleAmt"] = str(min_price)
    if max_price is not None:
        params["maxSaleAmt"] = str(max_price)

    data = _make_request("property/snapshot", params)
    if not data or "property" not in data:
        return None

    properties = []
    try:
        for prop in data["property"]:
            addr = prop.get("address", {})
            building = prop.get("building", {})
            size = building.get("size", {})
            rooms = building.get("rooms", {})
            lot = prop.get("lot", {})
            assessment = prop.get("assessment", {})

            properties.append({
                "address": addr.get("line1", ""),
                "city": addr.get("locality", ""),
                "state": addr.get("countrySubd", ""),
                "zip_code": addr.get("postal1", postal_code),
                "bedrooms": rooms.get("beds"),
                "bathrooms": rooms.get("bathstotal") or rooms.get("bathsfull"),
                "sqft": size.get("universalsize") or size.get("livingsize"),
                "lot_size": lot.get("lotsize1"),
                "year_built": building.get("summary", {}).get("yearbuilt"),
                "assessed_value": assessment.get("assessed", {}).get("assdttlvalue"),
                "market_value": assessment.get("market", {}).get("mktttlvalue"),
                "attom_id": prop.get("identifier", {}).get("attomId"),
            })
    except (IndexError, KeyError, TypeError) as e:
        print(f"   ATTOM parse error in property/snapshot: {e}")

    return properties if properties else None


def search_sales_by_zip(postal_code: str,
                         min_price: int = None,
                         max_price: int = None,
                         page: int = 1,
                         page_size: int = 25) -> Optional[List[Dict]]:
    """
    Search recent sales in a ZIP code using /sale/snapshot.
    Useful for finding distressed sales, REO sales, and auction activity.
    """
    params = {
        "postalcode": postal_code,
        "page": str(page),
        "pagesize": str(page_size),
    }
    if min_price is not None:
        params["minSaleAmt"] = str(min_price)
    if max_price is not None:
        params["maxSaleAmt"] = str(max_price)

    data = _make_request("sale/snapshot", params)
    if not data or "property" not in data:
        return None

    sales = []
    try:
        for prop in data["property"]:
            addr = prop.get("address", {})
            sale = prop.get("sale", {})
            amount = sale.get("amount", {})
            building = prop.get("building", {})
            size = building.get("size", {})
            rooms = building.get("rooms", {})

            sales.append({
                "address": addr.get("line1", ""),
                "city": addr.get("locality", ""),
                "state": addr.get("countrySubd", ""),
                "zip_code": addr.get("postal1", postal_code),
                "sale_amount": amount.get("saleamt"),
                "sale_date": amount.get("salerecdate") or sale.get("salesSearchDate"),
                "sale_type": sale.get("calculation", {}).get("saletype"),
                "seller_name": sale.get("calculation", {}).get("sellername"),
                "bedrooms": rooms.get("beds"),
                "bathrooms": rooms.get("bathstotal"),
                "sqft": size.get("universalsize"),
                "year_built": building.get("summary", {}).get("yearbuilt"),
                "attom_id": prop.get("identifier", {}).get("attomId"),
            })
    except (IndexError, KeyError, TypeError) as e:
        print(f"   ATTOM parse error in sale/snapshot: {e}")

    return sales if sales else None


def get_expanded_profile(address: str, city_state_zip: str) -> Optional[Dict]:
    """
    Get expanded sale/foreclosure/loan history for a property.
    This endpoint returns pre-foreclosure filings, auction info, and
    detailed mortgage/lien data.
    """
    data = _make_request("saleshistory/expandedprofile", {
        "address1": address,
        "address2": city_state_zip,
    })

    if not data or "property" not in data:
        return None

    try:
        prop = data["property"][0]
        sale = prop.get("sale", {})
        mortgage = prop.get("mortgage", {}) or {}

        return {
            "sale_amount": sale.get("amount", {}).get("saleamt"),
            "sale_date": sale.get("salesSearchDate"),
            "sale_type": sale.get("calculation", {}).get("saletype"),
            "seller_name": sale.get("calculation", {}).get("sellername"),
            "deed_type": sale.get("calculation", {}).get("deedtype"),
            "foreclosure": sale.get("calculation", {}).get("isforeclosure"),
            "distressed_sale": sale.get("calculation", {}).get("isdistressedsale"),
            "reo_sale": sale.get("calculation", {}).get("isreosale"),
            "mortgage_amount": mortgage.get("amount", {}).get("mortgageAmount"),
            "lender_name": mortgage.get("lenderName"),
            "mortgage_date": mortgage.get("date"),
        }
    except (IndexError, KeyError, TypeError):
        return None
