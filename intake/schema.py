"""Strict quote schema plus per-field provenance."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from intake.catalog import Condition, Sku


class Status(str, Enum):
    OK = "ok"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"
    MISSING = "missing"


class Extractor(str, Enum):
    RULE = "rule"
    LLM = "llm"
    MOCK = "mock"
    REVIEWER = "reviewer"


class QuoteStatus(str, Enum):
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


QUOTE_FIELDS: tuple[str, ...] = (
    "gpu_sku",
    "gpus_per_node",
    "node_count",
    "condition",
    "location",
    "unit_price_usd",
    "total_price_usd",
    "lead_time_days",
    "dealer",
    "valid_until",
)

FIELD_LABELS = {
    "gpu_sku": "GPU SKU",
    "gpus_per_node": "GPUs / node",
    "node_count": "Nodes",
    "condition": "Condition",
    "location": "Location",
    "unit_price_usd": "Unit price (USD / node)",
    "total_price_usd": "Total (USD)",
    "lead_time_days": "Lead time (days)",
    "dealer": "Dealer",
    "valid_until": "Valid until",
}


class RawCell(BaseModel):
    """A raw value pulled from a file, before normalization."""

    text: str
    source: str  # cell ref ("C7") or email line ("L12")
    extractor: Extractor = Extractor.RULE
    currency_hint: str | None = None  # e.g. from a "Price (EUR)" header


class FieldResult(BaseModel):
    """One normalized field with its provenance and status."""

    value: Any = None  # JSON-safe: str, int, float or ISO date string
    raw: str | None = None
    status: Status
    source: str | None = None
    extractor: Extractor | None = None
    reason: str | None = None
    code: str | None = None  # machine-readable reason, e.g. "total_mismatch"


class Quote(BaseModel):
    """A fully validated quote. Only built when every field is ok."""

    model_config = ConfigDict(strict=True, frozen=True)

    gpu_sku: Sku
    gpus_per_node: PositiveInt
    node_count: PositiveInt
    condition: Condition
    location: str = Field(min_length=1)
    unit_price_usd: Decimal = Field(gt=0)
    total_price_usd: Decimal = Field(gt=0)
    lead_time_days: int = Field(ge=0)
    dealer: str = Field(min_length=1)
    valid_until: date

    @classmethod
    def from_fields(cls, fields: dict[str, FieldResult]) -> "Quote":
        bad = [n for n in QUOTE_FIELDS if fields[n].status != Status.OK]
        if bad:
            raise ValueError(f"fields not ok: {', '.join(bad)}")
        v = {n: fields[n].value for n in QUOTE_FIELDS}
        return cls(
            gpu_sku=Sku(v["gpu_sku"]),
            gpus_per_node=int(v["gpus_per_node"]),
            node_count=int(v["node_count"]),
            condition=Condition(v["condition"]),
            location=str(v["location"]),
            unit_price_usd=Decimal(str(v["unit_price_usd"])),
            total_price_usd=Decimal(str(v["total_price_usd"])),
            lead_time_days=int(v["lead_time_days"]),
            dealer=str(v["dealer"]),
            valid_until=date.fromisoformat(v["valid_until"]),
        )
