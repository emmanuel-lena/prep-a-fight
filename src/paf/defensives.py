"""When the top players of a spec press their defensives on a boss, and what hits them then (issue #1).

From the corpus: the ranked player's casts of personal defensives and healing consumables in each kill, clustered
into the typical moments of the fight; for each moment, how many of the kills have one, which defensives, and the
boss ability most often cast just before or after. SimC does not model survival: these are advice, not simmed.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from paf.corpus.analyze import kills_filter

# personal defensives by spell id (the name is a fallback for logs in another language), all classes: a spec only
# ever casts its own
DEFENSIVES: dict[int, str] = {
    # tanks' big defensives (issue #15)
    871: "Shield Wall", 12975: "Last Stand", 55233: "Vampiric Blood", 49028: "Dancing Rune Weapon",
    22842: "Frenzied Regeneration", 200851: "Rage of the Sleeper", 322507: "Celestial Brew",
    115176: "Zen Meditation", 132578: "Invoke Niuzao", 31850: "Ardent Defender", 86659: "Guardian of Ancient Kings",
    389539: "Sentinel", 187827: "Metamorphosis", 204021: "Fiery Brand", 196718: "Darkness",
    # Shaman
    108271: "Astral Shift", 108270: "Stone Bulwark Totem", 198103: "Earth Elemental",
    # Rogue
    31224: "Cloak of Shadows", 1966: "Feint", 5277: "Evasion", 185311: "Crimson Vial",
    # Mage
    45438: "Ice Block", 414659: "Ice Cold", 55342: "Mirror Image", 342245: "Alter Time", 108978: "Alter Time",
    235450: "Prismatic Barrier", 235313: "Blazing Barrier", 11426: "Ice Barrier",
    # Warlock
    104773: "Unending Resolve", 108416: "Dark Pact",
    # Priest
    47585: "Dispersion", 19236: "Desperate Prayer", 586: "Fade", 15286: "Vampiric Embrace",
    # Druid
    22812: "Barkskin", 61336: "Survival Instincts", 108238: "Renewal", 5487: "Bear Form",
    # Hunter
    186265: "Aspect of the Turtle", 264735: "Survival of the Fittest", 109304: "Exhilaration",
    # Paladin
    642: "Divine Shield", 498: "Divine Protection", 184662: "Shield of Vengeance",
    # Warrior
    118038: "Die by the Sword", 184364: "Enraged Regeneration", 97462: "Rallying Cry", 23920: "Spell Reflection",
    190456: "Ignore Pain",
    # Death Knight
    48707: "Anti-Magic Shell", 48792: "Icebound Fortitude", 49039: "Lichborne", 48743: "Death Pact",
    # Demon Hunter
    198589: "Blur", 196555: "Netherwalk",
    # Evoker
    363916: "Obsidian Scales", 374348: "Renewing Blaze",
    # Monk
    115203: "Fortifying Brew", 122470: "Touch of Karma", 122783: "Diffuse Magic",
    # everyone
    6262: "Healthstone",
}
CONSUMABLE_WORDS = ("health potion", "healing potion")
WINDOW = 8.0  # seconds around a moment that count as "at that moment"
BOSS_BEFORE, BOSS_AFTER = 3.0, 5.0  # a defensive is pressed a bit before the hit
FILLER = 25  # boss abilities cast more often than this per kill are fillers, not the reason for a defensive
SUPPORT = 0.25  # share of kills a moment needs


@dataclass
class DefensiveMoment:
    time: float  # seconds from the pull (median)
    share: float  # share of the kills where the top player pressed a defensive then
    spells: list[tuple[str, int, float]] = field(default_factory=list)  # name, spell id, share of those kills
    boss_ability: str = ""  # the boss ability most often cast around then
    boss_spell_id: int | None = None


def peaks(per_kill: list[list[float]], window: float = WINDOW, support: float = SUPPORT) -> list[float]:
    """Typical moments: the time when the most kills have a cast within +-window, then the next one once those
    casts are set aside, while at least `support` of the kills have one."""
    left = [sorted(ts) for ts in per_kill]
    out = []
    while True:
        best, best_n = None, 0
        for t in sorted({x for ts in left for x in ts}):
            n = sum(any(abs(x - t) <= window for x in ts) for ts in left)
            if n > best_n:
                best, best_n = t, n
        if best is None or best_n < support * len(per_kill):
            return sorted(out)
        near = sorted(x for ts in left for x in ts if abs(x - best) <= window)
        out.append(near[len(near) // 2])
        left = [[x for x in ts if abs(x - best) > window] for ts in left]


@dataclass
class Defensives:
    moments: list[DefensiveMoment] = field(default_factory=list)
    usage: list[tuple[str, int, float, float]] = field(default_factory=list)  # name, id, casts per kill, kill share
    kills: int = 0


def is_defensive(ability_id: int, name: str | None) -> bool:
    return ability_id in DEFENSIVES or any(w in (name or "").lower() for w in CONSUMABLE_WORDS)


def analyze(con: sqlite3.Connection, encounter_id: int, difficulty: int, spec: str) -> Defensives:
    where, params = kills_filter(encounter_id, difficulty)
    names = dict(con.execute("SELECT id, name FROM ability"))
    per_kill: dict[tuple[str, int], list[tuple[float, int]]] = defaultdict(list)
    kills = [tuple(r) for r in con.execute(
        f"SELECT f.report, f.fight_id FROM fight f JOIN ranked r USING(report, fight_id) WHERE {where} "
        f"AND r.spec=? AND r.actor_id IS NOT NULL", (*params, spec))]
    for rep, fid, aid, t in con.execute(
            f"SELECT c.report, c.fight_id, c.ability_id, c.t FROM player_cast c JOIN ranked r USING(report, fight_id) "
            f"JOIN fight f USING(report, fight_id) WHERE {where} AND r.spec=? AND c.actor_id=r.actor_id "
            f"AND c.type='cast'", (*params, spec)):
        if is_defensive(aid, names.get(aid)):
            per_kill[(rep, fid)].append((t, aid))
    if not kills:
        return Defensives()
    boss_casts: dict[tuple[str, int], list[tuple[float, int]]] = defaultdict(list)
    counts: Counter[int] = Counter()
    for rep, fid, aid, t in con.execute(
            f"SELECT e.report, e.fight_id, e.ability_id, e.t FROM enemy_cast e JOIN fight f USING(report, fight_id) "
            f"WHERE {where} AND e.type='cast'", params):
        boss_casts[(rep, fid)].append((t, aid))
        counts[aid] += 1
    fillers = {aid for aid, n in counts.items() if n / len(kills) > FILLER}

    moments = []
    for t in peaks([[x for x, _ in per_kill.get(k, [])] for k in kills]):
        near = {k: [(x, aid) for x, aid in per_kill.get(k, []) if abs(x - t) <= WINDOW] for k in kills}
        hit = [k for k, v in near.items() if v]
        if len(hit) / len(kills) < SUPPORT:
            continue
        spells = Counter(aid for k in hit for aid in {aid for _, aid in near[k]})
        reasons: Counter[int] = Counter()
        for k in hit:
            when = min(x for x, _ in near[k])
            reasons.update({aid for x, aid in boss_casts.get(k, []) if aid not in fillers
                            and when - BOSS_BEFORE <= x <= when + BOSS_AFTER})
        reason, n = reasons.most_common(1)[0] if reasons else (None, 0)
        if reason is not None and n < 0.4 * len(hit):
            reason = None
        moments.append(DefensiveMoment(
            round(t, 1), len(hit) / len(kills),
            [(DEFENSIVES.get(aid) or names.get(aid) or f"spell {aid}", aid, c / len(hit))
             for aid, c in spells.most_common(3)],
            names.get(reason, "") if reason else "", reason))
    casts: Counter[int] = Counter(aid for v in per_kill.values() for _, aid in v)
    used_in: Counter[int] = Counter(aid for v in per_kill.values() for aid in {a for _, a in v})
    usage = [(DEFENSIVES.get(aid) or names.get(aid) or f"spell {aid}", aid, n / len(kills), used_in[aid] / len(kills))
             for aid, n in casts.most_common() if used_in[aid] / len(kills) >= 0.1]
    return Defensives(moments, usage, len(kills))


def mrt_lines(d: Defensives) -> list[str]:
    """The defensive moments as MRT timers."""
    return [f"{{time:{int(m.time // 60)}:{int(m.time % 60):02d}}} Defensive: "
            + " / ".join(n for n, _, s in m.spells if s >= 0.2) + (f" - {m.boss_ability}" if m.boss_ability else "")
            for m in d.moments]


def nsrt_lines(d: Defensives, encounter_id: int, phases: list[tuple[str, float]], player: str) -> list[str]:
    """The defensive moments as NSRT reminders (the most used defensive of each moment)."""
    from paf.optimize import NSRT_UNSURE_AFTER, nsrt_phase

    out = []
    for m in d.moments:
        if not m.spells:
            continue
        ph, since = nsrt_phase(encounter_id, phases, m.time)
        limit = NSRT_UNSURE_AFTER.get((encounter_id, ph))
        if ph == 0 or (limit is not None and since > limit):
            continue
        out.append(f"time:{since:.1f};ph:{ph:g};tag:{player};spellid:{m.spells[0][1]};dur:5")
    return out
