"""후보 리그 dashboard: password login, read-only views of the engine's snapshots (CONTRACT.md 3-4).

    python -m candleague.dash            serve on CANDLEAGUE_DASH_HOST:CANDLEAGUE_DASH_PORT (default 127.0.0.1:8091)
    python -m candleague.dash hash       print a password hash for CANDLEAGUE_DASH_PASSWORD_HASH

CANDLEAGUE_DASH_OPEN=1 (setup_env.sh --no-password) serves it without the password, only on a Tailscale or loopback
address (open_ok); the firewall keeps the port to Tailscale.

Reads only CANDLEAGUE_SNAP (league.json, trades.json) and candleague/data/strategies_ko.json; never writes; a missing
file shows "준비 중". The page is the rule bot's v4 look (static/: the v4 css and the demo lab's js kit, copied). The login
pieces are the demo lab dashboard's (pbkdf2 password hash, signed session cookie, same-origin POST)."""

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.parse
from typing import Optional

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SESSION_S = 7 * 86_400
COOKIE = "candleague_session"


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
    """NaN / inf -> None (the browser's JSON.parse refuses NaN)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [finite_json(v) for v in o]
    return o


def read_snap(snap: str, name: str):
    try:
        with open(os.path.join(snap, name)) as fh:
            return finite_json(json.load(fh))
    except (OSError, ValueError):
        return None


KLINE_TFS = ("15m", "30m", "1h", "4h")
STATIC_TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}


def _static_files() -> frozenset:
    """Every .js / .css / .svg file under static/ (relative paths): the only files /static/ serves."""
    out = []
    for root, _dirs, files in os.walk(STATIC):
        for f in files:
            if os.path.splitext(f)[1] in STATIC_TYPES:
                out.append(os.path.relpath(os.path.join(root, f), STATIC).replace(os.sep, "/"))
    return frozenset(out)


STATIC_FILES = _static_files()
PUBLIC_FILES = frozenset(("tokens.css", "base.css", "login.css", "login.js", "icon.svg"))   # the login page's own
META_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "strategies_ko.json")


def klines_query(params) -> Optional[dict]:
    """coin / tf / limit of /api/klines, whitelisted (None when anything is off)."""
    from .live import COINS
    coin, tf = params.get("coin", ""), params.get("tf", "")
    try:
        limit = int(params.get("limit", "300"))
    except ValueError:
        return None
    if coin not in COINS or tf not in KLINE_TFS or not 50 <= limit <= 1000:
        return None
    return {"coin": coin, "tf": tf, "limit": limit}


def open_ok(host: str) -> bool:
    """A dashboard may run without the password only where nobody but the owners' own devices can reach it: a Tailscale
    address (100.64.0.0/10) or this machine (loopback). Anything else keeps the login."""
    import ipaddress
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return False
    return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")


def host_ok(header: str, hosts) -> bool:
    """The request's Host (without its port) is one of ``hosts``, or this machine's Tailscale name (``name`` or
    ``name.<tailnet>.ts.net``). Without the password a page on another site could otherwise point its own name at the
    dashboard's address (DNS rebinding) and read the league from the owner's browser."""
    h = (header or "").strip().lower()
    h = h[1:h.index("]")] if h.startswith("[") and "]" in h else h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if h in hosts:
        return True
    import socket
    me = socket.gethostname().lower().split(".")[0]
    return bool(me) and (h == me or (h.startswith(me + ".") and h.endswith(".ts.net")))


def create_app(snap: str, password_hash: str, secret: bytes, live=None, open_: bool = False, hosts=None):
    """``open_``: no password (owners 2026-10-11, "비밀번호 없애고 싶은데"); main() allows it only on a Tailscale or
    loopback address (open_ok), and then answers only requests addressed to this dashboard (``hosts``, host_ok)."""
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if live is None:
        from .live import Live
        live = Live.from_env()

    def authed(req: Request) -> bool:
        return open_ or token_ok(secret, req.cookies.get(COOKIE))

    @app.middleware("http")
    async def headers(req: Request, call_next):
        if open_ and hosts is not None and not host_ok(req.headers.get("host", ""), hosts):
            return Response("이 대시보드는 Tailscale 주소로 여세요 (예: http://100.x.x.x:8091)", status_code=400)
        resp = await call_next(req)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"     # no-referrer makes a form POST's Origin "null"
        # style attributes: the chart library adds one <style> element (the rule bot's and the demo lab's CSP allow it too)
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
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
            await asyncio.sleep(1.0)                       # slows guessing without stalling other requests
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

    cp_cache: dict = {}

    @app.get("/api/checkpoints")
    def checkpoints(req: Request):
        """The confirmed checkpoint results (WATCH_PREREG 3) for every checkpoint date already reached, computed from the
        snapshot exactly as research/fullgrid/diag/watch_check.py does (candleague/checkpoint.py); "final" once the
        engine has processed past that date. Cached until the snapshot changes."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        from . import checkpoint as CP
        from . import summary as SM
        today = time.strftime("%Y-%m-%d", time.gmtime())
        due = [c for c in SM.CHECKPOINTS if c["date"] <= today]
        if not due:
            return JSONResponse({"due": [], "results": {}})
        try:
            key = (os.path.getmtime(os.path.join(snap, "league.json")), os.path.getmtime(os.path.join(snap, "trades.json")),
                   tuple(c["date"] for c in due))
        except OSError:
            return JSONResponse({"due": [c["date"] for c in due], "results": {}, "status": "준비 중"})
        if cp_cache.get("key") != key:
            league, book = read_snap(snap, "league.json"), read_snap(snap, "trades.json")
            if not league or not league.get("accounts") or book is None:
                return JSONResponse({"due": [c["date"] for c in due], "results": {}, "status": "준비 중"})
            res = {}
            for c in due:
                r = CP.check(league, book, c["date"])
                r["final"] = int(league.get("done_ms") or 0) >= SM.day_ms(c["date"])
                r["ko"] = c["ko"]
                res[c["date"]] = r
            cp_cache.update(key=key, doc=finite_json({"due": [c["date"] for c in due], "results": res}))
        return JSONResponse(cp_cache["doc"])

    @app.get("/api/meta")
    def meta(req: Request):
        """Korean names, entry rules, parameter meanings and each pick's character (candleague/data/strategies_ko.json)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        return JSONResponse(read_snap(os.path.dirname(META_FILE), os.path.basename(META_FILE)) or {})

    @app.get("/api/live")
    def api_live(req: Request):
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        return JSONResponse(finite_json(live.live()))

    @app.get("/api/klines")
    def api_klines(req: Request):
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        q = klines_query(req.query_params)
        if q is None:
            return JSONResponse({"error": "coin / tf / limit"}, status_code=400)
        return JSONResponse(finite_json(live.klines(q["coin"], q["tf"], q["limit"])))

    @app.get("/api/league")
    def league(req: Request):
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        return JSONResponse(read_snap(snap, "league.json") or {"status": "준비 중"})

    @app.get("/api/fills")
    def fills(req: Request):
        """The league's newest closed trades over every account (newest first, at most 300)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        book = read_snap(snap, "trades.json") or {}
        rows = [{**t, "account": aid} for aid, b in book.items() for t in (b.get("trades") or [])]
        rows.sort(key=lambda t: t.get("exit_time") or 0, reverse=True)
        return JSONResponse({"fills": rows[:300]})

    @app.get("/api/trades/{aid}")
    def trades(aid: str, req: Request):
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        book = read_snap(snap, "trades.json") or {}
        return JSONResponse(book.get(aid) or {"equity": None, "trades": []})

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
    host = os.environ.get("CANDLEAGUE_DASH_HOST", "127.0.0.1")
    want_open = os.environ.get("CANDLEAGUE_DASH_OPEN") == "1"
    open_ = want_open and open_ok(host)
    if want_open and not open_:
        print(f"CANDLEAGUE_DASH_OPEN=1 but {host} is not a Tailscale or loopback address: the login stays on",
              file=sys.stderr)
    secret = os.environ.get("CANDLEAGUE_DASH_SECRET", "").encode()
    if not open_ and (len(secret) < 16 or not os.environ.get("CANDLEAGUE_DASH_PASSWORD_HASH")):
        print("CANDLEAGUE_DASH_SECRET (16자 이상)과 CANDLEAGUE_DASH_PASSWORD_HASH가 필요합니다", file=sys.stderr)
        return 2
    app = create_app(os.environ.get("CANDLEAGUE_SNAP", "/var/lib/candleague/snap"),
                     os.environ.get("CANDLEAGUE_DASH_PASSWORD_HASH", ""), secret or os.urandom(32), open_=open_,
                     hosts={host.lower(), "localhost", "127.0.0.1", "::1"})
    uvicorn.run(app, host=host, port=int(os.environ.get("CANDLEAGUE_DASH_PORT", "8091")), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
