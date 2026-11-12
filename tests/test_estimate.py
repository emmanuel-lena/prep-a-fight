import sqlite3
from types import SimpleNamespace

from paf import estimate
from paf.corpus.db import SCHEMA


def test_a_first_prep_counts_the_kills_and_the_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setattr("paf.pack.fetch_shared", lambda *a: None)
    monkeypatch.setattr(estimate, "sims_minutes", lambda first=False: 5.0)
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    fresh = SimpleNamespace(rate_limit=lambda: {"limitPerHour": 3600, "pointsSpentThisHour": 0, "pointsResetIn": 3600})
    e = estimate.plan(con, 9, 4, "Rogue", "Subtlety", fresh)
    assert e.source == "collect" and e.kills == 100 and e.wait == 0
    assert round(e.minutes) == 9  # 100 kills at 25 a minute, then 5 min of sims
    spent = SimpleNamespace(rate_limit=lambda: {"limitPerHour": 3600, "pointsSpentThisHour": 3000,
                                                "pointsResetIn": 1200})
    e = estimate.plan(con, 9, 4, "Rogue", "Subtlety", spent)
    assert round(e.wait) == 20 and "waiting for your Warcraft Logs quota" in e.sentence  # 1200 points, 600 left
    for i in range(30):
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status) VALUES(?, 1, 9, 4, 'done')",
                    (f"r{i}",))
    assert estimate.plan(con, 9, 4, "Rogue", "Subtlety", fresh).source == "corpus"


def test_a_first_prep_of_a_boss_is_not_predicted_from_preps_that_reused_their_sims(tmp_path, monkeypatch):
    # the owner, 2026-11-12: "it said 6 minutes, it took 12": the medians of preps again (their sims reused, 2 s)
    import json

    from paf import progress

    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    (tmp_path / "web").mkdir()
    hist = {"Ideal cooldown plan": [2, 2, 2, 600], "Your class's specs": [60, 60, 60],
            "Collecting the corpus": [180], "Collecting who handles": [60]}
    (tmp_path / "web" / "step-times.json").write_text(json.dumps(hist))
    assert estimate.sims_minutes() == (2 + 60) / 60  # every step, its median: the specs' step counted
    assert estimate.sims_minutes(first=True) == (600 + 60) / 60  # no first prep kept yet: the slowest
    hist["first:Ideal cooldown plan"] = [480, 540]
    (tmp_path / "web" / "step-times.json").write_text(json.dumps(hist))
    assert estimate.sims_minutes(first=True) == (510 + 60) / 60  # the first preps' median
    assert estimate.collect_minutes(50, 100) == 2.0  # this computer's pace, who handles what included
    _rows, left = progress.prep_progress("First prep of this boss for this spec on this computer: every sim runs.\n"
                                         "== Analyzing the corpus  [+0s]\n")
    assert left > 8  # the first preps' times, not the medians of preps again
