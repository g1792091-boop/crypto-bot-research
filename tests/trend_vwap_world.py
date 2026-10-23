"""Two different paper bots (owners 10-23, docs/vwap-bot-ko.md): the 추세판단 봇 (live-ac.db, the site's main paper bot,
deploy/combo.trend.json) and the 'VWAP 개선판' (vwap.db, deploy/combo.vwap.json). 바이비트 follows the trend bot all along;
WOO X Pro (the "mexc" slot) followed the trend bot until SWITCH, then its start record names vwap.db (deploy/vwap_switch.py
writes that ``paper_db``). Every database is made by the bots' own schema code (paperbot.store3.Store3,
paperbot.executor.ExecStore), the records in the shapes the bots write them (combo.py _log / _restate / outcomes, the
trade's context with ``gates`` and ``exit_why``, trendbot.py's state ``trend``, entrygates.picture's ``gates_now``).

Times are Korea time (NOW = Friday 2026-10-23 20:00 KST); ``build(folder, now)`` moves the whole world by now - NOW (the
screenshots use the real clock). One position at a time in each bot.

trend paper (live-ac.db, the trend bot since TREND_SINCE 10/21 23:28):
    OLD  LTC 롱 F3_BOS 30분     10/21 20:00  LOCK +8     (the bot before it: 전환 전)
    T1   BTC 롱 V39_ALL 1시간   10/22 10:00  LOCK +16    바이비트 · WOO X Pro
    T2   ETH 숏 S3_CMO 30분     10/22 11:00  SL   -40    바이비트 · WOO X Pro (its last trend trade: S3_CMO is also a VWAP member)
    T3   SOL 롱 F6_VWAP 1시간   10/22 15:00  JUDGE -6    바이비트 (WOO X Pro follows the VWAP bot's SOL 롱 of the same minute)
    T4   DOGE 숏 N06 30분       10/23 10:00  LOCK +12    바이비트
    T5   BCH 롱 F9_IFVG 1시간   10/23 14:00  SL   -38    바이비트 missed it (late)
    open LTC 롱 F16_FIB500 1시간 10/23 19:00 (바이비트 follows)
VWAP paper (vwap.db, its account since P2_SINCE 10/20 09:00):
    V1   BTC 롱 F6_VWAP 30분    10/20 10:00  TIME -3     (96봉 = 48시간; recorded before the gates info: no ctx.gates)
    V2   ETH 숏 S3_CMO 1시간    10/22 11:00  LOCK +14    (WOO X Pro was on the trend bot then: it followed T2)
    V3   SOL 롱 F6_VWAP 30분    10/22 15:00  LOCK +13    WOO X Pro
    V4   DOGE 숏 S3_CMO 1시간   10/23 10:00  SL   -45    WOO X Pro
    V5   BCH 롱 F6_VWAP 30분    10/23 13:30  LOCK +12    WOO X Pro missed it (late)
    V6   ETH 롱 S3_CMO 1시간    10/23 16:00  LOCK +15    WOO X Pro
    open SOL 숏 F6_VWAP 30분    10/23 18:30 (WOO X Pro follows)
    filtered: 4시간 추세 반대 · 변동성 높음 · 4시간 추세 판단을 못 읽음 · 변동성 판단에 쓸 30분봉을 못 읽음 · 경제 발표 · 나스닥
"""
from __future__ import annotations

import dataclasses
import json
import os
from typing import Optional

from paperbot import combo as C
from paperbot.executor import ExecStore
from paperbot.models import Position, Signal, SignalOutcome, TradeRecord
from paperbot.store3 import Store3

