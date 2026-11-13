import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { api } from "../api/client";
import type { InvoiceSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DecisionChip, StatusChip } from "../components/StatusChip";
import { fmtDate, fmtDateTime, inrApprox, money } from "../lib/format";

/** Invoice list. Suppliers see only their own invoices (enforced by the API). */
export function InvoicesPage() {
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["invoices"], queryFn: () => api<InvoiceSummary[]>("/invoices") });
  const canUpload = me?.role === "supplier" || me?.role === "clerk";

  return (
    <div className="page">
      <header className="page-head page-head-row">
        <div>
          <p className="label">{me?.role === "supplier" ? "Your invoices" : "All suppliers"}</p>
          <h1>Invoices</h1>
        </div>
        {canUpload ? (
          <Link to="/upload" className="btn btn-primary">
            <Upload size={16} aria-hidden="true" /> Upload invoice
          </Link>
        ) : null}
      </header>

      <section className="panel table-panel">
        {q.isLoading ? (
          <div className="skeleton-rows" aria-busy="true" aria-label="Loading invoices">
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="skeleton-row" />
            ))}
          </div>
        ) : q.isError ? (
          <p className="empty">Could not load invoices: {(q.error as Error).message}</p>
        ) : q.data && q.data.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Invoice</th>
                {me?.role !== "supplier" ? <th scope="col">Supplier</th> : null}
                <th scope="col">PO</th>
                <th scope="col">Invoice date</th>
                <th scope="col" className="num-col">
                  Total
                </th>
                <th scope="col">Decision</th>
                <th scope="col">Status</th>
                <th scope="col">With</th>
                <th scope="col">Received</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((inv) => (
                <tr key={inv.id}>
                  <td>
                    <Link to={`/invoices/${inv.id}`} className="mono row-link">
                      {inv.invoice_number || `#${inv.id}`}
                    </Link>
                  </td>
                  {me?.role !== "supplier" ? <td>{inv.supplier_name}</td> : null}
                  <td className="mono">{inv.po_number ?? "-"}</td>
                  <td>{fmtDate(inv.invoice_date)}</td>
                  <td className="num num-col">{money(inv.total, inv.currency)}{inv.currency !== "INR" ? <div className="muted small">{inrApprox(inv.total_inr, inv.currency)}</div> : null}</td>
                  <td>
                    <DecisionChip decision={inv.decision} />
                  </td>
                  <td>
                    <StatusChip status={inv.status} />
                  </td>
                  <td className="muted">{inv.current_owner}</td>
                  <td className="muted">{fmtDateTime(inv.received_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">
            <p>No invoices yet.</p>
            {canUpload ? (
              <Link to="/upload" className="btn">
                <Upload size={16} aria-hidden="true" /> Upload the first one
              </Link>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
