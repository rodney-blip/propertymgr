"""
Export module for saving analysis results
"""

import json
import csv
from typing import List
from pathlib import Path
from dataclasses import fields as dc_fields
from models import Property, AnalysisResult
import config


class DataExporter:
    """Export analysis results to various formats"""
    
    @staticmethod
    def export_to_json(analysis: AnalysisResult, 
                       filename: str = None) -> str:
        """
        Export analysis to JSON file
        
        Args:
            analysis: AnalysisResult object
            filename: Output filename (default from config)
        
        Returns:
            Path to created file
        """
        if filename is None:
            filename = config.OUTPUT_JSON_FILE
        
        filepath = Path(filename)
        
        with open(filepath, 'w') as f:
            json.dump(analysis.to_dict(), f, indent=2)
        
        return str(filepath)
    
    @staticmethod
    def export_to_csv(properties: List[Property], 
                      filename: str = None) -> str:
        """
        Export properties to CSV file
        
        Args:
            properties: List of Property objects
            filename: Output filename (default from config)
        
        Returns:
            Path to created file
        """
        if filename is None:
            filename = config.OUTPUT_CSV_FILE
        
        filepath = Path(filename)
        
        if not properties:
            raise ValueError("No properties to export")
        
        # Define CSV columns dynamically from dataclass fields
        columns = [f.name for f in dc_fields(Property)]
        
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            
            for prop in properties:
                row = {col: getattr(prop, col) for col in columns}
                writer.writerow(row)
        
        return str(filepath)
    
    @staticmethod
    def export_to_text(properties: List[Property],
                        count: int = 20,
                        filename: str = "top_deals.txt") -> str:
        """
        Export top deals as formatted text report
        
        Args:
            properties: List of Property objects (should be sorted)
            count: Number of top deals to export
            filename: Output filename
        
        Returns:
            Path to created file
        """
        filepath = Path(filename)
        
        with open(filepath, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write(f"TOP {count} AUCTION PROPERTY DEALS\n")
            f.write("=" * 80 + "\n\n")
            
            for i, prop in enumerate(properties[:count], 1):
                region_str = f" ({prop.region})" if prop.region else ""
                f.write(f"#{i} - {prop.address}, {prop.city}{region_str}, {prop.state}\n")
                f.write(f"{'─' * 80}\n")
                f.write(f"Property ID: {prop.id}\n")
                f.write(f"Auction Date: {prop.auction_date}\n")
                f.write(f"Platform: {prop.auction_platform}\n")
                if prop.mortgage_balance or prop.mortgage_lender:
                    f.write(f"\nMORTGAGE / DEBT:\n")
                    if prop.mortgage_balance:
                        f.write(f"  Mortgage Balance:    ${prop.mortgage_balance:>12,.0f}\n")
                        if prop.estimated_arv:
                            equity = prop.estimated_arv - prop.mortgage_balance
                            f.write(f"  Est. Equity:         ${equity:>12,.0f}\n")
                    if prop.mortgage_lender:
                        f.write(f"  Lender:              {prop.mortgage_lender}\n")
                    if prop.mortgage_date:
                        f.write(f"  Originated:          {prop.mortgage_date}\n")
                    if prop.mortgage_interest_rate:
                        f.write(f"  Interest Rate:       {prop.mortgage_interest_rate:.2f}%\n")
                    if prop.mortgage_term:
                        f.write(f"  Term:                {prop.mortgage_term}\n")
                    if prop.second_mortgage_balance:
                        f.write(f"  2nd Lien:            ${prop.second_mortgage_balance:>12,.0f}\n")
                        if prop.second_mortgage_lender:
                            f.write(f"  2nd Lien Holder:     {prop.second_mortgage_lender}\n")
                if prop.foreclosing_entity:
                    f.write(f"\nFORECLOSURE CONTEXT:\n")
                    f.write(f"  Foreclosing Entity:  {prop.foreclosing_entity}\n")
                    f.write(f"  Total Debt:          ${prop.total_debt:>12,.0f}\n" if prop.total_debt else "")
                    f.write(f"  Loan Type:           {prop.loan_type}\n" if prop.loan_type else "")
                    f.write(f"  Default Date:        {prop.default_date}\n" if prop.default_date else "")
                    f.write(f"  Stage:               {prop.foreclosure_stage}\n" if prop.foreclosure_stage else "")
                f.write("\n")
                
                f.write(f"PRICING:\n")
                f.write(f"  Auction Price:     ${prop.auction_price:>12,.0f}\n")
                f.write(f"  Estimated Value:   ${prop.estimated_arv:>12,.0f}\n")
                f.write(f"  Total Investment:  ${prop.total_investment:>12,.0f}\n")
                f.write(f"  Profit Potential:  ${prop.profit_potential:>12,.0f}\n\n")
                
                f.write(f"METRICS:\n")
                f.write(f"  Profit Margin:     {prop.profit_margin:>11.1f}%\n")
                f.write(f"  Deal Score:        {prop.deal_score:>11.1f}/100\n")
                f.write(f"  Recommended:       {'Yes' if prop.recommended else 'No':>14}\n\n")
                
                f.write(f"PROPERTY DETAILS:\n")
                f.write(f"  {prop.bedrooms} bed / {prop.bathrooms} bath | ")
                f.write(f"{prop.sqft:,} sqft | Built {prop.year_built}\n")
                f.write(f"  Neighborhood Score: {prop.neighborhood_score}/10\n\n")
                
                cost_breakdown = prop.get_cost_breakdown()
                f.write(f"COST BREAKDOWN:\n")
                f.write(f"  Purchase:      ${cost_breakdown['auction_price']:>12,.0f}\n")
                f.write(f"  Closing:       ${cost_breakdown['closing_costs']:>12,.0f}\n")
                f.write(f"  Holding:       ${cost_breakdown['holding_costs']:>12,.0f}\n")
                f.write(f"  Selling:       ${cost_breakdown['selling_costs']:>12,.0f}\n")
                f.write(f"  {'─' * 40}\n")
                f.write(f"  Total:         ${cost_breakdown['total_investment']:>12,.0f}\n\n")
                
                f.write(f"\n")
        
        return str(filepath)
    
    @staticmethod
    def export_to_html(alerts: List[dict],
                           filename: str = "deal_alerts.html") -> str:
        """
        Export alerts as HTML email template
        
        Args:
            alerts: List of alert dictionaries
            filename: Output filename
        
        Returns:
            Path to created file
        """
        filepath = Path(filename)
        
        html = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; background: white; 
                    padding: 30px; border-radius: 10px; }
        h1 { color: #667eea; }
        .alert { background: linear-gradient(135deg, #667eea, #764ba2);
                color: white; padding: 20px; border-radius: 8px; margin: 15px 0; }
        .alert-hot { background: linear-gradient(135deg, #ff6b6b, #ee5a6f); }
        .alert-excellent { background: linear-gradient(135deg, #f093fb, #f5576c); }
        .metric { margin: 10px 0; }
        .button { background: white; color: #667eea; padding: 12px 24px; 
                 text-decoration: none; border-radius: 6px; display: inline-block;
                 margin-top: 10px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚨 High-Value Auction Property Alerts</h1>
        <p>You have new fix-and-flip opportunities meeting your criteria!</p>
"""
        
        for alert in alerts[:5]:
            alert_class = "alert"
            if "HOT" in alert['level']:
                alert_class += " alert-hot"
            elif "EXCELLENT" in alert['level']:
                alert_class += " alert-excellent"
            
            html += f"""
        <div class="{alert_class}">
            <h2>{alert['level']}</h2>
            <div class="metric"><strong>Property:</strong> {alert['address']}</div>
            <div class="metric"><strong>Profit Margin:</strong> {alert['profit_margin']}</div>
            <div class="metric"><strong>Profit Potential:</strong> {alert['profit_potential']}</div>
            <div class="metric"><strong>Deal Score:</strong> {alert['deal_score']:.1f}/100</div>
            <div class="metric"><strong>Auction Date:</strong> {alert['auction_date']}</div>
            <a href="#" class="button">View Details</a>
        </div>
"""
        
        html += """
        <p style="margin-top: 30px; color: #666; font-size: 14px;">
            This is an automated alert from your Auction Property Analyzer.
        </p>
    </div>
</body>
</html>
"""
        
        with open(filepath, 'w') as f:
            f.write(html)
        
        return str(filepath)


def export_all_formats(analysis: AnalysisResult, 
                      properties: List[Property]) -> dict:
    """
    Export analysis in all available formats
    
    Returns:
        Dictionary of filenames created
    """
    exporter = DataExporter()
    
    files = {}
    
    # JSON export
    files['json'] = exporter.export_to_json(analysis)
    
    # CSV export (if enabled)
    if config.ENABLE_CSV_EXPORT:
        files['csv'] = exporter.export_to_csv(properties)
    
    # Top deals report
    sorted_props = sorted(properties, key=lambda x: x.deal_score, reverse=True)
    files['report'] = exporter.export_to_text(sorted_props)
    
    # Email alerts
    if analysis.alerts:
        files['email'] = exporter.export_to_html(analysis.alerts)
    
    return files
