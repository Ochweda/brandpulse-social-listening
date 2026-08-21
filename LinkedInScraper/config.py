"""
BrandPulse LinkedIn Scraper — Configuration
=============================================
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Chrome for Testing (CfT) ──────────────────────────────────────────────────
# Same CfT binary and profile used by Facebook/Instagram/TikTok scrapers.
# LinkedIn session must be active in this profile (log in once manually).
CHROME_EXECUTABLE_PATH = r"D:\Downloads\PythonScraperPlaywright\chrome\win64-146.0.7680.72\chrome-win64\chrome.exe"
CHROME_PROFILE_PATH    = r"C:\CfTInstagramProfile"
CHROME_PROFILE_DIR     = "Default"

# ── Scrape targets ────────────────────────────────────────────────────────────
# LinkedIn company universal names (the slug in the URL)
# e.g. linkedin.com/company/isuzu-east-africa → "isuzu-east-africa"
TARGET_COMPANIES = [
    "isuzu-east-africa-limited",
]

# Keyword searches — returns posts mentioning these terms across all LinkedIn
SEARCH_KEYWORDS = [
    "Isuzu Kenya",
    "Isuzu truck Kenya",
    "IsuzuKenya",
    "Isuzu East Africa",
]

# ── Date range ────────────────────────────────────────────────────────────────
DATE_FROM = "2025-01-01"
DATE_TO   = "2026-12-31"

# ── Volume controls ───────────────────────────────────────────────────────────
MAX_POSTS_PER_TARGET   = 50     # per company page or keyword search
MAX_COMMENTS_PER_POST  = 100    # LinkedIn comments are fewer than Facebook

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Scraperly: safe threshold is ~50-80 requests/day. Keep delays human-like.
DELAY_BETWEEN_REQUESTS = 3      # seconds between Voyager API calls
DELAY_BETWEEN_POSTS    = 2      # seconds between comment fetches
RATE_LIMIT_WAIT        = 60     # seconds to wait on 429 / 999 response
MAX_RETRIES            = 3

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "brandpulse_output"

# ── Maintenance tracker ───────────────────────────────────────────────────────
# Voyager endpoints update every 4-8 weeks per Scrapfly research.
# Update this after each verified working run.
SCRAPER_LAST_VERIFIED = "2026-03-26"