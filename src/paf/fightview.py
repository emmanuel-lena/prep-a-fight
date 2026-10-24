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
YOU_ORDER = ("do", "pot", "cd", "def", "move")  # your items in a row: the job first, then the burst, the move last
LUST_SECONDS = 40.0
POTION_SECONDS = 30.0
DEF_SUPPORT = 0.4  # a defensive is shown when at least this share of the top players press one there
DEF_SNAP = 10.0  # a defensive this close before its boss ability is moved to just before it
MOVE_CUE = 10.0  # a movement window this long gets a "keep up" cue (with the spell the top players use)
MOVE_LONG = 20.0  # longer: a stretch of moving around, not one move
MOVE_ICON = "inv_misc_map_01"  # a neutral picture: no spell of yours
IMMUNE_ICON = "spell_holy_divineshield"
PHASE_ICON = "inv_misc_pocketwatch_01"  # a stage begins: the clock, never an empty square


@dataclass
class Item:
    side: str  # "boss" or "you"
    kind: str  # boss: phase, immune, adds, cast, move, lust; you: pot, cd, def, do, move
    name: str  # game name (icon, tooltip)
    text: str  # what the lane says
    icon: str = ""
    dur: float = 0.0  # seconds it lasts (a bar along the clock), 0 = none
    t: float = 0.0  # its own time (a row groups items a few seconds apart)
    why: str = ""  # a press no boss event explains: the plan's rule or its cooldown, and what the top players do
    hint: str = ""  # a boss event: the Encounter Journal's line for damage dealers that names it


@dataclass
class Moment:
    t: float
    items: list[Item] = field(default_factory=list)

    @property
    def boss(self) -> list[Item]:
        return [i for i in self.items if i.side == "boss"]

    @property
    def you(self) -> list[Item]:
        return sorted((i for i in self.items if i.side == "you"),  # in time order, then by kind
                      key=lambda i: (int(max(i.t, -1)), YOU_ORDER.index(i.kind)))

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


def _span(v: float) -> str:
    """A duration, never mistaken for a clock time: "12 s", "1 min 43 s"."""
    v = round(v)
    return f"{v} s" if v < 60 else f"{v // 60} min" + (f" {v % 60} s" if v % 60 else "")


def _mmss(t: float) -> str:
    s = int(max(0.0, t))  # whole seconds, as the MRT note and Dig deeper write them
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
    try:
        names = gamedata.spell_names()
    except Exception:  # noqa: BLE001 - no names: the linked spell only
        names = {}
    for name, ref in d.links.items():
        if ref.startswith("spell="):
            sid = ref[6:].split("&")[0]
            if sid.isdigit() and 0 < (table.get(int(sid)) or 0) <= 60:
                out[name] = table[int(sid)]
            elif sid.isdigit():  # the cast spell has no aura (Ascendance 114050): its aura is a neighbour of the name
                near = {table[s] for s in range(int(sid) - 3, int(sid) + 4)
                        if names.get(s) == name and 0 < (table.get(s) or 0) <= 60}
                if len(near) == 1:
                    out[name] = near.pop()
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
        if hits:  # never later than the top players press it: a cast time can be its channel's end (DPS round 10:
            # Feint at 3:05, 6 s long, moved to 3:11 for Imbibe "cast" at 3:12, when its venoms spawn)
            t = max(0.0, min(t, min(hits, key=lambda c: abs(c - t)) - 1))
        # the logs tie it to that ability; with no cast of it close by, it is a hit that lands long after its cast
        # no cast of it around the press (8 s before to 12 s after, as the defensives table reads it): a late hit
        late = m.boss_ability in casts and not [c for c in casts[m.boss_ability] if t - 8 <= c <= t + 12]
        why = f"{m.boss_ability}'s damage" if late else m.boss_ability
        out.append((t, m.spells[0][0], why))
    return out


def defensive_moments(d) -> list:
    """The defensive moments the fight tab calls, at its times (for the NSRT reminders: the same presses)."""
    from dataclasses import replace

    kept = {(s, round(t, 1)) for t, s, _w in _defensives(d)}
    out = []
    for m in (d.defensives.moments if d.defensives else []):
        if m.spells and m.share >= DEF_SUPPORT:
            t = next((t for s, t in kept if s == m.spells[0][0] and abs(t - m.time) <= DEF_SNAP + 3), m.time)
            out.append(replace(m, time=t))
    return out


