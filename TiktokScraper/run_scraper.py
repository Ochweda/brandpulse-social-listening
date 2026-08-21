"""
BrandPulse TikTok Scraper — Single Entry Point
================================================
One command runs the full pipeline:
    scrape → normalize → V1 enrichment → V2 enrichment → NLP → output

Lessons applied from Instagram and X builds:
    ✅ Single entry point (no more 4 separate commands)
    ✅ AfriSenti / NLP model loads ONCE at startup, stays in memory
       for the entire NLP batch — not reloaded per post
    ✅ V1 and V2 enrichers run from the same process (no subprocess overhead)
    ✅ Output saved automatically with timestamp
    ✅ --skip-nlp flag for fast test runs
    ✅ CSV export: one row per post, all comments as JSON array in one cell

Usage:
    # Scrape only (save raw + normalized JSON + CSV)
    python run_scraper.py

    # Scrape + full enrichment pipeline (V1 + V2 + NLP)
    python run_scraper.py --enrich

    # Scrape + V1 + V2 only (fast — skips model loading)
    python run_scraper.py --enrich --skip-nlp

    # Scrape + enrich + push to Supabase
    python run_scraper.py --enrich --supabase
"""

import asyncio
import argparse
import csv
import json
import os
from datetime import datetime

from Scripts.scraper import run_full_scrape
from Scripts.normalizer import normalize_batch


# ──────────────────────────────────────────────────────────────────
# CSV FIELDS
# ──────────────────────────────────────────────────────────────────

# Every scalar field from the BrandPulse post schema.
# comments_json is a JSON-serialised array — one cell per post row,
# containing all collected comments with author / text / likes.
CSV_FIELDS = [
    "platform",
    "post_id",
    "post_url",
    "source_type",
    "query",
    "author_username",
    "author_name",
    "author_followers",
    "author_verified",
    "text",
    "timestamp",
    "language",
    "hashtags",          # comma-joined string
    "mentions",          # comma-joined string
    "music_title",
    "music_author",
    "likes",
    "comments",          # total comment count from TikTok stats
    "shares",
    "views",
    "total_engagement",
    "comments_json",     # JSON array: [{author, text, likes}, ...]
    "scraped_at",
]


# ──────────────────────────────────────────────────────────────────
# STEP 1: SCRAPE + NORMALIZE + SAVE
# ──────────────────────────────────────────────────────────────────

