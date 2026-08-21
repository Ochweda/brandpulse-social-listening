"""
BrandPulse Facebook Scraper — Normalizer
=========================================
Converts raw Facebook post dicts (from scraper.py) into the standard
BrandPulse schema used by Instagram, TikTok, and X scrapers.

Raw post dict fields (from scraper.py):
    post_id         — Facebook post ID string
    post_url        — permalink URL
    text            — post body text
    created_time    — unix timestamp (int)
    author_name     — display name
    author_id       — Facebook user/page ID
    reactions       — total reaction count
    comment_count   — total comments (from metadata)
    shares          — share count
    source          — "search" | "page_feed"
    query           — search term or page URL
    scraped_at      — ISO 8601 string
    comments        — list of raw comment dicts

Raw comment dict fields:
    comment_id      — Facebook comment ID
    text            — comment body
    created_time    — unix timestamp
    author_name     — commenter display name
    author_id       — commenter Facebook ID
    likes           — comment like count

BrandPulse schema (post object):
    platform        — "facebook"
    post_id
    post_url
    source_type     — "search" | "page_feed"
    query
    author_name
    author_id
    text
    timestamp       — ISO 8601 (converted from unix)
    language        — "" (NLP fills this downstream)
    hashtags        — extracted from text
    mentions        — @mentions extracted from text
    engagement:
        reactions
        comments    — total comment count from metadata
        shares
        total
    top_comments    — normalised comment list [{author, text, likes, timestamp}]
    scraped_at
"""

import re
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _unix_to_iso(unix_ts) -> str:
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _extract_hashtags(text: str) -> list[str]:
    return [tag.lower() for tag in re.findall(r"#(\w+)", text)]


def _extract_mentions(text: str) -> list[str]:
    return [m.lower() for m in re.findall(r"@(\w+)", text)]


# ──────────────────────────────────────────────────────────────────────────────
# SINGLE POST NORMALIZER
# ──────────────────────────────────────────────────────────────────────────────

def normalize_post(raw: dict) -> dict | None:
    """
    Normalize a single raw Facebook post dict to BrandPulse schema.
    Returns None if post_id is missing.
    """
    post_id = str(raw.get("post_id", "")).strip()
    if not post_id:
        return None

    text = str(raw.get("text", "")).strip()

    # Normalise comments list
    top_comments = []
    for c in raw.get("comments", []):
        if not c.get("text"):
            continue
        top_comments.append({
            "author":     c.get("author_name", ""),
            "author_id":  str(c.get("author_id", "")),
            "text":       c.get("text", ""),
            "likes":      int(c.get("likes", 0) or 0),
            "timestamp":  _unix_to_iso(c.get("created_time", 0)),
        })

    reactions = int(raw.get("reactions", 0) or 0)
    comments  = int(raw.get("comment_count", 0) or 0)
    shares    = int(raw.get("shares", 0) or 0)

    return {
        "platform":    "facebook",
        "post_id":     post_id,
        "post_url":    raw.get("post_url", ""),
        "source_type": raw.get("source", ""),
        "query":       raw.get("query", ""),
        "author_name": raw.get("author_name", ""),
        "author_id":   str(raw.get("author_id", "")),
        "text":        text,
        "timestamp":   _unix_to_iso(raw.get("created_time", 0)),
        "language":    "",
        "hashtags":    _extract_hashtags(text),
        "mentions":    _extract_mentions(text),
        "engagement": {
            "reactions": reactions,
            "comments":  comments,
            "shares":    shares,
            "total":     reactions + comments + shares,
        },
        "top_comments": top_comments,
        "scraped_at":   raw.get("scraped_at", datetime.now(timezone.utc).isoformat()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# BATCH NORMALIZER
# ──────────────────────────────────────────────────────────────────────────────

def normalize_batch(raw_posts: list[dict]) -> dict:
    """
    Normalize a list of raw post dicts into a BrandPulse batch payload.
    """
    posts   = []
    skipped = 0

    for raw in raw_posts:
        normalized = normalize_post(raw)
        if normalized:
            posts.append(normalized)
        else:
            skipped += 1

    if skipped:
        print(f"   ⚠️  Skipped {skipped} malformed post(s) during normalization")

    return {
        "platform":   "facebook",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "post_count": len(posts),
        "posts":      posts,
    }