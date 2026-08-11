"""
SQLite schema as plain SQL (kept simple on purpose -- no ORM, per project
guidance to avoid overengineering for a small personal project).
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    property_type TEXT,
    transaction_type TEXT,
    city TEXT,
    district TEXT,
    neighborhood TEXT,
    address TEXT,
    latitude REAL,
    longitude REAL,
    price REAL,
    currency TEXT,
    original_price REAL,
    original_currency TEXT,
    area_sqm REAL,
    price_per_sqm REAL,
    rooms INTEGER,
    bedrooms INTEGER,
    floor INTEGER,
    total_floors INTEGER,
    building_year INTEGER,
    building_type TEXT,
    renovation_status TEXT,
    furnished INTEGER,
    seller_type TEXT,
    seller_name TEXT,
    published_at TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    ambiguous_fields TEXT,
    raw_data TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_city ON listings(city);
CREATE INDEX IF NOT EXISTS idx_listings_district ON listings(district);
CREATE INDEX IF NOT EXISTS idx_listings_property_type ON listings(property_type);
CREATE INDEX IF NOT EXISTS idx_listings_price_per_sqm ON listings(price_per_sqm);

CREATE TABLE IF NOT EXISTS analysis (
    listing_id TEXT PRIMARY KEY REFERENCES listings(listing_id),
    market_average_price REAL,
    market_median_price REAL,
    comparable_count INTEGER,
    estimated_market_price REAL,
    estimated_market_price_per_sqm REAL,
    discount_percentage REAL,
    rule_score REAL,
    ai_score REAL,
    final_deal_score REAL,
    deal_classification TEXT,
    ai_summary TEXT,
    ai_positive_factors TEXT,
    ai_risk_factors TEXT,
    ai_confidence REAL,
    analyzed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_analysis_final_score ON analysis(final_deal_score);

CREATE TABLE IF NOT EXISTS processing (
    listing_id TEXT PRIMARY KEY REFERENCES listings(listing_id),
    first_processed_at TEXT,
    last_processed_at TEXT,
    telegram_sent INTEGER DEFAULT 0,
    telegram_message_id INTEGER
);

CREATE TABLE IF NOT EXISTS run_stats (
    run_at TEXT PRIMARY KEY,
    listings_checked INTEGER,
    new_listings INTEGER,
    ai_analyzed INTEGER,
    deals_found INTEGER
);
"""
