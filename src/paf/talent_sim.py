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

    @property
    def count(self) -> int:
        return len(self.players)

    @property
    def median_rank(self) -> float:
        return st.median(p["rank_pos"] for p in self.players)


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
