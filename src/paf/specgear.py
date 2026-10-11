"""Which spec and which gear on this boss: the gap between the specs of your class among the top players (their
boss damage in the rankings), your character simmed on the rebuilt fight in each spec wearing the top players' gear
at the season's top item level, your own kills on the boss, and one sentence that says what to do, with its noise.

Everything comes from the rankings (``characterRankings`` with ``includeCombatantInfo``: each top player's gear),
so another spec needs no corpus of its own. Talents: yours for your spec; for another spec, the build of the
profile SimulationCraft ships for it (the rankings give talent IDs, not an import code)."""

from __future__ import annotations

import random
import re
import statistics as st
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

TOP_ILVL = 334  # the season's top item level (Myth 6/6)
GEAR_TOPS = 20  # the top players whose gear makes the set of a spec
MIN_TOPS = 10  # fewer ranked players than this: the spec is not compared

# the damage specs of each class, as Warcraft Logs names them
DAMAGE_SPECS = {
    "DeathKnight": ("Frost", "Unholy"), "DemonHunter": ("Havoc", "Devourer"), "Druid": ("Balance", "Feral"),
    "Evoker": ("Devastation",), "Hunter": ("BeastMastery", "Marksmanship", "Survival"),
    "Mage": ("Arcane", "Fire", "Frost"), "Monk": ("Windwalker",), "Paladin": ("Retribution",),
    "Priest": ("Shadow",), "Rogue": ("Assassination", "Outlaw", "Subtlety"),
    "Shaman": ("Elemental", "Enhancement"), "Warlock": ("Affliction", "Demonology", "Destruction"),
    "Warrior": ("Arms", "Fury"),
}

SLOTS = {0: "head", 1: "neck", 2: "shoulder", 4: "chest", 5: "waist", 6: "legs", 7: "feet", 8: "wrist", 9: "hands",
         10: "finger1", 11: "finger2", 12: "trinket1", 13: "trinket2", 14: "back", 15: "main_hand", 16: "off_hand"}
PAIRS = ((10, 11), (12, 13))  # two rings, two trinkets: the two most worn, whatever their slot


def spec_label(spec: str) -> str:
    """BeastMastery -> Beast Mastery."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", spec)


def simc_spec(spec: str) -> str:
    """BeastMastery -> beast_mastery."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", spec).lower()


@dataclass
class Tops:
    """The top players of a spec on a boss, from the rankings."""
    spec: str  # Warcraft Logs name: "Enhancement"
    amounts: list[float]  # their DPS (the ranking's metric), best first
    gear: list[dict] = field(default_factory=list)  # the set they wear most, WCL items by slot index
    build: tuple[tuple[int, int], ...] = ()  # the talent build they play most: (talentID, rank)

    @property
    def median(self) -> float:
        return st.median(self.amounts)

    def interval(self, n: int = 1000, seed: int = 1) -> tuple[float, float]:
        """90% bootstrap interval of the median (the noise of "the top players of this spec do X")."""
        rnd = random.Random(seed)
        meds = sorted(st.median(rnd.choices(self.amounts, k=len(self.amounts))) for _ in range(n))
        return meds[int(0.05 * n)], meds[int(0.95 * n) - 1]


def _items(row: dict) -> dict[int, dict]:
    return {i: it for i, it in enumerate(row.get("gear") or []) if i in SLOTS and it.get("id")}


def common_set(rows: list[dict]) -> list[dict]:
    """The set the top players wear most, slot by slot: the most worn item of each slot (enchant and gems of the
    best ranked player who wears it), the two most worn rings and trinkets, and the weapons of the most common
    main hand (a two-hander and a one-hander with an off-hand are not mixed)."""
    gear: list[dict] = [{} for _ in range(17)]
    players = [_items(r) for r in rows]
    paired = {s for p in PAIRS for s in p}

    def first_with(item_id, slots) -> dict:
        return next(p[s] for p in players for s in slots if s in p and p[s]["id"] == item_id)

    for slot in SLOTS:
        if slot in paired or slot in (15, 16):
            continue
        worn = Counter(p[slot]["id"] for p in players if slot in p)
        if worn:
            gear[slot] = first_with(worn.most_common(1)[0][0], (slot,))
    for a, b in PAIRS:
        worn = Counter(p[s]["id"] for p in players for s in (a, b) if s in p)
        for slot, (item_id, _n) in zip((a, b), worn.most_common(2), strict=False):
            gear[slot] = first_with(item_id, (a, b))
    mains = Counter(p[15]["id"] for p in players if 15 in p)
    if mains:
        main = mains.most_common(1)[0][0]
        gear[15] = first_with(main, (15,))
        offs = Counter(p[16]["id"] for p in players if p.get(15, {}).get("id") == main and 16 in p)
        if offs:
            gear[16] = first_with(offs.most_common(1)[0][0], (16,))
    return gear


