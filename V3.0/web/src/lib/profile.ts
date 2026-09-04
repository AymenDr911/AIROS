"use client";
/* AIROS V3 - profile creation flow (Slice 6, CHG-014).
   Exact V2 parity with app/onboarding/* + services/cv_extractor.py:
   the CAREER_STAGES list, EU-countries visa logic, employment types,
   education statuses and the V2 data shapes are ported verbatim.
   Writes go through the V3 backend (PUT /api/profile) which applies the
   exact migration transform; extraction goes through POST /api/profile/
   extract-cv (Gemini via the AI gateway, server-side key only). */
import { apiUrl } from "./config";

export const CAREER_STAGES = [
  "Student / Recent Graduate",
  "Looking for Internship",
  "Entry-Level Professional (0–2 years)",
  "Experienced Professional (3–8 years)",
  "Senior Expert / Manager (8+ years)",
  "Freelancer / Consultant",
  "Entrepreneur / Business Owner",
  "Career Transition / Changing Path",
];

/* V2 personal_identity.py EU/EEA list (verbatim) */
export const EU_COUNTRIES = [
  "france", "germany", "belgium", "netherlands", "luxembourg", "italy", "spain",
  "portugal", "austria", "ireland", "finland", "greece", "slovakia", "slovenia",
  "estonia", "latvia", "lithuania", "cyprus", "malta", "croatia", "sweden", "denmark",
  "poland", "czech republic", "czechia", "hungary", "romania", "bulgaria",
];

export const EMPLOYMENT_TYPES = [
  "Full-time", "Part-time", "Contract", "Internship", "Freelance", "Volunteer", "Other",
];

export const EDUCATION_STATUSES = ["Completed", "In Progress", "Expected"];

export type SavedFile = {
  original_name: string;
  saved_as: string;
  storage_ref: string;
  uploaded_at: string;
  size_kb: number;
};

export type EducationEntry = {
  degree: string;
  institution: string;
  field_of_study: string;
  status: string;
  start_year: string;
  end_year: string;
  location?: string;
  description?: string;
};

export type ExperienceEntry = {
  company: string;
  title: string;
  location: string;
  employment_type: string;
  start_date: string;
  end_date: string | null;
  currently_working: boolean;
  description: string;
};

export type CertEntry = { name: string; issuer: string; year: string };

export type LanguageEntry = { language: string; level: string };

/* V2 personal_identity dict (manual mode shape, personal_identity.py) */
export type Identity = {
  first_name: string;
  last_name: string;
  country: string;
  city: string;
  nationality: string;
  linkedin: string;
  github: string;
  whatsapp: string;
  languages: string;
  requires_visa_sponsorship: boolean;
  visa_status: string;
  has_driver_license: boolean;
};

export type SkillsDict = {
  technical: string[];
  methodologies: string[];
  tools: string[];
  core: string[];
};

/* The draft the onboarding wizard carries (V2 session_state equivalent). */
export type ProfileDraft = {
  career_stage: string;
  identity: Identity;
  education: EducationEntry[];
  experience: ExperienceEntry[];
  skills: SkillsDict;
  languages: LanguageEntry[];
  certifications: CertEntry[];
  profile_method: "" | "manual" | "ai";
  onboarding_completed: boolean;
  saved_files: SavedFile[];
};

export function emptyDraft(): ProfileDraft {
  return {
    career_stage: "",
    identity: {
      first_name: "", last_name: "", country: "", city: "", nationality: "",
      linkedin: "", github: "", whatsapp: "", languages: "",
      requires_visa_sponsorship: false, visa_status: "", has_driver_license: false,
    },
    education: [],
    experience: [],
    skills: { technical: [], methodologies: [], tools: [], core: [] },
    languages: [],
    certifications: [],
    profile_method: "",
    onboarding_completed: false,
    saved_files: [],
  };
}

/** V2 career_stage.py normalization: exact match first, then a tolerant
    fallback (difflib.get_close_matches in V2). */
export function normalizeCareerStage(suggestion: string): string | null {
  if (!suggestion) return null;
  const s = suggestion.trim();
  const exact = CAREER_STAGES.find((c) => c === s);
  if (exact) return exact;
  const low = s.toLowerCase();
  const loose = CAREER_STAGES.find(
    (c) => c.toLowerCase() === low || c.toLowerCase().includes(low) || low.includes(c.toLowerCase())
  );
  return loose ?? null;
}

export type ExtractResult = {
  ok: boolean;
  rich_data?: Record<string, unknown>;
  saved_files?: SavedFile[];
  strong_evidence?: boolean;
  career_stage_suggestion?: string;
  detail?: string;
};

/** POST /api/profile/extract-cv - Road B (V2 extract_rich_profile). */
export async function extractCv(files: File[], token: string): Promise<ExtractResult> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  try {
    const resp = await fetch(apiUrl() + "/api/profile/extract-cv", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
      body: form,
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      return { ok: false, detail: (body as { detail?: string })?.detail ?? "Extraction failed (HTTP " + resp.status + ")" };
    }
    const { ok: _unused, ...rest } = body as ExtractResult;
    return { ok: true, ...rest };
  } catch (e) {
    return { ok: false, detail: "backend unreachable: " + (e as Error).message };
  }
}

/** PUT /api/profile - persist via the backend (exact migration transform). */
export async function saveProfile(
  draft: ProfileDraft,
  token: string
): Promise<{ ok: boolean; profile?: Record<string, unknown>; detail?: string }> {
  const payload = {
    career_stage: draft.career_stage,
    personal_identity: draft.identity,
    education: draft.education,
    experience: draft.experience,
    skills: draft.skills,
    languages: draft.languages,
    certifications: draft.certifications,
    profile_method: draft.profile_method,
    onboarding_completed: draft.onboarding_completed,
    saved_files: draft.saved_files,
  };
  try {
    const resp = await fetch(apiUrl() + "/api/profile", {
      method: "PUT",
      headers: {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      return { ok: false, detail: (body as { detail?: string })?.detail ?? "save failed (HTTP " + resp.status + ")" };
    }
    return { ok: true, profile: (body as { profile?: Record<string, unknown> }).profile };
  } catch (e) {
    return { ok: false, detail: "backend unreachable: " + (e as Error).message };
  }
}

