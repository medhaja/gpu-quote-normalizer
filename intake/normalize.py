"""Turn raw cells into typed field values with a status.

Every parser here is strict: it either produces a value it can defend
(status ok) or explains why it could not (ambiguous / invalid / missing).
"""

from __future__ import annotations

import re
from datetime import date, datetime

from intake.catalog import Condition, match_condition, match_sku
from intake.schema import QUOTE_FIELDS, Extractor, FieldResult, RawCell, Status

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

Parsed = tuple[object, Status, str | None]  # (value, status, reason)


def parse_int(text: str, *, allow_zero: bool = False) -> Parsed:
    t = text.strip().lower()
    m = re.fullmatch(r"(\d+)(?:\.0+)?\s*(?:x|×|gpus?|nodes?|servers?|units?|systems?)?", t)
    if not m:
        return None, Status.INVALID, f"'{text}' is not a whole number"
    n = int(m.group(1))
    if n <= 0 and not allow_zero:
        return None, Status.INVALID, "quantity must be greater than 0"
    return n, Status.OK, None


MONEY_RE = re.compile(
    r"(?P<pre>us\$|\$|€|usd|eur)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<k>k)?\s*(?P<post>usd|eur|€|\$)?"
)
CURRENCY_TOKENS = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR"}


def parse_money(text: str) -> tuple[float | None, str | None, str | None]:
    """Return (amount, currency found in the text, error)."""
    t = text.strip().lower()
    m = MONEY_RE.fullmatch(t)
    if not m:
        return None, None, f"'{text}' is not a price"
    amount = float(m.group("num").replace(",", ""))
    if m.group("k"):
        amount *= 1000
    curs = {CURRENCY_TOKENS[c] for c in (m.group("pre"), m.group("post")) if c}
    if len(curs) > 1:
        return None, None, f"'{text}' names two currencies"
    if amount <= 0:
        return None, None, "price must be greater than 0"
    return round(amount, 2), (curs.pop() if curs else None), None


def parse_lead_time(text: str) -> Parsed:
    t = text.strip().lower()
    t = re.sub(r"^(approx\.?|about|around|~)\s*", "", t)
    word = "|".join(NUMBER_WORDS)
    if re.search(r"\d+\s*(?:-|–|to)\s*\d+", t):
        return None, Status.AMBIGUOUS, f"'{text}' is a range, not a single lead time"
    m = re.fullmatch(rf"(\d+|{word})\s*(business\s+)?(days?|d|weeks?|wks?|w)?", t)
    if not m:
        return None, Status.INVALID, f"'{text}' is not a duration"
    n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS[m.group(1)]
    if m.group(2):
        return None, Status.AMBIGUOUS, f"'{text}' is in business days, not calendar days"
    unit = m.group(3) or "days"
    return (n * 7 if unit.startswith("w") else n), Status.OK, None


DATE_FORMATS = ("%Y-%m-%d", "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y")


def parse_date(text: str) -> Parsed:
    t = re.sub(r"[,.]", " ", text.strip())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"T00:00:00$|\s00:00:00$", "", t)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date().isoformat(), Status.OK, None
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a <= 12 and b <= 12 and a != b:
            return None, Status.AMBIGUOUS, f"'{text}' could be month/day or day/month"
        month, day = (a, b) if a <= 12 else (b, a)
        try:
            return date(y, month, day).isoformat(), Status.OK, None
        except ValueError:
            pass
    return None, Status.INVALID, f"'{text}' is not a date"


def parse_text(text: str) -> Parsed:
    t = re.sub(r"\s+", " ", text).strip()
    if not re.search(r"[A-Za-z]", t):
        return None, Status.INVALID, f"'{text}' has no letters"
    return t, Status.OK, None


def _result(cell: RawCell | None, value, status, reason, code=None) -> FieldResult:
    return FieldResult(
        value=value if status == Status.OK else None,
        raw=cell.text if cell else None,
        status=status,
        source=cell.source if cell else None,
        extractor=cell.extractor if cell else None,
        reason=reason,
        code=code,
    )


def normalize_field(name: str, cell: RawCell | None, row_currency: RawCell | None = None) -> FieldResult:
    """Normalize one field. ``row_currency`` is a currency column cell, if any."""
    if name == "condition" and (cell is None or not cell.text.strip()):
        r = _result(cell, None, Status.MISSING, "condition not stated; it is never inferred", "condition_missing")
        r.value = Condition.UNKNOWN.value
        return r
    if cell is None or not cell.text.strip():
        return _result(cell, None, Status.MISSING, "not found in source", "missing")

    text = cell.text
    if name == "gpu_sku":
        m = match_sku(text)
        return _result(cell, m.sku.value if m.sku else None, Status(m.status), m.reason)
    if name == "condition":
        c = match_condition(text)
        if c is None:
            return _result(cell, None, Status.AMBIGUOUS, f"'{text}' is not a known condition")
        return _result(cell, c.value, Status.OK, None)
    if name in ("gpus_per_node", "node_count"):
        return _result(cell, *parse_int(text))
    if name == "lead_time_days":
        return _result(cell, *parse_lead_time(text))
    if name == "valid_until":
        return _result(cell, *parse_date(text))
    if name in ("location", "dealer"):
        return _result(cell, *parse_text(text))
    if name in ("unit_price_usd", "total_price_usd"):
        amount, cur, err = parse_money(text)
        if err:
            return _result(cell, None, Status.INVALID, err)
        found = {c for c in (cur, cell.currency_hint, _currency_of(row_currency)) if c}
        if not found:
            return _result(cell, None, Status.AMBIGUOUS, "currency not stated", "currency_unknown")
        if len(found) > 1:
            return _result(cell, None, Status.AMBIGUOUS, f"conflicting currencies: {', '.join(sorted(found))}")
        cur = found.pop()
        if cur != "USD":
            return _result(cell, None, Status.INVALID,
                           f"quoted in {cur} ({text}); intake does not convert currency", "non_usd")
        return _result(cell, amount, Status.OK, None)
    raise KeyError(name)


def _currency_of(cell: RawCell | None) -> str | None:
    if cell is None:
        return None
    return CURRENCY_TOKENS.get(cell.text.strip().lower(), cell.text.strip().upper() or None)


def normalize_quote(raw: dict[str, RawCell]) -> dict[str, FieldResult]:
    return {name: normalize_field(name, raw.get(name), raw.get("currency")) for name in QUOTE_FIELDS}


def normalize_reviewer_value(name: str, text: str) -> FieldResult:
    """Reviewer input goes through the same parsers; currency is USD by definition."""
    cell = RawCell(text=text, source="reviewer", extractor=Extractor.REVIEWER, currency_hint="USD")
    if name == "condition" and text.strip().lower() == Condition.UNKNOWN.value:
        # A human may confirm that the condition is genuinely unknown.
        return _result(cell, Condition.UNKNOWN.value, Status.OK, None)
    return normalize_field(name, cell)
