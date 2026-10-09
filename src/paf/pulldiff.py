"""Two pulls of a boss side by side: what went better in one than in the other, for the raid and for one player.

By default, for a player: their worst and their best pull by their own DPS, among the pulls where they did not die
(so the gap is gameplay, not a death); for the raid: the kill against the best wipe, else the two best wipes; or any
two pulls of the log.
- The raid (paf.wipe, 15 s windows): the boss's health over both pulls, at the same moments; the deaths before the wipe
  and the boss health they cost; the raid's share of damage on each target.
- One player: damage on the boss per second, time active (Warcraft Logs' activeTime), damage per second of each
  ability, casts per minute of each ability (the rare ones are the cooldowns: their cast times are listed), the
  uptime of their own buffs and procs (the auras players of other classes also have, like a healer's, are left out),
  deaths, healthstones and potions (paf.tracker).
The highlights put first what moved the most: a change smaller than the noise of two pulls (a few %) is not one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from paf import tracker, wipe

FIGHTS = """query($c:String!){ reportData { report(code:$c) {
  masterData { actors(type:"Player") { id name icon } }
  fights(killType: Encounters) { id encounterID difficulty kill startTime endTime bossPercentage friendlyPlayers }
  } } }"""
SOURCE_TABLE = """query($c:String!,$f:[Int]!,$s:Int!,$d:TableDataType!){ reportData { report(code:$c) {
  table(fightIDs:$f, dataType:$d, sourceID:$s) } } }"""
ALL_DAMAGE = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) {
  table(fightIDs:$f, dataType:DamageDone) } } }"""
CASTS = """query($c:String!,$f:[Int]!,$s:Int!,$a:Float){ reportData { report(code:$c) {
  events(fightIDs:$f, dataType:Casts, sourceID:$s, startTime:$a, limit:10000) { data nextPageTimestamp } } } }"""

COOLDOWN_PER_MIN = 0.75  # an ability cast at most this often is shown as a cooldown, with its cast times
MOVED = 0.05  # a relative change under this is noise between two pulls
BUFF_MOVED = 0.1  # uptime points
SAME_LENGTH = 0.6


@dataclass
class Player:
    name: str
    icon: str
    dps: float = 0.0
    boss_dps: float = 0.0
    active: float | None = None  # share of the pull
    abilities: dict[str, float] = field(default_factory=dict)  # name -> damage per second
    casts: dict[str, int] = field(default_factory=dict)  # name -> casts
    cooldowns: dict[str, list[float]] = field(default_factory=dict)  # rare casts -> their times
    buffs: dict[str, float] = field(default_factory=dict)  # name -> uptime share
    deaths: list[float] = field(default_factory=list)
    healthstone: int = 0
    health: int = 0
    damage_potion: int = 0


@dataclass
class Side:
    fight: int
    kill: bool
    left: float  # boss health left at the end
    duration: float
    pull: wipe.Pull
    shares: dict[str, float]  # target -> share of the raid's damage
    deaths: dict[str, list[float]]  # player -> deaths before the wipe
    bare: int  # deaths without a healthstone or health potion first
    player: Player | None = None

    @property
    def label(self) -> str:
        m = f"{int(self.duration // 60)}:{int(self.duration % 60):02d}"
        return f"kill of {m}" if self.kill else f"wipe at {self.left:.0%} after {m}"


def pulls(client, code: str, encounter_id: int, difficulty: int) -> tuple[list[dict], dict[str, dict]]:
    rep = client.query(FIGHTS, {"c": code}, cache_ttl=3600)["reportData"]["report"]
    fights = [f for f in rep["fights"] or [] if f["encounterID"] == encounter_id and f["difficulty"] == difficulty
              and f["endTime"] - f["startTime"] >= tracker.MIN_PULL * 1000]
    # two players of the same name in a log (another realm): the one in the pulls of this boss
    present = Counter(p for f in fights for p in f.get("friendlyPlayers") or [])
    actors = sorted(rep["masterData"]["actors"] or [], key=lambda a: present.get(a["id"], 0))
    return fights, {a["name"]: a for a in actors}


