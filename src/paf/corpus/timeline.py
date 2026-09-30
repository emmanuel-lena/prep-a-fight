"""Lorrgs-like cooldown timelines of the top players of a spec on a boss, as a standalone HTML page."""

from __future__ import annotations

import html
import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import _q, canonical_waves, fight_waves, kills_filter, main_boss
from paf.wowhead import SCRIPT as WH_SCRIPT
from paf.wowhead import link, spell_ref

MAX_CASTS_PER_MIN = 2.6  # abilities cast more often than this are rotation, not cooldowns
MIN_USERS = 0.3  # an ability must be used by at least 30% of the players to be shown
BIN = 5  # seconds per bin in the aggregated view
# utility / defensive / movement abilities (shown apart from offensive cooldowns); matched on lowercase names
UTILITY_HINTS = ("astral shift", "gust of wind", "ghost wolf", "spiritwalker", "wind rush", "skyfury",
                 "health potion", "healthstone", "earth elemental", "stoneskin", "burrow", "hex", "purge",
                 "cleanse", "wind shear", "capacitor", "tremor", "earthbind", "thunderstorm", "reincarnation",
                 "blink", "ice block", "barrier", "unending resolve", "divine shield", "dispersion", "fade",
                 "desperate prayer", "obsidian scales", "renewing blaze", "hover", "cloak", "evasion", "sprint",
                 "feint", "shroud", "aspect of the turtle", "exhilaration", "survival", "bear form", "dash",
                 "stampeding", "barkskin", "roar", "fortifying", "diffuse", "roll", "transcendence", "ice bound",
                 "anti-magic", "death's advance", "blur", "netherwalk", "darkness", "shield wall", "rallying",
                 "heroic leap", "intervene", "defensive stance")
PALETTE = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9", "#f59f00", "#d6336c", "#15aabf", "#5c7cfa",
           "#74b816", "#fd7e14", "#0ca678", "#be4bdb", "#868e96", "#fab005"]
TARGET_PALETTE = ["#ae3ec9", "#1c7ed6", "#d6336c", "#f59f00"]  # other boss units; adds are green


@dataclass
class Ability:
    id: int
    name: str
    users: float  # share of players who cast it
    per_kill: float  # median casts per kill among users
    color: str = ""
    utility: bool = False


@dataclass
class Timeline:
    boss: str
    difficulty: str
    spec: str
    kills: int
    duration: float
    phases: list[tuple[str, float, bool]]  # name, median start, intermission
    waves: list[tuple[float, float, float, str]]  # start, count, lifetime, types
    abilities: list[Ability]
    players: list[dict] = field(default_factory=list)  # rank, dps, ilvl, duration, casts {ability: [t]}
    boss_casts: list[tuple[str, list[float]]] = field(default_factory=list)  # ability name, median times
    main_boss: str = ""  # the unit taking most of the damage (the encounter can be named otherwise)
    boss_spell_ids: dict[str, int] = field(default_factory=dict)  # boss ability name -> spell id (Wowhead links)


TARGET_GAP = 6.0  # seconds: a target segment ends this long after its last cast when nothing follows
ADDS = "adds"


def target_kind(name: str, is_boss: bool, boss_name: str) -> str:
    """'' for the main boss, the unit's name for another boss unit (a second boss, a heart...), 'adds' else."""
    if name.lower() == boss_name.lower():
        return ""
    return name if is_boss else ADDS


def target_segments(casts: list[tuple[float, str]]) -> list[tuple[float, float, str]]:
    """Casts (t, target kind) -> (start, end, kind) segments of consecutive casts on the same kind of target."""
    out: list[list] = []
    for t, kind in sorted(casts):
        if out and out[-1][2] == kind and t - out[-1][1] <= TARGET_GAP:
            out[-1][1] = t
        else:
            if out and t - out[-1][1] <= TARGET_GAP:
                out[-1][1] = t  # the previous segment lasts until the switch
            out.append([t, t, kind])
    return [(a, b + 1.5, k) for a, b, k in out]


