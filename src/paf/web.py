"""Local web UI (`paf serve`): paste your /simc, pick a boss, tick your assignments, get the prep sheet.

Standard library only. Listens on 127.0.0.1. Long work (corpus, sims) runs as `paf` subprocesses whose
output is shown live; the result is the prep sheet page.
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from paf import settings, theme
from paf.config import data_dir, load_dotenv
from paf.progress import PREP_STEPS, prep_progress  # noqa: F401 - PREP_STEPS: re-exported
from paf.theme import diff_pill

e = html.escape


def bossguide_css() -> str:
    from paf.bossguide import CSS as GUIDE_CSS

    return GUIDE_CSS

CSS = theme.CSS + bossguide_css() + theme.style("web")


def page(title: str, body: str, refresh: int | None = None, nav: str = "", job: str = "") -> bytes:
    """job: the prep whose own page this is (its banner is not repeated on top)."""
    from paf import loading

    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    try:
        running = loading.banners(skip=job)
    except Exception:  # noqa: BLE001 - a banner never breaks a page
        running = ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, '
            f'initial-scale=1">{meta}<title>{e(title)}</title>{theme.HEAD}<style>{CSS}{loading.CSS}</style>'
            f"{_class_style()}</head><body class='has-side'>"
            f"{theme.sidebar(nav, who=character_menu(), foot=lang_switch())}{loading.LOADER}"
            f"<main>{update_banner()}{running}{body}</main>{loading.JS}</body></html>").encode()


def share_page(key: str, error: str = "") -> str:
    """Share a prep sheet with the raid: a link that opens in any browser."""
    from paf import share

    item = next((x for x in prepared() if x["key"] == key and "prep" in x["files"]), None)
    if item is None:
        return "<h1>Not found</h1><p>Nothing prepared for this boss yet.</p>"
    info = share.current(key)
    head = (f"<h1>Share this prep</h1>"
            f"<p class='lead'>{e(item['name'])} {theme.diff_pill(item['difficulty'])}"
            + (f" &middot; {e(item['spec'])}" if item.get("spec") else "") + "</p>")
    err = f"<p class='notice'>{e(error)}</p>" if error else ""
    if info:
        return (head + err + f"""<div class='card'><p><b>Shared.</b> Anyone with this link sees the prep sheet in their
browser, without the app:</p><p class='row'><input readonly value='{e(info["url"])}' style='flex:1;min-width:260px'
onclick='this.select()'><button type='button' data-copy='{e(info["url"])}'>Copy the link</button>
<a class='btn ghost' href='{e(info["url"])}' target='_blank' rel='noopener'>Open</a></p>
<p class='small muted'>It stays online {info.get("days", 30)} days, then disappears. To publish a newer version after
a new prep, stop sharing and share again.</p>
<form method='post' action='/unshare/{e(key)}'><button class='btn ghost'>Stop sharing</button></form></div>{COPY_JS}""")
    return (head + err + f"""<div class='card'><p>Get a link to this prep sheet for your raid (Discord, guild
forum...): it opens in any browser, nobody needs the app.</p>
<p class='small muted'>The sheet shows your character's name and gear: anyone with the link can see them. It stays
online 30 days, and you can stop sharing it at any time.</p>
<form method='post' action='/share/{e(key)}'><button class='btn go'>Share it</button></form></div>""")


COPY_JS = """<script>document.addEventListener('click',function(ev){var b=ev.target.closest('[data-copy]');if(!b)return;
var t=b.getAttribute('data-copy'),o=b.textContent;function done(){b.textContent='Copied';setTimeout(function(){
b.textContent=o},1500)}if(navigator.clipboard){navigator.clipboard.writeText(t).then(done,function(){})}});</script>"""


def lang_switch() -> str:
    """The language of the app, in the top bar: changing it reloads the page."""
    from paf import i18n

    cur, windows = i18n.language(), i18n.system_language()
    if cur == "en" and (windows == "en" or windows not in i18n.available()):  # English only until the 1.0: the
        return ""  # switch shows for a player whose Windows is in a language the app has (partly) translated
    options = "".join(f"<option value='{e(c)}'{' selected' if c == cur else ''}>{e(c.upper())}</option>"
                      for c in i18n.available())
    return (f"<form method='post' action='/language' class='lang' style='display:inline'>"
            f"<select name='lang' aria-label='Language / Langue' onchange='pafLang(this)'>{options}</select>"
            f"<noscript><button>OK</button></noscript></form>{LANG_JS}")


# Switch the language in place: save it, fetch this page (and the sheet in its frame) again, already translated by
# the server, and swap the content without reloading: no flash, scroll and open tab kept. Without JavaScript the
# form posts and the page reloads.
LANG_JS = """<script>
async function pafFetch(url, opts){  // the whole response, body included, with a few tries: a local connection can drop
  for (let i = 0; ; i++) {
    const ctl = new AbortController(), timer = setTimeout(function(){ ctl.abort(); }, 5000);
    try {
      const r = await fetch(url, Object.assign({signal: ctl.signal}, opts));
      if (!(r.ok || r.status === 204)) throw new Error(r.status);
      const text = await r.text();
      clearTimeout(timer);
      return text;
    } catch (e) { clearTimeout(timer); if (i >= 2) throw e; await new Promise(function(ok){ setTimeout(ok, 150); }); }
  }
}
async function pafSwap(doc, url){
  const html = await pafFetch(url, {cache: 'no-store'});
  const fresh = new DOMParser().parseFromString(html, 'text/html');
  const win = doc.defaultView, y = win.scrollY;
  doc.title = fresh.title;
  const body = doc.importNode(fresh.body, true);
  body.querySelectorAll('script').forEach(function(old){
    const s = doc.createElement('script');
    for (const a of old.attributes) s.setAttribute(a.name, a.value);
    s.textContent = old.textContent; old.replaceWith(s);
  });
  doc.body.replaceWith(body);
  win.scrollTo(0, y);
}
async function pafLang(sel){
  sel.disabled = true;
  try {
    await pafFetch('/language', {method: 'POST', headers: {'X-Paf-Inline': '1'},
                                 body: new URLSearchParams({lang: sel.value})});
    const frame = document.querySelector('iframe');
    if (frame && frame.contentDocument) {  // a prep sheet in its frame: swap the top bar, then the sheet itself
      const html = await pafFetch(location.href, {cache: 'no-store'});
      const fresh = new DOMParser().parseFromString(html, 'text/html');
      document.title = fresh.title;
      const bar = fresh.querySelector('header.topbar');
      const swapBar = function(){
        const b = document.importNode(bar, true);
        b.querySelectorAll('script').forEach(function(old){
          const s = document.createElement('script'); s.textContent = old.textContent; old.replaceWith(s);
        });
        document.querySelector('header.topbar').replaceWith(b);
      };
      await pafSwap(frame.contentDocument, frame.contentWindow.location.href);
      if (bar) swapBar();
    } else {
      await pafSwap(document, location.href);
    }
  } catch (e) { window.pafLastError = String(e && e.stack || e); sel.disabled = false; sel.form.submit(); }
}
</script>"""


QUIT = {"hook": None}
PUBLIC_BASE = ""  # the local server's address, when the desktop window shows pages without it (paf.inproc)  # set by the desktop app: closes its window (an update is being installed)


def update_banner() -> str:
    from paf import update

    rel = update.STATE.get("release")
    if rel is None:
        return ""
    action = ("<form method='post' action='/update' style='display:inline'><button class='btn'>Update now</button>"
              "</form>" if update.install_dir() else
              f"<a class='btn' href='{e(rel.url)}' target='_blank' rel='noopener'>Download it</a>")
    return (f"<div class='notice small row'><span><b>Version {e(rel.version)} is out</b> (you have "
            f"{e(update.__version__)}). <a href='{e(rel.url)}' target='_blank' rel='noopener'>What's new</a>"
            f"</span>{action}</div>")


def busy() -> str:
    """What runs in the background that an update would kill (its processes use the installed Python): '' when
    nothing does."""
    from paf import lastraid, raidlead, raidqueue

    if any(j.get("status") == "running" for j in JOBS.jobs.values()):
        return "A prep is running"
    checks = (("Your raid is being prepared", lambda: raidqueue.active(raidqueue.load())),
              ("Your last raid is being read", lastraid.runner_alive),
              ("Your raid's roles are being read", raidlead.runner_alive))
    for what, running in checks:
        try:
            if running():
                return what
        except Exception:  # noqa: BLE001 - a state file that cannot be read never blocks an update
            pass
    return ""


def pause_all(why: str) -> None:
    """Pause every prep running and the raid queue (an update: the app resumes them at its next start); the last
    raid and the raid's roles are read again at the start anyway."""
    from paf import lastraid, raidlead, raidqueue
    from paf.jobrun import kill_tree

    for jid, _job in loading_running():
        JOBS.pause(jid, why)
    q = raidqueue.load()
    if raidqueue.active(q):
        raidqueue.pause(why)
    for module, key in ((lastraid, "_pid"), (raidlead, "pid")):
        try:
            state = module.load()
            if module.runner_alive(state):
                kill_tree(int(state[key]))
        except Exception:  # noqa: BLE001 - a reader that cannot be stopped never blocks an update
            pass


def loading_running() -> list:
    from paf import loading

    return list(loading.running_preps())


def resume_paused(why: str) -> int:
    """At the app's start: the preps an update paused go on (the raid queue: paf.raidqueue.resume)."""
    n = 0
    for jid in JOBS.paused(why):
        if JOBS.resume(jid):
            n += 1
    return n


def run_update(pause: bool = False) -> str:
    """Download the new installer, start it over this install and close the app (the installer reopens it). With
    something running, it asks first; `pause` pauses it, and the app resumes it after the update."""
    from paf import update

    rel, folder = update.STATE.get("release"), update.install_dir()
    if rel is None or folder is None:
        return "<h1>Nothing to update</h1><p><a href='/'>Back home</a></p>"
    working = busy()
    if working and not pause:
        return (f"<h1>{e(working)}</h1><p class='lead'>The update pauses it, and the app resumes it by itself when "
                "it opens again (the logs already read are kept; the sims of the boss being prepared run again)."
                "</p><form method='post' action='/update' class='cta'><input type='hidden' name='pause' value='1'>"
                "<button class='btn'>Pause it and update</button><a class='btn ghost' href='/'>Not now</a></form>")
    if working:
        pause_all("update")
    try:
        setup = update.download(rel)
    except (OSError, ValueError) as ex:
        return (f"<h1>The update failed</h1><p class='notice'>{e(str(ex))}</p><p>Download it by hand: "
                f"<a href='{e(rel.url)}' target='_blank' rel='noopener'>{e(rel.url)}</a></p>")
    update.run_installer(setup, folder)
    threading.Timer(1.5, lambda: (QUIT["hook"] or (lambda: os._exit(0)))()).start()
    return (f"<h1>Updating to {e(rel.version)}&hellip;</h1><p class='lead'>The app closes now and reopens by itself "
            f"in a few seconds. Your preps and settings are kept.</p>")


# the desktop app (paf.desktop) turns it on: a prep that ends while its window is behind others says so
NOTIFY = {"on": False, "title": "prep-a-fight"}


def _notify_done(args: list[str], status: str) -> None:
    """A Windows notification when a prep ends and the player is elsewhere (paf.tray): go cook, come back."""
    from paf import tray

    try:
        if tray.in_front(NOTIFY["title"]):
            return
        name = next((x.name for x in _encounters() if len(args) > 1 and str(x.id) == args[1]), "Your boss")
        if status == "done":
            tray.notify_once(f"{name} is ready", "Your prep sheet is waiting.", NOTIFY["title"])
        else:
            tray.notify_once(f"The {name} prep stopped", "Open prep-a-fight to see why.", NOTIFY["title"])
    except Exception:  # noqa: BLE001 - a notification never breaks a job
        pass


