"""실거래 대시보드 (the 실거래 site, owners 10/19: "대시보드가 지금 규칙봇 안에 있잖아 제거하고 따로 실거래용 봇 대시보드
사이트를 따로 만들고 싶어. 대시보드 형식은 지금 실거래봇 대시보드 형식으로 똑같이"). Read-only.

    DASH_PASSWORD_HASH=... DASH_SECRET=... python -m paperbot.livedash --host 127.0.0.1 --port 8093

- The page: static/live/index.html with its boot module static/live/main.js (the slim shell static/live/shell.js), over
  the rule bot's v4 core and the very 실거래 screens (static/v4/screens/livebots*.js): every 실거래 tab is a menu item
  (core/routes.js LIVE_SCREENS, <html data-site="live">, core/site.js). Versioned files as on the rule bot's page
  (dash/assets.py ``Assets`` over static/v4, static/vendor and static/live).
- Login: the same password as the rule bot's dashboard (DASH_PASSWORD_HASH, DASH_SECRET from /etc/paperbot/dash.env; the
  hash and token helpers of dash/app.py) but its OWN session cookie (``COOKIE``, signed with a key derived from
  DASH_SECRET, ``live_secret``): cookies belong to a host, not a port, so the two sites never read or overwrite each
  other's session, and a session of one is no session of the other.
- Routes: only what the 실거래 screens and the core modules they load ask for (tests/test_livedash_app.py scans them):
  the 실거래 additions of dash/more (livebots, livemissed, livetape, livepos, livewhy = 진입 근거, part B's liveinsight the
  moment it exists),
  the market pieces the 요약 / 차트 tabs show (ticks, movers, topstats, vplevels; /api/candles, /api/ticker, /api/levels,
  /api/events, /api/liq, /api/market), the server clock and code version (/api/time), the strategy names (/api/board:
  names only here) and the price alerts the rule bot's dashboard keeps (/api/price-alerts: read-only here; making one
  stays on the rule bot's dashboard). No rule-bot stream, rooms, inbox writes, agents or analysis machinery.
- Every database is opened read-only (the dash/more modules' own rule: mode=ro + query_only); nothing here places an
  order or changes a bot. Same headers as the rule bot's dashboard: the strict CSP, never in a frame, gzip except the
  live streams, pages and API answers never stored.
- Binds to 127.0.0.1 by default; the service binds the Tailscale address (deploy/paperbot-livedash.service). Never the
  internet.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import os
import time
from types import SimpleNamespace
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from ..dash import app as D
from ..dash.assets import REVALIDATE, Assets, asset_files

STATIC = D.STATIC
LIVE_LOGIN = os.path.join(STATIC, "live", "login.html")
COOKIE = "pb_live_session"            # never the rule bot's "pb_session" (the same host, another port)
SESSION_S = D.SESSION_S
# the page's folders: the rule bot's v4 core and screens, the chart library, the 실거래 site's own page and boot module
ASSET_DIRS = ("v4", "vendor", "live")
PUBLIC_PATHS = ("/login", "/api/login", "/static/login.css", "/static/login.js", "/static/live/login.html",
                # the phone home-screen shortcut: a browser fetches these without the login cookie (no data in them)
                "/static/live/manifest.json", "/static/icon.svg", "/static/icon-192.png", "/static/icon-512.png",
                "/static/apple-touch-icon.png")
# dash/more modules the 실거래 screens call (each registers its own GET routes; read-only)
MODULES = ("livebots", "livemissed", "livetape", "livepos", "livewhy", "ticks", "movers", "topstats", "vplevels")
# part B's 실거래 additions: registered when the module is there (an app without it still starts)
OPTIONAL_MODULES = ("liveinsight",)
PRICE_ALERTS_KO = "가격 알림은 규칙봇 대시보드(8080)에서 걸어 주세요 · 실거래 사이트는 보기만 해요"


def live_secret(secret: bytes) -> bytes:
    """The 실거래 site's session key, derived from DASH_SECRET: a rule-bot session token is never a live one (and back)."""
    return hmac.new(secret, b"paperbot-livedash-session-v1", hashlib.sha256).digest()


