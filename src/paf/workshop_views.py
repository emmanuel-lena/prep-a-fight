"""The workshop's result pages (paf.results data): a verdict first, in one sentence, then what supports it, with game
icons and gain bars. The text output stays one click away (the log)."""

from __future__ import annotations

import re
from html import escape as e
from pathlib import Path

from paf import theme

SLOTS = {"head": "Head", "neck": "Neck", "shoulder": "Shoulders", "back": "Back", "chest": "Chest", "wrist": "Wrists",
         "hands": "Hands", "waist": "Waist", "legs": "Legs", "feet": "Feet", "finger": "Ring", "finger1": "Ring",
         "finger2": "Ring", "trinket": "Trinket", "trinket1": "Trinket", "trinket2": "Trinket",
         "main_hand": "Main hand", "off_hand": "Off hand", "two_hand": "Two-hand", "weapon": "Weapons", "rings": "Rings",
         "trinkets": "Trinkets"}
_RUNS = re.compile(r"^Runs(?: and best set)?:\s*(.+?)\s*$", re.M)


def run_dir(log: str) -> Path | None:
    m = list(_RUNS.finditer(log))
    return Path(m[-1].group(1)) if m else None


def _pct(v: float | None, digits: int = 1) -> str:
    return "&ndash;" if v is None else f"{v:+.{digits}f}%".replace("-", "&minus;")


def _bar(v: float, scale: float) -> str:
    """A gain bar from a centre line: right and green for a gain, left and red for a loss."""
    w = 0 if not scale else min(50.0, abs(v) / scale * 50)
    side = "pos" if v >= 0 else "neg"
    return f"<span class='gbar'><span class='g {side}' style='width:{w:.1f}%'></span></span>"


def _item_icons(rows: list[dict]) -> dict[int, str]:
    from paf.icons import icons_for

    refs = {str(r["item_id"]): f"item={r['item_id']}" for r in rows if r.get("item_id")}
    try:
        return {int(k): v for k, v in icons_for(refs).items()}
    except Exception:  # noqa: BLE001 - offline: no icons
        return {}


def _img(icon: str, cls: str = "it-ic") -> str:
    from paf import icons

    return icons.img(icon, "large", cls) if icon else f"<span class='{cls} none'></span>"


def _verdict(kind: str, title: str, text: str = "", big: str = "") -> str:
    mark = {"go": "&#8593;", "ok": "&#10003;", "warn": "!"}[kind]
    return (f"<div class='verdict {kind}'><span class='v-mark' aria-hidden='true'>{mark}</span><div><b>{title}</b>"
            + (f"<p>{text}</p>" if text else "") + "</div>" + (f"<span class='v-big'>{big}</span>" if big else "")
            + "</div>")


def talents(d: dict) -> str:
    err = d.get("error") or 0.2
    rows = [r for r in d.get("rows", []) if r.get("gain") is not None]
    best = max(rows, key=lambda r: r["gain"], default=None)
    if best and best["gain"] > 2 * err:
        both = set(best["take"]) & set(best["drop"])  # a name on two talent nodes: not a change worth saying
        chips = ("".join(f"<span class='chip add'>+ {e(x)}</span>" for x in best["take"] if x not in both)
                 + "".join(f"<span class='chip drop'>&minus; {e(x)}</span>" for x in best["drop"] if x not in both))
        copy = (f"<button type='button' class='btn go' data-copy='{e(best['code'])}'>Copy the talents</button>"
                if best.get("code") else "")
        head = _verdict("go", f"Switch to <span>{e(best['label'])}</span>",
                        f"Played by {best['players']} top players. What changes:", _pct(best["gain"], 2))
        head += f"<div class='chips'>{chips}</div><div class='v-act'>{copy}</div>"
    else:
        head = _verdict("ok", "Keep your talents", "No build of the top players does better with your character on "
                              "this fight (the differences are within the error).")
    scale = max((abs(r["gain"]) for r in rows), default=1) or 1
    lines = "".join(
        f"<li><span class='l-name'><b>{e(r['label'])}</b><small>{r['players']} top players</small></span>"
        f"{_bar(r['gain'], scale)}<span class='l-val {'pos' if r['gain'] > 2 * err else 'neg' if r['gain'] < -2 * err else ''}'>"
        f"{_pct(r['gain'], 2)}</span></li>" for r in sorted(rows, key=lambda r: -r["gain"]))
    return (f"{head}<h3>Every build, on your character</h3><ul class='glist'>{lines}</ul>"
            f"<p class='ws-fine'>Compared with your current build, on {e(d.get('boss', 'the boss'))}. Differences under "
            f"&plusmn;{2 * err:.2f}% are noise.</p>")


