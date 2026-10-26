"""Three paper bots on one page (owners 10-26, docs/range-bot-ko.md): 바이비트 follows the 추세판단 봇 (live-ac.db), WOO X Pro
(the "mexc" slot) followed it until RSWITCH and the 레인지 봇 (range.db) since, 딥코인 follows the 'VWAP 개선판' (vwap.db).
The trend and VWAP databases are tests/trend_vwap_world.py's (the same bots' own records); range.db is made here in the
shapes the 레인지 봇 writes them (paperbot/combo.py + paperbot/rangebot.py through paperbot.store3.Store3: its start record
``combo_run`` with the config of deploy/combo.range.json, the pulled entries' signal rows and outcomes, the trade's
context ``range``, the state ``range`` snapshot and ``combo``'s ``range_wait``, the coin-flip twin COMBOFLIP@mix). Every
executor database through paperbot.executor.ExecStore.

Times are Korea time; NOW = Tuesday 2026-10-27 20:00 KST. The 레인지 봇 (account since RANGE_SINCE, Monday 10/26 09:00):

    R1  BTC 롱 40배   10/26 10:00  TP  +12%   before WOO X Pro moved (it followed the trend bot then)
    R2  ETH 숏 30배   10/26 14:00  TP  +12%   WOO X Pro: 고정 익절
    R3  SOL 롱 30배   10/26 17:00  SL  −50%   WOO X Pro: 손절 · the price kept going (never back to the TP level in 24 h)
    R4  DOGE 롱 30배  10/27 10:00  TP  +12%   WOO X Pro: 고정 익절
    R5  LTC 숏 30배   10/27 13:00  SL  −50%   WOO X Pro missed it (liq_skip) · the price reached the TP level 3 hours later
    R6  BCH 롱 30배   10/27 16:00  TP  +12%   WOO X Pro: 고정 익절 (today)
    open ETH 롱 30배  10/27 19:05  (WOO X Pro follows)          ``wait=True``: no position, a pullback wait instead
    filtered: 추세 확인 (ETH 슈퍼트렌드 반대) · 되돌림 안 옴 · 한 신호씩 · 강제청산 여유 부족
"""
from __future__ import annotations

import dataclasses
import json
import os
from typing import Optional

from paperbot import combo as C
from paperbot.executor import ExecStore
from paperbot.models import Position, Signal, SignalOutcome, TradeRecord
from paperbot.rangebot import RangeRules, kst
from paperbot.store3 import Store3
from tests import livebots_world as W
from tests import trend_vwap_world as TW

MIN, H, DAY = TW.MIN, TW.H, TW.DAY
KST0 = TW.KST0                                  # 2026-10-21 00:00 KST
NOW = KST0 + 6 * DAY + 20 * H                  # 10/27 (Tuesday) 20:00 KST
RANGE_SINCE = KST0 + 5 * DAY + 9 * H           # the 레인지 봇's account (10/26 09:00)
RSWITCH = KST0 + 5 * DAY + 12 * H              # WOO X Pro's start that names range.db (10/26 12:00)
ACCOUNT, FLIP = C.ACCOUNT, C.FLIP_ACCOUNT
RT = 0.0014                                     # the paper rules' round trip at taker 0.05 % (livebots.round_trip)
MEMBER = "F7_RF_TRIPLE@1h#1~f7rf"
DESCRIBE = "1. F7_RF_TRIPLE 1시간 - 커스텀값 rf_mult=9.0, rf_period=80 [ds-F7_RF_TRIPLE-1h-1]"
# (name, symbol, side, entry, hold minutes, exit reason, roe, price)
RANGE = [
    ("R1", "BTCUSDT", 1, KST0 + 5 * DAY + 10 * H, 50, "TP", 0.12, 100.0),
    ("R2", "ETHUSDT", -1, KST0 + 5 * DAY + 14 * H, 40, "TP", 0.12, 100.0),
    ("R3", "SOLUSDT", 1, KST0 + 5 * DAY + 17 * H, 70, "SL", -0.5, 100.0),
    ("R4", "DOGEUSDT", 1, KST0 + 6 * DAY + 10 * H, 55, "TP", 0.12, 100.0),
    ("R5", "LTCUSDT", -1, KST0 + 6 * DAY + 13 * H, 45, "SL", -0.5, 100.0),
    ("R6", "BCHUSDT", 1, KST0 + 6 * DAY + 16 * H, 35, "TP", 0.12, 100.0),
]
RANGE_OPEN = ("ETHUSDT", 1, KST0 + 6 * DAY + 19 * H + 5 * MIN, 100.0)
# the coin-flip twin's results on the same moments (the other side): +, -, +, -, -, -
FLIP_ROE = (0.12, -0.5, 0.12, -0.5, -0.5, -0.5)
# (symbol, side, bar close, status, why) of the rows the bot did not take
FILTERED = [
    ("ETHUSDT", 1, KST0 + 6 * DAY + 8 * H, "FILTERED", "추세 확인: ETH 1시간 슈퍼트렌드 하락(신호 롱와 반대)"),
    ("SOLUSDT", -1, KST0 + 6 * DAY + 11 * H, "FILTERED", "되돌림 안 옴(10-27 12:00까지 101.2에 안 닿음)"),
    ("BTCUSDT", 1, KST0 + 6 * DAY + 13 * H, "FILTERED", "한 신호씩: LTC 숏 되돌림 기다리는 중(10-27 14:00까지)"),
    ("DOGEUSDT", -1, KST0 + 6 * DAY + 15 * H, "FILTERED", "강제청산 여유 부족: 손절 거리 1.53% + 1시간 ATR 1.95% > 2.83%(30배, 아주 거친 장)"),
]
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def lev_of(sym: str) -> int:
    return 40 if sym == "BTCUSDT" else 30


