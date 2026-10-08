"""The visual identity shared by every page (web app, prep sheet, timelines): one palette, light and dark.

Palette: vintage grape #5c415d, vintage grape 2 #694966, dusty lavender #74526c, golden sand #dbd053,
golden bronze #c89933. Grapes carry the structure (header, primary buttons in light mode), the golds the
accents (highlights, primary buttons in dark mode, key numbers). Gold is never used for body text on a light
background (too little contrast).
"""

from __future__ import annotations

TOKENS = """
:root{
  --grape:#5c415d;--grape-2:#694966;--lavender:#74526c;--sand:#dbd053;--bronze:#c89933;
  --bg:#f6f2f5;--surface:#ffffff;--surface-2:#f1eaf0;--line:#e3d8e1;--fg:#2a1f2b;--muted:#6f5c6d;
  --link:#694966;--primary:#5c415d;--on-primary:#ffffff;--accent:#c89933;--accent-soft:#f6efd2;
  --pos:#2f7d3e;--neg:#b3392e;--warn:#9a6a10;
  --shadow:0 1px 2px rgba(42,31,43,.06),0 4px 16px rgba(42,31,43,.06);
  --header:linear-gradient(90deg,#5c415d,#694966 55%,#74526c);
  --stripe:linear-gradient(90deg,#dbd053,#c89933);
  --radius:10px;
  --font-display:"Chakra Petch","Bahnschrift","Segoe UI",system-ui,sans-serif;
  --font-body:"IBM Plex Sans","Segoe UI",system-ui,-apple-system,sans-serif;
  --font-data:"IBM Plex Mono",Consolas,ui-monospace,monospace;
  --glow:radial-gradient(1100px 520px at 12% -8%,rgba(116,82,108,.16),transparent 70%),radial-gradient(900px 480px at 100% 0%,rgba(219,208,83,.08),transparent 70%);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#181219;--surface:#221a23;--surface-2:#2b212c;--line:#3b2e3c;--fg:#f2eaf1;--muted:#b6a3b3;
  --link:#dbd053;--primary:#c89933;--on-primary:#1c1410;--accent:#dbd053;--accent-soft:#3a3320;
  --pos:#8fd18b;--neg:#f08f84;--warn:#e7c35a;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25);
  --glow:radial-gradient(1100px 560px at 12% -8%,rgba(116,82,108,.35),transparent 70%),radial-gradient(900px 480px at 100% 0%,rgba(200,153,51,.10),transparent 70%);color-scheme:dark;
}}
:root[data-theme="dark"]{
  --bg:#181219;--surface:#221a23;--surface-2:#2b212c;--line:#3b2e3c;--fg:#f2eaf1;--muted:#b6a3b3;
  --link:#dbd053;--primary:#c89933;--on-primary:#1c1410;--accent:#dbd053;--accent-soft:#3a3320;
  --pos:#8fd18b;--neg:#f08f84;--warn:#e7c35a;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.25);
  --glow:radial-gradient(1100px 560px at 12% -8%,rgba(116,82,108,.35),transparent 70%),radial-gradient(900px 480px at 100% 0%,rgba(200,153,51,.10),transparent 70%);color-scheme:dark;
}
"""

