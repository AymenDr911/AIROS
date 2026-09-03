"use client";
/* AIROS V3 - auth + theme + locale (Slice 4a port of app/js/app.js).
   Same Auth0 SPA flow (PKCE), same sync_my_account() call, same storage keys. */
import { createAuth0Client, type Auth0Client } from "@auth0/auth0-spa-js";
import { AIROS, apiUrl, redirectUri } from "./config";

let client: Auth0Client | null = null;

/** Single Auth0 SPA client, created lazily (parity: auth0() in app.js). */
export async function auth0(): Promise<Auth0Client> {
  if (client) return client;
  client = await createAuth0Client({
    domain: AIROS.domain,
    clientId: AIROS.clientId,
    authorizationParams: { redirect_uri: redirectUri() },
  });
  return client;
}

/** login(mode?) - mode "signup" renders the Auth0 sign-up screen (screen_hint). */
export async function login(mode?: "login" | "signup"): Promise<void> {
  const c = await auth0();
  await c.loginWithRedirect({
    authorizationParams: {
      redirect_uri: redirectUri(),
      screen_hint: mode ?? "login",
      ui_locales: getLocale(),
    },
  });
}

export async function logout(): Promise<void> {
  const c = await auth0();
  try {
    await c.logout({ logoutParams: { returnTo: redirectUri() } });
  } catch {
    await c.logout();
  }
}

/** Handles ?code=&state= after redirect, then reports auth state (parity: getSession). */
export async function getSession(): Promise<boolean> {
  const c = await auth0();
  const q = new URLSearchParams(window.location.search);
  if (q.has("code") && q.has("state")) {
    await c.handleRedirectCallback();
    window.history.replaceState(null, "", window.location.pathname);
  }
  return c.isAuthenticated();
}

/** POST {} to Supabase sync_my_account with the raw Auth0 ID token as bearer.
   Exact parity with verify_auth0.py / app.js (DEC-014: no custom token exchange). */
export async function syncAccount(c: Auth0Client): Promise<{ status: number; text: string }> {
  const claims = await c.getIdTokenClaims();
  const resp = await fetch(AIROS.supabaseUrl + "/rest/v1/rpc/sync_my_account", {
    method: "POST",
    headers: {
      apikey: AIROS.supabaseKey,
      Authorization: "Bearer " + (claims?.__raw ?? ""),
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  return { status: resp.status, text: await resp.text() };
}

export function providerLabel(sub: string | null | undefined): string {
  if (sub == null) return "unknown";
  if (sub.indexOf("google-oauth2") === 0) return "Google";
  if (sub.indexOf("auth0|") === 0) return "email + password";
  return "Auth0";
}

/** GET {api}/api/health (no auth) - backend wiring probe (Slice 5, DEC-011).
    Never throws; callers get a displayable result either way. */
export async function checkBackend(): Promise<{ ok: boolean; text: string }> {
  try {
    const resp = await fetch(apiUrl() + "/api/health");
    if (!resp.ok) {
      return { ok: false, text: "backend /api/health -> HTTP " + resp.status };
    }
    const body = (await resp.json()) as { status?: string; config?: string };
    return {
      ok: body.status === "ok",
      text: "backend /api/health -> " + (body.status ?? "?") + " (config " + (body.config ?? "?") + ")",
    };
  } catch (e) {
    return { ok: false, text: "backend unreachable: " + (e as Error).message };
  }
}

/* ---- Locked storage: never throws; falls back to memory (CHG-011 parity). ---- */
const mem: Record<string, string> = {};
let storeOk = true;
try {
  localStorage.setItem("__airos_probe_", "1");
  localStorage.removeItem("__airos_probe_");
} catch {
  storeOk = false;
}

function storageGet(key: string): string | null {
  if (storeOk) {
    try {
      const v = localStorage.getItem(key);
      if (v != null) return v;
    } catch {
      /* fall through to memory */
    }
  }
  return mem[key] ?? null;
}

function storageSet(key: string, value: string): void {
  mem[key] = value;
  if (storeOk) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* memory only */
    }
  }
}

/* ---- Locale ('airos-locale') - passed to Auth0 UL as ui_locales. ---- */
export function getLocale(): string {
  return storageGet("airos-locale") ?? "en";
}

export function setLocale(locale: string): void {
  storageSet("airos-locale", locale);
}

/* ---- Theme ('airos-theme') via data-theme attribute on <html>. ---- */
export function applySavedTheme(): void {
  const saved = storageGet("airos-theme");
  if (saved != null) document.documentElement.setAttribute("data-theme", saved);
}

export function toggleTheme(): void {
  const root = document.documentElement;
  const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
  root.setAttribute("data-theme", next);
  storageSet("airos-theme", next);
}

/** Pre-paint theme restore to avoid a light flash on dark users. */
export const themeBootstrapScript = `(function(){try{var t=localStorage.getItem('airos-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;
