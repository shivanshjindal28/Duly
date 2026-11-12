import { useEffect, useRef, useState } from "react";
import type { ExtractedFieldOut } from "../../api/types";
import { fieldLabel } from "./fields";

interface Props {
  invoiceId: number;
  pages: number;
  fields: ExtractedFieldOut[];
  selected: string | null;
  onSelect: (field: string) => void;
}

/**
 * Server-rendered page images with an overlay of every extracted field's bounding box.
 * Boxes are page fractions, so they line up at any zoom. The selected field is outlined
 * strongly and scrolled into view; low-confidence fields are dashed.
 */
export function DocumentViewer({ invoiceId, pages, fields, selected, onSelect }: Props) {
  const [page, setPage] = useState(1);
  const [showAll, setShowAll] = useState(true);
  const selectedRef = useRef<HTMLButtonElement>(null);
  const sel = fields.find((f) => f.field === selected);

  // Jump to the selected field's page (only when the selection changes, so thumbnails still work).
  useEffect(() => {
    if (sel?.page) setPage(sel.page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selected, page]);

  const boxes = fields.filter((f) => f.bbox && f.page === page && (showAll || f.field === selected));

  return (
    <div className="viewer">
      <div className="viewer-bar">
        {pages > 1 ? (
          <div className="viewer-thumbs" role="tablist" aria-label="Pages">
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                type="button"
                role="tab"
                aria-selected={n === page}
                className={`viewer-thumb${n === page ? " is-active" : ""}`}
                onClick={() => setPage(n)}
              >
                <img src={`/api/invoices/${invoiceId}/pages/${n}.png`} alt={`Page ${n}`} />
              </button>
            ))}
          </div>
        ) : (
          <span className="muted viewer-pageno">Page 1 of 1</span>
        )}
        <label className="viewer-toggle">
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          Show all fields
        </label>
      </div>
      <div className="viewer-scroll">
        <div className="viewer-page">
          <img src={`/api/invoices/${invoiceId}/pages/${page}.png`} alt={`Invoice page ${page}`} draggable={false} />
          {boxes.map((f) => {
            const [x0, y0, x1, y1] = f.bbox!;
            const isSel = f.field === selected;
            return (
              <button
                key={f.field}
                ref={isSel ? selectedRef : undefined}
                type="button"
                className={`viewer-box${isSel ? " is-selected" : ""}${f.needs_review ? " is-low" : ""}`}
                style={{
                  left: `${x0 * 100 - 0.4}%`,
                  top: `${y0 * 100 - 0.3}%`,
                  width: `${(x1 - x0) * 100 + 0.8}%`,
                  height: `${(y1 - y0) * 100 + 0.6}%`,
                }}
                title={`${fieldLabel(f.field)}: ${f.value ?? ""} (${Math.round(f.confidence * 100)}%)`}
                aria-label={`Highlight ${fieldLabel(f.field)}`}
                onClick={() => onSelect(f.field)}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
