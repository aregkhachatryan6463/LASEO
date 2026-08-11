"""
Parse List.am category-page listing cards (div.gl) into raw dicts.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

_ITEM_ID_RE = re.compile(r"/item/(\d+)")
_AT_LINE_RE = re.compile(
    r"^(?P<district>[^,]+),\s*"
    r"(?:(?P<rooms>\d+)\s*rm\.\s*,\s*)?"
    r"(?:(?P<area>[\d.,]+)\s*sq\.m\.\s*,\s*)?"
    r"(?:(?P<floor>\d+)/(?P<total_floors>\d+)\s*floor)?",
    re.IGNORECASE,
)
_AREA_IN_TEXT_RE = re.compile(r"([\d.,]+)\s*sq\.m\.", re.IGNORECASE)
_ROOMS_IN_TEXT_RE = re.compile(r"(\d+)\s*room", re.IGNORECASE)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_at_line(at_text: str) -> Dict[str, Any]:
    text = _clean_text(at_text)
    match = _AT_LINE_RE.match(text)
    if not match:
        return {"district": text.split(",")[0].strip() if text else "", "parse_note": f"unparsed at-line: {text!r}"}

    data = {k: v for k, v in match.groupdict().items() if v is not None}
    if "area" in data:
        data["area"] = data["area"].replace(",", "")
    return data


def _detect_seller_type(card_text: str) -> str:
    lowered = card_text.lower()
    if "agency" in lowered or "գործակալություն" in lowered:
        return "agent"
    return "owner"


def parse_listing_cards(html: str, property_type: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for link in soup.select("a[href*='/item/']"):
        if not link.select_one("div.p"):
            continue
        href = link.get("href", "")
        id_match = _ITEM_ID_RE.search(href)
        if not id_match:
            continue
        native_id = id_match.group(1)
        if native_id in seen_ids:
            continue
        seen_ids.add(native_id)

        price_el = link.select_one("div.p")
        title_el = link.select_one("div.l")
        at_el = link.select_one("div.at")

        price_raw = _clean_text(price_el.get_text()) if price_el else ""
        title = _clean_text(title_el.get_text()) if title_el else _clean_text(link.get_text(" ", strip=True))
        at_text = _clean_text(at_el.get_text()) if at_el else ""
        card_text = _clean_text(link.get_text(" ", strip=True))

        parsed_at = _parse_at_line(at_text) if at_text else {}
        district = parsed_at.get("district", "")
        rooms = parsed_at.get("rooms")
        area_raw = parsed_at.get("area")
        floor = parsed_at.get("floor")
        total_floors = parsed_at.get("total_floors")

        if not area_raw:
            area_match = _AREA_IN_TEXT_RE.search(title) or _AREA_IN_TEXT_RE.search(at_text)
            if area_match:
                area_raw = area_match.group(1).replace(",", "")

        if not rooms:
            rooms_match = _ROOMS_IN_TEXT_RE.search(title)
            if rooms_match:
                rooms = rooms_match.group(1)

        url = href if href.startswith("http") else f"https://www.list.am{href}"

        ambiguous = []
        if parsed_at.get("parse_note"):
            ambiguous.append(parsed_at["parse_note"])
        if not price_raw:
            ambiguous.append("price missing on card")
        if not area_raw:
            ambiguous.append("area missing on card")

        results.append(
            {
                "id": native_id,
                "url": url,
                "title": title,
                "description": title,
                "property_type": property_type,
                "transaction_type": "sale",
                "city": "Yerevan",
                "district": district,
                "neighborhood": district,
                "price_raw": price_raw,
                "area_raw": f"{area_raw} sq.m." if area_raw else None,
                "rooms": rooms,
                "floor": floor,
                "total_floors": total_floors,
                "seller_type": _detect_seller_type(card_text),
                "ambiguous": ambiguous,
                "at_line": at_text,
            }
        )

    return results


def cards_to_listings(raw_items: List[Dict[str, Any]]) -> Tuple[List[Any], int]:
    """Convert parsed card dicts to Listing objects. Returns (listings, skipped)."""
    from src.models.listing import Listing
    from src.utils.normalization import make_listing_id, parse_area_sqm, parse_int_safe, parse_price

    listings = []
    skipped = 0
    for item in raw_items:
        price, currency, price_note = parse_price(item.get("price_raw"))
        area, area_note = parse_area_sqm(item.get("area_raw"))
        ambiguous = list(item.get("ambiguous") or [])
        for note in (price_note, area_note):
            if note:
                ambiguous.append(note)

        if not price and not area:
            skipped += 1
            continue

        listings.append(
            Listing(
                listing_id=make_listing_id("listam", item.get("id"), item.get("url")),
                source="listam",
                url=item.get("url", ""),
                title=item.get("title", ""),
                description=item.get("description", ""),
                property_type=item.get("property_type", "unknown"),
                transaction_type=item.get("transaction_type", "sale"),
                city=item.get("city", ""),
                district=item.get("district", ""),
                neighborhood=item.get("neighborhood", ""),
                original_price=price,
                original_currency=currency,
                area_sqm=area,
                rooms=parse_int_safe(item.get("rooms")),
                floor=parse_int_safe(item.get("floor")),
                total_floors=parse_int_safe(item.get("total_floors")),
                seller_type=item.get("seller_type"),
                ambiguous_fields=ambiguous,
                raw_data=item,
            )
        )
    return listings, skipped
