"""The simple view of a prep sheet (issue #13): one screen, mostly pictures, for a player who does not read sims.

Three cards (what to change, what to press, what to watch out for), then the fight top to bottom, phase by
phase: the boss's spells on the left, what you do on the right (issue #9).
Everything else is in the details (paf.prep_report's tabs), one click away.
"""

from __future__ import annotations

from html import escape as e

from paf import icons, theme

MAX_CDS = 4  # cooldowns on the "press" card
MAX_WATCH = 3  # lines on the "watch out" card
# game icons for what has none of its own
POTION_ICON = "inv_potion_54"
ADDS_ICON = "inv_misc_groupneedmore"
LUST_ICON = "spell_nature_bloodlust"
MOVE_ICON = "ability_rogue_sprint"


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _fallback(d, name: str) -> str:
    """A generic game icon for what has none of its own: the potion, Bloodlust, the adds."""
    if name.lower() == "potion":
        return POTION_ICON
    if name.lower() == "bloodlust":
        return LUST_ICON
    if name == "Movement":
        return MOVE_ICON
    adds = {w[3] for w in d.waves if w[1]} | {a.name for a in d.actions if a.kind in ("kill", "ignore")}
    return ADDS_ICON if name in adds else ""


def _ic(d, name: str, size: str = "medium", cls: str = "") -> str:
    icon = d.icons.get(name, "") or _fallback(d, name)
    if icon:
        return icons.img(icon, size, cls)
    letter = next((c for c in name if c.isalpha()), "?").upper()  # no game icon: its initial
    return f"<span class='ic-none {cls}' aria-hidden='true'>{e(letter)}</span>"


def _plan(d):
    """The cooldown plan of the sheet: the player's (or the raid's) objective, else the best one worth it."""
    from paf.prep_report import wanted

    want = wanted(d) or "boss"
    plans = [p for p in d.optimized if p.objective in ("boss", "total")]
    plan = next((p for p in plans if p.objective == want), None)
    if plan is None or plan.gain <= 2 * plan.error:
        better = max((p for p in plans if p.gain > 2 * p.error), key=lambda p: p.gain, default=None)
        plan = better or plan
    return plan


def _presses(d) -> list[tuple[float, str]]:
    """(time, cooldown name) of every press of the plan."""
    plan = _plan(d)
    if plan is None or d.fight is None:
        return []
    from paf.optimize import plan_moments

    return [(t, n) for t, names in plan_moments(plan, d.fight, d.cd_names) for n in dict.fromkeys(names)]


def _size(gain: float) -> str:
    return "big" if gain >= 3 else "some" if gain >= 1 else "tiny"


SIZE_WORDS = {"big": "a big gain", "some": "a small gain", "tiny": "barely matters"}


# --- the three cards -----------------------------------------------------------------------------------------------

def _talent(d, t) -> str:
    """A talent with its icon, linked to Wowhead (its tooltip on hover); an empty slot when there is none."""
    if not t:
        return "<span class='tal none'>&mdash;</span>"
    name, sid = t
    pic = icons.img(d.icons.get(name, ""), "medium", "tal-ic") if d.icons.get(name) else "<span class='tal-ic none'></span>"
    if not sid:
        return f"<span class='tal'>{pic}<span>{e(name)}</span></span>"
    from paf.wowhead import url

    href, data = url(f"spell={sid}")
    return (f"<a class='tal' href='{e(href)}' data-wowhead='{e(data)}' data-wh-icon-added='true' target='_blank' "
            f"rel='noopener'>{pic}<span>{e(name)}</span></a>")


def swaps_html(d, swaps: list) -> str:
    """Your talent -> the build's talent, one line per point moved."""
    if not swaps:
        return ""
    lines = "".join(f"<li class='sw'>{_talent(d, a)}<span class='arr' aria-label='becomes'>&rarr;</span>{_talent(d, b)}</li>"
                    for a, b in swaps)
    return f"<li class='sw-list'><ul class='swaps'>{lines}</ul></li>"