class Jobs:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, args: list[str], result: Path | None) -> str:
        jid = uuid.uuid4().hex[:8]
        log = data_dir() / "web" / f"job-{jid}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        job = {"args": args, "log": log, "result": result, "status": "running", "started": time.time()}
        with self.lock:
            self.jobs[jid] = job
        self._save(jid, job)

        def run() -> None:
            with log.open("w", encoding="utf-8", errors="replace") as out:
                flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW
                from paf.jobrun import SESSION

                proc = subprocess.Popen([_python(), "-m", "paf", *args], stdout=out, stderr=subprocess.STDOUT,
                                        env={**_env(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}, **flags,
                                        **SESSION)
                job["pid"] = proc.pid
                self._save(jid, job)
                code = proc.wait()
            if job["status"] == "paused":  # stopped on purpose: it waits for Resume
                return
            job["status"] = "done" if code == 0 else f"failed (exit {code})"
            self._save(jid, job)
            if NOTIFY["on"] and args[:1] == ["prep"]:
                _notify_done(args, job["status"])

        threading.Thread(target=run, daemon=True).start()
        return jid

    @staticmethod
    def _save(jid: str, job: dict) -> None:
        """Jobs are kept on disk: the progress page survives a restart of the app (the prep keeps running)."""
        import json

        meta = {"args": job["args"], "result": str(job["result"] or ""), "status": job["status"],
                "started": job["started"], "pid": job.get("pid"), "why": job.get("why", ""),
                "next": job.get("next", "")}
        (data_dir() / "web" / f"job-{jid}.json").write_text(json.dumps(meta), encoding="utf-8")

    def get(self, jid: str) -> dict | None:
        import json
        import re

        if not re.fullmatch(r"[0-9a-f]{8}", jid):
            return None
        if jid in self.jobs:
            return self.jobs[jid]
        p = data_dir() / "web" / f"job-{jid}.json"
        if not p.is_file():
            return None
        meta = json.loads(p.read_text(encoding="utf-8"))
        log = data_dir() / "web" / f"job-{jid}.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        status = meta["status"]
        if status in ("paused", "resumed"):
            return {"args": meta["args"], "log": log, "result": Path(meta["result"]) if meta["result"] else None,
                    "status": status, "started": meta["started"], "why": meta.get("why", ""),
                    "next": meta.get("next", "")}
        if status == "running":  # started by an earlier run of the app: read the outcome from the log
            # still running: its process is alive (a long silent step, like extracting simc, writes nothing for
            # minutes); without a pid (an older app), a log written in the last 15 min
            alive = pid_alive(meta["pid"]) if meta.get("pid") else (
                log.is_file() and time.time() - log.stat().st_mtime < 900)
            status = "done" if "Prep sheet:" in text else "failed" if "Traceback" in text else (
                "running" if alive else "stopped")
        return {"args": meta["args"], "log": log, "result": Path(meta["result"]) if meta["result"] else None,
                "status": status, "started": meta["started"], "pid": meta.get("pid")}

    def pause(self, jid: str, why: str = "") -> bool:
        """Stop a running prep so it can go on later (Resume): the kills it downloaded and the Warcraft Logs answers
        stay in the corpus and the cache; its sims run again. `why`: 'update' when an update paused it (the app
        resumes it at its next start)."""
        from paf.jobrun import kill_tree

        job = self.get(jid)
        if job is None or job["status"] != "running":
            return False
        pid = job.get("pid") or (self.jobs.get(jid) or {}).get("pid")
        live = self.jobs.get(jid, job)
        live.update(status="paused", why=why)
        self._save(jid, live)
        if pid:
            kill_tree(int(pid))
        return True

    def resume(self, jid: str) -> str | None:
        """Start a paused prep again (a new job, the same command); the paused one points to it."""
        job = self.get(jid)
        if job is None or job["status"] != "paused":
            return job.get("next") if job else None
        new = self.start(job["args"], job["result"])
        job.update(status="resumed", next=new)
        self._save(jid, job)
        return new

    def paused(self, why: str | None = None) -> list[str]:
        """The paused jobs (for one reason, when given), most recent first."""
        import json

        out = []
        for p in sorted((data_dir() / "web").glob("job-*.json"), key=lambda p: -p.stat().st_mtime):
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if meta.get("status") == "paused" and (why is None or meta.get("why") == why):
                out.append(p.stem[4:])
        return out


def pid_alive(pid: int) -> bool:
    """Whether a process with this id runs (a job started by an earlier run of the app)."""
    if sys.platform == "win32":
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    import os

    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def _python() -> str:
    """The console Python next to the running one (the desktop app runs under pythonw.exe)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").is_file():
        return str(exe.parent / "python.exe")
    return sys.executable


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


JOBS = Jobs()


def _profile_path() -> Path:
    return data_dir() / "profiles" / "current.simc"


def _encounters() -> list:
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    try:
        encs = raid_encounters(WCLClient())
    except Exception:  # noqa: BLE001 - the UI must still load without credentials
        return []
    zone = max((x.zone_id for x in encs), default=None)
    return journal_order([x for x in encs if x.zone_id == zone])  # the raid's order, on every page


DIFF_NAMES = tuple(settings.DIFFICULTIES)


def split_key(key: str) -> tuple[str, str, str]:
    """'nek-zali-mythic-assassination-rogue' -> ('nek-zali', 'mythic', 'Assassination Rogue'). Reports made
    before the spec was part of the name have no spec."""
    import re

    m = re.match(rf"^(.+?)-({'|'.join(DIFF_NAMES)})(?:-(.+))?$", key)
    if not m:
        return key, "", ""
    return m.group(1), m.group(2), (m.group(3) or "").replace("-", " ").title()


def prepared() -> list[dict]:
    """Bosses with a prep sheet or a timeline in the reports folder, newest first."""
    import re

    reports = data_dir() / "reports"
    out: dict[str, dict] = {}
    for f in reports.glob("*.html") if reports.is_dir() else []:
        kind, _, key = f.stem.partition("-")
        if kind not in ("prep", "timeline") or not key or key.endswith("-slow"):  # a raid like yours: its sheet's
            continue
        item = out.setdefault(key, {"key": key, "files": {}, "mtime": 0.0, "name": "", "difficulty": ""})
        item["files"][kind] = f.name
        item["mtime"] = max(item["mtime"], f.stat().st_mtime)
        if kind == "prep" and f.with_suffix(".json").is_file():
            import json

            try:
                item["headline"] = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
            except ValueError:
                pass
        boss, diff, spec = split_key(key)
        item.update(boss=boss, difficulty=diff, spec=spec)
        if not item["name"] or kind == "prep":
            m = re.search(rb"<title>(.*?)</title>", f.read_bytes()[:4000], re.S)
            title = html.unescape(m.group(1).decode("utf-8", "replace")) if m else key
            item["name"] = re.sub(r"\s+(prep|timelines)$", "", title).strip()
    return sorted(out.values(), key=lambda x: -x["mtime"])


def prepared_block() -> str:
    items = prepared()
    if not items:
        return ""
    tiles = "".join(
        f'<a class="tile boss-tile" href="/view/{e(x["key"])}"><div class="name">{e(x["name"])}</div>'
        f'{diff_pill(x["difficulty"])} '
        + (f'<span class="pill">{e(x["spec"])}</span> ' if x["spec"] else "")
        + f'<span class="pill">{"prep sheet + timelines" if len(x["files"]) == 2 else "prep sheet only" if "prep" in x["files"] else "timelines only"}</span>'
        + (f'<div class="top"><b class="pos">{x["headline"]["gain"]:+.1f}%</b> {e(x["headline"]["what"])}</div>'
           if x.get("headline", {}).get("gain") is not None else "")
        + f'<div class="when">updated {time.strftime("%d %b %H:%M", time.localtime(x["mtime"]))}</div></a>'
        for x in items)
    return f'<h2>Your prepared bosses</h2><div class="grid">{tiles}</div>'


def ago(mtime: float, now: float | None = None) -> str:
    """When a prep was made, in words."""
    s = max(0.0, (now or time.time()) - mtime)
    if s < 120:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    if s < 2 * 86400:
        return "yesterday"
    return time.strftime("%d %b", time.localtime(mtime))


DIFF_LABELS = {"lfr": "LFR", "normal": "Normal", "heroic": "Heroic", "mythic": "Mythic"}


def boss_cards(items: list[dict], order: tuple[str, ...] = (), spec: bool = True) -> str:
    """The prepared bosses as a ruled list, one group per boss in the raid's order: the spec, the difficulty, when;
    the numbers stay in the sheet."""
    from paf import icons

    def row(x: dict) -> str:
        cls = (x.get("spec") or "").split(" ")[-1].lower()
        ic = icons.img(icons.CLASS_ICON.format(cls=cls), "medium", "bc-ic") if cls else "<span class='bc-ic'></span>"
        who = e(x["spec"] or "Your sheet") + " " if spec else ""  # under "Your sheets as X": said once
        return (f'<a class="bcard" href="/view/{e(x["key"])}">{ic}<span class="bc-txt">{who}'
                f'{diff_pill(x["difficulty"])}{"" if "prep" in x["files"] else " <span class=muted>no sim yet</span>"}'
                f'</span><span class="bc-when">{ago(x["mtime"])}</span></a>')
    groups: dict[str, list[dict]] = {}
    for x in items:
        groups.setdefault(x["name"], []).append(x)
    rank = {n: i for i, n in enumerate(order)}
    names = sorted(groups, key=lambda n: (rank.get(n, len(rank)), n))
    return "".join(f'<section class="bgroup"><h3>{e(n)}</h3><div class="bcards">{"".join(row(x) for x in groups[n])}'
                   f'</div></section>' for n in names)


TABS = (("prep", "Prep sheet"), ("timeline", "Top players' timelines"))
# a report shown in the app: its own brand bar goes (the sidebar carries the brand)
NO_TOPBAR = "try{var b=this.contentDocument.querySelector('.topbar');if(b)b.remove()}catch(x){}"


def view_page(key: str, tab: str) -> bytes:
    """One place per boss: the prep sheet and the top players' timelines as tabs (the reports stay standalone
    files, shown in a frame)."""
    item = next((x for x in prepared() if x["key"] == key), None)
    if item is None:
        return page("Not found", "<p>Nothing prepared for this boss yet.</p>")
    if tab not in item["files"]:
        tab = next(iter(k for k, _ in TABS if k in item["files"]))
    tabs = "".join(
        f'<a class="{"on" if k == tab else ""}" href="/view/{e(key)}?tab={k}">{e(label)}</a>'
        for k, label in TABS if k in item["files"])
    def spec_of(x: dict) -> str:  # "subtlety-rogue" in the key: two sheets of a boss told apart
        return x["key"].partition(f'-{x["difficulty"]}-')[2].replace("-", " ").title()
    groups: dict[str, list[dict]] = {}  # one group per spec, yours first: the spec is what tells sheets apart
    for x in sorted(prepared(), key=lambda x: (x["name"], x["difficulty"])):
        groups.setdefault(spec_of(x), []).append(x)
    others = "".join(
        f'<optgroup label="{e(g)}">' + "".join(
            f'<option value="/view/{e(x["key"])}"{" selected" if x["key"] == key else ""}>'
            f'{e(x["difficulty"].capitalize())} · {e(x["name"])}</option>' for x in xs) + "</optgroup>"
        for g, xs in sorted(groups.items(), key=lambda kv: (kv[0] != spec_of(item), kv[0])))
    src = f'/report/{e(item["files"][tab])}'
    boss_link = _boss_link(item)
    nav = (f'<label class="side-lab">Your sheets</label><select onchange="location=this.value" aria-label="Your sheets">'
           f'{others}</select><div class="side-links">{tabs}'
           + (f'<a href="{e(boss_link)}">Edit &amp; re-run</a>' if boss_link else "")
           + (f'<a href="/share/{e(key)}">Share</a>' if "prep" in item["files"] else "")
           + f'<a href="{PUBLIC_BASE}{src}" target="_blank">Open alone</a>')
    css = theme.style("view")
    watch = ""
    try:  # the full pass of this sheet running: the page reloads when it is done
        from paf import loading

        refining = next((jid for jid, job in loading.running_preps() if "--refine" in (job["args"] or [])
                         and job["result"] and Path(job["result"]).stem == f"prep-{key}"), None)
    except Exception:  # noqa: BLE001
        refining = None
    if refining:
        nav += f'<a href="/job/{e(refining)}">Full analysis running&hellip;</a>'
        watch = ("<script>setInterval(function(){fetch('/job/" + refining + "?part=live').then(function(r){"
                 "return r.text()}).then(function(t){if(t.indexOf('data-reload')>=0)location.reload()})"
                 ".catch(function(){})},15000)</script>")
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(item['name'])}</title>{theme.HEAD}<style>{CSS}{css}</style>{_class_style()}</head>"
            f"<body class='has-side'>{theme.sidebar(nav + '</div>', who=character_menu(), foot=lang_switch())}"
            f'<iframe src="{src}" title="{e(item["name"])}" onload="{NO_TOPBAR}"></iframe>{watch}</body></html>').encode()


def _boss_link(item: dict) -> str:
    """The boss page of a prepared boss (assignments, raid, options), from its name."""
    try:
        from paf.corpus.template import _slug

        encs = _encounters()
    except Exception:  # noqa: BLE001 - the link is a convenience
        return ""
    enc = next((x for x in encs if item["boss"] == _slug(x.name)), None)
    return f"/boss?boss={enc.id}&difficulty={item['difficulty']}" if enc else ""


def has_credentials() -> bool:
    """An API key of the player's, or their Warcraft Logs login (paf.wcllogin)."""
    import os

    from paf import wcllogin

    return bool(os.environ.get("WCL_CLIENT_ID") and os.environ.get("WCL_CLIENT_SECRET")) or wcllogin.logged_in()


CONNECT_JS = """<script>
(function(){
document.querySelectorAll('.wcl-connect').forEach(function(box){
  var b = box.querySelector('button'), say = box.querySelector('.wcl-say'), timer = null;
  function poll(){ fetch('/wcl/status').then(function(r){ return r.json(); }).then(function(j){
    if (j.status === 'ok') { clearInterval(timer); say.textContent = 'Connected.';
      var ev = new CustomEvent('wcl-connected', {cancelable: true});
      if (box.dispatchEvent(ev)) location.reload(); }
    else if (j.status === 'error') { clearInterval(timer); timer = null; b.disabled = false; say.textContent = j.error || 'Not connected: try again.'; }
  }).catch(function(){}); }
  b.addEventListener('click', function(){
    b.disabled = true; say.textContent = '';
    fetch('/wcl/login', {method: 'POST'}).then(function(r){ return r.json(); }).then(function(j){
      if (!j.ok) { b.disabled = false; say.textContent = j.error; return; }
      say.innerHTML = 'Log in on the Warcraft Logs page that just opened in your browser, then come back here. '
        + '<a target="_blank" rel="noopener">Open it again</a>';
      say.querySelector('a').href = j.url;
      if (!timer) timer = setInterval(poll, 1500);
    }).catch(function(){  // the answer was lost, the login may have started: watch it anyway
      b.disabled = false; if (!timer) timer = setInterval(poll, 1500); });
  });
});
})();
</script>"""


def connect_block(lead: bool = True, ghost: bool = False) -> str:
    """"Connect with Warcraft Logs" (paf.wcllogin): one click in the player's browser instead of an API key.
    Empty when this build has no public client."""
    from paf import wcllogin

    if not wcllogin.available():
        return ""
    text = ("<p>The app reads the top players' logs through <b>your</b> Warcraft Logs account: log in once, in "
            "your browser. Free; the app only reads public logs, nothing is posted.</p>" if lead else "")
    cls = "btn ghost" if ghost else "btn go"
    return (f"<div class='wcl-connect'>{text}<button type='button' class='{cls}'>Connect with Warcraft Logs</button>"
            f"<p class='wcl-say small muted' role='status'></p></div>{CONNECT_JS}")


