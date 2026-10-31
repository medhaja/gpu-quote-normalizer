from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError

from intake.pipeline import ReviewError, ingest, inbox, project, quote_events, reject_quote, review_field
from intake.schema import QuoteStatus, Status
from intake.store import AppendOnlyError, Event, RawFile, make_engine, make_session_factory

AS_OF = date(2026, 11, 2)
CSV = b"""Vendor,GPU,GPUs/Node,Nodes,Condition,Location,Unit Price (USD),Total (USD),Lead Time (days),Valid Until
Example Racks,H100,8,16,New,"Dallas, TX",220000,3520000,21,2026-12-15
Example Racks,H100 SXM5,8,16,,"Dallas, TX",215000,3440000,21,2026-12-15
"""


@pytest.fixture
def session():
    factory = make_session_factory(make_engine("sqlite://"))
    with factory() as s:
        yield s


def test_ingest_stores_raw_bytes_and_hash_before_parsing(session):
    r = ingest(session, "q.csv", CSV, AS_OF)
    raw = session.get(RawFile, r.file_id)
    assert raw.content == CSV and len(raw.sha256) == 64
    types = [e.type for e in session.scalars(select(Event).order_by(Event.id))]
    assert types[:2] == ["file_received", "file_parsed"]


def test_reingest_same_file_creates_no_duplicate_quotes(session):
    first = ingest(session, "q.csv", CSV, AS_OF)
    again = ingest(session, "q_resend.csv", CSV, AS_OF)
    assert first.status == "ingested" and again.status == "duplicate"
    assert len(project(session)) == 2
    assert session.scalar(select(func.count()).select_from(RawFile)) == 1
    rows = inbox(session)
    assert [r.duplicate_of for r in rows] == [None, "q.csv"]


def test_events_are_append_only_at_database_level(session):
    ingest(session, "q.csv", CSV, AS_OF)
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("UPDATE events SET payload = '{}'"))
    session.rollback()
    with pytest.raises(DatabaseError, match="append-only"):
        session.execute(text("DELETE FROM events"))
    session.rollback()


def test_events_are_append_only_in_orm(session):
    ingest(session, "q.csv", CSV, AS_OF)
    ev = session.scalars(select(Event)).first()
    ev.payload = "{}"
    with pytest.raises(AppendOnlyError):
        session.flush()
    session.rollback()


def test_flagged_quote_goes_to_review_and_edit_is_a_new_event(session):
    ingest(session, "q.csv", CSV, AS_OF)
    q = project(session)["Q1.1"]
    assert q.status == QuoteStatus.NEEDS_REVIEW and q.flagged == ["gpu_sku"]
    n_before = session.scalar(select(func.count()).select_from(Event))

    with pytest.raises(ReviewError, match="reason"):
        review_field(session, "Q1.1", "gpu_sku", "H100 SXM5", "  ", AS_OF)
    with pytest.raises(ReviewError, match="not accepted"):
        review_field(session, "Q1.1", "gpu_sku", "H100", "dealer said so", AS_OF)  # still ambiguous

    q = review_field(session, "Q1.1", "gpu_sku", "h100 sxm5", "dealer confirmed SXM5 by phone", AS_OF)
    assert q.status == QuoteStatus.PARSED
    assert q.fields["gpu_sku"].value == "H100-SXM5-80GB"
    assert q.fields["gpu_sku"].extractor.value == "reviewer"
    assert session.scalar(select(func.count()).select_from(Event)) == n_before + 2  # reviewed + revalidated

    reviewed = [e for e in quote_events(session, "Q1.1") if e.type == "field_reviewed"][0].data
    assert reviewed["before"]["status"] == "ambiguous" and reviewed["before"]["raw"] == "H100"
    assert reviewed["reason"] == "dealer confirmed SXM5 by phone"
    # The original extraction is still in the log, untouched.
    extracted = [e for e in quote_events(session, "Q1.1") if e.type == "quote_extracted"][0].data
    assert extracted["raw"]["gpu_sku"]["text"] == "H100"


def test_missing_condition_can_be_set_by_reviewer(session):
    ingest(session, "q.csv", CSV, AS_OF)
    q = project(session)["Q1.2"]
    assert q.fields["condition"].status == Status.MISSING and q.fields["condition"].value == "unknown"
    q = review_field(session, "Q1.2", "condition", "refurbished", "dealer email of Oct 30", AS_OF)
    assert q.status == QuoteStatus.PARSED


def test_review_reruns_cross_field_validation(session):
    bad_total = CSV.replace(b"3440000", b"3500000")
    ingest(session, "q.csv", bad_total, AS_OF)
    q = project(session)["Q1.2"]
    assert q.fields["total_price_usd"].code == "total_mismatch"
    q = review_field(session, "Q1.2", "unit_price_usd", "$218,750", "unit price typo, confirmed", AS_OF)
    assert q.fields["total_price_usd"].status == Status.OK


def test_reject_quote_requires_reason(session):
    ingest(session, "q.csv", CSV, AS_OF)
    with pytest.raises(ReviewError):
        reject_quote(session, "Q1.1", "")
    reject_quote(session, "Q1.1", "dealer withdrew quote")
    assert project(session)["Q1.1"].status == QuoteStatus.REJECTED


def test_unparseable_file_is_rejected_but_kept(session):
    r = ingest(session, "notes.csv", b"just,some\nrandom,text\n", AS_OF)
    assert r.status == "rejected"
    assert inbox(session)[0].error
