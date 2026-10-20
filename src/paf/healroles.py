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
from paf.corpus.collect import without_twins
from paf.corpus.db import TWIN
from paf.gamedata import external_kind
from paf.wcl import WCLClient, WCLError

KILLS = 40  # kills read per boss (about 6 points each): enough healers of each spec to compare
LONG_RATE = 1.1  # casts a minute: above, the median player of the spec uses the spell in its rotation
LONG_CD = 60.0  # seconds: a healer's spell with at least this cooldown is a raid cooldown or an external (Time
# Dilation and Ironbark are 60-90 s: at 90 the externals missed them)
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
CREATE TABLE IF NOT EXISTS heal_dispel_time(report TEXT, fight_id INT, aura_id INT, t REAL, delay REAL);
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


# a cast on another player is logged once more on the caster (Power Infusion's self copy): that copy goes
HEAL_TWINS = f"""DELETE FROM heal_cast WHERE rowid IN (SELECT a.rowid FROM heal_cast a JOIN heal_cast b
  ON a.report=b.report AND a.fight_id=b.fight_id AND a.actor_id=b.actor_id AND a.ability_id=b.ability_id
  WHERE a.on_other=0 AND b.on_other=1 AND abs(a.t-b.t)<={TWIN})"""


def ensure_tables(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    if "delay" not in {r[1] for r in con.execute("PRAGMA table_info(heal_dispel_time)")}:  # 0.8.18's first try
        con.execute("ALTER TABLE heal_dispel_time ADD COLUMN delay REAL")
    con.execute(HEAL_TWINS)


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
            casts = [c for x in rows for c in without_twins(client.events(  # one healer at a time: WCL's
                rep, fid, fr["startTime"], fr["endTime"], data_type="Casts", hostility="Friendlies",
                source_id=x[0], cache=False), x[0])]  # source.id filter returns nothing
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


DISPEL_KILLS = KILLS  # the same kills as the rest of the comparison (~1 page of events each)


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
        removed = [ev for ev in events if ev.get("type") in ("dispel", "removedebuff") and ev.get("extraAbilityGameID")]
        counts = Counter(ev["extraAbilityGameID"] for ev in removed)
        landed: dict[tuple[int, int], list[float]] = defaultdict(list)  # (debuff, player) -> when it landed
        try:  # the debuff they remove the most: when it landed on each player, for how long they wait to dispel
            for aura, _n in counts.most_common(1):
                for ev in client.events(rep, fid, fr["startTime"], fr["endTime"], data_type="Debuffs",
                                        ability_id=aura, filter_expression="type='applydebuff'", cache=False):
                    landed[(aura, ev.get("targetID"))].append(ev["timestamp"])
        except (WCLError, KeyError, TypeError, OSError) as e:
            log(f"  dispel timing skipped: {str(e)[:100]}")

        def delay(ev, landed=landed) -> float | None:
            before = [ev["timestamp"] - t for t in landed.get((ev["extraAbilityGameID"], ev.get("targetID")), [])
                      if 0 <= ev["timestamp"] - t <= 60000]
            return round(min(before) / 1000, 1) if before else None
        con.executemany("INSERT INTO heal_dispel VALUES(?,?,?,?)", [(rep, fid, a, n) for a, n in counts.items()])
        con.executemany("INSERT INTO heal_dispel_time VALUES(?,?,?,?,?)", [
            (rep, fid, ev["extraAbilityGameID"], round((ev["timestamp"] - fr["startTime"]) / 1000, 1), delay(ev))
            for ev in removed])
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


def dispel_delay(con: sqlite3.Connection, encounter_id: int, difficulty: int, aura: str,
                 names: dict[int, str]) -> tuple[float, int] | None:
    """(median seconds, dispels measured) between the debuff landing on a player and the top healer removing it
    from that player: when they dispel, which the player needs before what the dispel sets off. None: too few."""
    ensure_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    ids = {i for i, n in names.items() if n == aura}
    delays = [d for ab, d in con.execute(f"SELECT d.aura_id, d.delay FROM heal_dispel_time d JOIN fight f "
                                         f"USING(report, fight_id) WHERE {where} AND d.delay IS NOT NULL", params)
              if ab in ids]
    return (st.median(delays), len(delays)) if len(delays) >= 5 else None


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
        return " + ".join(f"{n} {s}s" if n > 1 else s for s, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))


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
    raid_cds: float  # long cooldowns cast on themselves, the raid or an enemy, per kill
    externals: float  # protective long cooldowns cast on another player (paf.gamedata.external_kind), per kill
    cd_names: list[tuple[str, float, list]] = field(default_factory=list)  # (spell, per kill, its moments)
    jobs: list[str] = field(default_factory=list)  # what the numbers say this spec does on this boss
    se: dict[str, float] = field(default_factory=dict)  # standard error of each number (its healers' spread)
    buffs: float = 0.0  # damage buffs cast on another player (Power Infusion), per kill
    buff_spells: list[str] = field(default_factory=list)  # their names, the most cast first


