"""Canonical GPU SKU and condition catalog.

The catalog is intentionally small. Normalization is exact and rule-based:
a raw string either maps to exactly one canonical SKU (ok), to several
(ambiguous), or to none (invalid). Nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Sku(str, Enum):
    H100_SXM5_80GB = "H100-SXM5-80GB"
    H100_PCIE_80GB = "H100-PCIE-80GB"
    H200_SXM_141GB = "H200-SXM-141GB"
    A100_SXM4_40GB = "A100-SXM4-40GB"
    A100_SXM4_80GB = "A100-SXM4-80GB"
    B200_SXM_192GB = "B200-SXM-192GB"
    L40S_PCIE_48GB = "L40S-PCIE-48GB"


class Condition(str, Enum):
    NEW = "new"
    REFURBISHED = "refurbished"
    USED = "used"
    UNKNOWN = "unknown"


# Explicit synonyms only. Anything else is ambiguous; a blank is "unknown".
CONDITION_SYNONYMS: dict[str, Condition] = {
    "new": Condition.NEW,
    "brand new": Condition.NEW,
    "brand-new": Condition.NEW,
    "new in box": Condition.NEW,
    "nib": Condition.NEW,
    "refurbished": Condition.REFURBISHED,
    "refurb": Condition.REFURBISHED,
    "recertified": Condition.REFURBISHED,
    "used": Condition.USED,
    "pre-owned": Condition.USED,
    "preowned": Condition.USED,
    "second hand": Condition.USED,
    "second-hand": Condition.USED,
}

FAMILY_RE = re.compile(r"(?<![a-z0-9])(h100|h200|a100|b200|l40s)(?![0-9])")
SXM_RE = re.compile(r"sxm")
PCIE_RE = re.compile(r"pci\s*-?\s*e")
MEM_RE = re.compile(r"(?<![0-9])(40|80)\s*g")


@dataclass(frozen=True)
class SkuMatch:
    sku: Sku | None
    candidates: tuple[Sku, ...]

    @property
    def status(self) -> str:
        if self.sku is not None:
            return "ok"
        return "ambiguous" if len(self.candidates) > 1 else "invalid"

    @property
    def reason(self) -> str | None:
        if self.sku is not None:
            return None
        if len(self.candidates) > 1:
            return "matches " + " and ".join(c.value for c in self.candidates)
        return "no catalog SKU matches"


def match_sku(raw: str) -> SkuMatch:
    """Map a raw GPU description to the catalog."""
    text = (raw or "").lower()
    families = sorted(set(FAMILY_RE.findall(text)))
    if not families:
        return SkuMatch(None, ())
    if len(families) > 1:
        # Several GPU families in one cell: never pick one.
        return SkuMatch(None, tuple(s for f in families for s in _family_candidates(f, text)))
    cands = _family_candidates(families[0], text)
    if len(cands) == 1:
        return SkuMatch(cands[0], cands)
    return SkuMatch(None, cands)


def _family_candidates(family: str, text: str) -> tuple[Sku, ...]:
    if family == "h100":
        sxm, pcie = bool(SXM_RE.search(text)), bool(PCIE_RE.search(text))
        if sxm and not pcie:
            return (Sku.H100_SXM5_80GB,)
        if pcie and not sxm:
            return (Sku.H100_PCIE_80GB,)
        return (Sku.H100_SXM5_80GB, Sku.H100_PCIE_80GB)
    if family == "a100":
        mems = set(MEM_RE.findall(text))
        if mems == {"40"}:
            return (Sku.A100_SXM4_40GB,)
        if mems == {"80"}:
            return (Sku.A100_SXM4_80GB,)
        return (Sku.A100_SXM4_40GB, Sku.A100_SXM4_80GB)
    return {
        "h200": (Sku.H200_SXM_141GB,),
        "b200": (Sku.B200_SXM_192GB,),
        "l40s": (Sku.L40S_PCIE_48GB,),
    }[family]


def match_condition(raw: str) -> Condition | None:
    """Return a condition for an explicit synonym, else None."""
    key = re.sub(r"\s+", " ", (raw or "").strip().lower())
    return CONDITION_SYNONYMS.get(key)
