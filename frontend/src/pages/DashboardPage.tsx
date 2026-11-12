import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, CalendarClock, Clock, Copy, Inbox, Wallet, Zap } from "lucide-react";
import { api } from "../api/client";
import { tokens } from "../theme/tokens";
import { fmtDate, fmtDateTime, inr } from "../lib/format";
import "./DashboardPage.css";

interface Summary {
  as_of: string;
  kpis: {
    in_queue: number;
    value_on_hold: string;
    touchless_rate: number | null;
    approved_count: number;
    avg_cycle_hours: number | null;
    msme_due_7d: number;
    msme_overdue: number;
    duplicates_prevented: number;
    duplicates_value: string;
  };
  by_type: { code: string; title: string; severity: string; count: number; value: string }[];
  by_supplier: { supplier_id: number; supplier_name: string; msme: string; open_exceptions: number; value_at_risk: string; oldest_days: number }[];
  by_age: { bucket: string; count: number; value: string }[];
  msme_due: { day: string; count: number; value: string }[];
}

const C = tokens.color;

function Kpi({ icon: Icon, label, value, sub, onClick }: { icon: typeof Inbox; label: string; value: string; sub?: string; onClick?: () => void }) {
  const body = (
    <>
      <span className="kpi-label">
        <Icon size={13} aria-hidden="true" /> {label}
      </span>
      <span className="kpi-value num">{value}</span>
      {sub ? <span className="kpi-sub">{sub}</span> : null}
    </>
  );
  return onClick ? (
    <button type="button" className="kpi kpi-link" onClick={onClick}>
      {body}
    </button>
  ) : (
    <div className="kpi">{body}</div>
  );
}

function cycle(hours: number | null): string {
  if (hours === null) return "-";
  return hours < 48 ? `${hours.toFixed(1)} h` : `${(hours / 24).toFixed(1)} d`;
}

