"""Run SimulationCraft and read its JSON results.

Options passed on the command line *after* the input file override those in the file, so the
input file holds the character (+ fight) and profilesets, and run options go on the command line.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from paf import cache as sim_cache
from paf.simc_install import find_simc


class SimcError(RuntimeError):
    pass


def fmt(x: float) -> str:
    """Locale-independent number for simc (never '0,1')."""
    return repr(float(x)) if not float(x).is_integer() else str(int(x))


@dataclass
class Metric:
    mean: float
    error: float = 0.0  # half-width of the confidence interval, as reported by simc


@dataclass
class ProfilesetResult:
    name: str
    metrics: dict[str, Metric] = field(default_factory=dict)
    iterations: int = 0

    @property
    def dps(self) -> Metric:
        return self.metrics["dps"]


@dataclass
class SimResult:
    baseline: dict[str, Metric]
    profilesets: list[ProfilesetResult]
    json_path: Path
    elapsed: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def delta_pct(self, ps: ProfilesetResult, metric: str = "dps") -> float:
        base = self.baseline[metric].mean
        return (ps.metrics[metric].mean - base) / base * 100 if base else 0.0


# profileset metric names as written in the JSON -> our short keys
_METRIC_KEYS = {
    "damage per second": "dps",
    "dps": "dps",
    "priority target damage per second": "prioritydps",
    "damage per second to priority target/boss": "prioritydps",
    "priority dps": "prioritydps",
    "prioritydps": "prioritydps",
    "damage per second (effective)": "dpse",
    "healing per second": "hps",
}


def metric_key(name: str) -> str:
    return _METRIC_KEYS.get(name.strip().lower(), name.strip().lower().replace(" ", "_"))


def _metric(d: dict[str, Any] | None) -> Metric | None:
    if not isinstance(d, dict) or "mean" not in d:
        return None
    err = d.get("mean_std_dev")
    if err is None:
        err = d.get("mean_error", 0.0)
    return Metric(float(d["mean"]), float(err or 0.0))


def parse_json(path: Path) -> SimResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    sim = raw.get("sim", raw)
    players = sim.get("players") or []
    if not players:
        raise SimcError(f"no player in {path}")
    cd = players[0].get("collected_data", {})
    baseline: dict[str, Metric] = {}
    for key in ("dps", "prioritydps", "dpse", "hps"):
        m = _metric(cd.get(key))
        if m and (m.mean or key == "dps"):
            baseline[key] = m
    if "dps" not in baseline:
        m = _metric((sim.get("statistics") or {}).get("raid_dps"))
        if m:
            baseline["dps"] = m

    results: list[ProfilesetResult] = []
    ps_block = sim.get("profilesets") or {}
    metric_name = metric_key(ps_block.get("metric", "dps")) if isinstance(ps_block, dict) else "dps"
    for r in (ps_block.get("results") or []) if isinstance(ps_block, dict) else []:
        err = r.get("mean_error")
        if err is None:
            err = r.get("mean_stddev", 0.0)
        pr = ProfilesetResult(r["name"], {metric_name: Metric(float(r["mean"]), float(err or 0.0))},
                              int(r.get("iterations", 0)))
        for extra in r.get("additional_metrics") or []:
            m = _metric(extra)
            if m and extra.get("metric"):
                pr.metrics[metric_key(extra["metric"])] = m
        if "dps" not in pr.metrics and metric_name != "dps":
            pr.metrics.setdefault("dps", pr.metrics[metric_name])
        results.append(pr)
    return SimResult(baseline, results, path, raw=raw)


def new_run_dir(root: Path | None = None, label: str = "") -> Path:
    if root is None:  # a source checkout keeps its runs next to the code, an installed copy in the data dir
        from paf.config import data_dir

        root = Path.cwd() / "runs" if (Path.cwd() / "pyproject.toml").is_file() else data_dir() / "runs"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    d = root / (f"{stamp}-{label}" if label else stamp)
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_input(profile: str, fight_lines: list[str] | None = None,
                profilesets: dict[str, list[str]] | None = None) -> str:
    """Character first, then fight options (enemies after the player), then profilesets.

    Beware: ``fight_style=Patchwerk`` silently discards raid_events; leave fight_style out of
    reconstructed fights.
    """
    lines = [profile.rstrip(), ""]
    if fight_lines:
        lines += fight_lines + [""]
    for name, opts in (profilesets or {}).items():
        if "." in name or '"' in name:
            raise ValueError(f"invalid profileset name {name!r}")
        first = True
        for o in opts:
            lines.append(f'profileset."{name}"{"=" if first else "+="}{o}')
            first = False
    return "\n".join(lines) + "\n"


def run(input_text: str, run_dir: Path, *, target_error: float = 0.2, iterations: int | None = None,
        threads: int = 0, metrics: tuple[str, ...] = ("dps", "prioritydps"), work_threads: int = 4,
        extra: list[str] | None = None, simc: str | None = None,
        html: bool = False, timeout: float | None = None, cache: bool = True) -> SimResult:
    """Run simc. Profilesets are ranked by metrics[0]; the others come back as additional metrics.

    cache: reuse the result of an identical earlier run (same simc, input and options), see paf.cache.

    work_threads: profileset_work_threads (2-4 measured ~30% faster than 1 on small sims).
    """
    exe = find_simc(simc)
    if exe is None:
        raise SimcError("simc not found: run `paf setup`")
    run_dir.mkdir(parents=True, exist_ok=True)
    inp = run_dir / "input.simc"
    inp.write_text(input_text, encoding="utf-8")
    json_path = run_dir / "report.json"
    args = [str(exe), str(inp), f"json2={json_path}", f"target_error={fmt(target_error)}"]
    if iterations:
        args.append(f"iterations={iterations}")
    if threads:
        args.append(f"threads={threads}")
    if "profileset." in input_text:
        args.append(f"profileset_metric={','.join(metrics)}")
        if work_threads > 1:
            args.append(f"profileset_work_threads={work_threads}")
    if html:
        args.append(f"html={run_dir / 'report.html'}")
    args += extra or []

    key = None
    if cache and not html:
        options = [a for a in args[2:] if not a.startswith("json2=")]
        key = sim_cache.sim_key(exe, input_text, options)
        hit = sim_cache.sim_get(key)
        if hit is not None:
            shutil.copyfile(hit, json_path)
            res = parse_json(json_path)
            res.elapsed = 0.0
            return res

    t0 = time.time()
    with (run_dir / "simc.log").open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
                              cwd=run_dir)
    elapsed = time.time() - t0
    if proc.returncode != 0 or not json_path.is_file():
        tail = (run_dir / "simc.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise SimcError(f"simc failed (exit {proc.returncode}):\n{tail}")
    res = parse_json(json_path)
    res.elapsed = elapsed
    if key:
        sim_cache.sim_put(key, json_path)
    return res
