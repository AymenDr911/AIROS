"use client";
/* AIROS V3 - ① Job Analyses menu (CHG-025).

THE USER-REQUESTED FLOW, exactly as specified (15 Sep 2026):
  a. the user pastes a JD in the "Job Analyses" sidebar menu;
  b. AIROS verifies it and produces the ATS + compatibility score between the
     JD and the user's OWN CV/profile (frozen deterministic engine, DEC-006);
  c. the FULL analysis report is listed on the page;
  d. the FINAL DECISION is rendered at the BOTTOM of the page;
  e. FAILED -> AIROS states the decision and clears the JD zone, which is left
     ready (and focused) for the next job offer; the report stays visible so
     every detail can still be read;
  f. PASSED -> AIROS closes the Job Analyses step and hands the user over to
     the next sidebar menu ("Application Workshop"), which appears in the
     sidebar the moment the analysis passes.

Nothing here re-implements scoring: `POST /api/ats/analyze` is the single
source (one Gemini parse + the frozen deterministic engine + hard blockers).
*/

import { useRef, useState } from "react";
import Link from "next/link";
import { analyzeJob, type AtsResult } from "@/lib/ats";

/** Minimum length that can plausibly be a full job description (verification). */
const MIN_JD_CHARS = 200;

/** Multilingual "this really is a job description" signals (verification). */
const JD_SIGNALS = [
  "job", "role", "position", "title", "responsib", "requirement", "qualif",
  "experience", "skill", "company", "we offer", "contract", "mission", "task",
  "profil", "aufgabe", "kenntnis", "bewerbung", "poste", "compétence",
  "candidat", "offer", "team", "salary", "location",
];

/** Human label of each deterministic verdict band (frozen engine bands). */
const BAND_LABEL: Record<string, string> = {
  hard_reject: "below 70% - hard reject",
  soft_reject: "70-79% - not yet suitable",
  manual: "80-89% - borderline, your call",
  proceed: "90%+ - strong match",
  blockers: "hard blocker(s) present - blocked whatever the score",
};

// --- defensive readers over the parsed JSON (never throw, never invent) -----
function s(v: unknown): string {
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}
function strList(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => s(x)).filter(Boolean) : [];
}
function o(v: unknown): Record<string, unknown> {
  return v != null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}
