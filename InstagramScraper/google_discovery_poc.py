"""
BrandPulse Google Discovery — POC
===================================
Discovers Instagram post URLs via Google search with date filtering.
No paid API key required — uses Playwright with your existing CfT setup.

Max throughput: 250 URLs per query per date window
              = 25 pages x 10 results per page
"""

import re
import time
import random
import os
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from typing import List, Dict, Tuple
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright


# ================================================================
# CHROME FOR TESTING — matches your existing setup
# ================================================================

CHROME_FOR_TESTING_EXE = (
    r"D:\Downloads\PythonScraperPlaywright"
    r"\chrome\win64-146.0.7680.72\chrome-win64\chrome.exe"
)

# IMPORTANT: Separate profile from Instagram to keep sessions clean
CHROME_GOOGLE_PROFILE = r"C:\CfTGoogleProfile"


# ================================================================
# DATE WINDOW HELPERS
# ================================================================

def monthly_windows(
    date_from: datetime, date_to: datetime
) -> List[Tuple[str, str]]:
    """
    Split a date range into monthly chunks.
    Returns list of (start, end) tuples in Google's MM/DD/YYYY format.
    """
    windows = []
    current = date_from.replace(day=1)
    while current < date_to:
        next_month = current + relativedelta(months=1)
        end = min(next_month, date_to)
        windows.append((
            current.strftime('%m/%d/%Y'),
            end.strftime('%m/%d/%Y'),
        ))
        current = next_month
    return windows


def weekly_windows(
    date_from: datetime, date_to: datetime
) -> List[Tuple[str, str]]:
    """
    Split a date range into weekly chunks.
    Use this when a hashtag has >300 posts per month.
    """
    windows = []
    current = date_from
    while current < date_to:
        end = min(current + timedelta(days=7), date_to)
        windows.append((
            current.strftime('%m/%d/%Y'),
            end.strftime('%m/%d/%Y'),
        ))
        current = end
    return windows


# ================================================================
# MAIN DISCOVERY FUNCTION
# ================================================================

def discover_instagram_posts(
    hashtag: str,
    date_from: datetime,
    date_to: datetime,
    window_size: str = 'monthly',
    max_pages_per_window: int = 25,
    headless: bool = False,
    delay_between_pages: float = 3.5,
    delay_between_queries: float = 7.0,
) -> List[Dict]:
    """
    Search Google to discover Instagram post URLs filtered by date.

    Args:
        hashtag:              e.g. 'isuzukenya' or '#isuzukenya'
        date_from:            Earliest post date to discover
        date_to:              Latest post date to discover
        window_size:          'monthly' (<300 posts/month) or 'weekly' (more)
        max_pages_per_window: Google pages per query (10 results each).
                              25 pages = up to 250 URLs per query per window.
                              Set this from run_poc_demo.py via MAX_POSTS//10
        headless:             False = visible browser (good for demos)
        delay_between_pages:  Seconds between Google page loads
        delay_between_queries: Seconds between different search queries

    Returns:
        List of dicts, each with:
        {url, shortcode, post_type, hashtag, source_query,
         source_window, google_page, discovered_at}
    """

    hashtag_clean = hashtag.lstrip('#').lower()

    # Two query variants — "#hashtag" catches tagged posts,
    # "hashtag" catches keyword mentions in captions
    query_variants = [
        f'site:instagram.com "#{hashtag_clean}"',
        f'site:instagram.com "{hashtag_clean}"',
    ]

    windows = (
        weekly_windows(date_from, date_to)
        if window_size == 'weekly'
        else monthly_windows(date_from, date_to)
    )

    total_queries = len(windows) * len(query_variants)
    max_possible = total_queries * max_pages_per_window * 10

    print(f"\n{'='*60}")
    print(f"🔍 GOOGLE DISCOVERY: #{hashtag_clean}")
    print(f"   Range:       {date_from.strftime('%d %b %Y')} → "
          f"{date_to.strftime('%d %b %Y')}")
    print(f"   Windows:     {len(windows)} {window_size}")
    print(f"   Queries:     {total_queries} total")
    print(f"   Pages/query: {max_pages_per_window} "
          f"({max_pages_per_window * 10} URLs each)")
    print(f"   Max URLs:    ~{max_possible:,} before dedup")
    print(f"{'='*60}\n")

    # shortcode → dict (auto-deduplicates across windows + queries)
    discovered: Dict[str, Dict] = {}

    os.makedirs(CHROME_GOOGLE_PROFILE, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_GOOGLE_PROFILE,
            executable_path=CHROME_FOR_TESTING_EXE,
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=ChromeWhatsNewUI",
            ],
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )

        page = (
            context.pages[0] if context.pages
            else context.new_page()
        )

        query_num = 0

        for window_start, window_end in windows:
            print(f"\n📅 Window: {window_start} → {window_end}")

            for query in query_variants:
                query_num += 1
                window_new = 0
                consecutive_empty = 0

                print(f"\n   [{query_num:02d}/{total_queries:02d}] {query}")

                for page_num in range(max_pages_per_window):
                    start_idx = page_num * 10

                    # Build Google URL with date range filter
                    # tbs=cdr:1 enables custom date range
                    # cd_min / cd_max set the boundaries
                    google_url = (
                        "https://www.google.com/search"
                        f"?q={quote_plus(query)}"
                        f"&tbs=cdr:1,cd_min:{window_start}"
                        f",cd_max:{window_end}"
                        f"&start={start_idx}"
                    )

                    try:
                        page.goto(
                            google_url,
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )

                        # Random human-like delay
                        time.sleep(
                            random.uniform(
                                delay_between_pages * 0.7,
                                delay_between_pages * 1.4,
                            )
                        )

                        # Handle consent popup (first visit only)
                        _handle_google_consent(page)

                        # Check for CAPTCHA — pause and let user solve
                        if _is_captcha(page):
                            print(
                                f"\n   ⚠️  CAPTCHA on page {page_num + 1}. "
                                "Solve it in the browser window. "
                                "Waiting up to 60 seconds..."
                            )
                            for _ in range(60):
                                time.sleep(1)
                                if not _is_captcha(page):
                                    print("   ✅ CAPTCHA resolved, continuing...")
                                    break

                        # Extract Instagram URLs from this results page
                        urls_this_page = _extract_instagram_urls(page)
                        new_this_page = 0

                        for url, shortcode, post_type in urls_this_page:
                            if shortcode not in discovered:
                                discovered[shortcode] = {
                                    'url': url,
                                    'shortcode': shortcode,
                                    'post_type': post_type,
                                    'hashtag': hashtag_clean,
                                    'source_query': query,
                                    'source_window': (
                                        f"{window_start}→{window_end}"
                                    ),
                                    'google_page': page_num + 1,
                                    'discovered_at': (
                                        datetime.now().isoformat()
                                    ),
                                }
                                new_this_page += 1
                                window_new += 1

                        total_now = len(discovered)
                        print(
                            f"      Page {page_num + 1:2d}: "
                            f"+{new_this_page:3d} new "
                            f"| running total: {total_now:5,}"
                        )

                        # Early stop: no URLs on this page
                        if len(urls_this_page) == 0:
                            consecutive_empty += 1
                            if consecutive_empty >= 2:
                                print(
                                    "      ℹ️  No results — "
                                    "end of Google index for this query"
                                )
                                break
                        # Early stop: all duplicates 3 pages in a row
                        elif new_this_page == 0:
                            consecutive_empty += 1
                            if consecutive_empty >= 3:
                                print(
                                    "      ℹ️  All duplicates — "
                                    "moving to next query"
                                )
                                break
                        else:
                            consecutive_empty = 0

                        # Check if Google explicitly says no more results
                        if _is_last_page(page):
                            print("      ℹ️  Google: no more results")
                            break

                        # Delay between pages
                        time.sleep(random.uniform(2.5, 5.5))

                    except Exception as e:
                        print(f"      ❌ Error page {page_num + 1}: {e}")
                        time.sleep(5)
                        break

                print(
                    f"   ✅ Query done: "
                    f"+{window_new} new this window"
                )

                # Delay between query variants
                if query != query_variants[-1] or window_end != windows[-1][1]:
                    time.sleep(
                        random.uniform(
                            delay_between_queries * 0.8,
                            delay_between_queries * 1.3,
                        )
                    )

        context.close()

    results = list(discovered.values())

    print(f"\n{'='*60}")
    print(f"✅ GOOGLE DISCOVERY COMPLETE")
    print(f"   Unique posts found: {len(results):,}")
    print(f"{'='*60}\n")

    return results


