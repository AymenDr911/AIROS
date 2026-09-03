-- =====================================================================
-- AIROS V3 — Core schema (Slice 2, DEC-009 / DEC-013)
-- PostgreSQL 15+ on Supabase (free tier). Idempotent DDL.
--
-- Design rules (from the Project Control Register):
--   * no V2 password column anywhere (ISS-001)
--   * no inline base64 document content (ISS-006) -> documents are
--     metadata-only stubs referencing a protected store (DEC-012)
--   * every user-data table is per-account isolated via Row Level
--     Security (ISS-003); RLS is applied in 0002_rls.sql
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- accounts  — one row per AIROS user (identity source of truth).
-- email is the unique natural key; auth0_sub is filled by the Auth0
-- integration slice (DEC-003) and used by RLS (`current_account_id()`).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.accounts (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email        TEXT        NOT NULL,
    auth0_sub    TEXT UNIQUE,
    verified     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_key   TEXT UNIQUE -- V2 snapshot key (email) for provenance/rollback
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_email ON public.accounts (lower(email));

-- ---------------------------------------------------------------------
-- profiles — 1:1 with accounts. Flexible payloads kept as JSONB so the
-- exact V2-derived shapes survive without destructive migrations.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    account_id      uuid PRIMARY KEY REFERENCES public.accounts(id) ON DELETE CASCADE,
    career_stage    TEXT      NOT NULL DEFAULT '',
    identity        JSONB     NOT NULL DEFAULT '{}'::jsonb,
    education       JSONB     NOT NULL DEFAULT '[]'::jsonb,
    experience      JSONB     NOT NULL DEFAULT '[]'::jsonb,
    skills          JSONB     NOT NULL DEFAULT '{}'::jsonb,   -- {CATEGORY: [skill,...]}
    languages       JSONB     NOT NULL DEFAULT '[]'::jsonb,
    certifications  JSONB     NOT NULL DEFAULT '[]'::jsonb,
    strong_evidence BOOLEAN   NOT NULL DEFAULT FALSE,
    original_cv_count INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- ---------------------------------------------------------------------
-- applications — one row per job application, owned by an account.
-- Lifecycle timeline + interviews stay as JSONB (flexible history,
-- DEC-013), with validated top-level columns for querying.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.applications (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id            uuid        NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    application_id        TEXT        NOT NULL,          -- V2 identifier (provenance)
    job_id                TEXT        NOT NULL,
    company_id            TEXT        NOT NULL,
    title                 TEXT        NOT NULL DEFAULT '',
    status                TEXT        NOT NULL DEFAULT '', -- KNOWN_LIFECYCLE set
    application_date      DATE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    ats_score             NUMERIC,                        -- historical only (recalculated: DEC-006)
    time_consumed_min     INTEGER,
    recruiter_name        TEXT        NOT NULL DEFAULT '',
    recruiter_email       TEXT        NOT NULL DEFAULT '',
    outcome               TEXT        NOT NULL DEFAULT '',
    timeline              JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- lifecycle history
    interviews            JSONB       NOT NULL DEFAULT '[]'::jsonb,
    cv_version            TEXT        NOT NULL DEFAULT '',
    cover_letter_version  TEXT        NOT NULL DEFAULT '',
    recruiter_email_path  TEXT        NOT NULL DEFAULT '',
    UNIQUE (account_id, application_id)
);

CREATE INDEX IF NOT EXISTS idx_applications_account    ON public.applications (account_id);
CREATE INDEX IF NOT EXISTS idx_applications_status     ON public.applications (status);
CREATE INDEX IF NOT EXISTS idx_applications_company    ON public.applications (company_id);
-- ---------------------------------------------------------------------
-- documents — metadata-only stubs (ISS-006). Content bytes live in the
-- protected document store (DEC-012), never in the database.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.documents (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id    uuid        NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    original_name TEXT        NOT NULL,
    saved_as      TEXT        NOT NULL DEFAULT '',
    uploaded_at   TIMESTAMPTZ,
    size_kb       NUMERIC,
    mime          TEXT        NOT NULL DEFAULT '',
    storage_ref   TEXT        NOT NULL DEFAULT '',  -- pointer to protected store
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_account ON public.documents (account_id);

-- updated_at trigger helper + apply to all tables
CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_accounts_updated_at     ON public.accounts;
DROP TRIGGER IF EXISTS trg_profiles_updated_at     ON public.profiles;
DROP TRIGGER IF EXISTS trg_applications_updated_at ON public.applications;
DROP TRIGGER IF EXISTS trg_documents_updated_at    ON public.documents;

CREATE TRIGGER trg_accounts_updated_at     BEFORE UPDATE ON public.accounts     FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_profiles_updated_at     BEFORE UPDATE ON public.profiles     FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_applications_updated_at BEFORE UPDATE ON public.applications FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER trg_documents_updated_at    BEFORE UPDATE ON public.documents    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

COMMIT;