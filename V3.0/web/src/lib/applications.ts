"use client";
/* AIROS V3 - Application client (CHG-018 — CHG-017 ATS workspace follow-on).
   Wraps the /api/applications router: save analyzed job, document engine,
   confirm application, tracking transitions, generated-document download.
   Every call forwards the Auth0 ID token as bearer (RLS boundary). */

import { apiUrl } from "./config";

export type SaveJobResult = {
  job: Record<string, unknown>;
  company: Record<string, unknown>;
  contact: Record<string, unknown> | null;
  /** Set when a migration-0008 column was missing on the live DB and the
      value was NOT saved (backend resilience - never silently lost). */
  schema_warning?: string;
};

export type DocsResult = {
  job_id: string;
  generated: Record<string, unknown>;
  validation: Record<string, unknown>;
  reliable_contact: Record<string, unknown>;
  docs: Record<string, string>;
  docs_generated_at: string;
  /** CHG-026: professional DOCX/PDF rendering report (failures are recorded
      here and never block or rewrite the generated text content). */
  rendering?: RenderingReport;
};

/** One document's rendering outcome (CHG-026). */
export type RenderedDocumentReport = {
  ok?: boolean;
  errors?: string[];
  docx?: { saved_as?: string; storage_ref?: string; size_kb?: number };
  pdf?: { saved_as?: string; storage_ref?: string; size_kb?: number };
};

export type RenderingReport = {
  pdf_available?: boolean;
  documents?: Record<string, RenderedDocumentReport>;
  errors?: string[];
};

export type DocumentFormat = "docx" | "pdf";

export type ConfirmResult = {
  created: boolean;
  application_id: string;
  application?: Record<string, unknown>;
};

function req(token: string, init?: RequestInit): RequestInit {
  return {
    ...init,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  };
}

async function call<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(apiUrl() + path, req(token, init));
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(
      (body as { detail?: string })?.detail ?? `Request failed (HTTP ${resp.status})`,
    );
  }
  return body as T;
}

export type JobContact = {
  name?: string;
  position?: string;
  email?: string;
  phone?: string;
  linkedin_url?: string;
  contact_type?: string;
  source?: string;
  confidence?: string;
};

export async function saveAnalyzedJob(
  token: string,
  payload: {
    analysis: Record<string, unknown>;
    original_jd: string;
    contact?: JobContact;
  },
): Promise<SaveJobResult> {
  return call<SaveJobResult>("/api/applications/jobs", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** V2 add_contact_to_job: link another recruiter contact to a saved job. */
export async function addJobContact(
  token: string,
  jobId: string,
  contact: JobContact,
): Promise<{ contact: Record<string, unknown>; contact_ids: string[] }> {
  return call("/api/applications/jobs/" + encodeURIComponent(jobId) + "/contacts", token, {
    method: "POST",
    body: JSON.stringify(contact),
  });
}

export async function generateDocuments(
  token: string,
  jobId: string,
  opts?: { generate_cv?: boolean; generate_cover_letter?: boolean; generate_recruiter_email?: boolean },
): Promise<DocsResult> {
  return call<DocsResult>(`/api/applications/jobs/${encodeURIComponent(jobId)}/documents`, token, {
    method: "POST",
    body: JSON.stringify({
      generate_cv: opts?.generate_cv ?? true,
      generate_cover_letter: opts?.generate_cover_letter ?? true,
      generate_recruiter_email: opts?.generate_recruiter_email ?? true,
    }),
  });
}

export async function confirmApplication(
  token: string,
  payload: { job_id: string; decision: "sent" | "cancelled"; channel?: string; application_date?: string; notes?: string },
): Promise<ConfirmResult> {
  return call<ConfirmResult>("/api/applications", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function applicationDetail(
  token: string,
  applicationId: string,
): Promise<{ application: Record<string, unknown> }> {
  return call(`/api/applications/${encodeURIComponent(applicationId)}`, token);
}

export async function applicationAction(
  token: string,
  applicationId: string,
  action: string,
  payload: Record<string, unknown> = {},
): Promise<{ application: Record<string, unknown> }> {
  return call(
    `/api/applications/${encodeURIComponent(applicationId)}/${action}`,
    token,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function downloadDocumentText(
  token: string,
  documentId: string,
): Promise<string> {
  const resp = await fetch(
    apiUrl() + `/api/applications/documents/${encodeURIComponent(documentId)}/content`,
    { headers: { Authorization: "Bearer " + token } },
  );
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(
      (body as { detail?: string })?.detail ?? `Download failed (HTTP ${resp.status})`,
    );
  }
  return resp.text();
}

/** CHG-026: download a rendered rendition (DOCX | PDF) of one document.
    The backend resolves the rendition from the document's timestamp stem in
    the protected store; a missing rendition is an actionable 409 message. */
export async function downloadDocumentFile(
  token: string,
  documentId: string,
  format: DocumentFormat,
): Promise<{ blob: Blob; filename: string }> {
  const resp = await fetch(
    apiUrl() +
      `/api/applications/documents/${encodeURIComponent(documentId)}/file?format=${format}`,
    { headers: { Authorization: "Bearer " + token } },
  );
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(
      (body as { detail?: string })?.detail ?? `Download failed (HTTP ${resp.status})`,
    );
  }
  const blob = await resp.blob();
  const disposition = resp.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return { blob, filename: match?.[1] ?? `document_${documentId}.${format}` };
}
