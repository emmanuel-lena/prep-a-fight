"""Boss mechanics from the in-game Encounter Journal (wago.tools JournalEncounterSection)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from paf.gamedata import spell_names, table_rows

# Encounter Journal icon flags
FLAGS = {
    1: "tank", 2: "damage", 4: "healer", 8: "heroic", 16: "deadly", 32: "important", 64: "interruptible",
    128: "magic", 256: "curse", 512: "poison", 1024: "disease", 2048: "enrage", 4096: "mythic", 8192: "bleed",
}
SECTION_TYPES = {0: "stage", 1: "creature", 2: "ability", 3: "overview"}
# DifficultyMask bits of the journal (-1 = every difficulty)
DIFFICULTY_BITS = {"lfr": 1 << 17, "normal": 1 << 14, "heroic": 1 << 15, "mythic": 1 << 16}


def clean_text(text: str, mythic: bool = True) -> str:
    """Strip the journal markup: spell links, colors, bullets, difficulty-conditional parts."""
    if not text:
        return ""
    # $[!16 ...$] = shown only on mythic (16 = difficulty id); $[16 ...$] variants
    text = re.sub(r"\$\[!?[\d,]+\s*(.*?)\$\]", (r"\1" if mythic else ""), text, flags=re.S)
    text = re.sub(r"\|c[0-9A-Fa-f]{8}\|Hspell:\d+\|h\[([^\]]*)\]\|h\|r", r"\1", text)
    text = re.sub(r"\|c[0-9A-Fa-f]{8}|\|r|\|H[^|]*\|h|\|h", "", text)
    text = text.replace("$bullet;", "-")
    text = re.sub(r"\$[a-zA-Z0-9]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Section:
    id: int
    title: str
    kind: str  # stage | creature | ability | overview
    spell_id: int
    flags: list[str]
    text: str
    parent: int
    order: int
    difficulty_mask: int
    children: list[Section] = field(default_factory=list)

    def for_difficulty(self, difficulty: str) -> bool:
        if "mythic" in self.flags and difficulty != "mythic":
            return False
        if "heroic" in self.flags and difficulty in ("lfr", "normal"):
            return False
        if self.difficulty_mask in (-1, 0):
            return True
        return bool(self.difficulty_mask & DIFFICULTY_BITS.get(difficulty, 0))


def encounter_sections(encounter_id: int) -> list[Section]:
    """Top-level journal sections of a boss (Warcraft Logs / DungeonEncounter id), as a tree."""
    journal_id = None
    for r in table_rows("JournalEncounter"):
        if r.get("DungeonEncounterID") == str(encounter_id):
            journal_id = r["ID"]
            break
    if journal_id is None:
        return []
    names = spell_names()
    by_id: dict[int, Section] = {}
    for r in table_rows("JournalEncounterSection"):
        if r.get("JournalEncounterID") != journal_id:
            continue
        sid = int(r.get("SpellID") or 0)
        flags_v = int(r.get("IconFlags") or 0)
        title = r.get("Title_lang") or ""
        if (not title or title.startswith("Section ")) and sid:
            title = names.get(sid, title)
        by_id[int(r["ID"])] = Section(
            int(r["ID"]), title, SECTION_TYPES.get(int(r.get("Type") or 0), "?"), sid,
            [n for b, n in FLAGS.items() if flags_v & b], clean_text(r.get("BodyText_lang") or ""),
            int(r.get("ParentSectionID") or 0), int(r.get("OrderIndex") or 0), int(r.get("DifficultyMask") or -1))
    roots = []
    for s in sorted(by_id.values(), key=lambda s: s.order):
        parent = by_id.get(s.parent)
        (parent.children if parent else roots).append(s)
    return roots


def _specificity(s: Section, difficulty: str) -> int:
    return (2 if difficulty in s.flags else 0) + (1 if s.difficulty_mask != -1 else 0) + len(s.text) // 1000


def dedupe(sections: list[Section], difficulty: str = "heroic") -> list[Section]:
    """The journal repeats sections per difficulty: keep one per (title, spell), the most specific one."""
    best: dict[tuple[str, int], Section] = {}
    order: list[tuple[str, int]] = []
    for s in sections:
        if not s.for_difficulty(difficulty):
            continue
        k = (s.title, s.spell_id)
        if k not in best:
            order.append(k)
            best[k] = s
        elif _specificity(s, difficulty) > _specificity(best[k], difficulty):
            best[k] = s
    out = []
    for k in order:
        s = best[k]
        s.children = dedupe(s.children, difficulty)
        out.append(s)
    return out


def walk(sections: list[Section], depth: int = 0):
    for s in sections:
        yield depth, s
        yield from walk(s.children, depth + 1)


def abilities(sections: list[Section], difficulty: str = "heroic") -> list[Section]:
    """Every ability section with a spell, for a difficulty (deduplicated by spell)."""
    out, seen = [], set()
    for _, s in walk(sections):
        if s.kind == "ability" and s.spell_id and s.for_difficulty(difficulty) and s.spell_id not in seen:
            seen.add(s.spell_id)
            out.append(s)
    return out


def format_sections(sections: list[Section], difficulty: str = "heroic", width: int = 110) -> str:
    lines = []
    for depth, s in walk(dedupe(sections, difficulty)):
        if not s.for_difficulty(difficulty):
            continue
        tags = f" [{', '.join(s.flags)}]" if s.flags else ""
        head = f"{'  ' * depth}{'- ' if s.kind == 'ability' else ''}{s.title}{tags}"
        if s.spell_id:
            head += f"  (spell {s.spell_id})"
        lines.append(head)
        if s.text and s.kind in ("overview", "ability", "creature"):
            lines.append(f"{'  ' * depth}    {s.text[:width]}{'...' if len(s.text) > width else ''}")
    return "\n".join(lines)
