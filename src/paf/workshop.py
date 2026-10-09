"""The workshop (the "Tools" page): each tool answers one question a player asks, with only the choices that matter
(the boss, the difficulty, the goal...), the other options folded. The prep of a boss already runs them all: here a
player runs one again, to dig further. Every command stays reachable, raw, under "For the curious" (paf.webtools).

A tool runs as a job (paf.web.JOBS) and its page shows the answer, not the whole log: the result block of the output
(paf.workshop.result_block), the reports it wrote, then the log, folded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape as e

from paf import settings, theme


@dataclass(frozen=True)
class Tool:
    cmd: str
    title: str
    question: str
    icon: str
    group: str
    minutes: str  # typical run time on a desktop
    # boss (required) | boss? (optional: every boss) | boss~ (optional: a training dummy) | difficulty | goal | goal3 | raid
    fields: tuple[str, ...]
    gives: str  # what the player gets
    needs_prep: bool = True  # reads the data of a prep of this boss (its corpus)


GROUPS = (("gear", "Your gear and talents"), ("cds", "Your cooldowns"), ("raid", "Your raid"), ("boss", "The boss"))

TOOLS: tuple[Tool, ...] = (
    Tool("topgear", "Best gear from your bags", "Which combination of your items does the most damage on this boss?",
         "inv_misc_bag_10", "gear", "5-15", ("boss~", "difficulty", "goal"),
         "Your best sets, each with its gain in % over what you wear.", needs_prep=False),
    Tool("droptimizer", "What a boss drops for you", "Which items of this boss, or of the whole raid, are real "
         "upgrades for you?", "inv_misc_coin_02", "gear", "5-10", ("boss?", "difficulty", "goal"),
         "Every item worth it for you, with its gain in %, best first.", needs_prep=False),
    Tool("bonusroll", "Where to use your bonus rolls", "Which boss gives you the most, on average, when you spend "
         "a bonus roll on it?", "inv_misc_coin_17", "gear", "5-10", ("difficulty", "goal"),
         "Every boss of the raid ranked by what a bonus roll brings you, with its best item.", needs_prep=False),
    Tool("talents", "The top players' talents, on you", "Which talent build of the best players does the most "
         "damage with your character, on this fight?", "inv_misc_book_11", "gear", "3-6", ("boss", "difficulty"),
         "The builds compared on your character, with their gain and the talents to change."),
    Tool("optimize", "When to press your cooldowns", "Hold a cooldown for the adds or press it on cooldown: what "
         "does the most damage on this fight?", "spell_holy_borrowedtime", "cds", "20-40",
         ("boss", "difficulty", "goal3"), "The best cooldown plan per goal, and the pull played with it."),
    Tool("timeline", "The top players' cooldowns, minute by minute", "When do the best players of your spec press "
         "each cooldown on this boss?", "inv_misc_pocketwatch_01", "cds", "1", ("boss", "difficulty"),
         "A page with the cooldown timeline of each top player, side by side."),
    Tool("raid", "Pad the adds or stay on the boss?", "From your raid's composition and DPS: do the others already "
         "cover the adds?", "inv_misc_groupneedmore", "raid", "1-3", ("boss", "difficulty", "raid"),
         "The verdict for each add type, and why."),
    Tool("review", "Who does what in your raid", "Who stays on the boss, who pads, who should go on a secondary "
         "target? Your raid's pull next to the top raids.", "inv_misc_spyglass_03", "raid", "1",
         ("boss", "difficulty", "raid"), "Each player's damage on the boss and on each target, next to the top "
         "players of their spec, and what to change for more boss damage."),
    Tool("comp", "Who hits what in your raid", "The adds you cannot skip: does the whole raid hit them, or a few "
         "players? Who, in your raid?", "achievement_guildperk_everybodysfriend", "raid", "1",
         ("boss", "difficulty", "raid"), "Each add with who takes it in the top raids and in your pull, and who "
         "should, in their own spec."),
    Tool("wipe", "Your best pull, in detail", "What did the deaths and the damage off the boss cost, and when would "
         "the boss have died without them?", "spell_shadow_soulleech_3", "raid", "1", ("boss", "difficulty", "raid"),
         "The boss's health over your best pull, as played and without the deaths, and what each death cost."),
    Tool("night", "Your raid night, pull by pull", "Who died, who used a healthstone or a health potion, who pressed "
         "a damage potion? Tonight's log, live too.", "inv_stone_04", "raid", "1", ("raid",),
         "Each player over the night, then each pull: deaths, healthstones, potions.", needs_prep=False),
    Tool("diff", "Two pulls side by side", "What went better in one pull than in another, for the raid and for "
         "you?", "inv_misc_spyglass_02", "raid", "1-2", ("boss", "difficulty", "raid"),
         "Both pulls' boss health, deaths, damage per target, and your damage, casts and buffs in each.",
         needs_prep=False),
    Tool("rotation", "Your rotation, spell by spell", "In single target, cleave and AoE: do you cast what the best "
         "rotation casts, with your gear and talents?", "spell_holy_borrowedtime", "raid", "1-2",
         ("boss", "difficulty", "raid"), "The points to work on, your share of each spell next to the rotation's, "
         "your DoTs and your cooldowns.", needs_prep=False),
    Tool("mechanics", "The boss's mechanics", "Every ability from the Encounter Journal, by role: what concerns you?",
         "inv_misc_book_09", "boss", "1", ("boss", "difficulty"),
         "The boss's abilities by role, and who handles what in the top kills.", needs_prep=False),
    Tool("assigns", "Assignments you can take", "Which mechanics can you be assigned to, when do they come, and "
         "what do they cost you?", "ability_warrior_rallyingcry", "boss", "1", ("boss", "difficulty"),
         "Each assignable mechanic with its timings and the damage it costs you."),
)
BY_CMD = {t.cmd: t for t in TOOLS}
CURATED_FIELDS = {"boss", "difficulty", "objective", "raid", "fight"}  # set by the curated form, not under "options"


def _icon(name: str, cls: str = "") -> str:
    from paf import icons

    return icons.img(name, "large", cls)


def _character() -> str:
    from paf import characters, icons

    c = next((c for c in characters.all_characters() if c.current), None)
    if c is None:
        return "<a class='ws-me none' href='/characters'>Add your character first &rarr;</a>"
    ic = icons.img(icons.CLASS_ICON.format(cls=c.class_name.lower()), "medium", "ws-me-ic")
    return (f"<a class='ws-me' href='/characters' title='Change'>{ic}<span><b>{e(c.name)}</b>"
            f"<small>{e(c.spec.title())} {e(c.class_name.title())}</small></span></a>")


def index() -> str:
    groups = ""
    for gid, title in GROUPS:
        cards = "".join(
            f"<a class='ws-card' href='/tool/{t.cmd}'>{_icon(t.icon, 'ws-ic')}<span class='ws-txt'><b>{e(t.title)}</b>"
            f"<span class='ws-q'>{e(t.question)}</span><span class='ws-meta'><span class='pill'>~{e(t.minutes)} min</span>"
            + ("<span class='pill gold'>after a prep</span>" if t.needs_prep else "") + "</span></span></a>"
            for t in TOOLS if t.group == gid)
        groups += f"<h2>{e(title)}</h2><div class='ws-cards'>{cards}</div>"
    from paf.webtools import raw_index

    return (f"<div class='ws'><header class='ws-head'><div><h1>Tools</h1><p class='lead'>Each tool answers one "
            f"question. The prep of a boss already runs them all: here, run one again to dig further.</p></div>"
            f"{_character()}</header>{groups}<details class='ws-raw'><summary>For the curious: every command, with all "
            f"its options</summary>{raw_index()}</details></div>{CSS}")


def _boss_select(encounters: list, optional: str = "") -> str:
    first = f"<option value=''>{e(optional)}</option>" if optional else ""
    opts = "".join(f"<option value='{x.id}'>{e(x.name)}</option>" for x in encounters)
    return f"<label class='ws-f'><span>Boss</span><select name='boss' class='big'>{first}{opts}</select></label>"


def _segs(name: str, label: str, options: list[tuple[str, str, str]], checked: str) -> str:
    segs = "".join(f"<label class='seg' title='{e(hint)}'><input type='radio' name='{name}' value='{e(v)}'"
                   f"{' checked' if v == checked else ''}><span>{e(text)}</span></label>" for v, text, hint in options)
    return f"<div class='ws-f'><span>{e(label)}</span><div class='segs'>{segs}</div></div>"


def _field(kind: str, encounters: list) -> str:
    from paf.web import DIFF_LABELS

    if kind in ("boss", "boss?", "boss~"):
        return _boss_select(encounters, {"boss?": "Every boss of the raid",
                                          "boss~": "A training dummy (no boss)"}.get(kind, ""))
    if kind == "difficulty":
        return _segs("difficulty", "Difficulty", [(d, DIFF_LABELS.get(d, d), "") for d in settings.DIFFICULTIES
                                                  if d != "lfr"], settings.get("difficulty"))
    if kind == "goal":
        return _segs("objective", "Your goal", [("boss", "Boss damage", "progress: everyone on the boss"),
                                                ("total", "Total damage", "pad the adds, or parse")], "boss")
    if kind == "goal3":
        return _segs("objective", "Your goal", [("all", "Both", "a plan for each"),
                                                ("boss", "Boss damage", ""), ("total", "Total damage", "")], "all")
    if kind == "raid":
        g = settings.get("guild")
        hint = f"Empty: the latest public log of {g}." if g else "Or set your guild in Settings."
        return (f"<label class='ws-f'><span>Your raid's log</span><input name='raid' placeholder='https://www.warcraftlogs"
                f".com/reports/...'><small class='muted'>{e(hint)}</small></label>")
    return ""


def tool_page(cmd: str, encounters: list) -> str | None:
    t = BY_CMD.get(cmd)
    if t is None:
        return None
    from paf.webtools import advanced_fields

    fields = "".join(_field(k, encounters) for k in t.fields)
    adv = advanced_fields(cmd, encounters, CURATED_FIELDS)
    note = ("<p class='ws-note'>It reads the data of a prep of this boss: prepare the boss first if you have not "
            "(Home, then the boss).</p>" if t.needs_prep else "")
    return (f"<div class='ws'><p class='small'><a href='/tools'>&larr; Tools</a></p>"
            f"<header class='ws-tool'>{_icon(t.icon, 'ws-big')}<div><h1>{e(t.title)}</h1><p class='lead'>{e(t.question)}"
            f"</p></div>{_character()}</header>"
            f"<form method='post' action='/tool/{e(cmd)}' class='ws-form'><input type='hidden' name='_curated' value='1'>"
            f"{fields}<p class='ws-gives'><b>You get:</b> {e(t.gives)}</p>{note}"
            + (f"<details class='ws-adv'><summary>More options</summary>{adv}</details>" if adv else "")
            + f"<div class='ws-go'><button class='btn go'>Run it &rarr;</button><span class='muted small'>About "
            f"{e(t.minutes)} min, on your computer. You can leave the page: it keeps running.</span></div></form></div>{CSS}")


def args(cmd: str, form: dict[str, list[str]]) -> list[str] | None:
    """The command line of a submitted workshop form: the curated fields, then the other options set."""
    t = BY_CMD.get(cmd)
    if t is None:
        return None
    from paf.webtools import tool_args

    def one(k: str) -> str:
        return (form.get(k) or [""])[0].strip()

    out = [cmd]
    boss, diff = one("boss"), one("difficulty")
    if "boss" in t.fields:
        if not boss:
            return None
        out.append(boss)
    elif ("boss?" in t.fields or "boss~" in t.fields) and boss:
        out += ["--boss", boss] + (["--fight", boss] if cmd == "droptimizer" else [])
    if diff:
        out += ["--difficulty", diff]
    if one("objective"):
        out += ["--objective", one("objective")]
    if one("raid"):
        out += ["--raid", one("raid")]
    rest = tool_args(cmd, {k: v for k, v in form.items() if k not in CURATED_FIELDS and k != "_curated"}) or [cmd]
    return out + [a for a in rest[1:] if a not in out[1:]]  # the folded options set by the player


# --- a tool's page while it runs and once done -------------------------------------------------------------------------

_PROGRESS = re.compile(r"^\s*(\[\d+/\d+\]|==|Running|Collecting|Fetching|  quota|  Warcraft Logs quota|simc |\$ )")


_NOISE = re.compile(r"^\s*(Runs:|Saved:|Report:|Prep sheet:)")
_NOTE = re.compile(r"^\s*(Statistical error|Items are simmed|Expected value|note:)", re.I)


def result_block(log: str) -> str:
    """The answer in a tool's output: its last lines once the progress lines and the file paths are left out (blank
    lines kept: they separate the tables)."""
    lines = [x for x in log.rstrip().splitlines() if not _PROGRESS.match(x) and not _NOISE.match(x)]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines[-70:]).strip("\n")


def _cells(line: str) -> list[str]:
    return [c for c in re.split(r"\s{2,}", line.strip()) if c]


def render_result(block: str) -> str:
    """The answer as a page: tables of the output as tables (gains in green, losses in red), "name: details" lines
    as a list, technical notes small."""
    html, notes = [], []
    for para in re.split(r"\n\s*\n", block):
        rows = [x for x in para.splitlines() if x.strip()]
        if not rows:
            continue
        if all(_NOTE.match(r) for r in rows):
            notes += rows
            continue
        tabular = [r for r in rows if len(_cells(r)) >= 3]
        if len(rows) >= 2 and len(tabular) >= max(2, len(rows) - 1):
            head = rows[0] if not re.search(r"[+-]\d+(\.\d+)?%", rows[0]) else ""
            body = rows[1:] if head else rows
            th = "".join(f"<th>{e(c)}</th>" for c in _cells(head)) if head else ""
            trs = "".join("<tr>" + "".join(f"<td>{_colour(c)}</td>" for c in _cells(r)) + "</tr>" for r in body
                          if len(_cells(r)) >= 2)
            html.append(f"<div class='ws-table'><table>{f'<thead><tr>{th}</tr></thead>' if th else ''}"
                        f"<tbody>{trs}</tbody></table></div>")
            continue
        intro = [r for r in rows if not r.startswith("  ")]
        items = [r.strip() for r in rows if r.startswith("  ")]
        html += [f"<p class='ws-p'>{_colour(r.strip())}</p>" for r in intro]
        if items:
            html.append("<ul class='ws-list'>" + "".join(f"<li>{_colour(i)}</li>" for i in items) + "</ul>")
    if notes:
        html.append("<p class='ws-fine'>" + "<br>".join(_colour(n.strip()) for n in notes) + "</p>")
    return "".join(html)


def _colour(text: str) -> str:
    """Gains in green, losses in red, in an escaped block."""
    out = e(text)
    out = re.sub(r"(?<![\w.])\+\d+(?:\.\d+)?%", lambda m: f"<b class='up'>{m.group(0)}</b>", out)
    return re.sub(r"(?<![\w.])-\d+(?:\.\d+)?%", lambda m: f"<b class='down'>{m.group(0)}</b>", out)


def job_page(jid: str, job: dict, log: str, elapsed: int, reports: list[str]) -> str | None:
    """The page of a workshop tool's run; None for a raw command (the plain page)."""
    t = BY_CMD.get(job["args"][0]) if job.get("args") else None
    if t is None:
        return None
    status = job["status"]
    head = (f"<header class='ws-tool'>{_icon(t.icon, 'ws-big')}<div><h1>{e(t.title)}</h1><p class='lead'>"
            f"{e(t.question)}</p></div></header>")
    if status == "running":
        from paf import results, workshop_views

        rd = workshop_views.run_dir(log)  # a tool that writes its result as it goes (a live log): shown so far
        data = results.read(rd) if rd else None
        partial = workshop_views.render(data) if data else None
        if partial:
            return (f"<div class='ws'>{head}<div class='ws-run'><span class='pl-spin'></span><div><b>Live</b> "
                    f"<span class='muted'>&middot; updated every 90 s, this page every 5 s</span></div></div>"
                    f"<div class='ws-answer'>{partial}</div></div>{CSS}{workshop_views.CSS}")
        tail = "\n".join(log.rstrip().splitlines()[-12:])
        return (f"<div class='ws'>{head}<div class='ws-run'><span class='pl-spin'></span><div><b>Working&hellip;</b> "
                f"<span id='el' data-start='{job['started']:.0f}'>{elapsed // 60} min {elapsed % 60:02d} s</span> "
                f"<span class='muted'>(about {e(t.minutes)} min)</span><p class='small muted'>You can leave this page: "
                f"it keeps running, and its result stays here.</p></div></div>"
                f"<pre class='ws-tail'>{e(tail)}</pre></div>{CSS}")
    ok = status == "done"
    from paf import results, workshop_views

    rd = workshop_views.run_dir(log)
    data = results.read(rd) if (ok and rd) else None
    view = workshop_views.render(data) if data else None
    if view:  # a page made for this result
        again = f"<div class='ws-go'><a class='btn ghost' href='/tool/{e(t.cmd)}'>Run it again</a></div>"
        return (f"<div class='ws'>{head}<div class='ws-answer'>{view}</div>{again}<details class='card'><summary>"
                f"The whole log</summary><pre class='log'>{e(log[-20000:])}</pre></details></div>{CSS}"
                f"{workshop_views.CSS}")
    links = "".join(f"<a class='btn go' href='/report/{e(r)}'>Open the page &rarr;</a>" for r in reports[:2])
    block = result_block(log)
    answer = (f"<div class='ws-answer'><h2>{'The answer' if ok else 'It stopped'}</h2>"
              + (f"<div class='ws-links'>{links}</div>" if links else "")
              + (f"<div class='ws-out'>{render_result(block)}</div>" if block else "") + "</div>")
    again = (f"<div class='ws-go'><a class='btn ghost' href='/tool/{e(t.cmd)}'>Run it again</a>"
             + ("" if ok else f"<a class='btn' href='/feedback?job={e(jid)}'>Send this report</a>") + "</div>")
    return (f"<div class='ws'>{head}{answer}{again}<details class='card'><summary>The whole log</summary>"
            f"<pre class='log'>{e(log[-20000:])}</pre></details></div>{CSS}")


CSS = "<style>" + theme.style("workshop") + "</style>"
