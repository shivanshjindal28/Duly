/**
 * Hosted demo only: the free API host sleeps when idle, and while it sleeps requests that come through the
 * website's proxy fail at once instead of waking it. A direct request does wake it, so the page sends one
 * (fire and forget, no data) as soon as it opens; the login page keeps retrying until the API answers.
 */
const WAKE_URL = "https://duly-api-7h0z.onrender.com/api/health";

export function wakeBackend(): void {
  if (!location.hostname.endsWith("duly.website")) return;
  fetch(WAKE_URL, { mode: "no-cors", cache: "no-store" }).catch(() => {});
}
