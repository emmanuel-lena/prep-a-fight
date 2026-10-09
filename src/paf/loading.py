"""Never a frozen window: a loading indicator while a page is on its way, and a banner with the progress of a prep
running in the background, on every page of the app (paf.web.page).

- Loading: a click on a link or a form starts a thin bar on top at once; after 0.4 s a card says "Loading..."; if
  it lasts, it says why (the first time, the game data is downloaded) and that nothing crashed.
- A prep running: "Preparing Nek'zali: 42% - about 12 min left", a bar, a link to its page; it updates itself.
"""

from __future__ import annotations

import time
from html import escape as e

from paf import theme

LOADER = """<div id="paf-load" aria-hidden="true"><div class="pl-bar"></div>
<div class="pl-card" role="status"><span class="pl-spin"></span><div><b>Loading&hellip;</b>
<span class="pl-slow">The first time, the app downloads the game data and the logs: it can take a moment.</span>
<span class="pl-slower">Still working: nothing has crashed.</span></div></div></div>"""

CSS = theme.style("loading")

JS = """<script>
(function(){
var L = document.getElementById('paf-load'); if (!L) return;
var timers = [];
function start(){
  stop(); L.classList.add('on');
  timers.push(setTimeout(function(){ L.classList.add('card'); }, 400));
  timers.push(setTimeout(function(){ L.classList.add('slow'); }, 4000));
  timers.push(setTimeout(function(){ L.classList.add('slower'); }, 15000));
}
function stop(){ timers.forEach(clearTimeout); timers = []; L.className = ''; }
document.addEventListener('click', function(ev){
  var a = ev.target.closest('a[href]'); if (!a || ev.defaultPrevented) return;
  var h = a.getAttribute('href');
  if (!h || h.charAt(0) === '#' || h.indexOf('javascript:') === 0 || a.target === '_blank' || a.hasAttribute('download')
      || a.hasAttribute('data-noload') || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
  if (a.origin && a.origin !== location.origin) return;
  start();
});
document.addEventListener('submit', function(ev){
  var f = ev.target; if (ev.defaultPrevented || f.hasAttribute('data-to') || f.hasAttribute('data-noload')) return;
  start(); var b = f.querySelector('button:not([type=button])'); if (b) b.classList.add('busy');
});
window.addEventListener('pageshow', stop);  // back to a page kept in memory: no loader left over
// a prep running: its banner updates itself
var jb = document.querySelector('.job-banner[data-job]');
if (jb) setInterval(function(){
  fetch('/job/' + jb.dataset.job + '?part=banner').then(function(r){ return r.text(); }).then(function(h){
    if (!h.trim()) { jb.remove(); return; }
    var t = document.createElement('div'); t.innerHTML = h; var n = t.firstElementChild; if (n) { jb.replaceWith(n); jb = n; }
  }).catch(function(){});
}, 5000);
})();
</script>"""

STARTUP = """<!doctype html><html><head><meta charset="utf-8"><style>
body{background:#181219;color:#d9cdd6;font:16px system-ui,sans-serif;display:grid;place-items:center;height:100vh;margin:0}
.box{display:flex;flex-direction:column;align-items:center;gap:16px;text-align:center;max-width:420px;padding:0 16px}
.spin{width:34px;height:34px;border-radius:50%;border:3px solid #3a2c38;border-top-color:#d4a73a;animation:t .8s linear infinite}
@keyframes t{to{transform:rotate(360deg)}}
b{font-size:18px;letter-spacing:.02em} .note{color:#a8939f;font-size:14px;opacity:0;animation:f 1s ease 4s forwards}
@keyframes f{to{opacity:1}}
</style></head><body><div class="box"><div class="spin"></div><b>Starting prep-a-fight&hellip;</b>
<span class="note">The first launch prepares the game data: it can take a minute.</span></div></body></html>"""


def startup_page() -> str:
    """The window's first page while the app starts, in the player's language."""
    try:
        from paf.i18n import translate

        return translate(STARTUP)
    except Exception:  # noqa: BLE001 - never block the start for a translation
        return STARTUP


def running_preps() -> list[tuple[str, dict]]:
    """The preps running now (started from this app, this session or an earlier one), newest first."""
    from paf.config import data_dir
    from paf.web import JOBS

    out = []
    folder = data_dir() / "web"
    for p in sorted(folder.glob("job-*.json"), key=lambda p: -p.stat().st_mtime)[:12] if folder.is_dir() else []:
        jid = p.stem.removeprefix("job-")
        job = JOBS.get(jid)
        if job and job["status"] == "running" and job["args"] and job["args"][0] == "prep":
            out.append((jid, job))
    return out


def percent(log: str, elapsed: float) -> tuple[int, float]:
    """(% done, minutes left) of a prep from its log."""
    from paf.progress import prep_progress

    _rows, left = prep_progress(log, elapsed)
    total = elapsed / 60 + left
    pct = int(round(100 * (elapsed / 60) / total)) if total > 0 else 0
    return max(1, min(99, pct)), left


def _boss_name(args: list[str]) -> str:
    try:
        from paf.web import _encounters

        boss = int(args[1])
        return next((x.name for x in _encounters() if x.id == boss), "the boss")
    except (ValueError, IndexError):
        return "the boss"


def banner(jid: str, job: dict) -> str:
    log = job["log"].read_text(encoding="utf-8", errors="replace") if job["log"].is_file() else ""
    pct, left = percent(log, time.time() - job["started"])
    eta = "almost done" if left < 1.5 else f"about {round(left)} min left"
    verb = "Full analysis of" if "--refine" in (job.get("args") or []) else "Preparing"
    return (f"<a class='job-banner' data-job='{e(jid)}' href='/job/{e(jid)}'><span class='jb-txt'>{verb} "
            f"<b>{e(_boss_name(job['args']))}</b>: <b class='jb-pct'>{pct}%</b> &middot; {eta}</span>"
            f"<span class='jb-bar'><span style='width:{pct}%'></span></span><span class='jb-go'>See &rarr;</span></a>")


def banners(skip: str = "") -> str:
    """The banner of each prep running (but the one whose page this is)."""
    return "".join(banner(jid, job) for jid, job in running_preps() if jid != skip)
