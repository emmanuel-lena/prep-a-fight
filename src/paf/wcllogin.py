"""Log in with Warcraft Logs: the player's own account instead of an API key they create (OAuth2 PKCE).

The app is a public client of Warcraft Logs (no secret: PUBLIC_CLIENT_ID is not a secret). "Connect" opens the
player's browser on Warcraft Logs' authorize page; Warcraft Logs sends the browser back to a small one-shot server on
REDIRECT (the same address is registered on the client), which trades the code for a token, saved in the data folder
(login file) and refreshed when it expires. paf.wcl then queries the user endpoint with it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from paf.config import data_dir

AUTHORIZE_URL = "https://www.warcraftlogs.com/oauth/authorize"
PORT = 47823
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
# the app's public client on Warcraft Logs (not a secret; PAF_WCL_PUBLIC_CLIENT="" hides the login)
PUBLIC_CLIENT_ID = os.environ.get("PAF_WCL_PUBLIC_CLIENT", "01a12525-5a69-7292-a435-04b1b8202589")
WAIT = 600.0  # seconds the callback server waits for the player
REFRESH_EARLY = 3600.0  # refresh this long before the token expires

_state: dict = {"status": "", "error": "", "url": ""}  # status: "" | waiting | ok | error
_lock = threading.Lock()


def available() -> bool:
    return bool(PUBLIC_CLIENT_ID)


def login_file() -> Path:
    return data_dir() / "wcl_login.json"


def load() -> dict | None:
    """The saved login: access_token, refresh_token, expires_at, client_id."""
    try:
        saved = json.loads(login_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved if saved.get("access_token") else None


def logged_in() -> bool:
    return load() is not None


def logout() -> None:
    login_file().unlink(missing_ok=True)


def _save(payload: dict, client_id: str, previous: dict | None = None) -> dict:
    saved = {"access_token": payload["access_token"],
             "refresh_token": payload.get("refresh_token") or (previous or {}).get("refresh_token", ""),
             "expires_at": time.time() + float(payload.get("expires_in", 3600)),
             "client_id": client_id}
    f = login_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(saved), encoding="utf-8")
    return saved


def token(transport) -> str:
    """A valid access token of the saved login, refreshed when it is about to expire."""
    saved = load()
    if saved is None:
        raise RuntimeError("not logged in to Warcraft Logs")
    if time.time() < saved["expires_at"] - REFRESH_EARLY or not saved.get("refresh_token"):
        return saved["access_token"]
    return refresh(transport, saved)["access_token"]


def refresh(transport, saved: dict | None = None) -> dict:
    from paf.wcl import TOKEN_URL, WCLError

    saved = saved or load()
    if not saved or not saved.get("refresh_token"):
        raise WCLError("Your Warcraft Logs login expired: connect again (Settings).")
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": saved["refresh_token"],
                                   "client_id": saved["client_id"], "scope": ""}).encode()
    status, raw = transport(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        raise WCLError(f"Your Warcraft Logs login expired (HTTP {status}): connect again (Settings).")
    return _save(json.loads(raw), saved["client_id"], saved)


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def authorize_url(client_id: str, state: str, verifier: str) -> str:
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": "",
        "state": state, "code_challenge": _challenge(verifier), "code_challenge_method": "S256"})


def exchange(code: str, verifier: str, client_id: str, transport=None) -> dict:
    """Trades the authorize code for a token and saves it."""
    from paf.wcl import TOKEN_URL, WCLError, _urllib_transport

    body = urllib.parse.urlencode({"grant_type": "authorization_code", "client_id": client_id,
                                   "redirect_uri": REDIRECT, "code_verifier": verifier, "code": code}).encode()
    status, raw = (transport or _urllib_transport)(TOKEN_URL, body,
                                                   {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200:
        raise WCLError(f"Warcraft Logs refused the login (HTTP {status})")
    return _save(json.loads(raw), client_id)


def status() -> dict:
    with _lock:
        return {k: v for k, v in _state.items() if k != "url"}


def _set(status_: str, error: str = "") -> None:
    with _lock:
        _state.update(status=status_, error=error)


PAGE = ("<!doctype html><meta charset='utf-8'><title>prep-a-fight</title><body style='font:16px system-ui;"
        "background:#181219;color:#f2eaf1;display:grid;place-items:center;height:90vh;margin:0'><div "
        "style='text-align:center'><h1 style='font-weight:600'>{title}</h1><p>{text}</p></div>")


def start(open_browser=None) -> str:
    """Starts a login: the one-shot callback server, then the authorize page in the player's browser.
    Returns the authorize URL (also shown to the player in case the browser does not open)."""
    if not available():
        raise RuntimeError("the Warcraft Logs login is not set up in this build")
    if open_browser is None:
        import webbrowser

        open_browser = webbrowser.open
    with _lock:
        again = _state["url"] if _state["status"] == "waiting" else ""
    if again:  # a second click while the first login waits: the same page again
        open_browser(again)
        return again
    client_id, verifier, state = PUBLIC_CLIENT_ID, secrets.token_urlsafe(64), secrets.token_urlsafe(24)

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args) -> None:  # quiet
            pass

        def do_GET(self) -> None:  # noqa: N802
            url = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            if url.path != "/callback":
                self.send_error(404)
                return
            if q.get("state") != state or "code" not in q:
                title, text = "Not connected", "Warcraft Logs did not confirm the login. Try again from the app."
                _set("error", q.get("error_description") or q.get("error") or "the login was cancelled")
            else:
                try:
                    exchange(q["code"], verifier, client_id)
                    title, text = "Connected to Warcraft Logs", "You can close this tab and go back to prep-a-fight."
                    _set("ok")
                except Exception as ex:  # noqa: BLE001 - shown in the app
                    title, text = "Not connected", str(ex)
                    _set("error", str(ex))
            data = PAGE.format(title=title, text=text).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            threading.Thread(target=server.shutdown, daemon=True).start()

    try:
        server = HTTPServer(("127.0.0.1", PORT), Callback)
    except OSError as ex:
        raise RuntimeError(f"port {PORT} is busy (another login is open?): {ex}") from ex
    _set("waiting")

    def serve() -> None:
        timer = threading.Timer(WAIT, server.shutdown)
        timer.daemon = True
        timer.start()
        server.serve_forever()
        server.server_close()
        timer.cancel()
        if status()["status"] == "waiting":
            _set("error", "No answer from Warcraft Logs: try again.")

    threading.Thread(target=serve, daemon=True).start()
    url = authorize_url(client_id, state, verifier)
    with _lock:
        _state["url"] = url
    open_browser(url)
    return url
