"""
Market analysis: estimate what a listing "should" cost based on comparable
listings, using outlier-resistant statistics (median + IQR filtering) rather
than a naive mean, so a single bizarre listing can't distort the estimate.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from src.models.listing import Listing, MarketAnalysis


def similarity_score(listing: Listing, candidate: dict) -> float:
    """
    Simple, explainable similarity score between 0 and 1 -- not machine
    learning, per project guidance to start simple.
    """
    if candidate.get("property_type") != listing.property_type:
        return 0.0  # property type must match to be a comparable at all

    score = 0.0
    weight_total = 0.0

    # Location (same district = high similarity)
    weight_total += 3
    if candidate.get("district") and candidate.get("district") == listing.district:
        score += 3

    # Area within +/-20%
    weight_total += 2
    if listing.area_sqm and candidate.get("area_sqm"):
        diff_ratio = abs(candidate["area_sqm"] - listing.area_sqm) / listing.area_sqm
        if diff_ratio <= 0.20:
            score += 2
        elif diff_ratio <= 0.35:
            score += 1

    # Rooms
    weight_total += 1.5
    if listing.rooms is not None and candidate.get("rooms") == listing.rooms:
        score += 1.5

    # Renovation
    weight_total += 1
    if candidate.get("renovation_status") and candidate.get("renovation_status") == listing.renovation_status:
        score += 1

    # Building type / age
    weight_total += 1
    if candidate.get("building_type") and candidate.get("building_type") == listing.building_type:
        score += 1

    return score / weight_total if weight_total else 0.0


def _iqr_filtered(values: List[float]) -> List[float]:
    """Remove points outside 1.5 * IQR -- classic, explainable outlier filter."""
    if len(values) < 4:
        return values
    sorted_vals = sorted(values)
    q1 = statistics.quantiles(sorted_vals, n=4)[0]
    q3 = statistics.quantiles(sorted_vals, n=4)[2]
    iqr = q3 - q1
    if iqr == 0:
        return sorted_vals
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return [v for v in sorted_vals if lower <= v <= upper]


def analyze_market(listing: Listing, comparables: List[dict], min_similarity: float = 0.4) -> MarketAnalysis:
    """
    Estimate market price/sqm for `listing` using `comparables` (list of dict
    rows as returned by Database.get_comparables).

    Method: filter comparables by similarity, then remove statistical
    outliers via IQR, then prefer median over mean (per project spec).
    """
    scored = [(c, similarity_score(listing, c)) for c in comparables]
    relevant = [c for c, s in scored if s >= min_similarity and c.get("price_per_sqm")]
    values = [c["price_per_sqm"] for c in relevant]

    filtered_values = _iqr_filtered(values)
    comparable_count = len(filtered_values)

    result = MarketAnalysis(analyzed_at=datetime.now(timezone.utc))
    result.comparable_count = comparable_count

    if comparable_count == 0:
        result.confidence = "low"
        result.method_notes = "No comparable listings available; cannot estimate market price."
        return result

    result.market_median_price_per_sqm = round(statistics.median(filtered_values), 2)
    result.market_average_price_per_sqm = round(statistics.mean(filtered_values), 2)

    # Prefer median when we have enough data (per spec); otherwise fall back to mean.
    if comparable_count >= 4:
        estimate = result.market_median_price_per_sqm
        result.method_notes = (
            f"Median of {comparable_count} comparable listings after IQR outlier filtering "
            f"(similarity >= {min_similarity})."
        )
    else:
        estimate = result.market_average_price_per_sqm
        result.method_notes = (
            f"Mean of {comparable_count} comparable listings (too few for a robust median)."
        )

    result.estimated_market_price_per_sqm = round(estimate, 2)
    if listing.area_sqm:
        result.estimated_market_price = round(estimate * listing.area_sqm, 2)

    if listing.price_per_sqm and result.estimated_market_price_per_sqm:
        discount = (
            (result.estimated_market_price_per_sqm - listing.price_per_sqm)
            / result.estimated_market_price_per_sqm
            * 100
        )
        result.discount_percentage = round(discount, 2)

    if comparable_count >= 8:
        result.confidence = "high"
    elif comparable_count >= 4:
        result.confidence = "medium"
    else:
        result.confidence = "low"

    return result


def classify_discount(discount_percentage: Optional[float]) -> str:
    if discount_percentage is None:
        return "unknown"
    if discount_percentage < 5:
        return "not_interesting"
    if discount_percentage < 10:
        return "slightly_below_market"
    if discount_percentage < 15:
        return "potential_deal"
    if discount_percentage < 20:
        return "good_deal"
    if discount_percentage < 30:
        return "excellent_deal"
    return "exceptional_investigate_carefully"
