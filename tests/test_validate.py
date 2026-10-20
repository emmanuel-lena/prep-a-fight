import sqlite3

from paf.corpus.db import SCHEMA
from paf.fight import Fight
from paf.validate import validate
from paf.wcl import WCLError


def test_a_log_made_private_is_skipped(tmp_path):
    """The Coiled Altar mythic (2026-10-20): a ranked player's log turned private; the validation goes on with the
    next player instead of stopping."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for k in (1, 2):
        con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                    "VALUES(?, 1, 9, 5, 300, 'done')", (f"r{k}",))
        con.execute("INSERT INTO ranked(report, fight_id, class, spec, rank_pos, dps, actor_id, gear_json) "
                    "VALUES(?, 1, 'Shaman', 'Elemental', ?, 1000, 7, '[]')", (f"r{k}", k))

    class Private:
        def query(self, *a, **k):
            raise WCLError("GraphQL error: You do not have permission to view this report.")

    assert validate(con, Private(), 9, 5, "Elemental", Fight(name="x", duration=300), tmp_path) == []
