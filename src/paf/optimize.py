"""Ideal cooldown plan for a fight: which rule each cooldown should follow, per objective.

Each cooldown of the character's APL (Ascendance, Stormkeeper, on-use trinkets, potion, racial...)
gets candidate rules built from the fight: on cooldown, hold for the next add wave, only inside add
waves, inside the attack windows of secondary targets, with lust / Power Infusion, not right before a
movement. A parallel coordinate descent picks, round after round, the best rule of every cooldown for
the objective (boss damage, total damage or damage to adds), then the result is confirmed with a
tighter error. Finally one simulated pull with the chosen rules gives the play-by-play (déroulé).
"""

from __future__ import annotations

import re
import subprocess
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from paf import simc
from paf.cdplan import action_name, apl_lines, dump_apl, parse_apl, split_if
from paf.fight import Fight
from paf.simc_install import find_simc

OBJECTIVES = ("boss", "total", "adds", "secondary")
# "secondary": damage to the secondary targets (a heart, a shield...) that the raid needs dead fast. SimC
# cannot tell them apart from adds, so it is measured on a variant of the fight where they are the only
# extra targets (see secondary_fight).


def secondary_fight(fight: Fight) -> Fight | None:
    """The fight with only its unique secondary targets as extra targets (None if it has none)."""
    units = [w for w in fight.add_waves if not w.scalable]
    if not units:
        return None
    f = Fight(**{**fight.__dict__})
    f.add_waves = units
    return f
TRACKED = ("ascendance", "stormkeeper", "ancestral_swiftness", "potion", "blood_fury", "berserking",
           "ancestral_call", "fireblood", "use_item")
LONG_COOLDOWN = 100.0  # seconds; holds of up to 60 s only make sense for long cooldowns


def cd_key(action: str) -> str | None:
    name = action_name(action)
    if name == "use_item":
        m = re.search(r"slot=(trinket[12]|main_hand)", action)
        if m:
            return f"use_item:{m.group(1)}"
        m = re.search(r"name=([a-z0-9_]+)", action)
        return f"use_item:{m.group(1)}" if m else None
    return name if name in TRACKED else None


def windows(times_lengths: list[tuple[float, float]], before: float = 2.0) -> str:
    return "|".join(f"time>={max(0.0, t - before):.0f}&time<={t + length:.0f}" for t, length in times_lengths)


@dataclass
class Rule:
    name: str
    description: str
    condition: Callable[[str | None], str | None]  # old condition -> new condition (None = no condition)


def fight_rules(fight: Fight, long_cd: bool) -> list[Rule]:
    adds = [(w.time, w.lifetime) for w in fight.add_waves if w.scalable]
    units = [(w.time, w.lifetime) for w in fight.add_waves if not w.scalable]
    buffs = [(fight.lust_time, 40.0)] if fight.lust_time is not None else []
    buffs += [(t, 15.0) for t in fight.power_infusion]

    def both(extra: str) -> Callable[[str | None], str | None]:
        return lambda old: f"({old})&({extra})" if old else extra

    rules = [Rule("default", "default SimC condition", lambda old: old),
             Rule("on_cooldown", "as soon as it is ready", lambda old: None)]
    holds = (20, 30, 45, 60) if long_cd else (10, 20, 30)
    for x in holds:
        rules.append(Rule(f"hold_adds_{x}", f"kept when adds come within {x} s",
                          both(f"raid_event.adds.up|raid_event.adds.in>{x}|fight_remains<{x}")))
    if adds:
        rules.append(Rule("add_waves", "only during add waves", both(windows(adds) + "|fight_remains<20")))
    if units:
        rules.append(Rule("secondary_targets", "only while the secondary targets are up",
                          both(windows(units) + "|fight_remains<20")))
    vuln = [(v.start, v.duration) for v in fight.vulnerable]
    if vuln:
        name = fight.vulnerable[0].name or "vulnerability"
        rules.append(Rule("vulnerable_windows", f"only while the boss takes more damage ({name})",
                          both(windows(vuln) + "|fight_remains<20")))
        for x in ((30, 60, 90) if long_cd else (15, 30)):
            rules.append(Rule(f"hold_vulnerable_{x}", f"kept when the boss becomes vulnerable within {x} s ({name})",
                              both(f"raid_event.vulnerable.up|raid_event.vulnerable.in>{x}|fight_remains<{x}")))
    if buffs:
        rules.append(Rule("lust_pi", "only with Bloodlust / Power Infusion",
                          both(windows(buffs, 1) + "|fight_remains<20")))
    if fight.movement:
        rules.append(Rule("not_before_move", "not in the 4 s before a movement",
                          both("raid_event.movement.in>4|raid_event.movement.up")))
    return rules


