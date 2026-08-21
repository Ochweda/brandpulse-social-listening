"""
Tweet enrichment + reply collection.
Mirrors instagram_scraper_python.py enrich_post() architecture.
Uses conversation_id search for replies — same principle as network interception
(pulling structured data directly, bypassing rendered DOM).
"""
import asyncio
import re
import json
from datetime import datetime
from typing import Dict, List, Optional
from twikit import Client


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_created_at(raw: str) -> Optional[str]:
    """Convert X's 'Fri Jan 01 12:00:00 +0000 2025' → ISO 8601."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%a %b %d %H:%M:%S +0000 %Y")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return raw


def _extract_hashtags(text: str) -> List[str]:
    return re.findall(r"#(\w+)", text or "")


def _engagement_rate(likes: int, replies: int, retweets: int, followers: int) -> float:
    if followers <= 0:
        return 0.0
    return round(((likes + replies + retweets) / followers) * 100, 4)


# ── Reply Collection ──────────────────────────────────────────────────────────

async def _collect_replies(
    client: Client,
    tweet_id: str,
    author_handle: str,
    limit: int,
    delay: float,
) -> List[Dict]:
    """
    Collect replies via conversation_id search.
    Equivalent to Instagram's GraphQL network interception:
    we pull structured reply data directly from the API.
    """
    print(f"\n  💬 Collecting replies (limit={limit})...")

    replies: Dict[str, Dict] = {}
    # Exclude the author's own replies to their tweet
    query = f"conversation_id:{tweet_id} -from:{author_handle}"

    try:
        results = await client.search_tweet(query, product="Latest", count=20)
    except Exception as e:
        print(f"  ⚠️  Reply search failed: {e}")
        return []

    page = 0
    consecutive_empty = 0

    while results and len(replies) < limit:
        page += 1
        batch = 0

        for reply in results:
            if len(replies) >= limit:
                break
            rid = str(reply.id)
            if rid in replies:
                continue

            text = getattr(reply, "full_text", None) or getattr(reply, "text", "") or ""
            replies[rid] = {
                "reply_id":   rid,
                "author":     reply.user.screen_name,
                "text":       text,
                "created_at": _parse_created_at(getattr(reply, "created_at", "") or ""),
                "like_count": getattr(reply, "favorite_count", 0) or 0,
                "position":   len(replies) + 1,
            }
            batch += 1

        print(f"    Page {page}: +{batch} replies | Total: {len(replies)}")

        if batch == 0:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
        else:
            consecutive_empty = 0

        if len(replies) >= limit:
            break

        try:
            await asyncio.sleep(delay)
            results = await results.next()
        except Exception:
            break

    reply_list = list(replies.values())
    print(f"  ✅ {len(reply_list)} replies collected")
    return reply_list


# ── Tweet Enrichment ──────────────────────────────────────────────────────────

async def enrich_tweet(
    client: Client,
    tweet_meta: Dict,
    reply_limit: int = 200,
    delay: float = 3.0,
) -> Dict:
    """
    Enrich a discovered tweet dict with full details + replies.
    Mirrors enrich_post() from instagram_scraper_python.py.
    """
    tweet_id = tweet_meta["tweet_id"]
    print(f"\n{'─'*55}")
    print(f"🐦 {tweet_meta['url']}")

    result = {
        # Pass-through from discovery
        "post_url":      tweet_meta["url"],
        "source_hashtag": tweet_meta.get("source_query", ""),
        "source_window":  tweet_meta.get("source_window", ""),
        # Fields matching Instagram CSV schema
        "post_date":       None,
        "username":        None,
        "author_name":     None,
        "is_verified":     None,
        "follower_count":  0,
        "post_type":       "tweet",
        "likes":           0,
        "comments":        0,
        "retweets":        0,
        "engagement_rate": 0.0,
        "location":        None,
        "location_source": None,
        "caption":         None,
        "hashtags":        [],
        "lang":            None,
        "comments_json":   "[]",
        "error":           None,
    }

    try:
        tweet = await client.get_tweet_by_id(tweet_id)

        if tweet is None:
            result["error"] = "Tweet not found (deleted or private)"
            return result

        user = tweet.user
        text = getattr(tweet, "full_text", None) or getattr(tweet, "text", "") or ""

        # Post type
        if getattr(tweet, "retweeted_tweet", None):
            result["post_type"] = "retweet"
        elif getattr(tweet, "quoted_tweet", None):
            result["post_type"] = "quote_tweet"

        # User
        result["username"]       = user.screen_name
        result["author_name"]    = getattr(user, "name", user.screen_name)
        result["is_verified"]    = bool(
            getattr(user, "verified", False) or
            getattr(user, "is_blue_verified", False)
        )
        result["follower_count"] = getattr(user, "followers_count", 0) or 0
        result["location"]       = getattr(user, "location", None) or None
        result["location_source"] = "profile" if result["location"] else None

        # Tweet
        result["post_date"]  = _parse_created_at(getattr(tweet, "created_at", "") or "")
        result["likes"]      = getattr(tweet, "favorite_count", 0) or 0
        result["comments"]   = getattr(tweet, "reply_count", 0) or 0
        result["retweets"]   = getattr(tweet, "retweet_count", 0) or 0
        result["caption"]    = text
        result["hashtags"]   = _extract_hashtags(text)
        result["lang"]       = getattr(tweet, "lang", None)

        result["engagement_rate"] = _engagement_rate(
            result["likes"], result["comments"],
            result["retweets"], result["follower_count"]
        )

        print(
            f"  👤 @{result['username']} | "
            f"❤️  {result['likes']:,} | "
            f"💬 {result['comments']:,} | "
            f"🔁 {result['retweets']:,} | "
            f"{'✅ Verified' if result['is_verified'] else ''}"
        )

        # Replies
        await asyncio.sleep(delay)
        replies = await _collect_replies(
            client=client,
            tweet_id=tweet_id,
            author_handle=result["username"],
            limit=reply_limit,
            delay=delay,
        )
        result["comments_json"] = json.dumps(replies, ensure_ascii=False)

    except Exception as e:
        result["error"] = str(e)
        print(f"  ❌ Enrichment failed: {e}")

    return result