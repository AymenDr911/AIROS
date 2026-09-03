-- =====================================================================
-- AIROS V3 — Per-account Row Level Security (Slice 2, DEC-013 / ISS-003)
-- PostgreSQL 15+ on Supabase (free tier). Idempotent DDL.
--
-- Isolation model:
--   * identity in V3 comes from Auth0 (DEC-003). The authenticated user is
--     identified by the JWT `sub` claim (auth.jwt() -> 'sub').
--   * `current_account_id()` resolves that claim to our `accounts.id`
--     and is SECURITY DEFINER so ids are never leaked to clients.
--   * every user-data table gets SELECT/INSERT/UPDATE/DELETE policies
--     scoped to `account_id = current_account_id()`.
-- =====================================================================

BEGIN;

-- tbls: the four user-data tables (all must be covered).
-- accounts itself is owned by its row; sub-policies apply via auth0_sub.

-- ---------------------------------------------------------------------
-- 1. Resolve authenticated Auth0 subject -> V3 account id
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.current_account_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id
      FROM public.accounts
     WHERE auth0_sub = auth.jwt() ->> 'sub'
     LIMIT 1
$$;

REVOKE ALL ON FUNCTION public.current_account_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.current_account_id() TO authenticated;

-- ---------------------------------------------------------------------
-- 2. Enable RLS on every user-data table (defense in depth)
-- ---------------------------------------------------------------------
ALTER TABLE public.accounts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents    ENABLE ROW LEVEL SECURITY;

-- FORCE so even the table owner (postgres) is constrained; only the
-- service_role (backend) can bypass RLS.
ALTER TABLE public.accounts     FORCE ROW LEVEL SECURITY;
ALTER TABLE public.profiles     FORCE ROW LEVEL SECURITY;
ALTER TABLE public.applications FORCE ROW LEVEL SECURITY;
ALTER TABLE public.documents    FORCE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------
-- 3. Per-account policies (authenticated users only)
-- ---------------------------------------------------------------------

-- accounts: a user reads/updates only their own row (matched on auth0_sub).
DROP POLICY IF EXISTS accounts_select_own ON public.accounts;
CREATE POLICY accounts_select_own
    ON public.accounts
    FOR SELECT
    TO authenticated
    USING (auth0_sub = auth.jwt() ->> 'sub');

DROP POLICY IF EXISTS accounts_update_own ON public.accounts;
CREATE POLICY accounts_update_own
    ON public.accounts
    FOR UPDATE
    TO authenticated
    USING (auth0_sub = auth.jwt() ->> 'sub')
    WITH CHECK (auth0_sub = auth.jwt() ->> 'sub');

-- profiles / applications / documents: scoped via the resolved account id.
DROP POLICY IF EXISTS profiles_select_own ON public.profiles;
CREATE POLICY profiles_select_own
    ON public.profiles
    FOR SELECT
    TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS profiles_insert_own ON public.profiles;
CREATE POLICY profiles_insert_own
    ON public.profiles
    FOR INSERT
    TO authenticated
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS profiles_update_own ON public.profiles;
CREATE POLICY profiles_update_own
    ON public.profiles
    FOR UPDATE
    TO authenticated
    USING (account_id = public.current_account_id())
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS profiles_delete_own ON public.profiles;
CREATE POLICY profiles_delete_own
    ON public.profiles
    FOR DELETE
    TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS applications_select_own ON public.applications;
CREATE POLICY applications_select_own
    ON public.applications
    FOR SELECT
    TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS applications_insert_own ON public.applications;
CREATE POLICY applications_insert_own
    ON public.applications
    FOR INSERT
    TO authenticated
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS applications_update_own ON public.applications;
CREATE POLICY applications_update_own
    ON public.applications
    FOR UPDATE
    TO authenticated
    USING (account_id = public.current_account_id())
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS applications_delete_own ON public.applications;
CREATE POLICY applications_delete_own
    ON public.applications
    FOR DELETE
    TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS documents_select_own ON public.documents;
CREATE POLICY documents_select_own
    ON public.documents
    FOR SELECT
    TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS documents_insert_own ON public.documents;
CREATE POLICY documents_insert_own
    ON public.documents
    FOR INSERT
    TO authenticated
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS documents_update_own ON public.documents;
CREATE POLICY documents_update_own
    ON public.documents
    FOR UPDATE
    TO authenticated
    USING (account_id = public.current_account_id())
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS documents_delete_own ON public.documents;
CREATE POLICY documents_delete_own
    ON public.documents
    FOR DELETE
    TO authenticated
    USING (account_id = public.current_account_id());

COMMIT;