"""
Apply two fixes to instagram_scraper_enhanced_geo.py:
1. Comments count fallback — use len(comment_texts) when _extract_comments_count() returns 0
2. Geo enrichment trimming — limit signals and all_candidates to top 3 in output

Run: python apply_fixes.py
(expects instagram_scraper_enhanced_geo.py in same directory)
"""

import sys

filename = 'instagram_scraper_python.py'

try:
    with open(filename, 'r', encoding='utf-8') as f:
        code = f.read()
except FileNotFoundError:
    print(f"❌ {filename} not found in current directory")
    sys.exit(1)

fixes_applied = 0

# ============================================================
# FIX 1: Comments count fallback
# ============================================================
# The _extract_comments_count() method only finds "View all X comments"
# but Instagram doesn't always show that (e.g. when all comments fit on
# screen, or on older posts). Fix: after extracting comment_texts, use
# len(comment_texts) as fallback if comments_count is still 0.

OLD_COMMENTS = """\
            comment_texts = self._extract_comment_texts(limit=10)

            # Geolocation enrichment"""

NEW_COMMENTS = """\
            comment_texts = self._extract_comment_texts(limit=10)

            # Fix: use actual extracted comments as fallback for comment count
            if comments_count == 0 and comment_texts:
                comments_count = len(comment_texts)
                print(f"   📊 Comments count updated from extracted texts: {comments_count}")

            # Geolocation enrichment"""

if OLD_COMMENTS in code:
    code = code.replace(OLD_COMMENTS, NEW_COMMENTS, 1)
    fixes_applied += 1
    print("✅ Fix 1 applied: Comments count fallback")
else:
    print("⚠️  Fix 1: Could not find target text — may already be applied or code changed")


# ============================================================
# FIX 2: Limit geo_enrichment output to top 3
# ============================================================
# The to_dict() method currently dumps ALL signals (48 in your sample!)
# and ALL candidates (34+). Trim both to top 3 by score/confidence.

OLD_TODICT = """\
    def to_dict(self) -> Dict:
        return {
            'best_location': self.best_location,
            'best_confidence': round(self.best_confidence, 2),
            'method_used': self.method_used,
            'signals_count': len(self.signals),
            'signals': [asdict(s) for s in self.signals],
            'all_candidates': self.all_candidates
        }"""

NEW_TODICT = """\
    def to_dict(self) -> Dict:
        # Sort signals by confidence (highest first) and keep top 3
        top_signals = sorted(self.signals, key=lambda s: s.confidence, reverse=True)[:3]
        # all_candidates is already sorted by score — keep top 3
        top_candidates = self.all_candidates[:3]
        return {
            'best_location': self.best_location,
            'best_confidence': round(self.best_confidence, 2),
            'method_used': self.method_used,
            'signals_count': len(self.signals),
            'top_signals': [asdict(s) for s in top_signals],
            'top_candidates': top_candidates
        }"""

if OLD_TODICT in code:
    code = code.replace(OLD_TODICT, NEW_TODICT, 1)
    fixes_applied += 1
    print("✅ Fix 2 applied: Geo enrichment trimmed to top 3")
else:
    print("⚠️  Fix 2: Could not find target text — may already be applied or code changed")


# Write back
if fixes_applied > 0:
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(code)
    print(f"\n🎉 {fixes_applied}/2 fixes applied to {filename}")
else:
    print(f"\n⚠️  No fixes applied — check the file")