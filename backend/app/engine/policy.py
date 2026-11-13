"""Tolerance profile parsed from the versioned policy data (SAP-style keys PP, DQ, BD)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Tolerances:
    pp_flag_pct: Decimal  # price variance accepted up to this % ...
    pp_flag_abs: Decimal  # ... and up to this amount (whichever is lower), then FLAG
    pp_block_pct: Decimal  # above this %: BLOCK
    dq_default_pct: Decimal  # quantity over-delivery accepted (default 0)
    dq_bulk_mt_pct: Decimal  # for bulk materials in MT (weighbridge differences)
    dq_block_pct: Decimal  # excess above this % of received: BLOCK (between: FLAG)
    bd_abs: Decimal  # total small differences auto-accepted
    version: int = 1
    # INR per one unit of each currency (policy table, editable; INR = 1). Empty = no conversions.
    fx: tuple[tuple[str, Decimal], ...] = ()
    fx_as_of: str = ""

    def rate(self, currency: str) -> Decimal | None:
        c = (currency or "").upper()
        if c == "INR":
            return Decimal(1)
        return dict(self.fx).get(c)

    @classmethod
    def from_policy(cls, data: dict, version: int = 1) -> Tolerances:
        t = data["tolerances"]
        d = lambda v: Decimal(str(v))  # noqa: E731
        return cls(
            pp_flag_pct=d(t["PP"]["flag_pct"]), pp_flag_abs=d(t["PP"]["flag_abs_inr"]),
            pp_block_pct=d(t["PP"]["block_pct"]), dq_default_pct=d(t["DQ"]["default_pct"]),
            dq_bulk_mt_pct=d(t["DQ"]["bulk_mt_pct"]), dq_block_pct=d(t["DQ"].get("block_pct", 5)),
            bd_abs=d(t["BD"]["auto_accept_inr"]), version=version,
            fx=tuple((c.upper(), d(r)) for c, r in (data.get("fx") or {}).get("rates", {}).items() if r),
            fx_as_of=str((data.get("fx") or {}).get("as_of", "")),
        )
