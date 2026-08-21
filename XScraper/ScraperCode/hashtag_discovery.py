"""
BrandPulse Hashtag Discovery & Batch Enrichment Pipeline
=========================================================
This module sits ON TOP of your existing InstagramScraperEnhanced.

Pipeline:
    [Hashtag] → [Explore Page] → [Post URLs] → [enrich_post() each] → [JSON + CSV]

It handles:
    1. Navigating to Instagram's hashtag explore page
    2. Extracting Top Posts (algorithmically ranked by Instagram)
    3. Scrolling to collect Recent Posts (reverse chronological)
    4. Deduplicating post URLs
    5. Feeding each URL into your existing enrich_post() method
    6. Aggregating results into BrandPulse-ready JSON and CSV files
    7. Rate limiting with human-like random delays

Usage:
    from hashtag_discovery import HashtagDiscovery
    from instagram_scraper_enhanced_geo import InstagramScraperEnhanced

    cookies = {
        'sessionid': 'YOUR_SESSION_ID',
        'ds_user_id': 'YOUR_USER_ID',
        'csrftoken': 'YOUR_CSRF_TOKEN'
    }

    # Initialize your existing scraper
    scraper = InstagramScraperEnhanced(cookies=cookies, headless=False)

    # Initialize the hashtag discovery layer
    discovery = HashtagDiscovery(scraper)

    # Scrape a hashtag — collects posts then enriches each one
    results = discovery.scrape_hashtag(
        hashtag='isuzukenya',
        max_top_posts=9,        # Instagram shows ~9 top posts
        max_recent_posts=20,    # How many recent posts to scroll for
        delay_between_posts=15  # Seconds between enrichment calls
    )

    # Scrape multiple hashtags in one run
    results = discovery.scrape_multiple_hashtags(
        hashtags=['isuzukenya', 'isuzudmax', 'isuzumux'],
        max_recent_posts=15,
        delay_between_posts=15
    )

    # Always close when done
    scraper.close()

Dependencies:
    - instagram_scraper_enhanced_geo.py (your existing scraper)
    - selenium, requests (already required by the scraper)
"""

import os
import csv
import json
import time
import random
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from selenium.webdriver.common.by import By

# Import your existing scraper
from instagram_scraper_python import InstagramScraperEnhanced


