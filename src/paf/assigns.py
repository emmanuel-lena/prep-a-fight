"""Player assignments: when each boss mechanic happens and what it costs the player who handles it.

Timings come from the corpus (debuffs of boss mechanics on players, and interrupts). The cost is
measured on the ranked players of the analyzed spec: in kills where they handled the mechanic,
how much more did they move (from their trajectory) than in kills where they did not, around the
same time. An assignment then becomes movement windows in the simulated fight.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass

from paf.corpus.analyze import canonical_waves, kills_filter
from paf.corpus.template import moving_seconds
from paf.fight import Fight, Window

WINDOW_BEFORE = 3.0  # seconds before the debuff / kick included in the cost window
WINDOW_AFTER = 8.0
DEFAULT_COST = 3.0  # seconds of movement when the corpus has too few samples
MIN_SAMPLES = 5
TANK_SPECS = {"Blood", "Brewmaster", "Protection", "Guardian", "Vengeance"}


@dataclass
class Mechanic:
    key: str  # "debuff:<id>" or "interrupt:<id>"
    name: str
    kind: str
    times: list[float]  # typical times in the fight
    cost: float  # extra seconds of movement for the player who handles it, each time
    samples: int  # kills where the analyzed spec handled it (basis of the cost)
    players_per_kill: float


def _cluster_times(per_kill: list[list[float]], support: float = 0.3) -> list[float]:
    waves = canonical_waves([[(t, 1, 0.0, [""]) for t in sorted(ts)] for ts in per_kill])
    return [w.t for w in waves if w.support >= support]


def mechanic_timings(con: sqlite3.Connection, encounter_id: int, difficulty: int, spec: str,
                     names: dict[int, str], keep: set[str] | None = None) -> list[Mechanic]:
    where, params = kills_filter(encounter_id, difficulty)
    kills = [tuple(r) for r in con.execute(
        f"SELECT f.report, f.fight_id FROM fight f JOIN mech_status m USING(report, fight_id) WHERE {where}", params)]
    durations = dict(((r[0], r[1]), r[2]) for r in con.execute(
        f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}", params))
    ranked = {(r[0], r[1]): r[2] for r in con.execute(
        f"SELECT r.report, r.fight_id, r.actor_id FROM ranked r JOIN fight f USING(report, fight_id) "
        f"WHERE {where} AND r.spec=? AND r.actor_id IS NOT NULL", (*params, spec))}
    events: dict[tuple[str, int], dict[tuple[str, int], list[tuple[float, int]]]] = \
        defaultdict(lambda: defaultdict(list))
    for r in con.execute(f"SELECT e.* FROM mech_event e JOIN fight f USING(report, fight_id) WHERE {where}", params):
        if r["ability_id"] is not None:
            events[(r["kind"], r["ability_id"])][(r["report"], r["fight_id"])].append((r["t"], r["actor_id"]))

    # per-second moving flags of the ranked players, from their trajectories
    pts: dict[tuple[str, int], list] = defaultdict(list)
    for r in con.execute(
            f"SELECT c.report, c.fight_id, c.t, c.x, c.y FROM player_cast c JOIN fight f USING(report, fight_id) "
            f"JOIN ranked r USING(report, fight_id) WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? "
            f"AND c.x IS NOT NULL", (*params, spec)):
        pts[(r["report"], r["fight_id"])].append((r["t"], r["x"], r["y"]))
    moving = {k: moving_seconds(p, durations.get(k, 600)) for k, p in pts.items() if len(p) > 50}

    def moved(k: tuple[str, int], t: float) -> float | None:
        flags = moving.get(k)
        if flags is None:
            return None
        a, b = max(0, int(t - WINDOW_BEFORE)), min(len(flags), int(t + WINDOW_AFTER) + 1)
        return float(sum(flags[a:b])) if b > a else None

    player_spec = {(r[0], r[1], r[2]): r[3] for r in con.execute(
        f"SELECT p.report, p.fight_id, p.actor_id, p.spec FROM player p JOIN fight f USING(report, fight_id) "
        f"WHERE {where}", params)}
    spec_is_tank = spec in TANK_SPECS

    out: list[Mechanic] = []
    for (kind, aid), by_kill in events.items():
        key = f"{kind}:{aid}"
        name = names.get(aid, f"spell {aid}")
        if keep is not None and kind != "interrupt" and name.lower() not in keep:
            continue
        if len(by_kill) < max(3, len(kills) * 0.2):
            continue
        handlers = [player_spec.get((k[0], k[1], a), "") for k, v in by_kill.items() for _, a in v]
        tank_share = sum(s in TANK_SPECS for s in handlers) / max(1, len(handlers))
        if kind != "interrupt" and (tank_share > 0.5) != spec_is_tank and tank_share > 0.5:
            continue  # a tank mechanic, not assignable to this spec
        times = _cluster_times([[t for t, _ in v] for v in by_kill.values()])
        if not times:
            continue
        # cost: movement of the ranked player when they handled it vs when someone else did, at the same time
        handled, not_handled = [], []
        for k, evs in by_kill.items():
            me = ranked.get(k)
            if me is None:
                continue
            mine = [t for t, a in evs if a == me]
            if mine:
                for t in mine:
                    m = moved(k, t)
                    if m is not None:
                        handled.append(m)
            else:
                for t in {t for t, _ in evs}:
                    m = moved(k, t)
                    if m is not None:
                        not_handled.append(m)
        if len(handled) >= MIN_SAMPLES and len(not_handled) >= MIN_SAMPLES:
            cost = max(0.0, st.median(handled) - st.median(not_handled))
        elif kind == "interrupt":
            cost = 0.0  # interrupts are instant; the cost is the target swap, ignored
        else:
            cost = DEFAULT_COST
        players = st.median(len({a for _, a in v}) for v in by_kill.values())
        out.append(Mechanic(key, name, kind, [round(t, 1) for t in times], round(min(cost, 10.0), 1),
                            len(handled), players))
    out.sort(key=lambda m: (m.kind != "debuff", m.players_per_kill, m.name))
    return out


def apply_assigns(fight: Fight, mechanics: list[Mechanic], chosen: list[str]) -> tuple[Fight, list[str]]:
    """Movement windows for every chosen mechanic (names or keys), each time it happens."""
    f = Fight(**{**fight.__dict__})
    f.personal_movement = list(fight.personal_movement)
    notes = []
    by = {m.name.lower(): m for m in mechanics} | {m.key: m for m in mechanics}
    for c in chosen:
        m = by.get(c.lower()) or by.get(c)
        if m is None:
            notes.append(f"unknown mechanic {c!r}")
            continue
        if m.cost <= 0:
            notes.append(f"{m.name}: no measurable cost, only noted")
            continue
        for t in m.times:
            f.personal_movement.append(Window(t, m.cost))
        notes.append(f"{m.name}: {m.cost:g}s of movement at " + ", ".join(f"{int(t // 60)}:{int(t % 60):02d}"
                                                                         for t in m.times))
    return f, notes


def boss_mechanic_names(con: sqlite3.Connection, encounter_id: int, difficulty: int,
                        names: dict[int, str]) -> set[str]:
    """Lowercase names of the boss's own abilities: Encounter Journal sections + abilities cast by enemies."""
    from paf.mechanics import encounter_sections, walk

    out = {s.title.lower() for _, s in walk(encounter_sections(encounter_id))}
    out |= {(names.get(r[0]) or "").lower() for r in con.execute(
        "SELECT DISTINCT e.ability_id FROM enemy_cast e JOIN fight f USING(report, fight_id) "
        "WHERE f.encounter_id=? AND f.difficulty=?", (encounter_id, difficulty))}
    out.discard("")
    return out


