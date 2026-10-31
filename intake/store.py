"""Storage: raw files (by SHA-256) and an append-only event log.

Quotes are never stored as mutable rows. ``intake.pipeline.project`` derives the
current state of every quote by replaying events. Updates and deletes on the
events table are blocked twice: by the ORM and by a database trigger.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, LargeBinary, String, Text, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DEFAULT_URL = "sqlite:///intake_demo.db"


class Base(DeclarativeBase):
    pass


class RawFile(Base):
    __tablename__ = "raw_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int]
    received_at: Mapped[datetime]


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("raw_files.id"), index=True)
    quote_id: Mapped[str | None] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]

    @property
    def data(self) -> dict:
        return json.loads(self.payload)


class AppendOnlyError(RuntimeError):
    pass


@event.listens_for(Session, "before_flush")
def _block_event_mutation(session, flush_context, instances):
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, (Event, RawFile)) and (obj in session.deleted or session.is_modified(obj)):
            raise AppendOnlyError(f"{type(obj).__name__} rows are append-only")


SQLITE_TRIGGERS = [
    f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
    f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;"
    for t in ("events", "raw_files") for op in ("UPDATE", "DELETE")
]
POSTGRES_TRIGGERS = [
    """CREATE OR REPLACE FUNCTION intake_append_only() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql;""",
    *[f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};" for t in ("events", "raw_files")],
    *[f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
      f"FOR EACH ROW EXECUTE FUNCTION intake_append_only();" for t in ("events", "raw_files")],
]


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL") or DEFAULT_URL
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    statements = SQLITE_TRIGGERS if engine.dialect.name == "sqlite" else (
        POSTGRES_TRIGGERS if engine.dialect.name == "postgresql" else [])
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def append(session: Session, type_: str, payload: dict, *, file_id: int | None = None,
           quote_id: str | None = None) -> Event:
    ev = Event(type=type_, payload=json.dumps(payload, default=str), file_id=file_id,
               quote_id=quote_id, created_at=now())
    session.add(ev)
    session.flush()
    return ev
