"""
Date-scoped tweet discovery using account timelines + date filtering.
Bypasses search API (which requires elevated account permissions) entirely.
Uses USER_TWEETS endpoint which works with standard cookie auth.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Dict
from twikit import Client
from twikit.errors import TooManyRequests


def _parse_tweet_date(tweet) -> datetime:
    """Extract datetime from a twikit Tweet object."""
    try:
        raw = getattr(tweet, "created_at", None)
        if not raw:
            return datetime.min.replace(tzinfo=timezone.utc)
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S +0000 %Y")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


async def _get_user_tweets_in_range(
    client: Client,
    screen_name: str,
    date_from: datetime,
    date_to: datetime,
    max_tweets: int,
    delay: float,
) -> List[Dict]:
    """
    Scrape all tweets from an account within a date range.
    Walks backward through the timeline stopping when tweets
    fall before date_from.
    """
    print(f"\n  📋 Scraping @{screen_name} timeline...")

    # Ensure dates are timezone-aware
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    if date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)

    discovered: Dict[str, Dict] = {}
    page = 0
    consecutive_empty = 0
    stop_early = False

    try:
        user = await client.get_user_by_screen_name(screen_name)
        print(f"  ✅ Found @{screen_name}: {user.followers_count:,} followers")
    except Exception as e:
        print(f"  ❌ Could not find @{screen_name}: {e}")
        return []

    try:
        results = await user.get_tweets("Tweets", count=20)
    except Exception as e:
        print(f"  ❌ Timeline fetch failed for @{screen_name}: {e}")
        return []

    while results and not stop_early and len(discovered) < max_tweets:
        page += 1
        batch = 0

        for tweet in results:
            tweet_date = _parse_tweet_date(tweet)
            tid = str(tweet.id)

            # Too new — skip but keep paginating
            if tweet_date > date_to:
                continue

            # Too old — stop entirely
            if tweet_date < date_from:
                print(f"  ⏹️  Reached tweets before {date_from.date()}, stopping")
                stop_early = True
                break

            if tid in discovered:
                continue

            text = getattr(tweet, "full_text", None) or getattr(tweet, "text", "") or ""
            discovered[tid] = {
                "tweet_id":     tid,
                "url":          f"https://x.com/{screen_name}/status/{tid}",
                "username":     screen_name,
                "source_query": f"from:{screen_name}",
                "source_window": f"{date_from.date()}_to_{date_to.date()}",
                "tweet_date":   tweet_date.isoformat(),
            }
            batch += 1

            if len(discovered) >= max_tweets:
                break

        print(f"    Page {page}: +{batch} in range | Total: {len(discovered)}")

        if batch == 0:
            consecutive_empty += 1
            if consecutive_empty >= 3 or stop_early:
                break
        else:
            consecutive_empty = 0

        if stop_early or len(discovered) >= max_tweets:
            break

        try:
            await asyncio.sleep(delay)
            results = await results.next()
        except TooManyRequests:
            print("  ⚠️  Rate limited — waiting 60s...")
            await asyncio.sleep(60)
            results = await results.next()
        except Exception as e:
            print(f"  ⚠️  Pagination stopped: {e}")
            break

    result = list(discovered.values())
    print(f"  ✅ @{screen_name}: {len(result)} tweets in date range")
    return result


async def _get_keyword_tweets_via_hashtag_account(
    client: Client,
    keyword: str,
    date_from: datetime,
    date_to: datetime,
    max_tweets: int,
    delay: float,
) -> List[Dict]:
    """
    For keyword/hashtag queries, find accounts that commonly post them
    and scrape those timelines. This is a best-effort approach when
    search API is unavailable.
    Currently returns empty — account-based discovery is the primary method.
    Extend this if you have specific competitor handles to monitor.
    """
    print(f"  ℹ️  Keyword '{keyword}' skipped — search API unavailable.")
    print(f"     Add competitor handles to ACCOUNTS in run_x_pipeline.py")
    return []


async def discover_tweets(
    client: Client,
    keywords: List[str],
    accounts: List[str],
    date_from: datetime,
    date_to: datetime,
    window_size: str = "monthly",    # kept for API compatibility, not used
    max_tweets_per_query: int = 100,
    delay: float = 2.0,
) -> List[Dict]:
    """
    Full discovery: scrapes account timelines filtered by date range.
    Primary source: accounts list (brand + competitors).
    """
    all_discovered: Dict[str, Dict] = {}

    print(f"\n{'='*60}")
    print(f"PHASE 1: TWEET DISCOVERY (Timeline Mode)")
    print(f"  Accounts  : {accounts}")
    print(f"  Date range: {date_from.date()} → {date_to.date()}")
    print(f"{'='*60}")

    if not accounts:
        print("⚠️  No accounts configured. Add handles to ACCOUNTS in run_x_pipeline.py")
        return []

    for account in accounts:
        tweets = await _get_user_tweets_in_range(
            client=client,
            screen_name=account,
            date_from=date_from,
            date_to=date_to,
            max_tweets=max_tweets_per_query,
            delay=delay,
        )
        new = sum(1 for t in tweets if t["tweet_id"] not in all_discovered)
        for t in tweets:
            all_discovered.setdefault(t["tweet_id"], t)
        print(f"  +{new} new | Running total: {len(all_discovered)}")
        await asyncio.sleep(delay * 2)

    result = list(all_discovered.values())
    print(f"\n{'='*60}")
    print(f"DISCOVERY COMPLETE: {len(result)} unique tweets found")
    print(f"{'='*60}")
    return result