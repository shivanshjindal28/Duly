"""Small HSN/SAC -> allowed GST rate table for Plant X's spend categories.

ASSUMPTION, verify with the tax team: rates are illustrative for the demo and change with
GST Council notifications. Where a code legitimately has more than one rate (for example
road freight under different GTA options), every allowed rate is listed. Lookups match
the longest known prefix, so "848210" uses the "8482" entry.
"""
from __future__ import annotations

from decimal import Decimal

D = Decimal

HSN_RATES: dict[str, tuple[str, frozenset[Decimal]]] = {
    "3901": ("Polymers of ethylene", frozenset({D(18)})),
    "3902": ("Polymers of propylene", frozenset({D(18)})),
    "3812": ("Plastic additives and stabilisers", frozenset({D(18)})),
    "3815": ("Catalysts", frozenset({D(18)})),
    "3923": ("Plastic sacks and bags (FFS bags)", frozenset({D(18)})),
    "6305": ("Jumbo bags (FIBC)", frozenset({D(5), D(12)})),
    "4415": ("Wooden pallets", frozenset({D(5), D(12)})),
    "8413": ("Pumps and pump parts", frozenset({D(18)})),
    "8482": ("Ball and roller bearings", frozenset({D(18)})),
    "8484": ("Gaskets and mechanical seals", frozenset({D(18)})),
    "9965": ("Goods transport services", frozenset({D(5), D(12), D(18)})),
    "9983": ("Technical testing and calibration", frozenset({D(18)})),
    "9987": ("Maintenance and repair services", frozenset({D(18)})),
}


def lookup(code: str | None) -> tuple[str, str, frozenset[Decimal]] | None:
    """Return (matched prefix, description, allowed rates) or None if the code is unknown."""
    if not code:
        return None
    for n in range(len(code), 3, -1):
        hit = HSN_RATES.get(code[:n])
        if hit:
            return code[:n], hit[0], hit[1]
    return None
