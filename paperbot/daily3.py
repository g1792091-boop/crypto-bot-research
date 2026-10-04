"""Nightly checks for the paper v3 run (separate process, its own database).

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
   (killed between the 195's commit and the copy's) is reported for that copy
   only, as "추가 계좌 재시작 틈".
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
   coin-minute. Early-kline accounts are counted apart (``parity.early_kline``), like the restart gaps: one WARN,
   no CRITICAL, no incident meeting (paperbot/agents/triggers.py). docs/signal-recording.md has the background.
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
   Each shadow trade runs alone on a fresh account (the starting equity) so results are comparable as ROE.
3. Data quality: missing minutes, zero-volume minutes, extreme ranges, last vs
   mark price gaps, extreme funding.

paper3.db is opened read-only; results go to ``--out``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from dataclasses import replace
from typing import Optional

import numpy as np

from .accounts import DAY_MS, day_key
from .aggregate import TF_MS
from .binance import BinanceError, BinanceREST, bars_from_klines
from .config import V3_STOP_ATR, V3_SYMBOLS, Settings, v3_settings
from .engine import PaperEngine, restore_engine
from .models import Bar, Signal
from .cards import STOP_VARIANTS
from .notify import CRITICAL, INFO, WARN
from .obsshadows import LOOKBACK_MS, first_signal, summarize, trade_shadows

MIN = 60_000
LIMIT_ATR = 0.25

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (day TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mismatches (day TEXT NOT NULL, account_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadows (
    key TEXT PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL, account_id TEXT NOT NULL,
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, side INTEGER NOT NULL,
    filled INTEGER, roe REAL, exit_reason TEXT, resolved INTEGER NOT NULL, data TEXT NOT NULL
);
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


def make_signal(d: dict, stop_atr: float = V3_STOP_ATR, ref: Optional[float] = None) -> Signal:
    return Signal(ts=d["bar_close"] - 1, symbol=d["symbol"], timeframe=d["timeframe"], strategy_id=d["strategy"],
                  side=int(d["side"]), stop_price=0.0, tier="best", atr=d["atr"],
                  meta={"stop_dist": stop_atr * d["atr"], "ref_price": ref if ref is not None else d["ref_price"],
                        "ref_time": d["ref_time"], "delay_ms": d["delay_ms"],
                        "account": f"{d['strategy']}@{d['timeframe']}"})


# ---------------------------------------------------------------- 1. replay parity
EXTRA_STATUS = {"created": "active", "resumed": "active", "suspended": "suspended", "held": "held"}


def extras_of(conn) -> dict:
    """The extra accounts of a paper3.db as the replay needs them: {aid: {kind, parent, created_ts, rule,
    stop_atr, skip_tag, timeline [(effective ms, status)]}} (``{}`` for a database without extras)."""
    from .extras import parse_rule, rule_fields
    rows = conn.execute("SELECT account_id, kind, parent, created_ts, data FROM accounts "
                        "WHERE kind NOT IN ('strategy', 'random') ORDER BY rowid").fetchall()
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
    try:
        data = json.loads(d.get("data") or "{}")
    except (TypeError, ValueError):
        return {}
    ctx = data.get("ctx") if isinstance(data, dict) else None
    return ctx if isinstance(ctx, dict) else {}


def replay(settings: Settings, brackets, specs, snapshot: dict, signals: dict, steps,
           extras: Optional[dict] = None) -> dict[str, list]:
    """Replay the day from the 00:00 snapshot. ``extras`` (``extras_of``): the extra accounts' own rules,
    starts during the day and suspended / held intervals; the original accounts use ``settings`` unchanged."""
    from .extras import settings_for, skip_hit
    extras = extras or {}
    engines = {}

    def make(aid):
        x = extras.get(aid)
        return PaperEngine(settings if x is None else settings_for(settings, x["rule"]), brackets,
                           symbol_specs=specs, book=aid)
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
    signal in a restart; never a mismatch of the 195)."""
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
                       extras: Optional[dict] = None, window_ms: int = EARLY_WINDOW_MS) -> dict:
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
                          extras=extras)
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
def _alone(settings: Settings, brackets, specs, sig: Signal, steps, i0: int) -> tuple[Optional[object], bool]:
    """Run one signal on a fresh account (settings.initial_equity) from step index i0. Returns (trade or None, resolved)."""
    e = PaperEngine(settings, brackets, symbol_specs=specs, book="shadow")
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
    idx = {ts: k for k, (ts, _, _) in enumerate(steps)}
    rows = []
    ext = extras_of(conn)
    sigs = day_signals(conn, start - 1, end - 1)
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
                                     replace(make_signal(d, ref=px), ts=steps[k][0] - 1), steps, k)
                if t is not None:
                    # a resting limit pays the maker fee and no entry slippage
                    roe = t.roe + t.leverage * (settings.taker_fee - settings.maker_fee + settings.slippage_frac)
                    reason = t.exit_reason
            rows.append({"key": key, "day": day, "kind": "limit", "account_id": aid, "symbol": d["symbol"],
                         "timeframe": d["timeframe"], "side": d["side"], "filled": int(fill is not None),
                         "roe": roe, "exit_reason": reason, "resolved": int(resolved), "data": "{}"})
    q = ("SELECT account_id, data FROM outcomes WHERE status = 'SKIPPED' AND step_ts >= ? AND step_ts < ?")
    for aid, data in conn.execute(q, (start, end)):
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
        t, resolved = _alone(acc_settings, brackets, specs, sig, steps, i0)
        rows.append({"key": f"skipped|{aid}|{s['symbol']}|{bc}", "day": day, "kind": "skipped",
                     "account_id": aid, "symbol": s["symbol"], "timeframe": s["timeframe"], "side": s["side"],
                     "filled": None, "roe": None if t is None else t.roe,
                     "exit_reason": None if t is None else t.exit_reason, "resolved": int(resolved), "data": "{}"})
    rows += stop_shadows(settings, brackets, specs, conn, day, start, end, steps, sigs, idx, ext)
    return rows


