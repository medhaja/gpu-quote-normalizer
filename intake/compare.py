"""Like-for-like comparison for one RFQ.

A quote is comparable only if its canonical SKU, GPUs per node and condition all
match the RFQ and every field is ok. Everything else that looks related (same
GPU family) is listed as excluded, with the reasons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from intake.pipeline import QuoteView
from intake.schema import FIELD_LABELS, QUOTE_FIELDS, QuoteStatus, Status

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_rfqs(path: Path = DATA_DIR / "rfqs.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Row:
    view: QuoteView
    unit: float
    per_gpu: float
    delta_pct: float = 0.0


@dataclass
class Comparison:
    rfq: dict
    comparable: list[Row] = field(default_factory=list)
    excluded: list[tuple[QuoteView, list[str]]] = field(default_factory=list)

    @property
    def spread(self) -> tuple[float, float] | None:
        if not self.comparable:
            return None
        units = [r.unit for r in self.comparable]
        return min(units), max(units)


def exclusion_reasons(v: QuoteView, rfq: dict) -> list[str]:
    reasons: list[str] = []
    if v.status == QuoteStatus.REJECTED:
        reasons.append(v.status_reason)
    f = v.fields
    checks = [("gpu_sku", rfq["gpu_sku"], "SKU is {got}; RFQ wants {want}"),
              ("gpus_per_node", rfq["gpus_per_node"], "{got} GPUs/node; RFQ wants {want}"),
              ("condition", rfq["condition"], "condition is {got}; RFQ wants {want}")]
    for name, want, msg in checks:
        r = f[name]
        if r.status == Status.OK and r.value != want:
            reasons.append(msg.format(got=r.value, want=want))
        elif r.status != Status.OK:
            reasons.append(f"{FIELD_LABELS[name]} {r.status.value}: {r.reason}")
    for name in QUOTE_FIELDS:
        r = f[name]
        if name in ("gpu_sku", "gpus_per_node", "condition") or r.status == Status.OK:
            continue
        if r.code == "expired" and v.status == QuoteStatus.REJECTED:
            continue  # already explained by the rejection reason
        reasons.append(f"{FIELD_LABELS[name]} {r.status.value}: {r.reason}")
    return reasons


def compare(views: dict[str, QuoteView], rfq: dict) -> Comparison:
    family = rfq["gpu_sku"].split("-")[0].lower()
    out = Comparison(rfq)
    for v in views.values():
        sku = v.fields["gpu_sku"]
        text = f"{sku.value or ''} {sku.raw or ''}".lower()
        if family not in text:
            continue
        reasons = exclusion_reasons(v, rfq)
        if reasons:
            out.excluded.append((v, reasons))
        else:
            unit = float(v.value("unit_price_usd"))
            out.comparable.append(Row(v, unit, unit / int(v.value("gpus_per_node"))))
    out.comparable.sort(key=lambda r: r.unit)
    if out.comparable:
        best = out.comparable[0].unit
        for r in out.comparable:
            r.delta_pct = (r.unit - best) / best * 100
    out.excluded.sort(key=lambda x: quote_sort_key(x[0].quote_id))
    return out


def quote_sort_key(quote_id: str) -> tuple[int, int]:
    """'Q12.3' -> (12, 3) so Q2 sorts before Q11."""
    a, _, b = quote_id.lstrip("Q").partition(".")
    return int(a), int(b or 0)
