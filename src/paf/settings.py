"""User settings stored in <data_dir>/settings.json (``paf config``)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from paf.config import data_dir

DIFFICULTIES = {"lfr": 1, "normal": 3, "heroic": 4, "mythic": 5}


@dataclass(frozen=True)
class Setting:
    default: Any
    help: str
    choices: tuple[str, ...] | None = None
    kind: type = str


SETTINGS: dict[str, Setting] = {
    "difficulty": Setting("heroic", "default raid difficulty", tuple(DIFFICULTIES)),
    "class": Setting("Shaman", "class analyzed by default (Warcraft Logs name)"),
    "spec": Setting("Elemental", "spec analyzed by default (Warcraft Logs name)"),
    "corpus_size": Setting(200, "number of kills collected per boss", kind=int),
    "cache_max_mb": Setting(2000, "disk cache cap in MB (sim results + Warcraft Logs responses)", kind=int),
    "guild": Setting("", "your guild's name: its latest log gives your raid's composition (pad the adds or not)"),
    "guild_server": Setting("", "your guild's server (e.g. Kazzak)"),
    "guild_region": Setting("eu", "your guild's region", ("eu", "us", "kr", "tw", "cn")),
    "region": Setting("", "restrict rankings to a region (EU, US, KR, TW, CN); empty = all"),
    "check_updates": Setting("on", "look for a new version of the app once a day", ("on", "off")),
}


def _path():
    return data_dir() / "settings.json"


def load() -> dict[str, Any]:
    values = {k: s.default for k, s in SETTINGS.items()}
    p = _path()
    if p.is_file():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            saved = {}
        values.update({k: v for k, v in saved.items() if k in SETTINGS})
    return values


def get(key: str) -> Any:
    return load()[key]


def set_value(key: str, raw: str) -> Any:
    if key not in SETTINGS:
        raise KeyError(f"unknown setting {key!r} (known: {', '.join(SETTINGS)})")
    s = SETTINGS[key]
    value: Any = raw.strip()
    if s.choices:
        value = value.lower()
        if value not in s.choices:
            raise ValueError(f"{key} must be one of: {', '.join(s.choices)}")
    if s.kind is int:
        value = int(value)
    p = _path()
    saved = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    saved[key] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    return value
