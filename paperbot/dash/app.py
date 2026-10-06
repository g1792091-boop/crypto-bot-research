"""Paper v4 dashboard: read-only web view of paper3.db (docs/dashboard.md). '/' serves the v4 page
(static/v4/index.html), '/v3' the old one ('예전 화면'); both sit behind the same login, which comes back to the page
that sent it (/login?next=<same-origin path>).

    DASH_PASSWORD_HASH=... DASH_SECRET=... python -m paperbot.dash --db paper3.db --port 8080 \
        --agents-db agents3.db --inbox-db inbox.db

- Opens the store read-only; the live runner stays the only writer.
- Agent rooms ('에이전트 방'): the staff discuss, decide and resolve by themselves (the agents tick
  writes agents3.db; opened read-only here). The owners may join in and approve/reject proposals
  (copy accounts and new-strategy accounts from the lab): those two things are written to inbox.db,
  whose only writer is this dashboard. The agents tick reads inbox.db read-only on its next turn, and
  the live runner starts an approved account after checking it again itself. Nothing here touches
  paper3.db or agents3.db for writing, calls a model, or places an order.
- Extra paper accounts (copies, new strategies) are on the leaderboard with their own marks, their
  rule or strategy, their proposal number and the runner's status for them (state 'extras').
- Login: one password (PBKDF2 hash in DASH_PASSWORD_HASH, make one with
  ``python -m paperbot.dash hash``) and a signed session cookie (DASH_SECRET).
- Live updates: /api/stream (server-sent events) sends changed accounts, new
  trades and alerts every few seconds. Prices tick in the browser straight
  from Binance's public mark-price stream.
- '분석' tab, health card, alert history, server clock and the 24-hour debate room: dash/analysis.py (read-only,
  heavy analyses one at a time in the background, cached 5-15 min). The '거래소 차트' (TradingView) and the
  Coinglass links are loaded by the browser only; this server never fetches them.
- Binds to 127.0.0.1 by default. Reach it through Tailscale or an SSH tunnel;
  never expose it directly (see docs/dashboard.md).
- Paper v4 groups (paperbot/groups.py, display only): every /api/board row carries its group (core = the 36,
  ds200 = DeepSeek, reel = the 5m reel, flip = coin flips, extra = copies / new-lab), the DeepSeek family and the
  account's exit rule; the run shape is counted from the accounts table (``run_shape``), never typed in. The DeepSeek
  coin-flip comparison is reference only ("참고": the flips draw "best" leverage, DeepSeek never does), and the
  DeepSeek P&L is shown in its own group view only (owners' D11; the page's group switch).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Iterator, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..config import (DS200_FAMILY, FIVE_M_MAX_DELAY_MS, REEL_NAME, REEL_TF, V3_TRADE_TFS, V4_ACCOUNTS, V4_GROUPS,
                      v4_tfs_of)

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
# the paper v4 dashboard (static/v4/index.html) is the page at '/'; the old one stays reachable at '/v3' ('예전 화면')
V4_INDEX = os.path.join(STATIC, "v4", "index.html")
OLD_INDEX = os.path.join(STATIC, "index.html")
COOKIE = "pb_session"
SESSION_S = 7 * 86400
# timeframes in display order (5m: the v4 reel and its three coin flips only)
TF_ORDER = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M")
# the 36's traded timeframes (config.V3_TRADE_TFS: 15m / 30m / 1h / 4h; the core group never trades 5m)
CORE_TFS = tuple(V3_TRADE_TFS)
# every timeframe some v4 group trades (config.V4_GROUPS: 5m for the reel and its coin flips, 15m-4h for the rest)
TRADE_TFS = tuple(tf for tf in TF_ORDER if any(tf in spec["tfs"] for spec in V4_GROUPS.values()))
# support / resistance lines (/api/levels) on the 36's timeframes only (5m stays a chart interval for them)
LEVEL_TFS = CORE_TFS
# the paper v4 groups in display order and the original ones (paperbot/groups.py; config.V4_GROUPS has the rules)
GROUP_ORDER = ("core", "ds200", "reel", "flip", "extra")
# the groups the home summary's best / worst lists span (the DeepSeek P&L stays inside its own group view, D11)
MAIN_GROUPS = ("core", "reel", "extra")
# /api/cards/stats without a strategy (분석 · 상황 태그): the 36 and the reel; the cap is cards.py's own limit
CARD_STATS_KINDS = ("strategy", "reel")
CARD_STATS_CAP = 2000
# the page's group views (app.js GROUP_VIEWS / inView) as SQL on the accounts table ``a`` (/api/trades?group=): "main" =
# the 36, the reel and the extras (the default); "reel" = the 5m card: the reel with its three 5m coin flips as its
# labelled comparison. A view, not a count: the 5m flips count in the coin-flip group everywhere (owners' decision;
# groups.group_of is the one source: summary.today.by_group, run_shape, the health card)
VIEW_SQL = {"main": "a.kind IN ('strategy', 'reel', 'copy', 'newlab')", "core": "a.kind = 'strategy'",
            "ds200": "a.kind = 'ds200'", "reel": "(a.kind = 'reel' OR (a.kind = 'random' AND a.timeframe = '5m'))",
            "flip": "a.kind = 'random'", "extra": "a.kind IN ('copy', 'newlab')"}
# the signal service's limits (sigservice.SignalService defaults; tests/test_dash_v4groups.py checks them)
SIGNAL_LIMITS = {"max_delay_ms": 180_000, "max_delay_ms_5m": FIVE_M_MAX_DELAY_MS, "timeout_s": 120}


def strategy_tfs(strategy: str) -> tuple:
    """The timeframes one strategy name trades: a DeepSeek definition its own (3 or 4), the reel 5m, any other name
    (the 36) the core timeframes."""
    if strategy in DS200_FAMILY:
        return tuple(v4_tfs_of("ds200", strategy))
    if strategy == REEL_NAME:
        return (REEL_TF,)
    return CORE_TFS


ACCOUNT_LINE = re.compile(r"^\[([^\]\s]+@[^\]\s]+)\] ")


def account_line(text) -> Optional[str]:
    """The account id of a per-account alert line ('[F9_FVG@15m] LIQUIDATED ...', '[A@1h] BUST: ...'); None else."""
    m = ACCOUNT_LINE.match(text) if isinstance(text, str) else None
    return m.group(1) if m else None


def signal_group(strategy: str) -> str:
    """The group of a signal_log row by its strategy name: a DeepSeek definition, the reel, a coin flip (RANDOM_k)
    or the 36 (core)."""
    if strategy in DS200_FAMILY:
        return "ds200"
    if strategy == REEL_NAME:
        return "reel"
    return "flip" if isinstance(strategy, str) and strategy.startswith("RANDOM_") else "core"


def signals_by_group(rows: list) -> list:
    """[{group, timeframe, status, n, avg_delay, max_delay}] from per-strategy signal_log counts (status: G15, a stopped
    DeepSeek timeframe is visible next to the 36's)."""
    acc: dict = {}
    for r in rows:
        k = (signal_group(r["strategy"]), r["timeframe"], r["status"])
        e = acc.setdefault(k, {"n": 0, "dsum": 0.0, "dn": 0, "max_delay": None})
        e["n"] += int(r["n"] or 0)
        e["dsum"] += float(r["dsum"] or 0)
        e["dn"] += int(r["dn"] or 0)
        if r["max_delay"] is not None:
            e["max_delay"] = r["max_delay"] if e["max_delay"] is None else max(e["max_delay"], r["max_delay"])
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    return [{"group": g, "timeframe": tf, "status": st, "n": e["n"],
             "avg_delay": e["dsum"] / e["dn"] if e["dn"] else None, "max_delay": e["max_delay"]}
            for (g, tf, st), e in sorted(acc.items(), key=lambda kv: (order.get(kv[0][0], 9), _tf_key(kv[0][1]), kv[0][2]))]


def signals_by_tf(rows: list) -> list:
    """[{timeframe, status, n, avg_delay}] (ordered by timeframe, status: SQL's GROUP BY order) from the per-strategy
    signal_log counts (the /api/status rows the pages have always read)."""
    acc: dict = {}
    for r in rows:
        e = acc.setdefault((r["timeframe"], r["status"]), [0, 0.0, 0])
        e[0] += int(r["n"] or 0)
        e[1] += float(r["dsum"] or 0)
        e[2] += int(r["dn"] or 0)
    return [{"timeframe": tf, "status": st, "n": n, "avg_delay": ds / dn if dn else None}
            for (tf, st), (n, ds, dn) in sorted(acc.items())]


def strategy_kind(strategy: str) -> str:
    """The original accounts' kind of one strategy name: 'ds200' for a DeepSeek definition, 'reel' for the reel,
    'strategy' for any other name (the 36; a copy carries its parent's name but is not the strategy's account)."""
    if strategy in DS200_FAMILY:
        return "ds200"
    return "reel" if strategy == REEL_NAME else "strategy"


def names_ko() -> dict:
    """Korean names of every strategy name: the 36 (roster3.STRATEGY_KO, the names Telegram uses), the DeepSeek
    definitions and the reel (groups.label_ko)."""
    from .. import groups as G
    from ..agents.roster3 import STRATEGY_KO
    out = {d: G.label_ko(d) for d in DS200_FAMILY}
    out[REEL_NAME] = G.label_ko(REEL_NAME)
    out.update(STRATEGY_KO)
    return out


def _tf_key(tf: str) -> int:
    return TF_ORDER.index(tf) if tf in TF_ORDER else len(TF_ORDER)


def run_shape(conn) -> dict:
    """What the browser shows as the run's shape (/api/board 'run_shape'), counted from the accounts table
    (groups.shape_from_db), never hard-coded in the static files and never typed in here:
    accounts (the original accounts), all_accounts (with the extras), strategy_accounts (the 36's accounts),
    q1_family (the 36's judged accounts), judged (every judged original), trade_tfs (every original account's
    timeframe), core_tfs (the 36's), judged_tfs (the 36's judged timeframes), judged_by_group, groups ({group:
    {accounts, tfs: {tf: n}, judged}}). An empty table (before the first start) gives the v4 rule's numbers
    (config.V4_GROUPS), marked source "config"."""
    from .. import groups as G
    s = G.shape_from_db(conn)
    grp = s["groups"]
    judged_by = {g: list(V4_GROUPS[g]["judged"]) for g in ("core", "ds200", "reel")}
    if not s["accounts"]:
        from ..config import V4_GROUP_ACCOUNTS, V4_GROUP_JUDGED, V4_GROUP_TF_COUNTS
        grp = {g: {"accounts": V4_GROUP_ACCOUNTS[g], "tfs": dict(V4_GROUP_TF_COUNTS[g]),
                   "judged": V4_GROUP_JUDGED.get(g, 0)} for g in V4_GROUPS}
        originals, total, source = V4_ACCOUNTS, V4_ACCOUNTS, "config"
    else:
        originals, total, source = s["originals"], s["accounts"], "accounts_table"
    tfs_of = lambda gs: sorted({tf for g in gs for tf in (grp.get(g) or {}).get("tfs", {})}, key=_tf_key)  # noqa: E731
    core_tfs = tfs_of(("core",)) or list(CORE_TFS)
    return {"source": source, "accounts": originals, "all_accounts": total,
            "strategy_accounts": (grp.get("core") or {}).get("accounts", 0),
            "q1_family": (grp.get("core") or {}).get("judged", 0),
            "judged": sum(int((grp.get(g) or {}).get("judged", 0)) for g in ("core", "ds200", "reel")),
            "trade_tfs": tfs_of(("core", "ds200", "reel", "flip")) or core_tfs, "core_tfs": core_tfs,
            "judged_tfs": [tf for tf in judged_by["core"]], "judged_by_group": judged_by,
            "groups": {g: grp[g] for g in sorted(grp, key=lambda k: GROUP_ORDER.index(k) if k in GROUP_ORDER else 9)},
            "versions": s.get("versions", [])}


def _finite_or_none(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def board_position(pos: dict, exits: Optional[str]) -> dict:
    """An open position as /api/board sends it. The reel's own exits (exits "reel": reel_engine.py) add the moving
    target ``tp`` (the previous closed 5m bar's upper Bollinger band, a resting limit) and the time exit
    ``time_exit``; a house-exit position has no fixed target (its tp_price is NaN: ladder) and gets ``tp`` None."""
    sig = pos.get("signal") if isinstance(pos.get("signal"), dict) else {}
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    st = meta.get("reel_exit") if isinstance(meta.get("reel_exit"), dict) else {}
    reel = exits == "reel"
    tp = _finite_or_none(pos.get("tp_price")) if reel else None      # (also as tp_price: the engine state's name)
    return {"symbol": pos["symbol"], "side": pos["side"], "qty": pos["qty"],
            "entry": pos["entry_price"], "entry_time": pos["entry_time"],
            "leverage": pos["leverage"], "margin": pos["margin"], "stop": pos["stop_price"],
            "stop_initial": pos.get("stop_initial"), "lock_roe": pos.get("lock_roe"),
            "liq": pos["liq_price"], "exits": exits or "house",
            "tp": tp, "tp_price": tp,
            "time_exit": st.get("end") if reel and isinstance(st.get("end"), (int, float)) else None}
BOARD_TTL_S = 2.0            # Data.board() reused this long without a database read (G17), then while unchanged
DIGEST_TTL_S = 120           # /api/digest/staff reused this long
EQUITY_MAX_POINTS = 1_500    # /api/account/<id> equity series at most this long (first, last, each bucket's min and max)
TRADES_TTL_S = 600           # /api/digest/week and tf reused this long: they decode every closed trade since the start
OVERLAP_TTL_S = 600          # /api/overlap result reused this long (the analysis reads weeks of 5-minute equity)


def downsample(points: list, limit: int = EQUITY_MAX_POINTS) -> list:
    """An equity series ([{t, v}] in time order) of at most ``limit`` points for the chart: the first and last points
    and, in each of (limit - 2) / 2 equal buckets of the rest, its lowest and highest point in time order, so every
    peak and trough (the drawdowns) stays on the line. A series that fits is returned as it is."""
    n = len(points)
    if n <= max(3, limit):
        return points
    inner = points[1:-1]
    buckets = max(1, (limit - 2) // 2)
    out = [points[0]]
    for b in range(buckets):
        chunk = inner[b * len(inner) // buckets:(b + 1) * len(inner) // buckets]
        if not chunk:
            continue
        lo = min(range(len(chunk)), key=lambda i: chunk[i]["v"])
        hi = max(range(len(chunk)), key=lambda i: chunk[i]["v"])
        out.extend(chunk[i] for i in sorted({lo, hi}))
    out.append(points[-1])
    return out


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
    def __init__(self, db: str, daily_db: Optional[str] = None, checkpoint_db: Optional[str] = None):
        self.db = db
        self.daily_db = daily_db
        # the checkpoint job's verdicts (read-only): the countdown stays on a checkpoint until its verdict is stored
        # (dash/more/verdictday.py clock); by default checkpoint.db next to paper3.db, like create_app
        self.checkpoint_db = checkpoint_db or os.path.join(os.path.dirname(os.path.abspath(db)), "checkpoint.db")
        # board(): the last result and the database marks it was computed from (G17: every open page's live stream
        # asked for it every 3 s, a GROUP BY over all trades plus 331 engines each time)
        self._board_hit: Optional[tuple] = None   # (marks, board, time.monotonic() of the last marks check)
        self._board_lock = threading.Lock()
        self.board_ttl_s = BOARD_TTL_S
        self._curves: dict = {}                 # /api/v4/curves: per step, the finished steps (Data.curves)
        self._curve_lock = threading.Lock()

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
        """Trade cards of the last ``days`` days (all history when None). For one strategy (the strategy tab and
        its 30-day tag shares) only its own original accounts (kind 'strategy', 'ds200' or 'reel': strategy_kind): a
        copy account carries its parent's strategy name, but its trades follow another rule and are not the
        strategy's."""
        from ..cards import cards_from_db
        since = 0 if days is None else int(time.time() * 1000 - days * 86_400_000)
        d = self._daily()
        try:
            with self.conn() as c:
                return cards_from_db(c, self._round_trip(c), strategy, tf, losses_only, since, limit, d,
                                     names_ko(), kinds=(strategy_kind(strategy),) if strategy else None)
        finally:
            if d is not None:
                d.close()

    def card_stats(self, strategy: Optional[str], tf: Optional[str], days: Optional[float]) -> dict:
        """Tag shares of the last ``days`` days' closed trades (at most CARD_STATS_CAP, newest first). Without a
        strategy: the 36 and the reel only (DeepSeek and the coin flips are counted on their own screens). ``from_ts``
        / ``capped`` say which window the cap really covers (a busy run fills the cap in a few days)."""
        from ..cards import cards_from_db, tag_stats
        if strategy:
            cs = self.cards(strategy, tf, days, CARD_STATS_CAP, losses_only=False)
        else:
            since = 0 if days is None else int(time.time() * 1000 - days * 86_400_000)
            d = self._daily()
            try:
                with self.conn() as c:
                    cs = cards_from_db(c, self._round_trip(c), None, tf, False, since, CARD_STATS_CAP, d, names_ko(),
                                       kinds=CARD_STATS_KINDS)
            finally:
                if d is not None:
                    d.close()
        times = [c.get("exit_time") for c in cs if c.get("exit_time")]
        return {"trades": len(cs), "losses": sum(c["pnl"] < 0 for c in cs), "wins": sum(c["pnl"] > 0 for c in cs),
                "tags": tag_stats(cs), "from_ts": min(times) if times else None, "capped": len(cs) >= CARD_STATS_CAP,
                "cap": CARD_STATS_CAP, "kinds": None if strategy else list(CARD_STATS_KINDS)}

    def last_marks(self, strategy: str, tf: str, symbol: str, days: float = 30) -> Optional[dict]:
        """Entry marks (support / resistance, entry strength) of the strategy's latest logged signal
        on this timeframe and coin in the last ``days`` days; None when there is none."""
        since = int(time.time() * 1000 - days * 86_400_000)
        with self.conn() as c:
            r = c.execute("SELECT bar_close, side, status, data FROM signal_log WHERE timeframe = ? AND bar_close >= ? "
                          "AND strategy = ? AND symbol = ? ORDER BY bar_close DESC, id DESC LIMIT 1",
                          (tf, since, strategy, symbol)).fetchone()
        if r is None:
            return None
        try:
            ctx = (json.loads(r["data"]) or {}).get("ctx") or {}
        except (TypeError, ValueError, AttributeError):
            ctx = {}
        return {"bar_close": r["bar_close"], "side": r["side"], "status": r["status"], "sr": ctx.get("sr"),
                "strength": ctx.get("strength"), "error": ctx.get("marks_error")}

    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(_ro_uri(self.db), uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        return c

    def state(self, c, key: str) -> Optional[tuple[int, dict]]:
        r = c.execute("SELECT ts, data FROM state WHERE k = ?", (key,)).fetchone()
        return None if r is None else (int(r["ts"]), json.loads(r["data"]))

    @staticmethod
    def _extra_fields(a: dict, xstate: Optional[dict]) -> dict:
        """label_ko, rule, description_ko, proposal_id and the runner's status of an extra account (None for the
        original accounts): from accounts.data (written once by the runner) and state 'extras'."""
        from ..agents.extra_accounts import KINDS, extra_status, label_of, rule_ko
        raw = a.pop("data", None)
        if a.get("kind") not in KINDS:
            return {"label_ko": None, "rule": None, "description_ko": None, "proposal_id": None, "extra_status": None}
        try:
            d = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        src = d.get("source") if isinstance(d.get("source"), dict) else {}
        return {"label_ko": label_of({**a, "data": d}), "rule": d.get("rule"),
                "rule_ko": rule_ko(d.get("rule")) if d.get("rule") else None, "spec": d.get("spec"),
                "description_ko": d.get("description_ko"), "proposal_id": src.get("proposal_id"),
                "extra_status": extra_status(xstate, a["account_id"])}

    @staticmethod
    def _group_fields(a: dict) -> dict:
        """The paper v4 facts of an accounts row (paperbot/groups.py, display only): group (core / ds200 / reel / flip /
        extra; "other" for a kind it does not know), the DeepSeek family, the exit rule the account runs
        (accounts.exits_of: "reel" for the reel and the v4 5m coin flips, else "house") and a Korean name for a
        DeepSeek definition, the reel or a 5m coin flip (None for the others: the page names them as before).
        ``vs_random_ref``: the coin-flip comparison is reference only (DeepSeek: always "normal" leverage, the flips
        draw "best" 21% of the time, so they are not a fair yardstick)."""
        from .. import groups as G
        from ..accounts import exits_of
        g = G.group_of(a)
        try:
            exits = exits_of(a.get("kind"), a.get("timeframe"), a.get("data")) if g != "other" else None
        except Exception:  # noqa: BLE001  (a broken data column never hides the account)
            exits = None
        return {"group": g, "family": G.family_of(a), "exits": exits,
                "name_ko": G.label_ko(a.get("strategy"), a.get("timeframe")), "vs_random_ref": g == "ds200"}

    def extras_state(self, c) -> Optional[dict]:
        st = self.state(c, "extras")
        return st[1] if st and isinstance(st[1], dict) and st[1].get("v") == 1 else None

    @staticmethod
    def _board_mark(c) -> tuple:
        """What board() is computed from, as cheap marks: the state rows it reads (the engines, the extras, the run;
        their time and size), the last trade id and the accounts table's size. Equal marks = the same board."""
        st = tuple(tuple(r) for r in c.execute(
            "SELECT k, ts, length(data) FROM state WHERE k IN ('accounts', 'extras', 'run') ORDER BY k"))
        t = c.execute("SELECT MAX(id) FROM trades").fetchone()
        a = c.execute("SELECT COUNT(*), MAX(rowid) FROM accounts").fetchone()
        return st, tuple(t), tuple(a)

    def board(self) -> dict:
        """The leaderboard (/api/board, the live stream, the CSV export), NaN / infinity sent as null (json_finite).
        Reused for ``board_ttl_s`` (2 s) without looking at the database, then computed again only when the
        database marks (_board_mark) changed; the result is shared between callers: never change it in place (copy a
        row first)."""
        hit = self._board_hit
        now = time.monotonic()
        if hit is not None and now - hit[2] < self.board_ttl_s:
            return hit[1]
        with self.conn() as c:
            mark = self._board_mark(c)
        if hit is not None and hit[0] == mark:
            with self._board_lock:
                self._board_hit = (mark, hit[1], now)
            return hit[1]
        b = json_finite(self._board())
        with self._board_lock:
            self._board_hit = (mark, b, now)
        return b

    def _board(self) -> dict:
        with self.conn() as c:
            accts = [dict(r) for r in c.execute(
                "SELECT account_id, strategy, timeframe, kind, created_ts, parent, data FROM accounts ORDER BY rowid")]
            st = self.state(c, "accounts")
            eng = st[1]["engines"] if st else {}
            xstate = self.extras_state(c)
            stats = {r["account_id"]: dict(r) for r in c.execute(       # one pass over trades for every account
                "SELECT account_id, COUNT(*) AS trades, SUM(pnl > 0) AS wins, SUM(pnl < 0) AS losses, SUM(pnl) AS pnl, "
                "SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) AS gross_win, SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END) AS gross_loss, "
                "SUM(exit_reason = 'LOCK') AS locks, MAX(exit_time) AS last_exit, "
                "AVG(leverage) AS avg_lev FROM trades GROUP BY account_id")}
            shape = run_shape(c)
        for a in accts:
            a.update(self._group_fields(a))                 # (reads the data column: group, family, exits)
            a.update(self._extra_fields(a, xstate))         # (drops the raw data column)
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
                "wins": s.get("wins") or 0, "losses": s.get("losses") or 0,
                "gross_win": s.get("gross_win") or 0.0, "gross_loss": s.get("gross_loss") or 0.0,
                "locks": s.get("locks") or 0, "avg_leverage": s.get("avg_lev"),
                "last_exit": s.get("last_exit"),
                "position": None if not pos else board_position(pos, a.get("exits")),
            })
        # the best coin flip per timeframe: the comparison of every group on that timeframe (the reel's on 5m are the
        # three 5m flips with the reel's own exits, owners' D4; DeepSeek's is marked reference only, vs_random_ref)
        best_random = {}
        for r in rows:
            if r["kind"] == "random" and r["wallet"] is not None:
                best_random[r["timeframe"]] = max(best_random.get(r["timeframe"], 0.0), r["wallet"])
        for r in rows:
            b = best_random.get(r["timeframe"])
            r["beats_random"] = None if b is None or r["wallet"] is None else (r["wallet"] > b and not r["bust"])
            if r["kind"] in ("copy", "newlab") or r["group"] == "other":
                r["beats_random"] = None   # started later than the coin-flip accounts: their wallets are not comparable
        from .. import groups as G
        from ..agents.roster3 import STRATEGY_KO
        # strategy_ko: the names every Telegram message uses (app.js name() shows them, the code in a tooltip);
        # names_ko: the DeepSeek definitions and the reel (groups.label_ko), group_ko / family_ko: the group switch
        names_ko = {d: G.label_ko(d) for d in DS200_FAMILY}
        names_ko[REEL_NAME] = G.label_ko(REEL_NAME)
        return {"ts": st[0] if st else None, "accounts": rows, "best_random": best_random,
                "initial": self.initial(), "extras_runtime": xstate, "strategy_ko": dict(STRATEGY_KO),
                "names_ko": names_ko, "group_ko": dict(G.GROUP_KO), "family_ko": dict(G.DS_FAMILY_KO),
                "default_groups": list(G.DEFAULT_SHOWN_GROUPS), "run_shape": shape}

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
            from .. import levwhy as LW
            oc = LW.entered_outcomes(c, aid)                # the sizing's rejected candidates, per entry
            fixed_normal = a["kind"] in ("ds200", "reel") or (a["kind"] == "random" and a["timeframe"] == REEL_TF)
            for t in trades:
                d = json.loads(t.pop("data"))
                t.update(side=d["side"], entry_price=d["entry_price"], exit_price=d["exit_price"],
                         stop_initial=d.get("stop_initial"), lock_roe=d.get("lock_roe"),
                         fees=d["fees"], funding=d["funding"], tier=d.get("tier"))
                try:
                    t["why"] = LW.compact(LW.for_trade(d, oc))
                except Exception:  # noqa: BLE001  (an explanation never hides the trade)
                    t["why"] = None
                if fixed_normal:                            # DeepSeek, the reel, the 5m flips: always 'normal'
                    t["why"] = {**(t["why"] or {"leverage": t["leverage"]}), "short_ko": FIXED_NORMAL_KO,
                                "fixed": "normal"}
            eq = [{"t": r["ts"], "v": r["equity"]} for r in c.execute(
                "SELECT ts, equity FROM equity WHERE account_id = ? ORDER BY ts", (aid,))]
            eq_points = len(eq)
            eq = downsample(eq)
            counts = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM outcomes WHERE account_id = ? GROUP BY status", (aid,))}
            st = self.state(c, "accounts")
            xstate = self.extras_state(c)
            e = (st[1]["engines"].get(aid) if st else None) or {}
            pos_why = None
            if isinstance(e.get("position"), dict):
                try:
                    pos_why = LW.compact(LW.for_position(c, aid, e["position"]))
                except Exception:  # noqa: BLE001
                    pos_why = None
        acc = dict(a)
        acc.update(self._group_fields(acc))     # group, family, exits (the reel's own exits: no ladder), name_ko
        extra = None
        if acc.get("kind") in ("copy", "newlab"):
            extra = {**self._extra_fields(dict(acc), xstate), "kind": acc["kind"], "parent": acc.get("parent"),
                     "created_ts": acc.get("created_ts"),
                     "events": [ev for ev in (xstate or {}).get("events") or []
                                if isinstance(ev, dict) and ev.get("account_id") == aid][-50:]}
            try:
                src = (json.loads(acc.get("data") or "{}") or {}).get("source") or {}
            except (TypeError, ValueError, AttributeError):
                src = {}
            extra["trial_id"] = src.get("trial_id") if isinstance(src, dict) else None
        # an open position's tp_price is NaN under the ladder exits (engine.py: no fixed take-profit), and
        # json.loads gives it back as NaN: not valid JSON (the route answered 500 for every account holding one)
        return json_finite({"account": acc, "state": e, "trades": trades, "equity": eq, "equity_points": eq_points,
                            "signals": counts, "extra": extra, "position_why": pos_why})

    def position_why(self) -> dict:
        """{account_id: why} of every open position (levwhy: group, score, leverage, the rejected higher candidates)."""
        from .. import levwhy as LW
        out = {}
        with self.conn() as c:
            st = self.state(c, "accounts")
            fixed = {r[0] for r in c.execute(
                "SELECT account_id FROM accounts WHERE kind IN ('ds200', 'reel') OR (kind = 'random' AND timeframe = ?)",
                (REEL_TF,))}
            for aid, e in ((st[1].get("engines") or {}) if st else {}).items():
                p = (e or {}).get("position")
                if not isinstance(p, dict):
                    continue
                try:
                    out[aid] = {**LW.compact(LW.for_position(c, aid, p)), "entry_time": p.get("entry_time")}
                except Exception:  # noqa: BLE001
                    if aid not in fixed:
                        continue
                    out[aid] = {"entry_time": p.get("entry_time"), "leverage": p.get("leverage")}
                if aid in fixed:
                    # DeepSeek, the reel and its 5m coin flips always trade at the 'normal' multiple (no 'best' search:
                    # p_best 0), so there is no rejected higher step to explain
                    out[aid].update(short_ko=FIXED_NORMAL_KO, fixed="normal")
        return {"positions": out}

    def status(self) -> dict:
        with self.conn() as c:
            hb = self.state(c, "heartbeat")
            run = self.state(c, "run")
            alerts = [dict(r) for r in c.execute(
                "SELECT ts, level, text FROM alerts WHERE level != 'INFO' ORDER BY rowid DESC LIMIT 50")]
            # the original accounts' signals only: a new-strategy account's own rows (strategy 'NL<n>', written
            # after the originals' compute) are not theirs (as in agents/packets3.py)
            since = int(time.time() * 1000) - 86_400_000
            # one pass over the day's signal_log: per (strategy, timeframe, status); the per-timeframe rows
            # (signals_24h) and the per-group rows (signals_by_group) are summed from it
            by_strategy = [dict(r) for r in c.execute(
                "SELECT strategy, timeframe, status, COUNT(*) AS n, SUM(delay_ms) AS dsum, COUNT(delay_ms) AS dn, "
                "MAX(delay_ms) AS max_delay FROM signal_log WHERE bar_close > ? AND strategy NOT GLOB 'NL[0-9]*' "
                "GROUP BY strategy, timeframe, status", (since,))]
            # the operations alerts (signal timeouts, data, the nightly check, ...) apart from the per-account lines
            # ('[A@15m] LIQUIDATED', '... BUST', drawdowns), which a liquidation burst of 171 DeepSeek accounts would
            # otherwise push out of the last 50 (G15)
            ops = [dict(r) for r in c.execute(
                "SELECT ts, level, text FROM alerts WHERE level != 'INFO' ORDER BY rowid DESC LIMIT 1000")]
        return {"now": int(time.time() * 1000), "heartbeat": hb, "run": run, "alerts": alerts,
                "ops_alerts": [a for a in ops if not account_line(a.get("text"))][:50],
                "signals_24h": signals_by_tf(by_strategy), "signals_by_group": signals_by_group(by_strategy),
                "limits": dict(SIGNAL_LIMITS)}

    def summary(self, now_ms: Optional[int] = None) -> dict:
        """Experiment progress (day n of 30, next checkpoint, observation period) and today's summary (KST day)."""
        from ..accounts import GROUP_OF_KIND, ORIGINAL_KINDS
        from ..checkpoint import PERIOD_DAYS
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        day_ms, kst = 86_400_000, 9 * 3_600_000
        with self.conn() as c:
            r = c.execute("SELECT MIN(created_ts) FROM accounts WHERE kind IN (%s)" % ",".join("?" * len(ORIGINAL_KINDS)),
                          ORIGINAL_KINDS).fetchone()
            start = int(r[0]) if r and r[0] is not None else None
            xs = self.extras_state(c)
            since = (now + kst) // day_ms * day_ms - kst                     # 00:00 KST today
            rows = [dict(x) for x in c.execute(
                "SELECT t.account_id, a.kind, t.pnl, t.exit_reason FROM trades t JOIN accounts a "
                "ON a.account_id = t.account_id WHERE t.exit_time >= ?", (since,))]
        out: dict = {"now": now, "start": start, "period_days": PERIOD_DAYS}
        # the verdict-day clock (dash/more/verdictday.py): a checkpoint that has passed stays the next one until the
        # checkpoint job has stored its verdict (never '2번째 판정 · 30일 남음' on the morning of the first verdict)
        from .more.verdictday import clock, day_state_reader, read_ledger
        ledger = read_ledger(self.checkpoint_db)
        day_state = day_state_reader(self.db)
        if start is not None:
            out["day"] = (now - (start - start % day_ms)) // day_ms + 1
            vc = clock(start, now, ledger, day_state)
            out["next_checkpoint"] = {"k": vc["k"], "ts": vc["ts"], "day": vc["day"], "due": vc["due"],
                                      "state": vc["state"]}
            out["verdict_clock"] = vc
            floor = (xs or {}).get("observe_until")
            obs = floor if isinstance(floor, int) and not isinstance(floor, bool) else start + 21 * day_ms
            out["observe_until"] = obs
            out["observing"] = now < obs
        # the restart banner (checkpoint.run_facts / checkpoint_ts, the verdict job's own definitions)
        try:
            from ..checkpoint import run_facts
            with self.conn() as c:
                rs = run_facts(c).get("start_ts")
        except (sqlite3.Error, TypeError, ValueError):
            rs = start
        out["restart"] = restart_banner(rs, now, ledger, day_state)
        per: dict = {}
        group = {}
        for x in rows:
            per[x["account_id"]] = per.get(x["account_id"], 0.0) + x["pnl"]
            group[x["account_id"]] = GROUP_OF_KIND.get(x["kind"], "other")

        def ranked(gs) -> tuple[list, list]:
            rank = sorted(((a, p) for a, p in per.items() if group[a] in gs), key=lambda kv: kv[1])
            return ([{"account_id": a, "pnl": round(p, 2)} for a, p in rank[::-1][:3] if p > 0],
                    [{"account_id": a, "pnl": round(p, 2)} for a, p in rank[:3] if p < 0])
        strat = [x for x in rows if x["kind"] == "strategy"]
        # best / worst: the 36, the reel and the extras (the DeepSeek P&L only in its own group, D11; the coin flips are
        # the yardstick); by_group: each group's own numbers (the page shows the groups its switch selects)
        best, worst = ranked(MAIN_GROUPS)
        by_group = {}
        for g in GROUP_ORDER:
            xs = [x for x in rows if group[x["account_id"]] == g]
            gb, gw = ranked((g,))
            by_group[g] = {"trades": len(xs), "pnl": round(sum(x["pnl"] for x in xs), 2),
                           "wins": sum(x["pnl"] > 0 for x in xs), "liquidations": sum(x["exit_reason"] == "LIQ" for x in xs),
                           "best": gb, "worst": gw}
        out["today"] = {"since": since, "trades": len(rows), "pnl": round(sum(x["pnl"] for x in strat), 2),
                        "wins": sum(x["pnl"] > 0 for x in strat), "strategy_trades": len(strat),
                        "liquidations": sum(x["exit_reason"] == "LIQ" for x in rows),
                        "best": best, "worst": worst, "by_group": by_group}
        try:   # the next US macro releases of data/macro_events.csv (events.py); [] when none is registered
            from .. import events
            out["events"] = [e.as_dict() for e in events.all_events() if e.ts_ms >= now][:3]
        except Exception:  # noqa: BLE001  (a broken calendar never hides the summary)
            out["events"] = []
        return out

    def liquidations(self, liq_db: str, symbol: str, minutes: int, now_ms: Optional[int] = None,
                     limit: int = 12) -> dict:
        """Market-wide forced orders of one coin from liq.db (liqstream.py, its own writer): totals of the
        last ``minutes`` and the latest rows. A SELL forced order closes a long, a BUY closes a short."""
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        since = now - minutes * 60_000
        out = {"symbol": symbol, "minutes": minutes, "long_usd": 0.0, "short_usd": 0.0, "n": 0, "rows": [],
               "recorder": False}
        if not os.path.exists(liq_db):
            return out
        c = sqlite3.connect(_ro_uri(liq_db), uri=True, timeout=5)
        try:
            for side, n, usd in c.execute(
                    "SELECT side, COUNT(*), SUM(COALESCE(NULLIF(avg_price, 0), price) * COALESCE(NULLIF(filled_qty, 0), qty)) "
                    "FROM liq WHERE symbol = ? AND trade_ts >= ? GROUP BY side", (symbol, since)):
                out["n"] += n
                out["long_usd" if side == "SELL" else "short_usd"] += float(usd or 0)
            out["rows"] = [{"ts": ts, "liquidated": "long" if side == "SELL" else "short", "price": px_,
                            "usd": round(float(usd or 0), 2)} for ts, side, px_, usd in c.execute(
                "SELECT trade_ts, side, COALESCE(NULLIF(avg_price, 0), price), "
                "COALESCE(NULLIF(avg_price, 0), price) * COALESCE(NULLIF(filled_qty, 0), qty) FROM liq "
                "WHERE symbol = ? ORDER BY trade_ts DESC LIMIT ?", (symbol, limit))]
            r = c.execute("SELECT MAX(received_ts) FROM liq").fetchone()
            out["last_any"] = r[0] if r else None
            out["recorder"] = True
        except sqlite3.Error:
            pass
        finally:
            c.close()
        out["long_usd"], out["short_usd"] = round(out["long_usd"], 2), round(out["short_usd"], 2)
        return out

    MARKET_SCAN = 60_000          # 전체 시장: the newest rows looked at (rowid order = arrival order; no trade_ts index)

    def liquidations_market(self, liq_db: str, minutes: int, now_ms: Optional[int] = None, limit: int = 30) -> dict:
        """Every coin's forced orders from liq.db (the recorder keeps the whole market): totals of the last ``minutes``
        and the latest rows with their coin. Bounded: only the newest ``MARKET_SCAN`` rows by rowid are read (the
        table has no trade_ts index); ``capped`` says the window may hold more than that."""
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        since = now - minutes * 60_000
        out = {"symbol": "ALL", "minutes": minutes, "long_usd": 0.0, "short_usd": 0.0, "n": 0, "rows": [],
               "recorder": False, "capped": False}
        if not os.path.exists(liq_db):
            return out
        c = sqlite3.connect(_ro_uri(liq_db), uri=True, timeout=5)
        try:
            top = (c.execute("SELECT MAX(rowid) FROM liq").fetchone() or [None])[0]
            if top is not None:
                lo = int(top) - self.MARKET_SCAN
                usd = "COALESCE(NULLIF(avg_price, 0), price) * COALESCE(NULLIF(filled_qty, 0), qty)"
                for side, n, v in c.execute(f"SELECT side, COUNT(*), SUM({usd}) FROM liq WHERE rowid > ? AND trade_ts >= ? "
                                            "GROUP BY side", (lo, since)):
                    out["n"] += n
                    out["long_usd" if side == "SELL" else "short_usd"] += float(v or 0)
                first = c.execute("SELECT trade_ts FROM liq WHERE rowid = (SELECT MIN(rowid) FROM liq WHERE rowid > ?)",
                                  (lo,)).fetchone()
                out["capped"] = bool(lo > 0 and first and first[0] is not None and int(first[0]) > since)
                out["rows"] = [{"symbol": sym, "ts": ts, "liquidated": "long" if side == "SELL" else "short", "price": px_,
                                "usd": round(float(v or 0), 2)} for sym, ts, side, px_, v in c.execute(
                    f"SELECT symbol, trade_ts, side, COALESCE(NULLIF(avg_price, 0), price), {usd} FROM liq "
                    "WHERE rowid > ? ORDER BY trade_ts DESC LIMIT ?", (max(lo, int(top) - 5_000), limit))]
            r = c.execute("SELECT MAX(received_ts) FROM liq").fetchone()
            out["last_any"] = r[0] if r else None
            out["recorder"] = True
        except sqlite3.Error:
            pass
        finally:
            c.close()
        out["long_usd"], out["short_usd"] = round(out["long_usd"], 2), round(out["short_usd"], 2)
        return out

    def trades_csv(self, account: Optional[str] = None) -> str:
        """Every closed trade (or one account's) as CSV, KST times, for Excel (UTF-8 with BOM)."""
        import csv
        import io
        q = ("SELECT t.account_id, a.kind, t.data FROM trades t JOIN accounts a ON a.account_id = t.account_id"
             + (" WHERE t.account_id = ?" if account else "") + " ORDER BY t.exit_time")
        with self.conn() as c:
            rows = c.execute(q, (account,) if account else ()).fetchall()
        kst = lambda ms: time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(int(ms) / 1000 + 9 * 3600)) if ms else ""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["계좌", "종류", "코인", "봉", "방향", "진입(한국)", "청산(한국)", "청산 이유", "레버리지", "진입가",
                    "청산가", "수량", "손익(USDT)", "ROE", "수수료", "펀딩", "청산 후 잔고"])
        for aid, kind, data in rows:
            try:
                d = json.loads(data)
            except (TypeError, ValueError):
                continue
            w.writerow([aid, kind, d.get("symbol"), d.get("timeframe"), "롱" if d.get("side", 0) > 0 else "숏",
                        kst(d.get("entry_time")), kst(d.get("exit_time")), d.get("exit_reason"), d.get("leverage"),
                        d.get("entry_price"), d.get("exit_price"), d.get("qty"), round(d.get("pnl") or 0, 4),
                        round(d.get("roe") or 0, 6), round(d.get("fees") or 0, 4), round(d.get("funding") or 0, 4),
                        round(d.get("equity_after") or 0, 4)])
        return "\ufeff" + buf.getvalue()

    def board_csv(self) -> str:
        import csv
        import io
        b = self.board()
        init = b.get("initial") or 0
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["계좌", "종류", "매매법", "봉", "잔고", "수익률", "거래", "승률", "최대 낙폭", "파산", "동전 봇보다 나음",
                    "그룹", "딥시크 계열", "청산 방식"])
        for a in b["accounts"]:
            wal = a.get("wallet")
            w.writerow([a["account_id"], a.get("kind"), a.get("strategy"), a.get("timeframe"),
                        "" if wal is None else round(wal, 2), "" if wal is None or not init else round(wal / init - 1, 6),
                        a.get("trades"), a.get("win_rate"), a.get("max_drawdown"), a.get("bust"),
                        ("참고 " if a.get("vs_random_ref") and a.get("beats_random") is not None else "")
                        + ("" if a.get("beats_random") is None else str(a.get("beats_random"))),
                        a.get("group"), a.get("family") or "", a.get("exits") or ""])
        return "\ufeff" + buf.getvalue()

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

    def trades(self, symbol: Optional[str], timeframe: Optional[str], limit: int, group: Optional[str] = None) -> list[dict]:
        """The latest closed trades (newest first), of one coin / timeframe / group view (VIEW_SQL) when given."""
        from ..accounts import GROUP_OF_KIND
        q = ("SELECT t.id, t.account_id, t.symbol, t.entry_time, t.exit_time, t.exit_reason, t.leverage, t.pnl, "
             "t.roe, t.equity_after, t.data, a.strategy, a.timeframe, a.kind FROM trades t "
             "JOIN accounts a ON a.account_id = t.account_id")
        where, args = [], []
        if group in VIEW_SQL:
            where.append(VIEW_SQL[group])
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
                     lock_roe=d.get("lock_roe"), tier=d.get("tier"), group=GROUP_OF_KIND.get(r.get("kind"), "other"))
        return rows

    def curves(self, step_ms: int = 3_600_000, now_ms: Optional[int] = None) -> dict:
        """/api/v4/curves: the original accounts' equity over the run (paper3.db ``equity``, every 5 minutes per
        account): each account's last value in each ``step`` (carried forward while it has none), the median per kind
        (strategy = the 36, ds200, reel, random = all 15 coin flips, random_5m = the reel's three 5m flips) and the
        sum over every original account except DeepSeek (owners' D11: its money only on the DeepSeek screen). Points are the end of each step (the running step: now). Incremental: the
        finished steps are kept, only the new rows are read (one indexed query per account)."""
        from ..accounts import ORIGINAL_KINDS
        step = min(CURVE_STEPS, key=lambda x: abs(x - int(step_ms)))
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        with self._curve_lock:
            with self.conn() as c:
                accts = [(r[0], r[1], r[2]) for r in c.execute(
                    "SELECT account_id, kind, timeframe FROM accounts WHERE kind IN (%s)"
                    % ",".join("?" * len(ORIGINAL_KINDS)), ORIGINAL_KINDS)]
                r = c.execute("SELECT MIN(created_ts) FROM accounts WHERE kind IN (%s)"
                              % ",".join("?" * len(ORIGINAL_KINDS)), ORIGINAL_KINDS).fetchone()
                start = int(r[0]) if r and r[0] is not None else None
                out = {"initial": self.initial(), "step": step, "start": start, "keys": list(CURVE_KEYS),
                       "t": [], "median": {k: [] for k in CURVE_KEYS}, "total": []}
                if start is None or not accts:
                    return out
                key_of = {aid: curve_keys(kind, tf) for aid, kind, tf in accts}
                st = self._curves.get(step)
                cur_b = now // step
                if st is None or st["start"] != start:          # a new run (or the first call): from its start, at
                    # most the last CURVE_MAX_POINTS steps (equity is written every 5 minutes for every account)
                    st = {"start": start, "done_b": max(start // step, cur_b - CURVE_MAX_POINTS) - 1, "last": {},
                          "t": [], "median": {k: [] for k in CURVE_KEYS}, "total": []}
                from_ts = max(start, (st["done_b"] + 1) * step)
                new: dict = {}
                for aid, _k, _tf in accts:
                    for b, eq, _ts in c.execute("SELECT ts / ? AS b, equity, MAX(ts) FROM equity "
                                                "WHERE account_id = ? AND ts >= ? GROUP BY b", (step, aid, from_ts)):
                        new.setdefault(int(b), {})[aid] = float(eq)
            last = dict(st["last"])

            def point(vals: dict) -> tuple:
                xs: dict = {k: [] for k in CURVE_KEYS}
                tot = 0.0
                for a, v in vals.items():
                    for k in key_of.get(a, ()):
                        xs[k].append(v)
                    if a in key_of and "ds200" not in key_of[a]:   # DeepSeek money only on its own screen (D11)
                        tot += v
                return {k: round(statistics.median(x), 2) if x else None for k, x in xs.items()}, round(tot, 2)
            # steps that ended CURVE_SETTLE_MS ago are kept (a late equity row of theirs is in by then); the newer
            # ones and the running step are shown, computed again next time
            settled_b = (now - CURVE_SETTLE_MS) // step

            def add(b: int, dst: dict, ts: int) -> None:
                last.update(new.get(b, {}))
                if not last:
                    return
                med, tot = point(last)
                dst["t"].append(ts)
                for k in CURVE_KEYS:
                    dst["median"][k].append(med[k])
                dst["total"].append(tot)
            for b in range(st["done_b"] + 1, settled_b):
                add(b, st, (b + 1) * step)
            st["done_b"], st["last"] = max(st["done_b"], settled_b - 1), dict(last)
            for k in ("t", "total"):
                del st[k][:-CURVE_MAX_POINTS]
            for v in st["median"].values():
                del v[:-CURVE_MAX_POINTS]
            self._curves[step] = st
            tmp = {"t": list(st["t"]), "total": list(st["total"]), "median": {k: list(v) for k, v in st["median"].items()}}
            for b in range(st["done_b"] + 1, cur_b + 1):
                add(b, tmp, now if b == cur_b else (b + 1) * step)
            t, total, mk = tmp["t"], tmp["total"], tmp["median"]
        n = CURVE_MAX_POINTS
        return {**out, "t": t[-n:], "median": {k: v[-n:] for k, v in mk.items()}, "total": total[-n:]}

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


# Imported here once, on the starting thread: the routes import them lazily from FastAPI's worker threads, and two
# first imports of scipy at the same moment (a page load asks /api/levels and /api/rooms together) left it half
# initialised ("partially initialized module 'scipy._lib._testutils'"), so every later request that needed it
# (/api/rooms, /api/analysis/health) answered 500 until the dashboard restarted.
WARM_IMPORTS = ("scipy", "scipy.signal", "scipy.stats", "scipy.sparse")


def warm_imports(names=WARM_IMPORTS) -> None:
    import importlib
    for n in names:
        try:
            importlib.import_module(n)
        except Exception:  # noqa: BLE001  (a missing optional package: the route that needs it reports it)
            pass


def json_finite(o):
    """``o`` with every NaN / infinity float replaced by None (JSON has no such numbers: Starlette refuses them)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: json_finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_finite(v) for v in o]
    return o


def fetch_candles(symbol: str, interval: str, limit: int = 300) -> list:
    key = (symbol, interval, limit)
    hit = _CANDLE_CACHE.get(key)
    if hit and time.time() - hit[0] < (4 if limit <= 5 else 20):     # small requests: the live-bar fallback
        return hit[1]
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    with urllib.request.urlopen(url, timeout=10) as r:
        rows = json.loads(r.read())
    # volume (base asset) feeds the chart's volume bars (v4 chart deck); older pages ignore the extra key
    out = [{"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4]), "volume": float(k[5])} for k in rows]
    _CANDLE_CACHE[key] = (time.time(), out)
    return out


TICKER_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT")
_TICKER_CACHE: dict = {}


def _ticker_row(s: str) -> dict:
    row: dict = {}
    try:
        with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={s}", timeout=5) as r:
            t = json.loads(r.read())
        row.update(c=float(t["lastPrice"]), p=float(t["priceChangePercent"]), h=float(t["highPrice"]),
                   l=float(t["lowPrice"]), q=float(t["quoteVolume"]))
    except Exception:  # noqa: BLE001  (one coin missing is shown as "—")
        pass
    try:
        with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={s}", timeout=5) as r:
            m = json.loads(r.read())
        row.update(mark=float(m["markPrice"]), r=float(m["lastFundingRate"]), T=int(m["nextFundingTime"]))
    except Exception:  # noqa: BLE001
        pass
    return row


def fetch_ticker() -> dict:
    """24h change/high/low/quote volume, mark price and funding of the 7 coins, fetched by the server.
    The page normally gets these from Binance's WebSocket in the browser; where that is blocked (some
    networks, some phones) it polls this instead (the v4 page's main price source). Per-symbol requests (weight 1
    each, 14 per refresh: the all-symbol forms weigh 40 + 10), the 7 coins in parallel, and a 5 s cache shared by
    every viewer, so the bot's own Binance weight budget is never at risk."""
    from concurrent.futures import ThreadPoolExecutor
    hit = _TICKER_CACHE.get("t")
    if hit and time.time() - hit[0] < 5:
        return hit[1]
    with ThreadPoolExecutor(max_workers=len(TICKER_SYMBOLS)) as ex:
        rows = list(ex.map(_ticker_row, TICKER_SYMBOLS))
    out = {s: row for s, row in zip(TICKER_SYMBOLS, rows) if row}
    _TICKER_CACHE["t"] = (time.time(), out)
    return out


