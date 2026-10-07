"""The simple view of a prep sheet (issue #13): one screen, mostly pictures, for a player who does not read sims.

Three cards (what to change, what to press, what to watch out for) and one bar of the whole fight with game icons.
Everything else is in the details (paf.prep_report's tabs), one click away.
"""

from __future__ import annotations

from html import escape as e

from paf import icons

MAX_CDS = 3  # cooldowns on the "press" card
MAX_WATCH = 3  # lines on the "watch out" card
ICON_PX = 30  # a marker on the fight bar
BAR_PX = 900  # the bar's width on a desktop (markers are placed in rows for it)


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _pct(t: float, dur: float) -> float:
    return max(0.0, min(100.0, 100 * t / dur)) if dur else 0.0


def _ic(d, name: str, size: str = "medium", cls: str = "") -> str:
    icon = d.icons.get(name, "")
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
                        f"{SIZE_WORDS[_size(g)]}</span>{button}</div></li>")
    if d.gear and d.gear[0][2] > 2 * d.gear_error:
        changes, _, w = d.gear[0]
        items = [c.split(": ", 1)[-1].rsplit(" (", 1)[0] for c in changes.split("; ")]
        pics = "".join(_ic(d, it) for it in items[:3])
        rows.append(f"<li><span class='pics'>{pics}</span><div><b>Swap some gear</b><span class='sz {_size(w)}'>"
                    f"{SIZE_WORDS[_size(w)]}</span><span class='what'>{'; '.join(linkify(c, d.links) for c in changes.split('; '))}"
                    f"</span></div></li>")
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
    # the cooldowns the plan moves first (they are the point), then the others by how rarely they come back
    names = sorted(order, key=lambda n: (n not in held, len(order[n])))[:MAX_CDS]
    return names, order, bool(held)


def press_card(d) -> str:
    names, order, held = _pressed(d)
    if not names:
        return ("<article class='card s-press'><h2>Your cooldowns</h2><p class='what'>Press them as soon as they are "
                "ready.</p></article>")
    rows = "".join(f"<li>{_ic(d, n)}<div><b>{e(n)}</b><span class='times'>"
                   + "".join(f"<time>{_mmss(t)}</time>" for t in order[n][:5])
                   + ("<span class='more'>&hellip;</span>" if len(order[n]) > 5 else "") + "</span></div></li>"
                   for n in names)
    how = "Hold them for these moments." if held else "Press them as soon as they are ready."
    return f"<article class='card s-press'><h2>Your cooldowns</h2><p class='what'>{how}</p><ul>{rows}</ul></article>"


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


# --- the whole fight, one bar ----------------------------------------------------------------------------------------

def _rows(times: list[float], dur: float) -> list[int]:
    """A row per marker so that icons never overlap."""
    w = (ICON_PX + 4) / BAR_PX * 100
    last: list[float] = []
    out = []
    for t in times:
        x = _pct(t, dur)
        row = next((r for r, end in enumerate(last) if x >= end), None)
        if row is None:
            last.append(0.0)
            row = len(last) - 1
        last[row] = x + w
        out.append(row)
    return out


def _markers(d, events: list[tuple[float, str, str]], side: str, dur: float) -> tuple[str, int]:
    events = sorted(events)
    rows = _rows([t for t, _, _ in events], dur)
    html = "".join(f"<button class='mk {side}' style='left:{_pct(t, dur):.2f}%;--r:{r}' data-t='{_mmss(t)}' "
                   f"data-text='{e(say)}' aria-label='{_mmss(t)} {e(say)}'>{_ic(d, name, 'medium')}</button>"
                   for (t, name, say), r in zip(events, rows, strict=True))
    return html, (max(rows) + 1 if rows else 0)


def fight_bar(d) -> str:
    dur = d.duration or (d.fight.duration if d.fight else 0)
    if not dur:
        return ""
    phases = sorted(d.phases, key=lambda p: p[1])
    segs = "".join(f"<div class='seg p{i % 3}' style='left:{_pct(s, dur):.2f}%;width:"
                   f"{_pct((phases[i + 1][1] if i + 1 < len(phases) else dur) - s, dur):.2f}%' title='{e(n)}'>"
                   f"<span>{e(n)}</span></div>" for i, (n, s) in enumerate(phases)) or "<div class='seg p0' style='left:0;width:100%'></div>"
    names, order, _ = _pressed(d)
    mine = [(t, n, f"press {n}") for n in names for t in order[n]]
    boss = []
    for m in (d.defensives.moments if d.defensives else []):
        if m.spells:
            boss.append((m.time, m.spells[0][0], f"Defensive: {m.spells[0][0]}"
                         + (f" ({m.boss_ability})" if m.boss_ability else "")))
    for t, count, _life, name in d.waves:
        if count:
            boss.append((t, name, f"{count} × {name}" if count > 1 else name))
    for f in (d.fight.focus if d.fight is not None else []):
        boss.append((f.start, f.name, f"hit {f.name}"))
    up, n_up = _markers(d, mine, "up", dur)
    down, n_down = _markers(d, boss, "down", dur)
    lust = (f"<div class='lust' style='left:{_pct(d.lust, dur):.2f}%' title='Bloodlust'></div>"
            if d.lust is not None else "")
    ticks = "".join(f"<span style='left:{_pct(t, dur):.2f}%'>{_mmss(t)}</span>" for t in range(0, int(dur) + 1, 60))
    return f"""<article class='card s-bar'><h2>The fight, start to finish</h2>
<p class='what'>On top: what you press. Below: what the boss does. Touch an icon.</p>
<div class='bar-scroll'><div class='bar' style='--up:{n_up};--down:{n_down}'>{up}
<div class='axis'>{segs}{lust}</div><div class='ticks'>{ticks}</div>{down}</div></div>
<p class='say' aria-live='polite'>&nbsp;</p></article>"""