def run_config(paper_db: str, db: str, **over) -> dict:
    """The 레인지 봇's combo_run config as the bot writes it (combo.run_config of its ComboConfig)."""
    d = {**TW.deploy("combo.range.json"), "paper_db": paper_db, "db": db, **over}
    return json.loads(json.dumps(C.run_config(C.ComboConfig(**d)), default=str))


def tp_price(side: int, entry: float, lev: int, tp: float = 0.1) -> float:
    return entry * (1 + side * (tp / lev + RT))


def sl_price(side: int, entry: float, lev: int, sl: float = 0.5) -> float:
    return entry * (1 - side * (sl / lev - RT))


def info_of(sym: str, side: int, t0: int, entry_t: Optional[int] = None, close: float = 100.2, atr: float = 1.0) -> dict:
    """The range facts of a signal (rangebot._divert / _watch: info)."""
    out = {"side": side, "close": close, "atr": atr, "k": 0.2, "level": close - side * 0.2 * atr, "t0": t0, "until": t0 + 60 * MIN,
           "coin_st": side, "btc_st": side}
    if entry_t is not None:
        out.update(touch=entry_t - 10 * MIN, entry_t=entry_t)
    return out


def _signal(sym: str, side: int, bar_close: int, meta: dict) -> Signal:
    return Signal(ts=bar_close - 1, symbol=sym, timeframe="1h", strategy_id="F7_RF_TRIPLE", side=side, stop_price=0.0, tier="best",
                  score=3.0, atr=1.0, meta={"member": MEMBER, "member_order": 1, "stop_rule": "순ROE -50%", "source": "custom", **meta})


def _record(sym, side, et, hold, reason, roe, eq, price, ctx) -> TradeRecord:
    lev = lev_of(sym)
    margin = 0.4 * eq
    pnl = round(margin * roe, 4)
    xt = et + hold * MIN
    xp = tp_price(side, price, lev, 0.12 - 0.0) if reason == "TP" else sl_price(side, price, lev)
    return TradeRecord(strategy_id="F7_RF_TRIPLE", symbol=sym, timeframe="1h", side=side, signal_ts=et - 1, entry_time=et, entry_price=price,
                       exit_time=xt, exit_price=xp, exit_reason=reason, qty=margin * lev / price, leverage=lev, tier="base", margin=margin,
                       stop_price=sl_price(side, price, lev), tp_price=tp_price(side, price, lev), liq_price=price * (1 - side * 0.03),
                       fees=0.5, funding=0.0, pnl=pnl, roe=roe, price_move=(xp / price - 1.0), mae_price=price, mfe_price=price,
                       equity_after=eq + pnl, score=3.0, context=ctx, stop_initial=sl_price(side, price, lev), lock_roe=None)


