"""A boss as the game data describes it, before any log (the owner, 2026-11-12: "get more from the journal before the
logs"): its stages, each ability with what its spell does (read from its spell effects, not its text), its cast time,
its duration, its relative size in each difficulty, Blizzard's own warning severity, and the adds under the abilities
that bring them. paf.demands reads what the fight asks of a raid from it; the logs only add what the game data cannot
say (when, how fast the top raids answer, the scale of the sizes).

Coiled Altar mythic, from the game data alone: Eternal Nightfall, a 17 s cast, deadly, severity 2; under it Veil of
Twilight, an absorb on its caster of 4902 units (mythic; heroic 1472): a shield to break within the cast."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache

# SpellEffect.Effect and SpellEffect.EffectAura values read here
SCHOOL_DAMAGE, APPLY_AURA, TRIGGER_SPELL = 2, 6, 64
AURA_PERIODIC_DAMAGE, AURA_SCHOOL_ABSORB, AURA_DAMAGE_TAKEN, AURA_HEAL_ABSORB = 3, 69, 87, 301
TARGET_CASTER = 1
IMMUNE = -90.0  # % damage taken at most: the unit is out of reach (Tether of Awakening -99%)
SEVERITY = {0: "low", 1: "medium", 2: "high"}  # EncounterEvent.Severity, Blizzard's own boss warnings


@dataclass
class Effect:
    kind: str  # "damage" | "dot" | "shield" | "heal_absorb" | "damage_taken" | "other"
    size: float  # EffectBasePointsF for the difficulty (game units; damage taken: %)
    on_caster: bool


@dataclass
class Ability:
    spell: int
    name: str
    stage: str
    creature: str  # the add it belongs to ("" for the boss's own)
    flags: list[str]
    severity: int | None  # 0-2, Blizzard's warning severity; None: not warned
    cast: float  # seconds (0: instant)
    duration: float | None  # seconds; None: until removed
    effects: list[Effect]
    parent: int = 0  # the ability it comes under in the journal (Veil of Twilight under Eternal Nightfall)

    def has(self, kind: str, on_caster: bool | None = None) -> list[Effect]:
        return [x for x in self.effects if x.kind == kind and (on_caster is None or x.on_caster == on_caster)]


@dataclass
class Creature:
    name: str
    stage: str
    summoner: int  # the ability it comes under (Spawn of Vexhul under Venomous Emergence), 0: a stage's own


@dataclass
class Model:
    encounter_id: int
    difficulty: str
    stages: list[str] = field(default_factory=list)
    abilities: list[Ability] = field(default_factory=list)
    creatures: list[Creature] = field(default_factory=list)

    def ability(self, spell: int) -> Ability | None:
        return next((a for a in self.abilities if a.spell == spell), None)


@cache
def _severities() -> dict[int, int]:
    from paf.gamedata import table_rows

    try:
        return {int(r["SpellID"]): int(r.get("Severity") or 0) for r in table_rows("EncounterEvent")
                if r.get("SpellID", "").isdigit()}
    except Exception:  # noqa: BLE001 - offline: no severity
        return {}


@cache
def _times() -> tuple[dict[str, float], dict[str, float | None]]:
    """Cast time index -> seconds, duration index -> seconds (None: until removed)."""
    from paf.gamedata import table_rows

    casts = {r["ID"]: int(r.get("Base") or 0) / 1000 for r in table_rows("SpellCastTimes")}
    durs = {r["ID"]: (None if int(r.get("Duration") or 0) < 0 else int(r.get("Duration") or 0) / 1000)
            for r in table_rows("SpellDuration")}
    return casts, durs


FOREVER = 3600.0  # seconds: a longer duration (a week, for an aura the fight removes) is "until removed"


def _duration(durs: dict[str, float | None], index: str) -> float | None:
    d = durs.get(index, 0.0)
    return None if d is None or d >= FOREVER else d


def effects_of(rows: list[dict], difficulty: str) -> list[Effect]:
    """A spell's effects for a difficulty: its own rows (DifficultyID) over the default ones, by effect index."""
    from paf.gamedata import GAME_DIFFICULTY

    want = str(GAME_DIFFICULTY.get(difficulty, 15))
    by: dict[str, dict] = {}
    for r in rows:
        if r.get("DifficultyID") in ("0", "", None):
            by.setdefault(r.get("EffectIndex", "0"), r)
    for r in rows:
        if r.get("DifficultyID") == want:
            by[r.get("EffectIndex", "0")] = r
    out = []
    for _i, r in sorted(by.items()):
        eff, aura = int(r.get("Effect") or 0), int(r.get("EffectAura") or 0)
        size = float(r.get("EffectBasePointsF") or 0)
        on_caster = r.get("ImplicitTarget_0") == str(TARGET_CASTER)
        kind = ("damage" if eff == SCHOOL_DAMAGE else
                {AURA_PERIODIC_DAMAGE: "dot", AURA_SCHOOL_ABSORB: "shield", AURA_HEAL_ABSORB: "heal_absorb",
                 AURA_DAMAGE_TAKEN: "damage_taken"}.get(aura, "other") if eff == APPLY_AURA else "other")
        out.append(Effect(kind, size, on_caster))
    return out


