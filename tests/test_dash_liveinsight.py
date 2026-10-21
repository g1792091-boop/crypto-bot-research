"""실거래 › 규칙 점검 · 목표 · 위험 · 봇 상태 · 그룹, and 비용's 체결 비교 (dash/more/liveinsight.py, livebots.py costs; screens
livebots-judge / goal / risk / health.js, livebots-cost.js, livebots-rank.js groupBlock) on a hand-made 규칙봇 15 world.

The world (``world15``) is made with the bots' own writers (Store3 for live-ac.db and the rule bot's paper3.db, ExecStore
for the executors, livecheck.open_out / livemissed for livecheck.db), times as tests/livebots_world.py (T0 = 2026-10-19
09:00 KST, NOW = T0 + 10 h). The A+C config ran until T0 + 10 min (its last signal row), the 15 config started at START =
T0 + 30 min (``combo_run``), its first signal T0 + 1 h. Settings: V39_ALL@1h and S3_CMO_SANDWICH@30m (group A),
F3_BOS@30m and F9_FVG@1h (group B, no_chase). Prices are 100-ish so every number can be checked by hand:

    o0, o1, o2   the old config's trades (25 days, 20 h and 10 h before T0)
    t_a  BTC long  V39 (A)  LOCK +10.5 %       t_b  BCH short F3 (B) LOCK +12 %       t_c  LTC long F9 (B) SL -50 %
    R1   ETH long  S3 (A)   REV at 20 min; held: the bars fall through the -50 % net stop       -> lost
    R2   SOL short V39 (A)  REV at 15 min; held: the price falls to +12 % (lock 10 %), back up    -> won at the 10 % lock
    R3   DOGE long S3 (A)   REV; held: flat bars to now                                           -> open
    R4   LTC short F3 (B)   REV; no LTC bar at all                                                -> no_data
    chase c1 BTC long F3 (replayed: falls through the 40x stop -> lost), c2 ETH short F9 (the watcher's row: won),
          c3 DOGE short F3 (no bar at its minute -> no_data), c4 BCH long F9 (the watcher could not rebuild it)
    COMBOFLIP@mix since START: 2 wins of 4; bybit follows t_a (with fills), R1, t_c, R2; MEXC follows t_a, t_b and is late.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot.executor import ExecStore  # noqa: E402
from paperbot.ladder import roe_price  # noqa: E402
from paperbot.models import Position, Signal, SignalOutcome, TradeRecord  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import liveinsight as I  # noqa: E402

SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
H, MIN, DAY, T0, NOW = W.H, W.MIN, W.DAY, W.T0, W.NOW
START = T0 + 30 * MIN
TAKER, SLIP = 0.0005, 0.0002
RT = 2 * (TAKER + SLIP)
LADDER2 = {"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03}
MEMBERS15 = [{"strategy": "V39_ALL", "tf": "1h"}, {"strategy": "S3_CMO_SANDWICH", "tf": "30m"},
             {"strategy": "F3_BOS", "tf": "30m", "no_chase": True}, {"strategy": "F9_FVG", "tf": "1h", "no_chase": True}]
LABELS = ["V39_ALL@1h", "S3_CMO_SANDWICH@30m", "F3_BOS@30m", "F9_FVG@1h"]
CONFIG15 = {"name": "규칙봇 15", "initial_equity": 1000, "leverage": {"BTCUSDT": 40, "default": 30}, "margin": 0.3, "max_loss_frac": 0.35,
            "stop": {"mode": "roe", "roe": 0.5, "net": True}, "ladder": LADDER2, "rank": ["order"], "flip_twin": True,
            "early_exit": "own", "early_exit_until_lock": True, "no_weekend": True, "macro_blackout_min": 30, "us_open_pause_min": 30,
            "members": MEMBERS15}
OLD = "N03_ADX_GC@15m#2~abc123"
ACC, FLIP = W.ACCOUNT, W.FLIP
MARGIN = 300.0
CHASE_WHY = "추격 진입 막기: 롱인데 24시간 고점 쪽(95% 위치)"


def lev_of(sym):
    return 40 if sym == "BTCUSDT" else 30


def entry_of(side, ref=100.0):
    return ref * (1 + side * SLIP)


def stop_of(sym, side, ref=100.0):
    return roe_price(side, ref, lev_of(sym), -0.5, RT)


def booked(side, entry, exit_px, lev):
    """paperbot/engine.py _close: gross - both taker fees, over the margin (no funding)."""
    return lev * (side * (exit_px / entry - 1) - TAKER * (1 + exit_px / entry))


# ================================================================ the world
def _rec(name, sym, side, t, strat, tf, reason, roe=None, rev_open=None, hold=40 * MIN, eq=0.0):
    lev, e = lev_of(sym), entry_of(side)
    qty = MARGIN * lev / e
    if rev_open is not None:                           # a REV close: the minute's open, slippage against
        x = rev_open * (1 - side * SLIP)
        roe = booked(side, e, x, lev)
    else:
        x = roe_price(side, e, lev, roe, RT)
    pnl = roe * MARGIN
    return TradeRecord(strategy_id=strat, symbol=sym, timeframe=tf, side=side, signal_ts=t - 1, entry_time=t, entry_price=e,
                       exit_time=t + hold, exit_price=x, exit_reason=reason, qty=qty, leverage=lev, tier="base", margin=MARGIN,
                       stop_price=stop_of(sym, side), tp_price=0.0, liq_price=e * (1 - side * 0.03), fees=TAKER * qty * (e + x),
                       funding=0.0, pnl=pnl, roe=roe, price_move=side * (x / e - 1), mae_price=e, mfe_price=e, equity_after=eq + pnl,
                       score=3.0, stop_initial=stop_of(sym, side), lock_roe=0.10 if reason == "LOCK" else None)


# (name, coin, side, entry, strategy, tf, label, reason, roe, REV open price, hold)
PAPER15 = [
    ("o0", "SOLUSDT", 1, T0 - 25 * DAY, "N03_ADX_GC", "15m", OLD, "LOCK", 40 / MARGIN, None, 40 * MIN),
    ("o1", "ETHUSDT", 1, T0 - 20 * H, "N03_ADX_GC", "15m", OLD, "LOCK", 40 / MARGIN, None, 40 * MIN),
    ("o2", "SOLUSDT", 1, T0 - 10 * H, "N03_ADX_GC", "15m", OLD, "SL", -160 / MARGIN, None, 40 * MIN),
    ("t_a", "BTCUSDT", 1, T0 + 1 * H, "V39_ALL", "1h", "V39_ALL@1h", "LOCK", 0.105, None, 40 * MIN),
    ("R1", "ETHUSDT", 1, T0 + 2 * H, "S3_CMO_SANDWICH", "30m", "S3_CMO_SANDWICH@30m", "REV", None, 99.5, 20 * MIN),
    ("t_b", "BCHUSDT", -1, T0 + 3 * H, "F3_BOS", "30m", "F3_BOS@30m", "LOCK", 0.12, None, 40 * MIN),
    ("t_c", "LTCUSDT", 1, T0 + 4 * H, "F9_FVG", "1h", "F9_FVG@1h", "SL", -0.5, None, 40 * MIN),
    ("R2", "SOLUSDT", -1, T0 + 5 * H, "V39_ALL", "1h", "V39_ALL@1h", "REV", None, 100.3, 15 * MIN),
    ("R3", "DOGEUSDT", 1, T0 + 6 * H, "S3_CMO_SANDWICH", "30m", "S3_CMO_SANDWICH@30m", "REV", None, 99.8, 10 * MIN),
    ("R4", "LTCUSDT", -1, T0 + 7 * H, "F3_BOS", "30m", "F3_BOS@30m", "REV", None, 100.1, 5 * MIN),
]
FLIP15 = [(T0 - 20 * H, 1, 0.1, "LOCK", OLD), (T0 + 1 * H, -1, 0.1, "LOCK", "V39_ALL@1h"), (T0 + 2 * H, -1, -0.5, "SL", "S3_CMO_SANDWICH@30m"),
          (T0 + 3 * H, 1, 0.1, "LOCK", "F3_BOS@30m"), (T0 + 5 * H, 1, -0.5, "SL", "V39_ALL@1h")]
POS_T = NOW - 30 * MIN


def _sig(sym, tf, strat, side, t, label):
    order = LABELS.index(label) + 1 if label in LABELS else 2
    return Signal(ts=t - 1, symbol=sym, timeframe=tf, strategy_id=strat, side=side, stop_price=0.0, tier="best", score=3.0, atr=1.0,
                  meta={"member": label, "member_order": order, "stop_rule": "ROE -50% net at 30x", "source": "rule", "ref_price": 100.0})


def _siglog(s, t, tf, label, sym, side, status, why=None, strat=None):
    d = {"source": "rule", "strategy": strat or label.split("@")[0]}
    if why:
        d["why"] = why
    s.log_signals([{"bar_close": t, "timeframe": tf, "strategy": label, "symbol": sym, "side": side, "atr": 1.0, "ref_price": 100.0,
                    "ref_time": t, "delay_ms": 900, "status": status, "data": d}])


def paper15(path):
    s = Store3(path)
    s.add_account(ACC, "combo", "mix", "combo", T0 - 30 * DAY, "combo-v2")
    s.add_account(FLIP, "combo", "mix", "combo_flip", T0 - 30 * DAY, "combo-v2")
    eq, recs = 1000.0, {}
    for name, sym, side, t, strat, tf, label, reason, roe, rev, hold in PAPER15:
        r = _rec(name, sym, side, t, strat, tf, reason, roe, rev, hold, eq)
        eq = r.equity_after
        recs[name] = r
        s.trade(ACC, r)
        s.outcome(ACC, SignalOutcome(_sig(sym, tf, strat, side, t, label), "ENTERED", "ok", t, {"fill": r.entry_price}))
        _siglog(s, t, tf, label, sym, side, "SUBMITTED", strat=strat)
    feq = 1000.0
    for t, side, roe, reason, label in FLIP15:
        strat, tf = label.split("@")[0], label.split("@")[1].split("#")[0]
        r = _rec("f", "ETHUSDT", side, t, strat, tf, reason, roe, None, 40 * MIN, feq)
        feq = r.equity_after
        s.trade(FLIP, r)
        s.outcome(FLIP, SignalOutcome(_sig("ETHUSDT", tf, strat, side, t, label), "ENTERED", "ok", t, {}))
    # the old config's last signal row (its WAITING break dropped at the switch), then the 15 config's other rows
    _siglog(s, T0 + 10 * MIN, "15m", OLD, "DOGEUSDT", 1, "FILTERED", "설정이 바뀌어 기다리던 돌파 신호를 버림", "N03_ADX_GC")
    _siglog(s, T0 + 90 * MIN, "30m", "F3_BOS@30m", "BTCUSDT", 1, "FILTERED", CHASE_WHY)                      # c1
    _siglog(s, T0 + 8 * H, "1h", "F9_FVG@1h", "ETHUSDT", -1, "FILTERED", "추격 진입 막기: 숏인데 24시간 저점 쪽(5% 위치)")  # c2
    _siglog(s, T0 + 5 * H + 30 * MIN, "30m", "F3_BOS@30m", "DOGEUSDT", -1, "FILTERED", "추격 진입 막기: 숏인데 7일 범위 아래 20% 안(12% 위치)")
    _siglog(s, T0 + 9 * H, "1h", "F9_FVG@1h", "BCHUSDT", 1, "FILTERED", CHASE_WHY)                            # c4
    _siglog(s, T0 + 3 * H, "1h", "V39_ALL@1h", "ETHUSDT", 1, "FILTERED", "경제 발표 앞뒤 30분: 소비자물가(CPI) 2026-10-19 12:30")
    psig = _sig("BCHUSDT", "30m", "F3_BOS", 1, POS_T, "F3_BOS@30m")
    e = entry_of(1)
    pos = Position(signal=psig, symbol="BCHUSDT", side=1, qty=MARGIN * 30 / e, entry_price=e, entry_time=POS_T, leverage=30, tier="base",
                   margin=MARGIN, margin_initial=MARGIN, stop_price=stop_of("BCHUSDT", 1), tp_price=0.0, liq_price=96.9,
                   entry_fee=TAKER * MARGIN * 30, funding_paid=0.0, stop_initial=stop_of("BCHUSDT", 1), lock_roe=None)
    s.outcome(ACC, SignalOutcome(psig, "ENTERED", "ok", POS_T, {"fill": e}))
    from dataclasses import asdict
    engines = {ACC: {"wallet": eq, "peak_equity": 1080.0, "max_drawdown": 0.3, "halted": False, "halt_reason": "", "bust": False, "warned": [],
                     "last_mark": {"BCHUSDT": 100.5}, "position": asdict(pos), "pending": [], "n_trades": len(PAPER15)},
               FLIP: {"wallet": feq, "peak_equity": 1010.0, "max_drawdown": 0.3, "halted": False, "halt_reason": "", "bust": False, "warned": [],
                      "last_mark": {}, "position": None, "pending": [], "n_trades": len(FLIP15)}}
    s.put_state("accounts", NOW - 2 * MIN, {"last_ts": NOW - 2 * MIN, "engines": engines})
    s.put_state("heartbeat", NOW - 5_000, {"last_step": NOW - 2 * MIN, "queue": 1})
    s.put_state("combo_run", START, {"version": "combo-v2", "brackets": "example", "taker_fee": TAKER, "members": [], "config": CONFIG15})
    s.put_state("combo", NOW - 2 * MIN, {"cursor": 1, "queue": [], "breaks": [], "counts": {}, "version": "combo-v2", "members": LABELS})
    s.close()
    return recs


def _ohlc(closes, first_open):
    """[(o, h, l, c)] from closes: each bar opens at the close before it (the first at ``first_open``), 0.02 above / below
    its body."""
    out, prev = [], first_open
    for c in closes:
        out.append((prev, max(prev, c) + 0.02, min(prev, c) - 0.02, c))
        prev = c
    return out


def bars15(path):
    s = Store3(path)
    rows = []

    def put(sym, t0, ohlc):
        for i, (o, hi, lo, c) in enumerate(ohlc):
            ts = t0 + i * MIN
            rows.append({"ts": ts, "symbol": sym, "open": o, "high": hi, "low": lo, "close": c, "volume": 1.0, "close_time": ts + MIN - 1,
                         "processed_at": ts + MIN})

    # R1 ETH: the entry bar, drifts to 99.5 by its REV minute, then on down through the stop (98.47) at minute 54
    put("ETHUSDT", T0 + 2 * H, [(100.0, 100.05, 99.90, 99.95)]
        + _ohlc([99.95 - (i / 19) * 0.45 for i in range(1, 20)] + [99.5 - (i - 20) * 0.03 for i in range(20, 61)], 99.95))
    # R2 SOL short: up to 100.3 (REV), down to 99.45 (best +12.3 %: lock 10 %), then up through the lock at minute 32
    sol = [(100.0, 100.10, 99.95, 100.05)] + _ohlc([100.05 + (i / 14) * 0.25 for i in range(1, 15)]
                                                     + [100.3 - (i - 15) * (0.85 / 15) for i in range(15, 31)], 100.05)
    sol += [(99.45, 99.48, 99.42, 99.47), (99.47, 99.55, 99.46, 99.53), (99.53, 99.6, 99.5, 99.58)]
    put("SOLUSDT", T0 + 5 * H, sol)
    # R3 DOGE: flat from its entry to now (neither the stop nor the first lock)
    put("DOGEUSDT", T0 + 6 * H, [(100.0, 100.05, 99.95, 100.0)] * ((NOW - MIN - (T0 + 6 * H)) // MIN + 1))
    # chase c1 BTC long at 40x: down 0.05 a minute through its stop (98.89) at minute 22; and fresh bars just before now
    put("BTCUSDT", T0 + 90 * MIN, [(100.0, 100.05, 99.95, 100.0)] + _ohlc([100.0 - i * 0.05 for i in range(1, 31)], 100.0))
    put("BTCUSDT", NOW - 5 * MIN, [(100.0, 100.05, 99.95, 100.0)] * 5)
    s.live_bars(rows)
    s.log_signals([{"bar_close": NOW - 20 * MIN, "timeframe": "30m", "strategy": "V39_ALL", "symbol": "ETHUSDT", "side": 1, "atr": 1.0,
                    "ref_price": 100.0, "ref_time": NOW - 20 * MIN + 900, "delay_ms": 900, "status": "SUBMITTED", "data": {}}])
    s.close()


def _k(sym, t):
    return f"{ACC}|{sym}|{t}"


def execs15(p, recs):
    st = ExecStore(p["bybit_db"], lock=False)
    st.put_state("meta", T0 - 30 * DAY, {"mode": "mainnet", "account": ACC, "since": T0 - 30 * DAY, "exchange": "bybit", "live_since": T0 - 30 * DAY})
    a = recs["t_a"]
    W._live(st, _k("BTCUSDT", a.entry_time), "BTCUSDT", 1, a.entry_time, 3.15, 0.0332, entry_price=100.05, qty=0.3, lev=40)
    st.fills(_k("BTCUSDT", a.entry_time), [
        {"symbol": "BTCUSDT", "id": 1, "orderId": 11, "side": "BUY", "qty": "0.3", "price": "100.05", "commission": "0.0165",
         "commissionAsset": "USDT", "realizedPnl": "0", "time": a.entry_time + 20_000},
        {"symbol": "BTCUSDT", "id": 2, "orderId": 12, "side": "SELL", "qty": "0.3", "price": "100.40", "commission": "0.0167",
         "commissionAsset": "USDT", "realizedPnl": "0.105", "time": a.entry_time + 41 * MIN}])
    for name, sym, pnl, ep in (("R1", "ETHUSDT", -5.8, 100.03), ("t_c", "LTCUSDT", -15.2, 100.03), ("R2", "SOLUSDT", -4.0, 99.97)):
        r = recs[name]
        W._live(st, _k(sym, r.entry_time), sym, r.side, r.entry_time, pnl, 0.03, entry_price=ep, qty=round(r.qty * 0.1, 6), lev=30)
    for ts, eq_, tr in ((T0 - 25 * DAY, 100.0, 0.0), (T0 - 18 * DAY, 105.0, 0.0), (T0 - 3 * DAY, 160.0, 50.0), (T0 + 9 * H, 140.0, 50.0)):
        st.equity(ts, eq_, eq_, tr)
    open_t = {"key": _k("BCHUSDT", POS_T), "symbol": "BCHUSDT", "side": 1, "qty": 9.0, "leverage": 30, "stop": 98.48, "stop_initial": 98.48,
              "status": "open", "entry_ts": POS_T + 15_000, "entry_price": 100.03, "entry_time": POS_T, "paper_entry": entry_of(1), "mode": "mainnet"}
    st.trade_open(open_t)
    st.put_state("bot", NOW - 4_000, {"trade": open_t, "done": [], "loops": 9000, "mode": "mainnet", "account": ACC,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 2, "last_equity": 140.0, "trades": 4}})
    st.close()
    st = ExecStore(p["mexc_db"], lock=False)
    st.put_state("meta", T0 - 2 * DAY, {"mode": "mainnet", "account": ACC, "since": T0 - 2 * DAY, "exchange": "mexc", "live_since": T0 - 2 * DAY})
    for name, sym, pnl, ep in (("t_a", "BTCUSDT", 3.0, 100.04), ("t_b", "BCHUSDT", 3.5, 99.97)):
        r = recs[name]
        W._live(st, _k(sym, r.entry_time), sym, r.side, r.entry_time, pnl, 0.04, entry_price=ep, qty=round(r.qty * 0.1, 6), lev=r.leverage)
    st.equity(T0 - 2 * DAY, 50.0, 50.0, 0.0)
    st.equity(T0 + 9 * H, 52.0, 52.0, 0.0)
    st.put_state("bot", NOW - 10 * MIN, {"trade": None, "done": [], "loops": 100, "mode": "mainnet", "account": ACC,
                                         "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": 52.0, "trades": 2}})
    st.close()


def check15(path):
    from paperbot import livecheck as LC
    from paperbot import livemissed as LM
    conn = LC.open_out(path)
    LM._schema(conn)

    def row(key, t, member, sym, side, state, **kw):
        base = {c: None for c in LM.COLS}
        base.update(key=key, t=t, step_ts=t, member=member, strategy=member.split("@")[0], tf=member.split("@")[1], symbol=sym, side=side,
                    why_kind="chase", why="추격 진입 막기", state=state, first_ts=t, updated_ts=NOW, signal="{}", grp="research", sims=1)
        base.update(kw)
        LM._upsert(conn, base)

    row(f"F9_FVG@1h|ETHUSDT|{T0 + 8 * H}", T0 + 8 * H, "F9_FVG@1h", "ETHUSDT", -1, "closed", entry_ts=T0 + 8 * H, entry_price=99.98,
        exit_ts=T0 + 8 * H + 50 * MIN, exit_price=99.5, reason="LOCK", roe_net=0.106, pnl=31.8, best_roe=0.13, margin=MARGIN,
        data=json.dumps({"lock": 0.10}))
    row(f"F9_FVG@1h|BCHUSDT|{T0 + 9 * H}", T0 + 9 * H, "F9_FVG@1h", "BCHUSDT", 1, "rebuild_failed",
        data=json.dumps({"why": "설정의 매매법을 찾지 못했어요"}, ensure_ascii=False))
    conn.execute("INSERT INTO seen (ts, paper_hb, paper_step, rule_bar, data) VALUES (?, ?, ?, ?, ?)", (NOW - 30_000, None, None, None, "{}"))
    conn.commit()
    conn.close()
    return path


def world15(folder):
    p = W.build_world(folder)
    for k in ("paper", "bybit_db", "mexc_db"):
        os.remove(p[k])
    recs = paper15(p["paper"])
    execs15(p, recs)
    kill = os.path.join(folder, "STOP")
    W.config(p["bybit_config"], p["bybit_db"], p["paper"], "bybit", 0.85, kill, n=0)
    W.config(p["mexc_config"], p["mexc_db"], p["paper"], "mexc", 0.85, kill, n=0)
    rule = os.path.join(folder, "rule-paper3.db")
    bars15(rule)
    check = check15(os.path.join(folder, "livecheck.db"))
    more = {**L.paths_more({}), "rule_db": rule, "check_db": check, "combo_config": "/nonexistent/combo.json"}
    return {"p": p, "more": more, "recs": recs, "rule": rule, "check": check, "kill": kill}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    I._holds.clear()
    yield
    L._cache.clear()
    I._holds.clear()


@pytest.fixture(scope="module")
def w15(tmp_path_factory):
    return world15(str(tmp_path_factory.mktemp("insight") / "w"))


def by_id(rows, key="id"):
    return {r[key]: r for r in rows}


# ================================================================ since when (config_start)
def test_the_start_is_the_restart_between_the_old_configs_last_signal_and_the_new_ones_first(w15):
    combo = L.read_combo(w15["p"]["paper"], w15["more"]["combo_config"])
    members = I.run_members(w15["p"]["paper"], combo)
    assert [m["label"] for m in members] == LABELS and [m["group"] for m in members] == ["A", "A", "B", "B"]
    st = I.config_start(w15["p"]["paper"], combo, members, NOW)
    assert st["ms"] == START and st["how"] == "run" and st["sure"] is True and st["name"] == "규칙봇 15" and st["run_ms"] == START


def _db(tmp_path, name, rows, run_ms=START, cfg=CONFIG15, labels=LABELS, signal_log=True):
    path = str(tmp_path / name)
    s = Store3(path)
    s.add_account(ACC, "combo", "mix", "combo", T0 - DAY, "combo-v2")
    for t, label in rows:
        _siglog(s, t, "1h", label, "ETHUSDT", 1, "SUBMITTED")
    s.put_state("combo_run", run_ms, {"taker_fee": TAKER, "config": cfg})
    if labels:
        s.put_state("combo", NOW, {"members": labels})
    s.close()
    if not signal_log:
        c = sqlite3.connect(path)
        c.execute("DROP TABLE signal_log")
        c.commit()
        c.close()
    return path


def _start(path):
    combo = L.read_combo(path, "/nonexistent/combo.json")
    return I.config_start(path, combo, I.run_members(path, combo), NOW)


def test_the_start_in_every_other_case(tmp_path):
    # restarted after its first signal: the first signal of this config is the start
    s = _start(_db(tmp_path, "a.db", [(T0, OLD), (T0 + H, "V39_ALL@1h"), (T0 + 2 * H, "F3_BOS@30m")], run_ms=T0 + 3 * H))
    assert (s["ms"], s["how"], s["sure"]) == (T0 + H, "first_signal", True)
    # a file that only ever ran this config: from the account's creation
    s = _start(_db(tmp_path, "b.db", [(T0 + H, "V39_ALL@1h")], run_ms=T0 + 3 * H))
    assert (s["ms"], s["how"], s["sure"]) == (T0 - DAY, "whole", True)
    # started, no signal of its own yet
    s = _start(_db(tmp_path, "c.db", [(T0, OLD)], run_ms=T0 + H))
    assert (s["ms"], s["how"], s["sure"]) == (T0 + H, "run", True)
    # no signal log to tell: only the last start, not sure (trades are then counted by their setting)
    s = _start(_db(tmp_path, "d.db", [], run_ms=T0 + H, signal_log=False))
    assert (s["ms"], s["how"], s["sure"]) == (T0 + H, "run_only", False) and "지금 설정 매매법의 거래만" in s["how_ko"]
    # labels the page cannot rebuild (a research config without the bot's own list): unknown, said so
    s = _start(_db(tmp_path, "e.db", [(T0, OLD)], cfg=W.CONFIG, labels=None))
    assert s["ms"] is None and s["sure"] is False and "매매법 이름" in s["how_ko"]
    # the newest row is the old config's although this one is said to run: never a guess
    s = _start(_db(tmp_path, "f.db", [(T0 + 2 * H, OLD)], run_ms=T0 + H))
    assert s["ms"] is None and s["sure"] is False


def test_trades_are_grouped_by_their_setting_and_counted_from_the_start(w15):
    cx = I.context(w15["p"], NOW, w15["more"])
    trades = cx["acc"]["trades"]
    g = {t["symbol"] + str(t["entry_time"]): I.group_of(t, cx["meta"], cx["members"], cx["start"]) for t in trades}
    names = {r[0]: g[r[1] + str(r[3])] for r in PAPER15}
    assert names == {"o0": "old", "o1": "old", "o2": "old", "t_a": "A", "R1": "A", "t_b": "B", "t_c": "B", "R2": "A", "R3": "A", "R4": "B"}
    since = I.since_start(trades, cx["start"], cx["meta"], cx["members"])
    assert len(since) == 7 and all(t["entry_time"] >= START for t in since)
    # without a sure start: the same seven, by their settings (the ENTERED outcomes' labels)
    assert len(I.since_start(trades, {"ms": None, "sure": False}, cx["meta"], cx["members"])) == 7


# ================================================================ small statistics
def test_wilson_interval_closed_forms_and_symmetry():
    z = I.Z90
    assert I.wilson(0, 0) is None
    lo, hi = I.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(z * z / (10 + z * z))                 # x = 0: upper = z^2 / (n + z^2)
    lo, hi = I.wilson(10, 10)
    assert hi == 1.0 and lo == pytest.approx(10 / (10 + z * z))
    a, b = I.wilson(7, 20), I.wilson(13, 20)
    assert a[0] == pytest.approx(1 - b[1]) and a[1] == pytest.approx(1 - b[0])      # symmetric
    lo, hi = I.wilson(86, 100)
    assert lo < 0.86 < hi and 0.79 < lo < 0.81 and 0.90 < hi < 0.92
    assert (I.wilson(860, 1000)[1] - I.wilson(860, 1000)[0]) < (hi - lo)              # narrows with n


def test_next_losses_table_is_compounded():
    t = I.next_losses(0.3, 0.5, 200.0)
    assert [r["n"] for r in t] == [1, 2, 3, 4]
    assert [round(r["left"], 6) for r in t] == [0.85, 0.7225, 0.614125, 0.522006]
    assert [round(r["lost"], 4) for r in t] == [0.15, 0.2775, 0.3859, 0.478]          # the start guide's -15 / -39 / -48 %
    assert t[2]["money_left"] == pytest.approx(200 * 0.85 ** 3)
    assert I.next_losses(None, 0.5, 100) == [] and I.next_losses(0.3, None, 100) == []
    assert I.next_losses(0.3, 0.5, None)[0]["money_left"] is None


def test_weekdays_and_the_month():
    mo = I.month_of(NOW)
    assert mo["label"] == "2026년 10월" and mo["days"] == 31
    assert mo["from_ms"] == T0 - 18 * DAY - 9 * H and mo["to_ms"] == T0 + 13 * DAY - 9 * H              # 10/01 .. 11/01 00:00 KST
    assert mo["days_left"] == pytest.approx((mo["to_ms"] - NOW) / DAY)
    assert I.weekday_days(T0, T0 + 5 * DAY) == pytest.approx(4 + 15 / 24)              # Monday 09:00 KST to Saturday 09:00 KST
    sat = T0 + 4 * DAY + 15 * H                                                         # Saturday 00:00 KST
    assert I.weekday_days(sat, sat + 2 * DAY) == 0.0 and I.weekday_days(None, NOW) == 0.0


# ================================================================ 규칙 점검: 빠른 손절
def test_rev_exits_held_instead_lost_won_open_and_no_data(w15):
    d = I.judge(w15["p"], NOW, w15["more"])
    rev = d["rev"]
    assert rev["state"] == "ok" and len(rev["rows"]) == 4
    rows = {r["symbol"]: r for r in rev["rows"]}
    r1, r2, r3, r4 = rows["ETHUSDT"], rows["SOLUSDT"], rows["DOGEUSDT"], rows["LTCUSDT"]
    # R1: through the -50 % net stop (booked with the trade's own fees: -0.4996)
    assert r1["cf"]["state"] == "lost" and r1["cf"]["exit"]["reason"] == "SL"
    x = stop_of("ETHUSDT", 1) * (1 - SLIP)
    assert r1["cf"]["roe"] == pytest.approx(booked(1, entry_of(1), x, 30), abs=1e-9) and r1["cf"]["roe"] == pytest.approx(-0.5, abs=0.001)
    assert r1["cf"]["exit"]["t"] == T0 + 2 * H + 54 * MIN + MIN - 1
    assert r1["delta_roe"] == pytest.approx(r1["roe"] - r1["cf"]["roe"]) and r1["delta_roe"] > 0.3          # the early exit saved
    assert r1["delta_pnl"] == pytest.approx(r1["delta_roe"] * MARGIN) and r1["group"] == "A"
    # R2: down to +12.3 % (lock 10 %, the two-part ladder), back up through the lock: won at 10.6 %
    lock_px = roe_price(-1, entry_of(-1), 30, 0.10, RT)
    assert r2["cf"]["state"] == "won" and r2["cf"]["exit"]["reason"] == "LOCK" and r2["cf"]["lock"] == pytest.approx(0.10)
    assert r2["cf"]["roe"] == pytest.approx(booked(-1, entry_of(-1), lock_px * (1 + SLIP), 30), abs=1e-9)
    assert r2["cf"]["roe"] == pytest.approx(0.1061, abs=0.0005) and r2["delta_roe"] < -0.2                 # it cost a win
    # R3 flat to now: undecided, its net ROE now; R4: no bar at all
    assert r3["cf"]["state"] == "open" and r3["delta_roe"] is None
    assert r3["cf"]["roe"] == pytest.approx(30 * (100.0 / entry_of(1) - 1 - RT))
    assert r4["cf"]["state"] == "no_data" and "1분봉" in r4["cf"]["why_ko"] and r4["group"] == "B"
    t = rev["totals"]
    assert (t["n"], t["lost"], t["won"], t["open"], t["unknown"], t["decided"]) == (4, 1, 1, 1, 1, 2)
    assert t["delta_roe"] == pytest.approx(r1["delta_roe"] + r2["delta_roe"]) and t["verdict"] == ("saved" if t["delta_roe"] > 0 else "cost")
    # bybit followed R1 and R2: the same points at its own margin (entry x qty / 30)
    b = t["live"]["bybit"]
    assert b["n"] == 2 and b["delta_pnl"] == pytest.approx(sum(r["delta_roe"] * r["live"]["bybit"]["margin"] for r in (r1, r2)))
    assert t["live"]["mexc"]["n"] == 0 and rev["small"] is True


def test_the_replay_is_the_engines_own_ladder_on_a_bar_path():
    """A synthetic path straight through livetape.rebuild: +12 % then +16 % (locks 10 %, 12 %), back to 12 %: won at the
    12 % lock; and the same entry falling through the net stop: lost at -50 %."""
    from paperbot.dash.more import livetape as T
    run = {"taker_fee": TAKER, "config": CONFIG15}
    e0 = T0 + 9 * H
    t = {"symbol": "ETHUSDT", "side": 1, "entry_price": 100.02, "entry_time": e0, "leverage": 30, "stop_initial": stop_of("ETHUSDT", 1),
         "liq_price": None, "qty": None, "margin": None, "fees": None, "exit_price": None, "exit_reason": "REV", "exit_time": e0 + MIN}
    rules = T.rules_of(t, run)
    px = lambda roe: roe_price(1, 100.02, 30, roe, RT)                                          # noqa: E731

    def bar(i, o, hi, lo, c):
        ts = e0 + i * MIN
        return {"ts": ts, "open": o, "high": hi, "low": lo, "close": c, "m_open": o, "m_high": hi, "m_low": lo, "close_time": ts + MIN - 1}

    up = [bar(0, 100.0, 100.05, 99.95, 100.02), bar(1, 100.02, px(0.12), 100.0, px(0.115)), bar(2, px(0.115), px(0.16), px(0.13), px(0.155)),
          bar(3, px(0.15), px(0.151), px(0.11), px(0.115))]
    rb = T.rebuild({**t, "exit_reason": "HOLD"}, up, rules, True, [], until=e0 + 3 * MIN)
    assert [round(k["lock"], 9) for k in rb["locks"]] == [0.10, 0.12] and rb["exit"]["reason"] == "LOCK"
    roe = I.booked_roe(t, rb["exit"]["price"], "LOCK", rules["taker_fee"])
    # booked above the lock's own net ROE: the lock charges slippage on both sides, the fill already paid the entry's
    assert roe == pytest.approx(booked(1, 100.02, px(0.12) * (1 - SLIP), 30)) and 0.12 < roe < 0.13
    down = [bar(0, 100.0, 100.05, 99.95, 100.0), bar(1, 100.0, 100.0, 98.4, 98.45)]
    rb = T.rebuild({**t, "exit_reason": "HOLD"}, down, rules, True, [], until=e0 + MIN)
    assert rb["exit"]["reason"] == "SL" and not rb["locks"]
    assert I.booked_roe(t, rb["exit"]["price"], "SL", rules["taker_fee"]) == pytest.approx(-0.5, abs=0.01)


def test_a_decided_replay_is_kept_and_an_open_one_worked_out_again(w15):
    I.judge(w15["p"], NOW, w15["more"])
    kept = [v for v in I._holds.values()]
    assert any(exp is None for exp, _o in kept) and any(exp is not None for exp, _o in kept)


# ================================================================ 규칙 점검: 추격 막기
def test_chase_blocked_signals_watcher_rows_first_then_replayed(w15):
    d = I.judge(w15["p"], NOW, w15["more"])
    ch = d["chase"]
    assert ch["state"] == "ok" and ch["missed"]["state"] == "ok"
    rows = {r["symbol"]: r for r in ch["rows"]}
    assert set(rows) == {"BTCUSDT", "ETHUSDT", "DOGEUSDT", "BCHUSDT"}                     # the macro-paused row is not a chase
    c1, c2, c3, c4 = rows["BTCUSDT"], rows["ETHUSDT"], rows["DOGEUSDT"], rows["BCHUSDT"]
    assert c1["cf"]["source"] == "replay" and c1["cf"]["state"] == "lost" and c1["cf"]["exit"]["reason"] == "SL"
    assert c1["cf"]["roe"] == pytest.approx(booked(1, entry_of(1), stop_of("BTCUSDT", 1) * (1 - SLIP), 40)) and c1["cf"]["roe"] == pytest.approx(-0.5, abs=0.001)
    # the money at the account's size then: margin 30 % of the wallet before c1 (after o2; t_a was still open)
    assert c1["cf"]["pnl"] == pytest.approx(c1["cf"]["roe"] * 0.3 * w15["recs"]["o2"].equity_after) and c1["cf"]["pnl_est"]
    assert c2["cf"]["source"] == "missed" and c2["cf"]["state"] == "won" and c2["cf"]["roe"] == pytest.approx(0.106) and c2["cf"]["pnl"] == 31.8
    assert c3["cf"]["source"] == "replay" and c3["cf"]["state"] == "no_data"
    assert c4["cf"]["source"] == "missed" and c4["cf"]["state"] == "unknown" and "찾지 못했어요" in c4["cf"]["why_ko"]
    assert all(r["group"] == "B" for r in ch["rows"]) and ch["rows"][0]["t"] == T0 + 9 * H              # newest first
    t = ch["totals"]
    assert (t["n"], t["won"], t["lost"], t["open"], t["unknown"], t["decided"], t["replayed"]) == (4, 1, 1, 0, 2, 2, 2)
    assert t["roe_sum"] == pytest.approx(c1["cf"]["roe"] + 0.106) and t["verdict"] == "saved"           # the block avoided a -50 %


def test_chase_without_the_watchers_file_replays_everything(w15, tmp_path):
    more = {**w15["more"], "check_db": str(tmp_path / "none.db")}
    ch = I.judge(w15["p"], NOW, more)["chase"]
    assert ch["missed"]["state"] == "missing" and all(r["cf"]["source"] == "replay" for r in ch["rows"])
    rows = {r["symbol"]: r for r in ch["rows"]}
    assert rows["ETHUSDT"]["cf"]["state"] == "no_data"                     # no ETH bar at T0 + 8 h: never made up
    assert rows["BTCUSDT"]["cf"]["state"] == "lost"


# ================================================================ 규칙 점검: 동전 쌍둥이
def test_the_coin_flip_twin_since_the_start(w15):
    tw = I.judge(w15["p"], NOW, w15["more"])["twin"]
    assert tw["state"] == "ok"
    assert (tw["real"]["n"], tw["real"]["wins"]) == (7, 2) and (tw["flip"]["n"], tw["flip"]["wins"]) == (4, 2)
    assert tw["gap"] == pytest.approx(2 / 7 - 0.5) and tw["small"] is True and tw["ref_flip_win"] == 0.75
    assert tw["real"]["start_equity"] == pytest.approx(w15["recs"]["o2"].equity_after)                     # the wallet at the start
    assert tw["flip"]["roe_sum"] == pytest.approx(0.1 - 0.5 + 0.1 - 0.5)


# ================================================================ honest states
def test_no_paper_database_an_unreadable_one_and_an_empty_one(w15, tmp_path):
    p = dict(w15["p"], paper=str(tmp_path / "gone.db"))
    d = I.judge(p, NOW, w15["more"])
    assert d["paper"]["state"] == "missing" and d["rev"]["state"] == "missing" and d["chase"]["state"] == "missing"
    assert d["twin"]["state"] == "missing" and d["rev"]["rows"] == [] and d["rev"]["totals"] is None
    g = I.goal(p, NOW, w15["more"])
    assert g["accts"][0]["state"] == "missing" and g["record"]["state"] == "missing"
    assert I.risk(p, NOW, w15["more"])["accts"][0]["state"] == "missing"
    assert I.groups(p, NOW, w15["more"])["accts"]["paper"]["state"] == "missing"
    hb = by_id(I.health(p, NOW, w15["more"])["items"])
    assert hb["paper_hb"]["state"] == "missing"
    os.makedirs(tmp_path / "dir.db")                                            # a folder in the file's place: 못 읽음 + why
    p2 = dict(w15["p"], paper=str(tmp_path / "dir.db"))
    d = I.judge(p2, NOW, w15["more"])
    assert d["paper"]["state"] == "error" and d["rev"]["state"] == "error" and d["paper"]["reason_ko"]
    # an empty account: no trade yet, every count 0 and every rate unknown (never 0 %)
    e = str(tmp_path / "empty.db")
    s = Store3(e)
    s.add_account(ACC, "combo", "mix", "combo", T0, "combo-v2")
    s.add_account(FLIP, "combo", "mix", "combo_flip", T0, "combo-v2")
    s.put_state("accounts", NOW - MIN, {"last_ts": NOW - MIN, "engines": {ACC: {"wallet": 1000.0, "position": None}, FLIP: {"wallet": 1000.0, "position": None}}})
    s.put_state("combo_run", START, {"taker_fee": TAKER, "config": CONFIG15})
    s.close()
    d = I.judge(dict(w15["p"], paper=e), NOW, w15["more"])
    assert d["rev"]["state"] == "ok" and d["rev"]["totals"]["n"] == 0 and d["rev"]["totals"]["verdict"] is None
    assert d["chase"]["totals"]["n"] == 0 and d["twin"]["real"]["n"] == 0 and d["twin"]["real"]["win_rate"] is None
    r = I.goal(dict(w15["p"], paper=e), NOW, w15["more"])["record"]
    assert r["n"] == 0 and r["win_rate"] is None and r["wilson90"] is None and r["implied"] is None


def test_no_rule_bot_bars_says_so_per_trade(w15, tmp_path):
    more = {**w15["more"], "rule_db": str(tmp_path / "no-rule.db")}
    rev = I.judge(w15["p"], NOW, more)["rev"]
    assert {r["cf"]["state"] for r in rev["rows"]} == {"missing"} and rev["totals"]["decided"] == 0
    h = I.health(w15["p"], NOW, more)
    bars = [i for i in h["items"] if i["id"] == "bars"]
    assert len(bars) == 1 and bars[0]["state"] == "missing" and h["summary"]["tone"] == "bad"


# ================================================================ 목표
def test_goal_this_month_pace_and_record(w15):
    g = I.goal(w15["p"], NOW, w15["more"])
    assert g["target"] == I.MONTHLY_TARGET == 5.0 and g["target_mult"] == 6.0
    a = by_id(g["accts"])
    pa = a["paper"]
    eq0 = w15["recs"]["o0"].equity_after                                                 # o0 closed before 10/01 KST
    assert pa["start_equity"] == pytest.approx(eq0) and pa["now_equity"] == pytest.approx(w15["recs"]["R4"].equity_after)
    assert pa["ret"] == pytest.approx(pa["now_equity"] / eq0 - 1) and pa["closed_n"] == 9
    need = 6.0 / (1 + pa["ret"])
    assert pa["pace"]["need"] == pytest.approx(need) and pa["pace"]["per_day"] == pytest.approx(need ** (1 / g["month"]["days_left"]) - 1)
    assert pa["pace"]["wins"] == math.ceil(math.log(need) / math.log(1.03))                                # +3 % wins (30 % x 10 %)
    by = a["bybit"]                                                                     # deposits out: 100 -> 140 - 50 = 90
    assert by["start_equity"] == 100.0 and by["now_equity"] == pytest.approx(90.0) and by["ret"] == pytest.approx(-0.1) and not by["late_start"]
    mx = a["mexc"]
    assert mx["late_start"] is True and mx["start_ms"] == T0 - 2 * DAY and mx["ret"] == pytest.approx(0.04)
    r = g["record"]
    assert (r["n"], r["wins"]) == (7, 2) and r["wilson90"] == pytest.approx(I.wilson(2, 7)) and r["break_even"] == 0.86
    assert r["entries"] == 8 and r["weekday_entries"] == 8                                                 # 7 closed + the open one
    assert r["weekdays"] == pytest.approx((NOW - START) / DAY) and r["weekday_ref"] == 6.2
    assert r["per_weekday"] is None and r["implied"] is None                     # under one whole weekday: no rate, no arithmetic
    assert r["avg_win"] == pytest.approx((0.105 + 0.12) / 2) and r["avg_loss"] < 0
    assert r["break_even_record"] == pytest.approx(-r["avg_loss"] / (r["avg_win"] - r["avg_loss"]))
    r2 = I.goal(w15["p"], NOW + DAY, w15["more"])["record"]                      # a day later (Tuesday 19:00 KST)
    assert r2["per_weekday"] == pytest.approx(8 / ((NOW + DAY - START) / DAY))
    m = r2["implied"]
    assert m["small"] is True and m["per_trade"] < 0 and m["rest_mult"] < 1 and m["trades_left"] == pytest.approx(r2["per_weekday"] * I.month_of(NOW + DAY)["weekdays_left"])
    logs = [math.log(t.equity_after / (t.equity_after - t.pnl)) for n, t in w15["recs"].items() if n not in ("o0", "o1", "o2")]
    assert m["per_trade"] == pytest.approx(math.exp(sum(logs) / len(logs)) - 1)


# ================================================================ 위험
def test_risk_stop_now_streak_drawdown_table_and_kill_file(w15):
    from paperbot.ladder import net_roe
    d = I.risk(w15["p"], NOW, w15["more"])
    assert d["margin"] == 0.3 and d["stop_roe"] == 0.5 and d["stop_net"] is True and d["one_stop"] == pytest.approx(0.15)
    assert [round(x["left"], 4) for x in d["table"]] == [0.85, 0.7225, 0.6141, 0.522]
    a = by_id(d["accts"])
    p = a["paper"]["position"]
    roe = net_roe(1, entry_of(1), stop_of("BCHUSDT", 1), 30, RT, 0.0)
    assert p["stop_roe"] == pytest.approx(roe) and p["stop_roe"] == pytest.approx(-0.5, abs=0.01) and p["stop_money"] == pytest.approx(roe * MARGIN)
    assert p["stop_share"] == pytest.approx(p["stop_money"] / a["paper"]["balance"]) and p["liq"] == 96.9
    assert p["liq_dist"] == pytest.approx(1 - 96.9 / 100.5) and p["stop_to_liq"] == pytest.approx(1 - 96.9 / stop_of("BCHUSDT", 1))
    assert a["paper"]["streak"] == 4                                                     # t_c, R2, R3, R4 lost in a row
    assert a["paper"]["peak"] == pytest.approx(w15["recs"]["o1"].equity_after) and a["paper"]["drawdown"] > 0.3
    b = a["bybit"]
    assert b["streak"] == 2 and b["streak_from"] == "executor" and b["peak"] == pytest.approx(110.0)       # 160 - the 50 deposit
    assert b["drawdown"] == pytest.approx(1 - 90 / 110)
    lp = b["position"]
    gross, fees = 9.0 * (98.48 - 100.03), 0.00055 * 9.0 * (100.03 + 98.48)
    assert lp["liq"] is None and lp["stop_money"] == pytest.approx(gross - fees) and lp["stop_share"] == pytest.approx((gross - fees) / 140.0)
    assert a["mexc"]["position"] is None and a["paper"]["next"][0]["money_left"] == pytest.approx(a["paper"]["balance"] * 0.85)
    k = d["kill"]
    assert k["any"] is False and k["files"] == [{"path": w15["kill"], "present": False, "from_config": True}]
    assert k["cmd"] == "sudo touch /var/lib/paperbot/STOP"
    open(w15["kill"], "w").close()
    try:
        assert I.risk(w15["p"], NOW, w15["more"])["kill"]["any"] is True
        h = I.health(w15["p"], NOW, w15["more"])
        assert h["summary"]["tone"] == "bad" and h["summary"]["ko"].startswith("비상 정지 파일 있음")
    finally:
        os.remove(w15["kill"])


# ================================================================ 봇 상태
def test_health_items_thresholds_and_one_line(w15):
    h = I.health(w15["p"], NOW, w15["more"])
    items = h["items"]
    bars = {i["who"]: i for i in items if i["id"] == "bars"}
    assert bars["BTCUSDT"]["state"] == "ok" and bars["BTCUSDT"]["at"] == NOW - MIN and bars["BTCUSDT"]["late_ms"] == 0
    assert bars["DOGEUSDT"]["state"] == "ok"
    assert bars["ETHUSDT"]["state"] == "late" and bars["ETHUSDT"]["late_ms"] == NOW - (T0 + 2 * H + 60 * MIN + MIN)
    assert bars["LTCUSDT"]["state"] == "late" and bars["LTCUSDT"]["at"] is None and "이틀" in bars["LTCUSDT"]["why_ko"]
    one = {(i["id"], i["who"]): i for i in items}
    assert one[("signal", None)]["state"] == "ok" and one[("signal", None)]["severity"] == "warn"
    assert one[("paper_hb", None)]["state"] == "ok" and one[("paper_hb", None)]["detail"] == {"queue": 1}
    assert one[("paper_step", None)]["state"] == "ok" and one[("paper_step", None)]["late_ms"] == MIN
    assert one[("exec", "bybit")]["state"] == "ok" and one[("exec", "mexc")]["state"] == "late"
    assert one[("exec", "mexc")]["late_ms"] == 10 * MIN and one[("watch", None)]["state"] == "ok"
    assert h["limits"] == {"bars_ms": 3 * MIN, "paper_hb_ms": 2 * MIN, "paper_step_ms": 3 * MIN, "exec_ms": 3 * MIN, "signal_ms": 2 * H,
                           "watch_ms": 10 * MIN}
    s = h["summary"]
    assert s["tone"] == "bad" and "MEXC 실행기 늦음 (10분)" in s["ko"] and "1분봉 ETH 늦음" in s["ko"] and "1분봉 BTC" not in s["ko"]
    assert "1분봉 LTC 늦음 (이틀 넘게 없음)" in s["ko"]
    assert I.health_summary([{"id": "x", "ko": "x", "state": "ok", "severity": "bad"}], {"any": False}) == {"tone": "ok", "ko": "다 정상", "bad": 0, "warn": 0}
    quiet = I.health_summary([{"id": "signal", "ko": "규칙봇 마지막 신호", "state": "quiet", "severity": "warn", "late_ms": 3 * H}], {"any": False})
    assert quiet["tone"] == "warn" and quiet["ko"] == "규칙봇 마지막 신호 조용함 (3시간)"


def test_pause_now_weekend_nasdaq_open_and_the_next_resume(w15):
    p = w15["p"]
    pz = I.health(p, NOW, w15["more"])["pause"]                         # Monday 19:00 KST: entries allowed, the Nasdaq open next
    assert pz["paused"] is False and pz["next"]["why"] == "usopen" and pz["rules"]["us_open_pause_min"] == 30
    assert pz["next"]["from"] == T0 + 13 * H + 30 * MIN and pz["next"]["to"] == T0 + 14 * H                 # 09:30-10:00 New York (EDT)
    inside = T0 + 13 * H + 40 * MIN
    pz = I.pause_part(p, inside, CONFIG15)
    assert pz["paused"] is True and [w["why"] for w in pz["why"]] == ["usopen"] and pz["resume_ms"] == T0 + 14 * H
    sat = T0 + 5 * DAY + 3 * H                                          # Saturday 12:00 KST: the weekend, back Monday 00:00 KST
    pz = I.pause_part(p, sat, CONFIG15)
    assert pz["paused"] is True and pz["why"][0]["why"] == "weekend" and pz["resume_ms"] == T0 + 7 * DAY - 9 * H
    assert I.us_open_windows(NOW, 30)[1] is None


# ================================================================ 그룹 (성적 · 순위)
def test_groups_a_b_and_the_old_settings_for_each_account(w15):
    g = I.groups(w15["p"], NOW, w15["more"])
    assert [x["id"] for x in g["defs"]] == ["A", "B", "old"] and g["defs"][0]["n_members"] == 2 and g["defs"][1]["n_members"] == 2
    pa = g["accts"]["paper"]["groups"]
    assert (pa["A"]["n"], pa["A"]["wins"]) == (4, 1) and (pa["B"]["n"], pa["B"]["wins"]) == (3, 1) and (pa["old"]["n"], pa["old"]["wins"]) == (3, 2)
    assert pa["B"]["win_rate"] == pytest.approx(1 / 3) and pa["B"]["roe_sum"] == pytest.approx(0.12 - 0.5 + w15["recs"]["R4"].roe)
    assert pa["none"]["n"] == 0 and pa["A"]["small"] is True
    by = g["accts"]["bybit"]["groups"]
    assert (by["A"]["n"], by["B"]["n"], by["old"]["n"], by["none"]["n"]) == (3, 1, 0, 0)
    assert by["A"]["pnl"] == pytest.approx(3.15 - 5.8 - 4.0)
    mx = g["accts"]["mexc"]["groups"]
    assert (mx["A"]["n"], mx["B"]["n"]) == (1, 1) and mx["B"]["wins"] == 1
    gone = I.groups(dict(w15["p"], mexc_db=str(w15["p"]["mexc_db"]) + ".gone"), NOW, w15["more"])
    assert gone["accts"]["mexc"]["state"] == "missing" and gone["accts"]["paper"]["state"] == "ok"


# ================================================================ 비용: 체결 비교 · 진입 방식 판단
def test_costs_carry_fill_gaps_and_the_entry_judge_without_changing_the_rest(w15):
    co = L.costs(w15["p"], NOW)
    b = co["accts"]["bybit"]
    assert {"n", "matched", "slip_avg", "rows", "missed", "coins"} <= set(b)             # the earlier keys stay
    g = b["gaps"]
    assert g["state"] == "ok" and g["n"] == 4 and g["matched"] == 4 and g["entry_n"] == 4 and g["exit_n"] == 1 and g["fee_n"] == 1
    ta = next(r for r in g["rows"] if r["symbol"] == "BTCUSDT")
    pe, px = entry_of(1), roe_price(1, entry_of(1), 40, 0.105, RT)
    assert ta["entry_gap"] == pytest.approx(-(100.05 - pe) / pe) and ta["entry_roe"] == pytest.approx(ta["entry_gap"] * 40)
    assert ta["exit_gap"] == pytest.approx(-(px - 100.40) / px) and ta["fills"] == 2
    fee = (0.0165 + 0.0167) / (0.3 * 100.05 + 0.3 * 100.40)
    assert ta["fee_rate"] == pytest.approx(fee) and ta["fee_roe"] == pytest.approx((0.0005 - fee) * 2 * 40)
    assert g["fee_rate"] == pytest.approx(fee) and g["assumed"] == {"taker": 0.0005, "slip": 0.0002, "exchange_fee": 0.00055}
    assert g["total_roe"] == pytest.approx(g["entry_roe"] + g["exit_roe"] + g["fee_roe"]) and g["total_parts"] == 3
    j = co["entry_judge"]
    assert j["need"] == [10, 20] and j["win_ref"] == 0.1 and "두 분" in j["who_ko"]
    jb = by_id(j["rows"])["bybit"]
    assert jb["n"] == 4 and jb["entry_roe"] == pytest.approx(g["entry_roe"]) and jb["share_of_win"] == pytest.approx(-g["entry_roe"] / 0.1)
    assert jb["entry_source"] == "paper"
    # an executor without a database: no gaps, and its judge row says so
    os.rename(w15["p"]["mexc_db"], w15["p"]["mexc_db"] + ".x")
    try:
        L._cache.clear()
        co = L.costs(w15["p"], NOW)
        assert "gaps" not in co["accts"]["mexc"] and by_id(co["entry_judge"]["rows"])["mexc"]["state"] == "missing"
        assert by_id(co["entry_judge"]["rows"])["mexc"]["entry_roe"] is None
    finally:
        os.rename(w15["p"]["mexc_db"] + ".x", w15["p"]["mexc_db"])


def test_read_only_the_files_are_unchanged(w15):
    files = [w15["p"]["paper"], w15["p"]["bybit_db"], w15["p"]["mexc_db"], w15["rule"], w15["check"]]
    before = {f: open(f, "rb").read() for f in files}
    for fn in (I.judge, I.goal, I.risk, I.health, I.groups):
        fn(w15["p"], NOW, w15["more"])
    L.costs(w15["p"], NOW)
    assert {f: open(f, "rb").read() for f in files} == before


# ================================================================ the routes
def test_routes_behind_the_login_answer_and_cache(w15, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from test_dash import SECRET, _store
    for k, v in W.env_of(w15["p"]).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", w15["rule"])
    monkeypatch.setenv("PAPERBOT_LIVE_CHECK_DB", w15["check"])
    dbp = str(tmp_path / "paper3.db")
    _store(dbp).close()
    app = create_app(dbp, hash_password("pw pw pw pw"), SECRET, candles=lambda s, i, n: [])
    reg = I.register(app, SimpleNamespace())
    assert reg["routes"] == ["/api/v4/livebots/judge", "/api/v4/livebots/goal", "/api/v4/livebots/risk", "/api/v4/livebots/health",
                             "/api/v4/livebots/groups"]
    c = TestClient(app)
    assert c.get("/api/v4/livebots/judge", follow_redirects=False).status_code in (401, 302, 307)
    assert c.post("/api/login", json={"password": "pw pw pw pw"}).status_code == 200
    got = {r: c.get(r) for r in reg["routes"]}
    assert all(v.status_code == 200 for v in got.values())
    assert got["/api/v4/livebots/judge"].json()["rev"]["totals"]["n"] == 4
    assert got["/api/v4/livebots/goal"].json()["target"] == 5.0
    assert got["/api/v4/livebots/risk"].json()["table"][0]["left"] == pytest.approx(0.85)
    assert got["/api/v4/livebots/health"].json()["summary"]["tone"] in ("ok", "warn", "bad")
    assert got["/api/v4/livebots/groups"].json()["accts"]["paper"]["state"] == "ok"
    assert any(k.startswith("insight:judge:") for k in L._cache)                       # the 5 s cache


# ================================================================ the screens in node
def _node(tmp_path, body: str, **data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    from paperbot.dash.app import json_finite
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    mods = "".join(f"const {n} = await import('file://{SCREENS}/livebots-{f}.js');\n"
                   for n, f in (("J", "judge"), ("G", "goal"), ("R", "risk"), ("HL", "health"), ("K", "cost"), ("RK", "rank"), ("P", "perf")))
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n" + mods + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => D.walk(n).text.replace(/\\s+/g, ' ');\n"
              "const mkCtx = (answers) => { const st = {calls: [], every: []}; return {st, ctx: {params: {query: {}}, alive: () => true, track() {},"
              " listen() {}, on() {}, watch() {}, href: (n, a) => '#/' + n, every(ms, fn) { st.every.push(ms); },"
              " api: async (path) => { st.calls.push(path); const a = answers[path] !== undefined ? answers[path] : answers['*'];"
              " if (a instanceof Error) throw a; return JSON.parse(JSON.stringify(a)); }}}; };\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


BAD = re.compile(r"\b(null|undefined|NaN|Infinity)\b|\[object")


def test_node_check_every_file():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    for f in ("judge", "goal", "risk", "health", "cost", "rank", "perf"):
        r = subprocess.run([node, "--check", os.path.join(SCREENS, f"livebots-{f}.js")], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (f, r.stderr)


@pytest.fixture(scope="module")
def answers(w15):
    from paperbot.dash.app import json_finite
    L._cache.clear()
    return {"judge": json_finite(I.judge(w15["p"], NOW, w15["more"])), "goal": json_finite(I.goal(w15["p"], NOW + DAY, w15["more"])),
            "risk": json_finite(I.risk(w15["p"], NOW, w15["more"])), "health": json_finite(I.health(w15["p"], NOW, w15["more"])),
            "groups": json_finite(I.groups(w15["p"], NOW, w15["more"])), "costs": json_finite(L.costs(w15["p"], NOW))}


def test_pure_functions_in_node(tmp_path, answers):
    out = _node(tmp_path, """const j = D_a.judge, g = D_a.goal;
    console.log(JSON.stringify({
      pp: [J.pp(0.308), J.pp(-0.2381), J.pp(null)], start: J.startWords(j.start), startNone: J.startWords({ms: null, how_ko: "모름"}),
      cf: j.rev.rows.map((r) => J.cfWords(r.cf).kind), rv: J.revVerdict(j.rev.totals), rv0: J.revVerdict({n: 0}),
      cv: J.chaseVerdict(j.chase.totals), tw: J.twinWords(j.twin),
      prog: [G.progressOf(0, 5), G.progressOf(5, 5), G.progressOf(-0.2, 5), G.progressOf(1.4494897, 5), G.progressOf(null, 5)],
      bar: G.barOf(0.5, [0.25, 0.75]), rw: [G.rangeWords([0.1, 0.5], 0.86), G.rangeWords([0.8, 0.9], 0.86), G.rangeWords([0.87, 0.95], 0.86)],
      pace: G.paceWords(g.accts[0].pace), paceDone: G.paceWords({need: 0.9, reached: true}), mult: [G.multKo(1.8432), G.multKo(0.0005), G.multKo(null)],
      stop: R.stopWords(D_a.risk.accts[0].position), stopLock: R.stopWords({stop_money: 12, stop_share: 0.01, stop_roe: 0.1}), none: R.stopWords(null),
      liqLive: R.liqWords({kind: "live"}, {}), liq: R.liqWords(D_a.risk.accts[0], D_a.risk.accts[0].position),
      items: D_a.health.items.map((i) => HL.itemWords(i).tone), lim: HL.limitsWords(D_a.health.limits),
      pz: HL.pauseWords({paused: true, why: [{ko: "주말(토·일, 한국 시간)"}], resume_ms: 1792422000000}, 1792400000000).ko,
      gt: K.gapTiles(D_a.costs.accts.bybit.gaps).map((t) => [t.id, t.v]), gt0: K.gapTiles({state: "ok", assumed: {}}).map((t) => t.v),
      jr: K.judgeRow(D_a.costs.entry_judge.rows[0], [10, 20]), jr0: K.judgeRow({n: 0}, [10, 20]).ko,
      grp: RK.groupRows(D_a.groups, "paper").map((g) => [g.id, g.rec.n]), grpB: RK.groupRows(D_a.groups, "bybit").map((g) => g.id),
    }));""", a=answers)
    assert out["pp"] == ["+30.8%p", "−23.8%p", "—"]
    assert out["start"].startswith("규칙봇 15 시작 10/19 09:30부터") and out["startNone"] == "지금 설정: 모름"
    assert sorted(out["cf"]) == ["lost", "none", "open", "won"]
    assert out["rv"]["tone"] in ("up", "down") and "빠른 손절" in out["rv"]["ko"] and "아직 없어요" in out["rv0"]["ko"]
    assert out["cv"]["tone"] == "up" and out["cv"]["ko"].startswith("추격 막기가 손해를 순ROE 합 +")
    assert out["tw"] == "진짜 신호가 동전보다 승률 21.4%p 낮음"
    assert out["prog"][:3] == [0, 1, 0] and abs(out["prog"][3] - 0.5) < 1e-3 and out["prog"][4] is None
    assert out["bar"] == {"at": 50, "lo": 25, "hi": 75}
    assert out["rw"] == ["90% 범위 전체가 본전선 아래예요", "90% 범위가 본전선에 걸쳐 있어요", "90% 범위 전체가 본전선 위예요"]
    assert out["pace"].startswith("목표까지 ×") and "하루" in out["pace"] and "+3% 승리로" in out["pace"] and out["paceDone"] == "이번 달 목표에 닿았어요"
    assert out["mult"] == ["×1.84", "×0.01 미만", "—"]
    assert out["stop"]["tone"] == "down" and out["stop"]["ko"].startswith("지금 손절에 닿으면 −") and re.search(r"순ROE −50\.\d%", out["stop"]["ko"])
    assert out["stopLock"]["tone"] == "up" and "닿아도 +12.00" in out["stopLock"]["ko"] and out["none"]["ko"] == "포지션 없음"
    assert "실행기 기록에 없어요" in out["liqLive"] and out["liq"].startswith("강제청산 96.90")
    assert "bad" in out["items"] and "ok" in out["items"] and "1분봉·페이퍼 마지막 1분 3분" in out["lim"] and "2시간" in out["lim"]
    assert out["pz"].startswith("지금 진입 쉬는 중 (주말") and "다시 진입" in out["pz"]
    gt = dict(out["gt"])
    assert gt["in"].startswith("−") and gt["out"].startswith("−") and gt["fee"] == "0.055%" and gt["sum"].endswith("%p")
    assert out["gt0"] == ["체결 기록 전", "체결 기록 전", "체결 기록 전", "—"]
    assert out["jr"]["n"] == 4 and out["jr"]["ready"] is False and out["jr"]["ko"].startswith("진입이 평균 순ROE −") and "+10% 이긴 거래의" in out["jr"]["ko"]
    assert out["jr0"] == "잰 진입이 아직 없어요"
    assert out["grp"] == [["A", 4], ["B", 3], ["old", 3]] and out["grpB"] == ["A", "B", "old"]


def test_views_draw_the_answers(tmp_path, answers):
    out = _node(tmp_path, """const run = async (V, path, a) => { const c = mkCtx({[path]: a}); const v = V(c.ctx); await tick(); await tick(); return {t: texts(v.el), c}; };
    const j = await run(J.judgeView, "/api/v4/livebots/judge", D_a.judge), g = await run(G.goalView, "/api/v4/livebots/goal", D_a.goal);
    const r = await run(R.riskView, "/api/v4/livebots/risk", D_a.risk), h = await run(HL.healthView, "/api/v4/livebots/health", D_a.health);
    const k = await run(K.costView, "/api/v4/livebots/costs", D_a.costs);
    const gb = mkCtx({"/api/v4/livebots/groups": D_a.groups}); const blk = RK.groupBlock(gb.ctx); await tick(); await tick();
    const pf = mkCtx({"/api/v4/livebots/groups": D_a.groups, "*": {now_ms: 1, accts: {paper: {state: "missing"}, bybit: {state: "missing"}, mexc: {state: "missing"}}}});
    const pv = P.perfView(pf.ctx); await tick(); await tick();
    console.log(JSON.stringify({j: j.t, g: g.t, r: r.t, h: h.t, k: k.t, blk: texts(blk.el), pv: texts(pv.el), pcalls: pf.st.calls,
      every: [j.c.st.every, g.c.st.every, r.c.st.every, h.c.st.every], calls: [j.c.st.calls, g.c.st.calls, r.c.st.calls, h.c.st.calls]}));""", a=answers)
    for k in ("j", "g", "r", "h", "k", "blk", "pv"):
        assert not BAD.search(out[k]), (k, BAD.search(out[k]))
    j = out["j"]
    for words in ("새 규칙이 실제로 도왔나?", "규칙봇 15 시작 10/19 09:30부터", "빠른 손절 판정", "빠른 손절: 첫 잠금(+10%) 전에", "−50% 손절에 닿았을 것",
                  "이겼을 것 · +10.6% 잠금 익절", "아직 결정 안 남", "1분봉 없음", "아낌", "손해", "추격 막기 판정", "추격 막기가 손해를",
                  "감시 계산", "다시 계산", "동전 쌍둥이 비교", "진짜 신호가 동전보다 승률 21.4%p 낮음", "아직 우연이 커요", "펀딩비는 넣지 않았어요",
                  "모의 · 실제 시세", "실거래 · 거래소 실제 체결"):
        assert words in j, words
    g = out["g"]
    for words in ("목표: 한 달 +500% (×6)", "두 분이 정한 목표예요 (예측 아님)", "2026년 10월 수익률", "목표까지 ×", "+3% 승리로", "첫 잔고 기록부터",
                  "지금까지 기록", "28.6%", "90% 범위", "본전 약 86%", "82%~83%", "평일 하루 진입", "6.2번", "이긴 거래 평균", "진 거래 평균",
                  "지금 기록 그대로라면", "예측이 아니고", "표본 적음"):
        assert words in g, words
    r = out["r"]
    for words in ("위험 · 보여 주기만 해요", "지금 손절에 닿으면 −", "계좌의 −", "강제청산 96.90", "실행기 기록에 없어요", "연속 손실", "4번",
                  "최고점 대비", "손절이 연달아 오면", "손절 한 번 = 계좌의 약 15%", "85.0% (−15.0%)", "52.2%", "비상 정지 파일", "없음",
                  "sudo touch /var/lib/paperbot/STOP", "지금 포지션 없음"):
        assert words in r, words
    h = out["h"]
    for words in ("1분봉 BTC", "1분봉 ETH", "늦음", "정상", "페이퍼 봇 심장 박동", "바이비트 실행기", "MEXC 실행기", "실시간 감시", "규칙봇 마지막 신호",
                  "늦음 기준: 1분봉·페이퍼 마지막 1분 3분", "지금 진입할 수 있어요", "나스닥 개장 뒤 30분", "비상 정지 파일 없음", "MEXC 실행기 늦음 (10분)"):
        assert words in h, words
    k = out["k"]
    for words in ("체결 비교", "진입 체결 차이 평균", "청산 체결 차이 평균", "수수료 (한쪽)", "0.055%", "거래당 합 (순ROE)", "진입 방식 판단",
                  "4번", "10~20번 잼", "+10% 이긴 거래의", "지금: 페이퍼 체결을 따라감", "판단은 두 분이"):
        assert words in k, words
    for words in ("그룹별 성적", "A 그룹", "B 그룹", "예전 매매법", "추격 진입 막기", "규칙봇 15 시작 10/19 09:30부터", "4번", "25.0%", "표본 적음"):
        assert words in out["blk"], words
    assert "그룹별 성적" in out["pv"] and "/api/v4/livebots/groups" in out["pcalls"]
    assert out["every"] == [[60000], [60000], [30000], [15000, 5000]]
    assert out["calls"] == [["/api/v4/livebots/judge"], ["/api/v4/livebots/goal"], ["/api/v4/livebots/risk"], ["/api/v4/livebots/health"]]


def test_views_say_not_there_yet_and_keep_a_failed_refresh_dimmed(tmp_path, w15):
    from paperbot.dash.app import json_finite
    p = dict(w15["p"], paper=str(tmp_path / "gone.db"))
    gone = {k: json_finite(fn(p, NOW, w15["more"])) for k, fn in (("judge", I.judge), ("goal", I.goal), ("risk", I.risk))}
    out = _node(tmp_path, """const run = async (V, path, seq) => { let i = 0; const c = mkCtx({}); c.ctx.api = async () => { const a = seq[Math.min(i++, seq.length - 1)];
        if (a instanceof Error) throw a; return JSON.parse(JSON.stringify(a)); }; c.ctx.every = (ms, fn) => { c.st.every.push(fn); }; const v = V(c.ctx); await tick(); await tick(); return {v, c}; };
    const j = await run(J.judgeView, "", [D_g.judge]), g = await run(G.goalView, "", [D_g.goal]), r = await run(R.riskView, "", [D_g.risk]);
    const f = await run(J.judgeView, "", [new Error("down")]);
    const s = await run(G.goalView, "", [D_g.goal, Object.assign(new Error("down"), {kind: "network"})]);
    await s.c.st.every[0](); await tick();
    const dimmed = D.walk(s.v.el).classes.some((c) => c.includes("is-stale"));
    console.log(JSON.stringify({j: texts(j.v.el), g: texts(g.v.el), r: texts(r.v.el), f: texts(f.v.el), s: texts(s.v.el), dimmed}));""", g=gone)
    for k in ("j", "g", "r"):
        assert "수집 전" in out[k] and not BAD.search(out[k]), k
    assert "불러오지 못했습니다" in out["f"] or "서버에 닿지 못했습니다" in out["f"]
    assert out["dimmed"] and "자료를 보여 드립니다" in out["s"] and "수집 전" in out["s"]


# ================================================================ the files
def test_the_files_keep_the_house_rules():
    lbcss = open(os.path.join(SCREENS, "livebots.css"), encoding="utf-8").read()
    for name, pre in (("judge", "lbj"), ("goal", "lbg"), ("risk", "lbv"), ("health", "lbd")):
        css = re.sub(r"/\*.*?\*/", "", open(os.path.join(SCREENS, f"livebots-{name}.css"), encoding="utf-8").read(), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\b(rgba?|hsla?)\(\s*\d", css), name
        for v in re.findall(r"font-size\s*:\s*([^;}]+)", css) + re.findall(r"(?<![-\w])font\s*:\s*([^;}]+)", css):
            assert "var(--t-" in v, (name, v)
        assert "infinite" not in css and "animation" not in css, name
        body = re.sub(r"@media[^{]*\{", "", css)
        for sel in re.findall(r"([^{}@;]+)\{", body):
            for part in sel.strip().split(","):
                assert "." + pre in part, (name, part)
        js = open(os.path.join(SCREENS, f"livebots-{name}.js"), encoding="utf-8").read()
        code = re.sub(r"//[^\n]*", "", js)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "setInterval(",
                    "localStorage", "toFixed("):
            assert bad not in code, (name, bad)
        # 목표 reads the replay's first-day words from 재현 비교 (weekdaysKo: "평일 30분", owners 10/21 "허전해 보여서")
        want = {"../core/pb.js", "./livebots-kit.js"} | ({"./livebots-expect.js"} if name == "goal" else set())
        assert set(re.findall(r'from "([^"]+)"', js)) == want, name
        assert f'export function {name}View(ctx)' in js and f'"/api/v4/livebots/{name}"' in js, name
        assert f'@import url("livebots-{name}.css");' in lbcss, name                     # loaded with the 실거래 screen's css
        assert "ui.staleNote(e, st.okAt" in js and "ui.dim(body, !!st.d)" in js and "sourceState(" in js, name
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "liveinsight.py"), encoding="utf-8").read()
    assert "MONTHLY_TARGET = 5.0" in src and src.count("MONTHLY_TARGET = ") == 1                       # the owners' goal: one named constant
    for pinned in ("paperbot/engine.py", "paperbot/ladder.py"):                                        # imported, never edited here
        assert os.path.exists(os.path.join(ROOT, pinned))
