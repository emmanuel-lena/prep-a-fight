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
import re
from dataclasses import dataclass, field
from html import escape as e
from importlib.resources import files

from paf import icons, simple, theme

ROW_GAP = 6.0  # seconds: events this close share one row of the timeline
PRE = -2.0  # where "before the pull" sits
ANCHORS = ("phase", "immune", "adds", "cast")  # boss events a press can confirm, and that name a row, in this order
YOU_ORDER = ("pot", "cd", "def", "do", "move")  # your items in a row: the burst first, the movement cue last
LUST_SECONDS = 40.0
POTION_SECONDS = 30.0
DEF_SUPPORT = 0.4  # a defensive is shown when at least this share of the top players press one there
DEF_SNAP = 10.0  # a defensive this close before its boss ability is moved to just before it
MOVE_CUE = 10.0  # a movement window this long gets a "keep up" cue (with the spell the top players use)
MOVE_LONG = 20.0  # longer: a stretch of moving around, not one move
MOVE_ICON = "inv_misc_map_01"  # a neutral picture: no spell of yours
IMMUNE_ICON = "spell_holy_divineshield"


@dataclass
class Item:
    side: str  # "boss" or "you"
    kind: str  # boss: phase, immune, adds, cast, move, lust; you: pot, cd, def, do, move
    name: str  # game name (icon, tooltip)
    text: str  # what the lane says
    icon: str = ""
    dur: float = 0.0  # seconds it lasts (a bar along the clock), 0 = none
    t: float = 0.0  # its own time (a row groups items a few seconds apart)


@dataclass
class Moment:
    t: float
    items: list[Item] = field(default_factory=list)

    @property
    def boss(self) -> list[Item]:
        return [i for i in self.items if i.side == "boss"]

    @property
    def you(self) -> list[Item]:
        return sorted((i for i in self.items if i.side == "you"), key=lambda i: (YOU_ORDER.index(i.kind), i.t))

    @property
    def anchor(self) -> Item | None:
        """The boss event that names this row, if any (movement and Bloodlust never do)."""
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
        return self.you[0].text if self.you else (self.boss[0].text if self.boss else "")


def _mmss(t: float) -> str:
    s = round(max(0.0, t))  # rounded, as the page's script shows it
    return f"{s // 60}:{s % 60:02d}"


def _icon(d, name: str) -> str:
    return d.icons.get(name, "") or simple._fallback(d, name)


