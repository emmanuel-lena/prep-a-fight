"""The Gear tool by target count (#43; the owner, 2026-11-12: "if single target wear this, if 2 targets this gear and
these talents, if 3+ this"): no boss, a training dummy for each count, and for each the talents then the set.

1. The talent builds on each dummy: yours, the one SimulationCraft ships (its rotation is written for it), and the top
   players' two most played on every boss your corpus holds (paf.talent_sim.compare: one sim per dummy, every build
   a profileset). A build is taken only beyond the noise; else yours stays.
2. Top Gear on your bags and vault on each dummy, with that dummy's talents (paf.topgear.run_topgear).

The dummies stand all fight (simc's Patchwerk with desired_targets): a raid's two bosses or a council more than
short add waves. "3+" is simmed on 5 targets."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from paf.talent_sim import Build

COUNTS = ((1, "1 target"), (2, "2 targets"), (5, "3+ targets"))  # 3+: simmed on 5
TOPS_PER_BOSS = 2  # the top players' builds kept per boss of the corpus
MAX_BUILDS = 10  # builds simmed at most (yours aside)


@dataclass
class Count:
    targets: int
    label: str

    @property
    def fight(self) -> str:  # a folder name too: no comma or colon (paf.cli._gear_fights)
        return f"dummy {self.targets} target{'s' if self.targets > 1 else ''}"

    def lines(self, secs: int) -> list[str]:
        return ["fight_style=Patchwerk", f"max_time={secs}", f"desired_targets={self.targets}"]


def with_talents(profile_text: str, code: str) -> str:
    """The profile with another build (its talents= line replaced, or added)."""
    if re.search(r"^talents=", profile_text, re.M):
        return re.sub(r"^talents=.*$", f"talents={code}", profile_text, count=1, flags=re.M)
    return profile_text.rstrip() + f"\ntalents={code}\n"


def own_code(profile_text: str) -> str:
    m = re.search(r"^talents=(\S+)", profile_text, re.M)
    return m.group(1) if m else ""


def corpus_builds(con: sqlite3.Connection, spec: str, bosses: dict[int, str], fetch=None) -> list[Build]:
    """The top players' most played builds on each boss of the corpus (the bosses you prepared), one per talent
    set, labelled by the boss where the most top players play it. `fetch(builds)` reads their import strings."""
    from paf.talent_sim import top_builds

    by_key: dict[frozenset[int], Build] = {}
    pairs = con.execute("SELECT encounter_id, difficulty, COUNT(*) n FROM fight WHERE status='done' "
                        "GROUP BY encounter_id, difficulty ORDER BY difficulty DESC, n DESC").fetchall()
    for enc, diff, _n in pairs:
        try:
            got = top_builds(con, enc, diff, spec, n=TOPS_PER_BOSS)
        except sqlite3.Error:
            continue
        if fetch is not None:
            fetch(got)
        for b in got:
            if not b.code:
                continue
            b.label = f"top players on {bosses.get(enc, f'boss {enc}')}"
            if b.key not in by_key or b.count > by_key[b.key].count:
                by_key[b.key] = b
    return sorted(by_key.values(), key=lambda b: -b.count)[:MAX_BUILDS]


def decoded(code: str, tree_id: int | None, label: str) -> Build | None:
    """A build from its import string (SimulationCraft's, yours), its talents read for the swaps."""
    from paf.talents import TalentError, decode, taken

    if not code or tree_id is None:
        return None
    try:
        _spec, choices = decode(code, tree_id)
    except (TalentError, ValueError, IndexError):
        return None
    return Build(frozenset(taken(choices)), code=code, label=label)


def candidates(profile_text: str, cls: str, tops: list[Build], shipped: str | None) -> list[Build]:
    """Yours first (the baseline: the sims' gains are over it), then SimulationCraft's, then the top players'."""
    from paf.talents import tree_for_entries

    tree_id = tree_for_entries(sorted(tops[0].key)) if tops else None
    if tree_id is None:
        from paf import talent_tree

        tree = talent_tree.load(cls)
        tree_id = tree_for_entries(list(tree.talents)) if tree else None
    out: list[Build] = []
    for b in (decoded(own_code(profile_text), tree_id, "your build"),
              decoded(shipped or "", tree_id, "SimulationCraft's build"), *tops):
        if b is not None and b.key and all(b.key != x.key for x in out):
            out.append(b)
    return out


def best_rows(tc, counts: list[Count]) -> dict[str, object]:
    """Each dummy's build: the best beyond the noise (two sims of this error, at two standard deviations), else
    None (keep yours)."""
    noise = 2 * 2 ** 0.5 * tc.error
    out: dict[str, object] = {}
    for c in counts:
        rows = [r for r in tc.rows if r.swaps and c.fight in r.per_fight]
        best = max(rows, key=lambda r: r.per_fight[c.fight][0], default=None)
        out[c.fight] = best if best is not None and best.per_fight[c.fight][0] > noise else None
    return out


def run(profile_text: str, pool, builds: list[Build], secs: int, run_dir: Path, *, max_combos: int = 1500,
        objective: float = 0.0, log: Callable[[str], None] = print) -> dict:
    """The talents on every dummy, then each dummy's set with its talents; `pool`: your items (paf.topgear.GearPool),
    `builds`: yours first (paf.bytargets.candidates)."""
    from paf import results, talent_sim
    from paf.topgear import FightProfile, run_topgear

    counts = [Count(n, label) for n, label in COUNTS]
    fights = {c.fight: c.lines(secs) for c in counts}
    out: dict = {"length": secs, "counts": []}
    picks: dict[str, object] = {}
    tc = None
    if len(builds) > 1:
        log(f"== Talents: {len(builds)} builds on {len(counts)} training dummies")
        tc = talent_sim.compare(profile_text, builds, fights, run_dir / "talents")
        picks = best_rows(tc, counts) if tc else {}
        out["talent_error"] = tc.error if tc else None
    for c in counts:
        row = picks.get(c.fight)
        text = with_talents(profile_text, row.build.code) if row is not None else profile_text
        entry: dict = {"targets": c.targets, "label": c.label, "talents": None}
        if row is not None:
            entry["talents"] = {"label": row.build.label, "players": row.build.count, "code": row.build.code,
                                "gain": row.per_fight[c.fight][0],
                                "swaps": [[list(a) if a else None, list(b) if b else None] for a, b in row.swaps]}
        if pool.candidates:
            log(f"== Gear on {c.label}" + (f", with the {row.build.label}" if row is not None else ""))
            res = run_topgear(text, pool, [FightProfile(c.fight, fights[c.fight])], run_dir / f"gear-{c.targets}",
                              objective=objective, max_combos=max_combos, log=log)
            entry["gear"] = results.topgear(res, top=3)
        out["counts"].append(entry)
    return out


def summary(out: dict) -> list[str]:
    """The answer as lines, for the log (the page draws the cards)."""
    lines = []
    for c in out.get("counts", []):
        t = c.get("talents")
        g = (c.get("gear") or {}).get("rows") or []
        err = (c.get("gear") or {}).get("error") or 0.2
        talents = (f"talents of the {t['label']} {t['gain']:+.1f}%" if t else "your talents")
        gear = ("; ".join(f"{x['slot']}: {', '.join(i['name'] or '?' for i in x['items'])}" for x in g[0]["changes"])
                + f" {g[0]['gain']:+.1f}%") if g and g[0]["gain"] > 2 * err else "what you wear"
        lines.append(f"  {c['label']}: {talents}; {gear}")
    return lines