def gear_lines(gear: list[dict], ilvl: int = TOP_ILVL) -> list[str]:
    """simc item lines at the given item level (the bonus IDs kept: sockets, embellishments, tier)."""
    out = []
    for i, it in enumerate(gear):
        slot = SLOTS.get(i)
        if not slot or not it.get("id"):
            continue
        v = f"{slot}=,id={it['id']}"
        if it.get("bonusIDs"):
            v += ",bonus_id=" + "/".join(str(b) for b in it["bonusIDs"])
        if it.get("permanentEnchant"):
            v += f",enchant_id={it['permanentEnchant']}"
        gems = [str(g["id"]) for g in it.get("gems") or [] if g.get("id")]
        if gems:
            v += ",gem_id=" + "/".join(gems)
        out.append(f"{v},ilevel={ilvl}")
    return out


HEADER_KEYS = ("level", "race", "region", "server", "professions")
ITEM_LINE = re.compile(r"^(head|neck|shoulders?|back|chest|shirt|tabard|wrists?|hands|waist|legs|feet|finger[12]|"
                       r"trinket[12]|main_hand|off_hand)=")


def character_in(profile: str, spec: str, talents: list[str], gear: list[dict]) -> str:
    """Your character (name, race, level, server) as a spec, with these talent lines, in this gear."""
    lines, out = profile.splitlines(), []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        key = s.partition("=")[0]
        if not out and "=" in s and key in {"deathknight", "demonhunter", "druid", "evoker", "hunter", "mage", "monk",
                                            "paladin", "priest", "rogue", "shaman", "warlock", "warrior"}:
            out.append(s)
        elif key in HEADER_KEYS:
            out.append(s)
    if not out:
        raise ValueError("no character in this profile")
    out += [f"spec={simc_spec(spec)}", *talents, *gear_lines(gear)]
    return "\n".join(out) + "\n"


def bundled_talents(cls: str, spec: str, simc_path: str | None = None) -> str | None:
    """The talents of the profile SimulationCraft ships for a spec (MID2_Shaman_Enhancement.simc)."""
    from paf.simc_install import bundled_profile

    words = {"DeathKnight": "Death_Knight", "DemonHunter": "Demon_Hunter"}.get(cls, cls)
    path = bundled_profile(f"*_{words}_{spec_label(spec).replace(' ', '_')}.simc", simc_path)
    if path is None:
        return None
    m = re.search(r"^talents=(\S+)", path.read_text(encoding="utf-8", errors="replace"), re.M)
    return m.group(1) if m else None


def simc_token(name: str) -> str:
    """A talent's name as SimulationCraft spells it: "Dragon-Bone Dice" -> dragonbone_dice."""
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


def parse_talent_query(text: str) -> dict[int, tuple[str, str]]:
    """simc's `spell_query=talent.class=...` output -> {entry id: (name, tree)}; the entry id is what Warcraft Logs
    reports as talentID."""
    out = {}
    for block in re.split(r"^(?=Name\s*:)", text, flags=re.M):
        name = re.search(r"^Name\s*:\s*(.+?)\s*$", block, re.M)
        entry = re.search(r"^Entry\s*:\s*(\d+)", block, re.M)
        tree = re.search(r"^Tree\s*:\s*(\w+)", block, re.M)
        if name and entry and tree:
            out[int(entry.group(1))] = (name.group(1), tree.group(1))
    return out


