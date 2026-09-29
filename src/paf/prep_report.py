"""The one-page boss prep sheet (HTML), assembled from the other modules' results."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime

e = html.escape


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def _pct(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "-"
    cls = "pos" if v > 0.0001 else "neg" if v < -0.0001 else ""
    return f'<span class="{cls}">{v:+.{digits}f}%</span>'


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
    loot: list[tuple[str, str, float]] = field(default_factory=list)  # item, slot, delta on the boss fight
    loot_ilvl: int = 0
    loot_error: float = 0.0
    notes: list[str] = field(default_factory=list)
    optimized: list = field(default_factory=list)  # paf.optimize.Plan per objective
    mrt: dict[str, str] = field(default_factory=dict)  # objective -> MRT note
    alignment: list = field(default_factory=list)  # paf.optimize.Alignment
    fight: object | None = None  # paf.fight.Fight used by the sims
    assigns: list[str] = field(default_factory=list)  # notes of the player's assignments
    validation: tuple[float, float, float] | None = None  # simulated / real DPS of the top players (min, median, max)


def headline(d: PrepData) -> list[str]:
    """The few things to remember, computed from the results."""
    out = []
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
    labels = {"boss": "boss damage", "total": "total damage (pad)", "adds": "damage to adds",
              "secondary": "damage to secondary targets"}
    for p in d.optimized:
        if p.objective == "adds" or p.gain <= 2 * p.error:
            continue
        changed = [f"{k.replace('use_item:', '')} {r.name.replace('_', ' ')}"
                   for k, r in p.choice.items() if r.name != "default"]
        others = ", ".join(f"{o} {v:+.1f}%" for o, v in p.totals.items() if o not in (p.objective, "adds"))
        trust = "robust" if p.robust and not p.flags else "to double-check (see the plan)"
        out.append(f"Cooldowns for {labels[p.objective]}: {p.gain:+.1f}% ({trust}); {'; '.join(changed)}"
                   + (f" [{others}]" if others else "") + ".")
    held = [a for a in d.alignment if a.units_cover and a.in_units > a.units_cover * 1.5 and a.in_units - a.units_cover > 0.1]
    if held:
        out.append("Top players hold " + ", ".join(a.ability for a in held) + " for the secondary targets.")
    if d.plans and d.plans.rows:
        p, tot, _ = d.plans.rows[0]
        if p.name != "default" and tot > 2 * d.plans.error:
            out.append(f"Cooldowns: '{p.name.replace('_', ' ')}' ({p.description}) gives {tot:+.1f}%.")
        else:
            out.append("Cooldowns: the default priority list is already the best plan tested.")
    if d.gear:
        changes, _, w = d.gear[0]
        if w > 2 * d.gear_error:
            out.append(f"Gear: {changes} ({w:+.2f}%).")
        else:
            out.append("Gear: your equipped set is already the best among your items on this fight.")
    if d.loot:
        item, slot, delta = d.loot[0]
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


def render(d: PrepData) -> str:
    parts: list[str] = []
    parts.append(f"<h1>{e(d.boss)} ({e(d.difficulty)}): prep sheet</h1>")
    parts.append(f'<p class="muted">{e(d.spec)}, character {e(d.character)}. Built from {d.kills} ranked kills '
                 f'on Warcraft Logs and SimulationCraft, {datetime.now():%Y-%m-%d %H:%M}.</p>')

    key = headline(d)
    if key:
        parts.append('<h2>What to remember</h2><div class="card key"><ul>'
                     + "".join(f"<li>{e(k)}</li>" for k in key) + "</ul></div>")

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
        labels = {"boss": "Boss damage", "total": "Total damage (pad)", "adds": "Damage to adds", "secondary": "Damage to secondary targets (burst them)"}
        blocks = []
        for p in d.optimized:
            changed = {k: r for k, r in p.choice.items() if r.name != "default"}
            rules = "".join(f"<tr><td>{e(k.replace('use_item:', ''))}</td><td>{e(r.description)}</td></tr>"
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
            blocks.append(f"""<div class="card"><h3 style="margin:0 0 6px">{labels.get(p.objective, p.objective)}: {_pct(p.gain)}
<span class="small muted">vs the default priority list{'; ' + others if others else ''}</span></h3>
{checks}<table><tr><th>Cooldown</th><th>Rule</th></tr>{rules}</table>
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
            rows += (f"<tr><td>{e(a.ability)}</td><td class='n'>{a.in_adds:.0%}</td><td class='n'>{a.in_units:.0%}</td>"
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
        body = "".join(f"<tr><td class='small'>{e(ch)}</td><td class='n'>{_pct(w)}</td>"
                       + "".join(f"<td class='n'>{_pct(per.get(f))}</td>" for f in d.gear_fights) + "</tr>"
                       for ch, per, w in d.gear[:8])
        parts.append(f"""<h2>Best gear from your bags</h2><div class="card scroll">
<p class="small muted">Simmed {e(d.gear_plan or 'with the default priority list')}.</p>
<table><tr><th>Changes vs equipped</th><th>Weighted</th>{head}</tr>{body}</table>
<p class="small muted">Statistical error about +/-{d.gear_error:.2f}%.</p></div>""")

    # loot
    if d.loot:
        body = "".join(f"<tr><td>{e(i)}</td><td>{e(s)}</td><td class='n'>{_pct(v)}</td></tr>" for i, s, v in d.loot[:12])
        parts.append(f"""<h2>What this boss drops, for you</h2><div class="card scroll">
<table><tr><th>Item</th><th>Slot</th><th>On this fight</th></tr>{body}</table>
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
            f"<title>{e(d.boss)} prep</title><style>{CSS}</style></head><body><main>{''.join(parts)}"
            f'<p class="small muted">Generated by prep-a-fight. Player names are not shown.</p></main></body></html>')
