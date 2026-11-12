/** Labels and ordering for extracted fields. */

export const HEADER_ORDER = [
  "supplier_name",
  "supplier_gstin",
  "invoice_number",
  "invoice_date",
  "po_number",
  "buyer_gstin",
  "place_of_supply",
  "currency",
  "taxable_total",
  "cgst",
  "sgst",
  "igst",
  "total",
  "bank_account",
  "bank_ifsc",
  "irn",
] as const;

export const FIELD_LABEL: Record<string, string> = {
  supplier_name: "Supplier",
  supplier_gstin: "Supplier GSTIN",
  buyer_gstin: "Bill-to GSTIN",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  po_number: "PO number",
  place_of_supply: "Place of supply",
  currency: "Currency",
  taxable_total: "Taxable value",
  cgst: "CGST",
  sgst: "SGST",
  igst: "IGST",
  total: "Invoice total",
  bank_account: "Bank account",
  bank_ifsc: "IFSC",
  irn: "IRN",
  item_code: "Item code",
  description: "Description",
  hsn_sac: "HSN/SAC",
  qty: "Qty",
  uom: "UoM",
  unit_price: "Unit price",
  taxable_value: "Line value",
  gst_rate: "GST %",
};

export const MONEY_FIELDS = new Set([
  "taxable_total",
  "cgst",
  "sgst",
  "igst",
  "total",
  "unit_price",
  "taxable_value",
]);

export const MONO_FIELDS = new Set([
  "supplier_gstin",
  "buyer_gstin",
  "invoice_number",
  "po_number",
  "bank_account",
  "bank_ifsc",
  "irn",
  "item_code",
  "hsn_sac",
]);

/** "lines[2].qty" -> { line: 2, name: "qty" }; "total" -> { line: null, name: "total" } */
export function parseFieldPath(path: string): { line: number | null; name: string } {
  const m = /^lines\[(\d+)\]\.(.+)$/.exec(path);
  return m ? { line: Number(m[1]), name: m[2] } : { line: null, name: path };
}

export function fieldLabel(path: string): string {
  const { line, name } = parseFieldPath(path);
  const base = FIELD_LABEL[name] ?? name;
  return line === null ? base : `Line ${line + 1} · ${base}`;
}
