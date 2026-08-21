"""
BrandPulse POC Demo
====================
Google Search → URL Discovery → Instagram Enrichment → JSON + CSV

HOW TO USE:
  1. Edit the configuration block below (lines marked with ←)
  2. Run: python run_poc_demo.py

The demo runs in two phases:
  Phase 1: Google search discovers post URLs (browser opens Google)
  Phase 2: Instagram scraper enriches each post (browser opens Instagram)
"""

import json
import os
import csv
import time
import random
from datetime import datetime
from google_discovery_poc import discover_instagram_posts
from instagram_scraper_python import InstagramScraperEnhanced


# ================================================================
# ▼▼▼  CONFIGURATION — CHANGE THESE FOR EACH RUN  ▼▼▼
# ================================================================

CLIENT_NAME = "isuzu_kenya_integration_test"                    # ← client identifier

HASHTAGS = [                                       # ← hashtags to scrape
    "isuzukenya",
    "isuzudmax",
]

DATE_FROM = datetime(2025, 2, 1)                   # ← start date (inclusive)
DATE_TO   = datetime(2025, 3, 1)                  # ← end date (inclusive)

# 'monthly' for most hashtags
# 'weekly'  if you expect 300+ posts/month under the hashtag
WINDOW_SIZE = 'monthly'                            # ← 'monthly' or 'weekly'

# Maximum posts to discover per query per date window
# 50 = 5 Google pages × 10 results per page
# Increase to 300 (30 pages) or decrease to 100 (10 pages) as needed
MAX_POSTS_PER_QUERY = 50                          # ← posts per query window

# Seconds between Instagram post enrichments (don't go below 10)
ENRICHMENT_DELAY = 17                              # ← seconds between posts

# Show browser windows during discovery and enrichment
# True = faster but invisible   False = you can watch it (good for demos)
HEADLESS = False                                   # ← True or False

OUTPUT_DIR = "./brandpulse_output"                 # ← output folder

# ================================================================
# ▲▲▲  END OF CONFIGURATION  ▲▲▲
# ================================================================


os.makedirs(OUTPUT_DIR, exist_ok=True)

# Convert MAX_POSTS_PER_QUERY to pages (Google returns 10 per page)
MAX_PAGES = MAX_POSTS_PER_QUERY // 10


# ----------------------------------------------------------------
# PHASE 1 — DISCOVER POST URLs VIA GOOGLE
# ----------------------------------------------------------------

print("\n" + "=" * 60)
print("PHASE 1: GOOGLE URL DISCOVERY")
print("=" * 60)
print(f"  Client:         {CLIENT_NAME}")
print(f"  Hashtags:       {', '.join('#' + h for h in HASHTAGS)}")
print(f"  Date range:     "
      f"{DATE_FROM.strftime('%d %b %Y')} → {DATE_TO.strftime('%d %b %Y')}")
print(f"  Window size:    {WINDOW_SIZE}")
print(f"  Max posts/query: {MAX_POSTS_PER_QUERY} ({MAX_PAGES} pages × 10)")

all_posts = []
seen_shortcodes = set()

for hashtag in HASHTAGS:
    posts = discover_instagram_posts(
        hashtag=hashtag,
        date_from=DATE_FROM,
        date_to=DATE_TO,
        window_size=WINDOW_SIZE,
        max_pages_per_window=MAX_PAGES,
        headless=HEADLESS,
    )

    added = 0
    for post in posts:
        if post['shortcode'] not in seen_shortcodes:
            seen_shortcodes.add(post['shortcode'])
            all_posts.append(post)
            added += 1

    print(f"\n  #{hashtag}: {added} unique posts added "
          f"(running total: {len(all_posts)})")

print(f"\n✅ PHASE 1 COMPLETE")
print(f"   Total unique posts to enrich: {len(all_posts)}")

# Save discovered URLs immediately — if Phase 2 crashes you
# can reload this file and skip Phase 1 on retry
urls_backup = os.path.join(OUTPUT_DIR, f"{CLIENT_NAME}_urls_backup.json")
with open(urls_backup, 'w') as f:
    json.dump(all_posts, f, indent=2)
print(f"   URLs backed up to: {urls_backup}")

if not all_posts:
    print("\n⚠️  No posts discovered. Check:")
    print("   - Hashtags are spelled correctly")
    print("   - Date range contains actual posts")
    print("   - Google profile is not blocked (check browser window)")
    raise SystemExit(0)


# ----------------------------------------------------------------
# PHASE 2 — ENRICH EACH POST VIA INSTAGRAM SCRAPER
# ----------------------------------------------------------------

est_minutes = (len(all_posts) * ENRICHMENT_DELAY) // 60

