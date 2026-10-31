from types import SimpleNamespace

from intake.extractors import ground, llm_extract, mock_extract, parse_llm_json
from intake.normalize import normalize_quote
from intake.parsers import parse_file
from intake.parsers.email import parse_email
from intake.schema import Extractor, Status

PROSE = b"""From: Example Racks <sales@example-racks.example>
To: desk@buyer.example
Subject: quote

Hi,

We can offer 16 x 8-GPU NVIDIA H100 SXM5 80G nodes, brand new, at $221,000 per node.
Total for the order is $3,536,000.
Lead time is 3 weeks. Ships from Dallas, TX.
Valid until December 12, 2026.
"""


def fields(content: bytes, name="q.eml", **kw):
    p = parse_email(name, content, **kw)
    return p, [normalize_quote(q) for q in p.quotes]


def test_prose_email_all_fields_by_rule():
    p, (f,) = fields(PROSE)
    values = {k: v.value for k, v in f.items()}
    assert values == {
        "gpu_sku": "H100-SXM5-80GB", "gpus_per_node": 8, "node_count": 16, "condition": "new",
        "location": "Dallas, TX", "unit_price_usd": 221000.0, "total_price_usd": 3536000.0,
        "lead_time_days": 21, "dealer": "Example Racks", "valid_until": "2026-12-12",
    }
    assert all(v.extractor == Extractor.RULE for v in f.values())
    assert f["unit_price_usd"].source == "L7" and f["dealer"].source == "L1"


TWO = b"""From: Example Racks <sales@example-racks.example>
Subject: two options

Option A: 8 x 8-GPU H200 nodes, new, $300,000 per node, total $2,400,000, lead time 21 days.
Option B: 32 x 8-GPU A100 80GB SXM4 nodes, refurbished, $80,000 per node, total $2,560,000, lead time 42 days.

Both options ship from Phoenix, AZ and are valid through Jan 15, 2027.
"""


def test_two_quotes_in_one_email_share_trailing_terms():
    p, (a, b) = fields(TWO)
    assert p.quote_labels == ["Option A", "Option B"]
    assert (a["gpu_sku"].value, a["node_count"].value, a["unit_price_usd"].value) == ("H200-SXM-141GB", 8, 300000.0)
    assert (b["gpu_sku"].value, b["node_count"].value, b["condition"].value) == ("A100-SXM4-80GB", 32, "refurbished")
    for q in (a, b):
        assert q["location"].value == "Phoenix, AZ" and q["valid_until"].value == "2027-01-15"


FWD = b"""From: Desk <desk@buyer.example>
Subject: Fwd: quote

FYI below.

---------- Forwarded message ---------
From: Example Racks <sales@example-racks.example>
Subject: RE: RFQ

> 16 x 8-GPU h100-sxm nodes, new units.
> Unit price: $230,000 per node
"""


def test_forwarded_chain_uses_innermost_sender_as_dealer():
    p, (f,) = fields(FWD)
    assert f["dealer"].value == "Example Racks" and f["dealer"].source == "L7"
    assert f["gpu_sku"].value == "H100-SXM5-80GB" and f["condition"].value == "new"


WORDS = b"""From: Example Racks <sales@example-racks.example>
Subject: H200

We have 8 x 8-GPU H200 nodes, new, at $300,000 per node (total $2,400,000).
We can deliver in about three weeks.
Everything is staged at our Reno, NV facility.
Valid until 2026-12-01.
"""


def test_mock_fills_gaps_rules_missed_and_records_extractor():
    p, (f,) = fields(WORDS)
    assert f["lead_time_days"].value == 21 and f["lead_time_days"].extractor == Extractor.MOCK
    assert f["location"].value == "Reno, NV" and f["location"].extractor == Extractor.MOCK
    assert f["lead_time_days"].status == Status.OK  # status decided by the shared parser
    assert any("mock extractor" in n for n in p.notes)


def test_gap_filler_cannot_override_flagged_fields():
    text = PROSE.replace(b"NVIDIA H100 SXM5 80G", b"H100").replace(b"3 weeks", b"3-4 weeks")
    _, (f,) = fields(text)
    assert f["gpu_sku"].status == Status.AMBIGUOUS
    assert f["lead_time_days"].status == Status.AMBIGUOUS and f["lead_time_days"].extractor == Extractor.RULE


def test_hallucinated_llm_span_is_dropped():
    lines = [(1, "Lead time is about three weeks.")]
    cells, notes = ground({"lead_time_days": {"span": "10 days", "line": 1}}, lines, Extractor.LLM)
    assert cells == {} and notes


def test_llm_extractor_with_stubbed_completion():
    def fake_completion(**kwargs):
        assert "lead_time_days" in kwargs["messages"][0]["content"]
        content = '{"lead_time_days": {"span": "about three weeks", "line": 5}, "bogus": {"span": "x", "line": 1}}'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    stub = (Extractor.LLM, lambda lines, missing: llm_extract(lines, missing, completion=fake_completion))
    _, (f,) = fields(WORDS, gap_filler=stub)
    assert f["lead_time_days"].value == 21 and f["lead_time_days"].extractor == Extractor.LLM
    assert f["location"].status == Status.MISSING  # the LLM did not return it, nothing invented


def test_llm_failure_falls_back_to_missing_not_crash():
    def boom(lines, missing):
        raise TimeoutError

    p, (f,) = fields(WORDS, gap_filler=(Extractor.LLM, boom))
    assert f["lead_time_days"].status == Status.MISSING
    assert any("failed" in n for n in p.notes)


def test_parse_llm_json_is_defensive():
    assert parse_llm_json("not json", ["location"]) == {}
    assert parse_llm_json('{"location": {"span": 5, "line": 1}}', ["location"]) == {}


def test_mock_extract_shape():
    assert mock_extract([(3, "total comes to $1,000,000 all-in")], ["total_price_usd"]) == {
        "total_price_usd": {"span": "$1,000,000", "line": 3}}


def test_inline_table_email():
    content = b"""From: Example Racks <a@example-racks.example>

| GPU | GPUs/node | Nodes | Condition | Unit price (USD) | Total (USD) | Lead time | Valid until |
|-----|-----------|-------|-----------|------------------|-------------|-----------|-------------|
| B200 | 8 | 4 | new | 450,000 | 1,800,000 | 14 days | 2026-12-20 |
| L40S | 8 | 8 | new | 75,000 | 600,000 | 21 days | 2026-12-20 |

All units ship from San Jose, CA.
"""
    p = parse_file("t.txt", content)
    qs = [normalize_quote(q) for q in p.quotes]
    assert len(qs) == 2
    assert all(f.status == Status.OK for q in qs for f in q.values())
    assert qs[1]["unit_price_usd"].value == 75000.0
