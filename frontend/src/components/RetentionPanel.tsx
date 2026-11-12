import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, CheckCircle2, ShieldCheck, Trash2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import { fmtDate, fmtDateTime } from "../lib/format";

const plural = (n: number | string, word: string) => `${n} ${word}${Number(n) === 1 ? "" : "s"}`;

interface Retention {
  settings: { documents_years: number; chat_days: number; email_body_days: number };
  cutoffs: { documents_before: string; chats_before: string; email_bodies_before: string };
  due: { documents: number; documents_kept_open_invoice: number; chats: number; email_texts: number };
  oldest_document: string | null;
  oldest_document_due: string | null;
  never_deleted: string[];
  last_run: { at: string; counts: Record<string, number | string> } | null;
  can_run: boolean;
}

/** Data retention: what is due for deletion under the policy, what is never deleted, and a run button (admin). */
export function RetentionPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["retention"], queryFn: () => api<Retention>("/policy/retention") });
  const [confirming, setConfirming] = useState(false);
  const run = useMutation({
    mutationFn: () => api<Retention & { result: Record<string, number> }>("/policy/retention/run", { method: "POST" }),
    onSuccess: (d) => {
      qc.setQueryData(["retention"], d);
      setConfirming(false);
    },
  });
  const r = q.data;
  if (!r) return null;
  const total = r.due.documents + r.due.chats + r.due.email_texts;

  return (
    <section className="panel retention" aria-labelledby="ret-title">
      <h2 id="ret-title" className="panel-title">
        <Archive size={15} aria-hidden="true" /> Data retention
      </h2>
      <p className="muted small">
        Periods are the "Data retention" values above. Applied on demand here (a scheduler would run it nightly in
        production). Every run is in the audit trail with counts only.
      </p>
      <ul className="ret-due">
        <li>
          <strong className="num">{r.due.documents}</strong> invoice file{r.due.documents === 1 ? "" : "s"} older than {r.settings.documents_years} years
          (before {fmtDate(r.cutoffs.documents_before)}) on paid or rejected invoices
          {r.due.documents_kept_open_invoice ? `; ${r.due.documents_kept_open_invoice} kept because an invoice is still open` : ""}
        </li>
        <li>
          <strong className="num">{r.due.chats}</strong> payment-assistant chat{r.due.chats === 1 ? "" : "s"} older than {r.settings.chat_days} days
        </li>
        <li>
          <strong className="num">{r.due.email_texts}</strong> email text{r.due.email_texts === 1 ? "" : "s"} older than {r.settings.email_body_days} days
        </li>
      </ul>
      {r.oldest_document_due ? (
        <p className="small">
          Oldest invoice file: {fmtDate(r.oldest_document)}, due for deletion on {fmtDate(r.oldest_document_due)} (if its invoice is closed).
        </p>
      ) : null}
      <div className="ret-keep">
        <p className="small strong">
          <ShieldCheck size={13} aria-hidden="true" /> Never deleted by retention
        </p>
        <ul className="small">
          {r.never_deleted.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      </div>
      {r.last_run ? (
        <p className="small muted">
          Last run {fmtDateTime(r.last_run.at)}: {plural(r.last_run.counts.documents_deleted, "file")},{" "}
          {plural(r.last_run.counts.chats_deleted, "chat")}, {plural(r.last_run.counts.email_texts_deleted, "email text")} deleted.
        </p>
      ) : (
        <p className="small muted">Retention has not been run yet.</p>
      )}
      {r.can_run ? (
        <div className="ret-actions">
          {confirming ? (
            <>
              <button type="button" className="btn btn-danger" disabled={run.isPending} onClick={() => run.mutate()}>
                <Trash2 size={15} aria-hidden="true" /> Delete {total} item{total === 1 ? "" : "s"} now
              </button>
              <button type="button" className="btn" onClick={() => setConfirming(false)}>Cancel</button>
              <span className="small muted">Deleted files cannot be recovered.</span>
            </>
          ) : (
            <button type="button" className="btn" onClick={() => setConfirming(true)}>
              <Trash2 size={15} aria-hidden="true" /> Apply retention now
            </button>
          )}
        </div>
      ) : null}
      {run.isSuccess ? (
        <p className="alert alert-success" role="status">
          <CheckCircle2 size={14} aria-hidden="true" /> Done: {plural(run.data.result.documents_deleted, "file")},{" "}
          {plural(run.data.result.chats_deleted, "chat")} and {plural(run.data.result.email_texts_deleted, "email text")} deleted.
        </p>
      ) : null}
      {run.isError ? (
        <p className="alert alert-error" role="alert">{run.error instanceof ApiError ? run.error.message : "Retention run failed."}</p>
      ) : null}
    </section>
  );
}
