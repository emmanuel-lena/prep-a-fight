"""Tank prep (issue #15): what hits the tank on a boss and when, when the top tanks of your spec press their defensives
and taunt (the tank swaps), how much they keep their mitigation up. From the logs of the top tanks of the spec (the
corpus; Warcraft Logs ranks tanks by damage), no SimulationCraft: its survival numbers (DTPS, TMI) would not say
more than the logs do.

- The damage the ranked tank takes: Warcraft Logs' damage-taken graph with the tank as the source (one series per
  boss ability, about 2 points a kill, the first RAID_KILLS kills), per STEP seconds; the median over the kills. Its
  big moments (the tank busters) are named by the ability doing the most there.
- What hits the tank: each ability's median share of the tank's damage taken.
- Defensives: the spells the top tanks cast at most once every 45 s or so that most take (paf.healer.cooldowns),
  with the big moment each answers. Tank swaps: when most of them taunt (TAUNTS).
- Mitigation: the uptime of the buffs most of the top tanks have (paf.rotation.tops_buffs), highest first.
"""

from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field
from html import escape as e

from paf.healer import RAID_KILLS, SPIKE, SPIKE_GAP, STEP, Cooldown, Moment, _mmss

GRAPH = """query($c:String!,$f:[Int]!,$s:Int!,$a:Float,$b:Float){ reportData { report(code:$c) {
  graph(fightIDs:$f, dataType:DamageTaken, sourceID:$s, startTime:$a, endTime:$b) } } }"""
TAUNTS = {355: "Taunt", 6795: "Growl", 56222: "Dark Command", 115546: "Provoke", 62124: "Hand of Reckoning",
          185245: "Torment"}


@dataclass
class TankPrep:
    boss: str
    difficulty: str
    spec: str
    kills: int
    duration: float
    curve: list[float]
    moments: list[Moment]
    hitters: list[tuple[str, float]]  # ability, median share of the tank's damage taken
    cooldowns: list[Cooldown]
    swaps: list[float]  # when most top tanks taunt
    taunts_per_kill: float
    mitigation: list[tuple[str, float]]  # buff, median uptime
    builds: list[tuple[int, str, str]]
    trinkets: list[tuple[str, int, float]]
    journal: list[str]
    phases: list[tuple[str, float]] = field(default_factory=list)


def ensure_table(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS tank_damage(report TEXT, fight_id INT, step REAL, series TEXT, "
                "PRIMARY KEY(report, fight_id))")


def fetch_tank_damage(client, con, encounter_id: int, difficulty: int, limit: int = RAID_KILLS, log=print) -> int:
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM tank_damage d JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id, r.actor_id FROM fight f JOIN ranked r USING(report, fight_id) "
        f"LEFT JOIN tank_damage d USING(report, fight_id) WHERE {where} AND d.report IS NULL "
        f"AND r.actor_id IS NOT NULL ORDER BY r.rank_pos", params).fetchall()[:max(0, limit - have)]
    from paf.healer import fight_bounds, series_of

    for rep, fid, actor in todo:
        a, b = fight_bounds(client, rep, fid)
        g = client.query(GRAPH, {"c": rep, "f": [fid], "s": actor, "a": a, "b": b},
                         cache_ttl=86400)["reportData"]["report"]["graph"]
        step, series = series_of(g.get("data", g) if isinstance(g, dict) else {})
        con.execute("INSERT OR REPLACE INTO tank_damage VALUES(?,?,?,?)", (rep, fid, step, json.dumps(series)))
    con.commit()
    if todo:
        log(f"  the tank's damage taken in {len(todo)} kills")
    return len(todo)


