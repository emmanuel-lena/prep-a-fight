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
import statistics as st
import subprocess
from collections import OrderedDict, defaultdict
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


DISCOVERED: set[str] = set()  # the spec's own cooldowns, found by discover_cooldowns for the current character
DISCOVER_MAX_CASTS = 6  # at most this many casts in the 5-minute probe...
DISCOVER_MIN_GAP = 40.0  # ...at least this far apart (s): a cooldown, not a rotational spell
NOT_COOLDOWNS = {"auto_attack", "snapshot_stats", "flask", "food", "augmentation", "bloodlust", "heroism",
                 "invoke_external_buff", "wait", "pool_resource", "variable", "call_action_list", "run_action_list"}


def cd_key(action: str) -> str | None:
    name = action_name(action)
    if name == "use_item":
        m = re.search(r"slot=(trinket[12]|main_hand)", action)
        if m:
            return f"use_item:{m.group(1)}"
        m = re.search(r"name=([a-z0-9_]+)", action)
        return f"use_item:{m.group(1)}" if m else None
    return name if name in TRACKED or name in DISCOVERED else None


def discover_cooldowns(profile_text: str, apl: OrderedDict[str, list[str]], run_dir: Path) -> set[str]:
    """The spec's cooldowns: actions of its priority list cast rarely and far apart in a simulated 5-minute
    pull on one target (Ascendance, Combustion, Avenging Wrath...), whatever the class."""
    names = {action_name(a) for acts in apl.values() for a in acts} - NOT_COOLDOWNS - {"use_item", "use_items"}
    events = play_by_play(profile_text, apl, Plan("discover", {}, 0, 0), Fight("probe", 300), run_dir,
                          [Cooldown(n, n, True) for n in sorted(names) if n])
    by: dict[str, list[float]] = defaultdict(list)
    for t, label in sorted(events):
        ts = by[label.replace(" ", "_")]
        if not ts or t - ts[-1] > 3.0:  # the log has the cast start and its execution: one cast
            ts.append(t)
    precombat = {action_name(a) for a in apl.get("precombat", [])}
    found = set()
    for n, ts in by.items():
        if n in precombat and len(ts) <= 1:  # a buff applied before the pull (weapon imbue, shield...)
            continue
        gaps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
        if len(ts) <= DISCOVER_MAX_CASTS and (not gaps or st.median(gaps) >= DISCOVER_MIN_GAP):
            found.add(n)
    return found


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
    sensitivity: dict[str, float] = field(default_factory=dict)  # uncertain-parameter variant -> gain %
    flags: list[str] = field(default_factory=list)  # reasons to double-check this plan

    @property
    def robust(self) -> bool:
        """The gain holds on every variant of the uncertain parameters."""
        return all(g > max(2 * self.error, 0.1) for g in self.sensitivity.values()) if self.sensitivity else True


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


def fight_variants(fight: Fight) -> dict[str, Fight]:
    """The fight with its uncertain parameters pushed to the pessimistic side of their plausible range."""
    out: dict[str, Fight] = {}
    uncertain = [v for v in fight.vulnerable if not v.source.startswith("game data")]
    if uncertain:  # amps read in the game data are exact: only the measured ones are uncertain
        f = Fight(**{**fight.__dict__})
        f.vulnerable = [v if v.source.startswith("game data")
                        else type(v)(v.start, v.duration, round(1 + (v.multiplier - 1) / 2, 2), v.name, v.source)
                        for v in fight.vulnerable]
        out["amp halved"] = f
    if any(w.scalable for w in fight.add_waves):
        f = Fight(**{**fight.__dict__})
        f.add_waves = [type(w)(w.time, w.count, round(w.lifetime * 0.75, 1), w.name, w.scalable) if w.scalable else w
                       for w in fight.add_waves]
        out["adds die 25% faster"] = f
    if fight.movement:
        f = Fight(**{**fight.__dict__})
        f.movement_scale = min(1.0, fight.movement_scale + 0.25)
        out["more movement"] = f
    return out


