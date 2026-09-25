"use client";
/* AIROS V3 - application-run state shared by the sidebar and the pages (CHG-025).

WHY THIS EXISTS (user request, 15 Sep 2026): the sidebar menu set is
stage-driven ("Application Workshop" appears once a job analysis PASSED), and
the sidebar is rendered by every page (Dashboard / Job Analyses / My Profile).
A `useState` inside one page cannot drive a menu that must stay correct when
the user navigates, so the run state is kept in ONE place:

  - `pending`  : the PASSED analysis + the exact JD text it came from. Its
                 presence is what reveals the "Application Workshop" menu.
  - `saved`    : the saved job/company/contact of the run (SaveJobStep result)
                 so navigating between menus never re-saves a duplicate job.
  - `tracked`  : how many applications the user has (gates "Job Tracking").

sessionStorage (not localStorage) is deliberate: the run belongs to the open
tab/session, and closing the browser clears a half-finished application run
instead of leaking a stale JD into the next visit. Nothing here touches the
backend or the RLS boundary - it is pure client navigation state.
*/

import { useEffect, useState } from "react";
import { type AtsResult } from "./ats";
import { type SaveJobResult } from "./applications";

/** A job offer that passed the ATS gate, with the JD text it was scored from. */
export type PendingAnalysis = { analysis: AtsResult; jobText: string };

const PENDING_KEY = "airos:run:pending";
const SAVED_KEY = "airos:run:saved";
const TRACKED_KEY = "airos:run:tracked";
/** Same-tab change notification (the `storage` event only fires cross-tab). */
const RUN_EVENT = "airos:run-changed";

function store(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null; // Safari private mode / storage disabled - degrade silently.
  }
}

function read<T>(key: string): T | null {
  const s = store();
  if (s == null) return null;
  try {
    const raw = s.getItem(key);
    return raw == null ? null : (JSON.parse(raw) as T);
  } catch {
    return null;
  }
}

function write(key: string, value: unknown | null): void {
  const s = store();
  if (s == null) return;
  try {
    if (value == null) s.removeItem(key);
    else s.setItem(key, JSON.stringify(value));
  } catch {
    /* quota / disabled storage: the UI still works, it just does not persist. */
  }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(RUN_EVENT));
}

export function getPendingAnalysis(): PendingAnalysis | null {
  return read<PendingAnalysis>(PENDING_KEY);
}

export function setPendingAnalysis(value: PendingAnalysis | null): void {
  write(PENDING_KEY, value);
}

export function getSavedJob(): SaveJobResult | null {
  return read<SaveJobResult>(SAVED_KEY);
}

export function setSavedJob(value: SaveJobResult | null): void {
  write(SAVED_KEY, value);
}

export function getTrackedCount(): number | null {
  const value = read<number>(TRACKED_KEY);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function setTrackedCount(value: number | null): void {
  write(TRACKED_KEY, value);
}

/** Drop the run (analysis + saved job) without touching the tracked count. */
export function clearRun(): void {
  write(PENDING_KEY, null);
  write(SAVED_KEY, null);
}

export type RunState = {
  pending: PendingAnalysis | null;
  saved: SaveJobResult | null;
  tracked: number | null;
};

/** Subscribe to the shared run state (client components only). */
export function useRunState(): RunState {
  const [state, setState] = useState<RunState>({ pending: null, saved: null, tracked: null });

  useEffect(() => {
    const sync = () =>
      setState({ pending: getPendingAnalysis(), saved: getSavedJob(), tracked: getTrackedCount() });
    sync();
    window.addEventListener(RUN_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(RUN_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return state;
}
