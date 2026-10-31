"""Shared line-level patterns used by the email extractor and spreadsheet preambles.

Each pattern captures the raw span for one field. The span is then parsed by
``intake.normalize``; the patterns only locate text, they never decide values.
"""

from __future__ import annotations

import re

FAMILY = r"(?:h100|h200|a100|b200|l40s)"
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"  # never ends on a comma
MONEY = rf"(?:[$€]\s?{_NUM}k?|(?:usd|eur)\s?{_NUM}k?|{_NUM}\s?(?:usd|eur))"
DATE = (r"(?:[A-Za-z]{3,9}\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}"
        r"|\d{1,2} [A-Za-z]{3,9},? \d{4})")
CITY = r"([A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+)*,\s*[A-Z]{2})\b"

I = re.IGNORECASE

LINE_PATTERNS: dict[str, list[re.Pattern]] = {
    "gpu_sku": [
        re.compile(rf"(?<![a-z0-9])((?:nvidia\s+)?{FAMILY}(?:[\s-]*(?:sxm\d?|pcie|pci-e|hgx|\d{{2,3}}\s?gb?))*)(?![a-z0-9])", I),
    ],
    "gpus_per_node": [
        re.compile(r"(?<![\d,.])(\d+)[\s-]*gpus?\b", I),
        re.compile(rf"(?<![\d,.])(\d+)\s*[x×]\s*(?:nvidia\s+)?{FAMILY}[^.\n]*?\bper (?:node|server)\b", I),
    ],
    "node_count": [
        re.compile(r"\b(?:qty|quantity|node count)\s*[:=]?\s*(\d+)\b", I),
        re.compile(r"(?<![\w,.$€-])(\d+)\s*(?:x\s+)?(?:(?:[a-z][\w-]*|\d+-gpu|\d+gb?)\s+){0,6}?(?:nodes|servers|systems)\b", I),
    ],
    "unit_price_usd": [
        re.compile(rf"\b(?:unit price|price per node|per[- ]node price|price/node)\s*[:=]?\s*(?:is\s+)?({MONEY})", I),
        re.compile(rf"({MONEY})\s*(?:per|/|each|a)\s*(?:node|server|system)\b", I),
    ],
    "total_price_usd": [
        re.compile(rf"\btotal(?: price)?(?: for the order)?\s*(?:is|of|:|=|comes to)?\s*({MONEY})", I),
    ],
    "lead_time_days": [
        re.compile(r"\b(?:lead time|ships? in|delivery in)\s*(?:is|of|:)?\s*"
                   r"((?:approx\.?\s*|about\s+|~)?\d+(?:\s*[-–]\s*\d+)?\s*(?:business\s+)?(?:days?|weeks?))", I),
    ],
    "valid_until": [
        re.compile(rf"\b(?:valid (?:until|through|thru)|expires(?: on)?|good through|validity)\s*[:\-]?\s*({DATE})", I),
    ],
    "condition": [
        re.compile(r"\bcondition\s*[:\-]\s*([a-z][a-z -]*[a-z])", I),
        re.compile(r"\b(brand[- ]new|new|refurbished|refurb|recertified|used|pre-owned)\b"
                   r"(?=\s*(?:units?\b|nodes?\b|servers?\b|systems?\b|condition\b|in box\b|,|\.|;|$))", I),
    ],
    "location": [
        # Keyword is case-insensitive; the city itself must be capitalised ("Dallas, TX").
        re.compile(rf"\b(?i:ships? from|shipping from|located in|location|warehouse in|in stock (?:in|at))\s*[:\-]?\s*{CITY}"),
    ],
    "dealer": [
        re.compile(r"\b(?:dealer|vendor|supplier|quote from|quotation from)\s*[:\-–—]\s*(.+?)\s*$", I),
    ],
    "currency": [
        re.compile(r"\b(?:all )?prices? (?:are )?(?:in|quoted in)\s+(usd|eur)\b", I),
        re.compile(r"\bcurrency\s*[:=]\s*(usd|eur)\b", I),
    ],
}


def find_in_line(field: str, line: str) -> str | None:
    for pat in LINE_PATTERNS[field]:
        m = pat.search(line)
        if m:
            return m.group(1).strip()
    return None
