"""Game data tables from wago.tools (DB2 exports as CSV), cached locally."""

from __future__ import annotations

import csv
import io
import time
import urllib.request
from functools import cache
from pathlib import Path

from paf.config import data_dir

WAGO_CSV = "https://wago.tools/db2/{table}/csv"
MAX_AGE = 7 * 86400


def _table_path(table: str, locale: str = "") -> Path:
    return data_dir() / "gamedata" / (f"{table}.{locale}.csv" if locale else f"{table}.csv")


def table_rows(table: str, max_age: float = MAX_AGE, locale: str = "") -> list[dict[str, str]]:
    """A DB2 table; locale (frFR, deDE...): its texts in that language (default: English)."""
    p = _table_path(table, locale)
    if not p.is_file() or time.time() - p.stat().st_mtime > max_age:
        url = WAGO_CSV.format(table=table) + (f"?locale={locale}" if locale else "")
        req = urllib.request.Request(url, headers={"User-Agent": "prep-a-fight"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


@cache
def spell_names(locale: str = "") -> dict[int, str]:
    return {int(r["ID"]): r["Name_lang"] for r in table_rows("SpellName", locale=locale) if r.get("ID", "").isdigit()}


@cache
def talent_entry_names() -> dict[int, str]:
    """TraitNodeEntry id (what Warcraft Logs reports as talentID) -> talent name."""
    spells = spell_names()
    defs: dict[int, str] = {}
    for r in table_rows("TraitDefinition"):
        name = r.get("OverrideName_lang") or ""
        if not name:
            sid = int(r.get("SpellID") or 0)
            name = spells.get(sid, "")
        if r.get("ID", "").isdigit():
            defs[int(r["ID"])] = name
    out: dict[int, str] = {}
    for r in table_rows("TraitNodeEntry"):
        if r.get("ID", "").isdigit():
            out[int(r["ID"])] = defs.get(int(r.get("TraitDefinitionID") or 0), "")
    return out


@cache
def talent_entries() -> dict[int, tuple[str, int, int, float, float]]:
    """TraitNodeEntry id -> (talent name, spell id, node id, x, y): to show a talent (icon, Wowhead tooltip) and to
    pair the talents two builds swap (the same choice node, else the nearest in the tree)."""
    spells = spell_names()
    defs: dict[int, tuple[str, int]] = {}
    for r in table_rows("TraitDefinition"):
        if r.get("ID", "").isdigit():
            sid = int(r.get("SpellID") or 0)
            defs[int(r["ID"])] = (r.get("OverrideName_lang") or spells.get(sid, ""), sid)
    node_of = {int(r["TraitNodeEntryID"]): int(r["TraitNodeID"]) for r in table_rows("TraitNodeXTraitNodeEntry")
               if r.get("TraitNodeEntryID", "").isdigit() and r.get("TraitNodeID", "").isdigit()}
    pos = {int(r["ID"]): (float(r.get("PosX") or 0), float(r.get("PosY") or 0)) for r in table_rows("TraitNode")
           if r.get("ID", "").isdigit()}
    out: dict[int, tuple[str, int, int, float, float]] = {}
    for r in table_rows("TraitNodeEntry"):
        if r.get("ID", "").isdigit():
            eid = int(r["ID"])
            name, sid = defs.get(int(r.get("TraitDefinitionID") or 0), ("", 0))
            node = node_of.get(eid, 0)
            x, y = pos.get(node, (0.0, 0.0))
            out[eid] = (name, sid, node, x, y)
    return out


# InventoryType values (Item.db2)
INV_ONE_HAND = 13
INV_SHIELD = 14
INV_RANGED = 15
INV_TWO_HAND = 17
INV_MAIN_HAND = 21
INV_OFF_HAND = 22
INV_HOLDABLE = 23
INV_RANGED_RIGHT = 26


@cache
def item_inventory_types() -> dict[int, int]:
    return {int(r["ID"]): int(r["InventoryType"] or 0) for r in table_rows("Item") if r.get("ID", "").isdigit()}


@cache
def item_sets() -> dict[int, tuple[int, str]]:
    """item id -> (set id, set name) for every item that belongs to a set (tier sets)."""
    out: dict[int, tuple[int, str]] = {}
    for r in table_rows("ItemSet"):
        if not r.get("ID", "").isdigit():
            continue
        for i in range(17):
            v = r.get(f"ItemID_{i}") or "0"
            if v.isdigit() and int(v):
                out[int(v)] = (int(r["ID"]), r.get("Name_lang", ""))
    return out


AURA_MOD_DAMAGE_PERCENT_TAKEN = 87
# Difficulty ids of the game data (Difficulty.db2)
GAME_DIFFICULTY = {"lfr": 17, "normal": 14, "heroic": 15, "mythic": 16}


def _filtered_rows(table: str, column: str, value: int, locale: str = "") -> list[dict[str, str]]:
    """A few rows of a big DB2 table, fetched with the wago.tools filter (cached per value); locale: its texts in
    that language."""
    suffix = f"-{locale}" if locale else ""
    p = data_dir() / "gamedata" / "filtered" / f"{table}-{column}-{value}{suffix}.csv"
    if not p.is_file():
        url = WAGO_CSV.format(table=table) + f"?filter[{column}]={value}" + (f"&locale={locale}" if locale else "")
        req = urllib.request.Request(url, headers={"User-Agent": "prep-a-fight"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if text.lstrip().startswith("{"):  # {"errors": ...}
        return []
    return list(csv.DictReader(io.StringIO(text)))


def damage_taken_amp(spell_id: int, difficulty: str = "heroic") -> float | None:
    """Multiplier of damage taken applied by a spell (aura 'mod damage % taken'), from the game data:
    e.g. Venomous Heart +100% -> 2.0. Difficulty-specific effects win over the default ones."""
    rows = [r for r in _filtered_rows("SpellEffect", "SpellID", spell_id)
            if r.get("EffectAura") == str(AURA_MOD_DAMAGE_PERCENT_TAKEN)]
    if not rows:
        return None
    want = str(GAME_DIFFICULTY.get(difficulty, 15))
    row = next((r for r in rows if r.get("DifficultyID") == want), None) or \
        next((r for r in rows if r.get("DifficultyID") in ("0", "")), None)
    if row is None:
        return None
    try:
        pct = float(row.get("EffectBasePointsF") or row.get("EffectBasePoints") or 0)
    except ValueError:
        return None
    return round(1 + pct / 100, 2) if pct > 0 else None


def spell_description(spell_id: int, locale: str = "") -> str:
    rows = _filtered_rows("Spell", "ID", spell_id, locale)
    return (rows[0].get("Description_lang") or "") if rows else ""


@cache
def item_names() -> dict[int, tuple[str, int]]:
    """item id -> (name, AllowableClass bitmask; -1 = every class)."""
    out: dict[int, tuple[str, int]] = {}
    for r in table_rows("ItemSearchName"):
        if r.get("ID", "").isdigit():
            try:
                allow = int(r.get("AllowableClass") or -1)
            except ValueError:
                allow = -1
            out[int(r["ID"])] = (r.get("Display_lang", ""), allow)
    return out


@cache
def item_classes() -> dict[int, tuple[int, int, int]]:
    """item id -> (ClassID, SubclassID, InventoryType)."""
    return {int(r["ID"]): (int(r["ClassID"] or 0), int(r["SubclassID"] or 0), int(r["InventoryType"] or 0))
            for r in table_rows("Item") if r.get("ID", "").isdigit()}


@cache
def encounter_loot() -> dict[int, tuple[str, list[int]]]:
    """Warcraft Logs / DungeonEncounter id -> (boss name, item ids of its Encounter Journal loot table)."""
    journal: dict[int, tuple[int, str]] = {}
    for r in table_rows("JournalEncounter"):
        if r.get("DungeonEncounterID", "").lstrip("-").isdigit() and r.get("ID", "").isdigit():
            journal[int(r["ID"])] = (int(r["DungeonEncounterID"]), r.get("Name_lang", ""))
    out: dict[int, tuple[str, list[int]]] = {}
    for r in table_rows("JournalEncounterItem"):
        if not r.get("JournalEncounterID", "").isdigit():
            continue
        je = journal.get(int(r["JournalEncounterID"]))
        if je:
            out.setdefault(je[0], (je[1], []))[1].append(int(r["ItemID"]))
    return out


def spell_cooldowns() -> dict[int, tuple[float, int]]:
    """Spell id -> (cooldown in seconds, charges): the longest of the spell's own and category cooldowns, or the
    recharge time of its charges. Base values: talents may shorten them."""
    cats = {r["ID"]: r for r in table_rows("SpellCategory")}
    charge_of = {r["SpellID"]: cats.get(r.get("ChargeCategory") or "") for r in table_rows("SpellCategories")
                 if r.get("ChargeCategory") not in (None, "", "0")}
    out: dict[int, tuple[float, int]] = {}
    for r in table_rows("SpellCooldowns"):
        if r.get("DifficultyID") not in (None, "", "0") or not r.get("SpellID", "").isdigit():
            continue
        cd = max(int(r.get("RecoveryTime") or 0), int(r.get("CategoryRecoveryTime") or 0)) / 1000
        if cd > 0:
            out[int(r["SpellID"])] = (cd, 1)
    for sid, cat in charge_of.items():
        if cat and sid.isdigit() and int(cat.get("MaxCharges") or 0) > 1 and int(cat.get("ChargeRecoveryTime") or 0):
            out[int(sid)] = (int(cat["ChargeRecoveryTime"]) / 1000, int(cat["MaxCharges"]))
    return out


def spell_durations() -> dict[int, float]:
    """Spell id -> base duration of its aura in seconds (spells whose duration grows with a resource, like a
    finisher's with combo points, are left out: their duration is read in the log)."""
    durations = {r["ID"]: r for r in table_rows("SpellDuration")}
    out: dict[int, float] = {}
    for r in table_rows("SpellMisc"):
        d = durations.get(r.get("DurationIndex") or "")
        if not d or not r.get("SpellID", "").isdigit() or r.get("DifficultyID") not in (None, "", "0"):
            continue
        if int(d.get("DurationPerResource") or 0) or int(d.get("Duration") or 0) <= 0:
            continue
        out[int(r["SpellID"])] = int(d["Duration"]) / 1000
    return out


def boss_display_ids() -> dict[int, int]:
    """Encounter id (Warcraft Logs' / DungeonEncounter) -> creature display id of its first boss in the Encounter
    Journal (for a portrait)."""
    journal = {r["ID"]: int(r["DungeonEncounterID"]) for r in table_rows("JournalEncounter")
               if (r.get("DungeonEncounterID") or "").isdigit()}
    out: dict[int, tuple[int, int]] = {}
    for r in table_rows("JournalEncounterCreature"):
        enc = journal.get(r.get("JournalEncounterID") or "")
        disp = int(r.get("CreatureDisplayInfoID") or 0)
        order = int(r.get("OrderIndex") or 0)
        if enc and disp and (enc not in out or order < out[enc][1]):
            out[enc] = (disp, order)
    return {k: v[0] for k, v in out.items()}