def live_assets(static_dir: str = STATIC) -> Assets:
    """The page's files by content hash (dash/assets.py): static/live/index.html, its boot module and every v4 file."""
    return Assets(static_dir, dirs=ASSET_DIRS, index="live/index.html", boot="live/main.js", code_dirs=("live", "v4"))


def register_modules(app, ctx, names=MODULES, optional=OPTIONAL_MODULES) -> dict:
    """Register the dash/more modules the 실거래 screens need; an optional one that is not there yet is skipped (any
    other import error is raised: a broken module must not hide behind a missing one)."""
    done: dict = {}
    for name in tuple(names) + tuple(optional):
        full = f"paperbot.dash.more.{name}"
        try:
            mod = importlib.import_module(full)
        except ModuleNotFoundError as exc:
            if name in optional and exc.name == full:
                continue
            raise
        done[name] = mod.register(app, ctx)
    return done


def create_app(password_hash: Optional[str], secret: bytes, candles=D.fetch_candles, ticker=D.fetch_ticker,
               market=D.fetch_market, frames=D.fetch_frame, liq_db: Optional[str] = "/var/lib/paperbot/liq.db",
               inbox_db: Optional[str] = "/var/lib/paperbot/inbox.db", static_dir: str = STATIC) -> FastAPI:
    app = FastAPI(title="실거래", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(D.GZipExceptStream, minimum_size=D.GZIP_MIN_BYTES)
    assets = app.state.assets = live_assets(static_dir)
    key = live_secret(secret)
    fails: dict[str, list[float]] = {}

    def authed(req: Request) -> bool:
        return password_hash is None or D.token_ok(key, req.cookies.get(COOKIE))

    async def _guarded(req: Request, call_next):
        path = req.url.path
        if path in PUBLIC_PATHS:            # exact paths only
            return await call_next(req)
        if not authed(req):
            if path.startswith("/api/"):
                return JSONResponse({"error": "login required"}, status_code=401)
            return RedirectResponse(D.login_redirect(path, req.url.query))
        resp = await call_next(req)
        if path.startswith("/static/") and not path.endswith((".html", "/")):
            if "cache-control" not in resp.headers:
                resp.headers["Cache-Control"] = REVALIDATE
        else:
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.middleware("http")
    async def guard(req: Request, call_next):
        resp = await _guarded(req, call_next)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = D.CSP
        return resp

    # ---------------------------------------------------------------- login (the rule bot's helpers, this site's cookie)
    @app.get("/login")
    def login_page():
        return FileResponse(os.path.join(static_dir, "live", "login.html"))

    @app.post("/api/login")
    async def login(req: Request):
        ip = req.client.host if req.client else "?"
        recent = [t for t in fails.get(ip, []) if time.time() - t < 900]
        if len(recent) >= 10:
            raise HTTPException(429, "too many attempts, wait 15 minutes")
        body = await D._json_object(req)
        if password_hash is None or D.check_password(str(body.get("password", "")), password_hash):
            fails.pop(ip, None)
            resp = JSONResponse({"ok": True})
            resp.set_cookie(COOKIE, D.make_token(key), max_age=SESSION_S, httponly=True, samesite="strict",
                            secure=bool(os.environ.get("DASH_SECURE_COOKIE")))
            return resp
        fails[ip] = recent + [time.time()]
        raise HTTPException(401, "wrong password")

    @app.post("/api/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    # ---------------------------------------------------------------- the page
    @app.get("/")
    def index():
        """The 실거래 site (static/live/index.html; its files load from /static/v-<ver>/..., dash/assets.py)."""
        return HTMLResponse(assets.index_html())

    @app.get("/api/time")
    def get_time():
        """The server clock (the countdowns) and the page code's fingerprint (core/version.js: '새 버전')."""
        return {"now": int(time.time() * 1000), "ver": assets.ver()}

    @app.get("/api/board")
    def get_board():
        """Names only (the rule bot's accounts are on its own dashboard): the strategies' Korean names the pages show
        (core/store.js reads strategy_ko / names_ko from this key; the 관제 and 순위 tabs watch it for them)."""
        from ..agents.roster3 import STRATEGY_KO
        return {"names_only": True, "accounts": [], "strategy_ko": dict(STRATEGY_KO), "names_ko": D.names_ko(),
                "note_ko": "실거래 사이트: 규칙봇 계좌 목록은 규칙봇 대시보드에만 있어요 (여기는 매매법 이름만)"}

    # ---------------------------------------------------------------- the market (the same fetchers and rules as dash/app.py)
    @app.get("/api/candles")
    def get_candles(symbol: str, interval: str = "15m", limit: int = 300):
        if symbol not in D.TICKER_SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        if interval not in D.CANDLE_INTERVALS:
            raise HTTPException(400, "unknown interval")
        return candles(symbol, interval, min(max(limit, 2), 1500))

    @app.get("/api/ticker")
    def get_ticker():
        return ticker()

    @app.get("/api/market")
    def get_market():
        """Outside context for 일정 (fear & greed, dominance, indexes); the rule bot's fetcher and its cache."""
        try:
            return market()
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "시장 자료를 받지 못했습니다")

    @app.get("/api/events")
    def get_events(days_back: int = 60, days_ahead: int = 30):
        """Registered US macro releases around now (data/macro_events.csv, no outside fetch)."""
        from .. import events as EV
        now = int(time.time() * 1000)
        lo = now - min(max(int(days_back), 0), 400) * 86_400_000
        hi = now + min(max(int(days_ahead), 0), 400) * 86_400_000
        return {"events": [e.as_dict() for e in EV.all_events() if lo <= e.ts_ms <= hi], "problems": EV.problems()}

    levels_cache: dict = {}

    @app.get("/api/levels")
    def get_levels(symbol: str = "BTCUSDT", tf: str = "15m"):
        """Support / resistance of the last closed bar (entry_marks.chart_levels), as on the rule bot's charts."""
        from .. import entry_marks
        if symbol not in D.TICKER_SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        if tf not in D.LEVEL_TFS:
            return {"levels": [], "note": "no levels for this timeframe"}
        df = frames(symbol, tf, entry_marks.chart_bars(tf))
        if df is None or len(df) < 320:
            raise HTTPException(503, "no price data")
        k = (symbol, tf, str(df["ts"].iloc[-1]))
        if k not in levels_cache:
            if len(levels_cache) > 128:
                levels_cache.clear()
            try:
                levels_cache[k] = {**entry_marks.chart_levels(df, tf), "bar": str(df["ts"].iloc[-1])}
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(503, f"levels failed: {type(exc).__name__}")
        return levels_cache[k]

    # 시장 강제청산 (요약's left column): the liquidation recorder's liq.db, through the rule bot's two read-only readers
    # (dash/app.py Data.liquidations / liquidations_market: they open liq.db mode=ro and use nothing else of Data)
    liq = D.Data(liq_db or "liq.db")

    @app.get("/api/liq")
    def get_liq(symbol: str = "BTCUSDT", minutes: int = 60):
        path = liq_db or ""
        if symbol == "ALL":
            return liq.liquidations_market(path, min(max(minutes, 5), 1440))
        if symbol not in D.TICKER_SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        return liq.liquidations(path, symbol, min(max(minutes, 5), 1440))

    # 가격 알림 선 on the 실거래 charts: the alerts the rule bot's dashboard keeps in inbox.db, read-only here (its Rooms
    # reader alone: nothing of the rooms is started, inbox.db is never created or written by this site)
    alerts = D.Rooms(None, inbox_db) if inbox_db else None

    @app.get("/api/price-alerts")
    def get_price_alerts():
        if alerts is None:
            return {"alerts": [], "sender_alive": False, "sender_hb": None, "max": None, "read_only": True}
        return {**alerts.price_alerts(), "read_only": True, "note_ko": PRICE_ALERTS_KO}

    @app.post("/api/price-alerts")
    def post_price_alert():
        raise HTTPException(403, PRICE_ALERTS_KO)

    @app.post("/api/price-alerts/{alert_id}/{action}")
    def change_price_alert(alert_id: int, action: str):
        raise HTTPException(403, PRICE_ALERTS_KO)

    # ---------------------------------------------------------------- the 실거래 additions and the market pieces (dash/more)
    ctx = SimpleNamespace(data=None, rooms=None, db=None, daily_db=None, agents_db=None, checkpoint_db=None,
                          candles=candles, frames=frames, ticker=ticker, market=market, site="live")
    app.state.more = register_modules(app, ctx)

    app.mount("/static", asset_files(static_dir, assets), name="static")
    return app
