"""
List.am listing source.

Fetches apartment/house sale listings from list.am category pages using curl_cffi
(Chrome TLS impersonation) to work through Cloudflare protection.

Note: List.am's Terms of Use restrict automated access. This integration exists for
personal monitoring at the user's request. Prefer requesting official access when
possible (see LISTAM_ACCESS_REQUEST.md).
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from curl_cffi import requests as cf_requests

from src.models.listing import Listing
from src.sources.base import ListingSource, SourceUnavailableError
from src.sources.listam_parser import cards_to_listings, parse_listing_cards

logger = logging.getLogger(__name__)

# list.am category IDs for sale listings
CATEGORY_IDS: Dict[str, int] = {
    "apartment": 60,
    "house": 1386,
}

# n=1&gl=1 => Yerevan (city group 1)
YEREVAN_QUERY = "n=1&gl=1"


class ListAmSource(ListingSource):
    name = "listam"

    def __init__(self, max_pages: int = 2, request_delay_sec: float = 0.5, language: str = "en"):
        self.max_pages = max(1, max_pages)
        self.request_delay_sec = max(0.0, request_delay_sec)
        self.language = language.strip("/") or "en"
        self._session = cf_requests.Session(impersonate="chrome")

    def _category_url(self, category_id: int, page: int) -> str:
        base = f"https://www.list.am/{self.language}/category/{category_id}"
        if page > 1:
            base = f"{base}/{page}"
        return f"{base}?{YEREVAN_QUERY}"

    def _fetch_page(self, category_id: int, page: int) -> str:
        url = self._category_url(category_id, page)
        try:
            response = self._session.get(url, timeout=30)
        except Exception as exc:
            raise SourceUnavailableError(f"List.am request failed for {url}: {exc}") from exc

        if response.status_code != 200:
            raise SourceUnavailableError(
                f"List.am returned HTTP {response.status_code} for {url} "
                f"(Cloudflare block or temporary outage)."
            )

        if "Just a moment" in response.text[:2000]:
            raise SourceUnavailableError("List.am blocked this request (Cloudflare challenge page).")

        return response.text

    def fetch_listings(self, city: str, property_types: List[str]) -> List[Listing]:
        if city and city.lower() not in ("yerevan", "երevan", "erevan"):
            logger.warning(
                "List.am source is configured for Yerevan (n=1). "
                f"Requested city {city!r} will still return Yerevan listings."
            )

        selected_types = [pt.lower() for pt in (property_types or list(CATEGORY_IDS.keys()))]
        all_raw: List[dict] = []

        for property_type in selected_types:
            category_id = CATEGORY_IDS.get(property_type)
            if not category_id:
                logger.info(f"Skipping unsupported property type for List.am: {property_type}")
                continue

            for page in range(1, self.max_pages + 1):
                html = self._fetch_page(category_id, page)
                cards = parse_listing_cards(html, property_type=property_type)
                logger.info(
                    f"List.am category {category_id} page {page}: parsed {len(cards)} cards"
                )
                all_raw.extend(cards)
                if self.request_delay_sec:
                    time.sleep(self.request_delay_sec)

        listings, skipped = cards_to_listings(all_raw)
        if skipped:
            logger.info(f"Skipped {skipped} List.am cards missing price/area")

        if not listings and not all_raw:
            raise SourceUnavailableError("List.am returned zero parseable listings this run.")

        # Deduplicate by listing_id (apartments + houses shouldn't overlap, but be safe)
        deduped: Dict[str, Listing] = {}
        for listing in listings:
            deduped[listing.listing_id] = listing

        logger.info(f"List.am fetch complete: {len(deduped)} listings")
        return list(deduped.values())
