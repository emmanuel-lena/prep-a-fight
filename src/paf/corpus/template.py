"""Build a typical fight (paf.fight.Fight) for a boss from its corpus."""

from __future__ import annotations

import math
import re
import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import KILLABLE_DEATH_RATE, _q, canonical_waves, council, fight_waves, kills_filter
from paf.fight import AddWave, Fight, Focus, Vulnerable, Window

LUST_NAMES = {"bloodlust", "heroism", "time warp", "primal rage", "fury of the aspects", "ancient hysteria",
              "netherwinds", "drums of fury", "drums of the mountain", "drums of the maelstrom",
              "feral hide drums", "thunderous drums", "timeless drums", "harrier's cry"}
POWER_INFUSION = 10060

MOVE_SPEED = 1.5  # yards/s between two consecutive casts above which the player is moving
MAX_GAP = 4.0  # seconds; longer gaps between casts are not used to infer movement
MOVE_SHARE = 0.5  # a second belongs to a movement window when at least half of the players move
MIN_MOVE = 3.0  # seconds; shorter movement windows are ignored
MERGE_GAP = 3  # seconds; movement windows closer than this are merged
BOSS_UNIT_MIN_SHARE = 0.02  # secondary boss units taking less raid damage than this are mechanics, not targets
ATTACK_GAP = 10.0  # seconds without a cast on a unit that end an attack window
FOCUS_STEP = 10  # seconds; a council's focus is read per slice of this length
FOCUS_DOMINANT = 0.6  # a player hits one council member in a slice when it gets this share of their casts
FOCUS_MIN = 20.0  # seconds; shorter focus segments are merged into their neighbours


@dataclass
class TemplateInfo:
    kills: int
    moving_share: float  # median share of the fight the ranked players spend moving
    movement_by_phase: list[tuple[str, float]] = field(default_factory=list)
    boss_units: list[AddWave] = field(default_factory=list)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def report_key(boss: str, difficulty: str) -> str:
    """Name of a boss's reports (prep-<key>.html, timeline-<key>.html...): boss, difficulty and the analyzed
    spec, so the preps of two characters never overwrite each other."""
    from paf import settings

    return f"{_slug(boss)}-{difficulty}-{_slug(settings.get('spec'))}-{_slug(settings.get('class'))}"


def moving_seconds(points: list[tuple[float, float, float]], duration: float) -> list[bool]:
    """Per-second moving flags from (t, x, y) points of one player."""
    flags = [False] * (int(duration) + 1)
    pts = sorted(p for p in points if p[1] is not None and p[2] is not None)
    for (t0, x0, y0), (t1, x1, y1) in zip(pts, pts[1:], strict=False):
        dt = t1 - t0
        if dt <= 0 or dt > MAX_GAP:
            continue
        if math.dist((x0, y0), (x1, y1)) / dt >= MOVE_SPEED:
            for s in range(int(t0), min(int(t1) + 1, len(flags))):
                flags[s] = True
    return flags


def movement_windows(per_kill: list[list[bool]], share: float = MOVE_SHARE) -> list[Window]:
    if not per_kill:
        return []
    length = min(len(f) for f in per_kill)
    frac = [sum(f[s] for f in per_kill) / len(per_kill) for s in range(length)]
    raw: list[list[int]] = []
    start = None
    for s, v in enumerate(frac + [0.0]):
        if v >= share and start is None:
            start = s
        elif v < share and start is not None:
            if raw and start - raw[-1][1] <= MERGE_GAP:
                raw[-1][1] = s
            else:
                raw.append([start, s])
            start = None
    return [Window(float(a), float(b - a)) for a, b in raw if b - a >= MIN_MOVE]


