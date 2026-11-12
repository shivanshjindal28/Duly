import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Building2, Inbox, MailCheck, MailQuestion, Paperclip, Send, ShieldAlert } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { Decision } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PageSkeleton } from "../components/PageSkeleton";
import { DecisionChip } from "../components/StatusChip";
import { fmtDateTime } from "../lib/format";
import "./InboxPage.css";

interface AttachmentOut {
  filename: string;
  content_type: string;
  size: number;
  outcome: "invoice" | "rejected";
  invoice_id?: number;
  invoice_number?: string;
  decision?: Decision;
  error?: string;
}
interface EmailOut {
  id: number;
  from_addr: string;
  from_name: string | null;
  subject: string;
  body: string;
  source: "mailbox" | "composed";
  sender_status: "verified" | "internal" | "lookalike" | "unknown";
  sender_detail: string;
  sender_supplier: string | null;
  status: string;
  attachments: AttachmentOut[];
  received_at: string;
}
interface InboxOut {
  mailbox: string;
  simulated: boolean;
  emails: EmailOut[];
}

const SENDER: Record<EmailOut["sender_status"], { label: string; chip: string; Icon: typeof MailCheck }> = {
  verified: { label: "Registered supplier address", chip: "chip-approve", Icon: MailCheck },
  internal: { label: "Plant X colleague", chip: "chip-neutral", Icon: Building2 },
  lookalike: { label: "Lookalike domain", chip: "chip-block", Icon: ShieldAlert },
  unknown: { label: "Sender not on vendor master", chip: "chip-flag", Icon: MailQuestion },
};

