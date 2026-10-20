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


def test_an_item_simc_lacks_drops_its_slot(tmp_path, monkeypatch):
    """The Coiled Altar heroic, Subtlety (2026-10-20): a top player's ring (268249) is missing from SimC's offline
    data and SimC stops; the player is simmed again without that slot (their real stats are imposed anyway)."""
    from types import SimpleNamespace

    from paf import simc
    from paf import validate as v

    seen = []

    def run(text, run_dir, target_error=0.3):
        seen.append("finger1=" in text)
        if "finger1=" in text:
            raise simc.SimcError("Player 'rank3': Item 'inactive' Slot 'finger1': Error retrieving item from BCP API")
        ps = SimpleNamespace(name="held", dps=SimpleNamespace(mean=1000.0), metrics={})
        return SimpleNamespace(profilesets=[ps], baseline={"dps": SimpleNamespace(mean=990.0)})

    monkeypatch.setattr(simc, "run", run)
    monkeypatch.setattr(v, "aligned_apl", lambda *a: (["actions=x"], ["actions=y"]))
    monkeypatch.setattr(v, "_player_profile", lambda *a: "rogue=r\nfinger1=,id=268249\nhead=,id=1\n")
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("INSERT INTO fight(report, fight_id, encounter_id, difficulty, duration_s, status) "
                "VALUES('r', 1, 9, 4, 300, 'done')")
    con.execute("INSERT INTO ranked(report, fight_id, class, spec, rank_pos, dps, actor_id, gear_json) "
                "VALUES('r', 1, 'Rogue', 'Subtlety', 3, 1000, 7, '[]')")
    checks = validate(con, object(), 9, 4, "Subtlety", Fight(name="x", duration=300), tmp_path)
    assert [c.ratio for c in checks] == [1.0] and seen == [True, False]
