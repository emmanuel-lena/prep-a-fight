"""Command-line entry point: ``paf <command>``."""

from __future__ import annotations

import argparse
import subprocess
import time

from paf import __version__
from paf.config import load_dotenv
from paf.corpus.analyze import main_boss
from paf.notes import load_fight
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

    from paf import characters, settings

    c = characters.save(text)
    print(f"Saved as your character {c.name} ({c.spec} {c.class_name}), now the active one")
    print(f"Analyzed spec: {settings.get('spec')} {settings.get('class')} (its own corpus of top players)")
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


FIRST_SHEET = 100  # kills a first prep waits for (measured: the fight as with 200, talent rates within 3 points)


def _refine_later(con, enc, diff: int, sheet) -> None:
    """After a first prep from part of the corpus: a second pass of the same prep (`--refine`), detached, that
    downloads the rest of the corpus and makes the sheet again from all of it. It is a job of the app (its banner
    shows its progress; the sheet's page reloads when it is done); one per boss and difficulty."""
    import json
    import os
    import subprocess
    import sys
    import uuid

    from paf.config import data_dir

    pending = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='pending'",
                          (enc.id, diff)).fetchone()[0]
    if not pending:
        return
    folder = data_dir() / "web"
    folder.mkdir(parents=True, exist_ok=True)
    from paf.web import pid_alive

    for meta in folder.glob("job-*.json"):  # already refining this boss
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if "--refine" in m.get("args", []) and m.get("result") == str(sheet) and m.get("pid") and pid_alive(m["pid"]):
            return
    args = [x for x in sys.argv[1:] if x not in ("--refresh", "--open")] + ["--refine"]
    jid = uuid.uuid4().hex[:8]
    flags = 0x00000008 | 0x08000000 if sys.platform == "win32" else 0  # DETACHED_PROCESS, CREATE_NO_WINDOW
    with (folder / f"job-{jid}.log").open("w", encoding="utf-8") as out:
        proc = subprocess.Popen([sys.executable, "-m", "paf", *args], stdout=out, stderr=subprocess.STDOUT,
                                creationflags=flags, env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                                          "PYTHONUNBUFFERED": "1"},
                                **({} if sys.platform == "win32" else {"start_new_session": True}))
    (folder / f"job-{jid}.json").write_text(json.dumps({"args": args, "result": str(sheet), "status": "running",
                                                        "started": time.time(), "pid": proc.pid}), encoding="utf-8")
    print(f"  {pending} more kills: the full analysis runs in the background; the sheet refreshes when it is done.")


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
    from paf import settings as _settings

    # a prep the player waits for takes the whole quota; the background collection leaves the rest to the app
    full = getattr(args, "full_quota", False)
    stats = collect(client, con, enc, diff, retry_errors=args.retry, limit=getattr(args, "limit", None),
                    points_per_hour=3600 if full else _settings.get("corpus_points"))
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
    rep = analyze(con, enc.id, diff, main_boss(con, enc.id, diff, enc.name), spec, names)
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
    from paf.corpus.analyze import council
    from paf.corpus.units import fetch_boss_auras, fetch_council_stack, fetch_unit_windows

    boss = main_boss(con, enc.id, diff, enc.name)
    fetch_unit_windows(client, con, enc.id, diff, boss)  # secondary units' real windows (cheap, cached)
    if members := council(con, enc.id, diff):  # how many council members are stacked
        fetch_council_stack(client, con, enc.id, diff, members)
    fetch_boss_auras(client, con, enc.id, diff, boss)  # auras on the boss: possible damage amps
    fight, info = build_template(con, enc.id, diff, boss, settings.get("spec"), diff_name, title=enc.name)
    if info.kills == 0:
        print(f"No kills in the corpus for {enc.name} {diff_name}: run `paf corpus \"{enc.name}\"` first.")
        return 1
    path = template_path(enc.name, diff_name)
    if path.is_file():  # keep the calibrations done on the previous version
        from paf.fight import Fight

        old = Fight.load(path)
        fight.add_scale, fight.movement_scale = old.add_scale, old.movement_scale
    fight.save(path)
    print(f"{fight.name}: typical fight from {info.kills} kills, {_mmss(fight.duration)}")
    print(f"  bloodlust at {_mmss(fight.lust_time or 0)}; power infusion at "
          f"{', '.join(_mmss(t) for t in fight.power_infusion) or 'none'}")
    for w in fight.invulnerable:
        print(f"  boss not attackable {_mmss(w.start)}-{_mmss(w.start + w.duration)} (intermission)")
    for v in fight.vulnerable:
        print(f"  {_mmss(v.start)}-{_mmss(v.start + v.duration)}  {v.name}: shares the boss's health, "
              f"boss takes x{v.multiplier:g} damage ({v.source or 'measured in the logs'})")
    if fight.focus:
        print(f"  a council: {', '.join(dict.fromkeys(f.name for f in fight.focus))}, {fight.targets} of them "
              f"stacked (simulated as {fight.targets} bosses the whole fight); the top players mostly hit:")
        for f in fight.focus:
            print(f"    {_mmss(f.start):>5}-{_mmss(f.start + f.duration)}  {f.name} ({f.support:.0%} of the kills)")
    print("  targets besides the boss:")
    for w in fight.add_waves:
        print(f"    {_mmss(w.time):>5}  x{w.count:<3} alive {w.lifetime:3.0f}s  {w.name}")
    print(f"  movement: {settings.get('spec')} players move {info.moving_share:.0%} of the fight; by phase: "
          + ", ".join(f"{n.split(':')[0]} {v:.0%}" for n, v in info.movement_by_phase))
    if fight.movement:
        print("  movement windows shared by most players: "
              + ", ".join(f"{_mmss(w.start)} ({w.duration:.0f}s)" for w in fight.movement))
    print(f"Saved: {path}\n       {path.with_suffix('.simc')}")
    from paf.notes import refresh_notes

    npath = refresh_notes(path, fight)
    print(f"Boss notes (correct what the logs cannot tell, e.g. a damage amp): {npath}")
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    import webbrowser

    from paf import settings
    from paf.config import data_dir
    from paf.corpus import db
    from paf.corpus.collect import backfill_npc_actors
    from paf.corpus.template import report_key
    from paf.corpus.timeline import build_timeline, render_html

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    backfill_npc_actors(client, con, enc.id, diff)
    tl = build_timeline(con, enc.id, diff, enc.name, diff_name, settings.get("spec"), top=args.top)
    if tl.kills == 0:
        print(f"No kills in the corpus for {enc.name} {diff_name}: run `paf corpus \"{enc.name}\"` first.")
        return 1
    out = data_dir() / "reports" / f"timeline-{report_key(enc.name, diff_name)}.html"
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

    profile, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    fight = load_fight(fpath)
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


def _objective(raw: str) -> float:
    raw = raw.strip().lower()
    if raw in ("total", "pad", "dps"):
        return 0.0
    if raw in ("boss", "priority", "st"):
        return 1.0
    v = float(raw.removeprefix("mix:"))
    if not 0 <= v <= 1:
        raise argparse.ArgumentTypeError("objective must be total, boss or a boss weight between 0 and 1")
    return v


def cmd_topgear(args: argparse.Namespace) -> int:
    from paf import simc
    from paf.corpus.template import template_path
    from paf.fight import PRESETS
    from paf.gamedata import item_inventory_types, item_sets
    from paf.profile import parse_simc_export
    from paf.topgear import FightProfile, GearPool, best_set_simc, format_result, run_topgear

    profile_text, origin = _load_profile(args.profile)
    profile = parse_simc_export(profile_text)
    pool = GearPool(profile, item_inventory_types(), item_sets())
    fights: list[FightProfile] = []
    for boss in args.boss or []:
        _, enc, diff_name, _ = _encounter_and_difficulty(argparse.Namespace(boss=boss, difficulty=args.difficulty))
        fpath = template_path(enc.name, diff_name)
        if not fpath.is_file():
            print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
            return 1
        fights.append(FightProfile(fpath.stem, load_fight(fpath).to_simc()))
    for preset in args.preset or ([] if fights else ["patchwerk"]):
        fights.append(FightProfile(preset, PRESETS[preset]))
    n_cand = len(pool.candidates)
    tier = f", tier set {pool.tier_set}" if pool.tier_set else ""
    print(f"{profile.name} ({origin}): {n_cand} candidate items{tier}; fights: {', '.join(f.name for f in fights)}")
    if not n_cand:
        print("No items in bags / great vault / links: export /simc with 'Bags' ticked,")
        print("or link items in game with /simc [item].")
        return 1
    root = simc.new_run_dir(label="topgear")
    res = run_topgear(profile_text, pool, fights, root, pass1_error=args.pass1_error,
                      pass2_error=args.pass2_error, objective=args.objective, max_combos=args.max_combos,
                      min_tier=args.min_tier)
    report = format_result(res, pool, top=args.top)
    from paf import results

    results.write(root, "topgear", results.topgear(res))
    print()
    print(report)
    (root / "results.txt").write_text(report + "\n", encoding="utf-8")
    best = res.best()
    if best:
        (root / "best_set.simc").write_text(best_set_simc(pool, best), encoding="utf-8")
    print(f"\nRuns and best set: {root}")
    return 0


def _boss_fights(enc, diff_name: str) -> dict[str, list[str]]:
    """The boss template (if any) and a Patchwerk of the same length."""
    from paf import simc
    from paf.corpus.template import template_path

    fights: dict[str, list[str]] = {}
    fpath = template_path(enc.name, diff_name)
    duration = 300.0
    if fpath.is_file():
        fight = load_fight(fpath)
        fights[fpath.stem] = fight.to_simc()
        duration = fight.duration
    fights["patchwerk"] = ["fight_style=Patchwerk", f"max_time={simc.fmt(duration)}", "desired_targets=1"]
    return fights


def print_talents(tc) -> None:
    header = "  ".join(f"{n[:18]:>18}" for n in tc.fights)
    print(f"\n{'build':<12} {'players':>7} {'med.rank':>8}  {header}")
    print(f"{'your build':<12} {'':>7} {'':>8}  " + "  ".join(f"{'ref':>18}" for _ in tc.fights))
    for r in tc.rows:
        cols = []
        for f in tc.fights:
            if f not in r.per_fight:
                cols.append(f"{'n/a':>18}")
                continue
            tot, boss = r.per_fight[f]
            cell = f"{tot:+.2f}%" + (f" (boss {boss:+.1f}%)" if boss is not None else "")
            cols.append(f"{cell:>18}")
        print(f"{r.build.label:<12} {r.build.count:>7} {r.build.median_rank:>8.0f}  " + "  ".join(cols))
    print(f"\nStatistical error: about +/-{tc.error:.2f}% per value.")
    if any(r.add or r.drop for r in tc.rows):
        print("\nWhat each build changes compared to yours:")
        for r in tc.rows:
            if not r.add and not r.drop:
                print(f"  {r.build.label}: same talents as yours")
                continue
            print(f"  {r.build.label}: take {', '.join(r.add) or '-'}")
            print(f"  {'':<{len(r.build.label)}}  drop {', '.join(r.drop) or '-'}")


def cmd_talents(args: argparse.Namespace) -> int:
    from paf import settings, simc
    from paf.corpus import db
    from paf.talent_sim import compare_builds

    profile_text, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    spec = settings.get("spec")
    print(f"{enc.name} {diff_name}: most common {spec} builds simmed on your character ({origin})")
    tc = compare_builds(profile_text, db.connect(), client, enc.id, diff, spec, _boss_fights(enc, diff_name),
                        simc.new_run_dir(label="talents"), n=args.builds, target_error=args.error)
    if tc is None:
        print(f"No ranked {spec} players in the corpus for {enc.name} {diff_name}: run `paf corpus` first.")
        return 1
    print_talents(tc)
    from paf import results

    results.write(tc.run_dir, "talents", results.talents(tc, enc.name, diff_name))
    print(f"\nRuns: {tc.run_dir}")
    return 0


def print_plans(pc) -> None:
    for act, times in pc.cd_times.items():
        print(f"  {act}: top players use it at {', '.join(_mmss(t) for t in times) or '(no common timing)'}")
    print(f"\n{'plan':<26} {'total':>8} {'boss':>8}   on {pc.fight_name}")
    for p, tot, boss in pc.rows:
        print(f"{p.name:<26} {tot:+7.2f}% {boss:+7.2f}%   {p.description}")
    print(f"\nStatistical error: about +/-{pc.error:.2f}%. SimC evaluates these plans; it does not invent new ones.")


