"""Who handles each boss mechanic in the corpus: interrupts, and debuffs of journal abilities on players."""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from paf.corpus.analyze import kills_filter
from paf.wcl import WCLClient, WCLError

MECH_QUERY = """
query($code:String!, $f:[Int]!, $filter:String) { reportData { report(code:$code) {
  fights(fightIDs:$f) { startTime endTime }
  kicks: events(fightIDs:$f, dataType:Interrupts, hostilityType:Friendlies, limit:10000) { data nextPageTimestamp }
  debuffs: events(fightIDs:$f, dataType:Debuffs, hostilityType:Friendlies, filterExpression:$filter,
                  limit:10000) { data nextPageTimestamp }
} } }
"""

ASSIGNED_MAX = 3  # a mechanic that hits at most this many players per kill (median) is assigned


def debuff_filter(spell_ids: list[int]) -> str:
    return f"type = 'applydebuff' and ability.id in ({', '.join(str(s) for s in sorted(set(spell_ids)))})"


def fetch_mechanics(client: WCLClient, con: sqlite3.Connection, encounter_id: int, difficulty: int,
                    spell_ids: list[int], log: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    where, params = kills_filter(encounter_id, difficulty)
    todo = con.execute(
        f"SELECT f.report, f.fight_id FROM fight f LEFT JOIN mech_status m USING(report, fight_id) "
        f"WHERE {where} AND m.report IS NULL", params).fetchall()
    flt = debuff_filter(spell_ids) if spell_ids else "type = 'applydebuff'"
    for i, r in enumerate(todo, 1):
        try:
            data = client.query(MECH_QUERY, {"code": r["report"], "f": [r["fight_id"]], "filter": flt})
            rep = data["reportData"]["report"]
            start = rep["fights"][0]["startTime"]
            end = rep["fights"][0]["endTime"]
            kicks = (rep.get("kicks") or {}).get("data") or []
            debuffs = (rep.get("debuffs") or {}).get("data") or []
            nxt = (rep.get("debuffs") or {}).get("nextPageTimestamp")
            if nxt and nxt < end:
                debuffs += list(client.events(r["report"], r["fight_id"], nxt, end, data_type="Debuffs",
                                              hostility="Friendlies", filter_expression=flt, cache=False))
        except (WCLError, KeyError, TypeError, IndexError, OSError) as e:
            log(f"  [{i}/{len(todo)}] skipped: {str(e)[:100]}")
            continue
        rows = [(r["report"], r["fight_id"], "interrupt", ev.get("extraAbilityGameID") or ev.get("abilityGameID"),
                 ev.get("sourceID"), round((ev["timestamp"] - start) / 1000, 3)) for ev in kicks]
        rows += [(r["report"], r["fight_id"], "debuff", ev.get("abilityGameID"), ev.get("targetID"),
                  round((ev["timestamp"] - start) / 1000, 3)) for ev in debuffs]
        con.execute("DELETE FROM mech_event WHERE report=? AND fight_id=?", (r["report"], r["fight_id"]))
        con.executemany("INSERT INTO mech_event VALUES(?,?,?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO mech_status VALUES(?,?,?)",
                    (r["report"], r["fight_id"], datetime.now(UTC).isoformat(timespec="seconds")))
        con.commit()
        if i % 20 == 0 or i == len(todo):
            log(f"  [{i}/{len(todo)}] mechanics fetched")
    return len(todo)


@dataclass
class MechanicStats:
    ability_id: int
    name: str
    kind: str  # debuff | interrupt
    kills: int  # kills where it happens
    players_per_kill: float  # median distinct players affected (debuff) / kicking (interrupt)
    events_per_kill: float
    specs: list[tuple[str, float]] = field(default_factory=list)  # spec -> share of the affected players
    assigned: bool = False
    my_spec_rate: float = 0.0  # share of kills where a player of the analyzed spec handles it


def mechanic_stats(con: sqlite3.Connection, encounter_id: int, difficulty: int, spec: str,
                   names: dict[int, str]) -> list[MechanicStats]:
    where, params = kills_filter(encounter_id, difficulty)
    kills = [tuple(r) for r in con.execute(
        f"SELECT f.report, f.fight_id FROM fight f JOIN mech_status m USING(report, fight_id) WHERE {where}", params)]
    if not kills:
        return []
    specs = {(r["report"], r["fight_id"], r["actor_id"]): f"{r['spec']} {r['class']}" for r in con.execute(
        f"SELECT p.* FROM player p JOIN fight f USING(report, fight_id) WHERE {where}", params)}
    per: dict[tuple[str, int], dict[tuple[str, int], list]] = defaultdict(lambda: defaultdict(list))
    for r in con.execute(
            f"SELECT e.* FROM mech_event e JOIN fight f USING(report, fight_id) WHERE {where}", params):
        per[(r["kind"], r["ability_id"])][(r["report"], r["fight_id"])].append(r["actor_id"])
    out = []
    for (kind, aid), by_kill in per.items():
        if aid is None:
            continue
        players = [len(set(v)) for v in by_kill.values()]
        events = [len(v) for v in by_kill.values()]
        spec_count: Counter[str] = Counter()
        mine = 0
        for (rep, fid), actors in by_kill.items():
            kill_specs = {specs.get((rep, fid, a), "?") for a in set(actors)}
            spec_count.update(specs.get((rep, fid, a), "?") for a in set(actors))
            if any(s.startswith(spec) for s in kill_specs):
                mine += 1
        total = sum(spec_count.values()) or 1
        med_players = st.median(players)
        out.append(MechanicStats(
            aid, names.get(aid, f"spell {aid}"), kind, len(by_kill), med_players, st.median(events),
            [(s, n / total) for s, n in spec_count.most_common(5)],
            assigned=kind == "interrupt" or med_players <= ASSIGNED_MAX,
            my_spec_rate=mine / len(by_kill)))
    out.sort(key=lambda m: (m.kind, -m.kills, m.players_per_kill))
    return [m for m in out if m.kills >= max(3, len(kills) * 0.2)]
