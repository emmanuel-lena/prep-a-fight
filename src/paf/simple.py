"""The simple view of a prep sheet (issue #13): one screen, mostly pictures, for a player who does not read sims.

Three cards (what to change, what to press, what to watch out for), then the fight top to bottom, phase by
phase: the boss's spells on the left, what you do on the right (issue #9).
Everything else is in the details (paf.prep_report's tabs), one click away.
"""

from __future__ import annotations

from html import escape as e

from paf import icons

MAX_CDS = 3  # cooldowns on the "press" card
MAX_WATCH = 3  # lines on the "watch out" card
# game icons for what has none of its own
POTION_ICON = "inv_potion_54"
ADDS_ICON = "inv_misc_groupneedmore"
LUST_ICON = "spell_nature_bloodlust"


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _fallback(d, name: str) -> str:
    """A generic game icon for what has none of its own: the potion, Bloodlust, the adds."""
    if name.lower() == "potion":
        return POTION_ICON
    if name.lower() == "bloodlust":
        return LUST_ICON
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


# --- the whole fight, top to bottom (issue #9) ----------------------------------------------------------------------

ROW_GAP = 3.0  # seconds; events this close share a row


def _item(d, name: str, label: str) -> str:
    pic = _ic(d, name, "medium", "vi")
    return f"<span class='it'>{pic}<span>{e(label)}</span></span>"


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
            out.append((t, "r", _item(d, n, n)))
    for m in (d.defensives.moments if d.defensives else []):
        if m.spells:
            out.append((m.time, "r", _item(d, m.spells[0][0], f"Defensive: {m.spells[0][0]}")))
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
        lines = "".join(f"<li><div class='l'>{''.join(left)}</div><time>{_mmss(t)}</time>"
                        f"<div class='r'>{''.join(right)}</div></li>" for t, left, right in mine)
        blocks.append(f"<details class='vp'{' open' if not blocks else ''}><summary><span class='vp-name'>{e(name)}</span>"
                      f"<span class='vp-time'>{_mmss(start)} &ndash; {_mmss(end)}</span></summary>"
                      f"<ol class='vt'>{lines}</ol></details>")
    return (f"<article class='card s-fight'><h2>The fight, step by step</h2>"
            f"<p class='what'>Left: what the boss does. Right: what you do. Open a phase to see it.</p>"
            f"<div class='vt-head' aria-hidden='true'><span>The boss</span><span></span><span>You</span></div>"
            f"{''.join(blocks)}</article>")


def simple_html(d) -> str:
    cards = change_card(d) + press_card(d) + watch_card(d)
    return (f"<div class='simple'><div class='cards'>{cards}</div>{fight_html(d)}"
            f"<p class='to-detail'><a class='btn' href='#overview'>See all the details &rarr;</a></p></div>")


CSS = """
/* the simple view (paf.simple) */
body.simple-on .tabs{display:none}
.simple{max-width:980px;font-size:17px}
.simple .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.simple .card{margin:0;padding:18px 20px}
.simple h2{font:600 21px/1.2 'Fraunces',Georgia,serif;text-transform:none;letter-spacing:0;color:var(--fg);margin:0 0 12px}
.simple .cards ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:14px}
.simple .cards li{display:flex;gap:12px;align-items:center}
.simple .cards li>div{display:flex;flex-direction:column;gap:3px;min-width:0}
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
.simple .times time{font:600 15px var(--font-data);padding:2px 8px;border-radius:999px;background:var(--surface-2);
  border:1px solid var(--line)}
.simple .s-press .what{margin:-6px 0 12px}
/* the fight, top to bottom: the boss on the left, you on the right, the time in the middle */
.simple .s-fight{margin-top:16px}
.simple .s-fight>.what{margin:-6px 0 10px}
.vt-head,.vt li{display:grid;grid-template-columns:minmax(0,1fr) 64px minmax(0,1fr);gap:10px;align-items:center}
.vt-head{font:600 12px var(--font-data);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);padding:0 0 6px}
.vt-head span:first-child{text-align:right} .vt-head span:last-child{text-align:left}
.vp{border-top:1px solid var(--line)}
.vp>summary{display:flex;gap:12px;align-items:baseline;padding:12px 4px;cursor:pointer;list-style:none}
.vp>summary::-webkit-details-marker{display:none}
.vp>summary::before{content:"\\203A";color:var(--accent);font-size:20px;display:inline-block;transition:transform .2s}
.vp[open]>summary::before{transform:rotate(90deg)}
.vp-name{font:600 18px/1.3 'Fraunces',Georgia,serif;color:var(--fg)}
.vp-time{font:500 14px var(--font-data);color:var(--muted)}
.vt{list-style:none;margin:0 0 14px;padding:0;position:relative}
.vt::before{content:"";position:absolute;left:50%;top:0;bottom:0;border-left:2px solid var(--line)}
.vt li{padding:7px 0;position:relative}
.vt time{justify-self:center;z-index:1;font:600 14px var(--font-data);padding:3px 8px;border-radius:999px;
  background:var(--bg);border:1.5px solid var(--line);color:var(--fg)}
.vt .l,.vt .r{display:flex;flex-direction:column;gap:6px;min-width:0}
.vt .l{align-items:flex-end;text-align:right}
.vt .it{display:inline-flex;align-items:center;gap:8px;font-size:15.5px;line-height:1.3}
.vt .l .it{flex-direction:row-reverse}
.vt .it img,.vt .it .ic-none{width:30px;height:30px;font-size:13px;border-radius:5px}
.vt .it.do{font-weight:600;color:var(--accent)}
.to-detail{margin:22px 0 0}
.to-detail .btn{font-size:16px;padding:10px 18px}
.back-simple{margin-right:8px}
@media (max-width:640px){.simple{font-size:16px}.simple .cards{grid-template-columns:1fr}
  .vt-head,.vt li{grid-template-columns:minmax(0,1fr) 50px minmax(0,1fr);gap:6px}.vt .it{font-size:14px;gap:6px}
  .vt .it img,.vt .it .ic-none{width:24px;height:24px}}
"""

JS = ""
