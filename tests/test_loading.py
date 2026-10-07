import time

from paf import loading, web


def test_every_page_has_the_loader_and_the_running_preps():
    page = web.page("X", "<p>hi</p>").decode()
    assert 'id="paf-load"' in page and "Loading&hellip;" in page and "nothing has crashed" in page


def test_banner_of_a_running_prep(tmp_path, monkeypatch):
    log = tmp_path / "job.log"
    log.write_text("== Collecting the corpus from Warcraft Logs  [+0s]\n", encoding="utf-8")
    job = {"args": ["prep", "3470", "--difficulty", "mythic"], "log": log, "started": time.time() - 60,
           "status": "running"}
    monkeypatch.setattr(web, "_encounters", lambda: [type("E", (), {"id": 3470, "name": "Nek'zali"})()])
    html = loading.banner("abcd1234", job)
    assert "Preparing <b>Nek&#x27;zali</b>" in html and "data-job='abcd1234'" in html and "%" in html
    monkeypatch.setattr(loading, "running_preps", lambda: [("abcd1234", job)])
    assert "class='job-banner'" in web.page("Home", "").decode()
    assert "class='job-banner'" not in web.page("Its page", "", job="abcd1234").decode()  # not on its own page


def test_percent_stays_between_1_and_99():
    assert loading.percent("", 0)[0] >= 1
    assert loading.percent("== Done  [+600s]\n", 600)[0] <= 99


def test_the_startup_page_has_a_spinner():
    assert "class=\"spin\"" in loading.startup_page() and "Starting prep-a-fight" in loading.STARTUP
