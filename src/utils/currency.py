"""
Currency conversion with a simple on-disk cache so we don't hammer the
exchange-rate API every run (it's called at most once per
EXCHANGE_RATE_CACHE_HOURS).

Uses https://www.exchangerate-api.com's free open endpoint (no key required
for the "open" access endpoint used here: exchangerate-api.com/docs/free ).
If the request fails for any reason (offline, rate-limited, etc.) we fall
back to a small set of hard-coded approximate rates so the app keeps working
-- clearly logged as a fallback, never silently.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

import requests

from src.utils.logging import logger

_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "exchange_rate_cache.json")
_API_URL = "https://open.er-api.com/v6/latest/USD"

# Used only if the live API is unreachable. Approximate, rarely changes much.
_FALLBACK_RATES_USD_BASE = {
    "USD": 1.0,
    "EUR": 0.92,
    "AMD": 387.0,
}


class CurrencyConverter:
    def __init__(self, cache_hours: int = 6, cache_path: str = None):
        self.cache_hours = cache_hours
        self.cache_path = cache_path or _CACHE_PATH
        self._rates: Optional[Dict[str, float]] = None

    def _load_cache(self) -> Optional[Dict[str, float]]:
        if not os.path.exists(self.cache_path):
            return None
        try:
            with open(self.cache_path, "r") as f:
                data = json.load(f)
            age_hours = (time.time() - data.get("fetched_at", 0)) / 3600
            if age_hours > self.cache_hours:
                return None
            return data.get("rates")
        except (json.JSONDecodeError, OSError):
            return None

    def _save_cache(self, rates: Dict[str, float]) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump({"fetched_at": time.time(), "rates": rates}, f)
        except OSError as e:
            logger.warning(f"Could not write exchange rate cache: {e}")

    def _get_rates(self) -> Dict[str, float]:
        if self._rates:
            return self._rates

        cached = self._load_cache()
        if cached:
            self._rates = cached
            return cached

        try:
            resp = requests.get(_API_URL, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            rates = payload.get("rates")
            if not rates:
                raise ValueError("exchange rate response missing 'rates'")
            self._save_cache(rates)
            self._rates = rates
            return rates
        except Exception as e:
            logger.warning(f"Exchange rate API unavailable ({e}); using fallback rates")
            self._rates = _FALLBACK_RATES_USD_BASE
            return self._rates

    def convert(self, amount: float, from_currency: str, to_currency: str = "USD") -> Optional[float]:
        if amount is None:
            return None
        from_currency = (from_currency or "").upper()
        to_currency = to_currency.upper()
        if from_currency == to_currency:
            return amount

        rates = self._get_rates()  # rates are USD-based: 1 USD = rates[CCY]
        if from_currency not in rates or to_currency not in rates:
            logger.warning(f"Unknown currency in conversion: {from_currency} -> {to_currency}")
            return None

        amount_in_usd = amount / rates[from_currency]
        return amount_in_usd * rates[to_currency]
