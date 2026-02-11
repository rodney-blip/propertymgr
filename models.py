"""
Data models for the Auction Property Analyzer
"""

from dataclasses import dataclass, asdict, field
from typing import Optional
from datetime import datetime
import config


@dataclass
class Property:
    """Property data model with all relevant information"""
    
    # Basic information
    id: str
    address: str
    city: str
    state: str
    zip_code: str
    region: str
    
    # Pricing
    auction_price: float
    estimated_arv: float
    estimated_repairs: float
    
    # Property details
    bedrooms: int
    bathrooms: float
    sqft: int
    lot_size: float
    year_built: int
    property_type: str
    
    # Auction details
    auction_date: str
    auction_platform: str
    description: str
    
    # Quality metrics
    neighborhood_score: int  # 1-10 scale
    
    # Calculated fields (computed after creation)
    profit_potential: float = 0.0
    profit_margin: float = 0.0
    total_investment: float = 0.0
    deal_score: float = 0.0
    recommended: bool = False
    
    # Foreclosure context
    foreclosing_entity: Optional[str] = None
    total_debt: Optional[float] = None
    loan_type: Optional[str] = None
    default_date: Optional[str] = None
    foreclosure_stage: Optional[str] = None

    # Optional fields
    property_url: Optional[str] = None
    bank_contact_url: Optional[str] = None
    image_url: Optional[str] = None
    notes: Optional[str] = None
    
    def calculate_metrics(self) -> None:
        """Calculate all investment metrics and scoring"""
        
        # Cost breakdown
        closing_costs = self.auction_price * config.CLOSING_COST_PERCENT
        holding_costs = (self.estimated_arv * 
                        config.HOLDING_COST_PERCENT_PER_MONTH * 
                        config.HOLDING_MONTHS)
        selling_costs = self.estimated_arv * config.SELLING_COST_PERCENT
        
        # Total investment
        self.total_investment = (self.auction_price + 
                                self.estimated_repairs + 
                                closing_costs + 
                                holding_costs)
        
        # Profit calculation
        self.profit_potential = self.estimated_arv - self.total_investment - selling_costs
        self.profit_margin = ((self.profit_potential / self.estimated_arv) * 100 
                             if self.estimated_arv > 0 else 0)
        
        # Deal scoring
        self.deal_score = self._calculate_deal_score()
        
        # Recommendation
        self.recommended = (
            self.profit_margin >= config.MIN_PROFIT_MARGIN and
            self.estimated_repairs <= config.MAX_REPAIR_COST and
            self.deal_score >= config.MIN_DEAL_SCORE
        )
    
    def _calculate_deal_score(self) -> float:
        """Calculate deal quality score (0-100)"""
        score = 0
        
        # 1. Profit Margin Score (40 points max)
        margin_weight = config.SCORE_WEIGHTS["profit_margin"]
        if self.profit_margin >= 40:
            score += margin_weight
        elif self.profit_margin >= 30:
            score += margin_weight * 0.75 + (self.profit_margin - 30) * 0.25
        else:
            score += self.profit_margin * (margin_weight / 40)
        
        # 2. Repair Efficiency Score (20 points max)
        repair_weight = config.SCORE_WEIGHTS["repair_efficiency"]
        repair_ratio = self.estimated_repairs / self.auction_price
        if repair_ratio <= 0.15:
            score += repair_weight
        elif repair_ratio <= 0.30:
            score += repair_weight * 0.75
        else:
            score += max(0, repair_weight * 0.5 - (repair_ratio - 0.30) * 50)
        
        # 3. Neighborhood Score (20 points max)
        neighborhood_weight = config.SCORE_WEIGHTS["neighborhood"]
        score += (self.neighborhood_score / 10) * neighborhood_weight
        
        # 4. Property Characteristics Score (20 points max)
        char_weight = config.SCORE_WEIGHTS["property_characteristics"]
        char_score = 0
        
        # Ideal square footage
        if 1500 <= self.sqft <= 3000:
            char_score += 5
        elif 1200 <= self.sqft < 1500 or 3000 < self.sqft <= 3500:
            char_score += 3
        
        # Bedroom count
        if 3 <= self.bedrooms <= 4:
            char_score += 5
        elif self.bedrooms == 2 or self.bedrooms == 5:
            char_score += 3
        
        # Bathroom count
        if self.bathrooms >= 2:
            char_score += 5
        elif self.bathrooms >= 1.5:
            char_score += 3
        
        # Age of home
        age = datetime.now().year - self.year_built
        if age <= 20:
            char_score += 5
        elif age <= 40:
            char_score += 3
        elif age <= 60:
            char_score += 1
        
        score += char_score
        
        return min(100, max(0, score))
    
    def get_alert_level(self) -> Optional[str]:
        """Get alert level for this property"""
        if self.profit_margin >= config.ALERT_LEVELS["hot"]:
            return "🔥 HOT DEAL"
        elif self.profit_margin >= config.ALERT_LEVELS["excellent"]:
            return "⭐ EXCELLENT"
        elif self.profit_margin >= config.ALERT_LEVELS["good"]:
            return "✅ GOOD"
        return None
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)
    
    def get_cost_breakdown(self) -> dict:
        """Get detailed cost breakdown"""
        return {
            "auction_price": self.auction_price,
            "repairs": self.estimated_repairs,
            "closing_costs": self.auction_price * config.CLOSING_COST_PERCENT,
            "holding_costs": (self.estimated_arv * 
                            config.HOLDING_COST_PERCENT_PER_MONTH * 
                            config.HOLDING_MONTHS),
            "selling_costs": self.estimated_arv * config.SELLING_COST_PERCENT,
            "total_investment": self.total_investment
        }
    
    def __str__(self) -> str:
        """String representation"""
        return (f"{self.address}, {self.city}, {self.state} | "
                f"${self.auction_price:,.0f} | "
                f"Margin: {self.profit_margin:.1f}% | "
                f"Score: {self.deal_score:.1f}")


@dataclass
class AnalysisResult:
    """Container for analysis results"""
    
    total_properties: int
    recommended_deals: int
    avg_profit_margin: float
    avg_deal_score: float
    top_deals: list
    all_properties: list
    alerts: list
    statistics: dict
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)
