"""What the fight demands, found by itself (the owner, 2026-11-12: "a prep is 20% useful, the rest is noise"; what
decides a spec is the fight's demands): the moments a raid must put out damage fast, and which spec of yours does.

- A DPS check: a shield on an enemy that must be broken (Coiled Altar mythic: Malacrass's Veil of Twilight, 34.8 M,
  broken in 12 to 17 s by a top raid, or Eternal Nightfall wipes). Found in the Encounter Journal (a spell whose game
  description absorbs damage), read in the top kills (when it goes up, when it breaks), placed in stage time.
- A burst on adds: a short add wave (Twin Fangs mythic: 3 adds that live ~11 s in the top kills).
- A damage amp, with Bloodlust when it falls in it (the boss takes x2: a spec with an execute there).

Each spec's damage in each window comes from the specs' sims (simc's per-second damage of the player), all in the top
players' gear at the same item level: no sim of its own."""
from __future__ import annotations

import re
import sqlite3
import statistics as st
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

SHIELD_TEXT = re.compile(r"absorb\w*\s+\$s\d+\s+damage", re.I)  # "absorbing $s1 damage" (not "... healing")
KILLS = 12  # kills read per boss for its shields (about 1.5 quota points each)
BURST_ADDS = 45.0  # seconds: an add wave that lives this long at most is a burst (a longer one is a second target)

SCHEMA = """
CREATE TABLE IF NOT EXISTS enemy_shield(      -- shields on enemies (journal spells that absorb damage), paf.demands
  report TEXT, fight_id INT, ability_id INT, t_start REAL, t_end REAL, absorb REAL);
CREATE TABLE IF NOT EXISTS shield_status(report TEXT, fight_id INT, PRIMARY KEY(report, fight_id));
"""

SHIELD_QUERY = """query($code:String!,$f:[Int]!,$s:Float!,$e:Float!,$x:String!){ reportData { report(code:$code) {
  events(fightIDs:$f, startTime:$s, endTime:$e, dataType:Buffs, hostilityType:Enemies, filterExpression:$x,
         limit:2000){ data } } } }"""


@dataclass
class Window:
    kind: str  # "shield" | "adds" | "amp"
    label: str  # "Veil of Twilight", "Add waves", "x2 amp"
    spans: list[tuple[float, float]]  # (start, end) in the fight's time, every occurrence
    detail: str = ""  # "broken in 13 s by the top raids", "Bloodlust in it"
    spell: int = 0


@dataclass
class Demands:
    windows: list[Window] = field(default_factory=list)
    damage: dict[str, dict[str, float]] = field(default_factory=dict)  # spec -> window label -> damage (and "all")


def shield_spells(sections) -> dict[int, str]:
    """The journal's spells whose game description absorbs damage: {spell id: name}."""
    from paf.gamedata import table_rows

    ids: dict[int, str] = {}

    def walk(xs):
        for s in xs or []:
            if s.spell_id:
                ids.setdefault(int(s.spell_id), s.title)
            walk(s.children)
    walk(sections)
    try:
        text = {int(r["ID"]): r.get("Description_lang") or "" for r in table_rows("Spell")
                if r.get("ID", "").isdigit() and int(r["ID"]) in ids}
    except Exception:  # noqa: BLE001 - offline: no shield known
        return {}
    return {i: n for i, n in ids.items() if SHIELD_TEXT.search(text.get(i, ""))}


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


def fetch_shields(client, con: sqlite3.Connection, encounter_id: int, difficulty: int, spells: dict[int, str],
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


def shield_windows(con: sqlite3.Connection, encounter_id: int, difficulty: int, spells: dict[int, str],
                   clock=None) -> list[Window]:
    """Each shield's typical occurrences: the k-th one of a kill at its median start (stage time when a clock is
    given), lasting the median time the top raids took to break it. Seen in half the kills read at least."""
    from paf.corpus.analyze import kills_filter

    try:
        con.executescript(SCHEMA)
    except sqlite3.Error:
        return []
    where, params = kills_filter(encounter_id, difficulty)
    read = con.execute(f"SELECT COUNT(*) FROM shield_status a JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    rows = con.execute(f"SELECT s.report, s.fight_id, s.ability_id, s.t_start, s.t_end, s.absorb FROM enemy_shield s "
                       f"JOIN fight f USING(report, fight_id) WHERE {where} ORDER BY s.t_start", params).fetchall()
    per: dict[int, dict[int, list[tuple[float, float, float]]]] = defaultdict(lambda: defaultdict(list))
    nth: dict[tuple, int] = defaultdict(int)
    for rep, fid, aid, t0, t1, absorb in rows:
        k = nth[(rep, fid, aid)]
        nth[(rep, fid, aid)] += 1
        at = clock.at((rep, fid), t0) if clock else t0
        if at is not None:
            per[aid][k].append((at, t1 - t0, absorb))
    out = []
    for aid, occ in per.items():
        spans, took, absorbs = [], [], []
        for k in sorted(occ):
            xs = occ[k]
            if read and len(xs) < read / 2:  # an occurrence most kills never reach
                continue
            start, dur = st.median(x[0] for x in xs), st.median(x[1] for x in xs)
            spans.append((round(start, 1), round(start + dur, 1)))
            took += [x[1] for x in xs]
            absorbs += [x[2] for x in xs if x[2]]
        if spans:
            size = f", {st.median(absorbs) / 1e6:.1f} M absorbed" if absorbs else ""
            out.append(Window("shield", spells.get(aid, f"Shield {aid}"), spans,
                              f"broken in {st.median(took):.0f} s by the top raids{size}", aid))
    return out


def fight_windows(fight) -> list[Window]:
    """The short add waves (all of them, one window) and each damage amp, from the rebuilt fight."""
    out = []
    waves = [(w.time, w.time + w.lifetime) for w in fight.add_waves if 0 < w.lifetime <= BURST_ADDS]
    if waves:
        life = st.median(b - a for a, b in waves)
        out.append(Window("adds", "Add waves", waves, f"{len(waves)} waves that live ~{life:.0f} s"))
    lust = getattr(fight, "lust_time", None)
    for v in getattr(fight, "vulnerable", []) or []:
        a, b = v.start, v.start + v.duration
        bl = lust is not None and a - 10 <= lust <= b
        out.append(Window("amp", f"x{v.multiplier:g} amp", [(a, b)], "Bloodlust in it" if bl else "", 0))
    return out


def window_damage(timeline: list[float], spans: list[tuple[float, float]]) -> float:
    """A per-second damage timeline summed over the spans."""
    return sum(sum(timeline[max(0, int(a)):max(0, int(b))]) for a, b in spans)


def compare(windows: list[Window], timelines: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """spec -> window label -> damage in it ("all": the whole fight)."""
    return {spec: {"all": sum(tl), **{w.label: window_damage(tl, w.spans) for w in windows}}
            for spec, tl in timelines.items() if tl}
