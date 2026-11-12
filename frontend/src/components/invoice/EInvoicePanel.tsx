import { CheckCircle2, CircleSlash, OctagonX, QrCode, TriangleAlert } from "lucide-react";
import type { EInvoiceOut } from "../../api/types";

/** "Trust the signed QR, not the pixels": signed IRP values next to what is printed. */
export function EInvoicePanel({ e }: { e: EInvoiceOut }) {
  const mismatch = e.fields.some((f) => !f.same);
  let head;
  if (e.status === "valid" && !mismatch) {
    head = (
      <span className="chip chip-approve">
        <CheckCircle2 size={13} aria-hidden="true" /> Signed e-invoice verified
      </span>
    );
  } else if (e.status === "valid") {
    head = (
      <span className="chip chip-block">
        <OctagonX size={13} aria-hidden="true" /> Printed invoice differs from the signed e-invoice
      </span>
    );
  } else if (e.status === "invalid") {
    head = (
      <span className="chip chip-block">
        <OctagonX size={13} aria-hidden="true" /> QR not signed by the trusted IRP key
      </span>
    );
  } else if (e.applicable) {
    head = (
      <span className="chip chip-flag">
        <TriangleAlert size={13} aria-hidden="true" /> Signed QR expected but not found
      </span>
    );
  } else {
    head = (
      <span className="chip chip-neutral">
        <CircleSlash size={13} aria-hidden="true" /> e-invoice not applicable
      </span>
    );
  }
  return (
    <div className="einv">
      <div className="einv-head">
        <QrCode size={16} aria-hidden="true" /> {head}
      </div>
      {e.error ? <p className="einv-error">{e.error}</p> : null}
      {e.fields.length ? (
        <table className="table einv-table">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Printed / extracted</th>
              <th scope="col">Signed by IRP</th>
            </tr>
          </thead>
          <tbody>
            {e.fields.map((f) => (
              <tr key={f.field} className={f.same ? "" : "einv-diff"}>
                <th scope="row">{f.field}</th>
                <td className="mono">{f.printed ?? "-"}</td>
                <td className="mono">
                  {f.signed ?? "-"} {f.same ? null : <span className="sr-only">(differs)</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {e.status !== "none" && e.sandbox ? (
        <p className="einv-note">
          Verified against the demo Sandbox IRP key. Production trusts the NIC Invoice Registration Portal public key.
        </p>
      ) : null}
    </div>
  );
}
