# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Generate mock data, run analysis, export all formats
python3 main.py --mock

# Custom property count
python3 main.py --mock --count 100

# Custom filters
python3 main.py --mock --min-margin 35 --max-price 500000 --max-repairs 60000

# Scrape REAL MLS foreclosures from Redfin (no API key needed!)
python3 main.py --scrape

# Scrape with wider ZIP coverage
python3 main.py --scrape --max-zips 20 --count 100

# Scrape Oregon sheriff's sales (real courthouse auctions, no API key needed!)
python3 main.py --sheriff

# Fetch Auction.com listings via Apify cloud (requires apify_token)
python3 main.py --auction-com

# Fetch real properties from ATTOM + BatchData APIs (requires keys)
python3 main.py --real

# Real data with more ZIP codes scanned
python3 main.py --real --max-zips 20 --count 100

# Enrich mock data with live API data (Census, ATTOM)
python3 main.py --mock --enrich

# Re-export existing data without re-running analysis
python3 main.py --export-only

# Show top N deals
python3 main.py --mock --top 10

# Compare state markets
python3 main.py --mock --compare-states

# Check API key configuration
python3 main.py --api-status

# Standalone entry point (delegates to main.py --mock)
python3 property_analyzer.py

# Serve dashboard (then open http://localhost:8000/index.html)
python3 -m http.server 8000
```

There is no test suite. No external dependencies are required for core functionality (stdlib only).

## Architecture

`property_analyzer.py` is a thin wrapper that delegates to `main.py --mock`.

### Data Flow
Config constants → `MockDataGenerator` (or `auction_fetcher.py` for real data) → `Property` dataclass objects (with `calculate_metrics()`) → `PropertyAnalyzer` (filter/analyze) → `AnalysisResult` → `DataExporter` (JSON/CSV/TXT/HTML) → `property_analysis.json` → `index.html` dashboard (client-side JS)

### Key Modules
- **`config.py`**: All constants, thresholds, and geographic data. `REGION_DEFINITIONS` is the single source of truth for state→region→city/zip mapping. `SCORING_THRESHOLDS` centralizes deal scoring parameters. `CITY_COORDINATES` provides geolocation for mock data. `STATE_TAX_RATES` drives state-specific tax generation. API keys loaded from `.api_keys.json` or env vars (`ATTOM_API_KEY`, `BATCHDATA_API_KEY`, `CENSUS_API_KEY`, `HUD_API_KEY`, `APIFY_TOKEN`).
- **`models.py`**: `Property` and `AnalysisResult` dataclasses. `Property` uses `@dataclass` — non-default fields must precede default fields (Python 3.9 constraint). Scoring logic in `_calculate_deal_score()` reads all thresholds from `config.SCORING_THRESHOLDS`.
- **`analyzer.py`**: `PropertyAnalyzer` — loads, filters, and analyzes properties. Produces statistics by city/region/platform.
- **`exporter.py`**: `DataExporter` with static methods: `export_to_json`, `export_to_csv`, `export_to_text`, `export_to_html`. CSV columns are generated dynamically from `Property` dataclass fields.
- **`data_generator.py`**: `MockDataGenerator` — creates realistic properties with distribution (25% hot / 25% excellent / 25% good / 25% mediocre). Populates occupancy, condition, tax, rent, geolocation, and sale history fields.
- **`property_analyzer.py`**: Thin wrapper — imports and calls `main.main()`, defaults to `--mock` if no args given.

### Data Sources (5 modes)
| CLI Flag | Source | Cost | Data | Dashboard Badge |
|----------|--------|------|------|-----------------|
| `--mock` | Synthetic generator | Free | Fake properties for testing | Yellow "MOCK" |
| `--scrape` | Redfin Stingray API | Free | Real MLS-listed foreclosures | Green "REAL MLS DATA" |
| `--sheriff` | oregonsheriffssales.org | Free | Real courthouse auction listings | Red "SHERIFF SALE" |
| `--auction-com` | Auction.com via Apify | ~$0.01/property | Real Auction.com listings | Blue "AUCTION.COM" |
| `--real` | ATTOM + BatchData APIs | Paid keys | Public records + pre-foreclosures | No badge |

### Scraper Modules
- **`scraper_redfin.py`**: Redfin Stingray API scraper. Fetches real MLS-listed foreclosures/bank-owned properties via the public `gis-csv` endpoint. Uses `poly` parameter (lat/lng bounding box) — NOT `region_id` (which uses Redfin's internal IDs, not ZIP codes). No API key required. Rate-limited to 3s between requests. Circuit breaker stops after consecutive failures. Invoked via `--scrape` CLI flag.
- **`scraper_orsheriff.py`**: Oregon Sheriff's Sales scraper. Fetches judicial foreclosure auction listings from oregonsheriffssales.org by county. Parses HTML listing cards for address, sale date/time, case parties, PDF links. County-based (not ZIP-based). Configured via `config.SHERIFF_COUNTIES`. Invoked via `--sheriff` CLI flag.
- **`scraper_auctioncom.py`**: Auction.com scraper via Apify cloud (ParseForge PPE actor). Sends state-level Auction.com URLs to Apify's REST API, which runs a headless browser to bypass Incapsula WAF. Supports sync (run-sync-get-dataset-items) and async (poll) modes. Requires `apify_token` in `.api_keys.json`. Invoked via `--auction-com` CLI flag.

### API Integration (optional, for real data)
- **`api_attom.py`**: ATTOM Property API via RapidAPI (AVM valuations, sales history). 2-second rate limit on free tier.
- **`api_batchdata.py`**: BatchData API (foreclosure lookups, pre-foreclosure searches). Bearer token auth.
- **`api_census.py`**: US Census ACS + HUD fair market rent. Free, no key required (500/day limit).
- **`data_fetcher.py`**: Unified orchestrator that enriches Property objects with live API data. Caches Census data by ZIP. Each API call is wrapped in try/except for graceful degradation.
- **`auction_fetcher.py`**: Fetches real properties from all sources (ATTOM, BatchData, Redfin, Sheriff, Auction.com), deduplicates by normalized address, builds `Property` objects. `sources` parameter controls which backends to use. State-level sources (Auction.com, Sheriff) run before the ZIP loop.

### Geographic Coverage (10 states, ~23 regions, ~170 cities)
| State | Regions | Notes |
|-------|---------|-------|
| Oregon | Portland Metro, Salem/Mid-Valley, Eugene/Lane, Central Oregon, Southern Oregon | Original state |
| Texas | Greater Austin, DFW, Houston Metro, San Antonio, El Paso | Original state |
| Washington | Southern Washington / Vancouver | Original state |
| Florida | Tampa Bay, Orlando Metro, Jacksonville | $190/sqft |
| Arizona | Phoenix Metro, Tucson Area | $170/sqft |
| Georgia | Metro Atlanta, Augusta/Savannah | $165/sqft |
| North Carolina | Charlotte Metro, Raleigh-Durham | $175/sqft |
| Ohio | Columbus Metro, Cleveland/Akron | $130/sqft |
| Tennessee | Nashville Metro, Memphis Area | $155/sqft |
| California | Sacramento Metro, Central Valley, Inland Empire | $350/sqft |

### Dashboard (`index.html`)
Static HTML that loads `property_analysis.json` via `fetch()`. All filtering/sorting is client-side JavaScript. Must be served via HTTP server (not `file://`) due to fetch.