def loot(d: dict) -> str:
    err = d.get("error") or 0.2
    rows = d.get("rows", [])
    icons = _item_icons(rows)
    good = [r for r in rows if r["gain"] > 2 * err]
    bad = [r for r in rows if r["gain"] <= 2 * err]
    where = ", ".join(d.get("bosses", [])[:3]) + ("&hellip;" if len(d.get("bosses", [])) > 3 else "")
    if good:
        head = _verdict("go", "1 item worth it for you" if len(good) == 1 else f"{len(good)} items worth it for you",
                        f"From {e(where)}, at item level {d.get('ilvl')}.", _pct(good[0]["gain"]))
    else:
        head = _verdict("ok", "Nothing here is an upgrade for you", f"From {e(where)}, at item level {d.get('ilvl')}: "
                              "what you wear is already as good or better.")
    def card(r: dict, scale: float) -> str:
        return (f"<li class='icard'>{_img(icons.get(r['item_id'], ''))}<span class='l-name'><b>{e(r['name'])}</b>"
                f"<small><span>{e(SLOTS.get(r['slot'], r['slot']))}</span> &middot; {e(r['boss'])}</small></span>"
                f"{_bar(r['gain'], scale)}<span class='l-val {'pos' if r['gain'] > 2 * err else 'neg'}'>"
                f"{_pct(r['gain'])}</span></li>")
    def scale(lst: list[dict]) -> float:  # each list its own scale: a small gain is not lost next to big losses
        return max((abs(r["gain"]) for r in lst), default=1) or 1

    body = f"<ul class='glist items'>{''.join(card(r, scale(good)) for r in good)}</ul>" if good else ""
    if bad:
        body += (f"<details class='more'><summary>Not upgrades ({len(bad)})</summary><ul class='glist items'>"
                 f"{''.join(card(r, scale(bad)) for r in bad)}</ul></details>")
    evs = [x for x in d.get("ev", []) if x["ev"] > 0]
    ev = ("<h3>Which boss is worth it</h3><ul class='glist'>" + "".join(
        f"<li><span class='l-name'><b>{e(x['boss'])}</b><small>{x['n']} items for you</small></span>"
        f"{_bar(x['ev'], max(y['ev'] for y in evs))}<span class='l-val pos'>{_pct(x['ev'], 2)}</span></li>"
        for x in evs) + "</ul>") if len(evs) > 1 else ""
    return (f"{head}{body}{ev}<p class='ws-fine'>Each item simmed in its slot on your character; differences under "
            f"&plusmn;{2 * err:.2f}% are noise.</p>")


def topgear(d: dict) -> str:
    err = d.get("error") or 0.2
    rows = d.get("rows", [])
    if not rows:
        return _verdict("warn", "Nothing to compare", "No item in your bags could replace what you wear: paste a "
                                "/simc export with your bags.")
    best = rows[0]
    icons = _item_icons([i for r in rows[:4] for c in r["changes"] for i in c["items"]])

    def item(slot: str, i: dict) -> str:
        meta = [SLOTS.get(slot, slot)] + ([str(i["ilvl"])] if i.get("ilvl") else [])
        meta += [i["source"]] if i.get("source") not in ("bags", "equipped", None) else []
        return (f"<li class='icard'>{_img(icons.get(i.get('item_id') or 0, ''))}<span class='l-name'>"
                f"<b>{e(i['name'] or '?')}</b><small>{' &middot; '.join(f'<span>{e(m)}</span>' for m in meta)}</small>"
                f"</span></li>")

    def changes(r: dict) -> str:
        return "".join(item(c["slot"], i) for c in r["changes"] for i in c["items"])
    if best["gain"] > 2 * err:
        head = _verdict("go", "Put on these items", f"The best set from your bags{' on ' + e(', '.join(d.get('fights', []))) if d.get('fights') else ''}.",
                        _pct(best["gain"], 2)) + f"<ul class='glist items'>{changes(best)}</ul>"
    else:
        head = _verdict("ok", "Keep what you wear", "No combination of your bags does better (the differences are "
                              "within the error).")
    others = rows[1:6] if best["gain"] > 2 * err else rows[:5]
    more = "".join(f"<details class='more'><summary><b>{_pct(r['gain'], 2)}</b> &middot; "
                   f"{e(', '.join(i['name'] or '?' for c in r['changes'] for i in c['items']))}</summary>"
                   f"<ul class='glist items'>{changes(r)}</ul></details>" for r in others if r["changes"])
    title = "Other good sets" if best["gain"] > 2 * err else "The closest sets (within the error)"
    return (f"{head}" + (f"<h3>{title}</h3>{more}" if more else "")
            + f"<p class='ws-fine'>Differences under &plusmn;{2 * err:.2f}% are noise.</p>")


def cooldowns(d: dict) -> str:
    labels = {"boss": "For boss damage", "total": "For total damage (pad)", "adds": "On the adds",
              "secondary": "On the secondary targets"}
    out = ""
    for p in d.get("plans", []):
        worth = p["gain"] > 2 * (p.get("error") or 0.2)
        rules = "".join(f"<li><b>{e(r['cd'])}</b><span>{e(r['how'])}</span></li>" for r in p["rules"])
        body = (f"<ul class='rules'>{rules}</ul>" if worth and rules else
                "<p>Press your cooldowns as soon as they are ready: holding them gains nothing here.</p>")
        flags = "".join(f"<p class='ws-fine'>! {e(f)}</p>" for f in p.get("flags", []))
        out += (f"<div class='plan {'go' if worth else 'ok'}'><div class='p-head'><b>{e(labels.get(p['objective'], p['objective']))}</b>"
                f"<span class='v-big'>{_pct(p['gain'], 2) if worth else '&#10003;'}</span></div>{body}{flags}</div>")
    return out or _verdict("warn", "No plan", "The optimization found nothing to compare.")


def _pull(d: dict) -> str:
    """'Your raid's kill of 7:11, next to the top raids of this boss', from 'this boss, kill of 7:11'."""
    import re

    m = re.search(r"(kill|pull) of ([\d:]+)", d.get("fight", ""))
    what = (f"<span>Your raid's {m.group(1)}</span> <span class='num'>{m.group(2)}</span>" if m
            else "<span>Your raid's pull</span>")
    return f"{what} <span>next to the top raids of this boss.</span>"


