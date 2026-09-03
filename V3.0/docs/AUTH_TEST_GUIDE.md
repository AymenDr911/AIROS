# AIROS V3 — Simple Auth Test Guide

A short, step-by-step checklist to test the AIROS login flows yourself.
Each test takes about **5 minutes**. Mark ✅/❌ in the table at the end.

> 8 tests: 1-6 real Auth flows, 7 branded login (Tier A(,and 8 the
> self-check harness (no browser automation needed — just open the page.(

---

## Before you start (one-time)

1. From the repo root, start a local server:

   ```bash
   python3 -m http.server 8000
   ```

2. Open **http://localhost:8000/app/index.html** in the browser — this
   is the real app shell (login → `sync_my_account()` → welcome page).
   The legacy tester page (`scripts/auth0_dev_login.html`) stays available
   for power users/token capture (serve it separately from `scripts/`).

3. One-time dashboard step: register the app callback URLs in Auth0 ->
   **Applications -> your app -> Settings** → Allowed Callback URLs + Allowed
   Logout URLs = `http://localhost:8000/app/app.html` (see
   `AUTH0_SETUP.md` Step 3bis).

4. Make sure these two Auth0 settings are already done (dashboard):

   - ✅ **Password history + quality policy** on the database connection
     (`Authentication → Database → Username-Password-Authentication →
     Settings → Password Policy`) — this is the fix for the "reset accepted my
     old password" issue (CHG-007).
   - ✅ **Google connection enabled** (`Authentication → Social → Google`) —
     needed for Test 4. (If not done yet, see `AUTH0_SETUP.md` Step 9, item 4.)

---

## Test 1 — Sign up + verify your email

**What to do:**
1. On the tester page choose **Sign up** → click **Sign up with Auth0**.
2. Create an account with **your real email** and a password.
3. Check your **inbox AND spam** for the Auth0 verification email.
4. Click the verify link in that email.

**What you should see:** ✅ You can then log in; the printed ID token contains
`"email_verified": true` (and `"role": "authenticated"`).

---

## Test 2 — Log in with a wrong password

**What to do:**
1. Choose **Log in**, enter your correct email but a **wrong password**.

**What you should see:** ✅ A clear inline error ("Wrong email or password"),
no token, no session, no crash.

---

## Test 3 — Forgot password (does it really change the password?)

> **Applies to email + password accounts only.** If you sign in with **Google**,
> there is **no AIROS/Auth0 password to reset** — your password is your Google
> password (change it at `myaccount.google.com` → Security). Requesting a reset
> for a Google-only account sends **no Auth0 reset email** (by design), and the
> "Keep track of your Google Account data" email you may see comes from
> **Google** after each Sign-in-with-Google — it is normal and needs no action.

**What to do:**
1. Click **Forgot password** on the Auth0 page (or use the tester's
   **Send password-reset email**).
2. Check **inbox AND spam** for the "reset your password" email, open the link.
3. Set a **NEW password** (different from your old one) and submit.
4. Log in with the new password → must work.
5. **The important check:** request another reset and try to set your
   **OLD password** again.

**What you should see:**
- ✅ Step 4 works (new password accepted).
- ✅ Step 5 is **REJECTED** ("Cannot reuse old password") — this proves
  CHG-007 (password history) is active. If it still accepts the old password,
  the dashboard setting from *Before you start* is not applied yet.

---

## Test 4 — Google sign-in

**What to do:**
1. On the login page, click **Continue with Google**.
2. Choose your Google account and come back to the app.

**What you should see:** ✅ The printed ID token shows:
- `"sub": "google-oauth2|..."` (Google identity)
- `"email_verified": true` (Google already verified the email)
- `"role": "authenticated"`

---

## Test 5 — No Apple button

**What to do:**
1. Look at the login page and the Google sign-in page.

**What you should see:** ✅ **No "Sign in with Apple" button anywhere** — email +
password and Google are the only options (Apple rejected, DEC-015).

---

## Test 6 — Account really created in the database (optional, advanced)

**What to do:**
1. From the tester page, copy the printed ID token.
2. Run:

   ```bash
   python3 scripts/verify_auth0.py --token <ID_TOKEN>
   ```

**What you should see:** ✅ Output ends with
`VERIFY OK - Auth0 identity flow works and per-account RLS holds`.

---

## Quick result table

| # | Test | Pass criteria | Result |
|---|------|---------------|--------|
| 1 | Sign up + email verify | Verification link works; `email_verified=true` | ☐ |
| 2 | Wrong password | Clear inline error, no session | ☐ |
| 3 | Forgot password | New password works; **old password rejected** | ☐ |
| 4 | Google sign-in | `sub=google-oauth2\|…`, `email_verified=true` | ☐ |
| 5 | No Apple button | Only Email/password + Google shown | ☐ |
| 6 | DB account created | `VERIFY OK` (optional) | ☐ |
| 7 | Branded login | AIROS palette; only Email/Password + Google; FR via ui_locales | ☐ |
| 8 | Self-check harness | `6/6 PASS` in `scripts/selfcheck.html` | ☐ |

---

## Test 7 - Branded login page

**What to do:**
1. In the Auth0 dashboard, apply Tier A out of `docs/AUTH0_BRANDING.md`:
   the no-code theme (Customization Options - AIROS palette(, then( optional( Custom Text, and **Requires email verification** (Step A1(.
2. Open the app landing `http://localhost:8000/app/index.html`, pick EN or FR,
   click **Continue with Auth0**.

**What you should see:** ✅ The hosted login shows the AIROS palette, email+password form +
**Continue with Google** (no Apple - DEC-015(; a NEW unverified account is routed to
verify its email before first login; FR renders French prompts. (Preview the mock first:
`scripts/brand_preview.html`.(

## Test 8 — Self-check harness (button wiring proof(

**What to do:**
1. Open **http://localhost:8000/scripts/selfcheck.html** in the browser.

**What you should see:** ✅ Its probe lines render **6/6 PASS** — it loads the
REAL `app/js/app.js` bundle and fires every app-shell button/login( signup( theme(
EN( FR( autonomously (. If any line says FAIL, snapshot it and share (its the
same harness we run headless (CHG-010(.(

---

## If something fails

| Symptom | Likely reason | Fix |
|---------|---------------|-----|
| Emails never arrive | Check **spam** first; Auth0 email provider misconfigured | See `AUTH0_SETUP.md` → "Email provider note" |
| No Google button | Google connection not created/enabled yet | `AUTH0_SETUP.md` Step 9, item 4 |
| Reset still accepts old password | Password history not enabled yet | `Authentication → Database → … → Password Policy` (CHG-007) |
| Reset never arrives (Google account) | Social (Google) logins have **no Auth0 password** — reset only applies to email+password accounts | Change the password in your **Google Account** (`myaccount.google.com` → Security); Google's "Sign in with Google" email is normal, no action needed |
| Apple button present | Old cached page | Hard-refresh (Cmd+Shift+R); Apple is removed in DEC-015 |