# ================================================================
# HELPER FUNCTIONS
# ================================================================

def _handle_google_consent(page) -> None:
    """Dismiss Google's cookie consent popup if it appears."""
    selectors = [
        'button[id="L2AGLb"]',            # "Accept all" (EN)
        'button[id="W0wltc"]',            # "Reject all"
        'button:has-text("Accept all")',
        'button:has-text("Reject all")',
        'button:has-text("I agree")',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click()
                time.sleep(1.5)
                return
        except Exception:
            pass


def _is_captcha(page) -> bool:
    """Detect if Google is showing a CAPTCHA challenge."""
    try:
        content = page.content().lower()
        signals = [
            'detected unusual traffic',
            'unusual traffic from your computer network',
            'captcha',
            'recaptcha',
            'verify you are human',
            'not a robot',
        ]
        return any(s in content for s in signals)
    except Exception:
        return False


def _is_last_page(page) -> bool:
    """Check if Google indicates there are no more results."""
    try:
        content = page.content().lower()
        end_signals = [
            'did not match any documents',
            'no results found',
            'no more results',
        ]
        return any(s in content for s in end_signals)
    except Exception:
        return False


def _extract_instagram_urls(
    page,
) -> List[Tuple[str, str, str]]:
    """
    Extract Instagram post/reel URLs from a Google results page.
    Returns list of (clean_url, shortcode, post_type) tuples.
    Deduplicates within the page.
    """
    results = []
    seen_on_page = set()

    try:
        # Pull all href values that contain instagram.com
        all_hrefs: List[str] = page.eval_on_selector_all(
            "a[href]",
            """els => els
                .map(e => e.href)
                .filter(h => h && h.includes('instagram.com'))""",
        )

        for href in all_hrefs:
            match = re.search(
                r'instagram\.com/(p|reel)/([A-Za-z0-9_-]+)',
                href,
            )
            if match:
                post_type = match.group(1)
                shortcode = match.group(2)
                if shortcode not in seen_on_page:
                    seen_on_page.add(shortcode)
                    clean_url = (
                        f"https://www.instagram.com"
                        f"/{post_type}/{shortcode}/"
                    )
                    results.append((clean_url, shortcode, post_type))

    except Exception:
        pass

    return results