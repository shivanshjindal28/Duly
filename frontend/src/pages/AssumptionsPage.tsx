import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { PageSkeleton } from "../components/PageSkeleton";
import { api } from "../api/client";
import { inr } from "../lib/format";
import "./AboutPages.css";

interface Band { max_inr: number | null; levels: number[] }
interface TdsRule { label: string; rate_pct?: number; rate_individual_pct?: number; rate_other_pct?: number; single_threshold_inr?: number; annual_threshold_inr?: number }
interface AssumptionsOut {
  organisation: { name: string; gstin: string; state_code: string; address: string } | null;
  suppliers: {
    code: string; name: string; category: string; state_code: string; msme: string; udyam: string | null;
    enterprise: string; e_invoice: boolean; terms_days: number; written_agreement: boolean; tds_section: string;
    early_discount: string | null;
  }[];
  policy: {
    version: number;
    name: string;
    data: {
      tolerances: { PP: { flag_pct: number; flag_abs_inr: number; block_pct: number }; DQ: { default_pct: number; bulk_mt_pct: number; block_pct: number }; BD: { auto_accept_inr: number } };
      doa: { touchless_max_inr: number; bands: Band[] };
      mfa_threshold_inr: number;
      confidence_threshold: number;
      sla_hours: number;
      msme: { max_term_days: number; no_agreement_days: number; rbi_bank_rate_pct: number };
      bank_change_cooling_hours: number;
      payments: { cost_of_funds_pct: number; run_interval_days: number; msme_buffer_days: number };
      corporate_tax_rate_pct: number;
      tds: Record<string, TdsRule>;
    };
  } | null;
  hsn: { code: string; description: string; rates: number[] }[];
}

const STATE: Record<string, string> = { "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka" };
const LEVEL = ["", "L1 Finance Manager", "L2 Plant Head", "L3 CFO"];
const lakh = (v: number) => inr(v).replace(".00", "");

