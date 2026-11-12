import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, KeyRound, Lock, OctagonX, RotateCcw, Send, ShieldAlert, XCircle } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { InvoiceDetail, StepOut } from "../../api/types";
import { fmtDateTime } from "../../lib/format";

const STEP_ICON = { approved: CheckCircle2, rejected: XCircle, skipped: RotateCcw, pending: Clock } as const;

function StepRow({ s }: { s: StepOut }) {
  const Icon = STEP_ICON[s.status];
  return (
    <li className={`step step-${s.status}`}>
      <Icon size={15} aria-hidden="true" className="step-icon" />
      <div className="step-body">
        <p className="step-title">
          <strong>{s.title}</strong>
          <span className="muted"> · {s.status === "pending" ? "waiting" : s.status}</span>
          {s.mfa_verified ? (
            <span className="chip chip-approve step-chip">
              <KeyRound size={11} aria-hidden="true" /> MFA
            </span>
          ) : null}
          {s.escalated_at ? (
            <span className="chip chip-flag step-chip">
              <AlertTriangle size={11} aria-hidden="true" /> Escalated
            </span>
          ) : s.overdue ? (
            <span className="chip chip-flag step-chip">
              <Clock size={11} aria-hidden="true" /> Overdue
            </span>
          ) : null}
        </p>
        {s.approver ? (
          <p className="step-meta">
            {s.approver}
            {s.delegated_from ? ` (for ${s.delegated_from}, delegated)` : ""} · {fmtDateTime(s.decided_at)}
          </p>
        ) : s.status === "pending" && s.due_at ? (
          <p className="step-meta">SLA due {fmtDateTime(s.due_at)}</p>
        ) : s.decided_at ? (
          <p className="step-meta">{fmtDateTime(s.decided_at)}</p>
        ) : null}
        {s.comment ? <p className="step-comment">"{s.comment}"</p> : null}
      </div>
    </li>
  );
}

type Action = "approve" | "reject" | "send-back" | "request-info" | "override";

/** Approval timeline and the actions the signed-in user may take (the server re-checks every one). */
export function ApprovalPanel({ inv }: { inv: InvoiceDetail }) {
  const qc = useQueryClient();
  const wf = inv.workflow;
  const [comment, setComment] = useState("");
  const [totp, setTotp] = useState("");
  const act = useMutation({
    mutationFn: (action: Action) =>
      api(`/approvals/invoices/${inv.id}/${action}`, {
        method: "POST",
        body: JSON.stringify({ comment, totp: totp || null }),
      }),
    onSuccess: () => {
      setComment("");
      setTotp("");
      qc.invalidateQueries({ queryKey: ["invoice", String(inv.id)] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["approval-queue"] });
    },
  });
  const err = act.error instanceof ApiError ? act.error : null;
  const busy = act.isPending;

  return (
    <div className="approvals">
      {wf.override_justification ? (
        <div className="override-note">
          <ShieldAlert size={15} aria-hidden="true" />
          <p>
            <strong>FLAG overridden</strong> by {wf.override_by}, {fmtDateTime(wf.override_at)}: "{wf.override_justification}"
          </p>
        </div>
      ) : null}

      {wf.steps.length > 0 ? (
        <ol className="steps" aria-label="Approval steps">
          {wf.steps.map((s) => (
            <StepRow key={`${s.sequence}-${s.status}-${s.decided_at}`} s={s} />
          ))}
        </ol>
      ) : (
        <p className="muted approvals-empty">
          {inv.status === "blocked"
            ? "Blocked invoices are not routed for approval until the cause is fixed."
            : inv.status === "flagged"
              ? "Flagged: an AP clerk must resolve the exception or route it with a justification."
              : "Not routed for approval yet."}
        </p>
      )}

      {wf.approve_blocked_reason ? (
        <div className={`alert ${wf.approve_blocked_sod ? "alert-error" : "alert-info"}`} role="note">
          {wf.approve_blocked_sod ? <Lock size={16} aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
          <span>{wf.approve_blocked_reason}</span>
        </div>
      ) : null}

      {wf.can_approve ? (
        <div className="action-box">
          <label className="field">
            <span>Comment (required to reject, send back or ask the supplier)</span>
            <textarea className="input textarea" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          {wf.mfa_required ? (
            <label className="field">
              <span>
                <KeyRound size={12} aria-hidden="true" /> Authenticator code (invoices above ₹10 lakh need MFA)
              </span>
              <input
                className="input mono totp"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={totp}
                onChange={(e) => setTotp(e.target.value.replace(/\D/g, ""))}
                placeholder="123456"
              />
            </label>
          ) : null}
          <div className="action-row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || (wf.mfa_required && totp.length !== 6)}
              onClick={() => act.mutate("approve")}
            >
              <CheckCircle2 size={15} aria-hidden="true" /> Approve
            </button>
            <button type="button" className="btn" disabled={busy || comment.trim().length < 5} onClick={() => act.mutate("send-back")}>
              <RotateCcw size={15} aria-hidden="true" /> Send back
            </button>
            <button type="button" className="btn" disabled={busy || comment.trim().length < 5} onClick={() => act.mutate("request-info")}>
              <Send size={15} aria-hidden="true" /> Ask supplier
            </button>
            <button type="button" className="btn btn-danger" disabled={busy || comment.trim().length < 5} onClick={() => act.mutate("reject")}>
              <OctagonX size={15} aria-hidden="true" /> Reject
            </button>
          </div>
        </div>
      ) : null}

      {wf.can_override ? (
        <div className="action-box">
          <label className="field">
            <span>Justification to route this FLAG for approval (min. 15 characters; needs a second approver)</span>
            <textarea className="input textarea" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          <div className="action-row">
            <button type="button" className="btn btn-primary" disabled={busy || comment.trim().length < 15} onClick={() => act.mutate("override")}>
              <ShieldAlert size={15} aria-hidden="true" /> Override and route for approval
            </button>
          </div>
        </div>
      ) : null}

      {err ? (
        <div className="alert alert-error" role="alert">
          {err.info.sod ? <Lock size={16} aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
          <span>{err.message}</span>
        </div>
      ) : null}
    </div>
  );
}
