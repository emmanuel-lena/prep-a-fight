"""Build a typical fight (paf.fight.Fight) for a boss from its corpus."""

from __future__ import annotations

import math
import re
import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import KILLABLE_DEATH_RATE, _q, canonical_waves, fight_waves, kills_filter
from paf.fight import AddWave, Fight, Vulnerable, Window

LUST_NAMES = {"bloodlust", "heroism", "time warp", "primal rage", "fury of the aspects", "ancient hysteria",
              "netherwinds", "drums of fury", "drums of the mountain", "drums of the maelstrom",
              "feral hide drums", "thunderous drums", "timeless drums", "harrier's cry"}
POWER_INFUSION = 10060

MOVE_SPEED = 1.5  # yards/s between two consecutive casts above which the player is moving
MAX_GAP = 4.0  # seconds; longer gaps between casts are not used to infer movement
MOVE_SHARE = 0.5  # a second belongs to a movement window when at least half of the players move
MIN_MOVE = 3.0  # seconds; shorter movement windows are ignored
MERGE_GAP = 3  # seconds; movement windows closer than this are merged
BOSS_UNIT_MIN_SHARE = 0.02  # secondary boss units taking less raid damage than this are mechanics, not targets
ATTACK_GAP = 10.0  # seconds without a cast on a unit that end an attack window


@dataclass
class TemplateInfo:
    kills: int
    moving_share: float  # median share of the fight the ranked players spend moving
    movement_by_phase: list[tuple[str, float]] = field(default_factory=list)
    boss_units: list[AddWave] = field(default_factory=list)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def moving_seconds(points: list[tuple[float, float, float]], duration: float) -> list[bool]:
    """Per-second moving flags from (t, x, y) points of one player."""
    flags = [False] * (int(duration) + 1)
    pts = sorted(p for p in points if p[1] is not None and p[2] is not None)
    for (t0, x0, y0), (t1, x1, y1) in zip(pts, pts[1:], strict=False):
        dt = t1 - t0
        if dt <= 0 or dt > MAX_GAP:
            continue
        if math.dist((x0, y0), (x1, y1)) / dt >= MOVE_SPEED:
            for s in range(int(t0), min(int(t1) + 1, len(flags))):
                flags[s] = True
    return flags


def movement_windows(per_kill: list[list[bool]], share: float = MOVE_SHARE) -> list[Window]:
    if not per_kill:
        return []
    length = min(len(f) for f in per_kill)
    frac = [sum(f[s] for f in per_kill) / len(per_kill) for s in range(length)]
    raw: list[list[int]] = []
    start = None
    for s, v in enumerate(frac + [0.0]):
        if v >= share and start is None:
            start = s
        elif v < share and start is not None:
            if raw and start - raw[-1][1] <= MERGE_GAP:
                raw[-1][1] = s
            else:
                raw.append([start, s])
            start = None
    return [Window(float(a), float(b - a)) for a, b in raw if b - a >= MIN_MOVE]


def attack_windows(con: sqlite3.Connection, where: str, params: tuple, spec: str,
                   keys: list[tuple[str, int]]) -> list[AddWave]:
    """Windows when secondary boss units (e.g. a heart) are attacked, from the ranked players' casts.

    Only units taking a real share of the raid's damage count; the others are mechanics.
    """
    shares = dict(con.execute(
        f"SELECT d.target, SUM(d.amount) FROM damage_by_target d JOIN fight f USING(report, fight_id) "
        f"WHERE {where} GROUP BY d.target", params).fetchall())
    total = sum(v or 0 for v in shares.values()) or 1
    units = {r[0] for r in con.execute("SELECT name FROM npc WHERE is_boss=1")
             if (shares.get(r[0]) or 0) / total >= BOSS_UNIT_MIN_SHARE}
    if not units:
        return []
    casts = con.execute(
        f"SELECT c.report, c.fight_id, n.name, c.t FROM player_cast c JOIN fight f USING(report, fight_id) "
        f"JOIN ranked r USING(report, fight_id) "
        f"JOIN add_instance a ON a.report=c.report AND a.fight_id=c.fight_id AND a.actor_id=c.target_id "
        f"AND a.instance=COALESCE(c.target_instance, 1) JOIN npc n ON n.game_id=a.game_id "
        f"WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? AND c.type='cast' "
        f"AND n.name IN ({','.join('?' * len(units))}) ORDER BY c.t", (*params, spec, *units)).fetchall()
    segments: dict[tuple[str, int], list] = defaultdict(list)
    for name in units:
        per_kill: dict[tuple[str, int], list[float]] = defaultdict(list)
        for c in casts:
            if c["name"] == name:
                per_kill[(c["report"], c["fight_id"])].append(c["t"])
        for k, times in per_kill.items():
            seg_start = prev = times[0]
            for tt in times[1:] + [None]:
                if tt is None or tt - prev > ATTACK_GAP:
                    segments[k].append((seg_start, prev - seg_start + 2.0, name))
                    if tt is not None:
                        seg_start = tt
                if tt is not None:
                    prev = tt
    waves = canonical_waves([[(s, 1, d, [nm]) for s, d, nm in segments.get(k, [])] for k in keys])
    return [AddWave(w.t, 1, w.lifetime, ", ".join(w.types), scalable=False) for w in waves if w.lifetime >= 5]


