"""A synthetic paper3.db for 조합 성과 (#/combo; tests/test_dash_combo.py and the combo-paper screenshot harness).

The v4 run shape (the 36 locked strategies x 15m / 30m / 1h / 4h, the 12 core coin flips, a few DeepSeek definitions,
the reel and its three 5m coin flips) with everything the combo views read:

- closed trades that carry the TradeRecord fields (side, signal_ts = the signal bar's close - 1, entry_time = that
  close), strategies in six clusters that win and lose on the same days and share part of their entries (same coin,
  side and about the same bar), so correlations and 'same bet' overlaps have something to find;
- the 5-minute ``equity`` samples of every account (wallet between trades, the open trade's P&L moving in with a
  wiggle while it is open: mark-to-market like accounts.AccountBook writes them);
- ``signal_log`` rows: one per trade's signal, plus signals the account could not take because it was busy (status
  SUBMITTED, no trade), as sigservice writes every signal it computes;
- state 'accounts' (engines with a few open positions), 'run', 'heartbeat'.

Deterministic (``seed``). ``days`` may be fractional (1.4 = the first day and a half: the day 0-1 waiting states).

    from combo_world import build
    info = build("/tmp/x/paper3.db", days=20)
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
from dataclasses import asdict  # noqa: F401  (kept for callers that build TradeRecords by hand)

import numpy as np

from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.config import DS200_DEFS, REEL_NAME
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
STEP = 5 * MIN
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": HOUR, "4h": 4 * HOUR}
CORE_TFS = ("15m", "30m", "1h", "4h")
PER_DAY = {"5m": 4.0, "15m": 2.6, "30m": 1.8, "1h": 1.1, "4h": 0.45}
HOLD_BARS = {"5m": (2, 30), "15m": (2, 16), "30m": (2, 12), "1h": (1, 10), "4h": (1, 6)}
BASE = {"BTCUSDT": 62000.0, "ETHUSDT": 2450.0, "SOLUSDT": 145.0, "DOGEUSDT": 0.118, "LTCUSDT": 66.0, "BCHUSDT": 330.0}
SYMS = tuple(BASE)
INITIAL = 5000.0


def kst(y, m, d, hh=0, mm=0) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc).timestamp() * 1000) - 9 * HOUR


def record(strategy: str, tf: str, symbol: str, side: int, entry: int, exit_t: int, pnl: float, wallet: float,
           lev: int = 30, reason: str | None = None) -> TradeRecord:
    margin = wallet * lev / 100.0
    P = BASE.get(symbol, 100.0)
    roe = pnl / margin if margin > 0 else 0.0
    px = P * (1 + side * roe / lev)
    return TradeRecord(
        strategy_id=strategy, symbol=symbol, timeframe=tf, side=side, signal_ts=entry - 1, entry_time=entry,
        entry_price=P, exit_time=exit_t, exit_price=px, exit_reason=reason or ("LOCK" if pnl > 0 else "SL"),
        qty=margin * lev / P, leverage=lev, tier="normal", margin=margin, stop_price=P * (1 - side * 0.006),
        tp_price=float("nan"), liq_price=P * (1 - side * 0.9 / lev), fees=margin * lev * 0.001, funding=0.0,
        pnl=pnl, roe=roe, price_move=side * (px / P - 1), mae_price=P, mfe_price=P, equity_after=wallet + pnl,
        score=0.0, context={}, stop_initial=P * (1 - side * 0.006), lock_roe=None)


def _accounts(strategies, ds_defs: int) -> list:
    out = []                                          # (aid, strategy, tf, kind)
    for tf in CORE_TFS:
        out += [(f"{s}@{tf}", s, tf, "strategy") for s in strategies]
    for tf in CORE_TFS:
        out += [(f"RANDOM_{k}@{tf}", f"RANDOM_{k}", tf, "random") for k in (1, 2, 3)]
    for name, _fam, tfs in DS200_DEFS[:ds_defs]:
        out += [(f"{name}@{tf}", name, tf, "ds200") for tf in tfs]
    out.append((f"{REEL_NAME}@5m", REEL_NAME, "5m", "reel"))
    out += [(f"RANDOM_{k}@5m", f"RANDOM_{k}", "5m", "random") for k in (1, 2, 3)]
    return out


def build(path: str, days: float = 20, seed: int = 7, start: int | None = None, strategies=None,
          equity: bool = True, signals: bool = True, ds_defs: int = 3, open_positions: int = 12) -> dict:
    """Write the world to ``path`` (a new file). ``start`` defaults to 2026-10-06 03:35 KST (the v4 start)."""
    rng = random.Random(seed)
    start = kst(2026, 10, 6, 3, 35) if start is None else int(start)    # 10/06 03:35 KST (the v4 start)
    now = start + int(days * DAY)
    core = list(strategies or STRATEGY_KO)
    cluster = {s: i % 6 for i, s in enumerate(core)}
    skill = {s: rng.gauss(0, 1) for s in core}
    accounts = _accounts(core, ds_defs)
    st = Store3(path)
    for aid, s, tf, kind in accounts:
        group = {"strategy": "core", "random": "flip", "ds200": "ds200", "reel": "reel"}[kind]
        exits = "reel" if kind == "reel" or (kind == "random" and tf == "5m") else "house"
        st.add_account(aid, s, tf, kind, start, "paper-v4", None, {"group": group, "exits": exits})
    st.put_state("run", start, {"taker_fee": 0.0005, "initial_equity": INITIAL, "settings": "paper-v4"})
    st.add_run(start, {"commit": "combo-fixture", "changes": []})
    nd = max(1, math.ceil(days))
    mood = [[rng.gauss(0, 1) for _c in range(6)] for _d in range(nd)]
    market = [rng.gauss(0, 0.8) for _d in range(nd)]
    events = {(c, d): [(start + d * DAY + rng.randrange(0, DAY - 4 * HOUR), rng.choice(SYMS), rng.choice((1, -1)))
                       for _ in range(4)] for c in range(6) for d in range(nd)}
    grid = np.arange((start + STEP - 1) // STEP * STEP, now + 1, STEP, dtype=np.int64)
    n_tr = n_sig = n_busy = 0
    engines = {}
    opened = 0
    sig_rows: list = []
    eq_rows: list = []
    for aid, s, tf, kind in accounts:
        bar = TF_MS[tf]
        wallet = INITIAL
        t = start + rng.randrange(0, 2 * bar)
        trades = []
        while True:
            gap = rng.expovariate(PER_DAY[tf] / DAY)
            t = (int(t + gap) // bar) * bar
            if t < start:
                t += bar
            d = (t - start) // DAY
            if t >= now - bar or d >= nd:
                break
            sym, side = rng.choice(SYMS), rng.choice((1, -1))
            if kind == "strategy" and rng.random() < 0.5:             # a cluster entry: same coin, side, about the bar
                et, sym, side = rng.choice(events[(cluster[s], d)])
                t = max(t, (et // bar) * bar)
                while t < start:                                     # the first bar boundary after the start
                    t += bar
            if kind == "reel" or (kind == "random" and tf == "5m"):
                side = 1
            hold = rng.randint(*HOLD_BARS[tf]) * bar
            exit_t = t + hold
            if exit_t >= now:
                break
            if kind == "strategy":
                p = 0.5 + 0.06 * skill[s] + 0.25 * math.tanh(mood[d][cluster[s]] + 0.6 * market[d])
            elif kind == "ds200":
                p = 0.5 + 0.15 * math.tanh(market[d])
            else:
                p = 0.47 + 0.1 * math.tanh(0.5 * market[d] * side)
            lev = rng.choice((20, 30, 30, 40))
            margin = wallet * lev / 100.0
            pnl = margin * (rng.uniform(0.05, 0.45) if rng.random() < p else -rng.uniform(0.05, 0.3))
            rec = record(s, tf, sym, side, t, exit_t, pnl, wallet, lev)
            st.trade(aid, rec)
            trades.append((t, exit_t, wallet, pnl))
            wallet += pnl
            n_tr += 1
            if signals:
                sig_rows.append((t, tf, s, sym, side, "SUBMITTED"))
                n_sig += 1
                # signals the account could not take while this trade was open (busy): logged, never traded
                k = t + bar
                while k < exit_t:
                    if rng.random() < 0.18:
                        sig_rows.append((k, tf, s, rng.choice(SYMS), 1 if tf == "5m" else rng.choice((1, -1)), "SUBMITTED"))
                        n_sig += 1
                        n_busy += 1
                    k += bar
            t = exit_t
        pos = None
        if opened < open_positions and kind in ("strategy", "random") and rng.random() < 0.25:
            opened += 1
            sym = rng.choice(SYMS)
            P = BASE[sym]
            side = rng.choice((1, -1))
            pos = {"symbol": sym, "side": side, "qty": wallet * 0.3 * 30 / P, "entry_price": P,
                   "entry_time": int(now - rng.randrange(1, 4) * TF_MS[tf]), "leverage": 30, "tier": "normal",
                   "margin": wallet * 0.3, "margin_initial": wallet * 0.3, "stop_price": P * (1 - side * 0.006),
                   "tp_price": None, "liq_price": P * (1 - side * 0.03), "entry_fee": 1.0, "funding_paid": 0.0,
                   "mae_price": P, "mfe_price": P, "stop_initial": P * (1 - side * 0.006), "lock_roe": None,
                   "signal": {"meta": {}}}
        engines[aid] = {"wallet": wallet, "peak_equity": max(INITIAL, wallet), "max_drawdown": 0.0, "halted": False,
                        "halt_reason": "", "bust": False, "warned": [], "last_mark": {}, "position": pos,
                        "pending": [], "n_trades": len(trades)}
        if equity and len(grid):
            eq = np.full(len(grid), INITIAL)
            w = INITIAL
            phase = rng.random() * 6.0
            for t0, t1, w0, pnl in trades:
                a, b = np.searchsorted(grid, t0), np.searchsorted(grid, t1)
                if b > a:                                      # the open trade: its P&L moving in, with a wiggle
                    x = (grid[a:b] - t0) / max(1, t1 - t0)
                    eq[a:b] = w0 + pnl * x + 0.35 * abs(pnl) * np.sin(phase + 9.0 * x) * np.sin(math.pi * x)
                eq[b:] = w0 + pnl
                w = w0 + pnl
            del w
            peak = np.maximum.accumulate(np.maximum(eq, INITIAL))
            dd = 1 - eq / peak
            eq_rows.extend(zip([aid] * len(grid), grid.tolist(), np.round(eq, 4).tolist(), np.round(dd, 6).tolist()))
            if len(eq_rows) > 400_000:
                st.conn.executemany("INSERT OR REPLACE INTO equity VALUES (?,?,?,?)", eq_rows)
                eq_rows.clear()
    if eq_rows:
        st.conn.executemany("INSERT OR REPLACE INTO equity VALUES (?,?,?,?)", eq_rows)
    if sig_rows:
        sig_rows.sort()
        st.conn.executemany("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, atr, ref_price, "
                            "ref_time, delay_ms, status, data) VALUES (?,?,?,?,?,1.0,1.0,?,1000,?,'{}')",
                            [(b, tf, s, sym, side, b + 1000, status) for b, tf, s, sym, side, status in sig_rows])
    st.put_state("accounts", now, {"last_ts": now, "engines": engines})
    st.put_state("heartbeat", now, {"steps": 1, "last_step": now})
    st.commit()
    st.close()
    return {"start": start, "now": now, "trades": n_tr, "signals": n_sig, "busy_signals": n_busy,
            "accounts": len(accounts), "open": opened, "days": days, "strategies": core}


# ---------------------------------------------------------------- hand-made cases (tests)
def blank(path: str, start: int, accounts: list, initial: float = INITIAL) -> Store3:
    """An empty paper3.db with ``accounts`` [(aid, kind)] created at ``start``."""
    st = Store3(path)
    for aid, kind in accounts:
        s, tf = aid.split("@")
        st.add_account(aid, s, tf, kind, start, "paper-v4", None, {})
    st.put_state("run", start, {"taker_fee": 0.0005, "initial_equity": initial})
    st.commit()
    return st


def trade(st: Store3, aid: str, entry: int, exit_t: int, pnl: float, *, symbol="BTCUSDT", side=1, wallet=INITIAL,
          lev=30, signal_bar=None) -> None:
    """One closed trade (``signal_bar``: the signal bar's close, default the entry time)."""
    s, tf = aid.split("@")
    rec = record(s, tf, symbol, side, entry, exit_t, pnl, wallet, lev)
    if signal_bar is not None:
        rec.signal_ts = int(signal_bar) - 1
    st.trade(aid, rec)


def equity(st: Store3, aid: str, points) -> None:
    """5-minute samples [(ts, equity)]."""
    st.conn.executemany("INSERT OR REPLACE INTO equity VALUES (?,?,?,0)", [(aid, int(t), float(e)) for t, e in points])


def signal(st: Store3, strategy: str, tf: str, bar_close: int, symbol: str = "BTCUSDT", side: int = 1,
           status: str = "SUBMITTED") -> None:
    st.conn.execute("INSERT INTO signal_log (bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, "
                    "delay_ms, status, data) VALUES (?,?,?,?,?,1.0,1.0,?,1000,?,'{}')",
                    (int(bar_close), tf, strategy, symbol, int(side), int(bar_close) + 1000, status))


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True)
