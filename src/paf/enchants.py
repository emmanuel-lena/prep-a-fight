"""Enchants and gems simmed on your set (the Gear tool, the owner 2026-10-24: "the full package"). The candidates are
what the top players of your spec wear, from the rankings (paf.specgear's query): never a fixed list, always this
season's, and only the ones the best players chose. Each enchant is simmed in its slot, each gem in every socket you
have filled (a unique gem, worn once by most top players, is left where it is)."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from paf.specgear import GEAR_TOPS, SLOTS

SHARE = 0.10  # a candidate: worn by this share of the top players at least
PER_SLOT = 3  # enchants tried per slot
GEMS = 4  # gems tried


@dataclass
class Choice:
    kind: str  # "enchant" | "gem"
    slot: str  # simc slot ("" for a gem: every socket)
    item: int  # the enchant id or the gem's item id
    share: float  # of the top players who wear it there
    name: str = ""
    gain: float | None = None  # % over what you wear, once simmed


def tops_rows(client, encounter_id: int, difficulty: int, cls: str, spec: str) -> list[dict]:
    """The ranking rows of the top players of a spec on a boss, best first (their gear included; cached 6 h)."""
    from paf.raidneed import RANKING_QUERY

    data = client.query(RANKING_QUERY, {"id": encounter_id, "diff": difficulty, "cls": cls, "spec": spec,
                                        "metric": "bossdps"}, cache_ttl=6 * 3600)
    cr = ((data.get("worldData") or {}).get("encounter") or {}).get("characterRankings") or {}
    rows = sorted((r for r in cr.get("rankings") or [] if r.get("amount")), key=lambda r: -r["amount"])
    return rows[:GEAR_TOPS]


def unique_gems(rows: list[dict]) -> set[int]:
    """Gems most top players wear exactly once: a unique gem (one per character), never put in every socket."""
    once: Counter = Counter()
    seen: Counter = Counter()
    for r in rows:
        worn = Counter(g["id"] for it in r.get("gear") or [] for g in it.get("gems") or [] if g.get("id"))
        for gid, n in worn.items():
            seen[gid] += 1
            once[gid] += n == 1
    return {g for g, n in seen.items() if once[g] >= 0.8 * n}


def candidates(rows: list[dict]) -> list[Choice]:
    """Each slot's enchants and the gems the top players wear, with their share."""
    if not rows:
        return []
    n = len(rows)
    out: list[Choice] = []
    for i, slot in SLOTS.items():
        worn = Counter(it.get("permanentEnchant") for r in rows for k, it in enumerate(r.get("gear") or [])
                       if k == i and it.get("permanentEnchant"))
        out += [Choice("enchant", slot, int(e), c / n) for e, c in worn.most_common(PER_SLOT) if c / n >= SHARE]
    unique = unique_gems(rows)
    gems = Counter(g for r in rows for g in {g["id"] for it in r.get("gear") or [] for g in it.get("gems") or []
                                             if g.get("id") and g["id"] not in unique})  # players wearing it
    out += [Choice("gem", "", int(g), c / n) for g, c in gems.most_common(GEMS) if c / n >= SHARE]
    return out


def run(profile: str, fights: list, run_dir, choices: list[Choice], unique: set[int], objective: float = 0.0,
        log=print) -> float:
    """Sim every choice on your profile, on each fight (weighted); each choice gets its gain. The sims' error, %."""
    from paf import simc
    from paf.topgear import score_of

    sets = variants(profile, choices, unique)
    if not sets:
        return 0.0
    gains: dict[str, float] = {}
    err = 0.0
    total = sum(f.weight for f in fights) or 1
    for fp in fights:
        res = simc.run_sets(profile, fp.lines, sets, run_dir / f"enchants-{fp.name}", log=log, target_error=0.2)
        base = res.baseline["dps"].mean or 1
        for ps in res.profilesets:
            gains[ps.name] = gains.get(ps.name, 0.0) + score_of(res, ps, objective) * fp.weight / total
            err = max(err, 100 * ps.dps.error / base)
    for k, c in enumerate(choices):
        key = f"{'e' if c.kind == 'enchant' else 'g'}{k}"
        c.gain = gains.get(key, 0.0 if key not in sets else None)  # 0: already worn
    return err