@cache
def journal_creatures(encounter_id: int) -> frozenset[str]:
    """The units the journal lists for a boss (its bosses and its adds), by name."""
    from paf.gamedata import table_rows

    try:
        jid = next((r["ID"] for r in table_rows("JournalEncounter")
                    if r.get("DungeonEncounterID") == str(encounter_id)), None)
        return frozenset(r.get("Name_lang") or "" for r in table_rows("JournalEncounterCreature")
                         if jid and r.get("JournalEncounterID") == jid)
    except Exception:  # noqa: BLE001 - offline: none known
        return frozenset()


def build(encounter_id: int, difficulty: str) -> Model:
    """The model of a boss for a difficulty, from the Encounter Journal and the spell tables (no log)."""
    from paf.gamedata import _filtered_rows
    from paf.mechanics import dedupe, encounter_sections

    m = Model(encounter_id, difficulty)
    sections = dedupe(encounter_sections(encounter_id), difficulty)
    casts, durs = _times()
    sev = _severities()
    units = journal_creatures(encounter_id)
    seen: set[tuple[int, str]] = set()

    def walk(xs, stage: str, creature: str, parent: int, depth: int) -> None:
        for s in xs:
            if not s.for_difficulty(difficulty) or s.kind == "overview":
                continue
            if not s.spell_id and s.title not in units and depth == 0:  # "Stage Two: Usurper's Reprisal"
                m.stages.append(s.title)
                walk(s.children, s.title, "", 0, depth + 1)
                continue
            if not s.spell_id:  # a unit (Spawn of Vexhul) or a thing of the fight (Virulent Cyst)
                if (s.title, stage) not in {(c.name, c.stage) for c in m.creatures}:
                    m.creatures.append(Creature(s.title, stage, parent))
                walk(s.children, stage, s.title, parent, depth + 1)
                continue
            if (s.spell_id, stage) not in seen:
                seen.add((s.spell_id, stage))
                misc = next(iter(_filtered_rows("SpellMisc", "SpellID", s.spell_id)), {})
                m.abilities.append(Ability(
                    s.spell_id, s.title, stage, creature, list(s.flags), sev.get(s.spell_id),
                    casts.get(misc.get("CastingTimeIndex", ""), 0.0), _duration(durs, misc.get("DurationIndex", "")),
                    effects_of(_filtered_rows("SpellEffect", "SpellID", s.spell_id), difficulty), parent))
            walk(s.children, stage, creature, s.spell_id, depth + 1)
    walk(sections, "", "", 0, 0)
    if not m.stages:  # a boss without stages: one, unnamed
        m.stages.append("")
    return m