function Rows({ rows }: { rows: [string, string, string?][] }) {
  return (
    <table className="table kv-table">
      <tbody>
        {rows.map(([k, v, why]) => (
          <tr key={k}>
            <th scope="row">{k}</th>
            <td className="num">{v}</td>
            <td className="muted small">{why ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Scenario & assumptions (spec section 3): the story, and every rule value Duly runs on, from live policy data. */
export function AssumptionsPage() {
  const q = useQuery({ queryKey: ["assumptions"], queryFn: () => api<AssumptionsOut>("/assumptions") });
  if (q.isLoading) return <PageSkeleton blocks={4} label="Loading assumptions" />;
  if (!q.data?.policy) return <div className="page alert alert-error">Could not load the assumptions.</div>;
  const { organisation: org, suppliers, hsn } = q.data;
  const p = q.data.policy.data;
  let prev = p.doa.touchless_max_inr;
  const bands = p.doa.bands.map((b) => {
    const from = prev;
    prev = b.max_inr ?? prev;
    return [`Clean invoice above ${lakh(from)}` + (b.max_inr ? ` up to ${lakh(b.max_inr)}` : ""), b.levels.map((l) => LEVEL[l]).join(" then ")] as [string, string];
  });

  return (
    <div className="page about">
      <header className="page-head">
        <p className="label">The story behind the demo</p>
        <h1>Scenario &amp; assumptions</h1>
        <p className="muted">
          Every company, person and number here is fictional, and every rule value is an assumption. Rules are policy
          data (version {q.data.policy.version}), so finance can change them without a code release, on the{" "}
          <Link to="/policy">Policy</Link> page.
        </p>
      </header>

      <section className="panel about-doc md">
        <h2>Plant X</h2>
        <p>
          <strong>{org?.name ?? "Plant X Polymers Pvt Ltd"}</strong> is a fictional polypropylene and polyethylene
          plant in Gujarat, India (GSTIN <span className="mono">{org?.gstin}</span>, state code {org?.state_code}).
          Currency INR, financial year April to March. Accounts payable is run by a small shared-services team in
          Mumbai.
        </p>
        <p>
          Why polymers: the spend covers every procure-to-pay edge case. Bulk raw materials in tonnes with quantity
          tolerances, packaging from MSMEs, spares with partial deliveries, maintenance services with no goods receipt,
          freight, and both intra-state (CGST + SGST) and inter-state (IGST) tax.
        </p>
        <p>
          <strong>Focus user:</strong> the AP clerk, who spends most of the day chasing mismatches by hand.{" "}
          <strong>Focus problem:</strong> wrong, duplicated or fraudulent invoices get paid while honest MSME suppliers
          are paid late.
        </p>
        <p>
          Payment terms: 60 days from a compliant invoice for large suppliers (configurable per supplier); for
          Udyam-registered micro and small suppliers, at most 45 days from acceptance (15 days without a written
          agreement). Impact volume: 3,000 invoices a month (editable on the Impact page).
        </p>
      </section>

      <section className="panel table-panel" aria-labelledby="sup-title">
        <h2 id="sup-title" className="label about-table-title">Suppliers (fictional, synthetic GSTINs with valid check digits)</h2>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Supplier</th>
              <th scope="col">Category</th>
              <th scope="col">State</th>
              <th scope="col">MSME</th>
              <th scope="col">e-invoice</th>
              <th scope="col" className="num-col">Terms</th>
              <th scope="col">TDS</th>
              <th scope="col">Early-payment discount</th>
            </tr>
          </thead>
          <tbody>
            {suppliers.map((s) => (
              <tr key={s.code}>
                <td>
                  {s.name} <span className="muted mono small">{s.code}</span>
                </td>
                <td>{s.category}</td>
                <td>
                  {STATE[s.state_code] ?? s.state_code} ({s.state_code}) {s.state_code === "24" ? "· CGST+SGST" : "· IGST"}
                </td>
                <td>{s.msme === "none" ? "No" : `${s.msme[0].toUpperCase()}${s.msme.slice(1)} · ${s.enterprise}`}</td>
                <td>{s.e_invoice ? "Signed QR" : "Not applicable"}</td>
                <td className="num-col">
                  {s.terms_days} d{s.msme !== "none" && !s.written_agreement ? " (no written agreement: 15 d MSME cap)" : ""}
                </td>
                <td>{s.tds_section}</td>
                <td>{s.early_discount ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="about-two">
        <section className="panel" aria-labelledby="tol-title">
          <h2 id="tol-title" className="label about-table-title">Matching tolerances (SAP-style keys)</h2>
          <Rows rows={[
            ["PP price: flag above", `${p.tolerances.PP.flag_pct}% or ${inr(p.tolerances.PP.flag_abs_inr)} on the line`, "Within both, information only"],
            ["PP price: block above", `${p.tolerances.PP.block_pct}%`],
            ["DQ quantity: goods", `${p.tolerances.DQ.default_pct}%`, "Nothing billed beyond what was received"],
            ["DQ quantity: bulk in MT", `${p.tolerances.DQ.bulk_mt_pct}%`, "Weighbridge allowance"],
            ["DQ quantity: block above", `${p.tolerances.DQ.block_pct}%`, "Up to this, a flag"],
            ["BD small difference auto-accepted", inr(p.tolerances.BD.auto_accept_inr)],
            ["Field confidence for review", `${Math.round(p.confidence_threshold * 100)}%`, "Below this a person confirms the field"],
          ]} />
        </section>
        <section className="panel" aria-labelledby="doa-title">
          <h2 id="doa-title" className="label about-table-title">Delegation of authority</h2>
          <Rows rows={[
            [`Clean invoice up to ${lakh(p.doa.touchless_max_inr)}`, "Policy P-01 (touchless)", "No human touch"],
            ...bands,
            ["Flag routed with an override", "L1 then L2", "Written justification of 15+ characters"],
            ["MFA required above", lakh(p.mfa_threshold_inr)],
            ["Approval SLA per step", `${p.sla_hours} h`, "Then the next level can act"],
            ["Bank change cooling period", `${p.bank_change_cooling_hours} h`, "Plus a call-back and maker-checker"],
          ]} />
        </section>
        <section className="panel" aria-labelledby="msme-title">
          <h2 id="msme-title" className="label about-table-title">MSME and payments</h2>
          <Rows rows={[
            ["MSME maximum term", `${p.msme.max_term_days} days from acceptance`, "MSMED Act s.15"],
            ["Without a written agreement", `${p.msme.no_agreement_days} days`],
            ["RBI bank rate", `${p.msme.rbi_bank_rate_pct}%`, "Verify the current rate; interest is 3x, monthly rests"],
            ["Corporate tax rate", `${p.corporate_tax_rate_pct}%`, "Only to size the tax-deduction effect"],
            ["Cost of funds", `${p.payments.cost_of_funds_pct}% a year`, "Take a discount only if it beats this"],
            ["Payment run every", `${p.payments.run_interval_days} days`],
            ["MSME safety buffer", `${p.payments.msme_buffer_days} days`, "Pay if due before the next run plus this"],
          ]} />
        </section>
        <section className="panel" aria-labelledby="tds-title">
          <h2 id="tds-title" className="label about-table-title">TDS (s.393, verify with the tax team)</h2>
          <Rows rows={Object.values(p.tds).map((r) => [
            r.label,
            r.rate_pct !== undefined ? `${r.rate_pct}%` : `${r.rate_individual_pct}% individual / ${r.rate_other_pct}% other`,
            [r.single_threshold_inr ? `single bill > ${lakh(r.single_threshold_inr)}` : "", r.annual_threshold_inr ? `year > ${lakh(r.annual_threshold_inr)}` : ""].filter(Boolean).join(", "),
          ] as [string, string, string])} />
        </section>
      </div>

      <section className="panel table-panel" aria-labelledby="hsn-title">
        <h2 id="hsn-title" className="label about-table-title">HSN / SAC GST rates used by the tax check (illustrative)</h2>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Code</th>
              <th scope="col">Description</th>
              <th scope="col">Allowed GST rates</th>
            </tr>
          </thead>
          <tbody>
            {hsn.map((h) => (
              <tr key={h.code}>
                <td className="mono">{h.code}</td>
                <td>{h.description}</td>
                <td className="num">{h.rates.map((r) => `${r}%`).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
