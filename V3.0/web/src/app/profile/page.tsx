"use client";
/* AIROS V3 - profile creation wizard (Slice 6, CHG-014).
   Exact port of the V2 onboarding flow:
     cv_choice.py  -> step "choice"          (Road A manual / Road B AI)
     career_stage  -> step "career_stage"    (8 stages, AI suggestion)
     personal_identity -> step "identity"    (EU visa logic included)
     education     -> step "education"       (list + AI prefill)
     experience    -> step "experience"      (list + AI prefill, achievements)
     skills        -> step "skills"          (3 comma inputs + AI prefill)
   Persistence goes through PUT /api/profile (exact migration transform). */
import { useEffect, useState } from "react";
import Link from "next/link";
import { AUTH_TIMEOUT_MS, auth0, getSession, login, withTimeout } from "@/lib/airos";
import {
  CAREER_STAGES,
  EDUCATION_STATUSES,
  EMPLOYMENT_TYPES,
  EU_COUNTRIES,
  emptyDraft,
  extractCv,
  normalizeCareerStage,
  saveProfile,
  type ProfileDraft,
  type ExtractResult,
  type EducationEntry,
  type ExperienceEntry,
} from "@/lib/profile";

type Step = "choice" | "career_stage" | "identity" | "education" | "experience" | "skills" | "done";

