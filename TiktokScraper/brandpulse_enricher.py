"""
BrandPulse Post-Processing Enrichment Layer
=============================================
Adds 7 new analysis fields ON TOP of existing scraped data.
No scraper changes needed — this processes the final result dict.

New fields added to each post:
    1. product_mentions   — Isuzu models found in caption/comments
    2. partner_mentions   — Partner brands found in caption/comments
    3. intent_level       — high / medium / low / none
    4. topic_tags         — pricing, financing, quality, etc.
    5. emoji_summary      — emoji counts + sentiment mapping
    6. platform           — "instagram" (hardcoded for now)
    7. campaign_tags      — hashtags/slogans mapped to campaign names

Usage (standalone):
    enricher = BrandPulseEnricher()
    enriched_post = enricher.enrich(scraped_post_dict)

Usage (integrated into scraper):
    # In enrich_post(), right before building `result`:
    bp = BrandPulseEnricher()
    bp_fields = bp.enrich(result)
    result.update(bp_fields)

Author: BrandPulse Analytics / Big Bold Red
"""

import re
from typing import Dict, List, Optional
from collections import Counter


# ================================================================
# SECTION 1: KEYWORD DATABASES
# ================================================================
# These are the reference dictionaries that power each enrichment.
# They are separated from the logic so you can update them without
# touching the code — eventually these move to a config file or DB.

# ----------------------------------------------------------------
# 1A. PRODUCT / MODEL DATABASE
# ----------------------------------------------------------------
# Maps regex patterns → canonical product names.
# Patterns handle common misspellings, missing hyphens, etc.
# Each entry: (compiled_regex, canonical_name, product_category)

PRODUCT_PATTERNS = [
    # Light Commercial Vehicles (LCV)
    (re.compile(r'\b[dD][\-\s]?[mM][aA][xX]\b'),              'D-MAX',       'LCV / Pickup'),
    (re.compile(r'\b[mM][uU][\-\s]?[xX]\b'),                  'MU-X',        'SUV'),
    (re.compile(r'\bmu\s*x\b', re.I),                          'MU-X',        'SUV'),

    # Medium / Heavy Commercial Vehicles
    (re.compile(r'\b[fF][rR][rR]\b'),                          'FRR',         'Medium Truck'),
    (re.compile(r'\b[fF][vV][zZ]\b'),                          'FVZ',         'Heavy Truck'),
    (re.compile(r'\b[fF][sS][rR]\b'),                          'FSR',         'Medium Truck'),
    (re.compile(r'\b[fF][tT][sS]\b'),                          'FTS',         'Heavy Truck'),
    (re.compile(r'\b[nN][qQ][rR]\b'),                          'NQR',         'Medium Truck'),
    (re.compile(r'\b[nN][mM][rR]\b'),                          'NMR',         'Light Truck'),
    (re.compile(r'\b[nN][pP][sS]\b'),                          'NPS',         'Truck / Game Viewer'),
    (re.compile(r'\b[nN][pP][rR]\b'),                          'NPR',         'Medium Truck'),
    (re.compile(r'\b[gG][xX][rR]\b'),                          'GXR',         'Heavy Truck'),
    (re.compile(r'\b[cC][yY][zZ]\b'),                          'CYZ',         'Heavy Truck'),
    (re.compile(r'\b[eE][xX][rR]\b'),                          'EXR',         'Prime Mover'),
    (re.compile(r'\b[gG][iI][gG][aA]\b'),                     'GIGA',        'Heavy Truck'),

    # Generic brand-level product terms
    (re.compile(r'\b[tT]ipper\b'),                             'Tipper',      'Truck Body Type'),
    (re.compile(r'\b[gG]ame\s*[vV]iewer\b'),                  'Game Viewer', 'Safari / Tourism'),
    (re.compile(r'\b[pP]ick[\-\s]?up\b'),                     'Pickup',      'LCV / Pickup'),
    (re.compile(r'\b[sS][uU][vV]\b'),                         'SUV',         'SUV'),
]

# ----------------------------------------------------------------
# 1B. PARTNER BRANDS DATABASE
# ----------------------------------------------------------------
# Maps regex patterns → canonical partner name + partner type.
# Partner type helps with reporting (bank, fuel, tourism, etc.)

