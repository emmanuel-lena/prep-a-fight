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
SIM_STEPS = ("Calibrating the fight", "Validating the fight", "Your raid and the adds", "Simming your character",
             "Cooldown timelines", "Talent builds", "Cooldown plans", "Top Gear", "What this boss drops",
             "Ideal cooldown plan", "Analyzing the corpus")
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
                "corpus": "Uses the kills already in your corpus.",
                "collect": f"Downloads the top {self.kills} kills of your spec from Warcraft Logs; more follow in "
                           f"the background afterwards."}[self.source]
        wait = (f" Includes about {round(self.wait)} min waiting for your Warcraft Logs quota."
                if self.wait >= 1 else "")
        return f"{what} About {max(1, round(self.minutes))} min.{wait}"


def sims_minutes() -> float:
    import statistics as st

    from paf.progress import history

    hist = history()
    done = [st.median(v) for k, v in hist.items() if v and k.startswith(SIM_STEPS)]
    return sum(done) / 60 if done else TYPICAL_SIMS


def plan(con, encounter_id: int, difficulty: int, class_name: str, spec: str, client=None) -> Estimate:
    from paf import pack
    from paf.cli import FIRST_SHEET

    sims = sims_minutes()
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
    left, reset = QUOTA, 60.0
    if client is not None:
        try:
            rl = client.rate_limit()
            left, reset = max(0.0, rl["limitPerHour"] - rl["pointsSpentThisHour"]), rl["pointsResetIn"] / 60
        except Exception:  # noqa: BLE001 - unknown quota: a fresh hour
            pass
    wait = 0.0
    if points > left:  # past what is left this hour: the reset, then whole hours
        extra = points - left
        wait = reset + 60.0 * max(0.0, extra / QUOTA - 1)
    collect = kills / KILLS_PER_MIN
    return Estimate("collect", collect + wait + sims, kills=kills, wait=wait, sims=sims)
