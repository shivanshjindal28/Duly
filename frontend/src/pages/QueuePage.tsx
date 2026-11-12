import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, Keyboard, Save, X } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { Decision, InvoiceStatus, SupplierOut } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DecisionChip, StatusChip } from "../components/StatusChip";
import { fmtDate, inr } from "../lib/format";
import "./QueuePage.css";

interface Row {
  id: number;
  invoice_number: string;
  supplier_id: number | null;
  supplier_name: string | null;
  total: string;
  status: InvoiceStatus;
  decision: Decision | null;
  reasons: string[];
  top_reason: string | null;
  age_days: number;
  current_owner: string;
  msme_due_date: string | null;
  received_at: string;
}
type SortKey = "invoice_number" | "supplier_name" | "total" | "age_days" | "msme_due_date" | "status";
const FILTER_KEYS = ["status", "reason", "supplier_id", "age", "msme_due_within"] as const;
const VIEWS_KEY = "duly.queue.views";

const REASONS = [
  "NO_PO", "MISSING_GR", "MISSING_SES", "QTY_EXCEEDS_GR", "PRICE_VARIANCE", "TAX_MISMATCH", "MATH_ERROR",
  "BANK_MISMATCH", "GSTIN_INVALID", "SUPPLIER_MISMATCH", "LINE_NOT_ON_PO", "NO_LINES", "NEEDS_REVIEW",
];

