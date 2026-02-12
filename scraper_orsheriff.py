#!/usr/bin/env python3
"""
Oregon Sheriff's Sales scraper — oregonsheriffssales.org

Scrapes judicial foreclosure auction listings from the Oregon State Sheriffs'
Association website. These are real courthouse-step sheriff's sales (not MLS
listings) with confirmed sale dates, case info, and Notice of Sale PDFs.

Data source: https://oregonsheriffssales.org/county/{county_name}/
Each county page has HTML listing cards with address, sale date/time,
case parties, PDF links, and a detail page URL.

Rate-limited to 2 seconds between requests to be respectful.

Data flow:
  scrape_county(county_name) → List[Dict]  (raw property dicts)
  ↓
  Fed into auction_fetcher._build_property_from_raw() via source="sheriff"
"""

import re
import ssl
import time
import random
from typing import List, Dict, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from datetime import datetime

# Try to import config for settings; fall back to defaults
try:
    import config as _cfg
    RATE_LIMIT = getattr(_cfg, "SHERIFF_RATE_LIMIT", 2)
    MAX_RETRIES = getattr(_cfg, "SHERIFF_MAX_RETRIES", 2)
    TIMEOUT = getattr(_cfg, "SHERIFF_TIMEOUT", 15)
    USER_AGENT = getattr(_cfg, "SHERIFF_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36")
except ImportError:
    RATE_LIMIT = 2
    MAX_RETRIES = 2
    TIMEOUT = 15
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

BASE_URL = "https://oregonsheriffssales.org"

# County name → URL slug mapping
# Covers ~50 mi from Bend + ~50 mi from Medford
COUNTY_SLUGS = {
    # Central Oregon (Bend area)
    "deschutes": "deschutes",
    "crook": "crook",
    "jefferson": "jefferson",
    # Southern Oregon (Medford area)
    "jackson": "jackson",
    "josephine": "josephine",
    "douglas": "douglas",
    # Shared / extended
    "klamath": "klamath",
    "lane": "lane",
}

# County → region mapping (matches config.REGION_DEFINITIONS for Oregon)
COUNTY_TO_REGION = {
    "deschutes": "Central Oregon",
    "multnomah": "Portland Metro",
    "clackamas": "Portland Metro",
    "washington": "Portland Metro",
    "marion": "Salem / Mid-Valley",
    "polk": "Salem / Mid-Valley",
    "lane": "Eugene / Lane County",
    "jackson": "Southern Oregon",
    "josephine": "Southern Oregon",
    "douglas": "Southern Oregon",
    "benton": "Salem / Mid-Valley",
    "linn": "Salem / Mid-Valley",
    "yamhill": "Portland Metro",
    "lincoln": "Eugene / Lane County",
    "klamath": "Southern Oregon",
    "jefferson": "Central Oregon",
    "coos": "Southern Oregon",
    "curry": "Southern Oregon",
    "union": "Central Oregon",
}

# Track consecutive failures for circuit breaker
_consecutive_failures = 0
CIRCUIT_BREAKER_LIMIT = 3


def scrape_county(county_name: str, timeout: int = None) -> List[Dict]:
    """
    Scrape all sheriff's sale listings for a single Oregon county.

    Args:
        county_name: County name (lowercase), e.g. "deschutes", "multnomah"
        timeout: HTTP timeout in seconds

    Returns:
        List of raw property dicts compatible with _build_property_from_raw()
    """
    global _consecutive_failures

    if _consecutive_failures >= CIRCUIT_BREAKER_LIMIT:
        return []

    if timeout is None:
        timeout = TIMEOUT

    slug = COUNTY_SLUGS.get(county_name, county_name)
    url = f"{BASE_URL}/county/{slug}/"

    html = _fetch_page(url, timeout)
    if html is None:
        return []

    properties = _parse_county_page(html, county_name)

    # Rate limiting
    time.sleep(RATE_LIMIT + random.uniform(0, 0.5))

    return properties


