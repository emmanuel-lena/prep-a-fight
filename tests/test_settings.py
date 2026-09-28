import pytest

from paf import settings


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))


def test_defaults():
    assert settings.get("difficulty") == "heroic"
    assert settings.get("corpus_size") == 200


def test_set_and_reload():
    assert settings.set_value("difficulty", "Mythic") == "mythic"
    assert settings.set_value("corpus_size", "50") == 50
    assert settings.get("difficulty") == "mythic"
    assert settings.get("corpus_size") == 50


def test_validation():
    with pytest.raises(ValueError):
        settings.set_value("difficulty", "hard")
    with pytest.raises(KeyError):
        settings.set_value("nope", "1")