@dataclass
class Cooldown:
    key: str
    label: str
    long: bool
    rules: list[Rule] = field(default_factory=list)


def find_cooldowns(apl: OrderedDict[str, list[str]], fight: Fight, cd_durations: dict[str, float]) -> list[Cooldown]:
    keys: OrderedDict[str, str] = OrderedDict()
    for acts in apl.values():
        for a in acts:
            k = cd_key(a)
            if k and k not in keys:
                keys[k] = k.replace("use_item:", "").replace("_", " ")
    out = []
    for k, label in keys.items():
        long_cd = cd_durations.get(k, 120.0) >= LONG_COOLDOWN
        out.append(Cooldown(k, label, long_cd, fight_rules(fight, long_cd)))
    return out


def apply_rules(apl: OrderedDict[str, list[str]], choice: dict[str, Rule]) -> list[str]:
    """Profile lines of the APL with every chosen rule applied (whole APL, to be used as base or profileset)."""
    new_apl: OrderedDict[str, list[str]] = OrderedDict()
    for lst, acts in apl.items():
        new = []
        for a in acts:
            k = cd_key(a)
            rule = choice.get(k) if k else None
            if rule and rule.name != "default":
                head, old = split_if(a)
                cond = rule.condition(old)
                a = f"{head},if={cond}" if cond else head
            new.append(a)
        new_apl[lst] = new
    return apl_lines(new_apl)


def metric_delta(res: simc.SimResult, ps: simc.ProfilesetResult, objective: str) -> tuple[float, float]:
    """(delta %, error %) of a profileset vs the baseline for an objective."""
    b, p = res.baseline, ps.metrics
    base_err = b["dps"].error / b["dps"].mean * 100 if b["dps"].mean else 0.0
    if objective == "total" or "prioritydps" not in b or "prioritydps" not in p:
        return res.delta_pct(ps, "dps"), max(ps.dps.error / b["dps"].mean * 100, base_err)
    if objective == "boss":
        return res.delta_pct(ps, "prioritydps"), max(p["prioritydps"].error / b["prioritydps"].mean * 100, base_err)
    # "adds" and "secondary" (on the secondary-targets fight): damage not done to the main boss
    base_adds = b["dps"].mean - b["prioritydps"].mean
    adds = p["dps"].mean - p["prioritydps"].mean
    err = ((p["dps"].error ** 2 + p["prioritydps"].error ** 2) ** 0.5) / base_adds * 100 if base_adds else 0.0
    return ((adds - base_adds) / base_adds * 100 if base_adds else 0.0), err


@dataclass
class Plan:
    objective: str
    choice: dict[str, Rule]
    gain: float  # confirmed delta % vs the default APL, for the objective
    error: float
    totals: dict[str, float] = field(default_factory=dict)  # confirmed delta % for every objective
    rounds: int = 0
    timeline: list[tuple[float, str]] = field(default_factory=list)


def optimize_objective(profile_text: str, apl: OrderedDict[str, list[str]], cds: list[Cooldown], fight: Fight,
                       objective: str, run_dir: Path, *, target_error: float = 0.2, max_rounds: int = 3,
                       log: Callable[[str], None] = print) -> Plan:
    default = {c.key: c.rules[0] for c in cds}
    choice = dict(default)
    used = secondary_fight(fight) if objective == "secondary" else fight
    fight_lines = (used or fight).to_simc()
    for rnd in range(1, max_rounds + 1):
        base = "\n".join([profile_text.rstrip(), *apply_rules(apl, choice)])
        sets: dict[str, list[str]] = {}
        owner: dict[str, tuple[str, Rule]] = {}
        for c in cds:
            for i, r in enumerate(c.rules):
                if r.name == choice[c.key].name:
                    continue
                name = f"{re.sub(r'[^a-z0-9]', '_', c.key)}__{i}"
                sets[name] = apply_rules(apl, {**choice, c.key: r})
                owner[name] = (c.key, r)
        res = simc.run(simc.build_input(base, fight_lines, sets), run_dir / f"{objective}-round{rnd}",
                       target_error=target_error)
        best: dict[str, tuple[float, Rule]] = {}
        for ps in res.profilesets:
            if ps.name not in owner:
                continue
            key, rule = owner[ps.name]
            d, err = metric_delta(res, ps, objective)
            if d > 2 * err and d > best.get(key, (0.0, None))[0]:
                best[key] = (d, rule)
        if not best:
            log(f"  [{objective}] round {rnd}: no significant improvement")
            break
        for key, (_d, rule) in best.items():
            choice[key] = rule
        log(f"  [{objective}] round {rnd}: " + ", ".join(f"{k.replace('use_item:', '')} -> {r.name} ({d:+.2f}%)"
                                                       for k, (d, r) in best.items()))
    plan = Plan(objective, choice, 0.0, 0.0, rounds=rnd)
    return plan


