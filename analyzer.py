"""
Core analyzer module for processing auction properties
"""

import statistics
from typing import List, Dict, Optional
from models import Property, AnalysisResult
import config


class PropertyAnalyzer:
    """Analyzes auction properties and identifies opportunities"""
    
    def __init__(self):
        self.properties: List[Property] = []
        self.filtered_properties: List[Property] = []
        self.analysis_result: Optional[AnalysisResult] = None
    
    def load_properties(self, properties: List[Property]) -> None:
        """Load properties for analysis"""
        self.properties = properties
        print(f"Loaded {len(properties)} properties")
    
    def filter_properties(self, 
                         custom_filters: Optional[Dict] = None) -> List[Property]:
        """
        Filter properties based on criteria
        
        Args:
            custom_filters: Optional dict with custom filter values
                {
                    'states': ['Oregon', 'Texas'],
                    'min_price': 100000,
                    'max_price': 1200000,
                    'max_repairs': 999999999,  # no repair filter
                    'property_types': ['Single Family']
                }
        """
        # Use config defaults if no custom filters provided
        filters = {
            'states': config.TARGET_STATES,
            'regions': None,  # None means all regions
            'min_price': config.MIN_AUCTION_PRICE,
            'max_price': config.MAX_AUCTION_PRICE,
            'max_repairs': config.MAX_REPAIR_COST,  # effectively disabled
            'property_types': config.ALLOWED_PROPERTY_TYPES
        }
        
        if custom_filters:
            filters.update(custom_filters)
        
        filtered = []
        
        for prop in self.properties:
            # State filter
            if prop.state not in filters['states']:
                continue

            # Region filter
            if filters.get('regions') and prop.region not in filters['regions']:
                continue

            # Price range filter
            if (prop.auction_price < filters['min_price'] or 
                prop.auction_price > filters['max_price']):
                continue
            
            # Repair cost filter
            if prop.estimated_repairs > filters['max_repairs']:
                continue
            
            # Property type filter
            if prop.property_type not in filters['property_types']:
                continue
            
            filtered.append(prop)
        
        self.filtered_properties = filtered
        return filtered
    
    def analyze(self) -> AnalysisResult:
        """Analyze filtered properties and generate insights"""
        
        if not self.filtered_properties:
            raise ValueError("No properties to analyze. Run filter_properties() first.")
        
        # Sort by deal score
        sorted_props = sorted(self.filtered_properties, 
                            key=lambda x: x.deal_score, 
                            reverse=True)
        
        # Get recommended deals
        recommended = [p for p in sorted_props if p.recommended]
        
        # Generate alerts
        alerts = self._generate_alerts(sorted_props)
        
        # Calculate statistics
        stats = self._calculate_statistics(sorted_props)
        
        # Create result
        self.analysis_result = AnalysisResult(
            total_properties=len(sorted_props),
            recommended_deals=len(recommended),
            avg_profit_margin=statistics.mean([p.profit_margin for p in sorted_props]),
            avg_deal_score=statistics.mean([p.deal_score for p in sorted_props]),
            top_deals=[p.to_dict() for p in sorted_props[:20]],
            all_properties=[p.to_dict() for p in sorted_props],
            alerts=alerts,
            statistics=stats
        )
        
        return self.analysis_result
    
    def _generate_alerts(self, properties: List[Property]) -> List[Dict]:
        """Generate alerts for high-value deals"""
        alerts = []
        
        # Get top recommended deals
        recommended = [p for p in properties if p.recommended]
        
        for prop in recommended[:10]:  # Top 10 deals
            alert_level = prop.get_alert_level()
            
            if alert_level:
                alerts.append({
                    "level": alert_level,
                    "property_id": prop.id,
                    "address": f"{prop.address}, {prop.city}, {prop.state}",
                    "profit_margin": f"{prop.profit_margin:.1f}%",
                    "profit_potential": f"${prop.profit_potential:,.0f}",
                    "max_bid_price": prop.max_bid_price,
                    "auction_date": prop.auction_date,
                    "deal_score": prop.deal_score
                })
        
        return alerts
    
    def _calculate_statistics(self, properties: List[Property]) -> Dict:
        """Calculate various statistics"""
        
        if not properties:
            return {}
        
        # Dynamic per-state counts
        state_counts = {}
        for state in config.TARGET_STATES:
            key = f"{state.lower().replace(' ', '_')}_count"
            state_counts[key] = len([p for p in properties if p.state == state])

        return {
            **state_counts,
            "avg_auction_price": statistics.mean([p.auction_price for p in properties]),
            "median_auction_price": statistics.median([p.auction_price for p in properties]),
            "avg_arv": statistics.mean([p.estimated_arv for p in properties]),
            "avg_sqft": statistics.mean([p.sqft for p in properties]),
            "deals_over_40_percent": len([p for p in properties if p.profit_margin >= 40]),
            "deals_30_to_40_percent": len([p for p in properties if 30 <= p.profit_margin < 40]),
            "deals_20_to_30_percent": len([p for p in properties if 20 <= p.profit_margin < 30]),
            "avg_neighborhood_score": statistics.mean([p.neighborhood_score for p in properties]),
            "properties_by_city": self._count_by_city(properties),
            "properties_by_region": self._count_by_region(properties),
            "properties_by_platform": self._count_by_platform(properties)
        }
    
    def _count_by_city(self, properties: List[Property]) -> Dict:
        """Count properties by city"""
        counts = {}
        for prop in properties:
            city_key = f"{prop.city}, {prop.state}"
            counts[city_key] = counts.get(city_key, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
    
    def _count_by_region(self, properties: List[Property]) -> Dict:
        """Count properties by region"""
        counts = {}
        for prop in properties:
            if prop.region:
                region_key = f"{prop.region} ({prop.state})"
                counts[region_key] = counts.get(region_key, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def _count_by_platform(self, properties: List[Property]) -> Dict:
        """Count properties by platform"""
        counts = {}
        for prop in properties:
            counts[prop.auction_platform] = counts.get(prop.auction_platform, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
    
    def get_top_deals(self, count: int = 5) -> List[Property]:
        """Get top N deals by score"""
        if not self.filtered_properties:
            return []
        
        sorted_props = sorted(self.filtered_properties, 
                            key=lambda x: x.deal_score, 
                            reverse=True)
        return sorted_props[:count]
    
    def get_deals_by_margin(self, min_margin: float) -> List[Property]:
        """Get deals above a certain profit margin"""
        return [p for p in self.filtered_properties 
                if p.profit_margin >= min_margin]
    
    def get_deals_by_state(self, state: str) -> List[Property]:
        """Get deals in a specific state"""
        return [p for p in self.filtered_properties
                if p.state == state]

    def get_deals_by_region(self, region: str) -> List[Property]:
        """Get deals in a specific region"""
        return [p for p in self.filtered_properties
                if p.region == region]
    
    def print_summary(self) -> None:
        """Print analysis summary"""
        if not self.analysis_result:
            print("No analysis available. Run analyze() first.")
            return
        
        result = self.analysis_result
        
        print("=" * 80)
        print("ANALYSIS SUMMARY")
        print("=" * 80)
        print(f"Total Properties: {result.total_properties}")
        print(f"Recommended Deals: {result.recommended_deals}")
        print(f"Average Profit Margin: {result.avg_profit_margin:.1f}%")
        print(f"Average Deal Score: {result.avg_deal_score:.1f}/100")
        print()
        
        stats = result.statistics
        print("MARKET BREAKDOWN:")
        for state in config.TARGET_STATES:
            key = f"{state.lower().replace(' ', '_')}_count"
            print(f"  {state}: {stats.get(key, 0)} properties")
        print()
        print(f"  Hot Deals (40%+): {stats.get('deals_over_40_percent', 0)}")
        print(f"  Excellent (30-40%): {stats.get('deals_30_to_40_percent', 0)}")
        print(f"  Good (20-30%): {stats.get('deals_20_to_30_percent', 0)}")
        print()
    
    def print_alerts(self) -> None:
        """Print high-value alerts"""
        if not self.analysis_result or not self.analysis_result.alerts:
            print("No alerts to display.")
            return
        
        print("🚨 HIGH-VALUE DEAL ALERTS:")
        print("-" * 80)
        
        for alert in self.analysis_result.alerts[:5]:
            print(f"{alert['level']}")
            print(f"   Property: {alert['address']}")
            print(f"   Profit Margin: {alert['profit_margin']} | "
                  f"Potential: {alert['profit_potential']}")
            print(f"   Deal Score: {alert['deal_score']:.1f}/100 | "
                  f"Auction: {alert['auction_date']}")
            print()
    
    def print_top_deals(self, count: int = 5) -> None:
        """Print top deals"""
        top_deals = self.get_top_deals(count)
        
        if not top_deals:
            print("No deals to display.")
            return
        
        print(f"🏆 TOP {count} DEALS:")
        print("-" * 80)
        
        for i, prop in enumerate(top_deals, 1):
            print(f"{i}. {prop.address}, {prop.city}, {prop.state}")
            print(f"   Auction Price: ${prop.auction_price:,.0f} | "
                  f"Est. Value: ${prop.estimated_arv:,.0f}")
            print(f"   Profit: ${prop.profit_potential:,.0f}")
            print(f"   Profit Margin: {prop.profit_margin:.1f}% | "
                  f"Score: {prop.deal_score:.1f}/100")
            print()
