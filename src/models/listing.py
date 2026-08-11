"""
Core data structures shared across the whole pipeline.

Using plain dataclasses (not an ORM model) here keeps the "business object"
independent from how it is stored. src/database/models.py maps these to SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class Listing:
    # Identity
    listing_id: str          # stable ID, derived deterministically (see utils/normalization.py)
    source: str               # e.g. "mock", "listam"
    url: str

    # Content
    title: str
    description: str = ""
    property_type: str = "unknown"      # apartment, house, land, commercial, unknown
    transaction_type: str = "sale"      # sale, rent

    # Location
    city: str = ""
    district: str = ""
    neighborhood: str = ""
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Price (normalized)
    price: Optional[float] = None            # in base_currency (see settings.base_currency)
    currency: str = "USD"                    # currency the normalized price is in
    original_price: Optional[float] = None   # price as originally listed
    original_currency: Optional[str] = None  # currency as originally listed

    # Size / layout
    area_sqm: Optional[float] = None
    price_per_sqm: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None

    # Building
    building_year: Optional[int] = None
    building_type: Optional[str] = None       # stone, panel, monolith, etc.
    renovation_status: Optional[str] = None   # renovated, needs_renovation, unknown
    furnished: Optional[bool] = None

    # Seller
    seller_type: Optional[str] = None   # owner, agent, unknown
    seller_name: Optional[str] = None

    # Timestamps
    published_at: Optional[datetime] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    # Data quality
    ambiguous_fields: List[str] = field(default_factory=list)

    # Anything else from the source we want to keep for debugging / future use
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketAnalysis:
    market_average_price_per_sqm: Optional[float] = None
    market_median_price_per_sqm: Optional[float] = None
    comparable_count: int = 0
    estimated_market_price: Optional[float] = None
    estimated_market_price_per_sqm: Optional[float] = None
    discount_percentage: Optional[float] = None
    confidence: str = "low"   # low, medium, high -- based on comparable_count
    method_notes: str = ""
    analyzed_at: Optional[datetime] = None


@dataclass
class AIAssessment:
    is_residential: Optional[bool] = None
    is_likely_full_price: Optional[bool] = None
    potentially_misleading: Optional[bool] = None
    deal_quality: Optional[float] = None      # 0-10
    confidence: Optional[float] = None        # 0-1
    positive_factors: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    urgency_signals: List[str] = field(default_factory=list)
    summary: str = ""
    recommendation: str = "IGNORE"   # IGNORE, WATCH, INVESTIGATE, STRONG_DEAL
    used_ai: bool = False            # False when we fell back to rule-based analysis


@dataclass
class DealScore:
    rule_score: float = 0.0
    ai_score: float = 0.0
    final_score: float = 0.0
    classification: str = "IGNORE"   # EXCEPTIONAL, EXCELLENT, GOOD, INTERESTING, IGNORE


@dataclass
class ProcessedListing:
    """A listing bundled with all analysis results, ready for filtering/alerting/storage."""
    listing: Listing
    market: MarketAnalysis
    ai: AIAssessment
    score: DealScore
    telegram_sent: bool = False
    telegram_message_id: Optional[int] = None
