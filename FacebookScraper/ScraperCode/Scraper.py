"""
BrandPulse Facebook Scraper — Core Scraping Logic
===================================================
Uses Playwright GraphQL XHR interception throughout.

Why GraphQL interception, not DOM scraping:
    Facebook's HTML uses randomly hashed CSS class names regenerated on every
    deploy — DOM selectors break within days. Facebook's internal GraphQL
    endpoint (POST /api/graphql/) is stable across deploys and returns clean
    structured JSON containing post text, author, timestamp, reactions, and
    paginated comments in one place.

How it works:
    1. Navigate to facebook.com/search/posts/?q=<keyword> (or a page URL)
    2. Intercept every POST /api/graphql/ response
    3. Parse responses — identify those containing post edge nodes
    4. Filter posts by date range using the unix timestamp in each node
    5. For each qualifying post, navigate to the post URL
    6. Intercept GraphQL comment responses as comments load
    7. Click "View more comments" repeatedly to paginate up to MAX_COMMENTS_PER_POST

GraphQL response structure (post node):
    node.id                     — post ID
    node.message.text           — post body text
    node.created_time           — unix timestamp
    node.url / node.permalink_url — post URL
    node.owner.name             — author name
    node.owner.id               — author ID
    node.feedback.reaction_count.count  — total reactions
    node.feedback.comments_count.total_count — comment count

GraphQL response structure (comment node):
    node.id                     — comment ID
    node.body.text              — comment text
    node.created_time           — unix timestamp
    node.author.name            — commenter name
    node.author.id              — commenter ID
    node.feedback.reactors.count — comment likes

Architecture:
    auth.py        CfT browser → BrowserContext
    scraper.py     GraphQL XHR interception → raw post + comment dicts
    normalizer.py  raw dicts → BrandPulse schema
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import random
import copy
import hashlib
import requests as _requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import quote_plus
from playwright.async_api import async_playwright, BrowserContext, Page, Response

from ScraperCode.auth import create_browser_context, check_maintenance_warning
from config import (
    SEARCH_QUERIES, TARGET_PAGES,
    DATE_FROM, DATE_TO,
    MAX_POSTS_PER_TARGET, MAX_COMMENTS_PER_POST,
    DELAY_BETWEEN_POSTS, DELAY_BETWEEN_SCROLLS,
    DELAY_COMMENT_CLICK, RATE_LIMIT_WAIT, MAX_RETRIES,
)


# ── Date range as unix timestamps ─────────────────────────────────────────────
_TS_FROM = int(datetime.fromisoformat(DATE_FROM).replace(tzinfo=timezone.utc).timestamp())
_TS_TO   = int(datetime.fromisoformat(DATE_TO).replace(tzinfo=timezone.utc).timestamp())

def _parse_fb_count(val) -> int:
    """
    Parse Facebook's formatted count strings to int.
    Handles: 7, "7", "1.4K", "2.3M", None → int
    """
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    s = str(val).strip().upper().replace(",", "")
    try:
        if s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        return int(float(s))
    except (ValueError, TypeError):
        return 0
    
# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1: GRAPHQL RESPONSE PARSER
# ──────────────────────────────────────────────────────────────────────────────

def _extract_posts_from_graphql(body: dict) -> list[dict]:
    """
    Handles three response structures:
      1. serpResponse   — facebook.com/search/posts/?q=... (standard search)
      2. topic_deep_dive — facebook.com/hashtag/...
      3. Legacy recursive walk — page feeds
    """
    # ── serpResponse (standard keyword search) ────────────────────────
    try:
        edges = body["data"]["serpResponse"]["results"]["edges"]
        stories = []
        for edge in edges:
            try:
                story = (
                    edge["rendering_strategy"]["view_model"]
                        ["click_model"]["story"]
                )
                story["_tdd"] = True   # same internal shape — reuse normalizer
                stories.append(story)
            except (KeyError, TypeError):
                continue
        if stories:
            return stories
    except (KeyError, TypeError):
        pass

    # ── topic_deep_dive (hashtag pages) ──────────────────────────────
    try:
        edges = body["data"]["topic_deep_dive"]["rendering_strategies"]["edges"]
        stories = []
        for edge in edges:
            try:
                story = edge["rendering_strategy"]["explore_view_model"]["story"]
                story["_tdd"] = True
                stories.append(story)
            except (KeyError, TypeError):
                continue
        if stories:
            return stories
    except (KeyError, TypeError):
        pass

    # ── Legacy recursive walk (page feeds) ───────────────────────────
    posts = []
    _walk_for_posts(body, posts)
    return posts

def _walk_for_posts(obj, results: list, depth: int = 0):
    """Recursively walk a JSON object looking for post nodes."""
    if depth > 12:
        return
    if isinstance(obj, dict):
        # Post node heuristic: has created_time (int) and message or story
        if (
            isinstance(obj.get("created_time"), int)
            and (
                isinstance(obj.get("message"), dict)
                or isinstance(obj.get("story"), dict)
                or isinstance(obj.get("message"), str)
            )
        ):
            results.append(obj)
            return  # Don't recurse into a found node's children
        for v in obj.values():
            _walk_for_posts(v, results, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_posts(item, results, depth + 1)


def _extract_comments_from_graphql(body: dict) -> list[dict]:
    """
    Walk a GraphQL response body and extract all comment-shaped nodes.

    Comment node heuristic: has 'body' dict with 'text' key, and a
    'created_time' int — distinguishes comments from post nodes which
    use 'message' instead of 'body'.
    """
    comments = []
    _walk_for_comments(body, comments)
    return comments


def _walk_for_comments(obj, results: list, depth: int = 0):
    if depth > 12:
        return
    if isinstance(obj, dict):
        body = obj.get("body")
        if (
            isinstance(obj.get("created_time"), int)
            and isinstance(body, dict)
            and isinstance(body.get("text"), str)
        ):
            results.append(obj)
            return
        for v in obj.values():
            _walk_for_comments(v, results, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_comments(item, results, depth + 1)


def _normalise_post_node(node: dict, source: str, query: str) -> dict | None:
    """
    Convert a raw GraphQL post node to a flat intermediate dict.
    Returns None if required fields are missing.
    """
    post_id      = node.get("id", "")
    created_time = node.get("created_time", 0)

    if not post_id or not created_time:
        return None

    # Filter by date range
    if not (_TS_FROM <= created_time <= _TS_TO):
        return None

    # Post text — may be under 'message' or 'story'
    msg = node.get("message") or node.get("story") or {}
    if isinstance(msg, str):
        text = msg
    elif isinstance(msg, dict):
        text = msg.get("text", "")
    else:
        text = ""

    # Post URL — several possible keys
    post_url = (
        node.get("url")
        or node.get("permalink_url")
        or node.get("link")
        or ""
    )

    # Author
    owner = node.get("owner") or node.get("author") or {}
    author_name = owner.get("name", "") if isinstance(owner, dict) else ""
    author_id   = owner.get("id", "")   if isinstance(owner, dict) else ""

    # Engagement
    feedback = node.get("feedback") or {}
    reaction_count = (
        (feedback.get("reaction_count") or {}).get("count", 0)
        or (feedback.get("reactions") or {}).get("count", 0)
        or 0
    )
    comment_count = (
        (feedback.get("comments_count") or {}).get("total_count", 0)
        or (feedback.get("comment_count") or {}).get("count", 0)
        or node.get("comment_count", 0)
        or 0
    )
    share_count = (
        (node.get("share_count") or {}).get("count", 0)
        or node.get("share_count", 0)
        or 0
    )

    return {
        "post_id":       str(post_id),
        "post_url":      post_url,
        "text":          text,
        "created_time":  created_time,
        "author_name":   author_name,
        "author_id":     str(author_id),
        "reactions":     int(reaction_count),
        "comment_count": int(comment_count),
        "shares":        int(share_count),
        "source":        source,
        "query":         query,
        "scraped_at":    datetime.now(timezone.utc).isoformat(),
        "comments":      [],  # filled in by fetch_comments_for_post()
    }

def _normalise_tdd_story(story: dict, source: str, query: str) -> dict | None:
    """
    Normalize a topic_deep_dive story node (Facebook search results)
    to the same intermediate dict shape as _normalise_post_node().

    Field paths verified against fb_response.json (2026-03-23).
    """
    post_id = story.get("post_id", "")
    if not post_id:
        return None

    # Timestamp ──────────────────────────────────────────────────────
    try:
        created_time = (
            story["comet_sections"]["timestamp"]["story"]["creation_time"]
        )
    except (KeyError, TypeError):
        created_time = 0

    if not created_time:
        return None

    if not (_TS_FROM <= created_time <= _TS_TO):
        return None

    # Content (text, URL, actors) ────────────────────────────────────
    try:
        cs = story["comet_sections"]["content"]["story"]
    except (KeyError, TypeError):
        cs = {}

    try:
        text = cs["message"]["text"]
    except (KeyError, TypeError):
        text = ""

    post_url = cs.get("wwwURL", "")

    actors = cs.get("actors") or []
    if actors and isinstance(actors[0], dict):
        author_name = actors[0].get("name", "")
        author_id   = str(actors[0].get("id", ""))
    else:
        author_name = ""
        author_id   = ""

    # Engagement ─────────────────────────────────────────────────────
    try:
        ufi = (
            story["comet_sections"]["feedback"]["story"]
                 ["story_ufi_container"]["story"]
                 ["feedback_context"]["feedback_target_with_context"]
                 ["comet_ufi_summary_and_actions_renderer"]["feedback"]
        )
        # Sum per-reaction-type counts for an exact integer total
        top_reactions = ufi.get("top_reactions", {}).get("edges", [])
        reaction_count = sum(
            e.get("reaction_count", 0) for e in top_reactions
            if isinstance(e, dict)
        )
        # Fall back to i18n string if top_reactions is empty
        if reaction_count == 0:
            reaction_count = _parse_fb_count(ufi.get("i18n_reaction_count", 0))

        share_count = _parse_fb_count(ufi.get("i18n_share_count", 0))
    except (KeyError, TypeError):
        reaction_count = share_count = 0

    # Comment count (pcomment = preliminary count, often 0 in search) 
    try:
        comment_count = int(
            story["comet_sections"]["feedback"]["story"]
                 ["story_ufi_container"]["story"]
                 ["feed_backend_data"].get("pcomment", 0) or 0
        )
    except (KeyError, TypeError):
        comment_count = 0

    return {
        "post_id":       str(post_id),
        "post_url":      post_url,
        "text":          text,
        "created_time":  created_time,
        "author_name":   author_name,
        "author_id":     author_id,
        "reactions":     reaction_count,
        "comment_count": comment_count,
        "shares":        share_count,
        "source":        source,
        "query":         query,
        "scraped_at":    datetime.now(timezone.utc).isoformat(),
        "comments":      [],
    }

def _normalise_comment_node(node: dict) -> dict | None:
    """Convert a raw GraphQL comment node to a flat dict."""
    comment_id   = node.get("id", "")
    body         = node.get("body", {})
    text         = body.get("text", "") if isinstance(body, dict) else str(body)
    created_time = node.get("created_time", 0)

    if not text:
        return None

    author = node.get("author") or node.get("commenter") or {}
    author_name = author.get("name", "") if isinstance(author, dict) else ""
    author_id   = author.get("id", "")   if isinstance(author, dict) else ""

    likes = (
        (node.get("feedback") or {}).get("reactors", {}).get("count", 0)
        or node.get("like_count", 0)
        or 0
    )

    return {
        "comment_id":   str(comment_id),
        "text":         text,
        "created_time": created_time,
        "author_name":  author_name,
        "author_id":    str(author_id),
        "likes":        int(likes),
    }


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2: COMMENT FETCHER
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2: COMMENT FETCHER  (mbasic.facebook.com — plain HTML)
# ──────────────────────────────────────────────────────────────────────────────

from bs4 import BeautifulSoup as _BS


    # REPLACE _MOBILE_UA with this:
_MOBILE_UA = (
    "curl/7.68.0"
)


def _build_mbasic_url(post: dict) -> str:
    """
    Build a mbasic.facebook.com URL using the numeric post_id.

    mbasic requires numeric IDs — it cannot handle pfbid-encoded URLs
    (permalink.php?story_fbid=pfbid0...) or reel URLs. The story.php
    format with the numeric post_id is the universal fallback that works
    for page posts, group posts, and reels alike.

    Optionally include &id=<page_id> extracted from permalink.php URLs
    to help mbasic resolve the correct page context.
    """
    post_id  = post.get("post_id", "")
    post_url = post.get("post_url", "")

    if not post_id:
        return ""

    # Try to extract numeric page/profile ID from permalink.php URLs
    # e.g. facebook.com/permalink.php?story_fbid=pfbid...&id=100063524542962
    page_id = ""
    if "permalink.php" in post_url and "id=" in post_url:
        try:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(post_url).query)
            page_id = qs.get("id", [""])[0]
        except Exception:
            pass

    if page_id:
        return (
            f"https://mbasic.facebook.com/story.php"
            f"?story_fbid={post_id}&id={page_id}"
        )

    return f"https://mbasic.facebook.com/story.php?story_fbid={post_id}"
def _parse_mbasic_comment(div) -> dict | None:
    """
    Parse one mbasic comment block into a flat dict.

    mbasic comment HTML (stable since ~2015):
        <div id="...">
          <h3><a href="/username">Author Name</a></h3>
          Comment text as a direct text node
          <div><abbr title="Wednesday, 25 March 2026 at 10:30">4d</abbr></div>
          <div><a href="/ufi/reaction/...">N people like this</a></div>
        </div>
    """
    try:
        h3 = div.find("h3")
        if not h3:
            return None

        # Author
        author_link = h3.find("a")
        author_name = (
            author_link.get_text(strip=True)
            if author_link else h3.get_text(strip=True)
        )
        author_href = author_link.get("href", "") if author_link else ""
        author_id   = ""
        if "id=" in author_href:
            author_id = author_href.split("id=")[-1].split("&")[0]
        elif author_href.startswith("/") and "?" not in author_href:
            author_id = author_href.strip("/")

        # Comment ID — div id attr, else hash of content
        comment_id = div.get("id", "")
        if not comment_id:
            comment_id = hashlib.md5(
                div.get_text(strip=True).encode()
            ).hexdigest()[:16]

        # Text — strip h3 + child divs to isolate the raw text node
        div_copy = copy.copy(div)
        for tag in div_copy.find_all(["h3", "div", "abbr", "br"]):
            tag.decompose()
        text = div_copy.get_text(separator=" ", strip=True)
        if not text:
            return None

        # Timestamp — abbr title is a human-readable datetime string
        created_time = 0
        abbr = div.find("abbr")
        if abbr:
            ts_str = abbr.get("title", "")
            if ts_str:
                try:
                    from dateutil import parser as _dp
                    created_time = int(_dp.parse(ts_str).timestamp())
                except Exception:
                    pass

        # Likes
        likes = 0
        for a in div.find_all("a"):
            href = a.get("href", "")
            if "reaction" in href or "like" in href.lower():
                digits = "".join(filter(str.isdigit, a.get_text()))
                likes  = int(digits) if digits else 0
                break

        return {
            "comment_id":   comment_id,
            "text":         text,
            "created_time": created_time,
            "author_name":  author_name,
            "author_id":    author_id,
            "likes":        likes,
        }

    except Exception:
        return None


def _find_mbasic_comment_blocks(soup: BeautifulSoup) -> list:
    """
    Locate comment divs in mbasic HTML.

    Each comment has an <h3> (author) as a direct child AND an <abbr>
    (timestamp) somewhere inside it. This two-signal pattern has been
    stable across all mbasic versions.
    """
    blocks = []
    for div in soup.find_all("div"):
        if div.find("h3", recursive=False) and div.find("abbr"):
            blocks.append(div)
    return blocks


def _find_mbasic_next_link(soup: BeautifulSoup) -> str | None:
    """
    Find the 'See more comments' / 'View more comments' pagination anchor
    in mbasic HTML. mbasic renders this as a plain <a> — no JS needed.
    """
    for a in soup.find_all("a"):
        text = a.get_text(strip=True).lower()
        href = a.get("href", "")
        if href and any(p in text for p in [
            "more comments", "view more", "see more",
        ]):
            return href
    return None


async def fetch_comments_for_post(
    context: BrowserContext,
    post: dict,
) -> list[dict]:
    """
    Extract comments directly from the DOM via Playwright.

    Facebook renders comment text as server-side HTML in div[dir="auto"].
    This is stable across all post types (posts, reels, groups).
    No GraphQL interception, no mbasic — pure DOM extraction.
    """
    post_url = post.get("post_url", "")
    if not post_url:
        return []

    all_comments: list[dict] = []
    seen_texts: set[str] = set()
    page = await context.new_page()

    try:
        await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000 + random.uniform(0, 1000))

        # Scroll to bottom to trigger comment section lazy-load
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        consecutive_no_new = 0

        while len(all_comments) < MAX_COMMENTS_PER_POST:
            # ── Extract all visible comments from DOM ─────────────────
            # ADD temporarily before the evaluate block:
            dom_info = await page.evaluate("""
                () => {
                    const dialog = document.querySelector('div[role="dialog"]');
                    const articles = document.querySelectorAll('div[role="article"]');
                    const allDirs = document.querySelectorAll('div[dir="auto"]');
                    return {
                        has_dialog: !!dialog,
                        article_count: articles.length,
                        dir_auto_count: allDirs.length,
                        dialog_html_preview: dialog ? dialog.innerHTML.slice(0, 300) : 'no dialog',
                    };
                }
            """)
            print(f"      [DEBUG] DOM: {dom_info}")
            comments_raw = await page.evaluate("""
                () => {
                    const results = [];
                    // Each comment block is a div[role="article"] or
                    // contains a div[dir="auto"] for the comment text.
                    // We walk all aria-label'd comment containers.
                    
                    // Method: find all divs with dir=auto that are 
                    // comment text (not post body).
                    // Comments sit inside the UFI (user feedback interface)
                    // section which appears after the post content.
                    
                    const allDirs = document.querySelectorAll('div[dir="auto"]');
                    for (const el of allDirs) {
                        const text = el.innerText.trim();
                        if (!text || text.length < 2) continue;
                        
                        // Find the nearest ancestor that also contains
                        // an author name (a > span pattern)
                        let container = el.parentElement;
                        let author = '';
                        let depth = 0;
                        while (container && depth < 8) {
                            // Look for a link with a name (author link)
                            const authorEl = container.querySelector(
                                'a[href*="/user/"], a[href*="profile.php"], a[role="link"]'
                            );
                            if (authorEl) {
                                author = authorEl.innerText.trim();
                                if (author) break;
                            }
                            container = container.parentElement;
                            depth++;
                        }
                        
                        // Find timestamp (aria-label on a time-like element)
                        let timestamp = '';
                        let tsEl = el.closest('[data-testid]');
                        if (!tsEl) tsEl = el.parentElement;
                        const spanWithTime = tsEl ? tsEl.querySelector('span[aria-label]') : null;
                        if (spanWithTime) {
                            timestamp = spanWithTime.getAttribute('aria-label') || '';
                        }
                        
                        results.push({ text, author, timestamp });
                    }
                    return results;
                }
            """)

            new_this_round = 0
            for c in comments_raw:
                text = c.get("text", "").strip()
                author = c.get("author", "").strip()
                if not text or text in seen_texts:
                    continue
                # Skip the post body itself (usually longer, first element)
                if not author and len(all_comments) == 0:
                    continue
                seen_texts.add(text)
                import hashlib
                all_comments.append({
                    "comment_id":   hashlib.md5(
                        f"{post.get('post_id')}{text}".encode()
                    ).hexdigest()[:16],
                    "text":         text,
                    "created_time": 0,
                    "author_name":  author,
                    "author_id":    "",
                    "likes":        0,
                })
                new_this_round += 1

            print(f"      [DOM] {new_this_round} new comments "
                  f"(total: {len(all_comments)})")

            if new_this_round == 0:
                consecutive_no_new += 1
                if consecutive_no_new >= 2:
                    break
            else:
                consecutive_no_new = 0

            if len(all_comments) >= MAX_COMMENTS_PER_POST:
                break

            # ── Click "View more comments" ─────────────────────────────
            clicked = False
            for phrase in [
                "View more comments", "See more comments",
                "Load more comments", "View previous comments"
            ]:
                try:
                    btn = page.locator(
                        f'div[role="button"]:has-text("{phrase}")'
                    ).first
                    if await btn.is_visible(timeout=1500):
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        await page.wait_for_timeout(
                            DELAY_COMMENT_CLICK * 1000
                            + random.uniform(0, 500)
                        )
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                break

        total = len(all_comments)
        if total:
            print(f"      💬 {total} comments for post {post.get('post_id')}")
        else:
            print(f"      ℹ️  0 comments for post {post.get('post_id')}")

        await asyncio.sleep(DELAY_BETWEEN_POSTS + random.uniform(-1, 1))

    except Exception as e:
        print(f"      ⚠️  Comment fetch failed: {e}")
    finally:
        try:
            await page.close()
        except Exception:
            pass

    return all_comments[:MAX_COMMENTS_PER_POST]
# ──────────────────────────────────────────────────────────────────────────────
# SECTION 3: SEARCH FEED SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

async def scrape_search_query(
    context: BrowserContext,
    query: str,
) -> list[dict]:
    """
    Search Facebook for a keyword and collect posts via GraphQL interception.

    URL: https://www.facebook.com/search/posts/?q=<query>

    Facebook fires GraphQL requests as the search results feed loads.
    Each scroll triggers another batch. We keep scrolling until we have
    enough posts within the date range or we hit posts older than DATE_FROM.
    """
    print(f"\n[Scraper] Search: '{query}'")
    posts_by_id: dict[str, dict] = {}
    graphql_queue: asyncio.Queue = asyncio.Queue()
    hit_date_floor  = False
    search_url      = f"https://www.facebook.com/search/posts/?q={quote_plus(query)}"

    page = await context.new_page()

    async def handle_response(response: Response):
        if "/api/graphql" in response.url and response.status == 200:
            print(f"      [DEBUG] GraphQL hit: {response.url[:80]}")
            try:
                text = await response.text()
                parsed_count = 0
                has_tdd = False
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        body = json.loads(line)
                        if "topic_deep_dive" in str(body)[:200]:
                            has_tdd = True
                        await graphql_queue.put(body)
                        parsed_count += 1
                    except json.JSONDecodeError:
                        pass
                print(f"      [DEBUG] Lines parsed: {parsed_count}, has topic_deep_dive: {has_tdd}")
            except Exception as e:
                print(f"      [DEBUG] Response read failed: {e}")

    page.on("response", handle_response)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000 + random.uniform(0, 1000))
            # ── Extra wait to ensure initial GraphQL responses arrive ──────────
            await page.wait_for_timeout(3000)   # ADD THIS
            print(f"      [DEBUG] Page title: {await page.title()}")
            print(f"      [DEBUG] Page URL:   {page.url}")
            print(f"      [DEBUG] Queue size after load: {graphql_queue.qsize()}")  # ADD THIS  

            scroll_num = 0
            while (
                len(posts_by_id) < MAX_POSTS_PER_TARGET
                and not hit_date_floor
            ):
                # Drain GraphQL queue
                while not graphql_queue.empty():
                    body = await graphql_queue.get()
                    
                    # ── DEBUG DUMP (remove after diagnosis) ──────────────
                    import pathlib
                    _debug_dir = pathlib.Path("debug_graphql")
                    _debug_dir.mkdir(exist_ok=True)
                    _existing = list(_debug_dir.glob("*.json"))
                    _idx = len(_existing)
                    if _idx < 10:   # cap at 10 files
                        _debug_path = _debug_dir / f"response_{_idx:02d}.json"
                        with open(_debug_path, "w", encoding="utf-8") as _f:
                            json.dump(body, _f, ensure_ascii=False, indent=2)
                    # ── END DEBUG ─────────────────────────────────────────
                    raw_nodes = _extract_posts_from_graphql(body)

                    # REPLACE WITH:
                    for node in raw_nodes:
                        if node.get("_tdd"):
                            # topic_deep_dive story — use dedicated normalizer
                            try:
                                ct = (
                                    node["comet_sections"]["timestamp"]
                                        ["story"]["creation_time"]
                                )
                            except (KeyError, TypeError):
                                ct = 0
                            if ct and ct < _TS_FROM:
                                hit_date_floor = True
                                break
                            post = _normalise_tdd_story(node, "search", query)
                        else:
                            # Legacy node shape (page feeds, older queries)
                            ct = node.get("created_time", 0)
                            if ct and ct < _TS_FROM:
                                hit_date_floor = True
                                break
                            post = _normalise_post_node(node, "search", query)

                        if post and post["post_id"] not in posts_by_id:
                            posts_by_id[post["post_id"]] = post
                            print(
                                f"      [Feed] +1 post "
                                f"(total: {len(posts_by_id)}) "
                                f"— {post['author_name']}"
                            )

                if hit_date_floor or len(posts_by_id) >= MAX_POSTS_PER_TARGET:
                    break

                # Scroll down to load more
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                scroll_num += 1
                await page.wait_for_timeout(
                    DELAY_BETWEEN_SCROLLS * 1000 + random.uniform(0, 800)
                )

                # Safety: stop after many scrolls with nothing new
                if scroll_num > 50:
                    print(f"   ⚠️  Max scroll depth reached for '{query}'")
                    break

            print(f"   ✅ {len(posts_by_id)} posts collected for '{query}'")
            break  # success

        except Exception as e:
            print(f"   ⚠️  Error scraping '{query}' (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RATE_LIMIT_WAIT)
            else:
                print(f"   ❌ Max retries reached for '{query}'")
        finally:
            page.remove_listener("response", handle_response)

    try:
        await page.close()
    except Exception:
        pass

    return list(posts_by_id.values())


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 4: PAGE FEED SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

async def scrape_page_feed(
    context: BrowserContext,
    page_url: str,
) -> list[dict]:
    """
    Scrape posts from a specific Facebook page's timeline.

    Navigates to page_url/posts and intercepts GraphQL feed responses.
    Same scroll-and-collect pattern as the search scraper.
    """
    print(f"\n[Scraper] Page: {page_url}")
    posts_by_id: dict[str, dict] = {}
    graphql_queue: asyncio.Queue = asyncio.Queue()
    hit_date_floor = False
    feed_url       = page_url.rstrip("/") + "/posts"

    page = await context.new_page()

    async def handle_response(response: Response):
        if "/api/graphql" in response.url and response.status == 200:
            try:
                text = await response.text()
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        body = json.loads(line)
                        await graphql_queue.put(body)
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass

    page.on("response", handle_response)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await page.goto(feed_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000 + random.uniform(0, 1000))

            scroll_num = 0
            while (
                len(posts_by_id) < MAX_POSTS_PER_TARGET
                and not hit_date_floor
            ):
                while not graphql_queue.empty():
                    body = await graphql_queue.get()
                    raw_nodes = _extract_posts_from_graphql(body)

                    for node in raw_nodes:
                        ct = node.get("created_time", 0)
                        if ct and ct < _TS_FROM:
                            hit_date_floor = True
                            break
                        post = _normalise_post_node(node, "page_feed", page_url)
                        if post and post["post_id"] not in posts_by_id:
                            posts_by_id[post["post_id"]] = post
                            print(
                                f"      [Page] +1 post "
                                f"(total: {len(posts_by_id)})"
                            )

                if hit_date_floor or len(posts_by_id) >= MAX_POSTS_PER_TARGET:
                    break

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                scroll_num += 1
                await page.wait_for_timeout(
                    DELAY_BETWEEN_SCROLLS * 1000 + random.uniform(0, 800)
                )

                if scroll_num > 50:
                    print(f"   ⚠️  Max scroll depth reached for {page_url}")
                    break

            print(f"   ✅ {len(posts_by_id)} posts collected for {page_url}")
            break

        except Exception as e:
            print(f"   ⚠️  Error scraping {page_url} (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RATE_LIMIT_WAIT)
            else:
                print(f"   ❌ Max retries reached for {page_url}")
        finally:
            page.remove_listener("response", handle_response)

    try:
        await page.close()
    except Exception:
        pass

    return list(posts_by_id.values())


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 5: MASTER SCRAPE
# ──────────────────────────────────────────────────────────────────────────────

async def run_full_scrape() -> list[dict]:
    """
    Run all search queries + page scrapes, then enrich with comments.

    Phase 1: collect post metadata from all search queries and target pages.
    Phase 2: for each post, navigate to post URL and collect comments.

    Both phases share the same BrowserContext so Facebook sees one
    continuous authenticated session.
    """
    check_maintenance_warning()
    all_posts: dict[str, dict] = {}

    async with async_playwright() as playwright:
        context = await create_browser_context(playwright)
        if not context:
            print("❌ Cannot proceed — browser context failed to launch.")
            return []

        # Anchor page — prevents context auto-close
        anchor = await context.new_page()
        await anchor.goto("about:blank")
        print("[Scraper] Anchor page open.\n")

        try:
            # ── Phase 1: collect posts ────────────────────────────────────
            print("=" * 60)
            print("PHASE 1: Collecting post metadata")
            print("=" * 60)

            for query in SEARCH_QUERIES:
                posts = await scrape_search_query(context, query)
                for p in posts:
                    if p["post_id"] not in all_posts:
                        all_posts[p["post_id"]] = p
                await asyncio.sleep(3 + random.uniform(0, 2))

            for page_url in TARGET_PAGES:
                posts = await scrape_page_feed(context, page_url)
                for p in posts:
                    if p["post_id"] not in all_posts:
                        all_posts[p["post_id"]] = p
                await asyncio.sleep(3 + random.uniform(0, 2))

            print(f"\n📊 Phase 1 complete — {len(all_posts)} unique posts found.")

            # ── Phase 2: collect comments per post ───────────────────────
            print("\n" + "=" * 60)
            print("PHASE 2: Collecting comments")
            print("=" * 60)

            posts_list = list(all_posts.values())
            for i, post in enumerate(posts_list, 1):
                print(
                    f"\n[{i:3d}/{len(posts_list)}] "
                    f"{post.get('author_name', '?')} "
                    f"— {post.get('comment_count', 0)} comments expected"
                )
                if not post.get("post_url"):
                    print("      ⚠️  No post URL — skipping comments")
                    continue

                comments = await fetch_comments_for_post(context, post)
                all_posts[post["post_id"]]["comments"] = comments

        finally:
            try:
                await anchor.close()
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass

    result = list(all_posts.values())
    total_comments = sum(len(p.get("comments", [])) for p in result)

    print(f"\n[Scraper] Done.")
    print(f"   📝 Posts:    {len(result)}")
    print(f"   💬 Comments: {total_comments} total")

    return result


# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST
# Run: python -m Scripts.scraper
# ──────────────────────────────────────────────────────────────────────────────

async def _test_single_search():
    """
    Quick smoke-test: search 'Isuzu Kenya', collect first 3 posts,
    then fetch comments for post 1.
    """
    print("=" * 60)
    print("🧪 Facebook Scraper — GraphQL Interception Test")
    print("=" * 60)

    # Temporarily reduce limits for test
    import config as cfg
    orig_max = cfg.MAX_POSTS_PER_TARGET
    cfg.MAX_POSTS_PER_TARGET = 3

    async with async_playwright() as playwright:
        context = await create_browser_context(playwright)
        if not context:
            sys.exit(1)

        try:
            posts = await scrape_search_query(context, "Isuzu Kenya")
            cfg.MAX_POSTS_PER_TARGET = orig_max

            if not posts:
                print(
                    "\n⚠️  No posts collected.\n"
                    "   1. Run: python -m Scripts.auth to verify session\n"
                    "   2. Check Facebook search manually in CfT\n"
                    "   3. GraphQL schema may have changed — check Network tab\n"
                )
                return

            print(f"\n✅ Got {len(posts)} posts")
            for p in posts[:3]:
                print(
                    f"   ID:      {p['post_id']}\n"
                    f"   Author:  {p['author_name']}\n"
                    f"   Text:    {p['text'][:80]}...\n"
                    f"   URL:     {p['post_url']}\n"
                    f"   Reactions: {p['reactions']}\n"
                )

            if posts[0].get("post_url"):
                print(f"[Test] Fetching comments for first post...")
                comments = await fetch_comments_for_post(context, posts[0])
                print(f"\n✅ {len(comments)} comments collected")
                for c in comments[:3]:
                    print(
                        f"   @{c['author_name']}: "
                        f"{c['text'][:60]}... "
                        f"({c['likes']} likes)"
                    )
                print("\n✅ Test passed.\n")

        finally:
            try:
                await context.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(_test_single_search())