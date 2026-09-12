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
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Additive migrations. Never drop production tables."""
        analysis_cols = {row[1] for row in conn.execute("PRAGMA table_info(analysis)").fetchall()}
        if "score_breakdown" not in analysis_cols:
            conn.execute("ALTER TABLE analysis ADD COLUMN score_breakdown TEXT")
        if "formula_version" not in analysis_cols:
            conn.execute("ALTER TABLE analysis ADD COLUMN formula_version TEXT")

        user_cols = {row[1] for row in conn.execute("PRAGMA table_info(telegram_users)").fetchall()}
        if "min_price_usd" not in user_cols:
            conn.execute("ALTER TABLE telegram_users ADD COLUMN min_price_usd REAL")
        if "max_price_usd" not in user_cols:
            conn.execute("ALTER TABLE telegram_users ADD COLUMN max_price_usd REAL")
        if "pending_input" not in user_cols:
            conn.execute("ALTER TABLE telegram_users ADD COLUMN pending_input TEXT")

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
                    ai_summary, ai_positive_factors, ai_risk_factors, ai_confidence, analyzed_at,
                    score_breakdown, formula_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    analyzed_at=excluded.analyzed_at,
                    score_breakdown=excluded.score_breakdown,
                    formula_version=excluded.formula_version
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
                    json.dumps(processed.score.to_breakdown_dict(), ensure_ascii=False),
                    processed.score.formula_version,
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

    def get_top_deals(
        self,
        limit: int = 10,
        since_iso: Optional[str] = None,
        classifications: Optional[List[str]] = None,
    ) -> List[dict]:
        with self._connect() as conn:
            clauses = []
            params: list = []
            if since_iso:
                clauses.append("a.analyzed_at >= ?")
                params.append(since_iso)
            if classifications:
                placeholders = ",".join("?" * len(classifications))
                clauses.append(f"a.deal_classification IN ({placeholders})")
                params.extend(classifications)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT l.*, a.final_deal_score, a.deal_classification, a.discount_percentage,
                       a.comparable_count, a.estimated_market_price, a.estimated_market_price_per_sqm,
                       a.score_breakdown, a.formula_version, a.ai_summary, a.ai_positive_factors,
                       a.ai_risk_factors, a.ai_confidence, a.analyzed_at
                FROM listings l
                JOIN analysis a ON a.listing_id = l.listing_id
                {where}
                ORDER BY a.final_deal_score DESC LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_listing_analysis_row(self, listing_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT l.*, a.final_deal_score, a.deal_classification, a.discount_percentage,
                       a.comparable_count, a.estimated_market_price, a.estimated_market_price_per_sqm,
                       a.market_median_price, a.score_breakdown, a.formula_version,
                       a.ai_summary, a.ai_positive_factors, a.ai_risk_factors, a.ai_confidence
                FROM listings l
                JOIN analysis a ON a.listing_id = l.listing_id
                WHERE l.listing_id = ?
                """,
                (listing_id,),
            ).fetchone()
            return dict(row) if row else None

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

    # -- Telegram users --------------------------------------------------------

    def get_user(self, telegram_user_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_chat_id(self, chat_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_users WHERE chat_id = ? LIMIT 1",
                (str(chat_id),),
            ).fetchone()
            return dict(row) if row else None

    def register_user(
        self,
        telegram_user_id: int,
        chat_id: str,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        good_enabled: bool = False,
        excellent_enabled: bool = True,
        exceptional_enabled: bool = True,
    ) -> dict:
        """Create user with defaults if new; preserve prefs if existing. Reactivate on /start."""
        now = _now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM telegram_users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE telegram_users SET
                        chat_id = ?, username = ?, first_name = ?,
                        last_seen_at = ?, updated_at = ?,
                        blocked = 0, notifications_enabled = 1
                    WHERE telegram_user_id = ?
                    """,
                    (str(chat_id), username, first_name, now, now, telegram_user_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO telegram_users (
                        telegram_user_id, chat_id, username, first_name,
                        good_enabled, excellent_enabled, exceptional_enabled,
                        notifications_enabled, blocked,
                        created_at, updated_at, last_seen_at
                    ) VALUES (?,?,?,?,?,?,?,?,0,?,?,?)
                    """,
                    (
                        telegram_user_id, str(chat_id), username, first_name,
                        int(good_enabled), int(excellent_enabled), int(exceptional_enabled),
                        1, now, now, now,
                    ),
                )
        return self.get_user(telegram_user_id)

    def touch_user(self, telegram_user_id: int, chat_id: Optional[str] = None) -> None:
        now = _now_iso()
        with self._connect() as conn:
            if chat_id:
                conn.execute(
                    "UPDATE telegram_users SET last_seen_at = ?, chat_id = ? WHERE telegram_user_id = ?",
                    (now, str(chat_id), telegram_user_id),
                )
            else:
                conn.execute(
                    "UPDATE telegram_users SET last_seen_at = ? WHERE telegram_user_id = ?",
                    (now, telegram_user_id),
                )

    def update_user_pref(self, telegram_user_id: int, field: str, value: bool) -> Optional[dict]:
        allowed = {
            "good_enabled", "excellent_enabled", "exceptional_enabled",
            "notifications_enabled", "blocked",
        }
        if field not in allowed:
            raise ValueError(f"Invalid user pref field: {field}")
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                f"UPDATE telegram_users SET {field} = ?, updated_at = ?, last_seen_at = ? WHERE telegram_user_id = ?",
                (int(value), now, now, telegram_user_id),
            )
        return self.get_user(telegram_user_id)

    def mark_user_blocked(self, telegram_user_id: int) -> None:
        self.update_user_pref(telegram_user_id, "blocked", True)

    def set_notifications_enabled(self, telegram_user_id: int, enabled: bool) -> Optional[dict]:
        return self.update_user_pref(telegram_user_id, "notifications_enabled", enabled)

    def get_active_users(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM telegram_users
                WHERE notifications_enabled = 1 AND blocked = 0
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def user_wants_classification(self, user: dict, classification: str) -> bool:
        if not user:
            return False
        if not user.get("notifications_enabled") or user.get("blocked"):
            return False
        mapping = {
            "GOOD": "good_enabled",
            "EXCELLENT": "excellent_enabled",
            "EXCEPTIONAL": "exceptional_enabled",
        }
        field = mapping.get(classification)
        if not field:
            return False
        return bool(user.get(field))

    def enabled_classifications_for_user(self, user: dict) -> List[str]:
        out = []
        if user.get("good_enabled"):
            out.append("GOOD")
        if user.get("excellent_enabled"):
            out.append("EXCELLENT")
        if user.get("exceptional_enabled"):
            out.append("EXCEPTIONAL")
        return out

    def user_price_ok(self, user: dict, price: Optional[float]) -> bool:
        """True if the listing's price is within this user's range (no range set = no limit)."""
        if price is None:
            return True
        min_price = user.get("min_price_usd")
        max_price = user.get("max_price_usd")
        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False
        return True

    def set_price_range(self, telegram_user_id: int, min_price: Optional[float], max_price: Optional[float]) -> Optional[dict]:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_users
                SET min_price_usd = ?, max_price_usd = ?, pending_input = NULL,
                    updated_at = ?, last_seen_at = ?
                WHERE telegram_user_id = ?
                """,
                (min_price, max_price, now, now, telegram_user_id),
            )
        return self.get_user(telegram_user_id)

    def set_pending_input(self, telegram_user_id: int, value: Optional[str]) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE telegram_users SET pending_input = ?, updated_at = ? WHERE telegram_user_id = ?",
                (value, now, telegram_user_id),
            )

    # -- Per-user deliveries ---------------------------------------------------

    def was_alert_delivered(self, listing_id: str, telegram_user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM alert_deliveries WHERE listing_id = ? AND telegram_user_id = ?",
                (listing_id, telegram_user_id),
            ).fetchone()
            return row is not None

    def record_delivery(self, listing_id: str, telegram_user_id: int, classification: str) -> bool:
        """Returns True if a new row was inserted, False if already delivered."""
        now = _now_iso()
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO alert_deliveries (listing_id, telegram_user_id, sent_at, deal_classification)
                    VALUES (?,?,?,?)
                    """,
                    (listing_id, telegram_user_id, now, classification),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def bootstrap_legacy_subscriber(
        self,
        chat_id: str,
        good_enabled: bool = False,
        excellent_enabled: bool = True,
        exceptional_enabled: bool = True,
    ) -> Optional[dict]:
        """
        If TELEGRAM_CHAT_ID is set in the environment and that chat has no user
        row yet, create one so the original operator is not silently dropped.
        Does not overwrite existing preferences.
        """
        chat_id = (chat_id or "").strip()
        if not chat_id:
            return None
        existing = self.get_user_by_chat_id(chat_id)
        if existing:
            return existing
        try:
            user_id = int(chat_id)
        except ValueError:
            logger.warning("TELEGRAM_CHAT_ID is set but is not numeric; skipping legacy bootstrap")
            return None
        if self.get_user(user_id):
            return self.get_user(user_id)
        logger.info("Bootstrapping legacy Telegram subscriber from TELEGRAM_CHAT_ID (prefs not overwritten later)")
        return self.register_user(
            telegram_user_id=user_id,
            chat_id=chat_id,
            first_name="Legacy subscriber",
            good_enabled=good_enabled,
            excellent_enabled=excellent_enabled,
            exceptional_enabled=exceptional_enabled,
        )

    # -- Bot getUpdates offset -------------------------------------------------

    def get_bot_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_bot_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO bot_state (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
