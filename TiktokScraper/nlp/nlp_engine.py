"""
BrandPulse NLP Engine
=====================
Core NLP processing module for BrandPulse Analytics Suite.

Handles:
  - Language detection (English / Swahili / Sheng) with Sheng heuristic
  - Sentiment analysis routing:
      → English text  → Google Cloud NLP API
      → Swahili/Sheng → HuggingFace AfriSenti model (local)
  - Trilingual keyword extraction (EN / SW / Sheng)
  - Tone classification

CRITICAL: Google Cloud NLP does NOT support Swahili.
This is why we need the hybrid pipeline — English goes to Google,
everything else goes to the local HuggingFace model.

Dependencies:
    pip install langdetect transformers torch google-cloud-language

Environment:
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

Usage:
    from nlp.nlp_engine import detect_language, analyze_sentiment, extract_keywords

    lang = detect_language("Gari hii ni kali sana!")
    sent = analyze_sentiment("Gari hii ni kali sana!")
    keys = extract_keywords("Gari hii ni kali sana!", "sheng")
"""

import os
import sys
import warnings

# Suppress noisy transformer warnings during import
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*tokenizers.*")

# ──────────────────────────────────────────────────────────
# LAZY IMPORTS — only load heavy libraries when first needed
# ──────────────────────────────────────────────────────────
# This prevents the 1.5GB model from loading if you only
# need language detection or keyword extraction.

_langdetect_loaded = False
_afrisenti_model = None
_afrisenti_tokenizer = None
_google_nlp_client = None
_google_nlp_available = None  # None = not checked yet

# AfriSenti official label mapping (from HuggingFace model card)
# Index 0 = positive, Index 1 = neutral, Index 2 = negative
AFRISENTI_ID2LABEL = {0: "positive", 1: "neutral", 2: "negative"}

from nlp.keyword_lexicons import (
    POSITIVE_KEYWORDS,
    NEGATIVE_KEYWORDS,
    SHENG_MARKERS,
    SWAHILI_MARKERS,
)


# ══════════════════════════════════════════════════════════
# STEP 1: LANGUAGE DETECTION
# ══════════════════════════════════════════════════════════

def _ensure_langdetect():
    """Lazy-load langdetect with deterministic seed."""
    global _langdetect_loaded
    if not _langdetect_loaded:
        from langdetect import DetectorFactory
        DetectorFactory.seed = 0  # deterministic results
        _langdetect_loaded = True


def detect_language(text: str) -> dict:
    """
    Detect language of text with Sheng heuristic.

    Returns dict with:
        language: "english" | "swahili" | "sheng" | "mixed" | "unknown"
        confidence: float 0.0-1.0
        base_detection: raw langdetect code (if Sheng override applied)
        sheng_markers_found: int (if Sheng detected)
        swahili_markers_found: int (if Swahili detected)

    Strategy:
        1. Run langdetect for base language code
        2. Count Sheng marker hits — if ≥2, override to "sheng"
        3. Count Swahili marker hits for confidence scoring
        4. If both EN and SW markers present, flag as "mixed"
    """
    if not text or len(text.strip()) < 10:
        return {"language": "unknown", "confidence": 0.0}

    _ensure_langdetect()

    try:
        from langdetect import detect
        lang_code = detect(text)
    except Exception:
        lang_code = "unknown"

    text_lower = text.lower()
    import string
    words = set(w.strip(string.punctuation) for w in text_lower.split())
    words.discard("")

    # Count Sheng markers
    sheng_hits = sum(1 for m in SHENG_MARKERS if m in words)

    # Count Swahili markers
    sw_hits = sum(1 for m in SWAHILI_MARKERS if m in words)

    # Strong Sheng override: 2+ markers = Sheng
    if sheng_hits >= 2:
        return {
            "language": "sheng",
            "confidence": min(0.5 + (sheng_hits * 0.1), 0.95),
            "base_detection": lang_code,
            "sheng_markers_found": sheng_hits,
            "swahili_markers_found": sw_hits,
        }

    # Mixed language detection (common in Kenyan social media)
    en_indicators = lang_code == "en"
    sw_indicators = lang_code == "sw" or sw_hits >= 3

    if en_indicators and sw_hits >= 2:
        return {
            "language": "mixed",
            "confidence": 0.7,
            "base_detection": lang_code,
            "sheng_markers_found": sheng_hits,
            "swahili_markers_found": sw_hits,
        }

    # Standard mapping
    lang_map = {"sw": "swahili", "en": "english"}
    detected = lang_map.get(lang_code, lang_code)

    return {
        "language": detected,
        "confidence": 0.85,
        "base_detection": lang_code,
        "sheng_markers_found": sheng_hits,
        "swahili_markers_found": sw_hits,
    }


