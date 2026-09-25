"use client";
/* AIROS V3 - Job Tracking (CHG-018, V2 page 5 parity).
   Manual-only lifecycle for a confirmed application: status transitions,
   recruiter responses, interview scheduling, follow-ups (action), next-action
   logic and close. Every write goes through the /api/applications router with
   the caller's token (RLS preserved). */
import { useCallback, useEffect, useState } from "react";
import { applicationAction, applicationDetail } from "@/lib/applications";

const STATUS_LABELS: Record<string, string> = {
  APPLIED: "📥 Applied",
  WAITING: "⏳ Waiting",
  FOLLOW_UP: "📤 Follow-up (action)",
  EMPLOYER_RESPONSE: "💬 Employer Response",
  SCREENING: "🔎 Screening",
  INTERVIEW: "🪑 Interview",
  ASSESSMENT: "🧪 Assessment",
  ADDITIONAL_INFO: "📄 Additional Info",
  OFFER: "🎉 Offer",
  REJECTED: "❌ Rejected",
  WITHDRAWN: "↩️ Withdrawn",
  CLOSED: "🗂️ Closed",
};

const RESPONSE_TYPES: Record<string, string> = {
  REFUSED: "❌ Refused",
  INTERVIEW_REQUEST: "🗓️ Request for interview (date/time)",
  ADDITIONAL_INFO_REQUEST: "📄 Request for additional data / file",
};

const RESPONSE_CHANNELS = ["Email", "WhatsApp", "Phone", "LinkedIn message", "Other"];
const INTERVIEW_MODES = [
  "Online (video call)",
  "Skype",
  "Google Meet",
  "Microsoft Teams",
  "Zoom",
  "Phone call",
  "In person (on site)",
  "Other",
];

const str = (v: unknown): string => (v == null ? "" : String(v));
const num = (v: unknown, fallback = 0): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};
const arr = (v: unknown): Record<string, unknown>[] =>
  Array.isArray(v) ? (v as Record<string, unknown>[]) : [];
const fmtDate = (v: unknown): string => {
  const s = str(v);
  return s ? s.slice(0, 10) : "—";
};

type Props = {
  applicationId: string;
  token: string;
  onBack: () => void;
};