PARTNER_PATTERNS = [
    # Banks & Financial Institutions
    (re.compile(r'\b[cC]o[\-\s]?op\s*[bB]ank\b'),            'Co-op Bank',              'Banking'),
    (re.compile(r'\b[nN][cC][bB][aA]\s*[bB]ank\b'),          'NCBA Bank',               'Banking'),
    (re.compile(r'\b[nN][cC][bB][aA]\b'),                     'NCBA Bank',               'Banking'),
    (re.compile(r'\b[sS]tanbic\s*[bB]ank\b'),                'Stanbic Bank',            'Banking'),
    (re.compile(r'\b[sS]tanbic\b'),                           'Stanbic Bank',            'Banking'),
    (re.compile(r'\bI\s*&\s*M\s*[bB]ank\b'),                 'I&M Bank',                'Banking'),
    (re.compile(r'\b[dD]iamond\s*[tT]rust\s*[bB]ank\b'),     'Diamond Trust Bank',      'Banking'),
    (re.compile(r'\b[dD][tT][bB]\b'),                         'Diamond Trust Bank (DTB)','Banking'),
    (re.compile(r'\b[eE]quity\s*[bBgG]'),                     'Equity Bank/Group',       'Banking'),
    (re.compile(r'\b[eE]quity\b'),                            'Equity Bank',             'Banking'),
    (re.compile(r'\b[kK][cC][bB]\b'),                         'KCB Bank',                'Banking'),
    (re.compile(r'\b[aA]bsa\b'),                              'Absa Bank',               'Banking'),
    (re.compile(r'\b[bB]arclays\b'),                          'Absa/Barclays',           'Banking'),

    # Fuel & Energy
    (re.compile(r'\b[sS]hell\b'),                             'Shell',                   'Fuel & Energy'),
    (re.compile(r'\b[tT]otal\s*[eE]nergies?\b'),             'TotalEnergies',           'Fuel & Energy'),
    (re.compile(r'\b[rR]ubis\b'),                             'Rubis Energy',            'Fuel & Energy'),

    # Insurance
    (re.compile(r'\b[bB]ritam\b'),                            'Britam',                  'Insurance'),
    (re.compile(r'\b[jJ]ubilee\s*[iI]nsurance\b'),           'Jubilee Insurance',       'Insurance'),
    (re.compile(r'\b[aA][pP][aA]\s*[iI]nsurance\b'),         'APA Insurance',           'Insurance'),

    # Tourism & Events
    (re.compile(r'\b[tT][oO][sS]\s*[kK]enya\b'),             'TOS Kenya',               'Tourism'),
    (re.compile(r'\b[tT]our\s*[oO]perators?\s*[sS]ociety\b'),'TOS Kenya',               'Tourism'),
    (re.compile(r'\b[kK][wW][sS]\b'),                        'KWS',                     'Wildlife/Tourism'),
    (re.compile(r'\b[kK]enya\s*[wW]ildlife\b'),              'KWS',                     'Wildlife/Tourism'),

    # Athletes / Ambassadors
    (re.compile(r'\b[eE]liud\s*[kK]ipchoge\b'),              'Eliud Kipchoge',          'Brand Ambassador'),
    (re.compile(r'\b[kK]ipchoge\b'),                         'Eliud Kipchoge',          'Brand Ambassador'),

    # M-Pesa / Safaricom
    (re.compile(r'\b[mM][\-\s]?[pP]esa\b'),                  'M-Pesa',                  'Mobile Money'),
    (re.compile(r'\b[sS]afaricom\b'),                        'Safaricom',               'Telco'),
]

# ----------------------------------------------------------------
# 1C. INTENT KEYWORDS
# ----------------------------------------------------------------
# Three tiers. Each keyword list is checked against caption + comments.
# We return the HIGHEST intent level found.

INTENT_KEYWORDS = {
    'high': {
        'keywords': [
            'buy', 'buying', 'purchase', 'purchased', 'order', 'ordered',
            'book', 'booking', 'booked', 'apply', 'applied', 'applying',
            'contact', 'call', 'whatsapp', 'inbox', 'dm me', 'dm us',
            'visit', 'visiting', 'showroom', 'dealer', 'dealership',
            'interested', 'need', 'i need', 'looking for', 'want to buy',
            'how much', 'what price', 'bei gani', 'bei ni', 'how do i get',
            'where can i', 'where do i', 'where to buy', 'where to get',
            'test drive', 'test-drive', 'financing', 'loan', 'installment',
            'deposit', 'down payment', 'repayment', 'napenda kununua',
            'nataka', 'nitaorder', 'naomba', 'nipe number',
        ],
        'patterns': [
            re.compile(r'\b0[17]\d{8}\b'),          # Kenyan phone numbers
            re.compile(r'\+254\s*\d{9}\b'),          # +254 numbers
            re.compile(r'\b0800\s*\d{3}\s*\d{3}\b'), # Toll-free
        ]
    },
    'medium': {
        'keywords': [
            'compare', 'comparing', 'versus', 'vs', 'vs.',
            'consider', 'considering', 'thinking', 'thinking about',
            'review', 'reviews', 'feedback', 'opinion', 'opinions',
            'recommend', 'recommendation', 'which one', 'which model',
            'better', 'best', 'worth it', 'is it good', 'any good',
            'pros and cons', 'experience', 'thoughts', 'advice',
            'nikushauri', 'gari gani', 'which truck',
        ],
        'patterns': []
    },
    'low': {
        'keywords': [
            'saw', 'seen', 'spotted', 'looks like', 'looks good',
            'nice', 'beautiful', 'trending', 'viral', 'heard about',
            'heard of', 'fire', 'goals', 'dream car', 'dream truck',
            'one day', 'some day', 'wish', 'i wish', 'maybe',
            'nimeona', 'nimesspot', 'poa', 'safi', 'dope',
        ],
        'patterns': []
    }
}

