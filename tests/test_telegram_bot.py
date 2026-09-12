import os
import tempfile

import pytest

from config.settings import Settings
from src.database.database import Database
from src.models.listing import Listing, MarketAnalysis, AIAssessment
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


def make_processed():
    settings = Settings()
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
    score = calculate_final_score(listing, market, ai, settings)
    from src.models.listing import ProcessedListing
    return ProcessedListing(listing=listing, market=market, ai=ai, score=score)


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def test_deal_message_contains_price_and_score():
    processed = make_processed()
    text = bot.format_deal_message(processed)
    assert "$125,000" in text
    assert f"{processed.score.final_score:.0f}/100" in text
    assert "WHY LASEO LIKES IT" in text
    assert "WHAT TO CHECK" in text


def test_deal_message_breakdown_matches_real_components():
    processed = make_processed()
    text = bot.format_deal_message(processed)
    for c in processed.score.components:
        assert c.name in text


def test_open_listing_button_uses_real_url():
    processed = make_processed()
    markup = bot._deal_alert_keyboard(processed.listing.url)
    assert markup["inline_keyboard"][0][0]["url"] == "https://list.am/item/1"


def test_no_button_when_no_url():
    assert bot._deal_alert_keyboard("") is None


# ---------------------------------------------------------------------------
# Settings keyboard reflects real per-user state
# ---------------------------------------------------------------------------

def test_settings_text_shows_on_off_correctly():
    user = {"good_enabled": 0, "excellent_enabled": 1, "exceptional_enabled": 1, "notifications_enabled": 1}
    text = bot.format_settings_text(user)
    assert "Good: OFF" in text
    assert "Excellent: ON" in text
    assert "Exceptional: ON" in text


def test_settings_keyboard_has_three_toggle_buttons():
    user = {"good_enabled": 0, "excellent_enabled": 1, "exceptional_enabled": 1}
    kb = bot.build_settings_keyboard(user)
    callback_data = [row[0]["callback_data"] for row in kb["inline_keyboard"]]
    assert callback_data == ["toggle:good", "toggle:excellent", "toggle:exceptional"]


# ---------------------------------------------------------------------------
# process_telegram_updates dispatch (HTTP calls mocked out)
# ---------------------------------------------------------------------------

@pytest.fixture
def settings():
    s = Settings()
    s.telegram_bot_token = "test-token"
    return s


def test_start_command_registers_a_new_user(db, settings, monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "_get_updates", lambda s, offset: [
        {"update_id": 1, "message": {"text": "/start", "chat": {"id": 555}, "from": {"id": 555, "first_name": "Areg"}}}
    ])
    monkeypatch.setattr(bot, "_post", lambda s, method, payload: sent.append((method, payload)) or {"ok": True, "result": {"message_id": 1}})

    count = bot.process_telegram_updates(settings, db)

    assert count == 1
    user = db.get_user(555)
    assert user is not None
    assert user["excellent_enabled"] == 1  # default
    assert db.get_bot_state(bot._OFFSET_KEY) == "1"


def test_stop_command_pauses_only_that_user(db, settings, monkeypatch):
    db.register_user(telegram_user_id=1, chat_id="1")
    db.register_user(telegram_user_id=2, chat_id="2")

    monkeypatch.setattr(bot, "_get_updates", lambda s, offset: [
        {"update_id": 5, "message": {"text": "/stop", "chat": {"id": 1}, "from": {"id": 1}}}
    ])
    monkeypatch.setattr(bot, "_post", lambda s, method, payload: {"ok": True, "result": {"message_id": 1}})

    bot.process_telegram_updates(settings, db)

    assert db.get_user(1)["notifications_enabled"] == 0
    assert db.get_user(2)["notifications_enabled"] == 1  # unaffected


def test_callback_toggles_the_right_preference_only(db, settings, monkeypatch):
    db.register_user(telegram_user_id=9, chat_id="9",
                      good_enabled=False, excellent_enabled=True, exceptional_enabled=True)

    monkeypatch.setattr(bot, "_get_updates", lambda s, offset: [
        {
            "update_id": 10,
            "callback_query": {
                "id": "cb1", "data": "toggle:good",
                "from": {"id": 9},
                "message": {"chat": {"id": 9}, "message_id": 42},
            },
        }
    ])
    monkeypatch.setattr(bot, "_post", lambda s, method, payload: {"ok": True, "result": {"message_id": 1}})

    bot.process_telegram_updates(settings, db)

    user = db.get_user(9)
    assert user["good_enabled"] == 1        # toggled on
    assert user["excellent_enabled"] == 1   # untouched
    assert user["exceptional_enabled"] == 1  # untouched


def test_offset_advances_so_updates_are_not_reprocessed(db, settings, monkeypatch):
    calls = {"n": 0}

    def fake_get_updates(s, offset):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"update_id": 100, "message": {"text": "/help", "chat": {"id": 1}, "from": {"id": 1}}}]
        # Second call must request offset=101 (100 + 1); simulate no new updates.
        assert offset == 101
        return []

    monkeypatch.setattr(bot, "_get_updates", fake_get_updates)
    monkeypatch.setattr(bot, "_post", lambda s, method, payload: {"ok": True, "result": {"message_id": 1}})

    bot.process_telegram_updates(settings, db)
    bot.process_telegram_updates(settings, db)
    assert calls["n"] == 2
