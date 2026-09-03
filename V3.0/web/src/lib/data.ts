/* AIROS V3 - read-only data access for the dashboard (Slice 4b).
   Fetches the signed-in user's OWN rows via Supabase PostgREST with the
   Auth0 ID token as bearer - the verified per-account RLS path
   (DEC-013/DEC-014, same as sync_my_account / verify_auth0.py).
   Read-only by design: writes belong to the backend services slice (DEC-011). */
import type { Auth0Client } from "@auth0/auth0-spa-js";
import { AIROS } from "./config";

export type AccountRow = {
  id: string;
  email: string;
  auth0_sub: string | null;
  verified: boolean;
  created_at: string;
  updated_at: string;
  source_key: string | null;
};

export type ProfileRow = {
  career_stage: string;
  identity: unknown;
  education: unknown;
  experience: unknown;
  skills: unknown;
  languages: unknown;
  certifications: unknown;
  strong_evidence: boolean;
  original_cv_count: number;
  updated_at: string;
};

export type ApplicationRow = {
  id: string;
  application_id: string;
  job_id: string;
  company_id: string;
  title: string;
  status: string;
  application_date: string | null;
  outcome: string;
  ats_score: number | string | null;
  cv_version: string;
  cover_letter_version: string;
  updated_at: string;
};

export type DocumentRow = {
  id: string;
  original_name: string;
  saved_as: string;
  mime: string;
  size_kb: number | string | null;
  uploaded_at: string | null;
  storage_ref: string;
  updated_at: string;
};

/** GET /rest/v1/{table}?select=*&{query} as the authenticated user.
   Returns rows or a human-readable error string (never throws). */
export async function fetchTable<T>(
  c: Auth0Client,
  table: string,
  query = ""
): Promise<{ rows: T[]; error: string }> {
  const claims = await c.getIdTokenClaims();
  const token = claims?.__raw ?? "";
  const url =
    AIROS.supabaseUrl + "/rest/v1/" + table + "?select=*" + (query ? "&" + query : "");
  let resp: Response;
  try {
    resp = await fetch(url, {
      headers: {
        apikey: AIROS.supabaseKey,
        Authorization: "Bearer " + token,
        Accept: "application/json",
      },
    });
  } catch (e) {
    return { rows: [], error: "network error: " + (e as Error).message };
  }
  if (!resp.ok) {
    let detail = "HTTP " + resp.status;
    try {
      const body = (await resp.json()) as { message?: string };
      if (body?.message) detail += ": " + body.message;
    } catch {
      /* non-JSON error body */
    }
    return { rows: [], error: detail };
  }
  const rows = (await resp.json()) as T[];
  return { rows, error: "" };
}