BASE = """
*{box-sizing:border-box}
html{color-scheme:light dark}
body{margin:0;background:var(--glow),var(--bg);background-attachment:fixed;color:var(--fg);font:15px/1.6 var(--font-body)}
h1,h2,h3,.brand,.btn,button,.kpi .v,.kpi .l,.tabs a,.sev,.pill,th,.step .num{font-family:var(--font-display)}
td.n,.gain,.kpi .v,code,pre{font-variant-numeric:tabular-nums}
a{color:var(--link);text-decoration:none} a:hover{text-decoration:underline}
main{max-width:1040px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:30px;line-height:1.15;margin:0 0 6px;letter-spacing:.005em;font-weight:700;text-wrap:balance}
h2{font-size:17px;margin:34px 0 12px;letter-spacing:.06em;text-transform:uppercase;font-weight:600;color:var(--muted);text-wrap:balance}
h3{font-size:16px;margin:0 0 8px;font-weight:600;letter-spacing:.01em}
p{margin:0 0 10px}
.muted{color:var(--muted)} .small{font-size:13px} .tiny{font-size:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;
  margin:10px 0;box-shadow:var(--shadow)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%}
td,th{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:0}
td.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.pos{color:var(--pos);font-weight:600} .neg{color:var(--neg)}
button,.btn{font:inherit;font-weight:600;background:var(--primary);color:var(--on-primary);border:0;border-radius:10px;
  padding:9px 16px;cursor:pointer;display:inline-block;text-decoration:none}
button:hover,.btn:hover{filter:brightness(1.08);text-decoration:none}
.btn.big{padding:12px 22px;font-size:16px}
.btn.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}
input,select,textarea{font:inherit;color:var(--fg);background:var(--surface-2);border:1px solid var(--line);
  border-radius:8px;padding:8px 10px}
input:focus,select:focus,textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
a:focus-visible,button:focus-visible,.btn:focus-visible,summary:focus-visible{outline:2px solid var(--accent);
  outline-offset:2px;border-radius:6px}
.chip:focus-within{outline:2px solid var(--accent);outline-offset:2px}
input[type=checkbox],input[type=radio]{accent-color:var(--bronze);width:16px;height:16px;padding:0;vertical-align:-3px}
textarea{width:100%;min-height:150px;font:12.5px/1.45 ui-monospace,Consolas,monospace}
label{display:block;margin:6px 0}
details>summary{cursor:pointer;color:var(--muted);font-size:13px;margin:6px 0}
pre{white-space:pre-wrap;font:12px/1.45 ui-monospace,Consolas,monospace}
code{font:12.5px ui-monospace,Consolas,monospace;background:var(--surface-2);padding:1px 5px;border-radius:5px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
/* header */
.topbar{background:var(--header);color:#fff;position:relative}
.topbar::after{content:"";position:absolute;left:0;right:0;bottom:0;height:3px;background:var(--stripe)}
.topbar .in{max-width:1040px;margin:0 auto;padding:12px 16px 15px;display:flex;gap:16px;align-items:center;
  flex-wrap:wrap}
.topbar a{color:#fff} .brand{font-weight:700;font-size:17px;letter-spacing:.01em}
.nav-back{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;cursor:pointer;border:1px solid rgba(255,255,255,.35);background:rgba(255,255,255,.08);color:#fff;font:inherit;font-weight:600}
.nav-back:hover{background:rgba(255,255,255,.18)} .nav-back[hidden]{display:none}
.nav-home{text-decoration:none;margin-right:4px} .nav-home:hover{text-decoration:none} .nav-home svg{display:block}
@media (max-width:640px){.nav-back span{display:none}}
.brand b{color:var(--sand)}
.topbar .nav{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
.topbar .nav a{padding:6px 12px;border-radius:8px;color:#f3e9f2;font-size:14px}
.topbar .nav a.on,.topbar .nav a:hover{background:rgba(255,255,255,.14);text-decoration:none}
.topbar select{background:rgba(255,255,255,.12);color:#fff;border-color:rgba(255,255,255,.25)}
.topbar select option{color:#2a1f2b}
/* building blocks */
.step{display:flex;gap:14px;align-items:flex-start}
.step .num{flex:none;width:30px;height:30px;border-radius:50%;background:var(--accent-soft);color:var(--fg);
  border:2px solid var(--accent);display:grid;place-items:center;font-weight:700;font-size:14px}
.step .body{flex:1;min-width:0}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;
  background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.pill.gold{background:var(--accent-soft);color:var(--fg);border-color:var(--accent)}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;
  box-shadow:var(--shadow);display:block;color:var(--fg)}
a.tile:hover{border-color:var(--accent);text-decoration:none}
.kpi .v{font-size:26px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.kpi .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
.kpi .s{font-size:12.5px;color:var(--muted);margin-top:4px}
.hero{background:var(--surface);border:1px solid var(--line);border-left:5px solid var(--accent);
  border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow);margin:14px 0}
.hero .verdict{font-size:20px;font-weight:700;margin-bottom:6px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border:1px solid var(--line);border-radius:999px;
  background:var(--surface-2);cursor:pointer;margin:0;font-size:14px}
.chip:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
.chip input{accent-color:var(--bronze)}
.chip .meta{color:var(--muted);font-size:12px}
.notice{border-left:4px solid var(--warn);background:var(--surface-2);padding:10px 14px;border-radius:8px}
a.wh{color:inherit;text-decoration:none;border-bottom:1px dotted var(--muted)}
@media (max-width:640px){h1{font-size:22px} .kpi .v{font-size:22px}}
"""

