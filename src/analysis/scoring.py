"""
Final 0-100 deal score, combining market discount, location quality,
property characteristics, condition, comparable confidence, AI assessment,
and urgency/negotiation signals -- weighted per config/settings.py.

Each sub-score is 0-100 before weighting, so weights are simple percentages.

This module is the SINGLE SOURCE OF TRUTH for:
  - factor names and weights
  - classification thresholds
  - formula_version
  - the numerical breakdown shown in Telegram
"""
from __future__ import annotations

from typing import List, Tuple

from config.settings import Settings
from src.models.listing import Listing, MarketAnalysis, AIAssessment, DealScore, ScoreComponent

# Districts with strong general demand in Yerevan (illustrative default;
# easy to extend/replace with a config file later without touching logic).
_STRONG_LOCATIONS = {"kentron", "arabkir", "davtashen", "achapnyak"}

FORMULA_VERSION = "1.2"

ALERT_CLASSIFICATIONS = ("GOOD", "EXCELLENT", "EXCEPTIONAL")


def get_score_factor_defs(settings: Settings) -> List[Tuple[str, str, float]]:
    """
    Ordered (key, display_name, weight) tuples. Telegram "How LASEO Scores"
    and the alert breakdown both read from this list.
    """
    return [
        ("market_discount", "Market Discount", settings.weight_market_discount),
        ("comparable_confidence", "Comparable Confidence", settings.weight_comparable_confidence),
        ("location", "Location", settings.weight_location_quality),
        ("property_quality", "Property Quality", settings.weight_property_characteristics),
        ("condition", "Condition", settings.weight_condition),
        ("ai_assessment", "AI Assessment", settings.weight_ai_assessment),
        ("urgency", "Urgency / Negotiation", settings.weight_urgency),
    ]


def get_classification_thresholds(settings: Settings) -> dict:
    return {
        "INTERESTING": settings.threshold_interesting,
        "GOOD": settings.threshold_good,
        "EXCELLENT": settings.threshold_excellent,
        "EXCEPTIONAL": settings.threshold_exceptional,
    }


def classify_deal_score(final: float, settings: Settings) -> str:
    if final >= settings.threshold_exceptional:
        return "EXCEPTIONAL"
    if final >= settings.threshold_excellent:
        return "EXCELLENT"
    if final >= settings.threshold_good:
        return "GOOD"
    if final >= settings.threshold_interesting:
        return "INTERESTING"
    return "IGNORE"


def classification_label(classification: str) -> str:
    return {
        "EXCEPTIONAL": "🔥 EXCEPTIONAL",
        "EXCELLENT": "🔵 EXCELLENT",
        "GOOD": "🟢 GOOD",
        "INTERESTING": "🟡 INTERESTING",
        "IGNORE": "🏠 LISTING",
    }.get(classification, classification)


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


def _component(key: str, name: str, raw: float, weight: float) -> ScoreComponent:
    raw = max(0.0, min(float(raw), 100.0))
    return ScoreComponent(
        key=key,
        name=name,
        raw_score=round(raw, 1),
        weight=weight,
        contribution=round(raw * weight, 2),
    )


def _build_components(
    listing: Listing, market: MarketAnalysis, ai: AIAssessment, settings: Settings
) -> List[ScoreComponent]:
    raw_by_key = {
        "market_discount": _discount_subscore(market),
        "comparable_confidence": _comparable_confidence_subscore(market),
        "location": _location_subscore(listing),
        "property_quality": _property_characteristics_subscore(listing),
        "condition": _condition_subscore(listing),
        "ai_assessment": _ai_subscore(ai),
        "urgency": _urgency_subscore(ai, listing),
    }
    return [
        _component(key, name, raw_by_key[key], weight)
        for key, name, weight in get_score_factor_defs(settings)
    ]


def calculate_rule_score(listing: Listing, market: MarketAnalysis, settings: Settings) -> float:
    """Score using only rule-based signals (no AI) -- always available."""
    components = _build_components(listing, market, AIAssessment(), settings)
    return round(sum(c.contribution for c in components), 1)