def simc_block() -> str:
    """On first launch the app downloads SimulationCraft by itself: say so until it is there."""
    from paf.simc_install import simc_status

    state = simc_status()
    if not state:
        return ""
    if state == "downloading":
        return ('<p class="notice small"><b>First launch:</b> SimulationCraft (about 100 MB) is downloading in the '
                'background. You can connect to Warcraft Logs meanwhile; reload this page in a minute.</p>')
    return f'<p class="notice small">{e(state)} <a href="/tool/setup">Try again</a></p>'


def credentials_block(error: str = "") -> str:
    from paf import wcllogin

    err = f'<p class="notice">{e(error)}</p>' if error else ""
    return f"""<div class="card step"><div class="num">0</div><div class="body">
<h3>Connect to Warcraft Logs <span class="pill">once</span></h3>{connect_block()}
{"<details><summary>Or use your own API key</summary>" if wcllogin.available() else ""}
<p class="small">prep-a-fight reads the top players' logs with <b>your own</b> free Warcraft Logs API key (each player
has an hourly quota, so the key is not shared).</p>
<ol class="small">
<li>Log in on <a href="https://www.warcraftlogs.com/api/clients" target="_blank" rel="noopener">warcraftlogs.com/api/clients</a>
and click <b>Create Client</b>.</li>
<li>Name: anything (e.g. <code>prep-a-fight</code>). Redirect URL: <code>http://localhost</code>. Leave "Public Client"
unticked.</li>
<li>Copy the <b>Client ID</b> and the <b>Client Secret</b> here.</li></ol>{err}
<form method="post" action="/credentials" class="row"><input name="id" class="key-in" placeholder="Client ID" aria-label="Client ID"
required><input name="secret" class="key-in" type="password" placeholder="Client Secret" aria-label="Client Secret" required>
<button>Save and test</button></form>
<p class="tiny muted">Saved on this computer only, in {e(str(data_dir() / '.env'))}.</p>
{"</details>" if wcllogin.available() else ""}</div></div>"""


def home(error: str = "") -> bytes:
    from paf.profile import parse_simc_export

    prof = _profile_path()
    loaded = None
    if prof.is_file():
        loaded = parse_simc_export(prof.read_text(encoding="utf-8-sig"))
    paste = """<form method="post" action="/profile"><textarea name="simc"
placeholder="In game: type /simc, then Ctrl+A, Ctrl+C, and paste here"></textarea>
<p><button>Load this character</button></p></form>"""
    if loaded is not None:
        from paf.profile import role

        warn = ("" if role(loaded) == "damage" else
                f'<p class="notice small">{e(loaded.spec.title())} is a {role(loaded)} spec: its prep comes from the '
                f'logs of the top {role(loaded)}s (what they face, when they press their cooldowns, their talents and '
                f'trinkets); SimulationCraft does not sim {"healing" if role(loaded) == "healer" else "survival"}, '
                f'so there are no gear sims.</p>')
        character = (f"""<p><b>{e(loaded.name)}</b> <span class="pill">{e(loaded.spec)} {e(loaded.class_name)}</span>
<span class="pill">{len(loaded.candidates)} items in bags</span></p>{warn}
<details><summary>Load another character or an updated export</summary>{paste}</details>""")
    else:
        character = paste
    encs = _encounters()
    options = "".join(f'<option value="{x.id}">{e(x.name)}</option>' for x in encs)
    diff = settings.get("difficulty")
    diffs = "".join(f'<option{" selected" if d == diff else ""}>{d}</option>' for d in settings.DIFFICULTIES)
    boss_form = (f"""<form method="get" action="/boss" class="row">
<select name="boss" aria-label="Boss">{options}</select><select name="difficulty" aria-label="Difficulty">{diffs}</select>
<button>Continue</button></form>"""
                 if encs else '<p class="muted">Connect to Warcraft Logs first (step 0).</p>' if not has_credentials()
                 else '<p class="muted">Warcraft Logs did not answer: check your connection, then reload.</p>')
    creds = simc_block() + (credentials_block(error) if not has_credentials() or error else "")
    g, gs, gr = settings.get("guild"), settings.get("guild_server"), settings.get("guild_region")
    regions = "".join(f'<option{" selected" if r == gr else ""}>{r}</option>'
                      for r in settings.SETTINGS["guild_region"].choices)
    guild_state = f'<span class="pill">{e(g)}</span>' if g else '<span class="pill">optional</span>'
    guild_step = f"""<div class="card step"><div class="num">{{n}}</div><div class="body">
<h3>Your raid {guild_state}</h3>
<p class="small muted">Your guild's latest public log gives your raid's composition and DPS: the prep then tells you
whether the others cover the adds (stay on the boss) or you should pad them.</p>
<form method="post" action="/guild" class="row"><input name="guild" placeholder="Guild name" value="{e(g)}">
<input name="server" placeholder="Server" value="{e(gs)}"><select name="region" aria-label="Region">{regions}</select>
<button class="btn ghost">Save</button></form></div></div>"""
    guild = guild_step.replace("{n}", "3")  # after 1 your character, 2 the boss
    if loaded is not None and encs and has_credentials() and not error:  # ready: one big thing to do
        # in the home's fold the boss is not a step: your character (1), your raid (2)
        return page("prep-a-fight", simple_home(loaded, encs, character, guild_step.replace("{n}", "2"), creds))
    body = f"""<h1>Prepare a boss fight</h1>
<p class="lead">The top players' logs, your character and SimulationCraft: your plan for this fight.</p>
{prepared_block()}
<h2>New prep</h2>{creds}
<div class="card step"><div class="num">1</div><div class="body"><h3>Your character</h3>{character}</div></div>
<div class="card step"><div class="num">2</div><div class="body"><h3>The boss</h3>{boss_form}</div></div>
{guild}"""
    return page("prep-a-fight", body)


def _class_style() -> str:
    """The active character's class color for the whole app (paf.theme.class_accent)."""
    from paf import characters

    try:
        cur = next((c for c in characters.all_characters() if c.current), None)
    except Exception:  # noqa: BLE001 - a color never breaks a page
        return ""
    return theme.class_accent(cur.class_name) if cur else ""


def character_menu() -> str:
    """The active character next to the brand, on every page: the whole app is about it. Its menu switches to another
    character (staying on the page) or adds one."""
    from paf import characters, icons

    try:
        chars = characters.all_characters()
    except Exception:  # noqa: BLE001 - a menu never breaks a page
        return ""
    cur = next((c for c in chars if c.current), None)
    if cur is None:
        return '<a class="who-add" href="/characters#add">+ Add your character</a>'

    def ic(c) -> str:
        return icons.img(icons.CLASS_ICON.format(cls=c.class_name.lower()), "medium", "who-ic")
    back = "this.form.back.value=location.pathname+location.search"
    others = "".join(
        f'<form method="post" action="/character/select"><input type="hidden" name="slug" value="{e(c.slug)}">'
        f'<input type="hidden" name="back" value="/"><button onclick="{back}">{ic(c)}<span><b>{e(c.name)}</b>'
        f'<small>{e(c.spec.title())} {e(c.class_name.title())}</small></span></button></form>'
        for c in chars if not c.current)
    return (f'<details class="who"><summary>{ic(cur)}<span><b>{e(cur.name)}</b><small>{e(cur.spec.title())} '
            f'{e(cur.class_name.title())}</small></span><span class="who-caret">&#9662;</span></summary>'
            f'<div class="who-menu">{others}<a href="/characters#add">+ Add a character</a>'
            f'<a href="/characters">Manage your characters</a></div></details>')


def characters_strip() -> str:
    """Your other characters, one click to switch; and a new one (its /simc export)."""
    from paf import characters, icons

    others = [c for c in characters.all_characters() if not c.current]
    chips = "".join(
        f'<form method="post" action="/character/select" class="ch"><input type="hidden" name="slug" value="{e(c.slug)}">'
        f'<button title="{e(c.spec.title())} {e(c.class_name.title())}">'
        f'{icons.img(icons.CLASS_ICON.format(cls=c.class_name.lower()), "medium", "ch-ic")}<span>{e(c.name)}'
        f'<small>{e(c.spec.title())}</small></span>'
        f'</button></form>' for c in others)
    add = '<a class="ch-new" href="/characters#add">+ Add a character</a>'
    return f'<div class="chars">{chips}{add}</div>'


ADD_FORM = ('<form method="post" action="/profile" class="add-form"><p class="add-help">In game, on that character: '
            'type <code>/simc</code>, then Ctrl+A, Ctrl+C, and paste here. Paste it again after a gear change to '
            'update it.</p><textarea name="simc" id="simc-box" required placeholder="Paste the /simc export here"></textarea>'
            '<p><button class="btn go">Add this character</button></p></form>')


def characters_page() -> str:
    """All your characters: play one, update its export, remove it; and add a new one."""
    from paf import characters, icons, lastraid

    auto = lastraid.ticked()
    cards = ""
    for c in characters.all_characters():
        logs = (f'<form method="post" action="/character/autologs" class="cc-logs"><input type="hidden" name="slug" '
                f'value="{e(c.slug)}"><input type="hidden" name="on" value="{"0" if c.slug in auto else "1"}">'
                f'<label><input type="checkbox"{" checked" if c.slug in auto else ""} onchange="this.form.submit()"> '
                f'<span>Check this character&#39;s last raid when the app starts (shown on <a href="/reclear">Reclear'
                f'</a>)</span>'
                f'</label></form>')
        ic = icons.img(icons.CLASS_ICON.format(cls=c.class_name.lower()), "large", "cc-ic")
        badge = ('<span class="muted small">from a log: no bags</span>' if c.imported else
                 f'<span class="muted small">{c.bags} items in bags</span>')
        play = ('<span class="cc-on">Playing now</span>' if c.current else
                f'<form method="post" action="/character/select"><input type="hidden" name="slug" value="{e(c.slug)}">'
                f'<button class="btn ghost">Play this character</button></form>')
        cards += (f'<div class="ccard{" on" if c.current else ""}">{ic}<div class="cc-txt"><b>{e(c.name)}'
                  f'{(" <small class=muted>" + e(c.realm) + "</small>") if c.realm else ""}</b>'
                  f'<span class="cc-spec">{e(c.spec.title())} {e(c.class_name.title())}</span><span>{badge} '
                  f'<span class="muted small">&middot; updated <span>{ago(c.mtime)}</span></span></span></div><div class="cc-act">{play}'
                  f'<a class="btn ghost" href="#simc-box" onclick="setTimeout(function(){{document.getElementById(\'simc-box\').focus()}},50)">Paste a new export</a>'
                  f'<details class="rm"><summary class="cc-rm">Remove</summary><div class="rm-ask">'
                  f'<span>Remove this character? Its /simc export is deleted.</span>'
                  f'<form method="post" action="/character/remove"><input type="hidden" name="slug" value="{e(c.slug)}">'
                  f'<button class="btn danger">Yes, remove it</button></form>'
                  '<button type="button" class="btn ghost" onclick="this.closest(\'details\').open=false">Keep it'
                  f'</button></div></details></div>{logs}</div>')
    empty = "" if cards else "<p class='muted'>No character yet: add your first one below.</p>"
    cur = next((c for c in characters.all_characters() if c.current), None)
    lead = (f"You play <b>{e(cur.name)}</b>, {e(cur.spec.title())} {e(cur.class_name.title())}"
            + (f" ({e(cur.realm)})" if cur.realm else "") + ". Switch in one click; paste a new /simc export after a "
            "gear change." if cur else "One /simc export per character: switch in one click.")
    have = {c.name.lower() for c in characters.all_characters()}
    from paf import onboarding, wcllogin

    mine = [x for x in onboarding.account_characters() if x[0].lower() not in have]
    acc = ("<p class='add-help'>From your Warcraft Logs account, in one click (their latest logged boss fight gives "
           "their gear and talents, no bags):</p><div class='acc-add'>" + "".join(
               f"<form method='post' action='/character/import'><input type='hidden' name='name' value='{e(n)}'>"
               f"<input type='hidden' name='server' value='{e(sv)}'><input type='hidden' name='region' value='{e(rg)}'>"
               f"<button class='btn ghost'>Add {e(n)} <small>{e(sv)}-{e(rg.upper())}</small></button></form>"
               for n, sv, rg in mine) + "</div><p class='add-help'>Or, with your bags:</p>") if mine else (
        "")
    after = ("<p class='add-help'>Faster, without bags: <a href='/settings'>connect Warcraft Logs</a> and add your "
             "account's characters in one click.</p>") if not mine and wcllogin.available() and not wcllogin.logged_in() \
        else ""
    return (f"<h1>Your characters</h1><p class='lead'>{lead}</p><div class='ccards'>{cards}</div>{empty}"
            f"<h2 id='add'>Add a character</h2>{acc}{ADD_FORM}{after}")


DIFF_SHAPES = (("normal", "tri"), ("heroic", "sq"), ("mythic", "penta"))  # WoW's green, blue, purple


def journal_order(encs) -> list:
    """The bosses in the Encounter Journal's order (the raid's order); as given when the Journal cannot be had."""
    try:
        from paf.bossimg import journal

        _portraits, order = journal()
    except Exception:  # noqa: BLE001 - offline
        order = {}
    return sorted(encs, key=lambda x: order.get(x.id, (1 << 30, 0)))


def fresh_bosses(encs, difficulty: str, class_name: str, spec: str) -> set[int]:
    """The bosses with a prep sheet of this week (made after the last reset) at this difficulty for this spec."""
    from datetime import UTC, datetime

    from paf import pack
    from paf.corpus.template import _slug

    mine = f"{spec}-{class_name}".lower().replace(" ", "-")
    done = {x["key"]: x for x in prepared()}
    out = set()
    for x in encs:
        item = done.get(f"{_slug(x.name)}-{difficulty}-{mine}")
        if item and "prep" in item["files"] and not pack.is_stale(
                datetime.fromtimestamp(item["mtime"], UTC).isoformat()):
            out.add(x.id)
    return out


