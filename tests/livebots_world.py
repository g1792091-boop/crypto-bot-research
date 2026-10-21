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

The live checks (``live_checks``): livecheck.db and liveimprove.db made by paperbot/livecheck.py and paperbot/liveimprove.py
themselves (two watcher passes with their loss cards, three morning checks, the weekly pass and the owners' ledger steps).
``rich=True`` first adds four KST days of reference strategies before T0 (``rich_trades``): N03_ADX_GC 8/14 (주의),
F4_FAN 1/10 (확실히 나쁨), N08_ICHI_WR 15/15, F12_MSS_DISP 2/3, and loss cards of every label.
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


# ---------------------------------------------------------------- the live checks' own files (livecheck.db, liveimprove.db)
# Made by paperbot/livecheck.py and paperbot/liveimprove.py themselves (their schemas and writers: run_watch with its loss
# cards and noise checks, run_check, save_week through run_weekly, ledger_add, set_status), never a copy of them.
EX_UNITS = {"bybit": "paperbot-executor", "mexc": "paperbot-executor-mexc"}
# the rich world (rich_trades): four KST days before T0 (10/15 .. 10/18), reference strategies so the scorecard has words
# and the loss cards every label. (strategy, tf, member label order or None, member_order or None, coin, side, won)
RICH = {"N03": ("N03_ADX_GC", "15m", 5, 5), "F4": ("F4_FAN", "30m", 77, 77), "N08": ("N08_ICHI_WR", "30m", 49, 49),
        "F12": ("F12_MSS_DISP", "1h", 1, None)}
RICH_DAYS = (
    "N08 W, F4 L, N03 W, N08 W, F4 W, N03 W, F4 L, N08 W, N03 W, F12 W",
    "F4 L, N08 W, N03 L, N08 W, F4 L, N03 W, N08 W, F4 L, N03 W, N08 W",
    "N03 L, N03 L, N08 W, F4 L, N08 W, N03 W, F12 W, F4 L, N08 W, N03 Lgap",
    "F4 L, N08 W, N03 W, F12 Lbig, N08 W, F4 L, N03 L, N08 W, N03 L, N08 W, N03 W, N08 W",
)
RICH_COIN = {"N03": ("ETHUSDT", -1), "F4": ("BTCUSDT", 1), "N08": ("SOLUSDT", 1), "F12": ("LTCUSDT", -1)}
RICH_MARGIN = 40.0
BYBIT_FOLLOWS = ("N03",)               # the rich trades bybit followed (qty 1.2 x 100 / 30x = margin 4, one tenth of the paper's)


def rich_plan() -> list:
    """[(code, strategy, tf, order, member_order, coin, side, entry ms, won, tag)] of the rich world, oldest first."""
    out = []
    for d, line in enumerate(RICH_DAYS):
        base = T0 - (len(RICH_DAYS) - d) * DAY + H                  # 10:00 KST of that day
        for i, item in enumerate(line.split(", ")):
            code, res = item.split(" ")
            strat, tf, order, mo = RICH[code]
            sym, side = RICH_COIN[code]
            out.append((code, strat, tf, order, mo, sym, side, base + i * 80 * MIN, res.startswith("W"), res[1:]))
    return out


def rich_trades(p: dict) -> list:
    """Adds the rich world's paper trades (with their ENTERED signals: setting, BTC 4h regime, stop) to the paper database
    and the trades bybit followed (one that won where the paper lost: the live-paper gap) to its database."""
    s = Store3(p["paper"])
    eq = 1000.0
    plan = rich_plan()
    for k, (code, strat, tf, order, mo, sym, side, t, won, tag) in enumerate(plan):
        roe = 0.12 if won else (-0.75 if tag == "big" else -0.35 if code == "F4" else -0.45)
        pnl = round(RICH_MARGIN * roe, 2)
        eq += pnl
        rec = _trade(sym, side, t, pnl, roe, eq, strat, tf, "LOCK" if won else "SL")
        s.trade(ACCOUNT, rec)
        meta = {"member": f"{strat}@{tf}#{order}~rich", "stop_rule": "3 x ATR", "source": "custom", "rdims": {"reg5": k % 5},
                "rstop": ["atr", 2.0]}
        if mo is not None:
            meta["member_order"] = mo
        sig = Signal(ts=t - 1, symbol=sym, timeframe=tf, strategy_id=strat, side=side, stop_price=0.0, tier="best", score=3.0, atr=1.0,
                     meta=meta)
        from paperbot.models import SignalOutcome
        s.outcome(ACCOUNT, SignalOutcome(sig, "ENTERED", "ok", t, {"fill": 100.0}))
    s.close()
    st = ExecStore(p["bybit_db"], lock=False)
    for code, strat, tf, order, mo, sym, side, t, won, tag in plan:
        if code in BYBIT_FOLLOWS or tag == "gap":
            paper = RICH_MARGIN * (0.12 if won else -0.45) / 10
            pnl = 0.4 if tag == "gap" else round(paper - 0.03, 2)            # the gap: bybit won where the paper lost
            _live(st, _k(sym, t), sym, side, t, pnl, 0.05, qty=1.2)
    st.close()
    return plan


def exec_infos(p: dict) -> list:
    """The executors as paperbot/livecheck.py reads them (their configs as plain JSON; never the key file)."""
    from paperbot import livecheck as LC
    return LC.load_executors(tuple((ex, p[f"{ex}_config"], EX_UNITS[ex], p[f"{ex}_db"], 20, 0.85) for ex in ("bybit", "mexc")))


def rule_bars(path: str, symbol: str, a: int, b: int, high=None, step: int = MIN) -> str:
    """The rule bot's 1m bars (paper3.db ``live_bars``, store3's own writer) for ``symbol`` in [a, b); ``high(ts)`` sets a
    bar's high (default: the close)."""
    s = Store3(path)
    rows = []
    for ts in range(a - a % MIN, b, step):
        hi = high(ts) if high else 100.0
        rows.append({"ts": ts, "symbol": symbol, "open": 100.0, "high": hi, "low": 99.9, "close": 100.0, "volume": 1.0,
                     "close_time": ts + MIN - 1, "processed_at": ts + MIN})
    s.live_bars(rows)
    s.close()
    return path


def livecheck_db(p: dict, folder: str, now: int = NOW) -> str:
    """livecheck.db by livecheck's own passes: the watcher at now - 30 min (loss cards, the noise check of the SOL loss
    from the rule bot's bars: back to +15 % ROE within 4 hours = a noise stop; the 1m bars late, bybit's open position
    without a recorded stop, MEXC halted) and at ``now`` (the bars back: that alarm clears and re-arms), then the morning
    checks: 10/18 with both executors (loud: MEXC halted), the days before with executors not started yet (quiet), one
    day (10/16) without a check."""
    from paperbot import livecheck as LC
    from paperbot.notify import ListNotifier
    out = os.path.join(folder, "livecheck.db")
    rule = os.path.join(folder, "rule-paper3.db")
    t3 = next(x[3] for x in PAPER if x[0] == "t3")
    rule_bars(rule, "SOLUSDT", t3 + 40 * MIN, t3 + 40 * MIN + 4 * H, high=lambda ts: 100.5 if ts == t3 + 2 * H else 100.0)
    infos = exec_infos(p)
    src = LC.Sources(db=out, paper_db=p["paper"], rule_db=rule, combo_config=os.path.join(folder, "no-combo.json"),
                     cache=os.path.join(folder, "livecheck-cache.db"), shadow_glob=os.path.join(folder, "shadow-*.db"), executors=infos)
    units = lambda unit: ("active", "enabled")            # noqa: E731  (both executors meant to run)
    LC.run_watch(src, now_ms=now - 30 * MIN, notifier=ListNotifier(), units=units, exists=lambda path: False)
    rule_bars(rule, "BTCUSDT", now - 3 * MIN, now)
    LC.run_watch(src, now_ms=now, notifier=ListNotifier(), units=units, exists=lambda path: False)
    LC.run_check(src, day="2026-10-18", now_ms=now, no_replay=True, notifier=ListNotifier())
    before = [LC.ExecInfo(name=x.name, config=x.config, unit=x.unit, db=os.path.join(folder, f"not-started-{x.name}.db"),
                          light_n=x.light_n, light_min=x.light_min, exchange=x.exchange, account=x.account) for x in infos]
    early = LC.Sources(**{**src.__dict__, "executors": before})
    for day in ("2026-10-17", "2026-10-15"):
        LC.run_check(early, day=day, now_ms=now, no_replay=True, notifier=ListNotifier())
    return out


def liveimprove_db(p: dict, folder: str, now: int = NOW) -> str:
    """liveimprove.db by liveimprove's own writers: on a world without candidates two hand-made flagged cells
    (ledger_add, the finder's shape), then the weekly pass (run_weekly: snapshot, week, the evidence refreshed), then the
    owners' hand: #1 to 백테스트 시험 (set_status)."""
    from paperbot import liveimprove as LI
    from paperbot.notify import ListNotifier
    out = os.path.join(folder, "liveimprove.db")
    ref = LI.load_ref()
    src = LI.Sources(db=out, paper_db=p["paper"], executors=exec_infos(p))
    conn = LI.open_out(out)
    try:
        cand = LI.find_candidates(LI.gather(src)["trades"], ref)
        if not cand["flagged"]:
            flagged = []
            for kind, key, n, w, tfs in (("strategy_coin", ("S2_ST_ROC", "SOLUSDT"), 9, 4, ["30m"]), ("hb", (3,), 8, 4, [])):
                p0, _fit, _hon, src_ko = LI.cell_expect(ref, kind, key)
                flagged.append({"cell": LI.cell_id(kind, key), "kind": kind, "key": list(key), "label": LI.cell_label(ref, kind, key, tfs),
                                "n": n, "wins": w, "expected": p0, "expected_src": src_ko, "p": LI.binom_cdf(w, n, p0), "family": 14,
                                "question": LI.question(ref, kind, key, tfs)})
            LI.ledger_add(conn, flagged, now - DAY)
    finally:
        conn.close()
    LI.run_weekly(src, now_ms=now, notifier=ListNotifier())
    conn = LI.open_out(out)
    try:
        LI.set_status(conn, 1, "백테스트 시험", "질문대로 두 기간 돌림", now_ms=now + MIN, who="두 분")
        rows = LI.ledger_rows(conn)
        if len(rows) >= 2:
            LI.set_status(conn, rows[-1]["id"], "기각", "2025-26에서 나빠짐", now_ms=now + 2 * MIN, who="두 분")
    finally:
        conn.close()
    return out


def live_checks(p: dict, folder: Optional[str] = None, now: int = NOW, rich: bool = False) -> dict:
    """The two live-check files for a world ({"check_db", "improve_db"}); ``rich``: first the rich world's trades."""
    folder = folder or os.path.dirname(p["paper"])
    if rich:
        rich_trades(p)
    return {"check_db": livecheck_db(p, folder, now), "improve_db": liveimprove_db(p, folder, now)}


def env_more_of(m: dict) -> dict:
    from paperbot.dash.more.livebots import ENV_MORE
    return {ENV_MORE[k][0]: v for k, v in m.items() if k in ENV_MORE}


def extend_world(folder: str, p: dict) -> dict:
    """For the screenshot scripts: the rich world's trades and both live-check files, their paths in the environment."""
    m = live_checks(p, folder, rich=True)
    os.environ.update(env_more_of(m))
    return m


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


# ---------------------------------------------------------------- the 실거래 분석 팀's own file (paperbot/liveteam.py)
TEAM_LEAD = {"headline": "페이퍼 48번 중 31번 이김: 현실 기대 범위의 아래쪽, 아직 판단은 이릅니다", "verdict": "지켜보기",
             "summary": ["페이퍼 승률 64.6%는 현실 숫자(75%)보다 낮지만 48번이면 우연으로도 나올 수 있는 범위(p=0.07)입니다",
                         "F4_FAN이 10번 중 1번만 이겨 성적표에서 '확실히 나쁨'입니다", "MEXC는 3연패로 멈춰 있습니다(사람이 풀어야 함)"],
             "good": ["N08_ICHI_WR 15번 모두 이김"], "worries": ["F4_FAN", "MEXC 멈춤"], "watch_next": ["다음 20번의 승률", "F4_FAN의 다음 5번"],
             "ideas": [{"idea": "F4_FAN을 강하락 장세에서 빼면 나아지는가", "why": "실거래 10번 중 9번 손실, 그중 6번이 강하락",
                        "test": "2020-24로 정하고 2025-26에서 한 번 확인, 그다음 그림자 봇 2주"}]}


def team_db(folder: str, p: dict, now: int = NOW) -> str:
    """liveteam.db made by paperbot/liveteam.py itself (FakeRunner answers): a decision meeting at 40 trades (done, with an
    idea), a weekly report, a quiet week and a meeting whose plan limit stopped it."""
    from paperbot import liveteam as T
    from paperbot.agents import runner as R
    path = os.path.join(folder, "liveteam.db")
    os.environ[T.DB_ENV] = path
    conn = T.connect(path)
    try:
        src = T.sources(now, p)
        answers = {"risk": {"headline": "바이비트 -8.35달러, MEXC는 3연패로 멈춤", "points": ["바이비트 19번 중 12번 이김", "MEXC 멈춤은 규칙대로"],
                            "worry": "MEXC가 멈춘 동안 페이퍼 진입을 못 따라감", "luck": "아직 거래가 적어 우연이 큼"},
                   "stats": {"headline": "48번 중 31번: 현실 기대보다 낮지만 우연 범위 안", "points": ["현실 75%면 31번 이하일 확률 7%"],
                             "worry": None, "luck": "p=0.07, 아직 결론 못 냄"},
                   "market": {"headline": "횡보장에서 8번 중 4번", "points": ["강하락 8번", "SOL 16번"], "worry": None, "luck": "칸마다 10번 미만"},
                   "lead": TEAM_LEAD}
        # the calls are charged at the world's clock (the usage of "today" is the world's day, not the day the tests run)
        T.tick(conn, src, R.FakeRunner(answers=answers), T.BUDGET_DEFAULT, clock=lambda: now)
        T.quiet(conn, "weekly", "weekly:2026-10-12", now - 7 * DAY, "지난주 닫힌 거래가 없어 AI 회의 없이 넘어갑니다")
        T.tick(conn, src, R.FakeRunner(answers=answers), T.BUDGET_DEFAULT, clock=lambda: now)
        T.tick(conn, {**src, "now": now + H}, R.FakeRunner(answers=answers, fail={"risk": R.UsageLimitReached("5-hour limit reached")}),
               T.BUDGET_DEFAULT, only="loss", force=True, clock=lambda: now + H)
        T.put_state(conn, "auth", now, {"ok": True, "why": "claude.ai"})
        T.put_state(conn, "tick", now, {"result": {"state": "done"}, "dry": False})
    finally:
        conn.close()
    return path
