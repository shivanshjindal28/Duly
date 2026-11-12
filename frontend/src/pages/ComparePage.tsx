import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Equal, EqualNot } from "lucide-react";
import { api } from "../api/client";
import type { Decision, InvoiceStatus } from "../api/types";
import { DecisionChip, StatusChip } from "../components/StatusChip";
import { fmtDateTime, inr } from "../lib/format";
import "./ComparePage.css";

interface DupMatch {
  probability: number;
  exact: boolean;
  signals: { name: string; score: number; detail: string }[];
  other: { id: number; invoice_number: string; status: InvoiceStatus; decision: Decision | null; received_at: string; pages: number };
  fields: { field: string; this: string | null; other: string | null; same: boolean; normalised_same: boolean | null }[];
}
interface DuplicatesOut {
  invoice_id: number;
  invoice_number: string;
  pages: number;
  matches: DupMatch[];
}

const LABEL: Record<string, string> = {
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  supplier_gstin: "Supplier GSTIN",
  po_number: "PO number",
  taxable_total: "Taxable value",
  total: "Invoice total",
  lines: "Items x qty",
  bank_account: "Bank account",
  irn: "IRN",
  file_sha256: "File fingerprint (SHA-256)",
};
const SIGNAL: Record<string, string> = {
  exact_number: "Same invoice number (normalised), same FY",
  same_irn: "Same e-invoice IRN",
  same_file: "Same file",
  near_match: "Same amount, date and items",
  visual: "Looks the same (perceptual hash)",
};

const money = (f: string, v: string | null) => (v && (f === "total" || f === "taxable_total") ? inr(v) : (v ?? "-"));

/** Side-by-side duplicate evidence: both documents and every compared field. */
export function ComparePage() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["duplicates", id], queryFn: () => api<DuplicatesOut>(`/invoices/${id}/duplicates`) });
  if (!q.data) return <div className="skeleton-row" style={{ height: 300 }} aria-busy="true" />;
  const m = q.data.matches[0];
  return (
    <div className="page compare-page">
      <header className="page-head">
        <Link to={`/invoices/${id}`} className="btn btn-ghost compare-back">
          <ArrowLeft size={16} aria-hidden="true" /> Back to invoice
        </Link>
        <p className="label">Duplicate check</p>
        <h1>Side-by-side comparison</h1>
      </header>
      {!m ? (
        <p className="empty">No earlier invoice resembles this one.</p>
      ) : (
        <>
          <section className={`panel compare-verdict ${m.exact ? "is-exact" : "is-possible"}`}>
            <h2>{m.exact ? "Duplicate" : `Possible duplicate (${Math.round(m.probability * 100)}% likely)`}</h2>
            <ul>
              {m.signals.map((s) => (
                <li key={s.name}>
                  <CheckCircle2 size={14} aria-hidden="true" /> <strong>{SIGNAL[s.name] ?? s.name}</strong>: {s.detail}
                </li>
              ))}
            </ul>
          </section>

          <div className="compare-docs">
            <figure className="panel">
              <figcaption>
                <span className="label">This invoice</span> <span className="mono">{q.data.invoice_number || `#${q.data.invoice_id}`}</span>
              </figcaption>
              <img src={`/api/invoices/${q.data.invoice_id}/pages/1.png`} alt="This invoice, page 1" />
            </figure>
            <figure className="panel">
              <figcaption>
                <span className="label">Earlier invoice</span>{" "}
                <Link to={`/invoices/${m.other.id}`} className="mono">
                  {m.other.invoice_number}
                </Link>{" "}
                <StatusChip status={m.other.status} /> <DecisionChip decision={m.other.decision} />
                <span className="muted"> · received {fmtDateTime(m.other.received_at)}</span>
              </figcaption>
              <img src={`/api/invoices/${m.other.id}/pages/1.png`} alt="Earlier invoice, page 1" />
            </figure>
          </div>

          <section className="panel table-panel">
            <table className="table compare-table">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">This invoice</th>
                  <th scope="col" aria-label="Same or different" />
                  <th scope="col">Earlier invoice</th>
                </tr>
              </thead>
              <tbody>
                {m.fields.map((f) => {
                  const match = f.same || f.normalised_same;
                  return (
                    <tr key={f.field} className={match ? "is-same" : ""}>
                      <th scope="row">{LABEL[f.field] ?? f.field}</th>
                      <td className="mono">{money(f.field, f.this)}</td>
                      <td className="compare-eq">
                        {f.same ? (
                          <span className="chip chip-block"><Equal size={12} aria-hidden="true" /> Same</span>
                        ) : f.normalised_same ? (
                          <span className="chip chip-block"><Equal size={12} aria-hidden="true" /> Same once normalised</span>
                        ) : (
                          <span className="chip chip-neutral"><EqualNot size={12} aria-hidden="true" /> Differs</span>
                        )}
                      </td>
                      <td className="mono">{money(f.field, f.other)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
