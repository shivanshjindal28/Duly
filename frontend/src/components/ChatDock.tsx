import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Bot, Loader2, MessageCircle, Search, Send, ShieldAlert, X } from "lucide-react";
import { api, ApiError } from "../api/client";
import "./ChatDock.css";

interface ChatOut {
  session_id: number;
  answer: string;
  tools: { name: string; ref: string | null; label: string }[];
  mode: "live" | "offline";
  refused: boolean;
  flagged: boolean;
}
interface Turn {
  role: "user" | "assistant";
  text: string;
  out?: ChatOut;
}

interface Props {
  /** Staff only: which supplier the clerk is helping. Suppliers always get their own data. */
  supplierId?: number;
  greetingName?: string;
  /** Docked (floating button) or inline (full panel on a page). */
  variant?: "dock" | "inline";
}

/** "Where is my payment?" assistant. Shows which records each answer looked up. */
export function ChatDock({ supplierId, greetingName, variant = "dock" }: Props) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(variant === "inline");
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setTurns([]);
    setSessionId(null);
  }, [supplierId]);
  // Block body on purpose: newer browsers return a Promise from scrollIntoView, and an effect
  // must not return anything but a cleanup function.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  const ask = useMutation({
    mutationFn: (message: string) =>
      api<ChatOut>("/chat", {
        method: "POST",
        body: JSON.stringify({ message, lang: i18n.language === "hi" ? "hi" : "en", session_id: sessionId, supplier_id: supplierId ?? null }),
      }),
    onSuccess: (out) => {
      setSessionId(out.session_id);
      setTurns((x) => [...x, { role: "assistant", text: out.answer, out }]);
    },
    onError: (e) => setTurns((x) => [...x, { role: "assistant", text: e instanceof ApiError ? e.message : t("chat.error") }]),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const msg = input.trim();
    if (!msg || ask.isPending) return;
    setTurns((x) => [...x, { role: "user", text: msg }]);
    setInput("");
    ask.mutate(msg);
  }

  if (!open) {
    return (
      <button type="button" className="chat-fab" onClick={() => setOpen(true)} aria-label={t("chat.open")}>
        <MessageCircle size={20} aria-hidden="true" /> <span>{t("chat.open")}</span>
      </button>
    );
  }

  return (
    <section className={`chat chat-${variant}`} aria-label={t("chat.title")} lang={i18n.language}>
      <header className="chat-head">
        <div>
          <h2>
            <Bot size={16} aria-hidden="true" /> {t("chat.title")}
          </h2>
          <p>{t("chat.subtitle")}</p>
        </div>
        {variant === "dock" ? (
          <button type="button" className="btn btn-ghost chat-close" onClick={() => setOpen(false)} aria-label={t("chat.close")}>
            <X size={16} aria-hidden="true" />
          </button>
        ) : null}
      </header>
      <div className="chat-log" role="log" aria-live="polite">
        <p className="chat-msg chat-assistant">{t("chat.greeting", { name: greetingName ?? "" })}</p>
        {turns.map((m, i) => (
          <div key={i} className={`chat-turn chat-turn-${m.role}`}>
            <p className={`chat-msg chat-${m.role}${m.out?.refused ? " is-refused" : ""}`}>
              {m.out?.refused || m.out?.flagged ? <ShieldAlert size={14} aria-hidden="true" className="chat-shield" /> : null}
              {m.text}
            </p>
            {m.out ? (
              <div className="chat-meta">
                {m.out.tools.map((c, j) => (
                  <span key={j} className="chip chip-neutral chat-chip">
                    <Search size={11} aria-hidden="true" /> {t("chat.looked_up")}: {c.label}
                  </span>
                ))}
                <span className="chat-mode">{m.out.mode === "live" ? t("chat.mode_live") : t("chat.mode_offline")}</span>
              </div>
            ) : null}
          </div>
        ))}
        {ask.isPending ? (
          <p className="chat-msg chat-assistant chat-typing">
            <Loader2 size={14} className="spin" aria-hidden="true" />
          </p>
        ) : null}
        <div ref={endRef} />
      </div>
      <form className="chat-form" onSubmit={submit}>
        <input
          className="input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t("chat.placeholder")}
          aria-label={t("chat.placeholder")}
          maxLength={1000}
        />
        <button type="submit" className="btn btn-primary" disabled={!input.trim() || ask.isPending}>
          <Send size={15} aria-hidden="true" /> {t("chat.send")}
        </button>
      </form>
    </section>
  );
}
