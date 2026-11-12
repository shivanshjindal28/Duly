import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { BadgeCheck, CalendarClock, CircleAlert, FileMinus2, Hourglass, Languages, Landmark, Upload, Wallet } from "lucide-react";
import { api } from "../api/client";
import type { InvoiceStatus } from "../api/types";
import { BankDetailsCard } from "../components/BankDetailsCard";
import { ChatDock } from "../components/ChatDock";
import "./BankChangesPage.css";
import { DulyRail } from "../components/DulyRail";
import { StatusChip } from "../components/StatusChip";
import { setLanguage } from "../i18n";
import { fmtDate, inr } from "../lib/format";
import "./SupplierPortalPage.css";

interface Todo {
  code: string;
  severity: string;
  you_act: boolean;
  params: Record<string, string>;
}
interface PortalInvoice {
  id: number;
  invoice_number: string;
  invoice_date: string | null;
  po_number: string | null;
  total: string;
  status: InvoiceStatus;
  stage: string;
  rail: number;
  expected_payment: string | null;
  msme_due_date: string | null;
  msme_days_left: number | null;
  todos: Todo[];
}
interface Portal {
  supplier_name: string;
  supplier_code: string;
  msme_category: string;
  msme_eligible: boolean;
  udyam_no: string | null;
  payment_terms_days: number;
  written_agreement: boolean;
  bank_account_masked: string;
  bank_ifsc: string;
  today: string;
  invoices: PortalInvoice[];
  payments: { invoice_number: string; paid_at: string; gross: string; tds: string; net: string; utr: string }[];
}