MIN, H, DAY = 60_000, 3_600_000, 86_400_000
KST0 = 1_792_508_400_000                      # 2026-10-21 00:00 KST (a Wednesday)
NOW = KST0 + 2 * DAY + 20 * H                 # 10/23 (Friday) 20:00 KST
TREND_SINCE = KST0 + 23 * H + 28 * MIN        # the trend bot's first start on live-ac.db
P2_SINCE = KST0 - DAY + 9 * H                 # the VWAP bot's account (10/20 09:00)
LIVE_SINCE = KST0 - DAY                       # both executors started (10/20 00:00)
SWITCH = KST0 + DAY + 14 * H                  # WOO X Pro's start that names vwap.db (10/22 14:00)
ACCOUNT, FLIP = C.ACCOUNT, C.FLIP_ACCOUNT
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (name, symbol, side, entry, hold minutes, exit reason, pnl, roe, strategy, tf, price)
TREND = [
    ("OLD", "LTCUSDT", 1, KST0 + 20 * H, 60, "LOCK", 8.0, 0.02, "F3_BOS", "30m", 80.0),
    ("T1", "BTCUSDT", 1, KST0 + DAY + 10 * H, 40, "LOCK", 16.0, 0.04, "V39_ALL", "1h", 60000.0),
    ("T2", "ETHUSDT", -1, KST0 + DAY + 11 * H, 40, "SL", -40.0, -0.1, "S3_CMO_SANDWICH", "30m", 2500.0),
    ("T3", "SOLUSDT", 1, KST0 + DAY + 15 * H, 50, "JUDGE", -6.0, -0.015, "F6_VWAP_FAIL", "1h", 150.0),
    ("T4", "DOGEUSDT", -1, KST0 + 2 * DAY + 10 * H, 50, "LOCK", 12.0, 0.03, "N06_MACD_ORB", "30m", 0.2),
    ("T5", "BCHUSDT", 1, KST0 + 2 * DAY + 14 * H, 40, "SL", -38.0, -0.095, "F9_IFVG", "1h", 400.0),
]
TREND_OPEN = ("LTCUSDT", 1, KST0 + 2 * DAY + 19 * H, "F16_FIB500", "1h", 81.0)
VWAP = [
    ("V1", "BTCUSDT", 1, KST0 - DAY + 10 * H, 96 * 30, "TIME", -3.0, -0.0075, "F6_VWAP_FAIL", "30m", 61000.0),
    ("V2", "ETHUSDT", -1, KST0 + DAY + 11 * H, 80, "LOCK", 14.0, 0.035, "S3_CMO_SANDWICH", "1h", 2500.0),
    ("V3", "SOLUSDT", 1, KST0 + DAY + 15 * H, 40, "LOCK", 13.0, 0.0325, "F6_VWAP_FAIL", "30m", 150.0),
    ("V4", "DOGEUSDT", -1, KST0 + 2 * DAY + 10 * H, 60, "SL", -45.0, -0.1125, "S3_CMO_SANDWICH", "1h", 0.2),
    ("V5", "BCHUSDT", 1, KST0 + 2 * DAY + 13 * H + 30 * MIN, 40, "LOCK", 12.0, 0.03, "F6_VWAP_FAIL", "30m", 400.0),
    ("V6", "ETHUSDT", 1, KST0 + 2 * DAY + 16 * H, 50, "LOCK", 15.0, 0.0375, "S3_CMO_SANDWICH", "1h", 2510.0),
]
VWAP_OPEN = ("SOLUSDT", -1, KST0 + 2 * DAY + 18 * H + 30 * MIN, "F6_VWAP_FAIL", "30m", 152.0)
# (symbol, side, bar close, member strategy, tf, why, gates) of the VWAP bot's filtered signals
VWAP_FILTERED = [
    ("BTCUSDT", 1, KST0 + 2 * DAY + 9 * H + 30 * MIN, "F6_VWAP_FAIL", "30m", "4시간 추세 반대: 상승 0·하락 3·중립 1", "against"),
    ("ETHUSDT", -1, KST0 + 2 * DAY + 12 * H, "S3_CMO_SANDWICH", "1h", "변동성 높음: ATR 0.812% > 지난 30일 80% 위치 0.633%", "high"),
    ("LTCUSDT", 1, KST0 + 2 * DAY + 15 * H, "F6_VWAP_FAIL", "30m", "4시간 추세 판단을 못 읽음(진입 안 함): LTCUSDT 4h 봉을 못 받음", None),
    ("BCHUSDT", -1, KST0 + DAY + 20 * H + 30 * MIN, "F6_VWAP_FAIL", "30m",
     "변동성 판단에 쓸 30분봉을 못 읽음(진입 안 함): 끝난 봉을 아직 못 받음", "vote_only"),
    ("DOGEUSDT", 1, KST0 + DAY + 21 * H, "S3_CMO_SANDWICH", "1h", "경제 발표 앞뒤 30분: 신규 실업수당 청구 2026-10-22 12:30", None),
    ("SOLUSDT", -1, KST0 + DAY + 22 * H + 30 * MIN, "F6_VWAP_FAIL", "30m",
     "나스닥 개장 앞 30분·뒤 30분 진입 안 함 (뉴욕 09:00~10:00, 09:30 개장)", None),
]
# (symbol, side, bar close, strategy, tf, why) of the trend bot's filtered signals (trendjudge.check's words)
TREND_FILTERED = [
    ("BTCUSDT", 1, KST0 + 2 * DAY + 11 * H, "V39_ALL", "1h", "4시간 추세가 하락이라 롱 안 함(상승 0·하락 3·중립 1)"),
    ("ETHUSDT", -1, KST0 + 2 * DAY + 12 * H + 30 * MIN, "N06_MACD_ORB", "30m", "1시간 추세 힘 약함(ADX 15, 20 미만)"),
    ("SOLUSDT", 1, KST0 + 2 * DAY + 16 * H, "F9_IFVG", "1h", "추격 진입 막기: 24시간 고점 쪽 10% 안(0.96)"),
    ("DOGEUSDT", -1, KST0 + DAY + 18 * H, "F16_FIB382", "30m", "1시간 EMA20에서 2.1 ATR 아래(너무 뻗음, 1.5 넘음)"),
]


