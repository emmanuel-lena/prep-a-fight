import io
import json
import urllib.error

from paf import share


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_standalone_sheet():
    html = ('<body><a href="timeline-x.html">See the timelines</a> <a href="https://www.wowhead.com/spell=1">Feint</a>'
            '<a href="#boss">The boss</a></body>')
    out = share.standalone(html)
    assert "timeline-x.html" not in out and "See the timelines" in out
    assert "https://www.wowhead.com/spell=1" in out and 'href="#boss"' in out and "Prepared with" in out


def test_share_and_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setenv("PAF_FEEDBACK_URL", "https://relay.example.workers.dev")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "prep-boss-mythic-x.html").write_text("<body>prep-a-fight sheet</body>")
    calls = []

    def fake(url, data=None, method="GET", headers=None):
        calls.append((method, url, (headers or {}).get("X-Share-Token")))
        if method == "POST":
            assert b"Prepared with" in data
            return _Resp(json.dumps({"id": "abc", "url": "https://relay/s/abc", "token": "t0k", "days": 30}).encode())
        if method == "DELETE" and len(calls) > 2:
            raise urllib.error.HTTPError(url, 404, "gone", {}, io.BytesIO(b""))
        return _Resp(b"")

    monkeypatch.setattr(share, "_request", fake)
    info = share.publish("boss-mythic-x")
    assert info["url"] == "https://relay/s/abc" and share.current("boss-mythic-x")["token"] == "t0k"
    share.stop("boss-mythic-x")
    assert calls[-1] == ("DELETE", "https://relay.example.workers.dev/s/abc", "t0k")
    assert share.current("boss-mythic-x") is None
    share.publish("boss-mythic-x")
    share.stop("boss-mythic-x")  # already expired on the relay (404): forgotten anyway
    assert share.current("boss-mythic-x") is None
