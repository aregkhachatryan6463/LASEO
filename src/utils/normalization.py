"""
Normalization utilities for messy real-estate listing data.

Design goal (per project spec): never silently guess when parsing is
ambiguous. Functions here return None (or raise) plus append a note to
`ambiguous` when they can't confidently parse a value, so the caller can
flag the record instead of pretending it understood it.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional, Tuple, List

# ---------------------------------------------------------------------------
# Area parsing
# ---------------------------------------------------------------------------

_AREA_UNIT_WORDS = ["քմ", "sqm", "sq.m", "sq m", "m2", "m²", "kv.m", "кв.м", "кв. м"]


def parse_area_sqm(raw: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """
    Parse a free-text area string into a float number of square meters.

    Returns (value, ambiguity_note). value is None if parsing failed.
    Handles: "75 քմ", "75 m²", "75 sqm", "75.5", "75,5 քմ"
    """
    if raw is None:
        return None, "area missing"
    text = str(raw).strip().lower()
    if not text:
        return None, "area missing"

    # Strip known unit words so we're left with just the number.
    for unit in _AREA_UNIT_WORDS:
        text = text.replace(unit, "")
    text = text.strip()

    # Handle European-style decimal commas: "75,5" -> "75.5"
    # But be careful not to mangle thousand separators like "1,200".
    # Heuristic: a comma followed by exactly 1-2 digits at the end is a decimal comma.
    match = re.match(r"^(\d+),(\d{1,2})$", text)
    if match:
        text = f"{match.group(1)}.{match.group(2)}"
    else:
        # Otherwise assume commas are thousands separators and strip them.
        text = text.replace(",", "")

    text = re.sub(r"[^\d.]", "", text)
    if not text:
        return None, f"could not parse area from raw value: {raw!r}"

    try:
        value = float(text)
    except ValueError:
        return None, f"could not parse area from raw value: {raw!r}"

    if value <= 0 or value > 100000:
        return None, f"area out of plausible range: {value}"

    return value, None


# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
    "֏": "AMD",
    "amd": "AMD",
    "dram": "AMD",
    "դր": "AMD",
}


def parse_price(raw: Optional[str]) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Parse a free-text price string into (amount, currency, ambiguity_note).

    Handles: "$120,000", "120000 USD", "120 000$", "120.000$", "120000"
    When no currency symbol/code is present, currency is returned as None and
    the caller must treat the record as ambiguous (do not assume a currency).
    """
    if raw is None:
        return None, None, "price missing"
    text = str(raw).strip().lower()
    if not text:
        return None, None, "price missing"

    currency = None
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            currency = code
            text = text.replace(symbol, "")
            break

    # Remove spaces used as thousand separators ("120 000")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", "", text)

    # Distinguish "120.000" (European thousands) from "120.5" (decimal).
    # Heuristic: if there's exactly one '.' followed by exactly 3 digits and
    # nothing after, treat it as a thousands separator.
    dot_thousands = re.match(r"^(\d{1,3})\.(\d{3})$", text)
    if dot_thousands:
        text = dot_thousands.group(1) + dot_thousands.group(2)
    else:
        # Strip commas used as thousands separators, e.g. "120,000"
        text = text.replace(",", "")

    text = re.sub(r"[^\d.]", "", text)
    if not text:
        return None, currency, f"could not parse price from raw value: {raw!r}"

    try:
        amount = float(text)
    except ValueError:
        return None, currency, f"could not parse price from raw value: {raw!r}"

    if amount <= 0:
        return None, currency, f"price out of plausible range: {amount}"

    note = None if currency else "currency not specified in source text; flagged as ambiguous"
    return amount, currency, note


# ---------------------------------------------------------------------------
# Stable listing ID
# ---------------------------------------------------------------------------

def make_listing_id(source: str, source_native_id: Optional[str], url: Optional[str]) -> str:
    """
    Produce a stable, deterministic listing ID.

    Preference order:
      1. source's own native ID if available (most stable)
      2. a hash derived from the URL (never the title alone -- titles change/repeat)
    """
    if source_native_id:
        return f"{source}:{source_native_id}"
    if url:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return f"{source}:url:{digest}"
    raise ValueError("Cannot derive a stable listing_id without a native ID or URL")


# ---------------------------------------------------------------------------
# Rooms parsing helper
# ---------------------------------------------------------------------------

def parse_int_safe(raw) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    text = re.sub(r"[^\d]", "", str(raw))
    return int(text) if text else None