function num(v: unknown): number {
  const value = Number(v);
  return Number.isFinite(value) ? value : 0;
}
/** ["German (C1)", "English (fluent)"] from a languages[] JSON value. */
function langNames(v: unknown): string[] {
  return Array.isArray(v)
    ? v
        .map((item) => {
          const entry = o(item);
          const name = s(entry.language) || s(item);
          return entry.level ? name + " (" + s(entry.level) + ")" : name;
        })
        .filter(Boolean)
    : [];
}
function countItems(v: unknown): number {
  return Array.isArray(v) ? v.length : 0;
}
export default function JobAnalyses({
  hasProfile,
  cvSummary,
  token,
  onPassed,
  onOpenWorkshop,
  onDiscardRun,
}: {
  hasProfile: boolean;
  /** What the score was computed against (from the caller's OWN profiles row). */
  cvSummary: { originals: number; careerStage: string; updatedAt: string } | null;
  token: string;
  /** (f) analysis PASSED: register the run (reveals ② in the sidebar). */
  onPassed: (jobText: string, result: AtsResult) => void;
  /** (f) the user took the decision: close ① and open ② Application Workshop. */
  onOpenWorkshop: () => void;
  /** The user abandoned the run (start a new analysis): hide ② again. */
  onDiscardRun: () => void;
}) {
  const [jobText, setJobText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
  const [softWarn, setSoftWarn] = useState("");
  const [result, setResult] = useState<AtsResult | null>(null);
  /** (f) set when a PASSED analysis has been closed by AIROS. */
  const [closed, setClosed] = useState(false);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const reset = () => {
    setResult(null);
    setJobText("");
    setErr("");
    setNotice("");
    setSoftWarn("");
    setClosed(false);
    // A fresh analysis abandons the current run: ② / ③ leave the sidebar again.
    onDiscardRun();
    requestAnimationFrame(() => taRef.current?.focus());
  };

  /** (b) deterministic pre-verification, before spending an AI call. */
  const verifyInput = (raw: string): string => {
    const text = raw.trim();
    if (!text) return "Paste the job description first.";
    if (text.length < MIN_JD_CHARS) {
      return (
        "AIROS could not verify this as a job description: only " +
        text.length +
        " characters pasted (a complete offer needs at least ~" +
        MIN_JD_CHARS +
        "). Paste the full JD."
      );
    }
    return "";
  };

  const looksLikeJd = (raw: string): boolean => {
    const text = raw.toLowerCase();
    return JD_SIGNALS.filter((signal) => text.includes(signal)).length >= 3;
  };

  const analyze = async () => {
    const problem = verifyInput(jobText);
    if (problem) {
      setErr(problem);
      return;
    }
    setSoftWarn(
      looksLikeJd(jobText)
        ? ""
        : "This text lacks the usual job-description markers (role, requirements, skills). AIROS still verifies it with the parser - if it cannot, the verdict is a safe NO, never a guess."
    );
    setBusy(true);
    setErr("");
    setNotice("");
    try {
      const res = await analyzeJob(jobText, token);
      if (!res.ok) {
        // Transport / API failure: NOT a verdict - keep the JD so it can be retried.
        setErr(res.detail);
        return;
      }
      setResult(res.result);
      if (res.result.verdict.proceed) {
        // (f) PASSED: register the run so "② Application Workshop" appears in the
        // sidebar right away; the report + the final decision stay on this page
        // until the user takes the decision at the bottom.
        setClosed(true);
        onPassed(jobText, res.result);
        return;
      }
      // (e) FAILED: state the decision and clear the JD zone for the next offer.
      setClosed(false);
      setJobText("");
      setNotice(
        res.result.parse_failed
          ? "AIROS could not verify this text as a job description (the parser extracted no requirements), so the final decision is a safe NO. The job-description field has been cleared - paste your next offer above."
          : "AIROS's final decision for this offer is NO. The job-description field has been cleared so the next offer can be pasted straight away - the full report stays below for review."
      );
      requestAnimationFrame(() => taRef.current?.focus());
    } finally {
      setBusy(false);
    }
  };

  const band = result?.verdict.band ?? "";
  const passed = result?.verdict.proceed === true;
  const parsedJob = o(result?.parsed_job);
  const parsedCv = o(result?.parsed_cv);
  const jobRequired = o(parsedJob.required_skills);
  const jobPreferred = o(parsedJob.preferred_skills);
  const cvSkills = o(parsedCv.skills);
  const recruiter = o(parsedJob.recruiter_contact);
  const jobLanguages = Array.isArray(parsedJob.languages) ? parsedJob.languages : [];
  const jobExperience = o(parsedJob.experience);
  const jobEducation = o(parsedJob.education);
  const jobLocation = o(parsedJob.location_requirements);
  const jobVisa = o(parsedJob.visa_sponsorship);
  const jobAuth = o(parsedJob.work_authorization);
  const bandBorder =
    band === "proceed" ? "border-ok" : band === "manual" ? "border-warn" : "border-danger";
  return (
    <div className="mt-4">
      {/* ---------------- (a) + (b) the JD zone ---------------- */}
      <div className="card">
        <h2 className="text-lg font-bold m-0">① Job Analyses</h2>
        <p className="text-sm text-muted mt-1 mb-0">
          Paste the full job description (a). AIROS verifies it and scores it against{" "}
          <b>your own CV / profile</b> (b); the complete report (c) and the final decision (d)
          follow below.
        </p>
        {!hasProfile && (
          <p className="text-sm text-warn mt-2 mb-0">
            You have no profile yet.{" "}
            <Link href="/profile" className="text-brand underline underline-offset-2">
              Build your profile first
            </Link>{" "}
            so the score can be computed against your real CV.
          </p>
        )}

        {closed ? (
          <div className="mt-3 rounded-lg border border-ok p-3">
            <p className="text-sm font-semibold text-ok m-0">
              ✅ Job analysis closed - this offer PASSED.
            </p>
            <p className="text-sm mt-1 mb-0">
              The Job Analyses step is finished and the <b>Application Workshop</b> is now open
              in the sidebar. Take the final decision at the bottom of this page, or start a
              fresh analysis for another offer.
            </p>
            <button type="button" className="btn-secondary text-sm mt-2" onClick={reset}>
              ↺ Start a new analysis
            </button>
          </div>
        ) : (
          <>
            <textarea
              ref={taRef}
              className="input w-full mt-3"
              rows={9}
              placeholder="Paste the full job description here (title, requirements, skills, languages, visa notes...)..."
              value={jobText}
              onChange={(e) => setJobText(e.target.value)}
              disabled={busy}
            />
            <div className="flex items-center justify-between flex-wrap gap-2 mt-1">
              <span className="text-xs text-muted">
                {jobText.trim().length} characters pasted (minimum ~{MIN_JD_CHARS})
              </span>
              {notice !== "" && (
                <span className="text-xs text-danger">field cleared for the next offer</span>
              )}
            </div>
            <button type="button" onClick={analyze} className="btn-primary mt-2" disabled={busy}>
              {busy ? "Verifying & scoring the offer..." : "Verify & score this JD against my CV"}
            </button>
            {busy && (
              <p className="text-xs text-muted mt-2 mb-0">
                One AI call for the JD parse + deterministic scoring - a few seconds.
              </p>
            )}
          </>
        )}

        {err !== "" && (
          <p role="alert" className="text-danger text-sm mt-2 mb-0">
            {err}
          </p>
        )}
        {softWarn !== "" && <p className="text-xs text-warn mt-2 mb-0">{softWarn}</p>}
        {notice !== "" && (
          <p role="status" className="text-sm text-warn mt-2 mb-0">
            {notice}
          </p>
        )}
        <p className="text-xs text-muted mt-3 mb-0">
          Verdict thresholds: &lt;70 hard reject | 70-79 strengthen | 80-89 your call | 90+ strong
          match. A hard blocker always forces NO.
        </p>
      </div>

      {result != null && <><div className={"card mt-4 border " + bandBorder}>
        <h3 className="m-0 text-sm font-semibold">
          (c) Analysis report - ATS &amp; compatibility score
        </h3>
        <div className="flex items-center gap-3 flex-wrap mt-3">
          <div className="text-3xl font-bold">{result.ats_score}%</div>
          <div className="flex flex-col">
            <span className="text-sm font-semibold">{result.decision}</span>
            <span className="text-xs text-muted">
              verdict band: {BAND_LABEL[band] ?? band}
            </span>
          </div>
        </div>
        <p className="text-sm text-muted mt-2 mb-0">
          {s(parsedJob.job_title) || "(job title not stated in the JD)"}
          {s(parsedJob.company_name) ? " · " + s(parsedJob.company_name) : ""}
          {s(parsedJob.location) ? " · " + s(parsedJob.location) : ""}
        </p>
        {result.parse_failed === true && (
          <div className="rounded-lg border border-danger p-3 mt-3">
            <p className="text-sm font-semibold text-danger m-0">
              ⚠ AIROS could not verify this text as a job description
            </p>
            <p className="text-sm mt-1 mb-0">
              The parser extracted no requirements from the pasted text, so no reliable score
              exists. The verdict is a safe NO - never a guess.
            </p>
          </div>
        )}
        <div className="mt-3">
          {s(result.verdict.title) !== "" && (
            <p className="text-sm font-semibold m-0">{result.verdict.title}</p>
          )}
          <p className="text-sm mt-2 mb-0">{result.verdict.message}</p>
          {s(result.verdict.next_step) !== "" && (
            <p className="text-xs text-muted mt-2 mb-0">
              Next step: {result.verdict.next_step}
            </p>
          )}
        </div>
        {s(result.visa_note) !== "" && (
          <p className="text-sm text-ok mt-2 mb-0">{result.visa_note}</p>
        )}
        {result.hard_blockers.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-semibold text-danger m-0">Hard blockers</p>
            <ul className="text-sm mt-1 mb-0 pl-5">
              {result.hard_blockers.map((b, i) => (
                <li key={i}>
                  <b>{b}</b>
                  {result.blocker_explanations[i] ? " — " + result.blocker_explanations[i] : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">
          What AIROS compared - your CV / profile against this offer
        </h3>
        <div
          className="grid gap-4 mt-3"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))" }}
        >
          <div>
            <p className="text-xs font-semibold text-brand m-0">Your CV / profile</p>
            <ul className="text-sm mt-1 mb-0 pl-5">
              <li>
                Original CV file(s) on record:{" "}
                <b>{cvSummary != null ? cvSummary.originals : "not loaded"}</b>
              </li>
              <li>
                Career stage: <b>{cvSummary?.careerStage || "not set"}</b>
              </li>
              <li>
                Profile last updated: <b>{s(cvSummary?.updatedAt).slice(0, 10) || "unknown"}</b>
              </li>
              <li>
                Skills: <b>{countItems(cvSkills.technical)}</b> technical,{" "}
                <b>{countItems(cvSkills.methodologies)}</b> methodologies,{" "}
                {countItems(cvSkills.tools)} tools
              </li>
              <li>
                Languages: <b>{langNames(parsedCv.languages).join(", ") || "none recorded"}</b>
              </li>
              <li>
                Experience entries: <b>{countItems(parsedCv.experience)}</b> · Education:{" "}
                <b>{countItems(parsedCv.education)}</b> · Certifications:{" "}
                <b>{countItems(parsedCv.certifications)}</b>
              </li>
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold text-brand m-0">This job offer (parsed by AIROS)</p>
            <ul className="text-sm mt-1 mb-0 pl-5">
              <li>
                Title: <b>{s(parsedJob.job_title) || "-"}</b>
              </li>
              <li>
                Company: <b>{s(parsedJob.company_name) || "-"}</b>
              </li>
              <li>
                Location: <b>{s(parsedJob.location) || "-"}</b>
                {s(parsedJob.country) ? " (" + s(parsedJob.country) + ")" : ""}
              </li>
              <li>
                Industry / seniority: <b>{s(parsedJob.industry) || "-"}</b> /{" "}
                <b>{s(parsedJob.seniority_level) || "-"}</b>
              </li>
              <li>
                Experience asked:{" "}
                <b>
                  {num(jobExperience.min_years) > 0
                    ? num(jobExperience.min_years) + "+ years"
                    : "-"}
                </b>
                {num(jobExperience.preferred_years) > 0
                  ? " (preferred " + num(jobExperience.preferred_years) + "+)"
                  : ""}
              </li>
              <li>
                Degree asked: <b>{s(jobEducation.min_degree) || "-"}</b>
              </li>
              <li>
                Languages required: <b>{langNames(parsedJob.languages).join(", ") || "-"}</b>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">The offer as AIROS read it (full parse)</h3>
        {jobLanguages.length > 0 && (
          <p className="text-sm mt-2 mb-0">
            <b>Languages:</b>{" "}
            {jobLanguages
              .map((l) => {
                const entry = o(l);
                const name = s(entry.language);
                if (!name) return "";
                const level = s(entry.level);
                const req = entry.required === true ? "required" : "preferred";
                return name + (level ? " " + level : "") + " (" + req + ")";
              })
              .filter(Boolean)
              .join(" · ")}
          </p>
        )}
        <div
          className="grid gap-4 mt-3"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}
        >
          {(["technical", "methodologies", "tools"] as const).map((key) => (
            <div key={"req-" + key}>
              <p className="text-xs font-semibold m-0">Required {key}</p>
              <p className="text-sm mt-1 mb-0 break-words">
                {strList(jobRequired[key]).join(", ") || "not stated"}
              </p>
            </div>
          ))}
        </div>
        <div
          className="grid gap-4 mt-3"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}
        >
          {(["technical", "methodologies", "tools"] as const).map((key) => (
            <div key={"pref-" + key}>
              <p className="text-xs font-semibold m-0">Preferred {key}</p>
              <p className="text-sm mt-1 mb-0 break-words">
                {strList(jobPreferred[key]).join(", ") || "not stated"}
              </p>
            </div>
          ))}
        </div>
        <p className="text-sm mt-3 mb-0">
          <b>Certifications asked:</b>{" "}
          {strList(parsedJob.certifications).join(", ") || "none stated"}
        </p>
        <p className="text-sm mt-1 mb-0">
          <b>Preferred degree fields:</b>{" "}
          {strList(jobEducation.preferred_fields).join(", ") || "none stated"}
        </p>
        <p className="text-sm mt-1 mb-0">
          <b>Work arrangement:</b>{" "}
          {[
            jobLocation.remote === true ? "remote" : "",
            jobLocation.hybrid === true ? "hybrid" : "",
            jobLocation.on_site === true ? "on-site" : "",
          ]
            .filter(Boolean)
            .join(" / ") || "not stated"}
          {strList(jobLocation.cities_or_countries).length > 0
            ? " · " + strList(jobLocation.cities_or_countries).join(", ")
            : ""}
          {s(jobLocation.relocation_support)
            ? " · relocation: " + s(jobLocation.relocation_support)
            : ""}
        </p>
        <p className="text-sm mt-1 mb-0">
          <b>Visa / sponsorship:</b> {s(jobVisa.support) || "not mentioned"}
          {s(jobVisa.evidence) ? " — " + s(jobVisa.evidence) : ""}
        </p>
        <p className="text-sm mt-1 mb-0">
          <b>Right to work:</b> {s(jobAuth.requirement) || "not mentioned"}
          {s(jobAuth.evidence) ? " — " + s(jobAuth.evidence) : ""}
        </p>
        {strList(parsedJob.responsibilities).length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-semibold m-0">Responsibilities read from the JD</p>
            <ul className="text-sm mt-1 mb-0 pl-5">
              {strList(parsedJob.responsibilities)
                .slice(0, 8)
                .map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
            </ul>
          </div>
        )}
        {strList(parsedJob.keywords).length > 0 && (
          <p className="text-xs text-muted mt-3 mb-0">
            <b>Keywords:</b> {strList(parsedJob.keywords).slice(0, 20).join(", ")}
          </p>
        )}
      </div>

<div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">Component scores (deterministic engine)</h3>
        <div
          className="grid gap-3 mt-3"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}
        >
          {Object.entries(result.sub_scores).map(([k, v]) => (
            <div key={k} className="rounded-lg border border-border p-3 text-center">
              <div className="text-lg font-bold">{Math.round(num(v))}%</div>
              <div className="text-xs text-muted mt-1">{k.replace(/_/g, " ")}</div>
            </div>
          ))}
        </div>
        <div
          className="grid gap-3 mt-4"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}
        >
          <div>
            <p className="text-xs font-semibold text-ok m-0">
              ✅ Strengths matched in your profile ({result.gap_analysis.strengths.length})
            </p>
            <p className="text-sm mt-1 mb-0 break-words">
              {result.gap_analysis.strengths.length > 0
                ? result.gap_analysis.strengths.join(", ")
                : "No strong matches detected."}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold text-danger m-0">
              ❌ Missing / gaps ({result.gap_analysis.missing.length})
            </p>
            <p className="text-sm mt-1 mb-0 break-words">
              {result.gap_analysis.missing.length > 0
                ? result.gap_analysis.missing.join(", ")
                : "No significant gaps detected."}
            </p>
          </div>
        </div>
      </div>

      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">
          Evidence the engine used (why each point was credited)
        </h3>
        {result.evidence.length === 0 ? (
          <p className="text-sm text-muted mt-2 mb-0">
            No evidence rows were recorded for this comparison.
          </p>
        ) : (
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-border">
                  <th className="py-2 pr-3">Item</th>
                  <th className="py-2 pr-3">Category</th>
                  <th className="py-2 pr-3">Evidence</th>
                  <th className="py-2 pr-3">Source in your CV</th>
                </tr>
              </thead>
              <tbody>
                {result.evidence.slice(0, 30).map((e, i) => (
                  <tr key={i} className="border-b border-border">
                    <td className="py-2 pr-3 font-medium">{e.item}</td>
                    <td className="py-2 pr-3">{e.category}</td>
                    <td className="py-2 pr-3">{e.stars || "level " + String(e.level)}</td>
                    <td className="py-2 pr-3 break-words">{e.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {result.evidence.length > 30 && (
          <p className="text-xs text-muted mt-2 mb-0">
            Showing the first 30 of {result.evidence.length} evidence rows.
          </p>
        )}
      </div>

      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">Recruiter (RH) found in this offer</h3>
        {s(recruiter.name) !== "" || s(recruiter.email) !== "" ? (
          <p className="text-sm mt-2 mb-0">
            <b>{s(recruiter.name) || "(no name stated)"}</b>
            {s(recruiter.position) ? " — " + s(recruiter.position) : ""}
            {s(recruiter.email) ? " · " + s(recruiter.email) : " · no email"}
            {s(recruiter.phone) ? " · " + s(recruiter.phone) : ""}
            <br />
            It will be prefilled in the save step of the Application Workshop — verify before
            saving.
          </p>
        ) : (
          <p className="text-sm text-muted mt-2 mb-0">
            No individual recruiter could be read from this offer (only generic addresses or
            none). One can be added manually in the save step.
          </p>
        )}
      </div>
</>}

      {result != null && <><div className={"card mt-4 border-2 " + (passed ? "border-ok" : "border-danger")}>
        <p className="text-xs uppercase tracking-wide text-muted m-0">(d) Final decision</p>
        <h3 className={"text-xl font-bold m-0 " + (passed ? "text-ok" : "text-danger")}>
          {passed ? "✅ PASS - proceed with this offer" : "❌ NO - do not proceed with this offer"}
        </h3>
        <p className="text-sm text-muted mt-1 mb-0">
          ATS &amp; compatibility score <b>{result.ats_score}%</b> · {result.decision} · band:{" "}
          {BAND_LABEL[band] ?? band}
        </p>
        {passed ? (
          <>
            <p className="text-sm mt-3 mb-0">
              {band === "manual"
                ? "This role is near your bar, so the decision is yours to make. Continue and AIROS closes this analysis and opens the Application Workshop for this offer."
                : "This role is a strong match. Continue and AIROS closes this analysis and opens the Application Workshop for this offer."}
            </p>
            <div className="flex gap-2 mt-3 flex-wrap">
              <button
                type="button"
                className="btn-primary"
                onClick={() => onOpenWorkshop()}
              >
                Close the job analysis &amp; open the Application Workshop →
              </button>
              <button type="button" className="btn-secondary" onClick={reset}>
                ↺ Start a new analysis
              </button>
              <Link href="/profile" className="btn-secondary">
                Improve my profile
              </Link>
            </div>
            <p className="text-xs text-muted mt-2 mb-0">
              The <b>Application Workshop</b> menu is already visible in the sidebar; the analysis
              is closed as soon as you continue.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm mt-3 mb-0">{result.verdict.message}</p>
            {band === "blockers" ? (
              <p className="text-sm mt-2 mb-0">
                Resolve the hard blocker(s) listed in the report above (they are non-negotiable for
                this offer) and re-analyse it later, or move to an offer without them.
              </p>
            ) : band === "soft_reject" ? (
              <p className="text-sm mt-2 mb-0">
                Close the gaps shown in the component scores, then re-analyse this offer, or pick an
                offer closer to your strongest skills.
              </p>
            ) : (
              <p className="text-sm mt-2 mb-0">
                This offer is below your 70% bar. Pick an offer closer to your strongest skills and
                experience level.
              </p>
            )}
            <p className="text-sm text-danger mt-2 mb-0">
              The job-description field at the top of this page has been cleared and is ready for
              your next offer; the report above stays visible for review until something new is
              pasted.
            </p>
            <div className="flex gap-2 mt-3 flex-wrap">
              <button type="button" className="btn-secondary" onClick={reset}>
                ↺ Clear this report &amp; start a new analysis
              </button>
              <Link href="/profile" className="btn-secondary">
                Improve my profile
              </Link>
            </div>
          </>
        )}
      </div></>}
    </div>
  );
}


