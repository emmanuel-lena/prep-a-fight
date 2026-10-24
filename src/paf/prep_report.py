"""The one-page boss prep sheet (HTML), assembled from the other modules' results."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime

from paf import bossguide, icons, raidneed, theme
from paf.theme import diff_pill
from paf.wowhead import SCRIPT as WH_SCRIPT
from paf.wowhead import link, linkify

e = html.escape


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def _pct(v: float | None, digits: int = 2, err: float = 0.0) -> str:
    """A gain in %, green or red only when it stands out of the noise (`err`, the sims' error)."""
    if v is None:
        return "-"
    v = round(v, digits) + 0.0  # a gain under the shown precision is none: "0.0%", neutral, never "-0.0%"
    cls = "" if abs(v) <= 2 * err else "pos" if v > 0 else "neg" if v < 0 else ""
    return f'<span class="{cls}">{v:+.{digits}f}%</span>' if v else f"<span>{0:.{digits}f}%</span>"


@dataclass
class RaidInfo:
    """Your raid and the adds (paf.raidneed)."""
    report: str
    fight: str  # which pull the composition and DPS come from
    players: int
    you: tuple[str, float]  # spec, DPS
    you_found: bool  # False: you are not in that log, a player of your spec at the raid's median DPS is used
    verdicts: list = field(default_factory=list)  # paf.raidneed.AddVerdict
    objective: str | None = None  # "boss" or "pad"
    cleavers: list = field(default_factory=list)  # (name, spec, DPS on the main adds)
    archetypes: dict = field(default_factory=dict)  # "AoE / funnel" / "flexible" / "single target" -> players
    your_archetype: str = ""
    your_profile: object | None = None  # paf.raidneed.SpecProfile of your spec (total vs boss DPS rankings)
    estimated: list = field(default_factory=list)  # specs whose share on the adds is estimated from the rankings
    logged_as: str = ""  # your spec in that log when it is another one ("Assassination Rogue")


@dataclass
class PrepData:
    boss: str
    difficulty: str
    spec: str
    character: str
    kills: int = 0
    duration: float = 0.0
    phases: list[tuple[str, float]] = field(default_factory=list)
    game_phases: list[tuple[str, float]] = field(default_factory=list)  # Warcraft Logs' own, for NSRT's counter
    waves: list[tuple[float, int, float, str]] = field(default_factory=list)
    lust: float | None = None
    # the top raids' Bloodlust spots (paf.corpus.lust.Spot) with what each one gives you in the sim:
    # [(spot, total damage %, boss damage %)] against the lust the fight uses; lust_pick: the raid lead's
    lust_spots: list = field(default_factory=list)
    lust_pick: str = ""
    lust_noise: float = 0.0  # +- % of a spot's gain (the sims' noise)
    # the kill times this boss is planned for (issue #26): [(who kills that long, seconds, sheet file)]; kill_now:
    # this sheet's one. The fight tab switches between them.
    kill_times: list = field(default_factory=list)
    kill_now: int = 0
    pi: list[float] = field(default_factory=list)
    moving_share: float = 0.0
    add_share_spec: float | None = None  # median share of the spec's damage on adds (logs)
    boss_share_real: float | None = None
    add_scale: float = 1.0
    sim_dps: float | None = None
    sim_boss_dps: float | None = None
    patchwerk_dps: float | None = None
    timeline_file: str = ""
    talents: object | None = None  # paf.talent_sim.TalentComparison
    specs: dict | None = None  # paf.specgear.to_json: your class's damage specs on this fight (the verdict first)
    plans: object | None = None  # paf.cdplan.PlanComparison
    gear: list[tuple[str, dict[str, float], float]] = field(default_factory=list)  # changes, per fight, weighted
    gear_fights: list[str] = field(default_factory=list)
    gear_error: float = 0.0
    gear_plan: str = ""  # which cooldown plan the Top Gear was simmed with ("" = default APL)
    # item, slot, delta as a single swap on the equipped set, delta in your best sets (None = not measured)
    loot: list[tuple[str, str, float, float | None]] = field(default_factory=list)
    loot_ilvl: int = 0
    loot_error: float = 0.0
    notes: list[str] = field(default_factory=list)
    optimized: list = field(default_factory=list)  # paf.optimize.Plan per objective
    mrt: dict[str, str] = field(default_factory=dict)  # objective -> MRT note
    nsrt: dict[str, str] = field(default_factory=dict)  # objective -> Northern Sky Raid Tools reminders
    defensives: object | None = None  # paf.defensives.Defensives: when the top players press theirs
    alignment: list = field(default_factory=list)  # paf.optimize.Alignment
    fight: object | None = None  # paf.fight.Fight used by the sims
    assigns: list[str] = field(default_factory=list)  # notes of the player's assignments
    validation: tuple[float, float, float] | None = None  # simulated / real DPS of the top players (min, median, max)
    tops_casts: dict[str, list[float]] = field(default_factory=dict)  # cooldown key -> top players' cast times
    tops_players: int = 0
    links: dict[str, str] = field(default_factory=dict)  # spell / item name -> Wowhead reference
    cd_names: dict[str, str] = field(default_factory=dict)  # cooldown key (ascendance, trinket1) -> in-game name
    raid: RaidInfo | None = None
    goal: str | None = None  # "boss" / "total" when the player chose it (else the raid's log decides)
    icons: dict[str, str] = field(default_factory=dict)  # spell / item / cooldown key name -> game icon file
    boss_casts: list[tuple[str, list[float]]] = field(default_factory=list)  # boss spell, typical times
    precast: list[str] = field(default_factory=list)  # cooldowns the priority list casts before the pull
    movement: object | None = None  # paf.movement.Movement: move for the strategy, stand still otherwise
    review: object | None = None  # paf.review.Review: your own log next to the top players' (casting, moving)
    raid_tools: dict = field(default_factory=dict)  # comp / wipe / night: paf.workshop_views data
    partial: tuple[int, int] | None = None  # a first pass: (kills used, kills found); the full pass follows
    imported: bool = False  # the character was read from a log (no bags): no gear nor loot until /simc
    class_name: str = ""  # e.g. "shaman" (class icon in the header)
    guide_summary: str = ""  # html: the boss in 60 seconds (Encounter Journal, your role)
    guide_abilities: str = ""  # html: every ability phase by phase, with what the logs add
    role_bullets: list[str] = field(default_factory=list)  # what the journal tells your role to do
    actions: list = field(default_factory=list)  # paf.actions.Action: what the top players do, from their logs
    ability_roles: dict[str, list[str]] = field(default_factory=dict)  # boss ability -> roles the journal flags
    mech_times: dict[str, list[float]] = field(default_factory=dict)  # mechanic -> typical times (paf.assigns)
    export: dict[str, str] = field(default_factory=dict)  # plan label ('' = fight only) -> simc lines (Raidbots)


PALETTE = ["#c89933", "#8e6a9b", "#4f8a8b", "#5b8fb0", "#b8ad3c", "#b0577f", "#3f6fa0", "#6c9a5b", "#74526c"]


def _key(label: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")


def alive(fight, t: float, life: float) -> float:
    """How long an add wave lives: its lifetime in the logs, cut at the end of an intermission it belongs to (several
    successive adds of an intermission can merge into one long window in the corpus)."""
    for w in (fight.invulnerable if fight is not None else []):
        if w.start - 3 <= t <= w.start + w.duration:
            return min(life, w.start + w.duration - t)
    return life


def plan_timeline_svg(plan, fight, tops: dict[str, list[float]], tops_players: int, px: float = 1.4,
                      names: dict[str, str] | None = None, phases: list | None = None,
                      links: dict[str, str] | None = None, legend: bool = True) -> str:
    """Lorrgs-like strip for a plan: the fight (phases, add waves, vulnerability windows, lust) then one row per
    cooldown with the plan's casts (dots) over the top players' casts of the same cooldown (bars)."""
    if fight is None or not plan.timeline:
        return ""
    dur = fight.duration
    px = max(px, 930 / max(dur, 1))  # the fight across the card's width, whatever its length
    W = int(dur * px) + 200
    x0 = 190  # room for a trinket's whole name ("Vile Vial of Volatile Venom")

    def x(t: float) -> float:
        return round(x0 + t * px, 1)

    rows: list[str] = []
    y = 18
    # time axis
    axis = "".join(f'<line x1="{x(s)}" y1="14" x2="{x(s)}" y2="100%" stroke="var(--line)"/>'
                   + (f'<text x="{x(s) + 2}" y="11" font-size="10" fill="var(--muted)">{_mmss(s)}</text>'
                      if dur - s > 30 else "")  # a tick label near the kill's: the kill's alone ("4:0ll 4:15")
                   for s in range(0, int(dur) + 1, 60)) + (
        f'<line x1="{x(dur)}" y1="14" x2="{x(dur)}" y2="100%" stroke="var(--muted)" stroke-dasharray="3 3"/>'
        f'<text x="{x(dur) - 2}" y="11" font-size="10" fill="var(--muted)" text-anchor="end">kill {_mmss(dur)}</text>')
    # fight strip
    fight_row = [f'<text x="4" y="{y + 12}" font-size="11" fill="var(--fg)">Fight</text>']
    for name, s in sorted(phases or [], key=lambda p: p[1])[1:]:  # the stages, where raiders think in them
        axis += (f'<line x1="{x(s)}" y1="14" x2="{x(s)}" y2="100%" stroke="var(--fg)" stroke-opacity=".35" '
                 f'stroke-dasharray="2 4"><title>{e(name)} {_mmss(s)}</title></line>')
    for w in fight.add_waves:
        fight_row.append(f'<rect x="{x(w.time)}" y="{y}" width="{max(2, alive(fight, w.time, w.lifetime) * px):.1f}" height="16" '
                         f'fill="#6c9a5b" opacity="0.4"><title>{_mmss(w.time)} adds x{w.count}</title></rect>')
    for v in fight.vulnerable:
        fight_row.append(f'<rect x="{x(v.start)}" y="{y}" width="{max(2, v.duration * px):.1f}" height="16" '
                         f'fill="#c89933" opacity="0.5"><title>{e(v.name)} x{v.multiplier:g}</title></rect>'
                         f'<text x="{x(v.start) + 2}" y="{y + 12}" font-size="10" fill="var(--fg)">x{v.multiplier:g}</text>')
    for w in fight.invulnerable:
        fight_row.append(f'<rect x="{x(w.start)}" y="{y}" width="{w.duration * px:.1f}" height="16" fill="#868e96" '
                         f'opacity="0.4"><title>boss away</title></rect>')
    if fight.lust_time is not None:
        fight_row.append(f'<rect x="{x(fight.lust_time)}" y="{y - 2}" width="{40 * px:.1f}" height="3" fill="#c2410c">'
                         f'<title>Bloodlust {_mmss(fight.lust_time)}</title></rect>')
    rows.append("".join(fight_row))
    y += 26
    # one row per cooldown
    labels: list[str] = []
    for _, label in plan.timeline:
        if label not in labels:
            labels.append(label)
    for label in sorted(labels, key=_key):  # one order for every plan's chart: compared row by row
        color = PALETTE[sum(map(ord, _key(label))) % len(PALETTE)]  # one color per cooldown, the same in every chart
        by_link = {_key(n): n for n in (links or {})}  # the game's own name of a racial or a trinket
        small = {"of", "the", "and", "a", "in", "on", "to"}  # a name's small words stay small, as the game writes them
        words = label.replace("_", " ").split()
        titled = " ".join(w if i and w.lower() in small else w[:1].upper() + w[1:] for i, w in enumerate(words))
        shown = (names or {}).get(_key(label)) or by_link.get(_key(label)) or titled
        full, shown = shown, shown if len(shown) <= 30 else shown[:29] + "…"
        row = [f'<text x="4" y="{y + 12}" font-size="11" fill="var(--fg)"><title>{e(full)}</title>{e(shown)}</text>']
        tt = tops.get(_key(label)) or []
        if tt and tops_players:
            bins: dict[int, int] = {}
            for t in tt:
                if t <= dur:  # a slower kill's casts past this one's end: off the drawing (DPS round 14)
                    bins[int(t // 5)] = bins.get(int(t // 5), 0) + 1
            peak = max(bins.values(), default=1)
            for b, n in bins.items():
                h = 16 * n / peak
                row.append(f'<rect x="{x(b * 5)}" y="{y + 16 - h:.1f}" width="{5 * px - 0.5:.1f}" height="{h:.1f}" '
                           f'fill="{color}" opacity="0.25"><title>top players: {n} cast{"s" if n != 1 else ""} at {_mmss(b * 5)}</title></rect>')
        for t, lab in plan.timeline:
            if lab == label:
                row.append(f'<circle cx="{x(t)}" cy="{y + 8}" r="5" fill="{color}" stroke="var(--card)" stroke-width="1.5">'
                           f'<title>{e(label)} {_mmss(t)}</title></circle>')
        rows.append("".join(row))
        y += 22
    return (f'<div class="scroll"><svg class="plan-tl" viewBox="0 0 {W} {y + 4}" width="100%" '
            f'style="font-family:system-ui;max-width:{W * 1.15:.0f}px">{axis}'
            f'{"".join(rows)}</svg></div>' + ("" if not legend else  # once a tab (the owner: less text)
            '<p class="small muted">Dots: this plan (one simulated pull). Pale bars: '
            'when the top players cast the same cooldown.'
            + (" Green: add waves." if fight.add_waves else "")
            + (" Gold: boss vulnerability windows (x = damage taken)." if fight.vulnerable else "")
            + (" Grey: boss away." if fight.invulnerable else "")
            + (" Orange line: Bloodlust." if fight.lust_time is not None else "")
            + (" Dashed lines: stage changes." if phases and len(phases) > 1 else "")
            + (" A press before the pull is drawn at 0:00." if any(t < 0.5 for t, _l in plan.timeline) else "") + "</p>"))


def _base(name: str) -> str:
    return name.split(" (after")[0].split(" (boss aura)")[0].strip()


def cd_name(d: PrepData, key: str) -> str:
    """A cooldown key of the plans as the player knows it (the trinket's name, not 'trinket1')."""
    k = key.replace("use_item:", "")
    if d.cd_names.get(key) or d.cd_names.get(k):
        return d.cd_names.get(key) or d.cd_names.get(k)
    small = {"of", "the", "and", "a", "an", "in", "on", "to"}  # "Vile Vial of Volatile Venom", not "Of"
    words = k.replace("_", " ").split()
    return " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))


def burst_names(d: PrepData) -> tuple[str, str]:
    """(vulnerability windows, separate priority targets) of the fight, by name."""
    f = d.fight
    if f is None:
        return "", ""
    vuln = list(dict.fromkeys(_base(v.name) for v in f.vulnerable if v.name))
    units = list(dict.fromkeys(_base(w.name) for w in f.add_waves if not w.scalable and w.name))
    return " / ".join(vuln), " / ".join(units)


def rule_phrase(d: PrepData, rule: str) -> str:
    """A rule of the optimizer in the player's words, with the fight's real names."""
    import re

    vuln, units = burst_names(d)
    waves = ", ".join(dict.fromkeys(re.sub(r"\s*\([^)]*\)", "", w.name).strip() or "adds"
                                    for w in (d.fight.add_waves if d.fight is not None else []) if w.scalable))
    # the add waves a rule is about; a boss unit played as a wave (an Echo) has its own burst plan
    m = re.fullmatch(r"hold_(adds|vulnerable)_(\d+)", rule)
    if m:
        what = "the next add wave" if m.group(1) == "adds" else (vuln or "the damage amp")
        return f"hold for {what} if within {m.group(2)} s, else use it"  # short, everywhere (DPS round 43)
    return {"default": "as SimC's default priority list", "on_cooldown": "the moment it is ready (the default list can wait some seconds)",
            "add_waves": f"only on add waves{f' ({waves})' if waves else ''}", "secondary_targets": f"only on {units or 'the secondary targets'}",
            "vulnerable_windows": f"only during {vuln or 'the damage amp'}", "lust_pi": "with Bloodlust",
            "not_before_move": "not in the 4 s before moving"}.get(rule, rule.replace("_", " "))


def objective_name(d: PrepData, objective: str) -> str:
    _, units = burst_names(d)
    return {"boss": "Boss damage", "total": "Pad (total damage)", "adds": "Damage to adds",
            "secondary": f"Burst {units or 'the secondary targets'}"}.get(objective, objective)


def headline(d: PrepData) -> list[str]:
    """The few things to remember, computed from the results, in the player's words (one string per point,
    '\\n' separates its lines)."""
    out = []
    if d.raid and d.raid.verdicts:
        v = d.raid.verdicts[0]
        what = "stay on the boss" if d.raid.objective == "boss" else "pad the adds"
        out.append(f"With your raid: {what}. {v.add.name}: {v.reason}.")
    if d.talents and d.talents.rows:
        fight = d.talents.fights[0]
        best = max(d.talents.rows, key=lambda r: r.per_fight.get(fight, (-1e9, None))[0])
        gain = best.per_fight.get(fight, (0.0, None))[0]
        if gain > 2 * d.talents.error:
            take = ", ".join([x for x in best.add if x not in getattr(best, "drop", [])][:4]) or "-"
            out.append(f"Talents: {best.build.label} ({best.build.count} top players) gives {gain:+.1f}% on this "
                       f"fight; it takes {take}.")
        else:
            out.append("Talents: your build is as good as the top players' builds on this fight.")
    short = {"boss": "boss", "total": "pad", "secondary": "burst"}
    done: dict[tuple, int] = {}  # same rules as an objective already listed -> merged into it
    for p in d.optimized:
        if p.objective == "adds" or p.gain <= 2 * p.error:
            continue
        sig = tuple(sorted((k, r.name) for k, r in p.choice.items() if r.name != "default"))
        if sig in done:
            i = done[sig]
            head, _, rest = out[i].partition(": ")
            out[i] = f"{head} and {short.get(p.objective, p.objective)}, same plan: {rest}"
            continue
        done[sig] = len(out)
        by_rule: dict[str, list[str]] = {}
        for k, r in p.choice.items():
            if r.name != "default":
                by_rule.setdefault(rule_phrase(d, r.name), []).append(cd_name(d, k))
        others = ", ".join(f"{short.get(o, o)} {v:+.1f}%" for o, v in p.totals.items() if o not in (p.objective, "adds"))
        trust = ("not checked on harder variants of the fight" if not p.sensitivity else
                 "holds up on pessimistic variants of the fight" if p.robust and not p.flags
                 else "check the warnings in its plan below")
        lines = [f"{objective_name(d, p.objective)}: {p.gain:+.1f}% vs SimC's default priority list"
                 + (f" ({others})" if others else "") + f"; {trust}."]
        lines += [f"{', '.join(cds)}: {phrase}" for phrase, cds in by_rule.items()]
        out.append("\n".join(lines))
    held = [a for a in d.alignment if a.units_cover and a.in_units > a.units_cover * 1.5 and a.in_units - a.units_cover > 0.1]
    if held:
        vuln, units = burst_names(d)
        out.append("The top players keep " + ", ".join(a.ability for a in held) + " for "
                   + (" / ".join(x for x in (vuln, units) if x) or "the burst windows") + ".")
    if d.plans and d.plans.rows:
        p, tot, _ = d.plans.rows[0]
        if p.name != "default" and tot > 2 * d.plans.error:
            out.append(f"Cooldowns: '{p.name.replace('_', ' ')}' ({p.description}) gives {tot:+.1f}%.")
        else:
            out.append("Cooldowns: the default priority list is already the best plan tested.")
    if d.gear:
        changes, _, w = d.gear[0]
        if w > 2 * d.gear_error:
            out.append(f"Gear for this fight{' with your assignments' if d.assigns else ''} ({w:+.2f}%): "
                       + "\n".join(changes.split("; ")))
        else:
            out.append("Gear: your equipped set is already the best among your items on this fight.")
    if d.loot:
        item, slot, simple, real = d.loot[0]
        delta = real if real is not None else simple
        if delta > 2 * d.loot_error:
            out.append(f"Loot to hope for: {item} ({slot}, {delta:+.2f}% at item level {d.loot_ilvl}).")
    return out


CSS = theme.CSS + bossguide.CSS + theme.style("prep")


def kpi_tiles(d: PrepData) -> str:
    """The prep at a glance: model check, your raid's verdict, cooldowns, gear, talents."""
    tiles = []

    def tile(label: str, value: str, sub: str, cls: str = "") -> None:
        tiles.append(f'<div class="tile kpi {cls}"><div class="l">{e(label)}</div><div class="v">{value}</div>'
                     f'<div class="s">{e(sub)}</div></div>')

    if d.goal in ("boss", "total"):
        tile("Your role", "Boss" if d.goal == "boss" else "Pad the adds", "your choice for this prep")
    elif d.raid and d.raid.objective:
        tile("Your role", "Boss" if d.raid.objective == "boss" else "Pad the adds",
             "the others cover the adds" if d.raid.objective == "boss" else "your raid needs your damage on them")
    want = wanted(d)
    plans = [p for p in d.optimized if p.objective in ("boss", "total")]
    best = next((p for p in plans if p.objective == want), None) or (max(plans, key=lambda p: p.gain) if plans else None)
    if best is not None:
        tile("Cooldown plan", f"{best.gain:+.1f}%", f"{_goal(best.objective)} damage, vs using them on cooldown",
             "good" if best.gain > 2 * best.error else "")
    r = best_build(d)
    if r is not None:
        g = r.per_fight.get(d.talents.fights[0], (0.0, None))[0]
        tile("Talents", f"{g:+.1f}%" if g > 2 * d.talents.error else "OK",
             f"{r.build.label}, vs your current talents" if g > 2 * d.talents.error
             else "your talents match the top players'", "good" if g > 2 * d.talents.error else "")
    if d.gear:
        w = d.gear[0][2]
        tile("Gear", f"{w:+.2f}%" if w > 2 * d.gear_error else "Best",
             "swaps from your bags, vs your equipped gear" if w > 2 * d.gear_error
             else "no swap from your bags beats it beyond the error", "good" if w > 2 * d.gear_error else "")
    conf = ""
    if d.validation:
        lo, med, hi = d.validation
        level = "high" if abs(med - 1) <= 0.05 else "medium" if abs(med - 1) <= 0.12 else "low"
        gap = abs(med - 1)
        meaning = ("the sim matches reality: trust the gains below." if level == "high" else
                   f"the sim is off by {gap:.0%}: trust which option wins more than the exact %." if level == "medium"
                   else f"the sim is off by {gap:.0%}: this fight is badly rebuilt for your spec, use the gains as "
                        f"hints only.")
        conf = (f'<p class="conf small"><span class="pill {"on" if level == "high" else ""}">Confidence: {level} '
                f'&middot; sim {med:.0%} of real</span> <b>{e(meaning)}</b> <span class="muted">The top players, simmed '
                f'on this rebuilt fight with their own gear, get {med:.0%} of the DPS they really did (100% = perfect). '
                f'Gains are % of your DPS.</span></p>')
    return (f'<div class="kpis">{"".join(tiles)}</div>' if tiles else "") + conf


def wanted(d: PrepData) -> str | None:
    """The objective to follow: the player's own choice, else the verdict from the raid's log, else none."""
    if d.goal in ("boss", "total"):
        return d.goal
    if d.raid and d.raid.objective:
        return "boss" if d.raid.objective == "boss" else "total"
    return None


def _goal(objective: str) -> str:
    return {"boss": "boss", "total": "total (pad)", "secondary": "burst"}.get(objective, objective)


def simmed_note(d: PrepData) -> str:
    """What the "Simmed" column of the add waves is, in the direction the calibration went."""
    if (d.add_scale or 1) >= 1:
        return '"Simmed": the adds of the wave in the sims, at their real number (the logs\' count).'  # no claim
        # on the boss share here: the measured one is in the paragraph below (a review: "more" read against 70% vs 73%)
    return (f'"Simmed": the adds of the wave in the sims, counted at ×{d.add_scale:g} of their real number to bring '
            "the sims' boss share toward the top players' (SimC hits every add in range).")


def healers_left(r) -> tuple[int, bool]:
    """The log's players no add group counts (its healers), and whether your other character is one of the log's:
    then it is you, not a healer (DPS round 47: Ixuu the rogue counted among the healers)."""
    swapped = bool(r.logged_as) and not r.you_found
    return r.players - sum(len(ps) for ps in r.archetypes.values()) - int(swapped), swapped


def raid_section(r: RaidInfo, gear: bool = True) -> str:
    you = (f"you ({e(r.you[0])}, {r.you[1] / 1000:,.0f}k DPS"
           + (f" <span class='pill'>your log: {e(r.logged_as)}</span>" if r.logged_as else "") + ")" if r.you_found else
           f"{'an' if r.you[0][:1].lower() in 'aeiou' else 'a'} {e(r.you[0])} at your raid's median DPS ({r.you[1] / 1000:,.0f}k; " + (f"you are in that log as {e(r.logged_as)}, swapped out)" if r.logged_as else f"you are not in that log as {e(r.you[0])})"))  # another spec of yours may be
    head = (f"<p class='small'>From your raid's log <a href='https://www.warcraftlogs.com/reports/{e(r.report)}' "
            f"target='_blank' rel='noopener'>{e(r.report)}</a> ({e(r.fight)}, {r.players} players), with {you}.</p>")
    if not r.verdicts:
        return (f"<h2>Your raid and the adds</h2><div class='card'>{head}<p>No add takes a real share of the damage "
                f"on this boss: nothing to decide, play for the boss.</p></div>")
    rows = "".join(
        f"<tr><td>{e(v.add.name)}</td><td class='n'>{v.without_you:.0%}</td><td class='n'>{v.with_you:.0%}</td>"
        f"<td class='n'>{v.low:.0%}</td><td><b>{'boss' if v.verdict == 'boss' else 'pad'}</b>: "
        f"{_without_shares(e(re.sub(r'^(pad them|stay on the boss)[:,] *', '', raidneed.readable(v.reason))))}"
        "</td></tr>"  # its shares are the row's columns (DPS round 47: said twice)
        for v in r.verdicts)
    def chip(p: str) -> str:  # "Poilodibz (Blood Death Knight)": the spec's icon, the name; the spec on hover
        name, _, spec = p.partition(" (")
        spec = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", spec.rstrip(")"))
        return f"<span class='chip' title='{e(spec)}'>{icons.spec_img(spec)}{e(name)}</span>"
    groups = "".join(f"<li><b>{e(k)} ({len(ps)})</b><span>{''.join(chip(p) for p in ps)}</span></li>"  # label, chips
                     for k, ps in r.archetypes.items() if ps)
    rest, swapped = healers_left(r)
    if groups and rest > 0:  # every player of the log accounted for
        groups += f"<li><b>healers ({rest})</b><span class='plain'>not counted for the adds</span></li>"
    if groups and swapped:
        groups += (f"<li><b>you (1)</b><span class='plain'>in the log as {e(r.logged_as)}, swapped for the spec you "
                   "prepare</span></li>")
    what = "the cooldown plan and the gear on this sheet are" if gear else "the cooldown plan on this sheet is"
    verdict = (f"Stay on the boss: {what} the one{'s' if gear else ''} for boss damage." if r.objective == "boss"
               else f"Pad the adds: {what} the one{'s' if gear else ''} for total damage.")
    mine = f" On this boss your spec is <b>{e(r.your_archetype)}</b>." if r.your_archetype else ""
    if r.objective != "boss" and "single" in (r.your_archetype or ""):  # why a single-target spec still pads
        mine += (" Single target or not, your raid lacks the cleave to kill the adds in time: when they are up, "
                 "your damage on them counts more than on the boss.")
    p = r.your_profile
    build = ""
    if p is not None:
        build = (f"<p class='small'>Your spec's top 100 on this boss: {p.dps / 1000:,.0f}k total DPS vs "
                 f"{p.boss_dps / 1000:,.0f}k for the top 100 by boss DPS ({p.boss_share:.0%}, Warcraft Logs counting every boss unit as the boss); {p.same_players} players "
                 f"are in both. ")
        build += (f"The pad build takes {e(', '.join(p.pad_talents) or '-')}; the boss build takes "
                  f"{e(', '.join(p.boss_talents) or '-')}.</p>" if p.pad_talents or p.boss_talents else
                  "Same talents in both: no separate pad build.</p>")
    est = (f"<p class='small muted'>Estimated from their total-DPS vs boss-DPS rankings (too rare in the "
           f"corpus): {e(', '.join(r.estimated))}.</p>" if r.estimated else "")
    return f"""<h2>Your raid and the adds</h2><div class="card">{head}
<p><b>{verdict}</b>{mine}</p>
<div class="scroll"><table><tr><th>Adds</th><th class="n">Your raid without you</th><th class="n">With you</th>
<th class="n">Top raids' weakest quarter</th><th>Verdict</th></tr>{rows}</table></div>
<p class="small muted">Damage your raid puts on these adds, as a share of the top raids' (their median = 100%).</p>
<p class="small">Your raid on this boss, by what each spec does with the adds:</p><ul class="small grp">{groups}</ul>{est}{build}
<h4 class="small">How it is computed</h4><p class="small muted">Measured: on this boss, each spec puts
a share of its damage on these adds while they are up (from the ranked kills): well above the median of all players =
AoE / funnel, well below = single target. Computed: your raid's damage on the adds = every player's DPS in your log x
their spec's share; the same for every top raid gives the reference range. Rule (not a measurement): if your raid
without you is within the top raids' range (above their weakest quarter), the others cover the adds and you stay on
the boss; otherwise you pad. Not promised: how long the adds will live. In the top kills it depends on the mechanics
and the strategy, not on the raid's DPS (checked: no correlation). Top players pad whatever their raid (they are
ranked on their own DPS), so their logs alone cannot tell what your raid needs.</p></div>"""


@dataclass
class Suggestion:
    severity: str  # "major" (>= 3%), "moderate" (>= 1%), "minor", "info"
    title: str  # html
    details: list[str] = field(default_factory=list)  # html lines
    gain: float | None = None
    icon: str = ""  # game icon file name
    metric: str = ""  # what the gain is of ("boss", "total", "burst"), when it is not your plain damage
    base: str = "SimC's default list"  # what the gain is against


THIN_CORPUS = 50  # fewer ranked kills than this: say the data is thin


def best_build(d: PrepData):
    """The best talent build in the sim, however many top players play it: the sim decides, not popularity
    (None if none)."""
    if not d.talents or not d.talents.rows:
        return None
    fight = d.talents.fights[0]
    return max(d.talents.rows, key=lambda r: r.per_fight.get(fight, (-1e9, None))[0])


ADDONS = {"MRT": "to paste in Method Raid Tools", "NSRT": "to paste in Northern Sky Raid Tools"}


def copy_button(text: str, label: str) -> str:
    """A copy button; an addon's note says which addon on hover (review 36: a line beside the buttons)."""
    tip = next((t for k, t in ADDONS.items() if k in label.split()), "")
    tip = f' title="{e(tip)}"' if tip else ""
    return f'<button type="button" class="btn ghost copy" data-copy="{e(text)}"{tip}>{e(label)}</button>'


def _fallen(p) -> bool:
    from paf.simple import fallen

    return fallen(p)


def simple_plan(d):
    from paf import simple

    return simple._plan(d)


def off_tops(d, p) -> list[str]:
    """The plan's cooldown casts that most top players make at another moment, close by: a sign the rebuilt fight
    misses what they wait for (a unit that comes up earlier, an immunity...). Any spec, any boss."""
    out, seen, by = [], {}, {}
    for t, label in p.timeline:
        by.setdefault(label, []).append(t)
    short = {k for k, ts in by.items()  # a short cooldown drifts with the rotation: its moment says nothing
             if len(ts) > 1 and sorted(b - a for a, b in zip(ts, ts[1:], strict=False))[(len(ts) - 1) // 2] < 60}
    for t, label in p.timeline:
        key = label.lower().replace(" ", "_")
        ts, n = d.tops_casts.get(key), d.tops_players
        if not ts or not n or t <= 5 or label in short or seen.get(key, 0) >= 2:
            continue
        here, there = tops_moment(ts, n, t)
        if here >= 0.25 or there is None:  # a fair share of them press it then too, or no other moment
            continue
        seen[key] = seen.get(key, 0) + 1
        out.append(f"{cd_name(d, key)}: the plan presses it at {_mmss(t)}, {there[0]:.0%} of the top "
                   f"players at about {_mmss(there[1])}.")
    return out


def tops_moment(ts: list[float], players: int, t: float) -> tuple[float, tuple[float, float] | None]:
    """The top players around a press at t: the share of them pressing it within 4 s, and the moment 6 to 30 s away
    where most of them (half at least) press it instead: (share, typical time), or None."""
    here = min(1.0, sum(abs(x - t) <= 4 for x in ts) / players)
    peak = max(((sum(abs(x - c) <= 4 for x in ts), c) for c in ts if 6 <= abs(c - t) <= 30), default=None)
    if peak is None or peak[0] / players < 0.5:
        return here, None
    around = sorted(x for x in ts if abs(x - peak[1]) <= 4)
    return here, (min(1.0, peak[0] / players), around[len(around) // 2])


def _stall(d, p) -> str:
    """A plan that holds a cooldown and loses far more boss damage than any cooldown is worth: SimC's default rotation
    ties other spells to that cooldown, so they stop while it is held (Subtlety: Shadow Dance waits on Shadow Blades)."""
    held = [d.cd_names.get(k, k) for k, r in p.choice.items() if r.name != "default"]
    boss = p.totals.get("boss") if p.objective != "boss" else p.gain
    if held and boss is not None and boss < -15:
        return ("Sim artifact: a direction, not a number.")  # the why on its hover (stall_why); no number: the
        # card's line gives it (DPS confirm round 7; round 42: two lines)
    return ""


def stall_why(d, p) -> str:
    """The reason _stall gives its short line, for its hover."""
    held = [d.cd_names.get(k, k) for k, r in p.choice.items() if r.name != "default"]
    return (f"SimC's default rotation ties other spells to {held[0]}, so they stop while it is held and pile up for "
            "the moment it is pressed: the real boss loss is lower and the gain likely overstated too.") if held else ""


def _severity(gain: float | None) -> str:
    if gain is None:
        return "info"
    return "major" if gain >= 3 else "moderate" if gain >= 1 else "minor"


def suggestions(d: PrepData) -> list[Suggestion]:
    """What to change, most valuable first (WoWAnalyzer-style): each with its measured gain."""

    def lk(text: str) -> str:
        return linkify(text, d.links)

    def ic(name: str) -> str:
        return d.icons.get(name, "")

    out: list[Suggestion] = []
    if d.raid and d.raid.verdicts:
        v = d.raid.verdicts[0]
        what = "stay on the boss" if d.raid.objective == "boss" else "pad the adds"
        why = raidneed.readable(v.reason)
        out.append(Suggestion("info", f"With your raid, <b>{what}</b>", [e(why[:1].upper() + why[1:].rstrip(".") + ".")]))
    if d.talents and d.talents.rows:
        best = best_build(d)
        g = best.per_fight.get(d.talents.fights[0], (0.0, None))[0] if best else 0.0
        if best is not None and g > 2 * d.talents.error and not getattr(best, "swaps", None):  # the card above
            # says it, with its gain and copy button: not twice (fresh DPS review: two +6.55% on one tab)
            both = set(best.add) & set(best.drop)  # same name on two nodes (e.g. a choice node): not a change
            add = [t for t in dict.fromkeys(best.add) if t not in both]
            drop = [t for t in dict.fromkeys(best.drop) if t not in both]

            def few(names: list[str]) -> str:
                return e(", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else ""))

            lines = []
            if getattr(best, "swaps", None):  # the card above shows them as icons, with its copy button (DPS
                add = drop = []  # round 11: the same swap three times on one tab; no pointer sentence, round 19)
            if add:
                lines.append("<span class='plus'>+</span> Take " + few(add))
            if drop:
                lines.append("<span class='minus'>&minus;</span> <span class='muted'>Drop " + few(drop) + "</span>")
            if best.build.code and not getattr(best, "swaps", None):
                lines.append(copy_button(best.build.code, "Copy the talent string") +
                             " <span class='muted small'>then in game: Talents, Import loadout. "
                             "Every build compared below, in Talents of the top players.</span>")
            out.append(Suggestion(_severity(g), f"Switch to the talents of <b>{e(best.build.label)}</b> "
                                  f"<span class='muted'>(played by {best.build.count} top players)</span>", lines, g,
                                  d.icons.get("__spec__", ""),
                                  "total damage" if any(c for _t, c, _l, _n in d.waves) else "boss damage",
                                  "your talents"))  # its base, as the plans' (DPS confirm round 10)
    want = wanted(d)

    def costly(p) -> bool:
        """A burst plan that loses boss or total damage: worth it only when the raid needs that target dead."""
        return p.objective == "secondary" and any(v < -2 * p.error for o, v in p.totals.items() if o in ("boss", "total"))

    from paf.simple import card_plan

    shown = card_plan(d)  # the change card's plan, with its rules and MRT button: not said twice (fresh DPS review)
    for p in sorted(d.optimized, key=lambda p: (p.objective != want, costly(p), -p.gain)):
        if p.objective == "adds" or p.gain <= 2 * p.error or p is shown:
            continue
        by_rule: dict[str, list[str]] = {}
        for k, r in p.choice.items():
            if r.name != "default":
                by_rule.setdefault(rule_phrase(d, r.name), []).append(k)
        from paf.simple import _fallback

        lines = [", ".join(icons.img(d.icons.get(k, "") or _fallback(d, cd_name(d, k)), "small")
                           + link(cd_name(d, k), d.links.get(k))
                           for k in ks) + f": {e(phrase)}" for phrase, ks in by_rule.items()]
        others = ", ".join(f"{_goal(o)} damage {v:+.1f}%" for o, v in p.totals.items()
                           if o not in (p.objective, "adds"))
        played_p = simple_plan(d)
        shown_gain, base = p.gain, "SimC's default list"
        if played_p is not None and played_p is not p and played_p.gain > 2 * played_p.error:  # the real cost

            def vs(o: str, p=p, played_p=played_p) -> float:
                return 100 * ((1 + p.totals[o] / 100) / (1 + played_p.totals[o] / 100) - 1)
            rel = [f"{_goal(o)} damage {vs(o):+.1f}%" for o in ("boss", "total")
                   if o != p.objective and o in p.totals and o in played_p.totals]
            if rel:  # the trade a player makes: against the plan played, the default list's numbers in Dig deeper
                others = "vs the plan the sheet plays: " + ", ".join(rel)  # (DPS confirm rounds 6-8: one base,
                if p.objective in p.totals and p.objective in played_p.totals:  # its headline gain too)
                    shown_gain, base = vs(p.objective), "the plan the sheet plays"
        if others:
            lines.append(f"<span class='muted small'>Also: {e(others)}.</span>")
        if d.mrt.get(p.objective):
            lines.append(copy_button(d.mrt[p.objective], "Copy the MRT note")
                         + (" " + copy_button(d.nsrt[p.objective], "Copy for NSRT") if d.nsrt.get(p.objective) else "")
                         )  # the addons named in the buttons' own tooltips (review 36)
        stall = _stall(d, p)
        if stall:
            lines.append(f"<div class='why' title='{e(stall_why(d, p))}'>&#9888; {e(stall)}</div>")
        fell = want is not None and p.objective == want and _fallen(p)
        flags = [f for f in p.flags if not (fell and f.startswith("not robust"))]  # its pill says it (confirm 9)
        if flags:  # shown, not folded; a sign under the shown precision says nothing
            lines.append("<div class='why'>&#9888; " + "; ".join(
                e(re.sub(r"[-+]0\.0%", "about 0%", f)[:1].upper() + re.sub(r"[-+]0\.0%", "about 0%", f)[1:])
                for f in flags) + "</div>")
        first = next((k for k, r in p.choice.items() if r.name != "default"), next(iter(p.choice), ""))  # what it changes
        goal = {"boss": "if you focus the boss", "total": "if you pad the adds",
                "secondary": f"to burst {burst_names(d)[1] or 'the secondary targets'}"}.get(p.objective, p.objective)
        tag = ""
        if want is not None and p.objective == want and not p.robust and getattr(p, "default_timeline", None):
            worst = min(p.sensitivity.items(), key=lambda x: x[1], default=None)  # the fight tab plays the default
            tag = (" <span class='pill near'>not played: not robust"  # list; why, in the pill, with its number
                   + (f", {worst[1]:+.1f}% if {e(worst[0])}" if worst else "") + "</span>")  # (DPS rounds 15, 9)
        elif want is not None and p.objective == want:
            tag = (" <span class='pill gold'>your choice</span>" if d.goal in ("boss", "total")
                   else " <span class='pill gold'>recommended for your raid</span>")
            other = next((o for o in d.optimized if o.objective in ("boss", "total") and o.objective != want
                          and o.gain > p.gain and o.robust and not p.robust), None)
            if other is not None:  # why the sheet plays the smaller, fragile plan
                lines.append(f"<span class='small'>Played because {'your raid pads the adds' if want == 'total' else 'your raid stays on the boss'} "
                             f"(see Your raid). On a night you {'focus the boss' if want == 'total' else 'pad the adds'}, the "
                             f"other plan is the safer one.</span>")
        elif want is None and p.objective in ("boss", "total"):
            tag = " <span class='pill'>pick one: see Your raid</span>"
        elif costly(p):
            tag = " <span class='pill'>only if your raid needs it dead fast</span>"
        played = want is not None and p.objective == want and not _fallen(p)  # not played: grey, never green
        sev = "info" if costly(p) else "alt" if (want is not None and not played and p.objective in ("boss", "total")) \
            else _severity(p.gain)  # a plan the sheet does not play is an alternative, whatever its size
        from paf.simple import _fallback  # a potion or a racial: the picture the fight tab shows for it

        out.append(Suggestion(sev, f"Cooldown plan <b>{e(goal)}</b>{tag}", lines, shown_gain,
                              d.icons.get(first, "") or _fallback(d, cd_name(d, first)), {"boss": "boss damage", "total": "total damage",
                                                       "secondary": "burst damage"}.get(p.objective, ""), base))
    if d.gear:
        changes, _, w = d.gear[0]
        if w > 2 * d.gear_error:
            names = [n for n in d.links if n in changes and d.links[n].startswith("item=")]
            out.append(Suggestion(_severity(w), "Equip from your bags", [lk(c) for c in changes.split("; ")], w,
                                  ic(names[0]) if names else ""))
    if d.loot:
        item, slot, simple, real = d.loot[0]
        delta = real if real is not None else simple
        if delta > 2 * d.loot_error:
            out.append(Suggestion(_severity(delta), f"Loot to hope for: {lk(item)}",
                                  [f"{e(slot)}, at item level {d.loot_ilvl}"], delta, ic(item)))
    held = [a for a in d.alignment if a.units_cover and a.in_units > a.units_cover * 1.5
            and a.in_units - a.units_cover > 0.1]
    if held:
        vuln, units = burst_names(d)
        played = simple_plan(d)
        rules = {cd_name(d, k): rule_phrase(d, r.name) for k, r in (played.choice.items() if played else [])}
        said = [f"Your plan: {a.ability}: {rules[a.ability]} (SimC finds it worth more that way for your character)."
                for a in held if a.ability in rules and "only on" not in rules[a.ability].replace("only on add", "")
                and not rules[a.ability].startswith("as SimC's default")]
        tried = {cd_name(d, k) for p in d.optimized for k in p.choice}
        kept = {cd_name(d, k) for p in d.optimized for k, r in p.choice.items() if r.name != "default"}
        said += [f"{a.ability}: SimC tried holding it and finds no gain for your character; your plans leave it to "
                 "the default priority list." for a in held if a.ability in tried and a.ability not in kept]
        out.append(Suggestion("info", "The top players keep " + ", ".join(lk(a.ability) for a in held) + " for "
                              + e(" / ".join(x for x in (vuln, units) if x) or "the burst windows"), [e(s) for s in said],
                              None, ic(held[0].ability)))
    order = {"info": 0}
    # your raid's verdict first, then the gains, biggest first, the situational ones last
    def rank(s: Suggestion) -> tuple:
        if s.title.startswith("With your raid"):
            return (order.get(s.severity, 1), 0)
        mine = "recommended for your raid" in s.title or "your choice" in s.title  # the plan the sheet plays
        return (2 if s.severity == "info" and s.gain is not None else 1, 0 if mine else 1,
                -(s.gain if s.gain is not None else -1))
    return sorted(out, key=rank)


def checklist_html(d: PrepData) -> str:
    """One line per thing to do, in raid order: before the pull, then during the fight."""
    items = [f"<li><label><input type='checkbox'> <span>{what}</span></label>{extra}</li>"
             for what, extra in checklist_items(d)]
    if not items:
        return ""
    return f'<div class="card checklist"><ul>{"".join(items)}</ul></div>'


def checklist_items(d: PrepData) -> list[tuple[str, str]]:
    """(what to do, a button) of each line of the raid checklist, in raid order."""
    items: list[tuple[str, str]] = []

    def item(what: str, extra: str = "") -> None:
        items.append((what, extra))

    best = best_build(d)
    g = best.per_fight.get(d.talents.fights[0], (0.0, None))[0] if best else 0.0
    if best is not None and g > 2 * d.talents.error:
        item(f"Talents: import <b>{e(best.build.label)}</b> ({g:+.1f}%)",
             " " + copy_button(best.build.code, "Copy") if best.build.code else "")
    elif d.talents:
        item("Talents: keep yours, they match the top players' on this fight")
    if d.gear and d.gear[0][2] > 2 * d.gear_error:
        changes, _, w = d.gear[0]
        item(f"Gear ({w:+.2f}%): " + "; ".join(linkify(c, d.links) for c in changes.split("; ")))
    elif d.gear:
        item("Gear: keep what you wear")
    want = wanted(d) or "boss"
    plan = next((p for p in d.optimized if p.objective == want and p.gain > 2 * p.error), None)
    if d.goal in ("boss", "total"):
        item("Your role (your choice): <b>" + ("boss damage first" if d.goal == "boss" else "pad the adds") + "</b>")
    elif d.raid and d.raid.objective:
        item("Your role: <b>" + ("stay on the boss" if d.raid.objective == "boss" else "pad the adds") + "</b>")
    elif not any(c for _t, c, _l, _n in d.waves):  # no adds on this boss: nothing to decide
        item("Your role: <b>the boss</b> <span class='muted'>(no adds to pad on this boss)</span>")
    else:
        item("Your role: ask your raid lead whether you should pad the adds or focus the boss "
             "<span class='muted'>(or set your guild in the app: the prep decides from your raid)</span>")
    if plan is not None:
        by_rule: dict[str, list[str]] = {}
        for k, r in plan.choice.items():
            if r.name != "default":
                by_rule.setdefault(rule_phrase(d, r.name), []).append(cd_name(d, k))
        rules = "; ".join(f"{', '.join(ks)}: {phrase}" for phrase, ks in by_rule.items())
        item(f"Cooldowns ({_goal(plan.objective)} damage, {plan.gain:+.1f}%): {e(rules)}",
             " " + copy_button(d.mrt[plan.objective], "Copy the MRT note") if d.mrt.get(plan.objective) else "")
    elif any(p.objective == want for p in d.optimized):
        item(f"Cooldowns ({_goal(want)} damage): use them as soon as they are ready; holding them for a moment of "
             f"the fight gains nothing measurable here")
    if getattr(d, "lust_spots", None):
        item(f"{icons.img(d.icons.get('Bloodlust', '') or _sfallback(d, 'Bloodlust'), 'small')}{lust_line(d)}")
    elif d.lust is not None:
        item("Bloodlust goes out at the pull" if d.lust < 15 else f"Bloodlust usually comes around {_mmss(d.lust)}")
    mine = [a for a in d.actions if a.kind in ("kill", "contact", "interrupt", "mechanic")
            and not (a.kind == "interrupt" and not a.text.startswith("Interrupt"))]
    for n, t in gate_kills(d):  # the add that ends the immunity, first
        item(f"{icons.img(_sfallback(d, n), 'small')}{e(t)}")
    for a in mine[:6]:
        item(f"{icons.img(d.icons.get(a.name, '') or _sfallback(d, a.name), 'small')}{e(a.text)}")
    if not mine:
        for b in d.role_bullets[:4]:
            item(e(b))
    for a in d.assigns:
        item("Your assignment: " + e(a))
    return items


def export_html(d: PrepData) -> str:
    """The rebuilt fight as simc lines, to sim it on Raidbots or anywhere else."""
    buttons = " ".join(copy_button(text, "Copy the fight" if not label else f"Copy the fight + plan for {label}")
                       for label, text in d.export.items())
    lines = d.export.get("", next(iter(d.export.values()), ""))
    has = ["duration"] + [w for w, key in (("add waves", "/adds,"), ("immune windows", "/invulnerable,"),
                                           ("damage windows", "/vulnerable,"), ("movement", "/movement,"),
                                           ("Bloodlust", "bloodlust_time="), ("Power Infusion", "power_infusion="))
                          if key in lines]  # what the copied lines hold, none other
    return f'''<h2>Sim this fight on Raidbots</h2><div class="card"><p class="small">The fight above as SimulationCraft
lines: {e(", ".join(has))}. On
<a href="https://www.raidbots.com/simbot/advanced" target="_blank" rel="noopener">Raidbots, Advanced</a>: paste your
<code>/simc</code> export, then these lines under it, in the same box. Leave the fight style out (Patchwerk removes
the raid events).</p><p>{buttons}</p></div>'''


def fightview_support() -> float:
    from paf.fightview import DEF_SUPPORT

    return DEF_SUPPORT


def defensives_html(d: PrepData) -> str:
    """When the top players of your spec press their defensives, and what hits them then."""
    df = d.defensives
    if not df or not (df.moments or df.usage):
        return ""
    casts = dict(d.boss_casts)

    def cast_note(m) -> str:  # the ability's cast long before the defensive: a hit that lands later, said with its cast
        near = [c for c in casts.get(m.boss_ability, []) if m.time - 8 <= c <= m.time + 12]  # its hit, around
        before = [c for c in casts.get(m.boss_ability, []) if c < m.time]
        return "" if near or not before else f" <span class='muted small'>(its damage; cast at {_mmss(max(before))})</span>"
    def untied(m) -> str:  # no ability tied in the logs: the boss's cast just before, said as a lead, not a fact
        lead = max(((c, n) for n, ts in d.boss_casts for c in ts if m.time - 10 <= c <= m.time), default=None)
        return (f"<span class='muted small'>none tied in the logs ({e(lead[1])} starts at {_mmss(lead[0])})</span>"
                if lead else "<span class='muted small'>none tied in the logs</span>")
    rows = "".join(
        f"<tr><td class='n'>{_mmss(m.time)}</td><td>{m.share:.0%}</td><td>"
        + ", ".join(f"{icons.img(d.icons.get(n, ''), 'small')}{link(n, f'spell={sid}')} "
                    f"<span class='muted small'>{s:.0%}</span>" for n, sid, s in m.spells)
        + f"</td><td>{link(m.boss_ability, f'spell={m.boss_spell_id}') + cast_note(m) if m.boss_ability else untied(m)}"
        + "</td></tr>" for m in df.moments)
    method = (f"When the top players of your spec press one ({df.kills} kills); the fight tab calls the moments where "
              f"{fightview_support():.0%} or more of them press one")
    answers = "cast within about 10 s, or long before for damage that lands later"
    table = (f"<div class='scroll'><table><tr><th>When</th><th title='{e(method)}'>Top players</th><th>Defensive</th>"
             f"<th title='{answers}'>The boss ability it answers</th></tr>{rows}</table></div>") if df.moments else (
        "<p class='small'>The top players do not press their defensives at one shared moment on this boss: use them "
        "when you take damage.</p>")
    usage = "".join(f"<span class='chip{' rare' if per < 0.2 else ''}'>{icons.img(d.icons.get(n, ''), 'small')}"
                    f"{link(n, f'spell={sid}')} <b>{per:.1f}</b>/kill on average &middot; {share:.0%} of the kills</span>"
                    for n, sid, per, share in df.usage[:6])  # chips, the rare ones muted, never dropped (DPS c. 14)
    return (f"<h2>Defensives <span class='pill near'>advice, not simmed</span></h2><div class='card'>{table}"  # the
            + (f"<div class='small chips'><span class='muted'>Used{'' if df.moments else f', {df.kills} ranked kills'}:"
               f"</span><span>{usage}</span></div>" if usage
               else "")  # the label its own column, the chips wrapping beside it (DPS confirm round 14)
            + "</div>")  # the table's method on its header (DPS rounds 36-40: three lines under it)  # no table: no columns told, the source in the chips' label (DPS confirm round 15)


def _track_top(d) -> str:
    """", the top of the Hero track" when the loot is valued at its difficulty's cap, not at your gear's level."""
    from paf.droptimizer import LOOT_CAP

    track = {"heroic": "Hero", "mythic": "Myth"}.get((d.difficulty or "").lower())
    return f", the top of the {track} track" if track and d.loot_ilvl == LOOT_CAP.get(d.difficulty.lower()) else ""


def nsrt_block(note: str) -> str:
    if not note:
        return ""
    # the button alone: the raw reminders are for the addon, not to read (the owner, 2026-10-24)
    return f'<div class="nb"><h4>Northern Sky Raid Tools reminders {copy_button(note, "Copy for NSRT")}</h4></div>'


def _pad_bar(text: str) -> str:
    """The raid's share of the top raids' damage on the adds as a bar, a mark at the weakest top raids' (DPS rounds
    36-42: "53% vs 84%" in words). '' when the line says no such pair."""
    import html as _html

    m = re.search(r"(?:with you, your raid does|already does|,) (\d+)% (?:of the top raids' damage on them|with you)"
                  r".*?the weakest top raids do (\d+)%", _html.unescape(text))  # the line as shown: escaped (round 43)
    if not m:
        return ""
    you, low = int(m[1]), int(m[2])
    top = max(100, you, low)
    end = "" if low / top > 0.8 else " ends"  # "100%" only where it does not touch the mark's label (round 45)
    return (f"<div class='padbar{end}' title='your raid {you}%, the weakest top raids {low}% of the top raids&#39; "
            "damage'>"
            f"<i style='width:{you / top * 100:.0f}%'></i><b style='left:{low / top * 100:.0f}%'></b>"
            f"<span>your raid {you}%</span><span class='lo' style='left:{low / top * 100:.0f}%'>{low}%</span></div>")


def _without_shares(text: str) -> str:
    """The pad line without the two shares its bar draws (DPS round 44: said twice): "Pad them: it lacks cleave.".
    The line with you and without you keeps its words: the bar draws only the share with you."""
    if "without you, " in text and " with you (" in text:
        return text
    out = re.sub(r"(?:(?:with|without) you, )?your raid (?:already )?does \d+%.*?\(the weakest top raids do \d+%\)(?:; )?", "",
                 text)
    out = re.sub(r":\s*$", ".", re.sub(r":\s+(?=[.;]|$)", "", out)).replace(": .", ".")
    return re.sub(r"^Pad them: it lacks", "Your raid lacks", out)  # the title says "pad" (round 45: said twice)


# an add to kill as paf.actions says it: its name, how many a kill, how fast, the spec's share on it
KILL_TEXT = re.compile(r"Kill the (?P<name>.+?) \((?:~(?P<n>\d+) per kill|once per kill)\): the top raids kill them "
                       r"in ~(?P<life>\d+) s(?:; top .+? players put (?P<share>\d+)% of their damage on them while "
                       r"they are up)?\.")


def places(g: float, gains: list[float]) -> int:
    """Decimals for a gain: two when another gain rounds alike at one (never one figure copied: DPS rounds 13, 38)."""
    return 2 if any(f"{g:.1f}" == f"{x:.1f}" and abs(g - x) >= 0.005 for x in gains) else 1


def suggestions_html(d: PrepData) -> str:
    rows = []
    gains = [x.gain for x in suggestions(d) if x.gain is not None]
    best = best_build(d) if d.talents else None  # the card's talent gain, left out of the list: still counted, so
    if best is not None:  # the plan's figure reads as the card's (+6.65% beside +6.55%, never +6.7%)
        gains.append(best.per_fight.get(d.talents.fights[0], (0.0, None))[0] or 0.0)
    for s in suggestions(d):
        label = {"major": "Major", "moderate": "Moderate", "minor": "Minor", "info": "Info",
                 "alt": "Alternative"}[s.severity]
        if s.severity == "info" and s.gain is not None:  # a gain only for some raids (a burst they may not need)
            label = "Situational"
        unit = f"<small>{e(s.metric)}, vs {e(s.base)}</small>" if s.metric else ""  # the baseline, said
        gain = (f'<div class="gain{" muted" if s.severity == "alt" else ""}">{s.gain:+.{places(s.gain, gains)}f}%'
                f'{unit}</div>'  # not played:
                if s.gain is not None else '<div class="gain"></div>')  # grey (DPS confirm round 10)
        pic = icons.img(s.icon or "inv_misc_groupneedmore", "medium")
        details = "".join(f"<div>{_without_shares(x) if _pad_bar(x) else x}</div>{_pad_bar(x)}" for x in s.details)
        rec = " rec" if "recommended for your raid" in s.title or "your choice" in s.title else ""
        rows.append(f'<div class="sugg {s.severity}{rec}">{pic}<div><div class="t"><span class="sev">{label}</span> '
                    f'{s.title}</div><div class="d">{details}</div></div>{gain}</div>')
    if not rows:
        return (f'<p class="muted">Nothing to change: no talent, {"gear or " if d.gear else "spec or "}cooldown change '
                'beats yours here.</p>')
    return f'<div class="card suggs">{"".join(rows)}</div>'


# the sheet's sections (the old tabs are gathered into them by render)
SECTIONS = (("fight", "The fight"), ("change", "What to change"), ("boss", "The boss"), ("deeper", "Dig deeper"))
TABS = (("overview", "Overview"), ("boss", "The boss"), ("cooldowns", "Cooldowns"), ("gear", "Gear & talents"), ("raid", "Your raid"),
        ("fight", "The fight"))
TAB_JS = """<script>
(function(){var ids=[...document.querySelectorAll('.panel')].map(function(p){return p.id});
function show(id){var to=null,el=id&&document.getElementById(id);
if(ids.indexOf(id)<0&&el&&el.closest('.panel')){to=el;id=el.closest('.panel').id}if(ids.indexOf(id)<0)id=ids[0];document.body.classList.toggle('on-fight',id==='fight');
document.querySelectorAll('.panel').forEach(function(p){
p.hidden=p.id!==id});document.querySelectorAll('.tabs a').forEach(function(a){
var on=a.getAttribute('href')==='#'+id;a.classList.toggle('on',on);a.setAttribute('aria-selected',on)});
var cur=document.querySelector('.tabs a.on');if(cur)cur.scrollIntoView({inline:'center',block:'nearest'});
if(to)to.scrollIntoView();else scrollTo(0,0);
if(window.__fv&&id==='fight')window.__fv.layout()}
addEventListener('hashchange',function(){show(location.hash.slice(1))});show(location.hash.slice(1));
document.addEventListener('click',function(ev){var b=ev.target.closest('[data-copy]');if(!b)return;
var t=b.getAttribute('data-copy'),done=function(){var o=b.textContent;b.textContent='Copied';
setTimeout(function(){b.textContent=o},1500)};if(navigator.clipboard&&navigator.clipboard.writeText){
navigator.clipboard.writeText(t).then(done,function(){prompt('Copy:',t)})}else{prompt('Copy:',t)}});})();
</script>"""


WS_CSS = theme.style("workshop")


def _contents(body: str) -> str:
    """Dig deeper is long: its headings get anchors and a row of links on top to jump to one."""
    import re

    heads = []

    def anchor(m: re.Match) -> str:
        import html as _h

        text = _h.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if not text:
            return m.group(0)
        hid = f"dd-{len(heads)}"
        heads.append((hid, text))
        return f"<h2{m.group(1)} id='{hid}'>{m.group(2)}</h2>"

    body = re.sub(r"<h2([^>]*)>(.*?)</h2>", anchor, body, flags=re.S)
    if len(heads) < 3:
        return body
    links = "".join(f"<a href='#{hid}' data-jump>{e(t[:48])}</a>" for hid, t in heads)
    return (f"<nav class='dd-toc' aria-label='In this section'><p>Every number behind the sheet, for who digs. "
            f"Jump to:</p><div>{links}</div></nav>{body}")


def _tools_html() -> str:
    """The tools that dig further into this boss (the sheet is shown in a frame: they open in the app's window)."""
    from paf import workshop

    return ("<h2>Dig further, one question at a time</h2>"
            + workshop.cards(("topgear", "droptimizer", "talents", "specgear", "optimize", "timeline", "assigns",
                              "mechanics"), target="_top"))


def gate_kills(d: PrepData) -> list[tuple[str, str]]:
    """(unit, sentence) of each add whose death ends the boss's immunity: the target that gates the fight."""
    out = []
    for w in (d.fight.invulnerable if d.fight is not None else []):
        for t, c, _life, names in d.waves:
            if c and w.start - 2 <= t <= w.start + w.duration:
                name = re.sub(r"\s*\([^)]*\)", "", names).strip()
                out.append((names, f"Kill the {name}: the boss is immune from {_mmss(w.start)} until it dies (it comes at "
                                  f"{_mmss(t)}; the top raids take about {w.duration - (t - w.start):.0f} s)."))
                break
    return out


def mech_around(html: str, d: PrepData) -> str:
    """The journal card of a mechanic that hits players (not a boss cast) gets its times from the logs too."""
    casts = {n for n, _ts in d.boss_casts}
    for name, ts in (getattr(d, "mech_times", None) or {}).items():
        if name in casts or not ts:
            continue
        times = ", ".join(_mmss(t) for t in ts)
        html = re.sub(rf"(<b>(?:<a [^>]*>)?{re.escape(e(name))}(?:</a>)?</b>[^<]*(?:<span[^>]*>[^<]*</span>[^<]*)*</div>)(?!<div class='small muted'>around)",
                      lambda m, times=times: m.group(1) + f"<div class='small muted'>around {times}</div>", html)
    return html


def stage_times(html: str, phases: list[tuple[str, float]], duration: float) -> str:
    """The journal's 'around m:ss' timings, each stage keeping only the casts that fall in it."""
    ph = sorted(phases, key=lambda p: p[1])
    spans = {n: (s, ph[i + 1][1] if i + 1 < len(ph) else (duration or 1e9)) for i, (n, s) in enumerate(ph)}

    def secs(x: str) -> int:
        m, s = x.split(":")
        return int(m) * 60 + int(s)

    def one(sec: re.Match) -> str:
        span = spans.get(re.sub(r"<[^>]+>", "", sec.group(2)).strip())
        if span is None:
            return sec.group(0)

        def keep(m: re.Match) -> str:
            ts = [t for t in re.findall(r"\d+:\d\d", m.group(1)) if span[0] - 15 <= secs(t) < span[1]]
            early = any(secs(t) < span[0] - 1 for t in ts)  # cast just before its stage starts: said so
            return (f"around {', '.join(ts)}" + (" (just before the stage starts)" if early else "")) if ts else ""
        body = re.sub(r"around ((?:\d+:\d\d(?:, )?)+)(?:…)?", keep, sec.group(3))
        body = re.sub(r"<div class='small muted'>(?: &middot; )?</div>", "", body.replace(">&middot; ", ">"))
        return sec.group(1) + body + "</section>"

    return re.sub(r'(<section class="card stage"><h3>(.*?)</h3>)(.*?)</section>', one, html, flags=re.S)


def in_time_order(note: str) -> str:
    """An MRT note ({time:m:ss}) or NSRT reminders (time:s;ph:n) with the defensives merged in time order (the
    player reads it before pasting it); the lines without a time keep their place on top."""
    import re

    def when(line: str):
        m = re.match(r"\{time:(\d+):(\d+)", line)
        if m:
            return (0.0, int(m[1]) * 60 + int(m[2]))
        m = re.match(r"time:([\d.]+);ph:([\d.]+)", line)
        return (float(m[2]), float(m[1])) if m else None

    lines = note.splitlines()
    head = [x for x in lines if when(x) is None]
    timed = sorted((x for x in lines if when(x) is not None), key=when)
    return "\n".join(head + timed) + ("\n" if note.endswith("\n") else "")


def lust_line(d: PrepData) -> str:
    """Where the fight puts Bloodlust (the raid lead's pick, else the top raids' most used spot) and what the top
    raids' other spots would give you in the sim."""
    spots = d.lust_spots
    used = next((x for x in spots if x[0].label == d.lust_pick), None) or next(
        (x for x in spots if x[0].t == d.lust), spots[0])
    sp = used[0]
    if sp.t is None:
        head = "<b>No Bloodlust</b>"
    elif sp.kind == "pull":
        head = "<b>Bloodlust on pull</b>"
    elif sp.kind == "phase":
        head = f"<b>Bloodlust at {_mmss(sp.t)}</b>, {e(sp.phrase.removeprefix('at '))}"
    else:
        head = f"<b>Bloodlust at {_mmss(sp.t)}</b>" + (f", {e(sp.label[0].lower() + sp.label[1:])}"
                                                      if sp.kind == "last_minute" else "")
    why = "your raid lead's pick" if d.lust_pick else f"{sp.share:.0%} of the top raids lust there"
    boss = (wanted(d) or "boss") == "boss"
    noise = getattr(d, "lust_noise", 0.0) or 0.0
    gains = [(x, b if boss and b is not None else tot) for x, tot, b in spots  # going without: the raid lead's call
             if x is not sp and tot is not None and x.t is not None]
    what = "boss damage" if boss else "damage"
    better = [(x, g) for x, g in gains if g > max(noise, 0.05)]
    tail = ""
    if better:
        x, g = max(better, key=lambda xg: xg[1])
        tail = (f" Lust {e(x.phrase)} ({x.share:.0%} of them) would give you <b class='pos'>{g:+.1f}% {what}</b>"
                + (f" (&plusmn;{noise:.1f}%)" if noise else "")
                + (": tell your raid lead." if not d.lust_pick else "."))
    elif gains:
        tail = " The top raids' other spots give you no more."
    return f"{head} ({why}).{tail}"


def unsimmed_amps(d: PrepData) -> list[str]:
    """Journal abilities that raise the boss's damage taken while the rebuilt fight has no window for them."""
    text = " ".join(d.role_bullets) + " " + re.sub(r"<[^>]+>", " ", d.guide_summary or "")
    boss = re.escape(d.boss.split(",")[0])  # the boss's own damage taken, not a player's (a tank debuff)
    names = re.findall(rf"\b([A-Z][\w']*(?: [A-Z][\w']*)*) increases (?:{boss}'s|his|her|its) damage taken", text)
    known = " ".join(v.name for v in (d.fight.vulnerable if d.fight is not None else []))
    return [n for n in dict.fromkeys(names) if n not in known]


def onto_adds(d: PrepData) -> None:
    """A burst a plan presses while the boss is immune, just before its adds spawn, goes on the spawn (as the fight
    tab calls it): every plan's timeline, MRT note and NSRT reminders then say the same time."""
    if d.fight is None or not d.fight.invulnerable or not d.optimized:
        return
    from paf.optimize import mrt_note, nsrt_note

    spawns = sorted(t for t, *_ in d.waves)
    imm = [(w.start, w.start + w.duration) for w in d.fight.invulnerable]

    def snap(t: float) -> float:
        if any(a <= t < b for a, b in imm):
            return next((s for s in spawns if t < s <= t + 6), t)
        return t
    spell_ids = {n.lower(): int(r.split("=", 1)[1]) for n, r in d.links.items()
                 if r.startswith("spell=") and r.split("=", 1)[1].isdigit()}
    for p in d.optimized:
        moved = [(snap(t), label) for t, label in p.timeline]
        if moved == list(p.timeline):
            continue
        p.timeline = moved
        if p.objective in d.mrt:
            d.mrt[p.objective] = mrt_note(d.boss, p, d.fight, d.cd_names)
        old = d.nsrt.get(p.objective, "")
        enc = re.match(r"EncounterID:(\d+)", old)
        tag = re.search(r";tag:([^;]+);", old)
        if enc and tag:
            d.nsrt[p.objective] = nsrt_note(int(enc[1]), p, d.fight, getattr(d, "game_phases", None) or d.phases, tag[1], spell_ids, d.cd_names)


PLAYED = "played"  # the notes key of the default list the fight tab plays instead of a plan not robust enough


def sheet_pickle(d) -> bytes:
    """The sheet's data as a pickle: database rows become dicts, functions made on the fly (the plans' rules, the
    compared plans) are dropped; nothing on the sheet reads them."""
    import io
    import pickle
    import sqlite3
    import types

    class Sheet(pickle.Pickler):
        def reducer_override(self, obj):
            if isinstance(obj, sqlite3.Row):
                return dict, (dict(zip(obj.keys(), tuple(obj), strict=True)),)
            if isinstance(obj, types.FunctionType | types.MethodType) and "<" in getattr(obj, "__qualname__", "<"):
                return type(None), ()
            return NotImplemented

    buf = io.BytesIO()
    Sheet(buf).dump(d)
    return buf.getvalue()


def render(d: PrepData) -> str:
    import pickle

    # the sheet's words are set on a copy: the data saved after it (and rendered again) stays as simmed. Copied as
    # it is saved: a fresh prep holds database rows, which deepcopy cannot copy (every new prep failed to render)
    d = pickle.loads(sheet_pickle(d))
    onto_adds(d)
    from paf import simple as _simple

    played = _simple._plan(d)  # what you can aim for: your character playing the plan the sheet calls, not the default
    d.aim_plan = bool(played and played.gain > 2 * played.error and d.sim_dps)
    if d.aim_plan:
        d.sim_dps *= 1 + played.totals.get("total", 0.0) / 100
        if d.sim_boss_dps:
            d.sim_boss_dps *= 1 + played.totals.get("boss", 0.0) / 100
    pre = {n for n in d.precast} | {n for n in d.links if "potion" in n.lower()} | {"Potion"}

    def before_pull(note: str) -> str:  # a press cast before the pull says so, as the fight tab's note does
        return "\n".join(line + " - before the pull" if line.startswith("{time:0:00}") and any(
            re.search(rf"\b{re.escape(n)}\b", line) for n in pre) and " - " not in line else line
            for line in note.splitlines())
    d.mrt = {k: before_pull(in_time_order(v)) for k, v in d.mrt.items()}
    d.nsrt = {k: in_time_order(v) for k, v in d.nsrt.items()}
    from paf import fightview, simple

    played = simple._plan(d)
    if played is not None and simple.plays_default(d) and d.fight is not None:  # the fight tab plays the default
        # list: its NSRT reminders too; the plan's card keeps its own notes (DPS round 11: a default-list MRT note
        # beside the plan's NSRT times under the pad plan)
        from paf.optimize import nsrt_note

        old = d.nsrt.get(played.objective, "")
        enc, tag = re.match(r"EncounterID:(\d+)", old), re.search(r";tag:([^;]+);", old)
        if enc and tag:
            ids = {n.lower(): int(r.split("=", 1)[1]) for n, r in d.links.items()
                   if r.startswith("spell=") and r.split("=", 1)[1].isdigit()}
            d.nsrt[PLAYED] = in_time_order(nsrt_note(int(enc[1]), played, d.fight, getattr(d, "game_phases", None)
                                                     or d.phases, tag[1], ids, d.cd_names))

    if d.talents and d.talents.rows and d.talents.fights:  # builds lettered in the order the sheet lists them: best first
        f0 = d.talents.fights[0]
        for i, r in enumerate(sorted(d.talents.rows, key=lambda r: -(r.per_fight.get(f0, (0.0, None))[0] or 0.0))):
            r.build.label = f"top build {chr(65 + i)}"
    if d.mrt:  # every plan's note says the defensives the fight tab calls, not the logs' longer list
        defs = fightview.note_lines(d, ("def", "move"))

        def tidy(v: str) -> str:
            lines = in_time_order("\n".join([x for x in v.splitlines() if " Defensive: " not in x] + defs)).splitlines()
            return "\n".join(dict.fromkeys(lines[:1] + fightview.prepull(lines[1:])))  # once each, however often run
        d.mrt = {k: tidy(v) for k, v in d.mrt.items()}
    if "secondary" in d.mrt:  # a burst plan's card gives its gain on another base: the note's title gives none
        d.mrt["secondary"] = re.sub(r" \([+-]?\d+\.\d%\)", "", d.mrt["secondary"], count=1)  # (DPS confirm 9)
    if d.nsrt and d.defensives and d.defensives.moments:  # NSRT reminds the same defensives as the fight tab
        from paf.defensives import Defensives, nsrt_lines

        ids = {str(s[1]) for m in d.defensives.moments for s in m.spells}
        kept = Defensives(fightview.defensive_moments(d))

        def renote(v: str) -> str:
            lines = v.splitlines()
            enc = re.match(r"EncounterID:(\d+)", lines[0] if lines else "")
            tag = next((m[1] for x in lines if (m := re.search(r";tag:([^;]+);", x))), "")
            if not enc or not tag:
                return v
            lines = [x for x in lines if not re.search(rf";spellid:({'|'.join(ids)});", x)
                     and not x.startswith("-- prep-a-fight: defensives not placed")]
            return in_time_order("\n".join(lines + nsrt_lines(kept, int(enc[1]), getattr(d, "game_phases", None) or d.phases, tag)
                                            + move_lines(int(enc[1]), tag)))
        from paf.optimize import NSRT_UNSURE_AFTER, nsrt_phase

        def move_lines(enc: int, tag: str) -> list[str]:  # the presses for a move the fight tab calls (Shadowstep)
            out, dropped = [], []
            for t, it in fightview.items(d):
                if it.side != "you" or it.kind != "move":
                    continue
                ref = d.links.get(it.name, "")
                sid = ref[6:].split("&")[0] if ref.startswith("spell=") else ""
                ph, since = nsrt_phase(enc, getattr(d, "game_phases", None) or d.phases, t)
                limit = NSRT_UNSURE_AFTER.get((enc, ph))
                if ph == 0 or (limit is not None and since > limit):
                    dropped.append(f"{it.name} {_mmss(t)}")
                    continue
                what = f"spellid:{sid}" if sid.isdigit() else f"text:{it.name.replace(';', ',')}"
                out.append(f"time:{since:.1f};ph:{ph:g};tag:{tag};{what};dur:5")
            if dropped:
                out.append("-- prep-a-fight: moves not placed (NSRT changes phase at a moment the logs do not give; "
                           "see the MRT note): " + ", ".join(dropped))
            return out
        d.nsrt = {k: renote(v) for k, v in d.nsrt.items()}
    if played is not None and d.mrt.get(played.objective):  # the plan you play: one note, the fight tab's, everywhere
        d.mrt[PLAYED if simple.plays_default(d) else played.objective] = fightview.mrt(d)  # a plan not played keeps
        # its own on its card
    from dataclasses import replace as _replace

    d.actions = [_replace(a, text=re.sub(r"(take it in (\d+)% of the kills): expect it\.",
                                                 lambda m: m[1] + (": expect it." if int(m[2]) >= 60 else ": it can be you."),
                                             a.text)) for a in d.actions] if d.actions else d.actions
    tabs: dict[str, list[str]] = {k: [] for k, _ in TABS}

    def lk(text: str) -> str:
        return linkify(text, d.links)

    # overview: a raid briefing (paf.briefing); before it, the simple view (paf.simple)
    from paf import bossguide, briefing, simple

    notices: list[str] = []  # said on top of the fight
    if getattr(d, "partial", None):
        used, found = d.partial
        notices.append(
            f"<div class='partial'><b>First analysis, from {used} of the {found} top kills</b><span>Measured on our "
            "corpora: the fight is within about 2% of the full corpus and the talent pick rates within about 3 points. "
            "The full analysis runs in the background: this sheet refreshes by itself when it is done.</span></div>")
    tabs["overview"].append(briefing.lede_html(d) + briefing.aim_html(d) + briefing.confidence_pill(d))
    for name in unsimmed_amps(d):
        notices.append(
            f'<p class="notice small"><b>{e(name)} is not in the sims:</b> the Encounter Journal says it raises the '
            f"boss's damage taken, but not by how much, so the sims leave it out and no plan saves a cooldown for it. "
            f"If your raid holds burst for {e(name)}, hold yours too.</p>")
    if d.kills and d.kills < THIN_CORPUS:
        notices.append(
            f'<p class="notice small"><b>Thin data:</b> only {d.kills} ranked kills of your spec on this boss and '
            f'difficulty. The timings of the fight and the habits of the top players are less reliable than usual.</p>')
    tabs["overview"].append(briefing.moves_html(d))
    tabs["overview"].append(briefing.checklist_html(d))
    if d.guide_summary or d.guide_abilities:
        tabs["boss"].append("<h2>The boss in 60 seconds</h2>" + bossguide.modernize(d.guide_summary, d.difficulty).replace(
            '<a href="#boss">Every ability, phase by phase &rarr;</a>', ""))
        if d.actions:
            groups = {"kill": "Adds to kill", "contact": "Units handled by contact (soak)", "interrupt": "Interrupts", "assignment": "Assignments",
                      "mechanic": "Mechanics you will get", "ignore": "Units the top raids leave alive"}
            blocks = ""
            for kind, title in groups.items():
                rows = [a for a in d.actions if a.kind == kind]
                gates = gate_kills(d) if kind == "kill" else []  # the unit that ends an immunity comes first
                if kind == "kill":  # a wave's unit no action names, as Your job says it (Nek'zali's Echo of Jawae)
                    named = {a.name for a in d.actions} | {re.sub(r"\s*\([^)]*\)", "", n).strip() for n, _t in gates}
                    for _t0, c, _l, n in d.waves:
                        base = re.sub(r"\s*\([^)]*\)", "", n).strip()
                        if c and ":" not in n and base not in named:
                            named.add(base)
                            ts = [_mmss(x) for x, c2, _l2, n2 in d.waves if c2 and n2 == n]
                            gates.append((n, f"Kill the {base} (at {', '.join(ts)})."))
                parsed = [(a, m) for a in rows if kind == "kill" and (m := KILL_TEXT.fullmatch(a.text))]
                # a boss unit to kill (an Echo of Jawae): a row of the table too, its count and life from the waves
                # (fresh DPS review: a bullet under the table)
                unit_waves = [(n, w) for n, _say in gates for w in d.waves if w[1] and w[3] == n][:4] if parsed else []
                unit_rows = [f"<tr><td>{icons.img(_sfallback(d, n), 'small')}{e(re.sub(r' *[(].*', '', n))}</td>"
                             f"<td class='n'>&times;{w[1]}</td><td class='n' title='alive this long in the top kills, "
                             f"not a kill time: it goes with its phase'>{w[2]:.0f} s alive</td><td><span class='muted' "
                             f"title='not measured: the share is read on the adds, not on a boss unit'>&mdash;</span>"
                             f"</td></tr>" for n, w in unit_waves]
                if parsed:  # the adds as a table: how many, how fast the top raids kill them, your share on them
                    # (fresh DPS review: bullet sentences)
                    done = [x for x, _m in parsed]  # by identity: an Action is no set member (it crashed a prep)
                    rows = [a for a in rows if not any(a is x for x in done)]
                    blocks += (f"<h3>{e(title)}</h3><table class='kills fit'><thead><tr><th>Add</th>"
                               "<th class='n'>a kill</th><th class='n' title='how long they live in the top kills'>"
                               "&#9201; killed in</th><th title='the share of the top players&#39; damage on them while "
                               "they are up'>your spec on them</th></tr></thead><tbody>" + "".join(
                                   f"<tr><td>{icons.img(d.icons.get(a.name, '') or _sfallback(d, a.name), 'small')}"
                                   f"{e(m['name'])}</td><td class='n'>&times;{m['n'] or 1}</td><td class='n'>"
                                   f"{m['life']} s</td><td>" + (
                                       f"<span class='kbar'><span style='width:{m['share']}%'></span></span> "
                                       f"{m['share']}%" if m['share'] else "<span class='muted' title='not measured "
                                       "for your spec: too short-lived or too rare in its kills'>&mdash;</span>")
                                   + "</td></tr>" for a, m in parsed)
                               + "".join(unit_rows) + "</tbody></table>")
                    gates = [g for g in gates if g[0] not in {u for u, _w in unit_waves}]  # said in the table
                    title = ""  # the list below, if any, goes under the same heading
                if rows or gates:
                    blocks += ((f"<h3>{e(title)}</h3>" if title else "") + "<ul>" + "".join(
                        f"<li>{icons.img(_sfallback(d, n), 'small')}{e(t)}</li>" for n, t in gates) + "".join(
                        f"<li>{icons.img(d.icons.get(a.name, '') or _sfallback(d, a.name), 'small')}{e(a.text)}</li>" for a in rows) + "</ul>")
            tabs["boss"].insert(0, "<h2>What the top players do, from their logs</h2><div class='card guide'>"
                                f"{blocks}</div>")
        tabs["boss"].append(defensives_html(d))
        tabs["boss"].append("<h2>Every ability, from the Encounter Journal</h2><p class='small muted'>Timings and how "
                            "many players are hit come from the ranked kills.</p>"
                            + f"<div class='stages'>{stage_times(mech_around(bossguide.modernize(d.guide_abilities, d.difficulty), d), d.phases, d.duration)}"
                            "</div>")
    else:
        tabs["boss"].append(defensives_html(d))
    if d.timeline_file:
        tabs["overview"].append(f'<p class="small"><a href="{e(d.timeline_file)}">See when the top players use each '
                                f'cooldown (timelines) &rarr;</a></p>')

    # the fight
    rows = "".join(f"<tr><td>{_mmss(t)}</td><td>{e('Stage One' if i == 0 and n.lower() == d.boss.lower() else n)}"
                   f"</td></tr>" for i, (n, t) in enumerate(sorted(d.phases, key=lambda p: p[1])))
    scalable = {w.name for w in (d.fight.add_waves if d.fight is not None else []) if w.scalable}

    def simmed(c: int, name: str) -> str:  # the sim's own count: the logs' scaled by add_scale (d.waves: the logs')
        return str(max(1, round(c * (d.add_scale or 1)))) if c and name in scalable else (str(c) if c else "-")
    waves = "".join(f"<tr><td>{_mmss(t)}</td><td class='n'>{c or '-'}</td><td class='n'>{simmed(c, names)}</td>"
                    f"<td class='n'>{alive(d.fight, t, life):.0f}s</td><td>{e(names)}</td></tr>" for t, c, life, names in d.waves)
    extra = []
    if d.lust is not None:
        extra.append(f"Bloodlust at {_mmss(d.lust)}")
    if d.pi:
        extra.append("Power Infusion at " + ", ".join(_mmss(t) for t in d.pi))
    rv = getattr(d, "review", None)  # one figure on the sheet: the one "Your last pull" sets yours against
    moving = rv.tops_moving if rv is not None and rv.tops_moving is not None else d.moving_share
    extra.append(f"top {e(d.spec)} players move {moving:.0%} of the fight")
    if d.add_share_spec:
        off = 1 - d.boss_share_real if d.boss_share_real is not None else d.add_share_spec  # one figure, as the lede
        extra.append(f"and do {off:.0%} of their damage off the boss")
    focus = ""
    if d.fight is not None and d.fight.focus:
        n = d.fight.targets
        focus = ("<h3 class='small muted' style='margin-top:14px'>"
                 + (f"A council: who the top players mostly hit ({n} bosses are stacked, the sims count {n} targets "
                    f"the whole fight)" if n > 1 else "A council: who the top players hit (the bosses are never "
                    "stacked, the sims count one target at a time)")
                 + "</h3><div class='scroll'><table><tr><th>Time</th>"
                 "<th>Boss</th><th>Kills</th></tr>"
                 + "".join(f"<tr><td>{_mmss(f.start)}-{_mmss(f.start + f.duration)}</td><td>{e(f.name)}</td>"
                           f"<td class='n'>{f.support:.0%}</td></tr>" for f in d.fight.focus) + "</table></div>")
    adds_block = (f"""<h3 class="small muted" style="margin-top:14px">Add waves (typical timeline across kills)</h3>
<p class="small muted">{simmed_note(d)}</p>
<div class="scroll"><table class="fit"><tr><th>Time</th><th class="n">In the logs</th><th class="n">Simmed</th><th class="n">Alive</th><th>Types</th></tr>{waves}</table></div>
""" if waves else "")
    tabs["fight"].append(f"""<h2>The fight</h2><div class="card"><p>Typical duration {_mmss(d.duration)}; {"; ".join(extra)}.</p>
<div class="scroll"><table class="fit">{rows}</table></div>
{adds_block}{focus}{f'<p><a href="{e(d.timeline_file)}">Cooldown timelines of the top players</a></p>' if d.timeline_file else ''}
</div>""")
    if d.export:
        tabs["fight"].append(export_html(d))
    if d.assigns:
        tabs["fight"].append('<h2>Your assignments and plan</h2><div class="card small"><ul>'
                             + "".join(f"<li>{e(a)}</li>" for a in d.assigns) + "</ul></div>")

    # your raid
    if d.raid_tools:
        from paf import workshop_views

        tools = getattr(d, "raid_tools", {}) or {}
        titles = {"comp": "Who hits what in your raid", "wipe": "Your best pull, in detail",
                  "night": "This boss in your raid's night"}
        for kind in ("comp", "wipe", "night"):
            if tools.get(kind):
                head = f"<h2>{e(titles[kind])}</h2>"  # every block under a section heading
                tabs["raid"].append(f"{head}<div class='ws-answer'>"
                                    f"{workshop_views.render({'kind': kind, **tools[kind]})}</div>")
        tabs["raid"].append(workshop_views.CSS)
    adds = any(c for _t, c, _l, _n in d.waves)
    if d.raid and (d.raid.verdicts or adds):
        tabs["raid"].append(raid_section(d.raid, bool(d.gear or d.loot)))
    elif d.raid or not adds:  # no adds on this boss: nothing to decide, no section
        pass
    else:
        tabs["raid"].append("""<h2>Your raid and the adds</h2><div class="card"><p>Not set for this prep. Set your guild
on the home page of the app (its latest public log is used), or paste one of your raid's logs on the boss page: the prep
then tells you whether the others cover the adds (stay on the boss) or you should pad them, and picks the cooldown plan
and the gear for that.</p></div>""")

    # sim of the fight
    if d.sim_dps and d.patchwerk_dps:
        boss = ""
        if d.sim_boss_dps:
            boss = (f", {d.sim_boss_dps:,.0f} of it on the boss ({d.sim_boss_dps / d.sim_dps:.0%}: your character's own "
                    f"share in this sim, with its talents and "
                    f"{'the plan the sheet plays' if getattr(d, 'aim_plan', False) else 'SimC' + chr(39) + 's default list'})")
        cal = ""
        if d.boss_share_real is not None and d.waves:
            cal = (f" The top players put {d.boss_share_real:.0%} of their damage on the boss in their logs: the rebuilt "
                   f"fight is tuned toward that by counting each add wave at {d.add_scale:g} of its size (SimC hits every "
                   f"add in range, real players do not)." if (d.add_scale or 1) < 1 else
                   f" The top players put {d.boss_share_real:.0%} of their damage on the boss in their logs; the rebuilt "
                   f"fight keeps every add wave at its full size (the add counts come from the logs).")
        tabs["fight"].append(f"""<h2>Your character on this fight</h2><div class="card">
<p>{d.sim_dps:,.0f} DPS on the rebuilt fight{boss}, vs {d.patchwerk_dps:,.0f} on a Patchwerk of the same length
({(d.sim_dps / d.patchwerk_dps - 1):+.0%}).{cal}</p></div>""")

    # talents
    if d.talents:
        from paf.raidlead import OTHER_BUILD
        from paf.talents import utility
        tc = d.talents
        adds = any(c for _t, c, _l, _n in d.waves)  # with adds the metric matters; without, it is boss damage
        names = {"boss fight": "This fight (total damage)" if adds else "This fight (boss damage)",
                 "patchwerk": "Single target (reference)"}
        head = "".join(f"<th class='n'>{e(names.get(f, f))} &plusmn;{2 * tc.error:.1f}%</th>" for f in tc.fights)
        body = f"<tr><td>your talents</td>{''.join('<td class=n>ref</td>' for _ in tc.fights)}<td></td></tr>"
        first = tc.fights[0]
        for r in sorted(tc.rows, key=lambda r: -(r.per_fight.get(first, (0.0, None))[0] or 0.0)):
            cells = ""
            for f in tc.fights:
                tot, boss = r.per_fight.get(f, (None, None))
                cells += f"<td class='n'>{_pct(tot, 1, err=2 * tc.error)}{'<br><span class=small>on the boss ' + _pct(boss, 1, err=2 * tc.error) + '</span>' if boss is not None else ''}</td>"
            both = set(r.add) & set(r.drop)
            add = [t for t in dict.fromkeys(r.add) if t not in both]
            drop = [t for t in dict.fromkeys(r.drop) if t not in both]
            free = utility(add + drop, d.class_name, d.spec) if add or drop else set()  # buttons the rotation never
            choice = [f"+ {e(t)}" for t in add if t in free] + [f"&minus; {e(t)}" for t in drop if t in free]  # presses:
            # apart, grey, the player's, each with its sign (the owner, 2026-10-24; round 37)
            add, drop = [t for t in add if t not in free], [t for t in drop if t not in free]
            diff = "<span class='muted'>only ranks or a choice node differ from yours</span>"
            if len(add) + len(drop) > OTHER_BUILD:  # another build altogether: one badge, not 40 names (the owner,
                # 2026-10-24; as on the raid lead page)
                diff = f"<span class='other-build'>other build &middot; {len(add) + len(drop)} talents apart</span>"
            elif add or drop:
                diff = (f"<span class='plus'>+</span> {e(', '.join(add) or '-')}<br>"
                        f"<span class='minus'>&minus;</span> <span class='muted'>{e(', '.join(drop) or '-')}</span>")
            if choice and len(add) + len(drop) <= OTHER_BUILD:
                diff = ("" if diff.endswith("from yours</span>") and not (add or drop) else diff + "<br>") + (
                    "<span class='muted'>your choice: " + ", ".join(choice) + "</span>")  # each name escaped above
            body += (f"<tr><td>{e(r.build.label)}<br><span class='small muted'>{r.build.count} players, median rank "
                     f"{r.build.median_rank:.0f}</span></td>{cells}<td class='small'>{diff}</td></tr>")
        best_g = max((((r.per_fight.get(first, (0.0, None))[0] or 0.0), r.build.label) for r in tc.rows),
                     default=(0.0, ""))
        verdict = (f"<p><b>Keep your talents:</b> no build of the top players beats yours by more than "
                   f"{2 * tc.error:.1f}% on this fight.</p>"
                   if best_g[0] <= 2 * tc.error else
                   f"<p><b>{e(best_g[1])} beats yours by {best_g[0]:+.1f}%</b> on this fight.</p>")
        tabs["gear"].append(f"""<h2>Talents of the top players, on your character</h2><div class="card scroll">
{verdict}<table><tr><th title="Each top build simmed on your character; a gap under &plusmn;{2 * tc.error:.1f}% (SimC's error) is
noise, and a build can lose on the dummy and win on this fight">Build</th>{head}
<th>Changes vs your talents</th></tr>{body}</table></div>""")  # the method on the header (DPS rounds 36-40)

    # cooldown plans
    if d.plans:
        pc = d.plans
        times = "; ".join(f"{e(a)} at {', '.join(_mmss(t) for t in ts)}" for a, ts in pc.cd_times.items() if ts)
        body = "".join(f"<tr><td>{e(p.name.replace('_', ' '))}</td><td class='n'>{_pct(tot)}</td>"
                       f"<td class='n'>{_pct(boss)}</td><td class='small'>{e(p.description)}</td></tr>"
                       for p, tot, boss in pc.rows)
        tabs["cooldowns"].append(f"""<h2>Cooldown plans</h2><div class="card scroll">
<p class="small">When the top players use their cooldowns: {times}.</p>
<table><tr><th>Plan</th><th>Total</th><th>Boss</th><th></th></tr>{body}</table>
<p class="small muted">Statistical error about &plusmn;{pc.error:.2f}%. SimC evaluates these plans; it does not invent new ones.</p>
</div>""")

    # ideal play-by-play per objective
    flat = bool(d.optimized) and all(abs(p.gain) <= 2 * p.error for p in d.optimized)
    if flat:  # no plan beats the default priority list on any goal: one block, not three of the same
        p = d.optimized[0]
        note = re.sub(r"cooldowns for .*\(\+?-?0\.0%\)", "cooldowns: SimC's default priority list",
                      d.mrt.get(p.objective, ""), count=1)
        tabs["cooldowns"].append(
            "<h2>Cooldown plan</h2><div class='card'><p><b>The default priority list is already right "
            "on this fight:</b> play it as it is. No other plan beats it for boss, total "
            "or burst damage (every gap within the sims' noise)."
            + (f" The sims leave out {e(', '.join(unsimmed_amps(d)))}: see the fight tab." if unsimmed_amps(d) else "")
            + "</p>"
            f"{plan_timeline_svg(p, d.fight, d.tops_casts, d.tops_players, names=d.cd_names, phases=d.phases, links=d.links)}"
            + (f"<h4>MRT note {copy_button(note, 'Copy the MRT note')}</h4><pre class='small note-pre'>{e(note)}</pre>"
               if note else "") + "</div>")
    if d.optimized and not flat:
        blocks = []
        first = wanted(d) or simple._plan(d).objective if simple._plan(d) else None
        twins = {"adds"} if any(o.objective == "secondary" and {k for k, r in o.choice.items() if r.name != "default"}
                                 for o in d.optimized) else set()  # burst on the adds says what 'adds' would
        for p in sorted(d.optimized, key=lambda p: p.objective != first):  # the sheet's plan first
            if p.objective in twins:
                continue
            changed = {k: r for k, r in p.choice.items() if r.name != "default"}
            from paf.simple import _fallback
            rules = "".join(f"<tr><td>{icons.img(d.icons.get(k, '') or _fallback(d, cd_name(d, k)), 'small')} "
                            f"{link(cd_name(d, k), d.links.get(k))}</td>"
                            f"<td>{e(rule_phrase(d, r.name))}</td></tr>"
                            for k, r in changed.items()) or "<tr><td>Every cooldown</td><td>as SimC's default priority list casts it</td></tr>"
            others = ", ".join(f"{_goal(o)} {_pct(v, 1)}" for o, v in p.totals.items() if o != p.objective)
            note = d.mrt.get(p.objective, "")
            checks = ""
            if p.sensitivity:
                checks += ("<p class='small'>Sensitivity (pessimistic variants of the fight): "
                           + ", ".join(f"{e(v)} {_pct(g, 1)}" for v, g in p.sensitivity.items())
                           + (" &rarr; <b>robust</b>" if p.robust else " &rarr; <b>not robust</b>") + "</p>")
            elif p.gain > 2 * p.error:  # said, never left out in silence
                checks += "<p class='small'>Not checked on pessimistic variants of the fight.</p>"
            if _stall(d, p):
                checks += f"<p class='small warn' title='{e(stall_why(d, p))}'>&#9888; {e(_stall(d, p))}</p>"
            if off := off_tops(d, p):
                checks += ("<p class='small warn'>&#9888; Not when the top players press it: " + e(" ".join(off))
                           + "</p>")
            flags = [f for f in p.flags if not (p.sensitivity and f.startswith("not robust"))]  # the sensitivity
            if flags:  # line above says it, with its numbers (DPS round 15: "not robust" three lines in a row)
                checks += "<ul class='small'>" + "".join(f"<li class='warn'>&#9888; {e(re.sub(r'[-+]0[.]0%', 'about 0%', f))}</li>"
                                                         for f in flags) + "</ul>"
            blocks.append(f"""<div class="card"><h3 style="margin:0 0 6px">{e(objective_name(d, p.objective))}: {_pct(p.gain, 1, err=1e9 if p.objective == "secondary" or _stall(d, p) else 0.0)}
<span class="small muted">vs the default priority list{'; ' + others if others else ''}</span>{(" <span class='pill near'>not played: not robust</span>" if _fallen(p) else " <span class='pill gold'>the sheet plays this plan</span>") if p.objective == first else ""}</h3>
{("<p class='small'>Played because " + ("your raid pads the adds" if p.objective == "total" else "your raid stays on the boss" if p.objective == "boss" else "it is your choice") + " (see Your raid and the adds, below)." + (" When the plan presses a burst while the boss is immune, the fight tab moves it onto the adds that spawn then." if d.fight is not None and d.fight.invulnerable else "") + "</p>") if p.objective == first and p.objective in ("boss", "total") and not _fallen(p) else ""}
{"<p class='small muted'>Burst damage counts only the damage on " + e(burst_names(d)[1] or "the burst targets") + ": worth it only if your raid needs " + e(burst_names(d)[1] or "them") + " dead fast" + ("." if _stall(d, p) else ", at the cost of the boss and total damage above.") + "</p>" if p.objective == "secondary" else ""}
{checks}{plan_timeline_svg(p, d.fight, d.tops_casts, d.tops_players, names=d.cd_names, phases=d.phases, links=d.links, legend=not blocks)}
<table><tr><th>Cooldown</th><th>Rule</th></tr>{rules}</table>
{"<p class='small muted'>The cooldowns not listed follow SimC's default priority list: their times can move with the ones the plan holds.</p>" if changed else ""}
<div class="pp-grid">{(f'<div><div class="nb"><h4>MRT note {copy_button(note, "Copy the MRT note")}</h4><pre class="small note-pre">{e(note)}</pre></div>'
  + nsrt_block(d.nsrt.get(p.objective, "")) + "</div>") if (changed or p.objective == first) and note else
 "<div><p class='small muted'>The default priority list as it is: no note to paste. The fight tab's note has its "
 "presses and your defensives.</p></div>"}</div>
</div>""")
        tabs["cooldowns"].append("<h2>Cooldown plans, per objective</h2>" + "".join(blocks))

    if d.alignment and (d.alignment[0].adds_cover or d.alignment[0].units_cover):  # no adds: nothing to hold for
        a0 = d.alignment[0]
        units = bool(a0.units_cover)  # no burst target here: no column of zeros (DPS round 15)
        rows = ""
        tested = {cd_name(d, k) for p in d.optimized for k in p.choice}  # the cooldowns the plans hold or release
        for a in d.alignment:
            if (tested and a.ability not in tested) or not (a.in_adds or a.in_units):
                continue  # an AoE spender is on adds by nature, not held; a row of zeros says nothing
            held = []
            if a.in_adds > a.adds_cover * 1.5 and a.in_adds - a.adds_cover > 0.1:
                held.append("held for adds")
            elif a.in_adds > a.adds_cover * 1.25 and a.in_adds - a.adds_cover > 0.1:
                held.append("leans to the adds")
            if a.units_cover and a.in_units > a.units_cover * 1.5 and a.in_units - a.units_cover > 0.1:
                held.append("held for burst targets")
            elif a.units_cover and a.in_units > a.units_cover * 1.25 and a.in_units - a.units_cover > 0.1:
                held.append("leans to burst targets")
            rows += (f"<tr><td>{icons.img(d.icons.get(a.ability, ''), 'small')} {lk(a.ability)}</td>"
                     f"<td class='n'>{a.in_adds:.0%}</td>" + (f"<td class='n'>{a.in_units:.0%}</td>" if units else "") + ""
                     f"<td>{e(' / '.join(held) or 'no clear hold')}</td></tr>")
        burst = f" ({e(burst_names(d)[1])})" if burst_names(d)[1] else ""
        burst_said = f", and on the burst targets{burst}, which cover {a0.units_cover:.0%}" if units else ""
        burst_note = (" SimC does not know that a burst target must die fast, so compare with the simulated plans "
                      "above." if units else "")
        burst_th = '<th class="n">On burst targets</th>' if units else ""
        tabs["cooldowns"].append(f"""<h2>What the top players do with their cooldowns</h2><div class="card scroll">
<p class="small">Share of their casts (after the opener) during add waves, which cover {a0.adds_cover:.0%} of the fight in the top kills{burst_said}. Much more
than the coverage means they hold the cooldown.{burst_note}</p>
<table><tr><th>Cooldown</th><th class="n">During adds</th>{burst_th}<th>Reading</th></tr>{rows}</table></div>""")

    # gear
    if d.gear:
        many = len(d.gear_fights) > 1
        head = "".join(f"<th>{e(f)}</th>" for f in d.gear_fights) if many else ""
        top = d.gear[0][2]
        body = ""
        seen_sets: set = set()
        uniq = []
        for g in d.gear:  # one row a set of items: two slot orders of the same items are one (a review: twin rows)
            k = frozenset(x.split(": ", 1)[-1] for part in g[0].split("; ") for x in part.split(" + "))
            if k not in seen_sets:
                seen_sets.add(k)
                uniq.append(g)
        for i, (ch, per, w) in enumerate(uniq[:8]):
            noise = (i and top > 2 * d.gear_error and top - w <= 2 * d.gear_error  # never "about the best" on a
                     and w >= 0)  # loss, nor under a best that is itself "keep yours" (a review: two verdicts)
            items = "".join(f"<div>{lk(c)}</div>" for c in ch.split("; "))
            body += (f"<tr class='{'noise' if noise else ''}'><td class='small gearset'>{items}"
                     + f"</td><td class='n'>{_pct(w, err=d.gear_error)}" + (" <span class='pill near'>&asymp; best</span>" if noise else
                                                          " <span class='pill near'>best</span>"
                                                          if not i and w > 2 * d.gear_error else
                                                          " <span class='pill near'>&asymp; keep yours</span>"
                                                          if not i else "")  # the verdict's own rule (a review)
                     + "</td>"
                     + ("".join(f"<td class='n'>{_pct(per.get(f))}</td>" for f in d.gear_fights) if many else "")
                     + "</tr>")
        mine = ("on the fight with your assignments and plan: " + "; ".join(d.assigns)) if d.assigns else \
            "on the fight without personal assignments (tick yours in the app to see if they change your gear)"
        tabs["gear"].insert(0, f"""<h2>Best gear from your bags, for this fight</h2><div class="card scroll">
{"<p class='small warn'>&#9888; Every set here loses more than 5%: a sim gone wrong, not a reading. Keep the gear you wear.</p>" if top < -5 else ""}
<table><tr><th title="Simmed {e(d.gear_plan or 'with the default priority list')}, {e(mine)}">Swaps vs your equipped gear
</th><th class="n">Gain &plusmn;{d.gear_error:.2f}%</th>{head}</tr>{body}</table>
{"<p class='tiny muted'>" + "; ".join(t for k, t in (("&asymp; best<", "&asymp; best: within the error of the best set"), ("keep yours<", "&asymp; keep yours: no set beats yours by twice the error")) if k in body) + ".</p>" if "near" in body else ""}</div>""")

    # loot
    if d.loot:
        body = "".join(f"<tr><td>{icons.img(d.icons.get(i, ''), 'small')} {lk(i)}</td><td>{e(s.replace('_', ' '))}</td>"
                       f"<td class='n'>{_pct(real, err=d.loot_error) if real is not None else '-'}</td>"
                       f"<td class='n'>{_pct(v, err=d.loot_error)}</td></tr>" for i, s, v, real in d.loot[:12])
        tabs["gear"].append(f"""<h2>What this boss drops, for you</h2><div class="card scroll">
{'<p class="notice small">Nothing this boss drops is an upgrade for you at item level ' + str(d.loot_ilvl) + ': every value below is a loss vs what you already have.</p>' if all((real if real is not None else v) <= 0 for _, _, v, real in d.loot) else ''}
<table><tr><th>Item</th><th>Slot</th><th class="n" title="vs your best set without it: the item inserted in your best
Top Gear sets, the rest rearranged around it (its real value; below a single swap when your best set already beats what you
wear)">In your best sets</th><th class="n" title="vs the gear you wear: the classic droptimizer value, one swap on your
equipped set">Single swap</th></tr>{body}</table>
<p class="small muted">At item level {d.loot_ilvl}{_track_top(d)}; statistical error about &plusmn;{d.loot_error:.2f}%.</p></div>""")

    notes = [re.sub(r"^SimC puts (\d+%) of your damage on the boss vs (\d+%) in the top players' logs, even with more "
                    r"adds:", r"Even with the add waves counted at the minimum, SimC's default priority list puts \1 "
                    r"of your damage on the boss vs \2 in the top players' logs:", n).replace("secondary targets",
                                                                                            "burst targets")
             for n in d.notes]  # notes saved by older preps, in the current words
    notes = [n.replace("trajectories is scaled by 0:", "trajectories is ignored (scaled by 0):").replace(
        "SimC's default priority list puts", "SimC's default priority list, in the top players' gear, puts").replace(
        "of your damage on the boss vs", "of its damage on the boss vs").replace(
        "in the top players' logs:", "in their logs:") for n in notes]  # the calibration's player, not yours

    def direction(n: str) -> str:  # a calibration note saved by an older prep, in the direction the numbers go
        m = re.match(r"Even with the add waves counted at the minimum, SimC's default priority list puts (\d+)% of "
                     r"your damage on the boss vs (\d+)%", n)
        if not m:
            return n
        from paf.cli import calibration_note

        return calibration_note(int(m[1]) / 100, int(m[2]) / 100)
    notes = [direction(n) for n in notes]
    if (d.add_scale or 1) >= 1:  # the adds at full size: "at the minimum" said otherwise
        notes = [n.replace("Even with the add waves counted at the minimum, ", "With every add wave at its full size, ")
                 for n in notes]
    if d.validation:
        lo, med, hi = d.validation
        notes.insert(0, f"Validation: the top players' own characters simmed on this rebuilt fight give {med:.0%} of "
                        "their real DPS with the movement as calibrated"
                        + ("." if f"{lo:.0%}" == f"{hi:.0%}" else  # one value: no range (round 38: "94% to 94%")
                           f" ({lo:.0%} to {hi:.0%} across the movement levels tried)."))
    notes += [
        "A rebuilt fight is an approximation: good to choose between builds, items and plans, not a prediction "
        "of your exact DPS.",
        "Corpus analyses are correlations (what the top players do); SimC checks them on your character.",
    ]
    tabs["fight"].append('<h2>Notes</h2><div class="card small muted"><ul>' + "".join(f"<li>{e(n)}</li>" for n in notes)
                         + "</ul></div>")

    # the four sections: the fight to play, what to change, the boss, and everything else for who digs
    from paf import fightview

    card, sugg = simple.change_card(d), suggestions_html(d)
    sections: dict[str, list[str]] = {
        "fight": notices + [fightview.html(d)],
        "change": [f"<div class='simple change-top'><div class='cards'>{card}</div></div>",
                   briefing.spec_html(d), "" if "Nothing to change" in card and "Nothing to change" in sugg else
                   ("<h2>Worth knowing</h2>" if "Nothing to change" in card else "<h2>Everything worth changing</h2>")
                   + sugg]
        + tabs["gear"],
        "boss": tabs["boss"],
        "deeper": tabs["overview"] + [f"<div class='simple'>{simple.review_card(d)}</div>"] + tabs["cooldowns"] + tabs["raid"] + tabs["fight"]
        + [_tools_html()],
    }
    sections["deeper"] = [_contents("".join(sections["deeper"]))]
    b = sections["boss"]  # the boss tab opens on what the top players do beside the boss in 60 seconds
    if len(b) >= 2 and b[0].startswith("<h2>What the top players do") and b[1].startswith("<h2>The boss in 60"):
        rest = b[2:]
        defs = next((x for x in rest if x.startswith("<h2>Defensives</h2>")), "")  # the left column's second card
        rest = [x for x in rest if x is not defs]
        sections["boss"] = [f"<div class='boss-top'><div>{b[0]}{defs}</div><div>{b[1]}</div></div>"] + rest
    byline = f"{e(d.character)} &middot; {e(d.spec)} &middot; {d.kills} ranked kills"
    return sheet_page(d.boss, d.difficulty, byline, d.class_name, sections, spec=d.spec)


def sheet_page(boss: str, difficulty: str, byline: str, class_name: str, sections: dict[str, list[str]],
               extra_css: str = "", labels: dict[str, str] | None = None, spec: str = "") -> str:
    """A prep sheet's page: the hero with the section tabs (SECTIONS), one panel per section with content. Every
    role's sheet (damage, healer, tank) has this skeleton. byline: html."""
    from paf import briefing, fightview, simple

    cls_icon = ((icons.spec_any(f"{spec} {class_name}", "large", "hero-ic") if spec else  # the spec named beside it
                 icons.img(icons.CLASS_ICON.format(cls=class_name.lower()), "large", "hero-ic"))  # (DPS round 49)
                if class_name else "")
    header = f"""<header class="sheet-hero"><div class="in">{cls_icon}<div class="txt">
<h1>{e(boss)} {diff_pill(difficulty)}</h1>
<p>{byline} <span class="nw">&middot; {datetime.now():%d %b %Y %H:%M}</span></p>
</div><nav class="tabs" aria-label="Sections"><div class="tabs-in" role="tablist">{''.join(
        f'<a role="tab" href="#{k}">{e((labels or {}).get(k, label))}</a>' for k, label in SECTIONS if sections.get(k))}</div></nav></div></header>"""
    panels = "".join(f'<section class="panel" id="{k}">{"".join(v)}</section>' for k, v in sections.items() if v)
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(boss)} prep</title><script>document.documentElement.classList.add('js')</script>"
            f"{WH_SCRIPT}{theme.HEAD}{briefing.FONTS}<style>{CSS}{briefing.CSS}{simple.CSS}{fightview.CSS}{WS_CSS}{extra_css}</style>{theme.class_accent(class_name)}</head><body>{header}<main>{panels}"
            f'<p class="small muted gen">Generated by prep-a-fight.</p></main>{TAB_JS}{briefing.JS}'
            f"</body></html>")


def _sfallback(d: PrepData, name: str) -> str:
    """A unit's or mechanic's picture as the fight tab finds it (an add has no spell icon of its own)."""
    from paf.simple import _fallback

    return _fallback(d, name)