# ----------------------------------------------------------------
# 1D. TOPIC TAGS
# ----------------------------------------------------------------
# Maps topic categories → keyword lists.
# A post can match MULTIPLE topics.

TOPIC_KEYWORDS = {
    'pricing': [
        'price', 'pricing', 'cost', 'costs', 'affordable', 'expensive',
        'cheap', 'budget', 'value', 'worth', 'ksh', 'kshs', 'million',
        'shillings', 'bei', 'bei gani', 'how much', 'discount', 'offer',
        'sale', 'grand sale', 'clearance', 'reduced', 'markdown',
        '9.9 million', '13.5 million', 'million to',
    ],
    'financing': [
        'financing', 'finance', 'financed', 'loan', 'loans', 'installment',
        'installments', 'repayment', 'repay', 'monthly', 'deposit',
        'down payment', 'bank', 'credit', 'mpesa', 'm-pesa', 'statement',
        'grace period', 'working capital', 'co-op bank', 'ncba', 'stanbic',
        'equity', 'dtb', 'i&m bank', 'diamond trust',
        '60-72months', '60-90 days', '95-100%', 'asset finance',
    ],
    'quality_durability': [
        'quality', 'durable', 'durability', 'reliable', 'reliability',
        'strong', 'robust', 'tough', 'rugged', 'built', 'solid',
        'efficient', 'performance', 'powerful', 'beast', 'imara',
        'world-class', 'engineering', 'well-built', 'long-lasting',
    ],
    'service_aftersales': [
        'service', 'aftersales', 'after-sales', 'warranty', 'maintenance',
        'repair', 'servicing', 'mechanic', 'workshop', 'support',
        'customer service', 'customer care', 'helpline',
    ],
    'spare_parts': [
        'spare', 'parts', 'spare parts', 'genuine', 'genuine parts',
        'filter', 'filter kit', 'oil filter', 'fuel filter', 'brake',
        'battery', 'tyre', 'tire', 'component', 'replacement',
        'availability', 'available', 'in stock', 'original parts',
    ],
    'delivery': [
        'delivery', 'deliver', 'delivered', 'delivers',
        'turnaround', 'wait', 'waiting', 'order time',
        'shipped', 'shipping', 'dispatch', 'dispatched',
        'isuzu delivers',
    ],
    'technology_features': [
        'technology', 'tech', 'features', 'feature', 'performance',
        'engine', 'litre', 'liter', '3-litre', '2.5', 'horsepower',
        'torque', '4x4', '4wd', 'awd', 'automatic', 'manual',
        'seater', '7-seater', '5-seater', 'comfort', 'leather',
        'infotainment', 'camera', 'sensor', 'cruise control',
        'fuel economy', 'fuel efficient', 'fuel consumption',
        'assembly', 'local assembly', 'assembled',
    ],
    'safari_tourism': [
        'safari', 'game drive', 'game viewer', 'wildlife', 'national park',
        'maasai mara', 'amboseli', 'tsavo', 'samburu', 'tourism',
        'tourist', 'travel', 'road trip', 'roadtrip', 'expedition',
        'tembea', 'tembeakenya', 'explore',
    ],
}

# ----------------------------------------------------------------
# 1E. CAMPAIGN DATABASE
# ----------------------------------------------------------------
# Maps known campaign identifiers → campaign metadata.
# Check hashtags, slogans in caption, and mentions.