def attack_windows(con: sqlite3.Connection, where: str, params: tuple, spec: str,
                   keys: list[tuple[str, int]], exclude: set[str] = frozenset()) -> list[AddWave]:
    """Windows when secondary boss units (e.g. a heart) are attacked, from the ranked players' casts.

    Only units taking a real share of the raid's damage count; the others are mechanics.
    """
    shares = dict(con.execute(
        f"SELECT d.target, SUM(d.amount) FROM damage_by_target d JOIN fight f USING(report, fight_id) "
        f"WHERE {where} GROUP BY d.target", params).fetchall())
    total = sum(v or 0 for v in shares.values()) or 1
    units = {r[0] for r in con.execute("SELECT name FROM npc WHERE is_boss=1")
             if (shares.get(r[0]) or 0) / total >= BOSS_UNIT_MIN_SHARE} - set(exclude)
    if not units:
        return []
    casts = con.execute(
        f"SELECT c.report, c.fight_id, n.name, c.t FROM player_cast c JOIN fight f USING(report, fight_id) "
        f"JOIN ranked r USING(report, fight_id) "
        f"JOIN add_instance a ON a.report=c.report AND a.fight_id=c.fight_id AND a.actor_id=c.target_id "
        f"AND a.instance=COALESCE(c.target_instance, 1) JOIN npc n ON n.game_id=a.game_id "
        f"WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? AND c.type='cast' "
        f"AND n.name IN ({','.join('?' * len(units))}) ORDER BY c.t", (*params, spec, *units)).fetchall()
    segments: dict[tuple[str, int], list] = defaultdict(list)
    for name in units:
        per_kill: dict[tuple[str, int], list[float]] = defaultdict(list)
        for c in casts:
            if c["name"] == name:
                per_kill[(c["report"], c["fight_id"])].append(c["t"])
        for k, times in per_kill.items():
            seg_start = prev = times[0]
            for tt in times[1:] + [None]:
                if tt is None or tt - prev > ATTACK_GAP:
                    segments[k].append((seg_start, prev - seg_start + 2.0, name))
                    if tt is not None:
                        seg_start = tt
                if tt is not None:
                    prev = tt
    waves = canonical_waves([[(s, 1, d, [nm]) for s, d, nm in segments.get(k, [])] for k in keys])
    return [AddWave(w.t, 1, w.lifetime, ", ".join(w.types), scalable=False) for w in waves if w.lifetime >= 5]


