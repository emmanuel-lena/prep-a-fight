import json
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


def test_first_run_shows_the_steps_then_home(server):
    from paf import settings

    url, _home = server
    page = fetch(url + "/")  # first run: the onboarding steps
    assert 'data-step="welcome"' in page and 'data-step="character"' in page and "Skip all" in page
    assert '"ok": false' in fetch(url + "/onboard/simc", b"simc=hello")
    fetch(url + "/onboard/skip")
    assert settings.get("onboarded") == "on" and "Prepare a boss fight" in fetch(url + "/")


def test_onboarding_saves_a_pasted_export(server):
    import json as _json

    url, home = server
    data = b'shaman="T"\nspec=elemental\nhead=,id=1\n'
    out = _json.loads(fetch(url + "/onboard/simc", b"simc=" + urllib.parse.quote(data).encode()))
    assert out["ok"] and out["name"] == "T" and (home / "profiles" / "current.simc").is_file()
    raid = _json.loads(fetch(url + "/onboard/raid", b"guild=G&server=Kazzak&region=eu"))
    assert raid["ok"]


def test_home_and_profile_upload(server):
    from paf import settings

    url, home = server
    settings.set_value("onboarded", "on")
    page = fetch(url + "/")
    assert "Prepare a boss fight" in page and 'name="simc"' in page and "items in bags" not in page
    data = b'shaman="T"\nspec=elemental\nhead=,id=1\n'
    fetch(url + "/profile", b"simc=" + urllib.parse.quote(data).encode())
    assert (home / "profiles" / "current.simc").read_text().startswith('shaman="T"')
    assert "<b>T</b>" in fetch(url + "/")


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


def test_credentials_saved_in_the_data_dir_and_loaded(tmp_path, monkeypatch):
    from paf.config import load_dotenv, save_credentials

    monkeypatch.setenv("PAF_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WCL_CLIENT_ID", raising=False)
    monkeypatch.delenv("WCL_CLIENT_SECRET", raising=False)
    assert not web.has_credentials()
    assert "Connect to Warcraft Logs" in web.credentials_block()
    save_credentials(" abc ", "s3cret")
    assert (tmp_path / "home" / ".env").read_text() == "WCL_CLIENT_ID=abc\nWCL_CLIENT_SECRET=s3cret\n"
    monkeypatch.delenv("WCL_CLIENT_ID")
    monkeypatch.delenv("WCL_CLIENT_SECRET")
    assert load_dotenv()["WCL_CLIENT_ID"] == "abc" and web.has_credentials()


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


def test_prep_progress_and_job_from_disk(tmp_path, monkeypatch):
    import json
    import time

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    log = "\n== Analyzing the corpus\n  x\n== Calibrating the fight on the logs\n"
    rows, left = web.prep_progress(log)
    states = [(label, state) for label, _, state in rows]
    assert states[0] == ("Rebuild the typical fight", "done") and states[1] == ("Calibrate it on the logs", "now")
    assert ("Find your best cooldown plan", "next") in states and left > 20
    assert not any(label.startswith("Download") for label, _ in states)  # corpus already there: skipped
    done_rows, done_left = web.prep_progress(log + "== Done\n")
    assert all(state == "done" for *_, state in done_rows) and done_left == 0
    # a job started by an earlier run of the app: its outcome is read from the log
    d = tmp_path / "web"
    d.mkdir()
    (d / "job-abcd1234.json").write_text(json.dumps({"args": [], "result": "", "status": "running",
                                                     "started": time.time() - 60}))
    (d / "job-abcd1234.log").write_text(log + "Prep sheet: x\n")
    assert web.JOBS.get("abcd1234")["status"] == "done"
    assert web.JOBS.get("../etc") is None
    page = web.job_page("abcd1234").decode()
    assert "The prep finished" in page and "failed" not in page



def test_report_keys_carry_the_spec():
    assert web.split_key("nek-zali-the-soulcoiler-mythic-assassination-rogue") == (
        "nek-zali-the-soulcoiler", "mythic", "Assassination Rogue")
    assert web.split_key("ula-tek-heroic") == ("ula-tek", "heroic", "")  # reports from before the spec was in the name


def test_every_link_of_the_top_bar_and_feedback_routes(server, monkeypatch):
    url, _ = server
    monkeypatch.delenv("PAF_FEEDBACK_URL", raising=False)
    from paf import feedback

    monkeypatch.setattr(feedback, "WEBHOOK_FILE", feedback.WEBHOOK_FILE.with_name("absent.txt"))
    for path in ("/", "/tools", "/settings", "/feedback"):
        assert "Not found" not in fetch(url + path), path
    done = fetch(url + "/feedback", urllib.parse.urlencode({"message": "It broke", "log": "on"}).encode())
    assert "issues/new" in done
    assert "Nothing to update" in fetch(url + "/update", b"")


