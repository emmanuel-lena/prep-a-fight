"""A boss fight model and its translation to SimulationCraft options.

Facts verified on simc 1210-01 (docs/research/simc-experiments.md):
- no ``fight_style`` line: Patchwerk silently discards raid_events;
- adds cannot die from damage, their lifetime is ``duration=`` (taken from logs);
- one ``adds`` line per wave with ``cooldown=9999`` (``last=`` is exclusive);
- ``external_buffs.power_infusion`` needs ``/`` between times.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from paf.simc import fmt


@dataclass
class AddWave:
    time: float  # seconds from pull
    count: int
    lifetime: float  # seconds the adds stay alive
    name: str = ""
    scalable: bool = True  # False for unique units (e.g. a secondary boss): calibration never changes the count


@dataclass
class Window:
    start: float
    duration: float
    distance: float = 0.0  # movement only (yards)


@dataclass
class Vulnerable:
    """A window where the boss takes more damage, e.g. a heart that shares the boss's health with a
    damage amplifier: damage done to it counts as boss damage (SimC raid event ``vulnerable``)."""
    start: float
    duration: float
    multiplier: float
    name: str = ""
    source: str = ""  # where the multiplier comes from: "game data (spell N)", "measured in the logs", "notes"


@dataclass
class Focus:
    """Which council member the top players mostly hit (information only: the simulated bosses are the stacked
    members, see Fight.targets)."""
    start: float
    duration: float
    name: str
    support: float  # share of the kills where they hit that boss then


def merged_movement(windows: list[Window]) -> list[Window]:
    """Union of overlapping movement windows. In SimC a movement event that starts during another one
    replaces it (it can shorten it), so overlaps must be merged before being sent."""
    timed = sorted((w for w in windows if not w.distance), key=lambda w: w.start)
    out: list[Window] = []
    for w in timed:
        if out and w.start <= out[-1].start + out[-1].duration:
            last = out[-1]
            end = max(last.start + last.duration, w.start + w.duration)
            out[-1] = Window(last.start, end - last.start)
        else:
            out.append(Window(w.start, w.duration))
    return out + [w for w in windows if w.distance]


@dataclass
class Fight:
    name: str
    duration: float
    add_waves: list[AddWave] = field(default_factory=list)
    invulnerable: list[Window] = field(default_factory=list)
    movement: list[Window] = field(default_factory=list)
    lust_time: float | None = 0.0  # None = no lust
    power_infusion: list[float] = field(default_factory=list)
    source: str = ""  # free text: which logs / cohort this was built from
    add_scale: float = 1.0  # multiplies add counts (calibration: adds a player actually hits)
    movement_scale: float = 1.0  # multiplies inferred movement durations (calibration on the top players' DPS)
    personal_movement: list[Window] = field(default_factory=list)  # player's own moves: never scaled
    vulnerable: list[Vulnerable] = field(default_factory=list)  # boss damage amplification windows
    # possible amps detected in the logs (auras on the boss): not simulated until confirmed in the boss notes
    candidate_vulnerable: list[Vulnerable] = field(default_factory=list)
    focus: list[Focus] = field(default_factory=list)  # a council: who the top players hit, when
    targets: int = 1  # bosses hit at once the whole fight (a council's stacked members): desired_targets

    def _spawns(self) -> list[tuple[float, float, AddWave]]:
        """(spawn, lifetime, wave) as simulated. SimC never goes back to the boss if an add is still alive when
        an invulnerability ends (retarget=1; verified on Nek'zali: 0 DPS until the end), so an add alive at that
        moment dies 1 s before the boss comes back and, if it outlives it, respawns 0.5 s after."""
        out = []
        for w in sorted(self.add_waves, key=lambda w: w.time):
            parts = [(w.time, w.time + w.lifetime)]
            for inv in self.invulnerable:
                back = inv.start + inv.duration
                nxt = []
                for a, b in parts:
                    if a < back - 1 and b > back - 1:
                        nxt.append((a, back - 1))
                        if b > back + 1.5:
                            nxt.append((back + 0.5, b))
                    else:
                        nxt.append((a, b))
                parts = nxt
            out += [(a, b - a, w) for a, b in parts if b - a >= 1]
        return out

    def raid_event_lines(self, add_scale: float | None = None, movement_scale: float | None = None) -> list[str]:
        scale = self.add_scale if add_scale is None else add_scale
        mscale = self.movement_scale if movement_scale is None else movement_scale
        moves = [Window(w.start, w.duration * mscale, w.distance * mscale) for w in self.movement]
        moves = [w for w in moves if w.duration >= 0.5 or w.distance] + list(self.personal_movement)
        events: list[str] = []
        for i, (t, life, w) in enumerate(self._spawns(), 1):
            count = max(1, round(w.count * scale)) if w.scalable else w.count
            events.append(f"adds,name=wave{i},count={count},first={fmt(round(t, 1))},"
                          f"duration={fmt(round(life, 1))},cooldown=9999")
        for w in self.invulnerable:  # retarget: without it the player keeps hitting the immune boss
            events.append(f"invulnerable,first={fmt(round(w.start, 1))},"
                          f"duration={fmt(round(w.duration, 1))},cooldown=9999,retarget=1")
        for v in self.vulnerable:
            events.append(f"vulnerable,first={fmt(round(v.start, 1))},duration={fmt(round(v.duration, 1))},"
                          f"cooldown=9999,multiplier={fmt(round(v.multiplier, 2))}")
        for w in merged_movement(moves):
            ev = f"movement,first={fmt(round(w.start, 1))},cooldown=9999"
            if w.distance:
                ev += f",distance={fmt(round(w.distance, 1))}"
            else:
                ev += f",duration={fmt(round(w.duration, 1))}"
            events.append(ev)
        return [("raid_events=/" if j == 0 else "raid_events+=/") + ev for j, ev in enumerate(events)]

    def to_simc(self) -> list[str]:
        lines = [
            f"# fight: {self.name}" + (f" ({self.source})" if self.source else ""),
            "fixed_time=1",
            "vary_combat_length=0",
            f"max_time={fmt(round(self.duration, 1))}",
        ]
        if self.targets > 1:  # every target is a boss: simc's priority damage would count the first one only
            lines.append(f"desired_targets={self.targets}")
        if self.lust_time is None:
            lines.append("override.bloodlust=0")
        else:
            lines.append(f"bloodlust_time={fmt(round(self.lust_time, 1))}")
        if self.power_infusion:
            lines.append("external_buffs.power_infusion="
                         + "/".join(fmt(round(t, 1)) for t in self.power_infusion))

        return lines + self.raid_event_lines()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        path.with_suffix(".simc").write_text("\n".join(self.to_simc()) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Fight:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, d: dict) -> Fight:
        d = dict(d)
        d["add_waves"] = [AddWave(**w) for w in d.get("add_waves", [])]
        d["invulnerable"] = [Window(**w) for w in d.get("invulnerable", [])]
        d["movement"] = [Window(**w) for w in d.get("movement", [])]
        d["personal_movement"] = [Window(**w) for w in d.get("personal_movement", [])]
        d["vulnerable"] = [Vulnerable(**w) for w in d.get("vulnerable", [])]
        d["candidate_vulnerable"] = [Vulnerable(**w) for w in d.get("candidate_vulnerable", [])]
        d["focus"] = [Focus(**w) for w in d.get("focus", [])]
        return cls(**d)


PRESETS: dict[str, list[str]] = {
    "patchwerk": ["fight_style=Patchwerk", "max_time=300", "desired_targets=1"],
    "cleave2": ["fight_style=Patchwerk", "max_time=300", "desired_targets=2"],
    "aoe5": ["fight_style=Patchwerk", "max_time=300", "desired_targets=5"],
}
