"""
List.am data source -- NOT ACTIVE.

WHY: List.am's Terms of Use (https://www.list.am/help/14) explicitly state
that users agree not to "use automated programs to gain access" to the site,
and that content on the site may not be copied, reproduced, stored
electronically, or reused for commercial or other purposes without
permission. No official public API, RSS feed, or documented endpoint for
listing data was found for List.am at the time this was written.

Because of this, this project does not scrape or otherwise programmatically
access List.am. Building that would mean ignoring List.am's explicit
restriction on automated access, which this project intentionally will not
do, regardless of framing (personal project, research, etc.).

WHAT WOULD ACTIVATE THIS INTEGRATION:
  1. A licensing agreement or partnership directly with List.am (List Group
     CJSC) that grants permission for automated/API access to listing data,
     OR
  2. List.am publishing an official public API or data feed in the future,
     OR
  3. Switching this application to a different data source that does offer
     an official API/feed (e.g. a real-estate site with a documented public
     API), and adjusting the filters/fields below to match.

If/when one of those becomes true, implement ListingSource here following
the exact same shape as MockListingSource in mock.py -- fetch_listings()
should return a List[Listing], using the same normalization helpers in
src/utils/normalization.py. No other part of the application needs to
change; main.py selects the source based on the DATA_SOURCE setting.
"""
from __future__ import annotations

from typing import List

from src.models.listing import Listing
from src.sources.base import ListingSource, SourceUnavailableError


class ListAmSource(ListingSource):
    name = "listam"

    def fetch_listings(self, city: str, property_types: List[str]) -> List[Listing]:
        raise SourceUnavailableError(
            "List.am integration is intentionally not implemented: List.am's Terms of "
            "Use (https://www.list.am/help/14) prohibit automated access and reuse of "
            "site content. See the module docstring in src/sources/listam.py for what "
            "would need to change to activate this source legitimately. "
            "Set DATA_SOURCE=mock in your .env to run the system with demo data."
        )
