"""Your best pull of a boss you have not killed, in detail: what the deaths cost, what each player's boss damage cost
next to the top players of their spec, and when the boss would have died without them.

From the log, cut into windows of 15 s (one damage table per window, read with the deaths of the pull):
- a damage dealer who dies loses, until they are back (a window with at least half their usual damage: a battle
  res) or the end, the median boss damage per window they did before dying; the deaths of the wipe itself (after
  half the raid is dead) are left out;
- the boss's health = the boss damage of the pull / the share of its health taken;
- the damage off the boss: had the raid put the top kills' share of its damage on the boss (paf.raidreview), each
  window's boss damage scales by that ratio. A longer pull sees more adds: this part is an upper bound;
- playing like the top players: every damage dealer alive the whole pull at the median boss DPS of their spec's
  players in the top kills (paf.comp.boss_dps), tanks and healers as they played.
Per damage dealer, the boss damage lost: to their deaths, and while alive, under the median of their spec. Their
talents are compared with the top 100 of their spec on this boss: the talents the top by total DPS (padding) takes
more often than the top by boss DPS, and the reverse (paf.raidneed rankings), clearest first.
A kill time past the end of the pull is extrapolated at the boss damage of the last minute before the wipe.
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

STEP = 15.0
BACK = 0.5  # a dead player is back with this share of their usual damage in a window
TALENT_GAP = 0.15  # a talent taken this much more often by one top 100 than by the other
TALENTS_SHOWN = 4
CLASSES = {"DeathKnight", "DemonHunter", "Druid", "Evoker", "Hunter", "Mage", "Monk", "Paladin", "Priest", "Rogue",
           "Shaman", "Warlock", "Warrior"}
NON_DAMAGE = ("Restoration", "Holy", "Discipline", "Preservation", "Mistweaver", "Blood", "Brewmaster", "Guardian",
              "Protection", "Vengeance")
SCENARIOS = ("as_is", "no_deaths", "no_deaths_share", "like_tops")

FIGHTS = """query($c:String!){ reportData { report(code:$c) {
  fights(killType: Encounters) { id encounterID difficulty kill startTime endTime bossPercentage } } } }"""
DEATHS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) { table(fightIDs:$f, dataType:Deaths) } } }"""
WINDOW = """query($c:String!,$f:[Int]!,$s:Float!,$e:Float!){ reportData { report(code:$c) {
  table(fightIDs:$f, dataType:DamageDone, startTime:$s, endTime:$e) } } }"""