def stop_shadows(settings: Settings, brackets, specs, conn, day: str, start: int, end: int, steps,
                 sigs: dict, idx: dict, ext: Optional[dict] = None) -> list[dict]:
    """For every losing trade (stop or liquidation) whose signal bar closed in the day: the
    same signal alone with a 1.5 / 2.5 / 3 ATR stop (leverage re-chosen by the same rules).
    Feeds the loss cards (cards.py). A copy account's cards read these rows under its parent's id (the copy
    repeats the parent's signal), so a parent signal is also computed when only a copy of it lost (the parent
    won or was not in it): such a row has ``actual_roe`` None and ``copies`` (left out of the day's summary,
    which is about the original accounts' losses)."""
    rows = []
    q = ("SELECT account_id, data FROM trades WHERE exit_reason IN ('SL', 'LIQ') "
         "AND entry_time >= ? AND entry_time < ?")
    parent_of = {aid: x["parent"] for aid, x in (ext or {}).items() if x.get("kind") == "copy" and x.get("parent")}
    lost, copy_lost = {}, {}
    for aid, data in conn.execute(q, (start, end + DAY_MS)):
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


def run_day(conn, out: sqlite3.Connection, rest: BinanceREST, settings: Settings, brackets, specs,
            day: str, horizon_days: int = 3, early_window_ms: int = EARLY_WINDOW_MS) -> dict:
    start = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    end = start + DAY_MS
    now = rest.server_time()
    last = min(now - now % MIN, end + horizon_days * DAY_MS)
    symbols = list(brackets)
    steps = fetch_steps(rest, symbols, start, last)
    day_steps = [s for s in steps if s[0] < end]
    report = {"day": day, "steps": len(day_steps)}
    snap = conn.execute("SELECT data FROM state WHERE k = ?", (day_key(start),)).fetchone()
    if snap is None:
        report["parity"] = "no 00:00 snapshot for this day (runner not running then)"
        mism = []
    else:
        ext = extras_of(conn)
        snap_d = json.loads(snap[0])
        sigs = day_signals(conn, start, end, with_data=bool(ext))
        rep = replay(settings, brackets, specs, snap_d, sigs, day_steps, extras=ext)
        rep_day = {a: [t for t in ts if t.exit_time < end] for a, ts in rep.items()}
        stored = stored_trades(conn, start, end)
        mism = compare(rep_day, stored)
        if ext:
            label_crash_gaps(mism, ext, conn)
        gaps = sum(1 for m in mism if m.get("crash_gap"))
        early = explain_mismatches(conn, rest, settings, brackets, specs, snap_d, sigs, day_steps, rep_day, stored,
                                   mism, start, end, extras=ext, window_ms=early_window_ms)
        n_early = early["early_kline"]
        report["parity"] = {"accounts": len(rep), "mismatched_accounts": len(mism) - gaps - n_early}
        if n_early:
            report["parity"].update(early_kline=n_early, early_kline_events=early["early_kline_events"])
        if early.get("live_bars") is not None:
            report["parity"]["live_bars"] = {"bars": early["live_bars"], **(early.get("live_bars_replay") or {})}
        if ext:
            report["parity"].update(extra_accounts=sum(1 for a in rep if a in ext), crash_gaps=gaps)
    sh = shadows(settings, brackets, specs, conn, day, start, end, steps)
    # trades that closed today but were entered earlier need the steps from their signal on
    first = first_signal(conn, start, end)
    pre = fetch_steps(rest, symbols, max(first, start - LOOKBACK_MS), start) if first is not None else []
    tv, tv_info = trade_shadows(settings, brackets, specs, conn, day, start, end, pre + steps, make_signal,
                                quality=True)
    lim = [r for r in sh if r["kind"] == "limit"]
    report["shadows"] = {
        "limit_signals": len(lim), "limit_filled": sum(r["filled"] for r in lim),
        "limit_mean_roe": float(np.mean([r["roe"] for r in lim if r["roe"] is not None]))
        if any(r["roe"] is not None for r in lim) else None,
        "skipped": sum(1 for r in sh if r["kind"] == "skipped"),
        "stop_variants": {},
    }
    for k in STOP_VARIANTS:
        v = [r for r in sh if r["kind"] == f"stop{k}" and r["roe"] is not None and r["resolved"]
             and json.loads(r["data"]).get("actual_roe") is not None]     # the original accounts' losses
        report["shadows"]["stop_variants"][str(k)] = {
            "losing_trades": len(v),
            "mean_roe": float(np.mean([r["roe"] for r in v])) if v else None,
            "turned_positive": sum(1 for r in v if r["roe"] > 0),
            "better_than_actual": sum(1 for r in v if r["roe"] > json.loads(r["data"])["actual_roe"]),
        }
    report["shadows"]["trade_variants"] = summarize(tv, tv_info)
    sh += tv
    report["data_quality"] = data_quality(day_steps, symbols, start, end)
    report["fill_costs"] = fill_cost_report(conn, start, end)
    out.execute("DELETE FROM mismatches WHERE day = ?", (day,))
    out.executemany("INSERT INTO mismatches VALUES (?,?,?)", [(day, m["account_id"], json.dumps(m)) for m in mism])
    out.executemany("INSERT OR REPLACE INTO shadows VALUES (:key,:day,:kind,:account_id,:symbol,:timeframe,:side,"
                    ":filled,:roe,:exit_reason,:resolved,:data)", sh)
    out.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (day, int(time.time() * 1000), json.dumps(report)))
    out.commit()
    return report


