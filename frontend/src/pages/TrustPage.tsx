import { useEffect } from "react";
import { PageSkeleton } from "../components/PageSkeleton";
import { useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Eye, FileLock2, Gavel, KeyRound, Link2, ScanSearch, ShieldAlert, type LucideIcon } from "lucide-react";
import { api } from "../api/client";
import "./AboutPages.css";

interface TrustOut {
  threshold: number;
  ai_mode: "live" | "cached" | "offline";
  ai_model: string;
  engine: { matches: number; ai_decided: number };
  extraction: {
    fields: number;
    below_threshold: number;
    reviews: number;
    corrected: number;
    sources: Record<string, number>;
    models: Record<string, number>;
  };
  injection: { found: number; ai_quarantined: number };
  access: {
    users_by_role: Record<string, number>;
    sod_refusals: number;
    mfa_approvals: number;
    lockouts: number;
    failed_logins: number;
    chat_refusals: number;
    chat_injection_flags: number;
  };
  data: { bank_accounts_encrypted: number; bank_alerts: number; synthetic: boolean };
  audit: { ok: boolean; events: number; signed_head: boolean };
}

const n = (v: number) => new Intl.NumberFormat("en-IN").format(v);

function Control({ icon: Icon, title, how, evidence }: { icon: LucideIcon; title: string; how: string[]; evidence: [string, string][] }) {
  return (
    <section className="panel control-card">
      <h2 className="control-title">
        <Icon size={17} aria-hidden="true" /> {title}
      </h2>
      <ul className="control-how">
        {how.map((h) => (
          <li key={h}>{h}</li>
        ))}
      </ul>
      <dl className="control-evidence" aria-label={`Live evidence: ${title}`}>
        {evidence.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className={v.length > 14 ? "evidence-text" : "num"}>{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** Trust & controls (spec section 12): each control with the live numbers that show it working. */
export function TrustPage() {
  const q = useQuery({ queryKey: ["trust"], queryFn: () => api<TrustOut>("/trust") });
  const { hash } = useLocation();
  useEffect(() => {
    if (q.data && hash) {
      document.getElementById(hash.slice(1))?.scrollIntoView({ block: "center" });
    }
  }, [q.data, hash]);
  if (q.isLoading) return <PageSkeleton blocks={4} label="Loading controls" />;
  if (!q.data) return <div className="page alert alert-error">Could not load the controls.</div>;
  const t = q.data;
  const e = t.extraction;
  const mode = t.ai_mode === "offline" ? "offline: OCR + rules (AI switched off)" : `${t.ai_mode} · ${t.ai_model}`;
  return (
    <div className="page about">
      <header className="page-head">
        <p className="label">Responsible AI, security and data</p>
        <h1>Trust &amp; controls</h1>
        <p className="muted">
          How Duly keeps people in charge of AI, money and data. Every number on this page is computed live from the
          database and the audit chain.
        </p>
      </header>

      <div className="control-grid">
        <Control icon={Gavel} title="AI never decides" how={[
          "The deterministic rules engine decides APPROVE, FLAG or BLOCK. AI only extracts fields, and powers the payment chatbot.",
          "The engine package imports nothing from the AI package; a unit test fails the build if it ever does.",
          "Every decision is stored with its reason codes, evidence, policy version and engine version.",
        ]} evidence={[
          ["Engine decisions recorded", n(t.engine.matches)],
          ["Decisions made by AI", n(t.engine.ai_decided)],
        ]} />

        <Control icon={Eye} title="Confidence and human review" how={[
          `Every field has a confidence score and its location on the page. Below ${Math.round(t.threshold * 100)}% (policy), a person must confirm or correct it.`,
          "Corrections are logged with the old value, the new value, who made it and why. They are never overwritten.",
          "If AI and the PDF text layer disagree, the text layer wins and the field goes to review.",
        ]} evidence={[
          ["Fields extracted", n(e.fields)],
          ["Below the threshold", n(e.below_threshold)],
          ["Human review actions", n(e.reviews)],
          ["Values corrected", n(e.corrected)],
        ]} />

        <Control icon={ScanSearch} title="Prompt-injection shield" how={[
          "Before any AI reads a document, Duly looks for hidden text (white, tiny, off-page, metadata) and instruction-like phrasing.",
          "If anything is found, the AI's reading is quarantined: shown to the clerk, never used. Hidden words never reach the parser.",
          "The chatbot strips injection phrases and has no tool that can reach another supplier's data.",
        ]} evidence={[
          ["Documents with hidden instructions", n(t.injection.found)],
          ["AI readings quarantined", n(t.injection.ai_quarantined)],
          ["Chat messages flagged", n(t.access.chat_injection_flags)],
          ["Cross-supplier chat requests refused", n(t.access.chat_refusals)],
        ]} />

        <Control icon={KeyRound} title="Access control" how={[
          "Six roles with server-side checks on every request; suppliers see only their own invoices (others return 404).",
          "Segregation of duties: no approving an invoice you processed, a PO you created, or two steps of one invoice.",
          "MFA (authenticator code) for approvals above Rs 10 lakh; 5 failed logins lock an account; sessions expire.",
        ]} evidence={[
          ["Users", Object.entries(t.access.users_by_role).map(([r, c]) => `${c} ${r}`).join(" · ")],
          ["Approvals with MFA", n(t.access.mfa_approvals)],
          ["Segregation-of-duties refusals", n(t.access.sod_refusals)],
          ["Failed logins / lockouts", `${n(t.access.failed_logins)} / ${n(t.access.lockouts)}`],
        ]} />

        <Control icon={FileLock2} title="Privacy and data minimisation" how={[
          "Only the invoice document (page images and its text) goes to the AI provider; never the vendor master, bank data or other invoices.",
          "Bank accounts are encrypted at rest (AES-GCM) and masked everywhere (XXXXXX4417), also in logs.",
          "Synthetic data only. The AI kill switch (AI mode: offline) runs everything on local OCR and rules.",
        ]} evidence={[
          ["AI mode now", mode],
          ["Vendor bank accounts encrypted", n(t.data.bank_accounts_encrypted)],
          ["Bank-detail fraud alerts", n(t.data.bank_alerts)],
          ["All master data synthetic", t.data.synthetic ? "yes" : "NO"],
        ]} />

        <Control icon={Link2} title="Tamper-evident audit trail" how={[
          "Every action is an event whose hash covers the previous event's hash; the chain head is signed with Ed25519.",
          "Events are written only after the business change commits, so the log never describes something that did not happen.",
          "Auditors can verify the chain any time; an edited or deleted row is pinpointed.",
        ]} evidence={[
          ["Chain", t.audit.ok ? "verified" : "BROKEN"],
          ["Events", n(t.audit.events)],
          ["Signed head valid", t.audit.signed_head ? "yes" : "no"],
        ]} />

        <Control icon={ShieldAlert} title="Application security" how={[
          "Uploads checked for type, size, page count and active PDF content (JavaScript, launch actions, embedded files); images re-encoded.",
          "CSRF protection, SameSite=strict session cookie, security headers (CSP, frame denial), login rate limit.",
          "Secrets only in environment variables; dependencies pinned to exact versions.",
        ]} evidence={[]} />

        <Control icon={BrainCircuit} title="Transparency" how={[
          "The AI mode badge is always visible in the top bar.",
          "Each extracted field records which extractor, model and prompt version produced it.",
          "Each decision shows the rule, the evidence values and where on the page they came from.",
        ]} evidence={Object.entries(e.models).map(([m, c]) => [m, `${n(c)} fields`] as [string, string])} />
      </div>

      <section className="panel model-card" aria-labelledby="model-card-title">
        <h2 id="model-card-title" className="label">Model card</h2>
        <div className="model-card-grid">
          <div>
            <h3>What the AI does</h3>
            <ul>
              <li>Reads invoice pages and returns each field with a confidence and the line it came from (strict JSON schema).</li>
              <li>Answers supplier questions through five read-only tools scoped to that supplier.</li>
            </ul>
          </div>
          <div>
            <h3>What it does not do</h3>
            <ul>
              <li>Approve, flag, block, route or pay anything.</li>
              <li>See vendor master data, bank details or other suppliers' invoices.</li>
              <li>Use tools during extraction.</li>
            </ul>
          </div>
          <div>
            <h3>Known failure modes</h3>
            <ul>
              <li>Misreads on blurred or tilted photos (OCR or AI): caught by confidence, arithmetic and GSTIN check-digit rules.</li>
              <li>Being instructed by text on the document: caught by the injection shield, and powerless anyway.</li>
              <li>Network or API outage: Duly falls back to offline OCR and says so in the audit trail.</li>
            </ul>
          </div>
          <div>
            <h3>How humans stay in control</h3>
            <ul>
              <li>Review of every low-confidence field, with the reason logged.</li>
              <li>Approvals by people under delegation of authority, with MFA for large amounts.</li>
              <li>A one-click AI kill switch; the whole demo runs offline.</li>
            </ul>
          </div>
        </div>
        <p className="muted small" id="ai-use">
          Generative AI use: Claude (via Claude Code) helped design and write this code, and Claude via the API powers
          extraction and the chatbot inside Duly. The team reviewed and can explain all of it.
        </p>
      </section>
    </div>
  );
}
