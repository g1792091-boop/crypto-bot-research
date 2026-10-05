"""Nightly checks for the paper run (v3, and v4 with its account groups; separate process, its own database).

    python -m paperbot.daily3 run --db paper3.db --out daily3.db [--day YYYY-MM-DD] [--no-notify]
        [--brackets FILE | --allow-example-brackets]

Re-running a day (``--day``) replaces that day's report and mismatches in daily3.db (shadow rows by key).

For one UTC day (default: yesterday):

1. Replay parity. Start every account from the ``day:<date>`` snapshot the live
   runner saved at 00:00, feed it the day's 1m bars (last and mark price, funding,
   fetched again from Binance) and the day's submitted signals from signal_log,
   and compare the trades with the ones the live run recorded. Any difference is
   a mismatch (engine bug, restart problem or revised exchange data).
   Extra accounts (paperbot/extras.py) are replayed with their own rules: a copy's
   settings (first lock) and stop distance, its parent's signals of bars closing
   after its start (minus the ones its skip tag drops), an account started during
   the day from its start, and no signals while suspended / no steps while held
   (state ``extras`` events). A copy that lost one boundary's signal in a restart
   (killed between the originals' commit and the copy's) is reported for that copy
   only, as "추가 계좌 재시작 틈".
   Paper v4 (owners' D2 (ii), D4): the original accounts are every kind in ``accounts.ORIGINAL_KINDS`` (core
   "strategy", coin flips "random", DeepSeek "ds200", the reel "reel"), all on the book's settings. The reel and the
   three 5m coin flips replay on their live engine class (``engine_classes``: paperbot/reel_engine.py ``ReelEngine``,
   the reel's own exits) and their signals are rebuilt from the entry levels the runner logged (signal_log data
   ``reel``: absolute stop, first target, the 19 closes; ``make_signal``). A logged ``stop_dist`` is used when present.
   The report splits parity and the day's trades by group (``parity.groups``, ``trades.groups``) and the 09:20 text
   reads "재계산 일치 331/331 (매매법 144/144 · 딥시크 171/171 · 5분 단타 1/1 · 동전 15/15)".
   Early 1m klines (``explain_mismatches``): the live feed takes a 1m kline as soon as the minute has closed and
   never reads it again, so a kline read within a second of its close can miss the minute's last trades (a less
   extreme high/low); live then exits later than the replay on the final klines. A mismatch is labelled
   ``early_kline`` only with proof: (i) when the live runner recorded the bars it stepped on (paper3.db
   ``live_bars``), the day is replayed ALSO on live's own bars; a mismatch that disappears there, where live's bar
   of the trigger minute has the same open and a less extreme high/low (or a lower volume) than the final kline,
   is early_kline; one that persists on live's own bars is an engine / parity problem and stays CRITICAL.
   (ii) Without live bars for the trigger minute, the public aggregate trades of that minute must show the trade
   that reached the replay's stop in the last ``EARLY_WINDOW_MS`` of the minute, with the same entry / size / stop
   on both sides, the replay exiting in that minute and live later (at a later bar's open beyond its stop or at
   its stop on a later bar), and no feed warning; and this must hold for every mismatched account of that
   coin-minute. Early-kline accounts are counted apart (``parity.early_kline``), like the restart gaps: a line of the silent
   INFO summary, no CRITICAL, no incident meeting (paperbot/agents/triggers.py). docs/signal-recording.md has the background.
2. Shadows (no accounts): for every submitted signal of the day
   - limit: would a limit order 0.25 ATR better than the reference price have
     filled within one bar of the signal's timeframe, and with what net ROE under
     the same exit rules;
   - skipped: for signals an account skipped (position open, lower priority), the
     net ROE the trade would have had;
   - stop1.5/2.5/3.0: each losing trade with a different initial stop;
   - trade variants (paperbot/obsshadows.py, pre-registered in docs/observation-shadows.md):
     every trade that closed in the day re-run with first lock 0.15/0.20/0.30, a time
     stop, and fixed 10x/20x leverage, plus the unchanged rules as a control; and (docs/
     observation-shadows-2.md) the sizing tier picked by the signal's recorded entry strength.
     docs/observation-shadows-3.md adds fixed 30x / 40x / 50x (tier margin share) and a 1.5 / 2.5 / 3 ATR stop at
     the real trade's leverage (stopw1.5 / stopw2.5 / stopw3). docs/observation-shadows-4.md adds fixed
     take-profits at 1 / 1.5 / 2 / 3 R without the ladder and the ladder capped at 2R (tp1R .. tp3R, ladder_cap2R),
     fixed 20x / 30x / 40x / 50x with margin = leverage % (lev20m20 .. lev50m50), and per account the shadow
     equity curves of the leverage variants and the base (daily3.db shadow_curves, obsshadows.write_curves).
   Each shadow trade runs alone on a fresh account (the starting equity) so results are comparable as ROE.
   Accounts with their own exits (paper v4's reel and 5m coin flips) run their limit and skipped shadows on their own
   engine; they get no stop what-ifs and no trade variants (both vary the house exits they do not use); a signal the
   reel's own entry rules skipped is no "skipped" shadow. DeepSeek runs the house exits and is shadowed like the 36.
3. Data quality: missing minutes, zero-volume minutes, extreme ranges, last vs
   mark price gaps, extreme funding.
4. Realistic stop slippage (descriptive, paperbot/slipcost.py): for every SL / LOCK / LIQ exit of the day, where a
   real STOP_MARKET (contract price) of the trade's size would have filled, from the public aggregate trades of
   the exit minute from the first trade at or through the stop (the trigger) for ``slipcost.WINDOW_MS``, and the
   order-book read the live runner recorded for that exit (fill_costs) when there is one. One row per exit in
   daily3.db ``stop_slips`` and a summary (median, p90, worst, total $ beyond paper; per strategy, timeframe,
   coin) in the report's ``stop_slippage``. The coin-minutes with the most exit notional first, at most
   ``STOP_MAX_MINUTES`` of them, ``STOP_MAX_PAGES`` pages each and ``STOP_MAX_TOTAL_PAGES`` a night (weight 20 a
   page, paced); exits past a cap or a failed request are recorded with their status, never fatal.
5. Cost at a larger size (descriptive): from the day's fill_costs book reads, the slippage if the order had been
   2x / 5x / 10x the paper size, per coin and timeframe (report ``size_costs``; slipcost.summarize_size_costs).

Paper v4 additions to the report and the 09:20 text (gap pass, owners 2026-10-05):
- The run's start day (G25): the day the run started after its 00:00 UTC has no ``day:<date>`` snapshot by design.
  When the original accounts' MIN(created_ts) is after the day's start, the report says so (``start_day``; parity
  stays a string) and the 09:20 text is the silent INFO line "시작한 날: 재계산 없음", not the WARN "재계산 못 함".
- Shadows and the stop slippage by group (G28): ``shadows.groups`` and ``stop_slippage.groups``. The text gives
  numbers for the groups with per-trade Telegram (core, reel, extras; groups.TRADE_ALERT_GROUPS) and one count line
  for DeepSeek; the coin flips stay in the report only. The stop-slippage caps read the core / reel exits first
  (``STOP_GROUP_RANK``), so a busy DeepSeek night cannot crowd them out.
- The DeepSeek nightly recomputation (paperbot/dscheck.py, 00:30 UTC): its last one-line summary
  (``dscheck.read_summary``) is a line of the text. That check runs after this report, so the line is the night
  before's (it names its own day); "결과 없음" when it has not run (its timer is switched on after the reset checks).

paper3.db is opened read-only; results go to ``--out``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from dataclasses import replace
from typing import Optional

import numpy as np

from .accounts import DAY_MS, GROUP_OF_KIND, ORIGINAL_KINDS, HeldEngine, day_key, original_engine_cls
from .aggregate import TF_MS
from .binance import BinanceError, BinanceREST, bars_from_klines
from .config import V3_STOP_ATR, V3_SYMBOLS, Settings, v3_settings
from .engine import PaperEngine, restore_engine
from .models import Bar, Signal
from .cards import STOP_VARIANTS
from .notify import CRITICAL, INFO, WARN
from .obsshadows import LOOKBACK_MS, first_signal, summarize, trade_shadows, write_curves

MIN = 60_000
LIMIT_ATR = 0.25
DSCHECK_DIR = "/var/lib/paperbot/dscheck"     # paperbot/dscheck.py DEFAULT_OUT (its last.txt: one Korean line)

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (day TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mismatches (day TEXT NOT NULL, account_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadows (
    key TEXT PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL, account_id TEXT NOT NULL,
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, side INTEGER NOT NULL,
    filled INTEGER, roe REAL, exit_reason TEXT, resolved INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stop_slips (
    key TEXT PRIMARY KEY, day TEXT NOT NULL, account_id TEXT NOT NULL, strategy TEXT, timeframe TEXT,
    symbol TEXT NOT NULL, exit_reason TEXT NOT NULL, exit_time INTEGER NOT NULL, status TEXT NOT NULL,
    paper_bps REAL, real_bps REAL, diff_usd REAL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS stop_slips_day ON stop_slips (day);
CREATE INDEX IF NOT EXISTS stop_slips_exit ON stop_slips (exit_time);
"""


# ---------------------------------------------------------------- data
def fetch_steps(rest: BinanceREST, symbols, start: int, end: int) -> list[tuple[int, dict, dict]]:
    """Aligned 1m steps (with mark prices and funding) for [start, end)."""
    bars: dict[int, dict] = {}
    fund: dict[int, dict] = {}
    for s in symbols:
        t = start
        while t < end:
            rows = [r for r in rest.klines(s, "1m", start_time=t, limit=1500) if int(r[0]) < end]
            if not rows:
                break
            marks = rest.mark_klines(s, "1m", start_time=t, limit=1500)
            for b in bars_from_klines(s, rows, marks):
                bars.setdefault(b.open_time, {})[s] = b
            t = int(rows[-1][0]) + MIN
            if len(rows) < 1500:
                break
        for r in rest.funding_rates(s, start_time=start):
            ft = int(r["fundingTime"])
            if start <= ft < end:
                fund.setdefault(ft - ft % MIN, {})[s] = float(r["fundingRate"])
    return [(t, bars[t], fund.get(t, {})) for t in sorted(bars)]


