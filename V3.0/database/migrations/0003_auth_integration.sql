-- =====================================================================
-- AIROS V3 — Auth0 <-> Supabase identity integration (Slice 3, DEC-003/DEC-014)
--
-- Uses the NATIVE Supabase "Third-party Auth" Auth0 integration: an Auth0
-- ID token (RS256) carrying `role='authenticated'` is presented to
-- PostgREST, which verifies it and exposes its claims via `auth.jwt()`.
--
--   * This migration adds the DB-side account sync only:
--       public.sync_my_account() upserts the caller's OWN `accounts` row,
--       reading `sub` / `email` strictly from the verified JWT, never
--       from a client parameter.
--   * The Auth0 tenant + Supabase integration are configured in the
--     dashboards (see docs/AUTH0_SETUP.md). RS256 only (HS256/PS256 are
--     not supported by the Supabase integration).
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- sync_my_account() - one-call, idempotent account provisioning.
-- Returns the caller's account UUID. SAFE: uses only server-verified
-- claims (`auth.jwt()` is the JWT that Supabase already verified), so a
-- client can never create or own an account for someone else's sub.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_my_account()
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, auth
AS $$
DECLARE
    v_sub    text;
    v_email  text;
    v_ver    boolean;
    v_id     uuid;
BEGIN
    v_sub   := nullif(auth.jwt() ->> 'sub', '');
    v_email := nullif(auth.jwt() ->> 'email', '');
    v_ver   := coalesce(nullif(auth.jwt() ->> 'email_verified', '')::boolean, true);

    IF v_sub IS NULL THEN
        RAISE EXCEPTION 'sync_my_account: missing required `sub` claim in the verified JWT';
    END IF;

    INSERT INTO public.accounts (email, auth0_sub, verified, source_key)
    VALUES (coalesce(v_email, 'auth0-' || v_sub), v_sub, v_ver, NULL)
    ON CONFLICT (auth0_sub)
    DO UPDATE SET email      = COALESCE(EXCLUDED.email, public.accounts.email),
                  verified   = public.accounts.verified OR EXCLUDED.verified,
                  updated_at = now()
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

REVOKE ALL ON FUNCTION public.sync_my_account() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sync_my_account() TO authenticated;

COMMIT;