"""The boss in 60 seconds: the in-game Encounter Journal (overview, what each role does, abilities phase by
phase) with what the logs add (when each ability comes, how many players handle it per kill)."""

from __future__ import annotations

import html
import re

from paf import icons
from paf.mechanics import Section, dedupe, encounter_sections, walk

e = html.escape
ROLE_TITLES = {"damage": "Damage Dealers", "healer": "Healers", "tank": "Tank"}
SHOWN_FLAGS = {"tank": "tank", "healer": "healer", "damage": "dps", "interruptible": "interrupt", "deadly": "deadly",
               "mythic": "mythic", "important": "important"}
SHORT = 220  # characters of an ability's description shown before "more"


def bullets(text: str) -> list[str]:
    """The journal's "- a. - b." role summaries as a list."""
    parts = re.split(r"(?:^|\s)-\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _when(times: list[float]) -> str:
    return ", ".join(_mmss(t) for t in times[:5]) + ("…" if len(times) > 5 else "")


def load(encounter_id: int, difficulty: str) -> list[Section]:
    try:
        return dedupe(encounter_sections(encounter_id), difficulty)
    except Exception:  # noqa: BLE001 - the guide is a bonus: no game data, no guide
        return []


def spell_refs(sections: list[Section]) -> dict[str, str]:
    """Ability name -> Wowhead reference, for links and icons."""
    return {s.title: f"spell={s.spell_id}" for _, s in walk(sections) if s.spell_id and s.title}


def summary_html(sections: list[Section], role: str = "damage", full_link: str = "") -> str:
    """The overview and what your role does, from the journal."""
    over = next((s for s in sections if s.kind == "overview"), None)
    if over is None:
        return ""
    mine = next((c for c in over.children if c.title == ROLE_TITLES.get(role)), None)
    others = [c for c in over.children if c is not mine and c.text]
    out = [f"<p>{e(over.text)}</p>" if over.text else ""]
    if mine and mine.text:
        out.append(f"<h3>What you do ({e(mine.title.lower())})</h3><ul>"
                   + "".join(f"<li>{e(b)}</li>" for b in bullets(mine.text)) + "</ul>")
    for c in others:
        out.append(f"<details><summary>{e(c.title)}</summary><ul class='small'>"
                   + "".join(f"<li>{e(b)}</li>" for b in bullets(c.text)) + "</ul></details>")
    if full_link:
        out.append(f'<p class="small"><a href="{e(full_link)}">Every ability, phase by phase &rarr;</a></p>')
    return f'<div class="card guide">{"".join(out)}</div>'


def describe(spell_id: int) -> str:
    """The spell's own description when the journal has none (game variables made readable)."""
    if not spell_id:
        return ""
    try:
        from paf.gamedata import spell_description
        from paf.mechanics import clean_text

        return clean_text(spell_description(spell_id) or "")
    except Exception:  # noqa: BLE001 - a missing description is fine
        return ""


def _ability(s: Section, depth: int, ctx: dict) -> str:
    tags = "".join(f'<span class="pill {"gold" if f in ("deadly", "interruptible") else ""}">{SHOWN_FLAGS[f]}</span>'
                   for f in s.flags if f in SHOWN_FLAGS)
    facts = []
    times = ctx["timings"].get(s.title.lower())
    if times:
        facts.append(f"around {_when(times)}")
    m = ctx["mechanics"].get(s.title.lower())
    if m:
        who = "interrupted" if m.kind == "interrupt" else f"{m.players_per_kill:.0f} players hit per kill"
        facts.append(who + (f", ~{m.cost:g} s of movement for you" if m.cost else ""))
    if s.title.lower() in ctx["burst"]:
        facts.append(f"<b>burst window: the boss takes x{ctx['burst'][s.title.lower()]:g} damage</b>")
    text = s.text or ctx["describe"](s.spell_id)
    body = ""
    if text:
        body = (f"<div class='small'>{e(text)}</div>" if len(text) <= SHORT else
                f"<details class='small'><summary>{e(text[:SHORT])}…</summary>{e(text[SHORT:])}</details>")
    pic = icons.img(ctx["icons"].get(s.title, ""), "small")
    fact = f"<div class='small muted'>{' &middot; '.join(facts)}</div>" if facts else ""
    return (f'<div class="ab" style="margin-left:{min(depth, 3) * 14}px"><div>{pic}<b>{e(s.title)}</b> {tags}</div>'
            f"{fact}{body}</div>")


def abilities_html(sections: list[Section], *, timings: dict[str, list[float]] | None = None,
                   mechanics: list | None = None, burst: dict[str, float] | None = None,
                   icon_map: dict[str, str] | None = None) -> str:
    """Every stage and unit of the journal with its abilities; facts from the logs when known."""
    ctx = {"timings": {k.lower(): v for k, v in (timings or {}).items()},
           "mechanics": {m.name.lower(): m for m in (mechanics or [])},
           "burst": {k.lower(): v for k, v in (burst or {}).items()}, "icons": icon_map or {},
           "describe": describe}
    cards = []
    for top in sections:
        if top.kind == "overview":
            continue
        rows = []
        for depth, s in walk(top.children):
            if s.kind == "ability":
                rows.append(_ability(s, depth, ctx))
            elif s.kind == "creature":
                rows.append(f'<div class="unit" style="margin-left:{min(depth, 3) * 14}px">{e(s.title)}'
                            + (f" <span class='muted small'>{e(s.text[:160])}</span>" if s.text else "") + "</div>")
        head = e(top.title) + "".join(f' <span class="pill">{SHOWN_FLAGS[f]}</span>'
                                       for f in top.flags if f in SHOWN_FLAGS)
        intro = f"<p class='small muted'>{e(top.text[:300])}</p>" if top.text and top.kind != "stage" else ""
        if top.kind == "ability":
            rows.insert(0, _ability(top, 0, ctx))
        cards.append(f'<details class="card stage" {"open" if top.kind == "stage" else ""}><summary><h3>{head}</h3>'
                     f"</summary>{intro}{''.join(rows)}</details>")
    return "".join(cards)


CSS = """
.guide ul{margin:6px 0 10px;padding-left:20px} .guide li{margin:4px 0}
.stage summary{list-style:none;cursor:pointer} .stage summary h3{display:inline;font-size:16px}
.stage summary::before{content:"\\25B8  ";color:var(--muted)} .stage[open] summary::before{content:"\\25BE  "}
.ab{padding:8px 0;border-top:1px solid var(--line)} .ab .pill{font-size:11px;padding:1px 7px;margin-left:4px}
.unit{padding:10px 0 2px;font-weight:700;color:var(--muted);text-transform:uppercase;font-size:12px;
  letter-spacing:.04em}
"""