def day_signals(conn, start: int, end: int, with_data: bool = False) -> dict[int, list[dict]]:
    """Submitted signals whose bar closed in [start, end], by bar close (``with_data``: also the row's data
    JSON text, for the copies' skip tags)."""
    out: dict[int, list[dict]] = {}
    cols = ("bar_close", "timeframe", "strategy", "symbol", "side", "atr", "ref_price", "ref_time", "delay_ms")
    if with_data:
        cols += ("data",)
    q = (f"SELECT {', '.join(cols)} "
         "FROM signal_log WHERE status = 'SUBMITTED' AND bar_close > ? AND bar_close <= ? ORDER BY id")
    for r in conn.execute(q, (start, end)):
        d = dict(zip(cols, r))
        out.setdefault(d["bar_close"], []).append(d)
    return out


def make_signal(d: dict, stop_atr: Optional[float] = None, ref: Optional[float] = None) -> Signal:
    """The signal_log row as the runner submitted it. With the row's ``data`` (``day_signals(with_data=True)``)
    the signal carries its ctx as the live one does, so the quality_v1 leverage group (levrule: the recorded
    strength) is the live account's; without it a strategy signal has no strength and sizes as "normal".

    Stop: ``stop_atr`` x ATR when given (the stop what-ifs, a copy's own stop); otherwise the row's logged
    ``data.stop_dist`` when the runner recorded one, else V3_STOP_ATR x ATR (every house signal of v3 and v4).
    A row whose data carries ``reel`` (paper v4: the reel and the 5m coin flips, the entry levels sigservice put
    into the live signal's ``meta["reel"]``, paperbot/reelsig.py) is rebuilt as the reel's signal
    (paperbot/reel_engine.py contract): the absolute stop ``reel.stop``, the first target ``reel.up_band`` as
    ``tp_price``, ``meta["reel"]`` as logged and no ``stop_dist`` (``stop_atr`` does not apply). A logged
    ``data.lev_group`` is carried as ``meta["lev_group"]`` (levrule.signal_group reads it first)."""
    data = _data_of(d) if "data" in d else {}
    ref_price = ref if ref is not None else d["ref_price"]
    reel = data.get("reel")
    if isinstance(reel, dict):
        meta = {"ref_price": ref_price, "ref_time": d["ref_time"], "delay_ms": d["delay_ms"],
                "account": f"{d['strategy']}@{d['timeframe']}", "reel": reel}
        if isinstance(data.get("ctx"), dict):
            meta["ctx"] = data["ctx"]
        if data.get("lev_group") is not None:
            meta["lev_group"] = data["lev_group"]
        return Signal(ts=d["bar_close"] - 1, symbol=d["symbol"], timeframe=d["timeframe"], strategy_id=d["strategy"],
                      side=int(d["side"]), stop_price=_num(reel.get("stop")), tier="best",
                      tp_price=_num(reel.get("up_band")), atr=d["atr"], meta=meta)
    if stop_atr is None and _num(data.get("stop_dist")) > 0:
        dist = float(data["stop_dist"])
    else:
        dist = (V3_STOP_ATR if stop_atr is None else stop_atr) * d["atr"]
    meta = {"stop_dist": dist, "ref_price": ref_price,
            "ref_time": d["ref_time"], "delay_ms": d["delay_ms"], "account": f"{d['strategy']}@{d['timeframe']}"}
    if "data" in d:
        meta["ctx"] = _ctx_of(d)
    if data.get("lev_group") is not None:
        meta["lev_group"] = data["lev_group"]
    return Signal(ts=d["bar_close"] - 1, symbol=d["symbol"], timeframe=d["timeframe"], strategy_id=d["strategy"],
                  side=int(d["side"]), stop_price=0.0, tier="best", atr=d["atr"], meta=meta)


def _num(x) -> float:
    """A finite float, else NaN (a malformed logged level: the engine then rejects the signal as live did)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) else float("nan")


def _data_of(d: dict) -> dict:
    """A signal_log row's data JSON as a dict ({} when missing or malformed)."""
    raw = d.get("data")
    try:
        data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- 1. replay parity
EXTRA_STATUS = {"created": "active", "resumed": "active", "suspended": "suspended", "held": "held"}


def extras_of(conn) -> dict:
    """The extra accounts of a paper3.db as the replay needs them: {aid: {kind, parent, created_ts, rule,
    stop_atr, skip_tag, timeline [(effective ms, status)]}} (``{}`` for a database without extras)."""
    from .extras import parse_rule, rule_fields
    rows = conn.execute("SELECT account_id, kind, parent, created_ts, data FROM accounts "
                        f"WHERE kind NOT IN ({', '.join('?' * len(ORIGINAL_KINDS))}) ORDER BY rowid",
                        ORIGINAL_KINDS).fetchall()
    if not rows:
        return {}
    st = conn.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()
    events = (json.loads(st[0]).get("events") or []) if st else []
    out = {}
    for aid, kind, parent, created, data in rows:
        try:
            d = json.loads(data or "{}")
        except ValueError:
            d = {}
        rule = parse_rule(d.get("rule")) if kind == "copy" else None
        f = rule_fields(rule)
        tl = [(int(created), "active")]
        for ev in events:
            if ev.get("account_id") == aid and ev.get("event") in EXTRA_STATUS and ev.get("event") != "created":
                tl.append((int(ev.get("effective", ev.get("ts", 0)) or 0), EXTRA_STATUS[ev["event"]]))
        tl.sort(key=lambda x: x[0])
        out[aid] = {"kind": kind, "parent": parent, "created_ts": int(created), "rule": rule,
                    "stop_atr": f["stop_atr"], "skip_tag": f["skip_tag"], "timeline": tl}
    return out


def account_rows(conn) -> dict:
    """{aid: {"kind", "timeframe", "data"}} of the accounts table ({} for a database without one)."""
    try:
        rows = conn.execute("SELECT account_id, kind, timeframe, data FROM accounts").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {aid: {"kind": kind, "timeframe": tf, "data": data} for aid, kind, tf, data in rows}


def engine_classes(conn, rows: Optional[dict] = None) -> dict:
    """{aid: engine class} of the ORIGINAL accounts that the live book does not run on ``PaperEngine``, built the way
    AccountBook builds them (``accounts.original_engine_cls`` from the row's kind, timeframe and data): paper v4's
    reel and 5m coin flips run ``paperbot.reel_engine.ReelEngine`` (owners' D2 (ii), D4); when that class cannot be
    loaded the live book holds those accounts (``HeldEngine``) and so does the replay. Every other account (all of a
    v3 database) is absent: ``PaperEngine``, exactly as before."""
    out = {}
    for aid, r in (account_rows(conn) if rows is None else rows).items():
        if r["kind"] not in ORIGINAL_KINDS:
            continue
        try:
            cls = original_engine_cls(r["kind"], r["timeframe"], r["data"])
        except Exception:  # noqa: BLE001  as live: a reel engine module that fails to load holds its accounts
            cls = HeldEngine
        if cls is not None:
            out[aid] = cls
    return out


def run_start_ts(conn) -> Optional[int]:
    """MIN(created_ts) of the run's ORIGINAL accounts (the run's start; extras start later), None without them."""
    try:
        r = conn.execute(f"SELECT MIN(created_ts) FROM accounts WHERE kind IN ({', '.join('?' * len(ORIGINAL_KINDS))})",
                         ORIGINAL_KINDS).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(r[0]) if r and r[0] is not None else None


def dscheck_line(out_dir: Optional[str]) -> Optional[str]:
    """The DeepSeek nightly recomputation's last one-line summary (paperbot/dscheck.py ``read_summary``), None when
    it never ran or cannot be read. Never raises."""
    if not out_dir:
        return None
    try:
        from .dscheck import read_summary
    except Exception:  # noqa: BLE001  (its module needs pandas and the research code: read the file itself)
        read_summary = None
    try:
        if read_summary is not None:
            return read_summary(out_dir)
        with open(os.path.join(out_dir, "last.txt"), encoding="utf-8") as fh:
            return fh.readline().strip() or None
    except Exception:  # noqa: BLE001  (a line of the report, never the night's failure)
        return None


def account_groups(conn, rows: Optional[dict] = None) -> dict:
    """{aid: group} for the report's split (accounts.GROUP_OF_KIND: core, ds200, reel, flip, extra; "other" for an
    unknown kind)."""
    return {aid: GROUP_OF_KIND.get(r["kind"], "other") for aid, r in (account_rows(conn) if rows is None
                                                                       else rows).items()}


def extra_status(x: dict, ts: int) -> str:
    """An extra's state at time ``ts`` (the last timeline entry at or before it)."""
    cur = "active"
    for t, status in x["timeline"]:
        if t <= ts:
            cur = status
        else:
            break
    return cur


def _ctx_of(d: dict) -> dict:
    ctx = _data_of(d).get("ctx")
    return ctx if isinstance(ctx, dict) else {}


def replay(settings: Settings, brackets, specs, snapshot: dict, signals: dict, steps,
           extras: Optional[dict] = None, engine_cls: Optional[dict] = None) -> dict[str, list]:
    """Replay the day from the 00:00 snapshot. ``extras`` (``extras_of``): the extra accounts' own rules,
    starts during the day and suspended / held intervals; the original accounts use ``settings`` unchanged.
    ``engine_cls`` (``engine_classes``): the original accounts with their own engine class (paper v4: the reel and
    the 5m coin flips replay on ``ReelEngine`` with the reel's exits, their signals rebuilt by ``make_signal``
    from the logged entry levels); every other account replays on ``PaperEngine``."""
    from .extras import settings_for, skip_hit
    extras = extras or {}
    engine_cls = engine_cls or {}
    engines = {}

    def make(aid):
        x = extras.get(aid)
        if x is None:
            return engine_cls.get(aid, PaperEngine)(settings, brackets, symbol_specs=specs, book=aid)
        return PaperEngine(settings_for(settings, x["rule"]), brackets, symbol_specs=specs, book=aid)
    for aid, st in snapshot["engines"].items():
        e = make(aid)
        restore_engine(e, st)
        engines[aid] = e
    later = sorted((x["created_ts"], aid) for aid, x in extras.items() if aid not in engines)
    copies: dict[str, list[str]] = {}
    for aid, x in extras.items():
        if x["kind"] == "copy" and x["parent"] and x["rule"] is not None:
            copies.setdefault(x["parent"], []).append(aid)
    for ts, bars, funding in steps:
        while later and later[0][0] <= ts:              # started during the day: fresh at the initial equity
            aid = later.pop(0)[1]
            engines[aid] = make(aid)
        tb = {s: b for s, b in bars.items() if s in brackets}
        for aid, e in engines.items():
            if aid in extras and extra_status(extras[aid], ts) == "held":
                continue
            e.step(tb, funding)
            e.outcomes.clear()
        bc = ts + MIN
        for d in signals.get(bc, []):
            aid = f"{d['strategy']}@{d['timeframe']}"
            if aid in engines and not (aid in extras and extra_status(extras[aid], ts) != "active"):
                engines[aid].submit(make_signal(d))
            for c in copies.get(aid, ()):
                x = extras[c]
                if c not in engines or x["created_ts"] >= bc or extra_status(x, ts) != "active":
                    continue
                if x["skip_tag"] and skip_hit(x["skip_tag"], int(d["side"]), _ctx_of(d)):
                    continue
                sig = make_signal(d, stop_atr=x["stop_atr"])
                sig.meta["account"] = c
                engines[c].submit(sig)
    return {aid: e.trades for aid, e in engines.items()}


