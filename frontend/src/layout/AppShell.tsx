import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Banknote,
  BarChart3,
  BookOpen,
  Building2,
  Clock,
  Cpu,
  FileCheck2,
  FileText,
  Landmark,
  LayoutDashboard,
  Link2,
  ListChecks,
  Mail,
  LogOut,
  MessageCircle,
  Network,
  Search,
  PackageCheck,
  ShieldCheck,
  Stamp,
  TrendingUp,
  Upload,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { api, type Health } from "../api/client";
import { CommandPalette } from "../components/CommandPalette";
import { roleBadge, useAuth, type Role } from "../auth/AuthContext";
import { useTranslation } from "react-i18next";
import "./AppShell.css";

interface NavItem {
  to: string;
  label: string;
  /** i18n key for roles that see the shell in their own language (suppliers: English / Hindi). */
  i18n?: string;
  icon: LucideIcon;
  roles: Role[] | "all";
}

/** Role-aware menu. Items are added here as each screen is built (see PROGRESS.md). */
const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Workspace",
    items: [
      { to: "/", label: "Overview", i18n: "shell.overview", icon: LayoutDashboard, roles: "all" },
      { to: "/portal", label: "My invoices", i18n: "shell.my_invoices", icon: Wallet, roles: ["supplier"] },
      { to: "/dashboard", label: "Dashboard", icon: BarChart3, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/queue", label: "Work queue", icon: ListChecks, roles: ["clerk", "approver", "auditor", "admin"] },
      {
        to: "/invoices",
        label: "Invoices",
        icon: FileText,
        roles: ["clerk", "approver", "auditor", "admin"],
      },
      { to: "/upload", label: "Upload invoice", i18n: "shell.upload", icon: Upload, roles: ["supplier", "clerk"] },
      { to: "/inbox", label: "AP mailbox", icon: Mail, roles: ["clerk", "auditor", "admin"] },
      { to: "/assistant", label: "Payment assistant", icon: MessageCircle, roles: ["clerk"] },
      { to: "/receiving", label: "Receiving", icon: PackageCheck, roles: ["stores"] },
      { to: "/approvals", label: "Approvals", icon: Stamp, roles: ["approver"] },
      { to: "/payments", label: "Payments", icon: Banknote, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/bank-changes", label: "Bank changes", icon: Landmark, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/suppliers", label: "Supplier risk", icon: Building2, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/controls", label: "Controls report", icon: FileCheck2, roles: ["auditor", "admin"] },
      { to: "/audit", label: "Audit chain", icon: Link2, roles: ["auditor", "admin"] },
      { to: "/admin/demo", label: "Demo controls", icon: Clock, roles: ["admin"] },
    ],
  },
  {
    section: "About Duly",
    items: [
      { to: "/impact", label: "Impact", icon: TrendingUp, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/trust", label: "Trust & controls", icon: ShieldCheck, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/architecture", label: "Architecture", icon: Network, roles: ["clerk", "approver", "auditor", "admin"] },
      { to: "/assumptions", label: "Scenario & assumptions", icon: BookOpen, roles: ["clerk", "approver", "auditor", "admin"] },
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
  const { i18n } = useTranslation();
  if (!me) return null;
  // Suppliers get the shell in their chosen language; staff screens are English.
  const supplier = me.role === "supplier";
  const t = i18n.getFixedT(supplier ? i18n.language : "en");

  const entity = me.supplier ? me.supplier.name : "Plant X Polymers Pvt Ltd · Dahej";
  const sections = NAV.map((s) => ({
    ...s,
    section: s.section === "Workspace" ? t("shell.workspace") : s.section,
    items: s.items
      .filter((i) => i.roles === "all" || i.roles.includes(me.role))
      .map((i) => ({ ...i, label: i.i18n ? t(i.i18n) : i.label })),
  })).filter((s) => s.items.length > 0);

  return (
    <div className="shell" lang={supplier && i18n.language === "hi" ? "hi" : "en"}>
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
        <p className="sidebar-foot">
          {t("shell.footer")}{" "}
          {me.role === "supplier" || me.role === "stores" ? (
            <span>{t("shell.ai_use")}</span>
          ) : (
            <Link to="/trust#ai-use" className="sidebar-foot-link">AI use declared</Link>
          )}
        </p>
      </aside>

      <header className="topbar">
        <div className="topbar-entity" title="Legal entity">
          <Building2 size={16} aria-hidden="true" />
          <span>{entity}</span>
        </div>
        <div className="topbar-right">
          <button
            type="button"
            className="btn palette-trigger"
            onClick={() => window.dispatchEvent(new Event("duly:open-palette"))}
            aria-keyshortcuts="Control+K Meta+K"
          >
            <Search size={15} aria-hidden="true" />
            <span className="palette-trigger-text">{t("shell.search")}</span>
            <kbd>Ctrl K</kbd>
          </button>
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
            <span>{t("shell.sign_out")}</span>
          </button>
        </div>
      </header>

      <main id="main" className="content" tabIndex={0}>
        <Outlet />
      </main>
      <CommandPalette role={me.role} nav={sections.flatMap((s) => s.items)} />
    </div>
  );
}
