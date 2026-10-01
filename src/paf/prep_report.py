"""The one-page boss prep sheet (HTML), assembled from the other modules' results."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

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


PALETTE = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9", "#f59f00", "#d6336c", "#15aabf", "#5c7cfa", "#74b816"]


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
                         f'fill="#2f9e44" opacity="0.35"><title>{_mmss(w.time)} adds x{w.count}</title></rect>')
    for v in fight.vulnerable:
        fight_row.append(f'<rect x="{x(v.start)}" y="{y}" width="{max(2, v.duration * px):.1f}" height="16" '
                         f'fill="#e8590c" opacity="0.45"><title>{e(v.name)} x{v.multiplier:g}</title></rect>'
                         f'<text x="{x(v.start) + 2}" y="{y + 12}" font-size="10" fill="var(--fg)">x{v.multiplier:g}</text>')
    for w in fight.invulnerable:
        fight_row.append(f'<rect x="{x(w.start)}" y="{y}" width="{w.duration * px:.1f}" height="16" fill="#868e96" '
                         f'opacity="0.4"><title>boss away</title></rect>')
    if fight.lust_time is not None:
        fight_row.append(f'<rect x="{x(fight.lust_time)}" y="{y - 2}" width="{40 * px:.1f}" height="3" fill="#d6336c">'
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
            f'when the top players cast the same cooldown. Green: add waves; orange: boss vulnerability windows '
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


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--line:#e6e3dc;--card:#fff;--pos:#1f7a3a;--neg:#b3261e;--acc:#1c64d6}
@media (prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#ececf0;--muted:#9a9aa3;--line:#2a2a31;--card:#1d1d22;
--pos:#5cc37a;--neg:#f07068;--acc:#6ea8ff}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;margin:0;padding:20px 16px}
main{max-width:1000px;margin:auto}
h1{font-size:24px;margin:0} h2{font-size:17px;margin:28px 0 8px} .muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.key li{margin:4px 0} table{border-collapse:collapse;width:100%} td,th{padding:5px 8px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top} th{font-weight:600;color:var(--muted);font-size:12px}
td.n{text-align:right;white-space:nowrap} .pos{color:var(--pos);font-weight:600} .neg{color:var(--neg)}
.scroll{overflow-x:auto} a{color:var(--acc)} .small{font-size:12px}
"""


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
    return f"""<h2>Your raid and the adds</h2><div class="card">{head}
<p><b>{verdict}</b>{mine}</p>
<div class="scroll"><table><tr><th>Adds</th><th>Your raid without you</th><th>With you</th>
<th>Top raids' weakest quarter</th><th>Verdict</th></tr>{rows}</table></div>
<p class="small muted">Damage your raid puts on these adds, as a share of the top raids' (their median = 100%).</p>
<p class="small">Your raid on this boss, by what each spec does with the adds:</p><ul class="small">{groups}</ul>
<details><summary class="small">How it is computed</summary><p class="small muted">Measured: on this boss, each spec puts
a share of its damage on these adds while they are up (from the ranked kills): well above the median of all players =
AoE / funnel, well below = single target. Computed: your raid's damage on the adds = every player's DPS in your log x
their spec's share; the same for every top raid gives the reference range. Rule (not a measurement): if your raid
without you is within the top raids' range (above their weakest quarter), the others cover the adds and you stay on
the boss; otherwise you pad. Not promised: how long the adds will live. In the top kills it depends on the mechanics
and the strategy, not on the raid's DPS (checked: no correlation). Top players pad whatever their raid (they are
ranked on their own DPS), so their logs alone cannot tell what your raid needs.</p></details></div>"""


