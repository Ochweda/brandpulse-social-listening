"""
BrandPulse Enricher V2 — Missing Fields Module
================================================
Adds 5 fields to the scraped post output:
  1. city              (LOC-02)  — extracted from geo_enrichment signals
  2. county            (LOC-03)  — mapped from city via Kenyan counties lookup
  3. brand_mentions    (BRD-03)  — Isuzu name count incl. misspelling variants
  4. account_type      (INF-02)  — classified from follower count + username patterns
  5. is_verified       (INF-01)  — placeholder (requires scraper-level change; see SCRAPER_PATCH below)

Language detection (LNG-01) and sentiment scoring (EMO-04) are handled
externally via Google Cloud NLP API through n8n workflows.

Usage:
    from brandpulse_enricher_v2 import BrandPulseEnricherV2
    enricher_v2 = BrandPulseEnricherV2()
    new_fields = enricher_v2.enrich(post_dict)
    post_dict.update(new_fields)

Zero external dependencies. Drop alongside brandpulse_enricher.py.
"""

import re


# ═══════════════════════════════════════════════════════════════════
# KENYAN CITIES DATABASE — city → (county, latitude, longitude, area_type)
# ═══════════════════════════════════════════════════════════════════

KENYAN_CITIES = {
    # Major urban centres
    "nairobi":    ("Nairobi County",     -1.2921,  36.8219, "urban"),
    "mombasa":    ("Mombasa County",     -4.0435,  39.6682, "urban"),
    "kisumu":     ("Kisumu County",      -0.1022,  34.7617, "urban"),
    "nakuru":     ("Nakuru County",      -0.3031,  36.0800, "urban"),
    "eldoret":    ("Uasin Gishu County",  0.5143,  35.2698, "urban"),
    "thika":      ("Kiambu County",      -1.0396,  37.0900, "urban"),
    "malindi":    ("Kilifi County",      -3.2138,  40.1169, "urban"),
    "kitale":     ("Trans-Nzoia County",  1.0187,  35.0020, "urban"),
    "garissa":    ("Garissa County",     -0.4532,  39.6461, "urban"),
    "nyeri":      ("Nyeri County",       -0.4197,  36.9511, "urban"),

    # Peri-urban / secondary towns
    "nanyuki":    ("Laikipia County",     0.0067,  37.0722, "peri-urban"),
    "naivasha":   ("Nakuru County",      -0.7171,  36.4310, "peri-urban"),
    "machakos":   ("Machakos County",    -1.5177,  37.2634, "peri-urban"),
    "kericho":    ("Kericho County",     -0.3692,  35.2863, "peri-urban"),
    "embu":       ("Embu County",        -0.5388,  37.4596, "peri-urban"),
    "meru":       ("Meru County",         0.0480,  37.6559, "peri-urban"),
    "lamu":       ("Lamu County",        -2.2717,  40.9020, "peri-urban"),
    "nandi":      ("Nandi County",        0.1836,  35.1269, "peri-urban"),
    "isiolo":     ("Isiolo County",       0.3546,  37.5822, "peri-urban"),
    "kajiado":    ("Kajiado County",     -1.8524,  36.7820, "peri-urban"),
    "kiambu":     ("Kiambu County",      -1.1714,  36.8356, "peri-urban"),
    "narok":      ("Narok County",       -1.0876,  35.8600, "peri-urban"),
    "migori":     ("Migori County",      -1.0634,  34.4731, "peri-urban"),
    "bungoma":    ("Bungoma County",      0.5635,  34.5607, "peri-urban"),
    "kakamega":   ("Kakamega County",     0.2827,  34.7519, "peri-urban"),
    "voi":        ("Taita-Taveta County",-3.3961,  38.5566, "peri-urban"),
    "nyahururu":  ("Laikipia County",     0.0381,  36.3660, "peri-urban"),
    "muranga":    ("Murang'a County",    -0.7210,  37.1527, "peri-urban"),
    "murang'a":   ("Murang'a County",    -0.7210,  37.1527, "peri-urban"),
    "kirinyaga":  ("Kirinyaga County",   -0.6591,  37.2927, "peri-urban"),
    "nyandarua":  ("Nyandarua County",   -0.3980,  36.5230, "peri-urban"),
    "laikipia":   ("Laikipia County",     0.0925,  36.8513, "peri-urban"),
    "marsabit":   ("Marsabit County",     2.3284,  37.9900, "peri-urban"),
    "mandera":    ("Mandera County",      3.9373,  41.8569, "peri-urban"),
    "wajir":      ("Wajir County",        1.7471,  40.0573, "peri-urban"),
    "turkana":    ("Turkana County",      3.1166,  35.5966, "peri-urban"),
    "lodwar":     ("Turkana County",      3.1166,  35.5966, "peri-urban"),
    "samburu":    ("Samburu County",      1.1748,  36.8948, "peri-urban"),
    "maralal":    ("Samburu County",      1.1003,  36.6980, "peri-urban"),
    "moyale":     ("Marsabit County",     3.5270,  39.0564, "peri-urban"),
    "homa bay":   ("Homa Bay County",    -0.5273,  34.4571, "peri-urban"),
    "siaya":      ("Siaya County",       -0.0617,  34.2881, "peri-urban"),
    "kitui":      ("Kitui County",       -1.3670,  38.0106, "peri-urban"),
    "makueni":    ("Makueni County",     -1.8039,  37.6195, "peri-urban"),
    "tharaka":    ("Tharaka-Nithi County",-0.3077,  37.7238, "peri-urban"),
    "nithi":      ("Tharaka-Nithi County",-0.3077,  37.7238, "peri-urban"),
    "kwale":      ("Kwale County",       -4.1737,  39.4521, "peri-urban"),
    "kilifi":     ("Kilifi County",      -3.5107,  39.8562, "peri-urban"),
    "taita":      ("Taita-Taveta County",-3.3961,  38.5566, "peri-urban"),
    "taveta":     ("Taita-Taveta County",-3.3961,  38.5566, "peri-urban"),
    "baringo":    ("Baringo County",      0.4710,  35.9643, "peri-urban"),
    "elgeyo":     ("Elgeyo-Marakwet County", 0.7674, 35.5084, "peri-urban"),
    "marakwet":   ("Elgeyo-Marakwet County", 0.7674, 35.5084, "peri-urban"),
    "bomet":      ("Bomet County",       -0.7813,  35.3428, "peri-urban"),
    "nyamira":    ("Nyamira County",     -0.5633,  34.9340, "peri-urban"),
    "kisii":      ("Kisii County",       -0.6698,  34.7675, "peri-urban"),
    "west pokot": ("West Pokot County",   1.6210,  35.2400, "peri-urban"),
    "kapenguria": ("West Pokot County",   1.2389,  35.1119, "peri-urban"),
    "tana river": ("Tana River County",  -1.5000,  39.9883, "peri-urban"),

    # Nairobi neighbourhood aliases
    "cbd":        ("Nairobi County",     -1.2864,  36.8172, "urban"),
    "westlands":  ("Nairobi County",     -1.2637,  36.8031, "urban"),
    "karen":      ("Nairobi County",     -1.3197,  36.7110, "urban"),
    "langata":    ("Nairobi County",     -1.3552,  36.7444, "urban"),
    "jkia":       ("Nairobi County",     -1.3192,  36.9275, "urban"),
    "makina":     ("Nairobi County",     -1.3106,  36.7827, "urban"),

    # Satellite towns
    "syokimau":   ("Machakos County",    -1.3808,  36.9375, "peri-urban"),
    "athi river": ("Machakos County",    -1.4581,  36.9826, "peri-urban"),
    "rongai":     ("Kajiado County",     -1.3958,  36.7583, "peri-urban"),
    "kikuyu":     ("Kiambu County",      -1.2466,  36.6817, "peri-urban"),
    "ruiru":      ("Kiambu County",      -1.1490,  36.9603, "peri-urban"),
    "juja":       ("Kiambu County",      -1.1045,  37.0144, "peri-urban"),
    "limuru":     ("Kiambu County",      -1.1130,  36.6490, "peri-urban"),

    # Coastal aliases
    "diani":      ("Kwale County",       -4.3477,  39.5681, "peri-urban"),
    "watamu":     ("Kilifi County",      -3.3540,  40.0240, "peri-urban"),
    "nyali":      ("Mombasa County",     -4.0167,  39.7126, "urban"),
    "bamburi":    ("Mombasa County",     -3.9907,  39.7244, "urban"),
}


