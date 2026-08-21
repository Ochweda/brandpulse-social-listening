"""
BrandPulse Full Pipeline Orchestrator — TikTok Edition
========================================================
Same structure as X and Instagram pipeline orchestrators.

TikTok-specific differences:
    1. NLP enricher receives max_comments=5 (top comments already filtered
       by scraper — no need to cap further)
    2. Batch summary includes TikTok-only fields: play_count, shares
    3. Top videos ranked by a TikTok engagement formula:
         score = likes + (shares * 3) + (play_count * 0.01)
       Shares weighted higher because TikTok shares are a stronger
       signal than likes (harder action, wider reach)
    4. V2 enricher city/county will mostly return None (TikTok strips
       location data) — account_type and brand_mentions still work fully

Usage:
    # Run pipeline on an already-scraped normalized file
    python run_full_pipeline.py brandpulse_output/brandpulse_tiktok_20260310_120000.json

    # Skip NLP (faster)
    python run_full_pipeline.py brandpulse_output/brandpulse_tiktok_20260310_120000.json --skip-nlp
"""

import json
import csv
import os
import sys
import argparse
from datetime import datetime


def load_posts(input_path: str) -> list:
    """Load posts from JSON file."""
    print(f"\n📂 Loading: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    posts = data.get("posts", []) if isinstance(data, dict) else data
    print(f"   Loaded {len(posts)} posts")
    return posts


def run_v1_enricher(posts: list) -> list:
    """
    V1 enricher: product/intent/topic/campaign analysis.
    Works unchanged — normalizer already mapped desc → caption.
    """
    print(f"\n{'='*60}")
    print("🔧 STAGE 1: V1 Enricher (product/intent/topic)")
    print(f"{'='*60}")

    try:
        from brandpulse_enricher import BrandPulseEnricher
        enricher = BrandPulseEnricher()

        for i, post in enumerate(posts):
            v1_fields = enricher.enrich(post)
            # Don't overwrite platform — normalizer already set it to "tiktok"
            v1_fields.pop("platform", None)
            post.update(v1_fields)

            intent = post.get("intent_level", {})
            intent_level = intent.get("level", "?") if isinstance(intent, dict) else intent
            topics = [
                t.get("topic", t) if isinstance(t, dict) else t
                for t in post.get("topic_tags", [])
            ]
            print(
                f"   ✅ [{i+1}/{len(posts)}] @{post.get('username', '?')}: "
                f"intent={intent_level}, topics={topics[:2]}"
            )

        print(f"\n   ✅ V1 complete — {len(posts)} posts processed")

    except ImportError:
        print("   ⚠️  brandpulse_enricher.py not found — skipping V1")
        print("   Copy brandpulse_enricher.py from InstagramScraper into TikTokScraper/")

    return posts


def run_v2_enricher(posts: list) -> list:
    """
    V2 enricher: location/account type/brand mentions.
    City/county will mostly be None (TikTok stripped location data).
    Account type and brand_mentions work fully.
    """
    print(f"\n{'='*60}")
    print("🔧 STAGE 2: V2 Enricher (location/account/brand)")
    print(f"{'='*60}")

    try:
        from brandpulse_enricher_2 import BrandPulseEnricherV2
        enricher = BrandPulseEnricherV2()

        for i, post in enumerate(posts):
            v2_fields = enricher.enrich(post)
            # Don't overwrite is_verified — scraper already set it from TikTokApi
            if post.get("is_verified") is not None:
                v2_fields.pop("is_verified", None)
            post.update(v2_fields)

            account = post.get("account_type", {})
            acct_type = account.get("type", "?") if isinstance(account, dict) else account
            city = post.get("city", "N/A")
            print(
                f"   ✅ [{i+1}/{len(posts)}] @{post.get('username', '?')}: "
                f"city={city}, account={acct_type}"
            )

        print(f"\n   ✅ V2 complete — {len(posts)} posts processed")

    except ImportError:
        print("   ⚠️  brandpulse_enricher_2.py not found — skipping V2")
        print("   Copy brandpulse_enricher_2.py from InstagramScraper into TikTokScraper/")

    return posts


def run_nlp_enricher(posts: list) -> list:
    """
    NLP enricher: language detection, sentiment, keywords, tone.

    Key difference from Instagram:
        TikTok does NOT return language natively (X does, TikTok doesn't).
        NLP enricher will run langdetect on caption text for all posts.

    max_comments=5 because scraper already filtered to top 5 comments.
    """
    print(f"\n{'='*60}")
    print("🧠 STAGE 3: NLP Enricher (language/sentiment/keywords)")
    print(f"{'='*60}")
    print("   ℹ️  Language will be detected via langdetect (TikTok has no native lang field)")

    try:
        from nlp.brandpulse_nlp_enricher import enrich_nlp_batch
        # max_comments=5 mirrors the MAX_COMMENTS_PER_VIDEO config
        posts = enrich_nlp_batch(posts, max_comments=5, verbose=True)
        print(f"\n   ✅ NLP complete — {len(posts)} posts processed")

    except ImportError as e:
        print(f"   ⚠️  NLP enricher import failed: {e}")
        print(
            "   Make sure the nlp/ folder is present in TikTokScraper/\n"
            "   Copy it from InstagramScraper/ — it works unchanged.\n"
            "   Install dependencies: pip install langdetect transformers torch"
        )

    return posts


def generate_batch_summary(posts: list) -> dict:
    """
    Batch summary with TikTok-specific fields.
    Extends the base summary with play_count and shares metrics.
    """
    print(f"\n{'='*60}")
    print("📊 STAGE 4: Batch Summary")
    print(f"{'='*60}")

    from collections import Counter

    summary = {
        "platform":    "tiktok",
        "total_posts": len(posts),
        "timestamp":   datetime.now().isoformat(),
    }

    # ── Sentiment ──
    scores = [
        p.get("sentiment_score", 0) for p in posts
        if p.get("sentiment_score") is not None
    ]
    if scores:
        summary["overall_sentiment_avg"] = round(sum(scores) / len(scores), 4)
        positive = sum(1 for s in scores if s > 0.25)
        negative = sum(1 for s in scores if s < -0.25)
        neutral  = len(scores) - positive - negative
        summary["sentiment_distribution"] = {
            "positive": positive, "neutral": neutral, "negative": negative
        }

    # ── Keyword drivers ──
    all_pos_kw = Counter()
    all_neg_kw = Counter()
    for post in posts:
        for kw in (post.get("positive_keywords") or []):
            word = kw["keyword"] if isinstance(kw, dict) else kw
            all_pos_kw[word] += 1
        for kw in (post.get("negative_keywords") or []):
            word = kw["keyword"] if isinstance(kw, dict) else kw
            all_neg_kw[word] += 1
    summary["top_positive_drivers"] = all_pos_kw.most_common(10)
    summary["top_negative_drivers"] = all_neg_kw.most_common(10)

    # ── Language distribution ──
    lang_dist = Counter(p.get("language_detected", "unknown") for p in posts)
    summary["language_distribution"] = dict(lang_dist)

    # ── High-intent posts ──
    high_intent = [
        p for p in posts
        if (p.get("intent_level") or {}).get("level") == "high"
    ]
    summary["high_intent_count"] = len(high_intent)
    summary["high_intent_usernames"] = [p.get("username", "?") for p in high_intent]

    # ── TikTok-specific: top videos by engagement ──────────────
    # TikTok engagement formula: shares weighted 3x (harder action),
    # play_count fractional (volume metric, not quality signal)
    def tiktok_engagement(p):
        return (
            (p.get("likes_count", 0) or 0)
            + (p.get("shares", 0) or 0) * 3
            + (p.get("play_count", 0) or 0) * 0.01
        )

    top_videos = sorted(posts, key=tiktok_engagement, reverse=True)[:5]
    summary["top_videos_by_engagement"] = [
        {
            "username":     v.get("username"),
            "caption":      (v.get("caption") or "")[:100],
            "likes":        v.get("likes_count", 0),
            "shares":       v.get("shares", 0),
            "play_count":   v.get("play_count", 0),
            "post_url":     v.get("post_url", ""),
        }
        for v in top_videos
    ]

    # ── TikTok-specific: total play counts ──
    total_plays = sum((p.get("play_count", 0) or 0) for p in posts)
    total_shares = sum((p.get("shares", 0) or 0) for p in posts)
    summary["total_play_count"] = total_plays
    summary["total_shares"] = total_shares

    # Print summary
    print(f"\n   📈 Sentiment avg: {summary.get('overall_sentiment_avg', 'N/A')}")
    if "sentiment_distribution" in summary:
        sd = summary["sentiment_distribution"]
        print(f"   📊 Distribution: +{sd['positive']} / ={sd['neutral']} / -{sd['negative']}")
    print(f"   🌍 Languages: {dict(lang_dist)}")
    print(f"   🚨 High-intent posts: {summary['high_intent_count']}")
    print(f"   👁️  Total plays: {total_plays:,}")
    print(f"   🔁 Total shares: {total_shares:,}")
    if summary["top_videos_by_engagement"]:
        top = summary["top_videos_by_engagement"][0]
        print(
            f"   🏆 Top video: @{top['username']} "
            f"({top['likes']:,} ❤️  {top['shares']:,} 🔁  {top['play_count']:,} 👁️ )"
        )

    return summary


def save_outputs(posts: list, summary: dict, input_path: str, output_dir: str = None):
    """Save enriched JSON, CSV, and summary."""
    print(f"\n{'='*60}")
    print("💾 STAGE 5: Saving outputs")
    print(f"{'='*60}")

    if output_dir is None:
        output_dir = os.path.dirname(input_path) or "brandpulse_output"
    os.makedirs(output_dir, exist_ok=True)

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name  = os.path.splitext(os.path.basename(input_path))[0]

    json_path = os.path.join(output_dir, f"{base_name}_enriched_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)
    print(f"   ✅ JSON: {json_path}")

    csv_path = os.path.join(output_dir, f"{base_name}_enriched_{timestamp}.csv")
    if posts:
        flat_posts = []
        for post in posts:
            flat = {}
            for key, value in post.items():
                flat[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
            flat_posts.append(flat)
        fieldnames = list(flat_posts[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(flat_posts)
    print(f"   ✅ CSV: {csv_path}")

    summary_path = os.path.join(output_dir, f"{base_name}_summary_{timestamp}.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"   ✅ Summary: {summary_path}")

    return json_path, csv_path, summary_path


def push_to_supabase(posts: list):
    """Optional: push enriched data to Supabase."""
    print(f"\n{'='*60}")
    print("☁️  STAGE 6: Pushing to Supabase")
    print(f"{'='*60}")

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print("   ⚠️  SUPABASE_URL and SUPABASE_KEY not set — skipping")
        return

    try:
        from supabase import create_client
        client = create_client(supabase_url, supabase_key)

        for i, post in enumerate(posts):
            post_id = post.get("post_id") or post.get("post_url", "")

            update = {
                "language_detected":     post.get("language_detected"),
                "sentiment_score":       post.get("sentiment_score"),
                "sentiment_magnitude":   post.get("sentiment_magnitude"),
                "sentiment_label":       post.get("sentiment_label"),
                "tone":                  post.get("tone"),
                "positive_keywords":     json.dumps(post.get("positive_keywords", [])),
                "negative_keywords":     json.dumps(post.get("negative_keywords", [])),
                "comment_sentiment_avg": post.get("comment_sentiment_avg"),
                # TikTok-specific
                "play_count":            post.get("play_count"),
                "shares":                post.get("shares"),
                "music_title":           post.get("music_title"),
                "platform":              "tiktok",
            }

            try:
                client.table("posts").update(update).eq("post_id", post_id).execute()
                print(f"   ✅ [{i+1}/{len(posts)}] @{post.get('username', '?')}")
            except Exception as e:
                print(f"   ⚠️  [{i+1}/{len(posts)}] Error: {e}")

        print(f"\n   ✅ Supabase push complete")

    except ImportError:
        print("   ⚠️  supabase not installed. Run: pip install supabase")


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BrandPulse TikTok Enrichment Pipeline")
    parser.add_argument("input_json", help="Path to normalized TikTok scrape JSON")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--skip-nlp",  action="store_true")
    parser.add_argument("--skip-v1",   action="store_true")
    parser.add_argument("--skip-v2",   action="store_true")
    parser.add_argument("--supabase",  action="store_true")
    args = parser.parse_args()

    if not os.path.isfile(args.input_json):
        print(f"❌ File not found: {args.input_json}")
        sys.exit(1)

    print("=" * 60)
    print("🚀 BrandPulse TikTok Enrichment Pipeline")
    print("=" * 60)

    posts = load_posts(args.input_json)

    if not args.skip_v1:
        posts = run_v1_enricher(posts)
    if not args.skip_v2:
        posts = run_v2_enricher(posts)
    if not args.skip_nlp:
        posts = run_nlp_enricher(posts)

    summary = generate_batch_summary(posts)
    json_path, csv_path, summary_path = save_outputs(
        posts, summary, args.input_json, args.output_dir
    )

    if args.supabase:
        push_to_supabase(posts)

    print(f"\n{'='*60}")
    print("✅ Pipeline complete!")
    print(f"   📄 {json_path}")
    print(f"   📊 {csv_path}")
    print(f"   📈 {summary_path}")


if __name__ == "__main__":
    main()