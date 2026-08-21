# test_search.py
import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ScraperCode"))

from ScraperCode.auth import get_authenticated_client

async def test():
    client = await get_authenticated_client()
    
    # Try all product variants
    for product in ["Latest", "Top", "People"]:
        try:
            print(f"\nTrying product='{product}'...")
            results = await client.search_tweet(
                "Isuzu Kenya",
                product=product,
                count=5
            )
            count = 0
            for tweet in results:
                print(f"  ✅ Got tweet: {tweet.id}")
                count += 1
                if count >= 2:
                    break
            print(f"  ✅ product='{product}' WORKS")
            break
        except Exception as e:
            print(f"  ❌ product='{product}' failed: {e}")

asyncio.run(test())