def journal_hints(d, names) -> dict[str, str]:
    """Event name -> the Encounter Journal's line for damage dealers that names it ("Dig In increases Sszorak's
    damage taken during Howling Maelstrom."): the one-line 'do' of a boss row, for every boss (#28)."""
    out: dict[str, str] = {}
    for b in getattr(d, "role_bullets", None) or []:
        line = re.sub(r"[\[\]]", "", b).strip()
        for n in names:
            if n and n not in out and re.search(rf"(?<!\w){re.escape(n)}(?:e?s)?(?!\w)", line, re.I):  # "Shorerunners"
                out[n] = line
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
            add(start, Item("boss", "phase", name, f"{name} begins", PHASE_ICON))
    starts = [s for _n, s in d.phases if s >= 1]
    for w in (d.fight.invulnerable if d.fight is not None else []):
        at = next((s for s in starts if abs(s - w.start) <= 3), w.start)  # an intermission: on its phase's row
        secs = int(w.start + w.duration) - int(w.start)  # from the clock times shown
        add(at, Item("boss", "immune", "Boss immune", f"The boss is immune for {secs} s", IMMUNE_ICON,
                     float(w.duration)))
    cast_names = {n for n, _ts in d.boss_casts}
    for a in d.actions:  # a mechanic that can be you, at the times the logs give, when no boss cast already says it
        if a.kind == "mechanic" and a.name not in cast_names:
            for t in (getattr(d, "mech_times", None) or {}).get(a.name, []):
                add(t, Item("boss", "mech", a.name, f"{a.name} (it can be you)", _icon(d, a.name)))
    roles = getattr(d, "ability_roles", None) or {}
    hits_you = {why.removesuffix("'s damage") for _t, _s, why in _defensives(d)}
    hits_you |= {m.boss_ability for m in (d.defensives.moments if d.defensives else []) if m.boss_ability}  # any
    for name, times in d.boss_casts:
        # the journal flags it for the tank only (and you need no defensive for it): shown dimmed, never confirmed
        tank = roles.get(name) == ["tank"] and name not in hits_you
        if tank and len(times) >= 4:  # the tank's, often: one dim row, its rhythm said (round 38: 7 grey rows)
            gap = (times[-1] - times[0]) / (len(times) - 1)
            add(times[0], Item("boss", "tank", name, f"{name} (tank · {len(times)}× · ~{gap:.0f} s)",
                               _icon(d, name)))
            times = []
        for t in times:
            add(t, Item("boss", "tank" if tank else "cast", name, f"{name} (tank)" if tank else name, _icon(d, name)))
            if name in act:
                add(t, Item("you", "do", name, act[name].format(name), _icon(d, name)))
    kills: dict[int, list[tuple[str, str, float]]] = {}  # one "you" row a wave moment (DPS round 10: "Kill Burning
    # Venom at 0:24" and "Kill Shrouded Venom at 0:24", two rows for one wave)
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
            kills.setdefault(round(t), []).append((name, shown, t))  # by the second shown: 24.0 and 24.1 are one
    for _s, got in kills.items():
        t, ns = got[0][2], [(n, sh) for n, sh, _t in got]
        verbs = {act.get(n, "Kill {}") for n, _s in ns}
        if len(ns) > 1 and verbs == {"Kill {}"}:
            add(t, Item("you", "do", ns[0][0], "Kill " + " and ".join(sh for _n, sh in ns), _icon(d, ns[0][0])))
        else:
            for n, sh in ns:
                add(t, Item("you", "do", n, act.get(n, "Kill {}").format(sh), _icon(d, n)))
    for f in (d.fight.focus if d.fight is not None else []):
        add(f.start, Item("you", "do", f.name, f"Hit {f.name}", _icon(d, f.name)))
    if d.lust is not None:
        lust = 0.0 if d.lust < 1 else d.lust  # within a second of the pull: at the pull
        add(lust, Item("boss", "lust", "Bloodlust", "Your raid's Bloodlust", _icon(d, "Bloodlust"), LUST_SECONDS))
    _names, order, _ = simple._pressed(d)
    dur = _durations(d)
    for n in order:  # every press of the plan (Your job lists the main ones)
        pot = "potion" in n.lower()
        for t in order[n]:
            at = PRE if t < 0.5 and (n in d.precast or pot) else t
            add(at, Item("you", "pot" if pot else "cd", n, n, _icon(d, n), POTION_SECONDS if pot else dur.get(n, 0.0)))
    for t, s, why in _defensives(d):
        add(t, Item("you", "def", s, f"{s} for {why}" if why else f"{s} (the top players' defensive)",
                    _icon(d, s), dur.get(s, 0.0)))
    end = d.duration or (d.fight.duration if d.fight else 0)
    if end:
        add(end, Item("boss", "kill", "The kill", f"The kill, around {_mmss(end)}"))
    cuts = sorted(s for _n, s in d.phases if s >= 1)
    spans: list[list] = []  # back-to-back windows (one ends as the next starts) are one move
    for w in sorted(d.movement.windows if d.movement else [], key=lambda w: w.start):
        if spans and w.start - spans[-1][1] <= 1.0:
            spans[-1][1] = max(spans[-1][1], w.start + w.duration)
        else:
            spans.append([w.start, w.start + w.duration, w])
    for a, b, w in spans:  # the strategy's movement: a bar, never an event
        for s0, s1 in zip([a] + [c for c in cuts if a < c < b], [c for c in cuts if a < c < b] + [b], strict=True):
            add(s0, Item("boss", "move", "Movement", f"Movement, {int(s1) - int(s0)} s", MOVE_ICON,  # one form
                         float(s1 - s0)))  # (round 38: "Movement, 7 s" beside "Movement from 0:23 to 0:49")
            if MOVE_CUE <= s1 - s0 <= MOVE_LONG and w.spells:
                s = w.spells[0][0]
                add(s0, Item("you", "move", s, f"{s} for the move", _icon(d, s)))
    spawns = [t for t, it in out if it.kind == "adds"]
    imm = [(w.start, w.start + w.duration) for w in (d.fight.invulnerable if d.fight is not None else [])]
    for k, (t, it) in enumerate(out):  # a burst pressed while the boss is immune, just before its adds: on the adds
        if it.kind in ("cd", "pot") and any(a <= t < b for a, b in imm):
            s = next((s for s in spawns if t < s <= t + 6), None)
            if s is not None:
                it.t = s
                out[k] = (s, it)
    for t, it in out:
        if it.kind in ("cd", "pot") and t >= 5 and not _ctx(t, out, it.kind):
            it.why = _why(d, it.name, t, order.get(it.name, []))
    hints = journal_hints(d, {_clean(it.name) for _t, it in out if it.side == "boss"})
    told: set[str] = set()
    for _t, it in sorted(out, key=lambda x: x[0]):  # said once, on the first event it names (the cause first)
        named = it.side == "boss" and it.kind in ("cast", "mech", "adds", "phase")
        hint = hints.get(_clean(it.name), "") if named else ""
        if hint and hint not in told:
            it.hint = hint
            told.add(hint)
    starts = sorted(s for _n, s in d.phases if s >= 1)
    for k, (t, it) in enumerate(out):  # a boss event logged just before a phase starts belongs to that phase
        s = next((s for s in starts if s - 1.0 <= t < s), None)
        if s is not None and it.side == "boss" and it.kind != "phase":
            it.t = s
            out[k] = (s, it)
    return sorted(out, key=lambda x: (x[0], x[1].kind != "phase"))


