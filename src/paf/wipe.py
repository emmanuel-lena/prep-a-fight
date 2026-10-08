"""Your best pull of a boss you have not killed, in detail: what the deaths cost, what the damage off the boss cost,
and when the boss would have died without them.

From the log, cut into windows of 15 s (one damage table per window, read with the deaths of the pull):
- a damage dealer who dies loses, until they are back (a window with at least half their usual damage: a battle
  res) or the end, the median boss damage per window they did before dying; the deaths of the wipe itself (after
  half the raid is dead) are left out;
- the boss's health = the boss damage of the pull / the share of its health taken;
- the damage off the boss: had the raid put the top kills' share of its damage on the boss (paf.raidreview), each
  window's boss damage scales by that ratio. A longer pull sees more adds: this part is an upper bound.
A kill time past the end of the pull is extrapolated at the boss damage of the last minute before the wipe.
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

STEP = 15.0
BACK = 0.5  # a dead player is back with this share of their usual damage in a window
NON_DAMAGE = ("Restoration", "Holy", "Discipline", "Preservation", "Mistweaver", "Blood", "Brewmaster", "Guardian",
              "Protection", "Vengeance")

FIGHTS = """query($c:String!){ reportData { report(code:$c) {
  fights(killType: Encounters) { id encounterID difficulty kill startTime endTime bossPercentage } } } }"""
DEATHS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) { table(fightIDs:$f, dataType:Deaths) } } }"""
WINDOW = """query($c:String!,$f:[Int]!,$s:Float!,$e:Float!){ reportData { report(code:$c) {
  table(fightIDs:$f, dataType:DamageDone, startTime:$s, endTime:$e) } } }"""


@dataclass
class Death:
    name: str
    spec: str  # "Class-Spec" icon of the log
    t: float
    back: float | None  # when they did damage again (a battle res), None = never
    lost: float  # boss damage lost


