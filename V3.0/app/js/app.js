/* AIROS V3 - app shell logic (interim UI, vanilla JS) */
/* Login via Auth0 -> sync account via Supabase -> show welcome/dashboard. */
/* HARDENED (CHG-011): NO top-level statement can throw - even if */
/*  config.js is blocked or localStorage is unavailable (Safari private mode(. */
/*  Wiring of the landing buttons happens INSIDE app.js (single source(; */
/*  if this module EVER fails,the index page has a fallback that makes every */
/*  button show the error instead of staying silent-dead. */
const CONFIG = window.AIROS_CONFIG || {};

/* Locked storage: never throws; falls back to memory. */
const _store = (function () {
  const mem = {};
  try {
    localStorage.setItem('__airos_probe_', '1');
    localStorage.removeItem('__airos_probe_');
    return { ok: true, mem: mem };
  } catch (e) {
    return { ok: false, mem: mem };
  }
})();

function storageGet(key) {
  if (_store.ok) {
    try { const v = localStorage.getItem(key); if (v != null) return v; } catch (e) { /* fall through */ }
  }
  return _store.mem[key] != null ? _store.mem[key] : null;
}

function storageSet(key, value) {
  _store.mem[key] = value;
  if (_store.ok) {
    try { localStorage.setItem(key, value); } catch (e) { /* memory only */ }
  }
}

const savedLocale = storageGet('airos-locale');
if (savedLocale != null) CONFIG.locale = savedLocale;

function reportError(msg) {
  const e = document.getElementById('err');
  if (e) { e.textContent = msg; e.classList.remove('hidden'); }
  else { try { alert(msg); } catch (x) { /* noop */ } }
}

function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
    const map = { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' };
    return map[ch] || ch;
  });
}

/* Auth0 SPA client handle - single instance, created lazily by auth0(). */
let client = null;

async function auth0() {
  if (client) return client;
  try {
    const mod = await import('https://cdn.jsdelivr.net/npm/@auth0/auth0-spa-js@2/+esm');
    client = await mod.createAuth0Client({
      domain: CONFIG.domain,
      clientId: CONFIG.clientId,
      authorizationParams: { redirect_uri: CONFIG.redirect }
    });
    return client;
  } catch (err) {
    throw new Error('Could not load the Auth0 library from CDN. Check your internet connection and try again. ' + ((err && err.message) || err));
  }
}

async function login(mode, locale) {
  const c = await auth0();
  const params = { screen_hint: mode == null ? 'login' : mode };
  const loc = locale != null ? locale : CONFIG.locale;
  if (loc) params.ui_locales = loc;
	await c.loginWithRedirect({
    redirect_uri: CONFIG.redirect,
    authorizationParams: params
  });
}

function setLocale(locale) {
  CONFIG.locale = locale;
  storageSet('airos-locale', locale);
}

async function logout() {
  const c = await auth0();
  try {
    await c.logout({ returnTo: CONFIG.redirect });
  } catch (err) {
    await c.logout();
  }
}

async function getSession() {
  const c = await auth0();
  const q = new URLSearchParams(location.search);
  if (q.has('code') && q.has('state')) {
    await c.handleRedirectCallback();
    history.replaceState(null, '', location.pathname);
  }
  return await c.isAuthenticated();
}

async function syncAccount(c) {
  const claims = await c.getIdTokenClaims();
	const resp = await fetch(CONFIG.supabaseUrl + '/rest/v1/rpc/sync_my_account', {
    method: 'POST',
    headers: {
      apikey: CONFIG.supabaseKey,
      Authorization: 'Bearer ' + claims.__raw,
      'Content-Type': 'application/json'
    },
    body: '{}'
  });
  return { status: resp.status, text: await resp.text() };
}

function badgeFor(verified) {
  if (verified === true) return '<span class="badge ok">email verified</span>';
		if (verified === false) return '<span class="badge warn">verify your email</span>';
		return '<span class="badge muted">verification unknown</span>';
}

