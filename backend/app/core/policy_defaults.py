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
}
