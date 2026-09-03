# AIROS V3 — Auth0 <-> Supabase identity integration (Slice 3)

**STATUS: implemented and LIVE-VERIFIED (31 Aug 2026)** — the whole flow was
executed on the real project with a real Auth0 test user
(`oauth-test@airos.local`); see the final "Step 8 — Expected output".

This guide covers the *dashboard-side* steps to complete Slice 3. The
code side (database function + tests) is already implemented in
`database/migrations/0003_auth_integration.sql` (and 0004 ACL hardening).

**What we are building (DEC-014):** an Auth0 **ID token** (RS256) that
carries `role='authenticated'` is presented to Supabase's Data API.
Supabase verifies it (native "Third-party Auth" Auth0 integration) and
exposes its claims via `auth.jwt()`. A `SECURITY DEFINER` function
(`sync_my_account()`) then provisions the caller's own `accounts` row.

**Time:** ~10 minutes. **Cost:** €0 (Auth0 free tier: 25k MAU).

---

## Prereqs

- [ ] Supabase project created (Slice 2, done) - `hpjeafsticujbswgfqjs`
- [ ] Schema + RLS migrations applied (Slice 2, done)
- [ ] Migration `0003_auth_integration.sql` applied (this guide, Step 1)

---

## Step 1 — Apply the DB-side migrations (0003 + 0004) — required before Step 8

The DB side of Slice 3 is two migrations that must exist in the live
Supabase project before any ID-token check can succeed:

- `database/migrations/0003_auth_integration.sql` — creates
  `public.sync_my_account()` (SECURITY DEFINER).
- `database/migrations/0004_auth_acl_hardening.sql` — closes a security
  leak found on the live project: Supabase **default privileges** directly
  grant `EXECUTE` on new `public`-schema functions to `anon`/`service_role`,
  and a `REVOKE ... FROM PUBLIC` (0003) does **not** cancel direct role
  grants. 0004 explicitly revokes `anon`/`service_role` (and fixes the
  default privileges) so the functions are callable ONLY by `authenticated`.

Run them in order (each is idempotent and wrapped in a transaction):

1. Supabase dashboard -> your project -> **SQL Editor** -> **New query**.
2. Paste the **full** content of `database/migrations/0003_auth_integration.sql`.
   Run it.
3. Paste the **full** content of `database/migrations/0004_auth_acl_hardening.sql`.
   Run it.
4. Confirm both were applied — `scripts/verify_supabase.py` must report:

```bash
cd ..   # repo root
python3 scripts/verify_supabase.py
# look for the new line:
#   sync_my_account : APPLIED (function exists; anon probe rejected with HTTP 403)
# and exit code 0 (VERIFY OK).
```

> If it reports `APPLIED BUT ANON CAN EXECUTE`, migration 0004 was not
> applied (or was altered). Re-check that the whole file was pasted.

## Step 2 — Create an Auth0 tenant

1. Go to https://auth0.com and sign up (free, no credit card).
2. Create a **tenant** with **region = Europe** (GDPR / DEC-009), e.g.
   `airos-v3` in `EU` (Frankfurt/Ireland depending on options shown).
3. Plan: **Free** (basic plan) is fine.

## Step 3 — Create the application

