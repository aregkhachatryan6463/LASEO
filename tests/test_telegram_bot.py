import os
import tempfile

import pytest

from config.settings import Settings
from src.database.database import Database
from src.models.listing import Listing, MarketAnalysis, AIAssessment, ProcessedListing
from src.analysis.scoring import calculate_final_score
import src.telegram.bot as bot


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    database = Database(path)
    yield database
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def settings():
    s = Settings()
    s.telegram_bot_token = "test-token"
    return s


def make_processed():
    s = Settings()
    listing = Listing(
        listing_id="mock:1", source="mock", url="https://list.am/item/1",
        title="2-room apartment", property_type="apartment", city="Yerevan",
        district="Arabkir", area_sqm=74.0, rooms=2, floor=7, total_floors=14,
        renovation_status="renovated", price=125000.0, price_per_sqm=1689.0,
    )
    market = MarketAnalysis(estimated_market_price_per_sqm=2150.0, discount_percentage=21.4,
                             confidence="high", comparable_count=8)
    ai = AIAssessment(deal_quality=8.5, positive_factors=["Priced well below comparables"],
                       risk_factors=["Documents not verified"])
    score = calculate_final_score(listing, market, ai, s)
    return ProcessedListing(listing=listing, market=market, ai=ai, score=score)


# ---------------------------------------------------------------------------
# Compact alert message + buttons
# ---------------------------------------------------------------------------

def test_alert_contains_real_url_for_telegram_link_preview():
    processed = make_processed()
    text = bot.format_deal_message(processed)
    assert "https://list.am/item/1" in text  # plain url text triggers Telegram's photo preview


def test_alert_is_short_not_a_full_breakdown_dump():
    processed = make_processed()
    text = bot.format_deal_message(processed)
    assert "HOW LASEO SCORED" not in text
    assert "WHY THIS DEAL" not in text
    assert "$125,000" in text


def test_alert_keyboard_has_breakdown_why_and_open_listing():
    processed = make_processed()
    kb = bot._deal_alert_keyboard(processed.listing.listing_id, processed.listing.url)
    top_row = [b["callback_data"] for b in kb["inline_keyboard"][0]]
    assert top_row == ["breakdown:mock:1", "why:mock:1"]
    assert kb["inline_keyboard"][1][0]["url"] == "https://list.am/item/1"


def test_no_open_listing_button_when_no_url():
    kb = bot._deal_alert_keyboard("mock:1", "")
    assert len(kb["inline_keyboard"]) == 1  # only breakdown/why, no url row


# ---------------------------------------------------------------------------
# On-demand breakdown / why, reconstructed from a stored DB row
# ---------------------------------------------------------------------------

def test_breakdown_from_row_matches_real_components(db):
    processed = make_processed()
    db.upsert_listing(processed.listing)
    db.save_analysis(processed)
    row = db.get_listing_analysis_row("mock:1")

    text = bot.format_score_breakdown_from_row(row)
    for c in processed.score.components:
        assert c.name in text
    assert f"{processed.score.final_score:.0f}/100" in text


def test_why_from_row_includes_ai_factors_and_confidence(db):
    processed = make_processed()
    db.upsert_listing(processed.listing)
    db.save_analysis(processed)
    row = db.get_listing_analysis_row("mock:1")

    text = bot.format_why_from_row(row)
    assert "Priced well below comparables" in text
    assert "Documents not verified" in text
    assert "HIGH" in text  # 8 comparables -> high confidence, per market.py thresholds


def test_confidence_thresholds_match_market_analysis():
    assert bot._confidence_from_comparable_count(8) == "high"
    assert bot._confidence_from_comparable_count(4) == "medium"
    assert bot._confidence_from_comparable_count(3) == "low"


# ---------------------------------------------------------------------------
# Settings text/keyboard include price range
# ---------------------------------------------------------------------------

def test_settings_text_shows_price_range():
    user = {"good_enabled": 0, "excellent_enabled": 1, "exceptional_enabled": 1,
            "min_price_usd": 50000, "max_price_usd": 150000, "notifications_enabled": 1}
    text = bot.format_settings_text(user)
    assert "$50,000" in text and "$150,000" in text


def test_settings_text_shows_any_price_when_unset():
    user = {"good_enabled": 0, "excellent_enabled": 1, "exceptional_enabled": 1, "notifications_enabled": 1}
    assert "Any price" in bot.format_settings_text(user)


