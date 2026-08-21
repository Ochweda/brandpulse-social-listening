# ================================================================
# BrandPulse Facebook Scraper — Configuration
# ================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ── Chrome for Testing (CfT) ─────────────────────────────────────────────────
# Same CfT binary used by TikTok and Instagram scrapers.
CHROME_EXECUTABLE_PATH = r"D:\Downloads\PythonScraperPlaywright\chrome\win64-146.0.7680.72\chrome-win64\chrome.exe"

# Profile where your Facebook session lives — same CfT profile as TikTok.
CHROME_PROFILE_PATH = r"C:\CfTInstagramProfile"
CHROME_PROFILE_DIR  = "Default"

# ── Search targets ────────────────────────────────────────────────────────────
# Keywords searched on facebook.com/search/posts/?q=...
# Facebook returns posts from ANY account mentioning these terms — public posts
# from individuals, pages, and groups alike. This is what gives you brand
# sentiment across the whole platform, not just Isuzu's own page.
SEARCH_QUERIES = [
    "Isuzu Kenya",
    "Isuzu D-Max Kenya",
    "Isuzu truck Kenya",
    "IsuzuKenya",
]

# Specific page URLs to also scrape directly (the brand's own posts).
# Set to [] to skip direct page scraping.
TARGET_PAGES = [
    "https://www.facebook.com/IsuzuEastAfrica",
]

# ── Date range ────────────────────────────────────────────────────────────────
# Posts outside this window are skipped. Format: "YYYY-MM-DD"
# The scraper stops scrolling a feed once it hits posts older than DATE_FROM.
DATE_FROM = "2025-01-01"
DATE_TO   = "2026-03-22"

# ── Volume controls ───────────────────────────────────────────────────────────
# Max posts to collect per search query / per target page
MAX_POSTS_PER_TARGET = 50

# Max comments to collect per post.
# Facebook paginates comments ~20-50 per GraphQL call. The scraper keeps
# clicking "View more comments" until this limit is hit or no cursor remains.
MAX_COMMENTS_PER_POST = 1000

# ── Rate limiting ─────────────────────────────────────────────────────────────
DELAY_BETWEEN_POSTS    = 4    # seconds between post navigations
DELAY_BETWEEN_SCROLLS  = 2    # seconds between feed scrolls
DELAY_COMMENT_CLICK    = 1.5  # seconds between "View more comments" clicks
RATE_LIMIT_WAIT        = 90   # seconds to wait after a rate-limit signal
MAX_RETRIES            = 3

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "brandpulse_output"

# ── Maintenance tracker ───────────────────────────────────────────────────────
# Update this date every time you confirm the scraper is working.
SCRAPER_LAST_VERIFIED = "2026-03-22"