_MARKET_CACHE: dict = {}
INDEXES = (("^IXIC", "나스닥"), ("^GSPC", "S&P 500"), ("DX-Y.NYB", "달러 지수"), ("^TNX", "미국 10년 금리"))
FNG_KO = {"Extreme Fear": "극도의 공포", "Fear": "공포", "Neutral": "중립", "Greed": "탐욕", "Extreme Greed": "극도의 탐욕"}


def _get_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (paperbot dashboard)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _cached(key: str, ttl: float, fn):
    hit = _MARKET_CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as exc:  # noqa: BLE001  (one source down is shown as such; the others still show)
        val = {"error": type(exc).__name__}
        if hit and "error" not in hit[1]:
            return {**hit[1], "stale": True}            # keep the last good value, marked old
    _MARKET_CACHE[key] = (time.time(), val)
    return val


def _fng(get) -> dict:
    d = get("https://api.alternative.me/fng/?limit=8")["data"]
    pick = lambda i: {"value": int(d[i]["value"]), "label": d[i]["value_classification"],    # noqa: E731
                      "label_ko": FNG_KO.get(d[i]["value_classification"], d[i]["value_classification"]),
                      "ts": int(d[i]["timestamp"]) * 1000} if len(d) > i else None
    return {"now": pick(0), "yesterday": pick(1), "week": pick(7)}


