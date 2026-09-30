"""Paper v3 dashboard: read-only web view of paper3.db (docs/dashboard.md).

    DASH_PASSWORD_HASH=... DASH_SECRET=... python -m paperbot.dash --db paper3.db --port 8080 \
        --agents-db agents3.db --inbox-db inbox.db

- Opens the store read-only; the live runner stays the only writer.
- Agent rooms ('에이전트 방'): the staff discuss, decide and resolve by themselves (the agents tick
  writes agents3.db; opened read-only here). The owners may join in and approve/reject copy
  proposals: those two things are written to inbox.db, whose only writer is this dashboard. The
  agents tick reads inbox.db read-only on its next turn. Nothing here touches paper3.db or
  agents3.db for writing, calls a model, or places an order.
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
import contextlib
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from typing import Iterator, Optional

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
def _ro_uri(path: str) -> str:
    """Read-only SQLite URI; the path quoted, so a '?', '#' or '%' in it never changes the open mode."""
    return f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro"


class Data:
    def __init__(self, db: str, daily_db: Optional[str] = None):
        self.db = db
        self.daily_db = daily_db

    def _daily(self) -> Optional[sqlite3.Connection]:
        if not self.daily_db or not os.path.exists(self.daily_db):
            return None
        return sqlite3.connect(_ro_uri(self.daily_db), uri=True, timeout=5)

    def _round_trip(self, c) -> float:
        from ..config import v3_settings
        run = self.state(c, "run")
        fee = run[1].get("taker_fee") if run else None
        return v3_settings(**({"taker_fee": fee} if fee else {})).round_trip_cost

    def cards(self, strategy: Optional[str], tf: Optional[str], days: Optional[float], limit: int,
              losses_only: bool = True) -> list[dict]:
        """Trade cards of the last ``days`` days (all history when None)."""
        from ..agents.roster3 import STRATEGY_KO
        from ..cards import cards_from_db
        since = 0 if days is None else int(time.time() * 1000 - days * 86_400_000)
        d = self._daily()
        try:
            with self.conn() as c:
                return cards_from_db(c, self._round_trip(c), strategy, tf, losses_only, since, limit, d,
                                     STRATEGY_KO)
        finally:
            if d is not None:
                d.close()

    def card_stats(self, strategy: Optional[str], tf: Optional[str], days: Optional[float]) -> dict:
        from ..cards import tag_stats
        cs = self.cards(strategy, tf, days, 2000, losses_only=False)
        return {"trades": len(cs), "losses": sum(c["pnl"] < 0 for c in cs), "wins": sum(c["pnl"] > 0 for c in cs),
                "tags": tag_stats(cs)}

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(_ro_uri(self.db), uri=True, timeout=5)
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
            r["beats_random"] = None if b is None or r["wallet"] is None else (r["wallet"] > b and not r["bust"])
        return {"ts": st[0] if st else None, "accounts": rows, "best_random": best_random,
                "initial": self.initial()}

    def initial(self) -> float:
        """Starting wallet of every account: what the running bot recorded, else the rule."""
        from ..config import V3_INITIAL
        with self.conn() as c:
            run = self.state(c, "run")
        return float(run[1].get("initial_equity", 1000.0)) if run else V3_INITIAL

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

    def signals(self, tf: Optional[str], limit: int, symbol: Optional[str] = None) -> list[dict]:
        q, args, where = "SELECT * FROM signal_log", [], []
        if tf:
            where.append("timeframe = ?")
            args.append(tf)
        if symbol:
            where.append("symbol = ?")
            args.append(symbol)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(min(max(limit, 1), 1000))
        with self.conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def latest_ids(self) -> tuple[int, int]:
        with self.conn() as c:
            t = c.execute("SELECT COALESCE(MAX(id), 0) FROM trades").fetchone()[0]
            a = c.execute("SELECT COALESCE(MAX(rowid), 0) FROM alerts").fetchone()[0]
        return int(t), int(a)

    def trades(self, symbol: Optional[str], timeframe: Optional[str], limit: int) -> list[dict]:
        q = ("SELECT t.id, t.account_id, t.symbol, t.entry_time, t.exit_time, t.exit_reason, t.leverage, t.pnl, "
             "t.roe, t.equity_after, t.data, a.strategy, a.timeframe, a.kind FROM trades t "
             "JOIN accounts a ON a.account_id = t.account_id")
        where, args = [], []
        if symbol:
            where.append("t.symbol = ?")
            args.append(symbol)
        if timeframe:
            where.append("a.timeframe = ?")
            args.append(timeframe)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY t.id DESC LIMIT ?"
        args.append(min(max(limit, 1), 2000))
        with self.conn() as c:
            rows = [dict(r) for r in c.execute(q, args)]
        for r in rows:
            d = json.loads(r.pop("data"))
            r.update(side=d["side"], entry_price=d["entry_price"], exit_price=d["exit_price"],
                     lock_roe=d.get("lock_roe"))
        return rows

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


_FRAME_CACHE: dict = {}


def fetch_frame(symbol: str, interval: str, limit: int = 1500):
    """Closed bars with volume (for the strategy views), oldest first; the forming bar is dropped.
    More than 1,500 bars are fetched in pages (Binance returns at most 1,500 per request)."""
    import pandas as pd
    key = (symbol, interval, limit)
    hit = _FRAME_CACHE.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    rows: list = []
    end = None
    while len(rows) < limit:
        n = min(1500, limit - len(rows))
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={n}"
        if end is not None:
            url += f"&endTime={end}"
        with urllib.request.urlopen(url, timeout=10) as r:
            page = json.loads(r.read())
        if not page:
            break
        rows = page + rows
        end = int(page[0][0]) - 1
        if len(page) < n:
            break
    now = time.time() * 1000
    rows = [k for k in rows if int(k[6]) < now]
    df = pd.DataFrame({"ts": pd.to_datetime([int(k[0]) for k in rows], unit="ms", utc=True),
                       "open": [float(k[1]) for k in rows], "high": [float(k[2]) for k in rows],
                       "low": [float(k[3]) for k in rows], "close": [float(k[4]) for k in rows],
                       "volume": [float(k[5]) for k in rows]})
    _FRAME_CACHE[key] = (time.time(), df)
    return df


def view_bars(tf: str) -> int:
    """History for a strategy view: the live signal service's window (two warm-ups), at most 6,000
    bars (four requests), so indicators that depend on their start match the bot's."""
    from .. import sweepsig
    lib = sweepsig.lib()
    return int(min(6000, max(1500, 2 * lib.warmup_bars(tf) + 3)))


