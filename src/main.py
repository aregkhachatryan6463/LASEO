"""
Entry point / pipeline orchestrator.

Usage:
    python -m src.main --mock          run one monitoring cycle against mock data
    python -m src.main --production    run one monitoring cycle against the real
                                        data source (DATA_SOURCE in .env)
    python -m src.main --test          run the automated test suite
    python -m src.main --status        print last run stats and exit
    python -m src.main --commands      run the interactive Telegram command bot
                                        (long-running; not for GitHub Actions)
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
from src.analysis.scoring import calculate_final_score
from src.ai.analyzer import AIAnalyzer
from src.telegram.bot import send_deal_alert, send_daily_summary
from src.utils.currency import CurrencyConverter
from src.utils.logging import setup_logging


def get_source(settings: Settings, run_index: int = 0):
    if settings.data_source == "mock":
        return MockListingSource(run_index=run_index)
    if settings.data_source == "listam":
        return ListAmSource()
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

    if score.final_score >= settings.min_deal_score and not db.was_telegram_sent(listing.listing_id):
        message_id = send_deal_alert(settings, processed)
        db.mark_processed(listing.listing_id, telegram_sent=True, telegram_message_id=message_id)
        logger.info(f"Telegram alert sent for listing {listing.listing_id} (score={score.final_score})")
    else:
        db.mark_processed(listing.listing_id, telegram_sent=False, telegram_message_id=None)


def main():
    parser = argparse.ArgumentParser(description="Armenian real-estate deal finder")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mock", action="store_true", help="Run one cycle against mock data")
    group.add_argument("--production", action="store_true", help="Run one cycle against the real data source")
    group.add_argument("--test", action="store_true", help="Run the automated test suite")
    group.add_argument("--status", action="store_true", help="Print last run stats and exit")
    group.add_argument("--commands", action="store_true", help="Run the interactive Telegram command bot")
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
        from src.telegram.bot import run_command_bot
        db = Database(settings.database_path)
        run_command_bot(settings, db)
        return

    if args.mock:
        source = get_source(settings, run_index=args.mock_run_index) if settings.data_source == "mock" else MockListingSource(run_index=args.mock_run_index)
    else:
        source = get_source(settings)

    run_monitoring_cycle(settings, source, logger, run_index_for_mock=args.mock_run_index)


if __name__ == "__main__":
    main()
