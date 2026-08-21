"""
Instagram Scraper - ENHANCED VERSION + GEOLOCATION ENRICHMENT
=============================================================
Complete single-file scraper with:
- All existing extraction methods (username, caption, likes, comments, etc.)
- All new fields (author_name, post_date, shares, views, location, post_type, comment_texts)
- Multi-signal geolocation enrichment (8 methods)

Session strategy: persistent Chrome profile (Profile 5).
NO cookie injection — the session lives inside Profile 5's own cookie store.
Log in manually in Profile 5 once, never log out, and this works indefinitely.
"""

import os
import time
import json
import re
import math
import struct
import requests as http_requests
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import Counter
from urllib.parse import unquote


from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException


from brandpulse_enricher import BrandPulseEnricher
from brandpulse_enricher_2 import BrandPulseEnricherV2
from playwright.sync_api import sync_playwright



# ================================================================
# CHROME FOR TESTING CONFIGURATION
# ================================================================
CHROME_FOR_TESTING_EXE     = r"D:\Downloads\PythonScraperPlaywright\chrome\win64-146.0.7680.72\chrome-win64\chrome.exe"
CHROME_FOR_TESTING_PROFILE = r"C:\CfTInstagramProfile"

# ================================================================
# SECTION 1: GEOLOCATION DATA MODELS & DATABASES
# ================================================================

@dataclass
class GeoSignal:
    """A single geolocation signal from one analysis method."""
    location: str
    confidence: float
    source: str
    details: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    raw_matches: List[str] = field(default_factory=list)


@dataclass
class GeoResult:
    """Aggregated geolocation result from all methods."""
    best_location: Optional[str] = None
    best_confidence: float = 0.0
    signals: List[GeoSignal] = field(default_factory=list)
    all_candidates: List[Dict] = field(default_factory=list)
    method_used: str = "none"

    def to_dict(self) -> Dict:
        top_signals = sorted(self.signals, key=lambda s: s.confidence, reverse=True)[:3]
        top_candidates = self.all_candidates[:3]
        return {
            'best_location': self.best_location,
            'best_confidence': round(self.best_confidence, 2),
            'method_used': self.method_used,
            'signals_count': len(self.signals),
            'top_signals': [asdict(s) for s in top_signals],
            'top_candidates': top_candidates
        }


# ----------------------------------------------------------------
# Location databases
# ----------------------------------------------------------------

COUNTRIES = {
    'kenya': {'country': 'Kenya', 'region': 'East Africa'},
    'nigeria': {'country': 'Nigeria', 'region': 'West Africa'},
    'south africa': {'country': 'South Africa', 'region': 'Southern Africa'},
    'tanzania': {'country': 'Tanzania', 'region': 'East Africa'},
    'uganda': {'country': 'Uganda', 'region': 'East Africa'},
    'ethiopia': {'country': 'Ethiopia', 'region': 'East Africa'},
    'ghana': {'country': 'Ghana', 'region': 'West Africa'},
    'rwanda': {'country': 'Rwanda', 'region': 'East Africa'},
    'egypt': {'country': 'Egypt', 'region': 'North Africa'},
    'morocco': {'country': 'Morocco', 'region': 'North Africa'},
    'senegal': {'country': 'Senegal', 'region': 'West Africa'},
    'cameroon': {'country': 'Cameroon', 'region': 'Central Africa'},
    'mozambique': {'country': 'Mozambique', 'region': 'Southern Africa'},
    'zimbabwe': {'country': 'Zimbabwe', 'region': 'Southern Africa'},
    'botswana': {'country': 'Botswana', 'region': 'Southern Africa'},
    'namibia': {'country': 'Namibia', 'region': 'Southern Africa'},
    'zambia': {'country': 'Zambia', 'region': 'Southern Africa'},
    'malawi': {'country': 'Malawi', 'region': 'Southern Africa'},
    'japan': {'country': 'Japan', 'region': 'East Asia'},
    'china': {'country': 'China', 'region': 'East Asia'},
    'india': {'country': 'India', 'region': 'South Asia'},
    'australia': {'country': 'Australia', 'region': 'Oceania'},
    'new zealand': {'country': 'New Zealand', 'region': 'Oceania'},
    'thailand': {'country': 'Thailand', 'region': 'Southeast Asia'},
    'indonesia': {'country': 'Indonesia', 'region': 'Southeast Asia'},
    'philippines': {'country': 'Philippines', 'region': 'Southeast Asia'},
    'malaysia': {'country': 'Malaysia', 'region': 'Southeast Asia'},
    'singapore': {'country': 'Singapore', 'region': 'Southeast Asia'},
    'south korea': {'country': 'South Korea', 'region': 'East Asia'},
    'vietnam': {'country': 'Vietnam', 'region': 'Southeast Asia'},
    'united kingdom': {'country': 'United Kingdom', 'region': 'Europe'},
    'uk': {'country': 'United Kingdom', 'region': 'Europe'},
    'france': {'country': 'France', 'region': 'Europe'},
    'germany': {'country': 'Germany', 'region': 'Europe'},
    'italy': {'country': 'Italy', 'region': 'Europe'},
    'spain': {'country': 'Spain', 'region': 'Europe'},
    'netherlands': {'country': 'Netherlands', 'region': 'Europe'},
    'switzerland': {'country': 'Switzerland', 'region': 'Europe'},
    'sweden': {'country': 'Sweden', 'region': 'Europe'},
    'portugal': {'country': 'Portugal', 'region': 'Europe'},
    'turkey': {'country': 'Turkey', 'region': 'Europe/Asia'},
    'united states': {'country': 'United States', 'region': 'North America'},
    'usa': {'country': 'United States', 'region': 'North America'},
    'canada': {'country': 'Canada', 'region': 'North America'},
    'mexico': {'country': 'Mexico', 'region': 'North America'},
    'brazil': {'country': 'Brazil', 'region': 'South America'},
    'argentina': {'country': 'Argentina', 'region': 'South America'},
    'colombia': {'country': 'Colombia', 'region': 'South America'},
    'chile': {'country': 'Chile', 'region': 'South America'},
    'uae': {'country': 'UAE', 'region': 'Middle East'},
    'dubai': {'country': 'UAE', 'region': 'Middle East'},
    'saudi arabia': {'country': 'Saudi Arabia', 'region': 'Middle East'},
    'qatar': {'country': 'Qatar', 'region': 'Middle East'},
    'israel': {'country': 'Israel', 'region': 'Middle East'},
}

CITIES = {
    # Kenya
    'nairobi': {'city': 'Nairobi', 'country': 'Kenya', 'lat': -1.2921, 'lon': 36.8219, 'tz_offset': 3},
    'mombasa': {'city': 'Mombasa', 'country': 'Kenya', 'lat': -4.0435, 'lon': 39.6682, 'tz_offset': 3},
    'kisumu': {'city': 'Kisumu', 'country': 'Kenya', 'lat': -0.1022, 'lon': 34.7617, 'tz_offset': 3},
    'nakuru': {'city': 'Nakuru', 'country': 'Kenya', 'lat': -0.3031, 'lon': 36.0800, 'tz_offset': 3},
    'eldoret': {'city': 'Eldoret', 'country': 'Kenya', 'lat': 0.5143, 'lon': 35.2698, 'tz_offset': 3},
    'thika': {'city': 'Thika', 'country': 'Kenya', 'lat': -1.0396, 'lon': 37.0900, 'tz_offset': 3},
    'malindi': {'city': 'Malindi', 'country': 'Kenya', 'lat': -3.2138, 'lon': 40.1169, 'tz_offset': 3},
    'nanyuki': {'city': 'Nanyuki', 'country': 'Kenya', 'lat': 0.0067, 'lon': 37.0722, 'tz_offset': 3},
    'nyeri': {'city': 'Nyeri', 'country': 'Kenya', 'lat': -0.4197, 'lon': 36.9511, 'tz_offset': 3},
    'lamu': {'city': 'Lamu', 'country': 'Kenya', 'lat': -2.2717, 'lon': 40.9020, 'tz_offset': 3},
    'naivasha': {'city': 'Naivasha', 'country': 'Kenya', 'lat': -0.7172, 'lon': 36.4310, 'tz_offset': 3},
    'machakos': {'city': 'Machakos', 'country': 'Kenya', 'lat': -1.5177, 'lon': 37.2634, 'tz_offset': 3},
    'garissa': {'city': 'Garissa', 'country': 'Kenya', 'lat': -0.4532, 'lon': 39.6461, 'tz_offset': 3},
    'kitale': {'city': 'Kitale', 'country': 'Kenya', 'lat': 1.0187, 'lon': 35.0020, 'tz_offset': 3},
    # East Africa
    'dar es salaam': {'city': 'Dar es Salaam', 'country': 'Tanzania', 'lat': -6.7924, 'lon': 39.2083, 'tz_offset': 3},
    'kampala': {'city': 'Kampala', 'country': 'Uganda', 'lat': 0.3476, 'lon': 32.5825, 'tz_offset': 3},
    'kigali': {'city': 'Kigali', 'country': 'Rwanda', 'lat': -1.9403, 'lon': 29.8739, 'tz_offset': 2},
    'addis ababa': {'city': 'Addis Ababa', 'country': 'Ethiopia', 'lat': 9.0250, 'lon': 38.7469, 'tz_offset': 3},
    'zanzibar': {'city': 'Zanzibar', 'country': 'Tanzania', 'lat': -6.1659, 'lon': 39.2026, 'tz_offset': 3},
    'arusha': {'city': 'Arusha', 'country': 'Tanzania', 'lat': -3.3869, 'lon': 36.6830, 'tz_offset': 3},
    'juba': {'city': 'Juba', 'country': 'South Sudan', 'lat': 4.8594, 'lon': 31.5713, 'tz_offset': 2},
    # West Africa
    'lagos': {'city': 'Lagos', 'country': 'Nigeria', 'lat': 6.5244, 'lon': 3.3792, 'tz_offset': 1},
    'abuja': {'city': 'Abuja', 'country': 'Nigeria', 'lat': 9.0579, 'lon': 7.4951, 'tz_offset': 1},
    'accra': {'city': 'Accra', 'country': 'Ghana', 'lat': 5.6037, 'lon': -0.1870, 'tz_offset': 0},
    'dakar': {'city': 'Dakar', 'country': 'Senegal', 'lat': 14.7167, 'lon': -17.4677, 'tz_offset': 0},
    # Southern Africa
    'johannesburg': {'city': 'Johannesburg', 'country': 'South Africa', 'lat': -26.2041, 'lon': 28.0473, 'tz_offset': 2},
    'cape town': {'city': 'Cape Town', 'country': 'South Africa', 'lat': -33.9249, 'lon': 18.4241, 'tz_offset': 2},
    'durban': {'city': 'Durban', 'country': 'South Africa', 'lat': -29.8587, 'lon': 31.0218, 'tz_offset': 2},
    'pretoria': {'city': 'Pretoria', 'country': 'South Africa', 'lat': -25.7479, 'lon': 28.2293, 'tz_offset': 2},
    'harare': {'city': 'Harare', 'country': 'Zimbabwe', 'lat': -17.8252, 'lon': 31.0335, 'tz_offset': 2},
    'lusaka': {'city': 'Lusaka', 'country': 'Zambia', 'lat': -15.3875, 'lon': 28.3228, 'tz_offset': 2},
    'gaborone': {'city': 'Gaborone', 'country': 'Botswana', 'lat': -24.6282, 'lon': 25.9231, 'tz_offset': 2},
    'maputo': {'city': 'Maputo', 'country': 'Mozambique', 'lat': -25.9692, 'lon': 32.5732, 'tz_offset': 2},
    'windhoek': {'city': 'Windhoek', 'country': 'Namibia', 'lat': -22.5609, 'lon': 17.0658, 'tz_offset': 2},
    # Global
    'london': {'city': 'London', 'country': 'UK', 'lat': 51.5074, 'lon': -0.1278, 'tz_offset': 0},
    'new york': {'city': 'New York', 'country': 'USA', 'lat': 40.7128, 'lon': -74.0060, 'tz_offset': -5},
    'los angeles': {'city': 'Los Angeles', 'country': 'USA', 'lat': 34.0522, 'lon': -118.2437, 'tz_offset': -8},
    'chicago': {'city': 'Chicago', 'country': 'USA', 'lat': 41.8781, 'lon': -87.6298, 'tz_offset': -6},
    'san francisco': {'city': 'San Francisco', 'country': 'USA', 'lat': 37.7749, 'lon': -122.4194, 'tz_offset': -8},
    'paris': {'city': 'Paris', 'country': 'France', 'lat': 48.8566, 'lon': 2.3522, 'tz_offset': 1},
    'tokyo': {'city': 'Tokyo', 'country': 'Japan', 'lat': 35.6762, 'lon': 139.6503, 'tz_offset': 9},
    'sydney': {'city': 'Sydney', 'country': 'Australia', 'lat': -33.8688, 'lon': 151.2093, 'tz_offset': 10},
    'melbourne': {'city': 'Melbourne', 'country': 'Australia', 'lat': -37.8136, 'lon': 144.9631, 'tz_offset': 10},
    'dubai': {'city': 'Dubai', 'country': 'UAE', 'lat': 25.2048, 'lon': 55.2708, 'tz_offset': 4},
    'mumbai': {'city': 'Mumbai', 'country': 'India', 'lat': 19.0760, 'lon': 72.8777, 'tz_offset': 5.5},
    'delhi': {'city': 'Delhi', 'country': 'India', 'lat': 28.7041, 'lon': 77.1025, 'tz_offset': 5.5},
    'beijing': {'city': 'Beijing', 'country': 'China', 'lat': 39.9042, 'lon': 116.4074, 'tz_offset': 8},
    'shanghai': {'city': 'Shanghai', 'country': 'China', 'lat': 31.2304, 'lon': 121.4737, 'tz_offset': 8},
    'bangkok': {'city': 'Bangkok', 'country': 'Thailand', 'lat': 13.7563, 'lon': 100.5018, 'tz_offset': 7},
    'singapore': {'city': 'Singapore', 'country': 'Singapore', 'lat': 1.3521, 'lon': 103.8198, 'tz_offset': 8},
    'berlin': {'city': 'Berlin', 'country': 'Germany', 'lat': 52.5200, 'lon': 13.4050, 'tz_offset': 1},
    'amsterdam': {'city': 'Amsterdam', 'country': 'Netherlands', 'lat': 52.3676, 'lon': 4.9041, 'tz_offset': 1},
    'toronto': {'city': 'Toronto', 'country': 'Canada', 'lat': 43.6532, 'lon': -79.3832, 'tz_offset': -5},
    'sao paulo': {'city': 'São Paulo', 'country': 'Brazil', 'lat': -23.5505, 'lon': -46.6333, 'tz_offset': -3},
    'cairo': {'city': 'Cairo', 'country': 'Egypt', 'lat': 30.0444, 'lon': 31.2357, 'tz_offset': 2},
    'istanbul': {'city': 'Istanbul', 'country': 'Turkey', 'lat': 41.0082, 'lon': 28.9784, 'tz_offset': 3},
    'seoul': {'city': 'Seoul', 'country': 'South Korea', 'lat': 37.5665, 'lon': 126.9780, 'tz_offset': 9},
    'jakarta': {'city': 'Jakarta', 'country': 'Indonesia', 'lat': -6.2088, 'lon': 106.8456, 'tz_offset': 7},
    'manila': {'city': 'Manila', 'country': 'Philippines', 'lat': 14.5995, 'lon': 120.9842, 'tz_offset': 8},
    'hong kong': {'city': 'Hong Kong', 'country': 'China', 'lat': 22.3193, 'lon': 114.1694, 'tz_offset': 8},
    'rome': {'city': 'Rome', 'country': 'Italy', 'lat': 41.9028, 'lon': 12.4964, 'tz_offset': 1},
    'madrid': {'city': 'Madrid', 'country': 'Spain', 'lat': 40.4168, 'lon': -3.7038, 'tz_offset': 1},
    'barcelona': {'city': 'Barcelona', 'country': 'Spain', 'lat': 41.3851, 'lon': 2.1734, 'tz_offset': 1},
    'moscow': {'city': 'Moscow', 'country': 'Russia', 'lat': 55.7558, 'lon': 37.6173, 'tz_offset': 3},
    'riyadh': {'city': 'Riyadh', 'country': 'Saudi Arabia', 'lat': 24.7136, 'lon': 46.6753, 'tz_offset': 3},
}

