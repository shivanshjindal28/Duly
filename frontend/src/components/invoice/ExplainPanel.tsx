import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MessageSquareText, ShieldCheck, UserRound } from "lucide-react";
import i18n from "../../i18n";
import { api } from "../../api/client";
import { inr } from "../../lib/format";
import "./ExplainPanel.css";

interface Point {
  code: string;
  title: string;
  severity: "block" | "flag";
  what: string;
  why: string;
  fix: string;
  who: string;
}

interface SupplierTodo {
  code: string;
  severity: string;
  you_act: boolean;
  params: Record<string, string>;
}

interface Explanation {
  decision: string;
  headline: string;
  points: Point[];
  notes: string[];
  next_step: string;
  footer: string;
  source: string;
  supplier_view: SupplierTodo[];
}

function supplierText(x: SupplierTodo, lang: "en" | "hi"): string {
  const t = i18n.getFixedT(lang);
  const params = { ...x.params };
  for (const k of ["credit", "po_price"]) if (params[k]) params[k] = inr(params[k], false);
  return i18n.exists(`todo.${x.code}`) ? t(`todo.${x.code}`, params) : t("todo.default", { code: x.code });
}

/** "Explain": the decision in plain words, written from its reason codes only (never changes the decision). */
export function ExplainPanel({ invoiceId, matchKey }: { invoiceId: number; matchKey: string }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"team" | "supplier">("team");
  const [lang, setLang] = useState<"en" | "hi">("en");
  const q = useQuery({
    queryKey: ["explain", invoiceId, matchKey],
    queryFn: () => api<Explanation>(`/invoices/${invoiceId}/explain`),
    enabled: open,
  });
  const e = q.data;

  return (
    <div className="explain">
      <button type="button" className="btn btn-sm" aria-expanded={open} aria-controls={`explain-${invoiceId}`} onClick={() => setOpen(!open)}>
        <MessageSquareText size={14} aria-hidden="true" /> {open ? "Hide explanation" : "Explain"}
      </button>
      {open ? (
        <section id={`explain-${invoiceId}`} className="explain-body" aria-label="Explanation of the decision">
          {q.isLoading ? <p className="muted small">Writing the explanation...</p> : null}
          {q.isError ? <p className="alert alert-error">Could not explain this decision.</p> : null}
          {e ? (
            <>
              <div className="explain-tabs" role="tablist" aria-label="Explanation for">
                <button type="button" role="tab" aria-selected={tab === "team"} className={tab === "team" ? "on" : ""} onClick={() => setTab("team")}>
                  For Plant X
                </button>
                <button type="button" role="tab" aria-selected={tab === "supplier"} className={tab === "supplier" ? "on" : ""} onClick={() => setTab("supplier")}>
                  What the supplier is told
                </button>
              </div>
              {tab === "team" ? (
                <div role="tabpanel">
                  <p className="explain-headline">{e.headline}</p>
                  {e.points.length ? (
                    <ol className="explain-points">
                      {e.points.map((p, i) => (
                        <li key={i} className={`explain-point sev-${p.severity}`}>
                          <p className="explain-title">{p.title}</p>
                          <p><span className="explain-k">What</span> {p.what}</p>
                          <p><span className="explain-k">Why it matters</span> {p.why}</p>
                          <p><span className="explain-k">How it gets fixed</span> {p.fix}</p>
                          <p className="explain-who"><UserRound size={12} aria-hidden="true" /> {p.who} acts</p>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                  <p className="explain-next"><span className="explain-k">Next</span> {e.next_step}</p>
                  {e.notes.length ? (
                    <details className="explain-notes">
                      <summary>{e.notes.length} note{e.notes.length > 1 ? "s" : ""} for information</summary>
                      <ul>{e.notes.map((n) => <li key={n}>{n}</li>)}</ul>
                    </details>
                  ) : null}
                </div>
              ) : (
                <div role="tabpanel">
                  <div className="explain-lang" role="group" aria-label="Language">
                    <button type="button" className={lang === "en" ? "on" : ""} aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
                    <button type="button" className={lang === "hi" ? "on" : ""} aria-pressed={lang === "hi"} onClick={() => setLang("hi")} lang="hi">हिंदी</button>
                  </div>
                  {e.supplier_view.length ? (
                    <ul className="explain-supplier" lang={lang}>
                      {e.supplier_view.map((x, i) => (
                        <li key={i}>
                          <span className={`chip ${x.you_act ? "chip-flag" : "chip-info"}`}>
                            {x.you_act ? (lang === "hi" ? "आपको करना है" : "Supplier acts") : lang === "hi" ? "Plant X कर रहा है" : "Plant X acts"}
                          </span>{" "}
                          {supplierText(x, lang)}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted small">Nothing for the supplier to do; their portal shows the stage and expected payment date.</p>
                  )}
                  <p className="muted small">Same words the supplier sees in their portal, from the reviewed English and Hindi texts.</p>
                </div>
              )}
              <p className="explain-footer">
                <ShieldCheck size={12} aria-hidden="true" /> {e.footer}
              </p>
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
