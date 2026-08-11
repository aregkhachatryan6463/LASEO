"""
Basic configurable filters applied before any expensive analysis is done.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config.settings import Settings
from src.models.listing import Listing


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""


def passes_basic_filters(listing: Listing, settings: Settings) -> FilterResult:
    if listing.property_type not in settings.property_types:
        return FilterResult(False, f"property_type '{listing.property_type}' not in configured types")

    if settings.city and listing.city.lower() != settings.city.lower():
        return FilterResult(False, f"city '{listing.city}' does not match configured city '{settings.city}'")

    if listing.price is None or listing.price <= 0:
        return FilterResult(False, "listing has no valid price")

    if listing.area_sqm is None:
        return FilterResult(False, "listing has no valid area (and no comparable-based estimate implemented yet)")

    if listing.area_sqm < settings.min_area_sqm:
        return FilterResult(False, f"area {listing.area_sqm} sqm below minimum {settings.min_area_sqm}")

    if listing.price > settings.max_price_usd:
        return FilterResult(False, f"price {listing.price} above maximum {settings.max_price_usd}")

    if listing.rooms is not None and listing.rooms < settings.min_rooms:
        return FilterResult(False, f"rooms {listing.rooms} below minimum {settings.min_rooms}")

    return FilterResult(True, "passed basic filters")


def should_trigger_ai(discount_percentage: Optional[float], settings: Settings) -> bool:
    """AI should NOT analyze every listing -- only those with a strong signal."""
    if discount_percentage is None:
        return False
    return discount_percentage >= settings.ai_trigger_discount_percent
