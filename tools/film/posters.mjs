// Renders the LinkedIn images from tools/film/posters.html into media/linkedin/ (2x for crispness, saved at 1x).
//   node tools/film/posters.mjs
import http from "node:http";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(ROOT, "frontend", "package.json"));
const { chromium } = require("@playwright/test");
const TYPES = { ".html": "text/html", ".png": "image/png", ".woff2": "font/woff2" };
const server = http.createServer((req, res) => {
  const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
}).listen(5298);

const OUT = path.join(ROOT, "media", "linkedin");
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? "msedge" });
const jobs = [["hero", 1080, 1350, "1-duly-every-invoice.png"], ["fraud", 1080, 1350, "2-duly-catches-what-slips-through.png"],
  ["suppliers", 1080, 1350, "3-duly-suppliers-paid-on-time.png"], ["thumb", 1920, 1080, "video-thumbnail.png"]];
for (const [id, w, h, name] of jobs) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
  await page.goto(`http://localhost:5298/tools/film/posters.html?id=${id}`);
  await page.evaluate(() => window.READY);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, name), clip: { x: 0, y: 0, width: w, height: h } });
  await page.close();
  console.log("saved", name);
}
await browser.close();
server.close();
