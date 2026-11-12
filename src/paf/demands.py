"""What the fight demands, found by itself (the owner, 2026-11-12: "a prep is 20% useful, the rest is noise"; what
decides a spec is the fight's demands, and the game data says most of it before any log).

From the game data (paf.encmodel), what each demand is:
- a shield to break: an absorb an enemy puts on itself, within the cast it comes under when it has one (Coiled Altar:
  Veil of Twilight on Malacrass, 4902 units mythic, to break within Eternal Nightfall's 17 s cast);
- a unit out of reach: an enemy at -90% damage taken or less while something holds (Tether of Awakening, Spirit
  Shield): what to kill first;
- a damage amp: an enemy taking more damage for a while (Ghastly Regeneration, +100% for 35 s);
- adds a spell brings (Spawn of Vexhul under Venomous Emergence): a burst.
From the logs, only what the game data cannot say: when each happens (the casts of the top kills, in stage time), how
fast the top raids break a shield and its real size, how long the adds live, Bloodlust.

Each spec's damage in each window comes from the specs' sims (simc's per-second damage of the player), all in the top
players' gear at the same item level: no sim of its own."""
from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

KILLS = 12  # kills read per boss for its shields (about 2 quota points each)
CAST_WINDOW = 5.0  # seconds: a cast this long at least is the time to break the shield it brings (Nightfall: 17)
BURST_ADDS = 45.0  # seconds: an add wave that lives this long at most is a burst (a longer one is a second target)

SCHEMA = """
CREATE TABLE IF NOT EXISTS enemy_shield(      -- shields on enemies (paf.encmodel: absorbs on their caster)
  report TEXT, fight_id INT, ability_id INT, t_start REAL, t_end REAL, absorb REAL);
CREATE TABLE IF NOT EXISTS shield_status(report TEXT, fight_id INT, PRIMARY KEY(report, fight_id));
"""

SHIELD_QUERY = """query($code:String!,$f:[Int]!,$s:Float!,$e:Float!,$x:String!){ reportData { report(code:$code) {
  events(fightIDs:$f, startTime:$s, endTime:$e, dataType:Buffs, hostilityType:Enemies, filterExpression:$x,
         limit:2000){ data } } } }"""


@dataclass
class Window:
    kind: str  # "shield" | "immune" | "amp" | "adds"
    label: str  # "Veil of Twilight", "Add waves", "x2 amp"
    spans: list[tuple[float, float]] = field(default_factory=list)  # (start, end) in the fight's time; [] unplaced
    detail: str = ""  # the game data's then the logs' facts, one sentence
    spell: int = 0
    unit: str = ""  # who carries it ("Hex Lord Malacrass")
    severity: int | None = None  # Blizzard's warning severity of the ability behind it


def from_model(m) -> list[Window]:
    """The demands the game data shows (paf.encmodel.Model), unplaced: one per spell."""
    from paf.encmodel import journal_creatures

    units = journal_creatures(m.encounter_id)
    out: dict[int, Window] = {}
    for a in m.abilities:
        if a.spell in out:  # the same spell in a later stage: its unit when the first one did not say it
            out[a.spell].unit = out[a.spell].unit or a.creature
            continue
        parent = m.ability(a.parent) if a.parent else None
        sev = a.severity if a.severity is not None else parent.severity if parent else None
        if shields := a.has("shield", on_caster=True):
            within = parent.cast if parent and parent.cast >= CAST_WINDOW else 0.0
            size = f", {shields[0].size:g} units ({m.difficulty})" if shields[0].size else ""
            out[a.spell] = Window(
                "shield", a.name, detail=(f"to break within {parent.name}'s {within:g} s cast" if within else
                                          "a shield to break") + size,
                spell=a.spell, unit=a.creature, severity=sev)
        elif reach := [x for x in a.has("damage_taken", on_caster=True) if x.size <= -90]:
            out[a.spell] = Window("immune", a.name, detail=f"{reach[0].size:g}% damage taken",
                                  spell=a.spell, unit=a.creature or m.boss, severity=sev)  # none said: the boss
        elif amp := [x for x in a.has("damage_taken", on_caster=True) if x.size > 0]:
            out[a.spell] = Window("amp", a.name, detail=f"+{amp[0].size:g}% damage taken"
                                  + (f" for {a.duration:g} s" if a.duration else ""), spell=a.spell,
                                  unit=a.creature, severity=sev)
    for c in m.creatures:
        if c.summoner and c.name in units and c.name not in {w.label for w in out.values()}:
            src = m.ability(c.summoner)
            out[-len(out) - 1] = Window("adds", c.name, detail=f"brought by {src.name}" if src else "",
                                        severity=src.severity if src else None)
    return list(out.values())