/** Exceptions dashboard: every number is computed live from the database; every chart drills down. */
export function DashboardPage() {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Summary>("/dashboard/summary") });
  const go = (params: Record<string, string | number>) =>
    navigate(`/queue?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()}`);

  if (q.isLoading || !q.data) {
    return (
      <div className="page" aria-busy="true">
        <div className="skeleton-row" style={{ height: 90 }} />
        <div className="skeleton-row" style={{ height: 300 }} />
      </div>
    );
  }
  const d = q.data;
  const k = d.kpis;
  const maxDue = Math.max(1, ...d.msme_due.map((x) => x.count));
  const today = d.as_of.slice(0, 10);

  return (
    <div className="page dashboard">
      <header className="page-head page-head-row">
        <div>
          <p className="label">Accounts payable · Plant X</p>
          <h1>Exceptions dashboard</h1>
        </div>
        <span className="muted as-of">As of {fmtDateTime(d.as_of)} (business time)</span>
      </header>

      <section className="kpis" aria-label="Key figures">
        <Kpi icon={Inbox} label="In queue" value={String(k.in_queue)} sub="open invoices" onClick={() => go({ status: "open" })} />
        <Kpi icon={AlertTriangle} label="Value on hold" value={inr(k.value_on_hold)} sub="blocked, flagged, in review" onClick={() => go({ status: "open" })} />
        <Kpi
          icon={Zap}
          label="Touchless rate"
          value={k.touchless_rate === null ? "-" : `${Math.round(k.touchless_rate * 100)}%`}
          sub={`of ${k.approved_count} approved, no human touch`}
        />
        <Kpi icon={Clock} label="Avg cycle time" value={cycle(k.avg_cycle_hours)} sub="upload to final approval" />
        <Kpi
          icon={CalendarClock}
          label="MSME due ≤ 7 days"
          value={String(k.msme_due_7d)}
          sub={k.msme_overdue ? `${k.msme_overdue} already overdue` : "none overdue"}
          onClick={() => go({ status: "all", msme_due_within: 7 })}
        />
        <Kpi icon={Copy} label="Duplicates prevented" value={String(k.duplicates_prevented)} sub={inr(k.duplicates_value)} />
      </section>

      <div className="dash-grid">
        <section className="panel chart-panel" aria-labelledby="type-title">
          <h2 id="type-title" className="label">
            Open exceptions by type
          </h2>
          {d.by_type.length === 0 ? (
            <p className="empty">No open exceptions.</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={Math.max(160, d.by_type.length * 38)}>
                <BarChart data={d.by_type} layout="vertical" margin={{ left: 8, right: 40 }}>
                  <XAxis type="number" dataKey="count" allowDecimals={false} domain={[0, (max: number) => Math.max(1, max)]} hide />
                  <YAxis type="category" dataKey="title" width={190} tick={{ fontSize: 12, fill: C.text }} />
                  <Tooltip formatter={(v) => [String(v), "invoices"]} />
                  <Bar dataKey="count" radius={[0, 3, 3, 0]} cursor="pointer" onClick={(e) => go({ status: "open", reason: (e as unknown as { code: string }).code })}>
                    {d.by_type.map((t) => (
                      <Cell key={t.code} fill={t.severity === "block" ? C.magenta : C.amber} />
                    ))}
                    <LabelList dataKey="count" position="right" style={{ fontSize: 12, fill: C.text }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <ul className="legend">
                <li>
                  <span className="swatch" style={{ background: C.magenta }} /> Blocks (cannot be paid)
                </li>
                <li>
                  <span className="swatch" style={{ background: C.amber }} /> Flags (clerk review)
                </li>
              </ul>
              <ul className="sr-only">
                {d.by_type.map((t) => (
                  <li key={t.code}>
                    <button type="button" onClick={() => go({ status: "open", reason: t.code })}>
                      {t.title}: {t.count}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="panel chart-panel" aria-labelledby="age-title">
          <h2 id="age-title" className="label">
            Open exceptions by age (days)
          </h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={d.by_age} margin={{ top: 16 }}>
              <XAxis dataKey="bucket" tick={{ fontSize: 12, fill: C.text }} />
              <YAxis allowDecimals={false} width={28} tick={{ fontSize: 11, fill: C.textSecondary }} />
              <Tooltip formatter={(v) => [String(v), "invoices"]} />
              <Bar dataKey="count" fill={C.primary} radius={[3, 3, 0, 0]} cursor="pointer" onClick={(e) => go({ status: "open", age: (e as unknown as { bucket: string }).bucket })}>
                <LabelList dataKey="count" position="top" style={{ fontSize: 12, fill: C.text }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>

      <section className="panel table-panel" aria-labelledby="sup-title">
        <h2 id="sup-title" className="label panel-title">
          Open exceptions by supplier
        </h2>
        {d.by_supplier.length === 0 ? (
          <p className="empty">No open exceptions.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Supplier</th>
                <th scope="col">MSME</th>
                <th scope="col" className="num-col">
                  Open exceptions
                </th>
                <th scope="col" className="num-col">
                  Value at risk
                </th>
                <th scope="col" className="num-col">
                  Oldest (days)
                </th>
              </tr>
            </thead>
            <tbody>
              {d.by_supplier.map((s) => (
                <tr key={s.supplier_id}>
                  <td>
                    <button type="button" className="link-btn" onClick={() => go({ status: "open", supplier_id: s.supplier_id })}>
                      {s.supplier_name}
                    </button>
                  </td>
                  <td>{s.msme === "none" ? <span className="muted">No</span> : <span className="chip chip-info">{s.msme}</span>}</td>
                  <td className="num num-col">{s.open_exceptions}</td>
                  <td className="num num-col">{inr(s.value_at_risk)}</td>
                  <td className="num num-col">{s.oldest_days}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel chart-panel" aria-labelledby="msme-title">
        <h2 id="msme-title" className="label">
          MSME statutory due dates (next 30 days)
        </h2>
        <p className="muted heat-note">Darker = more MSME invoices due that day. Days before today are shown if still unpaid (overdue).</p>
        <ol className="heat" aria-label="MSME due dates by day">
          {d.msme_due.map((x) => {
            const past = x.day < today;
            const level = x.count === 0 ? 0 : Math.ceil((x.count / maxDue) * 4);
            return (
              <li key={x.day}>
                <button
                  type="button"
                  className={`heat-day heat-${level}${past && x.count ? " heat-overdue" : ""}${x.day === today ? " heat-today" : ""}`}
                  title={`${fmtDate(x.day)}: ${x.count} invoice(s), ${inr(x.value)}`}
                  onClick={() => x.count && go({ status: "all", msme_due_within: Math.max(0, Math.round((Date.parse(x.day) - Date.parse(today)) / 86400000)) })}
                >
                  <span className="heat-dom">{x.day.slice(8, 10)}</span>
                  <span className="sr-only"> {fmtDate(x.day).slice(3)}: </span>
                  {x.count ? <span className="heat-count">{x.count}</span> : null}
                  <span className="sr-only">
                    {x.count ? ` MSME invoice${x.count === 1 ? "" : "s"} due${past ? ", overdue" : ""}` : "no MSME invoices due"}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </section>
      <p className="muted dash-foot">
        <Wallet size={12} aria-hidden="true" /> Duplicates prevented counts invoices the rules engine blocked or flagged as duplicates.
      </p>
    </div>
  );
}