function EmailCard({ e }: { e: EmailOut }) {
  const s = SENDER[e.sender_status];
  return (
    <article className="panel mail" aria-labelledby={`mail-${e.id}`}>
      <header className="mail-head">
        <div>
          <h2 id={`mail-${e.id}`} className="mail-subject">
            {e.subject || "(no subject)"}
          </h2>
          <p className="muted small">
            {e.from_name ? `${e.from_name} ` : ""}
            <span className="mono">&lt;{e.from_addr}&gt;</span> · {fmtDateTime(e.received_at)}
            {e.source === "composed" ? " · composed in Duly" : ""}
          </p>
        </div>
        <span className={`chip ${s.chip}`} title={e.sender_detail}>
          <s.Icon size={13} aria-hidden="true" /> {s.label}
        </span>
      </header>
      {e.sender_status === "lookalike" ? (
        <p className="alert alert-error small" role="note">
          <AlertTriangle size={14} aria-hidden="true" /> {e.sender_detail}. Invoices from this email are flagged and a
          security alert was logged.
        </p>
      ) : (
        <p className="muted small mail-sender">{e.sender_detail}.</p>
      )}
      {e.body ? (
        <details className="mail-body">
          <summary className="small">Message</summary>
          <pre>{e.body}</pre>
        </details>
      ) : null}
      {e.attachments.length ? (
        <ul className="mail-atts" aria-label="Attachments">
          {e.attachments.map((a, i) => (
            <li key={`${a.filename}-${i}`}>
              <Paperclip size={13} aria-hidden="true" />
              <span className="mono small">{a.filename}</span>
              {a.outcome === "invoice" && a.invoice_id ? (
                <>
                  <Link to={`/invoices/${a.invoice_id}`}>Invoice {a.invoice_number}</Link>
                  <DecisionChip decision={a.decision ?? null} />
                </>
              ) : (
                <span className="sev-block small">Rejected: {a.error}</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No attachments: nothing to process.</p>
      )}
    </article>
  );
}

function Compose({ onDone }: { onDone: (m: string) => void }) {
  const qc = useQueryClient();
  const [from, setFrom] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const send = useMutation({
    mutationFn: () => {
      const f = new FormData();
      f.append("from_addr", from);
      f.append("subject", subject);
      f.append("body", body);
      for (const file of Array.from(files ?? [])) f.append("files", file);
      return api<EmailOut>("/inbox/compose", { method: "POST", body: f });
    },
    onSuccess: (e) => {
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
      setSubject("");
      setBody("");
      setFiles(null);
      onDone(`Email from ${e.from_addr} received: ${e.attachments.filter((a) => a.outcome === "invoice").length} invoice(s).`);
    },
  });
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    send.mutate();
  };
  return (
    <form className="panel compose" onSubmit={submit} aria-labelledby="compose-title">
      <h2 id="compose-title" className="label">
        Send a test email to the AP mailbox
      </h2>
      <div className="compose-row">
        <label className="field">
          <span>From</span>
          <input className="input" type="email" required placeholder="accounts@navrang-pack.example" value={from}
            onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="field">
          <span>Subject</span>
          <input className="input" maxLength={300} value={subject} onChange={(e) => setSubject(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Message</span>
        <textarea className="input textarea" rows={2} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)} />
      </label>
      <label className="field">
        <span>Attachments (PDF, JPG or PNG invoices; other files are refused)</span>
        <input className="input" type="file" multiple required onChange={(e) => setFiles(e.target.files)} />
      </label>
      {send.error ? (
        <p className="alert alert-error" role="alert">
          {send.error instanceof ApiError ? send.error.message : "Could not send the email."}
        </p>
      ) : null}
      <button type="submit" className="btn btn-primary btn-sm compose-send" disabled={send.isPending}>
        <Send size={14} aria-hidden="true" /> {send.isPending ? "Processing…" : "Send to AP mailbox"}
      </button>
    </form>
  );
}

/** AP mailbox (email-in, simulated): what arrived, who really sent it, and what became of each attachment. */
export function InboxPage() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const isClerk = me?.role === "clerk";
  const [note, setNote] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const q = useQuery({ queryKey: ["inbox"], queryFn: () => api<InboxOut>("/inbox") });
  const fetchMail = useMutation({
    mutationFn: () => api<{ fetched: number; message: string }>("/inbox/fetch", { method: "POST" }),
    onSuccess: (r) => {
      setNote(r.message);
      qc.invalidateQueries({ queryKey: ["inbox"] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
    },
  });
  if (q.isLoading) return <PageSkeleton blocks={3} label="Loading the AP mailbox" />;
  if (!q.data) return <div className="page alert alert-error">Could not load the AP mailbox.</div>;

  return (
    <div className="page inbox-page">
      <header className="page-head page-head-row">
        <div>
          <p className="label">Email-in</p>
          <h1>AP mailbox</h1>
          <p className="muted">
            <span className="mono">{q.data.mailbox}</span> · simulated (no mail server, the demo runs offline): emails
            are real MIME messages. Each invoice attachment goes through the same checks as an upload, and the sender
            is checked against the vendor master.
          </p>
        </div>
        {isClerk ? (
          <div className="inbox-actions">
            <button type="button" className="btn btn-primary" onClick={() => fetchMail.mutate()} disabled={fetchMail.isPending}>
              <Inbox size={15} aria-hidden="true" /> {fetchMail.isPending ? "Fetching…" : "Fetch new mail"}
            </button>
            <button type="button" className="btn" onClick={() => setComposing((v) => !v)} aria-expanded={composing}>
              <Send size={15} aria-hidden="true" /> Compose
            </button>
          </div>
        ) : null}
      </header>
      {note ? (
        <p className="alert alert-success" role="status">
          {note}
        </p>
      ) : null}
      {isClerk && composing ? <Compose onDone={(m) => { setNote(m); setComposing(false); }} /> : null}
      {q.data.emails.length ? (
        <div className="mail-list">{q.data.emails.map((e) => <EmailCard key={e.id} e={e} />)}</div>
      ) : (
        <div className="panel empty">
          <p>No email yet. {isClerk ? "Fetch new mail to receive the suppliers' latest emails." : "An AP clerk fetches the mailbox."}</p>
        </div>
      )}
    </div>
  );
}
