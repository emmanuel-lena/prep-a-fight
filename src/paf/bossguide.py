"""The boss in 60 seconds: the in-game Encounter Journal (overview, what each role does, abilities phase by
phase) with what the logs add (when each ability comes, how many players handle it per kill)."""

from __future__ import annotations

import html
import re

from paf import icons, theme
from paf.mechanics import Section, dedupe, encounter_sections, walk
from paf.wowhead import link, spell_ref

e = html.escape
ROLE_TITLES = {"damage": "Damage Dealers", "healer": "Healers", "tank": "Tank"}
SHOWN_FLAGS = {"tank": "tank", "healer": "healer", "damage": "dps", "interruptible": "interrupt", "deadly": "deadly",
               "mythic": "mythic", "important": "important", "magic": "magic", "curse": "curse", "poison": "poison",
               "disease": "disease"}
DISPEL = {"magic", "curse", "poison", "disease"}  # a healer's to dispel: told on a healer's page (review 36)


def bullets(text: str) -> list[str]:
    """The journal's "- a. - b." role summaries as a list."""
    parts = re.split(r"(?:^|\s)-\s*", text)
    return [p.strip() for p in parts if p.strip()]


DIFF_IDS = {"lfr": 17, "normal": 14, "heroic": 15, "mythic": 16}


def readable(text: str, difficulty: str = "heroic") -> str:
    """The journal's text without its unresolved game variables: [Name] links become the name, "X Shadow damage"
    reads "Shadow damage", "by X%" reads "by a share", a lost target name ("fixate on the .") reads "a player"."""
    did = DIFF_IDS.get((difficulty or "heroic").lower(), 15)

    def by_diff(m: re.Match) -> str:  # $?DIFF15|DIFF16[text on those][text otherwise]: the sheet's difficulty
        ids = {int(x) for x in re.findall(r"\d+", m.group(1))}
        return m.group(2) if did in ids else (m.group(3) or "")
    t = re.sub(r"\$\?((?:DIFF\d+\|?)+)\[([^\]]*)\](?:\[([^\]]*)\])?", by_diff, text or "")
    t = re.sub(r"\[([^\]]+)\]", r"\1", t)
    for other in [d for d in ("Heroic", "Mythic") if not _applies(d, difficulty)]:  # another difficulty's sentence
        t = re.sub(rf"(?:^|(?<=[.!?] ))On {other} difficulty,.*?[.!?](?=\s|$)\s*", "", t)  # "every 1.5 sec."
    t = re.sub(r" by X%", "", t)
    t = re.sub(r"\bX% of\b", "a share of", t)
    t = re.sub(r"\bX%", "some", t)
    t = re.sub(r"\bX (yards?|yd)\b", r"a few \1", t)
    t = re.sub(r"\bX (sec|seconds?)\b", r"a few \1", t)
    t = re.sub(r"\b(?:inflicting|deals?|dealing) X\b", lambda m: m.group(0)[:-2], t)
    t = re.sub(r"\bX (\w+ damage)", r"\1", t)
    t = re.sub(r"\bthe next X healing\b", "an amount of incoming healing", t)
    t = re.sub(r"\b(healing|absorbing) X\b", r"\1 an amount", t)
    t = re.sub(r"\bX or fewer\b", "only a few", t)
    t = re.sub(r"\bX or more\b", "enough", t)
    t = re.sub(r"\bthe \.", "a player.", t)
    return t if t == text else re.sub(r"\s{2,}", " ", t)


def _applies(level: str, difficulty: str) -> bool:
    """A journal sentence "On Heroic difficulty, ..." applies to heroic and mythic; "On Mythic ..." to mythic."""
    order = ("lfr", "normal", "heroic", "mythic")
    d = (difficulty or "heroic").lower()
    return order.index(d) >= order.index(level.lower()) if d in order else True


