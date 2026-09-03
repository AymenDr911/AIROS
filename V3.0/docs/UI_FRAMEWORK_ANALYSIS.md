# AIROS V3 — UI Framework Deep Analysis (Option 2)

**Status: ANALYSIS COMPLETE — recommendation ready. No implementation performed.**
**DECISION 2 Sep 2026: user selected Option A — Next.js + Tailwind (over the Vite recommendation). Recorded as CHG-011; DEC-002 RESOLVED (Streamlit retired), DEC-010 ADOPTED (Tailwind + Next.js).**
Feeds: DEC-002 (UI stack) / DEC-010 (Tailwind) · register §5 · governed by CHG-003, DEC-011 and the Free-Plan constraint.
Register rule respected: any resulting change is recorded in the register **before** implementation.

## 1. Question
Which UI stack should carry V3's real dashboard (CV, Applications, Documents, ATS modules), and what happens to the interim vanilla shell and to Streamlit?

## 2. Ground truth (measured / verified 2 Sep 2026)
- Interim shell: **542 lines total** (`index.html` 70, `app.html` 26, `app.js` 251, `config.js` 19, `style.css` 176) — migration effort is bounded and small.
- Login UX lives in **Auth0 Universal Login** (hosted, Tier-A branded). The framework choice does **not** touch login/auth UX — only the post-login app shell.
- V3 Python layer today: `database/schema.py` (260 lines). The V2 engines (CV/ATS/AI) are not yet ported — they will arrive **behind FastAPI** (DEC-011), so the UI must be a clean API consumer.
- Free-tier facts (checked 2 Sep 2026):
  - **Vercel Hobby (€0):** 100 GB transfer/mo, 1M function invocations, 45-min builds, 100 deploys/day, static/SPA fully supported; non-commercial fair use (matches a personal project).
  - **Streamlit Community Cloud (€0):** public apps only (viewer allow-list exists), GitHub-push deploys, small single-instance containers, apps sleep when idle.
  - **Render free (€0):** 512 MB RAM, <1 vCPU, spins down when idle (cold start), 5 GB bandwidth, 500 build-min/mo — viable for dev-stage FastAPI, not an uptime guarantee.

## 3. Candidates
| # | Stack | One-liner |
|---|-------|-----------|
| A | Next.js + Tailwind (Vercel) | DEC-010's literal wording; full React framework + SSR |
| B | **Vite + React + Tailwind SPA (static)** | Lean React without SSR machinery |
| C | Extend vanilla JS/CSS shell (+Tailwind CDN) | No rewrite, no framework |
| D | Streamlit (Community Cloud) | V2's stack; fastest data-dashboards |

## 4. Findings
**Auth fit.** Auth0 spa-js works everywhere; React has the first-party `@auth0/auth0-react` SDK; vanilla already proven. Streamlit has no real session/OAuth story — community token hand-offs are fragile and would reintroduce the auth weakness V3 exists to remove (R02/ISS-001).

**Backend boundary (DEC-011).** All candidates can call FastAPI, but the pattern already proven end-to-end (ID token as bearer → `sync_my_account()` → per-account RLS, `verify_auth0.py`) is exactly an SPA + REST pattern — zero data-layer rework. Streamlit's rerun-everything model fights multi-step flows (upload → process → score) and its secrets-in-app habits caused ISS-004 in V2.

**Hosting (€0).** Static SPA deploys free anywhere (Vercel Hobby / Netlify / GitHub Pages). Next.js adds SSR we don't need: the dashboard is behind login, SEO-irrelevant — SSR functions would burn Vercel's function allowances for zero benefit. Render free hosts FastAPI with dev-acceptable cold starts; Supabase stays the EU data store.

**Effort.** 542-line rewrite ≈ **Slice 4a** (scaffold + login parity) + **Slice 4b** (welcome/placeholder-module parity); the palette/theme/EN-FR patterns port 1:1 (Tailwind `dark:` + CSS variables). Next.js adds routing/i18n machinery not needed yet. Vanilla "keep going" avoids the rewrite now but has no component model — every new module grows unmanaged DOM strings: the V2 maintenance trap.

**Maintainability/tests.** React + Vite: components, ecosystem (tables/forms/charts), `vitest` + Testing Library align with the CHG-004 quality gate. Vanilla has only the selfcheck harness; Streamlit has no UI test story.

## 5. Recommendation
**Adopt Tailwind CSS + Vite + React SPA; retire Streamlit from the V3 product path.**
- **DEC-010 AFFIRMED** — Tailwind adopted; the "Next.js/Vite" sub-choice resolves to **Vite** (B).
- **DEC-002 RESOLVED** — Streamlit is **not** carried into V3's product UI (kept only as a possible internal data-tool fallback, if ever needed).
- Hosting: static SPA on Vercel Hobby (fallback Netlify/GH Pages) + FastAPI on Render free + Supabase EU unchanged + Auth0 unchanged.
- Migration path: Slice 4a → 4b → real modules, each gated by the test plan (CHG-004).

## 6. Risks / notes
- Render free cold start after idle (~tens of seconds on first hit) — acceptable now; revisit under a hosting topic if it hurts UAT.
- Vercel Hobby = non-commercial fair use — matches today's stage; re-check if AIROS commercializes.
- A production URL later ⇒ new Auth0 Allowed Callback/Logout URLs + FastAPI CORS — one recorded CHG at deployment time.
