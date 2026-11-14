// Records the Duly product video: a scripted end-to-end run of the real app with on-screen captions
// and a visible cursor, captured through Chrome DevTools screencast frames (sharp 1080p), then encoded
// to MP4 with ffmpeg, plus an .srt subtitle file.
//
//   node tools/video/record.mjs            (from the repo root; needs .venv with imageio-ffmpeg and Edge)
//
// It starts its own backend (tools/video/server.py, fresh database, AI offline) and Vite on spare
// ports, so it never touches your data. Output: media/duly-demo.mp4 and media/duly-demo.srt.
import { spawn, execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(ROOT, "frontend", "package.json"));
const { chromium } = require("@playwright/test");

const API_PORT = 8200;
const WEB_PORT = 5190;
const BASE = `http://localhost:${WEB_PORT}`;
const PY = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const OUT = path.join(ROOT, "media");
const FRAMES = path.join(OUT, "frames");
const DEMO = path.join(ROOT, "demo", "invoices");
const LOGO = fs.readFileSync(path.join(ROOT, "frontend/public/duly.svg"), "utf8");

// ---------- servers ----------
function start(cmd, args, opts, readyText) {
  const p = spawn(cmd, args, { ...opts, shell: process.platform === "win32" && cmd === "npm" });
  return new Promise((resolve, reject) => {
    const onData = (d) => {
      const s = d.toString();
      process.stdout.write(`  | ${s}`);
      if (s.includes(readyText)) resolve(p);
    };
    p.stdout.on("data", onData);
    p.stderr.on("data", onData);
    p.on("exit", (code) => reject(new Error(`${cmd} exited ${code}`)));
  });
}
async function waitFor(url, ms = 120_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`timeout ${url}`);
}

// ---------- TOTP (RFC 6238) for the approvers' MFA ----------
function totp(secretB32) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secretB32.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30)));
  const h = crypto.createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

// ---------- overlay: captions + cursor (re-created on every document) ----------
const OVERLAY = `
(() => {
  const mount = () => {
    if (document.getElementById("vid-cap")) return;
    const st = document.createElement("style");
    st.textContent = \`
      #vid-cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:2147483646;max-width:min(1060px,92vw);
        background:rgba(11,31,68,.94);color:#fff;border-radius:14px;padding:14px 22px 15px;box-shadow:0 10px 30px rgba(0,0,0,.28);
        font:500 19px/1.4 "IBM Plex Sans",system-ui,sans-serif;display:none;border-left:5px solid #13A3C6}
      #vid-cap.top{bottom:auto;top:92px}
      #vid-cap .k{display:block;font:600 12.5px/1.2 "IBM Plex Sans",system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#5FD0EC;margin-bottom:5px}
      #vid-cap b{color:#FFD27A;font-weight:600}
      #vid-cur{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);transition:transform .08s}
      #vid-cur.down{transform:translate(-3px,-2px) scale(.82)}
      #vid-ring{position:fixed;z-index:2147483646;pointer-events:none;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
        border:3px solid #13A3C6;opacity:0;transform:scale(.4)}
      #vid-ring.go{animation:vidring .5s ease-out}
      @keyframes vidring{0%{opacity:.9;transform:scale(.4)}100%{opacity:0;transform:scale(1.4)}}
      .vid-hl{outline:3px solid #13A3C6 !important;outline-offset:3px !important;border-radius:6px;transition:outline-color .2s}
    \`;
    document.head.appendChild(st);
    const cap = document.createElement("div"); cap.id = "vid-cap"; document.body.appendChild(cap);
    const ring = document.createElement("div"); ring.id = "vid-ring"; document.body.appendChild(ring);
    const cur = document.createElement("div"); cur.id = "vid-cur";
    cur.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2l15 9.5-6.6 1.4L9 20z" fill="#fff" stroke="#0B1F44" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cur);
    const pos = JSON.parse(sessionStorage.getItem("vid-pos") || "[640,360]");
    cur.style.left = pos[0] + "px"; cur.style.top = pos[1] + "px";
    addEventListener("mousemove", (e) => { cur.style.left = e.clientX + "px"; cur.style.top = e.clientY + "px";
      sessionStorage.setItem("vid-pos", JSON.stringify([e.clientX, e.clientY])); }, true);
    addEventListener("mousedown", (e) => { cur.classList.add("down"); ring.style.left = e.clientX + "px"; ring.style.top = e.clientY + "px";
      ring.classList.remove("go"); void ring.offsetWidth; ring.classList.add("go"); }, true);
    addEventListener("mouseup", () => cur.classList.remove("down"), true);
    window.__vidCaption = (k, t) => { const c = document.getElementById("vid-cap");
      if (!t) { c.style.display = "none"; return; } c.innerHTML = (k ? '<span class="k">' + k + '</span>' : "") + t; c.style.display = "block"; };
    const last = sessionStorage.getItem("vid-cap-last");
    if (last) { const [k, t] = JSON.parse(last); window.__vidCaption(k, t); }
  };
  if (document.body) mount(); else addEventListener("DOMContentLoaded", mount);
})();`;

