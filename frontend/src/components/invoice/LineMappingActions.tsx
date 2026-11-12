import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { ReasonOut } from "../../api/types";

/** A line Duly matched by description: the AP clerk confirms it or says it is not on the PO. */
export function LineMappingActions({ r, invoiceId }: { r: ReasonOut; invoiceId: number }) {
  const qc = useQueryClient();
  const ev = r.evidence as { po_line_id?: number; po_line_no?: number; po_item_code?: string; invoice_description?: string; po_description?: string };
  const act = useMutation({
    mutationFn: (confirm: boolean) =>
      api(`/invoices/${invoiceId}/lines/${r.line_no}/mapping`, {
        method: "POST",
        body: JSON.stringify(
          confirm
            ? { po_line_id: ev.po_line_id, reason: `Same item as PO line ${ev.po_line_no} (${ev.po_item_code}), checked by the clerk` }
            : { po_line_id: null, reason: "Not an item on this purchase order, checked by the clerk" },
        ),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["invoice", String(invoiceId)] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
  if (!ev.po_line_id || r.line_no === null) return null;
  return (
    <div className="mapping">
      <dl className="mapping-pair">
        <div><dt>Invoice line {r.line_no}</dt><dd>{ev.invoice_description}</dd></div>
        <div><dt>PO line {ev.po_line_no} ({ev.po_item_code})</dt><dd>{ev.po_description}</dd></div>
      </dl>
      <div className="mapping-actions">
        <button type="button" className="btn btn-sm" disabled={act.isPending} onClick={() => act.mutate(true)}>
          <Check size={14} aria-hidden="true" /> Same item: confirm
        </button>
        <button type="button" className="btn btn-sm btn-danger" disabled={act.isPending} onClick={() => act.mutate(false)}>
          <X size={14} aria-hidden="true" /> Not on the PO
        </button>
      </div>
      {act.isError ? (
        <p className="alert alert-error" role="alert">{act.error instanceof ApiError ? act.error.message : "Could not save."}</p>
      ) : null}
    </div>
  );
}