export default function ProfilePage() {
  const [phase, setPhase] = useState<"loading" | "signedout" | "wizard" | "error">("loading");
  const [token, setToken] = useState("");
  const [step, setStep] = useState<Step>("choice");
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft());
  const [rich, setRich] = useState<ExtractResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const authed = await withTimeout(
          getSession(),
          AUTH_TIMEOUT_MS,
          "Auth0 is not responding. Check your connection, then retry."
        );
        if (cancelled) return;
        if (!authed) {
          setPhase("signedout");
          return;
        }
        const c = await auth0();
        const claims = await c.getIdTokenClaims();
        if (cancelled) return;
        setToken(claims?.__raw ?? "");
        setPhase("wizard");
      } catch (e) {
        if (!cancelled) {
          setErr((e as Error)?.message ?? "Unexpected error");
          setPhase("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [retryTick]);

  /* ---- Road B: V2 cv_choice.py extract + prefill (exact) ---- */
  async function runExtraction(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setErr("");
    const res = await extractCv(Array.from(files), token);
    setBusy(false);
    if (!res.ok || !res.rich_data) {
      // V2: "Extraction failed. Please try again or use Manual Mode."
      setErr(res.detail ?? "Extraction failed. Please try again or use Manual Mode.");
      return;
    }
    const data = res.rich_data as Record<string, unknown>;
    const next = emptyDraft();
    next.profile_method = "ai";
    next.saved_files = res.saved_files ?? [];
    applyRichData(next, data, langsOf(data));
    setRich(res);
    setDraft(next);
    setStep("career_stage"); // V2: extraction -> career_stage step
  }

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
        <h1 className="text-3xl font-bold">Could not start the profile wizard</h1>
        <p className="text-muted mt-3">{err}</p>
        <div className="flex justify-center gap-3 mt-6 flex-wrap">
          <button type="button" onClick={() => setRetryTick((t) => t + 1)} className="btn-primary">
            Try again
          </button>
          <button type="button" onClick={() => login()} className="btn-secondary">
            Continue with Auth0
          </button>
        </div>
      </div>
    );
  }

  if (phase === "signedout") {
    return (
      <div className="card text-center py-10">
        <h1 className="text-3xl font-bold">You are signed out</h1>
        <p className="text-muted mt-3">Sign in with Auth0 to build your profile.</p>
        <button type="button" onClick={() => login()} className="btn-primary mt-6">
          Continue with Auth0
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold m-0">Build your professional identity</h1>
        <Link href="/app" className="text-sm text-brand underline underline-offset-2">
          ← Back to the app
        </Link>
      </div>
      {err != null && (
        <p role="alert" className="text-danger text-sm mt-3">
          {err}
        </p>
      )}
      {busy && <div className="card mt-3">AIROS is analyzing your CV(s)... This may take a moment</div>}

      {step === "choice" && (
        <ChoiceStep
          busy={busy}
          onExtract={runExtraction}
          onManual={() => {
            // V2 cv_choice.py Road A
            const manual = emptyDraft();
            manual.profile_method = "manual";
            setDraft(manual);
            setRich(null);
            setStep("career_stage");
          }}
        />
      )}

      {step === "career_stage" && (
        <CareerStageStep
          draft={draft}
          suggestion={rich?.career_stage_suggestion ?? ""}
          onBack={() => setStep("choice")}
          onContinue={(stage) => {
            setDraft((d) => ({ ...d, career_stage: stage }));
            setStep("identity");
          }}
        />
      )}

      {step === "identity" && (
        <IdentityStep
          draft={draft}
          aiMode={draft.profile_method === "ai"}
          onBack={() => setStep("career_stage")}
          onContinue={(identity) => {
            setDraft((d) => ({ ...d, identity }));
            setStep("education");
          }}
        />
      )}

      {step === "education" && (
        <EducationStep
          draft={draft}
          onBack={() => setStep("identity")}
          onContinue={(education) => {
            setDraft((d) => ({ ...d, education }));
            setStep("experience");
          }}
        />
      )}

      {step === "experience" && (
        <ExperienceStep
          draft={draft}
          onBack={() => setStep("education")}
          onContinue={(experience) => {
            setDraft((d) => ({ ...d, experience }));
            setStep("skills");
          }}
        />
      )}

      {step === "skills" && (
        <SkillsStep
          draft={draft}
          busy={busy}
          onBack={() => setStep("experience")}
          onFinish={async (skills) => {
            const final: ProfileDraft = { ...draft, skills, onboarding_completed: true };
            setDraft(final);
            setBusy(true);
            setErr("");
            const res = await saveProfile(final, token);
            setBusy(false);
            if (!res.ok) {
              setErr(res.detail ?? "Save failed. Please try again.");
              return;
            }
            setStep("done");
          }}
        />
      )}

      {step === "done" && (
        <div className="card text-center py-10">
          <h2 className="text-2xl font-bold m-0">Profile saved!</h2>
          <p className="text-muted mt-3">
            Your professional identity is ready
            {draft.profile_method === "ai" ? " (built from your CV with AIROS extraction)" : ""}.
          </p>
          <Link href="/app" className="btn-primary mt-6 inline-block">
            Go to your dashboard
          </Link>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Prefill helpers (V2 cv_choice.py 2b + onboarding prefill logic, exact)
--------------------------------------------------------------------------- */
function langsOf(data: Record<string, unknown>): { language: string; level: string }[] {
  return (data["languages"] as { language: string; level: string }[]) ?? [];
}

function applyRichData(
  next: ProfileDraft,
  data: Record<string, unknown>,
  langs: { language: string; level: string }[]
): void {
  // V2 cv_choice.py 2b: skills/languages/certifications survive early saves
  const skills = data["skills"] as Record<string, string[]> | undefined;
  if (skills && typeof skills === "object") {
    next.skills = {
      technical: skills["technical"] ?? [],
      methodologies: skills["methodologies"] ?? [],
      tools: skills["tools"] ?? [],
      core: skills["core"] ?? [],
    };
  } else {
    const tech = (data["technical_skills"] as string[]) ?? [];
    const core = (data["core_skills"] as string[]) ?? [];
    if (tech.length || core.length) {
      next.skills = { technical: tech, core, methodologies: [], tools: [] };
    }
  }
  if (langs.length) next.languages = langs;
  const certs = (data["certifications"] as ProfileDraft["certifications"]) ?? [];
  if (certs.length) next.certifications = certs;

  // V2 personal_identity.py prefill: split full name, split location
  const aiIdentity = (data["personal_identity"] as Record<string, string>) ?? {};
  const fullName = aiIdentity["full_name"] ?? "";
  const parts = fullName.trim().split(" ");
  next.identity.first_name = parts.length >= 2 ? parts[0] : fullName;
  next.identity.last_name = parts.length >= 2 ? parts.slice(1).join(" ") : "";
  const location = aiIdentity["location"] ?? "";
  if (location.includes(",")) {
    next.identity.city = location.split(",")[0].trim();
    next.identity.country = location.split(",").slice(-1)[0].trim();
  } else {
    next.identity.country = location;
  }
  next.identity.nationality = next.identity.country;
  next.identity.whatsapp = aiIdentity["phone"] ?? "";
  next.identity.linkedin = aiIdentity["linkedin"] ?? "";
  next.identity.github = aiIdentity["github"] ?? "";
  next.identity.languages = langs
    .map((l) => `${l.language ?? ""} ${l.level ?? ""}`.trim())
    .join(", ");

  // V2 education.py prefill: field -> field_of_study, status "Completed"
  const aiEdu = (data["education"] as Record<string, string>[]) ?? [];
  next.education = aiEdu.map((e) => ({
    degree: e["degree"] ?? "",
    institution: e["institution"] ?? "",
    field_of_study: e["field"] ?? "",
    status: "Completed",
    start_year: e["start_year"] ?? "",
    end_year: e["end_year"] ?? "",
    location: e["location"] ?? "",
    description: e["description"] ?? "",
  }));

  // V2 experience.py prefill: role -> title, achievements -> bullets
  const aiExp =
    ((data["professional_experience"] ?? data["experience"] ?? data["experiences"]) as
      Record<string, unknown>[]) ?? [];
  next.experience = aiExp
    .filter((e) => typeof e === "object" && e != null)
    .map((e) => {
      const description = String(e["description"] ?? "");
      const achievements = e["achievements"];
      const bullets = Array.isArray(achievements)
        ? achievements.filter(Boolean).map((a) => "• " + String(a)).join("\n")
        : "";
      return {
        company: String(e["company"] ?? ""),
        title: String(e["role"] ?? e["title"] ?? ""),
        location: String(e["location"] ?? ""),
        employment_type: String(e["employment_type"] ?? "Full-time"),
        start_date: String(e["start_date"] ?? ""),
        end_date: (e["end_date"] as string) ?? "",
        currently_working: Boolean(e["currently_working"] ?? false),
        description: `${description}\n${bullets}`.trim(),
      } satisfies ExperienceEntry;
    });
}

/* ---------------------------------------------------------------------------
   Step 1: choice (V2 cv_choice.py, verbatim copy)
--------------------------------------------------------------------------- */
function ChoiceStep({
  busy,
  onExtract,
  onManual,
}: {
  busy: boolean;
  onExtract: (files: FileList | null) => void;
  onManual: () => void;
}) {
  const [files, setFiles] = useState<FileList | null>(null);
  return (
    <div>
      <div className="card text-center mt-4">
        <h2 className="text-xl font-bold m-0">Welcome to AIROS</h2>
        <p className="text-muted mt-2 mb-0">How do you want to build your professional identity?</p>
        <p className="text-xs text-muted mt-1 mb-0">You can always enrich or edit your profile later.</p>
      </div>

      <div className="grid gap-4 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        {/* Road A - Manual (V2 col1) */}
        <div className="card">
          <h3 className="m-0">✍️ Manual Mode</h3>
          <p className="text-sm text-muted mt-2">You will fill all information yourself step by step.</p>
          <button type="button" onClick={onManual} className="btn-primary w-full mt-4" disabled={busy}>
            Continue with Manual Mode
          </button>
        </div>

        {/* Road B - AI Powered (V2 col2) */}
        <div className="card">
          <h3 className="m-0">🤖 AI-Powered Mode</h3>
          <p className="text-sm text-muted mt-2">
            Upload one or several CVs. AIROS will extract the data and pre-fill the forms.
          </p>
          <input
            type="file"
            accept=".pdf,.docx"
            multiple
            disabled={busy}
            onChange={(e) => setFiles(e.target.files)}
            className="mt-3 text-sm"
          />
          {files != null && files.length > 0 && (
            <ul className="text-xs text-muted mt-2 mb-0 pl-5">
              {Array.from(files).map((f) => (
                <li key={f.name}>• {f.name}</li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={() => onExtract(files)}
            className="btn-primary w-full mt-4"
            disabled={busy || files == null || files.length === 0}
          >
            Extract with AIROS & Continue
          </button>
        </div>
      </div>

      <p className="text-xs text-muted mt-4">
        You can upload multiple versions of your CV. AIROS will combine them to build the richest
        possible profile. (PDF or DOCX)
      </p>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Step 2: career stage (V2 career_stage.py, verbatim)
--------------------------------------------------------------------------- */
function CareerStageStep({
  draft,
  suggestion,
  onBack,
  onContinue,
}: {
  draft: ProfileDraft;
  suggestion: string;
  onBack: () => void;
  onContinue: (stage: string) => void;
}) {
  const [selected, setSelected] = useState<string>(draft.career_stage);
  const normalized = normalizeCareerStage(suggestion);
  return (
    <div className="card mt-4">
      <h2 className="text-lg font-bold m-0">Let&apos;s build your professional identity</h2>
      <p className="text-sm text-muted mt-2 mb-4">
        This helps us personalize your experience and give you better recommendations.
      </p>
      <h3 className="text-sm font-semibold m-0">What best describes your current situation?</h3>
      {draft.profile_method === "ai" && normalized && (
        <p className="text-sm mt-2 mb-0">
          <span className="badge-ok">AI suggestion: {normalized} (you can change it)</span>
        </p>
      )}
      <div className="mt-3 flex flex-col gap-2">
        {CAREER_STAGES.map((stage) => (
          <label key={stage} className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="radio"
              name="career_stage"
              checked={selected === stage}
              onChange={() => setSelected(stage)}
            />
            {stage}
          </label>
        ))}
      </div>
      <div className="flex gap-2 mt-5">
        <button type="button" onClick={onBack} className="btn-secondary">
          ← Back
        </button>
        <button
          type="button"
          onClick={() => onContinue(selected)}
          className="btn-primary ml-auto"
          disabled={!selected}
        >
          Continue →
        </button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Step 3: personal identity (V2 personal_identity.py, verbatim incl. EU visa)
--------------------------------------------------------------------------- */
function IdentityStep({
  draft,
  aiMode,
  onBack,
  onContinue,
}: {
  draft: ProfileDraft;
  aiMode: boolean;
  onBack: () => void;
  onContinue: (identity: ProfileDraft["identity"]) => void;
}) {
  const [form, setForm] = useState<ProfileDraft["identity"]>(draft.identity);
  const [errLocal, setErrLocal] = useState("");
  const set = (k: keyof ProfileDraft["identity"], v: string | boolean) =>
    setForm((f) => ({ ...f, [k]: v }));

  // V2 smart visa sponsorship logic
  const isNonEu =
    form.nationality.trim() !== "" &&
    !EU_COUNTRIES.includes(form.nationality.trim().toLowerCase());
  const requiresVisa = isNonEu ? form.requires_visa_sponsorship : false;
  const visaStatus = isNonEu
    ? requiresVisa
      ? form.visa_status || "Requires sponsorship"
      : "No sponsorship required"
    : "EU/EEA citizen";

  function save() {
    if (!form.first_name.trim() || !form.last_name.trim() || !form.country.trim() || !form.nationality.trim()) {
      setErrLocal("Please fill all required fields (*)");
      return;
    }
    setErrLocal("");
    onContinue({
      ...form,
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      country: form.country.trim(),
      city: form.city.trim(),
      nationality: form.nationality.trim(),
      whatsapp: form.whatsapp.trim(),
      linkedin: form.linkedin.trim(),
      github: form.github.trim(),
      languages: form.languages.trim(),
      requires_visa_sponsorship: requiresVisa,
      visa_status: visaStatus,
    });
  }

  return (
    <div className="card mt-4">
      <h2 className="text-lg font-bold m-0">Personal Identity</h2>
      <p className="text-sm text-muted mt-1">Tell us a bit about yourself. You can always edit this later.</p>
      {aiMode && (
        <p className="text-sm mt-2 mb-0">
          <span className="badge-ok">Fields pre-filled from your CV. Please review and adjust if needed.</span>
        </p>
      )}
      {errLocal && <p className="text-danger text-sm mt-2 mb-0">{errLocal}</p>}

      <div className="grid gap-3 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        <label className="text-sm">
          First Name *<input className="input w-full mt-1" value={form.first_name} onChange={(e) => set("first_name", e.target.value)} />
        </label>
        <label className="text-sm">
          Last Name *<input className="input w-full mt-1" value={form.last_name} onChange={(e) => set("last_name", e.target.value)} />
        </label>
        <label className="text-sm">
          Country *<input className="input w-full mt-1" value={form.country} onChange={(e) => set("country", e.target.value)} />
        </label>
        <label className="text-sm">
          City (optional)<input className="input w-full mt-1" value={form.city} onChange={(e) => set("city", e.target.value)} />
        </label>
        <label className="text-sm">
          Nationality *<input className="input w-full mt-1" value={form.nationality} onChange={(e) => set("nationality", e.target.value)} />
        </label>
        <label className="text-sm">
          WhatsApp (for interviews)<input className="input w-full mt-1" value={form.whatsapp} onChange={(e) => set("whatsapp", e.target.value)} />
        </label>
        <label className="text-sm">
          LinkedIn URL (optional)<input className="input w-full mt-1" value={form.linkedin} onChange={(e) => set("linkedin", e.target.value)} />
        </label>
        <label className="text-sm">
          GitHub URL (optional)<input className="input w-full mt-1" value={form.github} onChange={(e) => set("github", e.target.value)} />
        </label>
      </div>
      <VisaBlock form={form} set={set} />
      <LangLicenseBlock form={form} set={set} />

      <div className="flex gap-2 mt-5">
        <button type="button" onClick={onBack} className="btn-secondary">← Back</button>
        <button type="button" onClick={save} className="btn-primary ml-auto">Save & Continue →</button>
      </div>
    </div>
  );
}

function VisaBlock({
  form,
  set,
}: {
  form: ProfileDraft["identity"];
  set: (k: keyof ProfileDraft["identity"], v: string | boolean) => void;
}) {
  const isNonEu =
    form.nationality.trim() !== "" &&
    !EU_COUNTRIES.includes(form.nationality.trim().toLowerCase());
  if (!isNonEu) {
    if (form.nationality.trim() === "") return null;
    return <p className="text-xs text-muted mt-3 mb-0">Visa status: EU/EEA citizen — no sponsorship required.</p>;
  }
  return (
    <div className="mt-3 text-sm">
      <span className="badge-warn">Your nationality is outside the EU/EEA.</span>
      <label className="flex items-center gap-2 mt-2 cursor-pointer">
        <input
          type="checkbox"
          checked={form.requires_visa_sponsorship}
          onChange={(e) => set("requires_visa_sponsorship", e.target.checked)}
        />
        I require visa sponsorship
      </label>
      {form.requires_visa_sponsorship && (
        <label className="block mt-2">
          Please clarify your situation
          <input
            className="input w-full mt-1"
            placeholder="e.g. Student visa, work permit needed..."
            value={
              form.visa_status === "EU/EEA citizen" || form.visa_status === "No sponsorship required"
                ? ""
                : form.visa_status
            }
            onChange={(e) => set("visa_status", e.target.value)}
          />
        </label>
      )}
    </div>
  );
}

function LangLicenseBlock({
  form,
  set,
}: {
  form: ProfileDraft["identity"];
  set: (k: keyof ProfileDraft["identity"], v: string | boolean) => void;
}) {
  return (
    <div>
      <label className="block text-sm mt-4">
        Languages you speak (e.g. French C2, English C1, Arabic Native)
        <input className="input w-full mt-1" value={form.languages} onChange={(e) => set("languages", e.target.value)} />
      </label>
      <label className="flex items-center gap-2 text-sm mt-3 cursor-pointer">
        <input
          type="checkbox"
          checked={form.has_driver_license}
          onChange={(e) => set("has_driver_license", e.target.checked)}
        />
        I have a driver&apos;s license
      </label>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Step 4: education (V2 education.py, verbatim)
--------------------------------------------------------------------------- */
function EducationStep({
  draft,
  onBack,
  onContinue,
}: {
  draft: ProfileDraft;
  onBack: () => void;
  onContinue: (education: EducationEntry[]) => void;
}) {
  const [list, setList] = useState<EducationEntry[]>(draft.education);
  const [f, setF] = useState<EducationEntry>({
    degree: "", institution: "", field_of_study: "", status: "Completed",
    start_year: "", end_year: "",
  });
  const [errLocal, setErrLocal] = useState("");

  function add() {
    if (!f.degree.trim() || !f.institution.trim()) {
      setErrLocal("Degree and Institution are required.");
      return;
    }
    setErrLocal("");
    setList((l) => [...l, { ...f, degree: f.degree.trim(), institution: f.institution.trim() }]);
    setF({ degree: "", institution: "", field_of_study: "", status: "Completed", start_year: "", end_year: "" });
  }

  return (
    <div className="card mt-4">
      <h2 className="text-lg font-bold m-0">Education</h2>
      <p className="text-sm text-muted mt-1">Add your education background. You can add multiple entries.</p>

      {list.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold m-0">Your Education</h3>
          <ul className="text-sm mt-2 mb-0 pl-5">
            {list.map((e, i) => (
              <li key={i} className="mt-1">
                {e.degree} — {e.institution} ({e.start_year} → {e.end_year}){" "}
                <button type="button" onClick={() => setList((l) => l.filter((_, j) => j !== i))} className="text-danger underline ml-1">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <h3 className="text-sm font-semibold mt-4 mb-0">Add Education</h3>
      {errLocal && <p className="text-danger text-sm mt-2 mb-0">{errLocal}</p>}
      <div className="grid gap-3 mt-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        <label className="text-sm">Degree / Diploma *
          <input className="input w-full mt-1" placeholder="e.g. Master's Degree, Bachelor, PhD..." value={f.degree} onChange={(e) => setF({ ...f, degree: e.target.value })} />
        </label>
        <label className="text-sm">Institution *
          <input className="input w-full mt-1" placeholder="e.g. University of Tunis" value={f.institution} onChange={(e) => setF({ ...f, institution: e.target.value })} />
        </label>
        <label className="text-sm">Field of Study
          <input className="input w-full mt-1" placeholder="e.g. Information Systems" value={f.field_of_study} onChange={(e) => setF({ ...f, field_of_study: e.target.value })} />
        </label>
        <label className="text-sm">Status *
          <select className="input w-full mt-1" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            {EDUCATION_STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className="text-sm">Start Year
          <input className="input w-full mt-1" placeholder="2019" value={f.start_year} onChange={(e) => setF({ ...f, start_year: e.target.value })} />
        </label>
        <label className="text-sm">End Year (or Expected)
          <input className="input w-full mt-1" placeholder="2023" value={f.end_year} onChange={(e) => setF({ ...f, end_year: e.target.value })} />
        </label>
      </div>
      <button type="button" onClick={add} className="btn-secondary w-full mt-3">➕ Add this Education</button>

      <div className="flex gap-2 mt-5">
        <button type="button" onClick={onBack} className="btn-secondary">← Back</button>
        <button type="button" onClick={() => onContinue(list)} className="btn-primary ml-auto">Save & Continue →</button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Step 5: experience (V2 experience.py, verbatim)
--------------------------------------------------------------------------- */
function ExperienceStep({
  draft,
  onBack,
  onContinue,
}: {
  draft: ProfileDraft;
  onBack: () => void;
  onContinue: (experience: ExperienceEntry[]) => void;
}) {
  const [list, setList] = useState<ExperienceEntry[]>(draft.experience);
  const [f, setF] = useState<ExperienceEntry>({
    company: "", title: "", location: "", employment_type: "Full-time",
    start_date: "", end_date: "", currently_working: false, description: "",
  });
  const [errLocal, setErrLocal] = useState("");

  function add() {
    if (!f.company.trim() || !f.title.trim() || !f.start_date.trim()) {
      setErrLocal("Company, Job Title and Start Date are required.");
      return;
    }
    setErrLocal("");
    setList((l) => [
      ...l,
      {
        ...f,
        company: f.company.trim(),
        title: f.title.trim(),
        location: f.location.trim(),
        start_date: f.start_date.trim(),
        end_date: f.currently_working ? null : (f.end_date ?? "").trim() || null,
        description: f.description.trim(),
      },
    ]);
    setF({ company: "", title: "", location: "", employment_type: "Full-time", start_date: "", end_date: "", currently_working: false, description: "" });
  }

  return (
    <div className="card mt-4">
      <h2 className="text-lg font-bold m-0">Professional Experience</h2>
      <p className="text-sm text-muted mt-1">Add your professional experience. You can add multiple entries.</p>

      {list.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold m-0">Your Experience</h3>
          <ul className="text-sm mt-2 mb-0 pl-5">
            {list.map((e, i) => (
              <li key={i} className="mt-1">
                {e.title} — {e.company} ({e.start_date} → {e.currently_working ? "Present" : e.end_date || "?"})
                <button type="button" onClick={() => setList((l) => l.filter((_, j) => j !== i))} className="text-danger underline ml-2">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <h3 className="text-sm font-semibold mt-4 mb-0">Add Experience</h3>
      {errLocal && <p className="text-danger text-sm mt-2 mb-0">{errLocal}</p>}
      <div className="grid gap-3 mt-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        <label className="text-sm">Company / Organization *
          <input className="input w-full mt-1" placeholder="e.g. Google, Self-employed" value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} />
        </label>
        <label className="text-sm">Job Title *
          <input className="input w-full mt-1" placeholder="e.g. Software Engineer, Product Manager" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        </label>
        <label className="text-sm">Location
          <input className="input w-full mt-1" placeholder="e.g. Remote, Paris, France" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} />
        </label>
        <label className="text-sm">Employment Type
          <select className="input w-full mt-1" value={f.employment_type} onChange={(e) => setF({ ...f, employment_type: e.target.value })}>
            {EMPLOYMENT_TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label className="text-sm">Start Date *
          <input className="input w-full mt-1" placeholder="2021-03 or March 2021" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} />
        </label>
        {!f.currently_working && (
          <label className="text-sm">End Date
            <input className="input w-full mt-1" placeholder="2023-08 or August 2023" value={f.end_date ?? ""} onChange={(e) => setF({ ...f, end_date: e.target.value })} />
          </label>
        )}
      </div>
      <label className="flex items-center gap-2 text-sm mt-2 cursor-pointer">
        <input type="checkbox" checked={f.currently_working} onChange={(e) => setF({ ...f, currently_working: e.target.checked })} />
        I currently work here
      </label>
      <label className="block text-sm mt-3">
        Description / Achievements
        <textarea
          className="input w-full mt-1"
          rows={4}
          placeholder="Key responsibilities, impact, technologies used..."
          value={f.description}
          onChange={(e) => setF({ ...f, description: e.target.value })}
        />
      </label>
      <button type="button" onClick={add} className="btn-secondary w-full mt-3">➕ Add this Experience</button>

      <div className="flex gap-2 mt-5">
        <button type="button" onClick={onBack} className="btn-secondary">← Back</button>
        <button type="button" onClick={() => onContinue(list)} className="btn-primary ml-auto">Save & Continue →</button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Step 6: skills (V2 skills.py, verbatim - 3 comma-separated inputs)
--------------------------------------------------------------------------- */
function SkillsStep({
  draft,
  busy,
  onBack,
  onFinish,
}: {
  draft: ProfileDraft;
  busy: boolean;
  onBack: () => void;
  onFinish: (skills: ProfileDraft["skills"]) => void;
}) {
  const [tech, setTech] = useState(draft.skills.technical.join(", "));
  const [method, setMethod] = useState(draft.skills.methodologies.join(", "));
  const [tools, setTools] = useState(draft.skills.tools.join(", "));

  const parse = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

  return (
    <div className="card mt-4">
      <h2 className="text-lg font-bold m-0">Skills &amp; Competencies</h2>
      <p className="text-sm text-muted mt-1">
        Add your core professional skills, methodologies, and tools to optimize your ATS profile matching.
      </p>

      <label className="block text-sm mt-4">
        Technical Languages &amp; Frameworks (comma-separated)
        <input className="input w-full mt-1" placeholder="e.g. Python, SQL, JavaScript" value={tech} onChange={(e) => setTech(e.target.value)} />
      </label>
      <label className="block text-sm mt-3">
        Methodologies &amp; Management
        <input className="input w-full mt-1" placeholder="e.g. Agile, Scrum, Kanban, PMP" value={method} onChange={(e) => setMethod(e.target.value)} />
      </label>
      <label className="block text-sm mt-3">
        Enterprise Software &amp; Tools
        <input className="input w-full mt-1" placeholder="e.g. Odoo, SAP, Jira, Confluence, Git" value={tools} onChange={(e) => setTools(e.target.value)} />
      </label>
      {draft.skills.core.length > 0 && (
        <p className="text-xs text-muted mt-2 mb-0">
          Core (soft) skills from your CV: {draft.skills.core.join(", ")}
        </p>
      )}

      <div className="flex gap-2 mt-5">
        <button type="button" onClick={onBack} className="btn-secondary">← Back</button>
        <button
          type="button"
          onClick={() =>
            onFinish({
              technical: parse(tech),
              methodologies: parse(method),
              tools: parse(tools),
              core: draft.skills.core,
            })
          }
          className="btn-primary ml-auto"
          disabled={busy}
        >
          Finish & Save Profile →
        </button>
      </div>
    </div>
  );
}

