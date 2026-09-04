"use client";
/* AIROS V3 - authed dashboard (Slice 4b): welcome + live READ-ONLY module
   views over the user's own RLS-scoped rows (accounts, profiles,
   applications, documents) fetched with the Auth0 ID token as bearer
   (DEC-014 pattern, same as sync_my_account / verify_auth0.py). */
import { useEffect, useState } from "react";
import Link from "next/link";
import type { Auth0Client } from "@auth0/auth0-spa-js";
import {
  AUTH_PROBE_TIMEOUT_MS,
  AUTH_TIMEOUT_MS,
  auth0,
  checkBackend,
  getSession,
  hasPendingLogin,
  login,
  logout,
  syncAccount,
  withTimeout,
  providerLabel,
} from "@/lib/airos";
import ConnectionProbe from "@/components/ConnectionProbe";
import {
  fetchTable,
  type AccountRow,
  type ApplicationRow,
  type DocumentRow,
  type ProfileRow,
} from "@/lib/data";

type Phase = "loading" | "signedout" | "welcome" | "error";

type SyncStatus = { text: string; ok: boolean };

type Tab = "overview" | "applications" | "documents" | "ats";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "applications", label: "Applications" },
  { id: "documents", label: "Documents" },
  { id: "ats", label: "ATS" },
];

type Load<T> = { rows: T[]; error: string };

type DataBundle = {
  account: Load<AccountRow>;
  profile: Load<ProfileRow>;
  applications: Load<ApplicationRow>;
  documents: Load<DocumentRow>;
};

/** One parallel round of RLS-scoped reads per login, cached in state. */
async function loadDashboard(c: Auth0Client): Promise<DataBundle> {
  const [account, profile, applications, documents] = await Promise.all([
    fetchTable<AccountRow>(c, "accounts"),
    fetchTable<ProfileRow>(c, "profiles"),
    fetchTable<ApplicationRow>(c, "applications", "order=updated_at.desc"),
    fetchTable<DocumentRow>(
      c,
      "documents",
      "order=uploaded_at.desc.nullslast,updated_at.desc"
    ),
  ]);
  return { account, profile, applications, documents };
}

export default function AppPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [errMsg, setErrMsg] = useState("");
  const [claims, setClaims] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [apiStatus, setApiStatus] = useState<SyncStatus | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [data, setData] = useState<DataBundle | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const [authNote, setAuthNote] = useState("");

  useEffect(() => {
    let cancelled = false;
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
        const c = await auth0();
        const cl = (await c.getIdTokenClaims()) as unknown as Record<string, unknown> | null;
        if (cancelled) return;
        setClaims(cl ?? {});
        setPhase("welcome");
        try {
          const r = await syncAccount(c);
          if (cancelled) return;
          setStatus({
            text: "sync_my_account() -> HTTP " + r.status + (r.text ? " " + r.text : ""),
            ok: r.status === 200,
          });
        } catch (e) {
          if (cancelled) return;
          setStatus({ text: "sync failed: " + (e as Error).message, ok: false });
        }
        // Slice 5 (DEC-011): backend resource-server wiring probe.
        setApiStatus(await checkBackend());
        // Slice 4b: one cached round of RLS-scoped reads for all module panes.
        try {
          const bundle = await loadDashboard(c);
          if (cancelled) return;
          setData(bundle);
        } catch (e) {
          if (cancelled) return;
          setData({
            account: { rows: [], error: (e as Error).message },
            profile: { rows: [], error: "" },
            applications: { rows: [], error: "" },
            documents: { rows: [], error: "" },
          });
        }
      } catch (e) {
        if (cancelled) return;
        const msg = (e as Error)?.message || "Unexpected error";
        if (!pendingLogin) {
          // Auth0 unreachable but no login is in progress: never block the
          // shell - show the sign-in screen with a note + connectivity probe.
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
        <h1 className="text-3xl font-bold">Could not start the app</h1>
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
        <p className="text-muted mt-3">Sign in with Auth0 to sync your account and enter AIROS.</p>
        {authNote != null && (
          <p className="text-xs text-warn mt-2 mb-0">{authNote}</p>
        )}
        <button type="button" onClick={() => login()} className="btn-primary mt-6">
          Continue with Auth0
        </button>
        <div className="mt-6 max-w-md">
          <ConnectionProbe />
        </div>
      </div>
    );
  }

  // welcome + dashboard (Slice 4b)
  const name = (claims?.name ?? claims?.nickname ?? claims?.email ?? "there") as string;
  const email = (claims?.email ?? claims?.sub ?? "") as string;
  const initials = String(name).slice(0, 1).toUpperCase();
  const verified = claims?.email_verified;
  const badge =
    verified === true ? (
      <span className="badge-ok">email verified</span>
    ) : verified === false ? (
      <span className="badge-warn">verify your email</span>
    ) : (
      <span className="badge-muted">verification unknown</span>
    );

  return (
    <div>
      <div className="card">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="w-11 h-11 rounded-full bg-brand text-white flex items-center justify-center font-bold text-lg">
            {initials}
          </div>
          <div className="flex flex-col min-w-0">
            <h2 className="text-xl font-bold m-0">Welcome, {name}</h2>
            <span className="text-sm break-all">
              {email} | {badge} | provider {providerLabel(claims?.sub as string | undefined)}
            </span>
          </div>
          <button type="button" onClick={() => logout()} className="btn-secondary ml-auto">
            Sign out
          </button>
        </div>
        <pre
          className={
            "mt-4 p-3 rounded-lg border text-xs whitespace-pre-wrap break-words bg-bg " +
            (status == null ? "border-border" : status.ok ? "border-ok" : "border-danger")
          }
        >
          {status == null ? "syncing..." : status.text}
        </pre>
        {apiStatus != null && (
          <p className="mt-2 mb-0 text-xs">
            <span className={apiStatus.ok ? "badge-ok" : "badge-warn"}>{apiStatus.text}</span>
          </p>
        )}
      </div>

      <div className="flex gap-2 mt-5 flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={tab === t.id ? "btn-primary" : "btn-secondary"}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && <OverviewPane data={data} />}
      {tab === "applications" && <ApplicationsPane apps={data?.applications} />}
      {tab === "documents" && <DocumentsPane docs={data?.documents} />}
      {tab === "ats" && <AtsPane apps={data?.applications} />}
    </div>
  );
}

