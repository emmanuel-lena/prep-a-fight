"""The overview of a prep sheet as a raid lead's briefing: a few lines that say what the fight is, the changes that
matter for you in order (said plainly when a change barely matters), the fight drawn as an annotated timeline, and
what to keep in mind once the pull starts (a list to tick, which fills the "ready" ring of the header).
Written to read like a person's notes rather than a dashboard: serif headings, sentences, one accent colour.
Everything is readable without JavaScript and without motion.
"""

from __future__ import annotations

import html
import re

from paf import icons, theme

e = html.escape
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;'
         '0,9..144,600;1,9..144,400&display=swap">')


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _pct(t: float, dur: float) -> float:
    return max(0.0, min(100.0, 100 * t / dur)) if dur else 0.0


# --- the few lines on top --------------------------------------------------------------------------------------------

def lede_html(d) -> str:
    dur = d.duration or 0
    units = {w.name for w in (d.fight.add_waves if getattr(d, "fight", None) is not None else []) if not w.scalable}
    waves = [w for w in d.waves if w[1] and not any(u.startswith(w[3]) or w[3].startswith(u) for u in units)]
    parts = [f"A {_mmss(dur)} fight" if dur else "This fight"]
    if waves:  # the add waves; a boss unit played as a wave (an Echo) is not one of them
        n = len({round(w[0]) for w in waves})  # a wave is a moment: two types at one Imbibe are one (a review: 6)
        parts.append(f"with {n} waves of adds" if n > 1 else "with one wave of adds")
    lust = ""
    if d.lust is not None:
        lust = "with Bloodlust at the pull" if d.lust < 15 else f"with Bloodlust around {_mmss(d.lust)}"
    first = " ".join(parts) + (f", {lust}." if lust else ".")  # one sentence, so that a catalog can say it
    second = ""
    focus = d.fight.focus if d.fight is not None else []
    if focus:
        members = list(dict.fromkeys(f.name for f in focus))
        stacked = d.fight.targets
        second += (f" A council of {len(members)} bosses, {stacked} of them stacked: the top players cleave them and "
                   f"start on {e(focus[0].name)}." if stacked > 1 else
                   f" A council of {len(members)} bosses, never stacked: the top players hit one at a time and start "
                   f"on {e(focus[0].name)}.")
    if d.add_share_spec is not None and not (focus and d.add_share_spec < 0.05):  # a council: said above
        real = getattr(d, "boss_share_real", None)  # the calibration's figure, said the same everywhere
        a = 1 - real if real is not None else d.add_share_spec
        second += (f" The best {e(d.spec)} players keep {1 - a:.0%} of their damage on the boss and put {a:.0%} on the adds."
                  if a >= 0.05 else f" The best {e(d.spec)} players put {1 - a:.0%} of their damage on the boss.")
        from paf.prep_report import wanted

        if wanted(d) == "total":  # your raid's call goes against what the top players do: say why, in the same breath
            second += " Your raid lacks cleave: you pad the adds."
    return f"<p class='lede rv'>{first}{second}</p>"


# --- what matters for you, in order ---------------------------------------------------------------------------------

