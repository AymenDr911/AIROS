"use client";
/* AIROS V3 - Application Preparation (CHG-018, V2 page 4 parity).
   Receives a saved job (Job + Company + Contact snapshot) and drives the
   post-ATS preparation flow: job summary, company review, recruiter status
   (reliable-contact detection), the ONE-call document engine with
   post-generation validation, and Confirm Application (sent -> tracking
   record APPLIED; cancelled -> no record). */
import { useState } from "react";
import {
  addJobContact,
  confirmApplication,
  downloadDocumentFile,
  downloadDocumentText,
  generateDocuments,
  type DocumentFormat,
  type DocsResult,
  type JobContact,
  type RenderedDocumentReport,
  type SaveJobResult,
} from "@/lib/applications";

const GENERIC_PREFIXES = ["info@", "contact@", "careers@", "jobs@", "hr@", "hello@", "recruitment@", "noreply@"];
const CONTACT_TYPES = ["HR Recruiter", "Talent Acquisition", "Hiring Manager", "General"];
const CONFIDENCE_LEVELS = ["High", "Medium", "Low"];
const CHANNELS = [
  "Job Platform (LinkedIn)",
  "Job Platform (StepStone)",
  "Job Platform (Indeed)",
  "Job Platform (Other)",
  "Company Career Site",
  "Direct Email to Recruiter",
  "LinkedIn Easy Apply",
  "Referral",
];

const str = (v: unknown): string => (v == null ? "" : String(v));

/** V2 reliable-contact rule: individual email + High/Medium confidence. */
function reliableContact(c: Record<string, unknown> | null | undefined): Record<string, unknown> | null {
  if (!c) return null;
  const email = str(c.email).trim().toLowerCase();
  if (!email || GENERIC_PREFIXES.some((p) => email.startsWith(p))) return null;
  const conf = str(c.confidence).toLowerCase();
  return conf === "high" || conf === "medium" ? c : null;
}

type Props = {
  jobId: string;
  saved: SaveJobResult;
  token: string;
  onConfirmed: (applicationId: string) => void;
  onBack: () => void;
};

