import { Link } from "react-router";
import type { MatchOut, ReasonOut, Severity } from "../../api/types";
import { fmtDateTime } from "../../lib/format";
import { DecisionChip, SeverityIcon } from "../StatusChip";

const ORDER: Record<Severity, number> = { block: 0, flag: 1, info: 2 };

const SUMMARY = {
  APPROVE: "Matches the PO and receipts within tolerance. Routed to the approval workflow.",
  FLAG: "Needs an AP clerk's review before it can be approved.",
  BLOCK: "Cannot be paid until the cause is fixed. Blocks cannot be overridden.",
} as const;

function ReasonItem({ r, onLine, invoiceId }: { r: ReasonOut; onLine?: (line: number) => void; invoiceId?: number }) {
  return (
    <li className={`reason reason-${r.severity}`}>
      <SeverityIcon severity={r.severity} />
      <div className="reason-body">
        <p className="reason-title">
          <span className="mono reason-code">{r.code}</span>
          <span>{r.title}</span>
          {r.line_no !== null && onLine ? (
            <button type="button" className="reason-line" onClick={() => onLine(r.line_no!)}>
              line {r.line_no}
            </button>
          ) : null}
        </p>
        <p className="reason-msg">{r.message}</p>
        {(r.code === "DUPLICATE" || r.code === "POSSIBLE_DUPLICATE") && invoiceId ? (
          <Link to={`/invoices/${invoiceId}/compare`} className="reason-compare">
            Compare side by side
          </Link>
        ) : null}
        {r.sap_equivalent ? (
          <p className="reason-sap" title="What a user would see / use in SAP today">
            SAP: {r.sap_equivalent}
          </p>
        ) : null}
      </div>
    </li>
  );
}

/** Decision card: the engine's outcome, every reason with evidence, and how it was produced. */
export function DecisionPanel({ match, onLine, invoiceId }: { match: MatchOut | null; onLine?: (line: number) => void; invoiceId?: number }) {
  if (!match) return <p className="muted">Not matched yet.</p>;
  const reasons = [...match.reasons].sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
  const actionable = reasons.filter((r) => r.severity !== "info");
  const infos = reasons.filter((r) => r.severity === "info");
  return (
    <div className={`decision decision-${match.decision.toLowerCase()}`}>
      <div className="decision-head">
        <DecisionChip decision={match.decision} large />
        <p className="decision-summary">{SUMMARY[match.decision]}</p>
      </div>
      {actionable.length > 0 ? (
        <ul className="reasons" aria-label="Reasons">
          {actionable.map((r, i) => (
            <ReasonItem key={i} r={r} onLine={onLine} invoiceId={invoiceId} />
          ))}
        </ul>
      ) : (
        <p className="decision-clean">No exceptions found.</p>
      )}
      {infos.length > 0 ? (
        <details className="reasons-info">
          <summary>
            {infos.length} informational note{infos.length > 1 ? "s" : ""}
          </summary>
          <ul className="reasons">
            {infos.map((r, i) => (
              <ReasonItem key={i} r={r} onLine={onLine} invoiceId={invoiceId} />
            ))}
          </ul>
        </details>
      ) : null}
      <p className="decision-prov muted">
        Decided by the rules engine ({match.engine_version}, policy v{match.policy_version}), trigger:{" "}
        {match.trigger.replace("_", " ")}, {fmtDateTime(match.created_at)}. AI does not make this decision.
      </p>
    </div>
  );
}