def shield_events(events: list[dict], start: float) -> list[tuple[int, float, float, float]]:
    """(ability, up, broken, absorb) of each shield in a kill's buff events (ms timestamps; up to the fight's start).
    A shield still up at the end of the kill is left out (it said nothing about breaking it)."""
    out, up = [], {}
    for ev in sorted(events, key=lambda x: x["timestamp"]):
        key = (ev.get("abilityGameID"), ev.get("targetID"), ev.get("targetInstance"))
        t = (ev["timestamp"] - start) / 1000
        if ev.get("type") in ("applybuff", "applydebuff"):
            up[key] = (t, float(ev.get("absorb") or 0))
        elif ev.get("type") in ("removebuff", "removedebuff") and key in up:
            t0, absorb = up.pop(key)
            out.append((int(key[0]), round(t0, 1), round(t, 1), absorb))
    return out


def fetch_shields(client, con: sqlite3.Connection, encounter_id: int, difficulty: int, spells: set[int],
                  kills: int = KILLS, log: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    """Each shield's up and broken times in the top kills (once per kill, kept in the corpus)."""
    from paf.corpus.analyze import kills_filter
    from paf.corpus.units import FIGHT_QUERY
    from paf.wcl import WCLDown, WCLError, WCLQuota

    if not spells:
        return 0
    con.executescript(SCHEMA)
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM shield_status a JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id FROM fight f LEFT JOIN shield_status a USING(report, fight_id) "
        f"WHERE {where} AND a.report IS NULL ORDER BY f.report LIMIT ?", (*params, max(0, kills - have))).fetchall()
    expr = f"ability.id in ({', '.join(str(i) for i in sorted(spells))})"
    for r in todo:
        try:
            fr = client.query(FIGHT_QUERY, {"code": r[0], "f": [r[1]]},
                              cache_ttl=0)["reportData"]["report"]["fights"][0]
            evs = client.query(SHIELD_QUERY, {"code": r[0], "f": [r[1]], "s": fr["startTime"], "e": fr["endTime"],
                                              "x": expr}, cache_ttl=0)["reportData"]["report"]["events"]["data"]
        except (WCLError, KeyError, TypeError, IndexError, OSError) as ex:
            if isinstance(ex, (WCLDown, WCLQuota)):
                log(f"  shields stopped: {str(ex)[:100]}; the rest is read on a later prep")
                break
            log(f"  shields skipped: {str(ex)[:100]}")
            continue
        con.executemany("INSERT INTO enemy_shield VALUES(?,?,?,?,?,?)",
                        [(r[0], r[1], *x) for x in shield_events(evs or [], fr["startTime"])])
        con.execute("INSERT OR REPLACE INTO shield_status VALUES(?,?)", (r[0], r[1]))
        con.commit()
    return len(todo)


TOGETHER = 8.0  # seconds: shields going up this close in a kill are one wave (a shield on each of 6 Restless Amani)


def _together(rows) -> list[tuple]:
    """Shield rows (report, fight, up, took, absorb) of one kill merged into waves: up at the first, broken at the
    last, each one's absorb (its median)."""
    out: list[list] = []
    for rep, fid, t0, took, absorb in sorted(rows, key=lambda r: (r[0], r[1], r[2])):
        cur = out[-1] if out else None
        if cur and (cur[0], cur[1]) == (rep, fid) and t0 - cur[2] <= TOGETHER:
            cur[3] = max(cur[3], t0 + took - cur[2])
            cur[5].append(absorb)
        else:
            out.append([rep, fid, t0, took, absorb, [absorb]])
    return [(r[0], r[1], r[2], r[3], st.median(r[5])) for r in out]


def _occurrences(rows, read: int, clock) -> list[list[tuple]]:
    """Rows (report, fight, t, *rest) of a kind of event, grouped by their rank in their kill (the k-th of each kill),
    in stage time; a rank half the kills never reach is left out."""
    per: dict[int, list[tuple]] = defaultdict(list)
    nth: dict[tuple, int] = defaultdict(int)
    for rep, fid, t, *rest in rows:
        k = nth[(rep, fid)]
        nth[(rep, fid)] += 1
        at = clock.at((rep, fid), t) if clock else t
        if at is not None:
            per[k].append((at, *rest))
    return [per[k] for k in sorted(per) if not read or len(per[k]) >= read / 2]


