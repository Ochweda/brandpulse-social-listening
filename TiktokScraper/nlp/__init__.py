"""
BrandPulse NLP Package
======================
Language detection, sentiment analysis, and keyword extraction
for English, Swahili, and Sheng text.

Usage:
    from nlp.brandpulse_nlp_enricher import BrandPulseNLPEnricher
    enricher = BrandPulseNLPEnricher()
    nlp_fields = enricher.enrich(post_dict)
"""

from nlp.nlp_engine import detect_language, analyze_sentiment, extract_keywords
from nlp.brandpulse_nlp_enricher import BrandPulseNLPEnricher

__all__ = [
    "detect_language",
    "analyze_sentiment",
    "extract_keywords",
    "BrandPulseNLPEnricher",
]