def _moves(d) -> list[tuple[float, str, str, str]]:
    """(gain, the sentence, its detail, a button) of each change worth saying, biggest first."""
    from paf.prep_report import _goal, best_build, cd_name, copy_button, linkify, rule_phrase, wanted

    out = []
    best = best_build(d)
    if d.talents:
        g = best.per_fight.get(d.talents.fights[0], (0.0, None))[0] if best else 0.0
        if best is not None and g > 2 * d.talents.error:
            from paf.talents import utility

            takes = list(dict.fromkeys(x for x in best.add if x not in best.drop))  # one name both ways (a rank
            drops = list(dict.fromkeys(x for x in best.drop if x not in best.add))  # or another node): no change
            free = utility(takes + drops, getattr(d, "class_name", ""), d.spec)  # the player's choice: not counted
            takes, drops = [x for x in takes if x not in free], [x for x in drops if x not in free]
            add = ", ".join(takes)
            say = (f"It takes {e(add)}." if takes and len(takes) + len(drops) <= 6 else  # a few: named; more: counted,
                   f"+{len(takes)} / &minus;{len(drops)} talents: see What to change." if takes or drops else "")
            # never a cut list read as the whole swap (DPS round 12: 6 of 10 named, the drops unsaid)
            out.append((g, f"Switch to <b>{e(best.build.label)}</b>, the talents of {best.build.count} top players.",
                        say,
                        copy_button(best.build.code, "Copy the talent string") if best.build.code else ""))
        else:
            out.append((0.0, f"Keep your talents: no build of the top players beats yours by more than "
                             f"{2 * d.talents.error:.1f}% on this fight.", "", ""))
    want = wanted(d) or "boss"
    plans = [p for p in d.optimized if p.objective in ("boss", "total")]
    plan = next((p for p in plans if p.objective == want and p.gain > 2 * p.error), None)
    if plan is None and wanted(d) is None:
        plan = max((p for p in plans if p.gain > 2 * p.error), key=lambda p: p.gain, default=None)
    from paf.simple import fallen

    if plan is not None and fallen(plan):  # the fight tab plays the default list (a review: "Play your cooldowns
        # for total damage +0.6%" beside a plan tagged not played)
        out.append((0.0, "Play SimC's default priority list: the plan's small gain turns into a loss on a slower "
                         "kill.", "", ""))
    elif plan is not None:
        rules = [(cd_name(d, k), rule_phrase(d, r.name)) for k, r in plan.choice.items() if r.name != "default"]
        say = "; ".join(f"{n}: {r}" for n, r in rules) + ("" if getattr(plan, "robust", True) else
                                                          ". Not robust: the gain can vanish on a harder fight.")
        out.append((plan.gain, f"Play your cooldowns for {e(_goal(plan.objective))} damage.", e(say),
                    copy_button(d.mrt[plan.objective], "Copy the MRT note") if d.mrt.get(plan.objective) else ""))
    elif plans:
        role = {"total": " for padding the adds", "boss": " for boss damage"}.get(wanted(d) or "", "")
        out.append((0.0, f"Play SimC's default priority list: no cooldown plan beats it{role} here.", "", ""))
    if d.gear:
        changes, _, w = d.gear[0]
        if w > 2 * d.gear_error:
            out.append((w, "Swap some gear from your bags.", "; ".join(linkify(c, d.links) for c in changes.split("; ")), ""))
        else:
            out.append((0.0, "Keep the gear you wear: nothing in your bags beats it beyond the sims' noise here.", "", ""))
    return sorted(out, key=lambda m: -m[0])


def moves_html(d) -> str:
    moves = _moves(d)
    if not moves:
        return ""
    from paf.prep_report import places

    items = []
    gains = [m[0] for m in moves]
    for i, (gain, say, more, button) in enumerate(moves, 1):
        g = f"{gain:+.{places(gain, gains)}f}%"  # two that round alike: two decimals
        if gain >= 3:
            tag = f"<span class='gain big'>{g}</span>"
        elif gain >= 1:
            tag = f"<span class='gain'>{g}</span>"
        elif gain > 0:
            tag = f"<span class='gain tiny' title='barely matters'>{g}</span>"
        else:
            tag = "<span class='gain ok'>&#10003;</span>"
        body = f"<p class='say'>{say}</p>" + (f"<div class='why'>{more}{(' ' + button) if button else ''}</div>"
                                              if (more or button) else "")
        items.append(f"<li class='rv'><span class='n'>{i}</span><div class='mv'>{body}</div>{tag}</li>")
    top = moves[0][0]
    note = ("" if top >= 1 else
            "<p class='aside rv'>Your setup is already right here: the changes below are small.</p>" if top > 0 else
            "<p class='aside rv'>Your setup is already right here: nothing below changes it.</p>")
    return f"<h2 class='rv'>What matters for you</h2>{note}<ol class='moves'>{''.join(items)}</ol>"


