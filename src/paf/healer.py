"""Healer prep (issue #16): the raid damage of a boss, its big moments, and when the top healers of your spec press
their healing cooldowns. No SimulationCraft (it does not sim healing well): everything comes from the logs of the top
healers of the spec on this boss (a corpus ranked by healing per second, paf.corpus.collect.ranking_metric).

- The raid damage: Warcraft Logs' damage-taken graph of each kill, bounded to the pull (one series per player, summed;
  about 2 points a kill, for the first RAID_KILLS kills), resampled to STEP seconds; the median over the kills, up to the median
  duration. Its big moments: the windows at SPIKE times the median or more, the boss spell cast just before named.
- The healing cooldowns: the spells the top players cast at most once every 45 s or so (rare casts) that most of them
  take; the moments most of them press each (paf.defensives.peaks), next to the nearest big moment of raid damage.
- Talents: the builds of the top players (count, with the import string); trinkets: the most played.
- What the Encounter Journal asks healers; the numbers (HPS of a talent or an item): QE Live.
"""

from __future__ import annotations

import json
import re
import statistics as st
from collections import Counter
from dataclasses import dataclass, field
from html import escape as e

from paf import theme
from paf.theme import diff_pill

GRAPH = """query($c:String!,$f:[Int]!,$a:Float,$b:Float){ reportData { report(code:$c) {
  graph(fightIDs:$f, dataType:DamageTaken, hostilityType:Friendlies, startTime:$a, endTime:$b) } } }"""
GRAPH_BY_ABILITY = """query($c:String!,$f:[Int]!,$a:Float,$b:Float){ reportData { report(code:$c) {
  graph(fightIDs:$f, dataType:DamageTaken, hostilityType:Friendlies, viewBy:Ability, startTime:$a, endTime:$b) } } }"""
NAMED = 0.4  # an ability doing this share of the raid's damage in a moment names it; below, the damage is mixed
ALSO = 0.25  # ... and a second one this share is named with it
BOUNDS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) { fights(fightIDs:$f) { startTime endTime } } } }"""


def fight_bounds(client, report: str, fight_id: int) -> tuple[float, float]:
    """The pull's start and end in the report (a graph without them covers the whole report)."""
    f = (client.query(BOUNDS, {"c": report, "f": [fight_id]}, cache_ttl=86400)["reportData"]["report"]["fights"]
         or [{}])[0]
    return f.get("startTime") or 0, f.get("endTime") or 0


def series_of(g: dict) -> tuple[float, dict[str, list[float]]]:
    """(seconds per point, name -> damage taken per second at each point) of a graph."""
    series = {s.get("name", "?"): s.get("data") or [] for s in g.get("series") or [] if s.get("name") != "Total"}
    first = next(iter(g.get("series") or []), {})
    return (first.get("pointInterval") or STEP * 1000) / 1000, series
RAID_KILLS = 40
STEP = 5.0
SPIKE = 1.5  # a moment with this many times the median raid damage is a big hit
RELATIVE = 0.85  # ... and every hit this close to the highest is one too (Nek'zali: 0:35 x1.62, 1:20 x1.57)
SPIKE_GAP = 15.0
ANSWER = (10.0, 8.0)  # seconds before and after a moment (a 5 s step) a press answers it
WAVE = 1.2  # without any SPIKE, the waves of raid damage at this many times the median are the moments to plan for
COOLDOWN_GAP = 45.0  # a spell cast at most once in this many seconds (median) is a cooldown
QE_LIVE = "https://questionablyepic.com/live/"


@dataclass
class Moment:
    t: float
    dtps: float  # raid damage taken per second there
    ratio: float  # times the median
    boss_spell: str = ""


@dataclass
class Cooldown:
    name: str
    spell_id: int
    users: float  # share of the top players who cast it
    per_kill: float
    times: list[float]  # when most of them press it: as many moments as their casts a kill, the best followed
    near: list[str] = field(default_factory=list)  # the big moment each one answers, if any
    alt: list[float] = field(default_factory=list)  # other moments some of them press it at instead
    every: float = 0.0  # pressed on cooldown, about every this many seconds (paf.healroles.on_cadence)


@dataclass
class HealerPrep:
    boss: str
    difficulty: str
    spec: str
    kills: int
    duration: float
    curve: list[float]  # median raid damage taken per second, per STEP
    moments: list[Moment]
    cooldowns: list[Cooldown]
    builds: list[tuple[int, str, str]]  # (players, label, import string)
    trinkets: list[tuple[str, int, float]]  # name, item id, share of the top players
    journal: list[str]
    phases: list[tuple[str, float]] = field(default_factory=list)
    comps: list = field(default_factory=list)  # paf.healroles.Comp, most played first
    presence: list = field(default_factory=list)  # paf.healroles.Presence of every healer spec
    roles: list = field(default_factory=list)  # paf.healroles.Role, every healer spec measured
    role_kills: int = 0  # kills the roles were measured on
    role_sample: str = ""  # which kills: "the top Restoration Shamans' kills (ranked by healing), median 4:50, 2 deaths"
    class_name: str = ""
    character: str = ""
    abilities: str = ""  # the Encounter Journal's stages, your role's abilities in full (paf.bossguide), html
    dispellable: list = field(default_factory=list)  # (ability, debuff type): the Journal's flags or the game data
    dispels_checked: bool = False  # the journal and the game data were read for them (none found is information)
    dispelled: list = field(default_factory=list)  # (debuff, a kill) the ranked healers removed, measured
    dispel_kills: int = 0
    dispel_text: str = ""  # what the dispelled ability does and sets off (journal, game data): the dispel's cost
    rare: list = field(default_factory=list)  # long cooldowns few top players press (Cooldown): said, not hidden
    casts: dict = field(default_factory=dict)  # boss ability -> its casts in the typical kill (timing evidence)
    split: list = field(default_factory=list)  # (talent, share picked) the top players split on (contested)
    split_players: int = 0
    dispel_delay: tuple | None = None  # (median s after it lands, dispels measured), paf.healroles.dispel_delay
    named_by_damage: bool = False
    raid_kills: int = 0  # kills the raid damage curve is the median of
    role_median: float = 0.0  # median duration of the healers' comparison's kills
    hero: list = field(default_factory=list)  # (hero tree, share of the top players), paf.healer.hero_split  # the moments are named by the raid's damage taken by ability (measured)


