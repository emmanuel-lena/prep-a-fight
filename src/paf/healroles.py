"""Healing compositions and roles (issue #27): which healer specs the top raids bring together on a boss, and what
job each spec does there, measured on the logs (no healing engine: SimulationCraft does not sim healing).

Per kill (KILLS of them, about 3 points each), read once into the corpus:
- every healer's healing and overhealing, their healing on the tanks (the healing table by target: each tank's
  sources), during the raid's damage spikes (the healing graph by source against the damage-taken graph), their
  dispels (the dispels table) and the raid's deaths;
- the healers' casts of long cooldowns (game data: a cooldown of LONG_CD s or more), with whether they were cast on
  another player (an external).
Then, per boss: the compositions (the healer specs of every kill of the corpus, from its players), and per spec its
share of the healing, of the tank healing, of the healing in spikes, its overheal, dispels, raid cooldowns and
externals, against the other healers of the same kills: "on this boss, this spec does this job".
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import zip_longest

from paf.corpus.analyze import kills_filter
from paf.wcl import WCLClient, WCLError

KILLS = 40  # kills read per boss (about 6 points each): enough healers of each spec to compare
LONG_CD = 90.0  # seconds: a healer's spell with at least this cooldown is a raid cooldown or an external
SPIKE = 1.5  # a graph point where the raid takes this many times its median damage is a spike

HEALERS = {("Shaman", "Restoration"), ("Druid", "Restoration"), ("Paladin", "Holy"), ("Priest", "Holy"),
           ("Priest", "Discipline"), ("Monk", "Mistweaver"), ("Evoker", "Preservation")}
TANKS = {("Warrior", "Protection"), ("Paladin", "Protection"), ("DeathKnight", "Blood"), ("Druid", "Guardian"),
         ("Monk", "Brewmaster"), ("DemonHunter", "Vengeance")}

SCHEMA = """
CREATE TABLE IF NOT EXISTS heal_stat(report TEXT, fight_id INT, actor_id INT, class TEXT, spec TEXT, total REAL,
  overheal REAL, tank REAL, spike REAL, dispels INT, PRIMARY KEY(report, fight_id, actor_id));
CREATE TABLE IF NOT EXISTS heal_dispel(report TEXT, fight_id INT, aura_id INT, n INT);  -- the ranked healer removed
CREATE TABLE IF NOT EXISTS heal_dispel_status(report TEXT, fight_id INT, PRIMARY KEY(report, fight_id));
CREATE TABLE IF NOT EXISTS heal_cast(report TEXT, fight_id INT, actor_id INT, ability_id INT, t REAL, on_other INT);
CREATE TABLE IF NOT EXISTS heal_kill(report TEXT, fight_id INT, deaths INT, spike_share REAL,
  PRIMARY KEY(report, fight_id));
"""

BOUNDS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) {
  fights(fightIDs:$f){ startTime endTime } } } }"""
