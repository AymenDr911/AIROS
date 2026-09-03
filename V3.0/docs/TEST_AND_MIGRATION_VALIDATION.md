# AIROS V3 — Test & Migration Validation Plan

**Objective:** Prove that V3 works correctly and that V2 data was migrated without unexplained loss or corruption.

Aligns with:
- Project Charter §5 (Success Criteria 1–6).
- Security & GDPR Baseline §8 (V2 remediation before migration).
- Migration Spec §4 (data-integrity rules) and §6 (repeatability).
- Project Control Register: R01, R05, R06, R07; CHG-001 (Security/GDPR before migration).

Reference owner: solo developer. Register rule applies: any change to this plan is recorded in the Register first.

---

## 1. Test levels → engineering surface → evidence

| Level | Targets (V3 module) | Concrete checks |
|-------|---------------------|-----------------|
| **Unit** | Business engines (deterministic rules) | skill classification; hard blockers; job matching; ATS calculations; lifecycle transitions; time-consumed calc |
| **Integration** | Services connecting engines + AI gateway | CV→Profile; JD→Job Intelligence; Profile+Job→Match; Match→Documents; Application→Tracker; Tracker→Interview prep |
| **Migration** | `migration/` pipeline (extract→transform→staging→load→reconcile) | record counts, relationships, field transformations, identifiers, document references, lifecycle history |
| **Security / GDPR** | Auth (Auth0), authorization, storage, config | authentication; authorization; user isolation; Super Admin restriction; document access; account deletion/export; secrets/config; unsafe input/file handling |
| **UAT** | Full UX journeys (UI consuming the API) | complete representative user journeys |

---

## 2. Migration test cases — mapped to real V2 evidence + synthetic fixtures

Required cases, each zipped to whether the current real V2 snapshot provides it or we need a fixture:

| # | Case | Real V2 source | Notes |
|---|------|----------------|-------|
| 1 | New / simple profile | `test@airos.demo` (**must be DISCARDED**) | doubles as the "discard demo/test data" negative test |
| 2 | Senior profile w/ long experience | `aymen.a@hotmail.com` (16+ yrs, PMP) | long-role evidence & skills classification exercised |
| 3 | Multiple professional roles | **not in V2** → synthetic fixture | exercises multi-profile transform |
| 4 | Multiple certifications + skills | real (13 certs incl. PMP; skills{}, languages[]) | certification→capability + reclassify |
| 5 | Existing application w/ recruiter | real (recruiter name/email on `APP-20260823-194420`) | contact reliability filtering; doc-reference integrity |
| 6 | Interview-stage application | real (`status=INTERVIEW`, timeline has APPLIED→INTERVIEW, interviews[]) | lifecycle + timeline transform |
| 7 | Rejected application | **not in V2** → synthetic fixture | retention/deletion rule + status encoding |
| 8 | Incomplete / legacy data | **not in V2** → synthetic fixture | partial-record tolerance; reconciliation |

> Test suite reuses the **same frozen V2 `users_db.json`** inspection we already did: it reads the live `V2.0/data/users_db.json`, so the fixture is the real payload, not a mock.

---

## 3. ATS benchmark (risk R06)

- Build a **fixed reference dataset** of representative JDs + pre-labelled expected component scores.
- Compare AIROS deterministic ATS scores against **selected external ATS tools**.
- Purpose: **calibrate and assess AIROS performance** — it is *not* a user-facing dependency and must **never determine an individual user's result**.
- Store benchmark result & scoring-version snapshots (tracked) so drift is visible; record changes per Register DEC-006.

---

## 4. Go / No-Go criteria (gate migration to production)

Migration is approved **only if all**:
1. Required records reconcile (counts, relationships, ids, refs, lifecycle history).
2. No critical data-integrity defect remains.
3. Critical end-to-end workflows pass.
4. Security + GDPR checks pass (auth, authz, isolation, Super Admin restriction, document access, deletion/export, secrets, unsafe-input).
5. Storage + resource limits pass (free-tier budget; retention applied).
6. Rollback is available and verified (frozen `V2.0` baseline, DEC-008).

Each maps to a Charter success criterion (1–6) so a PASS here equals the migration-gate.