"""
Auth — loads cookies.json or falls back to credential login.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

import json
import httpx
from twikit import Client
from config import X_USERNAME, X_EMAIL, X_PASSWORD, COOKIES_FILE
from curl_cffi.requests import AsyncSession


def _ensure_cookies_format(cookies_path: str) -> None:
    """
    twikit.load_cookies() expects a flat {name: value} dict.
    If the file is a browser-exported list of objects, convert it.
    Your current cookies.json is already the correct dict format
    so this is a no-op safety guard.
    """
    with open(cookies_path, "r") as f:
        data = json.load(f)

    if isinstance(data, list):
        converted = {
            c["name"]: c["value"]
            for c in data
            if "name" in c and "value" in c
        }
        with open(cookies_path, "w") as f:
            json.dump(converted, f, indent=2)
        print("[Auth] Converted cookie list → dict format.")


async def get_authenticated_client() -> Client:
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    
    # Use curl_cffi session with browser impersonation
    session = AsyncSession(impersonate="chrome120")
    client = Client(language="en-US", proxy=proxy)
    client.http = session  # inject curl_cffi transport
    
    if os.path.exists(COOKIES_FILE):
        print("[Auth] Loading saved cookies...")
        client.load_cookies(COOKIES_FILE)
        print("[Auth] Cookies loaded.")
    else:
        print("[Auth] Logging in with credentials...")
        await client.login(
            auth_info_1=X_USERNAME,
            auth_info_2=X_EMAIL,
            password=X_PASSWORD,
            cookies_file=COOKIES_FILE,
            enable_ui_metrics=True,
        )
        print("[Auth] ✅ Logged in. Cookies saved.")
    
    return client

if __name__ == "__main__":
    async def _test():
        client = await get_authenticated_client()
        user = await client.get_user_by_screen_name(X_USERNAME)
        print(f"[Auth Test] ✅ Logged in as: @{user.screen_name}")

    asyncio.run(_test())