"""
X (Twitter) BrandPulse Pipeline
Mirrors run_poc_demo.py structure from the Instagram pipeline exactly.

Phase 1: Discovery  — date-windowed tweet search (X native since:/until:)
Phase 2: Enrichment — full tweet data + reply collection
Phase 3: Output     — CSV + JSON matching Instagram schema
"""
import asyncio
import re
import sys



import os



import json
from datetime import datetime
from x_playwright_scraper import search_tweets_playwright, collect_replies_playwright


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ScraperCode"))

from auth import get_authenticated_client
from discovery import discover_tweets
from scraper import enrich_tweet
from normalizer import save_to_csv, save_to_json

# ─── RUN CONFIG — edit these before each run ──────────────────────────────────
CLIENT_NAME          = "isuzu_kenya_x_test"
KEYWORDS             = ["Isuzu Kenya", "#IsuzuKenya", "IsuzuKE"]
ACCOUNTS             = ["IsuzuKenya"]      # owned brand accounts
DATE_FROM            = datetime(2025, 1, 1)
DATE_TO              = datetime(2025, 3, 1)
WINDOW_SIZE          = "monthly"           # "monthly" | "weekly"
MAX_TWEETS_PER_QUERY = 50                  # per keyword × window
MAX_REPLIES          = 200                 # per tweet
ENRICHMENT_DELAY     = 4                   # seconds between enrichments (be conservative)
DISCOVERY_DELAY      = 2                   # seconds between search pages
OUTPUT_DIR           = "brandpulse_output"
# ─────────────────────────────────────────────────────────────────────────────

# Replace the discover_tweets call in main() with:
async def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{CLIENT_NAME}_{timestamp}"

    print(f"\n{'='*60}")
    print(f"  🐦 BRANDPULSE X PIPELINE (Playwright Mode)")
    print(f"  Run ID: {run_id}")
    print(f"{'='*60}\n")

    # ── Phase 1: Discovery via Playwright search ──────────────────
    print(f"\n{'='*60}")
    print(f"PHASE 1: TWEET DISCOVERY")
    print(f"{'='*60}")

    all_discovered = {}

    for keyword in KEYWORDS:
        tweets = await search_tweets_playwright(
            query=keyword,
            cookies_path="cookies.json",
            date_from=DATE_FROM,
            date_to=DATE_TO,
            max_tweets=MAX_TWEETS_PER_QUERY,
            headless=False,   # ← set True once confirmed working
        )
        for t in tweets:
            all_discovered.setdefault(t["tweet_id"], t)
        print(f"  ✅ '{keyword}': {len(tweets)} tweets | Running total: {len(all_discovered)}")
        await asyncio.sleep(DISCOVERY_DELAY)

    if not all_discovered:
        print("\n⚠️  No tweets discovered.")
        return

    discovered = list(all_discovered.values())
    save_to_json(discovered, os.path.join(OUTPUT_DIR, f"{run_id}_discovered.json"))

    # ── Phase 2: Enrich each tweet + collect replies ──────────────
    print(f"\n{'='*60}")
    print(f"PHASE 2: ENRICHMENT ({len(discovered)} tweets)")
    print(f"{'='*60}")

    enriched_tweets = []
    failed = []

    for i, tweet in enumerate(discovered, 1):
        print(f"\n[{i}/{len(discovered)}] {tweet.get('author', '')} — {tweet.get('tweet_id', '')}")

        try:

            if not tweet.get("author"):
                print(f"  ⚠️  Skipping tweet {tweet.get('tweet_id')} — no author")
                failed.append({"tweet_id": tweet.get("tweet_id"), "error": "missing author"})
                continue

            tweet_url = f"https://x.com/{tweet['author']}/status/{tweet['tweet_id']}"

            replies = await collect_replies_playwright(
                tweet_url=tweet_url,
                tweet_id=tweet["tweet_id"],
                cookies_path="cookies.json",
                limit=MAX_REPLIES,
                headless=False,
            )

            enriched = {
                "post_url":       tweet_url,
                "post_date":      tweet.get("created_at", ""),
                "username":       tweet.get("author", ""),
                "author_name":    tweet.get("author_name", ""),
                "is_verified":    tweet.get("is_verified", False),
                "follower_count": tweet.get("author_followers", 0),
                "source_hashtag": tweet.get("query", ""),
                "post_type":      "tweet",
                "likes":          tweet.get("likes", 0),
                "comments":       tweet.get("replies", 0),
                "retweets":       tweet.get("retweets", 0),
                "engagement_rate": 0.0,
                "location":       tweet.get("location", ""),
                "location_source": "profile" if tweet.get("location") else "",
                "caption":        tweet.get("text", ""),
                "hashtags":       " ".join(re.findall(r"#\w+", tweet.get("text", ""))),
                "lang":           tweet.get("lang", ""),
                "source_window":  f"{DATE_FROM.date()}_to_{DATE_TO.date()}",
                "comments_json":  json.dumps(replies, ensure_ascii=False),
            }
            enriched_tweets.append(enriched)
            print(f"  ✅ {len(replies)} replies collected")

        except Exception as e:
            failed.append({"tweet_id": tweet.get("tweet_id"), "error": str(e)})
            print(f"  ❌ Failed: {e}")

        await asyncio.sleep(ENRICHMENT_DELAY)

    # ── Phase 3: Output ───────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"PHASE 3: SAVING OUTPUT")
    print(f"{'='*60}")

    if enriched_tweets:
        save_to_csv(enriched_tweets, os.path.join(OUTPUT_DIR, f"{run_id}.csv"))
        save_to_json(enriched_tweets, os.path.join(OUTPUT_DIR, f"{run_id}.json"))

    if failed:
        save_to_json(failed, os.path.join(OUTPUT_DIR, f"{run_id}_failed.json"))

    print(f"\n{'='*60}")
    print(f"🎉 PIPELINE COMPLETE")
    print(f"   Discovered : {len(discovered)}")
    print(f"   Enriched   : {len(enriched_tweets)}")
    print(f"   Failed     : {len(failed)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
        loop.close()
    else:
        asyncio.run(main())
