"""Cross-field validators and quote-level status.

Field-level checks (types, currency, quantity > 0, missing condition) live in
``normalize``. The checks here need more than one field. Flags raised here keep
the parsed value (so a reviewer can see it) but set status to ``invalid``; they
are recomputed from scratch on every validation run.
"""

from __future__ import annotations

from datetime import date

from intake.schema import QUOTE_FIELDS, FieldResult, QuoteStatus, Status

TOLERANCE_USD = 1.0
CROSS_FIELD_CODES = {"total_mismatch", "expired"}


def validate(fields: dict[str, FieldResult], as_of: date) -> dict[str, FieldResult]:
    out = {n: _reset(f) for n, f in fields.items()}

    unit, nodes, total = out["unit_price_usd"], out["node_count"], out["total_price_usd"]
    if all(f.status == Status.OK for f in (unit, nodes, total)):
        expected = round(float(unit.value) * int(nodes.value), 2)
        if abs(float(total.value) - expected) > TOLERANCE_USD:
            out["total_price_usd"] = total.model_copy(update={
                "status": Status.INVALID,
                "code": "total_mismatch",
                "reason": (f"total ${float(total.value):,.2f} ≠ unit ${float(unit.value):,.2f} "
                           f"× {nodes.value} nodes = ${expected:,.2f}"),
            })

    vu = out["valid_until"]
    if vu.status == Status.OK and date.fromisoformat(vu.value) < as_of:
        out["valid_until"] = vu.model_copy(update={
            "status": Status.INVALID,
            "code": "expired",
            "reason": f"quote expired on {vu.value} (as of {as_of.isoformat()})",
        })
    return out


def _reset(f: FieldResult) -> FieldResult:
    if f.code in CROSS_FIELD_CODES and f.value is not None:
        return f.model_copy(update={"status": Status.OK, "code": None, "reason": None})
    return f


def quote_status(fields: dict[str, FieldResult], rejected_reason: str | None = None) -> tuple[QuoteStatus, str]:
    if rejected_reason:
        return QuoteStatus.REJECTED, f"rejected by reviewer: {rejected_reason}"
    if fields["valid_until"].code == "expired":
        return QuoteStatus.REJECTED, fields["valid_until"].reason or "expired"
    bad = [n for n in QUOTE_FIELDS if fields[n].status != Status.OK]
    if bad:
        return QuoteStatus.NEEDS_REVIEW, f"{len(bad)} field(s) need review: {', '.join(bad)}"
    return QuoteStatus.PARSED, "all fields ok"
