import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Building, CornerDownLeft, FileText, Search, Zap, type LucideIcon } from "lucide-react";
import { api } from "../api/client";
import type { Role } from "../auth/AuthContext";
import { inr } from "../lib/format";
import "./CommandPalette.css";

export interface PaletteNavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

interface Command {
  id: string;
  group: "Go to" | "Actions" | "Invoices" | "Suppliers";
  label: string;
  hint?: string;
  icon: LucideIcon;
  keywords?: string;
  run: () => void;
}

interface InvoiceRow { id: number; invoice_number: string; supplier_name: string | null; total: string; status: string }
interface SupplierRow { id: number; name: string; code: string; category: string }

const STAFF: Role[] = ["clerk", "approver", "auditor", "admin"];
const MAX_PER_GROUP = 6;

function score(text: string, q: string): number {
  if (!q) return 1;
  const t = text.toLowerCase();
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.every((w) => t.includes(w))) return 0;
  return t.startsWith(words[0]) ? 3 : t.split(/[\s/·-]+/).some((p) => p.startsWith(words[0])) ? 2 : 1;
}

/**
 * Ctrl/Cmd+K command palette: jump to a page, an invoice (by number or supplier), a supplier's
 * queue, or run an action. Everything offered is already allowed for the role (the server
 * still enforces it). Combobox + listbox pattern, fully keyboard driven.
 */
export function CommandPalette({ role, nav }: { role: Role; nav: PaletteNavItem[] }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("duly:open-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("duly:open-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      returnFocus.current = document.activeElement as HTMLElement | null;
      setQuery("");
      setActive(0);
      setTimeout(() => input.current?.focus(), 0);
    } else {
      returnFocus.current?.focus?.();
    }
  }, [open]);

  const canInvoices = role !== "stores";
  const invoices = useQuery({
    queryKey: ["palette-invoices"],
    queryFn: () => api<InvoiceRow[]>("/invoices"),
    enabled: open && canInvoices,
    staleTime: 30_000,
  });
  const suppliers = useQuery({
    queryKey: ["palette-suppliers"],
    queryFn: () => api<SupplierRow[]>("/suppliers"),
    enabled: open && STAFF.includes(role),
    staleTime: 60_000,
  });

  const commands = useMemo<Command[]>(() => {
    const go = (to: string) => () => navigate(to);
    const out: Command[] = nav.map((n) => ({ id: `nav:${n.to}`, group: "Go to", label: n.label, icon: n.icon, run: go(n.to) }));
    if (role === "auditor" || role === "admin") {
      out.push({ id: "act:verify", group: "Actions", label: "Verify audit chain", icon: Zap, keywords: "audit hash tamper", run: go("/audit?verify=1") });
    }
    if (role === "admin") {
      out.push({ id: "act:reset", group: "Actions", label: "Reset demo data", icon: Zap, keywords: "demo seed", run: go("/admin/demo") });
      out.push({ id: "act:ai", group: "Actions", label: "Switch AI mode (kill switch)", icon: Zap, keywords: "offline live cached", run: go("/admin/demo") });
    }
    if (role === "supplier" || role === "clerk") {
      out.push({ id: "act:upload", group: "Actions", label: "Upload an invoice", icon: Zap, keywords: "pdf photo", run: go("/upload") });
    }
    if (STAFF.includes(role)) {
      out.push({ id: "act:open", group: "Actions", label: "Open exceptions", icon: Zap, keywords: "blocked flagged queue", run: go("/queue?status=open") });
    }
    for (const i of invoices.data ?? []) {
      out.push({
        id: `inv:${i.id}`, group: "Invoices", label: i.invoice_number, icon: FileText,
        hint: `${i.supplier_name ?? ""} · ${inr(i.total)} · ${i.status.replace("_", " ")}`,
        keywords: i.supplier_name ?? "", run: go(`/invoices/${i.id}`),
      });
    }
    for (const s of suppliers.data ?? []) {
      out.push({
        id: `sup:${s.id}`, group: "Suppliers", label: s.name, icon: Building, hint: `${s.code} · ${s.category} · all invoices`,
        keywords: s.code, run: go(`/queue?status=all&supplier_id=${s.id}`),
      });
    }
    return out;
  }, [nav, role, invoices.data, suppliers.data, navigate]);

  const results = useMemo(() => {
    const q = query.trim();
    const groups: Command["group"][] = ["Go to", "Actions", "Invoices", "Suppliers"];
    const list: Command[] = [];
    for (const g of groups) {
      // Invoices and suppliers appear once the user types (hundreds of them otherwise).
      if (!q && (g === "Invoices" || g === "Suppliers")) continue;
      list.push(...commands
        .filter((c) => c.group === g)
        .map((c) => ({ c, s: Math.max(score(c.label, q), score(`${c.label} ${c.keywords ?? ""}`, q) ? 1 : 0) }))
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s)
        .slice(0, MAX_PER_GROUP)
        .map((x) => x.c));
    }
    return list;
  }, [commands, query]);

  useEffect(() => setActive(0), [query]);

  if (!open) return null;
  const run = (c: Command | undefined) => {
    if (!c) return;
    setOpen(false);
    c.run();
  };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(results[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    } else if (e.key === "Tab") {
      e.preventDefault(); // focus stays in the dialog
    }
  };

  let lastGroup = "";
  return (
    <div className="palette-backdrop" onMouseDown={() => setOpen(false)}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}>
        <div className="palette-search">
          <Search size={16} aria-hidden="true" />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Go to a page, an invoice number, a supplier..."
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={results[active] ? `palette-${results[active].id}` : undefined}
            aria-autocomplete="list"
            aria-label="Search pages, invoices, suppliers and actions"
          />
          <kbd>Esc</kbd>
        </div>
        <ul id="palette-list" role="listbox" aria-label="Results" className="palette-list">
          {results.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <li key={c.id} role="presentation">
                {header ? <div className="palette-group" role="presentation">{header}</div> : null}
                <div
                  id={`palette-${c.id}`}
                  role="option"
                  aria-selected={i === active}
                  className={`palette-item${i === active ? " active" : ""}`}
                  onMouseMove={() => setActive(i)}
                  onClick={() => run(c)}
                >
                  <c.icon size={15} aria-hidden="true" />
                  <span className={c.group === "Invoices" ? "mono" : ""}>{c.label}</span>
                  {c.hint ? <span className="palette-hint">{c.hint}</span> : null}
                  {i === active ? <CornerDownLeft size={13} aria-hidden="true" className="palette-enter" /> : null}
                </div>
              </li>
            );
          })}
          {results.length === 0 ? (
            <li role="presentation" className="palette-empty">
              {invoices.isLoading ? "Loading invoices..." : "Nothing matches. Try an invoice number like INV/0042 or a supplier name."}
            </li>
          ) : null}
        </ul>
        <p className="palette-foot">
          <kbd>↑</kbd> <kbd>↓</kbd> to move · <kbd>Enter</kbd> to open · <kbd>Ctrl</kbd>+<kbd>K</kbd> anywhere
        </p>
      </div>
    </div>
  );
}
