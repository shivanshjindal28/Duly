import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Languages } from "lucide-react";
import { api } from "../api/client";
import type { SupplierOut } from "../api/types";
import { ChatDock } from "../components/ChatDock";
import { setLanguage } from "../i18n";

/** AP clerk: answer a supplier's "where is my payment?" call with the same assistant, scoped to
 *  the supplier the clerk picks. */
export function AssistantPage() {
  const { i18n } = useTranslation();
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: () => api<SupplierOut[]>("/suppliers") });
  const [supplierId, setSupplierId] = useState<string>("");
  const chosen = (suppliers.data ?? []).find((s) => String(s.id) === supplierId);
  const hindi = i18n.language === "hi";
  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <header className="page-head page-head-row">
        <div>
          <p className="label">Supplier calls</p>
          <h1>Payment assistant</h1>
          <p className="muted">Answer a supplier's question with the same assistant they use. Pick who is calling first.</p>
        </div>
        <button type="button" className="btn" onClick={() => setLanguage(hindi ? "en" : "hi")}>
          <Languages size={16} aria-hidden="true" /> {hindi ? "English" : "हिन्दी"}
        </button>
      </header>
      <label className="field" style={{ maxWidth: 380 }}>
        <span>Supplier on the call</span>
        <select className="input" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
          <option value="">Choose a supplier</option>
          {(suppliers.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.code})
            </option>
          ))}
        </select>
      </label>
      {chosen ? <ChatDock key={chosen.id} supplierId={chosen.id} greetingName={chosen.name} variant="inline" /> : null}
    </div>
  );
}