def cmd_cdplan(args: argparse.Namespace) -> int:
    from paf import settings, simc
    from paf.cdplan import compare_plans
    from paf.corpus import db
    from paf.corpus.template import template_path
    from paf.corpus.timeline import build_timeline

    profile_text, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    tl = build_timeline(db.connect(), enc.id, diff, enc.name, diff_name, settings.get("spec"), top=10_000)
    print(f"{enc.name} {diff_name}: cooldown plans for {origin}")
    pc = compare_plans(profile_text, tl, load_fight(fpath), simc.new_run_dir(label="cdplan"),
                       target_error=args.error, objective=args.objective)
    if pc is None:
        print("None of the top players' cooldowns match an action of the default APL.")
        return 1
    print_plans(pc)
    print(f"Runs: {pc.run_dir}")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    from paf import settings, simc
    from paf.calibrate import calibrate, real_boss_share
    from paf.corpus import db
    from paf.corpus.template import template_path
    from paf.fight import Fight

    profile_text, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    spec = settings.get("spec")
    target = real_boss_share(db.connect(), enc.id, diff, main_boss(db.connect(), enc.id, diff, enc.name), spec)
    if target is None:
        print("No damage data for the ranked players in the corpus.")
        return 1
    raw = Fight.load(fpath)
    fight = load_fight(fpath, verbose=True)
    print(f"Top {spec} players do {target:.0%} of their damage to {enc.name}. Calibrating the add counts...")
    cal = calibrate(profile_text, fight, target, simc.new_run_dir(label="calibrate"))
    for s, share, dps in cal.points:
        print(f"  adds x{s:<4}  boss share {share:5.1%}  total {dps:10,.0f} dps")
    raw.add_scale = cal.scale
    raw.save(fpath)
    print(f"Add counts scaled by {cal.scale:g} in {fpath}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    import os

    from paf import simc
    from paf.corpus.template import template_path
    from paf.plan import apply_plan, mmss, optimize, parse_plan, plan_template

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    fight = load_fight(fpath)
    ppath = fpath.with_suffix(".plan.txt")
    if not ppath.is_file():
        ppath.write_text(plan_template(fight), encoding="utf-8")
        print(f"Plan created: {ppath}\nEdit it (your moves, soaks, assignments), then run this command again "
              f"with --optimize.")
        if args.edit and os.name == "nt":
            os.startfile(ppath)  # noqa: S606 - opens the user's own text file in their editor
        return 0
    if args.edit and os.name == "nt":
        os.startfile(ppath)  # noqa: S606
        return 0
    try:
        plan = parse_plan(ppath.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"{ppath}: {e}")
        return 1
    profile_text, origin = _load_profile(args.profile)
    template_fight = fight
    if plan.assigns:
        from paf import settings
        from paf.assigns import apply_assigns, load_mechanics
        from paf.corpus import db

        mechs = load_mechanics(db.connect(), enc.id, diff, settings.get("spec"))
        fight, notes = apply_assigns(fight, mechs, plan.assigns)
        for n in notes:
            print(f"  assign: {n}")
    shiftable = [m for m in plan.moves if m.shiftable]
    print(f"{fight.name} with your plan ({len(plan.moves)} moves, {len(plan.assigns)} assignments, "
          f"{len(shiftable)} shiftable)")
    root = simc.new_run_dir(label="plan")
    mine = apply_plan(fight, plan)
    sets = {"template_only": template_fight.raid_event_lines()} if plan.moves or plan.assigns else {}
    res = simc.run(simc.build_input(profile_text, mine.to_simc(), sets), root / "plan", target_error=args.error)
    d = res.baseline["dps"]
    print(f"  your plan: {d.mean:,.0f} dps")
    for ps in res.profilesets:
        print(f"  without your moves: {res.delta_pct(ps):+.2f}% (cost of your moves: {-res.delta_pct(ps):.2f}%)")
    if args.optimize and shiftable:
        metric = "prioritydps" if args.objective >= 0.5 and "prioritydps" in res.baseline else "dps"
        opt = optimize(profile_text, fight, plan, root / "optimize", metric=metric, target_error=args.error)
        print(f"\nOptimizer ({opt.tried} placements tried, metric {metric}): {opt.gain_pct:+.2f}%")
        for i, off in opt.offsets.items():
            m = plan.moves[i]
            when = mmss(m.start + off)
            change = "keep it" if off == 0 else f"move it {abs(off):g}s {'later' if off > 0 else 'earlier'}"
            print(f"  line {m.line}: {mmss(m.start)} move {m.duration:g}s -> {when} ({change})")
    elif args.optimize:
        print("Nothing to optimize: mark moves as shiftable, e.g. `5:30 move 8 shift -5..+5`.")
    print(f"Plan: {ppath}\nRuns: {root}")
    return 0


def cmd_droptimizer(args: argparse.Namespace) -> int:
    import statistics as st

    from paf import simc
    from paf.corpus.template import template_path
    from paf.droptimizer import boss_ev, run_droptimizer, usable_loot
    from paf.encounters import find_encounter, raid_encounters
    from paf.fight import PRESETS
    from paf.gamedata import encounter_loot, item_classes, item_names
    from paf.profile import parse_simc_export
    from paf.topgear import FightProfile
    from paf.wcl import WCLClient

    profile_text, origin = _load_profile(args.profile)
    profile = parse_simc_export(profile_text)
    client = WCLClient()
    if args.boss:
        encs = [find_encounter(client, b) for b in args.boss]
    else:
        encs = raid_encounters(client)
        zone = max(e.zone_id for e in encs)
        encs = [e for e in encs if e.zone_id == zone]
    levels = [i.ilvl for i in profile.equipped.values() if i.ilvl]
    ilvl = args.ilvl or (round(st.median(levels)) if levels else 0)
    if not ilvl:
        print("Your profile has no item levels: give one with --ilvl, or load your /simc export.")
        return 1
    items = usable_loot([e.id for e in encs], profile.class_name, encounter_loot(), item_classes(), item_names())
    owned = {i.item_id: i.ilvl for i in profile.equipped.values() if i.item_id}
    skipped = [it for it in items if (owned.get(it.item_id) or 0) >= ilvl]
    items = [it for it in items if it not in skipped]
    for it in skipped:
        print(f"  skipped {it.name}: already equipped at item level {owned[it.item_id]}")
    if not items:
        print("No usable loot found for these bosses.")
        return 1
    fights: list[FightProfile] = []
    for name in args.fight or []:
        _, enc, diff_name, _ = _encounter_and_difficulty(argparse.Namespace(boss=name, difficulty=args.difficulty))
        fpath = template_path(enc.name, diff_name)
        if not fpath.is_file():
            print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
            return 1
        fights.append(FightProfile(fpath.stem, load_fight(fpath).to_simc()))
    for preset in args.preset or ([] if fights else ["patchwerk"]):
        fights.append(FightProfile(preset, PRESETS[preset]))
    print(f"{profile.name} ({origin}): loot of {', '.join(e.name for e in encs)}")
    root = simc.new_run_dir(label="droptimizer")
    run_droptimizer(profile_text, profile, items, fights, root, ilvl, target_error=args.error,
                    objective=args.objective)
    weights = {f.name: f.weight for f in fights}
    names = [f.name for f in fights]
    ranked = sorted(items, key=lambda i: -i.weighted(weights))
    print(f"\n{'item':<40} {'slot':<9} {'boss':<22} " + "  ".join(f"{n[:14]:>14}" for n in names))
    for it in ranked[:args.top]:
        cols = "  ".join(f"{it.deltas.get(n, float('nan')):+13.2f}%" for n in names)
        print(f"{it.name[:40]:<40} {it.slot:<9} {it.boss[:22]:<22} {cols}")
    print("\nExpected value per boss (mean gain of its items, losses count as 0):")
    for boss, ev, n in boss_ev(items, weights):
        print(f"  {ev:+6.2f}%  {boss} ({n} usable items)")
    err = max((i.error for i in ranked[:args.top]), default=0)
    from paf import results

    kind = "bonusroll" if getattr(args, "bonus", False) else "loot"  # the same numbers, ranked for bonus rolls
    results.write(root, kind, results.loot(items, weights, boss_ev(items, weights), ilvl, [e.name for e in encs]))
    print(f"\nStatistical error: about +/-{err:.2f}%. Items are simmed at item level {ilvl} (--ilvl to change).")
    print(f"Runs: {root}")
    return 0


def tops_alignment_safe(timeline, fight) -> list:
    from paf.optimize import tops_alignment

    try:
        return tops_alignment(timeline, fight)
    except (ValueError, ZeroDivisionError):
        return []


def cmd_prep(args: argparse.Namespace) -> int:
    import statistics as st
    import webbrowser

    from paf import settings, simc
    from paf.calibrate import calibrate, real_boss_share
    from paf.cdplan import compare_plans
    from paf.config import data_dir
    from paf.corpus import db
    from paf.corpus.analyze import analyze
    from paf.corpus.template import _slug, build_template, report_key, template_path
    from paf.corpus.timeline import build_timeline, render_html
    from paf.droptimizer import run_droptimizer, usable_loot
    from paf.gamedata import encounter_loot, item_classes, item_inventory_types, item_names, item_sets
    from paf.prep_report import PrepData, render
    from paf.profile import parse_simc_export
    from paf.talent_sim import compare as compare_builds
    from paf.topgear import FightProfile, GearPool, run_topgear

    profile_text, origin = _load_profile(args.profile)
    profile = parse_simc_export(profile_text)
    from paf.profile import role, use_profile_spec

    if role(profile) != "damage":
        print(f"{profile.spec.title()} is a {role(profile)} spec: prep-a-fight only prepares damage dealers for now.")
        return 1
    use_profile_spec(profile)  # the corpus, timelines and talents are the loaded character's spec's
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    spec = settings.get("spec")
    con = db.connect()
    root = simc.new_run_dir(label=f"prep-{_slug(enc.name)}")

    from paf.progress import Clock

    clock = Clock()
    step = clock.step  # prints the step with its time: the app predicts the time left from it

    from paf import pack

    cls = settings.get("class")
    partial = None  # a first pass from part of the corpus: (kills used, kills found)
    fresh = args.refresh or args.refine  # the second pass makes the pack again from the whole corpus
    pk = None if fresh else pack.load(enc.id, diff, cls, spec)
    if not fresh and (pk is None or pack.is_stale(pk.created)):
        shared = pack.fetch_shared(enc.id, diff, cls, spec)  # another player of the app may have made a fresh one
        if shared is not None and (pk is None or shared.created > pk.created):
            pk = shared
            print(f"Downloaded the shared prep pack of {spec} {cls} ({pk.created[:16].replace('T', ' ')} UTC).")
    if pk is not None and pack.is_stale(pk.created):
        print(f"Prep pack from {pk.created[:16].replace('T', ' ')} UTC: made before this week's reset, rebuilding it "
              f"from the logs.")
        pk = None
    if pk is not None:  # the corpus grew since (the background download after a first prep): a finer pack from it
        local = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done' "
                            "AND COALESCE(cohort, '') != 'focus'", (enc.id, diff)).fetchone()[0]
        if local >= pk.kills + pack.GROWN:
            print(f"Your corpus has {local} kills, the prep pack {pk.kills}: making it again from the corpus.")
            pk = None
    if pk is not None:  # what the logs give, already computed: no corpus, no validation sims
        step(f"Using the prep pack ({pk.kills} top kills, {pk.created[:10]})")
        boss = pk.boss
        raw = pack.Fight.from_dict(pack.asdict(pk.fight))
        raw.movement_scale = 1.0  # as from the corpus: the adds are calibrated first, the movement scale comes after
        kills, phases, moving_share, add_share = pk.kills, pk.phases, pk.moving_share, pk.add_share_spec
    else:
        done = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done' "
                           "AND COALESCE(cohort, '') != 'focus'",
                           (enc.id, diff)).fetchone()[0]
        if done < 20 or args.refresh or args.refine:
            # the sheet from the first FIRST_SHEET kills (paf.corpus: the fight is as precise as with 200, the
            # talents within 3 points), the whole quota; the rest of the corpus comes in the background afterwards
            step("Collecting the corpus from Warcraft Logs")
            cmd_corpus(argparse.Namespace(boss=args.boss, difficulty=args.difficulty, kills=None, ilvl=None,
                                          list_only=False, retry=False, refetch=False, full_quota=True,
                                          limit=None if args.refine else max(0, FIRST_SHEET - done)))
        mech_missing = con.execute(
            "SELECT COUNT(*) FROM fight f LEFT JOIN mech_status m USING(report, fight_id) "
            "WHERE f.encounter_id=? AND f.difficulty=? AND f.status='done' AND m.report IS NULL "
            "AND COALESCE(f.cohort, '') != 'focus'",
            (enc.id, diff)).fetchone()[0]
        if mech_missing:
            from paf.corpus.mechanics import fetch_mechanics

            step(f"Collecting who handles each mechanic ({mech_missing} kills)")
            fetch_mechanics(client, con, enc.id, diff, [])

        if not args.refine:  # a first pass from part of the ranked kills: the sheet says so
            used, pending = (con.execute(f"SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? "
                                         f"AND status='{st}'", (enc.id, diff)).fetchone()[0]
                             for st in ("done", "pending"))
            partial = (used, used + pending) if pending else None
        step("Analyzing the corpus")
        boss = main_boss(con, enc.id, diff, enc.name)
        rep = analyze(con, enc.id, diff, boss, spec)
        from paf.corpus.analyze import council
        from paf.corpus.units import fetch_boss_auras, fetch_council_stack, fetch_unit_windows

        fetch_unit_windows(client, con, enc.id, diff, boss)
        if members := council(con, enc.id, diff):
            fetch_council_stack(client, con, enc.id, diff, members)
        fetch_boss_auras(client, con, enc.id, diff, boss)
        raw, info = build_template(con, enc.id, diff, boss, spec, diff_name, title=enc.name)
        kills, phases, moving_share = rep.kills, [(n, m) for n, _, m, _ in rep.phases], info.moving_share
        add_share = rep.ranked_add_share[1]
    from paf.notes import refresh_notes, with_notes

    refresh_notes(template_path(enc.name, diff_name), raw)
    fight = with_notes(raw, template_path(enc.name, diff_name), verbose=True)
    d = PrepData(enc.name, diff_name, spec, profile.name or origin, kills=kills, duration=fight.duration)
    d.partial = partial
    from paf.characters import is_imported

    d.imported = is_imported(profile_text)  # found on Warcraft Logs: no bags, the sheet asks for the /simc export
    d.phases = list(phases)
    d.lust, d.pi, d.moving_share = fight.lust_time, fight.power_infusion, moving_share
    d.add_share_spec = add_share
    print(f"  {kills} kills, {len(fight.add_waves)} add waves / targets, duration {_mmss(fight.duration)}")

    step("Calibrating the fight on the logs")
    target = pk.boss_share if pk is not None else real_boss_share(con, enc.id, diff, boss, spec)
    if target is not None:
        cal = calibrate(profile_text, fight, target, root / "calibrate")
        fight.add_scale = cal.scale
        d.boss_share_real, d.add_scale = target, cal.scale
        got = cal.achieved
        print(f"  top players: {target:.0%} of damage on the boss; add counts x{cal.scale:g}"
              + (f" (simulated: {got:.0%})" if got is not None else ""))
        if got is not None and abs(got - target) > 0.05:
            d.notes.append(
                f"SimC puts {got:.0%} of your damage on the boss vs {target:.0%} in the top players' logs, even "
                f"with more adds: SimC keeps single-target spells on the boss while real players also spend them "
                f"on adds and secondary targets. Boss-only numbers are optimistic, add damage pessimistic.")
    if pk is not None:  # the pack's validation: the top players' characters were simmed when it was made
        fight.movement_scale = pk.fight.movement_scale
        d.validation = pk.validation
        if d.validation:
            print(f"  simulated / real DPS of the top players: {d.validation[1]:.2f} with movement "
                  f"x{fight.movement_scale:g} (from the pack)")
        if fight.movement_scale < 1:
            d.notes.append(f"Movement inferred from the top players' trajectories is scaled by "
                           f"{fight.movement_scale:g}: they keep casting while moving, which SimC's movement windows "
                           f"do not model.")
    elif not args.no_validate:
        from paf.validate import calibrate_movement, validate

        step("Validating the fight on the top players' own characters")
        checks = validate(con, client, enc.id, diff, spec, fight, root / "validate", players=4,
                          race=profile.header.get("race", "orc"))
        if checks:
            scale, points = calibrate_movement(checks, fight, root / "validate-movement")
            fight.movement_scale = scale
            ratio = dict(points).get(scale) or min(points, key=lambda p: abs(p[0] - scale))[1]
            d.validation = (min(r for _, r in points), ratio, max(r for _, r in points))
            print(f"  simulated / real DPS of the top players: {ratio:.2f} with movement x{scale:g}")
            defaults = [c.sim_default / c.real for c in checks if c.sim_default and c.real]
            if defaults:
                import statistics
                print(f"  (cooldowns held for the vulnerability windows like the tops; default APL, movement x0: "
                      f"{statistics.median(defaults):.2f})")
            if scale < 1:
                d.notes.append(f"Movement inferred from the top players' trajectories is scaled by {scale:g}: they "
                               f"keep casting while moving, which SimC's movement windows do not model.")
    raw.add_scale, raw.movement_scale = fight.add_scale, fight.movement_scale
    raw.save(template_path(enc.name, diff_name))
    pack_fight = pack.Fight.from_dict(pack.asdict(raw))  # for a new pack: the add scale is each player's own
    pack_fight.add_scale = 1.0
    d.waves = [(w.time, max(1, round(w.count * fight.add_scale)) if w.scalable else w.count, w.lifetime, w.name)
               for w in fight.add_waves]
    d.waves += [(v.start, 0, v.duration, f"{v.name}: boss takes x{v.multiplier:g} damage") for v in fight.vulnerable]
    d.waves.sort()
    described: list[str] = []
    planned, ppath = _fight_with_plan(enc, diff_name, described)
    if ppath is not None:
        fight = planned
        d.assigns = described or [f"from your plan {ppath.name}"]
    d.fight = fight

    if args.objective is not None:  # the player's own choice wins over the raid's log
        d.goal = "boss" if args.objective >= 0.5 else "total"
    raid_url = args.raid or _plan_raid(enc, diff_name)
    if raid_url or settings.get("guild"):
        step("Your raid and the adds")
        try:
            if not raid_url:
                from paf.raidneed import guild_report

                raid_url = guild_report(client, settings.get("guild"), settings.get("guild_server"),
                                        settings.get("guild_region"), enc.id, diff)
            d.raid = _raid_verdict(client, con, enc, diff, raid_url, profile, spec,
                                   types=pk.add_types if pk is not None else None)
            from paf import review
            from paf.wcl import WCLError

            try:  # your own pull in that log next to the top players': casting, moving
                activity = (pk.activity if pk is not None and pk.activity
                            else review.tops_activity(con, enc.id, diff, spec))  # an older pack: the local corpus
                d.review = review.review(client, raid_url, enc.id, diff, profile.name, [n for n, _ in d.phases],
                                         activity) if activity and activity[0] is not None else None
            except (WCLError, ValueError, KeyError, TypeError) as ex:
                print(f"  your own pull could not be read: {str(ex)[:120]}")
            if d.review:
                r = d.review
                print(f"  your {r.fight}: casting {r.active:.0%} of the time (top players {r.tops_active or 0:.0%}), "
                      f"moving {r.moving:.0%} (top players {r.tops_moving or 0:.0%})")
            d.raid_tools = _raid_tools(client, con, enc, diff, raid_url)
        except (ValueError, OSError, KeyError, TypeError) as ex:
            print(f"  could not read your raid's log: {ex}")
            d.notes.append(f"Your raid's log could not be read ({ex}).")
        if d.raid and d.raid.verdicts:
            for v in d.raid.verdicts:
                print(f"  {v.add.name}: {v.verdict} - {v.reason}")
            if args.objective is None:
                args.objective = 1.0 if d.raid.objective == "boss" else 0.0
                print(f"  -> cooldowns and gear for {'boss' if args.objective else 'total'} damage")
        elif d.raid:
            print("  no add type takes a real share of the damage on this boss: nothing to decide")
    if args.objective is None:
        args.objective = 0.0

    step("Simming your character on the fight")
    real = simc.run(simc.build_input(profile_text, fight.to_simc()), root / "fight", target_error=args.error)
    dummy = simc.run(simc.build_input(profile_text, ["fight_style=Patchwerk", f"max_time={simc.fmt(fight.duration)}",
                                                     "desired_targets=1"]), root / "patchwerk", target_error=args.error)
    d.sim_dps, d.patchwerk_dps = real.baseline["dps"].mean, dummy.baseline["dps"].mean
    d.sim_boss_dps = real.baseline["prioritydps"].mean if "prioritydps" in real.baseline else None
    from paf.fight import merged_movement

    strat_moves = [w for w in merged_movement(fight.movement) if not w.distance]
    moving_s = sum(w.duration for w in strat_moves)
    move_cost = None
    if moving_s >= 10:  # what moving without casting costs you: the fight without, then with its movement windows
        from paf import movement

        still = [line for line in fight.to_simc() if not line.startswith("raid_events")]
        res = simc.run(simc.build_input(profile_text, still + fight.raid_event_lines(movement_scale=0.0),
                                        {"moving": fight.raid_event_lines(movement_scale=1.0)}),
                       root / "movement", target_error=args.error)
        ps = next((p for p in res.profilesets if p.name == "moving"), None)
        if ps is not None:
            move_cost = movement.cost(res.baseline["dps"].mean, ps.dps.mean, moving_s)
            print(f"  10 s of movement without casting: -{move_cost:.2f}% DPS"
                  f" (the top players lose x{fight.movement_scale:g} of that)")

    step("Cooldown timelines of the top players")
    if pk is not None:
        tl, tl_all = pk.timeline, pk.timeline_all
    else:
        from paf.corpus.collect import backfill_npc_actors

        backfill_npc_actors(client, con, enc.id, diff)
        tl = build_timeline(con, enc.id, diff, enc.name, diff_name, spec, top=25)
        tl_all = build_timeline(con, enc.id, diff, enc.name, diff_name, spec, top=10_000)
    reports = data_dir() / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    tl_file = reports / f"timeline-{report_key(enc.name, diff_name)}.html"
    tl_file.write_text(render_html(tl), encoding="utf-8")
    d.timeline_file = tl_file.name
    from paf import movement

    d.movement = movement.Movement(movement.mobility(tl_all, strat_moves), move_cost, fight.movement_scale,
                                   d.moving_share)

    fights = {"boss fight": fight.to_simc(),
              "patchwerk": ["fight_style=Patchwerk", f"max_time={simc.fmt(fight.duration)}", "desired_targets=1"]}
    step("Talent builds of the top players")
    if pk is not None:
        builds = pk.builds
    else:
        from paf.talent_sim import fetch_codes, top_builds

        builds = top_builds(con, enc.id, diff, spec)
        fetch_codes(client, con, builds)
    d.talents = compare_builds(profile_text, builds, fights, root / "talents", target_error=args.error)
    for r in d.talents.rows if d.talents else []:  # the swapped talents: icons and Wowhead tooltips on the sheet
        for side in r.swaps:
            for t in side:
                if t and t[1]:
                    d.links.setdefault(t[0], f"spell={t[1]}")
    from paf.prep_report import _key as cd_key_of

    for ab in tl_all.abilities:  # when the top players cast each cooldown (for the plan timelines)
        d.tops_casts[cd_key_of(ab.name)] = [t for p in tl_all.players for t in p["casts"].get(ab.id, [])]
    d.tops_players = len(tl_all.players)
    from paf.wowhead import profile_refs, spell_ref

    d.links.update(profile_refs(profile))
    for ab in tl_all.abilities:
        d.links.setdefault(ab.name, spell_ref(ab.id))
        d.links.setdefault(cd_key_of(ab.name), spell_ref(ab.id))  # cooldown keys of the plans
    for ab in tl_all.abilities:
        d.cd_names.setdefault(cd_key_of(ab.name), ab.name)
    for slot in ("trinket1", "trinket2", "main_hand"):
        it = profile.equipped.get(slot)
        if it and it.name:
            d.cd_names[slot] = d.cd_names[f"use_item:{slot}"] = it.name
        if it and it.name in d.links:
            d.links[f"use_item:{slot}"] = d.links[it.name]
    d.alignment = tops_alignment_safe(tl_all, fight)
    mechs = _boss_guide(d, con, enc, diff, diff_name, spec, tl_all, fight, pk)
    from paf import defensives

    d.defensives = pk.defensives if pk is not None else defensives.analyze(con, enc.id, diff, spec)
    for m in d.defensives.moments if d.defensives else []:
        for name, sid, _ in m.spells:
            d.links.setdefault(name, spell_ref(sid))
        if m.boss_ability and m.boss_spell_id:
            d.links.setdefault(m.boss_ability, spell_ref(m.boss_spell_id))
    if pk is None:  # share what the logs gave, computed: the next prep of this spec and boss skips the corpus
        from paf import raidneed
        from paf import review as review_mod

        new = pack.PackData(enc.id, diff, cls, spec, pack.now_utc(), kills, boss, pack_fight, list(phases), add_share,
                            moving_share, target, d.validation, tl, tl_all, builds,
                            raidneed.add_types(con, enc.id, diff), mechs, d.actions, d.defensives,
                            review_mod.tops_activity(con, enc.id, diff, spec))
        print(f"  prep pack saved: {pack.save(new)}")
        if settings.get("share_packs") == "on" and new.validation:
            print(f"  prep pack {pack.publish(new)}")
    if args.no_optimize:
        step("Cooldown plans")
        d.plans = compare_plans(profile_text, tl_all, fight, root / "cdplan", target_error=args.error / 2,
                                objective=args.objective)
    else:
        from paf.optimize import mrt_note, optimize_all

        step("Ideal cooldown plan per objective, with sensitivity checks")
        d.optimized, _ = optimize_all(profile_text, fight, root / "optimize", target_error=args.error,
                                      alignment=d.alignment, validation=d.validation[1] if d.validation else None)
        d.mrt = {p.objective: mrt_note(enc.name, p, fight, d.cd_names) for p in d.optimized}
        if d.defensives and d.defensives.moments:  # the defensive moments go in every note
            extra = defensives.mrt_lines(d.defensives)
            d.mrt = {o: n + "\n" + "\n".join(extra) for o, n in d.mrt.items()}
        from paf.optimize import nsrt_note

        spell_ids = {n.lower(): int(r.split("=", 1)[1]) for n, r in d.links.items()
                     if r.startswith("spell=") and r.split("=", 1)[1].isdigit()}
        player = profile.name or "everyone"
        d.nsrt = {p.objective: nsrt_note(enc.id, p, fight, d.phases, player, spell_ids, d.cd_names)
                  for p in d.optimized}
        if d.defensives and d.defensives.moments:
            extra = defensives.nsrt_lines(d.defensives, enc.id, d.phases, player)
            d.nsrt = {o: n + ("\n" + "\n".join(extra) if extra else "") for o, n in d.nsrt.items()}
        raid_notes = [n for o, n in d.mrt.items() if o != "adds"]  # "damage to adds" is not a raid plan
        (reports / f"mrt-{report_key(enc.name, diff_name)}.txt").write_text("\n\n".join(raid_notes) + "\n",
                                                                         encoding="utf-8")

    # the fight (and the cooldown plan to follow) as simc lines, to sim it on Raidbots
    from paf.export import fight_lines
    from paf.prep_report import wanted

    title = f"{enc.name} {diff_name}"
    d.export = {"": fight_lines(title, fight)}
    goal = wanted(d) or ("boss" if args.objective is not None and args.objective >= 0.5 else "total")
    plan = next((p for p in d.optimized if p.objective == goal and p.gain > 2 * p.error), None)
    from paf.cdplan import action_name, dump_apl, parse_apl

    apl = parse_apl(dump_apl(profile_text, root / "apl-export"))
    # what the priority list casts before the pull (Stormkeeper...): the sheet says to precast it
    d.precast = list(dict.fromkeys(d.cd_names[n] for n in (action_name(a) for a in apl.get("precombat", []))
                                   if n in d.cd_names))
    if plan is not None:
        from paf.optimize import apply_rules

        label = "boss damage" if goal == "boss" else "total damage (pad)"
        d.export[label] = fight_lines(title, fight, label, apply_rules(apl, plan.choice))
    (reports / f"fight-{report_key(enc.name, diff_name)}.simc").write_text(
        list(d.export.values())[-1], encoding="utf-8")

    if not args.no_gear:
        pool = GearPool(profile, item_inventory_types(), item_sets())
        gear_profile = profile_text
        best_sets: list[list[str]] = []
        if pool.candidates:
            want = "boss" if args.objective >= 0.5 else "total"
            plan = next((p for p in d.optimized if p.objective == want), None)
            if plan is not None and any(r.name != "default" for r in plan.choice.values()):
                # the best items depend on how cooldowns are played: sim them with the chosen plan
                from paf.cdplan import dump_apl, parse_apl
                from paf.optimize import apply_rules

                apl = parse_apl(dump_apl(profile_text, root / "apl-gear"))
                gear_profile = "\n".join([profile_text.rstrip(), *apply_rules(apl, plan.choice)])
                d.gear_plan = f"with the cooldown plan for {want} damage"
            step(f"Top Gear with your {len(pool.candidates)} items {d.gear_plan}".rstrip())
            gear_fights = [FightProfile("boss fight", fight.to_simc())]
            res = run_topgear(gear_profile, pool, gear_fights, root / "topgear", objective=args.objective,
                              max_combos=args.max_combos, pass2_error=0.3)
            weights = {f.name: f.weight for f in gear_fights}
            ranked = sorted(res.combos, key=lambda c: -c.weighted(weights))
            d.gear = [("; ".join(f"{o.fam}: {o.label()}" for o in c.options.values()), c.scores, c.weighted(weights))
                      for c in ranked[:8]]
            d.gear_fights = [f.name for f in gear_fights]
            d.gear_error = max((err for c in ranked[:8] for err in c.errors.values()), default=0.0)
            best_sets = [[line for o in c.options.values() for line in o.lines()] for c in ranked[:4]
                         if c.weighted(weights) > 0]

        step("What this boss drops")
        items = usable_loot([enc.id], profile.class_name, encounter_loot(), item_classes(), item_names())
        levels = [i.ilvl for i in profile.equipped.values() if i.ilvl]
        ilvl = args.ilvl or (round(st.median(levels)) if levels else 0)
        if not ilvl:  # a profile without item levels (an old import): the loot cannot be valued
            print("  skipped: your profile has no item levels (paste your /simc export to see what this boss drops)")
            d.notes.append("What this boss drops was skipped: your character's profile has no item levels. Paste "
                           "your /simc export in the app to get it.")
            items = []
        owned = {i.item_id: i.ilvl for i in profile.equipped.values() if i.item_id}
        items = [it for it in items if (owned.get(it.item_id) or 0) < ilvl]
        if items:
            boss_fight = FightProfile("boss fight", fight.to_simc())
            run_droptimizer(gear_profile, profile, items, [boss_fight], root / "loot", ilvl,
                            target_error=args.error, objective=args.objective)
            real: dict[int, float] = {}
            if best_sets:  # the item inserted in your best sets, the rest rearranged around it
                from paf.droptimizer import loot_in_best_sets

                real = loot_in_best_sets(gear_profile, profile, items, [[], *best_sets], boss_fight,
                                         root / "loot-best-sets", ilvl, target_error=args.error,
                                         objective=args.objective)
            ranked_items = sorted(items, key=lambda i: -real.get(i.item_id, i.deltas.get("boss fight", -1e9)))
            d.loot = [(i.name, i.slot, i.deltas.get("boss fight", 0.0), real.get(i.item_id)) for i in ranked_items]
            from paf.wowhead import item_ref

            for i in ranked_items:
                d.links.setdefault(i.name, item_ref(i.item_id, ilvl))
            d.loot_ilvl = ilvl
            d.loot_error = max((i.error for i in ranked_items[:12]), default=0.0)

    from paf.icons import CLASS_ICON, icons_for

    d.class_name = profile.class_name
    d.icons = {**d.icons, **icons_for(d.links)}
    from paf import i18n

    if i18n.language() != "en":  # the game's names and journal in the player's language (applied when shown)
        from paf import names

        names.build(enc.id, diff_name, d.links, i18n.wow_locale())
    d.icons["__spec__"] = CLASS_ICON.format(cls=profile.class_name.lower())
    out = reports / f"prep-{report_key(enc.name, diff_name)}.html"
    out.write_text(render(d), encoding="utf-8")
    try:  # the sheet's data, to render it again (design work) without a new prep; local only, never shared
        import copy
        import dataclasses
        import pickle

        from paf.optimize import Rule

        saved = copy.copy(d)  # the plans' rules carry functions: only their names and descriptions are kept
        saved.optimized = [dataclasses.replace(p, choice={k: Rule(r.name, r.description, None)
                                                          for k, r in p.choice.items()}) for p in d.optimized]
        try:
            data = pickle.dumps(saved)
        except (pickle.PicklingError, AttributeError, TypeError):  # the compared plans carry functions too
            saved.plans = None
            data = pickle.dumps(saved)
        (root / "prepdata.pickle").write_bytes(data)
    except Exception as exc:  # noqa: BLE001 - only a convenience
        print(f"  (the sheet's data was not saved for a later render: {str(exc)[:120]})")
    import json
    import re

    from paf.prep_report import suggestions

    top = next((s for s in suggestions(d) if s.gain is not None and s.severity != "info"), None)
    what = re.sub(r"<[^>]+>", "", re.sub(r"<span class='pill[^']*'>.*?</span>", "", top.title)) if top else ""
    summary = {"gain": round(top.gain, 1), "what": what.strip()} if top else {}
    out.with_suffix(".json").write_text(json.dumps(summary), encoding="utf-8")  # headline for the app's home
    step("Done")
    clock.save()
    if pk is None and not args.refine:
        _refine_later(con, enc, diff, out)
    from paf.prep_report import headline

    for line in headline(d):
        print(f"  - {line}")
    print(f"\nPrep sheet: {out}\nRuns: {root}")
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    """Who does what in your raid's pull, next to the top raids (paf.raidreview)."""
    from paf import raidreview, results, settings, simc
    from paf.corpus import db
    from paf.raidneed import guild_report, raid_from_report

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    boss = main_boss(con, enc.id, diff, enc.name)
    targets, habits = raidreview.references(con, enc.id, diff, boss)
    if not targets:
        print(f"No kill of {enc.name} {diff_name} in the corpus yet: prepare this boss first.")
        return 1
    url = args.raid or _plan_raid(enc, diff_name)
    if not url and settings.get("guild"):
        url = guild_report(client, settings.get("guild"), settings.get("guild_server"), settings.get("guild_region"),
                           enc.id, diff)
    if not url:
        print("Give a log of your raid (--raid <link>) or set your guild in the settings.")
        return 1
    rc = raid_from_report(client, url, enc.id, diff)
    if not rc.same_boss:
        print(f"This log has no pull of {enc.name}.")
        return 1
    r = raidreview.review(rc, targets, habits, boss)
    print(f"{enc.name} {diff_name}: your raid's {rc.fight}, next to the top raids")
    for t in r.targets:
        print(f"  {t.name:<30} your raid {t.raid_share:6.1%}  top raids {t.tops_share:6.1%}"
              + ("" if t.covered else "  <- short"))
    words = {"to_target": "should go on", "to_boss": "can move to the boss what goes on", "ok": "plays like the tops",
             "unknown": "spec not measured"}
    for p in r.players:
        what = f" {p.target} ({p.moved:+.0%} of their damage)" if p.target else ""
        print(f"  {p.name:<16} {p.spec:<26} {words[p.verdict]}{what}")
    root = simc.new_run_dir(label="review")
    results.write(root, "review", raidreview.to_dict(r))
    print(f"Runs: {root}")
    return 0


