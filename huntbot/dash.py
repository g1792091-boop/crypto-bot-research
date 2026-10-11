"""huntbot dashboard (추세 사냥 모의 봇): password login, read-only views of the runner's snapshots.

    python -m huntbot dash            serve on HUNTBOT_DASH_HOST:HUNTBOT_DASH_PORT (default 127.0.0.1:8092)
    python -m huntbot dash hash       print a password hash for HUNTBOT_DASH_PASSWORD_HASH

The login pieces are copied from the candidate league's (candleague/dash.py: pbkdf2 password hash, signed session cookie, same-origin
POST, HUNTBOT_DASH_OPEN=1 only on a Tailscale or loopback address with a Host check). Reads only <snap>/*.json (the
runner writes them; DeepSeek money is never in them, D11); never writes; never talks to Binance; a missing file shows
"준비 중". The page builds every element with text nodes (static/js/dom.js): no HTML from strings.
"""


import asyncio
import re
import os
import sys
import threading
import urllib.parse
from typing import Optional

import base64
import hashlib
import hmac
import math
import time

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SESSION_S = 7 * 86_400
COOKIE = "huntbot_session"
STATIC_TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
PUBLIC_FILES = frozenset(("hb.css", "login.js", "icon.svg"))
SNAP_FILES = {"status": "status.json", "lineup": "lineup.json", "systems": "systems.json",
              "positions": "positions.json", "trades": "trades.json"}


# ---------------------------------------------------------------- login pieces (copied from candleague/dash.py)
def hash_password(password: str, salt: Optional[bytes] = None, rounds: int = 200_000) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2${rounds}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def _sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_token(secret: bytes, now: Optional[float] = None) -> str:
    exp = int((now or time.time()) + SESSION_S)
    return f"{exp}.{_sign(secret, str(exp))}"