# --- the fight, drawn ------------------------------------------------------------------------------------------------

WIDTH_PX = 1000  # the timeline's width on a desktop (labels are placed for it, and wrap rows on phones)
FLIP_AT = 72  # % of the fight after which a label opens to the left of its pin


def _label_px(label: str, icon: bool) -> float:
    return len(label) * 6.9 + (20 if icon else 0) + 18


def _rows(events: list[tuple[float, str, bool]], dur: float) -> list[int]:
    """A row for each label (in time order) so that labels never overlap; a label past FLIP_AT opens leftwards."""
    spans: list[list[tuple[float, float]]] = []
    rows = []
    for t, label, icon in events:
        x = _pct(t, dur)
        w = _label_px(label, icon) / WIDTH_PX * 100
        a, b = (x - w, x) if x > FLIP_AT else (x, x + w)
        row = next((r for r, taken in enumerate(spans) if all(b < s - .4 or a > e + .4 for s, e in taken)), None)
        if row is None:
            spans.append([])
            row = len(spans) - 1
        spans[row].append((a, b))
        rows.append(row)
    return rows


def _short(name: str) -> str:
    return name.split(" (after")[0].split(" (boss aura)")[0].strip()


def _note(t: float, dur: float, row: int, side: str, label: str, title: str, text: str, kind: str, icon: str = "") -> str:
    pic = icons.img(icon, "small", "nt-ic") if icon else ""
    flip = " flip" if _pct(t, dur) > FLIP_AT else ""
    return (f"<button class='note {side} {kind}{flip}' style='left:{_pct(t, dur):.2f}%;--row:{row}' "
            f"data-t='{_mmss(t)}' data-title='{e(title)}' data-text='{e(text)}' aria-label='{e(_mmss(t) + ' ' + title)}'>"
            f"<span class='pin'></span><span class='lab'>{pic}{e(label)}</span></button>")


