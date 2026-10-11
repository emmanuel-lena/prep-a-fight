"""A class's talent tree, to search builds over every talent (ROADMAP R7): the talents and their trees from the
simc that sims them (``spell_query=talent.class=``), the links between nodes from the game data (wago TraitEdge),
and the rules a build must follow, checked against the top players' builds:

- a node is open when it has no parent in the tree, or one of its parents is at its max rank;
- a node behind a gate needs that many points spent in its tree on the nodes before the gate;
- each tree has a fixed budget (class, spec, hero), and the hero nodes all belong to one hero tree of the spec.

A build is ``{node: (entry, rank)}``: the entry tells a choice node's pick. simc does not check any of this
(docs/research/simc-experiments.md), so a search must."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import cache

Build = dict[int, tuple[int, int]]
TREES = ("class", "spec", "hero")


@dataclass(frozen=True)
class Talent:
    entry: int
    node: int
    name: str
    tree: str  # class | spec | hero | selection (the hero tree's choice)
    specs: frozenset[str]  # simc spec tokens; empty for the class tree (every spec)
    req: int  # points to spend in the tree before it (its gate)
    max_rank: int
    subtree: int  # hero tree id (0 elsewhere)


def parse_query(text: str) -> dict[int, Talent]:
    """simc's `spell_query=talent.class=<class>` output -> {entry: Talent}."""
    out = {}
    for block in re.split(r"^(?=Name\s*:)", text, flags=re.M):
        f = dict((k.strip(), v.strip()) for k, v in re.findall(r"^([A-Za-z. ]+?)\s*:\s*(.*)$", block, re.M))
        if not f.get("Entry", "").isdigit() or not f.get("Node", "").isdigit():
            continue
        out[int(f["Entry"])] = Talent(
            int(f["Entry"]), int(f["Node"]), f.get("Name", ""), (f.get("Tree") or "").split(" ")[0],
            frozenset(re.findall(r"([a-z_]+) \(\d+\)", f.get("Spec", ""))), int(f.get("Req. Points") or 0),
            int(f.get("Max Rank") or 1), int(f.get("Subtree") or 0))
    return out