function providerLabel(sub) {
  if (sub == null) return 'unknown';
		if (sub.indexOf('google-oauth2') === 0) return 'Google';
		if (sub.indexOf('auth0|') === 0) return 'email + password';
		return 'Auth0';
}

function moduleCard(title, desc) {
  return `<div class="module"><h3>${esc(title)}</h3><p>${esc(desc)}</p></div>`;
}

function renderSignedOut(view) {
  view.innerHTML = `
    <div class="hero">
      <h1>You are signed out</h1>
      <p>Sign in with Auth0 to sync your account and enter AIROS.</p>
      <button id="go" class="btn primary">Continue with Auth0</button>
    </div>`;
	document.getElementById('go').addEventListener('click', function () { login(); });
}

function renderWelcome(view, claims) {
  const name = claims.name || claims.nickname || claims.email || 'there';
	const email = claims.email || claims.sub || '';
	const initials = String(name).slice(0,1).toUpperCase();
	view.innerHTML = `
    <h2>Welcome, ${esc(name)}</h2>
    <div class="user-row">
      <div class="avatar">${esc(initials)}</div>
      <div class="user-meta">
        <span class="name">${esc(email)}</span>
        <span>${badgeFor(claims.email_verified)} | provider ${esc(providerLabel(claims.sub))}</span>
      </div>
    </div>
    <p class="muted mt">Account provisioning + connection status (live):</p>
    <pre id="status" class="status">syncing...</pre>
    <h2 class="mt">Coming next</h2>
    <div class="modules">
      ${moduleCard('CV', 'Upload, edit and version your CV.')}
      ${moduleCard('Applications', 'Track applications and their lifecycle.')}
      ${moduleCard('Documents', 'Cover letters, PDFs and generated outputs.')}
      ${moduleCard('ATS', 'Deterministic scoring against job-fit criteria.')}
    </div>`;
}

async function initApp() {
  applySavedTheme();
	const view = document.getElementById('view');
	if (view == null) return;
	try {
    const authed = await getSession();
    if (!authed) { renderSignedOut(view); return; }
    const c = await auth0();
    const claims = await c.getIdTokenClaims();
    renderWelcome(view, claims);
    const status = document.getElementById('status');
    try {
      const r = await syncAccount(c);
      status.textContent = 'sync_my_account() -> HTTP ' + r.status + (r.text ? ' ' + r.text : '');
      status.classList.add(r.status === 200 ? 'ok' : 'err');
    } catch (err) {
      status.textContent = 'sync failed: ' + err.message;
      status.classList.add('err');
    }
    const so = document.getElementById('signout');
    if (so != null) so.classList.remove('hidden');
  } catch (err) {
    view.innerHTML = '<p>Error: ' + esc(err.message) + '</p>';
  }
}

function toggleTheme() {
  const root = document.documentElement;
	const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
	root.setAttribute('data-theme', next);
	storageSet('airos-theme', next);
}

function applySavedTheme() {
  const saved = storageGet('airos-theme');
	if (saved != null) document.documentElement.setAttribute('data-theme', saved);
}

window.AIROS = {
  login: login,
  logout: logout,
  setLocale: setLocale,
  initApp: initApp,
  toggleTheme: toggleTheme
};

/* ---- Landing/app button wiring (single source of truth; runs once( ---- */
function wireButtons() {
  if (window.__airosWired) return;
  window.__airosWired = true;

  function on(id, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', function (ev) {
      try { fn(ev); } catch (e) { reportError((e && e.message) || 'Unexpected error'); }
    });
  }

  function onLang(btn) {
    btn.addEventListener('click', function () {
      try { setLocale(btn.getAttribute('data-locale')); } catch (e) { reportError((e && e.message) || 'Unexpected error'); }
    });
  }

  on('login', function () { return login(); });
  on('signup', function () { return login('signup'); });
  on('theme', function () { return toggleTheme(); });
  on('signout', function () { return logout(); });
  if (document.querySelectorAll) document.querySelectorAll('[data-locale]').forEach(onLang);
}

function boot() {
  wireButtons();
  if (document.getElementById('view') != null) {
    initApp();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}