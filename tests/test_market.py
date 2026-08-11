from src.analysis.market import analyze_market, classify_discount, similarity_score
from src.models.listing import Listing


def make_listing(**kwargs):
    defaults = dict(
        listing_id="x", source="mock", url="https://x", title="t",
        property_type="apartment", city="Yerevan", district="Arabkir",
        area_sqm=75.0, rooms=2, renovation_status="renovated", building_type="monolith",
        price=120000.0, price_per_sqm=1600.0,
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def make_comparable(price_per_sqm, **kwargs):
    row = dict(
        property_type="apartment", district="Arabkir", area_sqm=75.0, rooms=2,
        renovation_status="renovated", building_type="monolith", price_per_sqm=price_per_sqm,
    )
    row.update(kwargs)
    return row


def test_outlier_is_excluded_from_market_estimate():
    # From project spec: prices 1800,1850,1900,1950,2000,2050,2100,5000
    # 5000 should NOT drag the estimate up to "great deal" territory for a 2100 listing.
    values = [1800, 1850, 1900, 1950, 2000, 2050, 2100, 5000]
    comparables = [make_comparable(v) for v in values]
    listing = make_listing(price_per_sqm=2100.0)

    result = analyze_market(listing, comparables)

    assert result.comparable_count < len(values), "the 5000 outlier should be filtered out"
    assert result.market_median_price_per_sqm < 2300  # not dragged up by the outlier
    # A $2100/sqm listing should NOT look like a huge discount once the outlier is removed.
    assert result.discount_percentage < 15


def test_median_preferred_with_enough_comparables():
    comparables = [make_comparable(v) for v in [1500, 1550, 1600, 1650, 1700, 1750]]
    listing = make_listing(price_per_sqm=1400.0)
    result = analyze_market(listing, comparables)
    assert result.comparable_count >= 4
    assert result.estimated_market_price_per_sqm == result.market_median_price_per_sqm


def test_no_comparables_returns_low_confidence():
    listing = make_listing()
    result = analyze_market(listing, [])
    assert result.comparable_count == 0
    assert result.confidence == "low"
    assert result.estimated_market_price_per_sqm is None


def test_similarity_requires_matching_property_type():
    listing = make_listing(property_type="apartment")
    candidate = make_comparable(1600, property_type="house")
    assert similarity_score(listing, candidate) == 0.0


def test_classify_discount_buckets():
    assert classify_discount(2) == "not_interesting"
    assert classify_discount(7) == "slightly_below_market"
    assert classify_discount(12) == "potential_deal"
    assert classify_discount(17) == "good_deal"
    assert classify_discount(25) == "excellent_deal"
    assert classify_discount(35) == "exceptional_investigate_carefully"
    assert classify_discount(None) == "unknown"


def test_acceptance_scenario_discount_calculation():
    """From project acceptance test: market ~$2150/sqm, listing ~$1689/sqm -> ~21.4% discount."""
    comparables = [make_comparable(v) for v in [2100, 2150, 2200, 2120, 2180, 2160]]
    listing = make_listing(area_sqm=74.0, price=125000.0, price_per_sqm=round(125000 / 74, 2))
    result = analyze_market(listing, comparables)
    assert 18 <= result.discount_percentage <= 25
