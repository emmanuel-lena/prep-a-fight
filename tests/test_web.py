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


def test_prepared_bosses_and_view_tabs(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "prep-the-altar-heroic.html").write_text("<title>The Altar prep</title>")
    (rep / "timeline-the-altar-heroic.html").write_text("<title>The Altar timelines</title>")
    (rep / "timeline-other-mythic.html").write_text("<title>Other timelines</title>")
    items = {x["key"]: x for x in web.prepared()}
    assert items["the-altar-heroic"]["name"] == "The Altar" and items["the-altar-heroic"]["difficulty"] == "heroic"
    assert set(items["the-altar-heroic"]["files"]) == {"prep", "timeline"}
    page = web.view_page("the-altar-heroic", "timeline").decode()
    assert 'src="/report/timeline-the-altar-heroic.html"' in page and "Prep sheet" in page
    # only a timeline: the prep tab falls back to it
    assert 'src="/report/timeline-other-mythic.html"' in web.view_page("other-mythic", "prep").decode()
    assert "Your prepared bosses" in web.prepared_block()


def test_plan_block_and_current_assigns(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))

    class Enc:
        id, name = 7, "Boss"

    assert "Available after the first prep" in web.plan_block(Enc(), "heroic")
    plan = tmp_path / "fights" / "boss-heroic.plan.txt"
    plan.parent.mkdir(parents=True)
    plan.write_text("2:00 move 5\nassign Wail of Terror\n")
    assert web.current_assigns(Enc(), "heroic") == ["Wail of Terror"]
    block = web.plan_block(Enc(), "heroic")
    assert 'action="/plan"' in block and "2:00 move 5" in block


def test_describe_plan():
    from paf.plan import describe_plan, parse_plan

    lines = describe_plan(parse_plan("2:45 move 6\n5:30 move 8 shift -5..+5\nlust 0:00\nassign X\n"))
    assert lines == ["You move 6s at 2:45", "You move 8s at 5:30 (can shift -5..+5s)", "Bloodlust at 0:00"]


def test_server_is_quiet_on_connection_resets(capsys):
    srv = web.Server(("127.0.0.1", 0), web.Handler)
    try:
        try:
            raise ConnectionResetError(10054, "reset by peer")
        except ConnectionResetError:
            srv.handle_error(None, ("127.0.0.1", 1))
        assert capsys.readouterr().err == ""
    finally:
        srv.server_close()


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