def scrape_all_counties(counties: List[str] = None,
                        timeout: int = None,
                        progress: bool = True) -> List[Dict]:
    """
    Scrape sheriff's sale listings from multiple Oregon counties.

    Args:
        counties: List of county names to scrape. Defaults to all in COUNTY_SLUGS.
        timeout: HTTP timeout in seconds
        progress: Print progress updates

    Returns:
        Combined list of raw property dicts from all counties
    """
    if counties is None:
        counties = list(COUNTY_SLUGS.keys())

    all_results = []

    for i, county in enumerate(counties):
        if progress:
            print(f"      [{i+1}/{len(counties)}] Scraping {county.title()} County...")

        results = scrape_county(county, timeout)

        if progress and results:
            print(f"         Found {len(results)} sheriff's sale listings")

        all_results.extend(results)

        # Check circuit breaker
        if _consecutive_failures >= CIRCUIT_BREAKER_LIMIT:
            if progress:
                print("      ⚠ Circuit breaker tripped — stopping county scrape")
            break

    return all_results


def _fetch_page(url: str, timeout: int) -> Optional[str]:
    """
    Fetch HTML content from oregonsheriffssales.org with retry logic.

    Returns HTML string, or None on failure.
    """
    global _consecutive_failures

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
    }

    ctx = ssl.create_default_context()

    for attempt in range(MAX_RETRIES + 1):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                status = resp.getcode()
                if status != 200:
                    print(f"    ⚠ Sheriff's sales returned HTTP {status}")
                    _consecutive_failures += 1
                    return None

                raw = resp.read()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")

                if not text.strip() or text.strip().startswith("<!DOCTYPE") and len(text) < 500:
                    _consecutive_failures += 1
                    return None

                # Success
                _consecutive_failures = 0
                return text

        except HTTPError as e:
            if e.code in (403, 429):
                _consecutive_failures += 1
                if attempt < MAX_RETRIES:
                    wait = RATE_LIMIT * (attempt + 2)
                    time.sleep(wait)
                    continue
                return None
            _consecutive_failures += 1
            return None

        except (URLError, TimeoutError, OSError):
            if attempt < MAX_RETRIES:
                time.sleep(RATE_LIMIT)
                continue
            _consecutive_failures += 1
            return None

        except Exception:
            _consecutive_failures += 1
            return None

    return None


def _parse_county_page(html: str, county_name: str) -> List[Dict]:
    """
    Parse the HTML of a county sheriff's sales page and extract property listings.

    Each listing card has this structure:
        <div class='property-listing-card'>
            <h2 ...><strong>CASE TITLE (includes address in title)</strong></h2>
            <div class="fl-post-excerpt">ADDRESS LINE</div>
            <div class="fl-post-more-link">Sale Date: MM/DD/YYYY</div>
            <div class="fl-post-more-link">Sale Time: HH:MM am/pm</div>
            <a href="...pdf">Notice Of Sale</a>
            <a href="...property-listing/...">View Full Property Listing</a>
        </div>
    """
    properties = []

    # Find all property-listing-card blocks
    # Pattern: from <div class='property-listing-card'> to the closing </a></div>
    card_pattern = re.compile(
        r"<div class='property-listing-card'>(.*?)</div>\s*</a></div>",
        re.DOTALL
    )

    cards = card_pattern.findall(html)

    for card_html in cards:
        parsed = _parse_single_card(card_html, county_name)
        if parsed is not None:
            properties.append(parsed)

    return properties


