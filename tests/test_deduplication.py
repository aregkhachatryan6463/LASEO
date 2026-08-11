import os
import tempfile

import pytest

from src.database.database import Database
from src.models.listing import Listing


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # Database() will create it fresh
    database = Database(path)
    yield database
    if os.path.exists(path):
        os.remove(path)


def make_listing(listing_id="mock:1001"):
    return Listing(
        listing_id=listing_id, source="mock", url="https://example.com/1001",
        title="Test listing", property_type="apartment", city="Yerevan",
        district="Arabkir", area_sqm=74.0, price=125000.0, price_per_sqm=1689.0,
    )


def test_new_listing_is_not_known_initially(db):
    assert not db.listing_exists("mock:1001")


def test_listing_becomes_known_after_upsert(db):
    db.upsert_listing(make_listing())
    assert db.listing_exists("mock:1001")


def test_repeated_upsert_is_idempotent(db):
    for _ in range(100):
        db.upsert_listing(make_listing())
    ids = db.get_known_listing_ids()
    assert len(ids) == 1
    assert "mock:1001" in ids


def test_telegram_not_sent_twice_for_same_listing(db):
    db.upsert_listing(make_listing())
    assert db.was_telegram_sent("mock:1001") is False

    db.mark_processed("mock:1001", telegram_sent=True, telegram_message_id=42)
    assert db.was_telegram_sent("mock:1001") is True

    # Running "processing" again for the same listing should not un-send it
    # nor should application logic re-send once was_telegram_sent() is True.
    db.mark_processed("mock:1001", telegram_sent=False, telegram_message_id=None)
    assert db.was_telegram_sent("mock:1001") is True


def test_different_listings_are_tracked_independently(db):
    db.upsert_listing(make_listing("mock:1001"))
    db.upsert_listing(make_listing("mock:1002"))
    ids = db.get_known_listing_ids()
    assert ids == {"mock:1001", "mock:1002"}
