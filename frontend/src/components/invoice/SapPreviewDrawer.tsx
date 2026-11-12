import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, Copy, Database, X } from "lucide-react";
import { api } from "../../api/client";
import { inr } from "../../lib/format";
import { SapTerm } from "../SapTerm";
import "./SapPreviewDrawer.css";

interface Posting {
  system: string;
  method: string;
  url: string;
  headers: Record<string, string>;
  payload: Record<string, unknown> & {
    to_SuplrInvcItemPurOrdRef: { results: Record<string, string>[] };
    to_SupplierInvoiceTax: { results: Record<string, string>[] };
    to_SupplierInvoiceWhldgTax: { results: Record<string, string>[] };
  };
  fiscal_year: string;
  payment_block: string | null;
  warnings: string[];
}

interface Preview {
  posting: Posting;
  reads: { method: string; url: string; note: string }[];
  ready: boolean;
  transaction: string;
  note: string;
}

/** Bottom drawer: the S/4HANA supplier-invoice request Duly would send for this invoice (D6). */
export function SapPreviewDrawer({ invoiceId, onClose }: { invoiceId: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["sap-preview", invoiceId], queryFn: () => api<Preview>(`/invoices/${invoiceId}/sap-preview`) });
  const [copied, setCopied] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const p = q.data?.posting;
  const body = p?.payload;
  const json = body ? JSON.stringify(body, null, 2) : "";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="sap-backdrop" onClick={onClose}>
      <section className="sap-drawer" role="dialog" aria-modal="true" aria-labelledby="sap-title" onClick={(e) => e.stopPropagation()}>
        <header className="sap-head">
          <div>
            <p className="label">
              <Database size={12} aria-hidden="true" /> SAP S/4HANA · <SapTerm term="MIRO">{q.data?.transaction ?? "MIRO"}</SapTerm>
            </p>
            <h2 id="sap-title">SAP posting preview</h2>
          </div>
          <button ref={closeRef} type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close SAP posting preview">
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        {q.isLoading ? <p className="muted">Building the request...</p> : null}
        {q.isError ? <p className="alert alert-error">Could not build the preview.</p> : null}
        {p && body && q.data ? (
          <div className="sap-body">
            <div className="sap-left">
              <p className={`sap-status ${q.data.ready ? "ok" : "blocked"}`}>
                {q.data.ready ? <CheckCircle2 size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}
                {q.data.ready
                  ? "Approved: ready to post without a payment block."
                  : <SapTerm term="R">Not approved: would be posted with payment block R</SapTerm>}
              </p>
              <p className="sap-req mono">
                <span className="sap-method">{p.method}</span> {p.url}
              </p>
              <p className="muted small">{p.system} · fiscal year {p.fiscal_year}</p>
              <dl className="sap-facts">
                <div><dt>Company code</dt><dd className="mono">{String(body.CompanyCode)}</dd></div>
                <div><dt>Invoicing party</dt><dd className="mono">{String(body.InvoicingParty)}</dd></div>
                <div><dt>Supplier invoice ID</dt><dd className="mono">{String(body.SupplierInvoiceIDByInvcgParty)}</dd></div>
                <div><dt>Gross amount</dt><dd className="num">{inr(String(body.InvoiceGrossAmount))}</dd></div>
                <div><dt>Payment terms</dt><dd className="mono">{String(body.PaymentTerms)}</dd></div>
                <div><dt>Payment block</dt><dd className="mono">{String(body.PaymentBlockingReason) || "none"}</dd></div>
                <div><dt>PO items</dt><dd>{body.to_SuplrInvcItemPurOrdRef.results.length}</dd></div>
                <div><dt>Tax lines</dt><dd>{body.to_SupplierInvoiceTax.results.map((t) => `${t.TaxCode} ${inr(t.TaxAmount)}`).join(", ") || "-"}</dd></div>
                <div><dt>Withholding tax</dt><dd>{body.to_SupplierInvoiceWhldgTax.results.map((t) => `${t.WithholdingTaxType}/${t.WithholdingTaxCode}`).join(", ") || "none"}</dd></div>
              </dl>
              {p.warnings.length ? (
                <ul className="sap-warn">
                  {p.warnings.map((w) => (
                    <li key={w}><AlertTriangle size={13} aria-hidden="true" /> {w}</li>
                  ))}
                </ul>
              ) : null}
              <h3 className="label">Reads before posting</h3>
              <ul className="sap-reads">
                {q.data.reads.map((r) => (
                  <li key={r.url}>
                    <span className="mono small"><span className="sap-method get">{r.method}</span> {r.url}</span>
                    <span className="muted small">{r.note}</span>
                  </li>
                ))}
              </ul>
              <p className="muted small">{q.data.note}</p>
            </div>
            <div className="sap-right">
              <div className="sap-json-head">
                <span className="label">Request body (OData V2, deep insert)</span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={copy}>
                  {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />} {copied ? "Copied" : "Copy JSON"}
                </button>
              </div>
              <pre className="sap-json mono" tabIndex={0} aria-label="Request body JSON">{json}</pre>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