function InvoiceCard({ inv, msme }: { inv: PortalInvoice; msme: boolean }) {
  const { t, i18n } = useTranslation();
  const mine = inv.todos.filter((x) => x.you_act);
  const theirs = inv.todos.filter((x) => !x.you_act);
  const msg = (x: Todo) => {
    // Amounts in Indian grouping (the templates add the ₹ sign).
    const params = { ...x.params };
    for (const k of ["credit", "po_price"]) if (params[k]) params[k] = inr(params[k], false);
    return i18n.exists(`todo.${x.code}`) ? t(`todo.${x.code}`, params) : t("todo.default", { code: x.code });
  };
  const expected =
    inv.expected_payment !== null
      ? fmtDate(inv.expected_payment)
      : inv.status === "blocked" || inv.status === "flagged"
        ? t("portal.expected_after_fix")
        : inv.status === "paid"
          ? "-"
          : t("portal.expected_not_yet");
  return (
    <article className={`panel pinv${mine.length ? " pinv-action" : ""}`} aria-labelledby={`pinv-${inv.id}`}>
      <header className="pinv-head">
        <div>
          <h2 id={`pinv-${inv.id}`} className="mono">
            {t("portal.invoice", { number: inv.invoice_number })}
          </h2>
          <p className="muted">
            {t("portal.dated", { date: fmtDate(inv.invoice_date) })}
            {inv.po_number ? ` · ${t("portal.po", { po: inv.po_number })}` : ""}
          </p>
        </div>
        <div className="pinv-amount">
          <span className="num">{inr(inv.total)}</span>
          <StatusChip status={inv.status} label={t(`status.${inv.status}`)} />
        </div>
      </header>
      <DulyRail completed={inv.rail} />
      <dl className="pinv-facts">
        <div>
          <dt>{t("portal.where")}</dt>
          <dd>{t(inv.stage)}</dd>
        </div>
        <div>
          <dt>{t("portal.expected")}</dt>
          <dd>{expected}</dd>
        </div>
        {msme && inv.msme_due_date ? (
          <div>
            <dt>
              <CalendarClock size={12} aria-hidden="true" /> {t("portal.msme_due", { date: fmtDate(inv.msme_due_date) })}
            </dt>
            <dd>
              {inv.msme_days_left === null ? (
                "-"
              ) : inv.msme_days_left >= 0 ? (
                <span className={`countdown${inv.msme_days_left <= 7 ? " is-soon" : ""}`}>
                  <Hourglass size={12} aria-hidden="true" /> {t("portal.days_left", { count: inv.msme_days_left })}
                </span>
              ) : (
                <span className="countdown is-over">{t("portal.days_over", { count: -inv.msme_days_left })}</span>
              )}
            </dd>
          </div>
        ) : null}
      </dl>
      {mine.length ? (
        <section className="todo todo-you" aria-label={t("portal.what_to_do")}>
          <h3>
            <CircleAlert size={14} aria-hidden="true" /> {t("portal.what_to_do")}
          </h3>
          <ul>
            {mine.map((x) => (
              <li key={x.code}>{msg(x)}</li>
            ))}
          </ul>
          {mine.some((x) => x.code === "QTY_EXCEEDS_GR" || x.code === "SES_VALUE_EXCEEDED") &&
          !mine.some((x) => x.code === "DUPLICATE") ? (
            <Link to={`/invoices/${inv.id}#credit-note`} className="btn btn-sm todo-btn">
              <FileMinus2 size={14} aria-hidden="true" /> {t("portal.enter_credit_note")}
            </Link>
          ) : null}
        </section>
      ) : null}
      {theirs.length ? (
        <section className="todo todo-them" aria-label={t("portal.plant_x_doing")}>
          <h3>{t("portal.plant_x_doing")}</h3>
          <ul>
            {theirs.map((x) => (
              <li key={x.code}>{msg(x)}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {!inv.todos.length && inv.status !== "rejected" ? (
        <p className="todo-none">
          <BadgeCheck size={14} aria-hidden="true" /> {t("portal.nothing_to_do")}
        </p>
      ) : null}
      <Link to={`/invoices/${inv.id}`} className="pinv-link">
        {t("portal.details")}
      </Link>
    </article>
  );
}

/** Supplier portal: where is my invoice, why, what do I do, and when will I be paid. English / Hindi. */
export function SupplierPortalPage() {
  const { t, i18n } = useTranslation();
  const q = useQuery({ queryKey: ["portal"], queryFn: () => api<Portal>("/portal") });
  const hindi = i18n.language === "hi";

  if (!q.data) {
    return (
      <div className="page" aria-busy="true">
        <div className="skeleton-row" style={{ height: 120 }} />
      </div>
    );
  }
  const p = q.data;
  const open = p.invoices.filter((i) => !["paid", "rejected"].includes(i.status));
  const action = p.invoices.filter((i) => i.todos.some((x) => x.you_act));
  const next = open.map((i) => i.expected_payment).filter((d): d is string => !!d).sort()[0];
  const paid = p.payments.reduce((s, x) => s + Number(x.net), 0);
  const msmeDays = p.written_agreement ? Math.min(p.payment_terms_days, 45) : 15;

  return (
    <div className={`page portal${hindi ? " lang-hi" : ""}`} lang={hindi ? "hi" : "en"}>
      <header className="page-head page-head-row">
        <div>
          <p className="label">{t("portal.eyebrow")}</p>
          <h1>{t("portal.title")}</h1>
          <p className="muted portal-sub">
            {p.supplier_name} · {p.supplier_code} ·{" "}
            {p.msme_eligible ? (
              <span className="chip chip-info">{t("portal.msme_badge", { category: p.msme_category })}</span>
            ) : (
              t("portal.msme_none")
            )}
            {p.udyam_no ? ` · ${t("portal.udyam", { no: p.udyam_no })}` : ""}
          </p>
          <p className="muted portal-sub">
            {p.msme_eligible ? t("portal.terms_msme", { days: msmeDays }) : t("portal.terms", { days: p.payment_terms_days })} ·{" "}
            <Landmark size={12} aria-hidden="true" /> {t("portal.bank", { account: p.bank_account_masked })}
          </p>
        </div>
        <div className="portal-actions">
          <button
            type="button"
            className="btn"
            onClick={() => setLanguage(hindi ? "en" : "hi")}
            aria-label={`${t("portal.lang_toggle")}: ${t("portal.lang_label")}`}
            lang={hindi ? "en" : "hi"}
          >
            <Languages size={16} aria-hidden="true" /> {t("portal.lang_toggle")}
          </button>
          <Link to="/upload" className="btn btn-primary">
            <Upload size={16} aria-hidden="true" /> {t("portal.upload")}
          </Link>
        </div>
      </header>

      <section className="kpis portal-kpis" aria-label="Summary">
        <div className="kpi">
          <span className="kpi-label">{t("portal.kpi_open")}</span>
          <span className="kpi-value num">{open.length}</span>
        </div>
        <div className={`kpi${action.length ? " kpi-alert" : ""}`}>
          <span className="kpi-label">{t("portal.kpi_hold")}</span>
          <span className="kpi-value num">{action.length}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">{t("portal.kpi_next")}</span>
          <span className="kpi-value">{next ? fmtDate(next) : t("portal.none_yet")}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">
            <Wallet size={12} aria-hidden="true" /> {t("portal.kpi_paid")}
          </span>
          <span className="kpi-value num">{inr(paid)}</span>
        </div>
      </section>

      {p.invoices.length === 0 ? <p className="empty">{t("portal.empty")}</p> : null}
      <div className="pinv-list">
        {p.invoices.map((inv) => (
          <InvoiceCard key={inv.id} inv={inv} msme={p.msme_eligible} />
        ))}
      </div>

      <BankDetailsCard account={p.bank_account_masked} ifsc={p.bank_ifsc} />

      <section className="panel table-panel" aria-labelledby="pay-title">
        <h2 id="pay-title" className="label panel-title">
          {t("portal.payments")}
        </h2>
        {p.payments.length === 0 ? (
          <p className="empty">{t("portal.no_payments")}</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t("portal.col_invoice")}</th>
                <th scope="col">{t("portal.col_date")}</th>
                <th scope="col" className="num-col">{t("portal.col_gross")}</th>
                <th scope="col" className="num-col">{t("portal.col_tds")}</th>
                <th scope="col" className="num-col">{t("portal.col_net")}</th>
                <th scope="col">{t("portal.col_utr")}</th>
              </tr>
            </thead>
            <tbody>
              {p.payments.map((x) => (
                <tr key={x.utr}>
                  <td className="mono">{x.invoice_number}</td>
                  <td>{fmtDate(x.paid_at)}</td>
                  <td className="num num-col">{inr(x.gross)}</td>
                  <td className="num num-col">{inr(x.tds)}</td>
                  <td className="num num-col">{inr(x.net)}</td>
                  <td className="mono">{x.utr}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <p className="muted portal-help">{t("portal.help")}</p>
      <ChatDock greetingName={p.supplier_name} />
    </div>
  );
}
