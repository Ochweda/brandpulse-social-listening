"""
BrandPulse Facebook Scraper — Single Entry Point
=================================================
Two-phase pipeline:
    Phase 1: collect post metadata (GraphQL feed interception)
    Phase 2: collect comments per post (GraphQL comment pagination)

Then normalize → save JSON + CSV.

Usage:
    # Full run
    python run_scraper.py

    # Skip comments (fast metadata-only run)
    python run_scraper.py --skip-comments

    # Custom date range override
    python run_scraper.py --date-from 2025-01-01 --date-to 2025-06-30

    # Full run + push to Supabase
    python run_scraper.py --supabase
"""

import asyncio
import argparse
import csv
import json
import os
from datetime import datetime

from ScraperCode.Scraper import run_full_scrape
from ScraperCode.normalizer2 import normalize_batch


# ──────────────────────────────────────────────────────────────────────────────
# CSV FIELDS
# ──────────────────────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "platform",
    "post_id",
    "post_url",
    "source_type",
    "query",
    "author_name",
    "author_id",
    "text",
    "timestamp",
    "language",
    "hashtags",       # comma-joined
    "mentions",       # comma-joined
    "reactions",
    "comments",       # total comment count from metadata
    "shares",
    "total_engagement",
    "comments_json",  # JSON array of collected comments
    "scraped_at",
]


# ──────────────────────────────────────────────────────────────────────────────
# MAIN SCRAPE + SAVE
# ──────────────────────────────────────────────────────────────────────────────

async def scrape_and_save(
    output_dir: str = "brandpulse_output",
    date_from: str | None = None,
    date_to: str | None = None,
    skip_comments: bool = False,
) -> str | None:
    """
    Run the full Facebook scrape pipeline and save outputs.
    Returns path to the normalized JSON file.
    """
    # Apply any CLI date overrides before importing config values
    if date_from or date_to:
        import config
        if date_from:
            config.DATE_FROM = date_from
            import Scripts.scraper as sc
            from datetime import timezone
            sc._TS_FROM = int(
                datetime.fromisoformat(date_from)
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        if date_to:
            config.DATE_TO = date_to
            import Scripts.scraper as sc
            from datetime import timezone
            sc._TS_TO = int(
                datetime.fromisoformat(date_to)
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )

    if skip_comments:
        import config
        config.MAX_COMMENTS_PER_POST = 0

    output_dir_abs = os.path.abspath(output_dir)
    os.makedirs(output_dir_abs, exist_ok=True)

    print("=" * 60)
    print("📘 BrandPulse Facebook Scraper")
    print("=" * 60)

    # ── Scrape ─────────────────────────────────────────────────────
    print("\n[1/4] Scraping Facebook...")
    raw_posts = await run_full_scrape()
    print(f"      ✅ Collected {len(raw_posts)} posts")

    if not raw_posts:
        print(
            "\n      ⚠️  No posts collected.\n"
            "      Check:\n"
            "        1. Run: python -m Scripts.auth  to verify your session\n"
            "        2. Is DATE_FROM/DATE_TO range correct in config.py?\n"
            "        3. Run: python -m Scripts.scraper  to test a single search\n"
        )
        return None

    # ── Normalize ───────────────────────────────────────────────────
    print("\n[2/4] Normalizing to BrandPulse schema...")
    normalized_data = normalize_batch(raw_posts)
    posts = normalized_data["posts"]
    total_comments = sum(len(p.get("top_comments", [])) for p in posts)
    print(f"      ✅ Normalized {len(posts)} posts")
    print(f"      💬 {total_comments} total comments")

    # ── Save JSON ───────────────────────────────────────────────────
    print("\n[3/4] Saving JSON output...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    normalized_path = os.path.join(
        output_dir_abs, f"brandpulse_facebook_{timestamp}.json"
    )
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(normalized_data, f, ensure_ascii=False, indent=2)
    print(f"      ✅ Normalized JSON: {normalized_path}")

    raw_path = os.path.join(output_dir_abs, f"facebook_raw_{timestamp}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_posts, f, ensure_ascii=False, indent=2)
    print(f"      ✅ Raw backup:      {raw_path}")

    # ── Save CSV ────────────────────────────────────────────────────
    print("\n[4/4] Saving CSV output...")
    csv_path = os.path.join(
        output_dir_abs, f"brandpulse_facebook_{timestamp}.csv"
    )
    _save_csv(posts, csv_path)
    print(f"      ✅ CSV:             {csv_path}")
    print(
        "\n      📌 CSV format: one row per post.\n"
        "         comments_json = JSON array [{author, text, likes, timestamp}]\n"
        "         Load: df['comments'] = df['comments_json'].apply(json.loads)"
    )

    return normalized_path


def _save_csv(posts: list[dict], csv_path: str) -> None:
    """Write normalized posts to CSV. One row per post, comments as JSON array."""
    if not posts:
        return

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()

        for post in posts:
            engagement = post.get("engagement", {})
            hashtags   = post.get("hashtags", [])
            mentions   = post.get("mentions", [])
            comments   = post.get("top_comments", [])

            writer.writerow({
                "platform":        post.get("platform", ""),
                "post_id":         post.get("post_id", ""),
                "post_url":        post.get("post_url", ""),
                "source_type":     post.get("source_type", ""),
                "query":           post.get("query", ""),
                "author_name":     post.get("author_name", ""),
                "author_id":       post.get("author_id", ""),
                "text":            str(post.get("text", ""))[:500],
                "timestamp":       post.get("timestamp", ""),
                "language":        post.get("language", ""),
                "hashtags":        ", ".join(hashtags) if hashtags else "",
                "mentions":        ", ".join(mentions) if mentions else "",
                "reactions":       engagement.get("reactions", 0),
                "comments":        engagement.get("comments", 0),
                "shares":          engagement.get("shares", 0),
                "total_engagement": engagement.get("total", 0),
                "comments_json":   json.dumps(comments, ensure_ascii=False),
                "scraped_at":      post.get("scraped_at", ""),
            })


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="BrandPulse Facebook Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_scraper.py                                      # full run
  python run_scraper.py --skip-comments                      # metadata only (fast)
  python run_scraper.py --date-from 2025-01-01 --date-to 2025-06-30
  python run_scraper.py --supabase                           # full + push to DB
        """
    )
    parser.add_argument(
        "--skip-comments", action="store_true",
        help="Skip comment collection (metadata-only, much faster)"
    )
    parser.add_argument(
        "--date-from", default=None,
        help="Override DATE_FROM from config (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--date-to", default=None,
        help="Override DATE_TO from config (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--supabase", action="store_true",
        help="Push enriched results to Supabase after pipeline"
    )
    parser.add_argument(
        "--output-dir", default="brandpulse_output",
        help="Output directory (default: brandpulse_output)"
    )
    args = parser.parse_args()

    normalized_path = await scrape_and_save(
        output_dir=args.output_dir,
        date_from=args.date_from,
        date_to=args.date_to,
        skip_comments=args.skip_comments,
    )

    if not normalized_path:
        return

    if args.supabase:
        try:
            from run_full_pipeline import push_to_supabase, load_posts
            push_to_supabase(load_posts(normalized_path))
            print("✅ Pushed to Supabase.")
        except ImportError:
            print(
                "⚠️  run_full_pipeline.py not found.\n"
                "   Copy it from InstagramScraper — it works unchanged."
            )

    print(f"\n✅ Done. Output: {normalized_path}\n")


if __name__ == "__main__":
    asyncio.run(main())