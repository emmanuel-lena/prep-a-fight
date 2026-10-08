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

e = html.escape


def bossguide_css() -> str:
    from paf.bossguide import CSS as GUIDE_CSS

    return GUIDE_CSS

CSS = theme.CSS + bossguide_css() + """
pre.log{max-height:460px;overflow:auto;background:var(--surface-2);border-radius:8px;padding:10px 12px}
.boss-tile .name{font-weight:700;font-size:16px;margin-bottom:6px}
/* the home page once set up (simple_home) */
.home-hero{display:grid;gap:18px;margin:6px 0 30px;padding:24px;border-radius:16px;background:var(--surface);
  border:1px solid var(--line)}
.home-hero .me{display:flex;gap:14px;align-items:center}
.home-hero .me-ic{width:56px;height:56px;border-radius:10px;margin:0}
.home-hero .me b{display:block;font-size:20px} .home-hero .me span{color:var(--muted)}
.start{display:grid;gap:14px;max-width:560px}
.start h1{margin:4px 0 0;font:600 30px/1.15 'Fraunces',Georgia,serif}
.start select.big{font-size:18px;padding:12px 14px;border-radius:10px}
.segs{display:flex;gap:8px;flex-wrap:wrap}
.seg input{position:absolute;opacity:0;pointer-events:none}
.seg span{display:inline-block;padding:10px 18px;border-radius:999px;border:1.5px solid var(--line);cursor:pointer;
  font-weight:600;font-size:16px}
.seg input:checked+span{background:var(--accent);border-color:var(--accent);color:var(--bg)}
.seg input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
.btn.go{justify-self:start;font-size:18px;padding:12px 26px;border-radius:12px}
.h-mine{margin-top:0}
.chars{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start}
.chars .ch button{display:flex;gap:8px;align-items:center;padding:5px 12px 5px 5px;border-radius:999px;cursor:pointer;
  border:1px solid var(--line);background:none;color:var(--fg);font:inherit;font-weight:600}
.chars .ch button:hover{border-color:var(--accent)}
.chars .ch-ic{width:26px;height:26px;border-radius:50%;margin:0}
.ch-new{display:inline-flex;align-items:center;padding:6px 14px;border-radius:999px;border:1.5px dashed var(--accent);
  color:var(--accent);font-weight:600;text-decoration:none} .ch-new:hover{background:color-mix(in srgb,var(--accent) 10%,transparent)}
.ccards{display:grid;gap:12px;margin-bottom:24px}
.ccard{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:14px 16px;border-radius:14px;border:1px solid var(--line);
  background:var(--surface)} .ccard.on{border-color:var(--accent)}
.ccard .cc-ic{width:48px;height:48px;border-radius:10px;margin:0}
.cc-txt{display:flex;flex-direction:column;gap:4px;flex:1;min-width:180px} .cc-txt b{font-size:18px}
.cc-act{display:flex;gap:8px;align-items:center;flex-wrap:wrap} .cc-act form{margin:0}
.rb-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:10px;margin:0 0 6px}
.rb-boss{position:relative;display:flex;flex-direction:column;align-items:center;gap:6px;padding:8px 4px;border-radius:14px;
  cursor:pointer;outline:none} .rb-boss:hover,.rb-boss:focus-within{background:var(--surface)}
.rb-face{position:relative;width:64px;height:64px;border-radius:50%;overflow:hidden;background:#efe9df;
  box-shadow:0 0 0 2px var(--line);display:block}
.rb-img{width:100%;height:100%;object-fit:cover;object-position:50% 6%;transform:scale(1.9);transform-origin:50% 10%;display:block}
.rb-img.none{display:grid;place-items:center;transform:none;font:700 24px var(--font-data);color:#5a4b3c}
.rb-face .rb-img:not(.none),.rb-in .rb-img:not(.none){position:absolute;inset:0;background:#efe9df}
.rb-in{position:relative} .rb-face .rb-img.none,.rb-in .rb-img.none{position:absolute;inset:0}
.rb-boss.grey .rb-face{filter:grayscale(1) brightness(.75);box-shadow:0 0 0 2px var(--line)}
.rb-boss:not(.grey) .rb-face{box-shadow:0 0 0 2px var(--accent)}
.rb-n{position:absolute;right:2px;bottom:2px;min-width:18px;height:18px;padding:0 4px;border-radius:9px;background:rgba(0,0,0,.65);
  color:#fff;font:700 11px/18px var(--font-data);text-align:center}
.rb-name{font-size:12px;font-weight:600;text-align:center;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden}
.rb-boss.grey .rb-name{color:var(--muted)}
.rb-pop{position:absolute;top:calc(100% - 4px);left:50%;transform:translateX(-50%);z-index:20;display:none;width:max-content;
  padding:12px 14px;border-radius:12px;background:#0b0a10;border:1px solid #5d5a52;box-shadow:0 10px 30px rgba(0,0,0,.5);color:#fff}
.rb-boss:hover .rb-pop,.rb-boss:focus-within .rb-pop{display:block}
.rb-row>.rb-boss:nth-child(-n+2) .rb-pop{left:0;transform:none} .rb-row>.rb-boss:nth-last-child(-n+2) .rb-pop{left:auto;right:0;transform:none}
.rb-title{display:block;font:600 15px 'Fraunces',Georgia,serif;color:#ffd100;margin:0 0 10px}
.rb-ds{display:flex;gap:14px}
.rb-d{display:flex;flex-direction:column;align-items:center;gap:4px;min-width:78px;color:#fff;text-decoration:none}
.rb-d:hover{text-decoration:none} .rb-d b{font-size:12.5px} .rb-d small{font-size:11.5px;color:#bdb6a8}
.rb-frame{width:58px;height:58px;display:grid;place-items:center;transition:transform .12s}
.rb-d:hover .rb-frame{transform:scale(1.07)}
.rb-frame .rb-in{width:calc(100% - 6px);height:calc(100% - 6px);overflow:hidden;background:#efe9df;display:block}
.rb-frame.tri{background:#1eff00;clip-path:polygon(50% 0,100% 100%,0 100%)}
.rb-frame.tri .rb-in{clip-path:polygon(50% 0,100% 100%,0 100%);margin-top:5px;width:calc(100% - 10px);height:calc(100% - 9px)}
.rb-frame.sq{background:#0070dd;border-radius:6px} .rb-frame.sq .rb-in{border-radius:4px}
.rb-frame.penta{background:#a335ee;clip-path:polygon(50% 0,100% 38%,81% 100%,19% 100%,0 38%)}
.rb-frame.penta .rb-in{clip-path:polygon(50% 0,100% 38%,81% 100%,19% 100%,0 38%)}
.rb-d.no .rb-frame .rb-in,.rb-d.old .rb-frame .rb-in{filter:grayscale(1) brightness(.7)}
.rb-d.ok small{color:#1eff00} .rb-d.old small{color:#ffb84d} .rb-d.run small{color:#ffd100}
.rb-legend span+span::before{content:" · "}
.rm>summary{list-style:none;cursor:pointer} .rm>summary::-webkit-details-marker{display:none}
.rm[open]>summary{display:none} .rm-ask{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.rm-ask span{color:var(--neg);font-size:14px}
.btn.danger{color:var(--neg)}
.add-form textarea{width:100%;min-height:160px;box-sizing:border-box}
.bcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.bcard{display:flex;gap:12px;align-items:center;padding:14px 16px;border-radius:12px;border:1px solid var(--line);
  background:var(--surface);color:var(--fg);text-decoration:none;transition:border-color .15s,transform .15s}
.bcard:hover{border-color:var(--accent);transform:translateY(-1px)}
.bcard .bc-ic{width:40px;height:40px;border-radius:8px;margin:0;flex:none}
.bc-txt{display:flex;flex-direction:column;gap:4px;min-width:0;flex:1}
.bc-txt b{font-size:16px} .bc-meta{font-size:13px;color:var(--muted)}
.bc-when{font-size:12.5px;color:var(--muted);white-space:nowrap}
.bc-more,.home-more{margin-top:18px} .bc-more>summary,.home-more>summary{cursor:pointer;color:var(--muted)}
.home-more[open]>summary{margin-bottom:12px}
.boss-tile .when{font-size:12px;color:var(--muted);margin-top:8px}
.boss-tile .top{font-size:13px;margin-top:10px;line-height:1.35}
.cta{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:18px 0 6px}
.lead{font-size:16px;color:var(--muted);margin-bottom:18px}
.ring{vertical-align:-3px;margin-left:4px} .ring circle{fill:none;stroke-width:3} .ring-bg{stroke:var(--line)} .ring-fg{stroke:var(--accent);stroke-dasharray:50.3;stroke-dashoffset:50.3;transform:rotate(-90deg);transform-origin:center;animation:ring linear forwards} @keyframes ring{to{stroke-dashoffset:0}} @media (prefers-reduced-motion:reduce){.ring-fg{animation:none;stroke-dashoffset:25}}
ol.steps{list-style:none;margin:0;padding:0} .st{padding:7px 0;border-bottom:1px solid var(--line);display:flex;gap:4px}
.st:last-child{border-bottom:0} .st>span:first-child{display:inline-block;width:22px;flex:none} .st .small{font-weight:400}
.st.done{color:var(--muted)} .st.done span:first-child{color:var(--pos)} .st.now{font-weight:700}
.st.now span:first-child{color:var(--accent)} .st.next{color:var(--muted)}
"""


