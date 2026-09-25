# PROMPT FOR CLINE — Backlog Topic: RH contact recording + Application Workspace approval gate + App Tracking menu (consolidated user request)

Copy everything below this line into Cline in VS Code (workspace: `AIROS V3.0`).

---

## TOPIC — Consolidated user request (3 requirements): close the gaps against the existing CHG-021 / CHG-022 / CHG-023 implementation

You are working in AIROS V3.0 only. V2.0 is read-only. Most of the flow below ALREADY EXISTS — your job is to VERIFY it end-to-end and close ONLY the real gaps listed in "Scope". Do not rebuild what is already implemented. Register the topic in `docs/PROJECT_CONTROL_REGISTER.md` as the next free CHG number (CHG-023 is referenced in code comments but is NOT yet registered — reconcile that first, then use the next free number for genuinely new changes).

### Context — what already exists (verified in code, do NOT re-implement)

- JD recruiter (RH) extraction: `ai/ats.py` schema + `extract_recruiter_from_jd_text()` deterministic fallback (CHG-021). Generic inboxes (info@, careers@…) are rejected.
- Save-Job RH form prefilled from `parsed_job.recruiter_contact`, editable by the user: `web/src/components/applications/SaveJobStep.tsx`.
- Server-side recruiter persistence incl. partial contacts (name-only / phone-only …): `services/api/routers/applications.py` ("CHG-023" comments, recruiter persistence hardening).
- `contacts.phone`, `jobs.docs_generated_at`, `jobs.docs_approved_at`, `applications.docs_approved_at`: `database/migrations/0008_workspace_approval.sql`.
- Approval endpoint stamping system datetime + `time_consumed_min`: `services/api/routers/applications.py` (~line 644+).
- Prepare step with RH banner, Generate button, Original-vs-Tailored ATS tiles, sub-2-point-gain "marginal" honesty message: `web/src/components/applications/PrepareTab.tsx` + `ai/document_validation.py` (CHG-022).
- Track step (manual-only V2 lifecycle, all previous V2 features): `web/src/components/applications/TrackTab.tsx`, `ai/lifecycle.py` (CHG-018).
- Menu flow: Dashboard → Profile → Applications (Analyze → Prepare → Track) via `web/src/components/Sidebar.tsx` and `web/src/app/applications/page.tsx` (StageStepper).

### Scope — the 3 requirements and their REAL gaps

**R1 — RH contact data: always request it, always record it to a JSON file at call time.**
The user considers JD-extracted RH info NOT fully reliable. Requirements:
1. After the JD is analyzed (ATS verdict step), AIROS must ALWAYS present the RH capture step and ask the user to confirm/complete the RH data — even when the JD extraction found something. Prefill from extraction, but the form must never be skipped silently.
2. When the user submits RH data (name + email, phone optional but MUST be captured and stored when present), AIROS must save it to the database AS TODAY (contacts table, RLS-scoped) AND ALSO write a JSON record to the per-user workspace at call time.
3. The JSON record (one file per job, e.g. `data/uploads/<auth0_id>/generated/<JOB_ID>/rh_contact.json` — follow the existing generated-files layout in `data/uploads/…`) must contain: `job_id`, `name`, `email`, `phone`, `position`, `linkedin_url`, `source` (`jd_extracted` | `manual` | `jd_extracted_user_confirmed`), `captured_at` (exact system ISO datetime), and the account identifier. Writes must be best-effort and non-blocking: a JSON write failure must NEVER fail the API call (log it, continue). Stay consistent with the storage pattern used for generated documents (check how `data/uploads` is used in `services/` and reuse the same helper/pattern — do not invent a parallel storage layer).
4. Frontend: the RH step must visually confirm "RH data saved (database + record file)" after submission, and remain editable/re-submittable (the JSON file is overwritten with the latest confirmed values, keeping `captured_at` fresh).