def sensitivity(profile_text: str, apl: OrderedDict[str, list[str]], plans: list[Plan], fight: Fight,
                run_dir: Path, target_error: float = 0.1) -> None:
    """Gain of every plan on each pessimistic variant of the fight (V3: only robust plans are recommended)."""
    sets = {p.objective: apply_rules(apl, p.choice) for p in plans
            if p.objective != "secondary" and any(r.name != "default" for r in p.choice.values())}
    if not sets:
        return
    base = "\n".join([profile_text.rstrip(), *apl_lines(apl)])
    for name, variant in fight_variants(fight).items():
        res = simc.run(simc.build_input(base, variant.to_simc(), sets),
                       run_dir / f"sensitivity-{re.sub(r'[^a-z0-9]+', '-', name)}", target_error=target_error)
        by_name = {ps.name: ps for ps in res.profilesets}
        for p in plans:
            ps = by_name.get(p.objective)
            if ps is not None:
                p.sensitivity[name] = metric_delta(res, ps, p.objective)[0]


LARGE_GAIN = 5.0  # % above which a gain is shown as "check the model" rather than as a plain recommendation


def sanity_flags(plan: Plan, alignment: list, validation: float | None = None) -> list[str]:
    """V2: reasons to double-check a plan before following it.

    validation: simulated / real DPS of the top players on this fight (paf validate). A large gain is only
    flagged when something else is shaky: fight not validated (or off by more than 10%), gain not robust,
    or the plan contradicts what the top players do."""
    flags = []
    for variant, g in plan.sensitivity.items():
        if g <= max(2 * plan.error, 0.1):
            flags.append(f"not robust: {g:+.1f}% if {variant}")
    held = {}
    for a in alignment:
        key = re.sub(r"[^a-z0-9]+", "_", a.ability.lower()).strip("_")
        if a.units_cover and a.in_units > a.units_cover * 1.5 and a.in_units - a.units_cover > 0.1:
            held[key] = "the secondary target / vulnerability windows"
        elif a.in_adds > a.adds_cover * 1.5 and a.in_adds - a.adds_cover > 0.1:
            held[key] = "add waves"
    for key, rule in plan.choice.items():
        tops = held.get(key)
        if not tops or rule.name == "default":
            continue
        for_adds = rule.name.startswith(("hold_adds", "add_waves"))
        for_units = rule.name.startswith(("hold_vulnerable", "vulnerable_windows", "secondary_targets"))
        if (for_adds and "secondary" in tops) or (for_units and tops == "add waves"):
            flags.append(f"{key}: the plan keeps it for {'add waves' if for_adds else 'the vulnerability windows'}, "
                         f"the top players keep it for {tops}")
    validated = validation is not None and abs(validation - 1) <= 0.1
    if plan.gain > LARGE_GAIN and (flags or not validated):
        why = "fight not validated on the top players (paf validate)" if not validated else "see the other checks"
        flags.insert(0, f"large gain ({plan.gain:+.1f}%): {why}")
    return flags


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
                   capture_output=True, cwd=run_dir, timeout=600, **simc.LOW_PRIORITY)
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


