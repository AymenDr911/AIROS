/* CDP test: inject Auth0 cache, verify ChoiceStep, test fetch. */
import { spawn } from "node:child_process";
import fs from "node:fs";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const CPORT = 9224;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const token = fs.readFileSync("/tmp/test_token.txt", "utf-8").trim();
const payload = JSON.parse(Buffer.from(token.split(".")[1] + "==", "base64").toString());
const exp = Date.now() + 3600000;
const CID = "test-client-id";
const SCOPE = "openid profile email";
const cacheKey = `@@auth0spajs@@::${CID}::${SCOPE}`;
const idTokenKey = `@@auth0spajs@@::${CID}::@@user@@`;
const manifestKey = `@@auth0spajs@@::${CID}`;
const userObj = { user_id: payload.sub, email: payload.email, name: payload.email, nickname: payload.email.split("@")[0], picture: "", created_at: new Date(payload.iat*1000).toISOString() };
const decodedToken = { claims: { ...payload, __raw: token }, user: userObj };
const wrapped = JSON.stringify({ body: { id_token: token, access_token: token, token_type: "bearer", expires_in: 3600, decodedToken, audience: "", scope: SCOPE, client_id: CID }, expiresAt: exp });
const idEntry = JSON.stringify({ id_token: token, decodedToken });
const manifest = JSON.stringify({ keys: [cacheKey, idTokenKey] });

console.log("Token valid:", payload.exp > Math.floor(Date.now()/1000));
console.log("Keys:", cacheKey, idTokenKey, manifestKey);

const chrome = spawn(CHROME, [
  "--headless=new","--disable-gpu","--no-first-run",
  `--remote-debugging-port=${CPORT}`,
  "--user-data-dir=/tmp/airos-cdp-test","--window-size=1280,800","about:blank",
], { stdio: "ignore" });
process.on("exit", () => { try { chrome.kill(); } catch {} });
const errors = [], consoleMsgs = [];

try {
  let target = null;
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    try {
      const res = await fetch(`http://127.0.0.1:${CPORT}/json`);
      const list = await res.json();
      const pages = list.filter(t => t.type === "page");
      if (pages.length) { target = pages[0]; break; }
    } catch {}
  }
  if (!target) throw new Error("no CDP target");

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let msgId = 0; const pending = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown") {
      const d = m.params?.exceptionDetails;
      errors.push((d?.exception?.description || d?.text || "?").substring(0,500));
    }
    if (m.method === "Runtime.consoleAPICalled") {
      const args = m.params?.args || [];
      const text = args.map(a => a.value ?? a.description ?? "").join(" ");
      consoleMsgs.push(`${m.params?.type||"?"}: ${text}`.substring(0,300));
    }
  };
  const send = (method, params = {}) => new Promise(res => {
    const i = ++msgId; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params }));
  });
  const ev = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) return { err: r.result.exceptionDetails.exception?.description ?? r.result.exceptionDetails.text };
    return { val: r.result?.result?.value };
  };
  const evStr = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) {
      const desc = r.result.exceptionDetails.exception?.description ?? r.result.exceptionDetails.text;
      return desc ? desc.substring(0, 500) : "error";
    }
    return r.result?.result?.value;
  };

    await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");

  // Step 1: Navigate to profile page (should be signed out)
  console.log("\n=== Step 1: Navigate to /profile ===");
  await send("Page.navigate", { url: "http://localhost:3000/profile" });
  await sleep(9000);
  const t1 = await evStr("document.body.innerText");
  console.log("Initial:", (t1||"").substring(0,150));

  // Step 2: Inject Auth0 cache
  console.log("\n=== Step 2: Inject Auth0 cache ===");
  const injectCode = `
    localStorage.setItem("${cacheKey}", ${JSON.stringify(wrapped)});
    localStorage.setItem("${idTokenKey}", ${JSON.stringify(idEntry)});
    localStorage.setItem("${manifestKey}", ${JSON.stringify(manifest)});
    "injected";
  `;
  await evStr(injectCode);
  const lsKeys = await evStr("Object.keys(localStorage).filter(k => k.includes('auth0spajs')).join(', ')");
  console.log("Auth0 keys:", lsKeys);

  // Step 3: Reload
  console.log("\n=== Step 3: Reload ===");
  await send("Page.navigate", { url: "http://localhost:3000/profile?v=" + Date.now() });
  await sleep(9000);
  const t2 = await evStr("document.body.innerText");
  console.log("After reload:", (t2||"").substring(0,300));

  const hasInput = await evStr("!!document.querySelector('input[type=\"file\"]')");
  const btnInfo = await evStr("(() => { const btn = document.querySelector('button[type=\"button\"]'); return btn ? JSON.stringify({disabled: btn.disabled, text: btn.textContent.trim()}) : 'no button'; })()");
  console.log("File input:", hasInput, "Button:", btnInfo);

  if (hasInput === "true") {
    console.log("\n=== Step 4: Test direct fetch to backend ===");
    const fetchResult = await ev(`
      (async () => {
        try {
          const form = new FormData();
          const blob = new Blob(["test content for extraction"], { type: "application/octet-stream" });
          form.append("files", blob, "test.pdf");
          const resp = await fetch("http://localhost:8002/api/profile/extract-cv", {
            method: "POST",
            headers: { "Authorization": "Bearer " + "${token}" },
            body: form,
          });
          const body = await resp.json().catch(() => ({}));
          return { status: resp.status, hasRichData: !!body.rich_data, bodyKeys: Object.keys(body), detail: body.detail || null };
        } catch (e) {
          return { error: e.message };
        }
      })()
    `);
    console.log("Fetch result:", JSON.stringify(fetchResult.val || fetchResult.err));
    } else {
    console.log("No file input - ChoiceStep not rendered. Checking what's visible...");
  }

  // Print all captured messages
  if (consoleMsgs.length) {
    console.log("\n=== Console messages ===");
    consoleMsgs.forEach(m => console.log(m));
  }
  if (errors.length) {
    console.log("\n=== Page errors ===");
    errors.forEach(e => console.log(e));
  }
  if (!consoleMsgs.length && !errors.length) {
    console.log("\nNo console messages or page errors captured.");
  }
  console.log("\n=== Test complete ===");
} catch (e) {
  console.error("Script error:", e.message);
  if (errors.length) { console.log("\n=== Errors captured ==="); errors.forEach(e => console.log(e)); }
}



