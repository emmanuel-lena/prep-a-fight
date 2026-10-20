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
from dataclasses import dataclass, field, replace
from html import escape as e

from paf import theme
from paf.healer import (
    ANSWER,
    RAID_KILLS,
    RELATIVE,
    SPIKE,
    SPIKE_GAP,
    STEP,
    UNSIMMED,
    Cooldown,
    Moment,
    _and,
    _mmss,
    moment_names,
)
from paf.theme import diff_pill

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
    swaps: list[float]  # when most top tanks taunt (the pull's taunt left out)
    taunts_per_kill: float
    mitigation: list[tuple[str, float]]  # buff, median uptime
    builds: list[tuple[int, str, str]]
    trinkets: list[tuple[str, int, float]]
    journal: list[str]
    phases: list[tuple[str, float]] = field(default_factory=list)
    comps: list = field(default_factory=list)  # paf.healroles.Comp of the tanks
    presence: list = field(default_factory=list)  # paf.healroles.Presence of every tank spec
    swap_after: list[str] = field(default_factory=list)  # the boss cast just before each swap
    rare: list = field(default_factory=list)  # defensives a quarter to a half of the top tanks press
    class_name: str = ""
    character: str = ""
    abilities: str = ""  # the Encounter Journal's stages, the tanks' abilities in full (paf.bossguide), html
    stacks: dict = field(default_factory=dict)  # debuff on the top tanks -> (peak stacks, seconds each cycle)
    swap_debuff: str = ""  # the tank ability whose debuff the tanks swap on (measured on them)
    no_taunt: list = field(default_factory=list)  # (ability, its journal sentence): when taunts stop working
    hero: list = field(default_factory=list)  # (hero tree, share of the top players), paf.healer.hero_split
    short_defs: list = field(default_factory=list)  # (spell, share of the top tanks, casts a kill): too frequent
    # for a cooldown, too short for an uptime (Spell Reflection, Demoralizing Shout)
    split: list = field(default_factory=list)  # (talent, share picked) the top players split on
    split_players: int = 0


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
        # the buckets this kill lasts: a finished kill is no zero damage (the curve fell at the end, "the boss gets
        # easy", as the shorter kills ended)
        lasts = min(n, int((max((len(v) for v in data.values()), default=0) * step) // STEP))
        for name, values in data.items():
            mine = [0.0] * n
            for i, v in enumerate(values):
                b = int(i * step // STEP)
                if b < n:
                    mine[b] += v or 0
                    buckets[b] += v or 0
            for b in range(lasts):
                per_ability[name][b].append(mine[b])
        for b in range(lasts):
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
        if v < SPIKE * 0.9 * base or (i and curve[i - 1] > v) or (i + 1 < len(curve) and curve[i + 1] > v):
            continue
        t = i * STEP
        name = max(by, key=lambda a: by[a][i] if i < len(by[a]) else 0.0, default="")
        if found and t - found[-1].t < SPIKE_GAP:
            if v > found[-1].dtps:
                found[-1] = Moment(t, v, v / base, name)
            continue
        found.append(Moment(t, v, v / base, name))
    # every hit near the highest, as paf.healer.moments: a line at x1.5 kept one of Vashnik's four
    highest = max((m.ratio for m in found), default=0.0)
    found = [m for m in found if highest >= SPIKE and m.ratio >= max(SPIKE * 0.9, RELATIVE * highest)]
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
    lists = [[t for t in per_kill.get(k, []) if t >= PULL_TAUNT] for k in kills]  # the pull's taunt is no swap
    return peaks(lists), st.median(len(x) for x in lists)


PULL_TAUNT = 5.0  # seconds: a taunt this early picks the boss up, it is no swap
STACK_KILLS = 6  # kills read for the boss debuffs on the top tanks: ~1 page of events each


def fetch_stacks(client, con, encounter_id: int, difficulty: int, kills: int = STACK_KILLS,
                 log=lambda s: print(s, flush=True)) -> int:
    """The debuffs on the ranked tank of a few kills, each cycle (application to fall): its peak stacks and how
    long it stays. What a swap answers: Vashnik's Dripping Fangs is one debuff (no stacks) that lasts until the
    other tank taunts. WCL's targetID filter returns nothing on Debuffs: read them all, keep the tank's."""
    from paf.corpus.analyze import kills_filter
    from paf.healroles import BOUNDS
    from paf.wcl import WCLError

    ensure_debuff_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM tank_debuff_status s JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id, r.actor_id FROM fight f JOIN ranked r USING(report, fight_id) "
        f"LEFT JOIN tank_debuff_status s USING(report, fight_id) WHERE {where} AND s.report IS NULL "
        f"AND r.actor_id IS NOT NULL ORDER BY f.report LIMIT ?", (*params, max(0, kills - have))).fetchall()
    for rep, fid, actor in todo:
        try:
            fr = client.query(BOUNDS, {"c": rep, "f": [fid]}, cache_ttl=0)["reportData"]["report"]["fights"][0]
            events = list(client.events(rep, fid, fr["startTime"], fr["endTime"], data_type="Debuffs",
                                        hostility="Friendlies", cache=False))
        except (WCLError, KeyError, TypeError, IndexError, OSError) as e:
            log(f"  tank debuffs skipped: {str(e)[:100]}")
            continue
        con.executemany("INSERT INTO tank_debuff VALUES(?,?,?,?,?)",
                        [(rep, fid, a, p, d) for a, p, d in debuff_cycles(events, actor)])
        con.execute("INSERT OR REPLACE INTO tank_debuff_status VALUES(?,?)", (rep, fid))
        con.commit()
    return len(todo)


def ensure_debuff_tables(con) -> None:
    con.executescript("CREATE TABLE IF NOT EXISTS tank_debuff(report TEXT, fight_id INT, ability_id INT, peak INT, "
                      "seconds REAL);"
                      "CREATE TABLE IF NOT EXISTS tank_debuff_status(report TEXT, fight_id INT, "
                      "PRIMARY KEY(report, fight_id));")


def debuff_cycles(events: list[dict], actor: int) -> list[tuple[int, int, float]]:
    """(debuff, peak stacks, seconds) of each cycle of a debuff on the tank: from its application to its fall."""
    now: dict[int, list] = {}
    out = []
    for ev in events:
        if ev.get("targetID") != actor:
            continue
        a, kind, t = ev.get("abilityGameID"), ev.get("type"), ev.get("timestamp", 0)
        if kind == "applydebuff":
            now[a] = [1, t]
        elif kind == "applydebuffstack" and a in now:
            now[a][0] = max(now[a][0], int(ev.get("stack") or 0))
        elif kind == "removedebuff" and a in now:
            peak, start = now.pop(a)
            out.append((a, peak, round((t - start) / 1000, 1)))
    return out


def stacks(con, encounter_id: int, difficulty: int, names: dict[int, str]) -> dict[str, tuple[int, float]]:
    """Debuff name -> (median peak stacks, median seconds on the tank), for a debuff seen on at least 3 kills."""
    from paf.corpus.analyze import kills_filter

    ensure_debuff_tables(con)
    where, params = kills_filter(encounter_id, difficulty)
    per: dict[int, list[tuple[int, float]]] = defaultdict(list)
    seen: dict[int, set] = defaultdict(set)
    for rep, fid, a, p, d in con.execute(f"SELECT t.report, t.fight_id, t.ability_id, t.peak, t.seconds "
                                         f"FROM tank_debuff t JOIN fight f USING(report, fight_id) WHERE {where}",
                                         params):
        per[a].append((p, d))
        seen[a].add((rep, fid))
    return {names.get(a, f"spell {a}"): (round(st.median(p for p, _ in v)), st.median(d for _, d in v))
            for a, v in per.items() if len(seen[a]) >= 3}


def swap_causes(swaps: list[float], boss_casts: list[tuple[str, list[float]]], before: float = 8.0) -> list[str]:
    """The boss cast just before each swap (a stacking debuff's hit, a tank buster), or "" when none is close."""
    out = []
    for t in swaps:
        near = [(t - c, n) for n, ts in boss_casts for c in ts if -1.0 <= t - c <= before]
        out.append(min(near)[1] if near else "")
    return out


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

    mit = "".join(f"<li><b>{e(n)}</b><small>up {u:.0%} of the kill for the top tanks</small></li>"
                  for n, u in p.mitigation)
    defs = [c for c in p.cooldowns if is_defensive(c.spell_id, c.name)]
    others = [c for c in p.cooldowns if c not in defs]
    svg = curve_svg(p.curve, p.moments, p.phases, "Damage the tank takes over the fight")
    hit = "".join(f"<li><b>{e(n)}</b><small>{s:.0%} of the damage you take</small></li>" for n, s in p.hitters)
    swap = ("".join(f"<span class='chip'>{_mmss(t)}</span>" for t in p.swaps)
            if p.swaps else "")
    mit = "".join(f"<li><b>{e(n)}</b><small>up {u:.0%} of the fight for the top tanks</small></li>"
                  for n, u in p.mitigation)
    jr = "".join(f"<li>{e(x)}</li>" for x in p.journal)
    body = f"""<h1>{e(p.boss)} {diff_pill(p.difficulty)}</h1>
<p class="lead">{e(p.spec)}: the tank's prep, from {p.kills} kills of the top tanks of your spec. A {_mmss(p.duration)}
fight.</p>
<section class="hp-sec"><h2>What hits you, and when</h2>{svg}
<p class="small muted">Damage the top tanks take per second, median of the kills; a dot marks the tanks' biggest damage, whatever casts it.</p>
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


def swap_debuff(stacks: dict, tank_abilities: set[str]) -> str:
    """The debuff the tanks swap on: of the journal's tank abilities measured on the top tanks, a stacking one first
    (Nek'zali: Hollowing Strikes, 8 stacks), else the one that stays the longest (Vashnik: Dripping Fangs, 32 s)."""
    mine = {n: v for n, v in stacks.items() if n in tank_abilities and v[1] >= 10}
    if not mine:
        return ""
    return max(mine, key=lambda n: (mine[n][0] >= 2, mine[n][0], mine[n][1]))


def _taunt(spell_id: int) -> bool:
    try:
        from paf.gamedata import is_taunt

        return is_taunt(spell_id)
    except Exception:  # noqa: BLE001 - offline: listed
        return False


def taunt_immunity(sections, difficulty: str) -> list[tuple[str, str]]:
    """The journal's sentences that stop the swaps (Nek'zali's Uncoiled Rage: "grants immunity to Taunt effects")."""
    import re

    from paf import bossguide
    from paf.mechanics import walk

    out = []
    for _, s in walk(sections):
        text = bossguide.readable(s.text or bossguide.describe(s.spell_id), difficulty)  # as the boss tab
        if re.search(r"immun\w* to taunt", text, re.I) and s.title not in {n for n, _ in out}:
            out.append((s.title, text.strip()))  # the whole text: "Additionally, ..." needs what comes before
    return out


def _cause(common: str, stacks: dict) -> str:
    """What most swaps follow, measured on the top tanks: the stacks of a stacking debuff, or a debuff they never
    let stack and how long it stays; else a timing."""
    if common in stacks:
        peak, secs = stacks[common]
        return (f" (most of them at about {peak} stacks of {e(common)}, reached in about {secs:.0f} s; measured on "
                f"the top tanks)" if peak >= 2 else
                f" (most of them right after {e(common)}: the top tanks never take a second stack; the debuff "
                f"lasts about {secs:.0f} s)")
    return f" (most of them right after {e(common)}: a timing in the logs)"


def render_sheet(p: TankPrep) -> str:
    """The tank's sheet in the four sections of every role's sheet (issue #27): The fight (what hits you and when,
    your defensives where the top tanks press them, the swaps), What to change (mitigation, talents, trinkets), The
    boss (the abilities that hit you, the journal), Dig deeper (your other cooldowns, the top raids' tanks)."""
    from paf.defensives import is_defensive
    from paf.healer import (
        _plain as plain,
    )
    from paf.healer import (
        build_lead,
        comps_table,
        cooldowns_html,
        count,
        curve_svg,
        journal_lead,
        moments_html,
        presence_table,
        split_html,
        talents_html,
        trinkets_html,
    )
    from paf.prep_report import sheet_page

    mit = "".join(f"<li><b>{e(n)}</b><small>up {u:.0%} of the kill for the top tanks</small></li>"
                  for n, u in p.mitigation) + "".join(
        f"<li><b>{e(n)}</b><small>pressed {count(k)} times a kill by {u:.0%} of the top tanks"
        + (f" &middot; on cooldown, about every {ev:.0f} s" if ev else "") + "</small>"
        + (f"<span class='when'>{''.join(f'<span class=chip>{_mmss(t)}</span>' for t in ts)}</span>" if ts else "")
        + "</li>" for n, u, k, ts, ev in p.short_defs)
    defs = [c for c in p.cooldowns if is_defensive(c.spell_id, c.name)]
    others = [replace(c, near=["" for _ in c.near]) for c in p.cooldowns  # no buster to answer; taunts: the swaps
              if c not in defs and not _taunt(c.spell_id)]
    svg = curve_svg(p.curve, p.moments, p.phases, "Damage the top tanks take over the fight, and their defensives",
                    defs)
    causes = p.swap_after or ["" for _ in p.swaps]
    named = [c for c in causes if c]
    common = max(set(named), key=named.count) if named else ""
    one = bool(common) and named.count(common) >= len(causes) / 2  # one ability behind most swaps: said once
    if p.swap_debuff:  # measured on the top tanks: what they swap on; a cast just before is no cause then
        common, one = p.swap_debuff, True
        causes = ["" for _ in p.swaps]
    swap = "".join(f"<span class='chip'>{_mmss(t)}{f' after {e(c)}' if c and not (one and c == common) else ''}</span>"
                   for t, c in zip(p.swaps, causes, strict=False))
    lead = []
    if p.hitters:  # what hits the tanks over the fight first: their own danger, not the raid's
        lead.append(f"What hits the top tanks the most: {_and([f'{e(n)} ({s:.0%})' for n, s in p.hitters[:2]])} "
                    f"of their damage taken.")
    if p.moments:
        m = max(p.moments, key=lambda x: x.ratio)
        own = bool(set(moment_names(m)) & {n for n, _s in p.hitters[:3]})  # any of its abilities a tank hitter
        answers = [(c.name, c.times) for c in defs if not c.every] + [(n, ts) for n, _u, _k, ts, _ev in p.short_defs]
        press = next(((n, t) for n, ts in answers for t in ts if -ANSWER[0] <= t - m.t <= ANSWER[1]), None)
        lead.append(f"Their biggest moment: {_mmss(m.t)}, {e(m.boss_spell or 'tank damage')} ({m.ratio:.1f}&times; the "
                    f"usual damage" + ("" if own else ", raid damage the tanks take too") + ")"
                    + (f"; the top {e(p.spec)}s press {e(press[0])} for it." if press
                       else f"; most top {e(p.spec)}s press no defensive for it."))
    if p.swaps:
        lead.append(f"Each of them taunts about {p.taunts_per_kill:.0f} times a kill after the pull (adds included)"
                    + ((f", most often at about {p.stacks[common][0]} stacks of {e(common)}." if common in p.stacks
                        and p.stacks[common][0] >= 2 else f", swapping after each {e(common)} (the debuff lasts "
                        f"about {p.stacks[common][1]:.0f} s; they never take a second stack)." if common in p.stacks
                        else f", most often right after {e(common)} (a timing, not a measured cause).")
                       if one else
                       f", the first time at {_mmss(p.swaps[0])}" + (f" after {e(causes[0])}." if causes[0] else ".")))
    fight = ([f"<p class='lead'>{' '.join(lead)}</p>"] if lead else []) + [
        f"<h2>What hits the top tanks, and when</h2><div class='card'>{svg}<p class='small muted'>Damage the top tanks "
        f"take per second, median of the kills; a dot marks the tanks' biggest damage, whatever casts it.</p><ul class='hl2'>"
        f"{moments_html(p.moments, 'tank damage') or '<li>No big moment: steady damage.</li>'}</ul></div>",
        f"<h2>Your defensives, where the top {e(p.spec)}s press them</h2><ul class='hl2'>"
        f"{cooldowns_html(defs) or '<li>No defensive most top tanks share: they spread them.</li>'}</ul>"
        + (f"<p class='small muted'>Fewer of them press: {', '.join(f'{e(c.name)} ({c.users:.0%})' for c in p.rare)}."
           f"</p>" if p.rare else ""),
        f"<h2>Active mitigation and short defensives the top tanks use</h2><ul class='hl2'>"
        f"{mit or '<li>Not measured yet.</li>'}</ul>",
        f"<h2>Tank swaps</h2><p>{'The swap moments most top raids share' if swap else 'No swap moment most top raids share.'}"
        f"{_cause(common, p.stacks) if swap and one else ''}"
        f"{':' if swap else ''}</p>" + (f"<ul class='hl2'><li><span class='when'>{swap}</span>"
                                                          f"</li></ul>" if swap else "")
        + "".join(f"<p><b>Taunts stop working with {e(n)}:</b> {e(t)} <span class='muted'>(The Encounter Journal; "
                  f"whether the top kills reach it is not measured.)</span></p>" for n, t in p.no_taunt)]
    change = [build_lead(p.builds, p.spec, p.split_players or p.kills, p.split),
              talents_html(p.builds, p.split_players or p.kills, f"{p.spec}s", p.hero),
              split_html(p.split, p.split_players, p.spec) if p.split else "",
              f"<h2>Trinkets the top {e(p.spec)}s play</h2><ul class='hl2'>"
              f"{trinkets_html(p.trinkets) or '<li>No gear yet.</li>'}</ul>",
              "<p class='small muted'>No tank sim: these are the top players' choices, not a recommendation.</p>"]
    hit = "".join(f"<li><b>{e(n)}</b><small>{s:.0%} of the damage the top tanks take</small></li>"
                  for n, s in p.hitters)
    jr = "".join(f"<li>{e(plain(x))}</li>" for x in p.journal)
    # the tank's answer here: the swap (the fight tab's lead, its last sentence), else the journal's ask
    # the boss tab's answer: the mechanic the swaps follow (the fight tab says the swaps), else the journal's ask
    top_hit = (f"<p class='lead'>The swaps follow {e(common)}{_cause(common, p.stacks)}.</p>"
               if p.swaps and one and common in p.stacks else journal_lead(p.journal, "tanks"))
    boss = [top_hit, f"<h2>The abilities that hit the top tanks the most</h2><ul class='hl2'>{hit or '<li>Not measured yet.</li>'}</ul>"]
    if jr:
        boss.append(f"<h2>What the Encounter Journal asks tanks</h2><ul class='hl2'>{jr}</ul>")
    if p.abilities:  # every ability, the tanks' in full and the others' named
        boss.append(f"<h2>Every ability{', phase by phase' if '<h3>' in p.abilities else ''}</h2>"
                    f"<div class='stages'>{p.abilities}</div>")
    have = next((x for x in p.presence if x.spec == p.spec), None)
    deeper = []
    if have and p.presence:
        mates = [x for x in p.presence if x.spec != p.spec and x.kills >= 8]
        deeper.append(f"<p class='lead'>Beside a {e(p.spec)}, the top raids play "
                      + (", ".join(f"{e(x.spec)} (in {x.share:.0%} of the kills)"
                                   for x in sorted(mates, key=lambda x: -x.share)[:3])
                         if mates else "no other tank spec often") + ".</p>")
    worn = {n for n, _i, _s in p.trinkets}  # on-use trinkets on the fight tab, as the healers' sheets
    items = [c for c in others if c.name in worn]
    rest = [c for c in others if c not in items]
    from paf.healer import _item

    used = [c for c in rest if _item(c.spell_id)]  # potions: the deeper tab
    damage = [c for c in rest if c not in used]  # Avatar, Shield Charge: pressed by all of them, the fight tab
    if damage:
        fight.append(f"<h2>Your damage cooldowns</h2><ul class='hl2'>{cooldowns_html(damage)}</ul>")
    if items:
        fight.append(f"<h2>On-use trinkets</h2><ul class='hl2'>{cooldowns_html(items)}</ul>")
    if used:
        deeper.append(f"<h2>Consumables</h2><ul class='hl2'>{cooldowns_html(used)}</ul>")
    if p.presence:
        if have and have.share >= 0.99:  # the corpus is this spec's kills
            line = f"These are the top {e(p.spec)}s' kills; the table tells which tanks play beside them."
        elif have:
            line = f"{have.share:.0%} of the top kills bring a {e(p.spec)} ({have.per_kill:.1f} a kill when they do)."
        else:
            line = f"Few top raids bring a {e(p.spec)} on this boss."
        deeper.append(f"<h2>The top raids' tanks</h2><p>{line}</p>{presence_table(p.presence, p.spec, 'Tank')}"
                      + comps_table(p.comps, p.kills).replace("Healers", "Tanks"))
        deaths = any(x.deaths_with is not None for x in p.presence)
        deeper.append("<p class='small muted'>" + ("" if deaths else "The deaths of each composition are not read yet. ")
                      + "A spec's longer kills or extra deaths are a reading, not a verdict: the raids that bring it "
                      "differ in other ways too, and a few kills move a mean of deaths.</p>")
    byline = (f"{e(p.character or p.spec)} &middot; {e(p.spec)} &middot; {p.kills} top kills for the timings and "
              f"talents, median {_mmss(p.duration)} &middot; read from the logs, no tank sim")
    return sheet_page(p.boss, p.difficulty, byline, p.class_name,
                      {"fight": fight, "change": change, "boss": boss, "deeper": deeper}, theme.style("healer"),
                      UNSIMMED)
