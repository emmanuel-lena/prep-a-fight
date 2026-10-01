"""Your raid and the adds: should you pad them or leave them to the others and stay on the boss?

1. Measured: on this boss, every spec puts a share of its damage on each add type while they are up (its
   "focus": Balance Druids and Devastation Evokers much more than single-target specs), from the ranked kills.
2. Computed: your raid's capacity on the adds = for every player of one of your raid's logs, their DPS x their
   spec's focus; the same sum for every top raid of the corpus gives the reference range.
3. Rule (not a measurement): if your raid without you (all your damage on the boss) is within the top raids'
   range (above their weakest quarter), the others cover the adds: stay on the boss. Otherwise pad, and if
   even with you it stays below, the raid lacks cleave.

What the data does NOT support (checked on Ula'tek and Nek'zali, ~200 kills each): predicting how long the
adds live from the composition or the raid's DPS (correlation ~0). In the top kills, add lifetimes are set
by the mechanics and the strategy, so no lifetime is promised here. Top players are ranked on their own DPS,
add damage included, so they pad whatever their raid: their logs cannot tell what *your* raid needs.
"""

from __future__ import annotations

import re
import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import kills_filter

MIN_DAMAGE_SHARE = 0.02  # an add type must take this share of the raid's damage to matter
ONLY_TARGET_FOCUS = 0.6  # most specs put more than this on it while it is up: it is the only target then


@dataclass
class AddType:
    name: str
    kills: int
    lifetime: float  # median lifetime in the top kills (s)
    damage_share: float  # share of the raid's damage that goes to this add type
    focus: dict[str, float]  # "Spec Class" -> median share of their DPS on this add type while it is up
    default_focus: float
    tops_rate: float  # median raid DPS on this add type in the top kills, from the composition
    tops_low: float = 0.0  # the top raids' weakest quarter (25th percentile of the same)
    estimated: set[str] = field(default_factory=set)  # specs whose focus comes from the rankings, not the corpus

    def rate(self, comp: list[tuple[str, float]]) -> float:
        return sum(dps * self.focus.get(spec, self.default_focus) for spec, dps in comp)


def _union(ws: list[tuple[float, float]]) -> float:
    tot, cur = 0.0, None
    for a, b in sorted(ws):
        if cur and a <= cur[1]:
            cur[1] = max(cur[1], b)
        else:
            if cur:
                tot += cur[1] - cur[0]
            cur = [a, b]
    return tot + (cur[1] - cur[0] if cur else 0.0)