def cmd_comp(args: argparse.Namespace) -> int:
    """Who hits what in your raid: the targets the top raids cannot skip, and who takes them (paf.comp)."""
    from paf import comp, raidplan, raidreview, results, settings, simc
    from paf.corpus import db
    from paf.raidneed import guild_report, raid_from_report

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    boss = main_boss(con, enc.id, diff, enc.name)
    targets, _habits = raidreview.references(con, enc.id, diff, boss)
    if not targets:
        print(f"No kill of {enc.name} {diff_name} in the corpus yet: prepare this boss first.")
        return 1
    url = args.raid or _plan_raid(enc, diff_name)
    if not url and settings.get("guild"):
        url = guild_report(client, settings.get("guild"), settings.get("guild_server"), settings.get("guild_region"),
                           enc.id, diff)
    if not url:
        print("Give a log of your raid (--raid <link>) or set your guild in the settings.")
        return 1
    rc = raid_from_report(client, url, enc.id, diff)
    if not rc.same_boss:
        print(f"This log has no pull of {enc.name}.")
        return 1
    refs = comp.references(con, enc.id, diff, targets)
    rows = comp.assign(rc, refs)
    bosses = {boss} | {r.name for r in refs if r.second_boss}
    swap_list = comp.swaps(rc, comp.boss_dps(con, enc.id, diff, bosses), raidplan.class_specs(con, enc.id, diff))
    print(f"{enc.name} {diff_name}, your raid's pull ({rc.fight}): who hits what")
    for a in rows:
        kind = ("second boss" if a.second_boss else
                "whole raid" + (f" + {a.players} assigned" if a.players else "") if a.whole_raid else
                f"{a.players} assigned" if a.players else "a few players")
        print(f"  {a.target} ({kind}; your raid {a.raid_share:.0%}, top raids {a.tops_share:.0%})")
        print("    most damage on it: " + ", ".join(f"{s} {d / 1000:,.0f}k" for s, d, _ in a.ranking[:4]))
        if a.proposed:
            print("    on it: " + ", ".join(f"{n} ({s})" for n, s in a.proposed))
        if a.missed:
            print("    missed it: " + ", ".join(f"{n} {x:.0%} (their spec {h:.0%})" for n, _, x, h in a.missed))
    if not rows:
        print("  Nothing but the boss: no add to assign.")
    for x in swap_list:
        print(f"  {x.name}: {x.better} does {x.gain:+.0%} boss damage vs {x.current} on this boss")
    root = simc.new_run_dir(label="comp")
    results.write(root, "comp", comp.to_dict(boss, rc.fight, rows, swap_list))
    print(f"Runs: {root}")
    return 0