def talent_trees(cls: str, simc_path: str | None = None) -> dict[int, tuple[str, str]]:
    """Every talent of a class, from SimulationCraft's own data (so it matches the simc that sims it)."""
    import subprocess

    from paf.simc_install import find_simc

    exe = find_simc(simc_path)
    if exe is None:
        return {}
    token = cls.lower()  # DeathKnight -> deathknight, as simc names the class
    try:
        proc = subprocess.run([str(exe), f"spell_query=talent.class={token}"], capture_output=True, text=True,
                              timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_talent_query(proc.stdout)


def build_lines(build: tuple[tuple[int, int], ...], trees: dict[int, tuple[str, str]]) -> list[str] | None:
    """A build of talent IDs (with their ranks) as simc options, tree by tree; None when a talent is unknown to
    this simc (another patch): the caller falls back."""
    by_tree: dict[str, list[str]] = {"class": [], "spec": [], "hero": []}
    for talent, rank in build:
        name, tree = trees.get(talent, ("", ""))
        if tree == "selection":  # the hero tree's choice node: simc knows it from the hero talents
            continue
        if tree not in by_tree:
            return None
        by_tree[tree].append(f"{simc_token(name)}:{rank}")
    if not by_tree["class"] or not by_tree["spec"]:
        return None
    return ["talents="] + [f"{t}_talents={'/'.join(v)}" for t, v in by_tree.items() if v]


def common_build(rows: list[dict]) -> tuple[tuple[int, int], ...]:
    """The build the most top players play, talent for talent (a tie goes to the best ranked)."""
    builds = Counter(tuple(sorted((int(t["talentID"]), int(t.get("points") or 1)) for t in r.get("talents") or []
                                  if t.get("talentID"))) for r in rows)
    builds.pop((), None)
    return builds.most_common(1)[0][0] if builds else ()


def tops(client, encounter_id: int, difficulty: int, cls: str, spec: str, metric: str = "bossdps") -> Tops | None:
    """The top 100 of a spec on a boss (cached 6 h, shared with the raid lead's spec profiles)."""
    from paf.raidneed import RANKING_QUERY

    data = client.query(RANKING_QUERY, {"id": encounter_id, "diff": difficulty, "cls": cls, "spec": spec,
                                        "metric": metric}, cache_ttl=6 * 3600)
    cr = ((data.get("worldData") or {}).get("encounter") or {}).get("characterRankings") or {}
    rows = [r for r in cr.get("rankings") or [] if r.get("amount")]
    if len(rows) < MIN_TOPS:
        return None
    rows.sort(key=lambda r: -r["amount"])
    top = rows[:GEAR_TOPS]
    return Tops(spec, [r["amount"] for r in rows], common_set(top), common_build(top))


CHARACTER_RANKINGS = """query($n:String!, $s:String!, $r:String!, $e:Int!, $d:Int!, $m:CharacterRankingMetricType!) {
  characterData { character(name:$n, serverSlug:$s, serverRegion:$r) {
    encounterRankings(encounterID:$e, difficulty:$d, metric:$m) } } }"""


@dataclass
class MyKills:
    spec: str
    amounts: list[float]  # each ranked kill's DPS (the metric of the tops)

    @property
    def best(self) -> float:
        return max(self.amounts)

    @property
    def median(self) -> float:
        return st.median(self.amounts)


def my_kills(client, name: str, server: str, region: str, encounter_id: int, difficulty: int, spec: str,
             metric: str = "bossdps") -> MyKills | None:
    """Your ranked kills of the boss in this spec (public logs only), or None."""
    if not (name and server and region):
        return None
    data = client.query(CHARACTER_RANKINGS, {"n": name, "s": server.lower().replace(" ", "-").replace("'", ""),
                                             "r": region.upper(), "e": encounter_id, "d": difficulty, "m": metric},
                        cache_ttl=3600)
    ch = (data.get("characterData") or {}).get("character") or {}
    ranks = (ch.get("encounterRankings") or {}).get("ranks") or []
    amounts = [r["amount"] for r in ranks if r.get("amount") and (r.get("spec") or "").replace(" ", "") == spec]
    return MyKills(spec, amounts) if amounts else None


# --- the sims and the verdict -------------------------------------------------------------------------------------


@dataclass
class SpecRow:
    spec: str  # Warcraft Logs name
    tops: float  # the median of the top 100 (DPS of the ranking's metric)
    tops_lo: float
    tops_hi: float
    sim: float | None = None  # your character in this spec, in the top players' set at TOP_ILVL
    error: float = 0.0  # the sim's standard error, in % of its mean
    gear: list[str] = field(default_factory=list)  # the set, as simc lines (for the result page)
    items: list[dict] = field(default_factory=list)  # the set's items: slot, item_id, name
    talents: str = ""  # the build kept (the best in the sim): "tops", "yours" or "simc" (the profile simc ships)
    builds: dict[str, float] = field(default_factory=dict)  # every build simmed: its DPS (the ranking's metric)


@dataclass
class Result:
    boss: str
    difficulty: str
    mine: str  # your spec (Warcraft Logs name)
    rows: list[SpecRow]
    now: float | None = None  # your character as you are, same fight
    now_error: float = 0.0
    own_talents_sim: float | None = None  # your spec in the top players' set with your own talents
    kills: MyKills | None = None
    metric: str = "bossdps"
    run_dir: Path | None = None
    notes: list[str] = field(default_factory=list)

    def row(self, spec: str) -> SpecRow | None:
        return next((r for r in self.rows if r.spec == spec), None)


def _noise(a: float, b: float) -> float:
    """Two standard deviations of the difference of two independent sims, in %."""
    return 2 * (a * a + b * b) ** 0.5


def verdict(r: Result) -> tuple[str, str]:
    """(kind, sentence): "go" when another spec is worth it, "ok" to stay, "warn" when the sim and the logs
    disagree or nothing could be simmed."""
    mine = r.row(r.mine)
    others = [x for x in r.rows if x.spec != r.mine and x.sim]
    if mine is None or not mine.sim:
        return "warn", f"Your {spec_label(r.mine)} could not be simmed in the top players' gear on this fight."
    if not others:
        return "ok", (f"Stay {spec_label(r.mine)}: no other damage spec of your class has enough ranked players on "
                      f"this boss to compare.")
    best = max(others, key=lambda x: x.sim)
    gap = 100 * (best.sim / mine.sim - 1)
    noise = _noise(best.error, mine.error)
    tops_gap = 100 * (best.tops / mine.tops - 1)
    me, it = spec_label(r.mine), spec_label(best.spec)
    if gap > noise and tops_gap > 0:
        return "go", (f"Play {it}: in the top players' gear at {TOP_ILVL} it sims {gap:+.1f}% over your {me} on this "
                      f"fight (noise ±{noise:.1f}%), and the top {it} players do {tops_gap:+.0f}% over the "
                      f"top {me}.")
    if gap > noise:
        return "warn", (f"{it} sims {gap:+.1f}% over your {me} (noise ±{noise:.1f}%), but the top {it} "
                        f"players do {tops_gap:+.0f}% against the top {me}: the sim and the logs disagree, stay "
                        f"{me} unless you try it.")
    logs = f"; the top {it} players do {tops_gap:+.0f}% against the top {me}"
    return "ok", (f"Stay {me}: {it}, the best other spec, sims {gap:+.1f}% on this fight, within the noise "
                  f"(±{noise:.1f}%){logs}." if gap > -noise else
                  f"Stay {me}: it sims {-gap:.1f}% over {it}, the best other spec, on this fight (noise "
                  f"±{noise:.1f}%){logs}.")


def gear_sentence(r: Result) -> str:
    """What the top players' set at TOP_ILVL is worth to your spec, and what their talents add on top."""
    mine = r.row(r.mine)
    if mine is None or not mine.sim or not r.now:
        return ""
    me = spec_label(r.mine)
    gear_sim = r.own_talents_sim or (mine.sim if mine.talents != "tops" else None)
    out = ""
    if gear_sim:
        gap, noise = 100 * (gear_sim / r.now - 1), _noise(mine.error, r.now_error)
        out = (f"The top players' gear at {TOP_ILVL} sims like yours on this fight ({gap:+.1f}%, noise ±{noise:.1f}%)."
               if abs(gap) <= noise else
               f"The top players' gear at {TOP_ILVL} is worth {gap:+.1f}% to your {me} on this fight (noise "
               f"±{noise:.1f}%).")
    if r.own_talents_sim and mine.talents != "yours":
        gap, noise = 100 * (mine.sim / r.own_talents_sim - 1), _noise(mine.error, mine.error)
        whose = "the top players' talents" if mine.talents == "tops" else "the build SimulationCraft ships"
        if gap > noise:
            out += f" With {whose}, {gap:+.1f}% more."
    return out


def kills_sentence(r: Result) -> str:
    what = "boss damage" if r.metric == "bossdps" else "damage"
    if r.kills is None:
        return (f"No ranked kill of yours on {r.boss} {r.difficulty} in {spec_label(r.mine)} yet (public logs): "
                f"your real {what} shows here after one.")
    k, n = r.kills, len(r.kills.amounts)
    s = (f"Your {n} ranked {'kill' if n == 1 else 'kills'} here: best {k.best:,.0f}, median {k.median:,.0f} DPS of "
         f"{what}")
    if r.now:
        s += f", {100 * k.best / r.now:.0f}% of your sim as you are ({r.now:,.0f})"
    mine = r.row(r.mine)
    if mine:
        s += f"; the top {spec_label(r.mine)} players {mine.tops:,.0f}"
    return s + "."


def compare(profile: str, client, enc, difficulty: int, diff_name: str, cls: str, mine: str, fight_lines: list[str],
            run_dir: Path, *, character: tuple[str, str, str] = ("", "", ""), target_error: float = 0.2,
            metric: str = "bossdps", log=print) -> Result:
    """The whole comparison (sims run here: one per spec, and your character as you are)."""
    from paf import simc

    res = Result(enc.name, diff_name, mine, [], metric=metric, run_dir=run_dir)
    own_talents = (re.search(r"^talents=(\S+)", profile, re.M) or [None, None])[1]
    trees = talent_trees(cls)
    for spec in DAMAGE_SPECS.get(cls, (mine,)):
        t = tops(client, enc.id, difficulty, cls, spec, metric)
        if t is None:
            res.notes.append(f"{spec_label(spec)}: fewer than {MIN_TOPS} ranked players on this boss, not compared.")
            continue
        lo, hi = t.interval()
        row = SpecRow(spec, t.median, lo, hi, gear=gear_lines(t.gear),
                      items=[{"slot": SLOTS[i], "item_id": int(it["id"]), "name": it.get("name") or ""}
                             for i, it in enumerate(t.gear) if i in SLOTS and it.get("id")])
        res.rows.append(row)
        # every build that can be the spec's best in SimulationCraft, in one run: the top players' (their export,
        # rebuilt from the rankings), the one simc ships (its APL is written for it), and yours for your spec.
        # The best is kept: simc can play a build of the top players far under what they do with it.
        clear = ["class_talents=", "spec_talents=", "hero_talents="]
        builds: dict[str, list[str]] = {}
        if lines := build_lines(t.build, trees):
            builds["tops"] = lines
        if shipped := bundled_talents(cls, spec):
            builds["simc"] = clear + [f"talents={shipped}"]
        if spec == mine and own_talents:
            builds["yours"] = clear + [f"talents={own_talents}"]
        if not builds:
            res.notes.append(f"{spec_label(spec)}: no talent build found for it, not simmed.")
            continue
        log(f"  {spec_label(spec)} in the top players' gear at {TOP_ILVL}...")
        first, *others = builds
        try:
            sim = simc.run(simc.build_input(character_in(profile, spec, builds[first], t.gear), fight_lines,
                                            {k: builds[k] for k in others}),
                           run_dir / simc_spec(spec), target_error=target_error)
        except simc.SimcError as ex:
            res.notes.append(f"{spec_label(spec)} could not be simmed ({str(ex)[-120:]}).")
            continue
        err = 100 * sim.baseline["dps"].error / sim.baseline["dps"].mean
        got = {first: (sim.baseline.get("prioritydps") or sim.baseline["dps"]).mean}
        for ps in sim.profilesets:
            got[ps.name] = (ps.metrics.get("prioritydps") or ps.dps).mean
        best = max(got, key=got.get)
        row.sim, row.error, row.talents = got[best], err, best
        row.builds = got
        if "yours" in got:
            res.own_talents_sim = got["yours"]
        if "tops" in got and got["tops"] < 0.9 * got[best]:
            other = "the build it ships" if best == "simc" else "your build"
            res.notes.append(f"{spec_label(spec)}: SimulationCraft plays the top players' build "
                             f"{100 * (1 - got['tops'] / got[best]):.0f}% under {other} (they do {t.median:,.0f} "
                             f"with it): {other} is the one simmed.")
    log("  your character as you are...")
    sim = simc.run(simc.build_input(profile, fight_lines), run_dir / "now", target_error=target_error)
    m = sim.baseline.get("prioritydps") or sim.baseline["dps"]
    res.now, res.now_error = m.mean, 100 * sim.baseline["dps"].error / sim.baseline["dps"].mean
    name, server, region = character
    try:
        res.kills = my_kills(client, name, server, region, enc.id, difficulty, mine, metric)
    except Exception as ex:  # noqa: BLE001 - your kills are a nicety: the comparison stands without them
        res.notes.append(f"Your kills could not be read: {ex}")
    return res


def to_json(r: Result) -> dict:
    kind, text = verdict(r)
    title = (text.split(":")[0] if kind in ("go", "ok") else "Not compared" if "could not be simmed" in text else
             "The sim and the logs disagree")
    rows = [{"spec": x.spec, "label": spec_label(x.spec), "tops": x.tops, "tops_lo": x.tops_lo, "tops_hi": x.tops_hi,
             "sim": x.sim, "error": x.error, "gear": x.gear, "items": x.items} for x in r.rows]
    return {"boss": r.boss, "difficulty": r.difficulty, "mine": r.mine, "ilvl": TOP_ILVL, "metric": r.metric,
            "gear_tops": GEAR_TOPS, "verdict": kind, "title": title, "sentence": text,
            "gear_sentence": gear_sentence(r), "kills_sentence": kills_sentence(r), "now": r.now, "rows": rows,
            "kills": {"best": r.kills.best, "median": r.kills.median, "n": len(r.kills.amounts)} if r.kills else None,
            "notes": r.notes}
