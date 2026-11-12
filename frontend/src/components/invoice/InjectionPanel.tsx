import { ShieldAlert } from "lucide-react";
import type { InvoiceDetail } from "../../api/types";
import { inr } from "../../lib/format";

const KEY_FIELDS: [string, string][] = [
  ["invoice_number", "Invoice number"],
  ["total", "Invoice total"],
  ["bank_account", "Bank account"],
  ["po_number", "PO number"],
];

/** D2: what was hidden in the document, and the AI's quarantined reading next to the values used. */
export function InjectionPanel({ inv }: { inv: InvoiceDetail }) {
  const scan = inv.injection;
  if (!scan?.found) return null;
  const q = scan.ai_quarantined;
  const used: Record<string, string | null> = {
    invoice_number: inv.invoice_number,
    total: inv.total,
    bank_account: inv.bank_account_masked,
    po_number: inv.po_number,
  };
  return (
    <section className="panel inj" aria-labelledby="inj-title">
      <h2 id="inj-title" className="inj-title">
        <ShieldAlert size={18} aria-hidden="true" /> Prompt-injection attempt detected
      </h2>
      <p className="inj-lede">
        This document contains instructions aimed at an AI or at the approval process. Hidden text is removed before
        extraction, {q ? "the AI's reading of this document was quarantined, " : ""}and the decision is made by the
        rules engine, so the text cannot approve or redirect payment.
      </p>
      <ul className="inj-findings">
        {scan.findings
          .filter((f) => f.patterns.length)
          .map((f, i) => (
            <li key={i}>
              <span className="chip chip-block">{f.where}{f.page ? ` · page ${f.page}` : ""}</span>
              <blockquote className="mono">{f.text}</blockquote>
              <span className="inj-tags">Tries to: {f.patterns.join(", ")}</span>
            </li>
          ))}
      </ul>
      {q ? (
        <table className="table inj-table">
          <caption>AI output (quarantined, not used) vs values Duly used</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">AI said</th>
              <th scope="col">Used (deterministic parser + rules)</th>
            </tr>
          </thead>
          <tbody>
            {KEY_FIELDS.map(([k, label]) => {
              const ai = q.header?.[k]?.value ?? null;
              const usedValue = used[k];
              return (
                <tr key={k}>
                  <th scope="row">{label}</th>
                  <td className="mono">{k === "total" && ai ? inr(ai) : (ai ?? "-")}</td>
                  <td className="mono">{k === "total" && usedValue ? inr(usedValue) : (usedValue ?? "-")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="inj-note">The AI was not used for this document (offline mode), so there was nothing to quarantine.</p>
      )}
    </section>
  );
}
