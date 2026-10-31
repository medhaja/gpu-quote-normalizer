import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Tests always run offline with the deterministic mock extractor (FR10)."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