def cmd_wipe(args: argparse.Namespace) -> int:
    """Your best pull of a boss not killed yet, in detail: the deaths, the damage off the boss, and when it would have
    died without them (paf.wipe)."""
    import statistics as st

    from paf import comp, raidreview, results, settings, simc, wipe
    from paf.corpus import db
    from paf.raidneed import guild_report, report_code

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    boss = main_boss(con, enc.id, diff, enc.name)
    targets, _habits = raidreview.references(con, enc.id, diff, boss)
    main = next((t for t in targets if t.main), None)
    durations = sorted(r[0] for r in con.execute(
        "SELECT duration_s FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'", (enc.id, diff)))
    if not main or not durations:
        print(f"No kill of {enc.name} {diff_name} in the corpus yet: prepare this boss first.")
        return 1
    url = args.raid or _plan_raid(enc, diff_name)
    if not url and settings.get("guild"):
        url = guild_report(client, settings.get("guild"), settings.get("guild_server"), settings.get("guild_region"),
                           enc.id, diff)
    if not url:
        print("Give a log of your raid (--raid <link>) or set your guild in the settings.")
        return 1
    code = report_code(url)
    fight = wipe.best_wipe(client, code, enc.id, diff)
    if not fight:
        print(f"No wipe on {enc.name} {diff_name} in this log.")
        return 1
    print(f"Reading your best pull of {enc.name} {diff_name}, 15 s at a time...", flush=True)
    p = wipe.analyze(client, code, fight, boss, main.tops_share, comp.boss_dps(con, enc.id, diff, {boss}))
    wipe.add_talents(client, code, p, enc.id, diff)

    def mmss(t: float) -> str:
        return "never" if t == float("inf") else f"{int(t // 60)}:{int(t % 60):02d}"
    print(f"Best pull: {mmss(p.duration)}, boss at {p.boss_left:.1%}. Top kills: {mmss(st.median(durations))} "
          f"(longest {mmss(durations[-1])}).")
    print(f"Kill estimated at {mmss(p.kill_time())} as played, {mmss(p.kill_time('no_deaths'))} without the deaths, "
          f"{mmss(p.kill_time('no_deaths_share'))} with the top kills' boss share too, "
          f"{mmss(p.kill_time('like_tops'))} playing like the top players of each spec.")
    print(f"Boss damage share {p.raid_share:.0%} (top kills {p.tops_share:.0%}). Boss damage lost per player:")
    for c in p.culprits:
        h = p.health or 1
        ref = f"{c.tops_dps / 1000:,.0f}k" if c.tops_dps else "?"
        extra = (f"; padding talents: {', '.join(c.pad_talents)}" if c.pad_talents else "") + (
            f"; boss talents missing: {', '.join(c.boss_talents)}" if c.boss_talents else "")
        print(f"  {c.spec:24} {c.lost / h:5.1%} (dead {c.lost_dead / h:.1%}, alive {c.alive_dps / 1000:,.0f}k vs "
              f"{ref}){extra}")
    root = simc.new_run_dir(label="wipe")
    results.write(root, "wipe", wipe.to_dict(p, enc.name, durations[-1], st.median(durations)))
    print(f"Runs: {root}")
    return 0