def adjust_alignment(alignment: list[Alignment], default_timeline: list[tuple[float, str]],
                     fight: Fight) -> list[Alignment]:
    """Compare the top players to what the default priority list does in the sim, not to random casts:
    a cooldown cast on cooldown by the APL can land in add waves more often than their coverage (AoE
    conditions), which is not "holding" it. The coverages are raised to the APL's own shares."""
    adds = [(w.time, w.lifetime) for w in fight.add_waves if w.scalable]
    units = [(w.time, w.lifetime) for w in fight.add_waves if not w.scalable]
    units += [(v.start, v.duration) for v in fight.vulnerable]

    def inside(t: float, ws: list[tuple[float, float]]) -> bool:
        return any(a - 2 <= t <= a + length for a, length in ws)

    by: dict[str, list[float]] = {}
    for t, label in default_timeline:
        if t > 5:
            by.setdefault(re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_"), []).append(t)
    out = []
    for a in alignment:
        key = re.sub(r"[^a-z0-9]+", "_", a.ability.lower()).strip("_")
        times = by.get(key)
        if not times:
            out.append(a)
            continue
        sim_adds = sum(inside(t, adds) for t in times) / len(times)
        sim_units = sum(inside(t, units) for t in times) / len(times)
        out.append(Alignment(a.ability, a.casts, a.in_adds, a.in_units, max(a.adds_cover, sim_adds),
                             max(a.units_cover, sim_units)))
    return out


MRT_FREQUENT = 8  # a cooldown cast more often than this in the pull is part of the rotation
MRT_MERGE = 5.0  # seconds: casts of the same cooldown closer than this (charges) are one line
HOLD_RULES = ("hold_", "add_waves", "secondary_targets", "vulnerable_windows", "lust_pi")
GOALS = {"boss": "boss damage", "total": "total damage (pad)", "secondary": "burst", "adds": "damage to adds"}


def _short_context(fight: Fight, t: float) -> str:
    ctx = re.sub(r" \((after [^)]*|boss aura)\)", "", fight_context(fight, t))
    return ", ".join(c for c in ctx.split(", ") if c and c != "move soon")


def mrt_note(boss: str, plan: Plan, fight: Fight, names: dict[str, str] | None = None) -> str:
    """A note for Method Raid Tools: the casts that matter, one line per moment ({time:m:ss} timers from the
    pull). Rotational cooldowns are left out unless the plan holds them; charges cast together are one cast;
    cooldowns cast at the same moment share a line."""
    lines = [f"prep-a-fight: {boss}, cooldowns for {GOALS.get(plan.objective, plan.objective)} "
             f"({plan.gain:+.1f}%)"]
    for t, labels in plan_moments(plan, fight, names):
        ctx = _short_context(fight, t)
        lines.append(f"{{time:{int(t // 60)}:{int(t % 60):02d}}} {', '.join(dict.fromkeys(labels))}"
                     + (f" - {ctx}" if ctx else ""))
    return "\n".join(lines)


def plan_moments(plan: Plan, fight: Fight, names: dict[str, str] | None = None) -> list[tuple[float, list[str]]]:
    """(time from the pull, cooldown names) of the casts worth a reminder (see mrt_note)."""
    shown = {v.lower(): v for v in (names or {}).values()}

    def name(label: str) -> str:
        return shown.get(label.lower()) or " ".join(w if w in ("of", "the", "and") else w.capitalize()
                                                    for w in label.split())

    count: dict[str, int] = {}
    for _, label in plan.timeline:
        count[label] = count.get(label, 0) + 1
    rules = {k.replace("use_item:", "").replace("_", " "): r.name for k, r in plan.choice.items()}

    def keep(label: str, t: float) -> bool:
        if count[label] <= MRT_FREQUENT:
            return True
        # a rotational cooldown the plan holds: only its casts on the moments it is held for
        return rules.get(label, "default").startswith(HOLD_RULES) and bool(_short_context(fight, t))

    moments: list[tuple[float, list[str]]] = []
    last: dict[str, float] = {}
    for t, label in sorted(plan.timeline):
        if not keep(label, t) or t - last.get(label, -1e9) < MRT_MERGE:
            continue
        last[label] = t
        if moments and t - moments[-1][0] < 2:
            moments[-1][1].append(name(label))
        else:
            moments.append((t, [name(label)]))
    return moments


# Northern Sky Raid Tools numbers the phases of some bosses itself (its EncounterAlerts/<tier>/<Boss>.lua);
# Warcraft Logs phase n (1-based, in order) -> NSRT phase. "order": n -> n; "first": only the first phase can be placed.
# Bosses not listed: NSRT keeps phase 1
# for the whole fight, so reminder times count from the pull. Nek'zali: NSRT splits the intermission (1.5, then
# 1.75 when the second boss casts); reminders are given in 1.5, from the intermission start.
NSRT_PHASES: dict[int, dict[int, float] | str] = {
    3470: {1: 1, 2: 1.5, 3: 2},  # Nek'zali the Soulcoiler
    3429: {1: 1, 2: 2, 3: 2.5, 4: 3},  # The Coiled Altar
    3445: "order",  # Entombed Sentinels
    3497: "first",  # The Lost Explorers: its phases come back (1, 2, 1, 2...) while NSRT counts 1, 2, 3, 4
}
# NSRT phases that end at a moment Warcraft Logs does not mark: (encounter, phase) -> seconds after which a reminder
# would be cleared before firing (Nek'zali: 1.75 starts once the second boss casts, 25 s or more into 1.5)
NSRT_UNSURE_AFTER: dict[tuple[int, float], float] = {(3470, 1.5): 25.0}


def nsrt_phase(encounter_id: int, phases: list[tuple[str, float]], t: float) -> tuple[float, float]:
    """(NSRT phase, seconds since that phase started) of a time from the pull."""
    table = NSRT_PHASES.get(encounter_id)
    if not table or not phases:
        return 1, t
    starts = sorted(s for _, s in phases)
    n = max(i for i, s in enumerate(starts, 1) if s <= t) if t >= starts[0] else 1
    if table == "first":
        return (1, t) if n == 1 else (0, t)  # phase 0: cannot be placed
    ph = n if table == "order" else table.get(n)
    if ph is None:  # more Warcraft Logs phases than NSRT knows: stay in its last one
        n = max(table)
        ph = table[n]
    return ph, t - starts[n - 1]


def nsrt_note(encounter_id: int, plan: Plan, fight: Fight, phases: list[tuple[str, float]], player: str,
              spell_ids: dict[str, int], names: dict[str, str] | None = None) -> str:
    """Reminders for Northern Sky Raid Tools: one line per cooldown cast that matters (same choice as mrt_note),
    `time:<s since the phase start>;ph:<phase>;tag:<player>;spellid:<id>;dur:5`; a cooldown without a spell id
    (an item) is a text reminder."""
    lines = [f"EncounterID:{encounter_id}"]
    skipped = []
    for t, labels in plan_moments(plan, fight, names):
        ph, since = nsrt_phase(encounter_id, phases, t)
        limit = NSRT_UNSURE_AFTER.get((encounter_id, ph))
        if ph == 0 or (limit is not None and since > limit):
            skipped.append(f"{', '.join(dict.fromkeys(labels))} at {int(t // 60)}:{int(t % 60):02d}")
            continue
        for label in dict.fromkeys(labels):
            sid = spell_ids.get(label.lower())
            what = f"spellid:{sid}" if sid else f"text:{label.replace(';', ',')}"
            lines.append(f"time:{since:.1f};ph:{ph:g};tag:{player};{what};dur:5")
    if skipped:  # no time: or tag: on this line, so NSRT does not read it as a reminder
        lines.append("-- prep-a-fight: not placed (NSRT changes phase at a moment the logs do not give; see the MRT "
                     "note): " + "; ".join(skipped))
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
                 target_error: float = 0.2, log: Callable[[str], None] = print,
                 alignment: list | None = None,
                 validation: float | None = None) -> tuple[list[Plan], list[Cooldown]]:
    """alignment: what the top players do with their cooldowns (tops_alignment), to flag contradictions;
    validation: simulated / real DPS of the top players on this fight."""
    apl = parse_apl(dump_apl(profile_text, run_dir / "apl"))
    DISCOVERED.clear()
    DISCOVERED.update(discover_cooldowns(profile_text, apl, run_dir / "discover"))
    durations, used = cooldown_durations(profile_text, run_dir / "probe", apl)
    used_items = any(u not in TRACKED and u not in DISCOVERED for u in used)  # on-use items: their own name
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
    sensitivity(profile_text, apl, plans, fight, run_dir)
    if alignment:
        default_pull = play_by_play(profile_text, apl, Plan("default", {}, 0, 0), fight, run_dir, cds)
        alignment = adjust_alignment(alignment, default_pull, fight)
    for p in plans:
        p.flags = sanity_flags(p, alignment or [], validation)
        p.timeline = play_by_play(profile_text, apl, p, fight, run_dir, cds)
    return plans, cds
