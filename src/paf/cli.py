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
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
