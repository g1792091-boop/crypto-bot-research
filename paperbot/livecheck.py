"""실거래 일일 점검: the morning check of the two real-money executors (Bybit $100, MEXC $100, owners 2026-10-19) that
follow the combined paper bot (paperbot/combo.py, account COMBO@mix).

    python -m paperbot.livecheck run [--day YYYY-MM-DD] [--dry-run] [--no-replay]
    python -m paperbot.livecheck show [--day YYYY-MM-DD]

``run`` (deploy/paperbot-livecheck.timer, 09:10 KST) checks one trading day, 09:00 KST to 09:00 KST (00:00 to 00:00
UTC: the day boundary of the paper bot's snapshots and of the executors' daily loss limit), by default the one that
ended at 09:00 today; ``--day`` names it by the KST date it starts on. It stores the result in its own SQLite file
(``--db``, default /var/lib/paperbot/livecheck.db: tables days, parity, costs, scores; for a dashboard later) and sends
ONE plain-Korean Telegram message through the repository's notifier (paperbot/live.py ``_notifier``: live.env's bot
and chats). Silent (INFO) when everything is fine; loud (CRITICAL) when the replay and the paper bot disagree without
a known cause, when real costs are above the flags, when a real trade has no paper trade, or when an executor is
halted. ``--dry-run`` prints the message and writes nothing (no Telegram, no livecheck.db).

1. 대조 (parity): paperbot/livereplay.py runs the combined bot itself over the day as the live process ran it (the bars
   it stepped on, its own 09:00 snapshot, the market data it reads from Binance) and the result is compared with what
   the paper bot recorded in its database: every signal of the day (bar, coin, side, setting) with its status, and every
   COMBO@mix trade (entry time, coin, side, exit reason, net ROE). Each difference is reported in KST with coin, side
   and strategy, with the cause when one can be read from the records (the paper bot not running then: no record
   while the replay had signals, a restart, late signals refused; the rule bot's 1m bars missing or late; a market
   read that failed on the live side; a position the other side was still holding). Binance unreachable: the message
   says so. The replay takes about 6 minutes a day and is stopped by ``--replay-budget-min``.
2. 실제 비용: every executor trade closed in the day, matched to its paper trade (the executor's trade key is the paper
   position's own key; else the same coin and side entered within ``MATCH_MS``): entry and exit price against the
   paper's in bps (+ = worse for us), fees paid against the assumed rate (Bybit taker 0.055%, MEXC 0.08%), funding,
   and the day's averages. Loud when the average slippage is worse than ``SLIP_FLAG_BPS`` a side or the fee rate is
   above the assumed one.
3. 성적표: the paper account since its database started (trades, wins, win rate, last 20 and last 40, net P&L), each
   executor (trades, win rate, realised $ P&L, equity, halted or not, its signal light from the paper's last N closed
   trades and its own config's threshold, how many paper entries the light skipped), the coin-flip twin and the
   shadow paper bots (/var/lib/paperbot/combo/shadow-*.db) for reference, and the owners' 40-trade checkpoint
   (88% or more: consider more money; 82-88%: keep watching; under 82%: stop and rethink). Mondays add the last 7 days.
   Samples under 20 trades are marked as small.

Read-only towards the bots: their databases are opened read-only (paperbot/livepnl.py ``open_ro``), the executors'
configs are read as plain JSON (never their key file), no exchange account is called and no order is sent.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

MIN = 60_000
H1 = 3_600_000
DAY = 86_400_000
KST_MS = 9 * H1
ACCOUNT = "COMBO@mix"
FLIP_ACCOUNT = "COMBOFLIP@mix"
DEFAULT_DB = "/var/lib/paperbot/livecheck.db"
DEFAULT_CACHE = "/var/lib/paperbot/livecheck-cache.db"
COMBO_CONFIG = "/etc/paperbot/combo.json"
PAPER_DB = "/var/lib/paperbot/combo/live-ac.db"
RULE_DB = "/var/lib/paperbot/paper3.db"
SHADOW_GLOB = "/var/lib/paperbot/combo/shadow-*.db"
SHADOW_NAMES = {"shadow-b": "그림자 B 안정형", "shadow-nocut": "그림자 끄는 구간 없음", "shadow-ac32": "그림자 32개"}
# (name, executor config, systemd unit, fallbacks when the config cannot be read: db, light N, light share)
EXECUTORS = (("bybit", "/etc/paperbot/executor.json", "paperbot-executor",
              "/var/lib/paperbot/exec/executor-bybit-live.db", 20, 0.85),
             ("mexc", "/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc",
              "/var/lib/paperbot/exec/executor-mexc-live.db", 20, 0.90))
ASSUMED_FEE = {"bybit": 0.00055, "mexc": 0.0008, "binance": 0.0005}
EX_KO = {"bybit": "바이비트", "mexc": "MEXC", "binance": "바이낸스"}
KO_SIDE = {1: "롱", -1: "숏"}
KO_TF = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
KO_EXIT = {"SL": "손절", "LOCK": "계단 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산",
           "REV": "빠른 청산", "TP": "익절", "END": "끝"}
KO_DOW = "월화수목금토일"
KO_STATUS = {"SUBMITTED": "진입 신호", "FILTERED": "걸러짐", "WAITING": "돌파 대기", "BROKE": "돌파 확인",
             "REJECTED": "거절"}
MATCH_MS = 5 * MIN                 # an executor trade without the paper key: same coin and side, entered this close
SLIP_FLAG_BPS = 5.0                # average slippage a side (bps, + = worse than the paper) above this: loud
FEE_TOL = 1.02                     # fee rate above assumed x this: loud
ROE_TOL = 0.03                     # replay vs record: net ROE further apart than this (3 percentage points) differs
EXIT_TOL_MS = 5 * MIN              # ... or exit times further apart than this
SMALL = 20                         # fewer trades than this: "small sample"
CHECK_N, GROW, KEEP = 40, 0.88, 0.82      # the owners' checkpoint: 40 trades, 88% / 82%
MAX_LINES = 8                      # difference lines listed per kind
SILENT_GAP_MS = 30 * MIN           # replay signals but no record for this long: the paper bot was not running
REPLAY_BUDGET_MIN = 25


# ====================================================================== time
def kst(ms: int, fmt: str = "%H:%M") -> str:
    return time.strftime(fmt, time.gmtime(int(ms) / 1000 + 9 * 3600))


def kst_day(ms: int) -> str:
    """'10/19(월)'"""
    d = _dt.datetime.fromtimestamp(int(ms) / 1000 + 9 * 3600, _dt.timezone.utc)
    return f"{d.month}/{d.day}({KO_DOW[d.weekday()]})"


def kst_dt(ms: int) -> str:
    """'10/19 17:30'"""
    return kst(ms, "%m/%d %H:%M").lstrip("0").replace("/0", "/")


def window_of(day: str) -> tuple[int, int]:
    """[09:00 KST of ``day``, 09:00 KST the next day) in ms (= that UTC date)."""
    d = _dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
    w0 = int(d.timestamp() * 1000)
    return w0, w0 + DAY


def default_day(now_ms: int) -> str:
    """The last complete check day: the one that ended at the latest 09:00 KST."""
    return _dt.datetime.fromtimestamp(int(now_ms) / 1000 - 86_400, _dt.timezone.utc).strftime("%Y-%m-%d")


def usd(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"


def money(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.2f}"


def pct(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.0%}"


def coin(symbol: str) -> str:
    return str(symbol).replace("USDT", "")


# ====================================================================== reading the bots (read-only)
def open_ro(path: str) -> Optional[sqlite3.Connection]:
    """A read-only connection (paperbot/livepnl.py open_ro) or None when the file is missing or unreadable."""
    if not path or not os.path.exists(path):
        return None
    from .livepnl import open_ro as _ro
    try:
        conn = _ro(path)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn
    except sqlite3.Error:
        return None


def get_state(conn, key: str) -> tuple[Optional[int], Optional[dict]]:
    try:
        r = conn.execute("SELECT ts, data FROM state WHERE k = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None, None
    if r is None:
        return None, None
    try:
        return int(r[0]), json.loads(r[1])
    except (ValueError, TypeError):
        return int(r[0]), None


def paper_trades(conn, account: str) -> list:
    """Closed trades of a paper account, oldest exit first (the executor's signal light reads them newest first by
    exit_time, id)."""
    out = []
    try:
        rows = conn.execute("SELECT id, entry_time, exit_time, exit_reason, pnl, roe, symbol, data FROM trades "
                            "WHERE account_id = ? ORDER BY exit_time, id", (account,)).fetchall()
    except sqlite3.Error:
        return out
    for i, et, xt, reason, pnl, roe, sym, data in rows:
        try:
            d = json.loads(data)
        except (ValueError, TypeError):
            d = {}
        out.append({"id": int(i), "entry_time": int(et), "exit_time": int(xt), "reason": reason, "pnl": float(pnl),
                    "roe": float(roe), "symbol": sym, "side": int(d.get("side") or 0),
                    "strategy": d.get("strategy_id", ""), "tf": d.get("timeframe", ""),
                    "entry_price": d.get("entry_price"), "exit_price": d.get("exit_price"),
                    "funding": d.get("funding"), "fees": d.get("fees")})
    return out


def win_stats(trades: list) -> dict:
    n = len(trades)
    w = sum(1 for t in trades if t["pnl"] > 0)
    return {"n": n, "wins": w, "rate": (w / n) if n else None, "pnl": sum(t["pnl"] for t in trades)}


def light_state(trades: list, n: int, need: float, at: Optional[int] = None) -> dict:
    """The executor's signal light (paperbot/executor.py ``_light_ok``): the paper account's last ``n`` closed trades
    (newest by exit time, then id; only those closed by ``at``) won at least ``need`` of them. Fewer than ``n``
    closed trades: "building" (the executor follows every entry)."""
    if not n:
        return {"state": "off", "n": 0, "have": len(trades), "wins": None, "need": need}
    done = [t for t in trades if at is None or t["exit_time"] <= at]
    last = sorted(done, key=lambda t: (t["exit_time"], t["id"]))[-n:]
    wins = sum(1 for t in last if t["pnl"] > 0)
    if len(last) < n:
        return {"state": "building", "n": n, "have": len(last), "wins": wins, "need": need}
    return {"state": "green" if wins >= need * n - 1e-9 else "red", "n": n, "have": len(last), "wins": wins,
            "need": need}


def light_text(L: dict) -> str:
    if L["state"] == "off":
        return "신호등 꺼짐(모두 따라감)"
    if L["state"] == "building":
        return f"신호등 근거 쌓는 중({L['have']}/{L['n']}번, 그동안 모두 따라감)"
    word = "초록" if L["state"] == "green" else "빨강"
    return f"신호등 {word}(최근 {L['n']}번 {L['wins']}승 {L['wins'] / L['n']:.0%}, 기준 {L['need']:.0%})"


# ---------------------------------------------------------------- executors
@dataclass
class ExecInfo:
    name: str                       # "bybit" | "mexc"
    config: str
    unit: str
    db: str
    light_n: int
    light_min: float
    exchange: str = ""
    account: str = ACCOUNT
    budget: Optional[float] = None
    kill_file: str = "/var/lib/paperbot/STOP"
    max_dd: float = 0.5
    problem: str = ""               # the config could not be read: the fallbacks are used

    @property
    def label(self) -> str:
        return EX_KO.get(self.exchange or self.name, self.name)

    @property
    def fee(self) -> float:
        return ASSUMED_FEE.get(self.exchange or self.name, ASSUMED_FEE["binance"])


def load_executors(specs=EXECUTORS) -> list[ExecInfo]:
    """The executors' configs as plain JSON (the executor module and its key file are never touched)."""
    out = []
    for name, path, unit, db, n, share in specs:
        e = ExecInfo(name=name, config=path, unit=unit, db=db, light_n=n, light_min=share, exchange=name)
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            e.db = str(d.get("db") or db)
            e.exchange = str(d.get("exchange") or "binance")
            e.account = str(d.get("account") or ACCOUNT)
            e.light_n = int(d.get("signal_light_n", 0) or 0)
            e.light_min = float(d.get("signal_light_min_win", 0.85))
            e.budget = float(d["budget_usd"]) if d.get("budget_usd") is not None else None
            risk = d.get("risk") or {}
            e.kill_file = str(risk.get("kill_file") or e.kill_file)
            if risk.get("max_drawdown_pct") is not None:
                e.max_dd = float(risk["max_drawdown_pct"])
        except (OSError, ValueError, TypeError) as exc:
            e.problem = f"설정 파일을 못 읽음({type(exc).__name__}); 기본값 사용"
        out.append(e)
    return out


