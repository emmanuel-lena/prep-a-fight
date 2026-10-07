"""Your own log next to the top players' (no rotation analysis, see issue #14): do you keep casting (always be
casting), and do you move more than they do, phase by phase.

Both sides are measured the same way, from cast events:
- busy time: a cast with a cast time from its start to its end (at least one global cooldown), an instant cast one
  global cooldown; the global cooldown of a player is read from their own casts (the shortest usual gap);
- movement: the positions carried by the player's cast events (paf.corpus.template.moving_seconds).
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

GCD_MIN, GCD_MAX = 0.75, 1.5  # seconds: a global cooldown is in this range whatever the haste
IDLE_GAP = 2.5  # seconds without casting that count as an idle gap
LATENCY = 0.2  # seconds: a next action this soon after the previous one ends is back to back
MAX_GAPS = 3  # idle gaps shown


@dataclass
class PhaseReview:
    name: str
    active: float  # share of the phase you spend casting
    tops_active: float | None
    moving: float  # share of the phase you spend moving
    tops_moving: float | None


@dataclass
class Review:
    fight: str  # which pull: "kill of 6:12"
    active: float
    tops_active: float | None
    moving: float
    tops_moving: float | None
    phases: list[PhaseReview] = field(default_factory=list)
    gaps: list[tuple[float, float]] = field(default_factory=list)  # (start, length) of your longest idle gaps


def gcd(starts: list[float]) -> float:
    """A player's global cooldown: the usual shortest gap between two actions."""
    gaps = sorted(b - a for a, b in zip(starts, starts[1:], strict=False) if b - a > 0.3)
    if not gaps:
        return 1.2
    return min(GCD_MAX, max(GCD_MIN, gaps[len(gaps) // 10]))


def busy(casts: list[tuple[str, int, float]]) -> list[tuple[float, float]]:
    """Merged busy intervals from (type 'begincast' / 'cast', ability id, time) events in time order."""
    begun: dict[int, float] = {}
    starts = []
    spans = []
    for kind, ability, t in casts:
        if kind == "begincast":
            begun[ability] = t
            starts.append(t)
        elif ability in begun and t - begun[ability] < 10:
            spans.append((begun.pop(ability), t))
        else:
            starts.append(t)
            spans.append((t, t))
    g = gcd(sorted(starts))
    merged: list[list[float]] = []
    for a, b in sorted((a, max(b, a + g)) for a, b in spans):
        if merged and a <= merged[-1][1] + LATENCY:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def share(spans: list[tuple[float, float]], start: float, end: float) -> float:
    if end <= start:
        return 0.0
    return sum(max(0.0, min(b, end) - max(a, start)) for a, b in spans) / (end - start)


def idle_gaps(spans: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """The longest stretches without casting (start, length), longest first."""
    gaps = [(a2_end, b_start - a2_end) for (_, a2_end), (b_start, _) in zip(spans, spans[1:], strict=False)
            if b_start - a2_end >= IDLE_GAP]
    return sorted(gaps, key=lambda g: -g[1])[:MAX_GAPS]


def moving_share(points: list[tuple[float, float, float]], start: float, end: float) -> float:
    from paf.corpus.template import moving_seconds

    flags = moving_seconds(points, end)
    window = flags[int(start):int(end)]
    return sum(window) / len(window) if window else 0.0


def phase_bounds(starts: list[float], duration: float) -> list[tuple[float, float]]:
    return [(s, starts[i + 1] if i + 1 < len(starts) else duration) for i, s in enumerate(starts)]


# --- the top players (corpus) ----------------------------------------------------------------------------------------

def tops_activity(con: sqlite3.Connection, encounter_id: int, difficulty: int, spec: str
                  ) -> tuple[float | None, float | None, list[tuple[float | None, float | None]]]:
    """Median busy and moving shares of the ranked players of `spec`: overall, then per phase (in phase order)."""
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(
        f"SELECT c.report, c.fight_id, c.type, c.ability_id, c.t, c.x, c.y, f.duration_s FROM player_cast c "
        f"JOIN fight f USING(report, fight_id) JOIN ranked r USING(report, fight_id) "
        f"WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? ORDER BY c.t", (*params, spec)).fetchall()
    per: dict[tuple[str, int], list] = defaultdict(list)
    dur: dict[tuple[str, int], float] = {}
    for r in rows:
        per[(r[0], r[1])].append(r)
        dur[(r[0], r[1])] = r[7]
    phases: dict[tuple[str, int], list[float]] = defaultdict(list)
    for rep, fid, t in con.execute(f"SELECT p.report, p.fight_id, p.t_start FROM phase p JOIN fight f "
                                   f"USING(report, fight_id) WHERE {where} ORDER BY p.t_start", params):
        phases[(rep, fid)].append(t)
    active, moving = [], []
    by_phase: dict[int, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for k, evs in per.items():
        spans = busy([(r[2], r[3], r[4]) for r in evs])
        pts = [(r[4], r[5], r[6]) for r in evs if r[5] is not None]
        active.append(share(spans, 0, dur[k]))
        if len(pts) > 50:
            moving.append(moving_share(pts, 0, dur[k]))
        for i, (a, b) in enumerate(phase_bounds(phases.get(k) or [0.0], dur[k])):
            by_phase[i][0].append(share(spans, a, b))
            if len(pts) > 50:
                by_phase[i][1].append(moving_share(pts, a, b))
    med = (lambda v: round(st.median(v), 3) if v else None)  # noqa: E731
    return (med(active), med(moving),
            [(med(by_phase[i][0]), med(by_phase[i][1])) for i in sorted(by_phase)])


# --- your log (Warcraft Logs) ----------------------------------------------------------------------------------------

FIGHTS_QUERY = """query($code:String!){ reportData { report(code:$code) {
  masterData { actors(type:"Player") { id name } }
  fights(killType: Encounters) { id encounterID difficulty kill startTime endTime phaseTransitions { id startTime } }
} } }"""


def review(client, url: str, encounter_id: int, difficulty: int, name: str, phase_names: list[str],
           tops: tuple[float | None, float | None, list[tuple[float | None, float | None]]]) -> Review | None:
    """Your pull of this boss in your raid's log (a kill first, else the longest) next to the top players'.
    None when you are not in the log or the log has no pull of this boss."""
    from paf.raidneed import report_code

    code = report_code(url)
    rep = client.query(FIGHTS_QUERY, {"code": code}, cache_ttl=3600)["reportData"]["report"] or {}
    me = next((a for a in (rep.get("masterData") or {}).get("actors") or []
               if name and a.get("name", "").lower() == name.lower()), None)
    pulls = [f for f in rep.get("fights") or [] if f["encounterID"] == encounter_id and f["endTime"] > f["startTime"]]
    if me is None or not pulls:
        return None
    f = max(pulls, key=lambda f: (f["difficulty"] == difficulty, bool(f["kill"]), f["endTime"] - f["startTime"]))
    s0, s1 = f["startTime"], f["endTime"]
    duration = (s1 - s0) / 1000
    events = list(client.events(code, f["id"], s0, s1, data_type="Casts", source_id=me["id"], include_resources=True))
    casts = [(ev.get("type"), ev.get("abilityGameID"), (ev["timestamp"] - s0) / 1000) for ev in events
             if ev.get("type") in ("cast", "begincast") and ev.get("sourceID") == me["id"]]
    # positions in yards x100, of the player only when the event's resource actor is its source (as in the corpus)
    pts = [((ev["timestamp"] - s0) / 1000, ev["x"] / 100, ev["y"] / 100) for ev in events
           if ev.get("sourceID") == me["id"] and "x" in ev and "y" in ev and ev.get("resourceActor", 1) == 1]
    if not casts:
        return None
    spans = busy(casts)
    seen: dict[int, float] = {}
    for p in sorted(f.get("phaseTransitions") or [], key=lambda p: p["startTime"]):
        seen.setdefault(p["id"], (p["startTime"] - s0) / 1000)
    starts = sorted(seen.values()) or [0.0]
    phases = []
    for i, (a, b) in enumerate(phase_bounds(starts, duration)):
        top = tops[2][i] if i < len(tops[2]) else (None, None)
        name_i = phase_names[i] if i < len(phase_names) else f"Phase {i + 1}"
        phases.append(PhaseReview(name_i, round(share(spans, a, b), 3), top[0],
                                  round(moving_share(pts, a, b), 3) if pts else 0.0, top[1]))
    what = f"{'kill' if f['kill'] else 'pull'} of {int(duration // 60)}:{int(duration % 60):02d}"
    return Review(what, round(share(spans, 0, duration), 3), tops[0],
                  round(moving_share(pts, 0, duration), 3) if pts else 0.0, tops[1], phases,
                  idle_gaps(spans, duration))
