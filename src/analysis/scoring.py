"""
Final 0-100 deal score, combining market discount, location quality,
property characteristics, condition, comparable confidence, AI assessment,
and urgency/negotiation signals -- weighted per config/settings.py.

Each sub-score is 0-100 before weighting, so weights are simple percentages.
"""
from __future__ import annotations

from config.settings import Settings
from src.models.listing import Listing, MarketAnalysis, AIAssessment, DealScore

# Districts with strong general demand in Yerevan (illustrative default;
# easy to extend/replace with a config file later without touching logic).
_STRONG_LOCATIONS = {"kentron", "arabkir", "davtashen", "achapnyak"}


def _discount_subscore(market: MarketAnalysis) -> float:
    if market.discount_percentage is None:
        return 0.0
    # Cap at 40% discount -> 100 points, scale linearly, floor at 0 for <=0% discount.
    pct = max(0.0, min(market.discount_percentage, 40.0))
    return (pct / 40.0) * 100


def _location_subscore(listing: Listing) -> float:
    district = (listing.district or "").strip().lower()
    return 100.0 if district in _STRONG_LOCATIONS else 60.0


def _property_characteristics_subscore(listing: Listing) -> float:
    score = 50.0
    if listing.rooms and listing.rooms >= 2:
        score += 15
    if listing.total_floors and listing.floor:
        # Not ground floor, not top floor -- generally more desirable.
        if 1 < listing.floor < listing.total_floors:
            score += 15
    if listing.building_type in ("monolith", "stone"):
        score += 20
    return min(score, 100.0)


def _condition_subscore(listing: Listing) -> float:
    if listing.renovation_status == "renovated":
        return 100.0
    if listing.renovation_status == "needs_renovation":
        return 30.0
    return 50.0  # unknown


def _comparable_confidence_subscore(market: MarketAnalysis) -> float:
    return {"high": 100.0, "medium": 65.0, "low": 25.0}.get(market.confidence, 0.0)


def _ai_subscore(ai: AIAssessment) -> float:
    if ai.deal_quality is None:
        return 50.0  # neutral when AI wasn't run
    return max(0.0, min(ai.deal_quality, 10.0)) * 10


def _urgency_subscore(ai: AIAssessment, listing: Listing) -> float:
    text = f"{listing.title} {listing.description}".lower()
    urgency_words = ["շտապ", "urgent", "срочно"]
    has_signal = bool(ai.urgency_signals) or any(w in text for w in urgency_words)
    return 100.0 if has_signal else 40.0


def calculate_rule_score(listing: Listing, market: MarketAnalysis, settings: Settings) -> float:
    """Score using only rule-based signals (no AI) -- always available."""
    w = settings
    score = (
        _discount_subscore(market) * w.weight_market_discount
        + _location_subscore(listing) * w.weight_location_quality
        + _property_characteristics_subscore(listing) * w.weight_property_characteristics
        + _condition_subscore(listing) * w.weight_condition
        + _comparable_confidence_subscore(market) * w.weight_comparable_confidence
        + 50.0 * w.weight_ai_assessment  # neutral placeholder when no AI
        + _urgency_subscore(AIAssessment(), listing) * w.weight_urgency
    )
    return round(score, 1)


def calculate_final_score(
    listing: Listing, market: MarketAnalysis, ai: AIAssessment, settings: Settings
) -> DealScore:
    w = settings
    rule_component = (
        _discount_subscore(market) * w.weight_market_discount
        + _location_subscore(listing) * w.weight_location_quality
        + _property_characteristics_subscore(listing) * w.weight_property_characteristics
        + _condition_subscore(listing) * w.weight_condition
        + _comparable_confidence_subscore(market) * w.weight_comparable_confidence
    )
    ai_component = _ai_subscore(ai) * w.weight_ai_assessment
    urgency_component = _urgency_subscore(ai, listing) * w.weight_urgency

    final = round(rule_component + ai_component + urgency_component, 1)
    final = max(0.0, min(final, 100.0))

    if final >= 90:
        classification = "EXCEPTIONAL"
    elif final >= 80:
        classification = "EXCELLENT"
    elif final >= 70:
        classification = "GOOD"
    elif final >= 60:
        classification = "INTERESTING"
    else:
        classification = "IGNORE"

    return DealScore(
        rule_score=round(rule_component / (1 - w.weight_ai_assessment - w.weight_urgency), 1)
        if (1 - w.weight_ai_assessment - w.weight_urgency) > 0 else 0.0,
        ai_score=_ai_subscore(ai),
        final_score=final,
        classification=classification,
    )
