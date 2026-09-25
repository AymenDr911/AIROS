"use client";
/* AIROS V3 - Application Workspace (CHG-018 parity + CHG-025 Job Analyses rework).
   The four sidebar menus all live on this ONE route and are selected with the
   ?stage= deep link:
     ① analyze  - "Job Analyses": paste a JD -> AIROS verifies it -> ATS &
                  compatibility score against the OWN CV/profile -> the full
                  report -> the final decision at the bottom. A PASS closes the
                  step and opens the next menu.
     ② workshop - "Application Workshop": the hub the user is redirected to
                  once an analysis PASSED (the sidebar menu appears then).
     ③ prepare  - save the offer (Job + Company + Contact) and run the document
                  engine (ONE Gemini call: tailored CV + cover letter + recruiter
                  email), validation, then Confirm (sent/cancelled).
     ④ track    - the confirmed application with the manual-only lifecycle
                  (V2 pages 4+5): status moves, employer responses, interviews,
                  follow-ups, reminders, close.
   The passed analysis + saved job are persisted for the session in
   lib/workspace.ts, so the sidebar menu set stays correct on EVERY page. */
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AUTH_PROBE_TIMEOUT_MS,
  AUTH_TIMEOUT_MS,
  auth0,
  getSession,
  hasPendingLogin,
  login,
  withTimeout,
} from "@/lib/airos";
import ConnectionProbe from "@/components/ConnectionProbe";
import Sidebar, { type AppStage } from "@/components/Sidebar";
import ApplicationWorkshop from "@/components/applications/ApplicationWorkshop";
import JobAnalyses from "@/components/applications/JobAnalyses";
import SaveJobStep from "@/components/applications/SaveJobStep";
import PrepareTab from "@/components/applications/PrepareTab";
import TrackTab from "@/components/applications/TrackTab";
import { type SaveJobResult } from "@/lib/applications";
import { apiUrl } from "@/lib/config";
import { fetchTable, type ApplicationRow, type ProfileRow } from "@/lib/data";
import {
  clearRun,
  getPendingAnalysis,
  getSavedJob,
  setPendingAnalysis,
  setSavedJob,
  setTrackedCount,
  type PendingAnalysis,
} from "@/lib/workspace";

type Phase = "loading" | "ready" | "signedout" | "error";

/** ① Job Analyses -> ② Application Workshop -> ③ Preparation -> ④ Tracking. */
type Stage = AppStage;

/** ?stage= deep link -> stage ("analyze" is the default when the param is absent). */
function parseStage(value: string | null): Stage {
  return value === "workshop" || value === "prepare" || value === "track" ? value : "analyze";
}