def council_focus(con: sqlite3.Connection, where: str, params: tuple, spec: str, members: list[str],
                  duration: float) -> list[Focus]:
    """Which council member the ranked players hit along the fight: per slice of FOCUS_STEP s, the member most
    kills hit (support = share of the kills), consecutive slices merged."""
    casts = con.execute(
        f"SELECT c.report, c.fight_id, c.t, n.name FROM player_cast c JOIN fight f USING(report, fight_id) "
        f"JOIN ranked r USING(report, fight_id) JOIN npc_actor a ON a.report=c.report AND a.actor_id=c.target_id "
        f"JOIN npc n ON n.game_id=a.game_id WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? AND c.type='cast' "
        f"AND n.name IN ({','.join('?' * len(members))})", (*params, spec, *members)).fetchall()
    per: dict[tuple[str, int], dict[int, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for c in casts:
        per[(c["report"], c["fight_id"])][int(c["t"] // FOCUS_STEP)][c["name"]] += 1
    slices = []
    for i in range(int(duration // FOCUS_STEP) + 1):
        votes: dict[str, int] = defaultdict(int)
        seen = 0
        for kill in per.values():
            hits = kill.get(i)
            if not hits:
                continue
            seen += 1
            name, n = max(hits.items(), key=lambda kv: kv[1])
            if n / sum(hits.values()) >= FOCUS_DOMINANT:
                votes[name] += 1
        if seen and votes:
            name, n = max(votes.items(), key=lambda kv: kv[1])
            slices.append([i * FOCUS_STEP, FOCUS_STEP, name, [n / seen]])

    def joined(segs: list[list]) -> list[list]:  # consecutive segments on the same member become one
        out: list[list] = []
        for s in segs:
            if out and out[-1][2] == s[2]:
                out[-1] = [out[-1][0], s[0] + s[1] - out[-1][0], s[2], out[-1][3] + s[3]]
            else:
                out.append(list(s))
        return out

    merged = joined(slices)
    while len(merged) > 1 and min(m[1] for m in merged) < FOCUS_MIN:  # a short segment goes to its longer neighbour
        i = min(range(len(merged)), key=lambda j: merged[j][1])
        near = [j for j in (i - 1, i + 1) if 0 <= j < len(merged)]
        j = max(near, key=lambda j: merged[j][1])
        a, b = sorted((i, j))
        merged[a:b + 1] = [[merged[a][0], merged[b][0] + merged[b][1] - merged[a][0], merged[j][2], merged[j][3]]]
        merged = joined(merged)
    end = min(duration, merged[-1][0] + merged[-1][1]) if merged else 0
    out = []
    for k, (start, length, name, sup) in enumerate(merged):
        length = (end if k == len(merged) - 1 else start + length) - start
        out.append(Focus(round(start, 1), round(length, 1), name, round(st.median(sup), 2)))
    return out


def game_amp(encounter_id: int, unit_name: str, difficulty: str) -> tuple[float | None, str]:
    """Damage-taken multiplier of a unit from the game data: the Encounter Journal section named like the
    unit gives its spell, whose 'mod damage % taken' effect is the amp (e.g. Venomous Heart: +100%)."""
    from paf.gamedata import damage_taken_amp
    from paf.mechanics import encounter_sections, walk

    try:
        spells = {s.spell_id for _, s in walk(encounter_sections(encounter_id))
                  if s.spell_id and s.title.lower() == unit_name.lower()}
        for sid in sorted(spells):
            amp = damage_taken_amp(sid, difficulty)
            if amp:
                return amp, f"game data (spell {sid}: damage taken +{round((amp - 1) * 100)}%)"
    except OSError:
        pass
    return None, ""


def ability_names_all(con: sqlite3.Connection) -> dict[int, str]:
    from paf.gamedata import spell_names

    try:
        names = dict(spell_names())
    except OSError:
        names = {}
    names.update(dict(con.execute("SELECT id, name FROM ability").fetchall()))
    return names


def boss_unit_multiplier(con: sqlite3.Connection, where: str, params: tuple, boss_name: str, units: set[str],
                         units_time: float, duration: float, invulnerable_time: float, kills: int) -> float:
    """Damage amplification of secondary boss units: the raid's damage rate on them during their windows
    divided by its rate on the boss the rest of the attackable time (clamped to 1-5)."""
    if not units or units_time <= 0 or not kills:
        return 1.0
    names = {n for u in units for n in u.split(", ")}
    rows = dict(con.execute(
        f"SELECT d.target, SUM(d.amount) FROM damage_by_target d JOIN fight f USING(report, fight_id) "
        f"WHERE {where} GROUP BY d.target", params).fetchall())
    unit_dmg = sum(rows.get(n) or 0 for n in names)
    boss_dmg = rows.get(boss_name) or 0
    boss_time = duration - invulnerable_time - units_time
    if boss_dmg <= 0 or boss_time <= 0:
        return 1.0
    ratio = (unit_dmg / (kills * units_time)) / (boss_dmg / (kills * boss_time))
    return round(min(5.0, max(1.0, ratio)), 2)


def build_template(con: sqlite3.Connection, encounter_id: int, difficulty: int, boss_name: str,
                   spec: str, diff_name: str = "", title: str = "") -> tuple[Fight, TemplateInfo]:
    """boss_name: the main boss unit (paf.corpus.analyze.main_boss); title: the encounter's name."""
    where, params = kills_filter(encounter_id, difficulty)
    fights = con.execute(f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}", params).fetchall()
    keys = sorted((r["report"], r["fight_id"]) for r in fights)
    duration = st.median(r["duration_s"] for r in fights)

    # adds and secondary boss units
    rows = con.execute(
        f"SELECT a.report, a.fight_id, n.name, n.is_boss, a.t_spawn, a.t_death, a.died FROM add_instance a "
        f"JOIN npc n USING(game_id) JOIN fight f USING(report, fight_id) WHERE {where}", params).fetchall()
    death_rate: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        death_rate[r["name"]].append(r["died"])
    killable = {n for n, d in death_rate.items() if sum(d) / len(d) >= KILLABLE_DEATH_RATE}
    adds: dict[tuple[str, int], list] = defaultdict(list)
    for r in rows:
        if r["t_spawn"] is None or r["name"] not in killable or r["is_boss"]:
            continue
        adds[(r["report"], r["fight_id"])].append((r["t_spawn"], r["t_death"] - r["t_spawn"], r["name"]))
    # one timeline per add type: types spawned together can live very differently (Vashnik: Shrouded Venom ~13 s,
    # Burning Venom ~35 s, Malignant Totem ~41 s), and a mixed wave's median lifetime hid the long-lived ones
    add_waves = []
    for kind in sorted({s[2] for spawns in adds.values() for s in spawns}):
        per_kill = [fight_waves([s for s in adds.get(k, []) if s[2] == kind]) for k in keys]
        add_waves += [AddWave(w.t, max(1, round(w.count)), w.lifetime, kind) for w in canonical_waves(per_kill)]
    add_waves.sort(key=lambda w: w.time)
    # a council (several bosses with their own health): the simulated bosses are the members the player hits at once
    # (Fight.targets), so the members are neither adds nor vulnerability windows; their order is information
    members = set(council(con, encounter_id, difficulty))
    boss_waves = attack_windows(con, where, params, spec, keys, exclude=members)

    # intermissions -> the main boss is not attackable
    phases = defaultdict(list)
    for r in con.execute(f"SELECT p.* FROM phase p JOIN fight f USING(report, fight_id) WHERE {where}", params):
        phases[r["phase_id"]].append((r["t_start"], r["is_intermission"], r["name"]))
    ordered = sorted((pid, st.median(v[0] for v in vals), vals[0][1], vals[0][2]) for pid, vals in phases.items())
    from paf.corpus.units import phase_attackable

    attackable = phase_attackable(con, encounter_id, difficulty)  # measured on damage-taken graphs
    invulnerable = []
    for i, (pid, start, inter, _name) in enumerate(ordered):
        # a phase is "boss away" when the graphs show (almost) no damage on the boss; without measurements,
        # intermissions are assumed to be
        away = attackable[pid] < 0.2 if pid in attackable else bool(inter)
        if members:  # measured on one member only: another one is attackable while it is away
            away = False
        if away:
            end = ordered[i + 1][1] if i + 1 < len(ordered) else duration
            invulnerable.append(Window(round(start, 1), round(end - start, 1)))

    # lust and power infusion on the ranked players
    names = {r[0]: (r[1] or "").lower() for r in con.execute("SELECT id, name FROM ability")}
    lust_times, pi_times = [], []
    buffs = con.execute(
        f"SELECT b.report, b.fight_id, b.ability_id, b.t FROM player_buff b JOIN fight f USING(report, fight_id) "
        f"JOIN ranked r USING(report, fight_id) WHERE {where} AND b.type='applybuff' AND b.actor_id=r.actor_id "
        f"AND r.spec=? ORDER BY b.t", (*params, spec)).fetchall()
    first_lust: dict[tuple[str, int], float] = {}
    pis: dict[tuple[str, int], list] = defaultdict(list)
    for b in buffs:
        k = (b["report"], b["fight_id"])
        if names.get(b["ability_id"], "") in LUST_NAMES and k not in first_lust:
            first_lust[k] = b["t"]
        if b["ability_id"] == POWER_INFUSION:
            pis[k].append((b["t"], 15.0, "pi"))
    lust_times = list(first_lust.values())
    pi_waves = canonical_waves([fight_waves(pis.get(k, [])) for k in keys])
    pi_times = [w.t for w in pi_waves if w.support >= 0.3]

    # movement from the ranked players' trajectories
    pts: dict[tuple[str, int], list] = defaultdict(list)
    for r in con.execute(
            f"SELECT c.report, c.fight_id, c.t, c.x, c.y FROM player_cast c JOIN fight f USING(report, fight_id) "
            f"JOIN ranked r USING(report, fight_id) WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? "
            f"AND c.x IS NOT NULL", (*params, spec)):
        pts[(r["report"], r["fight_id"])].append((r["t"], r["x"], r["y"]))
    per_kill = [moving_seconds(p, duration) for p in pts.values() if len(p) > 50]
    moves = movement_windows(per_kill)
    moving_share = st.median(sum(f) / len(f) for f in per_kill) if per_kill else 0.0
    by_phase = []
    for i, (_, start, _inter, name) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else duration
        vals = [sum(f[int(start):int(end)]) / max(1, int(end) - int(start)) for f in per_kill]
        if vals:
            by_phase.append((name, st.median(vals)))

    # secondary boss units (e.g. a heart) share the boss's health: their windows become boss vulnerability
    # windows, with the damage amplification measured in the logs
    from paf.corpus.units import council_stack, trigger_casts, unit_windows

    measured, ratios = unit_windows(con, encounter_id, difficulty)
    measured = {k: [w for w in ws if w[2] not in members] for k, ws in measured.items()}
    measured = {k: ws for k, ws in measured.items() if ws}
    if measured:  # damage-taken graphs of a few kills: real windows and damage rate ratio of each unit
        waves = canonical_waves([[(s, 1, d, [nm]) for s, d, nm in kill] for kill in measured.values()])
        vulnerable = []
        ability_names = dict(con.execute("SELECT id, name FROM ability").fetchall())
        from paf.mechanics import encounter_sections, walk

        try:
            journal = {s.title.lower() for _, s in walk(encounter_sections(encounter_id))}
        except OSError:
            journal = None
        for w in waves:
            start, end, label = w.t, w.t + w.lifetime, ", ".join(w.types)
            trig = trigger_casts(con, measured, w.t, ability_names, journal)
            if trig:  # the window opens when the boss's cast ends (more precise than the damage graph)
                start = trig[1]
                label += f" (after {trig[0]})"
            amp, source = game_amp(encounter_id, w.types[0], diff_name or "heroic")
            if amp is None:
                # no damage amp in the game data: a second boss with its own health (e.g. a council member),
                # modeled as a separate target while it is up; the boss notes can turn it into an amp
                add_waves.append(AddWave(round(start, 1), 1, round(max(1.0, end - start), 1), label, scalable=False))
                continue
            vulnerable.append(Vulnerable(round(start, 1), round(max(1.0, end - start), 1), amp, label, source))
    else:  # fallback: the ranked players' casts on the unit
        mult = boss_unit_multiplier(con, where, params, boss_name, {w.name for w in boss_waves},
                                    sum(w.lifetime for w in boss_waves), duration,
                                    sum(w.duration for w in invulnerable), len(keys))
        vulnerable = [Vulnerable(round(w.time, 1), round(w.lifetime, 1), mult, w.name) for w in boss_waves]

    from paf.corpus.units import amp_candidates
    from paf.gamedata import damage_taken_amp

    candidates = []
    for name, ratio, wins, _k, aid in amp_candidates(con, encounter_id, difficulty, ability_names_all(con)):
        try:
            amp = damage_taken_amp(aid, diff_name or "heroic")
        except OSError:
            amp = None
        for t, d in wins:
            if amp:  # the game data confirms it: a real amp on the boss
                vulnerable.append(Vulnerable(round(t, 1), round(d, 1), amp, f"{name} (boss aura)",
                                             f"game data (spell {aid}: damage taken +{round((amp - 1) * 100)}%)"))
            else:
                candidates.append(Vulnerable(round(t, 1), round(d, 1), ratio, f"{name} (boss aura)",
                                             "measured in the logs, not confirmed"))

    fight = Fight(
        name=f"{title or boss_name} {diff_name}".strip(),
        duration=round(duration, 1),
        add_waves=add_waves,
        vulnerable=vulnerable,
        candidate_vulnerable=candidates,
        invulnerable=invulnerable,
        movement=moves,
        lust_time=round(st.median(lust_times), 1) if lust_times else 0.0,
        power_infusion=[round(t, 1) for t in pi_times],
        source=f"median of {len(keys)} ranked kills (paf corpus)",
        focus=council_focus(con, where, params, spec, sorted(members), duration) if members else [],
        targets=council_stack(con, encounter_id, difficulty) if members else 1,
    )
    return fight, TemplateInfo(len(keys), moving_share, by_phase, boss_waves)


def template_path(boss_name: str, diff_name: str):
    from paf.config import data_dir

    return data_dir() / "fights" / f"{_slug(boss_name)}-{diff_name}.json"


def lust_quantiles(values: list[float]) -> tuple[float, float, float]:
    return _q(values, .25), _q(values, .5), _q(values, .75)