def _why(d, name: str, t: float, presses: list[float]) -> str:
    """Why a press no boss event explains is there (issue #25): the plan's rule for it, or its cooldown coming back,
    then whether the top players press it then too or wait for another moment. Any spec, any boss."""
    from paf.prep_report import _key, rule_phrase, tops_moment

    plan = simple._plan(d)
    keys = {v: k for k, v in d.cd_names.items()}
    rule = plan.choice.get(keys.get(name, _key(name))) if plan is not None else None
    if rule is not None and rule.name not in ("default", "on_cooldown"):
        # the rule said on its first press after the pull only: the same words seven times read as noise (the
        # owner: less text)
        why = rule_phrase(d, rule.name) if not [x for x in presses if 5 <= x < t - 1] else ""
    else:
        before = [x for x in presses if x < t - 1]
        gaps = [b - a for a, b in zip(presses, presses[1:], strict=False)]
        why = "as soon as it is ready again" if before and gaps and t - before[-1] <= min(gaps) + 3 else \
            "when your rotation calls it"
    ts, n = d.tops_casts.get(_key(name)), d.tops_players
    if ts and n:
        here, there = tops_moment(ts, n, t)
        prev = [x for x in presses if x < t - 1]
        gaps = [b - a for a, b in zip(presses, presses[1:], strict=False)]
        if there is not None and there[1] < t and prev and gaps and there[1] < prev[-1] + min(gaps) - 3:
            there = None  # an earlier moment the cooldown cannot reach after the previous press: it is that
            # press's (a review: "earlier, at 1:37" on a 2:03 row whose previous press is 1:33)
        if there is not None and here < 0.25:
            when = "wait until" if there[1] > t else "press it earlier, at"  # a deviation said as one (a review:
            why += f"; {there[0]:.0%} of the top players {when} {_mmss(there[1])}"  # "press it at 1:37" on a 2:03 row)
        elif there is not None and there[0] >= here + 0.15:  # most press it a little apart: said, as Dig deeper's
            why += f"; {there[0]:.0%} of the top players press it at about {_mmss(there[1])}"  # warning (DPS c. 11)
        elif here >= 0.5:
            why += f"; {here:.0%} of the top players press it then"  # a share, not the rule's backing (DPS c. 8)
    return why.lstrip(";, ")  # a later press with no rule said: its top players' part alone


