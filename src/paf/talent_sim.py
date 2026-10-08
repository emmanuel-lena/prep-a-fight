"""Compare the talent builds of the top players (from the corpus) on your character, with SimC."""

from __future__ import annotations

import json
import sqlite3
import statistics as st
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from paf import simc
from paf.corpus.analyze import kills_filter
from paf.talents import decode, tree_for_entries
from paf.wcl import WCLClient

IMPORT_CODE_QUERY = """
query($code:String!, $f:[Int]!, $a:Int!) { reportData { report(code:$code) {
  fights(fightIDs:$f) { talentImportCode(actorID:$a) } } } }
"""


@dataclass
class Build:
    key: frozenset[int]  # talent entry ids
    players: list[sqlite3.Row] = field(default_factory=list)
    code: str | None = None
    label: str = ""
    n: int = 0  # number of top players, for a build read from a prep pack (no player rows)
    rank: float = 0.0  # their median rank, same

    @property
    def count(self) -> int:
        return len(self.players) or self.n

    @property
    def median_rank(self) -> float:
        return st.median(p["rank_pos"] for p in self.players) if self.players else self.rank


def top_builds(con: sqlite3.Connection, encounter_id: int, difficulty: int, spec: str, n: int = 6) -> list[Build]:
    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(
        f"SELECT r.* FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} AND r.spec=? "
        f"AND r.actor_id IS NOT NULL", (*params, spec)).fetchall()
    builds: dict[frozenset[int], Build] = {}
    for r in rows:
        talents = json.loads(r["talents_json"] or "[]")
        key = frozenset(t["talentID"] for t in talents)
        if not key:
            continue
        builds.setdefault(key, Build(key)).players.append(r)
    ranked = sorted(builds.values(), key=lambda b: (-b.count, b.median_rank))
    for i, b in enumerate(ranked[:n]):
        b.label = f"top build {chr(65 + i)}"
    return ranked[:n]


def fetch_codes(client: WCLClient, con: sqlite3.Connection, builds: list[Build]) -> None:
    """Loadout string of one player per build (cached in the corpus), ~2 points each."""
    for b in builds:
        for p in sorted(b.players, key=lambda p: p["rank_pos"]):
            if p["talent_code"]:
                b.code = p["talent_code"]
                break
        if b.code:
            continue
        for p in sorted(b.players, key=lambda p: p["rank_pos"])[:3]:
            data = client.query(IMPORT_CODE_QUERY, {"code": p["report"], "f": [p["fight_id"]], "a": p["actor_id"]},
                                cache_ttl=0)
            fights = (data["reportData"]["report"] or {}).get("fights") or []
            code = fights[0].get("talentImportCode") if fights else None
            if code:
                b.code = code
                con.execute("UPDATE ranked SET talent_code=? WHERE report=? AND fight_id=?",
                            (code, p["report"], p["fight_id"]))
                con.commit()
                break


def build_diff(mine: set[int], other: set[int], names: dict[int, str]) -> tuple[list[str], list[str]]:
    """Talent names taken in `other` and not in `mine`, and the reverse."""
    add = sorted({names.get(e, f"talent {e}") for e in other - mine} - {""})
    drop = sorted({names.get(e, f"talent {e}") for e in mine - other} - {""})
    return add, drop


@dataclass
class TalentResult:
    fights: list[str]
    rows: list[tuple[Build, dict[str, float], dict[str, float]]]  # build, total delta, boss delta per fight
    my_entries: set[int]


def sim_builds(profile_text: str, builds: list[Build], fights: dict[str, list[str]], run_dir: Path,
               target_error: float = 0.2) -> dict[str, simc.SimResult]:
    out = {}
    sets = {f"b{i}": [f"talents={b.code}"] for i, b in enumerate(builds) if b.code}
    for name, lines in fights.items():
        out[name] = simc.run(simc.build_input(profile_text, lines, sets), run_dir / name, target_error=target_error)
    return out


def my_talent_entries(profile_text: str, sample_entries: list[int]) -> set[int]:
    code = ""
    for line in profile_text.splitlines():
        if line.startswith("talents="):
            code = line.split("=", 1)[1].strip()
    if not code:
        return set()
    tree = tree_for_entries(sample_entries)
    if tree is None:
        return set()
    _, choices = decode(code, tree)
    return {c.entry_id for c in choices}


def choice_rates(builds_all: dict[frozenset[int], int]) -> dict[int, float]:
    total = sum(builds_all.values()) or 1
    rate: dict[int, float] = defaultdict(float)
    for key, n in builds_all.items():
        for e in key:
            rate[e] += n / total
    return rate