# ═══════════════════════════════════════════════════════════════════
# ACCOUNT TYPE PATTERNS (checked in specificity order: sales > media > brand)
# ═══════════════════════════════════════════════════════════════════

SALES_PATTERNS = [
    r"fromisuzu", r"dealer", r"sales", r"motors\b", r"auto\b",
    r"autospares", r"spares", r"trucks?kenya", r"watrucks",
    r"consultant", r"agent",
]

MEDIA_PATTERNS = [
    r"news", r"media", r"press", r"journal", r"reporter",
    r"editor", r"blog", r"magazine", r"chronicle",
    r"daily", r"standard", r"nation", r"hivileo",
    r"tv\b", r"radio", r"fm\b", r"broadcast",
]

BRAND_PATTERNS = [
    r"isuzu", r"isuzukenya", r"isuzueastafrica", r"isuzuea",
    r"toyota", r"honda", r"ford", r"mitsubishi", r"nissan",
]


# ═══════════════════════════════════════════════════════════════════
# BRAND NAME DETECTION — canonical name + misspelling variants (BRD-03)
# ═══════════════════════════════════════════════════════════════════

BRAND_NAME_PATTERNS = [
    # (pattern, variant_label, case_insensitive?)
    (r'\bisuzu\b',    "Isuzu",  True),
    (r'\bizuzu\b',    "Izuzu",  True),
    (r'\biszu\b',     "Iszu",   True),
    (r'\biszuzu\b',   "Iszuzu", True),
    (r'\bisszu\b',    "Isszu",  True),
    (r'\bissuzu\b',   "Issuzu", True),
    (r'\bisuzo\b',    "Isuzo",  True),
    (r'\bizuso\b',    "Izuso",  True),
    (r'\bısuzu\b',    "ısuzu",  False),   # Turkish dotless-i — match literal only (no IGNORECASE)
]