def range_db(path: str, now: int = NOW, wait: bool = False, heartbeat: bool = True, over: Optional[dict] = None) -> str:
    """range.db as the 레인지 봇 writes it (module docstring); ``wait``: no open position, a pullback wait instead; ``over``:
    other config numbers (the plan must follow them)."""
    s = Store3(path)
    s.add_account(ACCOUNT, "combo", "mix", "combo", RANGE_SINCE, "combo-v2")
    s.add_account(FLIP, "combo", "mix", "combo_flip", RANGE_SINCE, "combo-v2")
    cfg = run_config("/var/lib/paperbot/paper3.db", path, **(over or {}))
    s.put_state("combo_run", RANGE_SINCE, {"version": C.VERSION, "brackets": "example", "taker_fee": 0.0005, "members": [DESCRIBE],
                                           "config": cfg})
    eq, feq = 1000.0, 1000.0
    for (name, sym, side, et, hold, reason, roe, price), froe in zip(RANGE, FLIP_ROE):
        t0 = et - 30 * MIN - (et - 30 * MIN) % H                 # the 1h close of its signal
        info = info_of(sym, side, t0, et)
        rec = _record(sym, side, et, hold, reason, roe, eq, price, {"range": info})
        s.trade(ACCOUNT, rec)
        eq = rec.equity_after
        # the signal row (WAITING, restated BROKE) and the pulled entry's SUBMITTED row with its ENTERED outcome
        s.log_signals([{"bar_close": t0, "timeframe": "1h", "strategy": MEMBER, "symbol": sym, "side": side, "atr": 1.0, "ref_price": 100.2,
                        "ref_time": t0, "delay_ms": 800, "status": "BROKE",
                        "data": {"source": "custom", "strategy": "F7_RF_TRIPLE", "range": info,
                                 "why": f"되돌림 확인: {kst(et - 10 * MIN)}에 {info['level']:.6g} 닿음 → {kst(et)} 5분봉 시가에 진입"}}])
        s.log_signals([{"bar_close": et, "timeframe": "1h", "strategy": MEMBER, "symbol": sym, "side": side, "atr": 1.0, "ref_price": price,
                        "ref_time": et, "delay_ms": 900, "status": "SUBMITTED",
                        "data": {"source": "custom", "strategy": "F7_RF_TRIPLE", "pulled": True, "range": info}}])
        s.outcome(ACCOUNT, SignalOutcome(_signal(sym, side, et, {"pulled": True, "range": info}), "ENTERED", "ok", et, {"fill": price}))
        frec = _record(sym, -side, et, hold, "TP" if froe > 0 else "SL", froe, feq, price, {})
        s.trade(FLIP, frec)
        feq = frec.equity_after
    for sym, side, bc, st, why in FILTERED:
        s.log_signals([{"bar_close": bc, "timeframe": "1h", "strategy": MEMBER, "symbol": sym, "side": side, "atr": 1.0, "ref_price": 100.0,
                        "ref_time": bc, "delay_ms": 800, "status": st, "data": {"source": "custom", "strategy": "F7_RF_TRIPLE", "why": why}}])
    pos, wt, marks = None, None, {}
    if wait:
        sym, side, t0 = "SOLUSDT", 1, now - now % H
        info = info_of(sym, side, t0, close=150.0, atr=2.0)
        sig = _signal(sym, side, t0, {})
        wt = {"member": MEMBER, "t0": t0, "until": t0 + 60 * MIN, "level": info["level"], "hit": None, "info": info,
              "signal": dataclasses.asdict(sig)}
        s.log_signals([{"bar_close": t0, "timeframe": "1h", "strategy": MEMBER, "symbol": sym, "side": side, "atr": 2.0, "ref_price": 150.0,
                        "ref_time": t0, "delay_ms": 800, "status": "WAITING",
                        "data": {"source": "custom", "strategy": "F7_RF_TRIPLE", "range": info,
                                 "why": f"되돌림 기다림: {info['level']:.6g}까지(종가 150 - 0.2 ATR)"}}])
        marks = {sym: 150.3}
    else:
        sym, side, et, price = RANGE_OPEN
        lev = lev_of(sym)
        t0 = et - 30 * MIN - (et - 30 * MIN) % H
        info = info_of(sym, side, t0, et)
        sig = _signal(sym, side, et, {"pulled": True, "range": info, "ctx": {"range": info}})
        pos = Position(signal=sig, symbol=sym, side=side, qty=0.4 * eq * lev / price, entry_price=price, entry_time=et, leverage=lev,
                       tier="base", margin=0.4 * eq, margin_initial=0.4 * eq, stop_price=sl_price(side, price, lev),
                       tp_price=tp_price(side, price, lev), liq_price=price * (1 - side * (1 / lev - 0.005)), entry_fee=0.6,
                       funding_paid=0.0, stop_initial=sl_price(side, price, lev), lock_roe=None)
        s.log_signals([{"bar_close": et, "timeframe": "1h", "strategy": MEMBER, "symbol": sym, "side": side, "atr": 1.0, "ref_price": price,
                        "ref_time": et, "delay_ms": 900, "status": "SUBMITTED",
                        "data": {"source": "custom", "strategy": "F7_RF_TRIPLE", "pulled": True, "range": info}}])
        s.outcome(ACCOUNT, SignalOutcome(sig, "ENTERED", "ok", et, {"fill": price}))
        marks = {sym: price * 1.002}
    engines = {ACCOUNT: {"wallet": eq, "peak_equity": eq, "max_drawdown": 0.2, "halted": False, "halt_reason": "", "bust": False,
                         "warned": [], "last_mark": marks, "position": dataclasses.asdict(pos) if pos else None, "pending": [],
                         "n_trades": len(RANGE)},
               FLIP: {"wallet": feq, "peak_equity": 1000.0, "max_drawdown": 0.5, "halted": False, "halt_reason": "", "bust": False,
                      "warned": [], "last_mark": {}, "position": None, "pending": [], "n_trades": len(RANGE)}}
    s.put_state("accounts", now - MIN, {"last_ts": now - MIN, "engines": engines})
    s.put_state("combo", now - MIN, {"cursor": now - MIN, "queue": [], "breaks": [], "counts": {}, "version": C.VERSION,
                                     "members": [MEMBER], "range_wait": wt})
    rules = RangeRules.from_dict(cfg["range"])
    sts = {sym: (1 if i % 3 else -1) for i, sym in enumerate(SYMS)}
    sts["LTCUSDT"] = {"error": "LTC 5분봉 3000개뿐(슈퍼트렌드에 3600개 필요)"}
    snap_wait = None if wt is None else {k: wt[k] for k in ("member", "t0", "until", "level", "hit", "info")} | {
        "symbol": wt["signal"]["symbol"], "side": wt["signal"]["side"]}
    busy = ("한 신호씩: SOL 롱 되돌림 기다리는 중" if wait else f"한 신호씩: ETH 롱 포지션 들고 있음")
    s.put_state("range", now - 2 * MIN, {"ts": now - 2 * MIN, "st_at": now - now % H, "supertrend": sts, "wait": snap_wait, "busy": busy,
                                         "rules": rules.describe(), "numbers": dataclasses.asdict(rules)})
    if heartbeat:
        s.put_state("heartbeat", now - 4_000, {"last_step": now - MIN, "queue": 0})
    s.close()
    return path