class HashtagDiscovery:
    """
    Discovers posts under Instagram hashtags and enriches them
    using the existing InstagramScraperEnhanced pipeline.
    """

    def __init__(self, scraper: InstagramScraperEnhanced, output_dir: str = "./brandpulse_output"):
        """
        Args:
            scraper: An initialized InstagramScraperEnhanced instance.
                     The scraper handles browser setup and authentication.
            output_dir: Directory where JSON and CSV results are saved.
        """
        self.scraper = scraper
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ============================================================
    # STEP 1: NAVIGATE TO HASHTAG PAGE
    # ============================================================

    def _navigate_to_hashtag(self, hashtag: str) -> bool:
        """
        Navigate to Instagram's hashtag explore page.

        Instagram URL format: https://www.instagram.com/explore/tags/{hashtag}/

        The page has two sections:
        - Top Posts: ~9 posts that Instagram's algorithm ranks as most engaging
        - Recent Posts: Reverse chronological, loaded via infinite scroll

        Args:
            hashtag: The hashtag to search (without the # symbol)

        Returns:
            True if page loaded successfully, False if blocked/redirected
        """
        # Strip the # if the user included it
        hashtag = hashtag.lstrip('#').strip().lower()

        url = f"https://www.instagram.com/explore/tags/{hashtag}/"
        print(f"\n{'='*60}")
        print(f"🔎 HASHTAG DISCOVERY: #{hashtag}")
        print(f"{'='*60}")
        print(f"   URL: {url}")

        # Ensure browser is initialized
        if not self.scraper.driver:
            self.scraper._setup_driver()

        driver = self.scraper.driver

        print("   ⏳ Navigating to hashtag page...")
        driver.get(url)

        # Wait for the page to load — Instagram's JS needs time to render the grid
        time.sleep(random.uniform(5, 8))

        # Check if we got redirected to login (expired cookies)
        if '/accounts/login' in driver.current_url:
            print("   ❌ Redirected to login! Cookies may be expired.")
            return False

        # Check if the hashtag page actually loaded
        # Instagram shows "Sorry, this page isn't available" for invalid hashtags
        page_text = driver.find_element(By.TAG_NAME, 'body').text
        if "Sorry, this page isn't available" in page_text:
            print(f"   ❌ Hashtag #{hashtag} not found or page unavailable")
            return False

        # Close any popups (notifications prompt, cookie consent, etc.)
        self.scraper._close_popups()

        print(f"   ✅ Hashtag page loaded: #{hashtag}")
        driver.save_screenshot("debug_hashtag_page.png")
        print("   📸 Screenshot saved to debug_hashtag_page.png")
        return True

    # ============================================================
    # STEP 2: EXTRACT TOP POSTS
    # ============================================================

    def _extract_top_posts(self, max_posts: int = 9) -> List[str]:
        """
        Extract post URLs from the "Top Posts" section.

        How this works:
        - Instagram's hashtag page shows the top ~9 posts in a grid at the top.
        - Each post is an <a> tag with href like "/p/{shortcode}/" or "/reel/{shortcode}/"
        - The top posts section is usually the first set of grid items before the
          "Most recent" divider.

        Instagram's DOM structure (as of 2025):
        - Posts are inside <article> or main content divs
        - Each thumbnail is wrapped in an <a> tag
        - The href contains /p/ (photos/carousels) or /reel/ (reels)

        Args:
            max_posts: Maximum top posts to collect (Instagram shows ~9)

        Returns:
            List of full Instagram post URLs
        """
        print(f"\n📌 STEP 2: EXTRACTING TOP POSTS (max: {max_posts})")
        driver = self.scraper.driver

        top_urls = []
        seen = set()

        try:
            # Strategy 1: Find all post links in the page
            # The top posts appear first in the DOM before recent posts
            links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="/reel/"]')

            for link in links:
                if len(top_urls) >= max_posts:
                    break

                href = link.get_attribute('href')
                if not href:
                    continue

                # Normalize the URL
                # href could be "/p/ABC123/" or "https://www.instagram.com/p/ABC123/"
                if href.startswith('/'):
                    full_url = f"https://www.instagram.com{href}"
                else:
                    full_url = href

                # Extract the shortcode to use as unique identifier
                shortcode_match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', full_url)
                if not shortcode_match:
                    continue

                shortcode = shortcode_match.group(1)

                # Deduplicate — same post can appear multiple times in DOM
                if shortcode in seen:
                    continue
                seen.add(shortcode)

                # Normalize URL format
                if '/reel/' in full_url:
                    clean_url = f"https://www.instagram.com/reel/{shortcode}/"
                else:
                    clean_url = f"https://www.instagram.com/p/{shortcode}/"

                top_urls.append(clean_url)

            print(f"   ✅ Found {len(top_urls)} top posts")
            for i, url in enumerate(top_urls, 1):
                shortcode = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', url).group(1)
                print(f"      {i}. {shortcode}")

        except Exception as e:
            print(f"   ❌ Top post extraction failed: {e}")

        return top_urls

    # ============================================================
    # STEP 3: SCROLL FOR RECENT POSTS
    # ============================================================

    def _extract_recent_posts(self, max_posts: int = 20, max_scrolls: int = 15) -> List[str]:
        """
        Scroll the page to load and extract "Most Recent" posts.

        How Instagram's infinite scroll works:
        1. The page initially shows the top posts + first batch of recent posts.
        2. As you scroll down, Instagram's JavaScript makes XHR requests to
           fetch more posts and injects new <a> tags into the DOM.
        3. Each scroll batch typically adds 12-24 new posts.
        4. Instagram eventually stops loading new posts (either you hit their
           limit or there are no more posts for that hashtag).

        The scroll strategy:
        - Scroll to the bottom of the page
        - Wait 2-4 seconds for new content to load
        - Count how many new post links appeared
        - If no new links after 2 consecutive scrolls, stop (end of content)
        - Also stop if we've hit max_posts or max_scrolls

        Args:
            max_posts: Target number of recent posts to collect
            max_scrolls: Maximum scroll attempts before giving up

        Returns:
            List of full Instagram post URLs (deduplicated)
        """
        print(f"\n📜 STEP 3: SCROLLING FOR RECENT POSTS (target: {max_posts}, max scrolls: {max_scrolls})")
        driver = self.scraper.driver

        all_urls = []
        seen_shortcodes = set()
        no_new_count = 0  # Consecutive scrolls with no new posts

        # First, collect everything already on the page
        # (includes top posts — we'll separate them later)
        initial_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="/reel/"]')
        for link in initial_links:
            href = link.get_attribute('href')
            if href:
                match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', href)
                if match:
                    seen_shortcodes.add(match.group(1))

        print(f"   📊 Posts already on page: {len(seen_shortcodes)}")

        for scroll_num in range(1, max_scrolls + 1):
            if len(all_urls) >= max_posts:
                print(f"   ✅ Reached target ({max_posts} posts)")
                break

            # Scroll to bottom
            # Using scrollTo(0, document.body.scrollHeight) triggers Instagram's
            # lazy loading mechanism, which watches for scroll events
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # Human-like random delay — Instagram's anti-bot looks for consistent timing
            delay = random.uniform(2.5, 4.5)
            time.sleep(delay)

            # Count new posts that appeared after the scroll
            current_links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="/reel/"]')
            new_count = 0

            for link in current_links:
                href = link.get_attribute('href')
                if not href:
                    continue

                match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', href)
                if not match:
                    continue

                shortcode = match.group(1)

                if shortcode not in seen_shortcodes:
                    seen_shortcodes.add(shortcode)
                    new_count += 1

                    if '/reel/' in href:
                        url = f"https://www.instagram.com/reel/{shortcode}/"
                    else:
                        url = f"https://www.instagram.com/p/{shortcode}/"

                    all_urls.append(url)

                    if len(all_urls) >= max_posts:
                        break

            print(f"   📜 Scroll {scroll_num}/{max_scrolls}: +{new_count} new posts (total: {len(all_urls)})")

            # If no new posts loaded after scrolling, Instagram may have hit the end
            if new_count == 0:
                no_new_count += 1
                if no_new_count >= 2:
                    print(f"   ℹ️  No new posts after {no_new_count} scrolls — end of content")
                    break
            else:
                no_new_count = 0

            # Extra random micro-delay to seem more human
            time.sleep(random.uniform(0.5, 1.5))

        print(f"   ✅ Collected {len(all_urls)} recent posts total")
        return all_urls

    # ============================================================
    # STEP 4: DEDUPLICATE & MERGE
    # ============================================================

    def _merge_and_deduplicate(
        self,
        top_posts: List[str],
        recent_posts: List[str]
    ) -> Tuple[List[Dict], int]:
        """
        Merge top and recent posts, deduplicate, and tag each with its source.

        Why separate top vs recent?
        - Top posts have high engagement → useful for understanding what resonates
        - Recent posts show current activity → useful for real-time brand monitoring
        - BrandPulse reports can segment insights by post category

        The deduplication uses shortcodes as unique keys. A post can appear in
        both top and recent — when that happens, we tag it as 'top' (higher value).

        Args:
            top_posts: URLs from the Top Posts section
            recent_posts: URLs from scrolling the Recent section

        Returns:
            Tuple of (list of {url, category, shortcode} dicts, total unique count)
        """
        print(f"\n🔗 STEP 4: DEDUPLICATING")

        seen = {}  # shortcode → {url, category}
        merged = []

        # Top posts get priority
        for url in top_posts:
            match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', url)
            if match:
                sc = match.group(1)
                if sc not in seen:
                    entry = {'url': url, 'category': 'top', 'shortcode': sc}
                    seen[sc] = entry
                    merged.append(entry)

        # Recent posts — only add if not already in top
        for url in recent_posts:
            match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', url)
            if match:
                sc = match.group(1)
                if sc not in seen:
                    entry = {'url': url, 'category': 'recent', 'shortcode': sc}
                    seen[sc] = entry
                    merged.append(entry)

        top_count = sum(1 for m in merged if m['category'] == 'top')
        recent_count = sum(1 for m in merged if m['category'] == 'recent')

        print(f"   ✅ {len(merged)} unique posts ({top_count} top + {recent_count} recent)")
        return merged, len(merged)

    # ============================================================
    # STEP 5: BATCH ENRICHMENT
    # ============================================================

    def _enrich_batch(
        self,
        posts: List[Dict],
        hashtag: str,
        delay_between_posts: int = 15
    ) -> List[Dict]:
        """
        Run enrich_post() on each collected URL.

        Rate limiting strategy:
        - Wait 10-20 seconds between posts (randomized around delay_between_posts)
        - This simulates a real user browsing through posts
        - Instagram typically allows ~100-200 page loads per hour before throttling
        - At 15s average delay, that's ~240 posts/hour — at the edge of safe

        Error handling:
        - Each post enrichment is wrapped in try/except
        - If one post fails (e.g. deleted post, private account), we log it and continue
        - The failure doesn't kill the entire batch

        Args:
            posts: List of {url, category, shortcode} dicts from Step 4
            hashtag: The hashtag being scraped (added to each result for tracking)
            delay_between_posts: Average seconds between enrichment calls

        Returns:
            List of enriched post data dicts (your existing format + extras)
        """
        print(f"\n{'='*60}")
        print(f"⚡ STEP 5: BATCH ENRICHMENT ({len(posts)} posts)")
        print(f"{'='*60}")
        print(f"   Estimated time: ~{len(posts) * delay_between_posts // 60} minutes")
        print(f"   Average delay: {delay_between_posts}s between posts\n")

        results = []
        failed = []

        for i, post in enumerate(posts, 1):
            url = post['url']
            category = post['category']
            shortcode = post['shortcode']

            print(f"\n{'─'*40}")
            print(f"📸 Post {i}/{len(posts)} [{category.upper()}]: {shortcode}")
            print(f"{'─'*40}")

            try:
                # Call your existing enrichment pipeline
                # This runs all extraction methods + geolocation enrichment
                enriched = self.scraper.enrich_post(url)

                # Add BrandPulse metadata
                enriched['hashtag_source'] = f"#{hashtag}"
                enriched['post_category'] = category  # 'top' or 'recent'
                enriched['shortcode'] = shortcode
                enriched['discovery_timestamp'] = datetime.now().isoformat()

                results.append(enriched)
                print(f"   ✅ Enriched successfully")

            except Exception as e:
                print(f"   ❌ FAILED: {e}")
                failed.append({
                    'url': url,
                    'shortcode': shortcode,
                    'category': category,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

            # Rate limiting delay (skip after last post)
            if i < len(posts):
                # Randomize ±30% around the base delay
                jitter = delay_between_posts * 0.3
                actual_delay = random.uniform(
                    delay_between_posts - jitter,
                    delay_between_posts + jitter
                )
                print(f"   ⏳ Waiting {actual_delay:.1f}s before next post...")
                time.sleep(actual_delay)

        print(f"\n{'='*60}")
        print(f"📊 BATCH ENRICHMENT COMPLETE")
        print(f"   ✅ Succeeded: {len(results)}/{len(posts)}")
        print(f"   ❌ Failed: {len(failed)}/{len(posts)}")
        print(f"{'='*60}")

        return results, failed

    # ============================================================
    # STEP 6: SAVE RESULTS (JSON + CSV)
    # ============================================================

    def _save_results(
        self,
        results: List[Dict],
        failed: List[Dict],
        hashtag: str
    ) -> Tuple[str, str]:
        """
        Save enriched data to JSON (full detail) and CSV (tabular summary).

        Two output formats:

        1. JSON — Full detail for BrandPulse's database/API
           Contains everything: captions, comments, geo signals, etc.
           Used by: Backend ingestion, Supabase import, detailed analysis

        2. CSV — Flat tabular summary for dashboards and quick analysis
           One row per post with key metrics.
           Used by: Excel/Google Sheets, dashboard widgets, monthly reports

        File naming convention:
            brandpulse_{hashtag}_{YYYYMMDD_HHMMSS}.json
            brandpulse_{hashtag}_{YYYYMMDD_HHMMSS}.csv

        Args:
            results: List of enriched post dicts
            failed: List of failed post dicts
            hashtag: The hashtag that was scraped

        Returns:
            Tuple of (json_path, csv_path)
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f"brandpulse_{hashtag}_{timestamp}"

        # ---- JSON: Full detail ----
        json_path = os.path.join(self.output_dir, f"{base_name}.json")

        json_output = {
            'metadata': {
                'hashtag': f"#{hashtag}",
                'scraped_at': datetime.now().isoformat(),
                'total_posts_found': len(results) + len(failed),
                'posts_enriched': len(results),
                'posts_failed': len(failed),
                'top_posts_count': sum(1 for r in results if r.get('post_category') == 'top'),
                'recent_posts_count': sum(1 for r in results if r.get('post_category') == 'recent'),
            },
            'posts': results,
            'failed': failed
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_output, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n📄 JSON saved: {json_path}")

        # ---- CSV: Flat summary ----
        csv_path = os.path.join(self.output_dir, f"{base_name}.csv")

        csv_fields = [
            'hashtag_source', 'post_category', 'post_url', 'shortcode',
            'post_type', 'post_date', 'username', 'author_name',
            'follower_count', 'following_count',
            'likes', 'comments', 'shares', 'views', 'engagement_rate',
            'location', 'location_source', 'location_confidence',
            'caption', 'hashtags', 'mentions',
            'comment_count_extracted', 'scraped_at'
        ]

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
            writer.writeheader()

            for result in results:
                row = {
                    'hashtag_source': result.get('hashtag_source', ''),
                    'post_category': result.get('post_category', ''),
                    'post_url': result.get('post_url', ''),
                    'shortcode': result.get('shortcode', ''),
                    'post_type': result.get('post_type', ''),
                    'post_date': result.get('post_date', ''),
                    'username': result.get('username', ''),
                    'author_name': result.get('author_name', ''),
                    'follower_count': result.get('follower_count', 0),
                    'following_count': result.get('following_count', 0),
                    'likes': result.get('likes', 0),
                    'comments': result.get('comments', 0),
                    'shares': result.get('shares', 0),
                    'views': result.get('views', ''),
                    'engagement_rate': result.get('engagement_rate', 0),
                    'location': result.get('location', ''),
                    'location_source': result.get('location_source', ''),
                    'location_confidence': result.get('location_confidence', 0),
                    # Flatten these for CSV
                    'caption': (result.get('caption', '') or '')[:500],  # Truncate long captions
                    'hashtags': ', '.join(result.get('hashtags', [])),
                    'mentions': ', '.join(result.get('mentions', [])),
                    'comment_count_extracted': len(result.get('comment_texts', [])),
                    'scraped_at': result.get('scraped_at', ''),
                }
                writer.writerow(row)

        print(f"📊 CSV saved: {csv_path}")
        return json_path, csv_path

    # ============================================================
    # MAIN PUBLIC METHODS
    # ============================================================

    def scrape_hashtag(
        self,
        hashtag: str,
        max_top_posts: int = 9,
        max_recent_posts: int = 20,
        max_scrolls: int = 15,
        delay_between_posts: int = 15
    ) -> Dict:
        """
        Full pipeline: discover posts under a hashtag and enrich each one.

        This is the main method you call. It runs all 6 steps:
        1. Navigate to hashtag page
        2. Extract top posts
        3. Scroll for recent posts
        4. Deduplicate and merge
        5. Enrich each post with your existing scraper
        6. Save results to JSON + CSV

        Args:
            hashtag: The hashtag to search (with or without #)
            max_top_posts: Max top posts to collect (Instagram shows ~9)
            max_recent_posts: Target number of recent posts from scrolling
            max_scrolls: Maximum scroll attempts before giving up
            delay_between_posts: Average seconds between post enrichments

        Returns:
            Dict with metadata, results, and file paths
        """
        hashtag = hashtag.lstrip('#').strip().lower()

        print(f"\n{'='*60}")
        print(f"🚀 BRANDPULSE HASHTAG PIPELINE: #{hashtag}")
        print(f"{'='*60}")
        print(f"   Config: {max_top_posts} top + {max_recent_posts} recent")
        print(f"   Delay: ~{delay_between_posts}s between posts")
        start_time = datetime.now()

        # Step 1: Navigate
        if not self._navigate_to_hashtag(hashtag):
            return {'success': False, 'error': 'Failed to load hashtag page'}

        # Step 2: Top posts
        top_posts = self._extract_top_posts(max_posts=max_top_posts)

        # Step 3: Recent posts (scroll)
        recent_posts = self._extract_recent_posts(
            max_posts=max_recent_posts,
            max_scrolls=max_scrolls
        )

        # Step 4: Deduplicate
        merged, total = self._merge_and_deduplicate(top_posts, recent_posts)

        if total == 0:
            print("   ❌ No posts found under this hashtag")
            return {'success': False, 'error': 'No posts found'}

        # Step 5: Enrich
        results, failed = self._enrich_batch(
            posts=merged,
            hashtag=hashtag,
            delay_between_posts=delay_between_posts
        )

        # Step 6: Save
        json_path, csv_path = self._save_results(results, failed, hashtag)

        elapsed = (datetime.now() - start_time).total_seconds()

        summary = {
            'success': True,
            'hashtag': f"#{hashtag}",
            'posts_discovered': total,
            'posts_enriched': len(results),
            'posts_failed': len(failed),
            'top_posts': sum(1 for r in results if r.get('post_category') == 'top'),
            'recent_posts': sum(1 for r in results if r.get('post_category') == 'recent'),
            'elapsed_seconds': round(elapsed),
            'elapsed_readable': f"{int(elapsed // 60)}m {int(elapsed % 60)}s",
            'json_path': json_path,
            'csv_path': csv_path,
            'results': results,
            'failed': failed
        }

        print(f"\n{'='*60}")
        print(f"🎉 PIPELINE COMPLETE: #{hashtag}")
        print(f"   Posts: {summary['posts_enriched']} enriched, {summary['posts_failed']} failed")
        print(f"   Time: {summary['elapsed_readable']}")
        print(f"   JSON: {json_path}")
        print(f"   CSV:  {csv_path}")
        print(f"{'='*60}\n")

        return summary

    def scrape_multiple_hashtags(
        self,
        hashtags: List[str],
        max_top_posts: int = 9,
        max_recent_posts: int = 15,
        max_scrolls: int = 10,
        delay_between_posts: int = 15,
        delay_between_hashtags: int = 30
    ) -> Dict:
        """
        Run the pipeline across multiple hashtags.

        Use this for BrandPulse monthly reports where you track multiple
        brand-related hashtags (e.g. #isuzukenya, #isuzudmax, #toyotakenya).

        Adds an extra delay between hashtags to avoid triggering Instagram's
        rate limiter on hashtag page loads.

        Args:
            hashtags: List of hashtags to scrape
            max_top_posts: Max top posts per hashtag
            max_recent_posts: Target recent posts per hashtag
            max_scrolls: Max scroll attempts per hashtag
            delay_between_posts: Seconds between post enrichments
            delay_between_hashtags: Seconds between finishing one hashtag and starting the next

        Returns:
            Combined summary dict with per-hashtag breakdowns
        """
        print(f"\n{'='*60}")
        print(f"🚀 BRANDPULSE MULTI-HASHTAG PIPELINE")
        print(f"{'='*60}")
        print(f"   Hashtags: {', '.join(f'#{h.lstrip(chr(35))}' for h in hashtags)}")
        print(f"   Config: {max_top_posts} top + {max_recent_posts} recent per hashtag")
        total_estimate = len(hashtags) * (max_top_posts + max_recent_posts) * delay_between_posts
        print(f"   Estimated time: ~{total_estimate // 60} minutes (worst case)")

        start_time = datetime.now()
        all_summaries = []
        total_enriched = 0
        total_failed = 0

        for i, hashtag in enumerate(hashtags, 1):
            print(f"\n\n{'🔷'*30}")
            print(f"HASHTAG {i}/{len(hashtags)}: #{hashtag.lstrip('#')}")
            print(f"{'🔷'*30}")

            summary = self.scrape_hashtag(
                hashtag=hashtag,
                max_top_posts=max_top_posts,
                max_recent_posts=max_recent_posts,
                max_scrolls=max_scrolls,
                delay_between_posts=delay_between_posts
            )

            all_summaries.append(summary)
            if summary.get('success'):
                total_enriched += summary.get('posts_enriched', 0)
                total_failed += summary.get('posts_failed', 0)

            # Delay between hashtags (skip after last)
            if i < len(hashtags):
                jitter = delay_between_hashtags * 0.3
                actual = random.uniform(delay_between_hashtags - jitter, delay_between_hashtags + jitter)
                print(f"\n⏳ Waiting {actual:.0f}s before next hashtag...")
                time.sleep(actual)

        elapsed = (datetime.now() - start_time).total_seconds()

        combined = {
            'success': True,
            'hashtags_scraped': len(hashtags),
            'total_posts_enriched': total_enriched,
            'total_posts_failed': total_failed,
            'elapsed_seconds': round(elapsed),
            'elapsed_readable': f"{int(elapsed // 60)}m {int(elapsed % 60)}s",
            'per_hashtag': all_summaries
        }

        print(f"\n{'='*60}")
        print(f"🎉 ALL HASHTAGS COMPLETE")
        print(f"   Hashtags: {len(hashtags)}")
        print(f"   Total enriched: {total_enriched}")
        print(f"   Total failed: {total_failed}")
        print(f"   Total time: {combined['elapsed_readable']}")
        print(f"{'='*60}\n")

        return combined


# ================================================================
# USAGE EXAMPLES
# ================================================================

if __name__ == "__main__":

    # ----- YOUR COOKIES -----
    cookies = {
        'sessionid': 'YOUR_SESSION_ID_HERE',
        'ds_user_id': 'YOUR_USER_ID_HERE',
        'csrftoken': 'YOUR_CSRF_TOKEN_HERE'
    }

    # ----- INITIALIZE -----
    scraper = InstagramScraperEnhanced(
        cookies=cookies,
        headless=False,
        claude_api_key=None  # Optional: set for visual geo analysis
    )

    discovery = HashtagDiscovery(
        scraper=scraper,
        output_dir='./brandpulse_output'
    )

    # ----- EXAMPLE 1: Single hashtag -----
    result = discovery.scrape_hashtag(
        hashtag='isuzukenya',
        max_top_posts=2,
        max_recent_posts=3,
        delay_between_posts=15
    )

    # ----- EXAMPLE 2: Multiple hashtags (BrandPulse monthly report) -----
    # result = discovery.scrape_multiple_hashtags(
    #     hashtags=[
    #         'isuzukenya',
    #         'isuzudmax',
    #         'isuzumux',
    #     ],
    #     max_top_posts=2,
    #     max_recent_posts=2,
    #     delay_between_posts=15,
    #     delay_between_hashtags=30
    # )

    # ----- CLEANUP -----
    scraper.close()

    print("\n📁 Output files are in ./brandpulse_output/")
    print("   - JSON files: Full data for Supabase/API import")
    print("   - CSV files:  Tabular summary for dashboards")