def review(d: dict) -> str:
    """Who does what in the raid's pull: the targets first (your raid vs the top raids), then each player."""
    from paf import icons

    targets = d.get("targets", [])
    main = next((t["name"] for t in targets if t["main"]), "")
    players = d.get("players", [])
    moves = [p for p in players if p["verdict"] in ("to_target", "to_boss")]
    if moves:
        head = _verdict("go", "1 player can do better for the boss" if len(moves) == 1 else
                        f"{len(moves)} players can do better for the boss", _pull(d))
    else:
        head = _verdict("ok", "Your raid plays like the top raids", _pull(d))
    scale = max((max(t["raid"], t["tops"]) for t in targets), default=1) or 1
    rows = "".join(
        f"<li class='tg'><span class='l-name'><b>{e(t['name'])}</b><small>{'the boss' if t['main'] else ('covered' if t['covered'] else 'not enough')}"
        f"</small></span><span class='cov'><span class='c-raid {'ok' if t['covered'] else 'short'}' style='width:{t['raid'] / scale * 100:.1f}%'></span>"
        f"<span class='c-tops' style='left:{t['tops'] / scale * 100:.1f}%' title='top raids'></span></span>"
        f"<span class='l-val'>{t['raid']:.0%} <small>/ {t['tops']:.0%}</small></span></li>" for t in targets)

    def who(p: dict) -> str:
        cls = p["spec"].split(" ")[-1].lower()
        ic = icons.img(icons.CLASS_ICON.format(cls=cls), "medium", "it-ic")
        mine, habit = p["shares"].get(p["target"], 0.0), p["habit"].get(p["target"], 0.0)
        # short pieces, each a whole text (the translation matches whole texts): numbers and names apart
        def line(target: str, you: float, tops: float) -> str:
            return (f"<span class='p-num'><b>{you:.0%}</b> <span>on</span> <i>{e(target)}</i></span>"
                    f"<span class='p-tops'><span>top players of the spec:</span> <b>{tops:.0%}</b></span>")
        if p["verdict"] == "to_boss":
            say = line(p["target"], mine, habit) + ("<small>Your raid already covers it: that damage is better on "
                                                    "the boss.</small>")
        elif p["verdict"] == "to_target":
            say = line(p["target"], mine, habit) + "<small>Your raid lacks damage there.</small>"
        else:
            say = (line(main, p["shares"].get(main, 0.0), p["habit"].get(main, 0.0)) if p["habit"]
                   else "<small>Spec not measured on this boss.</small>")
        return (f"<li class='pl {p['verdict']}'>{ic}<span class='l-name'><b>{e(p['name'])}</b><small>{e(p['spec'])}</small>"
                f"</span><span class='p-say'>{say}</span></li>")
    groups = [("to_target", "Should go on a target"), ("to_boss", "Can move damage to the boss"),
              ("ok", "Play like the top players of their spec"), ("unknown", "Not measured")]
    blocks = ""
    for key, title in groups:
        lst = [p for p in players if p["verdict"] == key]
        if not lst:
            continue
        items = "".join(who(p) for p in lst)
        if key in ("ok", "unknown"):
            blocks += f"<details class='more'><summary>{e(title)} ({len(lst)})</summary><ul class='plist'>{items}</ul></details>"
        else:
            blocks += f"<h3>{e(title)}</h3><ul class='plist'>{items}</ul>"
    return (f"{head}<h3>Where your raid's damage goes</h3><ul class='glist cov-list'>{rows}</ul>{blocks}"
            "<p class='ws-fine'>Your raid's share of damage on each target, the mark is the top raids'. This compares "
            "habits: it does not know your raid's assignments (a soak, a kick, an add someone must hold).</p>")