def token_ok(secret: bytes, token: Optional[str], now: Optional[float] = None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < (now or time.time()):
        return False
    return hmac.compare_digest(sig, _sign(secret, exp))


def same_origin(req) -> bool:
    origin = req.headers.get("origin")
    if origin is not None:
        o = urllib.parse.urlsplit(origin)
        if not o.netloc or o.netloc.lower() != req.headers.get("host", "").lower():
            return False
    return req.headers.get("sec-fetch-site", "") != "cross-site"


def finite_json(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [finite_json(v) for v in o]
    return o


def open_ok(host: str) -> bool:
    """Without the password only on a Tailscale address (100.64.0.0/10) or this machine (loopback)."""
    import ipaddress
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return False
    return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")


def host_ok(header: str, hosts) -> bool:
    """The request's Host is one of ``hosts`` or this machine's Tailscale name (DNS rebinding guard, open mode)."""
    h = (header or "").strip().lower()
    h = h[1:h.index("]")] if h.startswith("[") and "]" in h else h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if h in hosts:
        return True
    import socket
    me = socket.gethostname().lower().split(".")[0]
    return bool(me) and (h == me or (h.startswith(me + ".") and h.endswith(".ts.net")))


def _static_files() -> frozenset:
    out = []
    for root, _dirs, files in os.walk(STATIC):
        for f in files:
            if os.path.splitext(f)[1] in STATIC_TYPES:
                out.append(os.path.relpath(os.path.join(root, f), STATIC).replace(os.sep, "/"))
    return frozenset(out)


STATIC_FILES = _static_files()


class SnapCache:
    """Each snapshot file parsed once per change (several viewers and screens ask at once)."""

    def __init__(self, snap: str):
        self.snap = snap
        self._lock = threading.Lock()
        self._docs: dict = {}

    def get(self, name: str):
        import json
        p = os.path.join(self.snap, name)
        try:
            st = os.stat(p)
        except OSError:
            return None
        key = (st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._docs.get(name)
            if hit and hit[0] == key:
                return hit[1]
        try:
            with open(p) as fh:
                doc = finite_json(json.load(fh))
        except (OSError, ValueError):
            return None
        with self._lock:
            self._docs[name] = (key, doc)
        return doc


def create_app(snap: str, password_hash: str, secret: bytes, open_: bool = False, hosts=None):
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    cache = SnapCache(snap)

    def authed(req: Request) -> bool:
        return open_ or token_ok(secret, req.cookies.get(COOKIE))

    @app.middleware("http")
    async def headers(req: Request, call_next):
        if open_ and hosts is not None and not host_ok(req.headers.get("host", ""), hosts):
            return Response("이 대시보드는 Tailscale 주소로 여세요 (예: http://100.x.x.x:8092)", status_code=400)
        resp = await call_next(req)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self'; "
                                                   "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        return resp

    @app.get("/login")
    def login_page():
        if open_:
            return RedirectResponse("/", status_code=303)
        return FileResponse(os.path.join(STATIC, "login.html"), headers={"Cache-Control": "no-cache"})

    @app.post("/login")
    async def login(req: Request):
        if not same_origin(req):
            return Response(status_code=403)
        form = urllib.parse.parse_qs((await req.body()).decode(errors="replace"))
        pw = (form.get("password") or [""])[0]
        if not password_hash or not check_password(pw, password_hash):
            await asyncio.sleep(1.0)
            return RedirectResponse("/login?bad=1", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, make_token(secret), max_age=SESSION_S, httponly=True, samesite="strict",
                        secure=req.url.scheme == "https")
        return resp

    @app.post("/logout")
    def logout(req: Request):
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/")
    def index(req: Request):
        if not authed(req):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/static/{name:path}")
    def static(name: str, req: Request):
        if name not in STATIC_FILES or (name not in PUBLIC_FILES and not authed(req)):
            return Response(status_code=404)
        return FileResponse(os.path.join(STATIC, name), media_type=STATIC_TYPES[os.path.splitext(name)[1]],
                            headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(os.path.join(STATIC, "icon.svg"), media_type="image/svg+xml")

    def snap_route(key: str):
        def route(req: Request):
            if not authed(req):
                return JSONResponse({"error": "login"}, status_code=401)
            doc = cache.get(SNAP_FILES[key])
            return JSONResponse(doc if doc is not None else {"missing": True, "status": "준비 중"})
        route.__name__ = f"api_{key}"
        return route

    for k in SNAP_FILES:
        app.get(f"/api/{k}")(snap_route(k))

    @app.get("/api/system/{sid:path}")
    def system(sid: str, req: Request):
        """One system's row (systems.json), its last 100 trades and its equity by the hour (sys/<hash>.json)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        rows = (cache.get("systems.json") or {}).get("rows") or []
        row = next((r for r in rows if r.get("id") == sid), None)
        if row is None:
            return JSONResponse({"error": "unknown system"}, status_code=404)
        f = row.get("file") or ""
        doc = cache.get(f"sys/{f}") if re.fullmatch(r"[0-9a-f]{16}\.json", f) else None
        doc = doc or {}
        return JSONResponse({"row": row, "trades": doc.get("trades") or [], "hourly": doc.get("hourly")})

    return app


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hash"]:
        import getpass
        pw = getpass.getpass("대시보드 비밀번호: ")
        if pw != getpass.getpass("한 번 더: "):
            print("두 번 입력한 비밀번호가 다릅니다", file=sys.stderr)
            return 2
        print(hash_password(pw))
        return 0
    import uvicorn

    from . import config as CFG
    host = os.environ.get("HUNTBOT_DASH_HOST", "127.0.0.1")
    want_open = os.environ.get("HUNTBOT_DASH_OPEN") == "1"
    open_ = want_open and open_ok(host)
    if want_open and not open_:
        print(f"HUNTBOT_DASH_OPEN=1 but {host} is not a Tailscale or loopback address: the login stays on",
              file=sys.stderr)
    secret = os.environ.get("HUNTBOT_DASH_SECRET", "").encode()
    if not open_ and (len(secret) < 16 or not os.environ.get("HUNTBOT_DASH_PASSWORD_HASH")):
        print("HUNTBOT_DASH_SECRET (16자 이상)과 HUNTBOT_DASH_PASSWORD_HASH가 필요합니다", file=sys.stderr)
        return 2
    app = create_app(CFG.snap_dir(), os.environ.get("HUNTBOT_DASH_PASSWORD_HASH", ""), secret or os.urandom(32),
                     open_=open_, hosts={host.lower(), "localhost", "127.0.0.1", "::1"})
    uvicorn.run(app, host=host, port=int(os.environ.get("HUNTBOT_DASH_PORT", "8092")), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