def render(d: PrepData) -> str:
    parts: list[str] = []
    parts.append(f"<h1>{e(d.boss)} ({e(d.difficulty)}): prep sheet</h1>")
    parts.append(f'<p class="muted">{e(d.spec)}, character {e(d.character)}. Built from {d.kills} ranked kills '
                 f'on Warcraft Logs and SimulationCraft, {datetime.now():%Y-%m-%d %H:%M}.</p>')

    def lk(text: str) -> str:
        return linkify(text, d.links)

    key = headline(d)
    if key:
        parts.append('<h2>What to remember</h2><div class="card key"><ul>'
                     + "".join("<li>" + "<br>".join(lk(line) for line in k.split("\n")) + "</li>" for k in key)
                     + "</ul></div>")

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
    parts.append(f"""<h2>The fight</h2><div class="card"><p>Typical duration {_mmss(d.duration)}; {"; ".join(extra)}.</p>
<div class="scroll"><table><tr><th>Phase</th><th></th></tr>{rows}</table></div>
<h3 class="small muted">Add waves (typical timeline across kills)</h3>
<div class="scroll"><table><tr><th>Time</th><th>Adds</th><th>Alive</th><th>Types</th></tr>{waves}</table></div>
{f'<p><a href="{e(d.timeline_file)}">Cooldown timelines of the top players</a></p>' if d.timeline_file else ''}
</div>""")

    if d.raid:
        parts.append(raid_section(d.raid))

    # sim of the fight
    if d.sim_dps and d.patchwerk_dps:
        boss = ""
        if d.sim_boss_dps:
            boss = f", {d.sim_boss_dps:,.0f} of it on the boss ({d.sim_boss_dps / d.sim_dps:.0%})"
        cal = ""
        if d.boss_share_real is not None:
            cal = (f" The fight is calibrated so that your share of damage on the boss matches the top players' "
                   f"logs ({d.boss_share_real:.0%}); add counts scaled by {d.add_scale:g}.")
        parts.append(f"""<h2>Your character on this fight</h2><div class="card">
<p>{d.sim_dps:,.0f} DPS on the rebuilt fight{boss}, vs {d.patchwerk_dps:,.0f} on a Patchwerk of the same length
({(d.sim_dps / d.patchwerk_dps - 1):+.0%}).{cal}</p></div>""")

    # talents
    if d.talents:
        tc = d.talents
        head = "".join(f"<th>{e(f)}</th>" for f in tc.fights)
        body = f"<tr><td>your build</td><td class='n'></td>{''.join('<td class=n>ref</td>' for _ in tc.fights)}<td></td></tr>"
        for r in tc.rows:
            cells = ""
            for f in tc.fights:
                tot, boss = r.per_fight.get(f, (None, None))
                cells += f"<td class='n'>{_pct(tot)}{'<br><span class=small>boss ' + _pct(boss, 1) + '</span>' if boss is not None else ''}</td>"
            diff = ""
            if r.add or r.drop:
                diff = f"take {e(', '.join(r.add) or '-')}<br><span class='muted'>drop {e(', '.join(r.drop) or '-')}</span>"
            body += (f"<tr><td>{e(r.build.label)}<br><span class='small muted'>{r.build.count} players, median rank "
                     f"{r.build.median_rank:.0f}</span></td><td class='n'></td>{cells}<td class='small'>{diff}</td></tr>")
        parts.append(f"""<h2>Talents of the top players, on your character</h2><div class="card scroll">
<table><tr><th>Build</th><th></th>{head}<th>vs your build</th></tr>{body}</table>
<p class="small muted">Statistical error about +/-{tc.error:.2f}%.</p></div>""")

    # cooldown plans
    if d.plans:
        pc = d.plans
        times = "; ".join(f"{e(a)} at {', '.join(_mmss(t) for t in ts)}" for a, ts in pc.cd_times.items() if ts)
        body = "".join(f"<tr><td>{e(p.name.replace('_', ' '))}</td><td class='n'>{_pct(tot)}</td>"
                       f"<td class='n'>{_pct(boss)}</td><td class='small'>{e(p.description)}</td></tr>"
                       for p, tot, boss in pc.rows)
        parts.append(f"""<h2>Cooldown plans</h2><div class="card scroll">
<p class="small">When the top players use their cooldowns: {times}.</p>
<table><tr><th>Plan</th><th>Total</th><th>Boss</th><th></th></tr>{body}</table>
<p class="small muted">Statistical error about +/-{pc.error:.2f}%. SimC evaluates these plans; it does not invent new ones.</p>
</div>""")

    # ideal play-by-play per objective
    if d.optimized:
        blocks = []
        for p in d.optimized:
            changed = {k: r for k, r in p.choice.items() if r.name != "default"}
            rules = "".join(f"<tr><td>{link(cd_name(d, k), d.links.get(k))}</td><td>{e(rule_phrase(d, r.name))}</td></tr>"
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
                checks += "<ul class='small'>" + "".join(f"<li>&#9888; {e(f)}</li>" for f in p.flags) + "</ul>"
            blocks.append(f"""<div class="card"><h3 style="margin:0 0 6px">{e(objective_name(d, p.objective))}: {_pct(p.gain)}
<span class="small muted">vs the default priority list{'; ' + others if others else ''}</span></h3>
{checks}{plan_timeline_svg(p, d.fight, d.tops_casts, d.tops_players, names=d.cd_names)}
<table><tr><th>Cooldown</th><th>Rule</th></tr>{rules}</table>
<details><summary class="small">Play-by-play of one simulated pull</summary><div class="scroll"><table>
<tr><th>Time</th><th>Cooldown</th><th>Context</th></tr>{steps}</table></div></details>
<details><summary class="small">MRT note</summary><pre class="small" style="white-space:pre-wrap">{e(note)}</pre></details>
</div>""")
        parts.append("<h2>Ideal cooldown play-by-play, per objective</h2>" + "".join(blocks))

    if d.alignment:
        a0 = d.alignment[0]
        rows = ""
        for a in d.alignment:
            held = []
            if a.in_adds > a.adds_cover * 1.5 and a.in_adds - a.adds_cover > 0.1:
                held.append("held for adds")
            if a.units_cover and a.in_units > a.units_cover * 1.5 and a.in_units - a.units_cover > 0.1:
                held.append("held for secondary targets")
            rows += (f"<tr><td>{lk(a.ability)}</td><td class='n'>{a.in_adds:.0%}</td><td class='n'>{a.in_units:.0%}</td>"
                     f"<td>{e(' / '.join(held) or 'no clear hold')}</td></tr>")
        parts.append(f"""<h2>What the top players do with their cooldowns</h2><div class="card scroll">
<p class="small">Share of their casts (after the opener) during add waves, which cover {a0.adds_cover:.0%} of the fight,
and on the secondary targets, which cover {a0.units_cover:.0%}. Much more than the coverage means they hold the cooldown.
SimC does not know that a secondary target must die fast, so compare with the simulated plans above.</p>
<table><tr><th>Cooldown</th><th>During adds</th><th>Secondary targets</th><th></th></tr>{rows}</table></div>""")

    if d.assigns:
        parts.append('<h2>Your assignments</h2><div class="card small"><ul>'
                     + "".join(f"<li>{e(a)}</li>" for a in d.assigns) + "</ul></div>")

    # gear
    if d.gear:
        head = "".join(f"<th>{e(f)}</th>" for f in d.gear_fights)
        body = "".join(f"<tr><td class='small'>{lk(ch)}</td><td class='n'>{_pct(w)}</td>"
                       + "".join(f"<td class='n'>{_pct(per.get(f))}</td>" for f in d.gear_fights) + "</tr>"
                       for ch, per, w in d.gear[:8])
        mine = ("on the fight with your assignments and plan: " + "; ".join(d.assigns)) if d.assigns else \
            "on the fight without personal assignments (tick yours in `paf serve` to see if they change your gear)"
        parts.append(f"""<h2>Best gear from your bags, for this fight</h2><div class="card scroll">
<p class="small">Simmed {e(d.gear_plan or 'with the default priority list')}, {e(mine)}.</p>
<table><tr><th>Changes vs equipped</th><th>Weighted</th>{head}</tr>{body}</table>
<p class="small muted">Statistical error about +/-{d.gear_error:.2f}%.</p></div>""")

    # loot
    if d.loot:
        body = "".join(f"<tr><td>{lk(i)}</td><td>{e(s)}</td><td class='n'>{_pct(real) if real is not None else '-'}</td>"
                       f"<td class='n'>{_pct(v)}</td></tr>" for i, s, v, real in d.loot[:12])
        parts.append(f"""<h2>What this boss drops, for you</h2><div class="card scroll">
<p class="small muted">"In your best sets": the item inserted in your best Top Gear sets, the rest of your gear
rearranged around it (its real value). "Single swap": the classic droptimizer value, on your equipped set.</p>
<table><tr><th>Item</th><th>Slot</th><th>In your best sets</th><th>Single swap</th></tr>{body}</table>
<p class="small muted">At item level {d.loot_ilvl}; statistical error about +/-{d.loot_error:.2f}%.</p></div>""")

    if d.validation:
        lo, med, hi = d.validation
        d.notes.insert(0, f"Validation: the top players' own characters simmed on this rebuilt fight give {med:.0%} of "
                          f"their real DPS (range {lo:.0%}-{hi:.0%}).")
    notes = d.notes + [
        "A rebuilt fight is an approximation: good to choose between builds, items and plans, not a prediction "
        "of your exact DPS.",
        "Corpus analyses are correlations (what the top players do); SimC checks them on your character.",
    ]
    parts.append('<h2>Notes</h2><div class="card small muted"><ul>' + "".join(f"<li>{e(n)}</li>" for n in notes)
                 + "</ul></div>")
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(d.boss)} prep</title>{WH_SCRIPT}<style>{CSS}"
            f"a.wh{{color:inherit;text-decoration:none;border-bottom:1px dotted currentColor}}</style></head><body><main>{''.join(parts)}"
            f'<p class="small muted">Generated by prep-a-fight. Player names are not shown.</p></main></body></html>')