function StatTile({ value, label }: { value: string; label: string }) {
  return (
    <div className="card text-center py-4">
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs text-muted mt-1">{label}</div>
    </div>
  );
}

function OverviewPane({ data }: { data: DataBundle | null }) {
  if (data == null) {
    return (
      <div className="card mt-4">
        <p className="text-muted m-0">Loading your data...</p>
      </div>
    );
  }
  if (data.account.error && data.account.rows.length === 0) {
    return <LoadError error={data.account.error} />;
  }
  const acc = data.account.rows[0];
  const prof = data.profile.rows[0];
  const skillCats =
    prof?.skills && typeof prof.skills === "object" && !Array.isArray(prof.skills)
      ? Object.keys(prof.skills as Record<string, unknown>).length
      : 0;
  return (
    <div className="mt-4">
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
        <StatTile value={acc ? "active" : "not synced"} label="Account row (RLS)" />
        <StatTile value={prof ? (prof.original_cv_count ?? 0) + " CVs" : "-"} label="Original CV count" />
        <StatTile value={String(data.applications.rows.length)} label="Applications" />
        <StatTile value={String(data.documents.rows.length)} label="Documents" />
      </div>

      {prof ? (
        <div className="card mt-3">
          <h3 className="m-0 text-sm font-semibold">Profile snapshot</h3>
          <ul className="text-sm mt-2 mb-0 pl-5">
            <li>
              Career stage: <b>{prof.career_stage || "(not set)"}</b>
            </li>
            <li>
              Strong evidence flag: <b>{prof.strong_evidence ? "yes" : "no"}</b>
            </li>
            <li>
              Skills categories: <b>{skillCats}</b> | languages:{" "}
              <b>{Array.isArray(prof.languages) ? prof.languages.length : 0}</b> | education entries:{" "}
              <b>{Array.isArray(prof.education) ? prof.education.length : 0}</b> | experience entries:{" "}
              <b>{Array.isArray(prof.experience) ? prof.experience.length : 0}</b>
            </li>
            {acc?.source_key ? (
              <li>
                V2 provenance key: <b>{acc.source_key}</b> (migrated data ready)
              </li>
            ) : null}
          </ul>
        </div>
      ) : (
        <div className="card mt-3">
          <h3 className="m-0 text-sm font-semibold">Profile snapshot</h3>
          <p className="text-sm text-muted mt-2 mb-0">
            No profile row yet for your account. V2 career data appears here after the
            migration cutover (Slice 1 output is ready; cutover is a separate approved topic).
          </p>
          <Link href="/profile" className="btn-primary mt-3 inline-block">
            Create your profile
          </Link>
        </div>
      )}

      <div className="card mt-3">
        <h3 className="m-0 text-sm font-semibold">Coming next</h3>
        <div className="grid gap-3 mt-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))" }}>
          <ModuleCard title="CV" desc="Upload, edit and version your CV." />
          <ModuleCard title="Applications" desc="Track applications and their lifecycle." />
          <ModuleCard title="Documents" desc="Cover letters, PDFs and generated outputs." />
          <ModuleCard title="ATS" desc="Deterministic scoring against job-fit criteria." />
        </div>
      </div>
    </div>
  );
}