def confirm(profile_text: str, apl: OrderedDict[str, list[str]], plans: list[Plan], fight: Fight, run_dir: Path,
            target_error: float = 0.05) -> None:
    """Measure every plan against the default APL with a tight error, for all objectives."""
    base = "\n".join([profile_text.rstrip(), *apl_lines(apl)])
    sets = {p.objective: apply_rules(apl, p.choice) for p in plans
            if any(r.name != "default" for r in p.choice.values())}
    if not sets:
        return
    res = simc.run(simc.build_input(base, fight.to_simc(), sets), run_dir / "confirm", target_error=target_error)
    by_name = {ps.name: ps for ps in res.profilesets}
    for p in plans:
        ps = by_name.get(p.objective)
        if ps is None:
            continue
        for obj in ("boss", "total", "adds"):
            d, err = metric_delta(res, ps, obj)
            p.totals[obj] = d
            if obj == p.objective:
                p.gain, p.error = d, err
    sec = secondary_fight(fight)
    if sec is not None:
        res = simc.run(simc.build_input(base, sec.to_simc(), sets), run_dir / "confirm-secondary",
                       target_error=target_error)
        by_name = {ps.name: ps for ps in res.profilesets}
        for p in plans:
            ps = by_name.get(p.objective)
            if ps is None:
                continue
            d, err = metric_delta(res, ps, "secondary")
            p.totals["secondary"] = d
            if p.objective == "secondary":
                p.gain, p.error = d, err


