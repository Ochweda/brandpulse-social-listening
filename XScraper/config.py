# X Scraper Config — mirrors your Instagram config structure
import os
from dotenv import load_dotenv

load_dotenv()

X_USERNAME = os.getenv("X_USERNAME")
X_EMAIL    = os.getenv("X_EMAIL")
X_PASSWORD = os.getenv("X_PASSWORD")

COOKIES_FILE = "cookies.json"

# Mirror your Instagram keyword/account targeting
TARGET_KEYWORDS = [
    "Isuzu Kenya",
    "IsuzuKE",
    "#IsuzuKenya",
]

TARGET_ACCOUNTS = [
    "IsuzuKenya",
    # add competitor handles here
]

MAX_TWEETS_PER_QUERY = 50