def place(windows: list[Window], m, con: sqlite3.Connection, encounter_id: int, difficulty: int, clock=None,
          fight=None) -> list[Window]:
    """The demands in the fight's time, from the logs: a shield from the top kills' shields (else from the casts of
    the spell it comes under), a unit out of reach or an amp from the casts of its spell or its parent's, the add
    waves and the amps of the rebuilt fight. A demand the logs never show stays, unplaced (said, not drawn)."""
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    kills = con.execute(f"SELECT COUNT(*) FROM fight f WHERE {where}", params).fetchone()[0]
    try:
        con.executescript(SCHEMA)
        read = con.execute(f"SELECT COUNT(*) FROM shield_status a JOIN fight f USING(report, fight_id) WHERE {where}",
                           params).fetchone()[0]
    except sqlite3.Error:
        read = 0

    def casts(spell: int) -> list[list[tuple]]:
        rows = con.execute(f"SELECT e.report, e.fight_id, e.t FROM enemy_cast e JOIN fight f USING(report, fight_id) "
                           f"WHERE {where} AND e.ability_id = ? AND e.type IN ('begincast', 'cast') "
                           f"ORDER BY e.report, e.fight_id, e.t", (*params, spell)).fetchall()
        firsts, last = [], {}
        for rep, fid, t in rows:  # a begincast and its cast: one press
            if last.get((rep, fid)) is None or t - last[(rep, fid)] > 3:
                firsts.append((rep, fid, t))
            last[(rep, fid)] = t
        return _occurrences(firsts, kills, clock)
    out = []
    for w in windows:
        a = m.ability(w.spell) if w.spell else None
        parent = m.ability(a.parent) if a and a.parent else None
        if w.kind == "shield":
            rows = con.execute(
                f"SELECT s.report, s.fight_id, s.t_start, s.t_end - s.t_start, s.absorb FROM enemy_shield s JOIN "
                f"fight f USING(report, fight_id) WHERE {where} AND s.ability_id = ? ORDER BY s.report, s.fight_id, "
                f"s.t_start", (*params, w.spell)).fetchall() if read else []
            occ = _occurrences(_together(rows), read, clock)
            if occ:
                took = [x[1] for o in occ for x in o]
                size = [x[2] for o in occ for x in o if x[2]]
                w.spans = [(round(st.median(x[0] for x in o), 1), round(st.median(x[0] + x[1] for x in o), 1))
                           for o in occ]
                w.detail += (f"; the top raids break it in {st.median(took):.0f} s"
                             + (f", {st.median(size) / 1e6:.1f} M" if size else ""))
            elif parent and parent.cast >= CAST_WINDOW and (occ := casts(parent.spell)):
                w.spans = [(round(st.median(x[0] for x in o), 1), round(st.median(x[0] for x in o) + parent.cast, 1))
                           for o in occ]
        elif w.kind in ("immune", "amp") and a is not None:
            occ = casts(a.spell) or (casts(parent.spell) if parent else [])
            if occ and a.duration:
                w.spans = [(round(st.median(x[0] for x in o), 1), round(st.median(x[0] for x in o) + a.duration, 1))
                           for o in occ]
        out.append(w)
    if fight is not None:  # out of reach while its unit lives: that unit's waves in the rebuilt fight; the boss
        for w in out:          # itself: its immune phases there
            if w.kind == "immune" and not w.spans and w.unit:
                if _name(w.unit) == _name(m.boss or ""):
                    w.spans = [(i.start, i.start + i.duration) for i in getattr(fight, "invulnerable", []) or []]
                else:
                    w.spans = [(x.time, x.time + x.lifetime) for x in fight.add_waves
                               if _name(x.name) == _name(w.unit) and x.lifetime > 0]
                    w.detail += f", while {w.unit} lives" if w.spans else ""
    if fight is not None:  # the rebuilt fight's adds and amps place the game data's by name, or come in addition
        for fw in fight_windows(fight):
            same = next((w for w in out if _name(w.label) == _name(fw.label) and w.kind in (fw.kind, "adds")), None)
            if same is None:
                out.append(fw)
            else:  # measured on the unit itself, in the sims' own time: it wins over a cast's
                same.spans = fw.spans
                same.detail = "; ".join(x for x in (same.detail, fw.detail) if x)
    end = getattr(fight, "duration", None) if fight is not None else None
    if end:  # a window ends with the fight (an add wave that outlives the kill in the template)
        for w in out:
            w.spans = [(a, min(b, end)) for a, b in w.spans if a < end]
    return out


def _name(label: str) -> str:
    """'Ghastly Regeneration (boss aura)' -> 'ghastly regeneration': a unit's or an aura's name, the notes left."""
    import re

    return re.sub(r"\s*\([^)]*\)", "", label).strip().lower()


def fight_windows(fight) -> list[Window]:
    """The rebuilt fight's short add waves (one window per kind of add) and its damage amps."""
    out = []
    by: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for w in fight.add_waves:
        if 0 < w.lifetime <= BURST_ADDS:
            by[_name(w.name) and w.name.split(" (")[0] or "Adds"].append((w.time, w.time + w.lifetime))
    for name, waves in by.items():
        life = st.median(b - a for a, b in waves)
        out.append(Window("adds", name, waves, f"{len(waves)} waves that live ~{life:.0f} s in the top kills"))
    lust = getattr(fight, "lust_time", None)
    for v in getattr(fight, "vulnerable", []) or []:
        a, b = v.start, v.start + v.duration
        bl = lust is not None and a - 10 <= lust <= b
        out.append(Window("amp", (v.name or "").split(" (")[0] or f"x{v.multiplier:g} amp", [(a, b)],
                          f"x{v.multiplier:g} damage taken" + (", Bloodlust in it" if bl else "")))
    return out


def window_damage(timeline: list[float], spans: list[tuple[float, float]]) -> float:
    """A per-second damage timeline summed over the spans."""
    return sum(sum(timeline[max(0, int(a)):max(0, int(b))]) for a, b in spans)


def compare(windows: list[Window], timelines: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """spec -> window label -> damage in it ("all": the whole fight), placed windows only."""
    return {spec: {"all": sum(tl), **{w.label: window_damage(tl, w.spans) for w in windows if w.spans}}
            for spec, tl in timelines.items() if tl}
