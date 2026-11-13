"""Units of measure: standard conversions by dimension plus item-specific pack sizes. Pure.

Standard units convert within their dimension (mass, volume, length, count). Pack units are
item master data ("1 BOX of BRG-6205 = 10 NOS", "1 BAG of ADD-AO-1010 = 25 KG") and convert
through the unit they contain, so a supplier may bill in boxes or bags while the PO is in pieces
or tonnes. Units with no rule (LS for a lump sum, TRIP) only match themselves.
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

D = Decimal

# dimension -> (base unit, {unit: how many base units in one unit})
DIMENSIONS: dict[str, tuple[str, dict[str, Decimal]]] = {
    "mass": ("KG", {"MG": D("0.000001"), "G": D("0.001"), "KG": D(1), "QTL": D(100), "MT": D(1000)}),
    "volume": ("L", {"ML": D("0.001"), "L": D(1), "KL": D(1000)}),
    "length": ("M", {"MM": D("0.001"), "CM": D("0.01"), "M": D(1), "KM": D(1000)}),
    "count": ("NOS", {"NOS": D(1), "PAIR": D(2), "DOZ": D(12), "GROSS": D(144)}),
}

# How invoices spell units -> the unit code Duly uses.
ALIASES = {
    "NO": "NOS", "NOS.": "NOS", "NUMBERS": "NOS", "PCS": "NOS", "PC": "NOS", "PIECE": "NOS", "PIECES": "NOS",
    "EA": "NOS", "EACH": "NOS", "UNIT": "NOS", "UNITS": "NOS", "UN": "NOS",
    "KGS": "KG", "KILO": "KG", "KILOGRAM": "KG", "KILOGRAMS": "KG",
    "GM": "G", "GMS": "G", "GR": "G", "GRAM": "G", "GRAMS": "G",
    "TON": "MT", "TONS": "MT", "TONNE": "MT", "TONNES": "MT", "MTS": "MT", "T": "MT",
    "QUINTAL": "QTL", "QTLS": "QTL",
    "LTR": "L", "LTRS": "L", "LT": "L", "LIT": "L", "LITRE": "L", "LITRES": "L", "LITER": "L", "LITERS": "L",
    "KLTR": "KL", "KILOLITRE": "KL", "MLTR": "ML", "MILLILITRE": "ML",
    "MTR": "M", "MTRS": "M", "RMT": "M", "METRE": "M", "METRES": "M", "METER": "M", "METERS": "M",
    "DZ": "DOZ", "DOZEN": "DOZ", "PR": "PAIR", "PRS": "PAIR", "PAIRS": "PAIR",
    "BOXES": "BOX", "BX": "BOX", "BAGS": "BAG", "DRUMS": "DRUM", "DRM": "DRUM", "BDL": "BUNDLE", "BUNDLES": "BUNDLE",
}

# One pack unit: 1 `unit` = `qty` `base_unit` (e.g. ("BOX", 10, "NOS")).
Pack = tuple[str, Decimal, str]


def norm(unit: str | None) -> str:
    u = (unit or "").strip().upper()
    if u in ALIASES:
        return ALIASES[u]
    u = u.rstrip(".")
    return ALIASES.get(u, u)


def _packs(packs: Iterable[Pack] | None) -> dict[str, tuple[Decimal, str]]:
    return {norm(u): (D(str(q)), norm(b)) for u, q, b in (packs or ())}


def _resolve(unit: str, packs: dict[str, tuple[Decimal, str]], depth: int = 0) -> tuple[str, Decimal] | None:
    """(base unit of its dimension, how many base units in one `unit`) or None if unknown."""
    if unit in packs and depth < 3:
        qty, inner = packs[unit]
        r = _resolve(inner, packs, depth + 1)
        return (r[0], qty * r[1]) if r else (inner, qty)
    for base, table in DIMENSIONS.values():
        if unit in table:
            return base, table[unit]
    return None


def factor(from_unit: str, to_unit: str, packs: Iterable[Pack] | None = None) -> Decimal | None:
    """How many `to_unit` are in one `from_unit` (qty_to = qty_from * factor); None if not convertible."""
    f, t = norm(from_unit), norm(to_unit)
    if f == t:
        return D(1)
    p = _packs(packs)
    a, b = _resolve(f, p), _resolve(t, p)
    if a is None or b is None or a[0] != b[0]:
        return None
    return a[1] / b[1]


def convertible_units(to_unit: str, packs: Iterable[Pack] | None = None) -> list[str]:
    """Every unit that can be converted to `to_unit` (for unit pickers): itself, its dimension, its packs."""
    t = norm(to_unit)
    p = _packs(packs)
    out = [t]
    target = _resolve(t, p)
    if target is None:
        return out
    for _dim, (base, table) in DIMENSIONS.items():
        if base == target[0]:
            out += [u for u in table if u not in out]
    out += [u for u in p if u not in out and factor(u, t, packs) is not None]
    return out


def describe(from_unit: str, to_unit: str, packs: Iterable[Pack] | None = None) -> str:
    """Human text for the conversion, e.g. '1 BOX = 10 NOS' or '1 KG = 0.001 MT'."""
    f = factor(from_unit, to_unit, packs)
    if f is None:
        return f"{norm(from_unit)} cannot be converted to {norm(to_unit)}"
    return f"1 {norm(from_unit)} = {f.normalize():f} {norm(to_unit)}"
