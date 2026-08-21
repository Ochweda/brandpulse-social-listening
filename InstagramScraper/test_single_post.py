"""
Single post comment extraction test.
Tests whether _extract_comment_texts can retrieve 100+ comments
and saves them to a CSV file for verification.

Usage: python test_single_post.py
"""

import json
import csv
import time
import os
from datetime import datetime
from instagram_scraper_python import InstagramScraperEnhanced

# ================================================================
# CONFIGURATION — change these
# ================================================================

# A post you know has many comments — find one manually first
# Good candidates: official brand posts, viral posts, posts with
# "View all X comments" link visible in Instagram
TEST_POST_URL = 'https://www.instagram.com/p/DVwHIu8jWnp/'

# How many comments to try to extract
# Set high to test the limit — the scraper will get as many as it can
COMMENT_LIMIT = 1000

OUTPUT_DIR = './brandpulse_output'

# ================================================================

os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"\n{'='*60}")
print(f"COMMENT EXTRACTION TEST")
print(f"URL: {TEST_POST_URL}")
print(f"Target: {COMMENT_LIMIT} comments")
print(f"{'='*60}\n")

scraper = InstagramScraperEnhanced(headless=False)

try:
    # Set up driver
    scraper._setup_driver()

    # Navigate to the post
    print("⏳ Loading post...")
    scraper.driver.get(TEST_POST_URL)
    time.sleep(7)
    scraper._close_popups()

    # Scroll to load comments
    scraper.driver.execute_script("window.scrollTo(0, 500);")
    time.sleep(2)

    # Extract with high limit
    print(f"\n💬 Extracting up to {COMMENT_LIMIT} comments...")
    comments = scraper._extract_comment_texts(limit=COMMENT_LIMIT)

    print(f"\n✅ RESULT: {len(comments)} comments extracted")

    # ── Save to CSV ──────────────────────────────────────────────
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = os.path.join(OUTPUT_DIR, f'comments_test_{ts}.csv')

    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['position', 'author', 'text'],
            extrasaction='ignore'
        )
        writer.writeheader()
        writer.writerows(comments)

    print(f"📊 CSV saved: {csv_path}")

    # ── Save to JSON ─────────────────────────────────────────────
    json_path = os.path.join(OUTPUT_DIR, f'comments_test_{ts}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'post_url': TEST_POST_URL,
            'target_limit': COMMENT_LIMIT,
            'extracted_count': len(comments),
            'comments': comments
        }, f, indent=2, ensure_ascii=False)

    print(f"📄 JSON saved: {json_path}")

    # ── Print summary ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"  Requested: {COMMENT_LIMIT}")
    print(f"  Extracted: {len(comments)}")
    if comments:
        print(f"  First comment: @{comments[0]['author']}: "
              f"{comments[0]['text'][:60]}...")
        print(f"  Last comment:  @{comments[-1]['author']}: "
              f"{comments[-1]['text'][:60]}...")
    print(f"{'='*60}\n")

finally:
    scraper.close()