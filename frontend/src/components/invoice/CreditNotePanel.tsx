import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileMinus2 } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { CreditSuggestion, InvoiceDetail } from "../../api/types";
import { fmtDate, inr, qty as fmtQty } from "../../lib/format";

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function defaultReason(s: CreditSuggestion[]): string {
  return s
    .map((x) => (x.mode === "qty" ? `${fmtQty(x.qty)} ${x.uom} ${x.item} not received` : `${x.item} billed above accepted services`))
    .join("; ");
}

/** Credit notes on this invoice, and (supplier or AP clerk, blocked / flagged) a form prefilled with the exact credit
 *  that clears the quantity or value exception. The server prices it from the invoice line and re-runs the match. */
export function CreditNotePanel({ inv }: { inv: InvoiceDetail }) {
  const qc = useQueryClient();
  const s = inv.credit_suggestion;
  const [open, setOpen] = useState(false);
  const [number, setNumber] = useState("");
  const [date, setDate] = useState(today());
  const [reason, setReason] = useState(defaultReason(s));
  const [amounts, setAmounts] = useState<Record<number, string>>(() =>
    Object.fromEntries(s.map((x) => [x.line_no, x.mode === "qty" ? String(Number(x.qty)) : String(Number(x.value))])),
  );
  const save = useMutation({
    mutationFn: () =>
      api<InvoiceDetail>(`/invoices/${inv.id}/credit-notes`, {
        method: "POST",
        body: JSON.stringify({
          number,
          note_date: date,
          reason,
          lines: s.map((x) => ({
            line_no: x.line_no,
            qty: x.mode === "qty" ? amounts[x.line_no] : null,
            value: x.mode === "value" ? amounts[x.line_no] : null,
          })),
        }),
      }),
    onSuccess: (d) => {
      qc.setQueryData(["invoice", String(inv.id)], d);
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["portal"] });
      setOpen(false);
      setNumber("");
    },
  });
  // Arriving from the supplier portal's "Enter credit note" button: open the form and bring it into view.
  const wantsForm = inv.can_issue_credit && s.length > 0 && window.location.hash === "#credit-note";
  useEffect(() => {
    if (wantsForm) {
      setOpen(true);
      document.getElementById("credit-note")?.scrollIntoView({ block: "center" });
    }
  }, [wantsForm]);
  const err = save.error instanceof ApiError ? save.error.message : save.error ? "Could not save the credit note." : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  if (!inv.credit_notes.length && !(inv.can_issue_credit && s.length)) return null;
  return (
    <div className="credit-notes" id="credit-note">
      <div className="pane-head pane-head-sub">
        <h2 className="label">Credit notes</h2>
      </div>
      {inv.credit_notes.length ? (
        <>
          <ul className="cn-list">
            {inv.credit_notes.map((n) => (
              <li key={n.number}>
                <span className="mono">{n.number}</span> · {fmtDate(n.note_date)} · <strong>{inr(n.total)}</strong>
                <span className="muted small">
                  {" "}
                  {n.reason}
                  {n.entered_by ? ` (entered by ${n.entered_by})` : ""}
                </span>
              </li>
            ))}
          </ul>
          <p className="small">
            Net payable <strong>{inr(inv.net_total)}</strong> <span className="muted">(invoice {inr(inv.total)})</span>
          </p>
        </>
      ) : null}

      {inv.can_issue_credit && s.length ? (
        open ? (
          <form className="cn-form" onSubmit={submit} aria-label="Credit note">
            <p className="small">
              A credit note for{" "}
              <strong>{inr(s.reduce((a, x) => a + Number(x.total), 0))}</strong> (incl. GST, priced from this invoice)
              clears the quantity / value exception in the decision above. Duly re-checks the invoice as soon as you
              save it.
            </p>
            <div className="cn-row">
              <label className="field">
                <span>Credit note number</span>
                <input className="input mono" maxLength={16} required value={number} onChange={(e) => setNumber(e.target.value)} />
              </label>
              <label className="field">
                <span>Date</span>
                <input className="input" type="date" required value={date} onChange={(e) => setDate(e.target.value)} />
              </label>
            </div>
            {s.map((x) => (
              <label className="field" key={x.line_no}>
                <span>
                  Line {x.line_no} ({x.item}): {x.mode === "qty" ? `quantity to credit (${x.uom})` : "taxable value to credit (₹)"}
                </span>
                <input
                  className="input num"
                  inputMode="decimal"
                  required
                  value={amounts[x.line_no] ?? ""}
                  onChange={(e) => setAmounts({ ...amounts, [x.line_no]: e.target.value })}
                />
              </label>
            ))}
            <label className="field">
              <span>Reason</span>
              <input className="input" required minLength={3} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            {err ? (
              <p className="alert alert-error" role="alert">
                {err}
              </p>
            ) : null}
            <div className="cn-actions">
              <button type="submit" className="btn btn-primary btn-sm" disabled={save.isPending || !number}>
                {save.isPending ? "Saving…" : "Save credit note"}
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>
            <FileMinus2 size={14} aria-hidden="true" /> Enter credit note for {inr(s.reduce((a, x) => a + Number(x.total), 0))}
          </button>
        )
      ) : null}
    </div>
  );
}