def change_card(d) -> str:
    from paf.prep_report import best_build, copy_button, linkify

    rows = []
    best = best_build(d)
    if d.talents and best is not None:
        g = best.per_fight.get(d.talents.fights[0], (0.0, None))[0]
        if g > 2 * d.talents.error:
            spec_ic = icons.img(icons.CLASS_ICON.format(cls=d.class_name.lower()), "medium") if d.class_name else ""
            button = copy_button(best.build.code, "Copy the talents") if best.build.code else ""
            rows.append(f"<li>{spec_ic}<div><b>Change your talents</b><span class='sz {_size(g)}'>"
                        f"{SIZE_WORDS[_size(g)]}</span></div></li>{swaps_html(d, getattr(best, 'swaps', []))}"
                        f"<li class='sw-copy'>{button}</li>")
    if d.gear and d.gear[0][2] > 2 * d.gear_error:
        changes, _, w = d.gear[0]
        items = [c.split(": ", 1)[-1].rsplit(" (", 1)[0] for c in changes.split("; ")]
        pics = "".join(_ic(d, it) for it in items[:3])
        rows.append(f"<li><span class='pics'>{pics}</span><div><b>Swap some gear</b><span class='sz {_size(w)}'>"
                    f"{SIZE_WORDS[_size(w)]}</span><span class='what'>{'; '.join(linkify(c, d.links) for c in changes.split('; '))}"
                    f"</span></div></li>")
    if getattr(d, "imported", False):  # no bags: the best gear and the loot need the /simc export
        rows.append("<li><span class='ok bad' aria-hidden='true'>!</span><div><b>Paste your /simc export</b>"
                    "<span class='what'>Your character was read from a log, without your bags: with /simc the "
                    "prep finds the best gear in them and what this boss drops for you.</span></div></li>")
    if not rows:
        rows.append("<li><span class='ok' aria-hidden='true'>&#10003;</span><div><b>Nothing to change</b>"
                    "<span class='what'>Your talents and gear are already right for this boss.</span></div></li>")
    return f"<article class='card s-change'><h2>Before the pull</h2><ul>{''.join(rows)}</ul></article>"


def _pressed(d) -> tuple[list[str], dict[str, list[float]], bool]:
    """The cooldowns worth showing (at most MAX_CDS), when each is pressed, and whether the plan holds some."""
    plan = _plan(d)
    held = {d.cd_names.get(k, k) for k, r in plan.choice.items() if r.name != "default"} if plan else set()
    order: dict[str, list[float]] = {}
    for t, n in _presses(d):
        order.setdefault(n, []).append(t)
    major = {d.cd_names.get(k, k) for k in plan.choice} if plan else set()  # the cooldowns the plan weighs
    from paf.optimize import OPENER

    def rank(n: str) -> tuple:
        rotation = all(t <= OPENER for t in order[n]) and n not in held  # only its opener is worth a reminder
        # the cooldowns the plan holds first (they are the point), then its big ones, the rotational ones last
        return (n not in held, n not in major, rotation, len(order[n]))

    names = sorted(order, key=rank)[:MAX_CDS]
    return names, order, bool(held)


def press_card(d) -> str:
    names, order, held = _pressed(d)
    if not names:
        return ("<article class='card s-press'><h2>Your cooldowns</h2><p class='what'>Press them as soon as they are "
                "ready.</p></article>")
    rows = "".join(f"<li>{_ic(d, n)}<div><b>{e(n)}</b><span class='times'>"
                   + "".join(f"<time>{'precast' if t < 0.5 and n in d.precast else _mmss(t)}</time>" for t in order[n][:5])
                   + ("<span class='more'>&hellip;</span>" if len(order[n]) > 5 else "") + "</span></div></li>"
                   for n in names)
    how = "Hold them for these moments." if held else "Press them as soon as they are ready."
    return (f"<article class='card s-press'><h2>Your cooldowns</h2><p class='what'>{how}</p><ul>{rows}</ul>"
            f"{copy_menu(d)}</article>")


