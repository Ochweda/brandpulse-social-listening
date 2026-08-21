"""
Fix: Filter out Instagram's "Start the conversation." placeholder
from comment extraction and comment count fallback.

Run: python apply_fix_comments.py
(expects instagram_scraper_python.py in same directory)
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
# FIX: Add "Start the conversation." to the ui_skip set
# ============================================================
# Instagram renders this placeholder text inside a span with the
# same CSS classes as real comments. The scraper picks it up as
# a comment. Adding it to ui_skip prevents extraction entirely.

OLD_UI_SKIP = """            ui_skip = {'follow','like','reply','view more comments','load more comments','view all',
                       'replies','see translation','translate','original','view','hide','report',
                       'delete','1 like','2 likes','3 likes','view reply','view replies',
                       'hide replies','instagram lite','meta ai','meta verified',
                       'contact uploading and non-users','about','help','press','api','jobs','privacy','terms'}"""

NEW_UI_SKIP = """            ui_skip = {'follow','like','reply','view more comments','load more comments','view all',
                       'replies','see translation','translate','original','view','hide','report',
                       'delete','1 like','2 likes','3 likes','view reply','view replies',
                       'hide replies','instagram lite','meta ai','meta verified',
                       'contact uploading and non-users','about','help','press','api','jobs','privacy','terms',
                       'start the conversation.','start the conversation'}"""

if OLD_UI_SKIP in code:
    code = code.replace(OLD_UI_SKIP, NEW_UI_SKIP, 1)
    fixes_applied += 1
    print("✅ Fix applied: Added 'Start the conversation.' to ui_skip set")
else:
    print("⚠️  Could not find ui_skip target — may already be applied or code changed")

# Write back
if fixes_applied > 0:
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(code)
    print(f"\n🎉 Fix applied to {filename}")
else:
    print(f"\n⚠️  No fixes applied — check the file")