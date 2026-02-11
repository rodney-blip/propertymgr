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

    Returns:
        List of property dicts with address and foreclosure info
    """
    request = {
        "address": {
            "city": city,
            "state": state,
        },
        "propertyType": property_type,
    }

    if min_value or max_value:
        request["marketValueRange"] = {}
        if min_value:
            request["marketValueRange"]["min"] = min_value
        if max_value:
            request["marketValueRange"]["max"] = max_value

    body = {"requests": [request]}

    data = _make_request("property/search", body)
    if not data:
        return None

    try:
        results = data.get("results", {}).get("properties", [])
        properties = []
        for prop in results:
            addr = prop.get("address", {})
            foreclosure = prop.get("preForeclosure", {}) or {}
            properties.append({
                "address": addr.get("street", ""),
                "city": addr.get("city", ""),
                "state": addr.get("state", ""),
                "zip_code": addr.get("zip", ""),
                "foreclosing_entity": foreclosure.get("trusteeName"),
                "default_amount": foreclosure.get("defaultAmount"),
                "filing_type": foreclosure.get("filingType"),
                "recording_date": foreclosure.get("recordingDate"),
                "auction_date": foreclosure.get("auctionDate"),
            })
        return properties if properties else None
    except (KeyError, TypeError):
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
