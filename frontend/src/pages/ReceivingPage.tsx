import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, PackageCheck, Wrench } from "lucide-react";
import { api, ApiError } from "../api/client";
import { fmtDate, fmtDateTime, inr, qty } from "../lib/format";
import "./ReceivingPage.css";

interface POLine {
  id: number;
  line_no: number;
  item_code: string;
  description: string;
  uom: string;
  ordered: string;
  unit_price: string;
  received: string;
  open: string;
}
interface OpenPO {
  po_number: string;
  supplier_name: string;
  po_date: string;
  is_service: boolean;
  lines: POLine[];
  receipts: { number: string; kind: string; posted_at: string }[];
}
interface Posting {
  number: string;
  kind: string;
  rechecked: number;
  released: number;
  message: string;
}

function POCard({ po }: { po: OpenPO }) {
  const qc = useQueryClient();
  const [inputs, setInputs] = useState<Record<number, string>>({});
  const [result, setResult] = useState<Posting | null>(null);
  const post = useMutation({
    mutationFn: async () => {
      if (po.is_service) {
        const [lineId, value] = Object.entries(inputs).find(([, v]) => v && Number(v) > 0) ?? [];
        return api<Posting>("/stores/service-entries", {
          method: "POST",
          body: JSON.stringify({ po_number: po.po_number, po_line_id: Number(lineId), value, description: "" }),
        });
      }
      const lines = Object.entries(inputs)
        .filter(([, v]) => v && Number(v) > 0)
        .map(([id, v]) => ({ po_line_id: Number(id), qty: v }));
      return api<Posting>("/stores/goods-receipts", {
        method: "POST",
        body: JSON.stringify({ po_number: po.po_number, lines }),
      });
    },
    onSuccess: (r) => {
      setResult(r);
      setInputs({});
      qc.invalidateQueries({ queryKey: ["open-pos"] });
    },
  });
  const anyOpen = po.lines.some((l) => Number(l.open) > 0);
  const hasInput = Object.values(inputs).some((v) => v && Number(v) > 0);
  const Icon = po.is_service ? Wrench : PackageCheck;

  return (
    <section className="panel po-card" aria-labelledby={`po-${po.po_number}`}>
      <header className="po-card-head">
        <div>
          <h2 id={`po-${po.po_number}`} className="mono">
            PO {po.po_number}
          </h2>
          <p className="muted">
            {po.supplier_name} · ordered {fmtDate(po.po_date)}
          </p>
        </div>
        <span className="chip chip-neutral">
          <Icon size={13} aria-hidden="true" /> {po.is_service ? "Services (ML81N)" : "Goods (MIGO 101)"}
        </span>
      </header>
      <table className="table po-lines">
        <thead>
          <tr>
            <th scope="col">Line</th>
            <th scope="col">Item</th>
            <th scope="col" className="num-col">
              {po.is_service ? "PO value" : "Ordered"}
            </th>
            <th scope="col" className="num-col">
              {po.is_service ? "Accepted" : "Received"}
            </th>
            <th scope="col" className="num-col">
              Open
            </th>
            <th scope="col" className="num-col">
              {po.is_service ? "Accept now (₹)" : "Receive now"}
            </th>
          </tr>
        </thead>
        <tbody>
          {po.lines.map((l) => (
            <tr key={l.id}>
              <td className="num">{l.line_no}</td>
              <td>
                <span className="mono">{l.item_code}</span> <span className="muted">{l.description}</span>
              </td>
              <td className="num num-col">{po.is_service ? inr(l.ordered) : `${qty(l.ordered)} ${l.uom}`}</td>
              <td className="num num-col">{po.is_service ? inr(l.received) : `${qty(l.received)} ${l.uom}`}</td>
              <td className="num num-col">{po.is_service ? inr(l.open) : `${qty(l.open)} ${l.uom}`}</td>
              <td className="num-col">
                {Number(l.open) > 0 ? (
                  <input
                    className="input po-qty num"
                    inputMode="decimal"
                    aria-label={`${po.is_service ? "Value to accept" : "Quantity received"} for ${l.item_code}`}
                    placeholder={po.is_service ? inr(l.open, false) : qty(l.open)}
                    value={inputs[l.id] ?? ""}
                    onChange={(e) => setInputs({ ...inputs, [l.id]: e.target.value.replace(/[^\d.]/g, "") })}
                  />
                ) : (
                  <span className="muted">Complete</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <footer className="po-card-foot">
        <span className="muted po-history">
          {po.receipts.length
            ? `${po.receipts.length} posted · last ${po.receipts[0].kind} ${po.receipts[0].number}, ${fmtDateTime(po.receipts[0].posted_at)}`
            : "Nothing received yet"}
        </span>
        {anyOpen ? (
          <button type="button" className="btn btn-primary" disabled={!hasInput || post.isPending} onClick={() => post.mutate()}>
            <Icon size={15} aria-hidden="true" /> {po.is_service ? "Post service entry" : "Post goods receipt"}
          </button>
        ) : null}
      </footer>
      {post.isError ? (
        <div className="alert alert-error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{post.error instanceof ApiError ? post.error.message : "Posting failed."}</span>
        </div>
      ) : null}
      {result ? (
        <div className={`alert ${result.released ? "alert-success" : "alert-info"}`} role="status">
          <CheckCircle2 size={16} aria-hidden="true" />
          <span>{result.message}</span>
        </div>
      ) : null}
    </section>
  );
}

/** Stores: post goods receipts and service entry sheets against open POs (simulates SAP MIGO / ML81N). */
export function ReceivingPage() {
  const q = useQuery({ queryKey: ["open-pos"], queryFn: () => api<OpenPO[]>("/stores/open-pos") });
  const pos = [...(q.data ?? [])].sort(
    (a, b) => Number(b.lines.some((l) => Number(l.open) > 0)) - Number(a.lines.some((l) => Number(l.open) > 0)),
  );
  return (
    <div className="page receiving">
      <header className="page-head">
        <p className="label">Stores · Plant X Dahej</p>
        <h1>Receiving</h1>
        <p className="muted">
          Post what physically arrived or what service work was accepted. Invoices waiting on a PO are re-checked by
          Duly automatically.
        </p>
      </header>
      {q.isLoading ? (
        <div className="skeleton-rows" aria-busy="true">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="skeleton-row" style={{ height: 120 }} />
          ))}
        </div>
      ) : (
        pos.map((po) => <POCard key={po.po_number} po={po} />)
      )}
    </div>
  );
}
