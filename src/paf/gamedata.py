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
