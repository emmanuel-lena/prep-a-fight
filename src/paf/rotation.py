"""Rotation review, generic for every spec (issue #14): what a player's own log says about their rotation, with no
analyzer written per spec.

From one pull of the log (the player's casts with their main resource, their buffs, the debuffs they put on enemies):
- DoTs refreshed too early: for each debuff the player puts with a spell they cast (same name), its duration (game
  data, else the 90th percentile of its applications that ended in the log: adds dying shorten the others), and a
  refresh made by casting that spell on that target (within 0.3 s: not by another spell, like Seed of Corruption
  spreading Corruption) with more than 30% of it left (past the pandemic window) wastes part of the previous one;
  also its uptime on the target it was on the most;
- resource wasted: each ability is a builder or a spender from the player's resource before and after its casts (the
  next cast's reading); a builder cast at 95% or more of the maximum wastes what it builds;
- cooldowns: for each spell of the spec's default APL (paf.apl: utility and defensives left out) with a cooldown of
  30 s or more (game data, shortened to the shortest gap the player left between two casts when talents shorten it)
  and its charges, the casts the pull allowed against the casts made.
- the contexts: the pull cut into 5 s windows by the number of enemies the player hit (each enemy taking 5% or more
  of their damage in the window; adds of one kind told apart by their instance): single target (1), cleave (2-3), AoE
  (4+). In each, the share of the player's casts that goes to each spell of the APL (a share: movement and
  mechanics lower every spell's casts per minute alike), next to SimulationCraft's: their own character (gear and
  talents of that pull, paf.validate.profile_from_log) with the default APL on 1, 3 and 5 targets.
- buffs: the uptime of each of the player's buffs and procs next to the top players' of the spec on this boss (their
  median, from the corpus's buff events), when the corpus of the spec has this boss; matched by spell id.
Each finding comes with its numbers: a reading, not a verdict (a strategy, an assignment or a movement can explain a
gap).
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

EVENTS = """query($c:String!,$f:[Int]!,$t:EventDataType!,$s:Int,$h:HostilityType,$x:String,$a:Float,$e:Float){
  reportData { report(code:$c) { events(fightIDs:$f, dataType:$t, sourceID:$s, hostilityType:$h, filterExpression:$x,
    startTime:$a, endTime:$e, limit:10000, includeResources:true) { data nextPageTimestamp } } } }"""
DETAILS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) {
  playerDetails(fightIDs:$f, includeCombatantInfo:true) } } }"""
IMPORT = """query($c:String!,$f:[Int]!,$a:Int!){ reportData { report(code:$c) {
  fights(fightIDs:$f) { talentImportCode(actorID:$a) } } } }"""
ABILITIES = """query($c:String!){ reportData { report(code:$c) { masterData { abilities { gameID name } } } } }"""

PANDEMIC = 0.3
CAP = 0.95
MIN_COOLDOWN = 30.0  # seconds: shorter ones are the rotation, not cooldowns
MIN_REFRESHES = 4
WINDOW = 5.0  # seconds, for the contexts
CONTEXTS = (("st", "Single target", 1, 1), ("cleave", "Cleave (2-3 targets)", 2, 3), ("aoe", "AoE (4+ targets)", 4, 99))
SIM_TARGETS = {"st": 1, "cleave": 3, "aoe": 5}
RESOURCES = {0: "mana", 1: "rage", 2: "focus", 3: "energy", 4: "combo points", 5: "runes", 6: "runic power",
             7: "soul shards", 8: "astral power", 9: "holy power", 11: "maelstrom", 12: "chi", 13: "insanity",
             17: "fury", 18: "pain", 19: "essence"}


@dataclass
class Cast:
    t: float
    ability: int
    resource: tuple[int, float, float] | None  # (type, amount, max) before the cast
    target: int = 0  # actor id x 1000 + instance: adds of one kind share their actor id


@dataclass
class Log:
    duration: float
    casts: list[Cast]
    debuffs: list[tuple[float, str, int, int]]  # (t, type, ability, target)
    names: dict[int, str]


@dataclass
class DotFinding:
    name: str
    duration: float
    refreshes: int
    early: int  # refreshed with more than the pandemic window left
    median_left: float  # seconds left at a refresh
    uptime: float  # on the target it was on the most


@dataclass
class WasteFinding:
    resource: str
    builder: str
    casts: int
    capped: int  # cast at 95% of the maximum or more


@dataclass
class CooldownFinding:
    name: str
    cooldown: float
    charges: int
    casts: int
    possible: int
    times: list[float]


