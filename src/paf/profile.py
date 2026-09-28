"""Parse the in-game SimulationCraft addon export (``/simc``).

Layout (from the addon source):
- character header: ``shaman="Name"``, ``spec=``, ``level=``, ``talents=``...
- equipped gear: ``head=,id=...,bonus_id=...``
- ``### Gear from Bags``: per item ``#``, ``# Name (ilvl)``, optional ``# upgrade_levels=...``,
  then ``# slot=,id=...``
- ``### Weekly Reward Choices`` ... ``### End of Weekly Reward Choices``: same item format
- ``### Linked gear`` (``/simc [item link]``): same format, name without ilvl
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SLOTS = (
    "head", "neck", "shoulder", "back", "chest", "shirt", "tabard", "wrist", "hands", "waist",
    "legs", "feet", "finger1", "finger2", "trinket1", "trinket2", "main_hand", "off_hand",
)
CLASSES = (
    "warrior", "paladin", "hunter", "rogue", "priest", "deathknight", "shaman", "mage",
    "warlock", "monk", "druid", "demonhunter", "evoker",
)

_NAME_ILVL = re.compile(r"^(?P<name>.*?)\s*\((?P<ilvl>\d+)\)\s*$")


@dataclass
class Item:
    slot: str
    line: str  # raw simc value after "slot=", e.g. ",id=123,bonus_id=1/2"
    name: str = ""
    ilvl: int | None = None
    source: str = "equipped"  # equipped | bags | vault | linked

    @property
    def fields(self) -> dict[str, str]:
        out = {}
        for part in self.line.split(","):
            k, sep, v = part.partition("=")
            if sep and k:
                out[k.strip()] = v.strip()
        return out

    @property
    def item_id(self) -> int | None:
        v = self.fields.get("id")
        return int(v) if v and v.isdigit() else None

    def simc(self) -> str:
        return f"{self.slot}={self.line}"


@dataclass
class Profile:
    class_name: str = ""
    name: str = ""
    spec: str = ""
    header: dict[str, str] = field(default_factory=dict)
    equipped: dict[str, Item] = field(default_factory=dict)
    candidates: list[Item] = field(default_factory=list)

    def by_source(self, source: str) -> list[Item]:
        return [i for i in self.candidates if i.source == source]


def _split_slot(text: str) -> tuple[str, str] | None:
    key, sep, value = text.partition("=")
    key = key.strip()
    if sep and key in SLOTS:
        return key, value.strip()
    return None


def parse_simc_export(text: str) -> Profile:
    p = Profile()
    source: str | None = None
    pending_name, pending_ilvl = "", None

    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line:
            continue

        if line.startswith("###"):
            title = line.lstrip("#").strip().lower()
            if title.startswith("gear from bags"):
                source = "bags"
            elif title.startswith("end of weekly reward"):
                source = None
            elif title.startswith("weekly reward"):
                source = "vault"
            elif title.startswith("linked gear"):
                source = "linked"
            else:
                source = None
            pending_name, pending_ilvl = "", None
            continue

        if line.startswith("#"):
            body = line[1:].strip()
            if source is None or not body:
                if not body:
                    pending_name, pending_ilvl = "", None
                continue
            slot = _split_slot(body)
            if slot:
                p.candidates.append(Item(slot[0], slot[1], pending_name, pending_ilvl, source))
                pending_name, pending_ilvl = "", None
            elif "=" not in body.split(" ", 1)[0]:
                m = _NAME_ILVL.match(body)
                pending_name = m.group("name") if m else body
                pending_ilvl = int(m.group("ilvl")) if m else None
            continue

        slot = _split_slot(line)
        if slot:
            p.equipped[slot[0]] = Item(slot[0], slot[1])
            continue

        key, sep, value = line.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key in CLASSES and not p.class_name:
            p.class_name, p.name = key, value.strip('"')
        elif key == "spec":
            p.spec = value
        p.header[key] = value
    return p


def looks_like_export(text: str) -> bool:
    p = parse_simc_export(text)
    return bool(p.class_name and p.equipped)
