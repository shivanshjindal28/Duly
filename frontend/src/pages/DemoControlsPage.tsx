import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, FastForward, RotateCcw, ShieldX } from "lucide-react";
import { api, ApiError } from "../api/client";
import { fmtDateTime } from "../lib/format";

interface ClockOut {
  now: string;
  offset_hours: number;
  escalated: number;
}

/** Admin demo controls (DEMO_MODE only): the business clock behind SLA timers and countdowns. */
export function DemoControlsPage() {
  const qc = useQueryClient();
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
        <p className="muted">Move the business clock forward to show SLA escalation, cooling periods and MSME countdowns.</p>
      </header>
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