def test_check_for_updates_button(server, monkeypatch):
    url, _ = server
    from paf import update

    monkeypatch.setattr(update, "_get", lambda u: b"[]")
    assert "Check for updates" in fetch(url + "/settings")
    assert "You have the latest version" in fetch(url + "/update/check", b"")
    monkeypatch.setattr(update, "_get", lambda u: json.dumps([{
        "tag_name": "v99.0.0", "html_url": "https://github.com/x/y/releases/tag/v99.0.0", "body": "",
        "assets": [{"name": "s.exe", "size": 1, "browser_download_url": "https://github.com/x/y/s.exe"}]}]).encode())
    page = fetch(url + "/update/check", b"")
    assert "Version 99.0.0 is out" in page
    update.STATE["release"] = None


def test_prep_progress_with_a_pack():
    log = "== Using the prep pack (199 top kills, 2026-10-06)\n== Calibrating the fight on the logs\n"
    rows, left = web.prep_progress(log)
    labels = [label for label, *_ in rows]
    assert not any("corpus" in x.lower() or "real DPS" in x for x in labels) and rows[0][2] == "done"


def test_job_page_updates_itself(server):
    import json
    import time

    url, home = server
    (home / "web").mkdir(exist_ok=True)
    (home / "web" / "job-abcd0f02.json").write_text(json.dumps(
        {"args": ["prep", "3470", "--difficulty", "mythic"], "result": "", "status": "running",
         "started": time.time() - 30}))
    (home / "web" / "job-abcd0f02.log").write_text("== Simming your character on the fight  [+5s]\n")
    from paf import web as w

    w.JOBS.jobs.pop("abcd0f02", None)
    job = w.JOBS.get("abcd0f02")
    job["status"] = "running"
    w.JOBS.jobs["abcd0f02"] = job
    page = fetch(url + "/job/abcd0f02")
    assert "id='live'" in page and "part=live" in page
    part = fetch(url + "/job/abcd0f02?part=live")
    assert "Sim your character" in part and "topbar" not in part
    job["status"] = "done"
    assert "data-reload" in fetch(url + "/job/abcd0f02?part=live")
    w.JOBS.jobs.pop("abcd0f02", None)


def test_language_switch_in_the_top_bar(server, monkeypatch):
    url, _ = server
    page = fetch(url + "/settings")
    assert "action='/language'" in page and "value='fr'" in page
    fetch(url + "/language", urllib.parse.urlencode({"lang": "fr"}).encode())
    from paf import settings

    assert settings.get("language") == "fr"
    monkeypatch.delenv("PAF_LANG")  # now the setting decides
    assert "Réglages" in fetch(url + "/settings")


def test_simple_home_once_set_up(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setenv("WCL_CLIENT_ID", "id")
    monkeypatch.setenv("WCL_CLIENT_SECRET", "secret")
    monkeypatch.setattr(web, "_encounters", lambda: [SimpleNamespace(id=3470, name="Nek'zali the Soulcoiler")])
    (tmp_path / "profiles").mkdir(parents=True)
    (tmp_path / "profiles" / "current.simc").write_text('shaman="Ixuu"\nspec=elemental\nhead=,id=1\n')
    rep = tmp_path / "reports"
    rep.mkdir()
    (rep / "prep-the-altar-heroic-elemental-shaman.html").write_text("<title>The Altar prep</title>")
    page = web.home().decode()
    assert "Prepare a boss</h1>" in page and "Let's go" in page and 'name="difficulty" value="mythic"' in page
    assert "Your bosses" in page and "The Altar" in page and "just now" in page
    assert "Change your character" in page and 'name="simc"' in page  # the rest, folded
    assert "%" not in page.split("Your bosses", 1)[1].split("<details", 1)[0]  # no numbers on the cards


def test_ago():
    now = 1_000_000.0
    assert web.ago(now - 30, now) == "just now" and web.ago(now - 600, now) == "10 min ago"
    assert web.ago(now - 7200, now) == "2 h ago" and web.ago(now - 100_000, now) == "yesterday"


def test_finding_a_character_needs_the_key(tmp_path, monkeypatch):
    from paf import onboarding

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.delenv("WCL_CLIENT_ID", raising=False)
    monkeypatch.delenv("WCL_CLIENT_SECRET", raising=False)
    out = onboarding.find_character("Someone", "Kazzak", "eu")
    assert not out["ok"] and "Warcraft Logs key first" in out["error"]