// ---------- recording state ----------
const cues = []; // {start, end, text}
let current = null;
let page;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function caption(kicker, html, holdMs = 0) {
  const now = Date.now() / 1000;
  if (current) current.end = now;
  current = html ? { start: now, end: null, text: `${kicker ? kicker + ": " : ""}${html.replace(/<[^>]+>/g, "")}` } : null;
  if (current) cues.push(current);
  await page.evaluate(([k, t]) => {
    sessionStorage.setItem("vid-cap-last", JSON.stringify([k, t]));
    window.__vidCaption && window.__vidCaption(k, t);
  }, [kicker, html]);
  if (holdMs) await sleep(holdMs);
}
/** Reading time: ~ 17 characters a second, at least 2.8 s. */
const readMs = (html) => Math.max(2800, Math.round(html.replace(/<[^>]+>/g, "").length / 17 * 1000));
async function say(kicker, html, extra = 0) {
  await caption(kicker, html, readMs(html) + Math.min(extra, 300));
}

/** Move the caption to the top of the screen (when the thing to see is at the bottom of the page). */
async function captionAtTop(on) {
  await page.evaluate((on) => document.getElementById("vid-cap")?.classList.toggle("top", on), on);
}
async function moveTo(locator) {
  await locator.scrollIntoViewIfNeeded();
  const b = await locator.boundingBox();
  if (!b) return;
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await sleep(120);
}
async function click(locator, after = 450) {
  await locator.waitFor({ state: "visible", timeout: 60_000 });
  await moveTo(locator);
  await locator.click();
  await sleep(after);
}
async function type(locator, text) {
  await click(locator, 200);
  await locator.pressSequentially(text, { delay: 35 });
  await sleep(250);
}
/** Smoothly bring an element into view inside the app's scrolling <main>. */
async function show(locator, block = "center", wait = 700) {
  await locator.first().waitFor({ state: "visible", timeout: 60_000 });
  await locator.first().evaluate((el, block) => el.scrollIntoView({ behavior: "smooth", block }), block);
  await sleep(wait);
}
async function highlight(locator, on = true) {
  await locator.first().evaluate((el, on) => el.classList.toggle("vid-hl", on), on);
}
async function go(p) {
  await page.goto(BASE + p);
  await page.waitForLoadState("networkidle");
  await sleep(350);
}
async function signInAs(name, then) {
  await ctx.clearCookies();
  await page.goto(BASE + "/login");
  await page.waitForLoadState("networkidle");
  const btn = page.getByRole("button", { name: new RegExp(name) });
  await btn.scrollIntoViewIfNeeded();
  await sleep(250);
  await click(btn, 500);
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  await page.waitForLoadState("networkidle");
  if (then) await go(then);
}
async function upload(file) {
  await go("/upload");
  await page.getByLabel("Invoice file").setInputFiles(path.join(DEMO, file));
  await sleep(500);
  await click(page.getByRole("button", { name: "Upload and check" }), 200);
  await page.waitForURL(/\/invoices\/\d+$/, { timeout: 120_000 });
  await page.waitForLoadState("networkidle");
  await sleep(700);
}
async function card(html) {
  await page.setContent(`<!doctype html><html><head><style>
    body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(circle at 30% 20%,#17336b,#0B1F44 60%);
      font-family:"IBM Plex Sans",Segoe UI,system-ui,sans-serif;color:#fff;text-align:center}
    .logo svg{width:96px;height:96px} h1{font-size:64px;margin:18px 0 6px;letter-spacing:-.02em} h2{font-size:30px;font-weight:500;color:#5FD0EC;margin:0 0 26px}
    p{font-size:21px;color:#C9D6EA;max-width:880px;margin:8px auto;line-height:1.5} .rail{display:flex;gap:26px;justify-content:center;margin-top:30px;font-size:17px;color:#C9D6EA}
    .rail b{color:#fff} .chip{display:inline-block;margin-top:26px;padding:8px 16px;border:1px solid #3A5285;border-radius:20px;font-size:16px;color:#C9D6EA}
    .fade{animation:f .9s ease-out both}@keyframes f{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
  </style></head><body><div class="fade">${html}</div></body></html>`);
  await sleep(400);
}

