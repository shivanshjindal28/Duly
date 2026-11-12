import { useEffect, useMemo, useState } from "react";
import { PageSkeleton } from "../components/PageSkeleton";
import { useQuery } from "@tanstack/react-query";
import { Calculator, Clock, Copy, Gauge, Info, RotateCcw, ShieldCheck, Sparkles, Timer, Zap } from "lucide-react";
import { api } from "../api/client";
import { inr, inrShort } from "../lib/format";
import "./DashboardPage.css";
import "./ImpactPage.css";

interface RootCause {
  key: string;
  title: string;
  count: number;
  value: string;
  codes: { code: string; title: string }[];
}

interface Assumption {
  key: string;
  label: string;
  unit: string;
  value: number | string | null;
  reason: string;
  measured?: string;
}

interface ImpactOut {
  measured: {
    invoices: number;
    days: number;
    value: string;
    touchless_rate: number | null;
    touchless: number;
    approved: number;
    first_pass_rate: number | null;
    avg_cycle_hours: number | null;
    p90_cycle_hours: number | null;
    root_causes: RootCause[];
    exceptions: number;
    duplicates_caught: number;
    duplicates_value: string;
    msme_paid: number;
    msme_on_time_rate: number | null;
    msme_open: number;
    ai_fields: number;
    ai_review_rate: number | null;
    ai_corrected_rate: number | null;
  };
  assumptions: Assumption[];
  formulas: Record<string, string>;
}

const STORE_KEY = "duly.impact.assumptions";
const pctText = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "-" : `${(v * 100).toFixed(digits)}%`);
const days = (h: number | null | undefined) => (h === null || h === undefined ? "-" : `${(h / 24).toFixed(1)} d`);
const num = (v: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 }).format(v);

function loadSaved(): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function Tile({ icon: Icon, label, value, sub }: { icon: typeof Zap; label: string; value: string; sub?: string }) {
  return (
    <div className="kpi">
      <span className="kpi-label">
        <Icon size={13} aria-hidden="true" /> {label}
      </span>
      <span className="kpi-value num">{value}</span>
      {sub ? <span className="kpi-sub">{sub}</span> : null}
    </div>
  );
}

