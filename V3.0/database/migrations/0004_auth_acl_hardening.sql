-- =====================================================================
-- AIROS V3 — Auth function ACL hardening (Slice 3, DEC-014 follow-up)
--
-- Discovery (live probe after applying 0003): calling
--   public.sync_my_account()  with the ANONYMOUS (publishable) key
-- resulting in HTTP 400 P0001 ("missing required `sub` claim") — i.e.
-- the function RAN as `anon` instead of being denied.
--
-- Root cause: Supabase installs DEFAULT PRIVILEGES on the `public`
-- schema that directly GRANT EXECUTE on new functions to `anon` and
-- `service_role`. `REVOKE ALL ... FROM PUBLIC` (0003) only removes the
-- PUBLIC pseudo-role grant and does NOT cancel those direct role grants.
--
-- This migration explicitly revokes EXECUTE from `anon` / `service_role`
-- on both auth functions and re-grants ONLY `authenticated`, then fixes
-- the default privileges so future auth functions do not inherit the leak.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. sync_my_account() — the account-provisioning RPC.
--    Must be executable ONLY by `authenticated` (DEC-014).
-- ---------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.sync_my_account() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sync_my_account() FROM anon;
REVOKE ALL ON FUNCTION public.sync_my_account() FROM service_role;
REVOKE ALL ON FUNCTION public.sync_my_account() FROM postgres;
GRANT EXECUTE ON FUNCTION public.sync_my_account() TO authenticated;

-- ---------------------------------------------------------------------
-- 2. current_account_id() — the RLS identity resolver (0002).
--    Same doctrine: only `authenticated` (RLS runs as the caller role).
-- ---------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.current_account_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.current_account_id() FROM anon;
REVOKE ALL ON FUNCTION public.current_account_id() FROM service_role;
REVOKE ALL ON FUNCTION public.current_account_id() FROM postgres;
GRANT EXECUTE ON FUNCTION public.current_account_id() TO authenticated;

-- ---------------------------------------------------------------------
-- 3. Default privileges (postgres-owned, public schema): future functions
--    no longer inherit the platform's anon/service_role grants.
-- ---------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, service_role, postgres;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO authenticated;

COMMIT;