def page(title: str, body: str, refresh: int | None = None, nav: str = "", job: str = "") -> bytes:
    """job: the prep whose own page this is (its banner is not repeated on top)."""
    from paf import loading

    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    try:
        running = loading.banners(skip=job)
    except Exception:  # noqa: BLE001 - a banner never breaks a page
        running = ""
    nav = nav or ('<a href="/">Home</a><a href="/characters">Characters</a><a href="/tools">Tools</a>'
                  '<a href="/settings">Settings</a><a href="/feedback">Feedback</a>')
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"{meta}<title>{e(title)}</title>{theme.HEAD}<style>{CSS}{loading.CSS}</style></head><body>"
            f"{theme.topbar(nav + lang_switch(), back=True)}{loading.LOADER}"
            f"<main>{update_banner()}{running}{body}</main>{loading.JS}</body></html>").encode()


def share_page(key: str, error: str = "") -> str:
    """Share a prep sheet with the raid: a link that opens in any browser."""
    from paf import share

    item = next((x for x in prepared() if x["key"] == key and "prep" in x["files"]), None)
    if item is None:
        return "<h1>Not found</h1><p>Nothing prepared for this boss yet.</p>"
    info = share.current(key)
    head = (f"<h1>Share this prep</h1><p class='lead'>{e(item['name'])} &middot; {e(item['difficulty'])}"
            + (f" &middot; {e(item['spec'])}" if item.get("spec") else "") + "</p>")
    err = f"<p class='notice'>{e(error)}</p>" if error else ""
    if info:
        return (head + err + f"""<div class='card'><p><b>Shared.</b> Anyone with this link sees the prep sheet in their
browser, without the app:</p><p class='row'><input readonly value='{e(info["url"])}' style='flex:1;min-width:260px'
onclick='this.select()'><button type='button' data-copy='{e(info["url"])}'>Copy the link</button>
<a class='btn ghost' href='{e(info["url"])}' target='_blank' rel='noopener'>Open</a></p>
<p class='small muted'>It stays online {info.get("days", 30)} days, then disappears. To publish a newer version after
a new prep, stop sharing and share again.</p>
<form method='post' action='/unshare/{e(key)}'><button class='btn ghost'>Stop sharing</button></form></div>
<p><a href='/view/{e(key)}'>Back to the prep sheet</a></p>{COPY_JS}""")
    return (head + err + f"""<div class='card'><p>Get a link to this prep sheet for your raid (Discord, guild
forum...): it opens in any browser, nobody needs the app.</p>
<p class='small muted'>The sheet shows your character's name and gear: anyone with the link can see them. It stays
online 30 days, and you can stop sharing it at any time.</p>
<form method='post' action='/share/{e(key)}'><button class='btn'>Share it</button></form></div>
<p><a href='/view/{e(key)}'>Back to the prep sheet</a></p>""")


