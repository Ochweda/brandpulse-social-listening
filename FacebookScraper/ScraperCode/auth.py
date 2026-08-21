"""
BrandPulse Facebook Scraper — Authentication
=============================================
Launches Chrome for Testing with the existing CfT profile.
Identical pattern to TikTok and Instagram scrapers.

Your Facebook session is already saved in the CfT profile —
no login code needed. CfT opens and finds Facebook already
authenticated.

How to set up (one-time):
    1. Open CfT manually
    2. Log into facebook.com
    3. That's it — session persists in the profile
"""

import sys
import os

# Make config importable when running as standalone module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import date
from playwright.async_api import async_playwright, BrowserContext, Playwright

from config import (
    CHROME_EXECUTABLE_PATH, CHROME_PROFILE_PATH,
    CHROME_PROFILE_DIR, SCRAPER_LAST_VERIFIED,
)


def check_maintenance_warning():
    """Warn if scraper hasn't been verified recently."""
    try:
        last_verified = date.fromisoformat(SCRAPER_LAST_VERIFIED)
        days_since    = (date.today() - last_verified).days
        if days_since > 30:
            print(
                f"\n⚠️  WARNING: Scraper last verified {days_since} days ago "
                f"({SCRAPER_LAST_VERIFIED}).\n"
                "   Facebook's GraphQL schema changes every few weeks.\n"
                "   Update SCRAPER_LAST_VERIFIED in config.py after confirming it works.\n"
            )
    except Exception:
        pass


def clean_profile_locks(profile_path: str):
    """Remove Playwright lock files that prevent CfT from loading the profile."""
    lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
    for lock in lock_files:
        for base in [profile_path, os.path.join(profile_path, "Default")]:
            lock_path = os.path.join(base, lock)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                    print(f"[Auth] Removed lock file: {lock_path}")
                except Exception:
                    pass


async def create_browser_context(playwright: Playwright) -> BrowserContext | None:
    """
    Launch CfT with the existing profile via launch_persistent_context.

    Facebook is extremely sensitive to automation signals. Using the real
    CfT profile (with existing cookies, fingerprint history, and session
    tokens) is the single most important thing for avoiding detection —
    it presents as a browser Facebook has seen before.
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
            user_agent=(                                          # ← ADD THIS
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        print("[Auth] Browser launched successfully.")
        return context

    except Exception as e:
        print(f"[Auth] ❌ Failed to launch browser: {e}")
        if "executable" in str(e).lower():
            print(
                "\n   💡 CfT binary not found at CHROME_EXECUTABLE_PATH.\n"
                f"   Current value: {CHROME_EXECUTABLE_PATH}\n"
                "   Update it in config.py to match your actual CfT path.\n"
            )
        elif "user-data-dir" in str(e).lower() or "profile" in str(e).lower():
            print(
                "\n   💡 Chrome profile not found at CHROME_PROFILE_PATH.\n"
                f"   Current value: {CHROME_PROFILE_PATH}\n"
            )
        return None


async def verify_session(context: BrowserContext) -> bool:
    """
    Confirm Facebook session is active.
    Returns True if logged in (home feed visible), False if login page.
    """
    page = await context.new_page()
    try:
        print("[Auth] Verifying Facebook session...")
        await page.goto(
            "https://www.facebook.com/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(3000)

        url = page.url
        if "login" in url or "checkpoint" in url:
            print(
                "[Auth] ❌ Session invalid — redirected to login/checkpoint.\n"
                "   Open CfT manually, log into facebook.com, then retry."
            )
            return False

        print("[Auth] ✅ Facebook session is active.")
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
    print("BrandPulse Facebook — Auth Test")
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
            try:
                await context.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(test_auth())