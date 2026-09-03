# AIROS V3 - Tier A: Brand the Auth0 login page (Universal Login)

**STATUS: IMPLEMENTED (docs + payloads + preview( - UAT pending: the dashboard steps below are applied by the tenant owner.**

Tier A = give the **hosted Auth0 login** the AIROS look, with **EUR 0** andonly no-code Auth0 tools: the **no-code theme editor** + **Custom Text** overrides. **A Custom Domain is NOT required for this tier.** (Page Templates / ACUL need one - deferred, see architecture note at the end.(

## What users will see after Tier A
- The Auth0 Universal Login matches AIROS brand: blue primary buttons, white cards, rounded inputs, clean light background.

- Login = the standard email+password form + a **Continue with Google** social button (**no Apple** - DEC-015; Apple connection simply stays disabled(.(
- Prompts in English by default; **French** via the standard OIDC `ui_locales` parameter (our app now exposes an EN/FR toggle(.
- New email/password users **must verify their email before their first login** (Requires email verification - R02 gate(.

---

## Step A1 - Gate: require email verification (1 min(

1. Dashboard -> **Authentication -> Database -> Username-Password-Authentication -> Settings**.
2. Tick **Requires email verification** -> Save. (It sits in the same Settings area as Password Policy - CHG-007.(

**Effect:** an unverified email/password account cannot sign in until the user clicks the verification link Auth0 emails(; Google accounts are exempt (their email arrives pre-verified by Google(.



## Step A2 - No-code theme (3 min(

1. Dashboard -> **Branding -> Universal Login -> Customization Options**.
2. Set the AIROS palette below using the **Styles** menu components (Colors(; optionally the **Borders** and **Widget** options per the second table. The editor preview pane shows every change live.3. **Save and Publish**; then **Try** to open the live preview in a new tab.



### AIROS palette (Colors(

| Component | Value |
|----------------------------|----------|
| Primary button | `#2564EB` |
| Primary button label | `#FFFFFF` |
| Secondary button border | `#C7D2E0` |
| Secondary button label | `#2564EB` |
| Links and focused components | `#2564EB` |
| Base focus color | `#1D4FC4` |
| Base hover color | `#1D4FC4` |
| Header | `#1A2332` |
| Body text | `#5B6B7F` |
| Input labels | `#1A2332` |
| Input placeholder text | `#93A1B4` |
| Input filled text | `#1A2332` |
| Input border | `#C7D2E0` |
| Input background | `#FFFFFF` |
| Icons | `#5B6B7F` |
| Error | `#DC2626` |
| Success | `#16A34A` |

### Borders / Widget

| Option | Value |
|---------|-------|
| Buttons style | rounded |
| Inputs style | rounded |
| Widget corner radius | medium (rounded( |
| Shadow | on |
| Logo position | Center |
| Logo URL | leave empty until you host the AIROS logo (see note below( |
| Logo height | ~40px |
| Header text alignment | Center |
| Social buttons layout | default |

> **Logo note:** Logo URL needs a hosted file (Auth0 recommends SVG(. We have no static host yet; leave empty for now (the dot+wordmark brand already appears in the app shell(, or point it at your future GitHub Pages/Vercel URL once the hosting topic is approved. Page background: leave empty; optionally add a subtle JPEG (at least 2000px wide( later. If you prefer to keep the no-code theme only and skip Custom Text, stop after A2 and Save/Publish - Tier A is functional already.



## Step A3 - Custom Text (optional: French tone(

1. Dashboard -> **Branding -> Universal Login -> Advanced Options -> Custom Text**.
2. Pick a **Prompt** (e.g. `login`( -> a **Screen** -> a **Language** -> override the keys the editor lists (e.g. `title`, `description`, `buttonText`(- VALUES reset-password screens document examples like `title` / `description` / `buttonText`; the editor shows each screen's keys(.
3. **Save Changes**. To preview a specific language, run the flow with `ui_locales` set to it (below(.

Example French: in the editor pick language French and set:- login.title: `Bienvenue sur AIROS`- login.buttonText: `Se connecter`- login.description: `Connectez-vous pour acceder a votre espace AIROS.`(adjust keys to what the editor shows for the login screen(.



## Step A4 - Try it end-to-end (+ UAT checklist(

```bash
cd '<repo root>'
python3 -m http.server 8000
# open http://localhost:8000/app/index.html
# click FR or EN, then Continue with Auth0 -> the hosted login renders in that language
```

- [ ] UL shows the AIROS palette (blue primary button, white card, rounded inputs(.
- [ ] Email+password login works; a NEW unverified user is routed to verify their email before first login.(
- [ ] Google button appears; **no Apple button** anywhere (DEC-015(.
- [ ] FR toggle renders French prompts (plus your Custom Text(.
- [ ] After login: welcome page (app shell( shows `sync_my_account()` OK (callback registered - CHG-008(.



## Architecture note - what we did NOT use, and why

| Option | Requirement | Status |
|--------|-------------|--------|
| Universal Login **Page Templates** (Liquid( | **Custom Domain** | **DEFERRED** (needs domain decision( |
| **Advanced Customizations for UL (ACUL(** | **Custom Domain** + CDN/SRI build pipeline | **DEFERRED** (out of Euro 0 scope for now( |
| No-code theme + Custom Text (Tier A( | none | **USED** |

Auth0 docs warn: UL internal CSS class names change on every build - customizations targeting them break(. **Tier A touches no Auth0 internals** (we only use disher the documented no-code editor(, so nothing to break.(

---

## Related
- `AUTH0_SETUP.md` Step 3bis (callback + app shell(.
- `AUTH_TEST_GUIDE.md` Test 7 (brand UAT(.
- Project Control Register: **Slice 3.6** + **CHG-009**.(