def exec_trades(conn) -> list:
    out = []
    try:
        cur = conn.execute("SELECT * FROM trades ORDER BY entry_ts")
    except sqlite3.Error:
        return out
    cols = [c[0] for c in cur.description]
    for r in cur.fetchall():
        t = dict(zip(cols, r))
        try:
            t["data"] = json.loads(t.get("data") or "{}")
        except (ValueError, TypeError):
            t["data"] = {}
        out.append(t)
    return out


def exec_fills(conn, key: str) -> list:
    try:
        return [json.loads(d) for (d,) in conn.execute("SELECT data FROM fills WHERE trade_key = ? ORDER BY ts, id",
                                                       (key,))]
    except (sqlite3.Error, ValueError):
        return []


def exec_events(conn, kind: str, since: Optional[int] = None, until: Optional[int] = None) -> list:
    q, a = "SELECT ts, text, data FROM events WHERE kind = ?", [kind]
    if since is not None:
        q, a = q + " AND ts >= ?", a + [int(since)]
    if until is not None:
        q, a = q + " AND ts < ?", a + [int(until)]
    try:
        rows = conn.execute(q + " ORDER BY id", a).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for ts, text, data in rows:
        try:
            d = json.loads(data or "{}")
        except ValueError:
            d = {}
        out.append({"ts": int(ts), "text": text, "data": d})
    return out


def exec_equity(conn) -> tuple[Optional[dict], Optional[dict]]:
    """(first, last) equity samples."""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(equity)")}
        tr = "transfers" if "transfers" in cols else "0"
        first = conn.execute(f"SELECT ts, equity, wallet, {tr} FROM equity ORDER BY ts LIMIT 1").fetchone()
        last = conn.execute(f"SELECT ts, equity, wallet, {tr} FROM equity ORDER BY ts DESC LIMIT 1").fetchone()
    except sqlite3.Error:
        return None, None

    def d(r):
        return None if r is None else {"ts": int(r[0]), "equity": float(r[1]), "wallet": float(r[2]),
                                       "transfers": float(r[3] or 0)}
    return d(first), d(last)


# ====================================================================== 2. costs
def match_paper(et: dict, paper: list, account: str = ACCOUNT) -> Optional[dict]:
    """The paper trade an executor trade followed: its key (account|symbol|paper entry time), else the same coin and
    side entered within MATCH_MS of the live entry."""
    key = str(et.get("key") or "")
    parts = key.split("|")
    if len(parts) == 3 and parts[0] == account:
        for p in paper:
            if p["symbol"] == parts[1] and str(p["entry_time"]) == parts[2]:
                return p
    best, gap = None, MATCH_MS + 1
    for p in paper:
        if p["symbol"] != et.get("symbol") or p["side"] != int(et.get("side") or 0):
            continue
        g = abs(int(p["entry_time"]) - int(et.get("entry_ts") or 0))
        if g < gap:
            best, gap = p, g
    return best