def load_mechanics(con: sqlite3.Connection, encounter_id: int, difficulty: int, spec: str) -> list[Mechanic]:
    """Assignable boss mechanics of a boss (needs `paf mechanics BOSS --corpus` data)."""
    from paf.gamedata import spell_names

    names = {**spell_names(), **dict(con.execute("SELECT id, name FROM ability").fetchall())}
    keep = boss_mechanic_names(con, encounter_id, difficulty, names)
    return [m for m in mechanic_timings(con, encounter_id, difficulty, spec, names, keep)
            if m.kind == "interrupt" or m.players_per_kill <= 12]


def assigns_template(mechanics: list[Mechanic], spec: str) -> str:
    lines = ["", f"# Boss mechanics you may be assigned to (uncomment yours). Cost measured on {spec} players:"]
    for m in mechanics:
        when = ", ".join(f"{int(t // 60)}:{int(t % 60):02d}" for t in m.times[:8])
        what = "kick" if m.kind == "interrupt" else f"{m.players_per_kill:.0f} players per kill"
        cost = f"{m.cost:g}s moving each time" if m.samples >= MIN_SAMPLES else f"~{m.cost:g}s (few samples)"
        lines.append(f"# assign {m.name:<28} # {what}; {cost}; at {when}")
    return "\n".join(lines) + "\n"
