import { Check } from "lucide-react";
import "./DulyRail.css";

/** The 5-stop P2P lifecycle that gives Duly its name. */
export const RAIL_STOPS = ["ordered", "received", "matched", "approved", "paid"] as const;
export type RailStop = (typeof RAIL_STOPS)[number];

interface Props {
  /** Number of completed stops (0 to 5). */
  completed: number;
  /** Visual variant: on the navy brand panel or on a light surface. */
  tone?: "light" | "dark";
  /** Optional sub-label under each stop, e.g. "PO", "GR". */
  showDocs?: boolean;
}

const DOCS: Record<RailStop, string> = {
  ordered: "PO",
  received: "GR / SES",
  matched: "3-way",
  approved: "DoA",
  paid: "UTR",
};

export function DulyRail({ completed, tone = "light", showDocs = false }: Props) {
  return (
    <div className="duly-rail-wrap">
    <ol className={`duly-rail duly-rail-${tone}`} aria-label={`Invoice lifecycle: ${completed} of 5 stages done`}>
      {RAIL_STOPS.map((stop, i) => {
        const state = i < completed ? "done" : i === completed ? "current" : "todo";
        return (
          <li key={stop} className={`duly-rail-stop is-${state}`}>
            <span className="duly-rail-dot" aria-hidden="true">
              {state === "done" ? <Check size={12} strokeWidth={3} /> : null}
            </span>
            <span className="duly-rail-text">
              <span className="duly-rail-name">
                <span className="duly-rail-prefix">Duly </span>
                <strong>{stop}</strong>
              </span>
              {showDocs ? <span className="duly-rail-doc">{DOCS[stop]}</span> : null}
              <span className="sr-only">{state === "done" ? " (done)" : state === "current" ? " (current)" : ""}</span>
            </span>
          </li>
        );
      })}
    </ol>
    </div>
  );
}
