"""후보 리그 dashboard: password login, read-only views of the engine's snapshots (CONTRACT.md 3-4).

    python -m candleague.dash            serve on CANDLEAGUE_DASH_HOST:CANDLEAGUE_DASH_PORT (default 127.0.0.1:8091)
    python -m candleague.dash hash       print a password hash for CANDLEAGUE_DASH_PASSWORD_HASH

Reads only CANDLEAGUE_SNAP (league.json, trades.json); never writes there; a missing file shows "준비 중". The login
pieces are the demo lab dashboard's (pbkdf2 password hash, signed session cookie, same-origin POST)."""

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
STATIC_FILES = ("app.js", "league.css", "login.css", "vendor/lightweight-charts.standalone.production.js")


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


def create_app(snap: str, password_hash: str, secret: bytes, live=None):
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if live is None:
        from .live import Live
        live = Live.from_env()

    def authed(req: Request) -> bool:
        return token_ok(secret, req.cookies.get(COOKIE))

    @app.middleware("http")
    async def headers(req: Request, call_next):
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
        return FileResponse(os.path.join(STATIC, "login.html"))

    @app.post("/login")
    async def login(req: Request):
        if not same_origin(req):
            return Response(status_code=403)
        form = urllib.parse.parse_qs((await req.body()).decode(errors="replace"))
        pw = (form.get("password") or [""])[0]
        if not password_hash or not check_password(pw, password_hash):
            time.sleep(1.0)
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
        return FileResponse(os.path.join(STATIC, "index.html"))

    @app.get("/static/{name:path}")
    def static(name: str, req: Request):
        if name not in STATIC_FILES or (name not in ("league.css", "login.css") and not authed(req)):
            return Response(status_code=404)
        return FileResponse(os.path.join(STATIC, name))

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
    secret = os.environ.get("CANDLEAGUE_DASH_SECRET", "").encode()
    if len(secret) < 16 or not os.environ.get("CANDLEAGUE_DASH_PASSWORD_HASH"):
        print("CANDLEAGUE_DASH_SECRET (16자 이상)과 CANDLEAGUE_DASH_PASSWORD_HASH가 필요합니다", file=sys.stderr)
        return 2
    app = create_app(os.environ.get("CANDLEAGUE_SNAP", "/var/lib/candleague/snap"),
                     os.environ["CANDLEAGUE_DASH_PASSWORD_HASH"], secret)
    uvicorn.run(app, host=os.environ.get("CANDLEAGUE_DASH_HOST", "127.0.0.1"),
                port=int(os.environ.get("CANDLEAGUE_DASH_PORT", "8091")), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