def default_pair(fights: list[dict]) -> tuple[dict, dict] | None:
    """(A, B): the best wipe and the kill, else the second best wipe and the best one."""
    kills = [f for f in fights if f["kill"]]
    wipes = sorted((f for f in fights if not f["kill"] and f.get("bossPercentage") is not None),
                   key=lambda f: f["bossPercentage"])
    if kills and wipes:
        return wipes[0], kills[0]
    if len(wipes) >= 2:
        return wipes[1], wipes[0]
    return None


def player_pair(client, code: str, fights: list[dict], name: str, rows: dict[int, tracker.PullRow]
                ) -> tuple[dict, dict] | None:
    """(worst, best) pull of the player by their DPS, among the pulls where they did not die and that last at least
    60% of the longest of them (a short pull's DPS is inflated by the opener)."""
    scored = []
    alive = [f for f in fights if not ((r := rows.get(f["id"])) and r.players.get(name) and r.players[name].deaths)]
    longest = max(((f["endTime"] - f["startTime"]) / 1000 for f in alive), default=0)
    for f in alive:
        dur = (f["endTime"] - f["startTime"]) / 1000
        if dur < max(60, SAME_LENGTH * longest):  # a short pull is all opener and cooldowns: not comparable
            continue
        t = client.query(ALL_DAMAGE, {"c": code, "f": [f["id"]]}, cache_ttl=86400)["reportData"]["report"]["table"]
        t = t.get("data", t) if isinstance(t, dict) else {}
        me = next((e for e in t.get("entries") or [] if e.get("name") == name), None)
        if me and me.get("total"):
            scored.append((me["total"] / dur, f))
    if len(scored) < 2:
        return None
    scored.sort(key=lambda x: x[0])
    return scored[0][1], scored[-1][1]


def _table(client, code: str, fid: int, source: int, kind: str) -> dict:
    t = client.query(SOURCE_TABLE, {"c": code, "f": [fid], "s": source, "d": kind},
                     cache_ttl=86400)["reportData"]["report"]["table"]
    return t.get("data", t) if isinstance(t, dict) else {}


def player_side(client, code: str, fight: dict, actor: dict, p: wipe.Pull, row: tracker.PullRow | None,
                others: list[dict] = ()) -> Player:
    """others: players of the pull (their auras tell the externals from the player's own buffs)."""
    fid, dur = fight["id"], (fight["endTime"] - fight["startTime"]) / 1000
    out = Player(actor["name"], actor.get("icon", ""))
    dmg = _table(client, code, fid, actor["id"], "DamageDone")
    out.abilities = {}
    for e in dmg.get("entries") or []:
        out.abilities[e.get("name", "?")] = out.abilities.get(e.get("name", "?"), 0.0) + (e.get("total") or 0) / dur
    out.dps = sum(out.abilities.values())
    everyone = client.query(ALL_DAMAGE, {"c": code, "f": [fid]}, cache_ttl=86400)["reportData"]["report"]["table"]
    everyone = everyone.get("data", everyone) if isinstance(everyone, dict) else {}
    me = next((e for e in everyone.get("entries") or [] if e.get("name") == actor["name"]), {})
    bosses = p.bosses or ({max(p.targets, key=p.targets.get)} if p.targets else set())  # else: the most hit
    out.boss_dps = sum(t.get("total", 0) for t in me.get("targets") or [] if t.get("name") in bosses) / dur
    if me.get("activeTime") and everyone.get("totalTime"):
        out.active = min(1.0, me["activeTime"] / everyone["totalTime"])
    casts = _table(client, code, fid, actor["id"], "Casts")
    out.casts = {e.get("name", "?"): int(e.get("total") or 0) for e in casts.get("entries") or []}
    rare = {n for n, k in out.casts.items() if 0 < k <= max(1, COOLDOWN_PER_MIN * dur / 60)}
    if rare:
        ids = {e.get("guid"): e.get("name") for e in casts.get("entries") or [] if e.get("name") in rare}
        start = None
        while True:
            ev = client.query(CASTS, {"c": code, "f": [fid], "s": actor["id"], "a": start},
                              cache_ttl=86400)["reportData"]["report"]["events"]
            for x in ev.get("data") or []:
                name = ids.get(x.get("abilityGameID"))
                if name and x.get("type") == "cast":
                    out.cooldowns.setdefault(name, []).append((x["timestamp"] - fight["startTime"]) / 1000)
            start = ev.get("nextPageTimestamp")
            if not start:
                break
    buffs = _table(client, code, fid, actor["id"], "Buffs")
    total = (buffs.get("totalTime") or dur * 1000) or 1
    shared: set[str] = set()  # auras of players of other classes too: externals (a healer's), not the player's own
    cls = actor.get("icon", "").partition("-")[0]
    for other in [x for x in others if x.get("icon", "").partition("-")[0] != cls][:2]:
        shared |= {a.get("name") for a in _table(client, code, fid, other["id"], "Buffs").get("auras") or []}
    out.buffs = {a.get("name", "?"): (a.get("totalUptime") or 0) / total for a in buffs.get("auras") or []
                 if a.get("name") not in shared}
    mine = row.players.get(actor["name"]) if row else None
    if mine:
        out.deaths, out.healthstone, out.health, out.damage_potion = (mine.deaths, len(mine.healthstone),
                                                                       len(mine.health), len(mine.damage))
    return out