# ---------------------------------------------------------------- app
def agent_feed(agents_db: Optional[str], limit: int = 200) -> list[dict]:
    """Meeting messages written by the v3 agent pipelines (their own database)."""
    if not agents_db or not os.path.exists(agents_db):
        return []
    c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(agents_db))}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(
            "SELECT id, ts, meeting, role, kind, text, data FROM messages ORDER BY id DESC LIMIT ?", (limit,))]
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


# ---------------------------------------------------------------- agent rooms
PUBLIC_PATHS = ("/login", "/api/login", "/static/login.html", "/static/login.css", "/static/login.js")
TICK_EVERY_MS = 15 * 60_000  # the agents timer (deploy/paperbot-agents.timer)
SAY_MAX_CHARS = 1_000        # one owner post (rooms_db.MAX_OWNER_TEXT)
SAY_PER_HOUR = 20            # owner posts per hour, both owners together (counted in inbox.db)
AUTHOR_MAX = 20
BODY_MAX = 16_384            # bytes of one owner write (a 1,000-character post is at most ~4 KB of JSON)
BUDGET_CLASSES = ("incident", "owner", "loss", "scheduled", "weekly")
CLASS_KO = {"incident": "사고 점검", "owner": "두 분 글", "loss": "손실·파산 복기", "scheduled": "정기 회의",
            "weekly": "주간 검토",
            # calls that timed out with no model activity (a hung API): counted in the day's and 7-day totals only
            "timeout": "시간 초과(장애, 회의 종류 한도에는 안 셈)"}
WEEKDAY_KO = "월화수목금토일"
# proposal statuses as the page names them (rooms.js PSTATUS_KO), for the refusal messages
PSTATUS_KO = {"awaiting_owner": "두 분 확인 대기", "approved": "승인됨", "rejected": "거절됨",
              "blocked_gate": "코드 관문에서 막힘", "blocked_cap": "복제 한도로 막힘"}


def budget_caps(env_text: Optional[str] = None) -> dict:
    """Daily AI caps per trigger class {class: {calls, tokens}} plus 'total' (per KST day) and 'week'
    (rolling 7 KST days) until the agents tick has run once (after that the dashboard shows the caps
    the tick stored in agents3.db): the rooms engine's defaults, overridden by env
    AGENTS_BUDGET="incident=15:400000,owner=20,total=80:2000000,week=420" (same CLASS=CALLS[:TOKENS]
    syntax as the tick's --budget). Empty when neither is available."""
    caps: dict = {}
    try:
        from ..agents.rooms import DEFAULT_BUDGETS, DEFAULT_TOTAL, DEFAULT_WEEK
        caps = {k: {"calls": int(v[0]), "tokens": int(v[1])} for k, v in DEFAULT_BUDGETS.items()}
        caps["total"] = {"calls": int(DEFAULT_TOTAL[0]), "tokens": int(DEFAULT_TOTAL[1])}
        caps["week"] = {"calls": int(DEFAULT_WEEK[0]), "tokens": int(DEFAULT_WEEK[1])}
    except Exception:  # the engine is optional for the dashboard
        caps = {}
    for part in (env_text or "").replace(";", ",").split(","):
        k, _, v = part.strip().partition("=")
        calls, _, toks = v.strip().partition(":")
        if not k or not calls.isdigit():
            continue
        caps[k] = {"calls": int(calls), "tokens": int(toks) if toks.isdigit() else caps.get(k, {}).get("tokens")}
    return caps


def _trigger_defaults() -> dict:
    """Numbers for the 'when does this room meet' line (from triggers.TriggerPolicy when importable)."""
    d = {"loss_min_count": 3, "loss_min_gap_ms": 4 * 3_600_000, "weekly_min_trades": 30,
         "checkpoint_every_days": 30, "morning_hour_kst": 8, "evening_hour_kst": 22}
    try:
        from ..agents.triggers import TriggerPolicy
        p = TriggerPolicy()
        d = {k: getattr(p, k, v) for k, v in d.items()}
    except Exception:
        pass
    return d


