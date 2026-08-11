from src.sources.listam_parser import parse_listing_cards


SAMPLE_HTML = """
<html><body>
<div class="gl">
  <a href="/en/item/12345?ld_src=2" class="h">
    <div class="p">$125,000</div>
    <div class="l">2 room apartment on Example Street in Arabkir, 74 sq.m.</div>
    <div class="at">Arabkir, 2 rm., 74 sq.m., 7/14 floor</div>
  </a>
</div>
<div class="gl">
  <a href="/en/item/99999?ld_src=2" class="h">
    <div class="p">18,000,000 ֏</div>
    <div class="l">Agency 3 room apartment in Kentron</div>
    <div class="at">Kentron, 3 rm., 90 sq.m., 5/9 floor</div>
  </a>
</div>
</body></html>
"""


def test_parse_listing_cards_extracts_core_fields():
    cards = parse_listing_cards(SAMPLE_HTML, property_type="apartment")
    assert len(cards) == 2

    first = cards[0]
    assert first["id"] == "12345"
    assert first["price_raw"] == "$125,000"
    assert first["district"] == "Arabkir"
    assert first["rooms"] == "2"
    assert first["area_raw"] == "74 sq.m."
    assert first["floor"] == "7"
    assert first["total_floors"] == "14"
    assert first["property_type"] == "apartment"
    assert first["url"].endswith("/en/item/12345?ld_src=2")

    second = cards[1]
    assert second["seller_type"] == "agent"
    assert "18,000,000" in second["price_raw"]