def comp(d: dict) -> str:
    """Who hits what: per target, the specs of the raid that do the most damage on it, and who should hit it."""
    from paf import icons

    boss = d.get("boss", "")
    targets = d.get("targets", [])

    def ic(spec: str, size: str = "medium") -> str:
        return icons.img(icons.CLASS_ICON.format(cls=spec.split(" ")[-1].lower()), size, "it-ic")

    def names(lst: list) -> str:
        return "".join(f"<span class='who'>{ic(p['spec'])}<b>{e(p['name'])}</b></span>" for p in lst)

    assigned = [t for t in targets if t["players"]]
    if not targets:
        return _verdict("ok", "Nothing to assign on this boss", "<span>The top raids put their damage on the boss.</span>")
    if assigned:
        head = _verdict("go", "Who hits what in your raid", "<span>The specs of your raid that do the most damage on "
                        "each target, from the top kills of this boss.</span>")
    else:
        head = _verdict("ok", "Who hits what in your raid", "<span>No add is assigned in the top raids: the whole raid "
                        "switches.</span>")
    cards = ""
    for t in targets:
        ranking = "".join(
            f"<li>{ic(r['spec'])}<span class='l-name'><b>{e(r['spec'])}</b><small>{e(', '.join(r['players']))}</small>"
            f"</span><span class='l-val'>{r['dps'] / 1000:,.0f}k</span></li>" for r in t["ranking"])
        if t["second_boss"]:
            kind = "Second boss"
            say = (f"<p><span>The top raids split their damage:</span> <b class='num'>{t['main']:.0%}</b> "
                   f"<span>on</span> <i>{e(boss)}</i>, <b class='num'>{t['tops']:.0%}</b> <span>on</span> "
                   f"<i>{e(t['name'])}</i>.</p><p class='lab'>The specs of your raid that hit both bosses the hardest"
                   "</p>")
        elif t["players"]:
            kind = "Whole raid" if t["whole_raid"] else "Assigned"
            say = (f"<p><span>Players on it in the top raids:</span> <b class='num'>{t['players']}</b>"
                   + (" <span>(on top of the whole raid)</span>" if t["whole_raid"] else "") + "</p>"
                   "<p class='lab'>The specs of your raid that do the most damage on it</p>")
        else:
            kind = "Whole raid"
            say = ("<p>In the top raids, the whole raid hits it.</p>"
                   "<p class='lab'>The specs of your raid that do the most damage on it</p>")
        block = f"<ul class='rank'>{ranking}</ul>" if ranking else ""
        if t["proposed"]:
            block += f"<p class='lab go'>Put them on it</p><div class='whos'>{names(t['proposed'])}</div>"
        if t["pulled"]:
            block += (f"<details class='more'><summary>On it in your pull ({len(t['pulled'])})</summary>"
                      f"<div class='whos'>{names(t['pulled'])}</div></details>")
        if t["missed"]:
            block += (f"<p class='lab warn'>Hardly hit it in your pull</p><div class='whos'>{names(t['missed'])}</div>")
        cards += (f"<div class='job'><div class='j-head'><b>{e(t['name'])}</b><small>{kind}</small></div>{say}{block}"
                  "</div>")
    swaps = d.get("swaps") or []
    swap_html = ""
    if swaps:
        swap_html = ("<h3>Change spec for more boss damage</h3><ul class='glist items three'>" + "".join(
            f"<li>{ic(x['better'], 'large')}<span class='l-name'><b>{e(x['name'])}</b><small><span class='was'>"
            f"{e(x['current'])}</span> &rarr; {e(x['better'])}</small></span><span class='l-val pos'>"
            f"{_pct(x['gain'] * 100, 0)}</span></li>" for x in swaps) + "</ul><p class='ws-fine'>Optional: the boss "
            "damage of the other spec's players in the top kills of this boss, vs the current spec's (medians). "
            "It does not know each player's gear or practice on the other spec.</p>")
    return (f"{head}<div class='jobs wide'>{cards}</div>{swap_html}<p class='ws-fine'>DPS on the target of each spec's players in "
            "the top kills of this boss (those assigned to it for an assigned target; on both bosses for a second "
            "boss). It compares specs, not your players' skill, and does not know your strategy.</p>")

def _mmss(t: float | None) -> str:
    if t is None or t == float("inf"):
        return "&ndash;"
    return f"{int(t // 60)}:{int(t % 60):02d}"


