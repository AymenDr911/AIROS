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

/** Post-login destination. Overridable via NEXT_PUBLIC_APP_REDIRECT; by
 * default derived from the current origin so dev/prod ports just work.
 * Must be registered as an Allowed Callback + Logout URL in Auth0. */
export function redirectUri(): string {
  if (process.env.NEXT_PUBLIC_APP_REDIRECT) return process.env.NEXT_PUBLIC_APP_REDIRECT;
  if (typeof window !== "undefined") return window.location.origin + "/app";
  return "http://localhost:3000/app";
}

/** Backend resource server (Slice 5, DEC-011). Overridable via
 * NEXT_PUBLIC_API_URL; dev default is the FastAPI dev port. */
export function apiUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
}