def _key(sym: str, t: int) -> str:
    return f"{ACCOUNT}|{sym}|{t}"


def _live(st: ExecStore, sym, side, et, pnl, fee, price, reason: str, code: Optional[str] = None, lev: Optional[int] = None) -> None:
    """A closed live trade: following the paper's close ("paper 청산"), its own fixed take-profit ("고정 익절", exit_code TP)
    or its own exchange stop firing ("손절 발동")."""
    lev = lev or lev_of(sym)
    key = _key(sym, et)
    qty = 40.0 * lev / price
    t = {"key": key, "symbol": sym, "side": side, "qty": qty, "leverage": lev, "entry_ts": et + 20_000, "entry_price": price * (1 + side * 0.0003),
         "stop_initial": sl_price(side, price, lev), "mode": "mainnet", "entry_time": et, "paper_entry": price}
    st.trade_open(t)
    extra = {"exit_code": code} if code else {}
    st.trade_close(key, et + 41 * MIN, reason, pnl, {**t, **extra}, "fills")
    st.trade_costs(key, {"pnl": pnl, "realized": pnl + fee, "commission": fee, "funding": 0.0, "slippage": 0.01,
                         "real_cost": fee + 0.01, "assumed_cost": fee, "ok": True})


def mexc_db(path: str, range_path: str, trend_path: str, now: int = NOW, wait: bool = False) -> str:
    """WOO X Pro: the trend bot (T1, T2, T4 by the paper's close) until RSWITCH, then the 레인지 봇 (its own take-profit and
    stop), R5 not followed (liq_skip), the open ETH (unless ``wait``)."""
    st = ExecStore(path, lock=False)
    st.put_state("meta", TW.LIVE_SINCE, {"mode": "mainnet", "account": ACCOUNT, "since": TW.LIVE_SINCE, "exchange": "wooxpro",
                                         "live_since": TW.LIVE_SINCE})
    for ts, pdb in ((TW.LIVE_SINCE, trend_path), (RSWITCH, range_path)):
        st.event(ts, "INFO", "start", f"시작: paper 계좌 {ACCOUNT} 따라 하기 (페이퍼 DB {pdb}), mainnet", {"paper_db": pdb})
    t = {r[0]: r for r in TW.TREND}
    for name, pnl in (("T1", 1.5), ("T2", -4.2), ("T4", 1.1)):
        r = t[name]
        _live(st, r[1], r[2], r[3], pnl, 0.12, r[10], "paper 청산 → 거래소 포지션 닫기", lev=30)
    rr = {r[0]: r for r in RANGE}
    for name, pnl in (("R2", 3.6), ("R3", -16.4), ("R4", 3.3), ("R6", 3.4)):
        _n, sym, side, et, _h, reason, _roe, price = rr[name]
        if reason == "TP":
            _live(st, sym, side, et, pnl, 0.2, price, "고정 익절 순ROE +10% 도달 → 시장가로 닫음", code="TP")
        else:
            _live(st, sym, side, et, pnl, 0.2, price, "거래소 손절 발동")
    r5 = rr["R5"]
    st.event(r5[3] + 4_000, "INFO", "liq_skip", "LTCUSDT 손절(순ROE -50%)이 강제청산 가격보다 멀어 이번 진입은 하지 않음",
             {"key": _key(r5[1], r5[3])})
    trade = None
    if not wait:
        sym, side, et, price = RANGE_OPEN
        trade = TW._open(st, sym, side, et, price, 120.0, 9000, scale=1.0, lev=30)
    for ts, eq in ((TW.LIVE_SINCE + H, 100.0), (RSWITCH - H, 98.0), (RSWITCH + H, 98.0), (now - H, 91.8)):
        st.equity(ts, eq, eq, 0.0)
    st.put_state("bot", now - 4_000, {"trade": trade, "done": [], "loops": 9000, "mode": "mainnet", "account": ACCOUNT,
                                      "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": 91.8,
                                               "trades": 7}})
    st.close()
    return path


