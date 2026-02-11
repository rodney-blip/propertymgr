"""
BatchData API client for foreclosure records and lien data.
Sign up at: https://app.batchdata.com
Docs: https://developer.batchdata.com
Sandbox token available for free testing with mock data.
"""

import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, List
import config


BASE_URL = "https://api.batchdata.com/api/v1"

_last_request_time = 0.0
_REQUEST_INTERVAL = 0.5  # seconds between requests


def _make_request(endpoint: str, body: Dict) -> Optional[Dict]:
    """Make an authenticated POST request to BatchData."""
    global _last_request_time

    api_key = config.API_KEYS.get("batchdata")
    if not api_key:
        return None

    # Rate limiting
    elapsed = time.time() - _last_request_time
    if elapsed < _REQUEST_INTERVAL:
        time.sleep(_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()

    url = f"{BASE_URL}/{endpoint}"
    data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"   BatchData API error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"   BatchData API error: {e}")
        return None


def lookup_property(address: str, city: str, state: str, zip_code: str) -> Optional[Dict]:
    """
    Full property lookup with all attributes including foreclosure/lien data.

    Returns:
        Dict with foreclosure context, mortgage data, and property details
    """
    body = {
        "requests": [
            {
                "address": {
                    "street": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                }
            }
        ]
    }

    data = _make_request("property/lookup", body)
    if not data:
        return None

    try:
        results = data.get("results", {}).get("properties", [])
        if not results:
            return None

        prop = results[0]

        # Extract foreclosure/pre-foreclosure data
        foreclosure = prop.get("preForeclosure", {}) or {}
        mortgage = prop.get("mortgage", {}) or {}
        lien = prop.get("lien", {}) or {}

        return {
            "foreclosing_entity": (
                foreclosure.get("trusteeName")
                or mortgage.get("lenderName")
                or lien.get("lenderName")
            ),
            "total_debt": (
                foreclosure.get("defaultAmount")
                or mortgage.get("amount")
                or lien.get("amount")
            ),
            "loan_type": mortgage.get("loanType"),
            "default_date": foreclosure.get("recordingDate"),
            "foreclosure_stage": foreclosure.get("filingType"),
            "auction_date": foreclosure.get("auctionDate"),
            "auction_location": foreclosure.get("auctionLocation"),
            "trustee_name": foreclosure.get("trusteeName"),
            "trustee_phone": foreclosure.get("trusteePhone"),
            "lien_amount": lien.get("amount"),
            "original_loan_amount": mortgage.get("amount"),
            "loan_origination_date": mortgage.get("originationDate"),
        }
    except (IndexError, KeyError, TypeError):
        return None


def search_foreclosures(city: str, state: str,
                        min_value: int = None,
                        max_value: int = None,
                        property_type: str = "Single Family Residential") -> Optional[List[Dict]]:
    """
    Search for properties with pre-foreclosure filings in a given area.
    Uses the searchCriteria/query format that BatchData requires.

    Returns:
        List of property dicts with address and foreclosure info
    """
    # Build query string — BatchData uses free-text location search
    query = f"{city}, {state}"

    body = {
        "searchCriteria": {
            "query": query,
        },
        "options": {
            "skip": 0,
            "take": 25,
        }
    }

    data = _make_request("property/search", body)
    if not data:
        return None

    try:
        results = data.get("results", {}).get("properties", [])
        properties = []
        for prop in results:
            addr = prop.get("address", {})

            # Extract foreclosure data from the correct field names
            foreclosure = prop.get("foreclosure", {}) or {}
            mortgage_history = prop.get("mortgageHistory", []) or []
            open_lien = prop.get("openLien", {}) or {}
            involuntary_lien = prop.get("involuntaryLien", {}) or {}

            # Get mortgage info from history
            latest_mortgage = mortgage_history[0] if mortgage_history else {}

            # Skip if not in our target area (sandbox returns random data)
            prop_state = addr.get("state", "")
            if prop_state and prop_state != state:
                continue

            # Determine sale price from deed history
            deed_history = prop.get("deedHistory", []) or []
            latest_sale = deed_history[0] if deed_history else {}
            sale_price = latest_sale.get("salePrice", 0) or 0

            # Get property details
            prop_details = prop.get("propertyDetails", {}) or {}
            building = prop_details.get("building", {}) or {}

            properties.append({
                "address": addr.get("street", ""),
                "city": addr.get("city", ""),
                "state": addr.get("state", ""),
                "zip_code": addr.get("zip", ""),
                "foreclosing_entity": (
                    foreclosure.get("documentType")
                    or latest_mortgage.get("lenderName")
                ),
                "default_amount": (
                    involuntary_lien.get("amount")
                    or foreclosure.get("amount")
                ),
                "total_debt": latest_mortgage.get("amount"),
                "filing_type": foreclosure.get("documentType"),
                "foreclosure_stage": foreclosure.get("status"),
                "recording_date": foreclosure.get("recordingDate"),
                "auction_date": foreclosure.get("auctionDate"),
                "sale_amount": sale_price,
                "loan_type": latest_mortgage.get("loanType"),
                "lender_name": latest_mortgage.get("lenderName"),
                "bedrooms": building.get("beds"),
                "bathrooms": building.get("baths"),
                "sqft": building.get("size"),
                "year_built": building.get("yearBuilt"),
                "assessed_value": prop.get("valuation", {}).get("assessedValue"),
                "market_value": prop.get("valuation", {}).get("estimatedValue"),
            })
        return properties if properties else None
    except (KeyError, TypeError, IndexError):
        return None


def search_properties_by_area(query: str,
                                take: int = 25,
                                skip: int = 0,
                                session_id: str = None) -> Optional[List[Dict]]:
    """
    Search for properties using a free-text location query.
    Supports city+state, zip code, or full address.

    Args:
        query: Location query, e.g. "Portland, OR" or "97201"
        take: Number of results per page (max 1000, recommended max 500)
        skip: Number of results to skip (for pagination)
        session_id: Session ID for paginated requests

    Returns:
        List of property dicts or None
    """
    body = {
        "searchCriteria": {
            "query": query,
        },
        "options": {
            "skip": skip,
            "take": min(take, 500),
        }
    }
    if session_id:
        body["options"]["sessionId"] = session_id

    data = _make_request("property/search", body)
    if not data:
        return None

    try:
        results = data.get("results", {}).get("properties", [])
        meta = data.get("results", {}).get("meta", {})

        properties = []
        for prop in results:
            addr = prop.get("address", {})
            foreclosure = prop.get("foreclosure", {}) or {}
            deed_history = prop.get("deedHistory", []) or []
            mortgage_history = prop.get("mortgageHistory", []) or []
            latest_sale = deed_history[0] if deed_history else {}
            latest_mortgage = mortgage_history[0] if mortgage_history else {}
            building = prop.get("propertyDetails", {}).get("building", {}) or {}

            properties.append({
                "address": addr.get("street", ""),
                "city": addr.get("city", ""),
                "state": addr.get("state", ""),
                "zip_code": addr.get("zip", ""),
                "sale_amount": latest_sale.get("salePrice", 0),
                "sale_date": latest_sale.get("saleDate"),
                "foreclosure_status": foreclosure.get("status"),
                "foreclosure_date": foreclosure.get("recordingDate"),
                "lender_name": latest_mortgage.get("lenderName"),
                "loan_amount": latest_mortgage.get("amount"),
                "loan_type": latest_mortgage.get("loanType"),
                "bedrooms": building.get("beds"),
                "bathrooms": building.get("baths"),
                "sqft": building.get("size"),
                "year_built": building.get("yearBuilt"),
                "assessed_value": prop.get("valuation", {}).get("assessedValue"),
                "market_value": prop.get("valuation", {}).get("estimatedValue"),
                "latitude": addr.get("latitude"),
                "longitude": addr.get("longitude"),
            })
        return properties if properties else None
    except (KeyError, TypeError, IndexError):
        return None


def enrich_foreclosure_context(address: str, city: str, state: str, zip_code: str) -> Optional[Dict]:
    """
    Convenience: get just the foreclosure/lien context for a property.
    Returns dict with foreclosing_entity, total_debt, loan_type, etc. or None.
    """
    result = lookup_property(address, city, state, zip_code)
    if not result:
        return None

    return {
        "foreclosing_entity": result.get("foreclosing_entity"),
        "total_debt": result.get("total_debt"),
        "loan_type": result.get("loan_type"),
        "default_date": result.get("default_date"),
        "foreclosure_stage": result.get("foreclosure_stage"),
    }
