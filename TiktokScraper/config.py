# ================================================================
# BrandPulse TikTok Scraper — Configuration
# ================================================================
# All tunable settings live here. No magic numbers in scraper code.
#
# Maintenance note:
#   TikTok changes its XHR endpoint paths every 4-8 weeks.
#   Update SCRAPER_LAST_VERIFIED after each confirmed working run
#   so the team knows when maintenance is due.
# ================================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ── Chrome for Testing (CfT) ─────────────────────────────────────────────────
# Path to the CfT chrome.exe binary — same binary used by Instagram and X scrapers.
# Find your version folder inside C:\\chrome\ and update the path below.
CHROME_EXECUTABLE_PATH = r"D:\Downloads\PythonScraperPlaywright\chrome\win64-146.0.7680.72\chrome-win64\chrome.exe"

# ── Chrome Profile ───────────────────────────────────────────────────────────
# Point to your Chrome user data directory — the folder that contains "Default/"
# Same value you'd pass to Selenium's --user-data-dir argument.
#
# Common locations:
#   Windows: r"C:\Users\<YourName>\AppData\Local\Google\Chrome\User Data"
#   Or if you made a dedicated profile folder: r"C:\ChromeProfiles"
CHROME_PROFILE_PATH = r"C:\CfTInstagramProfile"
CHROME_PROFILE_DIR  = "Default"

# ── Scrape targets ───────────────────────────────────────────────────────────
TARGET_HASHTAGS = [
    "IsuzuKenya",
    "IsuzuEA",
    "IsuzuTruck",
]
 
TARGET_ACCOUNTS = [
    "isuzukenya",
]
 
# ── Volume controls ──────────────────────────────────────────────────────────
# Max videos to collect per hashtag/account
MAX_VIDEOS_PER_TARGET = 30
 
# Max top-liked comments to fetch per video
MAX_COMMENTS_PER_VIDEO = 5
 
# Minimum likes a comment must have to be included
MIN_COMMENT_LIKES = 1
 
# Set False for fast test runs (skips comment fetching entirely)
FETCH_COMMENTS = True
 
# ── Rate limiting ─────────────────────────────────────────────────────────────
# Delay between video scrapes (seconds) — randomised ±1s in scraper
DELAY_BETWEEN_VIDEOS = 3
 
# Delay between comment fetches (seconds)
DELAY_BETWEEN_COMMENTS = 2
 
# How long to wait after getting no results before retrying (seconds)
RATE_LIMIT_WAIT = 60
 
# Max retry attempts before skipping a target
MAX_RETRIES = 3
 
# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "brandpulse_output"
 
# ── Maintenance tracker ───────────────────────────────────────────────────────
# Update this date every time you confirm the scraper is working.
# If today's date is >30 days past this, the scraper may need maintenance.
SCRAPER_LAST_VERIFIED = "2026-03-21"