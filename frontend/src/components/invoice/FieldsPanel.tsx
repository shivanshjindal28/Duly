import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, History, Pencil, X } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { ExtractedFieldOut, InvoiceDetail } from "../../api/types";
import { fmtDate, fmtDateTime, inr } from "../../lib/format";
import { FIELD_LABEL, HEADER_ORDER, MONEY_FIELDS, MONO_FIELDS, parseFieldPath } from "./fields";

interface Props {
  invoiceId: number;
  fields: ExtractedFieldOut[];
  threshold: number;
  canReview: boolean;
  selected: string | null;
  onSelect: (field: string) => void;
}

const SOURCE_LABEL: Record<string, string> = {
  text: "PDF text",
  ocr: "OCR",
  ai: "AI",
  qr: "Signed QR",
  rule: "Rule",
  manual: "Human reviewed",
  none: "Not found",
};

function display(name: string, value: string | null): string {
  if (value === null) return "Not found";
  if (MONEY_FIELDS.has(name)) return inr(value);
  if (name === "invoice_date") return fmtDate(value);
  return value;
}

function useReview(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { field: string; value?: string; reason: string }) =>
      api<InvoiceDetail>(`/invoices/${invoiceId}/review`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (inv) => {
      qc.setQueryData(["invoice", String(invoiceId)], inv);
      qc.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
}

function Editor({ f, invoiceId, onDone }: { f: ExtractedFieldOut; invoiceId: number; onDone: () => void }) {
  const { name } = parseFieldPath(f.field);
  const [value, setValue] = useState(name === "bank_account" ? "" : (f.value ?? ""));
  const [reason, setReason] = useState("");
  const review = useReview(invoiceId);

  function submit(e: FormEvent) {
    e.preventDefault();
    review.mutate({ field: f.field, value: value.trim(), reason: reason.trim() }, { onSuccess: onDone });
  }

  return (
    <form className="field-editor" onSubmit={submit}>
      <label className="field">
        <span>Correct value{name === "invoice_date" ? " (YYYY-MM-DD)" : ""}</span>
        <input className="input" value={value} onChange={(e) => setValue(e.target.value)} autoFocus required />
      </label>
      <label className="field">
        <span>Reason (logged in the audit trail)</span>
        <input
          className="input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Misread digit, checked against the paper copy"
          required
          minLength={3}
        />
      </label>
      {review.isError ? (
        <p className="field-error" role="alert">
          {review.error instanceof ApiError ? review.error.message : "Could not save."}
        </p>
      ) : null}
      <div className="field-editor-actions">
        <button type="submit" className="btn btn-primary" disabled={review.isPending || reason.trim().length < 3}>
          <Check size={14} aria-hidden="true" /> Save correction
        </button>
        <button type="button" className="btn btn-ghost" onClick={onDone}>
          <X size={14} aria-hidden="true" /> Cancel
        </button>
      </div>
    </form>
  );
}

function FieldRow({ f, threshold, invoiceId, canReview, selected, onSelect }: { f: ExtractedFieldOut } & Omit<Props, "fields">) {
  const { name } = parseFieldPath(f.field);
  const [editing, setEditing] = useState(false);
  const confirm = useReview(invoiceId);
  const pctConf = Math.round(f.confidence * 100);
  const low = f.needs_review;
  const missing = f.value === null;
  const reviewed = f.source === "manual";
  return (
    <li className="field-item">
      <button
        type="button"
        className={`field-row${selected === f.field ? " is-selected" : ""}${low ? " is-low" : ""}`}
        onClick={() => onSelect(f.field)}
        disabled={!f.bbox}
        aria-pressed={selected === f.field}
      >
        <span className="field-name">{FIELD_LABEL[name] ?? name}</span>
        <span className={`field-value${MONO_FIELDS.has(name) || MONEY_FIELDS.has(name) ? " mono" : ""}${missing ? " muted" : ""}`}>
          {display(name, f.value)}
        </span>
        <span className="field-meta">
          {missing ? null : (
            <>
              <span className="conf" aria-label={`Confidence ${pctConf} percent`}>
                <span className="conf-bar">
                  <span className={`conf-fill${low ? " is-low" : ""}`} style={{ width: `${Math.max(4, pctConf)}%` }} />
                  <span className="conf-threshold" style={{ left: `${threshold * 100}%` }} />
                </span>
                <span className="conf-num num">{pctConf}%</span>
              </span>
              <span className="field-source">{SOURCE_LABEL[f.source] ?? f.source}</span>
              {low ? (
                <span className="chip chip-flag field-review">
                  <AlertTriangle size={11} aria-hidden="true" /> Review
                </span>
              ) : null}
            </>
          )}
        </span>
      </button>
      {reviewed ? (
        <p className="field-history">
          <History size={11} aria-hidden="true" />
          {f.previous_value === f.value ? "Confirmed" : `Was ${display(name, f.previous_value)}`}
          {f.previous_confidence !== null ? ` (read at ${Math.round((f.previous_confidence ?? 0) * 100)}%)` : ""} by{" "}
          {f.reviewed_by}, {fmtDateTime(f.reviewed_at)}: "{f.review_reason}"
        </p>
      ) : null}
      {canReview && !editing ? (
        <div className="field-actions">
          {low ? (
            <button
              type="button"
              className="btn btn-sm"
              disabled={confirm.isPending}
              onClick={() => confirm.mutate({ field: f.field, reason: "Confirmed against the document" })}
            >
              <Check size={13} aria-hidden="true" /> Confirm
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => setEditing(true)}
            aria-label={`Correct ${FIELD_LABEL[name] ?? name}`}
          >
            <Pencil size={13} aria-hidden="true" /> {low || missing ? "Correct" : "Edit"}
          </button>
        </div>
      ) : null}
      {editing ? <Editor f={f} invoiceId={invoiceId} onDone={() => setEditing(false)} /> : null}
    </li>
  );
}

/** Extracted fields with per-field confidence; click to highlight. Clerks confirm or correct (logged). */
export function FieldsPanel({ invoiceId, fields, threshold, canReview, selected, onSelect }: Props) {
  const byPath = new Map(fields.map((f) => [f.field, f]));
  const header = HEADER_ORDER.map((k) => byPath.get(k)).filter((f): f is ExtractedFieldOut => !!f);
  const lineGroups = new Map<number, ExtractedFieldOut[]>();
  for (const f of fields) {
    const { line } = parseFieldPath(f.field);
    if (line !== null) lineGroups.set(line, [...(lineGroups.get(line) ?? []), f]);
  }
  const lowCount = fields.filter((f) => f.needs_review).length;
  const rowProps = { invoiceId, threshold, canReview, selected, onSelect };

  return (
    <div className="fields">
      <p className="fields-note muted">
        {lowCount > 0
          ? `${lowCount} field${lowCount > 1 ? "s" : ""} below the ${Math.round(threshold * 100)}% confidence threshold need a human check.`
          : `All fields at or above the ${Math.round(threshold * 100)}% confidence threshold.`}
      </p>
      <ul className="field-list">
        {header.map((f) => (
          <FieldRow key={f.field} f={f} {...rowProps} />
        ))}
      </ul>
      {[...lineGroups.entries()].map(([line, items]) => (
        <div key={line} className="field-group">
          <h3 className="field-group-title">Line {line + 1}</h3>
          <ul className="field-list">
            {items.map((f) => (
              <FieldRow key={f.field} f={f} {...rowProps} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
