import { useEffect, useState } from "react";

/** True while the viewport is at most `max` px wide (phones). Used where CSS cannot reach, e.g. chart axis widths. */
export function useNarrow(max = 640): boolean {
  const query = `(max-width: ${max}px)`;
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setNarrow(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return narrow;
}
