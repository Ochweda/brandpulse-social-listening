# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**BrandPulse** — a dual-platform social media scraping and NLP enrichment suite targeting Kenyan brands (primarily Isuzu Kenya). Two independent scrapers share a common enrichment pipeline.

```
PythonScraperPlaywright/
├── XScraper/          — X (Twitter) scraper using twikit (async)
└── InstagramScraper/  — Instagram scraper using Selenium + Playwright
```

---

## XScraper

### Running

All commands must be run from `XScraper/` as the working directory. Never run scripts inside `ScraperCode/` directly — they import from `config.py` which lives at the `XScraper/` root, and Python won't find it otherwise.

```bash
cd XScraper/

# Activate venv
source venv/Scripts/activate          # Git Bash
venv\Scripts\activate.bat             # CMD
venv\Scripts\Activate.ps1             # PowerShell

# Scrape (edit KEYWORDS/ACCOUNTS/DATE_FROM/DATE_TO/WINDOW_SIZE at the top
# of run_x_pipeline.py before running — there are no CLI flags)
python run_x_pipeline.py

# Run the enrichment pipeline on the scraped output
python run_full_pipeline.py brandpulse_output/brandpulse_x_TIMESTAMP.json

# Test auth module in isolation (use -m, not direct path)
python -m ScraperCode.auth
```

`run_scraper.py` (twikit-only scraping) is dead code from an earlier design and has been removed — `run_x_pipeline.py` is the real entry point.

### Architecture

```
run_x_pipeline.py           ← entry point (config edited in-file, no CLI flags)
  └── x_playwright_scraper.py   ← tweet discovery + reply collection via Playwright
  └── ScraperCode/discovery.py  ← date-windowed tweet search
  └── ScraperCode/scraper.py    ← enrich_tweet() — full tweet data assembly
        └── ScraperCode/auth.py ← twikit Client auth only (login + cookies.json cache;
                                   actual scraping goes through Playwright, not the twikit API)
  └── ScraperCode/normalizer.py ← save_to_csv() / save_to_json()
  └── run_full_pipeline.py  ← enrichment chain, run separately on the saved JSON (importable or standalone)
        ├── brandpulse_enricher.py    ← V1: product/intent/topic tags
        ├── brandpulse_enricher_2.py  ← V2: location/account/brand
        └── nlp/                      ← NLP enricher package
              ├── nlp_engine.py
              ├── brandpulse_nlp_enricher.py
              └── keyword_lexicons.py
config.py                   ← targets, credentials (reads from .env)
```

**Data flow:** `twikit` (auth only) → Playwright discovers + enriches tweets (`x_playwright_scraper.py`) → `ScraperCode/normalizer.py` maps to BrandPulse schema → JSON + CSV saved by `run_x_pipeline.py` → `run_full_pipeline.py` (run separately) → V1 enricher → V2 enricher → NLP enricher → enriched JSON + CSV output in `brandpulse_output/`

**BrandPulse schema** (the common format enrichers expect): fields are `caption`, `username`, `follower_count`, `likes_count`, `comment_texts`, `hashtags`, `mentions`, `post_url`, `platform`. The normalizer's job is to map the scraper's native field names to these.

### Auth & Sessions

- First run: logs in with credentials from `.env`, saves session to `cookies.json`
- Subsequent runs: loads `cookies.json` directly (no re-login)
- If login fails with `httpx.ConnectTimeout`: X's servers are unreachable at the network level. Set `HTTPS_PROXY=http://host:port` in `.env` to route through a proxy.

### NLP Pipeline

Hybrid design for Kenya's trilingual context:
- **English** → Google Cloud NLP API (requires `GOOGLE_APPLICATION_CREDENTIALS` env var)
- **Swahili / Sheng** → HuggingFace AfriSenti model (runs locally)
- Language detection uses `langdetect`, but skips it for X tweets since X's API pre-detects language

NLP dependencies are separate from the base scraper: `pip install langdetect transformers torch google-cloud-language`

### Environment Variables (`.env`)

```
X_USERNAME=
X_EMAIL=
X_PASSWORD=
HTTPS_PROXY=        # optional — uncomment if X is blocked
SUPABASE_URL=       # optional
SUPABASE_KEY=       # optional
GOOGLE_APPLICATION_CREDENTIALS=  # path to service account JSON for NLP
```

---

## InstagramScraper

### Running

```bash
cd InstagramScraper/

# The venv is flat (no venv/ subfolder — Lib/, Scripts/, Include/ are at root)
source Scripts/activate               # Git Bash

python run_scraper.py
python run_full_pipeline.py brandpulse_output/<file>.json
```

### Architecture

Single-file scraper (`instagram_scraper_python.py`) using Selenium with a **persistent Chrome profile** at `C:\ChromeProfiles\Default`. Log in manually in that profile once — the session persists indefinitely via the cookie store. No `.env` credentials needed for scraping.

The `HashtagDiscovery` class (`hashtag_discovery.py`) wraps `InstagramScraperEnhanced` to traverse hashtag pages and extract post data.

Geolocation uses 8 signal sources fused into a `GeoResult` confidence score.

### Dependencies

```bash
pip install -r requirements.txt
# Core: selenium, playwright, beautifulsoup4, requests, pandas, lxml
```

---

## IDE / Workspace Setup

- **Interpreter**: `XScraper/venv/Scripts/python.exe` (set via `Python: Select Interpreter`)
- **`pyrightconfig.json`** at `XScraper/` root: points Pylance at the venv
- **`.vscode/settings.json`** at workspace root: `python.analysis.extraPaths: ["./XScraper"]` — this is what allows `from config import ...` inside `ScraperCode/` to resolve in the IDE
- If `config` or `twikit` show unresolved import errors: run `Python: Restart Language Server` from the command palette