def fight_map_html(d) -> str:
    from paf.prep_report import _goal, wanted

    dur = d.duration or (d.fight.duration if d.fight else 0)
    if not dur:
        return ""
    phases = sorted(d.phases, key=lambda p: p[1])
    brackets = ""
    for i, (name, start) in enumerate(phases):
        end = phases[i + 1][1] if i + 1 < len(phases) else dur
        short = name  # the full name: the game's table translates it
        brackets += (f"<div class='ph' style='left:{_pct(start, dur):.2f}%;width:{_pct(end - start, dur):.2f}%' "
                     f"title='{e(name)}'><span>{e(short)}</span></div>")
    above: list[tuple[float, str, str, str, str, str]] = []  # t, label, title, text, kind, icon
    shade = ""
    for t, count, life, name in d.waves:
        if count == 0:
            shade += (f"<div class='burst' style='left:{_pct(t, dur):.2f}%;width:{max(_pct(life, dur), .6):.2f}%'></div>")
            above.append((t, "burst", name, f"The boss takes more damage for {life:.0f} s: a good moment for your "
                                             f"big cooldowns, if they are ready.", "k-burst", ""))
        else:
            shade += (f"<div class='adds' style='left:{_pct(t, dur):.2f}%;width:{max(_pct(life, dur), .6):.2f}%'></div>")
            what = f"{count} × {_short(name)}" if count > 1 and name else (_short(name) if name else f"{count} adds")
            above.append((t, f"{count} adds" if count > 1 else _short(name or "add"), what,
                          f"Alive about {life:.0f} s.", "k-adds", ""))
    for f in (d.fight.focus if d.fight is not None else []):
        above.append((f.start, f.name, f"Focus {f.name}", f"{f.support:.0%} of the top players' kills hit {f.name} here.",
                      "k-focus", ""))
    if d.lust is not None:
        above.append((d.lust, "Bloodlust", "Bloodlust", "Bloodlust usually goes out here: worth having your cooldowns ready "
                      "for it.",
                      "k-lust", ""))
    below: list[tuple[float, str, str, str, str, str]] = []
    want = wanted(d) or "boss"
    plan = next((p for p in d.optimized if p.objective == want), None) or next(iter(d.optimized), None)
    if plan is not None and d.fight is not None:
        from paf.optimize import plan_moments

        seen: set[str] = set()
        for t, labels in plan_moments(plan, d.fight, d.cd_names):
            names = list(dict.fromkeys(labels))
            ic = next((d.icons.get(n) for n in names if d.icons.get(n)), "")
            label = " + ".join(names) if not (ic and set(names) <= seen) else ""  # a cooldown seen before: its icon
            seen.update(names)
            below.append((t, label, ", ".join(names),
                          f"A good moment for {', '.join(names)}: the sim does best pressing it here "
                          f"({_goal(plan.objective)} damage). Your raid's calls come first.", "k-you", ic))
    if d.defensives:
        for m in d.defensives.moments:
            name = m.spells[0][0] if m.spells else "a defensive"
            why = f" for {m.boss_ability}" if m.boss_ability else ""
            below.append((m.time, name, f"{name}{why}", f"{m.share:.0%} of the top players press {name}{why} here.",
                          "k-def", d.icons.get(name, "")))
    if not (above or below):
        return ""
    above.sort()
    below.sort()
    ra = _rows([(t, lab, bool(ic)) for t, lab, _, _, _, ic in above], dur)
    rb = _rows([(t, lab, bool(ic)) for t, lab, _, _, _, ic in below], dur)
    notes = "".join(_note(t, dur, r, "up", lab, ti, tx, k, ic) for (t, lab, ti, tx, k, ic), r in zip(above, ra, strict=True))
    notes += "".join(_note(t, dur, r, "down", lab, ti, tx, k, ic) for (t, lab, ti, tx, k, ic), r in zip(below, rb, strict=True))
    ticks = "".join(f"<span style='left:{_pct(t, dur):.2f}%'>{_mmss(t)}</span>"
                    for t in range(0, int(dur) + 1, 60 if dur <= 480 else 120))
    up, down = (max(ra) + 1 if ra else 0), (max(rb) + 1 if rb else 0)
    focus_legend = "<span class='lg k-focus'>focus</span>" if d.fight is not None and d.fight.focus else ""
    return f"""<h2 class='rv'>How the fight goes</h2>
<div class='tl-scroll rv'><div class='tl' style='--up:{up};--down:{down}' data-dur='{dur:.0f}'>
<div class='tl-phases'>{brackets}</div><div class='tl-zone up'></div>
<div class='tl-axis'>{shade}<div class='tl-ticks'>{ticks}</div></div><div class='tl-zone down'></div>
{notes}<div class='tl-legend small muted'><span class='lg k-adds'>adds</span><span class='lg k-burst'>burst window</span>{focus_legend}
<span class='lg k-you'>suggested cooldowns</span><span class='lg k-def'>defensives</span></div></div></div>
<p class='margin rv' aria-live='polite'><b class='m-t'></b> <span class='m-title'>Point at a note on the timeline</span>
<span class='m-text'>: what comes then, and what can help.</span></p>"""


# --- once the pull starts --------------------------------------------------------------------------------------------

def _fight_items(d) -> list[tuple[str, str]]:
    from paf.prep_report import checklist_items

    skip = ("Talents:", "Gear", "Cooldowns (", "Talents :")
    return [(w, x) for w, x in checklist_items(d) if not w.startswith(skip)]


def checklist_html(d) -> str:
    items = _fight_items(d)
    if not items:
        return ""
    lines = "".join(f"<li class='rv'><label><input type='checkbox'><span class='box' aria-hidden='true'></span>"
                    f"<span class='t'>{what}</span></label>{extra}</li>" for what, extra in items)
    return f"<h2 class='rv' id='checks'>Once the pull starts</h2><ul class='checks'>{lines}</ul>"


def ready_count(d) -> int:
    return len(_fight_items(d))


