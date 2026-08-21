"""
BrandPulse TikTok Scraper — Core Scraping Logic
=================================================
Uses Playwright XHR interception for video feeds, in-session navigation
for comments.

Video feeds (XHR interception):
    TikTok fires internal REST endpoints to load video feeds:
        Hashtag feed:  GET /api/challenge/item_list/
        Account feed:  GET /api/post/item_list/

Comment strategy (in-session navigation + DOM scraping):
    The root cause of ERR_ABORTED on video pages was cold navigation —
    Playwright opening a brand-new page and jumping directly to a video URL
    looks exactly like a bot to TikTok's WAF (no referrer, no session warm-up,
    no human-like timing).

    Fix: after the hashtag/account XHR collection finishes, we keep that
    SAME page alive and navigate to each video URL from within it. TikTok
    sees a continuous same-session, same-tab navigation (with a valid
    tiktok.com referrer) rather than cold fresh-page jumps. This matches
    what a real user does: browse the hashtag page, click a video, go back,
    click another.

    Comment extraction is two-stage:
        Stage 1 — rehydration blob (__UNIVERSAL_DATA_FOR_REHYDRATION__)
        Stage 2 — click Comments tab → wait for render → DOM scraping

Architecture:
    auth.py        CfT browser → BrowserContext
    scraper.py     XHR interception (feeds) + in-session navigation (comments)
    normalizer.py  raw video dicts → BrandPulse schema
    enrichers      BrandPulse schema → enriched output
"""

import asyncio
import json
import random
import sys
from datetime import datetime
from playwright.async_api import async_playwright, BrowserContext, Page, Response

from Scripts.auth import create_browser_context, check_maintenance_warning
from config import (
    TARGET_HASHTAGS, TARGET_ACCOUNTS,
    MAX_VIDEOS_PER_TARGET, MAX_COMMENTS_PER_VIDEO,
    MIN_COMMENT_LIKES, FETCH_COMMENTS,
    DELAY_BETWEEN_VIDEOS, DELAY_BETWEEN_COMMENTS,
    RATE_LIMIT_WAIT, MAX_RETRIES,
)


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1: XHR RESPONSE COLLECTOR
# ──────────────────────────────────────────────────────────────────────────────

async def _collect_xhr_responses(
    page: Page,
    url: str,
    endpoint_pattern: str,
    max_items: int,
    scroll_count: int = 6,
) -> list[dict]:
    """
    Navigate to a TikTok page and collect intercepted XHR JSON payloads
    matching endpoint_pattern.

    NOTE: Does NOT close the page — caller keeps it alive for in-session
    video navigation afterwards.
    """
    collected_items: list[dict] = []
    response_queue: asyncio.Queue = asyncio.Queue()

    async def handle_response(response: Response):
        if endpoint_pattern in response.url:
            try:
                body = await response.json()
                await response_queue.put(body)
            except Exception:
                pass

    page.on("response", handle_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3000 + random.uniform(0, 800))

        for scroll_num in range(scroll_count):
            while not response_queue.empty():
                data = await response_queue.get()
                items = data.get("itemList") or data.get("items") or []
                if items:
                    collected_items.extend(items)
                    print(
                        f"      [XHR] Batch {scroll_num + 1}: "
                        f"+{len(items)} items (total: {len(collected_items)})"
                    )

            if len(collected_items) >= max_items:
                break

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000 + random.uniform(0, 1000))

        await page.wait_for_timeout(1500)
        while not response_queue.empty():
            data = await response_queue.get()
            items = data.get("itemList") or data.get("items") or []
            if items:
                collected_items.extend(items)

    except Exception as e:
        print(f"      [XHR] Navigation/collection error for {url}: {e}")
    finally:
        page.remove_listener("response", handle_response)

    return collected_items[:max_items]


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2: REHYDRATION DATA EXTRACTOR
# ──────────────────────────────────────────────────────────────────────────────