def moments(d) -> list[Moment]:
    """Events close in time share a row; a phase start always opens its own."""
    out: list[Moment] = []
    for t, it in items(d):
        if (not out or t - out[-1].t > ROW_GAP or (it.kind in ("phase", "kill") and t - out[-1].t > 0.5)
                or (it.side == "you" and it.kind == "cd" and t - out[-1].t >= 3)  # a press on its own time's row
                or (t < 0) != (out[-1].t < 0)):  # (round 39: the kill and Shadow Blades 1:40 on a 3:57 / 1:34 pill)
            out.append(Moment(t))
        out[-1].items.append(it)
    return out


def _phases(d, dur: float) -> list[tuple[str, float, float]]:
    ph = sorted(d.phases, key=lambda p: p[1]) or [("The fight", 0.0)]
    if ph[0][0].strip().lower() in ("", d.boss.lower()):  # a first phase named after the boss: say what it is
        ph[0] = ("Stage One" if len(ph) > 1 else "The fight", ph[0][1])
    total = {n: sum(1 for m, _ in ph if m == n) for n, _ in ph}
    seen: dict[str, int] = {}
    named = []
    for n, s in ph:  # a stage that comes back says so (the Sentinels' Stage One, between each Stasis)
        seen[n] = seen.get(n, 0) + 1
        named.append((n if total[n] == 1 else f"{n} ({seen[n]} of {total[n]})", s))
    return [(n, 0.0 if i == 0 else s, named[i + 1][1] if i + 1 < len(named) else dur) for i, (n, s) in enumerate(named)]



def _ic(icon: str, cls: str = "ic") -> str:
    if not icon:
        return f"<i class='{cls} none' aria-hidden='true'></i>"
    return (f"<i class='{cls}' aria-hidden='true' style=\"background-image:url('"
            f"{icons.CDN.format(size='medium', icon=icon)}')\"></i>")


def _ev(it: Item, row_t: float | None = None) -> str:
    bold = it.side == "you" and it.kind in ("cd", "pot", "def")
    text = f"<b>{e(it.text)}</b>" if bold else e(it.text)
    # any time its row does not show says so: the page never snaps an event to a time it does not have
    notes = [f"at {_mmss(it.t)}"] if (row_t is not None and it.t >= 1 and _mmss(it.t) != _mmss(row_t)
                                      and f"from {_mmss(it.t)}" not in it.text) else []
    if it.dur and it.kind not in ("move", "immune"):
        notes.append(f"lasts {it.dur:.0f} s")
    if it.why:
        notes.append(it.why)
    small = f"<small>{', '.join(notes)}</small>" if notes else ""
    if it.hint:
        small += f"<small class='hint' title='Journal: {e(it.hint)}'>&#128214; journal</small>"  # its words on hover
    return (f"<div class='ev ek-{it.kind}'>{_ic(it.icon)}<div class='x'><span class='main'>{text}</span>{small}"
            "</div></div>")


def _row(m: Moment, i: int, gap: float = 0.0) -> str:
    shown = [x for x in m.boss if x.kind != "phase"] or m.boss  # the phase's band says it, unless it is alone
    boss = "".join(_ev(x, m.t) for x in shown)
    you = "".join(_ev(x, m.t) for x in m.you)
    when = "Before the pull" if m.t < 0 else ("Pull" if m.t < 1 else _mmss(m.t))
    label = f"{when}, {m.title}: show this moment"
    quiet = not m.you and all(x.kind == "tank" for x in m.boss)  # grey: only the tank's, nothing for you
    cls = "fm quiet" if quiet else ("fm kill" if any(x.kind == "kill" for x in m.boss) else "fm")
    room = f" style='min-height:{min(110, max(0, (gap - ROW_GAP) * 2.2)) + 34:.0f}px'" if gap > ROW_GAP else ""
    return (f"<div class='{cls}{' has-boss' if boss else ''}' data-i='{i}' data-t='{m.t:g}' data-title='{e(m.title)}'"
            f"{room}>"
            f"<div class='boss'>{'<span class=vh>Boss: </span>' + boss if boss else ''}</div>"
            f"<div class='spine'><button type='button' class='t' aria-label='{e(label)}'>{e(when)}</button></div>"
            f"<div class='you'>{'<span class=vh>You: </span>' + you if you else ''}</div></div>")


