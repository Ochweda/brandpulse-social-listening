"""
BrandPulse LinkedIn Scraper — Entry Point
==========================================
Full pipeline: auth → scrape → normalize → save JSON + CSV

Usage:
    # Full run
    python run_scraper.py

    # Skip comments (posts only, much faster)
    python run_scraper.py --skip-comments

    # Date range override
    python run_scraper.py --date-from 2025-01-01 --date-to 2025-12-31
"""

import asyncio
import argparse
import csv
import json
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

from ScraperCode.auth      import get_linkedin_cookies, verify_cookies
from ScraperCode.Scraper   import run_full_scrape
from ScraperCode.normalizer import normalize_batch


CSV_FIELDS = [
    "platform",
    "post_id",
    "post_url",
    "source_type",
    "query",
    "author_name",
    "author_id",
    "author_url",
    "text",
    "time_text",
    "language",
    "hashtags",
    "mentions",
    "reactions",
    "comments",
    "reposts",
    "total_engagement",
    "comments_json",
    "scraped_at",
]


async def scrape_and_save(
    output_dir: str = "brandpulse_output",
    skip_comments: bool = False,
) -> str | None:

    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("🔷 BrandPulse LinkedIn Scraper")
    print("=" * 60)

    print("\n[1/4] Using CfT persistent profile for authentication")

    print("\n[2/4] Scraping LinkedIn via Playwright DOM...")

    if skip_comments:
        import config as cfg
        cfg.MAX_COMMENTS_PER_POST = 0

    from playwright.async_api import async_playwright as _apw
    async with _apw() as playwright:
        raw_posts = await run_full_scrape(playwright)

    print(f"      ✅ Collected {len(raw_posts)} posts")

    if not raw_posts:
        print("\n      ⚠️  No posts. Run: python -m ScraperCode.Scraper to test.\n")
        return None

    # ── Step 3: Normalize ─────────────────────────────────────────
    print("\n[3/4] Normalizing to BrandPulse schema...")
    normalized_data = normalize_batch(raw_posts)
    posts           = normalized_data["posts"]
    total_comments  = sum(len(p.get("top_comments", [])) for p in posts)
    print(f"      ✅ Normalized {len(posts)} posts")
    print(f"      💬 {total_comments} total comments")

    # ── Step 4: Save ──────────────────────────────────────────────
    print("\n[4/4] Saving outputs...")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = os.path.join(output_dir, f"brandpulse_linkedin_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(normalized_data, f, ensure_ascii=False, indent=2)
    print(f"      ✅ JSON:       {json_path}")

    raw_path = os.path.join(output_dir, f"linkedin_raw_{ts}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_posts, f, ensure_ascii=False, indent=2)
    print(f"      ✅ Raw backup: {raw_path}")

    csv_path = os.path.join(output_dir, f"brandpulse_linkedin_{ts}.csv")
    _save_csv(posts, csv_path)
    print(f"      ✅ CSV:        {csv_path}")

    return json_path


def _save_csv(posts: list[dict], csv_path: str) -> None:
    if not posts:
        return

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()

        for post in posts:
            eng      = post.get("engagement", {})
            hashtags = post.get("hashtags", [])
            mentions = post.get("mentions", [])
            comments = post.get("top_comments", [])

            writer.writerow({
                "platform":        post.get("platform", ""),
                "post_id":         post.get("post_id", ""),
                "post_urn":        post.get("post_urn", ""),
                "post_url":        post.get("post_url", ""),
                "source_type":     post.get("source_type", ""),
                "query":           post.get("query", ""),
                "author_name":     post.get("author_name", ""),
                "author_id":       post.get("author_id", ""),
                "text":            str(post.get("text", ""))[:1000],
                "article_title":   post.get("article_title", ""),
                "timestamp":       post.get("timestamp", ""),
                "language":        post.get("language", ""),
                "hashtags":        ", ".join(hashtags) if hashtags else "",
                "mentions":        ", ".join(mentions) if mentions else "",
                "reactions":       eng.get("reactions", 0),
                "comments":        eng.get("comments", 0),
                "shares":          eng.get("shares", 0),
                "total_engagement": eng.get("total", 0),
                "comments_json":   json.dumps(comments, ensure_ascii=False),
                "scraped_at":      post.get("scraped_at", ""),
            })


async def main():
    parser = argparse.ArgumentParser(description="BrandPulse LinkedIn Scraper")
    parser.add_argument(
        "--skip-comments", action="store_true",
        help="Skip comment collection (posts only, much faster)"
    )
    parser.add_argument(
        "--date-from", default=None, help="Override DATE_FROM (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--date-to", default=None, help="Override DATE_TO (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--output-dir", default="brandpulse_output", help="Output directory"
    )
    args = parser.parse_args()

    if args.date_from or args.date_to:
        import config
        from datetime import timezone as tz
        if args.date_from:
            config.DATE_FROM = args.date_from
            import ScraperCode.Scraper as sc
            sc._TS_FROM = int(
                datetime.fromisoformat(args.date_from)
                .replace(tzinfo=tz.utc).timestamp() * 1000
            )
        if args.date_to:
            config.DATE_TO = args.date_to
            import ScraperCode.Scraper as sc
            sc._TS_TO = int(
                datetime.fromisoformat(args.date_to)
                .replace(tzinfo=tz.utc).timestamp() * 1000
            )

    result = await scrape_and_save(
        output_dir=args.output_dir,
        skip_comments=args.skip_comments,
    )

    if result:
        print(f"\n✅ Done. Output: {result}\n")
    else:
        print("\n❌ Scrape failed. See messages above.\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())