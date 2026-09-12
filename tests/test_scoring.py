import pytest

from config.settings import Settings
from src.analysis.scoring import calculate_final_score, classify_deal_score
from src.models.listing import Listing, MarketAnalysis, AIAssessment


def make_listing(**kwargs):
    defaults = dict(
        listing_id="x", source="mock", url="https://x", title="ՇՏԱՊ 2 սենյականոց",
        property_type="apartment", city="Yerevan", district="Arabkir",
        area_sqm=74.0, rooms=2, floor=7, total_floors=14,
        renovation_status="renovated", building_type="monolith",
        price=125000.0, price_per_sqm=1689.0,
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def test_high_discount_high_confidence_scores_well():
    settings = Settings()
    listing = make_listing()
    market = MarketAnalysis(
        estimated_market_price_per_sqm=2150.0, discount_percentage=21.4,
        confidence="high", comparable_count=8,
    )
    ai = AIAssessment(deal_quality=8.5, confidence=0.86, recommendation="INVESTIGATE",
                       urgency_signals=["seller states urgent sale"])
    score = calculate_final_score(listing, market, ai, settings)
    assert score.final_score >= 70
    assert score.classification in ("GOOD", "EXCELLENT", "EXCEPTIONAL")


def test_no_discount_scores_low():
    settings = Settings()
    listing = make_listing(price_per_sqm=2200.0)
    market = MarketAnalysis(estimated_market_price_per_sqm=2150.0, discount_percentage=-2.3,
                             confidence="low", comparable_count=1)
    ai = AIAssessment()
    score = calculate_final_score(listing, market, ai, settings)
    assert score.final_score < 60
    assert score.classification == "IGNORE"


def test_score_is_bounded_0_to_100():
    settings = Settings()
    listing = make_listing()
    market = MarketAnalysis(estimated_market_price_per_sqm=10000.0, discount_percentage=95.0,
                             confidence="high", comparable_count=20)
    ai = AIAssessment(deal_quality=10.0, confidence=1.0, urgency_signals=["urgent"])
    score = calculate_final_score(listing, market, ai, settings)
    assert 0.0 <= score.final_score <= 100.0


# ---------------------------------------------------------------------------
# "Displayed formula must equal actual formula" guarantees
# ---------------------------------------------------------------------------

def _typical_score():
    settings = Settings()
    listing = make_listing()
    market = MarketAnalysis(estimated_market_price_per_sqm=2150.0, discount_percentage=21.4,
                             confidence="high", comparable_count=8)
    ai = AIAssessment(deal_quality=8.5, confidence=0.86, urgency_signals=["seller states urgent sale"])
    return settings, calculate_final_score(listing, market, ai, settings)


def test_each_component_contribution_equals_raw_times_weight():
    _settings, score = _typical_score()
    for c in score.components:
        assert c.contribution == pytest.approx(c.raw_score * c.weight, abs=0.01)


def test_sum_of_contributions_minus_penalties_equals_final_score():
    _settings, score = _typical_score()
    total = sum(c.contribution for c in score.components) - sum(p.contribution for p in score.penalties)
    total = max(0.0, min(round(total, 1), 100.0))
    assert total == pytest.approx(score.final_score, abs=0.1)


def test_component_weights_sum_to_one():
    settings = Settings()
    _s, score = _typical_score()
    total_weight = sum(c.weight for c in score.components)
    assert total_weight == pytest.approx(1.0, abs=0.001)


def test_formula_version_is_recorded_on_every_score():
    _settings, score = _typical_score()
    assert score.formula_version  # non-empty
    assert score.formula_version == Settings().formula_version


@pytest.mark.parametrize(
    "final_score,expected",
    [
        (95, "EXCEPTIONAL"),
        (90, "EXCEPTIONAL"),
        (89.9, "EXCELLENT"),
        (80, "EXCELLENT"),
        (79.9, "GOOD"),
        (70, "GOOD"),
        (69.9, "INTERESTING"),
        (60, "INTERESTING"),
        (59.9, "IGNORE"),
    ],
)
def test_classification_is_deterministic_from_thresholds(final_score, expected):
    """
    Classification must come purely from the numeric thresholds in
    config/settings.py -- never from an LLM's judgement call.
    """
    settings = Settings()
    assert classify_deal_score(final_score, settings) == expected
