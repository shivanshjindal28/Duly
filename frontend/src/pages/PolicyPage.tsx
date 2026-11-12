import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, History, Lock, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import { api, ApiError } from "../api/client";
import { fmtDateTime, inr } from "../lib/format";
import "./PolicyPage.css";

interface FieldDef {
  path: string;
  section: string;
  label: string;
  unit: "%" | "INR" | "hours" | "days" | "ratio";
  min: number;
  max: number;
  integer: boolean;
  help: string;
}

interface Version {
  version: number;
  reason: string;
  active: boolean;
  created_at: string;
  created_by: string | null;
  changed: Record<string, { from: number | null; to: number | null }>;
}

interface PolicyOut {
  version: number;
  can_edit: boolean;
  fields: FieldDef[];
  values: Record<string, number | null>;
  statutory: { label: string; unit: string; value: number }[];
  history: Version[];
}

function show(f: FieldDef | undefined, v: number | null | undefined): string {
  if (v === null || v === undefined) return "-";
  if (!f) return String(v);
  if (f.unit === "INR") return inr(v).replace(".00", "");
  if (f.unit === "%") return `${v}%`;
  if (f.unit === "ratio") return v.toFixed(2);
  return `${v} ${f.unit}`;
}

/** Policy: tolerances, approval limits and thresholds as versioned data. Admin edits; everyone on staff can read. */
export function PolicyPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["policy"], queryFn: () => api<PolicyOut>("/policy") });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState<number | null>(null);

  const reset = () => {
    if (!q.data) return;
    setDraft(Object.fromEntries(Object.entries(q.data.values).map(([k, v]) => [k, v === null ? "" : String(v)])));
  };
  useEffect(reset, [q.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const byPath = useMemo(() => Object.fromEntries((q.data?.fields ?? []).map((f) => [f.path, f])), [q.data]);
  const changes = useMemo(() => {
    const out: Record<string, number> = {};
    if (!q.data) return out;
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v);
      if (v.trim() !== "" && !Number.isNaN(n) && n !== q.data.values[k]) out[k] = n;
    }
    return out;
  }, [draft, q.data]);
  const nChanged = Object.keys(changes).length;

  const save = useMutation({
    mutationFn: () => api<PolicyOut>("/policy", { method: "POST", body: JSON.stringify({ changes, reason }) }),
    onSuccess: (d) => {
      qc.setQueryData(["policy"], d);
      setSaved(d.version);
      setReason("");
    },
  });

  if (q.isLoading) return <div className="page"><p className="muted">Loading policy...</p></div>;
  if (!q.data) return <div className="page alert alert-error">Could not load the policy.</div>;
  const d = q.data;
  const sections = [...new Set(d.fields.map((f) => f.section))];

  return (
    <div className="page policy">
      <header className="page-head">
        <p className="label">Configuration · versioned data, not code</p>
        <h1>
          <SlidersHorizontal size={20} aria-hidden="true" /> Policy <span className="chip chip-info">v{d.version} active</span>
        </h1>
        <p className="muted">
          Tolerances, approval limits and thresholds the rules engine and workflow run on. A change creates a new version;
          older versions are kept, and every decision records the version that made it. New matches, approvals and payment
          runs use the new version at once; decisions already made are not changed.
          {d.can_edit ? "" : " Only an administrator can change it."}
        </p>
      </header>

      <form
        className="policy-form"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {sections.map((s) => (
          <fieldset key={s} className="panel policy-section">
            <legend>{s}</legend>
            {d.fields
              .filter((f) => f.section === s)
              .map((f) => {
                const id = `pol-${f.path.replace(/\./g, "-")}`;
                const changed = f.path in changes;
                return (
                  <div key={f.path} className={`policy-row${changed ? " changed" : ""}`}>
                    <label htmlFor={id}>
                      <span className="policy-label">{f.label}</span>
                      {f.help ? <span className="muted small">{f.help}</span> : null}
                    </label>
                    <div className="policy-input">
                      <input
                        id={id}
                        className="input num"
                        type="number"
                        inputMode="decimal"
                        min={f.min}
                        max={f.max}
                        step={f.integer ? 1 : f.unit === "ratio" ? 0.01 : 0.01}
                        value={draft[f.path] ?? ""}
                        disabled={!d.can_edit}
                        onChange={(e) => setDraft({ ...draft, [f.path]: e.target.value })}
                        aria-describedby={`${id}-unit`}
                      />
                      <span id={`${id}-unit`} className="policy-unit">{f.unit === "ratio" ? "0-1" : f.unit}</span>
                    </div>
                    {changed ? (
                      <span className="policy-was small">was {show(f, d.values[f.path])}</span>
                    ) : (
                      <span className="policy-was" />
                    )}
                  </div>
                );
              })}
          </fieldset>
        ))}

        <fieldset className="panel policy-section">
          <legend>
            <Lock size={13} aria-hidden="true" /> Statutory (not editable)
          </legend>
          {d.statutory.map((s) => (
            <div key={s.label} className="policy-row">
              <span className="policy-label">{s.label}</span>
              <span className="num">{s.value} {s.unit}</span>
              <span className="muted small">MSMED Act s.15: law, not policy.</span>
            </div>
          ))}
        </fieldset>

        {d.can_edit ? (
          <div className="panel policy-save">
            <label className="field">
              <span>Reason for the change (goes into the audit trail)</span>
              <input className="input" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Finance committee raised the touchless limit after the Q3 review" />
            </label>
            <div className="policy-actions">
              <button type="submit" className="btn btn-primary" disabled={!nChanged || reason.trim().length < 10 || save.isPending}>
                <Save size={15} aria-hidden="true" /> Save as v{d.version + 1} ({nChanged} change{nChanged === 1 ? "" : "s"})
              </button>
              <button type="button" className="btn" onClick={reset} disabled={!nChanged}>
                <RotateCcw size={15} aria-hidden="true" /> Discard
              </button>
              {nChanged && reason.trim().length < 10 ? <span className="muted small">Write a reason of at least 10 characters.</span> : null}
            </div>
            {save.isError ? (
              <p className="alert alert-error" role="alert">{save.error instanceof ApiError ? save.error.message : "Could not save."}</p>
            ) : null}
            {saved && !save.isError ? (
              <p className="alert alert-success" role="status">
                <CheckCircle2 size={14} aria-hidden="true" /> Policy v{saved} is active. The change is in the audit trail.
              </p>
            ) : null}
          </div>
        ) : null}
      </form>

      <section className="panel table-panel" aria-labelledby="pol-hist">
        <h2 id="pol-hist" className="panel-title">
          <History size={15} aria-hidden="true" /> Version history
        </h2>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">When</th>
              <th scope="col">By</th>
              <th scope="col">Reason</th>
              <th scope="col">What changed</th>
            </tr>
          </thead>
          <tbody>
            {d.history.map((v) => (
              <tr key={v.version}>
                <td>
                  v{v.version} {v.active ? <span className="chip chip-approve">active</span> : null}
                </td>
                <td>{fmtDateTime(v.created_at)}</td>
                <td>{v.created_by ?? "-"}</td>
                <td>{v.reason}</td>
                <td>
                  {Object.keys(v.changed).length === 0 ? (
                    <span className="muted">Initial policy</span>
                  ) : (
                    <ul className="policy-diff">
                      {Object.entries(v.changed).map(([k, c]) => (
                        <li key={k}>
                          {byPath[k]?.label ?? k}: {show(byPath[k], c.from)} → <strong>{show(byPath[k], c.to)}</strong>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