print("\n" + "=" * 60)
print("PHASE 2: INSTAGRAM POST ENRICHMENT")
print("=" * 60)
print(f"  Posts to enrich:  {len(all_posts)}")
print(f"  Delay per post:   {ENRICHMENT_DELAY}s")
print(f"  Estimated time:   ~{est_minutes} minutes")

scraper = InstagramScraperEnhanced(headless=HEADLESS)
results = []
failed = []

try:
    for i, post in enumerate(all_posts, 1):
        print(f"\n[{i:3d}/{len(all_posts)}] "
              f"#{post['hashtag']} | {post['shortcode']}")

        try:
            enriched = scraper.enrich_post(post['url'], comment_limit=1000)

            # Attach discovery metadata to enriched result
            enriched['source_hashtag']   = post['hashtag']
            enriched['source_query']     = post['source_query']
            enriched['source_window']    = post['source_window']
            enriched['discovery_method'] = 'google_serp_poc'
            enriched['client']           = CLIENT_NAME

            results.append(enriched)

            # Print one-line summary per post
            date_str = (enriched.get('post_date') or '')[:10]
            print(
                f"   ✅ @{enriched.get('username', '?')} | "
                f"{enriched.get('likes', 0)} likes | "
                f"{enriched.get('comments', 0)} comments | "
                f"{date_str}"
            )

        except Exception as e:
            print(f"   ❌ Failed: {e}")
            failed.append({
                'url':        post['url'],
                'shortcode':  post['shortcode'],
                'hashtag':    post['hashtag'],
                'error':      str(e),
                'failed_at':  datetime.now().isoformat(),
            })

        # Rate limiting between posts — skip after the last one
        if i < len(all_posts):
            delay = ENRICHMENT_DELAY * random.uniform(0.7, 1.3)
            print(f"   ⏳ {delay:.0f}s...")
            time.sleep(delay)

finally:
    scraper.close()


# ----------------------------------------------------------------
# PHASE 3 — SAVE OUTPUT
# ----------------------------------------------------------------

print("\n" + "=" * 60)
print("PHASE 3: SAVING OUTPUT")
print("=" * 60)

ts = datetime.now().strftime('%Y%m%d_%H%M%S')

# Full JSON — unchanged, keep as-is
json_file = os.path.join(OUTPUT_DIR, f"{CLIENT_NAME}_{ts}.json")
with open(json_file, 'w', encoding='utf-8') as f:
    json.dump(
        {
            'client':              CLIENT_NAME,
            'hashtags':            HASHTAGS,
            'date_from':           DATE_FROM.isoformat(),
            'date_to':             DATE_TO.isoformat(),
            'window_size':         WINDOW_SIZE,
            'max_posts_per_query': MAX_POSTS_PER_QUERY,
            'run_at':              datetime.now().isoformat(),
            'total_discovered':    len(all_posts),
            'total_enriched':      len(results),
            'total_failed':        len(failed),
            'posts':               results,
            'failed':              failed,
        },
        f, indent=2, ensure_ascii=False, default=str,
    )

# CSV — one row per post, comments grouped as JSON in one column
csv_file = os.path.join(OUTPUT_DIR, f"{CLIENT_NAME}_{ts}.csv")

CSV_FIELDS = [
    'post_url',
    'post_date',
    'username',
    'author_name',
    'is_verified',
    'follower_count',
    'source_hashtag',
    'post_type',
    'likes',
    'comments',
    'engagement_rate',
    'location',
    'location_source',
    'caption',
    'hashtags',
    'source_window',
    'comments_json',   # ← all comments for this post, as a JSON string
]

if results:
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=CSV_FIELDS, extrasaction='ignore'
        )
        writer.writeheader()

        for r in results:
            row = {}

            # Scalar fields — copy directly
            for field in CSV_FIELDS:
                row[field] = r.get(field, '')

            # Flatten list fields
            if isinstance(row.get('hashtags'), list):
                row['hashtags'] = ', '.join(row['hashtags'])

            # Truncate caption
            if row.get('caption'):
                row['caption'] = str(row['caption'])[:300]

            # ── Comments: serialise the full list as a JSON string ────
            # Each element: {author, text, position, like_count,
            #                reply_count, created_at, author_verified}
            # Grouped under the post URL so they stay together when
            # the CSV is loaded into pandas or the Supabase pipeline.
            comment_texts = r.get('comment_texts', [])
            if comment_texts:
                row['comments_json'] = json.dumps(
                    comment_texts,
                    ensure_ascii=False
                )
            else:
                row['comments_json'] = '[]'

            writer.writerow(row)

print(f"\n🎉 POC COMPLETE")
print(f"   Discovered:  {len(all_posts):,} posts")
print(f"   Enriched:    {len(results):,} posts")
print(f"   Failed:      {len(failed):,} posts")
print(f"   JSON:        {json_file}")
if results:
    print(f"   CSV:         {csv_file}")