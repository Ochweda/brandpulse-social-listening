"""
Normalizes enriched tweet dicts to Instagram-compatible CSV schema.
Field names and order match instagram_scraper_python.py output exactly
so both CSVs can be merged/compared without transformation.
"""
import csv
import json
import os
from typing import List, Dict, Any

# Exact field order matching Instagram pipeline CSV
# X-specific fields (retweets, lang) appended at the end — non-breaking
CSV_FIELDS = [
    "post_url",
    "post_date",
    "username",
    "author_name",
    "is_verified",
    "follower_count",
    "source_hashtag",
    "post_type",
    "likes",
    "comments",
    "engagement_rate",
    "location",
    "location_source",
    "caption",
    "hashtags",
    "source_window",
    "comments_json",
    # X-specific extras
    "retweets",
    "lang",
    "error",
]


def normalize_tweet(enriched: Dict) -> Dict:
    """Flatten one enriched tweet dict into a CSV-ready row."""
    hashtags = enriched.get("hashtags", [])
    hashtags_str = (
        " ".join(f"#{h}" for h in hashtags)
        if isinstance(hashtags, list)
        else str(hashtags)
    )

    return {
        "post_url":        enriched.get("post_url", ""),
        "post_date":       enriched.get("post_date", ""),
        "username":        enriched.get("username", ""),
        "author_name":     enriched.get("author_name", ""),
        "is_verified":     enriched.get("is_verified", ""),
        "follower_count":  enriched.get("follower_count", 0),
        "source_hashtag":  enriched.get("source_hashtag", ""),
        "post_type":       enriched.get("post_type", "tweet"),
        "likes":           enriched.get("likes", 0),
        "comments":        enriched.get("comments", 0),
        "engagement_rate": enriched.get("engagement_rate", 0.0),
        "location":        enriched.get("location", ""),
        "location_source": enriched.get("location_source", ""),
        "caption":         enriched.get("caption", ""),
        "hashtags":        hashtags_str,
        "source_window":   enriched.get("source_window", ""),
        "comments_json":   enriched.get("comments_json", "[]"),
        "retweets":        enriched.get("retweets", 0),
        "lang":            enriched.get("lang", ""),
        "error":           enriched.get("error", ""),
    }


def save_to_csv(enriched_tweets: List[Dict], output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    rows = [normalize_tweet(t) for t in enriched_tweets]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✅ CSV saved: {output_path} ({len(rows)} rows)")
    return output_path


def save_to_json(data: Any, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON saved: {output_path}")
    return output_path