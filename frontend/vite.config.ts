import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to FastAPI so the session cookie is same-origin
// (SameSite=strict works and no CORS is needed in the browser).
// DULY_WEB_PORT / DULY_API_URL let the Playwright smoke test run its own stack beside a dev server.
// (Node's `process`, declared here so the browser-only tsconfig needs no @types/node.)
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.DULY_WEB_PORT ?? 5173),
    strictPort: true,
    proxy: { "/api": { target: process.env.DULY_API_URL ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
});
