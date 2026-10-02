"""The one-page boss prep sheet (HTML), assembled from the other modules' results."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

from paf import icons, theme
from paf.wowhead import SCRIPT as WH_SCRIPT
from paf.wowhead import link, linkify

e = html.escape


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def _pct(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "-"
    cls = "pos" if v > 0.0001 else "neg" if v < -0.0001 else ""
    return f'<span class="{cls}">{v:+.{digits}f}%</span>'


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


@dataclass
class PrepData:
    boss: str
    difficulty: str
    spec: str
    character: str
    kills: int = 0
    duration: float = 0.0
    phases: list[tuple[str, float]] = field(default_factory=list)
    waves: list[tuple[float, int, float, str]] = field(default_factory=list)
    lust: float | None = None
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
    alignment: list = field(default_factory=list)  # paf.optimize.Alignment
    fight: object | None = None  # paf.fight.Fight used by the sims
    assigns: list[str] = field(default_factory=list)  # notes of the player's assignments
    validation: tuple[float, float, float] | None = None  # simulated / real DPS of the top players (min, median, max)
    tops_casts: dict[str, list[float]] = field(default_factory=dict)  # cooldown key -> top players' cast times
    tops_players: int = 0
    links: dict[str, str] = field(default_factory=dict)  # spell / item name -> Wowhead reference
    cd_names: dict[str, str] = field(default_factory=dict)  # cooldown key (ascendance, trinket1) -> in-game name
    raid: RaidInfo | None = None
    icons: dict[str, str] = field(default_factory=dict)  # spell / item / cooldown key name -> game icon file
    class_name: str = ""  # e.g. "shaman" (class icon in the header)


PALETTE = ["#c89933", "#8e6a9b", "#4f8a8b", "#d0705a", "#b8ad3c", "#b0577f", "#3f6fa0", "#6c9a5b", "#74526c"]


def _key(label: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")


def plan_timeline_svg(plan, fight, tops: dict[str, list[float]], tops_players: int, px: float = 1.4,
                      names: dict[str, str] | None = None) -> str:
    """Lorrgs-like strip for a plan: the fight (phases, add waves, vulnerability windows, lust) then one row per
    cooldown with the plan's casts (dots) over the top players' casts of the same cooldown (bars)."""
    if fight is None or not plan.timeline:
        return ""
    dur = fight.duration
    W = int(dur * px) + 170
    x0 = 160

    def x(t: float) -> float:
        return round(x0 + t * px, 1)

    rows: list[str] = []
    y = 18
    # time axis
    axis = "".join(f'<line x1="{x(s)}" y1="14" x2="{x(s)}" y2="100%" stroke="var(--line)"/>'
                   f'<text x="{x(s) + 2}" y="11" font-size="10" fill="var(--muted)">{_mmss(s)}</text>'
                   for s in range(0, int(dur) + 1, 60))
    # fight strip
    fight_row = [f'<text x="4" y="{y + 12}" font-size="11" fill="var(--fg)">Fight</text>']
    for w in fight.add_waves:
        fight_row.append(f'<rect x="{x(w.time)}" y="{y}" width="{max(2, w.lifetime * px):.1f}" height="16" '
                         f'fill="#6c9a5b" opacity="0.4"><title>{_mmss(w.time)} adds x{w.count}</title></rect>')
    for v in fight.vulnerable:
        fight_row.append(f'<rect x="{x(v.start)}" y="{y}" width="{max(2, v.duration * px):.1f}" height="16" '
                         f'fill="#c89933" opacity="0.5"><title>{e(v.name)} x{v.multiplier:g}</title></rect>'
                         f'<text x="{x(v.start) + 2}" y="{y + 12}" font-size="10" fill="var(--fg)">x{v.multiplier:g}</text>')
    for w in fight.invulnerable:
        fight_row.append(f'<rect x="{x(w.start)}" y="{y}" width="{w.duration * px:.1f}" height="16" fill="#868e96" '
                         f'opacity="0.4"><title>boss away</title></rect>')
    if fight.lust_time is not None:
        fight_row.append(f'<rect x="{x(fight.lust_time)}" y="{y - 2}" width="{40 * px:.1f}" height="3" fill="#b0577f">'
                         f'<title>Bloodlust {_mmss(fight.lust_time)}</title></rect>')
    rows.append("".join(fight_row))
    y += 26
    # one row per cooldown
    labels: list[str] = []
    for _, label in plan.timeline:
        if label not in labels:
            labels.append(label)
    for i, label in enumerate(labels):
        color = PALETTE[i % len(PALETTE)]
        shown = (names or {}).get(_key(label)) or label.title()
        row = [f'<text x="4" y="{y + 12}" font-size="11" fill="var(--fg)">{e(shown[:24])}</text>']
        tt = tops.get(_key(label)) or []
        if tt and tops_players:
            bins: dict[int, int] = {}
            for t in tt:
                bins[int(t // 5)] = bins.get(int(t // 5), 0) + 1
            peak = max(bins.values())
            for b, n in bins.items():
                h = 16 * n / peak
                row.append(f'<rect x="{x(b * 5)}" y="{y + 16 - h:.1f}" width="{5 * px - 0.5:.1f}" height="{h:.1f}" '
                           f'fill="{color}" opacity="0.25"><title>top players: {n} casts at {_mmss(b * 5)}</title></rect>')
        for t, lab in plan.timeline:
            if lab == label:
                row.append(f'<circle cx="{x(t)}" cy="{y + 8}" r="5" fill="{color}" stroke="var(--card)" stroke-width="1.5">'
                           f'<title>{e(label)} {_mmss(t)}</title></circle>')
        rows.append("".join(row))
        y += 22
    return (f'<div class="scroll"><svg width="{W}" height="{y + 4}" style="font-family:system-ui">{axis}'
            f'{"".join(rows)}</svg></div><p class="small muted">Dots: this plan (one simulated pull). Pale bars: '
            f'when the top players cast the same cooldown. Green: add waves; gold: boss vulnerability windows '
            f'(x = damage taken); grey: boss away; pink line: Bloodlust.</p>')


def _base(name: str) -> str:
    return name.split(" (after")[0].split(" (boss aura)")[0].strip()


def cd_name(d: PrepData, key: str) -> str:
    """A cooldown key of the plans as the player knows it (the trinket's name, not 'trinket1')."""
    k = key.replace("use_item:", "")
    return d.cd_names.get(key) or d.cd_names.get(k) or k.replace("_", " ").title()


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
    m = re.fullmatch(r"hold_(adds|vulnerable)_(\d+)", rule)
    if m:
        what = "the next add wave" if m.group(1) == "adds" else (vuln or "the damage amp")
        return f"keep for {what} if it comes within {m.group(2)} s"
    return {"default": "as SimC's default priority list", "on_cooldown": "on cooldown",
            "add_waves": "only on add waves", "secondary_targets": f"only on {units or 'the secondary targets'}",
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
            take = ", ".join(best.add[:4]) or "-"
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
        trust = ("holds up on pessimistic variants of the fight" if p.robust and not p.flags
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


CSS = theme.CSS + """
:root{--card:var(--surface)}
.key ul{margin:0;padding-left:18px} .key li{margin:8px 0}
.kpis{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin:18px 0 6px}
.kpi.good .v{color:var(--pos)} .kpi.warn .v{color:var(--warn)}
.warn{color:var(--warn)}
/* header and tabs */
.sheet-hero{background:var(--header);color:#fff;position:sticky;top:0;z-index:5}
.sheet-hero .in{max-width:1040px;margin:0 auto;padding:16px 16px 10px;display:flex;gap:14px;align-items:center}
.sheet-hero h1{color:#fff;margin:0 0 2px} .sheet-hero p{margin:0;color:#eadfe9;font-size:13px}
.hero-ic{width:48px;height:48px;border-radius:10px;border:2px solid var(--sand);flex:none}
.tabs{background:rgba(0,0,0,.18);border-bottom:3px solid transparent;border-image:var(--stripe) 1}
.tabs .in{max-width:1040px;margin:0 auto;padding:0 10px;display:flex;gap:2px;overflow-x:auto}
.tabs a{color:#eadfe9;padding:10px 14px;font-weight:600;font-size:14px;white-space:nowrap;border-bottom:3px solid transparent;
  margin-bottom:-3px}
.tabs a:hover{color:#fff;text-decoration:none} .tabs a.on{color:var(--sand);border-bottom-color:var(--sand)}
/* suggestions */
.suggs{padding:4px 18px}
.sugg{display:grid;grid-template-columns:40px 1fr auto;gap:14px;align-items:start;padding:14px 0;
  border-bottom:1px solid var(--line)}
.sugg:last-child{border-bottom:0}
.sugg .ic,.sugg .phm{width:36px;height:36px;border-radius:7px;display:block;border:1px solid var(--line)}
.sugg .phm{background:var(--surface-2)}
.sugg .t{font-size:15px;line-height:1.35} .sugg .d{font-size:13.5px;color:var(--fg);margin-top:4px}
.sugg .d div{margin:3px 0}
.ics{display:inline-block;width:18px;height:18px;border-radius:4px;vertical-align:-4px;margin-right:2px}
.ics.ph{background:transparent}
.panel{scroll-margin-top:120px}
.sugg .gain{font-size:20px;font-weight:700;color:var(--pos);font-variant-numeric:tabular-nums;white-space:nowrap}
.sev{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;padding:2px 7px;
  border-radius:5px;margin-right:6px;vertical-align:2px}
.major .sev{background:var(--bronze);color:#1c1410} .moderate .sev{background:var(--accent-soft);color:var(--fg);
  border:1px solid var(--accent)} .minor .sev{background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.info .sev{background:var(--lavender);color:#fff}
.major{box-shadow:inset 3px 0 0 var(--bronze);padding-left:12px;margin-left:-15px}
@media (max-width:640px){.sugg{grid-template-columns:36px 1fr}.sugg .gain{grid-column:2;font-size:16px}}
"""


def kpi_tiles(d: PrepData) -> str:
    """The prep at a glance: model check, your raid's verdict, cooldowns, gear, talents."""
    tiles = []

    def tile(label: str, value: str, sub: str, cls: str = "") -> None:
        tiles.append(f'<div class="tile kpi {cls}"><div class="l">{e(label)}</div><div class="v">{value}</div>'
                     f'<div class="s">{e(sub)}</div></div>')

    if d.validation:
        lo, med, hi = d.validation
        tile("Fight model", f"{med:.0%}", f"of the top players' real DPS when simmed (range {lo:.0%}-{hi:.0%})",
             "good" if 0.9 <= med <= 1.1 else "warn")
    if d.raid and d.raid.objective:
        tile("Your raid", "Boss" if d.raid.objective == "boss" else "Pad",
             "the others cover the adds" if d.raid.objective == "boss" else "the adds need your damage")
    want = ("boss" if d.raid.objective == "boss" else "total") if d.raid and d.raid.objective else None
    plans = [p for p in d.optimized if p.objective in ("boss", "total")]
    best = next((p for p in plans if p.objective == want), None) or (max(plans, key=lambda p: p.gain) if plans else None)
    if best is not None:
        tile("Cooldown plan", f"{best.gain:+.1f}%", f"{objective_name(d, best.objective).lower()} vs SimC's default",
             "good" if best.gain > 2 * best.error else "")
    if d.gear:
        w = d.gear[0][2]
        tile("Gear", f"{w:+.2f}%" if w > 2 * d.gear_error else "Best",
             "with a few swaps from your bags" if w > 2 * d.gear_error else "your equipped set is already the best",
             "good" if w > 2 * d.gear_error else "")
    if d.talents and d.talents.rows:
        fight = d.talents.fights[0]
        r = max(d.talents.rows, key=lambda r: r.per_fight.get(fight, (-1e9, None))[0])
        g = r.per_fight.get(fight, (0.0, None))[0]
        tile("Talents", f"{g:+.1f}%" if g > 2 * d.talents.error else "OK",
             f"with {r.build.label}" if g > 2 * d.talents.error else "your build matches the top players'",
             "good" if g > 2 * d.talents.error else "")
    return f'<div class="kpis">{"".join(tiles)}</div>' if tiles else ""


def raid_section(r: RaidInfo) -> str:
    you = (f"you ({e(r.you[0])}, {r.you[1] / 1000:,.0f}k DPS)" if r.you_found else
           f"a {e(r.you[0])} at your raid's median DPS ({r.you[1] / 1000:,.0f}k; you are not in that log)")
    head = (f"<p class='small'>From your raid's log <a href='https://www.warcraftlogs.com/reports/{e(r.report)}' "
            f"target='_blank' rel='noopener'>{e(r.report)}</a> ({e(r.fight)}, {r.players} players), with {you}.</p>")
    if not r.verdicts:
        return (f"<h2>Your raid and the adds</h2><div class='card'>{head}<p>No add takes a real share of the damage "
                f"on this boss: nothing to decide, play for the boss.</p></div>")
    rows = "".join(
        f"<tr><td>{e(v.add.name)}</td><td class='n'>{v.without_you:.0%}</td><td class='n'>{v.with_you:.0%}</td>"
        f"<td class='n'>{v.low:.0%}</td><td><b>{'boss' if v.verdict == 'boss' else 'pad'}</b>: "
        f"{e(v.reason)}</td></tr>" for v in r.verdicts)
    groups = "".join(f"<li><b>{e(k)}</b> ({len(ps)}): {e(', '.join(ps))}</li>" for k, ps in r.archetypes.items() if ps)
    verdict = ("Stay on the boss: the cooldown plan and the gear below are the ones for boss damage." if r.objective
               == "boss" else "Pad the adds: the cooldown plan and the gear below are the ones for total damage.")
    mine = f" On this boss your spec is <b>{e(r.your_archetype)}</b>." if r.your_archetype else ""
    p = r.your_profile
    build = ""
    if p is not None:
        build = (f"<p class='small'>Your spec's top 100 on this boss: {p.dps / 1000:,.0f}k total DPS vs "
                 f"{p.boss_dps / 1000:,.0f}k for the top 100 by boss DPS ({p.boss_share:.0%}); {p.same_players} players "
                 f"are in both. ")
        build += (f"The pad build takes {e(', '.join(p.pad_talents) or '-')}; the boss build takes "
                  f"{e(', '.join(p.boss_talents) or '-')}.</p>" if p.pad_talents or p.boss_talents else
                  "Same talents in both: no separate pad build.</p>")
    est = (f"<p class='small muted'>Estimated from their total-DPS vs boss-DPS rankings (too rare in the "
           f"corpus): {e(', '.join(r.estimated))}.</p>" if r.estimated else "")
    return f"""<h2>Your raid and the adds</h2><div class="card">{head}
<p><b>{verdict}</b>{mine}</p>
<div class="scroll"><table><tr><th>Adds</th><th>Your raid without you</th><th>With you</th>
<th>Top raids' weakest quarter</th><th>Verdict</th></tr>{rows}</table></div>
<p class="small muted">Damage your raid puts on these adds, as a share of the top raids' (their median = 100%).</p>
<p class="small">Your raid on this boss, by what each spec does with the adds:</p><ul class="small">{groups}</ul>{est}{build}
<details><summary class="small">How it is computed</summary><p class="small muted">Measured: on this boss, each spec puts
a share of its damage on these adds while they are up (from the ranked kills): well above the median of all players =
AoE / funnel, well below = single target. Computed: your raid's damage on the adds = every player's DPS in your log x
their spec's share; the same for every top raid gives the reference range. Rule (not a measurement): if your raid
without you is within the top raids' range (above their weakest quarter), the others cover the adds and you stay on
the boss; otherwise you pad. Not promised: how long the adds will live. In the top kills it depends on the mechanics
and the strategy, not on the raid's DPS (checked: no correlation). Top players pad whatever their raid (they are
ranked on their own DPS), so their logs alone cannot tell what your raid needs.</p></details></div>"""


@dataclass
class Suggestion:
    severity: str  # "major" (>= 3%), "moderate" (>= 1%), "minor", "info"
    title: str  # html
    details: list[str] = field(default_factory=list)  # html lines
    gain: float | None = None
    icon: str = ""  # game icon file name


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
        out.append(Suggestion("info", f"With your raid, <b>{what}</b>", [e(v.reason)]))
    if d.talents and d.talents.rows:
        fight = d.talents.fights[0]
        best = max(d.talents.rows, key=lambda r: r.per_fight.get(fight, (-1e9, None))[0])
        g = best.per_fight.get(fight, (0.0, None))[0]
        if g > 2 * d.talents.error:
            both = set(best.add) & set(best.drop)  # same name on two nodes (e.g. a choice node): not a change
            add = [t for t in dict.fromkeys(best.add) if t not in both]
            drop = [t for t in dict.fromkeys(best.drop) if t not in both]

            def few(names: list[str]) -> str:
                return e(", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else ""))

            lines = []
            if add:
                lines.append("Take " + few(add))
            if drop:
                lines.append("<span class='muted'>Drop " + few(drop) + "</span>")
            lines.append("<span class='muted small'>Full comparison in Gear &amp; talents.</span>")
            out.append(Suggestion(_severity(g), f"Play the talent build <b>{e(best.build.label)}</b> "
                                  f"<span class='muted'>({best.build.count} top players)</span>", lines, g,
                                  d.icons.get("__spec__", "")))
    want = ("boss" if d.raid.objective == "boss" else "total") if d.raid and d.raid.objective else None
    for p in sorted(d.optimized, key=lambda p: (p.objective != want, -p.gain)):
        if p.objective == "adds" or p.gain <= 2 * p.error:
            continue
        by_rule: dict[str, list[str]] = {}
        for k, r in p.choice.items():
            if r.name != "default":
                by_rule.setdefault(rule_phrase(d, r.name), []).append(k)
        lines = [", ".join(icons.img(d.icons.get(k, ""), "small") + link(cd_name(d, k), d.links.get(k))
                           for k in ks) + f": {e(phrase)}" for phrase, ks in by_rule.items()]
        if p.flags:
            lines.append("<span class='warn'>&#9888; " + e("; ".join(p.flags)) + "</span>")
        first = next(iter(p.choice), "")
        others = ", ".join(f"{o if o != 'total' else 'pad'} {v:+.1f}%" for o, v in p.totals.items()
                           if o not in (p.objective, "adds"))
        out.append(Suggestion(_severity(p.gain), f"Cooldowns for <b>{e(objective_name(d, p.objective).lower())}</b>"
                              + (f" <span class='muted'>({others})</span>" if others else ""), lines, p.gain,
                              d.icons.get(first, "")))
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
        out.append(Suggestion("info", "The top players keep " + ", ".join(lk(a.ability) for a in held) + " for "
                              + e(" / ".join(x for x in (vuln, units) if x) or "the burst windows"), [],
                              None, ic(held[0].ability)))
    order = {"info": 0}
    return sorted(out, key=lambda s: (order.get(s.severity, 1) if s.title.startswith("With your raid") else 1,
                                      -(s.gain if s.gain is not None else -1)))


def suggestions_html(d: PrepData) -> str:
    rows = []
    for s in suggestions(d):
        label = {"major": "Major", "moderate": "Moderate", "minor": "Minor", "info": "Info"}[s.severity]
        gain = f'<div class="gain">{s.gain:+.1f}%</div>' if s.gain is not None else '<div class="gain"></div>'
        pic = icons.img(s.icon, "medium") or '<span class="phm"></span>'
        details = "".join(f"<div>{x}</div>" for x in s.details)
        rows.append(f'<div class="sugg {s.severity}">{pic}<div><div class="t"><span class="sev">{label}</span> '
                    f'{s.title}</div><div class="d">{details}</div></div>{gain}</div>')
    if not rows:
        return '<p class="muted">Nothing to change: your character already plays this fight well.</p>'
    return f'<div class="card suggs">{"".join(rows)}</div>'


TABS = (("overview", "Overview"), ("cooldowns", "Cooldowns"), ("gear", "Gear & talents"), ("raid", "Your raid"),
        ("fight", "The fight"))
TAB_JS = """<script>
(function(){var ids=[...document.querySelectorAll('.panel')].map(function(p){return p.id});
function show(id){if(ids.indexOf(id)<0)id=ids[0];document.querySelectorAll('.panel').forEach(function(p){
p.hidden=p.id!==id});document.querySelectorAll('.tabs a').forEach(function(a){
a.classList.toggle('on',a.getAttribute('href')==='#'+id)});scrollTo(0,0)}
addEventListener('hashchange',function(){show(location.hash.slice(1))});show(location.hash.slice(1));})();
</script>"""


def render(d: PrepData) -> str:
    tabs: dict[str, list[str]] = {k: [] for k, _ in TABS}

    def lk(text: str) -> str:
        return linkify(text, d.links)

    # overview
    tabs["overview"].append(kpi_tiles(d))
    tabs["overview"].append("<h2>Suggestions</h2>" + suggestions_html(d))
    if d.timeline_file:
        tabs["overview"].append(f'<p class="small"><a href="{e(d.timeline_file)}">See when the top players use each '
                                f'cooldown (timelines) &rarr;</a></p>')

    # the fight
    rows = "".join(f"<tr><td>{_mmss(t)}</td><td>{e(n)}</td></tr>" for n, t in d.phases)
    waves = "".join(f"<tr><td>{_mmss(t)}</td><td class='n'>{c or '-'}</td><td class='n'>{life:.0f}s</td>"
                    f"<td>{e(names)}</td></tr>" for t, c, life, names in d.waves)
    extra = []
    if d.lust is not None:
        extra.append(f"Bloodlust at {_mmss(d.lust)}")
    if d.pi:
        extra.append("Power Infusion at " + ", ".join(_mmss(t) for t in d.pi))
    extra.append(f"top {e(d.spec)} players move {d.moving_share:.0%} of the fight")
    if d.add_share_spec is not None:
        extra.append(f"and do {d.add_share_spec:.0%} of their damage to adds")
    tabs["fight"].append(f"""<h2>The fight</h2><div class="card"><p>Typical duration {_mmss(d.duration)}; {"; ".join(extra)}.</p>
<div class="scroll"><table><tr><th>Phase</th><th></th></tr>{rows}</table></div>
<h3 class="small muted" style="margin-top:14px">Add waves (typical timeline across kills)</h3>
<div class="scroll"><table><tr><th>Time</th><th>Adds</th><th>Alive</th><th>Types</th></tr>{waves}</table></div>
{f'<p><a href="{e(d.timeline_file)}">Cooldown timelines of the top players</a></p>' if d.timeline_file else ''}
</div>""")
    if d.assigns:
        tabs["fight"].append('<h2>Your assignments and plan</h2><div class="card small"><ul>'
                             + "".join(f"<li>{e(a)}</li>" for a in d.assigns) + "</ul></div>")

    # your raid
    if d.raid:
        tabs["raid"].append(raid_section(d.raid))
    else:
        tabs["raid"].append("""<h2>Your raid and the adds</h2><div class="card"><p>Not set for this prep. Set your guild
on the home page of the app (its latest public log is used), or paste one of your raid's logs on the boss page: the prep
then tells you whether the others cover the adds (stay on the boss) or you should pad them, and picks the cooldown plan
and the gear for that.</p></div>""")

    # sim of the fight
    if d.sim_dps and d.patchwerk_dps:
        boss = ""
        if d.sim_boss_dps:
            boss = f", {d.sim_boss_dps:,.0f} of it on the boss ({d.sim_boss_dps / d.sim_dps:.0%})"
        cal = ""
        if d.boss_share_real is not None:
            cal = (f" The fight is calibrated so that your share of damage on the boss matches the top players' "
                   f"logs ({d.boss_share_real:.0%}); add counts scaled by {d.add_scale:g}.")
        tabs["fight"].append(f"""<h2>Your character on this fight</h2><div class="card">
<p>{d.sim_dps:,.0f} DPS on the rebuilt fight{boss}, vs {d.patchwerk_dps:,.0f} on a Patchwerk of the same length
({(d.sim_dps / d.patchwerk_dps - 1):+.0%}).{cal}</p></div>""")

    # talents
    if d.talents:
        tc = d.talents
        head = "".join(f"<th>{e(f)}</th>" for f in tc.fights)
        body = f"<tr><td>your build</td>{''.join('<td class=n>ref</td>' for _ in tc.fights)}<td></td></tr>"
        for r in tc.rows:
            cells = ""
            for f in tc.fights:
                tot, boss = r.per_fight.get(f, (None, None))
                cells += f"<td class='n'>{_pct(tot)}{'<br><span class=small>boss ' + _pct(boss, 1) + '</span>' if boss is not None else ''}</td>"
            diff = ""
            if r.add or r.drop:
                diff = f"take {e(', '.join(r.add) or '-')}<br><span class='muted'>drop {e(', '.join(r.drop) or '-')}</span>"
            body += (f"<tr><td>{e(r.build.label)}<br><span class='small muted'>{r.build.count} players, median rank "
                     f"{r.build.median_rank:.0f}</span></td>{cells}<td class='small'>{diff}</td></tr>")
        tabs["gear"].append(f"""<h2>Talents of the top players, on your character</h2><div class="card scroll">
<table><tr><th>Build</th>{head}<th>vs your build</th></tr>{body}</table>
<p class="small muted">Statistical error about +/-{tc.error:.2f}%.</p></div>""")

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
<p class="small muted">Statistical error about +/-{pc.error:.2f}%. SimC evaluates these plans; it does not invent new ones.</p>
</div>""")

    # ideal play-by-play per objective
    if d.optimized:
        blocks = []
        for p in d.optimized:
            changed = {k: r for k, r in p.choice.items() if r.name != "default"}
            rules = "".join(f"<tr><td>{icons.img(d.icons.get(k, ''), 'small')} {link(cd_name(d, k), d.links.get(k))}</td>"
                            f"<td>{e(rule_phrase(d, r.name))}</td></tr>"
                            for k, r in changed.items()) or "<tr><td colspan=2>the default priority list</td></tr>"
            others = ", ".join(f"{o} {_pct(v, 1)}" for o, v in p.totals.items() if o != p.objective)
            steps = ""
            if p.timeline and d.fight is not None:
                from paf.optimize import fight_context

                steps = "".join(f"<tr><td>{_mmss(t)}</td><td>{e(label)}</td><td class='small muted'>"
                                f"{e(fight_context(d.fight, t))}</td></tr>" for t, label in p.timeline)
            note = d.mrt.get(p.objective, "")
            checks = ""
            if p.sensitivity:
                checks += ("<p class='small'>Sensitivity (pessimistic variants of the fight): "
                           + ", ".join(f"{e(v)} {_pct(g, 1)}" for v, g in p.sensitivity.items())
                           + (" &rarr; <b>robust</b>" if p.robust else " &rarr; <b>not robust</b>") + "</p>")
            if p.flags:
                checks += "<ul class='small'>" + "".join(f"<li class='warn'>&#9888; {e(f)}</li>" for f in p.flags) + "</ul>"
            blocks.append(f"""<div class="card"><h3 style="margin:0 0 6px">{e(objective_name(d, p.objective))}: {_pct(p.gain)}
<span class="small muted">vs the default priority list{'; ' + others if others else ''}</span></h3>
{checks}{plan_timeline_svg(p, d.fight, d.tops_casts, d.tops_players, names=d.cd_names)}
<table><tr><th>Cooldown</th><th>Rule</th></tr>{rules}</table>
<details><summary class="small">Play-by-play of one simulated pull</summary><div class="scroll"><table>
<tr><th>Time</th><th>Cooldown</th><th>Context</th></tr>{steps}</table></div></details>
<details><summary class="small">MRT note</summary><pre class="small" style="white-space:pre-wrap">{e(note)}</pre></details>
</div>""")
        tabs["cooldowns"].append("<h2>Ideal cooldown play-by-play, per objective</h2>" + "".join(blocks))

    if d.alignment:
        a0 = d.alignment[0]
        rows = ""
        for a in d.alignment:
            held = []
            if a.in_adds > a.adds_cover * 1.5 and a.in_adds - a.adds_cover > 0.1:
                held.append("held for adds")
            if a.units_cover and a.in_units > a.units_cover * 1.5 and a.in_units - a.units_cover > 0.1:
                held.append("held for secondary targets")
            rows += (f"<tr><td>{icons.img(d.icons.get(a.ability, ''), 'small')} {lk(a.ability)}</td>"
                     f"<td class='n'>{a.in_adds:.0%}</td><td class='n'>{a.in_units:.0%}</td>"
                     f"<td>{e(' / '.join(held) or 'no clear hold')}</td></tr>")
        tabs["cooldowns"].append(f"""<h2>What the top players do with their cooldowns</h2><div class="card scroll">
<p class="small">Share of their casts (after the opener) during add waves, which cover {a0.adds_cover:.0%} of the fight,
and on the secondary targets, which cover {a0.units_cover:.0%}. Much more than the coverage means they hold the cooldown.
SimC does not know that a secondary target must die fast, so compare with the simulated plans above.</p>
<table><tr><th>Cooldown</th><th>During adds</th><th>Secondary targets</th><th></th></tr>{rows}</table></div>""")

    # gear
    if d.gear:
        head = "".join(f"<th>{e(f)}</th>" for f in d.gear_fights)
        body = "".join(f"<tr><td class='small'>{lk(ch)}</td><td class='n'>{_pct(w)}</td>"
                       + "".join(f"<td class='n'>{_pct(per.get(f))}</td>" for f in d.gear_fights) + "</tr>"
                       for ch, per, w in d.gear[:8])
        mine = ("on the fight with your assignments and plan: " + "; ".join(d.assigns)) if d.assigns else \
            "on the fight without personal assignments (tick yours in the app to see if they change your gear)"
        tabs["gear"].insert(0, f"""<h2>Best gear from your bags, for this fight</h2><div class="card scroll">
<p class="small">Simmed {e(d.gear_plan or 'with the default priority list')}, {e(mine)}.</p>
<table><tr><th>Changes vs equipped</th><th>Weighted</th>{head}</tr>{body}</table>
<p class="small muted">Statistical error about +/-{d.gear_error:.2f}%.</p></div>""")

    # loot
    if d.loot:
        body = "".join(f"<tr><td>{icons.img(d.icons.get(i, ''), 'small')} {lk(i)}</td><td>{e(s)}</td>"
                       f"<td class='n'>{_pct(real) if real is not None else '-'}</td>"
                       f"<td class='n'>{_pct(v)}</td></tr>" for i, s, v, real in d.loot[:12])
        tabs["gear"].append(f"""<h2>What this boss drops, for you</h2><div class="card scroll">
<p class="small muted">"In your best sets": the item inserted in your best Top Gear sets, the rest of your gear
rearranged around it (its real value). "Single swap": the classic droptimizer value, on your equipped set.</p>
<table><tr><th>Item</th><th>Slot</th><th>In your best sets</th><th>Single swap</th></tr>{body}</table>
<p class="small muted">At item level {d.loot_ilvl}; statistical error about +/-{d.loot_error:.2f}%.</p></div>""")

    notes = list(d.notes)
    if d.validation:
        lo, med, hi = d.validation
        notes.insert(0, f"Validation: the top players' own characters simmed on this rebuilt fight give {med:.0%} of "
                        f"their real DPS (range {lo:.0%}-{hi:.0%}).")
    notes += [
        "A rebuilt fight is an approximation: good to choose between builds, items and plans, not a prediction "
        "of your exact DPS.",
        "Corpus analyses are correlations (what the top players do); SimC checks them on your character.",
    ]
    tabs["fight"].append('<h2>Notes</h2><div class="card small muted"><ul>' + "".join(f"<li>{e(n)}</li>" for n in notes)
                         + "</ul></div>")

    cls_icon = icons.img(icons.CLASS_ICON.format(cls=d.class_name.lower()), "large", "hero-ic") if d.class_name else ""
    header = f"""<header class="sheet-hero"><div class="in">{cls_icon}<div class="txt">
<h1>{e(d.boss)} <span class="pill gold">{e(d.difficulty)}</span></h1>
<p>{e(d.character)} &middot; {e(d.spec)} &middot; {d.kills} ranked kills &middot; {datetime.now():%d %b %Y %H:%M}</p>
</div></div><nav class="tabs"><div class="in">{''.join(f'<a href="#{k}">{e(label)}</a>' for k, label in TABS
                                                         if tabs[k])}</div></nav></header>"""
    panels = "".join(f'<section class="panel" id="{k}">{"".join(v)}</section>' for k, v in tabs.items() if v)
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(d.boss)} prep</title>{WH_SCRIPT}<style>{CSS}</style></head><body>{header}<main>{panels}"
            f'<p class="small muted">Generated by prep-a-fight. Player names are not shown.</p></main>{TAB_JS}'
            f"</body></html>")