def wipe(d: dict) -> str:
    """The best pull in detail: when the boss would have died, the boss health curves, the deaths and their cost."""
    from paf import icons

    k = d.get("kill", {})
    longest = d.get("longest_kill") or 0
    big = _mmss(k.get("no_deaths_share"))
    head = _verdict("go", f"Boss at {d['left']:.1%} after {_mmss(d['duration'])}",
                    f"<span>Without the deaths, and with the top kills' share of damage on the boss:</span> "
                    f"<span>kill at</span> <span class='num'>{big}</span>.", big)
    tiles = "".join(
        f"<div class='kt {cls}'><small>{label}</small><b>{_mmss(k.get(key))}</b></div>"
        for key, label, cls in (("as_is", "As played", ""), ("no_deaths", "Without the deaths", ""),
                                ("no_deaths_share", "And the top kills' boss share", "go"),
                                ("like_tops", "Like the top players of each spec", "go")) if key in k)
    tiles += (f"<div class='kt'><small>Top kills</small><b>{_mmss(d.get('median_kill'))}</b>"
              f"<span><span>longest</span> {_mmss(longest)}</span></div>")
    # boss health curves over the pull
    curves = d.get("curves", {})
    n = max((len(v) for v in curves.values()), default=0)
    span = max(d["duration"], longest, 1)
    W, H, L, B = 640, 220, 40, 26

    def pts(vals: list[float]) -> str:
        return " ".join(f"{L + i * 15 / span * (W - L - 10):.1f},{10 + (1 - v) * (H - B - 20):.1f}"
                        for i, v in enumerate(vals))
    lines = ""
    for key, cls in (("as_is", "c-now"), ("no_deaths", "c-alive"), ("no_deaths_share", "c-best"),
                     ("like_tops", "c-tops")):
        if curves.get(key):
            lines += f"<polyline class='{cls}' points='{pts(curves[key])}'/>"
    xk = L + longest / span * (W - L - 10)
    ticks = "".join(f"<text x='{L + t / span * (W - L - 10):.1f}' y='{H - 6}' class='tk'>{int(t // 60)}:00</text>"
                    for t in range(0, int(span) + 1, 120))
    deaths = d.get("deaths", [])
    marks = "".join(f"<line class='dm' x1='{L + x['t'] / span * (W - L - 10):.1f}' x2='{L + x['t'] / span * (W - L - 10):.1f}' "
                    f"y1='10' y2='{H - B}'/>" for x in deaths)
    svg = (f"<svg class='hp' viewBox='0 0 {W} {H}' role='img' aria-label='Boss health over the pull'>"
           f"<line class='ax' x1='{L}' x2='{W - 10}' y1='{H - B}' y2='{H - B}'/>"
           f"<text x='4' y='16' class='tk'>100%</text><text x='4' y='{H - B}' class='tk'>0%</text>{ticks}{marks}"
           f"<line class='kl' x1='{xk:.1f}' x2='{xk:.1f}' y1='10' y2='{H - B}'/>{lines}</svg>"
           "<div class='legend'><span class='c-now'>As played</span><span class='c-alive'>Without the deaths</span>"
           "<span class='c-best'>And the top kills' boss share</span><span class='c-tops'>Like the top players of "
           "each spec</span><span class='kl'>Longest top kill</span>"
           "<span class='dm'>A death</span></div>") if n else ""

    def who(x: dict) -> str:
        cls, _, spec = x["spec"].partition("-")
        ic = icons.img(icons.CLASS_ICON.format(cls=cls.lower()), "medium", "it-ic")
        back = (f"<span>back at</span> {_mmss(x['back'])}" if x["back"] is not None else "<span>never back</span>")
        return (f"<li>{ic}<span class='l-name'><b>{e(x['name'])}</b><small><span>died at</span> {_mmss(x['t'])} "
                f"&middot; {back}</small></span><span class='l-val neg'>&minus;{x['lost']:.1%}</span></li>")
    lost = sum(x["lost"] for x in deaths)
    death_html = ""
    if deaths:
        death_html = (f"<h3>The deaths: <span class='num'>{lost:.1%}</span> of the boss's health</h3>"
                      f"<ul class='glist items three'>{''.join(who(x) for x in sorted(deaths, key=lambda x: -x['lost']))}</ul>")
    share = (f"<h3>The damage off the boss</h3><p><span>Your raid put</span> <b class='num'>{d['raid_share']:.0%}</b> "
             f"<span>of its damage on the boss, the top kills</span> <b class='num'>{d['tops_share']:.0%}</b>.</p>")
    culprits = [c for c in d.get("culprits", []) if c["lost_alive"] + c["lost_dead"] >= 0.002]

    def culprit(c: dict) -> str:
        cls = c["spec"].partition("-")[0]
        ic = icons.img(icons.CLASS_ICON.format(cls=cls.lower()), "medium", "it-ic")
        why = []
        if c["tops_dps"]:
            why.append(f"<span class='p-num'><span>on the boss while alive:</span> <b>{c['alive_dps'] / 1000:,.0f}k</b> "
                       f"<span>top players of the spec:</span> <b>{c['tops_dps'] / 1000:,.0f}k</b></span>")
        if c["lost_dead"] >= 0.001:
            why.append(f"<span class='p-tops'><span>deaths:</span> <b>&minus;{c['lost_dead']:.1%}</b></span>")
        chips = "".join(f"<span class='chip drop'>{e(t)}</span>" for t in c["pad_talents"])
        if chips:
            why.append(f"<span class='p-tops'>Talents the padders take more:</span><span class='chips'>{chips}</span>")
        chips = "".join(f"<span class='chip add'>{e(t)}</span>" for t in c["boss_talents"])
        if chips:
            why.append(f"<span class='p-tops'>Talents the boss top takes more:</span><span class='chips'>{chips}</span>")
        lost = c["lost_alive"] + c["lost_dead"]
        return (f"<li class='pl'>{ic}<span class='l-name'><b>{e(c['name'])}</b><small>&minus;{lost:.1%}</small></span>"
                f"<span class='p-say'>{''.join(why)}</span></li>")
    culprit_html = ""
    if culprits:
        culprit_html = ("<h3>Who lost the most boss damage</h3><p class='ws-fine'>Share of the boss's health, next to "
                        "the median boss DPS of the top kills' players of the same spec.</p><ul class='plist'>"
                        + "".join(culprit(c) for c in culprits) + "</ul>")
    return (f"{head}<div class='kts'>{tiles}</div>{svg}{culprit_html}{death_html}{share}<p class='ws-fine'>From your log, 15 s at a "
            "time. A dead player loses the boss damage they did per 15 s before dying, until a battle res; the deaths "
            "of the wipe itself are left out. The boss share part is an upper bound: a longer pull sees more adds. "
            "A kill past the end of the pull is extrapolated at the boss damage of its last minute.</p>")

def night(d: dict) -> str:
    """The raid night: per player, then per pull."""
    from paf import icons

    pulls = d.get("pulls", [])
    summary = d.get("summary", {})
    ic_of = d.get("icons", {})

    def ic(name: str) -> str:
        cls = ic_of.get(name, "").partition("-")[0]
        return icons.img(icons.CLASS_ICON.format(cls=cls.lower()), "medium", "it-ic") if cls else _img("")
    deaths = sum(v["deaths"] for v in summary.values())
    bare = sum(v["bare"] for v in summary.values())
    head = _verdict("warn" if bare else "ok", f"{len(pulls)} pulls, {deaths} deaths before the wipes",
                    f"<span>Died without a healthstone or a health potion first:</span> <span class='num'>{bare}</span>")
    rows = ""
    for name, v in sorted(summary.items(), key=lambda x: (-x[1]["bare"], -x[1]["deaths"])):
        pot = v["pulls_damage_potion"]
        rows += (f"<tr><td class='who-c'>{ic(name)}<b>{e(name)}</b></td><td class='n'>{v['deaths']}</td>"
                 f"<td class='n {'bad' if v['bare'] else ''}'>{v['bare']}</td><td class='n'>{v['healthstone']}</td>"
                 f"<td class='n'>{v['health']}</td><td class='n {'bad' if not pot else ''}'>{pot}/{len(pulls)}</td></tr>")
    table = (f"<div class='scroll'><table class='night'><tr><th>Player</th><th>Deaths</th><th>Without a healthstone or "
             f"potion</th><th>Healthstones</th><th>Health potions</th><th>Pulls with a damage potion</th></tr>{rows}"
             "</table></div>")
    detail = ""
    for r in pulls:
        dead = sorted(((min(p["deaths"]), n, p["bare"]) for n, p in r["players"].items() if p["deaths"]))
        end = "Kill" if r["kill"] else f"{(r['left'] or 0):.0%}"
        who = "".join(f"<span class='who {'bare' if b else ''}'>{ic(n)}<b>{e(n)}</b> {_mmss(t)}</span>"
                      for t, n, b in dead[:12])
        detail += (f"<li><div class='j-head'><b>{e(r['boss'])}</b><small><span class='num'>{_mmss(r['duration'])}</span>"
                   f" &middot; {end}</small></div><div class='whos'>{who}</div></li>")
    return (f"{head}<h3>Over the night</h3>{table}<details class='more'><summary>Pull by pull ({len(pulls)})</summary>"
            f"<ul class='pulls'>{detail}</ul></details><p class='ws-fine'>Read from the casts of the log: a potion "
            "pressed before the pull is not counted, nor the deaths of the wipe itself. A name in red died without a "
            "healthstone or a health potion first.</p>")

