import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clock, KeyRound, Lock, UserCheck } from "lucide-react";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { DecisionChip } from "../components/StatusChip";
import type { Decision } from "../api/types";
import { fmtDate, fmtDateTime, inrApprox, money } from "../lib/format";
import "./ApprovalsPage.css";

interface QueueItem {
  invoice_id: number;
  invoice_number: string;
  supplier_name: string | null;
  invoice_date: string | null;
  total: string;
  currency?: string;
  total_inr?: string | null;
  decision: Decision | null;
  override: boolean;
  step_level: number;
  step_title: string;
  due_at: string | null;
  overdue: boolean;
  escalated: boolean;
  can_act: boolean;
  reason: string | null;
  via_delegation: boolean;
  mfa_required: boolean;
}
interface Delegation {
  id: number;
  from_name: string;
  to_name: string;
  starts_at: string;
  ends_at: string;
  reason: string;
  active: boolean;
}
interface Approver {
  id: number;
  full_name: string;
  level: number;
}

function DelegationCard() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["delegations"], queryFn: () => api<Delegation[]>("/approvals/delegations") });
  const people = useQuery({ queryKey: ["approvers"], queryFn: () => api<Approver[]>("/approvals/approvers") });
  const [to, setTo] = useState("");
  const [days, setDays] = useState("3");
  const [reason, setReason] = useState("");
  const add = useMutation({
    mutationFn: () =>
      api("/approvals/delegations", {
        method: "POST",
        body: JSON.stringify({ to_user_id: Number(to), days: Number(days), reason }),
      }),
    onSuccess: () => {
      setReason("");
      qc.invalidateQueries({ queryKey: ["delegations"] });
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    add.mutate();
  }
  return (
    <section className="panel side-card" aria-labelledby="deleg-title">
      <h2 id="deleg-title" className="label">
        Delegation
      </h2>
      <p className="muted side-note">Time-boxed and logged. The delegate approves in your name for your level only.</p>
      <form className="deleg-form" onSubmit={submit}>
        <label className="field">
          <span>Delegate to</span>
          <select className="input" value={to} onChange={(e) => setTo(e.target.value)} required>
            <option value="">Choose an approver</option>
            {(people.data ?? [])
              .filter((p) => p.id !== me?.id)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name} (L{p.level})
                </option>
              ))}
          </select>
        </label>
        <div className="deleg-row">
          <label className="field">
            <span>Days</span>
            <input className="input" type="number" min={1} max={30} value={days} onChange={(e) => setDays(e.target.value)} />
          </label>
          <label className="field deleg-reason">
            <span>Reason</span>
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="On leave" required />
          </label>
        </div>
        {add.isError ? (
          <p className="field-error" role="alert">
            {add.error instanceof ApiError ? add.error.message : "Could not save."}
          </p>
        ) : null}
        <button className="btn" type="submit" disabled={!to || reason.trim().length < 3 || add.isPending}>
          <UserCheck size={15} aria-hidden="true" /> Delegate
        </button>
      </form>
      <ul className="deleg-list">
        {(list.data ?? []).map((d) => (
          <li key={d.id}>
            <span className={`chip ${d.active ? "chip-approve" : "chip-neutral"}`}>{d.active ? "Active" : "Ended"}</span>{" "}
            {d.from_name} → {d.to_name}, until {fmtDateTime(d.ends_at)} · <span className="muted">{d.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Approver work queue: invoices at my level (or escalated / delegated to me), and SoD conflicts. */
export function ApprovalsPage() {
  const q = useQuery({ queryKey: ["approval-queue"], queryFn: () => api<QueueItem[]>("/approvals/queue") });
  const mine = (q.data ?? []).filter((i) => i.can_act);
  const blocked = (q.data ?? []).filter((i) => !i.can_act);
  return (
    <div className="page approvals-page">
      <header className="page-head">
        <p className="label">Delegation of Authority</p>
        <h1>Approvals</h1>
      </header>
      <div className="approvals-grid">
        <section className="panel table-panel" aria-labelledby="queue-title">
          <h2 id="queue-title" className="sr-only">
            Waiting for you
          </h2>
          {q.isLoading ? (
            <div className="skeleton-rows" aria-busy="true">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="skeleton-row" />
              ))}
            </div>
          ) : mine.length === 0 && blocked.length === 0 ? (
            <p className="empty">Nothing is waiting for you.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Invoice</th>
                  <th scope="col">Supplier</th>
                  <th scope="col" className="num-col">
                    Total
                  </th>
                  <th scope="col">Match</th>
                  <th scope="col">Step</th>
                  <th scope="col">SLA</th>
                  <th scope="col">Note</th>
                </tr>
              </thead>
              <tbody>
                {[...mine, ...blocked].map((i) => (
                  <tr key={i.invoice_id} className={i.can_act ? "" : "row-locked"}>
                    <td>
                      <Link to={`/invoices/${i.invoice_id}`} className="mono row-link">
                        {i.invoice_number}
                      </Link>
                      <div className="muted cell-sub">{fmtDate(i.invoice_date)}</div>
                    </td>
                    <td>{i.supplier_name}</td>
                    <td className="num num-col">{money(i.total, i.currency)}{i.currency && i.currency !== "INR" ? <div className="muted small">{inrApprox(i.total_inr, i.currency)}</div> : null}</td>
                    <td>
                      <DecisionChip decision={i.decision} />
                      {i.override ? <span className="chip chip-flag cell-chip">Override</span> : null}
                    </td>
                    <td>{i.step_title}</td>
                    <td>
                      {i.escalated ? (
                        <span className="chip chip-flag">
                          <AlertTriangle size={12} aria-hidden="true" /> Escalated
                        </span>
                      ) : i.overdue ? (
                        <span className="chip chip-flag">
                          <Clock size={12} aria-hidden="true" /> Overdue
                        </span>
                      ) : (
                        <span className="muted">{fmtDateTime(i.due_at)}</span>
                      )}
                    </td>
                    <td className="cell-note">
                      {!i.can_act ? (
                        <span className="sod-note">
                          <Lock size={12} aria-hidden="true" /> {i.reason}
                        </span>
                      ) : (
                        <>
                          {i.mfa_required ? (
                            <span className="chip chip-info cell-chip">
                              <KeyRound size={11} aria-hidden="true" /> MFA
                            </span>
                          ) : null}
                          {i.via_delegation ? <span className="chip chip-neutral cell-chip">Delegated</span> : null}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <DelegationCard />
      </div>
    </div>
  );
}