async def scrape_and_save(output_dir: str = "brandpulse_output") -> str | None:
    """
    Run the full TikTok scrape, normalize to BrandPulse schema,
    save both JSON and CSV to disk.

    CSV structure:
        One row per post. All comments for that post are serialised
        as a JSON array in the `comments_json` column — e.g.:
            [{"author":"user1","text":"Great truck!","likes":12}, ...]

        Load in pandas with:
            import pandas as pd, json
            df = pd.read_csv("brandpulse_tiktok_*.csv")
            df['comments'] = df['comments_json'].apply(json.loads)

    Returns path to the normalized JSON file (pipeline input).
    """
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("🎬 BrandPulse TikTok Scraper")
    print("=" * 60)

    # ── Scrape ──────────────────────────────────────────────────
    print("\n[1/4] Scraping TikTok...")
    raw_videos = await run_full_scrape()
    print(f"      ✅ Collected {len(raw_videos)} videos")

    if not raw_videos:
        print(
            "\n      ⚠️  No videos collected.\n"
            "      Check:\n"
            "        1. Is Chrome profile path correct in config.py?\n"
            "        2. Run: python -m Scripts.auth  to verify your session\n"
            "        3. Run: python -m Scripts.scraper  to test a single hashtag\n"
        )
        return None

    # ── Normalize ───────────────────────────────────────────────
    print("\n[2/4] Normalizing to BrandPulse schema...")
    normalized_data = normalize_batch(raw_videos)
    posts = normalized_data["posts"]
    print(f"      ✅ Normalized {len(posts)} posts")

    total_comments = sum(len(p.get("top_comments", [])) for p in posts)
    print(f"      💬 {total_comments} total comments across all posts")

    # ── Save JSON ────────────────────────────────────────────────
    print("\n[3/4] Saving JSON output...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # os.path.abspath resolves relative paths to absolute — prevents
    # Windows OSError [Errno 22] Invalid argument on relative paths
    output_dir_abs = os.path.abspath(output_dir)
    os.makedirs(output_dir_abs, exist_ok=True)

    normalized_path = os.path.join(
        output_dir_abs, f"brandpulse_tiktok_{timestamp}.json"
    )
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(normalized_data, f, ensure_ascii=False, indent=2)
    print(f"      ✅ Normalized JSON: {normalized_path}")

    raw_path = os.path.join(output_dir_abs, f"tiktok_raw_{timestamp}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_videos, f, ensure_ascii=False, indent=2)
    print(f"      ✅ Raw backup:      {raw_path}")

    # ── Save CSV ─────────────────────────────────────────────────
    print("\n[4/4] Saving CSV output...")
    csv_path = os.path.join(
        output_dir_abs, f"brandpulse_tiktok_{timestamp}.csv"
    )
    _save_csv(posts, csv_path)
    print(f"      ✅ CSV:             {csv_path}")
    print(
        f"\n      📌 CSV format: one row per post.\n"
        f"         comments_json column = JSON array of all comments.\n"
        f"         Load with: df['comments'] = df['comments_json'].apply(json.loads)"
    )

    return normalized_path


def _save_csv(posts: list[dict], csv_path: str) -> None:
    """
    Write posts to CSV. One row per post.

    comments_json column contains a JSON-serialised array of every comment
    collected for that post:
        [
          {"author": "user1", "text": "Great truck!", "likes": 12},
          {"author": "user2", "text": "How much?",    "likes": 3},
          ...
        ]

    This keeps the flat CSV structure (one row = one post) while preserving
    full comment data. Load with json.loads() in pandas or any JSON parser.
    """
    if not posts:
        return

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()

        for post in posts:
            engagement = post.get("engagement", {})

            hashtags = post.get("hashtags", [])
            mentions = post.get("mentions", [])

            # Serialise full comments list as a JSON array in one cell
            top_comments  = post.get("top_comments", [])
            comments_json = json.dumps(top_comments, ensure_ascii=False)

            writer.writerow({
                "platform":         post.get("platform", ""),
                "post_id":          post.get("post_id", ""),
                "post_url":         post.get("post_url", ""),
                "source_type":      post.get("source_type", ""),
                "query":            post.get("query", ""),
                "author_username":  post.get("author_username", ""),
                "author_name":      post.get("author_name", ""),
                "author_followers": post.get("author_followers", 0),
                "author_verified":  post.get("author_verified", False),
                "text":             str(post.get("text", ""))[:500],
                "timestamp":        post.get("timestamp", ""),
                "language":         post.get("language", ""),
                "hashtags":         ", ".join(hashtags) if hashtags else "",
                "mentions":         ", ".join(mentions) if mentions else "",
                "music_title":      post.get("music_title", ""),
                "music_author":     post.get("music_author", ""),
                "likes":            engagement.get("likes", 0),
                "comments":         engagement.get("comments", 0),
                "shares":           engagement.get("shares", 0),
                "views":            engagement.get("views", 0),
                "total_engagement": engagement.get("total", 0),
                "comments_json":    comments_json,
                "scraped_at":       post.get("scraped_at", ""),
            })


# ──────────────────────────────────────────────────────────────────
# STEP 2: ENRICHMENT PIPELINE
# ──────────────────────────────────────────────────────────────────

def run_pipeline(
    normalized_path: str,
    skip_nlp: bool = False,
    push_supabase: bool = False,
):
    """
    Chain the normalized JSON through the full enrichment pipeline.

    Imports run_full_pipeline which handles V1 → V2 → NLP in sequence.
    Because this runs in the same process as the scraper, the NLP model
    is loaded once and stays in memory — no reload between posts.
    """
    print("\n" + "=" * 60)
    print("🔧 Starting enrichment pipeline...")
    print("=" * 60)

    try:
        from run_full_pipeline import (
            load_posts, run_v1_enricher, run_v2_enricher,
            run_nlp_enricher, generate_batch_summary,
            save_outputs, push_to_supabase,
        )

        posts = load_posts(normalized_path)
        posts = run_v1_enricher(posts)
        posts = run_v2_enricher(posts)

        if not skip_nlp:
            posts = run_nlp_enricher(posts)

        summary = generate_batch_summary(posts)
        json_path, csv_path, summary_path = save_outputs(
            posts, summary, normalized_path
        )

        if push_supabase:
            push_to_supabase(posts)

        print(f"\n✅ Pipeline complete!")
        print(f"   📄 Enriched JSON: {json_path}")
        print(f"   📊 Enriched CSV:  {csv_path}")
        print(f"   📈 Summary:       {summary_path}")

    except ImportError as e:
        print(f"   ⚠️  Pipeline import failed: {e}")
        print(
            "   Make sure these files are in the TikTokScraper root folder:\n"
            "     run_full_pipeline.py\n"
            "     brandpulse_enricher.py\n"
            "     brandpulse_enricher_2.py\n"
            "   (Copy them from InstagramScraper — they work unchanged)"
        )


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="BrandPulse TikTok Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_scraper.py                        # scrape + save JSON + CSV
  python run_scraper.py --enrich               # full enrichment pipeline
  python run_scraper.py --enrich --skip-nlp    # no model loading (fast)
  python run_scraper.py --enrich --supabase    # full pipeline + push to DB
        """
    )
    parser.add_argument(
        "--enrich", action="store_true",
        help="Run full enrichment pipeline after scraping"
    )
    parser.add_argument(
        "--skip-nlp", action="store_true",
        help="Skip NLP stage (no AfriSenti model load — faster)"
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

    normalized_path = await scrape_and_save(args.output_dir)

    if not normalized_path:
        return

    if args.enrich:
        run_pipeline(
            normalized_path,
            skip_nlp=args.skip_nlp,
            push_supabase=args.supabase,
        )
    else:
        print(
            f"\n💡 Tip: Run with --enrich to process through the full pipeline:\n"
            f"   python run_scraper.py --enrich\n"
            f"   python run_scraper.py --enrich --skip-nlp  (faster, no model load)\n"
        )


if __name__ == "__main__":
    asyncio.run(main())