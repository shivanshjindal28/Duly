import type { MatchOut, Severity } from "../../api/types";
import { inr, pct, qty } from "../../lib/format";
import { SeverityIcon } from "../StatusChip";

/** PO | GR | Invoice | Variance per line. Variance cells carry the severity of the matching reason. */
export function MatchMatrix({ match, isService }: { match: MatchOut | null; isService: boolean }) {
  if (!match || match.matrix.length === 0) {
    return <p className="muted matrix-empty">No PO lines to compare (see the reasons above).</p>;
  }
  const sev = (line: number, codes: string[]): Severity | null => {
    const hits = match.reasons.filter((r) => r.line_no === line && codes.includes(r.code));
    if (hits.some((r) => r.severity === "block")) return "block";
    if (hits.some((r) => r.severity === "flag")) return "flag";
    return hits.length ? "info" : null;
  };
  const cell = (s: Severity | null) => (s ? ` var-${s}` : "");

  return (
    <div className="matrix-wrap">
      <table className="table matrix">
        <thead>
          <tr>
            <th scope="col">Line</th>
            <th scope="col">PO line</th>
            <th scope="col">Description</th>
            <th scope="col" className="num-col">
              PO qty
            </th>
            <th scope="col" className="num-col">
              {isService ? "SES accepted" : "Received (GR)"}
            </th>
            <th scope="col" className="num-col">
              Invoiced before
            </th>
            <th scope="col" className="num-col">
              This invoice
            </th>
            <th scope="col" className="num-col">
              PO price
            </th>
            <th scope="col" className="num-col">
              Invoice price
            </th>
            <th scope="col" className="num-col">
              Price var.
            </th>
            <th scope="col" className="num-col">
              Qty var.
            </th>
          </tr>
        </thead>
        <tbody>
          {match.matrix.map((row) => {
            const p = sev(row.invoice_line_no, ["PRICE_VARIANCE", "SMALL_DIFFERENCE"]);
            const q = sev(row.invoice_line_no, ["QTY_EXCEEDS_GR", "MISSING_GR", "MISSING_SES", "SES_VALUE_EXCEEDED"]);
            const unmatched = row.po_line_id === null;
            return (
              <tr key={row.invoice_line_no}>
                <td className="num">{row.invoice_line_no}</td>
                <td className="mono">{unmatched ? "not on PO" : row.po_line_no}</td>
                <td>{row.description}</td>
                <td className="num num-col">{unmatched ? "-" : `${qty(row.po_qty)} ${row.uom}`}</td>
                <td className={`num num-col${cell(q)}`}>
                  {unmatched ? "-" : isService ? inr(row.received) : `${qty(row.received)} ${row.uom}`}
                </td>
                <td className="num num-col">
                  {unmatched ? "-" : isService ? inr(row.previously_invoiced) : qty(row.previously_invoiced)}
                </td>
                <td className={`num num-col${cell(q)}`}>
                  {qty(row.invoice_qty)} {row.uom}
                </td>
                <td className="num num-col">{inr(row.po_price)}</td>
                <td className={`num num-col${cell(p)}`}>{inr(row.invoice_price)}</td>
                <td className={`num num-col${cell(p)}`}>
                  {p && p !== "info" ? <SeverityIcon severity={p} size={12} /> : null}{" "}
                  {row.price_variance_pct === null ? "-" : `${pct(row.price_variance_pct)} (${inr(row.price_variance_amount)})`}
                </td>
                <td className={`num num-col${cell(q)}`}>
                  {q && q !== "info" ? <SeverityIcon severity={q} size={12} /> : null}{" "}
                  {row.qty_variance === null ? "-" : Number(row.qty_variance) > 0 ? `+${qty(row.qty_variance)}` : qty(row.qty_variance)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
