#!/usr/bin/env python3
"""
Auction Property Analyzer - Main CLI Application
Command-line interface for analyzing fix-and-flip opportunities
"""

import argparse
import json
import sys
from typing import Optional

from models import Property
from analyzer import PropertyAnalyzer
from data_generator import generate_mock_data
from data_fetcher import DataFetcher
from exporter import export_all_formats, DataExporter
from auction_fetcher import fetch_real_properties
import config


class AuctionAnalyzerCLI:
    """Command-line interface for the analyzer"""
    
    def __init__(self):
        self.analyzer = PropertyAnalyzer()
        self.properties = []
    
    def run_full_analysis(self,
                         use_mock_data: bool = True,
                         use_real_data: bool = False,
                         property_count: int = None,
                         enrich: bool = False,
                         max_zips: int = 12,
                         sources: list = None) -> None:
        """
        Run complete analysis pipeline

        Args:
            use_mock_data: Use generated mock data
            use_real_data: Fetch real properties from ATTOM/BatchData/Redfin
            property_count: Number of properties to generate/fetch
            enrich: Enrich mock data with live API calls (ATTOM, BatchData, Census)
            max_zips: Number of ZIP codes to scan in real-data mode
            sources: Which data sources to use (None=all, ["redfin"], ["attom","batchdata"])
        """
        print("=" * 80)
        print("AUCTION PROPERTY ANALYZER")
        print("Fix-and-Flip Opportunity Identifier")
        print("=" * 80)
        print()

        # Step 1: Load data
        if use_real_data:
            if sources and "auctioncom" in sources and len(sources) == 1:
                print("🏠 Fetching Auction.com listings via Apify cloud...")
                print("   Source: Auction.com (ParseForge PPE actor)")
                ac_states = getattr(config, "AUCTIONCOM_STATES", ["Oregon"])
                print(f"   States: {', '.join(ac_states)}")
                print(f"   Max items: {getattr(config, 'AUCTIONCOM_MAX_ITEMS', 100)}")
            elif sources and "sheriff" in sources and len(sources) == 1:
                print("🏠 Scraping REAL sheriff's sale auction data...")
                print("   Source: Oregon Sheriffs Sales (oregonsheriffssales.org)")
                counties = getattr(config, "SHERIFF_COUNTIES", ["deschutes"])
                print(f"   Counties: {', '.join(c.title() for c in counties)}")
            elif sources and "redfin" in sources and len(sources) == 1:
                print("🏠 Scraping REAL MLS foreclosure data from Redfin...")
                print("   Source: Redfin Stingray API (MLS-listed foreclosures)")
            else:
                print("🏠 Fetching REAL auction & foreclosure data...")
                print("   Sources: ATTOM Property API + BatchData Pre-Foreclosure")
                if sources and "redfin" in sources:
                    print("            + Redfin MLS Foreclosures")
            print()
            count = property_count or config.MOCK_DATA_COUNT
            self.properties = fetch_real_properties(
                limit=count, max_zips=max_zips, progress=True,
                sources=sources
            )
            if not self.properties:
                print("\n   ⚠️  No real properties found.")
                print("   Auction inventory changes frequently — try again later.")
                print("   Or check the source directly (Auction.com, oregonsheriffssales.org)")
                return
            print(f"   🏠 Loaded {len(self.properties)} real properties\n")
        elif use_mock_data:
            print("📊 Generating mock auction data...")
            self.properties = generate_mock_data(property_count)
            print(f"   Generated {len(self.properties)} properties")
        else:
            print("❌ No data source specified")
            print("   Use --mock for test data or --real for live auction data")
            return

        # Step 1.5: Enrich with live APIs if requested (mock data only)
        if enrich and use_mock_data and not use_real_data:
            print()
            print("🌐 Enriching with live API data...")
            fetcher = DataFetcher()
            status = fetcher.status()
            for api, state in status.items():
                indicator = "✅" if "Ready" in state and "no key" not in state.lower() else "⚠️"
                print(f"   {indicator} {api}: {state}")
            print()
            self.properties = fetcher.enrich_properties(self.properties)

        self.analyzer.load_properties(self.properties)
        print()

        # Step 2: Filter
        print("🔍 Filtering properties...")
        filtered = self.analyzer.filter_properties()
        print(f"   {len(filtered)} properties meet criteria")
        print(f"   Filters: {config.TARGET_STATES}, "
              f"${config.MIN_AUCTION_PRICE:,}-${config.MAX_AUCTION_PRICE:,}, "
              f"max repairs ${config.MAX_REPAIR_COST:,}")
        print()

        # Step 3: Analyze
        print("📈 Analyzing deals...")
        analysis = self.analyzer.analyze()
        print(f"   Found {analysis.recommended_deals} recommended deals")
        print(f"   Average profit margin: {analysis.avg_profit_margin:.1f}%")
        print()

        # Step 4: Export
        print("💾 Exporting results...")
        files = export_all_formats(analysis, filtered)
        for format_type, filename in files.items():
            print(f"   ✅ {format_type.upper()}: {filename}")
        print()

        # Step 5: Display results
        self.analyzer.print_alerts()
        self.analyzer.print_top_deals(5)

        print("=" * 80)
        print("Analysis complete! View index.html for interactive exploration.")
        print("=" * 80)
    
    def analyze_custom(self, 
                      states: list,
                      min_price: int,
                      max_price: int,
                      max_repairs: int,
                      min_margin: float) -> None:
        """Run analysis with custom filters"""
        
        if not self.properties:
            print("⚠️  No properties loaded. Run with --mock first.")
            return
        
        print("🔍 Applying custom filters...")
        
        custom_filters = {
            'states': states,
            'min_price': min_price,
            'max_price': max_price,
            'max_repairs': max_repairs
        }
        
        filtered = self.analyzer.filter_properties(custom_filters)
        print(f"   Found {len(filtered)} properties")
        
        if not filtered:
            print("   No properties match your criteria")
            return
        
        analysis = self.analyzer.analyze()
        
        # Show only deals meeting minimum margin
        high_margin_deals = [p for p in self.analyzer.filtered_properties 
                            if p.profit_margin >= min_margin]
        
        print(f"\n📊 Deals with {min_margin}%+ margin: {len(high_margin_deals)}")
        
        for prop in high_margin_deals[:10]:
            print(f"   {prop}")
    
    def compare_states(self) -> None:
        """Compare deals across different states"""
        
        if not self.properties:
            print("⚠️  No properties loaded. Run with --mock first.")
            return
        
        print("📊 STATE COMPARISON")
        print("=" * 80)
        
        for state in config.TARGET_STATES:
            state_deals = self.analyzer.get_deals_by_state(state)
            
            if not state_deals:
                continue
            
            recommended = [p for p in state_deals if p.recommended]
            avg_margin = sum(p.profit_margin for p in state_deals) / len(state_deals)
            avg_score = sum(p.deal_score for p in state_deals) / len(state_deals)
            
            print(f"\n{state}:")
            print(f"  Total Properties: {len(state_deals)}")
            print(f"  Recommended: {len(recommended)}")
            print(f"  Avg Margin: {avg_margin:.1f}%")
            print(f"  Avg Score: {avg_score:.1f}/100")
            
            # Show top deal
            top = sorted(state_deals, key=lambda x: x.deal_score, reverse=True)[0]
            print(f"  Top Deal: {top.address}, {top.city}")
            print(f"    Margin: {top.profit_margin:.1f}% | Score: {top.deal_score:.1f}")


