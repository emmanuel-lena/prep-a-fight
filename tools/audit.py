"""Audit what the prep reads of every boss, so nobody has to check each sheet by hand (the owner, 2026-11-12: "I can't
go over it every time, automate it even if it is not perfect at first").

    python tools/audit.py [--difficulty heroic,mythic] [--out FILE]

For each boss of the current raid: the fight's demands from the game data (paf.encmodel, paf.demands), placed by the
logs when a corpus has the boss, and the assignments the guide offers (paf.assigns), then what looks wrong:
- a soak taken by about one player at a time (the boss's target, not a soak);
- an interrupt on a spell the journal does not say interruptible and no shield gates;
- a shield the logs never show broken;
- a deadly or high-severity ability that is neither a demand nor an assignment (what the sheet does not say);
- a unit out of reach without its unit, or a demand outside the fight.
Prints Markdown; exits 0 (a report, not a test)."""
from __future__ import annotations

import argparse
import glob
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def corpora_with(encounter_id: int, difficulty: int) -> list[sqlite3.Connection]:
    """The local corpora (any spec) that hold kills of this boss, the richest first."""
    from paf.config import data_dir

    out = []
    for p in sorted(glob.glob(str(data_dir() / "corpus-*.sqlite"))):
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            n = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                            (encounter_id, difficulty)).fetchone()[0]
        except sqlite3.Error:
            n = 0
        if n:
            out.append((n, p, con))
    return [c for _n, _p, c in sorted(out, key=lambda x: -x[0])]


def audit_boss(enc, diff_name: str, diff: int) -> tuple[list[str], list[str], list[str]]:
    """(lines describing the boss, flags: what looks wrong, notes: what the sheet leaves aside, for a look)."""
    from paf import demands, encmodel
    from paf.assigns import load_mechanics
    from paf.fight import Fight

    lines, flags, notes = [], [], []
    m = encmodel.build(enc.id, diff_name)
    wins = demands.from_model(m)
    cons = corpora_with(enc.id, diff)
    fight = None
    try:
        from paf.corpus.template import template_path

        p = template_path(enc.name, diff_name).with_suffix(".json")
        fight = Fight.load(p) if p.is_file() else None
    except Exception:  # noqa: BLE001
        fight = None
    if cons:
        wins = demands.place(wins, m, cons[0], enc.id, diff, None, fight)
    lines.append(f"{len(m.stages)} stages, {len(m.abilities)} abilities, {len(m.creatures)} units; "
                 f"{sum(1 for c in cons)} corpora with kills" + ("" if fight else "; no rebuilt fight"))
    for w in wins:
        when = ", ".join(f"{int(a // 60)}:{int(a % 60):02d}" for a, _b in w.spans[:5]) or "unplaced"
        lines.append(f"- {w.kind} **{w.label}**{' on ' + w.unit if w.unit else ''} ({when}): {w.detail}")
        if w.kind == "shield" and cons and not w.spans:
            read = cons[0].execute("SELECT COUNT(*) FROM sqlite_master WHERE name='shield_status'").fetchone()[0] and \
                cons[0].execute("SELECT COUNT(*) FROM shield_status s JOIN fight f USING(report, fight_id) "
                                "WHERE f.encounter_id=? AND f.difficulty=?", (enc.id, diff)).fetchone()[0]
            if read:
                flags.append(f"shield {w.label} never seen broken in {read} kills read")
            else:
                notes.append(f"shield {w.label}: not read in the logs yet (read on the next prep)")
        if w.kind == "adds" and not w.spans:
            notes.append(f"adds {w.label}: not in the rebuilt fight (not hit by the top players, or not prepared)")
        if w.kind == "immune" and not w.unit:
            flags.append(f"{w.label}: out of reach, but whose unit?")
        if fight and any(b > fight.duration + 5 for _a, b in w.spans):
            flags.append(f"{w.label}: a window past the fight's end")
    said = {w.spell for w in wins} | {a.parent for a in m.abilities if a.spell in {w.spell for w in wins}}
    mechs = []
    for con in cons:
        try:
            mechs = load_mechanics(con, enc.id, diff, "")
        except Exception:  # noqa: BLE001 - a corpus without mechanics
            mechs = []
        if mechs:
            break
    for x in mechs:
        sid = int(x.key.split(":")[1])
        per = x.players_per_kill / max(1, len(x.times))
        kind = "kick" if x.kind == "interrupt" else "soak"
        lines.append(f"- assignment {kind} **{x.name}** at "
                     + ", ".join(f"{int(t // 60)}:{int(t % 60):02d}" for t in x.times[:6])
                     + f" (~{per:.1f} players each time, {x.cost:g} s moving)")
        said.add(sid)
        if kind == "soak" and per < 1.5:
            flags.append(f"soak {x.name}: ~{per:.1f} player each time, the boss's target more likely")
        if kind == "kick":
            a = m.ability(sid)
            if a is not None and "interruptible" not in a.flags and not any(
                    w.kind == "shield" and m.ability(w.spell) and m.ability(w.spell).parent == sid for w in wins):
                flags.append(f"kick {x.name}: the journal does not say it is interruptible")
    names = {x.name.lower() for x in mechs}  # a soak's mark has its spell's name (Guillotine)

    def covered(a) -> bool:  # said, or what failing something said costs (Execution under Guillotine)
        while a is not None:
            if a.spell in said or a.name.lower() in names:
                return True
            a = m.ability(a.parent) if a.parent else None
        return False
    for a in m.abilities:
        if a.severity == 2 and not covered(a):  # Blizzard's high warnings, left to the boss tab
            notes.append(f"{a.name} (severity 2{', ' + a.stage if a.stage else ''}): a big mechanic, no DPS demand")
    return lines, flags, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--difficulty", default="heroic,mythic")
    ap.add_argument("--out")
    args = ap.parse_args()
    from paf.config import load_dotenv

    load_dotenv()
    from paf import settings
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    out = ["# What the prep reads of every boss", ""]
    total = 0
    for enc in raid_encounters(WCLClient()):
        for diff_name in args.difficulty.split(","):
            diff = settings.DIFFICULTIES.get(diff_name, 4)
            try:
                lines, flags, notes = audit_boss(enc, diff_name, diff)
            except Exception as ex:  # noqa: BLE001 - one boss never stops the audit
                lines, flags, notes = [], [f"audit failed: {ex}"], []
            total += len(flags)
            out += [f"## {enc.name} ({diff_name})", "", *lines, ""]
            out += (["**To check:**", *[f"- {f}" for f in flags], ""] if flags else ["Nothing to check.", ""])
            out += ["Left aside:", *[f"- {n}" for n in notes], ""] if notes else []
    out.insert(1, f"{total} things to check.")
    text = "\n".join(out)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