def ability_names_all(con: sqlite3.Connection) -> dict[int, str]:
    from paf.gamedata import spell_names

    try:
        names = dict(spell_names())
    except OSError:
        names = {}
    names.update(dict(con.execute("SELECT id, name FROM ability").fetchall()))
    return names


def boss_unit_multiplier(con: sqlite3.Connection, where: str, params: tuple, boss_name: str, units: set[str],
                         units_time: float, duration: float, invulnerable_time: float, kills: int) -> float:
    """Damage amplification of secondary boss units: the raid's damage rate on them during their windows
    divided by its rate on the boss the rest of the attackable time (clamped to 1-5)."""
    if not units or units_time <= 0 or not kills:
        return 1.0
    names = {n for u in units for n in u.split(", ")}
    rows = dict(con.execute(
        f"SELECT d.target, SUM(d.amount) FROM damage_by_target d JOIN fight f USING(report, fight_id) "
        f"WHERE {where} GROUP BY d.target", params).fetchall())
    unit_dmg = sum(rows.get(n) or 0 for n in names)
    boss_dmg = rows.get(boss_name) or 0
    boss_time = duration - invulnerable_time - units_time
    if boss_dmg <= 0 or boss_time <= 0:
        return 1.0
    ratio = (unit_dmg / (kills * units_time)) / (boss_dmg / (kills * boss_time))
    return round(min(5.0, max(1.0, ratio)), 2)


