"""실거래 일일 점검: the morning check of the two real-money executors (Bybit $100, MEXC $100, owners 2026-10-19) that
follow the combined paper bot (paperbot/combo.py, account COMBO@mix).

    python -m paperbot.livecheck run [--day YYYY-MM-DD] [--dry-run] [--no-replay]
    python -m paperbot.livecheck show [--day YYYY-MM-DD]
    python -m paperbot.livecheck watch [--dry-run]
    python -m paperbot.livecheck preview
    python -m paperbot.livecheck chat-ids

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
   executor (trades, win rate, realised $ P&L, equity, halted or not, and only for an executor that runs the signal
   light (off in the live configs since owners 10-19): the light from the paper's last N closed trades and its own
   config's threshold, how many paper entries the light skipped), the coin-flip twin and the shadow paper bots
   (/var/lib/paperbot/combo/shadow-*.db) for reference, and the owners' 40-trade checkpoint (88% or more: consider
   more money; 82-88%: keep watching; under 82%: stop and rethink; only with the 5-year reference of the running
   config: none for 규칙봇 15). Mondays add the last 7 days.
   Samples under 20 trades are marked as small.
4. 못 탄 신호 (one quiet line, never loud): the day's signals the paper bot did not take and their virtual results per
   reason, and the paper trades the executors did not follow, next to the trades it took ("어제 못 탄 신호 n개(가상): 한 번에
   하나 a승 b패 · 연구 조건 c승 d패 · … · 실제로 탄 거래 x승 y패"; paperbot/livemissed.py morning_line on the watcher's
   ``missed`` table; nothing when the day has none). No message per signal.

``watch`` (deploy/paperbot-livewatch.timer, every minute; 실시간 감시) sends a LOUD message once per condition, with
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
4. an executor's equity is 25% or more below its peak (re-armed under 20%; the message names its own drawdown halt
   when its config has one, else says there is none: the live configs since owners 10-19), and, silent, the first
   time its equity (deposits taken out) reaches +50% and +100% of its start.
Each pass also records what it saw (``seen``): the morning check reads the paper bot's stopped spans from it.

3부 (owners 2026-10-19, live improvement; compared with deploy/combo.live-ac.expected.json, the backtest reference:
"fit" = the whole period, "honest" = the twin fitted on 2020-24 read on unseen 2025-26; a reference whose config_sha256
is not the running config file's is another bot's and is not used at all, ``ref_config_problem``: no card number, no
expected range, no 88% / 82% rule, one line saying why):
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
⑤ 멈춤 요약 (watcher): a halt of an executor gives one loud message: the rule (a loss streak / drawdown with the
   executor's own number, both off in the live configs since owners 10-19 / STOP file / other), the trades before it
   with their card labels, the balance against the budget, the paper's last 20 (and the light when it runs one), and
   the owners' guide (start guide section 9 and the rules table, live-safety.md 3-5; without those two halts a line
   that this halt was not one of them).
Server (watcher; the bots share the server with the experiments): free disk under 2 GB, MemAvailable under 500 MB:
loud, with the biggest memory users (systemctl show MemoryCurrent) and the experiments to stop first; the rule bot,
the paper bot and the executors are never suggested.

4부 (owners 10-19, "텔레그램 알림이 깔끔하게"): the watcher (every minute, about half a second a pass) also tells the
live trades, one message each, de-duplicated in livecheck.db (trade_msgs, live_state): 🟢 진입 (the paper entry and
each executor's answer: ✅ entered with its margin and stop, ⛔ blocked by its light, ⏸ halted, ⚠ did not follow;
sent once every executor answered or after 3 minutes), 🔒 the FIRST lock only, ✅ a winning exit (each executor's
P&L and balance, the day, the lights), ❌ a losing exit = its loss card; 🚦 a light that changes, 🏁 the 40th paper
trade, ▶️ / ⏹ an executor started or stopped on a signal; ⏳ a break signal waiting (once its result is known the same
message gets it as a last line: edited, never a second message), ⏸ / 🔔 the paper bot's entry pause (the weekend, a
macro release) starting / ending. Every message: a short first line (emoji, what, coin, side,
the key number), Korean labels, the strategy as name + Korean timeframe + type (never the member label), prices at
the coin's precision, money as $x.xx, ROE as +x.x%; alarms are CRITICAL (🚨, they ring with TELEGRAM_SOUND=critical)
and end with "지금 할 일:", everything else is INFO (silent); raw error text only on a last "자세히:" line. Where they
go: the units load /etc/paperbot/live-telegram.env after live.env (the live bot's own token from @BotFather and the
owners' private chats, comma-separated, in TELEGRAM_CHAT_*; paperbot/notify.py), so the rule bot's room keeps only the
rule bot. A new token there whose chats are still live.env's room (where the new bot is not), or an empty CRITICAL
chat line, reaches no one: after 10 minutes the watcher says so once through live.env's own bot (tg_pass), and
``show`` ends with where the live messages go. Of those two files only the Telegram lines are read.
``preview`` prints one sample of every message from a hand-made world (paperbot/livepreview.py; sends nothing);
``chat-ids`` lists the private chats the bot in effect has seen (live.env's token, then live-telegram.env's; getMe and
getUpdates; the token is never printed; sends nothing).

Read-only towards the bots: their databases are opened read-only (paperbot/livepnl.py ``open_ro``), the executors'
configs are read as plain JSON (never their key file), no exchange account is called and no order is sent.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .notify import CRITICAL, INFO, chat_ids

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
COMBO_CONFIG_ENV = "PAPERBOT_LIVE_COMBO_CONFIG"    # the running config's path when set (the dashboard's name, dash.env)
# A 5-year reference (expected.json, likely.json) whose config_sha256 is not the running config's: never shown as if it
# described that config (ref_config_problem).
REF_OTHER_CONFIG_KO = "이 설정의 5년 기준표가 없어요(지난 봇 기준표라 쓰지 않아요)"
PAPER_DB = "/var/lib/paperbot/combo/live-ac.db"
RULE_DB = "/var/lib/paperbot/paper3.db"
SHADOW_GLOB = "/var/lib/paperbot/combo/shadow-*.db"
SHADOW_NAMES = {"shadow-b": "그림자 B 안정형", "shadow-nocut": "그림자 끄는 구간 없음", "shadow-ac32": "그림자 32개"}
# (name, executor config, systemd unit, fallbacks when the config cannot be read: db, light N, light share; the live
# configs run without the signal light since owners 10-19 (deploy/executor.live-*.json "signal_light_n": 0))
EXECUTORS = (("bybit", "/etc/paperbot/executor.json", "paperbot-executor",
              "/var/lib/paperbot/exec/executor-bybit-live.db", 0, 0.85),
             ("mexc", "/etc/paperbot/executor-mexc.json", "paperbot-executor-mexc",
              "/var/lib/paperbot/exec/executor-mexc-live.db", 0, 0.90))
ASSUMED_FEE = {"bybit": 0.00055, "mexc": 0.0008, "binance": 0.0005}


def running_combo_config() -> str:
    """The config file the live paper bot runs: ``PAPERBOT_LIVE_COMBO_CONFIG`` when set, else /etc/paperbot/combo.json."""
    return os.environ.get(COMBO_CONFIG_ENV) or COMBO_CONFIG


EX_KO = {"bybit": "바이비트", "mexc": "MEXC", "binance": "바이낸스"}
KO_SIDE = {1: "롱", -1: "숏"}
KO_TF = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
KO_EXIT = {"SL": "손절", "LOCK": "계단 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산",
           "REV": "빠른 청산(반대 신호)", "TP": "익절", "END": "끝"}
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
                    "stop_initial": d.get("stop_initial"), "mfe_price": d.get("mfe_price"),
                    "lock_roe": d.get("lock_roe")})
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
    max_dd: Optional[float] = None  # its drawdown halt (risk.max_drawdown_pct); None: none (owners 10-19) or not known
    max_streak: Optional[int] = None    # its loss-streak halt (risk.max_consecutive_losses); None: none or not known
    max_loss: Optional[float] = None    # one stop-out's largest share of its equity (risk.max_loss_frac)
    problem: str = ""               # the config could not be read: the fallbacks are used

    @property
    def light_on(self) -> bool:
        return bool(self.light_n)

    @property
    def auto_halts(self) -> Optional[bool]:
        """Does it halt by itself on a losing run or a drawdown? None when its config could not be read."""
        if self.max_dd is not None or self.max_streak is not None:
            return True
        return None if self.problem else False

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
            if risk.get("max_consecutive_losses") is not None:
                e.max_streak = int(risk["max_consecutive_losses"])
            if risk.get("max_loss_frac") is not None:
                e.max_loss = float(risk["max_loss_frac"])
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
    combo_config: str = field(default_factory=running_combo_config)
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
        return {"error": "바이낸스에 연결하지 못해 다시 계산을 못 했습니다", "detail": str(exc)[:160], "down": True}
    except Exception as exc:  # noqa: BLE001  a fault of this check, not of the bots: the rest of the message still goes
        import traceback
        traceback.print_exc()
        return {"error": "다시 계산 중 오류가 났습니다. 개발자에게 알려 주세요",
                "detail": f"{type(exc).__name__}: {str(exc)[:140]}", "crash": True}
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
    s["pos_entry"] = ((eng.get(ACCOUNT) or {}).get("position") or {}).get("entry_time")
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


CHECK_NO_RULE_KO = "40번 판단 기준은 지난 봇의 5년 기준표로 정한 숫자라 이 설정에는 쓰지 않아요"


def checkpoint_line(p: dict, ref_ko: str = "") -> str:
    """The owners' 40-trade checkpoint in the morning check. ``ref_ko`` (the reference was made for another config,
    e.g. 규칙봇 15 from 10-20): '' (no line). The 40-trade 88% / 82% rule came from the old bot's 5-year reference and
    the paper account's first 40 trades are that bot's; the reference note (reference_notes) says once why there is no
    such comparison."""
    rule = "거래 40번에서 88% 이상이면 늘리기 검토 / 82~88% 계속 지켜보기 / 82% 미만 멈추고 다시 생각"
    n = p["n"]
    if ref_ko:
        return ""
    if n < CHECK_N:
        now = f", 지금 {p['wins']}/{n}승 {p['rate']:.0%}" if n else ""
        return f"- 판단: {rule} → {CHECK_N - n}번 남음{now}"
    f = p["first40"]
    verdict = ("늘리기 검토" if f["rate"] >= GROW - 1e-9 else "계속 지켜보기" if f["rate"] >= KEEP - 1e-9
               else "멈추고 다시 생각")
    tail = f" · 최근 40번 {p['last40']['rate']:.0%}" if p.get("last40") else ""
    return f"- 판단(첫 40번): {f['wins']}승 {f['rate']:.1%} → {verdict}{tail}"


def score_lines(paper: Optional[dict], execs: list, shadows: list, ref_ko: str = "") -> list:
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
        if (r.get("light") or {}).get("state", "off") != "off":       # no light (owners 10-19): no light line
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
        cp = checkpoint_line(paper, ref_ko)
        if cp:
            out.append(cp)
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
            notes: Optional[list] = None, now_ms: Optional[int] = None, rest: Optional[str] = None,
            missed: Optional[str] = None, ref_ko: str = "") -> tuple[str, str, list]:
    """(level, text, loud reasons). ``cards``: the loss cards of the day (3부 ①, already sent by the watcher; here one
    line each with the noise-stop result), ``drift``: the paper against the backtest's ranges (3부 ②), ``missed``: the
    day's not-entered signals in one quiet line (paperbot/livemissed.py morning_line; never loud), ``ref_ko``: the
    reference was made for another config (the checkpoint line without the old bot's rule)."""
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
    if rest:
        lines += [rest, ""]
    lines += parity_lines(parity) + [""] + cost_lines(execs)
    if cards:
        lines += ["", f"손실 카드 {len(cards)}장"] + [card_line(c, now_ms or w1) for c in cards[:MAX_LINES]]
        if len(cards) > MAX_LINES:
            lines.append(f"- 외 {len(cards) - MAX_LINES}장")
    if missed:
        lines += ["", missed]
    sl = score_lines(paper, execs, shadows, ref_ko)
    if drift:
        at = next((i for i, ln in enumerate(sl) if ln.startswith("- 페이퍼")), 0)
        sl.insert(at + 1, drift)
    lines += [""] + sl + [f"※ {x}" for x in (notes or [])]
    if week:
        lines += [""] + week
    nxt = []
    if parity.get("flags"):
        nxt.append("대조 차이 전체를 개발자에게 보내 주세요: sudo -u paperbot /opt/paperbot/venv/bin/python -m "
                   "paperbot.livecheck show")
    if any((r.get("cost") or {}).get("flags") for r in execs):
        nxt.append("거래소 앱의 체결 내역(가격·수수료)과 비교해 보세요")
    if any(r.get("halted") for r in execs):
        nxt.append("멈춘 실행기는 이유를 확인한 뒤 사람이 풉니다(clear-halt, docs/live1019-start-ko.md 9장)")
    if nxt:
        lines += [""] + [f"지금 할 일: {x}" for x in nxt]
    if parity.get("detail"):
        lines += ["", f"자세히: {parity['detail']}"]
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
    conn.executescript(SCHEMA + WATCH_SCHEMA + LOSS_SCHEMA + TRADE_SCHEMA + STATE_SCHEMA + TG_IDS_SCHEMA)
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


# ====================================================================== 실시간 감시 (watch, every minute)
FOLLOW_MS = 3 * MIN                # a paper entry older than this must have been followed
RECENT_MS = H1                     # ... also when the paper trade already closed within this
STOP_GRACE_MS = 60_000             # an open real position without a recorded stop after this
STALE_EXEC_MS = 10 * MIN           # executor state older than this while it should run
STALE_PAPER_MS = 10 * MIN          # the paper bot's heartbeat older than this
STALE_BARS_MS = 5 * MIN            # the rule bot's newest 1m bar older than this
RULE_UNIT = "paperbot-live3"       # the rule bot: it writes those 1m bars
RESTART_GRACE_MS = 10 * MIN        # the rule bot (re)started this recently (an update): its bars catch up first...
STALE_BARS_HARD_MS = 15 * MIN      # ...but never quiet once its newest bar is this old
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


def unit_started(unit: str) -> Optional[int]:
    """When a systemd unit last became active (epoch ms), None when systemctl cannot say."""
    import subprocess
    try:
        p = subprocess.run(["systemctl", "show", unit, "-p", "ActiveEnterTimestampMonotonic", "--value"],
                           capture_output=True, text=True, timeout=5)
        us = int((p.stdout or "").strip() or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return int(time.time() * 1000 - (time.monotonic() - us / 1e6) * 1000) if us > 0 else None


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
                     exp: Optional[dict] = None, started: Callable = unit_started) -> tuple[list, set, dict]:
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
                          "지금 할 일: sudo systemctl status paperbot-combo · sudo journalctl -u paperbot-combo -n 50",
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
    late = bar is None or now_ms - (bar + MIN) > STALE_BARS_MS
    up = started(RULE_UNIT) if late and bar is not None and units(RULE_UNIT)[0] == "active" else None
    if up is not None and 0 <= now_ms - up < RESTART_GRACE_MS and now_ms - (bar + MIN) <= STALE_BARS_HARD_MS:
        late = None                       # just restarted (an update): not judged while its bars catch up
    else:
        judged.add("rule_bars")
    if late:
        conds.append(Cond("rule_bars", CRITICAL,
                          "규칙봇 1분봉이 5분 넘게 들어오지 않습니다\n"
                          + (f"마지막 1분봉: {_ago(now_ms, bar + MIN)}\n" if bar is not None else
                             f"1분봉 기록({src.rule_db})을 읽을 수 없습니다\n")
                          + "페이퍼 봇은 이 1분봉으로 움직입니다(멈추면 페이퍼도 실거래도 멈춤)\n"
                          "지금 할 일: sudo systemctl status paperbot-live3 · sudo journalctl -u paperbot-live3 -n 50",
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
                                  f"지금 할 일: sudo systemctl status {ex.unit} · sudo journalctl -u {ex.unit} -n 50",
                                  recover=f"✅ {ex.label} 실행기 기록이 다시 들어옵니다"))
            continue
        try:
            bts, bot = get_state(c, "bot")
            _m, meta = get_state(c, "meta")
            keys = {r[0] for r in c.execute("SELECT key FROM trades")}
            if stopped_by_signal(c) is not None and units(ex.unit)[0] not in ("active", "activating", "reloading"):
                run, why = False, "끄라는 신호를 받아 꺼짐"          # a person's stop (or a restart): ⏹, no alarm
            risk = (bot or {}).get("risk") or {}
            seen["exec"][ex.name] = {"ts": bts, "equity": risk.get("last_equity"), "halted": bool(risk.get("halted"))}
            # 2a. state / heartbeat
            judged.add(f"stale:{ex.name}")
            if run and (bts is None or now_ms - bts > STALE_EXEC_MS):
                conds.append(Cond(f"stale:{ex.name}", CRITICAL,
                                  f"{ex.label} 실행기가 10분 넘게 기록을 남기지 않습니다\n"
                                  f"마지막 기록: {_ago(now_ms, bts)} · 서비스 상태: {why}\n"
                                  "꺼졌거나 멈춰 있으면 페이퍼를 따라가지 못합니다(열린 포지션은 거래소 손절이 지킴)\n"
                                  f"지금 할 일: sudo systemctl status {ex.unit} · sudo journalctl -u {ex.unit} -n 50",
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
                                  "지금 할 일: 거래소 앱에서 이 포지션에 손절 주문이 걸려 있는지 바로 보세요. 없으면 앱에서 "
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
                                      + dd_halt_words(ex),
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
                by_hand = set(risk.get("halt_kinds") or []) == {"kill"}       # the STOP file: a person's stop
                text = halt_text(ex, risk, c, paper or [], src.db)
                conds.append(Cond(f"halt:{ex.name}:{int(risk.get('halted_ts') or 0)}", INFO if by_hand else CRITICAL,
                                  ("⏹ " + text.replace("실행기가 멈췄습니다", "실행기 꺼짐 (사람이 끔)", 1)) if by_hand
                                  else text, recover=f"✅ {ex.label} 실행기 멈춤이 풀렸습니다"))
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
                                      "지금 할 일: 아침 점검의 실제 비용 줄과 손실 카드를 보고, 거래소 앱의 체결 내역과 비교하세요",
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
                        + (f"{light_text(light)} · " if light["state"] != "off" else "")
                        + f"멈춤 아님 · 실행기 마지막 기록 {_ago(now_ms, bts)}\n"
                        f"실행기 기록: {said}\n"
                        f"지금 할 일: 거래소 앱에서 포지션을 확인하고 sudo journalctl -u {ex.unit} -n 50 으로 이유를 보세요"))
        finally:
            c.close()
    # 3부 ②: the paper against the backtest's ranges
    if paper is not None and exp is not None:
        dc, dj = drift_conditions(paper, exp, lights=any(ex.light_on for ex in infos))
        conds += dc
        judged |= dj
    # the server (same server as the experiments)
    if host is not None:
        hc, hj = health_conditions(host, src)
        conds += hc
        judged |= hj
    return conds, judged, seen


def dd_halt_words(ex: ExecInfo) -> str:
    """The drawdown alarm's last lines: the executor's own drawdown halt when its config has one; none since owners
    10-19 (the live configs): said so, with both ways to stop; config unreadable: neither claimed."""
    stop = f"멈추려면 sudo systemctl stop {ex.unit}, 포지션은 거래소 손절이 지킴"
    if ex.max_dd is not None:
        return f"{ex.max_dd:.0%}가 되면 실행기가 스스로 멈춥니다\n지금 할 일: 두 분이 계속할지 정하세요({stop})"
    if ex.auto_halts is False:
        return ("잔고가 줄어도 실행기는 스스로 멈추지 않습니다(낙폭 멈춤 없음)\n"
                f"지금 할 일: 두 분이 계속할지 정하세요({stop} · 두 실행기 모두 바로 닫고 멈추려면 sudo touch {ex.kill_file})")
    return f"지금 할 일: 두 분이 계속할지 정하세요({stop})"


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
              units: Callable = unit_state, exists: Callable = os.path.exists, host: Optional["Host"] = None,
              tg: Optional[dict] = None, started: Callable = unit_started) -> list:
    """One pass: first the loss cards of new losing paper trades (3부 ①; so a halt summary can name their causes),
    then every condition that became active is sent once (loud unless said otherwise) and every one that cleared is
    re-armed (with a silent line when it has one). ``tg``: the Telegram files (tg_files(); read when None).
    Returns [(event, key, level, text)]."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    exp, ref_ko = usable_expected(src)          # another config's reference: no comparison numbers (ref_config_problem)
    out = []
    conn = None if dry_run else open_out(src.db)
    try:
        n = notifier if (notifier is not None or dry_run) else _notifier()
        # ---- trade messages and loss cards; a dry run works on a copy in memory
        cc = conn
        if conn is None:
            cc = sqlite3.connect(":memory:")
            cc.executescript(LOSS_SCHEMA + TRADE_SCHEMA + STATE_SCHEMA + TG_IDS_SCHEMA)
            ro = open_ro(src.db)
            if ro is not None:
                for table, n_cols in (("loss_cards", 22), ("trade_msgs", 6), ("live_state", 3), ("tg_ids", 4)):
                    try:
                        cc.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * n_cols)})",
                                       ro.execute(f"SELECT * FROM {table}").fetchall())
                    except sqlite3.Error:
                        pass
                ro.close()
        send = (lambda lv, tx: True) if (dry_run or n is None) else n.send
        # the live bot's own Telegram setup first: when it cannot reach the owners, live.env's bot says so
        t = tg if tg is not None else tg_files()
        if dry_run or n is None:
            send_base = send
        elif notifier is not None:
            send_base = n.send               # a notifier handed in (tests, the preview) carries both
        else:
            send_base = tg_base_send(t)
        out += tg_pass(cc, now_ms, t, send_base, send)
        for kind, key, level, text in trade_pass(src, cc, now_ms, exp, send, units=units):
            out.append((kind, key, level, text))
        # ⏳ with the Telegram notifier's message ids when it gives them (a notifier without them: no result edit)
        live = not (dry_run or n is None)
        out += wait_pass(src, cc, now_ms, send, send_ids=getattr(n, "send_ids", None) if live else None)
        out += wait_result_pass(src, cc, now_ms, getattr(n, "edit", None) if live else (lambda lv, ids, tx: True))
        out += pause_pass(src, cc, now_ms, send)
        for card in cards_pass(src, cc, now_ms, exp, send=send, ref_ko=ref_ko):
            if card.get("sent"):
                out.append(("card", card["key"], CRITICAL if card["loud"] else INFO, card["text"]))
        out += changes_pass(src, cc, now_ms, exp, send, ref_ko=ref_ko)
        try:                                        # 못 탄 신호 성적: view only, bounded (60 sims / 10 s), sends nothing
            from .livemissed import missed_pass
            missed_pass(src, cc, now_ms)
        except Exception as exc:  # noqa: BLE001  never in the way of the alarms below
            print(f"missed_pass: {type(exc).__name__}: {exc}", file=sys.stderr)
        if conn is None:
            cc.close()
        # ---- conditions
        conds, judged, seen = watch_conditions(src, now_ms, units, exists, host=host, exp=exp, started=started)
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
CARD_WAIT_MS = 3 * MIN             # a card waits for the executors to close, at most this long after the paper exit
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
HALT_KO = {"streak": "3연패(연속 손실 3번)", "drawdown": "낙폭 50%", "kill": "STOP 파일(비상 정지)",
           "wrong_side": "방향이 반대인 포지션(실행기 안전장치)", "gate": "실거래 관문 확인 실패(실행기 안전장치)"}
# quoted from docs/live1019-start-ko.md (the owners' rules and section 9) and docs/live-safety.md 3-5; a test keeps
# them equal to the guide
HALT_GUIDE = ("3연패나 낙폭 50% 멈춤은 이유가 있어서 걸린 것입니다. 두 분이 같이 원인을 본 뒤에 풉니다",
              "다시 켤지는 두 분이 정합니다: STOP 파일 지우기 → 실행기 끄기 → `clear-halt`")
# an executor without the loss-streak and drawdown halts (owners 10-19, 규칙봇 15) halted by the STOP file or one of
# its own safety stops (a wrong-side or unknown position, a stop it could not place ...): the first line is true of
# such a halt whatever the config says; the second is the guide's
HALT_GUIDE_NO_AUTO = ("이 멈춤은 연패·낙폭 때문이 아닙니다(비상 정지 파일이나 실행기 안전장치). 두 분이 같이 원인을 본 뒤에 풉니다",
                      HALT_GUIDE[1])
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


class RefConfigMismatch(ValueError):
    """A 5-year reference made for another config than the one the live bot runs (``ref_config_problem``)."""


def ref_config_problem(ref: Optional[dict], combo_config_path: Optional[str] = None) -> str:
    """'' when the 5-year reference ``ref`` (deploy/combo.live-ac.expected.json, or likely.json with its ``source``) may
    be shown against the running config, else the Korean reason (REF_OTHER_CONFIG_KO). The one guard of livecheck,
    liveimprove and the dashboard: a reference whose ``config_sha256`` is not the sha256 of the running config file's
    bytes (``combo_config_path``, default ``running_combo_config()``) describes another bot. A config file that cannot
    be read (a development machine, the tests) or a reference without the hash: usable, as before."""
    if not isinstance(ref, dict):
        return ""
    want = ref.get("config_sha256")
    if not want and isinstance(ref.get("source"), dict):
        want = ref["source"].get("config_sha256")
    if not want:
        return ""
    try:
        with open(combo_config_path or running_combo_config(), "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""
    return "" if sha == str(want).strip().lower() else REF_OTHER_CONFIG_KO


def usable_expected(src: Sources) -> tuple[Optional[dict], str]:
    """(the backtest reference, '') or (None, why): None also when it was made for another config than
    ``src.combo_config`` (ref_config_problem), so no loss card, expected range or checkpoint line compares the bot
    with another bot's numbers."""
    exp = load_expected(src.expected)
    why = ref_config_problem(exp, src.combo_config)
    return (None, why) if why else (exp, "")


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