def _blocks(html: str, start: int) -> list[tuple[int, int, int]]:
    """(start, end, indent px) of each ability or unit row from `start`, by balancing the divs."""
    out = []
    for m in re.finditer(r'<div class="(ab|unit)" style="margin-left:(\d+)px">', html[start:]):
        s = start + m.start()
        if out and s < out[-1][1]:
            continue  # inside the previous row
        depth, i = 0, s
        for t in re.finditer(r"<div\b|</div>", html[s:]):
            depth += 1 if t.group(0) == "<div" else -1
            if depth == 0:
                i = s + t.end()
                break
        end = i
        if m.group(1) == "unit":  # a unit's description follows it
            d = re.match(r"\s*<p class='small muted unit-d'[^>]*>.*?</p>", html[end:], re.S)
            if d:
                end += d.end()
        out.append((s, end, int(m.group(2))))
    return out


def grouped(html: str) -> str:
    """Each top-level ability (or unit) with its children in one block, so two columns never split a parent from
    the abilities under it."""
    rows = _blocks(html, 0)
    if not rows:
        return html
    out, pos, i = [], 0, 0
    while i < len(rows):
        s, e0, ind = rows[i]
        j = i + 1
        while j < len(rows) and rows[j][2] > ind and rows[j][0] - rows[j - 1][1] < 40:
            j += 1
        out.append(html[pos:s] + "<div class='abg'>" + html[s:rows[j - 1][1]] + "</div>")
        pos = rows[j - 1][1]
        i = j
    return "".join(out) + html[pos:]


def modernize(html: str, difficulty: str = "heroic") -> str:
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
    h = re.sub(r'class="pill gold">(deadly|interrupt)', r'class="pill warn">\1', h)
    if "class='abg'" not in h:
        h = grouped(h)
    # an ability card titled by the ability it opens with: the title once (the ability row carries it)
    h = re.sub(r'<section class="card stage"><h3>([^<]+?)\s*(?:<span[^>]*>[^<]*</span>\s*)*</h3>'
               r'(\s*<div class=\'abg\'><div class="ab" style="margin-left:0px"><div>'
               r'(?:<img[^>]*>|<span class="ics[^"]*"></span>)?<b>\1</b>)',
               r'<section class="card stage">\2', h)
    h = re.sub(r"<h3>What you do \(([^)]*)\)</h3>", r"<h3>What the journal tells \1</h3>", h)
    return readable(h, difficulty)


def _mentioned_in_summary(sections: list[Section], role: str) -> set[str]:
    """Every ability the role's summary names, its subject or in passing ("…protected by Sanguineous Fortitude")."""
    said = " ".join(role_bullets(sections, role)).lower()
    return {s.title for _, s in walk(sections) if s.kind == "ability" and s.title and s.title.lower() in said}


def _named_in_summary(sections: list[Section], role: str) -> set[str]:
    """The abilities the journal's summary for this role names ("Imbibe inflicts heavy damage…" for the healers)."""
    lines = [b.lower().lstrip() for b in role_bullets(sections, role)]  # the line's subject only, not a name in
    # passing (round 39: "…if too many souls enter the Soulcoil Well" marked the Well)
    return {s.title for _, s in walk(sections) if s.kind == "ability" and s.title
            and any(x.startswith(s.title.lower()) for x in lines)}


def _short(stage: str) -> str:
    """"Stage One: Soulcoiler Initiation" -> "Stage One": its name once in its heading (fresh app review 6)."""
    return stage.split(":", 1)[0].strip() or stage


def _mmss(t: float) -> str:
    from paf.plan import mmss  # rounded, as the page's header and plan box (app round 14: 0:52 under 0:53)

    return mmss(t)


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
    mine = next((c for c in over.children if _same_role(c.title, role)), None) if over else None
    return bullets(mine.text) if mine and mine.text else []


def _same_role(title: str, role: str) -> bool:
    """A journal's role heading: "Tank" or "Tanks", "Healer" or "Healers" (Nek'zali writes Tanks, Nymrissa Healer)."""
    want = ROLE_TITLES.get(role, "")
    return bool(want) and title.lower().rstrip("s") == want.lower().rstrip("s")


ROLE_AS = {"damage": "a damage dealer", "healer": "a healer", "tank": "a tank"}