def calculate_final_score(
    listing: Listing, market: MarketAnalysis, ai: AIAssessment, settings: Settings
) -> DealScore:
    components = _build_components(listing, market, ai, settings)
    penalties: List[ScoreComponent] = []  # current formula has no separate penalty term
    total = sum(c.contribution for c in components) - sum(p.contribution for p in penalties)
    final = max(0.0, min(round(total, 1), 100.0))

    non_ai_weight = 1.0 - settings.weight_ai_assessment - settings.weight_urgency
    rule_raw = sum(
        c.contribution for c in components if c.key not in ("ai_assessment", "urgency")
    )
    rule_score = round(rule_raw / non_ai_weight, 1) if non_ai_weight > 0 else 0.0

    return DealScore(
        rule_score=rule_score,
        ai_score=_ai_subscore(ai),
        final_score=final,
        classification=classify_deal_score(final, settings),
        components=components,
        penalties=penalties,
        formula_version=settings.formula_version or FORMULA_VERSION,
    )


def why_laseo_likes(listing: Listing, market: MarketAnalysis, ai: AIAssessment, score: DealScore) -> List[str]:
    bullets = []
    if market.discount_percentage is not None and market.discount_percentage > 0:
        bullets.append(
            f"Asking price is approximately {market.discount_percentage:.0f}% below estimated market value."
        )
    if market.comparable_count:
        strength = "strong" if market.confidence == "high" else market.confidence
        bullets.append(
            f"{market.comparable_count} comparable listing(s) support the valuation ({strength} confidence)."
        )
    district = (listing.district or "").strip()
    if district.lower() in _STRONG_LOCATIONS:
        bullets.append(f"{district} is treated as a strong local market.")
    if _urgency_subscore(ai, listing) >= 100:
        bullets.append("Listing or description signals urgency (possible negotiation room).")
    if listing.renovation_status == "renovated":
        bullets.append("Listed as renovated.")
    for factor in (ai.positive_factors or [])[:3]:
        if factor and factor not in bullets:
            bullets.append(factor)
    if not bullets:
        bullets.append("Score is based on the weighted factors shown in the breakdown.")
    return bullets[:6]


def why_it_may_not_be_a_deal(listing: Listing, market: MarketAnalysis, ai: AIAssessment) -> List[str]:
    bullets = []
    if market.confidence == "low" or market.comparable_count < 4:
        bullets.append(
            f"Valuation reliability is LOW ({market.comparable_count} comparable"
            f"{'' if market.comparable_count == 1 else 's'})."
        )
    if market.confidence == "medium":
        bullets.append("Comparable evidence is only medium — treat the discount as an estimate.")
    if listing.renovation_status in (None, "", "unknown"):
        bullets.append("Condition / renovation status is not specified.")
    if listing.renovation_status == "needs_renovation":
        bullets.append("Listing indicates the property needs renovation.")
    for field in (listing.ambiguous_fields or [])[:3]:
        bullets.append(f"Unclear data: {field}")
    for risk in (ai.risk_factors or [])[:4]:
        if risk:
            bullets.append(risk)
    bullets.append("Verify documents, final price, and actual condition in person.")
    bullets.append("This is not a professional appraisal.")
    # de-dupe while preserving order
    seen = set()
    unique = []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            unique.append(b)
    return unique[:7]


def format_formula_text(settings: Settings) -> str:
    lines = ["DEAL SCORE FORMULA", "", "Score ="]
    defs = get_score_factor_defs(settings)
    for i, (_key, name, weight) in enumerate(defs):
        prefix = "  " if i == 0 else "+ "
        lines.append(f"{prefix}{weight:.2f} × {name}")
    lines.append("")
    lines.append("Each factor is scored 0–100, then multiplied by its weight.")
    lines.append(f"Formula version: {settings.formula_version}")
    return "\n".join(lines)


def format_how_laseo_scores(settings: Settings) -> str:
    t = get_classification_thresholds(settings)
    lines = [
        "📊 HOW LASEO SCORES",
        "",
        "LASEO does not only check whether a price is below average.",
        "It combines several signals into a 0–100 Deal Score.",
        "",
        "WEIGHTS",
    ]
    for _key, name, weight in get_score_factor_defs(settings):
        lines.append(f"• {name} — {int(round(weight * 100))}%")
    lines += [
        "",
        "CLASSIFICATION",
        f"🟢 GOOD: {t['GOOD']:.0f}–{t['EXCELLENT'] - 1:.0f}",
        f"🔵 EXCELLENT: {t['EXCELLENT']:.0f}–{t['EXCEPTIONAL'] - 1:.0f}",
        f"🔥 EXCEPTIONAL: {t['EXCEPTIONAL']:.0f}–100",
        "",
        format_formula_text(settings),
        "",
        f"Formula version: {settings.formula_version}",
    ]
    return "\n".join(lines)
