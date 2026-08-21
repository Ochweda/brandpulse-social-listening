"""
BrandPulse LinkedIn Scraper — Normalizer
=========================================
Converts raw DOM-scraped post dicts into the BrandPulse schema.

Raw post dict fields (from Scraper.py DOM extraction):
    post_id       — LinkedIn activity/ugcPost numeric ID (may be empty)
    post_url      — full permalink URL (may be empty)
    text          — post body text (always present)
    author_name   — display name (may be empty if selector missed)
    author_id     — profile slug from URL
    author_url    — full profile/company URL
    time_text     — relative time string ("5d", "2w", "3mo")
    reactions     — total reaction count
    comment_count — comment count from post metadata
    reposts       — repost/reshare count
    hashtags      — list of hashtag strings
    source        — "company_feed" | "search"
    query         — company slug or search keyword
    scraped_at    — ISO 8601 string
    comments      — list of raw comment dicts

Raw comment dict:
    comment_id   — md5 hash
    text         — comment text
    author_name  — commenter name
    author_id    — profile slug
    timestamp    — relative or aria-label time string
    likes        — comment like count
    created_time — 0 (not available from DOM)
"""

import re
import hashlib
from datetime import datetime, timezone


def _make_post_id(raw: dict) -> str:
    """
    Generate a stable post ID. Use the scraped post_id if available,
    otherwise hash the text content. This ensures every post has a key.
    """
    if raw.get("post_id"):
        return str(raw["post_id"])
    text = raw.get("text", "")
    return hashlib.md5(text[:120].encode()).hexdigest()[:16]


def _extract_hashtags(text: str) -> list[str]:
    found = re.findall(r"#(\w+)", text)
    return list({tag.lower() for tag in found})


def _extract_mentions(text: str) -> list[str]:
    return list({m.lower() for m in re.findall(r"@(\w+)", text)})


def _parse_time_text(time_text: str) -> str:
    """
    Convert LinkedIn relative time ("5d", "2w", "3mo") to a note string.
    We can't convert to ISO without a reference date, so we store as-is.
    """
    return time_text.strip() if time_text else ""


def normalize_post(raw: dict) -> dict | None:
    """Normalize a single raw DOM post dict to BrandPulse schema."""

    text = str(raw.get("text", "")).strip()

    # Every post must have text — skip completely empty posts
    if not text:
        return None

    post_id  = _make_post_id(raw)
    post_url = str(raw.get("post_url", "")).strip()
    hashtags = raw.get("hashtags", []) or _extract_hashtags(text)
    mentions = _extract_mentions(text)

    # Engagement
    reactions     = int(raw.get("reactions", 0) or 0)
    comment_count = int(raw.get("comment_count", 0) or 0)
    reposts       = int(raw.get("reposts", 0) or 0)

    # Comments
    top_comments = []
    for c in raw.get("comments", []):
        if not c.get("text"):
            continue
        top_comments.append({
            "author":    c.get("author_name", ""),
            "author_id": str(c.get("author_id", "")),
            "text":      c.get("text", ""),
            "likes":     int(c.get("likes", 0) or 0),
            "timestamp": c.get("timestamp", ""),
        })

    return {
        "platform":     "linkedin",
        "post_id":      post_id,
        "post_url":     post_url,
        "source_type":  raw.get("source", ""),
        "query":        raw.get("query", ""),
        "author_name":  str(raw.get("author_name", "") or ""),
        "author_id":    str(raw.get("author_id", "") or ""),
        "author_url":   str(raw.get("author_url", "") or ""),
        "text":         text,
        "time_text":    _parse_time_text(raw.get("time_text", "")),
        "timestamp":    "",          # relative only — no ISO conversion possible
        "language":     "",          # filled by NLP pipeline downstream
        "hashtags":     list(set(hashtags)),
        "mentions":     mentions,
        "engagement": {
            "reactions":     reactions,
            "comments":      comment_count,
            "reposts":       reposts,
            "total":         reactions + comment_count + reposts,
        },
        "top_comments": top_comments,
        "scraped_at":   raw.get("scraped_at", datetime.now(timezone.utc).isoformat()),
    }


def normalize_batch(raw_posts: list[dict]) -> dict:
    """Normalize a list of raw post dicts into a BrandPulse batch payload."""
    posts   = []
    skipped = 0

    for raw in raw_posts:
        normalized = normalize_post(raw)
        if normalized:
            posts.append(normalized)
        else:
            skipped += 1

    if skipped:
        print(f"   ⚠️  Skipped {skipped} empty post(s) during normalization")

    return {
        "platform":   "linkedin",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "post_count": len(posts),
        "posts":      posts,
    }