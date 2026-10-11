"""Search the talent build that does the most on a fight, over every talent of the tree (ROADMAP R7).

A local search, round after round: from a build, simc sims every point taken away and every point added that the
tree allows (each as a profileset, at a loose error), and every other pick of the choice nodes. The best swaps
(a point moved from one talent to another, predicted from those margins) are then simmed at the normal error, and
the best of them is kept when it beats the noise. It stops when nothing does. Starts: the builds given (yours, the
ones simc ships, the top players'), each simmed once; the best start of each hero tree is climbed.

A local search can miss a build two moves away (a filler talent on the way to a better one), and simc's default
rotation is written for some builds more than others: a build it plays badly sims low whatever it is worth."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paf.talent_tree import Build, Tree, key


@dataclass
class Step:
    change: str  # "Talent A -> Talent B"
    gain: float  # % over the previous build


@dataclass
class Climb:
    start: str
    build: Build
    value: float
    error: float  # % (one standard error of the mean)
    steps: list[Step] = field(default_factory=list)


@dataclass
class SearchResult:
    starts: dict[str, float]  # each start's value
    climbs: list[Climb]

    @property
    def best(self) -> Climb:
        return max(self.climbs, key=lambda c: c.value)


def _value(metrics: dict, metric: str) -> tuple[float, float]:
    m = metrics.get(metric) or metrics["dps"]
    return m.mean, 100 * m.error / m.mean if m.mean else 0.0


def _sim(tree: Tree, character: str, fight: list[str], base: Build, others: dict[str, Build], run_dir: Path,
         error: float, metric: str, reference: str) -> tuple[tuple[float, float], dict[str, float]]:
    """(base value, its error %), {name: value} of the other builds, in one simc run."""
    from paf import simc

    res = simc.run(simc.build_input(character + "\n".join(tree.simc_lines(base, reference)) + "\n", fight,
                                    {n: tree.simc_lines(b, reference) for n, b in others.items()}),
                   run_dir, target_error=error)
    base_v = _value(res.baseline, metric)
    return base_v, {ps.name: _value(ps.metrics, metric)[0] for ps in res.profilesets}


def _label(tree: Tree, before: Build, after: Build) -> str:
    gone = [tree.talents[e].name for n, (e, r) in before.items() if after.get(n, (0, 0))[0] != e or
            after[n][1] < r]
    new = [tree.talents[e].name for n, (e, r) in after.items() if before.get(n, (0, 0))[0] != e or
           before[n][1] < r]
    return f"{', '.join(gone) or '-'} -> {', '.join(new) or '-'}"


def _combine(base: Build, removed: Build, added: Build) -> Build | None:
    """base with the change of `removed` (one point less) and of `added` (one point more), None if they touch the
    same node."""
    rm = next(n for n in set(base) | set(removed) if base.get(n) != removed.get(n))
    ad = next(n for n in set(base) | set(added) if base.get(n) != added.get(n))
    if rm == ad:
        return None
    out = dict(base)
    if rm in removed:
        out[rm] = removed[rm]
    else:
        del out[rm]
    out[ad] = added[ad]
    return out


def climb(tree: Tree, spec: str, character: str, fight: list[str], start: Build, name: str, run_dir: Path, *,
          reference: str, budget: dict[str, int], loose: float = 0.5, error: float = 0.2, confirm: int = 6,
          rounds: int = 15, metric: str = "prioritydps", log=print) -> Climb:
    build, steps = start, []
    value, err = 0.0, 0.0
    for i in range(rounds):
        removals, additions, flips = tree.removals(build, spec), tree.additions(build, spec), tree.flips(build, spec)
        named = {f"r{j}": b for j, b in enumerate(removals)} | {f"a{j}": b for j, b in enumerate(additions)} | \
                {f"f{j}": b for j, b in enumerate(flips)}
        (value, err), got = _sim(tree, character, fight, build, named, run_dir / f"{name}-{i}-margins", loose, metric,
                                    reference)
        loss = {k: value - v for k, v in got.items() if k[0] == "r"}
        gain = {k: v - value for k, v in got.items() if k[0] == "a"}
        guesses: dict[tuple, tuple[float, Build]] = {}
        for a, g in gain.items():
            for r, lo in loss.items():
                b = _combine(build, named[r], named[a])
                if b is not None and g - lo > 0 and not tree.problems(b, spec, budget):
                    guesses.setdefault(key(b), (g - lo, b))
        for f, v in got.items():
            if f[0] == "f" and v > value:
                guesses.setdefault(key(named[f]), (v - value, named[f]))
        best = sorted(guesses.values(), key=lambda x: -x[0])[:confirm]
        if not best:
            break
        cands = {f"c{j}": b for j, (_, b) in enumerate(best)}
        (value, err), got = _sim(tree, character, fight, build, cands, run_dir / f"{name}-{i}-confirm", error, metric,
                                    reference)
        top = max(got, key=got.get)
        gain_pct = 100 * (got[top] / value - 1)
        if gain_pct <= 2 * 2 ** 0.5 * err:  # within the noise of two sims: stop
            break
        steps.append(Step(_label(tree, build, cands[top]), gain_pct))
        log(f"    {name}: {steps[-1].change} ({gain_pct:+.2f}%)")
        build, value = cands[top], got[top]
    return Climb(name, build, value, err, steps)


def _hero(tree: Tree, build: Build) -> int:
    return next((tree.talents[e].subtree for e, _ in build.values() if tree.talents[e].tree == "hero"), 0)


def hero_starts(tree: Tree, spec: str, starts: dict[str, Build], donors: list[Build]) -> dict[str, Build]:
    """A start in each hero tree of the spec the starts leave out: the best start's class and spec talents with the
    hero talents of a build (another spec's) that takes that hero tree."""
    if not starts:
        return {}
    covered = {_hero(tree, b) for b in starts.values()}
    base = next(iter(starts.values()))
    out = {}
    for hero in sorted(tree.hero_trees(spec) - covered):
        for donor in donors:
            if _hero(tree, donor) != hero:
                continue
            b = {n: v for n, v in base.items() if tree.talents[v[0]].tree != "hero"}
            b.update({n: v for n, v in donor.items() if tree.talents[v[0]].tree == "hero"})
            if not tree.problems(b, spec, tree.spent(base)):
                out[f"hero{hero}"] = b
                break
    return out


def search(tree: Tree, spec: str, character: str, fight: list[str], starts: dict[str, Build], run_dir: Path, *,
           reference: str, donors: list[Build] | None = None, error: float = 0.2, metric: str = "prioritydps",
           log=print, **kw) -> SearchResult:
    """`character`: the character's lines without talents (each build adds its own); `reference`: an import string
    of the spec (its free nodes, its hero tree choice). Starts with problems (another patch's build) are left
    out."""
    ok = {name: b for name, b in starts.items() if b and not tree.problems(b, spec)}
    for name, b in hero_starts(tree, spec, ok, donors or []).items():
        ok.setdefault(name, b)
    if not ok:
        return SearchResult({}, [])
    first, *rest = ok
    (v0, _e), got = _sim(tree, character, fight, ok[first], {n: ok[n] for n in rest}, run_dir / "starts", error,
                         metric, reference)
    values = {first: v0, **got}
    by_hero: dict[int, str] = {}
    for n in sorted(values, key=lambda n: -values[n]):
        hero = next((tree.talents[e].subtree for e, _ in ok[n].values() if tree.talents[e].tree == "hero"), 0)
        by_hero.setdefault(hero, n)
    climbs = []
    for n in by_hero.values():
        log(f"  climbing from {n} ({values[n]:,.0f})...")
        climbs.append(climb(tree, spec, character, fight, ok[n], n, run_dir, reference=reference,
                            budget=tree.spent(ok[n]), error=error,
                            metric=metric, log=log, **kw))
    return SearchResult(values, climbs)