// ---------- the story ----------
async function story() {
  // 0. Title
  await card(`<div class="logo">${LOGO}</div><h1>Duly</h1><h2>Every invoice, duly done.</h2>
    <p>A smart procure-to-pay assistant that reads supplier invoices, checks them against purchase orders and goods receipts,
    and <b>approves, flags or blocks</b> each one with a clear reason.</p>
    <div class="rail"><span><b>Duly ordered</b> PO</span>→<span><b>Duly received</b> GR</span>→<span><b>Duly matched</b> 3-way</span>→<span><b>Duly approved</b> DoA</span>→<span><b>Duly paid</b> UTR</span></div>
    <div class="chip">Rules decide · AI only reads and explains · Works fully offline</div>`);
  await sleep(6000);
  await card(`<h2 style="margin-bottom:14px">The setting</h2><p>Plant X Polymers, a fictional polypropylene plant in Gujarat.
    Its accounts-payable team gets thousands of supplier invoices a month: price and quantity mismatches, invoices before the goods arrive,
    duplicates, fake bank details, and MSME suppliers who must be paid within 45 days.</p>
    <p style="margin-top:22px;color:#FFD27A">Let's follow real invoices through Duly, end to end.</p>`);
  await sleep(7000);

  // 1. Login
  await go("/login");
  await caption("Six roles, one app", "Separate logins for <b>suppliers</b>, <b>AP clerks</b>, <b>approvers</b>, <b>stores</b>, <b>auditors</b> and <b>admins</b>, each enforced on the server. In demo mode every persona is one click away.");
  await sleep(2500);
  await show(page.locator(".login-personas"), "start", 600);
  await sleep(Math.max(500, readMs("Separate logins for <b>suppliers</b>, <b>AP clerks</b>, <b>approvers</b>, <b>stores</b>, <b>auditors</b> and <b>admins</b>, each enforced on the server. In demo mode every persona is one click away.") - 3100));

  // 2. S04 missing GR
  await signInAs("Hetal Shah", "/portal");
  await caption("Scenario: invoice before delivery", "<b>Hetal</b> from Navrang Packaging, a micro-enterprise supplier, invoices <b>20,000 bags</b> before the goods have reached the plant…");
  await sleep(2600);
  await upload("S04_packaging_missing_gr.pdf");
  await say("Read in seconds", "Duly reads the invoice with <b>local OCR</b>: every field is boxed on the original document with a confidence score.");
  await show(page.locator(".detail-pane").nth(2), "start");
  await say("⛔ BLOCK · MISSING_GR", "Nothing has been received against PO 4500001004, so the rules engine <b>blocks</b> payment, with the reason and its SAP equivalent (payment block R, MIGO).", 600);

  // 3. Stores posts GR -> auto release
  await signInAs("Imran Shaikh", "/receiving");
  await say("Stores · goods receipt", "The bags arrive. <b>Imran</b> from stores posts the goods receipt: no paperwork, just the quantity received.");
  const po = page.locator("section.po-card", { has: page.getByRole("heading", { name: "4500001004" }) });
  await show(po, "center", 600);
  await type(po.getByLabel("Quantity received for PKG-FFS-25"), "20000");
  await click(po.getByRole("button", { name: "Post goods receipt" }), 1500);
  await show(po.getByRole("status"), "center", 400);
  await say("Automatic re-check", "Duly re-runs the match the moment the receipt is posted: the blocked invoice is <b>released to approval</b> automatically. Nobody has to remember it.", 800);

  // 4. Fraud: S06 bank mismatch
  await signInAs("Dinesh Patel");
  await caption("Scenario: payment fraud", "Next, an invoice from Kesar Engineering arrives asking to be paid into a <b>new bank account</b>, a classic business-email-compromise trick…");
  await upload("S06_impellers_bank_mismatch.pdf");
  await show(page.locator(".detail-pane").nth(2), "start");
  await say("⛔ BLOCK · BANK_MISMATCH", "The bank details differ from the vendor master: <b>blocked</b>, and a security alert is raised. Bank details can only change through a call-back, a 72-hour cooling period and a second approver.", 800);

  // 5. Prompt injection S07
  await signInAs("Hetal Shah");
  await caption("Scenario: attacking the AI", "This pallets invoice hides <b>white 4-point text</b> telling an AI to approve it and change the bank account…");
  await upload("S07_pallets_prompt_injection.pdf");
  await show(page.locator(".inj"), "start", 600);
  await highlight(page.locator(".inj"));
  await say("🛡️ Prompt-injection shield", "Duly finds the hidden instruction <b>before any AI reads the page</b>, shows it verbatim and quarantines it. The invoice is flagged for a person.", 800);
  await highlight(page.locator(".inj"), false);

  // 6. Edited total vs signed QR (S08) and the clean e-invoice (S01)
  await signInAs("Anil Joshi");
  await caption("Scenario: an edited PDF", "Sahyadri's catalyst invoice: someone changed the printed total <b>after</b> the government portal signed the e-invoice QR…");
  await upload("S08_catalyst_edited_total_qr_mismatch.pdf");
  await show(page.locator(".einv"), "center", 600);
  await highlight(page.locator(".einv"));
  await say("⛔ BLOCK · QR_MISMATCH", "<b>Trust the signed QR, not the pixels.</b> Duly verifies the IRP signature and compares the signed values with the printed ones: the total was changed from ₹5,01,500 to ₹5,19,500.", 800);
  await highlight(page.locator(".einv"), false);
  await caption("Scenario: a clean invoice", "Now a genuine ₹15 lakh e-invoice from the same supplier…");
  await upload("S01_catalyst_clean_einvoice.pdf");
  await show(page.locator(".detail-pane").nth(2), "start");
  await say("✅ APPROVE", "Signed QR verified, PO and goods receipt match: <b>approved by the rules</b> and routed by the Delegation of Authority. Above ₹10 lakh it needs <b>L1 and L2, both with MFA</b>.", 600);
  await show(page.locator(".detail-matrix").first(), "start", 600);
  await say("Three-way match", "Every line compared: purchase order (ME23N), goods receipt (MIGO) and invoice (MIRO), with quantities, prices and variances.");

  // 7. Clerk: dashboard, queue, duplicate compare, price variance + Explain, SAP preview
  await signInAs("Asha Kulkarni", "/dashboard");
  await say("Exceptions dashboard", "The AP clerk's view: open exceptions by <b>type, supplier and age</b>, value on hold, touchless rate and duplicates prevented, all live from the data.", 600);
  await go("/queue?status=open");
  await say("Work queue", "Every bar on the dashboard drills into this queue: filters, saved views, CSV export and J / K / Enter shortcuts.");
  await click(page.getByRole("link", { name: "INV-42" }).first(), 1500);
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => { const im = [...document.querySelectorAll(".viewer-page img")]; return im.length > 0 && im.every((i) => i.complete && i.naturalWidth > 0); }, null, { timeout: 30_000 }).catch(() => {});
  await show(page.locator(".detail-pane").nth(2), "start");
  await say("⛔ BLOCK · DUPLICATE", "A WhatsApp <b>photo</b> of an invoice Kesar already sent, renumbered from INV/0042 to INV-42. Duly normalises the number and compares totals, lines and the image itself.", 400);
  await click(page.getByRole("link", { name: /Compare side by side/ }).first(), 600);
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => [...document.images].every((i) => i.complete), null, { timeout: 30_000 }).catch(() => {});
  await say("Side-by-side evidence", "Both documents and every matching signal, so the clerk can prove it in seconds. Duplicates are never paid twice.", 600);
  await caption("Command palette", "<b>Ctrl K</b> jumps to any page or invoice from anywhere…");
  await page.keyboard.press("Control+K");
  await sleep(700);
  await page.getByRole("combobox", { name: /Search pages, invoices/ }).pressSequentially("0913", { delay: 90 });
  await sleep(1300);
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/invoices\/\d+$/);
  await page.waitForLoadState("networkidle");
  await sleep(1000);
  await show(page.locator(".detail-pane").nth(2), "start");
  await say("🟡 FLAG · PRICE_VARIANCE", "Billed ₹639.84 a kg against a PO price of ₹620.00: <b>3.2% above</b>, over the 1% tolerance, so it is flagged with the exact rupee difference.");
  await click(page.getByRole("button", { name: /^Explain/ }).first(), 2200);
  await say("Explain", "<b>Explain</b> writes the decision in plain words, from the reason codes only. It never changes the decision: <b>rules decide, AI only explains</b>.", 800);
  await show(page.locator(".detail-head"), "start", 300);
  await click(page.getByRole("button", { name: /SAP posting preview/ }), 1500);
  await say("SAP-ready", "The exact <b>SAP S/4HANA</b> posting Duly would make: the OData payload, the payment block and the reads it does first. Duly is a side-car to the ERP, not a replacement.", 600);
  await page.keyboard.press("Escape");
  await sleep(600);

  // 8. Approvals with MFA
  for (const [name, level] of [["Rohan Mehta", "L1 Finance Manager"], ["Kavita Desai", "L2 Plant Head"]]) {
    await signInAs(name, "/approvals");
    await say(`Approvals · ${level}`, level.startsWith("L1")
      ? "<b>Rohan</b> sees only the invoices waiting for his level, with the decision and reasons already explained."
      : "Then <b>Kavita</b>, the Plant Head, approves the same invoice at level 2.");
    await click(page.getByRole("link", { name: "SCA/26-27/0912" }).first(), 1500);
    await page.waitForLoadState("networkidle");
    const panel = page.locator(".action-box");
    await show(panel, "center", 500);
    const setup = await (await page.request.get(`${BASE}/api/auth/mfa-setup`)).json();
    const secret = new URL(setup.otpauth_uri).searchParams.get("secret");
    if (level.startsWith("L1")) await caption("Multi-factor approval", "Above ₹10 lakh every approver must enter an <b>authenticator code</b>. Segregation of duties stops anyone approving their own work.");
    await type(panel.getByPlaceholder("123456"), totp(secret));
    await click(panel.getByRole("button", { name: "Approve" }), 900);
    await page.locator(".step-approved").nth(level.startsWith("L1") ? 0 : 1).waitFor({ timeout: 20_000 });
    await sleep(level.startsWith("L1") ? 2600 : 600);
  }
  await show(page.locator(".steps").first(), "center", 400);
  await say("Fully approved", "L1 and L2 both signed off with MFA. Every step is written to the <b>tamper-evident audit chain</b>.");

  // 9. Approve the MSME invoice, then the payment run
  await signInAs("Rohan Mehta", "/approvals");
  await click(page.getByRole("link", { name: "NPW-305" }).first(), 1500);
  await page.waitForLoadState("networkidle");
  await show(page.locator(".action-box"), "center", 300);
  await caption("MSME supplier", "Navrang is a <b>micro enterprise</b>: by law it must be paid within 45 days of delivery. This invoice is on day 41.");
  await click(page.locator(".action-box").getByRole("button", { name: "Approve" }), 2000);
  await go("/payments");
  await say("MSME 45-day guardian", "Open MSME invoices, days left, the <b>interest exposure</b> (3 × the RBI bank rate) and the tax deduction at risk if a payment slips.", 600);
  await show(page.getByRole("heading", { name: /Payment proposal/ }), "start", 700);
  await say("Smart payment run", "MSME invoices due before the next run go first (<b>NPW-305, 4 days left</b>); early-payment discounts are taken only when they beat the cost of funds; TDS is withheld automatically.", 900);
  const rel = page.getByRole("button", { name: /^Release \d+ payments/ });
  if (await rel.isEnabled().catch(() => false)) {
    await click(rel, 2500);
    await say("Duly paid", "Payments are released with a UTR each, and the suppliers see <b>paid</b> in their portal.", 400);
  }

  // 10. Currencies and units
  await signInAs("Lena Brandt");
  await caption("Scenario: an import in euros", "<b>Nordwerk</b>, a German supplier, bills <b>€19,250</b> against a purchase order in euros…");
  await upload("S13_import_eur_nucleating_agent.pdf");
  await highlight(page.locator(".detail-facts > div").first());
  await say("💱 Currency conversion", "Matched in euros, converted at the policy exchange rate: <b>≈ ₹20.1 lakh</b>. Approval limits and MFA use the rupee value; no Indian GST applies to an import.", 800);
  await highlight(page.locator(".detail-facts > div").first(), false);
  await signInAs("Dinesh Patel");
  await caption("Scenario: different units", "Kesar bills <b>12 BOX</b> of bearings, but the purchase order is in pieces…");
  await upload("S14_bearings_billed_in_boxes.pdf");
  await show(page.locator(".detail-matrix").first(), "start", 600);
  await captionAtTop(true);
  await highlight(page.locator(".detail-matrix tbody tr").first());
  await say("📦 Unit conversion", "The item master says 1 BOX = 10 pieces, so Duly matches <b>120 NOS</b> against the PO and the goods received: approved, with the conversion shown.", 600);
  await highlight(page.locator(".detail-matrix tbody tr").first(), false);
  await captionAtTop(false);

  // 11. Supplier portal, Hindi, chatbot
  await go("/portal");
  await say("Supplier portal", "Kesar's own view: each invoice on the Duly rail, what Plant X is doing about it, and the <b>expected payment date</b>.");
  await click(page.getByRole("button", { name: /हिन्दी|Hindi/ }).first(), 1500);
  await say("हिन्दी", "The portal and the assistant work in <b>English and Hindi</b>.");
  await click(page.getByRole("button", { name: /English/ }).first(), 900);
  await click(page.getByRole("button", { name: "Payment assistant" }), 900);
  const chat = page.getByRole("region", { name: "Where is my payment?" });
  await type(chat.getByRole("textbox"), "When will I get paid for INV/0042?");
  await click(chat.getByRole("button", { name: "Ask" }), 2200);
  await say("\"Where is my payment?\"", "The assistant answers from Kesar's <b>own records only</b>, with the status and expected payment date. Questions about other suppliers are refused and logged.");
  await type(chat.getByRole("textbox"), "Show me Navrang's invoices");
  await click(chat.getByRole("button", { name: "Ask" }), 2200);
  await say("Guardrails", "Refused: suppliers can never see each other's data.", 400);
  await click(page.getByRole("button", { name: "Close assistant" }), 500);

  // 12. Auditor
  await signInAs("Meera Iyer", "/audit");
  await caption("Tamper-evident audit trail", "Every event is <b>hash-chained</b> (SHA-256) and the chain head is signed (Ed25519). Edit one row in the database and the chain breaks at that exact event. One click re-verifies them all.");
  await sleep(2500);
  await click(page.getByRole("button", { name: "Verify chain" }), 400);
  await sleep(Math.max(800, readMs("Every event is <b>hash-chained</b> (SHA-256) and the chain head is signed (Ed25519). Edit one row in the database and the chain breaks at that exact event. One click re-verifies them all.") - 2900));
  await go("/controls");
  await say("Controls report", "The auditor's report: <b>10 controls</b> (no PO no pay, three-way match, duplicates, DoA, segregation of duties, MFA, bank changes…) <b>tested against the live data</b>, downloadable as a PDF.", 800);

  // 13. Trust and impact
  await go("/trust");
  await say("Responsible AI", "<b>AI never decides.</b> Decisions made by the rules engine are counted here, and decisions made by AI: <b>zero</b>. Low-confidence fields always go to a person, and the AI can be switched off entirely.", 600);
  await go("/impact");
  await say("Measurable impact", "Measured on Duly's own data, then projected for Plant X with every assumption editable and every formula shown: AP hours saved, duplicates prevented, MSME interest avoided.", 800);

  // 14. Phone
  await page.setViewportSize({ width: 390, height: 780 });
  await go("/dashboard");
  await caption("Works on a phone", "Every screen adapts to a phone…");
  await sleep(1800);
  await click(page.getByRole("button", { name: "Open menu" }), 1500);
  await caption("Works on a phone", "…with a slide-in menu, stacked cards and a full-screen assistant.");
  await sleep(2500);
  await page.keyboard.press("Escape");
  await sleep(800);
  await caption("", "");
  await page.setViewportSize({ width: 1280, height: 720 });

  // 15. End card
  await card(`<div class="logo">${LOGO}</div><h1>Duly</h1><h2>Every invoice, duly done.</h2>
    <p>Separate logins · extraction with confidence · three-way match · approvals with MFA · audit chain · exceptions dashboard ·
    supplier portal · duplicate detection · payment chatbot · controls report</p>
    <p style="color:#FFD27A;margin-top:18px">Signed-QR check · prompt-injection shield · bank-fraud block · MSME guardian · smart payment run · SAP-ready</p>
    <div class="chip">www.duly.website · LYB Mumbai Hackathon 2026 · Plant X is fictional; all data is synthetic</div>`);
  await sleep(8000);
}