def ready_ring(n: int) -> str:
    if not n:
        return ""
    return (f"<a class='ready' href='#checks' title='Tick the {n} points of &quot;Once the pull starts&quot; as you learn them'>"
            f"<svg viewBox='0 0 44 44' aria-hidden='true'>"
            f"<circle cx='22' cy='22' r='19' class='r-bg'/><circle cx='22' cy='22' r='19' class='r-fg'/></svg>"
            f"<div class='r-txt'><b class='r-n'>0/{n}</b><span>checked</span></div></a>")


def _k(v: float) -> str:
    return f"{v / 1000:,.0f}k" if v >= 10000 else f"{v:,.0f}"


def aim_html(d) -> str:
    """What to aim for, at a glance: your character simmed on this fight (boss damage first), the same on a training
    dummy, and what the top players of your spec really do here."""
    if not d.sim_dps:
        return ""
    from paf.prep_report import wanted

    pad = hasattr(d, "goal") and wanted(d) == "total" and d.sim_boss_dps  # your role is to pad: the total first
    you = d.sim_dps if pad else (d.sim_boss_dps or d.sim_dps)
    unit = (f"DPS in all, {_k(d.sim_boss_dps)} on the boss" if pad else
            f"boss DPS, {_k(d.sim_dps)} in all" if d.sim_boss_dps else "DPS")
    tiles = [("You can aim for", _k(you), unit + " on this fight, played well")]
    if d.patchwerk_dps:
        tiles.append(("On a training dummy", _k(d.patchwerk_dps),
                      f"DPS: this fight costs you {1 - d.sim_dps / d.patchwerk_dps:.0%}" if d.sim_dps < d.patchwerk_dps
                      else "DPS: this fight gives you more than a dummy"))
    p = _profile(d)
    if p is not None and getattr(p, "boss_dps", None):
        tiles.append((f"The best {e(d.spec)}", _k(p.dps), "DPS in all (median of the top 100, their own gear, as "
                                                          "Warcraft Logs ranks them)"))  # its 'boss' counts other units
    cells = "".join(f"<div class='kpi'><div class='l'>{lab}</div><div class='v'>{val}</div><div class='s'>{sub}</div>"
                    "</div>" for lab, val, sub in tiles)
    note = ""
    if overshoot(d):  # the sim's total above what the best really do: said beside the figure, with your own log
        best = ((getattr(d, "specs", None) or {}).get("kills") or {}).get("best")
        note = (f"<p class='aim-note small'>SimC's area damage hits every add in range: its total runs above real logs "
                f"(the top 100 do {_k(p.dps)} in all). Trust the boss figure and the gaps between plans more than this "
                f"total.{f' Your best kill here: {_k(best)} in all.' if best else ''}</p>")
    return f"<div class='aim rv'>{cells}</div>{note}"


def _wanted(d):
    from paf.prep_report import wanted

    return wanted(d) if hasattr(d, "goal") else None


def _profile(d):
    """Your spec's total vs boss DPS rankings on this boss (read with your raid's log)."""
    raid = getattr(d, "raid", None)
    return getattr(d, "your_profile", None) or (getattr(raid, "your_profile", None) if raid else None)


def overshoot(d) -> bool:
    """The sim's total DPS on this fight above the top players' real median: the adds count more in SimC."""
    p = _profile(d)
    return bool(p is not None and getattr(p, "dps", None) and d.sim_dps and d.sim_dps > 1.05 * p.dps)


def spec_role(s: dict) -> str:
    role = "padding the adds (total damage)" if s.get("role") == "total" else "boss damage"
    n = s.get("assigns") or 0
    return role + (f", with your {n} assignment{'s' if n != 1 else ''}" if n else "")