def build_card(t: dict, meta: dict, trades: list, exp: Optional[dict], outs: list, ref_ko: str = "") -> dict:
    """One losing paper trade against the backtest reference (fields kept for the dashboard). Without a reference
    (``exp`` None) no backtest number at all, not even the streak lengths; ``ref_ko`` says why (usable_expected)."""
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
        "streak": streak, "fit_longest": None if exp is None else (((exp or {}).get("overall") or {}).get("fit") or {})
        .get("streaks", {}).get("longest", 3), "honest_longest": None if exp is None else
        (((exp or {}).get("overall") or {}).get("honest") or {}).get("streaks", {}).get("longest", 5),
        "executors": outs, "gap": gap, "bigger": bigger, "label": label,
        "loud": bool(bigger or gap or streak >= 2), "member_ref": mem, **({"ref_ko": ref_ko} if ref_ko else {})}


EXP_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def _p(x: Optional[float], d: int = 1) -> str:
    return "-" if x is None else f"{x:+.{d}%}"


CARD_TODO = {"실거래-페이퍼 차이": "거래소 앱의 체결 가격·시각을 페이퍼와 비교해 보세요",
             "평소보다 큰 손실": "거래소 앱에서 손절이 제자리에 걸려 있었는지 보세요"}


def streak_todo(infos: Optional[list]) -> str:
    """'지금 할 일' of a losing run's card, from the executors' configs: their loss-streak halt when they have one; none
    since owners 10-19 (the live configs): said so, with the kill file; configs not known: neither claimed."""
    if infos:
        ns = [ex.max_streak for ex in infos if ex.max_streak]
        if ns:
            return f"따로 할 일은 없습니다. {min(ns)}연패면 실행기가 스스로 멈춥니다(9장)"
        if all(ex.auto_halts is False for ex in infos):
            return ("연패해도 실행기는 스스로 멈추지 않습니다. 계속할지 두 분이 정하세요"
                    f"(두 실행기 모두 바로 닫고 멈추려면 sudo touch {infos[0].kill_file})")
    return "계속할지 두 분이 정하세요(손실 카드들의 판정을 같이 보세요)"


