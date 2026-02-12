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
    auction_date: str  # YYYY-MM-DD or "" if unknown
    auction_platform: str
    description: str

    # Quality metrics
    neighborhood_score: int  # 1-10 scale

    # Calculated fields (computed after creation)
    profit_potential: float = 0.0
    profit_margin: float = 0.0
    total_investment: float = 0.0
    max_bid_price: float = 0.0
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

    # Property condition and occupancy
    occupancy_status: Optional[str] = None       # "Vacant", "Owner Occupied", "Tenant Occupied", "Unknown"
    condition_category: Optional[str] = None     # "Cosmetic Only", "Light Rehab", "Moderate Rehab", "Heavy Rehab"

    # Tax and financial data
    annual_property_tax: Optional[float] = None
    hoa_monthly: Optional[float] = None
    estimated_monthly_rent: Optional[float] = None

    # Previous sale history
    last_sale_price: Optional[float] = None
    last_sale_date: Optional[str] = None

    # Geolocation
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Additional metadata
    county: Optional[str] = None
    data_source: Optional[str] = None            # "mock", "attom", "batchdata", "redfin", "sheriff", "auctioncom"
    auction_date_is_past: bool = False            # True if auction already occurred
    
    def calculate_metrics(self) -> None:
        """Calculate all investment metrics and scoring.

        Simplified formula (no repair estimates — those are unknowable
        without a physical inspection):
          Total investment = auction_price + closing(3%) + holding(ARV×1%×6mo)
          Profit = ARV − total_investment − selling(ARV×8%)
          Max bid = ARV × 0.70 × 0.91 (70% rule with 91% safety factor)
        """

        # Cost breakdown
        closing_costs = self.auction_price * config.CLOSING_COST_PERCENT
        holding_costs = (self.estimated_arv *
                        config.HOLDING_COST_PERCENT_PER_MONTH *
                        config.HOLDING_MONTHS)
        selling_costs = self.estimated_arv * config.SELLING_COST_PERCENT

        # Total investment (no repairs — unknowable without inspection)
        self.total_investment = (self.auction_price +
                                closing_costs +
                                holding_costs)

        # Profit calculation
        self.profit_potential = self.estimated_arv - self.total_investment - selling_costs
        self.profit_margin = ((self.profit_potential / self.estimated_arv) * 100
                             if self.estimated_arv > 0 else 0)

        # Max bid price — 70% rule at 91% safety margin
        # ARV × 0.70 × 0.91 (no repair deduction — account for repairs in your own due diligence)
        self.max_bid_price = round(max(0, self.estimated_arv * 0.70 * 0.91), 2)

        # Deal scoring
        self.deal_score = self._calculate_deal_score()

        # Recommendation
        self.recommended = (
            self.profit_margin >= config.MIN_PROFIT_MARGIN and
            self.deal_score >= config.MIN_DEAL_SCORE
        )
    
    def _calculate_deal_score(self) -> float:
        """Calculate deal quality score (0-100).

        Weights (must sum to 100):
          - Profit margin: 50 pts  (was 40; absorbed repair_efficiency)
          - Neighborhood:  25 pts  (was 20)
          - Property chars: 25 pts (was 20)
        """
        score = 0
        t = config.SCORING_THRESHOLDS

        # 1. Profit Margin Score (50 points max)
        margin_weight = config.SCORE_WEIGHTS["profit_margin"]
        if self.profit_margin >= t["margin_excellent"]:
            score += margin_weight
        elif self.profit_margin >= t["margin_good"]:
            score += margin_weight * 0.75 + (self.profit_margin - t["margin_good"]) * 0.25
        else:
            score += self.profit_margin * (margin_weight / t["margin_excellent"])

        # 2. Neighborhood Score (25 points max)
        neighborhood_weight = config.SCORE_WEIGHTS["neighborhood"]
        score += (self.neighborhood_score / 10) * neighborhood_weight

        # 3. Property Characteristics Score (25 points max)
        char_weight = config.SCORE_WEIGHTS["property_characteristics"]
        char_score = 0

        # Ideal square footage
        if t["sqft_ideal_min"] <= self.sqft <= t["sqft_ideal_max"]:
            char_score += 5
        elif t["sqft_acceptable_min"] <= self.sqft < t["sqft_ideal_min"] or t["sqft_ideal_max"] < self.sqft <= t["sqft_acceptable_max"]:
            char_score += 3

        # Bedroom count
        if t["beds_ideal_min"] <= self.bedrooms <= t["beds_ideal_max"]:
            char_score += 5
        elif self.bedrooms in t["beds_acceptable"]:
            char_score += 3

        # Bathroom count
        if self.bathrooms >= t["baths_good"]:
            char_score += 5
        elif self.bathrooms >= t["baths_acceptable"]:
            char_score += 3

        # Age of home
        age = datetime.now().year - self.year_built
        if age <= t["age_new"]:
            char_score += 5
        elif age <= t["age_mid"]:
            char_score += 3
        elif age <= t["age_old"]:
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
