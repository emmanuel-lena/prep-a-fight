import sqlite3

from paf.corpus.db import SCHEMA
from paf.corpus.mechanics import fetch_mechanics
from paf.wcl import WCLQuota


class _Client:
    def __init__(self):
        self.calls = 0

    def query(self, *a, **k):
        self.calls += 1
        raise WCLQuota("Warcraft Logs quota used up for this hour")


def test_who_handles_stops_on_the_quota_with_one_line():
    # issue #34: the quota used up mid-step cost a 54 min wait; the step stops, the rest is read on a later prep
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO fight(report, fight_id, encounter_id, difficulty, status) VALUES(?,?,?,?,?)",
                    [(f"r{i}", 1, 3420, 5, "done") for i in range(5)])
    lines, client = [], _Client()
    fetch_mechanics(client, con, 3420, 5, [], log=lines.append)
    assert client.calls == 1 and len(lines) == 1 and "later prep" in lines[0]
    assert con.execute("SELECT COUNT(*) FROM mech_status").fetchone()[0] == 0  # nothing marked: read next time
