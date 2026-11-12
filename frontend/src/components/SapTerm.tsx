import type { ReactNode } from "react";
import { Info } from "lucide-react";

/** SAP vocabulary, shown as tooltips so finance and SAP users can map Duly to what they know. */
export const SAP_TERMS = {
  PO: "SAP: ME23N, display purchase order.",
  GR: "SAP: MIGO, goods movement type 101 (goods receipt for a purchase order).",
  SES: "SAP: service entry sheet (ML81N / Manage Service Entry Sheets): the accepted value of services.",
  MIRO: "SAP: MIRO, enter incoming invoice (logistics invoice verification).",
  PP: "SAP tolerance key PP: price variance between invoice and PO price.",
  DQ: "SAP tolerance key DQ: quantity variance, invoice quantity above the received (GR) quantity.",
  BD: "SAP tolerance key BD: small differences accepted automatically.",
  R: "SAP payment block R: blocked for invoice verification; released (MRBR) once the mismatch is resolved.",
} as const;

export type SapTermKey = keyof typeof SAP_TERMS;

export function SapTerm({ term, children }: { term: SapTermKey; children: ReactNode }) {
  return (
    <span className="sap-term">
      {children}
      <span className="tip" tabIndex={0} aria-label={SAP_TERMS[term]}>
        <Info size={11} aria-hidden="true" />
        <span role="tooltip" className="tip-body">{SAP_TERMS[term]}</span>
      </span>
    </span>
  );
}
