"""
US Census Bureau & HUD API client for neighborhood data.
Census key signup (free): https://api.census.gov/data/key_signup.html
HUD token signup (free): https://www.huduser.gov/portal/dataset/fmr-api.html
"""

import json
import urllib.request
import urllib.error
from typing import Optional, Dict
import config


CENSUS_BASE = "https://api.census.gov/data"
HUD_BASE = "https://www.huduser.gov/hudapi/public"

# ACS 5-Year variable codes
ACS_VARIABLES = {
    "median_income": "B19013_001E",
    "total_population": "B01003_001E",
    "median_age": "B01002_001E",
    "median_home_value": "B25077_001E",
    "median_rent": "B25064_001E",
    "total_housing_units": "B25002_001E",
    "vacant_units": "B25002_003E",
    "owner_occupied": "B25003_002E",
    "renter_occupied": "B25003_003E",
}


def get_neighborhood_data(zip_code: str, year: int = 2023) -> Optional[Dict]:
    """
    Get neighborhood demographics and housing data from US Census ACS 5-Year.

    Args:
        zip_code: 5-digit ZIP code
        year: ACS data year (default 2023, most recent complete)

    Returns:
        Dict with income, population, housing stats, or None
    """
    census_key = config.API_KEYS.get("census")

    variables = ",".join(["NAME"] + list(ACS_VARIABLES.values()))
    url = (
        f"{CENSUS_BASE}/{year}/acs/acs5"
        f"?get={variables}"
        f"&for=zip%20code%20tabulation%20area:{zip_code}"
    )
    if census_key:
        url += f"&key={census_key}"

    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            rows = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"   Census API error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"   Census API error: {e}")
        return None

    if not rows or len(rows) < 2:
        return None

    header = rows[0]
    values = rows[1]

    def _val(var_code):
        try:
            idx = header.index(var_code)
            v = values[idx]
            if v and int(v) > 0:
                return int(v)
        except (ValueError, IndexError, TypeError):
            pass
        return None

    result = {}
    for name, code in ACS_VARIABLES.items():
        result[name] = _val(code)

    # Calculate derived metrics
    total_units = result.get("total_housing_units")
    vacant = result.get("vacant_units")
    if total_units and vacant and total_units > 0:
        result["vacancy_rate"] = round(vacant / total_units * 100, 1)

    owner = result.get("owner_occupied")
    renter = result.get("renter_occupied")
    if owner and renter and (owner + renter) > 0:
        result["owner_occupancy_rate"] = round(owner / (owner + renter) * 100, 1)

    return result


def get_fair_market_rent(county_fips: str, year: int = 2026) -> Optional[Dict]:
    """
    Get HUD Fair Market Rent data for a county.

    Args:
        county_fips: 10-digit FIPS entity ID (5-digit county FIPS + "99999")
        year: FMR year (default 2026)

    Returns:
        Dict with rent values by bedroom count, or None
    """
    hud_token = config.API_KEYS.get("hud")
    if not hud_token:
        return None

    url = f"{HUD_BASE}/fmr/data/{county_fips}?year={year}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {hud_token}",
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"   HUD API error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"   HUD API error: {e}")
        return None

    if not data or "data" not in data:
        return None

    fmr = data["data"].get("basicdata", {})
    return {
        "efficiency": fmr.get("Efficiency"),
        "one_bedroom": fmr.get("One-Bedroom"),
        "two_bedroom": fmr.get("Two-Bedroom"),
        "three_bedroom": fmr.get("Three-Bedroom"),
        "four_bedroom": fmr.get("Four-Bedroom"),
    }


def calculate_neighborhood_score(zip_code: str) -> Optional[int]:
    """
    Calculate a 1-10 neighborhood score from Census data.
    Uses median income, home values, vacancy rates, and owner occupancy.

    Returns:
        Integer score 1-10 or None if data unavailable
    """
    data = get_neighborhood_data(zip_code)
    if not data:
        return None

    score = 5.0  # Start at midpoint

    # Income factor: national median ~$75K
    income = data.get("median_income")
    if income:
        if income >= 100000:
            score += 2.0
        elif income >= 75000:
            score += 1.0
        elif income >= 50000:
            score += 0.0
        elif income >= 35000:
            score -= 1.0
        else:
            score -= 2.0

    # Home value factor
    home_value = data.get("median_home_value")
    if home_value:
        if home_value >= 400000:
            score += 1.0
        elif home_value >= 250000:
            score += 0.5
        elif home_value < 150000:
            score -= 1.0

    # Vacancy rate factor (lower is better)
    vacancy = data.get("vacancy_rate")
    if vacancy is not None:
        if vacancy < 5:
            score += 1.0
        elif vacancy < 10:
            score += 0.0
        elif vacancy < 15:
            score -= 0.5
        else:
            score -= 1.0

    # Owner occupancy factor (higher is better for flips)
    owner_rate = data.get("owner_occupancy_rate")
    if owner_rate is not None:
        if owner_rate >= 70:
            score += 1.0
        elif owner_rate >= 50:
            score += 0.0
        else:
            score -= 0.5

    return max(1, min(10, round(score)))
