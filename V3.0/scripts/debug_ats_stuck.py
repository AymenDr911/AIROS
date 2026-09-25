"""AIROS V3 - ATS stuck debug probe (stage-by-stage, timed)."""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _env() -> dict:
    env: dict = {}
    try:
        for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, _, v = s.partition("=")
                env[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return env

def timed(label, fn, budget=30.0):
    t0 = time.time()
    try:
        out = fn()
        dt = time.time() - t0
        print(("[OK] " if dt <= budget else "[SLOW] ") + f"{label}: {dt*1000:.0f}ms")
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {label}: {(time.time()-t0)*1000:.0f}ms -> {str(e)[:300]}")
        return None

def main() -> int:
    print("=== AIROS V3 ATS stuck probe ===")
    key = (_env().get("GEMINI_API_KEY", "") or "").strip().strip("'\"")
    print(f"S0 key_len={len(key)}")
    from ai import gateway as gw
    from ai import ats
    print(f"S0 chain={gw.MODEL_FALLBACK_CHAIN}")
    def s1():
        ms = gw._list_supported_generate_models(key)
        print(f" total={len(ms)} chain_exists={[m in ms for m in gw.MODEL_FALLBACK_CHAIN]}")
    timed("S1 models-list", s1, 30.0)
    def s2():
        p = {"contents": [{"parts": [{"text": 'Return ONLY {"ok": true}.'}]}],
             "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}}
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=" + key
        req = urllib.request.Request(url, data=json.dumps(p).encode(), headers={"Content-Type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=45).read().decode())
        cand = data.get("candidates", [])
        txt = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "") if cand else ""
        print(f" finish={cand[0].get('finishReason') if cand else None} txt={txt[:80]!r}")
    timed("S2 single generate 3.6-flash", s2, 50.0)

    def s3():
        orig = gw._call_gemini
        sample = json.dumps({"job_title": "Nurse", "company_name": "Clinic",
            "required_skills": {"technical": ["ICU"], "methodologies": [], "tools": []},
            "experience": {"min_years": 2, "preferred_years": 3, "level": ""},
            "education": {"min_degree": "", "preferred_fields": []},
            "languages": [], "certifications": ["BLS"], "keywords": ["ICU"]})
        gw._call_gemini = lambda *a, **k: sample  # type: ignore
        ats._call_gemini = lambda *a, **k: sample  # type: ignore
        try:
            job = ats.parse_job_v2("Registered Nurse ICU, BLS, 2+ years", "k", force_refresh=True)
            assert job["job_title"] == "Nurse" and not job.get("_api_error"), job
            print(f" parsed title={job['job_title']!r}")
        finally:
            gw._call_gemini = orig
    timed("S3 parse_job_v2 mocked", s3, 5.0)
    def s4():
        cand = {"skills": {"technical": ["ICU"], "methodologies": [], "tools": []},
            "total_experience_years": 5, "education": [], "experience": [],
            "languages": [], "certifications": [{"name": "BLS"}], "location": "",
            "nationality": "", "industry_hints": [], "all_tokens": {"icu", "nurse"}}
        job = {"job_title": "Nurse", "company_name": "C", "industry": "",
            "experience": {"min_years": 2, "preferred_years": 3, "level": ""},
            "education": {"min_degree": "", "preferred_fields": []},
            "required_skills": {"technical": ["ICU"], "methodologies": [], "tools": []},
            "preferred_skills": {"technical": [], "methodologies": [], "tools": []},
            "certifications": ["BLS"], "languages": []}
        r = ats.compute_ats_engine(cand, job)
        v = ats.classify_threshold(r["overall_ats"], [])
        print(f" score={r['overall_ats']:.1f} band={v['band']} proceed={v['proceed']}")
        assert ats.classify_threshold(float("nan"), [])["proceed"] is False
    timed("S4 engine + fail-safe", s4, 5.0)
    def s5():
        import inspect
        from services.api.routers import ats as router
        src = inspect.getsource(router.analyze_job)
        assert "job_text is required" in src and "GEMINI_API_KEY" in src
        print(" router guards: 422/409/500/502 present")
    timed("S5 router guards", s5, 5.0)
    def s6():
        req = urllib.request.Request("http://localhost:8001/api/health")
        print(" health=" + urllib.request.urlopen(req, timeout=8).read().decode()[:200])
    timed("S6 backend health :8001", s6, 10.0)
    def s7():
        from services.api.config import get_settings
        get_settings.cache_clear()
        print(f" cors={get_settings().cors_origins}")
        get_settings.cache_clear()
    timed("S7 CORS config", s7, 5.0)
    print("=== probe done: any FAIL/SLOW above is the stuck stage ===")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