def _clean(name: str) -> str:
    """A unit's name as the game shows it: the corpus's notes in brackets go ('Echo (after Soul Transfer)')."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip() or name


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
    missing = {d.cd_names.get(k, k) for k in d.cd_names} - set(out)
    if missing:  # a cooldown the sheet does not link: its name in the game's spell table
        try:
            from paf import gamedata

            seen: dict[str, set[float]] = {}
            for sid, name in gamedata.spell_names().items():
                if name in missing and 0 < table.get(sid, 0) <= 60:
                    seen.setdefault(name, set()).add(table[sid])
            out.update({n: next(iter(v)) for n, v in seen.items() if len(v) == 1})  # only when the name is clear
        except Exception:  # noqa: BLE001 - no names: no bar for it
            pass
    return out


def _defensives(d) -> list[tuple[float, str, str]]:
    """(time, spell, boss ability) of the defensives most top players press, just before the hit they take."""
    casts = dict(d.boss_casts)
    out = []
    for m in (d.defensives.moments if d.defensives else []):
        if not m.spells or m.share < DEF_SUPPORT:
            continue
        t = m.time
        hits = [c for c in casts.get(m.boss_ability, []) if t - 3 <= c <= t + DEF_SNAP] if m.boss_ability else []
        if hits:
            t = max(0.0, min(hits, key=lambda c: abs(c - t)) - 1)
        why = m.boss_ability if hits or any(abs(c - t) <= 15 for c in casts.get(m.boss_ability, [])) else ""
        out.append((t, m.spells[0][0], why))
    return out


def items(d) -> list[tuple[float, Item]]:
    """Every event of the fight, (time, item), each at its own time."""
    out: list[tuple[float, Item]] = []

    def add(t: float, it: Item) -> None:
        it.t = t
        out.append((t, it))

    todo = {"kill": "Kill {}", "interrupt": "Interrupt {}", "contact": "Soak {}"}
    act = {a.name: todo[a.kind] for a in d.actions if a.kind in todo
           and not (a.kind == "interrupt" and not a.text.startswith("Interrupt"))}
    skip = {a.name for a in d.actions if a.kind == "ignore"}
    for name, start in sorted(d.phases, key=lambda p: p[1]):
        if start >= 1:
            add(start, Item("boss", "phase", name, f"{name} begins"))
    starts = [s for _n, s in d.phases if s >= 1]
    for w in (d.fight.invulnerable if d.fight is not None else []):
        at = next((s for s in starts if abs(s - w.start) <= 3), w.start)  # an intermission: on its phase's row
        add(at, Item("boss", "immune", "Boss immune", f"The boss is immune for {w.duration:.0f} s", IMMUNE_ICON,
                     float(w.duration)))
    roles = getattr(d, "ability_roles", None) or {}
    hits_you = {why for _t, _s, why in _defensives(d)}
    for name, times in d.boss_casts:
        # the journal flags it for the tank only (and you need no defensive for it): shown dimmed, never confirmed
        tank = roles.get(name) == ["tank"] and name not in hits_you
        for t in times:
            add(t, Item("boss", "tank" if tank else "cast", name, f"{name} (tank)" if tank else name, _icon(d, name)))
            if name in act:
                add(t, Item("you", "do", name, act[name].format(name), _icon(d, name)))
    for t, count, life, name in d.waves:
        if not count:
            continue
        shown = _clean(name)
        label = f"{count} × {shown}" if count > 1 else shown
        stop = d.duration or (d.fight.duration if d.fight else 0) or t + life
        for w in (d.fight.invulnerable if d.fight is not None else []):  # adds of an intermission die with it
            if w.start - 3 <= t <= w.start + w.duration:
                stop = min(stop, w.start + w.duration)
        add(t, Item("boss", "adds", name, label, _icon(d, name), float(min(life or 0, max(0.0, stop - t)))))
        if name not in skip and _clean(name) not in skip:
            add(t, Item("you", "do", name, act.get(name, "Kill {}").format(shown), _icon(d, name)))
    for f in (d.fight.focus if d.fight is not None else []):
        add(f.start, Item("you", "do", f.name, f"Hit {f.name}", _icon(d, f.name)))
    if d.lust is not None:
        lust = 0.0 if d.lust < 1 else d.lust  # within a second of the pull: at the pull
        add(lust, Item("boss", "lust", "Bloodlust", "Your raid's Bloodlust", _icon(d, "Bloodlust"), LUST_SECONDS))
    names, order, _ = simple._pressed(d)
    dur = _durations(d)
    for n in names:
        pot = "potion" in n.lower()
        for t in order[n]:
            at = PRE if t < 0.5 and (n in d.precast or pot) else t
            add(at, Item("you", "pot" if pot else "cd", n, n, _icon(d, n), POTION_SECONDS if pot else dur.get(n, 0.0)))
    for t, s, why in _defensives(d):
        add(t, Item("you", "def", s, f"{s} for {why}" if why else s, _icon(d, s), dur.get(s, 0.0)))
    end = d.duration or (d.fight.duration if d.fight else 0)
    if end:
        add(end, Item("boss", "kill", "The kill", f"The kill, around {_mmss(end)}"))
    cuts = sorted(s for _n, s in d.phases if s >= 1)
    for w in (d.movement.windows if d.movement else []):  # the strategy's movement: a bar, never an event
        a, b = w.start, w.start + w.duration
        for s0, s1 in zip([a] + [c for c in cuts if a < c < b], [c for c in cuts if a < c < b] + [b], strict=True):
            long = s1 - s0 > MOVE_LONG
            add(s0, Item("boss", "move", "Movement", f"Movement until {_mmss(s1)}" if long else
                         f"Movement, {s1 - s0:.0f} s", MOVE_ICON, float(s1 - s0)))
            if MOVE_CUE <= s1 - s0 <= MOVE_LONG and w.spells:
                s = w.spells[0][0]
                add(s0, Item("you", "move", s, f"{s} for the move", _icon(d, s)))
    starts = sorted(s for _n, s in d.phases if s >= 1)
    for k, (t, it) in enumerate(out):  # a boss event logged just before a phase starts belongs to that phase
        s = next((s for s in starts if s - 1.0 <= t < s), None)
        if s is not None and it.side == "boss" and it.kind != "phase":
            it.t = s
            out[k] = (s, it)
    return sorted(out, key=lambda x: (x[0], x[1].kind != "phase"))


def moments(d) -> list[Moment]:
    """Events close in time share a row; a phase start always opens its own."""
    out: list[Moment] = []
    for t, it in items(d):
        if (not out or t - out[-1].t > ROW_GAP or (it.kind == "phase" and t - out[-1].t > 0.5)
                or (t < 0) != (out[-1].t < 0)):
            out.append(Moment(t))
        out[-1].items.append(it)
    return out


def _phases(d, dur: float) -> list[tuple[str, float, float]]:
    ph = sorted(d.phases, key=lambda p: p[1]) or [("The fight", 0.0)]
    if ph[0][0].strip().lower() in ("", d.boss.lower()):  # a first phase named after the boss: say what it is
        ph[0] = ("Stage One" if len(ph) > 1 else "The fight", ph[0][1])
    return [(n, 0.0 if i == 0 else s, ph[i + 1][1] if i + 1 < len(ph) else dur) for i, (n, s) in enumerate(ph)]


def _ic(icon: str, cls: str = "ic") -> str:
    if not icon:
        return f"<i class='{cls} none' aria-hidden='true'></i>"
    return (f"<i class='{cls}' aria-hidden='true' style=\"background-image:url('"
            f"{icons.CDN.format(size='medium', icon=icon)}')\"></i>")


def _ev(it: Item, row_t: float | None = None) -> str:
    bold = it.side == "you" and it.kind in ("cd", "pot", "def")
    text = f"<b>{e(it.text)}</b>" if bold else e(it.text)
    notes = [f"at {_mmss(it.t)}"] if row_t is not None and it.t >= 0 and abs(it.t - row_t) > 2 else []
    if it.dur and it.kind not in ("move", "immune"):
        notes.append(f"lasts {it.dur:.0f} s")
    small = f"<small>{', '.join(notes)}</small>" if notes else ""
    return (f"<div class='ev ek-{it.kind}'>{_ic(it.icon)}<div class='x'><span class='main'>{text}</span>{small}"
            "</div></div>")


def _row(m: Moment, i: int, gap: float = 0.0) -> str:
    shown = [x for x in m.boss if x.kind != "phase"] or m.boss  # the phase's band says it, unless it is alone
    boss = "".join(_ev(x, m.t) for x in shown)
    you = "".join(_ev(x, m.t) for x in m.you)
    when = "Before the pull" if m.t < 0 else ("Pull" if m.t < 1 else _mmss(m.t))
    label = f"{when}, {m.title}: show this moment"
    quiet = not m.you and not any(x.kind in ("phase", "immune", "adds", "move", "lust", "kill") for x in m.boss)
    quiet = quiet or (not m.you and all(x.kind == "tank" for x in m.boss))
    cls = "fm quiet" if quiet else ("fm kill" if any(x.kind == "kill" for x in m.boss) else "fm")
    room = f" style='min-height:{min(110, max(0, (gap - ROW_GAP) * 2.2)) + 34:.0f}px'" if gap > ROW_GAP else ""
    return (f"<div class='{cls}{' has-boss' if boss else ''}' data-i='{i}' data-t='{m.t:g}' data-title='{e(m.title)}'"
            f"{room}>"
            f"<div class='boss'>{'<span class=vh>Boss: </span>' + boss if boss else ''}</div>"
            f"<div class='spine'><button type='button' class='t' aria-label='{e(label)}'>{e(when)}</button></div>"
            f"<div class='you'>{'<span class=vh>You: </span>' + you if you else ''}</div></div>")


def job_html(d) -> str:
    """Your job on this boss, in six lines at most: what kills a raid first, then your cooldowns and when."""
    from paf.prep_report import rule_phrase

    rows = [(a.name, f"<b>{e(a.text.split(':')[0].split(' (')[0])}</b>") for a in d.actions
            if a.kind in ("kill", "contact") or (a.kind == "interrupt" and a.text.startswith("Interrupt"))][:2]
    for w in (d.fight.invulnerable if d.fight is not None else [])[:1]:
        adds = [_clean(x[3]) for x in d.waves if w.start - 2 <= x[0] <= w.start + w.duration and x[1]]
        what = f": kill the {e(adds[0])} to bring it back" if adds else ""
        rows.append((IMMUNE_ICON, f"<b>The boss is immune at {_mmss(w.start)}</b> for {w.duration:.0f} s{what}."))
    defs = _defensives(d)
    if defs:
        s, why = defs[0][1], defs[0][2]
        rows.append((s, f"<b>{e(s)}</b>{' for ' + e(why) if why else ''}, the top players' defensive."))
    names, order, _held = simple._pressed(d)
    plan = simple._plan(d)
    rules = {d.cd_names.get(k, k): r.name for k, r in (plan.choice.items() if plan else []) if r.name != "default"}
    if d.lust is not None and d.lust < 5 and names:
        rows.append(("Bloodlust", "<b>Bloodlust at the pull</b>: your opener goes inside it."))
    for n in sorted(names, key=lambda n: min(order[n])):  # in the order you first press them
        pre = [t for t in order[n] if t < 0.5 and (n in d.precast or "potion" in n.lower())]
        rest = [_mmss(t) for t in order[n] if t not in pre]
        when = ", ".join(rest[:5]) + ("…" if len(rest) > 5 else "")
        if pre:
            when = "before the pull" + (f", then {when}" if rest else "")
        elif rest:
            when = f"at {when}"
        why = f": {rule_phrase(d, rules[n])}" if n in rules else ""
        rows.append((n, f"<b>{e(n)}</b> {e(when)}{e(why)}."))
    if not rows:
        return ""
    lis = "".join(f"<li>{_ic(ic if ic == IMMUNE_ICON else _icon(d, ic) if ic else '')}<span>{txt}</span></li>"
                  for ic, txt in rows[:7])
    return f"<section class='fbox job'><h2>Your job on this boss</h2><ul class='keys'>{lis}</ul></section>"


def _ctx(t: float, its: list[tuple[float, Item]]) -> str:
    """What a press is for, in a few words: on the pull, on the boss event it answers, inside Bloodlust."""
    if t < 0:
        return "before the pull"
    if t < 5:
        return "on the pull"
    near = [x for at, x in its if x.side == "boss" and x.kind in ANCHORS and t - 8 <= at <= t + 1]
    if near:
        order = ("adds", "cast", "immune", "phase")  # what you press it for, the most concrete first
        x = min(near, key=lambda x: (order.index(x.kind), abs(x.t - t)))
        return "on the " + x.text if x.kind == "adds" else ("when it starts" if x.kind == "phase" else "on " + x.text)
    return ""


PULL = {"t": 0, "n": "The pull", "k": "pull", "p": 0, "ic": ""}  # a pull timer that runs late: confirm the pull


def data(d, ms: list[Moment], dur: float) -> dict:
    """What the page's script needs, each event at its own time on the plan's clock."""
    its = items(d)
    phases = _phases(d, dur)

    def ph(t: float) -> int:
        return max((i for i, p in enumerate(phases) if t >= p[1] - 0.5), default=0)

    phase_starts = [s for _n, s, _e in phases[1:]]
    acts = [{"t": round(t, 1), "n": x.text, "k": x.kind, "ic": x.icon, "d": round(x.dur, 1),
             "c": "" if x.kind == "move" else _ctx(t, its)} for t, x in its if x.side == "you"]
    acts.sort(key=lambda a: (a["t"], YOU_ORDER.index(a["k"])))
    return {
        "end": round(dur, 1),
        "phases": [[n, round(s, 1), round(t, 1)] for n, s, t in phases],
        "rows": [round(m.t, 1) for m in ms],
        "acts": acts,
        "anchors": [PULL] + [{"t": round(t, 1), "n": x.name if x.kind in ("phase", "immune") else x.text, "k": x.kind,
                     "p": ph(t), "ic": x.icon} for t, x in its if x.side == "boss" and x.kind in ANCHORS and t >= 1
                    and not (x.kind != "phase" and any(abs(t - s) <= 1 for s in phase_starts))],
        "boss": [{"t": round(t, 1), "d": round(x.dur, 1), "n": x.text, "k": x.kind} for t, x in its
                 if x.side == "boss" and x.kind not in ("phase",)],
        "strips": [{"t": round(t, 1), "d": round(x.dur, 1), "k": x.kind, "side": x.side, "n": x.name}
                   for t, x in its if x.dur and x.kind in ("cd", "pot", "def", "lust", "adds", "move", "immune")],
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


def _phase_html(name: str, start: float, end: float, pi: int, rows: str, its: list) -> str:
    lasts = f"Starts around {_mmss(start)}; " if start >= 1 else "Starts at the pull; "
    lanes = "".join(f"<span>{x}</span>" for x in ("The boss", "Pull clock", "You"))
    mine = [(t, x) for t, x in its if start - 0.5 <= t < end - 0.5 and x.side == "boss"]
    said = [x.text[0].lower() + x.text[1:] for _t, x in mine if x.kind == "immune"]
    said += [f"{x.text} at {_mmss(t)}" for t, x in mine if x.kind == "adds"]
    lust = [t for t, x in mine if x.kind == "lust"]
    if lust:
        said.insert(0, "Bloodlust " + ("at the pull" if lust[0] < 5 else f"at {_mmss(lust[0])}"))
    adv = f"<p class='ph-adv'>{e(cap(', then '.join(said)))}.</p>" if said else ""
    return (f"<section class='stl' aria-labelledby='ph{pi}-h'><div class='ph-band' id='ph{pi}'><div class='ph-name'>"
            f"<h2 id='ph{pi}-h'>{e(name)}</h2><span>{lasts}lasts about {_mmss(end - start)}.</span></div>{adv}"
            f"<div class='ph-lanes' aria-hidden='true'>{lanes}</div></div>{rows}</section>")


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


LEGEND = ("<div class='fv-legend' aria-hidden='true'><span><i class='s-cd'></i>your cooldown</span>"
          "<span><i class='s-pot'></i>your potion</span><span><i class='s-def'></i>your defensive</span>"
          "<span><i class='s-lust'></i>Bloodlust</span>"
          "<span><i class='s-adds'></i>adds alive</span><span><i class='s-move'></i>everyone moves</span>"
          "<span>bar length = how long it lasts</span></div>")


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
    return (f"<dialog class='ss' id='ss' aria-label='{e(d.boss)}, second screen' tabindex='-1'>"
            f"<div class='ss-top'><h2><span id='ss-h'>{e(d.boss)}</span> {theme.diff_pill(d.difficulty)}</h2>"
            "<span class='ss-clock' id='ss-clock'>0:00</span><span class='ss-phase' id='ss-phase'></span>"
            "<span class='ss-boss' id='ss-boss' aria-label='Boss'></span>"
            f"{_btn('ss-close', 'Back to the plan', 'Escape')}</div>"
            "<div class='ss-mid'><div class='call' id='ss-call'></div><p class='then' id='ss-then'></p>"
            "<div class='bars' id='ss-bars' role='list' aria-label='Coming up'></div></div>"
            f"<div class='ss-bot'><div class='grp'>{_btn('ss-play', 'Play', cls='btn primary')}"
            f"{_btn('ss-pull', 'Start at 10 on the pull timer', 'Alt+P')}"
            f"{_btn('ss-sync', '', 'Control+Shift+Space', hidden=True)}</div>"
            f"<div class='grp'>{_btn('ss-sound', 'Voice and beeps', cls='btn ghost', more=' aria-pressed=false')}"
            f"{_btn('ss-wipe', 'Wipe, back to the pull', cls='btn ghost')}</div></div></dialog>")


def html(d) -> str:
    """The fight view, or '' when the prep has no fight to show."""
    dur = d.duration or (d.fight.duration if d.fight else 0)
    ms = moments(d)
    if not dur or not ms:
        return ""
    sections, phases, its = [], _phases(d, dur), items(d)
    for pi, (name, start, end) in enumerate(phases):
        last = pi == len(phases) - 1
        rows = "".join(_row(m, i, (ms[i + 1].t if i + 1 < len(ms) else dur) - m.t) for i, m in enumerate(ms)
                       if (m.t >= start - 0.5 or pi == 0) and (m.t < end - 0.5 or (last and m.t <= end)))
        if rows:
            sections.append(_phase_html(name, start, end, pi, rows, its))
    payload = json.dumps(data(d, ms, dur)).replace("</", "<\\/")
    return (f"<div class='fv'><a class='skip' href='#tl'>Skip to the fight</a><div class='sheet-fv'>{_side(d)}"
            f"<section class='ftl' id='tl' tabindex='-1' aria-label='The fight'>{LEGEND}{''.join(sections)}"
            f"<div class='tl-end'></div></section></div>{_second_screen(d)}"
            "<p class='vh' id='sr' aria-live='polite' aria-atomic='false'></p>"
            f"<script>var FV={payload};</script><script>{JS}</script></div>")


CSS = theme.style("fightview")
JS = files("paf").joinpath("scripts", "fightview.js").read_text(encoding="utf-8")
