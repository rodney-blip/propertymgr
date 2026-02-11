"""
ATTOM Data API client for property valuations and details.
Sign up at: https://rapidapi.com/attomdatasolutions/api/attom-property
Or direct: https://api.developer.attomdata.com (30-day free trial, 500 calls/day)
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, Dict
import config


RAPIDAPI_BASE = "https://attom-property.p.rapidapi.com/propertyapi/v1.0.0"

# Rate limiting: track last request time to avoid 429s
_last_request_time = 0.0
_REQUEST_INTERVAL = 2.0  # seconds between requests (RapidAPI free tier)


def _make_request(endpoint: str, params: Dict) -> Optional[Dict]:
    """Make an authenticated request to ATTOM via RapidAPI."""
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
    url = f"{RAPIDAPI_BASE}/{endpoint}?{query}"

    req = urllib.request.Request(url, headers={
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "attom-property.p.rapidapi.com",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
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
