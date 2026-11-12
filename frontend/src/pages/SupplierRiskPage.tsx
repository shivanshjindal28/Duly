import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { AlertTriangle, CheckCircle2, Leaf, ShieldAlert } from "lucide-react";
import { api } from "../api/client";
import { PageSkeleton } from "../components/PageSkeleton";
import { fmtDate, inrShort } from "../lib/format";
import "./AboutPages.css";
import "./SupplierRiskPage.css";

type Level = "high" | "watch" | "low";
interface Metric { basis: string }
interface RiskCard {
  supplier_id: number;
  code: string;
  name: string;
  category: string;
  msme: { category: string; udyam_no: string | null; is_msme: boolean; enterprise_type: string; terms_days: number; written_agreement: boolean };
  level: Level;
  reasons: { level: "high" | "watch"; text: string }[];
  invoices_12m: number;
  spend_paid_12m: string;
  on_time: Metric & { paid: number; on_time: number; rate: number | null; avg_days_late: number | null };
  disputes: Metric & { count: number; of: number; rate: number | null };
  duplicates: Metric & { blocked: number; possible: number; value_blocked: string };
  bank_changes: Metric & { approved_12m: number; in_progress: number; last_changed: string | null; mismatch_alerts: number };
  einvoice: Metric & { applicable: boolean; verified: number; failed: number; rate: number | null };
  sustainability: { scheme: string; status: string; label: string; last_assessed: string | null; score: number | null; note: string };
}
interface RiskOut {
  as_of: string;
  cards: RiskCard[];
  methodology: {
    window_days: number;
    recent_bank_change_days: number;
    thresholds: { dispute_rate_watch: number; min_invoices: number; duplicate_attempts_watch: number; einvoice_compliance_watch: number };
    levels: Record<Level, string>;
    note: string;
  };
}

const LEVEL: Record<Level, { label: string; chip: string; Icon: typeof ShieldAlert }> = {
  high: { label: "High risk", chip: "chip-block", Icon: ShieldAlert },
  watch: { label: "Watch", chip: "chip-flag", Icon: AlertTriangle },
  low: { label: "Low risk", chip: "chip-approve", Icon: CheckCircle2 },
};
const SUSTAIN_CHIP: Record<string, string> = {
  current: "chip-approve", due: "chip-flag", overdue: "chip-block", not_started: "chip-flag", not_required: "chip-neutral",
};
const pctOf = (r: number | null) => (r === null ? "-" : `${Math.round(r * 100)}%`);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function Card({ c }: { c: RiskCard }) {
  const lv = LEVEL[c.level];
  const msme = c.msme.is_msme
    ? `${cap(c.msme.category)} enterprise · ${c.msme.udyam_no ?? "Udyam no. missing"}`
    : "Not MSME";
  return (
    <article className="panel risk-card" aria-labelledby={`risk-${c.supplier_id}`}>
      <header className="risk-head">
        <div>
          <h2 id={`risk-${c.supplier_id}`} className="risk-name">{c.name}</h2>
          <p className="muted small">
            <span className="mono">{c.code}</span> · {c.category} · {c.invoices_12m} invoices, {inrShort(c.spend_paid_12m)} paid in 12 months
          </p>
        </div>
        <span className={`chip chip-lg ${lv.chip}`}>
          <lv.Icon size={14} aria-hidden="true" /> {lv.label}
        </span>
      </header>

      {c.reasons.length > 0 ? (
        <ul className="risk-reasons" aria-label="Why">
          {c.reasons.map((r) => (
            <li key={r.text} className={r.level === "high" ? "sev-block" : "sev-flag"}>{r.text}</li>
          ))}
        </ul>
      ) : (
        <p className="risk-clear small">No watch points in the last 12 months.</p>
      )}

      <dl className="control-evidence risk-metrics">
        <div>
          <dt>MSME status</dt>
          <dd className="evidence-text">{msme}</dd>
        </div>
        <div>
          <dt>Paid on time by Plant X</dt>
          <dd>
            {pctOf(c.on_time.rate)} <span className="muted small">{c.on_time.on_time} of {c.on_time.paid}</span>
            {c.on_time.avg_days_late !== null && <span className="sev-flag small"> · avg {c.on_time.avg_days_late} d late</span>}
          </dd>
        </div>
        <div>
          <dt>Dispute rate</dt>
          <dd>
            {pctOf(c.disputes.rate)} <span className="muted small">{c.disputes.count} of {c.disputes.of}</span>
          </dd>
        </div>
        <div>
          <dt>Duplicate attempts</dt>
          <dd>
            {c.duplicates.blocked} blocked
            {c.duplicates.possible > 0 && <span className="muted small"> · {c.duplicates.possible} possible</span>}
            {c.duplicates.blocked > 0 && <span className="muted small"> · {inrShort(c.duplicates.value_blocked)}</span>}
          </dd>
        </div>
        <div>
          <dt>Bank changes (12 months)</dt>
          <dd>
            {c.bank_changes.approved_12m}
            {c.bank_changes.last_changed && <span className="muted small"> · last {fmtDate(c.bank_changes.last_changed)}</span>}
            {c.bank_changes.in_progress > 0 && <span className="sev-flag small"> · {c.bank_changes.in_progress} in progress</span>}
            {c.bank_changes.mismatch_alerts > 0 && <span className="sev-block small"> · {c.bank_changes.mismatch_alerts} mismatch alert(s)</span>}
          </dd>
        </div>
        <div>
          <dt>e-invoice compliance</dt>
          <dd>
            {c.einvoice.applicable ? (
              <>
                {pctOf(c.einvoice.rate)} <span className="muted small">{c.einvoice.verified} verified, {c.einvoice.failed} failed</span>
              </>
            ) : (
              <span className="evidence-text">Not applicable</span>
            )}
          </dd>
        </div>
      </dl>

      <div className="risk-sustain">
        <Leaf size={15} aria-hidden="true" className="risk-leaf" />
        <div>
          <p className="small">
            <strong>{c.sustainability.scheme}</strong> (fictional):{" "}
            <span className={`chip ${SUSTAIN_CHIP[c.sustainability.status] ?? "chip-neutral"}`}>{c.sustainability.label}</span>
            {c.sustainability.score !== null && (
              <span className="muted"> · score {c.sustainability.score}/100, assessed {fmtDate(c.sustainability.last_assessed)}</span>
            )}
          </p>
          {c.sustainability.note && <p className="muted small">{c.sustainability.note}</p>}
        </div>
      </div>

      <footer className="risk-links small">
        <Link to={`/queue?status=open&supplier_id=${c.supplier_id}`}>Open exceptions</Link>
        <Link to={`/queue?status=all&supplier_id=${c.supplier_id}`}>All invoices</Link>
      </footer>
    </article>
  );
}

