// Product shots for the launch film: stages every feature on a fresh demo database (tools/video/server.py),
// then captures crisp 2x desktop and 3x phone screenshots of the real app into media/film/shots/.
//
//   node tools/film/shots.mjs
import { spawn, execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(ROOT, "frontend", "package.json"));
const { chromium } = require("@playwright/test");
const API_PORT = 8200, WEB_PORT = 5190, BASE = `http://localhost:${WEB_PORT}`;
const PY = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const OUT = path.join(ROOT, "media", "film", "shots");
const DEMO = path.join(ROOT, "demo", "invoices");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(url, ms = 180_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if ((await fetch(url)).ok) return; } catch {}
    await sleep(500);
  }
  throw new Error(`timeout ${url}`);
}

fs.mkdirSync(path.join(OUT, "pages"), { recursive: true });
console.log("Starting backend…");
const api = spawn(PY, [path.join(ROOT, "tools/video/server.py")], { cwd: ROOT, env: { ...process.env, DULY_API_PORT: String(API_PORT), PYTHONIOENCODING: "utf-8" } });
api.stdout.on("data", (d) => process.stdout.write(`  | ${d}`));
api.stderr.on("data", (d) => process.stdout.write(`  | ${d}`));
await waitFor(`http://127.0.0.1:${API_PORT}/api/health`);
const web = spawn("npm", ["run", "dev"], { cwd: path.join(ROOT, "frontend"), shell: process.platform === "win32",
  env: { ...process.env, DULY_WEB_PORT: String(WEB_PORT), DULY_API_URL: `http://127.0.0.1:${API_PORT}` } });
await waitFor(BASE);

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? "msedge" });
const desk = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light" });
const page = await desk.newPage();
page.setDefaultTimeout(90_000);

async function as(ctx, pg, email, then = "/") {
  await ctx.clearCookies();
  const r = await pg.request.post(`${BASE}/api/auth/demo-login`, { data: { email } });
  if (!r.ok()) throw new Error(`login ${email}: ${r.status()}`);
  await pg.goto(BASE + then);
  await pg.waitForLoadState("networkidle");
}
const csrf = async (ctx) => (await ctx.cookies()).find((c) => c.name === "duly_csrf")?.value ?? "";
async function upload(email, file) {
  await as(desk, page, email);
  const mime = file.endsWith(".pdf") ? "application/pdf" : "image/jpeg";
  const r = await page.request.post(`${BASE}/api/invoices/upload`, {
    headers: { "X-CSRF-Token": await csrf(desk) },
    multipart: { file: { name: file, mimeType: mime, buffer: fs.readFileSync(path.join(DEMO, file)) } },
  });
  if (r.status() !== 201) throw new Error(`upload ${file}: ${r.status()} ${await r.text()}`);
  const inv = await r.json();
  console.log(`  uploaded ${inv.invoice_number} -> ${inv.decision}`);
  return inv.id;
}
async function idOf(number) {
  const list = await (await page.request.get(`${BASE}/api/invoices`)).json();
  return (list.items ?? list).find((i) => i.invoice_number === number).id;
}
async function settle(pg) {
  await pg.waitForLoadState("networkidle");
  await pg.waitForFunction(() => [...document.images].every((i) => i.complete), null, { timeout: 30_000 }).catch(() => {});
  await pg.addStyleTag({ content: "*{caret-color:transparent!important} ::-webkit-scrollbar{display:none}" });
  await sleep(700);
}
async function shot(pg, name) { await settle(pg); await pg.screenshot({ path: path.join(OUT, name) }); console.log("  shot", name); }
async function el(pg, locator, name, maxH = 0) {
  await settle(pg);
  const loc = locator.first();
  await loc.scrollIntoViewIfNeeded();
  await sleep(300);
  if (!maxH) { await loc.screenshot({ path: path.join(OUT, name) }); console.log("  el", name); return; }
  const b = await loc.boundingBox();
  await pg.screenshot({ path: path.join(OUT, name), clip: { x: b.x, y: b.y, width: b.width, height: Math.min(b.height, maxH) } });
  console.log("  el", name);
}

// ---- stage the story ----
const ids = {};
ids.S04 = await upload("accounts@navrang-pack.example", "S04_packaging_missing_gr.pdf");
ids.S07 = await upload("accounts@navrang-pack.example", "S07_pallets_prompt_injection.pdf");
ids.S06 = await upload("invoices@kesar-spares.example", "S06_impellers_bank_mismatch.pdf");
ids.S14 = await upload("invoices@kesar-spares.example", "S14_bearings_billed_in_boxes.pdf");
ids.S08 = await upload("billing@sahyadri-catalysts.example", "S08_catalyst_edited_total_qr_mismatch.pdf");
ids.S01 = await upload("billing@sahyadri-catalysts.example", "S01_catalyst_clean_einvoice.pdf");
ids.S13 = await upload("billing@nordwerk-additives.example", "S13_import_eur_nucleating_agent.pdf");

