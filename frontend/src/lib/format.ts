/** Formatting helpers. Amounts always use Indian digit grouping: ₹12,34,567.00. */

const inrFmt = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const qtyFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });

export function inr(value: string | number | null | undefined, symbol = true): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return (symbol ? "₹" : "") + inrFmt.format(n);
}

/** Large amounts in lakh / crore: ₹2.35 Cr, ₹18.4 L, ₹45,000. */
export function inrShort(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  const a = Math.abs(n);
  if (a >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
  return "₹" + new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n);
}

const moneyFmt = new Map<string, Intl.NumberFormat>();

/** Amount in its own currency: ₹12,34,567.00, €19,250.00, $1,250.00. INR keeps Indian grouping. */
export function money(value: string | number | null | undefined, currency: string | null | undefined = "INR"): string {
  const c = (currency || "INR").toUpperCase();
  if (c === "INR") return inr(value);
  if (value === null || value === undefined || value === "") return "-";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  let f = moneyFmt.get(c);
  if (!f) {
    try {
      f = new Intl.NumberFormat("en-IN", { style: "currency", currency: c, minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } catch {
      f = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    moneyFmt.set(c, f);
  }
  const out = f.format(n);
  return /\d/.test(out[0]) ? `${c} ${out}` : out;
}

/** "≈ ₹17.3 L" for a foreign-currency amount (empty for INR). */
export function inrApprox(totalInr: string | number | null | undefined, currency: string | null | undefined): string {
  if (!currency || currency.toUpperCase() === "INR" || totalInr === null || totalInr === undefined) return "";
  return `≈ ${inrShort(totalInr)}`;
}

export function qty(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  return Number.isNaN(n) ? String(value) : qtyFmt.format(n);
}

export function pct(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value.length === 10 ? value + "T00:00:00" : value);
  return Number.isNaN(d.getTime()) ? value : dateFmt.format(d);
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : dateTimeFmt.format(d);
}