/** Supplier risk cards (spec D8): live figures per supplier, information only. */
export function SupplierRiskPage() {
  const q = useQuery({ queryKey: ["supplier-risk"], queryFn: () => api<RiskOut>("/suppliers/risk") });
  if (q.isLoading) return <PageSkeleton blocks={4} label="Loading supplier risk cards" />;
  if (!q.data) return <div className="page alert alert-error">Could not load the supplier risk cards.</div>;
  const { cards, methodology: m } = q.data;
  const t = m.thresholds;

  return (
    <div className="page about">
      <header className="page-head">
        <p className="label">Procurement view</p>
        <h1>Supplier risk</h1>
        <p className="muted">
          One card per supplier, computed live for the last {m.window_days} days (as of {fmtDate(q.data.as_of)}). {m.note}
        </p>
      </header>

      <div className="risk-grid">
        {cards.map((c) => <Card key={c.supplier_id} c={c} />)}
      </div>

      <section className="panel about-doc md" aria-labelledby="risk-method">
        <h2 id="risk-method">How the cards are computed</h2>
        <ul>
          <li><strong>High risk:</strong> {m.levels.high}</li>
          <li>
            <strong>Watch:</strong> bank change approved in the last {m.recent_bank_change_days} days or still in progress;
            {" "}{t.duplicate_attempts_watch}+ duplicates blocked; dispute rate {Math.round(t.dispute_rate_watch * 100)}%+
            (judged from {t.min_invoices} invoices); e-invoice compliance below {Math.round(t.einvoice_compliance_watch * 100)}%.
          </li>
          <li><strong>Low risk:</strong> {m.levels.low}</li>
          {cards[0] && (
            <>
              <li><strong>Paid on time:</strong> {cards[0].on_time.basis}</li>
              <li><strong>Dispute rate:</strong> {cards[0].disputes.basis}</li>
              <li><strong>Duplicate attempts:</strong> {cards[0].duplicates.basis}</li>
              <li><strong>Bank changes:</strong> {cards[0].bank_changes.basis}</li>
              <li><strong>e-invoice compliance:</strong> invoices with a verified signed QR out of those checked; only for suppliers above the e-invoicing threshold.</li>
            </>
          )}
          <li><strong>Sustainability:</strong> the assessment records are fictional, to show where a sustainable-sourcing status would sit next to AP data.</li>
        </ul>
      </section>
    </div>
  );
}
