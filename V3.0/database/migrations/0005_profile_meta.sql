-- =====================================================================
-- AIROS V3 - Profile metadata columns (Slice 6, CHG-014, V2 parity).
--
-- V2's onboarding tracked `profile_method` ("manual" | "ai") and
-- `onboarding_completed` per user profile (services/profile_service.py
-- PROFILE_KEYS). V3 preserves those semantics as real columns so the
-- new profile-creation flow behaves exactly like V2 and the migration
-- can carry the V2 values verbatim.
-- Idempotent DDL, transactional like 0001-0004.
-- =====================================================================

BEGIN;

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS profile_method TEXT NOT NULL DEFAULT '';

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
