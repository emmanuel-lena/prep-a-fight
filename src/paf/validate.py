"""Validate a rebuilt fight against reality: sim the top players' own characters (gear and talents from
their logs) on the fight and compare with the DPS they actually did."""

from __future__ import annotations

import json
import sqlite3
import statistics as st
from dataclasses import dataclass, field
from pathlib import Path

from paf import simc
from paf.cdplan import apl_lines, dump_apl, parse_apl
from paf.corpus.analyze import kills_filter
from paf.fight import Fight
from paf.talent_sim import IMPORT_CODE_QUERY
from paf.wcl import WCLClient

# Warcraft Logs gear array index -> simc slot
GEAR_SLOTS = {0: "head", 1: "neck", 2: "shoulder", 4: "chest", 5: "waist", 6: "legs", 7: "feet", 8: "wrist",
              9: "hands", 10: "finger1", 11: "finger2", 12: "trinket1", 13: "trinket2", 14: "back",
              15: "main_hand", 16: "off_hand"}


def profile_from_log(name: str, cls: str, spec: str, race: str, talents: str, gear: list[dict]) -> str:
    lines = [f'{cls.lower()}="{name}"', "level=90", f"race={race}", "role=spell", f"spec={spec.lower()}",
             f"talents={talents}"]
    for i, it in enumerate(gear):
        slot = GEAR_SLOTS.get(i)
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
        if it.get("itemLevel") and not it.get("bonusIDs"):
            v += f",ilevel={it['itemLevel']}"
        if it.get("itemLevel"):  # "# Name (ilvl)" before the item, as in a /simc export (the loot step needs it)
            lines.append(f"# {it.get('name') or 'item'} ({it['itemLevel']})")
        lines.append(v)
    return "\n".join(lines) + "\n"


DETAILS_QUERY = """
query($code:String!, $f:[Int]!) { reportData { report(code:$code) {
  playerDetails(fightIDs:$f, includeCombatantInfo:true) } } }
"""
STAT_OPTIONS = {"Crit": "gear_crit_rating", "Haste": "gear_haste_rating", "Mastery": "gear_mastery_rating",
                "Versatility": "gear_versatility_rating"}


def stat_overrides(client: WCLClient, report: str, fight_id: int, actor_id: int) -> list[str]:
    """The player's real secondary ratings from the log, as simc gear totals. Logs do not carry the stats
    of crafted items, so without this the rebuilt character is weaker than the real one."""
    data = client.query(DETAILS_QUERY, {"code": report, "f": [fight_id]}, cache_ttl=0)
    pd = (data["reportData"]["report"] or {}).get("playerDetails") or {}
    if isinstance(pd, str):
        pd = json.loads(pd)
    pd = (pd.get("data") or pd).get("playerDetails") or pd
    for role in ("dps", "healers", "tanks"):
        for p in pd.get(role) or []:
            if p.get("id") == actor_id:
                stats = (p.get("combatantInfo") or {}).get("stats") or {}
                out = []
                for key, option in STAT_OPTIONS.items():
                    v = (stats.get(key) or {}).get("max")
                    if v:
                        out.append(f"{option}={int(v)}")
                return out
    return []


@dataclass
class Check:
    rank: int
    real: float
    sim: float
    sim_boss: float | None
    profile: str = field(default="", repr=False)
    sim_default: float | None = None  # with the default APL, when sim is with cooldowns held like the tops

    @property
    def ratio(self) -> float:
        return self.sim / self.real if self.real else 0.0


def aligned_apl(profile: str, fight: Fight, run_dir: Path) -> tuple[list[str], list[str]] | None:
    """(default APL, APL with the long cooldowns kept for the vulnerability windows) as profile lines, or None
    when the fight has no such window. Top players stack their cooldowns in these windows (Coiled Altar: 100%
    of the Ascendance casts in the intermission) while the default APL casts them on cooldown, so simming
    them with the default APL underestimates what they do."""
    if not fight.vulnerable:
        return None
    from paf.optimize import apply_rules, cooldown_durations, find_cooldowns

    apl = parse_apl(dump_apl(profile, run_dir / "apl"))
    durations, _ = cooldown_durations(profile, run_dir / "probe", apl)
    choice = {}
    for c in find_cooldowns(apl, fight, durations):
        want = "hold_vulnerable_90" if c.long else "hold_vulnerable_30"
        rule = next((r for r in c.rules if r.name == want), None)
        if rule:
            choice[c.key] = rule
    return apl_lines(apl), apply_rules(apl, choice)


