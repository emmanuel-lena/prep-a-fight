"""Your raid night, pull by pull: who died, who used a healthstone or a health potion (and who died without), who
pressed a damage potion. For the raid leader.

From one log: the deaths of each pull and the casts of the consumables, recognized by their name in the log (English
or French: Healthstone, Pierre de soins, Health/Healing Potion, Potion de soins...); the other potions but mana
potions are damage potions. The potion counters of Warcraft Logs' player details stay at 0 in this expansion: the
casts are read instead. A potion pressed before the pull is not a cast of the pull: it is missed. The deaths of
the wipe itself (from the death that leaves half the raid dead) are left out.

The log: the one given, else the latest log of your active character (a live log too, while your raid uploads it),
else your guild's latest. Live, the pulls are read again every 90 s until 30 min pass without a new one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

MIN_PULL = 30.0  # shorter pulls (a reset) are left out
ABILITIES = """query($c:String!){ reportData { report(code:$c) {
  masterData { abilities { gameID name } actors(type:"Player") { id name icon } }
  fights(killType: Encounters) { id encounterID name difficulty kill startTime endTime bossPercentage
    friendlyPlayers } } } }"""
DEATHS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) { table(fightIDs:$f, dataType:Deaths) } } }"""
CASTS = """query($c:String!,$f:[Int]!,$x:String!,$s:Float){ reportData { report(code:$c) {
  events(fightIDs:$f, dataType:Casts, hostilityType:Friendlies, filterExpression:$x, startTime:$s, limit:10000)
  { data nextPageTimestamp } } } }"""


def kind(name: str) -> str | None:
    """'healthstone' | 'health' (a health potion) | 'damage' (a damage potion) | None."""
    n = name.lower()
    if n.startswith(("create ", "soulburn", "créer", "brûlure")):
        return None
    if "healthstone" in n or "pierre de soins" in n or "pierre de vie" in n:
        return "healthstone"
    if "potion" not in n:
        return None
    if any(w in n for w in ("health", "healing", "soins", "santé", "vie")):
        return "health"
    if "mana" in n:
        return None
    return "damage"


@dataclass
class PlayerPull:
    deaths: list[float] = field(default_factory=list)
    healthstone: list[float] = field(default_factory=list)
    health: list[float] = field(default_factory=list)
    damage: list[float] = field(default_factory=list)

    @property
    def died_bare(self) -> bool:
        """Died (the first time) without a healthstone or a health potion before."""
        if not self.deaths:
            return False
        first = self.deaths[0]
        return not any(t <= first for t in self.healthstone + self.health)


@dataclass
class PullRow:
    fight: int
    boss: str
    difficulty: int
    kill: bool
    duration: float
    boss_left: float | None
    players: dict[str, PlayerPull] = field(default_factory=dict)


def character_reports(client, name: str, server: str, region: str) -> list[str]:
    """The recent logs of a character, newest first (a live log too, while the raid uploads it)."""
    from paf.character import CHARACTER_QUERY, server_slug

    ch = client.query(CHARACTER_QUERY, {"n": name, "s": server_slug(server), "r": (region or "eu").upper()},
                      cache_ttl=60)["characterData"]["character"]
    reports = sorted(((ch or {}).get("recentReports") or {}).get("data") or [], key=lambda r: -r["startTime"])
    return [r["code"] for r in reports]


def character_report(client, name: str, server: str, region: str) -> str | None:
    """The latest log of a character, from Warcraft Logs."""
    codes = character_reports(client, name, server, region)
    return codes[0] if codes else None


def night(client, code: str, encounter_id: int | None = None, live: bool = False
          ) -> tuple[list[PullRow], dict[str, str]]:
    """The pulls of the log (of one boss when encounter_id is given), and player name -> icon ("Class-Spec")."""
    # a live log grows: its pulls are read again every minute (a finished pull's events never change: cached)
    rep = client.query(ABILITIES, {"c": code}, cache_ttl=60 if live else 3600)["reportData"]["report"]
    kinds = {a["gameID"]: k for a in rep["masterData"]["abilities"] or [] if (k := kind(a.get("name") or ""))}
    actors = {a["id"]: a for a in rep["masterData"]["actors"] or []}
    icons = {a["name"]: a.get("icon", "") for a in actors.values()}
    expr = f"ability.id in ({', '.join(str(i) for i in sorted(kinds))})" if kinds else ""
    rows = []
    for f in rep["fights"] or []:
        dur = (f["endTime"] - f["startTime"]) / 1000
        if dur < MIN_PULL or (encounter_id is not None and f["encounterID"] != encounter_id):
            continue
        t0 = f["startTime"]
        row = PullRow(f["id"], f.get("name") or str(f["encounterID"]), f["difficulty"], bool(f["kill"]), dur,
                      None if f["kill"] else (f.get("bossPercentage") or 0) / 100)
        players: dict[str, PlayerPull] = defaultdict(PlayerPull)
        table = client.query(DEATHS, {"c": code, "f": [f["id"]]}, cache_ttl=86400)["reportData"]["report"]["table"]
        table = table.get("data", table) if isinstance(table, dict) else {}
        deaths = sorted(((e["timestamp"] - t0) / 1000, e["name"]) for e in table.get("entries") or [])
        raid = len(f.get("friendlyPlayers") or []) or len({n for _, n in deaths}) or 1
        for i, (t, name) in enumerate(deaths):
            if i + 1 >= raid / 2:  # the wipe itself: half the raid is dead
                break
            players[name].deaths.append(t)
        start = None
        while expr:
            ev = client.query(CASTS, {"c": code, "f": [f["id"]], "x": expr, "s": start},
                              cache_ttl=86400)["reportData"]["report"]["events"]
            for e in ev.get("data") or []:
                who = actors.get(e.get("sourceID"))
                k = kinds.get(e.get("abilityGameID"))
                if who and k and e.get("type") == "cast":
                    getattr(players[who["name"]], k).append((e["timestamp"] - t0) / 1000)
            start = ev.get("nextPageTimestamp")
            if not start:
                break
        row.players = dict(players)
        rows.append(row)
    return rows, icons


def summary(rows: list[PullRow]) -> dict[str, dict]:
    """Per player over the night: pulls, deaths, deaths without a healthstone or health potion, uses."""
    out: dict[str, dict] = defaultdict(lambda: {"deaths": 0, "bare": 0, "healthstone": 0, "health": 0, "damage": 0,
                                                "pulls_damage_potion": 0})
    for r in rows:
        for name, p in r.players.items():
            s = out[name]
            s["deaths"] += len(p.deaths)
            s["bare"] += p.died_bare
            s["healthstone"] += len(p.healthstone)
            s["health"] += len(p.health)
            s["damage"] += len(p.damage)
            s["pulls_damage_potion"] += bool(p.damage)
    return dict(out)


def to_dict(code_label: str, rows: list[PullRow], icons: dict[str, str]) -> dict:
    return {"report": code_label, "pulls": [
        {"fight": r.fight, "boss": r.boss, "difficulty": r.difficulty, "kill": r.kill, "duration": r.duration,
         "left": r.boss_left, "players": {n: {"deaths": p.deaths, "healthstone": p.healthstone, "health": p.health,
                                              "damage": p.damage, "bare": p.died_bare} for n, p in r.players.items()}}
        for r in rows], "summary": summary(rows), "icons": icons}
