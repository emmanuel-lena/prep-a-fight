"""The rebuilt fight as SimulationCraft lines to paste elsewhere (Raidbots Advanced, a local simc input): the
fight options and raid events, optionally with a cooldown plan (the whole action priority list, rules applied).
"""

from __future__ import annotations

from paf import __version__
from paf.fight import Fight


def fight_lines(title: str, fight: Fight, plan_label: str = "", apl: list[str] | None = None) -> str:
    head = [f"# prep-a-fight {__version__}: {title}, the fight rebuilt from the top players' logs",
            "# Paste these lines UNDER your /simc export (Raidbots: Advanced sim, same text box).",
            "# Do not add a fight style: fight_style=Patchwerk silently removes the raid events."]
    lines = head + one_raid_events_line(fight.to_simc())
    if apl:
        lines += ["", f"# cooldown plan: {plan_label} (the whole priority list, with the plan's rules)", *apl]
    return "\n".join(lines) + "\n"


def one_raid_events_line(lines: list[str]) -> list[str]:
    """Every raid event on one `raid_events=` line, where the first one stood: Raidbots' Advanced input joined the
    `raid_events+=/...` lines that follow one another into one event ("Unexpected parameter 'movement'"), while
    simc reads either form the same."""
    events = [ln.split("=", 1)[1].lstrip("/") for ln in lines if ln.startswith(("raid_events=", "raid_events+="))]
    if not events:
        return lines
    out, done = [], False
    for ln in lines:
        if ln.startswith(("raid_events=", "raid_events+=")):
            if not done:
                out.append("raid_events=/" + "/".join(events))
                done = True
        else:
            out.append(ln)
    return out