TIMEZONE_REGIONS = {
    -10: ['Hawaii, USA'],
    -9: ['Alaska, USA'],
    -8: ['US West Coast', 'Pacific Time'],
    -7: ['US Mountain', 'Mountain Time'],
    -6: ['US Central', 'Central Time', 'Mexico City'],
    -5: ['US East Coast', 'Eastern Time', 'Colombia', 'Peru'],
    -4: ['Atlantic Time', 'Venezuela', 'Bolivia'],
    -3: ['Brazil', 'Argentina', 'Chile'],
    -2: ['Mid-Atlantic'],
    -1: ['Azores', 'Cape Verde'],
    0: ['UK', 'Ghana', 'Iceland', 'Portugal', 'West Africa (GMT)'],
    1: ['Central Europe', 'Nigeria', 'West Africa (WAT)', 'France', 'Germany'],
    2: ['Eastern Europe', 'South Africa', 'Egypt', 'Central Africa'],
    3: ['East Africa', 'Kenya', 'Saudi Arabia', 'Turkey', 'Russia (Moscow)'],
    4: ['UAE', 'Oman', 'Mauritius'],
    5: ['Pakistan', 'Uzbekistan'],
    5.5: ['India', 'Sri Lanka'],
    6: ['Bangladesh', 'Kazakhstan'],
    7: ['Thailand', 'Vietnam', 'Indonesia (WIB)'],
    8: ['China', 'Singapore', 'Malaysia', 'Philippines', 'Australia (AWST)'],
    9: ['Japan', 'South Korea'],
    10: ['Australia (AEST)', 'Papua New Guinea'],
    11: ['Solomon Islands', 'Vanuatu'],
    12: ['New Zealand', 'Fiji'],
}

LOCATION_HASHTAG_PATTERNS = [
    r'^#(nairobi|mombasa|kisumu|nakuru|eldoret|kenya)',
    r'^#(lagos|abuja|nigeria|accra|ghana)',
    r'^#(johannesburg|joburg|capetown|durban|southafrica)',
    r'^#(london|manchester|birmingham|uk|britain)',
    r'^#(newyork|nyc|losangeles|la|chicago|sanfrancisco|sf)',
    r'^#(tokyo|osaka|japan|seoul|korea)',
    r'^#(sydney|melbourne|brisbane|perth|australia)',
    r'^#(dubai|abudhabi|uae|riyadh|saudiarabia)',
    r'^#(paris|france|berlin|germany|amsterdam|netherlands)',
    r'^#visit(\w+)',
    r'^#explore(\w+)',
    r'^#(\w+)life$',
    r'^#(\w+)city$',
    r'^#(\w+)gram$',
    r'^#madein(\w+)',
    r'^#(eastafrica|westafrica|southernafrica|northafrica)',
    r'^#(africanmade|madeinafrica|africanbrand)',
    r'^#(\w+)kenya$',
    r'^#kenya(\w+)',
]

LOCATION_HASHTAGS = {
    '#nairobi': 'Nairobi, Kenya', '#nairobikenya': 'Nairobi, Kenya',
    '#nairobicity': 'Nairobi, Kenya', '#mombasa': 'Mombasa, Kenya',
    '#kenya': 'Kenya', '#kenyangirl': 'Kenya', '#kenyanboy': 'Kenya',
    '#visitkenya': 'Kenya', '#magicalkenya': 'Kenya', '#tembeakenya': 'Kenya',
    '#lagos': 'Lagos, Nigeria', '#nigeria': 'Nigeria',
    '#accra': 'Accra, Ghana', '#ghana': 'Ghana',
    '#johannesburg': 'Johannesburg, South Africa', '#joburg': 'Johannesburg, South Africa',
    '#capetown': 'Cape Town, South Africa', '#southafrica': 'South Africa',
    '#kampala': 'Kampala, Uganda', '#uganda': 'Uganda',
    '#daressalaam': 'Dar es Salaam, Tanzania', '#tanzania': 'Tanzania',
    '#kigali': 'Kigali, Rwanda', '#rwanda': 'Rwanda',
    '#addisababa': 'Addis Ababa, Ethiopia', '#ethiopia': 'Ethiopia',
    '#london': 'London, UK', '#nyc': 'New York, USA',
    '#newyork': 'New York, USA', '#losangeles': 'Los Angeles, USA',
    '#la': 'Los Angeles, USA', '#tokyo': 'Tokyo, Japan',
    '#sydney': 'Sydney, Australia', '#melbourne': 'Melbourne, Australia',
    '#dubai': 'Dubai, UAE', '#paris': 'Paris, France', '#berlin': 'Berlin, Germany',
    '#jdm': 'Japan', '#jdmlife': 'Japan', '#jdmlegends': 'Japan',
    '#jdmnation': 'Japan', '#jdmdiecast': 'Japan', '#jdmdaily': 'Japan',
}