CAMPAIGNS = {
    'tembea_tujenga_kenya': {
        'name': 'Tembea Tujenga Kenya (TTK)',
        'type': 'Domestic Tourism',
        'identifiers': {
            'hashtags': ['#tembeatujengekenya', '#ttk', '#tembeakenya', '#tembeaturismo'],
            'slogans': ['tembea tujenga kenya', 'tembea tujenga'],
            'mentions': ['@tembeatujengekenya'],
        }
    },
    'golden_jubilee': {
        'name': 'Isuzu EA 50th Anniversary (Golden Jubilee)',
        'type': 'Corporate Milestone',
        'identifiers': {
            'hashtags': ['#isuzueastafricaat50', '#isuzueaat50', '#isuzugoldenjubilee', '#mbelepamoja'],
            'slogans': ['50th anniversary', 'golden jubilee', 'mbele pamoja', '50 years'],
            'mentions': [],
        }
    },
    'grand_sale': {
        'name': 'Isuzu Grand Sale',
        'type': 'Sales Promotion',
        'identifiers': {
            'hashtags': ['#grandsale', '#isuzugrandsale', '#dtbxisuzukenya'],
            'slogans': ['grand sale', 'pre-used vehicles', 'pre-owned'],
            'mentions': [],
        }
    },
    'kipchoge_dmax': {
        'name': 'Kipchoge x D-MAX Limited Edition',
        'type': 'Ambassador / Product Launch',
        'identifiers': {
            'hashtags': ['#nohumanislimited', '#eliudkipchoge', '#isuzudmax', '#159dmax'],
            'slogans': ['no human is limited', 'limited edition 159', 'kipchoge'],
            'mentions': [],
        }
    },
    'mux_local_assembly': {
        'name': 'MU-X Local Assembly Launch',
        'type': 'Product Launch',
        'identifiers': {
            'hashtags': ['#isuzumux', '#muxkenya', '#muxlaunch'],
            'slogans': ['local assembly', 'locally assembled', 'first of its kind in africa',
                        'assembly of the isuzu mu-x', 'assembly of the mu-x'],
            'mentions': [],
        }
    },
    'isuzu_delivers': {
        'name': 'Isuzu Delivers',
        'type': 'Brand / Always-On',
        'identifiers': {
            'hashtags': ['#isuzudelivers'],
            'slogans': ['isuzu delivers'],
            'mentions': [],
        }
    },
    'genuine_parts': {
        'name': 'Genuine Isuzu Parts',
        'type': 'Aftersales / Parts',
        'identifiers': {
            'hashtags': ['#genuineisuzuparts', '#genuineparts'],
            'slogans': ['genuine isuzu parts', 'genuine parts'],
            'mentions': [],
        }
    },
    'setting_the_pace': {
        'name': 'TOSK Setting The Pace',
        'type': 'Tourism Partnership',
        'identifiers': {
            'hashtags': ['#tosksettingthepace', '#settingthepace'],
            'slogans': ['setting the pace'],
            'mentions': ['@toskenya'],
        }
    },
}

# ----------------------------------------------------------------
# 1F. EMOJI SENTIMENT MAP
# ----------------------------------------------------------------
# Maps individual emojis to a sentiment polarity.
# +1 = positive, -1 = negative, 0 = neutral

EMOJI_SENTIMENT = {
    # Positive
    '🔥': +1, '❤️': +1, '💯': +1, '👍': +1, '🙌': +1, '💪': +1,
    '😍': +1, '🥰': +1, '😊': +1, '😎': +1, '🤩': +1, '✅': +1,
    '🎉': +1, '🎊': +1, '🏆': +1, '⭐': +1, '🌟': +1, '💥': +1,
    '👏': +1, '🤝': +1, '🙏': +1, '💚': +1, '💛': +1, '💙': +1,
    '🤲': +1, '♥️': +1, '😀': +1, '😁': +1, '😃': +1, '😄': +1,
    '🥳': +1, '🤗': +1, '👌': +1, '✨': +1, '🌍': +1,
    '🇰🇪': 0,  # Flag — neutral (contextual)

    # Negative
    '😡': -1, '🤬': -1, '😤': -1, '👎': -1, '💔': -1, '😢': -1,
    '😭': -1, '😩': -1, '😠': -1, '🤦': -1, '😒': -1, '😞': -1,
    '😫': -1, '😰': -1, '🙄': -1, '👊': -1, '⚠️': -1,
    '😕': -1, '😟': -1, '😣': -1, '🤢': -1, '💀': -1,

    # Neutral / Ambiguous
    '😂': 0, '🤣': 0, '😅': 0, '🤔': 0, '😏': 0, '🤷': 0,
    '📱': 0, '📸': 0, '📍': 0, '🚗': 0, '🚙': 0, '🚚': 0,
    '📞': 0, '💰': 0, '🏢': 0, '🛣️': 0,
}


# ================================================================
# SECTION 2: ENRICHMENT ENGINE
# ================================================================