def side(client, code: str, fight: dict, boss: str, row: tracker.PullRow | None, actor: dict | None,
         others: list[dict] = ()) -> Side:
    p = wipe.analyze(client, code, fight, boss, 0.0)
    total = sum(p.targets.values()) or 1
    deaths = {n: x.deaths for n, x in (row.players.items() if row else []) if x.deaths}
    bare = sum(x.died_bare for x in row.players.values()) if row else 0
    s = Side(fight["id"], bool(fight["kill"]), (fight.get("bossPercentage") or 0) / 100 if not fight["kill"] else 0.0,
             (fight["endTime"] - fight["startTime"]) / 1000, p, {t: v / total for t, v in p.targets.items()}, deaths,
             bare)
    if actor:
        in_pull = [x for x in others if x["name"] in p.players and x["name"] != actor["name"]]
        s.player = player_side(client, code, fight, actor, p, row, in_pull)
    return s


def _rel(a: float, b: float) -> float:
    return b / a - 1 if a else 0.0


def highlights(a: Side, b: Side, boss: str) -> list[tuple[str, str]]:
    """What B did better (or worse) than A, biggest first: (kind, sentence) with kind good / bad."""
    out: list[tuple[float, str, str]] = []
    t = min(a.duration, b.duration)
    la, lb = a.pull.left_at(t), b.pull.left_at(t)
    out.append((abs(la - lb) * 4, "good" if lb < la else "bad",
                f"At {int(t // 60)}:{int(t % 60):02d}, the boss had {lb:.0%} left in B against {la:.0%} in A."))
    da, db = sum(len(v) for v in a.deaths.values()), sum(len(v) for v in b.deaths.values())
    if da != db:
        out.append((abs(da - db) / 10, "good" if db < da else "bad", f"Deaths before the wipe: {db} in B, {da} in A."))
    for target in sorted(set(a.shares) | set(b.shares), key=lambda x: -(a.shares.get(x, 0) + b.shares.get(x, 0))):
        sa, sb = a.shares.get(target, 0.0), b.shares.get(target, 0.0)
        if abs(sb - sa) >= 0.03:
            good = (sb > sa) == (target in (b.pull.bosses or {boss}))
            out.append((abs(sb - sa) * 2, "good" if good else "bad",
                        f"Share of the raid's damage on {target}: {sb:.0%} in B, {sa:.0%} in A."))
    pa, pb = a.player, b.player
    if pa and pb:
        if abs(_rel(pa.boss_dps, pb.boss_dps)) >= MOVED:
            out.append((abs(_rel(pa.boss_dps, pb.boss_dps)) * 3, "good" if pb.boss_dps > pa.boss_dps else "bad",
                        f"{pb.name}: {pb.boss_dps / 1000:,.0f}k on the boss in B, {pa.boss_dps / 1000:,.0f}k in A."))
        if pa.active is not None and pb.active is not None and abs(pb.active - pa.active) >= 0.03:
            out.append((abs(pb.active - pa.active) * 3, "good" if pb.active > pa.active else "bad",
                        f"{pb.name}: active {pb.active:.0%} of the pull in B, {pa.active:.0%} in A."))
        if len(pa.deaths) != len(pb.deaths):
            out.append((0.3, "good" if len(pb.deaths) < len(pa.deaths) else "bad",
                        f"{pb.name}: died {len(pb.deaths)} time(s) in B, {len(pa.deaths)} in A."))
    return [(k, s) for _, k, s in sorted(out, key=lambda x: -x[0])]