def ensure_table(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS raid_damage(report TEXT, fight_id INT, step REAL, series TEXT, "
                "PRIMARY KEY(report, fight_id))")
    con.execute("DELETE FROM raid_damage WHERE step > 10")  # read over the whole report by 0.6.23's first try
    con.execute("CREATE TABLE IF NOT EXISTS raid_damage_ability(report TEXT, fight_id INT, step REAL, series TEXT, "
                "PRIMARY KEY(report, fight_id))")


def fetch_raid_damage(client, con, encounter_id: int, difficulty: int, limit: int = RAID_KILLS,
                      log=print) -> int:
    """The damage-taken graph of the first `limit` kills that lack it (best ranked first); returns how many."""
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM raid_damage d JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id FROM fight f LEFT JOIN raid_damage d USING(report, fight_id) "
        f"LEFT JOIN ranked r USING(report, fight_id) WHERE {where} AND d.report IS NULL ORDER BY r.rank_pos",
        params).fetchall()[:max(0, limit - have)]
    for rep, fid in todo:
        a, b = fight_bounds(client, rep, fid)
        g = client.query(GRAPH, {"c": rep, "f": [fid], "a": a, "b": b}, cache_ttl=86400)["reportData"]["report"]["graph"]
        step, series = series_of(g.get("data", g) if isinstance(g, dict) else {})
        con.execute("INSERT OR REPLACE INTO raid_damage VALUES(?,?,?,?)", (rep, fid, step, json.dumps(series)))
    con.commit()
    # the same kills' damage taken by ability: what hits the raid in each big moment (measured, not a cast's timing)
    by = con.execute(f"SELECT d.report, d.fight_id FROM raid_damage d JOIN fight f USING(report, fight_id) "
                     f"LEFT JOIN raid_damage_ability x USING(report, fight_id) WHERE {where} AND x.report IS NULL",
                     params).fetchall()
    for rep, fid in by:
        a, b = fight_bounds(client, rep, fid)
        g = client.query(GRAPH_BY_ABILITY, {"c": rep, "f": [fid], "a": a, "b": b},
                         cache_ttl=86400)["reportData"]["report"]["graph"]
        step, series = series_of(g.get("data", g) if isinstance(g, dict) else {})
        con.execute("INSERT OR REPLACE INTO raid_damage_ability VALUES(?,?,?,?)", (rep, fid, step, json.dumps(series)))
    con.commit()
    if todo or by:
        log(f"  raid damage of {max(len(todo), len(by))} kills")
    return len(todo)


