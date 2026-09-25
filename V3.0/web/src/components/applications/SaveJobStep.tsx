"use client";
/* AIROS V3 - Save the analyzed job (CHG-018, V2 `_render_save_section` parity).
   After a passing ATS verdict the user sees the parsed company card, optionally
   adds the recruiter/HR contact, and saves the analyzed JD as Job + Company +
   Contact via POST /api/applications/jobs (V2 save_job + add_contact_to_job). */
import { useState } from "react";
import { saveAnalyzedJob, type JobContact, type SaveJobResult } from "@/lib/applications";
import type { AtsResult } from "@/lib/ats";

const CONTACT_TYPES = ["HR Recruiter", "Talent Acquisition", "Hiring Manager", "General"];
const CONFIDENCE_LEVELS = ["High", "Medium", "Low"];

type Props = {
  analysis: AtsResult;
  originalJd: string;
  token: string;
  onSaved: (saved: SaveJobResult) => void;
  onCancel: () => void;
};

/** Normalized analysis payload for the backend: strengths/gaps must be LISTS
    (AtsResult.gap_analysis is {missing, strengths} for the UI). */
function backendAnalysis(a: AtsResult): Record<string, unknown> {
  return {
    ats_score: a.ats_score,
    overall_ats: a.overall_ats,
    decision: a.decision,
    sub_scores: a.sub_scores,
    evidence: a.evidence,
    verdict: a.verdict,
    parsed_job: a.parsed_job,
    gap_analysis: a.gap_analysis?.missing ?? [],
    gaps: a.gap_analysis?.missing ?? [],
    hits: a.gap_analysis?.strengths ?? [],
    strengths: a.gap_analysis?.strengths ?? [],
  };
}

const str = (v: unknown): string => (v == null ? "" : String(v));

export default function SaveJobStep({ analysis, originalJd, token, onSaved, onCancel }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // Migration-0008 resilience (CHG-024): when a column is missing on the live
  // DB the backend saves what it can and returns schema_warning - shown here,
  // never silently dropped.
  const [schemaWarn, setSchemaWarn] = useState("");
  const pj = (analysis.parsed_job ?? {}) as Record<string, unknown>;
  // RH prefill: when the JD itself names the recruiter (parsed recruiter_contact),
  // prefill the form so "RH defined in JD" is saved instead of silently dropped.
  // The user can still edit/clear before saving (manual contact wins when filled).
  const prefill = (pj.recruiter_contact ?? {}) as Record<string, unknown>;
  const [contact, setContact] = useState<JobContact>({
    name: str(prefill.name),
    position: str(prefill.position),
    email: str(prefill.email),
    phone: str(prefill.phone),
    linkedin_url: str(prefill.linkedin_url),
    contact_type: "HR Recruiter",
    confidence: "Medium",
  });
  const set = (k: keyof JobContact) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setContact((c) => ({ ...c, [k]: e.target.value }));

  const filled = (c: JobContact): boolean =>
    [c.name, c.email, c.linkedin_url, c.position].some((v) => String(v ?? "").trim() !== "");

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      const saved = await saveAnalyzedJob(token, {
        analysis: backendAnalysis(analysis),
        original_jd: originalJd,
        contact: filled(contact) ? contact : undefined,
      });
      setSchemaWarn(saved.schema_warning ?? "");
      onSaved(saved);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 border-t border-border pt-4">
      <h3 className="m-0 text-sm font-semibold">Company &amp; Recruiter</h3>
      <p className="text-xs text-muted mt-1 mb-0">
        Review the company parsed from the offer, add the individual recruiter if known, then save
        the job to continue to the application preparation flow.
      </p>

      <div className="rounded-lg border border-border p-3 mt-3">
        <p className="text-xs font-semibold text-muted m-0">🏢 Company</p>
        <div className="grid gap-2 mt-2 text-sm" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
          <div><span className="text-muted text-xs">Name</span><div className="font-medium">{str(pj.company_name) || "—"}</div></div>
          <div><span className="text-muted text-xs">City / Location</span><div className="font-medium">{str(pj.city) || str(pj.location) || "—"}</div></div>
          <div><span className="text-muted text-xs">Country</span><div className="font-medium">{str(pj.country) || "—"}</div></div>
          <div><span className="text-muted text-xs">Address</span><div className="font-medium">{str(pj.address) || "—"}</div></div>
          <div><span className="text-muted text-xs">Industry</span><div className="font-medium">{str(pj.industry) || "—"}</div></div>
          <div><span className="text-muted text-xs">Phone</span><div className="font-medium">{str(pj.company_phone) || "—"}</div></div>
          <div><span className="text-muted text-xs">Website</span><div className="font-medium break-all">{str(pj.company_website) || "—"}</div></div>
          <div><span className="text-muted text-xs">LinkedIn</span><div className="font-medium break-all">{str(pj.company_linkedin) || "—"}</div></div>
        </div>
      </div>

      <div className="rounded-lg border border-border p-3 mt-3">
        <p className="text-xs font-semibold text-muted m-0">👤 Recruiter / Contact</p>
        <p className="text-xs text-muted mt-1 mb-0">
          Generic emails (info@, careers@, jobs@ …) are automatically treated as low-confidence.
          {str(prefill.name) || str(prefill.email)
            ? " — prefilled from the job description; verify before saving."
            : " — not found in the job description; add the individual recruiter if known."}
        </p>
        <div className="grid gap-2 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <label className="text-sm">
            <span className="text-xs text-muted">Name</span>
            <input className="input w-full" placeholder="Anna Müller" value={contact.name ?? ""} onChange={set("name")} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Position</span>
            <input className="input w-full" placeholder="Senior Talent Acquisition" value={contact.position ?? ""} onChange={set("position")} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Email</span>
            <input className="input w-full" type="email" placeholder="anna.mueller@company.com" value={contact.email ?? ""} onChange={set("email")} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Phone</span>
            <input className="input w-full" type="tel" placeholder="+32 470 12 34 56" value={contact.phone ?? ""} onChange={set("phone")} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">LinkedIn URL</span>
            <input className="input w-full" placeholder="https://linkedin.com/in/..." value={contact.linkedin_url ?? ""} onChange={set("linkedin_url")} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Contact Type</span>
            <select className="input w-full" value={contact.contact_type ?? "HR Recruiter"} onChange={set("contact_type")}>
              {CONTACT_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Confidence</span>
            <select className="input w-full" value={contact.confidence ?? "Medium"} onChange={set("confidence")}>
              {CONFIDENCE_LEVELS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {schemaWarn && (
        <p role="status" className="text-warn text-sm mt-2 mb-0">⚠️ {schemaWarn}</p>
      )}
      {err && (
        <p role="alert" className="text-danger text-sm mt-2 mb-0">{err}</p>
      )}

      <div className="flex gap-2 mt-4 flex-wrap">
        <button type="button" className="btn-primary" onClick={save} disabled={busy}>
          {busy ? "Saving the job + company..." : "💾 Save Job + Company + Recruiter"}
        </button>
        <button type="button" className="btn-secondary" onClick={onCancel} disabled={busy}>
          Back to the verdict
        </button>
      </div>
    </div>
  );
}