def deploy(name: str) -> dict:
    with open(os.path.join(ROOT, "deploy", name), encoding="utf-8") as fh:
        return json.load(fh)


def run_config(name: str, paper_db: str, db: str) -> dict:
    """The combo_run config as the bot writes it (dataclasses.asdict of its ComboConfig)."""
    d = {**deploy(name), "paper_db": paper_db, "db": db}
    return json.loads(json.dumps(dataclasses.asdict(C.ComboConfig(**d)), default=str))


def vote(raw: int, side: int, tf: str = "4h") -> dict:
    up, down = (3, 0) if raw > 0 else (0, 3) if raw < 0 else (1, 1)
    word = {1: "상승", -1: "하락"}.get(raw, "보류")
    return {"tf": tf, "bar_close": 0, "votes": {}, "up": up, "down": down, "raw": raw, "with_side": raw * side,
            "text": f"4시간 {word}(상승 {up}·하락 {down}·중립 {4 - up - down})"}


def vol(tf: str, atr: float, q: float) -> dict:
    tfk = {"30m": "30분", "1h": "1시간"}[tf]
    return {"tf": tf, "atr_pct": atr, "q_pct": q, "days": 30, "q": 0.8,
            "text": f"변동성 {tfk} ATR {atr:.2f}% (30일 80% 위치 {q:.2f}%)"}


def gates_of(side: int, tf: str, kind: str = "ok") -> dict:
    if kind == "against":
        return {"vote": vote(-side, side)}
    if kind == "vote_only":
        return {"vote": vote(0, side)}
    g = {"vote": vote(side if kind != "held" else 0, side)}
    g["vol"] = vol(tf, 0.812, 0.633) if kind == "high" else vol(tf, 0.45, 0.62)
    return g


def _signal(sym, tf, strat, side, bar_close, meta) -> Signal:
    return Signal(ts=bar_close - 1, symbol=sym, timeframe=tf, strategy_id=strat, side=side, stop_price=0.0, tier="best", score=3.0,
                  atr=1.0, meta={"member": f"{strat}@{tf}", "member_order": None, "stop_rule": "2 x ATR", "source": "rule",
                                 "ref_price": None, "ref_time": bar_close, **meta})