def _global(get) -> dict:
    g = get("https://api.coingecko.com/api/v3/global")["data"]
    return {"btc_dom": g["market_cap_percentage"].get("btc"), "eth_dom": g["market_cap_percentage"].get("eth"),
            "total_mcap": g["total_market_cap"].get("usd"), "mcap_chg_24h": g.get("market_cap_change_percentage_24h_usd"),
            "ts": int(g.get("updated_at") or 0) * 1000}


def _index(get, sym: str) -> dict:
    r = get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym, safe="")
            + "?range=5d&interval=30m")["chart"]["result"][0]
    m = r["meta"]
    ts, cl = r.get("timestamp") or [], (r.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    pts = [[int(t) * 1000, float(c)] for t, c in zip(ts, cl) if c is not None]
    step = max(1, len(pts) // 120)
    price, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
    day_prev = None
    if pts:                       # the change of the latest session: against the last close of the session before
        last_day = time.strftime("%Y-%m-%d", time.gmtime(pts[-1][0] / 1000 + int(m.get("gmtoffset") or 0)))
        before = [c for t, c in pts if time.strftime("%Y-%m-%d", time.gmtime(t / 1000 + int(m.get("gmtoffset") or 0))) < last_day]
        day_prev = before[-1] if before else None
    base = day_prev or prev
    return {"price": price, "prev": base, "chg": (price / base - 1) if price and base else None,
            "ts": int(m.get("regularMarketTime") or 0) * 1000, "points": pts[::step][-120:]}


def fetch_market(get=None) -> dict:
    """Fear & greed (alternative.me), dominance and total market cap (CoinGecko), Nasdaq, S&P 500, dollar index
    and the US 10-year yield (Yahoo Finance, 5 days of 30-minute closes). Each source on its own: one that fails
    shows as missing (or its last good value, marked stale). Cached for everyone: 30 min / 5 min / 5 min."""
    get = get or _get_json
    return {"fng": _cached("fng", 1800, lambda: _fng(get)), "global": _cached("global", 300, lambda: _global(get)),
            "indexes": [{"symbol": s, "name": n, **_cached("ix:" + s, 300, lambda s=s: _index(get, s))}
                        for s, n in INDEXES]}


_DEPTH_CACHE: dict = {}


def fetch_depth(symbol: str) -> dict:
    """Top 20 bids and asks of one coin, fetched by the server (fallback when the browser's WebSocket is blocked).
    Weight 2 per request, 2 s cache shared by every viewer."""
    hit = _DEPTH_CACHE.get(symbol)
    if hit and time.time() - hit[0] < 2:
        return hit[1]
    with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit=20", timeout=5) as r:
        d = json.loads(r.read())
    out = {"bids": [[float(p), float(q)] for p, q in d.get("bids", [])],
           "asks": [[float(p), float(q)] for p, q in d.get("asks", [])], "T": d.get("T")}
    _DEPTH_CACHE[symbol] = (time.time(), out)
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


TF_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
V4_COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")   # DeepSeek and the reel: no XRP


def view_bars(tf: str, strategy: Optional[str] = None) -> int:
    """History for a strategy view: the live signal service's window, so indicators that depend on their start match
    the bot's. The 36: two warm-ups, at most 6,000 bars (four requests). A DeepSeek definition: its live window
    (config.DS_WINDOW_5M 5m bars as chart bars: 15m 5,763, 30m 2,883, 1h 3,000, 4h 2,400). The reel:
    config.REEL_WINDOW_5M 5m bars."""
    from ..config import DS_WINDOW_5M, REEL_WINDOW_5M
    if strategy == REEL_NAME:
        return int(REEL_WINDOW_5M)
    if strategy in DS200_FAMILY and tf in DS_WINDOW_5M and tf in TF_MINUTES:
        return int(DS_WINDOW_5M[tf] * 5 // TF_MINUTES[tf])
    from .. import sweepsig
    lib = sweepsig.lib()
    return int(min(6000, max(1500, 2 * lib.warmup_bars(tf) + 3)))


# ---------------------------------------------------------------- app
FEED_ROOM_COLUMNS = ("room_id", "round_id", "speaker_name")


def agent_feed(agents_db: Optional[str], limit: int = 200, after_id: int = 0) -> list[dict]:
    """Meeting messages of agents3.db, newest first (``after_id``: only newer ones), each with its room, its meeting
    (round) and the speaker's name when the table has them (the agent rooms' messages: None otherwise)."""
    if not agents_db or not os.path.exists(agents_db):
        return []
    c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(agents_db))}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    try:
        have = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
        extra = [x for x in FEED_ROOM_COLUMNS if x in have]
        rows = [dict(r) for r in c.execute(
            "SELECT id, ts, meeting, role, kind, text, data%s FROM messages WHERE id > ? ORDER BY id DESC LIMIT ?"
            % "".join(f", {x}" for x in extra), (max(int(after_id), 0), min(max(int(limit), 1), 1000)))]
        for r in rows:
            for x in FEED_ROOM_COLUMNS:
                r.setdefault(x, None)
        return rows
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def stream_event(data: "Data", rooms: "Rooms", st: dict) -> str:
    """One /api/stream event ('data: {...}' + blank line): the trades and non-INFO alerts after the page's cursors
    (``st`` trade_id / alert_row, moved on here), the board rows that changed since the last event (wallet, trades,
    bust, position), the heartbeat and the agent rooms with new messages (``st`` room_msg). Strict JSON: a NaN or an
    infinity anywhere (an open position's NaN target, a trade's NaN) is sent as null, so the page's JSON.parse never
    drops the event (G12)."""
    # new agent-room messages (agents3.db max(id)): the page refreshes the rooms that changed
    st["room_msg"], rooms_changed = rooms.since(st["room_msg"])
    d = data.since(st["trade_id"], st["alert_row"])
    if d["trades"]:
        st["trade_id"] = d["trades"][-1]["id"]
    if d["alerts"]:
        st["alert_row"] = d["alerts"][-1]["rid"]
    b = data.board()                       # finite already (json_finite), shared: read only
    slim = {r["account_id"]: [r["wallet"], r["trades"], r["bust"], r["position"]] for r in b["accounts"]}
    last = st.get("last_board")
    changed = {k: v for k, v in slim.items() if last is None or last.get(k) != v}
    st["last_board"] = slim
    payload = {"ts": b["ts"], "changed": changed, "trades": d["trades"], "alerts": d["alerts"],
               "heartbeat": d["heartbeat"], "room_msg": st["room_msg"], "rooms": rooms_changed}
    return f"data: {json.dumps(json_finite(payload), allow_nan=False)}\n\n"


# ---------------------------------------------------------------- server facts (/api/v4/server)
_CPU_LAST: dict = {}            # the previous /proc/stat sample: {"t": monotonic s, "total": jiffies, "idle": jiffies}
_DB_SIZES: list = []            # (ts ms, bytes of the three databases) samples of this process: the daily growth
SERVER_TTL_S = 5


def _cpu_sample(path: str) -> tuple[int, int]:
    with open(path, encoding="ascii") as fh:
        vals = [int(x) for x in fh.readline().split()[1:9]]      # user nice system idle iowait irq softirq steal
    return sum(vals), vals[3] + (vals[4] if len(vals) > 4 else 0)


def cpu_facts(path: str = "/proc/stat") -> Optional[dict]:
    """{"pct", "cores"}: the busy share since the previous call (1 s .. 10 min ago), else over a 0.25 s sample."""
    try:
        total, idle = _cpu_sample(path)
        prev = dict(_CPU_LAST)
        if not prev or not 1 <= time.monotonic() - prev["t"] <= 600 or total <= prev["total"]:
            time.sleep(0.25)
            prev = {"t": time.monotonic(), "total": total, "idle": idle}
            total, idle = _cpu_sample(path)
        _CPU_LAST.update(t=time.monotonic(), total=total, idle=idle)
        dt = total - prev["total"]
        pct = 100.0 * (1 - (idle - prev["idle"]) / dt) if dt > 0 else None
    except (OSError, ValueError, IndexError):
        return None
    return {"pct": None if pct is None else round(min(max(pct, 0.0), 100.0), 1), "cores": os.cpu_count()}


def mem_facts(path: str = "/proc/meminfo") -> Optional[dict]:
    """{"used_mb", "total_mb"}: total minus what the kernel can hand out (MemAvailable)."""
    try:
        kb = {}
        with open(path, encoding="ascii") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                kb[k.strip()] = int(v.split()[0])
        total, avail = kb["MemTotal"], kb.get("MemAvailable", kb.get("MemFree", 0))
    except (OSError, ValueError, KeyError, IndexError):
        return None
    return {"used_mb": round((total - avail) / 1024, 1), "total_mb": round(total / 1024, 1)}


def disk_facts(path: str) -> Optional[dict]:
    """{"used_gb", "total_gb"} of the file system that holds the databases."""
    try:
        v = os.statvfs(path)
    except OSError:
        return None
    gb = 1024 ** 3
    return {"used_gb": round((v.f_blocks - v.f_bfree) * v.f_frsize / gb, 2), "total_gb": round(v.f_blocks * v.f_frsize / gb, 2)}


def _file_bytes(path: Optional[str]) -> Optional[int]:
    """A SQLite database's size with its write-ahead log; None when it is not there."""
    if not path or not os.path.exists(path):
        return None
    return sum(os.path.getsize(p) for p in (path, path + "-wal") if os.path.exists(p))


def db_facts(paper_db: str, agents_db: Optional[str], daily_db: Optional[str], now_ms: int) -> dict:
    """{"paper3_mb", "agents3_mb", "daily3_mb", "growth_mb_day"}: the growth from this process's samples (None until
    they span 6 hours: the dashboard keeps no size log of its own)."""
    sizes = {k: _file_bytes(p) for k, p in (("paper3", paper_db), ("agents3", agents_db), ("daily3", daily_db))}
    total = sum(v for v in sizes.values() if v)
    if not _DB_SIZES or now_ms - _DB_SIZES[-1][0] >= 3_600_000:
        _DB_SIZES.append((now_ms, total))
        del _DB_SIZES[:-200]
    first = next(((t, b) for t, b in _DB_SIZES if now_ms - t <= 8 * 86_400_000), None)
    span = (now_ms - first[0]) if first else 0
    growth = (total - first[1]) / 1024 ** 2 / (span / 86_400_000) if first and span >= 6 * 3_600_000 else None
    out = {f"{k}_mb": None if v is None else round(v / 1024 ** 2, 1) for k, v in sizes.items()}
    out["growth_mb_day"] = None if growth is None else round(growth, 1)
    return out


def signal_time(c, now_ms: int) -> list:
    """[{tf, bar_close, max_delay_ms, limit_ms, last_bar_close, last_delay_ms}]: per timeframe, the boundary of the
    last 24 hours whose signals waited longest (its slowest signal against the timeframe's limit) and the newest
    boundary (paper3.db signal_log; one indexed range per timeframe: siglog_tf)."""
    out = []
    since = now_ms - 86_400_000
    for tf in TF_MINUTES:                      # the timeframes the accounts trade (5m .. 4h)
        r = c.execute("SELECT bar_close, MAX(delay_ms) FROM signal_log WHERE timeframe = ? AND bar_close > ? "
                      "AND delay_ms IS NOT NULL AND strategy NOT GLOB 'NL[0-9]*'", (tf, since)).fetchone()
        if r is None or r[1] is None:
            continue
        last = c.execute("SELECT bar_close, MAX(delay_ms) FROM signal_log WHERE timeframe = ? AND bar_close = "
                         "(SELECT MAX(bar_close) FROM signal_log WHERE timeframe = ?) AND strategy NOT GLOB 'NL[0-9]*'",
                         (tf, tf)).fetchone()
        out.append({"tf": tf, "bar_close": r[0], "max_delay_ms": r[1],
                    "limit_ms": SIGNAL_LIMITS["max_delay_ms_5m"] if tf == REEL_TF else SIGNAL_LIMITS["max_delay_ms"],
                    "last_bar_close": last[0] if last else None, "last_delay_ms": last[1] if last else None})
    return out


TG_SENDS_FILE = "tgsends.db"    # the Telegram send counter's own file next to paper3.db (no Telegram sender writes
                                # into the trading database)


def telegram_counts(c, now_ms: int, sends_db: Optional[str] = None) -> Optional[dict]:
    """{"today", "week"}: messages sent to Telegram, from a ``tg_sends(day, kind, n)`` table (KST days 'YYYY-MM-DD',
    written by the senders): in paper3.db (``c``) or in its own file ``sends_db`` (tgsends.db next to paper3.db);
    None while no sender keeps that count."""
    kst = datetime.timezone(datetime.timedelta(hours=9))
    day = datetime.datetime.fromtimestamp(now_ms / 1000, kst).date()
    week0 = (day - datetime.timedelta(days=6)).isoformat()

    def count(conn) -> Optional[dict]:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tg_sends'").fetchone():
            return None
        today = conn.execute("SELECT COALESCE(SUM(n), 0) FROM tg_sends WHERE day = ?", (day.isoformat(),)).fetchone()[0]
        week = conn.execute("SELECT COALESCE(SUM(n), 0) FROM tg_sends WHERE day >= ? AND day <= ?",
                            (week0, day.isoformat())).fetchone()[0]
        return {"today": int(today or 0), "week": int(week or 0)}
    v = count(c)
    if v is None and sends_db and os.path.exists(sends_db):
        try:
            with contextlib.closing(sqlite3.connect(_ro_uri(sends_db), uri=True, timeout=2)) as t:
                v = count(t)
        except sqlite3.Error:
            v = None
    return v


def server_facts(data: "Data", agents_db: Optional[str], daily_db: Optional[str], now_ms: Optional[int] = None) -> dict:
    """/api/v4/server: CPU, memory, the data disk, the database sizes, the signal time per timeframe and the
    Telegram count. A part that cannot be read is None ('수집 전' on the page), never a made-up number."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    out: dict = {"now": now, "cpu": cpu_facts(), "mem": mem_facts(),
                 "disk": disk_facts(os.path.dirname(os.path.abspath(data.db))),
                 "db": db_facts(data.db, agents_db, daily_db, now), "signal_time": [], "telegram": None,
                 "services": None, "limits": dict(SIGNAL_LIMITS)}
    try:
        with contextlib.closing(data.conn()) as c:
            out["signal_time"] = signal_time(c, now)
            out["telegram"] = telegram_counts(c, now, os.path.join(os.path.dirname(os.path.abspath(data.db)),
                                                                   TG_SENDS_FILE))
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
    return out


# ---------------------------------------------------------------- agent rooms
# Content-Security-Policy on every answer (#88): scripts only from this server (no inline script: login.html loads
# /static/login.js), no plug-ins, never inside another site's frame. Inline style attributes stay allowed (the screens
# build markup with style="..."); the one outside host is Google Fonts (v4/index.html: the page keeps working with
# system fonts when it is blocked). data: covers the sound button's SVG mask and canvas snapshots; blob: the chart
# library's images. connect-src 'self' covers /api/* and the /api/stream event stream. frame-src: the v4 chart
# screen's TradingView chart iframe (the widget page and the host it moves to); no other site may be framed.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' data: https://fonts.gstatic.com; img-src 'self' data: blob:; media-src 'self' data: blob:; "
       "connect-src 'self'; worker-src 'self' blob:; manifest-src 'self'; "
       "frame-src https://s.tradingview.com https://www.tradingview-widget.com; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")
# the old dashboard at /v3 ('예전 화면') reads Binance's public WebSockets (wss://fstream.binance.com: live prices,
# candles, order book) and embeds the TradingView chart (s3.tradingview.com/tv.js) straight from the browser; the
# strict policy above would cut all of them off. Its page keeps the header it had before #88 (a CSP applies per page:
# the v4 page, the login page and every API answer keep the strict one).
CSP_V3 = "frame-ancestors 'none'"
V3_PAGES = ("/v3", "/static/index.html")
PUBLIC_PATHS = ("/login", "/api/login", "/static/login.html", "/static/login.css", "/static/login.js",
                # the phone home-screen shortcut: a browser fetches these without the login cookie (no data in them)
                "/static/manifest.json", "/static/icon.svg", "/static/icon-192.png", "/static/icon-512.png",
                "/static/apple-touch-icon.png")
# every kline interval Binance futures serves: the bot chart may show any of them (the accounts trade 15m-4h only)
CANDLE_INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M")
TICK_EVERY_MS = 15 * 60_000  # the agents timer (deploy/paperbot-agents.timer)
SAY_MAX_CHARS = 1_000        # one owner post (rooms_db.MAX_OWNER_TEXT)
SAY_PER_HOUR = 20            # owner posts per hour, both owners together (counted in inbox.db)
AUTHOR_MAX = 20
BODY_MAX = 16_384            # bytes of one owner write (a 1,000-character post is at most ~4 KB of JSON)
BUDGET_CLASSES = ("incident", "owner", "loss", "scheduled", "weekly", "research")
CLASS_KO = {"incident": "사고 점검", "owner": "두 분 글", "loss": "손실·파산 복기", "scheduled": "정기 회의",
            "weekly": "주간 검토", "research": "새 매매법 연구",
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


def _trigger_defaults(hours: Optional[dict] = None) -> dict:
    """Numbers for the 'when does this room meet' line: the hours the agents tick last used (``hours``, its
    cursor 'policy:hours': AGENTS_*_HOUR live in agents.env, which the dashboard does not read), else the
    server's defaults."""
    d = {"loss_min_count": 2, "loss_min_gap_ms": 2 * 3_600_000, "weekly_min_trades": 30,
         "checkpoint_every_days": 30, "morning_hour_kst": 8, "evening_hour_kst": 22,
         "ranking_hour_kst": 14, "tf_split_hour_kst": 18, "weekly_report_hour_kst": 21,
         "bull_bear_hour_kst": 12, "event_review_hour_kst": 11, "cost_review_hour_kst": 11,
         "combo_review_hour_kst": 11, "coin_review_hour_kst": 11, "learning_review_hour_kst": 11,
         "rr_review_hour_kst": 11, "risk_review_hour_kst": 11}
    try:
        from ..agents.triggers import TriggerPolicy
        p = TriggerPolicy()
        # TriggerPolicy() leaves the server-only meetings off (-1): keep the server's hours for those
        d.update({k: getattr(p, k) for k in d if hasattr(p, k) and getattr(p, k) is not None
                  and not (k.endswith("_hour_kst") and getattr(p, k) < 0)})
    except Exception:
        pass
    for k, key in (("morning", "morning_hour_kst"), ("ranking", "ranking_hour_kst"), ("tf_split", "tf_split_hour_kst"),
                   ("evening", "evening_hour_kst"), ("weekly_report", "weekly_report_hour_kst"),
                   ("bull_bear", "bull_bear_hour_kst"), ("event_review", "event_review_hour_kst"),
                   ("cost_review", "cost_review_hour_kst"), ("combo_review", "combo_review_hour_kst"),
                   ("coin_review", "coin_review_hour_kst"), ("learning_review", "learning_review_hour_kst"),
                   ("rr_review", "rr_review_hour_kst"), ("risk_review", "risk_review_hour_kst"),
                   ("loss_min_count", "loss_min_count"), ("loss_min_gap_ms", "loss_min_gap_ms")):
        v = (hours or {}).get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            d[key] = v
    return d


def group_role_of_room(room_id: str) -> Optional[str]:
    """The v4 group-specialist role key of a room ('team:ds_structure' -> 'ds_structure'); None for every other room."""
    from .. import groups as G
    key = room_id[len("team:"):] if isinstance(room_id, str) and room_id.startswith("team:") else None
    return key if key in G.ROLE_KO else None


def room_schedule_ko(room_id: str, hours: Optional[dict] = None) -> str:
    """Plain Korean: when the staff of this room meet by themselves (no one has to type)."""
    from ..agents.roster3 import STRATEGY_KO
    key = group_role_of_room(room_id)
    if key is not None:     # the five v4 specialist rooms (agents/triggers.py group_loss / group_bust / group_weekly)
        from .. import groups as G
        whose = "5분봉 단타 계좌(비교: 5분봉 동전 3개)" if key == "reel_5m" else f"딥시크 {len(G.role_members(key))}개 정의의 계좌"
        loss = ("손실이 3건 쌓이면(6시간 간격, 하루 2번까지)" if key == "reel_5m"
                else "새 손실이 5건 쌓이면(하루 1번까지)")
        from ..agents.roster3 import GROUP_ROLE_OF_ROOM
        rooms_in_order = list(GROUP_ROLE_OF_ROOM)          # triggers.GROUP_ROOMS: the weekly review day by room order
        wd = WEEKDAY_KO[rooms_in_order.index(room_id) % 7] + "요일" if room_id in rooms_in_order else "주 1회"
        return (f"{G.ROLE_KO[key]}: {whose}에 {loss}, 계좌가 파산하면(하루 1번 묶음), 거래가 30건 더 쌓인 뒤 "
                f"{wd} 주간 검토 때 스스로 회의를 엽니다. 기존 36개 방의 AI 호출은 쓰지 않고 남는 몫만 씁니다.")
    d = _trigger_defaults(hours)
    hh = lambda h: f"{h:02d}:00"  # noqa: E731
    if room_id.startswith("strat:"):
        names = list(STRATEGY_KO)
        s = room_id[len("strat:"):]
        wd = WEEKDAY_KO[names.index(s) % 7] if s in names else "정해진"
        gap_h = int(d["loss_min_gap_ms"] // 3_600_000)
        tf = (f", {len(CORE_TFS)}개 봉 계좌의 성적이 크게 갈리면 {hh(d['tf_split_hour_kst'])} 봉 비교 회의(봉 비교 분석가 참석)로"
              if d["tf_split_hour_kst"] >= 0 else "")
        return (f"새 손실이 {d['loss_min_count']}건 쌓이면 (같은 방은 {gap_h}시간 간격), 계좌가 파산하면, "
                f"거래가 {d['weekly_min_trades']}건 더 쌓인 뒤 {wd}요일 주간 검토 때{tf} 스스로 회의를 엽니다.")
    m, e, c = d["morning_hour_kst"], d["evening_hour_kst"], d["checkpoint_every_days"]
    more = " 자료가 많이 쌓인 주에는 한 번 더(주 2번까지)."

    def weekly(key: str, day: str, what: str) -> str:
        h = d.get(key, -1)
        return f" {day}요일 {hh(h)} {what}(자료가 쌓인 뒤부터).{more}" if isinstance(h, int) and h >= 0 else ""

    bb, ev = d.get("bull_bear_hour_kst", -1), d.get("event_review_hour_kst", -1)
    # the risk team: Tuesday's combination meeting, Friday's drawdown / bust risk meeting (owners' request 2026-10-04)
    risk = weekly("combo_review_hour_kst", "화", "조합·동시 손실 회의") + weekly("risk_review_hour_kst", "금", "낙폭·파산 위험 회의")
    return {
        "team:market": f"매일 {m:02d}:00 아침 회의: 장세 → 파생·쏠림 → 전략가 → 반론 → 팀장 요약(텔레그램 발송). "
                       + (f"매일 {hh(bb)} 낙관·비관 토론(코인 하나씩, 24시간 뒤 코드가 채점, 거래 없음). " if bb >= 0 else "")
                       + (f"미국 경제지표 발표 다음 날 {hh(ev)} 경제지표 복기. " if ev >= 0 else "")
                       + "시세가 크게 움직이면 바로 회의.",
        "team:review": (f"매일 {hh(d['ranking_hour_kst'])} 순위 검토(성과 분석 → 손익 복기 → 리스크 → 팀장, 텔레그램 발송), "
                        if d["ranking_hour_kst"] >= 0 else "매일 ")
                       + f"{e:02d}:00 저녁 점검: 손익 복기 → 가정 분석 → 리스크 책임자."
                       + weekly("coin_review_hour_kst", "수", "코인·장세 회의")
                       + weekly("rr_review_hour_kst", "목", "손익비·청산 회의"),
        "team:lead": f"매일 {e:02d}:00 팀장 3줄 요약(텔레그램 발송), {c}·{2 * c}·{3 * c}일째 중간 점검."
                     + weekly("learning_review_hour_kst", "토", "학습 정리 회의"),
        "team:ops": "사고가 나면 바로: 강제청산, 밤 점검 불일치, 데이터 끊김, 신호 지연."
                    + weekly("cost_review_hour_kst", "월", "비용·체결 회의"),
        "team:risk": ((risk.strip() + " 그 밖에는 두 분 글에 답합니다.") if risk
                      else "정해진 회의는 없고, 두 분이 남긴 메시지에 답합니다."),
    }.get(room_id, "")


# ------------------------------------------------ meeting room view (/api/office): read-only, from agents3.db
OFFICE_TTL_S = 4             # /api/office reused this long (the page polls every few seconds while it is open)
OFFICE_RECENT = 6            # finished meetings of today shown under the office
OFFICE_LINE = 90             # characters of a speech bubble (the first sentence of the real message)
OFFICE_SPEAKING = ("analysis", "challenge", "expert", "revision", "verdict", "summary")   # = digest.SPEAKING
OFFICE_STRATEGY_EXPERTS = ("entry_timing", "exit_timing", "whatif")                       # = rooms.STRATEGY_EXPERTS
# the daily meetings the hours in 'policy:hours' stand for: (hour key of _trigger_defaults, trigger, rooms, where)
OFFICE_DAILY = (("morning_hour_kst", "morning", ("team:market",), "시장분석팀"),
                ("bull_bear_hour_kst", "bull_bear", ("team:market",), "시장분석팀"),
                ("ranking_hour_kst", "ranking", ("team:review",), "손익 복기팀"),
                ("tf_split_hour_kst", "tf_split", (), "성적이 갈린 매매법 방"),
                ("evening_hour_kst", "evening", ("team:review", "team:lead"), "손익 복기팀 → 총괄"))
KST_TZ = datetime.timezone(datetime.timedelta(hours=9))


def _trigger_ko() -> dict:
    try:
        from ..agents.rooms import TRIGGER_KO
        return dict(TRIGGER_KO)
    except Exception:  # the engine is optional for the dashboard
        return {"morning": "아침 회의", "evening": "저녁 점검", "ranking": "순위 검토", "tf_split": "봉 비교 회의"}


def bubble_line(text: str, n: int = OFFICE_LINE) -> str:
    """The first sentence of a room message, for a speech bubble: the first line that is not the
    '↳ 누구에게 동의: …' reply line (that one when it is all there is), list marks dropped, cut at the
    first sentence end and at ``n`` characters. Only ever a piece of the real message."""
    import re
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    s = next((ln for ln in lines if not ln.startswith("↳")), lines[0])
    s = re.sub(r"^(?:[-•]|\d+\.)\s+", "", s)
    m = re.match(r"(.+?[.!?。])(?:\s|$)", s)
    if m:
        s = m.group(1)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def office_schedule(now_ms: int, hours: Optional[dict] = None) -> dict:
    """Today's fixed meeting hours (KST) from the hours the agents tick published ('policy:hours', else the
    server defaults) and the next one after ``now_ms``. Only the daily meetings the tick names there; meetings
    that open on their own (losses, incidents, owner posts, the lab) have no hour."""
    d = _trigger_defaults(hours)
    tk = _trigger_ko()
    slots = []
    for key, trig, rooms, where in OFFICE_DAILY:
        h = d.get(key)
        if isinstance(h, int) and not isinstance(h, bool) and 0 <= h <= 23:
            slots.append({"hour": h, "hhmm": f"{h:02d}:00", "trigger": trig, "trigger_ko": tk.get(trig, trig),
                          "room_ids": list(rooms), "where": where})
    slots.sort(key=lambda s: s["hour"])
    now = datetime.datetime.fromtimestamp(now_ms / 1000, tz=KST_TZ)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    nxt = None
    for s in slots:
        if s["hour"] * 60 > now.hour * 60 + now.minute:
            nxt = {**s, "at_ms": int((day0 + datetime.timedelta(hours=s["hour"])).timestamp() * 1000), "tomorrow": False}
            break
    if nxt is None and slots:
        s = slots[0]
        nxt = {**s, "at_ms": int((day0 + datetime.timedelta(days=1, hours=s["hour"])).timestamp() * 1000),
               "tomorrow": True}
    return {"slots": slots, "next": nxt, "source": "tick" if hours else "defaults"}


FIXED_NORMAL_KO = "딥시크·5분봉은 규칙상 늘 보통 배수"
# /api/v4/curves: the steps it answers in (15 minutes, 1 hour, 4 hours, 1 day), its series and its longest answer
CURVE_STEPS = (300_000, 900_000, 3_600_000, 14_400_000, 86_400_000)  # fill-home: 5 min for a run under 2 days
CURVE_KEYS = ("strategy", "ds200", "reel", "random", "random_5m")
CURVE_MAX_POINTS = 2_000
CURVE_SETTLE_MS = 15 * 60_000       # a step is kept once it ended this long ago


def curve_keys(kind: str, timeframe: str) -> tuple:
    """The /api/v4/curves series an original account counts in: its kind, and random_5m for a 5m coin flip."""
    return (kind, "random_5m") if kind == "random" and timeframe == REEL_TF else (kind,)
GZIP_MIN_BYTES = 1024        # responses at least this big are sent gzip-compressed when the browser accepts it
NO_GZIP_PATHS = ("/api/stream", "/api/v4/ticks")   # the live streams (text/event-stream: the board stream and the
                                   # sound's market trades, dash/more/ticks.py) are never compressed: a gzip buffer would
                                   # hold their events back (older Starlette versions compress streams without flushing)


class GZipExceptStream:
    """Starlette's GZipMiddleware for every response except the live stream (G17: /api/board is ~220 KB of JSON)."""

    def __init__(self, app, minimum_size: int = GZIP_MIN_BYTES):
        from starlette.middleware.gzip import GZipMiddleware
        self.app = app
        self.gz = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") not in NO_GZIP_PATHS:
            await self.gz(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def safe_next(path: Optional[str]) -> bool:
    """A login ``next`` this server may send the browser to: a same-origin path ('/...', never '//host', a
    backslash, a control character or the login page itself)."""
    return (isinstance(path, str) and 0 < len(path) <= 2000 and path.startswith("/") and not path.startswith("//")
            and "\\" not in path and not any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
            and not path.startswith("/login") and not path.startswith("/api/"))


def login_redirect(path: str, query: str = "") -> str:
    """'/login?next=<path>' for a page asked without a session (the path and its query string; '/' when unsafe)."""
    nxt = path + (f"?{query}" if query else "")
    return "/login?next=" + urllib.parse.quote(nxt if safe_next(nxt) else "/", safe="/")


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
                 say_per_hour: int = SAY_PER_HOUR, owners: tuple = (), paper_db: Optional[str] = None):
        from ..agents import extra_accounts, rooms_db
        self.R = rooms_db
        self.X = extra_accounts
        self.agents_db = agents_db
        self.inbox_db = inbox_db
        self.paper_db = paper_db            # read-only: the running extra accounts and the runner's state 'extras' 
        self.budget_env = budget_env
        self.say_per_hour = say_per_hour
        self.owners = tuple(owners)
        self._caps: Optional[dict] = None
        self.specs = {s["room_id"]: s for s in rooms_db.room_specs()}
        from ..agents import roster3
        from ..agents.roster3 import ROLES, SPECIALISTS, room_duty
        # the duty a member has in the rooms (what the room staff can really do), not the v3 roster's; the five v4
        # group specialists (DeepSeek families, the reel: roster3.GROUP_SPECIALISTS) are specialists too
        self.roles = {r[0]: {"id": r[0], "name": r[1], "team": r[2], "duty": room_duty(r[0])}
                      for r in ROLES + SPECIALISTS + tuple(getattr(roster3, "GROUP_SPECIALISTS", ()))}

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
            ai = self._ai_failing(a)
            hours = self.hours(a)
            waits, per_day = self._owner_waits(a, int(time.time() * 1000) if now_ms is None else now_ms)
        out = []
        for rid, spec in self.specs.items():
            r = {"room_id": rid, "kind": spec["kind"], "strategy": spec["strategy"], "title": spec["title"],
                 "members": spec["members"], "last_id": 0, "last_ts": None, "last_kind": None, "last_role": None,
                 "last_speaker": None, "last_text": "", "rounds_today": 0, "open_proposals": 0, "running": False}
            r.update({k: v for k, v in rows.pop(rid, {}).items() if v is not None or k not in r})
            r["schedule_ko"] = room_schedule_ko(rid, hours)
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
                "last_tick": last_tick, "ai": ai, "tick_every_ms": TICK_EVERY_MS, "rounds_per_room_day": per_day,
                "max_id": max((int(r.get("last_id") or 0) for r in out), default=0), "rooms": out,
                # the meeting hours the schedule lines use (the tick's 'policy:hours', else the server defaults)
                "hours": _trigger_defaults(hours)}

    @staticmethod
    def _ai_failing(a: Optional[sqlite3.Connection]) -> Optional[dict]:
        """The staff's meetings that failed in a row because no AI call was answered: {failed: how many, since: the
        oldest one's start}, none when a call was answered since (the streak of the tick's own WARN,
        rooms.check_runner_down). When every call fails (a revoked or expired Claude login, no route to Claude) the
        tick still runs and its sign of life stays OK, and such a call leaves no agent_calls row (nothing ran); the
        page says the staff stopped from this (rooms.js agentsState)."""
        if a is None:
            return None
        try:
            from ..agents.rooms import down_streak
            n, since, _ = down_streak(a)
            if since is not None and a.execute("SELECT 1 FROM agent_calls WHERE ok = 1 AND ts >= ? LIMIT 1",
                                               (since,)).fetchone():
                n, since = 0, None
        except (sqlite3.Error, ImportError):        # no rounds table yet; the engine is optional for the dashboard
            return None
        return {"failed": int(n), "since": since}

    def hours(self, a: Optional[sqlite3.Connection] = None) -> Optional[dict]:
        """The meeting hours the agents tick last used (rooms.HOURS_CURSOR), None before its first pass."""
        if a is None:
            with self.ro(self.agents_db) as c:
                return self._cursor_obj(c, "policy:hours")
        return self._cursor_obj(a, "policy:hours")

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
        spec["schedule_ko"] = room_schedule_ko(room_id, self.hours())
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
            from ..agents import packets3
            from ..agents.scorecard import scorecard
            out = {"counts": self.R.trial_counts(a, strategy), "research": packets3.research_counts(strategy),
                   "scorecard": scorecard(a, strategy),
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

    def runtime(self) -> tuple[Optional[list], Optional[dict]]:
        """(running extras, the runner's state 'extras') from paper3.db read-only, in one read; (None, None)
        when it cannot be read."""
        with self.ro(self.paper_db) as pc:
            return self.X.snapshot(pc)

    def _running(self, a: Optional[sqlite3.Connection], p: dict, extras: Optional[list],
                 xstate: Optional[dict]) -> Optional[dict]:
        """{account_id, created_ts, extra_status} of the account this proposal row started (exact source match)."""
        if extras is None or a is None:
            return None
        t = self.R.get_trial(a, int(p["trial_id"])) if p.get("trial_id") else None
        e = self.X.account_of_proposal(None, p, t, extras)
        if e is None:
            return None
        return {"account_id": e["account_id"], "created_ts": e["created_ts"], "label_ko": self.X.label_of(e),
                "extra_status": self.X.extra_status(xstate, e["account_id"])}

    def orphans(self) -> dict:
        """{account id: {...}}: running extras whose proposal is missing or not approved (the tick's cursor)."""
        with self.ro(self.agents_db) as a:
            return self._cursor_obj(a, self.X.ORPHANS) or {}

    def proposals(self, status: Optional[str] = None, strategy: Optional[str] = None,
                  room_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        from ..agents.roster3 import STRATEGY_KO
        decs = self._decisions()
        extras, xstate = self.runtime()
        with self.ro(self.agents_db) as a:
            rows = self.R.list_proposals(a, status, strategy, room_id, limit)
            upto = self._cursor(a, "inbox:approvals")
            now = self._gate_now(a)
            for p in rows:
                p["account_running"] = self._running(a, p, extras, xstate)
        for p in rows:
            dec = decs.get(int(p["id"]))
            eff, applied = self._effective(p, dec, upto)
            p["gate_now"] = now.get(str(p["id"]))
            p["strategy_ko"] = STRATEGY_KO.get(p.get("strategy") or "", p.get("strategy"))
            p["owner_decision"] = None if dec is None else {
                "decision": dec["decision"], "ts": dec["ts"], "note": dec.get("note"), "applied": applied}
            p["effective_status"] = eff
            p["kind"] = self.X.proposal_kind(p)
            p["account"] = self.X.proposal_account(p)
            p["runtime_refusal"] = self.X.refusal_of(xstate, p)
            p["runtime_ready"] = xstate is not None
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

    # -- the meeting room view (/api/office)
    def _role(self, role: str) -> dict:
        """{name, short name, team} of a room member; a specialist is named after its strategy, a v4 group
        specialist (spec_<key>, groups.V4_ROLES) after its role ('구조·유동성 담당'), with ``group_role`` = key."""
        from .. import groups as G
        from ..agents.roster3 import STRATEGY_KO
        if role.startswith("spec_"):
            s = role[len("spec_"):]
            if s in G.ROLE_KO:
                return {"name": self.R.role_name(role), "label": G.ROLE_KO[s], "team": "specialist", "group_role": s}
            return {"name": self.R.role_name(role), "label": STRATEGY_KO.get(s, s), "team": "specialist"}
        r = self.roles.get(role)
        return {"name": r["name"] if r else self.R.role_name(role), "label": None, "team": r["team"] if r else ""}

    @staticmethod
    def _consumed(msgs: list[dict]) -> list[str]:
        """The turns of a meeting so far, in order: a role that spoke, or whose turn code skipped (the room's
        notice '… 차례를 건너뜁니다' / '이번 차례는 건너뜁니다', data.role)."""
        out = []
        for m in msgs:
            if m["kind"] in OFFICE_SPEAKING and m["role"] not in ("code", "system", "owner"):
                out.append(m["role"])
            elif m["role"] == "code" and m["kind"] == "system" and "건너뜁니다" in (m["text"] or ""):
                d = m.get("_data")
                if isinstance(d, dict) and isinstance(d.get("role"), str):
                    out.append(d["role"])
        return out

    def _expected(self, room_id: str, trigger: str, data: Any, msgs: list[dict]) -> tuple[Optional[str], list[str]]:
        """(the role whose turn comes next when the meeting's own order says so, else None; the meeting's
        planned roles in order, as far as they are known). Same order as the agents' code (rooms.team_plan,
        rooms._strategy_round), read only: a turn that depends on an answer still to come is not guessed."""
        done = self._consumed(msgs)
        if room_id.startswith("strat:"):
            spec = "spec_" + room_id[len("strat:"):]
            plan = [spec, "devils_advocate"]
            if not done:
                return spec, plan
            if done == [spec]:
                return "devils_advocate", plan
            if len(done) == 3 and done[:2] == plan and done[2] in OFFICE_STRATEGY_EXPERTS:
                return spec, plan + [done[2]]          # the specialist's final answer after the expert
            return None, plan            # after the challenge: an expert, or the end (it depends on the answers)
        try:
            from ..agents import rooms as RM
            from ..agents import triggers as TR
            plan = [r for r, _ in RM.team_plan(TR.Due(room_id, trigger, 0, data if isinstance(data, dict) else {},
                                                      trigger))]
        except Exception:  # the engine is optional for the dashboard; a newer plan shape: no guess
            return None, []
        ptr = 0
        for r in done:
            if r not in plan[ptr:]:
                return None, plan            # e.g. a staff member the owners named (@) answered first
            ptr = plan.index(r, ptr) + 1
        if trigger == "research" and ptr == 1:
            return None, plan                # the lab's skeptic speaks only when a proposed spec is new
        return (plan[ptr] if ptr < len(plan) else None), plan

    def _round_msgs(self, a: sqlite3.Connection, room_id: str, round_id: int, limit: int = 80) -> list[dict]:
        rows = self.R._dicts(a.execute(
            "SELECT id, ts, role, kind, text, data FROM messages WHERE room_id = ? AND round_id = ? "
            "ORDER BY id DESC LIMIT ?", (room_id, round_id, limit)))[::-1]
        for m in rows:
            m["_data"] = self.R._loads(m.pop("data")) if m["role"] == "code" or m["kind"] in OFFICE_SPEAKING else None
        return rows

    def _meeting_now(self, a: sqlite3.Connection, r: dict, tk: dict) -> dict:
        from ..agents.roster3 import STRATEGY_KO
        rid = r["room_id"]
        td = self.R._loads(r["trigger_data"]) or {}
        msgs = self._round_msgs(a, rid, int(r["round_id"]))
        turns, lines = [], {}
        for m in msgs:
            if m["kind"] in OFFICE_SPEAKING and m["role"] not in ("code", "system", "owner"):
                t = {"role": m["role"], "kind": m["kind"], "ts": m["ts"], "line": bubble_line(m["text"])}
                turns.append(t)
                lines[m["role"]] = t
        try:
            nxt, plan = self._expected(rid, r["trigger"], td, msgs)
        except Exception:  # a turn order this code does not know: no guess
            nxt, plan = None, []
        last = msgs[-1] if msgs else None
        code = None
        if last is not None and last["role"] == "code" and last["kind"] in ("code_result", "system", "action") and (
                not turns or last["ts"] >= turns[-1]["ts"]):
            code = {"kind": last["kind"], "ts": last["ts"], "line": bubble_line(last["text"])}
        people = list(dict.fromkeys([*plan, *(t["role"] for t in turns), *([nxt] if nxt else [])]))
        strat = self.R.room_strategy(rid)
        spec = self.specs.get(rid) or {}
        return {"round_id": int(r["round_id"]), "room_id": rid, "kind": spec.get("kind") or (
                    "strategy" if strat else "team"),
                "title": spec.get("title") or STRATEGY_KO.get(strat or "", rid), "strategy": strat,
                "trigger": r["trigger"], "trigger_ko": tk.get(r["trigger"], r["trigger"]),
                "why": bubble_line(td.get("summary_ko") if isinstance(td, dict) else "", 120),
                "started_ts": r["started_ts"], "turns": turns[-20:], "lines": lines,
                "last_role": turns[-1]["role"] if turns else None, "next_role": nxt, "participants": people,
                "code": code}

    def office(self, now_ms: Optional[int] = None) -> dict:
        """The meeting room view: meetings running now (who spoke, in order, the first sentence of each one's
        latest message, whose turn comes next when the order says so), today's finished meetings with their
        decision line, the latest strategy-room meetings, today's counts and the fixed meeting hours.
        agents3.db read-only; bounded queries (index on rounds.status and on messages (room_id, id))."""
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        day0 = self.R.kst_day_start_ms(now)
        tk = _trigger_ko()
        # every team room, the five v4 group-specialist rooms (team:<key>, groups.V4_ROLES) among them, marked
        zones = [{"room_id": rid, "title": s["title"], "members": list(s["members"]),
                  "group_role": group_role_of_room(rid)}
                 for rid, s in self.specs.items() if s["kind"] == "team"]
        out: dict = {"ready": False, "now": now, "day": self.R.kst_day(now), "zones": zones,
                     "strategy_members": list(self.R.STRATEGY_ROOM_ROLES), "running": [], "recent": [],
                     "latest_strategy": [], "today": {"meetings": 0, "ai_calls": 0, "by_room": {}}}
        with self.ro(self.agents_db) as a:
            hours = self.hours(a)
            out["schedule"] = office_schedule(now, hours)
            if a is not None:
                out["ready"] = True
                try:
                    if a.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rounds'").fetchone():
                        self._office_read(a, now, day0, tk, out)
                except (sqlite3.Error, TypeError, ValueError) as exc:
                    out["error"] = f"agents3.db를 읽지 못함: {type(exc).__name__}"
        used = {m for z in zones for m in z["members"]} | set(out["strategy_members"])
        for x in out["running"]:
            used.update(x["participants"])
            used.update(x["lines"])
        for x in out["recent"]:
            used.update(x["speakers"])
        out["roles"] = {r: self._role(r) for r in sorted(used)}
        return out

    def _office_read(self, a: sqlite3.Connection, now: int, day0: int, tk: dict, out: dict) -> None:
        from ..agents.roster3 import STRATEGY_KO
        running = self.R._dicts(a.execute(
            "SELECT round_id, room_id, trigger, trigger_data, started_ts FROM rounds WHERE status = 'running' "
            "AND started_ts >= ? ORDER BY round_id DESC LIMIT 4", (now - self.R.RUNNING_FRESH_MS,)))
        out["running"] = [self._meeting_now(a, r, tk) for r in running[::-1]]
        by_room = {str(k): int(n) for k, n in a.execute(
            "SELECT room_id, COUNT(*) FROM rounds WHERE started_ts >= ? GROUP BY room_id", (day0,))}
        out["today"] = {"meetings": sum(by_room.values()), "ai_calls": int(self.R.usage_today(a, now)["calls"]),
                        "by_room": by_room}
        for r in self.R._dicts(a.execute(
                "SELECT round_id, room_id, trigger, started_ts, ended_ts, status, decision, calls FROM rounds "
                "WHERE started_ts >= ? AND status != 'running' ORDER BY round_id DESC LIMIT ?", (day0, OFFICE_RECENT))):
            dec = self.R._loads(r["decision"])
            speakers = list(dict.fromkeys(x[0] for x in a.execute(
                "SELECT role FROM messages WHERE room_id = ? AND round_id = ? AND kind IN (%s) "
                "AND role NOT IN ('code', 'system', 'owner') ORDER BY id LIMIT 40" % ",".join("?" * len(OFFICE_SPEAKING)),
                (r["room_id"], r["round_id"], *OFFICE_SPEAKING))))
            strat = self.R.room_strategy(r["room_id"])
            out["recent"].append({
                "round_id": int(r["round_id"]), "room_id": r["room_id"], "strategy": strat,
                "title": (self.specs.get(r["room_id"]) or {}).get("title") or STRATEGY_KO.get(strat or "", r["room_id"]),
                "trigger": r["trigger"], "trigger_ko": tk.get(r["trigger"], r["trigger"]), "status": r["status"],
                "started_ts": r["started_ts"], "ended_ts": r["ended_ts"], "calls": int(r["calls"] or 0),
                "decision": bubble_line((dec or {}).get("summary_ko", "") if isinstance(dec, dict) else "", 140),
                "speakers": speakers})
        for r in self.R._dicts(a.execute(
                "SELECT round_id, room_id, trigger, started_ts, ended_ts, status FROM rounds "
                "WHERE room_id LIKE 'strat:%' ORDER BY round_id DESC LIMIT 3")):
            strat = self.R.room_strategy(r["room_id"])
            out["latest_strategy"].append({
                "round_id": int(r["round_id"]), "room_id": r["room_id"], "strategy": strat,
                "title": STRATEGY_KO.get(strat or "", r["room_id"]), "trigger": r["trigger"],
                "trigger_ko": tk.get(r["trigger"], r["trigger"]), "status": r["status"],
                "started_ts": r["started_ts"], "ended_ts": r["ended_ts"]})

    # -- write side (inbox.db only)
    def ensure_inbox(self) -> None:
        """Create an empty inbox.db at the dashboard's start when there is none yet. The live runner reads it at
        every activation (the sticky reject and the owners' clicks): a missing file refuses every new extra account,
        including a copy the autonomous approver may approve alone after day 60. Never raises."""
        if not self.inbox_db or os.path.exists(self.inbox_db):
            return
        if not os.path.isdir(os.path.dirname(os.path.abspath(self.inbox_db))):
            return
        try:
            self.R.open_inbox_rw(self.inbox_db).close()
        except Exception as exc:  # noqa: BLE001  the first owner write creates it again
            print(f"inbox.db not created at start: {type(exc).__name__}: {exc}", file=sys.stderr)

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

    # -- price alerts (inbox.db; the Telegram sender paperbot/tradealerts.py fires them)
    def price_alerts(self, now_ms: Optional[int] = None) -> dict:
        """Alerts not deleted, with their state from the sender's price_alerts.json (next to inbox.db): armed /
        fired (when), the last price it saw, and whether the sender is running (heartbeat within 2 minutes)."""
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        with self.ro(self.inbox_db) as ib:
            alerts = self.R.price_alerts(ib)
        st: dict = {}
        if self.inbox_db:
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(self.inbox_db)), "price_alerts.json"),
                          encoding="utf-8") as fh:
                    st = json.load(fh) or {}
            except (OSError, ValueError):
                st = {}
        fired = st.get("fired") or {}
        for a in alerts:
            f = int(fired.get(str(a["id"]), 0) or 0)
            a["fired_ts"] = f if f >= a["armed_ts"] else None
            a["armed"] = a["fired_ts"] is None
        hb = int(st.get("hb") or 0)
        return {"alerts": alerts, "sender_alive": bool(hb) and now_ms - hb <= 120_000, "sender_hb": hb or None,
                "max": self.R.MAX_PRICE_ALERTS}

    def add_price_alert(self, symbol: str, direction: str, price: float, note: str, author: str) -> dict:
        c = self._inbox()
        try:
            aid = self.R.add_price_alert(c, symbol, direction, price, note, author)
        except ValueError as exc:
            raise HTTPException(400, "알림을 저장하지 못했습니다: " + ("50개까지만 걸 수 있습니다" if "at most" in str(exc)
                                                                 else "가격·방향을 확인해 주세요"))
        finally:
            c.close()
        return {"ok": True, "id": aid}

    def change_price_alert(self, alert_id: int, action: str) -> dict:
        if not any(a["id"] == int(alert_id) for a in self.price_alerts()["alerts"]):
            raise HTTPException(404, "그런 알림이 없습니다")
        c = self._inbox()
        try:
            self.R.change_price_alert(c, int(alert_id), action)
        finally:
            c.close()
        return {"ok": True}

    def decide(self, proposal_id: int, decision: str, note: str, author: str) -> dict:
        if not 0 < int(proposal_id) < 2 ** 63:          # beyond SQLite's integers: no such proposal
            raise HTTPException(404, "그런 제안이 없습니다")
        extras, xstate = self.runtime()
        with self.ro(self.agents_db) as a:
            p = self.R.get_proposal(a, proposal_id)
            upto = self._cursor(a, "inbox:approvals")
            now = self._gate_now(a).get(str(proposal_id))
            running = self._running(a, p, extras, xstate) if p is not None else None
        if p is None:
            raise HTTPException(404, "그런 제안이 없습니다")
        dec = self._decisions().get(int(proposal_id))
        eff, _ = self._effective(p, dec, upto)
        gate_ok = isinstance(p.get("gate"), dict) and p["gate"].get("pass") is True
        refusal = self.X.refusal_of(xstate, p)
        if decision == "approve":
            if not gate_ok:
                raise HTTPException(409, "코드 관문을 통과하지 못한 제안은 누구도 승인할 수 없습니다")
            if isinstance(now, dict) and now.get("pass") is False:
                raise HTTPException(409, "시험을 더 해서, 지금 기준으로 다시 판정하면 코드 관문을 "
                                         "통과하지 못합니다. 승인할 수 없습니다")
            # one more click on an approved proposal: given before the runner's extra-account feature started
            # (stale_ok), or the deciding owner's click is no longer in inbox.db (owner_click_missing)
            again = (p["status"] == "approved" and running is None and isinstance(refusal, dict)
                     and refusal.get("code") in self.X.RE_APPROVE)
            if dec is not None and dec.get("rejected_before"):
                raise HTTPException(409, f"이 제안은 지금 승인할 수 없는 상태입니다 ({PSTATUS_KO.get(eff, eff)})")
            if eff != "awaiting_owner" and not again:
                raise HTTPException(409, f"이 제안은 지금 승인할 수 없는 상태입니다 ({PSTATUS_KO.get(eff, eff)})")
        elif eff not in ("awaiting_owner", "approved"):
            raise HTTPException(409, f"이 제안은 지금 거절할 수 없는 상태입니다 ({PSTATUS_KO.get(eff, eff)})")
        elif running is not None:
            raise HTTPException(409, f"이미 시작된 계좌입니다 ({running['account_id']}). 시작된 계좌는 거절로 멈출 수 "
                                     "없습니다(계좌는 규칙대로 계속 돕니다)")
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