def range_exec_config(path: str, db: str, paper: str, kill: str) -> str:
    """The WOO X Pro config after deploy/range_switch.py --write (the keys it sets)."""
    TW.config(path, db, paper, "wooxpro", 0, 0.75, kill, loss=0.35)
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    d.update({"size_from": "equity", "margin_frac": 0.4, "leverage_by_symbol": {"BTCUSDT": 40, "*": 30}, "stop_from": "roe",
              "stop_roe": 0.5, "stop_net": True, "ladder_from": "own", "ladder": None, "take_profit_roe": 0.1, "ladder_basis": "net",
              "signal_light_n": 0, "equity_floor_frac": None, "liq_guard": True, "liq_guard_mmr": 0.005, "macro_block_min": 30})
    d["risk"]["max_leverage"] = 40
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return path


def _bars(path: str, symbol: str, a: int, b: int, high, low, step: int = 5 * MIN) -> None:
    """The rule bot's 1m bars (paper3.db live_bars, store3's own writer) of ``symbol`` in [a, b), every ``step``."""
    s = Store3(path)
    s.live_bars([{"ts": ts, "symbol": symbol, "open": 100.0, "high": high(ts), "low": low(ts), "close": 100.0, "volume": 1.0,
                  "close_time": ts + MIN - 1, "processed_at": ts + MIN} for ts in range(a - a % MIN, b, step)])
    s.close()


def rule_bars(path: str) -> str:
    """The rule bot's 1m bars after the two stop-outs: SOL (a long stopped at 10/26 18:10) never back up to its take-profit
    level in the 24 hours after (the price kept going down: 방향이 틀림); LTC (a short stopped at 10/27 13:45) down to its
    take-profit level three hours later (손절이 가까웠음)."""
    r3 = next(r for r in RANGE if r[0] == "R3")
    x3 = r3[3] + r3[4] * MIN
    _bars(path, "SOLUSDT", r3[3], x3 + 25 * H, high=lambda ts: 99.2, low=lambda ts: 97.0)
    r5 = next(r for r in RANGE if r[0] == "R5")
    x5 = r5[3] + r5[4] * MIN
    hit = x5 + 3 * H
    _bars(path, "LTCUSDT", r5[3], NOW, high=lambda ts: 102.0, low=lambda ts: 99.4 if ts == hit else 100.6)
    return path


