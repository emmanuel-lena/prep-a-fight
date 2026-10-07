"""Game names and Encounter Journal texts in the player's language (issue #2, part 3).

The pages are written with English game names (Warcraft Logs and the English game data). For another language,
an English -> localized table is built from the game's own data and applied when a page is sent (paf.i18n):
- the Encounter Journal of a boss in both languages, matched by section id: titles, texts, role bullets, boss name;
- spell and item names from Wowhead's tooltips in that language (by spell / item id).
The table is kept per WoW locale in <data>/cache/names-<locale>.json and grows with each prep.
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from paf.config import data_dir

# Wowhead tooltip locale numbers
WOWHEAD_LOCALES = {"enUS": 0, "koKR": 1, "frFR": 2, "deDE": 3, "zhCN": 4, "esES": 6, "ruRU": 7, "ptBR": 8, "itIT": 9}
TOOLTIP = "https://nether.wowhead.com/tooltip/{kind}/{id}?dataEnv=1&locale={loc}"


def _path(locale: str) -> Path:
    return data_dir() / "cache" / f"names-{locale}.json"


def load(locale: str) -> dict:
    """{"names": {english: localized}, "refs": {"spell=123": localized}}"""
    p = _path(locale)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"names": {}, "refs": {}}
    except ValueError:
        return {"names": {}, "refs": {}}


def _save(locale: str, data: dict) -> None:
    p = _path(locale)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def mapping(locale: str) -> dict[str, str]:
    return load(locale).get("names", {})


def _journal_pairs(encounter_id: int, difficulty: str, locale: str) -> dict[str, str]:
    from paf.bossguide import bullets
    from paf.mechanics import encounter_sections, walk

    out: dict[str, str] = {}
    en = {s.id: s for _, s in walk(encounter_sections(encounter_id))}
    loc = {s.id: s for _, s in walk(encounter_sections(encounter_id, locale))}
    from concurrent.futures import ThreadPoolExecutor

    from paf.bossguide import describe

    # the page shows a spell's own description when the journal has no text: both languages, fetched in parallel
    wanted = sorted({a.spell_id for a in en.values() if not a.text and a.spell_id})
    with ThreadPoolExecutor(max_workers=8) as pool:
        both = dict(zip(wanted, pool.map(lambda i: (describe(i), describe(i, locale)), wanted), strict=True))
    for da, db in both.values():
        if da and db and da != db:
            out[da] = db
    for sid, a in en.items():
        b = loc.get(sid)
        if b is None:
            continue
        if a.title and b.title and a.title != b.title and not re.match(r"Section\s*\d+$", b.title):
            out[a.title] = b.title
        if a.text and b.text and a.text != b.text:
            out[a.text] = b.text
            ba, bb = bullets(a.text), bullets(b.text)
            if len(ba) == len(bb) > 1:  # the role summaries are shown as bullets
                out.update({x: y for x, y in zip(ba, bb, strict=True) if x != y})
    out.update(_encounter_pairs(locale))
    return out


def _encounter_pairs(locale: str) -> dict[str, str]:
    """Every boss name, English -> localized (the Encounter Journal tables)."""
    from paf.gamedata import table_rows

    names = {r.get("DungeonEncounterID"): r.get("Name_lang") for r in table_rows("JournalEncounter")}
    local = {r.get("DungeonEncounterID"): r.get("Name_lang") for r in table_rows("JournalEncounter", locale=locale)}
    return {v: local[k] for k, v in names.items() if v and local.get(k) and local[k] != v}


def boss_names(locale: str) -> None:
    """The boss names in the player's language from the very first launch (the home page's boss list), once."""
    if locale == "enUS":
        return
    data = load(locale)
    if data.get("bosses"):
        return
    try:
        data.setdefault("names", {}).update(_encounter_pairs(locale))
    except Exception:  # noqa: BLE001 - offline: the names stay in English for now
        return
    data["bosses"] = True
    _save(locale, data)


def _tooltip_name(ref: str, locale: str) -> str:
    kind, _, id_ = ref.partition("=")
    id_ = id_.split("&")[0]
    if kind not in ("spell", "item") or not id_.isdigit():
        return ""
    url = TOOLTIP.format(kind=kind, id=id_, loc=WOWHEAD_LOCALES.get(locale, 0))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "prep-a-fight"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return str(json.loads(r.read()).get("name") or "")
    except (OSError, ValueError):
        return ""


def build(encounter_id: int | None, difficulty: str, refs: dict[str, str], locale: str) -> int:
    """Add a boss's journal and the given names (name -> Wowhead ref) to the table of `locale`; returns how many
    names it holds. Network errors leave the table as it was: the pages simply keep those names in English."""
    if locale == "enUS":
        return 0
    data = load(locale)
    names, by_ref = data.setdefault("names", {}), data.setdefault("refs", {})
    done = data.setdefault("journals", [])
    if encounter_id and f"{encounter_id}" not in done:  # once per boss (the journal changes with patches only)
        try:
            names.update(_journal_pairs(encounter_id, difficulty, locale))
            done.append(f"{encounter_id}")
        except Exception:  # noqa: BLE001 - no game data: the journal stays in English
            pass
    for name, ref in refs.items():
        if not name or not ref or "_" in name or name.islower():  # keys like "use_item:trinket1", not names
            continue
        if ref not in by_ref:
            by_ref[ref] = _tooltip_name(ref, locale)
        if by_ref[ref] and by_ref[ref] != name:
            names[name] = by_ref[ref]
    _save(locale, data)
    return len(names)