function ApplicationsTab({
  apps,
  onTrack,
}: {
  apps: { rows: ApplicationRow[]; error: string } | null;
  onTrack: (applicationId: string) => void;
}) {
  if (apps == null) {
    return (
      <div className="card mt-4">
        <p className="text-muted m-0">Loading your applications...</p>
      </div>
    );
  }
  if (apps.error) {
    return (
      <div className="card mt-4 border border-danger">
        <h3 className="m-0 text-sm font-semibold">Could not load your applications</h3>
        <p className="text-sm mt-2 mb-0 break-words">{apps.error}</p>
      </div>
    );
  }
  if (apps.rows.length === 0) {
    return (
      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">My applications</h3>
        <p className="text-sm text-muted mt-2 mb-0">
          No applications yet. Analyze a job offer and, on a passing verdict, confirm your
          application to create a tracking record here.
        </p>
      </div>
    );
  }
  return (
    <div className="card mt-4 overflow-x-auto">
      <h3 className="m-0 text-sm font-semibold">
        My applications (tracked) - {apps.rows.length} row{apps.rows.length === 1 ? "" : "s"}
      </h3>
      <table className="w-full text-sm mt-3 border-collapse">
        <thead>
          <tr className="text-left text-xs text-muted border-b border-border">
            <th className="py-2 pr-3">Title</th>
            <th className="py-2 pr-3">Company</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3">Applied</th>
            <th className="py-2 pr-3">Outcome</th>
            <th className="py-2 pr-3"></th>
          </tr>
        </thead>
        <tbody>
          {apps.rows.map((a) => (
            <tr key={a.id} className="border-b border-border">
              <td className="py-2 pr-3 font-medium">{a.title || a.application_id}</td>
              <td className="py-2 pr-3">{a.company_id}</td>
              <td className="py-2 pr-3">{a.status || "-"}</td>
              <td className="py-2 pr-3">{fmtDate(a.application_date)}</td>
              <td className="py-2 pr-3">{a.outcome || "-"}</td>
              <td className="py-2 pr-3">
                <button
                  type="button"
                  className="btn-secondary text-xs"
                  onClick={() => onTrack(a.application_id)}
                >
                  Track
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmtDate(v: string | null): string {
  if (!v) return "-";
  const d = new Date(v);
  return isNaN(d.getTime()) ? v : d.toISOString().slice(0, 10);
}

const STAGE_META: { id: Stage; label: string; title: string; hint: string }[] = [
  { id: "analyze", label: "Job Analyses", title: "① Job Analyses", hint: "Paste the full job description: AIROS verifies it and scores it against your own CV / profile. The complete report and the final decision follow on this page." },
  { id: "workshop", label: "Application Workshop", title: "② Application Workshop", hint: "The analysis PASSED, so this menu is now open - pick your next action for this offer." },
  { id: "prepare", label: "App Workspace / Preparation", title: "③ App Workspace / Preparation", hint: "This menu holds ALL the source data used to generate your application documents." },
  { id: "track", label: "Job Tracking", title: "④ Job Tracking", hint: "After you confirm the application: follow it manually until it closes." },
];

/** The dedicated application menu: ① Analyze -> Application Workshop -> ② Prepare -> ③ Track.
    After each step the page auto-advances to the next menu instead of
    staying inside the job analyzer. */
function StageStepper({
  current,
  enabled,
  onGo,
}: {
  current: Stage;
  enabled: Record<Stage, boolean>;
  onGo: (s: Stage) => void;
}) {
  return (
    <ol className="flex items-center gap-2 flex-wrap text-sm mt-5">
      {STAGE_META.map((s, i) => {
        const active = s.id === current;
        const done = (enabled[s.id] ?? false) && !active;
        // Only show the stage if it's the current one or it's been completed
        if (active || done) {
          return (
            <li key={s.id} className="flex items-center gap-2">
              {i > 0 && <span className="text-muted" aria-hidden="true">→</span>}
              <button
                type="button"
                disabled={!enabled[s.id]}
                onClick={() => onGo(s.id)}
                title={s.hint}
                className={
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm border font-medium " +
                  (active
                    ? "btn-primary"
                    : done
                      ? "text-ok"
                      : "text-muted opacity-70")
                }
              >
                <span
                  aria-hidden="true"
                  className={
                    "w-6 h-6 rounded-full inline-flex items-center justify-center text-xs font-bold " +
                    (active ? "bg-white text-brand" : done ? "text-ok" : "text-muted")
                  }
                >
                  {i + 1}
                </span>
                {s.label}
              </button>
            </li>
          );
        }
        return null;
      })}
    </ol>
  );
}

export default function ApplicationsPage() {
  // useSearchParams (below) must sit behind a Suspense boundary so the route
  // stays statically prerenderable (Next.js requirement).
  return (
    <Suspense
      fallback={
        <div className="card text-center py-6">
          <p className="text-muted">Loading...</p>
        </div>
      }
    >
      <ApplicationsWorkspace />
    </Suspense>
  );
}

function ApplicationsWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("loading");
  const [errMsg, setErrMsg] = useState("");
  const [authNote, setAuthNote] = useState("");
  const [retryTick, setRetryTick] = useState(0);
  const [stage, setStage] = useState<Stage>("analyze");
  const [apps, setApps] = useState<{ rows: ApplicationRow[]; error: string } | null>(null);
  const [hasProfile, setHasProfile] = useState(true);
  const [profile, setProfile] = useState<ProfileRow | null>(null);
  const [token, setToken] = useState("");
  // The run (passed analysis + saved job) is persisted for the session in
  // lib/workspace.ts, so the sidebar menu set and the workshop survive
  // navigation between the menus.
  const [pending, setPendingState] = useState<PendingAnalysis | null>(null);
  const [saved, setSavedState] = useState<SaveJobResult | null>(null);
  const [tracking, setTracking] = useState<string | null>(null);
  /** Applications confirmed during this session (the sidebar count, pre-refetch). */
  const [extraApps, setExtraApps] = useState(0);

  /** Write-through setters: page state + the shared (session) run state. */
  const setPending = (value: PendingAnalysis | null) => {
    setPendingState(value);
    setPendingAnalysis(value);
  };
  const setSaved = (value: SaveJobResult | null) => {
    setSavedState(value);
    setSavedJob(value);
  };
  const tracked = (apps?.rows.length ?? 0) + extraApps;

  useEffect(() => {
    let cancelled = false;
    // Restore the run of this session (a passed analysis + its saved job).
    setPendingState(getPendingAnalysis());
    setSavedState(getSavedJob());
    const pendingLogin = hasPendingLogin();
    (async () => {
      try {
        const authed = await withTimeout(
          getSession(),
          pendingLogin ? AUTH_TIMEOUT_MS : AUTH_PROBE_TIMEOUT_MS,
          pendingLogin
            ? "Auth0 did not complete the login. Check your connection, then retry."
            : "Could not reach Auth0 to check your session."
        );
        if (cancelled) return;
        if (!authed) {
          setPhase("signedout");
          return;
        }
        setPhase("ready");
        const c = await auth0();
        const claims = await c.getIdTokenClaims();
        setToken(claims?.__raw ?? "");
        const [profileRows, appRows] = await Promise.all([
          fetchTable<ProfileRow>(c, "profiles"),
          fetchTable<ApplicationRow>(c, "applications", "order=updated_at.desc"),
        ]);
        if (cancelled) return;
        setHasProfile(profileRows.rows.length > 0);
        setProfile(profileRows.rows[0] ?? null);
        setApps(appRows);
      } catch (e) {
        if (cancelled) return;
        const msg = (e as Error)?.message || "Unexpected error";
        if (!pendingLogin) {
          setAuthNote(msg + " Showing the sign-in screen below.");
          setPhase("signedout");
          return;
        }
        setErrMsg(msg);
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [retryTick]);

  // The ?stage= deep link is the source of truth for the visible menu, so it must
  // follow CLIENT navigations too (the sidebar entries point at this very same
  // route with a different ?stage=) - not just the first mount.
  const urlStage = parseStage(searchParams.get("stage"));
  useEffect(() => {
    setStage((current) => (current === urlStage ? current : urlStage));
  }, [urlStage]);

  // ...and keep the URL in step with the stage the flow advances to, so that a
  // refresh (or a shared link) lands back on the same menu.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const want = stage === "analyze" ? "" : "?stage=" + stage;
    if (window.location.search !== want) {
      router.replace(stage === "analyze" ? "/applications" : "/applications" + want, {
        scroll: false,
      });
    }
  }, [stage, router]);

  // Mirror the live application count into the shared run state: that is what
  // reveals/hides the ④ Job Tracking menu in the sidebar.
  useEffect(() => {
    if (apps != null) setTrackedCount(tracked);
  }, [apps, tracked]);
if (phase === "loading") {
    return (
      <div className="card text-center py-6">
        <p className="text-muted">Loading...</p>
        <p className="text-xs text-muted mt-3 mb-0">
          Stuck?{" "}
          <button
            type="button"
            className="text-brand underline underline-offset-2 cursor-pointer"
            onClick={() => window.location.reload()}
          >
            Reload the page
          </button>
        </p>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="card text-center py-10">
        <h1 className="text-3xl font-bold">Could not open the workspace</h1>
        <p className="text-muted mt-3">{errMsg}</p>
        <div className="flex justify-center gap-3 mt-6 flex-wrap">
          <button type="button" onClick={() => setRetryTick((t) => t + 1)} className="btn-primary">
            Try again
          </button>
          <button type="button" onClick={() => login()} className="btn-secondary">
            Continue with Auth0
          </button>
        </div>
        <div className="mt-6 max-w-md">
          <ConnectionProbe />
        </div>
      </div>
    );
  }

  if (phase === "signedout") {
    return (
      <div className="card text-center py-10">
        <h1 className="text-3xl font-bold">You are signed out</h1>
        <p className="text-muted mt-3">Sign in with Auth0 to use the application engine.</p>
        {authNote != null && <p className="text-xs text-warn mt-2 mb-0">{authNote}</p>}
        <button type="button" onClick={() => login()} className="btn-primary mt-6">
          Continue with Auth0
        </button>
        <div className="mt-6 max-w-md">
          <ConnectionProbe />
        </div>
      </div>
    );
  }
const meta = STAGE_META.find((s) => s.id === stage) ?? STAGE_META[0];
  /** Abandon the run (passed analysis + saved job): ② / ③ leave the sidebar. */
  const discardRun = () => {
    clearRun();
    setPendingState(null);
    setSavedState(null);
  };
  const resetAll = () => {
    discardRun();
    setTracking(null);
    setStage("analyze");
  };
  return (
    <div className="flex min-h-screen">
      <Sidebar activeStage={stage} trackedCount={tracked} />
      <div className="flex-1 p-6 max-w-5xl">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold m-0">{meta.title}</h1>
            <p className="text-sm text-muted mt-1 mb-0">{meta.hint}</p>
          </div>
          <div className="flex gap-2 items-center">
            {stage !== "analyze" && (
              <button type="button" className="btn-secondary text-sm" onClick={resetAll}>
                ＋ New analysis
              </button>
            )}
            <Link href="/app" className="text-sm text-brand underline underline-offset-2">
              ← Dashboard
            </Link>
          </div>
        </div>

        <StageStepper
          current={stage}
          enabled={{
            analyze: true,
            workshop: pending != null,
            prepare: pending != null,
            track: tracked > 0,
          }}
          onGo={(s) => {
            if (s === "analyze") {
              resetAll();
            } else if (s === "workshop") {
              setStage("workshop");
            } else if (s === "prepare") {
              if (pending) setStage("prepare");
            } else {
              setTracking(null);
              setStage("track");
            }
          }}
        />

        {stage === "prepare" &&
          saved &&
          ((() => {
            const c = saved.contact;
            const n = c && typeof c.name === "string" ? c.name : "";
            const e = c && typeof c.email === "string" ? c.email : "";
            const p = c && typeof c.position === "string" ? c.position : "";
            const line =
              n || e
                ? `${n || "Recruiter link saved"}${p ? ` — ${p}` : ""}${e ? ` · ${e}` : ""}`
                : "";
            return line ? (
              <p className="text-sm mt-3 mb-0">
                👤 <b>Recruiter (HR)</b> for this offer: {line} — verified below before generating the documents.
              </p>
            ) : null;
          })())}

        {stage === "analyze" ? (
          <JobAnalyses
            hasProfile={hasProfile}
            cvSummary={
              profile != null
                ? {
                    originals: profile.original_cv_count ?? 0,
                    careerStage: profile.career_stage ?? "",
                    updatedAt: profile.updated_at ?? "",
                  }
                : null
            }
            token={token}
            onPassed={(jobText, result) => {
              // (f) PASSED: register the run, which makes the ② Application
              // Workshop menu appear in the sidebar immediately (the report and
              // the final decision stay on this page until the decision is taken).
              setPending({ analysis: result, jobText });
              setSaved(null);
            }}
            onOpenWorkshop={() => setStage("workshop")}
            onDiscardRun={discardRun}
          />
        ) : stage === "workshop" ? (
          <ApplicationWorkshop
            run={pending}
            tracked={tracked}
            onOpenPreparation={() => setStage("prepare")}
            onOpenTracking={() => {
              setTracking(null);
              setStage("track");
            }}
            onNewAnalysis={resetAll}
          />
        ) : stage === "prepare" ? (
          pending == null ? (
            <div className="card mt-4">
              <p className="text-muted m-0">Analyze a job offer first (step ①) to unlock this menu.</p>
            </div>
          ) : saved == null ? (
            <SaveJobStep
              analysis={pending.analysis}
              originalJd={pending.jobText}
              token={token}
              onSaved={(savedResult) => setSaved(savedResult)}
              onCancel={() => setStage("analyze")}
            />
          ) : (
            <PrepareTab
              jobId={String((saved.job ?? {}).job_id ?? "")}
              saved={saved}
              token={token}
              onConfirmed={(applicationId) => {
                // The run is consumed by the application: drop it (which also
                // hides ② / ③) and reveal ④ Job Tracking immediately.
                setSaved(null);
                setPending(null);
                setExtraApps((n) => n + 1);
                setTracking(applicationId);
                setStage("track");
              }}
              onBack={() => setSaved(null)}
            />
          )
        ) : (
          tracking == null ? (
            <ApplicationsTab
              apps={apps}
              onTrack={(applicationId) => setTracking(applicationId)}
            />
          ) : (
            <TrackTab
              applicationId={tracking}
              token={token}
              onBack={() => setTracking(null)}
            />
          )
        )}
      </div>
    </div>
  );
}