class BrandPulseEnricherV2:
    """
    Post-processing enricher that adds 5 new fields to scraped Instagram posts.
    Operates on the already-scraped JSON dict — no browser/API calls needed.
    """

    def __init__(self):
        self.sales_re = [re.compile(p, re.IGNORECASE) for p in SALES_PATTERNS]
        self.media_re = [re.compile(p, re.IGNORECASE) for p in MEDIA_PATTERNS]
        self.brand_re = [re.compile(p, re.IGNORECASE) for p in BRAND_PATTERNS]
        self.brand_name_re = [
            (re.compile(p, re.IGNORECASE if ci else 0), name)
            for p, name, ci in BRAND_NAME_PATTERNS
        ]

    def enrich(self, post: dict) -> dict:
        """
        Main entry point. Takes a scraped post dict, returns a dict of new fields.
        Caller should do: post.update(enricher_v2.enrich(post))
        """
        city_data = self.extract_city(post)
        county_data = self.extract_county(city_data.get("city"))
        account_data = self.classify_account(post)
        brand_data = self.extract_brand_mentions(post)

        return {
            # LOC-02: City
            "city": city_data.get("city"),
            "city_confidence": city_data.get("confidence", 0.0),
            "city_source": city_data.get("source"),

            # LOC-03: County + area type
            "county": county_data.get("county"),
            "area_type": county_data.get("area_type"),

            # LOC-02/03/OUT-05: Lat/Lon (top-level for heatmap)
            "latitude": city_data.get("latitude") or county_data.get("latitude"),
            "longitude": city_data.get("longitude") or county_data.get("longitude"),

            # BRD-03: Brand name mentions (incl. misspellings)
            "brand_mentions": brand_data,

            # INF-02/03/04: Account type
            "account_type": account_data,

            # INF-01: Verified (placeholder — needs scraper patch)
            "is_verified": post.get("is_verified", None),
        }

    # ───────────────────────────────────────────────────────────────
    # BRD-03: BRAND NAME MENTIONS (incl. misspellings)
    # ───────────────────────────────────────────────────────────────

    def extract_brand_mentions(self, post: dict) -> dict:
        """
        Count Isuzu brand name mentions including common misspellings
        across caption + comment texts. Returns brand name, total count,
        variants found, and where they appeared.
        """
        caption = post.get("caption") or ""
        comment_text = " ".join(
            c.get("text", "") for c in post.get("comment_texts", [])
        )

        total_count = 0
        variants_found = []
        found_in = set()

        for pattern, variant_name in self.brand_name_re:
            cap_hits = len(pattern.findall(caption))
            com_hits = len(pattern.findall(comment_text))

            if cap_hits > 0:
                found_in.add("caption")
            if com_hits > 0:
                found_in.add("comments")

            hits = cap_hits + com_hits
            if hits > 0:
                total_count += hits
                if variant_name != "Isuzu":
                    variants_found.append({"variant": variant_name, "count": hits})

        return {
            "brand": "Isuzu",
            "count": total_count,
            "variants_found": variants_found,
            "found_in": sorted(list(found_in)),
        }

    # ───────────────────────────────────────────────────────────────
    # LOC-02: CITY EXTRACTION
    # ───────────────────────────────────────────────────────────────

    def extract_city(self, post: dict) -> dict:
        """
        Extract city from geo_enrichment signals.
        Priority: geo top_signals (city source) > top_candidates > location field > caption scan
        """
        geo = post.get("geo_enrichment", {})
        best_city = None
        best_confidence = 0.0
        best_source = None
        best_lat = None
        best_lon = None

        # Strategy 1: Check top_signals for city-source detections
        for signal in geo.get("top_signals", []):
            source = signal.get("source", "")
            location = signal.get("location", "")

            if "city" in source.lower():
                city_name = self._parse_city_from_location(location)
                if city_name:
                    conf = signal.get("confidence", 0.5)
                    if conf > best_confidence:
                        best_city = city_name
                        best_confidence = conf
                        best_source = source
                        best_lat = signal.get("latitude")
                        best_lon = signal.get("longitude")

        # Strategy 2: Check top_candidates for city-level locations
        for candidate in geo.get("top_candidates", []):
            location = candidate.get("location", "")
            city_name = self._parse_city_from_location(location)
            if city_name and candidate.get("max_confidence", 0) > best_confidence:
                if "," in location or city_name.lower() in KENYAN_CITIES:
                    best_city = city_name
                    best_confidence = candidate.get("max_confidence", 0.5)
                    best_source = ", ".join(candidate.get("sources", []))
                    best_lat = candidate.get("latitude")
                    best_lon = candidate.get("longitude")

        # Strategy 3: Parse the top-level location field
        if not best_city:
            location_str = post.get("location", "")
            city_name = self._parse_city_from_location(location_str)
            if city_name and city_name.lower() in KENYAN_CITIES:
                best_city = city_name
                best_confidence = post.get("location_confidence", 0.5) * 0.8
                best_source = "location_field_parse"

        # Strategy 4: Scan caption for known city names
        if not best_city:
            caption = (post.get("caption") or "").lower()
            for city_key in KENYAN_CITIES:
                pattern = r'\b' + re.escape(city_key) + r'\b'
                if re.search(pattern, caption):
                    best_city = city_key.title()
                    best_confidence = 0.55
                    best_source = "caption_city_scan"
                    break

        # Resolve coordinates from KENYAN_CITIES if not already set
        if best_city and not best_lat:
            city_key = best_city.lower()
            if city_key in KENYAN_CITIES:
                _, lat, lon, _ = KENYAN_CITIES[city_key]
                best_lat = lat
                best_lon = lon

        return {
            "city": best_city,
            "confidence": round(best_confidence, 2) if best_city else None,
            "source": best_source,
            "latitude": best_lat,
            "longitude": best_lon,
        }

    def _parse_city_from_location(self, location_str: str) -> str | None:
        """Parse city name from strings like 'Nairobi, Kenya' or 'Eldoret, Kenya'."""
        if not location_str:
            return None

        location_str = location_str.strip()

        if "," in location_str:
            city_part = location_str.split(",")[0].strip()
            if city_part.lower() in KENYAN_CITIES:
                return city_part.title()

        if location_str.lower() in KENYAN_CITIES:
            return location_str.title()

        return None

    # ───────────────────────────────────────────────────────────────
    # LOC-03: COUNTY MAPPING
    # ───────────────────────────────────────────────────────────────

    def extract_county(self, city: str | None) -> dict:
        """Map a city name to its Kenyan county, area type, and coordinates."""
        if not city:
            return {"county": None, "area_type": None, "latitude": None, "longitude": None}

        city_key = city.lower().strip()
        if city_key in KENYAN_CITIES:
            county, lat, lon, area = KENYAN_CITIES[city_key]
            return {"county": county, "area_type": area, "latitude": lat, "longitude": lon}

        return {"county": None, "area_type": None, "latitude": None, "longitude": None}

    # ───────────────────────────────────────────────────────────────
    # INF-02/03/04: ACCOUNT TYPE CLASSIFICATION
    # ───────────────────────────────────────────────────────────────

    def classify_account(self, post: dict) -> dict:
        """
        Classify the post author as:
          sales_professional | media | brand | macro_influencer |
          micro_influencer | nano_influencer | individual
        Checks patterns in specificity order (sales > media > brand),
        then falls back to follower-count thresholds.
        """
        username = (post.get("username") or "").lower()
        followers = post.get("follower_count", 0) or 0

        for pattern in self.sales_re:
            if pattern.search(username):
                return {
                    "type": "sales_professional",
                    "confidence": 0.80,
                    "signal": "username matches sales pattern",
                    "follower_tier": self._follower_tier(followers),
                }

        for pattern in self.media_re:
            if pattern.search(username):
                return {
                    "type": "media",
                    "confidence": 0.75,
                    "signal": "username matches media pattern",
                    "follower_tier": self._follower_tier(followers),
                }

        for pattern in self.brand_re:
            if pattern.search(username):
                return {
                    "type": "brand",
                    "confidence": 0.85,
                    "signal": "username matches brand pattern",
                    "follower_tier": self._follower_tier(followers),
                }

        if followers >= 100_000:
            return {
                "type": "macro_influencer",
                "confidence": 0.85,
                "signal": f"{followers:,} followers (≥100K)",
                "follower_tier": "macro",
            }
        elif followers >= 10_000:
            return {
                "type": "micro_influencer",
                "confidence": 0.75,
                "signal": f"{followers:,} followers (10K–100K)",
                "follower_tier": "micro",
            }
        elif followers >= 5_000:
            return {
                "type": "nano_influencer",
                "confidence": 0.65,
                "signal": f"{followers:,} followers (5K–10K)",
                "follower_tier": "nano",
            }
        else:
            return {
                "type": "individual",
                "confidence": 0.60,
                "signal": f"{followers:,} followers (<5K)",
                "follower_tier": "individual",
            }

    def _follower_tier(self, followers: int) -> str:
        if followers >= 100_000: return "macro"
        if followers >= 10_000:  return "micro"
        if followers >= 5_000:   return "nano"
        return "individual"