class BrandPulseEnricher:
    """
    Post-processing enrichment engine.

    Takes a scraped post dict and returns a dict of NEW fields
    that should be merged into the post.

    All analysis is done on text already in the scraped result —
    no additional web requests or browser actions needed.
    """

    def __init__(self):
        """Initialize with default keyword databases."""
        self.product_patterns = PRODUCT_PATTERNS
        self.partner_patterns = PARTNER_PATTERNS
        self.intent_keywords = INTENT_KEYWORDS
        self.topic_keywords = TOPIC_KEYWORDS
        self.campaigns = CAMPAIGNS
        self.emoji_sentiment = EMOJI_SENTIMENT

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # HELPER: Combine all text sources from a post
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def _get_all_text(self, post: Dict) -> str:
        """Combine caption + comment texts into one searchable block."""
        parts = []

        # Caption
        caption = post.get('caption', '') or ''
        parts.append(caption)

        # Comment texts
        for comment in post.get('comment_texts', []):
            parts.append(comment.get('text', ''))

        return '\n'.join(parts)

    def _get_comment_text_only(self, post: Dict) -> str:
        """Just the comments, no caption."""
        return '\n'.join(
            c.get('text', '') for c in post.get('comment_texts', [])
        )

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # FIELD 1: PRODUCT MENTIONS
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def extract_product_mentions(self, post: Dict) -> List[Dict]:
        """
        Scan caption + comments for Isuzu product/model names.

        Returns list of dicts:
            [{"product": "D-MAX", "category": "LCV / Pickup", "count": 3,
              "found_in": ["caption", "comments"]}]

        HOW IT WORKS:
        - Iterates through PRODUCT_PATTERNS (compiled regexes)
        - Searches caption and comments separately (to track source)
        - Deduplicates by canonical name
        - Counts total occurrences
        """
        print("\n🚗 ENRICHMENT: PRODUCT MENTIONS")

        caption = post.get('caption', '') or ''
        comments_text = self._get_comment_text_only(post)

        found = {}  # canonical_name → {category, caption_count, comment_count}

        for pattern, canonical, category in self.product_patterns:
            cap_hits = len(pattern.findall(caption))
            com_hits = len(pattern.findall(comments_text))

            if cap_hits or com_hits:
                if canonical not in found:
                    found[canonical] = {
                        'category': category,
                        'caption_count': 0,
                        'comment_count': 0,
                        'found_in': set()
                    }
                found[canonical]['caption_count'] += cap_hits
                found[canonical]['comment_count'] += com_hits
                if cap_hits:
                    found[canonical]['found_in'].add('caption')
                if com_hits:
                    found[canonical]['found_in'].add('comments')

        results = []
        for product, data in found.items():
            total = data['caption_count'] + data['comment_count']
            entry = {
                'product': product,
                'category': data['category'],
                'count': total,
                'found_in': sorted(data['found_in'])
            }
            results.append(entry)
            print(f"   ✅ {product} ({data['category']}) — {total}x in {', '.join(entry['found_in'])}")

        if not results:
            print("   ℹ️  No product mentions found")

        return results

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # FIELD 2: PARTNER MENTIONS
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def extract_partner_mentions(self, post: Dict) -> List[Dict]:
        """
        Scan caption + comments for partner brand mentions.

        Returns list of dicts:
            [{"partner": "Co-op Bank", "type": "Banking", "count": 1,
              "found_in": ["caption"]}]

        HOW IT WORKS:
        - Same pattern-matching approach as product_mentions
        - Uses PARTNER_PATTERNS with compiled regexes
        - Tracks where each mention was found
        """
        print("\n🤝 ENRICHMENT: PARTNER MENTIONS")

        caption = post.get('caption', '') or ''
        comments_text = self._get_comment_text_only(post)

        found = {}  # canonical → {type, counts, found_in}

        for pattern, canonical, partner_type in self.partner_patterns:
            cap_hits = len(pattern.findall(caption))
            com_hits = len(pattern.findall(comments_text))

            if cap_hits or com_hits:
                if canonical not in found:
                    found[canonical] = {
                        'type': partner_type,
                        'caption_count': 0,
                        'comment_count': 0,
                        'found_in': set()
                    }
                found[canonical]['caption_count'] += cap_hits
                found[canonical]['comment_count'] += com_hits
                if cap_hits:
                    found[canonical]['found_in'].add('caption')
                if com_hits:
                    found[canonical]['found_in'].add('comments')

        results = []
        for partner, data in found.items():
            total = data['caption_count'] + data['comment_count']
            entry = {
                'partner': partner,
                'type': data['type'],
                'count': total,
                'found_in': sorted(data['found_in'])
            }
            results.append(entry)
            print(f"   ✅ {partner} ({data['type']}) — {total}x")

        if not results:
            print("   ℹ️  No partner mentions found")

        return results

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # FIELD 3: INTENT LEVEL
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def extract_intent_level(self, post: Dict) -> Dict:
        """
        Classify user/audience intent from caption + comments.

        Returns:
            {"level": "high", "confidence": 0.85,
             "signals": ["how much", "call", "+254..."],
             "source": "caption+comments"}

        HOW IT WORKS:
        - Scans ALL text (caption + comments) for intent keywords
        - Checks highest tier first (high → medium → low)
        - Also runs regex patterns (phone numbers = high intent)
        - Returns the HIGHEST intent level with matched signals
        - Confidence is based on signal count and tier
        """
        print("\n🎯 ENRICHMENT: INTENT LEVEL")

        all_text = self._get_all_text(post)
        all_text_lower = all_text.lower()

        # Track signals per level
        level_signals = {'high': [], 'medium': [], 'low': []}

        for level, config in self.intent_keywords.items():
            # Keyword matching
            for kw in config['keywords']:
                if kw.lower() in all_text_lower:
                    level_signals[level].append(kw)

            # Pattern matching (phone numbers etc.)
            for pattern in config.get('patterns', []):
                matches = pattern.findall(all_text)
                for m in matches:
                    level_signals[level].append(f"[pattern: {m}]")

        # Determine highest level
        if level_signals['high']:
            level = 'high'
            signals = level_signals['high']
            confidence = min(0.7 + (len(signals) * 0.05), 0.95)
        elif level_signals['medium']:
            level = 'medium'
            signals = level_signals['medium']
            confidence = min(0.5 + (len(signals) * 0.05), 0.80)
        elif level_signals['low']:
            level = 'low'
            signals = level_signals['low']
            confidence = min(0.4 + (len(signals) * 0.05), 0.70)
        else:
            level = 'none'
            signals = []
            confidence = 0.0

        # Deduplicate signals, keep up to 5
        unique_signals = list(dict.fromkeys(signals))[:5]

        result = {
            'level': level,
            'confidence': round(confidence, 2),
            'signals': unique_signals,
            'signal_count': len(signals),
        }

        print(f"   {'✅' if level != 'none' else 'ℹ️'} Intent: {level} (conf: {confidence:.2f})")
        if unique_signals:
            print(f"   📊 Signals: {', '.join(unique_signals[:3])}...")

        return result

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # FIELD 4: TOPIC TAGS
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def extract_topic_tags(self, post: Dict) -> List[Dict]:
        """
        Tag post with product/service topic categories.

        Returns list of dicts:
            [{"topic": "financing", "confidence": 0.8,
              "keywords_matched": ["financing", "loan", "Co-op Bank"],
              "match_count": 5}]

        HOW IT WORKS:
        - Scans ALL text for keywords in each topic category
        - A topic is included if >= 1 keyword matches
        - Confidence is based on match count relative to keyword list size
        - Multiple topics can apply to the same post
        """
        print("\n🏷️  ENRICHMENT: TOPIC TAGS")

        all_text = self._get_all_text(post)
        all_text_lower = all_text.lower()

        results = []

        for topic, keywords in self.topic_keywords.items():
            matched = []
            for kw in keywords:
                if kw.lower() in all_text_lower:
                    matched.append(kw)

            if matched:
                # Confidence: more matches = more confident the topic applies
                match_ratio = len(matched) / len(keywords)
                confidence = min(0.5 + (match_ratio * 0.5) + (len(matched) * 0.03), 0.95)

                entry = {
                    'topic': topic,
                    'confidence': round(confidence, 2),
                    'keywords_matched': matched[:5],  # Top 5 for readability
                    'match_count': len(matched),
                }
                results.append(entry)
                print(f"   ✅ {topic} — {len(matched)} keywords (conf: {confidence:.2f})")

        # Sort by confidence descending
        results.sort(key=lambda x: x['confidence'], reverse=True)

        if not results:
            print("   ℹ️  No topic tags matched")

        return results

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # FIELD 5: EMOJI SUMMARY
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def extract_emoji_summary(self, post: Dict) -> Dict:
        """
        Extract and analyze emoji usage from caption + comments.

        Returns:
            {"total_count": 15, "unique_count": 5,
             "top_emojis": [{"emoji": "🔥", "count": 6, "sentiment": "positive"}],
             "sentiment_breakdown": {"positive": 10, "negative": 0, "neutral": 5},
             "emoji_sentiment_score": 0.67}

        HOW IT WORKS:
        - Uses a broad Unicode regex to extract all emoji characters
        - Counts occurrences of each emoji
        - Maps each to sentiment using EMOJI_SENTIMENT lookup
        - Computes an overall emoji sentiment score (-1 to +1)
        """
        print("\n😀 ENRICHMENT: EMOJI SUMMARY")

        all_text = self._get_all_text(post)

        # Extract emojis using Unicode ranges
        # This covers most common emoji blocks
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # Emoticons
            "\U0001F300-\U0001F5FF"  # Symbols & Pictographs
            "\U0001F680-\U0001F6FF"  # Transport & Map
            "\U0001F1E0-\U0001F1FF"  # Flags
            "\U00002702-\U000027B0"  # Dingbats
            "\U0001F900-\U0001F9FF"  # Supplemental Symbols
            "\U0001FA00-\U0001FA6F"  # Chess Symbols
            "\U0001FA70-\U0001FAFF"  # Symbols Extended-A
            "\U00002600-\U000026FF"  # Misc Symbols
            "\U0000FE00-\U0000FE0F"  # Variation selectors
            "\U0000200D"             # ZWJ
            "\U00002764"             # Heart
            "\U0000270D"             # Writing hand
            "\U00002705"             # Check mark
            "\U00002611"             # Ballot box
            "\U0000274C"             # Cross mark
            "]+",
            flags=re.UNICODE
        )

        found_emojis = emoji_pattern.findall(all_text)
        if not found_emojis:
            print("   ℹ️  No emojis found")
            return {
                'total_count': 0, 'unique_count': 0,
                'top_emojis': [],
                'sentiment_breakdown': {'positive': 0, 'negative': 0, 'neutral': 0},
                'emoji_sentiment_score': 0.0
            }

        # Count each individual emoji character
        emoji_counter = Counter()
        for emoji_group in found_emojis:
            # Some "emojis" are multi-char (ZWJ sequences). Count the group as one.
            emoji_counter[emoji_group] += 1

        total = sum(emoji_counter.values())
        unique = len(emoji_counter)

        # Build top emojis with sentiment
        sentiment_counts = {'positive': 0, 'negative': 0, 'neutral': 0}
        top_emojis = []

        for emoji, count in emoji_counter.most_common(10):
            polarity = self.emoji_sentiment.get(emoji, 0)
            if polarity > 0:
                sentiment_label = 'positive'
            elif polarity < 0:
                sentiment_label = 'negative'
            else:
                sentiment_label = 'neutral'

            sentiment_counts[sentiment_label] += count
            top_emojis.append({
                'emoji': emoji,
                'count': count,
                'sentiment': sentiment_label
            })

        # Overall score: +1 (all positive) to -1 (all negative)
        total_scored = sentiment_counts['positive'] + sentiment_counts['negative']
        if total_scored > 0:
            score = (sentiment_counts['positive'] - sentiment_counts['negative']) / total_scored
        else:
            score = 0.0

        result = {
            'total_count': total,
            'unique_count': unique,
            'top_emojis': top_emojis[:5],
            'sentiment_breakdown': sentiment_counts,
            'emoji_sentiment_score': round(score, 2)
        }

        print(f"   ✅ {total} emojis ({unique} unique)")
        print(f"   📊 Sentiment: +{sentiment_counts['positive']} / "
              f"-{sentiment_counts['negative']} / ~{sentiment_counts['neutral']}"
              f" → score: {score:.2f}")
        if top_emojis:
            print(f"   🏆 Top: {' '.join(e['emoji'] for e in top_emojis[:5])}")

        return result

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # FIELD 6: PLATFORM
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    @staticmethod
    def extract_platform(post: Dict) -> str:
        """
        Tag the source platform. Currently hardcoded to 'instagram'.
        When multi-platform scraping is added, this will inspect the
        post_url domain to determine the platform.
        """
        url = post.get('post_url', '')
        if 'instagram.com' in url:
            return 'instagram'
        elif 'tiktok.com' in url:
            return 'tiktok'
        elif 'twitter.com' in url or 'x.com' in url:
            return 'twitter'
        elif 'facebook.com' in url:
            return 'facebook'
        elif 'youtube.com' in url:
            return 'youtube'
        elif 'linkedin.com' in url:
            return 'linkedin'
        return 'unknown'

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # FIELD 7: CAMPAIGN TAGS
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def extract_campaign_tags(self, post: Dict) -> List[Dict]:
        """
        Map post to known campaigns based on hashtags, slogans, and mentions.

        Returns list of dicts:
            [{"campaign_id": "golden_jubilee",
              "campaign_name": "Isuzu EA 50th Anniversary",
              "campaign_type": "Corporate Milestone",
              "match_signals": ["#isuzueaat50", "#mbelepamoja"],
              "confidence": 0.9}]

        HOW IT WORKS:
        - For each campaign in CAMPAIGNS database:
          1. Check if any of its hashtags appear in post hashtags
          2. Check if any of its slogans appear in caption text
          3. Check if any of its @mentions appear in post mentions
        - A campaign is tagged if >= 1 identifier matches
        - Confidence scales with number of matches
        - A post can match MULTIPLE campaigns
        """
        print("\n📢 ENRICHMENT: CAMPAIGN TAGS")

        # Normalize post data for comparison
        post_hashtags_lower = [
            h.lower().strip() for h in post.get('hashtags', [])
        ]
        caption_lower = (post.get('caption', '') or '').lower()
        post_mentions_lower = [
            m.lower().strip() for m in post.get('mentions', [])
        ]

        results = []

        for campaign_id, campaign in self.campaigns.items():
            match_signals = []
            identifiers = campaign['identifiers']

            # Check hashtags
            for ht in identifiers.get('hashtags', []):
                if ht.lower() in post_hashtags_lower:
                    match_signals.append(ht)

            # Check slogans in caption
            for slogan in identifiers.get('slogans', []):
                if slogan.lower() in caption_lower:
                    match_signals.append(f'slogan: "{slogan}"')

            # Check @mentions
            for mention in identifiers.get('mentions', []):
                if mention.lower() in post_mentions_lower:
                    match_signals.append(mention)

            if match_signals:
                # More matches = higher confidence
                confidence = min(0.6 + (len(match_signals) * 0.1), 0.95)

                entry = {
                    'campaign_id': campaign_id,
                    'campaign_name': campaign['name'],
                    'campaign_type': campaign['type'],
                    'match_signals': list(dict.fromkeys(match_signals)),  # dedupe
                    'confidence': round(confidence, 2),
                }
                results.append(entry)
                print(f"   ✅ {campaign['name']} — {len(match_signals)} signals (conf: {confidence:.2f})")

        # Sort by confidence
        results.sort(key=lambda x: x['confidence'], reverse=True)

        if not results:
            print("   ℹ️  No campaign matches")

        return results

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # MASTER: RUN ALL ENRICHMENTS
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    def enrich(self, post: Dict) -> Dict:
        """
        Run all 7 enrichment methods on a scraped post dict.

        Returns a dict of NEW fields to merge into the post:
            {
                'product_mentions': [...],
                'partner_mentions': [...],
                'intent_level': {...},
                'topic_tags': [...],
                'emoji_summary': {...},
                'platform': 'instagram',
                'campaign_tags': [...]
            }
        """
        print("\n" + "=" * 60)
        print("📊 BRANDPULSE ENRICHMENT — PROCESSING POST")
        print("=" * 60)
        print(f"   Post: {post.get('post_url', 'N/A')}")
        print(f"   Author: @{post.get('username', '?')}")

        fields = {
            'product_mentions':  self.extract_product_mentions(post),
            'partner_mentions':  self.extract_partner_mentions(post),
            'intent_level':      self.extract_intent_level(post),
            'topic_tags':        self.extract_topic_tags(post),
            'emoji_summary':     self.extract_emoji_summary(post),
            'platform':          self.extract_platform(post),
            'campaign_tags':     self.extract_campaign_tags(post),
        }

        # Summary
        products = len(fields['product_mentions'])
        partners = len(fields['partner_mentions'])
        topics = len(fields['topic_tags'])
        campaigns = len(fields['campaign_tags'])
        intent = fields['intent_level']['level']
        emojis = fields['emoji_summary']['total_count']

        print(f"\n{'='*60}")
        print(f"✅ BRANDPULSE ENRICHMENT COMPLETE")
        print(f"   Products: {products} | Partners: {partners}")
        print(f"   Topics: {topics} | Campaigns: {campaigns}")
        print(f"   Intent: {intent} | Emojis: {emojis}")
        print(f"{'='*60}\n")

        return fields


