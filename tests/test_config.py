from paf.config import load_dotenv


def test_load_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nPAF_TEST_A=1\nPAF_TEST_B = 'two'\nnot a pair\n", encoding="utf-8")
    monkeypatch.delenv("PAF_TEST_A", raising=False)
    monkeypatch.setenv("PAF_TEST_B", "already")
    loaded = load_dotenv(env)
    assert loaded == {"PAF_TEST_A": "1", "PAF_TEST_B": "two"}
    import os

    assert os.environ["PAF_TEST_A"] == "1"
    assert os.environ["PAF_TEST_B"] == "already"  # existing env wins


def test_load_dotenv_missing(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == {}
