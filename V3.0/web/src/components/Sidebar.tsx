"use client";
/* AIROS V3 - persistent sidebar navigation (CHG-025).
   JOB ANALYSES WORKFLOW MENU SET (user request, 15 Sep 2026):
       Dashboard
     ①  Job Analyses                 - ALWAYS visible: paste a JD, AIROS verifies
                                       it and returns the ATS + compatibility verdict.
     ②  🛠️ Application Workshop       - APPEARS in the sidebar as soon as an
                                       analysis PASSED (that is the "next menu").
     ③  🗂️ App Workspace / Preparation - the workshop's hands-on step, while the
                                       run has no confirmed application yet.
     ④  📈 Job Tracking               - appears once at least one application exists.
     ☐  My Profile
   The four application entries share the /applications route and are selected
   with the ?stage= query param (deep link); `analyze` is the default stage.
   The run state (a passed analysis / saved job / tracked count) lives in
   lib/workspace.ts so the menu set stays correct on EVERY page. */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { logout } from "@/lib/airos";
import { useRunState } from "@/lib/workspace";

const APPLICATIONS_BASE = "/applications";

/** Workflow stages of the application engine (one route, ?stage= deep link). */
export type AppStage = "analyze" | "workshop" | "prepare" | "track";

type NavItem = {
  key: string;
  label: string;
  icon: string;
  href: string;
  /** Selected with ?stage= on the shared /applications route. */
  stage?: AppStage;
  /** Rendered indented, as a child of the Job Analyses submenu. */
  child?: boolean;
};

/** The menu set as a pure function of the run state (deterministic, testable):
    no analysis yet -> only ① Job Analyses is offered; a passed analysis reveals
    ② Application Workshop (plus ③ while nothing is confirmed yet); a confirmed
    application reveals ④ Job Tracking. */
export function navItems(hasRun: boolean, tracked: number): NavItem[] {
  const items: NavItem[] = [
    { key: "dashboard", label: "Dashboard", icon: "◫", href: "/app" },
    { key: "analyze", label: "Job Analyses", icon: "🔍", href: APPLICATIONS_BASE, stage: "analyze" },
  ];
  if (hasRun) {
    items.push({
      key: "workshop",
      label: "Application Workshop",
      icon: "🛠️",
      href: APPLICATIONS_BASE,
      stage: "workshop",
      child: true,
    });
    if (tracked === 0) {
      items.push({
        key: "prepare",
        label: "App Workspace / Preparation",
        icon: "🗂️",
        href: APPLICATIONS_BASE,
        stage: "prepare",
        child: true,
      });
    }
  }
  if (tracked > 0) {
    items.push({
      key: "track",
      label: "Job Tracking",
      icon: "📈",
      href: APPLICATIONS_BASE,
      stage: "track",
      child: true,
    });
  }
  items.push({ key: "profile", label: "My Profile", icon: "☐", href: "/profile" });
  return items;
}

export default function Sidebar({
  activeStage,
  trackedCount,
}: {
  /** Stage the hosting page is currently on (the workspace owns this state). */
  activeStage?: AppStage;
  /** Live application count when the page has already loaded it. */
  trackedCount?: number;
}) {
  const pathname = usePathname();
  const run = useRunState();
  // The application menus share one route; the active entry follows the
  // ?stage= query param (window read - useSearchParams would force a Suspense
  // boundary on every statically-prerendered page).
  const [stageQ, setStageQ] = useState("");
  useEffect(() => {
    setStageQ(new URLSearchParams(window.location.search).get("stage") ?? "");
  }, [pathname]);

  // Gate the menu set on the shared run state (a page that already loaded the
  // live data passes its own count, which wins over the cached one).
  const tracked = trackedCount ?? run.tracked ?? 0;
  const items = navItems(run.pending != null, tracked);
  const current = activeStage ?? (stageQ || "analyze");

  return (
    <aside className="w-56 shrink-0 border-r border-border bg-surface min-h-screen flex flex-col">
      <div className="px-4 py-4 border-b border-border flex items-center gap-2 font-bold">
        <span className="w-3 h-3 rounded-full bg-brand" aria-hidden="true" />
        AIROS <span className="text-muted font-normal text-sm">V3</span>
      </div>
      <nav className="flex-1 px-2 py-3 flex flex-col gap-1">
        {items.map((item) => {
          const active =
            pathname === item.href &&
            (item.href !== APPLICATIONS_BASE || (item.stage ?? "analyze") === current);
          return (
            <Link
              key={item.key}
              href={item.stage ? `${item.href}?stage=${item.stage}` : item.href}
              data-menu={item.key}
              className={
                "flex items-start gap-2 py-2 rounded-lg text-sm " +
                (item.child ? "pl-8 pr-3" : "px-3") +
                " " +
                (active ? "bg-brand/10 text-brand font-semibold" : "text-text hover:bg-bg")
              }
            >
              <span aria-hidden="true">{item.icon}</span>
              <span className="leading-snug">{item.label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="px-2 py-3 border-t border-border">
        <button
          type="button"
          onClick={() => logout()}
          className="w-full text-left px-3 py-2 rounded-lg text-sm text-muted hover:bg-bg"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}