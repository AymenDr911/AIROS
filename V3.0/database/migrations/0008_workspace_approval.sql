-- =====================================================================
-- AIROS V3 — Workspace approval + recruiter hardening (CHG-023)
-- Idempotent DDL:
--   * contacts.phone          — recruiter phone captured from the JD / manual form
--   * jobs.docs_generated_at  — exact system datetime of document generation
--   * jobs.docs_approved_at   — exact system datetime of the user's approval
--   * applications.docs_approved_at — carried into the confirmed tracking record
-- PostgreSQL 15+ on Supabase (free tier).
-- =====================================================================

BEGIN;

ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT '';

ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS docs_generated_at TEXT NOT NULL DEFAULT '';
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS docs_approved_at   TEXT NOT NULL DEFAULT '';

ALTER TABLE public.applications ADD COLUMN IF NOT EXISTS docs_approved_at TEXT NOT NULL DEFAULT '';

COMMIT;