def _record(sym, side, et, hold, reason, pnl, roe, eq, strat, tf, price, ctx, lev=30) -> TradeRecord:
    xt = et + hold * MIN
    move = roe / lev
    return TradeRecord(strategy_id=strat, symbol=sym, timeframe=tf, side=side, signal_ts=et - 1, entry_time=et, entry_price=price,
                       exit_time=xt, exit_price=price * (1 + side * move), exit_reason=reason, qty=400.0 * lev / price, leverage=lev,
                       tier="base", margin=400.0, stop_price=price * (1 - side * 0.01), tp_price=0.0, liq_price=price * (1 - side * 0.03),
                       fees=0.8, funding=0.0, pnl=pnl, roe=roe, price_move=move * side, mae_price=price, mfe_price=price,
                       equity_after=eq, score=3.0, context=ctx, stop_initial=price * (1 - side * 0.01),
                       lock_roe=0.1 if reason == "LOCK" else None)


def _engine(wallet: float, pos: Optional[Position], marks: dict) -> dict:
    return {"wallet": wallet, "peak_equity": wallet, "max_drawdown": 0.05, "halted": False, "halt_reason": "", "bust": False,
            "warned": [], "last_mark": marks, "position": dataclasses.asdict(pos) if pos else None, "pending": [],
            "n_trades": 0}


def _position(sym, side, et, strat, tf, price, meta, lev=30) -> Position:
    sig = _signal(sym, tf, strat, side, et, meta)
    return Position(signal=sig, symbol=sym, side=side, qty=400.0 * lev / price, entry_price=price, entry_time=et, leverage=lev,
                    tier="base", margin=400.0, margin_initial=400.0, stop_price=price * (1 - side * 0.012), tp_price=0.0,
                    liq_price=price * (1 - side * 0.03), entry_fee=0.6, funding_paid=0.0, stop_initial=price * (1 - side * 0.012),
                    lock_roe=None)


