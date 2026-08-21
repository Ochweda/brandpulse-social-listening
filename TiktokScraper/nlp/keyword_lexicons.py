"""
BrandPulse Keyword Lexicons
============================
Trilingual positive/negative keyword dictionaries for
English, Swahili, and Sheng sentiment keyword extraction.

These are used by nlp_engine.extract_keywords() to identify
emotional drivers in post captions and comments.

Automotive/brand-specific terms are included alongside
general sentiment words.
"""

# ──────────────────────────────────────────────────────────
# POSITIVE KEYWORDS
# ──────────────────────────────────────────────────────────

POSITIVE_KEYWORDS = {
    "en": [
        # General positive
        "amazing", "awesome", "beautiful", "best", "brilliant",
        "clean", "comfortable", "durable", "excellent", "fantastic",
        "fast", "good", "gorgeous", "great", "impressive",
        "incredible", "love", "luxurious", "magnificent", "nice",
        "perfect", "powerful", "premium", "quality", "reliable",
        "sleek", "smooth", "solid", "spacious", "strong",
        "stunning", "superb", "superior", "tough", "wonderful",
        # Automotive specific
        "beast", "fire", "fuel-efficient", "rugged", "torque",
        "horsepower", "turbo", "offroad", "4wd", "awd",
        # Social media slang (English)
        "goat", "king", "queen", "legend", "iconic", "elite",
        "insane", "lit", "sick", "dope", "clutch",
    ],
    "sw": [
        # Swahili positive
        "nzuri", "bora", "safi", "kubwa", "imara", "hodari",
        "tamu", "mzuri", "pendeza", "fahari", "furaha", "ajabu",
        "maridadi", "bomba", "nguvu", "shupavu", "jasiri",
        "kamili", "kuu", "bwana", "nzuri sana", "bora zaidi",
        "kubwa sana", "ya ajabu", "yenye nguvu",
    ],
    "sheng": [
        # Sheng positive
        "kali", "poa", "fiti", "safi", "noma", "dope", "fire",
        "mbichi", "freshi", "rada", "chap chap", "legit",
        "deadly", "moto", "bazu", "ngangari", "tite",
        "imeshika", "inabamba", "imebeba",
    ],
}

# ──────────────────────────────────────────────────────────
# NEGATIVE KEYWORDS
# ──────────────────────────────────────────────────────────

NEGATIVE_KEYWORDS = {
    "en": [
        # General negative
        "awful", "bad", "boring", "broken", "cheap", "complaint",
        "damaged", "dangerous", "defective", "disappointing",
        "disgusting", "dull", "expensive", "failure", "faulty",
        "flimsy", "garbage", "horrible", "issue", "junk",
        "lemon", "mediocre", "noisy", "overpriced", "poor",
        "problem", "recall", "rough", "rusty", "scam",
        "slow", "terrible", "trash", "ugly", "unreliable",
        "useless", "waste", "weak", "worst",
        # Automotive specific
        "breakdown", "stalling", "overheating", "leaking",
        "rattling", "rust", "accident", "repair",
    ],
    "sw": [
        # Swahili negative
        "mbaya", "mbovu", "bovu", "ghali", "dhaifu", "hatari",
        "haramu", "ovyo", "kibaya", "kichefuchefu", "taabu",
        "hasira", "uchungu", "kero", "duni", "hafifu",
        "mbaya sana", "ghali sana", "si nzuri",
    ],
    "sheng": [
        # Sheng negative
        "fala", "ngori", "bwaku", "kunoma", "mbaya", "trash",
        "waste", "kujipanga", "chizi", "bure kabisa",
        "imechapa", "imeoza", "haiendi", "ngumu",
    ],
}

# ──────────────────────────────────────────────────────────
# SHENG MARKERS (for language detection heuristic)
# ──────────────────────────────────────────────────────────

SHENG_MARKERS = [
    # Common Sheng words that distinguish from standard Swahili
    "safi", "poa", "fiti", "mambo", "niaje", "vipi",
    "mbaya", "noma", "kali", "fala", "manze", "ati",
    "maze", "buda", "dem", "mathee", "mbogi", "wasee",
    "doo", "kasheshe", "ngori", "rada", "chapaa",
    "sahii", "saii", "baze", "form", "ndai", "gava",
    "mtu", "jo", "bro", "maze", "enyewe", "aki",
    "lakini", "si", "kwani", "eeh", "aih", "kumbe",
    "sherehe", "kifing", "kanairo", "mresh", "dishi",
]

# ──────────────────────────────────────────────────────────
# SWAHILI MARKERS (for language detection)
# ──────────────────────────────────────────────────────────

SWAHILI_MARKERS = [
    "gari", "magari", "mzuri", "sana", "kubwa", "ndogo",
    "nzuri", "nchi", "watu", "mtu", "kazi", "nyumba",
    "askari", "duka", "sokoni", "barabara", "dereva",
    "safari", "haraka", "pole", "karibu", "asante",
    "habari", "shikamoo", "marahaba", "ndio", "hapana",
    "tafadhali", "pamoja", "kwa", "hii", "hiyo",
    "yake", "yetu", "wao", "sisi", "ninyi", "wewe",
    "yeye", "mimi", "anayeendesha", "inaendesha",
    "inafanya", "inaweza", "lazima", "bado", "tayari",
    "kesho", "jana", "leo", "sasa", "wakati",
    "mpya", "zamani", "bei", "gharama", "fedha",
    "shilingi", "pesa", "biashara", "soko", "uza",
    "nunua", "thamani", "nguvu", "imara", "hodari",
    "kubwa", "ndogo", "ndefu", "fupi", "bora",
    "kabisa", "zaidi", "kuliko", "kama", "ingawa",
    "lakini", "kwa sababu", "ili", "hata", "pia",
    "ama", "au", "wala", "bali", "ila",
    "na", "ya", "wa", "la", "cha",
    "vya", "kwa", "katika", "juu", "chini",
]