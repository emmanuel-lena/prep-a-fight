"""Decode WoW talent loadout strings (the in-game / SimC `talents=` export) into talent choices.

Format (Blizzard_ClassTalentImportExport.lua): base64 alphabet, bits read least-significant first.
Header: version (8 bits), spec id (16), tree hash (128). Then, for every node of the class tree in
ascending node id order: selected (1); if selected: purchased (1); if purchased: partially ranked (1)
[+ rank (6)], choice node (1) [+ choice index (2)].
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cache

from paf.gamedata import table_rows, talent_entry_names

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


class TalentError(ValueError):
    pass


class _Bits:
    def __init__(self, text: str):
        self.bits: list[int] = []
        for ch in text.strip():
            v = ALPHABET.find(ch)
            if v < 0:
                raise TalentError(f"invalid character {ch!r} in talent string")
            self.bits += [(v >> i) & 1 for i in range(6)]
        self.pos = 0

    def read(self, n: int) -> int:
        if self.pos + n > len(self.bits):
            raise TalentError("talent string too short for this talent tree")
        v = sum(self.bits[self.pos + i] << i for i in range(n))
        self.pos += n
        return v

    @property
    def remaining(self) -> int:
        return len(self.bits) - self.pos


@dataclass(frozen=True)
class Choice:
    node_id: int
    entry_id: int
    rank: int
    granted: bool = False  # selected for free (not purchased)


@cache
def _tree_data() -> tuple[dict[int, int], dict[int, list[int]], dict[int, int], dict[int, list[int]]]:
    """node -> tree, node -> entries (by index), entry -> max ranks, tree -> sorted nodes."""
    node_tree: dict[int, int] = {}
    tree_nodes: dict[int, list[int]] = defaultdict(list)
    for r in table_rows("TraitNode"):
        if r.get("ID", "").isdigit():
            n, t = int(r["ID"]), int(r["TraitTreeID"] or 0)
            node_tree[n] = t
            tree_nodes[t].append(n)
    for nodes in tree_nodes.values():
        nodes.sort()
    entries: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for r in table_rows("TraitNodeXTraitNodeEntry"):
        if r.get("TraitNodeID", "").isdigit():
            entries[int(r["TraitNodeID"])].append((int(r.get("_Index") or 0), int(r["TraitNodeEntryID"])))
    node_entries = {n: [e for _, e in sorted(v)] for n, v in entries.items()}
    max_ranks = {int(r["ID"]): int(r.get("MaxRanks") or 1) for r in table_rows("TraitNodeEntry")
                 if r.get("ID", "").isdigit()}
    return node_tree, node_entries, max_ranks, dict(tree_nodes)


def tree_for_entries(entry_ids: list[int]) -> int | None:
    """The talent tree most of these entries belong to (entries come from Warcraft Logs rankings)."""
    node_tree, node_entries, _, _ = _tree_data()
    entry_node = {e: n for n, es in node_entries.items() for e in es}
    trees = Counter(node_tree.get(entry_node.get(e, -1)) for e in entry_ids)
    trees.pop(None, None)
    return trees.most_common(1)[0][0] if trees else None


def decode(loadout: str, tree_id: int) -> tuple[int, list[Choice]]:
    """Return (spec id, choices) of a loadout string for the given class tree."""
    _, node_entries, max_ranks, tree_nodes = _tree_data()
    nodes = tree_nodes.get(tree_id)
    if not nodes:
        raise TalentError(f"unknown talent tree {tree_id}")
    b = _Bits(loadout)
    version = b.read(8)
    spec_id = b.read(16)
    for _ in range(16):
        b.read(8)  # tree hash
    if version < 2:
        raise TalentError(f"unsupported talent string version {version}")
    out: list[Choice] = []
    for node in nodes:
        if not b.read(1):
            continue
        purchased = b.read(1)
        rank = None
        choice = 0
        if purchased:
            if b.read(1):
                rank = b.read(6)
            if b.read(1):
                choice = b.read(2)
        entries = node_entries.get(node) or []
        if not entries:
            continue
        entry = entries[min(choice, len(entries) - 1)]
        out.append(Choice(node, entry, rank if rank is not None else max_ranks.get(entry, 1), not purchased))
    return spec_id, out


def names_of(choices: list[Choice]) -> dict[int, str]:
    names = talent_entry_names()
    return {c.entry_id: names.get(c.entry_id, f"talent {c.entry_id}") for c in choices}
