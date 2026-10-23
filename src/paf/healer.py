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

import functools
import html
import json
import re
import sqlite3
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
RAMP = (8.0, 30.0)  # seconds before a hit a ramp button is pressed for it (Evangelism 1:42 for 2:10)
ANSWER = (5.0, 8.0)  # seconds before and after a moment's start a press answers it: 5 s ahead, its 5 s window and 3
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
    support: list[float] = field(default_factory=list)  # each moment's share of the players pressing it then
    alt_support: list[float] = field(default_factory=list)  # the same for the other habits
    alt_near: list[str] = field(default_factory=list)  # the hit another habit answers, if any
    alt_of: list[float] = field(default_factory=list)  # the moment (same press of the kill) each habit replaces
    why: str = ""  # why it is never tied to a hit, said on its row
    rhythm: float = 0.0  # after its first press, pressed again as soon as it is back, about every this many seconds
    cd: float = 0.0  # its cooldown in the game data
    back: list = field(default_factory=list)  # its times most players press as soon as it is back (back_share)
    ramp: bool = False  # pressed 8 to 30 s before the hits it answers (paf.healer.RAMP): a ramp, said so
    on_others: float = -1.0  # an external: the share of its casts on another player (Life Cocoon 0.81); -1 unread
    presses: list = field(default_factory=list)  # each top player's press times (those who press it)
    back_half: list = field(default_factory=list)  # its times about half its players press as soon as it is back
    n_all: int = 0  # the top players read, those who never press it included
    lasts: list = field(default_factory=list)  # each top player's kill length: a late hit's share is of those reaching it
    press_lasts: list = field(default_factory=list)  # the kill length of each of presses' players, in their order
    rhythms: list = field(default_factory=list)  # (share of the top players, their press times): two groups that
    # press it at different moments all kill long (Disc's Evangelism: 0:04, 1:42, 3:15 or 0:24, 2:07, 3:38)
    # a button pressed in two steps (Stasis: store, then release, which is when it heals; the owner, round 79)
    pulls: list = field(default_factory=list)  # each press's pull time, parallel to presses (stage time: a gap)
    twice: float = -1.0  # the share of the top players pressing it twice or more, every cast counted; -1 unread
    release: Cooldown | None = None  # its release presses, as a cooldown's (its moments, shares and hits)
    release_gap: float = 0.0  # median seconds from a store to its release
    stored: list = field(default_factory=list)  # (spell, share of the stores holding it, share holding it twice)
    release_pairs: list = field(default_factory=list)  # (each release, seconds after its own store)
    unreleased: float = 0.0  # the share of stores with no release before the next store
    fates: list = field(default_factory=list)  # (each store, its release or None)
    hits: list = field(default_factory=list)  # the big hits' times, for a release chip's window
    icon: str = ""  # its game icon's file name (paf.icons), "" offline
    shown_at: dict = field(default_factory=dict)  # a mark's time as its card says it ("1:50 to 2:04"), for its hover
    windowed: list = field(default_factory=list)  # times the table names in a hit's window: their reason on hover
    window_of: dict = field(default_factory=dict)  # such a time -> its hit's time, when the press sits past it
    lead_back: dict = field(default_factory=dict)  # a time back from cooldown the lead says in a hit's window: its hit


def add_icons(prep) -> None:
    """Every cooldown of a sheet (HealerPrep, TankPrep) gets its spell's icon: read once from Wowhead, then cached;
    none offline (the names stay)."""
    cds = [c for v in vars(prep).values() if isinstance(v, list) for c in v if isinstance(c, Cooldown)]
    cds += [c.release for c in cds if c.release is not None]
    try:
        from paf.icons import icons_for

        found = icons_for({str(c.spell_id): f"spell={c.spell_id}" for c in cds if c.spell_id > 0})
    except Exception:  # noqa: BLE001 - offline: no icons
        return
    for c in cds:
        c.icon = found.get(str(c.spell_id), "")
    roles = getattr(prep, "roles", None) or []  # the other healers' buttons, by name (their table's cells)
    ids = {_shown(n): rest[1][3] for r in roles for n, _k, _ts, *rest in getattr(r, "cd_names", [])
           if len(rest) > 1 and len(rest[1]) > 3}
    try:
        got = icons_for({n: f"spell={i}" for n, i in ids.items()})
    except Exception:  # noqa: BLE001 - offline
        got = {}
    prep.role_icons = got
    # the trinkets (by item) and the split talents (by name) of the Change tab (heal rounds 12-15: no icon there)
    try:
        prep.item_icons = icons_for({n: f"item={i}" for n, i, _s in getattr(prep, "trinkets", []) or []})
    except Exception:  # noqa: BLE001 - offline
        prep.item_icons = {}
    talents = {re.sub(r" [0-9]+%.*$", "", x) for n, sh in getattr(prep, "split", []) or []
               for x in (n.split(" / ") if sh < 0 else [n])}
    if talents:
        try:
            from paf.gamedata import same_name_spells

            same = same_name_spells()
            prep.talent_icons = icons_for({n: f"spell={same[n][0]}" for n in talents if same.get(n)})
        except Exception:  # noqa: BLE001 - offline
            prep.talent_icons = {}
    # a tank's short defensives and active mitigation, known by name only (Spell Reflection): their spell's icon
    named = [n for n, *_r in getattr(prep, "short_defs", []) or []] + [n for n, _u in getattr(prep, "mitigation", []) or []]
    if named:
        try:
            from paf.gamedata import same_name_spells

            same = same_name_spells()
            ids = {n: same[n][0] for n in named if same.get(n)}
            prep.name_icons = icons_for({n: f"spell={i}" for n, i in ids.items()})
        except Exception:  # noqa: BLE001 - offline
            prep.name_icons = {}


def _ic(c: Cooldown | None) -> str:
    from paf.icons import img

    return img(c.icon, "small", "ics", "") if c is not None and c.icon else ""


def _spec_ic(spec: str) -> str:
    """A spec's class icon before its name in the tables (heal round 10: bare spec names, the cheapest visual)."""
    from paf import icons

    cls = icons.class_key(spec)
    return icons.img(icons.CLASS_ICON.format(cls=cls), "small", "ics", "") if cls else ""


def _comp_label(c) -> str:
    """A composition's specs, each with its icon ("2 Holy Priests + Restoration Shaman")."""
    n = Counter(getattr(c, "specs", ()) or ())
    if not n:
        return e(c.label)
    return " + ".join(f"<span class='nw'>{_spec_ic(s)}{e(f'{k} {s}s' if k > 1 else s)}</span>"
                      for s, k in sorted(n.items(), key=lambda x: (-x[1], x[0])))


# how to read the cards, one term a line (the owner: less text; every rule kept, said once)
HOW_TO_READ = (
    "<dl class='legend'><dt>N%</dt><dd>of the top players read; &ldquo;(N kills going)&rdquo;: of the kills still "
    "going then (a hit's window: those lasting through it); &ldquo;of its users&rdquo;: of the top players who "
    "press the button.</dd><dt>Tied to a hit</dt>"
    "<dd>pressed in the hit's window (5 s before to 8 s after; a ramp: 8 to 30 s ahead) by a quarter of its users; "
    "its share is the window's. One button a hit (a second within the noise), else the most pressed under a quarter.</dd><dt>A time</dt><dd>shared by a quarter of those who press the button; its share: the top players pressing within 8 s of it (&ldquo;of its users&rdquo; too, "
    "under a quarter).</dd><dt>On cooldown</dt><dd>pressed every time it comes back, all kill long.</dd>"
    "<dt>&#10226; back from cooldown</dt><dd>most of its players press it as soon as it is back: not saved for the hit, not "
    "counted for it (&#10226;&nbsp;about half: 40 to 60% of them).</dd><dt>&ldquo;or&rdquo;</dt><dd>another "
    "time some top players press it instead.</dd></dl>")

# stage time, as a legend term: every rule of STAGED, in fewer words
STAGE_TERM = ("after a dashed line: each kill's damage and presses counted from that stage's start, placed at its "
              "median start; a stage's seconds past the next one's start are left out of the times, still counted "
              "in who presses a button.")

LEAD_HITS = 4  # the big moments the lead says at most: Nek'zali's two rites and Stage Two's two waves
# the stage clock said, on a boss with stages (paf.stagetime, round 100)
STAGED = ("in stage time: each kill's damage and presses after a stage starts are counted from that stage's start, "
          "placed at its median start (the dashed lines), so a late stage's waves line up whatever time it began (a "
          "stage's seconds past the next one's median start are left out of the times, its presses still counted in "
          "who presses a button and how often); ")


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
    own_median: float = 0.0  # their median kill time (slower than the timings' 100: picked by healing)
    own_kills: int = 0  # the top kills whose healing tables are read (150): more than the timings' (100, every cast)
    own_timed: int = 0  # of them, the timings' kills (Restoration Shaman, Nek'zali: 99 of 100 in 149)
    own_sample: str = ""  # the kills the externals and cooldowns are read on: "the 150 kills of the top Holy Priests"
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
    split_wide: bool = False  # no talent 35-65%: the split is the talents they differ on most (15-85%)
    potions: list = field(default_factory=list)  # potions a quarter of them or more drink (Cooldown)
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


def _raid_rows(con, table: str, encounter_id: int, difficulty: int, pool: bool) -> list[tuple[float, str]]:
    return [(st_, se) for _k, st_, se in _raid_kills(con, table, encounter_id, difficulty, pool)]


def _raid_kills(con, table: str, encounter_id: int, difficulty: int, pool: bool) -> list[tuple[tuple, float, str]]:
    """(step, series) of each kill's raid damage: this corpus', or with pool every corpus' kills of the boss, each
    kill once (the boss is the same on every sheet: Nek'zali's second rite read 1:15 on four sheets, 1:20 on the
    others, and the other healers' answers to it changed with the sheet; round 33)."""
    from paf.config import data_dir
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    sql = f"SELECT d.report, d.fight_id, d.step, d.series FROM {table} d JOIN fight f USING(report, fight_id) WHERE {where}"
    if not pool:
        ensure_table(con)
        return [((r, f), st_, se) for r, f, st_, se in con.execute(sql, params)]
    seen, out = set(), []
    for path in sorted(data_dir().glob("corpus-*.sqlite")):
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                continue
            for rep, fid, st_, se in c.execute(sql, params):
                if (rep, fid) not in seen:
                    seen.add((rep, fid))
                    out.append(((rep, fid), st_, se))
        finally:
            c.close()
    return out


def raid_kills(con, encounter_id: int, difficulty: int, pool: bool = False) -> int:
    """The kills the raid damage curve is read on."""
    return len(_raid_rows(con, "raid_damage", encounter_id, difficulty, pool))


