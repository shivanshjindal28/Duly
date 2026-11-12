import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Hourglass, Landmark, ShieldCheck } from "lucide-react";
import { api, ApiError } from "../api/client";

export interface BankChange {
  id: number;
  supplier_id: number;
  supplier_name: string;
  current_account: string;
  current_ifsc: string;
  new_account: string;
  new_ifsc: string;
  new_bank_name: string;
  reason: string;
  status: "requested" | "proposed" | "cooling" | "approved" | "rejected";
  requested_at: string;
  requested_by: string | null;
  proposed_by: string | null;
  approved_by: string | null;
  callback: { checklist: Record<string, boolean>; contact: string; notes: string; at: string } | null;
  cooling_until: string | null;
  cooling_hours_left: number | null;
  decision_note: string | null;
  can_propose: boolean;
  can_approve: boolean;
  can_reject: boolean;
}

/** Supplier portal: current bank details and the safe way to change them. */
export function BankDetailsCard({ account, ifsc }: { account: string; ifsc: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ account: "", ifsc: "", bank_name: "", reason: "" });
  const list = useQuery({ queryKey: ["bank-changes"], queryFn: () => api<BankChange[]>("/bank-changes") });
  const create = useMutation({
    mutationFn: () => api<BankChange>("/bank-changes", { method: "POST", body: JSON.stringify(form) }),
    onSuccess: () => {
      setOpen(false);
      setForm({ account: "", ifsc: "", bank_name: "", reason: "" });
      qc.invalidateQueries({ queryKey: ["bank-changes"] });
    },
  });
  const active = (list.data ?? []).some((r) => ["requested", "proposed", "cooling"].includes(r.status));
  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }
  const field = (k: keyof typeof form, label: string, extra: Record<string, unknown> = {}) => (
    <label className="field">
      <span>{label}</span>
      <input className="input" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} required {...extra} />
    </label>
  );
  return (
    <section className="panel bank-card" aria-labelledby="bank-title">
      <header className="bank-head">
        <h2 id="bank-title">
          <Landmark size={16} aria-hidden="true" /> {t("bank.title")}
        </h2>
        {!open && !active ? (
          <button type="button" className="btn" onClick={() => setOpen(true)}>
            {t("bank.change")}
          </button>
        ) : null}
      </header>
      <p>{t("bank.current", { account, ifsc })}</p>
      <p className="muted bank-why">
        <ShieldCheck size={13} aria-hidden="true" /> {t("bank.why_slow")}
      </p>
      {open ? (
        <form className="bank-form" onSubmit={submit}>
          {field("account", t("bank.account"), { inputMode: "numeric" })}
          {field("ifsc", t("bank.ifsc"), { maxLength: 11 })}
          {field("bank_name", t("bank.bank_name"))}
          {field("reason", t("bank.reason"))}
          {create.isError ? (
            <p className="field-error" role="alert">
              {create.error instanceof ApiError ? create.error.message : "Error"}
            </p>
          ) : null}
          <div className="bank-actions">
            <button type="submit" className="btn btn-primary" disabled={create.isPending}>
              {t("bank.submit")}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
              {t("bank.cancel")}
            </button>
          </div>
        </form>
      ) : null}
      {(list.data ?? []).slice(0, 3).map((r) => (
        <p key={r.id} className={`bank-req bank-${r.status}`}>
          <strong>{t(`bank.status.${r.status === "proposed" ? "cooling" : r.status}`)}</strong> · {t("bank.to", { account: r.new_account, ifsc: r.new_ifsc })}
          {r.status === "cooling" && r.cooling_hours_left ? (
            <span>
              {" "}
              · <Hourglass size={12} aria-hidden="true" /> {t("bank.hours_left", { hours: Math.ceil(r.cooling_hours_left) })}
            </span>
          ) : null}
          {r.decision_note && r.status === "rejected" ? <span> · {r.decision_note}</span> : null}
        </p>
      ))}
    </section>
  );
}
