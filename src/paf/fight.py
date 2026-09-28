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


@dataclass
class Window:
    start: float
    duration: float
    distance: float = 0.0  # movement only (yards)


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

    def raid_event_lines(self, add_scale: float | None = None) -> list[str]:
        scale = self.add_scale if add_scale is None else add_scale
        events: list[str] = []
        for i, w in enumerate(sorted(self.add_waves, key=lambda w: w.time), 1):
            count = max(1, round(w.count * scale))
            events.append(f"adds,name=wave{i},count={count},first={fmt(round(w.time, 1))},"
                          f"duration={fmt(round(w.lifetime, 1))},cooldown=9999")
        for w in self.invulnerable:
            events.append(f"invulnerable,first={fmt(round(w.start, 1))},"
                          f"duration={fmt(round(w.duration, 1))},cooldown=9999")
        for w in self.movement:
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
        d = json.loads(path.read_text(encoding="utf-8"))
        d["add_waves"] = [AddWave(**w) for w in d.get("add_waves", [])]
        d["invulnerable"] = [Window(**w) for w in d.get("invulnerable", [])]
        d["movement"] = [Window(**w) for w in d.get("movement", [])]
        return cls(**d)


PRESETS: dict[str, list[str]] = {
    "patchwerk": ["fight_style=Patchwerk", "max_time=300", "desired_targets=1"],
    "cleave2": ["fight_style=Patchwerk", "max_time=300", "desired_targets=2"],
    "aoe5": ["fight_style=Patchwerk", "max_time=300", "desired_targets=5"],
}
