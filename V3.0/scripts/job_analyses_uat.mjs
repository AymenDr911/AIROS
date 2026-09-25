/* AIROS V3 - CHG-025 UAT driver (Job Analyses menu -> Application Workshop).
   Headless-Chrome click-through of the user-requested flow, with the Auth0 SPA
   cache forged locally and the /api/ats/analyze call STUBBED through
   window.fetch, so the whole UI flow is exercised deterministically without
   spending an AI call:

     1. no run yet      -> sidebar shows "Job Analyses", NOT "Application Workshop"
     2. canned PASS     -> (c) the full report renders, (d) the final decision PASS
                           is at the bottom, (f) "Application Workshop" appears
     3. click decision  -> AIROS closes ① and opens ② Application Workshop
     4. canned FAIL     -> (e) decision NO + the JD zone is cleared for the next offer

   Run: node scripts/job_analyses_uat.mjs   (Next.js server must be on :3000) */

import { spawn } from "node:child_process";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const CPORT = 9226;
const BASE = process.env.AIROS_UAT_BASE || "http://localhost:3000";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- forged (local-only) Auth0 cache: the UI gate needs an "authenticated" ---
// SPA cache entry; every Supabase read will simply 401 (handled by the pages).
const CID = process.env.AUTH0_CLIENT_ID || "";
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const now = Math.floor(Date.now() / 1000);
const jwt = [
  b64({ alg: "RS256", typ: "JWT" }),
  b64({
    sub: "auth0|uat-chg025",
    email: "uat@airos.local",
    email_verified: true,
    name: "AIROS UAT",
    iat: now,
    exp: now + 3600,
  }),
  "uat-signature",
].join(".");
const SCOPE = "openid profile email";
const exp = Date.now() + 3600 * 1000;
const user = { user_id: "auth0|uat-chg025", email: "uat@airos.local", name: "AIROS UAT" };
const decoded = { claims: { sub: user.user_id, email: user.email, __raw: jwt }, user };
const cacheKey = `@@auth0spajs@@::${CID}::${SCOPE}`;
const idTokenKey = `@@auth0spajs@@::${CID}::@@user@@`;
const manifestKey = `@@auth0spajs@@::${CID}`;
const wrapped = JSON.stringify({
  body: {
    id_token: jwt,
    access_token: jwt,
    token_type: "bearer",
    expires_in: 3600,
    decodedToken: decoded,
    audience: "",
    scope: SCOPE,
    client_id: CID,
  },
  expiresAt: exp,
});
const idEntry = JSON.stringify({ id_token: jwt, decodedToken: decoded });
const manifest = JSON.stringify({ keys: [cacheKey, idTokenKey] });
const results = [];
// --- canned ATS verdicts (same shape as POST /api/ats/analyze) -------------
const PASS = {
  ats_score: 92,
  overall_ats: 92.4,
  decision: "Excellent Match",
  parse_failed: false,
  sub_scores: {
    technical_skills: 95,
    experience: 90,
    methodologies: 88,
    tools: 92,
    languages: 100,
    education: 90,
    certifications: 80,
    industry: 94,
  },
  gap_analysis: {
    missing: ["Kubernetes"],
    strengths: ["Agile", "Python", "Stakeholder management"],
  },
  evidence: [
    {
      item: "Python",
      category: "technical",
      level: 4,
      stars: "****",
      source: "experience: Senior Engineer",
    },
    { item: "Agile", category: "methodologies", level: 3, stars: "***", source: "skills: MANAGEMENT" },
  ],
  hard_blockers: [],
  blocker_explanations: [],
  visa_note: "Visa sponsorship indicated in the JD.",
  parsed_job: {
    job_title: "Senior Delivery Manager",
    company_name: "ACME GmbH",
    location: "Munich",
    country: "Germany",
    industry: "Automotive",
    seniority_level: "Senior",
    recruiter_contact: {
      name: "Anna Mueller",
      position: "Talent Acquisition",
      email: "anna.mueller@acme.example",
      phone: "+49 170 1234567",
      linkedin_url: "",
    },
    required_skills: { technical: ["Python", "SQL"], methodologies: ["Agile", "Scrum"], tools: ["Jira"] },
    preferred_skills: { technical: ["Azure"], methodologies: ["SAFe"], tools: ["Confluence"] },
    experience: { min_years: 6, preferred_years: 8, level: "Senior" },
    education: { min_degree: "Bachelor", preferred_fields: ["Computer Science"] },
    languages: [
      { language: "German", level: "C1", required: true },
      { language: "English", level: "Fluent", required: true },
    ],
    certifications: ["PRINCE2"],
    responsibilities: ["Lead the delivery team", "Own the roadmap"],
    keywords: ["delivery", "agile", "stakeholder"],
    visa_sponsorship: { support: "Yes", evidence: "we sponsor visas", notes: "" },
    work_authorization: { requirement: "Sponsorship available", evidence: "Blue Card" },
    location_requirements: {
      remote: false,
      hybrid: true,
      on_site: true,
      cities_or_countries: ["Munich"],
      relocation_support: "Yes",
    },
  },
  parsed_cv: {
    skills: { technical: ["Python", "SQL", "Azure"], methodologies: ["Agile", "Scrum"], tools: ["Jira"] },
    languages: [
      { language: "German", level: "C1" },
      { language: "English", level: "Fluent" },
    ],
    experience: [{ company: "ACME" }],
    education: [{ degree: "Bachelor" }],
    certifications: [{ name: "PRINCE2" }],
  },
  verdict: {
    band: "proceed",
    title: "Strong match - proceed",
    message: "Strong match (>= 90%).",
    next_step: "Proceed to the post-ATS assessment process.",
    proceed: true,
  },
};

