/* AIROS Slice 4a UAT (CHG-012) - headless click-through:
   open http://localhost:3000/app, click "Continue with Auth0",
   expect navigation to the Auth0 hosted login (proves the registered
   callback + PKCE redirect build end-to-end). No credentials involved.
   Run: node scripts/next_uat.mjs   (Next.js dev server must be on :3000) */
import { spawn } from "node:child_process";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9222;
const APP = "http://localhost:3000/app";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORT}`, "--user-data-dir=/tmp/airos-uat-profile", "about:blank",
], { stdio: "ignore" });
process.on("exit", () => { try { chrome.kill(); } catch {} });

try {
  // wait for the CDP endpoint
  let target = null;
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json`);
      const list = await res.json();
      const pages = list.filter((t) => t.type === "page");
      if (pages.length) { target = pages[0]; break; }
    } catch { /* chrome not ready yet */ }
  }
  if (!target) throw new Error("no CDP page target");
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params = {}) =>
    new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const evalJs = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error("page error: " + JSON.stringify(r.result.exceptionDetails.exception?.description ?? r.result.exceptionDetails.text));
    return r.result?.result?.value;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Page.navigate", { url: APP });
  await sleep(9000); // dev-mode compile + hydrate

  const results = [];
  const check = (label, ok, extra = "") => {
    results.push(`${ok ? "PASS" : "FAIL"} ${label}${extra ? " - " + extra : ""}`);
    console.log(results[results.length - 1]);
  };

  const before = await evalJs("location.href");
  check("app loaded", before === APP, "url=" + before);

  const clicked = await evalJs(`(function(){
    const btns=[...document.querySelectorAll("button")];
    const b=btns.find(x=>/continue with auth0/i.test(x.textContent));
    if(!b) return "no-button";
    b.click(); return "clicked";
  })()`);
  check("login button found + clicked", clicked === "clicked", clicked);

  // wait for the redirect to the hosted login
  let href = "";
  for (let i = 0; i < 20; i++) {
    await sleep(500);
    href = await evalJs("location.href");
    if (href.includes("auth0.com")) break;
  }
  let u = null;
  try { u = new URL(href); } catch { /* not a url yet */ }
  check("redirected to Auth0 hosted login", !!u && /auth0\.com$/.test(u.hostname) && (u.pathname === "/u/login" || u.pathname === "/authorize"),
    "url=" + href.slice(0, 90));

  console.log("---");
  console.log(results.every((r) => r.startsWith("PASS")) ? "SLICE-4A UAT: ALL PASS" : "SLICE-4A UAT: FAILURES PRESENT");
  ws.close();
} catch (e) {
  console.error("HARNESS ERROR:", e.message);
  process.exitCode = 1;
} finally {
  chrome.kill();
}
