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


GROUPS = (("gear", "Your gear and talents"), ("cds", "Your cooldowns and rotation"), ("raid", "Your raid"), ("boss", "The boss"))

TOOLS: tuple[Tool, ...] = (
    Tool("topgear", "Best gear from your bags", "Your bags' best set for this boss.",
         "inv_misc_bag_10", "gear", "5-15", ("boss~", "difficulty", "goal"),
         "Your best sets, each with its gain in % over what you wear.", needs_prep=False),
    Tool("droptimizer", "What a boss drops for you", "Which drops of this boss, or the raid, upgrade you.", "inv_misc_coin_02", "gear", "5-10", ("boss?", "difficulty", "goal"),
         "Every item worth it for you, with its gain in %, best first.", needs_prep=False),
    Tool("bonusroll", "Where to use your bonus rolls", "Which boss is worth your bonus roll.", "inv_misc_coin_17", "gear", "5-10", ("difficulty", "goal"),
         "Every boss of the raid ranked by what a bonus roll brings you, with its best item.", needs_prep=False),
    Tool("specgear", "Which spec, which gear", "Your best spec here, and the top players' gear (ilvl 334) on you.", "achievement_bg_topdps", "gear", "1-3", ("boss", "difficulty"),
         "Your character simmed in each spec in the top players' gear, their gap in the logs, your own kills, and one "
         "sentence."),
    Tool("talents", "The top players' talents, on you", "Which top players' build does the most on you.", "inv_misc_book_11", "gear", "3-6", ("boss", "difficulty"),
         "The builds compared on your character, with their gain and the talents to change."),
    Tool("optimize", "When to press your cooldowns", "Hold each cooldown for a moment, or press it on cooldown.", "spell_holy_borrowedtime", "cds", "20-40",
         ("boss", "difficulty", "goal3"), "The best cooldown plan for each goal you pick, and the pull played with it."),
    Tool("timeline", "The top players' cooldowns, minute by minute", "When the best players of your spec press each cooldown.", "inv_misc_pocketwatch_01", "cds", "1", ("boss", "difficulty"),
         "A page with the cooldown timeline of each top player, side by side."),
    Tool("raid", "Pad the adds or stay on the boss?", "Do the others already cover the adds?", "inv_misc_groupneedmore", "raid", "1-3", ("boss", "difficulty", "raid"),
         "The verdict for each add type, and why."),
    Tool("review", "Your raid's pull, player by player", "Who stays on the boss, who pads, next to the top raids.", "inv_misc_spyglass_03", "raid", "1",
         ("boss", "difficulty", "raid"), "Each player's damage on the boss and on each target, next to the top "
         "players of their spec, and what to change for more boss damage."),
    Tool("comp", "Who hits what in your raid", "Who hits the adds you cannot skip, in your raid.", "achievement_guildperk_everybodysfriend", "raid", "1",
         ("boss", "difficulty", "raid"), "Each add with who takes it in the top raids and in your pull, and who "
         "should, in their own spec."),
    Tool("wipe", "Your best pull, in detail", "What the deaths cost, and when the boss would have died.", "spell_shadow_soulleech_3", "raid", "1", ("boss", "difficulty", "raid"),
         "The boss's health over your best pull, as played and without the deaths, and what each death cost."),
    Tool("night", "Your raid night, pull by pull", "Deaths, healthstones and potions, pull by pull; live too.", "inv_stone_04", "raid", "1", ("raid",),
         "Each player over the night, then each pull: deaths, healthstones, potions.", needs_prep=False),
    Tool("diff", "Two pulls side by side", "What went better in one pull than another, raid and you.", "inv_misc_spyglass_02", "raid", "1-2", ("boss", "difficulty", "raid"),
         "From the log you give: its worst and best pulls without a death (else its best wipe and the kill), with "
         "both pulls' boss health, deaths, damage per target, and your damage, casts and buffs in each.",
         needs_prep=False),
    Tool("rotation", "Your rotation, spell by spell", "Single target, cleave, AoE: your casts against the best rotation.", "ability_rogue_rollthebones", "cds", "1-2",
         ("boss", "difficulty", "raid"), "The points to work on, your share of each spell next to the rotation's, "
         "your DoTs and your cooldowns.", needs_prep=False),
    Tool("mechanics", "The boss's mechanics", "Every ability from the Encounter Journal, by role.",
         "inv_misc_book_09", "boss", "1", ("boss", "difficulty"),
         "The boss's abilities by role, and who handles what in the top kills.", needs_prep=False),
    Tool("assigns", "Assignments you can take", "Which mechanics a player can take, when, at what cost.", "ability_warrior_rallyingcry", "boss", "1", ("boss", "difficulty"),
         "Each assignable mechanic with its timings and the damage it costs.", needs_prep=False),  # reads the kills
)
BY_CMD = {t.cmd: t for t in TOOLS}
CURATED_FIELDS = {"boss", "difficulty", "objective", "raid", "fight"}  # set by the curated form, not under "options"


