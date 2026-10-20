"""The kill time a sheet plans for (issue #26): the top raids' kill, or a raid like yours, slower.

PRODUCT principle 7: the fight is simmed over the kill times raids actually have, not one duration. A slower raid's
fight is not the top raids' one stretched: its intermission comes later, a wave more spawns, Bloodlust lands
elsewhere. So it is rebuilt from the slower kills of the corpus (paf.corpus.analyze.slower_kills): as slow as your
raid's last kill of the boss (paf.lastraid) when it is slower than the top raids', else their slowest quarter.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from dataclasses import dataclass

MIN_KILLS = 30  # the slower kills the fight is rebuilt from: never fewer (its waves and phases need them)
SLOWER = 1.08  # a kill time at least this much longer than the top raids' median is worth a sheet of its own
YOURS = 0.95  # your raid's kill: the kills at least this close to it


@dataclass
class SlowCut:
    min_duration: float  # the corpus kills lasting at least this long
    why: str  # "as slow as your raid's last kill (5:41)" or "the slowest quarter of the top kills"
    kills: int

    @property
    def short(self) -> str:
        """The kill-time switch's label."""
        mine = self.why.startswith("as slow as your")
        return "like your raid's last kill" if mine else "a slower top kill (1 in 4)"


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def slow_cut(durations: list[float], own: float | None = None) -> SlowCut | None:
    """Which kills a raid like yours is rebuilt from, or None when the top kills are all about as long (or too few)."""
    ds = sorted(durations)
    if len(ds) < 2 * MIN_KILLS:
        return None
    mid = st.median(ds)
    if own and own > mid * SLOWER:
        cut, why = min(own * YOURS, ds[-MIN_KILLS]), f"as slow as your raid's last kill ({_mmss(own)})"
    else:
        cut, why = ds[int(0.75 * (len(ds) - 1))], "the slowest quarter of the top kills"
    slower = [d for d in ds if d >= cut]
    if st.median(slower) < mid * SLOWER:
        return None
    return SlowCut(round(cut, 1), why, len(slower))


def corpus_durations(con: sqlite3.Connection, encounter_id: int, difficulty: int) -> list[float]:
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    return [r[0] for r in con.execute(f"SELECT duration_s FROM fight f WHERE {where}", params) if r[0]]
