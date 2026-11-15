"""The top of Dig deeper as a raid lead's briefing: a few lines that say what the fight is, what to aim for and how
much to trust it; and the spec tiles and the fight's demands of What to change.
Written to read like a person's notes rather than a dashboard: serif headings, sentences, one accent colour.
Everything is readable without JavaScript and without motion.
"""

from __future__ import annotations

import html
import re

from paf import theme

e = html.escape
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;'
         '0,9..144,600;1,9..144,400&display=swap">')


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


# --- the few lines on top --------------------------------------------------------------------------------------------

def lede_html(d) -> str:
    dur = d.duration or 0
    units = {w.name for w in (d.fight.add_waves if getattr(d, "fight", None) is not None else []) if not w.scalable}
    waves = [w for w in d.waves if w[1] and not any(u.startswith(w[3]) or w[3].startswith(u) for u in units)]
    parts = [f"A {_mmss(dur)} fight" if dur else "This fight"]
    if waves:  # the add waves; a boss unit played as a wave (an Echo) is not one of them
        n = len({round(w[0]) for w in waves})  # a wave is a moment: two types at one Imbibe are one (a review: 6)
        bosses = sorted({w[3] for w in d.waves if w[1] and w not in waves})  # a boss unit said, not left out
        parts.append((f"with {n} waves of adds" if n > 1 else "with one wave of adds")  # (fresh DPS review: "2 waves"
                     + (f" and {' and '.join(e(re.sub(r' *[(].*', '', b)) for b in bosses)}" if bosses else ""))  # beside 3)
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
    others = [r for r in rows if r is not mine]
    own = bool(s.get("now")) and all(r.get("own") for r in others)  # your items in each spec, against you as you
    # are: the switch you can make (issue #35, the owner's call); else the top players' set on both

    def value(r: dict) -> float:
        return r["own"] if own else r["sim"]
    for r in sorted(others, key=lambda r: -value(r)):
        gap = 100 * (value(r) / (s["now"] if own else mine["sim"]) - 1)
        noise = 2 * (((r.get("own_error") if own else r.get("error")) or 0) ** 2
                     + ((s.get("now_error") if own else mine.get("error")) or 0) ** 2) ** 0.5
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
    by_label = {r.get("label"): r for r in s.get("rows") or []}
    mine_row = by_label.get(mine_label) or {}
    own = bool(s.get("now")) and all(r.get("own") for r in s.get("rows") or [] if r is not mine_row and r.get("sim"))

    def how(name: str) -> str:  # its tile's hover: the swaps from what you wear, a slot none of yours fits, and
        r = by_label.get(name) or {}  # the top players' set as the ceiling (issue #35)
        if not own or r is mine_row or not r.get("own"):
            return ""
        bits = []
        if r.get("own_changes"):
            bits.append("your best set: " + "; ".join(r["own_changes"]))
        if r.get("own_missing"):
            bits.append("none of your items fits: " + ", ".join(x.replace("_", " ") for x in r["own_missing"]))
        if r.get("sim") and mine_row.get("sim"):
            bits.append(f"in the top players' gear at {s.get('ilvl', 334)}: {100 * (r['sim'] / mine_row['sim'] - 1):+.0f}%")
        return f" title='{e('. '.join(bits))}'" if bits else ""
    tiles = "".join(
        f"<div class='spt {kind}'{how(name)}><span class='spt-n'>{e(name)}</span><span class='spt-v'>"
        f"{'your spec' if gap is None else 'same' if kind == 'same' else f'{gap:+.0f}%'}{short(name)}</span></div>"
        for name, gap, kind in gaps)
    failed = " ".join(s.get("notes") or [])

    def why(r) -> str:  # said, never silently dropped, with its reason
        return "SimC failed on it" if f"{r.get('spec')} could not be simmed" in failed else "no build found"
    tiles += "".join(f"<div class='spt low'><span class='spt-n'>{e(r.get('label', r.get('spec', '')))}</span>"
                     f"<span class='spt-v'>not simmed: {why(r)}</span></div>"
                     for r in s.get("rows") or [] if not r.get("sim"))
    return (f"<div class='specs rv'><p class='specs-head'><b>We simmed your character in each damage spec of your class"
            f"</b> <span class='muted'>for {e(spec_role(s))}, on this fight{', with your items' if own else ''}</span></p>"
            f"<div class='spt-row'>{tiles}</div>"
            + _short_note(missing, short_specs, mine_label) + "</div>")


DEMAND_GAP = 3.0  # % a spec must gain in a window to be said ahead there (a window is a few seconds of the sims)
DEMAND_GLYPH = {"shield": "&#128737;", "adds": "&#9876;", "amp": "&#9650;", "immune": "&#8856;"}


