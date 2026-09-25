"""Quick diagnostic of the ATS threshold classification.

Problem reported by user:
- after ATS analysis reaches ~80, there is no "next step" path:
  no Continue button, no menu guiding the user to the application
  preparation / tracking workflow.
"""
import sys, os
sys.path.insert(0, os.path.abspath("."))

from ai.ats import (
    THRESHOLD_BANDS,
    classify_threshold,
    _build_verdict,
    _blockers_response,
)

print("=== THRESHOLD_BANDS ===")
for b in THRESHOLD_BANDS:
    lo = b["score_min"]
    hi = b.get("score_max", float("inf"))
    hi_s = "inf" if hi == float("inf") else hi
    print(f"  {lo:g}-{hi_s:g}  band={b['band']!r:10s}  proceed={b['proceed']}")

print("\n=== classify_threshold (no blockers) ===")
for s in [50, 69, 70, 75, 79, 80, 85, 89, 90, 95, 100]:
    v = classify_threshold(s, [])
    print(f"  score={s:3g}  band={v['band']!r:10s}  proceed={v['proceed']!r}  title={v['title'][:45]}")

print("\n=== _build_verdict (no blockers) ===")
for s in [50, 75, 85, 90]:
    v = _build_verdict(s, [])
    print(f"  score={s:3g}  band={v['band']!r:10s}  proceed={v['proceed']!r}")

print("\n=== with hard blockers (score high but blocked) ===")
v = classify_threshold(95, ["needs work visa", "requires local language"])
print(f"  score=95  band={v['band']!r}  proceed={v['proceed']}")

print("\n=== Answer rationale ===")
print("If classify_threshold(80..89, []) returns proceed=True")
print("and the UI renders a 'Continue' button whenever verdict.proceed is True,")
print("then the 'no next step at 80' bug is fixed at the engine level.")
print("If it returns proceed=False, the engine is the blocker and must be fixed.")
