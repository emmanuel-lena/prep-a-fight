"""The fight view of a prep sheet: what to do and when, before and during the pull.

Left, sticky: your job on this boss, then a Now / Next card that plays the fight from the pull (or from a pull timer)
and a second screen for a boss-mod look. Right: the fight on one clock, three lanes: the boss | the pull clock | you,
with the duration of your cooldowns, the adds and Bloodlust drawn along it.

Everything comes from the prep (generic across specs, PRODUCT.md): the boss's spells and add waves at the top raids'
typical times, the strategy's movement, your cooldown plan (paf.optimize), your defensives (paf.defensives) and what
the top players do on the boss (paf.actions). During the pull, one press ("it starts now") moves the moments still to
come by the boss's delay, so the card follows a raid that is ahead or behind the plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape as e
from importlib.resources import files

from paf import icons, simple, theme

ROW_GAP = 6.0  # seconds: events this close share one moment
PRE = -2.0  # where the "before the pull" moment sits
ANCHORS = ("phase", "adds", "cast", "move")  # boss moments a press can confirm, in title order
LUST_SECONDS = 40.0
POTION_SECONDS = 30.0


@dataclass
class Item:
    side: str  # "boss" or "you"
    kind: str  # boss: phase, adds, cast, move, lust; you: cd, pot, def, do
    name: str  # game name (icon, tooltip)
    text: str  # what the lane says
    icon: str = ""
    dur: float = 0.0  # seconds it lasts (a bar along the clock), 0 = none


@dataclass
class Moment:
    t: float
    items: list[Item] = field(default_factory=list)

    @property
    def boss(self) -> list[Item]:
        return [i for i in self.items if i.side == "boss"]

    @property
    def you(self) -> list[Item]:
        return [i for i in self.items if i.side == "you"]

    @property
    def anchor(self) -> Item | None:
        """The boss event that marks this moment in the game (what a press confirms), if any."""
        for kind in ANCHORS:
            for i in self.boss:
                if i.kind == kind:
                    return i
        return None

    @property
    def title(self) -> str:
        if self.t < 0:
            return "Before the pull"
        if self.t < 1:
            return "The pull"
        a = self.anchor
        if a is not None:
            return a.text
        return self.you[0].text if self.you else ""


def _mmss(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _icon(d, name: str) -> str:
    return d.icons.get(name, "") or simple._fallback(d, name)


def _durations(d) -> dict[str, float]:
    """Cooldown name -> seconds its aura lasts (game data), for the spells the sheet links."""
    try:
        from paf import gamedata

        table = gamedata.spell_durations()
    except Exception:  # noqa: BLE001 - no game data: no bars
        return {}
    out: dict[str, float] = {}
    for name, ref in d.links.items():
        if ref.startswith("spell="):
            sid = ref[6:].split("&")[0]
            if sid.isdigit() and 0 < table.get(int(sid), 0) <= 60:
                out[name] = table[int(sid)]
    return out


def items(d) -> list[tuple[float, Item]]:
    """Every event of the fight, (time, item)."""
    out: list[tuple[float, Item]] = []
    todo = {"kill": "Kill {}", "interrupt": "Interrupt {}", "contact": "Soak {}"}
    act = {a.name: todo[a.kind] for a in d.actions if a.kind in todo
           and not (a.kind == "interrupt" and not a.text.startswith("Interrupt"))}
    for name, start in sorted(d.phases, key=lambda p: p[1]):
        if start >= 1:
            out.append((start, Item("boss", "phase", name, name)))
    for name, times in d.boss_casts:
        for t in times:
            out.append((t, Item("boss", "cast", name, name, _icon(d, name))))
            if name in act:
                out.append((t, Item("you", "do", name, act[name].format(name), _icon(d, name))))
    for t, count, life, name in d.waves:
        if not count:
            continue
        label = f"{count} × {name}" if count > 1 else name
        out.append((t, Item("boss", "adds", name, label, _icon(d, name), float(life or 0))))
        if name in act:
            out.append((t, Item("you", "do", name, act[name].format(name), _icon(d, name))))
    for f in (d.fight.focus if d.fight is not None else []):
        out.append((f.start, Item("you", "do", f.name, f"Hit {f.name}", _icon(d, f.name))))
    if d.lust is not None:
        out.append((d.lust, Item("boss", "lust", "Bloodlust", "Bloodlust", _icon(d, "Bloodlust"), LUST_SECONDS)))
    names, order, _ = simple._pressed(d)
    dur = _durations(d)
    for n in names:
        pot = "potion" in n.lower()
        for t in order[n]:
            at = PRE if t < 0.5 and (n in d.precast or pot) else t
            out.append((at, Item("you", "pot" if pot else "cd", n, n, _icon(d, n),
                                 POTION_SECONDS if pot else dur.get(n, 0.0))))
    for m in (d.defensives.moments if d.defensives else []):
        if m.spells:
            s = m.spells[0][0]
            why = f" for {m.boss_ability}" if m.boss_ability else ""
            out.append((m.time, Item("you", "def", s, f"{s}{why}", _icon(d, s))))
    for w in (d.movement.windows if d.movement else []):
        out.append((w.start, Item("boss", "move", "Movement", f"Everyone moves for {w.duration:.0f} s",
                                  _icon(d, "Movement"), float(w.duration))))
        out.append((w.start, Item("you", "do", "Movement", "Move with the raid", _icon(d, "Movement"))))
        for s, _share in w.spells[:1]:
            out.append((w.start, Item("you", "do", s, f"{s} to keep up", _icon(d, s))))
    return sorted(out, key=lambda x: x[0])


def moments(d) -> list[Moment]:
    """Events close in time share a moment; a phase start always opens its own."""
    out: list[Moment] = []
    for t, it in items(d):
        if (not out or t - out[-1].t > ROW_GAP or (it.kind == "phase" and t - out[-1].t > 0.5)
                or (t < 0) != (out[-1].t < 0)):
            out.append(Moment(t))
        out[-1].items.append(it)
    return out


def _phases(d, dur: float) -> list[tuple[str, float, float]]:
    ph = sorted(d.phases, key=lambda p: p[1]) or [("The fight", 0.0)]
    return [(n, 0.0 if i == 0 else s, ph[i + 1][1] if i + 1 < len(ph) else dur) for i, (n, s) in enumerate(ph)]


def _ic(icon: str, cls: str = "ic") -> str:
    if not icon:
        return f"<i class='{cls} none' aria-hidden='true'></i>"
    return (f"<i class='{cls}' aria-hidden='true' style=\"background-image:url('"
            f"{icons.CDN.format(size='medium', icon=icon)}')\"></i>")


def _ev(it: Item) -> str:
    bold = it.side == "you" and it.kind in ("cd", "pot", "def")
    text = f"<b>{e(it.text)}</b>" if bold else e(it.text)
    small = f"<small>lasts {it.dur:.0f} s</small>" if it.dur and it.kind not in ("move",) else ""
    return (f"<div class='ev ek-{it.kind}'>{_ic(it.icon)}<div class='x'><span class='main'>{text}</span>{small}"
            "</div></div>")


def _row(m: Moment, i: int) -> str:
    boss = "".join(_ev(x) for x in m.boss if x.kind != "phase")  # the phase's band already says it
    you = "".join(_ev(x) for x in m.you)
    when = "Before the pull" if m.t < 0 else ("Pull" if m.t < 1 else _mmss(m.t))
    label = f"{when}, {m.title}: show this moment"
    quiet = not m.you and not any(x.kind in ("phase", "adds", "move", "lust") for x in m.boss)
    cls = "fm quiet" if quiet else "fm"
    return (f"<div class='{cls}{' has-boss' if boss else ''}' data-i='{i}' data-t='{m.t:g}'>"
            f"<div class='boss'>{'<span class=vh>Boss: </span>' + boss if boss else ''}</div>"
            f"<div class='spine'><button type='button' class='t' aria-label='{e(label)}'>{e(when)}</button></div>"
            f"<div class='you'>{'<span class=vh>You: </span>' + you if you else ''}</div></div>")


def job_html(d) -> str:
    """Your job on this boss, in six lines at most: what kills a raid first, then your cooldowns and when."""
    rows = [(ic, f"<b>{e(say)}</b>") for ic, say in simple._watch(d)[:3]]
    names, order, held = simple._pressed(d)
    for n in names:
        pre = [t for t in order[n] if t < 0.5 and (n in d.precast or "potion" in n.lower())]
        rest = [_mmss(t) for t in order[n] if t not in pre]
        when = ", ".join(rest[:5]) + ("…" if len(rest) > 5 else "")
        if pre:
            when = "before the pull" + (f", then {when}" if rest else "")
        elif rest:
            when = f"at {when}"
        rows.append((n, f"<b>{e(n)}</b> {e(when)}."))
    if not rows:
        return ""
    lis = "".join(f"<li>{_ic(_icon(d, ic))}<span>{txt}</span></li>" for ic, txt in rows[:6])
    how = "Hold your cooldowns for these times." if held else "Press your cooldowns as soon as they are ready."
    return (f"<section class='fbox job'><h2>Your job on this boss</h2><ul class='keys'>{lis}</ul>"
            f"<p class='how'>{how}</p></section>")


def data(d, ms: list[Moment], dur: float) -> dict:
    """What the page's script needs: the moments and what to press, on the plan's clock."""
    return {
        "end": round(dur, 1),
        "phases": [[n, round(s, 1), round(t, 1)] for n, s, t in _phases(d, dur)],
        "moments": [{"t": round(m.t, 1), "title": m.title,
                     "anchor": (m.anchor.text if m.anchor is not None else ""),
                     "boss": [x.text for x in m.boss],
                     "you": [{"n": x.text, "k": x.kind, "ic": x.icon, "d": round(x.dur, 1)} for x in m.you]}
                    for m in ms],
        "strips": [{"t": round(t, 1), "d": round(x.dur, 1), "k": x.kind, "side": x.side, "n": x.name}
                   for t, x in items(d) if x.dur and x.kind in ("cd", "pot", "lust", "adds", "move")],
    }


def mrt(d) -> str:
    plan = simple._plan(d)
    want = plan.objective if plan is not None else "boss"
    return d.mrt.get(want) or next(iter(d.mrt.values()), "")


def _btn(id_: str, label: str, keys: str = "", cls: str = "btn", hidden: bool = False, more: str = "") -> str:
    """A button of the card; `keys` its keyboard shortcut (aria-keyshortcuts, then shown as it reads)."""
    shown = {"Space": "Space", "Alt+P": "Alt P", "Control+Shift+Space": "Ctrl ⇧ Space", "Escape": "Esc"}
    kbd = f"<kbd aria-hidden='true'>{shown[keys]}</kbd>" if keys else ""
    attrs = (f" aria-keyshortcuts='{keys}'" if keys else "") + (" hidden" if hidden else "") + more
    return f"<button type='button' class='{cls}' id='{id_}'{attrs}><span>{label}</span>{kbd}</button>"


def _phase_html(name: str, start: float, end: float, pi: int, rows: str) -> str:
    lasts = f"Starts around {_mmss(start)}; " if start >= 1 else "Starts at the pull; "
    lanes = "".join(f"<span>{x}</span>" for x in ("The boss", "Pull clock", "You"))
    return (f"<section class='stl' aria-labelledby='ph{pi}-h'><div class='ph-band' id='ph{pi}'><div class='ph-name'>"
            f"<h2 id='ph{pi}-h'>{e(name)}</h2><span>{lasts}lasts about {_mmss(end - start)}.</span></div>"
            f"<div class='ph-lanes' aria-hidden='true'>{lanes}</div></div>{rows}</section>")


LEGEND = ("<div class='fv-legend' aria-hidden='true'><span><i class='s-cd'></i>your cooldown</span>"
          "<span><i class='s-pot'></i>your potion</span><span><i class='s-lust'></i>Bloodlust</span>"
          "<span><i class='s-adds'></i>adds alive</span><span><i class='s-move'></i>everyone moves</span>"
          "<span>each bar lasts as long as it does in the fight</span></div>")


def _side(d) -> str:
    note = mrt(d)
    copy = (_btn("mrt", "Copy as MRT note", cls="btn ghost")
            + f"<textarea class='mrt-box' id='mrt-text' aria-label='MRT note' readonly hidden>{e(note)}</textarea>"
            if note else "")
    speed = ("<span class='seg' role='group' aria-label='Speed'><button type='button' data-s='1' aria-pressed='true'>"
             "×1</button><button type='button' data-s='4' aria-pressed='false'>×4</button></span>")
    return ("<aside class='fside' aria-label='Your plan'><section class='fbox now' aria-labelledby='now-h'>"
            "<h2 class='vh' id='now-h'>Now in the fight</h2>"
            "<div class='clock'><b id='c-time'>0:00</b><span id='c-phase'></span></div>"
            f"<div class='ctl'>{_btn('play', 'Play', 'Space', 'btn primary')}{speed}"
            f"{_btn('pull', 'Start at 10 on the pull timer', 'Alt+P')}</div>"
            "<h3 id='c-title'></h3><dl class='who'><dt>Boss</dt><dd id='c-boss'></dd><dt>You</dt>"
            "<dd class='yd' id='c-you'></dd></dl><div class='call' id='c-call'></div><p class='then' id='c-then'></p>"
            "<div class='nb'><p><span id='c-next'></span><b id='c-in'></b></p>"
            "<div class='meter'><i id='c-meter'></i></div></div>"
            f"{_btn('c-sync', '', 'Control+Shift+Space', hidden=True)}"
            f"<div class='foot'>{_btn('ss-open', 'Second screen', cls='btn ghost')}{copy}</div></section>"
            f"{job_html(d)}<p class='deep'>For those who dig: the cooldown plan, when the top players press each "
            "cooldown and every number are in <a href='#deeper'>Dig deeper</a>.</p></aside>")


def _second_screen(d) -> str:
    return ("<div class='ss' id='ss' role='dialog' aria-modal='true' aria-labelledby='ss-h' hidden tabindex='-1'>"
            f"<div class='ss-top'><h2><span id='ss-h'>{e(d.boss)}</span> {theme.diff_pill(d.difficulty)}</h2>"
            "<span class='ss-clock' id='ss-clock'>0:00</span><span class='ss-phase' id='ss-phase'></span>"
            f"{_btn('ss-close', 'Back to the plan', 'Escape')}</div>"
            "<div class='ss-mid'><div class='call' id='ss-call'></div><p class='then' id='ss-then'></p>"
            "<div class='bars' id='ss-bars' role='list' aria-label='Coming up'></div></div>"
            f"<div class='ss-bot'><div class='grp'>{_btn('ss-play', 'Play', cls='btn primary')}"
            f"{_btn('ss-pull', 'Start at 10 on the pull timer', 'Alt+P')}"
            f"{_btn('ss-sync', '', 'Control+Shift+Space', hidden=True)}</div>"
            f"<div class='grp'>{_btn('ss-sound', 'Voice and beeps', cls='btn ghost', more=' aria-pressed=false')}"
            f"{_btn('ss-wipe', 'Wipe, back to the pull', cls='btn ghost')}</div></div></div>")


def html(d) -> str:
    """The fight view, or '' when the prep has no fight to show."""
    dur = d.duration or (d.fight.duration if d.fight else 0)
    ms = moments(d)
    if not dur or not ms:
        return ""
    sections = []
    for pi, (name, start, end) in enumerate(_phases(d, dur)):
        rows = "".join(_row(m, i) for i, m in enumerate(ms) if (m.t >= start - 0.5 or pi == 0) and m.t < end - 0.5)
        if rows:
            sections.append(_phase_html(name, start, end, pi, rows))
    payload = json.dumps(data(d, ms, dur)).replace("</", "<\\/")
    return (f"<div class='fv'><a class='skip' href='#tl'>Skip to the fight</a><div class='sheet-fv'>{_side(d)}"
            f"<section class='ftl' id='tl' tabindex='-1' aria-label='The fight'>{LEGEND}{''.join(sections)}"
            f"<div class='tl-end'></div></section></div>{_second_screen(d)}"
            "<p class='vh' id='sr' aria-live='polite' aria-atomic='false'></p>"
            f"<script>var FV={payload};</script><script>{JS}</script></div>")


CSS = theme.style("fightview")
JS = files("paf").joinpath("scripts", "fightview.js").read_text(encoding="utf-8")
