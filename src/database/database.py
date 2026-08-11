"""
Thin SQLite access layer. No ORM -- just sqlite3 + small helper methods,
per the project's "don't overengineer" guidance.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, List

from src.database.models import SCHEMA_SQL
from src.models.listing import Listing, ProcessedListing
from src.utils.logging import logger


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str = "data/listings.db"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    # -- new-listing detection ------------------------------------------------

    def listing_exists(self, listing_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM listings WHERE listing_id = ?", (listing_id,)
            ).fetchone()
            return row is not None

    def get_known_listing_ids(self) -> set:
        with self._connect() as conn:
            rows = conn.execute("SELECT listing_id FROM listings").fetchall()
            return {r["listing_id"] for r in rows}

    # -- writes ----------------------------------------------------------------

    def upsert_listing(self, listing: Listing) -> None:
        now = _now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT first_seen_at FROM listings WHERE listing_id = ?",
                (listing.listing_id,),
            ).fetchone()
            first_seen = existing["first_seen_at"] if existing else now

            conn.execute(
                """
                INSERT INTO listings (
                    listing_id, source, url, title, description, property_type,
                    transaction_type, city, district, neighborhood, address,
                    latitude, longitude, price, currency, original_price,
                    original_currency, area_sqm, price_per_sqm, rooms, bedrooms,
                    floor, total_floors, building_year, building_type,
                    renovation_status, furnished, seller_type, seller_name,
                    published_at, first_seen_at, last_seen_at, ambiguous_fields, raw_data
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    price=excluded.price, currency=excluded.currency,
                    price_per_sqm=excluded.price_per_sqm, last_seen_at=excluded.last_seen_at,
                    raw_data=excluded.raw_data
                """,
                (
                    listing.listing_id, listing.source, listing.url, listing.title,
                    listing.description, listing.property_type, listing.transaction_type,
                    listing.city, listing.district, listing.neighborhood, listing.address,
                    listing.latitude, listing.longitude, listing.price, listing.currency,
                    listing.original_price, listing.original_currency, listing.area_sqm,
                    listing.price_per_sqm, listing.rooms, listing.bedrooms, listing.floor,
                    listing.total_floors, listing.building_year, listing.building_type,
                    listing.renovation_status,
                    None if listing.furnished is None else int(listing.furnished),
                    listing.seller_type, listing.seller_name,
                    listing.published_at.isoformat() if listing.published_at else None,
                    first_seen, now,
                    json.dumps(listing.ambiguous_fields, ensure_ascii=False),
                    json.dumps(listing.raw_data, ensure_ascii=False, default=str),
                ),
            )

    def save_analysis(self, processed: ProcessedListing) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analysis (
                    listing_id, market_average_price, market_median_price, comparable_count,
                    estimated_market_price, estimated_market_price_per_sqm, discount_percentage,
                    rule_score, ai_score, final_deal_score, deal_classification,
                    ai_summary, ai_positive_factors, ai_risk_factors, ai_confidence, analyzed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    market_average_price=excluded.market_average_price,
                    market_median_price=excluded.market_median_price,
                    comparable_count=excluded.comparable_count,
                    estimated_market_price=excluded.estimated_market_price,
                    estimated_market_price_per_sqm=excluded.estimated_market_price_per_sqm,
                    discount_percentage=excluded.discount_percentage,
                    rule_score=excluded.rule_score, ai_score=excluded.ai_score,
                    final_deal_score=excluded.final_deal_score,
                    deal_classification=excluded.deal_classification,
                    ai_summary=excluded.ai_summary, ai_positive_factors=excluded.ai_positive_factors,
                    ai_risk_factors=excluded.ai_risk_factors, ai_confidence=excluded.ai_confidence,
                    analyzed_at=excluded.analyzed_at
                """,
                (
                    processed.listing.listing_id,
                    processed.market.market_average_price_per_sqm,
                    processed.market.market_median_price_per_sqm,
                    processed.market.comparable_count,
                    processed.market.estimated_market_price,
                    processed.market.estimated_market_price_per_sqm,
                    processed.market.discount_percentage,
                    processed.score.rule_score, processed.score.ai_score, processed.score.final_score,
                    processed.score.classification,
                    processed.ai.summary,
                    json.dumps(processed.ai.positive_factors, ensure_ascii=False),
                    json.dumps(processed.ai.risk_factors, ensure_ascii=False),
                    processed.ai.confidence, now,
                ),
            )

    def mark_processed(self, listing_id: str, telegram_sent: bool, telegram_message_id: Optional[int]) -> None:
        now = _now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT first_processed_at FROM processing WHERE listing_id = ?", (listing_id,)
            ).fetchone()
            first_processed = existing["first_processed_at"] if existing else now
            conn.execute(
                """
                INSERT INTO processing (listing_id, first_processed_at, last_processed_at,
                                         telegram_sent, telegram_message_id)
                VALUES (?,?,?,?,?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    last_processed_at=excluded.last_processed_at,
                    telegram_sent = telegram_sent OR excluded.telegram_sent,
                    telegram_message_id = COALESCE(excluded.telegram_message_id, processing.telegram_message_id)
                """,
                (listing_id, first_processed, now, int(telegram_sent), telegram_message_id),
            )

    def was_telegram_sent(self, listing_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT telegram_sent FROM processing WHERE listing_id = ?", (listing_id,)
            ).fetchone()
            return bool(row and row["telegram_sent"])

    def record_run_stats(self, listings_checked: int, new_listings: int, ai_analyzed: int, deals_found: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO run_stats (run_at, listings_checked, new_listings, ai_analyzed, deals_found) "
                "VALUES (?,?,?,?,?)",
                (_now_iso(), listings_checked, new_listings, ai_analyzed, deals_found),
            )

    # -- reads for Telegram commands -------------------------------------------

    def get_last_run_stats(self) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_stats ORDER BY run_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def get_top_deals(self, limit: int = 10, since_iso: Optional[str] = None) -> List[dict]:
        with self._connect() as conn:
            if since_iso:
                rows = conn.execute(
                    """
                    SELECT l.*, a.* FROM listings l
                    JOIN analysis a ON a.listing_id = l.listing_id
                    WHERE a.analyzed_at >= ?
                    ORDER BY a.final_deal_score DESC LIMIT ?
                    """,
                    (since_iso, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT l.*, a.* FROM listings l
                    JOIN analysis a ON a.listing_id = l.listing_id
                    ORDER BY a.final_deal_score DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_comparables(self, city: str, district: str, property_type: str, exclude_id: str = None) -> List[dict]:
        """Fetch stored listings usable as comparables for market analysis."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM listings
                WHERE city = ? AND district = ? AND property_type = ?
                  AND price_per_sqm IS NOT NULL
                  AND (? IS NULL OR listing_id != ?)
                """,
                (city, district, property_type, exclude_id, exclude_id),
            ).fetchall()
            return [dict(r) for r in rows]