def card_text(c: dict, exp: Optional[dict] = None, infos: Optional[list] = None) -> str:
    """❌ 청산 = the loss card (3부 ①; 4부 style). Loud cards start with 🚨 and end with "지금 할 일:". ``infos``: the
    executors (their halts and lights decide some words)."""
    sym = c["symbol"]
    head = head_line("❌", "청산", sym, c["side"], f"순ROE {fmt_roe(c['roe'])}")
    typ = f" · {c['type']}" if c.get("type") else ""
    lines = [("🚨 " + head) if c["loud"] else head,
             f"{c['strategy']} {KO_TF.get(c['tf'], c['tf'])}{typ}"
             + (f" · {'세팅' if '#' in str(c.get('member') or '#') else '목록'} {c['member_order']}번"
                if c.get("member_order") else "") + f" · {c['hold_h']:.1f}시간 보유",
             f"진입 {kst(c['entry_time'])} → {KO_EXIT.get(c['exit_reason'], c['exit_reason'])} {kst(c['exit_time'])}"
             + (f" · 손절 {c['stop_type']}" if c.get("stop_type") else
                " · 손절" if c.get("stop_pct") is not None else "")
             + (f" 거리 {c['stop_pct']:.2f}%" if c.get("stop_pct") is not None else "")
             + (f" · 먼저 {c['mfe_roe']:+.1%}까지" if c.get("mfe_roe") is not None else "")]
    reg = (f"장세 {REG5_KO[int(c['reg5'])]} · " if c.get("reg5") is not None and 0 <= int(c["reg5"]) < 5 else "")
    if c.get("fit_win") is not None:
        hon = c.get("honest")
        lines.append(f"{reg}{int(c['hour']):02d}시 · 백테스트 승률 {c['fit_win']:.1%}"
                     + (f" (처음 보는 기간 {hon[1]:.0%})" if hon else ""))
        if c.get("loss_median") is not None and c.get("loss_worst") is not None:
            lines.append(f"손실 보통 {c['loss_median']:+.0%} / 최악 {c['loss_worst']:+.0%}"
                         + (f" · 손절까지 보통 {c['hours_median']:.1f}시간" if c.get("hours_median") is not None else ""))
        cells = []
        if c.get("reg5_cell"):
            cells.append(f"이 장세 {c['reg5_cell'][1]:.0%}({c['reg5_cell'][0]}번)")
        if c.get("sym_cell"):
            cells.append(f"이 코인 {c['sym_cell'][1]:.0%}({c['sym_cell'][0]}번)")
        if cells:
            lines.append(" · ".join(cells) + (" → 백테스트에서도 약한 자리" if c.get("weak") else ""))
    else:
        lines.append(f"{reg}{int(c['hour']):02d}시 · {c.get('ref_ko') or '백테스트 기준표에 이 매매법이 없음'}")
    if c.get("fit_longest") is None and c.get("honest_longest") is None:
        lines.append(f"연속 손실 {c['streak']}번째")
    else:
        lines.append(f"연속 손실 {c['streak']}번째 (백테스트 최장 {c['fit_longest']}번, 처음 보는 기간 {c['honest_longest']}번)")
    for o in c["executors"]:
        pad = PAD.get(o.get("name"), f"{o['label']} ")
        if o["status"] == "followed":
            lines.append(f"{pad}{fmt_usd(o.get('pnl'))} ({fmt_roe(o.get('roe'))})"
                         + (f" · 진입 {o['entry_bps']:+.1f}" if o.get("entry_bps") is not None else "")
                         + (f" / 청산 {o['exit_bps']:+.1f}bps" if o.get("exit_bps") is not None else ""))
        elif o["status"] == "open":
            lines.append(f"{pad}아직 닫는 중")
        elif o["status"] == "blocked":
            lines.append(f"{pad}⛔ 신호등이 막음")
        elif o["status"] == "no_record":
            lines.append(f"{pad}기록 없음")
        else:
            lines.append(f"{pad}따라가지 않음")
    lines.append(f"판정: {c['label']}")
    if c["loud"]:
        todo = CARD_TODO.get(c["label"]) or streak_todo(infos)
        lines.append(f"지금 할 일: {todo}")
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
               infos: Optional[list] = None, older_only: bool = False, ref_ko: str = "") -> list:
    """New losing paper trades -> cards (stored; sent when fresh and ``send`` is given), then the noise check of the
    cards whose 4 hours are over. ``older_only`` (the morning check): only losses too old for the watcher to send, so
    a fresh card keeps its message. ``ref_ko``: why ``exp`` is None (usable_expected), said on the card. Returns the
    new cards."""
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
            if t["pnl"] >= 0 or t["exit_time"] < now_ms - CARD_LOOKBACK_MS:
                continue
            if older_only and now_ms - t["exit_time"] <= CARD_SEND_MS:
                continue
            key = f"{ACCOUNT}|{t['symbol']}|{t['entry_time']}"
            if key in have:
                continue
            outs = [exec_outcome(ex, conns[ex.name], key, t) for ex in infos]
            if any(o["status"] == "open" for o in outs) and now_ms - t["exit_time"] < CARD_WAIT_MS:
                continue                                      # an executor is still closing: next pass
            card = build_card(t, entry_meta(pc, ACCOUNT, t["entry_time"], t["symbol"]), trades, exp, outs, ref_ko=ref_ko)
            card["leverage"], card["entry_price"] = t.get("leverage"), t.get("entry_price")
            text = card_text(card, infos=infos)
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
            card["text"], card["sent"] = text, sent
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


def drift_conditions(paper: list, exp: Optional[dict], lights: bool = True) -> tuple[list, set]:
    """``lights``: an executor runs the signal light (then the alarm says what it does)."""
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
                              + ("신호등이 빨강이면 실거래는 이미 따라가지 않습니다\n" if lights else "")
                              + "지금 할 일: 손실 카드들의 판정을 같이 보세요",
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
def halt_kinds(risk: dict) -> list:
    kinds = list(risk.get("halt_kinds") or [])
    reason = str(risk.get("halt_reason") or "")
    if not kinds:
        if "연속 손실" in reason:
            kinds.append("streak")
        if "낙폭" in reason:
            kinds.append("drawdown")
        if "비상 정지" in reason or "STOP" in reason:
            kinds.append("kill")
    return kinds


def halt_rule(risk: dict, ex: Optional[ExecInfo] = None) -> str:
    """The rule a halt came from, in words; a streak or drawdown halt with the executor's own number (its config,
    else the number in the halt's own record, else the old live configs' 3 / 50%)."""
    import re
    reason = str(risk.get("halt_reason") or "")
    words = []
    for k in halt_kinds(risk):
        if k == "streak":
            m = re.search(r"멈춤 기준 (\d+)번", reason) or re.search(r"연속 손실 (\d+)번", reason)
            n = (ex.max_streak if ex is not None and ex.max_streak else None) or (int(m[1]) if m else None)
            words.append(f"{n}연패(연속 손실 {n}번)" if n else HALT_KO["streak"])
        elif k == "drawdown":
            m = re.search(r"멈춤 기준 (\d+)%", reason)
            d = (f"{ex.max_dd:.0%}" if ex is not None and ex.max_dd is not None else None) or (f"{m[1]}%" if m else None)
            words.append(f"낙폭 {d}" if d else HALT_KO["drawdown"])
        elif k in HALT_KO:
            words.append(HALT_KO[k])
    return " + ".join(words) if words else f"기타({reason[:80] or '이유 기록 없음'})"