def _cadence(ts: list[float]) -> str:
    """Press times as a player reads them: up to five listed; more, the run at one cadence then the rest listed
    (DPS round 17: "every 31 s (8 times)" hid the press held to 2:47 for the wave)."""
    shown = [_mmss(t) for t in ts]
    if len(ts) <= 5:
        return ", ".join(shown)
    gaps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
    step = sorted(gaps)[len(gaps) // 2]
    run = next((i for i, g in enumerate(gaps) if abs(g - step) > 3), len(gaps))  # the first gap off the cadence
    if run < 3:  # no steady start: every time
        return ", ".join(shown)
    rest = shown[run + 1:]
    return (f"{shown[0]}, then about every {step:.0f} s to {shown[run]}"
            + (f"; then {', '.join(rest)}" if rest else ""))


def job_html(d) -> str:
    """Your job on this boss, a dozen lines at most: what kills a raid first, then your cooldowns and when."""
    from paf.prep_report import rule_phrase

    def at(name: str) -> str:  # the waves of that unit, as the fight tab places them
        ts = [t for t, c, _l, n in d.waves if c and _clean(n) == name]
        return f" at {', '.join(_mmss(t) for t in ts)}" if ts else ""
    rows = [(a.name, f"<b>{e(a.text.split(':')[0].split(' (')[0])}</b>{at(a.name)}.") for a in d.actions
            if a.kind in ("kill", "contact") or (a.kind == "interrupt" and a.text.startswith("Interrupt"))][:2]
    kills = [a for a in d.actions if a.kind == "kill"][:2]
    if len(kills) == 2 and at(kills[0].name) and at(kills[0].name) == at(kills[1].name):  # one wave, two units:
        # one line (DPS round 11: "Kill the Shrouded Venom at 0:24, 1:48, 3:12", then the Burning Venom's same)
        kills.sort(key=lambda a: next((i for i, w in enumerate(d.waves) if _clean(w[3]) == a.name), 99))
        both = "Kill " + " and ".join(e(a.name) for a in kills)  # the timeline's words and order (DPS round 12)
        rows = [r for r in rows if r[0] not in {a.name for a in kills}]
        rows.insert(0, (kills[0].name, f"<b>{both}</b>{at(kills[0].name)}."))  # every line ends alike
    hints = {it.name: it.hint for _t, it in items(d) if it.hint}
    said = {_clean(a.name) for a in d.actions}
    skip = {a.name for a in d.actions if a.kind == "ignore"}
    for _t, c, _l, n in d.waves:  # adds the fight has but no action names (Nymrissa's murlocs): kill them
        name = _clean(n)
        if len(rows) < 2 and c and name not in said and name not in skip and n not in skip:
            said.add(name)
            why = next((h for k, h in hints.items() if name.lower() in h.lower()), "")
            many = any(c2 > 1 for _t2, c2, _l2, n2 in d.waves if _clean(n2) == name) and not name.endswith("s")
            rows.append((n, f"<b>Kill the {e(name)}{'s' if many else ''}</b>{at(name)}."))  # the why: on the rows
            hints = {k: h for k, h in hints.items() if h != why}
    imm = d.fight.invulnerable if d.fight is not None else []
    for w in imm[:1]:
        adds = [_clean(x[3]) for x in d.waves if w.start - 2 <= x[0] <= w.start + w.duration and x[1]]
        what = f": your damage goes on the {e(adds[0])}" if adds else ""
        shown = [int(x.start + x.duration) - int(x.start) for x in imm]  # from the times shown, so "1:41 to 2:40"
        lo, hi = min(shown), max(shown)  # reads 59 s (DPS round 13: "(58 s)")

        long = _span(lo) if lo == hi else f"{_span(lo)} to {_span(hi)} each"  # every time (the Sentinels: three)
        if len(imm) == 1:
            when = f"from {_mmss(w.start)} to {_mmss(w.start + w.duration)}"
        else:
            when = f"at {', '.join(_mmss(x.start) for x in imm)}"
        rows.append((IMMUNE_ICON, f"<b>Boss immune</b> {when} ({long}){what}."))
    if len(rows) < 2:  # the journal's lines for damage dealers about this fight's events (Sszorak: Dig In)
        done = {r[0] for r in rows}
        for _t, it in items(d):
            if it.hint and it.hint in hints.values() and it.name not in done and len(rows) < 3:
                done.add(it.name)
                times = [_mmss(max(0.0, x)) for x, y in items(d) if y.side == "boss" and y.name == it.name]
                rows.append((it.name, f"<b>{e(_clean(it.name))}</b> at {', '.join(times[:5])}: {e(it.hint)} "
                                      "<span class='src'>(Journal)</span>"))  # the job itself: its words stay here
    defs = _defensives(d)
    if defs:
        s, why = defs[0][1], defs[0][2]
        at = ", ".join(_mmss(t) for t, x, _w in defs if x == s)  # every time the fight tab calls it
        rows.append((s, f"<b>{e(s)}</b> at {at}{' for ' + e(why.removesuffix(chr(39) + 's damage')) if why else ''}, "
                        "the top players' defensive."))
    wins = d.movement.windows if d.movement else []
    for t, it in items(d):  # a mobility spell the fight tab calls for a move: said, with who presses it
        if it.side == "you" and it.kind == "move":
            share = next((sh for w in wins if abs(w.start - t) <= 1.5 for n, sh in w.spells if n == it.name), None)
            who = f": {share:.0%} of the top players press it there" if share else ""
            rows.append((it.name, f"<b>{e(it.name)}</b> for the move at {_mmss(t)}{who}."))
    names, _order, _held = simple._pressed(d)
    order: dict[str, list[float]] = {}  # the times the fight view calls (a burst moved onto its adds included)
    for t, it in items(d):
        if it.side == "you" and it.kind in ("cd", "pot"):  # every press of the plan, as the fight tab calls them
            order.setdefault(it.name, []).append(0.0 if t < 0 else t)
    names = list(order)
    plan = simple._plan(d)
    rules = {d.cd_names.get(k, k): r.name for k, r in (plan.choice.items() if plan else []) if r.name != "default"}
    if d.lust is not None and d.lust < 5 and names:
        rows.append(("Bloodlust", "<b>Bloodlust at the pull</b>: your opener goes inside it."))
    for n in sorted((n for n in names if n in order), key=lambda n: min(order[n])):  # in the order you first press them
        pre = [t for t in order[n] if t < 0.5 and (n in d.precast or "potion" in n.lower())]
        rest = [_mmss(t) for t in order[n] if t not in pre]
        when = _cadence([t for t in order[n] if t not in pre])  # a long list: its cadence, never cut (DPS 16-17)
        if pre:
            when = "before the pull" + (f", then {when}" if rest else "")
        elif rest:
            when = f"at {when}"
        if all(t < 5 for t in order[n]) and "potion" not in n.lower():  # a short cooldown: the opener, then rotation
            when += ", then with your rotation"
        why = f": {rule_phrase(d, rules[n])}" if n in rules else ""
        same = next((r for r in rows if isinstance(r[0], list) and r[2] == (when, why)), None)
        if same is not None:  # pressed together, by the same rule: one line, both icons (Ancestral Call and
            same[0].append(n)  # Ascendance at 0:51, 2:52: the ninth line cut Ascendance off; a review)
            continue
        rows.append(([n], None, (when, why)))
    rows = [((r[0][0], f"<b>{e(_and_names(r[0]))}</b> {e(r[2][0])}{e(r[2][1])}.", r[0]) if isinstance(r[0], list)
             else (*r, None)) for r in rows]
    if not rows:
        return ""
    def pics(ic, many) -> str:  # a line's icon, or its cooldowns' side by side
        if many and len(many) > 1:
            return "<span class='ics2'>" + "".join(_ic(_icon(d, x)) for x in many) + "</span>"
        return _ic(ic if ic == IMMUNE_ICON else _icon(d, ic) if ic else "")
    lis = "".join(f"<li>{pics(ic, many)}<span>{txt}</span></li>" for ic, txt, many in rows[:12])  # every cooldown
    return f"<section class='fbox job'><h2>Your job on this boss</h2><ul class='keys'>{lis}</ul></section>"


def _and_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _ctx(t: float, its: list[tuple[float, Item]], kind: str = "def") -> str:
    """What a press is for, in a few words: on the pull, on the boss event it answers, inside Bloodlust. A boss cast
    is a reason for a defensive only (DPS round 17: "Shadow Blades - on Malignant Catalyst", a raid-wide hit)."""
    if t < 0:
        return "before the pull"
    if t < 1:
        return "on the pull"
    if t < 5:
        return "just after the pull"
    # a press answers an add wave, an immunity or a stage up to 8 s after it starts, a boss cast only within 3 s
    near = [x for at, x in its if x.side == "boss" and x.kind in ANCHORS and (x.kind != "cast" or kind == "def")
            and t - (3 if x.kind == "cast" else 8) <= at <= t + (2 if x.kind == "adds" else 1)]  # pressed as the
    # wave lands (0:51 for a 0:52.7 wave: its hold rule said nothing there; a review)
    if near:
        order = ("adds", "cast", "immune", "phase")  # what you press it for, the most concrete first
        x = min(near, key=lambda x: (order.index(x.kind), abs(x.t - t)))
        return ("on the " + x.text if x.kind == "adds" else "when it starts" if x.kind == "phase" else
                "when the boss goes immune" if x.kind == "immune" else "on " + x.text)
    return ""


PULL = {"t": 0, "n": "The pull", "k": "pull", "p": 0, "ic": ""}  # a pull timer that runs late: confirm the pull


def _t1(t: float) -> float:
    """A time to a tenth, cut and not rounded: 201.98 s stays 3:21 on every surface (MRT note, job card, page)."""
    return int(t * 10) / 10


def data(d, ms: list[Moment], dur: float) -> dict:
    """What the page's script needs, each event at its own time on the plan's clock."""
    its = items(d)
    phases = _phases(d, dur)

    def ph(t: float) -> int:
        return max((i for i, p in enumerate(phases) if t >= p[1] - 0.5), default=0)

    phase_starts = [s for _n, s, _e in phases[1:]]
    acts = [{"t": _t1(t), "n": x.text, "k": x.kind, "ic": x.icon, "d": round(x.dur, 1),
             "c": "" if x.kind == "move" else (_ctx(t, its, x.kind)
                                               or ("default list timing" if x.kind == "cd" else "")),
             "w": x.why}
            for t, x in its if x.side == "you"]
    acts.sort(key=lambda a: (a["t"], YOU_ORDER.index(a["k"])))
    return {
        "end": round(dur, 1),
        "phases": [[n, _t1(s), _t1(t)] for n, s, t in phases],
        "rows": [_t1(m.t) for m in ms],
        "acts": acts,
        "anchors": [PULL] + [{"t": _t1(t), "n": x.name if x.kind in ("phase", "immune") else x.text, "k": x.kind,
                     "p": ph(t), "ic": x.icon} for t, x in its if x.side == "boss" and x.kind in ANCHORS and t >= 1
                    and not (x.kind != "phase" and any(abs(t - s) <= 1 for s in phase_starts))],
        "boss": [{"t": _t1(t), "d": round(x.dur, 1), "n": x.text, "k": x.kind, "ic": x.icon} for t, x in its
                 if x.side == "boss" and x.kind not in ("phase",)],
        "strips": [{"t": _t1(t), "d": round(x.dur, 1), "k": x.kind, "side": x.side, "n": x.name}
                   for t, x in its if x.dur and x.kind in ("cd", "pot", "def", "lust", "adds", "move", "immune")],
    }


def mrt(d) -> str:
    """The MRT note of what the fight view calls: the same presses at the same times, from the same source."""
    plan = simple._plan(d)
    want = plan.objective if plan is not None else "boss"
    note = d.mrt.get(want) or next(iter(d.mrt.values()), "")
    if not note:
        return ""
    head = note.splitlines()[0]
    if plan is not None and (not any(r.name != "default" for r in plan.choice.values()) or plan.gain <= 2 * plan.error):
        head = re.sub(r"cooldowns for .*\(\+?-?\d+\.\d%\)", "cooldowns: SimC's default priority list", head)
    return "\n".join([head, *note_lines(d)])


def prepull(lines: list[str]) -> list[str]:
    """MRT fires {time:0:00} at the pull: the presses before it go on one plain line under the header."""
    pre = [re.sub(r"^\{time:0:00\} | - before the pull$", "", x) for x in lines if x.endswith(" - before the pull")]
    rest = [x for x in lines if not x.endswith(" - before the pull")]
    return ([f"Before the pull: {', '.join(pre)}"] if pre else []) + rest


def note_lines(d, kinds: tuple[str, ...] = ("cd", "pot", "def", "move")) -> list[str]:
    """The MRT lines of the presses the fight tab shows (of these kinds), each with what it is for."""
    its = items(d)
    lines = []
    for t, it in its:
        if it.side != "you" or it.kind not in kinds:
            continue
        c = _ctx(t, its, it.kind)
        said = c.replace("on the ", "").replace("on ", "") if c else ""
        why = " - " + c if c and c not in ("on the pull", "just after the pull") and said not in it.text else ""
        lines.append(f"{{time:{_mmss(max(0.0, t))}}} {it.text}{why}")
    return prepull(lines)


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
    said += [f"everyone moves from {_mmss(t)} to {_mmss(t + x.dur)}" for t, x in mine
             if x.kind == "move" and x.dur >= MOVE_CUE]  # the stage's movement worth a word, with its times
    said.sort(key=lambda s: [int(v) for v in re.findall(r"(\d+):(\d\d)", s)[:1][0]] if re.search(r"\d+:\d\d", s)
              else [0, 0])
    lust = [t for t, x in mine if x.kind == "lust"]
    if lust:
        said.insert(0, "Bloodlust " + ("at the pull" if lust[0] < 5 else f"at {_mmss(lust[0])}"))
    short = bool(mine) and all(x.kind in ("immune", "phase") for _t, x in mine)  # an immunity alone: its row says it
    adv = f"<p class='ph-adv'>{e(cap('; '.join(said)))}.</p>" if said and not short else ""  # in time order
    span = _span(int(end) - int(start))  # from the clock times shown (DPS round 13: "1:41" lasting "1 min 42 s")
    m = re.fullmatch(r"(.*) \((\d+ of \d+)\)", name)
    title = f"{e(m[1])} <span class='rep'>({m[2]})</span>" if m else e(name)
    return (f"<section class='stl{' short' if short else ''}' aria-labelledby='ph{pi}-h'><div class='ph-band' "
            f"id='ph{pi}'><div class='ph-name'><h2 id='ph{pi}-h'>{title}</h2><span>{lasts}lasts about {span}.</span>"
            f"</div>{adv}<div class='ph-lanes' aria-hidden='true'>{lanes}</div></div>{rows}</section>")


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


LEGEND_KINDS = (("cd", "your cooldown"), ("pot", "your potion"), ("def", "your defensive"), ("lust", "Bloodlust"),
                ("adds", "adds alive"), ("move", "everyone moves"), ("immune", "boss immune"))


def legend(its: list) -> str:
    """The legend of the bars this fight has, none other."""
    kinds = {x.kind for _t, x in its if x.dur}
    spans = "".join(f"<span><i class='s-{k}'></i>{label}</span>" for k, label in LEGEND_KINDS if k in kinds)
    grey = "<span>grey = the tank's</span>" if any(x.kind == "tank" for _t, x in its) else ""
    # the rows are not spaced to scale: a bar runs down to its end's row, not a length in seconds (a review)
    return f"<div class='fv-legend' aria-hidden='true'>{spans}{grey}</div>"  # a bar's end: its row (review 36)


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
            "<h3 id='c-title'></h3><dl class='who'><dt>Fight</dt><dd id='c-boss'></dd><dt>You</dt>"
            "<dd class='yd' id='c-you'></dd></dl><div class='call' id='c-call'></div><p class='then' id='c-then'></p>"
            "<div class='nb'><p><span id='c-next'></span><b id='c-in'></b></p>"
            "<div class='meter'><i id='c-meter'></i></div></div>"
            f"{_btn('c-sync', '', 'Control+Shift+Space', hidden=True)}"
            f"<div class='foot'>{_btn('ss-open', 'Second screen', cls='btn ghost')}{copy}</div></section>"
            f"{job_html(d)}</aside>")  # no pointer to the Dig deeper tab: it is right there (review 36)


