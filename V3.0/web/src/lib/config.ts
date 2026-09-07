/* AIROS V3 - frontend config (Slice 4a, CHG-012). Everything here is PUBLIC:
   Auth0 domain/client ID and the Supabase publishable key. The Auth0 Client
   Secret and the Supabase service_role key must NEVER appear in web/. */
const defaults = {
  domain: "dev-s6kc2wm7ppaoj8ni.eu.auth0.com",
  clientId: "mIqi9un7HPVTP8Ej5xlmXkkosUXYArDJ",
  supabaseUrl: "https://hpjeafsticujbswgfqjs.supabase.co",
  supabaseKey: "sb_publishable_ahyHLdUk7Tkc7P45DEgMfQ_ZK2bNdJ9",
};

export const AIROS = {
  domain: process.env.NEXT_PUBLIC_AUTH0_DOMAIN ?? defaults.domain,
  clientId: process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID ?? defaults.clientId,
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL ?? defaults.supabaseUrl,
  supabaseKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? defaults.supabaseKey,
};

/** Post-login destination. Overridable via NEXT_PUBLIC_APP_REDIRECT.
 * MUST exactly match the Allowed Callback + Logout URLs registered in Auth0.
 * Hardcoded to localhost (not window.location.origin) so it matches Auth0
 * regardless of whether the user accesses the site via 127.0.0.1 or localhost.
 * Verified: Auth0 returns 403 for 127.0.0.1 but 302 for localhost. */
export function redirectUri(): string {
  if (process.env.NEXT_PUBLIC_APP_REDIRECT) return process.env.NEXT_PUBLIC_APP_REDIRECT;
  return "http://localhost:3000/app";
}

/** Backend resource server (Slice 5, DEC-011). Overridable via
 * NEXT_PUBLIC_API_URL; dev default is the FastAPI dev port. */
export function apiUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
}