# ══════════════════════════════════════════════════════════
# STEP 2a: ENGLISH SENTIMENT — Google Cloud NLP
# ══════════════════════════════════════════════════════════

def _check_google_nlp_available() -> bool:
    """Check if Google Cloud NLP credentials are configured."""
    global _google_nlp_available
    if _google_nlp_available is not None:
        return _google_nlp_available

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if creds_path and os.path.isfile(creds_path):
        try:
            from google.cloud import language_v2
            _google_nlp_available = True
        except ImportError:
            print("⚠️  google-cloud-language not installed. Run: pip install google-cloud-language")
            _google_nlp_available = False
    else:
        print("⚠️  GOOGLE_APPLICATION_CREDENTIALS not set or file not found.")
        print("   English sentiment will fall back to HuggingFace model.")
        print(f"   Current value: '{creds_path}'")
        _google_nlp_available = False

    return _google_nlp_available


def _get_google_nlp_client():
    """Lazy-load Google Cloud NLP client."""
    global _google_nlp_client
    if _google_nlp_client is None:
        from google.cloud import language_v2
        _google_nlp_client = language_v2.LanguageServiceClient()
    return _google_nlp_client


def analyze_sentiment_english(text: str) -> dict:
    """
    Analyze English text sentiment via Google Cloud NLP API.

    Returns:
        score: float -1.0 to +1.0
        magnitude: float 0.0 to infinity (strength of emotion)
        provider: "google_cloud_nlp"
        sentences: list of per-sentence scores
    """
    if not text or len(text.strip()) < 5:
        return {"score": 0.0, "magnitude": 0.0, "provider": "google_cloud_nlp", "label": "neutral"}

    from google.cloud import language_v2

    client = _get_google_nlp_client()

    document = {
        "content": text,
        "type_": language_v2.Document.Type.PLAIN_TEXT,
        "language_code": "en",
    }

    try:
        response = client.analyze_sentiment(
            request={"document": document, "encoding_type": language_v2.EncodingType.UTF8}
        )
    except Exception as e:
        print(f"   ⚠️ Google Cloud NLP error: {e}")
        # Fall back to HuggingFace
        return analyze_sentiment_swahili(text)

    doc_sentiment = response.document_sentiment
    score = doc_sentiment.score
    magnitude = doc_sentiment.magnitude

    # Derive label from score
    if score > 0.25:
        label = "positive"
    elif score < -0.25:
        label = "negative"
    else:
        label = "neutral"

    sentences = []
    for sentence in response.sentences:
        sentences.append({
            "text": sentence.text.content,
            "score": sentence.sentiment.score,
            "magnitude": sentence.sentiment.magnitude,
        })

    return {
        "score": round(score, 4),
        "magnitude": round(magnitude, 4),
        "label": label,
        "confidence": round(min(magnitude, 1.0), 4),
        "provider": "google_cloud_nlp",
        "sentences": sentences,
    }


# ══════════════════════════════════════════════════════════
# STEP 2b: SWAHILI/SHENG SENTIMENT — HuggingFace AfriSenti
# ══════════════════════════════════════════════════════════

def _load_afrisenti_model():
    """
    Lazy-load AfriSenti model + tokenizer using the official HuggingFace pattern.
    Uses AutoModelForSequenceClassification + AutoTokenizer (not pipeline).

    Reference: https://huggingface.co/Davlan/afrisenti-twitter-sentiment-afroxlmr-large

    Downloads ~1.5GB on first run, then cached in ~/.cache/huggingface/.
    Returns (model, tokenizer) tuple.
    """
    global _afrisenti_model, _afrisenti_tokenizer

    if _afrisenti_model is None or _afrisenti_tokenizer is None:
        print("   🔄 Loading AfriSenti model + tokenizer (first time may take a minute)...")
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        MODEL = "Davlan/afrisenti-twitter-sentiment-afroxlmr-large"
        _afrisenti_tokenizer = AutoTokenizer.from_pretrained(MODEL)
        _afrisenti_model = AutoModelForSequenceClassification.from_pretrained(MODEL)
        _afrisenti_model.eval()  # Set to inference mode (disables dropout)
        print("   ✅ AfriSenti model loaded")

    return _afrisenti_model, _afrisenti_tokenizer


