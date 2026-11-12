import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Hourglass, Lock, PhoneCall, ShieldCheck, XCircle } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { BankChange } from "../components/BankDetailsCard";
import { fmtDateTime } from "../lib/format";
import "./BankChangesPage.css";

const STATUS: Record<BankChange["status"], { cls: string; label: string }> = {
  requested: { cls: "chip-info", label: "Requested: call-back needed" },
  proposed: { cls: "chip-flag", label: "Proposed" },
  cooling: { cls: "chip-flag", label: "Cooling period" },
  approved: { cls: "chip-approve", label: "Approved" },
  rejected: { cls: "chip-block", label: "Rejected" },
};

function Row({ r, checklist }: { r: BankChange; checklist: Record<string, string> }) {
  const qc = useQueryClient();
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [contact, setContact] = useState("");
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: (op: "propose" | "approve" | "reject") =>
      api(`/bank-changes/${r.id}/${op}`, {
        method: "POST",
        body: JSON.stringify(op === "propose" ? { checklist: checks, contact, notes: note } : { note }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bank-changes"] }),
  });
  const st = STATUS[r.status];
  return (
    <article className="panel bcr">
      <header className="bcr-head">
        <div>
          <h2>{r.supplier_name}</h2>
          <p className="muted">
            Requested {fmtDateTime(r.requested_at)} by {r.requested_by} · "{r.reason}"
          </p>
        </div>
        <span className={`chip ${st.cls}`}>{st.label}</span>
      </header>
      <div className="bcr-diff">
        <div>
          <p className="label">Current (vendor master)</p>
          <p className="mono">{r.current_account} · {r.current_ifsc}</p>
        </div>
        <div>
          <p className="label">Requested</p>
          <p className="mono">{r.new_account} · {r.new_ifsc}</p>
          <p className="muted">{r.new_bank_name}</p>
        </div>
      </div>
      {r.callback ? (
        <p className="bcr-callback">
          <PhoneCall size={13} aria-hidden="true" /> Call-back by {r.proposed_by} with {r.callback.contact}, {fmtDateTime(r.callback.at)}
          {r.callback.notes ? ` · "${r.callback.notes}"` : ""}
        </p>
      ) : null}
      {r.status === "cooling" ? (
        <p className="bcr-cooling">
          <Hourglass size={13} aria-hidden="true" />{" "}
          {r.cooling_hours_left && r.cooling_hours_left > 0
            ? `Cooling period: about ${Math.ceil(r.cooling_hours_left)} h left (until ${fmtDateTime(r.cooling_until)}).`
            : "Cooling period over: a finance approver (not the maker) can now approve."}
        </p>
      ) : null}
      {r.approved_by ? (
        <p className="bcr-done">
          <CheckCircle2 size={13} aria-hidden="true" /> Approved by {r.approved_by}; vendor master updated.
        </p>
      ) : null}

      {r.can_propose ? (
        <fieldset className="bcr-check">
          <legend>
            <ShieldCheck size={14} aria-hidden="true" /> Out-of-band call-back checklist (maker)
          </legend>
          {Object.entries(checklist).map(([k, label]) => (
            <label key={k} className="bcr-item">
              <input type="checkbox" checked={!!checks[k]} onChange={(e) => setChecks({ ...checks, [k]: e.target.checked })} /> {label}
            </label>
          ))}
          <label className="field">
            <span>Who did you speak to?</span>
            <input className="input" value={contact} onChange={(e) => setContact(e.target.value)} />
          </label>
        </fieldset>
      ) : null}
      {r.can_propose || r.can_approve || r.can_reject ? (
        <div className="bcr-actions">
          <input className="input" placeholder="Note (required to reject)" value={note} onChange={(e) => setNote(e.target.value)} />
          {r.can_propose ? (
            <button type="button" className="btn btn-primary" disabled={act.isPending} onClick={() => act.mutate("propose")}>
              <PhoneCall size={15} aria-hidden="true" /> Propose (start 72 h cooling)
            </button>
          ) : null}
          {r.status === "cooling" ? (
            <button type="button" className="btn btn-primary" disabled={!r.can_approve || act.isPending} onClick={() => act.mutate("approve")}
              title={r.can_approve ? "" : "Only a finance approver who is not the maker, after the cooling period"}>
              {r.can_approve ? <CheckCircle2 size={15} aria-hidden="true" /> : <Lock size={15} aria-hidden="true" />} Approve (checker)
            </button>
          ) : null}
          {r.can_reject ? (
            <button type="button" className="btn btn-danger" disabled={act.isPending} onClick={() => act.mutate("reject")}>
              <XCircle size={15} aria-hidden="true" /> Reject
            </button>
          ) : null}
        </div>
      ) : null}
      {act.isError ? (
        <p className="alert alert-error" role="alert">
          {act.error instanceof ApiError ? act.error.message : "Failed."}
        </p>
      ) : null}
    </article>
  );
}

/** AP staff: bank detail change requests with maker-checker, call-back and cooling period. */
export function BankChangesPage() {
  const list = useQuery({ queryKey: ["bank-changes"], queryFn: () => api<BankChange[]>("/bank-changes") });
  const checklist = useQuery({ queryKey: ["bank-checklist"], queryFn: () => api<Record<string, string>>("/bank-changes/checklist") });
  return (
    <div className="page bcr-page">
      <header className="page-head">
        <p className="label">Vendor master · payment fraud control</p>
        <h1>Bank detail changes</h1>
        <p className="muted">
          Clerk calls back on the number on file and proposes (maker), 72 h cooling period, then a finance approver
          approves (checker). Invoices printing other bank details stay blocked until then.
        </p>
      </header>
      {(list.data ?? []).length === 0 ? <p className="empty">No bank change requests.</p> : null}
      {(list.data ?? []).map((r) => (
        <Row key={r.id} r={r} checklist={checklist.data ?? {}} />
      ))}
    </div>
  );
}
