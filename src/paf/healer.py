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


def moment_names(m: Moment) -> list[str]:
    """The abilities a moment is named after: "mixed damage, most from A and B" -> [A, B]."""
    return [x for x in m.boss_spell.removeprefix("mostly ").removeprefix("after ").split(" and ") if x]


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
            m.boss_spell = f"mostly {first} and {second}"


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
        users = sum(1 for ts in per_player if ts) / max(1, len(tl.players))
        per_player = [ts for ts in per_player if ts]
        if not per_player or not tl.duration:
            continue
        per_kill = st.median(len(ts) for ts in per_player)
        if not min_users <= users < max_users or per_kill > max(1.0, tl.duration / COOLDOWN_GAP):
            continue
        if base and max(base.get(i, (0.0, 1))[0] for i in ids) < COOLDOWN_GAP:
            continue
        sid = max(abs_, key=lambda a: a.users).id
        times, alt, alt_of = press_moments(per_player, max(1, round(per_kill)), tl.duration)
        every = on_cadence(per_player, per_kill, tl.duration)
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
        gaps = [y - x for ts in per_player for x, y in pairwise(ts)]
        rhythm = st.median(gaps) if gaps and not every and cd and st.median(gaps) <= 1.15 * cd else 0.0
        if _item(sid):  # a trinket or a potion: one wording on every sheet, its rhythm said with it
            every = 0.0
        # one reason a button, the same on every boss: what it is first (Life Cocoon is cast on another player
        # on Vashnik and Nek'zali alike, even where it is pressed about every minute), then how often
        why = ("" if every else "cast on another player" if _external(sid) else "a cast-while-moving button"
               if _moving(sid) else "a movement button" if _speed(sid) else _item_why(name, sid) if _item(sid) else "about every minute" if per_kill >= 4
               else "")
        back = {x for x in [*times, *alt] if back_share(per_player, x, cd) > 0.5}  # pressed as soon as it is back
        tied = not (every or why)  # on cooldown, a 1-minute button, a
        near = []  # buff on one player, a cast-while-moving: near a hit by chance, not kept for it
        for t in times:
            m = min(found, key=lambda m: abs(m.t - t), default=None)
            ok = (tied and m is not None and -ANSWER[0] <= t - m.t <= ANSWER[1]  # pressed for the hit: before or in
                  and t not in back)  # it; not a press made as soon as it is back
            near.append(f"{_mmss(m.t)} {m.boss_spell}".strip() if ok else "")
        n_all = max(1, len(tl.players))  # the share of all the top players pressing it within 8 s of each moment
        support = [sum(1 for ts in per_player if any(abs(x - t) <= 8 for x in ts)) / n_all for t in times]
        # a moment a quarter of those who press it share at least: under, it is timing that varies (a chip at 12%
        # of the top players read as a moment next to "no moment most of them share")
        kept = [i for i, sp in enumerate(support) if sp >= 0.25 * users]
        times, near, support = [times[i] for i in kept], [near[i] for i in kept], [support[i] for i in kept]
        alt, alt_of = ([], []) if every else (alt, alt_of)
        alt_support = [sum(1 for ts in per_player if any(abs(x - t) <= 8 for x in ts)) / n_all for t in alt]
        kept = [i for i, sp in enumerate(alt_support) if sp >= 0.25 * users  # the same quarter as the moments,
                and alt_of[i] in times]  # of a moment still shown
        alt, alt_support, alt_of = [alt[i] for i in kept], [alt_support[i] for i in kept], [alt_of[i] for i in kept]
        alt_near = []  # another habit answers a hit too (Aura Mastery at 0:36 for 28%: the 0:35 hit)
        for t in alt:
            m = min(found, key=lambda m: abs(m.t - t), default=None)
            ok = (tied and m is not None and -ANSWER[0] <= t - m.t <= ANSWER[1]
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
                            back=sorted(x for x in back if x in times or x in alt)))
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
    return [(names[i], i, c / n) for i, c in count.most_common(6) if c / n >= 0.10]  # under 10%: no habit


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


CSS = "<style>" + theme.style("healer") + "</style>"
JS = ("<script>document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(!b)return;"
      "navigator.clipboard.writeText(b.dataset.copy).then(function(){b.textContent='Copied'},function(){})})"
      "</script>")


PRESS_ROWS = 4  # cooldown rows drawn under a damage curve


SWAP_LANE = -1  # a Cooldown with this spell id is the tank swaps' lane: ticks, no press marks


