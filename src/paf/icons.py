"""Game icons of spells and items (Wowhead's public tooltip data), cached on disk; images from Wowhead's CDN.

Without network the pages simply show no icon.
"""

from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from paf.config import data_dir

TOOLTIP = "https://nether.wowhead.com/tooltip/{kind}/{id}?dataEnv=1&locale=0"
CDN = "https://wow.zamimg.com/images/wow/icons/{size}/{icon}.jpg"
CLASS_ICON = "classicon_{cls}"


def class_key(spec: str) -> str:
    """"Frost Death Knight" / "Frost DeathKnight" / "Havoc Demon Hunter" -> "deathknight" / "demonhunter"; the last
    word otherwise ("Arcane Mage" -> "mage"): a two-word class never reads as its last word ("knight")."""
    low = (spec or "").lower().replace(" ", "")
    for two in ("deathknight", "demonhunter"):
        if low.endswith(two):
            return two
    return (spec or "").split(" ")[-1].lower()


# a spec's own icon (the talent window's), so Blood, Frost and Unholy read apart (fresh app review 7); each checked
# on the icon CDN
SPEC_ICON = {
    ("blood", "deathknight"): "spell_deathknight_bloodpresence",
    ("frost", "deathknight"): "spell_deathknight_frostpresence",
    ("unholy", "deathknight"): "spell_deathknight_unholypresence",
    ("havoc", "demonhunter"): "ability_demonhunter_specdps",
    ("vengeance", "demonhunter"): "ability_demonhunter_spectank",
    ("devourer", "demonhunter"): "classicon_demonhunter_void",
    ("balance", "druid"): "spell_nature_starfall",
    ("feral", "druid"): "ability_druid_catform",
    ("guardian", "druid"): "ability_racial_bearform",
    ("restoration", "druid"): "spell_nature_healingtouch",
    ("devastation", "evoker"): "classicon_evoker_devastation",
    ("preservation", "evoker"): "classicon_evoker_preservation",
    ("augmentation", "evoker"): "classicon_evoker_augmentation",
    ("beastmastery", "hunter"): "ability_hunter_bestialdiscipline",
    ("marksmanship", "hunter"): "ability_hunter_focusedaim",
    ("survival", "hunter"): "ability_hunter_camouflage",
    ("arcane", "mage"): "spell_holy_magicalsentry",
    ("fire", "mage"): "spell_fire_firebolt02",
    ("frost", "mage"): "spell_frost_frostbolt02",
    ("brewmaster", "monk"): "spell_monk_brewmaster_spec",
    ("mistweaver", "monk"): "spell_monk_mistweaver_spec",
    ("windwalker", "monk"): "spell_monk_windwalker_spec",
    ("holy", "paladin"): "spell_holy_holybolt",
    ("protection", "paladin"): "ability_paladin_shieldofthetemplar",
    ("retribution", "paladin"): "spell_holy_auraoflight",
    ("discipline", "priest"): "spell_holy_powerwordshield",
    ("holy", "priest"): "spell_holy_guardianspirit",
    ("shadow", "priest"): "spell_shadow_shadowwordpain",
    ("assassination", "rogue"): "ability_rogue_deadlybrew",
    ("outlaw", "rogue"): "ability_rogue_waylay",
    ("subtlety", "rogue"): "ability_stealth",
    ("elemental", "shaman"): "spell_nature_lightning",
    ("enhancement", "shaman"): "spell_shaman_improvedstormstrike",
    ("restoration", "shaman"): "spell_nature_magicimmunity",
    ("affliction", "warlock"): "spell_shadow_deathcoil",
    ("demonology", "warlock"): "spell_shadow_metamorphosis",
    ("destruction", "warlock"): "spell_shadow_rainoffire",
    ("arms", "warrior"): "ability_warrior_savageblow",
    ("fury", "warrior"): "ability_warrior_innerrage",
    ("protection", "warrior"): "ability_warrior_defensivestance",
}


def spec_icon(spec: str) -> str:
    """"Frost Death Knight" / "Frost DeathKnight" / "BeastMastery Hunter" -> its spec's icon; '' when unknown."""
    cls = class_key(spec)
    words = (spec or "").replace(" ", "").lower()
    sp = words[: len(words) - len(cls)] if words.endswith(cls) else ""
    return SPEC_ICON.get((sp, cls), "")


def spec_any(spec: str, size: str = "medium", cls: str = "it-ic") -> str:
    """A spec's icon from "Subtlety Rogue" or Warcraft Logs' "Rogue-Subtlety"; its class's when the spec is unknown."""
    if "-" in (spec or ""):
        c, _, sp = spec.partition("-")
        spec = f"{sp} {c}"
    key = class_key(spec)
    return img(spec_icon(spec) or CLASS_ICON.format(cls=key), size, cls) if key else ""


def spec_img(spec: str, cls: str = "ics") -> str:
    """A spec's small icon with a ring of its class's colour, so purple and blue squares read apart at 16 px (fresh
    app review 7); its class icon when the spec is unknown; '' when there is no class."""
    from paf.theme import CLASS_COLORS

    key = class_key(spec)
    if not key:
        return ""
    colour = CLASS_COLORS.get(key, "")
    ring = f' style="box-shadow:0 0 0 1.5px {colour}"' if colour else ""
    return img(spec_icon(spec) or CLASS_ICON.format(cls=key), "small", cls, "").replace("<img ", f"<img{ring} ", 1)


def _cache_path() -> Path:
    return data_dir() / "cache" / "icons.json"


def _load() -> dict[str, str]:
    p = _cache_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        return {}


def _fetch(kind: str, id_: int) -> str:
    req = urllib.request.Request(TOOLTIP.format(kind=kind, id=id_), headers={"User-Agent": "prep-a-fight"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return str(json.loads(r.read().decode("utf-8")).get("icon") or "")
    except (OSError, ValueError):
        return ""


def ref_key(ref: str) -> tuple[str, int] | None:
    """'item=123&ilvl=..' / 'spell=456' -> ('item', 123)."""
    m = re.match(r"(spell|item)=(\d+)", ref or "")
    return (m.group(1), int(m.group(2))) if m else None


def icons_for(refs: dict[str, str]) -> dict[str, str]:
    """Name -> icon file name for every Wowhead reference (fetched once, in parallel, then cached)."""
    cache = _load()
    keys = {name: ref_key(ref) for name, ref in refs.items()}
    todo = sorted({k for k in keys.values() if k and f"{k[0]}:{k[1]}" not in cache})
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for k, icon in zip(todo, pool.map(lambda k: _fetch(*k), todo), strict=True):
                cache[f"{k[0]}:{k[1]}"] = icon
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache), encoding="utf-8")
    return {name: cache.get(f"{k[0]}:{k[1]}", "") for name, k in keys.items() if k and cache.get(f"{k[0]}:{k[1]}")}


def img(icon: str, size: str = "medium", cls: str = "", alt: str = "") -> str:
    """An <img> of a game icon. size: small (an inline 18px icon; an empty slot when unknown, so names stay
    aligned), medium (36px), large (56px; '' when unknown)."""
    cls = cls or ("ics" if size == "small" else "ic")
    if not icon:
        return '<span class="ics ics-ph"></span>' if size == "small" else ""
    return (f'<img class="{cls}" src="{CDN.format(size=size, icon=icon)}" alt="{alt}" loading="lazy" '
            f'onerror="this.style.visibility=\'hidden\'">')
