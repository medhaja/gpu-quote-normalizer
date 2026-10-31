from intake.eval import evaluate
from intake.extractors import mock_extract
from intake.schema import Extractor


def test_no_wrong_value_is_marked_ok_on_labeled_set():
    rep = evaluate("mock", (Extractor.MOCK, mock_extract))
    assert rep.quotes == 60
    assert rep.count_mismatch == []
    assert rep.wrong_ok == []


def test_hallucinating_extractor_cannot_produce_ok_fields():
    """An extractor that invents spans for every gap must not create a single wrong ok."""
    def liar(lines, missing):
        return {f: {"span": "Atlantis, ZZ" if f == "location" else "999 days", "line": lines[0][0]} for f in missing}

    rep = evaluate("liar", (Extractor.LLM, liar))
    assert rep.wrong_ok == []