POLISH = """
.kpi .v{font-size:32px;font-weight:700;letter-spacing:.01em}
.kpi .l{font-weight:600;letter-spacing:.08em}
.pill{font-size:11px;letter-spacing:.05em;text-transform:uppercase;font-weight:600}
.btn,button{letter-spacing:.03em;transition:transform .12s ease,box-shadow .12s ease,filter .12s ease}
.btn:hover,button:hover{box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent)}
.btn:active,button:active{transform:translateY(1px)}
.tile{transition:border-color .15s ease,transform .15s ease}
a.tile:hover{transform:translateY(-2px)}
.card,.tile{background:color-mix(in srgb,var(--surface) 92%,transparent);backdrop-filter:blur(4px)}
.lead{max-width:68ch}
p,li{max-width:80ch}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

CSS = TOKENS + BASE + POLISH

# Google Fonts (the faces fall back to system ones offline)
HEAD = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" '
        'href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Mono:wght@500&family=IBM+Plex+Sans:wght@400;500;600'
        '&display=swap">')


BACK = ("<button type='button' class='nav-back' hidden aria-label='Go back' title='Go back' onclick='history.back()'>"
        "&larr; <span>Go back</span></button><script>(function(){var b=document.currentScript.previousElementSibling;"
        "if(history.length>1&&location.pathname!=='/')b.hidden=false;})();</script>")
# a Home button with a little house, back to the home page from anywhere (hidden on the home page itself)
HOME = ("<a class='nav-back nav-home' href='/' hidden aria-label='Home' title='Home'><svg viewBox='0 0 24 24' "
        "width='16' height='16' aria-hidden='true'><path d='M3 11.5 12 4l9 7.5M6 10v9.5h4.5V15h3v4.5H18V10' "
        "fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>"
        "<span>Home</span></a><script>(function(){var b=document.currentScript.previousElementSibling;"
        "if(location.pathname!=='/')b.hidden=false;})();</script>")


def topbar(right: str = "", home: str = "/", back: bool = False, who: str = "") -> str:
    """The gradient header with the brand; `right` holds navigation or selectors. back: a Back button (the desktop
    window has no browser buttons), shown when there is a page to go back to; who: the active character's menu."""
    return (f'<header class="topbar"><div class="in">{BACK + HOME if back else ""}<a class="brand" href="{home}">'
            f'prep-a-<b>fight</b></a>{who}<div class="nav">{right}</div></div></header>')


# the game's class colors: the app takes the active character's (accent, its soft background, the header's stripe)
CLASS_COLORS = {"deathknight": "#C41E3A", "demonhunter": "#A330C9", "druid": "#FF7C0A", "evoker": "#33937F",
                "hunter": "#AAD372", "mage": "#3FC7EB", "monk": "#00FF98", "paladin": "#F48CBA", "priest": "#FFFFFF",
                "rogue": "#FFF468", "shaman": "#0070DD", "warlock": "#8788EE", "warrior": "#C69B6D"}


def class_accent(class_name: str) -> str:
    """A <style> giving the app the color of the class: darkened on the light theme, lightened a little on the dark
    one, so every class reads on both. '' for an unknown class."""
    color = CLASS_COLORS.get((class_name or "").lower().replace(" ", ""))
    if not color:
        return ""
    dark = ("--accent:color-mix(in srgb,var(--class) 82%,#fff);"
            "--accent-soft:color-mix(in srgb,var(--class) 22%,#181219)")
    return (f"<style>:root{{--class:{color};--accent:color-mix(in srgb,var(--class) 68%,#000);"
            "--accent-soft:color-mix(in srgb,var(--class) 16%,#fff);"
            "--stripe:linear-gradient(90deg,var(--class),color-mix(in srgb,var(--class) 55%,#000))}"
            f"@media (prefers-color-scheme:dark){{:root:not([data-theme=\"light\"]){{{dark}}}}}"
            f":root[data-theme=\"dark\"]{{{dark}}}</style>")