DETAILS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) {
  playerDetails(fightIDs:$f, includeCombatantInfo:true) } } }"""


def label(icon: str) -> str:
    """'Warlock-Affliction' (the log's icon) -> 'Affliction Warlock' (the corpus's spec)."""
    cls, _, spec = icon.partition("-")
    return f"{spec} {cls}" if spec else icon


def is_damage(icon: str) -> bool:
    cls, _, spec = icon.partition("-")
    return cls in CLASSES and bool(spec) and spec not in NON_DAMAGE


@dataclass
class Death:
    name: str
    spec: str  # "Class-Spec" icon of the log
    t: float
    back: float | None  # when they did damage again (a battle res), None = never
    lost: float  # boss damage lost


@dataclass
class Culprit:
    name: str
    spec: str  # icon
    alive_dps: float  # boss DPS while alive
    tops_dps: float | None  # median boss DPS of the spec's players in the top kills
    lost_alive: float  # boss damage lost while alive, under the spec's median
    lost_dead: float  # boss damage lost to their deaths
    pad_talents: list[str] = field(default_factory=list)  # taken, and taken more by the padders
    boss_talents: list[str] = field(default_factory=list)  # not taken, and taken more by the boss top

    @property
    def lost(self) -> float:
        return self.lost_alive + self.lost_dead


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
    tops_windows: list[float] = field(default_factory=list)  # boss damage per window, playing like the tops
    players: dict[str, tuple[str, dict[int, float]]] = field(default_factory=dict)  # name -> (icon, window -> boss)
    culprits: list[Culprit] = field(default_factory=list)

    @property
    def share_ratio(self) -> float:
        return max(1.0, self.tops_share / self.raid_share) if self.raid_share else 1.0

    def scenario(self, key: str) -> list[float]:
        if key == "like_tops" and self.tops_windows:
            return self.tops_windows
        ratio = self.share_ratio if key == "no_deaths_share" else 1.0
        dead = key != "as_is"
        return [(v + (self.lost[w] if dead else 0.0)) * ratio for w, v in enumerate(self.windows)]

    def left_at(self, t: float, key: str = "as_is") -> float:
        done = 0.0
        for w, v in enumerate(self.scenario(key)):
            if w * STEP >= t:
                break
            done += min(1.0, (t - w * STEP) / STEP) * v
        return max(0.0, 1 - done / self.health) if self.health else 1.0

    def kill_time(self, key: str = "as_is") -> float:
        values = self.scenario(key)
        end = min(len(values), int((self.wipe_at or self.duration) // STEP))
        cum = 0.0
        for w in range(end):
            v = values[w]
            if cum + v >= self.health:
                return w * STEP + STEP * (self.health - cum) / v if v else w * STEP
            cum += v
        last = values[max(0, end - 4):end]
        rate = st.mean(last) / STEP if last else 0.0
        return end * STEP + (self.health - cum) / rate if rate > 0 else float("inf")


def best_wipe(client, code: str, encounter_id: int, difficulty: int) -> dict | None:
    fights = client.query(FIGHTS, {"c": code}, cache_ttl=3600)["reportData"]["report"]["fights"] or []
    wipes = [f for f in fights if f["encounterID"] == encounter_id and f["difficulty"] == difficulty
             and not f["kill"] and f.get("bossPercentage") is not None]
    return min(wipes, key=lambda f: f["bossPercentage"], default=None)


def analyze(client, code: str, fight: dict, boss: str, raid_share_tops: float,
            spec_boss_dps: dict[str, float] | None = None) -> Pull:
    """fight: from best_wipe; boss: the main boss's name as Warcraft Logs writes it; spec_boss_dps: spec -> median
    boss DPS of its players in the top kills (paf.comp.boss_dps)."""
    t0, t1, fid = fight["startTime"], fight["endTime"], fight["id"]
    n = int((t1 - t0) / 1000 // STEP) + 1
    on_boss: dict[str, dict[int, float]] = defaultdict(dict)
    icon: dict[str, str] = {}
    raid_total = boss_total = 0.0
    for w in range(n):
        s = t0 + w * STEP * 1000
        e = min(t1, s + STEP * 1000)
        if e <= s:
            continue
        data = client.query(WINDOW, {"c": code, "f": [fid], "s": s, "e": e}, cache_ttl=86400)["reportData"]["report"]
        table = data["table"].get("data", data["table"]) if isinstance(data["table"], dict) else {}
        for ent in table.get("entries") or []:
            icon[ent["name"]] = ent.get("icon", "")
            b = sum(t.get("total", 0) for t in ent.get("targets") or [] if t.get("name") == boss)
            on_boss[ent["name"]][w] = b
            boss_total += b
            raid_total += sum(t.get("total", 0) for t in ent.get("targets") or [])
    windows = [sum(v.get(w, 0.0) for v in on_boss.values()) for w in range(n)]
    left = fight["bossPercentage"] / 100
    p = Pull(fid, (t1 - t0) / 1000, left, boss_total / (1 - left) if left < 1 else 0.0, windows,
             raid_share=boss_total / raid_total if raid_total else 0.0, tops_share=raid_share_tops, lost=[0.0] * n,
             players={k: (icon.get(k, ""), v) for k, v in on_boss.items()})
    table = client.query(DEATHS, {"c": code, "f": [fid]}, cache_ttl=86400)["reportData"]["report"]["table"]
    table = table.get("data", table) if isinstance(table, dict) else {}
    deaths = sorted(((e["timestamp"] - t0) / 1000, e["name"], e.get("icon", "")) for e in table.get("entries") or [])
    for i, (t, _, _) in enumerate(deaths):
        if i + 1 >= (len(icon) or 1) / 2:
            p.wipe_at = t
            break
    end = int((p.wipe_at or p.duration) // STEP)
    dead: dict[str, set[int]] = defaultdict(set)  # name -> windows dead
    for t, name, ic in deaths:
        if p.wipe_at is not None and t >= p.wipe_at:
            break
        if not is_damage(ic):
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
            dead[name].add(w)
        p.deaths.append(Death(name, ic, t, back * STEP if back is not None else None, lost))
    dps = spec_boss_dps or {}
    if dps:
        p.tops_windows = [sum(dps[label(ic)] * STEP if is_damage(ic) and label(ic) in dps else ws.get(w, 0.0)
                              for ic, ws in p.players.values()) for w in range(n)]
    for name, (ic, ws) in p.players.items():
        if not is_damage(ic):
            continue
        alive = [w for w in range(end) if w not in dead[name]]
        alive_dps = sum(ws.get(w, 0.0) for w in alive) / (len(alive) * STEP) if alive else 0.0
        ref = dps.get(label(ic))
        lost_alive = max(0.0, ref - alive_dps) * len(alive) * STEP if ref else 0.0
        lost_dead = sum(d.lost for d in p.deaths if d.name == name)
        p.culprits.append(Culprit(name, ic, alive_dps, ref, lost_alive, lost_dead))
    p.culprits.sort(key=lambda c: -c.lost)
    return p


def talent_split(client, encounter_id: int, difficulty: int, spec_label: str) -> dict[int, tuple[float, float]]:
    """Talent entry id -> (share of the top 100 by total DPS taking it, share of the top 100 by boss DPS)."""
    from paf.raidneed import RANKING_QUERY

    spec, _, cls = spec_label.rpartition(" ")
    shares = []
    for metric in ("dps", "bossdps"):
        data = client.query(RANKING_QUERY, {"id": encounter_id, "diff": difficulty, "cls": cls, "spec": spec,
                                            "metric": metric}, cache_ttl=6 * 3600)
        rows = [r for r in ((data["worldData"]["encounter"]["characterRankings"] or {}).get("rankings") or [])
                if r.get("amount")]
        c: dict[int, int] = defaultdict(int)
        for r in rows:
            for t in r.get("talents") or []:
                c[t.get("talentID")] += 1
        shares.append({k: v / len(rows) for k, v in c.items()} if len(rows) >= 10 else {})
    if not shares[0] or not shares[1]:
        return {}
    return {t: (shares[0].get(t, 0.0), shares[1].get(t, 0.0)) for t in set(shares[0]) | set(shares[1])}


def add_talents(client, code: str, p: Pull, encounter_id: int, difficulty: int, top: int = 6) -> None:
    """The talents of the players who lost the most boss damage, next to the top 100 of their spec."""
    try:
        from paf.gamedata import talent_entry_names

        names = talent_entry_names()
    except Exception:  # noqa: BLE001 - the names are a nicety
        names = {}
    data = client.query(DETAILS, {"c": code, "f": [p.fight]}, cache_ttl=86400)["reportData"]["report"]["playerDetails"]
    data = data.get("data", data) if isinstance(data, dict) else {}
    data = data.get("playerDetails", data)
    details = {x["name"]: x for role in ("dps", "tanks", "healers") for x in data.get(role) or []}
    splits: dict[str, dict[int, tuple[float, float]]] = {}
    for c in p.culprits[:top]:
        x = details.get(c.name) or {}
        taken = {t.get("id") for t in (x.get("combatantInfo") or {}).get("talentTree") or []}
        spec = label(c.spec)
        if not taken:
            continue
        if spec not in splits:
            splits[spec] = talent_split(client, encounter_id, difficulty, spec)
        pad = sorted(((a - b, t) for t, (a, b) in splits[spec].items() if t in taken and a - b >= TALENT_GAP),
                     reverse=True)
        boss = sorted(((b - a, t) for t, (a, b) in splits[spec].items() if t not in taken and b - a >= TALENT_GAP),
                      reverse=True)
        pad_names = [names.get(t) or "" for _, t in pad]
        boss_names = [names.get(t) or "" for _, t in boss]
        both = set(pad_names) & set(boss_names)  # a choice node seen on both sides says nothing
        c.pad_talents = [n for n in dict.fromkeys(pad_names) if n and n not in both][:TALENTS_SHOWN]
        c.boss_talents = [n for n in dict.fromkeys(boss_names) if n and n not in both][:TALENTS_SHOWN]


def to_dict(p: Pull, boss: str, longest_kill: float, median_kill: float) -> dict:
    keys = [k for k in SCENARIOS if k != "like_tops" or p.tops_windows]
    h = p.health or 1
    return {"boss": boss, "fight": p.fight, "duration": p.duration, "left": p.boss_left, "wipe_at": p.wipe_at,
            "raid_share": p.raid_share, "tops_share": p.tops_share, "longest_kill": longest_kill,
            "median_kill": median_kill, "kill": {k: p.kill_time(k) for k in keys},
            "curves": {k: [round(p.left_at(w * STEP, k), 4) for w in range(len(p.windows) + 1)] for k in keys},
            "deaths": [{"name": d.name, "spec": d.spec, "t": d.t, "back": d.back, "lost": d.lost / h}
                       for d in p.deaths],
            "culprits": [{"name": c.name, "spec": c.spec, "alive_dps": c.alive_dps, "tops_dps": c.tops_dps,
                          "lost_alive": c.lost_alive / h, "lost_dead": c.lost_dead / h,
                          "pad_talents": c.pad_talents, "boss_talents": c.boss_talents} for c in p.culprits]}