def cost_row(ex: ExecInfo, et: dict, pt: Optional[dict], fills: list) -> dict:
    """One closed executor trade against its paper trade (bps: + = worse for us than the paper's price)."""
    from .livepnl import trade_costs
    side = int(et.get("side") or 0)
    c = trade_costs(side, fills, [], None, None, taker_fee=ex.fee) if fills else {}
    avg_in = c.get("avg_in") or et.get("entry_price")
    avg_out = c.get("avg_out")
    notional = (c.get("notional_in") or 0.0) + (c.get("notional_out") or 0.0)
    commission = et.get("commission")
    if commission is None and fills:
        commission = c.get("commission")
    funding = et.get("funding")
    row = {"exchange": ex.name, "key": et.get("key"), "symbol": et.get("symbol"), "side": side,
           "entry_ts": et.get("entry_ts"), "exit_ts": et.get("exit_ts"), "real_entry": avg_in, "real_exit": avg_out,
           "paper_entry": None, "paper_exit": None, "entry_bps": None, "exit_bps": None, "notional": notional or None,
           "commission": commission, "fee_rate": (float(commission) / notional) if (commission is not None and notional)
           else None, "assumed_fee": ex.fee, "funding": funding, "pnl": et.get("pnl"), "paper_roe": None,
           "matched": pt is not None, "fills": len(fills), "strategy": "", "tf": ""}
    if pt is not None:
        pe, px = pt.get("entry_price"), pt.get("exit_price")
        row.update(paper_entry=pe, paper_exit=px, paper_roe=pt["roe"], strategy=pt.get("strategy", ""),
                   tf=pt.get("tf", ""))
        if pe and avg_in:
            row["entry_bps"] = side * (float(avg_in) - float(pe)) / float(pe) * 1e4
        if px and avg_out:
            row["exit_bps"] = side * (float(px) - float(avg_out)) / float(px) * 1e4
    return row


def cost_summary(rows: list, fee: float) -> dict:
    ins = [r["entry_bps"] for r in rows if r.get("entry_bps") is not None]
    outs = [r["exit_bps"] for r in rows if r.get("exit_bps") is not None]
    both = ins + outs
    notional = sum(float(r["notional"]) for r in rows if r.get("notional") and r.get("commission") is not None)
    comm = sum(float(r["commission"]) for r in rows if r.get("notional") and r.get("commission") is not None)
    fund = sum(float(r["funding"] or 0) for r in rows)
    s = {"n": len(rows), "entry_bps": sum(ins) / len(ins) if ins else None,
         "exit_bps": sum(outs) / len(outs) if outs else None, "side_bps": sum(both) / len(both) if both else None,
         "fee_rate": comm / notional if notional else None, "assumed_fee": fee, "funding": fund,
         "pnl": sum(float(r["pnl"] or 0) for r in rows), "unmatched": sum(1 for r in rows if not r["matched"]),
         "unmeasured": sum(1 for r in rows if r.get("entry_bps") is None and r.get("exit_bps") is None)}
    s["flags"] = []
    if s["side_bps"] is not None and s["side_bps"] > SLIP_FLAG_BPS:
        s["flags"].append(f"미끄러짐이 한쪽 평균 {s['side_bps']:+.1f}bps로 기준 {SLIP_FLAG_BPS:g}bps보다 큽니다")
    if s["fee_rate"] is not None and s["fee_rate"] > fee * FEE_TOL + 1e-7:
        s["flags"].append(f"수수료가 {s['fee_rate']:.3%}로 가정 {fee:.3%}보다 높습니다")
    if s["unmatched"]:
        s["flags"].append(f"페이퍼 거래와 짝이 없는 실거래 {s['unmatched']}번")
    return s


# ====================================================================== 1. parity
def _skey(s: dict) -> tuple:
    return (int(s["bar_close"]), s["strategy"], s["symbol"], int(s["side"]))


def _tkey(t: dict) -> tuple:
    return (int(t["entry_time"]), t["symbol"], int(t["side"]))


@dataclass
class Context:
    """What the records say about the day, for the causes of differences."""
    live_signals: list = field(default_factory=list)
    replay_signals: list = field(default_factory=list)
    live_outcomes: list = field(default_factory=list)
    restarts: list = field(default_factory=list)          # paper bot start times (ms)
    alerts: list = field(default_factory=list)            # (ts, level, text) of the paper bot
    bar_gaps: list = field(default_factory=list)          # rule-bot minutes missing (ms)
    bar_late: dict = field(default_factory=dict)          # minute -> seconds late (> the paper bot's 150 s)
    down: list = field(default_factory=list)              # (from, to) the paper bot not running (watch records)
    live_busy: list = field(default_factory=list)         # (entry, exit) positions of the record
    replay_busy: list = field(default_factory=list)
    source: str = ""
    seeded: bool = True                                   # the replay started from the 09:00 snapshot
    replay_end: Optional[int] = None                      # the replay's last stepped minute's close
    prebreak: set = field(default_factory=set)            # (bar close, coin, side) of breaks of signals before 09:00
    live_last: Optional[int] = None                       # the record's last stepped minute
    w0: Optional[int] = None

    def silent_spans(self) -> list:
        """(from, to) spans of at least SILENT_GAP_MS where the replay logged 3+ signals and the record none."""
        live_t = sorted({s["bar_close"] for s in self.live_signals})
        rep_t = sorted({s["bar_close"] for s in self.replay_signals})
        out = []
        bounds = [None] + live_t + [None]
        for a, b in zip(bounds[:-1], bounds[1:]):
            inside = [t for t in rep_t if (a is None or t > a) and (b is None or t < b)]
            if len(inside) >= 3 and inside[-1] - inside[0] >= SILENT_GAP_MS:
                out.append((inside[0], inside[-1]))
        return out


def explain(t: int, ctx: Context, live_why: str = "", busy: Optional[str] = None) -> str:
    """The cause of a difference at time ``t`` (a bar close or an entry minute) when the records show one, else ''."""
    for a, b in ctx.down:
        if a - 3 * MIN <= t <= b + 3 * MIN:
            return f"그때 페이퍼 봇이 멈춰 있었음({kst(a)}~{kst(b)}, 감시 기록)"
    for o in ctx.live_outcomes:
        if o["status"] == "REJECTED" and o["reason"] == "late" \
                and abs(int(o.get("bar_close") or o["ts"]) - t) <= 5 * MIN:
            return "페이퍼 봇이 신호를 늦게 받아 거래하지 않음(재시작 따라잡기)"
    for a, b in ctx.silent_spans():
        r = [x for x in ctx.restarts if a <= x <= b + 6 * H1]
        if r and a - 5 * MIN <= t <= b + 5 * MIN:         # a silence alone could be a bug: only with a restart
            return f"{kst(a)}~{kst(b)} 페이퍼 봇 기록이 없음(꺼져 있다가 {kst(r[0])}에 다시 시작)"
    for r in ctx.restarts:
        if 0 <= r - t <= 30 * MIN:
            return f"그 무렵 페이퍼 봇이 다시 시작됨({kst(r)})"
    if "못 읽" in (live_why or ""):
        return f"그때 페이퍼 봇이 시장 자료를 못 읽음: {live_why[:80]}"
    m = t - MIN
    if ctx.source != "live" and m in ctx.bar_gaps:
        return f"규칙봇 1분봉이 빠짐({kst(m)})"
    if ctx.source != "live" and m in ctx.bar_late:
        return f"규칙봇 1분봉이 {ctx.bar_late[m]:.0f}초 늦게 들어옴"
    for ts, _lvl, text in ctx.alerts:
        if abs(ts - t) <= 3 * MIN:
            return f"그때 페이퍼 봇 경고: {text[:80]}"
    if busy:
        return busy
    return ""


def _busy(intervals: list, t: int) -> bool:
    return any(a <= t < b for a, b in intervals)


TF_MS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": H1, "4h": 4 * H1}
PREBREAK = "09:00 전에 나와 돌파를 기다리던 신호(다시 계산은 09:00부터라 없음)"


