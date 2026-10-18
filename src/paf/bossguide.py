"""The boss in 60 seconds: the in-game Encounter Journal (overview, what each role does, abilities phase by
phase) with what the logs add (when each ability comes, how many players handle it per kill)."""

from __future__ import annotations

import html
import re

from paf import icons, theme
from paf.mechanics import Section, dedupe, encounter_sections, walk

e = html.escape
ROLE_TITLES = {"damage": "Damage Dealers", "healer": "Healers", "tank": "Tank"}
SHOWN_FLAGS = {"tank": "tank", "healer": "healer", "damage": "dps", "interruptible": "interrupt", "deadly": "deadly",
               "mythic": "mythic", "important": "important"}


def bullets(text: str) -> list[str]:
    """The journal's "- a. - b." role summaries as a list."""
    parts = re.split(r"(?:^|\s)-\s*", text)
    return [p.strip() for p in parts if p.strip()]


def readable(text: str) -> str:
    """The journal's text without its unresolved game variables: [Name] links become the name, "X Shadow damage"
    reads "Shadow damage", "by X%" reads "by a share", a lost target name ("fixate on the .") reads "a player"."""
    t = re.sub(r"\[([^\]]+)\]", r"\1", text or "")
    t = re.sub(r"\bby X%", "by a share", t)
    t = re.sub(r"\bX% of\b", "a share of", t)
    t = re.sub(r"\bX%", "some", t)
    t = re.sub(r"\bX (yards?|yd)\b", r"a few \1", t)
    t = re.sub(r"\bX (sec|seconds?)\b", r"a few \1", t)
    t = re.sub(r"\b(?:inflicting|deals?|dealing) X\b", lambda m: m.group(0)[:-2], t)
    t = re.sub(r"\bX (\w+ damage)", r"\1", t)
    t = re.sub(r"\bthe \.", "a player.", t)
    return t if t == text else re.sub(r"\s{2,}", " ", t)


def modernize(html: str) -> str:
    """A guide stored by an older prep, as the current builder writes it: nothing folded, the journal's variables as
    words (the sheet is rendered again from the prep's data without its game data)."""
    if not html:
        return html
    h = re.sub(r"<details class='small fold'><summary><span>(.*?)</span></summary></details>",
               r"<div class='small ab-d'>\1</div>", html, flags=re.S)
    h = re.sub(r"<details><summary>([^<]*)</summary><ul class='small'>(.*?)</ul></details>",
               r"<h3 class='other-role'>\1</h3><ul class='small muted'>\2</ul>", h, flags=re.S)
    h = re.sub(r'<details class="card stage" (?:open)?\s*><summary><h3>(.*?)</h3></summary>(.*?)</details>',
               r'<section class="card stage"><h3>\1</h3>\2</section>', h, flags=re.S)
    h = re.sub(r"(<div class=\"unit\" style=\"[^\"]*\">)([^<]*) <span class='muted small clamp'>(.*?)</span></div>",
               r"\1\2</div><p class='small muted unit-d'>\3</p>", h, flags=re.S)
    return readable(h)


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


def ability_roles(sections: list[Section]) -> dict[str, list[str]]:
    """Ability name -> the roles the journal flags it for (tank, healer, damage); none when it flags no role."""
    return {s.title: [f for f in s.flags if f in ("tank", "healer", "damage")] for _, s in walk(sections)
            if s.kind == "ability" and s.title and any(f in ("tank", "healer", "damage") for f in s.flags)}


def role_bullets(sections: list[Section], role: str = "damage") -> list[str]:
    """What the journal tells your role to do, as short points."""
    over = next((s for s in sections if s.kind == "overview"), None)
    mine = next((c for c in over.children if c.title == ROLE_TITLES.get(role)), None) if over else None
    return bullets(mine.text) if mine and mine.text else []


def summary_html(sections: list[Section], role: str = "damage", full_link: str = "") -> str:
    """The overview and what your role does, from the journal."""
    over = next((s for s in sections if s.kind == "overview"), None)
    if over is None:
        return ""
    mine = next((c for c in over.children if c.title == ROLE_TITLES.get(role)), None)
    others = [c for c in over.children if c is not mine and c.text]
    out = [f"<p>{e(readable(over.text))}</p>" if over.text else ""]
    if mine and mine.text:
        out.append(f"<h3>What the journal tells {e(mine.title.lower())}</h3><ul>"
                   + "".join(f"<li>{e(readable(b))}</li>" for b in bullets(mine.text)) + "</ul>")
    for c in others:  # the other roles: shown, smaller (what the raid around you does)
        out.append(f"<h3 class='other-role'>{e(c.title)}</h3><ul class='small muted'>"
                   + "".join(f"<li>{e(readable(b))}</li>" for b in bullets(c.text)) + "</ul>")
    if full_link:
        out.append(f'<p class="small"><a href="{e(full_link)}">Every ability, phase by phase &rarr;</a></p>')
    return f'<div class="guide">{"".join(out)}</div>'


def describe(spell_id: int, locale: str = "") -> str:
    """The spell's own description when the journal has none (game variables made readable); locale: in that
    language (paf.names pairs both to translate the page)."""
    if not spell_id:
        return ""
    try:
        from paf.gamedata import spell_description
        from paf.mechanics import clean_text

        return clean_text(spell_description(spell_id, locale) or "", locale=locale)
    except Exception:  # noqa: BLE001 - a missing description is fine
        return ""


def _ability(s: Section, depth: int, ctx: dict) -> str:
    tags = "".join(f'<span class="pill {"warn" if f in ("deadly", "interruptible") else ""}">{SHOWN_FLAGS[f]}</span>'
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
    text = readable(s.text or ctx["describe"](s.spell_id))
    body = f"<div class='small ab-d'>{e(text)}</div>" if text else ""
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
                rows.append(f'<div class="unit" style="margin-left:{min(depth, 3) * 14}px">{e(s.title)}</div>'
                            + (f"<p class='small muted unit-d' style='margin-left:{min(depth, 3) * 14}px'>"
                               f"{e(readable(s.text))}</p>" if s.text else ""))
        head = e(top.title) + "".join(f' <span class="pill">{SHOWN_FLAGS[f]}</span>'
                                       for f in top.flags if f in SHOWN_FLAGS)
        intro = f"<p class='small muted'>{e(readable(top.text)[:300])}</p>" if top.text and top.kind != "stage" else ""
        if top.kind == "ability":
            rows.insert(0, _ability(top, 0, ctx))
        cards.append(f'<section class="card stage"><h3>{head}</h3>{intro}{"".join(rows)}</section>')
    return "".join(cards)


CSS = theme.style("bossguide")
