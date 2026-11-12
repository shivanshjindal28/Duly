import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, LogIn } from "lucide-react";
import { api, ApiError, type Health } from "../api/client";
import { ROLE_LABEL, useAuth, type Role } from "../auth/AuthContext";
import { DulyRail } from "../components/DulyRail";
import "./LoginPage.css";

interface Persona {
  email: string;
  full_name: string;
  title: string;
  role: Role;
  approver_level: number | null;
  supplier_name: string | null;
}

const ROLE_ORDER: Role[] = ["supplier", "clerk", "approver", "stores", "auditor", "admin"];

export function LoginPage() {
  const { me, login, demoLogin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/health") });
  const personas = useQuery({
    queryKey: ["demo-personas"],
    queryFn: () => api<Persona[]>("/auth/demo-personas"),
    enabled: health.data?.demo_mode === true,
  });

  if (me) return <Navigate to={from} replace />;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      navigate(from, { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Cannot reach the Duly server. Is the backend running?");
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void run(() => login(email.trim(), password));
  }

  const grouped = ROLE_ORDER.map((role) => ({
    role,
    people: (personas.data ?? []).filter((p) => p.role === role),
  })).filter((g) => g.people.length > 0);

  return (
    <div className="login">
      <section className="login-brand" aria-label="About Duly">
        <div className="login-brand-top">
          <img src="/duly.svg" alt="" width={36} height={36} />
          <span className="login-wordmark">Duly</span>
        </div>
        <div className="login-brand-body">
          <p className="label login-eyebrow">Smart procure-to-pay · Plant X</p>
          <h1 className="login-tagline">Every invoice, duly done.</h1>
          <p className="login-lede">
            Duly reads supplier invoices, checks them against purchase orders and goods receipts, and approves,
            flags or blocks each one with a clear reason. Rules decide. AI only reads and explains.
          </p>
          <DulyRail completed={3} tone="dark" showDocs />
        </div>
        <p className="login-foot">Built for LYB Mumbai Hackathon 2026 · Plant X is a fictional company · All data is synthetic</p>
      </section>

      <main className="login-main">
        <div className="login-card">
          <h2>Sign in</h2>
          <p className="muted">Use your Plant X or supplier portal account.</p>

          <form onSubmit={onSubmit} className="login-form" noValidate>
            <label className="field">
              <span>Email</span>
              <input
                className="input"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            {error ? (
              <div className="alert alert-error" role="alert">
                <AlertTriangle size={16} aria-hidden="true" />
                <span>{error}</span>
              </div>
            ) : null}
            <button className="btn btn-primary" type="submit" disabled={busy || !email || !password}>
              <LogIn size={16} aria-hidden="true" /> Sign in
            </button>
          </form>

          {health.data?.demo_mode && grouped.length > 0 ? (
            <section className="login-personas" aria-labelledby="personas-title">
              <div className="login-personas-head">
                <h3 id="personas-title" className="label">Demo personas</h3>
                <span className="chip chip-flag">Demo mode</span>
              </div>
              {grouped.map((g) => (
                <div key={g.role} className="persona-group">
                  <p className="persona-role">{ROLE_LABEL[g.role]}</p>
                  <ul>
                    {g.people.map((p) => (
                      <li key={p.email}>
                        <button
                          type="button"
                          className="persona"
                          disabled={busy}
                          onClick={() => void run(() => demoLogin(p.email))}
                        >
                          <span className="persona-name">{p.full_name}</span>
                          <span className="persona-sub">{p.supplier_name ?? p.title}</span>
                          <ArrowRight size={14} aria-hidden="true" className="persona-go" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          ) : null}
        </div>
      </main>
    </div>
  );
}