def compare_signals(live: list, rep: list, ctx: Context) -> dict:
    L = {_skey(s): s for s in live}
    R = {_skey(s): s for s in rep}
    out = {"same": 0, "different": [], "missing_live": [], "extra_live": []}
    for k in sorted(set(L) | set(R)):
        a, b = L.get(k), R.get(k)
        if a is not None and b is not None:
            if a["status"] == b["status"]:
                out["same"] += 1
                continue
            if (b["status"] == "WAITING" and ctx.replay_end is not None
                    and k[0] + TF_MS.get(b.get("tf"), H1) > ctx.replay_end):
                out["same"] += 1                 # the break was still awaited where the replay stopped
                continue
            why = explain(k[0], ctx, a.get("why", ""))
            out["different"].append({"t": k[0], "strategy": k[1], "symbol": k[2], "side": k[3], "tf": a.get("tf"),
                                     "name": a.get("name"), "live": a["status"], "replay": b["status"],
                                     "live_why": a.get("why", ""), "replay_why": b.get("why", ""), "why": why})
        elif b is not None:
            out["missing_live"].append({"t": k[0], "strategy": k[1], "symbol": k[2], "side": k[3], "tf": b.get("tf"),
                                        "name": b.get("name"), "replay": b["status"], "why": explain(k[0], ctx)})
        else:
            why = PREBREAK if (k[0], k[2], k[3]) in ctx.prebreak else explain(k[0], ctx, a.get("why", ""))
            out["extra_live"].append({"t": k[0], "strategy": k[1], "symbol": k[2], "side": k[3], "tf": a.get("tf"),
                                      "name": a.get("name"), "live": a["status"], "why": why})
    return out


def compare_trades(live: list, rep: list, ctx: Context, live_open: Optional[dict] = None,
                   rep_open: Optional[dict] = None) -> dict:
    """Trades of the record and the replay by (entry minute, coin, side); an open position counts with its entry."""
    L = {_tkey(t): dict(t, open=False) for t in live}
    R = {_tkey(t): dict(t, open=False) for t in rep}
    if live_open:
        L.setdefault(_tkey(live_open), dict(live_open, open=True))
    if rep_open:
        R.setdefault(_tkey(rep_open), dict(rep_open, open=True))
    out = {"same": 0, "open": 0, "different": [], "missing_live": [], "extra_live": []}
    for k in sorted(set(L) | set(R)):
        a, b = L.get(k), R.get(k)
        base = {"t": k[0], "symbol": k[1], "side": k[2]}
        if a is not None and b is not None:
            base.update(strategy=a.get("strategy") or b.get("strategy"), tf=a.get("tf") or b.get("tf"))
            if a["open"] and not b["open"] and ctx.live_last is not None \
                    and int(b["exit_time"]) + EXIT_TOL_MS < int(ctx.live_last):
                out["different"].append(dict(base, live=a, replay=b, what=["청산 시각"], why=explain(k[0], ctx)))
                continue
            if a["open"] or b["open"]:           # the entry agrees; the exit is compared once both are known
                out["open"] += 1
                out["same"] += 1
                continue
            diff = []
            if a.get("reason") != b.get("reason"):
                diff.append("청산 이유")
            if abs(float(a["roe"]) - float(b["roe"])) > ROE_TOL:
                diff.append("순ROE")
            if abs(int(a["exit_time"]) - int(b["exit_time"])) > EXIT_TOL_MS:
                diff.append("청산 시각")
            if not diff:
                out["same"] += 1
                continue
            out["different"].append(dict(base, live=a, replay=b, what=diff, why=explain(k[0], ctx)))
        elif b is not None:
            busy = "그때 페이퍼 봇은 다른 포지션을 들고 있었음(한 번에 하나)" if _busy(ctx.live_busy, k[0]) else None
            out["missing_live"].append(dict(base, strategy=b.get("strategy"), tf=b.get("tf"), replay=b,
                                            why=explain(k[0], ctx, busy=busy)))
        else:
            busy = "다시 돌린 쪽은 그때 다른 포지션을 들고 있었음(한 번에 하나)" if _busy(ctx.replay_busy, k[0]) else None
            if not ctx.seeded and ctx.w0 is not None and k[0] < ctx.w0:
                busy = "다시 계산은 09:00 상태 기록 없이 빈 계좌로 시작(전날부터 들고 온 거래)"
            if k in ctx.prebreak:
                busy = PREBREAK
            out["extra_live"].append(dict(base, strategy=a.get("strategy"), tf=a.get("tf"), live=a,
                                          why=explain(k[0], ctx, busy=busy)))
    return out


def parity_flags(sig: dict, tr: dict) -> int:
    """Differences without a known cause (the loud ones)."""
    n = 0
    for part in (sig, tr):
        for k in ("different", "missing_live", "extra_live"):
            n += sum(1 for x in part.get(k, []) if not x.get("why"))
    return n


def _sig_line(kind: str, x: dict) -> str:
    what = {"different": "상태 다름", "missing_live": "재계산에만 있음", "extra_live": "기록에만 있음"}[kind]
    name = x.get("name") or str(x.get("strategy", "")).split("@")[0]
    ko = KO_STATUS.get
    st = (f": 기록 {ko(x.get('live'), x.get('live'))} / 재계산 {ko(x.get('replay'), x.get('replay'))}"
          if kind == "different" else f" ({ko(x.get('replay') or x.get('live'), x.get('replay') or x.get('live'))})")
    return (f"- 신호 {what} {kst(x['t'])} {coin(x['symbol'])} {KO_SIDE.get(x['side'], x['side'])} {name} "
            f"{KO_TF.get(x.get('tf'), x.get('tf') or '')}{st}" + (f" — {x['why']}" if x.get("why") else ""))


def _trade_txt(t: dict) -> str:
    if t.get("open"):
        return "아직 열림"
    return f"{KO_EXIT.get(t.get('reason'), t.get('reason'))} {float(t['roe']):+.1%}"


def _trade_line(kind: str, x: dict) -> str:
    what = {"different": "결과 다름", "missing_live": "재계산에만 있음", "extra_live": "기록에만 있음"}[kind]
    head = (f"- 거래 {what} {kst(x['t'])} {coin(x['symbol'])} {KO_SIDE.get(x['side'], x['side'])} "
            f"{x.get('strategy') or ''} {KO_TF.get(x.get('tf'), x.get('tf') or '')}").rstrip()
    if kind == "different":
        body = f": 기록 {_trade_txt(x['live'])} / 재계산 {_trade_txt(x['replay'])}"
    elif kind == "missing_live":
        body = f" (재계산 {_trade_txt(x['replay'])})"
    else:
        body = f" (기록 {_trade_txt(x['live'])})"
    return head + body + (f" — {x['why']}" if x.get("why") else "")


def parity_lines(p: dict) -> list:
    """The 대조 part of the message."""
    if p.get("error"):
        return [f"대조: 못 함 — {p['error']}"]
    sig, tr = p["signals"], p["trades"]
    ns = sig["same"] + len(sig["different"]) + len(sig["missing_live"]) + len(sig["extra_live"])
    nt = tr["same"] + len(tr["different"]) + len(tr["missing_live"]) + len(tr["extra_live"])
    head = f"대조(다시 계산): 거래 {tr['same']}/{nt} 같음 · 신호 {sig['same']}/{ns} 같음"
    if tr.get("open"):
        head += f" · 열린 거래 {tr['open']}번은 진입만 비교"
    out = [head]
    lines = []
    for kind in ("different", "missing_live", "extra_live"):
        lines += [_trade_line(kind, x) for x in tr[kind]]
    for kind in ("different", "missing_live", "extra_live"):
        items = sig[kind]
        unexplained = [x for x in items if not x.get("why")]
        explained = [x for x in items if x.get("why")]
        lines += [_sig_line(kind, x) for x in unexplained]
        by: dict = {}
        for x in explained:
            by.setdefault(x["why"], []).append(x)
        for why, xs in by.items():
            if len(xs) == 1:
                lines.append(_sig_line(kind, xs[0]))
            else:
                what = {"different": "상태 다름", "missing_live": "재계산에만 있음", "extra_live": "기록에만 있음"}[kind]
                lines.append(f"- 신호 {what} {len(xs)}개({kst(xs[0]['t'])}~{kst(xs[-1]['t'])}) — {why}")
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"- 외 {len(lines) - MAX_LINES}줄 (python -m paperbot.livecheck show)"]
    out += lines
    for n in p.get("notes", []):
        out.append(f"- 참고: {n}")
    return out


