"""Personal fight plan: a small text file layered on top of the boss template, and an optimizer that
finds the best timing for the actions that can be shifted.

Format, one action per line (``#`` starts a comment):

    2:45 move 6            # soak: 6 s of movement at 2:45, fixed
    5:30 move 8 shift -5..+5   # can be done up to 5 s earlier or later
    4:10 move 4 distance 20    # movement of 20 yards (SimC computes the duration)
    no boss-movement           # ignore the movement windows inferred from the top players
    lust 0:00                  # override the bloodlust time
    pi 0:20 2:30               # override Power Infusion times
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

from paf import simc
from paf.fight import Fight, Window

_TIME = r"(\d+):(\d{2})|(\d+(?:\.\d+)?)"


def parse_time(s: str) -> float:
    m = re.fullmatch(_TIME, s.strip())
    if not m:
        raise ValueError(f"bad time {s!r} (use m:ss or seconds)")
    if m.group(1) is not None:
        return int(m.group(1)) * 60 + int(m.group(2))
    return float(m.group(3))


def mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(round(t % 60)):02d}"


@dataclass
class Move:
    start: float
    duration: float = 0.0
    distance: float = 0.0
    shift_min: float = 0.0
    shift_max: float = 0.0
    line: int = 0

    @property
    def shiftable(self) -> bool:
        return self.shift_min < 0 or self.shift_max > 0


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    keep_template_movement: bool = True
    lust: float | None = None
    no_lust: bool = False
    pi: list[float] | None = None


def parse_plan(text: str) -> Plan:
    p = Plan()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip().lower()
        if not line:
            continue
        tok = line.split()
        try:
            if tok[0] == "no" and len(tok) > 1 and tok[1] in ("boss-movement", "template-movement"):
                p.keep_template_movement = False
            elif tok[0] == "lust":
                if len(tok) > 1 and tok[1] == "none":
                    p.no_lust = True
                else:
                    p.lust = parse_time(tok[1])
            elif tok[0] == "pi":
                p.pi = [parse_time(x) for x in tok[1:]]
            elif len(tok) >= 3 and tok[1] == "move":
                m = Move(parse_time(tok[0]), float(tok[2]), line=n)
                rest = tok[3:]
                while rest:
                    if rest[0] == "shift" and len(rest) > 1:
                        a, _, b = rest[1].partition("..")
                        m.shift_min, m.shift_max = float(a), float(b or a)
                        rest = rest[2:]
                    elif rest[0] == "distance" and len(rest) > 1:
                        m.distance = float(rest[1])
                        rest = rest[2:]
                    else:
                        raise ValueError(f"unknown option {rest[0]!r}")
                p.moves.append(m)
            else:
                raise ValueError("expected '<time> move <seconds> [shift a..b] [distance y]', 'lust', 'pi' "
                                 "or 'no boss-movement'")
        except (ValueError, IndexError) as e:
            raise ValueError(f"line {n}: {e}") from None
    return p


def apply_plan(fight: Fight, plan: Plan, offsets: dict[int, float] | None = None) -> Fight:
    """A copy of the template fight with the plan applied (offsets: move index -> shift in seconds)."""
    offsets = offsets or {}
    f = Fight(**{**fight.__dict__})
    f.movement = list(fight.movement) if plan.keep_template_movement else []
    for i, m in enumerate(plan.moves):
        start = max(0.0, m.start + offsets.get(i, 0.0))
        f.movement.append(Window(start, m.duration, m.distance))
    if plan.no_lust:
        f.lust_time = None
    elif plan.lust is not None:
        f.lust_time = plan.lust
    if plan.pi is not None:
        f.power_infusion = plan.pi
    return f


def plan_template(fight: Fight) -> str:
    """Starting plan file: instructions plus the fight's events as comments."""
    lines = [
        f"# Personal plan for {fight.name}. Edit, save, then run `paf plan \"<boss>\" --optimize`.",
        "# One action per line:",
        "#   2:45 move 6                 6 s of movement at 2:45 (soak, dodge, assignment...)",
        "#   5:30 move 8 shift -5..+5    same, can happen up to 5 s earlier or later: the optimizer picks",
        "#   4:10 move 4 distance 20     20 yards of movement instead of a duration",
        "#   lust 0:00 | lust none       override Bloodlust",
        "#   pi 0:20 2:30                override Power Infusion times",
        "#   no boss-movement            drop the movement windows inferred from the top players",
        "#",
        "# The fight, from the template:",
    ]
    events = [(w.time, f"adds x{w.count} for {w.lifetime:.0f}s ({w.name})") for w in fight.add_waves]
    events += [(w.start, f"boss not attackable for {w.duration:.0f}s") for w in fight.invulnerable]
    events += [(w.start, f"movement {w.duration:.0f}s (top players)") for w in fight.movement]
    for t, what in sorted(events):
        lines.append(f"#   {mmss(t):>5}  {what}")
    lines.append("")
    return "\n".join(lines) + "\n"


