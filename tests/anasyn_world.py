"""A synthetic paper3.db for the ana-syn views (tests/test_dash_ana_syn.py and the screenshot harness): the v4 run shape
(the 36 locked strategies x 15m / 30m / 1h / 4h, the 12 core coin flips, some DeepSeek definitions, the reel and its
three 5m coin flips), ``days`` KST days of closed trades that carry every TradeRecord field (stop_initial, lock_roe,
mae_price, mfe_price consistent with the exit reason and the house ladder), and a few open positions in state
'accounts'. Deterministic (``seed``). Strategies come in six clusters that win and lose on the same days, and part of a
cluster's entries share the same coin, side and bar (so 'same bet' and 'fall together' have something to find).

    from anasyn_world import build
    info = build("/tmp/x/paper3.db", days=30)          # {"start", "now", "trades", ...}
"""
from __future__ import annotations

import datetime as dt
import json
import math
import random
from dataclasses import asdict

from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.config import DS200_DEFS, REEL_NAME
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

HOUR, DAY, MIN = 3_600_000, 86_400_000, 60_000
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": HOUR, "4h": 4 * HOUR}
CORE_TFS = ("15m", "30m", "1h", "4h")
PER_DAY = {"5m": 4.0, "15m": 2.6, "30m": 1.8, "1h": 1.1, "4h": 0.45}       # trades a day per account (about)
HOLD_BARS = {"5m": (2, 30), "15m": (2, 16), "30m": (2, 12), "1h": (1, 10), "4h": (1, 6)}
BASE = {"BTCUSDT": 62000.0, "ETHUSDT": 2450.0, "SOLUSDT": 145.0, "DOGEUSDT": 0.118, "LTCUSDT": 66.0, "BCHUSDT": 330.0}
SYMS = tuple(BASE)
MARGIN = {50: 0.5, 40: 0.4, 30: 0.3, 20: 0.2}
RT = 0.0014                      # v3_settings().round_trip_cost (taker 0.05% x 2 + slippage)
FIRST_LOCK, STEP, GAP = 0.10, 0.05, 0.02
INITIAL = 5000.0


def kst(y, m, d, hh=0, mm=0) -> int:
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc).timestamp() * 1000) - 9 * HOUR


def record(strategy, tf, symbol, side, entry, exit_t, reason, lev, wallet, *, lock_roe=None, roe=None, mae_stop=0.3,
           mfe_r=0.4, tier="normal"):
    """One closed trade with prices consistent with ``reason``: SL at the 2-ATR stop (0.6% here), LOCK at its lock,
    LIQ the whole margin, TP / TIME at ``roe``. Returns (TradeRecord, new wallet)."""
    P = BASE[symbol] * (1 + 0.01 * math.sin(entry / DAY))
    dist = P * 0.006
    stop0 = P - side * dist
    margin = wallet * MARGIN[lev]
    qty = margin * lev / P
    liq = P * (1 - side * 0.9 / lev)
    if reason == "SL":
        px = stop0 - side * P * 0.0002
        roe = lev * (side * (px / P - 1) - RT)
        mae_stop = max(mae_stop, 1.0 + 0.0002 * P / dist)
    elif reason == "LOCK":
        roe = lock_roe + 0.004
        px = P * (1 + side * (roe / lev + RT))
        need = ((lock_roe + GAP) / lev + RT) * P / dist          # the best move that armed this lock, in R
        mfe_r = max(mfe_r, need + 0.05)
    elif reason == "LIQ":
        roe, px = -1.0, liq
        mae_stop = max(mae_stop, (P - liq) * side / dist)
    else:                                                        # TP / TIME (the reel) at the given ROE
        px = P * (1 + side * (roe / lev + RT))
    pnl = roe * margin
    wallet_after = wallet + pnl
    mfe_r = max(mfe_r, max(0.0, side * (px - P) / dist))
    mae_px = P - side * mae_stop * dist
    mfe_px = P + side * mfe_r * dist
    rec = TradeRecord(
        strategy_id=strategy, symbol=symbol, timeframe=tf, side=side, signal_ts=entry - 1, entry_time=entry,
        entry_price=P, exit_time=exit_t, exit_price=px, exit_reason=reason, qty=qty, leverage=lev, tier=tier,
        margin=margin, stop_price=stop0 if reason != "LOCK" else P * (1 + side * (lock_roe / lev + RT)),
        tp_price=float("nan"), liq_price=liq, fees=qty * P * 0.001, funding=0.0, pnl=pnl, roe=roe,
        price_move=side * (px / P - 1), mae_price=mae_px, mfe_price=mfe_px, equity_after=wallet_after, score=0.0,
        context={}, strategy_style="", stop_initial=stop0, lock_roe=lock_roe if reason == "LOCK" else None)
    return rec, wallet_after