@dataclass
class ContextRow:
    name: str
    player: float  # share of the player's casts in that context
    sim: float  # SimulationCraft's, same character, same number of targets
    per_min: float = 0.0  # the player's casts per minute there


@dataclass
class Context:
    key: str  # st | cleave | aoe
    label: str
    seconds: float
    rows: list[ContextRow] = field(default_factory=list)


@dataclass
class BuffRow:
    name: str
    player: float  # uptime share of the pull
    tops: float  # median of the top players of the spec on this boss


@dataclass
class Review:
    player: str
    spec: str
    pull: str
    duration: float
    dots: list[DotFinding] = field(default_factory=list)
    waste: list[WasteFinding] = field(default_factory=list)
    cooldowns: list[CooldownFinding] = field(default_factory=list)
    contexts: list[Context] = field(default_factory=list)
    buffs: list[BuffRow] = field(default_factory=list)


def _events(client, code: str, fight: dict, kind: str, **ids) -> list[dict]:
    out, start = [], fight["startTime"]
    while start is not None:
        ev = client.query(EVENTS, {"c": code, "f": [fight["id"]], "t": kind, "a": start, "e": fight["endTime"], **ids},
                          cache_ttl=86400)["reportData"]["report"]["events"]
        out += ev.get("data") or []
        start = ev.get("nextPageTimestamp")
    return out


def fetch(client, code: str, fight: dict, actor_id: int, actor_name: str) -> Log:
    t0 = fight["startTime"]
    casts = []
    for e in _events(client, code, fight, "Casts", s=actor_id):
        if e.get("type") != "cast" or e.get("sourceID") != actor_id:
            continue
        res = next((r for r in e.get("classResources") or [] if r.get("type") != 0), None) or \
            next(iter(e.get("classResources") or []), None)
        casts.append(Cast((e["timestamp"] - t0) / 1000, e["abilityGameID"],
                          (res["type"], float(res["amount"]), float(res["max"])) if res and res.get("max") else None,
                          e.get("targetID", 0) * 1000 + (e.get("targetInstance") or 0)))
    debuffs = [((e["timestamp"] - t0) / 1000, e["type"], e["abilityGameID"],
                e.get("targetID", 0) * 1000 + (e.get("targetInstance") or 0))
               for e in _events(client, code, fight, "Debuffs", h="Enemies",
                                x="source.name = '" + actor_name.replace("'", "\\'") + "'")
               if e.get("sourceID") == actor_id]
    names = {a["gameID"]: a["name"] for a in client.query(ABILITIES, {"c": code}, cache_ttl=86400)[
        "reportData"]["report"]["masterData"]["abilities"] or []}
    return Log((fight["endTime"] - t0) / 1000, casts, debuffs, names)


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def dots(log: Log, base: dict[int, float] | None = None) -> list[DotFinding]:
    """base: spell id -> base duration (paf.gamedata.spell_durations)."""
    cast_names = {_norm(log.names.get(c.ability, "")) for c in log.casts}
    cast_times: dict[tuple[str, int], list[float]] = defaultdict(list)  # (spell, target) -> cast times
    for c in log.casts:
        cast_times[(_norm(log.names.get(c.ability, "")), c.target)].append(c.t)
    by: dict[tuple[int, int], list[tuple[float, str]]] = defaultdict(list)
    for t, kind, ability, target in sorted(log.debuffs):
        by[(ability, target)].append((t, kind))
    out = []
    for ability in {a for a, _ in by}:
        name = log.names.get(ability, "")
        if _norm(name) not in cast_names:  # put by a proc or a talent, not by a spell the player casts
            continue
        natural = []  # application or refresh -> removal, with no refresh in between
        for (ab, _), evs in by.items():
            if ab != ability:
                continue
            last = None
            for t, kind in evs:
                if kind in ("applydebuff", "refreshdebuff"):
                    last = (t, kind)
                elif kind == "removedebuff" and last and last[1] == "applydebuff":
                    natural.append(t - last[0])
                    last = None
        natural = sorted(x for x in natural if x >= 3)
        duration = (base or {}).get(ability) or (natural[int(len(natural) * 0.9)] if len(natural) >= 3 else 0.0)
        if duration < 3:
            continue

        lefts, uptimes = [], {}
        for (ab, target), evs in by.items():
            if ab != ability:
                continue
            end, up, start = None, 0.0, None
            for t, kind in evs:
                if kind == "applydebuff":
                    end, start = t + duration, t
                elif kind == "refreshdebuff" and end is not None:
                    left = max(0.0, end - t)
                    if any(abs(t - x) <= 0.3 for x in cast_times[(_norm(name), target)]):  # by casting it on it
                        lefts.append(left)
                    end = t + min(duration + left, duration * (1 + PANDEMIC))
                elif kind == "removedebuff" and start is not None:
                    up += t - start
                    end = start = None
            if start is not None:
                up += min(log.duration, end or log.duration) - start
            uptimes[target] = up / log.duration if log.duration else 0.0
        if len(lefts) < MIN_REFRESHES:
            continue
        early = sum(left > PANDEMIC * duration + 0.5 for left in lefts)
        out.append(DotFinding(name, duration, len(lefts), early, st.median(lefts), max(uptimes.values(), default=0.0)))
    return sorted(out, key=lambda d: -d.early / d.refreshes)