@dataclass
class Pull:
    fight: int
    duration: float
    boss_left: float  # share of the boss's health left at the end
    health: float
    windows: list[float]  # boss damage per window
    deaths: list[Death] = field(default_factory=list)
    wipe_at: float | None = None  # when half the raid was dead
    raid_share: float = 0.0  # share of the raid's damage on the boss
    tops_share: float = 0.0
    lost: list[float] = field(default_factory=list)  # boss damage lost to the deaths, per window

    def left_at(self, t: float, deaths: bool = True, share: bool = False) -> float:
        """Boss health left at time t, with the deaths (or without), the raid's share (or the tops')."""
        done = 0.0
        for w, dmg in enumerate(self.windows):
            start = w * STEP
            if start >= t:
                break
            part = min(1.0, (t - start) / STEP)
            v = dmg + (0.0 if deaths else self.lost[w])
            done += part * v * (self.share_ratio if share else 1.0)
        return max(0.0, 1 - done / self.health) if self.health else 1.0

    @property
    def share_ratio(self) -> float:
        return max(1.0, self.tops_share / self.raid_share) if self.raid_share else 1.0

    def kill_time(self, deaths: bool = True, share: bool = False) -> float:
        cum, end = 0.0, int((self.wipe_at or self.duration) // STEP)
        ratio = self.share_ratio if share else 1.0
        for w, dmg in enumerate(self.windows):
            v = (dmg + (0.0 if deaths else self.lost[w])) * ratio
            if w < end and cum + v >= self.health:
                return w * STEP + STEP * (self.health - cum) / v if v else w * STEP
            if w < end:
                cum += v
        last = [(self.windows[w] + (0.0 if deaths else self.lost[w])) * ratio for w in range(max(0, end - 4), end)]
        rate = st.mean(last) / STEP if last else 0.0
        return end * STEP + (self.health - cum) / rate if rate > 0 else float("inf")


def best_wipe(client, code: str, encounter_id: int, difficulty: int) -> dict | None:
    fights = client.query(FIGHTS, {"c": code}, cache_ttl=3600)["reportData"]["report"]["fights"] or []
    wipes = [f for f in fights if f["encounterID"] == encounter_id and f["difficulty"] == difficulty
             and not f["kill"] and f.get("bossPercentage") is not None]
    return min(wipes, key=lambda f: f["bossPercentage"], default=None)


def analyze(client, code: str, fight: dict, boss: str, raid_share_tops: float) -> Pull:
    """fight: from best_wipe; boss: the main boss's name as Warcraft Logs writes it."""
    t0, t1, fid = fight["startTime"], fight["endTime"], fight["id"]
    n = int((t1 - t0) / 1000 // STEP) + 1
    on_boss: dict[str, dict[int, float]] = defaultdict(dict)
    spec: dict[str, str] = {}
    raid_total = boss_total = 0.0
    for w in range(n):
        s = t0 + w * STEP * 1000
        e = min(t1, s + STEP * 1000)
        if e <= s:
            continue
        data = client.query(WINDOW, {"c": code, "f": [fid], "s": s, "e": e}, cache_ttl=86400)["reportData"]["report"]
        table = data["table"].get("data", data["table"]) if isinstance(data["table"], dict) else {}
        for ent in table.get("entries") or []:
            spec[ent["name"]] = ent.get("icon", "")
            b = sum(t.get("total", 0) for t in ent.get("targets") or [] if t.get("name") == boss)
            on_boss[ent["name"]][w] = b
            boss_total += b
            raid_total += sum(t.get("total", 0) for t in ent.get("targets") or [])
    windows = [sum(v.get(w, 0.0) for v in on_boss.values()) for w in range(n)]
    left = fight["bossPercentage"] / 100
    p = Pull(fid, (t1 - t0) / 1000, left, boss_total / (1 - left) if left < 1 else 0.0, windows,
             raid_share=boss_total / raid_total if raid_total else 0.0, tops_share=raid_share_tops, lost=[0.0] * n)
    table = client.query(DEATHS, {"c": code, "f": [fid]}, cache_ttl=86400)["reportData"]["report"]["table"]
    table = table.get("data", table) if isinstance(table, dict) else {}
    deaths = sorted(((e["timestamp"] - t0) / 1000, e["name"], e.get("icon", "")) for e in table.get("entries") or [])
    players = len(spec) or 1
    for i, (t, _, _) in enumerate(deaths):
        if i + 1 >= players / 2:
            p.wipe_at = t
            break
    end = int((p.wipe_at or p.duration) // STEP)
    for t, name, icon in deaths:
        if p.wipe_at is not None and t >= p.wipe_at:
            break
        if any(x in icon for x in NON_DAMAGE):
            continue
        ws = on_boss.get(name, {})
        dw = int(t // STEP)
        rate = st.median([ws.get(w, 0.0) for w in range(dw)]) if dw else 0.0
        back = next((w for w in range(dw + 1, n) if rate and ws.get(w, 0.0) >= BACK * rate), None)
        lost = 0.0
        for w in range(dw, min(back if back is not None else n, end)):
            gap = max(0.0, rate - ws.get(w, 0.0))
            p.lost[w] += gap
            lost += gap
        p.deaths.append(Death(name, icon, t, back * STEP if back is not None else None, lost))
    return p


def to_dict(p: Pull, boss: str, longest_kill: float, median_kill: float) -> dict:
    return {"boss": boss, "fight": p.fight, "duration": p.duration, "left": p.boss_left, "wipe_at": p.wipe_at,
            "raid_share": p.raid_share, "tops_share": p.tops_share, "longest_kill": longest_kill,
            "median_kill": median_kill,
            "kill": {"as_is": p.kill_time(), "no_deaths": p.kill_time(deaths=False),
                     "no_deaths_share": p.kill_time(deaths=False, share=True)},
            "curves": {k: [round(p.left_at(w * STEP, **kw), 4) for w in range(len(p.windows) + 1)]
                       for k, kw in (("as_is", {}), ("no_deaths", {"deaths": False}),
                                     ("no_deaths_share", {"deaths": False, "share": True}))},
            "deaths": [{"name": d.name, "spec": d.spec, "t": d.t, "back": d.back, "lost": d.lost / p.health
                        if p.health else 0.0} for d in p.deaths]}