# ====================================================================== the report
@dataclass
class Sources:
    db: str = DEFAULT_DB
    paper_db: str = PAPER_DB
    rule_db: str = RULE_DB
    combo_config: str = COMBO_CONFIG
    cache: str = DEFAULT_CACHE
    shadow_glob: str = SHADOW_GLOB
    executors: list = field(default_factory=list)


def combo_config(src: Sources, live_conn) -> tuple[Optional[dict], str]:
    """The config the paper bot runs (its own ``combo_run`` record), else the config file."""
    if live_conn is not None:
        _ts, run = get_state(live_conn, "combo_run")
        if run and isinstance(run.get("config"), dict):
            return run["config"], "기록"
    try:
        with open(src.combo_config, encoding="utf-8") as fh:
            return json.load(fh), src.combo_config
    except (OSError, ValueError):
        return None, ""


def read_live_bars(rule_db: str, a: int, b: int) -> Optional[dict]:
    conn = open_ro(rule_db)
    if conn is None:
        return None
    try:
        cur = conn.execute("SELECT ts, symbol, open, high, low, close, volume, mark_open, mark_high, mark_low, "
                           "mark_close, close_time, processed_at FROM live_bars WHERE ts >= ? AND ts < ? ORDER BY ts",
                           (int(a), int(b)))
        cols = [c[0] for c in cur.description]
        out: dict = {}
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            out.setdefault(int(row["ts"]), []).append(row)
        return out
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def bar_quality(bars: Optional[dict], w0: int, w1: int, late_s: float = 150.0) -> tuple[list, dict]:
    if not bars:
        return [], {}
    gaps = [t for t in range(w0, w1, MIN) if t not in bars]
    late = {}
    for t, rows in bars.items():
        p = max(int(r.get("processed_at") or 0) for r in rows)
        s = (p - (t + MIN)) / 1000
        if s > late_s:
            late[t] = s
    return gaps, late