def ability_rows(a: Player, b: Player, limit: int = 8) -> list[dict]:
    names = set(a.abilities) | set(b.abilities)
    rows = [{"name": n, "a": a.abilities.get(n, 0.0), "b": b.abilities.get(n, 0.0)} for n in names]
    return sorted(rows, key=lambda r: -abs(r["b"] - r["a"]))[:limit]


def cast_rows(a: Player, b: Player, da: float, db: float) -> list[dict]:
    """Per ability: casts per minute in A and B; the rare ones (cooldowns) with their times."""
    rows = []
    for n in sorted(set(a.casts) | set(b.casts)):
        ca, cb = a.casts.get(n, 0) / (da / 60), b.casts.get(n, 0) / (db / 60)
        cd = n in a.cooldowns or n in b.cooldowns
        if cd or abs(cb - ca) >= max(0.3, MOVED * max(ca, cb)):
            rows.append({"name": n, "a": ca, "b": cb, "cooldown": cd, "times_a": a.cooldowns.get(n, []),
                         "times_b": b.cooldowns.get(n, [])})
    return sorted(rows, key=lambda r: (not r["cooldown"], -abs(r["b"] - r["a"])))


def buff_rows(a: Player, b: Player, limit: int = 6) -> list[dict]:
    rows = [{"name": n, "a": a.buffs.get(n, 0.0), "b": b.buffs.get(n, 0.0)} for n in set(a.buffs) | set(b.buffs)]
    rows = [r for r in rows if abs(r["b"] - r["a"]) >= BUFF_MOVED and max(r["a"], r["b"]) >= 0.2]
    return sorted(rows, key=lambda r: -abs(r["b"] - r["a"]))[:limit]


def to_dict(boss: str, a: Side, b: Side) -> dict:
    curve = {k: [round(s.pull.left_at(w * wipe.STEP), 4) for w in range(len(s.pull.windows) + 1)]
             for k, s in (("a", a), ("b", b))}
    out = {"boss": boss, "a": {"label": a.label, "fight": a.fight, "duration": a.duration},
           "b": {"label": b.label, "fight": b.fight, "duration": b.duration}, "curves": curve,
           "highlights": [{"kind": k, "text": t} for k, t in highlights(a, b, boss)],
           "deaths": {"a": a.deaths, "b": b.deaths, "bare_a": a.bare, "bare_b": b.bare}}
    if a.player and b.player:
        pa, pb = a.player, b.player
        out["player"] = {
            "name": pb.name, "icon": pb.icon, "boss_a": pa.boss_dps, "boss_b": pb.boss_dps, "dps_a": pa.dps,
            "dps_b": pb.dps, "active_a": pa.active, "active_b": pb.active,
            "abilities": ability_rows(pa, pb), "casts": cast_rows(pa, pb, a.duration, b.duration),
            "buffs": buff_rows(pa, pb),
            "consumables": {k: [getattr(pa, k), getattr(pb, k)] for k in ("healthstone", "health", "damage_potion")},
            "deaths": [pa.deaths, pb.deaths]}
    return out
