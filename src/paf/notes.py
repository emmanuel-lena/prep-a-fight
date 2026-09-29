"""Boss notes: what the player knows about a boss and the logs cannot tell, applied on top of the detected
fight. One directive per line (``#`` starts a comment), unit names are matched on their beginning:

    amp Venomous Heart 2.0     # the boss takes x2.0 damage while this unit is up (overrides the measured value)
    separate Venomous Heart    # an independent priority target: its own health, not the boss's
    ignore Gore Rattle         # a mechanic, do not model it
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paf.fight import AddWave, Fight, Vulnerable


@dataclass
class Notes:
    amp: dict[str, float] = field(default_factory=dict)
    separate: set[str] = field(default_factory=set)
    ignore: set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not (self.amp or self.separate or self.ignore)


def parse_notes(text: str) -> Notes:
    n = Notes()
    for i, raw in enumerate(text.lstrip("﻿").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        verb, _, rest = line.partition(" ")
        verb, rest = verb.lower(), rest.strip()
        if verb == "amp":
            name, _, value = rest.rpartition(" ")
            try:
                n.amp[name.strip().lower()] = float(value)
            except ValueError:
                raise ValueError(f"line {i}: expected 'amp <unit> <multiplier>'") from None
        elif verb == "separate" and rest:
            n.separate.add(rest.lower())
        elif verb == "ignore" and rest:
            n.ignore.add(rest.lower())
        else:
            raise ValueError(f"line {i}: expected 'amp <unit> <x>', 'separate <unit>' or 'ignore <unit>'")
    return n


def _match(label: str, names: set[str] | dict) -> str | None:
    low = label.lower()
    return next((n for n in names if low.startswith(n)), None)


def apply_notes(fight: Fight, notes: Notes) -> tuple[Fight, list[str]]:
    """The fight with the player's corrections; returns the list of what changed."""
    f = Fight(**{**fight.__dict__})
    changes = []
    vulnerable = []
    add_waves = list(fight.add_waves)
    for v in fight.vulnerable:
        if _match(v.name, notes.ignore):
            changes.append(f"ignored {v.name} at {v.start:.0f}s")
            continue
        if _match(v.name, notes.separate):
            add_waves.append(AddWave(v.start, 1, v.duration, v.name, scalable=False))
            changes.append(f"{v.name} at {v.start:.0f}s modeled as a separate target")
            continue
        key = _match(v.name, notes.amp)
        if key:
            changes.append(f"{v.name} at {v.start:.0f}s: amp x{v.multiplier:g} -> x{notes.amp[key]:g}")
            v = type(v)(v.start, v.duration, notes.amp[key], v.name, "your boss notes")
        vulnerable.append(v)
    for v in fight.candidate_vulnerable:  # possible amps detected on the boss: only when confirmed
        key = _match(v.name, notes.amp)
        if key:
            vulnerable.append(type(v)(v.start, v.duration, notes.amp[key], v.name, "your boss notes"))
            changes.append(f"{v.name} at {v.start:.0f}s: confirmed, boss takes x{notes.amp[key]:g} damage")
    kept_waves = []
    for w in add_waves:
        if _match(w.name, notes.ignore):
            changes.append(f"ignored {w.name} at {w.time:.0f}s")
            continue
        key = _match(w.name, notes.amp) if not w.scalable else None
        if key:  # a separate unit that actually shares the boss's health with a damage amp
            vulnerable.append(Vulnerable(w.time, w.lifetime, notes.amp[key], w.name, "your boss notes"))
            changes.append(f"{w.name} at {w.time:.0f}s: shares the boss's health, x{notes.amp[key]:g}")
            continue
        kept_waves.append(w)
    f.vulnerable, f.add_waves = vulnerable, kept_waves
    return f, changes


def notes_template(fight: Fight) -> str:
    lines = [f"# Boss notes for {fight.name}: correct what the logs cannot tell. Uncomment / edit, then rerun.",
             "#   amp <unit> <x>      the boss takes x times the damage while this unit is up",
             "#   separate <unit>     an independent priority target (its own health)",
             "#   ignore <unit>       a mechanic, not a target",
             "#",
             "# Detected in the logs:"]
    seen = set()
    for v in fight.vulnerable:
        base = v.name.split(" (after")[0]
        if base in seen:
            continue
        seen.add(base)
        what = ("shares the boss's health (a boss-type unit)" if "(boss aura)" not in base
                else "an aura on the boss")
        if v.source.startswith("game data"):
            evidence = f"from the {v.source}: reliable."
        else:
            evidence = ("measured as the raid's damage rate on it vs on the boss: includes the cooldowns the raid "
                        "keeps for it, so the real amp is probably lower.")
        lines.append(f"#   {base}: {what}, boss damage x{v.multiplier:g} while it is up; {evidence}")
        lines.append(f"# amp {base} {v.multiplier:g}")
    for w in fight.add_waves:
        base = w.name.split(" (after")[0]
        if w.scalable or base in seen:
            continue
        seen.add(base)
        lines.append(f"#   {base}: a boss-type unit with no damage amp in the game data: modeled as a separate target "
                     "with its own health while it is up. If it shares the boss's health, write its amp:")
        lines.append(f"# amp {base} 1")
    cands: dict[str, list] = {}
    for v in fight.candidate_vulnerable:
        cands.setdefault(v.name.split(" (boss aura)")[0], []).append(v)
    for base, vs in cands.items():
        when = ", ".join(f"{int(v.start // 60)}:{int(v.start % 60):02d} ({v.duration:.0f}s)" for v in vs[:6])
        lines.append(f"#   Possible amp: the boss takes damage x{vs[0].multiplier:g} faster while it has the aura "
                     f"'{base}' ({when}). Not simulated: raid cooldowns can explain it too. If it really is a damage "
                     f"amp, uncomment and set the real value:")
        lines.append(f"# amp {base} {vs[0].multiplier:g}")
    return "\n".join(lines) + "\n"


def notes_path(fight_json: Path) -> Path:
    return fight_json.with_suffix(".notes.txt")


def refresh_notes(fight_json: Path, fight: Fight) -> Path:
    """Write the notes file: the detected part (comments) is regenerated, the player's lines are kept."""
    p = notes_path(fight_json)
    mine = []
    if p.is_file():
        mine = [line for line in p.read_text(encoding="utf-8-sig").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    p.parent.mkdir(parents=True, exist_ok=True)
    text = notes_template(fight)
    if mine:
        text += "\n# Your notes:\n" + "\n".join(mine) + "\n"
    p.write_text(text, encoding="utf-8")
    return p


def with_notes(fight: Fight, fight_json: Path, verbose: bool = False) -> Fight:
    """The fight with the boss notes next to its JSON applied (unchanged if there are none)."""
    p = notes_path(fight_json)
    if not p.is_file():
        return fight
    notes = parse_notes(p.read_text(encoding="utf-8-sig"))
    if notes.empty:
        return fight
    out, changes = apply_notes(fight, notes)
    if verbose:
        for c in changes:
            print(f"  boss notes: {c}")
    return out


def load_fight(fight_json: Path, verbose: bool = False) -> Fight:
    """Load a fight template with the player's boss notes applied. Save calibrations on the raw template
    (Fight.load), never on this corrected copy."""
    return with_notes(Fight.load(fight_json), fight_json, verbose)
