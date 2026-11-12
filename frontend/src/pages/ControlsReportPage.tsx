import { useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash, Download, FileCheck2, OctagonX } from "lucide-react";
import { api } from "../api/client";
import { fmtDateTime, inr } from "../lib/format";
import "./ControlsReportPage.css";

interface Control {
  id: string;
  title: string;
  objective: string;
  how: string;
  test: string;
  result: "effective" | "exceptions" | "no_activity";
  population: number;
  exceptions: { invoice_id?: number; invoice_number?: string; detail: string }[];
  metrics: Record<string, unknown>;
  evidence: { invoice_id?: number; invoice_number?: string; detail?: string; label?: string }[];
}
interface Report {
  period_from: string;
  period_to: string;
  generated_at: string;
  controls: Control[];
  overrides: { invoice_id: number; invoice_number: string; total: string; by: string | null; at: string | null; justification: string; approved_by: string[]; status: string }[];
  opinion: string;
}

const RESULT = {
  effective: { label: "Effective", cls: "chip-approve", Icon: CheckCircle2 },
  exceptions: { label: "Exceptions", cls: "chip-block", Icon: OctagonX },
  no_activity: { label: "No activity", cls: "chip-neutral", Icon: CircleSlash },
} as const;

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function Metrics({ m }: { m: Record<string, unknown> }) {
  const entries = Object.entries(m).filter(([k]) => k !== "users");
  if (!entries.length) return null;
  return (
    <dl className="ctl-metrics">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd className="mono">
            {k.endsWith("_inr") ? inr(String(v)) : typeof v === "object" && v !== null ? Object.entries(v).map(([a, b]) => `${a}: ${b}`).join(" · ") : String(v ?? "-")}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Auditor: every control tested on live data for a period; downloadable as PDF. */
export function ControlsReportPage() {
  const today = new Date();
  const [from, setFrom] = useState(iso(new Date(today.getTime() - 120 * 86400000)));
  const [to, setTo] = useState(iso(today));
  const [params, setParams] = useState({ from, to });
  const q = useQuery({
    queryKey: ["controls", params],
    queryFn: () => api<Report>(`/reports/controls?from=${params.from}&to=${params.to}`),
  });
  const r = q.data;

  return (
    <div className="page controls-page">
      <header className="page-head page-head-row">
        <div>
          <p className="label">Internal audit</p>
          <h1>Controls report</h1>
          <p className="muted">Each control is tested against the live data for the period, not asserted.</p>
        </div>
        <a className="btn btn-primary" href={`/api/reports/controls.pdf?from=${params.from}&to=${params.to}`}>
          <Download size={16} aria-hidden="true" /> Download PDF
        </a>
      </header>

      <form
        className="panel ctl-period"
        onSubmit={(e) => {
          e.preventDefault();
          setParams({ from, to });
        }}
      >
        <label className="field">
          <span>From</span>
          <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="field">
          <span>To</span>
          <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <button className="btn" type="submit">
          <FileCheck2 size={16} aria-hidden="true" /> Generate
        </button>
      </form>

      {!r ? (
        <div className="skeleton-row" style={{ height: 200 }} aria-busy="true" />
      ) : (
        <>
          <section className="panel ctl-opinion">
            <p className="label">Overall opinion</p>
            <p className="ctl-opinion-text">{r.opinion}</p>
            <p className="muted">Generated {fmtDateTime(r.generated_at)} · period {r.period_from} to {r.period_to}</p>
          </section>

          <div className="ctl-list">
            {r.controls.map((c) => {
              const res = RESULT[c.result];
              return (
                <details key={c.id} className={`panel ctl ctl-${c.result}`} open={c.result === "exceptions"}>
                  <summary>
                    <span className="mono ctl-id">{c.id}</span>
                    <span className="ctl-title">{c.title}</span>
                    <span className={`chip ${res.cls}`}>
                      <res.Icon size={13} aria-hidden="true" /> {res.label}
                    </span>
                    <span className="muted ctl-pop">
                      {c.population} tested · {c.exceptions.length} exception{c.exceptions.length === 1 ? "" : "s"}
                    </span>
                  </summary>
                  <div className="ctl-body">
                    <p><strong>Objective.</strong> {c.objective}</p>
                    <p><strong>How Duly enforces it.</strong> {c.how}</p>
                    <p><strong>Test performed.</strong> {c.test}</p>
                    <Metrics m={c.metrics} />
                    {c.exceptions.length ? (
                      <ul className="ctl-exc">
                        {c.exceptions.map((e, i) => (
                          <li key={i}>
                            {e.invoice_id ? <Link to={`/invoices/${e.invoice_id}`} className="mono">{e.invoice_number}</Link> : null} {e.detail}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {c.evidence.length ? (
                      <ul className="ctl-ev">
                        {c.evidence.map((e, i) => (
                          <li key={i}>
                            Evidence:{" "}
                            {e.invoice_id ? <Link to={`/invoices/${e.invoice_id}`}>{e.invoice_number ?? `invoice ${e.invoice_id}`}</Link> : null}{" "}
                            {e.detail ?? e.label}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {c.id === "C-10" && Array.isArray(c.metrics.users) ? (
                      <table className="table ctl-users">
                        <thead>
                          <tr>
                            <th scope="col">User</th>
                            <th scope="col">Role</th>
                            <th scope="col">MFA</th>
                            <th scope="col">Last login</th>
                            <th scope="col">Locked</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(c.metrics.users as { name: string; role: string; level: number | null; mfa: boolean; last_login: string | null; locked: boolean }[]).map((u) => (
                            <tr key={u.name}>
                              <td>{u.name}</td>
                              <td>{u.role}{u.level ? ` L${u.level}` : ""}</td>
                              <td>{u.mfa ? "Yes" : "No"}</td>
                              <td className="muted">{u.last_login ? fmtDateTime(u.last_login) : "Never"}</td>
                              <td>{u.locked ? "Yes" : "No"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : null}
                  </div>
                </details>
              );
            })}
          </div>

          <section className="panel table-panel">
            <h2 className="label panel-title">Overrides (FLAG routed with justification)</h2>
            {r.overrides.length === 0 ? (
              <p className="empty">No overrides in the period.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Invoice</th>
                    <th scope="col" className="num-col">Total</th>
                    <th scope="col">Overridden by</th>
                    <th scope="col">Justification</th>
                    <th scope="col">Approved by</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {r.overrides.map((o) => (
                    <tr key={o.invoice_id}>
                      <td><Link to={`/invoices/${o.invoice_id}`} className="mono">{o.invoice_number}</Link></td>
                      <td className="num num-col">{inr(o.total)}</td>
                      <td>{o.by}<div className="muted cell-sub">{fmtDateTime(o.at)}</div></td>
                      <td>{o.justification}</td>
                      <td>{o.approved_by.join(", ") || <span className="muted">pending</span>}</td>
                      <td>{o.status.replace("_", " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
