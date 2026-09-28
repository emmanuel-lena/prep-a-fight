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
    from paf.fight import PRESETS, Fight
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
        fights.append(FightProfile(fpath.stem, Fight.load(fpath).to_simc()))
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


def cmd_talents(args: argparse.Namespace) -> int:
    from paf import settings, simc
    from paf.corpus import db
    from paf.corpus.template import template_path
    from paf.fight import Fight
    from paf.gamedata import talent_entry_names
    from paf.talent_sim import build_diff, fetch_codes, my_talent_entries, sim_builds, top_builds

    profile_text, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    con = db.connect()
    spec = settings.get("spec")
    builds = top_builds(con, enc.id, diff, spec, n=args.builds)
    if not builds:
        print(f"No ranked {spec} players in the corpus for {enc.name} {diff_name}: run `paf corpus` first.")
        return 1
    fetch_codes(client, con, builds)
    names = talent_entry_names()
    sample = sorted(builds[0].key)
    mine = my_talent_entries(profile_text, sample)
    fights: dict[str, list[str]] = {}
    fpath = template_path(enc.name, diff_name)
    duration = 300.0
    if fpath.is_file():
        fight = Fight.load(fpath)
        fights[fpath.stem] = fight.to_simc()
        duration = fight.duration
    fights["patchwerk"] = ["fight_style=Patchwerk", f"max_time={simc.fmt(duration)}", "desired_targets=1"]
    total_players = sum(b.count for b in builds)
    print(f"{enc.name} {diff_name}: {len(builds)} most common {spec} builds ({total_players} players); "
          f"simming them on your character ({origin})")
    root = simc.new_run_dir(label="talents")
    results = sim_builds(profile_text, builds, fights, root, target_error=args.error)
    header = "  ".join(f"{n[:18]:>18}" for n in fights)
    print(f"\n{'build':<12} {'players':>7} {'med.rank':>8}  {header}")
    print(f"{'your build':<12} {'':>7} {'':>8}  " + "  ".join(f"{'ref':>18}" for _ in fights))
    for i, b in enumerate(builds):
        cols = []
        for res in results.values():
            ps = next((p for p in res.profilesets if p.name == f"b{i}"), None)
            if not ps:
                cols.append(f"{'n/a':>18}")
                continue
            tot = res.delta_pct(ps, "dps")
            has_boss = "prioritydps" in ps.metrics and "prioritydps" in res.baseline
            boss = res.delta_pct(ps, "prioritydps") if has_boss else None
            cell = f"{tot:+.2f}%" + (f" (boss {boss:+.1f}%)" if boss is not None else "")
            cols.append(f"{cell:>18}")
        print(f"{b.label:<12} {b.count:>7} {b.median_rank:>8.0f}  " + "  ".join(cols))
    err = max(r.baseline["dps"].error / r.baseline["dps"].mean * 100 for r in results.values())
    print(f"\nStatistical error: about +/-{err:.2f}% per value.")
    if mine:
        print("\nWhat each build changes compared to yours:")
        for b in builds:
            add, drop = build_diff(mine, set(b.key), names)
            if not add and not drop:
                print(f"  {b.label}: same talents as yours")
                continue
            print(f"  {b.label}: take {', '.join(add) or '-'}")
            print(f"  {'':<{len(b.label)}}  drop {', '.join(drop) or '-'}")
    print(f"\nRuns: {root}")
    return 0


def cmd_cdplan(args: argparse.Namespace) -> int:
    from paf import settings, simc
    from paf.cdplan import apl_lines, dump_apl, parse_apl, plan_lines, standard_plans, tracked_actions
    from paf.corpus import db
    from paf.corpus.analyze import canonical_waves
    from paf.corpus.template import template_path
    from paf.corpus.timeline import build_timeline
    from paf.fight import Fight

    profile_text, origin = _load_profile(args.profile)
    client, enc, diff_name, diff = _encounter_and_difficulty(args)
    fpath = template_path(enc.name, diff_name)
    if not fpath.is_file():
        print(f"No fight template for {enc.name} {diff_name}: run `paf template \"{enc.name}\"` first.")
        return 1
    fight = Fight.load(fpath)
    tl = build_timeline(db.connect(), enc.id, diff, enc.name, diff_name, settings.get("spec"), top=10_000)
    offensive = [a for a in tl.abilities if not a.utility]
    root = simc.new_run_dir(label="cdplan")
    apl = parse_apl(dump_apl(profile_text, root))
    tracked = tracked_actions(apl, [a.name for a in offensive])
    if not tracked:
        print("None of the top players' cooldowns match an action of the default APL.")
        return 1
    cds: dict[str, list[float]] = {}
    long_cds: set[str] = set()
    for ab in offensive:
        act = tracked.get(ab.name)
        if not act:
            continue
        per_player = [[(t, 1, 0.0, [""]) for t in p["casts"].get(ab.id, [])] for p in tl.players]
        cds[act] = [w.t for w in canonical_waves(per_player) if w.support >= 0.4]
        if ab.per_kill <= 6:
            long_cds.add(act)
    print(f"{enc.name} {diff_name}: cooldown plans for {origin}")
    for act, times in cds.items():
        print(f"  {act}: top players use it at {', '.join(_mmss(t) for t in times) or '(no common timing)'}")
    plans = standard_plans(cds, long_cds)
    sets = {p.name: plan_lines(apl, p) for p in plans if p.name != "default"}
    sets = {k: v for k, v in sets.items() if v}
    base = "\n".join([profile_text.rstrip(), *apl_lines(apl)])  # explicit APL: needed for overrides
    res = simc.run(simc.build_input(base, fight.to_simc(), sets), root / "fight", target_error=args.error)
    rows = []
    for p in plans:
        if p.name == "default":
            rows.append((p, 0.0, 0.0))
            continue
        ps = next((x for x in res.profilesets if x.name == p.name), None)
        if ps:
            boss = res.delta_pct(ps, "prioritydps") if "prioritydps" in ps.metrics and "prioritydps" in res.baseline \
                else 0.0
            rows.append((p, res.delta_pct(ps, "dps"), boss))
    w = args.objective
    rows.sort(key=lambda r: -(w * r[2] + (1 - w) * r[1]))
    err = res.baseline["dps"].error / res.baseline["dps"].mean * 100
    print(f"\n{'plan':<26} {'total':>8} {'boss':>8}   on {fight.name}")
    for p, tot, boss in rows:
        print(f"{p.name:<26} {tot:+7.2f}% {boss:+7.2f}%   {p.description}")
    print(f"\nStatistical error: about +/-{err:.2f}%. SimC evaluates these plans; it does not invent new ones.")
    print(f"Runs: {root}")
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
    target = real_boss_share(db.connect(), enc.id, diff, enc.name, spec)
    if target is None:
        print("No damage data for the ranked players in the corpus.")
        return 1
    fight = Fight.load(fpath)
    print(f"Top {spec} players do {target:.0%} of their damage to {enc.name}. Calibrating the add counts...")
    cal = calibrate(profile_text, fight, target, simc.new_run_dir(label="calibrate"))
    for s, share, dps in cal.points:
        print(f"  adds x{s:<4}  boss share {share:5.1%}  total {dps:10,.0f} dps")
    fight.add_scale = cal.scale
    fight.save(fpath)
    print(f"Add counts scaled by {cal.scale:g} in {fpath}")
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
    return p


def main(argv: list[str] | None = None) -> int:
    import sys

    for stream in (sys.stdout, sys.stderr):  # names from logs can be CJK; never crash on a cp1252 console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
