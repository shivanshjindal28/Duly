import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Lock, XCircle } from "lucide-react";
import { api, type Health } from "../api/client";
import { roleBadge, useAuth } from "../auth/AuthContext";
import { DulyRail } from "../components/DulyRail";
import "./OverviewPage.css";

/** Landing page per role: who you are, what your role can and cannot do (from the server), system status. */
export function OverviewPage() {
  const { me } = useAuth();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/health") });
  if (!me) return null;

  return (
    <div className="overview">
      <header className="page-head">
        <p className="label">{roleBadge(me)}</p>
        <h1>Welcome, {me.full_name.split(" ")[0]}</h1>
        <p className="muted">
          {me.title}
          {me.supplier ? ` · Vendor ${me.supplier.code}` : " · Plant X Polymers Pvt Ltd"}
        </p>
      </header>

      <section className="panel overview-rail" aria-labelledby="rail-title">
        <h2 id="rail-title" className="label">
          The Duly lifecycle
        </h2>
        <DulyRail completed={0} showDocs />
        <p className="muted overview-rail-note">
          Every invoice moves through these five stops. Each stop is checked by a deterministic rule, and every
          decision is written to the audit trail.
        </p>
      </section>

      <div className="overview-grid">
        <section className="panel overview-card" aria-labelledby="access-title">
          <h2 id="access-title" className="label">
            Your access
          </h2>
          <p className="muted overview-card-note">Enforced on the server for every request, not just hidden in the UI.</p>
          <ul className="access-list">
            {me.permissions.can.map((p) => (
              <li key={p}>
                <CheckCircle2 size={15} className="ok" aria-hidden="true" />
                <span>{p}</span>
              </li>
            ))}
          </ul>
          {me.permissions.cannot.length > 0 ? (
            <>
              <h3 className="access-sub">Not allowed for this role</h3>
              <ul className="access-list">
                {me.permissions.cannot.map((p) => (
                  <li key={p}>
                    <XCircle size={15} className="no" aria-hidden="true" />
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>

        <section className="panel overview-card" aria-labelledby="status-title">
          <h2 id="status-title" className="label">
            System status
          </h2>
          {health.data ? (
            <dl className="status-list">
              <div>
                <dt>Database</dt>
                <dd>
                  {health.data.db === "ok" ? (
                    <span className="chip chip-approve">
                      <CheckCircle2 size={13} aria-hidden="true" /> OK
                    </span>
                  ) : (
                    <span className="chip chip-block">
                      <XCircle size={13} aria-hidden="true" /> Error
                    </span>
                  )}
                </dd>
              </div>
              <div>
                <dt>AI mode</dt>
                <dd>
                  <span className="chip chip-neutral">
                    <Circle size={10} aria-hidden="true" /> {health.data.ai_mode}
                  </span>
                </dd>
              </div>
              <div>
                <dt>Policy version</dt>
                <dd className="num">v{health.data.policy_version ?? "-"}</dd>
              </div>
              <div>
                <dt>MFA</dt>
                <dd>
                  {me.mfa_enabled ? (
                    <span className="chip chip-approve">
                      <Lock size={12} aria-hidden="true" /> Enrolled
                    </span>
                  ) : (
                    <span className="chip chip-neutral">Not required for this role</span>
                  )}
                </dd>
              </div>
              <div>
                <dt>Build</dt>
                <dd className="num">v{health.data.version}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">Checking...</p>
          )}
        </section>
      </div>
    </div>
  );
}