def pulldiff(d: dict) -> str:
    """Two pulls side by side: the highlights first, the boss health, then the player's detail."""
    from paf import icons

    a, b = d.get("a", {}), d.get("b", {})
    pl = d.get("player")
    head = _verdict("go", f"{pl['name']}: pull B next to pull A" if pl else "Pull B next to pull A",
                    f"<span class='pab a'>A</span> <span>{e(a.get('label', ''))}</span> &middot; "
                    f"<span class='pab b'>B</span> <span>{e(b.get('label', ''))}</span>")
    hl = "".join(f"<li class='{h['kind']}'><span class='hm'>{'&#8593;' if h['kind'] == 'good' else '&#8595;'}</span>"
                 f"<span>{e(h['text'])}</span></li>" for h in d.get("highlights", []))
    out = head + (f"<h3>What changed, biggest first</h3><ul class='hl'>{hl}</ul>" if hl else "")
    curves = d.get("curves", {})
    span = max(a.get("duration", 0), b.get("duration", 0), 1)
    W, H, L, B = 640, 200, 40, 26

    def pts(vals: list[float]) -> str:
        return " ".join(f"{L + i * 15 / span * (W - L - 10):.1f},{10 + (1 - v) * (H - B - 20):.1f}"
                        for i, v in enumerate(vals))
    if curves:
        ticks = "".join(f"<text x='{L + t / span * (W - L - 10):.1f}' y='{H - 6}' class='tk'>{int(t // 60)}:00</text>"
                        for t in range(0, int(span) + 1, 120))
        out += (f"<h3>The boss's health</h3><svg class='hp' viewBox='0 0 {W} {H}' role='img' aria-label='Boss health'>"
                f"<line class='ax' x1='{L}' x2='{W - 10}' y1='{H - B}' y2='{H - B}'/><text x='4' y='16' class='tk'>"
                f"100%</text><text x='4' y='{H - B}' class='tk'>0%</text>{ticks}"
                f"<polyline class='c-now' points='{pts(curves.get('a', []))}'/>"
                f"<polyline class='c-best' points='{pts(curves.get('b', []))}'/></svg><div class='legend'>"
                "<span class='c-now'>Pull A</span><span class='c-best'>Pull B</span></div>")
    if not pl:
        return out + "<p class='ws-fine'>Pick a player to see their own damage, casts and buffs in both pulls.</p>"
    cls = pl["icon"].partition("-")[0]
    ic = icons.img(icons.CLASS_ICON.format(cls=cls.lower()), "medium", "it-ic") if cls else ""

    def k(v: float | None) -> str:
        return "&ndash;" if v is None else f"{v / 1000:,.0f}k"

    def pct(v: float | None) -> str:
        return "&ndash;" if v is None else f"{v:.0%}"
    tiles = "".join(f"<div class='kt'><small>{label}</small><b>{va} <span>&rarr;</span> {vb}</b></div>" for label, va, vb in (
        ("Damage per second", k(pl["dps_a"]), k(pl["dps_b"])), ("On the bosses", k(pl["boss_a"]), k(pl["boss_b"])),
        ("Active", pct(pl["active_a"]), pct(pl["active_b"]))))
    out += f"<h3 class='who-c'>{ic}<span>{e(pl['name'])}</span></h3><div class='kts'>{tiles}</div>"

    def table(title: str, head: tuple[str, str, str], rows: list[str]) -> str:
        return (f"<h3>{title}</h3><div class='scroll'><table class='night'><tr><th>{head[0]}</th><th>A</th><th>B</th>"
                f"<th>{head[1]}</th></tr>{''.join(rows)}</table></div>") if rows else ""

    def delta(va: float, vb: float, fmt: str) -> str:
        cls = "pos" if vb > va else "neg" if vb < va else ""
        return f"<td class='n {cls}'>{fmt.format(vb - va) if fmt else ''}</td>"
    out += table("Damage per second of each ability", ("Ability", "Change", ""), [
        f"<tr><td>{e(r['name'])}</td><td class='n'>{k(r['a'])}</td><td class='n'>{k(r['b'])}</td>"
        f"{delta(r['a'], r['b'], '')}</tr>".replace("<td class='n pos'></td>", f"<td class='n pos'>+{(r['b'] - r['a']) / 1000:,.0f}k</td>")
        .replace("<td class='n neg'></td>", f"<td class='n neg'>&minus;{(r['a'] - r['b']) / 1000:,.0f}k</td>")
        for r in pl.get("abilities", [])])

    def times(ts: list[float]) -> str:
        return " ".join(_mmss(t) for t in ts[:8])
    out += table("Casts per minute (cooldowns: when)", ("Ability", "Cast at, A / B", ""), [
        f"<tr><td>{e(r['name'])}</td><td class='n'>{r['a']:.1f}</td><td class='n'>{r['b']:.1f}</td>"
        f"<td class='small'>{(times(r['times_a']) + ' / ' + times(r['times_b'])) if r['cooldown'] else ''}</td></tr>"
        for r in pl.get("casts", [])[:12]])
    out += table("Uptime of your buffs and procs", ("Buff", "Change", ""), [
        f"<tr><td>{e(r['name'])}</td><td class='n'>{r['a']:.0%}</td><td class='n'>{r['b']:.0%}</td>"
        f"<td class='n {'pos' if r['b'] > r['a'] else 'neg'}'>{(r['b'] - r['a']) * 100:+.0f}</td></tr>"
        for r in pl.get("buffs", [])])
    cons = pl.get("consumables", {})
    out += ("<h3>Consumables and deaths</h3><ul class='hl'>"
            + "".join(f"<li><span>{label}:</span> <b class='num'>{cons.get(key, [0, 0])[0]}</b> <span>&rarr;</span> "
                      f"<b class='num'>{cons.get(key, [0, 0])[1]}</b></li>"
                      for key, label in (("healthstone", "Healthstones"), ("health", "Health potions"),
                                         ("damage_potion", "Damage potions")))
            + f"<li><span>Deaths:</span> <b class='num'>{len(pl['deaths'][0])}</b> <span>&rarr;</span> "
              f"<b class='num'>{len(pl['deaths'][1])}</b></li></ul>")
    return out + ("<p class='ws-fine'>Both pulls read from your log, 15 s at a time. The pulls compared by default are "
                  "your worst and your best by your own damage, among those where you did not die and of a similar "
                  "length: the gap is gameplay. Buffs that players of other classes also have (a healer's) are left "
                  "out.</p>")