def _parse_single_card(card_html: str, county_name: str) -> Optional[Dict]:
    """
    Parse a single property listing card HTML into a raw property dict.
    """
    # Extract case title (plaintiff vs defendant, often includes address)
    title_match = re.search(r'<strong>(.*?)</strong>', card_html, re.DOTALL)
    case_title = ""
    if title_match:
        case_title = _clean_html(title_match.group(1))

    # Extract address from the fl-post-excerpt div
    excerpt_match = re.search(
        r'class="fl-post-excerpt"[^>]*>(.*?)</div>',
        card_html, re.DOTALL
    )
    address_raw = ""
    if excerpt_match:
        address_raw = _clean_html(excerpt_match.group(1)).strip()

    if not address_raw:
        return None

    # Parse address into components: "428 SE Warsaw St. Redmond, OR 97756"
    address, city, state, zip_code = _parse_address(address_raw)
    if not address:
        return None

    # Extract sale date: "02/12/2026"
    date_match = re.search(
        r'<strong>Sale Date:\s*</strong></span>\s*([\d/]+)',
        card_html
    )
    sale_date = ""
    if date_match:
        sale_date = date_match.group(1).strip()

    # Extract sale time: "10:00 am"
    time_match = re.search(
        r'<strong>Sale Time:\s*</strong></span>\s*([^<\n]+)',
        card_html
    )
    sale_time = ""
    if time_match:
        sale_time = time_match.group(1).strip()

    # Convert sale date to ISO format: "2026-02-12"
    auction_date = _parse_date(sale_date)

    # Extract PDF URL (Notice of Sale)
    pdf_match = re.search(
        r'href="(https://[^"]+\.pdf)"',
        card_html
    )
    pdf_url = ""
    if pdf_match:
        pdf_url = pdf_match.group(1)

    # Extract listing detail URL
    listing_match = re.search(
        r'href="(https://oregonsheriffssales\.org/property-listing/[^"]+)"',
        card_html
    )
    listing_url = ""
    if listing_match:
        listing_url = listing_match.group(1)

    # Extract foreclosing entity (plaintiff) from case title
    # Pattern: "PLAINTIFF vs. DEFENDANT" or "PLAINTIFF v DEFENDANT"
    foreclosing_entity = _extract_plaintiff(case_title)

    # Determine region from county
    region = COUNTY_TO_REGION.get(county_name, "Oregon")

    return {
        "address": address,
        "city": city,
        "state": "Oregon",
        "zip_code": zip_code,
        "county": county_name.title(),
        "region": region,
        "auction_date": auction_date,
        "sale_time": sale_time,
        "case_title": case_title,
        "foreclosing_entity": foreclosing_entity,
        "foreclosure_stage": "Sheriff Sale Scheduled",
        "pdf_url": pdf_url,
        "listing_url": listing_url,
        "sale_type": "Sheriff Sale",
        "source_name": "Oregon Sheriffs Sales",
    }


def _parse_address(raw: str) -> Tuple[str, str, str, str]:
    """
    Parse a raw address string into (street_address, city, state, zip_code).

    Expected formats:
        "428 SE Warsaw St. Redmond, OR 97756"
        "2625 SW Glacier Ave Redmond OR 97756"
        "53362 Holtzclaw Rd La Pine Oregon 97739"
        "2380 SW Phlox Pond Drive, Redmond, OR 97756"
    """
    raw = raw.strip()

    # Try to extract ZIP code (5 digits, optionally -4)
    zip_match = re.search(r'(\d{5})(?:-\d{4})?$', raw)
    zip_code = ""
    if zip_match:
        zip_code = zip_match.group(1)
        raw = raw[:zip_match.start()].strip().rstrip(',').strip()

    # Try to find state abbreviation or full name
    state = "Oregon"  # Default since this is Oregon-only scraper

    # Remove state from end: "OR" or "Oregon"
    state_patterns = [
        r',?\s+OR\s*$',
        r',?\s+Oregon\s*$',
    ]
    for pat in state_patterns:
        raw = re.sub(pat, '', raw, flags=re.IGNORECASE).strip()

    # Now raw should be "street_address city" or "street_address, city"
    # Try comma-separated first
    if ',' in raw:
        parts = raw.rsplit(',', 1)
        street = parts[0].strip()
        city = parts[1].strip()
    else:
        # No comma — need to guess where street ends and city begins
        # Common Oregon city names to match at the end of the string
        city, street = _split_street_city(raw)

    return street, city, state, zip_code