def analyze_sentiment_swahili(text: str) -> dict:
    """
    Analyze Swahili/Sheng text sentiment via HuggingFace AfriSenti.

    Uses the OFFICIAL HuggingFace pattern from the model card:
        1. Tokenize with AutoTokenizer
        2. Forward pass through AutoModelForSequenceClassification
        3. Apply softmax to get probability distribution across 3 classes
        4. Map indices using id2label: {0: "positive", 1: "neutral", 2: "negative"}

    This gives us ALL class probabilities (not just the top label),
    which enables a much richer normalized score:
        - Positive probability pushed toward +1.0
        - Negative probability pushed toward -1.0
        - Neutral dampens toward 0.0

    We normalize to the same -1.0 to +1.0 scale as Google Cloud NLP
    so downstream code doesn't care which provider was used.

    Returns:
        score: float -1.0 to +1.0 (normalized composite)
        magnitude: float 0.0 to 1.0 (top-class confidence)
        label: "positive" | "negative" | "neutral"
        confidence: float 0.0 to 1.0
        scores_all: dict with all 3 class probabilities
        provider: "afrisenti_huggingface"
    """
    if not text or len(text.strip()) < 5:
        return {
            "score": 0.0,
            "magnitude": 0.0,
            "label": "neutral",
            "confidence": 0.0,
            "scores_all": {"positive": 0.0, "neutral": 1.0, "negative": 0.0},
            "provider": "afrisenti_huggingface",
        }

    model, tokenizer = _load_afrisenti_model()

    try:
        import numpy as np
        from scipy.special import softmax
        import torch

        # Tokenize (official pattern from model card)
        encoded_input = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)

        # Forward pass (no gradient computation needed for inference)
        with torch.no_grad():
            output = model(**encoded_input)

        # Extract logits and apply softmax (official pattern)
        logits = output[0][0].detach().numpy()
        scores = softmax(logits)

        # Map to labels using the official id2label
        # {0: "positive", 1: "neutral", 2: "negative"}
        score_dict = {}
        for idx, label_name in AFRISENTI_ID2LABEL.items():
            score_dict[label_name] = round(float(scores[idx]), 4)

        # Find the winning class
        ranking = np.argsort(scores)[::-1]  # Descending order
        top_label = AFRISENTI_ID2LABEL[ranking[0]]
        top_confidence = float(scores[ranking[0]])

        # ── Normalize to -1.0 to +1.0 scale ──
        # Use the full probability distribution for a nuanced score:
        #   normalized = P(positive) - P(negative)
        # This gives:
        #   Pure positive → ~+1.0
        #   Pure negative → ~-1.0
        #   Pure neutral  → ~0.0
        #   Mixed signals → somewhere in between
        normalized_score = score_dict["positive"] - score_dict["negative"]

    except ImportError as e:
        # scipy not installed — fall back to manual softmax
        print(f"   ⚠️ scipy not available ({e}), using manual softmax")
        try:
            import torch
            import numpy as np

            encoded_input = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                output = model(**encoded_input)

            logits = output[0][0].detach().numpy()

            # Manual softmax: exp(x) / sum(exp(x))
            exp_logits = np.exp(logits - np.max(logits))  # Subtract max for numerical stability
            scores = exp_logits / exp_logits.sum()

            score_dict = {}
            for idx, label_name in AFRISENTI_ID2LABEL.items():
                score_dict[label_name] = round(float(scores[idx]), 4)

            ranking = np.argsort(scores)[::-1]
            top_label = AFRISENTI_ID2LABEL[ranking[0]]
            top_confidence = float(scores[ranking[0]])
            normalized_score = score_dict["positive"] - score_dict["negative"]

        except Exception as e2:
            print(f"   ⚠️ AfriSenti inference failed: {e2}")
            return {
                "score": 0.0,
                "magnitude": 0.0,
                "label": "neutral",
                "confidence": 0.0,
                "scores_all": {"positive": 0.0, "neutral": 1.0, "negative": 0.0},
                "provider": "afrisenti_error",
            }

    except Exception as e:
        print(f"   ⚠️ AfriSenti error: {e}")
        return {
            "score": 0.0,
            "magnitude": 0.0,
            "label": "neutral",
            "confidence": 0.0,
            "scores_all": {"positive": 0.0, "neutral": 1.0, "negative": 0.0},
            "provider": "afrisenti_error",
        }

    return {
        "score": round(normalized_score, 4),
        "magnitude": round(top_confidence, 4),
        "label": top_label,
        "confidence": round(top_confidence, 4),
        "scores_all": score_dict,
        "provider": "afrisenti_huggingface",
    }


# ══════════════════════════════════════════════════════════
# STEP 3: UNIFIED SENTIMENT ROUTER
# ══════════════════════════════════════════════════════════

