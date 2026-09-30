"""Paper v3 dashboard: read-only web view of paper3.db (docs/dashboard.md).

    DASH_PASSWORD_HASH=... DASH_SECRET=... python -m paperbot.dash --db paper3.db --port 8080

- Opens the store read-only; the live runner stays the only writer.
- Login: one password (PBKDF2 hash in DASH_PASSWORD_HASH, make one with
  ``python -m paperbot.dash hash``) and a signed session cookie (DASH_SECRET).
- Live updates: /api/stream (server-sent events) sends changed accounts, new
  trades and alerts every few seconds. Prices tick in the browser straight
  from Binance's public mark-price stream.
- Binds to 127.0.0.1 by default. Reach it through Tailscale or an SSH tunnel;
  never expose it directly (see docs/dashboard.md).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.request
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
COOKIE = "pb_session"
SESSION_S = 7 * 86400
TRADE_TFS = ("5m", "15m", "30m", "1h", "4h")


# ---------------------------------------------------------------- auth
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


# ---------------------------------------------------------------- data
class Data:
    def __init__(self, db: str):
        self.db = db

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        return c

    def state(self, c, key: str) -> Optional[tuple[int, dict]]:
        r = c.execute("SELECT ts, data FROM state WHERE k = ?", (key,)).fetchone()
        return None if r is None else (int(r["ts"]), json.loads(r["data"]))

    def board(self) -> dict:
        with self.conn() as c:
            accts = [dict(r) for r in c.execute(
                "SELECT account_id, strategy, timeframe, kind, created_ts, parent FROM accounts ORDER BY rowid")]
            st = self.state(c, "accounts")
            eng = st[1]["engines"] if st else {}
            stats = {r["account_id"]: dict(r) for r in c.execute(
                "SELECT account_id, COUNT(*) AS trades, SUM(pnl > 0) AS wins, SUM(pnl) AS pnl, "
                "SUM(exit_reason = 'LOCK') AS locks, MAX(exit_time) AS last_exit, "
                "AVG(leverage) AS avg_lev FROM trades GROUP BY account_id")}
        rows = []
        for a in accts:
            e = eng.get(a["account_id"], {})
            s = stats.get(a["account_id"], {})
            n = s.get("trades") or 0
            pos = e.get("position")
            rows.append({
                **a, "wallet": e.get("wallet"), "max_drawdown": e.get("max_drawdown"),
                "bust": e.get("bust", False), "trades": n,
                "win_rate": (s.get("wins") or 0) / n if n else None, "pnl": s.get("pnl") or 0.0,
                "locks": s.get("locks") or 0, "avg_leverage": s.get("avg_lev"),
                "last_exit": s.get("last_exit"),
                "position": None if not pos else {
                    "symbol": pos["symbol"], "side": pos["side"], "qty": pos["qty"],
                    "entry": pos["entry_price"], "entry_time": pos["entry_time"],
                    "leverage": pos["leverage"], "margin": pos["margin"], "stop": pos["stop_price"],
                    "stop_initial": pos.get("stop_initial"), "lock_roe": pos.get("lock_roe"),
                    "liq": pos["liq_price"]},
            })
        best_random = {}
        for r in rows:
            if r["kind"] == "random" and r["wallet"] is not None:
                best_random[r["timeframe"]] = max(best_random.get(r["timeframe"], 0.0), r["wallet"])
        for r in rows:
            b = best_random.get(r["timeframe"])
            r["beats_random"] = None if b is None or r["wallet"] is None else r["wallet"] > b
        return {"ts": st[0] if st else None, "accounts": rows, "best_random": best_random}

    def account(self, aid: str) -> dict:
        with self.conn() as c:
            a = c.execute("SELECT * FROM accounts WHERE account_id = ?", (aid,)).fetchone()
            if a is None:
                raise KeyError(aid)
            trades = [dict(r) for r in c.execute(
                "SELECT id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data "
                "FROM trades WHERE account_id = ? ORDER BY id DESC LIMIT 500", (aid,))]
            for t in trades:
                d = json.loads(t.pop("data"))
                t.update(side=d["side"], entry_price=d["entry_price"], exit_price=d["exit_price"],
                         stop_initial=d.get("stop_initial"), lock_roe=d.get("lock_roe"),
                         fees=d["fees"], funding=d["funding"])
            eq = [{"t": r["ts"], "v": r["equity"]} for r in c.execute(
                "SELECT ts, equity FROM equity WHERE account_id = ? ORDER BY ts", (aid,))]
            counts = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM outcomes WHERE account_id = ? GROUP BY status", (aid,))}
            st = self.state(c, "accounts")
        e = (st[1]["engines"].get(aid) if st else None) or {}
        return {"account": dict(a), "state": e, "trades": trades, "equity": eq, "signals": counts}

    def status(self) -> dict:
        with self.conn() as c:
            hb = self.state(c, "heartbeat")
            run = self.state(c, "run")
            alerts = [dict(r) for r in c.execute(
                "SELECT ts, level, text FROM alerts WHERE level != 'INFO' ORDER BY rowid DESC LIMIT 50")]
            sig = [dict(r) for r in c.execute(
                "SELECT timeframe, status, COUNT(*) AS n, AVG(delay_ms) AS avg_delay FROM signal_log "
                "WHERE bar_close > ? GROUP BY timeframe, status",
                (int(time.time() * 1000) - 86_400_000,))]
        return {"now": int(time.time() * 1000), "heartbeat": hb, "run": run, "alerts": alerts,
                "signals_24h": sig}

    def signals(self, tf: Optional[str], limit: int) -> list[dict]:
        q, args = "SELECT * FROM signal_log", []
        if tf:
            q += " WHERE timeframe = ?"
            args.append(tf)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(min(max(limit, 1), 1000))
        with self.conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def since(self, trade_id: int, alert_row: int) -> dict:
        with self.conn() as c:
            trades = [dict(r) for r in c.execute(
                "SELECT id, account_id, symbol, exit_time, exit_reason, leverage, pnl, roe, equity_after "
                "FROM trades WHERE id > ? ORDER BY id LIMIT 200", (trade_id,))]
            alerts = [dict(r) for r in c.execute(
                "SELECT rowid AS rid, ts, level, text FROM alerts WHERE rowid > ? AND level != 'INFO' "
                "ORDER BY rowid LIMIT 50", (alert_row,))]
            hb = self.state(c, "heartbeat")
        return {"trades": trades, "alerts": alerts, "heartbeat": hb}


# ---------------------------------------------------------------- candles (public Binance data)
_CANDLE_CACHE: dict = {}


def fetch_candles(symbol: str, interval: str, limit: int = 300) -> list:
    key = (symbol, interval, limit)
    hit = _CANDLE_CACHE.get(key)
    if hit and time.time() - hit[0] < 20:
        return hit[1]
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    with urllib.request.urlopen(url, timeout=10) as r:
        rows = json.loads(r.read())
    out = [{"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4])} for k in rows]
    _CANDLE_CACHE[key] = (time.time(), out)
    return out


# ---------------------------------------------------------------- app
def create_app(db: str, password_hash: Optional[str], secret: bytes, candles=fetch_candles) -> FastAPI:
    app = FastAPI(title="paper v3", docs_url=None, redoc_url=None, openapi_url=None)
    data = Data(db)
    fails: dict[str, list[float]] = {}

    def authed(req: Request) -> bool:
        return password_hash is None or token_ok(secret, req.cookies.get(COOKIE))

    @app.middleware("http")
    async def guard(req: Request, call_next):
        path = req.url.path
        if path in ("/login", "/api/login") or path.startswith("/static/login"):
            return await call_next(req)
        if not authed(req):
            if path.startswith("/api/"):
                return JSONResponse({"error": "login required"}, status_code=401)
            return RedirectResponse("/login")
        resp = await call_next(req)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/login")
    def login_page():
        return FileResponse(os.path.join(STATIC, "login.html"))

    @app.post("/api/login")
    async def login(req: Request):
        ip = req.client.host if req.client else "?"
        recent = [t for t in fails.get(ip, []) if time.time() - t < 900]
        if len(recent) >= 10:
            raise HTTPException(429, "too many attempts, wait 15 minutes")
        body = await req.json()
        if password_hash is None or check_password(str(body.get("password", "")), password_hash):
            fails.pop(ip, None)
            resp = JSONResponse({"ok": True})
            resp.set_cookie(COOKIE, make_token(secret), max_age=SESSION_S, httponly=True, samesite="strict",
                            secure=bool(os.environ.get("DASH_SECURE_COOKIE")))
            return resp
        fails[ip] = recent + [time.time()]
        raise HTTPException(401, "wrong password")

    @app.post("/api/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"))

    @app.get("/api/board")
    def board():
        return data.board()

    @app.get("/api/account/{aid}")
    def account(aid: str):
        try:
            return data.account(aid)
        except KeyError:
            raise HTTPException(404, "no such account")

    @app.get("/api/status")
    def status():
        return data.status()

    @app.get("/api/signals")
    def signals(tf: Optional[str] = None, limit: int = 200):
        return data.signals(tf, limit)

    @app.get("/api/candles")
    def get_candles(symbol: str, interval: str = "15m", limit: int = 300):
        if symbol not in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT"):
            raise HTTPException(400, "unknown symbol")
        if interval not in ("1m", "5m", "15m", "30m", "1h", "4h", "1d"):
            raise HTTPException(400, "unknown interval")
        return candles(symbol, interval, min(max(limit, 10), 1500))

    @app.get("/api/stream")
    async def stream(req: Request, trade_id: int = 0, alert_row: int = 0):
        async def gen():
            nonlocal trade_id, alert_row
            last_board = None
            while not await req.is_disconnected():
                d = data.since(trade_id, alert_row)
                if d["trades"]:
                    trade_id = d["trades"][-1]["id"]
                if d["alerts"]:
                    alert_row = d["alerts"][-1]["rid"]
                b = data.board()
                slim = {r["account_id"]: [r["wallet"], r["trades"], r["bust"], r["position"]] for r in b["accounts"]}
                changed = {k: v for k, v in slim.items() if last_board is None or last_board.get(k) != v}
                last_board = slim
                payload = {"ts": b["ts"], "changed": changed, "trades": d["trades"], "alerts": d["alerts"],
                           "heartbeat": d["heartbeat"]}
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(3)
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