# the graphs need the pull's bounds: without them they cover the whole report (paf.healer.fight_bounds)
TABLES = """query($c:String!,$f:[Int]!,$s:Float,$e:Float){ reportData { report(code:$c) {
  heal: table(fightIDs:$f, dataType:Healing, viewBy:Source)
  tgt: table(fightIDs:$f, dataType:Healing, viewBy:Target)
  disp: table(fightIDs:$f, dataType:Dispels, viewBy:Source)
  deaths: table(fightIDs:$f, dataType:Deaths)
  hg: graph(fightIDs:$f, startTime:$s, endTime:$e, dataType:Healing, viewBy:Source)
  dg: graph(fightIDs:$f, startTime:$s, endTime:$e, dataType:DamageTaken, hostilityType:Friendlies)
} } }"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def _spec(icon: str | None) -> tuple[str, str] | None:
    """"Priest-Holy" -> ("Priest", "Holy")."""
    if not icon or "-" not in icon:
        return None
    cls, spec = icon.split("-", 1)
    return cls, spec


def _data(block: dict | None) -> dict:
    d = (block or {}).get("data", block) or {}
    return d if isinstance(d, dict) else {}


def spike_points(damage: list[float]) -> set[int]:
    """The graph points where the raid takes SPIKE times its median damage or more."""
    vals = [v for v in damage if v > 0]
    if not vals:
        return set()
    floor = SPIKE * st.median(vals)
    return {i for i, v in enumerate(damage) if v >= floor}


def kill_stats(r: dict) -> tuple[list[tuple], int, float]:
    """(healer rows (actor, class, spec, total, overheal, tank, spike, dispels), deaths, share of the fight in spikes)
    from one kill's TABLES answer."""
    heal = _data(r.get("heal")).get("entries") or []
    healers = {e["id"]: e for e in heal if _spec(e.get("icon")) in HEALERS}
    tank = defaultdict(float)  # by healer name: a tank's sources carry no id
    for t in _data(r.get("tgt")).get("entries") or []:
        if _spec(t.get("icon")) in TANKS:
            for s in t.get("sources") or []:
                tank[s.get("name")] += s.get("total") or 0
    disp = Counter()
    for block in _data(r.get("disp")).get("entries") or []:  # one block per kind, then the dispelled spells
        for ab in block.get("entries") or [block]:
            for det in ab.get("details") or []:
                disp[det.get("id")] += det.get("total") or 0
    dg = _data(r.get("dg")).get("series") or []
    raid = [sum(x) for x in zip_longest(*[s.get("data") or [] for s in dg if s.get("type") not in ("Total", "Pet")],
                                        fillvalue=0)] if dg else []
    spikes = spike_points(raid)
    by_name = {s.get("name"): s.get("data") or [] for s in _data(r.get("hg")).get("series") or []}
    rows = []
    for aid, e in healers.items():
        series = by_name.get(e.get("name"), [])
        tot = sum(series) or 1
        rows.append((aid, *_spec(e["icon"]), e.get("total") or 0, e.get("overheal") or 0, tank.get(e.get("name"), 0.0),
                     sum(v for i, v in enumerate(series) if i in spikes) / tot, int(disp.get(aid, 0))))
    deaths = len(_data(r.get("deaths")).get("entries") or [])
    return rows, deaths, (len(spikes) / len(raid)) if raid else 0.0


def long_cooldowns(spell_ids: set[int]) -> set[int]:
    """The spells of a set that the game data gives a cooldown of LONG_CD s or more."""
    from paf.gamedata import spell_cooldowns

    try:
        cds = spell_cooldowns()
    except OSError:
        return set()
    return {s for s in spell_ids if (cds.get(s) or (0, 0))[0] >= LONG_CD}


