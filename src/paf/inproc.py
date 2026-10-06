"""Serve the app's pages inside the process, without a network connection.

The desktop window asks for http://paf.local/... and WebView2 hands each request to the app (WebResourceRequested):
the request is run through the same handler as the local web server (paf.web.Handler), on an in-memory socket. No
connection is ever opened, so web filters, antivirus and firewalls that sit on local traffic (AdGuard filters
WebView2 like a browser and cut the app's connections to itself) have nothing to intercept.
"""

from __future__ import annotations

import io

HOST = "paf.local"
BASE = f"http://{HOST}"


class _Socket:
    """The bits of a socket that http.server uses: the request comes from memory, the response goes to memory."""

    def __init__(self, raw: bytes) -> None:
        self._in = io.BytesIO(raw)
        self.out = bytearray()

    def makefile(self, mode: str, *args, **kwargs):
        if "r" in mode:
            return self._in
        raise OSError("write through sendall")

    def sendall(self, data: bytes) -> None:
        self.out += data

    def settimeout(self, *_):
        pass

    def setsockopt(self, *_):
        pass

    def shutdown(self, *_):
        pass

    def close(self):
        pass


class _Server:
    """What a request handler reads from its server."""

    def __init__(self) -> None:
        self.server_address = ("127.0.0.1", 0)
        self.server_name = HOST
        self.server_port = 80


Response = tuple[int, str, list[tuple[str, str]], bytes]


def serve(method: str, path: str, headers: dict[str, str] | None = None, body: bytes = b"") -> Response:
    """(status, reason, headers, body) of one request to the app, run in this process."""
    from paf import web

    head = {k: v for k, v in (headers or {}).items() if k.lower() not in ("content-length", "connection", "host")}
    head["Host"] = HOST
    head["Content-Length"] = str(len(body))
    head["Connection"] = "close"
    lines_in = [f"{method} {path} HTTP/1.1"] + [f"{k}: {v}" for k, v in head.items()]
    raw = ("\r\n".join(lines_in) + "\r\n\r\n").encode("latin-1")
    sock = _Socket(raw + body)
    web.Handler(sock, ("127.0.0.1", 0), _Server())
    data = bytes(sock.out)
    top, _, payload = data.partition(b"\r\n\r\n")
    lines = top.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ", 2) if lines else ["HTTP/1.0", "500", "No response"]
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 500
    reason = parts[2] if len(parts) > 2 else ""
    out_headers = [tuple(x.split(": ", 1)) for x in lines[1:] if ": " in x]
    return status, reason, out_headers, payload


def as_page(status: int, headers: list[tuple[str, str]], body: bytes) -> tuple[int, list[tuple[str, str]], bytes]:
    """A redirect becomes a tiny page that goes there (the most reliable way inside WebView2)."""
    if status in (301, 302, 303, 307, 308):
        to = next((v for k, v in headers if k.lower() == "location"), "/")
        page = (f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={to}">'
                f'<script>location.replace({to!r})</script>').encode()
        return 200, [("Content-Type", "text/html; charset=utf-8")], page
    return status, headers, body
