"""The fight view of a prep sheet: what to do and when, before and during the pull.

The plan in a sentence (when you burst, the boss immune, your defensives) beside the opener; then the fight on one
clock, a lane a row: the raid's windows (phases, Bloodlust, the boss immune, everyone moving), yours (a lane a spell,
a bar as long as it lasts; a lane a unit you kill), then the boss's spells that concern you (one you answer, one that
may target you, one the journal tells damage dealers about), the rest a dot each; each mark's details on hover.
Below: where your plan and the top players differ, and the MRT note. The live view (one button, L) follows the pull
on a second screen: a big clock, what to press now and then, what runs, the next minute, the timeline's playhead.

Everything comes from the prep (generic across specs, PRODUCT.md): the boss's spells and add waves at the top raids'
typical times, the strategy's movement, your cooldown plan (paf.optimize), your defensives (paf.defensives) and what
the top players do on the boss (paf.actions). During the pull, one press ("it starts now") moves the moments still to
come by the boss's delay, so the live view follows a raid that is ahead or behind the plan.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html import escape as e
from importlib.resources import files

from paf import icons, simple, theme
from paf.pulllog import BIG_CD

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
    said_dur: bool = False  # its text says its length(s) already (two waves at one moment, one row)
    hint: str = ""  # a boss event: the Encounter Journal's line for damage dealers that names it


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
                add(t, Item("boss", "mech", a.name, f"{a.name} · you?", _icon(d, a.name)))
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
        dur = float(min(life or 0, max(0.0, stop - t)))
        same = next((x for tt, x in out if x.kind == "adds" and round(tt) == round(t)), None)
        if same is not None:  # another wave at that moment: one row, each with its length (fresh DPS review: two
            if not same.said_dur:  # rows for the 0:24 venoms); each unit never split across lines (no-break spaces)
                same.text, same.said_dur = f"{same.text} ({same.dur:.0f} s)".replace(" ", "\u00a0"), True
            same.text += " · " + f"{label} ({dur:.0f} s)".replace(" ", "\u00a0")
            same.dur = max(same.dur, dur)
        else:
            add(t, Item("boss", "adds", name, label, _icon(d, name), dur))
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
        elif it.kind in ("cd", "pot") and t >= 5:  # a press with its reason on the row: the top players' other
            # moment still said, as Dig deeper warns (fresh DPS review: Shadow Blades 3:20, the top players 3:13)
            it.why = _tops_off(d, it.name, t, order.get(it.name, []))
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
        hold = re.fullmatch(r"hold_(adds|vulnerable)_(\d+)", rule.name)  # Your job's badge words (round 46)
        why = ((f"hold ≤{hold[2]} s for {'adds' if hold[1] == 'adds' else 'the damage amp'}" if hold else
                rule_phrase(d, rule.name)) if not [x for x in presses if 5 <= x < t - 1] else "")
    else:
        before = [x for x in presses if x < t - 1]
        gaps = [b - a for a, b in zip(presses, presses[1:], strict=False)]
        why = "◷ on cooldown" if before and gaps and t - before[-1] <= min(gaps) + 3 else \
            "when your rotation calls it"
    ts, n = d.tops_casts.get(_key(name)), d.tops_players
    if ts and n:
        here, there = tops_moment(ts, n, t)
        prev = [x for x in presses if x < t - 1]
        gaps = [b - a for a, b in zip(presses, presses[1:], strict=False)]
        if there is not None and there[1] < t and prev and gaps and there[1] < prev[-1] + min(gaps) - 3:
            # an earlier moment the cooldown cannot reach after the previous press: not "press it earlier" (a
            # review: "earlier, at 1:37" on a 2:03 row whose previous press is 1:33), but said when few press it
            # here: the top players run a cycle ahead (fresh DPS review: Shadow Blades 3:20, them 3:13)
            if here < 0.25 and abs(there[1] - t) < abs(there[1] - prev[-1]):  # theirs, not the previous press's
                # (fresh DPS review: Ancestral Swiftness 2:03 flagged for the 1:37 of its own 1:33 press)
                why += (f"; ⚠ {there[0]:.0%} of the top players at about {_mmss(there[1])} (their cycle runs "
                        f"~{t - there[1]:.0f} s ahead)")
            there = None
        if there is not None and here < 0.25:
            when = "wait until" if there[1] > t else "press it earlier, at"  # a deviation said as one (a review:
            why += f"; {there[0]:.0%} of the top players {when} {_mmss(there[1])}"  # "press it at 1:37" on a 2:03 row)
        elif there is not None and there[0] >= here + 0.15:  # most press it a little apart: said, as Dig deeper's
            why += f"; {there[0]:.0%} of the top players press it at about {_mmss(there[1])}"  # warning (DPS c. 11)
        elif here >= 0.5:
            why += f"; {here:.0%} of the top players press it then"  # a share, not the rule's backing (DPS c. 8)
    return why.lstrip(";, ")  # a later press with no rule said: its top players' part alone


def _tops_off(d, name: str, t: float, presses: list[float] | None = None) -> str:
    """Most top players press it at another moment close by, few at this one (prep_report.off_tops' rule); a moment
    nearer another of your presses is that press's, not this one's."""
    from paf.prep_report import _key, tops_moment

    ts, n = d.tops_casts.get(_key(name)), d.tops_players
    if not ts or not n:
        return ""
    here, there = tops_moment(ts, n, t)
    if there is None or here >= 0.25 or any(abs(there[1] - x) < abs(there[1] - t) for x in presses or []
                                             if abs(x - t) > 1):
        return ""
    return f"⚠ {there[0]:.0%} of the top players at about {_mmss(there[1])}"


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


# a cooldown plan's rule as Your job's badge (its sentence on the badge's hover)
RULE_BADGE = {"add_waves": "adds only", "secondary_targets": "burst targets only", "vulnerable_windows": "in the amp",
              "lust_pi": "with Bloodlust", "on_cooldown": "on cooldown", "not_before_move": "not before a move"}


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
    shown = {"Space": "Space", "Alt+P": "Alt P", "Control+Shift+Space": "Ctrl ⇧ Space", "Escape": "Esc", "L": "L"}
    kbd = f"<kbd aria-hidden='true'>{shown[keys]}</kbd>" if keys else ""
    attrs = (f" aria-keyshortcuts='{keys}'" if keys else "") + (" hidden" if hidden else "") + more
    return f"<button type='button' class='{cls}' id='{id_}'{attrs}><span>{label}</span>{kbd}</button>"


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def opener_html(d) -> str:
    """The opener as a guide writes it (issue #39; the owner, 2026-10-26: "hard to read", a strip of 40 s of rotation
    and Shuriken Storm among the cooldowns): what you cast before the pull, then your presses in order, numbered,
    up to your last big cooldown (a press of BIG_CD s or more, from the game data, the potion, an item), those framed;
    then "your rotation". Each press's time under it, its name on hover. What a guide adds (issue #41, "how many
    shards at the Tyrant, must the dogs be out?"): the resource you hold on a spender's or a big cooldown's icon,
    the icons of what of yours is up under a big cooldown; and what the list presses in your cooldowns and between."""
    plan = simple._plan(d)
    if plan is None:
        return ""
    default = simple.plays_default(d)
    casts = getattr(plan, "default_opener" if default else "opener", None) or []
    if not casts:
        return ""
    notes = getattr(plan, "default_notes" if default else "notes", None)
    try:
        from paf.gamedata import spell_cooldowns

        cds = spell_cooldowns()
    except Exception:  # noqa: BLE001 - offline: the potion and the items only
        cds = {}
    items = {n for k, n in d.cd_names.items() if k.startswith("use_item")}

    def big(n: str, sid: int) -> bool:
        return "potion" in n.lower() or n in items or (cds.get(sid) or (0.0,))[0] >= BIG_CD
    pre = [(n, sid) for t, n, sid in casts if t < 0]
    seq = [(t, n, sid) for t, n, sid in casts if t >= 0]
    last = max((k for k, (_t, n, sid) in enumerate(seq) if big(n, sid)), default=-1)
    shown = seq[:max(last + 2, 6)][:18]  # to the last big cooldown and one press after, a short opener at least
    res = notes.resource if notes else ""

    def cell(k: int, t: float | None, n: str, sid: int) -> str:
        when = "pre-pull" if t is None else _mmss(t)
        hover, extra = [n, when], ""
        st = notes.at.get((round(t, 3), sid)) if notes and t is not None else None
        if st and st.res is not None and (st.spends or (big(n, sid) and st.res)):
            hover.append(f"{st.res} {res}")
            extra += f"<b class='res'>{st.res}</b>"
        if st and big(n, sid) and st.up:
            up = [notes.names.get(x, "") for x in st.up][:4]
            hover.append("with " + ", ".join(x for x in up if x))
            extra += "<span class='up'>" + "".join(_ic(_icon(d, x), "ic up") for x in up) + "</span>"
        return (f"<li class='{'big' if big(n, sid) else ''}' title='{e(' · '.join(hover))}'>{_ic(_icon(d, n))}"
                f"<small>{'' if k < 0 else k}</small><em>{when}</em>{extra}</li>")
    lust = (" <span class='pill'>in Bloodlust</span>" if d.lust is not None and d.lust < 5 else "")
    key = (f"; the number on an icon: your {res} as you press it" if res else "")
    return (f"<section class='opseq' aria-label='The opener'><h2 title='Framed: your big cooldowns, under them what of "
            f"yours is up{e(key)}'>Opener{lust} <span class='muted small'>as SimC plays it</span></h2><ol>"
            + "".join(cell(-1, None, n, sid) for n, sid in pre)
            + "".join(cell(k + 1, t, n, sid) for k, (t, n, sid) in enumerate(shown))
            + "<li class='then'>then your rotation</li></ol>" + _burst_html(d, notes) + "</section>")


def _burst_html(d, notes) -> str:
    """Two rows: what the list presses more in your big cooldowns, and more between them (issue #41: "what do I do
    in the burst phases and without them?"), each spell's share of the presses there."""
    sp = notes.split if notes else None
    if not sp or not (sp.inside or sp.outside):
        return ""

    def row(label: str, hint: str, side) -> str:
        cells = "".join(f"<li title='{e(notes.names.get(sid, ''))} · {c:.0%} of your presses {hint}'>"
                        f"{_ic(_icon(d, notes.names.get(sid, '')))}<em>{c:.0%}</em></li>" for sid, _a, c in side)
        return f"<div class='bs-row'><span class='bs-h'>{label}</span><ul>{cells}</ul></div>" if cells else ""
    return ("<div class='bs'>" + row("In your cooldowns", "in them", sp.inside)
            + row("Between them", "between them", sp.outside) + "</div>")


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




# --- the fight on one screen (the owner, 2026-11-12: "a big wall"; a horizontal timeline chosen among four mockups) ---

TRACK_PX = 1040  # the timeline's track at a desktop width: what a time label has room for
LABEL_PX = 62  # a press's time is printed when the next press of its lane is at least this far
FOLD_OFFSET = 1.5  # a boss cast at the same offset (± this) into every wave of one add is part of that wave
SAME_BURST = 3.0  # presses this close are one burst (the sentence on top)
MOVE_SHOWN = 30.0  # longer moving windows are the fight's rhythm (a boss kited around), not a reposition: not drawn
ANSWER_BEFORE, ANSWER_AFTER = 10.0, 6.0  # a defensive this long before (after) a cast answers that one
MOVE_CAUSE = (4.0, 2.0)  # a boss spell up to 4 s before a move's start, or 2 s after, is what starts it


@dataclass
class Mark:
    t: float
    dur: float = 0.0
    icon: str = ""
    tip: str = ""
    label: str = ""  # its time, or "pre"
    count: str = ""  # an add wave's count
    flag: bool = False  # the plan holds it, or the top players press it elsewhere
    tops: float | None = None  # where most top players press it, when elsewhere
    move: tuple[float, float] | None = None  # a boss cast's: the move it starts


@dataclass
class Lane:
    kind: str  # you: cd, pot, def, move, do, kill; boss: key, journal
    names: list[str]
    icons: list[str]
    sub: str = ""
    marks: list[Mark] = field(default_factory=list)


@dataclass
class Timeline:
    end: float
    phases: list[tuple[str, float, float]]
    lust: list[tuple[float, Item]]
    immune: list[tuple[float, Item]]
    moves: list[tuple[float, float, Item | None]]  # the repositions no boss cast starts (those are on its lane)
    you: list[Lane]
    boss: list[Lane]
    others: list[tuple[float, Item]]  # the other boss casts: a dot each
    tank: list[str]  # the tank's spells, hidden for a damage dealer


def _answers(it: Item) -> str:
    """The boss event a press of yours answers ("Feint for Ravenous Feast": Ravenous Feast)."""
    m = re.search(r"\bfor (.+)$", it.text)
    if not m or m[1] == "the move":
        return ""
    return m[1].removesuffix("'s damage").strip()


def _tops_at(why: str) -> float | None:
    m = re.search(r"at about (\d+):(\d\d)", why or "")
    return int(m[1]) * 60 + int(m[2]) if m else None


def _say_why(why: str) -> str:
    """A press's reason as a sentence for its hover."""
    parts = [x.strip() for x in (why or "").split(";") if x.strip()]
    parts = ["SimC presses it on cooldown" if x == "◷ on cooldown" else x.replace("⚠ ", "") for x in parts]
    return ". ".join(cap(x) for x in parts)


def _moves(boss: list[tuple[float, Item]], end: float) -> list[list[float]]:
    """The repositions: the moving windows merged (a move cut at a stage's start is one), the long ones left out."""
    moves: list[list[float]] = []
    for t, x in sorted(((t, x) for t, x in boss if x.kind == "move"), key=lambda p: p[0]):
        if moves and t <= moves[-1][1] + 0.5:
            moves[-1][1] = max(moves[-1][1], min(end, t + x.dur))
        else:
            moves.append([t, min(end, t + x.dur)])
    return [m for m in moves if m[1] - m[0] <= MOVE_SHOWN]


def move_cause(t: float, boss: list[tuple[float, Item]]) -> Item | None:
    """The boss spell that starts a move at t: a cast or a mechanic just before it (or as it starts), else an add
    wave; none when nothing comes then (the owner: "everyone moves" says nothing)."""
    near = [(x.kind == "adds", abs(s - t), x) for s, x in boss
            if x.kind in ("cast", "mech", "adds") and t - MOVE_CAUSE[0] <= s <= t + MOVE_CAUSE[1]]
    return min(near, key=lambda p: p[:2])[2] if near else None


def move_tip(a: float, b: float, cause: Item | None) -> str:
    said = f"The top players move {_mmss(a)} to {_mmss(b)} ({b - a:.0f} s)"
    return f"{_clean(cause.name)}: {said[0].lower()}{said[1:]}" if cause else f"{said}\nNo boss spell starts it"


def timeline(d) -> Timeline | None:
    """The fight as lanes (generic, every boss): yours first, a lane a spell (spells always pressed together share
    one), a lane a unit you kill; then the boss's spells that concern you (one you answer, one that may target you,
    one the journal tells damage dealers about); the rest a dot each, the tank's hidden."""
    end = d.duration or (d.fight.duration if d.fight else 0)
    if not end:
        return None
    its = [(t, x) for t, x in items(d) if t <= end + 0.5 and x.kind != "kill"]
    boss = [(t, x) for t, x in its if x.side == "boss"]
    mine = [(t, x) for t, x in its if x.side == "you"]
    moves = [(a, b, move_cause(a, boss)) for a, b in _moves(boss, end)]
    moved: dict[str, list[tuple[float, float]]] = {}  # a boss cast that makes you move: its lane, the move under it
    for a, b, c in moves:
        if c is not None and c.kind in ("cast", "mech"):
            moved.setdefault(c.name, []).append((a, b))
    waves = [{"t": t, "it": x, "name": _clean(x.name), "dur": min(x.dur, end - t), "mine": False, "with": []}
             for t, x in boss if x.kind == "adds"]
    answered = {_answers(x) for _t, x in mine} - {""}
    casts: dict[str, list[tuple[float, Item]]] = {}
    for t, x in boss:
        if x.kind in ("cast", "mech"):
            casts.setdefault(x.name, []).append((t, x))
    for name, occ in casts.items():  # a cast that comes with every wave of one add, at one offset: the wave's
        if name in answered or name in moved or occ[0][1].kind == "mech" or len(occ) < 2:
            continue
        offs = []
        for t, _x in occ:
            w = max((w for w in waves if w["t"] - 1 <= t <= w["t"] + w["dur"] + 5), key=lambda w: w["t"], default=None)
            offs.append((w, t - w["t"]) if w else None)
        if all(offs) and len({w["name"] for w, _o in offs}) == 1 and \
                max(o for _w, o in offs) - min(o for _w, o in offs) <= FOLD_OFFSET:
            for w, o in offs:
                w["with"].append((name, o))
            casts[name] = []
    boss_lanes, others = [], []
    for name, occ in casts.items():
        if not occ:
            continue
        key = name in answered or name in moved or any(x.kind == "mech" for _t, x in occ)
        hint = next((x.hint for _t, x in occ if x.hint), "")
        if not key and not hint:
            others += occ
            continue
        by = sorted({x.name for _t, x in mine if _answers(x) == name})
        lane = Lane("key" if key else "journal", [name], [occ[0][1].icon])
        answered_ = 0
        for t, x in occ:
            now = [(y.name, at - t) for at, y in mine if _answers(y) == name
                   and t - ANSWER_BEFORE <= at <= t + ANSWER_AFTER]
            answered_ += bool(now)
            said = ", ".join(f"{n} ({'at its cast' if abs(o) < 1 else f'{abs(o):.0f} s '}"
                             f"{'' if abs(o) < 1 else 'before' if o < 0 else 'after'})" for n, o in now)
            tip = [f"{name} · {_mmss(t)}"] + ([f"You answer with {said}"] if now else
                                              ["Your plan has no defensive for this one"] if by else
                                              ["It may target you"] if x.kind == "mech" else [])
            mv = next(((a, b) for a, b in moved.get(name, []) if t - MOVE_CAUSE[1] <= a <= t + MOVE_CAUSE[0]), None)
            tip += [f"You move {_mmss(mv[0])} to {_mmss(mv[1])} ({mv[1] - mv[0]:.0f} s), as the top players do"] if mv \
                else []
            tip += [hint] if hint else []
            lane.marks.append(Mark(t, icon=x.icon, tip="\n".join(tip), label=_mmss(t), flag=bool(by) and not now,
                                   move=mv))
        secs = sorted(b - a for a, b in moved.get(name, []))
        lane.sub = "\n".join(filter(None, [
            f"you: {', '.join(by)}" + (f" ({answered_} of {len(occ)})" if answered_ < len(occ) else "") if by else "",
            f"you move {secs[len(secs) // 2]:.0f} s" + (f" ({len(secs)} of {len(occ)})" if len(secs) < len(occ) else "")
            if secs else "",
            "may target you" if key and not by and not secs else "",
            "in the journal" if not key else ""]))
        boss_lanes.append(lane)
    boss_lanes.sort(key=lambda b: (b.kind != "key", b.marks[0].t))
    groups: dict[tuple[str, str], Lane] = {}
    for t, x in mine:
        if x.kind == "do":
            w = next((w for w in waves if w["name"] == _clean(x.name) and abs(w["t"] - t) < 3), None)
            if w is not None and x.text.startswith("Kill"):
                w["mine"] = True
                continue
        lane = groups.setdefault((x.kind, x.text if x.kind == "do" else x.name),
                                 Lane(x.kind, [x.text if x.kind == "do" else x.name], [x.icon]))
        why = _say_why(x.why)
        c = _ctx(t, its, x.kind)
        tops = _tops_at(x.why)
        tip = [f"{x.text} · {'before the pull' if t < 0 else _mmss(t)}" + (f" · lasts {x.dur:.0f} s" if x.dur else "")]
        tip += [cap(c)] if c else []
        tip += [why] if why else []
        lane.marks.append(Mark(t, x.dur, x.icon, "\n".join(tip), "pre" if t < 0 else _mmss(t),
                               flag="⚠" in x.why or "hold" in x.why,
                               tops=tops if tops is not None and abs(tops - t) > 3 else None))
        if x.kind == "def" and _answers(x):
            lane.sub = f"for {_answers(x)}"
    lanes = list(groups.values())
    merged: list[Lane] = []
    for lane in lanes:  # cooldowns always pressed together: one lane (Ancestral Call + Ascendance + the Vile Vial)
        same = next((m for m in merged if lane.kind == m.kind == "cd" and [round(x.t) for x in m.marks]
                     == [round(x.t) for x in lane.marks]), None)
        if same is None:
            merged.append(lane)
            continue
        same.names.append(lane.names[0])
        same.icons.append(lane.icons[0])
        for a, b in zip(same.marks, lane.marks, strict=True):
            a.dur = max(a.dur, b.dur)
            a.tip += f"\nWith {lane.names[0]}" + (f" ({b.dur:.0f} s)" if b.dur else "")
            a.flag = a.flag or b.flag
    order = ("cd", "pot", "def", "move", "do")
    merged.sort(key=lambda m: (order.index(m.kind), m.marks[0].t))
    for m in merged:
        if len(m.names) > 1:
            m.sub = "\n".join(f"+ {n}" for n in m.names[1:])
    kills: dict[str, Lane] = {}
    for w in waves:
        if not w["mine"]:
            continue
        x = w["it"]
        lane = kills.setdefault(w["name"], Lane("kill", [f"Kill {w['name']}"], [x.icon]))
        n = re.match(r"(\d+)\s*×", x.text.replace(" ", " "))
        tip = [f"Kill {x.text} · {_mmss(w['t'])} · alive {w['dur']:.0f} s in the top kills"]
        tip += [f"Comes with {', '.join(f'{c} (+{o:.0f} s)' for c, o in w['with'])}"] if w["with"] else []
        tip += [x.hint] if x.hint else []
        lane.marks.append(Mark(w["t"], w["dur"], x.icon, "\n".join(tip), _mmss(w["t"]),
                               n[1] if n and n[1] != "1" else ""))
    for lane in kills.values():
        total = sum(int(m.count or 1) for m in lane.marks)
        lane.sub = f"{len(lane.marks)} wave{'s' if len(lane.marks) > 1 else ''}" + (
            f" · {total} adds" if any(m.count for m in lane.marks) else "")
    you = merged[:]
    at = next((i for i, m in enumerate(you) if m.kind == "do"), len(you))
    you[at:at] = kills.values()
    return Timeline(end, _phases(d, end), [(t, x) for t, x in boss if x.kind == "lust"],
                    [(t, x) for t, x in boss if x.kind == "immune"],
                    [m for m in moves if m[2] is None or m[2].kind not in ("cast", "mech")], you, boss_lanes, others,
                    sorted({x.name for _t, x in boss if x.kind == "tank"}))


def _tip(text: str) -> str:
    return f" data-tip='{e(text)}'" if text else ""


def timeline_html(d, tl: Timeline) -> str:
    end = tl.end

    def x(t: float) -> str:
        return f"{max(0.0, min(100.0, t / end * 100)):.2f}%"

    def w(t: float, dur: float) -> str:
        return f"{max(0.0, min(dur, end - t)) / end * 100:.2f}%"

    def row(cls: str, head: str, track: str) -> str:
        return f"<div class='r {cls}'><div class='g'>{head}</div><div class='tr'>{track}</div></div>"

    def head(lane: Lane) -> str:
        ics = "".join(_ic(i) for i in lane.icons[:4])
        sub = "".join(f"<small>{e(x)}</small>" for x in lane.sub.split("\n")) if lane.sub else ""
        return (f"<span class='lics'>{ics}</span><span class='nm'>{e(lane.names[0])}{sub}</span>"
                f"<span class='ct'>×{len(lane.marks)}</span>")
    px = TRACK_PX / end
    ticks = "".join(f"<span class='tick{' min' if t % 60 == 0 else ''}' style='left:{x(t)}'>{_mmss(t)}</span>"
                    for t in range(0, int(end) + 1, 30) if (end - t) * px >= 64)
    rows = [row("ax", "", ticks + f"<span class='killflag'>Kill ~{_mmss(end)}</span>")]
    if len(tl.phases) > 1:
        ph = "".join(f"<span class='seg-ph{' imm' if any(abs(t - a) < 2 for t, _i in tl.immune) else ''}' "
                     f"style='left:{x(a)};width:calc({w(a, b - a)} - 3px)'{_tip(f'{n} · {_mmss(a)} to {_mmss(b)}')}>"
                     f"<span>{e(n)}</span>{'<em>' + _mmss(a) + '</em>' if (b - a) * px > 9 * len(n) + 60 else ''}"
                     f"</span>" for n, a, b in tl.phases)
        rows.append(row("fph", "<span class='lb'>Phases</span>", ph))
    wins = "".join(f"<span class='win lust' style='left:{x(t)};width:{w(t, it.dur)}'"
                   f"{_tip(f'{it.text} · {_mmss(t)} · lasts {it.dur:.0f} s')}>{_ic(it.icon)}Bloodlust</span>"
                   for t, it in tl.lust)
    wins += "".join(f"<span class='win imm' style='left:{x(t)};width:{w(t, it.dur)}'"
                    f"{_tip(f'Boss immune · {_mmss(t)} to {_mmss(t + it.dur)}')}>{_ic(it.icon)}Boss immune "
                    f"<em>{it.dur:.0f} s</em></span>" for t, it in tl.immune)
    if wins:
        rows.append(row("raid", "<span class='lb'>Raid</span>", wins))
    if tl.moves:
        mv = ""
        for k, (a, b, c) in enumerate(tl.moves):
            room = ((tl.moves[k + 1][0] if k + 1 < len(tl.moves) else end) - a) * px
            bar = max(4.0, (b - a) * px)
            name = _clean(c.name) if c else ""
            fits = 21 + bar + 5 + 6.6 * len(name) <= room - 6  # the name whole or not at all: its icon says it
            mv += (f"<span class='mvw' style='left:{x(a)};max-width:{room - 6:.0f}px'{_tip(move_tip(a, b, c))}>"
                   + (_ic(c.icon) if c else "") + f"<i class='mv' style='width:{bar:.0f}px'></i>"
                   + (f"<span>{e(name)}</span>" if name and fits else "") + "</span>")
        other = any(m.move for lane in tl.boss for m in lane.marks)  # the others are on their cast's lane
        rows.append(row("mvr", f"<span class='lb'>{'Other moves' if other else 'You move'}</span>", mv))
    rows.append("<div class='sec'><span>You</span></div>")
    for lane in tl.you:
        track = ""
        for k, m in enumerate(lane.marks):
            nxt = lane.marks[k + 1].t if k + 1 < len(lane.marks) else end
            room = (nxt - m.t) * px
            if m.dur:
                at = max(0.0, m.t)
                track += f"<span class='bar k-{lane.kind}' style='left:{x(at)};width:{w(at, m.dur)}'></span>"
            if m.tops is not None:
                said = f"Most top players press it at about {_mmss(m.tops)}"
                side = " late" if m.tops > m.t else ""  # its words away from the press's icon
                track += (f"<span class='ghost{side}' style='left:{x(m.tops)}'{_tip(said)}><b>tops {_mmss(m.tops)}</b>"
                          "</span>")
            wide = " wide" if m.count else ""
            long = f"<small>{m.dur:.0f} s</small>" if lane.kind == "kill" and m.dur and room > 110 else ""
            last = k + 1 == len(lane.marks)
            label = f"<span class='tm{wide}'>{m.label}{long}</span>" if room > (40 if last else LABEL_PX) else ""
            track += (f"<span class='ev k-{lane.kind}' style='left:{x(max(0.0, m.t))}'{_tip(m.tip)}>{_ic(m.icon)}"
                      + (f"<b class='n'>{m.count}</b>" if m.count else "")
                      + ("<b class='badge'>!</b>" if m.flag else "")
                      + f"{label}</span>")
        rows.append(row("you", head(lane), track))
    if tl.boss:
        rows.append("<div class='sec sb'><span>The boss <i>what concerns you</i></span></div>")
    for lane in tl.boss:
        track = "".join(f"<i class='mv' style='left:{x(m.move[0])};width:{w(m.move[0], m.move[1] - m.move[0])}'></i>"
                        for m in lane.marks if m.move)  # the move it starts: a dashed line under its icon
        track += "".join(f"<span class='bm{' open' if m.flag else ''}' style='left:{x(m.t)}'{_tip(m.tip)}>"
                        f"{_ic(m.icon)}"
                        + (f"<span class='tm'>{m.label}</span>" if lane.kind == "key" and (
                            (lane.marks[k + 1].t if k + 1 < len(lane.marks) else end) - m.t) * px > 48 else "")
                        + "</span>" for k, m in enumerate(lane.marks))
        rows.append(row(f"boss{' m' if lane.kind != 'key' else ''}", head(lane), track))
    grid = "".join(f"<i class='gl{' h' if t % 60 else ''}' style='left:{x(t)}'></i>"
                   for t in range(0, int(end) + 1, 30))
    grid += "".join(f"<i class='immcol' style='left:{x(t)};width:{w(t, it.dur)}'></i>" for t, it in tl.immune)
    grid += f"<i class='gl end' style='left:{x(end)}'></i><i class='cur'><b></b></i><i class='now'><b></b></i>"
    kinds = {lane.kind for lane in tl.you}
    key = [(k, t) for k, t in (("cd", "cooldown"), ("pot", "potion"), ("def", "defensive"), ("kill", "target alive"))
           if k in kinds]
    legend = "".join(f"<span><i class='kk k-{k}'></i>{t}</span>" for k, t in key)
    if any(m.tops is not None for lane in tl.you for m in lane.marks):
        legend += "<span><i class='kk ghostk'></i>where most top players press it</span>"
    if any(m.flag for lane in tl.you for m in lane.marks):
        legend += "<span><b class='badgek'>!</b>held by the plan, or pressed elsewhere by the tops</span>"
    if tl.moves or any(m.move for b in tl.boss for m in b.marks):
        legend += "<span><i class='kk mvk'></i>you move</span>"
    return (f"<div class='ftl' data-end='{end:.1f}' role='img' aria-label='The fight on one clock: your presses, the "
            f"adds you kill and the boss spells that concern you'>{''.join(rows)}<div class='ov'>{grid}</div></div>"
            f"<div class='fkey' aria-hidden='true'>{legend}</div>")


def summary(d, tl: Timeline) -> str:
    """The plan in a sentence: when you burst and where, the boss immune, your defensives."""
    its = items(d)
    lust = [(t, t + it.dur) for t, it in tl.lust]
    presses = sorted(((m.t, lane) for lane in tl.you if lane.kind in ("cd", "pot") for m in lane.marks if m.t >= 0),
                     key=lambda p: p[0])
    durs = {(round(m.t), lane.names[0]): m.dur for lane in tl.you for m in lane.marks}
    bursts: list[list] = []
    for t, lane in presses:
        if bursts and t - bursts[-1][0] <= SAME_BURST:
            bursts[-1][1].append(lane)
        else:
            bursts.append([t, [lane]])
    big = [(t, ls) for t, ls in bursts if len(ls) >= 2 and any(durs.get((round(t), x.names[0])) for x in ls)]

    def where(t: float) -> str:
        if any(a <= t <= b for a, b in lust):
            return "in Bloodlust"
        c = _ctx(t, its, "cd")
        return re.sub(r"^on the \d+ × ", "on the ", c) if c not in ("on the pull", "just after the pull") else ""
    parts = []
    if big:
        ws = [where(t) for t, _ls in big]
        if len(big) > 1 and len(set(ws)) == 1 and ws[0]:
            parts.append(f"Burst at {' and '.join(f'<b>{_mmss(t)}</b>' for t, _ls in big)}, each {e(ws[0])}.")
        else:
            parts.append("Burst " + " and ".join(f"at <b>{_mmss(t)}</b>{' ' + e(wh) if wh else ''}"
                                                 for (t, _ls), wh in zip(big, ws, strict=True)) + ".")
    for t, it in tl.immune:
        parts.append(f"The boss is immune from <b>{_mmss(t)}</b> to <b>{_mmss(t + it.dur)}</b>.")
    defs: dict[tuple[str, str], int] = {}
    for lane in tl.you:
        if lane.kind == "def":
            defs[(lane.names[0], lane.sub.removeprefix("for "))] = len(lane.marks)
    if defs:
        parts.append(", ".join(f"{e(n)} {'each' if k > 1 else 'for'} {e(w)}" if w else e(n)
                               for (n, w), k in defs.items()) + ".")
    return f"<p class='lede'>{' '.join(parts)}</p>" if parts else ""


def differ_html(d) -> str:
    """Where your plan and the top players differ: each press with a reason beyond its cooldown, said in full."""
    its = items(d)
    rows = []
    for t, it in its:
        if it.side != "you" or it.kind not in ("cd", "pot") or t < 5:
            continue
        parts = [x.strip() for x in (it.why or "").split(";") if x.strip()]
        if not [x for x in parts if x not in ("◷ on cooldown", "when your rotation calls it")]:
            continue
        pct = re.search(r"(\d+)% of the top players", it.why)
        tops = _tops_at(it.why)
        c = _ctx(t, its, it.kind)
        meter = (f"<div class='mtr'><span><i style='width:{pct[1]}%'></i></span>{pct[1]}% of the top players"
                 f"{' at ' + _mmss(tops) if tops is not None else ' then'}</div>") if pct else ""
        rows.append(f"<li>{_ic(it.icon)}<time>{_mmss(t)}</time><div><p><b>{e(it.text)}</b>"
                    f"{' <span class=muted>' + e(c) + '</span>' if c else ''}</p><p>{e(_say_why(it.why))}</p>{meter}"
                    f"</div></li>")
    if not rows:
        return ("<section class='card differ'><h2>Your plan and the top players</h2><p class='muted'>They press your "
                "cooldowns at the same moments.</p></section>")
    return (f"<section class='card differ'><h2>Where your plan and the top players differ</h2><ul>{''.join(rows)}"
            f"</ul></section>")


def mrt_html(d) -> str:
    note = mrt(d)
    if not note:
        return ""
    return (f"<section class='card mrtc'><div class='mrth'><h2>MRT note</h2>{_btn('mrt', 'Copy', cls='btn ghost')}"
            f"</div><textarea class='mrt-box' id='mrt-text' aria-label='MRT note' readonly "
            f"rows='{sum(1 + len(x) // 60 for x in note.splitlines())}'>{e(note)}</textarea></section>")


LIVE_TITLE = " title='Follow the pull live, on a second screen: what to press now and next'"


def live_html(d) -> str:
    """The live view (the owner's pick: the plan on one screen, the live of the player-first mockup): a big clock,
    what to press now, then, what is running, what comes in the next minute, the timeline with a playhead."""
    speed = ("<span class='seg' role='group' aria-label='Speed'><button type='button' data-s='1' aria-pressed='true'>"
             "×1</button><button type='button' data-s='4' aria-pressed='false'>×4</button></span>")
    return (f"<dialog class='lv' id='ss' aria-label='{e(d.boss)}, live' tabindex='-1'>"
            "<div class='lv-top'><div class='lv-clock'><b id='c-time'>0:00</b><span><span class='lv-boss'>"
            f"{e(d.boss)} {theme.diff_pill(d.difficulty)}</span><span id='c-phase'></span></span></div>"
            f"<div class='lv-ctl'>{_btn('play', 'Play', 'Space', 'btn primary')}"
            f"{_btn('pull', 'Start at 10 on the pull timer', 'Alt+P')}{speed}"
            f"{_btn('c-sync', '', 'Control+Shift+Space', hidden=True)}"
            f"{_btn('ss-sound', 'Voice and beeps', cls='btn ghost', more=' aria-pressed=false')}"
            f"{_btn('ss-wipe', 'Wipe', cls='btn ghost')}{_btn('ss-close', 'Close', 'Escape', 'btn ghost')}</div></div>"
            "<div class='lv-tl' id='lv-tl'></div>"
            "<div class='lv-main'><section class='lv-now' aria-label='Now'><div class='call' id='c-call'></div>"
            "<p class='then' id='c-then'></p></section>"
            "<aside class='lv-side'><h3>Running now</h3><dl class='who'><dt>Fight</dt><dd id='c-boss'></dd><dt>You</dt>"
            "<dd class='yd' id='c-you'></dd></dl><div class='nb'><p><span id='c-next'></span><b id='c-in'></b></p>"
            "<div class='meter'><i id='c-meter'></i></div></div><h3>The next minute</h3>"
            "<div class='bars' id='ss-bars' role='list' aria-label='Coming up'></div></aside></div></dialog>")


def _move_said(t: float, boss: list[tuple[float, Item]]) -> str:
    c = move_cause(t, boss)
    return f"Move for {_clean(c.name)}" if c else "Move"


def data(d, dur: float) -> dict:
    """What the page's script needs, each event at its own time on the plan's clock."""
    its = items(d)
    phases = _phases(d, dur)

    def ph(t: float) -> int:
        return max((i for i, p in enumerate(phases) if t >= p[1] - 0.5), default=0)

    phase_starts = [s for _n, s, _e in phases[1:]]
    boss = [(t, x) for t, x in its if x.side == "boss"]
    moves = _moves(boss, dur)  # the repositions the page draws, no other
    acts = [{"t": _t1(t), "n": x.text, "k": x.kind, "ic": x.icon, "d": round(x.dur, 1),
             "c": "" if x.kind == "move" else (_ctx(t, its, x.kind)
                                               or ("default list timing" if x.kind == "cd" else "")),
             "w": x.why}
            for t, x in its if x.side == "you"]
    acts.sort(key=lambda a: (a["t"], YOU_ORDER.index(a["k"])))
    return {
        "end": round(dur, 1),
        "phases": [[n, _t1(s), _t1(t)] for n, s, t in phases],
        "acts": acts,
        "anchors": [PULL] + [{"t": _t1(t), "n": x.name if x.kind in ("phase", "immune") else x.text, "k": x.kind,
                     "p": ph(t), "ic": x.icon} for t, x in its if x.side == "boss" and x.kind in ANCHORS and t >= 1
                    and not (x.kind != "phase" and any(abs(t - s) <= 1 for s in phase_starts))],
        "boss": [{"t": _t1(t), "d": round(x.dur, 1), "k": x.kind, "ic": x.icon,
                  "n": _move_said(t, boss) if x.kind == "move" else x.text} for t, x in its
                 if x.side == "boss" and x.kind not in ("phase",)
                 and (x.kind != "move" or any(a - 0.5 <= t <= b for a, b in moves))],
    }


def html(d) -> str:
    """The fight view, or '' when the prep has no fight to show."""
    tl = timeline(d)
    if tl is None or not (tl.you or tl.boss):
        return ""
    payload = json.dumps(data(d, tl.end)).replace("</", "<\\/")
    live = f"<div class='go-live'>{_btn('ss-open', 'Live view', 'L', 'btn primary', more=LIVE_TITLE)}</div>"
    return (f"<div class='fv'><div class='fv-top'><div class='fv-lede'>{summary(d, tl)}{live}</div>"
            f"{opener_html(d)}</div>"
            f"<section class='card tlc' id='tl' tabindex='-1' aria-labelledby='tl-h'><div class='tlh'><h2 id='tl-h'>"
            f"The pull, minute by minute</h2><span class='muted'>hover anything for the details</span>"
            f"{kill_switch(d)}</div>"
            f"{timeline_html(d, tl)}</section>"
            f"<div class='fv-below'>{differ_html(d)}{mrt_html(d)}</div>{live_html(d)}"
            "<div class='tip' id='fv-tip' role='tooltip' hidden></div>"
            "<p class='vh' id='sr' aria-live='polite' aria-atomic='false'></p>"
            f"<script>var FV={payload};</script><script>{JS}</script></div>")


CSS = theme.style("fightview")
JS = files("paf").joinpath("scripts", "fightview.js").read_text(encoding="utf-8")
