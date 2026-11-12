import { Fragment, useEffect, useId, useState, type ReactNode } from "react";
import { tokens } from "../theme/tokens";
import "./Markdown.css";

/**
 * Small Markdown renderer for our own docs (headings, paragraphs, bullet lists, inline code and
 * bold, fenced code, ```mermaid diagrams). Not a general Markdown engine: the input is a file in
 * this repo, rendered so the in-app page is literally the document.
 */
export function Markdown({ source, skipTitle = true }: { source: string; skipTitle?: boolean }) {
  const blocks: ReactNode[] = [];
  const parts = source.split(/^```(\w*)\n([\s\S]*?)^```\s*$/m);
  // split() with two groups yields: text, lang, code, text, lang, code, ...
  for (let i = 0; i < parts.length; i += 3) {
    blocks.push(<TextBlock key={`t${i}`} text={parts[i]} skipTitle={skipTitle && i === 0} />);
    if (i + 2 < parts.length) {
      const lang = parts[i + 1];
      const code = parts[i + 2];
      blocks.push(lang === "mermaid" ? <Mermaid key={`m${i}`} code={code} /> : <pre key={`c${i}`} className="md-pre mono">{code}</pre>);
    }
  }
  return <div className="md">{blocks}</div>;
}

function TextBlock({ text, skipTitle }: { text: string; skipTitle: boolean }) {
  const out: ReactNode[] = [];
  let para: string[] = [];
  let list: string[] = [];
  const flush = () => {
    if (para.length) out.push(<p key={out.length}>{inline(para.join(" "))}</p>);
    if (list.length) out.push(<ul key={out.length}>{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>);
    para = [];
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (/^#{1,4} /.test(line)) {
      flush();
      const level = line.indexOf(" ");
      const content = line.slice(level + 1);
      if (level === 1 && skipTitle) continue;
      out.push(level <= 2 ? <h2 key={out.length}>{content}</h2> : <h3 key={out.length}>{content}</h3>);
    } else if (/^\s*- /.test(line)) {
      if (para.length) flush();
      list.push(line.replace(/^\s*- /, ""));
    } else if (/^\s{2,}\S/.test(line) && list.length) {
      list[list.length - 1] += " " + line.trim();
    } else if (line === "") {
      flush();
    } else {
      if (list.length) flush();
      para.push(line);
    }
  }
  flush();
  return <>{out}</>;
}

function inline(text: string): ReactNode {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((t, i) => {
    if (t.startsWith("`") && t.endsWith("`")) return <code key={i} className="mono">{t.slice(1, -1)}</code>;
    if (t.startsWith("**") && t.endsWith("**")) return <strong key={i}>{t.slice(2, -2)}</strong>;
    return <Fragment key={i}>{t}</Fragment>;
  });
}

let mermaidReady: Promise<typeof import("mermaid")["default"]> | null = null;
function loadMermaid() {
  // Loaded only on pages that show a diagram; bundled, so it works offline.
  mermaidReady ??= import("mermaid").then(({ default: mermaid }) => {
    const C = tokens.color;
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      fontFamily: tokens.font.sans,
      themeVariables: {
        primaryColor: C.primarySoft,
        primaryBorderColor: C.primary,
        primaryTextColor: C.text,
        secondaryColor: C.canvas,
        tertiaryColor: C.surface,
        lineColor: C.textSecondary,
        clusterBkg: C.canvas,
        clusterBorder: C.border,
        actorBkg: C.primarySoft,
        actorBorder: C.primary,
        noteBkgColor: C.flagBg,
        fontSize: "13px",
      },
    });
    return mermaid;
  });
  return mermaidReady;
}

function Mermaid({ code }: { code: string }) {
  const id = "mmd" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    loadMermaid()
      .then((m) => m.render(id, code))
      .then((r) => {
        if (alive) setSvg(r.svg);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : "Diagram could not be drawn.");
      });
    return () => {
      alive = false;
    };
  }, [id, code]);
  if (error) return <pre className="md-pre mono" title={error}>{code}</pre>;
  if (!svg) return <div className="md-diagram md-diagram-loading muted">Drawing diagram...</div>;
  return <figure className="md-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}
