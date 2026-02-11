"""
Configuration settings for Auction Property Analyzer
Edit these values to customize the analyzer for your needs
"""

import json
import os
from pathlib import Path

def _load_local_keys():
    """Load API keys from .api_keys.json (gitignored) or environment variables."""
    keys = {}
    keyfile = Path(__file__).parent / ".api_keys.json"
    if keyfile.exists():
        try:
            keys = json.loads(keyfile.read_text())
        except Exception:
            pass
    # Environment variables override file values
    env_map = {
        "attom_rapidapi": "ATTOM_API_KEY",
        "batchdata": "BATCHDATA_API_KEY",
        "census": "CENSUS_API_KEY",
        "hud": "HUD_API_KEY",
    }
    for key_name, env_name in env_map.items():
        env_val = os.environ.get(env_name)
        if env_val:
            keys[key_name] = env_val
    return keys

_local_keys = _load_local_keys()

# Geographic targeting
TARGET_STATES = ["Oregon", "Texas", "Washington"]

# Price filters
MIN_AUCTION_PRICE = 100000
MAX_AUCTION_PRICE = 1200000

# Repair budget
MAX_REPAIR_COST = 80000

# Profit requirements
MIN_PROFIT_MARGIN = 30.0  # Percentage
MIN_DEAL_SCORE = 60  # Out of 100

# Property types
ALLOWED_PROPERTY_TYPES = ["Single Family"]

# Cost assumptions (as percentages or fixed amounts)
CLOSING_COST_PERCENT = 0.03  # 3% of purchase price
HOLDING_MONTHS = 6
HOLDING_COST_PERCENT_PER_MONTH = 0.01  # 1% of ARV per month
SELLING_COST_PERCENT = 0.08  # 8% of ARV (agent fees, closing)

# Deal scoring weights (must sum to 100)
SCORE_WEIGHTS = {
    "profit_margin": 40,
    "repair_efficiency": 20,
    "neighborhood": 20,
    "property_characteristics": 20
}

# Alert thresholds
ALERT_LEVELS = {
    "hot": 40.0,      # 40%+ profit margin
    "excellent": 35.0,  # 35-40% profit margin
    "good": 30.0      # 30-35% profit margin
}

# Data generation (for mock data)
MOCK_DATA_COUNT = 75

# Active region filter: only scan these regions per state.
# Set to None (or omit the state) to include ALL regions for that state.
# Set to a list of region names to restrict scanning to just those regions.
# This is useful for concentrating API calls on your target market.
ACTIVE_REGIONS = {
    "Oregon": ["Central Oregon", "Southern Oregon"],  # Bend/Redmond + Medford area only
    "Texas": ["Greater Austin"],  # Focus on Austin — exclude DFW, Houston, SA, El Paso
    "Washington": None,   # All Washington regions
}

# Region definitions: state -> region_name -> list of (city, zip_code) tuples
REGION_DEFINITIONS = {
    "Oregon": {
        "Portland Metro": [
            ("Portland", "97201"), ("Beaverton", "97005"), ("Hillsboro", "97123"),
            ("Gresham", "97030"), ("Lake Oswego", "97034"), ("Tigard", "97223"),
            ("Tualatin", "97062"), ("Oregon City", "97045"), ("West Linn", "97068"),
        ],
        "Salem / Mid-Valley": [
            ("Salem", "97301"), ("Keizer", "97303"), ("Albany", "97321"),
            ("Corvallis", "97330"), ("McMinnville", "97128"), ("Woodburn", "97071"),
        ],
        "Eugene / Lane County": [
            ("Eugene", "97401"), ("Springfield", "97477"), ("Cottage Grove", "97424"),
        ],
        "Central Oregon": [
            ("Bend", "97701"), ("Redmond", "97756"), ("Madras", "97741"),
            ("Prineville", "97754"), ("Sisters", "97759"),
        ],
        "Southern Oregon": [
            ("Medford", "97501"), ("Ashland", "97520"), ("Grants Pass", "97526"),
            ("Klamath Falls", "97601"), ("Roseburg", "97470"),
        ],
    },
    "Texas": {
        "Greater Austin": [
            ("Austin", "78701"), ("Round Rock", "78664"), ("Cedar Park", "78613"),
            ("Georgetown", "78626"), ("Pflugerville", "78660"), ("Kyle", "78640"),
            ("San Marcos", "78666"), ("Leander", "78641"),
        ],
        "Dallas / Fort Worth": [
            ("Dallas", "75201"), ("Fort Worth", "76101"), ("Arlington", "76010"),
            ("Plano", "75023"), ("Irving", "75060"), ("Frisco", "75034"),
            ("McKinney", "75069"), ("Denton", "76201"), ("Grand Prairie", "75050"),
            ("Garland", "75040"), ("Richardson", "75080"), ("Mesquite", "75149"),
        ],
        "Houston Metro": [
            ("Houston", "77001"), ("Sugar Land", "77478"), ("Pearland", "77581"),
            ("League City", "77573"), ("Pasadena", "77501"), ("Baytown", "77520"),
            ("The Woodlands", "77380"), ("Katy", "77449"), ("Cypress", "77429"),
        ],
        "San Antonio Area": [
            ("San Antonio", "78201"), ("New Braunfels", "78130"),
            ("Seguin", "78155"), ("Boerne", "78006"), ("Schertz", "78154"),
        ],
        "El Paso Area": [
            ("El Paso", "79901"), ("Socorro", "79927"), ("Horizon City", "79928"),
        ],
    },
    "Washington": {
        "Southern Washington / Vancouver": [
            ("Vancouver", "98660"), ("Camas", "98607"), ("Washougal", "98671"),
            ("Battle Ground", "98604"), ("Ridgefield", "98642"), ("Woodland", "98674"),
            ("Longview", "98632"), ("Kelso", "98626"),
        ],
    },
}

