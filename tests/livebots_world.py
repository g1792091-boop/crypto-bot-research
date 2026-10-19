"""A hand-made live world for the 실거래 screen (tests/test_dash_livebots.py and offline screenshots).

Every database is made by the bots' own schema code, never a copy of it: the paper bot's ``live-ac.db`` through
``paperbot.store3.Store3`` (the paper engine's state shape: ``paperbot.engine.engine_state`` of a Position), the two
executors' databases through ``paperbot.executor.ExecStore`` (its SCHEMA and MIGRATIONS) with the rows its own methods write
(trade_open / trade_close / trade_costs / equity / halt_log / event / put_state). The configs are the start guide's.

The standard world (times UTC ms, T0 = 2026-10-19 00:00 UTC = 09:00 KST), small enough to check by hand:

paper COMBO@mix (initial 1,000):  t1 BTC long +20 (T0+1h, before both executors started at T0+1h30)
                                  t2 ETH short +15   t3 SOL long -60   t4 DOGE long +10   t5 LTC short +12   t6 BCH long +8
                                  open: BTC long 40x, entry 62,000, stop 62,200 (lock +10%), last mark 62,500
paper COMBOFLIP@mix:              +5, -30, -20, +7
bybit (qty_scale 0.1, light 20 / 85%):  t2 +1.40 (fills, fee 0.30)  t3 -6.30 (fee 0.20)  t6 +0.70 (fee 0.10)
                                  extra BTC short -2.00 at T0+7h (wallet estimate, no paper trade)
                                  old ETH +3.00 one day before the paper database (fee 0.10)
                                  t4 missed: halted T0+3h30 .. T0+4h30; t5 missed: no record
                                  open: BTC long, entry 62,010, stop 62,210 (above entry: locked)
mexc (qty_scale 0.1, light 20 / 90%):   t2 +1.30 (fee 0.40)  t4 +0.90 (fee 0.20)  t6 +0.60 (key 2 minutes after the paper's)
                                  t3 missed: entry_check WARN; t5 missed: late WARN; halted at T0+8h (3연패)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

from paperbot.executor import ExecStore
from paperbot.models import Position, Signal, TradeRecord
from paperbot.store3 import Store3

H = 3_600_000
MIN = 60_000
DAY = 86_400_000
T0 = 1_792_368_000_000                     # 2026-10-19 00:00 UTC (09:00 KST)
NOW = T0 + 10 * H
ACCOUNT, FLIP = "COMBO@mix", "COMBOFLIP@mix"
LIVE_SINCE = T0 + H + 30 * MIN

# (name, symbol, side, entry ms, pnl, roe, strategy, timeframe, exit reason)
PAPER = [
    ("t1", "BTCUSDT", 1, T0 + 1 * H, 20.0, 0.05, "S2_ST_ROC", "1h", "LOCK"),
    ("t2", "ETHUSDT", -1, T0 + 2 * H, 15.0, 0.0375, "N03_ADX_GC", "15m", "LOCK"),
    ("t3", "SOLUSDT", 1, T0 + 3 * H, -60.0, -0.15, "S2_ST_ROC", "30m", "SL"),
    ("t4", "DOGEUSDT", 1, T0 + 4 * H, 10.0, 0.025, "N03_ADX_GC", "1h", "LOCK"),
    ("t5", "LTCUSDT", -1, T0 + 5 * H, 12.0, 0.03, "S2_ST_ROC", "4h", "LOCK"),
    ("t6", "BCHUSDT", 1, T0 + 6 * H, 8.0, 0.02, "N03_ADX_GC", "15m", "LOCK"),
]
FLIP_PNL = [5.0, -30.0, -20.0, 7.0]
LADDER = {"first_lock": 0.1, "step": 0.03, "trigger_gap": 0.01}
# three settings in the shape of deploy/combo.live-ac.json (research members: stop, entry, invert, filter, disp, off, cell)
MEMBERS = [
    {"strategy": "S2_ST_ROC", "tf": "1h", "numbers": {"st_len": 10, "roc_len": 12}, "cell": "S2_ST_ROC_1h", "stop": ["atr", 3.0],
     "entry": "now", "filter": [["weekend", 0], ["session", 0]], "off": [["hr", 5], ["symside", 7], ["dow", 3]]},
    {"strategy": "N03_ADX_GC", "tf": "15m", "numbers": {"adx_len": 14}, "cell": "N03_ADX_GC_15m", "stop": ["swing", 10],
     "entry": "break", "invert": True, "disp": ["range", 1.5], "off": [["oi24", 2]]},
    {"strategy": "S2_ST_ROC", "tf": "30m", "numbers": {"st_len": 8, "roc_len": 9}, "cell": "core-S2_ST_ROC-30m-1", "stop": ["pct", 2.0],
     "entry": "now"},
]
CONFIG = {"name": "A+C 합본", "initial_equity": 1000, "leverage": {"BTCUSDT": 40, "default": 30}, "margin": 0.4,
          "ladder": LADDER, "max_loss_frac": 0.35, "flip_twin": True, "no_weekend": True, "macro_blackout_min": 30,
          "stop": {"mode": "atr_fit", "atr": 3.0, "min_atr": 1.0}, "rank": ["order"], "members": MEMBERS}
ORDER_OF = {("S2_ST_ROC", "1h"): 1, ("N03_ADX_GC", "15m"): 2, ("S2_ST_ROC", "30m"): 3}


def _label(strat: str, tf: str) -> str:
    return f"{strat}@{tf}#{ORDER_OF.get((strat, tf), 9)}~abc123"


def _signal(sym: str, tf: str, strat: str, side: int, bar_close: int, member: Optional[str] = None) -> Signal:
    member = member or _label(strat, tf)
    return Signal(ts=bar_close - 1, symbol=sym, timeframe=tf, strategy_id=strat, side=side, stop_price=0.0, tier="best", score=3.0,
                  atr=1.0, meta={"member": member, "member_order": ORDER_OF.get((strat, tf), 9), "stop_rule": "3 x ATR", "source": "custom"})


def signals_and_outcomes(s: Store3) -> None:
    """The combined bot's own records of its signals (paperbot/combo.py _log / _restate and the engine's outcomes): every
    paper trade was an ENTERED signal; around them signals that were filtered (research filter, a switched-off bucket, the
    weekend, a macro release), one that lost to another signal of the same minute, one late, one waiting for its break."""
    from paperbot.models import SignalOutcome
    for _name, sym, side, t, _pnl, _roe, strat, tf, _reason in PAPER:
        sig = _signal(sym, tf, strat, side, t)
        s.log_signals([{"bar_close": t, "timeframe": tf, "strategy": sig.meta["member"], "symbol": sym, "side": side, "atr": 1.0,
                        "ref_price": 100.0, "ref_time": t, "delay_ms": 900, "status": "SUBMITTED", "data": {"source": "custom", "strategy": strat}}])
        s.outcome(ACCOUNT, SignalOutcome(sig, "ENTERED", "ok", t, {"fill": 100.0}))
    rows = [("FILTERED", "BTCUSDT", 1, T0 + 30 * MIN, "연구 조건 밖: weekend=0"), ("FILTERED", "ETHUSDT", -1, T0 + 90 * MIN, "끈 구간: hr=5"),
            ("FILTERED", "SOLUSDT", 1, T0 + 150 * MIN, "끈 구간: symside=7"), ("FILTERED", "DOGEUSDT", 1, T0 - 2 * DAY, "주말(한국 시간 토·일) 진입 안 함"),
            ("FILTERED", "LTCUSDT", -1, T0 + 200 * MIN, "경제 발표 앞뒤 30분: 소비자물가(CPI) 2026-10-19 12:30"),
            ("WAITING", "BCHUSDT", 1, NOW - 10 * MIN, "돌파 확인 대기")]
    for st, sym, side, t, why in rows:
        s.log_signals([{"bar_close": t, "timeframe": "15m", "strategy": _label("N03_ADX_GC", "15m"), "symbol": sym, "side": side, "atr": 1.0,
                        "ref_price": 100.0, "ref_time": t, "delay_ms": 800, "status": st, "data": {"source": "custom", "strategy": "N03_ADX_GC", "why": why}}])
    # same minute as t2: a second signal lost to it; and a late one
    lost = _signal("SOLUSDT", "1h", "S2_ST_ROC", 1, T0 + 2 * H)
    late = _signal("BTCUSDT", "30m", "S2_ST_ROC", -1, T0 + 7 * H)
    for sig, st, reason in ((lost, "SKIPPED", "lower score than entered signal"), (late, "REJECTED", "late")):
        s.log_signals([{"bar_close": sig.ts + 1, "timeframe": sig.timeframe, "strategy": sig.meta["member"], "symbol": sig.symbol, "side": sig.side,
                        "atr": 1.0, "ref_price": 100.0, "ref_time": sig.ts + 1, "delay_ms": 900, "status": "SUBMITTED",
                        "data": {"source": "custom", "strategy": sig.strategy_id}}])
        s.outcome(ACCOUNT, SignalOutcome(sig, st, reason, sig.ts + 1, {}))


def _trade(sym, side, entry_t, pnl, roe, eq, strat, tf, reason, price=100.0) -> TradeRecord:
    return TradeRecord(strategy_id=strat, symbol=sym, timeframe=tf, side=side, signal_ts=entry_t - 1, entry_time=entry_t,
                       entry_price=price, exit_time=entry_t + 40 * MIN, exit_price=price * (1 + side * 0.01), exit_reason=reason,
                       qty=10.0, leverage=30, tier="base", margin=400.0, stop_price=price * (1 - side * 0.01), tp_price=0.0,
                       liq_price=price * (1 - side * 0.03), fees=0.8, funding=0.1, pnl=pnl, roe=roe, price_move=0.01 * side,
                       mae_price=price, mfe_price=price, equity_after=eq, score=3.0, lock_roe=0.1 if reason == "LOCK" else None)


def paper_db(path: str, with_position: bool = True, n_extra: int = 0, extra_wins: Optional[list] = None, records: bool = True) -> str:
    """live-ac.db. ``extra_wins``: more closed trades after t6 (True = +5, False = -5), for the light tests."""
    s = Store3(path)
    s.add_account(ACCOUNT, "combo", "mix", "combo", T0, "combo-v2")
    s.add_account(FLIP, "combo", "mix", "combo_flip", T0, "combo-v2")
    eq = 1000.0
    last_t = T0
    for name, sym, side, t, pnl, roe, strat, tf, reason in PAPER:
        eq += pnl
        s.trade(ACCOUNT, _trade(sym, side, t, pnl, roe, eq, strat, tf, reason))
        last_t = t
    for i, w in enumerate(extra_wins or []):
        pnl = 5.0 if w else -5.0
        eq += pnl
        last_t = T0 + 6 * H + (i + 1) * 5 * MIN
        s.trade(ACCOUNT, _trade("ETHUSDT", 1, last_t, pnl, pnl / 400, eq, "S2_ST_ROC", "15m", "LOCK" if w else "SL"))
    feq = 1000.0
    for i, pnl in enumerate(FLIP_PNL):
        feq += pnl
        s.trade(FLIP, _trade("ETHUSDT", 1 if i % 2 else -1, T0 + (i + 2) * H, pnl, pnl / 400, feq, "S2_ST_ROC", "15m", "SL"))
    pos = None
    if with_position:
        sig = _signal("BTCUSDT", "1h", "S2_ST_ROC", 1, T0 + 9 * H)
        pos = Position(signal=sig, symbol="BTCUSDT", side=1, qty=0.25, entry_price=62000.0, entry_time=T0 + 9 * H, leverage=40,
                       tier="base", margin=387.0, margin_initial=387.5, stop_price=62200.0, tp_price=0.0, liq_price=60600.0,
                       entry_fee=7.75, funding_paid=0.5, stop_initial=61000.0, lock_roe=0.1)
    engines = {ACCOUNT: {"wallet": eq, "peak_equity": eq, "max_drawdown": 0.06, "halted": False, "halt_reason": "", "bust": False,
                         "warned": [], "last_mark": {"BTCUSDT": 62500.0}, "position": asdict(pos) if pos else None, "pending": [],
                         "n_trades": len(PAPER)},
               FLIP: {"wallet": feq, "peak_equity": 1005.0, "max_drawdown": 0.05, "halted": False, "halt_reason": "", "bust": False,
                      "warned": [], "last_mark": {}, "position": None, "pending": [], "n_trades": 4}}
    s.put_state("accounts", NOW - 2 * MIN, {"last_ts": NOW - 2 * MIN, "engines": engines})
    if records:
        signals_and_outcomes(s)
    s.put_state("combo_run", T0, {"version": "combo-v2", "brackets": "example", "taker_fee": 0.0005,
                                  "members": [f"{i}. {m['strategy']}" for i, m in enumerate(MEMBERS, 1)], "config": CONFIG})
    s.close()
    return path


def _live(st: ExecStore, key, sym, side, entry_t, pnl, fee, source="fills", entry_price=100.0, qty=1.0, lev=30):
    t = {"key": key, "symbol": sym, "side": side, "qty": qty, "leverage": lev, "entry_ts": entry_t + 20_000,
         "entry_price": entry_price, "stop_initial": entry_price * 0.99, "mode": "mainnet", "entry_time": entry_t}
    st.trade_open(t)
    st.trade_close(key, entry_t + 41 * MIN, "paper 청산 → 거래소 포지션 닫기", pnl, t, "wallet")
    if source == "fills":
        st.trade_costs(key, {"pnl": pnl, "realized": pnl + fee, "commission": fee, "funding": 0.0, "slippage": 0.01,
                             "real_cost": fee + 0.01, "assumed_cost": fee, "ok": True})


def _k(sym: str, t: int) -> str:
    return f"{ACCOUNT}|{sym}|{t}"


def bybit_db(path: str) -> str:
    st = ExecStore(path, lock=False)
    st.put_state("meta", T0, {"mode": "mainnet", "account": ACCOUNT, "since": T0, "exchange": "bybit", "live_since": LIVE_SINCE})
    p = {n: (sym, side, t) for n, sym, side, t, *_ in PAPER}
    _live(st, _k(p["t2"][0], p["t2"][2]), "ETHUSDT", -1, p["t2"][2], 1.4, 0.3)
    _live(st, _k(p["t3"][0], p["t3"][2]), "SOLUSDT", 1, p["t3"][2], -6.3, 0.2)
    _live(st, _k(p["t6"][0], p["t6"][2]), "BCHUSDT", 1, p["t6"][2], 0.7, 0.1)
    _live(st, _k("BTCUSDT", T0 + 7 * H), "BTCUSDT", -1, T0 + 7 * H, -2.0, 0.0, source="wallet")
    _live(st, _k("ETHUSDT", T0 - DAY), "ETHUSDT", 1, T0 - DAY, 3.0, 0.1)
    open_t = {"key": _k("BTCUSDT", T0 + 9 * H), "symbol": "BTCUSDT", "side": 1, "qty": 0.025, "leverage": 40, "stop": 62210.0,
              "stop_initial": 61010.0, "status": "open", "entry_ts": T0 + 9 * H + 15_000, "entry_price": 62010.0,
              "entry_time": T0 + 9 * H, "paper_entry": 62000.0, "mode": "mainnet"}
    st.trade_open(open_t)
    for ts, eq in ((T0 + 2 * H, 100.0), (T0 + 4 * H, 99.5), (T0 + 9 * H, 101.5)):
        st.equity(ts, eq, eq - 0.5, 0.0)
    st.halt_log(T0 + 3 * H + 30 * MIN, "halt", "연속 손실 3번", planned=True)
    st.halt_log(T0 + 4 * H + 30 * MIN, "clear", "연속 손실 3번", "두 분", "확인함")
    st.event(LIVE_SINCE, "INFO", "start", "시작: paper 계좌 COMBO@mix 따라 하기, mainnet")
    st.event(T0 + 3 * H + 30 * MIN, "CRITICAL", "halt", "거래를 멈춥니다(사람이 풀 때까지): 연속 손실 3번")
    st.event(T0 + 4 * H + 30 * MIN, "WARN", "halt_cleared", "두 분님이 멈춤을 풀었습니다: 연속 손실 3번 (메모: 확인함)")
    for i in range(3):
        st.event(NOW - (i + 1) * MIN, "WARN", "retry", "GET /v5/position/list 재시도: timeout")
    st.event(T0 + 6 * H + 50 * MIN, "WARN", "pnl_check", "BCHUSDT 체결로 계산한 실현 손익이 거래소 기록(closed-pnl)과 다릅니다",
             {"key": _k("BCHUSDT", T0 + 6 * H)})
    st.event(T0 + 9 * H, "INFO", "entry", "진입 BTCUSDT 롱 0.025 @ 62010, 40배, 손절 61010", {"key": _k("BTCUSDT", T0 + 9 * H)})
    st.put_state("bot", NOW - 5_000, {"trade": open_t, "done": [], "loops": 9000, "mode": "mainnet", "account": ACCOUNT,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 1, "last_equity": 101.5,
                                               "trades": 5}})
    st.close()
    return path


def mexc_db(path: str) -> str:
    st = ExecStore(path, lock=False)
    st.put_state("meta", T0, {"mode": "mainnet", "account": ACCOUNT, "since": T0, "exchange": "mexc", "live_since": LIVE_SINCE})
    _live(st, _k("ETHUSDT", T0 + 2 * H), "ETHUSDT", -1, T0 + 2 * H, 1.3, 0.4)
    _live(st, _k("DOGEUSDT", T0 + 4 * H), "DOGEUSDT", 1, T0 + 4 * H, 0.9, 0.2)
    _live(st, _k("BCHUSDT", T0 + 6 * H + 2 * MIN), "BCHUSDT", 1, T0 + 6 * H + 2 * MIN, 0.6, 0.3)
    st.equity(T0 + 9 * H, 102.8, 102.8, 0.0)
    st.event(LIVE_SINCE, "INFO", "start", "시작")
    st.event(T0 + 3 * H, "WARN", "entry_check", "진입 검사(SOLUSDT): skip - 오늘 남은 손실 한도보다 손절 손실이 큼",
             {"key": _k("SOLUSDT", T0 + 3 * H)})
    st.event(T0 + 5 * H + 4 * MIN, "WARN", "late", "paper 진입이 240초 전이라 따라 하지 않습니다", {"key": _k("LTCUSDT", T0 + 5 * H)})
    st.halt_log(T0 + 8 * H, "halt", "연속 손실 3번", planned=True)
    st.event(T0 + 8 * H, "CRITICAL", "halt", "거래를 멈춥니다(사람이 풀 때까지): 연속 손실 3번")
    st.put_state("bot", NOW - 4_000, {"trade": None, "done": [], "loops": 9100, "mode": "mainnet", "account": ACCOUNT,
                                      "risk": {"halted": True, "halt_reason": "연속 손실 3번", "halted_ts": T0 + 8 * H,
                                               "consecutive_losses": 3, "last_equity": 102.8, "trades": 3}})
    st.close()
    return path


def config(path: str, db: str, paper: str, exchange: str, min_win: float, kill_file: str, n: int = 20,
           extra: Optional[dict] = None) -> str:
    # owners 10/19: the $40 daily loss limit and the wallet check (budget_usd) were taken out of both configs
    d = {"exchange": exchange, "mode": "mainnet", "account": ACCOUNT, "paper_db": paper, "db": db,
         "qty_scale": 0.1, "entry_source": "paper", "stop_from": "ratio", "signal_light_n": n, "signal_light_min_win": min_win,
         "risk": {"max_drawdown_pct": 0.5, "max_consecutive_losses": 3, "max_leverage": 40,
                  "max_notional_usd": 10000, "max_loss_frac": 0.35,
                  "allowed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"],
                  "kill_file": kill_file}}
    d.update(extra or {})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return path


def build_world(folder: str) -> dict:
    """Every file of the standard world in ``folder``; the env mapping the dashboard reads."""
    os.makedirs(folder, exist_ok=True)
    p = {k: os.path.join(folder, f) for k, f in (("paper", "live-ac.db"), ("bybit_db", "executor-bybit-live.db"),
                                                ("mexc_db", "executor-mexc-live.db"), ("bybit_config", "executor.json"),
                                                ("mexc_config", "executor-mexc.json"))}
    paper_db(p["paper"])
    bybit_db(p["bybit_db"])
    mexc_db(p["mexc_db"])
    kill = os.path.join(folder, "STOP")
    config(p["bybit_config"], p["bybit_db"], p["paper"], "bybit", 0.85, kill)
    config(p["mexc_config"], p["mexc_db"], p["paper"], "mexc", 0.9, kill)
    return p


def env_of(p: dict) -> dict:
    from paperbot.dash.more.livebots import ENV
    return {ENV[k][0]: v for k, v in p.items() if k in ENV}


def shadow_db(path: str, pnls: list, since: int = T0) -> str:
    """A shadow paper bot's database (the same Store3 shape, account COMBO@mix): closed trades of ``pnls`` from ``since``."""
    s = Store3(path)
    s.add_account(ACCOUNT, "combo", "mix", "combo", since, "combo-v2")
    eq = 1000.0
    for i, pnl in enumerate(pnls):
        eq += pnl
        t = since + (i + 1) * H
        s.trade(ACCOUNT, _trade("ETHUSDT", 1, t, pnl, pnl / 400, eq, "S2_ST_ROC", "1h", "LOCK" if pnl > 0 else "SL"))
    s.put_state("accounts", NOW - MIN, {"last_ts": NOW - MIN, "engines": {ACCOUNT: {"wallet": eq, "peak_equity": eq, "max_drawdown": 0.0,
                "halted": False, "halt_reason": "", "bust": False, "warned": [], "last_mark": {}, "position": None, "pending": [],
                "n_trades": len(pnls)}}})
    s.put_state("combo_run", since, {"version": "combo-v2", "taker_fee": 0.0005, "members": [], "config": {**CONFIG, "name": "B 안정형"}})
    s.close()
    return path