def waste(log: Log) -> list[WasteFinding]:
    """Builders cast at the resource's cap."""
    change: dict[int, list[float]] = defaultdict(list)
    for c, nxt in zip(log.casts, log.casts[1:], strict=False):
        if c.resource and nxt.resource and c.resource[0] == nxt.resource[0] and nxt.t - c.t < 3:
            change[c.ability].append(nxt.resource[1] - c.resource[1])
    builders = {a for a, v in change.items() if len(v) >= 5 and st.median(v) > 0}
    out: dict[int, WasteFinding] = {}
    for c in log.casts:
        if c.ability in builders and c.resource and c.resource[0] != 0:
            f = out.setdefault(c.ability, WasteFinding(RESOURCES.get(c.resource[0], "resource"),
                                                       log.names.get(c.ability, str(c.ability)), 0, 0))
            f.casts += 1
            f.capped += c.resource[1] >= CAP * c.resource[2]
    return sorted((f for f in out.values() if f.casts >= 5), key=lambda f: -f.capped / f.casts)


def cooldowns(log: Log, base: dict[int, tuple[float, int]], rotation: set[str] | None = None
              ) -> list[CooldownFinding]:
    """base: ability -> (cooldown in s, charges) from the game data (paf.gamedata.spell_cooldowns); rotation: the
    spells of the spec's default APL (paf.apl.spells): the others are utility or defensives, left out."""
    times: dict[int, list[float]] = defaultdict(list)
    for c in log.casts:
        times[c.ability].append(c.t)
    out = []
    for ability, ts in times.items():
        if ability not in base or (rotation and _norm(log.names.get(ability, "")) not in rotation):
            continue
        cd, charges = base[ability]
        gaps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
        if charges <= 1 and len(gaps) >= 2:
            cd = min(cd, min(gaps))  # a talent shortens it: the player's shortest gap shows how much
        if cd < MIN_COOLDOWN:
            continue
        possible = charges + int(max(0.0, log.duration - 1) // cd)
        out.append(CooldownFinding(log.names.get(ability, str(ability)), cd, charges, len(ts), possible, ts))
    return sorted(out, key=lambda f: -(f.possible - f.casts) / f.possible)


def targets_per_window(client, code: str, fight: dict, actor_id: int) -> list[int]:
    """Enemies the player hit in each 5 s window (taking 5% or more of their damage there)."""
    t0 = fight["startTime"]
    n = int((fight["endTime"] - t0) / 1000 // WINDOW) + 1
    hits: list[dict[int, float]] = [defaultdict(float) for _ in range(n)]
    for e in _events(client, code, fight, "DamageDone", s=actor_id):
        if e.get("sourceID") != actor_id or e.get("type") != "damage" or e.get("targetIsFriendly"):
            continue
        w = int((e["timestamp"] - t0) / 1000 // WINDOW)
        if 0 <= w < n:
            hits[w][e.get("targetID", 0) * 1000 + (e.get("targetInstance") or 0)] += e.get("amount", 0) or 0
    return [sum(v >= 0.05 * sum(h.values()) for v in h.values()) if h else 0 for h in hits]


def context_of(count: int) -> str:
    return next((key for key, _, lo, hi in CONTEXTS if lo <= count <= hi), "")


def player_details(client, code: str, fight: dict, actor_id: int) -> dict | None:
    """Warcraft Logs' details of the player in that pull: type (class), specs, combatantInfo (gear, talents, stats)."""
    data = client.query(DETAILS, {"c": code, "f": [fight["id"]]}, cache_ttl=86400)["reportData"]["report"]
    pd = data.get("playerDetails") or {}
    pd = (pd.get("data") or pd).get("playerDetails") or pd if isinstance(pd, dict) else {}
    return next((x for role in ("dps", "healers", "tanks") for x in pd.get(role) or [] if x.get("id") == actor_id),
                None)


def spec_of(me: dict | None) -> tuple[str, str]:
    """(class, spec) as Warcraft Logs writes them ("Rogue", "Assassination")."""
    me = me or {}
    spec = ((me.get("specs") or [{}])[0].get("spec") or (me.get("icon") or "-").partition("-")[2]).replace(" ", "")
    return me.get("type") or "", spec


def profile_from_pull(client, code: str, fight: dict, actor: dict) -> str | None:
    """The player's SimulationCraft profile from that pull: gear, talents, secondary stats (as paf.character)."""
    from paf.validate import STAT_OPTIONS, profile_from_log

    me = player_details(client, code, fight, actor["id"])
    info = (me or {}).get("combatantInfo") or {}
    if not me or not info.get("gear"):
        return None
    spec = spec_of(me)[1]
    fights = client.query(IMPORT, {"c": code, "f": [fight["id"]], "a": actor["id"]},
                          cache_ttl=86400)["reportData"]["report"]["fights"] or []
    talents = fights[0].get("talentImportCode") if fights else None
    if not spec or not talents:
        return None
    profile = profile_from_log(actor["name"], me.get("type") or "", spec, "human", talents, info["gear"])
    stats = info.get("stats") or {}
    return profile + "".join(f"{opt}={int(stats[k]['max'])}\n" for k, opt in STAT_OPTIONS.items()
                             if (stats.get(k) or {}).get("max"))


def sim_casts(profile: str, targets: int, run_dir) -> dict[str, tuple[str, float]]:
    """Normalized name -> (name, casts per minute) of each spell of the character with the default APL on `targets`
    targets."""
    from paf import simc

    r = simc.run(simc.build_input(profile, ["fight_style=Patchwerk", f"desired_targets={targets}", "max_time=180"]),
                 run_dir, target_error=0.5)
    player = (r.raw.get("sim", {}).get("players") or [{}])[0]
    minutes = ((player.get("collected_data") or {}).get("fight_length") or {}).get("mean", 180) / 60
    out: dict[str, tuple[str, float]] = {}
    for st_ in player.get("stats") or []:
        n = (st_.get("num_executes") or {}).get("mean") or 0
        name = st_.get("spell_name") or st_.get("name") or ""
        if n:
            k = _norm(name)
            out[k] = (out.get(k, (name, 0.0))[0], out.get(k, (name, 0.0))[1] + n / minutes)
    return out


def contexts(log: Log, windows: list[int], sims: dict[str, dict[str, tuple[str, float]]], rotation: set[str]
             ) -> list[Context]:
    """Per context, the share of the player's casts on each spell of the APL next to the sim's."""
    out = []
    for key, label, _, _ in CONTEXTS:
        ws = {w for w, n in enumerate(windows) if context_of(n) == key}
        seconds = len(ws) * WINDOW
        if seconds < 20 or key not in sims:
            continue
        counts: dict[str, int] = defaultdict(int)
        shown: dict[str, str] = {}
        for c in log.casts:
            name = log.names.get(c.ability, "")
            if int(c.t // WINDOW) in ws and _norm(name) in rotation:
                counts[_norm(name)] += 1
                shown[_norm(name)] = name
        sim = {k: v for k, v in sims[key].items() if k in rotation}
        total, sim_total = sum(counts.values()) or 1, sum(v for _, v in sim.values()) or 1
        rows = [ContextRow(shown.get(k) or sim.get(k, (k, 0))[0], counts.get(k, 0) / total,
                           sim.get(k, ("", 0.0))[1] / sim_total, counts.get(k, 0) / (seconds / 60))
                for k in set(counts) | set(sim)]
        rows = [r for r in rows if max(r.player, r.sim) >= 0.02]
        out.append(Context(key, label, seconds, sorted(rows, key=lambda r: -abs(r.player - r.sim))))
    return out


BUFF_GAP = 0.10  # uptime points
BUFF_PRESENT = 0.5  # a buff the top players have in at least this share of the kills (else a talent of some)


def tops_buffs(con, encounter_id: int, difficulty: int) -> dict[int, tuple[str, float]]:
    """Spell id -> (name, median uptime) of the buffs of the corpus's ranked players on this boss, for the buffs most
    of them have (a buff from a talent few take is left out)."""
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    dur = {(r[0], r[1]): r[2] for r in con.execute(f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}",
                                                   params)}
    names = {r[0]: r[1] for r in con.execute("SELECT id, name FROM ability")}
    up: dict[int, dict[tuple[str, int], float]] = defaultdict(lambda: defaultdict(float))
    since: dict[tuple[str, int, int], float] = {}
    for rep, fid, ab, kind, t in con.execute(
            f"SELECT b.report, b.fight_id, b.ability_id, b.type, b.t FROM player_buff b JOIN fight f "
            f"USING(report, fight_id) WHERE {where} ORDER BY b.report, b.fight_id, b.t", params):
        key = (rep, fid, ab)
        if kind == "applybuff":
            since[key] = t
        elif kind == "removebuff" and key in since:
            up[ab][(rep, fid)] += t - since.pop(key)
    for (rep, fid, ab), t in since.items():  # still up at the end of the kill
        up[ab][(rep, fid)] += max(0.0, dur.get((rep, fid), t) - t)
    kills = len(dur) or 1
    out = {}
    for ab, per in up.items():
        if len(per) / kills < BUFF_PRESENT:
            continue
        shares = [v / dur[k] for k, v in per.items() if dur.get(k)]
        if shares:
            out[ab] = (names.get(ab) or str(ab), st.median(shares))
    return out


def buff_rows(player: dict[int, tuple[str, float]], tops: dict[int, tuple[str, float]]) -> list[BuffRow]:
    """The buffs whose uptime differs from the top players' (both ways), biggest gap first."""
    rows = [BuffRow(tops[ab][0], player.get(ab, ("", 0.0))[1], tops[ab][1]) for ab in tops]
    rows = [r for r in rows if abs(r.player - r.tops) >= BUFF_GAP and max(r.player, r.tops) >= 0.2]
    return sorted(rows, key=lambda r: -abs(r.player - r.tops))


def review(log: Log, player: str, spec: str, pull: str, base: dict[int, tuple[float, int]],
           durations: dict[int, float] | None = None, rotation: set[str] | None = None) -> Review:
    return Review(player, spec, pull, log.duration, dots(log, durations), waste(log),
                  cooldowns(log, base, rotation))


GAP = 0.08  # a spell's share of casts this far from the rotation's
EARLY = 0.3  # share of refreshes made too early
CAPPED = 0.1


def rotation_like(r: Review) -> set[str]:
    """Spells the player casts about as often as the rotation does: their early refreshes are the rotation's own
    (some spells are meant to be cast again before the window), not a fault."""
    return {_norm(x.name) for c in r.contexts for x in c.rows if x.player <= x.sim * 1.25}


def highlights(r: Review, limit: int = 5) -> list[tuple[float, str]]:
    """The points to work on, biggest first: (weight, sentence)."""
    out: list[tuple[float, str]] = []
    for c in r.contexts:
        weight = c.seconds / (r.duration or 1)
        for x in c.rows:
            if abs(x.player - x.sim) >= GAP:
                more = "more" if x.player > x.sim else "less"
                out.append((abs(x.player - x.sim) * weight * 2, f"{c.label}: {x.name} is {x.player:.0%} of your casts, "
                                                                 f"{x.sim:.0%} in the rotation ({more} than it)."))
    as_often = rotation_like(r)
    for d in r.dots:
        if d.refreshes and d.early / d.refreshes >= EARLY and _norm(d.name) not in as_often:
            out.append((d.early / d.refreshes * 0.3, f"{d.name} refreshed too early {d.early} times out of "
                                                     f"{d.refreshes} (median {d.median_left:.1f} s left; refresh "
                                                     f"under {PANDEMIC * d.duration:.1f} s)."))
    for c in r.cooldowns:
        if c.possible - c.casts >= 1 and c.casts < c.possible:
            out.append(((c.possible - c.casts) / c.possible * 0.5, f"{c.name}: {c.casts} casts, {c.possible} possible "
                                                                     f"in the pull."))
    for b in r.buffs[:3]:
        if b.player < b.tops - 0.15:
            out.append(((b.tops - b.player) * 0.8, f"{b.name}: up {b.player:.0%} of the pull, {b.tops:.0%} for the top "
                                                   f"players of your spec on this boss."))
    for w in r.waste:
        if w.casts and w.capped / w.casts >= CAPPED:
            out.append((w.capped / w.casts * 0.3, f"{w.builder} cast at full {w.resource} {w.capped} times out of "
                                                   f"{w.casts}: what it builds is lost."))
    return sorted(out, key=lambda x: -x[0])[:limit]


def to_dict(r: Review) -> dict:
    return {"player": r.player, "spec": r.spec, "pull": r.pull, "duration": r.duration,
            "highlights": [t for _, t in highlights(r)],
            "dots": [dict(vars(d), like_rotation=_norm(d.name) in rotation_like(r)) for d in r.dots],
            "waste": [vars(w) for w in r.waste],
            "cooldowns": [vars(c) for c in r.cooldowns],
            "contexts": [{"key": c.key, "label": c.label, "seconds": c.seconds, "rows": [vars(x) for x in c.rows]}
                         for c in r.contexts],
            "buffs": [vars(b) for b in r.buffs]}
