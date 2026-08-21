"""
BrandPulse Full Pipeline Orchestrator — X (Twitter) Edition
=============================================================
Identical to the Instagram pipeline orchestrator with two key differences:

  1. Loads posts from the normalized JSON output of run_x_pipeline.py
     (posts already have "caption", "username", etc. mapped by normalizer.py)

  2. V2 enricher skips geo_enrichment lookups gracefully when location
     data is absent (common on X after Twitter removed location fields in 2023)

  3. NLP enricher respects the pre-detected language_detected field
     from the X API — skips langdetect when already set.

Usage:
    # Full pipeline on a normalized X scrape file
    python run_full_pipeline.py brandpulse_output/brandpulse_x_20260304_120000.json

    # Skip NLP (faster)
    python run_full_pipeline.py brandpulse_output/brandpulse_x_20260304_120000.json --skip-nlp

    # Push to Supabase after enrichment
    python run_full_pipeline.py brandpulse_output/brandpulse_x_20260304_120000.json --supabase
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
    # Handle both formats: raw list or {"metadata": ..., "posts": [...]}
    if isinstance(data, dict) and "posts" in data:
        posts = data["posts"]
    else:
        posts = data
    print(f"   Loaded {len(posts)} posts")
    return posts


def run_v1_enricher(posts: list) -> list:
    """
    Run V1 enricher (brandpulse_enricher.py).
    Adds: product_mentions, partner_mentions, intent_level,
          topic_tags, emoji_summary, platform, campaign_tags.

    Works unchanged on X data because normalizer.py already mapped:
        tweet["text"] → post["caption"]
        tweet["author"] → post["username"]
        etc.
    """
    print(f"\n{'='*60}")
    print("🔧 STAGE 1: V1 Enricher (product/intent/topic)")
    print(f"{'='*60}")

    try:
        from brandpulse_enricher import BrandPulseEnricher
        enricher = BrandPulseEnricher()

        for i, post in enumerate(posts):
            v1_fields = enricher.enrich(post)
            # Don't overwrite platform — normalizer already set it to "twitter"
            v1_fields.pop("platform", None)
            post.update(v1_fields)
            intent = post.get("intent_level", {})
            intent_level = intent.get("level", "?") if isinstance(intent, dict) else intent
            topics = [t.get("topic", t) if isinstance(t, dict) else t
                      for t in post.get("topic_tags", [])]
            print(f"   ✅ [{i+1}/{len(posts)}] @{post.get('username', '?')}: "
                  f"intent={intent_level}, topics={topics[:2]}")

        print(f"\n   ✅ V1 enrichment complete — {len(posts)} posts processed")

    except ImportError:
        print("   ⚠️  brandpulse_enricher.py not found — skipping V1")
        print("   Copy brandpulse_enricher.py into the XScraper root folder.")

    return posts


def run_v2_enricher(posts: list) -> list:
    """
    Run V2 enricher (brandpulse_enricher_2.py).
    Adds: city, county, area_type, account_type, brand_mentions,
          is_verified, latitude, longitude.

    Note: City/county will mostly return None for X posts since X
    stripped location data in 2023. Account type + brand mentions
    will still work normally.
    """
    print(f"\n{'='*60}")
    print("🔧 STAGE 2: V2 Enricher (location/account/brand)")
    print(f"{'='*60}")

    try:
        from brandpulse_enricher_2 import BrandPulseEnricherV2
        enricher = BrandPulseEnricherV2()

        for i, post in enumerate(posts):
            v2_fields = enricher.enrich(post)
            # Don't overwrite is_verified if scraper already set it from twikit
            if post.get("is_verified") is not None:
                v2_fields.pop("is_verified", None)
            post.update(v2_fields)
            account = post.get("account_type", {})
            acct_type = account.get("type", "?") if isinstance(account, dict) else account
            city = post.get("city", "N/A")
            print(f"   ✅ [{i+1}/{len(posts)}] @{post.get('username', '?')}: "
                  f"city={city}, account={acct_type}")

        print(f"\n   ✅ V2 enrichment complete — {len(posts)} posts processed")

    except ImportError:
        print("   ⚠️  brandpulse_enricher_2.py not found — skipping V2")
        print("   Make sure brandpulse_enricher_2.py is in the XScraper root folder.")

    return posts


def run_nlp_enricher(posts: list) -> list:
    """
    Run NLP enricher (nlp/brandpulse_nlp_enricher.py).
    Adds: language_detected, sentiment_score, sentiment_magnitude,
          tone, positive_keywords, negative_keywords, comment_sentiment_avg.

    X-specific optimization: tweets already have language_detected set
    from the X API (mapped by normalizer.py). The NLP enricher will use
    this value directly instead of running langdetect.
    """
    print(f"\n{'='*60}")
    print("🧠 STAGE 3: NLP Enricher (language/sentiment/keywords)")
    print(f"{'='*60}")

    # Log how many tweets already have language pre-detected
    pre_detected = sum(1 for p in posts if p.get("language_detected"))
    print(f"   ℹ️  {pre_detected}/{len(posts)} tweets have pre-detected language from X API")

    try:
        from nlp.brandpulse_nlp_enricher import enrich_nlp_batch
        posts = enrich_nlp_batch(posts, max_comments=0, verbose=True)
        # max_comments=0 because X tweets don't have nested comment_texts
        print(f"\n   ✅ NLP enrichment complete — {len(posts)} posts processed")

    except ImportError as e:
        print(f"   ⚠️  NLP enricher import failed: {e}")
        print("   Make sure the nlp/ folder exists with all 4 files:")
        print("     nlp/__init__.py")
        print("     nlp/nlp_engine.py")
        print("     nlp/brandpulse_nlp_enricher.py")
        print("     nlp/keyword_lexicons.py")
        print("   And install: pip install langdetect transformers torch")

    return posts


def generate_batch_summary(posts: list) -> dict:
    """
    Generate aggregate stats across the full batch.
    Extended for X-specific fields: retweets, reply_count.
    """
    print(f"\n{'='*60}")
    print("📊 STAGE 4: Batch Summary")
    print(f"{'='*60}")

    from collections import Counter

    summary = {
        "platform": "twitter",
        "total_posts": len(posts),
        "timestamp": datetime.now().isoformat(),
    }

    # ── Sentiment distribution ──
    scores = [p.get("sentiment_score", 0) for p in posts
              if p.get("sentiment_score") is not None]
    if scores:
        summary["overall_sentiment_avg"] = round(sum(scores) / len(scores), 4)
        summary["overall_sentiment_min"] = min(scores)
        summary["overall_sentiment_max"] = max(scores)
        positive = sum(1 for s in scores if s > 0.25)
        negative = sum(1 for s in scores if s < -0.25)
        neutral = len(scores) - positive - negative
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

    # ── Tone distribution ──
    tone_dist = Counter(p.get("tone", "unknown") for p in posts)
    summary["tone_distribution"] = dict(tone_dist)

    # ── High-intent posts ──
    high_intent = [p for p in posts
                   if (p.get("intent_level") or {}).get("level") == "high"]
    summary["high_intent_count"] = len(high_intent)
    summary["high_intent_usernames"] = [p.get("username", "?") for p in high_intent]

    # ── X-specific: top tweets by engagement ──
    def engagement(p):
        return (p.get("likes_count", 0) or 0) + \
               (p.get("retweets", 0) or 0) * 2 + \
               (p.get("replies", 0) or 0)

    top_tweets = sorted(posts, key=engagement, reverse=True)[:5]
    summary["top_tweets_by_engagement"] = [
        {
            "username": t.get("username"),
            "text_preview": (t.get("caption") or "")[:100],
            "likes": t.get("likes_count", 0),
            "retweets": t.get("retweets", 0),
            "replies": t.get("replies", 0),
        }
        for t in top_tweets
    ]

    # Print summary
    print(f"\n   📈 Sentiment avg: {summary.get('overall_sentiment_avg', 'N/A')}")
    if "sentiment_distribution" in summary:
        sd = summary["sentiment_distribution"]
        print(f"   📊 Distribution: +{sd['positive']} / ={sd['neutral']} / -{sd['negative']}")
    print(f"   🌍 Languages: {dict(lang_dist)}")
    print(f"   🎯 Tone: {dict(tone_dist)}")
    print(f"   🚨 High-intent posts: {summary['high_intent_count']}")
    if summary["top_tweets_by_engagement"]:
        top = summary["top_tweets_by_engagement"][0]
        print(f"   🏆 Top tweet: @{top['username']} "
              f"({top['likes']} ❤️  {top['retweets']} 🔁)")

    return summary


def save_outputs(posts: list, summary: dict, input_path: str, output_dir: str = None):
    """Save enriched JSON, CSV, and summary."""
    print(f"\n{'='*60}")
    print("💾 STAGE 5: Saving outputs")
    print(f"{'='*60}")

    if output_dir is None:
        output_dir = os.path.dirname(input_path) or "brandpulse_output"

    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    # Save enriched JSON
    json_path = os.path.join(output_dir, f"{base_name}_enriched_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2, ensure_ascii=False)
    print(f"   ✅ JSON: {json_path}")

    # Save enriched CSV (flatten nested fields)
    csv_path = os.path.join(output_dir, f"{base_name}_enriched_{timestamp}.csv")
    if posts:
        flat_posts = []
        for post in posts:
            flat = {}
            for key, value in post.items():
                if isinstance(value, (list, dict)):
                    flat[key] = json.dumps(value, ensure_ascii=False)
                else:
                    flat[key] = value
            flat_posts.append(flat)

        fieldnames = list(flat_posts[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(flat_posts)
        print(f"   ✅ CSV: {csv_path}")

    # Save summary
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

            nlp_update = {
                "language_detected":    post.get("language_detected"),
                "sentiment_score":      post.get("sentiment_score"),
                "sentiment_magnitude":  post.get("sentiment_magnitude"),
                "sentiment_label":      post.get("sentiment_label"),
                "tone":                 post.get("tone"),
                "positive_keywords":    json.dumps(post.get("positive_keywords", [])),
                "negative_keywords":    json.dumps(post.get("negative_keywords", [])),
                "comment_sentiment_avg": post.get("comment_sentiment_avg"),
                # X-specific fields
                "retweets":             post.get("retweets"),
                "replies":              post.get("replies"),
                "platform":             "twitter",
            }

            try:
                client.table("posts").update(nlp_update).eq("post_id", post_id).execute()
                print(f"   ✅ [{i+1}/{len(posts)}] @{post.get('username', '?')}")
            except Exception as e:
                print(f"   ⚠️  [{i+1}/{len(posts)}] Error: {e}")

        print(f"\n   ✅ Supabase push complete")

    except ImportError:
        print("   ⚠️  supabase not installed. Run: pip install supabase")


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="BrandPulse X Enrichment Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_json", help="Path to normalized X scrape JSON")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--skip-nlp", action="store_true", help="Skip NLP stage")
    parser.add_argument("--skip-v1", action="store_true", help="Skip V1 enricher")
    parser.add_argument("--skip-v2", action="store_true", help="Skip V2 enricher")
    parser.add_argument("--supabase", action="store_true", help="Push to Supabase")
    args = parser.parse_args()

    if not os.path.isfile(args.input_json):
        print(f"❌ File not found: {args.input_json}")
        sys.exit(1)

    print("=" * 60)
    print("🚀 BrandPulse X Enrichment Pipeline")
    print("=" * 60)
    print(f"   Input:  {args.input_json}")
    print(f"   Stages: V1={'skip' if args.skip_v1 else 'run'}, "
          f"V2={'skip' if args.skip_v2 else 'run'}, "
          f"NLP={'skip' if args.skip_nlp else 'run'}")

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
    print(f"{'='*60}")
    print(f"   📄 Enriched JSON: {json_path}")
    print(f"   📊 Enriched CSV:  {csv_path}")
    print(f"   📈 Summary:       {summary_path}")


if __name__ == "__main__":
    main()