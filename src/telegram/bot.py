"""
Telegram integration.

Two responsibilities, both implemented as plain HTTP calls to the Bot API
(no long-running process needed, so this stays $0/month on GitHub Actions):

  1. send_deal_alert() / send_daily_summary() -- push a message to ONE
     specific user's chat. Called once per qualifying user from
     src/main.py's monitoring cycle.

  2. process_telegram_updates() -- a SHORT poll of getUpdates (the offset
     is stored in the `bot_state` table so it survives between runs) that
     handles incoming commands (/start, /settings, /stop, /top, /today,
     /status, /how, /help) and inline-button taps (the Good/Excellent/
     Exceptional toggles). This is called once per monitoring cycle
     (roughly every 5 minutes, same schedule as listing checks), so no
     separate always-on bot process is required.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, List

import requests

from config.settings import Settings
from src.analysis.scoring import (
    ALERT_CLASSIFICATIONS,
    classification_label,
    format_how_laseo_scores,
    why_laseo_likes,
    why_it_may_not_be_a_deal,
)
from src.models.listing import ProcessedListing
from src.utils.logging import logger

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _post(settings: Settings, method: str, payload: dict) -> Optional[dict]:
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; cannot call Telegram API")
        return None
    url = _API_BASE.format(token=settings.telegram_bot_token, method=method)
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"Telegram API call failed ({method}): {e}")
        return None


# ---------------------------------------------------------------------------
# Deal alert formatting + sending
# ---------------------------------------------------------------------------

def format_score_breakdown(processed: ProcessedListing) -> str:
    """
    Renders the ACTUAL structured score components produced by
    src/analysis/scoring.py -- this text can never drift from the real
    formula because it is generated from the same ScoreComponent objects
    used to compute processed.score.final_score.
    """
    s = processed.score
    lines = ["🧮 HOW LASEO SCORED IT", ""]
    for c in s.components:
        lines.append(f"{c.name}: {c.raw_score:.0f}/100 × {c.weight * 100:.0f}% = {c.contribution:+.1f}")
    for p in s.penalties:
        lines.append(f"{p.name} (penalty): {p.contribution:+.1f}")
    lines.append("")
    lines.append(f"FINAL: {s.final_score:.0f}/100  ({s.classification})")
    lines.append(f"Formula version: {s.formula_version}")
    return "\n".join(lines)


def format_deal_message(processed: ProcessedListing) -> str:
    l = processed.listing
    m = processed.market
    ai = processed.ai
    s = processed.score

    icon = {"EXCEPTIONAL": "🚨", "EXCELLENT": "🔥", "GOOD": "🟢", "INTERESTING": "🟡"}.get(s.classification, "🏠")
    label = classification_label(s.classification)

    lines = [f"{icon} {label} DEAL", ""]
    if l.neighborhood or l.district:
        lines.append(f"📍 {l.neighborhood or l.district}, {l.city or 'Yerevan'}")
    lines.append(f"🏠 {l.title}")

    facts = []
    if l.rooms:
        facts.append(f"{l.rooms} rooms")
    if l.area_sqm:
        facts.append(f"{l.area_sqm:.0f} m²")
    if facts:
        lines.append("📐 " + " · ".join(facts))
    if l.floor and l.total_floors:
        lines.append(f"🏢 {l.floor}/{l.total_floors}")
    if l.renovation_status:
        lines.append(f"🛠 {l.renovation_status.replace('_', ' ').title()}")

    if l.price:
        lines.append(f"\n💰 ${l.price:,.0f}")
    if l.price_per_sqm:
        lines.append(f"💵 ${l.price_per_sqm:,.0f}/m²")

    lines.append("\n━━━━━━━━━━━━━━")
    lines.append("🎯 MARKET")
    if m.estimated_market_price_per_sqm:
        lines.append(f"Estimated market price: ${m.estimated_market_price_per_sqm:,.0f}/m²")
    if m.discount_percentage is not None:
        direction = "below" if m.discount_percentage >= 0 else "above"
        lines.append(f"Estimated discount: ~{abs(m.discount_percentage):.0f}% {direction} market")
    lines.append(f"Data confidence: {m.confidence.upper()} ({m.comparable_count} comparable listing(s))")

    lines.append("\n━━━━━━━━━━━━━━")
    lines.append(f"{icon} DEAL SCORE: {s.final_score:.0f}/100")

    likes = why_laseo_likes(l, m, ai, s)
    if likes:
        lines.append("\n🧠 WHY LASEO LIKES IT")
        lines += [f"• {b}" for b in likes]

    risks = why_it_may_not_be_a_deal(l, m, ai)
    if risks:
        lines.append("\n⚠️ WHAT TO CHECK")
        lines += [f"• {b}" for b in risks]

    lines.append("\n" + format_score_breakdown(processed))

    lines.append(
        "\nEstimated market value is based on available comparable listings -- "
        "this is not a professional appraisal."
    )

    return "\n".join(lines)


def _deal_alert_keyboard(listing_url: str) -> Optional[dict]:
    if not listing_url:
        return None
    return {"inline_keyboard": [[{"text": "🔗 Open Listing", "url": listing_url}]]}


def send_deal_alert(settings: Settings, processed: ProcessedListing, chat_id: str) -> Optional[int]:
    """Send one deal alert to one specific chat_id (one recipient)."""
    text = format_deal_message(processed)
    if settings.dry_run:
        logger.info(f"[DRY RUN] Would send Telegram alert to {chat_id}:\n{text}")
        return None
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    markup = _deal_alert_keyboard(processed.listing.url)
    if markup:
        payload["reply_markup"] = markup
    result = _post(settings, "sendMessage", payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


def send_daily_summary(settings: Settings, chat_id: str, stats: dict, best_deal_text: str = "") -> None:
    text = (
        "🏠 DAILY REAL ESTATE REPORT\n\n"
        f"Listings checked: {stats.get('listings_checked', 0)}\n"
        f"New listings: {stats.get('new_listings', 0)}\n"
        f"AI analyzed: {stats.get('ai_analyzed', 0)}\n"
        f"Deals found: {stats.get('deals_found', 0)}\n"
    )
    if best_deal_text:
        text += f"\n🔥 Best opportunity:\n{best_deal_text}"
    if settings.dry_run:
        logger.info(f"[DRY RUN] Would send daily summary to {chat_id}:\n{text}")
        return
    _post(settings, "sendMessage", {"chat_id": chat_id, "text": text})


def send_plain_message(settings: Settings, chat_id, text: str, reply_markup: Optional[dict] = None) -> Optional[int]:
    if settings.dry_run:
        logger.info(f"[DRY RUN] Would send message to {chat_id}:\n{text}")
        return None
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    result = _post(settings, "sendMessage", payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


# ---------------------------------------------------------------------------
# /settings inline keyboard (per-user Good/Excellent/Exceptional toggles)
# ---------------------------------------------------------------------------

_PREF_FIELDS = [
    ("good_enabled", "toggle:good", "Good"),
    ("excellent_enabled", "toggle:excellent", "Excellent"),
    ("exceptional_enabled", "toggle:exceptional", "Exceptional"),
]
_PREF_ICONS = {"good_enabled": "🟢", "excellent_enabled": "🔵", "exceptional_enabled": "🔥"}


def format_settings_text(user: dict) -> str:
    lines = ["⚙️ YOUR ALERTS", ""]
    for field, _cb, label in _PREF_FIELDS:
        state = "ON" if user.get(field) else "OFF"
        lines.append(f"{_PREF_ICONS[field]} {label}: {state}")
    lines.append("")
    if not user.get("notifications_enabled", 1):
        lines.append("⏸ All notifications are currently paused. Send /start to resume.")
    else:
        lines.append("Tap a button below to turn a deal type on or off.")
    return "\n".join(lines)


def build_settings_keyboard(user: dict) -> dict:
    row = []
    for field, cb, label in _PREF_FIELDS:
        mark = "✅" if user.get(field) else "⬜️"
        row.append({"text": f"{mark} {_PREF_ICONS[field]} {label}", "callback_data": cb})
    return {"inline_keyboard": [[b] for b in row]}


# ---------------------------------------------------------------------------
# Short-poll command + callback-button processing
# ---------------------------------------------------------------------------

_OFFSET_KEY = "telegram_update_offset"


def _get_updates(settings: Settings, offset: Optional[int]) -> List[dict]:
    if not settings.telegram_bot_token:
        return []
    url = _API_BASE.format(token=settings.telegram_bot_token, method="getUpdates")
    params: dict = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", []) if data.get("ok") else []
    except requests.RequestException as e:
        logger.error(f"getUpdates failed: {e}")
        return []


def _answer_callback(settings: Settings, callback_query_id: str, text: str = "") -> None:
    _post(settings, "answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text, "show_alert": False})


def _edit_message(settings: Settings, chat_id, message_id, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    _post(settings, "editMessageText", payload)


def _handle_start(settings: Settings, db, user_id: int, chat_id, username, first_name) -> None:
    is_new = db.get_user(user_id) is None
    user = db.register_user(
        telegram_user_id=user_id,
        chat_id=str(chat_id),
        username=username,
        first_name=first_name,
        good_enabled=settings.default_good_enabled,
        excellent_enabled=settings.default_excellent_enabled,
        exceptional_enabled=settings.default_exceptional_enabled,
    )
    if is_new:
        welcome = (
            "👋 Welcome to LASEO!\n\n"
            "I monitor Yerevan real-estate listings and alert you when I find a genuine "
            "deal below market value. You will NOT get old listings -- only new ones from "
            "now on. Browse past deals any time with /top or /today.\n\n"
            "By default you'll receive 🔵 Excellent and 🔥 Exceptional alerts (🟢 Good is "
            "off by default since there are a lot of them). Change this any time with /settings."
        )
    else:
        welcome = "👋 Welcome back! Your alert settings were kept exactly as they were."
    send_plain_message(settings, chat_id, welcome)
    send_plain_message(settings, chat_id, format_settings_text(user), reply_markup=build_settings_keyboard(user))


def _handle_settings(settings: Settings, db, user_id: int, chat_id) -> None:
    user = db.get_user(user_id) or db.register_user(
        telegram_user_id=user_id,
        chat_id=str(chat_id),
        good_enabled=settings.default_good_enabled,
        excellent_enabled=settings.default_excellent_enabled,
        exceptional_enabled=settings.default_exceptional_enabled,
    )
    send_plain_message(settings, chat_id, format_settings_text(user), reply_markup=build_settings_keyboard(user))


def _handle_stop(settings: Settings, db, user_id: int, chat_id) -> None:
    if db.get_user(user_id):
        db.set_notifications_enabled(user_id, False)
    send_plain_message(
        settings, chat_id,
        "⏸ Notifications paused. You will not receive deal alerts until you send /start again.\n"
        "(This only affects your own alerts -- LASEO keeps monitoring for everyone else.)",
    )


def _handle_top(settings: Settings, db, chat_id, since_iso: Optional[str] = None, header: str = "🏆 TOP DEALS") -> None:
    deals = db.get_top_deals(limit=10, since_iso=since_iso, classifications=list(ALERT_CLASSIFICATIONS))
    if not deals:
        send_plain_message(settings, chat_id, "No qualifying deals found yet.")
        return
    lines = [header, ""]
    for d in deals:
        price = f"${d['price']:,.0f}" if d.get("price") else "price n/a"
        lines.append(f"{d['final_deal_score']:.0f}/100 — {d['title']} — {price}")
    send_plain_message(settings, chat_id, "\n".join(lines))


def _handle_status(settings: Settings, db, chat_id) -> None:
    stats = db.get_last_run_stats()
    if not stats:
        send_plain_message(settings, chat_id, "No monitoring runs recorded yet.")
        return
    send_plain_message(
        settings, chat_id,
        "✅ LASEO is running\n"
        f"Last check: {stats['run_at']}\n"
        f"Listings checked: {stats['listings_checked']}\n"
        f"New listings: {stats['new_listings']}\n"
        f"AI analyzed: {stats['ai_analyzed']}\n"
        f"Deals found: {stats['deals_found']}",
    )


def _handle_how(settings: Settings, chat_id) -> None:
    send_plain_message(settings, chat_id, format_how_laseo_scores(settings))


def _handle_help(settings: Settings, chat_id) -> None:
    send_plain_message(
        settings, chat_id,
        "/settings - choose which deal types you get\n"
        "/top - all-time top deals\n"
        "/today - today's deals\n"
        "/how - how LASEO scores deals\n"
        "/status - last monitoring run\n"
        "/stop - pause your alerts\n"
        "/start - resume / restart\n"
        "/help - this message",
    )


def _handle_callback(settings: Settings, db, callback_query: dict) -> None:
    cq_id = callback_query["id"]
    data = callback_query.get("data", "")
    from_user = callback_query.get("from", {})
    user_id = from_user.get("id")
    message = callback_query.get("message", {}) or {}
    chat_id = (message.get("chat", {}) or {}).get("id")
    message_id = message.get("message_id")

    field_map = {
        "toggle:good": "good_enabled",
        "toggle:excellent": "excellent_enabled",
        "toggle:exceptional": "exceptional_enabled",
    }
    field = field_map.get(data)
    if not field or user_id is None:
        _answer_callback(settings, cq_id)
        return

    user = db.get_user(user_id)
    if not user:
        _answer_callback(settings, cq_id, "Send /start first.")
        return

    new_value = not bool(user.get(field))
    user = db.update_user_pref(user_id, field, new_value)
    _answer_callback(settings, cq_id, "Updated ✅")
    if chat_id is not None and message_id is not None:
        _edit_message(settings, chat_id, message_id, format_settings_text(user), build_settings_keyboard(user))


def process_telegram_updates(settings: Settings, db) -> int:
    """
    Fetch any Telegram updates since the last stored offset, handle them,
    and advance the offset. Safe to call every ~5 minutes from the same job
    that checks listings -- no separate long-running bot process needed.
    Returns the number of updates processed (for logging).
    """
    if not settings.telegram_bot_token:
        return 0

    raw_offset = db.get_bot_state(_OFFSET_KEY)
    offset = int(raw_offset) + 1 if raw_offset else None
    updates = _get_updates(settings, offset)

    for update in updates:
        try:
            if "callback_query" in update:
                _handle_callback(settings, db, update["callback_query"])
            elif "message" in update:
                msg = update["message"]
                text = (msg.get("text") or "").strip()
                chat_id = (msg.get("chat", {}) or {}).get("id")
                from_user = msg.get("from", {}) or {}
                user_id = from_user.get("id")
                if user_id is None or chat_id is None or not text:
                    continue

                if db.get_user(user_id):
                    db.touch_user(user_id, chat_id=str(chat_id))

                command = text.split()[0].split("@")[0].lower()
                username = from_user.get("username")
                first_name = from_user.get("first_name")

                if command == "/start":
                    _handle_start(settings, db, user_id, chat_id, username, first_name)
                elif command == "/settings":
                    _handle_settings(settings, db, user_id, chat_id)
                elif command == "/stop":
                    _handle_stop(settings, db, user_id, chat_id)
                elif command in ("/top", "/deals"):
                    _handle_top(settings, db, chat_id)
                elif command == "/today":
                    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
                    _handle_top(settings, db, chat_id, since_iso=since, header="📅 TODAY'S DEALS")
                elif command == "/status":
                    _handle_status(settings, db, chat_id)
                elif command == "/how":
                    _handle_how(settings, chat_id)
                elif command == "/help":
                    _handle_help(settings, chat_id)
        except Exception as e:
            logger.error(f"Failed to process Telegram update {update.get('update_id')}: {e}")
        finally:
            db.set_bot_state(_OFFSET_KEY, str(update["update_id"]))

    return len(updates)