def _split_street_city(raw: str) -> Tuple[str, str]:
    """
    Split a string like "428 SE Warsaw St. Redmond" into ("Redmond", "428 SE Warsaw St.").

    Uses known Oregon city names and common patterns.
    """
    # Known cities in our target counties (expand as needed)
    known_cities = [
        "La Pine", "Redmond", "Bend", "Sisters", "Sunriver",
        "Prineville", "Madras", "Powell Butte", "Terrebonne",
        "Portland", "Gresham", "Beaverton", "Hillsboro", "Tigard",
        "Lake Oswego", "Oregon City", "West Linn", "Milwaukie",
        "Salem", "Keizer", "Silverton", "Stayton", "Woodburn",
        "Eugene", "Springfield", "Cottage Grove", "Florence",
        "Medford", "Ashland", "Grants Pass", "Klamath Falls",
        "Roseburg", "Corvallis", "Albany", "McMinnville", "Newberg",
        "Troutdale", "Fairview", "Happy Valley", "Clackamas",
    ]

    # Sort by length (longest first) so "La Pine" matches before "Pine"
    known_cities.sort(key=len, reverse=True)

    for city_name in known_cities:
        # Check if raw ends with the city name (case-insensitive)
        pattern = re.compile(r'(.+?)\s+' + re.escape(city_name) + r'\s*$', re.IGNORECASE)
        match = pattern.match(raw)
        if match:
            return city_name, match.group(1).strip()

    # Fallback: assume last word(s) are the city
    # Try last two words first (for cities like "La Pine")
    words = raw.split()
    if len(words) >= 3:
        # Try last 2 words as city
        possible_city = " ".join(words[-2:])
        if possible_city[0].isupper():
            return possible_city, " ".join(words[:-2])
        # Try last word
        return words[-1], " ".join(words[:-1])
    elif len(words) == 2:
        return words[-1], words[0]

    return "", raw


def _extract_plaintiff(case_title: str) -> str:
    """
    Extract the foreclosing entity (plaintiff) from the case title.

    Examples:
        "LAKEVIEW LOAN SERVICING, LLC vs. UNKNOWN HEIRS..." → "Lakeview Loan Servicing, LLC"
        "PENNYMAC LOAN SERVICES, LLC v JON P. GARDNER..." → "Pennymac Loan Services, LLC"
        "Umpqua Bank vs. DOE 1..." → "Umpqua Bank"
    """
    # Split on " vs. ", " vs ", " v. ", " v " (case-insensitive)
    parts = re.split(r'\s+(?:vs?\.?)\s+', case_title, maxsplit=1, flags=re.IGNORECASE)
    if parts:
        plaintiff = parts[0].strip()
        # Title-case it for readability (but preserve LLC, LLP, etc.)
        plaintiff = _smart_title_case(plaintiff)
        return plaintiff
    return ""


def _smart_title_case(text: str) -> str:
    """
    Title-case text but preserve common abbreviations like LLC, LLP, USA, etc.
    """
    preserve = {"LLC", "LLP", "LP", "INC", "CORP", "NA", "USA", "VA", "HUD", "FHA"}
    words = text.split()
    result = []
    for word in words:
        clean = word.rstrip(',').rstrip(';')
        if clean.upper() in preserve:
            result.append(clean.upper() + word[len(clean):])
        else:
            result.append(word.title())
    return " ".join(result)


def _parse_date(date_str: str) -> str:
    """
    Convert "MM/DD/YYYY" to "YYYY-MM-DD" ISO format.
    Returns empty string if parsing fails.
    """
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str.strip(), "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return date_str


def _clean_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def reset_circuit_breaker():
    """Reset the circuit breaker counter."""
    global _consecutive_failures
    _consecutive_failures = 0


def get_circuit_breaker_status() -> dict:
    """Return current circuit breaker state for diagnostics."""
    return {
        "consecutive_failures": _consecutive_failures,
        "limit": CIRCUIT_BREAKER_LIMIT,
        "tripped": _consecutive_failures >= CIRCUIT_BREAKER_LIMIT,
    }


# --- CLI test ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        county = sys.argv[1].lower()
    else:
        county = "deschutes"

    print(f"Scraping sheriff's sales for {county.title()} County, Oregon...")
    print(f"URL: {BASE_URL}/county/{county}/")
    print()

    results = scrape_county(county)

    if not results:
        print("No sheriff's sale listings found.")
    else:
        print(f"Found {len(results)} sheriff's sale listings:\n")
        for i, prop in enumerate(results, 1):
            print(f"  {i}. {prop['address']}")
            print(f"     {prop['city']}, {prop['state']} {prop['zip_code']}")
            print(f"     Sale Date: {prop['auction_date']}  Time: {prop['sale_time']}")
            print(f"     Plaintiff: {prop['foreclosing_entity']}")
            if prop.get('pdf_url'):
                print(f"     PDF: {prop['pdf_url']}")
            if prop.get('listing_url'):
                print(f"     Detail: {prop['listing_url']}")
            print()

    print(f"Circuit breaker: {get_circuit_breaker_status()}")