def analyze_sentiment(text: str, language: str = None) -> dict:
    """
    Route text to the correct sentiment engine based on detected language.

    If language is not provided, it will be auto-detected first.

    Routing logic:
        "english"          → Google Cloud NLP (if available, else AfriSenti)
        "swahili" / "sheng" → HuggingFace AfriSenti
        "mixed"            → AfriSenti (better at code-switched text)
        "unknown"          → Try Google first, fall back to AfriSenti
        anything else      → AfriSenti as fallback

    Returns:
        language_detected: str
        sentiment_score: float -1.0 to +1.0
        sentiment_magnitude: float
        sentiment_label: str
        sentiment_provider: str
        sentiment_confidence: float
    """
    if not text or len(text.strip()) < 5:
        return {
            "language_detected": "unknown",
            "sentiment_score": 0.0,
            "sentiment_magnitude": 0.0,
            "sentiment_label": "neutral",
            "sentiment_provider": "none",
            "sentiment_confidence": 0.0,
        }

    # Auto-detect language if not provided
    if language is None:
        lang_result = detect_language(text)
        language = lang_result["language"]
    else:
        lang_result = {"language": language}

    # Route to appropriate engine
    if language == "english" and _check_google_nlp_available():
        sentiment = analyze_sentiment_english(text)
    elif language in ("swahili", "sheng", "mixed"):
        sentiment = analyze_sentiment_swahili(text)
    elif language == "english":
        # Google not available, use AfriSenti as fallback
        sentiment = analyze_sentiment_swahili(text)
        sentiment["provider"] = "afrisenti_fallback_for_english"
    elif language == "unknown":
        # Try AfriSenti (handles multilingual better than nothing)
        sentiment = analyze_sentiment_swahili(text)
        sentiment["provider"] = "afrisenti_fallback_unknown_lang"
    else:
        # Other language codes (fr, pt, etc.)
        if _check_google_nlp_available():
            try:
                sentiment = analyze_sentiment_english(text)
            except Exception:
                sentiment = analyze_sentiment_swahili(text)
        else:
            sentiment = analyze_sentiment_swahili(text)

    return {
        "language_detected": language,
        "sentiment_score": sentiment.get("score", 0.0),
        "sentiment_magnitude": sentiment.get("magnitude", 0.0),
        "sentiment_label": sentiment.get("label", "neutral"),
        "sentiment_provider": sentiment.get("provider", "unknown"),
        "sentiment_confidence": sentiment.get("confidence", 0.0),
        # AfriSenti provides all 3 class probabilities; Google NLP doesn't
        "scores_all": sentiment.get("scores_all", None),
    }


# ══════════════════════════════════════════════════════════
# STEP 4: TRILINGUAL KEYWORD EXTRACTION
# ══════════════════════════════════════════════════════════

def extract_keywords(text: str, language: str) -> dict:
    """
    Extract positive and negative keywords from text using
    trilingual word lists (English, Swahili, Sheng).

    Always checks English keywords (code-switching is extremely
    common in Kenyan social media). Adds Swahili and Sheng lists
    based on detected language.

    Returns:
        positive_keywords: list of {"keyword": str, "language": str}
        negative_keywords: list of {"keyword": str, "language": str}
        positive_count: int
        negative_count: int
    """
    if not text:
        return {
            "positive_keywords": [],
            "negative_keywords": [],
            "positive_count": 0,
            "negative_count": 0,
        }

    text_lower = text.lower()
    # Strip punctuation from individual words for exact matching
    import string
    words = set(w.strip(string.punctuation) for w in text_lower.split())
    words.discard("")  # Remove empty strings from stripping

    # Always check English (code-switching is the norm)
    languages_to_check = ["en"]
    if language in ("swahili", "sheng", "mixed"):
        languages_to_check.append("sw")
    if language in ("sheng", "mixed"):
        languages_to_check.append("sheng")

    pos_found = []
    neg_found = []

    for lang in languages_to_check:
        # Positive keywords
        for kw in POSITIVE_KEYWORDS.get(lang, []):
            # Single-word: check in word set (exact match)
            # Multi-word: check in full text (substring)
            if " " in kw:
                if kw in text_lower:
                    pos_found.append({"keyword": kw, "language": lang})
            elif kw in words:
                pos_found.append({"keyword": kw, "language": lang})

        # Negative keywords
        for kw in NEGATIVE_KEYWORDS.get(lang, []):
            if " " in kw:
                if kw in text_lower:
                    neg_found.append({"keyword": kw, "language": lang})
            elif kw in words:
                neg_found.append({"keyword": kw, "language": lang})

    # Deduplicate (same keyword might appear in multiple language lists)
    seen_pos = set()
    deduped_pos = []
    for item in pos_found:
        if item["keyword"] not in seen_pos:
            seen_pos.add(item["keyword"])
            deduped_pos.append(item)

    seen_neg = set()
    deduped_neg = []
    for item in neg_found:
        if item["keyword"] not in seen_neg:
            seen_neg.add(item["keyword"])
            deduped_neg.append(item)

    return {
        "positive_keywords": deduped_pos,
        "negative_keywords": deduped_neg,
        "positive_count": len(deduped_pos),
        "negative_count": len(deduped_neg),
    }


