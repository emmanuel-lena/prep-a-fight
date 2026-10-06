import pytest


@pytest.fixture(autouse=True)
def english_pages(monkeypatch):
    """Pages in English whatever the language of the machine running the tests (test_i18n sets its own)."""
    monkeypatch.setenv("PAF_LANG", "en")
