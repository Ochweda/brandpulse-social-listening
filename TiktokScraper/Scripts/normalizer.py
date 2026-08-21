"""
BrandPulse TikTok Scraper — Normalizer
=======================================
Converts raw TikTok video dicts (from scraper.py) into the standard
BrandPulse schema — the same schema used by Instagram and X/Twitter.

Why a separate normalizer?
    The enrichers (brandpulse_enricher.py, brandpulse_enricher_2.py)
    are platform-agnostic and expect BrandPulse schema.
    Normalizing here means the enrichers work unchanged across all platforms.

Raw TikTok dict fields (from XHR interception in scraper.py):
    id                    — video ID string
    desc                  — caption / description
    createTime            — unix timestamp (int)
    author.uniqueId       — @handle
    author.nickname       — display name
    author.followerCount  — follower count
    author.verified       — bool
    stats.diggCount       — likes
    stats.commentCount    — comment count
    stats.shareCount      — shares
    stats.playCount       — views
    music.title           — background music title
    music.authorName      — music author
    source                — "hashtag_search" | "account_scrape"
    query                 — hashtag or account username used
    scraped_at            — ISO 8601 string
    comments_data         — list of {author, text, likes}

BrandPulse schema (post object):
    platform          — "tiktok"
    post_id           — video ID
    post_url          — full tiktok.com URL
    source_type       — "hashtag_search" | "account_scrape"
    query             — hashtag or account that sourced this video
    author_username   — @handle (uniqueId)
    author_name       — display name (nickname)
    author_followers  — follower count
    author_verified   — True/False
    text              — caption/description
    timestamp         — ISO 8601 string (converted from unix)
    language          — "" (TikTok XHR doesn't return lang — NLP fills this)
    hashtags          — list extracted from desc (strings without #)
    mentions          — list of @handles extracted from desc
    music_title       — background audio title
    music_author      — background audio author
    engagement:
        likes
        comments      — total comment count (from stats)
        shares
        views
        total         — likes + comments + shares
    top_comments      — list of {author, text, likes} from comments_data
    scraped_at        — ISO 8601 string
"""

import re
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _unix_to_iso(unix_ts) -> str:
    """Convert a unix timestamp (int or float) to ISO 8601 string."""
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _extract_hashtags(text: str) -> list[str]:
    """Pull hashtag strings (without #) from a caption."""
    return [tag.lower() for tag in re.findall(r"#(\w+)", text)]


def _extract_mentions(text: str) -> list[str]:
    """Pull @handle strings (without @) from a caption."""
    return [m.lower() for m in re.findall(r"@(\w+)", text)]


# ──────────────────────────────────────────────────────────────────────────────
# SINGLE POST NORMALIZER
# ──────────────────────────────────────────────────────────────────────────────

def normalize_post(raw: dict) -> dict | None:
    """
    Normalize a single raw TikTok video dict to BrandPulse schema.
    Returns None if the video is missing required fields (id, desc).
    """
    post_id = str(raw.get("id", "")).strip()
    desc    = str(raw.get("desc", "")).strip()

    # Allow posts with empty captions — TikTok often has blank desc
    # Only hard-skip if there is no video ID at all
    if not post_id:
        return None

    # ── Author ────────────────────────────────────────────────────
    author = raw.get("author", {})
    if isinstance(author, str):
        # Rare case: XHR returns author as a plain string (uniqueId only)
        author = {"uniqueId": author, "nickname": author}

    username  = author.get("uniqueId", "")
    nickname  = author.get("nickname", "")
    followers = int(author.get("followerCount", 0) or 0)
    verified  = bool(author.get("verified", False))

    # ── Stats → Engagement ────────────────────────────────────────
    stats    = raw.get("stats", {})
    likes    = int(stats.get("diggCount",    0) or 0)
    comments = int(stats.get("commentCount", 0) or 0)
    shares   = int(stats.get("shareCount",   0) or 0)
    views    = int(stats.get("playCount",    0) or 0)

    # ── Music ─────────────────────────────────────────────────────
    music = raw.get("music", {})
    if isinstance(music, str):
        music = {}
    music_title  = music.get("title", "")
    music_author = music.get("authorName", "")

    # ── Timestamp ─────────────────────────────────────────────────
    timestamp = _unix_to_iso(raw.get("createTime", 0))

    # ── Hashtags + mentions extracted from caption ────────────────
    hashtags = _extract_hashtags(desc)
    mentions = _extract_mentions(desc)

    # ── Post URL ──────────────────────────────────────────────────
    post_url = (
        f"https://www.tiktok.com/@{username}/video/{post_id}"
        if username else f"https://www.tiktok.com/video/{post_id}"
    )

    # ── Comments → top_comments ───────────────────────────────────
    # comments_data is already normalised by scraper.py:
    #   [{author: str, text: str, likes: int}, ...]
    top_comments = [
        {
            "author": c.get("author", ""),
            "text":   c.get("text", ""),
            "likes":  int(c.get("likes", 0) or 0),
        }
        for c in raw.get("comments_data", [])
    ]

    return {
        "platform":        "tiktok",
        "post_id":         post_id,
        "post_url":        post_url,
        "source_type":     raw.get("source", ""),
        "query":           raw.get("query", ""),
        "author_username": username,
        "author_name":     nickname,
        "author_followers": followers,
        "author_verified": verified,
        "text":            desc,
        "timestamp":       timestamp,
        "language":        "",   # TikTok XHR doesn't return lang — NLP fills this
        "hashtags":        hashtags,
        "mentions":        mentions,
        "music_title":     music_title,
        "music_author":    music_author,
        "engagement": {
            "likes":    likes,
            "comments": comments,
            "shares":   shares,
            "views":    views,
            "total":    likes + comments + shares,
        },
        "top_comments": top_comments,
        "scraped_at":   raw.get("scraped_at", datetime.now(timezone.utc).isoformat()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# BATCH NORMALIZER
# ──────────────────────────────────────────────────────────────────────────────

def normalize_batch(raw_videos: list[dict]) -> dict:
    """
    Normalize a list of raw TikTok video dicts into a BrandPulse batch payload.

    Returns a dict with:
        platform   — "tiktok"
        scraped_at — batch timestamp
        post_count — number of successfully normalized posts
        posts      — list of BrandPulse post objects
    """
    posts   = []
    skipped = 0

    for raw in raw_videos:
        normalized = normalize_post(raw)
        if normalized:
            posts.append(normalized)
        else:
            skipped += 1

    if skipped:
        print(f"   ⚠️  Skipped {skipped} malformed video(s) during normalization")

    return {
        "platform":   "tiktok",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "post_count": len(posts),
        "posts":      posts,
    }