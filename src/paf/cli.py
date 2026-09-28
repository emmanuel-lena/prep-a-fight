"""Command-line entry point: ``paf <command>``."""

from __future__ import annotations

import argparse
import subprocess

from paf import __version__
from paf.config import load_dotenv
from paf.simc_install import find_simc, install_nightly


def _simc_version(exe) -> str:
    out = subprocess.run([str(exe)], capture_output=True, text=True, errors="replace", timeout=60)
    first = (out.stdout or out.stderr).strip().splitlines()
    return first[0].removeprefix("Nothing to sim!").strip() if first else "?"


def cmd_setup(args: argparse.Namespace) -> int:
    exe = install_nightly(force=args.force)
    print(f"simc ready: {exe}")
    print(f"  {_simc_version(exe)}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    import os

    ok = True
    exe = find_simc(args.simc)
    if exe:
        print(f"[ok] simc: {exe}\n     {_simc_version(exe)}")
    else:
        ok = False
        print("[!!] simc not found: run `paf setup`, or pass --simc / set PAF_SIMC")
    for key in ("WCL_CLIENT_ID", "WCL_CLIENT_SECRET"):
        if os.environ.get(key):
            print(f"[ok] {key} set")
        else:
            ok = False
            print(f"[!!] {key} missing: create a client at https://www.warcraftlogs.com/api/clients")
            print("     and put it in a .env file (see README)")
    if ok:
        from paf.wcl import WCLClient, WCLError

        try:
            rl = WCLClient().rate_limit()
            print(f"[ok] Warcraft Logs API: {rl['pointsSpentThisHour']:.0f} / {rl['limitPerHour']} points "
                  f"used this hour (reset in {rl['pointsResetIn'] // 60} min)")
        except (WCLError, OSError) as e:
            ok = False
            print(f"[!!] Warcraft Logs API: {e}")
    return 0 if ok else 1


def cmd_profile(args: argparse.Namespace) -> int:
    import sys
    from pathlib import Path

    from paf.config import data_dir
    from paf.profile import parse_simc_export

    if args.file == "-":
        text, origin = sys.stdin.read(), "stdin"
    elif args.file:
        path = Path(args.file.strip('"'))
        text, origin = path.read_text(encoding="utf-8-sig", errors="replace"), str(path)
    else:
        from paf.clipboard import read_clipboard

        text, origin = read_clipboard(), "clipboard"

    p = parse_simc_export(text)
    if not (p.class_name and p.equipped):
        print(f"No /simc export found in {origin}.")
        print("In game: /simc, Ctrl+A, Ctrl+C, then run `paf profile` again (or pass the saved file).")
        return 1

    print(f"{p.name} - {p.spec} {p.class_name}  (from {origin})")
    print(f"  equipped: {len(p.equipped)} slots")
    for source, label in (("bags", "bags"), ("vault", "great vault"), ("linked", "linked")):
        items = p.by_source(source)
        if items:
            print(f"  {label}: {len(items)} item(s)")
            for i in items:
                ilvl = f" ({i.ilvl})" if i.ilvl else ""
                print(f"    {i.slot:<10} {i.name or i.item_id}{ilvl}")
    if "main_hand" in p.equipped and "off_hand" not in p.equipped:
        print("  note: no off-hand equipped. If you play 1H + off-hand, redo /simc with it equipped.")

    dest = data_dir() / "profiles"
    dest.mkdir(parents=True, exist_ok=True)
    body = text.replace("\r\n", "\n")
    (dest / "current.simc").write_text(body, encoding="utf-8")
    print(f"Saved as the current profile: {dest / 'current.simc'}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    from paf import settings

    if args.key and args.value is not None:
        try:
            v = settings.set_value(args.key, args.value)
        except (KeyError, ValueError) as e:
            print(e)
            return 1
        print(f"{args.key} = {v}")
        return 0
    values = settings.load()
    keys = [args.key] if args.key else list(settings.SETTINGS)
    for k in keys:
        if k not in settings.SETTINGS:
            print(f"unknown setting {k!r}")
            return 1
        s = settings.SETTINGS[k]
        choices = f" ({'/'.join(s.choices)})" if s.choices else ""
        print(f"{k:<12} = {values[k]!s:<12} {s.help}{choices}")
    return 0


def _encounter_and_difficulty(args: argparse.Namespace):
    from paf import settings
    from paf.encounters import find_encounter
    from paf.wcl import WCLClient

    client = WCLClient()
    enc = find_encounter(client, args.boss)
    diff_name = (args.difficulty or settings.get("difficulty")).lower()
    return client, enc, diff_name, settings.DIFFICULTIES[diff_name]


def cmd_corpus(args: argparse.Namespace) -> int:
    from paf import settings
    from paf.corpus import db
    from paf.corpus.collect import collect, enumerate_kills, store_ranked

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    cls, spec = settings.get("class"), settings.get("spec")
    count = args.kills or settings.get("corpus_size")
    con = db.connect()

    brackets: list[int | None] = [None]
    cohort = "top"
    pages = None
    if args.ilvl:
        b = enc.bracket_for_ilvl(args.ilvl)
        if b is None:
            print("This zone has no item level brackets; using the top cohort.")
        else:
            brackets = [x for x in (b - 1, b, b + 1) if x >= 1]
            cohort = f"ilvl{args.ilvl:g}"
            pages = [1, 3, 6, 10]
    print(f"{enc.name} ({enc.zone_name}), {diff_name}: collecting {count} {spec} {cls} kills, cohort {cohort}")
    kills = enumerate_kills(client, enc, diff, cls, spec, count=count, brackets=brackets, pages=pages,
                            region=settings.get("region"))
    new = store_ranked(con, enc, diff, cohort, kills)
    print(f"  {len(kills)} ranked kills found ({new} new)")
    if len(kills) < min(20, count):
        lower = {"mythic": "heroic", "heroic": "normal", "normal": "lfr"}.get(diff_name)
        hint = f" Try --difficulty {lower}." if lower else ""
        print(f"  Only {len(kills)} ranked {spec} kills on {diff_name}: analyses will be noisy.{hint}")
    if args.list_only:
        return 0
    if args.refetch:
        con.execute("UPDATE fight SET status='pending' WHERE encounter_id=? AND difficulty=?", (enc.id, diff))
        con.commit()
    stats = collect(client, con, enc, diff, retry_errors=args.retry)
    total = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                        (enc.id, diff)).fetchone()[0]
    print(f"Done: {stats['done']} fetched, {stats['error']} skipped; {total} kills in the corpus ({db.db_path()})")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from paf import settings
    from paf.corpus import db
    from paf.corpus.analyze import analyze, format_report

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    spec = settings.get("spec")
    con = db.connect()
    names = {}
    try:
        from paf.gamedata import talent_entry_names

        names = talent_entry_names()
    except OSError as e:
        print(f"(talent names unavailable: {e})")
    rep = analyze(con, enc.id, diff, enc.name, spec, names)
    if rep.kills == 0:
        print(f"No kills in the corpus for {enc.name} {diff_name}: run `paf corpus \"{enc.name}\"` first.")
        return 1
    print(f"[{diff_name}] " + format_report(rep, spec))
    return 0


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def cmd_template(args: argparse.Namespace) -> int:
    from paf import settings
    from paf.corpus import db
    from paf.corpus.template import build_template, template_path

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    fight, info = build_template(con, enc.id, diff, enc.name, settings.get("spec"), diff_name)
    if info.kills == 0:
        print(f"No kills in the corpus for {enc.name} {diff_name}: run `paf corpus \"{enc.name}\"` first.")
        return 1
    path = template_path(enc.name, diff_name)
    fight.save(path)
    print(f"{fight.name}: typical fight from {info.kills} kills, {_mmss(fight.duration)}")
    print(f"  bloodlust at {_mmss(fight.lust_time or 0)}; power infusion at "
          f"{', '.join(_mmss(t) for t in fight.power_infusion) or 'none'}")
    for w in fight.invulnerable:
        print(f"  boss not attackable {_mmss(w.start)}-{_mmss(w.start + w.duration)} (intermission)")
    print("  targets besides the boss:")
    for w in fight.add_waves:
        print(f"    {_mmss(w.time):>5}  x{w.count:<3} alive {w.lifetime:3.0f}s  {w.name}")
    print(f"  movement: {settings.get('spec')} players move {info.moving_share:.0%} of the fight; by phase: "
          + ", ".join(f"{n.split(':')[0]} {v:.0%}" for n, v in info.movement_by_phase))
    if fight.movement:
        print("  movement windows shared by most players: "
              + ", ".join(f"{_mmss(w.start)} ({w.duration:.0f}s)" for w in fight.movement))
    print(f"Saved: {path}\n       {path.with_suffix('.simc')}")
    print("Edit the .json to customize the fight (times, counts, lifetimes, movement), then sim it.")
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    import webbrowser

    from paf import settings
    from paf.config import data_dir
    from paf.corpus import db
    from paf.corpus.template import _slug
    from paf.corpus.timeline import build_timeline, render_html

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    tl = build_timeline(db.connect(), enc.id, diff, enc.name, diff_name, settings.get("spec"), top=args.top)
    if tl.kills == 0:
        print(f"No kills in the corpus for {enc.name} {diff_name}: run `paf corpus \"{enc.name}\"` first.")
        return 1
    out = data_dir() / "reports" / f"timeline-{_slug(enc.name)}-{diff_name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(tl), encoding="utf-8")
    print(f"{len(tl.players)} players, {len(tl.abilities)} cooldowns detected: "
          + ", ".join(a.name for a in tl.abilities))
    print(f"Report: {out}")
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


def _load_profile(path: str | None) -> tuple[str, str]:
    from pathlib import Path

    from paf.config import data_dir

    p = Path(path) if path else data_dir() / "profiles" / "current.simc"
    if not p.is_file():
        raise SystemExit("No profile: copy your /simc export and run `paf profile` (or pass --profile FILE).")
    return p.read_text(encoding="utf-8-sig"), str(p)


def cmd_sim(args: argparse.Namespace) -> int:
    from paf import simc
    from paf.corpus.template import template_path
    from paf.fight import Fight

    profile, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    fight = Fight.load(fpath)
    root = simc.new_run_dir(label=f"sim-{fpath.stem}")
    print(f"Simming {origin} on {fight.name} ({_mmss(fight.duration)}) and on a Patchwerk of the same length...")
    real = simc.run(simc.build_input(profile, fight.to_simc()), root / "fight", target_error=args.error)
    dummy = simc.run(simc.build_input(profile, ["fight_style=Patchwerk", f"max_time={simc.fmt(fight.duration)}",
                                                "desired_targets=1"]), root / "patchwerk", target_error=args.error)
    d, b = real.baseline["dps"], real.baseline.get("prioritydps")
    p = dummy.baseline["dps"]
    print(f"  Patchwerk        {p.mean:10,.0f} dps")
    print(f"  {fight.name:<16} {d.mean:10,.0f} dps total ({(d.mean / p.mean - 1):+.1%} vs Patchwerk)")
    if b:
        print(f"  {'':<16} {b.mean:10,.0f} dps on the boss ({b.mean / d.mean:.0%} of your damage)")
    print(f"Runs: {root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paf", description="prep-a-fight: prepare a boss fight from top logs.")
    p.add_argument("--version", action="version", version=f"paf {__version__}")
    p.add_argument("--simc", help="path to simc executable (default: installed nightly, PAF_SIMC, PATH)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="download the latest SimulationCraft nightly (Windows)")
    s.add_argument("--force", action="store_true", help="re-download even if already installed")
    s.set_defaults(func=cmd_setup)

    d = sub.add_parser("doctor", help="check that simc and Warcraft Logs credentials are available")
    d.set_defaults(func=cmd_doctor)

    pr = sub.add_parser(
        "profile",
        help="load your /simc export (from the clipboard, a file, or stdin) as the current profile",
    )
    pr.add_argument("file", nargs="?", help="export file (drag it onto the terminal); '-' = stdin; "
                    "default = clipboard")
    pr.set_defaults(func=cmd_profile)

    cf = sub.add_parser("config", help="show or change settings (e.g. `paf config difficulty mythic`)")
    cf.add_argument("key", nargs="?")
    cf.add_argument("value", nargs="?")
    cf.set_defaults(func=cmd_config)

    co = sub.add_parser("corpus", help="collect ranked kills of a boss from Warcraft Logs (resumable)")
    co.add_argument("boss", help="boss name (partial is fine) or encounter id")
    co.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    co.add_argument("--kills", type=int, help="number of kills (default: `paf config corpus_size`)")
    co.add_argument("--ilvl", type=float, help="cohort of players around this item level instead of the top")
    co.add_argument("--list-only", action="store_true", help="only list ranked kills, fetch nothing")
    co.add_argument("--retry", action="store_true", help="retry kills that failed before")
    co.add_argument("--refetch", action="store_true", help="fetch again kills already in the corpus")
    co.set_defaults(func=cmd_corpus)

    an = sub.add_parser("analyze", help="fight shape, add waves, who hits adds, talents (from the corpus)")
    an.add_argument("boss")
    an.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    an.set_defaults(func=cmd_analyze)

    tp = sub.add_parser("template", help="build the typical fight of a boss from the corpus (for SimC)")
    tp.add_argument("boss")
    tp.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    tp.set_defaults(func=cmd_template)

    sm = sub.add_parser("sim", help="sim your profile on the typical fight of a boss vs a Patchwerk")
    sm.add_argument("boss")
    sm.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    sm.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    sm.add_argument("--error", type=float, default=0.2, help="target error in %% (default 0.2)")
    sm.set_defaults(func=cmd_sim)

    tl = sub.add_parser("timeline", help="HTML page with the cooldown timelines of the top players (Lorrgs-like)")
    tl.add_argument("boss")
    tl.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    tl.add_argument("--top", type=int, default=25, help="players shown one per row (default 25)")
    tl.add_argument("--open", action="store_true", help="open the page in the browser")
    tl.set_defaults(func=cmd_timeline)
    return p


def main(argv: list[str] | None = None) -> int:
    import sys

    for stream in (sys.stdout, sys.stderr):  # names from logs can be CJK; never crash on a cp1252 console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