@dataclass
class TalentRow:
    build: Build
    per_fight: dict[str, tuple[float, float | None]]  # fight -> (total delta %, boss delta % or None)
    add: list[str]
    drop: list[str]
    # [(your talent, its spell id), (the build's talent, its spell id)]; one side None when nothing pairs with it
    swaps: list = field(default_factory=list)


NEAR = 1500.0  # tree units: a talent dropped and one taken this close are shown as one swap


def swaps(mine: set[int], other: set[int], entries: dict[int, tuple[str, int, int, float, float]]) -> list:
    """The talents a build swaps, paired: your talent -> its talent. A choice node first (two talents of one
    node), then the nearest taken talent in the tree; the rest alone. A name on both sides (a talent on two nodes)
    is not a change."""
    def info(e: int):
        return entries.get(e, (f"talent {e}", 0, 0, 0.0, 0.0))

    taken, dropped = sorted(other - mine), sorted(mine - other)
    both = {info(e)[0] for e in taken} & {info(e)[0] for e in dropped}
    def once(es: list[int]) -> list[int]:  # a talent with two ranks is two entries: one line
        out_, seen = [], set()
        for e in es:
            name = info(e)[0]
            if name and name not in both and name not in seen:
                seen.add(name)
                out_.append(e)
        return out_

    taken, dropped = once(taken), once(dropped)
    out = []
    for d in list(dropped):  # the same choice node
        t = next((t for t in taken if info(t)[2] and info(t)[2] == info(d)[2]), None)
        if t is not None:
            out.append(((info(d)[0], info(d)[1]), (info(t)[0], info(t)[1])))
            dropped.remove(d)
            taken.remove(t)
    while dropped and taken:  # the nearest in the tree
        d, t = min(((d, t) for d in dropped for t in taken),
                   key=lambda p: (info(p[0])[3] - info(p[1])[3]) ** 2 + (info(p[0])[4] - info(p[1])[4]) ** 2)
        if ((info(d)[3] - info(t)[3]) ** 2 + (info(d)[4] - info(t)[4]) ** 2) ** 0.5 > NEAR:
            break
        out.append(((info(d)[0], info(d)[1]), (info(t)[0], info(t)[1])))
        dropped.remove(d)
        taken.remove(t)
    for d, t in zip(list(dropped), list(taken), strict=False):  # the points left: moved from one to the other
        out.append(((info(d)[0], info(d)[1]), (info(t)[0], info(t)[1])))
        dropped.remove(d)
        taken.remove(t)
    out += [((info(d)[0], info(d)[1]), None) for d in dropped]
    out += [(None, (info(t)[0], info(t)[1])) for t in taken]
    return out


@dataclass
class TalentComparison:
    fights: list[str]
    rows: list[TalentRow]
    error: float
    run_dir: Path


def compare_builds(profile_text: str, con: sqlite3.Connection, client: WCLClient, encounter_id: int,
                   difficulty: int, spec: str, fights: dict[str, list[str]], run_dir: Path, *, n: int = 6,
                   target_error: float = 0.2) -> TalentComparison | None:
    builds = top_builds(con, encounter_id, difficulty, spec, n=n)
    if not builds:
        return None
    fetch_codes(client, con, builds)
    return compare(profile_text, builds, fights, run_dir, target_error=target_error)


def compare(profile_text: str, builds: list[Build], fights: dict[str, list[str]], run_dir: Path, *,
            target_error: float = 0.2) -> TalentComparison | None:
    """Sim the player's character with each build (from the corpus or a prep pack)."""
    from paf.gamedata import talent_entries, talent_entry_names

    if not builds:
        return None
    names = talent_entry_names()
    try:
        entries = talent_entries()
    except Exception:  # noqa: BLE001 - without the tree data, the talents are only named
        entries = {}
    mine = my_talent_entries(profile_text, sorted(builds[0].key))
    results = sim_builds(profile_text, builds, fights, run_dir, target_error=target_error)
    rows = []
    for i, b in enumerate(builds):
        per: dict[str, tuple[float, float | None]] = {}
        for fname, res in results.items():
            ps = next((p for p in res.profilesets if p.name == f"b{i}"), None)
            if ps:
                has_boss = "prioritydps" in ps.metrics and "prioritydps" in res.baseline
                per[fname] = (res.delta_pct(ps, "dps"), res.delta_pct(ps, "prioritydps") if has_boss else None)
        add, drop = build_diff(mine, set(b.key), names) if mine else ([], [])
        rows.append(TalentRow(b, per, add, drop, swaps(mine, set(b.key), entries) if mine and entries else []))
    err = max(r.baseline["dps"].error / r.baseline["dps"].mean * 100 for r in results.values())
    return TalentComparison(list(fights), rows, err, run_dir)
