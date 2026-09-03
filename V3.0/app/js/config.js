/* AIROS V3 - app shell config (interim UI, everything public/publishable). */
/* Only PUBLIC values live here: Auth0 domain/client ID and the Supabase publishable key.
   The Auth0 Client Secret and Supabase service_role must NEVER appear in frontend code. */
window.AIROS_CONFIG = {
  // Auth0 tenant + application (Slice 3, DEC-014)
  domain: 'dev-s6kc2wm7ppaoj8ni.eu.auth0.com',
  clientId: 'mIqi9un7HPVTP8Ej5xlmXkkosUXYArDJ',
  // Must be registered as an "Allowed Callback URL" + "Allowed Logout
  // URL" in Auth0 -> Applications -> Settings (docs/AUTH0_SETUP.md Step 3bis).
  redirect: 'http://localhost:8000/app/app.html',

  // Supabase project (Slice 2/3)
  supabaseUrl: 'https://hpjeafsticujbswgfqjs.supabase.co',
  supabaseKey: 'sb_publishable_ahyHLdUk7Tkc7P45DEgMfQ_ZK2bNdJ9',

  // Optional: request the Auth0 Universal Login in a specific language
  // (standard OIDC ui_locales - Auth0 UL honors it(. 'en' is default;
  // 'fr' renders French prompts (edit copy via Branding > UL > Custom Text(.
  locale: 'en',
};