# ═══════════════════════════════════════════════════════════════════
# BATCH PROCESSING UTILITY
# ═══════════════════════════════════════════════════════════════════

def enrich_v2_json(input_path: str, output_path: str):
    """
    Read a scraped JSON file, apply V2 enrichment to all posts, write output.
    Usage: python brandpulse_enricher_v2.py input.json output.json
    """
    import json

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    enricher = BrandPulseEnricherV2()
    posts = data.get("posts", [])

    for post in posts:
        v2_fields = enricher.enrich(post)
        post.update(v2_fields)

    data.setdefault("metadata", {})
    data["metadata"]["brandpulse_v2_enriched"] = True
    data["metadata"]["v2_fields_added"] = [
        "city", "city_confidence", "city_source",
        "county", "area_type", "latitude", "longitude",
        "brand_mentions", "account_type", "is_verified",
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✅ V2 enrichment complete: {len(posts)} posts → {output_path}")
    return data


# ═══════════════════════════════════════════════════════════════════
# SCRAPER PATCH: is_verified detection
# ═══════════════════════════════════════════════════════════════════
#
# This field CANNOT be detected in post-processing — it requires a
# scraper-level change to check for the verification badge while
# the browser is on the profile page.
#
# Add this method to your scraper class and call it during profile
# data extraction (after navigating to the author's profile):
#
# ┌─────────────────────────────────────────────────────────────┐
# │  def _extract_is_verified(self):                            │
# │      """Check if the current profile has a verified badge."""│
# │      try:                                                   │
# │          selectors = [                                      │
# │              'svg[aria-label="Verified"]',                  │
# │              'span[title="Verified"]',                      │
# │              '[data-testid="verified-badge"]',              │
# │          ]                                                  │
# │          for sel in selectors:                              │
# │              elements = self.driver.find_elements(          │
# │                  By.CSS_SELECTOR, sel                       │
# │              )                                              │
# │              if elements:                                   │
# │                  print("   ✅ Verified account detected")   │
# │                  return True                                │
# │          return False                                       │
# │      except Exception:                                      │
# │          return None  # Unknown — detection failed          │
# │                                                             │
# │  # In your enrich_post() method, add:                       │
# │  result["is_verified"] = self._extract_is_verified()        │
# └─────────────────────────────────────────────────────────────┘
#
# Once the scraper populates is_verified, the V2 enricher will
# pass it through via: post.get("is_verified", None)


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        enrich_v2_json(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python brandpulse_enricher_v2.py <input.json> <output.json>")
        print("   Or: from brandpulse_enricher_v2 import BrandPulseEnricherV2")