import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BadgeIndianRupee, CalendarClock, CheckCircle2, Info, Lock, Percent, Send, Timer } from "lucide-react";
import { api, ApiError } from "../api/client";
import { fmtDate, fmtDateTime, inr } from "../lib/format";
import "./DashboardPage.css";
import "./PaymentsPage.css";

type Rule = "overdue" | "msme" | "discount" | "terms" | "defer";

interface Item {
  invoice_id: number;
  invoice_number: string;
  supplier_name: string;
  msme: boolean;
  invoice_date: string | null;
  due_date: string | null;
  msme_due_date: string | null;
  days_left: number | null;
  pay: boolean;
  rule: Rule;
  reason: string;
  gross: string;
  taxable: string;
  discount: string;
  discount_apr_pct: string | null;
  tds_section: string;
  tds_label: string;
  tds_rate_pct: string;
  tds: string;
  net: string;
  interest_if_late: string;
}

interface Run {
  run_date: string;
  next_run: string;
  cost_of_funds_pct: string;
  items: Item[];
  summary: {
    cash_kept: string;
    cash_kept_avg_days: string | null;
    dpo_on_plan_days: string | null;
    dpo_if_all_paid_today_days: string | null;
  };
  assumptions: { payments: Record<string, number>; tds: Record<string, Record<string, number | string>>; rbi_bank_rate_pct: number };
  can_release: boolean;
}

interface MsmeRow {
  invoice_id: number;
  invoice_number: string;
  supplier_name: string;
  amount: string;
  due_date: string;
  paid_on: string | null;
  status: "on_time" | "paid_late" | "open" | "overdue";
  days_left: number | null;
  days_late: number;
  interest: string;
  deduction_at_risk: string;
  tax_effect: string;
}

interface Guardian {
  rows: MsmeRow[];
  totals: { open: number; due_7d: number; overdue: number; on_time_pct: number | null; interest: string; deduction_at_risk: string; tax_effect: string };
  assumptions: { rbi_bank_rate_pct: number; interest_rate_pct: number; corporate_tax_rate_pct: number };
  tax_rule: string;
  form1: {
    period: string;
    as_of: string;
    total_outstanding: string;
    rows: { supplier_name: string; udyam_no: string | null; invoice_number: string; amount_due: string; due_since: string; paid_on: string | null; days_beyond: number; reason_for_delay: string }[];
  };
}

interface Paid {
  id: number;
  run_id: string;
  invoice_id: number;
  invoice_number: string;
  supplier_name: string;
  paid_at: string;
  gross: string;
  discount: string;
  tds: string;
  tds_section: string;
  net: string;
  utr: string;
}

const RULE: Record<Rule, { cls: string; label: string }> = {
  overdue: { cls: "chip-block", label: "Overdue" },
  msme: { cls: "chip-flag", label: "MSME due" },
  discount: { cls: "chip-approve", label: "Take discount" },
  terms: { cls: "chip-info", label: "Due on terms" },
  defer: { cls: "chip-neutral", label: "Later run" },
};

const MSME_STATUS: Record<MsmeRow["status"], { cls: string; label: string }> = {
  open: { cls: "chip-info", label: "Open" },
  overdue: { cls: "chip-block", label: "Overdue" },
  on_time: { cls: "chip-approve", label: "Paid on time" },
  paid_late: { cls: "chip-flag", label: "Paid late" },
};

function sum(items: Item[], k: "gross" | "discount" | "tds" | "net"): number {
  return items.reduce((a, i) => a + Number(i[k]), 0);
}

function Kpi({ icon: Icon, label, value, sub, tone }: { icon: typeof Timer; label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <span className="kpi-label">
        <Icon size={13} aria-hidden="true" /> {label}
      </span>
      <span className="kpi-value num">{value}</span>
      {sub ? <span className="kpi-sub">{sub}</span> : null}
    </div>
  );
}