def summary_html(sections: list[Section], role: str = "damage", full_link: str = "") -> str:
    """The overview and what your role does, from the journal."""
    over = next((s for s in sections if s.kind == "overview"), None)
    if over is None:
        return ""
    mine = next((c for c in over.children if _same_role(c.title, role)), None)
    others = [c for c in over.children if c is not mine and c.text]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", readable(over.text)) if over.text else []
    out = []  # your part first, then the story of the fight
    if mine and mine.text:
        out.append(f"<h3>For you, as {ROLE_AS.get(role, 'a player')}</h3><ul>"
                   + "".join(f"<li>{e(readable(b))}</li>" for b in bullets(mine.text)) + "</ul>")
    if sentences:
        out.append("<h3>The fight</h3><div class='over'>" + "".join(f"<p>{e(x)}</p>" for x in sentences) + "</div>")
    # the other roles: none here; the ability list names theirs from the journal's flags, one source (round 37: two
    # healer lists that disagreed)
    del others
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
    raid = "raid damage" in ctx["also"].get(s.title, "")  # measured as a big raid hit: its tank tag says the raid
    dispel = ctx["role"] == "healer" and bool(DISPEL & set(s.flags))  # a healer's dispel keeps its words
    m = ctx["mechanics"].get(s.title.lower())
    can_be_you = m is not None and m.kind != "interrupt" and m.players_per_kill > 0  # it lands on players: you too
    # named by the role's summary (its subject or in passing) and not kept for another reason: its words are the
    # summary's, so a marker says where, never the words twice, never a bare name (rounds 37-40)
    summed = (s.title in ctx["mentioned"] and s.title not in ctx["also"] and not dispel
              and (s.title in ctx["named"] or not (can_be_you or ctx["role"] in s.flags)))  # in passing, its own
    # words say what the line does not (round 41: Toxic Vapor's stacking damage, a healer's)
    tags = "".join(f'<span class="pill {"warn" if f in ("deadly", "interruptible") else ""}">{SHOWN_FLAGS[f]}'  # too
                   + (" &middot; raid too" if f == "tank" and raid else "") + "</span>"  # (round 112: Possession
                   for f in s.flags if f in SHOWN_FLAGS  # Barrage tagged "tank", three of the four raid hits)
                   and not (summed and f == ctx["role"]))  # one marker, not the role's flag too (round 39)
    facts = []
    times = ctx["timings"].get(s.title.lower())
    if times:
        facts.append(f"around {_when(times)}")
    if m:
        who = "interrupted" if m.kind == "interrupt" else f"{m.players_per_kill:.0f} players hit per kill"
        facts.append(who + (f", ~{m.cost:g} s of movement for you" if m.cost else ""))
    if s.title in ctx["also"]:
        facts.append(e(ctx["also"][s.title]))
    if ctx["shares"].get(s.title):  # its share of the raid's damage taken, as the bars above (fresh heal review)
        facts.append(f"{ctx['shares'][s.title]:.0%} of the raid&#39;s damage")
    if s.title.lower() in ctx["burst"]:
        facts.append(f"<b>burst window: the boss takes x{ctx['burst'][s.title.lower()]:g} damage</b>")
    # the journal's words only on what the journal flags for your role (or hits you too); the rest: its name, icon,
    # tags and times, the name a Wowhead link to read it (the owner, 2026-10-24: less prose)
    told = (not ctx["role"] or ctx["role"] in s.flags or s.title in ctx["also"] or can_be_you
            or (ctx["role"] == "healer" and bool(DISPEL & set(s.flags))))  # a healer's dispels (review 36: Essence
    # Rend, the boss tab's headline, a bare name); what the role's summary names: a tag, its words being the
    # summary's (round 37: the same sentences in both columns)
    if summed:  # its numbers stay
        told = False
        tags += ('<span class="pill sum" title="its words: in the journal&#39;s lines for your role, on this page">'
                 "&uarr; for you</span>")
    text = readable(s.text, ctx["difficulty"]).strip() if s.text and told else ""
    if not text and told:  # no journal text, or only another difficulty's sentence: the spell's own description
        text = readable(ctx["describe"](s.spell_id), ctx["difficulty"])
    body = f"<div class='small ab-d'>{e(text)}</div>" if text else ""
    pic = icons.img(ctx["icons"].get(s.title, ""), "small")
    fact = f"<div class='small muted'>{' &middot; '.join(facts)}</div>" if facts else ""
    name = link(s.title, spell_ref(s.spell_id) if s.spell_id else None)
    return (f'<div class="ab" style="margin-left:{min(depth, 1) * 14}px"><div>{pic}<b>{name}</b> {tags}</div>'
            f"{fact}{body}</div>")