def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(
        description='Auction Property Analyzer - Find fix-and-flip opportunities',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full analysis with mock data
  python main.py --mock

  # Scrape REAL MLS foreclosures from Redfin (no API key needed!)
  python main.py --scrape

  # Scrape with more ZIP codes for wider coverage
  python main.py --scrape --max-zips 20 --count 100

  # Scrape Oregon sheriff's sales (real courthouse auctions)
  python main.py --sheriff

  # Fetch Auction.com listings via Apify cloud (free tier: 100 properties)
  python main.py --auction-com

  # Fetch REAL auction/foreclosure data from ATTOM/BatchData APIs
  python main.py --real

  # Real data with more ZIP codes scanned
  python main.py --real --max-zips 20 --count 100

  # Enrich mock data with live API data (ATTOM, BatchData, Census)
  python main.py --mock --enrich

  # Check which APIs are configured
  python main.py --api-status

  # Generate specific number of properties
  python main.py --mock --count 100

  # Custom filters
  python main.py --mock --min-margin 35 --max-price 500000

  # Compare states
  python main.py --mock --compare-states
        """
    )

    data_source = parser.add_mutually_exclusive_group()
    data_source.add_argument('--mock', action='store_true',
                             help='Use mock data for testing')
    data_source.add_argument('--real', action='store_true',
                             help='Fetch REAL auction/foreclosure data from ATTOM & BatchData APIs')
    data_source.add_argument('--scrape', action='store_true',
                             help='Scrape Redfin for real MLS-listed foreclosures (no API key needed)')
    data_source.add_argument('--sheriff', action='store_true',
                             help='Scrape Oregon sheriff\'s sales (real courthouse auctions, no API key needed)')
    data_source.add_argument('--auction-com', action='store_true', dest='auction_com',
                             help='Fetch Auction.com listings via Apify (requires apify_token in .api_keys.json)')

    parser.add_argument('--count', type=int, default=None,
                       help='Number of properties to generate/fetch (default: from config)')

    parser.add_argument('--max-zips', type=int, default=12,
                       help='Number of ZIP codes to scan in --real mode (default: 12)')

    parser.add_argument('--min-margin', type=float, default=config.MIN_PROFIT_MARGIN,
                       help=f'Minimum profit margin %% (default: {config.MIN_PROFIT_MARGIN})')

    parser.add_argument('--max-price', type=int, default=config.MAX_AUCTION_PRICE,
                       help=f'Maximum auction price (default: {config.MAX_AUCTION_PRICE})')

    parser.add_argument('--max-repairs', type=int, default=config.MAX_REPAIR_COST,
                       help=f'Maximum repair cost (default: {config.MAX_REPAIR_COST})')

    parser.add_argument('--states', nargs='+', default=config.TARGET_STATES,
                       help=f'Target states (default: {" ".join(config.TARGET_STATES)})')

    parser.add_argument('--enrich', action='store_true',
                       help='Enrich mock data with live API calls (ATTOM, BatchData, Census)')

    parser.add_argument('--api-status', action='store_true',
                       help='Show which APIs are configured and exit')

    parser.add_argument('--compare-states', action='store_true',
                       help='Compare deals across states')

    parser.add_argument('--export-only', action='store_true',
                       help='Only export existing data (skip analysis)')

    parser.add_argument('--top', type=int, default=5,
                       help='Number of top deals to show (default: 5)')
    
    args = parser.parse_args()
    
    # Initialize CLI
    cli = AuctionAnalyzerCLI()
    
    # Handle API status check
    if args.api_status:
        fetcher = DataFetcher()
        print("🔌 API Status:")
        print("-" * 60)
        for api, state in fetcher.status().items():
            indicator = "✅" if "Ready" in state and "no key" not in state.lower() else "⚠️"
            print(f"  {indicator} {api}: {state}")
        print()
        print("Set API keys in config.py under API_KEYS to enable live data.")
        return

    # Handle export-only mode
    if args.export_only:
        import os
        json_path = config.OUTPUT_JSON_FILE
        if not os.path.exists(json_path):
            print(f"❌ No existing data found at {json_path}")
            print("   Run a full analysis first with --mock or --real")
            return

        print("📂 Loading existing analysis data...")
        with open(json_path, 'r') as f:
            data = json.load(f)

        # Reconstruct Property objects from the saved JSON
        all_props = data.get("all_properties", [])
        properties = []
        for p in all_props:
            prop = Property(
                id=p["id"], address=p["address"], city=p["city"],
                state=p["state"], zip_code=p["zip_code"], region=p["region"],
                auction_price=p["auction_price"], estimated_arv=p["estimated_arv"],
                estimated_repairs=p["estimated_repairs"], bedrooms=p["bedrooms"],
                bathrooms=p["bathrooms"], sqft=p["sqft"], lot_size=p["lot_size"],
                year_built=p["year_built"], property_type=p["property_type"],
                auction_date=p["auction_date"], auction_platform=p["auction_platform"],
                description=p.get("description", ""), neighborhood_score=p["neighborhood_score"],
            )
            prop.calculate_metrics()
            properties.append(prop)

        print(f"   Loaded {len(properties)} properties")

        # Run through analyzer to produce AnalysisResult
        cli.analyzer.load_properties(properties)
        filtered = cli.analyzer.filter_properties()
        analysis = cli.analyzer.analyze()

        print("💾 Re-exporting results...")
        files = export_all_formats(analysis, filtered)
        for format_type, filename in files.items():
            print(f"   ✅ {format_type.upper()}: {filename}")
        print("\nExport complete!")
        return

    # Run analysis
    if args.real:
        cli.run_full_analysis(
            use_mock_data=False, use_real_data=True,
            property_count=args.count, max_zips=args.max_zips
        )
    elif args.scrape:
        cli.run_full_analysis(
            use_mock_data=False, use_real_data=True,
            property_count=args.count, max_zips=args.max_zips,
            sources=["redfin"]
        )
    elif args.sheriff:
        cli.run_full_analysis(
            use_mock_data=False, use_real_data=True,
            property_count=args.count, max_zips=args.max_zips,
            sources=["sheriff"]
        )
    elif args.auction_com:
        cli.run_full_analysis(
            use_mock_data=False, use_real_data=True,
            property_count=args.count, max_zips=args.max_zips,
            sources=["auctioncom"]
        )
    elif args.mock:
        cli.run_full_analysis(use_mock_data=True, property_count=args.count,
                              enrich=args.enrich)
    else:
        parser.print_help()
        print("\n⚠️  Please specify --mock, --real, --scrape, --sheriff, or --auction-com")
        return

    # Additional operations (shared across --mock and --real)
    if args.compare_states:
        print("\n")
        cli.compare_states()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Analysis interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
