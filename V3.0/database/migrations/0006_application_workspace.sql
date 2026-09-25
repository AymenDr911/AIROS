-- =====================================================================
-- AIROS V3 — Application workspace (CHG-018)
-- companies / contacts / jobs + V2-parity columns on applications.
-- PostgreSQL 15+ on Supabase (free tier). Idempotent DDL.
--
-- Design rules (Project Control Register):
--   * per-account isolation via Row Level Security, same pattern as
--     0002_rls.sql (current_account_id() from the Auth0 `sub` claim;
--     RLS policies for the new tables are added in 0007_rls_extension.sql)
--   * V2 identifier parity: JOB-YYYY-NNNNNN / COMP-YYYY-NNNNNN /
--     CONT-YYYY-NNNNNN are stored as TEXT (V2 provenance, unique per
--     account); uuid PKs remain the join keys (DEC-013)
--   * flexible histories (timeline, interviews, interactions, responses,
--     follow-ups, assessment) stay JSONB (DEC-013)
--   * document CONTENT never lands in the DB (ISS-006): generated
--     documents live in the protected store; `documents` stays
--     metadata-only
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- companies — one row per (account, company); V2 find_or_create parity
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.companies (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      uuid        NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    company_id      TEXT        NOT NULL,          -- V2 identifier (COMP-YYYY-NNNNNN)
    name            TEXT        NOT NULL,
    division        TEXT        NOT NULL DEFAULT '',
    industry        TEXT        NOT NULL DEFAULT '',
    address         TEXT        NOT NULL DEFAULT '',
    city            TEXT        NOT NULL DEFAULT '',
    country         TEXT        NOT NULL DEFAULT '',
    website         TEXT        NOT NULL DEFAULT '',
    careers_website TEXT        NOT NULL DEFAULT '',
    linkedin_url    TEXT        NOT NULL DEFAULT '',
    phone           TEXT        NOT NULL DEFAULT '',
    general_emails  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    notes           TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, company_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_account_name
    ON public.companies (account_id, lower(name));
CREATE INDEX IF NOT EXISTS idx_companies_account ON public.companies (account_id);

-- ---------------------------------------------------------------------
-- contacts — recruiters / hiring managers (V2 contact.py fields)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.contacts (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id    uuid        NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    contact_id    TEXT        NOT NULL,            -- V2 identifier (CONT-YYYY-NNNNNN)
    company_id    TEXT        NOT NULL,            -- V2 companies.company_id (per account)
    name          TEXT        NOT NULL DEFAULT '',
    position      TEXT        NOT NULL DEFAULT '',
    email         TEXT        NOT NULL DEFAULT '',
    linkedin_url  TEXT        NOT NULL DEFAULT '',
    contact_type  TEXT        NOT NULL DEFAULT 'General',   -- HR Recruiter | Talent Acquisition | Hiring Manager | General
    source        TEXT        NOT NULL DEFAULT 'Manual',
    confidence    TEXT        NOT NULL DEFAULT 'Medium',    -- High / Medium / Low
    verified      BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_contacts_account ON public.contacts (account_id);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON public.contacts (account_id, company_id);

-- ---------------------------------------------------------------------
-- jobs — saved analyzed job offers (V2 save_job record, Stage 1 output)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.jobs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        uuid        NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    job_id            TEXT        NOT NULL,        -- V2 identifier (JOB-YYYY-NNNNNN)
    company_id        TEXT        NOT NULL,        -- V2 companies.company_id (per account)
    title             TEXT        NOT NULL DEFAULT '',
    department        TEXT        NOT NULL DEFAULT '',
    location          TEXT        NOT NULL DEFAULT '',
    country           TEXT        NOT NULL DEFAULT '',
    job_url           TEXT        NOT NULL DEFAULT '',
    source            TEXT        NOT NULL DEFAULT 'Manual',
    original_jd       TEXT        NOT NULL DEFAULT '',
    job_json          JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- structured Gemini parse
    publication_date  TEXT        NOT NULL DEFAULT '',
    analysis_date     TEXT        NOT NULL DEFAULT '',
    ats_score         NUMERIC,
    ats_components    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    gap_analysis      JSONB       NOT NULL DEFAULT '[]'::jsonb,
    strengths         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    evidence          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    recommendation    TEXT        NOT NULL DEFAULT '',
    verdict           JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- CHG-017 verdict snapshot
    contact_ids       JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- V2 contacts.contact_id list
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_account  ON public.jobs (account_id);
CREATE INDEX IF NOT EXISTS idx_jobs_company  ON public.jobs (account_id, company_id);

-- ---------------------------------------------------------------------
-- applications — extend with the V2 tracker record fields (CHG-018).
-- Flat captured-snapshot columns + JSONB histories, 0001 stays intact.
-- ---------------------------------------------------------------------
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS channel                TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS notes                  TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS docs_generated_at      TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS company_name           TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS location               TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS country                TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS job_url                TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS source                 TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS recruiter_position     TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS recruiter_linkedin     TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS recruiter_id           TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS recruiter_interactions JSONB  NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS recruiter_responses    JSONB  NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS follow_ups             JSONB  NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS assessment             JSONB;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS outcome_detail         JSONB;
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS last_activity          TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS last_activity_at       TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS follow_up_checkpoint   TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS employer_response_date TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS job_closing_date       TEXT   NOT NULL DEFAULT '';
ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS next_action_source     TEXT   NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_applications_job_id ON public.applications (account_id, job_id);

-- updated_at triggers for the new tables
DROP TRIGGER IF EXISTS trg_companies_updated_at ON public.companies;
DROP TRIGGER IF EXISTS trg_contacts_updated_at  ON public.contacts;
DROP TRIGGER IF EXISTS trg_jobs_updated_at      ON public.jobs;
CREATE TRIGGER trg_companies_updated_at BEFORE UPDATE ON public.companies FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_contacts_updated_at  BEFORE UPDATE ON public.contacts  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_jobs_updated_at      BEFORE UPDATE ON public.jobs      FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

COMMIT;