async def _extract_rehydration_comments(
    page: Page,
    author_username: str,
) -> list[dict]:
    """
    Extract pre-loaded comments from TikTok's __UNIVERSAL_DATA_FOR_REHYDRATION__.

    Tries window object first (richer), then the script tag as fallback.
    Attempts two known paths through the JSON blob:
        1. videoDetail.itemInfo.itemStruct  (primary)
        2. itemInfo.itemStruct              (fallback)
    """
    try:
        raw_json = await page.evaluate("""
            () => {
                if (window.__UNIVERSAL_DATA_FOR_REHYDRATION__) {
                    return JSON.stringify(window.__UNIVERSAL_DATA_FOR_REHYDRATION__);
                }
                const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                return el ? el.textContent : null;
            }
        """)

        if not raw_json:
            return []

        blob = json.loads(raw_json)
        scope = blob.get("__DEFAULT_SCOPE__", {})
        vd    = scope.get("webapp.video-detail", {})

        # Path 1
        item_struct = (
            vd.get("videoDetail", {})
              .get("itemInfo", {})
              .get("itemStruct", {})
        )
        # Path 2 fallback
        if not item_struct:
            item_struct = (
                vd.get("itemInfo", {})
                  .get("itemStruct", {})
            )

        comment_list = item_struct.get("commentList", [])
        if not comment_list:
            return []

        comments = []
        for c in comment_list:
            c_author   = c.get("user", {}).get("unique_id", "")
            like_count = int(c.get("digg_count", 0) or 0)
            if c_author.lower() == author_username.lower():
                continue
            if like_count < MIN_COMMENT_LIKES:
                continue
            comments.append({
                "author": c_author,
                "text":   c.get("text", ""),
                "likes":  like_count,
            })
        return comments

    except Exception as e:
        print(f"      [Rehydration] Parse error: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 3: DOM COMMENT SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

async def _scrape_comments_from_dom(page: Page, author_username: str) -> list[dict]:
    """
    Scrape comments using data-e2e="comment-level-1" — confirmed present in
    DevTools Elements panel (span wrapping each comment text).

    Also confirmed from DevTools:
        data-e2e="comment-level-1"  — the comment text span itself (confirmed)
        username links: <a href="/@username"> inside each comment wrapper

    We find comment-level-1 spans, walk up to the item wrapper, then extract
    username from the nearest <a href="/@..."> and like count from adjacent numbers.
    """
    try:
        comments_raw = await page.evaluate("""
            () => {
                const results = [];

                // data-e2e="comment-level-1" confirmed in DevTools Elements panel
                const textEls = document.querySelectorAll('[data-e2e="comment-level-1"]');
                if (!textEls.length) return results;

                textEls.forEach(textEl => {
                    try {
                        const text = textEl.innerText.trim();
                        if (!text) return;

                        // Walk up to comment item wrapper
                        let wrapper = textEl;
                        for (let i = 0; i < 8; i++) {
                            if (!wrapper.parentElement) break;
                            wrapper = wrapper.parentElement;
                            // Stop when wrapper contains a user profile link
                            if (wrapper.querySelector('a[href*="/@"]')) break;
                        }

                        // Extract author from profile link href: /@username
                        let author = '';
                        const link = wrapper.querySelector('a[href*="/@"]');
                        if (link) {
                            const m = link.href.match(/\/@([^/?&#]+)/);
                            if (m) author = m[1];
                        }

                        // Like count: find number spans/strongs near wrapper
                        let likes = 0;
                        const numEls = wrapper.querySelectorAll('strong, span');
                        for (const el of numEls) {
                            const raw = (el.innerText || '').trim();
                            const m = raw.match(/^(\d+(?:\.\d+)?)[KkMm]?$/);
                            if (m) {
                                let n = parseFloat(m[1]);
                                if (/[Kk]/.test(raw)) n *= 1000;
                                if (/[Mm]/.test(raw)) n *= 1000000;
                                if (n > likes && n < 10000000) likes = Math.round(n);
                            }
                        }

                        results.push({ author, text, likes });
                    } catch (e) {}
                });

                return results;
            }
        """)
        return comments_raw or []
    except Exception as e:
        print(f"      [DOM] Scrape error: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 4: IN-SESSION COMMENT FETCHER
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_comments_in_session(
    page: Page,
    video_id: str,
    author_username: str,
    return_url: str,
) -> list[dict]:
    """
    Fetch comments by navigating the EXISTING page to the video URL.

    Why in-session navigation fixes ERR_ABORTED:
        Cold navigation (new page → goto video URL) produces:
            - No Referer header
            - No browsing history on this domain
            - Immediate cold-start fingerprint
        TikTok's 2026 WAF aborts these aggressively.

        Navigating the SAME page that just loaded the hashtag/account feed
        produces:
            - Referer: https://www.tiktok.com/tag/{hashtag} (set automatically)
            - Existing session cookies already accepted
            - Natural click-then-navigate timing

    After comment collection, navigates back to return_url so subsequent
    video navigations also carry a valid tiktok.com referrer.
    """
    if not FETCH_COMMENTS:
        return []

    comments: list[dict] = []
    video_url = f"https://www.tiktok.com/@{author_username}/video/{video_id}"

    try:
        # Navigate from within existing TikTok session
        await page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000 + random.uniform(0, 500))

        # ── Stage 1: Rehydration ───────────────────────────────────────────
        rehydration_comments = await _extract_rehydration_comments(page, author_username)
        if rehydration_comments:
            print(f"      [Rehydration] {len(rehydration_comments)} comments for {video_id}")
            comments.extend(rehydration_comments)
        else:
            print(f"      [Rehydration] No pre-loaded comments for {video_id}")

        # ── Stage 2: Click Comments tab → DOM scraping ────────────────────
        # The Comments tab is confirmed needed — TikTok defaults to "You may like".
        # After clicking, comment-level-1 spans render inside DivCommentListContainer.
        # data-e2e="comments" resolves to a HIDDEN inbox tab — do NOT wait for it.
        if len(comments) < MAX_COMMENTS_PER_VIDEO:
            tab_clicked = False
            for tab_selector in [
                '[data-e2e="browse-comments-tab"]',
                '[data-e2e="comment-tab"]',
                'button:has-text("Comments")',
                'span:has-text("Comments")',
            ]:
                try:
                    tab = page.locator(tab_selector).first
                    if await tab.is_visible(timeout=3000):
                        await tab.click()
                        tab_clicked = True
                        print(f"      [DOM] Clicked Comments tab for {video_id}")
                        break
                except Exception:
                    continue

            if not tab_clicked:
                print(f"      [DOM] Comments tab not found for {video_id} — trying anyway")

            # Wait for comment items to render — confirmed selector from DevTools:
            #   <span data-e2e="comment-level-1"> wraps each comment text span.
            # Use a generous timeout: comments lazy-render after the tab click.
            # Do NOT wait for data-e2e="comments" — that resolves to a hidden
            # inbox notification tab button, not the comment section.
            try:
                await page.wait_for_selector(
                    '[data-e2e="comment-level-1"]', timeout=12000
                )
            except Exception:
                print(f"      [DOM] comment-level-1 not found for {video_id} — 0 comments or slow render")

            dom_comments = await _scrape_comments_from_dom(page, author_username)
            added = 0
            for c in dom_comments:
                c_author   = c.get("author", "")
                like_count = int(c.get("likes", 0) or 0)
                if c_author.lower() == author_username.lower():
                    continue
                if like_count < MIN_COMMENT_LIKES:
                    continue
                if not any(existing["text"] == c.get("text", "") for existing in comments):
                    comments.append({
                        "author": c_author,
                        "text":   c.get("text", ""),
                        "likes":  like_count,
                    })
                    added += 1
            if added:
                print(f"      [DOM] +{added} comments for {video_id}")

        # ── Final sort + trim ──────────────────────────────────────────────
        comments.sort(key=lambda c: c["likes"], reverse=True)
        comments = comments[:MAX_COMMENTS_PER_VIDEO]

        if comments:
            print(f"      💬 {len(comments)} comments total for {video_id}")
        else:
            print(f"      ⚠️  0 comments for {video_id}")

        await asyncio.sleep(DELAY_BETWEEN_COMMENTS + random.uniform(-0.5, 0.5))

        # Navigate back so next video also has a tiktok.com referrer
        try:
            await page.goto(return_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(1000 + random.uniform(0, 500))
        except Exception:
            pass

    except Exception as e:
        print(f"      ⚠️  Comment fetch failed for {video_id}: {e}")
        # Recover page to return_url to preserve session
        try:
            await page.goto(return_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass

    return comments


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 5: VIDEO DICT BUILDER
# ──────────────────────────────────────────────────────────────────────────────

def _build_video_dict(item: dict, source: str, query: str, comments: list) -> dict:
    author   = item.get("author", {})
    if isinstance(author, str):
        author = {"uniqueId": author}
    stats    = item.get("stats", {})
    music    = item.get("music", {})
    video_id = str(item.get("id", ""))

    return {
        "id":           video_id,
        "desc":         item.get("desc", ""),
        "createTime":   item.get("createTime", ""),
        "author": {
            "uniqueId":      author.get("uniqueId", ""),
            "nickname":      author.get("nickname", ""),
            "followerCount": author.get("followerCount", 0),
            "verified":      author.get("verified", False),
        },
        "stats": {
            "diggCount":    stats.get("diggCount", 0),
            "commentCount": stats.get("commentCount", 0),
            "shareCount":   stats.get("shareCount", 0),
            "playCount":    stats.get("playCount", 0),
        },
        "music": {
            "title":      music.get("title", "") if isinstance(music, dict) else "",
            "authorName": music.get("authorName", "") if isinstance(music, dict) else "",
        },
        "source":        source,
        "query":         query,
        "scraped_at":    datetime.now().isoformat(),
        "comments_data": comments,
    }


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 6: HASHTAG SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

async def scrape_by_hashtag(context: BrowserContext, hashtag: str) -> list[dict]:
    """
    Scrape videos from a hashtag page, then navigate in-session to each
    video for comment collection.

    OLD approach: close page → new page per video → cold goto(video_url)
    NEW approach: keep page → navigate same page to each video URL
    """
    print(f"\n[Scraper] Hashtag: #{hashtag}")
    videos_data: list[dict] = []
    hashtag_url = f"https://www.tiktok.com/tag/{hashtag}"

    for attempt in range(1, MAX_RETRIES + 1):
        page = None
        try:
            page = await context.new_page()
            raw_items = await _collect_xhr_responses(
                page,
                url=hashtag_url,
                endpoint_pattern="/api/challenge/item_list/",
                max_items=MAX_VIDEOS_PER_TARGET,
            )
            # Page stays open — do NOT close here

            if not raw_items:
                print(f"   ⚠️  No XHR items for #{hashtag} (attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    print(f"   ⏳ Waiting {RATE_LIMIT_WAIT}s before retry...")
                    await asyncio.sleep(RATE_LIMIT_WAIT)
                continue

            print(f"   ✅ {len(raw_items)} videos found — fetching comments in-session...")

            for item in raw_items:
                video_id  = str(item.get("id", ""))
                author    = item.get("author", {})
                author_id = author.get("uniqueId", "") if isinstance(author, dict) else author

                comments = await fetch_comments_in_session(
                    page=page,
                    video_id=video_id,
                    author_username=author_id,
                    return_url=hashtag_url,
                )
                videos_data.append(
                    _build_video_dict(item, "hashtag_search", hashtag, comments)
                )
                await asyncio.sleep(DELAY_BETWEEN_VIDEOS + random.uniform(-1, 1))

            print(f"   ✅ {len(videos_data)} videos collected for #{hashtag}")
            break

        except Exception as e:
            print(f"   ⚠️  Error on #{hashtag} (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RATE_LIMIT_WAIT)
            else:
                print(f"   ❌ Max retries reached for #{hashtag}")
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    return videos_data


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 7: ACCOUNT SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

async def scrape_by_account(context: BrowserContext, username: str) -> list[dict]:
    """
    Scrape videos from an account page, then navigate in-session to each
    video for comment collection.
    """
    print(f"\n[Scraper] Account: @{username}")
    videos_data: list[dict] = []
    account_url = f"https://www.tiktok.com/@{username}"

    for attempt in range(1, MAX_RETRIES + 1):
        page = None
        try:
            page = await context.new_page()
            raw_items = await _collect_xhr_responses(
                page,
                url=account_url,
                endpoint_pattern="/api/post/item_list/",
                max_items=MAX_VIDEOS_PER_TARGET,
            )

            if not raw_items:
                print(f"   ⚠️  No XHR items for @{username} (attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    print(f"   ⏳ Waiting {RATE_LIMIT_WAIT}s before retry...")
                    await asyncio.sleep(RATE_LIMIT_WAIT)
                continue

            print(f"   ✅ {len(raw_items)} videos found — fetching comments in-session...")

            for item in raw_items:
                video_id = str(item.get("id", ""))
                comments = await fetch_comments_in_session(
                    page=page,
                    video_id=video_id,
                    author_username=username,
                    return_url=account_url,
                )
                videos_data.append(
                    _build_video_dict(item, "account_scrape", username, comments)
                )
                await asyncio.sleep(DELAY_BETWEEN_VIDEOS + random.uniform(-1, 1))

            print(f"   ✅ {len(videos_data)} videos collected for @{username}")
            break

        except Exception as e:
            print(f"   ⚠️  Error on @{username} (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RATE_LIMIT_WAIT)
            else:
                print(f"   ❌ Max retries reached for @{username}")
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    return videos_data


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 8: MASTER SCRAPE
# ──────────────────────────────────────────────────────────────────────────────

async def run_full_scrape() -> list[dict]:
    """
    Run all hashtag + account scrapes within a single browser context.

    Anchor page holds context alive between scraper calls. Each scraper
    opens its own page, uses it for both XHR collection AND in-session
    video navigation, then closes it cleanly when done.
    """
    check_maintenance_warning()
    all_results: list[dict] = []

    async with async_playwright() as playwright:
        context = await create_browser_context(playwright)
        if not context:
            print("❌ Cannot proceed — browser context failed to launch.")
            return []

        anchor_page = await context.new_page()
        await anchor_page.goto("about:blank")
        print("[Scraper] Anchor page open — context will stay alive between scrapes.")

        try:
            for hashtag in TARGET_HASHTAGS:
                results = await scrape_by_hashtag(context, hashtag)
                all_results.extend(results)
                await asyncio.sleep(3 + random.uniform(0, 2))

            for account in TARGET_ACCOUNTS:
                results = await scrape_by_account(context, account)
                all_results.extend(results)
                await asyncio.sleep(3 + random.uniform(0, 2))

        finally:
            try:
                await anchor_page.close()
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass

    seen: set = set()
    unique_results: list[dict] = []
    for video in all_results:
        vid_id = video.get("id", "")
        if vid_id and vid_id not in seen:
            seen.add(vid_id)
            unique_results.append(video)

    total_comments = sum(len(v.get("comments_data", [])) for v in unique_results)
    print(f"\n[Scraper] Done.")
    print(f"   🎬 Videos:   {len(unique_results)}")
    print(f"   💬 Comments: {total_comments} total across all videos")

    return unique_results


# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST
# Run: python -m Scripts.scraper
# ──────────────────────────────────────────────────────────────────────────────

async def _test_single_hashtag():
    """
    Smoke-test: fetch 3 videos from #IsuzuKenya and attempt comments on
    the first video using in-session navigation.
    """
    print("=" * 60)
    print("🧪 TikTok Scraper — In-Session Navigation Test")
    print("=" * 60)

    async with async_playwright() as playwright:
        context = await create_browser_context(playwright)
        if not context:
            sys.exit(1)

        hashtag_url = "https://www.tiktok.com/tag/IsuzuKenya"

        try:
            print("\n[Test] Fetching 3 videos from #IsuzuKenya...")
            page = await context.new_page()
            items = await _collect_xhr_responses(
                page,
                url=hashtag_url,
                endpoint_pattern="/api/challenge/item_list/",
                max_items=3,
                scroll_count=3,
            )

            if not items:
                print(
                    "\n⚠️  No videos collected.\n"
                    "   1. Run: python -m Scripts.auth to verify session\n"
                    "   2. Close all Chrome windows before running\n"
                )
                await page.close()
                return

            first     = items[0]
            author    = first.get("author", {})
            stats     = first.get("stats", {})
            video_id  = str(first.get("id", ""))
            author_id = author.get("uniqueId", "?") if isinstance(author, dict) else str(author)

            print(f"\n✅ Got {len(items)} videos via XHR")
            print(f"   ID:      {video_id}")
            print(f"   Author:  @{author_id}")
            print(f"   Caption: {str(first.get('desc', ''))[:80]}...")
            print(f"   Likes:   {stats.get('diggCount', 0):,}")
            print(f"   Views:   {stats.get('playCount', 0):,}")

            print(f"\n[Test] Fetching comments via in-session navigation...")
            comments = await fetch_comments_in_session(
                page=page,
                video_id=video_id,
                author_username=author_id,
                return_url=hashtag_url,
            )

            if comments:
                print(f"\n✅ {len(comments)} comments collected:")
                for c in comments[:3]:
                    print(f"   @{c['author']}: {c['text'][:60]}... ({c['likes']} likes)")
                print("\n✅ Test passed.\n")
            else:
                print(
                    "\n⚠️  0 comments collected.\n"
                    "   Check the browser window — did the video page load?\n"
                    "   Did the Comments tab appear?\n"
                )

            await page.close()

        finally:
            try:
                await context.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(_test_single_hashtag())