def halt_guide(ex: ExecInfo, risk: dict) -> tuple[str, tuple]:
    """(the header line, the guide lines) of a halt summary: the owners' guide about the loss-streak and drawdown halts
    (quoted from live1019-start-ko.md) only when this halt came from one of them or the executor's config has them; the
    live configs have neither since owners 10-19: then a line that this halt is not one of them (true of its kinds
    whatever the config says) and the guide's way to lift it."""
    kinds = set(halt_kinds(risk))
    if kinds & {"streak", "drawdown"} or ex.auto_halts:
        return "안내서(live1019-start-ko.md):", HALT_GUIDE
    return "안내:", HALT_GUIDE_NO_AUTO


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
    lines = [f"{ex.label} 실행기가 멈췄습니다 · 이유: {halt_rule(risk, ex)}",
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
    light = f" · {light_text(light_state(paper, ex.light_n, ex.light_min))}" if ex.light_on else ""
    if len(paper) >= 20:
        w = sum(1 for t in last20 if t["pnl"] > 0)
        lines.append(f"페이퍼 최근 20번 {w}승({w / 20:.0%}){light}")
    else:
        lines.append(f"페이퍼 거래 {len(paper)}번(표본 작음){light}")
    head, guide = halt_guide(ex, risk)
    lines += [head] + [f"- {g}" for g in guide]
    lines += ["지금 할 일: 두 분이 같이 원인을 본 뒤 이 순서로 풉니다(live-safety.md 3-5)",
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
        return ["(서비스별 메모리를 읽지 못함)",
                "지금 할 일: 실험 서비스(에이전트·토론방·데모·리그·그림자)부터 끄세요. paperbot-live3·paperbot-combo·"
                "실행기는 끄지 않기"]
    top = sorted(units, key=lambda u: -u[1])[:6]
    lines = ["많이 쓰는 순서: " + ", ".join(f"{u.removesuffix('.service')} {_gb(m)}" for u, m in top)]
    first = [u for u, _m in sorted(units, key=lambda u: -u[1]) if experiment(u)][:3]
    if first:
        lines.append("끄면 안 됨: paperbot-live3, paperbot-combo, paperbot-executor, paperbot-executor-mexc")
        lines.append("지금 할 일: 실험부터 끄기 sudo systemctl stop "
                     + " ".join(u.removesuffix(".service") for u in first))
    else:
        lines.append("끄면 안 됨: paperbot-live3, paperbot-combo, paperbot-executor, paperbot-executor-mexc")
        lines.append("지금 할 일: 끌 만한 실험 서비스가 켜져 있지 않습니다. 개발자에게 알려 주세요")
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
                          "지금 할 일: sudo du -xh /var/lib/paperbot --max-depth 2 | sort -h | tail 로 큰 것을 보고, 실험 "
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


# ====================================================================== 4부: 실거래 텔레그램 (one clean live stream)
ENTRY_WAIT_MS = 3 * MIN            # a trade message waits this long at most for the executors to act
TRADE_SEND_MS = 30 * MIN           # an entry / exit older than this when first seen is recorded, not sent
PRICE_DP = {"BTCUSDT": 0, "ETHUSDT": 2, "SOLUSDT": 2, "DOGEUSDT": 5, "LTCUSDT": 2, "BCHUSDT": 2}
PAD = {"paper": "페이퍼   ", "bybit": "바이비트 ", "mexc": "MEXC     "}
LIGHT_DOT = {"green": "🟢", "red": "🔴", "building": "⚪", "off": "⚪"}
TRADE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_msgs (
    key TEXT NOT NULL,
    kind TEXT NOT NULL,
    first_ts INTEGER NOT NULL,
    sent_ts INTEGER,
    level TEXT,
    text TEXT,
    PRIMARY KEY (key, kind)
);
"""
# where a sent message landed ({chat id: message id}, notify.TelegramNotifier.send_ids), for a message that is edited
# later (the ⏳ wait turns into its result); a table of its own so older livecheck.db files keep their columns
TG_IDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tg_ids (
    key TEXT NOT NULL,
    kind TEXT NOT NULL,
    ids_json TEXT NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (key, kind)
);
"""


# ---------------------------------------------------------------- numbers as the owners read them
def fmt_price(x, symbol: str = "") -> str:
    """67,250 · 182.35 · 0.24512: the coin's precision, thousands separators."""
    if x is None:
        return "-"
    x = float(x)
    dp = PRICE_DP.get(symbol)
    if dp is None:
        dp = 0 if abs(x) >= 1000 else 2 if abs(x) >= 1 else 5
    return f"{x:,.{dp}f}"


def fmt_usd(x, sign: bool = True) -> str:
    """+$9.36 / -$1.52 (sign) or $40.00."""
    if x is None:
        return "-"
    x = float(x)
    return (f"{'+' if x >= 0 else '-'}${abs(x):,.2f}" if sign else f"{'-' if x < 0 else ''}${abs(x):,.2f}")


def fmt_roe(x) -> str:
    return "-" if x is None else f"{float(x):+.1%}"


def strat_text(name: str, tf: str, exp: Optional[dict]) -> str:
    """F15_LON_BRK 1시간 · 돌파 (never the internal member label or its hash)."""
    typ = (((exp or {}).get("strategies") or {}).get(name) or {}).get("type")
    return f"{name} {KO_TF.get(tf, tf)}" + (f" · {typ}" if typ else "")


def _pad(ex) -> str:
    return PAD.get(ex.name, ex.label + " ")


def head_line(emoji: str, what: str, symbol: str, side: int, key_number: str) -> str:
    return f"{emoji} {what} · {coin(symbol)} {KO_SIDE.get(int(side), '')} · {key_number}"


# ---------------------------------------------------------------- what an executor did with one paper trade
def _exec_row(c, key: str) -> Optional[dict]:
    try:
        cur = c.execute("SELECT * FROM trades WHERE key = ?", (key,))
        r = cur.fetchone()
        if r is None:
            return None
        row = dict(zip([d[0] for d in cur.description], r))
    except sqlite3.Error:
        return None
    try:
        row["data"] = json.loads(row.get("data") or "{}")
    except (ValueError, TypeError):
        row["data"] = {}
    return row


def entry_state(ex: ExecInfo, c, key: str, paper: list, entry_time: int, run: bool) -> dict:
    """The executor's answer to a paper entry: entered / entering (wait) / blocked by the light / halted / off /
    refused (its own words) / unknown (wait, then "did not follow")."""
    if c is None:
        return {"state": "none"}
    row = _exec_row(c, key)
    if row is not None:
        qty, px, lev = float(row.get("qty") or 0), float(row.get("entry_price") or 0), int(row.get("leverage") or 1)
        return {"state": "entered", "price": px, "margin": qty * px / max(lev, 1), "lev": lev,
                "stop": row.get("stop_initial") or row["data"].get("stop_initial")}
    _ts, bot = get_state(c, "bot")
    t = (bot or {}).get("trade") or {}
    if t.get("key") == key:
        return {"state": "entering"}
    told = _key_events(c, key)
    if any(k == "light_red" for _t, k, _x in told):
        return {"state": "blocked", "light": light_state(paper, ex.light_n, ex.light_min, at=entry_time + MIN)}
    if told:
        return {"state": "refused", "why": str(told[0][2])[:70]}
    if ((bot or {}).get("risk") or {}).get("halted"):
        return {"state": "halted"}
    if not run:
        return {"state": "off"}
    return {"state": "unknown"}


def entry_exec_line(ex: ExecInfo, st: dict, symbol: str) -> str:
    s = st["state"]
    if s == "entered":
        return (f"{_pad(ex)}✅ {fmt_price(st['price'], symbol)} · 증거금 {fmt_usd(st['margin'], sign=False)}"
                + (f" · 손절 {fmt_price(st['stop'], symbol)}" if st.get("stop") else "") + " · 포지션 1/1")
    if s == "blocked":
        L = st["light"]
        num = f" (최근 {L['n']}번 {L['wins']}승 {L['wins'] / L['n']:.0%})" if L.get("n") and L.get("wins") is not None \
            and L["state"] != "building" else ""
        return f"{_pad(ex)}⛔ 신호등이 막음{num}"
    if s == "halted":
        return f"{_pad(ex)}⏸ 멈춤 중이라 따라가지 않음"
    if s == "off":
        return f"{_pad(ex)}⏹ 꺼져 있음"
    if s == "none":
        return f"{_pad(ex)}기록 없음(아직 시작 전)"
    if s == "refused":
        return f"{_pad(ex)}⚠ 따라가지 않음 ({st['why']})"
    if s == "entering":
        return f"{_pad(ex)}… 들어가는 중"
    return f"{_pad(ex)}⚠ 따라가지 않음 (알람 따로)"


def entry_text(p: dict, states: list, exp: Optional[dict]) -> str:
    """🟢 진입: the paper's entry and each executor's answer."""
    sym, side, entry, stop = p["symbol"], int(p["side"]), p.get("entry_price"), p.get("stop_initial")
    lev = int(p.get("leverage") or 0)
    lines = [head_line("🟢", "진입", sym, side, f"{lev}배" if lev else "페이퍼"),
             strat_text(p.get("strategy", ""), p.get("tf", ""), exp),
             f"{PAD['paper']}{fmt_price(entry, sym)}"
             + (f" · 손절 {fmt_price(stop, sym)} ({(float(stop) / float(entry) - 1):+.2%})" if (stop and entry) else "")]
    lines += [entry_exec_line(ex, st, sym) for ex, st in states]
    return "\n".join(lines)


def lock_text(p: dict, moves: list) -> str:
    """🔒 잠금 시작: the first lock of a trade and where each executor's stop went."""
    parts = []
    for ex, mv in moves:
        if mv["state"] == "moved":
            parts.append(f"{ex.label} 손절 {fmt_price(mv['from'], p['symbol'])} → {fmt_price(mv['to'], p['symbol'])}")
        elif mv["state"] == "waiting":
            parts.append(f"{ex.label} 손절 아직 그대로({fmt_price(mv['from'], p['symbol'])})")
        elif mv["state"] == "closed":
            parts.append(f"{ex.label} 이미 청산")
        else:
            parts.append(f"{ex.label} 따라가지 않음")
    return "\n".join([head_line("🔒", "잠금 시작", p["symbol"], p["side"], f"{float(p['lock_roe']):+.0%} 확보"),
                      " · ".join(parts)])


def exit_exec_line(ex: ExecInfo, o: dict) -> str:
    s = o["status"]
    if s == "followed":
        return (f"{_pad(ex)}{fmt_usd(o.get('pnl'))} ({fmt_roe(o.get('roe'))})"
                + (f" · 잔고 {fmt_usd(o['equity'], sign=False)}" if o.get("equity") is not None else ""))
    if s == "open":
        return f"{_pad(ex)}아직 닫는 중"
    if s == "blocked":
        return f"{_pad(ex)}⛔ 신호등이 막음"
    if s == "no_record":
        return f"{_pad(ex)}기록 없음"
    return f"{_pad(ex)}따라가지 않음"


def exit_reason_text(t: dict) -> str:
    if t.get("reason") == "LOCK":
        lock = t.get("lock_roe")
        return f"잠금 {float(lock):+.0%} 청산" if lock is not None else "잠금 청산"
    return KO_EXIT.get(t.get("reason"), str(t.get("reason") or ""))


def day_line(paper: list, now_ms: int, infos: list) -> str:
    """오늘(09시부터) 승패 · 최근 20번 · 신호등."""
    d0 = now_ms - (now_ms + 0) % DAY                   # 00:00 UTC = 09:00 KST: the trading day
    today = [t for t in paper if t["exit_time"] >= d0]
    w = sum(1 for t in today if t["pnl"] > 0)
    out = f"오늘 {w}승 {len(today) - w}패"
    if len(paper) >= 20:
        w20 = sum(1 for t in paper[-20:] if t["pnl"] > 0)
        out += f" · 최근 20번 {w20}승({w20 / 20:.0%})"
    else:
        w_all = sum(1 for t in paper if t["pnl"] > 0)
        out += f" · 지금까지 {len(paper)}번 {w_all}승(표본 작음)"
    lights = [f"{ex.label} {LIGHT_DOT[light_state(paper, ex.light_n, ex.light_min)['state']]}" for ex in infos]
    if not any(ex.light_on for ex in infos):          # no light (owners 10-19): no light dots
        lights = []
    return out + (" · 신호등 " + " ".join(lights) if lights else "")


def win_text(t: dict, outs: list, paper: list, now_ms: int, exp: Optional[dict], infos: list) -> str:
    mfe, entry, lev = t.get("mfe_price"), float(t.get("entry_price") or 0), int(t.get("leverage") or 1)
    best = int(t["side"]) * (float(mfe) - entry) / entry * lev if (mfe and entry) else None
    lines = [head_line("✅", "청산", t["symbol"], t["side"], f"순ROE {fmt_roe(t['roe'])}"),
             f"{strat_text(t.get('strategy', ''), t.get('tf', ''), exp)} · "
             f"{(t['exit_time'] - t['entry_time']) / H1:.1f}시간 보유 · {exit_reason_text(t)}"
             + (f" (최고 {best:+.0%})" if best is not None else "")]
    lines += [exit_exec_line(ex, o) for ex, o in outs]
    lines.append(day_line(paper, now_ms, infos))
    return "\n".join(lines)


def exit_outcome(ex: ExecInfo, c, key: str, pt: dict) -> dict:
    """exec_outcome plus the executor's balance after the trade."""
    o = exec_outcome(ex, c, key, pt)
    if c is not None and o["status"] == "followed":
        _ts, bot = get_state(c, "bot")
        o["equity"] = ((bot or {}).get("risk") or {}).get("last_equity")
    return o


def _msg_row(conn, key: str, kind: str) -> Optional[tuple]:
    return conn.execute("SELECT first_ts, sent_ts FROM trade_msgs WHERE key = ? AND kind = ?", (key, kind)).fetchone()


def _msg_put(conn, key: str, kind: str, first_ts: int, sent_ts: Optional[int] = None, level: Optional[str] = None,
             text: Optional[str] = None) -> None:
    conn.execute("INSERT OR REPLACE INTO trade_msgs VALUES (?,?,?,?,?,?)", (key, kind, first_ts, sent_ts, level, text))


# ---------------------------------------------------------------- ⏳ 진입 대기 (owners 10/19)
# A "break" setting of the combined bot (33 of its 95) does not enter at its signal: it waits, for one bar of its own
# timeframe, for the price to trade beyond the signal bar's high (long) / low (short), then enters the next minute
# (paperbot/combo.py _research_signal / _breaks; its signal_log row says WAITING until then). That wait is a real
# "entry may come": the page and one quiet message show it. The bot's other checks still apply at the break (the signal
# bar size, the switched-off buckets, one position at a time, the weekend and the macro pause). Once the bot has
# restated the wait (combo.py _restate: BROKE and then its entry's outcome, or FILTERED with its why) the same message
# gets one result line at its end (wait_result_pass; Telegram editMessageText, never a second message).
WAIT_TF_MS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": H1, "4h": 4 * H1}
WAIT_MSGS_ENV = "PAPERBOT_LIVE_WAIT_MSGS"              # "0": no ⏳ message (the page still shows the waits)
WAIT_EDIT_MAX_MS = 48 * H1                             # a wait sent longer ago than this is no longer edited
# the bot's why of a wait that ended without an entry (combo.py _breaks / _submit_due / _research_entry), plain Korean;
# "돌파 없음" has its own line (WAIT_LAPSED)
WAIT_WHY_KO = (("연구 조건 밖: 신호봉 크기", "신호봉 크기가 연구 조건 밖"), ("연구 조건 밖", "연구 조건 밖"),
               ("연구 조건을 못 읽음", "연구 조건을 못 읽음"), ("돌파 확인이 늦음", "돌파 확인이 늦음(봇 재시작 따라잡기)"),
               ("주말", "주말이라 진입 쉼"), ("경제 발표", "경제 발표 앞뒤라 진입 쉼"), ("끈 구간", "끈 구간에 걸림"),
               ("설정에 없는", "설정이 바뀜"))
# the paper engine's reason when the entry signal of a break was not taken (engine.py _record, combo.py)
WAIT_SKIP_KO = (("in position", "이미 포지션 있음"), ("lower score", "같은 때 다른 신호가 먼저 들어감"), ("late", "신호가 늦음"),
                ("stop rule", "손절 자리가 안 맞음"), ("sizing", "크기 계산이 거절함"), ("halted", "페이퍼 계좌 멈춤 중"),
                ("early exit", "같은 분에 빠른 청산"), ("guard", "보호 장치"), ("no next bar", "다음 1분봉 없음"))
WAIT_LAPSED = "→ ⌛ 시간 지남 · 진입 없음"


def pending_entries(paper_conn, rule_conn, now_ms: int) -> list:
    """The break signals still waiting now, oldest first: coin, side, strategy, setting, timeframe, the signal bar's
    close (t0) and the deadline (t0 + one bar), the level the price must trade beyond (the signal bar's 1m high / low
    in the rule bot's bars, as the paper bot takes it; None before that bar is in the file), the last 1m close and how
    far it still has to go (a fraction of the price, <= 0 once beyond)."""
    try:
        rows = paper_conn.execute("SELECT bar_close, timeframe, strategy, symbol, side, data FROM signal_log WHERE status = 'WAITING' "
                                  "AND bar_close >= ? ORDER BY bar_close, id", (int(now_ms) - 4 * H1,)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for bc, tf, member, sym, side, data in rows:
        tf_ms = WAIT_TF_MS.get(tf)
        if tf_ms is None or bc is None:
            continue
        t0, until = int(bc), int(bc) + tf_ms
        if until <= now_ms:
            continue                                   # lapsed: the bot restates it at its next minute
        try:
            d = json.loads(data or "{}")
        except ValueError:
            d = {}
        side = int(side or 0)
        level = last = last_ts = moved = None
        if rule_conn is not None:
            try:
                hi, lo = rule_conn.execute("SELECT MAX(high), MIN(low) FROM live_bars WHERE symbol = ? AND ts >= ? AND ts < ?",
                                           (sym, t0 - tf_ms, t0)).fetchone()
                level = hi if side > 0 else lo
                r = rule_conn.execute("SELECT ts, close FROM live_bars WHERE symbol = ? ORDER BY ts DESC LIMIT 1", (sym,)).fetchone()
                if r:
                    last_ts, last = int(r[0]), float(r[1])
                hi2, lo2 = rule_conn.execute("SELECT MAX(high), MIN(low) FROM live_bars WHERE symbol = ? AND ts >= ?", (sym, t0)).fetchone()
                moved = hi2 if side > 0 else lo2
            except sqlite3.Error:
                pass
        level = float(level) if level is not None else None
        out.append({"key": f"{member}|{sym}|{t0}", "t0": t0, "until": until, "tf": tf, "member": member,
                    "strategy": d.get("strategy") or str(member).split("@")[0], "symbol": sym, "side": side,
                    "level": level, "last": last, "last_ts": last_ts,
                    "to_go": (side * (level - last) / last) if level is not None and last else None,
                    "touched": (moved > level if side > 0 else moved < level) if moved is not None and level is not None else None})
    return out


def wait_text(w: dict, now_ms: int) -> str:
    side = KO_SIDE.get(w["side"], "")
    where = "위로 올라가면" if w["side"] > 0 else "아래로 내려가면"
    lv = f"{w['level']:,.6g}" if w.get("level") is not None else "신호봉 끝"
    lines = [f"⏳ 진입 대기 · {coin(w['symbol'])} {side} · {w['strategy']} {KO_TF.get(w['tf'], w['tf'])}",
             f"{lv} {where} 진입" + (f" (지금 {w['last']:,.6g} · {abs(w['to_go']):.2%} 남음)" if w.get("to_go") is not None and w["to_go"] > 0
                                    else " (지금 그 가격 근처)" if w.get("to_go") is not None else ""),
             f"{kst(w['until'])}까지 못 넘으면 진입 없음 · {max(0, (w['until'] - now_ms) // MIN)}분 남음",
             "들어가면 🟢 진입 알림이 따로 와요 (봇의 다른 확인은 그대로: 신호봉 크기·끈 구간·한 번에 하나)"]
    return "\n".join(lines)


def _paused_now(now_ms: int, mins: int = 30) -> bool:
    """The bots' own pause right now: the KST weekend, or ±mins around a registered US macro release."""
    if ((int(now_ms) + KST_MS) // DAY + 3) % 7 >= 5:
        return True
    try:
        from . import events as EV
        return bool(EV.near(int(now_ms), mins * MIN, mins * MIN))
    except Exception:  # noqa: BLE001  without the file: not paused by it (the paper bot says so itself)
        return False


def wait_pass(src: Sources, conn, now_ms: int, send: Callable, send_ids: Optional[Callable] = None) -> list:
    """⏳ one quiet message per break signal that starts waiting, while the paper account holds no position and the bots
    are not paused (then a break could not enter anyway: nothing is sent, and the wait is not marked, so a wait still
    open when the position closes is told then). Off with PAPERBOT_LIVE_WAIT_MSGS=0. ``send_ids`` (the Telegram
    notifier's): sent through it instead and where it landed kept (tg_ids), so its result can be written into it."""
    if conn is None or os.environ.get(WAIT_MSGS_ENV, "").strip() == "0":
        return []
    pc = open_ro(src.paper_db)
    if pc is None:
        return []
    rc = open_ro(src.rule_db)
    try:
        _ts, acc = get_state(pc, "accounts")
        pos = (((acc or {}).get("engines") or {}).get(ACCOUNT) or {}).get("position")
        waits = pending_entries(pc, rc, now_ms)
    finally:
        pc.close()
        if rc is not None:
            rc.close()
    if pos or _paused_now(now_ms):
        return []
    out = []
    for w in waits:
        if _msg_row(conn, w["key"], "wait"):
            continue
        if w.get("touched"):
            _msg_put(conn, w["key"], "wait", now_ms)      # already beyond: the entry message comes instead
            continue
        text = wait_text(w, now_ms)
        if send_ids is not None:
            ids = send_ids(INFO, text) or {}
            ok = bool(ids)                                 # {} = no chat took it (tried again next pass)
        else:
            ids, ok = {}, send(INFO, text) is not False
        if ok:
            _msg_put(conn, w["key"], "wait", now_ms, now_ms, INFO, text)
            ids = {str(c): int(m) for c, m in ids.items() if m is not None}
            if ids:
                conn.execute("INSERT OR REPLACE INTO tg_ids VALUES (?,?,?,?)", (w["key"], "wait", json.dumps(ids), now_ms))
            out.append(("wait", w["key"], INFO, text))
    return out


def _why_of(data) -> str:
    """The why a signal_log row's data carries (combo.py _log / _restate)."""
    try:
        return str(json.loads(data or "{}").get("why") or "")
    except (ValueError, AttributeError):
        return ""


def _why_ko(why: str) -> str:
    w = str(why or "")
    return next((ko for head, ko in WAIT_WHY_KO if w.startswith(head)), w[:60] or "이유 기록 없음")


def _skip_ko(reason: str) -> str:
    r = str(reason or "")
    return next((ko for head, ko in WAIT_SKIP_KO if r.startswith(head)), r[:60] or "이유 기록 없음")


def _entry_outcome(pc, entry_t: int, tf: str, member: str, symbol: str) -> Optional[tuple]:
    """(status, reason) of the paper account's outcome for the entry signal a break made (its signal: ts + 1 = the
    entry minute, the same timeframe, setting and coin), None while the engine has not recorded it."""
    try:
        rows = pc.execute("SELECT status, reason, data FROM outcomes WHERE account_id = ? AND symbol = ? AND step_ts >= ? "
                          "AND step_ts < ? ORDER BY id", (ACCOUNT, symbol, entry_t - MIN, entry_t + DAY)).fetchall()
    except sqlite3.Error:
        return None
    for status, reason, data in rows:
        try:
            s = json.loads(data or "{}").get("signal") or {}
            meta = s.get("meta") or {}
            if int(s.get("ts")) + 1 == entry_t and s.get("timeframe") == tf and (meta.get("member") or s.get("strategy_id")) == member:
                return status, reason
        except (ValueError, TypeError, AttributeError):
            continue
    return None


def wait_result(pc, key: str) -> Optional[str]:
    """The result line of a ⏳ wait (key 'setting|coin|signal bar close'), from the paper bot's own records: the wait's
    signal_log row as combo.py restated it (BROKE: then its entry signal's row and the engine's outcome; FILTERED: the
    why). None while the result is not known yet."""
    try:
        member, sym, t0 = key.rsplit("|", 2)
        row = pc.execute("SELECT status, data, timeframe FROM signal_log WHERE bar_close = ? AND strategy = ? AND symbol = ?",
                         (int(t0), member, sym)).fetchone()
    except (ValueError, sqlite3.Error):
        return None
    if row is None:
        return None
    status, data, tf = row
    if status == "FILTERED":
        why = _why_of(data)
        return WAIT_LAPSED if why.startswith("돌파 없음") else f"→ 진입 안 함: {_why_ko(why)}"
    if status != "BROKE":
        return None
    m = re.search(r"(\d{12,})", _why_of(data))             # "돌파 확인: {entry minute ms} 분에 진입 신호"
    if not m:
        return None
    entry_t = int(m[1])
    try:
        sub = pc.execute("SELECT status, data FROM signal_log WHERE bar_close = ? AND timeframe = ? AND strategy = ? AND symbol = ?",
                         (entry_t, tf, member, sym)).fetchone()
    except sqlite3.Error:
        return None
    if sub is not None and sub[0] == "FILTERED":           # the weekend, a macro release, a switched-off bucket ...
        return f"→ 돌파했지만 진입 안 함: {_why_ko(_why_of(sub[1]))}"
    o = _entry_outcome(pc, entry_t, tf, member, sym)
    if o is None:
        return None
    if o[0] == "ENTERED":
        return f"→ ✅ 돌파! {kst(entry_t)}에 진입했어요 (🟢 진입 알림 참고)"
    return f"→ 돌파했지만 진입 안 함: {_skip_ko(o[1])}"


def wait_result_pass(src: Sources, conn, now_ms: int, edit: Optional[Callable]) -> list:
    """→ each sent ⏳ wait whose result is known gets it: the same message edited (``edit``: the Telegram notifier's
    editMessageText), its text + a blank line + one result line (wait_result). Once per wait (trade_msgs kind
    'wait_result'), also when the edit fails (the message deleted or too old: logged, never sent as a new message); a
    wait sent more than 48 hours ago is given up quietly. Only waits whose message ids were kept (tg_ids); off with
    PAPERBOT_LIVE_WAIT_MSGS=0. Returns [("wait_result", key, level, new text)] edited."""
    if conn is None or edit is None or os.environ.get(WAIT_MSGS_ENV, "").strip() == "0":
        return []
    rows = conn.execute("SELECT m.key, m.sent_ts, m.text, g.ids_json FROM trade_msgs m JOIN tg_ids g ON g.key = m.key "
                        "AND g.kind = 'wait' WHERE m.kind = 'wait' AND m.sent_ts IS NOT NULL AND NOT EXISTS (SELECT 1 "
                        "FROM trade_msgs r WHERE r.key = m.key AND r.kind = 'wait_result') ORDER BY m.sent_ts").fetchall()
    if not rows:
        return []
    out = []
    pc = open_ro(src.paper_db)
    try:
        for key, sent_ts, text, ids_json in rows:
            if now_ms - int(sent_ts) > WAIT_EDIT_MAX_MS or not text:
                _msg_put(conn, key, "wait_result", now_ms)            # given up quietly
                continue
            line = wait_result(pc, key) if pc is not None else None
            if line is None:
                continue
            new = f"{text}\n\n{line}"
            try:
                ids = json.loads(ids_json or "{}")
            except ValueError:
                ids = {}
            ok = bool(ids) and edit(INFO, ids, new) is not False
            if not ok:
                print(f"⏳ 대기 메시지에 결과를 못 씀(새 메시지는 안 보냄): {key}", file=sys.stderr)
            _msg_put(conn, key, "wait_result", now_ms, now_ms if ok else None, INFO, new)
            if ok:
                out.append(("wait_result", key, INFO, new))
        conn.execute("DELETE FROM tg_ids WHERE ts < ?", (now_ms - 30 * DAY,))
        conn.commit()
    finally:
        if pc is not None:
            pc.close()
    return out


# ---------------------------------------------------------------- ⏸ 🔔 진입 쉼 시작 · 끝 (owners 10/19)
# The paper bot makes no new entry in its pauses (combo.py _submit_due): the KST weekend (config no_weekend) and
# ±macro_blackout_min around each US macro release (data/macro_events.csv). One quiet message when a pause starts and
# one when it ends; pauses that overlap or touch are one (a Friday-night release running into the weekend).
PAUSE_MSGS_ENV = "PAPERBOT_LIVE_PAUSE_MSGS"            # "0": no ⏸ / 🔔 message
PAUSE_SEND_MS = 10 * MIN                               # a start / end first seen later than this after it: not told
PAUSE_POS = "열린 포지션은 손절·잠금 그대로 관리돼요"


def pause_spans(cfg: Optional[dict], a: int, b: int) -> list:
    """The paper bot's entry pauses that touch [a, b], oldest first, overlapping or touching ones merged: each {"from",
    "to", "weekend": bool, "macro": [events.Event], "parts": the weekend ("weekend") and the releases by start}. The
    weekend is the dashboard's (paperbot/dash/more/livebots.py weekend_span: Saturday 00:00 to Monday 00:00 KST, as
    combo.py kst_weekend) when the config has no_weekend; a release's pause is its time ±macro_blackout_min, edges
    included (paperbot/events.py near, as combo.py _macro_near takes it). [] without a config (the rules unknown)."""
    if not cfg:
        return []
    lo = a - 3 * DAY                                       # earlier pauses that may reach [a, b] through a merge
    raw = []
    if cfg.get("no_weekend"):
        from .dash.more.livebots import weekend_span
        s, e = weekend_span(lo)
        while s <= b:
            raw.append((s, e, "weekend"))
            s, e = s + 7 * DAY, e + 7 * DAY
    w = int(cfg.get("macro_blackout_min") or 0) * MIN
    if w:
        from . import events as EV
        raw += [(ev.ts_ms - w, ev.ts_ms + w, ev) for ev in EV.all_events() if ev.ts_ms + w >= lo and ev.ts_ms - w <= b]
    out: list = []
    for s, e, part in sorted(raw, key=lambda x: (x[0], x[1])):
        if out and s <= out[-1]["to"]:
            cur = out[-1]
            cur["to"] = max(cur["to"], e)
        else:
            cur = {"from": s, "to": e, "weekend": False, "macro": [], "parts": []}
            out.append(cur)
        cur["parts"].append(part)
        if part == "weekend":
            cur["weekend"] = True
        else:
            cur["macro"].append(part)
    return [x for x in out if x["to"] >= a and x["from"] <= b]


def _at(ms: int, ref: int) -> str:
    """'21:30' on ``ref``'s KST day, else with the weekday: '월 00:00'."""
    if (int(ms) + KST_MS) // DAY == (int(ref) + KST_MS) // DAY:
        return kst(ms)
    return f"{KO_DOW[_dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, _dt.timezone.utc).weekday()]} {kst(ms)}"


def pause_what(span: dict, mins: int, ref: int, times: bool = True) -> str:
    """'CPI 발표 21:30 앞뒤 30분', '주말', 'NFP 발표 23:45 앞뒤 30분 + 주말' (in time order; ``times`` False: without the
    release times)."""
    words, macros = [], []
    for p in span["parts"]:
        if p == "weekend":
            words.append("주말")
            continue
        if not macros:
            words.append("")                               # where the releases go
        m = f"{p.kind} 발표" + (f" {_at(p.ts_ms, ref)}" if times else "")
        if m not in macros:
            macros.append(m)
    rel = " · ".join(macros) + f" 앞뒤 {mins}분"
    return " + ".join(x or rel for x in words)


def pause_start_text(span: dict, mins: int, now_ms: int, pos: bool) -> str:
    until = _at(span["to"], now_ms)
    if span["weekend"] and not span["macro"]:
        return f"⏸ 주말 진입 쉼 시작 · {until}까지" + (f"\n{PAUSE_POS}" if pos else "")
    return (f"⏸ 진입 쉼 시작 · {pause_what(span, mins, now_ms)}\n{until}까지 새 진입 없음"
            + (f" ({PAUSE_POS})" if pos else ""))


def pause_end_text(nxt: Optional[dict], mins: int, now_ms: int) -> str:
    return "🔔 진입 쉼 끝 · 다시 진입할 수 있어요" + (
        f"\n다음 쉼: {_at(nxt['from'], now_ms)}~{_at(nxt['to'], nxt['from'])} ({pause_what(nxt, mins, now_ms, False)})"
        if nxt is not None else "")


def pause_pass(src: Sources, conn, now_ms: int, send: Callable) -> list:
    """⏸ one quiet message when an entry pause of the paper bot starts and 🔔 one when it ends (pause_spans of the
    config the paper bot runs, combo_config; the end names the next pause when it starts within 24 hours; the start
    says that an open paper position is still managed). Told only within PAUSE_SEND_MS after the moment (a watcher that
    was down sends no stale news), once each (trade_msgs kinds 'pause' / 'resume', keyed by the moment's ms); the start
    of a pause already over is not told. Off with PAPERBOT_LIVE_PAUSE_MSGS=0. Returns [(kind, key, level, text)] sent."""
    if conn is None or os.environ.get(PAUSE_MSGS_ENV, "").strip() == "0":
        return []
    pc = open_ro(src.paper_db)
    try:
        cfg, _where = combo_config(src, pc)
        _ts, acc = get_state(pc, "accounts") if pc is not None else (None, None)
    finally:
        if pc is not None:
            pc.close()
    pos = (((acc or {}).get("engines") or {}).get(ACCOUNT) or {}).get("position")
    try:
        spans = pause_spans(cfg, now_ms - PAUSE_SEND_MS, now_ms + DAY)
    except Exception as exc:  # noqa: BLE001  the calendar unreadable: no pause news this pass
        print(f"진입 쉼 일정을 못 읽음: {type(exc).__name__}: {exc}"[:200], file=sys.stderr)
        return []
    mins = int((cfg or {}).get("macro_blackout_min") or 0)
    due = []
    for i, sp in enumerate(spans):
        if now_ms - PAUSE_SEND_MS <= sp["from"] <= now_ms < sp["to"]:
            due.append((sp["from"], "pause", pause_start_text(sp, mins, now_ms, bool(pos))))
        if now_ms - PAUSE_SEND_MS <= sp["to"] <= now_ms:
            nxt = next((x for x in spans[i + 1:] if x["from"] <= now_ms + DAY), None)
            due.append((sp["to"], "resume", pause_end_text(nxt, mins, now_ms)))
    out = []
    for t, kind, text in sorted(due, key=lambda d: d[0]):
        key = str(int(t))
        if _msg_row(conn, key, kind):
            continue
        if send(INFO, text) is not False:
            _msg_put(conn, key, kind, now_ms, now_ms, INFO, text)
            out.append((kind, key, INFO, text))
    conn.commit()
    return out


def trade_pass(src: Sources, conn, now_ms: int, exp: Optional[dict], send: Callable, infos: Optional[list] = None,
               units: Callable = None) -> list:
    """🟢 entries, 🔒 first locks and ✅ winning exits of the paper account, one message each (trade_msgs; a losing
    exit is its loss card). Each waits until every executor answered (entered / blocked / halted / its own reason) or
    ENTRY_WAIT_MS passed. Returns [(kind, key, level, text)] sent."""
    pc = open_ro(src.paper_db)
    if pc is None or conn is None:
        if pc is not None:
            pc.close()
        return []
    out = []
    infos = infos if infos is not None else (src.executors or load_executors())
    units = units or unit_state
    conns = {ex.name: open_ro(ex.db) for ex in infos}
    runs = {ex.name: should_run(ex, units)[0] for ex in infos}
    try:
        paper = paper_trades(pc, ACCOUNT)
        _ts, acc = get_state(pc, "accounts")
        pos = (((acc or {}).get("engines") or {}).get(ACCOUNT) or {}).get("position")
        entries = [dict(t, open=False) for t in paper if t["entry_time"] >= now_ms - 2 * H1]
        if pos:
            sig = pos.get("signal") or {}
            entries.append({"entry_time": int(pos["entry_time"]), "symbol": pos["symbol"], "side": int(pos["side"]),
                            "strategy": sig.get("strategy_id", ""), "tf": sig.get("timeframe", ""),
                            "entry_price": pos.get("entry_price"), "stop_initial": pos.get("stop_initial")
                            or pos.get("stop_price"), "leverage": pos.get("leverage"), "open": True,
                            "lock_roe": pos.get("lock_roe")})
        # ---- entries
        for e in sorted(entries, key=lambda x: x["entry_time"]):
            key = f"{ACCOUNT}|{e['symbol']}|{e['entry_time']}"
            if _msg_row(conn, key, "entry"):
                continue
            if now_ms - e["entry_time"] > TRADE_SEND_MS:
                _msg_put(conn, key, "entry", now_ms)            # seen too late: recorded, never sent
                continue
            states = [(ex, entry_state(ex, conns[ex.name], key, paper, e["entry_time"], runs[ex.name]))
                      for ex in infos]
            waiting = any(st["state"] in ("entering", "unknown") for _ex, st in states)
            if waiting and now_ms - e["entry_time"] < ENTRY_WAIT_MS:
                continue
            text = entry_text(e, states, exp)
            if send(INFO, text) is not False:
                _msg_put(conn, key, "entry", now_ms, now_ms, INFO, text)
                out.append(("entry", key, INFO, text))
        # ---- the first lock of the open position
        if pos and pos.get("lock_roe") is not None:
            p = entries[-1]
            key = f"{ACCOUNT}|{p['symbol']}|{p['entry_time']}"
            row = _msg_row(conn, key, "lock")
            if row is None or row[1] is None:
                first = row[0] if row else now_ms
                if row is None:
                    _msg_put(conn, key, "lock", first)
                moves = []
                for ex in infos:
                    c = conns[ex.name]
                    _bts, bot = get_state(c, "bot") if c is not None else (None, None)
                    t = (bot or {}).get("trade") or {}
                    xr = _exec_row(c, key) if c is not None else None
                    if t.get("key") == key and t.get("status") == "open":
                        a, b = t.get("stop_initial"), t.get("stop")
                        moves.append((ex, {"state": "moved" if (a and b and float(a) != float(b)) else "waiting",
                                           "from": a, "to": b}))
                    elif xr is not None and xr.get("exit_ts"):
                        moves.append((ex, {"state": "closed"}))
                    else:
                        moves.append((ex, {"state": "none"}))
                if not any(m["state"] == "waiting" for _e, m in moves) or now_ms - first >= ENTRY_WAIT_MS:
                    text = lock_text(p, moves)
                    if send(INFO, text) is not False:
                        _msg_put(conn, key, "lock", first, now_ms, INFO, text)
                        out.append(("lock", key, INFO, text))
        # ---- winning exits (a losing exit is its loss card)
        for t in paper:
            if t["pnl"] < 0 or t["exit_time"] < now_ms - 2 * H1:
                continue
            key = f"{ACCOUNT}|{t['symbol']}|{t['entry_time']}"
            if _msg_row(conn, key, "exit"):
                continue
            lock = _msg_row(conn, key, "lock")
            if lock is not None and lock[1] is None:
                _msg_put(conn, key, "lock", lock[0])               # closed before its lock message: the exit says it
                conn.execute("UPDATE trade_msgs SET sent_ts = 0 WHERE key = ? AND kind = 'lock'", (key,))
            if now_ms - t["exit_time"] > TRADE_SEND_MS:
                _msg_put(conn, key, "exit", now_ms)
                continue
            outs = [(ex, exit_outcome(ex, conns[ex.name], key, t)) for ex in infos]
            if any(o["status"] == "open" for _e, o in outs) and now_ms - t["exit_time"] < ENTRY_WAIT_MS:
                continue
            text = win_text(t, outs, paper, now_ms, exp, infos)
            if send(INFO, text) is not False:
                _msg_put(conn, key, "exit", now_ms, now_ms, INFO, text)
                out.append(("exit", key, INFO, text))
        conn.execute("DELETE FROM trade_msgs WHERE first_ts < ?", (now_ms - 30 * DAY,))
        conn.commit()
    finally:
        pc.close()
        for c in conns.values():
            if c is not None:
                c.close()
    return out


# ---------------------------------------------------------------- 🚦 🏁 ▶️ ⏹: changes, sent once each (live_state)
STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_state (
    k TEXT PRIMARY KEY,
    v TEXT,
    ts INTEGER NOT NULL
);
"""
LIGHT_WORD = {"green": "다시 따라갑니다(새 진입부터)", "red": "새 진입을 따라가지 않습니다(페이퍼는 계속 거래, 기준을 넘으면 "
              "다시 따라감)"}


def _state_get(conn, k: str) -> Optional[str]:
    r = conn.execute("SELECT v FROM live_state WHERE k = ?", (k,)).fetchone()
    return None if r is None else r[0]


def _state_put(conn, k: str, v: str, ts: int) -> None:
    conn.execute("INSERT OR REPLACE INTO live_state VALUES (?,?,?)", (k, v, ts))


def light_change_text(ex: ExecInfo, old: str, L: dict) -> str:
    num = (f"최근 {L['n']}번 {L['wins']}승({L['wins'] / L['n']:.0%}) · 기준 {L['need']:.0%}"
           if L["state"] in ("green", "red") else f"근거 쌓는 중({L['have']}/{L['n']})")
    return (f"🚦 신호등 · {ex.label} {LIGHT_DOT.get(old, '⚪')}→{LIGHT_DOT[L['state']]} · {num}\n"
            f"{LIGHT_WORD.get(L['state'], '')}").rstrip()


def checkpoint_text(paper: list, execs: list, exp: Optional[dict], ref_ko: str = "") -> tuple[str, str]:
    """🏁 the 40th closed paper trade: the owners' pre-registered verdict (loud only under 82%). ``ref_ko`` (the
    reference was made for another config): the count only, silent, without the old bot's 88% / 82% rule."""
    f = win_stats(paper[:CHECK_N])
    rate = f["rate"] or 0.0
    if ref_ko:
        lines = [f"🏁 40번 도달 · 페이퍼 첫 40번 {f['wins']}승({rate:.1%})"]
        parts = [f"{ex.label} {n}번 {w}승" + (f"({w / n:.0%})" if n else "") for ex, (n, w) in execs]
        if parts:
            lines.append("실거래 " + " · ".join(parts))
        lines.append(f"참고: {CHECK_NO_RULE_KO} · {ref_ko}")
        return INFO, "\n".join(lines)
    verdict = ("늘리기 검토" if rate >= GROW - 1e-9 else "계속 지켜보기" if rate >= KEEP - 1e-9 else "멈추고 다시 생각")
    loud = rate < KEEP - 1e-9
    lines = [f"🏁 40번 도달 · 페이퍼 첫 40번 {f['wins']}승({rate:.1%}) → {verdict}",
             "미리 정한 기준: 88% 이상 늘리기 검토 / 82~88% 계속 지켜보기 / 82% 미만 멈추고 다시 생각"]
    parts = []
    for ex, (n, w) in execs:
        parts.append(f"{ex.label} {n}번 {w}승" + (f"({w / n:.0%})" if n else ""))
    if parts:
        lines.append("실거래 " + " · ".join(parts))
    hon = (((exp or {}).get("overall") or {}).get("honest") or {}).get("win_2025_26")
    lines.append("참고: 40번은 아직 작은 표본입니다"
                 + (f". 처음 보는 기간(2025-26) 백테스트 승률은 {hon:.0%}였습니다" if hon else ""))
    if loud:
        lines[0] = "🚨 " + lines[0]
        lines.append("지금 할 일: 미리 정한 대로 멈추고 다시 생각합니다. 실행기 끄는 법은 9장 표")
    return (CRITICAL if loud else INFO), "\n".join(lines)


def _last_event(c, kinds: tuple) -> Optional[tuple]:
    try:
        return c.execute(f"SELECT id, ts, kind FROM events WHERE kind IN ({','.join('?' * len(kinds))}) "
                         "ORDER BY id DESC LIMIT 1", kinds).fetchone()
    except sqlite3.Error:
        return None


def stopped_by_signal(c) -> Optional[int]:
    """The time the executor last stopped on a SIGTERM (a person's systemctl stop, or a server restart) when no
    start came after it; else None."""
    e = _last_event(c, ("start", "sigterm"))
    return int(e[1]) if e and e[2] == "sigterm" else None


def changes_pass(src: Sources, conn, now_ms: int, exp: Optional[dict], send: Callable,
                 infos: Optional[list] = None, ref_ko: str = "") -> list:
    """🚦 a signal light that changed, 🏁 the 40th paper trade, ▶️ / ⏹ an executor started / stopped by a signal.
    The first look only records (nothing is sent for what was already so). ``ref_ko``: the reference was made for
    another config (usable_expected): no 🏁 at all (the 88% / 82% rule is the old bot's). 🚦 only for an executor that
    runs the light (signal_light_n; off in the live configs since owners 10-19), and ▶️ names the light only then.
    Returns [(kind, key, level, text)]."""
    out = []
    infos = infos if infos is not None else (src.executors or load_executors())
    pc = open_ro(src.paper_db)
    paper = None
    if pc is not None:
        try:
            paper = paper_trades(pc, ACCOUNT)
        finally:
            pc.close()

    def emit(kind, key, level, text, k, v):
        if send(level, text) is not False:
            _state_put(conn, k, v, now_ms)
            out.append((kind, key, level, text))

    execs40 = []
    for ex in infos:
        c = open_ro(ex.db)
        try:
            # ▶️ / ⏹ from the executor's own start / SIGTERM events
            if c is not None:
                e = _last_event(c, ("start", "sigterm"))
                k = f"run:{ex.name}"
                if e is not None:
                    prev = _state_get(conn, k)
                    v = str(e[0])
                    if prev is None:
                        _state_put(conn, k, v, now_ms)
                    elif prev != v:
                        _bts, bot = get_state(c, "bot")
                        risk = (bot or {}).get("risk") or {}
                        if e[2] == "start":
                            eq = risk.get("last_equity")
                            L = light_state(paper or [], ex.light_n, ex.light_min)
                            text = (f"▶️ {ex.label} 실행기 켜짐"
                                    + (f" · 잔고 {fmt_usd(eq, sign=False)}" if eq is not None else "")
                                    + (f" · {light_text(L)}" if ex.light_on else ""))
                        else:
                            text = (f"⏹ {ex.label} 실행기 꺼짐 (끄라는 신호를 받음: 사람이 끔이나 서버 재시작)\n"
                                    "열린 포지션은 거래소 손절이 지킵니다. 다시 켜기: "
                                    f"sudo systemctl start {ex.unit}")
                        emit("run", k, INFO, text, k, v)
                if paper is not None:
                    try:
                        rows = c.execute("SELECT pnl FROM trades WHERE exit_ts IS NOT NULL").fetchall()
                    except sqlite3.Error:
                        rows = []
                    execs40.append((ex, (len(rows), sum(1 for (p,) in rows if (p or 0) > 0))))
            # 🚦 the light, when it changes
            if paper is not None and ex.light_n:
                L = light_state(paper, ex.light_n, ex.light_min)
                k = f"light:{ex.name}"
                prev = _state_get(conn, k)
                if prev is None:
                    _state_put(conn, k, L["state"], now_ms)
                elif prev != L["state"]:
                    emit("light", k, INFO, light_change_text(ex, prev, L), k, L["state"])
        finally:
            if c is not None:
                c.close()
    # 🏁 the 40th closed paper trade (counted from the paper bot's live start: its database). Not for a config the 5-year
    # reference was not made for (ref_ko, e.g. 규칙봇 15 from 10-20): its 88% / 82% rule is the old bot's and the
    # database's first 40 trades are the old bot's too; nothing is sent or recorded (a later config with its own
    # reference still gets its 🏁 once)
    if ref_ko:
        pass
    elif paper is not None and len(paper) >= CHECK_N and _state_get(conn, "checkpoint40") is None:
        level, text = checkpoint_text(paper, execs40, exp, ref_ko=ref_ko)
        emit("checkpoint", "checkpoint40", level, text, "checkpoint40", str(len(paper)))
    conn.commit()
    return out


# ---------------------------------------------------------------- 📋 the day ahead
def us_open_span(w1: int, mins) -> Optional[tuple]:
    """(from, to) ms of the paper bot's Nasdaq-open pause in the trading day that starts at ``w1`` (09:00 KST): the
    NYSE open (09:30 New York, the KST date of ``w1``) and ``mins`` after it, on NYSE weekdays that are not holidays
    (combo.py us_open_pause); None without the rule (config us_open_pause_min) or on a day without an open."""
    if not mins:
        return None
    from .sessions import NY, NYSE_HOLIDAYS
    d = _dt.datetime.fromtimestamp((int(w1) + KST_MS) / 1000, _dt.timezone.utc).date()
    if d.weekday() >= 5 or d.strftime("%Y-%m-%d") in NYSE_HOLIDAYS:
        return None
    a = int(_dt.datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp() * 1000)
    return a, a + int(mins) * MIN


def rest_line(w1: int, cfg: Optional[dict]) -> str:
    """오늘 진입 쉬는 시간: the US macro releases of the trading day ahead (±macro_blackout_min, data/macro_events.csv),
    the Nasdaq open pause (us_open_pause_min) and, on Friday, the weekend."""
    cfg = cfg or {}
    mins = cfg.get("macro_blackout_min", 30)
    parts = []
    if mins:
        try:
            from . import events as EV
            evs = [e for e in EV.all_events() if w1 - int(mins) * MIN <= e.ts_ms < w1 + DAY + int(mins) * MIN]
        except Exception:  # noqa: BLE001  the line says it could not be read
            evs = None
        if evs is None:
            parts.append((0, "경제 발표 일정을 못 읽음"))
        for e in evs or []:
            a, b = e.ts_ms - int(mins) * MIN, e.ts_ms + int(mins) * MIN
            when = kst(a) if (a + KST_MS) // DAY == (w1 + KST_MS) // DAY else "내일 " + kst(a)
            parts.append((a, f"{when}~{kst(b)} {EV.KIND_KO.get(e.kind, e.kind)}"))
    us = us_open_span(w1, cfg.get("us_open_pause_min"))
    if us is not None:
        parts.append((us[0], f"{kst(us[0])}~{kst(us[1])} 나스닥 개장"))
    parts = [x for _t, x in sorted(parts, key=lambda p: p[0])]
    line = "- 오늘 진입 쉬는 시간: " + (" · ".join(parts) if parts else "없음(미국 경제 발표 없음)")
    weekday = _dt.datetime.fromtimestamp((w1 + KST_MS) / 1000, _dt.timezone.utc).weekday()
    if weekday == 4 and cfg.get("no_weekend", True):
        line += "\n- 주말(토·일 KST)은 진입하지 않습니다"
    return line


# ---------------------------------------------------------------- 🤖 the live bot's Telegram setup (owners 10-19)
# The live side writes through its own bot (a new token from @BotFather) to each owner's private chat with it:
# /etc/paperbot/live-telegram.env, loaded by the live units after their own env file, carries the token and the chat
# lines. A token there without the chat lines would send to live.env's room, where the new bot is not:
# nothing would arrive, so the watcher says so once through live.env's own bot (the rule bot's room).
LIVE_ENV = "/etc/paperbot/live.env"
LIVE_TG_ENV = "/etc/paperbot/live-telegram.env"
TG_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_CRITICAL", "TELEGRAM_CHAT_WARN", "TELEGRAM_CHAT_INFO",
           "TELEGRAM_SOUND", "PAPERBOT_COMBO_TRADE_MSGS")
TG_SETUP_GRACE_MS = 10 * MIN       # the owners fill live-telegram.env in steps (token, chat-ids, chat lines)
TG_FIX = ("지금 할 일: chat-ids로 두 분 개인 채팅 번호를 찾아 live-telegram.env에 채팅 줄 3개"
          "(TELEGRAM_CHAT_CRITICAL·WARN·INFO)를 넣고 페이퍼 봇을 다시 켜기(12장 \"실거래 텔레그램을 개인 채팅으로\")")


def read_tg_env(path: str) -> Optional[dict]:
    """The Telegram lines of an EnvironmentFile (systemd's KEY=VALUE, '#' comments, optional quotes; a later line
    wins); None when it cannot be read. Every other line (an exchange key) is skipped, never kept."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    out = {}
    for line in lines:
        s = line.strip()
        if not s or s[0] in "#;" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() not in TG_KEYS:
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def tg_files(live_env: str = LIVE_ENV, override: str = LIVE_TG_ENV) -> dict:
    """{"base": live.env's Telegram lines (None: unreadable), "over": live-telegram.env's (None: no file or
    unreadable), "over_exists", "over_mtime" (ms)}."""
    try:
        mtime, exists = int(os.stat(override).st_mtime * 1000), True
    except OSError:
        mtime, exists = None, False
    return {"base": read_tg_env(live_env), "over": read_tg_env(override), "over_exists": exists, "over_mtime": mtime}


def tg_effective(t: dict, environ=None) -> dict:
    """The Telegram values in effect, as the live units load them: live.env, then live-telegram.env over it; the
    process environment only for what neither file says (or when they cannot be read)."""
    env = os.environ if environ is None else environ
    eff = {k: env[k] for k in TG_KEYS if k in env}
    eff.update(t.get("base") or {})
    eff.update(t.get("over") or {})
    return eff


def tg_source(t: dict) -> str:
    """Where the token in effect comes from, in the owners' words."""
    if (t.get("over") or {}).get("TELEGRAM_BOT_TOKEN"):
        return "live-telegram.env(실거래 전용 봇)"
    if (t.get("base") or {}).get("TELEGRAM_BOT_TOKEN"):
        return "live.env(규칙봇)"
    return "환경 변수"


def tg_problem(t: dict) -> Optional[tuple]:
    """(kind, text) when live-telegram.env cannot reach the owners: a new bot token whose chats are still live.env's
    (the rule bot's room, where the new bot is not), or an empty CRITICAL chat line. None when fine or not judged
    (live.env unreadable, no override)."""
    base, over = t.get("base"), t.get("over")
    if base is None or not over:
        return None
    if "TELEGRAM_CHAT_CRITICAL" in over and not chat_ids(over["TELEGRAM_CHAT_CRITICAL"]):
        return "empty", ("🚨 텔레그램 설정 · live-telegram.env의 TELEGRAM_CHAT_CRITICAL 줄이 비어 있습니다\n"
                         "실거래 메시지(진입·청산·알람)가 아무 데도 가지 않습니다. 이 메시지는 그래서 규칙봇 방으로 "
                         "보냅니다\n" + TG_FIX + ". 아직이면 그 줄 앞에 #를 붙여 두세요")
    bt = base.get("TELEGRAM_BOT_TOKEN", "")
    et = over.get("TELEGRAM_BOT_TOKEN") or bt
    bc = chat_ids(base.get("TELEGRAM_CHAT_CRITICAL"))
    ec = chat_ids(over["TELEGRAM_CHAT_CRITICAL"]) if "TELEGRAM_CHAT_CRITICAL" in over else bc
    # a private chat's id is the person's own id, the same for every bot: the new bot reaches it once that person
    # pressed Start (chat-ids lists it), so only a shared group or channel (negative id, @name) means "still the rule
    # bot's room" (owners 10-19: the rule bot already wrote to a private chat, the live lines were right)
    if et and et != bt and set(ec) == set(bc) and not all(str(c).strip().isdigit() for c in ec):
        return "token", ("🚨 텔레그램 설정 · 실거래 전용 봇의 채팅 줄이 없습니다\n"
                         "live-telegram.env에 새 봇 토큰은 있는데 채팅 번호가 live.env(규칙봇 방) 그대로입니다. 새 봇은 "
                         "규칙봇 방에 없어서 실거래 메시지(진입·청산·알람)가 가지 않습니다. 이 메시지는 그래서 규칙봇 "
                         "방으로 보냅니다\n" + TG_FIX)
    return None


def tg_status(t: dict) -> str:
    """One doctor line for ``show``: where the live messages go (never a token; chats counted, not listed)."""
    base, over = t.get("base"), t.get("over")
    if base is None:
        return "텔레그램 설정: live.env를 못 읽음(서버에서 paperbot 사용자로 실행하면 보입니다)"
    prob = tg_problem(t)
    if prob is not None:
        return "⚠ " + prob[1].removeprefix("🚨 ")
    if t.get("over_exists") and over is None:
        return ("⚠ 텔레그램 설정: live-telegram.env를 못 읽음. 지금 할 일: sudo chown root:paperbot "
                f"{LIVE_TG_ENV} && sudo chmod 640 {LIVE_TG_ENV}")
    eff = tg_effective(t, environ={})
    n = len(chat_ids(eff.get("TELEGRAM_CHAT_CRITICAL")))
    mode = str(eff.get("TELEGRAM_SOUND", "")).strip().lower()
    sound = {"critical": "🚨만 소리", "1": "🚨·경고 소리"}.get(mode, "모두 무음")
    if not over:
        return f"텔레그램 설정: 실거래 메시지도 live.env의 봇·방으로 갑니다(live-telegram.env 없음, 12장) · {sound}"
    return (f"텔레그램 설정: {tg_source(t)} → 채팅 {n}곳 · {sound}"
            + (" · 페이퍼 봇 날것 진입·청산 줄 끔" if eff.get("PAPERBOT_COMBO_TRADE_MSGS", "").strip() == "0" else ""))


def tg_base_send(t: dict) -> Optional[Callable]:
    """live.env's own bot and room (the rule bot's), for the one message the live chats cannot carry."""
    from .notify import TelegramNotifier
    base = t.get("base") or {}
    if not base.get("TELEGRAM_BOT_TOKEN") or not chat_ids(base.get("TELEGRAM_CHAT_CRITICAL")):
        return None
    return TelegramNotifier(env=base).send


def tg_pass(conn, now_ms: int, t: dict, send_base: Optional[Callable], send: Callable) -> list:
    """🚨 once (through live.env's bot) when live-telegram.env cannot reach the owners, after it has stayed so for
    TG_SETUP_GRACE_MS (the owners fill it in steps); ✅ through the live chats once it is fixed (live_state
    'tg_setup')."""
    out = []
    prob = tg_problem(t)
    prev = _state_get(conn, "tg_setup")
    if prob is None:
        if prev and t.get("base") is not None:
            text = "✅ 텔레그램 설정이 맞춰졌습니다 · 실거래 메시지는 live-telegram.env의 봇과 채팅으로 갑니다"
            if send(INFO, text) is not False:
                conn.execute("DELETE FROM live_state WHERE k = 'tg_setup'")
                out.append(("tg_clear", "tg_setup", INFO, text))
        conn.commit()
        return out
    kind, text = prob
    if prev == kind:
        return out
    if t.get("over_mtime") is not None and now_ms - int(t["over_mtime"]) < TG_SETUP_GRACE_MS:
        return out                       # being filled in right now
    if send_base is not None and send_base(CRITICAL, text) is not False:
        _state_put(conn, "tg_setup", kind, now_ms)
        out.append(("tg_setup", "tg_setup", CRITICAL, text))
    conn.commit()
    return out


# ====================================================================== commands
def _notifier():
    """The live messages' notifier (paperbot/notify.py TelegramNotifier; shared with paperbot/liveimprove.py). Where
    they go and what rings comes from the environment: the units load /etc/paperbot/live-telegram.env after live.env
    (the owners' private chats in TELEGRAM_CHAT_*, comma-separated, and TELEGRAM_SOUND=critical: the 🚨 messages are
    CRITICAL and ring, everything else is INFO and silent). The console without a bot token or a chat."""
    from .notify import ConsoleNotifier, TelegramNotifier
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        return TelegramNotifier()
    return ConsoleNotifier()


live_notifier = _notifier


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
        exp, ref_ko = usable_expected(src)    # another config's reference: None, and one note says so
        notes = reference_notes(exp, src, ref_ko)
        if not dry_run:                       # cards the watcher has not made yet (stored, not sent) and noise checks
            cards_pass(src, out_conn, now_ms, exp, send=None, infos=infos, older_only=True, ref_ko=ref_ko)
        cards = stored_cards(out_conn, w0, w1)
        drift = drift_line(drift_state(trades, exp)) if (paper is not None and exp is not None) else None
        ccfg = None
        lc = open_ro(src.paper_db)
        if lc is not None:
            try:
                ccfg = combo_config(src, lc)[0]
            finally:
                lc.close()
        missed = None
        try:                                  # 못 탄 신호 (the watcher's table): one quiet line, never in the way of the check
            from .livemissed import morning_line
            missed = morning_line(out_conn, trades, (paper or {}).get("pos_entry"), w0, w1)
        except Exception as exc:  # noqa: BLE001
            print(f"missed line: {type(exc).__name__}: {exc}", file=sys.stderr)
        level, text, loud = compose(day, w0, w1, parity, paper, execs, shadows, week, cards=cards, drift=drift,
                                    notes=notes, now_ms=now_ms, rest=rest_line(w1, ccfg), missed=missed, ref_ko=ref_ko)
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


def reference_notes(exp: Optional[dict], src: Sources, ref_ko: str = "") -> list:
    """One line when the backtest reference is missing, or made for another config than the running one
    (``src.combo_config``; ref_config_problem's reason: then nothing is compared with it)."""
    why = ref_ko or ref_config_problem(exp, src.combo_config)
    if why:
        return [why]
    if exp is None:
        return [f"백테스트 기준표({src.expected})를 못 읽어 손실 카드·기대 범위 비교 없음"]
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


def private_chats(updates: list) -> list:
    """[(chat id, first name, username, last message ms)] of the private chats in getUpdates' answer, newest first."""
    seen: dict = {}
    for u in updates or []:
        if not isinstance(u, dict):
            continue
        for k in ("message", "edited_message", "my_chat_member"):
            m = u.get(k) or {}
            chat = m.get("chat") or {}
            if chat.get("type") != "private" or "id" not in chat:
                continue
            when = int(m.get("date") or 0) * 1000
            prev = seen.get(chat["id"])
            if prev is None or when > prev[3]:
                seen[chat["id"]] = (chat["id"], chat.get("first_name") or "", chat.get("username") or "", when)
    return sorted(seen.values(), key=lambda x: -x[3])


def chat_ids_text(token: str, fetch: Optional[Callable] = None, source: Optional[str] = None) -> str:
    """The owners' private chat ids as the bot saw them (getMe and getUpdates: reads only, sends nothing). The token
    is never printed, not even in an error. ``source``: where the token came from (tg_source)."""
    import urllib.request
    if not token:
        return ("TELEGRAM_BOT_TOKEN이 없습니다: live-telegram.env와 live.env를 읽을 수 있는 paperbot 사용자로 "
                "실행하세요(12장의 명령)")
    get = fetch if fetch is not None else (lambda u: urllib.request.urlopen(u, timeout=20).read())
    head = []
    try:                                 # which bot this is (the owners check it is the live bot)
        me = json.loads(get(f"https://api.telegram.org/bot{token}/getMe"))
        name = ((me or {}).get("result") or {}).get("username") if isinstance(me, dict) else None
    except Exception:  # noqa: BLE001  only a label; getUpdates below reports the error
        name = None
    if name or source:
        head.append(f"봇: {('@' + name) if name else '(이름 못 읽음)'}" + (f" · 토큰: {source}" if source else ""))
    if source and source.startswith("live.env"):
        head.append("주의: 아직 규칙봇 토큰입니다. 실거래 전용 봇 토큰을 live-telegram.env에 먼저 넣으세요(12장)")
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100&timeout=0"
    try:
        got = json.loads(get(url))
    except Exception as exc:  # noqa: BLE001  the type only: an error text could carry the URL with the token
        code = getattr(exc, "code", None)
        return (f"텔레그램에 묻지 못했습니다({type(exc).__name__}{f' {code}' if code else ''}). "
                + ("봇 토큰을 확인하세요" if code in (401, 404) else "잠시 뒤 다시 해 보세요"))
    chats = private_chats(got.get("result") if isinstance(got, dict) else [])
    if not chats:
        return "\n".join(head + ["최근 개인 채팅이 없습니다. 각자 텔레그램에서 봇을 열어 시작(Start)을 누르고 "
                                 "\"hi\"를 보낸 뒤 다시 실행하세요(봇은 시작을 누른 사람에게만 보낼 수 있습니다)"])
    lines = head + ["개인 채팅 (번호 · 이름 · 아이디 · 마지막 메시지)"]
    for cid, name, user, when in chats:
        lines.append(f"{cid} · {name or '-'} · {('@' + user) if user else '-'} · "
                     + (kst_dt(when) if when else "-"))
    ids = ",".join(str(c[0]) for c in chats)
    lines.append(f"live-telegram.env의 세 줄에 넣을 값: {ids}  (두 분 것만 남기세요)")
    return "\n".join(lines)


def cmd_chat_ids(a) -> int:
    """The token in effect: live.env, then live-telegram.env over it (as the live units load them)."""
    t = tg_files(a.live_env, a.live_telegram_env)
    print(chat_ids_text(str(tg_effective(t).get("TELEGRAM_BOT_TOKEN", "")).strip(), source=tg_source(t)))
    return 0


def cmd_preview(a) -> int:
    from .livepreview import main as preview_main
    return preview_main("ac" if getattr(a, "old", False) else "live15")


def cmd_show(a) -> int:
    try:
        return _show(a)
    finally:                             # where the live messages go (the live bot's setup), last
        print("\n" + tg_status(tg_files(a.live_env, a.live_telegram_env)))


def _show(a) -> int:
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
        p.add_argument("--combo-config", default=running_combo_config(),
                       help="the config the paper bot runs (default: PAPERBOT_LIVE_COMBO_CONFIG, else /etc/paperbot/combo.json)")
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
    w = sub.add_parser("watch", help="one pass of the real-time watcher (every minute by its timer)")
    common(w)
    w.add_argument("--dry-run", action="store_true", help="print what would be sent: no Telegram, nothing written")
    pv = sub.add_parser("preview", help="print one sample of every live Telegram message (hand-made world, sends nothing)")
    pv.add_argument("--old", action="store_true", help="the A+C bot's world (light, halts, 5-year reference) instead of "
                                                      "규칙봇 15's")
    c = sub.add_parser("chat-ids", help="the owners' private chat ids the bot in effect has seen (getUpdates; sends "
                                        "nothing, never prints the token)")
    s = sub.add_parser("show", help="print a stored check and where the live messages go")
    s.add_argument("--db", default=DEFAULT_DB)
    s.add_argument("--day", default=None)
    for p in (c, s):
        p.add_argument("--live-env", default=LIVE_ENV, help=argparse.SUPPRESS)
        p.add_argument("--live-telegram-env", default=LIVE_TG_ENV, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    return {"run": cmd_run, "watch": cmd_watch, "show": cmd_show, "preview": cmd_preview,
            "chat-ids": cmd_chat_ids}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
