import sqlite3
from types import SimpleNamespace

from paf.corpus import collect as col
from paf.corpus.db import SCHEMA


def test_a_first_prep_fetches_only_the_best_ranked_kills(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for i in range(5):
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status) "
                    "VALUES(?, 1, 9, 4, 'pending')",
                    (f"r{i}",))
        con.execute("INSERT INTO ranked(report, fight_id, rank_pos, dps, name, class, spec) "
                    "VALUES(?, 1, ?, 1, 'x', 'Rogue', 'Subtlety')", (f"r{i}", 5 - i))
    fetched = []

    def fake(client, con, report, fight_id, name, ranked):
        fetched.append(report)
        return {"adds": [], "fight": {"duration_s": 1}, "players": []}
    monkeypatch.setattr(col, "fetch_kill", fake)
    client = SimpleNamespace(rate_limit=lambda: {"pointsSpentThisHour": 0, "limitPerHour": 3600, "pointsResetIn": 1})
    stats = col.collect(client, con, SimpleNamespace(id=9), 4, limit=2, log=lambda s: None)
    assert stats["done"] == 2 and fetched == ["r4", "r3"]  # the two best ranked (rank_pos 1, 2), the rest later
