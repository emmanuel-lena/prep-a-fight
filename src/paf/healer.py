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
from itertools import pairwise

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
    named_by_damage: bool = False  # the moments are named by the raid's damage taken by ability (measured)


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


COOLDOWN_SLACK = 0.9  # two moments of a plan are at least this share of the players' shortest usual gap apart


def cooldowns(tl, found: list[Moment], base: dict[int, tuple[float, int]] | None = None,
              min_users: float = 0.5, max_users: float = 1.01) -> list[Cooldown]:
    """The cooldowns of the top players (spells with a cooldown of COOLDOWN_GAP s or more in the game data, that most
    of them cast; dispels, rotation spells and moves left out) and when most of them press each."""
    from paf.defensives import ranked_peaks

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
        ranked = ranked_peaks(per_player) if per_player else []
        keep = max(1, round(a.per_kill))
        # the moments come from all the players: two closer than one player ever presses it twice are two habits,
        # not one plan (Avenging Wrath at 0:21 and 0:41); the second goes with the other habits
        gaps = sorted(y - x for ts in per_player for x, y in pairwise(sorted(ts)))
        gap = gaps[len(gaps) // 10] * COOLDOWN_SLACK if gaps else 0.0
        times: list[float] = []
        alt = []
        for t, _n in ranked:
            if len(times) < keep and all(abs(t - x) >= gap for x in times):
                times.append(t)
            else:
                alt.append(t)
        times, alt = sorted(times), sorted(alt)
        near = []
        for t in times:
            m = min(found, key=lambda m: abs(m.t - t), default=None)
            ok = m is not None and -ANSWER[0] <= t - m.t <= ANSWER[1]  # pressed for the hit: just before or in it
            near.append(f"{_mmss(m.t)} {m.boss_spell}".strip() if ok else "")
        out.append(Cooldown(a.name, a.id, a.users, a.per_kill, times, near, alt))
    return sorted(out, key=lambda c: -c.users)


def trinkets(con, encounter_id: int, difficulty: int, top: int = 50) -> list[tuple[str, int, float]]:
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


def curve_svg(curve: list[float], found: list[Moment], phases: list[tuple[str, float]], label: str) -> str:
    """A damage-taken curve (per STEP), its big moments as dots, the phases as dashed lines."""
    W, H, L, B = 760, 200, 46, 24
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
    return (f"<svg viewBox='0 0 {W} {H}' class='rd' role='img' aria-label='{e(label)}'>"
            f"<line class='ax' x1='{L}' x2='{W - 10}' y1='{H - B}' y2='{H - B}'/>{median}{lines}{ticks}"
            f"<polyline points='{pts}'/>{marks}</svg>")


def _per_s(v: float) -> str:
    """A damage rate on the chart's axis: 1.4M/s, 820k/s."""
    return f"{v / 1e6:.1f}M/s" if v >= 1e6 else f"{v / 1e3:.0f}k/s"


def moments_html(found: list[Moment], what: str) -> str:
    """what: kept for the callers; a moment no boss cast explains shows its time only."""
    return "".join(f"<li><b>{_mmss(m.t)}</b><span>{e(m.boss_spell) if m.boss_spell else ''}</span>"
                   f"<small>&times;{m.ratio:.1f} the fight's median</small></li>" for m in found)


def cooldowns_html(cds: list[Cooldown]) -> str:
    return "".join(
        f"<li><b>{e(c.name)}</b><small>pressed by {c.users:.0%} of the top players &middot; {c.per_kill:.1f} a kill</small>"
        "<span class='when'>" + ("".join(f"<span class='chip'>{_mmss(t)}{_near(n)}</span>"
                                        for t, n in zip(c.times, c.near, strict=False))
                                or "<small>when they need it: no moment most of them share</small>")
        + (f"<small class='alt'>some press it at {', '.join(_mmss(t) for t in c.alt)} instead</small>"
           if c.alt else "") + "</span></li>"
        for c in cds)


def _near(n: str) -> str:
    """ "0:35 Possession Barrage" -> " · Possession Barrage": the moment a press answers ("0:35" alone: the 0:35 hit,
    no boss cast to name it)."""
    if not n:
        return ""
    t, _, name = n.partition(" ")
    return f" &middot; {e(name)}" if name else f" &middot; the {e(t)} hit"


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


def builds_html(builds: list) -> str:
    copy = "<button class='btn ghost copy' data-copy='{}'>Copy the talents</button>"
    return "".join(f"<li><b>{e(b[1][:1].upper() + b[1][1:])}</b><small>{b[0]} of the top players"
                   + (f" &middot; {e(b[3])}" if len(b) > 3 and b[3] else "") + "</small>"
                   + (copy.format(e(b[2])) if b[2] else "") + "</li>" for b in builds)


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
    cds = "".join(f"<span class='chip'>{e(n)} {', '.join(_mmss(t) for t in ts) or ''}</span>"
                  for n, _k, ts in r.cd_names[:5]) if chips else ""
    return (f"<article class='hrole'><h3>{e(r.spec)}{' <small>(you)</small>' if mine else ''}</h3>"
            f"<ul class='jobs'>{''.join(f'<li>{e(j)}</li>' for j in r.jobs)}</ul>"
            f"<p class='nums'>{' · '.join(_nums(r))}</p>" + (f"<p class='when'>{cds}</p>" if cds else "")
            + f"<p class='small muted'>{r.players} {e(r.spec)}s in the kills read.</p></article>")


def contested(con, encounter_id: int, difficulty: int, spec: str, lo: float = 0.2, hi: float = 0.8,
              shown: int = 10) -> tuple[list[tuple[str, float]], int]:
    """The talents the top players of the spec split on (picked by lo to hi of them), the closest to half first,
    and how many players were read: when most play a build of their own, these explain the builds."""
    import json

    from paf.corpus.analyze import kills_filter

    try:
        from paf.gamedata import talent_entry_names

        names = talent_entry_names()
    except Exception:  # noqa: BLE001 - offline: no names, no line
        return [], 0
    where, params = kills_filter(encounter_id, difficulty)
    picks: dict[str, int] = {}
    players = 0
    for (tj,) in con.execute(f"SELECT r.talents_json FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} "
                             f"AND r.spec=? AND r.actor_id IS NOT NULL", (*params, spec)):
        got = {names.get(t["talentID"]) for t in json.loads(tj or "[]")} - {None, ""}
        if got:
            players += 1
            for n in got:
                picks[n] = picks.get(n, 0) + 1
    split = [(n, c / players) for n, c in picks.items() if players and lo <= c / players <= hi]
    return sorted(split, key=lambda x: abs(x[1] - 0.5))[:shown], players


def _and(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def build_lead(builds: list, spec: str, players: int, split: list | None = None) -> str:
    """The change tab's answer: the most played build when the top players agree on one; when their builds are
    scattered, the talents they split on (the rest they agree on)."""
    if not builds:
        return ""
    top = builds[0]
    total = sum(b[0] for b in builds)
    if split and top[0] < players / 5:  # no build a fifth of them play: the answer is in the split talents
        return (f"<p class='lead'>The top {e(spec)}s agree on most talents and split on "
                + e(_and([n for n, _s in split[:4]])) + f"; no build is played by more than {top[0]} of the "
                f"{players} players read.</p>")
    return (f"<p class='lead'>The most played build of the top {e(spec)}s: {e(top[1])}, by {top[0]} of the "
            f"{players} players read" + (f"; the {len(builds)} builds below cover {total} of them, the other "
                                        f"{players - total} play builds of their own" if len(builds) > 1 else "")
            + ".</p>")


def split_html(split: list, players: int, spec: str) -> str:
    """The talents the top players split on, with how often each is picked: what the builds above hide."""
    return (f"<h2>The talents the top {e(spec)}s split on</h2><p>Picked by this share of the {players} players "
            "read; the closest to half first:</p><ul class='hl2 split'>"
            + "".join(f"<li><b>{e(n)}</b><small>{s:.0%}</small></li>" for n, s in split) + "</ul>")


def journal_lead(lines: list[str], who: str) -> str:
    """The boss tab's answer: the abilities the Encounter Journal asks this role to handle."""
    names = list(dict.fromkeys(re.findall(r"\[([^\]]+)\]", " ".join(lines))))
    if not names and lines:  # the journal's notes without spell links: said as they are, just below
        return (f"<p class='lead'>The Encounter Journal has {len(lines)} notes for {who} on this boss, just below; "
                f"every ability follows, yours in full, the others named.</p>")
    if not names:
        return f"<p class='lead'>The Encounter Journal asks {who} nothing in particular on this boss.</p>"
    return (f"<p class='lead'>What the Encounter Journal asks {who} to handle here: {e(', '.join(names[:5]))}. Every "
            f"ability follows, yours in full, the others named.</p>")


def jobs_lead(roles: list) -> str:
    """The deeper tab's answer: the healer specs whose job stands out on this boss."""
    # a healing job of this boss: not "close to the others", nor Power Infusion given on every boss
    lines = [f"the {r.spec} {r.jobs[0]}" for r in roles
             if r.jobs and not r.jobs[0].startswith(("close to", "buffs a damage dealer"))]
    if not lines:
        return "<p class='lead'>No healer spec stands out on this boss: every one does a share of the same job.</p>"
    return "<p class='lead'>What stands out here: " + "; ".join(e(x) for x in lines) + ".</p>"


def _nums(r) -> list[str]:
    """A healer spec's numbers, each said once: one a job line already gives is left out."""
    said = " ".join(r.jobs)
    out = [f"{_pct(r.healing)} of the healers' healing", f"{_pct(r.tank)} of its healing on the tanks"]
    if "spike" not in said:
        out.append(f"{_pct(r.spike)} of it in the raid's damage spikes (the marked moments)")
    if "overheal" not in said:
        out.append(f"{_pct(r.overheal)} overheal")
    out.append(f"{r.dispels:.1f} dispels a minute")
    if "external" not in said:
        out.append(f"{r.externals:.1f} externals a kill (protective cooldowns cast on another player)")
    if r.buffs and "buffs" not in said:
        out.append(f"{r.buffs:.1f} damage buffs given a kill ({', '.join(r.buff_spells)})")
    return out


def _plain(text: str) -> str:
    """A journal line without its spell brackets: "[Soulcoil Well]" -> "Soulcoil Well"."""
    return re.sub(r"[\[\]]", "", text)


FEW_KILLS = 8  # a spec in fewer of the kills read: its numbers say little


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
    if not comps:
        return ""
    deaths = any(c.deaths is not None for c in comps)
    rows = "".join(
        f"<tr><td>{e(c.label)}</td><td class='n'>{c.kills} ({_pct(c.share)})</td><td class='n'>{_mmss(c.duration)}</td>"
        + (f"<td class='n'>{'' if c.deaths is None else f'{c.deaths:.1f}'}</td>" if deaths else "") + "</tr>"
        for c in comps)
    return ("<table class='hcomp'><thead><tr><th>Healers</th><th>Top kills</th><th>Median kill</th>"
            + ("<th>Deaths a kill</th>" if deaths else "") + f"</tr></thead><tbody>{rows}</tbody></table>"
            f"<p class='small muted'>Of {n_kills} top kills read. Exact compositions played at least 5 times; the "
            f"other {n_kills - sum(c.kills for c in comps)} kills play rarer ones.</p>")


def render_sheet(h: HealerPrep) -> str:
    """The healer's sheet: The fight (the raid damage, your cooldowns where the top healers press them), What to
    change (your spec's job here, the healers of the top kills, talents, trinkets), The boss, Dig deeper (every
    healer spec's job, the compositions, how it is measured)."""
    from paf.defensives import is_defensive
    from paf.prep_report import sheet_page

    mine = next((r for r in h.roles if r.spec == h.spec), None)
    svg = curve_svg(h.curve, h.moments, h.phases, "Raid damage taken over the fight")
    worn = {n for n, _i, _s in h.trinkets}  # an on-use trinket is no class cooldown
    items = [c for c in h.cooldowns if c.name in worn]
    heals = [c for c in h.cooldowns if not is_defensive(c.spell_id, c.name) and c not in items]
    defs = [c for c in h.cooldowns if c not in heals and c not in items]
    lead = ""
    if h.moments:
        shown = h.moments[:3]
        said = [m.boss_spell for m in shown]
        ratios = _and([f"&times;{m.ratio:.1f}" for m in shown])
        if len(set(said)) == 1 and said[0] and len(shown) > 1:  # one ability each time: said once
            hits = f"{_and([_mmss(m.t) for m in shown])}, each time {e(said[0])} ({ratios} the fight's median)"
        else:
            hits = _and([f"{_mmss(m.t)} ({e(m.boss_spell) + ', ' if m.boss_spell else ''}&times;{m.ratio:.1f})"
                         for m in shown]) + " the fight's median"
        # a cooldown said for a moment only when the top players' usual press answers it (paf.healer.ANSWER)
        answers = []
        for m in shown:
            mine_here = [c.name for c in heals if any(n and n.split(" ", 1)[0] == _mmss(m.t) for n in c.near)]
            if mine_here:
                answers.append(f"{_mmss(m.t)}: {_and(mine_here[:3])}")
        lead = (f"<p class='lead'>The raid takes the most damage at {hits}."
                + (f" Around them the top {e(h.spec)}s press: {e('; '.join(answers))}." if answers else
                   f" No healing cooldown of the top {e(h.spec)}s is kept for them.") + "</p>")
    you = []
    own = "ranked by their healing" in (h.role_sample or "")
    if mine is not None:
        you = [f"<h2>How you heal, against the other healers</h2>{role_card(mine, h.roles, True, chips=False)}"
               f"<p class='small muted'>From {h.role_kills} {e(h.role_sample or 'top kills')}."
               + (" Kills ranked by your spec's healing: your share of the healing is inflated." if own else "")
               + "</p>"]
    fight = ([lead] if lead else []) + you + [
        f"<h2>The raid damage, and its big moments</h2><div class='card'>{svg}<p class='small muted'>Damage the "
        f"raid takes per second, median of the top kills; a dot marks a big moment, "
        + ("named after the ability doing the most of the raid's damage there, measured on the same kills"
           if h.named_by_damage else "named after the boss cast just before it (&quot;after X&quot;: 8 to 30 s "
           "before, matched by timing)") + f".</p><ul class='hl2'>"
        f"{moments_html(h.moments, 'raid damage') or '<li>No big moment: steady raid damage.</li>'}</ul></div>",
        f"<h2>Your long cooldowns, where the top {e(h.spec)}s press them</h2><ul class='hl2'>"
        f"{cooldowns_html(heals) or '<li>Not enough top players in the corpus yet.</li>'}</ul>"]
    if h.rare:  # a big cooldown the top players skip is information too (Healing Tide Totem: 3 kills in 100)
        fight.append(f"<p class='small muted'>Few top {e(h.spec)}s press "
                     + ", ".join(f"{e(c.name)} ({c.users:.0%})" for c in h.rare) + " on this boss.</p>")
    if defs:
        fight.append(f"<h2>Your defensives</h2><ul class='hl2'>{cooldowns_html(defs)}</ul>")
    if items:
        fight.append(f"<h2>On-use trinkets</h2><ul class='hl2'>{cooldowns_html(items)}</ul>")
    n_kills = h.role_kills or h.kills
    change = [build_lead(h.builds, h.spec, h.kills, h.split)]
    change.append(f"<h2>Talents the top {e(h.spec)}s play</h2><ul class='hl2'>"
                  f"{builds_html(h.builds) or '<li>No build yet.</li>'}</ul>")
    if h.split:
        change.append(split_html(h.split, h.split_players, h.spec))
    trk = trinkets_html(h.trinkets) or "<li>No gear yet.</li>"
    change.append(f"<h2>Trinkets the top {e(h.spec)}s play</h2><ul class='hl2'>{trk}</ul>"
                  f"<p class='small muted'>No healing sim: these are the top players' choices, not a recommendation. "
                  f"To weigh a talent or an item for your character, use <a href=\"{QE_LIVE}\" target=\"_blank\" "
                  f"rel=\"noopener\">QE Live</a>.</p>")
    jr = "".join(f"<li>{e(_plain(x))}</li>" for x in h.journal)
    first = ([f"<p class='lead'>Your measured job here: dispel {e(h.dispelled[0][0])} ({h.dispelled[0][1]:.1f} a kill "
              f"in the top kills)." + (f" {e(h.dispel_text)}" if h.dispel_text else "") + "</p>"]
             if h.dispelled and h.dispelled[0][1] >= 1 else [journal_lead(h.journal, "healers")])
    boss = first + (
        [f"<h2>What the Encounter Journal asks healers</h2><ul class='hl2'>{jr}</ul>"] if jr else [])
    if h.dispelled:  # measured: what the top healers of the spec removed
        inside = set(re.findall(r'<b>([^<]+)</b>', h.abilities))  # the abilities the journal lists below
        boss.append(f"<h2>What the top {e(h.spec)}s dispel here</h2><p>"
                    + _and([f"{e(n)} ({k:.1f} a kill" + ("" if n in inside else ", not in the Encounter Journal")
                            + ")" for n, k in h.dispelled])
                    + f", on {h.dispel_kills} of their kills read.</p>")
    elif h.dispellable:  # where the dispels most likely go: the Journal's flags and the game data, not a measure
        boss.append("<h2>What you can dispel here</h2><p>Dispellable on this boss at this difficulty: "
                    + _and([f"{e(n)} ({e(t)})" for n, t in h.dispellable])
                    + "; your spec's dispels in the top kills most likely go to them (not measured per debuff yet)."
                    "</p>")
    elif h.dispels_checked:
        boss.append("<h2>What you can dispel here</h2><p>No ability of this boss is dispellable at this difficulty, "
                    "in the Encounter Journal or the game data: the dispels in the top kills go to other debuffs "
                    "(which ones is not measured yet).</p>")
    if h.abilities:  # every ability, the healers' in full and the others' named
        boss.append(f"<h2>Every ability, phase by phase</h2><div class='stages'>{h.abilities}</div>")
    others = "".join(role_card(r, h.roles, r.spec == h.spec, chips=r.spec != h.spec) for r in h.roles)
    few = [p.spec for p in h.presence if p.spec not in {r.spec for r in h.roles}]
    deeper_first: list[str] = [jobs_lead(h.roles)]
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
              f"{e(h.role_sample or 'top kills')}: each healer against the other healers of the same kill; a job "
              f"shows only when a number stands out beyond the sample's noise. The sample matters: kills ranked by a "
              f"healer's healing are slower, with more to heal, than the fastest kills. No healing engine: these are "
              f"the logs, not sims.</p><div class='hroles'>{others or '<p>Not measured yet.</p>'}</div>"
              + (f"<p class='small muted'>Too few healers measured: {e(', '.join(few))}.</p>" if few else ""),
              (f"<h2>The healer compositions played most</h2>{comps_table(h.comps, n_kills)}" if h.comps else "")]
    byline = (f"{e(h.character or h.spec)} &middot; {e(h.spec)} &middot; {h.kills} top kills &middot; "
              f"a {_mmss(h.duration)} fight")  # the healers' jobs say their own sample
    return sheet_page(h.boss, h.difficulty, byline, h.class_name,
                      {"fight": fight, "change": change, "boss": boss, "deeper": deeper}, theme.style("healer"))