const FAIL = {
  ...PASS,
  ats_score: 74,
  overall_ats: 74.2,
  decision: "Good Match",
  gap_analysis: {
    missing: ["Kubernetes", "SAFe", "Automotive domain"],
    strengths: ["Agile", "Python"],
  },
  verdict: {
    band: "soft_reject",
    title: "Soft rejection - strengthen your profile first",
    message: "This job is not yet suitable for your current profile.",
    next_step: "Strengthen the missing skills, then re-analyse this offer later.",
    proceed: false,
  },
};
const JD_TEXT =
  "Senior Delivery Manager - ACME GmbH, Munich (hybrid). We are looking for an experienced " +
  "delivery manager to lead a cross-functional agile team. Requirements: 6+ years of experience, " +
  "strong Python and SQL skills, Agile/Scrum and Jira, fluent German (C1) and English. " +
  "Responsibilities: lead the delivery team, own the roadmap, manage senior stakeholders. " +
  "We offer relocation support and we sponsor visas (Blue Card). Contact: Anna Mueller, " +
  "Talent Acquisition, anna.mueller@acme.example.";

const check = (name, ok, extra = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  [" + extra + "]" : ""}`);
};

const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    `--remote-debugging-port=${CPORT}`,
    "--user-data-dir=/tmp/airos-ja-uat",
    "--window-size=1400,1000",
    "about:blank",
  ],
  { stdio: "ignore" }
);
process.on("exit", () => {
  try {
    chrome.kill();
  } catch {}
});

