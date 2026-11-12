"""Default policy (version 1). Every value is an assumption, editable by admin as versioned data.

Tolerance keys are modelled on SAP invoice verification tolerance keys:
PP = price variance, DQ = quantity variance, BD = small differences auto-accepted.
"""
from __future__ import annotations

DEFAULT_POLICY: dict = {
    "tolerances": {
        "PP": {"flag_pct": 1.0, "flag_abs_inr": 500, "block_pct": 5.0},
        "DQ": {"default_pct": 0.0, "bulk_mt_pct": 0.5, "block_pct": 5.0},
        "BD": {"auto_accept_inr": 10},
    },
    # Delegation of Authority, invoice value incl. GST (INR). Levels: 1 Finance Manager,
    # 2 Plant Head, 3 CFO. Clean invoices up to touchless_max are approved by policy P-01.
    "doa": {
        "touchless_max_inr": 50_000,
        "bands": [
            {"max_inr": 1_000_000, "levels": [1]},
            {"max_inr": 10_000_000, "levels": [1, 2]},
            {"max_inr": None, "levels": [1, 2, 3]},
        ],
    },
    "mfa_threshold_inr": 1_000_000,
    "confidence_threshold": 0.85,
    "sla_hours": 48,
    # rbi_bank_rate_pct is an editable assumption; verify the current RBI bank rate before use.
    "msme": {"max_term_days": 45, "no_agreement_days": 15, "rbi_bank_rate_pct": 5.75},
    "bank_change_cooling_hours": 72,
    # Data retention. ASSUMPTION, confirm with legal: GST law keeps accounts 72 months after the annual
    # return (CGST Act s.36) and the Companies Act 8 years (s.128(5)), so invoice documents are kept 8 years.
    "retention": {"documents_years": 8, "chat_days": 180, "email_body_days": 365},
    # Payment run (D5). ASSUMPTIONS: cost of funds and run interval are finance inputs.
    "payments": {"cost_of_funds_pct": 9.0, "run_interval_days": 7, "msme_buffer_days": 7},
    # Tax-deduction-at-risk display only (D4). ASSUMPTION: confirm with the tax team.
    "corporate_tax_rate_pct": 25.17,
    # TDS under Income-tax Act 2025 s.393 (formerly 194C / 194J / 194Q). ASSUMPTION: verify with the tax team.
    "tds": {
        "contractor": {"label": "Contractor (s.393; formerly 194C)", "rate_individual_pct": 1, "rate_other_pct": 2,
                       "single_threshold_inr": 30000, "annual_threshold_inr": 100000},
        "technical": {"label": "Fees for technical services (s.393; formerly 194J)", "rate_pct": 2,
                      "annual_threshold_inr": 50000},
        "professional": {"label": "Professional fees (s.393; formerly 194J)", "rate_pct": 10,
                         "annual_threshold_inr": 50000},
        "goods": {"label": "Purchase of goods (s.393; formerly 194Q)", "rate_pct": 0.1,
                  "annual_threshold_inr": 5000000},
    },
}
