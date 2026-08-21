"""
BrandPulse TikTok Scraper — Authentication
==========================================
Uses Playwright launch_persistent_context with the Chrome profile —
the exact same strategy as the Instagram scraper with --user-data-dir.

No TikTokApi. No msToken. No cookie extraction. No DPAPI.
Chrome opens the profile and finds TikTok already logged in.

How to set up (one-time):
    1. Open Chrome normally (not via script)
    2. Log into TikTok at tiktok.com
    3. That's it — the session is saved in your Chrome profile
"""

import asyncio
import os
import sys
from datetime import date
from playwright.async_api import async_playwright, BrowserContext, Playwright

from config import CHROME_EXECUTABLE_PATH, CHROME_PROFILE_PATH, CHROME_PROFILE_DIR, SCRAPER_LAST_VERIFIED


def clean_profile_locks(profile_path: str):
    """Remove lock files Playwright leaves behind that cause Chrome to load the wrong profile."""
    lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
    for lock in lock_files:
        for base in [profile_path, os.path.join(profile_path, "Default")]:
            lock_path = os.path.join(base, lock)
            if os.path.exists(lock_path):
                os.remove(lock_path)
                print(f"[Auth] Removed lock file: {lock_path}")


def check_maintenance_warning():
    """Warn if scraper hasn't been verified recently."""
    try:
        last_verified = date.fromisoformat(SCRAPER_LAST_VERIFIED)
        days_since = (date.today() - last_verified).days
        if days_since > 30:
            print(
                f"\n⚠️  WARNING: Scraper last verified {days_since} days ago "
                f"({SCRAPER_LAST_VERIFIED})."
            )
            print("   TikTok updates its structure every 2-4 weeks.")
            print("   Update SCRAPER_LAST_VERIFIED in config.py after confirming it works.\n")
    except Exception:
        pass


async def create_browser_context(playwright: Playwright) -> BrowserContext | None:
    """
    Launch Chrome for Testing (CfT) with the existing user profile via
    launch_persistent_context.

    Uses CfT executable directly via executable_path — the same binary
    used by the Instagram and X scrapers. This avoids the "Chrome is being
    controlled" banner conflicts that occur with the system-installed Chrome,
    and gives us a pinned, reproducible browser version.

    The profile path carries over the saved TikTok session cookies so
    TikTok sees a known, already-authenticated browser — not a cold start.
    """
    check_maintenance_warning()

    print("[Auth] Launching Chrome for Testing (CfT)...")
    print(f"[Auth] Executable:        {CHROME_EXECUTABLE_PATH}")
    print(f"[Auth] Profile path:      {CHROME_PROFILE_PATH}")
    print(f"[Auth] Profile directory: {CHROME_PROFILE_DIR}")

    clean_profile_locks(CHROME_PROFILE_PATH)

    try:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_PATH,
            executable_path=CHROME_EXECUTABLE_PATH,  # CfT binary — pinned, reproducible
            headless=False,             # Must be False — TikTok blocks headless browsers
            args=[
                f"--profile-directory={CHROME_PROFILE_DIR}",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
            ],
            viewport={"width": 1280, "height": 800},
        )
        print("[Auth] Browser launched successfully.")
        return context

    except Exception as e:
        print(f"[Auth] ❌ Failed to launch browser: {e}")

        if "user-data-dir" in str(e) or "profile" in str(e).lower():
            print(
                "\n   💡 Check that CHROME_PROFILE_PATH in config.py points to your\n"
                "   Chrome user data directory (the folder containing 'Default/').\n"
                "   Example: r\"C:\\Users\\YourName\\AppData\\Local\\Google\\Chrome\\User Data\"\n"
            )
        elif "executable" in str(e).lower() or "chrome" in str(e).lower():
            print(
                "\n   💡 CfT binary not found at CHROME_EXECUTABLE_PATH in config.py.\n"
                "   Check the path points to chrome.exe inside your chrome-win64 folder.\n"
                "   Example: r\"C:\\chrome\\win64-146.0.7680.72\\chrome-win64\\chrome.exe\"\n"
            )

        return None


async def verify_session(context: BrowserContext) -> bool:
    """
    Confirm TikTok session is active by loading the homepage.
    Returns True if logged in, False if redirected to login.
    """
    page = await context.new_page()
    try:
        print("[Auth] Verifying TikTok session...")
        await page.goto(
            "https://www.tiktok.com/",
            wait_until="domcontentloaded",
            timeout=25000,
        )
        await page.wait_for_timeout(3000)

        current_url = page.url
        if "login" in current_url or "signup" in current_url:
            print("[Auth] ❌ Session invalid — redirected to login page.")
            print(
                "   Open Chrome normally, log into tiktok.com, then retry.\n"
                "   Make sure you're using the same Chrome profile as CHROME_PROFILE_PATH."
            )
            return False

        print("[Auth] ✅ TikTok session is active.")
        return True

    except Exception as e:
        print(f"[Auth] Session verification failed: {e}")
        return False
    finally:
        await page.close()


# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST
# Run: python -m Scripts.auth
# ──────────────────────────────────────────────────────────────────────────────

async def test_auth():
    print("=" * 60)
    print("BrandPulse TikTok — Auth Test")
    print("=" * 60)

    async with async_playwright() as playwright:
        context = await create_browser_context(playwright)
        if not context:
            print("\n❌ Auth test failed — browser did not launch.")
            sys.exit(1)

        try:
            ok = await verify_session(context)
            if ok:
                print("\n✅ Auth test passed. Ready to scrape.\n")
            else:
                print("\n❌ Auth test failed — session not active.")
                sys.exit(1)
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(test_auth())