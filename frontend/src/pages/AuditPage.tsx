import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Link2Off, ShieldCheck, ShieldX } from "lucide-react";
import { api } from "../api/client";
import { fmtDateTime } from "../lib/format";
import "./AuditPage.css";

export interface AuditEvent {
  id: number;
  ts: string;
  actor: string | null;
  actor_role: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
  prev_hash: string;
  hash: string;
}
interface VerifyOut {
  ok: boolean;
  events: number;
  head_id: number | null;
  head_hash: string | null;
  head_signature_ok: boolean;
  broken_at_id: number | null;
  problem: string | null;
  expected_hash: string | null;
  stored_hash: string | null;
  verified_at: string | null;
  public_key: string;
  algorithm: string;
}

const short = (h: string | null) => (h ? `${h.slice(0, 8)}…${h.slice(-4)}` : "-");

export function summarise(e: AuditEvent): string {
  const a = (e.after ?? {}) as Record<string, unknown>;
  switch (e.action) {
    case "invoice.matched":
      return `${a.decision} (${(a.reasons as string[] | undefined)?.join(", ") || "clean"}) · ${a.trigger}`;
    case "invoice.uploaded":
      return `${a.invoice_number} · ${a.text_source} · ${(a.needs_review as string[] | undefined)?.length ?? 0} to review`;
    case "field.reviewed":
      return `${a.field}: ${(e.before as Record<string, unknown>)?.value ?? "-"} → ${a.value} ("${a.reason}")`;
    case "approval.approved":
      return `L${a.level}${a.mfa ? " with MFA" : ""}${a.comment ? `: "${a.comment}"` : ""}`;
    case "approval.routed":
      return `levels ${(a.levels as number[]).map((l) => "L" + l).join(" → ")}${a.override ? " (override)" : ""}`;
    case "security.sod_refused":
      return String(a.reason ?? "");
    case "auth.login_failed":
      return String(a.why ?? "");
    default:
      return Object.entries(a)
        .slice(0, 3)
        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
        .join(" · ");
  }
}

/** Auditor: verify the hash chain (visual chain of blocks) and browse events. */
export function AuditPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const verify = useMutation({
    mutationFn: () => api<VerifyOut>("/audit/verify"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["audit-events"] }),
  });
  const events = useQuery({
    queryKey: ["audit-events", filter],
    queryFn: () => api<AuditEvent[]>(`/audit/events?limit=200${filter ? `&action=${encodeURIComponent(filter)}` : ""}`),
  });
  // Opened as /audit?verify=1 (e.g. from the command palette): run the check straight away, once.
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    if (params.get("verify") === "1") {
      setParams({}, { replace: true });
      verify.mutate();
    }
  }, [params, setParams, verify]);
  const v = verify.data;
  const all = events.data ?? [];
  // Chain view: the 10 most recent blocks, or the neighbourhood of the break.
  const around = v && !v.ok && v.broken_at_id ? all.filter((e) => Math.abs(e.id - v.broken_at_id!) <= 4) : all.slice(0, 10);
  const chain = [...around].sort((a, b) => a.id - b.id);

  // Bring the first broken block into view (the strip scrolls horizontally).
  useEffect(() => {
    document.querySelector(".block.is-first-broken")?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  }, [v, events.data]);

  return (
    <div className="page audit-page">
      <header className="page-head page-head-row">
        <div>
          <p className="label">Tamper-evident audit trail</p>
          <h1>Audit chain</h1>
          <p className="muted">Every event stores SHA-256(previous hash + event). The latest hash is signed with Duly's Ed25519 key.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => verify.mutate()} disabled={verify.isPending}>
          <ShieldCheck size={16} aria-hidden="true" /> {verify.isPending ? "Verifying..." : "Verify chain"}
        </button>
      </header>

      {v ? (
        <section className={`panel verify-result ${v.ok ? "is-ok" : "is-broken"}`} role="status">
          {v.ok ? <ShieldCheck size={28} aria-hidden="true" /> : <ShieldX size={28} aria-hidden="true" />}
          <div>
            <h2>{v.ok ? "Chain verified" : `Chain broken at event #${v.broken_at_id}`}</h2>
            {v.ok ? (
              <p>
                {v.events} events re-hashed; every link matches. Head #{v.head_id} <span className="mono">{short(v.head_hash)}</span>{" "}
                signature valid.
              </p>
            ) : (
              <>
                <p>{v.problem}</p>
                <p className="mono verify-hashes">
                  expected {short(v.expected_hash)} · stored {short(v.stored_hash)}
                </p>
              </>
            )}
            <p className="muted verify-meta">
              {v.algorithm} · verified {fmtDateTime(v.verified_at)} · public key <span className="mono">{v.public_key.slice(0, 16)}…</span>
            </p>
          </div>
        </section>
      ) : null}

      {chain.length > 0 ? (
        <section className="chain" aria-label="Chain of blocks" tabIndex={0}>
          {chain.map((e, i) => {
            const broken = v && !v.ok && v.broken_at_id !== null && e.id >= v.broken_at_id;
            const first = v && !v.ok && e.id === v.broken_at_id;
            return (
              <div key={e.id} className="chain-item">
                {i > 0 ? (
                  broken ? (
                    <Link2Off size={16} className="chain-link is-broken" aria-label="broken link" />
                  ) : (
                    <Link2 size={16} className="chain-link" aria-label="linked" />
                  )
                ) : null}
                <div className={`block${first ? " is-first-broken" : broken ? " is-broken" : v?.ok ? " is-ok" : ""}`}>
                  <p className="block-id mono">#{e.id}</p>
                  <p className="block-action">{e.action}</p>
                  <p className="block-hash mono" title={e.hash}>
                    {short(e.hash)}
                  </p>
                  <p className="block-prev mono" title={`previous: ${e.prev_hash}`}>
                    ↖ {e.prev_hash.slice(0, 6)}
                  </p>
                </div>
              </div>
            );
          })}
        </section>
      ) : null}

      <section className="panel table-panel">
        <div className="audit-filter">
          <label className="field">
            <span>Filter by action</span>
            <select className="input" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All events</option>
              <option value="auth.">Logins</option>
              <option value="invoice.">Invoices (upload, match, override)</option>
              <option value="field.">Human review</option>
              <option value="approval.">Approvals</option>
              <option value="security.">Security (SoD refusals)</option>
              <option value="gr.">Goods receipts</option>
              <option value="demo.">Demo controls</option>
            </select>
          </label>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Time</th>
              <th scope="col">Actor</th>
              <th scope="col">Action</th>
              <th scope="col">Entity</th>
              <th scope="col">Details</th>
              <th scope="col">Hash</th>
            </tr>
          </thead>
          <tbody>
            {all.map((e) => (
              <tr key={e.id} className={v && !v.ok && v.broken_at_id === e.id ? "row-broken" : ""}>
                <td className="num">{e.id}</td>
                <td className="muted">{fmtDateTime(e.ts)}</td>
                <td>
                  {e.actor ?? <span className="muted">system</span>}
                  {e.actor_role ? <span className="muted"> · {e.actor_role}</span> : null}
                </td>
                <td className="mono">{e.action}</td>
                <td>
                  {e.entity_type === "invoice" && e.entity_id ? (
                    <Link to={`/invoices/${e.entity_id}`}>invoice {e.entity_id}</Link>
                  ) : (
                    <span className="muted">{[e.entity_type, e.entity_id].filter(Boolean).join(" ")}</span>
                  )}
                </td>
                <td className="audit-details">{summarise(e)}</td>
                <td className="mono muted">{e.hash.slice(0, 8)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