**R2 — Application Workspace (preparation) ordering: improvement preview FIRST, then an explicit approval button, then ready documents + system date/time stamp.**
1. Menu naming: keep the existing Sidebar/StageStepper naming ("Applications" with the Analyze → Prepare → Track stepper). The Prepare step is the "Application Workspace / Preparation". Do not create duplicate menus.
2. Verify and enforce this exact sequence: ATS analysis success → Save job + RH (R1) → Prepare step shows, PER DOCUMENT, the relevant improvements BEFORE final generation: the tailored-CV improvement summary (Original ATS score vs expected tailored score, sub-score highlights, and the explicit message when the deterministic gain cannot beat ~2 points — reuse the CHG-022 `marginal` status wording) plus the cover-letter and (when reliable RH exists) recruiter-email previews.
3. The user MUST approve by clicking an explicit button (suggested label: "✅ Approve & generate ready documents"). Only on approval: call the document engine, persist the generated documents, and stamp the EXACT system date+time (`docs_generated_at` on generation; `docs_approved_at` via the existing approval endpoint). If the current implementation already generates-then-approves, reorder so the approval gate comes before the final ready-document persistence — keep the existing endpoint signatures and validation logic, only re-sequence the frontend flow (and, if needed, split the existing endpoint into preview vs generate; prefer frontend re-sequencing to minimize backend churn).
4. The recorded timestamps must let the system compute the application process period when the user later returns and confirms the application (Confirm → tracking record APPLIED): verify `time_consumed_min` = minutes between `docs_generated_at` and confirm time still works through `ai/lifecycle.py` `build_tracking_record` + the confirm endpoint, and surface the elapsed period in the Confirm step UI ("Package generated <date time> — <n> minutes/hours ago").

**R3 — App Tracking menu: keep ALL previous-version features exactly as they are.**
The tracking feature ("App tracking" / Job Tracking workspace, CHG-018, V2 page-5 parity) already exists in `TrackTab.tsx` + `ai/lifecycle.py`. Requirement: NO regression and NO feature loss. Verify the full manual lifecycle is reachable from the menu flow (Dashboard → Applications → Track) and that every V2 capability still works: status transitions (APPLIED → WAITING → EMPLOYER_RESPONSE → SCREENING → INTERVIEW → OFFER), illegal-transition rejection, recruiter responses, interview scheduling, follow-up actions, next-action display, refused/closed outcomes, recruiter + RH context display. Do not change its behavior; only fix anything broken that you find during verification.

### Non-goals (scope protection)

- No new frameworks, paid services, or infra. Free-plan only.
- No changes to the deterministic ATS engine's scoring algorithm (CHG-022 behavior is frozen except where R2 requires re-sequencing UI flow).
- No changes to V2.0, no new sidebar menus beyond what exists.
- No migration of the RH JSON record into V2's `users_db.json` — this is a V3 per-job file only.

### Validation (Definition of Done)

- `pytest` from V3.0 root: all existing tests pass (baseline was 221 passed); add tests for (a) the JSON record write incl. `captured_at` + non-blocking failure, (b) the approval-gate ordering (approval stamps `docs_approved_at` BEFORE final persistence / the confirm duration is correct), (c) a regression test asserting the Track lifecycle endpoints are untouched (existing tests already cover this — they must stay green).
- `npx tsc --noEmit` in `web/` clean; production `npm run build` green.
- Manual e2e walk-through documented in the final report: Dashboard → Profile → Applications → Analyze (JD with an RH name) → RH capture (edit prefill, confirm) → verify `rh_contact.json` exists with correct fields → Prepare preview (ATS tiles + marginal message) → "Approve & generate" → timestamps stamped → Confirm application → tracking record with correct `time_consumed_min`.
- Update `docs/PROJECT_CONTROL_REGISTER.md`: register the reconciled CHG-023 entry (if missing) and the new CHG for this topic, with files touched, validation results, and UAT-pending status.

### Report & stop

Finish with the standard topic report (implemented / files / tests / results / decisions / limitations) and STOP — wait for explicit user approval before any other backlog topic.