@dataclass
class Tree:
    talents: dict[int, Talent]
    parents: dict[int, set[int]]  # node -> the nodes linked above it

    def __post_init__(self) -> None:
        self.by_node: dict[int, list[Talent]] = defaultdict(list)
        for t in self.talents.values():
            self.by_node[t.node].append(t)

    def first(self, node: int) -> Talent:
        return self.by_node[node][0]

    def visible(self, spec: str) -> set[int]:
        """The nodes a spec can take (simc spec token: subtlety, beast_mastery)."""
        return {n for n, ts in self.by_node.items()
                if ts[0].tree != "selection" and (ts[0].tree == "class" or spec in ts[0].specs)}

    def hero_trees(self, spec: str) -> set[int]:
        return {t.subtree for t in self.talents.values() if t.tree == "hero" and spec in t.specs}

    # --- builds ---------------------------------------------------------------------------------------------------

    def from_ranks(self, ranks: list[tuple[int, int]]) -> Build:
        """A build from (entry, rank) pairs (the rankings' talents); the hero tree's choice node is dropped."""
        out: Build = {}
        for entry, rank in ranks:
            t = self.talents.get(entry)
            if t is not None and t.tree in TREES:
                out[t.node] = (entry, rank)
        return out

    def from_loadout(self, loadout: str) -> Build:
        """A build from an import string (yours, simc's): its free nodes kept like the rankings keep them, except
        the root of the hero tree not taken (the string carries both)."""
        from paf.talents import decode, tree_for_entries

        tree_id = tree_for_entries(list(self.talents))
        if tree_id is None:
            return {}
        _spec, choices = decode(loadout, tree_id)
        chosen = {self.talents[c.entry_id].subtree for c in choices
                  if not c.granted and c.entry_id in self.talents and self.talents[c.entry_id].tree == "hero"}
        return self.from_ranks([(c.entry_id, c.rank) for c in choices if c.entry_id in self.talents and not (
            c.granted and self.talents[c.entry_id].tree == "hero" and self.talents[c.entry_id].subtree not in chosen)])

    def spent(self, build: Build) -> dict[str, int]:
        out = dict.fromkeys(TREES, 0)
        for entry, rank in build.values():
            out[self.talents[entry].tree] += rank
        return out

    def problems(self, build: Build, spec: str, budget: dict[str, int] | None = None) -> list[str]:
        """Why a build is not one the game allows ([] when it is)."""
        out = []
        visible = self.visible(spec)
        heroes = {self.talents[e].subtree for e, _ in build.values() if self.talents[e].tree == "hero"}
        if len(heroes) > 1:
            out.append("nodes of two hero trees")
        for node, (entry, rank) in build.items():
            t = self.talents[entry]
            if node not in visible:
                out.append(f"{t.name}: not a talent of this spec")
            if not 1 <= rank <= t.max_rank:
                out.append(f"{t.name}: rank {rank} of {t.max_rank}")
            ups = self.parents.get(node, set()) & visible
            if t.tree == "hero":  # the hero tree's first node opens with the tree's choice; the rest by links
                ups = {u for u in ups if self.first(u).tree == "hero"}
            if ups and not any(u in build and build[u][1] >= self.talents[build[u][0]].max_rank for u in ups):
                out.append(f"{t.name}: no parent at max rank")
            if t.tree in ("class", "spec") and t.req:
                before = sum(r for e, r in build.values()
                             if self.talents[e].tree == t.tree and self.talents[e].req < t.req)
                if before < t.req:
                    out.append(f"{t.name}: {before} of the {t.req} points its gate needs")
        if budget:
            spent = self.spent(build)
            out += [f"{tree}: {spent[tree]} points of {n}" for tree, n in budget.items() if spent[tree] != n]
        return out

    def removals(self, build: Build, spec: str) -> list[Build]:
        """Every build with one point less that is still allowed (its budget one short)."""
        out = []
        for node, (entry, rank) in build.items():
            b = dict(build)
            if rank > 1:
                b[node] = (entry, rank - 1)
            else:
                del b[node]
            if not self.problems(b, spec):
                out.append(b)
        return out

    def additions(self, build: Build, spec: str) -> list[Build]:
        """Every build with one point more that is allowed (each pick of a choice node apart)."""
        out = []
        hero = {self.talents[e].subtree for e, _ in build.values() if self.talents[e].tree == "hero"}
        for node in self.visible(spec):
            if node in build:
                entry, rank = build[node]
                if rank < self.talents[entry].max_rank:
                    b = dict(build)
                    b[node] = (entry, rank + 1)
                    if not self.problems(b, spec):
                        out.append(b)
                continue
            for t in self.by_node[node]:
                if t.tree == "hero" and hero and t.subtree not in hero:
                    continue
                if t.tree in ("spec", "hero") and spec not in t.specs:
                    continue
                b = dict(build)
                b[node] = (t.entry, 1)
                if not self.problems(b, spec):
                    out.append(b)
        return out

    def flips(self, build: Build, spec: str) -> list[Build]:
        """Every other pick of the choice nodes taken."""
        out = []
        for node, (entry, rank) in build.items():
            for t in self.by_node[node]:
                if t.entry != entry and (t.tree == "class" or spec in t.specs):
                    b = dict(build)
                    b[node] = (t.entry, min(rank, t.max_rank))
                    if not self.problems(b, spec):
                        out.append(b)
        return out

    def loadout(self, build: Build, reference: str) -> str:
        """The build's import string. `reference`, a string of the same spec, gives the spec, the nodes granted for
        free and the hero tree's choice node. Names are no use: a class can have two talents of one name (Ancient
        Arts, Rogue), and simc takes the wrong one (-25% for Subtlety)."""
        from paf.talents import Choice, decode, encode, tree_for_entries

        tree_id = tree_for_entries(list(self.talents))
        spec_id, ref = decode(reference, tree_id)
        hero = next((self.talents[e].subtree for e, _ in build.values() if self.talents[e].tree == "hero"), 0)
        out = {c.node_id: c for c in ref if c.granted}
        for c in ref:
            picks = self.by_node.get(c.node_id) or []
            if picks and picks[0].tree == "selection" and not c.granted:
                pick = next((t for t in picks if t.subtree == hero), None)
                if pick:
                    out[c.node_id] = Choice(c.node_id, pick.entry, 1, False)
        for node, (entry, rank) in build.items():
            if node not in out or not out[node].granted:
                out[node] = Choice(node, entry, rank, False)
        return encode(spec_id, list(out.values()), tree_id)

    def simc_lines(self, build: Build, reference: str) -> list[str]:
        """The build as a simc option."""
        return [f"talents={self.loadout(build, reference)}"]


def key(build: Build) -> tuple:
    return tuple(sorted(build.items()))


@cache
def edges() -> dict[int, set[int]]:
    """node -> its parents, every tree of the game (wago TraitEdge)."""
    from paf.gamedata import table_rows

    out: dict[int, set[int]] = defaultdict(set)
    for r in table_rows("TraitEdge"):
        a, b = r.get("LeftTraitNodeID", ""), r.get("RightTraitNodeID", "")
        if a.isdigit() and b.isdigit():
            out[int(b)].add(int(a))
    return dict(out)


def load(cls: str, simc_path: str | None = None) -> Tree | None:
    """The talent tree of a class (Warcraft Logs class name: DeathKnight), or None without simc."""
    import subprocess

    from paf.simc_install import find_simc

    exe = find_simc(simc_path)
    if exe is None:
        return None
    try:
        proc = subprocess.run([str(exe), f"spell_query=talent.class={cls.lower()}"], capture_output=True,
                              text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    talents = parse_query(proc.stdout)
    if not talents:
        return None
    nodes = {t.node for t in talents.values()}
    return Tree(talents, {n: p & nodes for n, p in edges().items() if n in nodes})
