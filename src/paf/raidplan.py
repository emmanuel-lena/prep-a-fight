"""Raid planner: which spec each player brings and who pads the adds, for the most boss damage while the
adds still die as in the top raids.

Per player and spec, from the data of this boss:
- skill = the player's DPS in your raid's log / the top 100 median DPS of the spec they played (a player at 80% of
  the tops is assumed at 80% on any spec);
- "pad" (the top players' habit): damage = skill x top 100 median DPS, of which the spec's measured share goes to
  the adds (from the ranked kills: every player of the spec, not only yours);
- "boss" (stay on the boss): boss damage = skill x top 100 median boss DPS, a third of the pad add damage
  (cleave that comes anyway).
The raid must reach the add damage of the top raids' weakest quarter (per second, from the ranked kills). Start
with everyone on the boss in the spec that does the most boss damage, then switch to pad the players (or specs)
that cost the least boss damage per add damage gained, until the adds are covered. Healers and tanks are kept
as they are and counted with their measured add damage.
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf import theme
from paf.corpus.analyze import kills_filter
from paf.raidneed import HEALERS

TAB_JS = """<script>(function(){var ids=[...document.querySelectorAll('.panel')].map(function(p){return p.id});
function show(id){if(ids.indexOf(id)<0)id=ids[0];document.querySelectorAll('.panel').forEach(
function(p){p.hidden=p.id!==id});
document.querySelectorAll('.tabs a').forEach(function(a){a.classList.toggle('on',a.getAttribute('href')==='#'+id)})}
addEventListener('hashchange',function(){show(location.hash.slice(1))});show(location.hash.slice(1));})();</script>"""

TANKS = {"Blood DeathKnight", "Brewmaster Monk", "Protection Paladin", "Protection Warrior", "Guardian Druid",
         "Vengeance DemonHunter"}
BOSS_MODE_ADDS = 1 / 3  # share of the pad add damage a player staying on the boss still does (cleave)
MAX_SKILL = 1.3


@dataclass
class Member:
    name: str
    current: str  # "Spec Class" played in the log
    dps: float  # DPS in the log
    options: list[str] = field(default_factory=list)  # specs this player can play (current included)

    @property
    def role(self) -> str:
        return "healer" if self.current in HEALERS else "tank" if self.current in TANKS else "damage"


@dataclass
class Choice:
    member: Member
    spec: str
    pad: bool
    boss: float  # estimated boss DPS
    adds: float  # estimated DPS on the adds


@dataclass
class Plan:
    choices: list[Choice]
    boss: float
    adds: float
    required: float  # add DPS of the top raids' weakest quarter
    current_boss: float  # the comp of the log, everyone padding like the top players
    current_adds: float
    covered: bool
    notes: list[str] = field(default_factory=list)


def add_shares(con: sqlite3.Connection, encounter_id: int, difficulty: int) -> dict[str, float]:
    """Median share of each spec's damage that goes to the adds (all non-boss units) on this boss."""
    where, params = kills_filter(encounter_id, difficulty)
    bosses = {r[0] for r in con.execute("SELECT name FROM npc WHERE is_boss=1")}
    per: dict[tuple[str, int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
    specs: dict[tuple[str, int, int], str] = {}
    for rep, fid, actor, cls, spec in con.execute(
            f"SELECT p.report, p.fight_id, p.actor_id, p.class, p.spec FROM player p JOIN fight f "
            f"USING(report, fight_id) WHERE {where}", params):
        specs[(rep, fid, actor)] = f"{spec} {cls}"
    for rep, fid, actor, target, amount in con.execute(
            f"SELECT d.report, d.fight_id, d.actor_id, d.target, d.amount FROM damage_by_target d JOIN fight f "
            f"USING(report, fight_id) WHERE {where}", params):
        per[(rep, fid, actor)][0 if target in bosses else 1] += amount or 0
    shares: dict[str, list[float]] = defaultdict(list)
    for k, (b, a) in per.items():
        if k in specs and a + b > 0:
            shares[specs[k]].append(a / (a + b))
    return {s: st.median(v) for s, v in shares.items() if len(v) >= 10}


def required_adds(con: sqlite3.Connection, encounter_id: int, difficulty: int) -> tuple[float, float]:
    """(median, weakest quarter) of the top raids' damage per second on the adds."""
    where, params = kills_filter(encounter_id, difficulty)
    bosses = {r[0] for r in con.execute("SELECT name FROM npc WHERE is_boss=1")}
    dur = {(r[0], r[1]): r[2] for r in con.execute(
        f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}", params)}
    adds: dict[tuple[str, int], float] = defaultdict(float)
    for rep, fid, target, amount in con.execute(
            f"SELECT d.report, d.fight_id, d.target, d.amount FROM damage_by_target d JOIN fight f "
            f"USING(report, fight_id) JOIN player p ON p.report=d.report AND p.fight_id=d.fight_id "
            f"AND p.actor_id=d.actor_id WHERE {where}", params):
        if target not in bosses:
            adds[(rep, fid)] += amount or 0
    rates = sorted(v / dur[k] for k, v in adds.items() if dur.get(k))
    if not rates:
        return 0.0, 0.0
    return st.median(rates), rates[len(rates) // 4]


def _options(m: Member, profiles: dict, shares: dict[str, float]) -> list[Choice]:
    ref = profiles.get(m.current)
    skill = min(MAX_SKILL, m.dps / ref.dps) if ref and ref.dps else 0.8
    default_share = st.median(shares.values()) if shares else 0.2
    out = []
    for spec in m.options:
        p = profiles.get(spec)
        if p is None:
            continue
        a = shares.get(spec, default_share)
        total = skill * p.dps
        pad_boss, pad_adds = total * (1 - a), total * a
        boss_boss = max(skill * p.boss_dps, pad_boss)
        out.append(Choice(m, spec, True, pad_boss, pad_adds))
        out.append(Choice(m, spec, False, boss_boss, pad_adds * BOSS_MODE_ADDS))
    return out


def plan(members: list[Member], profiles: dict, shares: dict[str, float], required: float) -> Plan:
    fixed, chosen, options = [], {}, {}
    for m in members:
        opts = _options(m, profiles, shares)
        if m.role != "damage" or not opts:  # healers, tanks, unknown specs: as they are, padding like the tops
            a = shares.get(m.current, 0.0)
            fixed.append(Choice(m, m.current, True, m.dps * (1 - a), m.dps * a))
            continue
        options[m.name] = opts
        chosen[m.name] = max((o for o in opts if not o.pad), key=lambda o: o.boss)

    def totals() -> tuple[float, float]:
        cs = fixed + list(chosen.values())
        return sum(c.boss for c in cs), sum(c.adds for c in cs)

    boss, adds = totals()
    while adds < required:
        best, best_cost = None, None
        for name, opts in options.items():
            cur = chosen[name]
            for o in opts:
                gain = o.adds - cur.adds
                if gain <= 0:
                    continue
                cost = (cur.boss - o.boss) / gain
                if best_cost is None or cost < best_cost:
                    best, best_cost = o, cost
        if best is None:
            break
        chosen[best.member.name] = best
        boss, adds = totals()
    current = []
    for m in members:
        ref = [o for o in _options(Member(m.name, m.current, m.dps, [m.current]), profiles, shares) if o.pad]
        if ref and m.role == "damage":
            current.append(ref[0])
        else:
            a = shares.get(m.current, 0.0)
            current.append(Choice(m, m.current, True, m.dps * (1 - a), m.dps * a))
    notes = []
    if adds < required:
        notes.append("Even with every damage dealer padding, the raid stays below the top raids' add damage: "
                     "bring more cleave specs or expect the adds to live longer.")
    return Plan(fixed + list(chosen.values()), boss, adds, required, sum(c.boss for c in current),
                sum(c.adds for c in current), adds >= required, notes)


@dataclass
class Played:
    """What one player did in the raid's pull, from the log."""
    name: str
    spec: str
    role: str
    dps: float
    boss: float  # DPS on the boss
    adds: float  # DPS on everything else
    tops_share: float | None  # median share on the adds of the top players of the spec on this boss

    @property
    def share(self) -> float:
        return self.adds / self.dps if self.dps else 0.0

    @property
    def verdict(self) -> str:
        if self.tops_share is None or self.role != "damage":
            return ""
        d = self.share - self.tops_share
        return "padded more than the tops" if d > 0.1 else "stayed on the boss more than the tops" if d < -0.1 else \
            "like the top players"


def what_happened(rc, bosses: set[str], shares: dict[str, float]) -> list[Played]:
    """Per player of the raid's log: DPS on the boss and on the adds, vs the habit of the top players of the
    spec. Empty when the log has no pull of this boss."""
    if not getattr(rc, "same_boss", False) or not rc.duration:
        return []
    out = []
    for name, spec, dps in rc.players:
        targets = rc.targets.get(name, {})
        boss = sum(v for k, v in targets.items() if k in bosses) / rc.duration
        role = "healer" if spec in HEALERS else "tank" if spec in TANKS else "damage"
        out.append(Played(name, spec, role, dps, boss, max(0.0, dps - boss), shares.get(spec)))
    return sorted(out, key=lambda x: (x.role != "damage", -x.adds))


def render(p: Plan, boss: str, difficulty: str, report: str, fight: str, played: list[Played] | None = None) -> str:
    import html


    e = html.escape

    def k(v: float) -> str:
        return f"{v / 1000:,.0f}k"

    order = {"tank": 0, "healer": 2, "damage": 1}
    rows = ""
    for c in sorted(p.choices, key=lambda c: (order[c.member.role], not c.pad, -c.boss)):
        m = c.member
        swap = "" if c.spec == m.current else f" <span class='pill gold'>swap from {e(m.current)}</span>"
        role = ({"tank": "tank", "healer": "healer"}[m.role] if m.role != "damage"
                else "<b>pad the adds</b>" if c.pad else "stay on the boss")
        rows += (f"<tr><td>{e(m.name)}</td><td>{e(c.spec)}{swap}</td><td>{role}</td>"
                 f"<td class='n'>{k(c.boss)}</td><td class='n'>{k(c.adds)}</td></tr>")
    gain = (p.boss / p.current_boss - 1) * 100 if p.current_boss else 0.0
    cover = p.adds / p.required if p.required else 0.0
    notes = "".join(f"<p class='notice small'>{e(n)}</p>" for n in p.notes)
    padders = sum(c.pad for c in p.choices if c.member.role == "damage")
    happened = ""
    if played:
        add_total = sum(x.adds for x in played)
        cover_note = (" (covered)" if add_total >= p.required else
                      " (not covered: the adds lived longer than in the top raids)")
        rows_h = "".join(
            f"<tr><td>{e(x.name)}</td><td>{e(x.spec)}</td><td class='n'>{k(x.dps)}</td><td class='n'>{k(x.boss)}</td>"
            f"<td class='n'>{k(x.adds)}</td><td class='n'>{x.share:.0%}</td>"
            f"<td class='n'>{'' if x.tops_share is None else f'{x.tops_share:.0%}'}</td><td>{e(x.verdict)}</td></tr>"
            for x in played)
        happened = f"""<section class="panel" id="pull"><h2>What happened in this pull</h2>
<p class="small">Read from the log: each player's damage on the boss and on the adds, next to what the top players of
the same spec do on this boss. The raid did <b>{k(add_total)}</b> DPS on the adds; the top raids' weakest quarter does
<b>{k(p.required)}</b>{cover_note}.</p>
<div class="card scroll"><table><tr><th>Player</th><th>Spec</th><th>DPS</th><th>Boss</th><th>Adds</th><th>On adds</th>
<th>Top players</th><th></th></tr>{rows_h}</table></div></section>"""
    tabs = ("<nav class='tabs'><a href='#pull'>What happened</a><a href='#plan'>Best comp for this boss</a></nav>"
            if happened else "")
    body = f"""<h1>{e(boss)} <span class="pill gold">{e(difficulty)}</span>: your raid</h1>
<p class="lead">From your raid's log {e(report)} ({e(fight)}).</p>{tabs}{happened}
<section class="panel" id="plan"><h2>Best comp for this boss</h2>
<p class="small">Who should play what, and who pads the adds, for the most boss damage while the adds still die as fast
as in the top raids. Estimated from each player's DPS in the log and the top 100 of every spec on this boss.</p>
<div class="kpis" style="display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
<div class="tile kpi"><div class="l">Boss damage</div><div class="v">{gain:+.1f}%</div>
<div class="s">vs your comp with everyone padding like the top players</div></div>
<div class="tile kpi"><div class="l">Adds covered</div><div class="v">{cover:.0%}</div>
<div class="s">of the add damage of the top raids' weakest quarter</div></div>
<div class="tile kpi"><div class="l">Padders</div><div class="v">{padders}</div>
<div class="s">damage dealers on the adds</div></div></div>{notes}
<div class="card scroll"><table><tr><th>Player</th><th>Spec</th><th>Role</th><th>Boss DPS</th><th>Add DPS</th></tr>
{rows}</table></div>
<details class="card"><summary>How it is computed</summary><p class="small muted">{e(__doc__ or '')}</p></details>
</section>"""
    css = (theme.style("raidplan"))
    js = TAB_JS if happened else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(boss)} raid plan</title>{theme.HEAD}<style>{theme.CSS}{css}</style></head><body>"
            f"{theme.topbar('')}<main>{body}</main>{js}</body></html>")


def class_specs(con: sqlite3.Connection, encounter_id: int, difficulty: int) -> dict[str, list[str]]:
    """Class -> its damage specs seen on this boss ("Fire Mage", "Frost Mage"...)."""
    where, params = kills_filter(encounter_id, difficulty)
    out: dict[str, set[str]] = defaultdict(set)
    for cls, spec in con.execute(f"SELECT DISTINCT p.class, p.spec FROM player p JOIN fight f "
                                 f"USING(report, fight_id) WHERE {where}", params):
        label = f"{spec} {cls}"
        if label not in HEALERS and label not in TANKS:
            out[cls].add(label)
    return {c: sorted(v) for c, v in out.items()}
