"""Cooldown plans: variants of the default action priority list (APL), compared with SimC on a fight.

A variant rewrites the conditions of the lines that use a cooldown (e.g. ``ascendance``) and redefines,
inside a profileset, every action list that contains such a line (verified to work on simc 1210-01).
"""

from __future__ import annotations

import re
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from paf import simc
from paf.simc_install import find_simc

_ACTION = re.compile(r"^actions(?:\.(?P<list>[a-z0-9_]+))?(?P<op>\+?=)/?(?P<body>.*)$")


def dump_apl(profile_text: str, run_dir: Path, simc_path: str | None = None) -> str:
    """The full default APL of the character (simc ``save_actions=``)."""
    exe = find_simc(simc_path)
    if exe is None:
        raise simc.SimcError("simc not found: run `paf setup`")
    run_dir.mkdir(parents=True, exist_ok=True)
    inp, out = run_dir / "apl_input.simc", run_dir / "apl.simc"
    inp.write_text(profile_text, encoding="utf-8")
    subprocess.run([str(exe), str(inp), "iterations=1", f"save_actions={out}"], capture_output=True,
                   cwd=run_dir, timeout=300)
    if not out.is_file():
        raise simc.SimcError("simc did not write the action list")
    return out.read_text(encoding="utf-8")


def parse_apl(text: str) -> OrderedDict[str, list[str]]:
    """{list name ('' = default list): [action strings]} in order."""
    lists: OrderedDict[str, list[str]] = OrderedDict()
    for raw in text.splitlines():
        line = raw.strip()
        m = _ACTION.match(line)
        if not m:
            continue
        name = m.group("list") or ""
        if m.group("op") == "=":
            lists[name] = []
        lists.setdefault(name, []).append(m.group("body"))
    return lists


def action_name(action: str) -> str:
    return action.split(",", 1)[0].strip()


def split_if(action: str) -> tuple[str, str | None]:
    """('ascendance,target_if=...', 'cooldown.x>1') from 'ascendance,target_if=...,if=cooldown.x>1'."""
    parts = action.split(",")
    head, cond = [], None
    for p in parts:
        if p.startswith("if="):
            cond = p[3:]
        else:
            head.append(p)
    return ",".join(head), cond


def with_condition(action: str, cond: str | None) -> str:
    head, _ = split_if(action)
    return f"{head},if={cond}" if cond else head


def snake(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "")).strip("_")


@dataclass
class Plan:
    name: str
    description: str
    rewrite: dict[str, callable]  # action name -> function(old condition) -> new condition (None = no if)


def windows_condition(times: list[float], before: float = 3.0, after: float = 12.0) -> str:
    return "|".join(f"time>={max(0.0, t - before):.0f}&time<={t + after:.0f}" for t in times)


def standard_plans(cds: dict[str, list[float]], long_cds: set[str]) -> list[Plan]:
    """cds: APL action name -> typical cast times of the top players (s)."""
    plans = [Plan("default", "the default SimC priority list", {})]
    plans.append(Plan("on_cooldown", "every tracked cooldown as soon as it is ready",
                      {a: (lambda old: None) for a in cds}))
    if long_cds:
        plans.append(Plan("hold_for_adds", "long cooldowns kept when adds come within 25 s",
                          {a: (lambda old: f"({old})&(raid_event.adds.up|raid_event.adds.in>25)" if old
                               else "raid_event.adds.up|raid_event.adds.in>25") for a in long_cds}))
    # frequent cooldowns (a cast every ~30 s) have no stable common timing: only long ones are timed
    timed = {a: t for a, t in cds.items() if t and a in long_cds}
    if timed:
        plans.append(Plan("top_timings", "long cooldowns only around the times the top players use them",
                          {a: (lambda old, t=t: windows_condition(t)) for a, t in timed.items()}))
        plans.append(Plan("top_timings_apl", "long cooldowns: default conditions within the top players' windows",
                          {a: (lambda old, t=t: f"({old})&({windows_condition(t)})" if old
                               else windows_condition(t)) for a, t in timed.items()}))
        for a, t in timed.items():
            if a in long_cds:
                plans.append(Plan(f"top_timing_{a}", f"only {a} around the top players' times",
                                  {a: (lambda old, t=t: windows_condition(t))}))
    return plans


def plan_lines(apl: OrderedDict[str, list[str]], plan: Plan) -> list[str]:
    """Profileset option lines redefining the action lists changed by the plan."""
    out: list[str] = []
    for lst, actions in apl.items():
        new = []
        changed = False
        for a in actions:
            fn = plan.rewrite.get(action_name(a))
            if fn:
                _, old = split_if(a)
                a2 = with_condition(a, fn(old))
                changed |= a2 != a
                new.append(a2)
            else:
                new.append(a)
        if changed:
            key = f"actions.{lst}" if lst else "actions"
            out.append(f"{key}={new[0]}")
            out += [f"{key}+=/{a}" for a in new[1:]]
    return out


def tracked_actions(apl: OrderedDict[str, list[str]], ability_names: list[str]) -> dict[str, str]:
    """Ability names (from logs) that exist as APL actions -> action name."""
    present = {action_name(a) for acts in apl.values() for a in acts}
    out = {}
    for n in ability_names:
        s = snake(n)
        if s in present:
            out[n] = s
    return out


def apl_lines(apl: OrderedDict[str, list[str]]) -> list[str]:
    """The whole APL as profile lines. A profile needs explicit actions for profileset overrides of
    action lists to take effect: without them simc generates its default APL and ignores the overrides."""
    out: list[str] = []
    for lst, actions in apl.items():
        key = f"actions.{lst}" if lst else "actions"
        for i, a in enumerate(actions):
            out.append(f"{key}={a}" if i == 0 else f"{key}+=/{a}")
    return out
