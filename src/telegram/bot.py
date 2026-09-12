"""
Telegram integration.

Two responsibilities, both implemented as plain HTTP calls to the Bot API
(no long-running process needed, so this stays $0/month on GitHub Actions):

  1. send_deal_alert() / send_daily_summary() -- push a message to ONE
     specific user's chat. Called once per qualifying user from
     src/main.py's monitoring cycle. The alert itself is kept SHORT on
     purpose (fast to skim while browsing many listings); the score math
     and "why" explanation are one tap away instead of always inline.

  2. process_telegram_updates() -- a poll of getUpdates (the offset is
     stored in the `bot_state` table so it survives between runs) that
     handles incoming commands (/start, /settings, /stop, /top, /today,
     /status, /how, /help), inline-button taps (classification toggles,
     Score Breakdown, Why This Deal, price range), and a plain-text reply
     when a user is in the middle of setting their price range. This runs
     once per monitoring cycle, so no separate always-on bot process is
     required -- but it also means replies to a button tap or a typed
     price range only appear on the NEXT scheduled run (or immediately if
     you click "Run workflow" on GitHub yourself).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import requests

from config.settings import Settings
from src.analysis.scoring import (
    ALERT_CLASSIFICATIONS,
    classification_label,
    format_how_laseo_scores,
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
# Deal alert -- kept short, with the real link inline (so Telegram shows a
# photo preview) and the deeper detail one tap away.
# ---------------------------------------------------------------------------

def format_deal_message(processed: ProcessedListing) -> str:
    l = processed.listing
    m = processed.market
    s = processed.score

    icon = {"EXCEPTIONAL": "🚨", "EXCELLENT": "🔥", "GOOD": "🟢", "INTERESTING": "🟡"}.get(s.classification, "🏠")
    label = classification_label(s.classification)

    lines = [f"{icon} {label} — {s.final_score:.0f}/100", ""]
    if l.neighborhood or l.district:
        lines.append(f"📍 {l.neighborhood or l.district}, {l.city or 'Yerevan'}")

    facts = []
    if l.rooms:
        facts.append(f"{l.rooms} rooms")
    if l.area_sqm:
        facts.append(f"{l.area_sqm:.0f} m²")
    if l.renovation_status:
        facts.append(l.renovation_status.replace("_", " ").title())
    if facts:
        lines.append("🏠 " + " · ".join(facts))

    price_line = ""
    if l.price:
        price_line = f"💰 ${l.price:,.0f}"
        if l.price_per_sqm:
            price_line += f"  (${l.price_per_sqm:,.0f}/m²)"
    if price_line:
        lines.append(price_line)

    if m.discount_percentage is not None:
        direction = "below" if m.discount_percentage >= 0 else "above"
        lines.append(f"📉 ~{abs(m.discount_percentage):.0f}% {direction} market")

    if l.url:
        # A plain URL in the message text (not just a button) is what makes
        # Telegram generate a link preview with the listing's photo.
        lines.append("")
        lines.append(l.url)

    return "\n".join(lines)


def _deal_alert_keyboard(listing_id: str, listing_url: str) -> dict:
    rows = [
        [
            {"text": "🧮 Score Breakdown", "callback_data": f"breakdown:{listing_id}"},
            {"text": "🧠 Why This Deal", "callback_data": f"why:{listing_id}"},
        ]
    ]
    if listing_url:
        rows.append([{"text": "🔗 Open Listing", "url": listing_url}])
    return {"inline_keyboard": rows}


def send_deal_alert(settings: Settings, processed: ProcessedListing, chat_id: str) -> Optional[int]:
    """Send one short deal alert to one specific chat_id (one recipient)."""
    text = format_deal_message(processed)
    if settings.dry_run:
        logger.info(f"[DRY RUN] Would send Telegram alert to {chat_id}:\n{text}")
        return None
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
        "reply_markup": _deal_alert_keyboard(processed.listing.listing_id, processed.listing.url),
    }
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
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    result = _post(settings, "sendMessage", payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


# ---------------------------------------------------------------------------
# On-demand detail: rebuilt from the DATABASE, not from the live object --
# this is what lets a button tap work even long after the alert was sent
# and the original run has ended.
# ---------------------------------------------------------------------------

def _confidence_from_comparable_count(count: int) -> str:
    """Mirrors src/analysis/market.py's thresholds exactly."""
    if count >= 8:
        return "high"
    if count >= 4:
        return "medium"
    return "low"


