"""
Mock data generator for testing the analyzer
"""

import random
from datetime import datetime, timedelta
from typing import List
from models import Property
import config


class MockDataGenerator:
    """Generates realistic mock auction property data"""

    def __init__(self):
        self.street_names = [
            "Oak", "Maple", "Cedar", "Pine", "Elm", "Willow", "River", "Lake",
            "Park", "Main", "Highland", "Valley", "Hill", "Garden", "Forest",
            "Spring", "Sunset", "Mountain", "Ridge", "Creek"
        ]

        self.street_types = ["St", "Ave", "Dr", "Ln", "Ct", "Way", "Rd", "Blvd", "Pl"]

        self.foreclosing_entities = [
            "Bank of America", "Wells Fargo", "Chase Bank", "US Bank",
            "Citibank", "PNC Bank", "Truist Bank", "Capital One",
            "Flagstar Bank", "Mr. Cooper", "Nationstar Mortgage",
            "Ocwen Financial", "PHH Mortgage", "Shellpoint Mortgage",
            "Freedom Mortgage", "Caliber Home Loans", "NewRez LLC",
        ]

        self.loan_types = [
            "Conventional", "FHA", "VA", "USDA", "Jumbo",
            "ARM", "Fixed-Rate", "Interest-Only",
        ]

        self.foreclosure_stages = [
            "Pre-Foreclosure", "Notice of Default", "Lis Pendens",
            "Auction Scheduled", "Bank Owned (REO)", "Short Sale",
        ]
    
    def generate_properties(self, count: int = None) -> List[Property]:
        """Generate mock properties"""
        if count is None:
            count = config.MOCK_DATA_COUNT
        
        properties = []
        
        for i in range(count):
            prop = self._generate_single_property(i)
            prop.calculate_metrics()
            properties.append(prop)
        
        return properties
    
    def _generate_single_property(self, index: int) -> Property:
        """Generate a single property"""
        
        # Select state, region, then city within region
        state = random.choice(config.TARGET_STATES)
        regions = config.REGION_DEFINITIONS[state]
        region = random.choice(list(regions.keys()))
        city, zip_code = random.choice(regions[region])
        
        # Property details
        bedrooms = random.randint(2, 5)
        bathrooms = random.choice([1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
        sqft = random.randint(1000, 3500)
        year_built = random.randint(1960, 2020)
        lot_size = round(random.uniform(0.1, 0.5), 2)
        
        # Generate pricing based on deal quality
        base_price_per_sqft = config.PRICE_PER_SQFT.get(state, 180)
        price_variation = random.uniform(0.9, 1.2)
        estimated_arv = sqft * base_price_per_sqft * price_variation
        
        # Create distribution of deal qualities
        deal_type = random.random()
        if deal_type < 0.25:  # 25% hot deals
            discount_factor = random.uniform(0.40, 0.52)
            repair_factor = random.choice([0.05, 0.08, 0.10])
        elif deal_type < 0.50:  # 25% excellent deals
            discount_factor = random.uniform(0.50, 0.60)
            repair_factor = random.choice([0.08, 0.10, 0.12, 0.15])
        elif deal_type < 0.75:  # 25% good deals
            discount_factor = random.uniform(0.60, 0.70)
            repair_factor = random.choice([0.10, 0.12, 0.15, 0.18])
        else:  # 25% mediocre deals
            discount_factor = random.uniform(0.70, 0.85)
            repair_factor = random.choice([0.15, 0.20, 0.25, 0.30])
        
        auction_price = estimated_arv * discount_factor
        estimated_repairs = auction_price * repair_factor
        
        # Ensure within bounds
        auction_price = max(config.MIN_AUCTION_PRICE, 
                          min(config.MAX_AUCTION_PRICE, auction_price))
        
        # Generate dates
        days_ahead = random.randint(1, 45)
        auction_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        # Address
        address = (f"{random.randint(100, 9999)} "
                  f"{random.choice(self.street_names)} "
                  f"{random.choice(self.street_types)}")
        
        # Neighborhood score (influenced by region and year built)
        base_neighborhood = 5
        if region in ("Portland Metro", "Greater Austin", "Dallas / Fort Worth"):
            base_neighborhood += 1
        elif region in ("Central Oregon", "El Paso Area"):
            base_neighborhood -= 1
        if year_built > 2000:
            base_neighborhood += 1
        if sqft > 2000:
            base_neighborhood += 1

        neighborhood_score = min(10, max(1, base_neighborhood + random.randint(-2, 2)))

        # Foreclosure context
        foreclosing_entity = random.choice(self.foreclosing_entities)
        loan_type = random.choice(self.loan_types)
        foreclosure_stage = random.choice(self.foreclosure_stages)
        # Total debt is typically higher than auction price
        debt_ratio = random.uniform(1.1, 1.8)
        total_debt = round(auction_price * debt_ratio, 2)
        # Default date is 3-18 months before auction
        months_ago = random.randint(3, 18)
        default_date = (datetime.now() - timedelta(days=months_ago * 30)).strftime("%Y-%m-%d")
        
        # Description
        condition = "light cosmetic" if repair_factor <= 0.15 else "moderate"
        description = (f"Single family home in {city}, {state}. "
                      f"Property needs {condition} updates and repairs. "
                      f"Great opportunity in a {neighborhood_score}/10 neighborhood.")
        
        return Property(
            id=f"PROP-{index + 1001}",
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            region=region,
            auction_price=round(auction_price, 2),
            estimated_arv=round(estimated_arv, 2),
            estimated_repairs=round(estimated_repairs, 2),
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            sqft=sqft,
            lot_size=lot_size,
            year_built=year_built,
            property_type="Single Family",
            auction_date=auction_date,
            auction_platform=random.choice(config.AUCTION_PLATFORMS),
            description=description,
            neighborhood_score=neighborhood_score,
            foreclosing_entity=foreclosing_entity,
            total_debt=total_debt,
            loan_type=loan_type,
            default_date=default_date,
            foreclosure_stage=foreclosure_stage,
        )


def generate_mock_data(count: int = None) -> List[Property]:
    """Convenience function to generate mock data"""
    generator = MockDataGenerator()
    return generator.generate_properties(count)