USERNAME_LOCATION_KEYWORDS = {
    'australasia': {'location': 'Australasia (Australia/New Zealand)', 'confidence': 0.65, 'type': 'region'},
    'eastafrica': {'location': 'East Africa', 'confidence': 0.55, 'type': 'region'},
    'westafrica': {'location': 'West Africa', 'confidence': 0.55, 'type': 'region'},
    'southernafrica': {'location': 'Southern Africa', 'confidence': 0.55, 'type': 'region'},
    'middleeast': {'location': 'Middle East', 'confidence': 0.50, 'type': 'region'},
    'southeast_asia': {'location': 'Southeast Asia', 'confidence': 0.50, 'type': 'region'},
    'southeastasia': {'location': 'Southeast Asia', 'confidence': 0.50, 'type': 'region'},
    'latinamerica': {'location': 'Latin America', 'confidence': 0.50, 'type': 'region'},
    'nordic': {'location': 'Scandinavia', 'confidence': 0.45, 'type': 'region'},
    'caribbean': {'location': 'Caribbean', 'confidence': 0.50, 'type': 'region'},
    'pacific': {'location': 'Pacific Region', 'confidence': 0.35, 'type': 'region'},
    'oceania': {'location': 'Oceania', 'confidence': 0.50, 'type': 'region'},
    'subsaharan': {'location': 'Sub-Saharan Africa', 'confidence': 0.50, 'type': 'region'},
    'kenya': {'location': 'Kenya', 'confidence': 0.65, 'type': 'country'},
    'kenyan': {'location': 'Kenya', 'confidence': 0.65, 'type': 'country'},
    'naija': {'location': 'Nigeria', 'confidence': 0.70, 'type': 'country'},
    'nigeria': {'location': 'Nigeria', 'confidence': 0.65, 'type': 'country'},
    'nigerian': {'location': 'Nigeria', 'confidence': 0.65, 'type': 'country'},
    'southafrica': {'location': 'South Africa', 'confidence': 0.65, 'type': 'country'},
    'tanzania': {'location': 'Tanzania', 'confidence': 0.65, 'type': 'country'},
    'uganda': {'location': 'Uganda', 'confidence': 0.65, 'type': 'country'},
    'ethiopia': {'location': 'Ethiopia', 'confidence': 0.65, 'type': 'country'},
    'ghana': {'location': 'Ghana', 'confidence': 0.65, 'type': 'country'},
    'rwanda': {'location': 'Rwanda', 'confidence': 0.65, 'type': 'country'},
    'zambia': {'location': 'Zambia', 'confidence': 0.60, 'type': 'country'},
    'zimbabwe': {'location': 'Zimbabwe', 'confidence': 0.60, 'type': 'country'},
    'botswana': {'location': 'Botswana', 'confidence': 0.60, 'type': 'country'},
    'mozambique': {'location': 'Mozambique', 'confidence': 0.60, 'type': 'country'},
    'namibia': {'location': 'Namibia', 'confidence': 0.60, 'type': 'country'},
    'senegal': {'location': 'Senegal', 'confidence': 0.60, 'type': 'country'},
    'cameroon': {'location': 'Cameroon', 'confidence': 0.60, 'type': 'country'},
    'australia': {'location': 'Australia', 'confidence': 0.65, 'type': 'country'},
    'aussie': {'location': 'Australia', 'confidence': 0.65, 'type': 'country'},
    'newzealand': {'location': 'New Zealand', 'confidence': 0.65, 'type': 'country'},
    'japan': {'location': 'Japan', 'confidence': 0.60, 'type': 'country'},
    'japanese': {'location': 'Japan', 'confidence': 0.60, 'type': 'country'},
    'brasil': {'location': 'Brazil', 'confidence': 0.65, 'type': 'country'},
    'brazil': {'location': 'Brazil', 'confidence': 0.60, 'type': 'country'},
    'mexico': {'location': 'Mexico', 'confidence': 0.55, 'type': 'country'},
    'mexicano': {'location': 'Mexico', 'confidence': 0.65, 'type': 'country'},
    'canada': {'location': 'Canada', 'confidence': 0.55, 'type': 'country'},
    'canadian': {'location': 'Canada', 'confidence': 0.60, 'type': 'country'},
    'indonesia': {'location': 'Indonesia', 'confidence': 0.60, 'type': 'country'},
    'filipino': {'location': 'Philippines', 'confidence': 0.65, 'type': 'country'},
    'pinoy': {'location': 'Philippines', 'confidence': 0.70, 'type': 'country'},
    'thailand': {'location': 'Thailand', 'confidence': 0.60, 'type': 'country'},
    'korean': {'location': 'South Korea', 'confidence': 0.55, 'type': 'country'},
    'indian': {'location': 'India', 'confidence': 0.50, 'type': 'country'},
    'deutsch': {'location': 'Germany', 'confidence': 0.60, 'type': 'country'},
    'british': {'location': 'United Kingdom', 'confidence': 0.55, 'type': 'country'},
    'nairobi': {'location': 'Nairobi, Kenya', 'confidence': 0.75, 'type': 'city'},
    'mombasa': {'location': 'Mombasa, Kenya', 'confidence': 0.75, 'type': 'city'},
    'kisumu': {'location': 'Kisumu, Kenya', 'confidence': 0.75, 'type': 'city'},
    'nakuru': {'location': 'Nakuru, Kenya', 'confidence': 0.75, 'type': 'city'},
    'eldoret': {'location': 'Eldoret, Kenya', 'confidence': 0.75, 'type': 'city'},
    'lagos': {'location': 'Lagos, Nigeria', 'confidence': 0.70, 'type': 'city'},
    'abuja': {'location': 'Abuja, Nigeria', 'confidence': 0.75, 'type': 'city'},
    'accra': {'location': 'Accra, Ghana', 'confidence': 0.75, 'type': 'city'},
    'joburg': {'location': 'Johannesburg, South Africa', 'confidence': 0.75, 'type': 'city'},
    'johannesburg': {'location': 'Johannesburg, South Africa', 'confidence': 0.75, 'type': 'city'},
    'capetown': {'location': 'Cape Town, South Africa', 'confidence': 0.75, 'type': 'city'},
    'durban': {'location': 'Durban, South Africa', 'confidence': 0.75, 'type': 'city'},
    'kampala': {'location': 'Kampala, Uganda', 'confidence': 0.75, 'type': 'city'},
    'kigali': {'location': 'Kigali, Rwanda', 'confidence': 0.75, 'type': 'city'},
    'daressalaam': {'location': 'Dar es Salaam, Tanzania', 'confidence': 0.75, 'type': 'city'},
    'london': {'location': 'London, UK', 'confidence': 0.60, 'type': 'city'},
    'nyc': {'location': 'New York, USA', 'confidence': 0.70, 'type': 'city'},
    'newyork': {'location': 'New York, USA', 'confidence': 0.65, 'type': 'city'},
    'losangeles': {'location': 'Los Angeles, USA', 'confidence': 0.65, 'type': 'city'},
    'chicago': {'location': 'Chicago, USA', 'confidence': 0.60, 'type': 'city'},
    'sanfrancisco': {'location': 'San Francisco, USA', 'confidence': 0.65, 'type': 'city'},
    'tokyo': {'location': 'Tokyo, Japan', 'confidence': 0.65, 'type': 'city'},
    'sydney': {'location': 'Sydney, Australia', 'confidence': 0.65, 'type': 'city'},
    'melbourne': {'location': 'Melbourne, Australia', 'confidence': 0.60, 'type': 'city'},
    'dubai': {'location': 'Dubai, UAE', 'confidence': 0.65, 'type': 'city'},
    'mumbai': {'location': 'Mumbai, India', 'confidence': 0.70, 'type': 'city'},
    'delhi': {'location': 'Delhi, India', 'confidence': 0.60, 'type': 'city'},
    'bangkok': {'location': 'Bangkok, Thailand', 'confidence': 0.70, 'type': 'city'},
    'paris': {'location': 'Paris, France', 'confidence': 0.50, 'type': 'city'},
    'berlin': {'location': 'Berlin, Germany', 'confidence': 0.55, 'type': 'city'},
    'istanbul': {'location': 'Istanbul, Turkey', 'confidence': 0.65, 'type': 'city'},
    'toronto': {'location': 'Toronto, Canada', 'confidence': 0.65, 'type': 'city'},
    'vancouver': {'location': 'Vancouver, Canada', 'confidence': 0.65, 'type': 'city'},
    'seattle': {'location': 'Seattle, USA', 'confidence': 0.65, 'type': 'city'},
    'houston': {'location': 'Houston, USA', 'confidence': 0.55, 'type': 'city'},
    'atlanta': {'location': 'Atlanta, USA', 'confidence': 0.60, 'type': 'city'},
    'miami': {'location': 'Miami, USA', 'confidence': 0.60, 'type': 'city'},
    'denver': {'location': 'Denver, USA', 'confidence': 0.55, 'type': 'city'},
    'jakarta': {'location': 'Jakarta, Indonesia', 'confidence': 0.70, 'type': 'city'},
    'manila': {'location': 'Manila, Philippines', 'confidence': 0.65, 'type': 'city'},
    'hongkong': {'location': 'Hong Kong, China', 'confidence': 0.70, 'type': 'city'},
    'singapore': {'location': 'Singapore', 'confidence': 0.65, 'type': 'city'},
    'cairo': {'location': 'Cairo, Egypt', 'confidence': 0.65, 'type': 'city'},
    'riyadh': {'location': 'Riyadh, Saudi Arabia', 'confidence': 0.70, 'type': 'city'},
    'mzansi': {'location': 'South Africa', 'confidence': 0.75, 'type': 'slang'},
    'saffa': {'location': 'South Africa', 'confidence': 0.70, 'type': 'slang'},
    'bongo': {'location': 'Tanzania', 'confidence': 0.60, 'type': 'slang'},
    'kiwi': {'location': 'New Zealand', 'confidence': 0.55, 'type': 'slang'},
    'pinay': {'location': 'Philippines', 'confidence': 0.70, 'type': 'slang'},
    'desi': {'location': 'South Asia (India/Pakistan)', 'confidence': 0.50, 'type': 'slang'},
    'tico': {'location': 'Costa Rica', 'confidence': 0.65, 'type': 'slang'},
    'gringo': {'location': 'Latin America', 'confidence': 0.40, 'type': 'slang'},
    '_ke': {'location': 'Kenya', 'confidence': 0.60, 'type': 'code'},
    '_ng': {'location': 'Nigeria', 'confidence': 0.60, 'type': 'code'},
    '_za': {'location': 'South Africa', 'confidence': 0.60, 'type': 'code'},
    '_tz': {'location': 'Tanzania', 'confidence': 0.60, 'type': 'code'},
    '_ug': {'location': 'Uganda', 'confidence': 0.60, 'type': 'code'},
    '_gh': {'location': 'Ghana', 'confidence': 0.60, 'type': 'code'},
    '_uk': {'location': 'United Kingdom', 'confidence': 0.55, 'type': 'code'},
    '_au': {'location': 'Australia', 'confidence': 0.55, 'type': 'code'},
    '_jp': {'location': 'Japan', 'confidence': 0.55, 'type': 'code'},
    '_de': {'location': 'Germany', 'confidence': 0.55, 'type': 'code'},
    '_fr': {'location': 'France', 'confidence': 0.55, 'type': 'code'},
    '_br': {'location': 'Brazil', 'confidence': 0.55, 'type': 'code'},
    '_ca': {'location': 'Canada', 'confidence': 0.50, 'type': 'code'},
    '_in': {'location': 'India', 'confidence': 0.50, 'type': 'code'},
    '_ph': {'location': 'Philippines', 'confidence': 0.55, 'type': 'code'},
    '_id': {'location': 'Indonesia', 'confidence': 0.50, 'type': 'code'},
    '_sg': {'location': 'Singapore', 'confidence': 0.55, 'type': 'code'},
    '_ae': {'location': 'UAE', 'confidence': 0.55, 'type': 'code'},
    '_sa': {'location': 'Saudi Arabia', 'confidence': 0.50, 'type': 'code'},
    '_nz': {'location': 'New Zealand', 'confidence': 0.55, 'type': 'code'},
}


# ================================================================
# SECTION 2: PLAYWRIGHT → SELENIUM SHIM
# ================================================================
# Translates Selenium-style calls (find_element, By.XPATH, etc.)
# into Playwright equivalents, so all extraction methods work unchanged.

def _pw_selector(by, value: str) -> str:
    """Convert a Selenium By + value into a Playwright selector string."""
    if by == By.XPATH:
        return f"xpath={value}"
    elif by == By.TAG_NAME:
        # Tag names are valid CSS selectors as-is
        return value
    else:
        # CSS_SELECTOR, ID, CLASS_NAME etc. all work as CSS in Playwright
        return value


class PlaywrightElementShim:
    """Wraps a Playwright Locator to look like a Selenium WebElement."""

    def __init__(self, locator, page):
        self._loc = locator
        self._page = page

    @property
    def text(self) -> str:
        try:
            return self._loc.inner_text(timeout=3000)
        except Exception:
            return ""

    def get_attribute(self, name: str) -> Optional[str]:
        try:
            return self._loc.get_attribute(name, timeout=3000)
        except Exception:
            return None

    def click(self):
        self._loc.click(timeout=3000)

    def find_element(self, by, value: str) -> "PlaywrightElementShim":
        sel = _pw_selector(by, value)
        return PlaywrightElementShim(self._loc.locator(sel).first, self._page)

    def find_elements(self, by, value: str) -> List["PlaywrightElementShim"]:
        sel = _pw_selector(by, value)
        try:
            return [PlaywrightElementShim(el, self._page)
                    for el in self._loc.locator(sel).all()]
        except Exception:
            return []


class PlaywrightDriverShim:
    """Wraps a Playwright Page to look like a Selenium WebDriver."""

    def __init__(self, page):
        self._page = page

    @property
    def current_url(self) -> str:
        return self._page.url

    def get(self, url: str):
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)

    def find_element(self, by, value: str) -> PlaywrightElementShim:
        sel = _pw_selector(by, value)
        return PlaywrightElementShim(self._page.locator(sel).first, self._page)

    def find_elements(self, by, value: str) -> List[PlaywrightElementShim]:
        sel = _pw_selector(by, value)
        try:
            return [PlaywrightElementShim(el, self._page)
                    for el in self._page.locator(sel).all()]
        except Exception:
            return []

    def execute_script(self, script: str, *args):
        return self._page.evaluate(script)

    def set_window_size(self, w: int, h: int):
        self._page.set_viewport_size({"width": w, "height": h})

    def save_screenshot(self, path: str):
        try:
            self._page.screenshot(path=path)
            print(f"   📸 Screenshot saved: {path}")
        except Exception as e:
            print(f"   ⚠️  Screenshot failed: {e}")

    def implicitly_wait(self, seconds: int):
        pass  # Playwright handles waits differently

    def refresh(self):
        self._page.reload(wait_until="domcontentloaded", timeout=30000)

    @property
    def page_source(self) -> str:
        return self._page.content()

    def quit(self):
        # Handled by InstagramScraperEnhanced.close() via self._context
        pass


# ================================================================
# SECTION 3: GEOLOCATION ENRICHER CLASS
# ================================================================

