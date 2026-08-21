"""
BrandPulse LinkedIn Scraper — Core Scraping Logic
===================================================
Architecture: Playwright DOM scraping via CfT persistent context.

Why DOM scraping, not Voyager API:
    Investigation confirmed LinkedIn server-side renders post content
    directly into HTML — exactly like Facebook. The Elements panel
    shows post text in <span data-testid="expandable-text-box"> and
    comments in <div dir="auto"> containers. Voyager API attempts
    returned 400/403 because LinkedIn migrated endpoints to an
    opaque GraphQL format that changes every 4-8 weeks.

    The DOM approach is stable, session-authenticated via the CfT
    profile, and mirrors the working Facebook scraper architecture.

How it works:
    1. CfT launches with persistent profile (already logged in)
    2. Navigate to keyword search URL or company posts URL
    3. Scroll to load all posts (infinite scroll)
    4. page.evaluate() extracts post data from rendered DOM
    5. For each post, open post URL and extract comments via
       div[dir="auto"] — identical strategy to Facebook scraper
    6. Paginate by scrolling until post limit reached

Key DOM selectors (verified from Elements panel, March 2026):
    Posts container : li[role="listitem"]
    Post text       : span[data-testid="expandable-text-box"]
    Post author     : a[href*="/company/"], a[href*="/in/"]
    Comments        : div[dir="auto"] (same as Facebook)
    Engagement      : button[aria-label*="reaction"],
                      button[aria-label*="comment"]
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import random
import hashlib
from datetime import datetime, timezone
from urllib.parse import quote_plus
from playwright.async_api import async_playwright, BrowserContext, Page

from config import (
    CHROME_EXECUTABLE_PATH, CHROME_PROFILE_PATH, CHROME_PROFILE_DIR,
    TARGET_COMPANIES, SEARCH_KEYWORDS,
    MAX_POSTS_PER_TARGET, MAX_COMMENTS_PER_POST,
    DELAY_BETWEEN_REQUESTS, DELAY_BETWEEN_POSTS,
)

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1: BROWSER CONTEXT
# ──────────────────────────────────────────────────────────────────────────────

async def launch_linkedin_context(playwright) -> BrowserContext:
    """
    Launch CfT with persistent profile.
    Same pattern as Facebook scraper — LinkedIn session already active.
    """
    for lock in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        for base in [CHROME_PROFILE_PATH,
                     os.path.join(CHROME_PROFILE_PATH, CHROME_PROFILE_DIR)]:
            lp = os.path.join(base, lock)
            if os.path.exists(lp):
                try:
                    os.remove(lp)
                except Exception:
                    pass

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=CHROME_PROFILE_PATH,
        executable_path=CHROME_EXECUTABLE_PATH,
        headless=False,
        args=[
            f"--profile-directory={CHROME_PROFILE_DIR}",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--disable-notifications",
        ],
        viewport={"width": 1280, "height": 900},
        user_agent=_DESKTOP_UA,
    )
    return context


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2: POST DOM EXTRACTOR
# ──────────────────────────────────────────────────────────────────────────────

_EXTRACT_POSTS_JS = """
() => {
    const posts = [];
    const seen  = new Set();

    // ── Strategy: find ALL post text elements across both page types ──
    // Search pages: span[data-testid="expandable-text-box"]
    // Company pages: span.break-words inside update-components-text
    const textEls = [
        ...document.querySelectorAll('span[data-testid="expandable-text-box"]'),
        ...document.querySelectorAll(
            'div.update-components-text span.break-words, ' +
            'div.update-components-update-v2__commentary span.break-words'
        )
    ];

    for (const textEl of textEls) {
        try {
            const text = textEl.innerText.trim();
            if (!text) continue;

            // Walk up to find the post card
            let card = textEl.parentElement;
            for (let i = 0; i < 15; i++) {
                if (!card) break;
                // Stop at feed-full-update container (has the URN)
                if (card.getAttribute('data-view-name') === 'feed-full-update') break;
                // Also stop when we have both author link and action buttons
                if (card.querySelector('a[href*="/in/"], a[href*="/company/"]') &&
                    card.querySelector('button[aria-label]')) break;
                card = card.parentElement;
            }
            if (!card) continue;

            // ── Post URL / ID ──────────────────────────────────────
            // Primary: extract from data-view-name div's tracking scope
            let postUrl = '';
            let postId  = '';

            // Walk up to find the data-view-name container
            let urnContainer = card;
            for (let i = 0; i < 5; i++) {
                if (!urnContainer) break;
                const scope = urnContainer.getAttribute('data-view-tracking-scope') ||
                              urnContainer.getAttribute('data-finite-scroll-hotkey-item') ||
                              '';
                if (scope.includes('updateEntityUrn') || scope.includes('activity:')) {
                    try {
                        const parsed = JSON.parse(scope);
                        const urn = parsed.updateEntityUrn || parsed.entityUrn || '';
                        const m = urn.match(/activity:(\\d+)/);
                        if (m) { postId = m[1]; break; }
                    } catch(e) {}
                }
                // Also check data attributes directly
                const dataUrn = urnContainer.getAttribute('data-urn') || '';
                const m2 = dataUrn.match(/activity:(\\d+)/);
                if (m2) { postId = m2[1]; break; }
                urnContainer = urnContainer.parentElement;
            }

            // Secondary: find activity URL in links
            if (!postId) {
                const allLinks = card.querySelectorAll('a[href]');
                for (const a of allLinks) {
                    const href = a.href || '';
                    const m = href.match(/(?:activity:|ugcPost:)(\\d+)/) ||
                              href.match(/activity-(\\d+)/);
                    if (m && href.includes('feed')) {
                        postId  = m[1];
                        postUrl = href.split('?')[0];
                        break;
                    }
                }
            }

            // Build URL from ID if we have ID but no URL
            if (postId && !postUrl) {
                postUrl = `https://www.linkedin.com/feed/update/urn:li:activity:${postId}/`;
            }

            const key = postId || text.slice(0, 50);
            if (seen.has(key)) continue;
            seen.add(key);

            // ── Author ─────────────────────────────────────────────
            let authorName = '';
            let authorUrl  = '';

            const authorLinks = card.querySelectorAll(
                'a[href*="/in/"], a[href*="/company/"]'
            );
            for (const a of authorLinks) {
                const hiddenSpan = a.querySelector('span[aria-hidden="true"]');
                const name = hiddenSpan
                    ? hiddenSpan.innerText.trim()
                    : a.innerText.trim().split('\\n')[0];
                if (name && name.length > 1 &&
                    !name.includes('Follow') && !name.includes('Message')) {
                    authorName = name;
                    authorUrl  = a.href.split('?')[0];
                    break;
                }
            }

            const authorIdMatch = authorUrl.match(/\\/company\\/([^/?]+)/) ||
                                  authorUrl.match(/\\/in\\/([^/?]+)/);
            const authorId = authorIdMatch ? authorIdMatch[1] : '';

            // ── Timestamp ──────────────────────────────────────────
            let timeText = '';
            const allLinks2 = card.querySelectorAll('a[href]');
            for (const a of allLinks2) {
                const label = a.getAttribute('aria-label') || '';
                const txt   = a.innerText.trim();
                if (label.match(/\\d+\\s*(minute|hour|day|week|month|year)/i)) {
                    timeText = label; break;
                }
                if (txt.match(/^\\d+[smhdwmy]$/) ||
                    txt.match(/^\\d+\\s*(minute|hour|day|week|month|year)/i)) {
                    timeText = txt; break;
                }
            }

            // ── Engagement ─────────────────────────────────────────
            let reactions = 0, commentCount = 0, reposts = 0;
            card.querySelectorAll('[aria-label]').forEach(el => {
                const label = (el.getAttribute('aria-label') || '').toLowerCase();
                const n = label.match(/(\\d[\\d,]*)/);
                if (!n) return;
                const val = parseInt(n[1].replace(/,/g, ''));
                if (label.includes('reaction') || label.includes('like'))
                    reactions = Math.max(reactions, val);
                if (label.includes('comment'))
                    commentCount = Math.max(commentCount, val);
                if (label.includes('repost') || label.includes('reshare'))
                    reposts = Math.max(reposts, val);
            });

            // ── Hashtags ───────────────────────────────────────────
            const hashtags = Array.from(
                card.querySelectorAll('a[href*="/feed/hashtag/"]')
            ).map(el => el.innerText.replace('#', '').trim().toLowerCase())
             .filter(Boolean);

            posts.push({
                post_id: postId, post_url: postUrl, text,
                author_name: authorName, author_id: authorId, author_url: authorUrl,
                time_text: timeText, reactions, comment_count: commentCount,
                reposts, hashtags,
            });

        } catch(e) { /* skip */ }
    }
    return posts;

}
"""

# ──────────────────────────────────────────────────────────────────────────────
# SECTION 3: COMMENT DOM EXTRACTOR
# ──────────────────────────────────────────────────────────────────────────────

_EXTRACT_COMMENTS_JS = """
() => {
    const results = [];
    const seen    = new Set();

    // Comments are in article.comments-comment-entity
    // Image 4 confirms: text in span[dir="ltr"] inside update-components-text
    const commentArticles = document.querySelectorAll(
        'article.comments-comment-entity, ' +
        'div.comments-comment-item'
    );

    for (const article of commentArticles) {
        try {
            // Text: span[dir="ltr"] inside the comment content
            const textEl = article.querySelector(
                'span[dir="ltr"], div[dir="ltr"], ' +
                'div.update-components-text span.break-words'
            );
            const text = textEl ? textEl.innerText.trim() : '';
            if (!text || text.length < 2 || seen.has(text.slice(0, 60))) continue;
            seen.add(text.slice(0, 60));

            // Author: first profile link
            let author   = '';
            let authorId = '';
            const aLink = article.querySelector('a[href*="/in/"], a[href*="/company/"]');
            if (aLink) {
                const span = aLink.querySelector('span[aria-hidden="true"]');
                author = span ? span.innerText.trim() : aLink.innerText.trim().split('\\n')[0];
                const m = aLink.href.match(/\\/in\\/([^/?]+)/) ||
                          aLink.href.match(/\\/company\\/([^/?]+)/);
                if (m) authorId = m[1];
            }

            // Timestamp
            let timestamp = '';
            const timeEl = article.querySelector('time, a[aria-label*="ago"], span[aria-label*="ago"]');
            if (timeEl) {
                timestamp = timeEl.getAttribute('aria-label') ||
                            timeEl.getAttribute('datetime') ||
                            timeEl.innerText || '';
            }

            // Likes
            let likes = 0;
            const likeBtn = article.querySelector('button[aria-label*="Like"], button[aria-label*="React"]');
            if (likeBtn) {
                const n = (likeBtn.getAttribute('aria-label') || '').match(/(\\d+)/);
                if (n) likes = parseInt(n[1]);
            }

            results.push({ text, author, author_id: authorId, timestamp, likes });
        } catch(e) { /* skip */ }
    }

    // Fallback: div[dir="auto"] for any missed comments
    if (results.length === 0) {
        document.querySelectorAll('div[dir="auto"]').forEach(el => {
            const text = el.innerText.trim();
            if (!text || text.length < 2 || seen.has(text.slice(0, 60))) return;
            seen.add(text.slice(0, 60));
            results.push({ text, author: '', author_id: '', timestamp: '', likes: 0 });
        });
    }

    return results;
}
"""


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 4: SCROLL + EXTRACT LOOP
# ──────────────────────────────────────────────────────────────────────────────

async def scroll_and_extract_posts(
    page: Page,
    source: str,
    query: str,
) -> list[dict]:
    """
    Scroll the page, extracting posts after each scroll.
    Stops when MAX_POSTS_PER_TARGET reached or 3 scrolls yield nothing new.
    """
    all_posts:          dict[str, dict] = {}
    consecutive_no_new: int             = 0

    # Wait for posts to render
    try:
        await page.wait_for_selector(
            'span[data-testid="expandable-text-box"], '
            'div.update-components-text span.break-words',
            timeout=15000,
        )
    except Exception:
        print(f"   ⚠️  No posts found after 15s — page may not have loaded")
        return []

    await page.wait_for_timeout(2000)

    while len(all_posts) < MAX_POSTS_PER_TARGET:
        raw_posts = await page.evaluate(_EXTRACT_POSTS_JS)

        new_this_round = 0
        for raw in raw_posts:
            key = raw.get("post_id") or hashlib.md5(
                raw.get("text", "")[:60].encode()
            ).hexdigest()[:12]

            if key not in all_posts:
                raw["source"]     = source
                raw["query"]      = query
                raw["scraped_at"] = datetime.now(timezone.utc).isoformat()
                raw["comments"]   = []
                all_posts[key]    = raw
                new_this_round   += 1
                print(
                    f"      [{source}] +1 post (total: {len(all_posts)}) "
                    f"— {raw.get('author_name', '?')}"
                )

        if new_this_round == 0:
            consecutive_no_new += 1
            if consecutive_no_new >= 3:
                print(f"   ℹ️  No new posts after 3 scrolls — done")
                break
        else:
            consecutive_no_new = 0

        if len(all_posts) >= MAX_POSTS_PER_TARGET:
            break

        # Scroll to trigger infinite scroll
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(
            DELAY_BETWEEN_REQUESTS * 1000 + random.uniform(0, 1500)
        )

        # Click "Show more results" if present
        for btn_text in ["Show more results", "Load more", "See more"]:
            try:
                btn = page.locator(f'button:has-text("{btn_text}")').first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    break
            except Exception:
                pass

    return list(all_posts.values())


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 5: COMMENT FETCHER
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_comments_for_post(
    context: BrowserContext,
    post: dict,
) -> list[dict]:
    """
    Open post URL, extract comments via div[dir="auto"].
    Identical strategy to the working Facebook scraper.
    """
    post_url = post.get("post_url", "")
    if not post_url:
        return []

    all_comments: list[dict] = []
    seen_texts:   set[str]   = set()
    page = await context.new_page()

    try:
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000 + random.uniform(0, 1000))

        # Scroll to trigger comment load
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 600)")
            await page.wait_for_timeout(1000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        try:
            await page.wait_for_selector(
                'article.comments-comment-entity, '
                'div.comments-comment-item',
                timeout=8000,
            )
        except Exception:
            pass  # Post may have no comments — continue anyway

        # On some posts, comments are collapsed — click Comment button to expand
        try:
            comment_btn = page.locator(
                'button[aria-label*="Comment"], '
                'button:has-text("Comment")'
            ).first
            if await comment_btn.is_visible(timeout=3000):
                await comment_btn.click()
                await page.wait_for_timeout(2000)
        except Exception:
            pass  # Already expanded or no comment button — continue
            
        consecutive_no_new = 0

        while len(all_comments) < MAX_COMMENTS_PER_POST:
            comments_raw = await page.evaluate(_EXTRACT_COMMENTS_JS)

            new_this_round = 0
            for c in comments_raw:
                text = c.get("text", "").strip()
                if not text or text in seen_texts:
                    continue
                seen_texts.add(text)

                all_comments.append({
                    "comment_id":  hashlib.md5(
                        f"{post.get('post_id','')}{text}".encode()
                    ).hexdigest()[:16],
                    "text":        text,
                    "author_name": c.get("author", ""),
                    "author_id":   c.get("author_id", ""),
                    "timestamp":   c.get("timestamp", ""),
                    "likes":       int(c.get("likes", 0) or 0),
                    "created_time": 0,
                })
                new_this_round += 1

            print(
                f"      [DOM] {new_this_round} new comments "
                f"(total: {len(all_comments)})"
            )

            if new_this_round == 0:
                consecutive_no_new += 1
                if consecutive_no_new >= 2:
                    break
            else:
                consecutive_no_new = 0

            if len(all_comments) >= MAX_COMMENTS_PER_POST:
                break

            # Click "Load more comments"
            clicked = False
            for phrase in [
                "Load more comments", "Show more comments",
                "View more comments", "See previous comments",
            ]:
                try:
                    btn = page.locator(
                        f'button:has-text("{phrase}"), '
                        f'span:has-text("{phrase}")'
                    ).first
                    if await btn.is_visible(timeout=1500):
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        await page.wait_for_timeout(
                            DELAY_BETWEEN_POSTS * 1000 + random.uniform(0, 500)
                        )
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                break

        total = len(all_comments)
        print(
            f"      {'💬' if total else 'ℹ️ '} "
            f"{total} comments for post {post.get('post_id', '?')}"
        )

    except Exception as e:
        print(f"      ⚠️  Comment fetch failed: {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return all_comments[:MAX_COMMENTS_PER_POST]


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 6: COMPANY PAGE SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

async def scrape_company_posts(
    context: BrowserContext,
    company_slug: str,
) -> list[dict]:
    """Scrape posts from linkedin.com/company/{slug}/posts/"""
    url  = f"https://www.linkedin.com/company/{company_slug}/posts/"
    page = await context.new_page()

    print(f"\n[Scraper] Company: {company_slug}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        if "login" in page.url or "authwall" in page.url:
            print("   ❌ Session expired — login required")
            await page.close()
            return []

        # Click the Posts tab if on company overview page
        try:
            posts_tab = page.locator('a:has-text("Posts")').first
            if await posts_tab.is_visible(timeout=3000):
                await posts_tab.click()
                await page.wait_for_timeout(2000)
        except Exception:
            pass

        posts = await scroll_and_extract_posts(page, "company_feed", company_slug)
        print(f"   ✅ {len(posts)} posts from {company_slug}")

    except Exception as e:
        print(f"   ❌ Company scrape failed: {e}")
        posts = []
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return posts


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 7: KEYWORD SEARCH SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

async def scrape_keyword_posts(
    context: BrowserContext,
    keyword: str,
) -> list[dict]:
    """
    Scrape posts from the LinkedIn content search page.
    URL confirmed in DevTools to serve server-rendered post HTML.
    """
    encoded = quote_plus(keyword)
    url = (
        f"https://www.linkedin.com/search/results/content/"
        f"?keywords={encoded}"
        f"&origin=SWITCH_SEARCH_VERTICAL"
        f"&sortBy=date_posted"
    )
    page = await context.new_page()

    print(f"\n[Scraper] Search: '{keyword}'")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        if "login" in page.url or "authwall" in page.url:
            print("   ❌ Session expired — login required")
            await page.close()
            return []

        # Click Posts filter tab if not already on it
        try:
            posts_tab = page.locator('button:has-text("Posts")').first
            if await posts_tab.is_visible(timeout=2000):
                await posts_tab.click()
                await page.wait_for_timeout(2000)
        except Exception:
            pass

        posts = await scroll_and_extract_posts(page, "search", keyword)
        print(f"   ✅ {len(posts)} posts for '{keyword}'")

    except Exception as e:
        print(f"   ❌ Search scrape failed: {e}")
        posts = []
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return posts


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 8: MASTER SCRAPE
# ──────────────────────────────────────────────────────────────────────────────

async def run_full_scrape(playwright) -> list[dict]:
    """
    Full pipeline: launch CfT → collect posts → enrich with comments.
    Returns list of raw post dicts ready for normalizer.py
    """
    context   = await launch_linkedin_context(playwright)
    all_posts: dict[str, dict] = {}

    print("\n" + "=" * 60)
    print("PHASE 1: Collecting posts")
    print("=" * 60)

    for slug in TARGET_COMPANIES:
        posts = await scrape_company_posts(context, slug)
        for p in posts:
            key = p.get("post_id") or hashlib.md5(
                p.get("text", "")[:60].encode()
            ).hexdigest()[:12]
            if key not in all_posts:
                all_posts[key] = p
        await asyncio.sleep(DELAY_BETWEEN_REQUESTS + random.uniform(0, 2))

    for keyword in SEARCH_KEYWORDS:
        posts = await scrape_keyword_posts(context, keyword)
        for p in posts:
            key = p.get("post_id") or hashlib.md5(
                p.get("text", "")[:60].encode()
            ).hexdigest()[:12]
            if key not in all_posts:
                all_posts[key] = p
        await asyncio.sleep(DELAY_BETWEEN_REQUESTS + random.uniform(0, 2))

    print(f"\n📊 Phase 1 complete — {len(all_posts)} unique posts.")

    print("\n" + "=" * 60)
    print("PHASE 2: Collecting comments")
    print("=" * 60)

    posts_list = list(all_posts.values())
    for i, post in enumerate(posts_list, 1):
        print(
            f"\n[{i:3d}/{len(posts_list)}] "
            f"{post.get('author_name', '?')} "
            f"— {post.get('comment_count', 0)} expected"
        )
        if not post.get("post_url"):
            print("      ⚠️  No post URL — skipping")
            continue

        comments = await fetch_comments_for_post(context, post)
        key = post.get("post_id") or hashlib.md5(
            post.get("text", "")[:60].encode()
        ).hexdigest()[:12]
        all_posts[key]["comments"] = comments

    await context.close()

    result         = list(all_posts.values())
    total_comments = sum(len(p.get("comments", [])) for p in result)
    print(f"\n[Scraper] Done. Posts: {len(result)} | Comments: {total_comments}")

    return result


# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST — python -m ScraperCode.Scraper
# ──────────────────────────────────────────────────────────────────────────────

async def _test():
    import config as cfg

    print("=" * 60)
    print("🧪 LinkedIn Scraper — DOM Test")
    print("=" * 60)

    cfg.MAX_POSTS_PER_TARGET  = 3
    cfg.MAX_COMMENTS_PER_POST = 5

    async with async_playwright() as playwright:
        context = await launch_linkedin_context(playwright)

        print("\n[Test 1] Keyword search: 'Isuzu East Africa Limited'")
        posts = await scrape_keyword_posts(context, "Isuzu East Africa Limited")

        if posts:
            print(f"\n✅ {len(posts)} posts collected")
            for p in posts[:2]:
                print(
                    f"\n   Author : {p.get('author_name', '?')}\n"
                    f"   Text   : {p.get('text', '')[:80]}...\n"
                    f"   URL    : {p.get('post_url', '?')}\n"
                    f"   Likes  : {p.get('reactions', 0)}"
                )

            if posts[0].get("post_url"):
                print("\n[Test 2] Comments for first post...")
                comments = await fetch_comments_for_post(context, posts[0])
                print(f"✅ {len(comments)} comments")
                for c in comments[:3]:
                    print(f"   @{c['author_name']}: {c['text'][:60]}...")
        else:
            print(
                "\n⚠️  No posts — check:\n"
                "   1. LinkedIn logged in CfT? → python -m ScraperCode.auth\n"
                "   2. Search page loading? → open URL in CfT manually\n"
                "   3. Selectors changed? → inspect li[role=listitem] in DevTools\n"
            )

        await context.close()

    print("\n✅ Test complete.\n")


if __name__ == "__main__":
    asyncio.run(_test())