def fetch_heal_roles(client: WCLClient, con: sqlite3.Connection, encounter_id: int, difficulty: int,
                     kills: int = KILLS, log: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    ensure_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM heal_kill h JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(f"SELECT f.report, f.fight_id FROM fight f LEFT JOIN heal_kill h USING(report, fight_id) "
                       f"WHERE {where} AND h.report IS NULL ORDER BY f.report LIMIT ?",
                       (*params, max(0, kills - have))).fetchall()
    for rep, fid in todo:
        try:
            fr = client.query(BOUNDS, {"c": rep, "f": [fid]}, cache_ttl=0)["reportData"]["report"]["fights"][0]
            r = client.query(TABLES, {"c": rep, "f": [fid], "s": fr["startTime"], "e": fr["endTime"]},
                             cache_ttl=0)["reportData"]["report"]
            rows, deaths, share = kill_stats(r)
            casts = [c for x in rows for c in client.events(  # one healer at a time: WCL's source.id filter
                rep, fid, fr["startTime"], fr["endTime"], data_type="Casts", hostility="Friendlies",
                source_id=x[0], cache=False)]  # returns nothing
        except (WCLError, KeyError, TypeError, IndexError, OSError) as e:
            log(f"  healing skipped: {str(e)[:100]}")
            continue
        longs = long_cooldowns({c.get("abilityGameID") for c in casts if c.get("type") == "cast"})
        con.execute("DELETE FROM heal_cast WHERE report=? AND fight_id=?", (rep, fid))
        con.executemany("INSERT OR REPLACE INTO heal_stat VALUES(?,?,?,?,?,?,?,?,?,?)",
                        [(rep, fid, *x) for x in rows])
        con.executemany("INSERT INTO heal_cast VALUES(?,?,?,?,?,?)", [
            (rep, fid, c["sourceID"], c["abilityGameID"], round((c["timestamp"] - fr["startTime"]) / 1000, 1),
             int(c.get("targetID") not in (None, -1, c["sourceID"]) and bool(c.get("targetIsFriendly", True))))
            for c in casts if c.get("type") == "cast" and c.get("abilityGameID") in longs])
        con.execute("INSERT OR REPLACE INTO heal_kill VALUES(?,?,?,?)", (rep, fid, deaths, round(share, 3)))
        con.commit()
    return len(todo)


DISPEL_KILLS = 6  # kills read for what the top healers dispel: ~1 page of events each


def fetch_dispels(client: WCLClient, con: sqlite3.Connection, encounter_id: int, difficulty: int,
                  kills: int = DISPEL_KILLS, log: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    """What the ranked healer of a few kills dispels (the aura each dispel removes): where a spec's dispels go,
    measured, not guessed from the Journal (Vashnik heroic: none of its abilities is dispellable in the game data,
    yet the top healers dispel about once a minute)."""
    ensure_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM heal_dispel_status s JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id, r.actor_id FROM fight f JOIN ranked r USING(report, fight_id) "
        f"LEFT JOIN heal_dispel_status s USING(report, fight_id) WHERE {where} AND s.report IS NULL "
        f"AND r.actor_id IS NOT NULL ORDER BY f.report LIMIT ?", (*params, max(0, kills - have))).fetchall()
    for rep, fid, actor in todo:
        try:
            fr = client.query(BOUNDS, {"c": rep, "f": [fid]}, cache_ttl=0)["reportData"]["report"]["fights"][0]
            events = list(client.events(rep, fid, fr["startTime"], fr["endTime"], data_type="Dispels",
                                        source_id=actor, cache=False))
        except (WCLError, KeyError, TypeError, IndexError, OSError) as e:
            log(f"  dispels skipped: {str(e)[:100]}")
            continue
        counts = Counter(ev.get("extraAbilityGameID") for ev in events
                         if ev.get("type") in ("dispel", "removedebuff") and ev.get("extraAbilityGameID"))
        con.executemany("INSERT INTO heal_dispel VALUES(?,?,?,?)", [(rep, fid, a, n) for a, n in counts.items()])
        con.execute("INSERT OR REPLACE INTO heal_dispel_status VALUES(?,?)", (rep, fid))
        con.commit()
    return len(todo)


def dispelled(con: sqlite3.Connection, encounter_id: int, difficulty: int, names: dict[int, str],
              top: int = 3) -> tuple[list[tuple[str, float]], int]:
    """(debuff, dispels a kill) the ranked healers remove the most, and the kills read."""
    ensure_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    n = con.execute(f"SELECT COUNT(*) FROM heal_dispel_status s JOIN fight f USING(report, fight_id) WHERE {where}",
                    params).fetchone()[0]
    rows = con.execute(f"SELECT d.aura_id, SUM(d.n) FROM heal_dispel d JOIN fight f USING(report, fight_id) "
                       f"WHERE {where} GROUP BY d.aura_id ORDER BY 2 DESC LIMIT ?", (*params, top)).fetchall()
    return [(names.get(a, f"spell {a}"), s / n) for a, s in rows if n], n


# --- compositions -----------------------------------------------------------------------------------------------

@dataclass
class Comp:
    specs: tuple[str, ...]  # "Holy Priest", sorted, one entry per healer
    kills: int
    share: float  # of the corpus' kills
    duration: float  # median kill time (s)
    deaths: float | None  # mean deaths, on the kills read (None: none read)

    @property
    def label(self) -> str:
        c = Counter(self.specs)
        return " + ".join(f"{n} {s}" if n > 1 else s for s, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))


def pretty(cls: str, spec: str) -> str:
    return f"{spec} {'Death Knight' if cls == 'DeathKnight' else 'Demon Hunter' if cls == 'DemonHunter' else cls}"