# the paper v4 run's rules in one line (docs/paper-v4-rules.md), the banner on every view (summary.js)
RULES_V4_KO = ("기존 36 · 딥시크 44 · 5분봉 단타 1 · 동전 봇 · 좋은 자리 50/40배, 보통 30/20배(딥시크·5분봉은 늘 보통), "
               "비중=배수% · 5분봉 단타는 자체 청산(스윙 저점 손절·볼린저 윗선 익절·8시간) · 1분봉 8초 뒤 읽기")
RULES_V4_LABEL = "v4 규칙"
# documents the dashboard serves read-only as text (GET /api/doc/<name>); nothing else under docs/
DOCS = {"rules-change-1": "paper-v3-rules-change-1.md", "levrule-eval": "levrule-eval.md",
        "rules-v4": "paper-v4-rules.md", "verdict-v4": "paper-v4-verdict.md", "levrule-eval-v4": "levrule-eval-v4.md",
        "tradingagents-limits": "tradingagents-limits.md"}       # #88 A11: linked from the FAQ
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs")
DOC_MAX_BYTES = 200_000


def _doc_link(name: str, fallback: str) -> str:
    """/api/doc/<name> when that document is in docs/ (the v4 documents land with the restart), else the fallback's."""
    return f"/api/doc/{name if os.path.isfile(os.path.join(DOCS_DIR, DOCS[name])) else fallback}"


