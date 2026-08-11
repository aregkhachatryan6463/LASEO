"""
Mock listing source.

Loads realistic-looking Armenian real-estate listings from
data/mock_data.json so the entire pipeline (normalization -> market analysis
-> scoring -> AI -> Telegram -> database) can be developed, demoed, and
tested without any real data source.

To simulate "new listings appearing over time" across monitoring runs, pass
a different `run_seed` -- the demo dataset includes a couple of listings
that only appear on later "runs" so you can watch new-listing detection work.
"""
from __future__ import annotations

import json
import os
from typing import List

from src.models.listing import Listing
from src.sources.base import ListingSource
from src.utils.normalization import parse_area_sqm, parse_price, make_listing_id, parse_int_safe

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock_data.json")


class MockListingSource(ListingSource):
    name = "mock"

    def __init__(self, path: str = None, run_index: int = 0):
        self.path = path or _DEFAULT_PATH
        self.run_index = run_index  # which "batch" of listings to reveal (0 = all base listings)

    def fetch_listings(self, city: str, property_types: List[str]) -> List[Listing]:
        with open(self.path, "r", encoding="utf-8") as f:
            raw_items = json.load(f)

        listings = []
        for item in raw_items:
            # "appears_on_run" lets the demo dataset simulate new listings showing
            # up in later monitoring cycles. Listings with no key always appear.
            appears_on_run = item.get("appears_on_run", 0)
            if appears_on_run > self.run_index:
                continue

            if property_types and item.get("property_type", "").lower() not in property_types:
                continue
            if city and item.get("city", "").lower() != city.lower():
                continue

            price, currency, price_note = parse_price(item.get("price_raw"))
            area, area_note = parse_area_sqm(item.get("area_raw"))
            ambiguous = [n for n in (price_note, area_note) if n]

            listing = Listing(
                listing_id=make_listing_id("mock", item.get("id"), item.get("url")),
                source="mock",
                url=item.get("url", ""),
                title=item.get("title", ""),
                description=item.get("description", ""),
                property_type=item.get("property_type", "unknown"),
                transaction_type=item.get("transaction_type", "sale"),
                city=item.get("city", ""),
                district=item.get("district", ""),
                neighborhood=item.get("neighborhood", ""),
                address=item.get("address"),
                original_price=price,
                original_currency=currency,
                area_sqm=area,
                rooms=parse_int_safe(item.get("rooms")),
                bedrooms=parse_int_safe(item.get("bedrooms")),
                floor=parse_int_safe(item.get("floor")),
                total_floors=parse_int_safe(item.get("total_floors")),
                building_year=parse_int_safe(item.get("building_year")),
                building_type=item.get("building_type"),
                renovation_status=item.get("renovation_status"),
                furnished=item.get("furnished"),
                seller_type=item.get("seller_type"),
                seller_name=item.get("seller_name"),
                ambiguous_fields=ambiguous,
                raw_data=item,
            )
            listings.append(listing)
        return listings
