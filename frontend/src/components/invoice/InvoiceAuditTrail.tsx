import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { fmtDateTime } from "../../lib/format";
import { summarise, type AuditEvent } from "../../pages/AuditPage";

/** Who did what to this invoice, from the hash-chained audit trail (staff only). */
export function InvoiceAuditTrail({ invoiceId }: { invoiceId: number }) {
  const q = useQuery({
    queryKey: ["audit-events", "invoice", invoiceId],
    queryFn: () => api<AuditEvent[]>(`/audit/events?entity_type=invoice&entity_id=${invoiceId}&limit=100`),
  });
  if (!q.data?.length) return <p className="muted">No events yet.</p>;
  return (
    <ul className="audit-trail">
      {[...q.data].reverse().map((e) => (
        <li key={e.id}>
          <span className="muted">{fmtDateTime(e.ts)}</span>
          <span>
            <span className="mono">{e.action}</span>
            <br />
            <span className="muted">{e.actor ?? "system"}</span>
          </span>
          <span>{summarise(e)}</span>
        </li>
      ))}
    </ul>
  );
}