CRASH_GAP_KO = "추가 계좌 재시작 틈"


def label_crash_gaps(mism: list[dict], extras: dict, conn, gap_ms: int = 10 * MIN) -> list[dict]:
    """Mark an extra's mismatch as a restart gap when its first replayed trade the live run does not have
    came from a signal bar followed by a runner start within ``gap_ms`` (the copy lost that boundary's
    signal in a restart; never a mismatch of the originals)."""
    starts = [int(r[0]) for r in conn.execute("SELECT started_ts FROM runs")]
    for m in mism:
        x = extras.get(m["account_id"])
        if x is None:
            continue
        stored = {tuple(t) for t in m.get("stored", [])}
        first = next((t for t in m.get("replayed", []) if tuple(t) not in stored), None)
        if first is None:
            continue
        bc = m.get("signal_bars", {}).get(str(first[1]))
        if bc is not None and any(bc <= s <= bc + gap_ms for s in starts):
            m["label"] = CRASH_GAP_KO
            m["crash_gap"] = True
    return mism


def _rkey(t) -> tuple:
    """A replayed trade (TradeRecord) as compare() sees it."""
    return (t.symbol, t.entry_time, t.exit_time, t.exit_reason, round(t.exit_price, 10), round(t.pnl, 6))


def _skey(t: dict) -> tuple:
    """A stored (live) trade as compare() sees it."""
    return (t["symbol"], t["entry_time"], t["exit_time"], t["exit_reason"], round(t["exit_price"], 10),
            round(t["pnl"], 6))


def compare(replayed: dict[str, list], stored: dict[str, list[dict]]) -> list[dict]:
    out = []
    for aid in sorted(set(replayed) | set(stored)):
        a = [_rkey(t) for t in replayed.get(aid, [])]
        b = [_skey(t) for t in stored.get(aid, [])]
        if a != b:
            out.append({"account_id": aid, "replayed": a[:20], "stored": b[:20],
                        "signal_bars": {str(t.entry_time): t.signal_ts + 1 for t in replayed.get(aid, [])[:20]}})
    return out


