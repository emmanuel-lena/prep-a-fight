"""The overview of a prep sheet as a raid lead's briefing: a few lines that say what the fight is, the changes that
matter for you in order (said plainly when a change barely matters), the fight drawn as an annotated timeline, and
what to keep in mind once the pull starts (a list to tick, which fills the "ready" ring of the header).
Written to read like a person's notes rather than a dashboard: serif headings, sentences, one accent colour.
Everything is readable without JavaScript and without motion.
"""

from __future__ import annotations

import html

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
    waves = [w for w in d.waves if w[1]]
    parts = [f"A {_mmss(dur)} fight" if dur else "This fight"]
    if waves:
        parts.append(f"with {len(waves)} waves of adds" if len(waves) > 1 else "with one wave of adds")
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
        a = d.add_share_spec
        second += (f" The best {e(d.spec)} players keep {1 - a:.0%} of their damage on the boss and put {a:.0%} on the adds."
                  if a >= 0.05 else f" The best {e(d.spec)} players stay on the boss almost the whole time.")
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
            add = ", ".join(dict.fromkeys(best.add[:6]))
            out.append((g, f"Switch to <b>{e(best.build.label)}</b>, the talents of {best.build.count} top players.",
                        f"It takes {e(add)}." if add else "",
                        copy_button(best.build.code, "Copy the talent string") if best.build.code else ""))
        else:
            out.append((0.0, "Keep your talents: no build of the top players does better on this fight.", "", ""))
    want = wanted(d) or "boss"
    plans = [p for p in d.optimized if p.objective in ("boss", "total")]
    plan = next((p for p in plans if p.objective == want and p.gain > 2 * p.error), None)
    if plan is None and wanted(d) is None:
        plan = max((p for p in plans if p.gain > 2 * p.error), key=lambda p: p.gain, default=None)
    if plan is not None:
        rules = [(cd_name(d, k), rule_phrase(d, r.name)) for k, r in plan.choice.items() if r.name != "default"]
        say = "; ".join(f"{n}: {r}" for n, r in rules)
        out.append((plan.gain, f"Play your cooldowns for {e(_goal(plan.objective))} damage.", e(say),
                    copy_button(d.mrt[plan.objective], "Copy the MRT note") if d.mrt.get(plan.objective) else ""))
    elif plans:
        out.append((0.0, "Press your cooldowns as soon as they are ready: holding them gains nothing here.", "", ""))
    if d.gear:
        changes, _, w = d.gear[0]
        if w > 2 * d.gear_error:
            out.append((w, "Swap some gear from your bags.", "; ".join(linkify(c, d.links) for c in changes.split("; ")), ""))
        else:
            out.append((0.0, "Keep the gear you wear: nothing in your bags beats it here.", "", ""))
    return sorted(out, key=lambda m: -m[0])


def moves_html(d) -> str:
    moves = _moves(d)
    if not moves:
        return ""
    items = []
    for i, (gain, say, more, button) in enumerate(moves, 1):
        if gain >= 3:
            tag = f"<span class='gain big'>{gain:+.1f}%</span>"
        elif gain >= 1:
            tag = f"<span class='gain'>{gain:+.1f}%</span>"
        elif gain > 0:
            tag = f"<span class='gain tiny' title='barely matters'>{gain:+.1f}%</span>"
        else:
            tag = "<span class='gain ok'>&#10003;</span>"
        body = (f"<details><summary>{say}</summary><div class='why'>{more}{(' ' + button) if button else ''}</div>"
                f"</details>" if (more or button) else f"<p class='say'>{say}</p>")
        items.append(f"<li class='rv'><span class='n'>{i}</span><div class='mv'>{body}</div>{tag}</li>")
    top = moves[0][0]
    note = ("" if top >= 1 else "<p class='aside rv'>You are already close to what the best players do here: the changes "
                                "below are small.</p>")
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
            above.append((t, "burst", name, f"The boss takes more damage for {life:.0f} s: your big cooldowns hit "
                                             f"harder here.", "k-burst", ""))
        else:
            shade += (f"<div class='adds' style='left:{_pct(t, dur):.2f}%;width:{max(_pct(life, dur), .6):.2f}%'></div>")
            what = f"{count} × {_short(name)}" if count > 1 and name else (_short(name) if name else f"{count} adds")
            above.append((t, f"{count} adds" if count > 1 else _short(name or "add"), what,
                          f"Alive about {life:.0f} s.", "k-adds", ""))
    for f in (d.fight.focus if d.fight is not None else []):
        above.append((f.start, f.name, f"Focus {f.name}", f"{f.support:.0%} of the top players' kills hit {f.name} here.",
                      "k-focus", ""))
    if d.lust is not None:
        above.append((d.lust, "Bloodlust", "Bloodlust", "Bloodlust usually goes out here: line your cooldowns up.",
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
                          f"Press {', '.join(names)} (cooldown plan for {_goal(plan.objective)} damage).", "k-you", ic))
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
<span class='lg k-you'>your cooldowns</span><span class='lg k-def'>defensives</span></div></div></div>
<p class='margin rv' aria-live='polite'><b class='m-t'></b> <span class='m-title'>Point at a note on the timeline</span>
<span class='m-text'>: what comes then, and what you do.</span></p>"""


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


def confidence_pill(d) -> str:
    if not d.validation:
        return ""
    med = d.validation[1]
    gap = abs(med - 1)
    level = "high" if gap <= 0.05 else "medium" if gap <= 0.12 else "low"
    say = {"high": "the sim matches what the best players really did: trust the numbers.",
           "medium": f"the sim is {gap:.0%} off what the best players really did: trust which option wins more than "
                     f"the exact %.",
           "low": f"the sim is {gap:.0%} off what the best players really did: read the numbers as hints."}[level]
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