def _active_character() -> tuple[str, str, str]:
    """(name, server, region) of the active character, from its /simc export."""
    import re

    from paf.config import data_dir

    path = data_dir() / "profiles" / "current.simc"
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""

    def field(key: str) -> str:
        m = re.search(rf'^{key}="?([^"\n]+)"?\s*$', text, re.M)
        return m.group(1).strip() if m else ""
    m = re.search(r'^(?:deathknight|demonhunter|druid|evoker|hunter|mage|monk|paladin|priest|rogue|shaman|warlock|'
                  r'warrior)="?([^"\n]+)"?', text, re.M)
    return (m.group(1).strip() if m else ""), field("server"), field("region")


def cmd_night(args: argparse.Namespace) -> int:
    """Your raid night, pull by pull: deaths, healthstones, health and damage potions (paf.tracker)."""
    from paf import results, settings, simc, tracker
    from paf.raidneed import GUILD_REPORTS_QUERY, report_code, server_slug
    from paf.wcl import WCLClient

    client = WCLClient()
    code = report_code(args.raid) if args.raid else None
    name, server, region = _active_character()
    if not code and name and server:  # your character's latest log: tonight's, live too
        code = tracker.character_report(client, name, server, region)
        if code:
            print(f"The latest log of {name}.")
    if not code and settings.get("guild"):
        data = client.query(GUILD_REPORTS_QUERY, {"name": settings.get("guild"),
                                                  "server": server_slug(settings.get("guild_server")),
                                                  "region": settings.get("guild_region").upper()}, cache_ttl=300)
        reports = (data["reportData"]["reports"] or {}).get("data") or []
        code = reports[0]["code"] if reports else None
    if not code:
        print("Give a log of your raid (--raid <link>), load your character, or set your guild in the settings.")
        return 1
    root = simc.new_run_dir(label="night")
    seen, quiet_since = -1, time.time()
    while True:
        print("Reading the pulls of the log...", flush=True)
        rows, icons = tracker.night(client, code, live=args.live)
        if len(rows) != seen:
            seen, quiet_since = len(rows), time.time()
            if rows:
                results.write(root, "night", tracker.to_dict(code, rows, icons))
                print(f"Runs: {root}", flush=True)  # the page shows the night so far
                print(f"{len(rows)} pulls so far.", flush=True)
        if not args.live:
            break
        if time.time() - quiet_since > 30 * 60:
            print("No new pull for 30 minutes: the night is over.")
            break
        time.sleep(90)
    if not rows:
        print("No boss pull in this log.")
        return 1
    s = tracker.summary(rows)
    print(f"{len(rows)} pulls. Per player: deaths (without a healthstone or health potion first), healthstones, "
          f"health potions, pulls with a damage potion")
    for pname, v in sorted(s.items(), key=lambda x: (-x[1]["bare"], -x[1]["deaths"])):
        print(f"  {pname:<16} {icons.get(pname, ''):<24} deaths {v['deaths']:2} ({v['bare']} bare)  "
              f"healthstones {v['healthstone']:2}  health potions {v['health']:2}  "
              f"damage potion {v['pulls_damage_potion']}/{len(rows)}")
    print(f"Runs: {root}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Two pulls of a boss side by side, for the raid and for one player (paf.pulldiff)."""
    from paf import characters, pulldiff, results, settings, simc, tracker
    from paf.corpus import db
    from paf.raidneed import guild_report, report_code

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    boss = main_boss(con, enc.id, diff, enc.name)
    url = args.raid or _plan_raid(enc, diff_name)
    if not url and settings.get("guild"):
        url = guild_report(client, settings.get("guild"), settings.get("guild_server"), settings.get("guild_region"),
                           enc.id, diff)
    if not url:
        print("Give a log of your raid (--raid <link>) or set your guild in the settings.")
        return 1
    code = report_code(url)
    fights, actors = pulldiff.pulls(client, code, enc.id, diff)
    rows = {r.fight: r for r in tracker.night(client, code, enc.id)[0]}
    who = args.player or next((c.name for c in characters.all_characters() if c.current), "")
    actor = next((a for n, a in actors.items() if n.lower() == who.lower()), None) if who else None
    if who and not actor:
        print(f"{who} is not in this log: the raid only.")
    if args.pulls:
        ids = [int(x) for x in args.pulls.replace(" ", "").split(",")]
        by_id = {f["id"]: f for f in fights}
        pair = (by_id.get(ids[0]), by_id.get(ids[-1])) if len(ids) == 2 else None
        if not pair or None in pair:
            print(f"Pulls of {enc.name} {diff_name} in this log: {', '.join(str(f['id']) for f in fights)}")
            return 1
    else:
        pair = (pulldiff.player_pair(client, code, fights, actor["name"], rows) if actor else None) or \
            pulldiff.default_pair(fights)
    if not pair:
        print(f"Fewer than two pulls of {enc.name} {diff_name} to compare in this log.")
        return 1
    print("Reading both pulls, 15 s at a time...", flush=True)
    others = list(actors.values())
    a, b = (pulldiff.side(client, code, f, boss, rows.get(f["id"]), actor, others) for f in pair)
    d = pulldiff.to_dict(boss, a, b)
    print(f"{enc.name} {diff_name}: A = {a.label} (pull {a.fight}), B = {b.label} (pull {b.fight})")
    for h in d["highlights"]:
        print(f"  {'+' if h['kind'] == 'good' else '-'} {h['text']}")
    root = simc.new_run_dir(label="diff")
    results.write(root, "diff", d)
    print(f"Runs: {root}")
    return 0


def cmd_rotation(args: argparse.Namespace) -> int:
    """A player's rotation in one pull, next to SimulationCraft's on the same targets (paf.rotation)."""
    import tempfile
    from pathlib import Path

    from paf import apl, characters, pulldiff, results, rotation, settings, simc, tracker
    from paf.gamedata import spell_cooldowns, spell_durations
    from paf.raidneed import guild_report, report_code

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    url = args.raid or _plan_raid(enc, diff_name)
    if not url and settings.get("guild"):
        url = guild_report(client, settings.get("guild"), settings.get("guild_server"), settings.get("guild_region"),
                           enc.id, diff)
    if not url:
        print("Give a log of your raid (--raid <link>) or set your guild in the settings.")
        return 1
    code = report_code(url)
    fights, actors = pulldiff.pulls(client, code, enc.id, diff)
    who = args.player or next((c.name for c in characters.all_characters() if c.current), "")
    actor = next((a for n, a in actors.items() if n.lower() == who.lower()), None) if who else None
    if not actor:
        print(f"{who or 'Nobody'} is not in this log: give the player with --player.")
        return 1
    if args.pull:
        fight = next((f for f in fights if f["id"] == args.pull), None)
    else:  # their best pull without a death, else the kill / the best wipe
        rows = {r.fight: r for r in tracker.night(client, code, enc.id)[0]}
        pair = pulldiff.player_pair(client, code, fights, actor["name"], rows) or pulldiff.default_pair(fights)
        fight = pair[1] if pair else (fights[0] if fights else None)
    if not fight:
        print(f"No pull of {enc.name} {diff_name} in this log.")
        return 1
    cls, spec = rotation.spec_of(rotation.player_details(client, code, fight, actor["id"]))
    print(f"Reading {actor['name']}'s pull {fight['id']} ({spec} {cls})...", flush=True)
    log = rotation.fetch(client, code, fight, actor["id"], actor["name"])
    spells = apl.spells(apl.default_apl(cls, spec))
    r = rotation.review(log, actor["name"], f"{spec} {cls}", f"pull {fight['id']}", spell_cooldowns(),
                        spell_durations(), spells)
    profile = rotation.profile_from_pull(client, code, fight, actor)
    if profile and spells:
        print("Simulating the same character with the default rotation on 1, 3 and 5 targets...", flush=True)
        windows = rotation.targets_per_window(client, code, fight, actor["id"])
        sims = {k: rotation.sim_casts(profile, n, Path(tempfile.mkdtemp(prefix="paf-rot-")))
                for k, n in rotation.SIM_TARGETS.items()}
        r.contexts = rotation.contexts(log, windows, sims, spells)
    else:
        print("  no SimulationCraft comparison: the log lacks this player's gear or talents, or simc has no APL")
    for _, text in rotation.highlights(r):
        print("  " + text)
    root = simc.new_run_dir(label="rotation")
    results.write(root, "rotation", dict(rotation.to_dict(r), boss=enc.name, kill=bool(fight["kill"])))
    print(f"Runs: {root}")
    return 0


def cmd_raid(args: argparse.Namespace) -> int:
    from paf import settings
    from paf.corpus import db
    from paf.profile import parse_simc_export

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    if not con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                       (enc.id, diff)).fetchone()[0]:
        print(f"No kill of {enc.name} {diff_name} in the corpus yet: run `paf corpus \"{enc.name}\"` first.")
        return 1
    url = args.raid or _plan_raid(enc, diff_name)
    if not url:
        if not settings.get("guild"):
            print("Give a log of your raid (--raid <link>) or set your guild once: `paf config guild \"<name>\"`, "
                  "`paf config guild_server <server>`, `paf config guild_region eu`.")
            return 1
        from paf.raidneed import guild_report

        url = guild_report(client, settings.get("guild"), settings.get("guild_server"), settings.get("guild_region"),
                           enc.id, diff)
    try:
        profile = parse_simc_export(_load_profile(args.profile)[0])
    except SystemExit:
        from paf.profile import Profile

        profile = Profile()
    r = _raid_verdict(client, con, enc, diff, url, profile, settings.get("spec"), fill=args.fill)
    print(f"{enc.name} ({diff_name}), your raid from log {r.report} ({r.fight}, {r.players} players)")
    print(f"you: {r.you[0]}, {r.you[1] / 1000:,.0f}k DPS" + ("" if r.you_found else " (not in that log: raid median)"))
    if not r.verdicts:
        print("No add takes a real share of the damage on this boss: play for the boss.")
        return 0
    print("\nYour raid's damage on the adds, as a share of the top raids' (median = 100%):")
    print(f"{'Adds':24} {'without you':>12} {'with you':>9} {'top raids, weakest quarter':>27}")
    for v in r.verdicts:
        print(f"{v.add.name:24} {v.without_you:11.0%} {v.with_you:9.0%} {v.low:27.0%}")
        print(f"  -> {v.verdict}: {v.reason}")
    for kind, players in r.archetypes.items():
        if players:
            print(f"\n{kind} on this boss ({len(players)}): " + ", ".join(players))
    if r.estimated:
        print(f"\n(estimated from their rankings, too rare in the corpus: {', '.join(r.estimated)})")
    if r.your_profile:
        p = r.your_profile
        print(f"\nYour spec's top 100: {p.dps / 1000:,.0f}k total DPS, {p.boss_dps / 1000:,.0f}k boss DPS "
              f"({p.boss_share:.0%} on the boss), {p.same_players} players in both")
        if p.pad_talents or p.boss_talents:
            print(f"  pad build takes: {', '.join(p.pad_talents) or '-'}; boss build takes: "
                  f"{', '.join(p.boss_talents) or '-'}")
        else:
            print("  same talents in both: no separate pad build")
    print(f"\n=> {'Stay on the boss' if r.objective == 'boss' else 'Pad the adds'}: "
          f"`paf prep \"{enc.name}\"` will use the cooldown plan and gear for "
          f"{'boss' if r.objective == 'boss' else 'total'} damage.")
    return 0