try {
  let target = null;
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    try {
      const list = await (await fetch(`http://127.0.0.1:${CPORT}/json`)).json();
      const pages = list.filter((t) => t.type === "page");
      if (pages.length) {
        target = pages[0];
        break;
      }
    } catch {}
  }
  if (!target) throw new Error("no CDP target");

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });
  let msgId = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m);
      pending.delete(m.id);
    }
  };
  const send = (method, params = {}) =>
    new Promise((res) => {
      const i = ++msgId;
      pending.set(i, res);
      ws.send(JSON.stringify({ id: i, method, params }));
    });
  const evStr = async (expr) => {
    const r = await send("Runtime.evaluate", {
      expression: expr,
      awaitPromise: true,
      returnByValue: true,
    });
    if (r.result?.exceptionDetails) {
      const d = r.result.exceptionDetails;
      return "ERR: " + (d.exception?.description ?? d.text ?? "?");
    }
    return r.result?.result?.value;
  };
  await send("Page.enable");
  await send("Runtime.enable");

  const sidebar = () =>
    evStr(`Array.from(document.querySelectorAll("nav a")).map(a => a.textContent.trim()).join(" | ")`);
  const body = () => evStr("document.body.innerText");
  const stub = (payload) => `
    window.__uatPayload = ${JSON.stringify(payload)};
    if (!window.__uatOrigFetch) window.__uatOrigFetch = window.fetch;
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      if (url.includes("/api/ats/analyze")) {
        return new Response(JSON.stringify(window.__uatPayload), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
      return window.__uatOrigFetch(input, init);
    };
    "stubbed";
  `;
  const pasteAndAnalyze = async () => {
    await evStr(`
      (() => {
        const ta = document.querySelector("textarea");
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
        setter.call(ta, ${JSON.stringify(JD_TEXT)});
        ta.dispatchEvent(new Event("input", { bubbles: true }));
        const btn = Array.from(document.querySelectorAll("button")).find(b => b.textContent.includes("Verify & score"));
        if (!btn) return "no analyze button";
        btn.click();
        return "clicked";
      })()
    `);
    await sleep(3000);
  };
  // Step 0: forge the Auth0 SPA cache for this origin, then load the menu.
  await send("Page.navigate", { url: BASE + "/applications" });
  await sleep(4000);
  await evStr(`
    localStorage.clear();
    localStorage.setItem(${JSON.stringify(cacheKey)}, ${JSON.stringify(wrapped)});
    localStorage.setItem(${JSON.stringify(idTokenKey)}, ${JSON.stringify(idEntry)});
    localStorage.setItem(${JSON.stringify(manifestKey)}, ${JSON.stringify(manifest)});
    "ok";
  `);
  await send("Page.navigate", { url: BASE + "/applications?stage=analyze&v=" + Date.now() });
  await sleep(9000);

  // --- 1. before any analysis: only ① Job Analyses is offered --------------
  console.log("\n=== Step 1: sidebar before any analysis ===");
  let nav = await sidebar();
  console.log("sidebar:", nav);
  check("sidebar shows Job Analyses", String(nav).includes("Job Analyses"));
  check(
    "② Application Workshop hidden before a PASS",
    !String(nav).includes("Application Workshop"),
    String(nav)
  );

  // --- 2. canned PASS: report + final decision + new sidebar menu ----------
  console.log("\n=== Step 2: PASS analysis (API stubbed) ===");
  await evStr(stub(PASS));
  await pasteAndAnalyze();
  let text = String(await body());
  check("(c) report: ATS & compatibility score", text.includes("ATS & compatibility score"));
  check("(c) report: what AIROS compared (CV vs offer)", text.includes("What AIROS compared"));
  check("(c) report: full JD parse", text.includes("The offer as AIROS read it"));
  check("(c) report: component scores", text.includes("Component scores"));
  check("(c) report: evidence table", text.includes("Evidence the engine used"));
  check("(c) report: recruiter (RH) found", text.includes("Anna Mueller"));
  check("(d) final decision at the bottom = PASS", text.includes("PASS - proceed with this offer"));
  nav = await sidebar();
  check("(f) ② Application Workshop appears in the sidebar", String(nav).includes("Application Workshop"), String(nav));

  // --- 3. (f) the decision closes ① and redirects to ② --------------------
  console.log("\n=== Step 3: decision -> Application Workshop ===");
  const clicked = await evStr(`
    (() => {
      const btn = Array.from(document.querySelectorAll("button"))
        .find(b => b.textContent.includes("open the Application Workshop"));
      if (!btn) return "no decision button";
      btn.click();
      return "clicked";
    })()
  `);
  await sleep(2500);
  text = String(await body());
  check("decision button present and clickable", clicked === "clicked", String(clicked));
  check(
    "② Application Workshop page shown",
    text.includes("Application Workshop") && text.includes("App Workspace / Preparation")
  );
  const search = String(await evStr("location.search"));
  check("URL now carries ?stage=workshop", search === "?stage=workshop", search);
  nav = await sidebar();
  check(
    "② / ③ are offered in the sidebar once the run is open",
    String(nav).includes("Application Workshop") && String(nav).includes("App Workspace / Preparation"),
    String(nav)
  );

  // --- 4. canned FAIL: (e) NO + JD zone cleared ---------------------------
  console.log("\n=== Step 4: FAIL analysis (API stubbed) ===");
  await send("Page.navigate", { url: BASE + "/applications?stage=analyze&v=" + Date.now() });
  await sleep(9000);
  await evStr(stub(FAIL));
  await pasteAndAnalyze();
  text = String(await body());
  check("(d) final decision = NO", text.includes("NO - do not proceed with this offer"));
  check("(e) AIROS tells the user the JD zone was cleared", text.includes("cleared"));
  const taValue = await evStr("(document.querySelector('textarea') || {}).value");
  check("(e) JD zone cleared for the next offer", taValue === "", "value=" + JSON.stringify(taValue));
  check("report stays visible after a FAIL", text.includes("Component scores"));
} catch (e) {
  console.error("Script error:", e.message);
}

const failed = results.filter((r) => !r.ok);
console.log(`\n=== ${results.length - failed.length}/${results.length} checks passed ===`);
if (failed.length) {
  console.log("FAILED:", failed.map((f) => f.name).join(" ; "));
}
// Explicit exit: the headless Chrome child keeps the event loop alive otherwise.
process.exit(failed.length ? 1 : 0);