def validate(con: sqlite3.Connection, client: WCLClient, encounter_id: int, difficulty: int, spec: str,
             fight: Fight, run_dir: Path, *, players: int = 6, race: str = "orc",
             target_error: float = 0.3, align: bool = True) -> list[Check]:
    """align: sim the tops with their long cooldowns kept for the vulnerability windows (as they play), the
    default APL being reported next to it."""
    where, params = kills_filter(encounter_id, difficulty)
    rows = con.execute(
        f"SELECT r.* FROM ranked r JOIN fight f USING(report, fight_id) WHERE {where} AND r.spec=? "
        f"AND r.actor_id IS NOT NULL ORDER BY r.rank_pos", (*params, spec)).fetchall()
    checks: list[Check] = []
    apls = None
    for r in rows:
        if len(checks) >= players:
            break
        code = r["talent_code"]
        if not code:
            data = client.query(IMPORT_CODE_QUERY, {"code": r["report"], "f": [r["fight_id"]], "a": r["actor_id"]},
                                cache_ttl=0)
            fights = (data["reportData"]["report"] or {}).get("fights") or []
            code = fights[0].get("talentImportCode") if fights else None
            if not code:
                continue
            con.execute("UPDATE ranked SET talent_code=? WHERE report=? AND fight_id=?",
                        (code, r["report"], r["fight_id"]))
            con.commit()
        gear = json.loads(r["gear_json"] or "[]")
        if not gear:
            continue
        prof = profile_from_log(f"rank{r['rank_pos']}", r["class"], r["spec"], race, code, gear)
        prof += "\n".join(stat_overrides(client, r["report"], r["fight_id"], r["actor_id"])) + "\n"
        if align and apls is None:
            apls = aligned_apl(prof, fight, run_dir) or False
        if apls:
            default_lines, held_lines = apls
            res = simc.run(simc.build_input(prof + "\n".join(default_lines) + "\n", fight.to_simc(),
                                            {"held": held_lines}),
                           run_dir / f"rank{r['rank_pos']}", target_error=target_error)
            ps = next(p for p in res.profilesets if p.name == "held")
            boss = ps.metrics.get("prioritydps")
            checks.append(Check(r["rank_pos"], r["dps"], ps.dps.mean, boss.mean if boss else None,
                                prof + "\n".join(held_lines) + "\n", res.baseline["dps"].mean))
            continue
        res = simc.run(simc.build_input(prof, fight.to_simc()), run_dir / f"rank{r['rank_pos']}",
                       target_error=target_error)
        boss = res.baseline.get("prioritydps")
        checks.append(Check(r["rank_pos"], r["dps"], res.baseline["dps"].mean, boss.mean if boss else None, prof))
    return checks


MOVEMENT_SCALES = (0.0, 0.25, 0.5, 0.75, 1.0)


def calibrate_movement(checks: list[Check], fight: Fight, run_dir: Path,
                       target_error: float = 0.3) -> tuple[float, list[tuple[float, float]]]:
    """Movement scale for which the top players' simulated DPS matches their real DPS (median ratio 1)."""
    per_scale: dict[float, list[float]] = {s: [] for s in MOVEMENT_SCALES}
    fixed = [line for line in fight.to_simc() if not line.startswith("raid_events")]
    for check in checks:
        prof = check.profile
        sets = {f"m{int(s * 100)}": fight.raid_event_lines(movement_scale=s) for s in MOVEMENT_SCALES}
        res = simc.run(simc.build_input(prof, fixed + fight.raid_event_lines(), sets), run_dir / f"cal{check.rank}",
                       target_error=target_error)
        for ps in res.profilesets:
            s = int(ps.name[1:]) / 100
            per_scale[s].append(ps.dps.mean / check.real)
    points = [(s, st.median(v)) for s, v in sorted(per_scale.items()) if v]
    scale = 1.0
    for (s0, r0), (s1, r1) in zip(points, points[1:], strict=False):
        if (r0 - 1.0) * (r1 - 1.0) <= 0 and r0 != r1:
            scale = s0 + (s1 - s0) * (r0 - 1.0) / (r0 - r1)
            break
    else:
        if points:
            scale = min(points, key=lambda p: abs(p[1] - 1.0))[0]
    return round(scale, 2), points


def summary(checks: list[Check]) -> tuple[float, float, float] | None:
    if not checks:
        return None
    ratios = sorted(c.ratio for c in checks)
    return ratios[0], st.median(ratios), ratios[-1]
