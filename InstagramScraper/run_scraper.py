import sys

# Windows consoles default to cp1252, which can't encode the emoji used in
# this scraper's progress prints — reconfigure before anything prints.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from instagram_scraper_python import InstagramScraperEnhanced
from hashtag_discovery import HashtagDiscovery

if __name__ == '__main__':
    scraper = InstagramScraperEnhanced(headless=False)
    discovery = HashtagDiscovery(scraper=scraper)

    result = discovery.scrape_hashtag('isuzukenya', max_recent_posts=3)

    scraper.close()