# ================================================================
# SECTION 3: BATCH PROCESSING UTILITY
# ================================================================

def enrich_scraped_json(input_path: str, output_path: str = None) -> Dict:
    """
    Process an entire scraped JSON file (with metadata.posts array).

    Usage:
        enrich_scraped_json('isuzukenya_scraped.json', 'isuzukenya_enriched.json')

    This reads the file, enriches every post, writes the result,
    and prints a summary.
    """
    import json

    if output_path is None:
        base = input_path.rsplit('.', 1)[0]
        output_path = f"{base}_enriched.json"

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    enricher = BrandPulseEnricher()
    posts = data.get('posts', [])

    print(f"\n🚀 Enriching {len(posts)} posts from {input_path}...")
    print(f"{'='*60}\n")

    for i, post in enumerate(posts, 1):
        print(f"\n{'─'*40}")
        print(f"📌 POST {i}/{len(posts)}: {post.get('post_url', 'N/A')}")
        print(f"{'─'*40}")

        new_fields = enricher.enrich(post)
        post.update(new_fields)

    # Add enrichment metadata
    from datetime import datetime
    data['metadata']['brandpulse_enriched_at'] = datetime.now().isoformat()
    data['metadata']['brandpulse_fields_added'] = [
        'product_mentions', 'partner_mentions', 'intent_level',
        'topic_tags', 'emoji_summary', 'platform', 'campaign_tags'
    ]

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"🎉 DONE! Enriched {len(posts)} posts → {output_path}")
    print(f"{'='*60}\n")

    return data


