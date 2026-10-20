"""A raid like yours (paf.killtime, issue #26): which kills its fight is rebuilt from."""
from paf.killtime import slow_cut


def test_the_slowest_quarter_without_your_kill():
    durations = [240 + i for i in range(100)]  # 4:00 to 5:39, median 4:49
    cut = slow_cut(durations)
    assert cut.min_duration == 314 and cut.kills == 26 and "slowest quarter" in cut.why  # their median: 5:26
    assert slow_cut([280 + i / 5 for i in range(100)]) is None  # all within 20 s: one kill time is enough


def test_as_slow_as_your_raid():
    durations = [240 + i for i in range(100)]
    cut = slow_cut(durations, own=330.0)  # 5:30, 14% over the median
    assert cut.min_duration == 310.0 and cut.kills == 30 and "5:30" in cut.why  # at least 30 kills
    assert "slowest quarter" in slow_cut(durations, own=250.0).why  # a raid as fast as the tops: the slower quarter
    assert slow_cut(durations[:50], own=330.0) is None  # too few kills to rebuild a fight from


def test_the_fight_tab_switches_between_kill_times():
    from paf import fightview
    from paf.prep_report import PrepData

    d = PrepData("Nek'zali", "heroic", "Elemental", "Char", kills=225, duration=255.7)
    assert fightview.kill_switch(d) == ""  # one kill time: no switch
    d.kill_times = [("typical top kill", 255.7, "prep-nek-heroic.html"),
                    ("slower top kills", 313.7, "prep-nek-heroic-slow.html")]
    html = fightview.kill_switch(d)
    assert "href='prep-nek-heroic.html#fight' class='ks on' aria-current=page><b>4:15</b>" in html
    assert "href='prep-nek-heroic-slow.html#fight' class='ks'><b>5:13</b>" in html


def test_a_raid_like_yours_is_not_another_boss(tmp_path, monkeypatch):
    from paf import web

    reports = tmp_path / "reports"
    reports.mkdir()
    for name in ("prep-nek-zali-heroic-elemental-shaman.html", "prep-nek-zali-heroic-elemental-shaman-slow.html"):
        (reports / name).write_text("<title>Nek'zali prep</title>", encoding="utf-8")
    monkeypatch.setattr(web, "data_dir", lambda: tmp_path)
    assert [x["key"] for x in web.prepared()] == ["nek-zali-heroic-elemental-shaman"]