def queue_strip(difficulty: str) -> str:
    """Above the raid board (issue #21): "Prepare the whole raid", or where the queue is; it updates itself."""
    from paf import characters, raidqueue

    q = raidqueue.load()
    if raidqueue.active(q):
        ready, total, now = raidqueue.progress(q)
        pct = round(100 * ready / total) if total else 0
        word = "boss" if total == 1 else "bosses"
        head = (f"Preparing your raid: <b>{ready} of {total}</b> {word} ready" if ready < total else
                f"Your raid is ready: <b>{total} {word}</b>")
        doing = ""
        if now:
            doing = (f"Full analysis of {e(now['name'])} in the background: the sheet updates by itself"
                     if now["pass"] == "full" else f"Now: {e(now['name'])}")
        return (f"<div class='rq on' id='raidq' role='status' data-ready='{ready}'><div class='rq-txt'>"
                f"<span class='rq-head'>{head}</span><span class='rq-now'>{doing}</span>"
                "<small>You can close the app: it keeps going from the notification area and tells you when your "
                f"raid is ready.</small></div><span class='rq-bar' aria-hidden='true'><span style='width:{pct}%'>"
                "</span></span><form method='post' action='/raid/stop'><button class='btn ghost'>Stop</button>"
                "</form></div>")
    note = ""
    if q and q.get("character") == characters.current_slug() and any(i["status"] == "waiting" for i in q["items"]):
        note = ("<small>Paused when you switched characters: prepare again to go on.</small>"
                if q.get("paused") == "character" else
                "<small>Stopped: prepare again to go on, the bosses already prepared stay.</small>")
    return (f"<div class='rq' id='raidq'><div class='rq-txt'><span class='rq-head'>Prepare the whole raid in one "
            f"go</span><span class='rq-now'>Every boss, one after the other, while you do something else.</span>"
            f"{note}</div><a class='btn ghost' href='/raid/prepare?difficulty={e(difficulty)}'>Prepare the whole raid</a>"
            "</div>")


QUEUE_JS = """<script>(function(){var s=document.getElementById('raidq');if(!s||!s.classList.contains('on'))return;
setInterval(function(){fetch('/raid/strip').then(function(r){return r.text()}).then(function(h){
var t=document.createElement('div');t.innerHTML=h;var n=t.firstElementChild;if(!n)return;
if(n.dataset.ready!==s.dataset.ready||!n.classList.contains('on')){location.reload();return}
s.replaceWith(n);s=n}).catch(function(){})},8000)})();</script>"""


def reclear_page() -> str:
    """After a raid night (issue #24): the character's last log read against the top players of the spec, boss by
    boss (paf.lastraid), then the tools that dig into one log."""
    from paf import characters, lastraid, workshop

    slug = characters.current_slug()
    card = lastraid.card(slug) if slug else ""
    if card:
        last = card + lastraid.CARD_JS
    else:
        last = ("<section class='rc-empty'><p>It shows here what cost you the most on each boss. Raided tonight and "
                "the log is up on Warcraft Logs? Look now:</p>"
                "<form method='post' action='/lastraid/again'><button class='btn go'>Look for my last raid now</button>"
                "</form></section>")
    lead = ("Your last raid, read against the top players of your spec: what cost you the most, boss by boss, and "
            "where to look in the log." if card else "No raid of yours read yet: the app looks for your character's "
            "latest log of the current raid each time it starts.")
    return (f"<div class='rc'><header class='rc-head'><h1>Reclear</h1><p class='lead'>{lead}</p>"
            f"</header>{last}<h2>Dig deeper into your play</h2><p class='muted'>Each one starts from your raid's latest "
            f"log; paste another link to read that one instead.</p>"
            f"{workshop.cards(('rotation', 'diff', 'wipe'))}<p class='muted'>The raid's pulls, player by player, and "
            f"your raid night are on <a href='/raidlead'>Raid lead</a>.</p></div>{workshop.CSS}")


def raid_prepare_page(difficulty: str) -> bytes:
    """Before the whole raid is queued: the bosses to prepare, those already prepared this week, how long until
    every boss has its sheet (the quota shared), and the button."""
    from datetime import datetime, timedelta

    from paf import raidqueue
    from paf.corpus import db
    from paf.wcl import WCLClient

    if difficulty not in settings.DIFFICULTIES:
        difficulty = settings.get("difficulty")
    encs = journal_order(_encounters())
    if not encs:
        return page("Prepare the whole raid", "<h1>Prepare the whole raid</h1><p class='lead'>The raid's bosses "
                                              "come from Warcraft Logs: add your key in <a href='/settings'>Settings"
                                              "</a> first.</p>")
    if raidqueue.active(raidqueue.load()):
        return page("Prepare the whole raid", "<h1>Your raid is being prepared</h1><p class='lead'>Follow it on the "
                                              "<a href='/#raidq'>home page</a>, or stop it there to start another "
                                              "one.</p>")
    cls, spec = settings.get("class"), settings.get("spec")
    ready = fresh_bosses(encs, difficulty, cls, spec)
    from paf.corpus.template import _slug

    sheets = {x["key"] for x in prepared() if "prep" in x["files"]}  # an older sheet: "to redo", as on Home
    mine_key = f"{spec}-{cls}".lower().replace(" ", "-")
    old = {x.id for x in encs if f"{_slug(x.name)}-{difficulty}-{mine_key}" in sheets}
    todo = [x for x in encs if x.id not in ready]
    diffs = "".join(f'<label class="seg"><input type="radio" name="difficulty" value="{d}"{" checked" if d == difficulty else ""} '
                    f'onchange="this.form.submit()"><span>{e(DIFF_LABELS.get(d, d))}</span></label>'
                    for d in settings.DIFFICULTIES if d != "lfr")
    rows = "".join(f"<li class='{'ok' if x.id in ready else 'todo'}'><b>{e(x.name)}</b>"
                   f"<span>{'prepared this week' if x.id in ready else 'to redo' if x.id in old else 'to prepare'}"
                   "</span></li>" for x in encs)
    if not todo:
        plan = "<p class='lead'>Every boss is prepared for this week at this difficulty.</p><p><a class='btn' href='/'>Back home</a></p>"
    else:
        est = raidqueue.estimate(db.connect(), todo, settings.DIFFICULTIES[difficulty], cls, spec, WCLClient())
        at = (datetime.now() + timedelta(minutes=est.minutes)).strftime("%H:%M")
        where = []
        if est.collect:
            where.append(f"{est.collect} {'boss downloads' if est.collect == 1 else 'bosses download'} the top kills "
                         f"from Warcraft Logs first")
        if est.packs:
            where.append(f"{est.packs} {'comes' if est.packs == 1 else 'come'} from a prep pack")
        wait = f" It includes about {round(est.wait)} min waiting for your Warcraft Logs quota." if est.wait >= 1 else ""
        plan = (f"<div class='rq-when'><b>Ready around {at}</b><span>About {max(1, round(est.minutes))} min for "
                f"{len(todo)} {'boss' if len(todo) == 1 else 'bosses'}{': ' + ', '.join(where) if where else ''}."
                f"{wait}</span></div>"
                "<p>Go and do something else: you can close the app, it keeps going from the notification area and "
                "tells you when your raid is ready. Then the full analysis of each boss goes on in the background "
                "(it takes longer: the Warcraft Logs quota) and the sheets update by themselves.</p>"
                f"<form method='post' action='/raid/prepare'><input type='hidden' name='difficulty' value='{e(difficulty)}'>"
                f"<button class='btn big'>Prepare {len(todo)} {'boss' if len(todo) == 1 else 'bosses'}</button></form>")
    body = (f"<h1>Prepare the whole raid</h1><p class='lead'>Every boss for {e(spec)} {e(cls)}, one after the other. "
            f"The bosses already prepared this week are kept.</p><form method='get' action='/raid/prepare' "
            f"class='segs' role='radiogroup' aria-label='Difficulty'>{diffs}</form>"
            f"<div class='rq-cols'><ol class='rq-list'>{rows}</ol><div class='rq-plan'>{plan}</div></div>")
    return page("Prepare the whole raid", body)



# a boss's popup stays on screen whatever row the boss is on (the raid board wraps on narrow windows and phones)
RB_JS = """<script>document.querySelectorAll('.rb-boss').forEach(function(b){function fit(){var p=b.querySelector('.rb-pop');
if(!p)return;p.style.marginLeft='0px';var r=p.getBoundingClientRect(),w=document.documentElement.clientWidth,m=12,dx=0;
if(r.left<m)dx=m-r.left;else if(r.right>w-m)dx=w-m-r.right;p.style.marginLeft=dx+'px'}
function soon(){requestAnimationFrame(fit)}b.addEventListener('pointerenter',soon);b.addEventListener('focusin',soon)});
</script>"""


def raid_board(encs, class_name: str, spec: str) -> str:
    """The raid at a glance for the active character: a row of the bosses' portraits (grey while not prepared at any
    difficulty); hovering or tapping one opens, under it, its three difficulties, like a talent's tooltip: a green
    triangle (normal), a blue square (heroic), a purple pentagon (mythic), each prepared (since when), to redo (made
    before this week's reset), in progress or not yet, and a link straight to the sheet or the prep."""
    from datetime import UTC, datetime

    from paf import loading, pack
    from paf.corpus.template import _slug

    if not encs:
        return ""
    try:
        from paf.bossimg import journal

        portraits, order = journal()
    except Exception:  # noqa: BLE001 - offline: no portraits, the names stay, the raid's order
        portraits, order = {}, {}
    encs = sorted(encs, key=lambda x: order.get(x.id, (1 << 30, 0)))  # the Encounter Journal's order
    mine = f"{spec}-{class_name}".lower().replace(" ", "-")
    done = {x["key"]: x for x in prepared()}
    from paf import raidqueue

    rq = raidqueue.load()
    queued = {d: raidqueue.waiting(rq, d) for d, _shape in DIFF_SHAPES}
    running = {}
    for jid, job in loading.running_preps():
        args = job["args"]
        diff = args[args.index("--difficulty") + 1] if "--difficulty" in args else settings.get("difficulty")
        running[(args[1] if len(args) > 1 else "", diff)] = (jid, job)

    def portrait(x, cls: str = "") -> str:
        if x.id not in portraits:
            return f"<span class='rb-img none {cls}'>{e(x.name[:1])}</span>"
        # the Journal's portrait, served by the app (paf.bossimg); the initial shows if it cannot be had
        return (f"<span class='rb-img none {cls}'>{e(x.name[:1])}</span><img class='rb-img {cls}' "
                f"src='/bossimg/{x.id}.png' alt='' loading='lazy' onerror=\"if(this.dataset.r)this.remove();"
                f"else{{this.dataset.r=1;this.src+='?r=1'}}\">")  # one retry, then the initial
    items = ""
    for i, x in enumerate(encs, 1):
        states, ready, here = "", False, ""
        for diff, shape in DIFF_SHAPES:
            key = f"{_slug(x.name)}-{diff}-{mine}"
            item = done.get(key)
            run = running.get((str(x.id), diff))
            if run:
                log = run[1]["log"].read_text(encoding="utf-8", errors="replace") if run[1]["log"].is_file() else ""
                pct, _ = loading.percent(log, time.time() - run[1]["started"])
                href, state, word = f"/job/{e(run[0])}", "run", f"{pct}%"
            elif x.id in queued[diff]:
                href, state, word = "#raidq", "wait", "queued"
            elif item and "prep" in item["files"]:
                stale = pack.is_stale(datetime.fromtimestamp(item["mtime"], UTC).isoformat())
                href, state, word = f"/view/{e(key)}", "old" if stale else "ok", "to redo" if stale else ago(item["mtime"])
                ready = ready or not stale
            else:
                href, state, word = f"/boss?boss={x.id}&amp;difficulty={diff}", "no", "prepare"
            if diff == settings.get("difficulty"):  # said under the portrait, without pointing at it
                said = {"no": "not prepared", "ok": f"ready {word}", "old": "redo"}.get(state, word)
                here = f"<small class='rb-st {state}'>{said}</small>"
            states += (f"<a class='rb-d {state}' href='{href}'><span class='rb-frame {shape}'><span class='rb-in'>"
                       f"{portrait(x)}</span></span><b>{e(DIFF_LABELS.get(diff, diff))}</b><small>{word}</small></a>")
        items += (f"<div class='rb-boss{'' if ready else ' grey'}' tabindex='0'><span class='rb-face'>{portrait(x)}"
                  f"<span class='rb-n'>{i}</span></span><span class='rb-name'>{e(x.name)}</span>{here}"
                  f"<div class='rb-pop' role='group' aria-label='{e(x.name)}'><b class='rb-title'>{e(x.name)}</b>"
                  f"<div class='rb-ds'>{states}</div></div></div>")
    return (f"<h2 class='h-mine'>Your raid, boss by boss</h2>"
            f"<p class='rb-legend'>Under each boss, where it stands in {e(DIFF_LABELS.get(settings.get('difficulty'), ''))} "
            "this week. Click a boss for its three difficulties, then open a sheet or start a prep.</p>"
            f"<div class='rb-row'>{items}</div>{QUEUE_JS}{RB_JS}")  # the queue strip: in the hero, this week