# ================================================================
# SECTION 4: STANDALONE TEST
# ================================================================

if __name__ == "__main__":
    # Quick test with a sample post dict
    sample = {
        "post_url": "https://www.instagram.com/p/DUSsV0FjhDi/",
        "username": "phyllisfromisuzu",
        "caption": (
            "A historic milestone for Kenya and Africa 🇰🇪🌍\n"
            "Yesterday, Isuzu East Africa officially launched the assembly of the "
            "Isuzu MU-X in Kenya — the first of its kind in Africa.\n"
            "This 7-seater SUV represents world-class engineering, local assembly "
            "excellence, and Isuzu's continued commitment to the African market.\n"
            "Built for comfort, performance, and reliability — ready for families, "
            "executives, and fleets alike."
        ),
        "hashtags": ["#IsuzuKenya", "#isuzukenya"],
        "mentions": [],
        "comment_texts": [
            {"author": "fan1", "text": "Dream car 🔥🔥🔥 how much is it?"},
            {"author": "fan2", "text": "This is a beast! 😍 Where can I test drive?"},
        ],
    }

    enricher = BrandPulseEnricher()
    result = enricher.enrich(sample)

    import json
    print("\n📋 ENRICHMENT OUTPUT:")
    print(json.dumps(result, indent=2, ensure_ascii=False))