# Build reverse lookup: (state, city) -> region_name
CITY_TO_REGION = {}
for _state, _regions in REGION_DEFINITIONS.items():
    for _region_name, _cities in _regions.items():
        for _city_name, _zip_code in _cities:
            CITY_TO_REGION[(_state, _city_name)] = _region_name

# Build flat city lists from region definitions (single source of truth)
STATE_CITIES = {}
for _state_name, _state_regions in REGION_DEFINITIONS.items():
    STATE_CITIES[_state_name] = []
    for _region_cities in _state_regions.values():
        STATE_CITIES[_state_name].extend(_region_cities)

# Legacy aliases for backward compatibility
OREGON_CITIES = STATE_CITIES.get("Oregon", [])
TEXAS_CITIES = STATE_CITIES.get("Texas", [])
WASHINGTON_CITIES = STATE_CITIES.get("Washington", [])

# Auction platforms
AUCTION_PLATFORMS = [
    "Auction.com",
    "Hubzu",
    "RealtyBid",
    "HomePath",
    "Bank Foreclosure",
    "Hudson & Marshall",
    "Williams & Williams"
]

# Auction platform URLs
AUCTION_PLATFORM_URLS = {
    "Auction.com": "https://www.auction.com",
    "Hubzu": "https://www.hubzu.com",
    "RealtyBid": "https://www.realtybid.com",
    "HomePath": "https://www.homepath.fanniemae.com",
    "Bank Foreclosure": None,
    "Hudson & Marshall": "https://www.hudsonandmarshall.com",
    "Williams & Williams": "https://www.williamsauction.com",
}

# Bank / servicer REO contact URLs
BANK_CONTACT_URLS = {
    "Bank of America": "https://realestatecenter.bankofamerica.com",
    "Wells Fargo": "https://reo.wellsfargo.com",
    "Chase Bank": "https://www.chase.com/personal/mortgage/reo",
    "US Bank": "https://www.usbank.com/home-loans/reo.html",
    "Citibank": "https://www.citibank.com/reo",
    "PNC Bank": "https://www.pnc.com/en/personal-banking/home-lending.html",
    "Truist Bank": "https://www.truist.com/mortgage/reo",
    "Capital One": "https://www.capitalone.com",
    "Flagstar Bank": "https://www.flagstar.com/reo",
    "Mr. Cooper": "https://www.mrcooper.com",
    "Nationstar Mortgage": "https://www.mrcooper.com",
    "Ocwen Financial": "https://www.phhmortgage.com",
    "PHH Mortgage": "https://www.phhmortgage.com",
    "Shellpoint Mortgage": "https://www.shellpointmtg.com",
    "Freedom Mortgage": "https://www.freedommortgage.com",
    "Caliber Home Loans": "https://www.newrez.com",
    "NewRez LLC": "https://www.newrez.com",
}

# Price per square foot by state (for ARV estimation)
PRICE_PER_SQFT = {
    "Oregon": 200,
    "Texas": 160,
    "California": 350,
    "Washington": 220,
    "Arizona": 170,
    "Colorado": 230
}

# API keys (add your own when integrating real data)
# ATTOM via RapidAPI: https://rapidapi.com/attomdatasolutions/api/attom-property
# BatchData: https://app.batchdata.com (sandbox token available for free testing)
# Census: https://api.census.gov/data/key_signup.html (free)
# HUD: https://www.huduser.gov/portal/dataset/fmr-api.html (free)
API_KEYS = {
    "attom_rapidapi": _local_keys.get("attom_rapidapi"),   # RapidAPI key for ATTOM property valuations
    "batchdata": _local_keys.get("batchdata"),              # BatchData bearer token for foreclosure records
    "census": _local_keys.get("census"),                    # US Census API key (free)
    "hud": _local_keys.get("hud"),                          # HUD Fair Market Rent token (free)
    "zillow": None,
    "redfin": None,
    "auction_com": None,
    "realtor_com": None,
}

# Output settings
OUTPUT_JSON_FILE = "property_analysis.json"
OUTPUT_CSV_FILE = "properties.csv"
ENABLE_CSV_EXPORT = True

# Web server settings
DEFAULT_PORT = 8000
DASHBOARD_FILE = "index.html"
