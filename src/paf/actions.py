"""What to do on the boss, from what the top players of your spec actually do in their logs (not from the
Encounter Journal's descriptions): which adds they kill and how fast, which casts they interrupt, which
mechanics are assignments. Every line states the measured fact it comes from."""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass

from paf.corpus.analyze import kills_filter

RANDOM_SHARE = 1 / 20  # one player of your spec in a 20-player raid
KICK_SHARE = 0.3  # your spec handles it in at least this share of the kills: it is part of your job
ASSIGN_PLAYERS = 4  # at most this many players hit per kill: an assignment, not raid damage


@dataclass
class Action:
    kind: str  # kill | ignore | interrupt | assignment | mechanic
    name: str
    text: str


def _adds(con: sqlite3.Connection, encounter_id: int, difficulty: int, skip: set[str]) -> list[dict]:
    where, params = kills_filter(encounter_id, difficulty)
    kills = con.execute(f"SELECT COUNT(*) FROM fight f WHERE {where}", params).fetchone()[0] or 1
    per: dict[str, dict] = defaultdict(lambda: {"n": 0, "died": 0, "life": [], "kills": set()})
    for rep, fid, name, t0, t1, died in con.execute(
            f"SELECT a.report, a.fight_id, n.name, a.t_spawn, a.t_death, a.died FROM add_instance a JOIN npc n "
            f"USING(game_id) JOIN fight f USING(report, fight_id) WHERE {where} AND n.is_boss=0", params):
        if name in skip:
            continue
        p = per[name]
        p["n"] += 1
        p["died"] += died
        p["kills"].add((rep, fid))
        if t0 is not None and t1 is not None and t1 > t0:
            p["life"].append(t1 - t0)
    damage = dict(con.execute(
        f"SELECT d.target, SUM(d.amount) FROM damage_by_target d JOIN fight f USING(report, fight_id) "
        f"WHERE {where} GROUP BY d.target", params).fetchall())
    total = sum(v or 0 for v in damage.values()) or 1
    out = []
    for name, p in per.items():
        if len(p["kills"]) < max(3, kills * 0.3) or not p["life"]:
            continue
        out.append({"name": name, "per_kill": p["n"] / len(p["kills"]), "died": p["died"] / p["n"],
                    "life": st.median(p["life"]), "share": (damage.get(name) or 0) / total})
    return sorted(out, key=lambda a: -a["share"])


def actions(con: sqlite3.Connection, encounter_id: int, difficulty: int, spec: str, mechanics: list,
            focus: dict[str, float] | None = None, skip: set[str] | None = None) -> list[Action]:
    """focus: add name -> share of your spec's damage on it while it is up (paf.raidneed);
    skip: units that are not adds (the boss's own units, damage-amp windows)."""
    who = f"top {spec} players"
    out: list[Action] = []
    for a in _adds(con, encounter_id, difficulty, skip or set()):
        many = f"~{a['per_kill']:.0f} per kill" if a["per_kill"] >= 1.5 else "once per kill"
        if a["died"] >= 0.8 and a["share"] >= 0.01:
            f = (focus or {}).get(a["name"])
            extra = f"; {who} put {f:.0%} of their damage on them while they are up" if f else ""
            out.append(Action("kill", a["name"], f"Kill the {a['name']} ({many}): the top raids kill them in "
                                                 f"~{a['life']:.0f} s{extra}."))
        elif a["died"] <= 0.1 and a["share"] < 0.01 and a["life"] > 60:
            out.append(Action("ignore", a["name"], f"{a['name']}: the top raids do not kill it with damage (it "
                                                   f"stays ~{a['life'] / 60:.0f} min); do not spend your damage on "
                                                   f"it unless your raid's strategy says so."))
    for m in mechanics:
        if m.kind == "interrupt":
            if m.spec_share >= KICK_SHARE:
                out.append(Action("interrupt", m.name, f"Interrupt {m.name}: {who} kick it in {m.spec_share:.0%} "
                                                       f"of the kills (~{m.per_kill:.0f} kicks per kill), far more "
                                                       f"than one player in twenty would: it is part of your job."))
            elif m.per_kill >= 2:
                out.append(Action("interrupt", m.name, f"{m.name} is interrupted ~{m.per_kill:.0f} times per kill, "
                                                       f"mostly by other classes ({who}: {m.spec_share:.0%} of "
                                                       f"the kills); kick it if your raid asks."))
        elif m.players_per_kill <= ASSIGN_PLAYERS:
            cost = f", ~{m.cost:g} s of movement when it is you" if m.cost else ""
            n = round(m.players_per_kill)
            out.append(Action("assignment", m.name, f"{m.name}: {n} player{'s' if n > 1 else ''} per kill, an "
                                                    f"assignment{cost}. Tick it on the boss page if it is yours."))
        elif m.spec_share >= max(KICK_SHARE, 3 * RANDOM_SHARE):
            out.append(Action("mechanic", m.name, f"{m.name}: hits ~{m.players_per_kill:.0f} players per kill; "
                                                  f"{who} take it in {m.spec_share:.0%} of the kills: expect it."))
    order = {"kill": 0, "interrupt": 1, "assignment": 2, "mechanic": 3, "ignore": 4}
    seen: set[str] = set()
    unique = []
    for a in sorted(out, key=lambda a: order[a.kind]):  # one line per mechanic (several spell ids share a name)
        if (a.kind in ("kill", "ignore") and ("unit", a.name) in seen) or (a.kind not in ("kill", "ignore")
                                                                          and ("ability", a.name) in seen):
            continue
        seen.add(("unit" if a.kind in ("kill", "ignore") else "ability", a.name))
        unique.append(a)
    return unique