def _boss_guide(d, con, enc, diff: int, diff_name: str, spec: str, tl, fight, pk=None) -> list:
    """The boss in 60 seconds (Encounter Journal) with the logs' timings and assignment stats. pk: a prep pack
    (its mechanics and actions instead of the corpus). Returns the mechanics (for a new pack)."""
    from paf import bossguide
    from paf.icons import icons_for

    sections = bossguide.load(enc.id, diff_name)
    if pk is not None:
        mechs = pk.mechanics
    else:
        try:
            from paf.assigns import load_mechanics

            mechs = load_mechanics(con, enc.id, diff, spec)
        except Exception:  # noqa: BLE001 - the guide works without the assignment stats
            mechs = []
    # the boss's spells and when (the simple view's vertical timeline): the Encounter Journal's, else the rare ones
    journal = set(bossguide.spell_refs(sections)) if sections else set()
    d.boss_casts = [(n, ts) for n, ts in (tl.boss_casts if tl is not None else [])
                    if (n in journal if journal else len(ts) <= 12)]
    if not sections:
        return mechs
    burst = {v.name.split(" (")[0]: v.multiplier for v in fight.vulnerable}
    gicons = icons_for(bossguide.spell_refs(sections))
    d.icons.update(gicons)
    d.guide_summary = bossguide.summary_html(sections, "damage", "#boss")
    d.role_bullets = bossguide.role_bullets(sections, "damage")
    if pk is not None:
        d.actions = pk.actions
    else:
        _corpus_actions(d, con, enc, diff, spec, sections, mechs)
    d.guide_abilities = bossguide.abilities_html(sections, timings=dict(tl.boss_casts), mechanics=mechs,
                                                 burst=burst, icon_map=gicons)
    return mechs


def _corpus_actions(d, con, enc, diff: int, spec: str, sections, mechs) -> None:
    """What the top players do on this boss (kill, kick, soak...), from the corpus."""
    try:
        from paf import raidneed, settings
        from paf.actions import actions

        label = f"{spec} {settings.get('class')}"
        focus = {t.name: t.focus[label] for t in raidneed.add_types(con, enc.id, diff) if label in t.focus}
        skip = {r[0] for r in con.execute("SELECT name FROM npc WHERE is_boss=1")}
        from paf.actions import contact_debuffs
        from paf.mechanics import walk

        def own(section) -> list[str]:  # the unit's own abilities, not those of the units it contains
            out = []
            for c in section.children:
                if c.kind == "ability":
                    out.append(c.title)
                    out += own(c)
            return out

        units = {s.title: own(s) for _, s in walk(sections) if s.kind == "creature"}
        contact = contact_debuffs(con, enc.id, diff, units)
        d.actions = actions(con, enc.id, diff, spec, mechs, focus, skip, contact)
    except Exception as ex:  # noqa: BLE001 - the guide works without them
        print(f"  actions from the logs skipped: {ex}")


def cmd_raidplan(args: argparse.Namespace) -> int:
    """The raid's comp: which spec each player brings and who pads, for the most boss damage with the adds
    covered like in the top raids (paf.raidplan)."""
    from paf import raidneed, raidplan, settings
    from paf.config import data_dir
    from paf.corpus import db
    from paf.corpus.template import _slug

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    if not con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                       (enc.id, diff)).fetchone()[0]:
        print(f"No kill of {enc.name} {diff_name} in the corpus yet: run `paf corpus \"{enc.name}\"` first.")
        return 1
    url = args.raid or _plan_raid(enc, diff_name)
    if not url and settings.get("guild"):
        url = raidneed.guild_report(client, settings.get("guild"), settings.get("guild_server"),
                                    settings.get("guild_region"), enc.id, diff)
    if not url:
        print("Give a log of your raid (--raid <link>) or set your guild (`paf config guild ...`).")
        return 1
    rc = raidneed.raid_from_report(client, url, enc.id, diff)
    by_class = raidplan.class_specs(con, enc.id, diff)
    extra: dict[str, list[str]] = {}
    for part in (args.options or "").split(";"):
        name, _, specs = part.partition(":")
        if name.strip():
            extra[name.strip().lower()] = [s.strip() for s in specs.split(",") if s.strip()]
    members = []
    for name, spec, dps in rc.players:
        opts = [spec] + extra.get(name.lower(), [])
        if args.swap_specs and spec not in raidneed.HEALERS and spec not in raidplan.TANKS:
            opts += by_class.get(spec.rpartition(" ")[2], [])
        members.append(raidplan.Member(name, spec, dps, list(dict.fromkeys(opts))))
    print(f"{len(members)} players from log {rc.report} ({rc.fight}); reading the top 100 of "
          f"{len({s for m in members for s in m.options})} specs...", flush=True)
    profiles = raidneed.spec_profiles(client, enc.id, diff, [s for m in members for s in m.options])
    shares = raidplan.add_shares(con, enc.id, diff)
    _median, low = raidplan.required_adds(con, enc.id, diff)
    p = raidplan.plan(members, profiles, shares, low)
    print(f"\nBoss damage {p.boss / 1000:,.0f}k/s vs {p.current_boss / 1000:,.0f}k/s for the comp of the log "
          f"({(p.boss / p.current_boss - 1) * 100 if p.current_boss else 0:+.1f}%); adds {p.adds / 1000:,.0f}k/s "
          f"for {low / 1000:,.0f}k/s needed ({'covered' if p.covered else 'NOT covered'})")
    for c in sorted(p.choices, key=lambda c: (c.member.role != "damage", not c.pad, -c.boss)):
        role = c.member.role if c.member.role != "damage" else ("PAD" if c.pad else "boss")
        swap = f"  (swap from {c.member.current})" if c.spec != c.member.current else ""
        print(f"  {c.member.name:18} {c.spec:26} {role:6} boss {c.boss / 1000:6,.0f}k  "
              f"adds {c.adds / 1000:5,.0f}k{swap}")
    for n in p.notes:
        print("  " + n)
    bosses = {r[0] for r in con.execute("SELECT name FROM npc WHERE is_boss=1")}
    played = raidplan.what_happened(rc, bosses, shares)
    if played:
        print("\nIn this pull (boss / adds DPS, share on adds vs the top players of the spec):")
        for x in played:
            tops = f"tops {x.tops_share:.0%}" if x.tops_share is not None else ""
            print(f"  {x.name:18} {x.spec:26} boss {x.boss / 1000:6,.0f}k  adds {x.adds / 1000:5,.0f}k  "
                  f"{x.share:4.0%} {tops:9} {x.verdict}")
    out = data_dir() / "reports" / f"raidplan-{_slug(enc.name)}-{diff_name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(raidplan.render(p, enc.name, diff_name, rc.report, rc.fight, played), encoding="utf-8")
    print(f"\nRaid plan: {out}")
    return 0


def _plan_raid(enc, diff_name: str) -> str:
    """The `raid <log link>` line of the boss plan, if any."""
    from paf.corpus.template import template_path
    from paf.plan import parse_plan

    p = template_path(enc.name, diff_name).with_suffix(".plan.txt")
    try:
        return parse_plan(p.read_text(encoding="utf-8-sig")).raid if p.is_file() else ""
    except ValueError:
        return ""


def _raid_tools(client, con, enc, diff: int, url: str) -> dict:
    """For the "Your raid" tab of the prep: who hits what (paf.comp), the best pull if the boss is not dead in that
    log (paf.wipe), this boss's pulls of the night (paf.tracker). Each one on its own: a failure only skips it."""
    import statistics as st

    from paf import comp, raidplan, raidreview, tracker, wipe
    from paf.raidneed import raid_from_report, report_code

    out: dict = {}
    code = report_code(url)
    boss = main_boss(con, enc.id, diff, enc.name)
    targets, _ = raidreview.references(con, enc.id, diff, boss)  # empty with a prep pack and no local corpus
    if targets:
        try:
            rc = raid_from_report(client, url, enc.id, diff)
            if rc.same_boss:
                refs = comp.references(con, enc.id, diff, targets)
                bosses = {boss} | {r.name for r in refs if r.second_boss}
                swaps = comp.swaps(rc, comp.boss_dps(con, enc.id, diff, bosses),
                                   raidplan.class_specs(con, enc.id, diff))
                out["comp"] = comp.to_dict(boss, rc.fight, comp.assign(rc, refs), swaps)
        except Exception as ex:  # noqa: BLE001 - an extra of the prep: never fails it
            print(f"  who hits what: skipped ({str(ex)[:100]})")
        try:
            main = next(t for t in targets if t.main)
            fight = wipe.best_wipe(client, code, enc.id, diff)
            durations = sorted(r[0] for r in con.execute(
                "SELECT duration_s FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'", (enc.id, diff)))
            if fight and durations:
                p = wipe.analyze(client, code, fight, boss, main.tops_share, comp.boss_dps(con, enc.id, diff, {boss}))
                wipe.add_talents(client, code, p, enc.id, diff)
                out["wipe"] = wipe.to_dict(p, enc.name, durations[-1], st.median(durations))
                t = p.kill_time("no_deaths")
                print(f"  best pull: boss at {p.boss_left:.1%}, kill estimated at {int(t // 60)}:{int(t % 60):02d} "
                      f"without the deaths")
        except Exception as ex:  # noqa: BLE001
            print(f"  best pull: skipped ({str(ex)[:100]})")
    try:
        rows, icons = tracker.night(client, code, enc.id)
        if rows:
            out["night"] = tracker.to_dict(code, rows, icons)
    except Exception as ex:  # noqa: BLE001
        print(f"  the night's pulls: skipped ({str(ex)[:100]})")
    return out