1. Auth0 dashboard -> **Applications -> Create Application**.
2. Name: `airos-v3`; type: **Single Page Web Application**.
3. Note the **Domain** and **Client ID** (public values; keep the
   **Client Secret** private, you won't need it for the SPA flow).

## Step 3bis — Register the app shell URLs (one-time dashboards step)

So the browser can return to the app after login (and after sign-out):

1. Auth0 dashboard -> **Applications -> your app -> Settings** ->
   **Allowed Callback URLs**: add `http://localhost:8000/app/app.html`
   (keep the tester's `http://localhost:8000/auth0_dev_login.html` if you
   still use the tester page.)
2. **Allowed Logout URLs**: add `http://localhost:8000/app/app.html`.

Then serve the app shell from the repo root (not from `scripts/`):

```bash
```bash
python3 -m http.server 8000
# open http://localhost:8000/app/index.html  (landing page)
# sign in -> Auth0 -> callback on http://localhost:8000/app/app.html
```

The app shell (`app/`) is a vanilla JS/CSS interim UI (DEC-002/DEC-010 still
pending): login via Auth0, calls `sync_my_account()` with the ID token as
bearer, shows welcome/dashboard placeholder, theme light/dark, sign-out.
It does NOT lock the future UI framework decision.
Branding ofthe hosted Auth0 login page (logo, palette, custom text,: see `docs/AUTH0_BRANDING.md` (Tier A(.

## Step 4 — Signing algorithm (must be RS256)

- Applications -> your app -> **Settings** -> scroll to "JSONWebToken
  (JWT) Signature Algorithm". It must be **RS256** (the default).
- Supabase does **NOT** support HS256 or PS256 (DEC-014 limitation).

## Step 5 — Connections

- **Database (email/password):** enabled by default via
  `Username-Password-Authentication`. This is our primary login.
- **Social (optional):** Authentication -> Social -> enable Google/GitHub
  if you want them (free tier supports unlimited social connections).

## Step 6 — Add the `role` claim (required)

Supabase assigns the Postgres role from the JWT `role` claim. Auth0
tokens do NOT include it by default and access tokens STRIP custom
claims - so we set it on the **ID token** via an Action.

1. Auth0 dashboard -> **Actions -> Library** -> **Build Custom**.
   Name: `set-authenticated-role`; trigger: **Login / Post Login**.
2. Use this code:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  api.idToken.setCustomClaim('role', 'authenticated');
};
```

3. **Deploy** the Action and **Add to Flow** (drag it into the Login flow).

> `scripts/verify_auth0.py` refuses ID tokens that carry a missing or
> wrong `role` claim (fail-fast), so if you see *"JWT `role` is not
> 'authenticated'"* the Action above was not deployed/attached yet.

## Step 7 — Add the Third-Party Auth integration in Supabase

1. Supabase dashboard -> your project -> **Authentication -> Third-Party
   Auth**.
2. **Add integration** -> **Auth0**.
3. Enter your Auth0 **Tenant ID** (the `<tenant>` part of
   `https://<tenant>.eu.auth0.com`), and the **region** (`eu`) if asked.
   (CLI equivalent: `[auth.third_party.auth0] enabled = true
   tenant = "<id>" tenant_region = "<region>"`.)

## Step 8 — Capture an ID token for the live check

Open `scripts/auth0_dev_login.html` in a browser served over HTTP:

```bash
cd scripts && python3 -m http.server 8000
# open http://localhost:8000/auth0_dev_login.html
```

1. Fill in your **Domain** and **Client ID**, click login, complete the
   Auth0 flow (create/reuse a test user).
2. The page prints the raw **ID token**. Copy it.
3. Run the verification (NEVER paste the token into chat):

```bash
cd .. && python3 scripts/verify_auth0.py --token <ID_TOKEN>
```

Expected output (verified live on 31 Aug 2026) ends with:
`VERIFY OK - Auth0 identity flow works and per-account RLS holds.`

> Production note: the dev test user had `email_verified=false`, and
> `sync_my_account()` stores exactly that (`verified=false`). Before
> production cutover (CHG-005), real users must complete email
> verification (Auth0 email verification requirement, R02), and we keep
> the claim-based handling we verified here.

## Step 9 — Real-user flow validation checklist (UAT)

The auth layer is wired; now prove the real UX journeys. Serve the tester page:

> Short version: a **6-test checklist** you can run yourself in ~30 minutes is in
> `docs/AUTH_TEST_GUIDE.md` (email verify, wrong password, forgot password,
> Google, no-Apple, DB account). The full details are below.

```bash
cd scripts && python3 -m http.server 8000
# open http://localhost:8000/auth0_dev_login.html
```

Readiness map (current tenant):
- ✅ **Signup, Login, Forgot-password** — available now (tester page has modes;
  the reset endpoint is verified working: `HTTP 200 — "We've just sent you an email…"`).
- ✅ **Email delivery (verification / reset)** — confirmed live by a real user on
  31 Aug 2026 (verified their email and reset their password via free-plan Auth0
  email provider). If messages stop arriving, configure a free SMTP sender
  (note below).
- 🟡 **Google sign-in** — needs one dashboard step (enable the Google connection).
- ❌ **Sign in with Apple** — rejected (DEC-015, 31 Aug 2026): paid Apple
  Developer Program (~$99/yr) conflicts with the Free-Plan constraint.

### 1 — Correct sign-up
Mode **Sign up** → create an account with your real email. Expected: redirected
back → ID token printed (`role=authenticated`). Then:
`python3 scripts/verify_auth0.py --token <ID_TOKEN>` → `sync_my_account()` 200 →
the `accounts` row exists for that real email.
Note: until you enable Auth0 **email verification**,
`email_verified=false` is normal. For production (R02) enable
"Requires email verification" on the database connection and confirm delivery.

### 2 — Error handling
Mode **Log in** with the correct email but a **wrong password**. Expected: Auth0
shows a clear inline error ("Wrong email or password"), no crash, no session.
Also try: logging in before verifying the email (allowed until you require
verification).

### 3 — Forgot password
Use "Forgot password" on the login page **or** the tester's
"Send password-reset email". Expected: `HTTP 200 — "We've just sent you an
email…"`. **Check the inbox AND spam** (look for "reset your password" from Auth0),
follow the link, set a new password, then log in with it.

> **Known limitation (found in real-user UAT, 31 Aug 2026):** Auth0 currently
> **accepts your previous password** during a reset — the reset then "succeeds"
> without actually changing anything. Fix (one dashboard step, CHG-007):
> Auth0 → **Authentication → Database → Username-Password-Authentication →
> Settings → Password Policy** → enable **Password history** (e.g. remember the
> last 5) and set the **strength policy** to *Good* (and the dictionary on) → Save.
> Retest: resetting with the *same* old password must now be rejected.

### 4 — Google sign-in (enable once)
1. Auth0 → **Authentication → Social → Google** → **Create connection**.
2. Google Cloud → **APIs & Services → OAuth consent screen** (external, free) →
   **Credentials → Create OAuth client ID** → type **Web application** → add the
   Auth0 redirect URI **`https://dev-s6kc2wm7ppaoj8ni.eu.auth0.com/login/callback`**.
3. Paste the Google **Client ID / Client Secret** into the Auth0 Google connection
   and enable it for your app.
4. Expected: the **Google** button appears on login; sign-in returns an ID token
   with `sub=google-oauth2|…`, `email_verified=true`, `role=authenticated` (the
   Action runs for every connection — no extra step).

### 5 — Sign in with Apple / iCloud (removed — DEC-015, 31 Aug 2026)
Sign-in with Apple is **rejected for V3**: it requires a **paid Apple Developer
Program** membership (~$99/yr), which conflicts with the Free-Plan constraint.
No Apple button will appear on the login page.

### Email provider note (only if reset/verification emails don't arrive)
Free options: **Brevo** (300/day), **Mailjet** (200/day), **SMTP2GO** (200/mo),
or a personal Gmail/Outlook relay. Configure at Auth0 → **Settings → Email →
Provider**. Keeps the €0 constraint.

## Security notes

- The **Client Secret** and **service_role** key must never leave their
  dashboards. Only the public values (URL, publishable key, Client ID)
  go into the local `.env`.
- `accounts` rows can ONLY be created through `sync_my_account()`, which
  trusts only the server-verified `sub` claim - never client input.
- RS256-only keeps signature verification on Supabase's side; no JWT
  library or secret is needed in our code (Free Plan friendly).