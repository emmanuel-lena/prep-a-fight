"""Before a prep starts: where its data will come from and how long it will take, from what will really happen.

- A prep pack of this week on this computer, or shared by another player (relay): no download from Warcraft Logs,
  only the sims.
- Else the local corpus when it has kills, else the first FIRST_SHEET kills collected from Warcraft Logs.
A collection costs about POINTS_PER_KILL points a kill (measured: 10) at KILLS_PER_MIN while the quota allows (25),
plus who handles each mechanic (about 2 points a kill); the key allows 3600 points an hour: past the points left in
this hour, the prep waits for the reset (rate_limit gives both). The sims take the median of this computer's last
preps (paf.progress history), else typical minutes.
"""

from __future__ import annotations

from dataclasses import dataclass

POINTS_PER_KILL = 10.0
MECH_POINTS_PER_KILL = 2.0
KILLS_PER_MIN = 25.0
QUOTA = 3600.0
COLLECT = ("Collecting", "Using the prep pack")  # the steps of where the data comes from, counted apart
TYPICAL_SIMS = 8.0  # minutes, a first prep on an average computer with everything checked


@dataclass
class Estimate:
    source: str  # pack_local | pack_shared | corpus | collect
    minutes: float
    kills: int = 0  # kills to download
    wait: float = 0.0  # minutes waiting for the quota's reset
    sims: float = 0.0  # minutes of sims

    @property
    def sentence(self) -> str:
        what = {"pack_local": "Uses the prep pack already on your computer: nothing to download.",
                "pack_shared": "Uses the prep pack another player shared this week: nothing to download from "
                               "Warcraft Logs.",
                "corpus": "Uses the top kills already downloaded on your computer: nothing to download.",
                "collect": f"Downloads the top {self.kills} kills of your spec from Warcraft Logs; more follow in "
                           f"the background afterwards."}[self.source]
        wait = (f" Includes about {round(self.wait)} min waiting for your Warcraft Logs quota."
                if self.wait >= 1 else "")
        return f"{what} About {max(1, round(self.minutes))} min.{wait}"


    @property
    def lead(self) -> str:
        """The boss page's answer, one sentence: how long, and from what."""
        what = {"pack_local": "from the prep pack already on your computer",
                "pack_shared": "from a prep pack another player shared this week",
                "corpus": "from the top kills already on your computer",
                "collect": f"after downloading the top {self.kills} kills of your spec from Warcraft Logs"}[self.source]
        wait = f", {round(self.wait)} min of it waiting for your Warcraft Logs quota" if self.wait >= 1 else ""
        return f"About {max(1, round(self.minutes))} min to prepare, {what}{wait}."


    @property
    def badge(self) -> str:
        """The lead as a badge (fresh app review 5): "~2 min · prep pack", the quota's wait apart."""
        what = "" if self.source != "collect" else f" · downloads {self.kills} kills"  # the source on hover; a
        wait = f" · {round(self.wait)} min of quota" if self.wait >= 1 else ""  # download said (it takes the time)
        return f"~{max(1, round(self.minutes))} min to prepare{what}{wait}"


def sims_minutes(first: bool = False) -> float:
    """Every step after the data's, as this computer ran them (paf.progress._minutes: a first prep of a boss from
    the first preps); none run yet: typical minutes."""
    from paf.progress import PREP_STEPS, _minutes, history

    hist = history()
    steps = [p for p, *_ in PREP_STEPS if not p.startswith(COLLECT) and hist.get(p)]
    return sum(_minutes(p, hist, 0.0, first) for p in steps) if steps else TYPICAL_SIMS


def collect_minutes(kills: int, first_sheet: int) -> float:
    """Downloading `kills` kills and who handles what in them: this computer's pace, else the typical rate."""
    from paf.progress import _minutes, history

    hist = history()
    if not hist.get("Collecting the corpus"):
        return kills / KILLS_PER_MIN
    share = kills / max(1, first_sheet)
    return share * (_minutes("Collecting the corpus", hist, 0.0) + _minutes("Collecting who handles", hist, 0.0))


def plan(con, encounter_id: int, difficulty: int, class_name: str, spec: str, client=None,
         first: bool = False) -> Estimate:
    """`first`: no prep of this boss for this spec on this computer yet (every sim runs)."""
    from paf import pack
    from paf.cli import FIRST_SHEET

    sims = sims_minutes(first)
    local = pack.load(encounter_id, difficulty, class_name, spec)
    if local is not None and not pack.is_stale(local.created) and pack.usable(local):
        return Estimate("pack_local", sims, sims=sims)
    try:
        shared = pack.fetch_shared(encounter_id, difficulty, class_name, spec)
    except Exception:  # noqa: BLE001 - offline: no shared pack
        shared = None
    if shared is not None and not pack.is_stale(shared.created):
        return Estimate("pack_shared", sims + 0.2, sims=sims)
    done = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done' "
                       "AND COALESCE(cohort, '') != 'focus'", (encounter_id, difficulty)).fetchone()[0]
    if done >= 20:
        return Estimate("corpus", sims, sims=sims)
    kills = max(0, FIRST_SHEET - done)
    points = kills * (POINTS_PER_KILL + MECH_POINTS_PER_KILL)
    from paf.wcl import quota_left

    left, reset = quota_left(client)  # never waits: a page shows this estimate
    wait = 0.0
    if points > left:  # past what is left this hour: the reset, then whole hours
        extra = points - left
        wait = reset + 60.0 * max(0.0, extra / QUOTA - 1)
    collect = collect_minutes(kills, FIRST_SHEET)
    return Estimate("collect", collect + wait + sims, kills=kills, wait=wait, sims=sims)