def verdict_method() -> dict:
    """How the day-30 verdict judges (checkpoint.N_BOTS same-bar coin flips, the per-group error budget
    checkpoint.FAMILY_ALPHA, owners' D5), as numbers and one Korean line ``method_ko`` (never typed in here)."""
    from .. import checkpoint as CP
    n = int(getattr(CP, "N_BOTS", 0) or 0)
    alpha = dict(getattr(CP, "FAMILY_ALPHA", {}) or {})
    # the one method text (G18): checkpoint.method_ko, the same line the agents' facts and Obsidian read
    return {"method_ko": CP.method_ko(None, n), "n_bots": n, "family_alpha": alpha}


def restart_banner(start_ts: Optional[int], now_ms: int, ledger: Optional[dict] = None, day_state=None) -> dict:
    """'새 실험 D+n / 30 · 첫 판정 MM/DD' of the run started at ``start_ts`` (checkpoint.run_facts): n = whole days
    since 00:00 UTC of the start day (the checkpoint clock: day 30 is the first verdict, checkpoint_ts), the verdict
    date in KST (09:00). The checkpoint named is the verdict-day clock's (dash/more/verdictday.py; ``ledger`` =
    read_ledger(checkpoint.db)): a checkpoint that has passed stays named ('판정 결과 기다림') until its verdict is
    stored; only then the next one, and ``of`` becomes its day (60, 90, ...). Without a ledger a passed checkpoint reads
    as not known, never as the next one. ``line_ko`` / ``chip_ko``: the one sentence every screen uses (change 13)."""
    from ..checkpoint import PERIOD_DAYS
    from .more.verdictday import clock
    out: dict = {"rules_ko": RULES_V4_KO, "rules_label": RULES_V4_LABEL, **verdict_method(),
                 "doc": _doc_link("rules-v4", "rules-change-1"),
                 "verdict_doc": _doc_link("verdict-v4", "rules-change-1"),
                 "levrule_doc": _doc_link("levrule-eval-v4", "levrule-eval")}
    if start_ts is None:
        return {**out, "ready": False, "text": "새 실험: 봇이 아직 첫 계좌를 만들지 않았습니다"}
    c = clock(int(start_ts), int(now_ms), ledger, day_state)
    n, k, cp, mmdd = c["n"], c["k"], c["ts"], c["mmdd"]
    if c["state"] == "ended":
        text = f"새 실험 D+{n} · 판정 끝"
    elif c["due"]:
        text = f"새 실험 D+{n} · {c['day']}일 판정 결과 기다림"
    elif k == 1:
        text = f"새 실험 D+{n} / {PERIOD_DAYS} · 첫 판정 {mmdd}"
    else:
        text = f"새 실험 D+{n} · {k}번째 판정 {mmdd}"
    return {**out, "ready": True, "day": n, "of": c["of"], "checkpoint": k, "verdict_ts": cp, "verdict_mmdd": mmdd,
            "text": text, "due": c["due"], "state": c["state"], "line_ko": c["line_ko"], "chip_ko": c["chip_ko"]}


