"use client";
/* AIROS V3 - ATS Job Analyzer client (DEC-006 increment).
   POST /api/ats/analyze: pasted JD -> ONE Gemini call (server-side) ->
   deterministic V2 engine -> threshold + hard-blocker verdict. */

import { apiUrl } from "./config";

export type AtsVerdict = {
  band: "hard_reject" | "soft_reject" | "blockers" | "manual" | "proceed";
  title?: string;
  message: string;
  next_step?: string;
  proceed: boolean;
};

export type AtsResult = {
  ats_score: number;
  overall_ats: number;
  decision: string;
  sub_scores: Record<string, number>;
  gap_analysis: { missing: string[]; strengths: string[] };
  evidence: { item: string; category: string; level: number; stars: string; source: string }[];
  hard_blockers: string[];
  blocker_explanations: string[];
  visa_note?: string;
  parsed_job: Record<string, unknown>;
  /** The candidate JSON the score was computed against (built from the OWN profile). */
  parsed_cv?: Record<string, unknown>;
  /** True when the JD parse produced no requirements -> the score is a safe NO. */
  parse_failed?: boolean;
  verdict: AtsVerdict;
};

export type AnalyzeResult =
  | { ok: true; result: AtsResult }
  | { ok: false; detail: string };

const ANALYZE_TIMEOUT_MS = 120_000;

/** POST /api/ats/analyze - wrapped in a 120s abort timeout so a hung
    connection can never leave the UI stuck on "Analyzing..." forever. */
export async function analyzeJob(
  jobText: string,
  token: string,
  forceRefresh = false
): Promise<AnalyzeResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ANALYZE_TIMEOUT_MS);
  try {
    const resp = await fetch(apiUrl() + "/api/ats/analyze", {
      method: "POST",
      headers: {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ job_text: jobText, force_refresh: forceRefresh }),
      signal: controller.signal,
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      return {
        ok: false,
        detail:
          (body as { detail?: string })?.detail ??
          "Analysis failed (HTTP " + resp.status + ")",
      };
    }
    return { ok: true, result: body as AtsResult };
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      return { ok: false, detail: "Analysis timed out. Please try again." };
    }
    return { ok: false, detail: "backend unreachable: " + (e as Error).message };
  } finally {
    clearTimeout(timer);
  }
}