def best(choices: list[Choice], err: float) -> list[Choice]:
    """The enchant of each slot and the gem worth changing: the best of each beyond the sims' noise."""
    out = []
    for slot in dict.fromkeys(c.slot for c in choices):
        top = max((c for c in choices if c.slot == slot and c.gain is not None), key=lambda c: c.gain, default=None)
        if top is not None and top.gain > 2 * err:
            out.append(top)
    return out


def _slot_line(profile: str, slot: str) -> str | None:
    names = {slot, slot + "s"} if slot in ("shoulder", "wrist") else {slot}
    found = [x.strip() for x in profile.splitlines() if x.strip().partition("=")[0] in names]
    return found[-1] if found else None  # the last: the set Top Gear put on (simc keeps a slot's last line)


def with_enchant(line: str, enchant: int) -> str:
    line = re.sub(r",enchant_id=\d+", "", line)
    return f"{line},enchant_id={enchant}"


def with_gem(line: str, gem: int, keep: set[int]) -> str:
    """Every gem of the line that is not a kept one (a unique gem) becomes this one."""
    m = re.search(r",gem_id=([\d/]+)", line)
    if not m:
        return line
    gems = [g if int(g) in keep else str(gem) for g in m[1].split("/")]
    return line.replace(m[0], ",gem_id=" + "/".join(gems))


def variants(profile: str, choices: list[Choice], unique: set[int]) -> dict[str, list[str]]:
    """A profileset per choice: the slot's line with that enchant, or every line with that gem; none when it is
    already what you wear."""
    out: dict[str, list[str]] = {}
    for k, c in enumerate(choices):
        if c.kind == "enchant":
            line = _slot_line(profile, c.slot)
            if line and f"enchant_id={c.item}" not in line and "id=" in line:
                out[f"e{k}"] = [with_enchant(line, c.item)]
        else:
            lines = [x.strip() for x in profile.splitlines() if ",gem_id=" in x and not x.lstrip().startswith("#")]
            new = [with_gem(x, c.item, unique) for x in lines]
            if new != lines:
                out[f"g{k}"] = new
    return out


def apply(profile: str, picks: list[Choice], unique: set[int]) -> str:
    """Your profile with these enchants and gem, each item line changed in place (never a second line for a slot:
    the last one would undo the other's change)."""
    out = []
    for raw in profile.splitlines():
        line, key = raw.strip(), raw.strip().partition("=")[0]
        if not line.startswith("#") and "id=" in line:
            for c in picks:
                if c.kind == "enchant" and key in ({c.slot, c.slot + "s"} if c.slot in ("shoulder", "wrist")
                                                   else {c.slot}):
                    line = with_enchant(line, c.item)
                elif c.kind == "gem":
                    line = with_gem(line, c.item, unique)
            raw = line
        out.append(raw)
    return "\n".join(out) + "\n"


def names(choices: list[Choice]) -> None:
    """The enchants' and the gems' names from the game data (an id when offline)."""
    try:
        from paf.gamedata import table_rows

        ench = {int(r["ID"]): r.get("Name_lang") or "" for r in table_rows("SpellItemEnchantment")
                if r.get("ID", "").isdigit()}
        want = {c.item for c in choices if c.kind == "gem"}
        items = {int(r["ID"]): r.get("Display_lang") or "" for r in table_rows("ItemSparse")
                 if r.get("ID", "").isdigit() and int(r["ID"]) in want}  # a gem's name (not in ItemSearchName)
    except Exception:  # noqa: BLE001 - offline: the ids
        ench, items = {}, {}
    for c in choices:
        c.name = readable((ench if c.kind == "enchant" else items).get(c.item) or "") or f"#{c.item}"


def readable(name: str) -> str:
    """A game string as a player reads it: no color code, its quality icon a rank ("|A:…Quality-12-Tier2…|a" ->
    "rank 2"), an armor kit's "+$k2 Agility" a plain "+Agility"."""
    rank = re.search(r"\|A:Professions-ChatIcon-Quality-\d+-Tier(\d)[^|]*\|a", name)
    name = re.sub(r"\|A:[^|]*\|a", "", name)
    name = re.sub(r"\|cn[^:|]*:|\|c[0-9a-fA-F]{8}|\|r", "", name)
    name = re.sub(r"\+\$k\d ", "+", name).strip()
    return f"{name} (rank {rank[1]})" if rank else name