def create_app(db: str, password_hash: Optional[str], secret: bytes, candles=fetch_candles, ticker=fetch_ticker,
               depth=fetch_depth, market=fetch_market,
               agents_db: Optional[str] = None, daily_db: Optional[str] = None, frames=fetch_frame,
               inbox_db: Optional[str] = None, say_per_hour: int = SAY_PER_HOUR,
               checkpoint_db: Optional[str] = None, debate_db: Optional[str] = None,
               failalert_dir: Optional[str] = None) -> FastAPI:
    # checkpoint verdicts (paperbot/checkpoint.py): by default checkpoint.db next to paper3.db, read-only
    checkpoint_db = checkpoint_db or os.path.join(os.path.dirname(os.path.abspath(db)), "checkpoint.db")
    # the 24-hour debate room (dash/analysis.py debate): by default debate/debate.db next to paper3.db, read-only
    debate_db = debate_db or os.path.join(os.path.dirname(os.path.abspath(db)), "debate", "debate.db")
    if inbox_db and any(other and same_file(inbox_db, other) for other in (db, daily_db, agents_db)):
        # the dashboard creates its tables in inbox.db: never in another process's database
        raise ValueError("--inbox-db must be its own file (not paper3.db, daily3.db or agents3.db)")
    warm_imports()
    app = FastAPI(title="paper v4", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipExceptStream, minimum_size=GZIP_MIN_BYTES)
    data = Data(db, daily_db, checkpoint_db)
    rooms = Rooms(agents_db, inbox_db, os.environ.get("AGENTS_BUDGET"), say_per_hour,
                  owner_names(os.environ.get("DASH_OWNERS")), paper_db=db)
    rooms.ensure_inbox()
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
            # back to the same page after logging in (login.html follows ?next=, same-origin paths only)
            return RedirectResponse(login_redirect(path, req.url.query))
        resp = await call_next(req)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.middleware("http")
    async def guard(req: Request, call_next):
        resp = await _guarded(req, call_next)
        # never inside another site's frame (the approve / reject buttons, the login form)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = CSP_V3 if req.url.path in V3_PAGES else CSP
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
        """The paper v4 dashboard (static/v4/index.html; its files load from /static/v4/)."""
        return FileResponse(V4_INDEX)

    @app.get("/v4")
    def index_v4():
        return FileResponse(V4_INDEX)

    @app.get("/v3")
    def index_v3():
        """The old dashboard ('예전 화면' in the v4 menu): same login, same data."""
        return FileResponse(OLD_INDEX)

    @app.get("/api/board")
    def board():
        b = data.board()
        # running extras whose proposal is missing or no longer approved (the agents tick flags them)
        orph = rooms.orphans() if any(r.get("kind") in ("copy", "newlab") for r in b["accounts"]) else {}
        rows = [{**r, "orphan": r["account_id"] in orph if r.get("kind") in ("copy", "newlab") else None}
                for r in b["accounts"]]           # (copies: the board is shared with the other callers)
        return {**b, "accounts": rows}

    @app.get("/api/account/{aid}")
    def account(aid: str):
        try:
            return data.account(aid)
        except KeyError:
            raise HTTPException(404, "no such account")

    @app.get("/api/status")
    def status():
        return data.status()

    @app.get("/api/doc/{name}")
    def doc_text(name: str):
        """A rules document as plain text, read-only (only the names in DOCS)."""
        from fastapi.responses import PlainTextResponse
        fn = DOCS.get(name)
        if fn is None:
            raise HTTPException(404, "no such document")
        try:
            with open(os.path.join(DOCS_DIR, fn), "rb") as fh:
                raw = fh.read(DOC_MAX_BYTES)
        except OSError:
            raise HTTPException(404, "document not installed")
        return PlainTextResponse(raw.decode("utf-8", "replace"), media_type="text/plain; charset=utf-8")

    why_cache: dict = {}

    @app.get("/api/levwhy")
    def levwhy():
        """Why each open position has its leverage (group, score, rejected higher candidates); 15 s cache."""
        hit = why_cache.get("v")
        if hit and time.time() - hit[0] < 15:
            return hit[1]
        try:
            v = data.position_why()
        except sqlite3.Error:
            v = {"positions": {}, "error": "paper3.db를 읽지 못함"}
        why_cache["v"] = (time.time(), v)
        return v

    @app.get("/api/checkpoint")
    def checkpoint_verdict():
        from ..checkpoint import dashboard_view
        return dashboard_view(checkpoint_db)

    @app.get("/api/signals")
    def signals(tf: Optional[str] = None, symbol: Optional[str] = None, limit: int = 200):
        return data.signals(tf, limit, symbol)

    @app.get("/api/trades")
    def trades(symbol: Optional[str] = None, tf: Optional[str] = None, limit: int = 200, group: Optional[str] = None):
        return data.trades(symbol, tf, limit, group)

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

    overlap_cache: dict = {}

    @app.get("/api/overlap")
    def get_overlap(days: float = 7):
        """How much the accounts overlap (paperbot/overlap.py): read-only, descriptive, cached ~10 min."""
        from ..overlap import report
        d = min(max(float(days), 1.0), 30.0) if days == days else 7.0
        key = round(d, 2)
        hit = overlap_cache.get(key)
        if hit is None or time.time() - hit[0] > OVERLAP_TTL_S:
            if len(overlap_cache) > 16:
                overlap_cache.clear()
            c = data.conn()
            try:
                overlap_cache[key] = hit = (time.time(), report(c, d))
            finally:
                c.close()
        return {**hit[1], "computed_at": int(hit[0] * 1000)}

    gh_cache: dict = {}
    bd_cache: dict = {}

    @app.get("/api/breakdown")
    def get_breakdown():
        """By coin, weekday/weekend x session, time windows, volatility at entry (paperbot/breakdown.py);
        read-only, descriptive, cached ~10 min."""
        from ..breakdown import report as bd_report
        hit = bd_cache.get("r")
        if hit is None or time.time() - hit[0] > OVERLAP_TTL_S:
            c = data.conn()
            try:
                bd_cache["r"] = hit = (time.time(), bd_report(c))
            finally:
                c.close()
        return {**hit[1], "computed_at": int(hit[0] * 1000)}

    @app.get("/api/ghcoin")
    def get_ghcoin():
        """GH Coin call recorder (paperbot/ghcoin.py): its calls, net R and the coin-flip comparison; read-only."""
        from ..ghcoin import report
        hit = gh_cache.get("r")
        if hit is None or time.time() - hit[0] > 60:
            gh_cache["r"] = hit = (time.time(), report(os.path.join(os.path.dirname(os.path.abspath(db)), "ghcoin")))
        return hit[1]

    view_cache: dict = {}

    @app.get("/api/strategy/{strategy}")
    def get_strategy_view(strategy: str, tf: str = "1h", symbol: str = "BTCUSDT"):
        """The strategy's own indicator lines and its entry conditions on the last closed bar, plus the
        entry marks of its latest signal on this timeframe and coin (descriptive, see entry_marks.py)."""
        from ..strategy_views import has_view, render
        v4 = strategy in DS200_FAMILY or strategy == REEL_NAME
        if symbol not in (V4_COINS if v4 else TICKER_SYMBOLS):   # DeepSeek and the reel trade the six coins (no XRP)
            raise HTTPException(400, "unknown symbol")
        if tf not in strategy_tfs(strategy):          # each group's own timeframes (the reel 5m only, the 36 never 5m)
            raise HTTPException(400, "unknown timeframe")
        try:
            known = has_view(strategy)                # the 36 (NAMES) and every v4 view that loads now
        except ImportError:
            known = False
        if not known:
            raise HTTPException(404, "no chart view for this strategy yet")
        n = view_bars(tf, strategy)
        try:
            df = frames(symbol, tf, n)
            btc = None
            if strategy == "F14_SMT" and symbol != "BTCUSDT":   # SMT compares with BTC's bars of the same timeframe
                btc = frames("BTCUSDT", tf, n)        # (matched on ts, as lib_c does; passed as the view's argument)
        except Exception:  # noqa: BLE001  (Binance unreachable or refusing: no chart, never a 500)
            raise HTTPException(503, "no price data")
        if df is None or len(df) < 50:
            raise HTTPException(503, "no price data")
        key = (strategy, tf, symbol, str(df["ts"].iloc[-1]),
               None if btc is None or not len(btc) else str(btc["ts"].iloc[-1]))
        if key not in view_cache:
            if len(view_cache) > 256:
                view_cache.clear()
            view_cache[key] = render(strategy, df, tf, symbol=symbol, btc=btc)
        try:  # read fresh on every call: the signal is logged a few seconds after the bar closes
            last = data.last_marks(strategy, tf, symbol)
        except sqlite3.Error:
            last = None
        return {**view_cache[key], "last_signal": last}

    @app.get("/api/strategies")
    def get_strategies(all: int = 0):  # noqa: A002  (the query parameter's name)
        """The 36 (roster order) with their 5-year style. ``all=1`` adds the 44 DeepSeek definitions (PREREG order)
        and the reel, each with its kind, group, family, Korean name (groups.label_ko) and timeframes; the 36 then
        carry kind 'strategy' and group 'core' too."""
        from ..agents.packets3 import CARDS
        from ..agents.roster3 import STRATEGY_KO
        prof = {}
        if os.path.exists(CARDS):
            with open(CARDS) as fh:
                prof = {c["strategy"]: c for c in json.load(fh)["cards"]}
        out = [{"strategy": k, "name_ko": v, "style": prof.get(k, {}).get("style"),
                "hold": prof.get(k, {}).get("hold"), "rare": prof.get(k, {}).get("rare")}
               for k, v in STRATEGY_KO.items()]
        if not all:
            return out
        from .. import groups as G
        from ..config import DS200_DEFS
        for x in out:
            x.update(kind="strategy", group="core", family=None, tfs=list(CORE_TFS))
        out += [{"strategy": d, "name_ko": G.label_ko(d), "kind": "ds200", "group": "ds200", "family": fam,
                 "family_ko": G.DS_FAMILY_KO.get(fam), "tfs": list(strategy_tfs(d)), "style": None, "hold": None,
                 "rare": None} for d, fam, _tfs in DS200_DEFS]
        out.append({"strategy": REEL_NAME, "name_ko": G.label_ko(REEL_NAME), "kind": "reel", "group": "reel",
                    "family": None, "tfs": [REEL_TF], "style": None, "hold": None, "rare": None})
        return out

    risk_cache: dict = {}

    @app.get("/api/profile/{strategy}")
    def get_profile(strategy: str):
        """The strategy's 5-year card, plus ``live_risk`` (agents/survival.py, read-only, cached ~10 min): its
        timeframe accounts' deepest drawdown and the highest account bust probability (accounts with >= 20 trades)."""
        from ..agents.packets3 import profile_card
        c = profile_card(strategy)
        if c is None and (strategy in DS200_FAMILY or strategy == REEL_NAME):
            # a DeepSeek definition or the reel: its 5-year research card (ds_profiles.py: the research exits, labelled
            # as such; the reel's are its own live exits)
            # (``card``: the same research in agents/packets3.profile_card's shape, ds_profiles.card: what the
            # specialists' packets read, one row per timeframe with the research exit closest to the live one)
            from .. import ds_profiles
            try:
                c = ds_profiles.profile(strategy)
                if c is not None:
                    c = {**c, "card": ds_profiles.card(strategy)}
            except Exception:  # noqa: BLE001  (a missing or changed research file: no card, never a 500)
                c = None
        if c is None:
            raise HTTPException(404, "unknown strategy")
        # 이미 해 본 시험 (strategy page, batch ana8A): what the pre-registered studies already tested for this name
        # (packets3.research_prior: the entry study for the 36, agents/ds_prior.json for DeepSeek and the reel).
        # json_finite: the rare 36 (N14_ICHI_RSI, N15_KC_AO) have NaN cells in their 5-year card (no signals on a
        # timeframe), which made this route a 500; they go out as null ("—" on the page).
        from ..agents.packets3 import research_prior
        try:
            c = json_finite({**c, "research_prior": research_prior(strategy)})
        except Exception:  # noqa: BLE001  (a description only: no prior, never a 500)
            c = json_finite({**c, "research_prior": None})
        hit = risk_cache.get(strategy)
        if hit is None or time.time() - hit[0] > TRADES_TTL_S:
            from ..agents import survival as SV
            try:
                conn = data.conn()
                try:
                    val = SV.dash_strategy(conn, strategy, int(time.time() * 1000))
                finally:
                    conn.close()
            except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
                val = {"error": type(exc).__name__}
            if len(risk_cache) > 64:
                risk_cache.clear()
            risk_cache[strategy] = hit = (time.time(), val)
        return {**c, "live_risk": hit[1]}

    curve_cache: dict = {}

    @app.get("/api/v4/curves")
    def get_curves(step: int = 3_600_000):
        """The original accounts' equity over the run: median per kind and the total (Data.curves; 60 s cache)."""
        hit = curve_cache.get(step)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        try:
            v = json_finite(data.curves(step))
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}")
        if len(curve_cache) > 8:
            curve_cache.clear()
        curve_cache[step] = (time.time(), v)
        return v

    server_cache: dict = {}

    @app.get("/api/v4/server")
    def get_server():
        """CPU, memory, disk, database sizes, signal time per timeframe, Telegram count (server_facts; 5 s cache)."""
        hit = server_cache.get("v")
        if hit and time.time() - hit[0] < SERVER_TTL_S:
            return hit[1]
        v = json_finite(server_facts(data, agents_db, daily_db))
        server_cache["v"] = (time.time(), v)
        return v

    @app.get("/api/agents/feed")
    def agents_feed(limit: int = 200, after_id: int = 0):
        return agent_feed(agents_db, min(max(limit, 1), 1000), after_id)

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

    office_cache: dict = {}

    @app.get("/api/office")
    def get_office():
        """The meeting room view (office.js): meetings running now with the real latest line of each speaker,
        today's finished meetings, today's counts and the fixed meeting hours. Read-only, reused a few seconds."""
        hit = office_cache.get("o")
        if hit is None or time.time() - hit[0] > OFFICE_TTL_S:
            office_cache["o"] = hit = (time.time(), rooms.office())
        return hit[1]

    # ------------------------------------------------ meeting digest (paperbot/agents/digest.py: code only, read-only)
    digest_cache: dict = {}
    digest_busy: set = set()
    digest_lock = threading.Lock()

    def _digest_cached(key: str, fn, ttl: float = DIGEST_TTL_S):
        """The first request computes; after that an expired result is answered at once (``stale: true``) while one
        background thread recomputes it, so the week and timeframe views (every closed trade since the start: about
        4 s at day 30) hold a request only the first time."""
        hit = digest_cache.get(key)
        if hit is None:
            digest_cache[key] = hit = (time.time(), fn())
        elif time.time() - hit[0] > ttl:
            with digest_lock:
                start = key not in digest_busy
                digest_busy.add(key)
            if start:
                def refresh():
                    try:
                        digest_cache[key] = (time.time(), fn())
                    except Exception as exc:  # noqa: BLE001  (the old result stays; retried on the next request)
                        print(f"warning: digest {key} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                    finally:
                        with digest_lock:
                            digest_busy.discard(key)
                threading.Thread(target=refresh, daemon=True, name=f"dash-digest-{key}").start()
            return {**hit[1], "computed_at": int(hit[0] * 1000), "stale": True}
        return {**hit[1], "computed_at": int(hit[0] * 1000)}

    @app.get("/api/digest/day")
    def get_digest_day(day: Optional[str] = None):
        """Every meeting of one KST day (default today): code summary, speakers, replies, lead lines."""
        from ..agents import digest as DG
        d = day or rooms.R.kst_day(int(time.time() * 1000))
        try:
            DG.day_start_ms(d)
        except ValueError:
            raise HTTPException(400, "day는 YYYY-MM-DD") from None
        with rooms.ro(rooms.agents_db) as a:
            return DG.day_digest(a, d)

    @app.get("/api/digest/staff")
    def get_digest_staff(days: int = 7):
        """Per staff member: turns, replies, questions, proposals, verdicts (last ``days``) and graded predictions."""
        from ..agents import digest as DG
        n = min(max(int(days), 1), 60)

        def make():
            with rooms.ro(rooms.agents_db) as a:
                return DG.staff_board(a, int(time.time() * 1000), n)
        return _digest_cached(f"staff:{n}", make)

    @app.get("/api/digest/week")
    def get_digest_week():
        """The last 7 days against the 7 before (what the Sunday Telegram report sends)."""
        from ..agents import digest as DG

        def make():
            try:
                c = data.conn()
                init = data.initial()
            except sqlite3.Error as exc:
                return {"error": f"paper3.db를 열지 못함: {type(exc).__name__}"}
            try:
                with rooms.ro(rooms.agents_db) as a:
                    rep = DG.week_report(c, a, int(time.time() * 1000), init)
            finally:
                c.close()
            return {**rep, "telegram_text": DG.compose_week(rep), "hours": _trigger_defaults(rooms.hours())}
        return _digest_cached("week", make, TRADES_TTL_S)

    @app.get("/api/digest/tf")
    def get_digest_tf():
        """Each strategy's timeframe accounts side by side and the ones that disagree (tf_split meetings)."""
        from ..agents import digest as DG

        def make():
            try:
                c = data.conn()
                init = data.initial()
            except sqlite3.Error as exc:
                return {"error": f"paper3.db를 열지 못함: {type(exc).__name__}", "strategies": [], "split": []}
            try:
                return {**DG.tf_split(c, init), "hours": _trigger_defaults(rooms.hours())}
            finally:
                c.close()
        return _digest_cached("tf", make, TRADES_TTL_S)

    # ------------------------------------------------ agent rooms: owner writes (inbox.db only)
    @app.get("/api/market")
    def get_market():
        """The market tab: outside data (fear & greed, dominance, US indexes) and the registered US macro releases."""
        from .. import events
        try:
            evs = [e.as_dict() for e in events.all_events()]
            probs = events.problems()
        except Exception as exc:  # noqa: BLE001
            evs, probs = [], [type(exc).__name__]
        now = int(time.time() * 1000)
        out = market()
        out["events"] = [e for e in evs if now - 7 * 86_400_000 <= e["ts_ms"] <= now + 120 * 86_400_000]
        out["events_total"] = len(evs)
        out["events_problems"] = probs[:5]
        return out

    @app.get("/api/price-alerts")
    def get_price_alerts():
        return rooms.price_alerts()

    @app.post("/api/price-alerts")
    async def post_price_alert(req: Request):
        """{symbol, price, direction?: above|below, note?}; without a direction it is set from the current
        price (a target above it fires on the way up, below it on the way down)."""
        if not same_origin(req):
            raise HTTPException(403, "다른 사이트에서 온 요청은 받지 않습니다")
        body = await _json_object(req)
        sym = body.get("symbol")
        if sym not in TICKER_SYMBOLS:
            raise HTTPException(400, "모르는 코인입니다")
        try:
            price = float(body.get("price"))
        except (TypeError, ValueError):
            raise HTTPException(400, "가격을 숫자로 적어 주세요")
        if not (price > 0 and price < 1e9):
            raise HTTPException(400, "가격을 확인해 주세요")
        direction = body.get("direction")
        if direction not in ("above", "below"):
            now_px = None
            try:
                t = ticker().get(sym) or {}
                now_px = t.get("c") or t.get("mark")
            except Exception:  # noqa: BLE001
                now_px = None
            if not now_px:
                raise HTTPException(503, "지금 가격을 몰라 방향을 정하지 못했습니다. 위/아래를 골라 주세요")
            direction = "above" if price > float(now_px) else "below"
        note = body.get("note") if isinstance(body.get("note"), str) else ""
        if note and not _storable(note):
            raise HTTPException(400, "메모에 보낼 수 없는 글자가 들어 있습니다")
        return {**rooms.add_price_alert(sym, direction, price, note.strip()[:100], rooms.author(body)),
                "direction": direction}

    @app.post("/api/price-alerts/{alert_id}/{action}")
    async def change_price_alert(alert_id: int, action: str, req: Request):
        if not same_origin(req):
            raise HTTPException(403, "다른 사이트에서 온 요청은 받지 않습니다")
        if action not in ("delete", "rearm"):
            raise HTTPException(404, "모르는 동작입니다")
        return rooms.change_price_alert(alert_id, action)

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
        if interval not in CANDLE_INTERVALS:
            raise HTTPException(400, "unknown interval")
        # the live-bar fallback asks for 2 rows every 5 s (fetch_candles caches those 4 s); the chart load asks for 300
        return candles(symbol, interval, min(max(limit, 2), 1500))

    @app.get("/api/summary")
    def get_summary():
        """Experiment day, next checkpoint, observation period and today's summary (KST)."""
        return data.summary()

    @app.get("/api/export/trades.csv")
    def export_trades(account: Optional[str] = None):
        name = f"trades_{account or 'all'}.csv".replace("@", "_").replace("~", "_")
        return Response(data.trades_csv(account), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/export/board.csv")
    def export_board():
        return Response(data.board_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="board.csv"'})

    @app.get("/api/depth")
    def get_depth(symbol: str = "BTCUSDT"):
        """Order book top 20 from the server (fallback for a blocked WebSocket)."""
        if symbol not in TICKER_SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        try:
            return depth(symbol)
        except Exception:  # noqa: BLE001
            raise HTTPException(503, "no order book")

    @app.get("/api/liq")
    def get_liq(symbol: str = "BTCUSDT", minutes: int = 60):
        """Forced liquidations of one coin (or symbol=ALL: the whole market, every coin the recorder keeps) across
        Binance (the liquidation recorder's liq.db), read-only."""
        liq_db = os.path.join(os.path.dirname(os.path.abspath(db)), "liq.db")
        if symbol == "ALL":
            return data.liquidations_market(liq_db, min(max(minutes, 5), 1440))
        if symbol not in TICKER_SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        return data.liquidations(liq_db, symbol, min(max(minutes, 5), 1440))

    levels_cache: dict = {}

    @app.get("/api/levels")
    def get_levels(symbol: str = "BTCUSDT", tf: str = "15m"):
        """Support / resistance lines of the last closed bar (entry_marks.chart_levels: the same level
        definitions recorded with every signal). Descriptive only."""
        from .. import entry_marks
        if symbol not in TICKER_SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        if tf not in LEVEL_TFS:
            return {"levels": [], "note": "no levels for this timeframe"}
        df = frames(symbol, tf, entry_marks.chart_bars(tf))
        if df is None or len(df) < 320:
            raise HTTPException(503, "no price data")
        key = (symbol, tf, str(df["ts"].iloc[-1]))
        if key not in levels_cache:
            if len(levels_cache) > 128:
                levels_cache.clear()
            try:
                levels_cache[key] = {**entry_marks.chart_levels(df, tf), "bar": str(df["ts"].iloc[-1])}
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(503, f"levels failed: {type(exc).__name__}")
        return levels_cache[key]

    @app.get("/api/events")
    def get_events(days_back: int = 60, days_ahead: int = 30):
        """Registered US macro releases around now (data/macro_events.csv, code only: no outside fetch)."""
        from .. import events as EV
        now = int(time.time() * 1000)
        lo = now - min(max(int(days_back), 0), 400) * 86_400_000
        hi = now + min(max(int(days_ahead), 0), 400) * 86_400_000
        return {"events": [e.as_dict() for e in EV.all_events() if lo <= e.ts_ms <= hi], "problems": EV.problems()}

    @app.get("/api/ghcoin/board")
    def get_ghcoin_board():
        """GH Coin's latest plan per coin (board.json of the recorder), without the totals."""
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(db)), "ghcoin", "board.json"), encoding="utf-8") as fh:
                b = json.load(fh)
        except (OSError, ValueError):
            return {"coins": {}, "alive": False}
        return {"coins": b.get("coins") or {}, "ts": b.get("ts"), "errors": b.get("errors") or {},
                "alive": time.time() * 1000 - int(b.get("ts") or 0) <= 15 * 60_000}

    @app.get("/api/ticker")
    def get_ticker():
        """The 7 coins' 24h ticker, mark price and funding from the server (fallback for a blocked WebSocket)."""
        return ticker()

    @app.get("/api/stream")
    async def stream(req: Request, trade_id: int = 0, alert_row: int = 0, room_msg: int = 0):
        async def gen():
            st = {"trade_id": trade_id, "alert_row": alert_row, "room_msg": room_msg, "last_board": None}
            if not st["trade_id"] and not st["alert_row"]:   # a new page starts from now, not from the first trade
                st["trade_id"], st["alert_row"] = data.latest_ids()
            if not st["room_msg"]:
                st["room_msg"] = rooms.last_id()
            while not await req.is_disconnected():
                # (in a worker thread: the database reads never hold up the other pages' requests)
                yield await asyncio.to_thread(stream_event, data, rooms, st)
                await asyncio.sleep(3)
        return StreamingResponse(gen(), media_type="text/event-stream")

    # the '분석' tab, the health card, the alert history, the server clock and the debate room (read-only)
    from . import analysis
    app.state.analysis = analysis.register(app, data, rooms, db, daily_db, checkpoint_db, debate_db,
                                           failalert_dir=failalert_dir or analysis.FAILALERT_DIR)

    # v4 additions (dash/more): race and calendar, strategy grid, daily story, since-last-visit, trade replay (read-only)
    from . import more
    app.state.more = more.register_all(app, data=data, rooms=rooms, db=db, daily_db=daily_db, agents_db=agents_db,
                                       checkpoint_db=checkpoint_db, candles=candles, frames=frames)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