// ---------- main ----------
fs.rmSync(FRAMES, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
fs.mkdirSync(FRAMES, { recursive: true });
console.log("Starting backend (fresh database + pre-staged scenarios)…");
const api = await start(PY, [path.join(ROOT, "tools/video/server.py")], { cwd: ROOT, env: { ...process.env, DULY_API_PORT: String(API_PORT), PYTHONIOENCODING: "utf-8" } }, "[video] backend ready");
await waitFor(`http://127.0.0.1:${API_PORT}/api/health`);
const web = spawn("npm", ["run", "dev"], { cwd: path.join(ROOT, "frontend"), shell: process.platform === "win32",
  env: { ...process.env, DULY_WEB_PORT: String(WEB_PORT), DULY_API_URL: `http://127.0.0.1:${API_PORT}` } });
await waitFor(BASE);

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? "msedge" });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5, colorScheme: "light" });
await ctx.addInitScript(OVERLAY);
page = await ctx.newPage();
page.setDefaultTimeout(60_000);
const cdp = await ctx.newCDPSession(page);
const frames = [];
cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
  const file = path.join(FRAMES, `f${String(frames.length).padStart(6, "0")}.jpg`);
  fs.writeFileSync(file, Buffer.from(data, "base64"));
  frames.push({ file, t: metadata.timestamp });
  try { await cdp.send("Page.screencastFrameAck", { sessionId }); } catch {}
});
await page.goto("about:blank");
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 88, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });

