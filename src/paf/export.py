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
    lines = head + fight.to_simc()
    if apl:
        lines += ["", f"# cooldown plan: {plan_label} (the whole priority list, with the plan's rules)", *apl]
    return "\n".join(lines) + "\n"
