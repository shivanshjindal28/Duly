import { useState } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Cpu, Eye, FileText } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { InvoiceDetail } from "../api/types";
import { DulyRail } from "../components/DulyRail";
import { DecisionPanel } from "../components/invoice/DecisionPanel";
import { DocumentViewer } from "../components/invoice/DocumentViewer";
import { FieldsPanel } from "../components/invoice/FieldsPanel";
import { MatchMatrix } from "../components/invoice/MatchMatrix";
import { StatusChip } from "../components/StatusChip";
import { fmtDate, inr } from "../lib/format";
import "./InvoiceDetailPage.css";

const AI_MODE: Record<string, string> = { live: "AI: live", cached: "AI: cached", offline: "AI: offline (OCR)" };

/** The hero screen: document | extracted fields | decision, with the match matrix below. */
export function InvoiceDetailPage() {
  const { id } = useParams();
  const [selected, setSelected] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["invoice", id], queryFn: () => api<InvoiceDetail>(`/invoices/${id}`) });

  if (q.isLoading) {
    return (
      <div className="detail-skeleton" aria-busy="true" aria-label="Loading invoice">
        <div className="skeleton-row" style={{ height: 56 }} />
        <div className="detail-skeleton-grid">
          <div className="skeleton-row" style={{ height: 520 }} />
          <div className="skeleton-row" style={{ height: 520 }} />
          <div className="skeleton-row" style={{ height: 520 }} />
        </div>
      </div>
    );
  }
  if (q.isError) {
    const msg = q.error instanceof ApiError && q.error.status === 404 ? "Invoice not found." : (q.error as Error).message;
    return (
      <div className="page">
        <p className="empty">{msg}</p>
        <Link to="/invoices">Back to invoices</Link>
      </div>
    );
  }
  const inv = q.data!;
  const isService = !!inv.match?.matrix.length && inv.match.matrix.every((r) => r.po_line_id === null || r.qty_variance === null);
  const selectLine = (line: number) => setSelected(`lines[${line - 1}].taxable_value`);

  return (
    <div className="detail">
      <header className="detail-head panel">
        <div className="detail-title">
          <Link to="/invoices" className="btn btn-ghost detail-back" aria-label="Back to invoices">
            <ArrowLeft size={16} aria-hidden="true" />
          </Link>
          <div>
            <p className="label">{inv.supplier_name}</p>
            <h1 className="mono">{inv.invoice_number || `Invoice #${inv.id}`}</h1>
          </div>
        </div>
        <dl className="detail-facts">
          <div>
            <dt>Total</dt>
            <dd className="num detail-total">{inr(inv.total)}</dd>
          </div>
          <div>
            <dt>Invoice date</dt>
            <dd>{fmtDate(inv.invoice_date)}</dd>
          </div>
          <div>
            <dt>PO</dt>
            <dd className="mono" title="SAP: ME23N display purchase order">
              {inv.po_number ?? "-"}
            </dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <StatusChip status={inv.status} />
            </dd>
          </div>
          <div>
            <dt>With</dt>
            <dd>{inv.current_owner}</dd>
          </div>
        </dl>
        <div className="detail-rail">
          <DulyRail completed={inv.rail} showDocs />
        </div>
      </header>

      {inv.pending_review.length > 0 ? (
        <div className="review-banner" role="status">
          <p>
            <Eye size={16} aria-hidden="true" />
            <span>
              <strong>Human review:</strong> {inv.pending_review.length} field
              {inv.pending_review.length > 1 ? "s need" : " needs"} confirmation before the decision takes effect
              {inv.can_review ? "." : " (an AP clerk will check them)."}
            </span>
          </p>
          <button type="button" className="btn btn-sm" onClick={() => setSelected(inv.pending_review[0])}>
            Show next field
          </button>
        </div>
      ) : null}

      <div className="detail-grid">
        <section className="panel detail-pane" aria-labelledby="doc-title">
          <div className="pane-head">
            <h2 id="doc-title" className="label">
              Document
            </h2>
            {inv.document ? (
              <a className="pane-link" href={`/api/invoices/${inv.id}/document`} target="_blank" rel="noreferrer">
                <FileText size={13} aria-hidden="true" /> Original
              </a>
            ) : null}
          </div>
          {inv.document ? (
            <DocumentViewer
              invoiceId={inv.id}
              pages={inv.document.pages}
              fields={inv.fields}
              selected={selected}
              onSelect={setSelected}
            />
          ) : (
            <p className="muted">No document.</p>
          )}
          {inv.document ? (
            <p className="doc-hash mono" title="SHA-256 fingerprint of the stored file">
              sha256 {inv.document.sha256.slice(0, 16)}…
            </p>
          ) : null}
        </section>

        <section className="panel detail-pane" aria-labelledby="fields-title">
          <div className="pane-head">
            <h2 id="fields-title" className="label">
              Extracted fields
            </h2>
            <span className="chip chip-neutral">
              <Cpu size={12} aria-hidden="true" /> {AI_MODE[inv.ai_mode ?? "offline"] ?? inv.ai_mode}
            </span>
          </div>
          <FieldsPanel
            invoiceId={inv.id}
            canReview={inv.can_review}
            fields={inv.fields}
            threshold={inv.confidence_threshold}
            selected={selected}
            onSelect={setSelected}
          />
        </section>

        <section className="panel detail-pane" aria-labelledby="decision-title">
          <div className="pane-head">
            <h2 id="decision-title" className="label">
              Decision
            </h2>
          </div>
          <DecisionPanel match={inv.match} onLine={selectLine} />
        </section>
      </div>

      <section className="panel detail-matrix" aria-labelledby="matrix-title">
        <div className="pane-head">
          <h2 id="matrix-title" className="label">
            Three-way match
          </h2>
          <span className="muted pane-hint">PO (ME23N) · {isService ? "Service entry (ML81N)" : "Goods receipt (MIGO)"} · Invoice (MIRO)</span>
        </div>
        <MatchMatrix match={inv.match} isService={isService} />
      </section>
    </div>
  );
}
