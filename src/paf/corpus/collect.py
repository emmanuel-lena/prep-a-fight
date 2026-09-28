"""Collect a per-boss corpus of kills from Warcraft Logs.

Pipeline (costs measured on Ula'tek heroic, see docs/research/wcl-corpus.md):
1. enumerate kills of a spec with ``characterRankings(includeCombatantInfo)``: 100 rows/page, ~1 point;
2. per kill, one aliased request (fight, phases, actors, damage table, enemy deaths / first debuffs /
   casts): ~6 points; then the ranked player's casts (with positions) and buffs: ~2 points.
Progress is stored in SQLite so an interrupted collection resumes where it stopped.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from paf.corpus.db import clear_fight_rows
from paf.encounters import Encounter
from paf.wcl import WCLClient, WCLError

RANKINGS_QUERY = """
query($id:Int!, $diff:Int!, $page:Int, $bracket:Int, $region:String, $cls:String!, $spec:String!) {
  worldData { encounter(id:$id) {
    characterRankings(className:$cls, specName:$spec, difficulty:$diff, metric:dps, page:$page,
                      bracket:$bracket, serverRegion:$region, includeCombatantInfo:true)
  } }
}
"""

KILL_QUERY = """
query($code:String!, $f:[Int]!) { reportData { report(code:$code) {
  archiveStatus { isAccessible }
  fights(fightIDs:$f) { id name encounterID kill difficulty size startTime endTime averageItemLevel
    phaseTransitions { id startTime } enemyNPCs { id gameID instanceCount petOwner } }
  phases { encounterID phases { id name isIntermission } }
  masterData { actors { id name gameID type subType petOwner } abilities { gameID name } }
  dmg: table(fightIDs:$f, dataType:DamageDone)
  deaths: events(fightIDs:$f, dataType:Deaths, hostilityType:Enemies, limit:10000) {
    data nextPageTimestamp }
  debuffs: events(fightIDs:$f, dataType:Debuffs, hostilityType:Enemies,
                  filterExpression:"type='applydebuff'", limit:10000) { data nextPageTimestamp }
  ecasts: events(fightIDs:$f, dataType:Casts, hostilityType:Enemies, limit:10000) {
    data nextPageTimestamp }
} } }
"""

PLAYER_QUERY = """
query($code:String!, $f:[Int]!, $a:Int!) { reportData { report(code:$code) {
  pcasts: events(fightIDs:$f, dataType:Casts, sourceID:$a, includeResources:true, limit:10000) {
    data nextPageTimestamp }
  pbuffs: events(fightIDs:$f, dataType:Buffs, targetID:$a, limit:10000) { data nextPageTimestamp }
} } }
"""

CLASSES = {"DeathKnight", "DemonHunter", "Druid", "Evoker", "Hunter", "Mage", "Monk", "Paladin",
           "Priest", "Rogue", "Shaman", "Warlock", "Warrior"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rows(scalar: Any) -> dict[str, Any]:
    """characterRankings / table are untyped JSON scalars; tolerate a missing wrapper."""
    if isinstance(scalar, str):
        scalar = json.loads(scalar)
    return scalar or {}


# --- 1. enumerate kills ------------------------------------------------------------------------


@dataclass
class RankedKill:
    report: str
    fight_id: int
    page: int
    pos: int
    row: dict[str, Any]


def enumerate_kills(client: WCLClient, enc: Encounter, difficulty: int, cls: str, spec: str, *,
                    count: int, brackets: Iterable[int | None] = (None,),
                    pages: Iterable[int] | None = None, region: str = "",
                    log: Callable[[str], None] = print) -> list[RankedKill]:
    """Ranked kills of a spec, unique by (report, fight). With several brackets, rows are merged
    and evenly subsampled so the cohort keeps its spread of skill levels."""
    per_bracket: list[list[RankedKill]] = []
    for br in brackets:
        got: list[RankedKill] = []
        want_pages = list(pages) if pages else list(range(1, (count + 99) // 100 + 1))
        for page in want_pages:
            v: dict[str, Any] = {"id": enc.id, "diff": difficulty, "page": page, "cls": cls, "spec": spec}
            if br is not None:
                v["bracket"] = br
            if region:
                v["region"] = region
            data = client.query(RANKINGS_QUERY, v, cache_ttl=6 * 3600)
            cr = _rows(data["worldData"]["encounter"]["characterRankings"])
            if cr.get("error"):
                log(f"  rankings page {page}: {cr['error']}")
                break
            rows = cr.get("rankings") or []
            for i, r in enumerate(rows):
                rep = r.get("report") or {}
                if rep.get("code") and rep.get("fightID") is not None:
                    got.append(RankedKill(rep["code"], int(rep["fightID"]), page, (page - 1) * 100 + i + 1, r))
            if not cr.get("hasMorePages"):
                break
        per_bracket.append(got)

    seen: set[tuple[str, int]] = set()
    merged: list[RankedKill] = []
    for group in per_bracket:
        for k in group:
            if (k.report, k.fight_id) not in seen:
                seen.add((k.report, k.fight_id))
                merged.append(k)
    if len(per_bracket) > 1 and len(merged) > count:
        step = len(merged) / count
        merged = [merged[int(i * step)] for i in range(count)]
    return merged[:count]


def store_ranked(con: sqlite3.Connection, enc: Encounter, difficulty: int, cohort: str,
                 kills: list[RankedKill]) -> int:
    new = 0
    for k in kills:
        r = k.row
        cur = con.execute(
            "INSERT OR IGNORE INTO fight(report, fight_id, encounter_id, difficulty, size, duration_s,"
            " region, guild_id, cohort) VALUES(?,?,?,?,?,?,?,?,?)",
            (k.report, k.fight_id, enc.id, difficulty, r.get("size"), (r.get("duration") or 0) / 1000,
             (r.get("server") or {}).get("region"), (r.get("guild") or {}).get("id"), cohort))
        new += cur.rowcount
        pi = sum(b.get("applications", 0) for b in r.get("externalBuffs") or [] if b.get("id") == 10060)
        con.execute(
            "INSERT INTO ranked(report, fight_id, class, spec, rank_page, rank_pos, dps, ilvl,"
            " talents_json, gear_json, pi_count, name) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(report, fight_id) DO UPDATE SET rank_page=excluded.rank_page,"
            " rank_pos=excluded.rank_pos, dps=excluded.dps, ilvl=excluded.ilvl,"
            " talents_json=excluded.talents_json, gear_json=excluded.gear_json, pi_count=excluded.pi_count,"
            " name=CASE WHEN ranked.actor_id IS NULL THEN excluded.name ELSE NULL END",
            (k.report, k.fight_id, r.get("class"), r.get("spec"), k.page, k.pos, r.get("amount"),
             r.get("bracketData"), json.dumps(r.get("talents") or []), json.dumps(r.get("gear") or []),
             pi, r.get("name")))
    con.commit()
    return new


# --- 2. per-kill parsing (pure) -------------------------------------------------------------------


def _key(ev: dict[str, Any], side: str) -> tuple[int, int]:
    return int(ev.get(f"{side}ID", -1)), int(ev.get(f"{side}Instance", 1) or 1)


def parse_kill(rep: dict[str, Any], fight_id: int, ranked_name: str | None,
               ranked: tuple[str, str, float] | None = None) -> dict[str, Any]:
    """Turn the KILL_QUERY payload into rows. Returns a dict of lists + metadata.

    ranked = (class, spec, dps) identifies the ranked player when names are anonymized.
    """
    fights = rep.get("fights") or []
    if not fights:
        raise WCLError("fight not found in report")
    f = fights[0]
    start, end = f["startTime"], f["endTime"]

    def t(ts: float) -> float:
        return round((ts - start) / 1000, 3)

    actors = {a["id"]: a for a in (rep.get("masterData") or {}).get("actors") or []}
    boss_ids = {i for i, a in actors.items() if a.get("subType") == "Boss" and i >= 0}
    enemy_ids = {n["id"] for n in f.get("enemyNPCs") or [] if not n.get("petOwner")}
    # the main boss is the boss unit named like the fight; other boss units (e.g. a heart to burn)
    # are tracked like adds so their timing is known
    main_ids = {i for i in boss_ids if actors[i].get("name") == f.get("name")} or boss_ids
    add_ids = enemy_ids - main_ids

    out: dict[str, Any] = {
        "fight": {"duration_s": round((end - start) / 1000, 3), "kill": int(bool(f.get("kill"))),
                  "avg_ilvl": f.get("averageItemLevel"), "size": f.get("size"),
                  "difficulty": f.get("difficulty")},
        "npcs": [], "phases": [], "adds": [], "players": [], "damage": [], "enemy_casts": [],
        "abilities": [(a["gameID"], a["name"]) for a in (rep.get("masterData") or {}).get("abilities") or []],
        "ranked_actor": None,
    }
    for n in f.get("enemyNPCs") or []:
        a = actors.get(n["id"], {})
        out["npcs"].append((n["gameID"], a.get("name", ""), int(n["id"] in boss_ids)))

    names = {}
    for p in rep.get("phases") or []:
        if p.get("encounterID") == f.get("encounterID"):
            names = {ph["id"]: (ph["name"], int(bool(ph.get("isIntermission")))) for ph in p["phases"]}
    for tr in f.get("phaseTransitions") or []:
        nm, inter = names.get(tr["id"], (f"P{tr['id']}", 0))
        out["phases"].append((tr["id"], nm, inter, t(tr["startTime"])))

    first: dict[tuple[int, int], float] = {}
    for ev in _events(rep.get("debuffs")) + _events(rep.get("ecasts")):
        side = "target" if ev.get("type") == "applydebuff" else "source"
        k = _key(ev, side)
        if k[0] in add_ids:
            first[k] = min(first.get(k, ev["timestamp"]), ev["timestamp"])
    deaths: dict[tuple[int, int], float] = {}
    for ev in _events(rep.get("deaths")):
        k = _key(ev, "target")
        if k[0] in add_ids:
            deaths[k] = ev["timestamp"]
    for k in sorted(set(first) | set(deaths)):
        game_id = actors.get(k[0], {}).get("gameID")
        spawn = first.get(k)
        death = deaths.get(k)
        out["adds"].append((k[0], k[1], game_id, t(spawn) if spawn is not None else None,
                            t(death if death is not None else end), int(death is not None)))

    for ev in _events(rep.get("ecasts")):
        sid, inst = _key(ev, "source")
        out["enemy_casts"].append((sid, inst, ev.get("abilityGameID"), ev.get("type"), t(ev["timestamp"])))

    entries = (_rows(rep.get("dmg")).get("data") or {}).get("entries") or []
    for e in entries:
        if e.get("type") not in CLASSES:
            continue
        icon = e.get("icon") or ""
        spec = icon.split("-", 1)[1] if "-" in icon else ""
        out["players"].append((e["id"], e["type"], spec, e.get("itemLevel"), e.get("total")))
        for tg in e.get("targets") or []:
            out["damage"].append((e["id"], tg.get("name"), tg.get("total")))
        if ranked_name and e.get("name") == ranked_name:
            out["ranked_actor"] = e["id"]
    if out["ranked_actor"] is None and ranked_name:
        for i, a in actors.items():
            if a.get("type") == "Player" and a.get("name") == ranked_name:
                out["ranked_actor"] = i
    if out["ranked_actor"] is None and ranked and out["fight"]["duration_s"]:
        # anonymized report: same class/spec with the closest DPS
        cls, spec, dps = ranked
        cands = [(abs((p[4] or 0) / out["fight"]["duration_s"] - dps), p[0]) for p in out["players"]
                 if p[1] == cls and p[2] == spec]
        if cands:
            out["ranked_actor"] = min(cands)[1]
    out["_start"], out["_end"] = start, end
    return out


def _events(block: Any) -> list[dict[str, Any]]:
    return (block or {}).get("data") or []


# --- 3. collection loop ---------------------------------------------------------------------------


def _complete(client: WCLClient, code: str, fight_id: int, block: dict[str, Any], start: float,
              end: float, **kw: Any) -> None:
    """Follow nextPageTimestamp for an aliased events block, in place."""
    nxt = block.get("nextPageTimestamp")
    if nxt and nxt < end:
        block["data"] = (block.get("data") or []) + list(
            client.events(code, fight_id, nxt, end, cache=False, **kw))
        block["nextPageTimestamp"] = None


def fetch_kill(client: WCLClient, con: sqlite3.Connection, report: str, fight_id: int,
               ranked_name: str | None, ranked: tuple[str, str, float] | None = None) -> dict[str, Any]:
    data = client.query(KILL_QUERY, {"code": report, "f": [fight_id]})
    rep = data["reportData"]["report"]
    if rep is None or not (rep.get("archiveStatus") or {}).get("isAccessible", True):
        raise WCLError("report not accessible (private, deleted or archived)")
    fights = rep.get("fights") or []
    if fights:
        s, e = fights[0]["startTime"], fights[0]["endTime"]
        _complete(client, report, fight_id, rep.get("deaths") or {}, s, e,
                  data_type="Deaths", hostility="Enemies")
        _complete(client, report, fight_id, rep.get("debuffs") or {}, s, e, data_type="Debuffs",
                  hostility="Enemies", filter_expression="type='applydebuff'")
        _complete(client, report, fight_id, rep.get("ecasts") or {}, s, e,
                  data_type="Casts", hostility="Enemies")
    parsed = parse_kill(rep, fight_id, ranked_name, ranked)

    actor = parsed["ranked_actor"]
    pcasts: list[dict[str, Any]] = []
    pbuffs: list[dict[str, Any]] = []
    if actor is not None:
        pd = client.query(PLAYER_QUERY, {"code": report, "f": [fight_id], "a": actor})
        prep = pd["reportData"]["report"]
        s, e = parsed["_start"], parsed["_end"]
        _complete(client, report, fight_id, prep.get("pcasts") or {}, s, e, data_type="Casts",
                  hostility="Friendlies", source_id=actor, include_resources=True)
        _complete(client, report, fight_id, prep.get("pbuffs") or {}, s, e, data_type="Buffs",
                  hostility="Friendlies", target_id=actor)
        pcasts, pbuffs = _events(prep.get("pcasts")), _events(prep.get("pbuffs"))

    write_kill(con, report, fight_id, parsed, pcasts, pbuffs)
    return parsed


def write_kill(con: sqlite3.Connection, report: str, fight_id: int, p: dict[str, Any],
               pcasts: list[dict[str, Any]], pbuffs: list[dict[str, Any]]) -> None:
    start = p["_start"]

    def t(ts: float) -> float:
        return round((ts - start) / 1000, 3)

    clear_fight_rows(con, report, fight_id)
    fk = (report, fight_id)
    fi = p["fight"]
    con.execute("UPDATE fight SET duration_s=?, kill=?, avg_ilvl=?, size=COALESCE(?, size), "
                "difficulty=COALESCE(?, difficulty) WHERE report=? AND fight_id=?",
                (fi["duration_s"], fi["kill"], fi["avg_ilvl"], fi["size"], fi["difficulty"], *fk))
    con.executemany("INSERT OR REPLACE INTO npc VALUES(?,?,?)", p["npcs"])
    con.executemany("INSERT OR IGNORE INTO ability VALUES(?,?)", p["abilities"])
    con.executemany("INSERT INTO phase VALUES(?,?,?,?,?,?)", [(*fk, *r) for r in p["phases"]])
    con.executemany("INSERT OR REPLACE INTO add_instance VALUES(?,?,?,?,?,?,?,?)",
                    [(*fk, *r) for r in p["adds"]])
    con.executemany("INSERT OR REPLACE INTO player VALUES(?,?,?,?,?,?,?)", [(*fk, *r) for r in p["players"]])
    con.executemany("INSERT OR REPLACE INTO damage_by_target VALUES(?,?,?,?,?)",
                    [(*fk, *r) for r in p["damage"]])
    con.executemany("INSERT INTO enemy_cast VALUES(?,?,?,?,?,?,?)", [(*fk, *r) for r in p["enemy_casts"]])
    actor = p["ranked_actor"]
    con.executemany(
        "INSERT INTO player_cast(report, fight_id, actor_id, ability_id, type, t, x, y, facing, target_id,"
        " target_instance) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [(*fk, actor, ev.get("abilityGameID"), ev.get("type"), t(ev["timestamp"]),
          ev["x"] / 100 if "x" in ev and ev.get("resourceActor", 1) == 1 else None,
          ev["y"] / 100 if "y" in ev and ev.get("resourceActor", 1) == 1 else None,
          ev.get("facing") / 100 if ev.get("facing") is not None and ev.get("resourceActor", 1) == 1
          else None, ev.get("targetID"), ev.get("targetInstance"))
         for ev in pcasts])
    con.executemany(
        "INSERT INTO player_buff VALUES(?,?,?,?,?,?,?)",
        [(*fk, actor, ev.get("abilityGameID"), ev.get("type"), t(ev["timestamp"]), ev.get("sourceID"))
         for ev in pbuffs if ev.get("type") in ("applybuff", "removebuff", "applybuffstack")])
    con.execute("UPDATE ranked SET actor_id=?, name=NULL WHERE report=? AND fight_id=?", (actor, *fk))
    con.execute("UPDATE fight SET status='done', error=NULL, fetched_at=? WHERE report=? AND fight_id=?",
                (_now(), *fk))
    con.commit()


def collect(client: WCLClient, con: sqlite3.Connection, enc: Encounter, difficulty: int, *,
            points_per_hour: float = 1500, retry_errors: bool = False,
            log: Callable[[str], None] = lambda s: print(s, flush=True),
            sleep: Callable[[float], None] = time.sleep) -> dict[str, int]:
    """Fetch every pending kill of this encounter/difficulty. Resumable."""
    statuses = ("pending", "error") if retry_errors else ("pending",)
    todo = con.execute(
        "SELECT f.report, f.fight_id, r.name, r.class, r.spec, r.dps "
        "FROM fight f LEFT JOIN ranked r USING(report, fight_id) "
        f"WHERE f.encounter_id=? AND f.difficulty=? AND f.status IN ({','.join('?' * len(statuses))}) "
        f"ORDER BY r.rank_pos",
        (enc.id, difficulty, *statuses)).fetchall()
    stats = {"done": 0, "error": 0, "todo": len(todo)}
    for i, row in enumerate(todo, 1):
        if i == 1 or i % 10 == 0:
            rl = client.rate_limit()
            if rl["pointsSpentThisHour"] >= min(points_per_hour, rl["limitPerHour"] * 0.95):
                wait = int(rl["pointsResetIn"]) + 5
                log(f"  quota: {rl['pointsSpentThisHour']:.0f}/{rl['limitPerHour']} points used, "
                    f"waiting {wait // 60} min for the reset...")
                sleep(wait)
        try:
            ranked = (row["class"], row["spec"], row["dps"]) if row["dps"] else None
            p = fetch_kill(client, con, row["report"], row["fight_id"], row["name"], ranked)
            stats["done"] += 1
            adds = sum(1 for a in p["adds"] if a[5])
            log(f"  [{i}/{len(todo)}] {p['fight']['duration_s']:.0f}s, {len(p['players'])} players, "
                f"{adds} adds killed")
        except (WCLError, KeyError, TypeError, ValueError) as e:
            stats["error"] += 1
            con.execute("UPDATE fight SET status='error', error=? WHERE report=? AND fight_id=?",
                        (str(e)[:500], row["report"], row["fight_id"]))
            con.commit()
            log(f"  [{i}/{len(todo)}] skipped: {str(e)[:120]}")
    return stats
