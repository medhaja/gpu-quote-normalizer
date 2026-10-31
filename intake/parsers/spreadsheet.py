"""Deterministic CSV / XLSX parser with an alias table for column headers."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from intake.parsers.base import ParsedFile
from intake.parsers.patterns import find_in_line
from intake.schema import RawCell

ALIASES: dict[str, str] = {}
for _field, _names in {
    "gpu_sku": ["gpu", "card", "model", "gpu model", "sku", "gpu sku", "accelerator", "gpu type"],
    "gpus_per_node": ["gpus node", "gpus per node", "gpu count", "gpus", "config", "gpus per server", "gpu per node"],
    "node_count": ["nodes", "node count", "qty", "quantity", "servers", "units", "number of nodes"],
    "condition": ["condition", "cond", "state"],
    "location": ["location", "ships from", "ship from", "warehouse", "site", "loc"],
    "unit_price_usd": ["unit price", "price node", "price per node", "unit", "unit cost", "price"],
    "total_price_usd": ["total", "total price", "extended price", "ext price", "line total", "total cost"],
    "lead_time_days": ["lead time", "lead time days", "lead time weeks", "eta", "lead", "delivery"],
    "dealer": ["dealer", "vendor", "supplier"],
    "valid_until": ["valid until", "expires", "quote valid until", "expiry", "validity", "valid through"],
    "currency": ["currency", "ccy"],
}.items():
    for _n in _names:
        ALIASES[_n] = _field

PRICE_FIELDS = {"unit_price_usd", "total_price_usd"}
SKIP_ROW_PREFIXES = ("note", "total", "grand total", "subtotal")
FILE_LEVEL_FIELDS = ("dealer", "valid_until", "location", "currency")


def normalize_header(text: str) -> tuple[str, str | None]:
    """Return (alias key, currency hint) for a header cell."""
    t = text.lower().replace("€", " eur ").replace("$", " usd ")
    tokens = re.sub(r"[^a-z0-9]+", " ", t).split()
    cur = "USD" if "usd" in tokens else "EUR" if "eur" in tokens else None
    return " ".join(tok for tok in tokens if tok not in ("usd", "eur")), cur


def map_columns(header: list[str]) -> tuple[dict[int, str], list[str]]:
    """Map column index -> field. Returns the mapping and the unmapped header names."""
    mapping: dict[int, str] = {}
    unmapped: list[str] = []
    for i, h in enumerate(header):
        if not h.strip():
            continue
        key, _ = normalize_header(h)
        field = ALIASES.get(key)
        if field and field not in mapping.values():
            mapping[i] = field
        else:
            unmapped.append(h.strip())
    return mapping, unmapped


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_grid(filename: str, content: bytes) -> tuple[list[list[str]], list[list[str]]]:
    """Return (grid, merged_filled_grid). The second copies merged values into every merged cell."""
    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig")
        grid = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]
        return _pad(grid), _pad(grid)
    wb = load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.worksheets[0]
    grid = [[_cell_text(c) for c in row] for row in ws.iter_rows(values_only=True)]
    grid = _pad(grid)
    filled = [row[:] for row in grid]
    for rng in ws.merged_cells.ranges:
        top = grid[rng.min_row - 1][rng.min_col - 1]
        for r in range(rng.min_row - 1, rng.max_row):
            for c in range(rng.min_col - 1, rng.max_col):
                if r < len(filled) and c < len(filled[r]):
                    filled[r][c] = top
    return grid, filled


def _pad(grid: list[list[str]]) -> list[list[str]]:
    width = max((len(r) for r in grid), default=0)
    return [r + [""] * (width - len(r)) for r in grid]


def ref(row: int, col: int) -> str:
    return f"{get_column_letter(col + 1)}{row + 1}"


def parse_spreadsheet(filename: str, content: bytes) -> ParsedFile:
    grid, filled = read_grid(filename, content)
    out = ParsedFile(kind="spreadsheet", grid=grid)

    header_row = None
    for r, row in enumerate(grid[:20]):
        mapping, _ = map_columns(row)
        if len(mapping) >= 3:
            header_row = r
            break
    if header_row is None:
        out.error = "no header row recognised (need at least 3 known column names)"
        return out

    header = grid[header_row]
    mapping, out.unmapped_columns = map_columns(header)
    parent = filled[header_row - 1] if header_row > 0 else [""] * len(header)
    out.column_map = {f"{header[i]} ({ref(header_row, i)})": f for i, f in mapping.items()}

    hints: dict[int, str | None] = {}
    for i, field in mapping.items():
        _, cur = normalize_header(header[i])
        hints[i] = cur or normalize_header(parent[i])[1]

    # File-level context from the preamble (title rows above the header).
    context: dict[str, RawCell] = {}
    for r in range(header_row):
        for c, text in enumerate(grid[r]):
            if not text:
                continue
            for field in FILE_LEVEL_FIELDS:
                span = find_in_line(field, text)
                if span and field not in context:
                    context[field] = RawCell(text=span, source=ref(r, c))
                    out.notes.append(f"{field} taken from preamble cell {ref(r, c)}")

    for r in range(header_row + 1, len(grid)):
        row = grid[r]
        non_empty = [t for t in row if t]
        if not non_empty or non_empty[0].lower().startswith(SKIP_ROW_PREFIXES):
            continue
        cells: dict[str, RawCell] = {}
        for i, field in mapping.items():
            text = row[i]
            if field == "lead_time_days" and "week" in header[i].lower() and text.isdigit():
                text = f"{text} weeks"
            # Empty cells are kept so a "missing" field still points at its cell.
            cells[field] = RawCell(text=text, source=ref(r, i),
                                   currency_hint=hints.get(i) if field in PRICE_FIELDS else None)
        if sum(1 for c in cells.values() if c.text) < 3:
            continue
        for field, cell in context.items():
            if field not in cells or not cells[field].text:
                cells[field] = cell
        out.quotes.append(cells)
        out.quote_labels.append(f"row {r + 1}")
    return out
