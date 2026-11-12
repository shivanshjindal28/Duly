// Playwright smoke test of the demo path. Starts its own backend (fresh seeded DB with history,
// AI offline, temp data folder) on :8100 and Vite on :5180, so it never touches the dev database
// or a running `python run.py`.
//
//   npx playwright install chromium   # once (or use an installed browser: PW_CHANNEL=msedge / chrome)
//   npx playwright test
import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const API_PORT = 8100;
const WEB_PORT = 5180;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const python =
  process.env.PYTHON ??
  path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], channel: process.env.PW_CHANNEL } }],
  webServer: [
    {
      command: `"${python}" scripts/e2e_server.py`,
      cwd: root,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: { DULY_API_PORT: String(API_PORT) },
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: "npm run dev",
      url: `http://localhost:${WEB_PORT}`,
      env: { DULY_WEB_PORT: String(WEB_PORT), DULY_API_URL: `http://127.0.0.1:${API_PORT}` },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