def build_template(con: sqlite3.Connection, encounter_id: int, difficulty: int, boss_name: str,
                   spec: str, diff_name: str = "") -> tuple[Fight, TemplateInfo]:
    where, params = kills_filter(encounter_id, difficulty)
    fights = con.execute(f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}", params).fetchall()
    keys = sorted((r["report"], r["fight_id"]) for r in fights)
    duration = st.median(r["duration_s"] for r in fights)

    # adds and secondary boss units
    rows = con.execute(
        f"SELECT a.report, a.fight_id, n.name, n.is_boss, a.t_spawn, a.t_death, a.died FROM add_instance a "
        f"JOIN npc n USING(game_id) JOIN fight f USING(report, fight_id) WHERE {where}", params).fetchall()
    death_rate: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        death_rate[r["name"]].append(r["died"])
    killable = {n for n, d in death_rate.items() if sum(d) / len(d) >= KILLABLE_DEATH_RATE}
    adds: dict[tuple[str, int], list] = defaultdict(list)
    for r in rows:
        if r["t_spawn"] is None or r["name"] not in killable or r["is_boss"]:
            continue
        adds[(r["report"], r["fight_id"])].append((r["t_spawn"], r["t_death"] - r["t_spawn"], r["name"]))
    add_waves = [AddWave(w.t, max(1, round(w.count)), w.lifetime, ", ".join(w.types))
                 for w in canonical_waves([fight_waves(adds.get(k, [])) for k in keys])]
    boss_waves = attack_windows(con, where, params, spec, keys)

    # intermissions -> the main boss is not attackable
    phases = defaultdict(list)
    for r in con.execute(f"SELECT p.* FROM phase p JOIN fight f USING(report, fight_id) WHERE {where}", params):
        phases[r["phase_id"]].append((r["t_start"], r["is_intermission"], r["name"]))
    ordered = sorted((pid, st.median(v[0] for v in vals), vals[0][1], vals[0][2]) for pid, vals in phases.items())
    invulnerable = []
    for i, (_, start, inter, _name) in enumerate(ordered):
        if inter:
            end = ordered[i + 1][1] if i + 1 < len(ordered) else duration
            invulnerable.append(Window(round(start, 1), round(end - start, 1)))

    # lust and power infusion on the ranked players
    names = {r[0]: (r[1] or "").lower() for r in con.execute("SELECT id, name FROM ability")}
    lust_times, pi_times = [], []
    buffs = con.execute(
        f"SELECT b.report, b.fight_id, b.ability_id, b.t FROM player_buff b JOIN fight f USING(report, fight_id) "
        f"JOIN ranked r USING(report, fight_id) WHERE {where} AND b.type='applybuff' AND b.actor_id=r.actor_id "
        f"AND r.spec=? ORDER BY b.t", (*params, spec)).fetchall()
    first_lust: dict[tuple[str, int], float] = {}
    pis: dict[tuple[str, int], list] = defaultdict(list)
    for b in buffs:
        k = (b["report"], b["fight_id"])
        if names.get(b["ability_id"], "") in LUST_NAMES and k not in first_lust:
            first_lust[k] = b["t"]
        if b["ability_id"] == POWER_INFUSION:
            pis[k].append((b["t"], 15.0, "pi"))
    lust_times = list(first_lust.values())
    pi_waves = canonical_waves([fight_waves(pis.get(k, [])) for k in keys])
    pi_times = [w.t for w in pi_waves if w.support >= 0.3]

    # movement from the ranked players' trajectories
    pts: dict[tuple[str, int], list] = defaultdict(list)
    for r in con.execute(
            f"SELECT c.report, c.fight_id, c.t, c.x, c.y FROM player_cast c JOIN fight f USING(report, fight_id) "
            f"JOIN ranked r USING(report, fight_id) WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? "
            f"AND c.x IS NOT NULL", (*params, spec)):
        pts[(r["report"], r["fight_id"])].append((r["t"], r["x"], r["y"]))
    per_kill = [moving_seconds(p, duration) for p in pts.values() if len(p) > 50]
    moves = movement_windows(per_kill)
    moving_share = st.median(sum(f) / len(f) for f in per_kill) if per_kill else 0.0
    by_phase = []
    for i, (_, start, _inter, name) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else duration
        vals = [sum(f[int(start):int(end)]) / max(1, int(end) - int(start)) for f in per_kill]
        if vals:
            by_phase.append((name, st.median(vals)))

    # secondary boss units (e.g. a heart) share the boss's health: their windows become boss vulnerability
    # windows, with the damage amplification measured in the logs
    from paf.corpus.units import trigger_casts, unit_windows

    measured, ratios = unit_windows(con, encounter_id, difficulty)
    if measured:  # damage-taken graphs of a few kills: real windows and damage rate ratio of each unit
        waves = canonical_waves([[(s, 1, d, [nm]) for s, d, nm in kill] for kill in measured.values()])
        vulnerable = []
        ability_names = dict(con.execute("SELECT id, name FROM ability").fetchall())
        for w in waves:
            start, end, label = w.t, w.t + w.lifetime, ", ".join(w.types)
            trig = trigger_casts(con, measured, w.t, ability_names)
            if trig:  # the window opens when the boss's cast ends (more precise than the damage graph)
                start = trig[1]
                label += f" (after {trig[0]})"
            vulnerable.append(Vulnerable(round(start, 1), round(max(1.0, end - start), 1),
                                         round(min(5.0, max(1.0, ratios.get(w.types[0], 1.0))), 2), label))
    else:  # fallback: the ranked players' casts on the unit
        mult = boss_unit_multiplier(con, where, params, boss_name, {w.name for w in boss_waves},
                                    sum(w.lifetime for w in boss_waves), duration,
                                    sum(w.duration for w in invulnerable), len(keys))
        vulnerable = [Vulnerable(round(w.time, 1), round(w.lifetime, 1), mult, w.name) for w in boss_waves]

    from paf.corpus.units import amp_candidates

    candidates = [Vulnerable(round(t, 1), round(d, 1), ratio, f"{name} (boss aura)")
                  for name, ratio, wins, _k in amp_candidates(con, encounter_id, difficulty, ability_names_all(con))
                  for t, d in wins]

    fight = Fight(
        name=f"{boss_name} {diff_name}".strip(),
        duration=round(duration, 1),
        add_waves=add_waves,
        vulnerable=vulnerable,
        candidate_vulnerable=candidates,
        invulnerable=invulnerable,
        movement=moves,
        lust_time=round(st.median(lust_times), 1) if lust_times else 0.0,
        power_infusion=[round(t, 1) for t in pi_times],
        source=f"median of {len(keys)} ranked kills (paf corpus)",
    )
    return fight, TemplateInfo(len(keys), moving_share, by_phase, boss_waves)


def template_path(boss_name: str, diff_name: str):
    from paf.config import data_dir

    return data_dir() / "fights" / f"{_slug(boss_name)}-{diff_name}.json"


def lust_quantiles(values: list[float]) -> tuple[float, float, float]:
    return _q(values, .25), _q(values, .5), _q(values, .75)