def room_schedule_ko(room_id: str) -> str:
    """Plain Korean: when the staff of this room meet by themselves (no one has to type)."""
    from ..agents.roster3 import STRATEGY_KO
    d = _trigger_defaults()
    if room_id.startswith("strat:"):
        names = list(STRATEGY_KO)
        s = room_id[len("strat:"):]
        wd = WEEKDAY_KO[names.index(s) % 7] if s in names else "정해진"
        gap_h = int(d["loss_min_gap_ms"] // 3_600_000)
        return (f"새 손실이 {d['loss_min_count']}건 쌓이면 (같은 방은 {gap_h}시간 간격), 계좌가 파산하면, "
                f"거래가 {d['weekly_min_trades']}건 더 쌓인 뒤 {wd}요일 주간 검토 때 스스로 회의를 엽니다.")
    m, e, c = d["morning_hour_kst"], d["evening_hour_kst"], d["checkpoint_every_days"]
    return {
        "team:market": f"매일 {m:02d}:00 아침 회의: 장세 → 파생·쏠림 → 전략가 → 반론 → 팀장 요약.",
        "team:review": f"매일 {e:02d}:00 저녁 점검: 손익 복기 → 가정 분석 → 리스크 책임자.",
        "team:lead": f"매일 {e:02d}:00 팀장 3줄 요약(텔레그램 발송), {c}·{2 * c}·{3 * c}일째 중간 점검.",
        "team:ops": "사고가 나면 바로: 강제청산, 밤 점검 불일치, 데이터 끊김, 신호 지연.",
        "team:risk": "정해진 회의는 없고, 두 분이 남긴 메시지에 답합니다.",
    }.get(room_id, "")


def same_origin(req: Request) -> bool:
    """Write endpoints: refuse a request whose Origin header is present and is not this site, scheme
    included (http://host is not https://host), and any browser request marked cross-site. The
    dashboard is served directly (Tailscale / SSH tunnel); behind a proxy that changes the scheme
    or the Host header every owner write would be refused (run uvicorn with --proxy-headers then)."""
    origin = req.headers.get("origin")
    if origin is not None:
        try:
            o = urllib.parse.urlsplit(origin)
        except ValueError:
            return False
        if not o.netloc or o.netloc.lower() != req.headers.get("host", "").lower():
            return False
        if (o.scheme or "").lower() != req.url.scheme.lower():
            return False
    return req.headers.get("sec-fetch-site", "") != "cross-site"


def owner_names(env_text: Optional[str] = None) -> tuple[str, ...]:
    """Names an owner post or decision may be signed with (env DASH_OWNERS="이름1,이름2"). Anything
    else is dropped: the author is not a free field (it could imitate '코드(자동 계산)')."""
    return tuple(n.strip()[:AUTHOR_MAX] for n in (env_text or "").split(",") if n.strip())


class Rooms:
    """Agent rooms for the dashboard. agents3.db (the agents tick writes it) is only ever opened
    read-only here; inbox.db (owner posts and approve/reject clicks) is written only here."""

    def __init__(self, agents_db: Optional[str], inbox_db: Optional[str], budget_env: Optional[str] = None,
                 say_per_hour: int = SAY_PER_HOUR, owners: tuple = ()):
        from ..agents import rooms_db
        self.R = rooms_db
        self.agents_db = agents_db
        self.inbox_db = inbox_db
        self.budget_env = budget_env
        self.say_per_hour = say_per_hour
        self.owners = tuple(owners)
        self._caps: Optional[dict] = None
        self.specs = {s["room_id"]: s for s in rooms_db.room_specs()}
        from ..agents.roster3 import ROLES, SPECIALISTS, room_duty
        # the duty a member has in the rooms (what the room staff can really do), not the v3 roster's
        self.roles = {r[0]: {"id": r[0], "name": r[1], "team": r[2], "duty": room_duty(r[0])}
                      for r in ROLES + SPECIALISTS}

    # -- connections
    @contextlib.contextmanager
    def ro(self, path: Optional[str]) -> Iterator[Optional[sqlite3.Connection]]:
        try:
            c = self.R.open_ro(path)
        except sqlite3.Error:
            c = None
        try:
            yield c
        finally:
            if c is not None:
                c.close()

    def known(self, room_id: str) -> bool:
        return room_id in self.specs

    def _cursor(self, a: Optional[sqlite3.Connection], k: str) -> int:
        if a is None:
            return 0
        try:
            r = a.execute("SELECT v FROM cursors WHERE k = ?", (k,)).fetchone()
            return int(json.loads(r[0])) if r and r[0] is not None else 0
        except (sqlite3.Error, TypeError, ValueError):
            return 0

    def _cursor_obj(self, a: Optional[sqlite3.Connection], k: str) -> Optional[dict]:
        if a is None:
            return None
        try:
            r = a.execute("SELECT v FROM cursors WHERE k = ?", (k,)).fetchone()
            v = json.loads(r[0]) if r and r[0] else None
        except (sqlite3.Error, TypeError, ValueError):
            return None
        return v if isinstance(v, dict) else None

    # -- read side
    def overview(self, now_ms: Optional[int] = None) -> dict:
        with self.ro(self.agents_db) as a:
            rows = {r["room_id"]: r for r in self.R.rooms_overview(a, now_ms)}
            ready = a is not None
            # the agents tick's last sign of life ({ts, ok, why}): the page tells the owners when the
            # staff have stopped (timer off, login refused, crashed) instead of promising an answer
            last_tick = self._cursor_obj(a, self.R.TICK_CURSOR)
            waits, per_day = self._owner_waits(a, int(time.time() * 1000) if now_ms is None else now_ms)
        out = []
        for rid, spec in self.specs.items():
            r = {"room_id": rid, "kind": spec["kind"], "strategy": spec["strategy"], "title": spec["title"],
                 "members": spec["members"], "last_id": 0, "last_ts": None, "last_kind": None, "last_role": None,
                 "last_speaker": None, "last_text": "", "rounds_today": 0, "open_proposals": 0, "running": False}
            r.update({k: v for k, v in rows.pop(rid, {}).items() if v is not None or k not in r})
            r["schedule_ko"] = room_schedule_ko(rid)
            out.append(r)
        out += list(rows.values())          # rooms the tick knows and this code does not (newer roster)
        for r in out:
            # why an owner post in this room is answered only after 00:00 KST (None: on the next turn)
            r["owner_wait"] = waits.get(r["room_id"], waits.get("*"))
        if any(r.get("open_proposals") for r in out):
            # a proposal the owners already decided (not yet applied by the tick) no longer waits for them
            waiting: dict = {}
            for p in self.proposals(status="awaiting_owner", limit=1000):
                if p["effective_status"] == "awaiting_owner":
                    waiting[p["room_id"]] = waiting.get(p["room_id"], 0) + 1
            for r in out:
                r["open_proposals"] = waiting.get(r["room_id"], 0)
        return {"ready": ready, "now": int(time.time() * 1000) if now_ms is None else now_ms,
                "last_tick": last_tick, "tick_every_ms": TICK_EVERY_MS, "rounds_per_room_day": per_day,
                "max_id": max((int(r.get("last_id") or 0) for r in out), default=0), "rooms": out}

    def _owner_waits(self, a: Optional[sqlite3.Connection], now_ms: int) -> tuple[dict, int]:
        """({room_id: why, '*': why for every room}, the room's daily meeting cap): the owners' posts that
        the agents tick does not answer on its next turn, judged with the tick's own rules (triggers._Rooms
        on agents3.db, the limits it stored in 'policy:caps', and the tick's own budget test
        ``ClassBudget.headroom``): 'room_full' when the room had its meetings today, 'budget' when the
        AI budget cannot carry an owner meeting now (the owner cap, the day's total or the 7-day cap after
        what is kept for incidents and the 08:00 / 22:00 meetings, or a stop today), 'paused' while the
        meetings are paused after a Claude plan limit or a runner outage, 'given_up' when the owner meeting
        the tick would open for the room was given up after its failed attempts (it opens again on a new
        post), 'retrying' while that one meeting keeps failing by itself and waits its own pause."""
        caps = self._stored_caps(a) or {}
        lim = caps.get("rooms") if isinstance(caps.get("rooms"), dict) else {}
        try:
            from ..agents import triggers as TR
            kw = {k: int(lim[k]) for k in ("max_rounds_per_room_day", "owner_reserved_per_room_day")
                  if isinstance(lim.get(k), int)}
            pol = TR.TriggerPolicy(**kw)
        except Exception:  # the engine is optional for the dashboard
            return {}, 3
        if a is None:
            return {}, pol.max_rounds_per_room_day
        out: dict = {}
        try:
            st = TR._Rooms(a, now_ms, pol)
            for rid in list(self.specs) + sorted(st.rooms - set(self.specs)):
                if st.room_full(rid, "owner"):
                    out[rid] = "room_full"
            blocked = st.class_blocked("owner")
            # the tick's own per-meeting checks (find_due) on the owner meeting it would open for each room:
            # one given up after its failed attempts opens again only when the owners write again; one that
            # keeps failing by itself waits its own growing pause (key_waiting)
            with self.ro(self.inbox_db) as ib:
                for d in TR._owner(ib, None, st):
                    k = d.data["key"]
                    if len(st.failed_attempts(d.room_id, "owner", k)) >= pol.max_attempts:
                        out[d.room_id] = "given_up"
                    elif st.key_waiting(d.room_id, "owner", k):
                        out.setdefault(d.room_id, "retrying")
        except (sqlite3.Error, TypeError, ValueError):
            return {}, pol.max_rounds_per_room_day
        if not caps and self._caps is None:
            self._caps = budget_caps(self.budget_env)
        allc = caps or self._caps or {}
        cap = allc.get("owner") or {}
        used = self.R.usage_today(a, now_ms)["by_class"].get("owner") or {}
        if blocked or any(isinstance(cap.get(k), int) and int(used.get(k) or 0) >= cap[k] for k in ("calls", "tokens")):
            out["*"] = "budget"
            out = {k: ("budget" if v not in ("room_full", "given_up") else v) for k, v in out.items()}
            return out, pol.max_rounds_per_room_day
        try:
            # the tick's own test before it opens an owner meeting (rooms.can_start): the owner cap, the
            # day's total and the 7-day cap, both minus what is kept for incidents and the 08:00 / 22:00
            # meetings, and a typical call's tokens. Read-only: headroom() only SELECTs agent_calls.
            from ..agents import rooms as RM
            budgets = {k: (int(v["calls"]), int(v["tokens"])) for k, v in allc.items()
                       if k in BUDGET_CLASSES and isinstance(v, dict)}
            tot, wk = allc.get("total") or {}, allc.get("week") or {}
            est = (allc.get("rooms") or {}).get("est_call_tokens") if isinstance(allc.get("rooms"), dict) else None
            head = RM.ClassBudget(None, a, "owner", *budgets["owner"], int(tot["calls"]), int(tot["tokens"]),
                                  lambda: now_ms, budgets=budgets,
                                  week=(int(wk["calls"]), int(wk["tokens"])) if wk.get("calls") is not None else None,
                                  call_tokens=int(est) if isinstance(est, int) else RM.RoomsPolicy().est_call_tokens
                                  ).headroom()
            pol_r = RM.RoomsPolicy()
            for rid in list(self.specs) + sorted(st.rooms - set(self.specs)):
                need = RM.round_min_calls(TR.Due(rid, "owner", 0, {"class": "owner"}, "owner"), pol_r)
                if out.get(rid) not in ("room_full", "given_up") and head < need:
                    out[rid] = "budget"
            if st.usage_paused() or st.transient_paused():
                for rid in list(self.specs) + sorted(st.rooms - set(self.specs)):
                    out.setdefault(rid, "paused")
        except (KeyError, TypeError, ValueError, AttributeError, ImportError, sqlite3.Error):
            pass
        return out, pol.max_rounds_per_room_day

    def room_info(self, room_id: str) -> dict:
        spec = dict(self.specs[room_id])
        with self.ro(self.agents_db) as a:
            got = self.R.get_room(a, room_id)
        if got:
            spec.update({k: got[k] for k in ("title", "members") if got.get(k)})
        spec["members_info"] = [self.roles.get(m, {"id": m, "name": self.R.role_name(m), "team": "", "duty": ""})
                                for m in spec["members"]]
        spec["schedule_ko"] = room_schedule_ko(room_id)
        return spec

    def pending_owner(self, a: Optional[sqlite3.Connection], room_id: str) -> list[dict]:
        """Owner posts in inbox.db the staff have not seen yet (not copied into the room)."""
        with self.ro(self.inbox_db) as ib:
            if ib is None:
                return []
            after = self._cursor(a, f"owner_copied:{room_id}")
            got = self.R.pending_inbox(ib, after, room_id, limit=200)
        if not got:
            return []
        copied: set = set()
        if a is not None:
            try:        # (inbox id, post time): ids restart if inbox.db is ever replaced
                copied = {(int(r[0]), int(r[1])) for r in a.execute(
                    "SELECT json_extract(data, '$.inbox_id'), ts FROM messages WHERE room_id = ? AND kind = 'owner' "
                    "AND json_extract(data, '$.inbox_id') IS NOT NULL", (room_id,))}
            except (sqlite3.Error, TypeError, ValueError):
                copied = set()
        return [{**m, "pending": True} for m in got if (int(m["id"]), int(m["ts"] or 0)) not in copied][-50:]

    def messages(self, room_id: str, after_id: int = 0, limit: int = 200, before_id: int = 0) -> dict:
        limit = min(max(int(limit or 1), 1), 500)
        with self.ro(self.agents_db) as a:
            msgs = self.R.room_messages(a, room_id, after_id, limit, before_id or None)
            pending = self.pending_owner(a, room_id)
            last = self.R.last_message_id(a)
        out = {"room_id": room_id, "messages": msgs, "pending_owner": pending,
               "has_more": (not after_id) and len(msgs) >= limit, "max_id": last}
        if not after_id and not before_id:
            out["room"] = self.room_info(room_id)
        return out

    def notes(self, room_id: str, limit: int = 50) -> list[dict]:
        with self.ro(self.agents_db) as a:
            return self.R.room_notes(a, room_id, limit)

    def trials(self, strategy: Optional[str], room_id: Optional[str], limit: int = 50) -> dict:
        with self.ro(self.agents_db) as a:
            out = {"counts": self.R.trial_counts(a, strategy),
                   "trials": self.R.trial_history(a, strategy, room_id, limit=min(max(int(limit), 1), 500))}
        # a copy-proposal row carries the PROPOSAL it recorded (the number the owners approve or reject)
        # and that proposal's status as the owners should see it; its own id is only a ledger row number
        props: Optional[list] = None
        for t in out["trials"]:
            if t.get("kind") != "copy_proposal":
                continue
            if props is None:
                props = self.proposals(strategy=strategy, room_id=room_id, limit=1000)
            ft = (t.get("spec") or {}).get("from_trial") if isinstance(t.get("spec"), dict) else None
            cands = [p for p in props if ft is not None and p.get("trial_id") == ft]
            if cands:      # written together (same time); several when a capped proposal was made again
                p = min(cands, key=lambda p: (abs(int(p.get("ts") or 0) - int(t.get("ts") or 0)), int(p["id"])))
                t["proposal_id"], t["proposal_status"] = int(p["id"]), p.get("effective_status") or p.get("status")
        return out

    def author(self, body: dict) -> str:
        """The signer of an owner write: one of the configured owner names, else nobody in particular."""
        a = body.get("author")
        a = " ".join(a.split())[:AUTHOR_MAX] if isinstance(a, str) else ""
        return a if a and a in self.owners else ""

    def _decisions(self) -> dict:
        """Latest owner decision per proposal id, from inbox.db. Clicks older than this agents3.db
        (cursor 'inbox:approvals_base': proposal ids restart at 1 in a new one) are not shown."""
        with self.ro(self.agents_db) as a:
            base = self._cursor(a, "inbox:approvals_base")
        rows: list = []
        with self.ro(self.inbox_db) as ib:
            while True:                 # every click after the base (oldest first), 1000 at a time
                got = self.R.pending_approvals(ib, rows[-1]["id"] if rows else base, limit=1000)
                rows += got
                if len(got) < 1000:
                    break
        out: dict = {}
        for r in rows:
            out[int(r["proposal_id"])] = {**r, "rejected_before": out.get(int(r["proposal_id"]), {}).get(
                "rejected_before", False) or r["decision"] == "reject"}
        return out

    @staticmethod
    def _effective(p: dict, dec: Optional[dict], applied_upto: int) -> tuple[str, bool]:
        """(status the owners should see, whether their latest click is already applied)."""
        if dec is None:
            return p["status"], True
        applied = int(dec["id"]) <= applied_upto or (
            (p["status"], dec["decision"]) in (("approved", "approve"), ("rejected", "reject")))
        if applied or p["status"] not in ("awaiting_owner", "approved"):
            return p["status"], applied
        return ("approved" if dec["decision"] == "approve" else "rejected"), False

    def proposals(self, status: Optional[str] = None, strategy: Optional[str] = None,
                  room_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        from ..agents.roster3 import STRATEGY_KO
        decs = self._decisions()
        with self.ro(self.agents_db) as a:
            rows = self.R.list_proposals(a, status, strategy, room_id, limit)
            upto = self._cursor(a, "inbox:approvals")
            now = self._gate_now(a)
        for p in rows:
            dec = decs.get(int(p["id"]))
            eff, applied = self._effective(p, dec, upto)
            p["gate_now"] = now.get(str(p["id"]))
            p["strategy_ko"] = STRATEGY_KO.get(p.get("strategy") or "", p.get("strategy"))
            p["owner_decision"] = None if dec is None else {
                "decision": dec["decision"], "ts": dec["ts"], "note": dec.get("note"), "applied": applied}
            p["effective_status"] = eff
        return rows

    @staticmethod
    def _gate_now(a: Optional[sqlite3.Connection]) -> dict:
        """{proposal id: {pass, n_trials}}: the agents tick re-judges open proposals with the room's
        current number of tests (cursor 'proposals:gate_now'); an approve click on a proposal that no
        longer passes is refused here and, in any case, by the tick."""
        if a is None:
            return {}
        try:
            r = a.execute("SELECT v FROM cursors WHERE k = 'proposals:gate_now'").fetchone()
            v = json.loads(r[0]) if r and r[0] else None
        except (sqlite3.Error, TypeError, ValueError):
            return {}
        return v if isinstance(v, dict) else {}

    def _stored_caps(self, a: Optional[sqlite3.Connection]) -> Optional[dict]:
        """The caps the agents tick really used (it stores them in agents3.db, cursor 'policy:caps')."""
        if a is None:
            return None
        try:
            r = a.execute("SELECT v FROM cursors WHERE k = 'policy:caps'").fetchone()
            v = json.loads(r[0]) if r and r[0] else None
        except (sqlite3.Error, TypeError, ValueError):
            return None
        return v if isinstance(v, dict) and v else None

    def usage(self, now_ms: Optional[int] = None) -> dict:
        with self.ro(self.agents_db) as a:
            u = self.R.usage_today(a, now_ms)
            stored = self._stored_caps(a)
        if stored is None and self._caps is None:
            self._caps = budget_caps(self.budget_env)
        caps = stored if stored is not None else self._caps
        classes = []
        for k in list(BUDGET_CLASSES) + sorted(set(u["by_class"]) - set(BUDGET_CLASSES)):
            got = u["by_class"].get(k, {"calls": 0, "failed": 0, "tokens": 0})
            cap = caps.get(k, {})
            classes.append({"class": k, "name_ko": CLASS_KO.get(k, k), **got,
                            "cap_calls": cap.get("calls"), "cap_tokens": cap.get("tokens")})
        total, wk = caps.get("total", {}), caps.get("week", {})
        with self.ro(self.agents_db) as a:
            w = self.R.usage_days(a, now_ms, 7)
        return {"day": u["day"], "calls": u["calls"], "tokens": u["tokens"], "cap_calls": total.get("calls"),
                "cap_tokens": total.get("tokens"), "classes": classes,
                "week": {"calls": w["calls"], "tokens": w["tokens"], "cap_calls": wk.get("calls"),
                         "cap_tokens": wk.get("tokens"), "since": w["since"]},
                "caps_source": "tick" if stored is not None else "defaults"}

    def since(self, after_id: int) -> tuple[int, dict]:
        """Rooms with messages newer than ``after_id`` -> {room_id: newest id}; for the live stream."""
        with self.ro(self.agents_db) as a:
            if a is None:
                return after_id, {}
            try:
                top = int(a.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0])
                if top < after_id:           # agents3.db was replaced: start over
                    after_id = 0
                rows = a.execute("SELECT room_id, MAX(id) FROM messages WHERE id > ? GROUP BY room_id",
                                 (after_id,)).fetchall()
            except sqlite3.Error:
                return after_id, {}
        changed = {r[0]: int(r[1]) for r in rows}
        return max([after_id, *changed.values()]), changed

    def last_id(self) -> int:
        with self.ro(self.agents_db) as a:
            return self.R.last_message_id(a)

    # -- write side (inbox.db only)
    def _inbox(self) -> sqlite3.Connection:
        if not self.inbox_db:
            raise HTTPException(503, "두 분 메시지 저장소(inbox.db)가 설정되지 않았습니다")
        try:
            return self.R.open_inbox_rw(self.inbox_db)
        except RuntimeError as exc:           # restored with the old -wal next to it (rooms_db.refuse_stale_wal)
            print(f"inbox.db not opened: {exc}", file=sys.stderr)
            raise HTTPException(503, "inbox.db를 백업에서 되살린 뒤 예전 -wal 파일이 남아 있어 저장하지 않았습니다. "
                                     "서비스를 멈추고 inbox.db-wal·inbox.db-shm을 지운 뒤 다시 켜 주세요")

    def say(self, room_id: str, text: str, author: str, now_ms: Optional[int] = None) -> dict:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        c = self._inbox()
        try:
            if self.R.owner_posts_since(c, None, now_ms - 3_600_000) >= self.say_per_hour:
                raise HTTPException(429, f"한 시간에 {self.say_per_hour}번까지 남길 수 있습니다. 잠시 뒤에 다시 보내 주세요")
            mid = self.R.add_owner_message(c, room_id, author, text, ts=now_ms)
        finally:
            c.close()
        return {"ok": True, "id": mid, "ts": now_ms, "room_id": room_id, "author": author, "text": text,
                "pending": True}

    def decide(self, proposal_id: int, decision: str, note: str, author: str) -> dict:
        if not 0 < int(proposal_id) < 2 ** 63:          # beyond SQLite's integers: no such proposal
            raise HTTPException(404, "그런 제안이 없습니다")
        with self.ro(self.agents_db) as a:
            p = self.R.get_proposal(a, proposal_id)
            upto = self._cursor(a, "inbox:approvals")
            now = self._gate_now(a).get(str(proposal_id))
        if p is None:
            raise HTTPException(404, "그런 제안이 없습니다")
        dec = self._decisions().get(int(proposal_id))
        eff, _ = self._effective(p, dec, upto)
        gate_ok = isinstance(p.get("gate"), dict) and p["gate"].get("pass") is True
        if decision == "approve":
            if not gate_ok:
                raise HTTPException(409, "코드 관문을 통과하지 못한 제안은 누구도 승인할 수 없습니다")
            if isinstance(now, dict) and now.get("pass") is False:
                raise HTTPException(409, "이 방에서 시험을 더 해서, 지금 기준으로 다시 판정하면 코드 관문을 "
                                         "통과하지 못합니다. 승인할 수 없습니다")
            if eff != "awaiting_owner" or (dec is not None and dec.get("rejected_before")):
                raise HTTPException(409, f"이 제안은 지금 승인할 수 없는 상태입니다 ({PSTATUS_KO.get(eff, eff)})")
        elif eff not in ("awaiting_owner", "approved"):
            raise HTTPException(409, f"이 제안은 지금 거절할 수 없는 상태입니다 ({PSTATUS_KO.get(eff, eff)})")
        c = self._inbox()
        try:
            aid = self.R.add_approval(c, proposal_id, decision, author, note or None)
        finally:
            c.close()
        return {"ok": True, "approval_id": aid, "proposal_id": proposal_id, "decision": decision,
                "message": "전달했습니다. 다음 차례(15분 안)에 코드가 반영합니다"}


async def _json_object(req: Request, limit: int = BODY_MAX) -> dict:
    """The request's JSON object, read with a size cap (a huge body is refused before it is parsed)."""
    try:
        if int(req.headers.get("content-length") or 0) > limit:
            raise HTTPException(413, "보낸 내용이 너무 큽니다")
    except ValueError:
        raise HTTPException(400, "잘못된 요청입니다")
    raw = bytearray()
    async for chunk in req.stream():
        raw += chunk
        if len(raw) > limit:
            raise HTTPException(413, "보낸 내용이 너무 큽니다")
    try:
        body = json.loads(bytes(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(400, "JSON 본문이 필요합니다")
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON 객체가 필요합니다")
    return body


def same_file(a: str, b: str) -> bool:
    """Do two database flags name the same file (symlinks, relative spellings and hard links)?"""
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:                 # one of them does not exist (yet)
        return False


def _storable(text: str) -> bool:
    """Text SQLite can store as UTF-8 (a lone surrogate like the JSON escape \\ud800 cannot)."""
    try:
        text.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def create_app(db: str, password_hash: Optional[str], secret: bytes, candles=fetch_candles,
               agents_db: Optional[str] = None, daily_db: Optional[str] = None, frames=fetch_frame,
               inbox_db: Optional[str] = None, say_per_hour: int = SAY_PER_HOUR) -> FastAPI:
    if inbox_db and any(other and same_file(inbox_db, other) for other in (db, daily_db, agents_db)):
        # the dashboard creates its tables in inbox.db: never in another process's database
        raise ValueError("--inbox-db must be its own file (not paper3.db, daily3.db or agents3.db)")
    app = FastAPI(title="paper v3", docs_url=None, redoc_url=None, openapi_url=None)
    data = Data(db, daily_db)
    rooms = Rooms(agents_db, inbox_db, os.environ.get("AGENTS_BUDGET"), say_per_hour,
                  owner_names(os.environ.get("DASH_OWNERS")))
    fails: dict[str, list[float]] = {}

    def authed(req: Request) -> bool:
        return password_hash is None or token_ok(secret, req.cookies.get(COOKIE))

    async def _guarded(req: Request, call_next):
        path = req.url.path
        if path in PUBLIC_PATHS:            # exact paths only: '/static/login/../app.js' is not public
            return await call_next(req)
        if not authed(req):
            if path.startswith("/api/"):
                return JSONResponse({"error": "login required"}, status_code=401)
            return RedirectResponse("/login")
        resp = await call_next(req)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.middleware("http")
    async def guard(req: Request, call_next):
        resp = await _guarded(req, call_next)
        # never inside another site's frame (the approve / reject buttons, the login form)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
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
        body = await _json_object(req)       # size-capped before it is parsed (no login needed to send it)
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
    def signals(tf: Optional[str] = None, symbol: Optional[str] = None, limit: int = 200):
        return data.signals(tf, limit, symbol)

    @app.get("/api/trades")
    def trades(symbol: Optional[str] = None, tf: Optional[str] = None, limit: int = 200):
        return data.trades(symbol, tf, limit)

    @app.get("/api/agents/roster")
    def agents_roster():
        from ..agents.roster3 import roster
        return roster()

    @app.get("/api/cards")
    def get_cards(strategy: Optional[str] = None, tf: Optional[str] = None, days: float = 30,
                  limit: int = 100, all: int = 0):
        return data.cards(strategy, tf, days if days > 0 else None, min(max(limit, 1), 500), losses_only=not all)

    @app.get("/api/cards/stats")
    def get_card_stats(strategy: Optional[str] = None, tf: Optional[str] = None, days: float = 30):
        return data.card_stats(strategy, tf, days if days > 0 else None)

    view_cache: dict = {}

    @app.get("/api/strategy/{strategy}")
    def get_strategy_view(strategy: str, tf: str = "1h", symbol: str = "BTCUSDT"):
        """The strategy's own indicator lines and its entry conditions on the last closed bar."""
        from ..strategy_views import render, views
        if symbol not in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT"):
            raise HTTPException(400, "unknown symbol")
        if tf not in TRADE_TFS:
            raise HTTPException(400, "unknown timeframe")
        try:
            known = strategy in views()
        except ImportError:
            known = False
        if not known:
            raise HTTPException(404, "no chart view for this strategy yet")
        df = frames(symbol, tf, view_bars(tf))
        if df is None or len(df) < 50:
            raise HTTPException(503, "no price data")
        key = (strategy, tf, symbol, str(df["ts"].iloc[-1]))
        if key not in view_cache:
            if len(view_cache) > 256:
                view_cache.clear()
            view_cache[key] = render(strategy, df, tf)
        return view_cache[key]

    @app.get("/api/strategies")
    def get_strategies():
        from ..agents.packets3 import CARDS
        from ..agents.roster3 import STRATEGY_KO
        prof = {}
        if os.path.exists(CARDS):
            with open(CARDS) as fh:
                prof = {c["strategy"]: c for c in json.load(fh)["cards"]}
        return [{"strategy": k, "name_ko": v, "style": prof.get(k, {}).get("style"),
                 "hold": prof.get(k, {}).get("hold"), "rare": prof.get(k, {}).get("rare")}
                for k, v in STRATEGY_KO.items()]

    @app.get("/api/profile/{strategy}")
    def get_profile(strategy: str):
        from ..agents.packets3 import profile_card
        c = profile_card(strategy)
        if c is None:
            raise HTTPException(404, "unknown strategy")
        return c

    @app.get("/api/agents/feed")
    def agents_feed(limit: int = 200):
        return agent_feed(agents_db, min(max(limit, 1), 1000))

    # ------------------------------------------------ agent rooms: reads (agents3.db, read-only)
    def _room(room_id: str) -> str:
        if not rooms.known(room_id):
            raise HTTPException(404, "그런 방이 없습니다")
        return room_id

    @app.get("/api/rooms")
    def get_rooms():
        return rooms.overview()

    @app.get("/api/rooms/{room_id}/messages")
    def get_room_messages(room_id: str, after_id: int = 0, limit: int = 200, before_id: int = 0):
        top = 2 ** 63 - 1                               # SQLite's largest integer
        return rooms.messages(_room(room_id), min(max(after_id, 0), top), limit, min(max(before_id, 0), top))

    @app.get("/api/rooms/{room_id}/notes")
    def get_room_notes(room_id: str, limit: int = 50):
        return rooms.notes(_room(room_id), limit)

    @app.get("/api/trials")
    def get_trials(strategy: Optional[str] = None, room_id: Optional[str] = None, limit: int = 50):
        return rooms.trials(strategy or None, room_id or None, limit)

    @app.get("/api/proposals")
    def get_proposals(status: Optional[str] = None, strategy: Optional[str] = None, room_id: Optional[str] = None,
                      limit: int = 100):
        if status and status not in rooms.R.PROPOSAL_STATUSES:
            raise HTTPException(400, "unknown status")
        return rooms.proposals(status or None, strategy or None, room_id or None, min(max(limit, 1), 1000))

    @app.get("/api/agents/usage")
    def get_agents_usage():
        return rooms.usage()

    # ------------------------------------------------ agent rooms: owner writes (inbox.db only)
    @app.post("/api/rooms/{room_id}/say")
    async def room_say(room_id: str, req: Request):
        if not same_origin(req):
            raise HTTPException(403, "다른 사이트에서 온 요청은 받지 않습니다")
        _room(room_id)
        body = await _json_object(req)
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(400, "보낼 내용이 없습니다")
        text = text.strip()
        if len(text) > SAY_MAX_CHARS:
            raise HTTPException(400, f"{SAY_MAX_CHARS:,}자까지 보낼 수 있습니다")
        if not _storable(text):
            raise HTTPException(400, "보낼 수 없는 글자가 들어 있습니다")
        return rooms.say(room_id, text, rooms.author(body))

    @app.post("/api/proposals/{proposal_id}/decide")
    async def proposal_decide(proposal_id: int, req: Request):
        if not same_origin(req):
            raise HTTPException(403, "다른 사이트에서 온 요청은 받지 않습니다")
        body = await _json_object(req)
        decision = body.get("decision")
        if decision not in ("approve", "reject"):
            raise HTTPException(400, "decision은 approve 또는 reject")
        note = body.get("note") or ""
        if not isinstance(note, str) or len(note.strip()) > SAY_MAX_CHARS:
            raise HTTPException(400, f"메모는 {SAY_MAX_CHARS:,}자까지 쓸 수 있습니다")
        if not _storable(note):
            raise HTTPException(400, "보낼 수 없는 글자가 들어 있습니다")
        return rooms.decide(proposal_id, decision, note.strip(), rooms.author(body))

    @app.get("/api/candles")
    def get_candles(symbol: str, interval: str = "15m", limit: int = 300):
        if symbol not in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT"):
            raise HTTPException(400, "unknown symbol")
        if interval not in ("1m", "5m", "15m", "30m", "1h", "4h", "1d"):
            raise HTTPException(400, "unknown interval")
        return candles(symbol, interval, min(max(limit, 10), 1500))

    @app.get("/api/stream")
    async def stream(req: Request, trade_id: int = 0, alert_row: int = 0, room_msg: int = 0):
        async def gen():
            nonlocal trade_id, alert_row, room_msg
            last_board = None
            if not trade_id and not alert_row:   # a new page starts from now, not from the first trade
                trade_id, alert_row = data.latest_ids()
            if not room_msg:
                room_msg = rooms.last_id()
            while not await req.is_disconnected():
                # new agent-room messages (agents3.db max(id)): the page refreshes the rooms that changed
                room_msg, rooms_changed = rooms.since(room_msg)
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
                           "heartbeat": d["heartbeat"], "room_msg": room_msg, "rooms": rooms_changed}
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(3)
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