def _raid_verdict(client, con, enc, diff: int, url: str, profile, spec: str, fill: bool = False, types=None):
    """Pad the adds or stay on the boss, from your raid's composition and DPS (paf.raidneed). fill: fetch a few
    ranked kills of the specs of your raid that are too rare in the corpus to be measured. types: the add types
    of a prep pack (else read from the corpus)."""
    import statistics as st

    from paf import raidneed, settings
    from paf.prep_report import RaidInfo
    from paf.wcl import WCLError

    rc = raidneed.raid_from_report(client, url, enc.id, diff)
    me = next((p for p in rc.players if profile.name and p[0].lower() == profile.name.lower()), None)
    others = [(s, dps) for n, s, dps in rc.players if me is None or n != me[0]]
    if me is not None:
        you, found = (me[1], me[2]), True
    else:  # not in that log: a damage dealer of your spec at the raid's median DPS among damage dealers
        dealers = sorted(dps for _, _, dps in rc.players)[len(rc.players) // 2:]
        you, found = (f"{spec} {settings.get('class')}", st.median(dealers) if dealers else 0.0), False
    if types is None:
        types = raidneed.add_types(con, enc.id, diff)
    missing = sorted({s for _, s, _ in rc.players if types and s not in types[0].focus and s not in raidneed.HEALERS})
    if missing and fill and con is not None:  # optional: measure the rare specs on real kills, not estimates
        from paf.corpus.collect import add_focus_kills, collect

        print(f"  not measured on this boss yet: {', '.join(missing)}; fetching ~20 ranked kills of each "
              f"(about 10 quota points per kill)", flush=True)
        for label in missing:
            spec_name, _, cls = label.rpartition(" ")
            try:
                add_focus_kills(client, con, enc, diff, cls, spec_name)
            except (WCLError, KeyError, TypeError) as ex:
                print(f"  {label}: {ex}")
        collect(client, con, enc, diff)
        types = raidneed.add_types(con, enc.id, diff)
    # every spec of the raid (and yours): total-DPS vs boss-DPS rankings, a few quota points per spec
    print("  reading the total-DPS and boss-DPS rankings of your raid's specs...", flush=True)
    profiles = raidneed.spec_profiles(client, enc.id, diff, [s for _, s, _ in rc.players] + [you[0]])
    types = [raidneed.with_profiles(t, profiles) for t in types]
    vs = raidneed.verdicts(types, others, you)
    return RaidInfo(rc.report, rc.fight, len(rc.players), you, found, vs, raidneed.overall(vs),
                    raidneed.best_cleavers(types, rc.players), raidneed.archetypes(types, rc.players),
                    raidneed.archetype(types[0], you[0]) if types else "", profiles.get(you[0]),
                    sorted(types[0].estimated) if types else [])


def _fight_with_plan(enc, diff_name: str, described: list[str] | None = None):
    """The boss template with the user's plan file applied (moves, lust, PI, assignments), if there is one.
    `described` receives what was applied, in the player's words."""
    from paf.corpus.template import template_path
    from paf.plan import apply_plan, describe_plan, parse_plan

    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        return None, None
    fight = load_fight(fpath)
    ppath = fpath.with_suffix(".plan.txt")
    if ppath.is_file():
        plan = parse_plan(ppath.read_text(encoding="utf-8"))
        if not plan.empty:
            fight = apply_plan(fight, plan)
            notes = []
            if plan.assigns:
                from paf import settings
                from paf.assigns import apply_assigns, load_mechanics
                from paf.corpus import db

                mechs = load_mechanics(db.connect(), enc.id, settings.DIFFICULTIES[diff_name], settings.get("spec"))
                fight, notes = apply_assigns(fight, mechs, plan.assigns)
                for n in notes:
                    print(f"  assign: {n}")
            if described is not None:
                described += [f"Assignment: {n}" for n in notes] + describe_plan(plan)
            return fight, ppath
    return fight, None


def cmd_assigns(args: argparse.Namespace) -> int:
    from paf import settings
    from paf.assigns import MIN_SAMPLES, assigns_template, load_mechanics
    from paf.corpus import db
    from paf.corpus.template import template_path
    from paf.fight import Fight
    from paf.plan import plan_template

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    spec = settings.get("spec")
    con = db.connect()
    have = con.execute("SELECT COUNT(*) FROM mech_status m JOIN fight f USING(report, fight_id) "
                       "WHERE f.encounter_id=? AND f.difficulty=?", (enc.id, diff)).fetchone()[0]
    if not have:
        _mechanics_from_corpus(enc, diff_name)
    mechs = load_mechanics(con, enc.id, diff, spec)
    if not mechs:
        print("No assignable mechanic found in the corpus.")
        return 1
    print(f"{enc.name} {diff_name}: mechanics players get assigned to (cost measured on {spec} players)\n")
    for m in mechs:
        when = ", ".join(_mmss(t) for t in m.times[:8]) + (" ..." if len(m.times) > 8 else "")
        what = "kick" if m.kind == "interrupt" else f"{m.players_per_kill:.0f}/kill"
        cost = f"{m.cost:g}s" + ("" if m.samples >= MIN_SAMPLES else " (default)")
        print(f"  {m.name:<28} {what:<8} cost {cost:<14} at {when}")
    fpath = template_path(enc.name, diff_name)
    if fpath.is_file():
        ppath = fpath.with_suffix(".plan.txt")
        text = ppath.read_text(encoding="utf-8") if ppath.is_file() else plan_template(Fight.load(fpath))
        # refresh the commented suggestions, keep everything the user wrote (uncommented `assign` lines too)
        kept = [line for line in text.splitlines()
                if not line.startswith("# assign ") and not line.startswith("# Boss mechanics you may be assigned")]
        while kept and not kept[-1].strip():
            kept.pop()
        ppath.write_text("\n".join(kept) + "\n" + assigns_template(mechs, spec), encoding="utf-8")
        print(f"\nIn your plan (uncomment the `# assign ...` lines of your assignments): {ppath}")
    return 0


def print_optimized(plans, fight) -> None:
    from paf.optimize import fight_context

    labels = {"boss": "boss damage", "total": "total damage", "adds": "damage to adds",
              "secondary": "damage to secondary targets"}
    for p in plans:
        others = ", ".join(f"{o} {v:+.2f}%" for o, v in p.totals.items() if o != p.objective)
        print(f"\n## Best plan for {labels[p.objective]}: {p.gain:+.2f}% (+/-{p.error:.2f}%) vs the default APL"
              + (f"  [{others}]" if others else ""))
        changed = {k: r for k, r in p.choice.items() if r.name != "default"}
        if not changed:
            print("  the default APL is already the best for this objective")
        for k, r in changed.items():
            print(f"  {k.replace('use_item:', ''):<22} {r.description}")
        if p.sensitivity:
            print("  sensitivity: " + ", ".join(f"{v} {g:+.1f}%" for v, g in p.sensitivity.items())
                  + ("  -> robust" if p.robust else "  -> NOT robust"))
        for flag in p.flags:
            print(f"  ! check: {flag}")
        if p.timeline:
            print("  play-by-play (one simulated pull):")
            for t, label in p.timeline:
                ctx = fight_context(fight, t)
                print(f"    {_mmss(t):>5}  {label:<24} {ctx}")


def print_alignment(enc, diff_name: str, diff: int, fight) -> None:
    """What the top players actually do with their cooldowns, to check the simulated plans against."""
    from paf import settings
    from paf.corpus import db
    from paf.corpus.timeline import build_timeline
    from paf.optimize import tops_alignment

    tl = build_timeline(db.connect(), enc.id, diff, enc.name, diff_name, settings.get("spec"), top=10_000)
    rows = tops_alignment(tl, fight)
    if not rows:
        return
    a0 = rows[0]
    print(f"\n## What the top players do (casts after the opener; add waves cover {a0.adds_cover:.0%} of the fight, "
          f"secondary targets {a0.units_cover:.0%}):")
    for a in rows:
        held = []
        if a.in_adds > a.adds_cover * 1.5 and a.in_adds - a.adds_cover > 0.1:
            held.append("held for adds")
        if a.units_cover and a.in_units > a.units_cover * 1.5 and a.in_units - a.units_cover > 0.1:
            held.append("held for secondary targets")
        print(f"  {a.ability:<24} {a.in_adds:5.0%} during adds, {a.in_units:5.0%} on secondary targets"
              f"   {' / '.join(held) or 'no clear hold'}")


def cmd_optimize(args: argparse.Namespace) -> int:
    from paf import simc
    from paf.config import data_dir
    from paf.corpus.template import _slug, report_key
    from paf.optimize import OBJECTIVES, mrt_note, optimize_all

    profile_text, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fight, ppath = _fight_with_plan(enc, diff_name)
    if fight is None:
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    objectives = OBJECTIVES if args.objective == "all" else (args.objective,)
    print(f"{enc.name} {diff_name}: optimizing cooldowns for {', '.join(objectives)} ({origin})"
          + (f", with your plan {ppath}" if ppath else ""))
    root = simc.new_run_dir(label=f"optimize-{_slug(enc.name)}")
    from paf import settings
    from paf.corpus import db
    from paf.corpus.timeline import build_timeline
    from paf.optimize import tops_alignment

    tl = build_timeline(db.connect(), enc.id, diff, enc.name, diff_name, settings.get("spec"), top=10_000)
    plans, _ = optimize_all(profile_text, fight, root, objectives=objectives, target_error=args.error,
                            alignment=tops_alignment(tl, fight))
    print_optimized(plans, fight)
    from paf import results

    results.write(root, "cooldowns", results.cooldowns(plans, enc.name, diff_name))
    print_alignment(enc, diff_name, diff, fight)
    notes = data_dir() / "reports" / f"mrt-{report_key(enc.name, diff_name)}.txt"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text("\n\n".join(mrt_note(enc.name, p, fight) for p in plans) + "\n", encoding="utf-8")
    print(f"\nMRT notes: {notes}\nRuns: {root}")
    return 0


def cmd_mechanics(args: argparse.Namespace) -> int:
    from paf import settings
    from paf.encounters import find_encounter
    from paf.mechanics import encounter_sections, format_sections
    from paf.wcl import WCLClient

    enc = find_encounter(WCLClient(), args.boss)
    diff_name = (args.difficulty or settings.get("difficulty")).lower()
    sections = encounter_sections(enc.id)
    if not sections:
        print(f"No Encounter Journal entry found for {enc.name}.")
        return 1
    print(f"{enc.name} ({diff_name}), from the in-game Encounter Journal:\n")
    print(format_sections(sections, diff_name, width=args.width))
    if args.corpus:
        _mechanics_from_corpus(enc, diff_name)
    return 0


def _mechanics_from_corpus(enc, diff_name: str) -> None:
    from paf import settings
    from paf.corpus import db
    from paf.corpus.mechanics import fetch_mechanics, mechanic_stats
    from paf.gamedata import spell_names
    from paf.mechanics import abilities, encounter_sections
    from paf.wcl import WCLClient

    diff = settings.DIFFICULTIES[diff_name]
    spec = settings.get("spec")
    con = db.connect()
    print("\nFetching who handles each mechanic in the corpus (interrupts, debuffs on players)...")
    # debuffs are not filtered by the journal ids: logged spell ids often differ from the journal's
    fetch_mechanics(WCLClient(), con, enc.id, diff, [])
    names = {**spell_names(), **dict(con.execute("SELECT id, name FROM ability").fetchall())}
    from paf.mechanics import walk

    sections = encounter_sections(enc.id)
    journal = {s.title.lower(): s for s in abilities(sections, diff_name)}
    # keep boss mechanics only: names from the journal, or abilities cast by enemies in the logs
    boss_names = {s.title.lower() for _, s in walk(sections)}
    boss_names |= {(names.get(r[0]) or "").lower() for r in con.execute(
        "SELECT DISTINCT e.ability_id FROM enemy_cast e JOIN fight f USING(report, fight_id) "
        "WHERE f.encounter_id=? AND f.difficulty=?", (enc.id, diff))}
    stats = [m for m in mechanic_stats(con, enc.id, diff, spec, names)
             if m.kind == "interrupt" or m.name.lower() in boss_names]
    if not stats:
        print("No mechanic data.")
        return
    print(f"\nWho handles what in the top kills ({spec} = share of kills where one of them does it):")
    print(f"  {'mechanic':<32} {'type':<9} {'players':>7} {spec[:8]:>8}  handled by")
    for m in stats:
        if m.kind == "debuff" and m.players_per_kill > 12:
            continue  # raid-wide
        j = journal.get(m.name.lower())
        tag = f" [{', '.join(j.flags)}]" if j and j.flags else ""
        who = ", ".join(f"{s} {v:.0%}" for s, v in m.specs[:3])
        kind = "kick" if m.kind == "interrupt" else ("assigned" if m.assigned else "several")
        print(f"  {m.name[:32]:<32} {kind:<9} {m.players_per_kill:>7.0f} {m.my_spec_rate:>8.0%}  {who}{tag}")
    raid_wide = [m.name for m in stats if m.kind == "debuff" and m.players_per_kill > 12]
    if raid_wide:
        print(f"  raid-wide (everyone): {', '.join(raid_wide[:10])}")


def cmd_validate(args: argparse.Namespace) -> int:
    from paf import settings, simc
    from paf.corpus import db
    from paf.corpus.template import _slug, template_path
    from paf.fight import Fight
    from paf.profile import parse_simc_export
    from paf.validate import summary, validate

    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    raw = Fight.load(fpath)
    fight = load_fight(fpath, verbose=True)
    race = "orc"
    try:
        race = parse_simc_export(_load_profile(None)[0]).header.get("race", race)
    except SystemExit:
        pass
    print(f"Simming the top {settings.get('spec')} players' own characters (gear and talents from their logs) "
          f"on the rebuilt {fight.name}...")
    checks = validate(db.connect(), client, enc.id, diff, settings.get("spec"), fight,
                      simc.new_run_dir(label=f"validate-{_slug(enc.name)}"), players=args.players, race=race)
    for c in checks:
        print(f"  rank {c.rank:<4} real {c.real:>9,.0f}  simulated {c.sim:>9,.0f}  ratio {c.ratio:5.2f}"
              + (f"  (default APL {c.sim_default / c.real:.2f})" if c.sim_default and c.real else ""))
    if args.calibrate and checks:
        from paf.validate import calibrate_movement

        print("\nCalibrating the inferred movement on these players...")
        scale, points = calibrate_movement(checks, fight, simc.new_run_dir(label="validate-movement"))
        for s_, ratio in points:
            print(f"  movement x{s_:<5} simulated / real {ratio:.2f}")
        raw.movement_scale = scale
        raw.save(fpath)
        print(f"Movement durations scaled by {scale:g} in {fpath}")
    s = summary(checks)
    if s:
        lo, med, hi = s
        print(f"\nSimulated / real DPS: median {med:.2f} (range {lo:.2f}-{hi:.2f}).")
        if med < 0.9:
            print("The rebuilt fight is harder than reality (too much movement or too few targets?).")
        elif med > 1.1:
            print("The rebuilt fight is easier than reality (too many targets, too little movement?).")
        else:
            print("The rebuilt fight is in line with the logs (within 10%).")
        print("Race is not in the logs (yours is used); secondary stats are the players' real ones from the logs.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from paf.web import serve

    serve(args.port, open_browser=not args.no_browser)
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

    tg = sub.add_parser("topgear", help="best combination of your items, on real boss fights and/or presets")
    tg.add_argument("--boss", action="append", help="boss whose fight template to use (repeatable)")
    tg.add_argument("--preset", action="append", choices=["patchwerk", "cleave2", "aoe5"],
                    help="standard fight to add (repeatable; default patchwerk when no --boss)")
    tg.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    tg.add_argument("--objective", type=_objective, default=0.0,
                    help="total (default), boss (boss-only damage) or a boss weight like 0.7")
    tg.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    tg.add_argument("--pass1-error", type=float, default=0.3)
    tg.add_argument("--pass2-error", type=float, default=0.15)
    tg.add_argument("--max-combos", type=int, default=1500)
    tg.add_argument("--min-tier", type=int, help="minimum tier pieces (default: as many as equipped, up to 4)")
    tg.add_argument("--top", type=int, default=10)
    tg.set_defaults(func=cmd_topgear)

    ta = sub.add_parser("talents", help="sim the most common talent builds of the top players on your character")
    ta.add_argument("boss")
    ta.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    ta.add_argument("--builds", type=int, default=6, help="number of builds compared (default 6)")
    ta.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    ta.add_argument("--error", type=float, default=0.2)
    ta.set_defaults(func=cmd_talents)

    cp = sub.add_parser("cdplan", help="compare cooldown plans (default APL, on cooldown, hold for adds, "
                                       "top players' timings) on the boss fight")
    cp.add_argument("boss")
    cp.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    cp.add_argument("--objective", type=_objective, default=0.0, help="total (default), boss, or a boss weight")
    cp.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    cp.add_argument("--error", type=float, default=0.1)
    cp.set_defaults(func=cmd_cdplan)

    ca = sub.add_parser("calibrate", help="scale the fight's add counts so your boss damage share matches "
                                          "the top players' logs")
    ca.add_argument("boss")
    ca.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    ca.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    ca.set_defaults(func=cmd_calibrate)

    pl = sub.add_parser("plan", help="your own plan on the fight (moves, soaks, lust, PI) and its optimizer")
    pl.add_argument("boss")
    pl.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    pl.add_argument("--edit", action="store_true", help="open the plan file in your text editor")
    pl.add_argument("--optimize", action="store_true", help="find the best timing of the shiftable moves")
    pl.add_argument("--objective", type=_objective, default=0.0, help="total (default) or boss")
    pl.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    pl.add_argument("--error", type=float, default=0.2)
    pl.set_defaults(func=cmd_plan)

    dr = sub.add_parser("droptimizer", help="value of every item the bosses drop, on the fights you choose")
    dr.add_argument("--boss", action="append", help="boss whose loot to test (repeatable; default: whole raid)")
    dr.add_argument("--fight", action="append", help="boss fight template to sim on (repeatable)")
    dr.add_argument("--preset", action="append", choices=["patchwerk", "cleave2", "aoe5"])
    dr.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    dr.add_argument("--ilvl", type=int, help="item level of the drops (default: median of your equipped items)")
    dr.add_argument("--objective", type=_objective, default=0.0)
    dr.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    dr.add_argument("--error", type=float, default=0.2)
    dr.add_argument("--top", type=int, default=25)
    dr.set_defaults(func=cmd_droptimizer)

    br = sub.add_parser("bonusroll", help="where to use your bonus rolls: each boss of the raid ranked by the gain a "
                                          "bonus roll brings you on average")
    br.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    br.add_argument("--ilvl", type=int, help="item level of the drops (default: median of your equipped items)")
    br.add_argument("--objective", type=_objective, default=0.0)
    br.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    br.add_argument("--error", type=float, default=0.2)
    br.set_defaults(func=cmd_droptimizer, boss=None, fight=None, preset=None, top=25, bonus=True)

    me = sub.add_parser("mechanics", help="boss mechanics from the Encounter Journal (roles, interrupts, mythic)")
    me.add_argument("boss")
    me.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    me.add_argument("--width", type=int, default=110, help="characters of description shown")
    me.add_argument("--corpus", action="store_true",
                    help="also show who handles each mechanic in the corpus kills (fetches ~2 points per kill)")
    me.set_defaults(func=cmd_mechanics)

    asg = sub.add_parser("assigns", help="boss mechanics you can be assigned to, with timings and cost from logs")
    asg.add_argument("boss")
    asg.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    asg.set_defaults(func=cmd_assigns)

    rp = sub.add_parser("raidplan", help="the raid's comp: which spec each player brings and who pads the adds")
    rp.add_argument("boss")
    rp.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    rp.add_argument("--raid", help="link to one of your raid's logs (default: the boss plan's or your guild's)")
    rp.add_argument("--swap-specs", action="store_true",
                    help="let every damage dealer switch to another damage spec of their class")
    rp.add_argument("--options", help='other specs players can play: "Name: Fire Mage, Frost Mage; Name2: ..."')
    rp.set_defaults(func=cmd_raidplan)

    cp = sub.add_parser("comp", help="who hits what in your raid: the adds the top raids cannot skip and who takes "
                                     "them")
    cp.add_argument("boss")
    cp.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    cp.add_argument("--raid", help="link to one of your raid's logs (default: the boss plan's or your guild's)")
    cp.set_defaults(func=cmd_comp)

    wp = sub.add_parser("wipe", help="your best pull of a boss not killed yet: what the deaths and the damage off the "
                                     "boss cost, and when it would have died without them")
    wp.add_argument("boss")
    wp.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    wp.add_argument("--raid", help="link to one of your raid's logs (default: the boss plan's or your guild's)")
    wp.set_defaults(func=cmd_wipe)

    nt = sub.add_parser("night", help="your raid night, pull by pull: deaths, healthstones, health and damage "
                                      "potions")
    nt.add_argument("--raid", help="link to the log (default: your active character's latest, else your guild's)")
    nt.add_argument("--live", action="store_true", help="follow a live log: read the new pulls every 90 s until 30 "
                                                        "minutes pass without one")
    nt.set_defaults(func=cmd_night)

    df = sub.add_parser("diff", help="two pulls of a boss side by side: what went better, for the raid and for a "
                                      "player")
    df.add_argument("boss")
    df.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    df.add_argument("--raid", help="link to one of your raid's logs (default: the boss plan's or your guild's)")
    df.add_argument("--player", help="the player to compare (default: your active character)")
    df.add_argument("--pulls", help="two pull numbers of the log, A,B (default: the player's worst and best pulls "
                                    "without a death, else the best wipe and the kill)")
    df.set_defaults(func=cmd_diff)

    ro = sub.add_parser("rotation", help="a player's rotation in one pull, next to SimulationCraft's default "
                                         "rotation with their gear and talents, in single target, cleave and AoE")
    ro.add_argument("boss")
    ro.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    ro.add_argument("--raid", help="link to one of your raid's logs (default: the boss plan's or your guild's)")
    ro.add_argument("--player", help="the player (default: your active character)")
    ro.add_argument("--pull", type=int, help="a pull number of the log (default: the player's best pull without a "
                                             "death)")
    ro.set_defaults(func=cmd_rotation)

    rd = sub.add_parser("raid", help="pad the adds or stay on the boss, from your raid's composition and DPS")
    rd.add_argument("boss")
    rd.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    rd.add_argument("--raid", help="link to one of your raid's logs (default: your guild's latest log, "
                                   "see `paf config guild`)")
    rd.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    rd.add_argument("--fill", action="store_true",
                    help="measure the specs of your raid that are too rare in the corpus on ~20 of their ranked kills "
                         "each (~10 quota points per kill) instead of estimating them from their rankings")
    rd.set_defaults(func=cmd_raid)
    rv = sub.add_parser("review", help="who does what in your raid's pull (boss, adds, secondary targets), next to "
                                       "the top raids")
    rv.add_argument("boss")
    rv.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    rv.add_argument("--raid", help="link to one of your raid's logs (default: your guild's latest log)")
    rv.set_defaults(func=cmd_review)

    va = sub.add_parser("validate", help="sim the top players' own characters on the rebuilt fight and compare "
                                         "with their real DPS")
    va.add_argument("boss")
    va.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    va.add_argument("--players", type=int, default=6)
    va.add_argument("--calibrate", action="store_true",
                    help="scale the inferred movement so the top players' simulated DPS matches their real DPS")
    va.set_defaults(func=cmd_validate)

    op = sub.add_parser("optimize", help="ideal cooldown plan and play-by-play on the fight, per objective")
    op.add_argument("boss")
    op.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    op.add_argument("--objective", choices=["all", "boss", "total", "adds", "secondary"], default="all")
    op.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    op.add_argument("--error", type=float, default=0.2)
    op.set_defaults(func=cmd_optimize)

    sv = sub.add_parser("serve", help="local web UI: paste your /simc, pick a boss, tick your assignments")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--no-browser", action="store_true")
    sv.set_defaults(func=cmd_serve)

    pr2 = sub.add_parser("prep", help="everything for one boss, as a one-page HTML prep sheet")
    pr2.add_argument("boss")
    pr2.add_argument("--difficulty", choices=["lfr", "normal", "heroic", "mythic"])
    pr2.add_argument("--objective", type=_objective, default=None,
                     help="total, boss, or a boss weight (default: from your raid's log if given, else total)")
    pr2.add_argument("--raid", help="link to one of your raid's logs: composition and DPS decide whether you pad "
                                    "the adds (default: the `raid` line of the boss plan)")
    pr2.add_argument("--profile", help="simc profile (default: the one loaded with `paf profile`)")
    pr2.add_argument("--error", type=float, default=0.2)
    pr2.add_argument("--ilvl", type=int, help="item level of the drops (default: median of your equipped items)")
    pr2.add_argument("--max-combos", type=int, default=300, help="Top Gear combination budget (default 300)")
    pr2.add_argument("--no-gear", action="store_true", help="skip Top Gear and loot (faster)")
    pr2.add_argument("--no-optimize", action="store_true",
                     help="simple cooldown plans instead of the full optimizer (faster)")
    pr2.add_argument("--no-validate", action="store_true",
                     help="skip the validation on the top players' characters (no movement calibration)")
    pr2.add_argument("--refresh", action="store_true", help="collect new kills first")
    pr2.add_argument("--open", action="store_true", help="open the sheet in the browser")
    pr2.add_argument("--refine", action="store_true", help=argparse.SUPPRESS)  # the second pass, run by the first
    pr2.set_defaults(func=cmd_prep)
    return p


def main(argv: list[str] | None = None) -> int:
    import sys

    for stream in (sys.stdout, sys.stderr):  # names from logs can be CJK; never crash on a cp1252 console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    load_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    finally:
        from paf.cache import prune_all
        try:
            prune_all()
        except OSError:
            pass