def raid_by_ability(con, encounter_id: int, difficulty: int, duration: float, pool: bool = False,
                    clock=None) -> dict[str, list[float]]:
    """The raid's damage taken per ability, per STEP, summed over the kills read (shares compare, not levels); with a
    stage clock (paf.stagetime), each kill's times in stage time."""
    n = int(duration // STEP) + 1
    out: dict[str, list[float]] = {}
    for kill, step, series in _raid_kills(con, "raid_damage_ability", encounter_id, difficulty, pool):
        for name, values in json.loads(series).items():
            row = out.setdefault(name, [0.0] * n)
            for i, v in enumerate(values):
                at = clock.at(kill, i * step) if clock else i * step
                if at is None:  # a stage's seconds past the next one's median start: left out
                    continue
                b = int(at // STEP)
                if b < n:
                    row[b] += v or 0
    return out


SUSTAINED = 1.15  # the raid damage this many times the median, for SUSTAINED_S or more: a stretch with no break
SUSTAINED_S = 30.0


def sustained(curve: list[float], found: list[Moment] | None = None) -> list[tuple[float, float, float]]:
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
            a, b = start * STEP, i * STEP  # a stretch holding a big moment is that moment (Evoker: 1:10-1:40)
            if b - a >= SUSTAINED_S and not any(a <= m.t < b for m in found or []):
                out.append((a, b, st.mean(curve[start:i]) / base))
            start = None
    return out


def _x(r: float) -> str:
    """A hit's ratio, rounded down, two decimals under SPIKE: a 1.47x hit read "1.5x" next to "no hit reaches 1.5x"
    (round 31), a 1.36x one "1.3x" next to "1.35x or more counts"."""
    return f"{int(r * 100 + 1e-9) / 100:.2f}" if r < 2 else f"{int(r * 10 + 1e-9) / 10:.1f}"  # 1.59 and 1.60,
    # not 1.5 and 1.6 (round 37: a 0.01 gap read as 0.1)


def moment_names(m: Moment) -> list[str]:
    """The abilities a moment is named after: "mixed damage, most from A and B" -> [A, B]."""
    return [x for x in m.boss_spell.removeprefix("mostly ").removeprefix("after ").split(" and ") if x]


def moment_notes(found: list[Moment], staged: bool = False) -> dict[str, str]:
    """The boss tab's measured line under each ability the raid's big moments are named after (Soulcoil Rite: no
    cast to time it, yet the fight tab names it twice)."""
    at: dict[str, list[float]] = {}
    for m in found:
        for n in moment_names(m):
            at.setdefault(n, []).append(m.t)
    clock = " (measured, in stage time as the fight tab)" if staged else " (measured)"  # the boss tab's own times
    return {n: "big raid damage at " + _and([_mmss(t) for t in ts]) + clock for n, ts in at.items()}  # are pull time
    # (round 101: "around 0:34, 1:10, 3:55 · big raid damage at 0:35, 3:50 and 4:15" on two clocks, unsaid)


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
            m.boss_spell = f"mostly {first} and {second}"


def raid_curve(con, encounter_id: int, difficulty: int, duration: float, pool: bool = False,
               clock=None) -> list[float]:
    """Median raid damage taken per second, per STEP seconds, over the kills that have it (pool: every corpus'); with
    a stage clock (paf.stagetime), each kill's damage in stage time, so a late stage's waves line up (round 100)."""
    rows = _raid_kills(con, "raid_damage", encounter_id, difficulty, pool)
    if pool and rows:  # the pooled kills' own length, not this sheet's: the same curve and ratios on every sheet
        lengths = [((clock.at(k, n_ * stp) or n_ * stp) if clock else n_ * stp)
                   for k, stp, se in rows for n_ in [max((len(v) for v in json.loads(se).values()), default=0)]]
        duration = st.median(lengths) or duration
    n = int(duration // STEP) + 1
    per_bucket: list[list[float]] = [[] for _ in range(n)]
    for kill, step, series in rows:
        data = json.loads(series)
        total: list[float] = []
        for values in data.values():
            for i, v in enumerate(values):
                if i >= len(total):
                    total.append(0.0)
                total[i] += v or 0
        for i, v in enumerate(total):  # each point covers `step` seconds: into STEP buckets
            at = clock.at(kill, i * step) if clock else i * step
            if at is None:  # a stage's seconds past the next one's median start: left out
                continue
            b = int(at // STEP)
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
        if found and t - found[-1].t <= SPIKE_GAP:  # 15 s apart is one stretch (the tanks' 3:25, 3:40, 3:55)
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


@functools.cache
def _choice_nodes() -> dict[int, int]:
    """Spell id -> its talent node, for the nodes offering a choice of two spells (Revival or Restoral)."""
    try:
        from paf.gamedata import talent_entries

        entries = talent_entries()
    except Exception:  # noqa: BLE001 - offline: no merge
        return {}
    by_node: dict[int, set[int]] = {}
    for _name, sid, node, _x, _y in entries.values():
        if sid and node:
            by_node.setdefault(node, set()).add(sid)
    return {sid: node for node, sids in by_node.items() if len(sids) == 2 for sid in sids}


def _node_key(spell_id: int, name: str) -> str:
    node = _choice_nodes().get(spell_id)
    return f"node {node}" if node else name


def _item_why(name: str, spell_id: int) -> str:
    """Why an item's use is no answer to a hit: a potion is the pull's, a trinket its rhythm's."""
    from paf.tracker import kind

    if k := kind(name, spell_id):
        return "a healthstone" if k == "healthstone" else "a potion"
    try:  # by the game data: a worn item's spell is a trinket's, any other a consumable's (Lightfused Mana Potion)
        from paf.gamedata import worn_item_spells

        return "a trinket, placed by its rhythm" if spell_id in worn_item_spells() else "a potion"
    except Exception:  # noqa: BLE001 - offline
        return "a trinket, placed by its rhythm"


def _moving(spell_id: int) -> bool:
    """A cast-while-moving button (Spiritwalker's Grace; game data aura 330): no answer to a raid hit. One that also
    changes spells (aura 108: Tip the Scales makes an empowered heal instant) is a throughput cooldown."""
    try:
        from paf.gamedata import _filtered_rows

        auras = {r.get("EffectAura") for r in _filtered_rows("SpellEffect", "SpellID", spell_id)}
        return "330" in auras and "108" not in auras
    except Exception:  # noqa: BLE001 - offline
        return False


def _raid(spell_id: int) -> bool:
    """A button that heals, shields or cuts the raid's damage (paf.gamedata.raid_kind); offline, none."""
    try:
        from paf.gamedata import raid_kind

        return raid_kind(spell_id)
    except Exception:  # noqa: BLE001 - offline
        return False


def _ramp_kind(spell_id: int) -> bool:
    """A ramp's button by the game data (paf.gamedata.is_ramp_kind): Evangelism, Rapture, Spirit Shell."""
    try:
        from paf.gamedata import is_ramp_kind

        return is_ramp_kind(spell_id)
    except Exception:  # noqa: BLE001 - offline
        return False


def _utility(spell_id: int) -> bool:
    """A utility button (paf.gamedata.is_utility): a pure dispel, a knockback, a movement button."""
    try:
        from paf.gamedata import is_utility

        return is_utility(spell_id)
    except Exception:  # noqa: BLE001 - offline
        return False


def _speed(spell_id: int) -> bool:
    """A movement button (Divine Steed: game data aura 31, run speed): no answer to a raid hit."""
    try:
        from paf.gamedata import is_speed

        return is_speed(spell_id)
    except Exception:  # noqa: BLE001 - offline
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
    groups: dict[str, list] = {}  # one spell under several ids (Lay on Hands 633 and its talented 471195): one row;
    for a in tl.abilities:          # an id cast too often for a cooldown is another spell of the same name (Divine
        if tl.duration and a.per_kill > max(1.0, tl.duration / COOLDOWN_GAP):  # Hymn's ticks, 64844, buried 64843)
            continue
        groups.setdefault(_node_key(a.id, a.name), []).append(a)  # the two sides of a choice node: one row
    out = []
    for _key, abs_ in groups.items():
        name = " / ".join(dict.fromkeys(a.name for a in sorted(abs_, key=lambda a: -a.users)))  # Revival / Restoral
        ids = [a.id for a in abs_]
        per_player = [sorted(t for i in ids for t in (p["casts"].get(i) or [])) or list(p["casts"].get(name) or [])
                      for p in tl.players]
        # each press's pull time beside its stage time (paf.stagetime.warp): a gap between two presses is the
        # game's cooldown, read in pull time (round 101: a Rewind gap read 178 s for 245 s across Stage Two)
        pulls = [sorted(t for i in ids for t in ((p.get("pull") or p["casts"]).get(i) or []))
                 or list((p.get("pull") or p["casts"]).get(name) or []) for p in tl.players]
        raw = [sorted(t for i in ids for t in ((p.get("raw") or p["casts"]).get(i) or []))
               or list((p.get("raw") or p["casts"]).get(name) or []) for p in tl.players]  # every cast, stage time or not
        users = sum(1 for ts in raw if ts) / max(1, len(tl.players))
        pressed_lasts = [p.get("duration") or tl.duration for p, ts in zip(tl.players, per_player, strict=False) if ts]
        pulls = [q for ts, q in zip(per_player, pulls, strict=False) if ts]
        per_player = [ts for ts in per_player if ts]
        if not per_player or not tl.duration:
            continue
        per_kill = st.median(len(ts) for ts in raw if ts)  # its presses a kill, all of them (round 107)
        if not min_users <= users < max_users or per_kill > max(1.0, tl.duration / COOLDOWN_GAP):
            continue
        if base and max(base.get(i, (0.0, 1))[0] for i in ids) < COOLDOWN_GAP:
            continue
        sid = max(abs_, key=lambda a: a.users).id
        times, alt, alt_of = press_moments(per_player, max(1, round(per_kill)), tl.duration)
        # two groups pressing it at different moments all kill long: its moments are theirs, the larger group's
        # the main ones, the other's each the habit of the same press (Disc's Evangelism on Vashnik read 0:03,
        # 2:11, 3:39: one group's opener with the other's later presses, a rhythm nobody plays; round 32)
        two = rhythms(per_player, times, alt, max(1, len(tl.players))) if alt else []
        def shared(t: float, per_player=per_player) -> bool:  # the quarter of its players the moments below need (kept)
            return sum(1 for ts in per_player if any(abs(x - t) <= 8 for x in ts)) >= 0.25 * len(per_player)
        if two and not all(shared(t) for _sp, ts in two for t in ts):  # a press too spread to show (Divine Hymn's
            two = []  # second, Nek'zali): no rhythm, or the row would lose it
        if two:
            def shared_at(t: float, per_player=per_player) -> int:  # the chip's own count (round 59: the 0:04
                return sum(1 for ts in per_player if any(abs(x - t) <= 8 for x in ts))  # group led at 31% for 36%)
            (_sa, a), (_sb, b) = sorted(two, key=lambda r: -shared_at(r[1][0]))
            times, alt, alt_of = list(a), list(b[:len(a)]), list(a[:len(b)])
        else:  # a press's most shared time is its main one, its habits after (round 41: Convoke "2:24 · 27%, or 2:37
            def near_n(t: float, per_player=per_player) -> int:  # for 28%" put the smaller first)
                return sum(1 for ts in per_player if any(abs(x - t) <= 8 for x in ts))
            for k, (x, of) in enumerate(zip(alt, alt_of, strict=False)):
                if of in times and near_n(x) > near_n(of):
                    j = times.index(of)
                    times[j], alt[k] = x, of
                    alt_of = [x if o == of else o for o in alt_of]
            times = sorted(times)
        every = on_cadence(pulls, per_kill, tl.duration)
        cd = max((base or {}).get(i, (0.0, 1))[0] for i in ids)
        if every and (any(abs((y - x) - every) > 0.15 * every for x, y in pairwise(times))
                      or (cd and every > 1.15 * cd)):  # held past its cooldown (the Vessel every 118 s, cooldown 90)
            every = 0.0  # its moments are not a cooldown apart: the top players hold it (the Vessel at 0:03, 2:02)
        if every and len(times) > 1:  # said from the moments shown, so the number matches them; an item's never
            every = st.median(y - x for x, y in pairwise(times))  # under its cooldown (the Vessel "every 111 s"):
            if _item(sid):                                         # a class spell's may be (Avatar every 53 s,
                every = max(every, cd)                             # Anger Management)
        # pressed again as soon as it is back after a first press of its own (Avenging Wrath at 0:42 then every
        # 123 s, its cooldown 120): the first may answer a hit, the next ones are its rhythm
        gaps = [y - x for ts in pulls for x, y in pairwise(ts)]
        rhythm = st.median(gaps) if gaps and not every and cd and st.median(gaps) <= 1.15 * cd else 0.0
        if _item(sid):  # a trinket or a potion: one wording on every sheet, its rhythm said with it
            every = 0.0
        # one reason a button, the same on every boss: what it is first (Life Cocoon is cast on another player
        # on Vashnik and Nek'zali alike, even where it is pressed about every minute), then how often
        why = ("" if every else "cast on another player" if _external(sid) else "a cast-while-moving button"
               if _moving(sid) else "a movement button" if _speed(sid) else _item_why(name, sid) if _item(sid) else "about every minute" if per_kill >= 4
               else "")
        # an "or" time is the same press 20 s away at most (round 76: Nature's Swiftness "2:09 …, or 1:22"); farther,
        # a minute button's is a moment of its own, a button on cooldown's is dropped, its cadence says where it lands
        # (round 77: Celestial Conduit "every 97 s" read 3:20 and 3:46); a habit held for a hit stays (round 74:
        # Avenging Wrath held for 0:35, the rest on cooldown)
        if why == MINUTE or every:
            far = {i for i, (x, of) in enumerate(zip(alt, alt_of, strict=False)) if abs(x - of) > OR_NEAR
                   and (why or not any(-ANSWER[0] <= x - m.t <= ANSWER[1] for m in found))}
            if why:
                times = sorted([*times, *(alt[i] for i in far if all(abs(alt[i] - t) > 8 for t in times))])
            alt, alt_of = [x for i, x in enumerate(alt) if i not in far], [x for i, x in enumerate(alt_of) if i not in far]
        shares = {x: back_share(per_player, x, cd, pulls) for x in [*times, *alt]}
        back = {x for x, b in shares.items() if b > BACK_SHARE[0]}  # pressed as soon as it is back; about half
        half = {x for x, b in shares.items() if BACK_SHARE[0] < b <= BACK_SHARE[1]}  # of them: no tie either
        tied = not (every or why)  # on cooldown, a 1-minute button, a
        near = []  # buff on one player, a cast-while-moving: near a hit by chance, not kept for it
        for t in times:
            m = min(found, key=lambda m: abs(m.t - t), default=None)
            ok = (tied and m is not None and -ANSWER[0] <= t - m.t <= ANSWER[1]  # pressed for the hit: before or in
                  and t not in back)  # it; not a press made as soon as it is back
            near.append(f"{_mmss(m.t)} {m.boss_spell}".strip() if ok else "")
        n_all = max(1, len(tl.players))  # the share of all the top players pressing it within 8 s of each moment,
        alld = [p.get("duration") or tl.duration for p in tl.players]  # of the kills still going then (round 98:

        def n_at(t: float, alld=alld) -> int:  # "3:52 · 24%" of 100 beside "28% of the 58 kills still going")
            return max(1, sum(1 for d in alld if d >= t))
        # a press counted from a kill still going at t, as its base (round 112: a kill ended within 8 s before t
        # counted on top, not below: Rewind "4:20 · 42% in the 92 kills" beside "43% in the 87")
        def near_at(t: float, pp=per_player, pl=pressed_lasts) -> int:
            return sum(1 for ts, d in zip(pp, pl, strict=False) if d >= t and any(abs(x - t) <= 8 for x in ts))
        support = [near_at(t) / n_at(t) for t in times]
        # a moment a quarter of those who press it share at least: under, it is timing that varies (a chip at 12%
        # of the top players read as a moment next to "no moment most of them share")
        # a quarter of those who press it, of the kills still going then: a late time's pressers are those whose kill
        # reaches it (round 104: Tranquility's 4:19, 22 of the 89 still going, read 22% of all 98 and refused)
        raw_lasts = [p.get("duration") or tl.duration for p, ts in zip(tl.players, raw, strict=False) if ts]

        def users_at(t: float, pl=raw_lasts, alld=alld) -> float:  # every caster, as "pressed by" and the share
            return sum(1 for d in pl if d >= t) / max(1, sum(1 for d in alld if d >= t))  # beside a chip (r. 113)
        kept = [i for i, sp in enumerate(support) if sp >= 0.25 * users_at(times[i]) - 1e-9]
        times, near, support = [times[i] for i in kept], [near[i] for i in kept], [support[i] for i in kept]
        # a hit's window a quarter of those who press it press it in, of the kills reaching its end, with no time of
        # the card there: the window's presses are a time of its own, as the rule says (round 106: Tranquility 26% at
        # Nek'zali's 4:15 refused, its presses spread 4:12-4:23, while Aura Mastery 23% was kept by its time)
        from paf.defensives import is_defensive

        if tied and not is_defensive(sid, name):  # a personal defensive is never kept for a raid hit: no time added
            for m in found:  # for one (round 109: Astral Shift's 4:18, admitted by the window, then "not kept")
                a_, b_ = m.t - ANSWER[0], m.t + ANSWER[1]
                if any(a_ - SLACK <= t <= b_ + SLACK for t in [*times, *alt]):
                    continue
                going = [ts for ts, d in zip(per_player, pressed_lasts, strict=False) if d >= b_]
                inside = [x for ts in going for x in ts if a_ <= x <= b_]
                k = sum(1 for ts in going if any(a_ <= x <= b_ for x in ts))
                if not going or k < 0.25 * len(going) or k / max(1, sum(1 for d in alld if d >= b_)) < FEW_SHARE:
                    continue
                t_new = st.median(inside)
                b_new = back_share(per_player, t_new, cd, pulls)
                if b_new > BACK_SHARE[0]:  # back from cooldown: no time held for it
                    continue
                rows_ = sorted([*zip(times, near, support, strict=False),
                                (t_new, f"{_mmss(m.t)} {m.boss_spell}".strip(),
                                 sum(1 for ts in per_player if any(abs(x - t_new) <= 8 for x in ts)) / n_at(t_new))])
                times, near, support = [r[0] for r in rows_], [r[1] for r in rows_], [r[2] for r in rows_]

        # a button on cooldown keeps another habit of a press its players do not make as soon as it is back (round
        # 74: 26% of the top Holy Paladins hold their first Avenging Wrath for Nek'zali's 0:35, the rest from the pull)
        if every:
            keep = [i for i, x in enumerate(alt) if x not in back]
            alt, alt_of = [alt[i] for i in keep], [alt_of[i] for i in keep]
        alt_support = [near_at(t) / n_at(t) for t in alt]
        kept = [i for i, sp in enumerate(alt_support) if sp >= 0.25 * users_at(alt[i]) - 1e-9  # the same quarter,
                and alt_of[i] in times]  # of a moment still shown
        alt, alt_support, alt_of = [alt[i] for i in kept], [alt_support[i] for i in kept], [alt_of[i] for i in kept]
        alt_near = []  # another habit answers a hit too (Aura Mastery at 0:36 for 28%: the 0:35 hit), a button on
        for t in alt:  # cooldown's too when its players hold it (not back: Avenging Wrath at 0:35)
            m = min(found, key=lambda m: abs(m.t - t), default=None)
            ok = ((tied or (every and not why)) and m is not None and -ANSWER[0] <= t - m.t <= ANSWER[1]
                  and t not in back)
            alt_near.append(f"{_mmss(m.t)} {m.boss_spell}".strip() if ok else "")
        # a ramp: pressed 8 to 30 s before the hits, on two of them at least and on most presses (Disc's
        # Evangelism at 0:24, 1:42, 3:15 for Vashnik's 0:40, 2:10, 3:35): its job is the hit after it (the owner)
        ramp = False
        if tied and found and _ramp_kind(sid):
            def ahead(t: float):
                m = min((m for m in found if m.t > t), key=lambda m: m.t - t, default=None)
                return m if m is not None and RAMP[0] <= m.t - t <= RAMP[1] else None
            # its moments or another habit of each press (Evangelism: 0:04 on cooldown for some, 0:24 for others)
            hit = {m.t for t in [*times, *alt] if (m := ahead(t))}
            if len(hit) >= 2:
                ramp = True
                # a press made as soon as it is back is its cooldown's, even ahead of a hit: no answer (the
                # lead says where those land)
                near = [n or (f"{_mmss(m.t)} {m.boss_spell}".strip() if t not in back and (m := ahead(t)) else "")
                        for t, n in zip(times, near, strict=False)]
                alt_near = [n or (f"{_mmss(m.t)} {m.boss_spell}".strip() if t not in back and (m := ahead(t))
                                  else "") for t, n in zip(alt, alt_near, strict=False)]
        out.append(Cooldown(name, sid, users, per_kill, times, near, alt, every, support, alt_support, alt_near,
                            alt_of, why, rhythm if len(times) > 1 else 0.0, cd=cd, ramp=ramp,
                            back=sorted(x for x in back if x in times or x in alt),
                            rhythms=sorted(two, key=lambda r: r[1][0]) if two and not (every or why) else [],
                            presses=per_player, pulls=pulls, n_all=n_all, back_half=sorted(half),
                            twice=sum(1 for ts in raw if len(ts) >= 2) / max(1, len(tl.players)),
                            lasts=[p.get("duration") or tl.duration for p in tl.players],
                            press_lasts=pressed_lasts))
    return sorted(out, key=lambda c: -c.users)


RHYTHM_SHARE = 0.2  # of the top players, each of two rhythms at least


def rhythms(per_player: list[list[float]], times: list[float], alt: list[float], n_all: int) -> list:
    """Two groups pressing a button at different moments the whole kill long: the players grouped by the moment of
    their first press (within 8 s), the two largest groups, each RHYTHM_SHARE of the top players at least, each
    said by the median time of each press most of its players make, kept when the two differ by more than 8 s at
    every press (Disc's Evangelism on Vashnik: 31 players at 0:04, 1:42, 3:15, 30 at 0:24, 2:01, 3:35; the chips
    mixed them with "or" and the lead read 1:42 as the next press after 2:07). Matching every press to a moment
    was too strict: the second press of the 0:24 group spreads from 1:47 to 2:15."""
    marks = sorted({*times, *alt})
    groups: dict[float, list[list[float]]] = {}
    for ts in per_player:
        m = min(marks, key=lambda m: abs(m - ts[0]), default=None) if ts else None
        if m is not None and abs(m - ts[0]) <= 8 and len(ts) >= 2:
            groups.setdefault(m, []).append(ts)
    two = sorted(groups.values(), key=len, reverse=True)[:2]
    if len(two) < 2 or len(two[1]) < RHYTHM_SHARE * n_all:
        return []
    out = []
    for g in two:
        moments = []
        for i in range(max(map(len, g))):
            at = [ts[i] for ts in g if len(ts) > i]
            if len(at) < len(g) / 2:
                break
            moments.append(st.median(at))  # each group's own time: the button's moments are set from these
            # (paf.healer.cooldowns), so the chips, the lead and the chart give the same times (rounds 30-32)
        out.append((len(g) / n_all, moments))
    a, b = out[0][1], out[1][1]
    if len(a) < 2 or len(b) < 2 or any(abs(x - y) <= 8 for x, y in zip(a, b, strict=False)):
        return []
    return sorted(out, key=lambda r: r[1][0])


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
    return [(names[i], i, c / n) for i, c in count.most_common(6) if c / n >= 0.10]  # under 10%: no habit


def _mmss(t: float) -> str:
    """Rounded to the second (round 86: truncated, Tranquility's 35.9 s read "as the 0:35 hit starts" and Rewind's
    36.7 s "1 s after")."""
    s = int(round(t))
    return f"{s // 60}:{s % 60:02d}"


CSS = "<style>" + theme.style("healer") + "</style>"
JS = ("<script>document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(!b)return;"
      "navigator.clipboard.writeText(b.dataset.copy).then(function(){b.textContent='Copied'},function(){})})"
      "</script>")


PRESS_ROWS = 4  # cooldown rows drawn under a damage curve


SWAP_LANE = -1  # a Cooldown with this spell id is the tank swaps' lane: ticks, no press marks


def curve_svg(curve: list[float], found: list[Moment], phases: list[tuple[str, float]], label: str,
              presses: list | None = None, named: set[str] | None = None, answered: set | None = None,
              moved: dict | None = None) -> str:
    """A damage-taken curve (per STEP), its big moments as dots, the phases as dashed lines; under it, one row per
    cooldown (Cooldown) with a mark where the top players usually press it: the hit and the button on one time axis."""
    # a lane for a cooldown with a moment 40% of the top players share: a spread one (Divine Steed) has none
    named = named or set()  # the cooldowns the lead names for a hit: their lane first, whatever their share; then
    rows = sorted((c for c in presses or [] if c.times and (c.name in named or (  # one 40% of the top players share,
        max(c.support or [1.0]) >= 0.4 and not c.why and not c.every  # never one tied to no hit by rule,
        and any([*c.near, *(c.alt_near or [])])))),  # nor one that answers none (Innervate, a mana button)
                  key=lambda c: c.name not in named)[:PRESS_ROWS]
    if answered is not None:  # the lead's answers only: the chart draws what the page says, a full mark each
        rows = [c for c in presses or [] if c.name in named][:PRESS_ROWS]
    W, H, L, B = 760, 200 + 18 * len(rows), 150 if rows else 46, 24 + 18 * len(rows)
    peak = max(curve, default=0) or 1
    span = max(len(curve) * STEP, 1)

    def x(t: float) -> str:
        return f"{L + t / span * (W - L - 10):.1f}"

    def y(v: float) -> str:
        return f"{30 + (1 - v / peak) * (H - B - 40):.1f}"  # room above the peaks for their labels
    pts = " ".join(f"{x(i * STEP)},{y(v)}" for i, v in enumerate(curve))
    guides = "".join(f"<line class='gd' x1='{x(m.t)}' x2='{x(m.t)}' y1='{y(m.dtps)}' y2='{H - 22}'/>"
                     for m in found) if rows else ""  # from each hit down through the lanes
    marks = guides + "".join(f"<circle cx='{x(m.t)}' cy='{y(m.dtps)}' r='4' class='mk'><title>{_mmss(m.t)}"
                    + (f" &middot; {'' if m.boss_spell.startswith('mostly') else 'mostly '}{e(m.boss_spell)}"
                       if m.boss_spell else "")
                    + f" &middot; {_x(m.ratio)}&times; the usual damage"  # each dot its hover (round 114)
                    + (f" &middot; {_stage_tag(m.t, phases)}" if _stage_tag(m.t, phases) else "") + "</title></circle>"
                    f"<text x='{float(x(m.t)) + 6:.1f}' y='{float(y(m.dtps)) - 8:.1f}' class='ml'>{_mmss(m.t)}</text>"
                    for m in found)
    lines = "".join(f"<line class='ph' x1='{x(t)}' x2='{x(t)}' y1='22' y2='{H - B}'/>"
                    f"<text x='{float(x(t)) + 4:.1f}' y='18' class='pn'>{e(n.split(':')[0])} &middot; {_mmss(t)}</text>"
                    for n, t in phases if t > 0)  # the phase changes, named
    end_anchor = " text-anchor='end'"  # the last tick inside the right edge (5:00 of a 5:02 fight was cut), the
    mid = " text-anchor='middle'"       # others centred on their minute, the first from the axis's start
    ticks = "".join(f"<text x='{x(t)}' y='{H - 6}' class='tk'{end_anchor if t > span - 20 else mid if t else ''}>"
                    f"{int(t // 60)}:00</text>" for t in range(0, int(span) + 1, 60))
    pos = [v for v in curve if v > 0]
    med = st.median(pos) if pos else 0.0  # the scale the moments are read against (x1.6 the fight's median)
    median = (f"<line class='md' x1='{L}' x2='{W - 10}' y1='{y(med)}' y2='{y(med)}'/>"
              f"<text x='{L - 4}' y='{float(y(med)) - 3:.1f}' class='mdl' text-anchor='end'>median</text>"
              f"<text x='{L - 4}' y='{float(y(med)) + 9:.1f}' class='mdl' text-anchor='end'>{_per_s(med)}</text>"
              ) if med else ""
    cds = "".join(
        f"<text x='{L - 8}' y='{H - B + 16 + 18 * i}' class='cl' text-anchor='end'>{e(_shown(c.name).split(',')[0][:22])}</text>"
        + ("".join(f"<line x1='{x(t)}' x2='{x(t)}' y1='{H - B + 6 + 18 * i}' y2='{H - B + 18 + 18 * i}' class='sw'>"
                   f"<title>{e(c.name)} {_mmss(t)}</title></line>" for t in c.times if t <= span))
        if c.spell_id == SWAP_LANE else
        f"<text x='{L - 8}' y='{H - B + 16 + 18 * i}' class='cl' text-anchor='end'>{e(_shown(c.name).split(',')[0][:22])}</text>"
        + "".join(f"<rect x='{float(x((moved or {}).get((c.name, t), t))) - 4:.1f}' y='{H - B + 6 + 18 * i}' "
                  f"width='8' height='13' rx='2' "
                  f"class='cp{'' if t in tied else ' off'}'><title>{e(_step_name(c.name))} {c.shown_at.get(t) or _mmss((moved or {}).get((c.name, t), t))}"
                  f"{'' if t in tied else _mark_reason(c, t, found)}</title></rect>"
                  for t in sorted([*c.times, *c.alt, *[pt for pt in [_pull_t(c)] if pt is not None]])
                  if t <= span  # in time order (round 84), the pull group the card shows too (round 99)
                  for tied in [{a for a in [*c.times, *c.alt] if (c.name, a) in answered} if answered is not None
                               else {a for a, n in [*zip(c.times, c.near, strict=False),
                                                    *zip(c.alt, c.alt_near or [""] * len(c.alt), strict=False)] if n}])
        for i, c in enumerate(rows))
    return (f"<svg viewBox='0 0 {W} {H}' class='rd' role='img' aria-label='{e(label)}'>"
            f"<line class='ax' x1='{L}' x2='{W - 10}' y1='{H - B}' y2='{H - B}'/>{median}{lines}{ticks}"
            f"<polyline points='{pts}'/>{marks}{cds}</svg>")


def _per_s(v: float) -> str:
    """A damage rate on the chart's axis: 1.4M/s, 820k/s."""
    return f"{v / 1e6:.1f}M/s" if v >= 1e6 else f"{v / 1e3:.0f}k/s"


def moments_html(found: list[Moment], what: str, phases: list | None = None) -> str:
    """what: kept for the callers; a moment no boss cast explains shows its time only; in a later stage, its time
    from that stage's start, the one a raider reads on their own kill (round 103: 3:50 is Stage Two +0:52)."""
    return "".join(f"<li><b>{_mmss(m.t)}</b><span>{e(m.boss_spell) if m.boss_spell else ''}</span>"
                   f"<small>{_x(m.ratio)}&times; the usual damage"
                   + (f" &middot; {e(tag)}" if (tag := _stage_tag(m.t, phases)) else "") + "</small></li>"
                   for m in found)


def hits_table(moments: list, shown: list, pairs: list, bare: dict, phases: list | None, by_icon: dict,
               rule: str, tags: dict | None = None, usual: str = "raid damage") -> str:
    """The big hits as a table: when, what hits, how hard (a bar), and what the top players press for it, with its
    icon; the lead's clauses each on their hit's row (a press said for two hits: on the first, the second points to
    it), a hit kept for none with why. Replaces the lead's long sentence and the list under the chart (the owner:
    less text)."""
    if not moments:
        return ""
    top = max(m.ratio for m in moments) or 1
    said: dict[str, str] = {}  # hit time -> its answer cell
    for _t, text in pairs:
        ts = re.findall(r"the (\d+:\d\d) hits?", text) + re.findall(r"(\d+:\d\d)(?:,| and) ", text.split("hits:")[0]
                                                                           if "hits:" in text else "")
        first = next((x for x in ts), None) or _mmss(_t)
        cell = re.sub(r"^for the \d+:\d\d hit, ", "", text)
        cell = re.sub(r" \((\d+) kills going\) \(about ([^)]*)\)", r" (about \2; \1 kills going)", cell)  # one bracket
        cell = _unnest(cell[:1].upper() + cell[1:])
        names = sorted((n for n, c in by_icon.items() if c is not None and getattr(c, "icon", "")), key=len, reverse=True)
        if names:  # each button's icon before its own name, in the text's order (a review: one icon, the wrong one)
            pat = re.compile(r"(?<![\w>])(" + "|".join(re.escape(e(n)) for n in names) + r")(?!\w)")
            seen: set[str] = set()

            def pic(m, seen=seen) -> str:
                n = html.unescape(m.group(1))
                if n in seen:
                    return m.group(1)
                seen.add(n)
                return _ic(by_icon[n]) + m.group(1)
            cell = pat.sub(pic, cell)
        said[first] = cell
        for x in dict.fromkeys(ts):
            if x != first:
                said.setdefault(x, f"<span class='muted'>the other choice of the press on the {first} row</span>")
    lead = {_mmss(m.t) for m in shown}
    # one reason on several rows: said once under the table (heal round 10: "None kept (no long defensive of theirs
    # pressed by a tenth of them in it)" twice under a lead saying none is kept)
    # its kills-going count left out: nobody pressed, so it says nothing (heal round 11: "; 89 kills going" kept
    # the 3:35 row apart from the 2:10's)
    def bare_of(v: str) -> str:
        v = re.sub(r" \(\d+ kills going\)\)$", ")", v)  # as _reach_note writes it, inside the reason's bracket
        return re.sub(r"; \d+ kills going\)$", ")", v) if re.fullmatch(r" \(no [^()]*\)", v) else v
    common = Counter(bare_of(v) for k, v in bare.items() if k not in said).most_common(1)
    same = common[0][0] if common and common[0][1] >= 2 and re.fullmatch(r" \(no [^()]*\)", common[0][0]) else None
    rows = []
    for m in sorted(moments, key=lambda m: m.t):
        k = _mmss(m.t)
        if k in said:
            ans = said[k]
        elif k in bare:
            ans = f"<span class='none'>None kept</span>{'' if bare_of(bare[k]) == same else _unnest(bare[k])}"
        else:  # a big moment past the lead's four
            ans = "<span class='muted'>not among the highest, the table reads four</span>" if k not in lead else ""
        tag = _stage_tag(m.t, phases)
        rows.append(f"<tr><td class='t'><b>{k}</b>" + (f"<small>{e(tag)}</small>" if tag else "") + "</td>"
                    f"<td>{e(m.boss_spell) if m.boss_spell else '<span class=muted>raid damage</span>'}"
                    + "".join(f"<span class='tag'>{x}</span>" for x in (tags or {}).get(k, [])) + "</td>"
                    f"<td class='sz'><span class='track'><span class='bar' style='width:{max(8, round((m.ratio - 1) / max(0.01, top - 1) * 100))}%'></span></span>"
                    f"<b>{_x(m.ratio)}&times;</b></td><td class='ans'>{_tidy(ans)}</td></tr>")  # the legend's ⟲, as the chips
    return ("<table class='hits'><thead><tr><th>When</th><th>What hits</th><th>Size &times;</th><th>What the top players press</th></tr></thead><tbody>" + "".join(rows)
            + f"</tbody></table><p class='small muted hits-rule'>{rule + '. ' if rule else ''}"
            + (f"None kept with no reason beside it: {same.strip()[1:-1]}. " if same else "") + "Size: &times; the usual "
            f"{usual}; bars from 1&times; to the biggest hit.</p>")


def _stage_tag(t: float, phases: list | None) -> str:
    """"Stage Two +0:52": a time's place in the stage it falls in, after the first one (stage time)."""
    cur = max(((n, s) for n, s, *_r in phases or [] if 0 < s <= t), key=lambda x: x[1], default=None)
    return f"{cur[0].split(':')[0]} +{_mmss(t - cur[1])}" if cur else ""


def _shown(name: str) -> str:
    """A spell's name without the log's internal suffix ("Stasis (Store)" -> "Stasis")."""
    return re.sub(r"\s*\([^)]*\)$", "", name) or name


KEPT = "\x00kept"  # a key of `named` no button has: (KEPT, hit) -> (the button the lead keeps, its share)


def _not_kept(hit: float, hs: float, named: dict | None, c: Cooldown | None = None) -> str:
    """"not kept for the X hit: N% in its window", with the lead's button when N reaches the quarter bar, and the
    kills still going (round 102: a late hit's share without its count)."""
    kept = (named or {}).get((KEPT, hit))
    from paf.defensives import is_defensive

    why = (", a personal defensive, no raid answer" if c is not None and is_defensive(c.spell_id, c.name)  # round
           else f", under {e(kept[0])}'s {_pct(kept[1])}"  # 104; the kept button whatever the
           if kept and (c is None or kept[0] != _shown(c.name)) else "")  # window share (round 105: Yu'lon "16% in
    # its window" read as the reason, its time shared by 30%)
    return (f" &middot; not kept for the {_mmss(hit)} hit: {_pct(hs)} in its window"
            f"{_reach_note(c, hit) if c is not None else ''}{why}")


def _untied_at(c: Cooldown, t: float, n: str, tied: str, named: dict | None) -> str:
    """A main time in a hit's window the lead does not keep: its count there said (round 90: "a time with no hit
    named lands on none" read false for a press in the hit's window)."""
    if not n or tied or (named or {}).get((c.name, t)) is not None or t in c.back or c.why or c.every:
        return ""
    hit = _secs(n.partition(" ")[0])
    hs = hit_share(c, t, hit)
    return "" if hs is None else _not_kept(hit, hs, named, c)


def _window_said(c: Cooldown, t: float, n: str, tied: str, named: dict | None, sp: float) -> bool:
    """A chip whose hit-window share follows: its own timed share left out, one number for one press (heal round
    11: "4:16 · 19% (26% of its users) · not kept for the 4:15 hit: 20% in its window")."""
    if _untied_at(c, t, n, tied, named) or _split(_named(c, t, named, tied, sp))[1]:
        return True  # a window clause on the chip: its share is the one (heal round 12: "3:49 · 30% · in the
        # window of the 3:50 hit: 22%")
    return t in c.back and not (c.why or c.every) and bool(_lead_back(c, t))  # (its window's share follows)


def _also_pressers(c: Cooldown, t: float, named: dict | None, n: str, sp: float) -> str:
    """A chip's share under a quarter, also of those who press the button: the moment's, or a tied chip's hit share
    (round 89: Shield Wall "0:34 · 1 s before the 0:35 hit · 23%" said none)."""
    shown = _named(c, t, named, n, sp)
    if "of its users" in shown:
        return ""
    if _split(shown)[0] in (_share(sp), _share(sp) + _still(c, t, sp)):  # its own share, before a window clause (r. 90:
        return _pressers(c, sp, t)                                # Shield Wall "3:52 · 24% · in the window…")
    if n and (hs := hit_share(c, t, _secs(n.partition(" ")[0]))) is not None and shown == _base(
            c, hs, _secs(n.partition(" ")[0])):
        end = _secs(n.partition(" ")[0]) + ANSWER[1]  # the window's base: its kills reaching the window's end
        u = _users_at(c, end)  # (round 109: "24% of those who press it" on a chip the window admitted at 25%)
        if hs and u and hs / u < 0.25 - 1e-9 and (ut := _users_at(c, t)):  # a kept time the window's share
            return f" ({_pct(min(1.0, sp / ut))} of its users)"  # one form (heal round 14); reads under: its own
        return _pressers(c, hs, end)  # (round 114: Aura Mastery 4:20 "24%", kept by its time at 28%)
    return ""


def _users_at(c: Cooldown, t: float | None) -> float:
    """The share of the top players pressing the button, of the kills still going at t (the keep test's base)."""
    if t is None or not c.lasts or len(c.press_lasts) != len(c.presses):
        return c.users
    going = sum(1 for d in c.lasts if d >= t)
    if not going or going == len(c.lasts):  # every kill reaches it: the header's share (round 113: 33% of those who
        return c.users                       # press it read against a header's 74%, timed presses only)
    reach_ = sum(1 for d in c.press_lasts if d >= t) / max(1, len(c.press_lasts))  # every caster, as the header
    return min(1.0, c.users * len(c.lasts) * reach_ / going)


def _kept_by_time(c: Cooldown, t: float, hit: float, sp: float) -> str:
    """A time kept by its own share of those who press it while its hit's window reads under a quarter of them: the
    time's share said beside the window's (round 114: "23% press Aura Mastery" for 4:15, kept by 4:20 at 28%)."""
    u = _users_at(c, hit + ANSWER[1])
    if t not in c.times or not sp or not u or sp / u >= 0.25 - 1e-9 or len(c.support) != len(c.times):
        return ""
    ut = _users_at(c, t)
    return f" ({_pct(min(1.0, c.support[c.times.index(t)] / ut))} of its users)" if ut else ""  # one form


def _pressers(c: Cooldown, sp: float, t: float | None = None) -> str:
    """Under a quarter of all the top players, the share of those who press the button, the one the quarter rule
    reads (round 83: "Shield Wall 2:57 · 15%" read as under the rule; 25% of the 60% who press it)."""
    u = _users_at(c, t)  # the keep test's own base, so a time shown never reads under the quarter (round 108:
    if not sp or sp >= 0.25 or not u or _pct(sp / u) == _pct(sp):  # "18% (24% of those who press it)")
        return ""
    return f" ({_pct(min(1.0, sp / u))} of its users)"


def _share(sp: float) -> str:
    """How many of the top players press it then: a chip is no consensus ("1:16 · 28% of them")."""
    return f" &middot; {_pct(sp)}" if sp else ""  # of the top players: the legend says it once


def _times_line(c: Cooldown) -> str:
    """A side line's button: who presses it, then each time with its own share (round 111: "Divine Steed (71%, about
    2:20)" read as 71% at 2:20, 29% press it there)."""
    shares = c.support or [0.0] * len(c.times)
    times = "; ".join(f"{_pct(sp)} about {_mmss(t)}" if sp else f"about {_mmss(t)}"
                      for t, sp in zip(c.times, shares, strict=False))
    return f"pressed by {_pct(c.users)}" + (f"; {times}" if times else ", no shared moment")


def _twice(c: Cooldown, named: dict | None = None) -> str:
    """A button pressed once a kill by most, twice by some: said, or its shares add past who presses it (round 110:
    Ultimate Penitence 27 + 20 + 15 + "the other 38%" past its 97%, 31% pressing it twice). Only when they do add
    past it (heal round 10: Spirit Link Totem 17 + 76 = its 93%, the caveat explained an overlap not there)."""
    if not c.presses or not c.n_all:
        return ""
    lines = [v[0] for k, v in (named or {}).items() if k[0] == c.name and isinstance(k[1], tuple)]
    if sum([*(c.support or []), *(c.alt_support or []), *lines]) + _rest(c, named) <= c.users + 0.005:
        return ""
    two = c.twice if c.twice >= 0 else sum(1 for ts in c.presses if len(ts) >= 2) / c.n_all  # every cast (r. 111)
    return f" ({_pct(two)} press it twice: a player can count in two shares)" if two >= 0.1 else ""


def _rest(c: Cooldown, named: dict | None = None) -> float:
    """A button pressed once a kill: the share of the top players its chips leave out (round 87: Ultimate Penitence
    pressed by 97%, its chips 27% and 20%, the other half unsaid). Its players press it once, so the chips' shares
    are of different players."""
    if round(c.per_kill) != 1 or c.every or c.why:
        return 0.0
    if c.presses and c.n_all:  # the players its card shows, counted: shares on different bases did not add up
        hits = [k[1][1] for k in (named or {}) if k[0] == c.name and isinstance(k[1], tuple)]  # (round 109: 52% -
        # a chip tied to a hit shows its window's players: those counted, as its share (round 110: 15% shown, 19
        # counted within 8 s of its time)
        for _t, n in zip(c.times, c.near or [""] * len(c.times), strict=False):
            if n:
                hits.append(_secs(n.partition(" ")[0]))
        free = [t for t, n in zip(c.times, c.near or [""] * len(c.times), strict=False) if not n] + list(c.alt)
        shown = sum(1 for ts in c.presses if any(abs(x - t) <= 8 for x in ts for t in free)  # 15% read
                    or any(h - ANSWER[0] <= x <= h + ANSWER[1] for x in ts for h in hits))  # "the other 36%")
        return max(0.0, c.users - shown / c.n_all)  # of every player pressing it, as "pressed by" (round 110: a
        # press past a stage's end, left out of the times, read 52% - 15% as "the other 34%")
    lines = [v[0] for k, v in (named or {}).items() if k[0] == c.name and isinstance(k[1], tuple)]  # its card's own
    return max(0.0, c.users - sum([*(c.support or []), *(c.alt_support or []), *lines]))  # lines too (round 89)


def _more(c: Cooldown, named: dict | None = None) -> str:
    """The casts a kill no shared moment shows ("+1"): the count always matches the "a kill" number; a press its
    card names in a hit's window counts as shown (round 94: Apotheosis "2 a kill", 0:40, about 2:16 and "+1 more")."""
    lines = sum(1 for k in named or {} if k[0] == c.name and isinstance(k[1], tuple))
    n = round(c.per_kill) - len(c.times) - lines  # the pull chip is the first press's other habit, not another press
    return f"+{n}" if n > 0 else ""


def hit_share(c: Cooldown, t: float, hit: float) -> float | None:
    """The share of the top players with a press of c in the hit's answer window (5 s before to 8 s after it; a ramp:
    within 8 s of its own time, ahead of the hit): what a press tied to a hit is said with. The moment's own share
    (within 8 s of the press) counted Revival up to 13 s after Vashnik's 0:40 hit: 49% against 35% (round 34)."""
    if not c.presses or not c.n_all:
        return None
    a, b = _window(c, t, hit)
    end = hit + ANSWER[1]  # the presses of the kills the base counts only (round 54: 19 presses, 16 of the 58 kills)
    lasts = c.press_lasts if len(c.press_lasts) == len(c.presses) else [end] * len(c.presses)
    return sum(1 for ts, d in zip(c.presses, lasts, strict=False)
               if (not c.lasts or d >= end) and any(a <= x <= b for x in ts)) / reach(c, hit)


def _window(c: Cooldown, t: float, hit: float) -> tuple[float, float]:
    """A press's window for a hit: the hit's answer window, or a ramp's own, ending where the hit's begins (round 52)."""
    if c.ramp and hit - t >= RAMP[0]:  # the ramp window the footnote states, 8 to 30 s ahead, never the pull's
        return max(hit - RAMP[1], PULL), hit - RAMP[0]  # opener (round 55: counted around one chip, 30% for 36%)
    return hit - ANSWER[0], hit + ANSWER[1]


def _counted(c: Cooldown, t: float, hit: float) -> list[float]:
    """The presses a hit's share counts: in the window, of the kills still going at its end."""
    a, b = _window(c, t, hit)
    end = hit + ANSWER[1]
    lasts = c.press_lasts if len(c.press_lasts) == len(c.presses) else [end] * len(c.presses)
    return [x for ts, d in zip(c.presses, lasts, strict=False) if not c.lasts or d >= end for x in ts if a <= x <= b]


def _back_in(c: Cooldown, t: float, hit: float) -> float | None:
    """Of the presses a hit's share counts, the share made within its cooldown + BACK of the player's own previous
    one: "back from cooldown" said of the same presses as the share (round 62: Celestial Conduit's window, 72% back,
    read "for about half" from the 2:09 moment's presses)."""
    if not c.cd or not c.presses:
        return None
    a, b = _window(c, t, hit)
    end = hit + ANSWER[1]
    lasts = c.press_lasts if len(c.press_lasts) == len(c.presses) else [end] * len(c.presses)
    pulls = c.pulls if len(c.pulls) == len(c.presses) else [None] * len(c.presses)
    gaps = [_gap(ts, pl, j) for ts, pl, d in zip(c.presses, pulls, lasts, strict=False)
            if not c.lasts or d >= end for j, x in enumerate(ts) if a <= x <= b]
    return (sum(1 for g in gaps if g is not None and g <= c.cd + BACK) / len(gaps)) if gaps else None


def reach(c: Cooldown, hit: float) -> int:
    """The top players whose kill reaches a hit: a late hit's share is of them (round 47: 42 of the 100 top Prot
    kills end before Nek'zali's 3:55, its "only 19%" was 33% of those still fighting)."""
    return max(1, sum(1 for d in c.lasts if d >= hit + ANSWER[1]) if c.lasts else c.n_all)  # through its window


def _reach_note(c: Cooldown, hit: float) -> str:
    n = reach(c, hit)
    # said whenever a kill ended before it: "51% of the top players" read as 51 of 100 for 48 of 95 (round 84)
    return f" ({n} kills going)" if c.lasts and n < len(c.lasts) else ""  # the legend says what (the owner: less text)


def _secs(mmss: str) -> float:
    m, _, sec = mmss.partition(":")
    return int(m) * 60 + int(sec)


def _or(c: Cooldown, t: float, answered: set | None = None, named: dict | None = None,
        moved: dict | None = None) -> str:
    """The other habits nearest this moment, said on its chip ("1:18, or 0:36 for some"): another player's choice
    for the same press, never an extra one."""
    near = [(a, sp, n) for a, sp, k, n in zip(c.alt, c.alt_support or [0.0] * len(c.alt),
                                              c.alt_of or [None] * len(c.alt), c.alt_near or [""] * len(c.alt),
                                              strict=False)
            if (k if k is not None else min(c.times, key=lambda x: abs(x - a))) == t]  # the same press only
    if not near:
        return ""
    # every other habit, each said, with the hit it answers as the main time is ("0:34 · 1 s before the 0:35 hit")
    orig = {a: n for a, _sp, n in near}  # the hit a habit sits in, tied or not
    near = [(a, sp, n if answered is None or (c.name, a) in answered else "") for a, sp, n in near]

    def untied(a: float, n: str) -> str:  # in a hit's window, not kept by the lead: its count there said, so "lands
        h = orig.get(a) or ""              # on none" never reads false (round 90: Yu'lon "or 0:32" in the 0:35 hit)
        if (n or not h or (named or {}).get((c.name, a)) is not None or a in c.back or c.why
                or (c.every and a not in _held(c))):  # a held habit of a button on cooldown too (round 91: Conduit
            return ""                                  # "or 0:37 for 25%" in the 0:35 hit, no clause)
        hit = _secs(h.partition(" ")[0])
        hs = hit_share(c, a, hit)
        return "" if hs is None else _not_kept(hit, hs, named, c)
    # a tied habit keeps its moment's share; its hit's window count follows, as a named one's (round 64: "or 0:23
    # for 36%" beside a main "0:04 · 31%" mixed a window share with a moment's)
    def back(a: float) -> str:  # tagged as the main time is (Evangelism's 1:42 habit, round 29)
        return f" &middot; back from cooldown{' for about half' if a in c.back_half else ''}{_lead_back(c, a)}"
    def window(a: float, n: str = "") -> str:  # a habit the lead names or ties for a hit: its count, after the
        hit = (named or {}).get((c.name, a))      # habit's own tag, with its own back-from-cooldown reading
        if hit is None and n:                     # (rounds 51, 63, 64)
            hit = _secs(n.partition(" ")[0])
        if hit is None or (hs := hit_share(c, a, hit)) is None:
            return ""
        if n and not (named or {}).get((c.name, a)):  # tied: its chip names the hit already; one share when equal
            return "" if _pct(hs) == _pct(sp_of[a]) else f" &middot; in its window:{_base(c, hs, hit).replace(' &middot;', '')}"
        where = "ahead of" if c.ramp and a < hit - ANSWER[0] else "in the window of"
        b = None if c.why == MINUTE else _back_in(c, a, hit)
        tag = ("" if b is None or b <= BACK_SHARE[0] else ", back from cooldown"
               + (" for about half" if b <= BACK_SHARE[1] else ""))
        return f" &middot; {where} the {_mmss(hit)} hit:{_base(c, hs, hit).replace(' &middot;', '')}" + tag
    sp_of = {a: sp for a, sp, _n in near}

    def at(a: float) -> float:  # an "or" time named for a hit's window: shown at the window's own time
        hit = (named or {}).get((c.name, a))
        inside = _counted(c, a, hit) if hit is not None and hit_share(c, a, hit) is not None else []
        return _center(inside) if inside else (moved or {}).get((c.name, a), a)

    def one(a: float, sp: float, n: str) -> str:  # one share a press: its window's when one is said (heal round 11:
        w, u = window(a, n), untied(a, n)          # "for 29% · in its window: 26%", "for 27% · ⟲, … window: 23%")
        bk = "" if w and "back from cooldown" in w else back(a) if a in c.back and not c.why else ""
        own = (f" &middot; {_pct(sp)}{_still(c, a, sp)}{_pressers(c, sp, a)}" if sp
               else " &middot; some")  # one form, as a main chip ("or 2:02 · 30%"; heal round 12: three forms)
        if w.startswith(" &middot; in its window:"):  # tied: the window's share is the chip's
            own, w = " &middot;" + w[len(" &middot; in its window:"):], ""
        elif u or w or "in the window of" in bk:  # a window's share said: the only one (heal round 12: "or 2:10 for
            own = ""                            # 32% · in the window of the 2:10 hit: 25%")
        return f"{_chip(at(a), n)}{own}{bk}{w}{u}"
    return ", or " + ", ".join(one(a, sp, n) for a, sp, n in near)


BACK = 8.0  # seconds past its cooldown a press still counts as pressed as soon as it is back
# the share of a moment's players pressing it as soon as it is back over which it is no answer; up to the second, said
# "for about half": Disc's Evangelism at 2:01 sat at 0.52, a tie to the 2:10 hit decided by a coin flip (round 35)
BACK_SHARE = (0.4, 0.6)


def back_share(per_player: list[list[float]], t: float, cd: float, pulls: list | None = None) -> float:
    """Of the players pressing a button about t (within 8 s), the share whose own press before it is within its
    cooldown plus BACK: they press it as soon as it is back. Read per player, never between moments (Evangelism's
    0:04 and 2:07 moments are 123 s apart, yet its players press it 90-102 s after their own last one)."""
    gaps = [_gap(ts, pulls[i] if pulls and len(pulls) == len(per_player) else None, j)
            for i, ts in enumerate(per_player) for j, x in enumerate(ts) if abs(x - t) <= 8]
    return (sum(1 for g in gaps if g is not None and g <= cd + BACK) / len(gaps)) if gaps and cd else 0.0


def _gap(ts: list[float], pull: list[float] | None, j: int) -> float | None:
    """A press's gap from the player's own previous one, in pull time when its pull times are known (they follow
    its stage times one to one, in the same order)."""
    if j == 0:
        return None
    src = pull if pull is not None and len(pull) == len(ts) else ts
    return src[j] - src[j - 1]


GROUP_GAP = 10.0  # seconds between two groups of presses in one window said apart ("1:41 or 2:01")
GROUP_SHARE = 0.3  # ... each holding this share of the presses at least
SPREAD = 12.0  # seconds the middle half of the presses counted spans from which their span is said, not a median
FEW_SHARE = 0.1  # a press in a hit no cooldown is kept for, said under the quarter bar from this share
SLACK = 3.0  # seconds past the answer window a moment may sit when its presses are counted in the window
PULL = 12.0  # seconds: a press before this is the pull's opener, never a ramp for the first hit (round 45)
OR_NEAR = 20.0  # seconds: the farthest "or" time of a button pressed about every minute or on cooldown
MINUTE = "about every minute"  # the reason a button pressed four times a kill or more is tied to no hit


def landed_in(m: Moment, cds: list[Cooldown], named: dict | None = None, word: str = "raid cooldown") -> str:
    """The press most of them make inside a hit no cooldown is kept for, and why it is no answer: "(35% have
    Tranquility land at 3:43, back from cooldown)". Every button and habit is read (Celestial Conduit's 2:11 habit,
    Life Cocoon), the same for healers and tanks."""
    near = []
    for c in cds:
        if _item(c.spell_id) or _external(c.spell_id) == "damage":  # a trinket, Power Infusion on a damage dealer:
            continue                                                  # nothing for the raid's hit
        if c.why and c.why != MINUTE:  # an external (Life Cocoon), an item: no raid answer to name; a button
            continue  # pressed about every minute is, with its reason (70% Convoke 4 s before Nek'zali's 1:15; round 37)
        for t, sp in [*zip(c.times, c.support or [], strict=False), *zip(c.alt, c.alt_support or [], strict=False)]:
            ramp = c.ramp and RAMP[0] <= m.t - t <= RAMP[1]  # a ramp lands its hit from 8 to 30 s ahead (Disc's
            # 2:01 Evangelism, 9 s before 2:10; round 36); a moment just past the window counts when its presses
            # are counted in it (Celestial Conduit's 3:43, 34% in Vashnik's 3:35 window; round 50)
            slack = SLACK if c.presses else 0.0
            if -ANSWER[0] - slack <= t - m.t <= ANSWER[1] + slack or ramp:
                why = ("pressed about every minute" if c.why == MINUTE else c.why or ("on cooldown" if c.every else "back from cooldown"
                                 + (" for about half" if t in c.back_half else "") if t in c.back else ""))
                if why:  # its share in the hit's window, as a tied press's (round 45: Convoke's 70% was its cluster's)
                    hs = hit_share(c, t, m.t)
                    if hs is not None and not hs:
                        continue
                    near.append((sp if hs is None else hs, c, t, why))
    from paf.defensives import is_defensive

    # a raid cooldown that answers a hit somewhere, as the chart's (Innervate, a mana button: "only 11%" on Vashnik's
    # 3:35), read in the window under the quarter bar (Nek'zali's 0:35: 20% of the top Discs press Ultimate Penitence)
    few = [(hs, c) for c in cds if not (c.why or c.every or _item(c.spell_id)
                                        or _external(c.spell_id) == "damage" or is_defensive(c.spell_id, c.name)
                                        or not (c.ramp or any([*c.near, *(c.alt_near or [])]) or _raid(c.spell_id)))
           for hs in [hit_share(c, m.t, m.t)] if hs and FEW_SHARE <= hs]  # (a raid kind by the game data
    few += [(hs, c.release) for c in cds if c.release is not None  # a two-step button's release competes too: its
            for hs in [hit_share(c.release, m.t, m.t)] if hs and FEW_SHARE <= hs]  # heal (round 103: Stasis 24%)
    # counts too: Spirit Link Totem, 17% in Vashnik's 2:10, timing varies elsewhere; round 58)

    def said(c: Cooldown, hs: float, reason: str) -> str:  # one wording for every hit kept for none (round 58),
        inside = _counted(c, m.t, m.t)                       # its time the counted presses', its chip named
        when = st.median(inside) if inside else m.t
        if not reason:  # a raid button's presses there judged too (round 67: Tip the Scales, "for about half"),
            b = _back_in(c, m.t, m.t)  # before its card line keeps it (round 69)
            reason = ("" if b is None or b <= BACK_SHARE[0] else "back from cooldown"
                      + (" for about half" if b <= BACK_SHARE[1] else ""))
        if hs >= 0.25 and not reason and c.presses:  # a quarter or more in the window, refused: its time's share
            pl = c.press_lasts if len(c.press_lasts) == len(c.presses) else [when] * len(c.presses)
            going = [ts for ts, d in zip(c.presses, pl, strict=False) if d >= when]  # those whose kill reaches it
            k = sum(1 for ts in going if any(abs(x - when) <= 8 for x in ts))  # said, the rule's (round 103: "no
            if going and k < 0.25 * len(going):  # time they share is near it" read false for presses at 4:17 to 4:21;
                reason = (f"its {_mmss(when)} is shared by {int(k / len(going) * 100)}% of those who press it, under a "
                          "quarter")  # round 104: of the kills still going), on its card too; said only when so;
                # rounded down beside "under a quarter" (round 105: 24.7% read "25%, under a quarter")
        near_t = min([*c.times, *c.alt], key=lambda x: abs(x - when), default=None)
        if named is not None and near_t is not None and abs(near_t - when) <= 15:
            named[(c.name, near_t)] = m.t
        elif named is not None:  # no chip near it: its card gets a line of its own (round 66: Spirit Link Totem
            named[(c.name, ("line", m.t))] = (hs, _about(inside) if inside else _mmss(when), _reach_note(c, m.t),
                                              reason)  # "timing varies" under the
            # lead's 2:12), its reason too (round 69: Apotheosis "back from cooldown")
        few_ = "only " if hs < 0.25 else ""
        verb = (f"release a {e(c.name[:-len(' release')])}, whichever store it was," if c.name.endswith(" release")
                else f"press {e(_shown(c.name))}")
        return (f" ({few_}{_pct(hs)} {verb} in its window{_reach_note(c, m.t)}, about "
                f"{_mmss(when)}{', ' + reason if reason else ''})")
    best_near = max((x[0] for x in near), default=0.0)
    rhythm_only = all(x[1].why == MINUTE or x[1].every for x in near)
    # under the bar, a raid cooldown about as common wins over a button pressed about every minute (round 57:
    # Nature's Swiftness 16% named over Spirit Link Totem's 17%, Convoke 19% over Tranquility's 21%)
    # and a raid cooldown pressed as much as the near presses when none of them is one (round 101: Obsidian Scales
    # 16% named for Nek'zali's 3:50 over Rewind's 20%; Tranquility 26%, no chip near 4:15, read as "none")
    no_raid = not any((_raid(x[1].spell_id) and not is_defensive(x[1].spell_id, x[1].name)) or x[1].ramp
                      for x in near)  # a personal defensive is no raid cooldown, whatever its game data's kind
    if few and (not near or (best_near < 0.25 and rhythm_only and max(h for h, _c in few) >= best_near - 0.03)
                or (no_raid and max(h for h, _c in few) >= best_near)
                or max(h for h, _c in few) > best_near + 0.03):  # clearly more pressed (round 103: a Stasis release
        # 24% under a Rewind 19% back from cooldown)
        hs, c = max(few, key=lambda x: x[0])
        return said(c, hs, "")
    if not near:
        on_cd = [(hs, c) for c in cds if c.every and _external(c.spell_id) != "damage" and not _item(c.spell_id)
                 for hs in [hit_share(c, m.t, m.t)] if hs and hs >= FEW_SHARE]  # (round 101: Power Infusion named)
        if on_cd:  # a button pressed on cooldown lands there: said, or "no long cooldown" is false (round 57: Stasis)
            hs, c = max(on_cd, key=lambda x: x[0])
            return said(c, hs, "on cooldown")
        some = next((c for c in cds if c.lasts), None)  # in the kills still going, as every share (round 65)
        return (f" (no {word} of theirs pressed by a tenth of them in it{_reach_note(some, m.t) if some else ''})"
                if cds else "")  # (round 59: Lay on Hands,
        # Avatar are long buttons, no raid cooldown nor defensive)  # (round 56: shorter
        # buttons, Divine Toll's 30 s, are not on the sheet's cards)
    # the closest of the presses a quarter make (Disc's 2:01 Evangelism, 9 s before 2:10, over its 1:41 one, 29 s)
    # a ramp button is read on its ramp window first (round 56: Disc's 3:35 read on the hit's, 29% for 39%)
    # and a raid cooldown before a button pressed about every minute or on cooldown (Tranquility 21%, back from
    # cooldown, over Convoke's 19% on Vashnik's 3:35; round 57)
    sp, c, t, why = max(near, key=lambda x: (x[0] >= 0.25, x[1].ramp and m.t - x[2] >= RAMP[0],
                                              not (x[1].why == MINUTE or x[1].every), -abs(m.t - x[2]), x[0]))
    if named is not None and c.presses:  # its chip gives the same count, said of this hit (round 50)
        named[(c.name, t)] = m.t
    few = "only " if sp < 0.25 else ""  # under a quarter, as the bare hits' "only N%" (round 39)
    of = _reach_note(c, m.t) if c.presses else ""  # counted in the hit's window: said, as its chip counts its moment
    ramp = c.ramp and t < m.t - ANSWER[0]
    inside = _counted(c, t, m.t)
    back = _back_in(c, t, m.t)  # judged on the counted presses, as the share (round 62)
    if back is not None and why.startswith("back from cooldown"):
        why = ("back from cooldown" if back > BACK_SHARE[1] else "back from cooldown for about half"
               if back > BACK_SHARE[0] else why)
    when = _about(inside) if inside else _mmss(t)  # the presses counted, not the moment's (round 53: "2:20" for a
    if ramp:                                          # window ending at 2:18, its presses at 2:14)
        return f" ({few}{_pct(sp)} ramp with {e(_shown(c.name))} ahead of it{of}, about {when}, {e(why)})"
    return f" ({few}{_pct(sp)} press {e(_shown(c.name))} in its window{of}, about {when}, {e(why)})"


def on_others(con, encounter_id: int, difficulty: int, spec: str, spell_ids: list[int]) -> dict[int, float]:
    """The share of each spell's casts by the ranked players that land on another player (Life Cocoon on Nek'zali:
    124 of 153; the rest on the Monk himself): the card's "a kill" and the deeper table's "on others" then agree."""
    from paf.corpus.analyze import kills_filter

    if not spell_ids:
        return {}
    where, params = kills_filter(encounter_id, difficulty)
    ids = ",".join(str(int(i)) for i in spell_ids)
    out = {}
    for sid, n, others in con.execute(
            f"SELECT c.ability_id, COUNT(*), SUM(c.target_id IS NOT NULL AND c.target_id != c.actor_id) "
            f"FROM player_cast c JOIN fight f USING(report, fight_id) JOIN ranked r ON r.report=c.report "
            f"AND r.fight_id=c.fight_id AND r.actor_id=c.actor_id WHERE {where} AND r.spec=? AND c.type='cast' "
            f"AND c.ability_id IN ({ids}) GROUP BY c.ability_id", (*params, spec)):
        if n:
            out[sid] = (others or 0) / n
    return out


def _rank(named: list[str]):
    """The order of the cooldown rows: the lead's answers, the other buttons tied to a hit, those on cooldown, then
    those never tied to one (a movement button, a trinket); by press share within each (Nature's Swiftness, 5 a
    kill, listed above Spirit Link Totem)."""
    def key(c: Cooldown) -> tuple:
        return (0 if c.name in named else 1 if any([*c.near, *(c.alt_near or [])]) else 3 if c.why
                else 2, -c.users)
    return key


def _lead_back(c: Cooldown, t: float) -> str:
    """A time back from cooldown the lead names in a hit's window: the lead's count said on it (round 114: "Shield
    Wall 23% in its window" beside a chip saying "3:27 for 27%" only)."""
    hit = c.lead_back.get(t)
    if hit is None or (hs := hit_share(c, t, hit)) is None:
        return ""
    return f" &middot; in the window of the {_mmss(hit)} hit:{_base(c, hs, hit).replace(' &middot;', '')}"  # one form


def _or_then_untied(c: Cooldown, t: float, n: str, tied: str, answered, named, moved) -> str:
    """A chip's "or" time, then why its time is not kept, led by that time: the reason after the "or" read as a third
    reason glued to it (round 114: Obsidian Scales "… no raid answer, or 3:49 for 17%")."""
    alt, why = _or(c, t, answered, named, moved), _untied_at(c, t, n, tied, named)
    return why + alt  # its own time's reason first, then the "or" (heal round 12: "4:17, or 3:49 … · 4:17 not
    # kept for the 4:15 hit", the main time said twice and its share last)


LEGEND_USE = {"On cooldown": "on cooldown", "&#10226; back from cooldown": "&#10226;", "&ldquo;or&rdquo;": ", or ",
              "of its users": "of its users"}


def legend_for(dl: str, page: str) -> str:
    """A legend with only the terms its page uses (a review: "On cooldown" defined where no card is)."""
    low = page.lower()
    def keep(m) -> str:
        term = m.group(1)
        need = LEGEND_USE.get(term)
        return m.group(0) if need is None or need in low else ""
    out = re.sub(r"<dt>(.*?)</dt><dd>.*?</dd>", keep, dl)
    if "ramp" not in low:  # a clause no card uses goes too (a review: the ramp window on a sheet with none)
        out = out.replace("; a ramp: 8 to 30 s ahead", "")
    return out


def _unnest(text: str) -> str:
    """A bracket inside a bracket, a clause: "(only 22% ... (99 kills going), about 3:49" -> "...; 99 kills going, ..."."""
    out, depth = [], 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            if depth:  # an inner bracket: its content as a clause
                j = text.find(")", i)
                if j > 0 and "(" not in text[i + 1:j]:
                    if out and out[-1] == " ":
                        out.pop()
                    out.append("; " + text[i + 1:j])
                    i = j + 1
                    continue
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        out.append(ch)
        i += 1
    return "".join(out)


def _src_chip(x: str) -> str:
    """A source as a chip: what, then its kill count; the qualifiers on hover (they add, never answer)."""
    what, _, rest = x.partition(": ")
    shown = rest.partition(" (")[0]  # one form on every sheet: its count, the bracket on hover (heal round 10: a
    more = f" title='{e(rest)}'" if shown != rest else ""  # 90-character cut read one chip two ways)
    return f"<span class='src'{more}><b>{e(what[:1].upper() + what[1:])}</b> {e(shown)}</span>"


def _tidy(html: str) -> str:
    """Two brackets in a row on a chip, one: "(99 kills going) (29% of its users)" -> "(99 kills going; 29% ...)"."""
    html = re.sub(r"\((\d+ kills going)\) \(([^()]*)\)", r"(\1; \2)", html)
    # "back from cooldown" on a chip: the glyph the legend defines (a review: said twice in one chip, 16 sheets)
    html = re.sub(r" ?(?:&middot;|,) back from cooldown for about half", " &middot; &#10226;&nbsp;about half", html)
    return re.sub(r" ?(?:&middot;|,) back from cooldown", "&nbsp;&middot;&nbsp;&#10226;", html)  # never alone on a line


def cooldowns_html(cds: list[Cooldown], answered: set | None = None, named: dict | None = None,
                   moved: dict | None = None) -> str:
    return _tidy(_cooldowns_html(cds, answered, named, moved))


def rare_html(cds: list[Cooldown], answered: set | None = None, named: dict | None = None) -> str:
    """The buttons fewer than half of the top players press: rows like the others, muted, with a "< half" badge
    (heal round 10: Time Dilation at 50% a row, at 48% a sentence on the next boss's sheet)."""
    return "".join(r.replace("<li>", "<li class='rare'>", 1).replace("</b>", "<span class='half'>&lt; half</span></b>", 1)
                   for c in sorted(cds, key=lambda c: -c.users)
                   for r in [cooldowns_html([c], answered, named)])


def _cooldowns_html(cds: list[Cooldown], answered: set | None = None, named: dict | None = None,
                    moved: dict | None = None) -> str:
    """The cooldown rows. answered: the (button, time) pairs the lead ties to a hit; a chip says its hit only for
    those, so no chip reads as an answer the lead and the chart do not give (Apotheosis "1 s before the 0:35 hit")."""
    def tie(c: Cooldown, t: float, n: str) -> str:
        return n if answered is None or (c.name, t) in answered else ""
    return "".join(
        f"<li><b>{_ic(c)}{e(_shown(c.name))}</b><small>pressed by {c.users:.0%} of the top players &middot; {count(c.per_kill)} a kill"
        + (f", {_pct(c.on_others)} of the presses on another player" if 0 <= c.on_others < 0.95 else
           ", all on another player" if c.on_others >= 0.95 else "") + "</small>"
        "<span class='when'>" + ("".join(f"<span class='chip'>{_chip((moved or {}).get((c.name, t), _named_at(c, t, named, sp)), tie(c, t, n))}"
                                        + ("" if _window_said(c, t, n, tie(c, t, n), named, sp) else
                                           _split(_named(c, t, named, tie(c, t, n), sp))[0]
                                           + _also_pressers(c, t, named, tie(c, t, n), sp))

                                        + (f" &middot; back from cooldown{' for about half' if t in c.back_half else ''}"
                                           + _lead_back(c, t)
                                           if t in c.back and not (c.why or c.every)  # its line says it; its
                                           and "back from cooldown" not in _named(c, t, named, tie(c, t, n), sp)
                                           else "")  # window's reading alone, as an "or" time's (round 78)
                                        + _split(_named(c, t, named, tie(c, t, n), sp))[1]  # each time its own
                                        + _or_then_untied(c, t, n, tie(c, t, n), answered, named, moved)
                                        + "</span>"  # window, then the "or" (r. 68)
                                        for k, (t, n, sp) in enumerate(zip(c.times, c.near,
                                                                           c.support or [0.0] * len(c.times),
                                                                           strict=False)))
                                or ("" if any(k[0] == c.name and isinstance(k[1], tuple) for k in (named or {}))
                                    else "<span class='vary'>no shared time</span>"))  # a badge where the chips go
        # (none when a window chip follows: heal round 12, Spirit Link Totem's 2:13 under "no shared time"),
        # a named line may follow (round 91; heal round 10: "timing varies: no shared moment" three times a sheet)
        + _pull_chip(c)
        + "".join(f"<span class='chip'>about {v[1] if isinstance(v[1], str) else _mmss(v[1])} &middot; in the "
                  f"window of the {_mmss(k[1][1])} hit: {_pct(v[0])}{v[2]}"
                  f"{' &middot; ' + v[3] if len(v) > 3 and v[3] and not (c.every and v[3] == 'on cooldown') else ''}</span>"  # a chip of its own, led by its time
                  # (round 91: plain text after a chip read as that chip's continuation)
                  for k, v in (named or {}).items()
                  if k[0] == c.name and isinstance(k[1], tuple))
        + ("<small class='alt'>two rhythms, by their first press: " + "; or ".join(
            f"from {_mmss((moved or {}).get((c.name, ts[0]), ts[0]))}, then "
            f"{_and([_mmss((moved or {}).get((c.name, t), t)) for t in ts[1:]])}" for _sp, ts in c.rhythms)
           + "</small>"
           if c.rhythms else "")
        + (f"<small class='alt'>on cooldown, about every {c.every:.0f} s"  # its other presses said too (round 109:
           + (f"; {_more(c, named)} more on that cadence" if c.times and _more(c, named) else "")  # Stasis "3 a
           + "</small>" if c.every and not _held(c) else  # kill", two chips)
           # a held habit kept (only one for a hit is): the cadence is the other group's (round 79: Avenging Wrath
           # "on cooldown" beside 26% holding it for 0:35, whose later presses vary)
           f"<small class='alt'>on cooldown from {_mmss(c.times[0])}, about every {c.every:.0f} s; those pressing it "
           f"at {_and([_mmss((moved or {}).get((c.name, a), a)) for a in _held(c)])} instead press it again at varying "
           "times</small>" if c.every else
           f"<small class='alt'>{_more(c, named)} more at varying times</small>" if c.times and _more(c, named) else
           f"<small class='alt'>the other {_pct(_rest(c, named))} at varying times{_twice(c, named)}</small>"
           if (c.times or any(k[0] == c.name and isinstance(k[1], tuple) for k in (named or {})))  # a card with
           and _rest(c, named) >= 0.15  # only a window line too (round 110: Spirit Link Totem's other 76% unsaid)
           else "")
        + _released(c)
        + (f"<small class='alt'>{'mostly ' if c.why.startswith('cast on another') and 0 <= c.on_others < 0.95 else ''}"
           f"{e(c.why)}: not tied to a hit"
           + ("; its players' times differ, so more times than presses" if c.why == MINUTE  # (round 89: 6 chips for
              and len(c.times) > round(c.per_kill) else "")  # Nature's Swiftness "4 a kill")
           + "</small>" if c.why and c.times else "")
        + ("<small class='alt'>its players' times differ, so more times than presses</small>"  # any button (round
           if not c.why and len(c.times) > round(c.per_kill) else "")  # 109: Tranquility "2 a kill", three chips)
        + "</span></li>"
        for c in cds)


def _named_at(c: Cooldown, t: float, named: dict | None, sp: float) -> float:
    """A chip's time: a press the lead names for a hit kept for none, its window counting the same share as its
    moment, is shown at the lead's time (its counted presses'), said once."""
    hit = (named or {}).get((c.name, t))
    if hit is None or hit_share(c, t, hit) is None:
        return t
    inside = _counted(c, t, hit)  # its window's time whenever its window's share is said (heal round 12: "3:43 ·
    return _center(inside) if inside else t  # in the window of the 3:35 hit: 34%, about 3:35", two times)


def _named(c: Cooldown, t: float, named: dict | None, n: str, sp: float) -> str:
    """A chip's share: of the hit's window when the lead names this press for a hit kept for none, said so, as the
    lead's count (round 50: "1:11 · 70%" under a lead saying 61% in the 1:15 window); else _tied_share's."""
    hit = (named or {}).get((c.name, t))
    if hit is not None and (hs := hit_share(c, t, hit)) is not None:
        where = "ahead of" if c.ramp and t < hit - ANSWER[0] else "in the window of"  # a ramp: around its own time
        b = None if c.why == MINUTE else _back_in(c, t, hit)  # its own reading (round 63); a minute button's
        # reason is the lead's, not "back from cooldown" (round 64: Convoke)
        tag = ("" if b is None or b <= BACK_SHARE[0] else ", back from cooldown"
               + (" for about half" if b <= BACK_SHARE[1] else ""))
        if _pct(hs) == _pct(sp):  # one count: said once, at the lead's time, the chip's own (round 78: "2:59 ·
            # 2:57", two times); under a quarter, of those who press it too (round 84); its offset from the hit, as
            # every other chip (heal round 10: "in the window of the 2:55 moment: the same 15%")
            return (_offset(_named_at(c, t, named, sp), _mmss(hit)) + _base(c, hs, hit) + _pressers(c, sp, t)
                    + tag)
        return (f"{_share(sp)}{_still(c, t, sp)} &middot; {where} the {_mmss(hit)} hit:{_base(c, hs, hit).replace(' &middot;', '')}"
                + tag)  # the chip's time is the window's (_named_at): one time a chip (heal round 12)
    if n and (hs := hit_share(c, t, _secs(n.partition(" ")[0]))) is not None:  # tied: its hit's count, its base
        return _base(c, hs, _secs(n.partition(" ")[0]))
    return _share(sp) + _still(c, t, sp)


def _still(c: Cooldown, t: float, sp: float | None = None) -> str:
    """A time's share past the first kill's end is of the kills still going then, said (round 98) when it reads
    otherwise than over every kill (round 99: "in the 99 kills still going" beside every late chip)."""
    n = sum(1 for d in c.lasts if d >= t) if c.lasts else 0
    if not c.lasts or not 0 < n < len(c.lasts):
        return ""
    if sp is not None and _pct(sp) == _pct(sp * n / len(c.lasts)):
        return ""
    return f" ({n} kills going)"


def _pull_chip(c: Cooldown) -> str:
    """The pull group the lead names for a first press ("23% open with it at the pull"), on its card too (rounds 54,
    60: the lead quoted a group no chip showed), when no moment of the card is already at the pull."""
    # a press the card does not show already (not Ascendance's 0:05 beside its 0:35 and 3:45, 2 a kill): _pull_t
    t = _pull_t(c)
    if t is None:
        return ""
    first = [ts[0] for ts in c.presses if ts and ts[0] <= PULL]
    return (f"<span class='chip'>{_mmss(t)} &middot; {_pct(len(first) / c.n_all)} of the top "
            "players, at the pull</span>")


def _pull_t(c: Cooldown) -> float | None:
    """The pull group's time when its card shows it (_pull_chip), else None: the chart draws it too (round 99: Divine
    Hymn's 0:05 group named in the lead, on its card, and missing from the chart)."""
    if (not c.presses or not c.n_all or any(x <= PULL for x in [*c.times, *c.alt]) or round(c.per_kill) > 2
            or round(c.per_kill) - len(c.times) <= 0):
        return None
    first = [ts[0] for ts in c.presses if ts and ts[0] <= PULL]
    return st.median(first) if len(first) >= 0.2 * c.n_all else None


def _groups(xs: list[float]) -> list[list[float]]:
    """Presses counted in a window: one group, or two when a gap of GROUP_GAP s or more splits them and each side
    holds GROUP_SHARE of them (Disc's Evangelism ahead of Vashnik's 2:10: 1:41 and 2:01, a median 1:48 nobody
    presses at; round 77)."""
    xs = sorted(xs)
    if len(xs) < 4:
        return [xs]
    k = max(range(1, len(xs)), key=lambda i: xs[i] - xs[i - 1])
    if ((xs[k] - xs[k - 1] >= GROUP_GAP and min(k, len(xs) - k) >= GROUP_SHARE * len(xs))
            or (xs[k] - xs[k - 1] >= 0.6 * GROUP_GAP and min(k, len(xs) - k) >= 0.4 * len(xs))):  # two balanced groups
        # 6 s apart too (round 105: Rewind at 1:10-1:14 and 1:20-1:23, 26 and 21 presses, said "1:14")
        return [xs[:k], xs[k:]]
    return [xs]


def _about(xs: list[float]) -> str:
    """The time of the presses counted: their median, each group's ("1:41 or 2:01"), or the span of their middle
    half when it is wide (Disc's Evangelism ahead of Vashnik's 2:10, spread from 1:40 to 2:01: "1:43 to 1:58")."""
    gs = _groups(xs)
    if len(gs) == 1 and len(xs) >= 4:
        q = st.quantiles(xs, n=4)
        if q[2] - q[0] >= SPREAD and _mmss(q[0]) != _mmss(q[2]):
            return f"{_mmss(q[0])} to {_mmss(q[2])}"
    return " or ".join(_mmss(st.median(g)) for g in gs)


def _center(xs: list[float]) -> float:
    """Where a chart mark goes: the median of the larger group of the presses counted."""
    return st.median(max(_groups(xs), key=len))


def _tw(c: Cooldown, t: float, hit: float) -> str:
    """A tied press's time: its counted presses' median, as the share's (round 63: "about 1:11" for presses at
    1:13), else its moment's."""
    inside = _counted(c, t, hit) if c.presses else []
    return _about(inside) if inside else _mmss(t)


STORE, RELEASE = " (Store)", " (Release)"  # a two-step button's two casts in the logs (Stasis)
STORED = 3  # the spells a store holds: "your next 3 helpful spells" (Stasis' tooltip)
STORED_SHARE = 0.25  # a spell said as stored when a quarter of the stores hold it (Hover, 4-10%, a move between)


def two_step(tl, cds: list[Cooldown], found: list[Moment]) -> None:
    """A button pressed in two steps (Stasis: "(Store)", then "(Release)", which casts what it stored): its release
    moments and shares, read as a cooldown's (window, kills still going), and how long after the store; what it
    stores: stored_spells."""
    from paf.healroles import press_moments

    for c in cds:
        if not c.name.endswith(STORE):
            continue
        rel = {a.id for a in tl.abilities if a.name == c.name[:-len(STORE)] + RELEASE}
        store = {a.id for a in tl.abilities if a.name == c.name}
        if not rel:
            continue
        per = [sorted(t for i in rel for t in (p["casts"].get(i) or [])) for p in tl.players]
        lasts = [p.get("duration") or tl.duration for p in tl.players]
        presses = [ts for ts in per if ts]
        if not presses:
            continue
        k = max(1, round(st.median(len(ts) for ts in presses)))
        times, _alt, _of = press_moments(presses, k, tl.duration)
        n_all = max(1, len(tl.players))
        support = [sum(1 for ts in presses if any(abs(x - t) <= 8 for x in ts)) / n_all for t in times]
        keep = [i for i, sp in enumerate(support) if sp >= 0.25 * len(presses) / n_all]
        r = Cooldown(c.name[:-len(STORE)] + " release", min(rel),  # its chart lane's name
                     len(presses) / n_all, st.median(len(ts) for ts in presses),
                     [times[i] for i in keep], support=[support[i] for i in keep], presses=presses, n_all=n_all,
                     lasts=lasts, press_lasts=[d for ts, d in zip(per, lasts, strict=False) if ts])
        r.near = [next((_mmss(m.t) for m in found if -ANSWER[0] <= t - m.t <= ANSWER[1]), "") for t in r.times]
        r.alt_of = [next((m.t for m in found if -ANSWER[0] <= t - m.t <= ANSWER[1]), -1.0) for t in r.times]  # its hit
        # each store paired with its own release, before the next store (round 83: a store never released was
        # paired with the next one's, ~100 s later: 19 s for 18); each release keeps its store's gap, for a hit's
        pairs, unreleased, stores, fates = [], 0, 0, []
        for p in tl.players:
            st_ts = sorted(t for i in store for t in (p["casts"].get(i) or []))
            rl_ts = sorted(t for i in rel for t in (p["casts"].get(i) or []))
            for j, t in enumerate(st_ts):
                stores += 1
                nxt = st_ts[j + 1] if j + 1 < len(st_ts) else float("inf")
                u = next((u for u in rl_ts if t < u <= nxt), None)
                fates.append((t, u))
                if u is None:
                    unreleased += 1
                else:
                    pairs.append((u, u - t))
        # the chart's release marks: one per store chip, as the card's release chips (round 96: the 1:41 store's
        # "1:50 to 2:04 · 54%", the largest, had no mark; the marks came from the releases' own clusters)
        groups = sorted([*c.times, *c.alt])
        marks = []
        for g in groups:
            us = [u for s_, u in fates if u is not None and abs(s_ - g) <= 8
                  and min(groups, key=lambda x, s_=s_: abs(x - s_)) == g]
            if us:
                marks.append((st.median(us), len(us) / n_all))
                r.shown_at[st.median(us)] = _about(us)  # its hover as its chip (round 114: "1:55" vs "1:50 to 2:04")
        if marks:
            r.times, r.support = [t for t, _sp in marks], [sp for _t, sp in marks]
            r.near = [next((_mmss(m.t) for m in found if -ANSWER[0] <= t - m.t <= ANSWER[1]), "") for t in r.times]
            r.alt_of = [next((m.t for m in found if -ANSWER[0] <= t - m.t <= ANSWER[1]), -1.0) for t in r.times]
        c.release, c.release_gap = r, (st.median(g for _u, g in pairs) if pairs else 0.0)
        c.release_pairs, c.unreleased, c.fates = pairs, (unreleased / stores if stores else 0.0), fates
        c.hits = [m.t for m in found]


def stored_spells(con, encounter_id: int, difficulty: int, store: str) -> list[tuple[str, float, float]]:
    """The spells a two-step button's store holds: the first STORED cast after each store by the ranked player of
    each timed kill, from every cast of the log (the timeline keeps its cooldowns only: Temporal Anomaly missing,
    Naturalize in its place). (spell, share of the stores holding it, share holding it twice), from a quarter."""
    rows = con.execute(
        "SELECT p.report, p.fight_id, a.name, p.t FROM player_cast p JOIN fight f USING(report, fight_id) "
        "JOIN ranked r ON r.report = p.report AND r.fight_id = p.fight_id AND r.actor_id = p.actor_id "
        "LEFT JOIN ability a ON a.id = p.ability_id WHERE f.encounter_id = ? AND f.difficulty = ? "
        "AND f.status = 'done' AND p.type = 'cast' ORDER BY p.report, p.fight_id, p.t",
        (encounter_id, difficulty)).fetchall()
    base = store[:-len(STORE)]
    skip = {store, base, base + RELEASE}
    kills: dict[tuple, list] = {}
    for rep, fid, name, _t in rows:
        kills.setdefault((rep, fid), []).append(name or "")
    held: dict[str, int] = {}
    twice: dict[str, int] = {}
    n = 0
    for names in kills.values():
        for j, name in enumerate(names):
            if name != store:
                continue
            n += 1
            nxt = [x for x in names[j + 1:] if x not in skip][:STORED]
            for x in set(nxt) - {""}:
                held[x] = held.get(x, 0) + 1
                twice[x] = twice.get(x, 0) + (nxt.count(x) > 1)
    return sorted(((x, v / n, twice[x] / n) for x, v in held.items() if v / n >= STORED_SHARE),
                  key=lambda y: (-y[1], -y[2], y[0]))


def _gap_of(c: Cooldown, inside: list[float]) -> float:
    """The median store-to-release gap of the releases counted in a window."""
    got = set(inside)
    gaps = [g for u, g in c.release_pairs if u in got]
    return st.median(gaps) if gaps else 0.0


def _released(c: Cooldown) -> str:
    """A two-step button's release and what it holds, on its card (Stasis: the store's chips above)."""
    r = c.release
    if r is None:
        return ""
    # one release chip per store chip, from that store's own releases (round 88: "2:13 · 37% · from the 1:57 store"
    # mixed the 1:57 group with a third of the 1:41 one, whose own release, about 1:54, had no chip); stores far
    # from every chip said apart
    groups = sorted([*c.times, *c.alt])
    by: dict[float, list] = {g: [] for g in groups}
    other: list = []
    for st_t, u in c.fates:
        g = min(groups, key=lambda x: abs(x - st_t), default=None)
        (by[g] if g is not None and abs(g - st_t) <= 8 else other).append((st_t, u))
    n = max(1, c.n_all or len(c.presses))

    def chip(g: float, fs: list) -> str:
        us = [u for _s, u in fs if u is not None]
        if not us:
            return ""
        gap = st.median(u - s_ for s_, u in fs if u is not None)
        never = 1 - len(us) / len(fs)
        # the hit its releases land in most, said when a tenth of the top players release there (round 95: the
        # 1:41 store's "1:50 to 2:04" gave 13% of the 2:10 hit's 35% with no word)
        def inwin(m: float) -> int:
            return sum(1 for u in us if m - ANSWER[0] <= u <= m + ANSWER[1])
        h = max(c.hits, key=inwin, default=None)
        win = ""
        any_chip = h is not None and (x := hit_share(r, h, h)) is not None and x >= 0.1 and bool(_counted(r, h, h))
        if h is not None and inwin(h) / reach(r, h) >= 0.1 and not any_chip:  # the any-store chip says that hit
            # (a review: "of them, 16%" beside "any store -> 0:35 hit 17%", two shares for one moment)
            at = st.median(us)  # the chip's own time outside the window: those who release there said apart (round
            out = "" if h - ANSWER[0] <= at <= h + ANSWER[1] else (" release it later," if at < h else  # 99: "1:50 to
                                                                    " release it earlier,")  # 2:04" read in 2:10)
            win = (f" &middot; of them, {_pct(inwin(h) / reach(r, h))}{_reach_note(r, h)} in the "
                   f"window of the {_mmss(h)} hit" if out else  # a part of this chip's releases, not more of them
                   # (round 108: "52% … 16% release it later" read as 68% of a 70% store)
                   f" &middot; in the window of the {_mmss(h)} hit: {_pct(inwin(h) / reach(r, h))}"
                   f"{_reach_note(r, h)}")
        return (f"<span class='chip'>{_about(us)} &middot; {_pct(len(us) / n)} &middot; from the "
                f"{_mmss(g)} store, each a median {gap:.0f} s after its own"
                + (f" ({_pct(never)} of those stores never released)" if never >= 0.05 else " (nearly all released)")
                + win + "</span>")
    chips = "".join(chip(g, by[g]) for g in groups)
    # each hit the lead answers with the release: its count of any store, as the lead says it (round 97: the lead's
    # 51% and 13 s found nowhere on the card, its chips 40% and 15 s from one store)
    for h in c.hits:
        hs = hit_share(r, h, h)
        inside = _counted(r, h, h)
        if hs is not None and hs >= 0.1 and inside:  # from a tenth, as the chips (round 99: 19% in 0:40 unsaid)
            chips += (f"<span class='chip any'>any store &rarr; {_mmss(h)} hit &middot; {_pct(hs)}"  # a chip, as the
                      f"{_reach_note(r, h)}"                                                   # stores' (less text)
                      + (f" &middot; held {gap:.0f} s" if (gap := _gap_of(c, inside)) else "") + "</span>")
    rest = [u for _s, u in other if u is not None]
    if chips and rest:
        chips += (f"<small class='alt'>and about {len(rest) / n:.1f} more releases a kill, of stores made at other "
                  "times</small>")  # releases, not players: a player may have several (round 88: "94% release")
    gap = "" if chips else f", a median {c.release_gap:.0f} s after its store" if c.release_gap else ""
    never = f"; {_pct(c.unreleased)} of the stores are never released" if c.unreleased >= 0.05 else ""
    out = (f"<span class='subrow'><small class='alt'>released:</small>{chips}</span>" if chips else  # each
           # chip says its stores' share never released
           f"<small class='alt'>released{gap} at varying times{never}</small>")  # as chips, as the store's (r. 83)
    if c.stored:
        out += (f"<span class='subrow'><small class='alt'>stored (first {STORED} casts):</small>" + "".join(
            f"<span class='chip'>{e(nm)} &middot; {_pct(sh)}" + (f" &middot; twice {_pct(tw)}" if tw >= 0.1 else "")
            + "</span>" for nm, sh, tw in c.stored) + "</span>")  # chips, as the releases (heal round 10: prose)
    return out


def _held(c: Cooldown) -> list[float]:
    """A button on cooldown's habits held for a hit (Avenging Wrath at 0:35, the rest from the pull)."""
    return [a for a, n in zip(c.alt, c.alt_near or [""] * len(c.alt), strict=False) if n]


def _step_name(name: str) -> str:
    """A two-step button's mark as its lane and cards say it: "Stasis store", not "Stasis (Store)"."""
    return name.replace(" (Store)", " store").replace(" (Release)", " release")


def _mark_reason(c: Cooldown, t: float, found: list | None) -> str:
    """An outline's hover: why it is no answer; a store whose release answers a hit says that alone (heal confirm
    round 5: "tied to no hit: its release goes on the 2:10 hit")."""
    why = _why_not(c, t, found)
    return f" ({why[2:]})" if why.startswith(": its release goes on") else f" (tied to no hit{why})"


def _why_not(c: Cooldown, t: float, found: list | None = None) -> str:
    """An untied mark's reason on hover, as its card gives it (round 75: an outline on a hit's dot read "tied to no
    hit" with no word why); every outline gives one (round 93: four said none). The pull's first press: "at the pull",
    never "on cooldown" (round 92); a store whose release the lead keeps for a hit says so, and a group of a button on
    cooldown that holds it past its cooldown is held, not on cooldown (round 93: Stasis 1:57)."""
    def hit_near(x: float):
        return next((m for m in found or [] if -ANSWER[0] <= x - m.t <= ANSWER[1]), None)
    hit_t = c.window_of.get(t)
    if hit_t is None and t in c.windowed and (m := hit_near(t)) is not None:
        hit_t = m.t
    if hit_t is not None:  # the table's own words for it, first (heal confirm rounds 4-7: "about every minute",
        b = None if c.why == MINUTE else _back_in(c, t, hit_t)  # "back from cooldown" alone; the chip's own
        back = ("" if b is None or b <= BACK_SHARE[0] else ", back from cooldown"  # reading of it, its words)
                + (" for about half" if b <= BACK_SHARE[1] else ""))
        where = "ahead of" if c.ramp and t < hit_t - ANSWER[0] else "in the window of"
        return f": {where} the {_mmss(hit_t)} hit{back}: not kept for it"
    if c.why:
        return f": {c.why}"
    if t <= PULL:
        return ": at the pull"
    if c.fates:  # a two-step button's store: where its release lands
        us = [u for s_, u in c.fates if u is not None and abs(s_ - t) <= 8]
        m = hit_near(st.median(us)) if us else None
        if m is not None:
            return f": its release goes on the {_mmss(m.t)} hit"
        if us:  # a release on no hit: where it lands, as the others' (round 114: the 1:41 store "on cooldown")
            nx = next((m for m in found or [] if 0 < m.t - ANSWER[0] - st.median(us) <= RAMP[1]), None)
            return (f": its release, about {_about(us)}, "
                    + (f"mostly before the {_mmss(nx.t)} hit's window" if nx is not None else "lands on no hit"))
    if c.every:  # its card's word first: "on cooldown" (round 94: Avenging Wrath 2:05 read "back from cooldown")
        return ": held past its cooldown" if t in c.alt and t not in c.back else ": on cooldown"
    if t in c.back:  # in a hit's window: the window first, as the table says it (heal confirm round 5)
        m = hit_near(t)
        half = " for about half" if t in c.back_half else ""
        return (f": in the window of the {_mmss(m.t)} hit, back from cooldown{half}: not kept for it" if m is not None
                else f": back from cooldown{half}")
    m = hit_near(t)
    if m is not None:  # the chips' words and separator (heal confirm round 7)
        return f": in the window of the {_mmss(m.t)} hit: not kept for it"
    m = next((m for m in found or [] if 0 < m.t - ANSWER[0] - t <= RAMP[1]), None)  # just ahead of a hit (round 97:
    mostly = m is not None and c.presses and any(m.t - ANSWER[0] <= x <= m.t + ANSWER[1] for ts in c.presses
                                                 for x in ts if abs(x - t) <= 15)  # some of its presses in it
    return (f": {'mostly ' if mostly else ''}before the {_mmss(m.t)} hit's window" if m is not None  # Stasis
            else ": away from the big hits")                             # hit's window, read "away")


def _split(chip: str) -> tuple[str, str]:
    """A named chip's own share, and its hit's window clause, said after its "or" times."""
    for mark in (" &middot; in the window of", " &middot; ahead of"):
        if mark in chip:
            i = chip.index(mark)
            return chip[:i], chip[i:]
    return chip, ""


def _base(c: Cooldown, hs: float, hit: float) -> str:
    """A hit's share on a chip, of what the lead counts it of: "33% of the 58 kills still going" when a late hit's
    kills are fewer (round 53: "33% of the top players" read as 33 of 100, for 19 of 58)."""
    n = reach(c, hit)
    of = f" ({n} kills going)" if c.lasts and n < len(c.lasts) else ""  # a share of players, the legend says
    return f" &middot; {_pct(hs)}{of}"


def _tied_share(c: Cooldown, t: float, n: str, sp: float) -> float:
    """A chip's share: in its hit's answer window when the lead ties it to the hit (hit_share), so the chip and the
    lead give one number; else the moment's own."""
    hs = hit_share(c, t, _secs(n.partition(" ")[0])) if n else None
    return sp if hs is None else hs


def _near(n: str) -> str:
    """ "0:35 Possession Barrage" -> " · Possession Barrage": the moment a press answers ("0:35" alone: the 0:35 hit,
    no boss cast to name it)."""
    if not n:
        return ""
    t = n.partition(" ")[0]  # the moment is named once, in its row: the chip says which one
    return f" &middot; the {e(t)} hit"


def _chip(t: float, n: str) -> str:
    """A press's time and the hit it answers, said as before, at or after it ("1:11 · just before the 1:15 hit")."""
    if not n:
        return _mmss(t)
    return _mmss(t) + _offset(t, n.partition(" ")[0])


def _offset(t: float, hit: str) -> str:
    """A press's offset from a hit's start ("3 s before the 1:15 hit"), from the seconds shown, rounded as they are
    (round 87: "0:40 · 1 s before the 0:40 hit" after the times were rounded and the gap not)."""
    m, _, sec = hit.partition(":")
    gap = int(round(t)) - (int(m) * 60 + int(sec))
    # one form, from its start: "4 s into" its 5 s window read as past it
    return (" &middot; on the hit" if gap == 0 else
            f" &middot; {-gap} s before the {e(hit)} hit" if gap < 0 else
            f" &middot; {gap} s after the {e(hit)} hit starts")


SHOWN_TALENTS = 60  # every class and spec difference shown (a hero tree is named, not listed): no "+N more"


def build_rows(builds: list, split: list | None = None) -> list[tuple[int, str, str, str]]:
    """(players, label, import string, what sets it apart from the most played build) of the top builds; the most
    played build says its side of each talent the top players split on (paf.healer.contested), so its row is no
    bare name."""
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
            out.append((b.count, b.label, b.code or "", _sides(b.key, names, split or []) if names else ""))
            continue
        mine, base = hero(b.key), hero(builds[0].key)
        other = mine and base and mine != base  # another hero tree: named, its own talents not listed one by one
        plus = sorted({names[t] for t in b.key - builds[0].key if names.get(t) and not (other and t in heroes)})
        minus = sorted({names[t] for t in builds[0].key - b.key if names.get(t) and not (other and t in heroes)})

        def few(xs: list[str]) -> str:  # another hero tree changes twenty talents: the first ones say enough
            return ", ".join(xs[:SHOWN_TALENTS]) + (f" (+{len(xs) - SHOWN_TALENTS} more)" if len(xs) > SHOWN_TALENTS
                                                    else "")
        diff = "; ".join(x for x in (f"the {mine} hero tree instead of {base}" if other else "",
                                     f"takes {few(plus)}" if plus else "", f"skips {few(minus)}" if minus else "") if x)
        diff = (f"differs from the most played: {diff}" if diff else "") + (
            f"{'; ' if diff else ''}{_sides(b.key, names, split or [])}" if split else "")
        out.append((b.count, b.label, b.code or "", diff))
    return out


def _sides(key, names: dict, split: list) -> str:
    """The build's side of each talent the top players split on: "of the talents they split on, takes Lightburst
    and Weal and Woe; skips Searing Light"."""
    mine = {names[t] for t in key if names.get(t)}
    takes, skips = [], []
    for n, sh in split:
        sides = [x.rpartition(" ")[0] for x in n.split(" / ")] if sh < 0 else [n]
        got = [x for x in sides if x in mine]
        if got:
            takes += got
        elif sh >= 0:
            skips.append(n)
    if not takes and not skips:
        return ""
    return "of the talents listed below, " + "; ".join(
        x for x in (f"takes {_and(takes)}" if takes else "", f"skips {_and(skips)}" if skips else "") if x)


UNSIMMED = {"change": "What the top players play"}  # no sim to say what to change: the tab says what it holds
BUILD_SHARE = 0.10  # a build fewer of the players read play is no shared build: not listed, nothing to copy


def talents_html(builds: list, players: int, who: str, hero: list | None = None) -> str:
    """The hero tree the top players pick (the first choice), then their builds played by enough of them."""
    line = ""
    if hero:
        line = (f"<p><b>Hero tree:</b> {e(hero[0][0])} (all {players} players read).</p>" if len(hero) == 1 else
                "<ul class='hl2 split'>" + _pair(" / ".join(f"{t} {round(sh * 100)}%" for t, sh in hero[:2]))  # the
                .replace("<li class='pair'><span>", "<li class='pair hero'><span><small>Hero tree</small> ", 1)  # choice
                + "</ul>")  # rows' stacked bar (heal round 16: plain text), with no half tick (round 17)
    if builds and builds[0][0] < BUILD_SHARE * players:  # 3 of 100 is no build to show, empty row and all
        return f"<h2>Talents the top {e(who)} play</h2>{line}" if line else ""  # the lead said there is no build
    return (f"<h2>Talents the top {e(who)} play</h2>{line}<ul class='hl2'>"
            f"{builds_html(shown_builds(builds, players)) or '<li>No build yet.</li>'}</ul>")


def shown_builds(builds: list, players: int) -> list:
    """The builds enough of the players read play (BUILD_SHARE): each one is shown and can be copied."""
    return [b for b in builds if not players or b[0] >= BUILD_SHARE * players]


def builds_html(builds: list) -> str:
    copy = "<button class='btn ghost copy' data-copy='{}'>Copy its import string</button>"
    # ranked by how many play it, never "top build A" (read as "the best"): a count, not a pick
    rank = ("The most played build", "The second most played", "The third most played")
    return "".join(f"<li><b>{rank[i] if i < len(rank) else e(b[1])}</b> "
                   f"<small>{b[0]} of the top players"
                   + (f" &middot; {e(b[3])}" if len(b) > 3 and b[3] else "") + "</small>"
                   + (copy.format(e(b[2])) if b[2] else "<small class='muted'>no import string in their logs</small>")
                   + "</li>" for i, b in enumerate(builds))


def _bar(share: float) -> str:
    """A share as a small bar with a tick at half (the owner: a number a bar says better)."""
    return f"<span class='sbar' aria-hidden='true'><span style='width:{round(max(0.0, min(1.0, share)) * 100)}%'></span></span>"


def _pic(icons: dict | None, name: str) -> str:
    from paf.icons import img

    got = (icons or {}).get(name, "")  # Wowhead's "?" for a spell it does not know: no icon (heal round 16:
    return img(got, "small", "ics", "") if got and "questionmark" not in got else ""  # Fearless)


def trinkets_html(trinkets: list[tuple[str, int, float]], icons: dict | None = None) -> str:
    return "".join(f"<li><a href='https://www.wowhead.com/item={i}' target='_blank' rel='noopener'>{_pic(icons, n)}"
                   f"{e(n)}</a>{_bar(s)}<small>{s:.0%}</small></li>" for n, i, s in trinkets)  # the heading says "equip"


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
<section class="hp-sec"><h2>Trinkets the top healers equip</h2><ul class="hl2">{trk or '<li>No gear yet.</li>'}</ul></section>
{f'<section class="hp-sec"><h2>What the Encounter Journal asks healers</h2><ul class="hl2">{jr}</ul></section>' if jr else ''}
<section class="hp-sec"><h2>The numbers</h2><p>SimulationCraft does not sim healing well: for the value of a talent or an
item for your healing, use <a href="{QE_LIVE}" target="_blank" rel="noopener">QE Live</a>.</p></section>"""
    return page(f"{h.boss} prep", body)


# --- the sheet in the four sections of every role's sheet (issue #27) ----------------------------------------------

def _pct(v: float) -> str:
    return f"{int(v * 100 + 0.5)}%"  # half up: 21/40 and 15/40 read 53% and 38%, not 52% and 38%


def contested(con, encounter_id: int, difficulty: int, spec: str, lo: float = 0.35, hi: float = 0.65,
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
        rest = 1 - sum(x for _n, x in sides)  # a choice node left empty, said (round 84: Bloodborne 48% /
        none = f" ({rest:.0%} take neither)" if len(sides) > 1 and round(rest * 100) >= 1 else ""  # Sudden Death 43%)
        split.append((" / ".join(f"{n} {s:.0%}" for n, s in sides) + none if len(sides) > 1 else sides[0][0],
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


def _and(items: list[str], word: str = "and") -> str:
    """'a', 'a and b', 'a, b and c'."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {word} " + items[-1] if items else ""


SPLIT = (0.15, 0.85)  # a talent taken by this share of the top players or between: they split on it


def _many(split: list, wide: bool = True) -> str:
    """Their builds' differences in words: one split talent is said as the only one (round 29: "the closest to 50/50
    being Move with Grace" read as if a list were cut)."""
    if len(split) == 1:
        lo, hi = SPLIT if wide else (0.35, 0.65)  # paf.healer.contested's default band, else the wide one
        return (f"their builds differ by many small choices, each taken by under {lo:.0%} or over "
                f"{hi:.0%} of them, except {e(split[0][0])}")
    def said(n: str) -> str:  # a choice node is one choice: "the choice of Wild Charge or Tiger Dash", never
        if " / " not in n:     # joined to the list's "and" (round 87: "Rake and Wild Charge 61% / Tiger Dash 39%")
            return n
        sides = [re.sub(r" [0-9]+%.*$", "", x) for x in n.split(" / ")]
        return "the choice of " + " or ".join(sides)
    def off(n: str, s: float) -> int:  # how far from half, in points: a pair by its first side ("A 61% / B 39%")
        m = re.search(r"([0-9]+)%", n) if s < 0 else None
        return round(abs((int(m.group(1)) / 100 if m else s) - 0.5) * 100)
    k = 4  # a tie at the cut named too (round 114: Oppressing Roar 30% left out beside Scarlet Adaptation 30%)
    while k < len(split) and off(*split[k]) == off(*split[3]):
        k += 1
    return (f"their builds differ by many small choices, {'the most split' if wide else 'the closest to 50/50'} "
            "being " + e(_and([said(n) for n, _s in split[:k]])))  # none near 50/50 in the wide list (round 44)


def build_lead(builds: list, spec: str, players: int, split: list | None = None, wide: bool = True) -> str:
    """The change tab's answer: the most played build when the top players agree on one; when their builds are
    scattered, the talents they split on (the rest they agree on)."""
    shown = shown_builds(builds, players)  # the sentence counts the builds the list shows
    if not shown:  # no shared build: still an answer, the talents they split on
        most = builds[0][0] if builds else 0
        return (f"<p class='lead'>No build is shared among the top {e(spec)}s; none is played by more than {most} of the "
                f"{players} players read"
                + (": they split on the talents listed below" if split else "") + f".{NOT_ADVICE}</p>")
    builds = shown
    top = builds[0]
    total = sum(b[0] for b in builds)
    if split and top[0] < players / 5:  # no build a fifth of them play: the answer is in the split talents
        return (f"<p class='lead'>The most played build, below, is played by only {top[0]} of the {players} top "
                f"{e(spec)}s read: "
                + "they split on the talents listed below" + f".{NOT_ADVICE}</p>")
    return (f"<p class='lead'>The most played build of the top {e(spec)}s"
            + ("" if len(builds) == 1 else f", {e(top[1])},") + f" is played by {top[0]} of the "
            f"{players} players read" + (f"; the {len(builds)} builds below cover {total} of them, the other "
                                        f"{players - total} play builds of their own" if len(builds) > 1 else "")
            + f".{NOT_ADVICE}</p>")


NOT_ADVICE = " Their choices, not simmed."


def _side(x: str) -> str:
    """One side of a talent choice: its name in bold, its share and any note muted ("Sudden Death 38% (3% take
    neither)": split at its last space, the note read as part of the name; round 94)."""
    m = re.match(r"^(.*?) ([0-9]+%)( \(.*\))?$", x)
    if not m:
        return f"<b>{e(x)}</b>"
    return f"<b>{e(m.group(1))}</b> <small>{m.group(2)}{e(m.group(3) or '')}</small>"


def split_html(split: list, players: int, spec: str, wide: bool = False, icons: dict | None = None) -> str:
    """The talents the top players split on, with how often each is picked: what the builds above hide. wide: none
    or one is taken by 35 to 65% of them (Holy Paladin, Holy Priest), so the talents they differ on most, 15 to 85%."""
    return ((f"<h2>The talents the top {e(spec)}s differ on most</h2><p>{(f'Only {e(near[0])} splits' if (near := [n for n, x in split if 0.35 <= x <= 0.65]) else 'No talent splits')} "
             f"them near half; {'the others listed are' if near else 'these are'} the ones 15 to 85% of the "
             f"{players} players read take, closest to half first:</p>" if wide else
             f"<h2>The talents the top {e(spec)}s split on</h2><p>The share of the {players} players read "
             "who take each, closest to half first:</p>") + "<ul class='hl2 split'>"
            + "".join(f"<li><b>{_pic(icons, n)}{e(n)}</b>{_bar(s)}<small>{s:.0%}</small></li>" if s >= 0 else _pair(n, icons)
                      for n, s in split) + "</ul>")


def _pair(n: str, icons: dict | None = None) -> str:
    """A choice node's row: both names, one stacked bar (each side's share, the rest taking neither), as the other
    rows (heal round 11: no bar, a lone "/" in the bar column)."""
    sides = [re.match(r"^(.*?) ([0-9]+)%", x) for x in n.split(" / ")]
    if not all(sides):
        return "<li>" + " / ".join(_side(x) for x in n.split(" / ")) + "</li>"
    neither = re.search(r"\(([0-9]+)% take neither\)", n)
    names = " <small>or</small> ".join(f"<b>{_pic(icons, m.group(1))}{e(m.group(1))}</b>" for m in sides)
    bar = "".join(f"<span class='p{i}' style='width:{int(m.group(2))}%'></span>" for i, m in enumerate(sides))
    nums = " / ".join(f"{m.group(2)}%" for m in sides) + (f" &middot; {neither.group(1)}% neither" if neither else "")
    return f"<li class='pair'><span>{names}</span><span class='sbar pair' aria-hidden='true'>{bar}</span><small>{nums}</small></li>"


def journal_lead(lines: list[str], who: str) -> str:
    """The boss tab's answer: the abilities the Encounter Journal asks this role to handle."""
    names = list(dict.fromkeys(re.findall(r"\[([^\]]+)\]", " ".join(lines))))
    if not names and lines:  # the journal's notes without spell links: said as they are, just below
        return (f"<p class='lead'>The Encounter Journal has {len(lines)} notes for {who} on this boss, just below; "
                f"every ability follows; another role's own abilities are only named.</p>")
    if not names:
        return f"<p class='lead'>The Encounter Journal asks {who} nothing in particular on this boss.</p>"
    return (f"<p class='lead'>What the Encounter Journal asks {who} to handle here: {e(', '.join(names[:5]))}. Every "
            f"ability follows; another role's own abilities are only named.</p>")


def roles_table(roles: list, mine: str = "") -> str:
    """Every healer spec's numbers side by side, one row a spec (the cards read as runs of seven numbers that could
    not be compared)."""
    if not roles:
        return ""
    buffs = any(r.buffs > 0 for r in roles)
    few = "<small>too few here</small>"  # a spec read in the pool, too rare in this sheet's kills for its casts
    head = ("<th>Healer</th><th>Healing share</th><th>On tanks</th>"
            "<th>In spikes</th>"  # the legend's "A spike" says how much of the fight (heal round 16: 5 lines)
            "<th>Overheal</th><th>Dispels a minute</th><th>Externals given a kill <small>(every player)</small></th>"
            + ("<th>Buffs given a kill</th>" if buffs else "")
            + "<th>Players</th>")
    rows = "".join(
        f"<tr class='{'mine' if r.spec == mine else ''}'><td>{_spec_ic(r.spec)}{e(r.spec)}{' <small>(you)</small>' if r.spec == mine else ''}"
        f"{' <small>few players</small>' if r.players < 100 else ''}"
        f"</td><td class='n'>{_pct(r.healing)}</td><td class='n'>{_pct(r.tank)}</td><td class='n'>{_pct(r.spike)}</td>"
        f"<td class='n'>{_pct(r.overheal)}</td><td class='n'>{r.dispels:.1f}</td>"
        f"<td class='n'>{few if r.externals < 0 else f'{r.externals:.1f}' if r.externals >= 0.05 else '<small>none</small>'}</td>"
        + (f"<td class='n'>{few if r.buffs < 0 else f'{r.buffs:.1f} <small>{e(_and(r.buff_spells))}</small>' if r.buffs else '<small>none</small>'}</td>"
           if buffs else "")
        + f"<td class='n'>{r.players}</td></tr>" for r in roles)
    return f"<table class='hcomp'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"  # each kill's ranked
    # player left out (paf.healroles.pooled_kills): no row is high by design any more (round 30)


def _unread(name: str) -> bool:
    """A button the other healers' lines leave out: one back every minute, or a two-step button's store, which heals
    nothing (round 84: "Stasis 2:11 · 14%" counted stores, the Evoker's sheet the releases)."""
    return _minute(name) or name.endswith(STORE)


def _minute(name: str) -> bool:
    """A button back every minute or sooner by the game data (Nature's Swiftness, 60 s): never tied to a hit, on the
    other healers' lines as on the fight tab."""
    try:
        from paf.gamedata import same_name_spells, spell_cooldowns

        cds = spell_cooldowns()
        best = max((cds.get(i, (0.0, 1))[0] for i in same_name_spells().get(_shown(name), [])), default=0.0)
        return 0 < best <= 60
    except Exception:  # noqa: BLE001 - offline
        return False


def _in_hit(n: str, ts: list, rest: list, h: float, bar: bool = True, back_ok: bool = False,
            ramps: bool = True) -> tuple | None:
    """(button, time, share) of a spec's healers pressing it in a hit's answer window, as the fight tab counts a tied
    press: over the window, not within 8 s of a moment's peak (the Evokers' Rewind for Nek'zali's 1:15: 26% in the
    window, 20% around its 1:13 peak, so "none shared"; round 40). Kept when a quarter of those who press it are
    there and fewer than BACK_SHARE[0] of those presses come as soon as it is back; without the presses, the moments."""
    if len(rest) < 2:  # no presses carried: its moments
        return next(((n, t, sp) for t, sp, back in ts if -ANSWER[0] <= t - h <= ANSWER[1] and not back), None)
    ps, total, cd, *sid = rest[1]
    ramp = ramps and bool(sid) and _ramp_kind(sid[0])  # a ramp lands its hit 8 to 30 s ahead, as the fight tab
    a, b = (h - RAMP[1], h - RAMP[0]) if ramp else (h - ANSWER[0], h + ANSWER[1])  # (Disc's Evangelism: round 44)
    if ramp:  # the pull's opener is no ramp for the first hit (Evangelism 0:00-0:09 read "0:08 (a ramp)" for 0:35)
        a = max(a, PULL)
    inside = [(x, max((y for y in p if y < x), default=None)) for p in ps for x in p if a <= x <= b]
    players = sum(1 for p in ps if any(a <= x <= b for x in p))
    if not total or not players or (bar and players < 0.25 * len(ps)):
        return None
    back = sum(1 for x, y in inside if y is not None and cd and x - y <= cd + BACK) / max(1, len(inside))
    if back > BACK_SHARE[0] and not back_ok:
        return None
    return n, st.median(x for x, _y in inside), players / total, players / max(1, len(ps)), ramp


def roles_more(roles: list, mine: str = "", found: list | None = None, staged: bool = False,
               icons: dict | None = None) -> str:
    """Under the table, what a number cannot say: what each other healer spec presses on each big hit (found), the
    same answer rule as the fight tab's (from 5 s before to 8 s after; a press back from cooldown is no answer); every
    spec and every hit said, "none" too (round 30: specs and hits left out without a word)."""
    from paf.icons import img

    hits = sorted(m.t for m in found or [])
    out = ""
    for r in roles:
        if r.spec == mine:
            continue
        if getattr(r, "raid_cds", 0) < 0:  # read in the pool only: too few of its healers in this sheet's kills for their casts
            out += (f"<tr><td class='who'><b>{_spec_ic(r.spec)}{e(r.spec)}</b><small>{getattr(r, 'own_players', 0)} healers</small></td>"
                    f"<td colspan='{len(hits)}' class='muted'>too few in these kills to read its casts</td></tr>")
            continue
        # a ramp as the fight tab reads one: its players press it 8 to 30 s ahead of two hits at least (a quarter
        # of those who press it each time), not every spell its game data could make one (round 85: Tip the Scales
        # "3:14 (a ramp)" for Vashnik's 3:35, never one on the Evoker's own sheet)
        ramp_of = {n: sum(1 for h in hits if (g := _in_hit(n, ts, rest, h, back_ok=True)) and len(g) > 4 and g[4]) >= 2
                   for n, _k, ts, *rest in r.cd_names}
        per_hit = []
        for h in hits:
            got = [(*g[:3], g[4] if len(g) > 4 else False, g[3] if len(g) > 4 else g[2])
                   for n, _k, ts, *rest in r.cd_names if not _unread(n)
                   for g in [_in_hit(n, ts, rest, h, ramps=ramp_of[n])] if g]
            under = [] if got else sorted((g for n, _k, ts, *rest in r.cd_names if not _unread(n)  # none at the bar:
                                           for g in [_in_hit(n, ts, rest, h, bar=False, ramps=ramp_of[n])] if g and g[2] >= 0.1),
                                          key=lambda x: -x[2])[:1]  # its most pressed, said so (round 41: "none
            held = [] if got or under else sorted(  # none held for it: its presses there come back from cooldown,
                (g for n, _k, ts, *rest in r.cd_names if not _unread(n)  # said, not "none shared" (round 69:
                 for g in [_in_hit(n, ts, rest, h, bar=False, back_ok=True, ramps=ramp_of[n])] if g and g[2] >= 0.1),  # Conduit 25%)
                key=lambda x: -x[2])[:1]
            under = under or [("back", *g) for g in held]
            per_hit.append((h, sorted(got, key=lambda x: -x[2])[:2], under))  # shared" read as "nothing pressed")
        def cell(got: list, under: list) -> str:
            """One spec's answer to one hit: its buttons (icon, time, share), else its most pressed under a quarter
            (faded), else none held (back from cooldown), else none shared; the legend says each."""
            def btn(n: str, t: float, rp: bool) -> str:
                ic = img((icons or {}).get(_shown(n), ""), "small", "ics", "")
                return f"{ic}<b>{e(_shown(n))}</b> {_mmss(t)}{' <small>(a ramp)</small>' if rp else ''}"
            if got:
                return "<br>".join(f"{btn(n, t, rp)} &middot; {_pct(sp)}"
                                   + (f" <small>({_pct(pp)} of its users)</small>" if _pct(pp) != _pct(sp) else "")  # the
                                   # fight tab's form: "/" also joins a choice node's names (heal round 11)
                                   for n, t, sp, rp, pp in got)  # all its healers / its users (the legend)
            low = [u for u in under if len(u) > 4 and u[0] != "back"]
            if low:
                n, t, sp, pp = low[0][:4]
                return (f"<span class='under'>{btn(n, t, low[0][4])} &middot; {_pct(sp)}"
                        + (f" <small>({int(pp * 100)}% of its users)</small>" if f"{int(pp * 100)}%" != _pct(sp)
                           else "") + "</span>")
            back = [u for u in under if u[0] == "back"]
            if back:
                u = back[0]
                return (f"<span class='held'>&#10226; none held</span> <small>{e(_shown(u[1]))} {_mmss(u[2])} &middot; "
                        f"{_pct(u[3])}"
                        + (f" ({int(u[4] * 100)}% of its users)" if len(u) > 5 and f"{int(u[4] * 100)}%" != _pct(u[3])
                           else "")  # as every cell (heal round 13)
                        + f"{' (a ramp)' if len(u) > 5 and u[5] else ''}</small>")
            return "<span class='muted'>&mdash; none shared</span>"
        n = getattr(r, "own_players", 0)  # under 100: a few players' habit, said (Disc: 43; round 46)
        out += (f"<tr><td class='who'><b>{_spec_ic(r.spec)}{e(r.spec)}</b>"
                + (f"<small>{n} healers{', few players' if n < 100 else ''}</small>" if n else "") + "</td>"
                + "".join(f"<td>{cell(got, under)}</td>" for _h, got, under in per_hit) + "</tr>")
    if not out:
        return ""
    left = list(dict.fromkeys(n for r in roles if r.spec != mine for n, *_x in getattr(r, "cd_names", [])
                              if n.endswith(STORE)))
    head = "".join(f"<th>{_mmss(h)} hit</th>" for h in hits)
    return ("<h2>The other healers' cooldowns on the big hits</h2>"
            f"<table class='others'><thead><tr><th>Healer</th>{head}</tr></thead><tbody>{out}</tbody></table>"
            "<dl class='legend'><dt>Read on</dt><dd>the table's kills"
            + (" whose stage starts are read (presses in stage time, as the curve)" if staged else "")
            + ", every player of each spec; that spec's own sheet reads its top players, so it can differ.</dd>"
            "<dt>A button</dt><dd>a quarter of the spec's healers who press it do so in the hit's window (5 s before "
            "to 8 s after; a ramp: 8 to 30 s ahead, never the opener before 0:12); its share: of all that spec's healers "
            "(and of those who press the button, when it differs).</dd><dt>Faded</dt><dd>under a quarter: its most pressed button, when "
            "a tenth of the spec's healers press it there.</dd><dt>&#10226; none held</dt><dd>its presses there come "
            "back from cooldown (over 40% of them): no answer, as on the fight tab.</dd><dt>&mdash; none shared</dt>"
            "<dd>no button reaches a tenth.</dd><dt>Few players</dt><dd>under 100 of the spec's healers in these "
            "kills: a habit of a few.</dd>"
            + "".join(f"<dt>{e(_shown(n))}</dt><dd>left out: its store heals nothing; its release is read for the top "
                      "players of its spec only (their own sheet).</dd>" for n in left)
            + "</dl>")


def _job(r) -> str:
    """A spec's healing job of this boss, or "": not "nothing stands out", nor Power Infusion given on every boss."""
    return next((j for j in r.jobs if not j.startswith(("nothing stands out", "buffs a damage dealer"))), "")


def _pace(h) -> str:
    """The comparison's kills against the timings' ones, said from the numbers (kills ranked by a healer's healing
    were said slower: on four sheets they were not)."""
    if not h.role_median or not h.duration or abs(h.role_median - h.duration) < 10:  # under 10 s: noise
        return ""
    return (f" {'Slower' if h.role_median > h.duration else 'Faster'} than the {h.kills} top kills "
            f"({_mmss(h.duration)}).")  # their own median just said (heal round 16: 4:35 twice in a sentence)


def jobs_lead(roles: list, mine: str = "") -> str:
    """The deeper tab's answer: your spec's job first, then the other healer specs whose job stands out. When every
    job found is one the top players do not keep, that is the answer, the averages in a small line (round 41: 110
    words in the lead's type to take each job back)."""
    found = [(r.spec, _job(r)) for r in roles if _job(r)]
    by = {r.spec: r for r in roles}

    def table(sp: str, j: str) -> str:  # the table's own number beside the means (round 78: 1.4, 1.0 and the
        r = by[sp]                       # table's 1.2 for one Holy Priest dispel rate, left to the reader)
        key = "dispels" if j.startswith("dispels") else "tank" if "tanks" in j else "spike" if "spikes" in j else ""
        x = getattr(r, key, None) if key else None
        v = "" if x is None else f"{x:.1f}" if key == "dispels" else _pct(x)
        return f" (the table's median {sp}: {v})" if v else ""
    if found and all("only on average" in j for _s, j in found):
        rows = ""
        for sp, j in found:
            m = re.match(r"(heals the tanks|answers the raid's damage spikes|dispels) more, but only on average: "
                         r"([\d.]+%?) .*?against ([\d.]+%?) for the other healers of the same kills \((\d+) kills\)"
                         r"; among the top players ranked by their healing [^:]*: the median top .*? ([\d.]+%?), the "
                         r"other specs' ([\d.]+%?)", j)
            if not m:  # an unknown form: the sentence as it is
                rows += f"<tr><td><b>{_spec_ic(sp)}{e(sp)}</b></td><td colspan='3'>{e(j)}</td></tr>"
                continue
            what, a_, b_, n, ta, tb = m.groups()
            rows += (f"<tr><td><b>{_spec_ic(sp)}{e(sp)}</b></td><td>{e(what)} more</td><td><b>{a_}</b> vs {b_} <small>({n} kills"
                     f"{e(table(sp, j)).replace(' (the table', '; the table').rstrip(')')})</small></td>"
                     f"<td><b>{ta}</b> vs {tb}</td><td class='no'>&#10007; not kept</td></tr>")
        return ("<p class='lead'>No healer spec has a job of its own here that the top players keep.</p>"
                "<table class='jobs fit'><thead><tr><th>Healer</th><th>On average</th><th>Every healer <small>(spec "
                "vs the others, paired within each kill)</small></th><th>Top players <small>(ranked ones)</small>"
                f"</th><th>A job?</th></tr></thead><tbody>{rows}</tbody></table>")
    you = next((r for r in roles if r.spec == mine), None)
    head = ""
    if you:
        head = (f"Your spec here: the {you.spec} {_job(you)}. " if _job(you) else
                "Your spec here: nothing stands out against the other healers of the same kills. ")
    lines = [f"the {r.spec} {_job(r)}" for r in roles if r.spec != mine and _job(r)]
    # a job's numbers are kill by kill, the table's the median player: said, so they read as two views (round 30)
    how = (" A job is read kill by kill, against the other healers of that kill; the table below shows each spec's "
           "median player, so its numbers differ.") if lines or (you and _job(you)) else ""
    if not lines:
        rest = "No other healer spec stands out either." if not you or not _job(you) else "No other healer spec stands out."
        return f"<p class='lead'>{e(head)}{rest}{e(how)}</p>"
    return f"<p class='lead'>{e(head)}The others: " + "; ".join(e(x) for x in lines) + f".{e(how)}</p>"


def nums_note(roles: list, own: str = "") -> str:
    """What the table's numbers are, said once above it in plain words, the method in a second, smaller line (the
    round-29 review: one 90-word block of statistics)."""
    cover = next((r.spike_cover for r in roles if getattr(r, "spike_cover", 0)), 0.0)
    spikes = f" ({_pct(cover)} of the fight)" if cover else ""
    # one term a line, the method folded into them (the owner: less text)
    plain = [("A row", "the spec's median player in these kills: every healer of it but each kill's ranked one."),
             ("A job", "a fifth more than the other healers of the same kills, beyond chance (paired within each "
                       "kill, Benjamini-Hochberg at 5%); with two bosses read, maybe a habit of the spec."),
             ("A spike", f"5 s at 1.5&times; the kill's median damage{spikes}, kill by kill; every spec heals more in "
                         "them, a higher share means harder in spikes."),
             ("The shares", "from different kills: they do not add up."),
             ("Externals, buffs", "a mean over every player of the spec, cast on others only."),
             ("Dispels", "the boss tab counts the top player only.")]
    return "<dl class='legend'>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in plain) + "</dl>"


def _plain(text: str) -> str:
    """A journal line without its spell brackets: "[Soulcoil Well]" -> "Soulcoil Well"."""
    return re.sub(r"[\[\]]", "", text)


WIDE_KILLS = 30  # a spec in fewer kills: its with/without numbers swing wide, said on its row (round 46)
FEW_KILLS = 15  # a spec in fewer of the kills read: its numbers say little (Vengeance, 10 kills: "0.0 deaths")


def presence_table(pres: list, mine: str = "", what: str = "Healer") -> str:
    """Each spec of a role in the top kills: how often it is brought, and the kills with it against without it."""
    if not pres:
        return "<p class='small muted'>Not enough kills read yet.</p>"
    deaths = any(p.deaths_with is not None for p in pres)

    def dd(a, b) -> str:  # deaths are read on fewer kills: too few of them with this spec is said, not left blank
        return ("<small>deaths read on too few kills</small>" if a is None else
                f"{a:.1f}" + (" <small>(too few without)</small>" if b is None else f" <small>({b:.1f} without)</small>"))
    rows = ""
    for p in pres:
        if p.spec == mine and p.share >= 0.99:  # the corpus is this spec's kills: its row says nothing
            continue
        few = p.kills < FEW_KILLS
        # the kills without it are held to the same threshold as the kills with it (10 kills read "too few" in one
        # row and gave a median in the next)
        without = round(p.kills / p.share) - p.kills if p.share else 0
        few_without = without < FEW_KILLS
        cells = ("<td class='n' colspan='3'><small>too few kills</small></td>" if few else
                 f"<td class='n'>{p.per_kill:.1f}</td><td class='n'>{_mmss(p.duration_with)}"
                 + (" <small>(too few without)</small>" if few_without or p.duration_without is None
                    else f" <small>({_mmss(p.duration_without)} without"
                    + ("" if p.duration_close or p.kills < WIDE_KILLS else ", beyond the noise") + ")</small>")
                 + "</td>" + (f"<td class='n'>{dd(p.deaths_with, None if few_without else p.deaths_without)}"
                              + (" <small>(these deaths: beyond the noise)</small>" if not p.deaths_close and p.deaths_with is not None
                                 and p.kills >= WIDE_KILLS  # a wide reading is never marked (round 51: 21 kills)
                                 and not few_without else "") + "</td>" if deaths else ""))
        if few and not deaths:
            cells = "<td class='n' colspan='2'><small>too few kills</small></td>"
        rows += (f"<tr class='{'mine ' if p.spec == mine else ''}{'few' if few else ''}'><td>{_spec_ic(p.spec)}{e(p.spec)}</td>"
                 f"<td class='n'>{_pct(p.share)} <small>({p.kills} kill{'s' if p.kills != 1 else ''}"
                 f"{', a wide reading' if FEW_KILLS <= p.kills < WIDE_KILLS else ''})</small></td>"
                 f"{cells}</tr>")
    head = (f"<th>{what}</th><th>Top kills with one</th><th>Per kill</th><th>Median kill</th>"
            + ("<th>Deaths per 20 players</th>" if deaths else ""))
    marked = "beyond the noise" in rows
    wide = any(FEW_KILLS <= p.kills < WIDE_KILLS for p in pres)  # never tested: not said within the noise
    noise = (f"<p>With or without any {e(what.lower())} spec{f' in {WIDE_KILLS} kills or more' if wide else ''} "
             "here, kill time and deaths stay within the noise.</p>")
    return ((noise if not marked else "")
            + f"<table class='hcomp'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
            "<dl class='legend'>" + ("<dt>Marked</dt><dd>a gap with and without the spec beyond three standard "
            "errors (clear with every number tested at once): a reading of these kills, not a reason to bring it."
            "</dd>" if marked else "") + "<dt>Deaths</dt><dd>per 20 players (heroic raids are 10 to 30), a mean over the kills whose deaths are "
            f"read.</dd><dt>A wide reading</dt><dd>{FEW_KILLS} to {WIDE_KILLS - 1} kills: never marked.</dd>"
            f"<dt>Too few kills</dt><dd>under {FEW_KILLS}: no number.</dd></dl>")  # every term (round 86; less text)


def comps_table(comps: list, n_kills: int) -> str:
    if not comps or all(c.kills < FEW_KILLS for c in comps):  # no composition played enough: no table to read
        return ""
    deaths = any(c.deaths is not None for c in comps)
    comps = [c for c in comps if c.kills >= FEW_KILLS]  # the same cut as every other table
    rows = "".join(
        f"<tr><td>{_comp_label(c)}</td><td class='n'>{_pct(c.share)} <small>({c.kills} kills)</small></td><td class='n'>{_mmss(c.duration)}</td>"
        + (f"<td class='n'>{'' if c.deaths is None else f'{c.deaths:.1f}' if c.kills >= FEW_KILLS else '<small>too few kills</small>'}</td>"
           if deaths else "") + "</tr>"
        for c in comps)
    return ("<table class='hcomp'><thead><tr><th>Healers</th><th>Top kills</th><th>Median kill</th>"
            + ("<th>Deaths per 20 players</th>" if deaths else "") + f"</tr></thead><tbody>{rows}</tbody></table>"
            f"<p class='small muted'>Of {n_kills} top kills read. Exact compositions played at least {FEW_KILLS} times; the "
            f"other {n_kills - sum(c.kills for c in comps)} kills play rarer ones."
            + ("" if deaths else  # the deaths read: the legend above says it (heal round 10: said twice)
               f" Deaths: too few of these kills had them read (shown from {FEW_KILLS}).") + "</p>")


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
    # a utility button (Divine Steed, Mass Dispel, Ring of Peace): one line at the end, never a healing cooldown
    utility = [c for c in [*h.cooldowns, *h.rare] if c not in items and _utility(c.spell_id)]
    own = [c for c in own if c not in utility]
    heals = [c for c in own if not is_defensive(c.spell_id, c.name) and c not in items]
    defs = [c for c in own if c not in heals and c not in items]
    lead, lead_names, answered, rel_marks = "", [], set(), []
    named: dict = {}  # the press the lead names for each hit kept for none: its chip counts that window too
    moved: dict = {}  # a tied press whose counted presses sit 5 s or more from its moment: drawn and said there
    bare_said: dict = {}  # each hit no cooldown is kept for: its row's words (what is pressed in its window)
    if h.moments:  # the highest, in time order (round 100: the first three in time kept Stage Two's 3:50, 1.42x, and
        shown = sorted(sorted(h.moments, key=lambda m: -m.ratio)[:LEAD_HITS], key=lambda m: m.t)  # lost its 4:15)
        ratios = (f"{'both' if len(shown) == 2 else 'each'} {_x(shown[0].ratio)}&times;"
                  if len({_x(m.ratio) for m in shown}) == 1 and len(shown) > 1
                  else _and([f"{_x(m.ratio)}&times;" for m in shown]))
        groups: dict[str, list[Moment]] = {}  # moments of the same ability said together (Vashnik's "mixed
        for m in shown:                       # damage, most from..." three times in one sentence)
            groups.setdefault(m.boss_spell, []).append(m)
        sep = "; " if any(len(ms) > 1 for ms in groups.values()) else None  # "0:40 (A); 2:10 and 3:35 (each time B)"
        hits = (sep.join if sep else _and)([f"{_and([_mmss(m.t) for m in ms])}"
                     + (f" ({'each time ' if len(ms) > 1 else ''}{e(name)})" if name else "") for name, ms in groups.items()])
        hits += f": {ratios} the usual damage"
        rule = ""
        if any(m.ratio < SPIKE for m in shown):  # said, not left to a reader of the 1.5x rule (round 29)
            rule = (" (none reaches 1.5&times;: the 3 highest waves)"  # the rule moments() applied, not the rounded
                    if max(m.ratio for m in h.moments) < SPIKE else  # figures (1.45 shows 1.5)
                    f" (big from {_x(max(SPIKE * 0.9, RELATIVE * max(m.ratio for m in h.moments)))}&times; here: "
                    "0.85 of the highest)")  # the bar applied (round 101: 1.35x said, 1.42x applied)
        # a cooldown said for a hit only when the top players' usual press answers it (paf.healer.ANSWER), at the
        # press's own time
        bare = []
        by_name: dict[str, list] = {}  # a button answering several hits is one clause
        for m in shown:
            mine_here = [(c, t, sp, press) for c in heals if not _external(c.spell_id)  # a buff on one player: no answer
                         for t, n, sp, press in [
                             *zip(c.times, c.near, c.support or [0.0] * len(c.times), c.times, strict=False),
                             *zip(c.alt, c.alt_near or [""] * len(c.alt), c.alt_support or [0.0] * len(c.alt),
                                  c.alt_of or c.alt, strict=False)]
                         if n and n.split(" ", 1)[0] == _mmss(m.t)]  # the main moment or another habit of its press
            if not mine_here:
                bare.append(_mmss(m.t))
            for c, t, sp, press in mine_here[:3]:
                hs = hit_share(c, t, m.t)  # counted in the hit's window, as the chip of a tied press says
                by_name.setdefault(c.name, []).append((m.t, t, sp if hs is None else hs, press, c))

        # one cooldown per hit, the one most of them press then; a second as common within the noise (Avenging
        # Wrath 36%, Aura Mastery 35% on Vashnik's 0:40 hit) is named with it; the other habits are on the rows below
        tops: dict[float, list] = {}
        for n, hs in by_name.items():
            for hit, t, sp, press, c in hs:
                tops.setdefault(hit, []).append((n, t, sp, press, c))
        n_read = max(1, h.kills)
        for hit, xs in tops.items():  # a ramp's time ahead of the hit first when as many press it (Evangelism
            xs.sort(key=lambda x: (-x[2], not (x[4].ramp and hit - x[1] >= RAMP[0])))  # 1:42 over 2:07, 36% both
            def noise(p: float, q: float = xs[0][2]) -> float:  # the gap's standard error, both shares' (round 34:
                return ((q * (1 - q) + p * (1 - p)) / n_read) ** 0.5  # Apotheosis 29% hid Divine Hymn 27%)
            # two buttons, never one twice (Evangelism at 2:07 and its 1:42 habit: one press, its most pressed time)
            tops[hit] = [x for i, x in enumerate(xs) if x[2] >= xs[0][2] - noise(x[2])
                         and x[0] not in {y[0] for y in xs[:i]}][:2]
        lead_names = list(dict.fromkeys(x[0] for xs in tops.values() for x in xs))
        for hit_t, xs in tops.items():  # the button kept for each hit, for a chip not kept at a quarter or more (round
            named[(KEPT, hit_t)] = (_shown(xs[0][0]), xs[0][2])  # 95: Conduit 25% "not kept" read as the rule broken)
        answered = {(x[0], x[1]) for xs in tops.values() for x in xs}  # what the chart draws full
        for hit_t, xs in tops.items():  # a tied press drawn and said at its counted presses' time when its moment is
            for x in xs:                # 5 s or more off (round 64: Divine Hymn "0:47" for presses at 0:41)
                inside = _counted(x[4], x[1], hit_t) if x[4].presses else []
                if inside and _mmss(st.median(inside)) != _mmss(x[1]):  # any shown difference (round 65: 0:42
                    moved[(x[0], x[1])] = _center(inside)                   # in the lead, 0:44 on the chip)
        # one press answering either of two hits (Aura Mastery at 0:36 for some, 1:19 for others) is said once
        by_press: dict[tuple, list] = {}
        for hit, xs in sorted(tops.items()):
            if len(xs) == 1:
                by_press.setdefault((xs[0][0], xs[0][3]), []).append((hit, *xs[0][1:3], xs[0][4]))
            else:
                by_press[(hit,)] = xs

        # one button for two hits with no player in both: one press, "their X goes on A or B" (round 93: Aura
        # Mastery "28% for 0:35 … 30% for 1:15" read as two presses of a 3-minute button nobody pressed twice)
        singles: dict[str, list] = {}
        for k, ps in by_press.items():
            if len(k) == 2 and len(ps) == 1:
                singles.setdefault(k[0], []).append(k)
        for _n, ks in singles.items():
            if len(ks) != 2:
                continue
            (h1, t1, _s1, c1), (h2, t2, _s2, _c2) = by_press[ks[0]][0], by_press[ks[1]][0]
            w1, w2 = _window(c1, t1, h1), _window(c1, t2, h2)
            both = sum(1 for ts in c1.presses if any(w1[0] <= x <= w1[1] for x in ts)
                       and any(w2[0] <= x <= w2[1] for x in ts))
            if both:
                continue
            by_press[ks[0]] = by_press[ks[0]] + by_press.pop(ks[1])

        def _other_players(n: str, hit: float, t: float, c) -> bool:
            """The same button said for an earlier hit by other players, none in both windows: "another" (round 93:
            Aura Mastery for 0:35 and 1:15 read as two presses nobody made)."""
            w = _window(c, t, hit)
            for xs in by_press.values():
                for x in xs:
                    if len(x) == 5:
                        n2, t2, _sp2, _p2, c2 = x
                        h2 = next((h for h, ys in tops.items() if x in ys), None)
                    else:
                        h2, t2, _sp2, c2 = x
                        n2 = c2.name
                    if n2 != n or h2 is None or h2 >= hit:
                        continue
                    w2 = _window(c, t2, h2)
                    if not any(any(w[0] <= y <= w[1] for y in ts) and any(w2[0] <= y <= w2[1] for y in ts)
                               for ts in c.presses):
                        return True
            return False

        def which(n: str, press: float, c) -> str:
            """Which press of the kill: "their first Divine Hymn" (2 a kill), "their Rewind" (one)."""
            k = sorted(c.times).index(press) if press in c.times else 0
            nth = ("first", "second", "third", "fourth")[k] if round(c.per_kill) > 1 and k < 4 else ""
            return f"their {nth + ' ' if nth else ''}{e(_shown(n))}"

        def ramp_of(c, t: float, hit: float) -> str:  # Evangelism 16 s ahead: the ramp is the answer
            return ", a ramp ahead of it" if c.ramp and hit - t >= RAMP[0] else ""

        def _other(ps: list) -> str:
            """A ramp played by one of two rhythms: the other said, so the ramp does not read as everyone's (Disc's
            Evangelism on Vashnik: a third ramps at 0:23 and 2:01, a third presses it from the pull; round 33)."""
            c = ps[0][3]
            ramp_ts = {round(t) for _h, t, _sp, _c in ps}
            rest = [(sp, ts) for sp, ts in c.rhythms if not ramp_ts & {round(t) for t in ts}]
            return "".join(f"; another {_pct(sp)} press it from the pull on its cooldown, about "
                           f"{_and([_mmss(t) for t in ts])}" if ts and ts[0] <= 10 else
                           f"; another {_pct(sp)} press it about {_and([_mmss(t) for t in ts])}" for sp, ts in rest[:1])

        def clause(key: tuple, ps: list) -> tuple[float, str]:
            if len(key) == 1:  # two cooldowns as common for one hit
                return key[0], (f"for the {_mmss(key[0])} hit, " + _and(
                    [f"{_pct(sp)} press {e(_shown(n))}{_reach_note(c, key[0])} (about {_tw(c, t, key[0])}"
                     f"{ramp_of(c, t, key[0])}"
                     f"{_also(c, p, t, sp, key[0]).replace('; another', ', another')})" for n, t, sp, p, c in ps]))
            n, press = key
            if len(ps) == 1:
                hit, t, sp, c = ps[0]
                return hit, (f"for the {_mmss(hit)} hit, {'another ' if _other_players(n, hit, t, c) else ''}"
                             f"{_pct(sp)} press {e(_shown(n))}{_reach_note(c, hit)} (about {_tw(c, t, hit)}"
                             f"{_kept_by_time(c, t, hit, sp)}{ramp_of(c, t, hit)})" + (_other([(hit, t, sp, c)]) if ramp_of(c, t, hit) else
                                                         _also(c, press, t, sp, hit)))
            c0 = ps[0][3]
            first = which(n, press, c0).startswith("their first") or round(c0.per_kill) <= 1
            pull = (sum(1 for ts in c0.presses if ts and ts[0] <= PULL) / c0.n_all) if first and c0.n_all else 0.0
            return ps[0][0], (f"{which(n, press, c0)} goes on " + _and(  # the most shared hit first
                [f"the {_mmss(hit)} hit ({_pct(sp)}, about {_tw(c_, t, hit)})"
                 for hit, t, sp, c_ in sorted(ps, key=lambda p: -p[2])], "or")
                + (f"; {_pct(pull)} open with it at the pull" if pull >= 0.2 and _pull_t(c0) is not None  # its card
                   else ""))  # shows it too (round 102: said, on no card); round 53: 22% Hymns

        def _also(c, press: float, t: float, sp: float, hit: float) -> str:
            """Another habit of the same press about as shared, tied to no hit: said, or the lead hides a third of
            them (Avenging Wrath "33% about 0:44", another 33% at 0:23; round 41)."""
            alts = [(a, x) for a, x, of in zip(c.alt, c.alt_support or [], c.alt_of or c.alt, strict=False)
                    if of == press and a != t and x >= 0.8 * sp
                    and (c.name, a) not in answered]  # one tied to another hit is said there (round 75)
            if not alts:
                return ""
            a, x = max(alts, key=lambda y: y[1])
            other = next((m2 for m2 in shown if m2.t != hit and -ANSWER[0] <= a - m2.t <= ANSWER[1]), None)
            if other is not None:  # in another hit's window: that hit's row and the button's own chip say it (heal
                return ""  # round 10: Conduit's 3:52 on the 4:15 row, "not kept for it: Revival is", said twice)
            gap = int(abs(_secs(_mmss(hit)) - _secs(_mmss(a))))  # from the hit, as the times shown (round 45)
            out = not (c.ramp or -ANSWER[0] <= a - hit <= ANSWER[1])  # outside its window: no answer, said so (round
            return (f"; another {_pct(x)} press it about {_mmss(a)}, {gap} s {'before' if a < hit else 'after'} the "  # 61)
                    "hit" + (", outside its window" if out else ""))
        # a ramp button answering several hits is one clause (Evangelism thrice in a row read as a list)
        ramps: dict[str, list] = {}
        for k, ps in by_press.items():
            if len(k) == 2 and len(ps) == 1 and ps[0][3].ramp and ps[0][0] - ps[0][1] >= RAMP[0]:
                ramps.setdefault(k[0], []).append((k, ps[0]))
        ramps = {n: sorted(kps, key=lambda x: x[1]) for n, kps in ramps.items() if len(kps) > 1}
        merged = {k for kps in ramps.values() for k, _p in kps}
        ramps = {n: [p for _k, p in kps] for n, kps in ramps.items()}
        # a two-step button's release in a hit no cooldown is kept for: its heal lands there (Stasis, 48% released
        # in Vashnik's 3:35 window; the owner, round 79)
        released, rel_marks, rel_named = [], [], []
        for b in list(bare):
            m = next(x for x in shown if _mmss(x.t) == b)
            for c in h.cooldowns:
                hs = hit_share(c.release, m.t, m.t) if c.release is not None else None
                if hs is not None and hs >= 0.25:
                    inside = _counted(c.release, m.t, m.t)
                    t_rel = min(c.release.times, key=lambda t: abs(t - m.t), default=None)  # its chart mark, tied
                    if t_rel is not None and abs(t_rel - m.t) <= ANSWER[1] + SLACK:  # as the lead says (the chart
                        rel_marks.append((c.release, t_rel, _center(inside)))  # follows the lead)
                    rel_named.append(c)  # named in the lead with the other answers (a review: "answer them with Rewind"
                    # while two of three rows were Stasis releases)
                    released.append((m.t, f"for the {b} hit, {_pct(hs)} release a {e(_shown(c.name))}, whichever "
                                          "store it was"
                                          f"{_reach_note(c.release, m.t)} (about {_about(inside)}"
                                          + (f", a median {gap:.0f} s after storing"  # these releases' own
                                             if (gap := _gap_of(c, inside)) else "")  # stores (round 83: 16 s for 13)
                                          + ")"))
                    bare.remove(b)
                    break
        pairs = sorted(
            released + [clause(k, ps) for k, ps in by_press.items() if k not in merged]
            + [(ps[0][0], f"{e(_shown(n))} is their ramp ahead of the {_and([_mmss(p[0]) for p in ps])} hits: "
                          + ", ".join(f"{_pct(sp)} about {_tw(c_, t, hit)}" for hit, t, sp, c_ in ps) + _other(ps))
               for n, ps in ramps.items()])
        # a ramp's later presses made as soon as it is back: said by its rhythm line and the bare hits' landed_in
        end = len(h.curve) * STEP
        long = "".join(f" {'From ' + _mmss(a) + ' to the end' if b >= end - STEP else _mmss(a) + ' to ' + _mmss(b)}, "
                       f"the raid takes about {r:.1f}&times; the usual damage without a break."
                       for a, b, r in sustained(h.curve, h.moments))
        caused = sorted({n for m in shown for n in moment_names(m)
                         if h.dispelled and h.dispel_text and n in h.dispel_text})  # Vashnik's Caustic Explosion
        from_dispel = "".join(
            f" {e(n)} is set off when {e(h.dispelled[0][0])} is dispelled." for n in caused)
        def landed(hit: str) -> str:
            """A press the cards show in a hit kept for none (Tranquility's second at 3:43, back from cooldown): said,
            so "no cooldown" never sits next to a chip in the hit."""
            m = next(x for x in shown if _mmss(x.t) == hit)
            return landed_in(m, h.cooldowns, named)
        # each hit with its own bracket: "the 2:10 hit, nor the 3:40 hit (35% have...)", never one bracket read
        # as covering both
        by_icon = {_shown(c.name): c for c in [*h.cooldowns, *h.rare] + [c.release for c in h.cooldowns
                                                                         if c.release is not None]}
        them = ("it" if len(shown) == 1 else "them" if not bare  # never more than its rows (a review: "answer
                else f"{len(shown) - len(bare)} of them")         # them" over two rows of "None kept")
        lead = (f"<p class='lead'>{len(shown)} big raid {'hit' if len(shown) == 1 else 'hits'}"
                + (f": the top {e(h.spec)}s answer {them} with "
                   + _and([f"<span class='nw'>{_ic(by_icon.get(_shown(n)))}<b>{e(_shown(n))}</b></span>"
                           for n in lead_names]
                          + [f"<span class='nw'>{_ic(c)}<b>a {e(_shown(c.name))} release</b></span>"
                             for c in {c.name: c for c in rel_named}.values()]) if lead_names or rel_named
                   else f"; the top {e(h.spec)}s keep no cooldown for {'it' if len(shown) == 1 else 'them'}")
                + f".{long}{from_dispel}</p>"
                + hits_table(h.moments, shown, pairs, (bare_said := {b: landed(b) for b in bare}), h.phases, by_icon,
                             rule.strip(" ()")[:1].upper() + rule.strip(" ()")[1:]))
    drawn = list(heals)  # the chart's lanes: the cards' cooldowns, and a two-step button's release the lead ties
    for r, t, at in rel_marks:  # (its own lane, a full mark; on the store's card, not a card of its own)
        drawn = [*drawn, r] if r not in drawn else drawn
        lead_names = [*lead_names, r.name, r.name[:-len(" release")] + STORE]  # its store's card up with the lead's
        answered.add((r.name, t))
        if _mmss(at) != _mmss(t):
            moved[(r.name, t)] = at
    for c in heals:  # a press named for a hit's window: its hover says that window (heal confirm round 6)
        for t in [*c.times, *c.alt]:
            if named.get((c.name, t)) is not None:
                c.window_of[t] = named[(c.name, t)]
    for c in heals:  # a chip shown at its hit window's time: its chart mark there too (heal confirm round:
        for t in [*c.times, *c.alt]:  # Tranquility "3:36" on the chip, its outline at 3:46)
            at = _named_at(c, t, named, 0.0)
            if (c.name, t) not in moved and _mmss(at) != _mmss(t):
                moved[(c.name, t)] = at
    from dataclasses import replace as _rep

    lanes_extra: set = set()
    for (n, key), v in list(named.items()):  # a window line ("about 2:13"): its time drawn as an outline too
        if isinstance(key, tuple) and isinstance(v, tuple) and isinstance(v[1], str) and re.fullmatch(r"\d+:\d\d", v[1]):
            t_line = float(_secs(v[1]))
            drawn = [_rep(c, alt=[*c.alt, t_line] if t_line not in c.alt else c.alt,
                          alt_near=[*(c.alt_near or [""] * len(c.alt)), ""] if t_line not in c.alt else c.alt_near,
                          windowed=[*c.windowed, t_line])
                     if c.name == n else c for c in drawn]
    for txt in bare_said.values():  # "press X in its window …, about 4:18": that mark's hover gives the row's reason
        for n, at in re.findall(r"press ([A-Z][^()]{2,40}?) in its window.*?about (\d+:\d\d)", re.sub(r"<[^>]+>", "", txt)):
            t_row = float(_secs(at))
            drawn = [_rep(c, windowed=[*c.windowed, *(t for t in [*c.times, *c.alt] if abs(t - t_row) <= 10)])
                     if _shown(c.name) == html.unescape(n) else c for c in drawn]
            lanes_extra.add(html.unescape(n))
        for _n, at in re.findall(r"release a ([A-Z][^()]{2,40}?), whichever store it was,.*?about (\d+:\d\d)",
                                  re.sub(r"<[^>]+>", "", txt)):  # a release in the window: its lane and outline
            t_row = float(_secs(at))  # (heal confirm round 4: Nek'zali's Evoker 3:53, no mark)
            for c in heals:
                r = c.release
                if r is not None and all(x.name != r.name for x in drawn):
                    drawn = [*drawn, _rep(r, alt=[*r.alt, t_row], alt_near=[*(r.alt_near or [""] * len(r.alt)), ""],
                                          windowed=[t_row])]
                    lanes_extra.add(_shown(r.name))
                    lanes_extra.add(_shown(c.name))  # its store's lane too, as the sheets with a kept release
    lanes = set(lead_names) | {k[0] for k in named if k[0] != KEPT} | {c.name for c in drawn if _shown(c.name) in lanes_extra}
    # gets its lane and its outline there (heal confirm round 2: Convoke 60% in the 1:15 window, no mark)
    svg = curve_svg(h.curve, h.moments, h.phases, "Raid damage taken over the fight, and the top players' healing "
                    "cooldowns", drawn, lanes, answered, moved)
    rare_kept = [c for c in h.rare if c not in utility]
    rare = [c for c in rare_kept if c not in items and not is_defensive(c.spell_id, c.name)
            and _external(c.spell_id) != "protective"]  # the others go to their own section
    rare_ext = [c for c in rare_kept if c not in items and _external(c.spell_id) == "protective"]
    rare_def = [c for c in rare_kept if c not in items and c not in rare_ext and is_defensive(c.spell_id, c.name)]
    fight = ([lead] if lead else []) + [
        f"<h2>The raid damage, and its big moments</h2><div class='card'>{svg}<p class='small muted'>Median raid "
        f"damage per second, {h.raid_kills or 'the top'} kills (up to 40 a spec read: the same hits on every healer "
        f"sheet; fewer kills past the median one). "
        + ("After a dashed line, stage time (below). " if getattr(h, "staged", False) else "")
        + ("Marks: the table's answers" + (" (an outline: another press, or one in a hit's window that is not "
                                            "its answer)" if any(
            (c.name, t) not in answered for c in drawn if c.name in lanes for t in [*c.times, *c.alt])
            else "") + ". " if lead_names
           else "No cooldown is kept for these hits; an outline: a press in a hit's window, not its answer. "
           if lanes else "No cooldown is kept for these hits, so none is drawn. ")
        + "A dot: a big hit, "
        + ("named after what deals most of the damage there"
           if h.named_by_damage else "named after the boss cast just before it (&quot;after X&quot;: 8 to 30 s "
           "before, matched by timing)") + f".</p><ul class='hl2'>"
        f"{'' if h.moments else '<li>No big moment: steady raid damage.</li>'}</ul></div>",
        f"<h2>Your long cooldowns, where the top {e(h.spec)}s press them</h2><ul class='hl2'>"
        f"{cooldowns_html(sorted((c for c in heals if _external(c.spell_id) != 'protective'), key=_rank(lead_names)), answered, named, moved) or '<li>Not enough top players in the corpus yet.</li>'}"
        f"{rare_html(rare, answered, named)}</ul>"]  # a cooldown the top players skip is information too
    exts = [c for c in heals if _external(c.spell_id) == "protective"]
    buffers = [c for c in heals if _external(c.spell_id) == "damage"]  # Power Infusion: a buff on a damage dealer
    buff_note = (f" {_and([e(_shown(c.name)) for c in buffers])}, a buff cast on a damage dealer, is with your long "
                 "cooldowns above." if buffers else "")  # round 34: "fewer than half cast one" read as PI's absence
    if exts or rare_ext:  # cast on another player: their own group, apart from the raid cooldowns; one form at
        # any share (round 98: Time Dilation 50% a card, 48% a line; heal round 10: still two forms)
        fight.append(f"<h2>Your externals{f', where the top {e(h.spec)}s cast them' if any(c.times for c in exts) else ''}"
                     f"</h2><ul class='hl2'>"
                     f"{cooldowns_html(exts, answered, named)}{rare_html(rare_ext, answered, named)}</ul>"
                     + (f"<p class='small muted'>{buff_note.strip()}</p>" if buff_note else ""))
    else:  # none, said (round 92: the Shaman's sheet had no line, the Dig deeper table a "–")
        fight.append(f"<h2>Your externals</h2><p class='small muted'>The top {e(h.spec)}s cast no long protective "
                     f"cooldown on another player here.{buff_note}</p>")
    if defs or rare_def:
        fight.append(f"<h2>Your defensives</h2><ul class='hl2'>{cooldowns_html(defs, answered, named)}"
                     f"{rare_html(rare_def, answered, named)}</ul>")
    if items:
        fight.append(f"<h2>On-use trinkets</h2><ul class='hl2'>{cooldowns_html(items, answered)}</ul>")
    potions = h.potions or [c for c in h.cooldowns if _item(c.spell_id) and c not in items]  # as the tank's
    if potions:
        fight.append(f"<h2>Consumables</h2><ul class='hl2'>{cooldowns_html(potions, set())}</ul>")
    if utility:
        fight.append("<p class='small muted'>Also pressed, no healing cooldown: "
                     + ", ".join(f"{e(_shown(c.name))} ({_times_line(c)})" for c in utility)
                     + ".</p>")
    n_kills = h.own_kills or h.kills  # the healers in this spec's top kills; the pooled numbers say their own
    change = [build_lead(h.builds, h.spec, h.split_players or h.kills, h.split, h.split_wide)]
    change.append(talents_html(h.builds, h.split_players or h.kills, f"{h.spec}s", h.hero))
    if h.split:
        change.append(split_html(h.split, h.split_players, h.spec, h.split_wide, getattr(h, "talent_icons", None)))
    trk = trinkets_html(h.trinkets, getattr(h, "item_icons", None)) or "<li>No gear yet.</li>"
    change.append(f"<h2>Trinkets the top {e(h.spec)}s equip</h2><ul class='hl2 bars'>{trk}</ul>"
                  f"<p class='small muted'>"
                  f"To weigh a talent or an item for your character, use <a href=\"{QE_LIVE}\" target=\"_blank\" "
                  f"rel=\"noopener\">QE Live</a>.</p>")
    jr = "".join(f"<li>{e(_plain(x))}</li>" for x in h.journal)
    when = (f", a median {h.dispel_delay[0]:.0f} s after it lands" if h.dispel_delay else "")
    # what the dispel sets off, when it is part of a big moment (Vashnik: Caustic Explosion at 2:10 and 3:35)
    feeds = sorted({n for m in h.moments for n in moment_names(m) if n and n in (h.dispel_text or "")})
    fed = "".join(f" {e(n)} is part of the raid's big damage at "
                  + _and([_mmss(m.t) for m in h.moments if n in moment_names(m)]) + "."
                  for n in feeds)
    # a dispel every healer does: said as what the top players do, not as this spec's job (Dig deeper says those)
    aura = h.dispelled[0][0] if h.dispelled else ""
    first = ([f"<p class='lead'>The top {e(h.spec)} of each kill removes {e(aura)} {h.dispelled[0][1]:.1f} times "
              f"a kill{when}." + (f" {e(h.dispel_text)}" if h.dispel_text else "") + fed + "</p>"  # the journal's
              f"<p class='small muted'>A mean over {h.dispel_kills} of their kills, timed: a lighter read than the "
              f"cooldowns' {h.kills}; the Dig deeper tab's rates a minute are medians over every kill.</p>"]  # method
             # under the lead, not in it (round 78)
             if h.dispelled and h.dispelled[0][1] >= 1 else [journal_lead(h.journal, "healers")])
    boss = first + (
        [f"<h2>What the Encounter Journal asks healers</h2><ul class='hl2'>{jr}</ul>"] if jr else [])
    if h.dispelled and (len(h.dispelled) > 1 or h.dispelled[0][1] < 1):  # the others than the lead's job, measured
        inside = set(re.findall(r'<b>([^<]+)</b>', h.abilities))  # the abilities the journal lists below
        said = h.dispelled[0][1] >= 1  # the lead's note says how it is counted (heal round 11: said twice)
        boss.append(f"<h2>{'What else' if said else 'What'} the top {e(h.spec)}s dispel here</h2><p class='dispels'>"
                    + "".join(f"<span class='chip'><b>{e(n)}</b> &middot; {k:.1f} a kill"
                              + ("" if n in inside else " &middot; <small>not in the Encounter Journal</small>")
                              + "</span>" for n, k in (h.dispelled[1:] if said else h.dispelled)) + "</p>"  # the
                    # lead's own said once (heal round 12: Exploding Infection 4.2 in the lead and its chip)
                    + ("" if said else f"<p class='small muted'>Means over {h.dispel_kills} of their kills read; the "
                       "rates a minute on the other tabs are medians over every kill.</p>"))  # (round 114: 6.0 a
                    # kill here beside "1.0 a minute")
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
            stages = stages.replace(f"<b>{e(name)}</b>", f"<b>{e(name)}</b> <small class=\"muted\">(the top "
                                    f"{e(h.spec)}s dispel it {k:.1f} times a kill)</small>", 1)
        boss.append(f"<h2>Every ability{', phase by phase' if '<h3>' in stages else ''}</h2>"  # Vashnik: one phase
                    f"<p class='small muted'>Pull times in the {h.kills} top {e(h.spec)} kills (median "
                    f"{_mmss(h.duration)}): they shift with your raid's pace, and another spec's sheet can differ"
                    + ("; the fight tab's, in stage time, can sit a few seconds off" if getattr(h, "staged", False)
                       else "") + ".</p>"
                    f"<div class='stages'>{stages}</div>")
    # every spec the pool reads (paf.healroles.POOL_PLAYERS): the Disc Priest, 3 in a Holy Priest's kills, has 43
    # in the pool; its casts unread here are said so in its cells
    shown = sorted(h.roles, key=lambda r: r.spec != h.spec)
    others = roles_table(shown, h.spec) + (nums_note(h.roles, h.own_sample) if shown else "") + roles_more(
        shown, h.spec, h.moments, getattr(h, "staged", False),
                                                  getattr(h, "role_icons", {}))
    few = [p.spec for p in h.presence if p.spec not in {r.spec for r in shown}]
    deeper_first: list[str] = [jobs_lead(shown, h.spec)]  # the cards below only: a spec too rare has no claim
    # every sample of the sheet, once (round 34: five kill counts and no map)
    counts = [f"your cooldowns' timings: the {h.kills} top {e(h.spec)} kills (every cast read)",
              # the 150 against the 100 said (round 78), counted, not assumed: the timed kills are read first, yet
              # not always all (Restoration Shaman, Nek'zali: 99 of 100 in 149)
              (f"the healers in them: {h.own_kills} top kills"
               + (f" ({'the' if h.own_timed == h.kills else f'{h.own_timed} of the'} timings' {h.kills} and "
                  f"{h.own_kills - h.own_timed} more, read for their healers only)"
                  if h.own_timed and h.own_kills > h.own_timed else ""))
              if h.own_kills else "",
              f"the table, jobs and the other healers: {h.role_kills:,} kills · every spec"
              + (" (the other healers' presses: those whose stage starts are read)" if getattr(h, "staged", False)
                 else "") if h.role_kills
              else "",
              f"the raid's damage: {h.raid_kills} kills" if h.raid_kills else "",
              "each job: its own kill count, per row",
              f"dispel timings: {h.dispel_kills} kills" if getattr(h, "dispel_kills", 0) else ""]
    deeper_first.append("<p class='sources'><span class='src-lab'>Read on</span>"  # one chip a source (the owner:
                        + "".join(_src_chip(x) for x in counts if x) + "</p>")  # less text)
    if h.presence:
        have = next((x for x in h.presence if x.spec == h.spec), None)
        if have and have.share >= 0.99:  # the corpus is your spec's top players' kills: they all have one
            line = (f"These are the top {e(h.spec)}s' kills, so every one has a {e(h.spec)} ({have.per_kill:.1f} a "
                    f"kill).")
        elif have:
            line = f"{_pct(have.share)} of the top kills bring a {e(h.spec)} ({have.per_kill:.1f} a kill when they do)."
        else:
            line = f"Few top raids bring a {e(h.spec)} on this boss."
        deeper_first.append(f"<h2>Healers in the top {e(h.spec)}s' kills</h2><p>{line} In the {n_kills} top kills read for "
                      f"their healing"  # the casts' 100 said under "Where the numbers come from" (round 77)
                      + (f" (median {_mmss(h.own_median)}" if h.own_median else "")
                      + (f", {'slower' if h.own_median > h.duration else 'faster'} than the {h.kills} top kills' "
                         f"{_mmss(h.duration)}: picked by their healing, not their kill time"
                         if h.own_median and abs(h.own_median - h.duration) >= 10 else "")
                      + (")" if h.own_median else "") + ": how often each other healer spec is there, and the kills "
                      "with it against those without it (a reading, not a verdict).</p>"
                      f"{presence_table(h.presence, h.spec)}")
    deeper = deeper_first + [f"<h2>What each healer spec brings here</h2><p class='small muted'>Measured on {h.role_kills:,} "
              f"{e(h.role_sample or 'top kills')}.{_pace(h)}</p>{others or '<p>Not measured yet.</p>'}"
              + (f"<p class='small muted'>Too few healers measured: {e(', '.join(few))}.</p>" if few else ""),
              (f"<h2>The healer compositions played most</h2>{comps_table(h.comps, n_kills)}"
               if comps_table(h.comps, n_kills) else "")]
    # every sample said once, at the top: the timings and talents, the healers' comparison; read, not simmed
    byline = (f"{e(h.character or h.spec)} &middot; {e(h.spec)} &middot; from {h.kills} top kills (median "
              f"{_mmss(h.duration)})"  # the healers' other samples are said on Dig deeper, where they are used
              + " &middot; no healing sim")
    # the legend under every card it explains, its used terms only (a review: mid-page, it split the cards)
    fight.append(legend_for(HOW_TO_READ.replace("</dl>", f"<dt>Stage time</dt><dd>{STAGE_TERM}</dd></dl>")
                            if getattr(h, "staged", False) else HOW_TO_READ, "".join(fight)))
    return sheet_page(h.boss, h.difficulty, byline, h.class_name,
                      {"fight": fight, "change": change, "boss": boss, "deeper": deeper}, theme.style("healer"),
                      UNSIMMED)