// Rohan approves the MSME and services invoices so the payment run shows them.
await as(desk, page, "rohan.mehta@plantx.example");
for (const n of ["NPW-305", "TTS/TA/2026/017"]) {
  const r = await page.request.post(`${BASE}/api/approvals/invoices/${await idOf(n)}/approve`, {
    headers: { "X-CSRF-Token": await csrf(desk) }, data: { comment: "ok" } });
  console.log(`  approved ${n}: ${r.status()}`);
}

// ---- desktop shots (clerk) ----
await as(desk, page, "asha.kulkarni@plantx.example", "/dashboard");
ids.S05 = await idOf("INV-42");
ids.S02 = await idOf("SCA/26-27/0913");
await shot(page, "dashboard.png");
await page.goto(`${BASE}/invoices/${ids.S01}`); await shot(page, "invoice-s01.png");
await el(page, page.locator(".detail-pane").nth(2), "decision-approve.png", 330);
await el(page, page.locator(".einv"), "qr-verified.png");
await page.goto(`${BASE}/invoices/${ids.S02}`); await shot(page, "invoice-s02.png");
await el(page, page.locator(".detail-pane").nth(2), "decision-flag.png", 330);
await page.goto(`${BASE}/invoices/${ids.S04}`); await shot(page, "invoice-s04.png");
await el(page, page.locator(".detail-pane").nth(2), "decision-block.png", 330);
await page.goto(`${BASE}/invoices/${ids.S05}`); await shot(page, "invoice-dup.png");
await el(page, page.locator(".detail-pane").nth(2), "decision-dup.png", 420);
await page.goto(`${BASE}/invoices/${ids.S05}/compare`); await shot(page, "compare.png");
await page.goto(`${BASE}/invoices/${ids.S06}`);
await el(page, page.locator(".detail-pane").nth(2), "decision-bank.png", 330);
await page.goto(`${BASE}/invoices/${ids.S07}`); await el(page, page.locator(".inj"), "injection.png");
await page.goto(`${BASE}/invoices/${ids.S08}`); await el(page, page.locator(".einv"), "qr-mismatch.png");
await page.goto(`${BASE}/invoices/${ids.S14}`); await el(page, page.locator(".detail-matrix").first(), "match-box.png");
await page.goto(`${BASE}/invoices/${ids.S13}`); await el(page, page.locator(".detail-head"), "eur-head.png");
await page.goto(`${BASE}/invoices/${ids.S13}`); await shot(page, "invoice-s13.png");

// payments and approvals (approver)
await as(desk, page, "rohan.mehta@plantx.example", "/payments");
await shot(page, "payments.png");
await el(page, page.locator(".guardian"), "guardian.png");
await page.getByRole("heading", { name: /Payment proposal/ }).scrollIntoViewIfNeeded();
await sleep(400);
await el(page, page.locator(".panel").filter({ has: page.getByRole("heading", { name: /Payment proposal/ }) }), "proposal.png", 620);

// audit (auditor)
await as(desk, page, "meera.iyer@plantx.example", "/audit");
await page.getByRole("button", { name: "Verify chain" }).click();
await page.getByRole("heading", { name: "Chain verified" }).waitFor();
await shot(page, "audit.png");
await el(page, page.locator(".verify-result"), "audit-verified.png");
await el(page, page.locator(".chain"), "audit-chain.png");

// raw invoice page images for the opening montage
for (const [k, id] of Object.entries(ids)) {
  const r = await page.request.get(`${BASE}/api/invoices/${id}/pages/1.png`);
  if (r.ok()) fs.writeFileSync(path.join(OUT, "pages", `${k}.png`), await r.body());
}

// ---- phone shots (supplier) ----
const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, colorScheme: "light" });
const pp = await phone.newPage();
pp.setDefaultTimeout(90_000);
await as(phone, pp, "invoices@kesar-spares.example", "/portal");
await shot(pp, "phone-portal-en.png");
await pp.getByRole("button", { name: /हिन्दी/ }).first().click();
await sleep(800);
await shot(pp, "phone-portal-hi.png");
await pp.getByRole("button", { name: /English/ }).first().click();
await sleep(500);
await pp.getByRole("button", { name: "Payment assistant" }).click();
const chat = pp.getByRole("region", { name: "Where is my payment?" });
await chat.getByRole("textbox").fill("When will I get paid for INV/0042?");
await chat.getByRole("button", { name: "Ask" }).click();
await chat.getByText(/Expected payment/).first().waitFor();
await shot(pp, "phone-chat.png");

await browser.close();
api.kill();
if (process.platform === "win32") { try { execFileSync("taskkill", ["/pid", String(web.pid), "/T", "/F"], { stdio: "ignore" }); } catch {} } else web.kill();
console.log("done:", fs.readdirSync(OUT).join(", "));
process.exit(0);
