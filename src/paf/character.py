"""Your character from Warcraft Logs, without a /simc export (issue #11): name, server and region give your latest
logged boss fight, whose gear, talents and secondary stats make a SimulationCraft profile (as the validation does for
the top players, paf.validate). It has no bags: Top Gear and the droptimizer still need the /simc export."""

from __future__ import annotations

import json
import time

CHARACTER_QUERY = """query($n:String!,$s:String!,$r:String!){ characterData { character(name:$n, serverSlug:$s,
  serverRegion:$r) { name faction { name } recentReports(limit: 8) { data { code startTime } } } } }"""
REPORT_QUERY = """query($c:String!){ reportData { report(code:$c) {
  fights(killType: Encounters) { id endTime } masterData { actors(type:"Player") { id name } } } } }"""
DETAILS_QUERY = """query($c:String!,$f:[Int]!){ reportData { report(code:$c) {
  playerDetails(fightIDs:$f, includeCombatantInfo:true) } } }"""
FIGHTS_PER_REPORT = 3  # boss fights tried per report, newest first


def server_slug(server: str) -> str:
    from paf.raidneed import server_slug as slug

    return slug(server)


def _details(client, code: str, fight_id: int, actor_id: int) -> dict | None:
    data = client.query(DETAILS_QUERY, {"c": code, "f": [fight_id]}, cache_ttl=3600)
    pd = (data["reportData"]["report"] or {}).get("playerDetails") or {}
    if isinstance(pd, str):
        pd = json.loads(pd)
    pd = (pd.get("data") or pd).get("playerDetails") or pd
    for role in ("dps", "healers", "tanks"):
        for p in pd.get(role) or []:
            if p.get("id") == actor_id:
                return p
    return None


def import_character(client, name: str, server: str, region: str) -> tuple[str, str]:
    """(SimulationCraft profile, what was read) from your latest logged boss fight. ValueError when the character
    or a usable log cannot be found."""
    from paf.talent_sim import IMPORT_CODE_QUERY
    from paf.validate import STAT_OPTIONS, profile_from_log

    name, region = name.strip(), (region or "eu").strip().upper()
    ch = client.query(CHARACTER_QUERY, {"n": name, "s": server_slug(server), "r": region},
                      cache_ttl=0)["characterData"]["character"]
    if ch is None:
        raise ValueError(f"{name} ({server}, {region}) is not on Warcraft Logs: check the name and the server, or "
                         f"paste your /simc export")
    race = "orc" if ((ch.get("faction") or {}).get("name") or "").lower() == "horde" else "human"
    for rep in (ch.get("recentReports") or {}).get("data") or []:
        r = client.query(REPORT_QUERY, {"c": rep["code"]}, cache_ttl=3600)["reportData"]["report"] or {}
        me = next((a for a in (r.get("masterData") or {}).get("actors") or []
                   if a.get("name", "").lower() == name.lower()), None)
        if me is None:
            continue
        for f in sorted(r.get("fights") or [], key=lambda f: -f["endTime"])[:FIGHTS_PER_REPORT]:
            p = _details(client, rep["code"], f["id"], me["id"])
            info = (p or {}).get("combatantInfo") or {}
            if not info.get("gear"):
                continue
            cls = p.get("type") or ""
            spec = ((p.get("specs") or [{}])[0].get("spec") or (p.get("icon") or "-").split("-", 1)[1]).replace(" ", "")
            data = client.query(IMPORT_CODE_QUERY, {"code": rep["code"], "f": [f["id"]], "a": me["id"]}, cache_ttl=0)
            fights = (data["reportData"]["report"] or {}).get("fights") or []
            talents = fights[0].get("talentImportCode") if fights else None
            if not cls or not spec or not talents:
                continue
            profile = profile_from_log(ch.get("name") or name, cls, spec, race, talents, info["gear"])
            # the log does not carry the stats of crafted items: the real secondary ratings instead
            stats = info.get("stats") or {}
            profile += "".join(f"{opt}={int(stats[k]['max'])}\n" for k, opt in STAT_OPTIONS.items()
                               if (stats.get(k) or {}).get("max"))
            when = time.strftime("%d %b", time.localtime(rep["startTime"] / 1000))
            return profile, f"{ch.get('name') or name}, {spec} {cls}: gear and talents from your log of {when}"
    raise ValueError(f"no recent boss fight of {name} in a public log: paste your /simc export instead")