@dataclass
class Optimization:
    base_dps: float
    offsets: dict[int, float]
    gain_pct: float
    tried: int


def optimize(profile_text: str, fight: Fight, plan: Plan, run_dir: Path, *, step: float = 2.0,
             metric: str = "dps", target_error: float = 0.2, max_rounds: int = 3) -> Optimization:
    """Coordinate descent over the shiftable moves: each round tries every allowed offset of one move
    (as profilesets redefining the raid events), keeps the best, then moves to the next one."""
    shiftable = [i for i, m in enumerate(plan.moves) if m.shiftable]
    offsets = {i: 0.0 for i in shiftable}
    base_fight = apply_plan(fight, plan, offsets)
    fixed = [line for line in base_fight.to_simc() if not line.startswith("raid_events")]
    tried = 0
    base_dps = None
    best_gain = 0.0
    for rnd in range(max_rounds):
        improved = False
        for i in shiftable:
            m = plan.moves[i]
            n_steps = int((m.shift_max - m.shift_min) / step) + 1
            candidates = [round(m.shift_min + k * step, 1) for k in range(n_steps)]
            sets = {}
            for c in candidates:
                if c == offsets[i]:
                    continue
                trial = {**offsets, i: c}
                sets[f"m{i}_{str(c).replace('-', 'n').replace('.', 'p')}"] = \
                    apply_plan(fight, plan, trial).raid_event_lines()
            if not sets:
                continue
            current = apply_plan(fight, plan, offsets)
            res = simc.run(simc.build_input(profile_text, fixed + current.raid_event_lines(), sets),
                           run_dir / f"round{rnd}-move{i}", target_error=target_error)
            tried += len(sets)
            if base_dps is None:
                base_dps = res.baseline[metric].mean
            best = max(res.profilesets, key=lambda p: res.delta_pct(p, metric) if metric in p.metrics else -1e9)
            delta = res.delta_pct(best, metric)
            err = best.dps.error / res.baseline["dps"].mean * 100 if res.baseline["dps"].mean else 0
            if delta > max(2 * err, 0.1):
                c = next(c for c in candidates
                         if f"m{i}_{str(c).replace('-', 'n').replace('.', 'p')}" == best.name)
                offsets[i] = c
                best_gain += delta
                improved = True
        if not improved:
            break
    confirmed = best_gain
    if any(offsets.values()):
        # confirm with a tighter error: the descent picks maxima, which favours lucky noise
        zero = {i: 0.0 for i in shiftable}
        res = simc.run(simc.build_input(profile_text, fixed + apply_plan(fight, plan, zero).raid_event_lines(),
                                        {"best": apply_plan(fight, plan, offsets).raid_event_lines()}),
                       run_dir / "confirm", target_error=target_error / 4)
        confirmed = res.delta_pct(res.profilesets[0], metric) if res.profilesets else 0.0
        err = res.profilesets[0].dps.error / res.baseline["dps"].mean * 100 if res.profilesets else 0.0
        if confirmed <= 2 * err:
            offsets = zero
            confirmed = 0.0
    return Optimization(base_dps or 0.0, offsets, confirmed, tried)


def combos_count(plan: Plan, step: float = 2.0) -> int:
    counts = [int((m.shift_max - m.shift_min) / step) + 1 for m in plan.moves if m.shiftable]
    return sum(counts) if counts else 0


def all_offsets(plan: Plan, step: float = 2.0):
    """Every combination of offsets (for small plans / tests)."""
    idx = [i for i, m in enumerate(plan.moves) if m.shiftable]
    ranges = [[round(plan.moves[i].shift_min + k * step, 1)
               for k in range(int((plan.moves[i].shift_max - plan.moves[i].shift_min) / step) + 1)] for i in idx]
    for combo in itertools.product(*ranges):
        yield dict(zip(idx, combo, strict=True))