def trend_db(path: str, sh: int, now: int) -> str:
    """The trend bot's paper database: its start record and state (since, the judgments, the members), the old bot's
    trade, its own trades with their ENTERED signals and the coin-flip twin's, its filtered signals, the open position."""
    from paperbot.trendjudge import Judgment, TrendRules
    s = Store3(path)
    s.add_account(ACCOUNT, "combo", "mix", "combo", KST0 - 10 * DAY + sh, "combo-v2")
    s.add_account(FLIP, "combo", "mix", "combo_flip", KST0 - 10 * DAY + sh, "combo-v2")
    cfg = run_config("combo.trend.json", "/var/lib/paperbot/paper3.db", path)
    rules = TrendRules.from_dict(cfg["trend"])
    s.put_state("combo_run", TREND_SINCE + sh, {"version": C.VERSION, "brackets": "example", "taker_fee": 0.0005,
                                                "members": [f"{i}. {m['strategy']}" for i, m in enumerate(cfg["members"], 1)],
                                                "config": cfg})
    labels = [f"{m['strategy']}@{m['tf']}" for m in cfg["members"]]
    s.put_state("combo", now - MIN, {"cursor": now - MIN, "queue": [], "breaks": [], "counts": {}, "version": C.VERSION,
                                     "members": labels, "trend_since": TREND_SINCE + sh})
    coins = {}
    for i, sym in enumerate(C.SYMBOLS if hasattr(C, "SYMBOLS") else ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")):
        row = {}
        for k, tf in enumerate(("1h", "4h", "1d")):
            raw = (1, -1, 0)[(i + k) % 3]
            votes = {"V39": raw or 1, "S6": raw or -1, "OBV": raw, "N12": raw if raw else 0}
            j = Judgment(symbol=sym, tf=tf, bar_close=now - now % H, votes=votes, raw=raw, dir=raw, held=(raw, raw),
                         adx=18.0 + 6 * ((i + k) % 4), adx_prev=20.0, close=100.0, ema20=99.5, atr=1.2)
            row[tf] = j.to_dict(rules)
        coins[sym] = row
    s.put_state("trend", now - MIN, {"ts": now - MIN, "coins": coins, "waits": [], "since": TREND_SINCE + sh,
                                     "pauses": {"day": None, "members": [], "coins": []}, "rules": rules.describe(),
                                     "numbers": dataclasses.asdict(rules)})
    s.put_state("heartbeat", now - 5_000, {"last_step": now - MIN, "queue": 0})
    eq, feq = 1000.0, 1000.0
    for name, sym, side, et, hold, reason, pnl, roe, strat, tf, price in TREND:
        et += sh
        eq += pnl
        tr = {"judge": f"4시간 {'상승' if side > 0 else '하락'}(상승 {3 if side > 0 else 0}·하락 {0 if side > 0 else 3}·중립 1, ADX 27 오름)",
              "score": 3.2, "htf": "4h" if tf == "1h" else "1h", "held": False}
        ctx = {"trend": tr} if name != "OLD" else {}
        if reason == "JUDGE":
            ctx["exit_why"] = "4시간 판단이 하락으로 바뀜(상승 0·하락 3·중립 1)"
        s.trade(ACCOUNT, _record(sym, side, et, hold, reason, pnl, roe, eq, strat, tf, price, ctx))
        meta = {"trend": {"htf": tr["htf"], "dir": side, "judge": tr["judge"], "strength": 3, "held": False}} if name != "OLD" else {}
        sig = _signal(sym, tf, strat, side, et, meta)
        s.log_signals([{"bar_close": et, "timeframe": tf, "strategy": f"{strat}@{tf}", "symbol": sym, "side": side, "atr": 1.0,
                        "ref_price": price, "ref_time": et, "delay_ms": 900, "status": "SUBMITTED",
                        "data": {"source": "rule", "strategy": strat, "why": f"추세 판단 통과: 바로 진입 · {tr['judge']}"}}])
        s.outcome(ACCOUNT, SignalOutcome(sig, "ENTERED", "ok", et, {"fill": price}))
        fp = pnl * (1 if name in ("T1", "T4") else -0.5)
        feq += fp
        s.trade(FLIP, _record(sym, -side, et, hold, "LOCK" if fp > 0 else "SL", fp, fp / 400, feq, strat, tf, price, {}))
    for sym, side, bc, strat, tf, why in TREND_FILTERED:
        s.log_signals([{"bar_close": bc + sh, "timeframe": tf, "strategy": f"{strat}@{tf}", "symbol": sym, "side": side, "atr": 1.0,
                        "ref_price": 100.0, "ref_time": bc + sh, "delay_ms": 800, "status": "FILTERED",
                        "data": {"source": "rule", "strategy": strat, "why": why}}])
    sym, side, et, strat, tf, price = TREND_OPEN
    et += sh
    meta = {"trend": {"htf": "4h", "dir": side, "judge": "4시간 상승(상승 3·하락 0·중립 1, ADX 26 오름)", "strength": 3, "held": False},
            "ctx": {"trend": {"judge": "4시간 상승(상승 3·하락 0·중립 1, ADX 26 오름)", "score": 3.0, "htf": "4h", "held": False}}}
    pos = _position(sym, side, et, strat, tf, price, meta)
    s.log_signals([{"bar_close": et, "timeframe": tf, "strategy": f"{strat}@{tf}", "symbol": sym, "side": side, "atr": 1.0,
                    "ref_price": price, "ref_time": et, "delay_ms": 900, "status": "SUBMITTED",
                    "data": {"source": "rule", "strategy": strat, "why": "추세 판단 통과: 바로 진입"}}])
    s.outcome(ACCOUNT, SignalOutcome(pos.signal, "ENTERED", "ok", et, {"fill": price}))
    s.put_state("accounts", now - MIN, {"last_ts": now - MIN, "engines": {ACCOUNT: _engine(eq, pos, {sym: price * 1.004}),
                                                                         FLIP: _engine(feq, None, {})}})
    s.close()
    return path


def vwap_db(path: str, sh: int, now: int) -> str:
    """The VWAP bot's paper database (combo.py's records: entered signals and trades carry what the gates read)."""
    s = Store3(path)
    s.add_account(ACCOUNT, "combo", "mix", "combo", P2_SINCE + sh, "combo-v2")
    s.add_account(FLIP, "combo", "mix", "combo_flip", P2_SINCE + sh, "combo-v2")
    cfg = run_config("combo.vwap.json", "/var/lib/paperbot/paper3.db", path)
    s.put_state("combo_run", P2_SINCE + sh, {"version": C.VERSION, "brackets": "example", "taker_fee": 0.0005,
                                             "members": [f"{i}. {m['strategy']}" for i, m in enumerate(cfg["members"], 1)],
                                             "config": cfg})
    s.put_state("combo", now - MIN, {"cursor": now - MIN, "queue": [], "breaks": [], "counts": {}, "version": C.VERSION,
                                     "members": [f"{m['strategy']}@{m['tf']}" for m in cfg["members"]]})
    s.put_state("heartbeat", now - 4_000, {"last_step": now - MIN, "queue": 0})
    eq, feq = 1000.0, 1000.0
    for name, sym, side, et, hold, reason, pnl, roe, strat, tf, price in VWAP:
        et += sh
        eq += pnl
        g = None if name == "V1" else gates_of(side, tf)
        ctx = {"gates": g} if g else {}
        if reason == "TIME":
            ctx["exit_why"] = "96봉(48시간) 지남"
        s.trade(ACCOUNT, _record(sym, side, et, hold, reason, pnl, roe, eq, strat, tf, price, ctx))
        meta = {"gates": g, "ctx": {"gates": g}} if g else {}
        sig = _signal(sym, tf, strat, side, et, {**meta, "member_order": 1 if strat == "F6_VWAP_FAIL" else 2})
        s.log_signals([{"bar_close": et, "timeframe": tf, "strategy": f"{strat}@{tf}", "symbol": sym, "side": side, "atr": 1.0,
                        "ref_price": price, "ref_time": et, "delay_ms": 900, "status": "SUBMITTED",
                        "data": {"source": "rule", "strategy": strat}}])
        s.outcome(ACCOUNT, SignalOutcome(sig, "ENTERED", "ok", et, {"fill": price}))
        fp = pnl * (0.8 if name in ("V2", "V6") else -0.6)
        feq += fp
        s.trade(FLIP, _record(sym, -side, et, hold, "LOCK" if fp > 0 else "SL", fp, fp / 400, feq, strat, tf, price, {}))
    for sym, side, bc, strat, tf, why, gk in VWAP_FILTERED:
        data = {"source": "rule", "strategy": strat, "why": why}
        if gk:
            data["gates"] = gates_of(side, tf, gk)
        s.log_signals([{"bar_close": bc + sh, "timeframe": tf, "strategy": f"{strat}@{tf}", "symbol": sym, "side": side, "atr": 1.0,
                        "ref_price": 100.0, "ref_time": bc + sh, "delay_ms": 800, "status": "FILTERED", "data": data}])
    sym, side, et, strat, tf, price = VWAP_OPEN
    et += sh
    g = gates_of(side, tf)
    pos = _position(sym, side, et, strat, tf, price, {"gates": g, "ctx": {"gates": g}, "member_order": 1})
    s.log_signals([{"bar_close": et, "timeframe": tf, "strategy": f"{strat}@{tf}", "symbol": sym, "side": side, "atr": 1.0,
                    "ref_price": price, "ref_time": et, "delay_ms": 900, "status": "SUBMITTED", "data": {"source": "rule", "strategy": strat}}])
    s.outcome(ACCOUNT, SignalOutcome(pos.signal, "ENTERED", "ok", et, {"fill": price}))
    late = _signal("BTCUSDT", "30m", "F6_VWAP_FAIL", 1, et + 30 * MIN, {"gates": gates_of(1, "30m"), "member_order": 1})
    s.log_signals([{"bar_close": et + 30 * MIN, "timeframe": "30m", "strategy": "F6_VWAP_FAIL@30m", "symbol": "BTCUSDT", "side": 1,
                    "atr": 1.0, "ref_price": 61500.0, "ref_time": et + 30 * MIN, "delay_ms": 900, "status": "SUBMITTED",
                    "data": {"source": "rule", "strategy": "F6_VWAP_FAIL"}}])
    s.outcome(ACCOUNT, SignalOutcome(late, "SKIPPED", "in position", et + 30 * MIN, {}))
    pic = {"at": now - 2 * MIN, "coins": {c: {"vote": vote(1 if i % 2 else -1, 1),
                                              "vol": {"30m": {**vol("30m", 0.4 + 0.05 * i, 0.6), "bar_close": now - 30 * MIN, "high": i == 3},
                                                      "1h": {**vol("1h", 0.5 + 0.05 * i, 0.7), "bar_close": now - H, "high": False}}}
                                          for i, c in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"))},
           "vote": cfg["vote_gate"], "vol": cfg["vol_gate"], "tfs": ["30m", "1h"]}
    s.put_state(C.GATES_NOW_KEY, now - 2 * MIN, pic)
    s.put_state("accounts", now - MIN, {"last_ts": now - MIN, "engines": {ACCOUNT: _engine(eq, pos, {sym: price * 0.997}),
                                                                         FLIP: _engine(feq, None, {})}})
    s.close()
    return path


def _key(sym: str, t: int) -> str:
    return f"{ACCOUNT}|{sym}|{t}"


def _live(st: ExecStore, sym, side, et, pnl, fee, price, scale=0.1, lev=30) -> None:
    key = _key(sym, et)
    qty = 400.0 * lev / price * scale
    t = {"key": key, "symbol": sym, "side": side, "qty": qty, "leverage": lev, "entry_ts": et + 20_000, "entry_price": price * (1 + side * 0.0002),
         "stop_initial": price * (1 - side * 0.01), "mode": "mainnet", "entry_time": et, "paper_entry": price}
    st.trade_open(t)
    st.trade_close(key, et + 41 * MIN, "paper 청산 → 거래소 포지션 닫기", pnl, t, "fills")
    st.trade_costs(key, {"pnl": pnl, "realized": pnl + fee, "commission": fee, "funding": 0.0, "slippage": 0.01,
                         "real_cost": fee + 0.01, "assumed_cost": fee, "ok": True})


def _open(st: ExecStore, sym, side, et, price, account_eq, loops, scale=0.1, lev=30) -> dict:
    t = {"key": _key(sym, et), "symbol": sym, "side": side, "qty": 400.0 * lev / price * scale, "leverage": lev,
         "stop": price * (1 - side * 0.012), "stop_initial": price * (1 - side * 0.012), "status": "open", "entry_ts": et + 15_000,
         "entry_price": price * (1 + side * 0.0002), "entry_time": et, "paper_entry": price, "mode": "mainnet", "stop_algo_id": "s1"}
    st.trade_open(t)
    return t


def exec_db(path: str, ex: str, plan: list, open_t: Optional[tuple], misses: list, starts: list, equity: list, sh: int,
            now: int) -> str:
    st = ExecStore(path, lock=False)
    st.put_state("meta", LIVE_SINCE + sh, {"mode": "mainnet", "account": ACCOUNT, "since": LIVE_SINCE + sh, "exchange": ex,
                                           "live_since": LIVE_SINCE + sh})
    for ts, pdb in starts:
        st.event(ts + sh, "INFO", "start", f"시작: paper 계좌 {ACCOUNT} 따라 하기 (페이퍼 DB {pdb}), mainnet", {"paper_db": pdb})
    for sym, side, et, pnl, fee, price in plan:
        _live(st, sym, side, et + sh, pnl, fee, price)
    trade = None
    if open_t:
        sym, side, et, price = open_t
        trade = _open(st, sym, side, et + sh, price, equity[-1][1], 9000)
    for sym, et in misses:
        st.event(et + sh + 4 * MIN, "WARN", "late", "paper 진입이 240초 전이라 따라 하지 않습니다", {"key": _key(sym, et + sh)})
    for ts, eq in equity:
        st.equity(ts + sh, eq, eq, 0.0)
    st.put_state("bot", now - 4_000, {"trade": trade, "done": [], "loops": 9000, "mode": "mainnet", "account": ACCOUNT,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": equity[-1][1],
                                               "trades": len(plan)}})
    st.close()
    return path


def config(path: str, db: str, paper: str, exchange: str, n: int, min_win: float, kill: str, loss: float = 0.35) -> str:
    d = {"exchange": exchange, "mode": "mainnet", "account": ACCOUNT, "paper_db": paper, "db": db, "qty_scale": 0.1,
         "entry_source": "paper", "ladder_from": "own", "signal_light_n": n, "signal_light_min_win": min_win,
         "risk": {"max_drawdown_pct": 0.5, "max_consecutive_losses": 3, "max_leverage": 40, "max_loss_frac": loss,
                  "allowed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"], "kill_file": kill}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return path


def by(rows: list, name: str) -> tuple:
    return next(r for r in rows if r[0] == name)


def build(folder: str, now: int = NOW) -> dict:
    """Every file of the world in ``folder`` (moved by now - NOW); the dashboard's paths (``paper2`` = vwap.db)."""
    os.makedirs(folder, exist_ok=True)
    sh = int(now) - NOW
    p = {"paper": os.path.join(folder, "live-ac.db"), "paper2": os.path.join(folder, "vwap.db"),
         "bybit_db": os.path.join(folder, "executor-bybit-live.db"), "mexc_db": os.path.join(folder, "executor-wooxpro-live.db"),
         "bybit_config": os.path.join(folder, "executor.json"), "mexc_config": os.path.join(folder, "executor-mexc.json")}
    trend_db(p["paper"], sh, now)
    vwap_db(p["paper2"], sh, now)
    t = {r[0]: r for r in TREND}
    v = {r[0]: r for r in VWAP}
    row = lambda r, pnl, fee: (r[1], r[2], r[3], pnl, fee, r[10])                    # noqa: E731
    exec_db(p["bybit_db"], "bybit", [row(t["OLD"], 0.8, 0.05), row(t["T1"], 1.6, 0.1), row(t["T2"], -4.1, 0.1), row(t["T3"], -0.7, 0.1),
                                     row(t["T4"], 1.1, 0.1)],
            (TREND_OPEN[0], TREND_OPEN[1], TREND_OPEN[2], TREND_OPEN[5]), [(t["T5"][1], t["T5"][3])],
            [(LIVE_SINCE, p["paper"])], [(LIVE_SINCE + H, 100.0), (KST0 + DAY + 12 * H, 101.2), (now - sh - H, 99.6)], sh, now)
    exec_db(p["mexc_db"], "wooxpro", [row(t["T1"], 1.5, 0.12), row(t["T2"], -4.2, 0.12), row(v["V3"], 1.2, 0.1), row(v["V4"], -4.6, 0.1),
                                      row(v["V6"], 1.4, 0.1)],
            (VWAP_OPEN[0], VWAP_OPEN[1], VWAP_OPEN[2], VWAP_OPEN[5]), [(v["V5"][1], v["V5"][3])],
            [(LIVE_SINCE, p["paper"]), (SWITCH, p["paper2"])], [(LIVE_SINCE + H, 100.0), (SWITCH + H, 97.5), (now - sh - H, 95.3)], sh, now)
    kill = os.path.join(folder, "STOP")
    config(p["bybit_config"], p["bybit_db"], p["paper"], "bybit", 20, 0.85, kill)
    config(p["mexc_config"], p["mexc_db"], p["paper2"], "wooxpro", 20, 0.75, kill, loss=0.2)
    return p


def more(folder: str) -> dict:
    """The live checks' paths of the world (none of them there: 수집 전) and no config files (the databases' own run)."""
    from paperbot.dash.more import livebots as L
    no = os.path.join(folder, "none")
    return {**L.paths_more({}), "rule_db": no + "-rule.db", "check_db": no + "-check.db", "improve_db": no + "-improve.db",
            "combo_config": no + "-combo.json", "combo2_config": no + "-combo2.json", "shadow_dir": no}