def kills_of(con: sqlite3.Connection, encounter_id: int, difficulty: int,
             role: set[tuple[str, str]] = HEALERS) -> dict[tuple[str, int], tuple[list[str], float, int | None]]:
    """Per top kill: (the specs of the role, its duration, its deaths if read). The healers come from the healing
    tables read (heal_stat): the corpus' players come from the damage table, where a healer who never attacks is
    missing (the Restoration corpus showed 1 or 2 healers in raids of 27 to 30). The tanks always attack: the
    corpus' players."""
    ensure_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    per: dict[tuple[str, int], list[str]] = defaultdict(list)
    dur: dict[tuple[str, int], float] = {}
    if role is HEALERS:
        dur = {(r, f): d for r, f, d in con.execute(
            f"SELECT k.report, k.fight_id, f.duration_s FROM heal_kill k JOIN fight f USING(report, fight_id) "
            f"WHERE {where}", params)}
        for rep, fid, cls, spec in con.execute(
                f"SELECT h.report, h.fight_id, h.class, h.spec FROM heal_stat h JOIN fight f USING(report, fight_id) "
                f"WHERE {where}", params):
            per[(rep, fid)].append(pretty(cls, spec))
    else:
        for rep, fid, cls, spec, d in con.execute(
                f"SELECT p.report, p.fight_id, p.class, p.spec, f.duration_s FROM player p "
                f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
            dur[(rep, fid)] = d
            if (cls, spec) in role:
                per[(rep, fid)].append(pretty(cls, spec))
    deaths = {(r, f): n for r, f, n in con.execute("SELECT report, fight_id, deaths FROM heal_kill")}
    return {k: (sorted(per[k]), d, deaths.get(k)) for k, d in dur.items() if per.get(k)}


def comps(con: sqlite3.Connection, encounter_id: int, difficulty: int, min_kills: int = 5,
          role: set[tuple[str, str]] = HEALERS) -> list[Comp]:
    """The exact compositions of a role in the top kills (kills_of), played at least min_kills times."""
    ks = kills_of(con, encounter_id, difficulty, role)
    groups: dict[tuple[str, ...], list] = defaultdict(list)
    for specs, d, dead in ks.values():
        groups[tuple(specs)].append((d, dead))
    n = len(ks) or 1
    out = []
    for specs, rows in groups.items():
        if len(rows) < min_kills:
            continue
        ds = [x for _d, x in rows if x is not None]
        out.append(Comp(specs, len(rows), len(rows) / n, st.median(d for d, _x in rows),
                        round(st.mean(ds), 1) if ds else None))  # deaths: a mean, as in the presence table
    return sorted(out, key=lambda c: -c.kills)


@dataclass
class Presence:
    """One spec in the top raids of a boss: how often it is brought, and the kills with it against without it."""
    spec: str
    share: float  # of the kills bringing at least one
    per_kill: float  # when brought
    kills: int
    duration_with: float
    duration_without: float | None
    deaths_with: float | None
    deaths_without: float | None


def presence(con: sqlite3.Connection, encounter_id: int, difficulty: int,
             role: set[tuple[str, str]] = HEALERS) -> list[Presence]:
    """Per spec of a role, most brought first: the kills that bring it against those that do not."""
    ks = list(kills_of(con, encounter_id, difficulty, role).values())
    out = []

    def mean(vals: list) -> float | None:
        vals = [v for v in vals if v is not None]
        return round(st.mean(vals), 1) if vals else None

    def med(vals: list) -> float | None:
        vals = [v for v in vals if v is not None]
        return st.median(vals) if vals else None
    for s in {x for specs, _d, _k in ks for x in specs}:
        with_ = [k for k in ks if s in k[0]]
        without = [k for k in ks if s not in k[0]]
        out.append(Presence(s, len(with_) / len(ks), st.mean(k[0].count(s) for k in with_), len(with_),
                            med([k[1] for k in with_]), med([k[1] for k in without]), mean([k[2] for k in with_]),
                            mean([k[2] for k in without])))  # deaths: a mean (one decimal), a median of 0s and 1s
                                                              # reads as a verdict
    return sorted(out, key=lambda p: -p.share)


def spec_counts(con: sqlite3.Connection, encounter_id: int, difficulty: int,
                role: set[tuple[str, str]] = HEALERS) -> list[tuple[str, float, float]]:
    """Per spec of a role: (spec, share of the kills that bring at least one, players of it per kill when brought)."""
    return [(p.spec, p.share, p.per_kill) for p in presence(con, encounter_id, difficulty, role)]


# --- roles ------------------------------------------------------------------------------------------------------

@dataclass
class Role:
    spec: str
    players: int  # healer-kills measured
    healing: float  # median share of the healers' healing, per healer
    tank: float  # median share of their own healing that goes on the tanks
    spike: float  # median share of their own healing done during the raid's damage spikes
    overheal: float  # median overheal / (healing + overheal)
    dispels: float  # median dispels per minute
    raid_cds: float  # long cooldowns cast on themselves or the raid, per kill
    externals: float  # long cooldowns cast on another player, per kill
    cd_names: list[tuple[str, float, list[float]]] = field(default_factory=list)  # (spell, per kill, median times)
    jobs: list[str] = field(default_factory=list)  # what the numbers say this spec does on this boss
    se: dict[str, float] = field(default_factory=dict)  # standard error of each number (its healers' spread)


TANK_HEALER = 1.4  # a spec puts this many times the other healers' tank share on the tanks: the tank healer
TANK_FLOOR = 0.12  # ... and at least this share: a tank's sources are its top healers only (a lower bound), and
# every healer measured on three bosses puts 4 to 10% on them
SPIKE_HEALER = 1.25  # ... of the share in spikes: the burst healer
DISPELLER = 2.0  # ... of the dispels: the dispeller
LOW_OVERHEAL = 0.75  # ... of the overheal or less: the efficient one


def roles(con: sqlite3.Connection, encounter_id: int, difficulty: int, names: dict[int, str] | None = None,
          min_players: int = 8) -> list[Role]:
    """What each healer spec does on this boss, against the other healers of the same kills."""
    ensure_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(f"SELECT h.* FROM heal_stat h JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchall()
    durs = {(r[0], r[1]): r[2] for r in con.execute(f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}",
                                                    params)}
    per_kill: dict[tuple[str, int], list] = defaultdict(list)
    for r in rows:
        per_kill[(r[0], r[1])].append(r)
    casts: dict[tuple[str, int, int], list[tuple[int, float, int]]] = defaultdict(list)
    for rep, fid, aid, ab, t, other in con.execute(
            f"SELECT c.report, c.fight_id, c.actor_id, c.ability_id, c.t, c.on_other FROM heal_cast c "
            f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        casts[(rep, fid, aid)].append((ab, t, other))
    spec_of = {(r[0], r[1], r[2]): pretty(r[3], r[4]) for r in rows}
    users: dict[int, set[str]] = defaultdict(set)
    for key, cs in casts.items():
        for ab, _t, _o in cs:
            users[ab].add(spec_of.get(key, ""))
    common = {ab for ab, specs in users.items() if len(specs) >= 3}  # three specs or more: a trinket, a potion
    stats: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    cd_times: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for k, hs in per_kill.items():
        total = sum(h[5] for h in hs) or 1
        minutes = (durs.get(k) or 1) / 60
        for h in hs:
            spec, tot, over, tank, spike, disp = pretty(h[3], h[4]), h[5], h[6], h[7], h[8], h[9]
            s = stats[spec]
            s["healing"].append(tot / total)
            s["tank"].append(tank / tot if tot else 0)
            s["spike"].append(spike)
            s["overheal"].append(over / (tot + over) if tot + over else 0)
            s["dispels"].append(disp / minutes)
            mine = [c for c in casts.get((k[0], k[1], h[2]), []) if c[0] not in common]
            s["raid"].append(sum(1 for _a, _t, o in mine if not o))
            s["ext"].append(sum(1 for _a, _t, o in mine if o))
            for ab, t, _o in mine:
                cd_times[spec][ab].append(t)
    out = []
    for spec, s in stats.items():
        n = len(s["healing"])
        if n < min_players:
            continue
        cds = [((names or {}).get(ab, f"spell {ab}"), len(ts) / n, _peaks(ts)) for ab, ts in cd_times[spec].items()
               if len(ts) / n >= 0.5]
        se = {k: (st.stdev(v) / len(v) ** 0.5 if len(v) > 1 else 0.0) for k, v in s.items()}
        out.append(Role(spec, n, st.median(s["healing"]), st.median(s["tank"]), st.median(s["spike"]),
                        st.median(s["overheal"]), st.median(s["dispels"]), st.mean(s["raid"]), st.mean(s["ext"]),
                        sorted(cds, key=lambda c: -c[1]),
                        se={"tank": se["tank"], "spike": se["spike"], "overheal": se["overheal"],
                            "dispels": se["dispels"], "raid_cds": se["raid"], "externals": se["ext"]}))
    for r in out:
        r.jobs = jobs(r, out)
    return sorted(out, key=lambda r: -r.players)


def _peaks(times: list[float], gap: float = 20.0) -> list[float]:
    """The usual moments of a set of cast times (clusters holding at least a fifth of them), medians."""
    groups: list[list[float]] = []
    for t in sorted(times):
        if groups and t - groups[-1][-1] <= gap:
            groups[-1].append(t)
        else:
            groups.append([t])
    keep = [g for g in groups if len(g) >= max(2, len(times) / 5)]
    return [round(st.median(g), 1) for g in keep]


def jobs(r: Role, everyone: list[Role]) -> list[str]:
    """What this spec does on the boss, from its numbers against the other healer specs measured."""
    others = [o for o in everyone if o is not r]
    if not others:
        return []

    def ref(attr: str) -> float:
        return st.median(getattr(o, attr) for o in others) or 0.0

    def clear(attr: str, lower: bool = False) -> bool:
        """The gap to the other healers is beyond this spec's sampling noise (two standard errors)."""
        gap = (ref(attr) - getattr(r, attr)) if lower else (getattr(r, attr) - ref(attr))
        return gap > 2 * r.se.get(attr, 0.0)
    out = []
    if r.tank >= max(TANK_FLOOR, ref("tank") * TANK_HEALER) and clear("tank"):
        out.append(f"heals the tanks: {r.tank:.0%} of its healing goes on them (the other healers {ref('tank'):.0%})")
    if r.spike >= max(0.05, ref("spike") * SPIKE_HEALER) and clear("spike"):
        out.append(f"answers the raid's damage spikes: {r.spike:.0%} of its healing lands in them "
                   f"(the other healers {ref('spike'):.0%})")
    if r.dispels >= max(0.2, ref("dispels") * DISPELLER) and clear("dispels"):
        out.append(f"dispels: {r.dispels:.1f} a minute (the other healers {ref('dispels'):.1f})")
    if r.externals >= 1 and r.externals >= ref("externals") * 1.5 and clear("externals"):
        out.append(f"gives externals: {r.externals:.1f} a kill on other players")
    if r.raid_cds >= 1 and r.raid_cds >= ref("raid_cds") * 1.5 and clear("raid_cds"):
        out.append(f"presses the most long cooldowns: {r.raid_cds:.1f} a kill")
    if r.overheal <= ref("overheal") * LOW_OVERHEAL and clear("overheal", lower=True):
        out.append(f"wastes little: {r.overheal:.0%} overhealing (the other healers {ref('overheal'):.0%})")
    if not out:
        out.append("close to the other healers on every number below")
    return out


def sample(con: sqlite3.Connection, encounter_id: int, difficulty: int) -> tuple[int, float, float]:
    """The kills the roles were measured on: (kills, median kill time, mean deaths). Shown with the roles: the
    sample changes them (Nek'zali heroic, the same specs: overheal 46-63% in kills ranked by an Elemental's damage,
    4:05 and no death; 19-35% in kills ranked by a Restoration Shaman's healing, 4:50 and 2 deaths)."""
    ensure_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(f"SELECT f.duration_s, k.deaths FROM heal_kill k JOIN fight f USING(report, fight_id) "
                       f"WHERE {where}", params).fetchall()
    if not rows:
        return 0, 0.0, 0.0
    return len(rows), st.median(r[0] for r in rows), round(st.mean(r[1] for r in rows), 1)
