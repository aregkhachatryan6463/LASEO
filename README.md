# Armenian Real Estate Deal Finder

Monitors residential real-estate listings, estimates fair market value from comparable
listings, filters and scores potential deals, and sends the best ones to a private Telegram
bot — automatically, roughly every 5 minutes, for **$0/month**.

**New here? Start with `SETUP.md`** — it explains everything step-by-step for someone who has
never coded before, using only an iPhone and a web browser.

## Important: this currently runs on demo data, not real List.am listings

List.am's own Terms of Service prohibit automated access, and no public API/feed exists. So
this project does **not** scrape List.am. Instead:

- The full pipeline (fetch → normalize → dedupe → filter → market analysis → AI → score →
  Telegram → database) runs against a realistic mock dataset in `data/mock_data.json`.
- `src/sources/listam.py` documents exactly why, and what would need to happen to activate a
  real List.am connection legitimately.
- See `DATA_ACCESS_FINDINGS.md` for the full investigation, and `LISTAM_ACCESS_REQUEST.md` for
  a ready-to-send request asking List.am for authorized access.
- The architecture (`ListingSource` interface) is built so a real data source can be plugged
  in later without changing anything else.

## How it works

```
data source → normalize → dedupe → basic filters → market analysis
    → AI analysis (only for promising listings) → deal score → Telegram alert → database
```

- **Market analysis** (`src/analysis/market.py`): estimates fair price/m² from comparable
  listings using median + outlier filtering (IQR), not a naive average.
- **AI analysis** (`src/ai/analyzer.py`): only runs on listings already flagged as notably
  below market. Supports Google Gemini's free tier or a local Ollama model; falls back to a
  rule-based analysis (keyword-based risk detection) if no AI is configured — the app is fully
  functional either way.
- **Deal score**: 0–100, weighted combination of discount size, location, condition,
  comparable-data confidence, AI assessment, and urgency signals.
- **Database**: SQLite, committed back to the GitHub repo after each run so history survives
  between runs (GitHub Actions runners don't keep files between runs on their own).

## Running it yourself (technical summary)

```
python -m src.main --mock          # one cycle against demo data
python -m src.main --production    # one cycle against DATA_SOURCE from .env
python -m src.main --status        # print last run's stats
python -m src.main --commands      # optional long-running /status /top /today Telegram bot
```

Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` to run
locally. In production (GitHub Actions), these come from GitHub Secrets instead — see
`SETUP.md`.

## Tests

`tests/` covers price/area parsing, currency handling, market-outlier filtering, deal scoring,
AI response parsing (including malformed responses), and new-listing deduplication.
Run with `python -m src.main --test` (or `pytest tests/` directly if you have pytest
installed).

## Documents in this repo

| File | What it's for |
|---|---|
| `SETUP.md` | Step-by-step setup for non-technical users |
| `DATA_ACCESS_FINDINGS.md` | Full List.am / alternative data source investigation |
| `LISTAM_ACCESS_REQUEST.md` | Ready-to-send request for authorized List.am access |
| `USER_INPUT_REQUIRED.md` | Exactly what you need to provide, vs. what's already handled |