def raid_by_ability(con, encounter_id: int, difficulty: int, duration: float) -> dict[str, list[float]]:
    """The raid's damage taken per ability, per STEP, summed over the kills read (shares compare, not levels)."""
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    n = int(duration // STEP) + 1
    out: dict[str, list[float]] = {}
    for step, series in con.execute(f"SELECT x.step, x.series FROM raid_damage_ability x JOIN fight f "
                                    f"USING(report, fight_id) WHERE {where}", params):
        for name, values in json.loads(series).items():
            row = out.setdefault(name, [0.0] * n)
            for i, v in enumerate(values):
                b = int(i * step // STEP)
                if b < n:
                    row[b] += v or 0
    return out


SUSTAINED = 1.15  # the raid damage this many times the median, for SUSTAINED_S or more: a stretch with no break
SUSTAINED_S = 30.0


def sustained(curve: list[float]) -> list[tuple[float, float, float]]:
    """(start, end, mean ratio) of the stretches the raid takes SUSTAINED x its median damage or more for SUSTAINED_S
    or more (Nek'zali's Uncoiling: the last 1:30 at about 1.2x): no peak, yet the fight's longest healing check."""
    pos = [v for v in curve if v > 0]
    if not pos:
        return []
    base = st.median(pos)
    out, start = [], None
    for i, v in enumerate(curve + [0.0]):
        if v >= SUSTAINED * base and start is None:
            start = i
        elif v < SUSTAINED * base and start is not None:
            if (i - start) * STEP >= SUSTAINED_S:
                out.append((start * STEP, i * STEP, st.mean(curve[start:i]) / base))
            start = None
    return out


def moment_names(m: Moment) -> list[str]:
    """The abilities a moment is named after: "mixed damage, most from A and B" -> [A, B]."""
    return [x for x in m.boss_spell.removeprefix("mixed damage, most from ").removeprefix("after ").split(" and ") if x]


def moment_notes(found: list[Moment]) -> dict[str, str]:
    """The boss tab's measured line under each ability the raid's big moments are named after (Soulcoil Rite: no
    cast to time it, yet the fight tab names it twice)."""
    at: dict[str, list[float]] = {}
    for m in found:
        for n in moment_names(m):
            at.setdefault(n, []).append(m.t)
    return {n: "big raid damage at " + _and([_mmss(t) for t in ts]) + " (measured)" for n, ts in at.items()}


def name_by_damage(found: list[Moment], by: dict[str, list[float]], width: int = 2) -> None:
    """Name each moment by what does the raid's damage there: its first ability when it does NAMED of it, with a
    second one doing ALSO; else "mixed damage" and the two biggest (Nek'zali's 0:35: Soulcoil Rite 53%)."""
    for m in found:
        b = int(m.t // STEP)
        w = sorted(((sum(v[b:b + width]), name) for name, v in by.items()), reverse=True)
        total = sum(x for x, _ in w)
        if not total:
            continue
        (a, first), (s, second) = w[0], (w[1] if len(w) > 1 else (0.0, ""))
        if a / total >= NAMED:
            m.boss_spell = f"{first} and {second}" if s / total >= ALSO else first
        else:
            m.boss_spell = f"mixed damage, most from {first} and {second}"


def raid_curve(con, encounter_id: int, difficulty: int, duration: float) -> list[float]:
    """Median raid damage taken per second, per STEP seconds, over the kills that have it."""
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    n = int(duration // STEP) + 1
    per_bucket: list[list[float]] = [[] for _ in range(n)]
    for step, series in con.execute(f"SELECT d.step, d.series FROM raid_damage d JOIN fight f "
                                    f"USING(report, fight_id) WHERE {where}", params):
        data = json.loads(series)
        total: list[float] = []
        for values in data.values():
            for i, v in enumerate(values):
                if i >= len(total):
                    total.append(0.0)
                total[i] += v or 0
        for i, v in enumerate(total):  # each point covers `step` seconds: into STEP buckets
            b = int(i * step // STEP)
            if b < n:
                per_bucket[b].append(v)
    return [st.median(v) if v else 0.0 for v in per_bucket]


def moments(curve: list[float], boss_casts: list[tuple[str, list[float]]], top: int = 8,
            skip: frozenset[str] | set[str] = frozenset(), raid: frozenset[str] | set[str] = frozenset()) -> list[Moment]:
    """The big moments of raid damage, the boss spell cast just before each (within 8 s). skip: abilities that cannot
    explain this damage (another role's: a tank buster under the raid's damage)."""
    base = st.median([v for v in curve if v > 0]) if any(curve) else 0.0
    if not base:
        return []
    found: list[Moment] = []
    for i, v in enumerate(curve):
        if v < WAVE * base or (i and curve[i - 1] > v) or (i + 1 < len(curve) and curve[i + 1] > v):
            continue
        t = i * STEP
        if found and t - found[-1].t < SPIKE_GAP:
            if v > found[-1].dtps:
                found[-1] = Moment(t, v, v / base)
            continue
        found.append(Moment(t, v, v / base))
    if found and max(m.ratio for m in found) < SPIKE:  # Vashnik: no single big hit, the raid damage comes in waves
        found = sorted(sorted(found, key=lambda m: -m.ratio)[:3], key=lambda m: m.t)  # the three highest waves
    elif found:  # the hits near the highest, not only those above a line two samples put on either side of
        highest = max(m.ratio for m in found)
        found = [m for m in found if m.ratio >= max(SPIKE * 0.9, RELATIVE * highest)]
    for m in found:
        near = [(m.t - x, name) for name, times in boss_casts if name not in skip for x in times if -2 <= m.t - x <= 8]
        later = [(m.t - x, name) for name, times in boss_casts if name not in skip for x in times if 8 < m.t - x <= 30]
        if near:
            m.boss_spell = min(near)[1]
        elif later:  # the damage that follows a cast (Vashnik: the waves 16 to 28 s after Imbibe), matched by timing;
            hits = [c for c in later if c[1] in raid]  # an ability the journal says hits all players goes first
            m.boss_spell = f"after {min(hits or later)[1]}"
    return sorted(sorted(found, key=lambda m: -m.ratio)[:top], key=lambda m: m.t)




def count(x: float) -> str:
    """A count a kill: "8", not "8.0" (a median of whole casts); "2.5" when it is a mean."""
    return f"{x:.0f}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"


def _item(spell_id: int) -> bool:
    try:
        from paf.gamedata import item_spells

        return spell_id in item_spells()
    except Exception:  # noqa: BLE001 - offline: kept
        return False


def _enemy(spell_id: int) -> bool:
    try:
        from paf.gamedata import enemy_only

        return enemy_only(spell_id)
    except Exception:  # noqa: BLE001 - offline: kept
        return False


def _external(spell_id: int) -> str:
    try:
        from paf.gamedata import external_kind

        return external_kind(spell_id)
    except Exception:  # noqa: BLE001 - offline: unknown
        return ""


def cooldowns(tl, found: list[Moment], base: dict[int, tuple[float, int]] | None = None,
              min_users: float = 0.5, max_users: float = 1.01) -> list[Cooldown]:
    """The cooldowns of the top players (spells with a cooldown of COOLDOWN_GAP s or more in the game data, that most
    of them cast; dispels, rotation spells and moves left out) and when most of them press each."""
    from paf.healroles import on_cadence, press_moments

    if base is None:
        try:
            from paf.gamedata import spell_cooldowns

            base = spell_cooldowns()
        except Exception:  # noqa: BLE001 - offline: no game data, the casts' rarity alone
            base = {}
    out, seen = [], set()
    for a in sorted(tl.abilities, key=lambda a: -a.users):
        if not min_users <= a.users < max_users or not tl.duration or a.per_kill > max(1.0, tl.duration / COOLDOWN_GAP) \
                or a.name in seen:
            continue
        if base and base.get(a.id, (0.0, 1))[0] < COOLDOWN_GAP:
            continue
        seen.add(a.name)
        per_player = [p["casts"].get(a.name) or p["casts"].get(a.id) or [] for p in tl.players]
        per_player = [ts for ts in per_player if ts]
        times, alt = press_moments(per_player, max(1, round(a.per_kill)), tl.duration)
        every = on_cadence(per_player, a.per_kill, tl.duration)
        near = []
        for t in times:
            m = min(found, key=lambda m: abs(m.t - t), default=None)
            ok = (not every and m is not None  # on cooldown: near a hit by its cadence, not kept for it
                  and -ANSWER[0] <= t - m.t <= ANSWER[1])  # pressed for the hit: just before or in it
            near.append(f"{_mmss(m.t)} {m.boss_spell}".strip() if ok else "")
        out.append(Cooldown(a.name, a.id, a.users, a.per_kill, times, near, [] if every else alt, every))
    return sorted(out, key=lambda c: -c.users)


def trinkets(con, encounter_id: int, difficulty: int, top: int = 100) -> list[tuple[str, int, float]]:
    """(trinket, item id, share of the top players wearing it): the same 100 kills as the cooldowns' presses."""
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(f"SELECT r.gear_json FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} "
                       f"AND r.gear_json IS NOT NULL ORDER BY r.rank_pos LIMIT {int(top)}", params).fetchall()
    count: Counter = Counter()
    names: dict[int, str] = {}
    for (g,) in rows:
        gear = json.loads(g or "[]")
        for slot in (12, 13):  # the trinket slots of Warcraft Logs' gear list
            if slot < len(gear) and gear[slot].get("id"):
                count[gear[slot]["id"]] += 1
                names[gear[slot]["id"]] = gear[slot].get("name") or str(gear[slot]["id"])
    n = len(rows) or 1
    return [(names[i], i, c / n) for i, c in count.most_common(6)]


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


CSS = "<style>" + theme.style("healer") + "</style>"
JS = ("<script>document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(!b)return;"
      "navigator.clipboard.writeText(b.dataset.copy).then(function(){b.textContent='Copied'},function(){})})"
      "</script>")


PRESS_ROWS = 4  # cooldown rows drawn under a damage curve


def curve_svg(curve: list[float], found: list[Moment], phases: list[tuple[str, float]], label: str,
              presses: list | None = None) -> str:
    """A damage-taken curve (per STEP), its big moments as dots, the phases as dashed lines; under it, one row per
    cooldown (Cooldown) with a mark where the top players usually press it: the hit and the button on one time axis."""
    rows = [c for c in presses or [] if c.times][:PRESS_ROWS]
    W, H, L, B = 760, 200 + 18 * len(rows), 150 if rows else 46, 24 + 18 * len(rows)
    peak = max(curve, default=0) or 1
    span = max(len(curve) * STEP, 1)

    def x(t: float) -> str:
        return f"{L + t / span * (W - L - 10):.1f}"

    def y(v: float) -> str:
        return f"{30 + (1 - v / peak) * (H - B - 40):.1f}"  # room above the peaks for their labels
    pts = " ".join(f"{x(i * STEP)},{y(v)}" for i, v in enumerate(curve))
    marks = "".join(f"<circle cx='{x(m.t)}' cy='{y(m.dtps)}' r='4' class='mk'/>"
                    f"<text x='{float(x(m.t)) + 6:.1f}' y='{float(y(m.dtps)) - 8:.1f}' class='ml'>{_mmss(m.t)}</text>"
                    for m in found)
    lines = "".join(f"<line class='ph' x1='{x(t)}' x2='{x(t)}' y1='22' y2='{H - B}'/>"
                    f"<text x='{float(x(t)) + 4:.1f}' y='18' class='pn'>{e(n.split(':')[0])}</text>"
                    for n, t in phases if t > 0)  # the phase changes, named
    ticks = "".join(f"<text x='{x(t)}' y='{H - 6}' class='tk'>{int(t // 60)}:00</text>"
                    for t in range(0, int(span) + 1, 60))
    pos = [v for v in curve if v > 0]
    med = st.median(pos) if pos else 0.0  # the scale the moments are read against (x1.6 the fight's median)
    median = (f"<line class='md' x1='{L}' x2='{W - 10}' y1='{y(med)}' y2='{y(med)}'/>"
              f"<text x='{L - 4}' y='{float(y(med)) - 3:.1f}' class='mdl' text-anchor='end'>median</text>"
              f"<text x='{L - 4}' y='{float(y(med)) + 9:.1f}' class='mdl' text-anchor='end'>{_per_s(med)}</text>"
              ) if med else ""
    cds = "".join(
        f"<text x='{L - 8}' y='{H - B + 16 + 18 * i}' class='cl' text-anchor='end'>{e(c.name.split(',')[0][:22])}</text>"
        + "".join(f"<rect x='{float(x(t)) - 3:.1f}' y='{H - B + 7 + 18 * i}' width='6' height='11' rx='1.5' "
                  f"class='cp'><title>{e(c.name)} {_mmss(t)}</title></rect>" for t in c.times)
        for i, c in enumerate(rows))
    return (f"<svg viewBox='0 0 {W} {H}' class='rd' role='img' aria-label='{e(label)}'>"
            f"<line class='ax' x1='{L}' x2='{W - 10}' y1='{H - B}' y2='{H - B}'/>{median}{lines}{ticks}"
            f"<polyline points='{pts}'/>{marks}{cds}</svg>")


def _per_s(v: float) -> str:
    """A damage rate on the chart's axis: 1.4M/s, 820k/s."""
    return f"{v / 1e6:.1f}M/s" if v >= 1e6 else f"{v / 1e3:.0f}k/s"


def moments_html(found: list[Moment], what: str) -> str:
    """what: kept for the callers; a moment no boss cast explains shows its time only."""
    return "".join(f"<li><b>{_mmss(m.t)}</b><span>{e(m.boss_spell) if m.boss_spell else ''}</span>"
                   f"<small>{m.ratio:.1f}&times; the usual damage</small></li>" for m in found)


def _more(c: Cooldown) -> str:
    """The casts a kill no shared moment shows ("+1"): the count always matches the "a kill" number."""
    n = round(c.per_kill) - len(c.times)
    return f"+{n}" if n > 0 else ""


def _or(c: Cooldown, t: float) -> str:
    """The other habits nearest this moment, said on its chip ("1:18, or 0:36 for some"): another player's choice
    for the same press, never an extra one."""
    near = [a for a in c.alt if min(c.times, key=lambda x: abs(x - a)) == t]
    return f", or {_mmss(min(near, key=lambda a: abs(a - t)))} for some" if near else ""  # one, the nearest


def cooldowns_html(cds: list[Cooldown]) -> str:
    return "".join(
        f"<li><b>{e(c.name)}</b><small>pressed by {c.users:.0%} of the top players &middot; {count(c.per_kill)} a kill</small>"
        "<span class='when'>" + ("".join(f"<span class='chip'>{_chip(t, n)}{_or(c, t)}</span>"
                                        for t, n in zip(c.times, c.near, strict=False))
                                or "<small>when they need it: no moment most of them share</small>")
        + (f"<small class='alt'>on cooldown, about every {c.every:.0f} s</small>" if c.every else
           f"<small class='alt'>{_more(c)} more when they need it</small>" if c.times and _more(c) else "")
        + "</span></li>"
        for c in cds)


def _near(n: str) -> str:
    """ "0:35 Possession Barrage" -> " · Possession Barrage": the moment a press answers ("0:35" alone: the 0:35 hit,
    no boss cast to name it)."""
    if not n:
        return ""
    t = n.partition(" ")[0]  # the moment is named once, in its row: the chip says which one
    return f" &middot; the {e(t)} hit"


def _chip(t: float, n: str) -> str:
    """A press's time and the hit it answers; "0:35 · the hit" when they are the same time."""
    return _mmss(t) + (" &middot; the hit" if n and n.partition(" ")[0] == _mmss(t) else _near(n))


SHOWN_TALENTS = 60  # every class and spec difference shown (a hero tree is named, not listed): no "+N more"


def build_rows(builds: list) -> list[tuple[int, str, str, str]]:
    """(players, label, import string, what sets it apart from the most played build) of the top builds."""
    try:
        from paf.gamedata import hero_trees, talent_entry_names

        names, heroes = talent_entry_names(), hero_trees()
    except Exception:  # noqa: BLE001 - offline: the builds without their difference
        names, heroes = {}, {}

    def hero(key) -> str:  # the hero tree a build plays: the one most of its hero talents belong to
        trees = [heroes[t] for t in key if t in heroes]
        return max(set(trees), key=trees.count) if trees else ""
    out = []
    for i, b in enumerate(builds):
        if i == 0 or not names:
            out.append((b.count, b.label, b.code or "", "the most played" if i == 0 else ""))
            continue
        mine, base = hero(b.key), hero(builds[0].key)
        other = mine and base and mine != base  # another hero tree: named, its own talents not listed one by one
        plus = sorted({names[t] for t in b.key - builds[0].key if names.get(t) and not (other and t in heroes)})
        minus = sorted({names[t] for t in builds[0].key - b.key if names.get(t) and not (other and t in heroes)})

        def few(xs: list[str]) -> str:  # another hero tree changes twenty talents: the first ones say enough
            return ", ".join(xs[:SHOWN_TALENTS]) + (f" (+{len(xs) - SHOWN_TALENTS} more)" if len(xs) > SHOWN_TALENTS
                                                    else "")
        diff = "; ".join(x for x in (f"the {mine} hero tree instead of {base}" if other else "",
                                     f"takes {few(plus)}" if plus else "", f"drops {few(minus)}" if minus else "") if x)
        out.append((b.count, b.label, b.code or "", diff))
    return out


UNSIMMED = {"change": "What the top players play"}  # no sim to say what to change: the tab says what it holds
SHARED_BUILD = 8  # players: fewer on the most played build, the top players build their own
COPY_SHARE = 0.10  # a build fewer of the players read play gets no copy button: copying it is no choice of theirs
BUILD_SHARE = 0.05  # a build fewer of the players read play is noise; the first one stays, a complete build to copy


def talents_html(builds: list, players: int, who: str, hero: list | None = None) -> str:
    """The hero tree the top players pick (the first choice), then their builds played by enough of them."""
    line = ""
    if hero:
        line = ("<p><b>Hero tree:</b> " + (f"{e(hero[0][0])} (all {players} players read)" if len(hero) == 1 else
                " &middot; ".join(f"{e(t)} {s:.0%}" for t, s in hero) + f" of the {players} players read") + ".</p>")
    if builds and builds[0][0] < SHARED_BUILD:  # 3 of 100 is no build to show, empty row and all
        return (f"<h2>Talents the top {e(who)} play</h2>{line}<p>No shared build: none is played by more than "
                f"{builds[0][0]} of the {players} players read. The talents they split on follow.</p>")
    return (f"<h2>Talents the top {e(who)} play</h2>{line}<ul class='hl2'>"
            f"{builds_html(shown_builds(builds, players), players) or '<li>No build yet.</li>'}</ul>")


def shown_builds(builds: list, players: int) -> list:
    """The builds enough of the players read play (BUILD_SHARE); the most played always, a complete build to copy."""
    return [b for i, b in enumerate(builds) if i == 0 or not players or b[0] >= BUILD_SHARE * players]


def builds_html(builds: list, players: int = 0) -> str:
    copy = "<button class='btn ghost copy' data-copy='{}'>Copy the talents</button>"
    return "".join(f"<li><b>{e(b[1][:1].upper() + b[1][1:])}</b><small>{b[0]} of the top players"
                   + (f" &middot; {e(b[3])}" if len(b) > 3 and b[3] else "") + "</small>"
                   + (copy.format(e(b[2])) if b[2] and (not players or b[0] >= COPY_SHARE * players) else "")
                   + "</li>" for b in builds)


def trinkets_html(trinkets: list[tuple[str, int, float]]) -> str:
    return "".join(f"<li><a href='https://www.wowhead.com/item={i}' target='_blank' rel='noopener'>{e(n)}</a>"
                   f"<small>equipped by {s:.0%} of the top players</small></li>" for n, i, s in trinkets)


def page(title: str, body: str) -> str:
    from paf import theme

    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(title)}</title>{theme.HEAD}<style>{theme.CSS}</style>{CSS}</head><body>"
            f"{theme.topbar('')}<main>{body}</main>{JS}</body></html>")


def render(h: HealerPrep) -> str:
    svg = curve_svg(h.curve, h.moments, h.phases, "Raid damage taken over the fight")
    mom, cds = moments_html(h.moments, "raid damage"), cooldowns_html(h.cooldowns)
    builds, trk = builds_html(h.builds), trinkets_html(h.trinkets)
    jr = "".join(f"<li>{e(x)}</li>" for x in h.journal)
    body = f"""<h1>{e(h.boss)} {diff_pill(h.difficulty)}</h1>
<p class="lead">{e(h.spec)}: the healer's prep, from {h.kills} kills of the top healers of your spec. A {_mmss(h.duration)}
fight.</p>
<section class="hp-sec"><h2>The raid damage, and its big moments</h2>{svg}
<p class="small muted">Damage the raid takes per second, median of the top kills; a dot marks a big moment, named after the boss cast just before it ("after X": 8 to 30 s before, matched by timing).</p>
<ul class="hl2">{mom or '<li>No big moment: steady raid damage.</li>'}</ul></section>
<section class="hp-sec"><h2>Your healing cooldowns, where the top healers press them</h2>
<ul class="hl2">{cds or '<li>Not enough top players in the corpus yet.</li>'}</ul></section>
<section class="hp-sec"><h2>Talents</h2><ul class="hl2">{builds or '<li>No build yet.</li>'}</ul></section>
<section class="hp-sec"><h2>Trinkets the top healers play</h2><ul class="hl2">{trk or '<li>No gear yet.</li>'}</ul></section>
{f'<section class="hp-sec"><h2>What the Encounter Journal asks healers</h2><ul class="hl2">{jr}</ul></section>' if jr else ''}
<section class="hp-sec"><h2>The numbers</h2><p>SimulationCraft does not sim healing well: for the value of a talent or an
item for your healing, use <a href="{QE_LIVE}" target="_blank" rel="noopener">QE Live</a>.</p></section>"""
    return page(f"{h.boss} prep", body)


# --- the sheet in the four sections of every role's sheet (issue #27) ----------------------------------------------

def _pct(v: float) -> str:
    return f"{v:.0%}"


def role_card(r, everyone: list, mine: bool, chips: bool = True) -> str:
    """One healer spec's job on the boss, with its numbers and how many healers they come from. chips: its long
    cooldowns' usual times (left out on your own card: the fight tab gives yours, from the top players of your spec)."""
    cds = "".join([f"<span class='chip'>{e(n)} {', '.join(_mmss(t) for t in ts)}</span>"
                   for n, _k, ts in r.cd_names if ts][:5]) if chips else ""
    return (f"<article class='hrole'><h3>{e(r.spec)}{' <small>(you)</small>' if mine else ''}</h3>"
            f"<ul class='jobs'>{''.join(f'<li>{e(j)}</li>' for j in r.jobs)}</ul>"
            f"<p class='nums'>{' · '.join(_nums(r))}</p>" + (f"<p class='when'>{cds}</p>" if cds else "")
            + f"<p class='small muted'>{r.players} {e(r.spec)}s in the kills read.</p></article>")


def contested(con, encounter_id: int, difficulty: int, spec: str, lo: float = 0.2, hi: float = 0.8,
              shown: int = 10) -> tuple[list[tuple[str, float]], int]:
    """The talents the top players of the spec split on (picked by lo to hi of them), the closest to half first,
    and how many players were read: when most play a build of their own, these explain the builds. A hero tree's
    talents are left out (they follow the tree, said apart: paf.healer.hero_split), and the two sides of a choice
    node are one line ("Revival 62% / Restoral 38%")."""
    import json

    from paf.corpus.analyze import kills_filter

    try:
        from paf.gamedata import hero_trees, talent_entries

        entries, heroes = talent_entries(), hero_trees()
    except Exception:  # noqa: BLE001 - offline: no names, no line
        return [], 0
    where, params = kills_filter(encounter_id, difficulty)
    picks: dict[int, int] = {}
    players = 0
    for (tj,) in con.execute(f"SELECT r.talents_json FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} "
                             f"AND r.spec=? AND r.actor_id IS NOT NULL", (*params, spec)):
        got = {t["talentID"] for t in json.loads(tj or "[]") if entries.get(t.get("talentID"), ("",))[0]}
        if got:
            players += 1
            for t in got:
                picks[t] = picks.get(t, 0) + 1
    by_node: dict[int, list[tuple[str, float]]] = {}
    for t, c in picks.items():
        if t in heroes or not players or not lo <= c / players <= hi:
            continue
        name, _sid, node, _x, _y = entries[t]
        by_node.setdefault(node or -t, []).append((name, c / players))
    split = []
    for sides in by_node.values():
        sides.sort(key=lambda x: -x[1])
        split.append((" / ".join(f"{n} {s:.0%}" for n, s in sides) if len(sides) > 1 else sides[0][0],
                      sides[0][1] if len(sides) == 1 else -1.0, sides[0][1]))
    # a pair says its own shares (-1 in the second place) and sorts by its first side, as a single talent by its
    # share: the closest to half first
    return [(n, s) for n, s, _k in sorted(split, key=lambda x: abs(x[2] - 0.5))][:shown], players


def hero_split(con, encounter_id: int, difficulty: int, spec: str) -> list[tuple[str, float]]:
    """(hero tree, share of the top players) on this boss: the first talent choice, before the builds."""
    import json

    from paf.corpus.analyze import kills_filter

    try:
        from paf.gamedata import hero_trees

        heroes = hero_trees()
    except Exception:  # noqa: BLE001 - offline: no line
        return []
    where, params = kills_filter(encounter_id, difficulty)
    trees: Counter = Counter()
    for (tj,) in con.execute(f"SELECT r.talents_json FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} "
                             f"AND r.spec=? AND r.actor_id IS NOT NULL", (*params, spec)):
        mine = [heroes[t["talentID"]] for t in json.loads(tj or "[]") if t.get("talentID") in heroes]
        if mine:
            trees[max(set(mine), key=mine.count)] += 1
    total = sum(trees.values())
    return [(t, n / total) for t, n in trees.most_common()] if total else []


def _and(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def build_lead(builds: list, spec: str, players: int, split: list | None = None) -> str:
    """The change tab's answer: the most played build when the top players agree on one; when their builds are
    scattered, the talents they split on (the rest they agree on)."""
    builds = shown_builds(builds, players)  # the sentence counts the builds the list shows
    if not builds:
        return ""
    top = builds[0]
    total = sum(b[0] for b in builds)
    if split and top[0] < players / 5:  # no build a fifth of them play: the answer is in the split talents
        return (f"<p class='lead'>The top {e(spec)}s split on "
                + e(_and([n for n, _s in split[:4]])) + f"; no build is played by more than {top[0]} of the "
                f"{players} players read.{NOT_ADVICE}</p>")
    return (f"<p class='lead'>The most played build of the top {e(spec)}s: {e(top[1])}, by {top[0]} of the "
            f"{players} players read" + (f"; the {len(builds)} builds below cover {total} of them, the other "
                                        f"{players - total} play builds of their own" if len(builds) > 1 else "")
            + f".{NOT_ADVICE}</p>")


NOT_ADVICE = " Their choices, not a recommendation: no sim weighs them."


def split_html(split: list, players: int, spec: str) -> str:
    """The talents the top players split on, with how often each is picked: what the builds above hide."""
    return (f"<h2>The talents the top {e(spec)}s split on</h2><p>Picked by this share of the {players} players "
            "read; the closest to half first:</p><ul class='hl2 split'>"
            + "".join(f"<li><b>{e(n)}</b><small>{s:.0%}</small></li>" if s >= 0 else f"<li><b>{e(n)}</b></li>"
                      for n, s in split) + "</ul>")


def journal_lead(lines: list[str], who: str) -> str:
    """The boss tab's answer: the abilities the Encounter Journal asks this role to handle."""
    names = list(dict.fromkeys(re.findall(r"\[([^\]]+)\]", " ".join(lines))))
    if not names and lines:  # the journal's notes without spell links: said as they are, just below
        return (f"<p class='lead'>The Encounter Journal has {len(lines)} notes for {who} on this boss, just below; "
                f"every ability follows, phase by phase; another role's own abilities are only named.</p>")
    if not names:
        return f"<p class='lead'>The Encounter Journal asks {who} nothing in particular on this boss.</p>"
    return (f"<p class='lead'>What the Encounter Journal asks {who} to handle here: {e(', '.join(names[:5]))}. Every "
            f"ability follows, phase by phase; another role's own abilities are only named.</p>")


def _job(r) -> str:
    """A spec's healing job of this boss, or "": not "nothing stands out", nor Power Infusion given on every boss."""
    return next((j for j in r.jobs if not j.startswith(("nothing stands out", "buffs a damage dealer"))), "")


def _pace(h) -> str:
    """The comparison's kills against the timings' ones, said from the numbers (kills ranked by a healer's healing
    were said slower: on four sheets they were not)."""
    if not h.role_median or not h.duration or abs(h.role_median - h.duration) < 10:  # under 10 s: noise
        return ""
    return (f" These kills are {'slower' if h.role_median > h.duration else 'faster'} than the {h.kills} top kills "
            f"of the timings ({_mmss(h.role_median)} against {_mmss(h.duration)}).")


def jobs_lead(roles: list, mine: str = "") -> str:
    """The deeper tab's answer: your spec's job first, then the other healer specs whose job stands out."""
    you = next((r for r in roles if r.spec == mine), None)
    head = ""
    if you:
        head = (f"Your spec here: the {you.spec} {_job(you)}. " if _job(you) else
                "Your spec here: nothing stands out against the other healers. ")
    lines = [f"the {r.spec} {_job(r)}" for r in roles if r.spec != mine and _job(r)]
    if not lines:
        return f"<p class='lead'>{e(head)}No other healer spec stands out on this boss.</p>"
    return f"<p class='lead'>{e(head)}The others: " + "; ".join(e(x) for x in lines) + ".</p>"


NUMS_NOTE = ("On each card: the share of the kill's healing; of its own healing, the share on the tanks and in the "
             "raid's spikes; overheal; dispels a minute; externals a kill (protective cooldowns cast on another "
             "player, not on themselves).")


def _nums(r) -> list[str]:
    """A healer spec's numbers, all of them, the same on every card (NUMS_NOTE says what each is)."""
    out = [f"{_pct(r.healing)} of the kill's healing", f"{_pct(r.tank)} on the tanks", f"{_pct(r.spike)} in spikes",
           f"{_pct(r.overheal)} overheal", f"{r.dispels:.1f} dispels a minute", f"{r.externals:.1f} externals a kill"]
    if r.buffs:
        out.append(f"{r.buffs:.1f} {_and(r.buff_spells)} a kill on another player")
    return out


def _plain(text: str) -> str:
    """A journal line without its spell brackets: "[Soulcoil Well]" -> "Soulcoil Well"."""
    return re.sub(r"[\[\]]", "", text)


FEW_KILLS = 15  # a spec in fewer of the kills read: its numbers say little (Vengeance, 10 kills: "0.0 deaths")


def presence_table(pres: list, mine: str = "", what: str = "Healer") -> str:
    """Each spec of a role in the top kills: how often it is brought, and the kills with it against without it."""
    if not pres:
        return "<p class='small muted'>Not enough kills read yet.</p>"
    deaths = any(p.deaths_with is not None for p in pres)

    def dd(a, b) -> str:
        return "" if a is None else f"{a:.1f}" + ("" if b is None else f" <small>({b:.1f} without)</small>")
    rows = ""
    for p in pres:
        if p.spec == mine and p.share >= 0.99:  # the corpus is this spec's kills: its row says nothing
            continue
        few = p.kills < FEW_KILLS
        cells = ("<td class='n' colspan='3'><small>too few kills</small></td>" if few else
                 f"<td class='n'>{p.per_kill:.1f}</td><td class='n'>{_mmss(p.duration_with)}"
                 + ("" if p.duration_without is None else f" <small>({_mmss(p.duration_without)} without)</small>")
                 + "</td>" + (f"<td class='n'>{dd(p.deaths_with, p.deaths_without)}</td>" if deaths else ""))
        if few and not deaths:
            cells = "<td class='n' colspan='2'><small>too few kills</small></td>"
        rows += (f"<tr class='{'mine ' if p.spec == mine else ''}{'few' if few else ''}'><td>{e(p.spec)}</td>"
                 f"<td class='n'>{_pct(p.share)} <small>({p.kills} kill{'s' if p.kills != 1 else ''})</small></td>"
                 f"{cells}</tr>")
    head = (f"<th>{what}</th><th>Top kills with one</th><th>Per kill</th><th>Median kill</th>"
            + ("<th>Deaths a kill</th>" if deaths else ""))
    return f"<table class='hcomp'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


def comps_table(comps: list, n_kills: int) -> str:
    if not comps or all(c.kills < FEW_KILLS for c in comps):  # no composition played enough: no table to read
        return ""
    deaths = any(c.deaths is not None for c in comps)
    rows = "".join(
        f"<tr><td>{e(c.label)}</td><td class='n'>{c.kills} ({_pct(c.share)})</td><td class='n'>{_mmss(c.duration)}</td>"
        + (f"<td class='n'>{'' if c.deaths is None else f'{c.deaths:.1f}' if c.kills >= FEW_KILLS else '<small>too few kills</small>'}</td>"
           if deaths else "") + "</tr>"
        for c in comps)
    return ("<table class='hcomp'><thead><tr><th>Healers</th><th>Top kills</th><th>Median kill</th>"
            + ("<th>Deaths a kill</th>" if deaths else "") + f"</tr></thead><tbody>{rows}</tbody></table>"
            f"<p class='small muted'>Of {n_kills} top kills read. Exact compositions played at least 5 times; the "
            f"other {n_kills - sum(c.kills for c in comps)} kills play rarer ones. Deaths from {FEW_KILLS} kills of a "
            f"composition, as in the table above.</p>")


def render_sheet(h: HealerPrep) -> str:
    """The healer's sheet: The fight (the raid damage, your cooldowns where the top healers press them), What to
    change (your spec's job here, the healers of the top kills, talents, trinkets), The boss, Dig deeper (every
    healer spec's job, the compositions, how it is measured)."""
    from paf.defensives import is_defensive
    from paf.prep_report import sheet_page

    worn = {n for n, _i, _s in h.trinkets}  # an on-use trinket is no class cooldown
    items = [c for c in h.cooldowns + h.rare if c.name in worn]  # an on-use trinket, however many press it
    own = [c for c in h.cooldowns if c in items or not (_item(c.spell_id) or _enemy(c.spell_id))]  # a potion, a
    # spell on enemies (Holy Word: Chastise): no healing cooldown
    heals = [c for c in own if not is_defensive(c.spell_id, c.name) and c not in items]
    svg = curve_svg(h.curve, h.moments, h.phases, "Raid damage taken over the fight, and the top players' healing "
                    "cooldowns", heals)
    defs = [c for c in own if c not in heals and c not in items]
    lead = ""
    if h.moments:
        shown = h.moments[:3]
        said = [m.boss_spell for m in shown]
        ratios = _and([f"{m.ratio:.1f}&times;" for m in shown])
        if len(set(said)) == 1 and said[0] and len(shown) > 1:  # one ability each time: said once
            hits = f"{_and([_mmss(m.t) for m in shown])}, each time {e(said[0])}"
        else:
            hits = _and([f"{_mmss(m.t)} ({e(m.boss_spell)})" if m.boss_spell else _mmss(m.t) for m in shown])
        hits += f": {ratios} the usual damage"
        # a cooldown said for a moment only when the top players' usual press answers it (paf.healer.ANSWER)
        answers = []
        for m in shown:
            mine_here = [c.name for c in heals if any(n and n.split(" ", 1)[0] == _mmss(m.t) for n in c.near)
                         and not _external(c.spell_id)]  # one player's buff (Life Cocoon, Power Infusion): no raid answer
            if mine_here:
                answers.append(f"at {_mmss(m.t)}, {_and(mine_here[:3])}")
        end = len(h.curve) * STEP
        long = "".join(f" {'From ' + _mmss(a) + ' to the end' if b >= end - STEP else _mmss(a) + ' to ' + _mmss(b)}, "
                       f"the raid takes about {r:.1f}&times; the usual damage without a break."
                       for a, b, r in sustained(h.curve))
        lead = (f"<p class='lead'>Big raid damage at {hits}.{long}"
                + (f" Around them the top {e(h.spec)}s press {e('; '.join(answers))}." if answers else
                   f" No healing cooldown of the top {e(h.spec)}s is kept for them.") + "</p>")
    fight = ([lead] if lead else []) + [
        f"<h2>The raid damage, and its big moments</h2><div class='card'>{svg}<p class='small muted'>Damage the "
        f"raid takes per second, median of {h.raid_kills or 'the top'} kills read; a dot marks a big moment, "
        + ("named after the ability doing the most of the raid's damage there, measured on the same kills"
           if h.named_by_damage else "named after the boss cast just before it (&quot;after X&quot;: 8 to 30 s "
           "before, matched by timing)") + f".</p><ul class='hl2'>"
        f"{moments_html(h.moments, 'raid damage') or '<li>No big moment: steady raid damage.</li>'}</ul></div>",
        f"<h2>Your long cooldowns, where the top {e(h.spec)}s press them</h2><ul class='hl2'>"
        f"{cooldowns_html(heals) or '<li>Not enough top players in the corpus yet.</li>'}</ul>"]
    rare = [c for c in h.rare if c not in items]
    if rare:  # a big cooldown the top players skip is information too (Healing Tide Totem: 3 kills in 100)
        fight.append(f"<p class='small muted'>Fewer than half of the top {e(h.spec)}s press "
                     + ", ".join(f"{e(c.name)} ({c.users:.0%}, {_and([_mmss(t) for t in c.times]) or 'no shared moment'})"
                                 for c in rare) + " on this boss.</p>")
    if defs:
        fight.append(f"<h2>Your defensives</h2><ul class='hl2'>{cooldowns_html(defs)}</ul>")
    if items:
        fight.append(f"<h2>On-use trinkets</h2><ul class='hl2'>{cooldowns_html(items)}</ul>")
    n_kills = h.role_kills or h.kills
    change = [build_lead(h.builds, h.spec, h.split_players or h.kills, h.split)]
    change.append(talents_html(h.builds, h.split_players or h.kills, f"{h.spec}s", h.hero))
    if h.split:
        change.append(split_html(h.split, h.split_players, h.spec))
    trk = trinkets_html(h.trinkets) or "<li>No gear yet.</li>"
    change.append(f"<h2>Trinkets the top {e(h.spec)}s play</h2><ul class='hl2'>{trk}</ul>"
                  f"<p class='small muted'>No healing sim: these are the top players' choices, not a recommendation. "
                  f"To weigh a talent or an item for your character, use <a href=\"{QE_LIVE}\" target=\"_blank\" "
                  f"rel=\"noopener\">QE Live</a>.</p>")
    jr = "".join(f"<li>{e(_plain(x))}</li>" for x in h.journal)
    when = (f", a median {h.dispel_delay[0]:.0f} s after it lands on the player" if h.dispel_delay else "")
    # what the dispel sets off, when it is part of a big moment (Vashnik: Caustic Explosion at 2:10 and 3:35)
    feeds = sorted({n for m in h.moments for n in moment_names(m) if n and n in (h.dispel_text or "")})
    fed = "".join(f" {e(n)} is part of the raid's big damage at "
                  + _and([_mmss(m.t) for m in h.moments if n in moment_names(m)]) + "."
                  for n in feeds)
    # a dispel every healer does: said as what the top players do, not as this spec's job (Dig deeper says those)
    first = ([f"<p class='lead'>Dispel {e(h.dispelled[0][0])}: the top {e(h.spec)} of each kill removes it "
              f"{h.dispelled[0][1]:.1f} times ({h.dispel_kills} kills read){when}."
              + (f" {e(h.dispel_text)}" if h.dispel_text else "") + fed + "</p>"]
             if h.dispelled and h.dispelled[0][1] >= 1 else [journal_lead(h.journal, "healers")])
    boss = first + (
        [f"<h2>What the Encounter Journal asks healers</h2><ul class='hl2'>{jr}</ul>"] if jr else [])
    if h.dispelled and (len(h.dispelled) > 1 or h.dispelled[0][1] < 1):  # the others than the lead's job, measured
        inside = set(re.findall(r'<b>([^<]+)</b>', h.abilities))  # the abilities the journal lists below
        boss.append(f"<h2>What the top {e(h.spec)}s dispel here</h2><p>"
                    + _and([f"{e(n)} ({k:.1f} a kill" + ("" if n in inside else ", not in the Encounter Journal")
                            + ")" for n, k in h.dispelled])
                    + f", on {h.dispel_kills} of their kills read.</p>")
    elif h.dispellable and not h.dispelled:  # where the dispels most likely go: the Journal's flags and the game data, not a measure
        boss.append("<h2>What you can dispel here</h2><p>Dispellable on this boss at this difficulty: "
                    + _and([f"{e(n)} ({e(t)})" for n, t in h.dispellable])
                    + "; your spec's dispels in the top kills most likely go to them (not measured per debuff yet)."
                    "</p>")
    elif h.dispels_checked and not h.dispelled:
        boss.append("<h2>What you can dispel here</h2><p>No ability of this boss is dispellable at this difficulty, "
                    "in the Encounter Journal or the game data: the dispels in the top kills go to other debuffs "
                    "(which ones is not measured yet).</p>")
    if h.abilities:  # every ability, the healers' in full and the others' named; your measured job tagged on it
        stages = h.abilities
        if h.dispelled and h.dispelled[0][1] >= 1:
            name, k = h.dispelled[0]
            stages = stages.replace(f"<b>{e(name)}</b>", f"<b>{e(name)}</b> <span class=\"pill gold\">you dispel "
                                    f"it: {k:.1f} a kill</span>", 1)
        boss.append(f"<h2>Every ability, phase by phase</h2><div class='stages'>{stages}</div>")
    enough = {p.spec for p in h.presence if p.kills >= FEW_KILLS} if h.presence else {r.spec for r in h.roles}
    shown = sorted((r for r in h.roles if r.spec == h.spec or r.spec in enough), key=lambda r: r.spec != h.spec)
    others = "".join(role_card(r, h.roles, r.spec == h.spec, chips=r.spec != h.spec) for r in shown)
    few = [p.spec for p in h.presence if p.spec not in {r.spec for r in shown}]
    deeper_first: list[str] = [jobs_lead(shown, h.spec)]  # the cards below only: a spec too rare has no claim
    if h.presence:
        have = next((x for x in h.presence if x.spec == h.spec), None)
        if have and have.share >= 0.99:  # the corpus is your spec's top players' kills: they all have one
            line = (f"These are the top {e(h.spec)}s' kills, so every one has a {e(h.spec)} ({have.per_kill:.1f} a "
                    f"kill); the table tells what the other healers bring.")
        elif have:
            line = f"{_pct(have.share)} of the top kills bring a {e(h.spec)} ({have.per_kill:.1f} a kill when they do)."
        else:
            line = f"Few top raids bring a {e(h.spec)} on this boss."
        deeper_first.append(f"<h2>Healers in the top {e(h.spec)}s' kills</h2><p>{line} Each healer spec in the {n_kills} "
                      f"kills read, with it and without it (a reading, not a verdict on the spec):</p>"
                      f"{presence_table(h.presence, h.spec)}")
    deeper = deeper_first + [f"<h2>Every healer spec's job on this boss</h2><p class='small muted'>Measured on {h.role_kills} "
              f"{e(h.role_sample or 'top kills')}: each spec's median player against the other healers of the same "
              f"kill; a job shows when a number stands out beyond the noise.{_pace(h)} {NUMS_NOTE}</p><div class='hroles'>{others or '<p>Not measured yet.</p>'}</div>"
              + (f"<p class='small muted'>Too few healers measured: {e(', '.join(few))}.</p>" if few else ""),
              (f"<h2>The healer compositions played most</h2>{comps_table(h.comps, n_kills)}"
               if comps_table(h.comps, n_kills) else "")]
    # every sample said once, at the top: the timings and talents, the healers' comparison; read, not simmed
    byline = (f"{e(h.character or h.spec)} &middot; {e(h.spec)} &middot; {h.kills} top kills for the timings and "
              f"talents, median {_mmss(h.duration)}"
              + (f" &middot; {h.role_kills} for the healers' comparison"
                 + (f", median {_mmss(h.role_median)}" if h.role_median else "") if h.role_kills else "")
              + " &middot; read from the logs, no healing sim")
    return sheet_page(h.boss, h.difficulty, byline, h.class_name,
                      {"fight": fight, "change": change, "boss": boss, "deeper": deeper}, theme.style("healer"),
                      UNSIMMED)
