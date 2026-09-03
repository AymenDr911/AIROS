# AIROS V3.0 — Run & Verify Guide (Step by Step)

Follow these steps IN ORDER. Do not skip Step 2 — it is the one thing that
blocks everything else.

---

## Step 1 — Start the local server

Open Terminal and run:

```bash
cd "/Users/macbook/Documents/Careers folder/AIROS/V3.0"
python3 -m http.server 8000
```

Leave this terminal window open while you use the app.

> Right now a server is already running on port 8000, so this step may
> already be done. If the port is busy, that is fine — the server is up.

**Check:** open http://localhost:8000/app/index.html — you should see the
"Welcome to AIROS V3" landing page.

---

## Step 2 — Register the app URL in Auth0 (ONE-TIME, 2 minutes)

This is the step that is currently missing. Without it, clicking
"Continue with Auth0" always ends on Auth0's error page
("Oops!, something went wrong — Callback URL mismatch").

1. Go to https://manage.auth0.com and log in.
2. Left menu: **Applications → Applications**.
3. Click the AIROS app (Client ID `mIqi9un7HPVTP8Ej5xlmXkkosUXYArDJ`).
4. Open the **Settings** tab.
5. Scroll down to the **"Application URIs"** section (it sits just above
   "Advanced Settings").
6. In **Allowed Callback URLs**, paste exactly:

   ```
   http://localhost:8000/app/app.html, http://localhost:8000/auth0_dev_login.html
   ```

7. In **Allowed Logout URLs**, paste exactly the same two URLs.
8. Click **Save Changes** at the bottom of the page.

**Check:** after saving, no error is shown and the fields keep their values.

---

## Step 3 — Open the app and log in

1. In the browser, open (or hard-refresh with **Cmd+Shift+R**):

   http://localhost:8000/app/index.html

2. Click **Continue with Auth0**.
3. You should now see the Auth0 hosted login page
   (email + password form, and "Continue with Google" if enabled).
4. Log in — or click **Sign up** first if you have no account yet
   (then verify your email from the inbox/spam before logging in).

**Check — SUCCESS looks like this:** you land on the app page showing
**"Welcome, \<your name\>"**, an **email verified** badge, and the status
line **`sync_my_account() -> HTTP 200`**.
That last line is the live proof that the whole auth chain works:
Auth0 identity → Supabase account provisioning → per-account RLS.

---

## What each page is

| URL | Purpose |
|-----|---------|
| `http://localhost:8000/app/index.html` | Landing page with the login buttons |
| `http://localhost:8000/app/app.html` | The after-login page (welcome + sync status) |
| `http://localhost:8000/auth0_dev_login.html` | Dev tester — prints your ID token (for `scripts/verify_auth0.py`) |
| `http://localhost:8000/scripts/selfcheck.html` | Self-check: should print `6/6 PASS` |
| `http://localhost:8000/scripts/brand_preview.html` | Static preview of the branded login |

---

## If something fails

| Symptom | Cause | Fix |
|---------|-------|-----|
| Auth0 shows "Oops!, something went wrong" | Callback URLs not saved (Step 2) | Redo Step 2, make sure you clicked **Save Changes** |
| `Error: Can't find variable: client` | Browser cached the old JavaScript | Hard-refresh: **Cmd+Shift+R** |
| Page stuck on "You are signed out" | You opened `app.html` directly without logging in | Normal — go to `index.html` and click Continue with Auth0 |
| No verification email arrives | Check spam; wait a minute | Or resend via the tester page |
| No Google button | Google connection not enabled in Auth0 | Authentication → Social → Google (dashboard) |
| Reset accepts the old password | Password history not enabled | Authentication → Database → Username-Password-Authentication → Password Policy (CHG-007) |
| `sync_my_account -> HTTP 401/404` on the welcome page | Migration 0003 not applied / token role wrong | See `docs/AUTH0_SETUP.md` Steps 1 & 6 |

---

## Optional deep verification (after a successful login)

From the tester page (`auth0_dev_login.html`), copy the printed ID token,
then in a SECOND terminal (keep the server running in the first):

```bash
cd "/Users/macbook/Documents/Careers folder/AIROS/V3.0"
python3 scripts/verify_auth0.py --token <PASTE_TOKEN_HERE>
```

Expected last line: `VERIFY OK — Auth0 identity flow works and per-account RLS holds.`
