"""
Central configuration for the whole application.

Everything here is loaded from environment variables (via a .env file locally,
or GitHub Secrets / Actions "env:" in production). Nothing here should be a
secret value hard-coded in source code.
"""
import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    try:
        return float(val) if val not in (None, "") else default
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    try:
        return int(val) if val not in (None, "") else default
    except ValueError:
        return default


def _list(name: str, default: List[str]) -> List[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [item.strip().lower() for item in val.split(",") if item.strip()]


@dataclass
class Settings:
    # Telegram
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # AI
    ai_provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "none").lower())
    ai_api_key: str = field(default_factory=lambda: os.getenv("AI_API_KEY", ""))
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "gemini-1.5-flash"))
    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1"))

    # Data source
    data_source: str = field(default_factory=lambda: os.getenv("DATA_SOURCE", "mock").lower())

    # Filters
    city: str = field(default_factory=lambda: os.getenv("CITY", "Yerevan"))
    property_types: List[str] = field(default_factory=lambda: _list("PROPERTY_TYPES", ["apartment", "house"]))
    min_area_sqm: float = field(default_factory=lambda: _float("MIN_AREA_SQM", 50))
    max_price_usd: float = field(default_factory=lambda: _float("MAX_PRICE_USD", 300000))
    min_rooms: int = field(default_factory=lambda: _int("MIN_ROOMS", 2))
    min_discount_percent: float = field(default_factory=lambda: _float("MIN_DISCOUNT_PERCENT", 10))
    min_deal_score: float = field(default_factory=lambda: _float("MIN_DEAL_SCORE", 70))
    ai_trigger_discount_percent: float = field(
        default_factory=lambda: _float("AI_TRIGGER_DISCOUNT_PERCENT", 10)
    )

    # Scheduling
    check_interval_minutes: int = field(default_factory=lambda: _int("CHECK_INTERVAL_MINUTES", 5))

    # Currency
    exchange_rate_cache_hours: int = field(default_factory=lambda: _int("EXCHANGE_RATE_CACHE_HOURS", 6))
    base_currency: str = field(default_factory=lambda: os.getenv("BASE_CURRENCY", "USD"))

    # Modes
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))
    daily_summary_enabled: bool = field(default_factory=lambda: _bool("DAILY_SUMMARY_ENABLED", True))

    # Database
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/listings.db"))

    # Deal score weights (must sum to 1.0; kept configurable here rather than in .env
    # because changing scoring strategy is a code-level decision, not a runtime one).
    weight_market_discount: float = 0.40
    weight_location_quality: float = 0.15
    weight_property_characteristics: float = 0.10
    weight_condition: float = 0.10
    weight_comparable_confidence: float = 0.10
    weight_ai_assessment: float = 0.10
    weight_urgency: float = 0.05


settings = Settings()
