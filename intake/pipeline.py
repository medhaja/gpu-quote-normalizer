"""Ingest, project and review.

file -> raw_files (sha256) -> parser -> normalizer -> validators -> events
The current state of a quote is the replay of its events (``project``).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from intake.extractors import active_extractor
from intake.normalize import normalize_quote, normalize_reviewer_value
from intake.parsers import parse_file
from intake.schema import QUOTE_FIELDS, FieldResult, QuoteStatus, Status
from intake.store import Event, RawFile, append, now
from intake.validators import quote_status, validate


def get_as_of() -> date:
    """Date used for the 'valid_until is not in the past' check."""
    v = os.environ.get("INTAKE_AS_OF")
    return date.fromisoformat(v) if v else date.today()


@dataclass
class IngestResult:
    status: str  # "ingested" | "duplicate" | "rejected"
    file_id: int
    quote_ids: list[str] = field(default_factory=list)
    message: str = ""


def ingest(session: Session, filename: str, content: bytes, as_of: date | None = None) -> IngestResult:
    as_of = as_of or get_as_of()
    sha = hashlib.sha256(content).hexdigest()
    existing = session.scalar(select(RawFile).where(RawFile.sha256 == sha))
    if existing:
        append(session, "file_duplicate", {"filename": filename, "sha256": sha,
                                           "duplicate_of": existing.filename}, file_id=existing.id)
        session.commit()
        return IngestResult("duplicate", existing.id, message=f"same SHA-256 as {existing.filename}; no new quotes")

    # Raw bytes and hash are stored before any parsing happens.
    raw = RawFile(filename=filename, sha256=sha, content=content, size=len(content), received_at=now())
    session.add(raw)
    session.flush()
    append(session, "file_received", {"filename": filename, "sha256": sha, "size": len(content)}, file_id=raw.id)

    parsed = parse_file(filename, content)
    extractor, _ = active_extractor()
    append(session, "file_parsed", {
        "kind": parsed.kind, "quotes": len(parsed.quotes), "unmapped_columns": parsed.unmapped_columns,
        "column_map": parsed.column_map, "notes": parsed.notes, "error": parsed.error,
        "gap_extractor": extractor.value if parsed.kind == "email" else None,
    }, file_id=raw.id)
    if parsed.error and not parsed.quotes:
        session.commit()
        return IngestResult("rejected", raw.id, message=parsed.error)

    ids = []
    for i, (cells, label) in enumerate(zip(parsed.quotes, parsed.quote_labels), start=1):
        qid = f"Q{raw.id}.{i}"
        append(session, "quote_extracted", {"label": label, "raw": {k: c.model_dump(mode="json") for k, c in cells.items()}},
               file_id=raw.id, quote_id=qid)
        normalized = normalize_quote(cells)
        append(session, "quote_normalized", {"fields": _dump(normalized)}, file_id=raw.id, quote_id=qid)
        _record_validation(session, raw.id, qid, normalized, as_of, cause="ingest")
        ids.append(qid)
    session.commit()
    return IngestResult("ingested", raw.id, ids, message=f"{len(ids)} quote(s) extracted")


def _dump(fields: dict[str, FieldResult]) -> dict:
    return {k: v.model_dump(mode="json") for k, v in fields.items()}


def _record_validation(session, file_id, qid, fields, as_of, cause, rejected_reason=None):
    validated = validate(fields, as_of)
    status, reason = quote_status(validated, rejected_reason)
    append(session, "quote_validated", {"fields": _dump(validated), "status": status.value, "status_reason": reason,
                                        "as_of": as_of.isoformat(), "cause": cause}, file_id=file_id, quote_id=qid)
    return validated


# ------------------------------------------------------------------ projection

@dataclass
class QuoteView:
    quote_id: str
    file_id: int
    label: str = ""
    filename: str = ""
    fields: dict[str, FieldResult] = field(default_factory=dict)
    rejected_reason: str | None = None
    review_count: int = 0

    @property
    def status_pair(self) -> tuple[QuoteStatus, str]:
        return quote_status(self.fields, self.rejected_reason)

    @property
    def status(self) -> QuoteStatus:
        return self.status_pair[0]

    @property
    def status_reason(self) -> str:
        return self.status_pair[1]

    @property
    def flagged(self) -> list[str]:
        return [n for n in QUOTE_FIELDS if self.fields[n].status != Status.OK]

    def value(self, name: str):
        return self.fields[name].value


def project(session: Session) -> dict[str, QuoteView]:
    """Replay the event log into the current state of every quote."""
    names = dict(session.execute(select(RawFile.id, RawFile.filename)).all())
    views: dict[str, QuoteView] = {}
    for ev in session.scalars(select(Event).where(Event.quote_id.is_not(None)).order_by(Event.id)):
        v = views.setdefault(ev.quote_id, QuoteView(ev.quote_id, ev.file_id, filename=names.get(ev.file_id, "")))
        d = ev.data
        if ev.type == "quote_extracted":
            v.label = d["label"]
        elif ev.type == "quote_validated":
            v.fields = {k: FieldResult.model_validate(f) for k, f in d["fields"].items()}
        elif ev.type == "field_reviewed":
            v.review_count += 1
        elif ev.type == "quote_rejected":
            v.rejected_reason = d["reason"]
    return views


def quote_events(session: Session, quote_id: str) -> list[Event]:
    view_file = session.scalar(select(Event.file_id).where(Event.quote_id == quote_id).limit(1))
    stmt = select(Event).where(
        (Event.quote_id == quote_id) | ((Event.file_id == view_file) & Event.quote_id.is_(None))
    ).order_by(Event.id)
    return list(session.scalars(stmt))


# ------------------------------------------------------------------ review

class ReviewError(ValueError):
    pass


def review_field(session: Session, quote_id: str, field_name: str, value: str, reason: str,
                 as_of: date | None = None, reviewer: str = "ops") -> QuoteView:
    """Set a field by hand. A reason is required; the original stays in the log."""
    as_of = as_of or get_as_of()
    if not (reason or "").strip():
        raise ReviewError("a reason is required for every manual edit")
    if field_name not in QUOTE_FIELDS:
        raise ReviewError(f"unknown field {field_name}")
    view = project(session).get(quote_id)
    if view is None:
        raise ReviewError(f"unknown quote {quote_id}")
    new = normalize_reviewer_value(field_name, value)
    if new.status != Status.OK:
        raise ReviewError(f"value not accepted: {new.reason}")
    new = new.model_copy(update={"reason": f"set by {reviewer}: {reason.strip()}"})
    append(session, "field_reviewed", {
        "field": field_name, "before": view.fields[field_name].model_dump(mode="json"),
        "after": new.model_dump(mode="json"), "reason": reason.strip(), "reviewer": reviewer,
    }, file_id=view.file_id, quote_id=quote_id)
    fields = dict(view.fields, **{field_name: new})
    _record_validation(session, view.file_id, quote_id, fields, as_of, cause="review", rejected_reason=view.rejected_reason)
    session.commit()
    return project(session)[quote_id]


def reject_quote(session: Session, quote_id: str, reason: str, reviewer: str = "ops") -> None:
    if not (reason or "").strip():
        raise ReviewError("a reason is required to reject a quote")
    view = project(session).get(quote_id)
    if view is None:
        raise ReviewError(f"unknown quote {quote_id}")
    append(session, "quote_rejected", {"reason": reason.strip(), "reviewer": reviewer},
           file_id=view.file_id, quote_id=quote_id)
    session.commit()


# ------------------------------------------------------------------ inbox

@dataclass
class FileRow:
    file_id: int
    filename: str
    kind: str
    received_at: str
    sha256: str
    counts: dict[str, int]
    duplicate_of: str | None = None
    error: str | None = None


def inbox(session: Session) -> list[FileRow]:
    views = project(session)
    rows: list[FileRow] = []
    files = {f.id: f for f in session.scalars(select(RawFile).order_by(RawFile.id))}
    parsed = {e.file_id: e.data for e in session.scalars(select(Event).where(Event.type == "file_parsed"))}
    for f in files.values():
        counts = {s.value: 0 for s in QuoteStatus}
        for v in views.values():
            if v.file_id == f.id:
                counts[v.status.value] += 1
        p = parsed.get(f.id, {})
        rows.append(FileRow(f.id, f.filename, p.get("kind", "?"), f.received_at.strftime("%Y-%m-%d %H:%M"),
                            f.sha256, counts, error=p.get("error")))
    for e in session.scalars(select(Event).where(Event.type == "file_duplicate").order_by(Event.id)):
        d = e.data
        rows.append(FileRow(e.file_id, d["filename"], "duplicate", e.created_at.strftime("%Y-%m-%d %H:%M"),
                            d["sha256"], {s.value: 0 for s in QuoteStatus}, duplicate_of=d["duplicate_of"]))
    return sorted(rows, key=lambda r: r.filename)