def parity_check(src: Sources, live_conn, w0: int, w1: int, now_ms: int, replay: Optional[Callable] = None,
                 budget_min: float = REPLAY_BUDGET_MIN, log=None, extra_ctx: Optional[Callable] = None) -> dict:
    """Replay the day and compare it with the record. ``replay(cfg_raw, w0, w1, live_bars, seed, taker_fee)`` returns
    a livereplay.ReplayResult (tests inject one); default: livereplay on Binance."""
    from . import livereplay as LR
    if live_conn is None:
        return {"error": f"페이퍼 봇 DB({src.paper_db})를 못 읽음"}
    cfg, cfg_src = combo_config(src, live_conn)
    if cfg is None:
        return {"error": "페이퍼 봇 설정을 못 읽음"}
    _ts, run = get_state(live_conn, "combo_run")
    taker = (run or {}).get("taker_fee")
    seed_key = "day:" + _dt.datetime.fromtimestamp(w0 / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")
    _sts, seed = get_state(live_conn, seed_key)
    bars = read_live_bars(src.rule_db, w0, w1 + 12 * H1)
    if replay is None:
        def replay(cfg_raw, a, b, live_bars, seed, taker_fee):
            m = LR.BinanceMarket(cache=src.cache)
            try:
                return LR.replay_day(cfg_raw, m, a, b, live_bars=live_bars, seed=seed, taker_fee=taker_fee,
                                     now_ms=now_ms, deadline_s=budget_min * 60, log=log)
            finally:
                m.close()
    try:
        res = replay(cfg, w0, w1, bars, seed, taker)
    except LR.MarketDown as exc:
        return {"error": f"바이낸스에 연결하지 못해 다시 계산을 못 했습니다({str(exc)[:120]})", "down": True}
    except Exception as exc:  # noqa: BLE001  a fault of this check, not of the bots: the rest of the message still goes
        import traceback
        traceback.print_exc()
        return {"error": f"다시 계산 중 오류({type(exc).__name__}: {str(exc)[:120]}); 개발자에게 알려 주세요",
                "crash": True}
    from .livereplay import outcomes_of, signals_of, trades_of
    live_sig = signals_of(live_conn, w0, w1)
    live_out = outcomes_of(live_conn, ACCOUNT)
    live_tr = [t for t in trades_of(live_conn, ACCOUNT, live_out)
               if w0 <= t["entry_time"] < w1 or (t["entry_time"] < w0 <= t["exit_time"])]
    _ats, acc = get_state(live_conn, "accounts")
    live_open = None
    p = ((acc or {}).get("engines", {}).get(ACCOUNT) or {}).get("position")
    if p and int(p["entry_time"]) < w1:
        live_open = {"entry_time": int(p["entry_time"]), "symbol": p["symbol"], "side": int(p["side"]),
                     "strategy": (p.get("signal") or {}).get("strategy_id"),
                     "tf": (p.get("signal") or {}).get("timeframe")}
    rep_tr = [t for t in res.trades if t["entry_time"] < w1]
    rep_open = res.open_position if (res.open_position and res.open_position["entry_time"] < w1) else None
    ctx = Context(live_signals=live_sig, replay_signals=res.signals, live_outcomes=live_out, source=res.source,
                  seeded=res.seeded, replay_end=res.end, live_last=_ats, w0=w0)
    if run and _ts is not None and w0 - 6 * H1 <= int(_ts) <= w1 + 6 * H1:
        ctx.restarts.append(int(_ts))
    try:
        ctx.alerts = [(int(a), lv, tx) for a, lv, tx in live_conn.execute(
            "SELECT ts, level, text FROM alerts WHERE ts >= ? AND ts < ? AND level != 'INFO' ORDER BY ts",
            (w0, w1 + H1))]
    except sqlite3.Error:
        pass
    ctx.bar_gaps, ctx.bar_late = bar_quality(bars, w0, w1)
    ctx.live_busy = [(t["entry_time"], t["exit_time"]) for t in trades_of(live_conn, ACCOUNT)
                     if t["exit_time"] >= w0 - DAY]
    if live_open:
        ctx.live_busy.append((live_open["entry_time"], now_ms))
    ctx.replay_busy = [(t["entry_time"], t["exit_time"]) for t in res.trades]
    if res.open_position:
        ctx.replay_busy.append((res.open_position["entry_time"], res.end))
    waiting = {(s["strategy"], s["symbol"], s["side"]) for s in res.signals if s["status"] in ("WAITING", "BROKE")}
    ctx.prebreak = {(s["bar_close"], s["symbol"], s["side"]) for s in live_sig
                    if s["status"] == "SUBMITTED" and s.get("why") == "돌파 확인"
                    and (s["strategy"], s["symbol"], s["side"]) not in waiting}
    if extra_ctx is not None:
        extra_ctx(ctx, w0, w1)
    rep_sig = res.signals
    if res.end < w1:                                    # a replay cut short: compare only what it covered
        rep_sig = [s for s in rep_sig if s["bar_close"] <= res.end]
        live_sig = [s for s in live_sig if s["bar_close"] <= res.end]
        live_tr = [t for t in live_tr if t["entry_time"] < res.end]
        if live_open and live_open["entry_time"] >= res.end:
            live_open = None
    sig = compare_signals(live_sig, rep_sig, ctx)
    tr = compare_trades(live_tr, rep_tr, ctx, live_open, rep_open)
    notes = list(res.notes)
    labels = {s["strategy"] for s in live_sig}
    if labels and not labels <= {s["strategy"] for s in res.signals} and sig["extra_live"] and not sig["same"]:
        notes.append("기록의 매매법 이름이 지금 설정과 다름(설정이 그 사이 바뀐 듯)")
    if res.end < w1:
        notes.append(f"다시 계산이 {kst(res.end)}까지만 됨" + ("(시간 제한)" if not res.complete else ""))
    if res.source != "live":
        notes.append("규칙봇 1분봉 대신 바이낸스 1분봉으로 계산")
    return {"signals": sig, "trades": tr, "notes": notes, "source": res.source, "seeded": res.seeded,
            "elapsed_s": res.elapsed_s, "end": res.end, "config": cfg_src, "errors": res.errors[:10],
            "flags": parity_flags(sig, tr), "brackets": res.brackets}


def exec_report(ex: ExecInfo, paper: list, w0: int, w1: int, now_ms: int) -> dict:
    """One executor's part: costs of the trades closed in the day, its scoreboard, light and halt."""
    r = {"name": ex.name, "label": ex.label, "db": ex.db, "problem": ex.problem, "exists": os.path.exists(ex.db)}
    r["light"] = light_state(paper, ex.light_n, ex.light_min)
    conn = open_ro(ex.db)
    if conn is None:
        r["missing"] = True
        return r
    try:
        trades = exec_trades(conn)
        closed = [t for t in trades if t.get("exit_ts") is not None]
        day = [t for t in closed if w0 <= int(t["exit_ts"]) < w1]
        rows = [cost_row(ex, t, match_paper(t, paper, ex.account), exec_fills(conn, t["key"])) for t in day]
        r["costs"] = rows
        r["cost"] = cost_summary(rows, ex.fee)
        pn = [float(t["pnl"] or 0) for t in closed]
        r["trades"] = len(closed)
        r["wins"] = sum(1 for x in pn if x > 0)
        r["pnl"] = sum(pn)
        r["day_trades"] = len(day)
        r["day_pnl"] = sum(float(t["pnl"] or 0) for t in day)
        bts, bot = get_state(conn, "bot")
        _mts, meta = get_state(conn, "meta")
        risk = (bot or {}).get("risk") or {}
        r["halted"] = bool(risk.get("halted"))
        r["halt_reason"] = risk.get("halt_reason") or ""
        r["state_ts"] = bts
        r["trade_open"] = (bot or {}).get("trade")
        r["live_since"] = (meta or {}).get("live_since") or (meta or {}).get("since")
        first, last = exec_equity(conn)
        r["equity"] = (last or {}).get("equity", risk.get("last_equity"))
        r["start"] = ex.budget if ex.budget is not None else ((first or {}).get("equity"))
        r["transfers"] = float((last or {}).get("transfers") or risk.get("transfers") or 0.0)
        r["peak"] = risk.get("peak_equity")
        skips = exec_events(conn, "light_red")
        r["light_skips"] = len({(e["data"] or {}).get("key", e["ts"]) for e in skips})
        r["light_skips_day"] = len({(e["data"] or {}).get("key", e["ts"]) for e in skips if w0 <= e["ts"] < w1})
    finally:
        conn.close()
    r["kill_file"] = os.path.exists(ex.kill_file)
    return r


def paper_report(conn, w0: int, w1: int) -> dict:
    trades = paper_trades(conn, ACCOUNT)
    s = win_stats(trades)
    s["last20"] = win_stats(trades[-20:]) if len(trades) >= 20 else None
    s["last40"] = win_stats(trades[-40:]) if len(trades) >= 40 else None
    s["day"] = win_stats([t for t in trades if w0 <= t["exit_time"] < w1])
    s["first40"] = win_stats(trades[:CHECK_N]) if len(trades) >= CHECK_N else None
    _ts, acc = get_state(conn, "accounts")
    eng = ((acc or {}).get("engines") or {})
    s["wallet"] = (eng.get(ACCOUNT) or {}).get("wallet")
    flip = paper_trades(conn, FLIP_ACCOUNT)
    s["flip"] = win_stats(flip) if flip or FLIP_ACCOUNT in eng else None
    s["trades"] = trades
    return s


def shadow_report(pattern: str) -> list:
    out = []
    for path in sorted(glob.glob(pattern)):
        base = os.path.basename(path)[:-3]
        conn = open_ro(path)
        if conn is None:
            out.append({"name": base, "label": SHADOW_NAMES.get(base, base), "missing": True})
            continue
        try:
            tr = paper_trades(conn, ACCOUNT)
        finally:
            conn.close()
        s = win_stats(tr)
        s["last20"] = win_stats(tr[-20:]) if len(tr) >= 20 else None
        out.append({"name": base, "label": SHADOW_NAMES.get(base, base), **s})
    return out


def checkpoint_line(p: dict) -> str:
    rule = "거래 40번에서 88% 이상이면 늘리기 검토 / 82~88% 계속 지켜보기 / 82% 미만 멈추고 다시 생각"
    n = p["n"]
    if n < CHECK_N:
        now = f", 지금 {p['wins']}/{n}승 {p['rate']:.0%}" if n else ""
        return f"- 판단: {rule} → {CHECK_N - n}번 남음{now}"
    f = p["first40"]
    verdict = ("늘리기 검토" if f["rate"] >= GROW - 1e-9 else "계속 지켜보기" if f["rate"] >= KEEP - 1e-9
               else "멈추고 다시 생각")
    tail = f" · 최근 40번 {p['last40']['rate']:.0%}" if p.get("last40") else ""
    return f"- 판단(첫 40번): {f['wins']}승 {f['rate']:.1%} → {verdict}{tail}"


def score_lines(paper: Optional[dict], execs: list, shadows: list) -> list:
    out = ["성적표(시작부터)"]
    small = False
    if paper is None:
        out.append("- 페이퍼: DB를 못 읽음")
    else:
        line = f"- 페이퍼: 거래 {paper['n']}번 · {paper['wins']}승"
        if paper["n"]:
            line += f"({paper['rate']:.0%})"
        if paper.get("last20"):
            line += f" · 최근 20번 {paper['last20']['rate']:.0%}"
        if paper.get("last40"):
            line += f" · 최근 40번 {paper['last40']['rate']:.0%}"
        line += f" · 손익 {usd(paper['pnl'])}"
        d = paper["day"]
        if d["n"]:
            line += f" (어제 {d['n']}번 {d['wins']}승 {usd(d['pnl'])})"
        out.append(line)
        small = small or paper["n"] < SMALL
    for r in execs:
        if r.get("missing"):
            out.append(f"- {r['label']}: 기록 없음({'아직 시작 전' if not r.get('exists') else '읽을 수 없음'})")
            continue
        n = r.get("trades", 0)
        line = f"- {r['label']}: 거래 {n}번 · {r.get('wins', 0)}승"
        if n:
            line += f"({r['wins'] / n:.0%})"
        line += f" · 실현 {usd(r.get('pnl', 0.0))}"
        if r.get("equity") is not None:
            line += f" · 잔고 {money(r['equity'])}"
        line += " · " + (f"멈춤({r['halt_reason'][:60]})" if r.get("halted") else "정상")
        out.append(line)
        sk = f" · 신호등이 거른 진입 {r.get('light_skips', 0)}번" + \
            (f"(어제 {r['light_skips_day']}번)" if r.get("light_skips_day") else "")
        out.append(f"  {light_text(r['light'])}{sk}")
        if r.get("kill_file"):
            out.append("  비상 정지 파일(STOP)이 있음: 새 진입 없음")
        small = small or n < SMALL
    if paper is not None:
        f = paper.get("flip")
        if f is not None:
            out.append(f"- 동전 쌍둥이(참고): 거래 {f['n']}번 · {f['wins']}승"
                       + (f"({f['rate']:.0%})" if f["n"] else "") + f" · 손익 {usd(f['pnl'])}")
        out.append(checkpoint_line(paper))
    for s in shadows:
        if s.get("missing"):
            out.append(f"- {s['label']}(참고): 못 읽음")
            continue
        out.append(f"- {s['label']}(참고): 거래 {s['n']}번 · {s['wins']}승" + (f"({s['rate']:.0%})" if s["n"] else "")
                   + (f" · 최근 20번 {s['last20']['rate']:.0%}" if s.get("last20") else "") + f" · 손익 {usd(s['pnl'])}")
    if small:
        out.append(f"※ {SMALL}번 미만은 표본이 작아 승률은 참고만 하세요")
    return out


def cost_lines(execs: list) -> list:
    out = ["실제 비용(어제 닫힌 실거래, 페이퍼 가격 대비 +가 불리)"]
    for r in execs:
        if r.get("missing"):
            continue
        c = r.get("cost") or {}
        if not c.get("n"):
            out.append(f"- {r['label']}: 어제 닫힌 거래 없음")
            continue
        parts = []
        if c.get("entry_bps") is not None:
            parts.append(f"진입 {c['entry_bps']:+.1f}bps")
        if c.get("exit_bps") is not None:
            parts.append(f"청산 {c['exit_bps']:+.1f}bps")
        if c.get("fee_rate") is not None:
            parts.append(f"수수료 {c['fee_rate']:.3%}(가정 {c['assumed_fee']:.3%})")
        else:
            parts.append("수수료 체결 기록 아직 없음")
        parts.append(f"펀딩 {usd(c['funding'])}")
        line = f"- {r['label']} {c['n']}번 {usd(c['pnl'])}: " + " · ".join(parts)
        out.append(line)
        if c.get("unmeasured"):
            out.append(f"  {c['unmeasured']}번은 체결 기록이 없어 가격 비교 못 함")
    return out


def week_lines(out_conn, day: str, w1: int, execs: list, paper: Optional[dict], ex_infos: list,
               parity: dict) -> list:
    """Mondays: the 7 days that ended at this check's end (this check's own rows included before they are saved)."""
    a = w1 - 7 * DAY
    today = {r["name"]: r.get("costs", []) for r in execs}
    lines = [f"지난 7일({kst_day(a)} 09:00 ~ {kst_day(w1)} 09:00)"]
    if paper is not None:
        wk = win_stats([t for t in paper["trades"] if a <= t["exit_time"] < w1])
        lines.append(f"- 페이퍼: 거래 {wk['n']}번 · {wk['wins']}승" + (f"({wk['rate']:.0%})" if wk["n"] else "")
                     + f" · 손익 {usd(wk['pnl'])}")
    for ex in ex_infos:
        conn = open_ro(ex.db)
        if conn is None:
            continue
        try:
            tr = [t for t in exec_trades(conn) if t.get("exit_ts") is not None and a <= int(t["exit_ts"]) < w1]
        finally:
            conn.close()
        pn = [float(t["pnl"] or 0) for t in tr]
        line = f"- {ex.label}: 거래 {len(tr)}번 · {sum(1 for x in pn if x > 0)}승 · 실현 {usd(sum(pn))}"
        rows = list(today.get(ex.name, []))
        if out_conn is not None:
            try:
                cur = out_conn.execute("SELECT entry_bps, exit_bps, commission, notional FROM costs WHERE exchange = ? "
                                       "AND exit_ts >= ? AND exit_ts < ? AND day != ?", (ex.name, a, w1, day))
                rows += [{"entry_bps": r[0], "exit_bps": r[1], "commission": r[2], "notional": r[3]}
                         for r in cur.fetchall()]
            except sqlite3.Error:
                pass
        ins = [r["entry_bps"] for r in rows if r.get("entry_bps") is not None]
        outs = [r["exit_bps"] for r in rows if r.get("exit_bps") is not None]
        if ins or outs:
            line += (f" · 평균 진입 {sum(ins) / len(ins):+.1f}" if ins else " · 진입 -") + \
                (f" / 청산 {sum(outs) / len(outs):+.1f}bps" if outs else " / 청산 -")
        nt = sum(float(r["notional"]) for r in rows if r.get("notional") and r.get("commission") is not None)
        if nt:
            cm = sum(float(r["commission"]) for r in rows if r.get("notional") and r.get("commission") is not None)
            line += f" · 수수료 {cm / nt:.3%}"
        lines.append(line)
    days, bad = 1, int(bool(parity.get("flags")))
    if out_conn is not None:
        try:
            got = out_conn.execute("SELECT day, report FROM days WHERE day >= ? AND day < ? AND day != ?",
                                   (utc_date(a), utc_date(w1), day)).fetchall()
        except sqlite3.Error:
            got = []
        for _d, rep in got:
            days += 1
            try:
                if (json.loads(rep).get("parity") or {}).get("flags"):
                    bad += 1
            except (ValueError, TypeError):
                pass
    lines.append(f"- 대조: 점검한 {days}일 중 이유를 모르는 차이가 있던 날 {bad}일")
    return lines


def utc_date(ms: int) -> str:
    return _dt.datetime.fromtimestamp(int(ms) / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")


def compose(day: str, w0: int, w1: int, parity: dict, paper: Optional[dict], execs: list, shadows: list,
            week: Optional[list]) -> tuple[str, str, list]:
    """(level, text, loud reasons)."""
    loud = []
    if parity.get("flags"):
        loud.append(f"대조에서 이유를 모르는 차이 {parity['flags']}개")
    for r in execs:
        if r.get("halted"):
            loud.append(f"{r['label']} 실행기 멈춤")
        for f in (r.get("cost") or {}).get("flags", []):
            loud.append(f"{r['label']} {f}")
    span = f"{kst_day(w0)} 09:00 ~ {kst_day(w1)} 09:00"
    if loud:
        lines = [f"실거래 일일 점검 · 확인할 것 {len(loud)}개", span, ""] + [f"- {x}" for x in loud] + [""]
    else:
        lines = ["📋 실거래 일일 점검 · " + ("이상 없음" if not parity.get("error") else "대조는 못 함"), span, ""]
    lines += parity_lines(parity) + [""] + cost_lines(execs) + [""] + score_lines(paper, execs, shadows)
    if week:
        lines += [""] + week
    nxt = []
    if parity.get("flags"):
        nxt.append("대조 차이: sudo -u paperbot /opt/paperbot/venv/bin/python -m paperbot.livecheck show 결과를 "
                   "개발자에게 보내 주세요")
    if any((r.get("cost") or {}).get("flags") for r in execs):
        nxt.append("비용: 거래소 앱의 체결 내역(가격·수수료)과 비교해 보세요")
    if any(r.get("halted") for r in execs):
        nxt.append("멈춘 실행기: 이유를 확인한 뒤 사람이 풀어야 합니다(executor clear-halt, docs/live1019-start-ko.md)")
    if nxt:
        lines += ["", "다음 할 일"] + [f"- {x}" for x in nxt]
    from .notify import CRITICAL, INFO
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3880] + "\n…(나머지: python -m paperbot.livecheck show)"
    return (CRITICAL if loud else INFO), text, loud


# ====================================================================== livecheck.db
SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    day TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    w0 INTEGER NOT NULL,
    w1 INTEGER NOT NULL,
    level TEXT NOT NULL,
    loud INTEGER NOT NULL,
    text TEXT NOT NULL,
    report TEXT NOT NULL,
    sent INTEGER
);
CREATE TABLE IF NOT EXISTS parity (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    verdict TEXT NOT NULL,
    t INTEGER NOT NULL,
    symbol TEXT,
    side INTEGER,
    strategy TEXT,
    live TEXT,
    replay TEXT,
    why TEXT
);
CREATE INDEX IF NOT EXISTS parity_day ON parity (day);
CREATE TABLE IF NOT EXISTS costs (
    day TEXT NOT NULL,
    exchange TEXT NOT NULL,
    key TEXT NOT NULL,
    symbol TEXT,
    side INTEGER,
    entry_ts INTEGER,
    exit_ts INTEGER,
    paper_entry REAL,
    real_entry REAL,
    entry_bps REAL,
    paper_exit REAL,
    real_exit REAL,
    exit_bps REAL,
    notional REAL,
    commission REAL,
    fee_rate REAL,
    assumed_fee REAL,
    funding REAL,
    pnl REAL,
    paper_roe REAL,
    matched INTEGER,
    PRIMARY KEY (exchange, key)
);
CREATE TABLE IF NOT EXISTS scores (
    day TEXT NOT NULL,
    who TEXT NOT NULL,
    trades INTEGER,
    wins INTEGER,
    pnl REAL,
    equity REAL,
    data TEXT,
    PRIMARY KEY (day, who)
);
"""


def open_out(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def save_day(conn, day: str, now_ms: int, w0: int, w1: int, level: str, loud: list, text: str, report: dict,
             sent: Optional[bool]) -> None:
    conn.execute("DELETE FROM parity WHERE day = ?", (day,))
    conn.execute("DELETE FROM scores WHERE day = ?", (day,))
    conn.execute("INSERT OR REPLACE INTO days VALUES (?,?,?,?,?,?,?,?,?)",
                 (day, now_ms, w0, w1, level, len(loud), text, json.dumps(report, default=str, ensure_ascii=False),
                  None if sent is None else int(bool(sent))))
    p = report.get("parity") or {}
    for kind, part in (("trade", p.get("trades") or {}), ("signal", p.get("signals") or {})):
        for verdict in ("different", "missing_live", "extra_live"):
            for x in part.get(verdict, []):
                conn.execute("INSERT INTO parity VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (day, kind, verdict, int(x["t"]), x.get("symbol"), x.get("side"), x.get("strategy"),
                              json.dumps(x.get("live"), default=str), json.dumps(x.get("replay"), default=str),
                              x.get("why", "")))
    for r in report.get("executors", []):
        for c in r.get("costs", []):
            conn.execute("INSERT OR REPLACE INTO costs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (day, c["exchange"], c["key"], c["symbol"], c["side"], c["entry_ts"], c["exit_ts"],
                          c["paper_entry"], c["real_entry"], c["entry_bps"], c["paper_exit"], c["real_exit"],
                          c["exit_bps"], c["notional"], c["commission"], c["fee_rate"], c["assumed_fee"],
                          c["funding"], c["pnl"], c["paper_roe"], int(bool(c["matched"]))))
        if not r.get("missing"):
            conn.execute("INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?,?)",
                         (day, r["name"], r.get("trades"), r.get("wins"), r.get("pnl"), r.get("equity"),
                          json.dumps({"light": r.get("light"), "halted": r.get("halted"),
                                      "light_skips": r.get("light_skips")}, default=str)))
    pp = report.get("paper")
    if pp:
        conn.execute("INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?,?)",
                     (day, "paper", pp["n"], pp["wins"], pp["pnl"], pp.get("wallet"),
                      json.dumps({"last20": pp.get("last20"), "last40": pp.get("last40")}, default=str)))
    conn.commit()


# ====================================================================== commands
def _notifier():
    from .live import _notifier as live_notifier
    return live_notifier()


def run_check(src: Sources, day: Optional[str] = None, now_ms: Optional[int] = None, dry_run: bool = False,
              replay: Optional[Callable] = None, no_replay: bool = False, notifier=None,
              budget_min: float = REPLAY_BUDGET_MIN, log=None, extra_ctx: Optional[Callable] = None) -> dict:
    """The whole morning check. Returns {"level", "text", "loud", "report", "sent"}."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    day = day or default_day(now_ms)
    w0, w1 = window_of(day)
    infos = src.executors or load_executors()
    live_conn = open_ro(src.paper_db)
    try:
        if no_replay:
            parity = {"error": "이번에는 다시 계산을 건너뜀(--no-replay)"}
        else:
            parity = parity_check(src, live_conn, w0, w1, now_ms, replay=replay, budget_min=budget_min, log=log,
                                  extra_ctx=extra_ctx)
        paper = paper_report(live_conn, w0, w1) if live_conn is not None else None
    finally:
        if live_conn is not None:
            live_conn.close()
    trades = paper["trades"] if paper else []
    execs = [exec_report(ex, trades, w0, w1, now_ms) for ex in infos]
    shadows = shadow_report(src.shadow_glob)
    out_conn = None if dry_run else open_out(src.db)
    if dry_run and os.path.exists(src.db):
        out_conn = open_ro(src.db)
    try:
        monday = _dt.datetime.fromtimestamp(w1 / 1000 + 9 * 3600, _dt.timezone.utc).weekday() == 0
        week = week_lines(out_conn, day, w1, execs, paper, infos, parity) if monday else None
        level, text, loud = compose(day, w0, w1, parity, paper, execs, shadows, week)
        report = {"day": day, "w0": w0, "w1": w1, "parity": parity, "executors": execs, "shadows": shadows,
                  "paper": {k: v for k, v in (paper or {}).items() if k != "trades"} if paper else None,
                  "infos": [ex.__dict__ for ex in infos]}
        sent = None
        if not dry_run:
            n = notifier if notifier is not None else _notifier()
            got = n.send(level, text)
            sent = got is not False
            save_day(out_conn, day, now_ms, w0, w1, level, loud, text, report, sent)
    finally:
        if out_conn is not None:
            out_conn.close()
    return {"level": level, "text": text, "loud": loud, "report": report, "sent": sent}


