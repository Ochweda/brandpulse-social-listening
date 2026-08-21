"""
BrandPulse LinkedIn Scraper — Authentication
=============================================
Extracts li_at + JSESSIONID from the CfT browser profile.

Why cookies instead of Playwright automation:
    LinkedIn's Voyager API accepts plain HTTP requests authenticated
    with two cookies: li_at (auth token) and JSESSIONID (CSRF token).
    Once extracted from the live CfT session, all subsequent Voyager
    calls are pure requests — no browser overhead, no detection risk
    from automation signals.

How to set up (one-time):
    1. Open CfT manually
    2. Navigate to linkedin.com and log in
    3. That's it — session persists in the CfT profile indefinitely
       (LinkedIn sessions last 1 year unless revoked)

Cookie roles:
    li_at       — Primary auth token. Identifies the logged-in user.
    JSESSIONID  — Session ID that doubles as the CSRF token.
                  Strip surrounding quotes before use as csrf-token header.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import date
from playwright.async_api import async_playwright, Playwright

from config import (
    CHROME_EXECUTABLE_PATH, CHROME_PROFILE_PATH,
    CHROME_PROFILE_DIR, SCRAPER_LAST_VERIFIED,
)

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def check_maintenance_warning():
    """Warn if scraper hasn't been verified recently (Voyager changes every 4-8 weeks)."""
    try:
        last_verified = date.fromisoformat(SCRAPER_LAST_VERIFIED)
        days_since    = (date.today() - last_verified).days
        if days_since > 30:
            print(
                f"\n⚠️  WARNING: LinkedIn scraper last verified {days_since} days ago "
                f"({SCRAPER_LAST_VERIFIED}).\n"
                "   LinkedIn Voyager endpoints change every 4-8 weeks.\n"
                "   Check Network tab for updated endpoint paths if scraper fails.\n"
                "   Update SCRAPER_LAST_VERIFIED in config.py after confirming.\n"
            )
    except Exception:
        pass


def clean_profile_locks(profile_path: str):
    """Remove CfT lock files that prevent profile loading."""
    lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
    for lock in lock_files:
        for base in [profile_path, os.path.join(profile_path, "Default")]:
            lock_path = os.path.join(base, lock)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except Exception:
                    pass


async def get_linkedin_cookies(playwright: Playwright) -> dict | None:
    """
    Launch CfT, navigate to LinkedIn, and extract li_at + JSESSIONID.

    Returns a dict with keys: li_at, JSESSIONID, csrf_token
    Returns None if session is not active (not logged in).

    The CSRF token is the JSESSIONID value with surrounding quotes stripped —
    this is how LinkedIn's own frontend constructs it.
    """
    check_maintenance_warning()
    clean_profile_locks(CHROME_PROFILE_PATH)

    print("[Auth] Launching CfT to extract LinkedIn session cookies...")
    print(f"[Auth] Profile: {CHROME_PROFILE_PATH}")

    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_PATH,
            executable_path=CHROME_EXECUTABLE_PATH,
            headless=False,
            args=[
                f"--profile-directory={CHROME_PROFILE_DIR}",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-notifications",
            ],
            viewport={"width": 1280, "height": 900},
            user_agent=_DESKTOP_UA,
        )

        page = await context.new_page()

        print("[Auth] Navigating to LinkedIn feed...")
        await page.goto(
            "https://www.linkedin.com/feed/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        # Check if redirected to login
        if "login" in page.url or "authwall" in page.url or "signup" in page.url:
            print(
                "[Auth] ❌ LinkedIn session not active — redirected to login.\n"
                "   Open CfT manually, log into linkedin.com, then retry.\n"
            )
            await context.close()
            return None

        # Extract all LinkedIn cookies
        all_cookies = await context.cookies(["https://www.linkedin.com"])
        cookie_map  = {c["name"]: c["value"] for c in all_cookies}

        li_at      = cookie_map.get("li_at", "")
        jsessionid = cookie_map.get("JSESSIONID", "").strip('"')

        if not li_at or not jsessionid:
            print(
                "[Auth] ❌ Could not find li_at or JSESSIONID cookies.\n"
                "   Ensure you are logged into LinkedIn in CfT.\n"
            )
            await context.close()
            return None

        print("[Auth] ✅ LinkedIn session cookies extracted successfully.")
        print(f"[Auth]    li_at      : {li_at[:20]}...")
        print(f"[Auth]    JSESSIONID : {jsessionid[:20]}...")

        await context.close()

        return {
            "li_at":      li_at,
            "JSESSIONID": jsessionid,
            "csrf_token": jsessionid,   # JSESSIONID sans quotes = CSRF token
        }

    except Exception as e:
        print(f"[Auth] ❌ Failed to extract cookies: {e}")
        return None


async def verify_cookies(cookies: dict) -> bool:
    """
    Lightweight session check — confirms cookies were extracted.
    Voyager API verification removed since scraper now uses DOM scraping.
    """
    li_at      = cookies.get("li_at", "")
    jsessionid = cookies.get("JSESSIONID", "")

    if li_at and jsessionid:
        print("[Auth] ✅ Session cookies present — ready for DOM scraping")
        return True

    print("[Auth] ❌ Missing li_at or JSESSIONID cookies")
    return False

# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST
# Run: python -m ScraperCode.auth
# ──────────────────────────────────────────────────────────────────────────────

async def test_auth():
    print("=" * 60)
    print("BrandPulse LinkedIn — Auth Test")
    print("=" * 60)

    async with async_playwright() as playwright:
        cookies = await get_linkedin_cookies(playwright)
        if not cookies:
            print("\n❌ Auth test failed.")
            sys.exit(1)

        ok = await verify_cookies(cookies)
        if ok:
            print("\n✅ Auth test passed. Ready to scrape LinkedIn.\n")
        else:
            print("\n❌ Cookie verification failed. Re-login to LinkedIn in CfT.\n")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_auth())