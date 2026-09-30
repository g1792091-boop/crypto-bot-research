"""Nightly checks for the paper v3 run (separate process, its own database).

    python -m paperbot.daily3 run --db paper3.db --out daily3.db [--day YYYY-MM-DD]
        [--brackets FILE | --allow-example-brackets]

For one UTC day (default: yesterday):

1. Replay parity. Start every account from the ``day:<date>`` snapshot the live
   runner saved at 00:00, feed it the day's 1m bars (last and mark price, funding,
   fetched again from Binance) and the day's submitted signals from signal_log,
   and compare the trades with the ones the live run recorded. Any difference is
   a mismatch (engine bug, restart problem or revised exchange data).
2. Shadows (no accounts): for every submitted signal of the day
   - limit: would a limit order 0.25 ATR better than the reference price have
     filled within one bar of the signal's timeframe, and with what net ROE under
     the same exit rules;
   - skipped: for signals an account skipped (position open, lower priority), the
     net ROE the trade would have had.
   Each shadow trade runs alone on $1,000 so results are comparable as ROE.
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
from .binance import BinanceREST, bars_from_klines
from .config import V3_STOP_ATR, V3_SYMBOLS, Settings, v3_settings
from .engine import PaperEngine, restore_engine
from .models import Bar, Signal
from .cards import STOP_VARIANTS
from .notify import CRITICAL, INFO, WARN

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


def day_signals(conn, start: int, end: int) -> dict[int, list[dict]]:
    """Submitted signals whose bar closed in [start, end], by bar close."""
    out: dict[int, list[dict]] = {}
    q = ("SELECT bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, delay_ms "
         "FROM signal_log WHERE status = 'SUBMITTED' AND bar_close > ? AND bar_close <= ? ORDER BY id")
    for r in conn.execute(q, (start, end)):
        d = dict(zip(("bar_close", "timeframe", "strategy", "symbol", "side", "atr", "ref_price", "ref_time",
                      "delay_ms"), r))
        out.setdefault(d["bar_close"], []).append(d)
    return out


def make_signal(d: dict, stop_atr: float = V3_STOP_ATR, ref: Optional[float] = None) -> Signal:
    return Signal(ts=d["bar_close"] - 1, symbol=d["symbol"], timeframe=d["timeframe"], strategy_id=d["strategy"],
                  side=int(d["side"]), stop_price=0.0, tier="best", atr=d["atr"],
                  meta={"stop_dist": stop_atr * d["atr"], "ref_price": ref if ref is not None else d["ref_price"],
                        "ref_time": d["ref_time"], "delay_ms": d["delay_ms"],
                        "account": f"{d['strategy']}@{d['timeframe']}"})


# ---------------------------------------------------------------- 1. replay parity
def replay(settings: Settings, brackets, specs, snapshot: dict, signals: dict, steps) -> dict[str, list]:
    engines = {}
    for aid, st in snapshot["engines"].items():
        e = PaperEngine(settings, brackets, symbol_specs=specs, book=aid)
        restore_engine(e, st)
        engines[aid] = e
    for ts, bars, funding in steps:
        tb = {s: b for s, b in bars.items() if s in brackets}
        for e in engines.values():
            e.step(tb, funding)
            e.outcomes.clear()
        for d in signals.get(ts + MIN, []):
            aid = f"{d['strategy']}@{d['timeframe']}"
            if aid in engines:
                engines[aid].submit(make_signal(d))
    return {aid: e.trades for aid, e in engines.items()}


def compare(replayed: dict[str, list], stored: dict[str, list[dict]]) -> list[dict]:
    out = []
    for aid in sorted(set(replayed) | set(stored)):
        a = [(t.symbol, t.entry_time, t.exit_time, t.exit_reason, round(t.exit_price, 10), round(t.pnl, 6))
             for t in replayed.get(aid, [])]
        b = [(t["symbol"], t["entry_time"], t["exit_time"], t["exit_reason"], round(t["exit_price"], 10),
              round(t["pnl"], 6)) for t in stored.get(aid, [])]
        if a != b:
            out.append({"account_id": aid, "replayed": a[:20], "stored": b[:20]})
    return out


def stored_trades(conn, start: int, end: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for aid, data in conn.execute("SELECT account_id, data FROM trades WHERE exit_time >= ? AND exit_time < ? "
                                  "ORDER BY id", (start, end)):
        out.setdefault(aid, []).append(json.loads(data))
    return out


# ---------------------------------------------------------------- 2. shadows
def _alone(settings: Settings, brackets, specs, sig: Signal, steps, i0: int) -> tuple[Optional[object], bool]:
    """Run one signal on a fresh $1,000 account from step index i0. Returns (trade or None, resolved)."""
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
        t, resolved = _alone(settings, brackets, specs, sig, steps, i0)
        rows.append({"key": f"skipped|{aid}|{s['symbol']}|{bc}", "day": day, "kind": "skipped",
                     "account_id": aid, "symbol": s["symbol"], "timeframe": s["timeframe"], "side": s["side"],
                     "filled": None, "roe": None if t is None else t.roe,
                     "exit_reason": None if t is None else t.exit_reason, "resolved": int(resolved), "data": "{}"})
    rows += stop_shadows(settings, brackets, specs, conn, day, start, end, steps, sigs, idx)
    return rows


def stop_shadows(settings: Settings, brackets, specs, conn, day: str, start: int, end: int, steps,
                 sigs: dict, idx: dict) -> list[dict]:
    """For every losing trade (stop or liquidation) whose signal bar closed in the day: the
    same signal alone with a 1.5 / 2.5 / 3 ATR stop (leverage re-chosen by the same rules).
    Feeds the loss cards (cards.py)."""
    rows = []
    q = ("SELECT account_id, data FROM trades WHERE exit_reason IN ('SL', 'LIQ') "
         "AND entry_time >= ? AND entry_time < ?")
    lost = {}
    for aid, data in conn.execute(q, (start, end + DAY_MS)):
        t = json.loads(data)
        lost[(aid, t["symbol"], t["signal_ts"] + 1)] = t
    for bc, lst in sigs.items():
        i0 = idx.get(bc)
        if i0 is None:
            continue
        for d in lst:
            aid = f"{d['strategy']}@{d['timeframe']}"
            if (aid, d["symbol"], bc) not in lost:
                continue
            for k in STOP_VARIANTS:
                t, resolved = _alone(settings, brackets, specs, make_signal(d, stop_atr=k), steps, i0)
                rows.append({"key": f"stop{k}|{aid}|{d['symbol']}|{bc}", "day": day, "kind": f"stop{k}",
                             "account_id": aid, "symbol": d["symbol"], "timeframe": d["timeframe"],
                             "side": d["side"], "filled": None, "roe": None if t is None else t.roe,
                             "exit_reason": None if t is None else t.exit_reason, "resolved": int(resolved),
                             "data": json.dumps({"leverage": None if t is None else t.leverage,
                                                 "actual_roe": lost[(aid, d["symbol"], bc)]["roe"]})})
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
def run_day(conn, out: sqlite3.Connection, rest: BinanceREST, settings: Settings, brackets, specs,
            day: str, horizon_days: int = 3) -> dict:
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
        rep = replay(settings, brackets, specs, json.loads(snap[0]), day_signals(conn, start, end), day_steps)
        mism = compare({a: [t for t in ts if t.exit_time < end] for a, ts in rep.items()},
                       stored_trades(conn, start, end))
        report["parity"] = {"accounts": len(rep), "mismatched_accounts": len(mism)}
    sh = shadows(settings, brackets, specs, conn, day, start, end, steps)
    lim = [r for r in sh if r["kind"] == "limit"]
    report["shadows"] = {
        "limit_signals": len(lim), "limit_filled": sum(r["filled"] for r in lim),
        "limit_mean_roe": float(np.mean([r["roe"] for r in lim if r["roe"] is not None]))
        if any(r["roe"] is not None for r in lim) else None,
        "skipped": sum(1 for r in sh if r["kind"] == "skipped"),
        "stop_variants": {},
    }
    for k in STOP_VARIANTS:
        v = [r for r in sh if r["kind"] == f"stop{k}" and r["roe"] is not None and r["resolved"]]
        report["shadows"]["stop_variants"][str(k)] = {
            "losing_trades": len(v),
            "mean_roe": float(np.mean([r["roe"] for r in v])) if v else None,
            "turned_positive": sum(1 for r in v if r["roe"] > 0),
            "better_than_actual": sum(1 for r in v if r["roe"] > json.loads(r["data"])["actual_roe"]),
        }
    report["data_quality"] = data_quality(day_steps, symbols, start, end)
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
    are WARN, and the one-line summary is a silent INFO message."""
    day = report["day"]
    msgs = []
    par = report.get("parity")
    if isinstance(par, dict):
        if par["mismatched_accounts"]:
            msgs.append((CRITICAL, f"[{day}] 재계산 불일치: 계좌 {par['mismatched_accounts']}개의 거래가 "
                                   "paper와 다릅니다. 운영 감사관 확인 필요 (daily3.db mismatches)"))
        par_txt = f"재계산 일치 {par['accounts'] - par['mismatched_accounts']}/{par['accounts']}"
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
    report = run_day(conn, out, rest, settings, brackets, specs, day)
    start = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    n = conn.execute("SELECT COUNT(*) FROM trades WHERE exit_time >= ? AND exit_time < ?",
                     (start, start + DAY_MS)).fetchone()[0]
    notify_report(report, _notifier(), n)
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