def test_settings_keyboard_has_price_button_after_toggles():
    user = {"good_enabled": 0, "excellent_enabled": 1, "exceptional_enabled": 1}
    kb = bot.build_settings_keyboard(user)
    assert len(kb["inline_keyboard"]) == 4
    assert kb["inline_keyboard"][3][0]["callback_data"] == "setprice"


# ---------------------------------------------------------------------------
# Price range parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("50000-150000", (50000.0, 150000.0)),
    ("$50,000 - $150,000", (50000.0, 150000.0)),
    ("50000 to 150000", (50000.0, 150000.0)),
    ("150000-50000", (50000.0, 150000.0)),  # auto-corrects swapped order
    ("100000+", (100000.0, None)),
    ("under 200000", (None, 200000.0)),
    ("any", (None, None)),
    ("clear", (None, None)),
])
def test_parse_price_range_valid_inputs(text, expected):
    lo, hi, err = bot._parse_price_range(text)
    assert (lo, hi) == expected
    assert err is None


def test_parse_price_range_rejects_garbage_without_crashing():
    lo, hi, err = bot._parse_price_range("banana")
    assert lo is None and hi is None
    assert err is not None


# ---------------------------------------------------------------------------
# Price range preference storage + filtering
# ---------------------------------------------------------------------------

def test_price_range_persists_and_filters(db):
    db.register_user(telegram_user_id=1, chat_id="1")
    db.set_price_range(1, 50000, 150000)
    user = db.get_user(1)

    assert db.user_price_ok(user, 100000) is True
    assert db.user_price_ok(user, 40000) is False
    assert db.user_price_ok(user, 200000) is False


def test_no_price_range_means_no_filter(db):
    db.register_user(telegram_user_id=1, chat_id="1")
    user = db.get_user(1)
    assert db.user_price_ok(user, 1) is True
    assert db.user_price_ok(user, 10_000_000) is True


def test_setting_price_range_clears_pending_input(db):
    db.register_user(telegram_user_id=1, chat_id="1")
    db.set_pending_input(1, "price_range")
    db.set_price_range(1, 10, 20)
    assert db.get_user(1)["pending_input"] is None


# ---------------------------------------------------------------------------
# End-to-end command/callback dispatch (network mocked)
# ---------------------------------------------------------------------------

def test_setprice_button_then_typed_reply_sets_the_range(db, settings, monkeypatch):
    db.register_user(telegram_user_id=5, chat_id="5")
    monkeypatch.setattr(bot, "_post", lambda s, method, payload: {"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(bot, "_get_updates", lambda s, offset: [
        {"update_id": 1, "callback_query": {"id": "cb1", "data": "setprice", "from": {"id": 5},
                                             "message": {"chat": {"id": 5}, "message_id": 1}}}
    ])
    bot.process_telegram_updates(settings, db)
    assert db.get_user(5)["pending_input"] == "price_range"

    monkeypatch.setattr(bot, "_get_updates", lambda s, offset: [
        {"update_id": 2, "message": {"text": "80000-200000", "chat": {"id": 5}, "from": {"id": 5}}}
    ])
    bot.process_telegram_updates(settings, db)
    user = db.get_user(5)
    assert user["min_price_usd"] == 80000 and user["max_price_usd"] == 200000
    assert user["pending_input"] is None


def test_breakdown_callback_sends_a_message(db, settings, monkeypatch):
    processed = make_processed()
    db.upsert_listing(processed.listing)
    db.save_analysis(processed)

    sent = []
    monkeypatch.setattr(bot, "_post", lambda s, method, payload: sent.append((method, payload)) or {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(bot, "_get_updates", lambda s, offset: [
        {"update_id": 1, "callback_query": {"id": "cb1", "data": "breakdown:mock:1", "from": {"id": 99},
                                             "message": {"chat": {"id": 99}, "message_id": 1}}}
    ])
    bot.process_telegram_updates(settings, db)
    messages = [p for (m, p) in sent if m == "sendMessage"]
    assert any("HOW LASEO SCORED" in p["text"] for p in messages)


def test_free_text_without_pending_input_is_ignored_quietly(db, settings, monkeypatch):
    db.register_user(telegram_user_id=1, chat_id="1")
    monkeypatch.setattr(bot, "_post", lambda s, method, payload: {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr(bot, "_get_updates", lambda s, offset: [
        {"update_id": 1, "message": {"text": "hey what's up", "chat": {"id": 1}, "from": {"id": 1}}}
    ])
    # Should not raise, and should not set any price range.
    bot.process_telegram_updates(settings, db)
    assert db.get_user(1)["min_price_usd"] is None
