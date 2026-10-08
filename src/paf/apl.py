"""The default APL of SimulationCraft for a spec, without a character: what the theorycrafters' rotation casts.

simc generates it for a bare character of the class and spec (with placeholder weapons: some classes need one to
start); it is kept per simc version in <data>/apl/. Used to tell the spells of the rotation (offensive cooldowns
included) from the utility and defensive ones, for every spec alike.
"""

from __future__ import annotations

import re
import subprocess

from paf.config import data_dir


def simc_tokens(class_name: str, spec: str) -> tuple[str, str]:
    """Warcraft Logs names ("DeathKnight", "BeastMastery") -> simc tokens ("deathknight", "beast_mastery")."""
    return class_name.lower(), re.sub(r"(?<!^)(?=[A-Z])", "_", spec.replace(" ", "")).lower()


def default_apl(class_name: str, spec: str) -> list[str]:
    """The action lines (actions...=...) of the spec's default APL; [] when simc cannot make one."""
    from paf.simc_install import find_simc

    exe = find_simc()
    if exe is None:
        return []
    cls, sp = simc_tokens(class_name, spec)
    path = data_dir() / "apl" / exe.parent.name / f"{cls}-{sp}.simc"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = {"creationflags": 0x08000000} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
        subprocess.run([str(exe), f"{cls}=apl", f"spec={sp}", "level=90", "main_hand=,id=2092", "off_hand=,id=2092",
                        f"save_actions={path}", "iterations=1", "max_time=10"], capture_output=True, timeout=180,
                       **flags)
        if not path.is_file():
            return []
    return [x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x.startswith("actions")]


def norm(name: str) -> str:
    """A spell's name as both simc (summon_darkglare) and Warcraft Logs (Summon Darkglare) write it."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def spells(lines: list[str]) -> set[str]:
    """The spells the APL casts (normalized names), without its keywords (variable, use_item, call_action_list...)."""
    keywords = {"variable", "useitem", "useitems", "callactionlist", "runactionlist", "potion", "snapshotstats",
                "wait", "poolresource", "invokeexternalbuff", "cancelbuff", "cancelaction"}
    out = set()
    for line in lines:
        _, _, body = line.partition("=")
        for action in body.split("/"):
            name = norm(action.split(",", 1)[0])
            if name and name not in keywords:
                out.add(name)
    return out