def tank_curves(con, encounter_id: int, difficulty: int, duration: float
                ) -> tuple[list[float], dict[str, list[float]], list[tuple[str, float]]]:
    """(median damage taken per second per STEP, the same per ability, (ability, median share) of the hitters)."""
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    n = int(duration // STEP) + 1
    total: list[list[float]] = [[] for _ in range(n)]
    per_ability: dict[str, list[list[float]]] = defaultdict(lambda: [[] for _ in range(n)])
    shares: dict[str, list[float]] = defaultdict(list)
    kills = 0
    for step, series in con.execute(f"SELECT d.step, d.series FROM tank_damage d JOIN fight f "
                                    f"USING(report, fight_id) WHERE {where}", params):
        data = json.loads(series)
        kills += 1
        sums = {name: sum(v or 0 for v in values) for name, values in data.items()}
        all_damage = sum(sums.values()) or 1
        for name, v in sums.items():
            shares[name].append(v / all_damage)
        buckets = [0.0] * n
        for name, values in data.items():
            mine = [0.0] * n
            for i, v in enumerate(values):
                b = int(i * step // STEP)
                if b < n:
                    mine[b] += v or 0
                    buckets[b] += v or 0
            for b in range(n):
                per_ability[name][b].append(mine[b])
        for b in range(n):
            total[b].append(buckets[b])
    curve = [st.median(v) if v else 0.0 for v in total]
    by = {name: [st.median(v) if v else 0.0 for v in rows] for name, rows in per_ability.items()}
    hitters = sorted(((name, st.median(v + [0.0] * (kills - len(v)))) for name, v in shares.items()),
                     key=lambda x: -x[1])
    return curve, by, [h for h in hitters if h[1] >= 0.03][:8]


def tank_busters(curve: list[float], by: dict[str, list[float]], top: int = 8) -> list[Moment]:
    """The big moments of the tank's damage taken, named by the ability doing the most there."""
    base = st.median([v for v in curve if v > 0]) if any(curve) else 0.0
    if not base:
        return []
    found: list[Moment] = []
    for i, v in enumerate(curve):
        if v < SPIKE * base or (i and curve[i - 1] > v) or (i + 1 < len(curve) and curve[i + 1] > v):
            continue
        t = i * STEP
        name = max(by, key=lambda a: by[a][i] if i < len(by[a]) else 0.0, default="")
        if found and t - found[-1].t < SPIKE_GAP:
            if v > found[-1].dtps:
                found[-1] = Moment(t, v, v / base, name)
            continue
        found.append(Moment(t, v, v / base, name))
    return sorted(sorted(found, key=lambda m: -m.ratio)[:top], key=lambda m: m.t)


def swaps(con, encounter_id: int, difficulty: int) -> tuple[list[float], float]:
    """When most of the top tanks taunt (the tank swaps), and their median taunts a kill."""
    from paf.corpus.analyze import kills_filter
    from paf.defensives import peaks

    where, params = kills_filter(encounter_id, difficulty)
    per_kill: dict[tuple[str, int], list[float]] = defaultdict(list)
    kills = [tuple(r) for r in con.execute(
        f"SELECT f.report, f.fight_id FROM fight f JOIN ranked r USING(report, fight_id) WHERE {where} "
        f"AND r.actor_id IS NOT NULL", params)]
    ids = ",".join(str(i) for i in TAUNTS)
    for rep, fid, t in con.execute(
            f"SELECT c.report, c.fight_id, c.t FROM player_cast c JOIN fight f USING(report, fight_id) "
            f"JOIN ranked r ON r.report=c.report AND r.fight_id=c.fight_id AND r.actor_id=c.actor_id "
            f"WHERE {where} AND c.ability_id IN ({ids}) AND c.type='cast'", params):
        per_kill[(rep, fid)].append(t)
    if not kills:
        return [], 0.0
    lists = [per_kill.get(k, []) for k in kills]
    return peaks(lists), st.median(len(x) for x in lists)


def render(p: TankPrep) -> str:
    from paf.defensives import is_defensive
    from paf.healer import (
        builds_html,
        cooldowns_html,
        curve_svg,
        moments_html,
        page,
        trinkets_html,
    )

    defs = [c for c in p.cooldowns if is_defensive(c.spell_id, c.name)]
    others = [c for c in p.cooldowns if c not in defs]
    svg = curve_svg(p.curve, p.moments, p.phases, "Damage the tank takes over the fight")
    hit = "".join(f"<li><b>{e(n)}</b><small>{s:.0%} of the damage you take</small></li>" for n, s in p.hitters)
    swap = ("".join(f"<span class='chip'>{_mmss(t)}</span>" for t in p.swaps)
            if p.swaps else "")
    mit = "".join(f"<li><b>{e(n)}</b><small>up {u:.0%} of the fight for the top tanks</small></li>"
                  for n, u in p.mitigation)
    jr = "".join(f"<li>{e(x)}</li>" for x in p.journal)
    body = f"""<h1>{e(p.boss)} <span class="pill gold">{e(p.difficulty)}</span></h1>
<p class="lead">{e(p.spec)}: the tank's prep, from {p.kills} kills of the top tanks of your spec. A {_mmss(p.duration)}
fight.</p>
<section class="hp-sec"><h2>What hits you, and when</h2>{svg}
<p class="small muted">Damage the top tanks take per second, median of the kills; a dot marks a tank buster.</p>
<ul class="hl2">{moments_html(p.moments, "tank damage") or '<li>No big moment: steady damage.</li>'}</ul></section>
<section class="hp-sec"><h2>The abilities that hit you the most</h2><ul class="hl2">{hit or '<li>Not measured yet.</li>'}</ul>
</section>
<section class="hp-sec"><h2>Your defensives, where the top tanks press them</h2>
<ul class="hl2">{cooldowns_html(defs) or '<li>No defensive most top tanks share: they spread them.</li>'}</ul></section>
{f'<section class="hp-sec"><h2>Your other cooldowns</h2><ul class="hl2">{cooldowns_html(others)}</ul></section>' if others else ''}
<section class="hp-sec"><h2>Tank swaps</h2><p>The top tanks taunt about <b>{p.taunts_per_kill:.0f}</b> times a kill{', most of them at:' if swap else '.'}</p>
<ul class="hl2"><li><span class='when'>{swap}</span></li></ul></section>
<section class="hp-sec"><h2>Your mitigation</h2><ul class="hl2">{mit or '<li>Not measured yet.</li>'}</ul></section>
<section class="hp-sec"><h2>Talents</h2><ul class="hl2">{builds_html(p.builds) or '<li>No build yet.</li>'}</ul></section>
<section class="hp-sec"><h2>Trinkets the top tanks play</h2><ul class="hl2">{trinkets_html(p.trinkets) or '<li>No gear yet.</li>'}</ul></section>
{f'<section class="hp-sec"><h2>What the Encounter Journal asks tanks</h2><ul class="hl2">{jr}</ul></section>' if jr else ''}"""
    return page(f"{p.boss} prep", body)
