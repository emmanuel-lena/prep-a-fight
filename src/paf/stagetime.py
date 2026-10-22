"""Stage time: a kill's times read from the start of the stage they fall in, placed at that stage's median start.

A boss's timers restart with each stage, and its stages start at different times from one kill to the next
(Nek'zali heroic: Stage Two from 2:34 to 3:30). Lined up on the pull, the waves of a late stage smear out of a median
curve and the top players' answers to them read as pressed at no hit (round 100: Stage Two's two raid hits, +50 s
and +80 s into it, missing from every healer sheet while the top Evokers' Rewinds landed on them). Read in stage
time, a wave sits at the same place in every kill. A boss with no stage keeps its pull time.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from pathlib import Path

Kill = tuple[str, int]


def kill_stages(encounter_id: int, difficulty: int, paths: list[Path] | None = None) -> dict[Kill, dict[int, float]]:
    """Each kill's stage starts (phase id -> seconds from the pull), read from every corpus."""
    from paf.config import data_dir

    out: dict[Kill, dict[int, float]] = {}
    for path in paths if paths is not None else sorted(data_dir().glob("corpus-*.sqlite")):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='phase'").fetchone():
                continue
            for rep, fid, pid, t in con.execute(
                    "SELECT p.report, p.fight_id, p.phase_id, p.t_start FROM phase p JOIN fight f USING(report, "
                    "fight_id) WHERE f.encounter_id = ? AND f.difficulty = ?", (encounter_id, difficulty)):
                out.setdefault((rep, fid), {})[pid] = t
        finally:
            con.close()
    return {k: v for k, v in out.items() if len(v) > 1}  # a single stage: nothing to line up


def median_starts(stages: dict[Kill, dict[int, float]]) -> dict[int, float]:
    """Each stage's median start over the kills that reach it."""
    per: dict[int, list[float]] = defaultdict(list)
    for s in stages.values():
        for pid, t in s.items():
            per[pid].append(t)
    return {pid: st.median(ts) for pid, ts in per.items()}


class Clock:
    """Maps a kill's pull time to stage time: the stage it falls in, at that stage's median start."""

    def __init__(self, stages: dict[Kill, dict[int, float]]):
        self.stages = stages
        self.med = median_starts(stages)

    def __bool__(self) -> bool:
        return bool(self.stages)

    def known(self, kill: Kill) -> bool:
        return kill in self.stages

    def at(self, kill: Kill, t: float) -> float | None:
        """t in stage time; None for a time of a stage that ran past the next stage's median start (a kill whose
        Stage Two came late: its Stage One's last seconds would sit on the others' Stage Two, and on its own)."""
        s = self.stages.get(kill)
        if not s:
            return t
        pid, start = max(((p, x) for p, x in s.items() if x <= t), key=lambda y: y[1], default=(None, 0.0))
        if pid is None:
            return t
        out = self.med.get(pid, start) + (t - start)
        later = [self.med[p] for p, x in s.items() if x > start and p in self.med]
        return None if later and out >= min(later) else out




def clock(encounter_id: int, difficulty: int, paths: list[Path] | None = None) -> Clock:
    return Clock(kill_stages(encounter_id, difficulty, paths))


def warp(tl, clk: Clock):
    """A timeline in stage time: each player's casts and kill length, the stage lines at their median starts. The
    timeline itself is left as it is (its boss casts, read by ordinal, stay in pull time)."""
    import copy

    if not clk:
        return tl
    out = copy.copy(tl)
    players = []
    for p in tl.players:
        k = p.get("kill")
        if k is None or not clk.known(k):
            players.append(p)
            continue
        q = dict(p)
        q["casts"] = {a: [x for t in ts if (x := clk.at(k, t)) is not None] for a, ts in p["casts"].items()}
        end = clk.at(k, p.get("duration") or tl.duration)
        q["duration"] = end if end is not None else max(clk.med.values(), default=p.get("duration") or tl.duration)
        players.append(q)
    out.players = players
    starts = sorted(clk.med.values())
    if len(starts) == len(tl.phases):  # the stage lines where the stage clock puts them
        out.phases = [(n, t_, *rest) for (n, _t, *rest), t_ in zip(tl.phases, starts, strict=False)]
    durs = [q["duration"] for q in players if q.get("duration")]
    if durs:
        out.duration = st.median(durs)
    return out
