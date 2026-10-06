import json

from paf import feedback, web


def test_feedback_scrubs_keys_paths_and_emails(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setenv("WCL_CLIENT_ID", "9a1b2c3d4e5f")
    log = ("token for 9a1b2c3d4e5f\nWCL_CLIENT_SECRET=abc\n"
           f"File \"{tmp_path}\\runs\\x\\input.simc\"\nFile \"C:\\Users\\Bob\\AppData\\x.py\"\nmail me@example.com\n")
    title, body = feedback.report("Crash on Ula'tek\nmore", "prep 3492", log)
    assert title == "Crash on Ula'tek"
    for leak in ("9a1b2c3d4e5f", "abc", str(tmp_path), "Bob", "me@example.com"):
        assert leak not in body
    assert "<data>" in body and "prep-a-fight" in body and "Command: paf prep 3492" in body
    url = feedback.issue_url(title, body + "x" * 50_000)
    assert url.startswith(feedback.ISSUES) and len(url) < 16_000


def test_feedback_page_previews_the_job_log(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.delenv("PAF_FEEDBACK_URL", raising=False)
    monkeypatch.setattr(feedback, "WEBHOOK_FILE", tmp_path / "none.txt")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "job-ab12.json").write_text(json.dumps({"args": ["prep", "3492"]}))
    (tmp_path / "web" / "job-ab12.log").write_text("Traceback: boom")
    page = web.feedback_page("ab12")
    assert "Traceback: boom" in page and "GitHub issue" in page and 'name="job" value="ab12"' in page
    done = web.send_feedback({"job": ["ab12"], "message": ["It broke"], "log": ["on"]})
    assert "github.com/emmanuel-lena/prep-a-fight/issues/new" in done


def test_feedback_relay_returns_the_issue(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"url": "https://github.com/x/y/issues/7"}'

    def fake_urlopen(req, timeout):
        sent["data"], sent["ua"] = json.loads(req.data), req.get_header("User-agent")
        return Resp()

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)
    assert feedback.send("https://relay.example.workers.dev", "T", "B") == "https://github.com/x/y/issues/7"
    assert sent["data"]["title"] == "T" and sent["ua"].startswith("prep-a-fight/")