TANK_HEALER = 1.4  # a spec puts this many times the other healers' tank share on the tanks: the tank healer
TANK_FLOOR = 0.12  # ... and at least this share: a tank's sources are its top healers only (a lower bound), and
# every healer measured on three bosses puts 4 to 10% on them
SPIKE_HEALER = 1.25  # ... of the share in spikes: the burst healer
DISPELLER = 2.0  # ... of the dispels: the dispeller


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
    # a long cooldown as the players press it, not its base cooldown: Holy Word: Serenity is 60 s on paper and cast
    # 7.8 times a minute (Holy Words cut it); a spell the median player of a spec casts more than LONG_RATE a minute
    # is part of the rotation
    rates: dict[tuple[str, int], list[float]] = defaultdict(list)
    for key, cs in casts.items():
        minutes = (durs.get(key[:2]) or 60) / 60
        for ab, n in Counter(ab for ab, _t, _o in cs).items():
            rates[(spec_of.get(key, ""), ab)].append(n / minutes)
    rotation = {k for k, v in rates.items() if st.median(v) > LONG_RATE}
    # cast on another unit is not an external yet: the boss (Touch of Death), a dead player (a battle res)...
    kind = {ab: external_kind(ab) for ab in users}
    buff_casts: dict[str, Counter] = defaultdict(Counter)
    stats: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    cd_times: dict[str, dict[int, list[list[float]]]] = defaultdict(lambda: defaultdict(list))  # per player-kill
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
            mine = [c for c in casts.get((k[0], k[1], h[2]), []) if c[0] not in common and (spec, c[0]) not in rotation]
            s["raid"].append(sum(1 for a, _t, o in mine if not (o and kind[a])))
            s["ext"].append(sum(1 for a, _t, o in mine if o and kind[a] == "protective"))
            s["buff"].append(sum(1 for a, _t, o in mine if o and kind[a] == "damage"))
            buff_casts[spec].update(a for a, _t, o in mine if o and kind[a] == "damage")
            own: dict[int, list[float]] = defaultdict(list)
            for ab, t, _o in mine:
                own[ab].append(t)
            for ab, ts in own.items():
                cd_times[spec][ab].append(ts)
    out = []
    for spec, s in stats.items():
        n = len(s["healing"])
        if n < min_players:
            continue
        mid = st.median(durs.values()) if durs else None
        cds = [((names or {}).get(ab, f"spell {ab}"), sum(map(len, ps)) / n,
                press_moments(ps, max(1, round(sum(map(len, ps)) / len(ps))), mid)[0])
               for ab, ps in cd_times[spec].items() if sum(map(len, ps)) / n >= 0.5]
        se = {k: (st.stdev(v) / len(v) ** 0.5 if len(v) > 1 else 0.0) for k, v in s.items()}
        out.append(Role(spec, n, st.median(s["healing"]), st.median(s["tank"]), st.median(s["spike"]),
                        st.median(s["overheal"]), st.median(s["dispels"]), st.mean(s["raid"]), st.mean(s["ext"]),
                        sorted(cds, key=lambda c: -c[1]),
                        se={"tank": se["tank"], "spike": se["spike"], "overheal": se["overheal"],
                            "dispels": se["dispels"], "raid_cds": se["raid"], "externals": se["ext"]},
                        buffs=st.mean(s["buff"]),
                        buff_spells=[(names or {}).get(ab, f"spell {ab}") for ab, _ in buff_casts[spec].most_common()]))
    for r in out:
        r.jobs = jobs(r, out)
    return sorted(out, key=lambda r: -r.players)


def press_moments(per_player: list[list[float]], keep: int, end: float | None = None
                  ) -> tuple[list[float], list[float]]:
    """(the moments most top players press a cooldown at, other moments some press it at): the shared clusters of
    their casts (paf.defensives.ranked_peaks, the best followed first), as many as their casts a kill. Two moments
    closer than one player ever presses it twice (the 10th percentile of their own gaps) are two habits, not one
    plan (Avenging Wrath "0:21, 0:41"): the second goes with the other habits; nothing after the kill's median end."""
    from itertools import pairwise

    from paf.defensives import ranked_peaks

    lists = [sorted(ts) for ts in per_player if ts]
    if not lists:
        return [], []
    gaps = sorted(y - x for ts in lists for x, y in pairwise(ts))
    gap = gaps[len(gaps) // 10] * 0.9 if gaps else 0.0
    times: list[float] = []
    alt: list[float] = []
    for t, _n in ranked_peaks(lists):
        if end is not None and t > end:
            continue
        if len(times) < keep and all(abs(t - x) >= gap for x in times):
            times.append(t)
        else:
            alt.append(t)
    return sorted(times), sorted(alt)


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
    # not jobs: the count of long cooldowns compares kits, not what the boss asks; low overheal is the spec's trait
    # on every boss (Restoration Shaman on 14 of 14 sheets). Both stay in the card's numbers.
    # a damage dealer's buff (Power Infusion) is no healing job of the boss: the card's numbers say it
    if not out:
        out.append("nothing stands out against the other healers")
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