def play_by_play(profile_text: str, apl: OrderedDict[str, list[str]], plan: Plan, fight: Fight, run_dir: Path,
                 cds: list[Cooldown], simc_path: str | None = None, seed: int = 7) -> list[tuple[float, str]]:
    """Cooldown casts of one simulated pull with the chosen rules."""
    exe = find_simc(simc_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    inp = run_dir / f"{plan.objective}-pull.simc"
    inp.write_text(simc.build_input("\n".join([profile_text.rstrip(), *apply_rules(apl, plan.choice)]),
                                    fight.to_simc()), encoding="utf-8")
    log = run_dir / f"{plan.objective}-pull.log"
    subprocess.run([str(exe), str(inp), "iterations=1", "log=1", f"output={log}", f"seed={seed}", "threads=1"],
                   capture_output=True, cwd=run_dir, timeout=600)
    events: list[tuple[float, str]] = []
    seen: set[tuple[float, str]] = set()
    pat = re.compile(r"^(\d+\.\d+) Player '[^']+' (?:performs|schedules execute for) Action '([a-z0-9_]+)'")
    wanted = {c.key for c in cds}
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if log.is_file() else []:
        m = pat.match(line)
        if not m:
            continue
        t, name = float(m.group(1)), m.group(2)
        label = None
        if name in wanted:
            label = name
        elif name.startswith("use_item_"):
            label = name.removeprefix("use_item_")
        if label and (round(t, 1), label) not in seen:
            seen.add((round(t, 1), label))
            events.append((t, label.replace("_", " ")))
    return events


def fight_context(fight: Fight, t: float) -> str:
    notes = []
    for w in fight.add_waves:
        if w.time - 2 <= t <= w.time + w.lifetime:
            notes.append(w.name.split(",")[0] if not w.scalable else "adds")
    for v in fight.vulnerable:
        if v.start - 2 <= t <= v.start + v.duration:
            notes.append(f"{(v.name or 'boss').split(',')[0]} x{v.multiplier:g}")
    if fight.lust_time is not None and fight.lust_time <= t <= fight.lust_time + 40:
        notes.append("lust")
    for pi in fight.power_infusion:
        if pi <= t <= pi + 15:
            notes.append("PI")
    for m in fight.movement + fight.personal_movement:
        if m.start - 4 <= t < m.start:
            notes.append("move soon")
    for w in fight.invulnerable:
        if w.start <= t <= w.start + w.duration:
            notes.append("boss away")
    return ", ".join(dict.fromkeys(notes))


@dataclass
class Alignment:
    ability: str
    casts: int
    in_adds: float  # share of the top players' casts during add waves
    in_units: float  # ... during the windows of secondary targets (e.g. a heart)
    adds_cover: float  # share of the fight covered by add waves (what random casts would give)
    units_cover: float


def _cover(windows_: list[tuple[float, float]], duration: float) -> float:
    covered = set()
    for t, length in windows_:
        covered.update(range(max(0, int(t - 2)), min(int(duration), int(t + length) + 1)))
    return len(covered) / duration if duration else 0.0


def tops_alignment(timeline, fight: Fight) -> list[Alignment]:
    """Do the top players hold their cooldowns for add waves / secondary targets? (timeline: paf Timeline)"""
    adds = [(w.time, w.lifetime) for w in fight.add_waves if w.scalable]
    units = [(w.time, w.lifetime) for w in fight.add_waves if not w.scalable]
    units += [(v.start, v.duration) for v in fight.vulnerable]  # secondary targets sharing the boss's health
    adds_cover, units_cover = _cover(adds, fight.duration), _cover(units, fight.duration)

    def inside(t: float, ws: list[tuple[float, float]]) -> bool:
        return any(a - 2 <= t <= a + length for a, length in ws)

    out = []
    for ab in timeline.abilities:
        if ab.utility:
            continue
        times = [t for p in timeline.players for t in p["casts"].get(ab.id, []) if t > 5]  # skip the opener
        if len(times) < 10:
            continue
        out.append(Alignment(ab.name, len(times), sum(inside(t, adds) for t in times) / len(times),
                             sum(inside(t, units) for t in times) / len(times), adds_cover, units_cover))
    return out


def mrt_note(boss: str, plan: Plan, fight: Fight) -> str:
    """A note for Method Raid Tools / NSRT: one line per cooldown cast, with its time."""
    lines = [f"prep-a-fight {boss} ({plan.objective}: {plan.gain:+.1f}%)"]
    for t, label in plan.timeline:
        ctx = fight_context(fight, t)
        lines.append(f"{{time:{int(t // 60)}:{int(t % 60):02d}}} {label.title()}" + (f" - {ctx}" if ctx else ""))
    return "\n".join(lines)


def cooldown_durations(profile_text: str, run_dir: Path,
                       apl: OrderedDict[str, list[str]]) -> tuple[dict[str, float], set[str]]:
    """Base cooldowns (s) of the tracked actions from a quick simulated pull (median gap between casts),
    and the set of actions the character actually used (other races' racials, items not equipped... are not)."""
    fight = Fight("probe", 300)
    plan = Plan("probe", {}, 0, 0)
    events = play_by_play(profile_text, apl, plan, fight, run_dir,
                          [Cooldown(k, k, True) for k in {cd_key(a) for acts in apl.values() for a in acts} if k])
    by: dict[str, list[float]] = {}
    for t, label in events:
        by.setdefault(label.replace(" ", "_"), []).append(t)
    out = {}
    for k, ts in by.items():
        gaps = sorted(b - a for a, b in zip(ts, ts[1:], strict=False))
        if gaps:
            out[k] = gaps[len(gaps) // 2]
    return out, set(by)


def optimize_all(profile_text: str, fight: Fight, run_dir: Path, *, objectives: tuple[str, ...] = OBJECTIVES,
                 target_error: float = 0.2, log: Callable[[str], None] = print) -> tuple[list[Plan], list[Cooldown]]:
    apl = parse_apl(dump_apl(profile_text, run_dir / "apl"))
    durations, used = cooldown_durations(profile_text, run_dir / "probe", apl)
    used_items = any(u not in TRACKED for u in used)  # on-use items show up under their own name
    # use_item keys are per slot in the APL but named by item in the log: long unless proven otherwise
    cds = [c for c in find_cooldowns(apl, fight, durations)
           if (c.key in used)
           or (c.key.startswith("use_item:") and c.key.split(":")[1] in used)
           or (c.key in ("use_item:trinket1", "use_item:trinket2", "use_item:main_hand") and used_items)]
    log("Cooldowns found: " + ", ".join(f"{c.label} ({'long' if c.long else 'short'})" for c in cds))
    if secondary_fight(fight) is None:
        objectives = tuple(o for o in objectives if o != "secondary")
    plans = [optimize_objective(profile_text, apl, cds, fight, obj, run_dir, target_error=target_error, log=log)
             for obj in objectives]
    confirm(profile_text, apl, plans, fight, run_dir)
    for p in plans:
        p.timeline = play_by_play(profile_text, apl, p, fight, run_dir, cds)
    return plans, cds