function Countdown({ days }: { days: number | null }) {
  if (days === null) return <span className="muted">-</span>;
  const cls = days < 0 ? "cd-late" : days <= 7 ? "cd-soon" : "cd-ok";
  return <span className={`countdown ${cls}`}>{days < 0 ? `${-days} d late` : `${days} d left`}</span>;
}

/** Finance: MSME 45-day guardian (D4) and the smart payment run with TDS (D5). */
export function PaymentsPage() {
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["payment-run"], queryFn: () => api<Run>("/payments/run") });
  const guard = useQuery({ queryKey: ["msme-guardian"], queryFn: () => api<Guardian>("/payments/msme") });
  const hist = useQuery({ queryKey: ["payment-history"], queryFn: () => api<Paid[]>("/payments/history") });
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [released, setReleased] = useState<string | null>(null);

  useEffect(() => {
    if (run.data) setPicked(new Set(run.data.items.filter((i) => i.pay).map((i) => i.invoice_id)));
  }, [run.data]);

  const chosen = useMemo(() => (run.data?.items ?? []).filter((i) => picked.has(i.invoice_id)), [run.data, picked]);
  const release = useMutation({
    mutationFn: () =>
      api<{ run_id: string; payments: { utr: string }[] }>("/payments/run/release", {
        method: "POST",
        body: JSON.stringify({ invoice_ids: chosen.map((i) => i.invoice_id) }),
      }),
    onSuccess: (r) => {
      setReleased(`${r.run_id}: ${r.payments.length} payments released with simulated UTRs.`);
      for (const k of ["payment-run", "msme-guardian", "payment-history", "invoices", "dashboard"]) qc.invalidateQueries({ queryKey: [k] });
    },
  });

  const g = guard.data;
  const r = run.data;
  const toggle = (id: number) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };

  return (
    <div className="page payments">
      <header className="page-head">
        <p className="label">Finance · working capital</p>
        <h1>Payments</h1>
        <p className="muted">
          MSME suppliers by statutory due date first, early-payment discounts only when they beat the cost of funds,
          everyone else on contract terms. {r ? `Run date ${fmtDate(r.run_date)}, next run ${fmtDate(r.next_run)}.` : ""}
        </p>
      </header>

      {g ? (
        <section className="panel guardian" aria-labelledby="guardian-h">
          <h2 id="guardian-h">
            <Timer size={16} aria-hidden="true" /> MSME 45-day guardian
          </h2>
          <div className="kpis kpis-4">
            <Kpi icon={CalendarClock} label="Open MSME invoices" value={String(g.totals.open)} sub={`${g.totals.due_7d} due within 7 days`} />
            <Kpi icon={AlertTriangle} label="Past due date" value={String(g.totals.overdue)}
              sub={g.totals.on_time_pct === null ? "No MSME payments yet" : `${g.totals.on_time_pct}% paid on time`}
              tone={g.totals.overdue ? "kpi-alert" : ""} />
            <Kpi icon={Percent} label="Interest exposure" value={inr(g.totals.interest)}
              sub={`MSMED s.16: ${g.assumptions.interest_rate_pct.toFixed(2)}% a year (3 x bank rate ${g.assumptions.rbi_bank_rate_pct}%), monthly rests`} />
            <div className="kpi">
              <span className="kpi-label">
                <BadgeIndianRupee size={13} aria-hidden="true" /> Tax deduction at risk
                <span className="tip" tabIndex={0} aria-label={g.tax_rule}>
                  <Info size={12} aria-hidden="true" />
                  <span role="tooltip" className="tip-body">{g.tax_rule}</span>
                </span>
              </span>
              <span className="kpi-value num">{inr(g.totals.deduction_at_risk)}</span>
              <span className="kpi-sub">
                Tax effect {inr(g.totals.tax_effect)} at an assumed {g.assumptions.corporate_tax_rate_pct}%. A tax professional should confirm.
              </span>
            </div>
          </div>
        </section>
      ) : null}

      <section className="panel table-panel" aria-labelledby="run-h">
        <div className="run-head">
          <h2 id="run-h">Payment proposal</h2>
          {r ? <span className="muted">Cost of funds assumption {r.cost_of_funds_pct}% a year</span> : null}
        </div>
        {r && r.items.length === 0 ? <p className="empty">No approved invoices waiting for payment.</p> : null}
        {r && r.items.length ? (
          <table className="table run-table">
            <thead>
              <tr>
                <th scope="col"><span className="sr-only">Pay</span></th>
                <th scope="col">Invoice</th>
                <th scope="col">Due</th>
                <th scope="col">Why</th>
                <th scope="col" className="num-col">Gross</th>
                <th scope="col" className="num-col">Discount</th>
                <th scope="col" className="num-col">TDS</th>
                <th scope="col" className="num-col">Net to bank</th>
              </tr>
            </thead>
            <tbody>
              {r.items.map((i) => (
                <tr key={i.invoice_id} className={picked.has(i.invoice_id) ? "" : "row-off"}>
                  <td>
                    <input type="checkbox" checked={picked.has(i.invoice_id)} onChange={() => toggle(i.invoice_id)}
                      aria-label={`Pay ${i.invoice_number}`} disabled={!r.can_release} />
                  </td>
                  <td>
                    <Link className="row-link" to={`/invoices/${i.invoice_id}`}>{i.invoice_number}</Link>
                    <div className="muted small">{i.supplier_name}{i.msme ? " · MSME" : ""}</div>
                  </td>
                  <td>
                    <div>{fmtDate(i.msme_due_date ?? i.due_date)}</div>
                    <Countdown days={i.days_left} />
                  </td>
                  <td className="why">
                    <span className={`chip ${RULE[i.rule].cls}`}>{RULE[i.rule].label}</span>
                    <div className="small">{i.reason}</div>
                  </td>
                  <td className="num-col num">{inr(i.gross)}</td>
                  <td className="num-col num">{Number(i.discount) ? inr(i.discount) : "-"}</td>
                  <td className="num-col num" title={i.tds_section === "none" ? "No TDS" : `${i.tds_label} at ${i.tds_rate_pct}%`}>
                    {Number(i.tds) ? inr(i.tds) : "-"}
                    {i.tds_section !== "none" ? <div className="muted small">{i.tds_label.split(" (")[0]}</div> : null}
                  </td>
                  <td className="num-col num strong">{inr(Number(i.net))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {r && r.items.length ? (
          <footer className="run-foot">
            <div className="run-totals">
              <span>{chosen.length} selected</span>
              <span>Gross {inr(sum(chosen, "gross"))}</span>
              <span>Discounts {inr(sum(chosen, "discount"))}</span>
              <span>TDS withheld {inr(sum(chosen, "tds"))}</span>
              <span className="strong">Cash out {inr(sum(chosen, "net"))}</span>
            </div>
            <p className="muted small">
              Cash kept by paying on terms, not early: {inr(r.summary.cash_kept)}
              {r.summary.cash_kept_avg_days ? ` for about ${r.summary.cash_kept_avg_days} more days` : ""}. Days payable on this
              plan {r.summary.dpo_on_plan_days ?? "-"} vs {r.summary.dpo_if_all_paid_today_days ?? "-"} if every approved invoice
              were paid today. TDS under s.393 of the Income-tax Act 2025 (formerly 194C/194J/194Q): rates and thresholds are a
              policy table, verify with the tax team.
            </p>
            <div className="run-actions">
              <button type="button" className="btn btn-primary" disabled={!r.can_release || !chosen.length || release.isPending}
                onClick={() => release.mutate()} title={r.can_release ? "" : "Only a finance approver can release a payment run"}>
                {r.can_release ? <Send size={15} aria-hidden="true" /> : <Lock size={15} aria-hidden="true" />} Release {chosen.length} payments
              </button>
              {!r.can_release ? <span className="muted small">Proposal only: a finance approver releases the run.</span> : null}
            </div>
            {released ? (
              <p className="alert alert-success" role="status">
                <CheckCircle2 size={14} aria-hidden="true" /> {released} Suppliers see them as "Duly paid" in the portal and chatbot.
              </p>
            ) : null}
            {release.isError ? (
              <p className="alert alert-error" role="alert">{release.error instanceof ApiError ? release.error.message : "Release failed."}</p>
            ) : null}
          </footer>
        ) : null}
      </section>

      {g ? (
        <section className="panel table-panel" aria-labelledby="msme-h">
          <h2 id="msme-h" className="panel-title">MSME invoices</h2>
          {g.rows.length === 0 ? <p className="empty">No MSME invoices accepted yet.</p> : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Invoice</th>
                  <th scope="col">Statutory due</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num-col">Amount</th>
                  <th scope="col" className="num-col">Interest (s.16)</th>
                  <th scope="col" className="num-col">Deduction at risk</th>
                </tr>
              </thead>
              <tbody>
                {g.rows.map((x) => (
                  <tr key={x.invoice_id}>
                    <td>
                      <Link className="row-link" to={`/invoices/${x.invoice_id}`}>{x.invoice_number}</Link>
                      <div className="muted small">{x.supplier_name}</div>
                    </td>
                    <td>
                      <div>{fmtDate(x.due_date)}</div>
                      {x.paid_on ? <span className="muted small">paid {fmtDate(x.paid_on)}</span> : <Countdown days={x.days_left} />}
                    </td>
                    <td><span className={`chip ${MSME_STATUS[x.status].cls}`}>{MSME_STATUS[x.status].label}</span></td>
                    <td className="num-col num">{inr(x.amount)}</td>
                    <td className="num-col num">{Number(x.interest) ? inr(x.interest) : "-"}</td>
                    <td className="num-col num">{Number(x.deduction_at_risk) ? inr(x.deduction_at_risk) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      {g ? (
        <section className="panel form1" aria-labelledby="form1-h">
          <h2 id="form1-h">MSME dues outstanding beyond 45 days · {g.form1.period}</h2>
          <p className="muted small">
            Half-yearly summary (the data for MSME Form I), as of {fmtDate(g.form1.as_of)}. Total {inr(g.form1.total_outstanding)}.
          </p>
          {g.form1.rows.length === 0 ? <p className="empty">Nothing outstanding beyond the due date in this half year.</p> : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Supplier</th>
                  <th scope="col">Udyam no.</th>
                  <th scope="col">Invoice</th>
                  <th scope="col">Due since</th>
                  <th scope="col" className="num-col">Days beyond</th>
                  <th scope="col" className="num-col">Amount</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {g.form1.rows.map((x) => (
                  <tr key={x.invoice_number}>
                    <td>{x.supplier_name}</td>
                    <td className="mono">{x.udyam_no ?? "-"}</td>
                    <td>{x.invoice_number}</td>
                    <td>{fmtDate(x.due_since)}</td>
                    <td className="num-col num">{x.days_beyond}</td>
                    <td className="num-col num">{inr(x.amount_due)}</td>
                    <td>{x.reason_for_delay}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      <section className="panel table-panel" aria-labelledby="paid-h">
        <h2 id="paid-h" className="panel-title">Duly paid</h2>
        {(hist.data ?? []).length === 0 ? <p className="empty">No payments released yet.</p> : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Invoice</th>
                <th scope="col">Paid</th>
                <th scope="col" className="num-col">TDS</th>
                <th scope="col" className="num-col">Net</th>
                <th scope="col">UTR (simulated)</th>
              </tr>
            </thead>
            <tbody>
              {(hist.data ?? []).map((p) => (
                <tr key={p.id}>
                  <td className="mono">{p.run_id}</td>
                  <td>
                    <Link className="row-link" to={`/invoices/${p.invoice_id}`}>{p.invoice_number}</Link>
                    <div className="muted small">{p.supplier_name}</div>
                  </td>
                  <td>{fmtDateTime(p.paid_at)}</td>
                  <td className="num-col num">{Number(p.tds) ? inr(p.tds) : "-"}</td>
                  <td className="num-col num">{inr(p.net)}</td>
                  <td className="mono">{p.utr}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
