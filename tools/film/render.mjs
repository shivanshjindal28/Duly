// Renders tools/film/film.html frame by frame (deterministic: every frame is render(t) at an exact time),
// so motion is perfectly smooth whatever the machine's speed.
//
//   node tools/film/render.mjs stills 3 10 18 27   -> media/film/stills/t03.0.png ... (for review)
//   node tools/film/render.mjs frames [fps]         -> media/film/frames/000000.jpg ... (default 60 fps)
import http from "node:http";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(ROOT, "frontend", "package.json"));
const { chromium } = require("@playwright/test");
const PORT = 5299;
const TYPES = { ".html": "text/html", ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2", ".svg": "image/svg+xml" };

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const file = path.join(ROOT, p === "/" ? "tools/film/film.html" : p);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
}).listen(PORT);

const [mode = "stills", ...args] = process.argv.slice(2);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? "msedge" });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await page.goto(`http://localhost:${PORT}/tools/film/film.html`);
await page.waitForFunction(() => window.FILM, null, { timeout: 60_000 });
const total = await page.evaluate(() => window.FILM.total);

if (mode === "stills") {
  const dir = path.join(ROOT, "media/film/stills");
  fs.mkdirSync(dir, { recursive: true });
  for (const a of args) {
    const t = Number(a);
    await page.evaluate((t) => window.FILM.render(t), t);
    await page.screenshot({ path: path.join(dir, `t${t.toFixed(1).padStart(4, "0")}.png`) });
  }
  console.log(`stills: ${args.join(", ")}`);
} else {
  const fps = Number(args[0] ?? 60);
  const dir = path.join(ROOT, "media/film/frames");
  fs.rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
  fs.mkdirSync(dir, { recursive: true });
  const n = Math.ceil(total * fps);
  const started = Date.now();
  for (let i = 0; i < n; i++) {
    await page.evaluate((t) => window.FILM.render(t), i / fps);
    await page.screenshot({ path: path.join(dir, `${String(i).padStart(6, "0")}.jpg`), type: "jpeg", quality: 93 });
    if (i % 300 === 0) console.log(`frame ${i}/${n} (${((Date.now() - started) / 1000).toFixed(0)} s)`);
  }
  fs.writeFileSync(path.join(dir, "fps.txt"), String(fps));
  console.log(`rendered ${n} frames at ${fps} fps`);
}
await browser.close();
server.close();
process.exit(0);
