from __future__ import annotations

from dataclasses import dataclass, field

from intake.schema import RawCell


@dataclass
class ParsedFile:
    kind: str  # "spreadsheet" | "email"
    quotes: list[dict[str, RawCell]] = field(default_factory=list)
    quote_labels: list[str] = field(default_factory=list)  # "row 7", "Option A", ...
    unmapped_columns: list[str] = field(default_factory=list)
    column_map: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    grid: list[list[str]] | None = None
    lines: list[str] | None = None
    error: str | None = None
