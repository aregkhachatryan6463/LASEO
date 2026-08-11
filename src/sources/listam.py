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

# Try several browser profiles; Cloudflare is pickier from datacenter IPs (e.g. GitHub Actions).
_IMPERSONATES = (
    "chrome131",
    "chrome124",
    "chrome120",
    "chrome110",
    "safari17_0",
    "edge101",
)


class ListAmSource(ListingSource):
    name = "listam"

    def __init__(self, max_pages: int = 2, request_delay_sec: float = 0.5, language: str = "en"):
        self.max_pages = max(1, max_pages)
        self.request_delay_sec = max(0.0, request_delay_sec)
        self.language = language.strip("/") or "en"
        self._session: Optional[cf_requests.Session] = None
        self._impersonate_index = 0
        self._warmed = False

    def _get_session(self) -> cf_requests.Session:
        if self._session is None:
            profile = _IMPERSONATES[self._impersonate_index % len(_IMPERSONATES)]
            self._session = cf_requests.Session(impersonate=profile)
        return self._session

    def _rotate_session(self) -> None:
        self._impersonate_index += 1
        profile = _IMPERSONATES[self._impersonate_index % len(_IMPERSONATES)]
        logger.info(f"Rotating List.am HTTP session to impersonate={profile}")
        self._session = cf_requests.Session(impersonate=profile)
        self._warmed = False

    def _warm_session(self) -> None:
        if self._warmed:
            return
        session = self._get_session()
        try:
            session.get(f"https://www.list.am/{self.language}/", timeout=30)
            self._warmed = True
        except Exception as exc:
            logger.warning(f"List.am homepage warmup failed: {exc}")

    def _category_url(self, category_id: int, page: int) -> str:
        base = f"https://www.list.am/{self.language}/category/{category_id}"
        if page > 1:
            base = f"{base}/{page}"
        return f"{base}?{YEREVAN_QUERY}"

    def _fetch_page(self, category_id: int, page: int) -> str:
        url = self._category_url(category_id, page)
        last_error: Optional[Exception] = None

        for attempt in range(len(_IMPERSONATES)):
            if attempt:
                self._rotate_session()
            self._warm_session()
            session = self._get_session()
            try:
                response = session.get(
                    url,
                    timeout=30,
                    headers={
                        "Accept-Language": "en-US,en;q=0.9,hy;q=0.8",
                        "Referer": f"https://www.list.am/{self.language}/category/{category_id}",
                    },
                )
            except Exception as exc:
                last_error = exc
                logger.warning(f"List.am request error (attempt {attempt + 1}): {exc}")
                continue

            if response.status_code == 403 or "Just a moment" in response.text[:2000]:
                last_error = SourceUnavailableError(
                    f"List.am blocked request for {url} (HTTP {response.status_code})."
                )
                logger.warning(f"List.am Cloudflare block (attempt {attempt + 1})")
                continue

            if response.status_code != 200:
                raise SourceUnavailableError(
                    f"List.am returned HTTP {response.status_code} for {url}."
                )

            return response.text

        raise SourceUnavailableError(
            f"List.am request failed for {url} after {len(_IMPERSONATES)} attempts: {last_error}"
        )

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