function AtsPane({ apps }: { apps?: Load<ApplicationRow> }) {
  if (apps == null) {
    return (
      <div className="card mt-4">
        <p className="text-muted m-0">Loading historical scores...</p>
      </div>
    );
  }
  if (apps.error) {
    return <LoadError error={apps.error} />;
  }
  const scores = apps.rows
    .map((a) => (a.ats_score == null ? null : Number(a.ats_score)))
    .filter((n): n is number => n != null && !isNaN(n));
  return (
    <div className="card mt-4">
      <h3 className="m-0 text-sm font-semibold">ATS (historical scores)</h3>
      {scores.length === 0 ? (
        <p className="text-sm text-muted mt-2 mb-0">
          No historical ATS scores on your applications. The deterministic ATS engine
          itself arrives with the backend services slice; per DEC-006 all historical
          scores are recalculated when it runs.
        </p>
      ) : (
        <div className="mt-3">
          <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
            <StatTile value={String(Math.round(Math.max(...scores)))} label="Highest historical score" />
            <StatTile
              value={String(Math.round(scores.reduce((s, n) => s + n, 0) / scores.length))}
              label="Average historical score"
            />
            <StatTile value={String(scores.length)} label="Scored applications" />
          </div>
          <p className="text-xs text-muted mt-3 mb-0">
            Historical values only (migrated from V2). They are not recomputed until the
            ATS engine slice (DEC-006).
          </p>
        </div>
      )}
    </div>
  );
}

function LoadError({ error }: { error: string }) {
  const authIssue = error.includes("401") || error.toLowerCase().includes("jwt");
  return (
    <div className="card mt-4 border border-danger">
      <h3 className="m-0 text-sm font-semibold">Could not load your data</h3>
      <p className="text-sm mt-2 mb-0 break-words">{error}</p>
      {authIssue ? (
        <p className="text-sm text-muted mt-2 mb-0">
          This usually means the session token expired - sign out and sign in again.
        </p>
      ) : null}
    </div>
  );
}

function fmtDate(v: string | null): string {
  if (!v) return "-";
  const d = new Date(v);
  return isNaN(d.getTime()) ? v : d.toISOString().slice(0, 10);
}

function ApplicationsPane({ apps }: { apps?: Load<ApplicationRow> }) {
  if (apps == null) {
    return (
      <div className="card mt-4">
        <p className="text-muted m-0">Loading your applications...</p>
      </div>
    );
  }
  if (apps.error) {
    return <LoadError error={apps.error} />;
  }
  if (apps.rows.length === 0) {
    return (
      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">Applications (live, read-only)</h3>
        <p className="text-sm text-muted mt-2 mb-0">
          No applications yet. Your V2 application history is migrated and appears here
          after the data cutover; creating new applications is part of the backend
          services slice (DEC-011).
        </p>
      </div>
    );
  }
  return (
    <div className="card mt-4 overflow-x-auto">
      <h3 className="m-0 text-sm font-semibold">
        Applications (live, read-only) - {apps.rows.length} row{apps.rows.length === 1 ? "" : "s"}
      </h3>
      <table className="w-full text-sm mt-3 border-collapse">
        <thead>
          <tr className="text-left text-xs text-muted border-b border-border">
            <th className="py-2 pr-3">Title</th>
            <th className="py-2 pr-3">Company</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3">Applied</th>
            <th className="py-2 pr-3">Outcome</th>
            <th className="py-2 pr-3">CV ver.</th>
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
              <td className="py-2 pr-3">{a.cv_version || "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DocumentsPane({ docs }: { docs?: Load<DocumentRow> }) {
  if (docs == null) {
    return (
      <div className="card mt-4">
        <p className="text-muted m-0">Loading your documents...</p>
      </div>
    );
  }
  if (docs.error) {
    return <LoadError error={docs.error} />;
  }
  if (docs.rows.length === 0) {
    return (
      <div className="card mt-4">
        <h3 className="m-0 text-sm font-semibold">Documents (live, read-only)</h3>
        <p className="text-sm text-muted mt-2 mb-0">
          No documents yet. V3 stores document <b>metadata only</b> in the database
          (ISS-006): file bytes live in the protected document store (DEC-012), and
          uploads arrive with the backend services slice (DEC-011).
        </p>
      </div>
    );
  }
  return (
    <div className="card mt-4 overflow-x-auto">
      <h3 className="m-0 text-sm font-semibold">
        Documents (live, read-only) - {docs.rows.length} row{docs.rows.length === 1 ? "" : "s"}
      </h3>
      <table className="w-full text-sm mt-3 border-collapse">
        <thead>
          <tr className="text-left text-xs text-muted border-b border-border">
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Type</th>
            <th className="py-2 pr-3">Size</th>
            <th className="py-2 pr-3">Uploaded</th>
            <th className="py-2 pr-3">Storage ref</th>
          </tr>
        </thead>
        <tbody>
          {docs.rows.map((d) => (
            <tr key={d.id} className="border-b border-border">
              <td className="py-2 pr-3 font-medium">{d.original_name}</td>
              <td className="py-2 pr-3">{d.mime || "-"}</td>
              <td className="py-2 pr-3">{d.size_kb == null ? "-" : d.size_kb + " KB"}</td>
              <td className="py-2 pr-3">{fmtDate(d.uploaded_at)}</td>
              <td className="py-2 pr-3 break-all">{d.storage_ref || "(none)"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModuleCard({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-xl border border-dashed border-border p-4">
      <h3 className="m-0 text-sm font-semibold text-text">{title}</h3>
      <p className="mt-1.5 mb-0 text-xs text-muted">{desc}</p>
    </div>
  );
}
