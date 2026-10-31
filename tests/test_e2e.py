"""End-to-end: generated files -> ingest -> review -> comparison, through the web app."""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from intake.compare import compare, load_rfqs
from intake.pipeline import ingest, project
from intake.store import make_engine, make_session_factory
from intake.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """Regenerate the dataset into a temp dir and check it matches the committed copy."""
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "generate_data.py")
    gen = importlib.util.module_from_spec(spec)
    sys.modules["gen"] = gen  # dataclasses need the module registered
    spec.loader.exec_module(gen)
    out = tmp_path_factory.mktemp("data")
    gen.write(out)
    return out


def test_generator_is_reproducible(generated):
    for f in sorted((ROOT / "data" / "samples").iterdir()):
        assert (generated / "samples" / f.name).read_bytes() == f.read_bytes(), f.name
    assert (generated / "labels.json").read_text() == (ROOT / "data" / "labels.json").read_text()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INTAKE_AS_OF", load_rfqs()["as_of"])
    url = f"sqlite:///{(tmp_path / 'e2e.db').as_posix()}"
    sessions = make_session_factory(make_engine(url))
    with sessions() as s:
        for p in sorted((ROOT / "data" / "samples").iterdir()):
            ingest(s, p.name, p.read_bytes())
    return TestClient(create_app(url)), sessions


def test_all_pages_render(client):
    c, _ = client
    for url in ["/", "/files/1", "/files/19", "/review", "/compare/RFQ-1001", "/compare/RFQ-1002",
                "/compare/RFQ-1003", "/quotes/Q1.1"]:
        r = c.get(url)
        assert r.status_code == 200, url
        assert "Not affiliated with Stoa" in r.text


def test_comparison_groups_only_like_for_like(client):
    _, sessions = client
    rfq = load_rfqs()["rfqs"][0]
    with sessions() as s:
        result = compare(project(s), rfq)
    assert len(result.comparable) >= 5
    for row in result.comparable:
        f = row.view.fields
        assert (f["gpu_sku"].value, f["gpus_per_node"].value, f["condition"].value) == ("H100-SXM5-80GB", 8, "new")
    assert all(reasons for _, reasons in result.excluded)


def test_resolving_in_ui_moves_quote_into_comparison(client):
    c, sessions = client
    rfq = load_rfqs()["rfqs"][0]
    with sessions() as s:
        target = next(v for v, _ in compare(project(s), rfq).excluded
                      if v.flagged == ["condition"] and v.fields["condition"].status.value == "missing")
    qid = target.quote_id

    # Missing reason is refused.
    r = c.post(f"/review/{qid}/condition", data={"value": "new", "reason": ""}, follow_redirects=False)
    assert r.status_code in (303, 422)
    r = c.post(f"/review/{qid}/condition", data={"value": "new", "reason": "dealer confirmed new by email"})
    assert r.status_code == 200

    page = c.get("/compare/RFQ-1001").text
    comparable_section = page.split("Excluded")[0]
    assert f">{qid}<" in comparable_section
    audit = c.get(f"/quotes/{qid}").text
    assert "dealer confirmed new by email" in audit and "field reviewed" in audit


def test_upload_and_duplicate_upload(client):
    c, _ = client
    content = (ROOT / "data" / "samples" / "21_bluefin_reply.eml").read_bytes()
    r = c.post("/upload", files={"file": ("again.eml", content, "message/rfc822")})
    assert r.status_code == 200 and "duplicate" in r.text.lower()
    new = content.replace(b"Dana Whitfield", b"Dana W.")
    r = c.post("/upload", files={"file": ("new.eml", new, "message/rfc822")}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/files/")
