"""
Entry point / pipeline orchestrator.

Usage:
    python -m src.main --mock          run one monitoring cycle against mock data
    python -m src.main --production    run one monitoring cycle against the real
                                        data source (DATA_SOURCE in .env)
    python -m src.main --test          run the automated test suite
    python -m src.main --status        print last run stats and exit
    python -m src.main --commands      process any pending Telegram commands/
                                        button taps once and exit (the 5-minute
                                        monitoring cycle already does this
                                        automatically; use this only for
                                        manual/local testing)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone

from config.settings import settings, Settings
from src.database.database import Database
from src.models.listing import Listing, MarketAnalysis, AIAssessment, DealScore, ProcessedListing
from src.sources.base import SourceUnavailableError
from src.sources.mock import MockListingSource
from src.sources.listam import ListAmSource
from src.analysis.filters import passes_basic_filters, should_trigger_ai
from src.analysis.market import analyze_market
from src.analysis.scoring import calculate_final_score, ALERT_CLASSIFICATIONS
from src.ai.analyzer import AIAnalyzer
from src.telegram.bot import send_deal_alert, send_daily_summary, process_telegram_updates
from src.utils.currency import CurrencyConverter
from src.utils.logging import setup_logging


def get_source(settings: Settings, run_index: int = 0):
    if settings.data_source == "mock":
        return MockListingSource(run_index=run_index)
    if settings.data_source == "listam":
        return ListAmSource(
            max_pages=settings.listam_max_pages,
            request_delay_sec=settings.listam_request_delay_sec,
            language=settings.listam_language,
        )
    raise ValueError(f"Unknown DATA_SOURCE: {settings.data_source}")


def _apply_currency_and_price_per_sqm(listing: Listing, converter: CurrencyConverter, settings: Settings) -> None:
    if listing.original_price is not None and listing.original_currency:
        converted = converter.convert(listing.original_price, listing.original_currency, settings.base_currency)
        listing.price = converted
        listing.currency = settings.base_currency
    elif listing.original_price is not None and not listing.original_currency:
        # Ambiguous currency -- do not silently assume. Leave price unset so
        # this listing gets filtered out and flagged, per project spec.
        listing.ambiguous_fields.append("price currency unknown; not converted")

    if listing.price and listing.area_sqm:
        listing.price_per_sqm = round(listing.price / listing.area_sqm, 2)


def run_monitoring_cycle(settings: Settings, source, logger, run_index_for_mock: int = 0) -> dict:
    db = Database(settings.database_path)
    converter = CurrencyConverter(cache_hours=settings.exchange_rate_cache_hours)
    ai_analyzer = AIAnalyzer(settings)

    logger.info("Monitoring started")

    # Make sure the original operator (TELEGRAM_CHAT_ID) has a row in
    # telegram_users so they keep receiving alerts under the new multi-user
    # system -- this preserves the existing behavior of the last month
    # without requiring them to send /start themselves. No-op if already
    # registered, and never overwrites existing preferences.
    db.bootstrap_legacy_subscriber(
        settings.telegram_chat_id,
        good_enabled=settings.default_good_enabled,
        excellent_enabled=settings.default_excellent_enabled,
        exceptional_enabled=settings.default_exceptional_enabled,
    )

    # Handle any /start, /settings, /stop, /top, /today, /status, /how, /help
    # commands and inline-button taps that arrived since the last cycle.
    # Short poll only -- no long-running bot process required.
    updates_processed = process_telegram_updates(settings, db)
    if updates_processed:
        logger.info(f"Processed {updates_processed} Telegram update(s)")

    try:
        raw_listings = source.fetch_listings(settings.city, settings.property_types)
    except SourceUnavailableError as e:
        logger.error(f"Data source unavailable this run: {e}")
        return {"listings_checked": 0, "new_listings": 0, "ai_analyzed": 0, "deals_found": 0}

    logger.info(f"Retrieved {len(raw_listings)} listings")

    known_ids = db.get_known_listing_ids()
    new_listings = [l for l in raw_listings if l.listing_id not in known_ids]
    logger.info(f"{len(new_listings)} new listings")

    ai_analyzed_count = 0
    deals_found = 0

    for listing in raw_listings:
        try:
            _apply_currency_and_price_per_sqm(listing, converter, settings)
            db.upsert_listing(listing)  # store/refresh every seen listing, new or not

            if listing.listing_id not in known_ids:
                _process_new_listing(listing, settings, db, ai_analyzer, logger)
        except Exception as e:
            logger.error(f"Failed to process listing {getattr(listing, 'listing_id', '?')}: {e}")
            continue

    stats = {
        "listings_checked": len(raw_listings),
        "new_listings": len(new_listings),
        "ai_analyzed": ai_analyzed_count,
        "deals_found": deals_found,
    }
    db.record_run_stats(**stats)
    logger.info(f"Run complete: {stats}")
    return stats


def _process_new_listing(listing: Listing, settings: Settings, db: Database, ai_analyzer: AIAnalyzer, logger) -> None:
    filter_result = passes_basic_filters(listing, settings)
    if not filter_result.passed:
        logger.info(f"Listing {listing.listing_id} filtered out: {filter_result.reason}")
        return
    logger.info(f"Listing {listing.listing_id} passed initial filter")

    comparables = db.get_comparables(listing.city, listing.district, listing.property_type, exclude_id=listing.listing_id)
    market = analyze_market(listing, comparables)

    ai = AIAssessment()
    if should_trigger_ai(market.discount_percentage, settings):
        context = {
            "title": listing.title, "description": listing.description,
            "property_type": listing.property_type, "location": f"{listing.district}, {listing.city}",
            "area_sqm": listing.area_sqm, "rooms": listing.rooms, "floor": listing.floor,
            "total_floors": listing.total_floors, "building_year": listing.building_year,
            "building_type": listing.building_type, "renovation_status": listing.renovation_status,
            "asking_price": listing.price, "price_per_sqm": listing.price_per_sqm,
            "market_price_per_sqm": market.estimated_market_price_per_sqm,
            "discount_percentage": market.discount_percentage,
            "comparable_count": market.comparable_count,
        }
        ai = ai_analyzer.analyze(context)
        logger.info(f"AI analyzed listing {listing.listing_id} (used_ai={ai.used_ai})")
    else:
        logger.info(f"Listing {listing.listing_id} did not meet AI trigger threshold; skipping AI")

    score = calculate_final_score(listing, market, ai, settings)
    processed = ProcessedListing(listing=listing, market=market, ai=ai, score=score)
    db.save_analysis(processed)

    # The listing is detected, scored, and stored regardless of anyone's
    # notification preferences -- preferences only affect who gets pinged.
    sent_to_anyone = False
    if score.classification in ALERT_CLASSIFICATIONS:
        recipients = [
            user for user in db.get_active_users()
            if db.user_wants_classification(user, score.classification)
        ]
        newly_sent = 0
        for user in recipients:
            if db.was_alert_delivered(listing.listing_id, user["telegram_user_id"]):
                continue  # never re-send the same listing to the same user
            send_deal_alert(settings, processed, chat_id=user["chat_id"])
            db.record_delivery(listing.listing_id, user["telegram_user_id"], score.classification)
            sent_to_anyone = True
            newly_sent += 1
        logger.info(
            f"Listing {listing.listing_id} classified {score.classification} "
            f"(score={score.final_score}); {newly_sent} new alert(s) sent "
            f"({len(recipients)} total recipient(s) want this classification)"
        )
    else:
        logger.info(f"Listing {listing.listing_id} scored {score.final_score} ({score.classification}); no alert")

    db.mark_processed(listing.listing_id, telegram_sent=sent_to_anyone, telegram_message_id=None)


def main():
    parser = argparse.ArgumentParser(description="Armenian real-estate deal finder")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mock", action="store_true", help="Run one cycle against mock data")
    group.add_argument("--production", action="store_true", help="Run one cycle against the real data source")
    group.add_argument("--test", action="store_true", help="Run the automated test suite")
    group.add_argument("--status", action="store_true", help="Print last run stats and exit")
    group.add_argument("--commands", action="store_true", help="Process pending Telegram commands/button taps once and exit")
    parser.add_argument("--mock-run-index", type=int, default=0, help="Which batch of mock listings to reveal (demo of new-listing detection)")
    args = parser.parse_args()

    logger = setup_logging(secrets=[settings.telegram_bot_token, settings.ai_api_key])

    if args.test:
        result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v"])
        sys.exit(result.returncode)

    if args.status:
        db = Database(settings.database_path)
        stats = db.get_last_run_stats()
        print(stats or "No runs recorded yet.")
        return

    if args.commands:
        # One-shot: process whatever Telegram commands/button taps are
        # currently pending and exit. This is the same function the 5-minute
        # monitoring cycle calls automatically -- run it manually here only
        # if you want to test commands without waiting for the next cycle.
        db = Database(settings.database_path)
        count = process_telegram_updates(settings, db)
        print(f"Processed {count} Telegram update(s).")
        return

    if args.mock:
        source = get_source(settings, run_index=args.mock_run_index) if settings.data_source == "mock" else MockListingSource(run_index=args.mock_run_index)
    else:
        source = get_source(settings)

    run_monitoring_cycle(settings, source, logger, run_index_for_mock=args.mock_run_index)


if __name__ == "__main__":
    main()
