"""실거래 일일 점검: the morning check of the two real-money executors (Bybit $100, MEXC $100, owners 2026-10-19) that
follow the combined paper bot (paperbot/combo.py, account COMBO@mix).

    python -m paperbot.livecheck run [--day YYYY-MM-DD] [--dry-run] [--no-replay]
    python -m paperbot.livecheck show [--day YYYY-MM-DD]
    python -m paperbot.livecheck watch [--dry-run]

``run`` (deploy/paperbot-livecheck.timer, 09:10 KST) checks one trading day, 09:00 KST to 09:00 KST (00:00 to 00:00
UTC: the day boundary of the paper bot's daily snapshots), by default the one that ended at 09:00 today; ``--day``
names it by the KST date it starts on. It stores the result in its own SQLite file
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

``watch`` (deploy/paperbot-livewatch.timer, every 2 minutes; 실시간 감시) sends a LOUD message once per condition, with
the next step, and re-arms it when the condition clears (state in livecheck.db: watch, watch_log; a silent line when
it clears where that helps):
1. the paper bot entered more than 3 minutes ago (its open position, or a trade entered within the last hour and
   already closed) and an executor has no trade with that key although its signal light was green (or still building,
   fewer than N closed trades) at the entry, it was not halted, no kill file, it should be running and it was already
   live then ("실거래가 페이퍼를 따라가지 않았습니다", with what its own records say about that entry);
2. an executor's open position has no protective stop recorded in its state (its ``stop_algo_id``; the exchange is
   never called), or its state is older than 10 minutes while it should be running (systemd: started or enabled);
3. the paper bot's heartbeat (combo.py writes ``state.heartbeat`` every poll) is older than 10 minutes, or the newest 1m
   bar of the rule bot (paper3.db live_bars, the paper bot's data) is older than 5 minutes;
4. an executor's equity is 25% or more below its peak (its halt is at 50%; re-armed under 20%), and, silent, the first
   time its equity (deposits taken out) reaches +50% and +100% of its start.
Each pass also records what it saw (``seen``): the morning check reads the paper bot's stopped spans from it.

3부 (owners 2026-10-19, live improvement; compared with deploy/combo.live-ac.expected.json, the backtest reference:
"fit" = the whole period, "honest" = the twin fitted on 2020-24 read on unseen 2025-26):
① 손실 카드: each new losing COMBO@mix paper trade gets a card (livecheck.db loss_cards, for the dashboard; sent by the
   watcher a few minutes after the exit, once the executors closed): strategy / tf / setting number / type, coin,
   side, entry and exit KST, hold hours, net ROE, exit reason, stop type and distance, BTC 4h regime (reg5) and KST
   hour, the best ROE first reached (MFE), the strategy's fit and unseen win, its usual and worst loss and hours to
   stop, its backtest win in this regime and on this coin ("백테스트에서도 약한 자리" when that cell is weak), the place
   in the losing streak, and what each executor did (followed: net ROE and slippage; blocked by the light; not
   followed). One cause label: 실거래-페이퍼 차이 > 평소보다 큰 손실 > 연속 손실 N번째 > 백테스트에서도 약한 자리 > 정상 범위
   손실. Silent, loud when the loss is beyond the strategy's backtest worst, there is a live-paper gap, or it is the 2nd+
   loss in a row. Four hours after the exit the noise stop is checked (the price back at +11% ROE from the entry, from
   the rule bot's 1m bars) and shown in the next morning check, never as a message of its own.
② 기대 이탈 (watcher): the paper's last 20 / 40 wins under the honest 5th percentile: loud "기대 범위 밑"; under the fit
   5th percentile only: a silent note; a strategy with 3+ losses in its last 5 trades: a silent note; an executor that
   lost where the paper won, 2+ times in its last 20 trades: loud. Under 20 paper trades: "표본 작음", no alarm.
⑤ 멈춤 요약 (watcher): a halt of an executor gives one loud message: the rule (3 losses / drawdown 50% / STOP file /
   other), the trades before it with their card labels, the balance against the budget, the paper's last 20 and the
   light, and the owners' guide quoted as it is (start guide section 9 and the rules table, live-safety.md 3-5).
Server (watcher; the bots share the server with the experiments): free disk under 2 GB, MemAvailable under 500 MB:
loud, with the biggest memory users (systemctl show MemoryCurrent) and the experiments to stop first; the rule bot,
the paper bot and the executors are never suggested.

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

from .notify import CRITICAL, INFO

MIN = 60_000
H1 = 3_600_000
DAY = 86_400_000
KST_MS = 9 * H1
ACCOUNT = "COMBO@mix"
FLIP_ACCOUNT = "COMBOFLIP@mix"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_FILE = os.path.join(ROOT, "deploy", "combo.live-ac.expected.json")     # the backtest reference (3부)
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
                    "funding": d.get("funding"), "fees": d.get("fees"), "leverage": d.get("leverage"),
                    "stop_initial": d.get("stop_initial"), "mfe_price": d.get("mfe_price")})
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
    expected: str = EXPECTED_FILE


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
    ctx.down += down_spans(src.db, w0, w1)             # the watcher's own record of the paper bot's heartbeat
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
            week: Optional[list], cards: Optional[list] = None, drift: Optional[str] = None,
            notes: Optional[list] = None, now_ms: Optional[int] = None) -> tuple[str, str, list]:
    """(level, text, loud reasons). ``cards``: the loss cards of the day (3부 ①, already sent by the watcher; here one
    line each with the noise-stop result), ``drift``: the paper against the backtest's ranges (3부 ②)."""
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
    lines += parity_lines(parity) + [""] + cost_lines(execs)
    if cards:
        lines += ["", f"손실 카드 {len(cards)}장"] + [card_line(c, now_ms or w1) for c in cards[:MAX_LINES]]
        if len(cards) > MAX_LINES:
            lines.append(f"- 외 {len(cards) - MAX_LINES}장")
    sl = score_lines(paper, execs, shadows)
    if drift:
        at = next((i for i, ln in enumerate(sl) if ln.startswith("- 페이퍼")), 0)
        sl.insert(at + 1, drift)
    lines += [""] + sl + [f"※ {x}" for x in (notes or [])]
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
    conn.executescript(SCHEMA + WATCH_SCHEMA + LOSS_SCHEMA)
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


# ====================================================================== 실시간 감시 (watch, every 2 minutes)
FOLLOW_MS = 3 * MIN                # a paper entry older than this must have been followed
RECENT_MS = H1                     # ... also when the paper trade already closed within this
STOP_GRACE_MS = 60_000             # an open real position without a recorded stop after this
STALE_EXEC_MS = 10 * MIN           # executor state older than this while it should run
STALE_PAPER_MS = 10 * MIN          # the paper bot's heartbeat older than this
STALE_BARS_MS = 5 * MIN            # the rule bot's newest 1m bar older than this
DD_WARN, DD_CLEAR = 0.25, 0.20     # equity this far below its peak: loud; re-armed once back under DD_CLEAR
GOOD_STEPS = (0.5, 1.0)            # equity first +50% / +100% of its start: silent good news, once
SEEN_KEEP_MS = 60 * DAY
RUNNING = ("active", "activating", "reloading", "deactivating", "failed")
UNIT_KO = {"active": "켜져 있음", "activating": "다시 켜지는 중", "reloading": "설정 다시 읽는 중",
           "deactivating": "끄는 중", "failed": "오류로 멈춤", "enabled": "꺼져 있음(자동 시작은 켜짐)",
           "enabled-runtime": "꺼져 있음(자동 시작은 켜짐)", "inactive": "꺼져 있음"}
WATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS watch (
    key TEXT PRIMARY KEY,
    active INTEGER NOT NULL,
    first_ts INTEGER NOT NULL,
    last_ts INTEGER NOT NULL,
    cleared_ts INTEGER,
    level TEXT NOT NULL,
    text TEXT NOT NULL,
    recover TEXT,
    once INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watch_log (
    ts INTEGER NOT NULL,
    key TEXT NOT NULL,
    event TEXT NOT NULL,
    level TEXT,
    text TEXT,
    sent INTEGER
);
CREATE TABLE IF NOT EXISTS seen (
    ts INTEGER PRIMARY KEY,
    paper_hb INTEGER,
    paper_step INTEGER,
    rule_bar INTEGER,
    data TEXT
);
"""


@dataclass
class Cond:
    key: str
    level: str
    text: str
    recover: Optional[str] = None      # a silent line when it clears
    once: bool = False                 # good news: never sent again


def unit_state(unit: str) -> tuple[str, str]:
    """(ActiveState, UnitFileState) of a systemd unit, ('', '') when systemctl cannot be asked."""
    import subprocess
    out = []
    for verb in ("is-active", "is-enabled"):
        try:
            p = subprocess.run(["systemctl", verb, unit], capture_output=True, text=True, timeout=5)
            out.append((p.stdout or "").strip().splitlines()[0] if (p.stdout or "").strip() else "")
        except (OSError, subprocess.SubprocessError):
            out.append("")
    return out[0], out[1]


def should_run(ex: ExecInfo, units: Callable) -> tuple[bool, str]:
    """Is the executor meant to be running (started or enabled; a person's ``systemctl stop`` of a disabled unit is
    not)? Unknown (no systemctl): when its database exists."""
    active, enabled = units(ex.unit)
    if active in RUNNING or enabled in ("enabled", "enabled-runtime"):
        word = active if active in RUNNING else enabled
        return True, UNIT_KO.get(word, word)
    if not active and not enabled:
        return os.path.exists(ex.db), "알 수 없음"
    return False, UNIT_KO.get(active, active)


def _ago(now_ms: int, ts: Optional[int]) -> str:
    if ts is None:
        return "기록 없음"
    m = max(0, int(now_ms) - int(ts)) // MIN
    return f"{kst(ts)}, {m}분 전" if m < 120 else f"{kst_dt(ts)}, {m // 60}시간 전"


def _key_events(conn, key: str, limit: int = 3) -> list:
    try:
        return conn.execute("SELECT ts, kind, text FROM events WHERE data LIKE ? ORDER BY id DESC LIMIT ?",
                            (f'%"{key}"%', limit)).fetchall()
    except sqlite3.Error:
        return []


def _paper_entries(conn, now_ms: int) -> list:
    """The paper account's entries the executors should have followed by now: its open position and the trades
    entered (and already closed) within RECENT_MS, each entered more than FOLLOW_MS ago."""
    out = []
    _ts, acc = get_state(conn, "accounts")
    p = (((acc or {}).get("engines") or {}).get(ACCOUNT) or {}).get("position")
    if p:
        sig = p.get("signal") or {}
        out.append({"entry_time": int(p["entry_time"]), "symbol": p["symbol"], "side": int(p["side"]),
                    "strategy": sig.get("strategy_id", ""), "tf": sig.get("timeframe", ""), "open": True})
    try:
        rows = conn.execute("SELECT entry_time, symbol, data FROM trades WHERE account_id = ? AND exit_time >= ?",
                            (ACCOUNT, int(now_ms) - RECENT_MS)).fetchall()
    except sqlite3.Error:
        rows = []
    for et, sym, data in rows:
        try:
            d = json.loads(data)
        except (ValueError, TypeError):
            d = {}
        out.append({"entry_time": int(et), "symbol": sym, "side": int(d.get("side") or 0),
                    "strategy": d.get("strategy_id", ""), "tf": d.get("timeframe", ""), "open": False})
    return [e for e in out if int(now_ms) - e["entry_time"] > FOLLOW_MS
            and (e["open"] or e["entry_time"] >= int(now_ms) - RECENT_MS)]


def watch_conditions(src: Sources, now_ms: int, units: Callable = unit_state,
                     exists: Callable = os.path.exists, host: Optional["Host"] = None,
                     exp: Optional[dict] = None) -> tuple[list, set, dict]:
    """(active conditions, the key prefixes that could be judged this time, an observation for ``seen``)."""
    conds, judged, seen = [], set(), {"ts": int(now_ms), "exec": {}}
    infos = src.executors or load_executors()
    # ---- 3. the paper bot and its bars
    pc = open_ro(src.paper_db)
    paper, entries = None, []
    if pc is not None:
        try:
            hb, _h = get_state(pc, "heartbeat")
            step, _a = get_state(pc, "accounts")
            paper = paper_trades(pc, ACCOUNT)
            entries = _paper_entries(pc, now_ms)
        finally:
            pc.close()
        seen.update(paper_hb=hb, paper_step=step)
    else:
        hb = step = None
    hb = hb if hb is not None else step               # a database written before the heartbeat existed
    judged.add("paper_stale")
    if hb is None or now_ms - hb > STALE_PAPER_MS:
        conds.append(Cond("paper_stale", CRITICAL,
                          "페이퍼 봇이 10분 넘게 아무것도 쓰지 않습니다\n"
                          f"마지막 기록: {_ago(now_ms, hb)}\n"
                          "실행기는 페이퍼가 멈추면 새 진입을 하지 않습니다(열린 포지션은 거래소 손절이 지킴)\n"
                          "다음: sudo systemctl status paperbot-combo · sudo journalctl -u paperbot-combo -n 50",
                          recover="✅ 페이퍼 봇 기록이 다시 들어옵니다"))
    rc, bar = open_ro(src.rule_db), None
    if rc is not None:
        try:
            got = rc.execute("SELECT MAX(ts) FROM live_bars").fetchone()
            bar = int(got[0]) if got and got[0] is not None else None
        except sqlite3.Error:
            bar = None
        finally:
            rc.close()
    seen["rule_bar"] = bar
    judged.add("rule_bars")
    if bar is None or now_ms - (bar + MIN) > STALE_BARS_MS:
        conds.append(Cond("rule_bars", CRITICAL,
                          "규칙봇 1분봉이 5분 넘게 들어오지 않습니다\n"
                          + (f"마지막 1분봉: {_ago(now_ms, bar + MIN)}\n" if bar is not None else
                             f"1분봉 기록({src.rule_db})을 읽을 수 없습니다\n")
                          + "페이퍼 봇은 이 1분봉으로 움직입니다(멈추면 페이퍼도 실거래도 멈춤)\n"
                          "다음: sudo systemctl status paperbot-live3 · sudo journalctl -u paperbot-live3 -n 50",
                          recover="✅ 규칙봇 1분봉이 다시 들어옵니다"))
    # ---- per executor
    for ex in infos:
        run, why = should_run(ex, units)
        c = open_ro(ex.db)
        if c is None:
            judged.add(f"stale:{ex.name}")
            if run:
                conds.append(Cond(f"stale:{ex.name}", CRITICAL,
                                  f"{ex.label} 실행기 기록을 읽을 수 없습니다(파일 없음)\n"
                                  f"서비스 상태: {why}\n"
                                  f"다음: sudo systemctl status {ex.unit} · sudo journalctl -u {ex.unit} -n 50",
                                  recover=f"✅ {ex.label} 실행기 기록이 다시 들어옵니다"))
            continue
        try:
            bts, bot = get_state(c, "bot")
            _m, meta = get_state(c, "meta")
            keys = {r[0] for r in c.execute("SELECT key FROM trades")}
            risk = (bot or {}).get("risk") or {}
            seen["exec"][ex.name] = {"ts": bts, "equity": risk.get("last_equity"), "halted": bool(risk.get("halted"))}
            # 2a. state / heartbeat
            judged.add(f"stale:{ex.name}")
            if run and (bts is None or now_ms - bts > STALE_EXEC_MS):
                conds.append(Cond(f"stale:{ex.name}", CRITICAL,
                                  f"{ex.label} 실행기가 10분 넘게 기록을 남기지 않습니다\n"
                                  f"마지막 기록: {_ago(now_ms, bts)} · 서비스 상태: {why}\n"
                                  "꺼졌거나 멈춰 있으면 페이퍼를 따라가지 못합니다(열린 포지션은 거래소 손절이 지킴)\n"
                                  f"다음: sudo systemctl status {ex.unit} · sudo journalctl -u {ex.unit} -n 50",
                                  recover=f"✅ {ex.label} 실행기 기록이 다시 들어옵니다"))
            # 2b. an open position without a recorded stop
            t = (bot or {}).get("trade")
            judged.add(f"stop:{ex.name}:")
            if t and t.get("status") in ("open", "entering") and not t.get("stop_algo_id") \
                    and now_ms - int(t.get("entry_ts") or now_ms) > STOP_GRACE_MS:
                conds.append(Cond(f"stop:{ex.name}:{t.get('key')}", CRITICAL,
                                  f"{ex.label} 실거래 포지션에 손절 기록이 없습니다\n"
                                  f"{coin(t.get('symbol', ''))} {KO_SIDE.get(t.get('side'), '')} "
                                  f"{t.get('qty')} · 진입 {_ago(now_ms, t.get('entry_ts'))} · 상태 {t.get('status')}\n"
                                  "다음: 거래소 앱에서 이 포지션에 손절 주문이 걸려 있는지 바로 보세요. 없으면 앱에서 "
                                  "손절을 걸거나 포지션을 닫으세요",
                                  recover=f"✅ {ex.label} 포지션의 손절이 기록됐거나 포지션이 닫혔습니다"))
            # 4. drawdown and good news
            eq, peak = risk.get("last_equity"), risk.get("peak_equity")
            if eq is not None and peak:
                dd = 1 - float(eq) / float(peak)
                judged.add(f"dd:{ex.name}")
                prev = _active_before(src, f"dd:{ex.name}")
                if dd >= DD_WARN or (prev and dd >= DD_CLEAR):
                    conds.append(Cond(f"dd:{ex.name}", CRITICAL,
                                      f"{ex.label} 실거래 잔고가 최고점보다 {dd:.0%} 줄었습니다\n"
                                      f"잔고 {money(float(eq))} · 최고 {money(float(peak))}\n"
                                      f"{ex.max_dd:.0%}가 되면 실행기가 스스로 멈춥니다\n"
                                      f"다음: 두 분이 계속할지 정하세요(멈추려면 sudo systemctl stop {ex.unit}, "
                                      "포지션은 거래소 손절이 지킴)",
                                      recover=f"✅ {ex.label} 잔고가 최고점 대비 {DD_CLEAR:.0%} 안으로 돌아왔습니다"))
                start = ex.budget
                if start is None:
                    first, _l = exec_equity(c)
                    start = (first or {}).get("equity")
                if start:
                    gain = (float(eq) - float(risk.get("transfers") or 0.0)) / float(start) - 1
                    for step_ in GOOD_STEPS:
                        judged.add(f"good:{ex.name}:{step_:g}")
                        if gain >= step_:
                            conds.append(Cond(f"good:{ex.name}:{step_:g}", INFO,
                                              f"🎉 {ex.label} 실거래 잔고가 처음으로 시작보다 +{step_:.0%}가 됐습니다\n"
                                              f"잔고 {money(float(eq))} (시작 {money(float(start))})", once=True))
            # 3부 ⑤: a halt, summed up once
            judged.add(f"halt:{ex.name}:")
            if risk.get("halted"):
                conds.append(Cond(f"halt:{ex.name}:{int(risk.get('halted_ts') or 0)}", CRITICAL,
                                  halt_text(ex, risk, c, paper or [], src.db),
                                  recover=f"✅ {ex.label} 실행기 멈춤이 풀렸습니다"))
            # 3부 ②: lost where the paper won
            if paper is not None:
                judged.add(f"vs_paper:{ex.name}")
                bad = exec_vs_paper(c, paper)
                if len(bad) >= VS_PAPER_MAX:
                    conds.append(Cond(f"vs_paper:{ex.name}", CRITICAL,
                                      f"{ex.label} 실거래가 페이퍼가 이긴 거래에서 {len(bad)}번 졌습니다"
                                      f"(최근 {VS_PAPER_N}번 중)\n"
                                      + "\n".join(f"- {kst_dt(t['entry_time'])} {coin(t['symbol'])} "
                                                  f"{KO_SIDE.get(t['side'], '')} {t['strategy']}: 페이퍼 {usd(t['pnl'])}"
                                                  f", 실거래 {usd(p)}" for t, p in bad[:4]) + "\n"
                                      "체결 가격이나 손절 위치가 페이퍼와 다를 수 있습니다\n"
                                      "다음: 아침 점검의 실제 비용 줄과 손실 카드를 보고, 거래소 앱의 체결 내역과 비교하세요",
                                      recover=f"✅ {ex.label}: 페이퍼가 이긴 거래에서 진 실거래가 다시 1번 이하입니다"))
            # 1. the paper entries it should have followed
            if paper is not None:
                judged.add(f"follow:{ex.name}:")
                halted = bool(risk.get("halted"))
                kill = exists(ex.kill_file)
                since = (meta or {}).get("live_since") or (meta or {}).get("since")
                held = (bot or {}).get("trade") or {}
                for e in entries:
                    key = f"{ex.account}|{e['symbol']}|{e['entry_time']}"
                    if key in keys or held.get("key") == key:
                        continue
                    if not run or halted or kill or (since is not None and e["entry_time"] < int(since)):
                        continue
                    light = light_state(paper, ex.light_n, ex.light_min, at=e["entry_time"] + MIN)
                    if light["state"] == "red":
                        continue
                    told = _key_events(c, key)
                    said = " / ".join(str(x[2])[:90] for x in told) if told else "이 진입에 대한 기록 없음"
                    conds.append(Cond(
                        f"follow:{ex.name}:{key}", CRITICAL,
                        f"실거래가 페이퍼를 따라가지 않았습니다 · {ex.label}\n"
                        f"페이퍼 진입 {kst(e['entry_time'])} {coin(e['symbol'])} {KO_SIDE.get(e['side'], '')} "
                        f"{e['strategy']} {KO_TF.get(e['tf'], e['tf'])} ({(now_ms - e['entry_time']) // MIN}분 지남"
                        + (", 페이퍼는 이미 청산" if not e["open"] else "") + ")\n"
                        f"{light_text(light)} · 멈춤 아님 · 실행기 마지막 기록 {_ago(now_ms, bts)}\n"
                        f"실행기 기록: {said}\n"
                        f"다음: 거래소 앱에서 포지션을 확인하고 sudo journalctl -u {ex.unit} -n 50 으로 이유를 보세요"))
        finally:
            c.close()
    # 3부 ②: the paper against the backtest's ranges
    if paper is not None and exp is not None:
        dc, dj = drift_conditions(paper, exp)
        conds += dc
        judged |= dj
    # the server (same server as the experiments)
    if host is not None:
        hc, hj = health_conditions(host, src)
        conds += hc
        judged |= hj
    return conds, judged, seen


def _active_before(src: Sources, key: str) -> bool:
    conn = open_ro(src.db)
    if conn is None:
        return False
    try:
        r = conn.execute("SELECT active FROM watch WHERE key = ?", (key,)).fetchone()
        return bool(r and r[0])
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def run_watch(src: Sources, now_ms: Optional[int] = None, dry_run: bool = False, notifier=None,
              units: Callable = unit_state, exists: Callable = os.path.exists, host: Optional["Host"] = None) -> list:
    """One pass: first the loss cards of new losing paper trades (3부 ①; so a halt summary can name their causes),
    then every condition that became active is sent once (loud unless said otherwise) and every one that cleared is
    re-armed (with a silent line when it has one). Returns [(event, key, level, text)]."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    exp = load_expected(src.expected)
    out = []
    conn = None if dry_run else open_out(src.db)
    try:
        n = notifier if (notifier is not None or dry_run) else _notifier()
        # ---- loss cards (silent unless the card says otherwise); a dry run works on a copy in memory
        cc = conn
        if conn is None:
            cc = sqlite3.connect(":memory:")
            cc.executescript(LOSS_SCHEMA)
            ro = open_ro(src.db)
            if ro is not None:
                try:
                    cc.executemany("INSERT INTO loss_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   ro.execute("SELECT * FROM loss_cards").fetchall())
                except sqlite3.Error:
                    pass
                finally:
                    ro.close()
        send = (lambda lv, tx: True) if (dry_run or n is None) else n.send
        for card in cards_pass(src, cc, now_ms, exp, send=send):
            out.append(("card", card["key"], CRITICAL if card["loud"] else INFO, card["text"]))
        if conn is None:
            cc.close()
        # ---- conditions
        conds, judged, seen = watch_conditions(src, now_ms, units, exists, host=host, exp=exp)
        stored = {}
        if conn is not None:
            stored = {r[0]: {"active": r[1], "recover": r[2], "once": r[3]} for r in conn.execute(
                "SELECT key, active, recover, once FROM watch")}
        elif os.path.exists(src.db):
            ro = open_ro(src.db)
            if ro is not None:
                try:
                    stored = {r[0]: {"active": r[1], "recover": r[2], "once": r[3]} for r in ro.execute(
                        "SELECT key, active, recover, once FROM watch")}
                except sqlite3.Error:
                    stored = {}
                finally:
                    ro.close()
        now_keys = {c.key for c in conds}
        for c in conds:
            row = stored.get(c.key)
            if row and row["active"]:
                if conn is not None:
                    conn.execute("UPDATE watch SET last_ts = ? WHERE key = ?", (now_ms, c.key))
                continue
            ok = True if dry_run or n is None else (n.send(c.level, c.text) is not False)
            out.append(("fire", c.key, c.level, c.text))
            if conn is not None:
                conn.execute("INSERT INTO watch_log VALUES (?,?,?,?,?,?)", (now_ms, c.key, "fire", c.level, c.text,
                                                                            int(ok)))
                if ok:                       # not sent: tried again on the next pass
                    conn.execute("INSERT OR REPLACE INTO watch (key, active, first_ts, last_ts, cleared_ts, level, "
                                 "text, recover, once) VALUES (?,1,?,?,NULL,?,?,?,?)",
                                 (c.key, now_ms, now_ms, c.level, c.text, c.recover, int(c.once)))
        for key, row in stored.items():
            if not row["active"] or row["once"] or key in now_keys:
                continue
            if not any(key == j or (j.endswith(":") and key.startswith(j)) for j in judged):
                continue                     # not judged this time (a database unreadable): left as it is
            out.append(("clear", key, INFO, row["recover"] or ""))
            if row["recover"] and not dry_run and n is not None:
                n.send(INFO, row["recover"])
            if conn is not None:
                conn.execute("UPDATE watch SET active = 0, cleared_ts = ? WHERE key = ?", (now_ms, key))
                conn.execute("INSERT INTO watch_log VALUES (?,?,?,?,?,?)", (now_ms, key, "clear", INFO,
                                                                            row["recover"] or "", 1))
        if conn is not None:
            conn.execute("INSERT OR REPLACE INTO seen VALUES (?,?,?,?,?)",
                         (now_ms, seen.get("paper_hb"), seen.get("paper_step"), seen.get("rule_bar"),
                          json.dumps(seen.get("exec") or {})))
            conn.execute("DELETE FROM seen WHERE ts < ?", (now_ms - SEEN_KEEP_MS,))
            conn.execute("DELETE FROM watch WHERE active = 0 AND once = 0 AND cleared_ts < ?", (now_ms - 30 * DAY,))
            conn.execute("DELETE FROM watch_log WHERE ts < ?", (now_ms - SEEN_KEEP_MS,))
            conn.commit()
    finally:
        if conn is not None:
            conn.close()
    return out


def down_spans(db: str, a: int, b: int, stale_ms: int = 5 * MIN) -> list:
    """(from, to) spans in [a, b] when the watcher saw the paper bot's heartbeat older than ``stale_ms``."""
    conn = open_ro(db)
    if conn is None:
        return []
    try:
        rows = conn.execute("SELECT ts, paper_hb FROM seen WHERE ts >= ? AND ts <= ? ORDER BY ts",
                            (int(a) - H1, int(b) + H1)).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out, start = [], None
    for ts, hb in rows:
        stale = hb is None or ts - int(hb) > stale_ms
        if stale and start is None:
            start = int(hb) if hb is not None else int(ts)
        elif not stale and start is not None:
            out.append((start, int(hb)))
            start = None
    if start is not None:
        out.append((start, int(rows[-1][0])))
    return [(x, y) for x, y in out if y >= a and x <= b]


# ====================================================================== 3부: 손실 카드, 기대 이탈, 멈춤 요약, 서버 상태
GAP_BPS = 10.0                     # a followed executor's entry or exit this far from the paper's price: a live gap
CARD_WAIT_MS = 3 * MIN             # a card waits this long after the paper exit for the executors to close
CARD_MAX_WAIT_MS = 30 * MIN        # ... at most this long
CARD_SEND_MS = 2 * H1              # losses older than this when first seen get a stored card, no message
CARD_LOOKBACK_MS = 7 * DAY
NOISE_MS = 4 * H1                  # noise stop: within 4 hours after the exit ...
NOISE_ROE = 0.11                   # ... the price went back to +11% ROE from the entry (the ladder's first step)
NOISE_GIVE_UP_MS = 28 * H1         # no 1m bars by then: "확인 못 함"
WEAK_MIN_N = 5                     # a backtest cell with fewer trades is not judged
WEAK_GAP = 0.08                    # a cell this far below the strategy's own win (or under break-even) is weak
STRAT_LAST, STRAT_LOSSES = 5, 3    # one strategy with 3+ losses in its last 5 trades: a silent note
VS_PAPER_N, VS_PAPER_MAX = 20, 2   # an executor lost where the paper won, 2+ times in its last 20 trades: loud
DISK_MIN, DISK_CLEAR = 2 * 1024 ** 3, int(2.5 * 1024 ** 3)
MEM_MIN, MEM_CLEAR = 500 * 1024 ** 2, 700 * 1024 ** 2
PROTECTED_UNITS = ("paperbot-live3.service", "paperbot-combo.service", "paperbot-executor.service",
                   "paperbot-executor-mexc.service")
EXPERIMENT_HINTS = ("agents", "debate", "demobot", "demo", "candleague", "league", "shadow", "huntbot", "combo2")
UNIT_FAMILIES = ("paperbot-*", "candleague-*", "demobot-*", "huntbot-*")
REG5_KO = ("강상승", "약상승", "강하락", "약하락", "횡보")
HALT_KO = {"streak": "3연패(연속 손실 3번)", "drawdown": "낙폭 50%", "kill": "STOP 파일(비상 정지)"}
# quoted from docs/live1019-start-ko.md (the owners' rules and section 9) and docs/live-safety.md 3-5; a test keeps
# them equal to the guide
HALT_GUIDE = ("3연패나 낙폭 50% 멈춤은 이유가 있어서 걸린 것입니다. 두 분이 같이 원인을 본 뒤에 풉니다",
              "다시 켤지는 두 분이 정합니다: STOP 파일 지우기 → 실행기 끄기 → `clear-halt`")
LOSS_SCHEMA = """
CREATE TABLE IF NOT EXISTS loss_cards (
    key TEXT PRIMARY KEY,
    trade_id INTEGER,
    ts INTEGER NOT NULL,
    entry_time INTEGER,
    exit_time INTEGER,
    symbol TEXT,
    side INTEGER,
    strategy TEXT,
    tf TEXT,
    member_order INTEGER,
    roe REAL,
    exit_reason TEXT,
    label TEXT,
    loud INTEGER,
    streak INTEGER,
    weak INTEGER,
    noise INTEGER,
    noise_roe REAL,
    noise_ts INTEGER,
    text TEXT,
    sent INTEGER,
    data TEXT
);
CREATE INDEX IF NOT EXISTS loss_cards_exit ON loss_cards (exit_time);
"""


def load_expected(path: str = EXPECTED_FILE) -> Optional[dict]:
    """The backtest reference (deploy/combo.live-ac.expected.json), None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def ref_member(exp: Optional[dict], order: Optional[int], strategy: str, tf: str) -> Optional[dict]:
    """The reference of one setting: ``members`` is keyed by the config position from 0 (the paper bot's
    ``member_order`` counts from 1); only when strategy and timeframe agree."""
    if not exp or order is None:
        return None
    m = (exp.get("members") or {}).get(str(int(order) - 1))
    return m if m and m.get("strategy") == strategy and m.get("tf") == tf else None


def _cell(d: Optional[dict], k) -> Optional[list]:
    v = (d or {}).get(str(k))
    return v if isinstance(v, list) and len(v) == 2 else None


def weak_cell(cell: Optional[list], strat_win: Optional[float], break_even: float) -> bool:
    if not cell or cell[0] < WEAK_MIN_N:
        return False
    return cell[1] < break_even or (strat_win is not None and cell[1] <= strat_win - WEAK_GAP)


def entry_meta(conn, account: str, entry_time: int, symbol: str) -> dict:
    """The signal meta of the paper entry (outcomes ENTERED: member, member_order, rdims, rstop, stop_rule)."""
    try:
        r = conn.execute("SELECT data FROM outcomes WHERE account_id = ? AND status = 'ENTERED' AND step_ts = ? "
                         "AND symbol = ? ORDER BY id DESC LIMIT 1", (account, int(entry_time), symbol)).fetchone()
    except sqlite3.Error:
        return {}
    if r is None:
        return {}
    try:
        return (json.loads(r[0]).get("signal") or {}).get("meta") or {}
    except (ValueError, TypeError, AttributeError):
        return {}


def loss_streak(trades: list, t: dict) -> int:
    """Losses in a row ending with ``t`` (paper trades ordered by exit)."""
    n = 0
    for x in reversed([y for y in trades if (y["exit_time"], y["id"]) <= (t["exit_time"], t["id"])]):
        if x["pnl"] >= 0:
            break
        n += 1
    return n


def exec_outcome(ex: ExecInfo, conn, key: str, pt: dict) -> dict:
    """What one executor did with the paper trade ``key``: followed (its net ROE and slippage), blocked by the
    signal light, or not followed (its own words)."""
    if conn is None:
        return {"name": ex.name, "label": ex.label, "status": "no_record"}
    try:
        r = conn.execute("SELECT * FROM trades WHERE key = ?", (key,)).fetchone()
        cols = [c[0] for c in conn.execute("SELECT * FROM trades LIMIT 0").description]
    except sqlite3.Error:
        r = None
    if r is not None:
        et = dict(zip(cols, r))
        row = cost_row(ex, et, pt, exec_fills(conn, key))
        margin = (float(et.get("qty") or 0) * float(et.get("entry_price") or 0)) / max(int(et.get("leverage") or 1), 1)
        roe = (float(et["pnl"]) / margin) if (et.get("pnl") is not None and margin) else None
        return {"name": ex.name, "label": ex.label, "status": "followed" if et.get("exit_ts") else "open",
                "roe": roe, "pnl": et.get("pnl"), "entry_bps": row["entry_bps"], "exit_bps": row["exit_bps"],
                "exit_ts": et.get("exit_ts")}
    told = _key_events(conn, key)
    if any(k == "light_red" for _ts, k, _t in told):
        return {"name": ex.name, "label": ex.label, "status": "blocked"}
    return {"name": ex.name, "label": ex.label, "status": "not_followed",
            "why": " / ".join(str(x[2])[:80] for x in told) if told else ""}


def live_gap(outs: list, paper_exit: int) -> bool:
    """A followed executor whose trade went another way than the paper's (price far apart, a win, another exit)."""
    for o in outs:
        if o["status"] != "followed":
            continue
        if (o.get("pnl") or 0) > 0:
            return True
        if any(abs(o[k]) > GAP_BPS for k in ("entry_bps", "exit_bps") if o.get(k) is not None):
            return True
        if o.get("exit_ts") and abs(int(o["exit_ts"]) - int(paper_exit)) > EXIT_TOL_MS:
            return True
    return False


def build_card(t: dict, meta: dict, trades: list, exp: Optional[dict], outs: list) -> dict:
    """One losing paper trade against the backtest reference (fields kept for the dashboard)."""
    name, tf = t.get("strategy", ""), t.get("tf", "")
    order = meta.get("member_order")
    if order is None and "#" in str(meta.get("member", "")):
        try:
            order = int(str(meta["member"]).split("#")[1].split("~")[0])
        except ValueError:
            order = None
    st = ((exp or {}).get("strategies") or {}).get(name) or {}
    mem = ref_member(exp, order, name, tf)
    be = float((exp or {}).get("break_even_win") or 0.776)
    dims = meta.get("rdims") or {}
    reg5 = dims.get("reg5")
    hour = dims.get("hr", int(((int(t["entry_time"]) + KST_MS) // H1) % 24))
    sym_i = ((exp or {}).get("symbols") or list(EXP_SYMBOLS)).index(t["symbol"]) \
        if t["symbol"] in ((exp or {}).get("symbols") or list(EXP_SYMBOLS)) else None
    entry, lev, side = float(t.get("entry_price") or 0), int(t.get("leverage") or 1), int(t["side"])
    stop0 = t.get("stop_initial")
    rstop = meta.get("rstop")
    stop_type = (f"{rstop[0]}{float(rstop[1]):g}" if isinstance(rstop, list) and len(rstop) == 2
                 else (mem or {}).get("stop", ""))
    mfe = t.get("mfe_price")
    reg_cell = _cell(st.get("by_reg5"), reg5) if reg5 is not None else None
    sym_cell = _cell(st.get("by_sym"), sym_i) if sym_i is not None else None
    weak = [w for w, c in (("장세", reg_cell), ("코인", sym_cell)) if weak_cell(c, st.get("win"), be)]
    streak = loss_streak(trades, t)
    roe = float(t["roe"])
    worst, med = st.get("loss_roe_worst"), st.get("loss_roe_median")
    bigger = worst is not None and roe < float(worst)
    gap = live_gap(outs, t["exit_time"])
    if gap:
        label = "실거래-페이퍼 차이"
    elif bigger:
        label = "평소보다 큰 손실"
    elif streak >= 2:
        label = f"연속 손실 {streak}번째"
    elif weak:
        label = "백테스트에서도 약한 자리"
    else:
        label = "정상 범위 손실"
    honest = st.get("honest_2025_26")
    return {
        "key": f"{ACCOUNT}|{t['symbol']}|{t['entry_time']}", "trade_id": t["id"], "strategy": name, "tf": tf,
        "member_order": order, "member": meta.get("member"), "type": st.get("type", ""),
        "symbol": t["symbol"], "side": side, "entry_time": int(t["entry_time"]), "exit_time": int(t["exit_time"]),
        "hold_h": (int(t["exit_time"]) - int(t["entry_time"])) / H1, "roe": roe, "pnl": t["pnl"],
        "exit_reason": t.get("reason"), "stop_type": stop_type,
        "stop_pct": abs(entry - float(stop0)) / entry * 100 if (stop0 and entry) else None,
        "reg5": reg5, "hour": hour,
        "mfe_roe": side * (float(mfe) - entry) / entry * lev if (mfe and entry) else None,
        "fit_win": st.get("win"), "honest": honest if isinstance(honest, list) else None,
        "loss_median": med, "loss_worst": worst, "hours_median": st.get("hours_to_stop_median"),
        "hours_p90": st.get("hours_to_stop_p90"), "reg5_cell": reg_cell, "sym_cell": sym_cell, "weak": weak,
        "streak": streak, "fit_longest": (((exp or {}).get("overall") or {}).get("fit") or {}).get("streaks", {})
        .get("longest", 3), "honest_longest": (((exp or {}).get("overall") or {}).get("honest") or {})
        .get("streaks", {}).get("longest", 5), "executors": outs, "gap": gap, "bigger": bigger, "label": label,
        "loud": bool(bigger or gap or streak >= 2), "member_ref": mem}


EXP_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def _p(x: Optional[float], d: int = 1) -> str:
    return "-" if x is None else f"{x:+.{d}%}"


def card_text(c: dict) -> str:
    head = (f"손실 카드 · {c['strategy']} {KO_TF.get(c['tf'], c['tf'])}"
            + (f" (#{c['member_order']}" + (f", {c['type']}" if c.get("type") else "") + ")"
               if c.get("member_order") else ""))
    lines = [head if c["loud"] else "🧾 " + head,
             f"{coin(c['symbol'])} {KO_SIDE.get(c['side'], '')} · 진입 {kst_dt(c['entry_time'])} → 청산 "
             f"{kst(c['exit_time'])} ({c['hold_h']:.1f}시간)",
             f"순ROE {c['roe']:+.1%} · {KO_EXIT.get(c['exit_reason'], c['exit_reason'])}"
             + (f" · 손절 {c['stop_type']}" if c.get("stop_type") else "")
             + (f", 거리 {c['stop_pct']:.2f}%" if c.get("stop_pct") is not None else ""),
             (f"장세 {REG5_KO[int(c['reg5'])]} · " if c.get("reg5") is not None and 0 <= int(c["reg5"]) < 5 else "")
             + f"진입 {int(c['hour']):02d}시"
             + (f" · 먼저 {c['mfe_roe']:+.1%}까지 갔음" if c.get("mfe_roe") is not None else "")]
    if c.get("fit_win") is not None:
        hon = c.get("honest")
        lines.append(f"백테스트 승률 {c['fit_win']:.1%}"
                     + (f" (처음 보는 2025-26 {hon[1]:.0%}, {hon[0]}번)" if hon else "")
                     + (f" · 손실 보통 {c['loss_median']:+.0%} / 최악 {c['loss_worst']:+.0%}"
                        if c.get("loss_median") is not None and c.get("loss_worst") is not None else "")
                     + (f" · 손절까지 보통 {c['hours_median']:.1f}시간" if c.get("hours_median") is not None else ""))
        cells = []
        if c.get("reg5_cell"):
            cells.append(f"이 장세 {c['reg5_cell'][1]:.0%}({c['reg5_cell'][0]}번)")
        if c.get("sym_cell"):
            cells.append(f"이 코인 {c['sym_cell'][1]:.0%}({c['sym_cell'][0]}번)")
        if cells:
            lines.append(" · ".join(cells) + (" → 백테스트에서도 약한 자리" if c.get("weak") else ""))
    else:
        lines.append("백테스트 기준표에 이 매매법이 없음")
    lines.append(f"연속 손실 {c['streak']}번째 (백테스트 최장 {c['fit_longest']}번, 처음 보는 기간 {c['honest_longest']}번)")
    for o in c["executors"]:
        if o["status"] == "followed":
            lines.append(f"{o['label']}: 따라감, 순ROE {_p(o.get('roe'))}"
                         + (f", 진입 {o['entry_bps']:+.1f}bps" if o.get("entry_bps") is not None else "")
                         + (f" / 청산 {o['exit_bps']:+.1f}bps" if o.get("exit_bps") is not None else ""))
        elif o["status"] == "open":
            lines.append(f"{o['label']}: 따라감, 아직 닫는 중")
        elif o["status"] == "blocked":
            lines.append(f"{o['label']}: 신호등이 막음(따라가지 않음)")
        elif o["status"] == "not_followed":
            lines.append(f"{o['label']}: 따라가지 않음" + (f"({o['why']})" if o.get("why") else ""))
    lines.append(f"판정: {c['label']}")
    return "\n".join(lines)


def card_line(c: dict, now_ms: int) -> str:
    """The morning check's line of a card (with its noise-stop result once known)."""
    n = c.get("noise")
    if n is None:
        tail = "노이즈 손절 확인은 다음 점검에서" if now_ms < c["exit_time"] + NOISE_MS + 10 * MIN else "노이즈 확인 중"
    elif n == 1:
        tail = f"노이즈 손절(4시간 안에 {c['noise_roe']:+.1%}까지 돌아감)"
    elif n == 0:
        tail = "노이즈 손절 아님" + (f"(4시간 최고 {c['noise_roe']:+.1%})" if c.get("noise_roe") is not None else "")
    else:
        tail = "노이즈 손절 확인 못 함(1분봉 없음)"
    return (f"- {kst_dt(c['exit_time'])} {coin(c['symbol'])} {KO_SIDE.get(c['side'], '')} {c['strategy']} "
            f"{c['roe']:+.1%} · {c['label']} · {tail}")


def noise_check(rule_db: str, c: dict, lev: int, entry: float, now_ms: int) -> Optional[tuple]:
    """(noise 1/0/-1, best ROE from the entry within NOISE_MS after the exit) once the 4 hours are over; None while
    waiting. From the rule bot's 1m bars (paper3.db live_bars, read-only)."""
    a, b = int(c["exit_time"]), int(c["exit_time"]) + NOISE_MS
    if now_ms < b + 2 * MIN:
        return None
    conn = open_ro(rule_db)
    rows = []
    if conn is not None:
        try:
            rows = conn.execute("SELECT high, low FROM live_bars WHERE symbol = ? AND ts >= ? AND ts < ?",
                                (c["symbol"], a - a % MIN, b)).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
    if len(rows) < int(0.8 * NOISE_MS / MIN):
        return (-1, None) if now_ms > int(c["exit_time"]) + NOISE_GIVE_UP_MS else None
    side = int(c["side"])
    best = max(float(r[0]) for r in rows) if side > 0 else min(float(r[1]) for r in rows)
    roe = side * (best - entry) / entry * lev
    return (1 if roe >= NOISE_ROE else 0), roe


def cards_pass(src: Sources, out_conn, now_ms: int, exp: Optional[dict], send: Optional[Callable] = None,
               infos: Optional[list] = None, older_only: bool = False) -> list:
    """New losing paper trades -> cards (stored; sent when fresh and ``send`` is given), then the noise check of the
    cards whose 4 hours are over. ``older_only`` (the morning check): only losses too old for the watcher to send, so
    a fresh card keeps its message. Returns the new cards."""
    pc = open_ro(src.paper_db)
    if pc is None or out_conn is None:
        if pc is not None:
            pc.close()
        return []
    new = []
    infos = infos if infos is not None else (src.executors or load_executors())
    conns = {ex.name: open_ro(ex.db) for ex in infos}
    try:
        trades = paper_trades(pc, ACCOUNT)
        have = {r[0] for r in out_conn.execute("SELECT key FROM loss_cards")}
        for t in trades:
            if t["pnl"] >= 0 or t["exit_time"] < now_ms - CARD_LOOKBACK_MS or now_ms - t["exit_time"] < CARD_WAIT_MS:
                continue
            if older_only and now_ms - t["exit_time"] <= CARD_SEND_MS:
                continue
            key = f"{ACCOUNT}|{t['symbol']}|{t['entry_time']}"
            if key in have:
                continue
            outs = [exec_outcome(ex, conns[ex.name], key, t) for ex in infos]
            if any(o["status"] == "open" for o in outs) and now_ms - t["exit_time"] < CARD_MAX_WAIT_MS:
                continue                                      # an executor is still closing: next pass
            card = build_card(t, entry_meta(pc, ACCOUNT, t["entry_time"], t["symbol"]), trades, exp, outs)
            card["leverage"], card["entry_price"] = t.get("leverage"), t.get("entry_price")
            text = card_text(card)
            sent = None
            if send is not None and now_ms - t["exit_time"] <= CARD_SEND_MS:
                sent = send(CRITICAL if card["loud"] else INFO, text) is not False
                if not sent:
                    continue                                  # not stored: tried again on the next pass
            out_conn.execute("INSERT OR REPLACE INTO loss_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (key, t["id"], now_ms, card["entry_time"], card["exit_time"], card["symbol"],
                              card["side"], card["strategy"], card["tf"], card["member_order"], card["roe"],
                              card["exit_reason"], card["label"], int(card["loud"]), card["streak"],
                              int(bool(card["weak"])), None, None, None, text,
                              None if sent is None else int(sent), json.dumps(card, default=str, ensure_ascii=False)))
            card["text"] = text
            new.append(card)
        for key, data in out_conn.execute("SELECT key, data FROM loss_cards WHERE noise IS NULL").fetchall():
            c = json.loads(data)
            got = noise_check(src.rule_db, c, int(c.get("leverage") or 1), float(c.get("entry_price") or 0) or 1.0,
                              now_ms)
            if got is not None:
                out_conn.execute("UPDATE loss_cards SET noise = ?, noise_roe = ?, noise_ts = ? WHERE key = ?",
                                 (got[0], got[1], now_ms, key))
        out_conn.commit()
    finally:
        pc.close()
        for c in conns.values():
            if c is not None:
                c.close()
    return new


def stored_cards(out_conn, a: int, b: int) -> list:
    """Cards of losses that exited in [a, b), and older ones whose noise check finished in [a, b)."""
    if out_conn is None:
        return []
    try:
        rows = out_conn.execute("SELECT data, noise, noise_roe, noise_ts FROM loss_cards WHERE (exit_time >= ? AND "
                                "exit_time < ?) OR (exit_time < ? AND noise_ts >= ? AND noise_ts < ?) "
                                "ORDER BY exit_time", (a, b, a, a, b)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for data, noise, nroe, nts in rows:
        c = json.loads(data)
        c.update(noise=noise, noise_roe=nroe, noise_ts=nts)
        out.append(c)
    return out


# ---------------------------------------------------------------- ② 기대 이탈
def drift_state(paper: list, exp: Optional[dict]) -> dict:
    """The paper's last 20 / 40 wins against the backtest's 5th percentiles (fit, honest)."""
    out = {"n": len(paper), "windows": []}
    o = (exp or {}).get("overall") or {}
    for n in (20, 40):
        fit = ((o.get("fit") or {}).get(f"rolling{n}_wins") or {}).get("p5")
        hon = ((o.get("honest") or {}).get(f"rolling{n}_wins") or {}).get("p5")
        if len(paper) < n or fit is None or hon is None:
            out["windows"].append({"n": n, "wins": None, "fit_p5": fit, "honest_p5": hon, "state": "small"})
            continue
        wins = sum(1 for t in paper[-n:] if t["pnl"] > 0)
        state = "below" if wins < hon else ("low" if wins < fit else "ok")
        out["windows"].append({"n": n, "wins": wins, "fit_p5": fit, "honest_p5": hon, "state": state})
    return out


def drift_line(d: dict) -> str:
    if d["n"] < 20:
        return f"- 기대 범위: 표본 작음({d['n']}번, 20번부터 봄)"
    parts = []
    for w in d["windows"]:
        if w["state"] == "small":
            continue
        word = {"ok": "범위 안", "low": "맞춘 백테스트 하위 5% 밑", "below": "기대 범위 밑"}[w["state"]]
        parts.append(f"최근 {w['n']}번 {w['wins']}승(백테스트 하위 5% {w['fit_p5']}승, 처음 보는 기간 "
                     f"{w['honest_p5']}승) {word}")
    return "- 기대 범위: " + " · ".join(parts)


def drift_conditions(paper: list, exp: Optional[dict]) -> tuple[list, set]:
    conds, judged = [], {"drift:", "drift_note:", "strat:"}
    d = drift_state(paper, exp)
    if exp is None:
        return conds, set()
    for w in d["windows"]:
        if w["state"] == "below":
            conds.append(Cond(f"drift:{w['n']}", CRITICAL,
                              f"기대 범위 밑 · 페이퍼 최근 {w['n']}번 {w['wins']}승\n"
                              f"처음 보는 기간(2025-26) 백테스트에서도 최근 {w['n']}번이 {w['honest_p5']}승보다 적은 때는 "
                              f"5%뿐이었습니다(맞춘 백테스트 하위 5%는 {w['fit_p5']}승)\n"
                              "신호등이 빨강이면 실거래는 이미 따라가지 않습니다. 손실 카드들의 판정을 같이 보세요",
                              recover=f"✅ 페이퍼 최근 {w['n']}번 승리가 다시 기대 범위 안입니다"))
        elif w["state"] == "low":
            conds.append(Cond(f"drift_note:{w['n']}", INFO,
                              f"📉 참고: 페이퍼 최근 {w['n']}번 {w['wins']}승 · 맞춘 백테스트의 하위 5%({w['fit_p5']}승) "
                              f"밑, 처음 보는 기간 하위 5%({w['honest_p5']}승) 위"))
    by: dict = {}
    for t in paper:
        by.setdefault(t.get("strategy", ""), []).append(t)
    for name, ts in sorted(by.items()):
        last = ts[-STRAT_LAST:]
        lost = sum(1 for t in last if t["pnl"] < 0)
        if len(last) >= STRAT_LOSSES and lost >= STRAT_LOSSES:
            conds.append(Cond(f"strat:{name}", INFO,
                              f"📉 참고: {name} 최근 {len(last)}번 중 {lost}번 손실"
                              + (f" (백테스트 승률 {exp['strategies'][name]['win']:.0%})"
                                 if name in (exp.get("strategies") or {}) else "")))
    return conds, judged


def exec_vs_paper(c, paper: list) -> list:
    """The executor's last VS_PAPER_N closed trades it lost where its paper trade won: [(paper trade, pnl)]."""
    by = {f"{ACCOUNT}|{t['symbol']}|{t['entry_time']}": t for t in paper}
    try:
        rows = c.execute("SELECT key, pnl FROM trades WHERE exit_ts IS NOT NULL AND pnl IS NOT NULL "
                         "ORDER BY exit_ts DESC LIMIT ?", (VS_PAPER_N,)).fetchall()
    except sqlite3.Error:
        return []
    return [(by[k], float(p)) for k, p in rows if k in by and float(p) < 0 and by[k]["pnl"] > 0]


# ---------------------------------------------------------------- ⑤ 멈춤 원인 요약
def halt_rule(risk: dict) -> str:
    kinds = list(risk.get("halt_kinds") or [])
    reason = str(risk.get("halt_reason") or "")
    if not kinds:
        if "연속 손실" in reason:
            kinds.append("streak")
        if "낙폭" in reason:
            kinds.append("drawdown")
        if "비상 정지" in reason or "STOP" in reason:
            kinds.append("kill")
    words = [HALT_KO[k] for k in kinds if k in HALT_KO]
    return " + ".join(words) if words else f"기타({reason[:80] or '이유 기록 없음'})"


def halt_text(ex: ExecInfo, risk: dict, c, paper: list, out_db: str) -> str:
    halted_ts = int(risk.get("halted_ts") or 0)
    kinds = set(risk.get("halt_kinds") or [])
    try:
        rows = c.execute("SELECT key, symbol, side, entry_ts, exit_ts, pnl, qty, entry_price, leverage FROM trades "
                         "WHERE exit_ts IS NOT NULL" + (" AND exit_ts <= ?" if halted_ts else "") +
                         " ORDER BY exit_ts DESC LIMIT 8", ((halted_ts + MIN,) if halted_ts else ())).fetchall()
    except sqlite3.Error:
        rows = []
    if "drawdown" in kinds and risk.get("peak_ts"):
        rows = [r for r in rows if int(r[4]) >= int(risk["peak_ts"])] or rows[:3]
    else:
        rows = rows[:3]
    labels = {}
    oc = open_ro(out_db)
    if oc is not None:
        try:
            labels = dict(oc.execute("SELECT key, label FROM loss_cards").fetchall())
        except sqlite3.Error:
            labels = {}
        finally:
            oc.close()
    by = {f"{ACCOUNT}|{t['symbol']}|{t['entry_time']}": t for t in paper}
    lines = [f"{ex.label} 실행기가 멈췄습니다 · 이유: {halt_rule(risk)}",
             f"멈춤 기록: {str(risk.get('halt_reason') or '-')[:120]}"]
    if rows:
        lines.append("멈추기 전 거래:")
        for key, sym, side, ets, xts, pnl, qty, px, lev in reversed(rows):
            margin = float(qty or 0) * float(px or 0) / max(int(lev or 1), 1)
            roe = f"{float(pnl) / margin:+.1%}" if (pnl is not None and margin) else "-"
            pt = by.get(key)
            lines.append(f"- {kst_dt(int(xts))} {coin(sym)} {KO_SIDE.get(side, '')} "
                         f"{(pt or {}).get('strategy', '')} {roe} ({usd(float(pnl or 0))})"
                         + (f" · 카드: {labels[key]}" if key in labels else ""))
    eq = risk.get("last_equity")
    if eq is not None and ex.budget:
        lines.append(f"잔고 {money(float(eq))} (시작 {money(ex.budget)}, {float(eq) / ex.budget - 1:+.1%})")
    elif eq is not None:
        lines.append(f"잔고 {money(float(eq))}")
    last20 = paper[-20:]
    if len(paper) >= 20:
        w = sum(1 for t in last20 if t["pnl"] > 0)
        lines.append(f"페이퍼 최근 20번 {w}승({w / 20:.0%}) · {light_text(light_state(paper, ex.light_n, ex.light_min))}")
    else:
        lines.append(f"페이퍼 거래 {len(paper)}번(표본 작음) · {light_text(light_state(paper, ex.light_n, ex.light_min))}")
    lines += ["안내서(live1019-start-ko.md):"] + [f"- {g}" for g in HALT_GUIDE]
    lines += ["풀 때(live-safety.md 3-5, 두 분이 같이 원인을 본 뒤):",
              "sudo rm /var/lib/paperbot/STOP   (비상 정지 파일이 있었다면)",
              f"sudo systemctl stop {ex.unit}",
              "cd /opt/crypto-bot-research && sudo -u paperbot-exec /opt/paperbot/venv/bin/python -m paperbot.executor "
              f"clear-halt --config {ex.config} --by 이름 --note \"이유\"",
              f"sudo systemctl start {ex.unit}"]
    return "\n".join(lines)


# ---------------------------------------------------------------- 서버 상태
def _disk_free(path: str) -> Optional[int]:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    return int(st.f_bavail) * int(st.f_frsize)


def _mem_available() -> Optional[int]:
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for ln in fh:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _unit_memory() -> list:
    """[(unit, bytes)] of the active paperbot-family services (systemctl list-units / show -p MemoryCurrent)."""
    import subprocess
    try:
        p = subprocess.run(["systemctl", "list-units", "--type=service", "--state=active", "--plain", "--no-legend",
                            *UNIT_FAMILIES], capture_output=True, text=True, timeout=10)
        units = [ln.split()[0] for ln in (p.stdout or "").splitlines() if ln.strip()]
        if not units:
            return []
        p = subprocess.run(["systemctl", "show", "-p", "Id", "-p", "MemoryCurrent", *units], capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    out, cur = [], {}
    for ln in (p.stdout or "").splitlines() + [""]:
        if not ln.strip():
            if cur.get("Id") and str(cur.get("MemoryCurrent", "")).isdigit():
                out.append((cur["Id"], int(cur["MemoryCurrent"])))
            cur = {}
            continue
        k, _, v = ln.partition("=")
        cur[k] = v.strip()
    return out


@dataclass
class Host:
    """The server, read-only: free disk (statvfs), MemAvailable (/proc/meminfo), the services' memory (systemctl)."""
    disk_free: Callable[[str], Optional[int]] = _disk_free
    mem_available: Callable[[], Optional[int]] = _mem_available
    unit_memory: Callable[[], list] = _unit_memory
    paths: tuple = ("/", "/var/lib/paperbot")


def _gb(x: int) -> str:
    return f"{x / 1024 ** 3:.1f}GB" if x >= 1024 ** 3 else f"{x / 1024 ** 2:.0f}MB"


def experiment(unit: str) -> bool:
    return unit not in PROTECTED_UNITS and any(h in unit for h in EXPERIMENT_HINTS)


def memory_lines(units: list) -> list:
    """The biggest memory users, the experiments to stop first; the bots that trade are never suggested."""
    if not units:
        return ["(서비스별 메모리를 읽지 못함: systemctl status 로 보세요)"]
    top = sorted(units, key=lambda u: -u[1])[:6]
    lines = ["많이 쓰는 순서: " + ", ".join(f"{u.removesuffix('.service')} {_gb(m)}" for u, m in top)]
    first = [u for u, _m in sorted(units, key=lambda u: -u[1]) if experiment(u)][:3]
    if first:
        lines.append("먼저 끌 것(실험): sudo systemctl stop " + " ".join(u.removesuffix(".service") for u in first))
    else:
        lines.append("끌 만한 실험 서비스가 켜져 있지 않습니다. 서버를 키우거나 개발자에게 알려 주세요")
    lines.append("끄면 안 됨: paperbot-live3, paperbot-combo, paperbot-executor, paperbot-executor-mexc")
    return lines


def health_conditions(host: Host, src: Sources) -> tuple[list, set]:
    conds, judged, seen_dev = [], set(), set()
    low = []
    for path in host.paths:
        try:
            dev = os.stat(path).st_dev
        except OSError:
            dev = path
        if dev in seen_dev:
            continue
        seen_dev.add(dev)
        free = host.disk_free(path)
        if free is None:
            continue
        judged.add("disk")
        prev = _active_before(src, "disk")
        if free < DISK_MIN or (prev and free < DISK_CLEAR):
            low.append((path, free))
    if low:
        conds.append(Cond("disk", CRITICAL,
                          "디스크 부족 · " + ", ".join(f"{p} 남은 공간 {_gb(f)}" for p, f in low) + "\n"
                          "꽉 차면 DB 기록이 실패해 페이퍼 봇과 실행기가 멈춥니다\n"
                          "다음: sudo du -xh /var/lib/paperbot --max-depth 2 | sort -h | tail 로 큰 것을 보고, 실험 "
                          "기록이나 오래된 백업(/var/backups/paperbot)부터 정리하세요(거래 DB는 지우지 마세요)",
                          recover="✅ 디스크 공간이 다시 넉넉합니다"))
    mem = host.mem_available()
    if mem is not None:
        judged.add("memory")
        prev = _active_before(src, "memory")
        if mem < MEM_MIN or (prev and mem < MEM_CLEAR):
            conds.append(Cond("memory", CRITICAL,
                              f"메모리 부족 · 남은 메모리 {_gb(mem)}\n"
                              "모자라면 리눅스가 아무 프로그램이나 강제로 끕니다(페이퍼 봇이나 실행기일 수도 있음)\n"
                              + "\n".join(memory_lines(host.unit_memory())),
                              recover="✅ 메모리 여유가 다시 생겼습니다"))
    return conds, judged


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
        exp = load_expected(src.expected)
        notes = reference_notes(exp, src)
        if not dry_run:                       # cards the watcher has not made yet (stored, not sent) and noise checks
            cards_pass(src, out_conn, now_ms, exp, send=None, infos=infos, older_only=True)
        cards = stored_cards(out_conn, w0, w1)
        drift = drift_line(drift_state(trades, exp)) if (paper is not None and exp is not None) else None
        level, text, loud = compose(day, w0, w1, parity, paper, execs, shadows, week, cards=cards, drift=drift,
                                    notes=notes, now_ms=now_ms)
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


def reference_notes(exp: Optional[dict], src: Sources) -> list:
    """The backtest reference missing, or made for another config than the one in /etc/paperbot/combo.json."""
    if exp is None:
        return [f"백테스트 기준표({src.expected})를 못 읽어 손실 카드·기대 범위 비교 없음"]
    try:
        import hashlib
        with open(src.combo_config, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return []
    if exp.get("config_sha256") and sha != exp["config_sha256"]:
        return ["백테스트 기준표가 지금 설정 파일과 다름(설정이 바뀌면 기준표도 다시 만들어야 함): 카드의 숫자는 참고만"]
    return []


def _sources(a) -> Sources:
    src = Sources(db=a.db, paper_db=a.paper_db, rule_db=a.rule_db, combo_config=a.combo_config, cache=a.cache,
                  shadow_glob=a.shadows, expected=a.expected)
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


def cmd_watch(a) -> int:
    src = _sources(a)
    try:
        with open(src.combo_config, encoding="utf-8") as fh:
            cc = json.load(fh)
    except (OSError, ValueError):
        cc = {}
    src.paper_db = a.paper_db or cc.get("db") or PAPER_DB
    src.rule_db = a.rule_db or cc.get("paper_db") or RULE_DB
    out = run_watch(src, dry_run=a.dry_run, host=Host())
    for event, key, level, text in out:
        print(f"[{event} {level}] {key}\n{text}\n")
    if a.dry_run and not out:
        print("새로 울릴 알람 없음")
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
        p.add_argument("--expected", default=EXPECTED_FILE, help="the backtest reference (combo.live-ac.expected.json)")
    r = sub.add_parser("run", help="the morning check of one day (09:00 to 09:00 KST)")
    common(r)
    r.add_argument("--day", default=None, help="YYYY-MM-DD: the KST date the checked day starts on (09:00)")
    r.add_argument("--dry-run", action="store_true", help="print only: no Telegram, nothing written")
    r.add_argument("--no-replay", action="store_true", help="skip the replay (대조)")
    r.add_argument("--replay-budget-min", type=float, default=REPLAY_BUDGET_MIN)
    r.add_argument("--verbose", action="store_true")
    w = sub.add_parser("watch", help="one pass of the real-time watcher (every 2 minutes by its timer)")
    common(w)
    w.add_argument("--dry-run", action="store_true", help="print what would be sent: no Telegram, nothing written")
    s = sub.add_parser("show", help="print a stored check")
    s.add_argument("--db", default=DEFAULT_DB)
    s.add_argument("--day", default=None)
    a = ap.parse_args(argv)
    return {"run": cmd_run, "watch": cmd_watch, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