COPY_JS = """<script>document.addEventListener('click',function(ev){var b=ev.target.closest('[data-copy]');if(!b)return;
var t=b.getAttribute('data-copy'),o=b.textContent;function done(){b.textContent='Copied';setTimeout(function(){
b.textContent=o},1500)}if(navigator.clipboard){navigator.clipboard.writeText(t).then(done,function(){})}});</script>"""


def lang_switch() -> str:
    """The language of the app, in the top bar: changing it reloads the page."""
    from paf import i18n

    cur = i18n.language()
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


def run_update() -> str:
    """Download the new installer, start it over this install and close the app (the installer reopens it)."""
    from paf import update

    rel, folder = update.STATE.get("release"), update.install_dir()
    if rel is None or folder is None:
        return "<h1>Nothing to update</h1><p><a href='/'>Back home</a></p>"
    if any(j.get("status") == "running" for j in JOBS.jobs.values()):
        return ("<h1>A prep is running</h1><p class='lead'>Updating would stop it. Update when it is done (the banner "
                "stays).</p><p><a href='/'>Back home</a></p>")
    try:
        setup = update.download(rel)
    except (OSError, ValueError) as ex:
        return (f"<h1>The update failed</h1><p class='notice'>{e(str(ex))}</p><p>Download it by hand: "
                f"<a href='{e(rel.url)}' target='_blank' rel='noopener'>{e(rel.url)}</a></p>")
    update.run_installer(setup, folder)
    threading.Timer(1.5, lambda: (QUIT["hook"] or (lambda: os._exit(0)))()).start()
    return (f"<h1>Updating to {e(rel.version)}&hellip;</h1><p class='lead'>The app closes now and reopens by itself "
            f"in a few seconds. Your preps and settings are kept.</p>")


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
                proc = subprocess.Popen([_python(), "-m", "paf", *args], stdout=out, stderr=subprocess.STDOUT,
                                        env={**_env(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}, **flags)
                job["pid"] = proc.pid
                self._save(jid, job)
                code = proc.wait()
            job["status"] = "done" if code == 0 else f"failed (exit {code})"
            self._save(jid, job)

        threading.Thread(target=run, daemon=True).start()
        return jid

    @staticmethod
    def _save(jid: str, job: dict) -> None:
        """Jobs are kept on disk: the progress page survives a restart of the app (the prep keeps running)."""
        import json

        meta = {"args": job["args"], "result": str(job["result"] or ""), "status": job["status"],
                "started": job["started"], "pid": job.get("pid")}
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
        if status == "running":  # started by an earlier run of the app: read the outcome from the log
            # still running: its process is alive (a long silent step, like extracting simc, writes nothing for
            # minutes); without a pid (an older app), a log written in the last 15 min
            alive = pid_alive(meta["pid"]) if meta.get("pid") else (
                log.is_file() and time.time() - log.stat().st_mtime < 900)
            status = "done" if "Prep sheet:" in text else "failed" if "Traceback" in text else (
                "running" if alive else "stopped")
        return {"args": meta["args"], "log": log, "result": Path(meta["result"]) if meta["result"] else None,
                "status": status, "started": meta["started"]}


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
    return [x for x in encs if x.zone_id == zone]


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
        if kind not in ("prep", "timeline") or not key:
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
        f'<span class="pill gold">{e(x["difficulty"] or "?")}</span> '
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


def boss_cards(items: list[dict], limit: int = 6) -> str:
    """The prepared bosses as plain cards: the boss, the difficulty, when; the numbers stay in the sheet."""
    from paf import icons

    def card(x: dict) -> str:
        cls = (x.get("spec") or "").split(" ")[-1].lower()
        ic = icons.img(icons.CLASS_ICON.format(cls=cls), "medium", "bc-ic") if cls else ""
        return (f'<a class="bcard" href="/view/{e(x["key"])}">{ic}<span class="bc-txt"><b>{e(x["name"])}</b>'
                f'<span class="bc-meta"><span class="pill gold">{e(DIFF_LABELS.get(x["difficulty"], x["difficulty"] or "?"))}</span>'
                f' {e(x["spec"] or "")}</span></span><span class="bc-when">{ago(x["mtime"])}</span></a>')
    head = "".join(card(x) for x in items[:limit])
    rest = items[limit:]
    more = (f'<details class="bc-more"><summary>{len(rest)} more</summary><div class="bcards">'
            + "".join(card(x) for x in rest) + "</div></details>") if rest else ""
    return f'<div class="bcards">{head}</div>{more}'


TABS = (("prep", "Prep sheet"), ("timeline", "Top players' timelines"))


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
    others = "".join(f'<option value="/view/{e(x["key"])}"{" selected" if x["key"] == key else ""}>'
                     f'{e(x["name"])} ({e(" ".join(filter(None, (x["difficulty"], x["spec"]))))})</option>'
                     for x in prepared())
    src = f'/report/{e(item["files"][tab])}'
    boss_link = _boss_link(item)
    nav = (f'<select onchange="location=this.value" aria-label="Boss">{others}</select>{tabs}'
           + (f'<a href="{e(boss_link)}">Edit &amp; re-run</a>' if boss_link else "")
           + (f'<a href="/share/{e(key)}">Share</a>' if "prep" in item["files"] else "")
           + f'<a href="{PUBLIC_BASE}{src}" target="_blank">Open alone</a>')
    css = "body{display:flex;flex-direction:column;height:100vh}iframe{border:0;width:100%;flex:1;display:block}"
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f"<title>{e(item['name'])}</title>{theme.HEAD}<style>{CSS}{css}</style></head><body>{theme.topbar(nav + lang_switch())}"
            f'<iframe src="{src}" title="{e(item["name"])}"></iframe></body></html>').encode()


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
    import os

    return bool(os.environ.get("WCL_CLIENT_ID") and os.environ.get("WCL_CLIENT_SECRET"))


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
    err = f'<p class="notice">{e(error)}</p>' if error else ""
    return f"""<div class="card step"><div class="num">0</div><div class="body">
<h3>Connect to Warcraft Logs <span class="pill">once</span></h3>
<p class="small">prep-a-fight reads the top players' logs with <b>your own</b> free Warcraft Logs API key (each player
has an hourly quota, so the key is not shared).</p>
<ol class="small">
<li>Log in on <a href="https://www.warcraftlogs.com/api/clients" target="_blank" rel="noopener">warcraftlogs.com/api/clients</a>
and click <b>Create Client</b>.</li>
<li>Name: anything (e.g. <code>prep-a-fight</code>). Redirect URL: <code>http://localhost</code>. Leave "Public Client"
unticked.</li>
<li>Copy the <b>Client ID</b> and the <b>Client Secret</b> here.</li></ol>{err}
<form method="post" action="/credentials" class="row"><input name="id" size="38" placeholder="Client ID" required>
<input name="secret" size="38" type="password" placeholder="Client Secret" required><button>Save and test</button></form>
<p class="tiny muted">Saved on this computer only, in {e(str(data_dir() / '.env'))}.</p></div></div>"""


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
                f'<p class="notice small">{e(loaded.spec.title())} is a {role(loaded)} spec: prep-a-fight only '
                f'prepares damage dealers for now (healers and tanks come later).</p>')
        character = (f"""<p><b>{e(loaded.name)}</b> <span class="pill gold">{e(loaded.spec)} {e(loaded.class_name)}</span>
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
    guild_state = f'<span class="pill gold">{e(g)}</span>' if g else '<span class="pill">optional</span>'
    guild = f"""<div class="card step"><div class="num">3</div><div class="body">
<h3>Your raid {guild_state}</h3>
<p class="small muted">Your guild's latest public log gives your raid's composition and DPS: the prep then tells you
whether the others cover the adds (stay on the boss) or you should pad them.</p>
<form method="post" action="/guild" class="row"><input name="guild" placeholder="Guild name" value="{e(g)}">
<input name="server" placeholder="Server" value="{e(gs)}"><select name="region" aria-label="Region">{regions}</select>
<button class="btn ghost">Save</button></form></div></div>"""
    if loaded is not None and encs and has_credentials() and not error:  # ready: one big thing to do
        return page("prep-a-fight", simple_home(loaded, encs, character, guild, creds))
    body = f"""<h1>Prepare a boss fight</h1>
<p class="lead">The top players' logs, your character and SimulationCraft: your plan for this fight.</p>
{prepared_block()}
<h2>New prep</h2>{creds}
<div class="card step"><div class="num">1</div><div class="body"><h3>Your character</h3>{character}</div></div>
<div class="card step"><div class="num">2</div><div class="body"><h3>The boss</h3>{boss_form}</div></div>
{guild}"""
    return page("prep-a-fight", body)


def characters_strip() -> str:
    """Your other characters, one click to switch; and a new one (its /simc export)."""
    from paf import characters, icons

    others = [c for c in characters.all_characters() if not c.current]
    chips = "".join(
        f'<form method="post" action="/character/select" class="ch"><input type="hidden" name="slug" value="{e(c.slug)}">'
        f'<button title="{e(c.spec.title())} {e(c.class_name.title())}">'
        f'{icons.img(icons.CLASS_ICON.format(cls=c.class_name.lower()), "medium", "ch-ic")}<span>{e(c.name)}</span>'
        f'</button></form>' for c in others)
    add = '<a class="ch-new" href="/characters#add">+ Add a character</a>'
    return f'<div class="chars">{chips}{add}</div>'


ADD_FORM = ('<form method="post" action="/profile" class="add-form"><p class="small muted">In game, on that character: '
            'type <code>/simc</code>, then Ctrl+A, Ctrl+C, and paste here. Paste it again after a gear change to '
            'update it.</p><textarea name="simc" required placeholder="Paste the /simc export here"></textarea>'
            '<p><button class="btn go">Add this character</button></p></form>')


def characters_page() -> str:
    """All your characters: play one, update its export, remove it; and add a new one."""
    from paf import characters, icons

    cards = ""
    for c in characters.all_characters():
        ic = icons.img(icons.CLASS_ICON.format(cls=c.class_name.lower()), "large", "cc-ic")
        badge = ('<span class="pill">from a log: no bags</span>' if c.imported else
                 f'<span class="pill">{c.bags} items in bags</span>')
        play = ('<span class="pill gold">active</span>' if c.current else
                f'<form method="post" action="/character/select"><input type="hidden" name="slug" value="{e(c.slug)}">'
                f'<button class="btn go">Play this character</button></form>')
        cards += (f'<div class="ccard{" on" if c.current else ""}">{ic}<div class="cc-txt"><b>{e(c.name)}</b>'
                  f'<span>{e(c.spec.title())} {e(c.class_name.title())}</span><span>{badge} '
                  f'<span class="muted small">updated <span>{ago(c.mtime)}</span></span></span></div><div class="cc-act">{play}'
                  f'<a class="btn ghost" href="#add">Update</a>'
                  f'<details class="rm"><summary class="btn ghost danger">Remove</summary><div class="rm-ask">'
                  f'<span>Remove this character? Its /simc export is deleted.</span>'
                  f'<form method="post" action="/character/remove"><input type="hidden" name="slug" value="{e(c.slug)}">'
                  f'<button class="btn danger">Yes, remove it</button></form>'
                  '<button type="button" class="btn ghost" onclick="this.closest(\'details\').open=false">Keep it'
                  f'</button></div></details></div></div>')
    empty = "" if cards else "<p class='muted'>No character yet: add your first one below.</p>"
    return (f"<h1>Your characters</h1><p class='lead'>One /simc export per character: switch in one click, paste "
            f"again after a gear change.</p><div class='ccards'>{cards}</div>{empty}"
            f"<h2 id='add'>+ Add a character</h2><div class='card'>{ADD_FORM}</div>")


BOSS_THUMB = "https://wow.zamimg.com/modelviewer/live/webthumbs/npc/{bucket}/{display}.png"
DIFF_SHAPES = (("normal", "tri"), ("heroic", "sq"), ("mythic", "penta"))  # WoW's green, blue, purple


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
        from paf.gamedata import boss_display_ids

        displays = boss_display_ids()
    except Exception:  # noqa: BLE001 - offline: no portraits, the names stay
        displays = {}
    mine = f"{spec}-{class_name}".lower().replace(" ", "-")
    done = {x["key"]: x for x in prepared()}
    running = {}
    for jid, job in loading.running_preps():
        args = job["args"]
        diff = args[args.index("--difficulty") + 1] if "--difficulty" in args else settings.get("difficulty")
        running[(args[1] if len(args) > 1 else "", diff)] = (jid, job)

    def portrait(x, cls: str = "") -> str:
        d = displays.get(x.id)
        if not d:
            return f"<span class='rb-img none {cls}'>{e(x.name[:1])}</span>"
        # no portrait on Wowhead for some bosses: the initial behind it shows instead
        return (f"<span class='rb-img none {cls}'>{e(x.name[:1])}</span><img class='rb-img {cls}' "
                f"src='{BOSS_THUMB.format(bucket=d % 256, display=d)}' alt='' loading='lazy' "
                f"referrerpolicy='no-referrer' onerror=\"this.remove()\">")
    items = ""
    for i, x in enumerate(encs, 1):
        states, ready = "", False
        for diff, shape in DIFF_SHAPES:
            key = f"{_slug(x.name)}-{diff}-{mine}"
            item = done.get(key)
            run = running.get((str(x.id), diff))
            if run:
                log = run[1]["log"].read_text(encoding="utf-8", errors="replace") if run[1]["log"].is_file() else ""
                pct, _ = loading.percent(log, time.time() - run[1]["started"])
                href, state, word = f"/job/{e(run[0])}", "run", f"{pct}%"
            elif item and "prep" in item["files"]:
                stale = pack.is_stale(datetime.fromtimestamp(item["mtime"], UTC).isoformat())
                href, state, word = f"/view/{e(key)}", "old" if stale else "ok", "to redo" if stale else ago(item["mtime"])
                ready = ready or not stale
            else:
                href, state, word = f"/boss?boss={x.id}&amp;difficulty={diff}", "no", "prepare"
            states += (f"<a class='rb-d {state}' href='{href}'><span class='rb-frame {shape}'><span class='rb-in'>"
                       f"{portrait(x)}</span></span><b>{e(DIFF_LABELS.get(diff, diff))}</b><small>{word}</small></a>")
        items += (f"<div class='rb-boss{'' if ready else ' grey'}' tabindex='0'><span class='rb-face'>{portrait(x)}"
                  f"<span class='rb-n'>{i}</span></span><span class='rb-name'>{e(x.name)}</span>"
                  f"<div class='rb-pop' role='group' aria-label='{e(x.name)}'><b class='rb-title'>{e(x.name)}</b>"
                  f"<div class='rb-ds'>{states}</div></div></div>")
    return (f"<h2 class='h-mine'>Your raid, boss by boss</h2><div class='rb-row'>{items}</div>"
            "<p class='small muted rb-legend'><span>Point at a boss: its three difficulties, and a click to the "
            "sheet or the prep.</span> <span>A grey boss is not prepared for this week yet.</span></p>")


def simple_home(loaded, encs, character: str, guild: str, creds: str) -> str:
    """The home page once the app is set up (issue #13): your character, one big "prepare a boss", your bosses."""
    from paf import i18n, icons, names

    if i18n.language() != "en":  # a new player's boss list in their language, before any prep
        names.boss_names(i18n.wow_locale())

    diff = settings.get("difficulty")
    options = "".join(f'<option value="{x.id}">{e(x.name)}</option>' for x in encs)
    diffs = "".join(f'<label class="seg"><input type="radio" name="difficulty" value="{d}"{" checked" if d == diff else ""}>'
                    f'<span>{e(DIFF_LABELS.get(d, d))}</span></label>' for d in settings.DIFFICULTIES if d != "lfr")
    ic = icons.img(icons.CLASS_ICON.format(cls=loaded.class_name.lower()), "large", "me-ic")
    items = prepared()
    board = raid_board(encs, loaded.class_name, loaded.spec)
    mine = (f'<details class="home-more"><summary>Every prep sheet ({len(items)})</summary>{boss_cards(items)}'
            f'</details>' if items else "")
    g = settings.get("guild")
    return f"""<section class="home-hero"><div class="me">{ic}<div><b>{e(loaded.name)}</b>
<span>{e(loaded.spec.title())} {e(loaded.class_name.title())}{(" &middot; " + e(g)) if g else ""}</span></div></div>
{characters_strip()}
<form method="get" action="/boss" class="start"><h1>Prepare a boss</h1>
<select name="boss" aria-label="Boss" class="big">{options}</select>
<div class="segs" role="radiogroup" aria-label="Difficulty">{diffs}</div>
<button class="btn go">Let's go &rarr;</button></form></section>
{board}{mine}
<details class="home-more"><summary>Change your character, your raid or your Warcraft Logs key</summary>
<div class="card step"><div class="num">1</div><div class="body"><h3>Your character</h3>{character}</div></div>
{guild}{creds}</details>"""


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
        chips = ""
        for m in mechs:
            when = ", ".join(f"{int(t // 60)}:{int(t % 60):02d}" for t in m.times[:4]) + ("…" if len(m.times) > 4 else "")
            what = "interrupt" if m.kind == "interrupt" else f"{m.players_per_kill:.0f} players per kill"
            cost = f", ~{m.cost:g} s of movement" if m.cost else ""
            checked = " checked" if m.name.lower() in current or m.key in current else ""
            chips += (f'<label class="chip" title="{e(when)}"><input type="checkbox" name="assign" value="{e(m.name)}"'
                      f'{checked}>{e(m.name)} <span class="meta">{what}{cost}</span></label>')
        article = "an" if spec[:1].lower() in "aeiou" else "a"
        assigns = (f'<p class="small muted">Tick what you handle on this fight. Timings and the movement it costs '
                   f'{article} {e(spec)} come from the logs; hover a mechanic to see when it happens.</p>'
                   f'<div class="chips">{chips}</div>')
    elif kills:
        assigns = ('<p class="muted small">The mechanics are collected during the first prep (about 2 quota points '
                   'per kill); you can tick yours afterwards.</p>')
    else:
        assigns = ('<p class="muted small">No kill collected yet: the first prep collects ~200 ranked kills from '
                   'Warcraft Logs (a few minutes to an hour depending on your API quota).</p>')
    last = prepared_link(enc, difficulty)
    from paf import bossguide
    from paf.icons import icons_for

    sections = bossguide.load(enc.id, difficulty)
    guide = ""
    from paf import i18n

    if sections and i18n.language() != "en":  # the journal in the player's language, before the first prep too
        from paf import names

        try:
            names.build(enc.id, difficulty, bossguide.spell_refs(sections), i18n.wow_locale())
        except Exception:  # noqa: BLE001 - offline: the guide stays in English
            pass
    if sections:
        gicons = icons_for(bossguide.spell_refs(sections))
        guide = (f"<h2>The boss in 60 seconds</h2>{bossguide.summary_html(sections, 'damage')}"
                 f"<details class='card'><summary>Every ability, phase by phase (Encounter Journal)</summary>"
                 f"{bossguide.abilities_html(sections, mechanics=mechs, icon_map=gicons)}</details>")
    raid_now = current_raid(enc, difficulty)
    g = settings.get("guild")
    raid_said = f"the latest public log of {g}" if g else ""
    nxt = "<button type='button' class='btn go next'>Next &rarr;</button>"
    back = "<button type='button' class='btn ghost prev'>&larr; Back</button>"
    body = f"""<p class="small"><a href="/">&larr; Home</a></p>
<h1>{e(enc.name)} <span class="pill gold">{e(DIFF_LABELS.get(difficulty, difficulty))}</span></h1>
<p class="lead">{kills} ranked kills in your corpus.{last}</p>
<form method="post" action="/prep" class="ob story" data-boss="{enc.id}-{e(difficulty)}">
<input type="hidden" name="boss" value="{enc.id}"><input type="hidden" name="difficulty" value="{e(difficulty)}">
<ol class="ob-dots" aria-hidden="true"><li></li><li></li><li></li><li></li></ol>
<section class="ob-step" data-step="goal"><h2>What do you want from this boss?</h2>
<div class="goals">
<label class="goal"><input type="radio" name="goal" value="boss"><span><b>Boss damage</b>
<small>Progress: your raid lead wants everyone on the boss. Cooldowns and gear aim at the boss.</small></span></label>
<label class="goal"><input type="radio" name="goal" value="total"><span><b>Pad the adds</b>
<small>Your job is the adds, or you farm for parses: cooldowns and gear for total damage.</small></span></label>
<label class="goal"><input type="radio" name="goal" value="auto" checked><span><b>Let my raid decide</b>
<small>The prep reads your raid's log: if the others already cover the adds, you stay on the boss.</small></span></label>
</div><div class="ob-actions">{nxt}</div></section>
<section class="ob-step" data-step="assigns"><h2>Are you assigned to something?</h2>{assigns}
<p class="small muted">Each assignment is simulated: its moves and its downtime change your cooldown plan and your gear.</p>
<div class="ob-actions">{back}{nxt}</div></section>
<section class="ob-step" data-step="raid"><h2>Your raid</h2>
<input name="raid" style="width:100%" value="{e(raid_now)}"
placeholder="Link to one of your raid's logs: https://www.warcraftlogs.com/reports/..." aria-label="Raid log link">
<p class="small muted" style="margin-top:6px">{e(raid_hint())}</p>
<div class="ob-actions">{back}{nxt}</div></section>
<section class="ob-step" data-step="go"><h2>Ready to prepare</h2>
<ul class="recap">
<li data-if="goal=boss">For <b>boss damage</b>.</li><li data-if="goal=total">For <b>total damage</b> (pad the adds).</li>
<li data-if="goal=auto">Your raid's log decides between boss damage and padding.</li>
<li data-if="assigns"><span>With your assignments:</span> <b class="recap-assigns"></b></li>
<li data-if="no-assigns">No assignment.</li>
<li data-if="raid">Your raid: <b class="recap-raid"></b></li>
<li data-if="no-raid">Your raid: <b>{e(raid_said) if raid_said else "none (the prep shows both plans)"}</b></li>
</ul>
<details class="what-sim"><summary>What to sim</summary>
<label><input type="checkbox" name="gear" checked> Best gear from your bags, and what this boss drops for you</label>
<label><input type="checkbox" name="optimize" checked> Ideal cooldown plan per objective
<span class="muted small">(the slowest part: 20 to 40 min)</span></label></details>
<div class="ob-actions">{back}<button class="btn go">Prepare this fight &rarr;</button></div>
<p class="small muted">Runs on your computer; you can follow it live.</p></section>
</form>
{(f"<details class='card'><summary>The boss in 60 seconds</summary>{guide}</details>") if guide else ""}
{_story_css()}{STORY_JS}
<h2>Advanced</h2>
<details class="card"><summary>Your fight plan: your own movements, Bloodlust, Power Infusion</summary>
{plan_block(enc, difficulty)}</details>
<details class="card"><summary>What you know about this boss: damage amps, targets to ignore</summary>
{notes_block(enc, difficulty)}</details>"""
    return page(enc.name, body)


def _story_css() -> str:
    from paf.onboarding import CSS as ONBOARDING_CSS

    return "<style>" + ONBOARDING_CSS + """
.story{margin:10px 0 30px;max-width:640px}
.story h2{font:600 26px/1.2 'Fraunces',Georgia,serif;margin:0 0 16px;text-transform:none;letter-spacing:0;color:var(--fg)}
.goals{display:grid;gap:10px}
.goal{display:block;cursor:pointer}
.goal input{position:absolute;opacity:0;pointer-events:none}
.goal>span{display:flex;flex-direction:column;gap:4px;padding:14px 16px;border:1.5px solid var(--line);border-radius:12px;
  transition:border-color .15s,background .15s}
.goal b{font-size:17px} .goal small{color:var(--muted);font-size:14.5px;line-height:1.45}
.goal input:checked+span{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 10%,transparent)}
.goal input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
.recap{list-style:none;padding:0;margin:0 0 14px;display:grid;gap:8px;font-size:17px}
.recap li::before{content:"\\2713";color:var(--pos);font-weight:700;margin-right:10px}
.recap li[hidden]{display:none}
.what-sim{margin:6px 0 0} .what-sim label{display:block;margin:6px 0}
</style>"""


STORY_JS = """<script>
(function(){
var f = document.querySelector('form.story'); if (!f) return;
var steps = [].slice.call(f.querySelectorAll('.ob-step')), dots = [].slice.call(f.querySelectorAll('.ob-dots li'));
var key = 'paf-goal:' + f.dataset.boss, at = 0;
try { var g = localStorage.getItem(key); var r = g && f.querySelector('input[name=goal][value=' + g + ']'); if (r) r.checked = true; } catch (e) {}
function recap(){
  var goal = (f.querySelector('input[name=goal]:checked') || {}).value || 'auto';
  var picked = [].slice.call(f.querySelectorAll('input[name=assign]:checked')).map(function(i){
    var t = i.parentNode.cloneNode(true); var m = t.querySelector('.meta'); if (m) m.remove(); return t.textContent.trim(); });
  var raid = (f.querySelector('input[name=raid]') || {}).value || '';
  f.querySelector('.recap-assigns').textContent = picked.join(', ');
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
  if (steps[at].dataset.step === 'go') recap();
}
f.querySelectorAll('.next').forEach(function(b){ b.addEventListener('click', function(){ show(at + 1); }); });
f.querySelectorAll('.prev').forEach(function(b){ b.addEventListener('click', function(){ show(at - 1, true); }); });
f.querySelectorAll('input[name=goal]').forEach(function(r){ r.addEventListener('change', function(){
  try { localStorage.setItem(key, r.value); } catch (e) {} setTimeout(function(){ show(at + 1); }, 200); }); });
f.addEventListener('submit', function(){ var r = f.querySelector('input[name=goal]:checked');
  try { if (r) localStorage.setItem(key, r.value); } catch (e) {} });
show(0);
})();
</script>"""

def prepared_link(enc, difficulty: str) -> str:
    from paf.corpus.template import report_key

    key = report_key(enc.name, difficulty)
    return f' <a href="/view/{e(key)}">Open the last prep sheet &rarr;</a>' if any(
        x["key"] == key for x in prepared()) else ""


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


def raid_hint() -> str:
    g = settings.get("guild")
    if g:
        return (f"Empty: the latest public log of {g} is used. Your raid's composition and DPS decide whether you pad "
                f"the adds or stay on the boss.")
    return ("Optional. Your raid's composition and DPS decide whether you pad the adds or stay on the boss. "
            "Or set your guild once on the home page.")


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
        text = p.read_text(encoding="utf-8-sig")
    elif template_path(enc.name, difficulty).is_file():
        text = plan_template(Fight.load(template_path(enc.name, difficulty)))
    else:
        return ('<p class="muted small">Available after the first prep: your own movements (a soak at 2:45, a '
                "dodge...), Bloodlust and Power Infusion timings, on top of the rebuilt fight.</p>")
    return f"""<p class="small muted">What you do on this fight that the logs cannot guess, one line each: <code>2:45 move 6</code>
(6 s of movement), <code>5:30 move 8 shift -5..+5</code> (the optimizer picks the best moment), <code>lust 0:00</code>,
<code>pi 0:20 2:30</code>, <code>no boss-movement</code>. The mechanics ticked above are added as <code>assign</code> lines.
Every sim of the prep (gear, talents, cooldowns) runs on this fight.</p>
<form method="post" action="/plan"><input type="hidden" name="boss" value="{enc.id}">
<input type="hidden" name="difficulty" value="{e(difficulty)}"><textarea name="plan">{e(text)}</textarea>
<p><button class="btn ghost">Save the plan</button></p></form>"""


def notes_block(enc, difficulty: str) -> str:
    """What the player knows about the boss: the detected mechanics with their evidence, editable."""
    from paf.corpus.template import template_path
    from paf.notes import notes_path

    p = notes_path(template_path(enc.name, difficulty))
    if not p.is_file():
        return ('<p class="muted small">Available after the first prep: the detected mechanics (units sharing the '
                "boss's health, damage amps...) with their evidence.</p>")
    text = p.read_text(encoding="utf-8-sig")
    return f"""<p class="small muted">Detected in the logs, with the evidence. Correct what the logs cannot tell (e.g. the
real damage amp of a heart: <code>amp Venomous Heart 2.0</code>), save, then prepare the fight again.</p>
<form method="post" action="/notes"><input type="hidden" name="boss" value="{enc.id}">
<input type="hidden" name="difficulty" value="{e(difficulty)}"><textarea name="notes">{e(text)}</textarea>
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
Your spec and the boss help."></textarea></label>
<label class="chip"><input type="checkbox" name="log" checked> Attach the {"log of this prep" if jid else "app's log"}
(below; your Warcraft Logs key, user folder and email addresses are removed)</label>
<label class="chip"><input type="checkbox" name="perf" checked> Attach performance measures: your computer's CPU,
cores and memory, and how long each step took (nothing personal: no name, no log, no folder). They help make the app
faster on every computer.</label>
<div class="cta"><button class="btn">Send</button></div></form>
<details class="card"><summary>Exactly what is sent</summary><pre class="log">{e(preview[-20000:])}</pre></details>'''


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
    return page("Preparing...", f"<div id='live'>{live}</div>{guide_preview(job['args'])}{js}", job=jid)


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
        + (" <span class='pill gold'>in progress</span>" if state == "now" else "")
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
                "<p class='small muted'>Your computer stays usable: the simulations run at low priority.</p>")
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
            elif url.path in ("/onboard/skip", "/onboard/finish"):
                from paf import onboarding

                onboarding.finish()
                self._redirect("/")
            elif url.path == "/boss":
                self._send(boss_page(q.get("boss", ""), q.get("difficulty", settings.get("difficulty"))))
            elif url.path == "/tools":
                from paf import workshop

                self._send(page("Tools", workshop.index()))
            elif url.path.startswith("/tool/"):
                from paf import workshop
                from paf.webtools import tool_page

                name = url.path.rsplit("/", 1)[1]
                body = (None if q.get("raw") else workshop.tool_page(name, _encounters())) or \
                    tool_page(name, _encounters())
                self._send(page("Tool", body) if body else page("Not found", "<p>Unknown tool.</p>"),
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
            elif self.path in ("/character/select", "/character/remove"):
                from paf import characters

                s = (form.get("slug") or [""])[0]
                (characters.select if self.path.endswith("select") else characters.remove)(s)
                self._redirect("/")
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
                self._send(page("Update", run_update()))
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
                        try:
                            settings.set_value(key, form[key][0])
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
            elif self.path == "/prep":
                from paf.corpus.template import report_key
                from paf.encounters import raid_encounters
                from paf.wcl import WCLClient

                boss_id = int(form["boss"][0])
                difficulty = form.get("difficulty", ["heroic"])[0]
                write_assigns(boss_id, difficulty, form.get("assign", []))
                raid = (form.get("raid") or [""])[0]
                if raid.strip():
                    from paf.raidneed import report_code

                    try:
                        report_code(raid)
                    except ValueError as ex:
                        self._send(page("Invalid log link", f"<p>{e(str(ex))}. "
                                                            f"<a href='javascript:history.back()'>Back</a></p>"), 400)
                        return
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