def _second_screen(d) -> str:
    return (f"<dialog class='ss' id='ss' aria-label='{e(d.boss)}, second screen' tabindex='-1'>"
            f"<div class='ss-top'><h2><span id='ss-h'>{e(d.boss)}</span> {theme.diff_pill(d.difficulty)}</h2>"
            "<span class='ss-clock' id='ss-clock'>0:00</span><span class='ss-phase' id='ss-phase'></span>"
            "<span class='ss-boss' id='ss-boss' aria-label='Boss'></span>"
            f"{_btn('ss-close', 'Back to the plan', 'Escape')}</div>"
            "<div class='ss-mid'><div class='call' id='ss-call'></div><p class='ss-you' id='ss-you'></p>"
            "<p class='then' id='ss-then'></p>"
            "<div class='bars' id='ss-bars' role='list' aria-label='Coming up'></div></div>"
            f"<div class='ss-bot'><div class='grp'>{_btn('ss-play', 'Play', cls='btn primary')}"
            f"{_btn('ss-pull', 'Start at 10 on the pull timer', 'Alt+P')}"
            f"{_btn('ss-sync', '', 'Control+Shift+Space', hidden=True)}</div>"
            f"<div class='grp'>{_btn('ss-sound', 'Voice and beeps', cls='btn ghost', more=' aria-pressed=false')}"
            f"{_btn('ss-wipe', 'Wipe, back to the pull', cls='btn ghost')}</div></div></dialog>")