def rotation(d: dict) -> str:
    """A player's rotation: the points to work on, each context's spells next to the rotation's, DoTs, cooldowns."""
    from paf import icons

    cls = d.get("spec", "").rpartition(" ")[2]
    ic = icons.img(icons.CLASS_ICON.format(cls=cls.lower()), "large", "it-ic") if cls else ""
    hl = d.get("highlights", [])
    head = _verdict("go" if hl else "ok", f"{d['player']}: your rotation",
                    f"<span>{e(d.get('spec', ''))}</span> &middot; <span>{e(d.get('boss', ''))}</span> &middot; "
                    f"<span>{e(d.get('pull', ''))}</span> &middot; <span class='num'>{_mmss(d.get('duration'))}</span>")
    out = f"<div class='rot-head'>{ic}{head}</div>"
    if hl:
        out += ("<h3>To work on</h3><ol class='todo'>" + "".join(f"<li>{e(t)}</li>" for t in hl) + "</ol>")
    else:
        out += "<p>Nothing stands out next to the rotation: well played.</p>"
    cards = ""
    total = sum(c["seconds"] for c in d.get("contexts", [])) or 1
    for c in d.get("contexts", []):
        rows = ""
        for x in c["rows"][:9]:
            gap = x["player"] - x["sim"]
            cls_ = "far" if abs(gap) >= 0.08 else ""
            rows += (f"<li class='{cls_}'><span class='l-name'><b>{e(x['name'])}</b><small>{x['per_min']:.1f}/min</small>"
                     f"</span><span class='cov'><span class='c-raid {'short' if cls_ else 'ok'}' "
                     f"style='width:{min(100, x['player'] * 100 / 0.6):.1f}%'></span><span class='c-tops' "
                     f"style='left:{min(100, x['sim'] * 100 / 0.6):.1f}%' title='rotation'></span></span>"
                     f"<span class='l-val'>{x['player']:.0%} <small>/ {x['sim']:.0%}</small></span></li>")
        cards += (f"<div class='job ctx'><div class='j-head'><b>{e(c['label'])}</b><small><span class='num'>"
                  f"{_mmss(c['seconds'])}</span> &middot; {c['seconds'] / total:.0%}</small></div>"
                  f"<ul class='glist cov-list'>{rows}</ul></div>")
    if cards:
        out += ("<h3>Your spells, by number of targets</h3><p class='ws-fine'>Bar: your share of casts; mark: the "
                "rotation's (SimulationCraft's default rotation, your gear and talents, same number of targets).</p>"
                f"<div class='jobs wide'>{cards}</div>")
    dots = d.get("dots", [])
    if dots:
        out += "<h3>Your DoTs</h3><ul class='glist items three'>" + "".join(
            f"<li><span class='dot-ic'>{x['uptime']:.0%}</span><span class='l-name'><b>{e(x['name'])}</b><small>"
            f"<span>refreshed too early</span> {x['early']}/{x['refreshes']} &middot; <span>median left</span> "
            f"{x['median_left']:.1f} s &middot; <span>window</span> {0.3 * x['duration']:.1f} s"
            + ("<br><span>as often as the rotation casts it: its own way</span>" if x.get("like_rotation") else "")
            + f"</small></span><span class='l-val {'neg' if not x.get('like_rotation') and x['early'] / x['refreshes'] >= 0.3 else ''}'>"
            f"{x['early'] / x['refreshes']:.0%}</span></li>" for x in dots if x["refreshes"]) + "</ul>"
    cds = d.get("cooldowns", [])
    if cds:
        out += "<h3>Your cooldowns</h3><ul class='glist items three cds'>" + "".join(
            f"<li><span class='pips'>{'&#9679;' * x['casts']}{'&#9675;' * max(0, x['possible'] - x['casts'])}</span>"
            f"<span class='l-name'><b>{e(x['name'])}</b><small><span>every</span> {x['cooldown']:.0f} s &middot; "
            f"{' '.join(_mmss(t) for t in x['times'][:8])}</small></span><span class='l-val "
            f"{'neg' if x['casts'] < x['possible'] else 'pos'}'>{x['casts']}/{x['possible']}</span></li>"
            for x in cds) + "</ul>"
    buffs = d.get("buffs", [])
    if buffs:
        out += ("<h3>Your buffs next to the top players'</h3><ul class='glist cov-list'>" + "".join(
            f"<li><span class='l-name'><b>{e(b['name'])}</b><small><span>top players of your spec:</span> "
            f"{b['tops']:.0%}</small></span><span class='cov'><span class='c-raid "
            f"{'short' if b['player'] < b['tops'] else 'ok'}' style='width:{b['player'] * 100:.1f}%'></span>"
            f"<span class='c-tops' style='left:{b['tops'] * 100:.1f}%' title='top players'></span></span>"
            f"<span class='l-val'>{b['player']:.0%}</span></li>" for b in buffs[:8]) + "</ul>")
    waste = [w for w in d.get("waste", []) if w["capped"]]
    if waste:
        out += "<h3>Resource lost</h3><ul class='hl'>" + "".join(
            f"<li class='bad'><span class='hm'>!</span><span>{e(w['builder'])}: {w['capped']}/{w['casts']} "
            f"<span>at full</span> {e(w['resource'])}</span></li>" for w in waste) + "</ul>"
    return out + ("<p class='ws-fine'>Read from your log, for every spec alike: no analyzer written per class. The "
                  "rotation is SimulationCraft's default one, simulated with your gear and talents of that pull on 1, "
                  "3 and 5 targets; the number of targets comes from the enemies you hit every 5 s. A gap is a "
                  "reading, not a fault: a mechanic, a movement or an assignment can explain it.</p>")