def build_timeline(con: sqlite3.Connection, encounter_id: int, difficulty: int, boss_name: str,
                   diff_name: str, spec: str, top: int = 25) -> Timeline:
    where, params = kills_filter(encounter_id, difficulty)
    fights = con.execute(f"SELECT report, fight_id, duration_s FROM fight f WHERE {where}", params).fetchall()
    keys = sorted((r["report"], r["fight_id"]) for r in fights)
    duration = st.median(r["duration_s"] for r in fights) if fights else 0
    names = dict(con.execute("SELECT id, name FROM ability").fetchall())
    main = main_boss(con, encounter_id, difficulty, boss_name)

    ranked = con.execute(
        f"SELECT r.* FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} AND r.spec=? "
        f"AND r.actor_id IS NOT NULL ORDER BY r.rank_pos", (*params, spec)).fetchall()
    casts: dict[tuple[str, int], dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    targets: dict[tuple[str, int], list[tuple[float, str]]] = defaultdict(list)
    for c in con.execute(
            f"SELECT c.report, c.fight_id, c.ability_id, c.t, n.name AS target, n.is_boss FROM player_cast c "
            f"JOIN fight f USING(report, fight_id) JOIN ranked r USING(report, fight_id) "
            f"LEFT JOIN npc_actor a ON a.report=c.report AND a.actor_id=c.target_id "
            f"LEFT JOIN npc n ON n.game_id=a.game_id "
            f"WHERE {where} AND c.actor_id=r.actor_id AND r.spec=? AND c.type='cast' ORDER BY c.t", (*params, spec)):
        k = (c["report"], c["fight_id"])
        casts[k][c["ability_id"]].append(c["t"])
        if c["target"]:
            targets[k].append((c["t"], target_kind(c["target"], bool(c["is_boss"]), main)))

    n = len(casts) or 1
    counts: dict[int, list[int]] = defaultdict(list)
    for per in casts.values():
        for a, ts in per.items():
            counts[a].append(len(ts))
    abilities = []
    for a, v in counts.items():
        med = st.median(v)
        if len(v) / n >= MIN_USERS and med / max(duration / 60, 1) <= MAX_CASTS_PER_MIN:
            abilities.append(Ability(a, names.get(a) or f"spell {a}", len(v) / n, med))
    for ab in abilities:
        ab.utility = any(h in ab.name.lower() for h in UTILITY_HINTS)
    abilities.sort(key=lambda x: (x.utility, -x.users, x.per_kill))
    for i, ab in enumerate(abilities):
        ab.color = PALETTE[i % len(PALETTE)] if not ab.utility else PALETTE[(i + 7) % len(PALETTE)]
    shown = {a.id for a in abilities}

    players = []
    for r in ranked[:top]:
        k = (r["report"], r["fight_id"])
        dur = next((f["duration_s"] for f in fights if (f["report"], f["fight_id"]) == k), duration)
        players.append({"rank": r["rank_pos"], "dps": r["dps"], "ilvl": r["ilvl"], "duration": dur,
                        "casts": {a: ts for a, ts in casts.get(k, {}).items() if a in shown},
                        "targets": target_segments(targets.get(k, []))})

    phases: dict[int, list] = defaultdict(list)
    for r in con.execute(f"SELECT p.* FROM phase p JOIN fight f USING(report, fight_id) WHERE {where}", params):
        phases[r["phase_id"]].append((r["t_start"], r["name"], r["is_intermission"]))
    phase_rows = [(v[0][1], st.median(x[0] for x in v), bool(v[0][2])) for _, v in sorted(phases.items())]

    rows = con.execute(
        f"SELECT a.report, a.fight_id, n.name, a.t_spawn, a.t_death, a.died, n.is_boss FROM add_instance a "
        f"JOIN npc n USING(game_id) JOIN fight f USING(report, fight_id) WHERE {where}", params).fetchall()
    rate: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        rate[r["name"]].append(r["died"])
    killable = {nm for nm, d in rate.items() if sum(d) / len(d) >= 0.5}
    spawns: dict[tuple[str, int], list] = defaultdict(list)
    for r in rows:
        if r["name"] in killable and not r["is_boss"] and r["t_spawn"] is not None:
            spawns[(r["report"], r["fight_id"])].append((r["t_spawn"], r["t_death"] - r["t_spawn"], r["name"]))
    waves = [(w.t, w.count, w.lifetime, ", ".join(w.types))
             for w in canonical_waves([fight_waves(spawns.get(k, [])) for k in keys])]

    # main boss abilities: enemy casts from units that are not tracked as adds
    add_actors = {(r[0], r[1], r[2]) for r in con.execute(
        f"SELECT a.report, a.fight_id, a.actor_id FROM add_instance a JOIN fight f USING(report, fight_id) "
        f"WHERE {where}", params)}
    per_ab: dict[str, dict[tuple[str, int], list[float]]] = defaultdict(lambda: defaultdict(list))
    spell_ids: dict[str, int] = {}
    for c in con.execute(
            f"SELECT e.report, e.fight_id, e.source_id, e.ability_id, e.t FROM enemy_cast e "
            f"JOIN fight f USING(report, fight_id) WHERE {where} AND e.type='cast' AND e.source_id >= 0", params):
        if (c["report"], c["fight_id"], c["source_id"]) not in add_actors:
            nm = names.get(c["ability_id"]) or f"spell {c['ability_id']}"
            per_ab[nm][(c["report"], c["fight_id"])].append(c["t"])
            spell_ids.setdefault(nm, c["ability_id"])
    boss_casts = []
    for a, per_kill in per_ab.items():
        if len(per_kill) / max(1, len(keys)) < 0.8:
            continue
        cw = canonical_waves([[(t, 1, 0.0, [""]) for t in ts] for ts in per_kill.values()])
        times = [w.t for w in cw]
        if 1 <= len(times) <= 40:
            boss_casts.append((a, times))
    boss_casts.sort(key=lambda x: x[1][0])

    return Timeline(boss_name, diff_name, spec, len(keys), duration, phase_rows, waves, abilities, players,
                    boss_casts, main, spell_ids)


def _mmss(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def render_html(tl: Timeline, px_per_s: float = 1.6) -> str:
    W = int(tl.duration * px_per_s) + 1
    LABEL = 190
    e = html.escape

    def x(t: float) -> float:
        return round(t * px_per_s, 1)

    def axis() -> str:
        return "".join(f'<line x1="{x(s)}" y1="0" x2="{x(s)}" y2="100%" class="grid"/>'
                       for s in range(0, int(tl.duration) + 1, 30))

    def ruler() -> str:
        body = "".join(f'<text x="{x(s) + 2}" y="12" class="tick">{_mmss(s)}</text>'
                       for s in range(0, int(tl.duration) + 1, 60))
        return (f'<div class="row"><div class="label" style="height:16px"></div>'
                f'<svg width="{W}" height="16">{axis()}{body}</svg></div>')

    def row(label: str, body: str, h: int = 22, sub: str = "", ref: str | None = None) -> str:
        if sub:
            h = max(h, 32)
        subl = f'<div class="sub">{e(sub)}</div>' if sub else ""
        dy = (h - 22) / 2
        return (f'<div class="row"><div class="label" style="height:{h}px"><div>{link(label, ref)}</div>{subl}</div>'
                f'<svg width="{W}" height="{h}">{axis()}<g transform="translate(0,{dy})">{body}</g></svg></div>')

    parts: list[str] = [ruler()]
    # phases
    body = []
    for i, (name, start, inter) in enumerate(tl.phases):
        end = tl.phases[i + 1][1] if i + 1 < len(tl.phases) else tl.duration
        cls = "inter" if inter else f"ph{i % 2}"
        short = name.split(":")[0]
        body.append(f'<rect x="{x(start)}" y="2" width="{max(1, x(end) - x(start))}" height="18" class="{cls}">'
                    f'<title>{e(name)} ({_mmss(start)})</title></rect>'
                    f'<text x="{x(start) + 4}" y="15" class="phl">{e(short)}</text>')
    parts.append(row("Phases", "".join(body)))
    # add waves
    body = []
    for t, count, life, types in tl.waves:
        body.append(f'<rect x="{x(t)}" y="3" width="{max(2, x(life))}" height="16" class="wave">'
                    f'<title>{_mmss(t)}: {count:.0f} adds alive ~{life:.0f}s ({e(types)})</title></rect>'
                    f'<text x="{x(t) + 2}" y="15" class="wl">{count:.0f}</text>')
    parts.append(row("Add waves", "".join(body), sub="count, bar = lifetime"))
    # boss abilities
    for name, times in tl.boss_casts[:12]:
        body = "".join(f'<line x1="{x(t)}" y1="4" x2="{x(t)}" y2="18" class="bc"><title>{_mmss(t)}</title></line>'
                       for t in times)
        sid = tl.boss_spell_ids.get(name)
        parts.append(row(name, body, h=22, ref=spell_ref(sid) if sid else None))

    # aggregated cooldown usage
    agg = [ruler()]
    util = [ruler()]
    nb = int(tl.duration // BIN) + 1
    for ab in tl.abilities:
        bins = [0] * nb
        for p in tl.players:
            for t in p["casts"].get(ab.id, []):
                if 0 <= t < tl.duration:
                    bins[int(t // BIN)] += 1
        peak = max(bins) or 1
        body = "".join(f'<rect x="{x(i * BIN)}" y="{22 - 20 * v / peak:.1f}" width="{x(BIN) - 0.5}" '
                       f'height="{20 * v / peak:.1f}" fill="{ab.color}"><title>{_mmss(i * BIN)}: {v} casts'
                       f'</title></rect>' for i, v in enumerate(bins) if v)
        (util if ab.utility else agg).append(
            row(ab.name, body, h=24, sub=f"{ab.users:.0%} use it, {ab.per_kill:g}/kill", ref=spell_ref(ab.id)))

    # targets: when the top players leave the main boss (share of players, per bin)
    kinds = sorted({k for p in tl.players for _, _, k in p.get("targets", []) if k}, key=lambda k: (k == ADDS, k))
    tcolor = {k: ("#2f9e44" if k == ADDS else TARGET_PALETTE[i % len(TARGET_PALETTE)]) for i, k in enumerate(kinds)}
    for k in kinds:
        bins = []
        for i in range(nb):
            mid = i * BIN + BIN / 2
            alive = [p for p in tl.players if p["duration"] > mid]
            on = sum(any(a <= mid <= b and kk == k for a, b, kk in p.get("targets", [])) for p in alive)
            bins.append(on / len(alive) if alive else 0)
        body = "".join(f'<rect x="{x(i * BIN)}" y="{22 - 20 * v:.1f}" width="{x(BIN) - 0.5}" height="{20 * v:.1f}" '
                       f'fill="{tcolor[k]}"><title>{_mmss(i * BIN)}: {v:.0%} of the players on {e(k)}</title></rect>'
                       for i, v in enumerate(bins) if v)
        parts.append(row(f"On {k}", body, h=24, sub="share of top players"))

    # per player
    players = [ruler()]
    for p in tl.players:
        body = [f'<rect x="{x(a)}" y="18.5" width="{max(1, x(b) - x(a))}" height="3.5" fill="{tcolor[k]}">'
                f'<title>{e(k)} {_mmss(a)}-{_mmss(b)}</title></rect>'
                for a, b, k in p.get("targets", []) if k]
        for ab in [a for a in tl.abilities if not a.utility]:
            for t in p["casts"].get(ab.id, []):
                body.append(f'<circle cx="{x(t)}" cy="11" r="4.5" fill="{ab.color}">'
                            f'<title>{e(ab.name)} {_mmss(t)}</title></circle>')
        end = f'<line x1="{x(p["duration"])}" y1="0" x2="{x(p["duration"])}" y2="22" class="end"/>'
        players.append(row(f"#{p['rank']}  {p['dps'] / 1000:,.0f}k", "".join(body) + end,
                           sub=f"ilvl {p['ilvl']:g}, {_mmss(p['duration'])}"))

    legend = "".join(f'<span class="lg"><i style="background:{a.color}"></i>{link(a.name, spell_ref(a.id))}</span>'
                     for a in tl.abilities if not a.utility)
    tlegend = "".join(f'<span class="lg"><i style="background:{c};border-radius:1px;height:4px"></i>on {e(k)}</span>'
                      for k, c in tcolor.items())
    if tlegend:
        tlegend = f'<div>Target strip under each player (nothing = on {e(tl.main_boss or tl.boss)}): {tlegend}</div>'
    lust_note = ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{e(tl.boss)} timelines</title>{WH_SCRIPT}
<style>
a.wh{{color:inherit;text-decoration:none;border-bottom:1px dotted var(--muted)}}
:root{{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--grid:#e6e3dc;--ph0:#e9eef7;--ph1:#dfe8f3;--inter:#f3e1d6;
--wave:#c9dfc4;--bc:#8a5a44;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16161a;--fg:#ececf0;--muted:#9a9aa3;--grid:#2a2a31;
--ph0:#20283a;--ph1:#1b2333;--inter:#3a2a22;--wave:#24402a;--bc:#d19a7a;--card:#1d1d22}}}}
body{{background:var(--bg);color:var(--fg);font:13px/1.4 system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:22px 0 6px}} p{{color:var(--muted);margin:0 0 10px}}
.scroll{{overflow-x:auto;background:var(--card);border-radius:8px;padding:8px 0}}
.row{{display:flex;align-items:center;min-width:max-content}}
.label{{width:{LABEL}px;flex:none;padding:0 10px;display:flex;flex-direction:column;justify-content:center;
position:sticky;left:0;background:var(--card);z-index:1;overflow:hidden;white-space:nowrap}}
.sub{{color:var(--muted);font-size:11px}}
.grid{{stroke:var(--grid);stroke-width:1}} .tick{{fill:var(--muted);font-size:10px}}
.ph0{{fill:var(--ph0)}} .ph1{{fill:var(--ph1)}} .inter{{fill:var(--inter)}} .phl{{fill:var(--fg);font-size:11px}}
.wave{{fill:var(--wave)}} .wl{{fill:var(--fg);font-size:10px}} .bc{{stroke:var(--bc);stroke-width:2}}
.end{{stroke:var(--muted);stroke-dasharray:2 2}}
.lg{{display:inline-flex;align-items:center;margin:0 12px 6px 0}} .lg i{{width:10px;height:10px;border-radius:50%;
display:inline-block;margin-right:5px}}
</style></head><body>
<h1>{e(tl.boss)} ({e(tl.difficulty)}): {e(tl.spec)} cooldown timelines</h1>
<p>{tl.kills} ranked kills, typical duration {_mmss(tl.duration)}. Cooldowns are detected automatically:
abilities used by at least {MIN_USERS:.0%} of players and cast at most {MAX_CASTS_PER_MIN:g} times per minute.
{lust_note}</p>
<div>{legend}</div>
<h2>The fight</h2><div class="scroll">{"".join(parts)}</div>
<h2>When the top players use each cooldown ({len(tl.players)} players, {BIN}s bins)</h2>
<div class="scroll">{"".join(agg)}</div>
<h2>Top players, one row each (rank, DPS): offensive cooldowns</h2>{tlegend}<div class="scroll">{"".join(players)}</div>
<h2>Defensives, movement and utility</h2>
<p>Movement abilities show where the fight forces players to move.</p>
<div class="scroll">{"".join(util)}</div>
<p style="margin-top:14px">Generated by prep-a-fight from Warcraft Logs data. Player names are not shown.</p>
</body></html>"""


def lifetimes_quantiles(values: list[float]) -> tuple[float, float, float]:
    return _q(values, .25), _q(values, .5), _q(values, .75)