def copy_menu(d) -> str:
    """One button that asks which note to copy: the MRT note or the NSRT reminders of the sheet's plan."""
    plan = _plan(d)
    want = plan.objective if plan is not None else "boss"
    notes = [(d.mrt.get(want) or next(iter(d.mrt.values()), ""), "MRT note", "Method Raid Tools: paste it in your note"),
             (d.nsrt.get(want) or next(iter(d.nsrt.values()), ""), "NSRT reminders",
              "Northern Sky Raid Tools: your personal reminders")]
    choices = "".join(f"<button type='button' data-copy='{e(text)}'><b>{e(label)}</b><span>{e(why)}</span></button>"
                      for text, label, why in notes if text)
    if not choices:
        return ""
    return (f"<details class='copy-menu'><summary class='btn ghost'>Copy the note</summary>"
            f"<div class='menu' role='menu'>{choices}</div></details>")


def _watch(d) -> list[tuple[str, str]]:
    """(icon name, sentence) of what to watch out for: the top players' habits on this boss, then defensives."""
    def acts(kind: str, say: str) -> list[tuple[str, str]]:
        return [(a.name, say.format(a.name)) for a in d.actions if a.kind == kind
                and not (kind == "interrupt" and not a.text.startswith("Interrupt"))]

    defs = []
    for m in (d.defensives.moments if d.defensives else []):
        if m.spells and m.boss_ability:  # the big hits first: a defensive there is what saves a casual player
            defs.append((m.spells[0][0], f"Defensive: {m.spells[0][0]} ({m.boss_ability})"))
    # what kills a raid first: adds to kill, kicks, one defensive, then the mechanics
    return (acts("kill", "Kill the {}") + acts("interrupt", "Interrupt {}") + defs[:1] + acts("contact", "Soak {}")
            + acts("mechanic", "Careful with {}") + defs[1:])


def watch_card(d) -> str:
    rows = "".join(f"<li>{_ic(d, ic)}<div><b>{e(say)}</b></div></li>" for ic, say in _watch(d)[:MAX_WATCH])
    if not rows:
        return ""
    return f"<article class='card s-watch'><h2>Watch out</h2><ul>{rows}</ul></article>"


def move_card(d) -> str:
    """Moving or standing still: the strategy's movement windows, what a second of movement costs, how the top
    players keep casting while they move."""
    m = d.movement
    if m is None or not (m.windows or m.cost_10s):
        return ""
    lines = []
    if m.windows:
        lines.append(("Movement", f"Move when the strategy says so: {len(m.windows)} moments where most top players "
                                 f"move ({m.covered:.0f} s in all), marked in the fight below.", ""))
    if m.cost_10s:
        lines.append(("", f"The rest of the time, stand still and cast: 10 s of movement without casting costs you "
                          f"about {m.cost_10s:.1f}% of your DPS.", "cost"))
    spells = {}
    for w in m.windows:
        for s, share in w.spells:
            spells[s] = max(spells.get(s, 0.0), share)
    if m.cost_10s and m.scale < 0.5:
        lost = m.cost_10s * m.scale
        how = f", {', '.join(list(spells)[:2])}" if spells else ""
        lines.append((next(iter(spells), ""), f"The top players lose only about {lost:.1f}% per 10 s: they keep casting "
                                              f"while they move (instant spells{how}).", ""))
    elif spells:
        s = next(iter(spells))
        lines.append((s, f"For these moments the top players use {s}.", ""))
    warn = "<span class='ok bad' aria-hidden='true'>!</span>"
    rows = "".join(f"<li>{_ic(d, ic) if ic else warn}<div><b>{e(say)}</b></div></li>" for ic, say, _ in lines)
    return f"<article class='card s-move'><h2>Moving or standing still</h2><ul>{rows}</ul></article>"


CAST_GAP = 0.03  # casting this much less than the top players is worth saying
MOVE_GAP = 0.08  # moving this much more than them in a phase is worth saying


