"""
ListingSource: the interface every data source must implement.

This is the seam that makes the whole application swappable. Today, only
MockListingSource is implemented (see mock.py) because List.am's Terms of
Use prohibit automated access (see listam.py docstring for details and
what would be needed to activate that integration legitimately).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from src.models.listing import Listing


class ListingSource(ABC):
    """Any data source (mock, a future licensed API, another site, etc.)."""

    name: str = "base"

    @abstractmethod
    def fetch_listings(self, city: str, property_types: List[str]) -> List[Listing]:
        """
        Return a list of Listing objects currently available from this source
        for the given city and property types.

        Implementations should raise SourceUnavailableError (not crash the
        whole app) if the source cannot be reached this run.
        """
        raise NotImplementedError


class SourceUnavailableError(Exception):
    """Raised when a source cannot be reached / used this run (transient)."""