def add_types(con: sqlite3.Connection, encounter_id: int, difficulty: int) -> list[AddType]:
    """The add types that matter on this boss, with each spec's focus on them (from the corpus)."""
    where, params = kills_filter(encounter_id, difficulty, include_focus=True)
    durations = {(r[0], r[1]): r[2] for r in con.execute(
        f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}", params)}
    damage = defaultdict(float)
    for target, amount in con.execute(
            f"SELECT d.target, SUM(d.amount) FROM damage_by_target d JOIN fight f USING(report, fight_id) "
            f"WHERE {where} GROUP BY d.target", params):
        damage[target] += amount or 0
    total = sum(damage.values()) or 1
    windows: dict[tuple[str, int, str], list[tuple[float, float]]] = defaultdict(list)
    died: dict[str, list[int]] = defaultdict(list)
    for rep, fid, name, t0, t1, dead in con.execute(
            f"SELECT a.report, a.fight_id, n.name, a.t_spawn, a.t_death, a.died FROM add_instance a "
            f"JOIN npc n USING(game_id) JOIN fight f USING(report, fight_id) WHERE {where} AND n.is_boss=0", params):
        died[name].append(dead)
        if dead and t0 is not None and t1 is not None and t1 > t0:
            windows[(rep, fid, name)].append((t0, t1))
    names = [n for n, d in died.items() if sum(d) / len(d) >= 0.8 and damage.get(n, 0) / total >= MIN_DAMAGE_SHARE]
    if not names:
        return []
    players: dict[tuple[str, int], list[tuple[int, str, float]]] = defaultdict(list)
    for rep, fid, actor, cls, spec, tot in con.execute(
            f"SELECT p.report, p.fight_id, p.actor_id, p.class, p.spec, p.total_damage FROM player p "
            f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        players[(rep, fid)].append((actor, f"{spec} {cls}", tot or 0))
    on: dict[tuple[str, int, int, str], float] = defaultdict(float)
    for rep, fid, actor, target, amount in con.execute(
            f"SELECT d.report, d.fight_id, d.actor_id, d.target, d.amount FROM damage_by_target d "
            f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        if target in names:
            on[(rep, fid, actor, target)] += amount or 0
    out = []
    for name in names:
        focus: dict[str, list[float]] = defaultdict(list)
        per_kill = []
        for (rep, fid, nm), ws in windows.items():
            dur = durations.get((rep, fid))
            if nm != name or not dur:
                continue
            up = _union(ws)
            if up < 5:
                continue
            comp = []
            for actor, spec, tot in players[(rep, fid)]:
                dps = tot / dur
                if dps > 0:
                    focus[spec].append(min(1.0, on[(rep, fid, actor, name)] / (dps * up)))
                    comp.append((spec, dps))
            per_kill.append((st.median(b - a for a, b in ws), comp))
        if len(per_kill) < 10:
            continue
        typical = {s: st.median(v) for s, v in focus.items() if len(v) >= 15}
        default = st.median(f for v in focus.values() for f in v)
        if default > ONLY_TARGET_FOCUS:  # everyone is on it: the only target at that time, not a choice
            continue
        t = AddType(name, len(per_kill), st.median(k[0] for k in per_kill), damage[name] / total, typical, default, 0)
        rates = sorted(t.rate(comp) for _, comp in per_kill)
        t.tops_rate, t.tops_low = st.median(rates), rates[len(rates) // 4]
        out.append(t)
    return sorted(out, key=lambda x: -x.damage_share)


# --- your raid -------------------------------------------------------------------------------------

REPORT_RE = re.compile(r"(?:reports/)?([A-Za-z0-9]{16})")
FIGHTS_QUERY = """query($code:String!){ reportData { report(code:$code) {
  fights(killType: Encounters) { id encounterID difficulty kill startTime endTime } } } }"""
TABLE_QUERY = """query($code:String!,$f:[Int]!){ reportData { report(code:$code) {
  table(dataType: DamageDone, fightIDs: $f) } } }"""


@dataclass
class RaidComp:
    report: str
    fight: str  # which fight the DPS were read on
    players: list[tuple[str, str, float]] = field(default_factory=list)  # name, "Spec Class", DPS


def report_code(url: str) -> str:
    m = REPORT_RE.search(url.strip())
    if not m:
        raise ValueError(f"not a Warcraft Logs report link: {url!r}")
    return m.group(1)


def raid_from_report(client, url: str, encounter_id: int, difficulty: int) -> RaidComp:
    """Composition and DPS of your raid from one of its logs: this boss at this difficulty if the log has it
    (a kill first, else the longest pull), else this boss at another difficulty, else the longest boss pull."""
    code = report_code(url)
    rep = client.query(FIGHTS_QUERY, {"code": code}, cache_ttl=3600)["reportData"]["report"]
    fights = [f for f in (rep or {}).get("fights") or [] if f["endTime"] > f["startTime"]]
    if not fights:
        raise ValueError("this log has no boss pull")

    def key(f):
        return (f["encounterID"] == encounter_id, f["difficulty"] == difficulty, bool(f["kill"]),
                f["endTime"] - f["startTime"])

    f = max(fights, key=key)
    dur = (f["endTime"] - f["startTime"]) / 1000
    data = client.query(TABLE_QUERY, {"code": code, "f": [f["id"]]}, cache_ttl=3600)["reportData"]["report"]["table"]
    data = data.get("data", data) if isinstance(data, dict) else {}
    players = []
    for e in data.get("entries") or []:
        icon = e.get("icon") or ""
        if "-" not in icon or not dur:
            continue
        cls, spec = icon.split("-", 1)
        players.append((e.get("name", "?"), f"{spec} {cls}", (e.get("total") or 0) / dur))
    what = "this boss" if f["encounterID"] == encounter_id else "another boss"
    return RaidComp(code, f"{what}, {'kill' if f['kill'] else 'pull'} of {int(dur // 60)}:{int(dur % 60):02d}",
                    players)


GUILD_REPORTS_QUERY = """query($name:String!,$server:String!,$region:String!){ reportData {
  reports(guildName:$name, guildServerSlug:$server, guildServerRegion:$region, limit:15) {
    data { code startTime } } } }"""


def server_slug(server: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", server.strip().lower().replace(" ", "-"))


def guild_report(client, name: str, server: str, region: str, encounter_id: int, difficulty: int) -> str:
    """The most recent public log of your guild with this boss (this difficulty first), else its latest log."""
    data = client.query(GUILD_REPORTS_QUERY, {"name": name, "server": server_slug(server), "region": region.upper()},
                        cache_ttl=1800)
    codes = [r["code"] for r in ((data["reportData"]["reports"] or {}).get("data") or [])]
    if not codes:
        raise ValueError(f"no public log found for the guild {name} ({server}-{region})")
    other = None
    for code in codes:  # newest first
        fights = (client.query(FIGHTS_QUERY, {"code": code}, cache_ttl=3600)["reportData"]["report"] or {}).get(
            "fights") or []
        if any(f["encounterID"] == encounter_id and f["difficulty"] == difficulty for f in fights):
            return code
        if other is None and any(f["encounterID"] == encounter_id for f in fights):
            other = code
    return other or codes[0]


@dataclass
class AddVerdict:
    add: AddType
    without_you: float  # your raid's capacity on these adds, you on the boss, as a share of the top raids' median
    with_you: float  # ... you on the adds too
    low: float  # the top raids' weakest quarter, same scale
    verdict: str  # "boss" or "pad"
    reason: str


def verdicts(types: list[AddType], comp: list[tuple[str, float]], you: tuple[str, float]) -> list[AddVerdict]:
    """comp: the other players (spec, DPS); you: your (spec, DPS)."""
    out = []
    for t in types:
        if t.tops_rate <= 0:
            continue
        others = t.rate(comp) / t.tops_rate
        with_you = (t.rate(comp) + you[1] * t.focus.get(you[0], t.default_focus)) / t.tops_rate
        low = t.tops_low / t.tops_rate
        if others >= low:
            v, why = "boss", (f"without you, your raid already puts {others:.0%} of the top raids' damage on them "
                              f"(their weakest quarter: {low:.0%}): the others cover them, stay on the boss")
        elif with_you >= low:
            v, why = "pad", (f"you make the difference: {others:.0%} of the top raids' damage on them without you, "
                             f"{with_you:.0%} with you (their weakest quarter: {low:.0%})")
        else:
            v, why = "pad", (f"even with you, your raid puts {with_you:.0%} of the top raids' damage on them (their "
                             f"weakest quarter: {low:.0%}): pad them, your raid lacks cleave")
        out.append(AddVerdict(t, others, with_you, low, v, why))
    return out


def overall(vs: list[AddVerdict]) -> str | None:
    """The objective for your cooldowns and gear: the verdict on the add type that weighs the most."""
    return vs[0].verdict if vs else None


# --- what each spec does with the adds, from Warcraft Logs' two rankings --------------------------------
# The top 100 of a spec by total DPS vs its top 100 by boss DPS: the gap is what padding adds at the top, for
# every spec (even the ones too rare in the corpus), and their talents show whether a "pad build" exists.

RANKING_QUERY = """query($id:Int!, $diff:Int!, $cls:String!, $spec:String!, $metric:CharacterRankingMetricType!) {
  worldData { encounter(id:$id) { characterRankings(className:$cls, specName:$spec, difficulty:$diff,
    metric:$metric, includeCombatantInfo:true) } } }"""
TALENT_GAP = 0.15  # a talent taken this much more often in one top 100 than in the other


@dataclass
class SpecProfile:
    spec: str  # "Spec Class"
    dps: float  # median of the top 100 by total DPS
    boss_dps: float  # median of the top 100 by boss DPS
    same_players: int  # players in both top 100
    pad_talents: list[str] = field(default_factory=list)  # taken more often by the total-DPS top
    boss_talents: list[str] = field(default_factory=list)  # taken more often by the boss-DPS top

    @property
    def boss_share(self) -> float:
        return self.boss_dps / self.dps if self.dps else 1.0


def spec_profile(client, encounter_id: int, difficulty: int, label: str,
                 talent_names: dict[int, str] | None = None) -> SpecProfile | None:
    spec, _, cls = label.rpartition(" ")
    lists = {}
    for metric in ("dps", "bossdps"):
        data = client.query(RANKING_QUERY, {"id": encounter_id, "diff": difficulty, "cls": cls, "spec": spec,
                                            "metric": metric}, cache_ttl=6 * 3600)
        cr = data["worldData"]["encounter"]["characterRankings"] or {}
        lists[metric] = [r for r in (cr.get("rankings") or []) if r.get("amount")]
    a, b = lists["dps"], lists["bossdps"]
    if len(a) < 10 or len(b) < 10:
        return None

    def who(r):
        return r.get("name"), (r.get("server") or {}).get("name")

    def picks(rows):
        c: dict[int, int] = defaultdict(int)
        for r in rows:
            for t in r.get("talents") or []:
                c[t.get("talentID")] += 1
        return c

    pa, pb = picks(a), picks(b)
    names = talent_names or {}
    gaps = [(pa[t] / len(a) - pb[t] / len(b), t) for t in set(pa) | set(pb)]
    p = SpecProfile(label, st.median(r["amount"] for r in a), st.median(r["amount"] for r in b),
                    len({who(r) for r in a} & {who(r) for r in b}))
    p.pad_talents = [names.get(t, f"talent {t}") for g, t in sorted(gaps, reverse=True) if g >= TALENT_GAP]
    p.boss_talents = [names.get(t, f"talent {t}") for g, t in sorted(gaps) if g <= -TALENT_GAP]
    return p


def spec_profiles(client, encounter_id: int, difficulty: int, labels: list[str]) -> dict[str, SpecProfile]:
    try:
        from paf.gamedata import talent_entry_names

        names = talent_entry_names()
    except Exception:  # noqa: BLE001 - names are a nicety; the numbers do not need them
        names = {}
    out = {}
    for label in sorted(set(labels)):
        if label in HEALERS:
            continue
        p = spec_profile(client, encounter_id, difficulty, label, names)
        if p:
            out[label] = p
    return out


def with_profiles(t: AddType, profiles: dict[str, SpecProfile]) -> AddType:
    """Fill the focus of the specs too rare in the corpus from their rankings' gap: a spec whose top padders
    gain twice the median gap is assumed to put twice the median focus on the adds."""
    measured = [p for s, p in profiles.items() if s in t.focus]
    if not measured:
        return t
    ref_pad = st.median(1 - p.boss_share for p in measured)
    ref_focus = st.median(t.focus[p.spec] for p in measured)
    if ref_pad <= 0:
        return t
    focus = dict(t.focus)
    for s, p in profiles.items():
        if s not in focus:
            focus[s] = min(1.0, ref_focus * (1 - p.boss_share) / ref_pad)
    out = AddType(**{**t.__dict__, "focus": focus})
    out.estimated = {s for s in focus if s not in t.focus}
    return out


AOE, FLEX, SINGLE = "AoE / funnel", "flexible", "single target"
UNKNOWN = "not measured on this boss (too few in the logs; counted as average)"


def archetype(t: AddType, spec: str) -> str:
    """What a spec is on this boss, from its focus on the main adds (measured, or estimated from the rankings
    for the rare specs) vs the median of all players."""
    if spec not in t.focus:
        return UNKNOWN
    f = t.focus[spec]
    if f >= 1.25 * t.default_focus:
        return AOE
    if f <= 0.75 * t.default_focus:
        return SINGLE
    return FLEX


HEALERS = {"Restoration Druid", "Restoration Shaman", "Holy Paladin", "Holy Priest", "Discipline Priest",
           "Mistweaver Monk", "Preservation Evoker"}


def archetypes(types: list[AddType], comp: list[tuple[str, str, float]]) -> dict[str, list[str]]:
    """Your raid's damage dealers and tanks by archetype on this boss: {archetype: ["name (spec)", ...]}."""
    out: dict[str, list[str]] = {AOE: [], FLEX: [], SINGLE: [], UNKNOWN: []}
    if types:
        dealers = [p for p in comp if p[1] not in HEALERS]
        for name, spec, _ in sorted(dealers, key=lambda p: -types[0].focus.get(p[1], types[0].default_focus)):
            out[archetype(types[0], spec)].append(f"{name} ({spec})")
    return out


def spec_table(t: AddType) -> list[tuple[str, float, str]]:
    """Every measured spec on this boss: (spec, focus on the main adds, archetype), AoE first."""
    return sorted(((s, f, archetype(t, s)) for s, f in t.focus.items()), key=lambda x: -x[1])


def best_cleavers(types: list[AddType], comp: list[tuple[str, str, float]], n: int = 3) -> list[tuple[str, str, float]]:
    """The players of your raid who put the most DPS on the main add type (name, spec, DPS on the adds)."""
    if not types:
        return []
    t = types[0]
    ranked = sorted(((name, spec, dps * t.focus.get(spec, t.default_focus)) for name, spec, dps in comp),
                    key=lambda x: -x[2])
    return ranked[:n]