def kill_switch(d) -> str:
    """The kill times this boss is planned for (issue #26), one sheet each: the fight, the plan's presses and the
    notes are those of that kill time."""
    kt = getattr(d, "kill_times", None) or []
    if len(kt) < 2:
        return ""
    now = getattr(d, "kill_now", 0)
    links = "".join(
        f"<a href='{e(f)}#fight' class='ks{' on' if i == now else ''}'{' aria-current=page' if i == now else ''}>"
        f"<b>{_mmss(t)}</b><small>{e(who)}</small></a>" for i, (who, t, f) in enumerate(kt))
    return (f"<nav class='kill-switch' aria-label='Plan for a kill of'><span class='ks-lab'>Plan for a kill of</span>"
            f"{links}<span class='ks-hint' title='Slower than {_mmss(kt[-1][1])}: take {_mmss(kt[-1][1])}, its later "
            f"timings then approximate'>the closest to your kill</span></nav>")  # the rest on hover (review 36)


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
    return (f"<div class='fv'><a class='skip' href='#tl'>Skip to the fight</a>{kill_switch(d)}"
            f"<div class='sheet-fv'>{_side(d)}"
            f"<section class='ftl' id='tl' tabindex='-1' aria-label='The fight'>{legend(its)}{''.join(sections)}"
            f"<div class='tl-end'></div></section></div>{_second_screen(d)}"
            "<p class='vh' id='sr' aria-live='polite' aria-atomic='false'></p>"
            f"<script>var FV={payload};</script><script>{JS}</script></div>")


CSS = theme.style("fightview")
JS = files("paf").joinpath("scripts", "fightview.js").read_text(encoding="utf-8")
