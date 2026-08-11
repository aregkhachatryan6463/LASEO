from src.utils.normalization import parse_area_sqm, parse_price, make_listing_id, parse_int_safe


def test_parse_area_plain_number():
    assert parse_area_sqm("75")[0] == 75.0


def test_parse_area_with_armenian_unit():
    assert parse_area_sqm("75 քմ")[0] == 75.0


def test_parse_area_with_m2_symbol():
    assert parse_area_sqm("75 m²")[0] == 75.0


def test_parse_area_with_sqm_word():
    assert parse_area_sqm("75 sqm")[0] == 75.0


def test_parse_area_decimal_comma():
    val, note = parse_area_sqm("75,5 քմ")
    assert val == 75.5
    assert note is None


def test_parse_area_missing_returns_none_with_note():
    val, note = parse_area_sqm(None)
    assert val is None
    assert note is not None


def test_parse_price_dollar_with_commas():
    amount, currency, note = parse_price("$120,000")
    assert amount == 120000.0
    assert currency == "USD"
    assert note is None


def test_parse_price_code_suffix():
    amount, currency, note = parse_price("120000 USD")
    assert amount == 120000.0
    assert currency == "USD"


def test_parse_price_space_thousands_and_symbol():
    amount, currency, note = parse_price("120 000$")
    assert amount == 120000.0
    assert currency == "USD"


def test_parse_price_dot_thousands():
    amount, currency, note = parse_price("120.000$")
    assert amount == 120000.0
    assert currency == "USD"


def test_parse_price_no_currency_is_flagged_ambiguous():
    amount, currency, note = parse_price("120000")
    assert amount == 120000.0
    assert currency is None
    assert note is not None


def test_price_per_sqm_calculation():
    price, _, _ = parse_price("$120,000")
    area, _ = parse_area_sqm("75 sqm")
    price_per_sqm = price / area
    assert round(price_per_sqm) == 1600


def test_make_listing_id_prefers_native_id():
    lid = make_listing_id("mock", "1001", "https://example.com/1001")
    assert lid == "mock:1001"


def test_make_listing_id_falls_back_to_url_hash():
    lid1 = make_listing_id("mock", None, "https://example.com/1001")
    lid2 = make_listing_id("mock", None, "https://example.com/1001")
    lid3 = make_listing_id("mock", None, "https://example.com/1002")
    assert lid1 == lid2  # deterministic
    assert lid1 != lid3  # different URL -> different ID


def test_make_listing_id_never_uses_title_alone():
    import pytest
    with pytest.raises(ValueError):
        make_listing_id("mock", None, None)


def test_parse_int_safe():
    assert parse_int_safe("3") == 3
    assert parse_int_safe(3) == 3
    assert parse_int_safe(None) is None