ROLE_OTHERS = {"tank": "the tanks", "healer": "the healers", "damage": "the damage dealers"}


def abilities_html(sections: list[Section], *, timings: dict[str, list[float]] | None = None,
                   mechanics: list | None = None, burst: dict[str, float] | None = None,
                   icon_map: dict[str, str] | None = None, role: str | None = None,
                   difficulty: str = "heroic", also: dict[str, str] | None = None,
                   phases: list[tuple[str, float]] | None = None, shares: dict[str, float] | None = None) -> str:
    """Every stage and unit of the journal with its abilities; facts from the logs when known. phases: the logs'
    phase names and median starts, said in the stage headings they match ("Stage Two" for "Stage Two: Uncoiling")."""
    def start(title: str) -> str:
        base = title.split(":")[0].strip().lower()
        t = next((t for n, t in phases or [] if n.split(":")[0].strip().lower() == base), None)
        return "" if t is None else (" <span class='muted small'>from the pull</span>" if t <= 1
                                     else f" <span class='muted small'>from about {_mmss(t)}</span>")
    ctx = {"timings": {k.lower(): v for k, v in (timings or {}).items()},
           "mechanics": {m.name.lower(): m for m in (mechanics or [])},
           "burst": {k.lower(): v for k, v in (burst or {}).items()}, "icons": icon_map or {},
           "describe": describe, "difficulty": difficulty, "also": also or {}, "role": role,
           "named": _named_in_summary(sections, role) if role else set(),
           "mentioned": _mentioned_in_summary(sections, role) if role else set(), "shares": shares or {}}
    def key(s: Section) -> tuple:
        return s.kind, s.title, readable(s.text), tuple(s.flags)

    def again(s: Section) -> bool:  # told word for word in an earlier stage, and everything under it too
        return key(s) in seen and all(again(c) for c in s.children)

    seen: dict[tuple, str] = {}  # what a stage repeats from an earlier one: named, not described twice
    told_text: dict[tuple, tuple[str, set]] = {}  # (kind, title, text) -> (stage, flags): the same words, retagged
    cards = []
    for top in sections:
        if top.kind == "overview":
            continue
        rows, repeated, others, skip, under, unit_said = [], {}, {}, None, None, False
        for depth, s in walk(top.children):
            if skip is not None and depth > skip:  # under an ability of another role: named with it
                continue
            skip = None
            # an ability whose only text is another difficulty's sentence keeps its name: it exists here too
            # (Vashnik heroic: Exploding Infection, "On Mythic difficulty, this gains a stack", is dispelled 4 times
            # a kill in the top heroic kills); a mythic-only ability is left out by its flag (dedupe)
            mine = [f for f in s.flags if f in ROLE_OTHERS]
            if role and s.kind == "ability" and mine and role not in mine and s.title not in (also or {}):
                # another role's job: named, not told (unless it hits you too: also)
                others.setdefault(mine[0], []).append(s.title)
                skip = depth
                continue
            if s.kind in ("ability", "creature") and again(s):
                if s.kind == "ability":
                    repeated.setdefault(seen[key(s)], []).append(s.title)
                continue
            prior = None
            if s.kind in ("ability", "creature"):
                seen.setdefault(key(s), top.title)
                prior = told_text.setdefault((s.kind, s.title, readable(s.text)), (top.title, set(s.flags)))
                prior = prior if prior[0] != top.title else None
            if under is not None and depth <= under:
                under = None
            quiet = under is not None  # under a unit already "as in" its stage: said once (round 38)
            if s.kind == "ability" and key(s) in seen and seen[key(s)] != top.title:  # told before: its name only,
                pic = icons.img(ctx["icons"].get(s.title, ""), "small")           # for what is new under it
                where = "" if quiet else f' <span class="muted small">as in {e(_short(seen[key(s)]))}</span>'
                rows.append(f'<div class="ab" style="margin-left:{min(depth, 1) * 14}px"><div>{pic}<b>{e(s.title)}</b>'
                            f"{where}</div></div>")
            elif s.kind == "ability" and prior:  # the same words as before, a new tag (Vessel of Awakening: deadly)
                was = prior
                new = [SHOWN_FLAGS[f] for f in s.flags if f in SHOWN_FLAGS and f not in was[1]]
                pic = icons.img(ctx["icons"].get(s.title, ""), "small")
                pills = " ".join(  # the pills every other ability gets (app round 11)
                    f'<span class="pill {"warn" if x in ("deadly", "interrupt") else ""}">{e(x)}</span>' for x in new)
                lead = "" if quiet else f"as in {e(_short(was[0]))}, "
                what = f"{lead}now</span> {pills}" if new else f"{lead}changed</span>"
                rows.append(f'<div class="ab" style="margin-left:{min(depth, 1) * 14}px"><div>{pic}<b>{e(s.title)}</b>'
                            f' <span class="muted small">{what}</div></div>')
            elif s.kind == "ability":
                rows.append(_ability(s, depth, ctx))
            elif s.kind == "creature":  # a unit told before: its name, then only what changed under it
                told = seen.get(key(s), top.title) != top.title
                under = depth if told else None  # its rows need not say "as in" again
                unit_said = unit_said or told
                ts = None if told else ctx["timings"].get(s.title.lower())  # when it comes, at its first stage
                at = f" <span class='muted small'>around {_when(ts)}</span>" if ts else ""  # only (app rounds 13-14:
                # the adds had no time, then the intermission's repeat gave the Stage One spawns)
                rows.append(f'<div class="unit" style="margin-left:{min(depth, 1) * 14}px">{e(s.title)}{at}</div>'
                            + (f"<p class='small muted unit-d' style='margin-left:{min(depth, 1) * 14}px'>"
                               + (f"As in {e(_short(seen[key(s)]))}; what changes:" if told
                                  else e(readable(s.text, difficulty)))
                               + "</p>" if s.text and (told or not role) else ""))  # a unit's story: not told
                # on a role's page (the owner, 2026-10-24); its abilities below say what it does
        head = e(top.title) + "".join(f' <span class="pill">{SHOWN_FLAGS[f]}</span>'
                                       for f in top.flags if f in SHOWN_FLAGS)
        if top.kind == "stage" and phases:  # when it starts, from the logs (round 79: no time in the headings)
            head += start(top.title)
        intro = (f"<p class='small muted'>{e(readable(top.text)[:300])}</p>"
                 if top.text and top.kind != "stage" and not role else "")
        if top.kind == "ability":
            rows.insert(0, _ability(top, 0, ctx))
        title = "" if top.kind == "ability" else f"<h3>{head}</h3>"  # an ability's card: its row names it
        body = "".join(rows)

        def chips(names: list[str], body: str = body) -> str:  # with icons, never counted (r. 43: the 3:50 hit's
            return "".join(f"<span class='ab-chip'>{icons.img(ctx['icons'].get(n, ''), 'small')}{e(n)}</span>"
                           for n in sorted(dict.fromkeys(names))  # hidden in "8"); sorted (r. 46); one with a row
                           if not re.search(rf">{re.escape(e(n))}(?:</a>)?</b>", body))  # is not a chip (round 44)
        notes = "".join(  # not `also`: the parameter (review 36: lost from stage 2)
            "<p class='small muted also'>"
            + ("Also unchanged: " if unit_said and len(repeated) == 1 else f"As in {e(_short(where))}: ")  # its unit
            + chips(names) + "</p>"  # said the stage (round 39)
            for where, names in repeated.items() if chips(names))
        notes += "".join(f"<p class='small muted also'>For {ROLE_OTHERS[r]}: {chips(names)}</p>"  # chips too (r. 45)
                         for r, names in others.items() if chips(names))
        cards.append(f'<section class="stage">{title}{intro}{grouped(body)}{notes}</section>')
    return "".join(cards)


CSS = theme.style("bossguide")