class GeoLocationEnricher:
    def __init__(self, driver=None, claude_api_key: Optional[str] = None):
        self.driver = driver
        self.claude_api_key = claude_api_key

    def analyze_caption_text(self, caption: str) -> List[GeoSignal]:
        print("\n🔍 GEO METHOD 1: CAPTION TEXT ANALYSIS")
        print(f"   Analyzing caption ({len(caption)} chars)...")
        signals = []
        if not caption:
            print("   ⚠️  No caption to analyze")
            return signals
        caption_lower = caption.lower()
        for city_key, city_data in CITIES.items():
            if re.search(r'\b' + re.escape(city_key) + r'\b', caption_lower):
                signals.append(GeoSignal(location=f"{city_data['city']}, {city_data['country']}", confidence=0.7, source='caption_text_city', details=f"City '{city_key}' in caption", latitude=city_data.get('lat'), longitude=city_data.get('lon'), raw_matches=[city_key]))
                print(f"   ✅ City: '{city_key}' → {city_data['city']}, {city_data['country']}")
        for country_key, country_data in COUNTRIES.items():
            if re.search(r'\b' + re.escape(country_key) + r'\b', caption_lower):
                signals.append(GeoSignal(location=country_data['country'], confidence=0.6, source='caption_text_country', details=f"Country '{country_key}' in caption", raw_matches=[country_key]))
                print(f"   ✅ Country: '{country_key}' → {country_data['country']}")
        prep_patterns = [
            (r'\b(?:in|from|at|near|visiting|based in|located in|live in|living in)\s+([A-Z][a-zA-Z\s]{2,25})', 0.75),
            (r'\b(?:shipped from|made in|built in|crafted in|manufactured in)\s+([A-Z][a-zA-Z\s]{2,25})', 0.65),
            (r'\b(?:available in|coming to|now in|launching in)\s+([A-Z][a-zA-Z\s]{2,25})', 0.50),
        ]
        for pattern, conf in prep_patterns:
            for match_text in re.findall(pattern, caption):
                match_lower = match_text.strip().rstrip('.,!?;:').lower()
                verified = None
                if match_lower in CITIES:
                    c = CITIES[match_lower]; verified = f"{c['city']}, {c['country']}"; conf = min(conf + 0.1, 0.95)
                elif match_lower in COUNTRIES:
                    verified = COUNTRIES[match_lower]['country']; conf = min(conf + 0.1, 0.95)
                if verified:
                    signals.append(GeoSignal(location=verified, confidence=conf, source='caption_text_preposition', details=f"Pattern: '...{match_text.strip()}'", raw_matches=[match_text.strip()]))
                    print(f"   ✅ Preposition: '{match_text.strip()}' → {verified}")
        for pattern, region, conf, name in [
            (r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', 'Japan/China', 0.3, 'CJK'),
            (r'[\uAC00-\uD7AF]', 'South Korea', 0.35, 'Korean'),
            (r'[\u0600-\u06FF]', 'Middle East/North Africa', 0.25, 'Arabic'),
            (r'[\u0E00-\u0E7F]', 'Thailand', 0.35, 'Thai'),
            (r'[\u0900-\u097F]', 'India', 0.3, 'Devanagari'),
            (r'[\u0410-\u044F]', 'Russia/Eastern Europe', 0.25, 'Cyrillic'),
        ]:
            if re.search(pattern, caption):
                signals.append(GeoSignal(location=region, confidence=conf, source='caption_text_language', details=f"{name} script detected", raw_matches=[f"[{name}]"]))
                print(f"   ✅ Language: {name} → {region}")
        if not signals:
            print("   ℹ️  No location signals in caption")
        return signals

    def analyze_hashtags(self, hashtags: List[str]) -> List[GeoSignal]:
        print("\n🏷️  GEO METHOD 2: HASHTAG ANALYSIS")
        print(f"   Analyzing {len(hashtags)} hashtags...")
        signals = []
        if not hashtags:
            print("   ⚠️  No hashtags"); return signals
        location_hits = Counter()
        all_raw = {}
        for tag in hashtags:
            tag_lower = tag.lower().strip()
            try: tag_decoded = unquote(tag_lower)
            except: tag_decoded = tag_lower
            if tag_decoded in LOCATION_HASHTAGS:
                loc = LOCATION_HASHTAGS[tag_decoded]; location_hits[loc] += 1; all_raw.setdefault(loc, []).append(tag)
            tag_clean = tag_decoded.replace('#', '')
            for city_key, city_data in CITIES.items():
                if city_key.replace(' ', '') in tag_clean and len(tag_clean) < 30:
                    loc = f"{city_data['city']}, {city_data['country']}"; location_hits[loc] += 1; all_raw.setdefault(loc, []).append(tag)
            for country_key, country_data in COUNTRIES.items():
                if country_key.replace(' ', '') in tag_clean and len(tag_clean) < 25:
                    loc = country_data['country']; location_hits[loc] += 0.5; all_raw.setdefault(loc, []).append(tag)
            for pattern in LOCATION_HASHTAG_PATTERNS:
                match = re.match(pattern, tag_decoded, re.IGNORECASE)
                if match:
                    matched = (match.group(1) if match.lastindex else match.group(0)).lower()
                    if matched in CITIES:
                        c = CITIES[matched]; loc = f"{c['city']}, {c['country']}"; location_hits[loc] += 0.75; all_raw.setdefault(loc, []).append(tag)
                    elif matched in COUNTRIES:
                        loc = COUNTRIES[matched]['country']; location_hits[loc] += 0.5; all_raw.setdefault(loc, []).append(tag)
        for loc, count in location_hits.most_common():
            conf = min(0.35 + (count * 0.15), 0.85)
            signals.append(GeoSignal(location=loc, confidence=round(conf, 2), source='hashtag_analysis', details=f"{int(count)} hashtag(s)", raw_matches=list(set(all_raw.get(loc, [])))))
            print(f"   ✅ {loc} (count: {count}, conf: {conf:.2f})")
        if not signals: print("   ℹ️  No location signals in hashtags")
        return signals

    def analyze_profile_metadata(self, username: str) -> List[GeoSignal]:
        print(f"\n👤 GEO METHOD 3: PROFILE METADATA ({username})")
        signals = []
        if not self.driver: print("   ⚠️  No driver — skipping"); return signals
        try:
            current_url = self.driver.current_url
            if username not in current_url:
                self.driver.get(f"https://www.instagram.com/{username}/"); time.sleep(5)
            bio_text = ""
            try:
                for selector in ['div.-vDIg span', 'span._ap3a._aaco._aacu._aacx._aad6._aade', 'section > div > span', 'header section span']:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        text = elem.text.strip()
                        if text and 20 < len(text) < 500 and not text.isdigit() and text.lower() not in ['follow', 'following', 'message', 'edit profile']:
                            bio_text = text; break
                    if bio_text: break
                if not bio_text:
                    try:
                        meta = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:description"]')
                        parts = meta.get_attribute('content').split(' - ', 1)
                        if len(parts) > 1: bio_text = parts[1].strip()
                    except: pass
            except: pass
            if bio_text:
                print(f"   📄 Bio: {bio_text[:100]}...")
                bio_lower = bio_text.lower()
                for city_key, city_data in CITIES.items():
                    if re.search(r'\b' + re.escape(city_key) + r'\b', bio_lower):
                        signals.append(GeoSignal(location=f"{city_data['city']}, {city_data['country']}", confidence=0.75, source='profile_bio_city', details=f"City '{city_key}' in bio", latitude=city_data.get('lat'), longitude=city_data.get('lon'), raw_matches=[city_key]))
                        print(f"   ✅ Bio city: {city_data['city']}, {city_data['country']}")
                for country_key, country_data in COUNTRIES.items():
                    if re.search(r'\b' + re.escape(country_key) + r'\b', bio_lower):
                        signals.append(GeoSignal(location=country_data['country'], confidence=0.6, source='profile_bio_country', details=f"Country '{country_key}' in bio", raw_matches=[country_key]))
                        print(f"   ✅ Bio country: {country_data['country']}")
                for pattern, conf, label in [
                    (r'📍\s*([A-Za-z\s,]{3,30})', 0.85, 'pin emoji'),
                    (r'based in\s+([A-Za-z\s,]{3,30})', 0.80, 'based in'),
                    (r'located in\s+([A-Za-z\s,]{3,30})', 0.80, 'located in'),
                    (r'from\s+([A-Za-z\s,]{3,30})', 0.60, 'from'),
                    (r'living in\s+([A-Za-z\s,]{3,30})', 0.75, 'living in'),
                ]:
                    match = re.search(pattern, bio_text, re.IGNORECASE)
                    if match:
                        loc = match.group(1).strip().rstrip('.,!|•')
                        signals.append(GeoSignal(location=loc, confidence=conf, source='profile_bio_pattern', details=f"Bio: '{label}' → '{loc}'", raw_matches=[match.group(0)]))
                        print(f"   ✅ Bio pattern: '{label}' → {loc}")
                for flag, country in {'🇰🇪': 'Kenya', '🇳🇬': 'Nigeria', '🇿🇦': 'South Africa', '🇹🇿': 'Tanzania', '🇺🇬': 'Uganda', '🇷🇼': 'Rwanda', '🇪🇹': 'Ethiopia', '🇬🇭': 'Ghana', '🇪🇬': 'Egypt', '🇺🇸': 'United States', '🇬🇧': 'United Kingdom', '🇫🇷': 'France', '🇩🇪': 'Germany', '🇯🇵': 'Japan', '🇦🇺': 'Australia', '🇨🇦': 'Canada', '🇧🇷': 'Brazil', '🇮🇳': 'India', '🇦🇪': 'UAE', '🇸🇬': 'Singapore', '🇰🇷': 'South Korea', '🇨🇳': 'China', '🇮🇩': 'Indonesia', '🇹🇭': 'Thailand', '🇲🇽': 'Mexico', '🇿🇲': 'Zambia', '🇿🇼': 'Zimbabwe', '🇲🇿': 'Mozambique', '🇧🇼': 'Botswana', '🇳🇦': 'Namibia'}.items():
                    if flag in bio_text:
                        signals.append(GeoSignal(location=country, confidence=0.65, source='profile_bio_flag', details=f"Flag {flag}", raw_matches=[flag]))
                        print(f"   ✅ Flag: {flag} → {country}")
            else:
                print("   ℹ️  No bio text found")
        except Exception as e:
            print(f"   ❌ Profile analysis failed: {e}")
        if not signals: print("   ℹ️  No location signals from profile")
        return signals

    def analyze_post_timing(self, post_date: str) -> List[GeoSignal]:
        print("\n🕐 GEO METHOD 4: POST TIMING ANALYSIS")
        signals = []
        if not post_date: print("   ⚠️  No post date"); return signals
        try:
            clean = re.sub(r'\.\d+', '', post_date.replace('Z', '+00:00'))
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            utc_hour = dt.hour
            print(f"   UTC: {dt.strftime('%Y-%m-%d %H:%M:%S')} (hour: {utc_hour})")
            for offset in range(-12, 15):
                local_hour = (utc_hour + offset) % 24
                if 9 <= local_hour <= 21: conf, src = 0.2, 'post_timing_peak'
                elif 7 <= local_hour <= 23: conf, src = 0.1, 'post_timing_active'
                else: continue
                if offset in TIMEZONE_REGIONS:
                    for region in TIMEZONE_REGIONS[offset]:
                        signals.append(GeoSignal(location=region, confidence=conf, source=src, details=f"UTC{'+' if offset >= 0 else ''}{offset} → {local_hour}:00 local", raw_matches=[f"UTC{'+' if offset >= 0 else ''}{offset}"]))
            if signals: print(f"   ✅ {len([s for s in signals if s.source == 'post_timing_peak'])} peak regions, {len(signals)} total\n   ⚠️  Timing is the WEAKEST signal")
        except Exception as e:
            print(f"   ❌ Failed: {e}")
        return signals

    def analyze_image_metadata(self, image_url: str) -> List[GeoSignal]:
        print("\n📷 GEO METHOD 5: IMAGE METADATA (EXIF)")
        print("   ⚠️  Instagram strips EXIF — will likely return nothing")
        signals = []
        if not image_url: return signals
        try:
            r = http_requests.get(image_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if r.status_code != 200: return signals
            gps = self._extract_exif_gps(r.content)
            if gps:
                lat, lon = gps
                nearest = self._reverse_geocode_local(lat, lon)
                loc = nearest if nearest else f"{lat:.4f}, {lon:.4f}"
                signals.append(GeoSignal(location=loc, confidence=0.95, source='image_exif_gps', details="GPS from EXIF", latitude=lat, longitude=lon, raw_matches=[f"{lat},{lon}"]))
                print(f"   ✅ GPS: {loc}")
            else: print("   ℹ️  No GPS in EXIF (expected)")
        except Exception as e:
            print(f"   ❌ Failed: {e}")
        return signals

    def _extract_exif_gps(self, data: bytes) -> Optional[Tuple[float, float]]:
        try:
            if data[:2] != b'\xff\xd8': return None
            offset = 2
            while offset < len(data) - 1:
                if data[offset] != 0xFF: break
                if data[offset + 1] == 0xE1:
                    length = struct.unpack('>H', data[offset + 2:offset + 4])[0]
                    seg = data[offset + 4:offset + 2 + length]
                    if seg[:6] == b'Exif\x00\x00': return self._parse_exif_gps(seg[6:])
                    break
                else:
                    length = struct.unpack('>H', data[offset + 2:offset + 4])[0]; offset += 2 + length
        except: pass
        return None

    def _parse_exif_gps(self, exif: bytes) -> Optional[Tuple[float, float]]:
        try:
            endian = '>' if exif[:2] == b'MM' else '<' if exif[:2] == b'II' else None
            if not endian: return None
            if struct.unpack(f'{endian}H', exif[2:4])[0] != 42: return None
            ifd_off = struct.unpack(f'{endian}I', exif[4:8])[0]
            n = struct.unpack(f'{endian}H', exif[ifd_off:ifd_off + 2])[0]
            gps_off = None
            for i in range(n):
                e = ifd_off + 2 + i * 12
                if struct.unpack(f'{endian}H', exif[e:e + 2])[0] == 0x8825:
                    gps_off = struct.unpack(f'{endian}I', exif[e + 8:e + 12])[0]; break
            if not gps_off: return None
            ng = struct.unpack(f'{endian}H', exif[gps_off:gps_off + 2])[0]
            tags = {}
            for i in range(ng):
                e = gps_off + 2 + i * 12
                tag = struct.unpack(f'{endian}H', exif[e:e + 2])[0]
                vo = struct.unpack(f'{endian}I', exif[e + 8:e + 12])[0]
                if tag in [1, 3]: tags[tag] = chr(exif[e + 8])
                elif tag in [2, 4]:
                    rats = []
                    for j in range(3):
                        ro = vo + j * 8
                        num = struct.unpack(f'{endian}I', exif[ro:ro + 4])[0]
                        den = struct.unpack(f'{endian}I', exif[ro + 4:ro + 8])[0]
                        rats.append(num / den if den else 0)
                    tags[tag] = rats
            if all(k in tags for k in [1, 2, 3, 4]):
                lat = tags[2][0] + tags[2][1] / 60 + tags[2][2] / 3600
                lon = tags[4][0] + tags[4][1] / 60 + tags[4][2] / 3600
                if tags[1] == 'S': lat = -lat
                if tags[3] == 'W': lon = -lon
                return (lat, lon)
        except: pass
        return None

    def _reverse_geocode_local(self, lat: float, lon: float) -> Optional[str]:
        min_d, nearest = float('inf'), None
        for ck, cd in CITIES.items():
            if 'lat' not in cd: continue
            dlat, dlon = math.radians(cd['lat'] - lat), math.radians(cd['lon'] - lon)
            a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(cd['lat'])) * math.sin(dlon / 2) ** 2
            d = 2 * math.asin(math.sqrt(a)) * 6371
            if d < min_d: min_d, nearest = d, f"{cd['city']}, {cd['country']}"
        return f"{nearest} (≈{min_d:.0f}km)" if min_d < 200 else None

    def analyze_visual_content(self, image_url: str) -> List[GeoSignal]:
        print("\n🖼️  GEO METHOD 6: VISUAL CONTENT RECOGNITION")
        signals = []
        if not self.claude_api_key:
            self.claude_api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not self.claude_api_key: print("   ⚠️  No Claude API key — skipping"); return signals
        try:
            import base64
            r = http_requests.get(image_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r.status_code != 200: return signals
            ct = r.headers.get('Content-Type', 'image/jpeg')
            mt = 'image/png' if 'png' in ct else 'image/webp' if 'webp' in ct else 'image/jpeg'
            b64 = base64.b64encode(r.content).decode('utf-8')
            print(f"   ⏳ Analyzing with Claude Vision...")
            resp = http_requests.post('https://api.anthropic.com/v1/messages', headers={'Content-Type': 'application/json', 'x-api-key': self.claude_api_key, 'anthropic-version': '2023-06-01'}, json={'model': 'claude-sonnet-4-20250514', 'max_tokens': 500, 'messages': [{'role': 'user', 'content': [{'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': b64}}, {'type': 'text', 'text': 'Analyze this image for geographic location clues: landmarks, signs, license plates, currency, architecture, vegetation, brands, flags.\n\nRespond ONLY in JSON:\n{"location_clues": [{"clue": "...", "inferred_location": "City, Country", "confidence": 0.0-1.0}], "best_guess": "City, Country", "best_confidence": 0.0-1.0}'}]}]}, timeout=30)
            if resp.status_code != 200: return signals
            text = ''.join(b['text'] for b in resp.json().get('content', []) if b.get('type') == 'text')
            text = re.sub(r'^```json\s*', '', text.strip()); text = re.sub(r'\s*```$', '', text)
            vr = json.loads(text)
            for clue in vr.get('location_clues', []):
                signals.append(GeoSignal(location=clue.get('inferred_location', 'Unknown'), confidence=float(clue.get('confidence', 0.3)), source='visual_content_recognition', details=f"Visual: {clue.get('clue', '')}", raw_matches=[clue.get('clue', '')]))
                print(f"   ✅ {clue.get('clue', '')[:50]}... → {clue.get('inferred_location')}")
            best = vr.get('best_guess'); bc = float(vr.get('best_confidence', 0))
            if best and bc > 0:
                signals.append(GeoSignal(location=best, confidence=bc, source='visual_content_best_guess', details="Claude Vision best guess", raw_matches=[f"best: {best}"]))
                print(f"   🎯 Best: {best} ({bc})")
        except json.JSONDecodeError as e: print(f"   ❌ Parse error: {e}")
        except Exception as e: print(f"   ❌ Failed: {e}")
        return signals

    @staticmethod
    def analyze_ip_network() -> List[GeoSignal]:
        print("\n🌐 GEO METHOD 7: IP/NETWORK ANALYSIS")
        print("   ❌ NOT POSSIBLE — poster's IP is server-side only")
        return []

    def analyze_username(self, username: str, author_name: str = "") -> List[GeoSignal]:
        print(f"\n🔤 GEO METHOD 8: USERNAME ANALYSIS")
        print(f"   Username: @{username}")
        if author_name: print(f"   Display name: {author_name}")
        signals = []
        if not username: print("   ⚠️  No username to analyze"); return signals
        username_lower = username.lower().strip()
        username_flat = username_lower.replace('_', '').replace('.', '').replace('-', '')
        author_lower = author_name.lower().strip() if author_name else ""
        author_flat = author_lower.replace(' ', '').replace('_', '').replace('.', '').replace('-', '').replace('|', '')
        found_locations = {}
        for keyword, data in USERNAME_LOCATION_KEYWORDS.items():
            matched_in = None; match_context = None
            if keyword.startswith('_'):
                if username_lower.endswith(keyword): matched_in = 'username_suffix'; match_context = f"@{username} ends with '{keyword}'"
            elif keyword in username_flat:
                matched_in = 'username_substring'; match_context = f"@{username} contains '{keyword}'"
            if not matched_in and author_flat and keyword in author_flat:
                matched_in = 'display_name'; match_context = f"Display name '{author_name}' contains '{keyword}'"
            if matched_in:
                loc = data['location']; conf = data['confidence']
                keyword_ratio = len(keyword) / max(len(username_flat), 1)
                if keyword_ratio > 0.5: conf = min(conf + 0.10, 0.90)
                elif keyword_ratio > 0.3: conf = min(conf + 0.05, 0.85)
                if matched_in == 'username_suffix': conf = max(conf - 0.05, 0.20)
                if matched_in == 'display_name': conf = max(conf - 0.05, 0.20)
                if loc not in found_locations or conf > found_locations[loc][0]:
                    found_locations[loc] = (conf, match_context, keyword, data['type'])
        for city_key, city_data in CITIES.items():
            city_flat = city_key.replace(' ', '')
            if len(city_flat) >= 4 and city_flat in username_flat:
                loc = f"{city_data['city']}, {city_data['country']}"; conf = 0.65
                ratio = len(city_flat) / max(len(username_flat), 1)
                if ratio > 0.4: conf = 0.75
                context = f"@{username} contains city '{city_key}'"
                if loc not in found_locations or conf > found_locations[loc][0]:
                    found_locations[loc] = (conf, context, city_key, 'city')
        for country_key, country_data in COUNTRIES.items():
            country_flat = country_key.replace(' ', '')
            if len(country_flat) >= 4 and country_flat in username_flat:
                loc = country_data['country']; conf = 0.55
                ratio = len(country_flat) / max(len(username_flat), 1)
                if ratio > 0.3: conf = 0.65
                context = f"@{username} contains country '{country_key}'"
                if loc not in found_locations or conf > found_locations[loc][0]:
                    found_locations[loc] = (conf, context, country_key, 'country')
        if author_lower:
            for city_key, city_data in CITIES.items():
                if re.search(r'\b' + re.escape(city_key) + r'\b', author_lower):
                    loc = f"{city_data['city']}, {city_data['country']}"; conf = 0.60; context = f"Display name '{author_name}' contains city '{city_key}'"
                    if loc not in found_locations or conf > found_locations[loc][0]: found_locations[loc] = (conf, context, city_key, 'city')
            for country_key, country_data in COUNTRIES.items():
                if len(country_key) >= 4 and re.search(r'\b' + re.escape(country_key) + r'\b', author_lower):
                    loc = country_data['country']; conf = 0.50; context = f"Display name '{author_name}' contains country '{country_key}'"
                    if loc not in found_locations or conf > found_locations[loc][0]: found_locations[loc] = (conf, context, country_key, 'country')
        for loc, (conf, context, keyword, ktype) in found_locations.items():
            signal = GeoSignal(location=loc, confidence=round(conf, 2), source=f'username_{ktype}', details=context, raw_matches=[keyword])
            signals.append(signal)
            print(f"   ✅ [{ktype}] '{keyword}' → {loc} (conf: {conf:.2f})")
        if not signals: print("   ℹ️  No location signals in username/display name")
        else: print(f"   📊 Total: {len(signals)} signal(s) from username analysis")
        return signals

    def enrich(self, caption: str = "", hashtags: List[str] = None, post_date: str = "", username: str = "", author_name: str = "", post_image_url: str = "", run_visual_analysis: bool = False) -> GeoResult:
        if hashtags is None: hashtags = []
        print("\n" + "=" * 60)
        print("🌍 GEOLOCATION ENRICHMENT — RUNNING ALL 8 METHODS")
        print("=" * 60)
        all_signals = []
        for method, args in [
            (self.analyze_caption_text, (caption,)),
            (self.analyze_hashtags, (hashtags,)),
            (self.analyze_profile_metadata, (username,) if username else None),
            (self.analyze_post_timing, (post_date,) if post_date else None),
            (self.analyze_image_metadata, (post_image_url,) if post_image_url else None),
        ]:
            if args is None: continue
            try: all_signals.extend(method(*args))
            except Exception as e: print(f"   ❌ {method.__name__} error: {e}")
        if run_visual_analysis and post_image_url:
            try: all_signals.extend(self.analyze_visual_content(post_image_url))
            except Exception as e: print(f"   ❌ Visual analysis error: {e}")
        self.analyze_ip_network()
        if username:
            try: all_signals.extend(self.analyze_username(username, author_name))
            except Exception as e: print(f"   ❌ Username analysis error: {e}")
        print("\n" + "=" * 60)
        print("📊 AGGREGATING SIGNALS")
        print("=" * 60)
        result = GeoResult(signals=all_signals)
        if not all_signals: print("   ℹ️  No geolocation signals found"); return result
        source_weights = {
            'image_exif_gps': 3.0, 'profile_business_address': 2.5,
            'visual_content_best_guess': 2.0, 'visual_content_recognition': 1.5,
            'profile_bio_city': 1.8, 'caption_text_city': 1.5,
            'caption_text_preposition': 1.4, 'profile_bio_pattern': 1.3,
            'hashtag_analysis': 1.2, 'username_city': 1.1,
            'username_slang': 1.0, 'username_country': 0.95,
            'username_region': 0.9, 'username_code': 0.8, 'username_substring': 0.9,
            'profile_bio_flag': 1.0, 'profile_bio_country': 0.9,
            'caption_text_country': 0.8, 'profile_link_tld': 0.6,
            'caption_text_language': 0.5, 'post_timing_peak': 0.3, 'post_timing_active': 0.15,
        }
        location_scores = {}
        for signal in all_signals:
            loc_key = signal.location.lower().strip()
            weight = source_weights.get(signal.source, 1.0)
            ws = signal.confidence * weight
            if loc_key not in location_scores:
                location_scores[loc_key] = {'display_name': signal.location, 'total_score': 0, 'signal_count': 0, 'max_confidence': 0, 'sources': [], 'lat': signal.latitude, 'lon': signal.longitude}
            e = location_scores[loc_key]
            e['total_score'] += ws; e['signal_count'] += 1; e['max_confidence'] = max(e['max_confidence'], signal.confidence); e['sources'].append(signal.source)
            if signal.latitude and not e['lat']: e['lat'] = signal.latitude; e['lon'] = signal.longitude
        for loc_key, data in location_scores.items():
            families = set(s.split('_')[0] for s in data['sources'])
            if len(families) >= 3: data['total_score'] *= 1.5; print(f"   🎯 Corroboration bonus: '{data['display_name']}' ({len(families)} methods)")
            elif len(families) >= 2: data['total_score'] *= 1.2
        ranked = sorted(location_scores.items(), key=lambda x: x[1]['total_score'], reverse=True)
        for loc_key, data in ranked:
            result.all_candidates.append({'location': data['display_name'], 'score': round(data['total_score'], 3), 'signal_count': data['signal_count'], 'max_confidence': round(data['max_confidence'], 2), 'sources': list(set(data['sources'])), 'latitude': data['lat'], 'longitude': data['lon']})
        if ranked:
            bk, bd = ranked[0]; result.best_location = bd['display_name']; top = bd['total_score']
            second = ranked[1][1]['total_score'] if len(ranked) > 1 else 0
            base_conf = min(bd['max_confidence'], 0.95); margin = (top - second) / top if top > 0 else 0
            result.best_confidence = min(base_conf + (margin * 0.1), 0.99)
            result.method_used = ', '.join(set(bd['sources']))
        print(f"\n{'='*60}")
        print(f"🌍 GEOLOCATION RESULT:")
        print(f"   Best: {result.best_location} (conf: {result.best_confidence:.2f})")
        print(f"   Methods: {result.method_used}")
        print(f"   Signals: {len(all_signals)} | Candidates: {len(result.all_candidates)}")
        if len(result.all_candidates) > 1:
            for i, c in enumerate(result.all_candidates[:3], 1):
                print(f"   {i}. {c['location']} (score: {c['score']}, signals: {c['signal_count']})")
        print(f"{'='*60}\n")
        return result


# ================================================================
# SECTION 4: INSTAGRAM SCRAPER (ENHANCED + GEO)
# ================================================================

class InstagramScraperEnhanced:
    """
    Enhanced Instagram scraper — Playwright persistent context, no cookie injection.

    Session is stored in Profile 5's own cookie store.
    First-time setup: open Chrome → switch to Profile 5 → log into Instagram manually → close Chrome.
    All subsequent runs reuse that session automatically.
    """

    def __init__(self, cookies: Dict = None, headless: bool = False, claude_api_key: Optional[str] = None):
        self.cookies = cookies          # unused — kept for API compatibility
        self.headless = headless
        self.claude_api_key = claude_api_key
        self.driver = None              # will be a PlaywrightDriverShim after _setup_driver
        self._context = None            # raw Playwright BrowserContext
        self._playwright = None         # raw Playwright instance

    # ----------------------------------------------------------------
    # BROWSER SETUP
    # ----------------------------------------------------------------

    def _setup_driver(self):
        print("🔐 Initializing browser (Playwright + Chrome for Testing)...")

        self._playwright = sync_playwright().start()

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=CHROME_FOR_TESTING_PROFILE,
            executable_path=CHROME_FOR_TESTING_EXE,
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=ChromeWhatsNewUI",
            ],
            ignore_https_errors=True,
            viewport={"width": 1920, "height": 1080},
        )

        # Wrap in shim so all existing extraction methods work unchanged
        page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )
        self.driver = PlaywrightDriverShim(page)

        print("⏳ Loading Instagram...")
        self.driver.get("https://www.instagram.com/")
        time.sleep(6)

        if "/accounts/login" in self.driver.current_url:
            self.close()
            raise Exception(
                "❌ Session expired or not found in CfTInstagramProfile.\n"
                "   Run this command first to log in manually:\n"
                f"   \"{CHROME_FOR_TESTING_EXE}\" "
                f"--user-data-dir=\"{CHROME_FOR_TESTING_PROFILE}\" "
                "--no-first-run\n"
                "   Log into Instagram, then close the browser and re-run the scraper."
            )

        print("✅ Authenticated via CfT persistent context\n")
        self._close_popups()
    
    # ----------------------------------------------------------------
    # ✅ FIX 2: _close_popups is now a proper class method (was nested
    #    inside _setup_driver before, making self._close_popups() fail)
    # ----------------------------------------------------------------

    def _close_popups(self):
        """Dismiss Instagram's 'Turn on Notifications' and cookie popups."""
        for label in ["Close", "Not Now", "Decline optional cookies"]:
            try:
                self.driver.find_element(
                    By.XPATH,
                    f'//*[@aria-label="{label}" or normalize-space(text())="{label}"]'
                ).click()
                time.sleep(1)
            except Exception:
                pass

    # ----------------------------------------------------------------
    # ✅ FIX 3: close() now shuts down the Playwright context properly
    #    (the old code called self.driver.close() on the shim, which did nothing)
    # ----------------------------------------------------------------

    def close(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        print("🔒 Browser closed")

    # ========================================================
    # EXTRACTION METHODS (unchanged — shim translates calls)
    # ========================================================

    def _extract_caption(self) -> str:
        print("\n📝 EXTRACTING CAPTION...")
        caption = ""
        try:
            for elem in self.driver.find_elements(By.CSS_SELECTOR, 'span.x193iq5w'):
                text = elem.text.strip()
                if 'comments on this post have been limited' in text.lower(): continue
                if re.search(r'\d+\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}', text): continue
                if 50 < len(text) < 5000:
                    caption = text
                    print(f"   ✅ Caption: {text[:80]}...")
                    break
        except Exception as e:
            print(f"   Failed: {e}")
        if not caption:
            try:
                for line in self.driver.find_element(By.TAG_NAME, 'body').text.split('\n'):
                    if len(line) > 100 and '#' in line:
                        caption = line
                        break
            except: pass
        print(f"   {'✅' if caption else '❌'} {len(caption)} chars")
        return caption

    def _extract_hashtags(self, caption: str) -> List[str]:
        print("\n🏷️  EXTRACTING HASHTAGS...")
        hashtags = re.findall(r'#\w+', caption)
        try:
            for link in self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/explore/tags/"]'):
                m = re.search(r'/explore/tags/([^/]+)/', link.get_attribute('href'))
                if m:
                    tag = f"#{m.group(1)}"
                    if tag not in hashtags: hashtags.append(tag)
        except: pass
        print(f"   ✅ {len(hashtags)} hashtags")
        return hashtags

    def _extract_likes(self) -> int:
        print("\n❤️  EXTRACTING LIKES...")
        try:
            for elem in self.driver.find_elements(By.CSS_SELECTOR, 'span.x1ypdohk.x1s688f[role="button"]'):
                text = elem.text.strip()
                if text.isdigit() and int(text) < 10000:
                    print(f"   ✅ {text}"); return int(text)
        except: pass
        try:
            for btn in self.driver.find_elements(By.TAG_NAME, 'button'):
                al = btn.get_attribute('aria-label')
                if al:
                    m = re.search(r'(\d+)\s+likes?', al, re.IGNORECASE)
                    if m: print(f"   ✅ {m.group(1)}"); return int(m.group(1))
        except: pass
        print("   ⚠️  0"); return 0

    def _extract_comments_count(self) -> int:
        print("\n💬 EXTRACTING COMMENT COUNT...")
        try:
            if self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Comments on this post have been limited')]"):
                print("   ✅ Limited → 0"); return 0
        except: pass
        try:
            if self.driver.find_elements(By.XPATH, "//*[contains(text(), 'No comments yet')]"):
                print("   ✅ No comments yet → 0"); return 0
        except: pass
        try:
            for elem in self.driver.find_elements(By.XPATH, "//*[contains(text(), 'comment')]"):
                text = elem.text.strip()
                if any(m in text for m in ['January','February','March','April','May','June','July','August','September','October','November','December']): continue
                m = re.search(r'view\s+all\s+(\d+)\s+comments?', text, re.IGNORECASE)
                if m: print(f"   ✅ {m.group(1)}"); return int(m.group(1))
        except: pass
        print("   ℹ️  0"); return 0

    def _extract_username(self) -> str:
        print("⏳ Extracting username...")

        # ── Method 1: og:title meta tag ─────────────────────────────
        # Instagram sets this to "Username (@handle) on Instagram: ..."
        # or "Display Name on Instagram: ..."
        # This is the most reliable signal on post pages.
        try:
            meta = self.driver.find_element(
                By.CSS_SELECTOR, 'meta[property="og:title"]'
            )
            content = meta.get_attribute('content') or ''
            # Pattern: "Display Name (@username) on Instagram"
            m = re.match(r'^.+?\(@([A-Za-z0-9._]+)\)', content)
            if m:
                username = m.group(1).strip()
                print(f"   ✅ {username} (og:title @handle)")
                return username
            # Pattern: "@username on Instagram"
            m = re.search(r'@([A-Za-z0-9._]+)', content)
            if m:
                username = m.group(1).strip()
                print(f"   ✅ {username} (og:title @mention)")
                return username
        except Exception:
            pass

        # ── Method 2: Article header links ──────────────────────────
        # The post author's username appears as a link in the post header.
        # We search several selectors for robustness against layout changes.
        _blocked = {
            'explore', 'reels', 'direct', 'accounts', 'stories',
            'legal', 'p', 'reel', 'tv', 'about', 'help', 'privacy',
            'terms', 'locations', 'tags', 'web', 'login', 'signup',
        }
        try:
            for selector in [
                'article header a[href]',
                'div[role="dialog"] header a[href]',
                'main article header a[href]',
                'section header a[href]',
            ]:
                for elem in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    href = elem.get_attribute('href') or ''
                    m = re.search(
                        r'instagram\.com/([A-Za-z0-9._]+)/?$', href
                    )
                    if m:
                        candidate = m.group(1).lower()
                        if candidate not in _blocked:
                            print(f"   ✅ {m.group(1)} (article header)")
                            return m.group(1)
        except Exception:
            pass

        # ── Method 3: Scan all links (absolute OR relative hrefs) ───
        # Instagram may use either absolute or relative URLs depending
        # on the page context. We match both patterns here.
        try:
            usernames = []
            for link in self.driver.find_elements(By.CSS_SELECTOR, 'a[href]'):
                href = link.get_attribute('href') or ''
                # Match absolute Instagram profile URL
                m = re.match(
                    r'^https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?$',
                    href
                )
                if not m:
                    # Match relative profile URL  /username/
                    m = re.match(r'^/([A-Za-z0-9._]+)/?$', href)
                if m:
                    candidate = m.group(1).lower()
                    if candidate not in _blocked:
                        usernames.append(m.group(1))

            unique = list(dict.fromkeys(usernames))
            # Index 1 (not 0) to skip the logged-in user's own profile
            # which often appears first in the page
            if len(unique) >= 2:
                print(f"   ✅ {unique[1]} (link scan)")
                return unique[1]
            elif unique:
                print(f"   ✅ {unique[0]} (link scan)")
                return unique[0]
        except Exception:
            pass

        # ── Method 4: og:url or canonical URL ───────────────────────
        # For profile pages, og:url points to the post URL but the
        # referrer or nearby og:description may contain the username.
        try:
            meta_desc = self.driver.find_element(
                By.CSS_SELECTOR, 'meta[property="og:description"]'
            )
            content = meta_desc.get_attribute('content') or ''
            m = re.search(r'@([A-Za-z0-9._]+)', content)
            if m:
                print(f"   ✅ {m.group(1)} (og:description)")
                return m.group(1)
        except Exception:
            pass

        print("   ❌ Username not found — all 4 methods exhausted")
        return None

    def _extract_profile_data(self) -> Dict:
        print("\n⏳ Extracting profile data...")
        data = {'followers': 0, 'following': 0, 'posts': 0}
        try:
            meta = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:description"]')
            content = meta.get_attribute('content')
            for pat, key in [(r'([\d.,]+[KkMm]?)\s*Followers','followers'),(r'([\d.,]+[KkMm]?)\s*Following','following'),(r'([\d.,]+[KkMm]?)\s*Posts','posts')]:
                m = re.search(pat, content, re.IGNORECASE)
                if m: data[key] = self._parse_count(m.group(1))
            print(f"   ✅ {data['followers']:,} / {data['following']:,} / {data['posts']:,}")
        except Exception as e:
            print(f"   ⚠️  Failed: {e}")
        return data

    def _parse_count(self, text: str) -> int:
        if not text: return 0
        m = re.search(r'([\d.]+)([KkMm]?)', text.replace(',',''))
        if not m: return 0
        n = float(m.group(1)); s = m.group(2).lower()
        if s == 'k': n *= 1000
        elif s == 'm': n *= 1000000
        return int(n)

    def _extract_author_name(self) -> str:
        print("\n👤 EXTRACTING AUTHOR NAME...")
        try:
            elems = self.driver.find_elements(By.CSS_SELECTOR, 'span._ap3a._aaco._aacw._aacx._aad7')
            if elems and elems[0].text.strip(): print(f"   ✅ {elems[0].text.strip()}"); return elems[0].text.strip()
        except: pass
        try:
            meta = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:title"]')
            m = re.search(r'^(.+?)\s*\(@', meta.get_attribute('content'))
            if m: print(f"   ✅ {m.group(1).strip()}"); return m.group(1).strip()
        except: pass
        try:
            header = self.driver.find_elements(By.TAG_NAME, 'header')
            if header:
                for span in header[0].find_elements(By.TAG_NAME, 'span'):
                    t = span.text.strip()
                    if t and 2 <= len(t) <= 50 and not t.startswith('@') and not t.isdigit() and t.lower() not in ['posts','followers','following','follow','message']:
                        print(f"   ✅ {t}"); return t
        except: pass
        print("   ⚠️  Not found"); return ""

    def _extract_post_date(self) -> Optional[str]:
        print("\n📅 EXTRACTING POST DATE...")
        try:
            for elem in self.driver.find_elements(By.CSS_SELECTOR, 'time.x1p4m5qa'):
                dt = elem.get_attribute('datetime')
                if dt: print(f"   ✅ {dt}"); return dt
        except: pass
        try:
            for elem in self.driver.find_elements(By.TAG_NAME, 'time'):
                dt = elem.get_attribute('datetime')
                if dt: print(f"   ✅ {dt}"); return dt
        except: pass
        try:
            body = self.driver.find_element(By.TAG_NAME, 'body').text
            for pat, unit in [(r'\b(\d+)\s*w\b','weeks'),(r'\b(\d+)\s*d\b','days'),(r'\b(\d+)\s*h\b','hours'),(r'\b(\d+)\s*m\b','minutes')]:
                m = re.search(pat, body)
                if m:
                    v = int(m.group(1)); now = datetime.now()
                    td = {'weeks': timedelta(weeks=v), 'days': timedelta(days=v), 'hours': timedelta(hours=v), 'minutes': timedelta(minutes=v)}
                    d = (now - td[unit]).isoformat(); print(f"   ✅ ~{v} {unit} ago → {d}"); return d
        except: pass
        print("   ⚠️  Not found"); return None

    def _extract_shares(self) -> int:
        print("\n📤 EXTRACTING SHARES...")
        try:
            for btn in self.driver.find_elements(By.TAG_NAME, 'button'):
                al = btn.get_attribute('aria-label')
                if al:
                    m = re.search(r'(\d+)\s+(shares?|sends?)', al, re.IGNORECASE)
                    if m: print(f"   ✅ {m.group(1)}"); return int(m.group(1))
        except: pass
        print("   ℹ️  0"); return 0

    def _extract_views(self) -> Optional[int]:
        print("\n👁️  EXTRACTING VIEWS...")
        try:
            for elem in self.driver.find_elements(By.XPATH, "//*[contains(text(), 'views') or contains(text(), 'Views')]"):
                m = re.search(r'([\d.,]+[KkMm]?)\s+views', elem.text.strip(), re.IGNORECASE)
                if m: v = self._parse_count(m.group(1)); print(f"   ✅ {v:,}"); return v
        except: pass
        print("   ℹ️  None (photo post?)"); return None

    def _extract_location(self) -> Optional[str]:
        print("\n📍 EXTRACTING LOCATION...")
        try:
            for link in self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/explore/locations/"]'):
                t = link.text.strip()
                if t and t.lower() != 'locations': print(f"   ✅ {t}"); return t
        except: pass
        try:
            header = self.driver.find_elements(By.TAG_NAME, 'header')
            if header:
                for link in header[0].find_elements(By.TAG_NAME, 'a'):
                    href = link.get_attribute('href')
                    if href and '/explore/locations/' in href:
                        t = link.text.strip()
                        if t and t.lower() != 'locations': print(f"   ✅ {t}"); return t
        except: pass
        print("   ℹ️  No native location tag"); return None

    def _extract_post_type(self) -> str:
        print("\n🎬 EXTRACTING POST TYPE...")
        try:
            for elem in self.driver.find_elements(By.XPATH, "//*[contains(text(), '/')]"):
                if re.match(r'^\d+/\d+$', elem.text.strip()): print("   ✅ carousel"); return "carousel"
        except: pass
        try:
            if self.driver.find_elements(By.TAG_NAME, 'video'): print("   ✅ video"); return "video"
        except: pass
        print("   ✅ photo"); return "photo"

    def _extract_post_image_url(self) -> Optional[str]:
        print("\n🖼️  EXTRACTING POST IMAGE URL...")
        try:
            url = self.driver.find_element(By.CSS_SELECTOR, 'meta[property="og:image"]').get_attribute('content')
            if url: print("   ✅ og:image"); return url
        except: pass
        print("   ⚠️  Not found"); return None

    def _scroll_comment_panel(self, pixels: int = 700) -> bool:
        """
        Scroll the confirmed comment panel.
        Selector confirmed via DevTools [scroll] badge:
            div.x5yr21d.xw2csxc.x1odjw0f.x1n2onr6
        """
        page = self.driver._page
        return page.evaluate(f"""() => {{

            const SELECTORS = [
                'div.x5yr21d.xw2csxc.x1odjw0f.x1n2onr6',  // CfT — confirmed
                'ul._a9z6._a9za',                            // personal account
                'ul._a9z6',
            ];

            for (const sel of SELECTORS) {{
                const panel = document.querySelector(sel);
                if (!panel) continue;
                const before = panel.scrollTop;
                panel.scrollTop += {pixels};
                const moved = panel.scrollTop > before;
                console.log('[BrandPulse] scroll |', sel,
                            '|', before, '->', panel.scrollTop,
                            '| moved:', moved);
                return moved;
            }}

            // Fallback: scored search
            let best = null, bestScore = 0;
            for (const el of document.querySelectorAll('div, ul, section')) {{
                const s = window.getComputedStyle(el);
                const ok = (s.overflowY === 'auto' || s.overflowY === 'scroll')
                        && el.scrollHeight > el.clientHeight + 80
                        && el.clientHeight < window.innerHeight - 50
                        && el.clientHeight > 200;
                if (ok) {{
                    const score = el.tagName === 'UL'
                                ? el.clientHeight * 2 : el.clientHeight;
                    if (score > bestScore) {{ best = el; bestScore = score; }}
                }}
            }}

            if (best) {{
                const before = best.scrollTop;
                best.scrollTop += {pixels};
                console.log('[BrandPulse] fallback scroll |',
                            best.tagName, best.className.slice(0,40),
                            '|', before, '->', best.scrollTop);
                return best.scrollTop > before;
            }}

            console.warn('[BrandPulse] no scrollable panel found');
            return false;
        }}""")


    def _extract_comments_js(self, limit: int) -> List[Dict]:
        """
        Depth-3 anchored extraction.

        CONFIRMED from DevTools diagnostic:
        - Panel: div.x5yr21d.xw2csxc.x1odjw0f.x1n2onr6
        - Depth 1: 1 node (outer wrapper)
        - Depth 2: 2 nodes (inner wrapper)
        - Depth 3: 18 nodes ← COMMENT ROWS live here
        - Profile links inside panel: 33
        - Leaf spans inside panel: 36 (alternating username/text)

        Strategy:
        1. Query depth-3 descendants: panel > * > * > *
        2. Each node is one comment block
        3. Author  = first <a href> resolving to an IG username
        4. Text    = longest leaf-node span/div passing noise filters
        """
        return self.driver._page.evaluate(f"""() => {{
            const LIMIT = {limit};

            const PATH_SKIP = new Set([
                'explore','reels','p','reel','tv','stories','direct',
                'accounts','legal','about','help','press','api','jobs',
                'privacy','terms','web','tags','locations','login','signup',
            ]);

            const TEXT_SKIP = new Set([
                'like','reply','follow','following','unfollow','verified',
                'see translation','translate','translate comment','original',
                'hide','delete','report','more','options',
                'view replies','hide replies','view all replies',
                'load more','view more','load more comments',
                'add a comment\u2026','add a comment...','post',
            ]);

            // ── 1. Locate panel ───────────────────────────────────────
            const PANEL_SELS = [
                'div.x5yr21d.xw2csxc.x1odjw0f.x1n2onr6',
                'ul._a9z6._a9za',
                'ul._a9z6',
            ];
            let panel = null;
            for (const sel of PANEL_SELS) {{
                panel = document.querySelector(sel);
                if (panel) {{
                    console.log('[BrandPulse] panel via:', sel);
                    break;
                }}
            }}

            if (!panel) {{
                // Fallback: tallest scrollable container
                let bestH = 0;
                for (const el of document.querySelectorAll('div, ul')) {{
                    const s = window.getComputedStyle(el);
                    if ((s.overflowY==='auto'||s.overflowY==='scroll')
                            && el.scrollHeight > el.clientHeight + 80
                            && el.clientHeight > 200
                            && el.clientHeight > bestH) {{
                        panel = el; bestH = el.clientHeight;
                    }}
                }}
                if (panel) console.log('[BrandPulse] panel via fallback');
                else {{ console.warn('[BrandPulse] NO panel found'); return []; }}
            }}

            // ── 2. Get depth-3 rows (confirmed comment containers) ────
            //
            // panel > * > * > *  gives us exactly the 18 nodes we saw
            // at depth 3 in the diagnostic.
            //
            // We also include depth-2 (2 nodes) as a fallback in case
            // Instagram restructures to one fewer wrapper level.
            const depth3 = [...panel.querySelectorAll(':scope > * > * > *')];
            const depth2 = [...panel.querySelectorAll(':scope > * > *')];

            // Use whichever depth has more nodes — more nodes = more comments
            const rows = depth3.length >= depth2.length ? depth3 : depth2;

            console.log('[BrandPulse] rows at depth3:', depth3.length,
                        '| depth2:', depth2.length,
                        '| using:', rows.length);

            // ── 3. Extract author + text from each row ────────────────
            const results  = [];
            const seenKeys = new Set();

            for (const row of rows) {{
                if (results.length >= LIMIT) break;

                // ── Author: first profile link in this row ─────────────
                let author = 'unknown';
                for (const a of row.querySelectorAll('a[href]')) {{
                    const m = a.href.match(
                        /(?:(?:https?:\\/\\/)?(?:www\\.)?instagram\\.com)?\\/([A-Za-z0-9._]{{3,30}})\\/?(?:\\?.*)?$/
                    );
                    if (m && !PATH_SKIP.has(m[1].toLowerCase())) {{
                        author = m[1];
                        break;
                    }}
                }}

                // ── Text: longest leaf-node span/div ───────────────────
                //
                // "Leaf node" = element with no <span> children.
                // This prevents double-counting text from wrapper elements.
                //
                // We also skip the author's own username appearing as text
                // (username spans sit right next to the comment text).
                let text = '', maxLen = 0;
                for (const node of row.querySelectorAll('span, div')) {{
                    if (node.querySelectorAll('span').length > 0) continue;

                    const t = (node.innerText || node.textContent || '').trim();

                    if (
                        t.length < 3 || t.length <= maxLen     ||
                        TEXT_SKIP.has(t.toLowerCase())          ||
                        t.toLowerCase() === author.toLowerCase() || // skip own username
                        /^\\d+$/.test(t)                        ||  // pure number
                        /^\\d+[wdhms]$/.test(t)                 ||  // "5d", "3h"
                        /^\\d+\\s*(like|hour|day|week|min)/i.test(t) ||
                        /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/i.test(t) ||
                        /^view\\s+(all\\s+)?\\d+/i.test(t)      ||  // "View all 9 replies"
                        /^ver\\s+\\d+/i.test(t)                     // Portuguese: "Ver 9 respostas"
                    ) continue;

                    maxLen = t.length;
                    text   = t;
                }}

                if (!text || text.length < 3) continue;

                // Skip rows that only contain the author's caption
                // (caption is the first long block from the post author —
                // keep it if it's genuinely a comment from someone else)
                const key = author + '::' + text.substring(0, 80);
                if (seenKeys.has(key)) continue;
                seenKeys.add(key);

                results.push({{
                    author  : author,
                    text    : text,
                    position: results.length + 1,
                }});
            }}

            console.log('[BrandPulse] extracted:', results.length,
                        '| from', rows.length, 'rows');
            return results;
        }}""") or []



    def _click_load_more_buttons(self) -> int:
        """
        Click comment-loading buttons.

        NOTE: CfT Instagram auto-loads on scroll — no load-more button
        exists in that version. This method is kept as a safety net for:
        - Reply expanders ("View all N replies") which DO appear
        - Personal account sessions where the button exists
        - Future layout changes

        Strategy A: aria-label on SVG (confirmed in DevTools)
        Strategy B: button._abl- (confirmed class)
        Strategy C: text pattern matching (English + Portuguese)
        """
        page = self.driver._page
        clicked = 0

        # ── Strategy A: aria-label (most stable) ──────────────────────
        clicked += page.evaluate("""() => {
            let n = 0;
            const LABELS = [
                'Load more comments',
                'Carregar mais comentários',
            ];
            for (const label of LABELS) {
                const svg = document.querySelector(`svg[aria-label="${label}"]`);
                if (!svg) continue;
                let el = svg;
                for (let i = 0; i < 5; i++) {
                    el = el.parentElement;
                    if (!el) break;
                    if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') {
                        if (el.offsetParent !== null) {
                            el.click(); n++;
                            console.log('[BrandPulse] A: clicked via aria-label:', label);
                        }
                        break;
                    }
                }
            }
            return n;
        }""")

        # ── Strategy B: button._abl- (confirmed class, personal account) ─
        if clicked == 0:
            clicked += page.evaluate("""() => {
                let n = 0;
                for (const btn of document.querySelectorAll('button._abl-')) {
                    if (btn.offsetParent === null) continue;
                    btn.click(); n++;
                    console.log('[BrandPulse] B: clicked button._abl-');
                }
                return n;
            }""")

        # ── Strategy C: text pattern — reply expanders + Portuguese ───
        clicked += page.evaluate("""() => {
            const PATTERNS = [
                /view\\s+all\\s+\\d+\\s+repl/i,
                /view\\s+\\d+\\s+repl/i,
                /ver\\s+\\d+\\s+resposta/i,
                /ver\\s+todas\\s+as/i,
                /view\\s+more\\s+comment/i,
                /ver\\s+mais\\s+coment/i,
            ];
            let n = 0;
            for (const el of document.querySelectorAll(
                'button, div[role="button"], span[role="button"]'
            )) {
                if (!el.offsetParent) continue;
                const t = (el.innerText || el.textContent || '').trim();
                if (PATTERNS.some(p => p.test(t))) {
                    el.click(); n++;
                    console.log('[BrandPulse] C: text-match clicked:', t.slice(0,50));
                }
            }
            return n;
        }""")

        if clicked:
            print(f"   [buttons] clicked {clicked}")
        return clicked



    def _extract_comment_texts(self, limit: int = 100) -> List[Dict]:
        """
        Hybrid comment extractor — network interception + DOM scroll.

        CONFIRMED response schema (from Network tab Response):
        {
        "data": {
            "xdt_api__v1__media__media_id__comments__connection": {
            "edges": [
                {
                "node": {
                    "user": { "username": "...", "is_verified": bool },
                    "text": "...",
                    "created_at": 1773394306,
                    "comment_like_count": 1,
                    "child_comment_count": 0,
                    "pk": "..."
                }
                }
            ],
            "page_info": {
                "end_cursor": "{...}",
                "has_next_page": true
            }
            }
        }
        }

        WHY NETWORK INTERCEPTION:
        Instagram virtualizes the comment panel — after ~100 DOM nodes,
        old ones are recycled and scrollTop stops increasing. The network
        layer has no such ceiling. Each scroll triggers a GraphQL POST to
        /graphql/query which returns the next page of comments in raw JSON
        before React touches the DOM.

        BONUS DATA CAPTURED:
        Each comment node also contains created_at (unix timestamp),
        comment_like_count, child_comment_count, and user.is_verified.
        These are stored alongside author/text for richer NLP input.
        """
        print(f"\n💬 EXTRACTING UP TO {limit} COMMENTS (network intercept + DOM)...")

        page         = self.driver._page
        all_comments : List[Dict] = []
        seen_keys    : set        = set()
        lock                      = threading.Lock()

        # ── Network response interceptor ──────────────────────────────
        # Registered BEFORE any scrolling so we catch every response.

        def on_response(response):
            if 'graphql/query' not in response.url:
                return
            if 'json' not in response.headers.get('content-type', ''):
                return
            try:
                body = response.json()
            except Exception:
                return
            if not isinstance(body, dict):
                return
            _parse_payload(body)

        def _parse_payload(data: dict):
            """
            Parse the confirmed GraphQL response schema.

            Primary key (confirmed): xdt_api__v1__media__media_id__comments__connection
            Fallback keys: legacy GraphQL edge schemas from older endpoints.
            Generic recursion: safety net for any future schema changes.
            """
            if not isinstance(data, dict):
                return

            # ── PRIMARY: confirmed schema from Network tab ─────────────
            # Key: xdt_api__v1__media__media_id__comments__connection
            # This is the only key that matters for CfT Instagram 2025.
            PRIMARY_KEY = 'xdt_api__v1__media__media_id__comments__connection'
            if PRIMARY_KEY in data:
                block = data[PRIMARY_KEY]
                if isinstance(block, dict):
                    edges = block.get('edges', [])
                    print(f"   [intercept] {PRIMARY_KEY}: "
                        f"{len(edges)} edges | "
                        f"has_next={block.get('page_info', {}).get('has_next_page')}")
                    for edge in edges:
                        node = edge.get('node', {})
                        if isinstance(node, dict):
                            _ingest_node(node)
                    return  # found primary key, no need to recurse further

            # ── FALLBACK: legacy GraphQL edge schemas ──────────────────
            # Kept for compatibility with personal accounts and older
            # Instagram layouts that use the pre-2024 GraphQL schema.
            LEGACY_KEYS = (
                'edge_media_to_comment',
                'edge_media_to_parent_comment',
                'edge_media_preview_comment',
                'edge_threaded_comments',
            )
            for key in LEGACY_KEYS:
                if key in data and isinstance(data[key], dict):
                    for edge in data[key].get('edges', []):
                        node = edge.get('node', {})
                        if isinstance(node, dict):
                            author = (
                                _dig(node, 'owner', 'username') or
                                _dig(node, 'user', 'username') or
                                'unknown'
                            )
                            _ingest(
                                author=author,
                                text=node.get('text', ''),
                                created_at=node.get('created_at'),
                                like_count=node.get('comment_like_count', 0),
                                reply_count=node.get('child_comment_count', 0),
                                is_verified=_dig(node, 'owner', 'is_verified'),
                            )

            # ── GENERIC RECURSION: unknown nesting ─────────────────────
            # Safety net — walks the entire response tree in case Instagram
            # introduces a new wrapper key in a future deploy.
            for v in data.values():
                if isinstance(v, dict):
                    _parse_payload(v)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            _parse_payload(item)

        def _ingest_node(node: dict):
            """Extract all fields from a confirmed XDTCommentDict node."""
            _ingest(
                author    = _dig(node, 'user', 'username') or 'unknown',
                text      = node.get('text', ''),
                created_at= node.get('created_at'),         # unix timestamp
                like_count= node.get('comment_like_count', 0),
                reply_count=node.get('child_comment_count', 0),
                is_verified=_dig(node, 'user', 'is_verified'),
            )

        def _ingest(author: str, text: str, created_at=None,
                    like_count: int = 0, reply_count: int = 0,
                    is_verified=None):
            """Thread-safe deduplication and storage."""
            if not text or len(text.strip()) < 2:
                return
            text   = text.strip()
            author = (author or 'unknown').strip()
            key    = author + '::' + text[:80]
            with lock:
                if key not in seen_keys and len(all_comments) < limit:
                    seen_keys.add(key)
                    entry = {
                        'author'     : author,
                        'text'       : text,
                        'position'   : len(all_comments) + 1,
                        'like_count' : like_count,
                        'reply_count': reply_count,
                    }
                    # Add optional fields only when present
                    if created_at:
                        entry['created_at'] = created_at
                    if is_verified is not None:
                        entry['author_verified'] = is_verified
                    all_comments.append(entry)

        def _dig(obj, *keys):
            for k in keys:
                if not isinstance(obj, dict):
                    return None
                obj = obj.get(k)
            return obj

        # Register interceptor BEFORE any scrolling
        page.on('response', on_response)

        try:
            # ── DOM seed: comments already rendered ────────────────────
            dom_seed = self._extract_comments_js(300)
            for c in dom_seed:
                _ingest(c['author'], c['text'])
            print(f"   DOM seed: {len(all_comments)} comments")

            # Prime: click any visible reply expanders
            primed = self._click_load_more_buttons()
            if primed:
                print(f"   Primed: {primed} button(s) clicked")
                time.sleep(2.5)

            # ── Scroll loop ────────────────────────────────────────────
            stale_rounds = 0
            scroll_px    = 700
            MAX_STALE    = 10
            round_num    = 0
            prev_total   = len(all_comments)

            while len(all_comments) < limit and stale_rounds < MAX_STALE:
                round_num += 1

                moved = self._scroll_comment_panel(scroll_px)

                # Longer wait when panel is at bottom — Instagram needs
                # extra time to detect scroll position and fire the request
                time.sleep(3.5 if not moved else 2.0)

                # DOM sweep each round — catches DOM-only nodes
                for c in self._extract_comments_js(limit * 3):
                    _ingest(c['author'], c['text'])

                nb = self._click_load_more_buttons()
                if nb:
                    time.sleep(1.5)

                current_total = len(all_comments)
                new_count     = current_total - prev_total
                prev_total    = current_total

                # Single stale increment per round
                if new_count == 0:
                    stale_rounds += 1
                    scroll_px = 1400
                else:
                    stale_rounds = 0
                    scroll_px    = 700

                print(
                    f"   Round {round_num:>3}: "
                    f"+{new_count:>4} new  │  "
                    f"total {current_total:>4}  │  "
                    f"stale {stale_rounds}  │  "
                    f"scroll {scroll_px}px"
                    + ('' if moved else '  [panel bottom]')
                )

        finally:
            try:
                page.remove_listener('response', on_response)
            except Exception:
                pass

        status = (
            "limit reached" if len(all_comments) >= limit
            else f"stalled after {stale_rounds} dry rounds"
        )
        print(f"\n   ✅ {len(all_comments)} comments │ "
            f"{round_num} rounds │ {status}")
        return all_comments[:limit]
    
    def _extract_is_verified(self) -> Optional[bool]:
        print("\n✓  EXTRACTING VERIFIED STATUS...")
        try:
            for sel in [
                'svg[aria-label="Verified"]',
                'span[title="Verified"]',
                '[data-testid="verified-badge"]',
            ]:
                if self.driver.find_elements(By.CSS_SELECTOR, sel):
                    print("   ✅ Verified account detected")
                    return True
            print("   ℹ️  Not verified")
            return False
        except Exception:
            print("   ⚠️  Verification check failed")
            return None
    # ========================================================
    # MAIN ENRICHMENT METHOD
    # ========================================================

    def enrich_post(self, post_url: str, comment_limit: int = 10) -> Dict:
        print(f"\n{'='*60}")
        print(f"📸 ENRICHING INSTAGRAM POST (ENHANCED + GEO)")
        print(f"{'='*60}")
        print(f"URL: {post_url}")
        print(f"{'='*60}\n")

        try:
            if not self.driver:
                self._setup_driver()

            print("⏳ Loading post...")
            self.driver.get(post_url)
            time.sleep(7)
            if '/accounts/login' in self.driver.current_url:
                raise Exception("Redirected to login! Session expired — log in again in Profile 5 and re-run.")
            print("✅ Loaded")
            self._close_popups()
            self.driver.execute_script("window.scrollTo(0, 500);"); time.sleep(2)
            self.driver.execute_script("window.scrollTo(0, 0);"); time.sleep(2)

            username = self._extract_username()
            if not username: raise Exception("Could not extract username")
            print(f"\n✅ @{username}")

            caption = self._extract_caption()
            hashtags = self._extract_hashtags(caption)
            mentions = re.findall(r'@[\w.]+', caption) if caption else []
            likes = self._extract_likes()
            comments_count = self._extract_comments_count()
            author_name = self._extract_author_name()
            author_profile_url = f"https://www.instagram.com/{username}/"
            post_date = self._extract_post_date()
            shares = self._extract_shares()
            views = self._extract_views()
            location = self._extract_location()
            post_type = self._extract_post_type()
            comment_texts = self._extract_comment_texts(limit=comment_limit)

            if comments_count == 0 and comment_texts:
                genuine_comments = [c for c in comment_texts if not re.match(r'^\d+\s*(minutes?|hours?|days?|weeks?|months?|years?)\s*ago$', c.get('text', ''), re.IGNORECASE) and c.get('text', '').lower() not in ['no comments yet', 'start the conversation', 'start the conversation.'] and len(c.get('text', '')) > 2]
                if genuine_comments:
                    comment_texts = genuine_comments; comments_count = len(genuine_comments)
                    print(f"   📊 {comments_count} genuine comments found")
                else:
                    comment_texts = []; print("   📊 No genuine comments — all were UI artifacts")

            geo_location = None; geo_confidence = 0; geo_details = {}
            if not location:
                print("\n📍 No native location — running geolocation enrichment...")
                post_image_url = self._extract_post_image_url()
                geo = GeoLocationEnricher(driver=self.driver, claude_api_key=self.claude_api_key)
                geo_result = geo.enrich(caption=caption, hashtags=hashtags, post_date=post_date, username=username, author_name=author_name, post_image_url=post_image_url or "", run_visual_analysis=bool(self.claude_api_key))
                geo_location = geo_result.best_location; geo_confidence = geo_result.best_confidence; geo_details = geo_result.to_dict()
            else:
                print(f"\n📍 Native location: {location}")

            print(f"\n⏳ Navigating to profile...")
            self.driver.get(f"https://www.instagram.com/{username}/"); time.sleep(5)
            self._close_popups()
            profile_data = self._extract_profile_data()

            engagement_rate = 0
            if profile_data['followers'] > 0:
                engagement_rate = ((likes + comments_count) / profile_data['followers']) * 100

            result = {
                'post_url': post_url, 'post_type': post_type, 'post_date': post_date,
                'username': username, 'author_name': author_name,
                'author_profile_url': author_profile_url,
                'follower_count': profile_data['followers'],
                'following_count': profile_data['following'],
                'posts_count': profile_data['posts'],
                'likes': likes, 'comments': comments_count,
                'shares': shares, 'views': views,
                'engagement_rate': round(engagement_rate, 2),
                'caption': caption, 'hashtags': hashtags, 'mentions': mentions,
                'location': location if location else geo_location,
                'location_source': 'instagram_tag' if location else 'geo_enrichment',
                'location_confidence': 1.0 if location else geo_confidence,
                'geo_enrichment': geo_details if not location else {},
                'comment_texts': comment_texts,
                'scraped_at': datetime.now().isoformat()
            }
            result["is_verified"] = self._extract_is_verified()

            try:
                bp_enricher = BrandPulseEnricher()
                bp_fields = bp_enricher.enrich(result)
                result.update(bp_fields)
                print(f"\n✅ BrandPulse: {len(result.get('product_mentions',[]))} products, {len(result.get('partner_mentions',[]))} partners, intent={result.get('intent_level',{}).get('level','?')}, {len(result.get('topic_tags',[]))} topics, {len(result.get('campaign_tags',[]))} campaigns")
            except Exception as e:
                print(f"\n⚠️  BrandPulse enrichment failed: {e}")

            try:
                bp_v2 = BrandPulseEnricherV2()
                v2_fields = bp_v2.enrich(result)
                result.update(v2_fields)
                print(f"✅ BrandPulse V2: city={result.get('city','—')}, county={result.get('county','—')}, account={result.get('account_type',{}).get('type','?')}, brand_mentions={result.get('brand_mentions',{}).get('count',0)}, verified={result.get('is_verified')}")
            except Exception as e:
                print(f"\n⚠️  BrandPulse V2 failed: {e}")

            src = result['location_source']; conf = f"{result['location_confidence']:.0%}"
            print(f"\n✅ ENRICHMENT COMPLETE!")
            print(f"{'='*60}")
            print(f"   Type: {result['post_type']} | Date: {result['post_date']}")
            print(f"   Author: {result['author_name']} (@{result['username']})")
            print(f"   Followers: {result['follower_count']:,}")
            print(f"   Likes: {result['likes']} | Comments: {result['comments']} ({len(result['comment_texts'])} texts)")
            print(f"   Shares: {result['shares']} | Views: {result['views']}")
            print(f"   Location: {result['location']} ({src}, {conf})")
            print(f"   Caption: {len(result['caption'])} chars | Hashtags: {len(result['hashtags'])} | Mentions: {len(result['mentions'])}")
            print(f"   Engagement: {result['engagement_rate']}%")
            print(f"{'='*60}\n")
            return result

        except Exception as e:
            print(f"\n❌ ERROR: {e}\n")
            raise


# ================================================================
# USAGE
# ================================================================

if __name__ == "__main__":
    scraper = InstagramScraperEnhanced(
        cookies={},
        headless=False,
        claude_api_key=None
    )

    test_urls = [
        'https://www.instagram.com/p/DRqpgFQkrtX/',
    ]

    try:
        result = scraper.enrich_post(test_urls[0])
        with open('instagram_enhanced_result.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n🎉 SUCCESS! Check instagram_enhanced_result.json\n")
    finally:
        scraper.close()