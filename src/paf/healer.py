"""Healer prep (issue #16): the raid damage of a boss, its big moments, and when the top healers of your spec press
their healing cooldowns. No SimulationCraft (it does not sim healing well): everything comes from the logs of the top
healers of the spec on this boss (a corpus ranked by healing per second, paf.corpus.collect.ranking_metric).

- The raid damage: Warcraft Logs' damage-taken graph of each kill, bounded to the pull (one series per player, summed;
  about 2 points a kill, for the first RAID_KILLS kills), resampled to STEP seconds; the median over the kills, up to the median
  duration. Its big moments: the windows at SPIKE times the median or more, the boss spell cast just before named.
- The healing cooldowns: the spells the top players cast at most once every 45 s or so (rare casts) that most of them
  take; the moments most of them press each (paf.defensives.peaks), next to the nearest big moment of raid damage.
- Talents: the builds of the top players (count, with the import string); trinkets: the most played.
- What the Encounter Journal asks healers; the numbers (HPS of a talent or an item): QE Live.
"""

from __future__ import annotations

import json
import statistics as st
from collections import Counter
from dataclasses import dataclass, field
from html import escape as e

GRAPH = """query($c:String!,$f:[Int]!,$a:Float,$b:Float){ reportData { report(code:$c) {
  graph(fightIDs:$f, dataType:DamageTaken, hostilityType:Friendlies, startTime:$a, endTime:$b) } } }"""
BOUNDS = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) { fights(fightIDs:$f) { startTime endTime } } } }"""


def fight_bounds(client, report: str, fight_id: int) -> tuple[float, float]:
    """The pull's start and end in the report (a graph without them covers the whole report)."""
    f = (client.query(BOUNDS, {"c": report, "f": [fight_id]}, cache_ttl=86400)["reportData"]["report"]["fights"]
         or [{}])[0]
    return f.get("startTime") or 0, f.get("endTime") or 0


def series_of(g: dict) -> tuple[float, dict[str, list[float]]]:
    """(seconds per point, name -> damage taken per second at each point) of a graph."""
    series = {s.get("name", "?"): s.get("data") or [] for s in g.get("series") or [] if s.get("name") != "Total"}
    first = next(iter(g.get("series") or []), {})
    return (first.get("pointInterval") or STEP * 1000) / 1000, series
RAID_KILLS = 40
STEP = 5.0
SPIKE = 1.6  # a moment with this many times the median raid damage
SPIKE_GAP = 15.0
COOLDOWN_GAP = 45.0  # a spell cast at most once in this many seconds (median) is a cooldown
QE_LIVE = "https://questionablyepic.com/live/"


@dataclass
class Moment:
    t: float
    dtps: float  # raid damage taken per second there
    ratio: float  # times the median
    boss_spell: str = ""


@dataclass
class Cooldown:
    name: str
    spell_id: int
    users: float  # share of the top players who cast it
    per_kill: float
    times: list[float]  # when most of them press it
    near: list[str] = field(default_factory=list)  # the big moment each one answers, if any


@dataclass
class HealerPrep:
    boss: str
    difficulty: str
    spec: str
    kills: int
    duration: float
    curve: list[float]  # median raid damage taken per second, per STEP
    moments: list[Moment]
    cooldowns: list[Cooldown]
    builds: list[tuple[int, str, str]]  # (players, label, import string)
    trinkets: list[tuple[str, int, float]]  # name, item id, share of the top players
    journal: list[str]
    phases: list[tuple[str, float]] = field(default_factory=list)


