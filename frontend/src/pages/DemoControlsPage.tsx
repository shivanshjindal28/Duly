import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, DatabaseZap, FastForward, Loader2, RotateCcw, ShieldX, Sparkles } from "lucide-react";
import { api, ApiError } from "../api/client";
import { fmtDateTime } from "../lib/format";

interface ClockOut {
  now: string;
  offset_hours: number;
  escalated: number;
}

interface AiModeOut {
  configured: string;
  effective: "live" | "cached" | "offline";
  overridden: boolean;
  key_configured: boolean;
  cached_extractions: number;
}

const AI_MODES: { mode: string; title: string; text: string }[] = [
  { mode: "live", title: "Live", text: "Claude reads each document (needs ANTHROPIC_API_KEY and internet)." },
  { mode: "cached", title: "Cached", text: "Replays earlier AI readings by file hash; no network. New files fall back to OCR." },
  { mode: "offline", title: "Offline", text: "AI kill switch: local OCR and rules only. The whole demo works like this." },
  { mode: "auto", title: "Auto", text: "Live if an API key is configured, otherwise offline." },
];

/** Admin demo controls (DEMO_MODE only): reset, AI mode, business clock, tamper demo. */
export function DemoControlsPage() {
  const qc = useQueryClient();
  const [confirmReset, setConfirmReset] = useState(false);
  const aiMode = useQuery({ queryKey: ["ai-mode"], queryFn: () => api<AiModeOut>("/admin/ai-mode") });
  const setAi = useMutation({
    mutationFn: (mode: string) => api<AiModeOut>("/admin/ai-mode", { method: "POST", body: JSON.stringify({ mode }) }),
    onSuccess: (m) => {
      qc.setQueryData(["ai-mode"], m);
      qc.invalidateQueries({ queryKey: ["health"] });
    },
  });
  const resetDemo = useMutation({
    mutationFn: () => api<{ counts: Record<string, number>; seconds: number }>("/admin/reset-demo", { method: "POST" }),
    onSuccess: () => {
      setConfirmReset(false);
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  });
  const clock = useQuery({ queryKey: ["clock"], queryFn: () => api<ClockOut>("/admin/clock") });
  const advance = useMutation({
    mutationFn: (hours: number) => api<ClockOut>("/admin/clock/advance", { method: "POST", body: JSON.stringify({ hours }) }),
    onSuccess: (c) => {
      qc.setQueryData(["clock"], c);
      qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "clock" && q.queryKey[0] !== "me" });
    },
  });
  const reset = useMutation({
    mutationFn: () => api<ClockOut>("/admin/clock/reset", { method: "POST" }),
    onSuccess: (c) => qc.setQueryData(["clock"], c),
  });
  const tamper = useMutation({
    mutationFn: (op: "tamper-demo" | "tamper-restore") =>
      api<{ event_id: number; change?: string; restored?: boolean }>(`/admin/${op}`, { method: "POST" }),
  });
  const last = advance.data;
  return (
    <div className="page" style={{ maxWidth: 720 }}>
      <header className="page-head">
        <p className="label">Demo mode</p>
        <h1>Demo controls</h1>
        <p className="muted">Reset the demo, switch the AI, and move the business clock to show SLA escalation, cooling periods and MSME countdowns.</p>
      </header>
      <section className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }} aria-labelledby="reset-title">
        <h2 id="reset-title" className="label">Reset demo data</h2>
        <p className="muted">
          Deletes every invoice, upload and audit event, then rebuilds the demo: master data, 68 POs and about 250
          invoices of history over 90 days, replayed through the real rules and workflow. Takes about 25 seconds. You
          stay signed in; the clock returns to real time; the AI mode is kept.
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {!confirmReset ? (
            <button type="button" className="btn btn-danger" disabled={resetDemo.isPending} onClick={() => setConfirmReset(true)}>
              <DatabaseZap size={15} aria-hidden="true" /> Reset demo data
            </button>
          ) : (
            <>
              <button type="button" className="btn btn-danger" disabled={resetDemo.isPending} onClick={() => resetDemo.mutate()}>
                {resetDemo.isPending ? <Loader2 size={15} className="spin" aria-hidden="true" /> : <DatabaseZap size={15} aria-hidden="true" />}
                {resetDemo.isPending ? "Resetting... about 25 seconds" : "Yes, delete everything and reseed"}
              </button>
              {!resetDemo.isPending ? (
                <button type="button" className="btn btn-ghost" onClick={() => setConfirmReset(false)}>
                  Cancel
                </button>
              ) : null}
            </>
          )}
        </div>
        {resetDemo.data ? (
          <p className="alert alert-success" role="status">
            {resetDemo.data.counts.restored_snapshot ? (
              <>Demo restored to its staged state in {resetDemo.data.seconds.toFixed(0)} s (history plus the background scenarios). The live-demo files are ready to upload.</>
            ) : (
              <>
                Demo reset in {resetDemo.data.seconds.toFixed(0)} s: {resetDemo.data.counts.history_invoices} history invoices,{" "}
                {resetDemo.data.counts.purchase_orders} POs, {resetDemo.data.counts.history_payment_runs} payment runs. The 12
                scenario files in demo/invoices are ready to upload.
              </>
            )}
          </p>
        ) : null}
        {resetDemo.isError ? (
          <p className="alert alert-error" role="alert">
            {resetDemo.error instanceof ApiError ? resetDemo.error.message : "Reset failed."}
          </p>
        ) : null}
      </section>
      <section className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }} aria-labelledby="ai-title">
        <h2 id="ai-title" className="label">
          <Sparkles size={13} aria-hidden="true" /> AI mode
        </h2>
        <p className="muted">
          Now: <strong>{aiMode.data ? aiMode.data.effective : "..."}</strong>
          {aiMode.data ? ` (setting: ${aiMode.data.configured}${aiMode.data.overridden ? ", set here" : ", from .env"}; ${aiMode.data.cached_extractions} cached AI readings)` : ""}
          . Whatever the mode, the rules engine makes every decision.
        </p>
        <div role="radiogroup" aria-label="AI mode" style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
          {AI_MODES.map((m) => {
            const selected = aiMode.data?.configured === m.mode;
            const disabled = setAi.isPending || (m.mode === "live" && aiMode.data !== undefined && !aiMode.data.key_configured);
            return (
              <button
                key={m.mode}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={disabled}
                className={`btn ${selected ? "btn-primary" : ""}`}
                style={{ height: "auto", padding: "10px 12px", flexDirection: "column", alignItems: "flex-start", textAlign: "left", gap: 2 }}
                onClick={() => setAi.mutate(m.mode)}
              >
                <strong>{m.title}</strong>
                <span style={{ fontSize: 12, fontWeight: 400, opacity: 0.9 }}>{m.text}</span>
              </button>
            );
          })}
        </div>
        {aiMode.data?.overridden ? (
          <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start" }} disabled={setAi.isPending} onClick={() => setAi.mutate("default")}>
            <RotateCcw size={14} aria-hidden="true" /> Use the .env setting
          </button>
        ) : null}
        {setAi.isError ? (
          <p className="alert alert-error" role="alert">
            {setAi.error instanceof ApiError ? setAi.error.message : "Could not change the AI mode."}
          </p>
        ) : null}
      </section>
      <section className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
        <p style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Clock size={16} aria-hidden="true" />
          <span>
            Business time: <strong>{clock.data ? fmtDateTime(clock.data.now) : "..."}</strong>
            {clock.data && clock.data.offset_hours ? (
              <span className="muted"> (+{(clock.data.offset_hours / 24).toFixed(1)} days ahead of real time)</span>
            ) : null}
          </span>
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {[24, 49, 24 * 7].map((h) => (
            <button key={h} type="button" className="btn" disabled={advance.isPending} onClick={() => advance.mutate(h)}>
              <FastForward size={15} aria-hidden="true" /> +{h < 48 ? `${h} h` : h === 49 ? "49 h (past SLA)" : "7 days"}
            </button>
          ))}
          <button type="button" className="btn btn-ghost" disabled={reset.isPending} onClick={() => reset.mutate()}>
            <RotateCcw size={15} aria-hidden="true" /> Reset to real time
          </button>
        </div>
        {last ? (
          <p className="alert alert-info" role="status">
            Clock advanced. {last.escalated} overdue approval step{last.escalated === 1 ? "" : "s"} escalated to the next
            level.
          </p>
        ) : null}
      </section>
      <section className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 className="label">Tamper demo</h2>
        <p className="muted">
          Edits one audit row directly in the database, bypassing Duly (what an insider with DB access could do). Then
          open Audit chain and press Verify: Duly shows the exact event where the chain breaks. Same as{" "}
          <span className="mono">python scripts/tamper_demo.py</span>.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn btn-danger" disabled={tamper.isPending} onClick={() => tamper.mutate("tamper-demo")}>
            <ShieldX size={15} aria-hidden="true" /> Run tamper demo
          </button>
          <button type="button" className="btn" disabled={tamper.isPending} onClick={() => tamper.mutate("tamper-restore")}>
            <RotateCcw size={15} aria-hidden="true" /> Restore original row
          </button>
        </div>
        {tamper.data ? (
          <p className="alert alert-info" role="status">
            {tamper.data.restored
              ? `Event #${tamper.data.event_id} restored. The chain verifies again.`
              : `Event #${tamper.data.event_id} edited directly in the database (${tamper.data.change}).`}
          </p>
        ) : null}
        {tamper.isError ? (
          <p className="alert alert-error" role="alert">
            {tamper.error instanceof ApiError ? tamper.error.message : "Failed."}
          </p>
        ) : null}
      </section>
    </div>
  );
}
