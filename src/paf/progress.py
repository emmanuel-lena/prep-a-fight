"""Progress of a prep: its steps, what each one does, how long it takes on this computer, and the findings so far.

The prep prints ``== <step>  [+<seconds since the start>s]``; the app reads the log of the job. Step durations of
finished preps are kept (``<data>/web/step-times.json``, the last ten per step) and their median predicts the next
prep; the very first prep uses typical minutes. The corpus step is predicted from its own pace (kills left x time
per kill so far) plus an announced quota wait.
"""

from __future__ import annotations

import json
import re
import statistics as st
import time

from paf.config import data_dir

# prefix of the step line, label, what it does and why it takes time, typical minutes (first prep)
PREP_STEPS = (
    ("Using the prep pack", "Reuse a shared prep pack",
     "Another player already prepared this boss with your spec today: what the logs give is reused, no download.", 0),
    ("Collecting the corpus", "Download the top players' kills",
     "About 200 kills of the best players of your spec, from Warcraft Logs. Your key allows 3600 points an hour, so "
     "the download is paced; it happens once per boss and is then shared with the other players.", 20),
    ("Collecting who handles", "Who handles each mechanic",
     "Who gets the debuffs and who interrupts, in each of these kills.", 4),
    ("Analyzing the corpus", "Rebuild the typical fight",
     "Duration, phases, add waves and movement, as the top players' kills show them.", 2),
    ("Calibrating the fight", "Calibrate it on the logs",
     "Adjusts the adds so the simulation splits your damage like the top players do.", 1),
    ("Validating the fight", "Check it against the top players' real DPS",
     "Sims a few top players with their own gear on this fight and compares with what they really did: this says "
     "how much to trust the numbers.", 2),
    ("Your raid and the adds", "Your raid and the adds",
     "Reads your raid's log: whether the others cover the adds or you should pad them.", 1),
    ("Simming your character", "Sim your character",
     "Your DPS on this fight, and on a training dummy for comparison.", 1),
    ("Cooldown timelines", "Top players' cooldown timelines",
     "When the top players press their cooldowns.", 1),
    ("Talent builds", "Sim the top players' talent builds",
     "Your character with each talent build of the top players, on this fight.", 3),
    ("Ideal cooldown plan", "Find your best cooldown plan",
     "Tries holding each cooldown for the adds, the burst windows... keeps what beats the default rotation, then "
     "checks it on harder versions of the fight. The longest step: thousands of simulated pulls on your CPU.", 20),
    ("Cooldown plans", "Compare cooldown plans", "Simple cooldown plans, compared on this fight.", 5),
    ("Top Gear", "Best gear from your bags", "Every useful combination of the items in your bags.", 5),
    ("What this boss drops", "What this boss drops for you", "Each drop of this boss, on your character.", 3),
)
OPTIONAL = ("Collecting", "Your raid", "Cooldown plans", "Using the prep pack")
_STEP = re.compile(r"^== (.*?)(?:\s+\[\+(\d+)s\])?\s*$")
_KILL = re.compile(r"^\s+\[(\d+)/(\d+)\]")
_WAIT = re.compile(r"waiting (\d+) min for the reset")


class Clock:
    """Prints the steps of a prep with their time, and keeps their durations for the next predictions."""

    def __init__(self) -> None:
        self.start = time.time()
        self.marks: list[tuple[str, float]] = []

    def step(self, msg: str) -> None:
        now = time.time()
        self.marks.append((msg, now))
        print(f"\n== {msg}  [+{int(now - self.start)}s]", flush=True)

    def save(self) -> None:
        """At the end of a prep: the duration of each step, by its PREP_STEPS prefix."""
        hist = history()
        ends = [t for _, t in self.marks[1:]] + [time.time()]
        for (msg, t0), t1 in zip(self.marks, ends, strict=True):
            prefix = step_of(msg)
            if prefix:
                hist[prefix] = (hist.get(prefix, []) + [round(t1 - t0, 1)])[-10:]
        path = data_dir() / "web" / "step-times.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(hist), encoding="utf-8")


def history() -> dict[str, list[float]]:
    path = data_dir() / "web" / "step-times.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except ValueError:
        return {}


def step_of(msg: str) -> str:
    return next((p for p, *_ in PREP_STEPS if msg.startswith(p)), "")


def _minutes(prefix: str, hist: dict[str, list[float]], default: float) -> float:
    past = hist.get(prefix)
    return st.median(past) / 60 if past else default


