import { NavLink, Outlet, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Building2,
  Clock,
  Cpu,
  FileText,
  LayoutDashboard,
  Link2,
  ListChecks,
  LogOut,
  PackageCheck,
  ShieldCheck,
  Stamp,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { api, type Health } from "../api/client";
import { roleBadge, useAuth, type Role } from "../auth/AuthContext";
import "./AppShell.css";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles: Role[] | "all";
}

/** Role-aware menu. Items are added here as each screen is built (see PROGRESS.md). */
const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Workspace",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, roles: "all" },
      { to: "/dashboard", label: "Dashboard", icon: BarChart3, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/queue", label: "Work queue", icon: ListChecks, roles: ["clerk", "approver", "auditor", "admin"] },
      {
        to: "/invoices",
        label: "Invoices",
        icon: FileText,
        roles: ["supplier", "clerk", "approver", "auditor", "admin"],
      },
      { to: "/upload", label: "Upload invoice", icon: Upload, roles: ["supplier", "clerk"] },
      { to: "/receiving", label: "Receiving", icon: PackageCheck, roles: ["stores"] },
      { to: "/approvals", label: "Approvals", icon: Stamp, roles: ["approver"] },
      { to: "/audit", label: "Audit chain", icon: Link2, roles: ["auditor", "admin"] },
      { to: "/admin/demo", label: "Demo controls", icon: Clock, roles: ["admin"] },
    ],
  },
];

const AI_MODE_TEXT: Record<Health["ai_mode"], string> = {
  live: "AI: live",
  cached: "AI: cached",
  offline: "AI: offline (OCR)",
};

export function AppShell() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/health"), refetchInterval: 30_000 });
  if (!me) return null;

  const entity = me.supplier ? me.supplier.name : "Plant X Polymers Pvt Ltd · Dahej";
  const sections = NAV.map((s) => ({
    ...s,
    items: s.items.filter((i) => i.roles === "all" || i.roles.includes(me.role)),
  })).filter((s) => s.items.length > 0);

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="sidebar-brand">
          <img src="/duly.svg" alt="" width={28} height={28} />
          <div>
            <div className="sidebar-wordmark">Duly</div>
            <div className="sidebar-tag">Every invoice, duly done.</div>
          </div>
        </div>
        <nav>
          {sections.map((s) => (
            <div key={s.section} className="nav-section">
              <p className="nav-section-label">{s.section}</p>
              <ul>
                {s.items.map((item) => (
                  <li key={item.to}>
                    <NavLink to={item.to} end={item.to === "/"} className="nav-link">
                      <item.icon size={16} aria-hidden="true" />
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <p className="sidebar-foot">Plant X is a fictional company. Synthetic data only.</p>
      </aside>

      <header className="topbar">
        <div className="topbar-entity" title="Legal entity">
          <Building2 size={16} aria-hidden="true" />
          <span>{entity}</span>
        </div>
        <div className="topbar-right">
          {health.data ? (
            <span className="chip chip-neutral" title={`Policy v${health.data.policy_version ?? "-"}`}>
              <Cpu size={13} aria-hidden="true" />
              {AI_MODE_TEXT[health.data.ai_mode]}
            </span>
          ) : null}
          <span className="chip chip-info">
            <ShieldCheck size={13} aria-hidden="true" />
            {roleBadge(me)}
          </span>
          <span className="topbar-user">{me.full_name}</span>
          <button
            type="button"
            className="btn btn-ghost topbar-logout"
            onClick={async () => {
              await logout();
              navigate("/login", { replace: true });
            }}
          >
            <LogOut size={16} aria-hidden="true" />
            <span>Sign out</span>
          </button>
        </div>
      </header>

      <main id="main" className="content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