def simple_home(loaded, encs, character: str, guild: str, creds: str) -> str:
    """The home page once the app is set up (issue #13): your character, one big "prepare a boss", your bosses."""
    from paf import i18n, icons, names

    if i18n.language() != "en":  # a new player's boss list in their language, before any prep
        names.boss_names(i18n.wow_locale())

    diff = settings.get("difficulty")
    encs = journal_order(encs)  # the list in the raid's order, like the board
    ready = fresh_bosses(encs, diff, loaded.class_name, loaded.spec)
    nxt = next((x for x in encs if x.id not in ready), None)  # the list opens on the first boss still to prepare
    options = "".join(f'<option value="{x.id}"{" selected" if nxt and x.id == nxt.id else ""}>{e(x.name)}</option>'
                      for x in encs)
    where = e(DIFF_LABELS.get(diff, diff))
    if nxt is not None:  # the next boss to prepare: no list to scroll, the board below picks another one
        pick = (f'<input type="hidden" name="boss" value="{nxt.id}"><p class="start-next">'
                + (f'{len(ready)} of {len(encs)} bosses ready this week. ' if ready else '')
                + f'Next to prepare: <b>{e(nxt.name)}</b>.</p><p class="start-say">For another boss, click it in your raid below.</p>')
    else:
        pick = ((f'<p class="start-say">Every boss is ready this week in {where}: pick one to prepare again.</p>'
                 if encs else "") + f'<select name="boss" aria-label="Boss" class="big">{options}</select>')
    week = (f'<aside class="hero-week"><h2>This week in {where}</h2><p class="hw-n"><b>{len(ready)}</b> of '
            f'{len(encs)} bosses ready</p>{queue_strip(diff)}</aside>') if encs else ""
    diffs = "".join(f'<label class="seg"><input type="radio" name="difficulty" value="{d}"{" checked" if d == diff else ""}>'
                    f'<span>{e(DIFF_LABELS.get(d, d))}</span></label>' for d in settings.DIFFICULTIES if d != "lfr")
    ic = icons.img(icons.CLASS_ICON.format(cls=loaded.class_name.lower()), "large", "me-ic")
    items = prepared()
    board = raid_board(encs, loaded.class_name, loaded.spec)
    try:
        from paf import characters, lastraid

        last = lastraid.card(characters.current_slug())
        last = last + lastraid.CARD_JS if last else ""
    except Exception:  # noqa: BLE001 - the home always shows
        last = ""
    me = f"{loaded.spec}-{loaded.class_name}".lower().replace(" ", "-")
    order = tuple(x.name for x in encs)
    own = [x for x in items if x["key"].endswith("-" + me)]  # the active character's spec first, the others after
    rest = [x for x in items if x not in own]
    mine = ((f'<h2>Your sheets as {e(loaded.spec.title())} {e(loaded.class_name.title())}</h2>'
             f'<div class="sheets">{boss_cards(own, order, spec=False)}</div>' if own else "")
            + (f'<h2>Your other specs&#39; sheets</h2><div class="sheets">{boss_cards(rest, order)}</div>' if rest else ""))
    g = settings.get("guild")
    return f"""<section class="home-hero"><form method="get" action="/boss" class="start"><h1>Prepare a boss</h1>
<p class="me">{ic}<span>for <b>{e(loaded.name)}</b>, {e(loaded.spec.title())} {e(loaded.class_name.title())}\
{(" &middot; " + e(g)) if g else ""}</span></p>{pick}
<div class="segs" role="radiogroup" aria-label="Difficulty">{diffs}</div>
<button class="btn go">Prepare <span class="go-boss">{e(nxt.name if nxt else (encs[0].name if encs else "this boss"))}</span>
&rarr;</button></form>{week}</section>
<script>(function(){{var s=document.querySelector('.start select'),b=document.querySelector('.go-boss');
if(s&&b)s.addEventListener('change',function(){{b.textContent=s.options[s.selectedIndex].text}})}})()</script>
{board}{last}{mine}"""


def boss_page(boss_id: str, difficulty: str) -> bytes:
    from paf.assigns import load_mechanics
    from paf.corpus import db
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    enc = next((x for x in raid_encounters(WCLClient()) if str(x.id) == boss_id), None)
    if enc is None:
        return page("Unknown boss", "<p>Unknown boss.</p>")
    diff = settings.DIFFICULTIES.get(difficulty, 4)
    spec = settings.get("spec")
    con = db.connect()
    kills = con.execute("SELECT COUNT(*) FROM fight WHERE encounter_id=? AND difficulty=? AND status='done'",
                        (enc.id, diff)).fetchone()[0]
    mechs = []
    if kills:
        try:
            mechs = load_mechanics(con, enc.id, diff, spec)
        except Exception:  # noqa: BLE001
            mechs = []
    current = {a.lower() for a in current_assigns(enc, difficulty)}
    if mechs:
        chips, seen = "", set()
        for m in mechs:
            if m.name.lower() in seen:  # one box per mechanic, however many times the logs list it
                continue
            seen.add(m.name.lower())
            when = ", ".join(f"{int(t // 60)}:{int(t % 60):02d}" for t in m.times[:4]) + ("…" if len(m.times) > 4 else "")
            what = "interrupt" if m.kind == "interrupt" else f"{m.players_per_kill:.0f} players hit per kill"
            cost = f", ~{m.cost:g} s of movement" if m.cost else ""
            checked = " checked" if m.name.lower() in current or m.key in current else ""
            at = f", around {e(when)}" if when else ""  # the times shown, not hidden in a tooltip
            chips += (f'<label class="chip"><input type="checkbox" name="assign" value="{e(m.name)}"'
                      f'{checked}>{e(m.name)} <span class="meta">{what}{cost}{at}</span></label>')
        label = f"{spec} {settings.get('class') or ''}".strip()  # "Subtlety Rogue", as everywhere else
        article = "an" if label[:1].lower() in "aeiou" else "a"
        assigns = (f'<p class="small muted">Tick what you handle on this fight. Timings and the movement it costs '
                   f'{article} {e(label)} come from the logs, with when each one happens.</p>'
                   f'<div class="chips">{chips}</div>')
    elif kills:
        assigns = ('<p class="muted small">The mechanics are collected during the first prep (about 2 quota points '
                   'per kill); you can tick yours afterwards.</p>')
    else:
        assigns = ('<p class="muted small">The mechanics come with the first prep&#39;s kills; you can tick yours on '
                   'the next one.</p>')
    last = prepared_link(enc, difficulty)
    from paf import bossguide
    from paf.icons import icons_for

    sections = bossguide.load(enc.id, difficulty)
    guide = journal = ""
    from paf import i18n

    if sections and i18n.language() != "en":  # the journal in the player's language, before the first prep too
        from paf import names

        try:
            names.build(enc.id, difficulty, bossguide.spell_refs(sections), i18n.wow_locale())
        except Exception:  # noqa: BLE001 - offline: the guide stays in English
            pass
    if sections:
        gicons = icons_for(bossguide.spell_refs(sections))
        from paf.profile import HEALER_SPECS, TANK_SPECS

        sp = (settings.get("spec") or "").lower()
        mine = "healer" if sp in HEALER_SPECS else "tank" if sp in TANK_SPECS else "damage"
        guide = f"<h2>The boss in 60 seconds</h2>{bossguide.summary_html(sections, mine)}"
        journal = (f"<section class='boss-journal'><h2>Every ability, from the Encounter Journal</h2><p class='adv-lede'>Timings "
                   f"and how many players are hit come from the ranked kills.</p><div class='stages'>"
                   f"{bossguide.abilities_html(sections, mechanics=mechs, icon_map=gicons, role=mine)}</div></section>")
    try:  # where the data will come from, and how long: from what will really happen (paf.estimate)
        from paf import estimate

        est = estimate.plan(con, enc.id, diff, settings.get("class"), spec, WCLClient())
    except Exception:  # noqa: BLE001 - an estimate never breaks the page
        est = None
    raid_now = current_raid(enc, difficulty)
    g = settings.get("guild")
    raid_said = f"the latest public log of {g}" if g else ""
    nxt = "<button type='button' class='btn go next'>Next &rarr;</button>"
    back = "<button type='button' class='btn ghost prev'>&larr; Previous step</button>"  # not the sidebar's Back
    no_adds = False  # the prep pack knows the fight: a boss without adds has nothing to pad
    try:
        from paf import pack

        pk = pack.load(enc.id, diff, settings.get("class"), spec)
        no_adds = pk is not None and not pk.fight.add_waves
    except Exception:  # noqa: BLE001 - no pack: the choice stays offered
        pass
    if no_adds:
        goal_html = ('<section class="ob-step" data-step="goal"><h2><span class="vh">Step 1 of 4: </span>Your goal on this boss</h2>'
                     '<p>No adds on this boss: the prep plays for <b>boss damage</b>.</p>'
                     '<input type="hidden" name="goal" value="boss">'
                     f'<div class="ob-actions">{nxt}</div></section>')
    else:
        goal_html = ('<section class="ob-step" data-step="goal"><h2><span class="vh">Step 1 of 4: </span>Your goal on this boss</h2>'
                     '<div class="goals">' + """<label class="goal"><input type="radio" name="goal" value="boss"><span><b>Boss damage</b>
<small>Progress: your raid lead wants everyone on the boss. Cooldowns and gear aim at the boss.</small></span></label>
<label class="goal"><input type="radio" name="goal" value="total"><span><b>Pad the adds</b>
<small>Your job is the adds, or you farm for parses: cooldowns and gear for total damage.</small></span></label>
<label class="goal"><input type="radio" name="goal" value="auto" checked><span><b>Let my raid decide</b>
<small>The prep reads your raid's log: if the others already cover the adds, you stay on the boss.</small></span></label>
""" + f'</div><div class="ob-actions">{nxt}</div></section>')
    body = f"""<div class="boss-cols"><div class="boss-main"><h1>{e(enc.name)} {diff_pill(difficulty)}</h1>
<p class="lead">{boss_line(enc, difficulty)}{e(est.lead) if est else ""}</p>{f'<p class="last-sheet">{last.strip()}</p>' if last.strip() else ""}
<form method="post" action="/prep" class="ob story" data-boss="{enc.id}-{e(difficulty)}">
<input type="hidden" name="boss" value="{enc.id}"><input type="hidden" name="difficulty" value="{e(difficulty)}">
<div class="ob-where" aria-hidden="true"><ol class="ob-dots"><li></li><li></li><li></li><li></li></ol><span class="ob-n">Step <b>1</b> of 4</span></div>
{goal_html}
<section class="ob-step" data-step="assigns"><h2><span class="vh">Step 2 of 4: </span>Are you assigned to something?</h2>{assigns}
<p class="small muted ob-note">Each assignment is simulated: its moves and its downtime change your cooldown plan and your gear.</p>
<div class="ob-actions">{back}{nxt}</div></section>
<section class="ob-step" data-step="raid"><h2><span class="vh">Step 3 of 4: </span>Your raid</h2>
<label class="ob-field">Your raid's log<input name="raid" type="url" value="{e(raid_now)}" aria-describedby="raid-help"
placeholder="https://www.warcraftlogs.com/reports/..."></label>
<p class="small muted raid-help" id="raid-help" aria-live="polite">{e(raid_hint(no_adds))}</p>
<div class="ob-actions">{back}{nxt}</div></section>
<section class="ob-step" data-step="go"><h2><span class="vh">Step 4 of 4: </span>Ready to prepare</h2>
<ul class="recap">
<li data-if="goal=boss">For <b>boss damage</b>.</li><li data-if="goal=total">For <b>total damage</b> (pad the adds).</li>
<li data-if="goal=auto">Your raid's log decides between boss damage and padding.</li>
<li data-if="assigns"><span class="recap-assigns-lab">With your assignments:</span> <b class="recap-assigns"></b></li>
<li data-if="no-assigns">No assignment.</li>
<li data-if="raid">Your raid: <b class="recap-raid"></b></li>
<li data-if="no-raid">Your raid: <b>{e(raid_said) if raid_said else "none (the prep shows both plans)"}</b></li>
</ul>
<fieldset class="what-sim"><legend>What to sim</legend>
<label><input type="checkbox" name="gear" checked><span>Best gear from your bags, and what this boss drops for you</span></label>
<label><input type="checkbox" name="optimize" checked><span>Ideal cooldown plan{" for boss damage" if no_adds else " for your goal"}
<span class="muted small">(the slowest part: 20 to 40 min the first time; the estimate above comes from this computer's last preps, faster when their sims are reused)</span></span></label><p class="small muted sim-none" hidden>Both off: the prep still gives the fight view, the boss journal and your talents, without a gear or cooldown plan.</p></fieldset>
<div class="ob-actions">{back}<button class="btn go" aria-describedby="go-why">Prepare this fight &rarr;</button><span class="go-why" id="go-why" hidden>Fix
the raid log link (step 3) or leave it empty first.</span></div>
<p class="small muted ob-note">Runs on your computer; you can follow it live.</p></section>
</form></div>
{(f"<aside class='boss-guide'>{guide}</aside>") if guide else ""}</div>{journal}
{_story_css()}{STORY_JS}
<h2>What you know that the logs cannot</h2>
<p class="adv-lede">Two plain-text notes the next prep of this boss reads: your own fight plan, and what you know about the
boss itself. Both are optional; the prep works from the logs without them.</p>
<section class="adv"><h3>Your fight plan: your own movements, Bloodlust, Power Infusion</h3>
{plan_block(enc, difficulty)}</section>
<section class="adv"><h3>What you know about this boss: damage amps, targets to ignore</h3>
{notes_block(enc, difficulty)}</section>"""
    return page(enc.name, body)


def _story_css() -> str:
    from paf.onboarding import CSS as ONBOARDING_CSS

    return "<style>" + ONBOARDING_CSS + theme.style("story") + "</style>"