def _bars(label: str, you: float, tops: float | None, good_high: bool) -> str:
    worse = tops is not None and ((tops - you) if good_high else (you - tops)) >= (CAST_GAP if good_high else MOVE_GAP)
    top = (f"<div class='bar tops'><span style='width:{tops * 100:.0f}%'></span><em>Top players {tops:.0%}</em></div>"
           if tops is not None else "")
    return (f"<div class='cmp'><b>{e(label)}</b><div class='bar you{' worse' if worse else ''}'>"
            f"<span style='width:{you * 100:.0f}%'></span><em>You {you:.0%}</em></div>{top}</div>")


def review_card(d) -> str:
    """Your own pull next to the top players': do you keep casting, do you move more than they do."""
    r = d.review
    if r is None:
        return ""
    says = []
    dur = d.duration or 0
    if r.tops_active is not None and r.tops_active - r.active >= CAST_GAP:
        worst = max(r.phases, key=lambda p: (p.tops_active or 0) - p.active, default=None)
        where = f", above all in {worst.name}" if worst and (worst.tops_active or 0) - worst.active >= CAST_GAP else ""
        says.append(f"You cast {(r.tops_active - r.active) * dur:.0f} s less than the top players over the fight{where}: "
                    f"always have a spell going, even while moving (instant spells).")
    elif r.tops_active is not None:
        says.append("You keep casting like the top players do.")
    moving = [p for p in r.phases if p.tops_moving is not None and p.moving - p.tops_moving >= MOVE_GAP]
    if moving:
        p = max(moving, key=lambda p: p.moving - p.tops_moving)
        says.append(f"You move more than them in {p.name} ({p.moving:.0%} of the phase, top players {p.tops_moving:.0%}): "
                    f"outside the strategy's moments, stand still.")
    elif r.tops_moving is not None:
        says.append("You do not move more than the top players.")
    gaps = "".join(f"<time>{_mmss(a)} &middot; {b:.0f} s</time>" for a, b in r.gaps)
    pauses = (f"<p class='what pauses'>Your longest pauses without casting:</p><div class='times'>{gaps}</div>"
              if gaps else "")
    return (f"<article class='card s-review'><h2>Your last pull</h2><p class='what'>{e(r.fight)}, from your raid's "
            f"log.</p><div class='cmps'>{_bars('Casting', r.active, r.tops_active, True)}"
            f"{_bars('Moving', r.moving, r.tops_moving, False)}</div>"
            + "".join(f"<p class='say'>{e(s)}</p>" for s in says) + pauses + "</article>")


# --- the whole fight, top to bottom (issue #9) ----------------------------------------------------------------------

ROW_GAP = 3.0  # seconds; events this close share a row
PULL = -5.0  # the time of the row "before the pull" (precasts)


def _item(d, name: str, label: str, before: str = "") -> str:
    """An icon and its label; `before` is a word of the app in its own element, so that a game name stays a whole
    text (the translation of a one-word name only applies to a whole text)."""
    pic = _ic(d, name, "medium", "vi")
    pre = f"<em class='pre'>{e(before)}</em> " if before else ""
    return f"<span class='it'>{pic}<span>{pre}<span>{e(label)}</span></span></span>"


def _do(label: str) -> str:
    return f"<span class='it do'>{e(label)}</span>"