def simple_html(d) -> str:
    cards = change_card(d) + press_card(d) + watch_card(d)
    return (f"<div class='simple'><div class='cards'>{cards}</div>{fight_bar(d)}"
            f"<p class='to-detail'><a class='btn' href='#overview'>See all the details &rarr;</a></p></div>")


CSS = """
/* the simple view (paf.simple) */
body.simple-on .tabs{display:none}
.simple{max-width:980px;font-size:17px}
.simple .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.simple .card{margin:0;padding:18px 20px}
.simple h2{font:600 21px/1.2 'Fraunces',Georgia,serif;text-transform:none;letter-spacing:0;color:var(--fg);margin:0 0 12px}
.simple ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:14px}
.simple li{display:flex;gap:12px;align-items:center}
.simple li>div{display:flex;flex-direction:column;gap:3px;min-width:0}
.simple li b{font-size:17px;font-weight:600}
.simple img,.simple .ic-none{width:40px;height:40px;border-radius:6px;flex:none;margin:0}
.simple .ic-none{display:inline-grid;place-items:center;background:var(--surface-2);border:1px solid var(--line);
  font:600 16px var(--font-data);color:var(--muted)}
.simple .pics{display:flex;gap:4px;flex:none}
.simple .pics img{width:32px;height:32px}
.simple .ok{width:40px;height:40px;flex:none;display:grid;place-items:center;border-radius:50%;background:var(--pos);
  color:#fff;font-size:22px}
.simple .what{color:var(--muted);font-size:15px;line-height:1.45;margin:0}
.simple .sz{font-size:14px;font-weight:600} .simple .sz.big{color:var(--pos)} .simple .sz.some{color:var(--fg)}
.simple .sz.tiny{color:var(--muted)}
.simple .times{display:flex;flex-wrap:wrap;gap:6px}
.simple time{font:600 15px var(--font-data);padding:2px 8px;border-radius:999px;background:var(--surface-2);
  border:1px solid var(--line)}
.simple .s-press .what{margin:-6px 0 12px}
.simple .s-bar{margin-top:16px}
.simple .s-bar .what{margin:-6px 0 6px}
.bar-scroll{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch}
.bar{position:relative;min-width:700px;margin:0 16px;--row:36px;
  height:calc(var(--up) * var(--row) + 46px + 22px + var(--down) * var(--row) + 8px)}
.bar .axis{position:absolute;left:0;right:0;top:calc(var(--up) * var(--row) + 6px);height:40px;border-radius:8px;
  overflow:hidden;background:var(--surface-2)}
.bar .seg{position:absolute;top:0;bottom:0;display:flex;align-items:center;padding:0 8px;font-size:13px;
  color:var(--fg);border-right:2px solid var(--bg);overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.bar .seg span{overflow:hidden;text-overflow:ellipsis}
.bar .p0{background:color-mix(in srgb,var(--accent) 22%,transparent)}
.bar .p1{background:color-mix(in srgb,var(--warn) 24%,transparent)}
.bar .p2{background:color-mix(in srgb,var(--pos) 22%,transparent)}
.bar .lust{position:absolute;top:0;bottom:0;width:4px;margin-left:-2px;background:var(--neg)}
.bar .ticks{position:absolute;left:0;right:0;top:calc(var(--up) * var(--row) + 50px);height:18px;
  font:500 12px var(--font-data);color:var(--muted)}
.bar .ticks span{position:absolute;transform:translateX(-50%)} .bar .ticks span:first-child{transform:none}
.mk{position:absolute;padding:0;border:0;background:none;cursor:pointer;margin-left:-15px;line-height:0}
.mk img,.mk .ic-none{width:30px;height:30px;font-size:13px;border-radius:5px;border:2px solid var(--bg);box-shadow:0 1px 3px rgba(0,0,0,.25)}
.mk.up{top:calc((var(--up) - 1 - var(--r)) * var(--row))}
.mk.down{top:calc(var(--up) * var(--row) + 72px + var(--r) * var(--row))}
.mk:hover img,.mk:focus-visible img,.mk.on img{outline:3px solid var(--accent);outline-offset:1px}
.mk:focus-visible{outline:none}
.s-bar .say{min-height:28px;margin:8px 0 0;font-size:16px;font-weight:600}
.to-detail{margin:22px 0 0}
.to-detail .btn{font-size:16px;padding:10px 18px}
.back-simple{margin-right:8px}
@media (max-width:640px){.simple{font-size:16px}.simple .cards{grid-template-columns:1fr}}
"""

JS = """<script>
(function(){
document.querySelectorAll('.s-bar').forEach(function(card){
  var say = card.querySelector('.say');
  card.querySelectorAll('.mk').forEach(function(m){
    function show(){ card.querySelectorAll('.mk.on').forEach(function(o){ o.classList.remove('on'); });
      m.classList.add('on'); say.textContent = m.dataset.t + ' \u00b7 ' + m.dataset.text; }
    m.addEventListener('click', show); m.addEventListener('mouseenter', show); m.addEventListener('focus', show); });
});
})();
</script>"""
