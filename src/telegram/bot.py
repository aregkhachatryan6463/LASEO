"""
Telegram integration.

Two responsibilities:
  1. send_deal_alert() / send_daily_summary() -- used by the monitoring script
     to push messages (via plain HTTP calls to the Bot API -- simplest
     possible approach, no long-running process needed for alerts).
  2. run_command_bot() -- an optional long-running bot process implementing
     /start /help /status /top /today /settings, for when the user wants to
     query the bot interactively. This is separate from the 5-minute
     monitoring job (which just sends messages) since GitHub Actions runs
     are short-lived and can't host a long-running bot.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from config.settings import Settings
from src.models.listing import ProcessedListing
from src.utils.logging import logger

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _post(settings: Settings, method: str, payload: dict) -> Optional[dict]:
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; cannot send Telegram message")
        return None
    url = _API_BASE.format(token=settings.telegram_bot_token, method=method)
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"Telegram API call failed: {e}")
        return None


def format_deal_message(processed: ProcessedListing) -> str:
    l = processed.listing
    m = processed.market
    ai = processed.ai
    s = processed.score

    icon = {
        "EXCEPTIONAL": "🚨",
        "EXCELLENT": "🔥",
        "GOOD": "🟢",
        "INTERESTING": "🟡",
    }.get(s.classification, "🏠")

    lines = [f"{icon} {s.classification.replace('_', ' ').title()} REAL-ESTATE DEAL", ""]
    lines.append(f"🏠 {l.title}")
    if l.neighborhood or l.district:
        lines.append(f"📍 {l.neighborhood or l.district}")
    if l.area_sqm:
        lines.append(f"📐 {l.area_sqm:.0f} m²")
    if l.floor and l.total_floors:
        lines.append(f"🏢 {l.floor}/{l.total_floors} floor")
    if l.renovation_status:
        lines.append(f"🛠 {l.renovation_status.replace('_', ' ').title()}")
    if l.price:
        lines.append(f"\n💰 ${l.price:,.0f}")
    if l.price_per_sqm:
        lines.append(f"💵 ${l.price_per_sqm:,.0f}/m²")
    if m.estimated_market_price_per_sqm:
        lines.append(f"\n📊 Comparable market (confidence: {m.confidence}):\n~${m.estimated_market_price_per_sqm:,.0f}/m²")
    if m.discount_percentage is not None:
        lines.append(f"📉 Estimated discount: {m.discount_percentage:.1f}%")

    lines.append(f"\n{icon} DEAL SCORE: {s.final_score:.0f}/100")

    if ai.summary:
        lines.append(f"\n🧠 AI assessment{'  ' if ai.used_ai else ' (rule-based, no AI configured)'}:\n{ai.summary}")

    if ai.positive_factors:
        lines.append("\n✅ Positive:")
        lines += [f"• {p}" for p in ai.positive_factors]

    if ai.risk_factors:
        lines.append("\n⚠️ Risks:")
        lines += [f"• {r}" for r in ai.risk_factors]

    lines.append(
        "\nEstimated market value is based on available comparable listings and "
        f"carries {m.confidence} confidence -- this is not a professional appraisal."
    )

    if l.url:
        lines.append(f"\n🔗 <a href=\"{l.url}\">OPEN LISTING</a>")

    return "\n".join(lines)


def send_deal_alert(settings: Settings, processed: ProcessedListing) -> Optional[int]:
    text = format_deal_message(processed)
    if settings.dry_run:
        logger.info(f"[DRY RUN] Would send Telegram alert:\n{text}")
        return None
    result = _post(
        settings, "sendMessage",
        {
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
    )
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


def send_daily_summary(settings: Settings, stats: dict, best_deal_text: str = "") -> None:
    if not settings.daily_summary_enabled:
        return
    text = (
        "🏠 DAILY REAL ESTATE REPORT\n\n"
        f"Listings discovered: {stats.get('listings_checked', 0)}\n"
        f"Below market: {stats.get('new_listings', 0)}\n"
        f"AI analyzed: {stats.get('ai_analyzed', 0)}\n"
        f"Strong deals: {stats.get('deals_found', 0)}\n"
    )
    if best_deal_text:
        text += f"\n🔥 Best opportunity:\n{best_deal_text}"

    if settings.dry_run:
        logger.info(f"[DRY RUN] Would send daily summary:\n{text}")
        return
    _post(settings, "sendMessage", {"chat_id": settings.telegram_chat_id, "text": text})


def send_plain_message(settings: Settings, text: str) -> None:
    if settings.dry_run:
        logger.info(f"[DRY RUN] Would send message:\n{text}")
        return
    _post(settings, "sendMessage", {"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "HTML"})


# ---------------------------------------------------------------------------
# Interactive command bot (optional, run separately with --commands)
# ---------------------------------------------------------------------------

def run_command_bot(settings: Settings, db) -> None:
    """
    Runs a long-poll Telegram bot process implementing the interactive
    commands. This is a separate, optional entry point (python -m src.main
    --commands) since GitHub Actions is not suited to a long-running
    process -- run this on your own computer, or skip it entirely and just
    rely on the automatic deal alerts.
    """
    try:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
    except ImportError:
        logger.error("python-telegram-bot is not installed. Run: pip install python-telegram-bot")
        return

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 Welcome! I monitor Armenian real-estate listings for potential deals.\n"
            "Use /help to see available commands."
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "/status - current bot status\n"
            "/top - top 10 opportunities found so far\n"
            "/today - today's strongest deals\n"
            "/settings - current filter settings"
        )

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = db.get_last_run_stats()
        if not stats:
            await update.message.reply_text("No monitoring runs recorded yet.")
            return
        await update.message.reply_text(
            "Bot status: Running\n"
            f"Last check: {stats['run_at']}\n"
            f"Listings checked: {stats['listings_checked']}\n"
            f"New listings: {stats['new_listings']}\n"
            f"AI analyzed: {stats['ai_analyzed']}\n"
            f"Deals found: {stats['deals_found']}"
        )

    async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
        deals = db.get_top_deals(limit=10)
        if not deals:
            await update.message.reply_text("No deals recorded yet.")
            return
        lines = []
        for d in deals:
            lines.append(f"{d['final_deal_score']:.0f}/100 - {d['title']} - ${d['price']:,.0f}" if d.get('price') else d['title'])
        await update.message.reply_text("\n".join(lines))

    async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        deals = db.get_top_deals(limit=10, since_iso=since)
        if not deals:
            await update.message.reply_text("No deals found today.")
            return
        lines = [f"{d['final_deal_score']:.0f}/100 - {d['title']}" for d in deals]
        await update.message.reply_text("\n".join(lines))

    async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            f"City: {settings.city}\n"
            f"Property types: {', '.join(settings.property_types)}\n"
            f"Min area: {settings.min_area_sqm} sqm\n"
            f"Max price: ${settings.max_price_usd:,.0f}\n"
            f"Min rooms: {settings.min_rooms}\n"
            f"Min discount: {settings.min_discount_percent}%\n"
            f"Min deal score: {settings.min_deal_score}\n"
            f"Check interval: {settings.check_interval_minutes} min\n"
            "(Change these by editing .env / GitHub Secrets, not from here.)"
        )

    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("settings", settings_cmd))
    logger.info("Command bot running (polling)... Press Ctrl+C to stop.")
    app.run_polling()
