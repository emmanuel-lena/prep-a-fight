"""Calibrate a rebuilt fight against the logs.

SimC puts every add of a wave in range for the whole lifetime, while real players split targets and
the raid kills adds at different speeds. We scale the add counts until the simulated share of damage
done to the main boss matches the median share of the top players of the spec in the corpus.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from paf import simc
from paf.corpus.analyze import kills_filter
from paf.fight import Fight

SCALES = (0.1, 0.2, 0.3, 0.45, 0.6, 0.8, 1.0)


def real_boss_share(con: sqlite3.Connection, encounter_id: int, difficulty: int, boss_name: str,
                    spec: str) -> float | None:
    """Median share of the ranked players' damage done to the main boss."""
    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(
        f"SELECT d.report, d.fight_id, d.target, d.amount FROM damage_by_target d "
        f"JOIN fight f USING(report, fight_id) JOIN ranked r USING(report, fight_id) "
        f"WHERE {where} AND d.actor_id=r.actor_id AND r.spec=?", (*params, spec)).fetchall()
    per: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        acc = per[(r["report"], r["fight_id"])]
        acc[0] += r["amount"] or 0
        if r["target"] == boss_name:
            acc[1] += r["amount"] or 0
    shares = [b / t for t, b in per.values() if t > 0]
    return st.median(shares) if shares else None


@dataclass
class Calibration:
    target: float
    points: list[tuple[float, float, float]]  # scale, simulated boss share, total dps
    scale: float


def calibrate(profile_text: str, fight: Fight, target_share: float, run_dir: Path,
              target_error: float = 0.5) -> Calibration:
    base_lines = [line for line in fight.to_simc() if not line.startswith("raid_events")]
    sets = {f"x{int(s * 100)}": fight.raid_event_lines(add_scale=s) for s in SCALES}
    res = simc.run(simc.build_input(profile_text, base_lines + fight.raid_event_lines(), sets), run_dir,
                   target_error=target_error)
    points = []
    for s in SCALES:
        ps = next((p for p in res.profilesets if p.name == f"x{int(s * 100)}"), None)
        if ps and "prioritydps" in ps.metrics and ps.dps.mean:
            points.append((s, ps.metrics["prioritydps"].mean / ps.dps.mean, ps.dps.mean))
    points.sort()
    scale = 1.0
    if points:
        # boss share decreases when the scale grows: find the bracket around the target, interpolate
        scale = min(points, key=lambda p: abs(p[1] - target_share))[0]
        for (s0, b0, _), (s1, b1, _) in zip(points, points[1:], strict=False):
            if (b0 - target_share) * (b1 - target_share) <= 0 and b0 != b1:
                scale = s0 + (s1 - s0) * (b0 - target_share) / (b0 - b1)
                break
    return Calibration(target_share, points, round(scale, 3))
