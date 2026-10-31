"""Rule-based extractor for plain-text quote emails (.eml / .txt).

Handles prose, inline pipe tables, forwarded chains (the innermost From: is the
dealer) and several quotes in one email ("Option A:", "Option B:" ...).
Fields the rules miss are offered to the gap-filler (mock or LLM).
"""

from __future__ import annotations

import re

from intake.extractors import GAP_FIELDS, active_extractor, ground
from intake.parsers.base import ParsedFile
from intake.parsers.patterns import find_in_line
from intake.parsers.spreadsheet import PRICE_FIELDS, map_columns, normalize_header
from intake.schema import QUOTE_FIELDS, RawCell

HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z-]*:\s")
FROM_RE = re.compile(r"^From:\s*(.+)$", re.I)
QUOTE_PREFIX_RE = re.compile(r"^\s*(?:>\s?)+")
BLOCK_START_RE = re.compile(r"^\s*(?:(?:option|quote|config(?:uration)?)\s*[A-Z0-9#]{0,3}\s*[:.)\-–]|\d+[.)]\s)", re.I)
TABLE_SEP_RE = re.compile(r"^[\s|:\-]+$")
EMAIL_FIELDS = QUOTE_FIELDS + ("currency",)
SHARED_FIELDS = ("dealer", "location", "valid_until", "currency", "condition", "lead_time_days")

Lines = list[tuple[int, str]]


def _strip(line: str) -> str:
    return QUOTE_PREFIX_RE.sub("", line).rstrip()


def _dealer_from(value: str) -> str | None:
    m = re.match(r'^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$', value)
    if m:
        return m.group(1).strip()
    return None if "@" in value else value.strip() or None


def _scan(lines: Lines, fields) -> dict[str, RawCell]:
    cells: dict[str, RawCell] = {}
    for field in fields:
        for n, text in lines:
            span = find_in_line(field, text)
            if span:
                cells[field] = RawCell(text=span, source=f"L{n}")
                break
    return cells


def _table(body: Lines) -> tuple[list[dict[str, RawCell]], set[int]]:
    """Parse an inline pipe table, if there is one."""
    pipe = [(n, t) for n, t in body if t.count("|") >= 3]
    for idx, (n, t) in enumerate(pipe):
        header = [c.strip() for c in t.strip().strip("|").split("|")]
        mapping, _ = map_columns(header)
        if len(mapping) < 3:
            continue
        used = {n}
        rows: list[dict[str, RawCell]] = []
        for rn, rt in pipe[idx + 1:]:
            used.add(rn)
            if TABLE_SEP_RE.match(rt):
                continue
            vals = [c.strip() for c in rt.strip().strip("|").split("|")]
            row: dict[str, RawCell] = {}
            for i, field in mapping.items():
                if i < len(vals) and vals[i]:
                    hint = normalize_header(header[i])[1] if field in PRICE_FIELDS else None
                    row[field] = RawCell(text=vals[i], source=f"L{rn}", currency_hint=hint)
            if len(row) >= 3:
                rows.append(row)
        return rows, used
    return [], set()


def _blocks(body: Lines) -> list[tuple[str, Lines]]:
    starts = [i for i, (_, t) in enumerate(body) if BLOCK_START_RE.match(t)]
    if len(starts) < 2:
        return []
    blocks = []
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(body)
        chunk: Lines = []
        for n, t in body[s:end]:
            if not t.strip():
                break
            chunk.append((n, t))
        label = re.match(r"^\s*([^:.)\-–]+)", chunk[0][1]).group(1).strip()
        blocks.append((label, chunk))
    return blocks


def parse_email(filename: str, content: bytes, gap_filler: tuple | None = None) -> ParsedFile:
    """``gap_filler`` is an optional (Extractor, function) pair; defaults to mock or LLM by env."""
    text = content.decode("utf-8", errors="replace").replace("\r\n", "\n")
    raw_lines = text.split("\n")
    out = ParsedFile(kind="email", lines=raw_lines)

    body_start = 0
    if raw_lines and HEADER_RE.match(raw_lines[0]):
        for i, line in enumerate(raw_lines):
            if not line.strip():
                body_start = i + 1
                break
    numbered: Lines = [(i + 1, _strip(t)) for i, t in enumerate(raw_lines)]
    body = numbered[body_start:]

    # Dealer: an explicit "Dealer:" line wins, else the innermost From: (forwarded chains).
    shared: dict[str, RawCell] = {}
    froms = [(n, m.group(1)) for n, t in numbered if (m := FROM_RE.match(t))]
    if froms:
        n, value = froms[-1]
        name = _dealer_from(value)
        if name:
            shared["dealer"] = RawCell(text=name, source=f"L{n}")
            if len(froms) > 1:
                out.notes.append(f"forwarded chain: dealer taken from the innermost From: on line {n}")

    rows, table_lines = _table(body)
    blocks = [] if rows else _blocks(body)
    if rows:
        out.notes.append(f"inline table with {len(rows)} rows")
        outside = [(n, t) for n, t in body if n not in table_lines]
        quotes = [(f"table row {i + 1}", r, []) for i, r in enumerate(rows)]
    elif blocks:
        out.notes.append(f"{len(blocks)} quotes found in one email")
        in_block = {n for _, chunk in blocks for n, _ in chunk}
        outside = [(n, t) for n, t in body if n not in in_block]
        quotes = [(label, _scan(chunk, EMAIL_FIELDS), chunk) for label, chunk in blocks]
    else:
        outside = []
        quotes = [("email", _scan(body, EMAIL_FIELDS), body)]
    # Lines outside any quote apply to every quote ("Both options ship from ...").
    # An explicit "Dealer:" line overrides the From: header.
    shared.update(_scan(outside, SHARED_FIELDS))

    extractor, fill = gap_filler or active_extractor()
    for label, cells, scope in quotes:
        for field, cell in shared.items():
            cells.setdefault(field, cell)
        missing = [f for f in GAP_FIELDS if f not in cells]
        if missing:
            # Only this quote's own lines plus shared lines: never another quote's block.
            try:
                found = fill(scope + outside, missing)
            except Exception as exc:  # an LLM outage must never break intake
                out.notes.append(f"{extractor.value} extractor failed ({type(exc).__name__}); fields left missing")
                found = {}
            grounded, notes = ground(found, numbered, extractor)
            out.notes.extend(notes)
            for field, cell in grounded.items():
                cells[field] = cell
                out.notes.append(f"{label}: {field} located by {extractor.value} extractor on {cell.source}")
        out.quotes.append(cells)
        out.quote_labels.append(label)
    if not out.quotes or not any(out.quotes):
        out.error = "no quote found in email"
    return out
