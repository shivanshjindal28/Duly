/** API response types (mirror backend/app/api/*.py Pydantic models). */

export type Decision = "APPROVE" | "FLAG" | "BLOCK";
export type Severity = "info" | "flag" | "block";
export type InvoiceStatus =
  | "received"
  | "needs_review"
  | "flagged"
  | "blocked"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "paid";

export interface InvoiceSummary {
  id: number;
  supplier_id: number | null;
  supplier_name: string | null;
  invoice_number: string;
  invoice_date: string | null;
  po_number: string | null;
  total: string;
  status: InvoiceStatus;
  decision: Decision | null;
  current_owner: string;
  received_at: string;
  rail: number;
}

export interface InvoiceLine {
  line_no: number;
  item_code: string | null;
  description: string;
  hsn_sac: string | null;
  qty: string;
  uom: string;
  unit_price: string;
  taxable_value: string;
  gst_rate: string;
  cgst: string;
  sgst: string;
  igst: string;
}

export interface ExtractedFieldOut {
  field: string;
  value: string | null;
  confidence: number;
  page: number | null;
  bbox: [number, number, number, number] | null;
  source: string;
  needs_review: boolean;
  previous_value: string | null;
  previous_confidence: number | null;
  reviewed_by: string | null;
  review_reason: string | null;
  reviewed_at: string | null;
}

export interface ReasonOut {
  code: string;
  title: string;
  severity: Severity;
  message: string;
  evidence: Record<string, string | number | null>;
  line_no: number | null;
  sap_equivalent: string | null;
}

export interface MatrixRow {
  invoice_line_no: number;
  po_line_id: number | null;
  po_line_no: number | null;
  description: string;
  po_qty: string | null;
  po_price: string | null;
  received: string | null;
  previously_invoiced: string | null;
  invoice_qty: string;
  invoice_price: string;
  uom: string;
  price_variance_pct: string | null;
  price_variance_amount: string | null;
  qty_variance: string | null;
}

export interface MatchOut {
  decision: Decision;
  policy_version: number;
  engine_version: string;
  trigger: string;
  created_at: string;
  reasons: ReasonOut[];
  matrix: MatrixRow[];
}

export interface InvoiceDetail extends InvoiceSummary {
  supplier_gstin: string | null;
  buyer_gstin: string | null;
  place_of_supply: string | null;
  currency: string;
  taxable_total: string;
  cgst: string;
  sgst: string;
  igst: string;
  bank_account_masked: string | null;
  bank_ifsc: string | null;
  irn: string | null;
  ai_mode: string | null;
  /** upload, or ers: self-billed by Duly from a goods receipt / service entry (no document). */
  origin: "upload" | "ers";
  lines: InvoiceLine[];
  document: { original_filename: string; mime_type: string; pages: number; sha256: string; size_bytes: number } | null;
  fields: ExtractedFieldOut[];
  confidence_threshold: number;
  pending_review: string[];
  can_review: boolean;
  match: MatchOut | null;
  workflow: WorkflowOut;
  einvoice: EInvoiceOut;
  injection: {
    found: boolean;
    findings: { where: string; text: string; page: number | null; patterns: string[] }[];
    ai_quarantined: { header?: Record<string, { value: string | null }> } | null;
  } | null;
}

export interface EInvoiceOut {
  status: "none" | "valid" | "invalid";
  error: string | null;
  applicable: boolean;
  sandbox: boolean;
  irn: string | null;
  fields: { field: string; printed: string | null; signed: string | null; same: boolean }[];
}

export interface StepOut {
  sequence: number;
  level: number;
  title: string;
  status: "pending" | "approved" | "rejected" | "skipped";
  approver: string | null;
  delegated_from: string | null;
  comment: string | null;
  by_policy: string | null;
  mfa_verified: boolean;
  due_at: string | null;
  escalated_at: string | null;
  decided_at: string | null;
  overdue: boolean;
}

export interface WorkflowOut {
  steps: StepOut[];
  override_by: string | null;
  override_at: string | null;
  override_justification: string | null;
  can_approve: boolean;
  approve_blocked_reason: string | null;
  approve_blocked_sod: boolean;
  mfa_required: boolean;
  can_override: boolean;
}

export interface SupplierOut {
  id: number;
  code: string;
  name: string;
  category: string;
  gstin: string;
  state_code: string;
  msme_category: string;
}