def _sources(a) -> Sources:
    src = Sources(db=a.db, paper_db=a.paper_db, rule_db=a.rule_db, combo_config=a.combo_config, cache=a.cache,
                  shadow_glob=a.shadows)
    return src


def cmd_run(a) -> int:
    src = _sources(a)
    try:                                         # the paper bot's own database and the bars it reads
        with open(src.combo_config, encoding="utf-8") as fh:
            cc = json.load(fh)
    except (OSError, ValueError):
        cc = {}
    src.paper_db = a.paper_db or cc.get("db") or PAPER_DB
    src.rule_db = a.rule_db or cc.get("paper_db") or RULE_DB
    log = (lambda s: print(s, file=sys.stderr, flush=True)) if a.verbose else None
    out = run_check(src, day=a.day, dry_run=a.dry_run, no_replay=a.no_replay, budget_min=a.replay_budget_min,
                    log=log)
    print(f"[{out['level']}]")
    print(out["text"])
    if out["sent"] is False:
        print("텔레그램 전송 실패(기록은 저장함)", file=sys.stderr)
    return 0


def cmd_show(a) -> int:
    conn = open_ro(a.db)
    if conn is None:
        print(f"{a.db}가 없습니다(아직 점검 전)")
        return 1
    try:
        if a.day:
            r = conn.execute("SELECT day, level, text, sent FROM days WHERE day = ?", (a.day,)).fetchone()
        else:
            r = conn.execute("SELECT day, level, text, sent FROM days ORDER BY day DESC LIMIT 1").fetchone()
        if r is None:
            print("그날 점검 기록이 없습니다")
            return 1
        print(f"{r[0]} [{r[1]}] 텔레그램 {'보냄' if r[3] else '못 보냄' if r[3] == 0 else '-'}")
        print(r[2])
        rows = conn.execute("SELECT kind, verdict, t, symbol, side, strategy, why FROM parity WHERE day = ? "
                            "ORDER BY t", (r[0],)).fetchall()
        if rows:
            print("\n대조 차이 전체:")
            for kind, verdict, t, sym, side, strat, why in rows:
                print(f"  {kind} {verdict} {kst_dt(t)} {coin(sym or '')} {KO_SIDE.get(side, side)} {strat} {why or ''}")
    finally:
        conn.close()
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.livecheck", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--db", default=DEFAULT_DB, help="livecheck.db (its own results)")
        p.add_argument("--paper-db", default=None, help="the paper bot's database (default: combo.json's db)")
        p.add_argument("--rule-db", default=None, help="paper3.db, the rule bot's 1m bars (default: combo.json's)")
        p.add_argument("--combo-config", default=COMBO_CONFIG)
        p.add_argument("--cache", default=DEFAULT_CACHE, help="kline cache between nights")
        p.add_argument("--shadows", default=SHADOW_GLOB)
    r = sub.add_parser("run", help="the morning check of one day (09:00 to 09:00 KST)")
    common(r)
    r.add_argument("--day", default=None, help="YYYY-MM-DD: the KST date the checked day starts on (09:00)")
    r.add_argument("--dry-run", action="store_true", help="print only: no Telegram, nothing written")
    r.add_argument("--no-replay", action="store_true", help="skip the replay (대조)")
    r.add_argument("--replay-budget-min", type=float, default=REPLAY_BUDGET_MIN)
    r.add_argument("--verbose", action="store_true")
    s = sub.add_parser("show", help="print a stored check")
    s.add_argument("--db", default=DEFAULT_DB)
    s.add_argument("--day", default=None)
    a = ap.parse_args(argv)
    return {"run": cmd_run, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
