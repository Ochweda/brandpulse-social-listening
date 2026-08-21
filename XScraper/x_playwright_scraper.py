"""
X (Twitter) Playwright-based scraper.
Combines Scraperly's cookie injection approach with our Instagram
network interception pattern.

Skips twikit login entirely — injects browser cookies directly
into Playwright context, then intercepts X's GraphQL search
responses before React renders them.
"""
import asyncio
import json
import re
import os
import sys
from datetime import datetime
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Page, Response

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Cookie loader ─────────────────────────────────────────────────────────────

def _load_cookies_for_playwright(cookies_path: str) -> List[Dict]:
    """
    Convert cookies.json (flat dict) → Playwright cookie format (list of dicts).
    Playwright needs: name, value, domain, path
    """
    with open(cookies_path, "r") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        # Already in Playwright/browser export format
        return raw

    # Flat dict format: {"auth_token": "xxx", "ct0": "xxx", ...}
    playwright_cookies = []
    for name, value in raw.items():
        playwright_cookies.append({
            "name":   name,
            "value":  value,
            "domain": ".twitter.com",
            "path":   "/",
        })
    # Also add for x.com domain
    for name, value in raw.items():
        playwright_cookies.append({
            "name":   name,
            "value":  value,
            "domain": ".x.com",
            "path":   "/",
        })
    return playwright_cookies


# ── GraphQL response parser ───────────────────────────────────────────────────

def _extract_tweets_from_response(data: dict) -> List[Dict]:
    tweets = []

    def _walk(obj):
        if isinstance(obj, dict):
            if obj.get("__typename") == "Tweet":
                legacy = obj.get("legacy", {})
                user_result = obj.get("core", {}).get("user_results", {}).get("result", {})
                user_legacy = user_result.get("legacy", {})
                # X stores screen_name in BOTH core and legacy depending on endpoint
                # Check core first, fall back to legacy
                user_core = user_result.get("core", {})
                screen_name = (
                    user_core.get("screen_name")
                    or user_legacy.get("screen_name")
                    or ""
                )
                display_name = (
                    user_core.get("name")
                    or user_legacy.get("name")
                    or ""
                )

                if legacy.get("full_text"):
                    tweets.append({
                        "tweet_id":         obj.get("rest_id", ""),
                        "text":             legacy.get("full_text", ""),
                        "author":           screen_name,
                        "author_name":      display_name,
                        "author_followers": user_legacy.get("followers_count", 0),
                        "is_verified":      user_result.get("is_blue_verified", False),
                        "created_at":       legacy.get("created_at", ""),
                        "likes":            legacy.get("favorite_count", 0),
                        "retweets":         legacy.get("retweet_count", 0),
                        "replies":          legacy.get("reply_count", 0),
                        "lang":             legacy.get("lang", ""),
                        "location":         user_result.get("location", {}).get("location", ""),
                        "query":            "",  # filled in by caller
                    })
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return tweets

# ── Core scraper ──────────────────────────────────────────────────────────────