def _icon(name: str, cls: str = "") -> str:
    from paf import icons

    return icons.img(name, "large", cls)


def cards(cmds: tuple[str, ...] | list[str], target: str = "") -> str:
    """The tools' cards, each a link to its page; `target` for a page shown in a frame (the sheet)."""
    tgt = f" target='{target}'" if target else ""
    n = sum(1 for c in cmds if c in BY_CMD)
    cols = {2: " c2", 4: " c2", 5: " c5", 8: " c4"}.get(n, "")  # rows that close: never one card alone
    return f"<div class='ws-cards{cols}'>" + "".join(
        f"<a class='ws-card' href='/tool/{t.cmd}'{tgt}>{_icon(t.icon, 'ws-ic')}<span class='ws-txt'><b>{e(t.title)}</b>"
        f"<span class='ws-q'>{e(t.question)}</span></span></a>"
        for c in cmds if (t := BY_CMD.get(c))) + "</div>"


def index() -> str:
    groups = ""
    for gid, title in GROUPS:
        groups += f"<h2>{e(title)}</h2>{cards([t.cmd for t in TOOLS if t.group == gid])}"

    return (f"<div class='ws'><header class='ws-head'><div><h1>Tools</h1><p class='lead'>A boss's prep runs them "
            f"all; run one again to dig further.</p></div>"
            f"</header>{groups}</div>{CSS}")


def _prepared_ids(encounters: list, diff: str | None = None) -> set:
    """The bosses with a prep sheet of your spec at a difficulty (yours by default): the data a tool reads."""
    try:
        from paf import settings
        from paf.corpus.template import _slug
        from paf.web import prepared

        mine = f"{settings.get('spec')}-{settings.get('class')}".lower().replace(" ", "-")
        keys = {x["key"] for x in prepared() if "prep" in x["files"]}
        diff = diff or settings.get("difficulty")
        return {x.id for x in encounters if f"{_slug(x.name)}-{diff}-{mine}" in keys}
    except Exception:  # noqa: BLE001 - no data: no marks
        return set()


# the form follows the boss and difficulty picked: the "· has a sheet" marks, the goals a boss without adds leaves,
# and whether the tool can run (an adds tool needs adds, a tool that reads a prep needs a sheet), with one note why not
READY_JS = """<script>(function(s){var f=s&&s.form;if(!f)return;
function diff(){var c=f.querySelector('[name=difficulty]:checked')||f.querySelector('select[name=difficulty]');return c&&c.value}
function opt(){return s.options[s.selectedIndex]||{dataset:{}}}
function sheet(o,d){return !d||(' '+(o.dataset.r||'')+' ').indexOf(' '+d+' ')>=0}
function update(init){
  var d=diff();
  [].forEach.call(s.options,function(o){if(o.dataset.n!=null)o.textContent=o.dataset.n+(d&&sheet(o,d)?' \u00b7 has a sheet':'')});
  if(init&&f.dataset.addsOnly&&opt().dataset.na){var w=[].filter.call(s.options,function(o){return !o.dataset.na})[0];if(w)s.value=w.value}
  var o=opt(),na=!!o.dataset.na;
  f.querySelectorAll('[name=objective]').forEach(function(r){var l=r.closest('label')||r;
    if(r.value==='total'||r.value==='all'){l.hidden=na;if(na&&r.checked){var b=f.querySelector('[name=objective][value=boss]');if(b)b.checked=true}}});
  var why=f.dataset.addsOnly&&na?'noadds':(f.dataset.needsPrep&&!sheet(o,d)?'noprep':'');
  f.querySelectorAll('.ws-noadds,.ws-noprep').forEach(function(n){n.hidden=n.className.indexOf('ws-'+why)<0||!why});
  var g=f.querySelector('.ws-go .btn');if(g)g.disabled=!!why;
  var a=f.querySelector('.ws-prep');if(a&&o.value)a.href='/boss?boss='+o.value+'&difficulty='+(d||'')}
f.addEventListener('change',function(){update()});document.addEventListener('DOMContentLoaded',function(){update(1)});update(1)
})(document.currentScript.previousElementSibling.querySelector('select'))</script>"""


def _no_adds(encounters: list) -> set:
    """The bosses whose prep pack has no add wave."""
    try:
        from paf import pack, settings

        diff = settings.DIFFICULTIES.get(settings.get("difficulty"), 4)
        out = set()
        for x in encounters:
            pk = pack.load(x.id, diff, settings.get("class"), settings.get("spec"))
            if pk is not None and not pk.fight.add_waves:
                out.add(x.id)
        return out
    except Exception:  # noqa: BLE001 - no packs: every choice stays
        return set()


