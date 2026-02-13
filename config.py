"""
Configuration settings for Auction Property Analyzer
Edit these values to customize the analyzer for your needs
"""

import json
import os
import sys
from pathlib import Path

def _load_local_keys():
    """Load API keys from .api_keys.json (gitignored) or environment variables."""
    keys = {}
    keyfile = Path(__file__).parent / ".api_keys.json"
    if keyfile.exists():
        try:
            keys = json.loads(keyfile.read_text())
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load .api_keys.json: {e}", file=sys.stderr)
    # Environment variables override file values
    env_map = {
        "attom_rapidapi": "ATTOM_API_KEY",
        "batchdata": "BATCHDATA_API_KEY",
        "census": "CENSUS_API_KEY",
        "hud": "HUD_API_KEY",
        "apify_token": "APIFY_TOKEN",
    }
    for key_name, env_name in env_map.items():
        env_val = os.environ.get(env_name)
        if env_val:
            keys[key_name] = env_val
    return keys

_local_keys = _load_local_keys()

# Geographic targeting
TARGET_STATES = [
    "Oregon",
    # "Washington", "Texas", "Florida", "Arizona",
    # "Georgia", "North Carolina", "Ohio", "Tennessee", "California",
]

# Price filters
MIN_AUCTION_PRICE = 100000
MAX_AUCTION_PRICE = 3000000

# Repair budget (no cap — show all properties regardless of repair estimate)
MAX_REPAIR_COST = 999999999

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
# Repair efficiency removed — unknowable without physical inspection
SCORE_WEIGHTS = {
    "profit_margin": 50,
    "neighborhood": 25,
    "property_characteristics": 25
}

# Deal scoring thresholds (referenced by models.py _calculate_deal_score)
SCORING_THRESHOLDS = {
    "margin_excellent": 40,
    "margin_good": 30,
    "sqft_ideal_min": 1500,
    "sqft_ideal_max": 3000,
    "sqft_acceptable_min": 1200,
    "sqft_acceptable_max": 3500,
    "beds_ideal_min": 3,
    "beds_ideal_max": 4,
    "beds_acceptable": [2, 5],
    "baths_good": 2.0,
    "baths_acceptable": 1.5,
    "age_new": 20,
    "age_mid": 40,
    "age_old": 60,
}

# Alert thresholds
ALERT_LEVELS = {
    "hot": 40.0,      # 40%+ profit margin
    "excellent": 35.0,  # 35-40% profit margin
    "good": 30.0      # 30-35% profit margin
}

# Data generation (for mock data)
MOCK_DATA_COUNT = 150

# Active region filter: only scan these regions per state.
# Set to None (or omit the state) to include ALL regions for that state.
# Set to a list of region names to restrict scanning to just those regions.
# This is useful for concentrating API calls on your target market.
ACTIVE_REGIONS = {
    "Oregon": ["Central Oregon", "Southern Oregon"],  # Bend/Redmond + Medford
    "Texas": [],                                      # Disabled
    "Washington": [],                                 # Disabled
    "Florida": [],          # Disabled
    "Arizona": [],          # Disabled
    "Georgia": [],          # Disabled
    "North Carolina": [],   # Disabled
    "Ohio": [],             # Disabled
    "Tennessee": [],        # Disabled
    "California": [],       # Disabled
}

