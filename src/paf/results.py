"""A tool's result as data, next to its runs (<run dir>/result.json): the workshop shows it as a page made for it
(paf.workshop), instead of the text the command prints. One function per tool builds the data from the objects the
command already has."""

from __future__ import annotations

import json
from pathlib import Path


def write(run_dir: Path, kind: str, data: dict) -> None:
    try:
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        (Path(run_dir) / "result.json").write_text(json.dumps({"kind": kind, **data}), encoding="utf-8")
    except OSError:  # the text output stays the result
        pass


def read(run_dir: Path) -> dict | None:
    p = Path(run_dir) / "result.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None


def fight_label(name: str) -> str:
    return {"patchwerk": "Training dummy", "cleave2": "2 targets", "aoe5": "5 targets"}.get(name, "On the boss")


def talents(tc, boss: str, difficulty: str) -> dict:
    main = tc.fights[0] if tc.fights else ""
    rows = []
    for r in tc.rows:
        tot, bossd = r.per_fight.get(main, (None, None))
        rows.append({"label": r.build.label, "players": r.build.count, "rank": r.build.median_rank, "gain": tot,
                     "boss_gain": bossd, "dummy": (r.per_fight.get("patchwerk") or (None,))[0],
                     "take": list(r.add), "drop": list(r.drop), "code": r.build.code or ""})
    return {"boss": boss, "difficulty": difficulty, "error": tc.error, "rows": rows}


def loot(items, weights: dict[str, float], evs, ilvl: int, bosses: list[str]) -> dict:
    ranked = sorted(items, key=lambda i: -i.weighted(weights))
    return {"bosses": bosses, "ilvl": ilvl, "error": max((i.error for i in items), default=0.0),
            "rows": [{"name": i.name, "item_id": i.item_id, "slot": i.slot, "boss": i.boss,
                      "gain": i.weighted(weights)} for i in ranked],
            "ev": [{"boss": b, "ev": ev, "n": n} for b, ev, n in evs]}


def topgear(res, top: int = 8) -> dict:
    weights = {f.name: f.weight for f in res.fights}
    ranked = sorted(res.combos, key=lambda c: -c.weighted(weights))[:top]
    rows = []
    for c in ranked:
        changes = [{"slot": o.fam, "items": [{"name": g.name, "ilvl": g.ilvl, "item_id": g.item_id,
                                               "source": g.source} for g in o.gears()]}
                   for o in c.options.values()]
        rows.append({"gain": c.weighted(weights), "changes": changes,
                     "per": {fight_label(f): v for f, v in c.scores.items()}})
    err = max((e for c in ranked for e in c.errors.values()), default=0.0)
    return {"fights": [fight_label(f.name) for f in res.fights], "error": err, "rows": rows}


def cooldowns(plans, boss: str, difficulty: str, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    out = []
    for p in plans:
        rules = [{"cd": names.get(k, k.replace("use_item:", "").replace("_", " ").title()), "how": r.description}
                 for k, r in p.choice.items() if r.name != "default"]
        out.append({"objective": p.objective, "gain": p.gain, "error": p.error, "rules": rules,
                    "robust": p.robust, "flags": list(p.flags)})
    return {"boss": boss, "difficulty": difficulty, "plans": out}