def bonusroll(d: dict) -> str:
    """Bonus rolls: each boss ranked by the mean gain of one roll (its usable items, losses as 0), its best item."""
    evs = sorted(d.get("ev", []), key=lambda x: -x["ev"])
    rows = d.get("rows", [])
    err = d.get("error") or 0.2
    try:  # the bosses' portraits (paf.bossimg), by name
        from paf.web import _encounters

        ids = {x.name: x.id for x in _encounters()}
    except Exception:  # noqa: BLE001 - offline: no portraits
        ids = {}
    if not evs or evs[0]["ev"] <= 0:
        return _verdict("ok", "No boss is worth a bonus roll for you",
                        "<span>Nothing they drop beats what you wear.</span>")
    top = evs[0]
    if top["ev"] < 2 * err:  # the best is within the noise of the sims: no boss stands out
        head = _verdict("ok", "No boss stands out for a bonus roll",
                        f"<span>The best mean gain of a roll is under the noise of the sims (&plusmn;{2 * err:.2f}%): "
                        "spend your rolls where you like, or try a higher difficulty.</span>", _pct(top["ev"], 2))
    else:
        head = _verdict("go", f"Bonus roll on {top['boss']} first",
                        "<span>The mean gain of one roll: every item it can give you counts, an item that is no "
                        "upgrade counts as 0.</span>", _pct(top["ev"], 2))
    scale = max(x["ev"] for x in evs) or 1
    out = ""
    for i, x in enumerate(evs, 1):
        mine = [r for r in rows if r["boss"] == x["boss"]]
        ups = [r for r in mine if r["gain"] > 2 * err]
        best = max(mine, key=lambda r: r["gain"], default=None)
        face = (f"<img class='br-face' src='/bossimg/{ids[x['boss']]}.png' alt='' loading='lazy' "
                f"onerror=\"this.remove()\">" if x["boss"] in ids else "")
        best_txt = (f"<span>best:</span> {e(best['name'])} <b class='pos'>{_pct(best['gain'])}</b>"
                    if best and best["gain"] > 2 * err else "<span>no real upgrade</span>")
        out += (f"<li class='br'><span class='br-rank'>{i}</span>{face}<span class='l-name'><b>{e(x['boss'])}</b>"
                f"<small><span>upgrades:</span> {len(ups)}/{x['n']} &middot; {best_txt}</small></span>"
                f"{_bar(x['ev'], scale)}<span class='l-val {'pos' if x['ev'] > 0 else ''}'>{_pct(x['ev'], 2)}</span>"
                "</li>")
    return (f"{head}<h3>Every boss, best roll first</h3><ul class='glist brs'>{out}</ul>"
            f"<p class='ws-fine'>Each item simmed in its slot on your character, at item level {d.get('ilvl')}; "
            f"a roll gives one item of the boss's loot for your spec, any of them alike. Gains under "
            f"&plusmn;{2 * err:.2f}% are noise.</p>")

VIEWS = {"talents": talents, "loot": loot, "topgear": topgear, "cooldowns": cooldowns, "review": review, "comp": comp, "wipe": wipe, "night": night, "diff": pulldiff, "rotation": rotation, "bonusroll": bonusroll}


def render(data: dict) -> str | None:
    view = VIEWS.get(data.get("kind", ""))
    return view(data) if view else None


CSS = "<style>" + theme.style("workshop-views") + "</style>"
