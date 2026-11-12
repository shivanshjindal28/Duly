/**
 * Thin fetch wrapper for the Duly API. Sends the session cookie, adds the CSRF header
 * (double-submit token from the readable `duly_csrf` cookie) on state-changing requests,
 * and turns error responses into ApiError.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** Structured refusal flags from the server, e.g. { sod: true } or { mfa: true }. */
    public info: { sod?: boolean; mfa?: boolean } = {},
  ) {
    super(message);
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  // JSON bodies are strings; FormData (uploads) must let the browser set the multipart boundary.
  if (typeof init.body === "string" && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCookie("duly_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const res = await fetch(`/api${path}`, { ...init, method, headers, credentials: "same-origin" });
  if (!res.ok) {
    let detail = res.statusText;
    let info = {};
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail && typeof body.detail.message === "string") {
        detail = body.detail.message;
        info = { sod: !!body.detail.sod, mfa: !!body.detail.mfa };
      } else detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body: a proxy or gateway answered, not Duly */
      if (res.status === 502 || res.status === 503 || res.status === 504) {
        detail =
          "The Duly server did not answer in time. It may be waking up (about a minute after a quiet spell), or a " +
          "photo or scan is still being read. Wait a moment and refresh; PDF invoices are the quickest.";
      }
    }
    throw new ApiError(res.status, detail, info);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export interface Health {
  status: string;
  version: string;
  db: string;
  demo_mode: boolean;
  ai_mode: "live" | "cached" | "offline";
  policy_version: number | null;
}