def stored_trades(conn, start: int, end: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for aid, data in conn.execute("SELECT account_id, data FROM trades WHERE exit_time >= ? AND exit_time < ? "
                                  "ORDER BY id", (start, end)):
        out.setdefault(aid, []).append(json.loads(data))
    return out


# ---------------------------------------------------------------- 1b. early 1m klines
EARLY_KLINE_KO = "early_kline (거래소 1분봉 확정 전 읽음)"
EARLY_SUSPECT_KO = "이른 1분봉 의심 (확인 못 함)"
LIVE_BARS_PARITY_KO = "엔진·재계산 문제 (봇이 쓴 1분봉으로 다시 계산해도 다름)"
EARLY_DOC = "docs/signal-recording.md '1분봉을 확정 전에 읽는 문제'"
EARLY_WINDOW_MS = 1000          # the trade that reached the stop must be this close to the minute's end
FEED_WARN_WINDOW_MS = 3 * MIN   # after the live exit: the feed writes a gap warning when it gives the minute up
FEED_WARNS = ("data gap at", "returned no bars", "no new closed bars", "local clock off", "data error")
FEED_SYMBOLS = tuple(V3_SYMBOLS) + ("XRPUSDT",)
AGG_LIMIT = 1000
AGG_MAX_PAGES = 60
AGG_MAX_MINUTES = 40            # coin-minutes checked on aggTrades per night (a real engine bug can mismatch many)
LIVE_BAR_COLS = ("ts", "symbol", "open", "high", "low", "close", "volume", "mark_open", "mark_high", "mark_low",
                 "mark_close", "close_time", "processed_at")


def load_live_bars(conn, start: int, end: int) -> Optional[dict]:
    """{(ts, symbol): row} of the bars the live runner stepped on in [start, end) (paper3.db ``live_bars``,
    paperbot/fillcost.py); None for a database from before the table."""
    try:
        rows = conn.execute(f"SELECT {', '.join(LIVE_BAR_COLS)} FROM live_bars WHERE ts >= ? AND ts < ?",
                            (start, end)).fetchall()
    except sqlite3.OperationalError:
        return None
    return {(int(r[0]), r[1]): dict(zip(LIVE_BAR_COLS, r)) for r in rows}


def _bar_of(r: dict) -> Bar:
    ts = int(r["ts"])
    return Bar(r["symbol"], ts, int(r["close_time"]) if r.get("close_time") is not None else ts + MIN - 1,
               float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
               mark_open=r.get("mark_open"), mark_high=r.get("mark_high"), mark_low=r.get("mark_low"),
               mark_close=r.get("mark_close"), volume=r.get("volume"))


def steps_on_live_bars(steps, live: dict) -> list:
    """``steps`` with every bar the live runner recorded replaced by that record (funding unchanged)."""
    by_ts: dict[int, dict] = {}
    for (ts, sym), r in live.items():
        by_ts.setdefault(ts, {})[sym] = r
    out = []
    for ts, bars, fund in steps:
        rec = by_ts.get(ts)
        if rec:
            bars = dict(bars)
            for sym, r in rec.items():
                bars[sym] = _bar_of(r)
        out.append((ts, bars, fund))
    return out


def _minute(t: int) -> int:
    return int(t) - int(t) % MIN


def _hm(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%H:%M:%S.") + f"{int(ms) % 1000:03d}"


def _bar_dict(b: Optional[Bar]) -> Optional[dict]:
    if b is None:
        return None
    return {"open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}


def _same(x, y, rel: float = 1e-9) -> bool:
    if x is None or y is None:
        return x is None and y is None
    return abs(float(x) - float(y)) <= rel * max(1.0, abs(float(x)), abs(float(y)))


def first_diff(replayed: list, stored: list[dict]) -> tuple[Optional[object], Optional[dict]]:
    """The first replayed / stored trade pair that compare() sees as different (either may be None)."""
    for k in range(max(len(replayed), len(stored))):
        a = replayed[k] if k < len(replayed) else None
        b = stored[k] if k < len(stored) else None
        if a is None or b is None or _rkey(a) != _skey(b):
            return a, b
    return None, None


def truncated_bar(live: dict, final: Optional[Bar]) -> bool:
    """Live's bar is an early read of the final kline: the same open, a high no higher and a low no lower, and
    something less (a lower high, a higher low or a lower volume)."""
    if final is None:
        return False
    inner = float(live["high"]) <= final.high and float(live["low"]) >= final.low
    vol_less = live.get("volume") is not None and final.volume is not None and float(live["volume"]) < final.volume
    less = float(live["high"]) < final.high or float(live["low"]) > final.low or vol_less
    return float(live["open"]) == final.open and inner and less


def early_shape(a, b: Optional[dict], bar_at, slip: float) -> tuple[list[str], dict]:
    """The trade shape an early kline gives (failed checks, proof): the same position on both sides (entry
    time and price, size, leverage, initial stop), the replay's SL/LOCK at its stop inside minute M, and live
    exiting later on an SL/LOCK either at a later bar's open beyond live's stop (open-gap fill = final open x
    (1 - side x slip)) or at its stop at a later bar's close; live's stop never looser than the replay's."""
    if a is None or b is None:
        return ["replay or live trade missing"], {}
    bad = []
    side = int(a.side)
    if not (a.symbol == b.get("symbol") and side == int(b.get("side", 0)) and a.entry_time == b.get("entry_time")
            and a.leverage == b.get("leverage") and _same(a.entry_price, b.get("entry_price"))
            and _same(a.qty, b.get("qty"))):
        bad.append("entry, size or leverage differ")
    if not _same(a.stop_initial, b.get("stop_initial")):
        bad.append("initial stop differs")
    m = _minute(a.exit_time)
    if a.exit_reason not in ("SL", "LOCK") or a.exit_time != m + MIN - 1 \
            or not _same(a.exit_price, a.stop_price * (1 - side * slip), 1e-10):
        bad.append("replay exit is not an SL/LOCK at its stop inside a minute")
    lt, lstop = int(b.get("exit_time", 0)), b.get("stop_price")
    shape = None
    if b.get("exit_reason") not in ("SL", "LOCK") or lt <= a.exit_time or lstop is None:
        bad.append("live exit is not a later SL/LOCK")
    elif lt % MIN == 0:
        fb = bar_at(lt, a.symbol)
        if fb is not None and _same(b.get("exit_price"), fb.open * (1 - side * slip), 1e-10) \
                and (fb.open - float(lstop)) * side <= 0:
            shape = "open_gap"
        else:
            bad.append("live exit at a bar open is not the final open beyond its stop")
    elif lt % MIN == MIN - 1:
        if _same(b.get("exit_price"), float(lstop) * (1 - side * slip), 1e-10):
            shape = "in_bar"
        else:
            bad.append("live exit at a bar close is not at its stop")
    else:
        bad.append("live exit time is not a bar open or close")
    if lstop is not None and side * (float(lstop) - a.stop_price) < -1e-9 * abs(a.stop_price):
        bad.append("live stop looser than the replay stop")
    proof = {"replay_exit": {"time": a.exit_time, "utc": _hm(a.exit_time), "reason": a.exit_reason,
                             "price": a.exit_price, "stop": a.stop_price},
             "live_exit": {"time": lt, "utc": _hm(lt), "reason": b.get("exit_reason"), "price": b.get("exit_price"),
                           "stop": lstop, "lock_roe": b.get("lock_roe"), "shape": shape},
             "entry": {"time": a.entry_time, "price": a.entry_price, "qty": a.qty, "side": side}}
    return bad, proof


def agg_trades(rest, symbol: str, start: int, end: int, limit: Optional[int] = None,
               max_pages: Optional[int] = None) -> list[tuple[int, float]]:
    """(time ms, price) of every aggregate trade of ``symbol`` with start <= time <= end, oldest first (public
    GET /fapi/v1/aggTrades through the REST client's generic getter: the first page by time, then by id;
    weight 20 a page)."""
    limit, max_pages = limit or AGG_LIMIT, max_pages or AGG_MAX_PAGES
    out: list[tuple[int, float]] = []
    page = rest._get("/fapi/v1/aggTrades", {"symbol": symbol, "startTime": int(start), "endTime": int(end),
                                            "limit": limit})
    for _ in range(max_pages):
        last = None
        for t in page or []:
            ts, last = int(t["T"]), int(t["a"])
            if ts > end:
                return out
            if ts >= start:
                out.append((ts, float(t["p"])))
        if not page or len(page) < limit or last is None:
            return out
        page = rest._get("/fapi/v1/aggTrades", {"symbol": symbol, "fromId": last + 1, "limit": limit})
    raise BinanceError(f"aggTrades {symbol} at {start}: more than {max_pages} pages")


def trade_evidence(trades: list, final: Optional[Bar], side: int, stop: float, minute: int,
                   window_ms: int = EARLY_WINDOW_MS) -> tuple[list[str], dict]:
    """(failed checks, proof): the minute's trades rebuild the final kline, and the first trade at or through
    the replay's stop came in the last ``window_ms`` of the minute (what an early read could miss)."""
    if not trades:
        return ["no trades returned for the minute (cannot verify)"], {"trades": 0}
    ps = [p for _, p in trades]
    rebuilt = {"open": ps[0], "high": max(ps), "low": min(ps), "close": ps[-1]}
    bad = []
    if final is None or not all(_same(rebuilt[k], getattr(final, k), 1e-12) for k in rebuilt):
        bad.append("the trades do not rebuild the final kline (cannot verify)")
    close = minute + MIN
    cross = next(((t, p) for t, p in trades if (p <= stop if side > 0 else p >= stop)), None)
    if cross is None:
        bad.append("no trade reached the replay stop")
    elif cross[0] < close - window_ms:
        bad.append(f"the first trade at the stop came {close - cross[0]} ms before the close "
                   f"(not in the last {window_ms} ms)")
    proof = {"trades": len(trades), "rebuilt": rebuilt, "final": _bar_dict(final), "window_ms": window_ms,
             "in_window": sum(1 for t, _ in trades if t >= close - window_ms),
             "first_at_stop": None if cross is None else {"time": cross[0], "utc": _hm(cross[0]), "price": cross[1],
                                                          "ms_before_close": close - cross[0]}}
    return bad, proof


def feed_warnings(conn, symbol: str, lo: int, hi: int) -> Optional[list[dict]]:
    """Feed warnings (data gap, no bars, stale feed, clock, data error) in paper3.db alerts between lo and hi
    that concern ``symbol`` (or name no symbol); None when the table cannot be read."""
    try:
        rows = conn.execute("SELECT ts, level, text FROM alerts WHERE ts >= ? AND ts <= ? "
                            "AND level IN ('WARN', 'CRITICAL') ORDER BY ts", (lo, hi)).fetchall()
    except sqlite3.OperationalError:
        return None
    out = []
    for ts, level, text in rows:
        text = text or ""
        if any(f in text for f in FEED_WARNS) and (symbol in text or not any(s in text for s in FEED_SYMBOLS)):
            out.append({"ts": int(ts), "level": level, "text": text[:200]})
    return out


def explain_mismatches(conn, rest, settings: Settings, brackets, specs, snapshot: dict, signals: dict, steps,
                       replayed: dict, stored: dict, mism: list[dict], start: int, end: int,
                       extras: Optional[dict] = None, window_ms: int = EARLY_WINDOW_MS,
                       engine_cls: Optional[dict] = None) -> dict:
    """Label the mismatches an early 1m kline explains (``early_kline`` True, ``label``, ``proof``) and say why
    the others are not (``early_kline_check``). ``replayed``: the day's replay (trades exiting before ``end``),
    ``stored``: the live trades, ``steps``: the day's final steps. Returns the report's summary (live bars seen,
    the replay on live's bars, the early-kline events). Restart gaps of extras are left alone."""
    final = {(ts, sym): b for ts, bars, _ in steps for sym, b in bars.items()}

    def bar_at(ts, sym):
        return final.get((ts, sym))

    slip = settings.slippage_frac
    live = load_live_bars(conn, start, end)
    info: dict = {"live_bars": None if live is None else len(live)}
    live_mism: set = set()
    if live:
        rep_live = replay(settings, brackets, specs, snapshot, signals, steps_on_live_bars(steps, live),
                          extras=extras, engine_cls=engine_cls)
        cmp_live = compare({a: [t for t in ts if t.exit_time < end] for a, ts in rep_live.items()}, stored)
        live_mism = {m["account_id"] for m in cmp_live}
        only = sorted(live_mism - {m["account_id"] for m in mism})
        info["live_bars_replay"] = {"mismatched": len(live_mism), "only_on_live_bars": only[:50]}
    groups: dict[tuple, list] = {}
    for m in mism:
        if m.get("crash_gap"):
            continue
        aid = m["account_id"]
        a, b = first_diff(replayed.get(aid, []), stored.get(aid, []))
        if a is None or a.exit_reason not in ("SL", "LOCK"):
            m["early_kline_check"] = {"failed": ["the first difference is not a replay stop exit"]}
            continue
        sym, mm = a.symbol, _minute(a.exit_time)
        m["trigger"] = {"symbol": sym, "minute": mm, "utc": _hm(mm)}
        if live and (mm, sym) in live:                       # (i) the bars live stepped on
            # the position's minutes up to the trigger: every live bar that differs from the final kline must be
            # an early read of it, and there must be one (the trigger minute's, else an earlier one that kept a
            # lock lower)
            diff_t, trunc_t = [], []
            for t in range(max(start, _minute(a.entry_time)), mm + MIN, MIN):
                lb, fb = live.get((t, sym)), bar_at(t, sym)
                if lb is None or fb is None:
                    continue
                if any(lb.get(k) is None or float(lb[k]) != getattr(fb, k) for k in ("open", "high", "low", "close")) \
                        or (lb.get("volume") is not None and fb.volume is not None
                            and float(lb["volume"]) != fb.volume):
                    diff_t.append(t)
                    if truncated_bar(lb, fb):
                        trunc_t.append(t)
            at = mm if mm in trunc_t else (trunc_t[-1] if trunc_t else mm)
            lb, fb = live[(at, sym)], bar_at(at, sym)
            proof = {"source": "live_bars", "symbol": sym, "minute": at, "utc": _hm(at), "trigger_minute": mm,
                     "live_bar": lb, "final_bar": _bar_dict(fb), "early_minutes": [_hm(t) for t in trunc_t],
                     "processed_ms_after_close": None if lb.get("processed_at") is None
                     else int(lb["processed_at"]) - (at + MIN)}
            if aid in live_mism:
                m.update(label=LIVE_BARS_PARITY_KO, live_bars_replay="mismatch",
                         early_kline_check={"failed": ["still differs when replayed on live's own bars"], **proof})
            elif trunc_t and len(trunc_t) == len(diff_t):
                m.update(label=EARLY_KLINE_KO, early_kline=True, proof=proof)
            else:
                m["early_kline_check"] = {"failed": ["live's bars before the exit are not early reads of the final "
                                                     "klines"], "other_minutes": [_hm(t) for t in diff_t
                                                                                  if t not in trunc_t], **proof}
            continue
        groups.setdefault((sym, mm), []).append((m, a, b))
    for k, ((sym, mm), items) in enumerate(sorted(groups.items(), key=lambda kv: kv[0][1])):   # (ii) trades
        try:
            if k >= AGG_MAX_MINUTES:
                raise RuntimeError(f"more than {AGG_MAX_MINUTES} coin-minutes to check")
            trades, err = agg_trades(rest, sym, mm, mm + MIN - 1), None
        except Exception as exc:  # noqa: BLE001  (no proof: the mismatch stays unexplained)
            trades, err = None, f"{type(exc).__name__}: {exc}"[:200]
        results = []
        for m, a, b in items:
            bad, proof = early_shape(a, b, bar_at, slip)
            shape_ok = not bad
            if trades is None:
                bad.append(f"aggTrades not read: {err}")
            else:
                tb, proof["trades"] = trade_evidence(trades, bar_at(mm, sym), int(a.side), a.stop_price, mm,
                                                     window_ms)
                bad += tb
            hi = int(b["exit_time"]) + FEED_WARN_WINDOW_MS if b else mm + MIN + FEED_WARN_WINDOW_MS
            warns = feed_warnings(conn, sym, mm, hi)
            if warns is None:
                bad.append("paper3.db alerts not readable")
            elif warns:
                bad.append(f"feed warning between the minute and the live exit: {warns[0]['text'][:120]}")
                proof["feed_warnings"] = warns[:5]
            proof.update(source="aggTrades", symbol=sym, minute=mm, utc=_hm(mm),
                         accounts=[x[0]["account_id"] for x in items])
            results.append((m, bad, proof, shape_ok))
        every = all(not bad for _, bad, _, _ in results)
        for m, bad, proof, shape_ok in results:
            if every:
                m.update(label=EARLY_KLINE_KO, early_kline=True, proof=proof)
                continue
            m["early_kline_check"] = {"failed": bad or ["another account of the same coin-minute was not explained"],
                                      **proof}
            if shape_ok:
                m["label"] = EARLY_SUSPECT_KO
    events: dict[tuple, list] = {}
    for m in mism:
        if m.get("early_kline"):
            p = m["proof"]
            events.setdefault((p["symbol"], p["minute"], p["source"]), []).append(m["account_id"])
    info["early_kline"] = sum(len(v) for v in events.values())
    info["early_kline_events"] = [{"symbol": s, "minute": t, "utc": _hm(t), "source": src, "accounts": v}
                                  for (s, t, src), v in sorted(events.items(), key=lambda kv: kv[0][1])]
    return info


# ---------------------------------------------------------------- 2. shadows
def _alone(settings: Settings, brackets, specs, sig: Signal, steps, i0: int,
           cls=PaperEngine) -> tuple[Optional[object], bool]:
    """Run one signal on a fresh account (settings.initial_equity) from step index i0. Returns (trade or None, resolved).
    ``cls``: the account's engine class (``engine_classes``; the reel's exits for the reel and the 5m coin flips)."""
    e = cls(settings, brackets, symbol_specs=specs, book="shadow")
    e.submit(sig)
    for ts, bars, funding in steps[i0:]:
        e.step({s: b for s, b in bars.items() if s in brackets}, funding)
        if e.trades:
            return e.trades[0], True
        if e.position is None and not e.pending:
            return None, True          # rejected by sizing
    return None, False


def limit_fill(sig_row: dict, steps, i0: int) -> Optional[tuple[int, float]]:
    """(step index, limit price) if a limit LIMIT_ATR x ATR better than the reference traded
    through within one bar of the signal's timeframe after it was ready."""
    side, ref, atr = int(sig_row["side"]), sig_row["ref_price"], sig_row["atr"]
    if ref is None or atr is None:
        return None
    limit = ref - side * LIMIT_ATR * atr
    until = sig_row["bar_close"] + TF_MS[sig_row["timeframe"]]
    for k in range(i0, len(steps)):
        ts, bars, _ = steps[k]
        if ts >= until:
            break
        b = bars.get(sig_row["symbol"])
        if b is None:
            continue
        if (b.low < limit) if side > 0 else (b.high > limit):
            return k, limit
    return None


def shadows(settings: Settings, brackets, specs, conn, day: str, start: int, end: int, steps) -> list[dict]:
    """Limit, skipped and stop what-if rows. An account with its own engine (``engine_classes``: paper v4's reel and
    5m coin flips) runs its limit and skipped shadows on that engine (the reel's exits), gets no skipped shadow for a
    signal its own entry rules skipped (reason "reel: ...": no trade under its rules) and no stop what-ifs (those vary
    the house 2 ATR stop, which it does not use)."""
    idx = {ts: k for k, (ts, _, _) in enumerate(steps)}
    rows = []
    ext = extras_of(conn)
    ecls = engine_classes(conn)
    sigs = day_signals(conn, start - 1, end - 1, with_data=True)     # data: the leverage group's strength
    for bc, lst in sigs.items():
        i0 = idx.get(bc)
        if i0 is None:
            continue
        for d in lst:
            aid = f"{d['strategy']}@{d['timeframe']}"
            key = f"limit|{aid}|{d['symbol']}|{bc}"
            fill = limit_fill(d, steps, i0)
            roe = reason = None
            resolved = True
            if fill is not None:
                k, px = fill
                t, resolved = _alone(settings, brackets, specs,
                                     replace(make_signal(d, ref=px), ts=steps[k][0] - 1), steps, k,
                                     cls=ecls.get(aid, PaperEngine))
                if t is not None:
                    # a resting limit pays the maker fee and no entry slippage
                    roe = t.roe + t.leverage * (settings.taker_fee - settings.maker_fee + settings.slippage_frac)
                    reason = t.exit_reason
            rows.append({"key": key, "day": day, "kind": "limit", "account_id": aid, "symbol": d["symbol"],
                         "timeframe": d["timeframe"], "side": d["side"], "filled": int(fill is not None),
                         "roe": roe, "exit_reason": reason, "resolved": int(resolved), "data": "{}"})
    q = ("SELECT account_id, reason, data FROM outcomes WHERE status = 'SKIPPED' AND step_ts >= ? AND step_ts < ?")
    for aid, why, data in conn.execute(q, (start, end)):
        if aid in ecls and str(why or "").startswith("reel:"):
            continue                    # the reel's own skip rule: no trade under its rules, nothing missed
        s = json.loads(data)["signal"]
        bc = s["ts"] + 1
        i0 = idx.get(bc)
        if i0 is None:
            continue
        sig = Signal(**{k: v for k, v in s.items()})
        # an extra account's own settings (a lock_start copy's first lock); its signal already carries its stop
        x = ext.get(aid)
        if x is not None and x.get("rule"):
            from .extras import settings_for
            acc_settings = settings_for(settings, x["rule"])
        else:
            acc_settings = settings
        t, resolved = _alone(acc_settings, brackets, specs, sig, steps, i0, cls=ecls.get(aid, PaperEngine))
        rows.append({"key": f"skipped|{aid}|{s['symbol']}|{bc}", "day": day, "kind": "skipped",
                     "account_id": aid, "symbol": s["symbol"], "timeframe": s["timeframe"], "side": s["side"],
                     "filled": None, "roe": None if t is None else t.roe,
                     "exit_reason": None if t is None else t.exit_reason, "resolved": int(resolved), "data": "{}"})
    rows += stop_shadows(settings, brackets, specs, conn, day, start, end, steps, sigs, idx, ext, own=set(ecls))
    return rows


def stop_shadows(settings: Settings, brackets, specs, conn, day: str, start: int, end: int, steps,
                 sigs: dict, idx: dict, ext: Optional[dict] = None, own: Optional[set] = None) -> list[dict]:
    """For every losing trade (stop or liquidation) whose signal bar closed in the day: the
    same signal alone with a 1.5 / 2.5 / 3 ATR stop (leverage re-chosen by the same rules).
    Feeds the loss cards (cards.py). A copy account's cards read these rows under its parent's id (the copy
    repeats the parent's signal), so a parent signal is also computed when only a copy of it lost (the parent
    won or was not in it): such a row has ``actual_roe`` None and ``copies`` (left out of the day's summary,
    which is about the original accounts' losses). ``own``: accounts with their own exits (paper v4's reel and 5m
    coin flips): no house-stop what-ifs."""
    rows = []
    own = own or set()
    q = ("SELECT account_id, data FROM trades WHERE exit_reason IN ('SL', 'LIQ') "
         "AND entry_time >= ? AND entry_time < ?")
    parent_of = {aid: x["parent"] for aid, x in (ext or {}).items() if x.get("kind") == "copy" and x.get("parent")}
    lost, copy_lost = {}, {}
    for aid, data in conn.execute(q, (start, end + DAY_MS)):
        if aid in own:
            continue
        t = json.loads(data)
        lost[(aid, t["symbol"], t["signal_ts"] + 1)] = t
        if aid in parent_of:
            copy_lost.setdefault((parent_of[aid], t["symbol"], t["signal_ts"] + 1), []).append(aid)
    for bc, lst in sigs.items():
        i0 = idx.get(bc)
        if i0 is None:
            continue
        for d in lst:
            aid = f"{d['strategy']}@{d['timeframe']}"
            own, copies = lost.get((aid, d["symbol"], bc)), copy_lost.get((aid, d["symbol"], bc))
            if own is None and not copies:
                continue
            for k in STOP_VARIANTS:
                t, resolved = _alone(settings, brackets, specs, make_signal(d, stop_atr=k), steps, i0)
                extra = {"copies": sorted(copies)} if copies else {}
                rows.append({"key": f"stop{k}|{aid}|{d['symbol']}|{bc}", "day": day, "kind": f"stop{k}",
                             "account_id": aid, "symbol": d["symbol"], "timeframe": d["timeframe"],
                             "side": d["side"], "filled": None, "roe": None if t is None else t.roe,
                             "exit_reason": None if t is None else t.exit_reason, "resolved": int(resolved),
                             "data": json.dumps({"leverage": None if t is None else t.leverage,
                                                 "actual_roe": None if own is None else own["roe"], **extra})})
    return rows


# ---------------------------------------------------------------- 3. data quality
def data_quality(steps, symbols, start: int, end: int) -> dict:
    out = {}
    expected = (end - start) // MIN
    for s in symbols:
        bs = [bars[s] for _, bars, _ in steps if s in bars and start <= bars[s].open_time < end]
        rng = np.array([(b.high - b.low) / b.close for b in bs]) if bs else np.zeros(0)
        med = float(np.median(rng)) if len(rng) else 0.0
        gap = [abs(b.close - b.mark_close) / b.mark_close for b in bs if b.mark_close]
        out[s] = {
            "minutes": len(bs), "missing": expected - len(bs),
            "zero_volume": sum(1 for b in bs if b.volume == 0),
            "extreme_ranges": int((rng > 15 * med).sum()) if med > 0 else 0,
            "max_range_pct": float(rng.max() * 100) if len(rng) else None,
            "max_last_mark_gap_pct": float(max(gap) * 100) if gap else None,
            "no_mark_minutes": sum(1 for b in bs if b.mark_close is None),
        }
    fund = [abs(r) for _, _, f in steps for r in f.values()]
    out["max_abs_funding_pct"] = float(max(fund) * 100) if fund else None
    return out


# ---------------------------------------------------------------- run
def fill_cost_report(conn, start: int, end: int) -> Optional[dict]:
    """The day's order-book cost records (paperbot/fillcost.py); None for a database without them."""
    from .fillcost import summary
    try:
        rows = [json.loads(r[0]) for r in conn.execute(
            "SELECT data FROM fill_costs WHERE ts >= ? AND ts < ?", (start, end))]
    except sqlite3.OperationalError:
        return None
    rep = summary(rows)
    rep["recorded"] = len(rows)
    rep["without_book"] = sum(1 for r in rows if r.get("status") != "ok")
    return rep


# ---------------------------------------------------------------- 4. realistic stop slippage, 5. larger sizes
STOP_MAX_MINUTES = 150          # coin-minutes read on aggTrades per night (the most exit notional first)
STOP_MAX_PAGES = 8              # pages of 1,000 trades per coin-minute (a busy BTC minute is 1-4)
STOP_MAX_TOTAL_PAGES = 600      # pages per night: 12,000 weight, paced below 1,600 weight a minute
STOP_PAGE_PAUSE_S = 0.75
STOP_MAX_FAILS = 5              # consecutive failed coin-minutes before the rest is left unread (API down)
STOP_DEPTH_NEAR_MS = 2 * MIN    # a fill_costs read of the exit counts when its step is this close to the minute


def _accounts_meta(conn) -> dict:
    try:
        return {a: (s, tf) for a, s, tf in conn.execute("SELECT account_id, strategy, timeframe FROM accounts")}
    except sqlite3.OperationalError:
        return {}


def agg_rows(rest, symbol: str, start: int, end: int, limit: int, max_pages: int, enough=None, budget=None,
             sleep=time.sleep, pause: float = STOP_PAGE_PAUSE_S) -> list[tuple[int, float, float, bool]]:
    """(ms, price, qty, buyer_is_maker) of the aggregate trades with start <= time <= end (like ``agg_trades``),
    stopping early once ``enough(rows)`` is true. ``budget`` ({"pages": n}) is shared by the night's calls; a page
    past it or past ``max_pages`` raises."""
    out: list = []

    def take(page) -> tuple[bool, Optional[int]]:
        last = None
        for t in page or []:
            ts, last = int(t["T"]), int(t["a"])
            if ts > end:
                return True, last
            if ts >= start:
                out.append((ts, float(t["p"]), float(t.get("q") or 0.0), bool(t.get("m", False))))
        return (not page or len(page) < limit or last is None), last

    params: dict = {"symbol": symbol, "startTime": int(start), "endTime": int(end), "limit": limit}
    for k in range(max_pages):
        if budget is not None:
            if budget["pages"] <= 0:
                raise RuntimeError("night's aggTrades page budget used up")
            budget["pages"] -= 1
        if k:
            sleep(pause)
        done, last = take(rest._get("/fapi/v1/aggTrades", params))
        if done or (enough is not None and enough(out)):
            return out
        params = {"symbol": symbol, "fromId": last + 1, "limit": limit}
    raise BinanceError(f"aggTrades {symbol} at {start}: more than {max_pages} pages")


def _enough_for(stops: list[tuple[int, float]], start: int, window_ms: int):
    """True once every (side, stop) has its trigger and the trades reach ``window_ms`` past it."""
    def check(rows) -> bool:
        if not rows:
            return False
        last = rows[-1][0]
        for side, stop in stops:
            trig = next((t for t, p, _q, _m in rows if t >= start and (p <= stop if side > 0 else p >= stop)), None)
            if trig is None or last <= trig + window_ms:
                return False
        return True
    return check


# Which coin-minutes the stop-slippage caps read first (G28): the groups the owners read trade by trade (core, reel)
# before the extras, then DeepSeek and the coin flips; an unknown group (a database without accounts) as core.
STOP_GROUP_RANK = {"core": 0, "reel": 0, "other": 0, "extra": 1, "ds200": 2, "flip": 2}


def stop_slippage(conn, rest, settings: Settings, day: str, start: int, end: int, sleep=time.sleep,
                  window_ms: Optional[int] = None) -> tuple[list[dict], dict]:
    """(one row per SL / LOCK / LIQ exit in [start, end), summary). Never raises for a failed request: the
    exits of that coin-minute get ``status = 'api_error'``; past a cap ``'cap'``. Paper v4: the coin-minutes holding
    a core or reel exit are read first (``STOP_GROUP_RANK``, then the most exit notional first), and the summary
    adds ``groups`` ({group: slipcost.stop_cell}) for the 09:20 split."""
    from . import slipcost as SC
    window_ms = SC.WINDOW_MS if window_ms is None else window_ms
    meta = _accounts_meta(conn)
    grp = account_groups(conn)
    q = ("SELECT account_id, data FROM trades WHERE exit_time >= ? AND exit_time < ? AND exit_reason IN "
         f"({', '.join('?' * len(SC.STOP_REASONS))}) ORDER BY id")
    exits = []
    for aid, data in conn.execute(q, (start, end, *SC.STOP_REASONS)):
        t = json.loads(data)
        s, tf = meta.get(aid, (t.get("strategy_id"), t.get("timeframe")))
        t.update(account_id=aid, strategy_id=t.get("strategy_id") or s, timeframe=t.get("timeframe") or tf)
        exits.append(t)
    depth: dict = {}
    try:
        for ts, aid, sym, sb in conn.execute(
                "SELECT ts, account_id, symbol, slip_best FROM fill_costs WHERE event = 'exit' AND status = 'ok' "
                "AND slip_best IS NOT NULL AND ts >= ? AND ts < ?", (start - 3 * MIN, end + 3 * MIN)):
            depth.setdefault((aid, sym), []).append((int(ts), float(sb)))
    except sqlite3.OperationalError:
        pass
    groups: dict = {}
    for t in exits:
        groups.setdefault((t["symbol"], _minute(int(t["exit_time"]))), []).append(t)
    order = sorted(groups.items(), key=lambda kv: (min(STOP_GROUP_RANK.get(grp.get(t["account_id"], "other"), 2)
                                                       for t in kv[1]),
                                                   -sum(float(t["qty"]) * float(t["exit_price"]) for t in kv[1]),
                                                   kv[0][1], kv[0][0]))
    budget = {"pages": STOP_MAX_TOTAL_PAGES}
    rows, fails, pages0, read = [], 0, budget["pages"], 0
    for k, ((sym, mm), ts_) in enumerate(order):
        trades, err, status = None, None, None
        if k >= STOP_MAX_MINUTES:
            status, err = "cap", f"more than {STOP_MAX_MINUTES} coin-minutes this night"
        elif fails >= STOP_MAX_FAILS:
            status, err = "api_error", f"not read: {STOP_MAX_FAILS} coin-minutes failed in a row"
        elif budget["pages"] <= 0:
            status, err = "cap", f"more than {STOP_MAX_TOTAL_PAGES} aggTrades pages this night"
        else:
            if read:
                sleep(STOP_PAGE_PAUSE_S)
            read += 1
            try:
                trades = agg_rows(rest, sym, mm, mm + MIN - 1 + window_ms, AGG_LIMIT, STOP_MAX_PAGES,
                                  enough=_enough_for([(int(t["side"]), float(t["stop_price"])) for t in ts_], mm,
                                                     window_ms), budget=budget, sleep=sleep)
                fails = 0
            except Exception as exc:  # noqa: BLE001  (descriptive: the exit is recorded as not measured)
                status, err = "api_error", f"{type(exc).__name__}: {exc}"[:200]
                fails += 1
                if "budget" in str(exc):
                    status = "cap"
        for t in ts_:
            if trades is None:
                fill = {"status": status, "error": err}
            else:
                near = [(abs(ts - mm), sb) for ts, sb in depth.get((t["account_id"], sym), [])
                        if abs(ts - mm) <= STOP_DEPTH_NEAR_MS]
                fill = SC.stop_fill(trades, int(t["side"]), float(t["stop_price"]), float(t["qty"]), mm, window_ms,
                                    depth_slip=min(near)[1] if near else None)
            r = SC.stop_row(t, fill, settings.slippage_frac)
            r["key"] = f"{t['account_id']}|{sym}|{t['entry_time']}|{t['exit_time']}"
            r["day"] = day
            rows.append(r)
    summary = SC.summarize_stops(rows, settings.slippage_frac)
    summary["api"] = {"coin_minutes": len(order), "read": read, "pages": pages0 - budget["pages"],
                      "window_ms": window_ms}
    by: dict = {g: [] for g in set(grp.values()) if g != "extra"}
    for r in rows:
        by.setdefault(grp.get(r["account_id"], "other"), []).append(r)
    summary["groups"] = _group_dict({g: SC.stop_cell(v) for g, v in by.items()})
    return rows, summary


def size_cost_report(conn, start: int, end: int) -> Optional[dict]:
    """Cost at 2x / 5x / 10x the paper size from the day's fill_costs book reads; None without the table."""
    from .slipcost import summarize_size_costs
    try:
        rows = [json.loads(r[0]) for r in conn.execute(
            "SELECT data FROM fill_costs WHERE ts >= ? AND ts < ? AND status = 'ok'", (start, end))]
    except sqlite3.OperationalError:
        return None
    tf_of = {a: tf for a, (_s, tf) in _accounts_meta(conn).items()}
    return summarize_size_costs(rows, tf_of)


def write_stop_slips(out: sqlite3.Connection, day: str, rows: list[dict]) -> None:
    out.execute("DELETE FROM stop_slips WHERE day = ?", (day,))
    out.executemany("INSERT OR REPLACE INTO stop_slips VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(r["key"], day, r["account_id"], r.get("strategy"), r.get("timeframe"), r["symbol"],
                      r["exit_reason"], r["exit_time"], r["status"], r.get("paper_bps"), r.get("real_bps"),
                      r.get("diff_usd"), json.dumps(r, default=str)) for r in rows])


def run_day(conn, out: sqlite3.Connection, rest: BinanceREST, settings: Settings, brackets, specs,
            day: str, horizon_days: int = 3, early_window_ms: int = EARLY_WINDOW_MS, stop_slip: bool = False,
            sleep=time.sleep, dscheck_dir: Optional[str] = None) -> dict:
    """One night. ``stop_slip`` (the nightly command's default): also the realistic stop slippage (4), which
    reads aggTrades; ``sleep`` paces those pages. ``dscheck_dir`` (the nightly command: ``DSCHECK_DIR``): a run
    with DeepSeek accounts adds the DeepSeek recomputation's last line (``report["dscheck"]``, None when none)."""
    start = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    end = start + DAY_MS
    now = rest.server_time()
    last = min(now - now % MIN, end + horizon_days * DAY_MS)
    symbols = list(brackets)
    steps = fetch_steps(rest, symbols, start, last)
    day_steps = [s for s in steps if s[0] < end]
    report = {"day": day, "steps": len(day_steps)}
    try:   # strategy signals of cells with quality edges whose strength score failed (sized 'normal'; review M2)
        from .strengthwatch import day_counts
        report["strength"] = day_counts(conn, start, end)
    except Exception as exc:  # noqa: BLE001  a count only
        report["strength"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    acc = account_rows(conn)
    groups = account_groups(conn, acc)
    snap = conn.execute("SELECT data FROM state WHERE k = ?", (day_key(start),)).fetchone()
    if snap is None:
        first = run_start_ts(conn)
        if first is not None and first > start:
            # the run started after this day's 00:00 UTC: no snapshot by design (G25), not a stopped runner
            hhmm = dt.datetime.fromtimestamp(first / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
            report["parity"] = (f"start day: the run started at {hhmm} UTC, after this day's 00:00 snapshot "
                                "(nothing to replay)" if first < end else
                                f"before the run: it started at {hhmm} UTC (nothing to replay)")
            report["start_day"] = {"run_start": first, "before_run": first >= end}
        else:
            report["parity"] = "no 00:00 snapshot for this day (runner not running then)"
        mism = []
    else:
        ext = extras_of(conn)
        ecls = engine_classes(conn, acc)                          # the reel and the 5m coin flips: ReelEngine
        snap_d = json.loads(snap[0])
        sigs = day_signals(conn, start, end, with_data=True)    # data: skip tags, the leverage group's strength,
        #                                                         the reel's entry levels
        rep = replay(settings, brackets, specs, snap_d, sigs, day_steps, extras=ext, engine_cls=ecls)
        rep_day = {a: [t for t in ts if t.exit_time < end] for a, ts in rep.items()}
        stored = stored_trades(conn, start, end)
        mism = compare(rep_day, stored)
        if ext:
            label_crash_gaps(mism, ext, conn)
        gaps = sum(1 for m in mism if m.get("crash_gap"))
        early = explain_mismatches(conn, rest, settings, brackets, specs, snap_d, sigs, day_steps, rep_day, stored,
                                   mism, start, end, extras=ext, window_ms=early_window_ms, engine_cls=ecls)
        n_early = early["early_kline"]
        report["parity"] = {"accounts": len(rep), "mismatched_accounts": len(mism) - gaps - n_early}
        if n_early:
            report["parity"].update(early_kline=n_early, early_kline_events=early["early_kline_events"])
        if early.get("live_bars") is not None:
            report["parity"]["live_bars"] = {"bars": early["live_bars"], **(early.get("live_bars_replay") or {})}
        if ext:
            report["parity"].update(extra_accounts=sum(1 for a in rep if a in ext), crash_gaps=gaps)
        report["parity"]["groups"] = parity_groups(rep, mism, groups)
    report["trades"] = trade_counts(conn, start, end, groups)
    sh = shadows(settings, brackets, specs, conn, day, start, end, steps)
    # trades that closed today but were entered earlier need the steps from their signal on
    first = first_signal(conn, start, end)
    pre = fetch_steps(rest, symbols, max(first, start - LOOKBACK_MS), start) if first is not None else []
    # the pre-registered what-ifs (trade_variants, stop_variants) summarize the run's own population as in v3 (the
    # 36, the coin flips, new-lab accounts); the DeepSeek accounts' shadows are summarized apart, in *_groups (jobs
    # review 4): one trade_shadows pass per population, so every trade is still shadowed exactly once
    def is_ds(aid):
        return groups.get(aid) == "ds200"
    tv, tv_info = trade_shadows(settings, brackets, specs, TradesOf(conn, lambda a: not is_ds(a)), day, start, end,
                                pre + steps, make_signal, quality=True, extra3=True, extra4=True)
    has_ds = "ds200" in groups.values()
    tv_ds, tv_ds_info = (trade_shadows(settings, brackets, specs, TradesOf(conn, is_ds), day, start, end, pre + steps,
                                       make_signal, quality=True, extra3=True, extra4=True) if has_ds else ([], {}))
    lim = [r for r in sh if r["kind"] == "limit"]
    report["shadows"] = {
        "limit_signals": len(lim), "limit_filled": sum(r["filled"] for r in lim),
        "limit_mean_roe": float(np.mean([r["roe"] for r in lim if r["roe"] is not None]))
        if any(r["roe"] is not None for r in lim) else None,
        "skipped": sum(1 for r in sh if r["kind"] == "skipped"),
        "stop_variants": stop_variants([r for r in sh if not is_ds(r["account_id"])]),
    }
    report["shadows"]["groups"] = shadow_groups(sh, groups)
    report["shadows"]["trade_variants"] = summarize(tv, tv_info)
    if has_ds:
        report["shadows"]["stop_variants_groups"] = {"ds200": stop_variants([r for r in sh if is_ds(r["account_id"])])}
        report["shadows"]["trade_variants_groups"] = {"ds200": summarize(tv_ds, tv_ds_info)}
    tv = tv + tv_ds
    sh += tv
    report["data_quality"] = data_quality(day_steps, symbols, start, end)
    report["fill_costs"] = fill_cost_report(conn, start, end)
    try:
        report["size_costs"] = size_cost_report(conn, start, end)
    except Exception as exc:  # noqa: BLE001  (descriptive: never stops the night)
        report["size_costs"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    slips = None
    if stop_slip:
        try:
            slips, report["stop_slippage"] = stop_slippage(conn, rest, settings, day, start, end, sleep=sleep)
        except Exception as exc:  # noqa: BLE001  (descriptive: never stops the night)
            report["stop_slippage"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    if slips is not None:
        write_stop_slips(out, day, slips)
    if dscheck_dir and "ds200" in groups.values():
        report["dscheck"] = dscheck_line(dscheck_dir)
    out.execute("DELETE FROM mismatches WHERE day = ?", (day,))
    out.executemany("INSERT INTO mismatches VALUES (?,?,?)", [(day, m["account_id"], json.dumps(m)) for m in mism])
    out.executemany("INSERT OR REPLACE INTO shadows VALUES (:key,:day,:kind,:account_id,:symbol,:timeframe,:side,"
                    ":filled,:roe,:exit_reason,:resolved,:data)", sh)
    report["shadows"]["curves"] = write_curves(out, day, tv, start=settings.initial_equity)   # observation-shadows-4
    out.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (day, int(time.time() * 1000), json.dumps(report)))
    out.commit()
    return report


GROUP_ORDER = ("core", "ds200", "reel", "flip", "extra", "other")


def _group_dict(d: dict) -> dict:
    """``d`` in the report's group order (core, ds200, reel, flip, extra, then any other)."""
    def key(g):
        return GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER), g
    return {g: d[g] for g in sorted(d, key=key)}


def parity_groups(replayed: dict, mism: list[dict], groups: dict) -> dict:
    """The parity split by account group (paper v4: core, ds200, reel, flip, extra; ``account_groups``):
    {group: {"accounts", "ok", "mismatched", "early_kline", "crash_gaps"}}. "accounts" counts the replayed accounts as
    ``parity.accounts`` does; a mismatch is counted once, as a restart gap, an early 1m kline or a real mismatch (the
    sum of "mismatched" is ``parity.mismatched_accounts``)."""
    out: dict = {}

    def slot(aid):
        return out.setdefault(groups.get(aid, "other"),
                              {"accounts": 0, "ok": 0, "mismatched": 0, "early_kline": 0, "crash_gaps": 0})
    for aid in replayed:
        slot(aid)["accounts"] += 1
    for m in mism:
        x = slot(m["account_id"])
        x["crash_gaps" if m.get("crash_gap") else "early_kline" if m.get("early_kline") else "mismatched"] += 1
    for x in out.values():
        x["ok"] = x["accounts"] - x["mismatched"] - x["early_kline"] - x["crash_gaps"]
    return _group_dict(out)


class TradesOf:
    """``conn`` whose closed trades (obsshadows.closed_trades' query) are only those of the accounts ``keep`` accepts;
    every other query passes through. trade_shadows then runs once per population (jobs review 4)."""

    QUERY = "SELECT account_id, data FROM trades WHERE exit_time >= ? AND exit_time < ? ORDER BY id"

    def __init__(self, conn, keep):
        self._conn, self._keep = conn, keep

    def execute(self, sql, *args):
        cur = self._conn.execute(sql, *args)
        if " ".join(sql.split()) == self.QUERY:
            return [r for r in cur if self._keep(r[0])]
        return cur

    def __getattr__(self, name):
        return getattr(self._conn, name)


def stop_variants(sh: list[dict]) -> dict:
    """report["shadows"]["stop_variants"]: per stop width, the losing trades' shadow ROE (the original accounts'
    losses: rows whose actual ROE is known)."""
    out = {}
    for k in STOP_VARIANTS:
        v = [r for r in sh if r["kind"] == f"stop{k}" and r["roe"] is not None and r["resolved"]
             and json.loads(r["data"]).get("actual_roe") is not None]
        out[str(k)] = {
            "losing_trades": len(v),
            "mean_roe": float(np.mean([r["roe"] for r in v])) if v else None,
            "turned_positive": sum(1 for r in v if r["roe"] > 0),
            "better_than_actual": sum(1 for r in v if r["roe"] > json.loads(r["data"])["actual_roe"]),
        }
    return out


def shadow_groups(sh: list[dict], groups: dict) -> dict:
    """The limit and skipped shadows by account group (G28): {group: {"limit_signals", "limit_filled",
    "limit_mean_roe", "skipped"}}; every group of the run's original accounts is listed (0 when it had none)."""
    per: dict = {g: [] for g in set(groups.values()) if g != "extra"}
    for r in sh:
        if r["kind"] in ("limit", "skipped"):
            per.setdefault(groups.get(r["account_id"], "other"), []).append(r)
    out = {}
    for g, rs in per.items():
        lim = [r for r in rs if r["kind"] == "limit"]
        roes = [r["roe"] for r in lim if r["roe"] is not None]
        out[g] = {"limit_signals": len(lim), "limit_filled": sum(int(r["filled"] or 0) for r in lim),
                  "limit_mean_roe": float(np.mean(roes)) if roes else None,
                  "skipped": sum(1 for r in rs if r["kind"] == "skipped")}
    return _group_dict(out)


def trade_counts(conn, start: int, end: int, groups: dict) -> dict:
    """{"total": n, "groups": {group: n}} of the trades that closed in [start, end) (paper3.db trades); every group
    of the run's original accounts is listed, with 0 when it had none (an empty reel day shows)."""
    per = {g: 0 for g in set(groups.values()) if g != "extra"}
    total = 0
    for aid, n in conn.execute("SELECT account_id, COUNT(*) FROM trades WHERE exit_time >= ? AND exit_time < ? "
                               "GROUP BY account_id", (start, end)):
        g = groups.get(aid, "other")
        per[g] = per.get(g, 0) + int(n)
        total += int(n)
    return {"total": total, "groups": _group_dict(per)}


def _split_text(parts: list[tuple[str, str]]) -> str:
    from .groups import GROUP_KO
    return " (" + " · ".join(f"{GROUP_KO.get(g, g)} {_n(v)}" for g, v in parts) + ")" if parts else ""


def _n(v) -> str:
    """A count with thousands separators (T4: '1,170', as the DeepSeek check's '1,284/1,284'); text unchanged."""
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else str(v)


def _slip_lines(what: str, c: dict) -> list[str]:
    """Two owner lines of the stop slippage (T3): in percent, and what the real fills would have cost in dollars.
    ``diff_usd_total`` > 0 = the real stop fills would have lost that much more than the paper's assumed fill."""
    out = [f"손절 체결 {what}{_n(int(c['measured']))}건: 실제 미끄러짐 {c['real_bps_median'] / 100:.3f}% · "
           f"모의 가정 {c['paper_bps_median'] / 100:.3f}%"]
    d = c.get("diff_usd_total")
    if d is not None:
        from .notify import money
        out.append("→ 실제 손절 가격이었어도 손익 차이 $1 미만" if abs(d) < 0.5 else
                   f"→ 실제 손절 가격이었다면 {money(abs(d))} {'더' if d > 0 else '덜'} 손실")
    return out


def _groups_of(d) -> dict:
    """A report's split by group when it says something (two groups or more), else {}."""
    return d if isinstance(d, dict) and len(d) > 1 else {}


# G28: the 09:20 text gives numbers for the groups the owners follow trade by trade (groups.TRADE_ALERT_GROUPS; an
# unknown group with them) and ONE count line for DeepSeek; the coin flips' shadows stay in the report only.
NUMBER_GROUPS = ("core", "reel", "extra", "other")
COUNT_LINE_GROUP = "ds200"


def _v4_split(*splits) -> bool:
    """Is this a paper v4 report (a DeepSeek or reel group in a split)? A v3 report keeps its text."""
    return any(isinstance(s, dict) and ("ds200" in s or "reel" in s) for s in splits)


def _gko(g: str) -> str:
    try:
        from .groups import GROUP_KO
        return GROUP_KO.get(g, g)
    except Exception:  # noqa: BLE001
        return g


def _shadow_lines(sh: dict, slip: dict, usd) -> list[str]:
    """The limit / skipped / stop-slippage lines of a paper v4 report, split by group (G28)."""
    sg = sh.get("groups") if isinstance(sh.get("groups"), dict) else {}
    gg = slip.get("groups") if isinstance(slip.get("groups"), dict) else {}
    num = [g for g in NUMBER_GROUPS if g in sg and (g in ("core", "reel") or sg[g].get("limit_signals")
                                                     or sg[g].get("skipped"))]
    out = []
    if num:
        out.append("지정가였다면 체결 " + " · ".join(f"{_gko(g)} {_n(sg[g].get('limit_filled', 0))}/"
                                             f"{_n(sg[g].get('limit_signals', 0))}" for g in num))
        out.append("포지션 중이라 놓친 신호 " + " · ".join(f"{_gko(g)} {_n(sg[g].get('skipped', 0))}" for g in num))
    for g in NUMBER_GROUPS:
        c = gg.get(g) or {}
        if c.get("measured"):
            out += _slip_lines(f"{_gko(g)} ", c)
    d, ds = sg.get(COUNT_LINE_GROUP), gg.get(COUNT_LINE_GROUP)
    if d is not None or ds is not None:
        d = d or {}
        out.append(f"{_gko(COUNT_LINE_GROUP)} (개수만): 지정가 체결 {_n(d.get('limit_filled', 0))}/"
                   f"{_n(d.get('limit_signals', 0))} · 놓친 신호 {_n(d.get('skipped', 0))}"
                   + (f" · 손절 {_n(int((ds or {}).get('exits') or 0))}건" if ds is not None else ""))
    return out


def notify_report(report: dict, notifier, trades_day: Optional[int] = None) -> list[tuple[str, str]]:
    """ONE owner message from one nightly report (routing in docs/paper-v3-rules-addendum.md; owners' Telegram
    layout 2026-10-04): loud only for a real parity mismatch (CRITICAL) or a missing 00:00 snapshot (WARN);
    everything else (mismatches proven to be early 1m klines, ``parity.early_kline``, which are not counted in
    ``mismatched_accounts``; bars only on the live record; an extra's restart gap; missing 1m bars) is a line of
    the silent INFO summary (and the agents open no incident meeting for early klines).
    A paper v4 report (``parity.groups``, ``trades.groups``) adds the split by group: "재계산 일치 331/331 (매매법
    144/144 · 딥시크 171/171 · 5분 단타 1/1 · 동전 15/15)", the groups of the mismatched accounts and the trades by
    group; a report without them, or with one group only, reads as before."""
    from .notify import day_ko, usd
    day = day_ko(report["day"])
    level, head, lines = INFO, [f"🔎 매일 점검 · {day}"], []
    par = report.get("parity")
    dq = report.get("data_quality", {})
    missing = {s: q["missing"] for s, q in dq.items() if isinstance(q, dict) and q.get("missing")}
    if isinstance(par, dict):
        early = int(par.get("early_kline") or 0)
        ok = par['accounts'] - par['mismatched_accounts'] - par.get('crash_gaps', 0) - early
        pg = _groups_of(par.get("groups"))
        if par["mismatched_accounts"]:
            level = CRITICAL
            head = [f"재계산 불일치 · {day}", "", f"계좌 {par['mismatched_accounts']}개의 거래가 paper와 다름"
                    + _split_text([(g, x["mismatched"]) for g, x in pg.items() if x.get("mismatched")])]
            if early:
                head.append(f"(그 밖에 {early}개는 확정 전 1분봉: 정상)")
            head += ["운영 감사관 확인 필요", "자세히: daily3.db mismatches", "", "매일 점검"]
        lines.append(f"재계산 일치 {ok}/{par['accounts']}"
                     + _split_text([(g, f"{x['ok']}/{x['accounts']}") for g, x in pg.items()]))
        if early and not par["mismatched_accounts"]:
            lines.append(f"({early}개는 확정 전 1분봉: 정상)")
        only_live = (par.get("live_bars") or {}).get("only_on_live_bars") or []
        if only_live:
            lines.append(f"기록 확인 필요: 봇이 쓴 1분봉으로는 계좌 {len(only_live)}개가 paper와 다름 "
                         "(완성된 1분봉으로는 일치, daily3.db reports)")
        if par.get("crash_gaps"):
            lines.append(f"{CRASH_GAP_KO}: 추가 계좌 {par['crash_gaps']}개가 신호 1개를 놓침 (원래 계좌와는 무관)")
    elif report.get("start_day"):
        # the run's start day (G25): no 00:00 snapshot by design; silent, no incident (agents read ``start_day``)
        lines.append("시작 전 날: 재계산 없음 (봇이 아직 안 돌던 날)" if report["start_day"].get("before_run") else
                     "시작한 날: 재계산 없음 (09:00 상태 저장 뒤에 시작 · 첫 재계산은 내일 09:20)")
    else:
        level = WARN
        head = [f"재계산 못 함 · {day}", "", "그날 09:00(한국) 상태 저장이 없음", "봇이 그때 멈춰 있었음", "", "매일 점검"]
    if trades_day is not None:
        tg = _groups_of((report.get("trades") or {}).get("groups") if isinstance(report.get("trades"), dict) else None)
        lines.append(f"거래 {_n(trades_day)}건" + _split_text(list(tg.items())))
    sh = report.get("shadows", {})
    slip = report.get("stop_slippage") or {}
    v4 = _v4_split(sh.get("groups") if sh else None, slip.get("groups"))
    if sh and not v4:
        lines.append(f"지정가였다면 체결 {sh.get('limit_filled', 0)}/{sh.get('limit_signals', 0)}")
        lines.append(f"포지션 중이라 놓친 신호 {sh.get('skipped', 0)}")
    elif v4:
        lines += _shadow_lines(sh or {}, slip, usd)
    try:
        from .strengthwatch import summary_line
        st_line = summary_line(report.get("strength"))
    except Exception:  # noqa: BLE001
        st_line = None
    if st_line:
        lines.append(st_line)
    lines.append(f"빠진 1분봉 {sum(missing.values())}"
                 + (" (" + ", ".join(f"{s.replace('USDT', '')} {n}" for s, n in missing.items()) + ")" if missing else ""))
    ov = slip.get("overall") or {}
    if ov.get("measured") and not v4:
        lines += _slip_lines("", ov)
    if "dscheck" in report:            # a run with DeepSeek accounts: the night before's recomputation, its own day
        lines.append(report["dscheck"] or "딥시크 밤 재계산: 결과 없음 (점검이 아직 안 돌았거나 타이머가 꺼짐)")
    text = "\n".join(head + ([""] if level == INFO else []) + lines)
    msgs = [(level, text)]
    for level, text in msgs:
        notifier.send(level, text)
    return msgs


def main(argv: Optional[list[str]] = None) -> int:
    from .live import _notifier, _rest, load_brackets
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--db", default="paper3.db")
    ap.add_argument("--out", default="daily3.db")
    ap.add_argument("--day")
    ap.add_argument("--brackets")
    ap.add_argument("--allow-example-brackets", action="store_true")
    ap.add_argument("--no-notify", action="store_true",
                    help="write the report but send no Telegram (e.g. re-running a past day to relabel it)")
    ap.add_argument("--early-window-ms", type=int, default=EARLY_WINDOW_MS,
                    help="early 1m kline proof: the trade that reached the stop must be this close to the end of "
                         "the minute (default %(default)s)")
    ap.add_argument("--no-stop-slip", action="store_true",
                    help="skip the realistic stop slippage (4; it reads public aggTrades, a few minutes a night)")
    ap.add_argument("--dscheck-dir", default=DSCHECK_DIR,
                    help="the DeepSeek recomputation's folder (paperbot/dscheck.py --out; its last.txt is a line of "
                         "the 09:20 text; default %(default)s)")
    args = ap.parse_args(argv)
    if not os.path.exists(args.db):       # right after a reset, before the bot created paper3.db: nothing to check
        print(f"INFO: {args.db} does not exist yet (new run not started): nothing to check, skipped")
        return 0
    rest = _rest()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    run = conn.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
    fee = json.loads(run[0]).get("taker_fee") if run else None
    settings = v3_settings(**({"taker_fee": fee} if fee else {}))
    brackets, _ = load_brackets(rest, list(V3_SYMBOLS), args.brackets, args.allow_example_brackets)
    specs = rest.exchange_info(list(V3_SYMBOLS))
    day = args.day or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    out = sqlite3.connect(args.out)
    out.execute("PRAGMA journal_mode=WAL")
    out.executescript(SCHEMA)
    report = run_day(conn, out, rest, settings, brackets, specs, day, early_window_ms=args.early_window_ms,
                     stop_slip=not args.no_stop_slip, dscheck_dir=args.dscheck_dir)
    start = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    n = conn.execute("SELECT COUNT(*) FROM trades WHERE exit_time >= ? AND exit_time < ?",
                     (start, start + DAY_MS)).fetchone()[0]
    if not args.no_notify:
        notify_report(report, _notifier(), n)
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