STORY_JS = """<script>
(function(){
var f = document.querySelector('form.story'); if (!f) return;
var steps = [].slice.call(f.querySelectorAll('.ob-step')), dots = [].slice.call(f.querySelectorAll('.ob-dots li'));
var key = 'paf-goal:' + f.dataset.boss, at = 0;
try { var g = localStorage.getItem(key); var r = g && f.querySelector('input[name=goal][value=' + g + ']'); if (r) r.checked = true; } catch (e) {}
function recap(){
  var goal = (f.querySelector('input[name=goal]:checked') || f.querySelector('input[name=goal][type=hidden]') || {}).value || 'auto';
  var picked = [].slice.call(f.querySelectorAll('input[name=assign]:checked')).map(function(i){
    var t = i.parentNode.cloneNode(true); var m = t.querySelector('.meta'); if (m) m.remove(); return t.textContent.trim(); });
  var rf = f.querySelector('input[name=raid]'); if (rf) rf.value = rf.value.trim();  // spaces alone are an empty field
  var raid = (rf || {}).value || '';
  var badraid = raid && !/warcraftlogs[.]com[/]reports[/][A-Za-z0-9]{16}/.test(raid);
  if (badraid) raid += ' (not a Warcraft Logs report link: fix it or leave it empty)';
  else if (raid) { var m = raid.match(/reports[/]([A-Za-z0-9]{16})/), fi = raid.match(/fight=([0-9]+)/);
    raid = 'report ' + m[1].slice(0, 6) + '\u2026' + (fi ? ', pull ' + fi[1] : ''); }  // short, not the raw link
  var rli = f.querySelector('.recap-raid'); if (rli && rli.closest('li')) rli.closest('li').classList.toggle('bad', !!badraid);
  var why = f.querySelector('.go-why'); if (why) why.hidden = !badraid;  // the disabled Prepare says why, beside it
  f.querySelector('.recap-assigns').textContent = picked.join(', ');
  f.querySelector('.recap-assigns-lab').textContent = picked.length === 1 ? 'With your assignment:' : 'With your assignments:';
  f.querySelector('.recap-raid').textContent = raid;
  f.querySelectorAll('.recap [data-if]').forEach(function(li){
    var c = li.dataset.if;
    li.hidden = !(c === 'goal=' + goal || (c === 'assigns' && picked.length) || (c === 'no-assigns' && !picked.length)
                  || (c === 'raid' && raid) || (c === 'no-raid' && !raid)); });
}
function show(i, back){
  at = Math.max(0, Math.min(steps.length - 1, i));
  steps.forEach(function(s, j){ s.classList.toggle('on', j === at); s.classList.toggle('back', !!back); });
  dots.forEach(function(d, j){ d.classList.toggle('on', j <= at); });
  var n = f.querySelector('.ob-n b'); if (n) n.textContent = at + 1;
  if (steps[at].dataset.step === 'go') recap();
  var hp = steps[at].querySelector('#raid-help');  // measured once shown: it keeps that height, no button moves under a click
  if (hp) {  // the help speaks of the goal picked: the 'Let my raid decide' clause only for that goal
    if (hp.dataset.full == null) hp.dataset.full = hp.textContent;
    var g = (f.querySelector('input[name=goal]:checked') || f.querySelector('input[name=goal][type=hidden]') || {}).value || 'auto';
    var base = g === 'auto' ? hp.dataset.full : hp.dataset.full.replace(/; with "Let my raid decide".*$/, '.');
    hp.dataset.t = base; if (!f.querySelector('input[name=raid]').value.trim()) hp.textContent = base;
    if (!hp.dataset.h) { hp.dataset.h = '1'; hp.style.minHeight = hp.offsetHeight + 'px'; } }
  var h2 = steps[at].querySelector('[aria-invalid=true]') || steps[at].querySelector('input[name=raid]')
    || steps[at].querySelector('h2');  // a field in error first, the log field ready to paste into, else the heading
  if (h2) { if (h2.tagName === 'H2') h2.tabIndex = -1; h2.focus({preventScroll: true}); }  // keep the place
  var cur = steps[at]; cur.classList.add('arriving');  // a double click on Next must not tick what lands under it
  setTimeout(function(){ cur.classList.remove('arriving');
    if (document.activeElement === document.body && h2) h2.focus({preventScroll: true}); }, 450);
}
function next(){  // a field in error keeps the player on its step, with the focus on it
  var rl = steps[at].querySelector('input[name=raid]'); if (rl) rl.dispatchEvent(new Event('change'));
  var bad = steps[at].querySelector('[aria-invalid=true]'); if (bad) { bad.focus(); return; } show(at + 1); }
f.querySelectorAll('.next').forEach(function(b){ b.addEventListener('mousedown', function(ev){ ev.preventDefault(); });  // no blur shift
  b.addEventListener('click', next); });
f.addEventListener('keydown', function(ev){  // Enter in a field moves on a step; only the last step's button prepares
  if (ev.key !== 'Enter' || ev.target.tagName !== 'INPUT') return;
  ev.preventDefault(); if (steps[at].dataset.step !== 'go') next(); });  // on the last step, Enter in a box does nothing
var rl = f.querySelector('input[name=raid]'), go = f.querySelector('.ob-step[data-step=go] .btn.go');
f.querySelectorAll('input[name=gear],input[name=optimize]').forEach(function(c){ c.addEventListener('change', function(){
  var none = !f.querySelector('input[name=gear]:checked') && !f.querySelector('input[name=optimize]:checked');
  var n = f.querySelector('.sim-none'); if (n) n.hidden = !none; }); });  // both off: what the prep still gives
if (rl) ['change', 'input'].forEach(function(ev){ rl.addEventListener(ev, function(e){  // checked when the field is left
  if (e.type === 'change') rl.value = rl.value.trim();
  if (e.type === 'input' && !rl.classList.contains('bad')) return;  // while typing, only an error already shown clears
  var bad = rl.value.trim() && !/warcraftlogs[.]com[/]reports[/][A-Za-z0-9]{16}/.test(rl.value);
  rl.classList.toggle('bad', !!bad); rl.setAttribute('aria-invalid', bad ? 'true' : 'false'); if (go) go.disabled = !!bad;
  var h = document.getElementById('raid-help'); if (h) h.classList.toggle('err', !!bad); if (h) { if (h.dataset.t == null) h.dataset.t = h.textContent;
    h.textContent = bad ? 'Not a Warcraft Logs report link: paste one like https://www.warcraftlogs.com/reports/..., or leave it empty.' : (rl.value.trim() ? 'This report is read for your raid: ' + rl.value.replace(/^.*reports[/]([A-Za-z0-9]{6})[A-Za-z0-9]*/, 'report $1\u2026').replace(/[?#].*fight=([0-9]+).*/, ', pull $1').replace(/[?#].*$/, '') + '.' : h.dataset.t); } }); });
f.querySelectorAll('.prev').forEach(function(b){ b.addEventListener('mousedown', function(ev){ ev.preventDefault(); });
  b.addEventListener('click', function(){ show(at - 1, true); }); });

f.querySelectorAll('input[name=goal]').forEach(function(r){ r.addEventListener('change', function(){
  try { localStorage.setItem(key, r.value); } catch (e) {} }); });  // a goal is picked; Next moves on (keyboard-safe)
f.addEventListener('submit', function(ev){  // only the Prepare button starts a prep: never Enter in a field or box
  var go = f.querySelector('.ob-step[data-step=go] .btn.go');
  if (ev.submitter !== go || steps[at].dataset.step !== 'go' || go.disabled) { ev.preventDefault(); return; }
  var r = f.querySelector('input[name=goal]:checked');
  try { if (r) localStorage.setItem(key, r.value); } catch (e) {} });
show(0);
})();
</script>"""

def prepared_link(enc, difficulty: str) -> str:
    from paf.corpus.template import report_key

    key = report_key(enc.name, difficulty)
    item = next((x for x in prepared() if x["key"] == key), None)
    if item is None:
        return ""
    if "prep" in item["files"]:
        return f' <a href="/view/{e(key)}">Open the last prep sheet &rarr;</a>'
    return f' <a href="/view/{e(key)}">Open the top players&#39; timelines &rarr;</a>'  # a timeline alone: said so


def boss_line(enc, difficulty: str) -> str:
    """The boss page's first words: what the rebuilt fight holds (adds, the boss away), from its template."""
    from paf.corpus.template import template_path
    from paf.fight import Fight

    try:
        f = Fight.load(template_path(enc.name, difficulty))
    except (OSError, ValueError, KeyError, TypeError):
        return ""

    def mmss(t: float) -> str:
        return f"{int(t // 60)}:{int(t % 60):02d}"
    adds = sorted({mmss(w.time) for w in f.add_waves if w.scalable}, key=lambda x: tuple(map(int, x.split(":"))))
    away = [f"{mmss(w.start)} to {mmss(w.start + w.duration)}" for w in f.invulnerable]
    parts = ([f"adds at {', '.join(adds[:4])}" + (" and later" if len(adds) > 4 else "")] if adds else []) + (
        [f"the boss away {', '.join(away[:3])}"] if away else [])
    said = "; ".join(parts) if parts else "one target from the pull to the kill"
    return e(f"In a {mmss(f.duration)} kill: {said}. ")


def _plan_path(enc, difficulty: str) -> Path:
    from paf.corpus.template import template_path

    return template_path(enc.name, difficulty).with_suffix(".plan.txt")


def current_raid(enc, difficulty: str) -> str:
    from paf.plan import parse_plan

    p = _plan_path(enc, difficulty)
    try:
        return parse_plan(p.read_text(encoding="utf-8-sig")).raid if p.is_file() else ""
    except ValueError:
        return ""


def raid_hint(no_adds: bool = False) -> str:
    g = settings.get("guild")
    if no_adds:  # nothing to pad: the log says how your last pull compares
        return ((f"Left empty, the latest public log of {g} is used. " if g else "Optional. ")
                + "The log shows how your last pull compares with the top players' pulls.")
    what = ("The log shows who plays what in your raid and how your last pull compares with the top players' pulls; "
            "with \"Let my raid decide\", it also decides between padding the adds and the boss.")
    if g:
        return f"Left empty, the latest public log of {g} is used. {what}"
    return f"Optional. {what} Or set your guild once on the home page."