def notify_report(report: dict, notifier, trades_day: Optional[int] = None) -> list[tuple[str, str]]:
    """Owner alerts from one nightly report (routing in docs/paper-v3-rules-addendum.md):
    a parity mismatch or a missing 00:00 snapshot is loud (CRITICAL/WARN), data gaps
    are WARN, and the one-line summary is a silent INFO message. Mismatches proven to be early 1m klines
    (``parity.early_kline``) are not counted in ``mismatched_accounts``: when they are all there is, one WARN
    instead of the CRITICAL (and the agents open no incident meeting for them)."""
    day = report["day"]
    msgs = []
    par = report.get("parity")
    if isinstance(par, dict):
        early = int(par.get("early_kline") or 0)
        if par["mismatched_accounts"]:
            more = f" (그 밖에 {early}개는 '1분봉을 확정 전에 읽음'으로 확인됨)" if early else ""
            msgs.append((CRITICAL, f"[{day}] 재계산 불일치: 계좌 {par['mismatched_accounts']}개의 거래가 "
                                   f"paper와 다릅니다. 운영 감사관 확인 필요 (daily3.db mismatches){more}"))
        elif early:
            msgs.append((WARN, f"[{day}] 재계산 차이 {early}개 계좌: 모두 '1분봉을 확정 전에 읽음'으로 확인됨"
                               f"(계산 오류 아님, {EARLY_DOC})"))
        only_live = (par.get("live_bars") or {}).get("only_on_live_bars") or []
        if only_live:
            msgs.append((WARN, f"[{day}] 봇이 쓴 1분봉으로 다시 계산하면 계좌 {len(only_live)}개가 paper와 다릅니다 "
                               "(완성된 1분봉으로는 일치, 기록 확인 필요: daily3.db reports)"))
        if par.get("crash_gaps"):
            msgs.append((WARN, f"[{day}] {CRASH_GAP_KO}: 추가 계좌 {par['crash_gaps']}개가 재시작 때 신호 하나를 놓쳤습니다 "
                               "(원래 195개 계좌와는 무관, daily3.db mismatches)"))
        ok = par['accounts'] - par['mismatched_accounts'] - par.get('crash_gaps', 0) - early
        par_txt = f"재계산 일치 {ok}/{par['accounts']}" + (f" (확정 전 1분봉 {early})" if early else "")
    else:
        msgs.append((WARN, f"[{day}] 재계산 못 함: 그날 00:00 상태 저장이 없습니다 (봇이 멈춰 있었음)"))
        par_txt = "재계산 못 함"
    dq = report.get("data_quality", {})
    missing = {s: q["missing"] for s, q in dq.items() if isinstance(q, dict) and q.get("missing")}
    if missing:
        msgs.append((WARN, f"[{day}] 빠진 1분봉: " + ", ".join(f"{s} {n}" for s, n in missing.items())))
    sh = report.get("shadows", {})
    parts = [par_txt]
    if trades_day is not None:
        parts.append(f"거래 {trades_day}건")
    if sh:
        parts.append(f"지정가였다면 체결 {sh.get('limit_filled', 0)}/{sh.get('limit_signals', 0)}")
        parts.append(f"포지션 중이라 놓친 신호 {sh.get('skipped', 0)}")
    parts.append("빠진 1분봉 " + str(sum(missing.values())))
    msgs.append((INFO, f"[{day}] 매일 점검: " + " · ".join(parts)))
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
    args = ap.parse_args(argv)
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
    report = run_day(conn, out, rest, settings, brackets, specs, day, early_window_ms=args.early_window_ms)
    start = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    n = conn.execute("SELECT COUNT(*) FROM trades WHERE exit_time >= ? AND exit_time < ?",
                     (start, start + DAY_MS)).fetchone()[0]
    if not args.no_notify:
        notify_report(report, _notifier(), n)
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