async def search_tweets_playwright(
    query: str,
    cookies_path: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    max_tweets: int = 100,
    headless: bool = True,
    proxy: Optional[str] = None,
) -> List[Dict]:
    """
    Search X for tweets using Playwright + cookie injection +
    GraphQL network interception.

    No twikit login flow — uses browser session cookies directly.
    Intercepts raw GraphQL JSON before React renders it.
    """
    # Build X search URL with date operators if specified
    search_query = query
    if date_from:
        search_query += f" since:{date_from.strftime('%Y-%m-%d')}"
    if date_to:
        search_query += f" until:{date_to.strftime('%Y-%m-%d')}"

    from urllib.parse import quote
    search_url = f"https://x.com/search?q={quote(search_query)}&src=typed_query&f=live"

    print(f"\n🔍 Query: {search_query}")
    print(f"   URL: {search_url}")

    cookies = _load_cookies_for_playwright(cookies_path)
    proxy_config = {"server": proxy} if proxy else None

    all_tweets: Dict[str, Dict] = {}
    intercepted_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            proxy=proxy_config,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        # ── Inject browser cookies (Scraperly technique) ──────────────────────
        await context.add_cookies(cookies)
        print(f"   ✅ {len(cookies)} cookies injected")

        page = await context.new_page()

        # ── Intercept GraphQL responses (our Instagram technique) ─────────────
        async def on_response(response: Response):
            try:
                if "SearchTimeline" in response.url and response.status == 200:
                    data = await response.json()
                    tweets = _extract_tweets_from_response(data)
                    for t in tweets:
                        t["query"] = query  # ← stamp the search query
                        if t["tweet_id"] and t["tweet_id"] not in all_tweets:
                            all_tweets[t["tweet_id"]] = t
                    if tweets:
                        print(f"   📡 Intercepted {len(tweets)} tweets (total: {len(all_tweets)})")
            except Exception:
                pass

        page.on("response", on_response)

        # ── Navigate to search page ───────────────────────────────────────────
        try:
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"   ⚠️  Navigation warning: {e} — continuing anyway")

        await asyncio.sleep(3)

        # Check if we got redirected to login page
        if "login" in page.url:
            print("   ❌ Redirected to login — cookies may be expired")
            await browser.close()
            return []

        print(f"   ✅ Page loaded: {page.url[:80]}")

        # ── Scroll to load more results ───────────────────────────────────────
        scroll_count = 0
        max_scrolls = max(5, max_tweets // 20)
        consecutive_no_new = 0

        while len(all_tweets) < max_tweets and scroll_count < max_scrolls:
            prev_count = len(all_tweets)
            scroll_count += 1

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.5)

            new_count = len(all_tweets) - prev_count
            print(f"   📜 Scroll {scroll_count}: +{new_count} new | Total: {len(all_tweets)}")

            if new_count == 0:
                consecutive_no_new += 1
                if consecutive_no_new >= 3:
                    print("   ℹ️  No new tweets after 3 scrolls — end of results")
                    break
            else:
                consecutive_no_new = 0

        await browser.close()

    result = list(all_tweets.values())
    print(f"\n   ✅ Total collected: {len(result)} tweets")
    return result


# ── Reply collection (same pattern) ──────────────────────────────────────────

async def collect_replies_playwright(
    tweet_url: str,
    tweet_id: str,
    cookies_path: str,
    limit: int = 100,
    headless: bool = True,
) -> List[Dict]:
    """
    Collect replies to a tweet via TweetDetail GraphQL interception.
    """
    cookies = _load_cookies_for_playwright(cookies_path)
    all_replies: Dict[str, Dict] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        async def on_response(response: Response):
            try:
                if "TweetDetail" in response.url and response.status == 200:
                    data = await response.json()
                    tweets = _extract_tweets_from_response(data)
                    for t in tweets:
                        tid = t["tweet_id"]
                        # Exclude the original tweet itself
                        if tid and tid != tweet_id and tid not in all_replies:
                            all_replies[tid] = {
                                "reply_id":   tid,
                                "author":     t["author"],
                                "text":       t["text"],
                                "created_at": t["created_at"],
                                "like_count": t["likes"],
                                "position":   len(all_replies) + 1,
                            }
            except Exception:
                pass

        page.on("response", on_response)

        try:
            await page.goto(tweet_url, wait_until="networkidle", timeout=30000)
        except Exception:
            pass

        await asyncio.sleep(3)

        # Scroll to load more replies
        for _ in range(max(3, limit // 20)):
            if len(all_replies) >= limit:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

        await browser.close()

    return list(all_replies.values())[:limit]

# Standalone test
if __name__ == "__main__":
    async def _test():
        results = await search_tweets_playwright(
            query="#IsuzuKenya",
            cookies_path="../cookies.json",
            max_tweets=5,
            headless=False,
        )
        print(f"Found {len(results)} tweets")
        for t in results[:3]:
            print(f"  @{t['author']}: {t['text'][:60]}")

    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_test())
        loop.close()
    else:
        asyncio.run(_test())