def ensure_table(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS raid_damage(report TEXT, fight_id INT, step REAL, series TEXT, "
                "PRIMARY KEY(report, fight_id))")
    con.execute("DELETE FROM raid_damage WHERE step > 10")  # read over the whole report by 0.6.23's first try


def fetch_raid_damage(client, con, encounter_id: int, difficulty: int, limit: int = RAID_KILLS,
                      log=print) -> int:
    """The damage-taken graph of the first `limit` kills that lack it (best ranked first); returns how many."""
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    have = con.execute(f"SELECT COUNT(*) FROM raid_damage d JOIN fight f USING(report, fight_id) WHERE {where}",
                       params).fetchone()[0]
    todo = con.execute(
        f"SELECT f.report, f.fight_id FROM fight f LEFT JOIN raid_damage d USING(report, fight_id) "
        f"LEFT JOIN ranked r USING(report, fight_id) WHERE {where} AND d.report IS NULL ORDER BY r.rank_pos",
        params).fetchall()[:max(0, limit - have)]
    for rep, fid in todo:
        a, b = fight_bounds(client, rep, fid)
        g = client.query(GRAPH, {"c": rep, "f": [fid], "a": a, "b": b}, cache_ttl=86400)["reportData"]["report"]["graph"]
        step, series = series_of(g.get("data", g) if isinstance(g, dict) else {})
        con.execute("INSERT OR REPLACE INTO raid_damage VALUES(?,?,?,?)", (rep, fid, step, json.dumps(series)))
    con.commit()
    if todo:
        log(f"  raid damage of {len(todo)} kills")
    return len(todo)


def raid_curve(con, encounter_id: int, difficulty: int, duration: float) -> list[float]:
    """Median raid damage taken per second, per STEP seconds, over the kills that have it."""
    from paf.corpus.analyze import kills_filter

    ensure_table(con)
    where, params = kills_filter(encounter_id, difficulty)
    n = int(duration // STEP) + 1
    per_bucket: list[list[float]] = [[] for _ in range(n)]
    for step, series in con.execute(f"SELECT d.step, d.series FROM raid_damage d JOIN fight f "
                                    f"USING(report, fight_id) WHERE {where}", params):
        data = json.loads(series)
        total: list[float] = []
        for values in data.values():
            for i, v in enumerate(values):
                if i >= len(total):
                    total.append(0.0)
                total[i] += v or 0
        for i, v in enumerate(total):  # each point covers `step` seconds: into STEP buckets
            b = int(i * step // STEP)
            if b < n:
                per_bucket[b].append(v)
    return [st.median(v) if v else 0.0 for v in per_bucket]


def moments(curve: list[float], boss_casts: list[tuple[str, list[float]]], top: int = 8) -> list[Moment]:
    """The big moments of raid damage, the boss spell cast just before each (within 8 s)."""
    base = st.median([v for v in curve if v > 0]) if any(curve) else 0.0
    if not base:
        return []
    found: list[Moment] = []
    for i, v in enumerate(curve):
        if v < SPIKE * base or (i and curve[i - 1] > v) or (i + 1 < len(curve) and curve[i + 1] > v):
            continue
        t = i * STEP
        if found and t - found[-1].t < SPIKE_GAP:
            if v > found[-1].dtps:
                found[-1] = Moment(t, v, v / base)
            continue
        found.append(Moment(t, v, v / base))
    for m in found:
        near = [(m.t - x, name) for name, times in boss_casts for x in times if -2 <= m.t - x <= 8]
        if near:
            m.boss_spell = min(near)[1]
    return sorted(sorted(found, key=lambda m: -m.ratio)[:top], key=lambda m: m.t)


def cooldowns(tl, found: list[Moment], base: dict[int, tuple[float, int]] | None = None) -> list[Cooldown]:
    """The cooldowns of the top players (spells with a cooldown of COOLDOWN_GAP s or more in the game data, that most
    of them cast; dispels, rotation spells and moves left out) and when most of them press each."""
    from paf.defensives import peaks

    if base is None:
        try:
            from paf.gamedata import spell_cooldowns

            base = spell_cooldowns()
        except Exception:  # noqa: BLE001 - offline: no game data, the casts' rarity alone
            base = {}
    out, seen = [], set()
    for a in sorted(tl.abilities, key=lambda a: -a.users):
        if a.users < 0.5 or not tl.duration or a.per_kill > max(1.0, tl.duration / COOLDOWN_GAP) or a.name in seen:
            continue
        if base and base.get(a.id, (0.0, 1))[0] < COOLDOWN_GAP:
            continue
        seen.add(a.name)
        per_player = [p["casts"].get(a.name) or p["casts"].get(a.id) or [] for p in tl.players]
        per_player = [ts for ts in per_player if ts]
        times = peaks(per_player) if per_player else []
        near = []
        for t in times:
            m = min(found, key=lambda m: abs(m.t - t), default=None)
            near.append(f"{_mmss(m.t)} {m.boss_spell}".strip() if m and abs(m.t - t) <= 20 else "")
        out.append(Cooldown(a.name, a.id, a.users, a.per_kill, times, near))
    return sorted(out, key=lambda c: -c.users)


def trinkets(con, encounter_id: int, difficulty: int, top: int = 50) -> list[tuple[str, int, float]]:
    from paf.corpus.analyze import kills_filter

    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(f"SELECT r.gear_json FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} "
                       f"AND r.gear_json IS NOT NULL ORDER BY r.rank_pos LIMIT {int(top)}", params).fetchall()
    count: Counter = Counter()
    names: dict[int, str] = {}
    for (g,) in rows:
        gear = json.loads(g or "[]")
        for slot in (12, 13):  # the trinket slots of Warcraft Logs' gear list
            if slot < len(gear) and gear[slot].get("id"):
                count[gear[slot]["id"]] += 1
                names[gear[slot]["id"]] = gear[slot].get("name") or str(gear[slot]["id"])
    n = len(rows) or 1
    return [(names[i], i, c / n) for i, c in count.most_common(6)]


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


CSS = """<style>
.hp-sec{margin:26px 0} .hp-sec h2{font:600 22px 'Fraunces',Georgia,serif;margin:0 0 10px;text-transform:none;letter-spacing:0}
.rd{width:100%;height:auto;display:block} .rd polyline{fill:none;stroke:var(--neg);stroke-width:2.5}
.rd .ax{stroke:var(--line)} .rd .ph{stroke:var(--accent);stroke-dasharray:4 4;opacity:.6}
.rd .tk,.rd .ml{fill:var(--muted);font-size:11px} .rd .mk{fill:var(--warn)}
.hl2{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.hl2 li{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;padding:10px 12px;border:1px solid var(--line);
  border-radius:10px;background:var(--surface)} .hl2 small{color:var(--muted)} .hl2 .when{display:flex;flex-wrap:wrap;gap:6px;width:100%}
.hl2 .chip{padding:3px 9px;border-radius:999px;border:1px solid var(--line);font-size:13px}
.hl2 .copy{margin-left:auto}
</style>"""
JS = ("<script>document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(!b)return;"
      "navigator.clipboard.writeText(b.dataset.copy).then(function(){b.textContent='Copied'},function(){})})"
      "</script>")


def curve_svg(curve: list[float], found: list[Moment], phases: list[tuple[str, float]], label: str) -> str:
    """A damage-taken curve (per STEP), its big moments as dots, the phases as dashed lines."""
    W, H, L, B = 760, 200, 46, 24
    peak = max(curve, default=0) or 1
    span = max(len(curve) * STEP, 1)

    def x(t: float) -> str:
        return f"{L + t / span * (W - L - 10):.1f}"

    def y(v: float) -> str:
        return f"{10 + (1 - v / peak) * (H - B - 20):.1f}"
    pts = " ".join(f"{x(i * STEP)},{y(v)}" for i, v in enumerate(curve))
    marks = "".join(f"<circle cx='{x(m.t)}' cy='{y(m.dtps)}' r='4' class='mk'/>"
                    f"<text x='{x(m.t)}' y='{max(12.0, float(y(m.dtps)) - 6):.1f}' class='ml'>{_mmss(m.t)}</text>"
                    for m in found)
    lines = "".join(f"<line class='ph' x1='{x(t)}' x2='{x(t)}' y1='10' y2='{H - B}'/>" for _, t in phases if t > 0)
    ticks = "".join(f"<text x='{x(t)}' y='{H - 6}' class='tk'>{int(t // 60)}:00</text>"
                    for t in range(0, int(span) + 1, 60))
    return (f"<svg viewBox='0 0 {W} {H}' class='rd' role='img' aria-label='{e(label)}'>"
            f"<line class='ax' x1='{L}' x2='{W - 10}' y1='{H - B}' y2='{H - B}'/>{lines}{ticks}"
            f"<polyline points='{pts}'/>{marks}</svg>")


def moments_html(found: list[Moment], what: str) -> str:
    return "".join(f"<li><b>{_mmss(m.t)}</b><span>{e(m.boss_spell) if m.boss_spell else what}</span>"
                   f"<small>&times;{m.ratio:.1f} the usual</small></li>" for m in found)


def cooldowns_html(cds: list[Cooldown]) -> str:
    return "".join(
        f"<li><b>{e(c.name)}</b><small>{c.users:.0%} of the top players &middot; {c.per_kill:.1f} a kill</small>"
        f"<span class='when'>" + "".join(f"<span class='chip'>{_mmss(t)}{(' &rarr; ' + e(n)) if n else ''}</span>"
                                       for t, n in zip(c.times, c.near, strict=False)) + "</span></li>"
        for c in cds)


def builds_html(builds: list[tuple[int, str, str]]) -> str:
    copy = "<button class='btn ghost copy' data-copy='{}'>Copy the talents</button>"
    return "".join(f"<li><b>{e(lbl)}</b><small>{n} of the top players</small>"
                   + (copy.format(e(code)) if code else "") + "</li>" for n, lbl, code in builds)


def trinkets_html(trinkets: list[tuple[str, int, float]]) -> str:
    return "".join(f"<li><a href='https://www.wowhead.com/item={i}' target='_blank' rel='noopener'>{e(n)}</a>"
                   f"<small>{s:.0%} of the top players</small></li>" for n, i, s in trinkets)


def page(title: str, body: str) -> str:
    from paf import theme

    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(title)}</title>{theme.HEAD}<style>{theme.CSS}</style>{CSS}</head><body>"
            f"{theme.topbar('')}<main>{body}</main>{JS}</body></html>")


def render(h: HealerPrep) -> str:
    svg = curve_svg(h.curve, h.moments, h.phases, "Raid damage taken over the fight")
    mom, cds = moments_html(h.moments, "raid damage"), cooldowns_html(h.cooldowns)
    builds, trk = builds_html(h.builds), trinkets_html(h.trinkets)
    jr = "".join(f"<li>{e(x)}</li>" for x in h.journal)
    body = f"""<h1>{e(h.boss)} <span class="pill gold">{e(h.difficulty)}</span></h1>
<p class="lead">{e(h.spec)}: the healer's prep, from {h.kills} kills of the top healers of your spec. A {_mmss(h.duration)}
fight.</p>
<section class="hp-sec"><h2>The raid damage, and its big moments</h2>{svg}
<p class="small muted">Damage the raid takes per second, median of the top kills; a dot marks a big moment.</p>
<ul class="hl2">{mom or '<li>No big moment: steady raid damage.</li>'}</ul></section>
<section class="hp-sec"><h2>Your healing cooldowns, where the top healers press them</h2>
<ul class="hl2">{cds or '<li>Not enough top players in the corpus yet.</li>'}</ul></section>
<section class="hp-sec"><h2>Talents</h2><ul class="hl2">{builds or '<li>No build yet.</li>'}</ul></section>
<section class="hp-sec"><h2>Trinkets the top healers play</h2><ul class="hl2">{trk or '<li>No gear yet.</li>'}</ul></section>
{f'<section class="hp-sec"><h2>What the Encounter Journal asks healers</h2><ul class="hl2">{jr}</ul></section>' if jr else ''}
<section class="hp-sec"><h2>The numbers</h2><p>SimulationCraft does not sim healing well: for the value of a talent or an
item for your healing, use <a href="{QE_LIVE}" target="_blank" rel="noopener">QE Live</a>.</p></section>"""
    return page(f"{h.boss} prep", body)