def format_score_breakdown_from_row(row: dict) -> str:
    breakdown = json.loads(row["score_breakdown"]) if row.get("score_breakdown") else {}
    lines = [f"🧮 HOW LASEO SCORED: {row.get('title', 'this listing')}", ""]
    for c in breakdown.get("components", []):
        lines.append(f"{c['name']}: {c['raw_score']:.0f}/100 × {c['weight'] * 100:.0f}% = {c['contribution']:+.1f}")
    for p in breakdown.get("penalties", []):
        lines.append(f"{p['name']} (penalty): {p['contribution']:+.1f}")
    lines.append("")
    lines.append(f"FINAL: {breakdown.get('final_score', row.get('final_deal_score', 0)):.0f}/100 "
                 f"({breakdown.get('classification', row.get('deal_classification', ''))})")
    if breakdown.get("formula_version"):
        lines.append(f"Formula version: {breakdown['formula_version']}")
    return "\n".join(lines)


def format_why_from_row(row: dict) -> str:
    positives = json.loads(row["ai_positive_factors"]) if row.get("ai_positive_factors") else []
    risks = json.loads(row["ai_risk_factors"]) if row.get("ai_risk_factors") else []
    comparable_count = row.get("comparable_count") or 0
    confidence = _confidence_from_comparable_count(comparable_count)

    lines = [f"🧠 WHY THIS DEAL: {row.get('title', '')}", ""]
    if row.get("discount_percentage") is not None:
        direction = "below" if row["discount_percentage"] >= 0 else "above"
        lines.append(f"• Priced ~{abs(row['discount_percentage']):.0f}% {direction} estimated market value")
    if positives:
        for p in positives:
            lines.append(f"• {p}")
    lines.append("")
    lines.append(f"Data confidence: {confidence.upper()} ({comparable_count} comparable listing(s))")
    if risks:
        lines.append("\n⚠️ WHAT TO CHECK")
        for r in risks:
            lines.append(f"• {r}")
    lines.append(
        "\nEstimated market value is based on available comparable listings -- "
        "this is not a professional appraisal."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /settings: classification toggles + price range
# ---------------------------------------------------------------------------

_PREF_FIELDS = [
    ("good_enabled", "toggle:good", "Good"),
    ("excellent_enabled", "toggle:excellent", "Excellent"),
    ("exceptional_enabled", "toggle:exceptional", "Exceptional"),
]
_PREF_ICONS = {"good_enabled": "🟢", "excellent_enabled": "🔵", "exceptional_enabled": "🔥"}


def _format_price_range(user: dict) -> str:
    lo, hi = user.get("min_price_usd"), user.get("max_price_usd")
    if lo is None and hi is None:
        return "Any price"
    if lo is not None and hi is not None:
        return f"${lo:,.0f} – ${hi:,.0f}"
    if lo is not None:
        return f"${lo:,.0f}+"
    return f"Up to ${hi:,.0f}"


def format_settings_text(user: dict) -> str:
    lines = ["⚙️ YOUR ALERTS", ""]
    for field, _cb, label in _PREF_FIELDS:
        state = "ON" if user.get(field) else "OFF"
        lines.append(f"{_PREF_ICONS[field]} {label}: {state}")
    lines.append(f"💵 Price range: {_format_price_range(user)}")
    lines.append("")
    if not user.get("notifications_enabled", 1):
        lines.append("⏸ All notifications are currently paused. Send /start to resume.")
    else:
        lines.append("Tap a button below to change it.")
    return "\n".join(lines)


def build_settings_keyboard(user: dict) -> dict:
    rows = []
    for field, cb, label in _PREF_FIELDS:
        mark = "✅" if user.get(field) else "⬜️"
        rows.append([{"text": f"{mark} {_PREF_ICONS[field]} {label}", "callback_data": cb}])
    rows.append([{"text": f"💵 Price range: {_format_price_range(user)} (tap to change)", "callback_data": "setprice"}])
    return {"inline_keyboard": rows}


_PRICE_RANGE_RE = re.compile(r"^\s*\$?([\d,]+(?:\.\d+)?)\s*(?:-|to|–)\s*\$?([\d,]+(?:\.\d+)?)\s*$", re.IGNORECASE)
_PRICE_MIN_ONLY_RE = re.compile(r"^\s*\$?([\d,]+(?:\.\d+)?)\s*\+\s*$")
_PRICE_MAX_ONLY_RE = re.compile(r"^\s*(?:up to|under|max)\s*\$?([\d,]+(?:\.\d+)?)\s*$", re.IGNORECASE)


def _parse_price_range(text: str):
    """
    Returns (min_price, max_price, error_message). On success error_message
    is None. Accepts: "50000-150000", "50000 to 150000", "100000+",
    "under 200000", and "any"/"clear"/"no limit" to remove the filter.
    """
    text = text.strip()
    if text.lower() in ("any", "clear", "no limit", "none", "reset"):
        return None, None, None

    m = _PRICE_RANGE_RE.match(text)
    if m:
        lo = float(m.group(1).replace(",", ""))
        hi = float(m.group(2).replace(",", ""))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi, None

    m = _PRICE_MIN_ONLY_RE.match(text)
    if m:
        return float(m.group(1).replace(",", "")), None, None

    m = _PRICE_MAX_ONLY_RE.match(text)
    if m:
        return None, float(m.group(1).replace(",", "")), None

    return None, None, (
        "I didn't understand that. Reply with a range like 50000-150000, "
        "or \"under 200000\", or \"any\" to remove the price filter."
    )


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
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
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
    db.set_pending_input(user_id, None)  # cancel any half-finished price-range prompt
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
        "/settings - choose which deal types you get, and your price range\n"
        "/top - all-time top deals\n"
        "/today - today's deals\n"
        "/how - how LASEO scores deals\n"
        "/status - last monitoring run\n"
        "/stop - pause your alerts\n"
        "/start - resume / restart\n"
        "/help - this message\n\n"
        "Tip: I only check Telegram once per scheduled run, so a button tap or a typed "
        "reply may take until the next run to show up -- or trigger it immediately "
        "yourself from GitHub's Actions tab with \"Run workflow\".",
    )


