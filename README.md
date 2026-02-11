# 🏠 Auction Property Analyzer

A comprehensive tool for identifying fix-and-flip opportunities in Oregon and Texas housing auctions.

## Features

✅ **Targeted Search**: Single-family homes $100k-$1.2M in Oregon and Texas
✅ **Light Rehab Focus**: Filters properties requiring ≤$80k in repairs
✅ **Profit Analysis**: Identifies deals with 30%+ profit margins
✅ **Smart Scoring**: 100-point deal scoring system
✅ **Interactive Dashboard**: Beautiful web interface with filtering
✅ **Real-time Alerts**: Highlights hot deals (40%+ margins)
✅ **Mock Data**: Working prototype with 75 realistic properties

## Quick Start

### 1. Run the Analyzer

```bash
python3 property_analyzer.py
```

This will:
- Generate 75 realistic auction properties
- Filter based on your criteria
- Calculate profit metrics for each property
- Export analysis to `property_analysis.json`
- Display top 5 deals and alerts in console

### 2. View the Dashboard

```bash
python3 -m http.server 8000
```

Then open your browser to: `http://localhost:8000/dashboard.html`

## How It Works

### Deal Scoring Algorithm (0-100 points)

**Profit Margin (40 points)**
- 40%+ margin: Full 40 points
- 30-40% margin: 30-40 points
- <30% margin: Scaled points

**Repair Amount (20 points)**
- ≤15% of purchase: 20 points
- 15-30% of purchase: 15 points
- >30% of purchase: Reduced points

**Neighborhood Score (20 points)**
- Based on area rating (1-10 scale)
- Score × 2 = points

**Property Characteristics (20 points)**
- Ideal sqft (1500-3000): 5 points
- 3-4 bedrooms: 5 points
- 2+ bathrooms: 5 points
- Built after 1980: 5 points

### Profit Calculation

```
Total Investment = Auction Price + Repairs + Closing (3%) + Holding (6mo) + Selling (8%)
Profit = ARV - Total Investment
Profit Margin = (Profit / ARV) × 100%
```

### Recommendation Criteria

A property is "Recommended" when:
- ✅ Profit margin ≥ 30%
- ✅ Repairs ≤ $80,000
- ✅ Deal score ≥ 60/100

## Dashboard Features

### Statistics Overview
- Total properties analyzed
- Number of recommended deals
- Average profit margin
- Hot deals count (40%+ margins)

### High-Value Alerts
- 🔥 **HOT DEAL**: 40%+ profit margin
- ⭐ **EXCELLENT**: 35-40% profit margin
- ✅ **GOOD**: 30-35% profit margin

### Filters
- **State**: Oregon, Texas, or both
- **Min Profit Margin**: Set minimum acceptable profit
- **Max Auction Price**: Budget constraints
- **Min Deal Score**: Quality threshold
- **Sort Options**: By score, margin, profit, or date

### Property Cards
Each property displays:
- Address and location
- Auction price and ARV
- Estimated repairs
- Profit potential and margin
- Deal score with visual progress bar
- Property details (bed/bath/sqft/year)
- Neighborhood score
- Auction date and platform

## Sample Output

```
🚨 HIGH-VALUE DEAL ALERTS:
--------------------------------------------------------------------------------
🔥 HOT DEAL
   Property: 4523 Oak St, Austin, Texas
   Profit Margin: 42.3% | Potential: $185,420
   Deal Score: 87.5/100 | Auction: 2026-03-15

⭐ EXCELLENT
   Property: 7821 Pine Ave, Portland, Oregon
   Profit Margin: 36.8% | Potential: $124,680
   Deal Score: 82.1/100 | Auction: 2026-02-28
```

## Customization

### Adjust Filters in Code

Edit `property_analyzer.py`:

```python
# Change price range
if prop.auction_price < 150000 or prop.auction_price > 900000:
    continue

# Adjust repair limit
if prop.estimated_repairs > 60000:
    continue

# Modify profit margin threshold
if prop.profit_margin < 35:
    continue
```

### Add More States

```python
# In generate_mock_data()
california_cities = [
    ("San Diego", "92101"), ("San Francisco", "94102")
]
state = random.choice(["Oregon", "Texas", "California"])
```

## Next Steps: Real Data Integration

To connect to actual auction sources:

### 1. Auction.com API
```python
import requests

def scrape_auction_com(state, min_price, max_price):
    # API endpoint (requires authentication)
    url = "https://api.auction.com/properties"
    params = {
        "state": state,
        "minPrice": min_price,
        "maxPrice": max_price,
        "propertyType": "single_family"
    }
    response = requests.get(url, params=params)
    return response.json()
```

### 2. Hubzu Integration
```python
def scrape_hubzu(state):
    # Web scraping with BeautifulSoup
    from bs4 import BeautifulSoup
    url = f"https://www.hubzu.com/properties?state={state}"
    # Parse property listings
```

### 3. RealtyBid
```python
def scrape_realtybid(state):
    # Selenium for dynamic content
    from selenium import webdriver
    driver = webdriver.Chrome()
    # Navigate and extract data
```

## Files Included

- `property_analyzer.py` - Main analysis engine
- `dashboard.html` - Interactive web dashboard
- `property_analysis.json` - Generated data file (after running analyzer)
- `README.md` - This documentation

## Requirements

- Python 3.7+
- No external dependencies for mock data
- For real scraping: requests, beautifulsoup4, selenium

## Tips for Real-World Use

1. **Verify ARV Estimates**: Use Zillow, Redfin, or local comps
2. **Get Professional Repair Quotes**: Don't rely solely on estimates
3. **Check Property History**: Title issues, liens, HOA
4. **Visit Properties**: Photos can be misleading
5. **Factor in Timeline**: Holding costs increase with delays
6. **Build Contractor Network**: Reliable contractors = better margins
7. **Know Your Market**: Local expertise is invaluable

## Legal Disclaimer

This tool is for educational and analytical purposes only. Always:
- Consult with real estate professionals
- Conduct proper due diligence
- Get professional inspections
- Verify all financial calculations
- Understand local laws and regulations

## Support

For issues or questions:
1. Check the code comments
2. Review the calculation formulas
3. Test with different filter settings
4. Verify JSON data structure

## License

Free to use and modify for personal/commercial projects.
