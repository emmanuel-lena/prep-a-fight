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


def _table_path(table: str) -> Path:
    return data_dir() / "gamedata" / f"{table}.csv"


def table_rows(table: str, max_age: float = MAX_AGE) -> list[dict[str, str]]:
    p = _table_path(table)
    if not p.is_file() or time.time() - p.stat().st_mtime > max_age:
        req = urllib.request.Request(WAGO_CSV.format(table=table), headers={"User-Agent": "prep-a-fight"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


@cache
def spell_names() -> dict[int, str]:
    return {int(r["ID"]): r["Name_lang"] for r in table_rows("SpellName") if r.get("ID", "").isdigit()}


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


def _filtered_rows(table: str, column: str, value: int) -> list[dict[str, str]]:
    """A few rows of a big DB2 table, fetched with the wago.tools filter (cached per value)."""
    p = data_dir() / "gamedata" / "filtered" / f"{table}-{column}-{value}.csv"
    if not p.is_file():
        url = WAGO_CSV.format(table=table) + f"?filter[{column}]={value}"
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


def spell_description(spell_id: int) -> str:
    rows = _filtered_rows("Spell", "ID", spell_id)
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
