"""The desktop app: the local web app in its own window (pywebview, on the WebView2 engine Windows ships),
without a console or a browser tab. Falls back to the browser when pywebview is missing."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from paf.config import data_dir, load_dotenv, migrate_old_home

TITLE = "prep-a-fight"
ICON = Path(__file__).parent / "assets" / "prep-a-fight.ico"


def _quiet_streams() -> None:
    """Started without a console (pythonw), print() and tracebacks need somewhere to go."""
    if sys.stdout is None or sys.stderr is None:
        log_dir = data_dir() / "web"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives with the app
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def _own_taskbar_icon() -> None:
    """Run under pythonw.exe, the window would be grouped with Python and show its icon in the taskbar."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("prep-a-fight.app")
        except (AttributeError, OSError):
            pass


def _serve_in_process(window) -> bool:
    """Have WebView2 ask the app itself for http://paf.local/... (paf.inproc): no network connection at all.
    False when the engine cannot be reached (the window then uses the local server). WebView2 objects are only
    touched on the window's own thread (from another thread they block)."""
    if not window.events.loaded.wait(20):  # the loading page is shown: the engine is ready
        return False
    form = window.native
    if form is None:
        return False
    from Microsoft.Web.WebView2.Core import CoreWebView2WebResourceContext
    from System import Action, Array, Byte
    from System.IO import MemoryStream

    from paf import inproc

    def on_request(sender, args) -> None:
        uri = str(args.Request.Uri)
        if not uri.startswith(inproc.BASE + "/"):
            return
        path = uri[len(inproc.BASE):] or "/"
        method = str(args.Request.Method)
        headers = {str(h.Key): str(h.Value) for h in args.Request.Headers.GetEnumerator()}
        body = b""
        if args.Request.Content is not None:
            ms = MemoryStream()
            args.Request.Content.CopyTo(ms)
            body = bytes(ms.ToArray())
        deferral = args.GetDeferral()
        env = sender.Environment

        def work() -> None:
            try:
                status, reason, head, data = inproc.serve(method, path, headers, body)
                status, head, data = inproc.as_page(status, head, data)
            except Exception as ex:  # noqa: BLE001 - shown in the window rather than a blank page
                status, reason, data = 500, "Error", str(ex).encode()
                head = [("Content-Type", "text/plain; charset=utf-8")]

            def reply() -> None:
                lines = "\r\n".join(f"{k}: {v}" for k, v in head if k.lower() not in ("content-length", "connection"))
                args.Response = env.CreateWebResourceResponse(MemoryStream(Array[Byte](data)), status,
                                                              reason or "OK", lines)
                deferral.Complete()

            form.Invoke(Action(reply))

        threading.Thread(target=work, daemon=True).start()

    done, ok = threading.Event(), [False]

    def install() -> None:
        try:
            core = form.browser.webview.CoreWebView2  # on the window's thread
            core.AddWebResourceRequestedFilter(f"{inproc.BASE}/*", CoreWebView2WebResourceContext.All)
            core.WebResourceRequested += on_request
            ok[0] = True
        finally:
            done.set()

    form.Invoke(Action(install))
    done.wait(5)
    return ok[0]


def _open(window, server_url: str) -> None:
    """Show the app: through paf.local when possible, else through the local server."""
    from paf import inproc, web

    try:
        inside = _serve_in_process(window)
    except Exception as ex:  # noqa: BLE001 - the local server always works as a fallback
        print(f"in-process pages unavailable ({ex}): using the local server")
        inside = False
    print(f"pages {'in process (paf.local)' if inside else 'through the local server'}", flush=True)
    web.PUBLIC_BASE = server_url.rstrip("/")  # links that open in the browser need a real address
    window.load_url(f"{inproc.BASE}/" if inside else server_url)


def main() -> int:
    moved = migrate_old_home()  # before anything opens a file in the data folder
    _quiet_streams()
    if moved:
        print(f"Moved from ~/.paf to {data_dir()}: {', '.join(moved)}")
    load_dotenv()
    _own_taskbar_icon()
    from paf import web
    from paf.simc_install import ensure_simc

    ensure_simc()  # first launch of an installed copy: SimulationCraft downloads while the player sets up
    from paf.update import check_in_background

    check_in_background()

    server = web.Server(("127.0.0.1", 0), web.Handler)  # a free port: several copies never collide
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        import webview
    except ImportError:
        import webbrowser

        print(f"pywebview is not installed: prep-a-fight opens in your browser ({url}). Ctrl+C to stop.")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    try:
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # Wowhead / Warcraft Logs links
    except (AttributeError, TypeError):
        pass
    from paf.loading import startup_page

    window = webview.create_window(TITLE, html=startup_page(), width=1320, height=920, min_size=(900, 600),
                                   background_color="#181219")
    web.QUIT["hook"] = window.destroy  # an update is being installed: close, the installer reopens the app
    webview.start(_open, (window, url), icon=str(ICON) if ICON.is_file() else None)
    server.shutdown()
    server.server_close()
    try:
        from paf.cache import prune_all

        prune_all()
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
