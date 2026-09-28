import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from paf import web


def fetch(url: str, data: bytes | None = None) -> str:
    """GET/POST with retries: some Windows machines reset a share of local connections (seen with a
    trivial stdlib server too), unrelated to the app."""
    for attempt in range(25):
        try:
            req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
            return urllib.request.urlopen(req, timeout=10).read().decode()
        except ConnectionResetError:
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError(f"{url}: connection reset every time")


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setattr(web, "_encounters", lambda: [])  # no network in tests
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path
    srv.shutdown()


def test_home_and_profile_upload(server):
    url, home = server
    page = fetch(url + "/")
    assert "Prepare a boss fight" in page and "No character loaded" in page
    data = b'shaman="T"\nspec=elemental\nhead=,id=1\n'
    fetch(url + "/profile", b"simc=" + urllib.parse.quote(data).encode())
    assert (home / "profiles" / "current.simc").read_text().startswith('shaman="T"')
    assert "Current character: <b>T</b>" in fetch(url + "/")


def test_reports_are_served_and_other_files_are_not(server):
    url, home = server
    (home / "reports").mkdir(parents=True)
    (home / "reports" / "prep-x-heroic.html").write_text('<a href="timeline-x.html">t</a>')
    assert 'href="/report/timeline-x.html"' in fetch(url + "/report/prep-x-heroic.html")
    with pytest.raises(urllib.error.HTTPError):
        fetch(url + "/report/..%2F..%2Fsecret.txt")


def test_write_assigns_keeps_other_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))

    class Enc:
        id, name = 7, "Boss"

    monkeypatch.setattr("paf.encounters.raid_encounters", lambda client: [Enc()])
    monkeypatch.setattr("paf.wcl.WCLClient", lambda: None)
    plan = tmp_path / "fights" / "boss-heroic.plan.txt"
    plan.parent.mkdir(parents=True)
    plan.write_text("2:00 move 5\nassign Old Mechanic\n")
    web.write_assigns(7, "heroic", ["Doomscale Shell"])
    assert plan.read_text() == "2:00 move 5\nassign Doomscale Shell\n"