**UI Features:**
- Dynamic state/region dropdowns populated from JS `REGION_DEFINITIONS` object
- Text search (address, city, ID, foreclosing entity) with debounce
- CSV export button (generates downloadable CSV from visible properties)
- Auction countdown timers (color-coded: red ≤3d, amber ≤7d)
- SVG bar chart (properties by state)
- Dark mode toggle (persisted via localStorage)
- Per-property notes (persisted via localStorage)
- Comparison mode (select up to 4 properties for side-by-side metrics)
- Property cards show occupancy, condition, tax, HOA, rent, last sale, max bid price
- Source-specific badges: blue (Auction.com), red (Sheriff Sale), green (Redfin MLS), yellow (Mock)
- Source-specific disclaimers: each data source gets its own colored banner

### Auction Platforms (12)
Auction.com, Hubzu, RealtyBid, HomePath, Bank Foreclosure, Hudson & Marshall, Williams & Williams, Xome, ServiceLink, Foreclosure.com, RealtyTrac, Bid4Assets

## Key Constraints

- **Dataclass field ordering**: When adding fields to `Property` in `models.py`, non-default fields CANNOT follow default fields. Place new default fields after all required fields.
- **`REGION_DEFINITIONS` is authoritative**: To add cities/states, add them to `REGION_DEFINITIONS` in `config.py`. Derived structures (`STATE_CITIES`, `CITY_TO_REGION`) are computed automatically. Also update `CITY_COORDINATES`, `STATE_TAX_RATES`, and `PRICE_PER_SQFT` for new states.
- **Dashboard sync**: When adding states/regions, update both `config.py` (data side) and the `REGION_DEFINITIONS` JS object in `index.html` (UI side).
- **Scoring thresholds**: All deal scoring magic numbers live in `config.SCORING_THRESHOLDS`. Update there, not in `models.py`.
- **`ACTIVE_REGIONS`**: Controls which regions are scanned for real API data. Set to `None` to include all regions, `[]` to disable a state, or a list of region names to restrict. Does not affect mock data generation.
- **API keys**: Store in `.api_keys.json` (gitignored) or set environment variables. Never commit keys.
- **`--mock`, `--real`, `--scrape`, `--sheriff`, `--auction-com` are mutually exclusive**: Cannot use more than one in the same run.
- **Profit formula**: `Total Investment = auction_price + repairs + closing(3%) + holding(ARV×1%×6mo)`. `Profit = ARV - total_investment - selling(ARV×8%)`. Max bid price uses 70% rule with 91% safety factor: `(ARV × 0.70 - repairs) × 0.91`. Recommended threshold: margin ≥ 30%, repairs ≤ $80k, score ≥ 60.
- **Redfin `region_id` is NOT a ZIP code**: The `poly` parameter (lat/lng bounding box) must be used instead. Coordinates are resolved from `config.CITY_COORDINATES`.
- **Sheriff scraper is county-based**: Uses `config.SHERIFF_COUNTIES` list. Add county names (lowercase) to expand coverage. County→region mapping is in `scraper_orsheriff.COUNTY_TO_REGION`.
- **Auction.com blocks direct scraping**: Incapsula WAF blocks all automated requests. Must use Apify cloud (headless browser) as proxy. The `apify_token` key is required.
