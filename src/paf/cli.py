"""Command-line entry point: ``paf <command>``."""

from __future__ import annotations

import argparse
import subprocess

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
    from paf.corpus.units import fetch_boss_auras, fetch_unit_windows

    boss = main_boss(con, enc.id, diff, enc.name)
    fetch_unit_windows(client, con, enc.id, diff, boss)  # secondary units' real windows (cheap, cached)
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
    ilvl = args.ilvl or round(st.median(i.ilvl for i in profile.equipped.values() if i.ilvl) or 0)
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
    from paf.corpus.template import _slug, build_template, template_path
    from paf.corpus.timeline import build_timeline, render_html
    from paf.droptimizer import run_droptimizer, usable_loot
    from paf.gamedata import encounter_loot, item_classes, item_inventory_types, item_names, item_sets
    from paf.prep_report import PrepData, render
    from paf.profile import parse_simc_export
    from paf.talent_sim import compare_builds
    from paf.topgear import FightProfile, GearPool, run_topgear

    profile_text, origin = _load_profile(args.profile)
    profile = parse_simc_export(profile_text)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    spec = settings.get("spec")
    con = db.connect()
    root = simc.new_run_dir(label=f"prep-{_slug(enc.name)}")

    def step(msg: str) -> None:
        print(f"\n== {msg}", flush=True)

    done = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                       (enc.id, diff)).fetchone()[0]
    if done < 20 or args.refresh:
        step("Collecting the corpus from Warcraft Logs")
        cmd_corpus(argparse.Namespace(boss=args.boss, difficulty=args.difficulty, kills=None, ilvl=None,
                                      list_only=False, retry=False, refetch=False))
    mech_missing = con.execute(
        "SELECT COUNT(*) FROM fight f LEFT JOIN mech_status m USING(report, fight_id) "
        "WHERE f.encounter_id=? AND f.difficulty=? AND f.status='done' AND m.report IS NULL",
        (enc.id, diff)).fetchone()[0]
    if mech_missing:
        from paf.corpus.mechanics import fetch_mechanics

        step(f"Collecting who handles each mechanic ({mech_missing} kills)")
        fetch_mechanics(client, con, enc.id, diff, [])

    step("Analyzing the corpus")
    boss = main_boss(con, enc.id, diff, enc.name)
    rep = analyze(con, enc.id, diff, boss, spec)
    from paf.corpus.units import fetch_boss_auras, fetch_unit_windows

    fetch_unit_windows(client, con, enc.id, diff, boss)
    fetch_boss_auras(client, con, enc.id, diff, boss)
    raw, info = build_template(con, enc.id, diff, boss, spec, diff_name, title=enc.name)
    from paf.notes import refresh_notes, with_notes

    refresh_notes(template_path(enc.name, diff_name), raw)
    fight = with_notes(raw, template_path(enc.name, diff_name), verbose=True)
    d = PrepData(enc.name, diff_name, spec, profile.name or origin, kills=rep.kills, duration=fight.duration)
    d.phases = [(n, m) for n, _, m, _ in rep.phases]
    d.lust, d.pi, d.moving_share = fight.lust_time, fight.power_infusion, info.moving_share
    d.add_share_spec = rep.ranked_add_share[1]
    print(f"  {rep.kills} kills, {len(fight.add_waves)} add waves / targets, duration {_mmss(fight.duration)}")

    step("Calibrating the fight on the logs")
    target = real_boss_share(con, enc.id, diff, boss, spec)
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
    if not args.no_validate:
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
    d.waves = [(w.time, max(1, round(w.count * fight.add_scale)) if w.scalable else w.count, w.lifetime, w.name)
               for w in fight.add_waves]
    d.waves += [(v.start, 0, v.duration, f"{v.name}: boss takes x{v.multiplier:g} damage") for v in fight.vulnerable]
    d.waves.sort()
    planned, ppath = _fight_with_plan(enc, diff_name)
    if ppath is not None:
        fight = planned
        d.assigns = [f"from your plan {ppath.name}"]
    d.fight = fight

    step("Simming your character on the fight")
    real = simc.run(simc.build_input(profile_text, fight.to_simc()), root / "fight", target_error=args.error)
    dummy = simc.run(simc.build_input(profile_text, ["fight_style=Patchwerk", f"max_time={simc.fmt(fight.duration)}",
                                                     "desired_targets=1"]), root / "patchwerk", target_error=args.error)
    d.sim_dps, d.patchwerk_dps = real.baseline["dps"].mean, dummy.baseline["dps"].mean
    d.sim_boss_dps = real.baseline["prioritydps"].mean if "prioritydps" in real.baseline else None

    step("Cooldown timelines of the top players")
    tl = build_timeline(con, enc.id, diff, enc.name, diff_name, spec, top=25)
    reports = data_dir() / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    tl_file = reports / f"timeline-{_slug(enc.name)}-{diff_name}.html"
    tl_file.write_text(render_html(tl), encoding="utf-8")
    d.timeline_file = tl_file.name

    fights = {"boss fight": fight.to_simc(),
              "patchwerk": ["fight_style=Patchwerk", f"max_time={simc.fmt(fight.duration)}", "desired_targets=1"]}
    step("Talent builds of the top players")
    d.talents = compare_builds(profile_text, con, client, enc.id, diff, spec, fights, root / "talents",
                               target_error=args.error)
    tl_all = build_timeline(con, enc.id, diff, enc.name, diff_name, spec, top=10_000)
    from paf.prep_report import _key as cd_key_of

    for ab in tl_all.abilities:  # when the top players cast each cooldown (for the plan timelines)
        d.tops_casts[cd_key_of(ab.name)] = [t for p in tl_all.players for t in p["casts"].get(ab.id, [])]
    d.tops_players = len(tl_all.players)
    d.alignment = tops_alignment_safe(tl_all, fight)
    if args.no_optimize:
        step("Cooldown plans")
        d.plans = compare_plans(profile_text, tl_all, fight, root / "cdplan", target_error=args.error / 2,
                                objective=args.objective)
    else:
        from paf.optimize import mrt_note, optimize_all

        step("Ideal cooldown plan per objective, with sensitivity checks")
        d.optimized, _ = optimize_all(profile_text, fight, root / "optimize", target_error=args.error,
                                      alignment=d.alignment, validation=d.validation[1] if d.validation else None)
        d.mrt = {p.objective: mrt_note(enc.name, p, fight) for p in d.optimized}
        (reports / f"mrt-{_slug(enc.name)}-{diff_name}.txt").write_text("\n\n".join(d.mrt.values()) + "\n",
                                                                         encoding="utf-8")

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
        ilvl = args.ilvl or round(st.median(i.ilvl for i in profile.equipped.values() if i.ilvl) or 0)
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
            d.loot_ilvl = ilvl
            d.loot_error = max((i.error for i in ranked_items[:12]), default=0.0)

    out = reports / f"prep-{_slug(enc.name)}-{diff_name}.html"
    out.write_text(render(d), encoding="utf-8")
    step("Done")
    from paf.prep_report import headline

    for line in headline(d):
        print(f"  - {line}")
    print(f"\nPrep sheet: {out}\nRuns: {root}")
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


def _fight_with_plan(enc, diff_name: str):
    """The boss template with the user's plan file applied (moves, lust, PI), if there is one."""
    from paf.corpus.template import template_path
    from paf.plan import apply_plan, parse_plan

    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        return None, None
    fight = load_fight(fpath)
    ppath = fpath.with_suffix(".plan.txt")
    if ppath.is_file():
        plan = parse_plan(ppath.read_text(encoding="utf-8"))
        if not plan.empty:
            fight = apply_plan(fight, plan)
            if plan.assigns:
                from paf import settings
                from paf.assigns import apply_assigns, load_mechanics
                from paf.corpus import db

                mechs = load_mechanics(db.connect(), enc.id, settings.DIFFICULTIES[diff_name], settings.get("spec"))
                fight, notes = apply_assigns(fight, mechs, plan.assigns)
                for n in notes:
                    print(f"  assign: {n}")
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
    from paf.corpus.template import _slug
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
    print_alignment(enc, diff_name, diff, fight)
    notes = data_dir() / "reports" / f"mrt-{_slug(enc.name)}-{diff_name}.txt"
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
    pr2.add_argument("--objective", type=_objective, default=0.0, help="total (default), boss, or a boss weight")
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
