import sqlite3
from types import SimpleNamespace

from paf import estimate
from paf.corpus.db import SCHEMA


def test_a_first_prep_counts_the_kills_and_the_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("PAF_HOME", str(tmp_path))
    monkeypatch.setattr("paf.pack.fetch_shared", lambda *a: None)
    monkeypatch.setattr(estimate, "sims_minutes", lambda: 5.0)
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