def _outcome(rng, p_win, lev, house=True):
    """(reason, lock_roe, roe, mae_stop, mfe_r) of one trade."""
    if rng.random() < p_win:
        mae = min(0.97, rng.betavariate(1.2, 2.6))
        if not house:
            return ("TP" if rng.random() < 0.8 else "TIME"), None, 0.04 + rng.random() * 0.3, mae, 0.0
        k = min(7, int(rng.expovariate(0.9)))
        return "LOCK", round(FIRST_LOCK + STEP * k, 4), None, mae, 0.0
    if rng.random() < 0.015:
        return "LIQ", None, None, 1.2, rng.random() * 0.5
    trig = ((FIRST_LOCK + GAP) / lev + RT) / 0.006 if house else 1.6
    if not house and rng.random() < 0.15:
        return "TIME", None, -0.05 - rng.random() * 0.2, 0.6 + rng.random() * 0.35, rng.random() * 0.8
    return "SL", None, None, 1.0, rng.random() * trig * 0.95


def build(path: str, days: int = 30, seed: int = 11, start: int | None = None, hours_into_last: int = 20,
          ds_defs: int = 6, open_positions: int = 24) -> dict:
    rng = random.Random(seed)
    start = kst(2026, 10, 5, 0, 30) if start is None else int(start)
    now = start + (days - 1) * DAY + hours_into_last * HOUR
    st = Store3(path)
    core = list(STRATEGY_KO)
    cluster = {s: i % 6 for i, s in enumerate(core)}
    skill = {s: rng.gauss(0, 1) for s in core}                  # some strategies better than others
    accounts = []                                                # (aid, strategy, tf, kind, house)
    for tf in CORE_TFS:
        accounts += [(f"{s}@{tf}", s, tf, "strategy", True) for s in core]
    for tf in CORE_TFS:
        accounts += [(f"RANDOM_{k}@{tf}", f"RANDOM_{k}", tf, "random", True) for k in (1, 2, 3)]
    for name, fam, tfs in DS200_DEFS[:ds_defs]:
        accounts += [(f"{name}@{tf}", name, tf, "ds200", True) for tf in tfs]
    accounts.append((f"{REEL_NAME}@5m", REEL_NAME, "5m", "reel", False))
    accounts += [(f"RANDOM_{k}@5m", f"RANDOM_{k}", "5m", "random", False) for k in (1, 2, 3)]
    for aid, s, tf, kind, house in accounts:
        group = {"strategy": "core", "random": "flip", "ds200": "ds200", "reel": "reel"}[kind]
        st.add_account(aid, s, tf, kind, start, "paper-v4", None,
                       {"group": group, "family": None, "exits": "house" if house else "reel"})
    st.put_state("run", start, {"taker_fee": 0.0005, "initial_equity": INITIAL, "settings": "paper-v4"})
    st.add_run(start, {"commit": "anasyn-fixture", "changes": []})
    # the days' moods: a market factor and one per cluster
    mood = [[rng.gauss(0, 1) for _c in range(6)] for _d in range(days)]
    market = [rng.gauss(0, 0.8) for _d in range(days)]
    events = {}                                                  # (cluster, day) -> [(time, symbol, side)]
    for c in range(6):
        for d in range(days):
            events[(c, d)] = [(start + d * DAY + rng.randrange(0, DAY - 4 * HOUR), rng.choice(SYMS), rng.choice((1, -1)))
                              for _ in range(3)]
    n_tr = 0
    engines = {}
    opened = 0
    for aid, s, tf, kind, house in accounts:
        bar = TF_MS[tf]
        wallet = INITIAL
        t = start + rng.randrange(0, 2 * bar)
        busted = False
        while t < now - bar and not busted:
            gap = rng.expovariate(PER_DAY[tf] / DAY)
            t = (int(t + gap) // bar) * bar
            if t < start:                                        # a start off the bar grid: the first bar after it
                t += bar
            if t >= now - bar:
                break
            d = (t - start) // DAY
            if d >= days:
                break
            sym, side = rng.choice(SYMS), rng.choice((1, -1))
            if kind == "strategy" and rng.random() < 0.45:     # a cluster entry: same coin, side, about the same bar
                et, sym, side = rng.choice(events[(cluster[s], d)])
                t = max(t, (et // bar) * bar, start)
            if not house:
                side = 1                                         # the reel and its flips: long only
            hold = rng.randint(*HOLD_BARS[tf]) * bar
            exit_t = t + hold
            if exit_t >= now:
                break
            if kind == "strategy":
                p = 0.6 + 0.07 * skill[s] + 0.2 * math.tanh(mood[d][cluster[s]] + 0.6 * market[d])
            elif kind == "ds200":
                p = 0.58 + 0.15 * math.tanh(market[d])
            elif kind == "reel":
                p = 0.5 + 0.1 * math.tanh(market[d])
            else:
                p = 0.55 + 0.1 * math.tanh(0.5 * market[d] * side)
            lev = rng.choice((20, 30, 30, 40, 50)) if house else 20
            reason, lock, roe, mae, mfe = _outcome(rng, p, lev, house)
            rec, wallet = record(s, tf, sym, side, t, exit_t, reason, lev, wallet, lock_roe=lock, roe=roe,
                                 mae_stop=mae, mfe_r=mfe, tier="best" if lev >= 40 else "normal")
            st.trade(aid, rec)
            n_tr += 1
            busted = wallet < 10.0
            t = exit_t
        pos = None
        if opened < open_positions and not busted and kind in ("strategy", "random") and rng.random() < 0.3:
            opened += 1
            sym = rng.choice(SYMS)
            P = BASE[sym]
            side = rng.choice((1, -1))
            lev = 30
            pos = {"symbol": sym, "side": side, "qty": wallet * 0.3 * lev / P, "entry_price": P,
                   "entry_time": int(now - rng.randrange(1, 6) * bar), "leverage": lev, "tier": "normal",
                   "margin": wallet * 0.3, "margin_initial": wallet * 0.3, "stop_price": P * (1 - side * 0.006),
                   "tp_price": None, "liq_price": P * (1 - side * 0.03), "entry_fee": 1.0, "funding_paid": 0.0,
                   "mae_price": P, "mfe_price": P, "stop_initial": P * (1 - side * 0.006), "lock_roe": None,
                   "signal": {"meta": {}}}
        engines[aid] = {"wallet": wallet, "peak_equity": max(INITIAL, wallet), "max_drawdown": 0.0, "halted": busted,
                        "halt_reason": "", "bust": busted, "warned": [], "last_mark": {}, "position": pos,
                        "pending": [], "n_trades": 0}
    st.put_state("accounts", now, {"last_ts": now, "engines": engines})
    st.put_state("heartbeat", now, {"steps": 1, "last_step": now})
    st.commit()
    st.close()
    return {"start": start, "now": now, "trades": n_tr, "accounts": len(accounts), "open": opened, "days": days}


def blank(path: str, start: int, accounts: list, initial: float = INITIAL) -> Store3:
    """An empty paper3.db with ``accounts`` [(aid, kind)] created at ``start`` (hand-built test cases add trades)."""
    st = Store3(path)
    for aid, kind in accounts:
        s, tf = aid.split("@")
        st.add_account(aid, s, tf, kind, start, "paper-v4", None, {})
    st.put_state("run", start, {"taker_fee": 0.0005, "initial_equity": initial})
    st.commit()
    return st


def trade(st: Store3, aid: str, entry: int, exit_t: int, pnl: float, *, symbol="BTCUSDT", side=1, reason=None,
          lock_roe=None, margin=1000.0, roe=None, equity_after=None, entry_price=100.0, stop_initial=99.0,
          mae_price=None, mfe_price=None, leverage=30) -> None:
    """A hand-made closed trade: every field the views read, the rest plain."""
    s, tf = aid.split("@")
    reason = reason or ("LOCK" if pnl > 0 else "SL")
    rec = TradeRecord(
        strategy_id=s, symbol=symbol, timeframe=tf, side=side, signal_ts=entry - 1, entry_time=entry,
        entry_price=entry_price, exit_time=exit_t, exit_price=entry_price, exit_reason=reason, qty=1.0,
        leverage=leverage, tier="normal", margin=margin, stop_price=stop_initial, tp_price=float("nan"),
        liq_price=entry_price * 0.9, fees=0.1, funding=0.0, pnl=pnl, roe=pnl / margin if roe is None else roe,
        price_move=0.0, mae_price=entry_price if mae_price is None else mae_price,
        mfe_price=entry_price if mfe_price is None else mfe_price,
        equity_after=(INITIAL + pnl) if equity_after is None else equity_after, score=0.0, context={},
        stop_initial=stop_initial, lock_roe=lock_roe)
    st.trade(aid, rec)


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True)
