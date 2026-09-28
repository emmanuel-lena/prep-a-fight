"""Find raid encounters (bosses) and their zone's ilvl brackets on Warcraft Logs."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from paf.wcl import WCLClient

ZONES_QUERY = """
{ worldData { expansions { id name zones { id name frozen
    encounters { id name }
    brackets { min max bucket type } } } } }
"""


@dataclass(frozen=True)
class Encounter:
    id: int
    name: str
    zone_id: int
    zone_name: str
    bracket_min: float | None = None
    bracket_bucket: float | None = None

    def bracket_for_ilvl(self, ilvl: float) -> int | None:
        """WCL bracket index containing this item level (1-based)."""
        if self.bracket_min is None or not self.bracket_bucket:
            return None
        return max(1, int((ilvl - self.bracket_min) // self.bracket_bucket) + 1)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def raid_encounters(client: WCLClient) -> list[Encounter]:
    """Encounters of the non-frozen raid zones of the latest expansion (M+ and dummies excluded)."""
    data = client.query(ZONES_QUERY, cache_ttl=86400)
    exp = max(data["worldData"]["expansions"], key=lambda e: e["id"])
    out: list[Encounter] = []
    for z in exp["zones"]:
        name = z["name"]
        if z["frozen"] or "mythic+" in name.lower() or "dummy" in name.lower() or "complete" in name.lower():
            continue
        if "(ptr)" in name.lower() or "beta" in name.lower() or len(z["encounters"]) < 2:
            continue
        br = z.get("brackets") or {}
        for e in z["encounters"]:
            out.append(Encounter(e["id"], e["name"], z["id"], name, br.get("min"), br.get("bucket")))
    return out


def find_encounter(client: WCLClient, query: str) -> Encounter:
    """Match a boss by name (accent/case/punctuation-insensitive substring) or by numeric id."""
    encounters = raid_encounters(client)
    if query.strip().isdigit():
        for e in encounters:
            if e.id == int(query):
                return e
    q = _norm(query)
    exact = [e for e in encounters if _norm(e.name) == q]
    hits = exact or [e for e in encounters if q in _norm(e.name)]
    if len(hits) == 1:
        return hits[0]
    names = ", ".join(e.name for e in (hits or encounters))
    raise LookupError(f"{'ambiguous' if hits else 'unknown'} boss {query!r}. Choices: {names}")