def _handle_setprice_prompt(settings: Settings, db, user_id: int, chat_id) -> None:
    db.set_pending_input(user_id, "price_range")
    send_plain_message(
        settings, chat_id,
        "💵 What price range should I alert you for?\n\n"
        "Reply with something like:\n"
        "50000-150000\n"
        "under 200000\n"
        "100000+\n\n"
        "Or reply \"any\" to remove the price filter.",
    )


def _handle_price_reply(settings: Settings, db, user_id: int, chat_id, text: str) -> None:
    lo, hi, error = _parse_price_range(text)
    if error:
        send_plain_message(settings, chat_id, error)
        return
    user = db.set_price_range(user_id, lo, hi)
    send_plain_message(settings, chat_id, f"✅ Price range set to: {_format_price_range(user)}")
    send_plain_message(settings, chat_id, format_settings_text(user), reply_markup=build_settings_keyboard(user))


def _handle_callback(settings: Settings, db, callback_query: dict) -> None:
    cq_id = callback_query["id"]
    data = callback_query.get("data", "")
    from_user = callback_query.get("from", {})
    user_id = from_user.get("id")
    message = callback_query.get("message", {}) or {}
    chat_id = (message.get("chat", {}) or {}).get("id")
    message_id = message.get("message_id")

    if user_id is None:
        _answer_callback(settings, cq_id)
        return

    if data.startswith("breakdown:"):
        listing_id = data.split(":", 1)[1]
        row = db.get_listing_analysis_row(listing_id)
        _answer_callback(settings, cq_id)
        if row:
            send_plain_message(settings, chat_id, format_score_breakdown_from_row(row))
        else:
            send_plain_message(settings, chat_id, "Sorry, I couldn't find that listing's details anymore.")
        return

    if data.startswith("why:"):
        listing_id = data.split(":", 1)[1]
        row = db.get_listing_analysis_row(listing_id)
        _answer_callback(settings, cq_id)
        if row:
            send_plain_message(settings, chat_id, format_why_from_row(row))
        else:
            send_plain_message(settings, chat_id, "Sorry, I couldn't find that listing's details anymore.")
        return

    if data == "setprice":
        _answer_callback(settings, cq_id)
        _handle_setprice_prompt(settings, db, user_id, chat_id)
        return

    field_map = {
        "toggle:good": "good_enabled",
        "toggle:excellent": "excellent_enabled",
        "toggle:exceptional": "exceptional_enabled",
    }
    field = field_map.get(data)
    if not field:
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
    and advance the offset. Returns the number of updates processed.
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

                is_command = text.startswith("/")
                command = text.split()[0].split("@")[0].lower() if is_command else ""
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
                elif not is_command:
                    user = db.get_user(user_id)
                    if user and user.get("pending_input") == "price_range":
                        _handle_price_reply(settings, db, user_id, chat_id, text)
                    # Otherwise: plain chit-chat with no pending question -- ignore quietly.
        except Exception as e:
            logger.error(f"Failed to process Telegram update {update.get('update_id')}: {e}")
        finally:
            db.set_bot_state(_OFFSET_KEY, str(update["update_id"]))

    return len(updates)
