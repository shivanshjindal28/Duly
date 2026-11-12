import { AlertTriangle, CheckCircle2, CircleDot, Clock, Eye, Info, OctagonX, Wallet, XCircle } from "lucide-react";
import type { Decision, InvoiceStatus, Severity } from "../api/types";

/** Status never conveyed by colour alone: every chip has an icon and text. */

const DECISION: Record<Decision, { cls: string; label: string; Icon: typeof CheckCircle2 }> = {
  APPROVE: { cls: "chip-approve", label: "Approve", Icon: CheckCircle2 },
  FLAG: { cls: "chip-flag", label: "Flag", Icon: AlertTriangle },
  BLOCK: { cls: "chip-block", label: "Block", Icon: OctagonX },
};

export function DecisionChip({ decision, large = false }: { decision: Decision | null; large?: boolean }) {
  if (!decision) return <span className="chip chip-neutral">Not matched</span>;
  const d = DECISION[decision];
  return (
    <span className={`chip ${d.cls}${large ? " chip-lg" : ""}`}>
      <d.Icon size={large ? 16 : 13} aria-hidden="true" />
      {d.label}
    </span>
  );
}

const STATUS: Record<InvoiceStatus, { cls: string; label: string; Icon: typeof CheckCircle2 }> = {
  received: { cls: "chip-neutral", label: "Received", Icon: CircleDot },
  needs_review: { cls: "chip-info", label: "Needs review", Icon: Eye },
  flagged: { cls: "chip-flag", label: "Flagged", Icon: AlertTriangle },
  blocked: { cls: "chip-block", label: "Blocked", Icon: OctagonX },
  pending_approval: { cls: "chip-info", label: "Pending approval", Icon: Clock },
  approved: { cls: "chip-approve", label: "Approved", Icon: CheckCircle2 },
  rejected: { cls: "chip-block", label: "Rejected", Icon: XCircle },
  paid: { cls: "chip-approve", label: "Paid", Icon: Wallet },
};

/** `label` overrides the English text (the supplier portal passes its translated label). */
export function StatusChip({ status, label }: { status: InvoiceStatus; label?: string }) {
  const s = STATUS[status];
  return (
    <span className={`chip ${s.cls}`}>
      <s.Icon size={13} aria-hidden="true" />
      {label ?? s.label}
    </span>
  );
}

const SEVERITY: Record<Severity, { cls: string; Icon: typeof CheckCircle2; label: string }> = {
  block: { cls: "chip-block", Icon: OctagonX, label: "Block" },
  flag: { cls: "chip-flag", Icon: AlertTriangle, label: "Flag" },
  info: { cls: "chip-info", Icon: Info, label: "Info" },
};

export function SeverityIcon({ severity, size = 14 }: { severity: Severity; size?: number }) {
  const s = SEVERITY[severity];
  return <s.Icon size={size} aria-label={s.label} className={`sev-icon sev-${severity}`} />;
}

export function severityClass(severity: Severity): string {
  return SEVERITY[severity].cls;
}
