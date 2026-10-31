"""Gap-fillers for free-text emails: a deterministic mock (default) and an optional LLM.

Both return the same shape: ``{field: {"span": "<exact text>", "line": <1-based line no>}}``.
They only *locate* text. ``ground()`` then checks the span really is on that line,
and the normal deterministic parsers decide the value and status. So neither
extractor can mark a field ok by itself, and a hallucinated span is dropped.
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable

from intake.normalize import NUMBER_WORDS
from intake.parsers.patterns import CITY, DATE, MONEY
from intake.schema import Extractor, RawCell

Lines = list[tuple[int, str]]  # (1-based line number, text)
GapFiller = Callable[[Lines, list[str]], dict[str, dict]]

GAP_FIELDS = ("location", "lead_time_days", "unit_price_usd", "total_price_usd", "valid_until")

_WORD = "|".join(NUMBER_WORDS)
MOCK_RULES: dict[str, tuple[re.Pattern, re.Pattern]] = {
    # field: (line must contain, span pattern)
    "lead_time_days": (re.compile(r"deliver|ship|lead|arriv|eta|out\b", re.I),
                       re.compile(rf"\b((?:about |around |approx\.? )?(?:\d+|{_WORD})\s+(?:business\s+)?(?:days?|weeks?))\b", re.I)),
    "location": (re.compile(r".", re.I), re.compile(CITY)),
    "unit_price_usd": (re.compile(r"node|server|box|each|unit", re.I), re.compile(rf"({MONEY})", re.I)),
    "total_price_usd": (re.compile(r"total|all-in|altogether|overall", re.I), re.compile(rf"({MONEY})", re.I)),
    "valid_until": (re.compile(r"valid|expire|good (?:through|until)", re.I), re.compile(rf"({DATE})")),
}


def mock_extract(lines: Lines, missing: list[str]) -> dict[str, dict]:
    """Deterministic stand-in for an LLM: keyword-proximity span finding."""
    found: dict[str, dict] = {}
    for field in missing:
        if field not in MOCK_RULES:
            continue
        gate, pat = MOCK_RULES[field]
        for n, text in lines:
            if gate.search(text) and (m := pat.search(text)):
                found[field] = {"span": m.group(1).strip(), "line": n}
                break
    return found


LLM_PROMPT = """You extract fields from a GPU server quote email.
Fields wanted: {fields}.
Return a JSON object mapping each field you can find to {{"span": "<text copied exactly from the line>", "line": <line number>}}.
Copy spans verbatim. Do not compute, convert or infer anything. Omit any field the text does not state.

Email (line numbers on the left):
{body}"""


def llm_extract(lines: Lines, missing: list[str], completion=None) -> dict[str, dict]:
    """Call an LLM through LiteLLM. ``completion`` can be injected for tests."""
    if completion is None:
        import litellm  # optional dependency, see requirements-llm.txt

        completion = litellm.completion
    body = "\n".join(f"{n:>3}: {t}" for n, t in lines)
    resp = completion(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": LLM_PROMPT.format(fields=", ".join(missing), body=body)}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return parse_llm_json(resp.choices[0].message.content, missing)


def parse_llm_json(text: str, allowed: list[str]) -> dict[str, dict]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    out = {}
    for field, v in (data or {}).items():
        if field in allowed and isinstance(v, dict) and isinstance(v.get("span"), str) and isinstance(v.get("line"), int):
            out[field] = {"span": v["span"], "line": v["line"]}
    return out


def active_extractor() -> tuple[Extractor, GapFiller]:
    """LLM when LLM_PROVIDER is set, otherwise the deterministic mock."""
    if os.environ.get("LLM_PROVIDER"):
        return Extractor.LLM, llm_extract
    return Extractor.MOCK, mock_extract


def ground(found: dict[str, dict], lines: Lines, extractor: Extractor) -> tuple[dict[str, RawCell], list[str]]:
    """Keep only spans that appear verbatim on the cited line."""
    by_no = dict(lines)
    cells: dict[str, RawCell] = {}
    notes: list[str] = []
    for field, hit in found.items():
        text = by_no.get(hit["line"], "")
        span = hit["span"].strip()
        if span and span.lower() in text.lower():
            cells[field] = RawCell(text=span, source=f"L{hit['line']}", extractor=extractor)
        else:
            notes.append(f"{extractor.value} span for {field} not found on line {hit['line']}; ignored")
    return cells, notes