def _events(d) -> list[tuple[float, str, str]]:
    """(time, side 'l' or 'r', item html): on the left what the boss does, on the right what you do."""
    out = []
    todo = {"kill": "Kill them", "interrupt": "Interrupt", "contact": "Soak it"}
    act = {a.name: todo[a.kind] for a in d.actions if a.kind in todo
           and not (a.kind == "interrupt" and not a.text.startswith("Interrupt"))}
    for name, times in d.boss_casts:
        for t in times:
            out.append((t, "l", _item(d, name, name)))
            if name in act:
                out.append((t, "r", _do(act[name])))
    for t, count, _life, name in d.waves:
        if not count:
            continue
        out.append((t, "l", _item(d, name, f"{count} × {name}" if count > 1 else name)))
        if name in act:
            out.append((t, "r", _do(act[name])))
    for f in (d.fight.focus if d.fight is not None else []):
        out.append((f.start, "r", _item(d, f.name, f"Hit {f.name}")))
    if d.lust is not None:
        out.append((d.lust, "l", _item(d, "Bloodlust", "Bloodlust")))
    names, order, _ = _pressed(d)
    for n in names:
        for t in order[n]:
            if t < 0.5 and n in d.precast:  # cast before the pull: a row of its own, on top
                out.append((PULL, "r", _item(d, n, n, "Before the pull:")))
            else:
                out.append((t, "r", _item(d, n, n)))
    for m in (d.defensives.moments if d.defensives else []):
        if m.spells:
            out.append((m.time, "r", _item(d, m.spells[0][0], f"Defensive: {m.spells[0][0]}")))
    for w in (d.movement.windows if d.movement else []):  # the strategy makes everyone move: so do you
        out.append((w.start, "l", _item(d, "Movement", f"Everyone moves ({w.duration:.0f} s)")))
        out.append((w.start, "r", _do("Move: it is the strategy")))
        for s, _share in w.spells[:1]:
            out.append((w.start, "r", _item(d, s, s)))
    return sorted(out, key=lambda x: x[0])


def _rows(events: list[tuple[float, str, str]]) -> list[tuple[float, list[str], list[str]]]:
    """Events close in time share a row: (time, left items, right items)."""
    rows: list[tuple[float, list[str], list[str]]] = []
    for t, side, item in events:
        if not rows or t - rows[-1][0] > ROW_GAP:
            rows.append((t, [], []))
        (rows[-1][1] if side == "l" else rows[-1][2]).append(item)
    return rows


def fight_html(d) -> str:
    dur = d.duration or (d.fight.duration if d.fight else 0)
    rows = _rows(_events(d))
    if not dur or not rows:
        return ""
    phases = sorted(d.phases, key=lambda p: p[1]) or [("The fight", 0.0)]
    blocks = []
    for i, (name, start) in enumerate(phases):
        end = phases[i + 1][1] if i + 1 < len(phases) else dur
        mine = [r for r in rows if (r[0] >= start - 0.5 or i == 0) and r[0] < end]
        if not mine:
            continue
        lines = "".join(f"<li><div class='l'>{''.join(left)}</div><time>{'Pull' if t == PULL else _mmss(t)}</time>"
                        f"<div class='r'>{''.join(right)}</div></li>" for t, left, right in mine)
        blocks.append(f"<details class='vp'{' open' if not blocks else ''}><summary><span class='vp-name'>{e(name)}</span>"
                      f"<span class='vp-time'>{_mmss(start)} &ndash; {_mmss(end)}</span></summary>"
                      f"<ol class='vt'>{lines}</ol></details>")
    return (f"<article class='card s-fight'><h2>The fight, step by step</h2>"
            f"<p class='to-minutes'><a class='btn' href='#minutes'>Minute by minute &rarr;</a></p>"
            f"<p class='what'>Left: what the boss does. Right: what you do. Open a phase to see it.</p>"
            f"<div class='vt-head' aria-hidden='true'><span>The boss</span><span></span><span>You</span></div>"
            f"{''.join(blocks)}</article>")


