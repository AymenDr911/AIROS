"use client";
/* AIROS V3 - ② Application Workshop menu (CHG-025).

The menu that APPEARS in the sidebar the moment the ① Job Analyses verdict
PASSES (user request, 15 Sep 2026) and the screen AIROS hands the user over
to. It shows the passed analysis and opens the rest of the run:
  - App Workspace / Preparation: save the offer (company + recruiter) and
    generate the tailored CV / cover letter / recruiter email, then confirm;
  - Job Tracking: the confirmed applications and their manual lifecycle;
  - another offer: close this run and score a fresh JD.

NOTE: the detailed workshop content is the next backlog topic. This file
deliberately stays a thin, honest hub so nothing outside the approved scope is
invented here.
*/

import { type PendingAnalysis } from "@/lib/workspace";

function s(v: unknown): string {
  return typeof v === "string" ? v : "";
}
function o(v: unknown): Record<string, unknown> {
  return v != null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

export default function ApplicationWorkshop({
  run,
  tracked,
  onOpenPreparation,
  onOpenTracking,
  onNewAnalysis,
}: {
  run: PendingAnalysis | null;
  tracked: number;
  onOpenPreparation: () => void;
  onOpenTracking: () => void;
  onNewAnalysis: () => void;
}) {
  if (run == null) {
    return (
      <div className="card mt-4">
        <h2 className="text-lg font-bold m-0">② Application Workshop</h2>
        <p className="text-sm text-muted mt-1 mb-0">
          This menu opens automatically the moment a job analysis PASSES. Score an offer in{" "}
          <b>① Job Analyses</b> first.
        </p>
      </div>
    );
  }

  const analysis = run.analysis;
  const job = o(analysis.parsed_job);

  return (
    <div className="mt-4">
      <div className="card border border-ok">
        <h2 className="text-lg font-bold m-0">② Application Workshop</h2>
        <p className="text-sm mt-1 mb-0">
          ✅ The job analysis for this offer PASSED - the Job Analyses step is closed and the run
          continues here.
        </p>
        <div className="flex items-center gap-3 flex-wrap mt-3">
          <div className="text-3xl font-bold text-ok">{analysis.ats_score}%</div>
          <div className="flex flex-col">
            <span className="text-sm font-semibold">
              {s(job.job_title) || "(job title not stated in the JD)"}
            </span>
            <span className="text-xs text-muted">
              {s(job.company_name) || "company not stated"}
              {s(job.location) ? " · " + s(job.location) : ""} · {analysis.decision} · band{" "}
              {analysis.verdict.band}
            </span>
          </div>
        </div>
        <p className="text-sm mt-3 mb-0">{analysis.verdict.message}</p>
      </div>

      <div
        className="grid gap-3 mt-4"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}
      >
        <div className="card">
          <h3 className="m-0 text-sm font-semibold">🗂️ App Workspace / Preparation</h3>
          <p className="text-sm text-muted mt-1 mb-0">
            Save this offer (company + recruiter), generate the tailored CV, cover letter and
            recruiter email, then confirm the application.
          </p>
          <button type="button" className="btn-primary mt-3" onClick={onOpenPreparation}>
            Open the workspace →
          </button>
        </div>
        <div className="card">
          <h3 className="m-0 text-sm font-semibold">📈 Job Tracking</h3>
          <p className="text-sm text-muted mt-1 mb-0">
            {tracked > 0
              ? tracked + " application(s) tracked - follow them up manually here."
              : "Available once an application has been confirmed."}
          </p>
          <button
            type="button"
            className="btn-secondary mt-3"
            onClick={onOpenTracking}
            disabled={tracked === 0}
          >
            Open tracking →
          </button>
        </div>
        <div className="card">
          <h3 className="m-0 text-sm font-semibold">🔍 Another offer</h3>
          <p className="text-sm text-muted mt-1 mb-0">
            Go back to ① Job Analyses and score a different job description.
          </p>
          <button type="button" className="btn-secondary mt-3" onClick={onNewAnalysis}>
            Start a new analysis
          </button>
        </div>
      </div>

      <p className="text-xs text-muted mt-3 mb-0">
        The job description behind this verdict is kept for the whole run, so the documents are
        always generated from the very same text you were scored against.
      </p>
    </div>
  );
}
