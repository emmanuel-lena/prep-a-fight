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


CHOICE_TYPES = {"2", "3"}  # TraitNode.Type: 2 a choice node, 3 the hero tree's choice


@cache
def _node_types() -> dict[int, str]:
    return {int(r["ID"]): r.get("Type", "0") for r in table_rows("TraitNode") if r.get("ID", "").isdigit()}


@cache
def _node_subtrees() -> dict[int, int]:
    """node -> its hero tree (0 outside the hero trees)."""
    return {int(r["ID"]): int(r.get("TraitSubTreeID") or 0) for r in table_rows("TraitNode")
            if r.get("ID", "").isdigit()}


def comparable(entries: set[int]) -> set[int]:
    """Entries brought to one per node, so two builds compare node by node: a talent with one entry per rank
    (Ancient Arts: 3 entries) is one talent; only a choice node keeps which of its talents is taken."""
    _, node_entries, _, _ = _tree_data()
    entry_node = {e: n for n, es in node_entries.items() for e in es}
    types = _node_types()
    out = set()
    for e in entries:
        node = entry_node.get(e)
        if node is None or types.get(node) in CHOICE_TYPES:
            out.add(e)
        else:
            out.add(node_entries[node][0])
    return out


def taken(choices: list[Choice]) -> set[int]:
    """The entries of a decoded build as the rankings list them: an import string also carries the free root of
    the hero tree not taken (Unseen Blade for a Deathstalker), which is no talent of the build."""
    subtrees = _node_subtrees()
    chosen = {subtrees.get(c.node_id, 0) for c in choices if not c.granted} - {0}
    return {c.entry_id for c in choices
            if not (c.granted and subtrees.get(c.node_id, 0) and subtrees.get(c.node_id, 0) not in chosen)}


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


def encode(spec_id: int, choices: list[Choice], tree_id: int, version: int = 2) -> str:
    """The import string of these choices (the inverse of decode; the tree hash left at zero, as third parties do)."""
    _, node_entries, max_ranks, tree_nodes = _tree_data()
    nodes = tree_nodes.get(tree_id)
    if not nodes:
        raise TalentError(f"unknown talent tree {tree_id}")
    by_node = {c.node_id: c for c in choices}
    bits: list[int] = []

    def put(v: int, n: int) -> None:
        bits.extend((v >> i) & 1 for i in range(n))

    put(version, 8)
    put(spec_id, 16)
    put(0, 128)
    for node in nodes:
        c = by_node.get(node)
        put(1 if c else 0, 1)
        if not c:
            continue
        put(0 if c.granted else 1, 1)
        if c.granted:
            continue
        partial = c.rank < max_ranks.get(c.entry_id, 1)
        put(1 if partial else 0, 1)
        if partial:
            put(c.rank, 6)
        entries = node_entries.get(node) or []
        choice = _node_types().get(node) in CHOICE_TYPES  # a node can list several entries without being a choice
        put(1 if choice else 0, 1)
        if choice:
            put(entries.index(c.entry_id) if c.entry_id in entries else 0, 2)
    bits += [0] * (-len(bits) % 6)
    return "".join(ALPHABET[sum(bits[i + j] << j for j in range(6))] for i in range(0, len(bits), 6))


def names_of(choices: list[Choice]) -> dict[int, str]:
    names = talent_entry_names()
    return {c.entry_id: names.get(c.entry_id, f"talent {c.entry_id}") for c in choices}


def utility(names, class_name: str, spec: str) -> set[str]:
    """The talents among names that are a button SimC's default rotation never presses and that deals, heals or
    raises nothing (Purge, Tremor Totem, Blind, Tranquilizing Shot): a player's choice, not a sim's (the owner,
    2026-10-24). Passive talents are never said so (their effects change other spells: the game data cannot tell
    a utility one apart). No APL (no simc): none."""
    from paf import apl
    from paf.gamedata import is_throughput, passive_spells, talent_entries

    try:
        cast = apl.spells(apl.default_apl(class_name, spec))
    except Exception:  # noqa: BLE001 - no APL, no claim
        return set()
    if not cast:
        return set()
    by_name: dict[str, list[int]] = defaultdict(list)
    wanted = set(names)
    for name, sid, *_ in talent_entries().values():
        if name in wanted and sid:
            by_name[name].append(sid)
    passive = passive_spells()
    out = set()
    for name in wanted:
        sids = by_name.get(name)
        try:  # every talent of that name a button that does nothing a sim counts (two classes can share a name)
            if sids and apl.norm(name) not in cast and all(s not in passive and not is_throughput(s) for s in sids):
                out.add(name)
        except Exception:  # noqa: BLE001 - game data unreachable: not said
            continue
    return out