# Region definitions: state -> region_name -> list of (city, zip_code) tuples
REGION_DEFINITIONS = {
    "Oregon": {
        "Portland Metro / Gresham": [
            ("Gresham", "97030"), ("Troutdale", "97060"), ("Fairview", "97024"),
            ("Wood Village", "97060"), ("Happy Valley", "97086"),
            ("Clackamas", "97015"), ("Milwaukie", "97222"),
            ("Gladstone", "97027"), ("Oregon City", "97045"),
            ("West Linn", "97068"), ("Estacada", "97023"),
            ("Portland", "97201"), ("Portland", "97209"), ("Portland", "97214"),
            ("Beaverton", "97005"), ("Hillsboro", "97123"),
            ("Lake Oswego", "97034"), ("Tigard", "97223"), ("Tualatin", "97062"),
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
            ("Austin", "78701"), ("Austin", "78741"), ("Austin", "78745"),
            ("Round Rock", "78664"), ("Cedar Park", "78613"),
            ("Georgetown", "78626"), ("Pflugerville", "78660"), ("Kyle", "78640"),
            ("San Marcos", "78666"), ("Leander", "78641"),
        ],
        "Dallas / Fort Worth": [
            ("Dallas", "75201"), ("Dallas", "75228"), ("Fort Worth", "76101"),
            ("Arlington", "76010"), ("Plano", "75023"), ("Irving", "75060"),
            ("Frisco", "75034"), ("McKinney", "75069"), ("Denton", "76201"),
            ("Grand Prairie", "75050"), ("Garland", "75040"),
            ("Richardson", "75080"), ("Mesquite", "75149"),
        ],
        "Houston Metro": [
            ("Houston", "77001"), ("Houston", "77004"), ("Houston", "77057"),
            ("Sugar Land", "77478"), ("Pearland", "77581"),
            ("League City", "77573"), ("Pasadena", "77501"), ("Baytown", "77520"),
            ("The Woodlands", "77380"), ("Katy", "77449"), ("Cypress", "77429"),
        ],
        "San Antonio Area": [
            ("San Antonio", "78201"), ("San Antonio", "78245"),
            ("New Braunfels", "78130"), ("Seguin", "78155"),
            ("Boerne", "78006"), ("Schertz", "78154"),
        ],
        "El Paso Area": [
            ("El Paso", "79901"), ("Socorro", "79927"), ("Horizon City", "79928"),
        ],
    },
    "Washington": {
        "Vancouver / Camas": [
            ("Vancouver", "98660"), ("Vancouver", "98661"), ("Vancouver", "98664"),
            ("Camas", "98607"), ("Washougal", "98671"),
            ("Battle Ground", "98604"), ("Brush Prairie", "98606"),
            ("Ridgefield", "98642"),
        ],
    },
    "Florida": {
        "Tampa Bay": [
            ("Tampa", "33602"), ("Tampa", "33609"), ("St. Petersburg", "33701"),
            ("Clearwater", "33755"), ("Brandon", "33510"), ("Lakeland", "33801"),
            ("Plant City", "33563"), ("Riverview", "33578"),
        ],
        "Orlando Metro": [
            ("Orlando", "32801"), ("Orlando", "32819"), ("Kissimmee", "34741"),
            ("Sanford", "32771"), ("Clermont", "34711"), ("Deltona", "32725"),
            ("Daytona Beach", "32114"), ("Ocala", "34470"),
        ],
        "Jacksonville": [
            ("Jacksonville", "32202"), ("Jacksonville", "32210"),
            ("St. Augustine", "32080"), ("Orange Park", "32073"),
            ("Fleming Island", "32003"), ("Fernandina Beach", "32034"),
        ],
    },
    "Arizona": {
        "Phoenix Metro": [
            ("Phoenix", "85004"), ("Phoenix", "85008"), ("Phoenix", "85041"),
            ("Mesa", "85201"), ("Chandler", "85224"), ("Scottsdale", "85251"),
            ("Gilbert", "85233"), ("Tempe", "85281"), ("Glendale", "85301"),
            ("Peoria", "85345"), ("Surprise", "85374"), ("Goodyear", "85338"),
        ],
        "Tucson Area": [
            ("Tucson", "85701"), ("Tucson", "85710"),
            ("Marana", "85653"), ("Oro Valley", "85737"),
            ("Sierra Vista", "85635"), ("Casa Grande", "85122"),
        ],
    },
    "Georgia": {
        "Metro Atlanta": [
            ("Atlanta", "30303"), ("Atlanta", "30318"),
            ("Marietta", "30060"), ("Decatur", "30030"),
            ("Lawrenceville", "30046"), ("Kennesaw", "30144"),
            ("Roswell", "30075"), ("Alpharetta", "30009"),
            ("Smyrna", "30080"), ("Douglasville", "30134"),
        ],
        "Augusta / Savannah": [
            ("Augusta", "30901"), ("Savannah", "31401"),
            ("Evans", "30809"), ("Hinesville", "31313"),
            ("Statesboro", "30458"), ("Warner Robins", "31088"),
        ],
    },
    "North Carolina": {
        "Charlotte Metro": [
            ("Charlotte", "28202"), ("Charlotte", "28205"),
            ("Concord", "28025"), ("Gastonia", "28052"),
            ("Huntersville", "28078"), ("Mooresville", "28115"),
            ("Matthews", "28105"), ("Kannapolis", "28081"),
        ],
        "Raleigh-Durham": [
            ("Raleigh", "27601"), ("Raleigh", "27610"),
            ("Durham", "27701"), ("Cary", "27511"),
            ("Chapel Hill", "27514"), ("Wake Forest", "27587"),
            ("Apex", "27502"), ("Holly Springs", "27540"),
        ],
    },
    "Ohio": {
        "Columbus Metro": [
            ("Columbus", "43215"), ("Columbus", "43204"),
            ("Dublin", "43017"), ("Westerville", "43081"),
            ("Grove City", "43123"), ("Reynoldsburg", "43068"),
            ("Gahanna", "43230"), ("Hilliard", "43026"),
        ],
        "Cleveland / Akron": [
            ("Cleveland", "44113"), ("Cleveland", "44102"),
            ("Akron", "44308"), ("Parma", "44134"),
            ("Lakewood", "44107"), ("Mentor", "44060"),
            ("Canton", "44702"), ("Elyria", "44035"),
        ],
    },
    "Tennessee": {
        "Nashville Metro": [
            ("Nashville", "37201"), ("Nashville", "37209"),
            ("Franklin", "37064"), ("Murfreesboro", "37129"),
            ("Hendersonville", "37075"), ("Clarksville", "37040"),
            ("Gallatin", "37066"), ("Lebanon", "37087"),
        ],
        "Memphis Area": [
            ("Memphis", "38103"), ("Memphis", "38116"),
            ("Germantown", "38138"), ("Bartlett", "38134"),
            ("Collierville", "38017"), ("Arlington", "38002"),
        ],
    },
    "California": {
        "Sacramento Metro": [
            ("Sacramento", "95814"), ("Sacramento", "95816"),
            ("Elk Grove", "95624"), ("Roseville", "95661"),
            ("Folsom", "95630"), ("Citrus Heights", "95610"),
            ("Rancho Cordova", "95670"), ("Rocklin", "95677"),
        ],
        "Central Valley": [
            ("Fresno", "93720"), ("Bakersfield", "93301"),
            ("Stockton", "95202"), ("Modesto", "95354"),
            ("Visalia", "93291"), ("Merced", "95340"),
            ("Hanford", "93230"), ("Tulare", "93274"),
        ],
        "Inland Empire": [
            ("Riverside", "92501"), ("San Bernardino", "92401"),
            ("Moreno Valley", "92553"), ("Ontario", "91761"),
            ("Fontana", "92335"), ("Rancho Cucamonga", "91730"),
            ("Corona", "92879"), ("Perris", "92570"),
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
    "Williams & Williams",
    "Xome",
    "ServiceLink",
    "Foreclosure.com",
    "RealtyTrac",
    "Bid4Assets",
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
    "Xome": "https://www.xome.com",
    "ServiceLink": "https://www.svclnk.com",
    "Foreclosure.com": "https://www.foreclosure.com",
    "RealtyTrac": "https://www.realtytrac.com",
    "Bid4Assets": "https://www.bid4assets.com",
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
    "Colorado": 230,
    "Florida": 190,
    "Georgia": 165,
    "North Carolina": 175,
    "Ohio": 130,
    "Tennessee": 155,
}

# State property tax rate ranges (used by mock generator)
STATE_TAX_RATES = {
    "Oregon": (0.009, 0.012),
    "Texas": (0.016, 0.025),
    "Washington": (0.009, 0.012),
    "Florida": (0.008, 0.012),
    "Arizona": (0.006, 0.010),
    "Georgia": (0.008, 0.012),
    "North Carolina": (0.008, 0.011),
    "Ohio": (0.015, 0.022),
    "Tennessee": (0.005, 0.009),
    "California": (0.007, 0.011),
}

# Approximate city-center coordinates for geolocation (lat, lng)
CITY_COORDINATES = {
    # Oregon
    ("Portland", "Oregon"): (45.5152, -122.6784),
    ("Beaverton", "Oregon"): (45.4871, -122.8037),
    ("Hillsboro", "Oregon"): (45.5229, -122.9898),
    ("Gresham", "Oregon"): (45.4983, -122.4310),
    ("Lake Oswego", "Oregon"): (45.4207, -122.6706),
    ("Tigard", "Oregon"): (45.4312, -122.7715),
    ("Tualatin", "Oregon"): (45.3838, -122.7637),
    ("Oregon City", "Oregon"): (45.3573, -122.6068),
    ("West Linn", "Oregon"): (45.3654, -122.6120),
    ("Salem", "Oregon"): (44.9429, -123.0351),
    ("Keizer", "Oregon"): (44.9901, -123.0262),
    ("Albany", "Oregon"): (44.6366, -123.1059),
    ("Corvallis", "Oregon"): (44.5646, -123.2620),
    ("McMinnville", "Oregon"): (45.2101, -123.1986),
    ("Woodburn", "Oregon"): (45.1437, -122.8554),
    ("Eugene", "Oregon"): (44.0521, -123.0868),
    ("Springfield", "Oregon"): (44.0462, -123.0220),
    ("Cottage Grove", "Oregon"): (43.7979, -123.0596),
    ("Bend", "Oregon"): (44.0582, -121.3153),
    ("Redmond", "Oregon"): (44.2726, -121.1739),
    ("Madras", "Oregon"): (44.6335, -121.1295),
    ("Prineville", "Oregon"): (44.2999, -120.7343),
    ("Sisters", "Oregon"): (44.2910, -121.5492),
    ("Medford", "Oregon"): (42.3265, -122.8756),
    ("Ashland", "Oregon"): (42.1946, -122.7095),
    ("Grants Pass", "Oregon"): (42.4390, -123.3284),
    ("Klamath Falls", "Oregon"): (42.2249, -121.7817),
    ("Roseburg", "Oregon"): (43.2165, -123.3417),
    ("Troutdale", "Oregon"): (45.5387, -122.3871),
    ("Fairview", "Oregon"): (45.5390, -122.4339),
    ("Wood Village", "Oregon"): (45.5335, -122.4186),
    ("Happy Valley", "Oregon"): (45.4449, -122.5131),
    ("Clackamas", "Oregon"): (45.4076, -122.5726),
    ("Milwaukie", "Oregon"): (45.4428, -122.6393),
    ("Gladstone", "Oregon"): (45.3807, -122.5957),
    ("Estacada", "Oregon"): (45.2896, -122.3334),
    # Texas
    ("Austin", "Texas"): (30.2672, -97.7431),
    ("Round Rock", "Texas"): (30.5083, -97.6789),
    ("Cedar Park", "Texas"): (30.5052, -97.8203),
    ("Georgetown", "Texas"): (30.6333, -97.6781),
    ("Pflugerville", "Texas"): (30.4394, -97.6200),
    ("Kyle", "Texas"): (29.9889, -97.8772),
    ("San Marcos", "Texas"): (29.8833, -97.9414),
    ("Leander", "Texas"): (30.5788, -97.8531),
    ("Dallas", "Texas"): (32.7767, -96.7970),
    ("Fort Worth", "Texas"): (32.7555, -97.3308),
    ("Arlington", "Texas"): (32.7357, -97.1081),
    ("Plano", "Texas"): (33.0198, -96.6989),
    ("Irving", "Texas"): (32.8140, -96.9489),
    ("Frisco", "Texas"): (33.1507, -96.8236),
    ("McKinney", "Texas"): (33.1972, -96.6397),
    ("Denton", "Texas"): (33.2148, -97.1331),
    ("Grand Prairie", "Texas"): (32.7459, -96.9978),
    ("Garland", "Texas"): (32.9126, -96.6389),
    ("Richardson", "Texas"): (32.9483, -96.7299),
    ("Mesquite", "Texas"): (32.7668, -96.5992),
    ("Houston", "Texas"): (29.7604, -95.3698),
    ("Sugar Land", "Texas"): (29.6197, -95.6349),
    ("Pearland", "Texas"): (29.5636, -95.2860),
    ("League City", "Texas"): (29.5075, -95.0950),
    ("Pasadena", "Texas"): (29.6911, -95.2091),
    ("Baytown", "Texas"): (29.7355, -94.9774),
    ("The Woodlands", "Texas"): (30.1658, -95.4613),
    ("Katy", "Texas"): (29.7858, -95.8245),
    ("Cypress", "Texas"): (29.9691, -95.6970),
    ("San Antonio", "Texas"): (29.4241, -98.4936),
    ("New Braunfels", "Texas"): (29.7030, -98.1245),
    ("Seguin", "Texas"): (29.5688, -97.9647),
    ("Boerne", "Texas"): (29.7947, -98.7320),
    ("Schertz", "Texas"): (29.5522, -98.2697),
    ("El Paso", "Texas"): (31.7619, -106.4850),
    ("Socorro", "Texas"): (31.6545, -106.3031),
    ("Horizon City", "Texas"): (31.6929, -106.2068),
    # Washington
    ("Vancouver", "Washington"): (45.6387, -122.6615),
    ("Camas", "Washington"): (45.5871, -122.3998),
    ("Washougal", "Washington"): (45.5832, -122.3535),
    ("Battle Ground", "Washington"): (45.7807, -122.5337),
    ("Brush Prairie", "Washington"): (45.7321, -122.4854),
    ("Ridgefield", "Washington"): (45.8151, -122.7429),
    # Florida
    ("Tampa", "Florida"): (27.9506, -82.4572),
    ("St. Petersburg", "Florida"): (27.7676, -82.6403),
    ("Clearwater", "Florida"): (27.9659, -82.8001),
    ("Brandon", "Florida"): (27.9378, -82.2859),
    ("Lakeland", "Florida"): (28.0395, -81.9498),
    ("Plant City", "Florida"): (28.0186, -82.1193),
    ("Riverview", "Florida"): (27.8661, -82.3265),
    ("Orlando", "Florida"): (28.5383, -81.3792),
    ("Kissimmee", "Florida"): (28.2920, -81.4076),
    ("Sanford", "Florida"): (28.8003, -81.2731),
    ("Clermont", "Florida"): (28.5494, -81.7729),
    ("Deltona", "Florida"): (28.9005, -81.2637),
    ("Daytona Beach", "Florida"): (29.2108, -81.0228),
    ("Ocala", "Florida"): (29.1872, -82.1401),
    ("Jacksonville", "Florida"): (30.3322, -81.6557),
    ("St. Augustine", "Florida"): (29.8946, -81.3145),
    ("Orange Park", "Florida"): (30.1666, -81.7065),
    ("Fleming Island", "Florida"): (30.0935, -81.7187),
    ("Fernandina Beach", "Florida"): (30.6697, -81.4628),
    # Arizona
    ("Phoenix", "Arizona"): (33.4484, -112.0740),
    ("Mesa", "Arizona"): (33.4152, -111.8315),
    ("Chandler", "Arizona"): (33.3062, -111.8413),
    ("Scottsdale", "Arizona"): (33.4942, -111.9261),
    ("Gilbert", "Arizona"): (33.3528, -111.7890),
    ("Tempe", "Arizona"): (33.4255, -111.9400),
    ("Glendale", "Arizona"): (33.5387, -112.1860),
    ("Peoria", "Arizona"): (33.5806, -112.2374),
    ("Surprise", "Arizona"): (33.6292, -112.3679),
    ("Goodyear", "Arizona"): (33.4353, -112.3585),
    ("Tucson", "Arizona"): (32.2226, -110.9747),
    ("Marana", "Arizona"): (32.4368, -111.2253),
    ("Oro Valley", "Arizona"): (32.3909, -110.9665),
    ("Sierra Vista", "Arizona"): (31.5455, -110.3035),
    ("Casa Grande", "Arizona"): (32.8795, -111.7574),
    # Georgia
    ("Atlanta", "Georgia"): (33.7490, -84.3880),
    ("Marietta", "Georgia"): (33.9526, -84.5499),
    ("Decatur", "Georgia"): (33.7748, -84.2963),
    ("Lawrenceville", "Georgia"): (33.9562, -83.9879),
    ("Kennesaw", "Georgia"): (34.0234, -84.6155),
    ("Roswell", "Georgia"): (34.0232, -84.3616),
    ("Alpharetta", "Georgia"): (34.0754, -84.2941),
    ("Smyrna", "Georgia"): (33.8839, -84.5144),
    ("Douglasville", "Georgia"): (33.7515, -84.7477),
    ("Augusta", "Georgia"): (33.4735, -81.9748),
    ("Savannah", "Georgia"): (32.0809, -81.0912),
    ("Evans", "Georgia"): (33.5337, -82.1307),
    ("Hinesville", "Georgia"): (31.8468, -81.5962),
    ("Statesboro", "Georgia"): (32.4488, -81.7832),
    ("Warner Robins", "Georgia"): (32.6130, -83.6243),
    # North Carolina
    ("Charlotte", "North Carolina"): (35.2271, -80.8431),
    ("Concord", "North Carolina"): (35.4088, -80.5795),
    ("Gastonia", "North Carolina"): (35.2621, -81.1873),
    ("Huntersville", "North Carolina"): (35.4107, -80.8429),
    ("Mooresville", "North Carolina"): (35.5849, -80.8101),
    ("Matthews", "North Carolina"): (35.1168, -80.7237),
    ("Kannapolis", "North Carolina"): (35.4874, -80.6217),
    ("Raleigh", "North Carolina"): (35.7796, -78.6382),
    ("Durham", "North Carolina"): (35.9940, -78.8986),
    ("Cary", "North Carolina"): (35.7915, -78.7811),
    ("Chapel Hill", "North Carolina"): (35.9132, -79.0558),
    ("Wake Forest", "North Carolina"): (35.9799, -78.5097),
    ("Apex", "North Carolina"): (35.7327, -78.8503),
    ("Holly Springs", "North Carolina"): (35.6513, -78.8336),
    # Ohio
    ("Columbus", "Ohio"): (39.9612, -82.9988),
    ("Dublin", "Ohio"): (40.0992, -83.1141),
    ("Westerville", "Ohio"): (40.1262, -82.9291),
    ("Grove City", "Ohio"): (39.8812, -83.0930),
    ("Reynoldsburg", "Ohio"): (39.9551, -82.8121),
    ("Gahanna", "Ohio"): (40.0192, -82.8791),
    ("Hilliard", "Ohio"): (40.0334, -83.1588),
    ("Cleveland", "Ohio"): (41.4993, -81.6944),
    ("Akron", "Ohio"): (41.0814, -81.5190),
    ("Parma", "Ohio"): (41.4048, -81.7229),
    ("Lakewood", "Ohio"): (41.4819, -81.7982),
    ("Mentor", "Ohio"): (41.6661, -81.3396),
    ("Canton", "Ohio"): (40.7989, -81.3784),
    ("Elyria", "Ohio"): (41.3684, -82.1076),
    # Tennessee
    ("Nashville", "Tennessee"): (36.1627, -86.7816),
    ("Franklin", "Tennessee"): (35.9251, -86.8689),
    ("Murfreesboro", "Tennessee"): (35.8456, -86.3903),
    ("Hendersonville", "Tennessee"): (36.3048, -86.6200),
    ("Clarksville", "Tennessee"): (36.5298, -87.3595),
    ("Gallatin", "Tennessee"): (36.3887, -86.4467),
    ("Lebanon", "Tennessee"): (36.2081, -86.2911),
    ("Memphis", "Tennessee"): (35.1495, -90.0490),
    ("Germantown", "Tennessee"): (35.0868, -89.8100),
    ("Bartlett", "Tennessee"): (35.2045, -89.8739),
    ("Collierville", "Tennessee"): (35.0420, -89.6645),
    ("Arlington", "Tennessee"): (35.2962, -89.6615),
    # California
    ("Sacramento", "California"): (38.5816, -121.4944),
    ("Elk Grove", "California"): (38.4088, -121.3716),
    ("Roseville", "California"): (38.7521, -121.2880),
    ("Folsom", "California"): (38.6780, -121.1761),
    ("Citrus Heights", "California"): (38.7071, -121.2810),
    ("Rancho Cordova", "California"): (38.5891, -121.3027),
    ("Rocklin", "California"): (38.7908, -121.2358),
    ("Fresno", "California"): (36.7378, -119.7871),
    ("Bakersfield", "California"): (35.3733, -119.0187),
    ("Stockton", "California"): (37.9577, -121.2908),
    ("Modesto", "California"): (37.6391, -120.9969),
    ("Visalia", "California"): (36.3302, -119.2921),
    ("Merced", "California"): (37.3022, -120.4830),
    ("Hanford", "California"): (36.3274, -119.6457),
    ("Tulare", "California"): (36.2077, -119.3473),
    ("Riverside", "California"): (33.9806, -117.3755),
    ("San Bernardino", "California"): (34.1083, -117.2898),
    ("Moreno Valley", "California"): (33.9425, -117.2297),
    ("Ontario", "California"): (34.0633, -117.6509),
    ("Fontana", "California"): (34.0922, -117.4350),
    ("Rancho Cucamonga", "California"): (34.1064, -117.5931),
    ("Corona", "California"): (33.8753, -117.5664),
    ("Perris", "California"): (33.7825, -117.2286),
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
    "apify_token": _local_keys.get("apify_token"),          # Apify API token for Auction.com scraping
    "zillow": None,
    "redfin": None,
    "auction_com": None,
    "realtor_com": None,
}

# Redfin Scraper Settings (used by scraper_redfin.py)
REDFIN_RATE_LIMIT = 3          # Seconds between requests
REDFIN_MAX_RETRIES = 2         # Retries per ZIP on failure
REDFIN_TIMEOUT = 15            # HTTP timeout in seconds
REDFIN_CIRCUIT_BREAKER = 3     # Consecutive failures before stopping
REDFIN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Oregon Sheriff's Sales Scraper Settings (used by scraper_orsheriff.py)
SHERIFF_RATE_LIMIT = 2           # Seconds between requests
SHERIFF_MAX_RETRIES = 2          # Retries per county on failure
SHERIFF_TIMEOUT = 15             # HTTP timeout in seconds
SHERIFF_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Sheriff scraper county configuration
# Which Oregon counties to scrape. Only Deschutes for initial test.
# Add more from scraper_orsheriff.COUNTY_SLUGS as needed:
#   "multnomah", "clackamas", "washington", "marion", "lane",
#   "jackson", "josephine", etc.
SHERIFF_COUNTIES = [
    "deschutes",                          # Deschutes County (Bend area)
    # "multnomah",                        # Multnomah County (Portland/Gresham)
    # "clackamas",                        # Clackamas County (Oregon City/Happy Valley)
    # "crook", "jefferson",              # Central Oregon (expand later)
    # "jackson", "josephine", "douglas", # Southern Oregon / Medford (expand later)
    # "klamath", "lane",                 # Shared / extended (expand later)
]

# Auction.com Scraper Settings (uses Apify cloud, requires apify_token)
AUCTIONCOM_TIMEOUT = 300        # Seconds to wait for Apify run (county pages can be slow)
AUCTIONCOM_MAX_ITEMS = 50       # Max properties per run (keep low to reduce cost)
AUCTIONCOM_STATES = ["Oregon"]  # States to search (fallback if no counties set)

# County-level targeting — much cheaper & more relevant than state-level scraping
# Format: list of (county_slug, state_abbrev) tuples
# URL pattern: https://www.auction.com/residential/{st}/{county}-county
AUCTIONCOM_COUNTIES = [
    ("deschutes", "or"),   # Bend, Redmond, La Pine, Sisters
    ("jackson", "or"),     # Medford, Ashland, Central Point (within 15 mi)
    # ("multnomah", "or"),   # Portland, Gresham, Troutdale, Fairview
    # ("clackamas", "or"),   # Oregon City, Happy Valley, Milwaukie, Estacada
    # ("clark", "wa"),       # Vancouver, Camas, Washougal, Battle Ground

    # Future: expand Central Oregon (~50 mi of Bend)
    # ("crook", "or"),       # Prineville (~29 mi from Bend)
    # ("jefferson", "or"),   # Madras, Culver (~41 mi from Bend)

    # Future: Southern Oregon (beyond 15 mi of Medford)
    # ("josephine", "or"),   # Grants Pass, Cave Junction (~24 mi)
    # ("douglas", "or"),     # Myrtle Creek, Canyonville, Roseburg (~35-66 mi)

    # Future: shared / extended
    # ("klamath", "or"),     # Klamath Falls (within both radii)
    # ("lane", "or"),        # Eugene/Springfield (Lane border ~30 mi W of Bend)

    # Future: Leander, TX area (~40 mi)
    # ("williamson", "tx"),  # Georgetown, Round Rock, Cedar Park
    # ("travis", "tx"),      # Austin, Leander
    # ("bell", "tx"),        # Killeen, Temple (~40 mi N)
    # ("burnet", "tx"),      # Marble Falls (~35 mi W)
]

# Output settings
OUTPUT_JSON_FILE = "property_analysis.json"
OUTPUT_CSV_FILE = "properties.csv"
ENABLE_CSV_EXPORT = True

# Web server settings
DEFAULT_PORT = 8000
DASHBOARD_FILE = "index.html"
