"""
BrandPulse NLP Enricher
========================
Wraps nlp_engine.py into an enricher class that follows the same
.enrich(post_dict) pattern as V1 and V2 enrichers.

This is the file you call from your scraper or pipeline:

    from nlp.brandpulse_nlp_enricher import BrandPulseNLPEnricher
    enricher = BrandPulseNLPEnricher()
    nlp_fields = enricher.enrich(post_dict)
    post_dict.update(nlp_fields)

Fields produced (mapped to task tracker):
    ┌──────────────────────────────┬───────────┬──────────────────────────────┐
    │ Field                        │ Task ID   │ Type                         │
    ├──────────────────────────────┼───────────┼──────────────────────────────┤
    │ language_detected            │ LNG-01    │ str: "english"/"swahili"/    │
    │                              │           │      "sheng"/"mixed"         │
    │ language_confidence          │ LNG-01    │ float 0.0-1.0               │
    │ sheng_markers_found          │ LNG-03    │ int                         │
    │ tone                         │ LNG-02    │ str: "positive"/"negative"/ │
    │                              │           │      "neutral"/"mixed"       │
    │ sentiment_score              │ EMO-04    │ float -1.0 to +1.0         │
    │ sentiment_magnitude          │ EMO-04    │ float 0.0+                  │
    │ sentiment_label              │ EMO-04    │ str                         │
    │ sentiment_provider           │ EMO-04    │ str: provider name          │
    │ sentiment_confidence         │ EMO-04    │ float 0.0-1.0              │
    │ sentiment_scores_all        │ EMO-04    │ dict: {positive, neutral,  │
    │                              │           │        negative} probs     │
    │ positive_keywords            │ EMO-02    │ list of {keyword, language} │
    │ negative_keywords            │ EMO-03    │ list of {keyword, language} │
    │ positive_keyword_count       │ EMO-02    │ int                         │
    │ negative_keyword_count       │ EMO-03    │ int                         │
    │ comment_sentiment_avg        │ OUT-01    │ float or None               │
    │ comment_sentiments_detail    │ OUT-01    │ list of sentiment dicts     │
    └──────────────────────────────┴───────────┴──────────────────────────────┘

Dependencies:
    pip install langdetect transformers torch google-cloud-language
"""

from nlp.nlp_engine import (
    detect_language,
    analyze_sentiment,
    extract_keywords,
    classify_tone,
)


