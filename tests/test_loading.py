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


def test_top_gear_left_from_its_passes():
    from paf.progress import _gear_left

    log = ("== Top Gear with your 36 items  [+3s]\nPass 1: 47 single swaps x 1 fight(s)\n  boss fight: 25s\n"
           "  kept: shoulder: 1\nPass 2: 215 combinations x 1 fight(s)\n")
    # 25 s for 47 -> 215 at the same pace = 114 s; 25 s of pass 1 + 30 s of pass 2 elapsed
    left = _gear_left(log, 55 / 60)
    assert round(left * 60) == round(215 * 25 / 47 - 30)
    assert _gear_left("== Top Gear  [+3s]\nPass 1: 47 single swaps x 1 fight(s)\n", 0.2) is None  # no pace yet