def prep_progress(log: str, elapsed: float | None = None) -> tuple[list[tuple[str, str, str]], float]:
    """[(label, why, state)] with state done / now / next, and the minutes left. Steps that a prep skips (the
    corpus already there, no raid set, a pack used...) are not listed. elapsed: seconds since the prep started."""
    steps: list[tuple[str, int | None]] = []
    for line in log.splitlines():
        m = _STEP.match(line)
        if m:
            steps.append((m.group(1), int(m.group(2)) if m.group(2) else None))
    seen = [s for s, _ in steps]
    finished = any(s.startswith("Done") for s in seen)
    idx = {i for i, (prefix, *_) in enumerate(PREP_STEPS) for s in seen if s.startswith(prefix)}
    last = max(idx) if idx else -1
    optional = OPTIONAL + (("Analyzing", "Validating") if any(s.startswith("Using the prep pack") for s in seen)
                           else ())
    hist = history()
    rows, left = [], 0.0
    for i, (prefix, label, why, minutes) in enumerate(PREP_STEPS):
        if i in idx:
            state = "done" if finished or i < last else "now"
            if state == "now" and prefix.startswith("Collecting the corpus"):
                kills = _kills(log)
                label += f" ({kills[-1][0]}/{kills[-1][1]})" if kills else ""
            rows.append((label, why, state))
        elif not finished and i > last and not prefix.startswith(optional):
            rows.append((label, why, "next"))
            left += _minutes(prefix, hist, minutes)
    if last >= 0 and not finished:
        prefix = PREP_STEPS[last][0]
        typical = _minutes(prefix, hist, PREP_STEPS[last][3])
        since = None
        start = next((t for s, t in reversed(steps) if s.startswith(prefix)), None)
        if elapsed is not None and start is not None:
            since = max(0.0, elapsed - start) / 60
        if prefix.startswith("Collecting the corpus"):
            left += _corpus_left(log, since, typical)
        else:
            left += max(typical - since, typical * 0.1) if since is not None else typical / 2
    return rows, left


def _kills(log: str) -> list[tuple[int, int]]:
    """(kills fetched, kills to fetch) of each progress line of the corpus step."""
    part = log[log.rfind("== Collecting the corpus"):] if "== Collecting the corpus" in log else ""
    return [(int(m.group(1)), int(m.group(2))) for m in (_KILL.match(x) for x in part.splitlines()) if m]


def _corpus_left(log: str, since: float | None, typical: float) -> float:
    """Kills left x minutes per kill so far, plus an announced quota wait."""
    kills = _kills(log)
    tail = log.rstrip().splitlines()[-1] if log.strip() else ""
    wait = int(_WAIT.search(tail).group(1)) if _WAIT.search(tail) else 0
    if not kills or since is None:
        return typical + wait
    done, total = kills[-1]
    pace = since / max(done, 1)
    return pace * (total - done) + wait


FINDINGS = (
    (re.compile(r"Downloaded the shared prep pack"), lambda m: "Shared prep pack found: no log download needed."),
    (re.compile(r"(\d+) ranked kills found"), lambda m: f"{m.group(1)} ranked kills of your spec found."),
    (re.compile(r"(\d+) kills, (\d+) add waves / targets, duration (\S+)"),
     lambda m: f"Typical fight rebuilt from {m.group(1)} kills: {m.group(3)}, {m.group(2)} add waves or targets."),
    (re.compile(r"top players: (\d+)% of damage on the boss"),
     lambda m: f"The top players put {m.group(1)}% of their damage on the boss."),
    (re.compile(r"simulated / real DPS of the top players: ([\d.]+)"),
     lambda m: f"The sim gets {float(m.group(1)):.0%} of the top players' real DPS (100% = it matches reality)."),
    (re.compile(r"-> cooldowns and gear for (\w+) damage"), lambda m: f"Your raid: plan for {m.group(1)} damage."),
    (re.compile(r"Cooldowns found: (.*)"), lambda m: f"Your cooldowns: {m.group(1)}."),
)


def findings(log: str) -> list[str]:
    """What the prep has learned so far, in the player's words (last match of each kind)."""
    out: dict[int, str] = {}
    for line in log.splitlines():
        for i, (rx, say) in enumerate(FINDINGS):
            m = rx.search(line)
            if m:
                out[i] = say(m)
    return [out[i] for i in sorted(out)]
