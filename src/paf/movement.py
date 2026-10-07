"""Moving or standing still: what a second of movement costs, when the strategy makes everyone move, and which
mobility spell the top players use then.

- The windows where most top players move at once (paf.corpus.template.movement_windows) are the strategy: move.
- SimC gives the cost of moving without casting: the same fight with and without those windows.
- The top players lose much less than that (they keep casting while moving): the validation's movement scale
  (paf.validate.calibrate_movement) measures how much of it they really lose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# spells that let a player keep casting while moving, or cover distance fast (English names, as in the logs)
MOBILITY = {
    "Spiritwalker's Grace", "Gust of Wind", "Ghost Wolf", "Ice Floes", "Blink", "Shimmer", "Hover", "Burning Rush",
    "Demonic Circle: Teleport", "Disengage", "Sprint", "Shadowstep", "Heroic Leap", "Charge", "Roll", "Chi Torpedo",
    "Wild Charge", "Dash", "Stampeding Roar", "Tiger Dash", "Door of Shadows", "Angelic Feather", "Fel Rush",
    "Vengeful Retreat", "Infernal Strike", "Death's Advance", "Wraith Walk", "Divine Steed", "Feline Swiftness",
    "Aspect of the Cheetah", "Soar", "Rescue", "Swiftness",
}
SUPPORT = 0.4  # share of the top players casting a mobility spell in a window for it to be suggested there
LEAD = 3.0  # seconds before a window when a mobility spell cast still counts for it
MIN_WINDOW = 5.0  # seconds; shorter windows are not worth a line


@dataclass
class Window:
    start: float
    duration: float
    spells: list[tuple[str, float]] = field(default_factory=list)  # mobility spell, share of the top players


@dataclass
class Movement:
    windows: list[Window]  # when the strategy makes most top players move
    cost_10s: float | None = None  # % of DPS lost per 10 s of movement without casting (SimC, your character)
    scale: float = 1.0  # share of that cost the top players really lose (validation)
    moving_share: float = 0.0  # share of the fight the top players spend moving

    @property
    def covered(self) -> float:
        return sum(w.duration for w in self.windows)


def mobility(timeline, windows: list) -> list[Window]:
    """The strategy's movement windows, each with the mobility spells most top players cast for it."""
    if timeline is None:
        return [Window(w.start, w.duration) for w in windows if w.duration >= MIN_WINDOW]
    abilities = [a for a in timeline.abilities if a.name in MOBILITY]
    players = timeline.players or []
    out = []
    for w in windows:
        if w.duration < MIN_WINDOW:
            continue
        spells = []
        for a in abilities:
            used = sum(any(w.start - LEAD <= t <= w.start + w.duration for t in p["casts"].get(a.id, []))
                       for p in players)
            share = used / len(players) if players else 0.0
            if share >= SUPPORT and a.name not in {s for s, _ in spells}:
                spells.append((a.name, round(share, 2)))
        out.append(Window(w.start, w.duration, sorted(spells, key=lambda s: -s[1])))
    return out


def cost(base_dps: float, moving_dps: float, seconds: float) -> float | None:
    """% of DPS lost per 10 s of movement without casting, from two sims of the same fight."""
    if not base_dps or seconds <= 0:
        return None
    return round(max(0.0, (base_dps - moving_dps) / base_dps * 100) / seconds * 10, 2)
