"""What one simulated pull's log says around each press (issue #41, a Demonology Warlock: "I cast the Tyrant, but
what must I have cast before? How many soul shards? Do I recast the dogs during it? What do I do in the burst and
outside it?"): the resource you hold when you press (shards, combo points, holy power...), what of yours is still up
(a summon for its duration, a buff your press gave until it fades), and over the pull what the action list presses
inside your big cooldowns and between them. Read from a play_by_play log (simc log=1), your character's lines only."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

BIG_CD = 45.0  # a press of this many seconds of cooldown at least is a big one (game data, base values)
SMALL_POOL = 10  # a resource of at most this many points is counted (shards, combo points), not energy or mana
RESOURCES = {"soul_shard": "shards", "combo_points": "combo points", "holy_power": "holy power", "chi": "chi",
             "arcane_charges": "arcane charges", "essence": "essence", "runes": "runes"}

_ROW = re.compile(r"^(\d+\.\d+) Player '([^']+)' (.*)$")
_PRESS = re.compile(r"^(performs|schedules execute for) Action '([a-z0-9_]+)' \((\d+)\)")
_GAIN = re.compile(r"^(\d+\.\d+) (\S+) gains [\d.]+ \([\d.]+\) ([a-z_]+) from .* \(([\d.]+)/([\d.]+)\)$")
_SPEND = re.compile(r"^consumes ([\d.]+) ([a-z_]+) for Action '([a-z0-9_]+)' \(\d+\) \(([\d.]+)\)$")
_SUMMON = re.compile(r"^summons (\S+) for ([\d.]+)s\.$")
_BUFF = re.compile(r"^(gains|loses) Buff '([a-z0-9_]+)' \((\d+)\)")


@dataclass
class Press:
    t: float
    action: str
    sid: int
    res: int | None = None  # the resource held at the press
    spends: bool = False  # it consumes that resource
    up: list[int] = field(default_factory=list)  # spell ids of your earlier presses still in effect


@dataclass
class Pull:
    presses: list[Press]
    resource: str = ""  # its player name: "shards"
    length: float = 0.0


def read(log: Path, actions: set[str] | None = None, ignore: set[str] = frozenset()) -> Pull:
    """Every press of the pull (what the action list schedules; `actions`: the list's own entries) with its state."""
    me: str | None = None
    res: dict[str, float] = {}
    pool: dict[str, float] = {}  # resource -> its max, when small
    effects: list[list] = []  # [source sid, source action, until (None: until its buff fades), buff name]
    presses: list[Press] = []
    spent: set[str] = set()
    last: tuple[float, str, int] | None = None  # the latest "performs": a summon or a buff at its time is its effect
    end = 0.0
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.is_file() else []
    for line in lines:
        g = _GAIN.match(line)
        if g and (me is None or g[2] == me):
            if float(g[5]) <= SMALL_POOL:
                pool[g[3]] = float(g[5])
            res[g[3]] = float(g[4])
            continue
        m = _ROW.match(line)
        if not m:
            continue
        t, who, rest = float(m[1]), m[2], m[3]
        if me is None and _PRESS.match(rest):
            me = who
        if who != me:
            continue
        end = t
        if p := _PRESS.match(rest):
            how, action, sid = p[1], p[2], int(p[3])
            if (action in ignore or (actions and action not in actions
                                    and not (action.startswith("use_item") and "use_item" in actions))):
                pass  # not a press of the list: a proc's or a summon's own action
            elif how == "performs":
                last = (t, action, sid)
            else:
                effects = [x for x in effects if x[2] is None or x[2] > t]
                up = list(dict.fromkeys(x[0] for x in effects if x[1] != action))
                presses.append(Press(t, action, sid, up=up))
                presses[-1].res = None if not pool else int(round(res.get(_main(pool), 0)))
        elif s := _SPEND.match(rest):
            if float(s[1]) > 0:
                spent.add(f"{s[3]}:{s[2]}")
            res[s[2]] = float(s[4])
        elif (s := _SUMMON.match(rest)) and last and last[0] == t and float(s[2]) > 0:
            effects.append([last[2], last[1], t + float(s[2]), ""])
        elif b := _BUFF.match(rest):
            if b[1] == "gains" and last and last[0] == t and (b[2] == last[1] or int(b[3]) == last[2] != 0):
                effects.append([last[2], last[1], None, b[2]])
            elif b[1] == "loses":
                effects = [x for x in effects if x[3] != b[2]]
    main = _main(pool) if pool else ""
    for x in presses:
        x.spends = f"{x.action}:{main}" in spent
    return Pull(presses, RESOURCES.get(main, main.replace("_", " ")), end)


def _main(pool: dict[str, float]) -> str:
    return next((r for r in RESOURCES if r in pool), next(iter(pool)))


def is_big(action: str, sid: int, cds: dict) -> bool:
    return action == "potion" or action.startswith("use_item") or (cds.get(sid) or (0.0,))[0] >= BIG_CD


@dataclass
class Split:
    share: float  # of the pull inside your big cooldowns
    inside: list[tuple[int, str, float]]  # (spell id, action, share of the presses there)
    outside: list[tuple[int, str, float]]


def burst_split(pull: Pull, cds: dict, top: int = 6, window: float = 20.0) -> Split | None:
    """What you press inside your big cooldowns (from each big press, `window` s: a burst's usual length) and
    between them, each spell's share of the presses there; only the spells whose share differs between the two."""
    bigs = [x.t for x in pull.presses if is_big(x.action, x.sid, cds) and x.t > 0]
    if not bigs or pull.length <= 0:
        return None
    spans: list[list[float]] = []
    for t in bigs:
        if spans and t <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], t + window)
        else:
            spans.append([t, t + window])
    inside, outside, names = Counter(), Counter(), {}
    for x in pull.presses:
        if is_big(x.action, x.sid, cds) or not x.sid:
            continue
        names[x.sid] = x.action
        (inside if any(a <= x.t < b for a, b in spans) else outside)[x.sid] += 1
    n_in, n_out = sum(inside.values()) or 1, sum(outside.values()) or 1
    covered = sum(min(b, pull.length) - a for a, b in spans) / pull.length

    def ranked(mine: Counter, n: int, other: Counter, n_other: int) -> list[tuple[int, str, float]]:
        out = [(sid, names[sid], c / n) for sid, c in mine.most_common()
               if c / n >= 0.05 and c / n >= 1.25 * other.get(sid, 0) / n_other]
        return out[:top]
    return Split(covered, ranked(inside, n_in, outside, n_out), ranked(outside, n_out, inside, n_in))


@dataclass
class Notes:
    """What the fight tab says of a pull: each press's state by (time, spell id), the burst split."""
    resource: str
    at: dict[tuple[float, int], Press]
    split: Split | None
    names: dict[int, str] = field(default_factory=dict)  # every spell id said, its name


def notes(log: Path, actions: set[str] | None, ignore: set[str], upto: float) -> Notes | None:
    try:
        from paf.gamedata import spell_cooldowns, spell_names

        cds, known = spell_cooldowns(), spell_names()
    except Exception:  # noqa: BLE001 - offline: the potion and the items are the big ones, the actions' names
        cds, known = {}, {}
    pull = read(log, actions, ignore)
    if not pull.presses:
        return None
    at = {(round(x.t, 3), x.sid): x for x in pull.presses if x.t <= upto}
    split = burst_split(pull, cds)
    actions_of = {x.sid: x.action for x in pull.presses}
    said = {s for x in at.values() for s in x.up} | {s for side in (split.inside, split.outside) if split
                                                    for s, _a, _c in side}
    names = {s: known.get(s) or actions_of.get(s, str(s)).replace("_", " ").capitalize() for s in said if s}
    return Notes(pull.resource, at, split, names)