def curve_svg(curve: list[float], found: list[Moment], phases: list[tuple[str, float]], label: str,
              presses: list | None = None, named: set[str] | None = None, answered: set | None = None) -> str:
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
    marks = guides + "".join(f"<circle cx='{x(m.t)}' cy='{y(m.dtps)}' r='4' class='mk'/>"
                    f"<text x='{float(x(m.t)) + 6:.1f}' y='{float(y(m.dtps)) - 8:.1f}' class='ml'>{_mmss(m.t)}</text>"
                    for m in found)
    lines = "".join(f"<line class='ph' x1='{x(t)}' x2='{x(t)}' y1='22' y2='{H - B}'/>"
                    f"<text x='{float(x(t)) + 4:.1f}' y='18' class='pn'>{e(n.split(':')[0])}</text>"
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
        + "".join(f"<rect x='{float(x(t)) - 4:.1f}' y='{H - B + 6 + 18 * i}' width='8' height='13' rx='2' "
                  f"class='cp{'' if t in tied else ' off'}'><title>{e(c.name)} {_mmss(t)}"
                  f"{'' if t in tied else ' (tied to no hit)'}</title></rect>"
                  for t in [*c.times, *c.alt] if t <= span
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


def moments_html(found: list[Moment], what: str) -> str:
    """what: kept for the callers; a moment no boss cast explains shows its time only."""
    return "".join(f"<li><b>{_mmss(m.t)}</b><span>{e(m.boss_spell) if m.boss_spell else ''}</span>"
                   f"<small>{m.ratio:.1f}&times; the usual damage</small></li>" for m in found)


def _shown(name: str) -> str:
    """A spell's name without the log's internal suffix ("Stasis (Store)" -> "Stasis")."""
    return re.sub(r"\s*\([^)]*\)$", "", name) or name


def _share(sp: float) -> str:
    """How many of the top players press it then: a chip is no consensus ("1:16 · 28% of them")."""
    return f" &middot; {_pct(sp)} of the top players" if sp else ""


def _more(c: Cooldown) -> str:
    """The casts a kill no shared moment shows ("+1"): the count always matches the "a kill" number."""
    n = round(c.per_kill) - len(c.times)
    return f"+{n}" if n > 0 else ""


def _or(c: Cooldown, t: float, answered: set | None = None) -> str:
    """The other habits nearest this moment, said on its chip ("1:18, or 0:36 for some"): another player's choice
    for the same press, never an extra one."""
    near = [(a, sp, n) for a, sp, k, n in zip(c.alt, c.alt_support or [0.0] * len(c.alt),
                                              c.alt_of or [None] * len(c.alt), c.alt_near or [""] * len(c.alt),
                                              strict=False)
            if (k if k is not None else min(c.times, key=lambda x: abs(x - a))) == t]  # the same press only
    if not near:
        return ""
    # every other habit, each said, with the hit it answers as the main time is ("0:34 · 1 s before the 0:35 hit")
    near = [(a, sp, n if answered is None or (c.name, a) in answered else "") for a, sp, n in near]
    return ", or " + ", ".join(f"{_chip(a, n)} for {_pct(sp)}" if sp else f"{_chip(a, n)} for some"
                               for a, sp, n in near)


BACK = 8.0  # seconds past its cooldown a press still counts as pressed as soon as it is back


def back_share(per_player: list[list[float]], t: float, cd: float) -> float:
    """Of the players pressing a button about t (within 8 s), the share whose own press before it is within its
    cooldown plus BACK: they press it as soon as it is back. Read per player, never between moments (Evangelism's
    0:04 and 2:07 moments are 123 s apart, yet its players press it 90-102 s after their own last one)."""
    near = [(x, max((y for y in ts if y < x), default=None)) for ts in per_player for x in ts if abs(x - t) <= 8]
    return (sum(1 for x, y in near if y is not None and x - y <= cd + BACK) / len(near)) if near and cd else 0.0


def landed_in(m: Moment, cds: list[Cooldown]) -> str:
    """The press most of them make inside a hit no cooldown is kept for, and why it is no answer: "(35% have
    Tranquility land at 3:43, back from cooldown)". Every button and habit is read (Celestial Conduit's 2:11 habit,
    Life Cocoon), the same for healers and tanks."""
    near = []
    for c in cds:
        if _item(c.spell_id) or _external(c.spell_id) == "damage":  # a trinket, Power Infusion on a damage dealer:
            continue                                                  # nothing for the raid's hit
        if c.why:  # an external (Life Cocoon), a 1-minute button (Nature's Swiftness): no raid answer to name
            continue
        for t, sp in [*zip(c.times, c.support or [], strict=False), *zip(c.alt, c.alt_support or [], strict=False)]:
            if -ANSWER[0] <= t - m.t <= ANSWER[1]:  # each time read on its own players (back_share)
                why = (c.why or ("on cooldown" if c.every else "back from cooldown"
                                 if t in c.back else ""))
                if why:
                    near.append((sp, c, t, why))
    if not near:
        return ""
    sp, c, t, why = max(near, key=lambda x: x[0])
    return f" ({_pct(sp)} have {e(_shown(c.name))} land at {_mmss(t)}, {e(why)})"


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


def cooldowns_html(cds: list[Cooldown], answered: set | None = None) -> str:
    """The cooldown rows. answered: the (button, time) pairs the lead ties to a hit; a chip says its hit only for
    those, so no chip reads as an answer the lead and the chart do not give (Apotheosis "1 s before the 0:35 hit")."""
    def tie(c: Cooldown, t: float, n: str) -> str:
        return n if answered is None or (c.name, t) in answered else ""
    return "".join(
        f"<li><b>{e(_shown(c.name))}</b><small>pressed by {c.users:.0%} of the top players &middot; {count(c.per_kill)} a kill"
        + (f", {_pct(c.on_others)} of them on another player" if 0 <= c.on_others < 0.95 else
           ", all on another player" if c.on_others >= 0.95 else "") + "</small>"
        "<span class='when'>" + ("".join(f"<span class='chip'>{_chip(t, tie(c, t, n))}{_share(sp)}"
                                        + (" &middot; back from cooldown"
                                           if t in c.back and not c.why else "")
                                        + f"{_or(c, t, answered)}</span>"
                                        for k, (t, n, sp) in enumerate(zip(c.times, c.near,
                                                                           c.support or [0.0] * len(c.times),
                                                                           strict=False)))
                                or "<small>timing varies: no shared moment</small>")
        + (f"<small class='alt'>on cooldown, about every {c.every:.0f} s</small>" if c.every else
           f"<small class='alt'>{_more(c)} more at varying times</small>" if c.times and _more(c) else "")
        + (f"<small class='alt'>{'mostly ' if c.why.startswith('cast on another') and 0 <= c.on_others < 0.95 else ''}"
           f"{e(c.why)}: not tied to a hit</small>" if c.why and c.times else "")
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
    """A press's time and the hit it answers, said as before, at or after it ("1:11 · just before the 1:15 hit")."""
    if not n:
        return _mmss(t)
    hit = n.partition(" ")[0]
    m, _, sec = hit.partition(":")
    gap = int(t) - (int(m) * 60 + int(sec))  # from the seconds shown: "0:42 · 2 s into the 0:40 hit"
    # said with its offset from the hit's start: "4 s into" its 5 s window, "3 s before", "2 s after" it
    return _mmss(t) + (f" &middot; as the {e(hit)} hit starts" if gap == 0 else  # one form, from its start (a hit
                       f" &middot; {-gap} s before the {e(hit)} hit" if gap < 0 else  # is a 5 s window: "6 s into"
                       f" &middot; {gap} s after the {e(hit)} hit starts")  # it read as past it)


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
        line = ("<p><b>Hero tree:</b> " + (f"{e(hero[0][0])} (all {players} players read)" if len(hero) == 1 else
                " &middot; ".join(f"{e(t)} {s:.0%}" for t, s in hero) + f" of the {players} players read") + ".</p>")
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


def _and(items: list[str], word: str = "and") -> str:
    """'a', 'a and b', 'a, b and c'."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {word} " + items[-1] if items else ""


def build_lead(builds: list, spec: str, players: int, split: list | None = None) -> str:
    """The change tab's answer: the most played build when the top players agree on one; when their builds are
    scattered, the talents they split on (the rest they agree on)."""
    shown = shown_builds(builds, players)  # the sentence counts the builds the list shows
    if not shown:  # no shared build: still an answer, the talents they split on
        most = builds[0][0] if builds else 0
        return (f"<p class='lead'>No build is shared among the top {e(spec)}s; none is played by more than {most} of the "
                f"{players} players read"
                + (f": their builds differ by many small choices, the closest to 50/50 being "
                   f"{e(_and([n for n, _s in split[:4]]))}" if split else "") + f".{NOT_ADVICE}</p>")
    builds = shown
    top = builds[0]
    total = sum(b[0] for b in builds)
    if split and top[0] < players / 5:  # no build a fifth of them play: the answer is in the split talents
        return (f"<p class='lead'>No build is played by more than {top[0]} of the {players} top {e(spec)}s read: "
                f"their builds differ by many small choices, the closest to 50/50 being "
                + e(_and([n for n, _s in split[:4]])) + f".{NOT_ADVICE}</p>")
    return (f"<p class='lead'>The most played build of the top {e(spec)}s"
            + ("" if len(builds) == 1 else f", {e(top[1])},") + f" is played by {top[0]} of the "
            f"{players} players read" + (f"; the {len(builds)} builds below cover {total} of them, the other "
                                        f"{players - total} play builds of their own" if len(builds) > 1 else "")
            + f".{NOT_ADVICE}</p>")


NOT_ADVICE = " Their choices, not a recommendation: no sim weighs them."


def split_html(split: list, players: int, spec: str, wide: bool = False) -> str:
    """The talents the top players split on, with how often each is picked: what the builds above hide. wide: none
    is taken by 35 to 65% of them (Holy Paladin), so the talents they differ on most, from 15 to 85%."""
    return ((f"<h2>The talents the top {e(spec)}s differ on most</h2><p>None is taken by 35 to 65% of them. The share "
             f"of the {players} players read who take each, closest to half first:</p>" if wide else
             f"<h2>The talents the top {e(spec)}s split on</h2><p>The share of the {players} players read "
             "who take each, closest to half first:</p>") + "<ul class='hl2 split'>"
            + "".join(f"<li><b>{e(n)}</b><small>{s:.0%}</small></li>" if s >= 0 else
                      "<li>" + " / ".join(f"<b>{e(a)}</b> <small>{b}</small>" for a, _, b in
                                          (x.rpartition(" ") for x in n.split(" / "))) + "</li>"
                      for n, s in split) + "</ul>")


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
    buffs = any(r.buffs for r in roles)
    cover = next((r.spike_cover for r in roles if getattr(r, "spike_cover", 0)), 0.0)
    head = ("<th>Healer</th><th>Healing share</th><th>On tanks</th>"
            f"<th>In spikes{f' ({_pct(cover)} of the fight)' if cover else ''}</th>"
            "<th>Overheal</th><th>Dispels a minute</th><th>Externals given a kill</th>"
            + ("<th>Buffs given a kill</th>" if buffs else "") + "<th>Players</th>")
    rows = "".join(
        f"<tr class='{'mine' if r.spec == mine else ''}'><td>{e(r.spec)}{' <small>(you)</small>' if r.spec == mine else ''}"
        f"</td><td class='n'>{_pct(r.healing)}</td><td class='n'>{_pct(r.tank)}</td><td class='n'>{_pct(r.spike)}</td>"
        f"<td class='n'>{_pct(r.overheal)}</td><td class='n'>{r.dispels:.1f}</td>"
        f"<td class='n'>{f'{r.externals:.1f}' if r.externals >= 0.05 else '&ndash;'}</td>"
        + (f"<td class='n'>{f'{r.buffs:.1f} <small>{e(_and(r.buff_spells))}</small>' if r.buffs else '&ndash;'}</td>"
           if buffs else "")
        + f"<td class='n'>{r.players}</td></tr>" for r in roles)
    return (f"<table class='hcomp'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
            + ("<p class='small muted'>Your spec's share of the healing is high by design: these kills were picked "
               "for its top healers.</p>" if any(r.spec == mine for r in roles) else ""))


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


def roles_more(roles: list, mine: str = "", found: list | None = None) -> str:
    """Under the table, what a number cannot say: each other spec's job here, and its cooldowns pressed for the big
    hits (found): who covers which hit, not its Avenging Wrath at the pull."""
    def chip(n: str, ts: list, users: float | None) -> str:  # the press share first: "14%" of all the players
        return "".join(f"<span class='chip'>{e(_shown(n))} {_mmss(t)} &middot; {_pct(sp)} of them</span>"
                       for t, sp in ts)
    out = ""
    for r in roles:
        jobs = [j for j in r.jobs if not j.startswith("nothing stands out")]
        def hit(t: float) -> bool:
            return found is None or any(-ANSWER[0] <= t - m.t <= ANSWER[1] for m in found)
        cds = "".join([chip(n, [x for x in ts if hit(x[0])], (rest or [None])[0]) for n, _k, ts, *rest in r.cd_names
                       if any(hit(t) for t, _sp in ts) and not _minute(n)][:5]) if r.spec != mine else ""
        if jobs or cds:
            out += (f"<li><b>{e(r.spec)}</b>" + (f"<small>{e('; '.join(jobs))}</small>" if jobs else "")
                    + (f"<span class='when'>{cds}</span>" if cds else "") + "</li>")
    return ("<h2>The other healers' cooldowns on the big hits</h2>"
            + (f"<ul class='hl2'>{out}</ul><p class='small muted'>Each share is of that spec's healers in these "
               "kills.</p>" if out else "<p>None of the other healer specs here shares a cooldown on them.</p>"))


def _job(r) -> str:
    """A spec's healing job of this boss, or "": not "nothing stands out", nor Power Infusion given on every boss."""
    return next((j for j in r.jobs if not j.startswith(("nothing stands out", "buffs a damage dealer"))), "")


def _pace(h) -> str:
    """The comparison's kills against the timings' ones, said from the numbers (kills ranked by a healer's healing
    were said slower: on four sheets they were not)."""
    if not h.role_median or not h.duration or abs(h.role_median - h.duration) < 10:  # under 10 s: noise
        return ""
    return (f" These kills are {'slower' if h.role_median > h.duration else 'faster'} than the {h.kills} top kills "
            f"({_mmss(h.role_median)} against {_mmss(h.duration)}).")


def jobs_lead(roles: list, mine: str = "") -> str:
    """The deeper tab's answer: your spec's job first, then the other healer specs whose job stands out."""
    you = next((r for r in roles if r.spec == mine), None)
    head = ""
    if you:
        head = (f"Your spec here: the {you.spec} {_job(you)}. " if _job(you) else
                "Your spec here: nothing stands out against the other healers of the same kills. ")
    lines = [f"the {r.spec} {_job(r)}" for r in roles if r.spec != mine and _job(r)]
    if not lines:
        return f"<p class='lead'>{e(head)}No other healer spec stands out either.</p>"
    return f"<p class='lead'>{e(head)}The others: " + "; ".join(e(x) for x in lines) + ".</p>"


def nums_note(roles: list) -> str:
    """What the cards' numbers are, said once above them (the spikes' share of the fight too)."""
    cover = next((r.spike_cover for r in roles if getattr(r, "spike_cover", 0)), 0.0)
    spikes = f", {_pct(cover)} of the fight" if cover else ""
    return ("Each row is the median of every player of the spec in these kills, a second one included (the boss "
            "tab's dispels count the top one; externals and buffs: a mean, on others only). A job is a spec doing more than the other healers of the same "
            "kills, read on every kill of the boss collected for any spec (each kill's ranked player left out, its kill picked for it), beyond chance over every spec and number (Benjamini-Hochberg, 5%) and "
            "by a fifth at least: a habit of the spec may show on other bosses too. The shares come from different kills and do not add up; "
            f"a spike is 5 s at 1.5 times the kill's median{spikes}. Externals and overheal follow each kit.")


def _plain(text: str) -> str:
    """A journal line without its spell brackets: "[Soulcoil Well]" -> "Soulcoil Well"."""
    return re.sub(r"[\[\]]", "", text)


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
                    + ("" if p.duration_close else ", beyond the noise") + ")</small>")
                 + "</td>" + (f"<td class='n'>{dd(p.deaths_with, None if few_without else p.deaths_without)}"
                              + (" <small>beyond the noise</small>" if not p.deaths_close and p.deaths_with is not None
                                 and not few_without else "") + "</td>" if deaths else ""))
        if few and not deaths:
            cells = "<td class='n' colspan='2'><small>too few kills</small></td>"
        rows += (f"<tr class='{'mine ' if p.spec == mine else ''}{'few' if few else ''}'><td>{e(p.spec)}</td>"
                 f"<td class='n'>{_pct(p.share)} <small>({p.kills} kill{'s' if p.kills != 1 else ''})</small></td>"
                 f"{cells}</tr>")
    head = (f"<th>{what}</th><th>Top kills with one</th><th>Per kill</th><th>Median kill</th>"
            + ("<th>Deaths per 20 players</th>" if deaths else ""))
    marked = "beyond the noise" in rows
    return ((f"<p>With or without any {e(what.lower())} spec here, kill time and deaths stay within the noise.</p>"
             if not marked else "")
            + f"<table class='hcomp'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
            "<p class='small muted'>A difference with and without a spec is marked when it is beyond the noise "
            "(three standard errors); unmarked, it is within it.</p>")


def comps_table(comps: list, n_kills: int) -> str:
    if not comps or all(c.kills < FEW_KILLS for c in comps):  # no composition played enough: no table to read
        return ""
    deaths = any(c.deaths is not None for c in comps)
    comps = [c for c in comps if c.kills >= FEW_KILLS]  # the same cut as every other table
    rows = "".join(
        f"<tr><td>{e(c.label)}</td><td class='n'>{c.kills} ({_pct(c.share)})</td><td class='n'>{_mmss(c.duration)}</td>"
        + (f"<td class='n'>{'' if c.deaths is None else f'{c.deaths:.1f}' if c.kills >= FEW_KILLS else '<small>too few kills</small>'}</td>"
           if deaths else "") + "</tr>"
        for c in comps)
    return ("<table class='hcomp'><thead><tr><th>Healers</th><th>Top kills</th><th>Median kill</th>"
            + ("<th>Deaths per 20 players</th>" if deaths else "") + f"</tr></thead><tbody>{rows}</tbody></table>"
            f"<p class='small muted'>Of {n_kills} top kills read. Exact compositions played at least {FEW_KILLS} times; the "
            f"other {n_kills - sum(c.kills for c in comps)} kills play rarer ones."
            + (" Deaths, per 20 players (heroic raids are 10 to 30), are a mean over the kills whose deaths were "
               f"read, shown from {FEW_KILLS} of them." if deaths else
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
    lead, lead_names, answered = "", [], set()
    if h.moments:
        shown = h.moments[:3]
        ratios = (f"{'both' if len(shown) == 2 else 'each'} {shown[0].ratio:.1f}&times;"
                  if len({round(m.ratio, 1) for m in shown}) == 1 and len(shown) > 1
                  else _and([f"{m.ratio:.1f}&times;" for m in shown]))
        groups: dict[str, list[Moment]] = {}  # moments of the same ability said together (Vashnik's "mixed
        for m in shown:                       # damage, most from..." three times in one sentence)
            groups.setdefault(m.boss_spell, []).append(m)
        sep = "; " if any(len(ms) > 1 for ms in groups.values()) else None  # "0:40 (A); 2:10 and 3:35 (each time B)"
        hits = (sep.join if sep else _and)([f"{_and([_mmss(m.t) for m in ms])}"
                     + (f" ({'each time ' if len(ms) > 1 else ''}{e(name)})" if name else "") for name, ms in groups.items()])
        hits += f": {ratios} the usual damage"
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
                by_name.setdefault(c.name, []).append((m.t, t, sp, press, c))

        # one cooldown per hit, the one most of them press then; a second as common within the noise (Avenging
        # Wrath 36%, Aura Mastery 35% on Vashnik's 0:40 hit) is named with it; the other habits are on the rows below
        tops: dict[float, list] = {}
        for n, hs in by_name.items():
            for hit, t, sp, press, c in hs:
                tops.setdefault(hit, []).append((n, t, sp, press, c))
        n_read = max(1, h.kills)
        for hit, xs in tops.items():  # a ramp's time ahead of the hit first when as many press it (Evangelism
            xs.sort(key=lambda x: (-x[2], not (x[4].ramp and hit - x[1] >= RAMP[0])))  # 1:42 over 2:07, 36% both
            noise = (xs[0][2] * (1 - xs[0][2]) / n_read) ** 0.5
            # two buttons, never one twice (Evangelism at 2:07 and its 1:42 habit: one press, its most pressed time)
            tops[hit] = [x for i, x in enumerate(xs) if x[2] >= xs[0][2] - noise
                         and x[0] not in {y[0] for y in xs[:i]}][:2]
        lead_names = list(dict.fromkeys(x[0] for xs in tops.values() for x in xs))
        answered = {(x[0], x[1]) for xs in tops.values() for x in xs}  # what the chart draws full
        # one press answering either of two hits (Aura Mastery at 0:36 for some, 1:19 for others) is said once
        by_press: dict[tuple, list] = {}
        for hit, xs in sorted(tops.items()):
            if len(xs) == 1:
                by_press.setdefault((xs[0][0], xs[0][3]), []).append((hit, *xs[0][1:3], xs[0][4]))
            else:
                by_press[(hit,)] = xs

        def which(n: str, press: float, c) -> str:
            """Which press of the kill: "their first Divine Hymn" (2 a kill), "their Rewind" (one)."""
            k = sorted(c.times).index(press) if press in c.times else 0
            nth = ("first", "second", "third", "fourth")[k] if round(c.per_kill) > 1 and k < 4 else ""
            return f"their {nth + ' ' if nth else ''}{e(_shown(n))}"

        def ramp_of(c, t: float, hit: float) -> str:  # Evangelism 16 s ahead: the ramp is the answer
            return ", a ramp ahead of it" if c.ramp and hit - t >= RAMP[0] else ""

        def clause(key: tuple, ps: list) -> tuple[float, str]:
            if len(key) == 1:  # two cooldowns as common for one hit
                return key[0], (f"for the {_mmss(key[0])} hit, " + _and(
                    [f"{_pct(sp)} press {e(_shown(n))} (about {_mmss(t)}{ramp_of(c, t, key[0])})" for n, t, sp, _p, c in ps]))
            n, press = key
            if len(ps) == 1:
                hit, t, sp, c = ps[0]
                return hit, f"for the {_mmss(hit)} hit, {_pct(sp)} press {e(_shown(n))} (about {_mmss(t)}{ramp_of(c, t, hit)})"
            return ps[0][0], (f"{which(n, press, ps[0][3])} goes on " + _and(
                [f"the {_mmss(hit)} hit ({_pct(sp)}, about {_mmss(t)})" for hit, t, sp, _c in ps], "or"))
        # a ramp button answering several hits is one clause (Evangelism thrice in a row read as a list)
        ramps: dict[str, list] = {}
        for k, ps in by_press.items():
            if len(k) == 2 and len(ps) == 1 and ps[0][3].ramp and ps[0][0] - ps[0][1] >= RAMP[0]:
                ramps.setdefault(k[0], []).append((k, ps[0]))
        ramps = {n: sorted(kps, key=lambda x: x[1]) for n, kps in ramps.items() if len(kps) > 1}
        merged = {k for kps in ramps.values() for k, _p in kps}
        ramps = {n: [p for _k, p in kps] for n, kps in ramps.items()}
        answers = [x for _t, x in sorted(
            [clause(k, ps) for k, ps in by_press.items() if k not in merged]
            + [(ps[0][0], f"{e(_shown(n))} is their ramp ahead of the {_and([_mmss(p[0]) for p in ps])} hits: "
                          + ", ".join(f"{_pct(sp)} about {_mmss(t)}" for _hit, t, sp, _c in ps))
               for n, ps in ramps.items()])]
        # a ramp's later presses made as soon as it is back still land ahead of hits (Disc's Evangelism 1:42 and
        # 3:15 on its 90 s cooldown): said as such, no answer, so a timer the boss and the button share is plain
        for c in heals:
            later = [(t, m) for t in sorted({*c.times, *c.alt}) if c.ramp and t in c.back
                     for m in [min((x for x in shown if x.t > t), key=lambda x: x.t - t, default=None)]
                     if m is not None and RAMP[0] <= m.t - t <= RAMP[1]]
            if later:
                answers.append(f"their next {e(_shown(c.name))} comes back from cooldown "
                               + _and([f"{int(m.t - t)} s ahead of the {_mmss(m.t)} hit (about {_mmss(t)})"
                                       for t, m in later]))
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
            return landed_in(m, h.cooldowns)
        # each hit with its own bracket: "the 2:10 hit, nor the 3:40 hit (35% have...)", never one bracket read
        # as covering both
        said_each = [f"the {b} hit{landed(b)}" for b in bare]
        bare_said = said_each[0] + "".join(f", nor {x}" for x in said_each[1:]) if said_each else ""
        lead = (f"<p class='lead'>Big raid damage at {hits}.{long}{from_dispel}"
                + (f" Among the top {e(h.spec)}s, {'; '.join(answers)}." if answers else "")
                + (f" No cooldown is kept for {bare_said}." if bare else "") + "</p>")
    svg = curve_svg(h.curve, h.moments, h.phases, "Raid damage taken over the fight, and the top players' healing "
                    "cooldowns", heals, set(lead_names), answered)
    fight = ([lead] if lead else []) + [
        f"<h2>The raid damage, and its big moments</h2><div class='card'>{svg}<p class='small muted'>Raid "
        f"damage taken per second, median of {h.raid_kills or 'the top'} kills; "
        + ("under it, the cooldowns the lead names (an outline: another press of the same button). " if lead_names
           else "no cooldown is kept for these hits, so none is drawn. ")
        + "A dot is a big moment, "
        + ("named after what does most of the raid's damage there"
           if h.named_by_damage else "named after the boss cast just before it (&quot;after X&quot;: 8 to 30 s "
           "before, matched by timing)") + f".</p><ul class='hl2'>"
        f"{moments_html(h.moments, 'raid damage') or '<li>No big moment: steady raid damage.</li>'}</ul></div>",
        f"<h2>Your long cooldowns, where the top {e(h.spec)}s press them</h2><ul class='hl2'>"
        f"{cooldowns_html(sorted((c for c in heals if _external(c.spell_id) != 'protective'), key=_rank(lead_names)), answered) or '<li>Not enough top players in the corpus yet.</li>'}</ul>"]
    rare_kept = [c for c in h.rare if c not in utility]
    rare = [c for c in rare_kept if c not in items and not is_defensive(c.spell_id, c.name)
            and _external(c.spell_id) != "protective"]  # the others go to their own section
    rare_ext = [c for c in rare_kept if c not in items and _external(c.spell_id) == "protective"]
    rare_def = [c for c in rare_kept if c not in items and c not in rare_ext and is_defensive(c.spell_id, c.name)]
    if rare:  # a big cooldown the top players skip is information too (Healing Tide Totem: 3 kills in 100)
        fight.append(f"<p class='small muted'>Fewer than half of the top {e(h.spec)}s press "
                     + ", ".join(f"{e(c.name)} ({c.users:.0%}, {_and([_mmss(t) for t in c.times]) or 'no shared moment'})"
                                 for c in rare) + " on this boss.</p>")
    # the rule, once, under the long cooldowns and their "fewer than half" line (Zephyr's read as part of it)
    fight.append("<p class='small muted'>Only the lead ties a press to a hit; a button on cooldown, cast on another "
                 "player, used while moving or a trinket says why it is not. A time is shown when a quarter of those who "
                 "press the button share it; its share is of all the top players.</p>")
    exts = [c for c in heals if _external(c.spell_id) == "protective"]

    def fewer(cs: list) -> str:
        return ("<p class='small muted'>Fewer than half of them press "
                + ", ".join(f"{e(c.name)} ({c.users:.0%}, {_and([_mmss(t) for t in c.times]) or 'no shared moment'})"
                            for c in cs) + ".</p>") if cs else ""
    if exts:  # cast on another player: their own group, apart from the raid cooldowns
        fight.append(f"<h2>Your externals{f', where the top {e(h.spec)}s cast them' if any(c.times for c in exts) else ''}"
                     f"</h2><ul class='hl2'>"
                     f"{cooldowns_html(exts, answered)}</ul>{fewer(rare_ext)}")
    elif rare_ext:  # Pain Suppression at 34%: still an external, never filed with the defensives
        fight.append(f"<h2>Your externals</h2><p class='small muted'>Fewer than half of the top {e(h.spec)}s cast one here: "
                     + ", ".join(f"{e(c.name)} ({c.users:.0%}, {_and([_mmss(t) for t in c.times]) or 'no shared moment'})"
                                 for c in rare_ext) + ".</p>")
    if defs or rare_def:
        fight.append(f"<h2>Your defensives</h2><ul class='hl2'>{cooldowns_html(defs, answered)}</ul>{fewer(rare_def)}")
    if items:
        fight.append(f"<h2>On-use trinkets</h2><ul class='hl2'>{cooldowns_html(items, answered)}</ul>")
    potions = h.potions or [c for c in h.cooldowns if _item(c.spell_id) and c not in items]  # as the tank's
    if potions:
        fight.append(f"<h2>Consumables</h2><ul class='hl2'>{cooldowns_html(potions, set())}</ul>")
    if utility:
        fight.append("<p class='small muted'>Also pressed, no healing cooldown: "
                     + ", ".join(f"{e(_shown(c.name))} ({_pct(c.users)} of them, "
                                 f"{_and([_mmss(t) for t in c.times]) or 'no shared moment'})" for c in utility)
                     + ".</p>")
    n_kills = h.role_kills or h.kills
    change = [build_lead(h.builds, h.spec, h.split_players or h.kills, h.split)]
    change.append(talents_html(h.builds, h.split_players or h.kills, f"{h.spec}s", h.hero))
    if h.split:
        change.append(split_html(h.split, h.split_players, h.spec, h.split_wide))
    trk = trinkets_html(h.trinkets) or "<li>No gear yet.</li>"
    change.append(f"<h2>Trinkets the top {e(h.spec)}s play</h2><ul class='hl2'>{trk}</ul>"
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
              f"({h.dispel_kills} kills read){when}."
              + (f" {e(h.dispel_text)}" if h.dispel_text else "") + fed + "</p>"]  # the journal's other text: below
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
            stages = stages.replace(f"<b>{e(name)}</b>", f"<b>{e(name)}</b> <small class=\"muted\">(the top "
                                    f"{e(h.spec)}s dispel it {k:.1f} times a kill)</small>", 1)
        boss.append(f"<h2>Every ability{', phase by phase' if '<h3>' in stages else ''}</h2>"  # Vashnik: one phase
                    f"<div class='stages'>{stages}</div>")
    enough = {p.spec for p in h.presence if p.kills >= FEW_KILLS} if h.presence else {r.spec for r in h.roles}
    shown = sorted((r for r in h.roles if r.spec == h.spec or r.spec in enough), key=lambda r: r.spec != h.spec)
    others = roles_table(shown, h.spec) + roles_more(shown, h.spec, h.moments)
    few = [p.spec for p in h.presence if p.spec not in {r.spec for r in shown}]
    deeper_first: list[str] = [jobs_lead(shown, h.spec)]  # the cards below only: a spec too rare has no claim
    if h.presence:
        have = next((x for x in h.presence if x.spec == h.spec), None)
        if have and have.share >= 0.99:  # the corpus is your spec's top players' kills: they all have one
            line = (f"These are the top {e(h.spec)}s' kills, so every one has a {e(h.spec)} ({have.per_kill:.1f} a "
                    f"kill).")
        elif have:
            line = f"{_pct(have.share)} of the top kills bring a {e(h.spec)} ({have.per_kill:.1f} a kill when they do)."
        else:
            line = f"Few top raids bring a {e(h.spec)} on this boss."
        deeper_first.append(f"<h2>Healers in the top {e(h.spec)}s' kills</h2><p>{line} How often each other healer spec is there in the {n_kills} "
                      f"kills read, and the kills with it against those without it (a reading, not a verdict):</p>"
                      f"{presence_table(h.presence, h.spec)}")
    deeper = deeper_first + [f"<h2>What each healer spec brings here</h2><p class='small muted'>Measured on {h.role_kills} "
              f"{e(h.role_sample or 'top kills')}.{_pace(h)} {nums_note(h.roles)}</p>{others or '<p>Not measured yet.</p>'}"
              + (f"<p class='small muted'>Too few healers measured: {e(', '.join(few))}.</p>" if few else ""),
              (f"<h2>The healer compositions played most</h2>{comps_table(h.comps, n_kills)}"
               if comps_table(h.comps, n_kills) else "")]
    # every sample said once, at the top: the timings and talents, the healers' comparison; read, not simmed
    byline = (f"{e(h.character or h.spec)} &middot; {e(h.spec)} &middot; from {h.kills} top kills (median "
              f"{_mmss(h.duration)})" + (f", healers compared on {h.role_kills}" if h.role_kills else "")
              + " &middot; no healing sim")
    return sheet_page(h.boss, h.difficulty, byline, h.class_name,
                      {"fight": fight, "change": change, "boss": boss, "deeper": deeper}, theme.style("healer"),
                      UNSIMMED)