def minutes_html(d) -> str:
    """The fight one minute per screen (issue #9): the boss's spells on the left, what you press on the right, the minute
    and its phase on top; scrolling snaps to the next minute, a mini-map of the whole fight jumps to one, the arrow and
    page keys move by a minute; with reduced motion, plain sections."""
    dur = d.duration or (d.fight.duration if d.fight else 0)
    rows = _rows(_events(d))
    if not dur or not rows:
        return ""
    phases = sorted(d.phases, key=lambda p: p[1]) or [("The fight", 0.0)]
    count = int(dur // 60) + 1
    sections, minimap = [], []
    for m in range(count):
        start, end = m * 60, min(dur, (m + 1) * 60)
        mine = [r for r in rows if (r[0] == PULL and m == 0) or (r[0] != PULL and start <= r[0] < end)]
        phase = next((n for n, t in reversed(phases) if t <= start + 1), phases[0][0])
        idx = next((i for i, (n, _t) in enumerate(phases) if n == phase), 0)
        lines = "".join(f"<li><div class='l'>{''.join(left)}</div><time>{'Pull' if t == PULL else _mmss(t)}</time>"
                        f"<div class='r'>{''.join(right)}</div></li>" for t, left, right in mine)
        body = (f"<div class='vt-head' aria-hidden='true'><span>The boss</span><span></span><span>You</span></div>"
                f"<ol class='vt'>{lines}</ol>" if lines else
                "<p class='mn-quiet'>A quiet minute: keep up your rotation.</p>")
        sections.append(f"<section class='mn' id='m{m}' data-m='{m}'><div class='mn-in'><header class='mn-head'>"
                        f"<b>{_mmss(start)} &ndash; {_mmss(end)}</b><span>{e(phase)}</span></header>{body}</div></section>")
        minimap.append(f"<a href='#m{m}' class='ph{idx % 4}' data-m='{m}' title='{_mmss(start)} {e(phase)}'>"
                       f"<span>{m}</span><i style='height:{min(100, len(mine) * 18)}%'></i></a>")
    return (f"<div class='mins-wrap'><nav class='mmap' aria-label='The fight, minute by minute'>{''.join(minimap)}</nav>"
            f"<div class='mins' tabindex='0'>{''.join(sections)}</div></div>")


def simple_html(d) -> str:
    cards = change_card(d) + press_card(d) + watch_card(d) + move_card(d) + review_card(d)
    return (f"<div class='simple'><div class='cards'>{cards}</div>{fight_html(d)}"
            f"<p class='to-detail'><a class='btn ghost' href='#overview'>See all the details &rarr;</a></p></div>")


CSS = theme.style("simple")

JS = """<script>
(function(){var box=document.querySelector('.mins');if(!box)return;var secs=[].slice.call(box.querySelectorAll('.mn'));
var links=[].slice.call(document.querySelectorAll('.mmap a'));
function mark(m){secs.forEach(function(x){x.classList.toggle('on',x.dataset.m===m)});
links.forEach(function(a){a.classList.toggle('on',a.dataset.m===m)})}
if('IntersectionObserver' in window){var io=new IntersectionObserver(function(es){es.forEach(function(en){
if(en.isIntersecting&&en.intersectionRatio>0.55)mark(en.target.dataset.m)})},{root:box,threshold:[0.55]});
secs.forEach(function(x){io.observe(x)})}else{secs.forEach(function(x){x.classList.add('on')})}
links.forEach(function(a){a.addEventListener('click',function(ev){ev.preventDefault();var t=document.getElementById('m'+a.dataset.m);
if(t)box.scrollTo({top:t.offsetTop-box.offsetTop,behavior:'smooth'})})});
box.addEventListener('keydown',function(ev){var cur=secs.findIndex(function(x){return x.classList.contains('on')});
var n=({ArrowDown:1,PageDown:1,ArrowUp:-1,PageUp:-1})[ev.key];if(!n)return;ev.preventDefault();
var t=secs[Math.max(0,Math.min(secs.length-1,(cur<0?0:cur)+n))];box.scrollTo({top:t.offsetTop-box.offsetTop,behavior:'smooth'})});
if(secs[0])mark('0')})();
(function(){
// the note menu: closes after a copy, or on a click elsewhere
document.addEventListener('click', function(ev){
  document.querySelectorAll('.copy-menu[open]').forEach(function(m){
    if (!m.contains(ev.target)) { m.open = false; return; }
    if (ev.target.closest('[data-copy]')) setTimeout(function(){ m.open = false; }, 900);
  });
});
})();
</script>"""
