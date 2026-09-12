import os
import tempfile

import pytest

from src.database.database import Database


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # Database() will create it fresh
    database = Database(path)
    yield database
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# /start registration
# ---------------------------------------------------------------------------

def test_new_user_gets_configured_defaults(db):
    user = db.register_user(
        telegram_user_id=111, chat_id="111",
        good_enabled=False, excellent_enabled=True, exceptional_enabled=True,
    )
    assert user["good_enabled"] == 0
    assert user["excellent_enabled"] == 1
    assert user["exceptional_enabled"] == 1
    assert user["notifications_enabled"] == 1
    assert user["blocked"] == 0


def test_existing_user_prefs_survive_second_start(db):
    db.register_user(telegram_user_id=111, chat_id="111",
                      good_enabled=False, excellent_enabled=True, exceptional_enabled=True)
    db.update_user_pref(111, "good_enabled", True)

    # User sends /start again (e.g. after restarting Telegram) -- their
    # customized preference must NOT be reset back to the default.
    user = db.register_user(
        telegram_user_id=111, chat_id="111",
        good_enabled=False, excellent_enabled=True, exceptional_enabled=True,
    )
    assert user["good_enabled"] == 1


def test_start_reactivates_a_stopped_user(db):
    db.register_user(telegram_user_id=111, chat_id="111")
    db.set_notifications_enabled(111, False)
    assert db.get_user(111)["notifications_enabled"] == 0

    db.register_user(telegram_user_id=111, chat_id="111")
    assert db.get_user(111)["notifications_enabled"] == 1


# ---------------------------------------------------------------------------
# Per-user classification preferences (User A / B / C from the spec)
# ---------------------------------------------------------------------------

@pytest.fixture
def three_users(db):
    # User A: Good OFF, Excellent OFF, Exceptional ON
    db.register_user(telegram_user_id=1, chat_id="1",
                      good_enabled=False, excellent_enabled=False, exceptional_enabled=True)
    # User B: Good ON, Excellent ON, Exceptional ON
    db.register_user(telegram_user_id=2, chat_id="2",
                      good_enabled=True, excellent_enabled=True, exceptional_enabled=True)
    # User C: Good ON, Excellent OFF, Exceptional OFF
    db.register_user(telegram_user_id=3, chat_id="3",
                      good_enabled=True, excellent_enabled=False, exceptional_enabled=False)
    return db


def _wants(db, user_id, classification):
    return db.user_wants_classification(db.get_user(user_id), classification)


def test_good_deal_goes_to_b_and_c_only(three_users):
    db = three_users
    assert _wants(db, 1, "GOOD") is False
    assert _wants(db, 2, "GOOD") is True
    assert _wants(db, 3, "GOOD") is True


def test_excellent_deal_goes_to_b_only(three_users):
    db = three_users
    assert _wants(db, 1, "EXCELLENT") is False
    assert _wants(db, 2, "EXCELLENT") is True
    assert _wants(db, 3, "EXCELLENT") is False


def test_exceptional_deal_goes_to_a_and_b_only(three_users):
    db = three_users
    assert _wants(db, 1, "EXCEPTIONAL") is True
    assert _wants(db, 2, "EXCEPTIONAL") is True
    assert _wants(db, 3, "EXCEPTIONAL") is False


def test_one_users_settings_never_affect_another(three_users):
    db = three_users
    db.update_user_pref(1, "good_enabled", True)
    assert _wants(db, 1, "GOOD") is True
    # B and C must be completely unaffected by A's change.
    assert _wants(db, 2, "GOOD") is True
    assert _wants(db, 3, "GOOD") is True
    db.update_user_pref(2, "exceptional_enabled", False)
    assert _wants(db, 1, "EXCEPTIONAL") is True
    assert _wants(db, 3, "EXCEPTIONAL") is False


def test_blocked_or_paused_user_wants_nothing(three_users):
    db = three_users
    db.set_notifications_enabled(2, False)
    assert _wants(db, 2, "GOOD") is False
    assert _wants(db, 2, "EXCELLENT") is False
    assert _wants(db, 2, "EXCEPTIONAL") is False


def test_settings_persist_across_a_new_database_connection(db):
    """Simulates surviving a restart: prefs are read from disk, not memory."""
    db.register_user(telegram_user_id=1, chat_id="1", good_enabled=False)
    db.update_user_pref(1, "good_enabled", True)

    reopened = Database(db.path)
    assert reopened.get_user(1)["good_enabled"] == 1


# ---------------------------------------------------------------------------
# Per-user delivery dedupe (never send the same listing twice to one user)
# ---------------------------------------------------------------------------

def test_delivery_is_recorded_and_not_duplicated(db):
    db.register_user(telegram_user_id=1, chat_id="1")
    assert db.was_alert_delivered("mock:1", 1) is False

    inserted = db.record_delivery("mock:1", 1, "EXCELLENT")
    assert inserted is True
    assert db.was_alert_delivered("mock:1", 1) is True

    # Recording the same listing+user pair again must not create a duplicate
    # row (unique constraint) and record_delivery should report that.
    inserted_again = db.record_delivery("mock:1", 1, "EXCELLENT")
    assert inserted_again is False


def test_delivery_tracking_is_independent_per_user(db):
    db.register_user(telegram_user_id=1, chat_id="1")
    db.register_user(telegram_user_id=2, chat_id="2")
    db.record_delivery("mock:1", 1, "EXCELLENT")

    assert db.was_alert_delivered("mock:1", 1) is True
    assert db.was_alert_delivered("mock:1", 2) is False


# ---------------------------------------------------------------------------
# Legacy single-chat bootstrap (keeps the existing operator subscribed)
# ---------------------------------------------------------------------------

def test_bootstrap_legacy_subscriber_creates_a_user_once(db):
    user = db.bootstrap_legacy_subscriber("555", good_enabled=False, excellent_enabled=True, exceptional_enabled=True)
    assert user is not None
    assert user["telegram_user_id"] == 555
    assert db.get_user(555) is not None


def test_bootstrap_does_not_touch_an_existing_users_prefs(db):
    db.register_user(telegram_user_id=555, chat_id="555",
                      good_enabled=True, excellent_enabled=False, exceptional_enabled=False)
    db.bootstrap_legacy_subscriber("555", good_enabled=False, excellent_enabled=True, exceptional_enabled=True)

    user = db.get_user(555)
    assert user["good_enabled"] == 1
    assert user["excellent_enabled"] == 0
    assert user["exceptional_enabled"] == 0


def test_bootstrap_with_empty_chat_id_is_a_no_op(db):
    assert db.bootstrap_legacy_subscriber("") is None
    assert db.bootstrap_legacy_subscriber(None) is None
