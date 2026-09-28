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