export default function PrepareTab({ jobId, saved, token, onConfirmed, onBack }: Props) {
  const job = saved.job ?? {};
  const company = saved.company ?? {};
  const [contacts, setContacts] = useState<Record<string, unknown>[]>(
    saved.contact ? [saved.contact] : []
  );
  // Reliable RH contact: prefer the saved contact, else any contact added
  // later in this session (addJobContact appends to `contacts`). The old
  // code only looked at contacts[0] — which is the FIRST contact — so a
  // recruiter added after a generic one never became the reliable one.
  const reliable =
    reliableContact(saved.contact) ??
    contacts.map((c) => reliableContact(c)).find((c) => c != null) ??
    null;

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  // --- document engine ---------------------------------------------------
  const [docs, setDocs] = useState<DocsResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [docErr, setDocErr] = useState("");

  // --- confirm -----------------------------------------------------------
  const [decision, setDecision] = useState<"sent" | "cancelled">("sent");
  const [channel, setChannel] = useState(CHANNELS[0]);
  const [appDate, setAppDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");

  // --- manual recruiter form ---------------------------------------------
  const [showAddContact, setShowAddContact] = useState(!reliable);
  const [manContact, setManContact] = useState<JobContact>({
    name: "", position: "", email: "", linkedin_url: "",
    contact_type: "HR Recruiter", confidence: "Medium",
  });
  const manSet = (k: keyof JobContact) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setManContact((c) => ({ ...c, [k]: e.target.value }));

  const generate = async () => {
    setGenerating(true);
    setDocErr("");
    try {
      const result = await generateDocuments(token, jobId, {
        generate_cv: true,
        generate_cover_letter: true,
        // No reliable individual recruiter email -> the RH mailing feature is
        // cleanly removed, the CV + cover letter generation is NOT blocked.
        generate_recruiter_email: reliable != null,
      });
      setDocs(result);
    } catch (e) {
      const msg = (e as Error).message || "Unknown error";
      // Browser-level fetch failures surface as terse messages ("Load failed"
      // in Safari, "Failed to fetch" in Chrome) that say nothing about the
      // backend. Turn them into an actionable hint so the user can fix the
      // cause instead of retrying blindly.
      if (/failed to fetch|load failed|network|connection|econnrefused|econnreset|timeout/i.test(msg)) {
        setDocErr(
          "Could not reach the document-generation backend (network error: " +
            msg +
            "). Start the API server (python3 -m uvicorn services.api.main:app --port 8001) " +
            "from V3.0/ and make sure it is reachable from this browser, then retry.",
        );
      } else {
        setDocErr(msg);
      }
    } finally {
      setGenerating(false);
    }
  };

  const download = async (docId: unknown) => {
    const id = str(docId);
    if (!id) return;
    try {
      const text = await downloadDocumentText(token, id);
      const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = id + ".txt";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDocErr((e as Error).message);
    }
  };

  /** CHG-026: download a ready-to-send rendition (DOCX | PDF) of a document. */
  const downloadRendition = async (docId: unknown, format: DocumentFormat) => {
    const id = str(docId);
    if (!id) return;
    try {
      const { blob, filename } = await downloadDocumentFile(token, id, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setDocErr((e as Error).message);
    }
  };

  /** Download buttons for one document: ready-to-send DOCX (and PDF when the
      server can convert it), with the plain text kept as a fallback. */
  const RenditionButtons = ({ docId, label }: { docId: unknown; label: string }) => {
    const id = str(docId);
    if (!id) return null;
    return (
      <span className="flex gap-2 flex-wrap items-center">
        <button
          type="button"
          className="btn-primary"
          onClick={() => downloadRendition(id, "docx")}
          title={`Download ${label} as a formatted, ready-to-send Word document`}
        >
          ⬇️ {label} (DOCX)
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => downloadRendition(id, "pdf")}
          title={`Download ${label} as a formatted, ready-to-send PDF`}
        >
          ⬇️ {label} (PDF)
        </button>
        <button
          type="button"
          className="btn-secondary text-xs"
          onClick={() => download(id)}
          title="Plain text fallback (Bloc-notes style)"
        >
          TXT
        </button>
      </span>
    );
  };

  /** CHG-026 rendering outcome for one document (QA + availability). */
  const RenderingStatus = ({ report, label }: { report: RenderedDocumentReport | undefined; label: string }) => {
    if (!report) return null;
    const errors = (report.errors ?? []).filter(
      (message) => !/^pdf: LibreOffice is not available/.test(message),
    );
    const pdfNote = (report.errors ?? []).find((message) =>
      /^pdf: LibreOffice is not available/.test(message),
    );
    return (
      <p className="text-xs mt-1 mb-0">
        {report.ok ? (
          <span className="text-ok">✅ {label} formatting QA passed — DOCX ready to send.</span>
        ) : errors.length > 0 ? (
          <span className="text-warn">
            ⚠️ {label} formatting notice: {errors.join(" · ")} (your text content is untouched
            below; no regeneration was triggered).
          </span>
        ) : (
          <span className="text-muted">{label}: rendered.</span>
        )}
        {pdfNote && (
          <span className="text-muted"> — {pdfNote.replace(/^pdf: /, "")}</span>
        )}
      </p>
    );
  };


  const addContact = async () => {
    if (!str(manContact.name).trim() && !str(manContact.email).trim()) {
      setErr("Please provide at least a name or an email for the recruiter.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const result = await addJobContact(token, jobId, manContact);
      setContacts((list) => [...list, result.contact]);
      setShowAddContact(false);
      setManContact({ name: "", position: "", email: "", linkedin_url: "", contact_type: "HR Recruiter", confidence: "Medium" });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const doConfirm = async () => {
    setBusy(true);
    setErr("");
    try {
      const result = await confirmApplication(token, {
        job_id: jobId,
        decision,
        channel: decision === "sent" ? channel : "",
        application_date: decision === "sent" ? appDate : "",
        notes,
      });
      if (result.created && result.application_id) {
        onConfirmed(result.application_id);
      } else {
        onBack();
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const atsComponents = (job.ats_components ?? {}) as Record<string, unknown>;
  const strengths = Array.isArray(job.strengths) ? job.strengths : [];
  const gaps = Array.isArray(job.gap_analysis) ? job.gap_analysis : [];
  const validation = docs?.validation ?? {};
  const atsRecalc = (validation.ats_recalculation ?? {}) as Record<string, unknown>;
  const generated = docs?.generated ?? {};
  const cv = (generated.cv ?? {}) as Record<string, unknown>;
  const coverLetter = (generated.cover_letter ?? {}) as Record<string, unknown>;
  const rendering = docs?.rendering;
  const email = (generated.recruiter_email ?? {}) as Record<string, unknown>;

  // --- post-generation validation derived view (objective ATS re-score) -----
  const scoreStatus = str(validation.status);
  const statusLabels: Record<string, string> = {
    improved: "Improved",
    marginal: "Marginal gain",
    regressed: "Regressed",
    unchanged: "Unchanged",
  };
  const statusLabel = statusLabels[scoreStatus] ?? (str(validation.status) || "—");
  const statusClass =
    scoreStatus === "improved"
      ? "text-ok"
      : scoreStatus === "marginal"
        ? "text-warn"
        : scoreStatus === "regressed"
          ? "text-danger"
          : "text-muted";
  const impValue = Number(validation.improvement) || 0;
  const recalcSub = (atsRecalc.sub_scores ?? {}) as Record<string, unknown>;
  const recalcGaps = (atsRecalc.gap_analysis ?? {}) as Record<string, unknown>;
  const recalcMatched = Array.isArray(recalcGaps.strengths) ? (recalcGaps.strengths as string[]) : [];
  const recalcRemaining = Array.isArray(recalcGaps.missing) ? (recalcGaps.missing as string[]) : [];

  return (
    <div className="mt-4 space-y-4">
      {err && <p role="alert" className="text-danger text-sm m-0">{err}</p>}
      {docErr && <p role="alert" className="text-danger text-sm m-0">{docErr}</p>}

      {/* ---------------- 1. Job summary ---------------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Job Summary</h3>
        <div className="grid gap-3 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
          <div><span className="text-xs text-muted">Job Title</span><div className="font-medium">{str(job.title) || "—"}</div></div>
          <div><span className="text-xs text-muted">ATS Score</span><div className="font-medium">{str(job.ats_score)}%</div></div>
          <div><span className="text-xs text-muted">Recommendation</span><div className="font-medium">{str(job.recommendation) || "—"}</div></div>
          <div><span className="text-xs text-muted">Company</span><div className="font-medium">{str(company.name) || str(job.company_id) || "—"}</div></div>
          <div><span className="text-xs text-muted">Location</span><div className="font-medium">{str(job.location) || "—"} · {str(job.country) || "—"}</div></div>
          <div><span className="text-xs text-muted">Source</span><div className="font-medium">{str(job.source) || "—"}</div></div>
        </div>

        {Object.keys(atsComponents).length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-semibold text-muted m-0">Component scores</p>
            <div className="grid gap-2 mt-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}>
              {Object.entries(atsComponents).map(([k, v]) => (
                <div key={k} className="rounded-lg border border-border p-2 text-center">
                  <div className="text-base font-bold">{Math.round(Number(v) || 0)}%</div>
                  <div className="text-xs text-muted mt-1">{k.replace(/_/g, " ")}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="grid gap-3 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
          <div>
            <p className="text-xs font-semibold text-ok m-0">✅ Strengths</p>
            <p className="text-sm mt-1 mb-0 break-words">{strengths.length ? strengths.join(", ") : "No strong matches detected."}</p>
          </div>
          <div>
            <p className="text-xs font-semibold text-danger m-0">❌ Gaps</p>
            <p className="text-sm mt-1 mb-0 break-words">{gaps.length ? gaps.join(", ") : "No significant gaps detected."}</p>
          </div>
        </div>
      </div>

      {/* ---------------- 1b. Evidence matrix (source data of the doc engine) ---------------- */}
      {(() => {
        const ev = Array.isArray(job.evidence) ? (job.evidence as Record<string, unknown>[]) : [];
        if (ev.length === 0) return null;
        const starRow = (row: Record<string, unknown>): string => {
          const raw = str(row.stars);
          if (raw) return raw;
          const level = Number(row.level ?? 0);
          return level > 0 ? "★".repeat(Math.min(5, level)) : "☆☆☆☆☆";
        };
        return (
          <div className="card mt-3">
            <h3 className="m-0 text-sm font-semibold">🧩 Data your documents are built from</h3>
            <p className="text-xs text-muted mt-1 mb-0">
              Evidence matrix extracted from your profile for every job target. The tailored CV emphasizes
              ★★★★+ evidence only — AIROS never claims a skill you cannot prove (V2 truthfulness rule).
            </p>
            <table className="w-full text-sm mt-3 border-collapse">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-border">
                  <th className="py-2 pr-3">Skill / target</th>
                  <th className="py-2 pr-3">Category</th>
                  <th className="py-2 pr-3">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {ev.map((row, i) => (
                  <tr key={i} className="border-b border-border">
                    <td className="py-2 pr-3 font-medium">{str(row.item)}</td>
                    <td className="py-2 pr-3">{str(row.category)}</td>
                    <td className="py-2 pr-3">
                      <span title={str(row.source)}>{starRow(row)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })()}

      {/* ---------------- 2. Company review ---------------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Company review</h3>
        <div className="grid gap-2 mt-3 text-sm" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
          <div><span className="text-xs text-muted">Name</span><div className="font-medium">{str(company.name) || "—"}</div></div>
          <div><span className="text-xs text-muted">Industry</span><div className="font-medium">{str(company.industry) || "—"}</div></div>
          <div><span className="text-xs text-muted">Address</span><div className="font-medium">{str(company.address) || "—"}</div></div>
          <div><span className="text-xs text-muted">City / Country</span><div className="font-medium">{str(company.city) || "—"} · {str(company.country) || "—"}</div></div>
          <div><span className="text-xs text-muted">Website</span><div className="font-medium break-all">{str(company.website) || "—"}</div></div>
          <div><span className="text-xs text-muted">LinkedIn</span><div className="font-medium break-all">{str(company.linkedin_url) || "—"}</div></div>
        </div>
      </div>
{/* ---------------- 3. Recruiter / HR contact ---------------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Recruiter / HR contact</h3>
        <p className="text-xs text-muted mt-1 mb-0">
          The HR/recruiter contact used to generate the recruiter email. Individual emails with
          High/Medium confidence are <span className="text-ok">reliable</span>; generic inboxes
          (info@, careers@, jobs@…) are never treated as a person.
        </p>

        {contacts.length === 0 ? (
          <p className="text-sm mt-2 mb-0">
            ℹ️ No recruiter saved for this offer yet — add one below, or leave it empty (the
            recruiter email is optional).
          </p>
        ) : (
          <div className="mt-2 space-y-2">
            {contacts.map((c, i) => {
              const rc = reliableContact(c);
              const name = str(c.name);
              const email = str(c.email);
              const pos = str(c.position);
              const li = str(c.linkedin_url);
              const conf = str(c.confidence);
              return (
                <div
                  key={str(c.contact_id) || `c${i}`}
                  className="rounded-lg border border-border p-3 flex items-start gap-3 flex-wrap"
                >
                  <div className="flex-1 min-w-40">
                    <p className="text-sm font-semibold m-0">
                      {name || "Unnamed contact"} {rc ? "✅" : ""}
                    </p>
                    <p className="text-xs text-muted mt-1 mb-0">
                      {pos || "Position unknown"} · {email || "no email"} · confidence: {conf || "—"}
                      {li ? " · " : ""}
                      {li ? (
                        <a className="text-brand" href={li} target="_blank" rel="noreferrer">LinkedIn</a>
                      ) : null}
                    </p>
                  </div>
                  <span className={"text-xs font-semibold px-2 py-1 rounded-full " + (rc ? "text-ok" : "text-warn")}>
                    {rc ? "Reliable" : "Below reliable threshold"}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {!showAddContact && (
          <button type="button" className="btn-secondary mt-3" onClick={() => setShowAddContact(true)}>
            ➕ {contacts.length === 0 ? "Add a recruiter / HR contact" : "Add another recruiter / HR contact"}
          </button>
        )}

        {showAddContact && (
          <div className="mt-3">
            <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
              <label className="text-sm"><span className="text-xs text-muted">Name</span>
                <input className="input w-full" value={manContact.name ?? ""} onChange={manSet("name")} placeholder="Anna Müller" /></label>
              <label className="text-sm"><span className="text-xs text-muted">Position</span>
                <input className="input w-full" value={manContact.position ?? ""} onChange={manSet("position")} placeholder="Senior Talent Acquisition" /></label>
              <label className="text-sm"><span className="text-xs text-muted">Email</span>
                <input className="input w-full" type="email" value={manContact.email ?? ""} onChange={manSet("email")} placeholder="anna.mueller@company.com" /></label>
              <label className="text-sm"><span className="text-xs text-muted">LinkedIn URL</span>
                <input className="input w-full" value={manContact.linkedin_url ?? ""} onChange={manSet("linkedin_url")} /></label>
              <label className="text-sm"><span className="text-xs text-muted">Contact Type</span>
                <select className="input w-full" value={manContact.contact_type ?? "HR Recruiter"} onChange={manSet("contact_type")}>
                  {CONTACT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select></label>
              <label className="text-sm"><span className="text-xs text-muted">Confidence</span>
                <select className="input w-full" value={manContact.confidence ?? "Medium"} onChange={manSet("confidence")}>
                  {CONFIDENCE_LEVELS.map((t) => <option key={t} value={t}>{t}</option>)}
                </select></label>
            </div>
            <button type="button" className="btn-primary mt-3" onClick={addContact} disabled={busy}>
              {busy ? "Saving..." : "💾 Save Recruiter"}
            </button>
          </div>
        )}
      </div>
{/* ---------------- 4. Document engine + validation ---------------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">🚀 Prepare your application package</h3>
        <p className="text-sm mt-2 mb-0">
          Generate your complete application package in <b>one AI call</b>: tailored CV + cover
          letter (+ recruiter email when a reliable contact exists), then an automatic post-generation
          validation report.
        </p>

        <button type="button" className="btn-primary mt-3" onClick={generate} disabled={generating}>
          {generating ? "Generating your application package..." : "🚀 Generate tailored CV + cover letter"}
        </button>

        {reliable == null && (
          <p className="text-sm mt-2 mb-0 rounded-lg border border-warn text-warn p-2">
            ℹ️ <b>No reliable recruiter email</b> found for this offer — the recruiter email will be
            skipped. Your tailored CV and cover letter are generated normally (the workflow is not blocked).
          </p>
        )}

        {docs && (
          <div className="mt-4 space-y-3">
            <p className="text-sm font-semibold text-ok m-0">✅ Application package generated at {str(docs.docs_generated_at)}</p>

            {(str(docs.docs.cv_document_id) || str(docs.docs.cover_letter_document_id) || str(docs.docs.email_document_id)) && (
              <div className="space-y-2">
                <p className="text-sm font-semibold m-0">📤 Ready-to-send documents</p>
                {str(docs.docs.cv_document_id) && (
                  <div>
                    <RenditionButtons docId={docs.docs.cv_document_id} label="Tailored CV" />
                    <RenderingStatus report={rendering?.documents?.cv} label="Tailored CV" />
                  </div>
                )}
                {str(docs.docs.cover_letter_document_id) && (
                  <div>
                    <RenditionButtons docId={docs.docs.cover_letter_document_id} label="Cover Letter" />
                    <RenderingStatus report={rendering?.documents?.cover_letter} label="Cover Letter" />
                  </div>
                )}
                {str(docs.docs.email_document_id) && (
                  <div>
                    <button
                      type="button"
                      className="btn-secondary text-xs"
                      onClick={() => download(docs.docs.email_document_id)}
                    >
                      ⬇️ Recruiter email (TXT)
                    </button>
                  </div>
                )}
              </div>
            )}

            <div>
              <details>
                <summary className="text-sm font-semibold cursor-pointer">📄 Tailored CV</summary>
                <pre className="text-xs overflow-auto max-h-72 mt-2 p-2 bg-bg rounded-lg whitespace-pre-wrap">{str(cv.full_text) || "(no text)"}</pre>
              </details>
            </div>
            <div>
              <details>
                <summary className="text-sm font-semibold cursor-pointer">📝 Cover Letter</summary>
                <pre className="text-xs overflow-auto max-h-72 mt-2 p-2 bg-bg rounded-lg whitespace-pre-wrap">{str(coverLetter.full_text) || "(no text)"}</pre>
              </details>
            </div>
            {email.required === true && str(email.body) && (
              <div>
                <details>
                  <summary className="text-sm font-semibold cursor-pointer">✉️ Recruiter Email</summary>
                  <pre className="text-xs overflow-auto max-h-72 mt-2 p-2 bg-bg rounded-lg whitespace-pre-wrap">
                    {`Subject: ${str(email.subject)}\n\n${str(email.body)}`}
                  </pre>
                </details>
              </div>
            )}
            {email.required !== true && (
              <p className="text-sm text-muted m-0">
                ⚠️ Recruiter Email — not applicable (no reliable individual recruiter email identified).
              </p>
            )}
          </div>
        )}

        {docs && Object.keys(validation).length > 0 && (
          <div className="mt-4 rounded-lg border border-border p-3">
            <p className="text-xs font-semibold text-muted m-0">Post-generation validation</p>
            <p className="text-xs text-muted mt-1 mb-0">
              The tailored score is <b>objective</b>: AIROS re-runs the same deterministic ATS engine
              on the generated document&apos;s own content (skills, experience, summary and full text) — no AI round-trip.
            </p>

            <div className="grid gap-3 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
              <div className="rounded-lg border border-border p-3 text-center">
                <div className="text-xs text-muted">Original ATS</div>
                <div className="text-2xl font-bold">{str(validation.original_ats)}%</div>
                <div className="text-xs text-muted mt-1">Your profile at analysis time</div>
              </div>
              <div className="rounded-lg border border-border p-3 text-center">
                <div className="text-xs text-muted">Tailored ATS</div>
                <div className="text-2xl font-bold">{str(validation.tailored_ats)}%</div>
                <div className="text-xs text-muted mt-1">Deterministic re-score of the generated CV</div>
              </div>
              <div className={"rounded-lg border border-border p-3 text-center " + statusClass}>
                <div className="text-xs text-muted">Gain</div>
                <div className="text-2xl font-bold">{impValue >= 0 ? "+" : ""}{impValue} pts</div>
                <div className="text-xs text-muted mt-1">Status: <b>{statusLabel}</b></div>
              </div>
            </div>

            {scoreStatus === "marginal" && (
              <div className="mt-3 rounded-lg border border-warn text-warn p-3 text-sm">
                <b>💡 AIROS could not make a meaningful difference here.</b> The tailored CV gains less
                than 2 points over your original ({str(validation.original_ats)}% → {str(validation.tailored_ats)}%).
                For this profile and this job description, nothing more could be improved while staying truthful.
                <br />
                <b>You are free to choose between your original CV and this tailored version</b> — download
                the tailored CV below and decide.
              </div>
            )}

            {str(validation.message) && <p className="text-sm mt-3 mb-0">{str(validation.message)}</p>}

            {Object.keys(recalcSub).length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold text-muted m-0">Score breakdown (tailored CV)</p>
                <div className="grid gap-2 mt-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))" }}>
                  {Object.entries(recalcSub).map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-border p-2 text-center">
                      <div className="text-base font-bold">{Math.round(Number(v) || 0)}%</div>
                      <div className="text-xs text-muted mt-1">{k.replace(/_/g, " ")}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {(recalcMatched.length > 0 || recalcRemaining.length > 0) && (
              <div className="grid gap-3 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
                <div>
                  <p className="text-xs font-semibold text-ok m-0">✅ Matched by the tailored CV</p>
                  <p className="text-sm mt-1 mb-0 break-words">
                    {recalcMatched.length ? recalcMatched.join(", ") : "None"}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold text-danger m-0">❌ Still missing in the tailored CV</p>
                  <p className="text-sm mt-1 mb-0 break-words">
                    {recalcRemaining.length ? recalcRemaining.join(", ") : "None"}
                  </p>
                </div>
              </div>
            )}

            {str(validation.needs_review) === "true" && (
              <p className="text-xs text-danger mt-2 mb-0">
                ⚠️ This result needs your review: the tailored CV regressed, or contains claims that
                could not be traced back to your profile (see the evidence / fabrication checks).
              </p>
            )}
          </div>
        )}
      </div>
{/* ---------------- 5. Confirm application ---------------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">✅ Confirm Application</h3>
        <p className="text-sm mt-2 mb-0">
          After you have applied <b>externally</b> (LinkedIn, company site, email…), come back here and
          confirm the outcome. Confirming “Sent” creates the tracking record (status APPLIED) in the
          Job Tracking workspace.
        </p>

        <div className="mt-3 space-y-3">
          <label className="text-sm flex items-center gap-3 flex-wrap">
            <span className="text-xs text-muted w-40 shrink-0">Application status</span>
            <select className="input" value={decision} onChange={(e) => setDecision(e.target.value as "sent" | "cancelled")}>
              <option value="sent">Sent successfully</option>
              <option value="cancelled">Cancelled / Not sent</option>
            </select>
          </label>

          {decision === "sent" && (
            <>
              <label className="text-sm flex items-center gap-3 flex-wrap">
                <span className="text-xs text-muted w-40 shrink-0">Application channel</span>
                <select className="input" value={channel} onChange={(e) => setChannel(e.target.value)}>
                  {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <label className="text-sm flex items-center gap-3 flex-wrap">
                <span className="text-xs text-muted w-40 shrink-0">Application date</span>
                <input className="input" type="date" value={appDate} onChange={(e) => setAppDate(e.target.value)} />
              </label>
              <label className="text-sm block">
                <span className="text-xs text-muted">Notes (optional)</span>
                <textarea className="input w-full" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
              </label>
            </>
          )}

          <button type="button" className="btn-primary" onClick={doConfirm} disabled={busy}>
            {busy ? "Confirming..." : "Confirm Application"}
          </button>
        </div>
      </div>
    </div>
  );
}