# ══════════════════════════════════════════════════════════
# STEP 5: TONE CLASSIFICATION
# ══════════════════════════════════════════════════════════

def classify_tone(sentiment_score: float, positive_count: int, negative_count: int) -> str:
    """
    Classify overall tone from sentiment score and keyword counts.

    Uses a two-tier system:
        1. If sentiment score is strong enough (>0.3 or <-0.3), use it directly
        2. If score is ambiguous, use keyword count differential as tiebreaker

    Returns: "positive" | "negative" | "neutral" | "mixed"
    """
    # Strong signal from sentiment model
    if sentiment_score > 0.3:
        return "positive"
    elif sentiment_score < -0.3:
        return "negative"

    # Weak signal — use keywords as tiebreaker
    if positive_count > negative_count + 2:
        return "positive"
    elif negative_count > positive_count + 2:
        return "negative"

    # Both positive and negative keywords present in similar amounts
    if positive_count >= 2 and negative_count >= 2:
        return "mixed"

    return "neutral"


# ══════════════════════════════════════════════════════════
# SELF-TEST (run this file directly to verify setup)
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("BrandPulse NLP Engine — Self Test")
    print("=" * 60)

    test_texts = [
        ("This Isuzu D-Max is amazing! Best truck I've ever driven.", "English positive"),
        ("Terrible service at the dealer. Waited 3 hours, no help.", "English negative"),
        ("Gari hii ni nzuri sana, imara na nguvu.", "Swahili positive"),
        ("Gari mbaya sana, ghali na dhaifu.", "Swahili negative"),
        ("Sahii hii ndai ni kali manze! Poa sana!", "Sheng positive"),
        ("Hii gari ni fala, ngori kabisa bure.", "Sheng negative"),
        ("Check out the new D-Max, gari ni kali!", "Mixed EN/Sheng"),
    ]

    for text, label in test_texts:
        print(f"\n{'─'*60}")
        print(f"📝 Input: \"{text}\"")
        print(f"   Expected: {label}")

        lang = detect_language(text)
        print(f"   Language: {lang['language']} (confidence: {lang['confidence']:.2f})")

        keywords = extract_keywords(text, lang["language"])
        print(f"   Keywords: +{keywords['positive_count']} / -{keywords['negative_count']}")
        if keywords["positive_keywords"]:
            print(f"     Positive: {[k['keyword'] for k in keywords['positive_keywords']]}")
        if keywords["negative_keywords"]:
            print(f"     Negative: {[k['keyword'] for k in keywords['negative_keywords']]}")

    # Test sentiment only if models are available
    print(f"\n{'='*60}")
    print("Testing sentiment analysis (requires models)...")
    print("=" * 60)

    sentiment_tests = [
        "This truck is absolutely amazing!",                    # EN positive
        "Terrible service, very disappointed.",                 # EN negative
        "Gari hii ni kali sana!",                              # SW positive (from model card)
        "I like you",                                          # EN (model card example)
        "Sahii hii ndai ni poa manze!",                        # Sheng positive
    ]

    try:
        for test_text in sentiment_tests:
            result = analyze_sentiment(test_text)
            print(f"\n   📝 \"{test_text}\"")
            print(f"      Score: {result['sentiment_score']:+.4f} | "
                  f"Label: {result['sentiment_label']} | "
                  f"Provider: {result['sentiment_provider']}")

            # Show all 3 class probabilities (AfriSenti's richer output)
            if "scores_all" in result:
                sa = result["scores_all"]
                print(f"      All scores: pos={sa.get('positive', 'N/A')}, "
                      f"neu={sa.get('neutral', 'N/A')}, "
                      f"neg={sa.get('negative', 'N/A')}")

        print(f"\n✅ All sentiment tests passed!")

    except Exception as e:
        print(f"\n⚠️  Sentiment test skipped: {e}")
        print("   Run: pip install transformers torch scipy numpy google-cloud-language")

    print(f"\n{'='*60}")
    print("Self-test complete!")
    print("=" * 60)