/** Impact (spec section 11): measured on Duly's own data, then projected for Plant X from editable assumptions. */
export function ImpactPage() {
  const q = useQuery({ queryKey: ["impact"], queryFn: () => api<ImpactOut>("/impact") });
  const [edits, setEdits] = useState<Record<string, number>>(loadSaved);
  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(edits));
    } catch {
      /* private window: edits just are not remembered */
    }
  }, [edits]);

  const a = useMemo(() => {
    const out: Record<string, number> = {};
    for (const x of q.data?.assumptions ?? []) out[x.key] = edits[x.key] ?? Number(x.value ?? 0);
    return out;
  }, [q.data, edits]);

  if (q.isLoading) return <PageSkeleton blocks={3} label="Loading impact" />;
  if (!q.data) return <div className="page alert alert-error">Could not load the impact data.</div>;
  const m = q.data.measured;

  // Projection (formulas shown next to each figure, with the values substituted).
  const yearInvoices = a.invoices_per_month * 12;
  const valuePerYear = yearInvoices * a.avg_invoice_value;
  const hours = (a.invoices_per_month * (a.touchless_rate / 100) * (a.manual_minutes - a.duly_minutes)) / 60;
  const costYear = hours * 12 * a.cost_per_hour;
  const dupYear = yearInvoices * (a.duplicate_rate / 100) * a.avg_invoice_value;
  const lateValue = valuePerYear * (a.msme_share / 100) * (a.msme_late_share / 100);
  const interest = lateValue * (a.msme_interest_pct / 100) * (a.days_late / 365);
  const taxTiming = lateValue * (a.tax_rate_pct / 100) * (a.cost_of_funds_pct / 100);
  const discounts = valuePerYear * (a.discount_eligible_share / 100) * (a.discount_pct / 100) * (a.capture_gain / 100);
  const aiCost = yearInvoices * a.ai_cost_per_invoice;
  const net = costYear + dupYear + interest + taxTiming + discounts - aiCost;
  const maxCause = Math.max(1, ...m.root_causes.map((r) => r.count));
  const edited = Object.keys(edits).length > 0;

  return (
    <div className="page impact">
      <header className="page-head">
        <p className="label">Business value</p>
        <h1>Impact</h1>
        <p className="muted">
          Left: what Duly measured on its own data. Right: what that means for Plant X, with every input an editable
          assumption and every formula shown.
        </p>
      </header>

      <section className="panel impact-headline" aria-label="Headline">
        <div>
          <p className="label">Headline · projected for Plant X</p>
          <p className="impact-big num">{num(hours)} AP hours saved a month</p>
          <p className="muted">
            at a {num(a.touchless_rate)}% touchless rate on {num(a.invoices_per_month)} invoices a month · MSME paid on
            time: <strong>{pctText(m.msme_on_time_rate)}</strong> measured
          </p>
        </div>
        <div className="impact-net">
          <span className="kpi-label">Net value a year (estimate)</span>
          <span className="impact-net-value num">{inrShort(net)}</span>
        </div>
      </section>

      <div className="impact-grid">
        <section className="panel impact-measured" aria-labelledby="measured-title">
          <h2 id="measured-title" className="label">
            Measured on Duly's data
          </h2>
          <p className="muted small">
            {m.invoices} invoices ({inrShort(m.value)}) over {m.days} days, computed live. The data is synthetic: it
            proves the mechanism, not Plant X's real numbers.
          </p>
          <div className="kpis impact-kpis">
            <Tile icon={Zap} label="Touchless rate" value={pctText(m.touchless_rate)} sub={`${m.touchless} of ${m.approved} approved, zero human touches`} />
            <Tile icon={Gauge} label="First-pass match" value={pctText(m.first_pass_rate)} sub="APPROVE on the first check" />
            <Tile icon={Clock} label="Cycle time" value={days(m.avg_cycle_hours)} sub={`average · P90 ${days(m.p90_cycle_hours)}`} />
            <Tile icon={Copy} label="Duplicates caught" value={String(m.duplicates_caught)} sub={inr(m.duplicates_value)} />
            <Tile icon={Timer} label="MSME on time" value={pctText(m.msme_on_time_rate)} sub={`${m.msme_paid} paid · ${m.msme_open} open`} />
            <Tile icon={Sparkles} label="AI fields to review" value={pctText(m.ai_review_rate, 1)} sub={`corrected ${pctText(m.ai_corrected_rate, 2)} of ${num(m.ai_fields)} fields`} />
          </div>
          <h3 className="label impact-sub">Exceptions by root cause ({m.exceptions} invoices ever flagged or blocked)</h3>
          {m.root_causes.length === 0 ? <p className="muted small">No exceptions yet: every invoice so far matched first time.</p> : null}
          <ul className="causes">
            {m.root_causes.map((r) => (
              <li key={r.key}>
                <span className="cause-title" title={r.codes.map((c) => c.code).join(", ")}>
                  {r.title}
                </span>
                <span className="cause-bar" aria-hidden="true">
                  <span style={{ width: `${(r.count / maxCause) * 100}%` }} />
                </span>
                <span className="num cause-count">{r.count}</span>
                <span className="num muted cause-value">{inrShort(r.value)}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel impact-projected" aria-labelledby="projected-title">
          <h2 id="projected-title" className="label">
            Projected for Plant X (a year)
          </h2>
          <dl className="proj">
            <Projection label="AP hours saved a month" value={`${num(hours)} h`}
              formula={`${num(a.invoices_per_month)} × ${num(a.touchless_rate)}% × (${num(a.manual_minutes)} − ${num(a.duly_minutes)} min) / 60`} />
            <Projection label="AP cost saved" value={inrShort(costYear)}
              formula={`${num(hours)} h × 12 × ${inr(a.cost_per_hour)}`} />
            <Projection label="Duplicate leakage prevented" value={inrShort(dupYear)}
              formula={`${num(yearInvoices)} invoices × ${num(a.duplicate_rate)}% × ${inrShort(a.avg_invoice_value)}`} />
            <Projection label="MSME interest avoided" value={inrShort(interest)}
              formula={`${inrShort(lateValue)} paid late × ${num(a.msme_interest_pct)}% × ${num(a.days_late)} / 365`} />
            <Projection label="Tax-deduction timing effect avoided" value={inrShort(taxTiming)}
              formula={`${inrShort(lateValue)} × ${num(a.tax_rate_pct)}% tax × ${num(a.cost_of_funds_pct)}% cost of funds (deduction moves a year)`} />
            <Projection label="Early-payment discounts captured" value={inrShort(discounts)}
              formula={`${inrShort(valuePerYear)} × ${num(a.discount_eligible_share)}% × ${num(a.discount_pct)}% × ${num(a.capture_gain)}%`} />
            <Projection label="Less: AI extraction cost" value={`− ${inrShort(aiCost)}`} negative
              formula={`${num(yearInvoices)} invoices × ${inr(a.ai_cost_per_invoice)}`} />
          </dl>
          <p className="muted small impact-note">
            <Info size={13} aria-hidden="true" /> Not counted: exception handling time, late-payment disputes, audit
            effort, and fraud prevented by the bank and QR checks. All of these make the real figure higher.
          </p>
        </section>
      </div>

      <section className="panel" aria-labelledby="assumptions-title">
        <div className="assumptions-head">
          <h2 id="assumptions-title" className="label">
            <Calculator size={14} aria-hidden="true" /> Assumptions (edit to see the effect)
          </h2>
          <button type="button" className="btn btn-sm" disabled={!edited} onClick={() => setEdits({})}>
            <RotateCcw size={14} aria-hidden="true" /> Reset to defaults
          </button>
        </div>
        <div className="table-panel">
          <table className="table assumptions">
            <thead>
              <tr>
                <th scope="col">Assumption</th>
                <th scope="col" className="num-col">Value</th>
                <th scope="col">Unit</th>
                <th scope="col">Why this default</th>
              </tr>
            </thead>
            <tbody>
              {q.data.assumptions.map((x) => (
                <tr key={x.key}>
                  <td>
                    {x.label}
                    {x.measured ? <span className="chip chip-info impact-chip">measured</span> : null}
                    {edits[x.key] !== undefined ? <span className="chip chip-flag impact-chip">edited</span> : null}
                  </td>
                  <td className="num-col">
                    <input
                      className="input num assumption-input"
                      type="number"
                      step="any"
                      min={0}
                      aria-label={x.label}
                      value={a[x.key]}
                      onChange={(e) => {
                        const v = e.target.value === "" ? 0 : Number(e.target.value);
                        if (!Number.isNaN(v)) setEdits((prev) => ({ ...prev, [x.key]: v }));
                      }}
                    />
                  </td>
                  <td className="muted">{x.unit}</td>
                  <td className="muted small">{x.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small impact-note">
          <ShieldCheck size={13} aria-hidden="true" /> Assumptions are illustrative and conservative, not researched
          facts. Edits stay in this browser only. The same model is written up in docs/IMPACT.md.
        </p>
      </section>
    </div>
  );
}

function Projection({ label, value, formula, negative }: { label: string; value: string; formula: string; negative?: boolean }) {
  return (
    <div className="proj-row">
      <dt>{label}</dt>
      <dd className={`num proj-value${negative ? " proj-neg" : ""}`}>{value}</dd>
      <dd className="proj-formula mono">= {formula}</dd>
    </div>
  );
}
