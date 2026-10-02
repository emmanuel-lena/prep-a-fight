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
        return '<span class="ics ph"></span>' if size == "small" else ""
    return (f'<img class="{cls}" src="{CDN.format(size=size, icon=icon)}" alt="{alt}" '
            f'onerror="this.style.visibility=\'hidden\'">')