export default function TrackTab({ applicationId, token, onBack }: Props) {
  const [app, setApp] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  const load = useCallback(async () => {
    try {
      const detail = await applicationDetail(token, applicationId);
      setApp(detail.application ?? {});
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [applicationId, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (action: string, payload: Record<string, unknown>, successNote?: string) => {
    setBusy(true);
    setErr("");
    setOk("");
    try {
      await applicationAction(token, applicationId, action, payload);
      await load();
      if (successNote) setOk(successNote);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // --- transition form ---------------------------------------------------
  const [newStatus, setNewStatus] = useState("");
  const [statusNote, setStatusNote] = useState("");

  // --- recruiter response form -------------------------------------------
  const [respType, setRespType] = useState("REFUSED");
  const [respChannel, setRespChannel] = useState("Email");
  const [respDate, setRespDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [respNote, setRespNote] = useState("");

  // RH (recruiter/HR) context — enriched by GET /api/applications/{id}:
  // `reliable_contact` (document-engine rule) + full `company` card, with
  // the application-row snapshot as fallback. Before this fix the Track tab
  // showed only the row snapshot, so RH data saved at Prepare time looked
  // "missing" whenever the row snapshot was empty.
  const reliable = (app?.reliable_contact ?? {}) as Record<string, unknown>;
  const companyCard = (app?.company ?? {}) as Record<string, unknown>;
  const rhName = str(reliable.name) || str(app?.recruiter_name);
  const rhEmail = str(reliable.email) || str(app?.recruiter_email);
  const rhPosition = str(reliable.position) || str(app?.recruiter_position);
  const rhLinkedin = str(reliable.linkedin_url) || str(app?.recruiter_linkedin);
  const hasRh = Boolean(rhName || rhEmail);

  // --- interview form ------------------------------------------------------
  const pending = (app?.pending_interview ?? null) as Record<string, unknown> | null;
  const [ivRound, setIvRound] = useState(1);
  const [ivWhen, setIvWhen] = useState("");
  const [ivMode, setIvMode] = useState(INTERVIEW_MODES[0]);
  const [ivNotes, setIvNotes] = useState("");

  // --- follow-up form ------------------------------------------------------
  const [fuWhen, setFuWhen] = useState(() => new Date().toISOString().slice(0, 10));
  const [fuChannel, setFuChannel] = useState("Email");
  const [fuNote, setFuNote] = useState("");
  const [remindDays, setRemindDays] = useState(8);

  // --- response/closing dates ----------------------------------------------
  const [respDateRule, setRespDateRule] = useState("");
  const [closingDate, setClosingDate] = useState("");
  const [closeNote, setCloseNote] = useState("");

  if (loading) {
    return (
      <div className="card mt-4">
        <p className="text-muted m-0">Loading your application record...</p>
      </div>
    );
  }

  if (!app) {
    return (
      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">Could not load the application</h3>
        <p className="text-sm mt-2 mb-0">{err}</p>
        <button type="button" className="btn-secondary mt-3" onClick={onBack}>← Back</button>
      </div>
    );
  }

  const status = str(app.status || "APPLIED");
  const allowed = (app.allowed_transitions ?? []) as string[];
  const nextAction = (app.next_action ?? {}) as Record<string, unknown>;
  const timeline = arr(app.timeline);
  const interviews = arr(app.interviews);
  const responses = arr(app.recruiter_responses);
  const followUps = arr(app.follow_ups);
  const draft = (app.follow_up_draft ?? {}) as Record<string, unknown>;

  return (
    <div className="mt-4 space-y-4">
      {err && <p role="alert" className="text-danger text-sm m-0">{err}</p>}
      {ok && <p role="alert" className="text-ok text-sm m-0">{ok}</p>}

      {/* ------- 1. header + summary ------- */}
      <div className="card">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h3 className="m-0 text-lg font-bold">{str(app.title) || str(app.application_id)}</h3>
            <p className="text-xs text-muted mt-1 mb-0">
              {str(app.application_id)} · {str(app.company_name) || "—"} · {STATUS_LABELS[status] ?? status}
            </p>
          </div>
          <button type="button" className="btn-secondary" onClick={onBack} disabled={busy}>← Back to my applications</button>
        </div>

        <div className="grid gap-3 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          <div><span className="text-xs text-muted">ATS score</span><div className="font-medium">{num(app.ats_score)}%</div></div>
          <div><span className="text-xs text-muted">Channel</span><div className="font-medium">{str(app.channel) || "—"}</div></div>
          <div><span className="text-xs text-muted">Applied</span><div className="font-medium">{fmtDate(app.application_date)}</div></div>
          <div><span className="text-xs text-muted">Docs generated</span><div className="font-medium">{fmtDate(app.docs_generated_at)}</div></div>
          <div><span className="text-xs text-muted">Time consumed</span><div className="font-medium">{app.time_consumed_min == null ? "—" : `${num(app.time_consumed_min, 0)} min`}</div></div>
          <div><span className="text-xs text-muted">Outcome</span><div className="font-medium">{str(app.outcome) || "—"}</div></div>
          <div><span className="text-xs text-muted">Follow-up checkpoint</span><div className="font-medium">{fmtDate(app.follow_up_checkpoint)}</div></div>
        </div>
        {/* RH card — snapshot-only before, so RH saved at Prepare time looked
            "missing". Now prefers the enriched reliable_contact. */}
        {hasRh ? (
          <p className="text-sm mt-3 mb-0">
            <b>Recruiter (RH):</b> {rhName || "—"}
            {rhPosition ? ` — ${rhPosition}` : ""} ({rhEmail || "no email"})
            {rhLinkedin ? (<> · <a href={rhLinkedin} target="_blank" rel="noreferrer">LinkedIn</a></>) : null}
          </p>
        ) : (
          <p className="text-sm mt-3 mb-0 text-muted">
            No recruiter linked yet — add one from the Prepare step or the job contacts.
          </p>
        )}
      </div>

      {/* ------- 2. next action (Rule 1/2/3 logic) ------- */}
      {nextAction && str(nextAction.action) && (
        <div className="card">
          <h3 className="m-0 text-sm font-semibold">Next recommended action</h3>
          <p className="text-sm mt-2 mb-0 font-medium">{str(nextAction.action)}</p>
          {str(nextAction.hint) && <p className="text-sm text-muted mt-1 mb-0">{str(nextAction.hint)}</p>}
          {(str(nextAction.date) || str(nextAction.source)) && (
            <p className="text-xs text-muted mt-2 mb-0">
              {str(nextAction.date) && <>Date: {fmtDate(nextAction.date)} · </>}
              {str(nextAction.source) && <>Source: {str(nextAction.source)}</>}
            </p>
          )}
        </div>
      )}

      {/* ------- 3. timeline ------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Timeline</h3>
        {timeline.length === 0 ? (
          <p className="text-sm text-muted mt-2 mb-0">No activity recorded yet.</p>
        ) : (
          <ul className="text-sm mt-3 mb-0 pl-5 space-y-1">
            {timeline.map((t, i) => (
              <li key={i}>
                <b>{STATUS_LABELS[str(t.status)] ?? str(t.status)}</b> — {fmtDate(t.at)} {str(t.at).length > 10 ? `· ${str(t.at).slice(11, 19)}` : ""}
                {str(t.note) && <span className="text-muted"> — {str(t.note)}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
{/* ------- 4. manual lifecycle: status transition ------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Update lifecycle status</h3>
        <p className="text-xs text-muted mt-1 mb-0">
          AIROS never assumes progress — every move is manual and validated against the V2 transition map.
        </p>
        {allowed.length === 0 ? (
          <p className="text-sm text-muted mt-2 mb-0">This application is terminal (closed).</p>
        ) : (
          <div className="mt-3 flex gap-2 flex-wrap items-end">
            <label className="text-sm">
              <span className="text-xs text-muted">Next status</span>
              <select className="input" value={newStatus} onChange={(e) => setNewStatus(e.target.value)}>
                <option value="">— choose —</option>
                {allowed.map((s) => <option key={s} value={s}>{STATUS_LABELS[s] ?? s}</option>)}
              </select>
            </label>
            <label className="text-sm flex-1 min-w-40">
              <span className="text-xs text-muted">Note (optional)</span>
              <input className="input w-full" placeholder="e.g. moved to interview round 2" value={statusNote} onChange={(e) => setStatusNote(e.target.value)} />
            </label>
            <button
              type="button"
              className="btn-primary"
              disabled={busy || !newStatus}
              onClick={() => {
                void act("status", { new_status: newStatus, note: statusNote }, "Status updated.");
                setNewStatus("");
                setStatusNote("");
              }}
            >
              Update status
            </button>
          </div>
        )}
      </div>

      {/* ------- 5. recruiter response ------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Record employer response</h3>
        <p className="text-xs text-muted mt-1 mb-0">
          Log what the employer responded and how it arrived. The status follows the outcome
          (REFUSED → Rejected · INTERVIEW_REQUEST → Interview + pending round · ADDITIONAL_INFO_REQUEST → Additional Info).
        </p>
        <div className="mt-3 grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
          <label className="text-sm">
            <span className="text-xs text-muted">Response type</span>
            <select className="input w-full" value={respType} onChange={(e) => setRespType(e.target.value)}>
              {Object.entries(RESPONSE_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Channel</span>
            <select className="input w-full" value={respChannel} onChange={(e) => setRespChannel(e.target.value)}>
              {RESPONSE_CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Responded on</span>
            <input className="input w-full" type="date" value={respDate} onChange={(e) => setRespDate(e.target.value)} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Note (optional)</span>
            <input className="input w-full" value={respNote} onChange={(e) => setRespNote(e.target.value)} />
          </label>
        </div>
        <button
          type="button"
          className="btn-primary mt-3"
          disabled={busy}
          onClick={() => {
            void act("response", { response_type: respType, channel: respChannel, responded_on: respDate, note: respNote }, "Employer response recorded.");
            setRespNote("");
          }}
        >
          Record employer response
        </button>
      </div>

      {/* ------- 6. interview scheduling ------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Schedule / log an interview round</h3>
        {pending && str(pending.round) && (
          <p className="text-sm text-warn mt-2 mb-0">
            🗓️ Round {str(pending.round)} was requested by the recruiter — add the date, time and manner.
          </p>
        )}
        <div className="mt-3 flex gap-2 flex-wrap">
          <label className="text-sm">
            <span className="text-xs text-muted">Round</span>
            <input className="input w-20" type="number" min={1} value={ivRound} onChange={(e) => setIvRound(Number(e.target.value) || 1)} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Date / time</span>
            <input className="input" type="datetime-local" value={ivWhen} onChange={(e) => setIvWhen(e.target.value)} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Manner</span>
            <select className="input" value={ivMode} onChange={(e) => setIvMode(e.target.value)}>
              {INTERVIEW_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label className="text-sm flex-1 min-w-40">
            <span className="text-xs text-muted">Notes (optional)</span>
            <input className="input w-full" value={ivNotes} onChange={(e) => setIvNotes(e.target.value)} />
          </label>
        </div>
        <button
          type="button"
          className="btn-primary mt-3"
          disabled={busy || !ivWhen}
          onClick={() => {
            void act("interview", { round_no: ivRound, scheduled_at: ivWhen, mode: ivMode, notes: ivNotes }, `Interview round ${ivRound} scheduled.`);
            setIvWhen("");
            setIvNotes("");
          }}
        >
          Save interview round
        </button>
        {!ivWhen && <p className="text-xs text-muted mt-2 mb-0">Interview date/time is mandatory.</p>}
      </div>
{/* ------- 7. interviews log ------- */}
      {interviews.length > 0 && (
        <div className="card">
          <h3 className="m-0 text-sm font-semibold">Interviews</h3>
          <ul className="text-sm mt-3 mb-0 pl-5 space-y-1">
            {interviews.map((iv, i) => (
              <li key={i}>
                <b>Round {str(iv.round)}</b> — {fmtDate(iv.scheduled_at)}
                {str(iv.mode) && <span className="text-muted"> · {str(iv.mode)}</span>}
                {str(iv.notes) && <span className="text-muted"> — {str(iv.notes)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ------- 8. recruiter responses log ------- */}
      {responses.length > 0 && (
        <div className="card">
          <h3 className="m-0 text-sm font-semibold">Recruiter responses</h3>
          <ul className="text-sm mt-3 mb-0 pl-5 space-y-1">
            {responses.map((r, i) => (
              <li key={i}>
                <b>{RESPONSE_TYPES[str(r.type)] ?? str(r.type)}</b> — {fmtDate(r.responded_on ?? r.at)}
                {str(r.channel) && <span className="text-muted"> · via {str(r.channel)}</span>}
                {str(r.note) && <span className="text-muted"> — {str(r.note)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ------- 9. follow-ups ------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Follow-up (action)</h3>
        <p className="text-xs text-muted mt-1 mb-0">
          Draft a follow-up, confirm you sent it, or postpone the reminder (checkpoint = application date + 8 days by default).
        </p>

        {str(draft.message) && (
          <details className="mt-3">
            <summary className="text-sm font-semibold cursor-pointer">✍️ Follow-up draft</summary>
            <pre className="text-xs whitespace-pre-wrap mt-2 p-2 bg-bg rounded-lg overflow-auto max-h-72">{str(draft.message)}</pre>
          </details>
        )}

        <div className="mt-3 flex gap-2 flex-wrap items-end">
          <label className="text-sm">
            <span className="text-xs text-muted">Contacted on</span>
            <input className="input" type="date" value={fuWhen} onChange={(e) => setFuWhen(e.target.value)} />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted">Channel</span>
            <select className="input" value={fuChannel} onChange={(e) => setFuChannel(e.target.value)}>
              {RESPONSE_CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="text-sm flex-1 min-w-40">
            <span className="text-xs text-muted">Note (optional)</span>
            <input className="input w-full" value={fuNote} onChange={(e) => setFuNote(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => {
              void act("followup", { contacted_at: fuWhen, channel: fuChannel, note: fuNote }, "Follow-up marked as sent.");
              setFuNote("");
            }}
          >
            Mark follow-up as sent
          </button>
          <label className="text-sm">
            <span className="text-xs text-muted">Remind me in (days)</span>
            <input className="input" type="number" min={1} value={remindDays} onChange={(e) => setRemindDays(Number(e.target.value) || 8)} />
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy}
            onClick={() => void act("remind-later", { days: remindDays }, `Reminder postponed by ${remindDays} day(s).`)}
          >
            Remind me later
          </button>
        </div>
      </div>
{/* ------- 10. date rules ------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Timeline dates</h3>
        <div className="mt-3 flex gap-2 flex-wrap items-end">
          <label className="text-sm">
            <span className="text-xs text-muted">Employer response date (Rule 1)</span>
            <input className="input" type="date" value={respDateRule} onChange={(e) => setRespDateRule(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy || !respDateRule}
            onClick={() => void act("response-date", { date: respDateRule }, "Employer response date set.")}
          >
            Set response date
          </button>
          <label className="text-sm">
            <span className="text-xs text-muted">Job closing date (Rule 2)</span>
            <input className="input" type="date" value={closingDate} onChange={(e) => setClosingDate(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn-secondary"
            disabled={busy || !closingDate}
            onClick={() => void act("closing-date", { date: closingDate }, "Job closing date set.")}
          >
            Set closing date
          </button>
        </div>
        <p className="text-xs text-muted mt-3 mb-0">
          Rule 1: the employer-provided response date drives the next-action logic. Rule 2: job closing date is informational only.
          When neither is set, the follow-up checkpoint (application date + 8 days) applies (Rule 3).
        </p>
      </div>

      {/* ------- 11. close ------- */}
      <div className="card">
        <h3 className="m-0 text-sm font-semibold">Close application</h3>
        <p className="text-xs text-muted mt-1 mb-0">
          Closing is only available from OFFER / REJECTED / WITHDRAWN. The record is kept for reporting.
        </p>
        <div className="mt-3 flex gap-2 flex-wrap items-end">
          <label className="text-sm flex-1 min-w-40">
            <span className="text-xs text-muted">Closing note (optional)</span>
            <input className="input w-full" value={closeNote} onChange={(e) => setCloseNote(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn-primary"
            disabled={busy}
            onClick={() => {
              void act("close", { note: closeNote }, "Application closed.");
              setCloseNote("");
            }}
          >
            Close application
          </button>
        </div>
      </div>
    </div>
  );
}
