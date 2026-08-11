from config.settings import Settings
from src.analysis.scoring import calculate_final_score
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