function loadViews(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(VIEWS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function toCsv(rows: Row[]): string {
  const head = ["invoice", "supplier", "total", "status", "decision", "reasons", "age_days", "with", "msme_due"];
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [head.join(","), ...rows.map((r) => [r.invoice_number, r.supplier_name, r.total, r.status, r.decision, r.reasons.join(" "), r.age_days, r.current_owner, r.msme_due_date].map(esc).join(","))].join("\n");
}

/** Dense work queue: filters from the URL (dashboard drill-down), sorting, saved views, keyboard. */
export function QueuePage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "age_days", dir: -1 });
  const [cursor, setCursor] = useState(0);
  const [views, setViews] = useState<Record<string, string>>(loadViews);
  const [notice, setNotice] = useState<string | null>(null);
  const tableRef = useRef<HTMLTableSectionElement>(null);

  const query = new URLSearchParams(params);
  if (!query.get("status")) query.set("status", "open");
  const rowsQ = useQuery({ queryKey: ["queue", query.toString()], queryFn: () => api<Row[]>(`/dashboard/queue?${query}`) });
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: () => api<SupplierOut[]>("/suppliers") });

  const rows = useMemo(() => {
    const r = [...(rowsQ.data ?? [])];
    r.sort((a, b) => {
      const av = a[sort.key] ?? "";
      const bv = b[sort.key] ?? "";
      const n = sort.key === "total" ? Number(av) - Number(bv) : av < bv ? -1 : av > bv ? 1 : 0;
      return n * sort.dir;
    });
    return r;
  }, [rowsQ.data, sort]);

  const approve = useMutation({
    mutationFn: (id: number) => api(`/approvals/invoices/${id}/approve`, { method: "POST", body: JSON.stringify({ comment: "Approved from queue" }) }),
    onSuccess: () => {
      setNotice("Approved.");
      qc.invalidateQueries({ queryKey: ["queue"] });
    },
    onError: (e) => setNotice(e instanceof ApiError ? e.message : "Could not approve."),
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
    setCursor(0);
  }

  // Keyboard: J/K move, Enter open, A approve (approvers), R open to reject, F open to flag/review.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (t.closest("input, select, textarea") || e.ctrlKey || e.metaKey || e.altKey) return;
      const row = rows[cursor];
      const key = e.key.toLowerCase();
      if (key === "j") setCursor((c) => Math.min(rows.length - 1, c + 1));
      else if (key === "k") setCursor((c) => Math.max(0, c - 1));
      else if ((key === "enter" || key === "r" || key === "f") && row) navigate(`/invoices/${row.id}`);
      else if (key === "a" && row && me?.role === "approver") approve.mutate(row.id);
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, cursor, me, navigate, approve]);

  useEffect(() => {
    tableRef.current?.querySelector<HTMLElement>(`tr[data-idx="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  function saveView() {
    const name = window.prompt("Name this view", "My view");
    if (!name) return;
    const next = { ...views, [name]: params.toString() };
    setViews(next);
    try {
      localStorage.setItem(VIEWS_KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable: the view lasts for this session only */
    }
  }

  function exportCsv() {
    const blob = new Blob([toCsv(rows)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `duly-queue-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const th = (key: SortKey, label: string, num = false) => (
    <th scope="col" className={num ? "num-col" : undefined} aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort-btn" onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : 1 }))}>
        {label}
        {sort.key === key ? sort.dir === 1 ? <ArrowUp size={12} aria-hidden="true" /> : <ArrowDown size={12} aria-hidden="true" /> : null}
      </button>
    </th>
  );
  const active = FILTER_KEYS.filter((k) => params.get(k));

  return (
    <div className="page queue-page">
      <header className="page-head page-head-row">
        <div>
          <p className="label">Work queue</p>
          <h1>Invoices to work</h1>
        </div>
        <div className="queue-actions">
          <button type="button" className="btn" onClick={saveView}>
            <Save size={15} aria-hidden="true" /> Save view
          </button>
          <button type="button" className="btn" onClick={exportCsv} disabled={!rows.length}>
            <Download size={15} aria-hidden="true" /> CSV
          </button>
        </div>
      </header>

      <section className="panel queue-filters" aria-label="Filters">
        <label className="field">
          <span>Status</span>
          <select className="input" value={params.get("status") ?? "open"} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="open">Open exceptions</option>
            <option value="all">All invoices</option>
            <option value="needs_review">Needs review</option>
            <option value="blocked">Blocked</option>
            <option value="flagged">Flagged</option>
            <option value="pending_approval">Pending approval</option>
            <option value="approved">Approved</option>
          </select>
        </label>
        <label className="field">
          <span>Reason</span>
          <select className="input" value={params.get("reason") ?? ""} onChange={(e) => setFilter("reason", e.target.value)}>
            <option value="">Any</option>
            {REASONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Supplier</span>
          <select className="input" value={params.get("supplier_id") ?? ""} onChange={(e) => setFilter("supplier_id", e.target.value)}>
            <option value="">Any</option>
            {(suppliers.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Age (days)</span>
          <select className="input" value={params.get("age") ?? ""} onChange={(e) => setFilter("age", e.target.value)}>
            <option value="">Any</option>
            {["0-7", "8-15", "16-30", "31-45", "45+"].map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        {Object.keys(views).length ? (
          <label className="field">
            <span>Saved views</span>
            <select className="input" value="" onChange={(e) => e.target.value && setParams(new URLSearchParams(views[e.target.value]))}>
              <option value="">Open a view</option>
              {Object.keys(views).map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {active.length ? (
          <button type="button" className="btn btn-ghost clear-btn" onClick={() => setParams(new URLSearchParams())}>
            <X size={14} aria-hidden="true" /> Clear filters
          </button>
        ) : null}
      </section>

      <p className="kbd-help muted">
        <Keyboard size={13} aria-hidden="true" /> <kbd>J</kbd>/<kbd>K</kbd> move · <kbd>Enter</kbd> open
        {me?.role === "approver" ? (
          <>
            {" "}
            · <kbd>A</kbd> approve (no-MFA invoices) · <kbd>R</kbd> open to reject
          </>
        ) : (
          <>
            {" "}
            · <kbd>F</kbd> open to review or flag
          </>
        )}{" "}
        · {rows.length} invoice{rows.length === 1 ? "" : "s"}
      </p>
      {notice ? (
        <p className="alert alert-info" role="status">
          {notice}
        </p>
      ) : null}

      <section className="panel table-panel">
        {rowsQ.isLoading ? (
          <div className="skeleton-rows" aria-busy="true">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="skeleton-row" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="empty">Nothing matches these filters.</p>
        ) : (
          <table className="table queue-table">
            <thead>
              <tr>
                {th("invoice_number", "Invoice")}
                {th("supplier_name", "Supplier")}
                {th("total", "Total", true)}
                <th scope="col">Decision</th>
                {th("status", "Status")}
                <th scope="col">Reasons</th>
                {th("age_days", "Age", true)}
                {th("msme_due_date", "MSME due")}
                <th scope="col">With</th>
              </tr>
            </thead>
            <tbody ref={tableRef}>
              {rows.map((r, i) => (
                <tr key={r.id} data-idx={i} className={i === cursor ? "is-cursor" : ""} onClick={() => setCursor(i)} aria-selected={i === cursor}>
                  <td>
                    <Link to={`/invoices/${r.id}`} className="mono row-link">
                      {r.invoice_number || `#${r.id}`}
                    </Link>
                  </td>
                  <td>{r.supplier_name}</td>
                  <td className="num num-col">{inr(r.total)}</td>
                  <td>
                    <DecisionChip decision={r.decision} />
                  </td>
                  <td>
                    <StatusChip status={r.status} />
                  </td>
                  <td className="reason-cell mono">{r.reasons.join(", ") || <span className="muted">-</span>}</td>
                  <td className="num num-col">{r.age_days} d</td>
                  <td>{r.msme_due_date ? fmtDate(r.msme_due_date) : <span className="muted">-</span>}</td>
                  <td className="muted">{r.current_owner}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
