import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Cpu, Database, FileText, Link2, ScanText, Sparkles, XCircle } from "lucide-react";
import { api } from "../api/client";
import { Markdown } from "../components/Markdown";
import "./AboutPages.css";

interface ArchitectureOut {
  markdown: string;
  status: {
    version: string;
    db: string;
    database: string;
    ai_mode: "live" | "cached" | "offline";
    ai_model: string | null;
    ocr: "loaded" | "ready" | "missing";
    audit_chain_ok: boolean;
    audit_events: number;
    policy_version: number | null;
    invoices: number;
    demo_mode: boolean;
    jobs: { queue: string; recent: { id: number; name: string; status: string; duration_ms: number | null }[] };
  };
}

function Status({ ok, icon: Icon, label, value }: { ok: boolean; icon: typeof Database; label: string; value: string }) {
  return (
    <li className="status-item">
      <Icon size={15} aria-hidden="true" className="muted" />
      <span className="status-label">{label}</span>
      <span className={`status-value ${ok ? "ok" : "bad"}`}>
        {ok ? <CheckCircle2 size={14} aria-hidden="true" /> : <XCircle size={14} aria-hidden="true" />}
        {value}
      </span>
    </li>
  );
}

/** Renders docs/ARCHITECTURE.md (the same file, served by the backend) plus a live system-status panel. */
export function ArchitecturePage() {
  const q = useQuery({ queryKey: ["architecture"], queryFn: () => api<ArchitectureOut>("/architecture") });
  const s = q.data?.status;
  return (
    <div className="page about">
      <header className="page-head">
        <p className="label">How Duly is built</p>
        <h1>Architecture</h1>
        <p className="muted">
          Rendered from <span className="mono">docs/ARCHITECTURE.md</span>: the diagram in the docs and in the app is
          one file.
        </p>
      </header>
      {s ? (
        <section className="panel about-status" aria-labelledby="status-title">
          <h2 id="status-title" className="label">
            System status
          </h2>
          <ul className="sys-status">
            <Status ok={s.db === "ok"} icon={Database} label="Database" value={`${s.database} · ${s.invoices} invoices`} />
            <Status ok icon={Sparkles} label="AI mode" value={s.ai_mode === "offline" ? "offline (OCR + rules)" : `${s.ai_mode} · ${s.ai_model}`} />
            <Status ok={s.ocr !== "missing"} icon={ScanText} label="OCR" value={s.ocr === "loaded" ? "loaded" : s.ocr === "ready" ? "ready (loads on first scan)" : "missing"} />
            <Status ok={s.audit_chain_ok} icon={Link2} label="Audit chain" value={s.audit_chain_ok ? `verified · ${s.audit_events} events` : "BROKEN"} />
            <Status ok={s.policy_version !== null} icon={FileText} label="Policy" value={`version ${s.policy_version ?? "-"}`} />
            <Status ok={!s.jobs.recent.some((j) => j.status === "failed")} icon={Cpu} label="Job queue"
              value={`${s.jobs.queue} · ${s.jobs.recent.length ? `last: ${s.jobs.recent[0].name.replace(/_/g, " ")} ${s.jobs.recent[0].duration_ms ?? "-"} ms` : "no jobs since start"}`} />
          </ul>
        </section>
      ) : null}
      <section className="panel about-doc">
        {q.isLoading ? (
          <div className="skeleton-rows" aria-busy="true">
            {Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton-row" />)}
          </div>
        ) : null}
        {q.data ? <Markdown source={q.data.markdown} /> : null}
        {q.isError ? <p className="alert alert-error">Could not load the architecture document.</p> : null}
      </section>
    </div>
  );
}