def build(folder: str, now: int = NOW, wait: bool = False, deepcoin: bool = True) -> dict:
    """Every file of the world in ``folder``; the dashboard's paths (``paper2`` = vwap.db, ``range`` = range.db)."""
    os.makedirs(folder, exist_ok=True)
    p = {"paper": os.path.join(folder, "live-ac.db"), "paper2": os.path.join(folder, "vwap.db"), "range": os.path.join(folder, "range.db"),
         "bybit_db": os.path.join(folder, "executor-bybit-live.db"), "mexc_db": os.path.join(folder, "executor-wooxpro-live.db"),
         "bybit_config": os.path.join(folder, "executor.json"), "mexc_config": os.path.join(folder, "executor-mexc.json"),
         "deepcoin_db": os.path.join(folder, "executor-deepcoin-live.db"), "deepcoin_config": os.path.join(folder, "executor-deepcoin.json"),
         "paper3": os.path.join(folder, "no-friend.db"), "wooxpro2_db": os.path.join(folder, "no-w2.db"),
         "wooxpro2_config": os.path.join(folder, "no-w2.json"), "toobit_db": os.path.join(folder, "no-tb.db"),
         "toobit_config": os.path.join(folder, "no-tb.json")}
    TW.trend_db(p["paper"], 0, now)
    TW.vwap_db(p["paper2"], 0, now)
    range_db(p["range"], now, wait=wait)
    t = {r[0]: r for r in TW.TREND}
    v = {r[0]: r for r in TW.VWAP}
    row = lambda r, pnl, fee: (r[1], r[2], r[3], pnl, fee, r[10])                    # noqa: E731
    TW.exec_db(p["bybit_db"], "bybit", [row(t["T1"], 1.6, 0.1), row(t["T2"], -4.1, 0.1), row(t["T3"], -0.7, 0.1), row(t["T4"], 1.1, 0.1)],
               (TW.TREND_OPEN[0], TW.TREND_OPEN[1], TW.TREND_OPEN[2], TW.TREND_OPEN[5]), [(t["T5"][1], t["T5"][3])],
               [(TW.LIVE_SINCE, p["paper"])], [(TW.LIVE_SINCE + H, 100.0), (now - H, 99.6)], 0, now)
    mexc_db(p["mexc_db"], p["range"], p["paper"], now, wait=wait)
    kill = os.path.join(folder, "STOP")
    TW.config(p["bybit_config"], p["bybit_db"], p["paper"], "bybit", 20, 0.85, kill)
    range_exec_config(p["mexc_config"], p["mexc_db"], p["range"], kill)
    if deepcoin:
        TW.exec_db(p["deepcoin_db"], "deepcoin", [row(v["V3"], 1.2, 0.1), row(v["V4"], -4.6, 0.1), row(v["V6"], 1.4, 0.1)],
                   (TW.VWAP_OPEN[0], TW.VWAP_OPEN[1], TW.VWAP_OPEN[2], TW.VWAP_OPEN[5]), [(v["V5"][1], v["V5"][3])],
                   [(TW.LIVE_SINCE, p["paper2"])], [(TW.LIVE_SINCE + H, 100.0), (now - H, 95.3)], 0, now)
        TW.config(p["deepcoin_config"], p["deepcoin_db"], p["paper2"], "deepcoin", 20, 0.75, kill, loss=0.2)
    else:
        p["deepcoin_db"], p["deepcoin_config"] = os.path.join(folder, "no-dc.db"), os.path.join(folder, "no-dc.json")
    return p


def more(folder: str) -> dict:
    """The live checks' paths of the world (none there: 수집 전), the rule bot's 1m bars (rule_bars) and no config files."""
    from paperbot.dash.more import livebots as L
    no = os.path.join(folder, "none")
    rule = os.path.join(folder, "rule-paper3.db")
    if not os.path.exists(rule):
        rule_bars(rule)
    return {**L.paths_more({}), "rule_db": rule, "check_db": no + "-check.db", "improve_db": no + "-improve.db",
            "combo_config": no + "-combo.json", "combo2_config": no + "-combo2.json", "range_config": no + "-range.json",
            "shadow_dir": no}
