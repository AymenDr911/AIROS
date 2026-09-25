-- =====================================================================
-- AIROS V3 — RLS extension for the application workspace tables
-- (CHG-018). Same isolation model as 0002_rls.sql / DEC-013:
-- current_account_id() resolves the Auth0 `sub` claim to accounts.id
-- (SECURITY DEFINER helper already created in 0002), every new user-data
-- table gets SELECT/INSERT/UPDATE/DELETE policies scoped to it.
-- Idempotent DDL.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Enable + FORCE RLS on the new tables (defense in depth)
-- ---------------------------------------------------------------------
ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs       ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.companies FORCE ROW LEVEL SECURITY;
ALTER TABLE public.contacts   FORCE ROW LEVEL SECURITY;
ALTER TABLE public.jobs       FORCE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------
-- 2. Per-account policies (authenticated users only)
-- ---------------------------------------------------------------------

-- companies
DROP POLICY IF EXISTS companies_select_own ON public.companies;
CREATE POLICY companies_select_own
    ON public.companies FOR SELECT TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS companies_insert_own ON public.companies;
CREATE POLICY companies_insert_own
    ON public.companies FOR INSERT TO authenticated
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS companies_update_own ON public.companies;
CREATE POLICY companies_update_own
    ON public.companies FOR UPDATE TO authenticated
    USING (account_id = public.current_account_id())
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS companies_delete_own ON public.companies;
CREATE POLICY companies_delete_own
    ON public.companies FOR DELETE TO authenticated
    USING (account_id = public.current_account_id());

-- contacts
DROP POLICY IF EXISTS contacts_select_own ON public.contacts;
CREATE POLICY contacts_select_own
    ON public.contacts FOR SELECT TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS contacts_insert_own ON public.contacts;
CREATE POLICY contacts_insert_own
    ON public.contacts FOR INSERT TO authenticated
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS contacts_update_own ON public.contacts;
CREATE POLICY contacts_update_own
    ON public.contacts FOR UPDATE TO authenticated
    USING (account_id = public.current_account_id())
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS contacts_delete_own ON public.contacts;
CREATE POLICY contacts_delete_own
    ON public.contacts FOR DELETE TO authenticated
    USING (account_id = public.current_account_id());

-- jobs
DROP POLICY IF EXISTS jobs_select_own ON public.jobs;
CREATE POLICY jobs_select_own
    ON public.jobs FOR SELECT TO authenticated
    USING (account_id = public.current_account_id());

DROP POLICY IF EXISTS jobs_insert_own ON public.jobs;
CREATE POLICY jobs_insert_own
    ON public.jobs FOR INSERT TO authenticated
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS jobs_update_own ON public.jobs;
CREATE POLICY jobs_update_own
    ON public.jobs FOR UPDATE TO authenticated
    USING (account_id = public.current_account_id())
    WITH CHECK (account_id = public.current_account_id());

DROP POLICY IF EXISTS jobs_delete_own ON public.jobs;
CREATE POLICY jobs_delete_own
    ON public.jobs FOR DELETE TO authenticated
    USING (account_id = public.current_account_id());

COMMIT;