def write_raid(boss_id: int, difficulty: str, url: str) -> None:
    """Keep the raid log link as the `raid` line of the boss plan file."""
    from paf.corpus.template import template_path
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    enc = next((x for x in raid_encounters(WCLClient()) if x.id == boss_id), None)
    if enc is None:
        return
    p = template_path(enc.name, difficulty).with_suffix(".plan.txt")
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8-sig").splitlines() if p.is_file() else []
    lines = [line for line in lines if not line.strip().lower().startswith("raid ")]
    if url.strip():
        lines.append(f"raid {url.strip()}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def current_assigns(enc, difficulty: str) -> list[str]:
    from paf.plan import parse_plan

    p = _plan_path(enc, difficulty)
    if not p.is_file():
        return []
    try:
        return parse_plan(p.read_text(encoding="utf-8-sig")).assigns
    except ValueError:
        return []


def plan_block(enc, difficulty: str) -> str:
    """The player's own fight plan (moves, lust, PI), editable; assignments are the ticked mechanics above."""
    from paf.corpus.template import template_path
    from paf.fight import Fight
    from paf.plan import plan_template

    p = _plan_path(enc, difficulty)
    if p.is_file():
        text = _fresh_header(p.read_text(encoding="utf-8-sig"))
    elif template_path(enc.name, difficulty).is_file():
        text = plan_template(Fight.load(template_path(enc.name, difficulty)))
    else:
        return ('<p class="muted small">Available after the first prep: your own movements (a soak at 2:45, a '
                "dodge...), Bloodlust and Power Infusion timings, on top of the rebuilt fight.</p>")
    return f"""<p class="small muted">What you do on this fight that the logs cannot guess, one line each: <code>2:45 move 6</code>
(6 s of movement), <code>5:30 move 8 shift -5..+5</code> (the optimizer picks the best moment), <code>lust 0:00</code>,
<code>pi 0:20 2:30</code>, <code>no boss-movement</code>. The mechanics ticked in "Are you assigned to something?" are added as <code>assign</code> lines.
Every sim of the prep (gear, talents, cooldowns) runs on this fight.</p>
<form method="post" action="/plan"><input type="hidden" name="boss" value="{enc.id}">
<input type="hidden" name="difficulty" value="{e(difficulty)}"><textarea name="plan" aria-label="Fight plan lines">{e(text)}</textarea>
<p><button class="btn ghost">Save the plan</button></p></form>"""


def _fresh_header(text: str) -> str:
    """A plan or notes file saved by an older version: its first comment line as the current template words it
    (they said to run a command)."""
    lines = text.splitlines()
    if lines and lines[0].startswith("# Personal plan for ") and "paf plan" in lines[0]:
        lines[0] = lines[0].split(". Edit", 1)[0] + ". Edit and save: the next prep of this boss uses it."
    elif lines and lines[0].startswith("# Boss notes for ") and "rerun" in lines[0]:
        lines[0:1] = [lines[0].split(" Uncomment", 1)[0],
                      "# Remove the # of a line to use it, save, then prepare the fight again."]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def notes_block(enc, difficulty: str) -> str:
    """What the player knows about the boss: the detected mechanics with their evidence, editable."""
    from paf.corpus.template import template_path
    from paf.notes import notes_path

    p = notes_path(template_path(enc.name, difficulty))
    if not p.is_file():
        return ('<p class="muted small">Available after the first prep: the detected mechanics (units sharing the '
                "boss's health, damage amps...) with their evidence.</p>")
    text = _fresh_header(p.read_text(encoding="utf-8-sig"))
    return f"""<p class="small muted">Detected in the logs, with the evidence. Correct what the logs cannot tell (e.g. the
real damage amp of a unit: <code>amp &lt;unit&gt; 2.0</code>), save, then prepare the fight again.</p>
<form method="post" action="/notes"><input type="hidden" name="boss" value="{enc.id}">
<input type="hidden" name="difficulty" value="{e(difficulty)}"><textarea name="notes" aria-label="Boss notes">{e(text)}</textarea>
<p><button class="btn ghost">Save the notes</button></p></form>"""


def write_assigns(boss_id: int, difficulty: str, chosen: list[str]) -> None:
    """Write the ticked assignments as uncommented `assign` lines in the boss plan file."""
    from paf.corpus.template import template_path
    from paf.encounters import raid_encounters
    from paf.wcl import WCLClient

    enc = next((x for x in raid_encounters(WCLClient()) if x.id == boss_id), None)
    if enc is None:
        return
    ppath = template_path(enc.name, difficulty).with_suffix(".plan.txt")
    ppath.parent.mkdir(parents=True, exist_ok=True)
    lines = ppath.read_text(encoding="utf-8-sig").splitlines() if ppath.is_file() else []
    lines = [line for line in lines if not line.strip().lower().startswith("assign ")]
    lines += [f"assign {c}" for c in chosen]
    ppath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def feedback_page(jid: str = "", note: str = "") -> str:
    from paf import feedback

    what, log = feedback.job_log(jid) if jid else ("", feedback.app_log())
    _, preview = feedback.report("(your message)", what, log, feedback.performance(log if jid else ""))
    dest = ("sent to the prep-a-fight team" if feedback.endpoint() else
            "opened as a GitHub issue in your browser, for you to post (a free GitHub account is needed)")
    return f'''<h1>Send feedback</h1>{note}<p class="lead">A bug, a wrong number, an idea: it is {dest}.</p>
<form method="post" action="/feedback" class="card"><input type="hidden" name="job" value="{e(jid)}">
<label>Your message <textarea name="message" required placeholder="What you did, what you expected, what you got.
Your spec and the boss help us."></textarea></label>
{f"""<label class="check-row"><input type="checkbox" name="log" checked><span> Attach the {"log of this prep" if jid else "app's log"}
(below; your Warcraft Logs key, user folder and email addresses are removed)</span></label>""" if log.strip() else ""}
<label class="check-row"><input type="checkbox" name="perf" checked><span> Attach performance measures: your computer's CPU,
cores and memory, and how long each step took (nothing personal: no name, no log, no folder). They help make the app
faster on every computer.</span></label>
<div class="cta"><button class="btn go">{"Send" if feedback.endpoint() else "Open it on GitHub"}</button></div></form>
<h2>Exactly what is sent</h2><div class="card"><pre class="log">{e(preview[-20000:])}</pre></div>'''


def send_feedback(form: dict) -> str:
    from paf import feedback

    jid = (form.get("job") or [""])[0]
    message = (form.get("message") or [""])[0]
    what, log = feedback.job_log(jid) if jid else ("", feedback.app_log())
    title, body = feedback.report(message, what, log if form.get("log") else "",
                                  feedback.performance(log if jid else "") if form.get("perf") else "")
    url = feedback.endpoint()
    if url:
        try:
            link = feedback.send(url, title, body)
            track = (f" You can follow it here: <a href='{e(link)}' target='_blank' rel='noopener'>{e(link)}</a>."
                     if link else "")
            return f"<h1>Thanks!</h1><p class='lead'>Your feedback was sent.{track} <a href='/'>Back home</a></p>"
        except (OSError, ValueError) as ex:
            note = f"<p class='notice small'>Sending failed ({e(str(ex))}): post it on GitHub instead.</p>"
    else:
        note = ""
    return (f"<h1>Almost done</h1>{note}<p class='lead'>Your report is ready on GitHub: open it, check it, and click "
            f"<b>Create</b>.</p><div class='cta'><a class='btn big' target='_blank' rel='noopener' "
            f"href='{e(feedback.issue_url(title, body))}'>Open the GitHub issue</a></div>")


def job_page(jid: str, part: str = "") -> bytes:
    job = JOBS.get(jid)
    if part == "banner":  # the banner of the other pages, refreshed by them
        from paf import loading

        return loading.banner(jid, job).encode() if job and job["status"] == "running" else b""
    if part == "live" and (job is None or job["status"] != "running"):  # finished: the page reloads itself
        return b"<p data-reload>Done.</p>"
    if job is None:
        return page("Unknown job", "<p>This prep is unknown (its files were removed?). <a href='/'>Home</a></p>")
    log = job["log"].read_text(encoding="utf-8", errors="replace") if job["log"].is_file() else ""
    elapsed = int(time.time() - job["started"])
    if job["status"] == "done" and job["result"] and job["result"].is_file():
        key = job["result"].stem.partition("-")[2]
        go = f"/view/{e(key)}"
        return (page("Done", f'<h1>Your prep is ready</h1><p class="lead">Opening the prep sheet&hellip;</p>'
                             f'<div class="cta"><a class="btn big" href="{go}">Open the prep sheet</a></div>'
                             f'<details class="card"><summary>What was done (log)</summary><pre class="log">'
                             f'{e(log[-20000:])}</pre></details>')
                .replace(b"<head>", f'<head><meta http-equiv="refresh" content="2;url={go}">'.encode(), 1))
    status = job["status"]
    if job["args"] and job["args"][0] != "prep":  # a tool: its output, then the reports it wrote
        from paf.webtools import new_reports

        name = job["args"][0]
        from paf import workshop

        nice = workshop.job_page(jid, job, log, elapsed, new_reports(job["started"]) if status == "done" else [])
        if nice is not None:
            return page(workshop.BY_CMD[name].title, nice, 5 if status == "running" else None, job=jid)
        if status == "running":
            return page(name, f"<h1>Running: {e(name)}</h1><p class='lead'><span id='el' "
                              f"data-start='{job['started']:.0f}'>{elapsed // 60} min {elapsed % 60:02d} s</span>. "
                              f"This page updates itself.</p><div class='card'><pre class='log'>{e(log[-8000:])}"
                              f"</pre></div>", 5)
        links = "".join(f"<li><a href='/report/{e(r)}'>{e(r)}</a></li>" for r in new_reports(job["started"]))
        head = "Finished" if status == "done" else f"Stopped ({e(status)})"
        return page(name, f"<h1>{head}: {e(name)}</h1>"
                          + (f"<h2>Reports written</h2><div class='card'><ul>{links}</ul></div>" if links else "")
                          + f"<h2>Output</h2><div class='card'><pre class='log'>{e(log[-20000:])}</pre></div>"
                          + f"<p><a class='btn ghost' href='/tool/{e(name)}'>Run it again</a></p>")
    if status == "done":
        return page("Done", "<h1>The prep finished</h1><p class='lead'>Its sheet is listed on the "
                            "<a href='/'>home page</a>.</p>")
    live = prep_live(jid, job, log, elapsed)
    if part == "live":
        return live.encode()
    js = f"""<script>(function(){{
function tick(){{var el=document.getElementById('el');if(!el)return;var s=+el.dataset.start;
var t=Math.max(0,Math.floor(Date.now()/1000-s));el.textContent=Math.floor(t/60)+' min '+String(t%60).padStart(2,'0')+' s'}}
setInterval(tick,1000);
var poll=setInterval(function(){{fetch('/job/{e(jid)}?part=live').then(function(r){{return r.text()}}).then(function(h){{
if(h.indexOf('data-reload')>=0){{clearInterval(poll);location.reload();return}}
var box=document.getElementById('live');var open=box.querySelector('details[open]');box.innerHTML=h;
if(open){{var d=box.querySelector('details');if(d)d.open=true}}}}).catch(function(){{}})}},{POLL_S * 1000})}})();</script>"""
    if status != "running":  # paused, stopped or failed: nothing to follow (a paused page must not reload itself)
        js = ""
    return page("Preparing..." if status == "running" else "Prep", f"<div id='live'>{live}</div>"
                f"{guide_preview(job['args'])}{js}", job=jid)


POLL_S = 5  # the prep page asks for its live part this often


def refresh_ring(seconds: int) -> str:
    """A small ring that fills until the next refresh of the live part (restarts with each refresh: the ring is
    inside it). No number shown: hovering says it."""
    return (f"<svg class='ring' viewBox='0 0 20 20' width='16' height='16' role='img' "
            f"aria-label='Next update in {seconds} s'><title>Next update in {seconds} s</title>"
            f"<circle cx='10' cy='10' r='8' class='ring-bg'/><circle cx='10' cy='10' r='8' class='ring-fg' "
            f"style='animation-duration:{seconds}s'/></svg>")


def prep_live(jid: str, job: dict, log: str, elapsed: int) -> str:
    """The part of the prep page that updates itself: steps, time left, what the prep found so far."""
    from paf.progress import findings

    status = job["status"]
    if status == "done":  # the page reloads and opens the sheet
        return "<p data-reload>Done.</p>"
    rows, left = prep_progress(log, elapsed)
    icon = {"done": "&#10003;", "now": "&#9679;", "next": "&#9675;"}
    items = "".join(
        f"<li class='st {state}'><span>{icon[state]}</span> <div><b>{e(label)}</b>"
        + (" <span class='pill on'>in progress</span>" if state == "now" else "")
        + (f"<div class='small muted'>{e(why)}</div>" if state != "done" else "") + "</div></li>"
        for label, why, state in rows)
    if status == "running":
        head = "Preparing the fight"
        if left < 1.5:
            eta = "almost done"
        else:
            eta = f"about {max(1, round(left * 0.85))}-{round(left * 1.2) + 1} min left"
        from paf.loading import percent

        pct, _left = percent(log, elapsed)
        lead = (f"<span id='el' data-start='{job['started']:.0f}'>{elapsed // 60} min {elapsed % 60:02d} s</span>"
                f" &middot; <b>{pct}%</b> &middot; <b>{eta}</b> {refresh_ring(POLL_S)}"
                f"<span class='jb-bar big'><span style='width:{pct}%'></span></span>")
        calm = ("<div class='leave'><b>You can leave this page.</b> The prep keeps running: a banner on top of every "
                "page shows how far it is, and its sheet appears on the home page. You can even close the app.</div>"
                "<p class='small muted'>Your computer stays usable: the simulations run at low priority.</p>"
                f"<form method='post' action='/job/{e(jid)}/pause' class='cta'><button class='btn ghost'>Pause this "
                "prep</button><span class='small muted'>Resume it whenever you want: the logs already read are kept."
                "</span></form>")
    elif status == "paused":
        why = " for the update" if job.get("why") == "update" else ""
        head = "The prep is paused"
        lead = (f"Paused{why}. It goes on from the logs already read; the sims of this boss run again."
                f"<form method='post' action='/job/{e(jid)}/resume' class='cta'><button class='btn'>Resume the prep"
                "</button></form>")
        calm = ""
    elif status == "resumed":
        head, calm = "The prep was resumed", ""
        lead = f"<a class='btn' href='/job/{e(job.get('next', ''))}'>Follow it</a>"
    else:
        head = "The prep stopped" if status == "stopped" else f"The prep failed ({e(status)})"
        lead = ("The log below says why. Go back to the boss page to try again, or "
                f"<a class='btn' href='/feedback?job={e(jid)}'>Send this report</a> (you see it before it goes).")
        calm = ""
    found = findings(log)
    so_far = ("<h2>So far</h2><div class='card'><ul class='small'>" + "".join(f"<li>{e(x)}</li>" for x in found)
              + "</ul></div>") if found else ""
    return (f"<h1>{head}</h1><p class='lead'>{lead}</p>{calm}<div class='card'><ol class='steps'>{items}</ol></div>"
            f"{so_far}<details class='card'><summary>Details (log)</summary><pre class='log'>{e(log[-6000:])}</pre>"
            f"</details>")


def guide_preview(args: list[str]) -> str:
    """While the prep runs: the boss in 60 seconds (Encounter Journal), if it is on this computer."""
    try:
        from paf import bossguide
        from paf.gamedata import _table_path

        if not _table_path("JournalEncounterSection").is_file():  # never wait for a download on this page
            return ""
        boss = int(args[1])
        diff = args[args.index("--difficulty") + 1] if "--difficulty" in args else settings.get("difficulty")
        sections = bossguide.load(boss, diff)
        from paf import i18n

        if sections and i18n.language() != "en":  # the journal in the player's language from the first prep
            from paf import names

            names.build(boss, diff, {}, i18n.wow_locale())
        summary = bossguide.summary_html(sections, "damage", "#boss") if sections else ""
    except Exception:  # noqa: BLE001 - only a reading while waiting
        return ""
    return (f"<h2>While you wait: the boss in 60 seconds</h2><div class='card'>{summary}</div>"
            f"<style>{bossguide.CSS}</style>" if summary else "")


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        if ctype.startswith("text/html"):  # every page, prep sheets included, in the player's language
            from paf.i18n import translate

            body = translate(body.decode("utf-8")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:  # quiet
        pass

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":
                from paf import onboarding

                if onboarding.needed():  # the first run: the steps (issue #11)
                    self._redirect("/welcome")
                    return
                self._send(home())
            elif url.path == "/welcome":
                from paf import onboarding

                self._send(page("Welcome", f"<style>{onboarding.CSS}</style>{onboarding.page_body()}{onboarding.JS}"))
            elif url.path == "/wcl/status":
                import json

                from paf import wcllogin

                self._send(json.dumps(wcllogin.status()).encode(), ctype="application/json")
            elif url.path in ("/onboard/skip", "/onboard/finish"):
                from paf import onboarding

                onboarding.finish()
                self._redirect("/")
            elif url.path.startswith("/bossimg/"):  # a boss's portrait from the Encounter Journal
                import re

                from paf import bossimg

                m = re.fullmatch(r"/bossimg/(\d+)\.png", url.path)
                img = bossimg.path(int(m.group(1))) if m else None
                if img:
                    self._send(img.read_bytes(), ctype="image/png")
                else:
                    self._send(b"", 404, "image/png")
            elif url.path == "/raid/prepare":
                self._send(raid_prepare_page(q.get("difficulty", settings.get("difficulty"))))
            elif url.path == "/raidlead":
                from paf import raidlead

                diff = q.get("difficulty") or raidlead.load().get("difficulty") or settings.get("difficulty")
                self._send(page("Raid lead", raidlead.page_body(diff if diff in settings.DIFFICULTIES else "heroic")))
            elif url.path == "/lastraid/card":
                from paf import characters, lastraid

                self._send(lastraid.card(characters.current_slug()).encode(), ctype="text/html; charset=utf-8")
            elif url.path == "/raid/strip":
                self._send(queue_strip(settings.get("difficulty")).encode(), ctype="text/html; charset=utf-8")
            elif url.path == "/boss":
                self._send(boss_page(q.get("boss", ""), q.get("difficulty", settings.get("difficulty"))))
            elif url.path == "/reclear":
                self._send(page("Reclear", reclear_page()))
            elif url.path == "/tools":
                from paf import workshop

                self._send(page("Tools", workshop.index()))
            elif url.path.startswith("/tool/"):
                from paf import workshop
                from paf.webtools import tool_page

                name = url.path.rsplit("/", 1)[1]
                body = (None if q.get("raw") else workshop.tool_page(name, _encounters())) or \
                    tool_page(name, _encounters())
                tool = workshop.BY_CMD.get(name)
                self._send(page(tool.title if tool else "Tool", body) if body else page("Not found", "<p>Unknown tool.</p>"),
                           200 if body else 404)
            elif url.path == "/characters":
                self._send(page("Characters", characters_page()))
            elif url.path == "/settings":
                from paf.webtools import settings_page

                self._send(page("Settings", settings_page()))
            elif url.path == "/feedback":
                self._send(page("Feedback", feedback_page(q.get("job", ""))))
            elif url.path.startswith("/share/"):
                self._send(page("Share", share_page(url.path.rsplit("/", 1)[1])))
            elif url.path.startswith("/view/"):
                self._send(view_page(url.path.rsplit("/", 1)[1], q.get("tab", "prep")))
            elif url.path.startswith("/job/"):
                self._send(job_page(url.path.rsplit("/", 1)[1], q.get("part", "")))
            elif url.path.startswith("/report/"):
                name = Path(url.path).name
                f = data_dir() / "reports" / name
                if f.is_file() and f.suffix in (".html", ".txt"):
                    ctype = "text/html; charset=utf-8" if f.suffix == ".html" else "text/plain; charset=utf-8"
                    body = f.read_bytes()
                    if f.suffix == ".html":  # links between reports (timeline) go through /report/
                        body = body.replace(b'href="timeline-', b'href="/report/timeline-')
                    self._send(body, ctype=ctype)
                else:
                    self._send(page("Not found", "<p>Not found.</p>"), 404)
            else:
                self._send(page("Not found", "<p>Not found.</p>"), 404)
        except Exception as ex:  # noqa: BLE001 - show the error in the page instead of dropping the connection
            self._send(page("Error", f"<h1>Error</h1><pre>{e(repr(ex))}</pre>"), 500)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True)
        try:
            if self.path.startswith("/onboard/"):
                from paf import onboarding

                f = {k: v[0] for k, v in form.items()}
                step = self.path.rsplit("/", 1)[1]
                out = {"key": lambda: onboarding.save_key(f.get("id", ""), f.get("secret", "")),
                       "character": lambda: onboarding.find_character(f.get("name", ""), f.get("server", ""),
                                                                       f.get("region", "eu")),
                       "simc": lambda: onboarding.paste_simc(f.get("simc", "")),
                       "raid": lambda: onboarding.save_raid(f.get("guild", ""), f.get("server", ""),
                                                            f.get("region", "eu"))}.get(step)
                if out is None:
                    self._send(b'{"ok": false}', 404, "application/json")
                    return
                import json

                self._send(json.dumps(out()).encode(), ctype="application/json")
            elif self.path == "/wcl/login":  # the player's Warcraft Logs login (paf.wcllogin)
                import json

                from paf import wcllogin

                try:
                    self._send(json.dumps({"ok": True, "url": wcllogin.start()}).encode(), ctype="application/json")
                except RuntimeError as ex:
                    self._send(json.dumps({"ok": False, "error": str(ex)}).encode(), ctype="application/json")
            elif self.path == "/wcl/logout":
                from paf import wcllogin

                wcllogin.logout()
                self._redirect("/settings")
            elif self.path == "/profile":
                from paf.profile import looks_like_export

                text = (form.get("simc") or [""])[0]
                if not looks_like_export(text):
                    self._send(page("Not a /simc export", "<p>That does not look like a /simc export. "
                                                          "<a href='/'>Back</a></p>"), 400)
                    return
                from paf import characters

                characters.save(text)  # a new character, or an update of a known one; now the active one
                self._redirect("/")
            elif self.path == "/character/import":  # one of your Warcraft Logs account's characters (Characters)
                from paf import onboarding

                f = {k: v[0] for k, v in form.items()}
                out = onboarding.find_character(f.get("name", ""), f.get("server", ""), f.get("region", "eu"))
                if not out.get("ok"):
                    self._send(page("Not added", f"<p>{e(out.get('error') or 'Not found.')} "
                                                 "<a href='/characters'>Back</a></p>"), 400)
                    return
                self._redirect("/characters")
            elif self.path in ("/character/select", "/character/remove"):
                from paf import characters

                s = (form.get("slug") or [""])[0]
                (characters.select if self.path.endswith("select") else characters.remove)(s)
                back = (form.get("back") or ["/"])[0]
                self._redirect(back if back.startswith("/") and not back.startswith("//") else "/")
            elif self.path == "/notes":
                from paf.corpus.template import template_path
                from paf.encounters import raid_encounters
                from paf.notes import notes_path, parse_notes
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                text = (form.get("notes") or [""])[0].replace("\r\n", "\n")
                try:
                    parse_notes(text)
                except ValueError as ex:
                    self._send(page("Invalid notes", f"<p>{e(str(ex))}. <a href='javascript:history.back()'>Back</a></p>"), 400)
                    return
                enc = next(x for x in raid_encounters(WCLClient()) if x.id == boss_id)
                notes_path(template_path(enc.name, difficulty)).write_text(text, encoding="utf-8")
                self._redirect(f"/boss?boss={boss_id}&difficulty={difficulty}")
            elif self.path.startswith("/tool/"):
                from paf import workshop
                from paf.webtools import tool_args

                name = self.path.rsplit("/", 1)[1]
                args = workshop.args(name, form) if "_curated" in form else tool_args(name, form)
                if args is None or args[0] in ("serve", "profile", "config"):
                    self._send(page("Not found", "<p>Unknown tool.</p>"), 404)
                    return
                self._redirect(f"/job/{JOBS.start(args, None)}")
            elif self.path.startswith(("/share/", "/unshare/")):
                from paf import share

                key = self.path.rsplit("/", 1)[1]
                try:
                    if self.path.startswith("/share/"):
                        share.publish(key)
                    else:
                        share.stop(key)
                    self._redirect(f"/share/{key}")
                except (OSError, RuntimeError, ValueError) as ex:
                    self._send(page("Share", share_page(key, f"Sharing failed: {ex}")), 502)
            elif self.path == "/language":
                from paf import i18n

                lang = (form.get("lang") or [""])[0]
                if lang in i18n.available():
                    settings.set_value("language", lang)
                if self.headers.get("X-Paf-Inline"):  # switched in place by the page itself
                    self.send_response(204)
                    self.end_headers()
                    return
                back = self.headers.get("Referer", "/")
                self._redirect(urlparse(back).path + (f"?{urlparse(back).query}" if urlparse(back).query else "")
                               if back.startswith(("http://127.0.0.1", "http://localhost", "http://paf.local")) else "/")
            elif self.path == "/feedback":
                self._send(page("Feedback", send_feedback(form)))
            elif self.path == "/update":
                self._send(page("Update", run_update(pause=bool(form.get("pause")))))
            elif self.path.startswith("/job/") and self.path.endswith(("/pause", "/resume")):
                jid = self.path.split("/")[2]
                if self.path.endswith("/pause"):
                    JOBS.pause(jid)
                    self._redirect(f"/job/{jid}")
                else:
                    self._redirect(f"/job/{JOBS.resume(jid) or jid}")
            elif self.path == "/update/check":
                from paf import update

                rel = update.check_now()
                self._send(page("Updates", f"<h1>Updates</h1><p class='lead'>Version {e(rel.version)} is out: see the "
                                           f"banner above.</p>" if rel else
                                f"<h1>Updates</h1><p class='lead'>You have the latest version "
                                f"({e(update.__version__)}).</p><p><a href='/settings'>Back to Settings</a></p>"))
            elif self.path == "/settings":
                from paf.webtools import settings_page

                errors = []
                for key in settings.SETTINGS:
                    if key in form:
                        try:  # the last value: a checkbox sends "on" after its hidden "off"
                            settings.set_value(key, form[key][-1])
                        except (KeyError, ValueError) as ex:
                            errors.append(f"{key}: {ex}")
                self._send(page("Settings", settings_page("; ".join(errors) if errors else "Saved.")))
            elif self.path == "/guild":
                settings.set_value("guild", (form.get("guild") or [""])[0])
                settings.set_value("guild_server", (form.get("server") or [""])[0])
                settings.set_value("guild_region", (form.get("region") or ["eu"])[0])
                self._redirect("/")
            elif self.path == "/credentials":
                from paf.config import save_credentials
                from paf.wcl import WCLClient, WCLError
                from paf.webtools import settings_page

                cid, secret = (form.get("id") or [""])[0].strip(), (form.get("secret") or [""])[0].strip()
                from_settings = (form.get("back") or [""])[0] == "settings"
                try:
                    WCLClient(cid, secret).rate_limit()
                except (WCLError, OSError) as ex:
                    error = f"Warcraft Logs refused these credentials (the old key is kept): {ex}"
                    self._send(page("Settings", settings_page(error)) if from_settings else home(error), 400)
                    return
                save_credentials(cid, secret)
                if from_settings:
                    self._send(page("Settings", settings_page("New Warcraft Logs key saved and tested.")))
                else:
                    self._redirect("/")
            elif self.path == "/plan":
                from paf.encounters import raid_encounters
                from paf.plan import parse_plan
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                text = (form.get("plan") or [""])[0].replace("\r\n", "\n")
                try:
                    parse_plan(text)
                except ValueError as ex:
                    self._send(page("Invalid plan", f"<p>{e(str(ex))}. <a href='javascript:history.back()'>Back</a></p>"), 400)
                    return
                enc = next(x for x in raid_encounters(WCLClient()) if x.id == boss_id)
                p = _plan_path(enc, difficulty)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
                self._redirect(f"/boss?boss={boss_id}&difficulty={difficulty}")
            elif self.path == "/raid/prepare":
                from paf import characters, raidqueue

                difficulty = (form.get("difficulty") or [settings.get("difficulty")])[0]
                if difficulty in settings.DIFFICULTIES:
                    encs = journal_order(_encounters())
                    ready = fresh_bosses(encs, difficulty, settings.get("class"), settings.get("spec"))
                    raidqueue.start(raidqueue.build(encs, difficulty, characters.current_slug(), ready))
                self._redirect("/#raidq")
            elif self.path == "/raidlead/read":
                from paf import raidlead

                diff = (form.get("difficulty") or [settings.get("difficulty")])[0]
                raidlead.start(diff if diff in settings.DIFFICULTIES else "heroic")
                self._redirect("/raidlead")
            elif self.path == "/raidlead/bench":
                from paf import raidlead

                raidlead.toggle_bench((form.get("name") or [""])[0])
                self._redirect("/raidlead")
            elif self.path == "/raidlead/lust":
                from paf import raidlead

                try:
                    enc_id, diff = int((form.get("enc") or ["0"])[0]), int((form.get("diff") or ["0"])[0])
                except ValueError:
                    enc_id = diff = 0
                if enc_id and diff:
                    raidlead.set_lust(enc_id, diff, (form.get("spot") or [""])[0])
                level = (form.get("difficulty") or [""])[0]
                self._redirect(f"/raidlead?difficulty={level if level in settings.DIFFICULTIES else 'heroic'}"
                               f"#boss-{enc_id}")
            elif self.path == "/lastraid/again":
                from paf import characters, lastraid

                lastraid.again(characters.current_slug())
                self._redirect("/reclear")
            elif self.path == "/character/autologs":
                from paf import lastraid

                slug = (form.get("slug") or [""])[0]
                if slug:
                    lastraid.tick(slug, (form.get("on") or ["0"])[0] == "1")
                    if (form.get("on") or ["0"])[0] == "1":
                        lastraid.start()
                self._redirect("/characters")
            elif self.path == "/raid/stop":
                from paf import raidqueue

                raidqueue.stop()
                self._redirect("/#raidq")
            elif self.path == "/prep":
                from paf.corpus.template import report_key
                from paf.encounters import raid_encounters
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                raid = (form.get("raid") or [""])[0]
                if raid.strip():  # checked before anything is written
                    from paf.raidneed import report_code

                    try:
                        report_code(raid)
                    except ValueError as ex:
                        self._send(page("Invalid log link", f"<p>{e(str(ex))}: nothing was started or saved. "
                                                            f"<a href='javascript:history.back()'>Back to the "
                                                            f"form</a></p>"), 400)
                        return
                write_assigns(boss_id, difficulty, form.get("assign", []))
                write_raid(boss_id, difficulty, raid)
                enc = next(x for x in raid_encounters(WCLClient()) if x.id == boss_id)
                args = ["prep", str(boss_id), "--difficulty", difficulty]
                if "gear" not in form:
                    args.append("--no-gear")
                if "optimize" not in form:
                    args.append("--no-optimize")
                goal = (form.get("goal") or ["auto"])[0]
                if goal in ("boss", "total"):
                    args += ["--objective", goal]
                result = data_dir() / "reports" / f"prep-{report_key(enc.name, difficulty)}.html"
                jid = JOBS.start(args, result)
                self._redirect(f"/job/{jid}")
            else:
                self._send(page("Not found", "<p>Not found.</p>"), 404)
        except Exception as ex:  # noqa: BLE001
            self._send(page("Error", f"<h1>Error</h1><pre>{e(repr(ex))}</pre>"), 500)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        """A browser closing or resetting a connection (tab closed, prefetch, reload...) is normal: no traceback."""
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    load_dotenv()
    from paf import wcl

    wcl.INTERACTIVE["on"] = True  # pages never wait for Warcraft Logs' quota (paf.wcl)
    from paf.simc_install import ensure_simc

    ensure_simc()  # a new computer: SimulationCraft downloads while the player sets up (as in paf.desktop)
    server = Server(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"prep-a-fight is running on {url} (Ctrl+C to stop)")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