def spec_gaps(s: dict) -> list[tuple[str, float | None, str]]:
    """(spec, its gap on you in %, its class: go | same | low) for each spec simmed, yours first (gap None)."""
    rows = [r for r in s.get("rows") or [] if r.get("sim")]
    mine = next((r for r in rows if r["spec"] == s.get("mine")), None)
    if mine is None:
        return []
    out: list[tuple[str, float | None, str]] = [(mine["label"], None, "mine")]
    for r in sorted((r for r in rows if r is not mine), key=lambda r: -r["sim"]):
        gap = 100 * (r["sim"] / mine["sim"] - 1)
        noise = 2 * ((r.get("error") or 0) ** 2 + (mine.get("error") or 0) ** 2) ** 0.5
        out.append((r["label"], gap, "go" if gap > noise and s.get("verdict") == "go" else
                    "same" if abs(gap) <= noise else "low" if gap < 0 else "up"))
    return out


def _short_note(missing: set, specs: list, mine: str) -> str:
    """The line under the spec tiles when some were simmed one item short (too new for SimC)."""
    if not missing:
        return ""
    item = e(", ".join(sorted(missing)))
    if mine in specs:  # your own: every gap is measured against it
        return (f"<p class='small muted'>Every gap is only roughly right: {e(_and_specs(specs))} simmed without "
                f"{item} (too new for SimC).</p>")
    return (f"<p class='small muted'>&dagger; simmed without {item} (too new for SimC): "
            f"{'that tile' if len(specs) == 1 else 'those tiles'} only roughly right.</p>")


def _and_specs(specs: list) -> str:
    return specs[0] if len(specs) == 1 else ", ".join(specs[:-1]) + " and " + specs[-1]


def spec_html(d) -> str:
    """We simmed your character in each damage spec of your class (paf.specgear): one tile per spec with its gap on
    you, for your role and assignments on this fight. Advice for you only, never about another player."""
    s = getattr(d, "specs", None)
    gaps = spec_gaps(s) if s else []
    if len(gaps) < 2:
        return ""
    notes = " ".join(s.get("notes") or [])

    def short(name: str) -> str:  # simmed one item short (too new for this simc build): said on its tile
        m = re.search(rf"{re.escape(name)}: the top players' (\w+) is unknown to this SimC", notes)
        if not m:
            return ""
        row = next((r for r in s.get("rows") or [] if r.get("label") == name), {})
        item = next((i.get("name") for i in row.get("items") or [] if i.get("slot") == m[1]), "")
        what = item or re.sub(r"\d$", "", m[1]).replace("_", " ")
        missing.add(what)
        short_specs.append(name)
        return "" if mine_label in short_specs else "<small> &dagger;</small>"  # the item said once, under the
        # tiles; your own spec short: no dagger anywhere, the note says every gap (DPS confirm round 8)
    missing: set[str] = set()  # (DPS confirm rounds 6-7: your own spec short makes every gap rough, no dagger)
    short_specs: list[str] = []
    mine_label = gaps[0][0]
    tiles = "".join(
        f"<div class='spt {kind}'><span class='spt-n'>{e(name)}</span><span class='spt-v'>"
        f"{'your spec' if gap is None else 'same' if kind == 'same' else f'{gap:+.0f}%'}{short(name)}</span></div>"
        for name, gap, kind in gaps)
    failed = " ".join(s.get("notes") or [])

    def why(r) -> str:  # said, never silently dropped, with its reason
        return "SimC failed on it" if f"{r.get('spec')} could not be simmed" in failed else "no build found"
    tiles += "".join(f"<div class='spt low'><span class='spt-n'>{e(r.get('label', r.get('spec', '')))}</span>"
                     f"<span class='spt-v'>not simmed: {why(r)}</span></div>"
                     for r in s.get("rows") or [] if not r.get("sim"))
    return (f"<div class='specs rv'><p class='specs-head'><b>We simmed your character in each damage spec of your class"
            f"</b> <span class='muted'>for {e(spec_role(s))}, on this fight</span></p>"
            f"<div class='spt-row'>{tiles}</div>"
            + _short_note(missing, short_specs, mine_label) + "</div>")