class BrandPulseNLPEnricher:
    """
    NLP enricher following the same .enrich(post_dict) interface
    as BrandPulseEnricher (V1) and BrandPulseEnricherV2.

    Usage:
        enricher = BrandPulseNLPEnricher()
        fields = enricher.enrich(post_dict)
        post_dict.update(fields)

    Config:
        max_comments: Max comments to run sentiment on (default 20).
                      Keeps API costs and processing time manageable.
        skip_comment_sentiment: Set True to skip per-comment analysis
                                (faster, saves API calls).
    """

    def __init__(self, max_comments: int = 20, skip_comment_sentiment: bool = False):
        self.max_comments = max_comments
        self.skip_comment_sentiment = skip_comment_sentiment

    def enrich(self, post: dict) -> dict:
        """
        Run full NLP pipeline on a single post.

        Expects post_dict to have (at minimum):
            - caption: str (the post's caption text)

        Optionally uses:
            - comment_texts: list[dict] with "text" key, OR list[str]
            - hashtags: list[str] (stripped before NLP to reduce noise)

        Returns a dict of NLP fields to merge into the post.
        """
        caption = post.get("caption", "") or ""

        # ── 1. LANGUAGE DETECTION (on caption — primary content) ──
        lang_result = detect_language(caption)
        language = lang_result["language"]

        # ── 2. SENTIMENT ANALYSIS (on caption) ──
        caption_sentiment = analyze_sentiment(caption, language=language)

        # ── 3. COMMENT-LEVEL SENTIMENT (optional) ──
        comment_sentiments = []
        comment_avg = None

        if not self.skip_comment_sentiment:
            raw_comments = post.get("comment_texts", []) or []
            comment_texts = self._extract_comment_strings(raw_comments)

            for comment_text in comment_texts[: self.max_comments]:
                if comment_text and len(comment_text.strip()) >= 5:
                    cs = analyze_sentiment(comment_text)
                    comment_sentiments.append({
                        "text": comment_text[:100],  # Truncate for storage
                        "score": cs["sentiment_score"],
                        "label": cs["sentiment_label"],
                        "provider": cs["sentiment_provider"],
                    })

            if comment_sentiments:
                comment_avg = round(
                    sum(c["score"] for c in comment_sentiments) / len(comment_sentiments),
                    4,
                )

        # ── 4. KEYWORD EXTRACTION (caption + comments combined) ──
        # Build full text for keyword scanning
        all_comment_text = " ".join(
            self._extract_comment_strings(post.get("comment_texts", []) or [])
        )
        full_text = f"{caption} {all_comment_text}"

        # Strip hashtags from keyword scan (they pollute results)
        hashtags = post.get("hashtags", []) or []
        for tag in hashtags:
            full_text = full_text.replace(f"#{tag}", "").replace(tag, "")

        keywords = extract_keywords(full_text, language)

        # ── 5. TONE CLASSIFICATION ──
        tone = classify_tone(
            caption_sentiment["sentiment_score"],
            keywords["positive_count"],
            keywords["negative_count"],
        )

        # ── 6. BUILD OUTPUT ──
        return {
            # Language (LNG-01, LNG-03)
            "language_detected": language,
            "language_confidence": lang_result.get("confidence", 0.0),
            "sheng_markers_found": lang_result.get("sheng_markers_found", 0),

            # Tone (LNG-02)
            "tone": tone,

            # Sentiment (EMO-04, OUT-01)
            "sentiment_score": caption_sentiment["sentiment_score"],
            "sentiment_magnitude": caption_sentiment["sentiment_magnitude"],
            "sentiment_label": caption_sentiment["sentiment_label"],
            "sentiment_provider": caption_sentiment["sentiment_provider"],
            "sentiment_confidence": caption_sentiment["sentiment_confidence"],
            # AfriSenti full probability distribution (pos/neu/neg)
            "sentiment_scores_all": caption_sentiment.get("scores_all", None),

            # Keywords (EMO-02, EMO-03)
            "positive_keywords": keywords["positive_keywords"],
            "negative_keywords": keywords["negative_keywords"],
            "positive_keyword_count": keywords["positive_count"],
            "negative_keyword_count": keywords["negative_count"],

            # Comment sentiment (OUT-01)
            "comment_sentiment_avg": comment_avg,
            "comment_sentiments_detail": comment_sentiments if comment_sentiments else None,
        }

    def _extract_comment_strings(self, comments) -> list:
        """
        Normalize comment_texts to a list of strings.

        Handles both formats:
            - list[str]: ["comment1", "comment2"]
            - list[dict]: [{"author": "x", "text": "comment1"}, ...]
        """
        if not comments:
            return []

        strings = []
        for item in comments:
            if isinstance(item, str):
                strings.append(item)
            elif isinstance(item, dict):
                text = item.get("text", "") or item.get("comment", "") or ""
                strings.append(text)

        return strings


# ══════════════════════════════════════════════════════════
# BATCH ENRICHMENT (for processing full JSON files)
# ══════════════════════════════════════════════════════════

def enrich_nlp_batch(posts: list, max_comments: int = 20, verbose: bool = True) -> list:
    """
    Run NLP enrichment on a list of post dicts.

    Usage:
        import json
        with open("brandpulse_output/brandpulse_isuzukenya_20260217_104028.json") as f:
            posts = json.load(f)
        enriched = enrich_nlp_batch(posts)
    """
    enricher = BrandPulseNLPEnricher(max_comments=max_comments)
    results = []

    for i, post in enumerate(posts):
        if verbose:
            username = post.get("username", "?")
            print(f"\n{'='*50}")
            print(f"🧠 NLP Processing {i+1}/{len(posts)}: @{username}")

        nlp_fields = enricher.enrich(post)
        post.update(nlp_fields)
        results.append(post)

        if verbose:
            score = nlp_fields["sentiment_score"]
            lang = nlp_fields["language_detected"]
            tone = nlp_fields["tone"]
            provider = nlp_fields["sentiment_provider"]
            pos = nlp_fields["positive_keyword_count"]
            neg = nlp_fields["negative_keyword_count"]
            print(f"   Language: {lang} | Tone: {tone} | Score: {score:+.3f}")
            print(f"   Provider: {provider} | Keywords: +{pos}/-{neg}")

    return results


# ══════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m nlp.brandpulse_nlp_enricher <input.json> [output.json]")
        print("\nExample:")
        print("  python -m nlp.brandpulse_nlp_enricher brandpulse_output/posts.json enriched.json")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) >= 3 else input_path.replace(".json", "_nlp.json")

    print(f"📂 Loading: {input_path}")
    with open(input_path) as f:
        posts = json.load(f)

    print(f"📊 Processing {len(posts)} posts...")
    enriched = enrich_nlp_batch(posts)

    with open(output_path, "w") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved to: {output_path}")