def _boss_select(encounters: list, optional: str = "", last: bool = False) -> str:
    """The raid's bosses; `optional` an empty choice, first (every boss) or `last` (the training dummy: the real fight
    comes first, it is the point of the app)."""
    extra = (f"<option value=''{' data-na=1' if last else ''}>{e(optional)}</option>"  # a training dummy has no adds
             if optional else "")
    ready = _prepared_ids(encounters)  # the bosses with a sheet: said, and the first of them picked
    first = next((x.id for x in encounters if x.id in ready), None) if not optional else None
    by_diff = {d: _prepared_ids(encounters, d) for d in ("normal", "heroic", "mythic")}
    flat = _no_adds(encounters)  # nothing to pad on these: the goal choice leaves only boss damage
    opts = "".join(f"<option value='{x.id}' data-n='{e(x.name)}'{' data-na=1' if x.id in flat else ''} "
                   f"data-r='{' '.join(d for d, s in by_diff.items() if x.id in s)}'"
                   f"{' selected' if x.id == first else ''}>{e(x.name)}{' · has a sheet' if x.id in ready else ''}</option>"
                   for x in encounters)
    body = opts + extra if last else extra + opts
    return f"<label class='ws-f'><span>Boss</span><select name='boss' class='big'>{body}</select></label>{READY_JS}"


def _segs(name: str, label: str, options: list[tuple[str, str, str]], checked: str) -> str:
    segs = "".join(f"<label class='seg' title='{e(hint)}'><input type='radio' name='{name}' value='{e(v)}'"
                   f"{' checked' if v == checked else ''}><span>{e(text)}</span></label>" for v, text, hint in options)
    return f"<div class='ws-f'><span>{e(label)}</span><div class='segs'>{segs}</div></div>"


def _field(kind: str, encounters: list) -> str:
    from paf.web import DIFF_LABELS

    if kind in ("boss", "boss?", "boss~"):
        return _boss_select(encounters, {"boss?": "Every boss of the raid",
                                          "boss~": "A training dummy (no boss)"}.get(kind, ""), last=kind == "boss~")
    if kind == "difficulty":
        return _segs("difficulty", "Difficulty", [(d, DIFF_LABELS.get(d, d), "") for d in settings.DIFFICULTIES
                                                  if d != "lfr"], settings.get("difficulty"))
    if kind == "goal":
        return _segs("objective", "Your goal", [("boss", "Boss damage", "progress: everyone on the boss"),
                                                ("total", "Pad the adds", "total damage: the adds count too")], "boss")
    if kind == "goal3":
        return _segs("objective", "Your goal", [("boss", "Boss damage", ""), ("total", "Pad the adds", ""),
                                                ("all", "Both, a plan for each", "")], "all")  # the wizard's words
    if kind == "raid":
        g = settings.get("guild")
        hint = f"Empty: the latest public log of {g}." if g else "Or set your guild in Settings."
        return (f"<label class='ws-f'><span>Your raid's log</span><input name='raid' placeholder='https://www.warcraftlogs"
                f".com/reports/...'><small class='muted'>{e(hint)}</small></label>")
    return ""


ADDS_ONLY = ("comp",)  # tools about the adds: off on a boss without any


def tool_page(cmd: str, encounters: list) -> str | None:
    t = BY_CMD.get(cmd)
    if t is None:
        return None
    fields = "".join(_field(k, encounters) for k in t.fields)  # the CLI's other options: ?raw=1, for developers
    note = ""  # said only when it matters: the boss picked has no sheet (ws-noprep)
    return (f"<div class='ws'>"
            f"<header class='ws-tool'>{_icon(t.icon, 'ws-big')}<div><h1>{e(t.title)}</h1><p class='lead'>{e(t.question)}"
            f"</p></div></header>"
            f"<form method='post' action='/tool/{e(cmd)}' class='ws-form'{' data-adds-only=1' if cmd in ADDS_ONLY else ''}"
            f"{' data-needs-prep=1' if t.needs_prep else ''}>"
            f"<input type='hidden' name='_curated' value='1'>"
            f"{fields}<p class='ws-gives'><b>You get:</b> {e(t.gives)}</p>{note}"
            "<p class='ws-note ws-noadds' hidden>No adds on this boss: nothing for this tool to read. Pick a boss with "
            "adds.</p><p class='ws-note ws-noprep' hidden>No sheet for this boss at this difficulty yet: <a href='/' "
            "class='ws-prep'>prepare it</a> first, then run this tool.</p>"
            f"<div class='ws-go'><button class='btn go'>Run it &rarr;</button><span class='muted small'>About "
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