def confidence_pill(d) -> str:
    if not d.validation:
        return ""
    med = d.validation[1]
    gap = abs(med - 1)
    level = "high" if gap <= 0.05 else "medium" if gap <= 0.12 else "low"
    say = {"high": "the top players' own characters, simmed on this fight, do "
                   f"{med:.0%} of their real damage: trust the numbers"
                   + (", the boss figure and the gaps more than the total (above)." if overshoot(d) else "."),
           "medium": f"the sim does {med:.0%} of the damage the best players really did: trust which option wins "
                     f"more than the exact %.",
           "low": f"the sim does {med:.0%} of the damage the best players really did: read the numbers as hints."}[level]
    share = next((m for n in d.notes if (m := re.search(r"puts (\d+)% of (?:its|your) damage on the boss vs (\d+)%", n))),
                 None)
    if share and int(share[1]) != int(share[2]):  # the total is right, the split between boss and adds is not
        low = int(share[1]) < int(share[2])
        say += (f" The split leans {'to the adds' if low else 'to the boss'}: SimC's default list in the top players' "
                f"gear puts {share[1]}% of its damage on the boss, they put {share[2]}%"
                + ("; the plan you play pads the adds, so your own figure puts less on the boss." if
                   getattr(d, "aim_plan", False) and _wanted(d) == "total" else "."))
    return f"<p class='trust {level} rv'><span>How much to trust this:</span> {e(say)}</p>"


CSS = theme.style("briefing")

JS = """<script>
(function(){
var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
var io = 'IntersectionObserver' in window ? new IntersectionObserver(function(es){
  es.forEach(function(en){ if(!en.isIntersecting) return; var el = en.target;
    var sibs = [].slice.call(el.parentNode.children).filter(function(x){ return x.classList.contains('rv'); });
    el.style.transitionDelay = reduce ? '0s' : (Math.max(0, sibs.indexOf(el)) * 60) + 'ms';
    el.classList.add('in'); io.unobserve(el); });
}, {threshold: .1}) : null;
document.querySelectorAll('.rv').forEach(function(el){ io ? io.observe(el) : el.classList.add('in'); });
// never hidden for good: a preview, a print or a slow window shows every block after a moment
setTimeout(function(){ document.querySelectorAll('.rv').forEach(function(el){ el.classList.add('in'); }); }, 1500);
// the timeline: a note tells its story in the margin below
document.querySelectorAll('.tl').forEach(function(tl){
  var m = tl.closest('section').querySelector('.margin');
  function show(n){ tl.querySelectorAll('.note.on').forEach(function(o){ o.classList.remove('on'); });
    n.classList.add('on'); m.querySelector('.m-t').textContent = n.dataset.t;
    m.querySelector('.m-title').textContent = n.dataset.title;
    m.querySelector('.m-text').textContent = ' \\u2014 ' + n.dataset.text; }
  tl.querySelectorAll('.note').forEach(function(n){ n.addEventListener('click', function(){ show(n); });
    n.addEventListener('mouseenter', function(){ show(n); }); n.addEventListener('focus', function(){ show(n); }); });
});
// once the pull starts: ticks fill the ring of the header, remembered on this computer
var boxes = [].slice.call(document.querySelectorAll('.checks input')), ring = document.querySelector('.ready');
var key = 'paf-ready:' + document.title;
try { var saved = JSON.parse(localStorage.getItem(key) || '[]'); boxes.forEach(function(b, i){ b.checked = !!saved[i]; }); } catch (e) {}
function update(bump){ if (!ring) return; var n = boxes.filter(function(b){ return b.checked; }).length;
  ring.querySelector('.r-n').textContent = n + '/' + boxes.length;
  ring.querySelector('.r-fg').style.strokeDashoffset = 119.4 * (1 - n / Math.max(1, boxes.length));
  ring.classList.toggle('done', n === boxes.length && n > 0);
  if (bump && !reduce){ ring.classList.remove('pop'); void ring.offsetWidth; ring.classList.add('pop'); } }
boxes.forEach(function(b){ b.addEventListener('change', function(){
  try { localStorage.setItem(key, JSON.stringify(boxes.map(function(x){ return x.checked; }))); } catch (e) {}
  update(true); }); });
update(false);
})();
</script>"""
