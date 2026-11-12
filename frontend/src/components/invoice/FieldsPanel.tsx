import { AlertTriangle } from "lucide-react";
import type { ExtractedFieldOut } from "../../api/types";
import { inr, fmtDate } from "../../lib/format";
import { FIELD_LABEL, HEADER_ORDER, MONEY_FIELDS, MONO_FIELDS, parseFieldPath } from "./fields";

interface Props {
  fields: ExtractedFieldOut[];
  threshold: number;
  selected: string | null;
  onSelect: (field: string) => void;
}

const SOURCE_LABEL: Record<string, string> = {
  text: "PDF text",
  ocr: "OCR",
  ai: "AI",
  qr: "Signed QR",
  rule: "Rule",
  manual: "Corrected",
  none: "Not found",
};

function display(name: string, value: string | null): string {
  if (value === null) return "Not found";
  if (MONEY_FIELDS.has(name)) return inr(value);
  if (name === "invoice_date") return fmtDate(value);
  return value;
}

function FieldRow({ f, threshold, selected, onSelect }: { f: ExtractedFieldOut; threshold: number } & Omit<Props, "fields" | "threshold">) {
  const { name } = parseFieldPath(f.field);
  const pctConf = Math.round(f.confidence * 100);
  const low = f.needs_review;
  const missing = f.value === null;
  return (
    <li>
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
                  <span
                    className={`conf-fill${low ? " is-low" : ""}`}
                    style={{ width: `${Math.max(4, pctConf)}%` }}
                  />
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
    </li>
  );
}

/** Extracted fields with per-field confidence; click to highlight on the document. */
export function FieldsPanel({ fields, threshold, selected, onSelect }: Props) {
  const byPath = new Map(fields.map((f) => [f.field, f]));
  const header = HEADER_ORDER.map((k) => byPath.get(k)).filter((f): f is ExtractedFieldOut => !!f);
  const lineGroups = new Map<number, ExtractedFieldOut[]>();
  for (const f of fields) {
    const { line } = parseFieldPath(f.field);
    if (line !== null) lineGroups.set(line, [...(lineGroups.get(line) ?? []), f]);
  }
  const lowCount = fields.filter((f) => f.needs_review).length;

  return (
    <div className="fields">
      <p className="fields-note muted">
        {lowCount > 0
          ? `${lowCount} field${lowCount > 1 ? "s" : ""} below the ${Math.round(threshold * 100)}% confidence threshold need a human check.`
          : `All fields at or above the ${Math.round(threshold * 100)}% confidence threshold.`}
      </p>
      <ul className="field-list">
        {header.map((f) => (
          <FieldRow key={f.field} f={f} threshold={threshold} selected={selected} onSelect={onSelect} />
        ))}
      </ul>
      {[...lineGroups.entries()].map(([line, items]) => (
        <div key={line} className="field-group">
          <h3 className="field-group-title">Line {line + 1}</h3>
          <ul className="field-list">
            {items.map((f) => (
              <FieldRow key={f.field} f={f} threshold={threshold} selected={selected} onSelect={onSelect} />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