def _title(w: dict) -> str:
    """A demand's name: an immunity is its unit to kill ("Echo of Jawae", Tether of Awakening on hover)."""
    return w["unit"] if w["kind"] == "immune" and w.get("unit") else w["label"]


def demands_html(d) -> str:
    """What the fight demands (paf.demands; the owner, 2026-11-12: the spec is chosen on them): its DPS checks, add
    bursts and amps as a strip, and, with other specs ticked, each spec's damage in each of them against yours."""
    dm = getattr(d, "demands", None)
    if not dm or not dm.get("windows"):
        return ""
    wins = dm["windows"]

    def head(w: dict) -> str:
        spans = w.get("spans") or []
        times = ", ".join(_mmss(a) for a, _b in spans[:6]) + ("…" if len(spans) > 6 else "")
        n = f" &times;{len(spans)}" if len(spans) > 1 else ""
        on = f" on {w['unit']}" if w.get("unit") else ""
        when = times or "not seen in the top kills' logs"
        hover = ". ".join(x for x in (f"{w['label']}{on}: {when}", w.get("detail") or "",
                                      "Blizzard's own warning: high" if w.get("severity") == 2 else "") if x)
        return (f"<span class='dm-w {w['kind']}{'' if spans else ' off'}{' high' if w.get('severity') == 2 else ''}'"
                f" title='{e(hover)}'>{DEMAND_GLYPH.get(w['kind'], '')} {e(_title(w))}{n}</span>")
    wins = sorted(wins, key=lambda w: (not w.get("spans"), -(w.get("severity") or 0)))  # placed, most severe first
    dmg = dm.get("damage") or {}
    mine = getattr(d, "specs", None) and d.specs.get("mine")
    grid = ""
    if mine in dmg and len(dmg) > 1:
        from paf.specgear import spec_label

        cols = [("all", "Whole fight")] + [(w["label"], _title(w)) for w in wins if w["label"] in dmg[mine]]
        best = {k: max(dmg, key=lambda sp: dmg[sp].get(k, 0)) for k, _ in cols}

        def cell(sp: str, k: str) -> str:
            if sp == mine:
                return ("<td class='dm-me dm-best'>your spec, best</td>" if best[k] == sp else
                        "<td class='dm-me'>your spec</td>")
            base = dmg[mine].get(k) or 0
            gap = 100 * (dmg[sp].get(k, 0) / base - 1) if base else 0.0
            kind = "pos" if gap >= DEMAND_GAP else "neg" if gap <= -DEMAND_GAP else ""
            return f"<td class='{kind}{' dm-best' if best[k] == sp else ''}'>{gap:+.0f}%</td>"
        rows = "".join(f"<tr><th>{e(spec_label(sp))}</th>{''.join(cell(sp, k) for k, _ in cols)}</tr>"
                       for sp in sorted(dmg, key=lambda x: x != mine))
        grid = (f"<table class='dm-grid'><thead><tr><th></th>{''.join(f'<th>{e(n)}</th>' for _, n in cols)}</tr>"
                f"</thead><tbody>{rows}</tbody></table><p class='small muted'>Your damage in each spec, in the top "
                f"players' gear, during each window: a spec ahead by {DEMAND_GAP:g}% or more is green.</p>")
    return (f"<div class='demands rv'><p class='specs-head'><b>What this fight demands</b></p>"
            f"<div class='dm-row'>{''.join(head(w) for w in wins)}</div>{grid}</div>")


def confidence_pill(d) -> str:
    if not d.validation:
        return ""
    med = d.validation[1]
    gap = abs(med - 1)
    level = "high" if gap <= 0.05 else "medium" if gap <= 0.12 else "low"
    say = {"high": "trust the numbers"
                   + (", the boss figure and the gaps more than the total (above)." if overshoot(d) else "."),
           "medium": "trust which option wins more than the exact %.",
           "low": "read the numbers as hints."}[level]  # the validation and the boss split: in Notes, once
    share = next((m for n in d.notes if (m := re.search(r"puts (\d+)% of (?:its|your) damage on the boss vs (\d+)%", n))),
                 None)
    if share and int(share[1]) != int(share[2]):  # the total is right, the split between boss and adds is not
        say += f" The sim leans {'to the adds' if int(share[1]) < int(share[2]) else 'to the boss'} (see Notes)."
    if getattr(d, "sim_boss_dps", None) and d.sim_dps and d.waves:  # your own split, said nowhere else
        say += f" Your character puts {d.sim_boss_dps / d.sim_dps:.0%} of its damage on the boss in the sim."
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
})();
</script>"""
