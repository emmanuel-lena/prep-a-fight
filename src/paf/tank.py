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
    STAGE_TERM,
    STEP,
    UNSIMMED,
    Cooldown,
    Moment,
    _mmss,
    _pct,
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
    no_taunt: list = field(default_factory=list)  # (ability, its journal text, kills reaching it, kills read)
    hero: list = field(default_factory=list)  # (hero tree, share of the top players), paf.healer.hero_split
    damage_kills: int = 0  # kills the tanks' damage curve is the median of
    short_defs: list = field(default_factory=list)  # (spell, share of the top tanks, casts a kill): too frequent
    # for a cooldown, too short for an uptime (Spell Reflection, Demoralizing Shout)
    split: list = field(default_factory=list)  # (talent, share picked) the top players split on
    split_marks: dict = field(default_factory=dict)  # the most played build's side of each split row
    split_players: int = 0
    split_wide: bool = False  # no talent 35-65%: the talents they differ on most (paf.healer.split_html)


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


def tank_curves(con, encounter_id: int, difficulty: int, duration: float, clock=None
                ) -> tuple[list[float], dict[str, list[float]], list[tuple[str, float]]]:
    """(median damage taken per second per STEP, the same per ability, (ability, median share) of the hitters); with
    a stage clock (paf.stagetime), each kill in stage time (round 100)."""
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    n = int(duration // STEP) + 1
    total: list[list[float]] = [[] for _ in range(n)]
    per_ability: dict[str, list[list[float]]] = defaultdict(lambda: [[] for _ in range(n)])
    shares: dict[str, list[float]] = defaultdict(list)
    kills = 0
    for rep, fid, step, series in con.execute(f"SELECT d.report, d.fight_id, d.step, d.series FROM tank_damage d "
                                              f"JOIN fight f USING(report, fight_id) WHERE {where}", params):
        def at(t: float, k=(rep, fid)) -> float | None:
            return clock.at(k, t) if clock else t
        data = json.loads(series)
        kills += 1
        sums = {name: sum(v or 0 for v in values) for name, values in data.items()}
        all_damage = sum(sums.values()) or 1
        for name, v in sums.items():
            shares[name].append(v / all_damage)
        buckets = [0.0] * n
        # the buckets this kill lasts: a finished kill is no zero damage (the curve fell at the end, "the boss gets
        # easy", as the shorter kills ended)
        # the buckets this kill covers: its seconds in stage time (a stage that came early leaves a gap before the
        # next one's median start: no zero damage there either)
        covered = {int(x // STEP) for i in range(max((len(v) for v in data.values()), default=0))
                   if (x := at(i * step)) is not None and int(x // STEP) < n}
        for name, values in data.items():
            mine = [0.0] * n
            for i, v in enumerate(values):
                x = at(i * step)
                if x is None:
                    continue
                b = int(x // STEP)
                if b < n:
                    mine[b] += v or 0
                    buckets[b] += v or 0
            for b in sorted(covered):
                per_ability[name][b].append(mine[b])
        for b in sorted(covered):
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
        if found and t - found[-1].t <= SPIKE_GAP:  # 15 s apart is one stretch (Stage Two's 3:25, 3:40, 3:55)
            if v > found[-1].dtps:
                found[-1] = Moment(t, v, v / base, name)
            continue
        found.append(Moment(t, v, v / base, name))
    # every hit near the highest, as paf.healer.moments: a line at x1.5 kept one of Vashnik's four
    highest = max((m.ratio for m in found), default=0.0)
    found = [m for m in found if highest >= SPIKE and m.ratio >= max(SPIKE * 0.9, RELATIVE * highest)]
    return sorted(sorted(found, key=lambda m: -m.ratio)[:top], key=lambda m: m.t)


def swaps(con, encounter_id: int, difficulty: int, clock=None) -> tuple[list[float], float]:
    """When most of the top tanks taunt (the tank swaps), and their median taunts a kill; with a stage clock
    (paf.stagetime), in stage time, as the curve."""
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
        x = clock.at((rep, fid), t) if clock else t
        if x is not None:
            per_kill[(rep, fid)].append(x)
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
    from paf.wcl import WCLDown, WCLError, WCLQuota

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
            if isinstance(e, (WCLDown, WCLQuota)):  # one line, not one a kill (issue #36)
                log(f"  tank debuffs stopped: {str(e)[:100]}; the rest is read on a later prep")
                break
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

    mit = "".join(f"<li><b>{e(n)}</b><b class='upn'>{u:.0%}</b><small>uptime</small></li>"
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
<section class="hp-sec"><h2>Trinkets the top tanks equip</h2><ul class="hl2">{trinkets_html(p.trinkets) or '<li>No gear yet.</li>'}</ul></section>
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


def reached(con, encounter_id: int, difficulty: int, name: str) -> tuple[int, int]:
    """(kills where the boss casts or gains `name`, kills read): a journal mechanic the top kills may never reach
    (Nek'zali's Uncoiled Rage, a full-energy enrage: 0 of them)."""
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    ids = [r[0] for r in con.execute("SELECT id FROM ability WHERE name=?", (name,))]
    n = con.execute(f"SELECT COUNT(*) FROM fight f WHERE {where}", params).fetchone()[0]
    if not ids:
        return 0, n
    marks = ",".join("?" * len(ids))
    hit = con.execute(
        f"SELECT COUNT(DISTINCT f.report || f.fight_id) FROM fight f WHERE {where} AND ("
        f"EXISTS (SELECT 1 FROM boss_aura b WHERE b.report=f.report AND b.fight_id=f.fight_id "
        f"AND b.ability_id IN ({marks})) OR EXISTS (SELECT 1 FROM enemy_cast c WHERE c.report=f.report "
        f"AND c.fight_id=f.fight_id AND c.ability_id IN ({marks})))", (*params, *ids, *ids)).fetchone()[0]
    return hit, n


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


def _none_for(note: str) -> str:
    """The biggest moment with no defensive kept: its aside said as the sentence, not twice (round 62)."""
    if note == " (no long defensive of theirs pressed by a tenth of them in it)":
        return "; no long defensive of theirs is pressed by a tenth of them in it."
    return f"; no defensive of theirs is kept for it{note}."


# how to read the defensive cards, one term a line (the owner: less text; every rule kept, said once)
TANK_HOW_TO_READ = (
    "<dl class='legend'><dt>N%</dt><dd>of the top players read; &ldquo;(N kills going)&rdquo;: of the kills still "
    "going then (a moment's window: those lasting through it); &ldquo;of its users&rdquo;: of the top players who "
    "press the button.</dd><dt>Tied to a moment</dt>"  # the table's word (review 36)
    "<dd>pressed in the moment's window (5 s before to 8 s after; a moment of 1.5&times; the usual damage or more "
    "is a hit) by a quarter of its users; its share is the "
    "window's.</dd><dt>A time</dt><dd>shared by a quarter of "
    "those who press the button; its share: the top players pressing within 8 s of it (&ldquo;of its users&rdquo; "
    "too, under a quarter).</dd><dt>On cooldown</dt><dd>pressed every time it comes back, all kill long."
    "</dd><dt>&#10226; back from cooldown</dt><dd>most of its players press it as soon as it is back: not saved for the hit, "
    "not counted for it (&#10226;&nbsp;about half: 40 to 60% of them).</dd><dt>&ldquo;or&rdquo;</dt><dd>another "
    "time some top players press it instead.</dd><dt>not kept</dt><dd>pressed in a moment's window, but not that "
    "moment's answer in the table.</dd></dl>")


def render_sheet(p: TankPrep) -> str:
    """The tank's sheet in the four sections of every role's sheet (issue #27): The fight (what hits you and when,
    your defensives where the top tanks press them, the swaps), What to change (mitigation, talents, trinkets), The
    boss (the abilities that hit you, the journal), Dig deeper (your other cooldowns, the top raids' tanks)."""
    from paf.defensives import is_defensive
    from paf.healer import (
        SWAP_LANE,
        _chip,
        _share,
        build_lead,
        comps_table,
        cooldowns_html,
        count,
        curve_svg,
        journal_lead,
        landed_in,
        presence_table,
        rare_html,
        split_html,
        talents_html,
        trinkets_html,
    )
    from paf.healer import (
        _plain as plain,
    )
    from paf.prep_report import sheet_page

    def mit_html(answered: set) -> str:
        """Active mitigation and the short defensives; a chip says its hit for the lead's presses only, as the
        cooldown rows (Spell Reflection at 0:33 for the 0:35 hit)."""
        def hit_of(n: str, t: float) -> str:
            m = next((m for m in p.moments if (n, t) in answered and -ANSWER[0] <= t - m.t <= ANSWER[1]), None)
            return f"{_mmss(m.t)} hit" if m else ""

        def _of_pressers(x: float, u: float) -> str:  # under a quarter, also of those who press it (round 89)
            return (f" ({_pct(min(1.0, x / u))} of its users)"
                    if x and x < 0.25 and u and _pct(x / u) != _pct(x) else "")

        def why(n: str, t: float) -> str:  # untied in a hit's window: the reason said (round 88: Spell Reflection at
            if hit_of(n, t):                # 2:59, in the 2:55 melee hit's window, with no word why)
                return ""
            from paf.gamedata import magic_only, physical_only, same_name_spells
            m = next((m for m in p.moments if -ANSWER[0] <= t - m.t <= ANSWER[1]), None)
            if m is None or not moment_names(m) or not all(physical_only(x) for x in moment_names(m)):
                return ""
            if not any(magic_only(i) for i in same_name_spells().get(n, [])):
                return ""
            return f" &middot; no answer to the physical {_mmss(m.t)} hit (magic only)"
        from paf.icons import img

        def ic(n: str) -> str:  # its spell's icon (paf.healer.add_icons), none offline
            got = getattr(p, "name_icons", {}).get(n, "")
            return img(got, "small", "ics") if got else ""
        return "".join(f"<li><b>{ic(n)}{e(n)}</b><small><span class='use' title='up {u:.0%} of the kill'>"  # one bar
                       f"<span class='ubar'><span style='width:{u * 100:.0f}%'></span></span>{u:.0%}</span> uptime"
                       "</small></li>"  # style for the section (fresh heal review: two bars in one section)
                       for n, u in p.mitigation) + "".join(
            f"<li><b>{ic(n)}{e(n)}</b><small><span class='use' title='pressed by {u:.0%} of the top players'>"  # the
            f"<span class='ubar'><span style='width:{u:.0%}'></span></span>{u:.0%}</span> &middot; {count(k)}/kill"
            + (f" <span class='pill rhythm' title='pressed every time it is back'>&#9719; every {ev:.0f} s</span>"
               if ev else "") + "</small>"  # the cards' one form: a bar, N/kill, the rhythm a badge (fresh heal review)
            + ("<span class='when'>" + "".join(f"<span class='chip'>{_chip(moved_t.get((n, t), t), hit_of(n, t))}"
                                               f"{_share(x := tied.get((n, t), sp) if hit_of(n, t) else sp)}"
                                               f"{_of_pressers(x, u)}{why(n, t)}</span>"  # no hit named: none (heal round 17: "not on a big hit" twice)
                                               for t, sp in zip(ts, sps, strict=False))
               + (f"<small class='alt'>+{round(k) - len(ts)} more at varying times</small>"  # every press counted, as
                  if not ev and round(k) > len(ts) else "")  # the cards (heal round 16: "3 a kill", two chips)
               + "</span>" if ts else "")
            + "</li>" for n, u, k, ts, ev, sps, *_rest in p.short_defs)
    defs = [c for c in p.cooldowns if is_defensive(c.spell_id, c.name)]

    def nouned(html: str) -> str:  # the cards' noun as the lead's: a moment under 1.5x is no hit (round 104)
        for m in p.moments:
            if m.ratio < 1.5:
                html = html.replace(f"the {_mmss(m.t)} hit", f"the {_mmss(m.t)} moment").replace(
                    f"the physical {_mmss(m.t)} hit", f"the physical {_mmss(m.t)} moment")
        return html
    others = [replace(c, near=["" for _ in c.near]) for c in p.cooldowns  # no buster to answer; taunts: the swaps
              if c not in defs and not _taunt(c.spell_id)]
    causes = p.swap_after or ["" for _ in p.swaps]
    named = [c for c in causes if c]
    common = max(set(named), key=named.count) if named else ""
    one = bool(common) and named.count(common) >= len(causes) / 2  # one ability behind most swaps: said once
    if p.swap_debuff:  # measured on the top tanks: what they swap on; a cast just before is no cause then
        common, one = p.swap_debuff, True
        causes = ["" for _ in p.swaps]
    swap = "".join(f"<span class='chip'>{_mmss(t)}{f' after {e(c)}' if c and not (one and c == common) else ''}</span>"
                   for t, c in zip(p.swaps, causes, strict=False))
    lead, answered = [], set()
    named: dict = {}  # the press the lead names for each hit kept for none: its chip counts that window too
    tied: dict[tuple[str, float], float] = {}  # a tied press's share in its hit's window: the lead's, on its chip
    table = ""  # the hits table, when there are big moments
    moved_t: dict[tuple[str, float], float] = {}  # ... and its counted presses' time, when it reads differently
    if p.moments:
        m = max(p.moments, key=lambda x: x.ratio)
        own = bool(set(moment_names(m)) & {n for n, _s in p.hitters[:3]})  # any of its abilities a tank hitter
        answers = ([(c.name, [t for t, n in zip(c.times, c.near, strict=False) if n],  # a press back from
                     [sp for sp, n in zip(c.support or [0.0] * len(c.times), c.near, strict=False) if n])  # cooldown
                    for c in defs if not c.every]  # is no answer (Shield Wall's 3:51)
                   + [(n, ts, sps) for n, _u, _k, ts, _ev, sps, *_rest in p.short_defs])
        from paf.gamedata import magic_only, physical_only, same_name_spells

        ids = {c.name: [c.spell_id] for c in defs}
        magic = {n: any(magic_only(i) for i in ids.get(n) or same_name_spells().get(n, [])) for n, _ts, _sps in answers}

        # each button's presses, for its share in a hit's window (round 48: Spell Reflection "41%" was its moment's,
        # 38% in the 0:35 window, as the healers' leads count)
        from paf.healer import FEW_SHARE, _tw, hit_share

        pressed = {c.name: c for c in defs}
        for n, u, k, ts, _ev, _sps, *rest in p.short_defs:
            if rest:
                pressed[n] = Cooldown(n, 0, u, k, ts, presses=[x for x in rest[0] if x],
                                      n_all=len(rest[0]), lasts=rest[1],
                                      press_lasts=[d for x, d in zip(rest[0], rest[1], strict=False) if x])

        def window(n: str, t: float, sp: float, hit: float) -> float:
            hs = hit_share(pressed[n], t, hit) if n in pressed else None
            return sp if hs is None else hs

        def answer(m: Moment) -> tuple | None:  # the most shared press for a hit (Spell Reflection, 41% at 0:33,
            phys = bool(moment_names(m)) and all(physical_only(x) for x in moment_names(m))  # before Shield Wall);
            return max(((n, t, window(n, t, sp, m.t)) for n, ts, sps in answers for t, sp in zip(ts, sps, strict=False)
                        if -ANSWER[0] <= t - m.t <= ANSWER[1] and sp and not (phys and magic[n])),  # never a magic
                       key=lambda x: x[2], default=None)  # cut on a melee hit (Spell Reflection on 2:55, round 30)
        def when(a: tuple, hit: Moment) -> str:  # its counted presses' time, as the healers' (round 70: "about
            return _tw(pressed[a[0]], a[1], hit.t) if a[0] in pressed else _mmss(a[1])  # 0:32" for presses at 0:33)

        long_names = {c.name for c in defs}
        extra: list[tuple] = []  # the long defensives said beside a short one: tied as the lead's answers

        def long_too(a: tuple | None, x: Moment) -> str:  # a short defensive answers: the long one most pressed in
            if a is None or a[0] in long_names:            # the window said too, a tenth at least and not back
                return ""                                  # from cooldown (the owner, round 79: Shield Wall 24%
            best = max(((c.name, t, hs) for c in defs      # beside Spell Reflection on Nek'zali's 0:35)
                        for t in [*c.times, *c.alt] if -ANSWER[0] <= t - x.t <= ANSWER[1] and t not in c.back
                        and not (c.why or c.every) for hs in [window(c.name, t, 0.0, x.t)] if hs >= FEW_SHARE),
                       key=lambda y: y[2], default=None)
            if best is None:
                return ""
            extra.append((*best, x))  # with its hit, for its chip's time
            return f"; {best[2]:.0%} press {e(best[0])}, a long defensive (about {when(best, x)})"

        def more_back(a: tuple | None, x: Moment) -> str:  # a long defensive pressed there more than the answer,
            if a is None:                                  # back from cooldown: said, or the lead hides it (round
                return ""                                  # 111: Rallying Cry 15% named, Shield Wall 23% unsaid)
            got = max(((c.name, window(c.name, t, 0.0, x.t), c, t) for c in defs for t in [*c.times, *c.alt]
                       if c.name != a[0] and -ANSWER[0] - 3 <= t - x.t <= ANSWER[1] + 3 and t in c.back),
                      key=lambda y: y[1], default=None)
            if not got or got[1] <= a[2]:
                return ""
            got[2].lead_back[got[3]] = x.t  # its chip says the same window count (round 114: 23% vs "3:27 for 27%")
            return f" &middot; {e(got[0])} {got[1]:.0%} in its window, back from cooldown"  # after the answer's
            # bracket (heal round 13: "(about 3:28; Shield Wall 23% … ⟲; 99 kills going)" read as Shield Wall's 99)

        from paf.healer import _reach_note

        def reach_of(a: tuple, x: Moment) -> str:  # "(99 kills going)" when a kill ended before, as the healers'
            return _reach_note(pressed[a[0]], x.t) if a[0] in pressed else ""

        big = answer(m)  # the biggest moment and its answer first, then the other hits in time order
        cells = {}  # each moment's answer, on its row of the hits table (the owner: less text)
        if big:
            cells[m.t] = (f"{big[2]:.0%} press {e(big[0])}{reach_of(big, m)} (about {when(big, m)})"
                          f"{long_too(big, m)}")
        # the other dots in time order: their most shared press, or why none is kept
        pairs = [(x, answer(x)) for x in sorted(p.moments, key=lambda x: x.t) if x is not m]
        for x, a in pairs:
            if a:
                cells[x.t] = (f"{a[2]:.0%} press {e(a[0])}{reach_of(a, x)} (about {when(a, x)}){more_back(a, x)}"
                              f"{long_too(a, x)}")
        answered = {(a[0], a[1]) for a in [big, *(a for _x, a in pairs), *extra] if a}  # the chart draws these full
        tied.update({(a[0], a[1]): a[2] for a in [big, *(a for _x, a in pairs), *extra] if a})
        from paf.healer import _counted

        for a, x in [(big, m), *((a, x) for x, a in pairs), *((a, a[3]) for a in extra)]:  # its chip at its counted
            # presses' time (round 70)
            inside = _counted(pressed[a[0]], a[1], x.t) if a and a[0] in pressed else []
            if inside and _mmss(st.median(inside)) != _mmss(a[1]):
                moved_t[(a[0], a[1])] = st.median(inside)
        bare = {_mmss(x.t): landed_in(x, defs, named, 'long defensive') for x in p.moments if x.t not in cells}
        names = sorted(dict.fromkeys(n for n, _t in answered),  # the most pressed first (a review: 15% before 38%)
                       key=lambda n: -max(v for (k, _t), v in tied.items() if k == n) if any(k == n for k, _t in tied)
                       else 0)
        from types import SimpleNamespace

        by_icon = {c.name: c for c in defs}  # the short defensives too (Spell Reflection), by name
        by_icon.update({n: SimpleNamespace(icon=ic) for n, ic in getattr(p, "name_icons", {}).items()
                        if n not in by_icon})
        from paf.healer import _and as and_
        from paf.healer import _ic, hits_table

        kept = len(p.moments) - len(bare)  # never more than the table's rows answer (a review: "answer them",
        them = "them" if kept == len(p.moments) else f"{kept} of them"  # 3:10 "None kept")
        lead.append(f"{len(p.moments)} big moments for the tanks"
                    + (f": the top {e(p.spec)}s answer {them} with "
                       + and_([f"<span class='nw'>{_ic(by_icon.get(n))}<b>{e(n)}</b></span>" for n in names]) + "."
                       if names
                       else f"; the top {e(p.spec)}s keep no long defensive for them."))
        if not own:  # the biggest is the raid's damage, not a tank buster (said, as the lead did)
            lead.append(f"The biggest, at {_mmss(m.t)}, is raid damage the tanks take too.")
        up = [(n, u) for n, u in p.mitigation if u >= 0.5][:2]  # what they do have, measured: their active
        if not names and up:  # mitigation's uptime (round 86: the biggest hit's answer was a negative alone)
            lead.append("Instead, their active mitigation is up most of the kill: "  # the bars below give the
                        + and_([f"<span class='nw'>{_ic(by_icon.get(n))}{e(n)}</span>" for n, _u in up]) + ".")  # %
        tags: dict[str, list[str]] = {}
        for x in p.moments:
            if x.ratio < 1.5:  # the healers' rule said (round 98: 1.45x "hits" with no word)
                tags.setdefault(_mmss(x.t), []).append("under 1.5&times;")  # its reason once, under the table
        # a hit that comes with a swap (Vashnik's 1:35 and 2:55, after Dripping Fangs): the time is the link
        with_swap = [(x, w) for x in p.moments for w in p.swaps if abs(w - x.t) <= ANSWER[0]]
        # said only when swaps are rare enough for it to mean something: one every 28 s (Vashnik) lands within 5 s
        # of any time one time in three
        n_swaps = max(len(p.swaps), 2 * round(p.taunts_per_kill or 0))  # every swap of a kill, not only those
        chance = n_swaps * 2 * ANSWER[0] / max(p.duration, 1)  # shared: each tank taunts, two taunts a swap pair
        if with_swap and chance < 1 / 3:
            for x, w in with_swap:
                tags.setdefault(_mmss(x.t), []).append(f"tank swap at {_mmss(w)}")
        table = hits_table(p.moments, p.moments, [(t, f"for the {_mmss(t)} hit, {c}") for t, c in cells.items()],
                           bare, p.phases, by_icon, "Under 1.5&times;: among the tanks' three highest all the same"
                           if any(x.ratio < 1.5 for x in p.moments) else "", tags, usual="damage the tank takes")
    swap_said = ""
    if p.swaps:
        # a tank's share of the kill's swaps, at least half the shared moments (round 43: "about 4" beside 9 swaps)
        taunts = f"{max(p.taunts_per_kill, len(p.swaps) / 2):.1f}".removesuffix(".0")
        swaps = f"{2 * max(p.taunts_per_kill, len(p.swaps) / 2):.0f}"  # both tanks' taunts: the swaps listed below
        first = "" if one else f"; the first at {_mmss(p.swaps[0])}" + (f" after {e(causes[0])}" if causes[0] else "")
        swap_said = (f"<span class='pill' title='the tanks swap about {swaps} times a kill after the pull (swaps on adds "
                     f"count){first}'>&#8644; {swaps}/kill</span> <span class='pill'>{taunts} taunts each</span>")  # badges,
        # the sentence on hover (fresh heal review: 70 words)
    # the chart's lanes: the defensives and short ones, the lead's answer first (Spell Reflection had none)
    shorts = [Cooldown(n, 0, u, k, ts, ["" for _ in ts], support=sps) for n, u, k, ts, _ev, sps, *_r in p.short_defs if ts]
    lane = [Cooldown("Tank swaps", SWAP_LANE, 1.0, len(p.swaps), p.swaps, [""] * len(p.swaps))] if p.swaps else []
    if not p.moments:
        answered = set()
    window_named = {c.name for c in defs if any(f"press {e(c.name)} in its window" in v
                                                for v in (bare.values() if p.moments else []))}  # its lane (heal
    # confirm round 3: "only 15% press Shield Wall in its window", no mark on the chart), drawn at the row's time
    # with the row's reason on hover (confirm round 4: an outline at 3:00 "back from cooldown" for "about 2:58")
    import re as _re

    from paf.healer import _secs
    for v in (bare.values() if p.moments else []):
        for n, at in _re.findall(r"press ([A-Z][^()]{2,40}?) in its window.*?about (\d+:\d\d)", _re.sub(r"<[^>]+>", "", v)):
            for c in defs:
                if e(c.name) == n:
                    for t in [*c.times, *c.alt]:
                        if abs(t - _secs(at)) <= 10:
                            moved_t[(c.name, t)] = float(_secs(at))
                            if t not in c.windowed:
                                c.windowed.append(t)
    svg = curve_svg(p.curve, p.moments, p.phases, "Damage the top tanks take over the fight, their defensives and "
                    "the swaps", [*defs, *shorts, *lane], {"Tank swaps", *(n for n, _t in answered), *window_named},
                    answered,
                    moved_t)  # its marks at the lead's times (round 71)
    svg = nouned(svg)  # its hovers in the cards' noun too (round 38: "the 2:55 hit" over a 1.45x moment)
    if any(m.ratio < 1.5 for m in p.moments):  # a moment named so: "tied to no moment" (round 39: both words)
        svg = svg.replace("tied to no hit", "tied to no moment").replace("the big hits", "the big moments")
    # the marks said are the ones drawn (heal round 10: "the table's answers" over a chart of swaps alone)
    outline = any((c.name, t) not in answered for c in [*defs, *shorts]
                  if c.name in {n for n, _t in answered} | window_named for t in c.times)
    marks = [*(["the table's answers" + (" (an outline: another press, or one in a moment's window that is not its "
                                          "answer)" if outline else "")]
               if answered else ["an outline: a press in a moment's window, not its answer"] if window_named else []),
             *(["a tick: a tank swap" if window_named and not answered else "the swaps"] if lane else [])]
    marks = f"Marks: {('; ' if window_named and not answered else ' and ').join(marks)}. " if marks else ""
    fight = ([f"<p class='lead'>{' '.join(lead)}</p>"] if lead else []) + ([table] if table else []) + [
        f"<h2>What hits the top tanks, and when</h2><div class='card'>{svg}<p class='small muted chart-key'>"
        # a key of glyphs, the method on hover, as the healers' (fresh heal review: a paragraph)
        f"<span class='pill' title='Median damage per second on the ranked tank of each top kill (that tank alone: a "
        f"swap moves it; fewer kills past the median one)'>{p.damage_kills or 'the top'} kills</span> "
        + ("<span>&#9478; stage time after a dashed line</span> " if getattr(p, "staged", False) else "")
        + (f"<span title='{e(marks)}'>&#9646; the table&#39;s answers</span> " if answered else "")
        + ("<span>| a tank swap</span> " if lane else "")
        + "<span title='one of the tanks&#39; three biggest moments, whatever casts it (another as high may be left "
        "out)'>&#9679; a big moment</span></p><ul class='hl2'>"
        f"{'' if p.moments else '<li>No big moment: steady damage.</li>'}</ul></div>",
        f"<h2>Your defensives, where the top players press them</h2><ul class='hl2'>"
        f"{nouned(cooldowns_html(defs, answered, named, moved_t)) or '<li>No defensive most top tanks share: they spread them.</li>'}"
        f"{nouned(rare_html(p.rare, answered, named))}</ul>",  # the same rows as the others (heal round 10)
        f"<h2>Active mitigation and short defensives the top tanks use</h2><ul class='hl2'>"
        f"{nouned(mit_html(answered)) or '<li>Not measured yet.</li>'}</ul>",
        f"<h2>Tank swaps</h2><p>{swap_said + ' ' if swap_said else ''}{'The swap moments most top raids share' if swap else 'No swap moment most top raids share.'}"
        f"{_cause(common, p.stacks) if swap and one else ''}"
        f"{':' if swap else ''}</p>" + (f"<ul class='hl2'><li><span class='when'>{swap}</span>"
                                                          f"</li></ul>" if swap else "")
        + (f"<p class='small muted'>About {extra} more swaps a kill come at varying times.</p>"
           if swap and (extra := round(2 * p.taunts_per_kill) - len(p.swaps)) > 0 else "")
        # the rule said (round 87: a swap tied on Nek'zali, none on Vashnik's swap every 28 s, with no word why)
        + ("<p class='small muted'><span class='pill' title='The table ties a swap to a hit only when swaps are rare "
           "enough not to land within 5 s of it by chance one time in three or more.'>? when a swap is tied to a hit"
           "</span></p>" if swap else "")  # the rule on hover (fresh heal review)
        + "".join(f"<p><b>Taunts stop working with {e(n)}:</b> {e(t)} <span class='muted'>(The Encounter Journal; "
                  + (f"never reached in the {k} top kills read" if not hit and k else
                     f"reached in {hit} of the {k} top kills read" if k else "not measured") + ".)</span></p>"
                  for n, t, hit, k in p.no_taunt if hit or not k)]  # never reached: one line on the boss tab
    change = [build_lead(p.builds, p.spec, p.split_players or p.kills, p.split, p.split_wide),
              talents_html(p.builds, p.split_players or p.kills, f"{p.spec}s", p.hero),
              split_html(p.split, p.split_players, p.spec, p.split_wide, getattr(p, "talent_icons", None),
                         getattr(p, "split_marks", None))
              if p.split else "",
              f"<h2>Trinkets the top players equip</h2><ul class='hl2 bars'>"
              f"{trinkets_html(p.trinkets, getattr(p, 'item_icons', None)) or '<li>No gear yet.</li>'}</ul>",
              ]  # the lead says no sim weighs them
    top_share = max((s_ for _n, s_ in p.hitters), default=1.0) or 1.0
    from paf.icons import img as _img

    names_ic = getattr(p, "name_icons", {}) or {}
    hit = "".join(f"<li><b>{_img(names_ic.get(n, ''), 'small', 'ics')}{e(n)}</b><span class='upbar' "  # icons
                  "aria-hidden='true'><span style='width:"  # a bar each, the
                  f"{s / top_share * 100:.0f}%'></span></span><small>{s:.0%}</small></li>"  # unit in the heading
                  for n, s in p.hitters)
    jr = "".join(f"<li>{e(plain(x))}</li>" for x in p.journal)
    # the tank's answer here: the swap (the fight tab's lead, its last sentence), else the journal's ask
    # the boss tab's answer: the mechanic the swaps follow (the fight tab says the swaps), else the journal's ask
    # the boss tab says what hits them (the fight tab, when): measured, then the journal below
    # the three most, and any tied with the third at its shown share (round 92: Dripping Fangs 8% left out beside
    # Caustic Surge 8%, the mechanic the swaps follow)
    top_hit = ("" if p.hitters else journal_lead(p.journal, "tanks"))  # the bars right below say it (round 43)
    boss = [top_hit, f"<h2>The abilities that hit the top tanks the most <small class='muted'>(% of the damage they "
                     f"take)</small></h2><ul class='hl2'>{hit or '<li>Not measured yet.</li>'}</ul>"]
    boss += [f"<p class='small muted'>Taunts stop working with {e(n)} (the Encounter Journal), never reached in the "
             f"{k} top kills read.</p>" for n, _t, hit, k in p.no_taunt if not hit and k]
    if jr:
        boss.append(f"<h2>What the Encounter Journal asks tanks</h2><ul class='hl2'>{jr}</ul>")
    if p.abilities:  # every ability, the tanks' in full and the others' named
        boss.append(f"<h2>Every ability{', phase by phase' if '<h3>' in p.abilities else ''}</h2>"
                    "<p class='small muted'><span class='pill' title='They shift with your raid&#39;s pace, and "
                    f"another spec&#39;s sheet can differ'>pull times &middot; {p.kills} kills, median "
                    f"{_mmss(p.duration)}</span></p>"  # the method a chip (round 43)
                    f"<div class='stages'>{p.abilities}</div>")
    have = next((x for x in p.presence if x.spec == p.spec), None)
    deeper = []
    from paf.icons import spec_img

    if have and p.presence:
        mates = [x for x in p.presence if x.spec != p.spec and x.kills >= 8]
        deeper.append(f"<p class='lead'>Beside a {e(p.spec)}, the top raids play "
                      + (", ".join(f"<span class='nw'>{spec_img(x.spec)}{e(x.spec)}</span> (in {x.share:.0%} of "
                                   "the kills)"
                                   for x in sorted(mates, key=lambda x: (-x.share, -x.kills, x.spec))[:3])
                         if mates else "no other tank spec often") + "."
                      + "".join(f" Kills with a {e(x.spec)} beside them are "
                                f"{abs(round(x.duration_with) - round(x.duration_without))} s "  # as the table's rounded
                                # times (round 92: 29 s beside 4:06 and 4:34)
                                f"{'shorter' if x.duration_with < x.duration_without else 'longer'}, beyond the noise (a "
                                f"reading, not a verdict: the raids that bring one differ in other ways too)."
                                for x in mates if x.kills >= 15 and x.duration_without and not x.duration_close)
                      + "</p>")
    worn = {n for n, _i, _s in p.trinkets}  # on-use trinkets on the fight tab, as the healers' sheets
    items = [c for c in others if c.name in worn]
    rest = [c for c in others if c not in items]
    from paf.healer import _item

    used = [c for c in rest if _item(c.spell_id)]  # potions: the deeper tab
    damage = [c for c in rest if c not in used]  # Avatar, Shield Charge: pressed by all of them, the fight tab
    if damage:
        fight.append(f"<h2>Your damage cooldowns</h2><ul class='hl2'>{cooldowns_html(damage, set())}</ul>")
    if items:
        fight.append(f"<h2>On-use trinkets</h2><ul class='hl2'>{cooldowns_html(items, set())}</ul>")
    if used:  # the healers' sheets have theirs on the fight tab too
        fight.append(f"<h2>Consumables</h2><ul class='hl2'>{cooldowns_html(used, set())}</ul>")
    if p.presence:
        if have and have.share >= 0.99:  # the corpus is this spec's kills
            line = ""  # the lead says who plays beside them (heal round 18: said twice)
        elif have:
            line = f"{have.share:.0%} of the top kills bring a {e(p.spec)} ({have.per_kill:.1f} a kill when they do)."
        else:
            line = f"Few top raids bring a {e(p.spec)} on this boss."
        deeper.append(f"<h2>The top raids' tanks</h2>{f'<p>{line}</p>' if line else ''}{presence_table(p.presence, p.spec, 'Tank')}"
                      + comps_table(p.comps, p.kills).replace("Healers", "Tanks"))
        deaths = any(x.deaths_with is not None for x in p.presence)
        # every sample of the sheet, once, as the healers' sheets (round 38: no map on the tank's)
        # every sample once, as chips with their words on hover, as the healers' "Read on" (heal rounds 36-48)
        deeper.append(
            "<p class='small muted chips'>Read on "
            f"<span class='pill' title='your cooldowns&#39; timings and the boss&#39;s times, every cast read'>{p.kills} "
            f"top kills</span> <span class='pill' title='the tanks&#39; damage'>{p.damage_kills or 40} for the damage"
            f"</span> <span class='pill' title='the tanks beside them and the compositions; deaths read on fewer"
            + ("" if deaths else ", not read yet") + "'>the same for the tanks beside them</span> "
            "<span class='pill' title='the raids that bring a spec differ in other ways too, and a few kills move a "
            "mean of deaths'>a reading, not a verdict</span></p>")
    from paf.healer import legend_for

    # the legend under every card it explains, its used terms only (as the healers'; a review: mid-page)
    fight.append(legend_for(TANK_HOW_TO_READ.replace("</dl>", f"<dt>Stage time</dt><dd>{STAGE_TERM}</dd></dl>")
                            if getattr(p, "staged", False) else TANK_HOW_TO_READ, "".join(fight)))
    byline = (f"{e(p.character or p.spec)} &middot; {e(p.spec)} &middot; from {p.kills} top kills (median "
              f"{_mmss(p.duration)}) &middot; no tank sim")
    return sheet_page(p.boss, p.difficulty, byline, p.class_name,
                      {"fight": fight, "change": change, "boss": boss, "deeper": deeper}, theme.style("healer"),
                      UNSIMMED)