let failed = null;
try {
  await story();
} catch (e) {
  failed = e;
  console.error("Story failed:", e);
  await page.screenshot({ path: path.join(OUT, "failure.png") }).catch(() => {});
}
if (current) current.end = Date.now() / 1000;
await sleep(300);
await cdp.send("Page.stopScreencast").catch(() => {});
await browser.close();
api.kill();
if (process.platform === "win32") { try { execFileSync("taskkill", ["/pid", String(web.pid), "/T", "/F"], { stdio: "ignore" }); } catch {} } else web.kill();

// ---------- encode ----------
console.log(`Captured ${frames.length} frames`);
const t0 = frames[0].t;
const end = frames[frames.length - 1].t + 1.5;
let list = "ffconcat version 1.0\n";
frames.forEach((f, i) => {
  const next = i + 1 < frames.length ? frames[i + 1].t : end;
  list += `file '${f.file.replace(/\\/g, "/")}'\nduration ${Math.max(0.001, next - f.t).toFixed(3)}\n`;
});
list += `file '${frames[frames.length - 1].file.replace(/\\/g, "/")}'\n`;
fs.writeFileSync(path.join(OUT, "frames.txt"), list);
const ffmpeg = execFileSync(PY, ["-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"]).toString().trim();
const mp4 = path.join(OUT, "duly-demo.mp4");
execFileSync(ffmpeg, ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", path.join(OUT, "frames.txt"),
  "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0B1F44,fps=30,format=yuv420p",
  "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-movflags", "+faststart", mp4], { stdio: "inherit" });

const ts = (s) => {
  const ms = Math.max(0, Math.round((s - t0) * 1000));
  const h = String(Math.floor(ms / 3600000)).padStart(2, "0"), m = String(Math.floor(ms / 60000) % 60).padStart(2, "0");
  const sec = String(Math.floor(ms / 1000) % 60).padStart(2, "0"), r = String(ms % 1000).padStart(3, "0");
  return `${h}:${m}:${sec},${r}`;
};
const srt = cues.filter((c) => c.end && c.end > c.start).map((c, i) => `${i + 1}\n${ts(c.start)} --> ${ts(c.end)}\n${c.text}\n`).join("\n");
fs.writeFileSync(path.join(OUT, "duly-demo.srt"), srt);
fs.rmSync(FRAMES, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
fs.rmSync(path.join(OUT, "frames.txt"), { force: true });
console.log(`Video: ${mp4} (${(fs.statSync(mp4).size / 1e6).toFixed(1)} MB, ${(end - t0).toFixed(0)} s)${failed ? "  (story stopped early: see media/failure.png)" : ""}`);
process.exit(failed ? 1 : 0);
