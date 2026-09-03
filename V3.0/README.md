# AIROS V3.0

V3.0 is the new major version of AIROS.

V2.0 remains frozen and is not modified by V3 development (rollback baseline).

## Architecture

- app            — UX/UI layer (pending DEC-010 decision)
- services       — application services (planned)
- domain         — domain/models (planned)
- database       — persistence layer (planned: Supabase PostgreSQL, DEC-009)
- storage        — document storage (pending DEC-012)
- ai             — AI gateway / provider abstraction (DEC-005)
- **migration**  — V2 snapshot extraction, transform & reconcile (done - slice 1)
- tests          — migration + validation tests (done - slice 1)
- docs           — project control register, test/migration validation plan
- scripts
- .streamlit

## Slice 1 — Migration-proof foundation (implemented)

Reads the frozen V2 snapshot (`V2.0/data/users_db.json`), applies the register's
business-safe migration rules (discard demo/user + plaintext password + inline
base64 CV; reclassify skills; preserve profile/applications/lifecycle), and
produces a reconciliation report per the Migration Specification §4.

```bash
# dry-run against the real frozen V2 snapshot (no DB writes)
python3 -m migration.runner --out /tmp/migration_report.json

# run the test suite (30 tests: migration slices + schema/RLS invariants)
python3 -m pytest -q
```

Security/GDPR guarantees verified (ISS-001/002/006, DEC-004/007):
- No V2 plaintext password is ever carried into V3.
- Demo/test accounts are discarded.
- Original CV content (inline base64) is not migrated; only a document stub
  (metadata) is emitted for later materialization into a protected store.

## Slice 2 — V3 Postgres schema + per-account RLS (implemented)

Defines the V3 PostgreSQL schema and its per-account Row Level Security
(DEC-009/DEC-013) as ordered, idempotent migrations:

- `database/migrations/0001_schema.sql` — `accounts`, `profiles`,
  `applications`, `documents` (JSONB flexible payloads; cascade ownership;
  NO password column ISS-001; document content never stored ISS-006).
- `database/migrations/0002_rls.sql` — `current_account_id()` resolver
  (Auth0 `sub` claim → account) + SELECT/INSERT/UPDATE/DELETE policies
  scoped per account on every user-data table (ISS-003).
- `database/schema.py` — pure, DB-free invariant validator (testable on any
  machine) powering `tests/test_schema.py`.

```bash
# validate the schema/RLS security invariants (no database required)
python3 -c "from database.schema import validate_schema; rs=validate_schema(); print(sum(r.ok for r in rs), '/', len(rs), 'checks pass')"

# live smoke check against the real Supabase project (needs .env config)
python3 scripts/verify_supabase.py
```

The migrations have been applied to the live Supabase project (EU region,
free tier) as part of the CHG-005 provisioning gate. Live verification
confirmed: all four tables present, anonymous reads return empty, and an
anonymous INSERT is rejected by RLS (`42501 — new row violates row-level
security policy`), i.e. per-account isolation (ISS-003) is enforced at the
data layer.

## Slice 3 — Auth0 identity integration (DEC-003 / DEC-014) — DONE & LIVE-VERIFIED

End-to-end Auth0 ↔ Supabase identity flow, fully verified against the real
project with a real Auth0 test user:

- **Auth0 (EU)**: tenant `dev-s6kc2wm7ppaoj8ni.eu.auth0.com`, Single-Page App
  (RS256), Local callback `http://localhost:8000/auth0_dev_login.html`,
  `set-authenticated-role` Login/Post-Login Action (puts `role=authenticated`
  on the ID token).
- **Supabase**: migrations `0003` (sync_my_account SECURITY DEFINER) + `0004`
  (anon/service_role ACL hardening, CHG-006) applied; **Third-party Auth →
  Auth0** integration enabled.
- **Verified** (`scripts/verify_auth0.py` with a real ID token):
  `sync_my_account()` → HTTP 200, self-provisioned `accounts` row
  `auth0|6a950f03e0fcfc5b3d3f3197`; authenticated SELECT = own row only;
  anonymous = `[]` → **`VERIFY OK` (exit 0)**. `verify_supabase.py` → VERIFY OK.

Local suite: `pytest: 53 passed`; `validate_schema()`: 36/36 checks green.

Real-user flow UAT is staged in `docs/AUTH0_SETUP.md` Step 9, with an
**auth-flow tester page** (`scripts/auth0_dev_login.html`): Log in / Sign up /
Forgot-password modes against the live tenant (password-reset endpoint verified
live: `HTTP 200`). Google sign-in is a readiness item in that checklist.
A quick self-run checklist (8 tests, ~30 min total) is in
`docs/AUTH_TEST_GUIDE.md`.

Interim app shell (`app/`, 1 Sep 2026): vanilla JS/CSS login + welcome
page — login via Auth0, auto `sync_my_account()`, light/dark theme, sign-out.
Serve from repo root → `http://localhost:8000/app/index.html`; register the
callback `http://localhost:8000/app/app.html` in Auth0 first (`AUTH0_SETUP.md`
Step 3bis). Does NOT lock the future UI framework decision (DEC-002/010;).
Register entry: Slice 3.5.
Runtime probe (headless-Chrome verified,: `scripts/selfcheck.html` — loads the
real app bundle and clicks every button (`6/6 PASS`, 1 Sep 2026; CHG-010(.
Tier A (branding(: the hosted Auth0 login is themed via the no-code editor + text overrides
(free, no custom domain; see `docs/AUTH0_BRANDING.md`; preview `scripts/brand_preview.html`(.

```bash
# quick runtime checks (open in your browser,no terminal output needed(:
#   1. http://localhost:8000/scripts/selfcheck.html       -> expect 6/6 PASS (button wiring(
#   2. http://localhost:8000/scripts/brand_preview.html   -> branded login mock (Tier A(
#   3. http://localhost:8000/app/index.html                 -> the app landing (login flow(
```

```bash
# replay the live check (needs a fresh ID token):
cd scripts && python3 -m http.server 8000   # serve auth0_dev_login.html (tester)
# open http://localhost:8000/auth0_dev_login.html -> pick mode -> login/signup
python3 scripts/verify_auth0.py --token <ID_TOKEN>
```

