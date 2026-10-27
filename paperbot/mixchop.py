"""믹스 30분 봇 (owners 2026-10-25 night): the WOO X Pro SECOND account trades the 30-minute signal of the TradingView
indicator "추세 조건 OBV·클링거 + 매매 시그널" (TREND_MIX_CHOP_SIGNAL.pine, its signal part), with the formulas and rules
of the design notes the owners handed over (SIGNAL_30M_GUIDE.md, BOT_FORMULAS.md). Owners' choices on top of them: ONE
position at a time across the coins, coins SOL · ETH · XRP · BCH · ZEC · DOGE (LTC off), market orders, $50 to start.

    python -m paperbot.mixchop check   --config /etc/paperbot/mixchop.json   # reads only: specs, account, sizes now
    python -m paperbot.mixchop signals --config /etc/paperbot/mixchop.json   # recent colour changes, to compare with TV
    python -m paperbot.mixchop run     --config /etc/paperbot/mixchop.json   # the bot ("mode": "paper" or "mainnet")

Signal (every 30m close, closed Binance USDT-M bars only, as the TradingView chart the owners read):
- avgRsi = EMA3( 50 + 50 * (rS + cS + mS) / 3 ), rS = (RSI26 - 50) / 50, cS = zsq(ROC7, 100), mS = zsq(close - close[7],
  100), zsq(x, n) = tanh(x / stdev_n(x)) (0 when the deviation is 0 or not yet defined).
- the line: nScore = ((RSI26 - 50) / 50 + zsq(ROC9, 100) + zsq(close - close[10], 100)) / 3, nLine = its running sum,
  nSig = EMA9(nLine); gold = nLine > nSig. Long: gold on this bar and not on the one before (to cyan); short: the other way.
- long also needs the 30m avgRsi > 50 and the last CLOSED 1h bar's avgRsi > 50 - buffer; short: < 50 and < 50 + buffer
  (a 30m bar closing on the hour uses the 1h bar closing with it, a :30 close the one before). No late entries: a colour
  change whose RSI conditions fail is skipped until the next change.
- the stop distance ATR14(30m, the signal bar) x the coin's multiple must be shorter than price x (1 / leverage - 0.5 %),
  else the signal is skipped (liquidation guard).
Pine's own seeding is reproduced (RMA and EMA start from a simple average); with 1,500 bars of history the values agree
with TradingView's to the decimals (tests/test_mixchop.py checks the design's DOGE table).

Trade:
- size: a stop-out loses ``risk_pct`` (0.25 %) of the account equity: qty = equity x risk / stop distance, isolated at
  the coin's leverage (40x; ZEC 20x), floored to the contract step; under the minimum: skipped, never rounded up.
- entry: a market order right after the 30m close; the stop is the fill price -/+ the stop distance, placed at once as
  a resting close-only stop on WOO X Pro (last price). A stop that cannot be placed closes the position at market.
- ladder (ROE on the leverage, price-based like the indicator): best = the most favourable price since entry (30m
  highs / lows); at each 30m close that did not stop the position, when best is ``roe_act`` % ROE past the entry, the
  stop goes to entry + 10 % ROE, and one more step of (roe_act - 10) % ROE for each further step reached; it only ever
  moves the favourable way, and only at 30m closes. No exit on an opposite signal or on time: stop or ladder only.
- owners 10-26 (config options, off unless set; deploy/mixchop.live.json sets them): ``margin_frac`` sizes each entry
  by margin instead (equity x margin_frac as margin: qty = equity x margin_frac x leverage / price, capped by
  ``max_notional_usd``); ``ladder`` {"trigger", "lock", "step"} replaces the coins' roe_act ladder for every coin with
  one on NET ROE (WOO X Pro's taker fee ``taker_fee`` on both sides, at the coin's leverage): trigger -> lock, then one
  step more for each further step (12 -> 10, 17 -> 15, 22 -> 20 ...); ``ladder_every_s`` > 0 follows the open position
  on Binance's closed 1m bars that often between the closes as well (best, the ladder, the resting stop moved; paper:
  its stop judged on the same 1m bars), and at the 30m close on 1m bars too.
- owners 10-26 ("둘 다"): ``rules`` ["mix", "st"] adds a second entry rule, the owners' own (research/mixchop_st:
  "30분봉 진입 슈퍼트렌드 14/3, 14/6 같은 상승 추세이고 스톡RSI 14/11/4/5를 사용하고 골든 크로스를 하는데 RSI26이 50 위에 있고
  그리고 1시간봉 RSI26도 50 위에 있으면 롱 진입, 1시간봉은 슈퍼트렌드 사용 안 함, 숏은 반대"): on the closed 30m bar, long =
  TradingView's Supertrend(ATR 14, factor 3) and (ATR 14, factor 6) both up, Stoch RSI (RSI 14, stochastic 11, K SMA 4,
  D SMA 5) %K crossing above %D on this bar, RSI(26) of the 30m closes > 50 and of the last CLOSED 1h bar > 50 (the same
  1h bar as the friend's rule); short = the mirror. Its stop and the liquidation guard as the friend's (ATR14 x the
  multiple). On one coin and close the friend's rule ("mix") answers first. ``stop_atr`` (owners 10-26: 3) replaces every
  coin's ``sl_atr`` for both rules. Exits as before (stop or ladder). Default: ["mix"] and the coins' own multiples.
- owners 10-27, the second rule changed ("스톡RSI 14/11/4/6 ... 골든 크로스를 하는데 RSI26이 50 위에 있고 MOM도 0선 위에
  있고 그리고 1시간봉 RSI26도 50 위에 있으면 롱 진입"): the Stoch RSI's %D SMA 5 -> 6 (``ST_STOCH``, read in the same order
  as on 10-26: RSI 14, stochastic 11, %K 4, %D 6) and one more condition, MOM(10) of the 30m closes (TradingView's
  Momentum, close - close 10 bars before, ``ST_MOM``) above 0 for a long, below 0 for a short.
- one position at a time over all coins; signals of one close compete by the coin order of the config.
- entry blocks (owners 10-25 night, the same as their own bots; not in the friend's design, so off unless the config
  sets them): ``no_weekend`` (Saturday and Sunday KST), ``us_open_pre_min`` / ``us_open_pause_min`` (minutes before /
  after the NYSE open 09:30 New York, DST aware, weekdays, not on NYSE holidays), ``macro_blackout_min`` (minutes
  around the US releases in data/macro_events.csv). Judged on the entry minute; only entries stop (the open position's
  stop and ladder go on). A blocked signal is skipped, not taken later.
- halts: the shared kill file or the bot's own stop file (no new entries; the open position keeps its stop and ladder;
  stop the service and close on WOO X Pro by hand to flatten), the equity floor (``equity_floor_frac`` of
  the starting equity: no new entries), any position on the account the bot does not know (no new entries, alert).
Restart: the state file holds the open position (coin, side, size, entry, stop, best, ladder step); at start it is
checked against WOO X Pro and the resting stop is placed again when missing. "paper" mode trades nothing: it fills at
the signal close and exits on the 30m bars as the indicator does (stop at the stop price, or the open when it gaps).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import signal as _signal
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Callable, Optional

import numpy as np
import pandas as pd

MIN30 = 30 * 60_000
MIN1 = 60_000
MINUTE_MAX = 1400               # 1m bars read at most (one request); a longer gap (the bot was down) is walked on 30m bars
H1 = 3_600_000
KST_MS = 9 * H1
BARS = 1500                     # history per request (Binance's maximum): enough for the EMA / RMA / sum to settle
SETTLE_S = 4.0                  # wait after a close before reading its bar
READ_TRIES = 12                 # ... and read again every 5 s while the bar is not there yet (1 minute)
POLL_S = 15.0                   # open position: how often WOO X Pro is asked whether it is still open
STOP_CHECK_S = 300.0            # ... and whether its stop is still resting
LOCK_ROE = 10.0                 # the first lock (the indicator's minimum take-profit, %)
MMR_PCT = 0.5                   # maintenance margin used by the liquidation guard (%)
ST_STOCH = (14, 11, 4, 6)       # the second rule's Stoch RSI: RSI, stochastic, %K SMA, %D SMA (owners 10-27: %D 5 -> 6)
ST_MOM = 10                     # ... and its MOM length (owners 10-27: MOM above / below 0)
# 30m settings of the design notes (BOT_FORMULAS.md 5): trend-bar buffer, stop ATR multiple, ladder start ROE, leverage
DEFAULT_COINS = {
    "SOLUSDT": {"h1_buf": 8.0, "sl_atr": 2.0, "roe_act": 150.0, "leverage": 40},
    "ETHUSDT": {"h1_buf": 8.5, "sl_atr": 1.5, "roe_act": 200.0, "leverage": 40},
    "XRPUSDT": {"h1_buf": 9.5, "sl_atr": 1.5, "roe_act": 200.0, "leverage": 40},
    "BCHUSDT": {"h1_buf": 3.0, "sl_atr": 2.0, "roe_act": 150.0, "leverage": 40},
    "ZECUSDT": {"h1_buf": 6.5, "sl_atr": 2.5, "roe_act": 100.0, "leverage": 20},
    "DOGEUSDT": {"h1_buf": 4.0, "sl_atr": 2.5, "roe_act": 100.0, "leverage": 40},
}
NAME = "믹스 30분 봇"
EXIT_KO = {"stop": "손절", "ladder": "계단 익절", "closed_while_down": "봇이 꺼진 사이 청산", "manual": "직접 청산",
           "protect": "손절을 못 걸어 바로 청산", "wrong_side": "방향이 다른 포지션이라 청산"}
ALERT_EVERY_S = 600              # a repeated CRITICAL (still no stop / an unknown position) at most this often
ADOPT_WINDOW_MS = 10 * 60_000    # an entry the bot could not see filled: a position on that coin within this is its own
LIQ_ROOM = 0.002                 # live: the stop must sit this much (of the price) inside WOO X Pro's own liquidation


class MixError(ValueError):
    """A configuration or state the bot refuses (Korean message)."""


# ====================================================================== indicators (Pine semantics)
def _seed_recursive(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Pine's ta.rma / ta.ema: NaN until n values exist, seeded with their simple average, then
    s = alpha * x + (1 - alpha) * s. ``x`` may start with NaN (they are skipped); later NaN keep the last value."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(x))
    if len(ok) < n:
        return out
    f = ok[0]
    if not np.isfinite(x[f:f + n]).all():
        return out
    s = float(np.mean(x[f:f + n]))
    out[f + n - 1] = s
    for i in range(f + n, len(x)):
        v = x[i]
        if np.isfinite(v):
            s = alpha * v + (1.0 - alpha) * s
        out[i] = s
    return out


def rma(x, n: int) -> np.ndarray:
    return _seed_recursive(x, n, 1.0 / n)


def ema(x, n: int) -> np.ndarray:
    return _seed_recursive(x, n, 2.0 / (n + 1))


def rsi(close, n: int) -> np.ndarray:
    """Pine ta.rsi: Wilder's averages of the gains and losses; 100 when there is no loss, 0 when there is no gain."""
    c = np.asarray(close, float)
    ch = np.r_[np.nan, np.diff(c)]
    up = np.where(np.isfinite(ch), np.maximum(ch, 0.0), np.nan)
    dn = np.where(np.isfinite(ch), np.maximum(-ch, 0.0), np.nan)
    u, d = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(d == 0, 100.0, np.where(u == 0, 0.0, 100.0 - 100.0 / (1.0 + u / d)))
    out[~(np.isfinite(u) & np.isfinite(d))] = np.nan
    return out


def stdev(x, n: int) -> np.ndarray:
    """Pine ta.stdev (population): NaN while the window holds a NaN."""
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def zsq(x, n: int) -> np.ndarray:
    """tanh(x / stdev_n(x)) with x / sd clipped to +-10; 0 when the deviation is 0 or undefined (Pine: na > 0 is
    false); NaN where x itself is undefined (the caller's nz makes it 0)."""
    x = np.asarray(x, float)
    sd = stdev(x, n)
    pos = np.isfinite(sd) & (sd > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.tanh(np.clip(x / np.where(pos, sd, 1.0), -10, 10))
    out = np.where(pos, z, 0.0)
    out[~np.isfinite(x)] = np.nan
    return out


def roc(x, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    prev = np.r_[np.full(n, np.nan), x[:-n]]
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100.0 * (x - prev) / prev


def mom(x, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    return x - np.r_[np.full(n, np.nan), x[:-n]]


def atr(high, low, close, n: int = 14) -> np.ndarray:
    h, l, c = (np.asarray(a, float) for a in (high, low, close))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.where(np.isfinite(pc), np.maximum(h, pc) - np.minimum(l, pc), h - l)
    return rma(tr, n)


def _nz(x, d: float = 0.0) -> np.ndarray:
    x = np.asarray(x, float)
    return np.where(np.isfinite(x), x, d)


def avg_rsi(close) -> np.ndarray:
    """평균 RSI (BOT_FORMULAS 2-2): RSI 26, ROC 7, MOM 7, normalised over 100 bars, EMA 3."""
    c = np.asarray(close, float)
    rs = (_nz(rsi(c, 26), 50.0) - 50.0) / 50.0
    cs = _nz(zsq(roc(c, 7), 100))
    ms = _nz(zsq(mom(c, 7), 100))
    return ema(50.0 + 50.0 * (rs + cs + ms) / 3.0, 3)


def line_gold(close) -> np.ndarray:
    """보라 · 하늘색 선 (BOT_FORMULAS 2-3): True = cyan (golden, long side). The running sum's start does not matter
    once its EMA has settled."""
    c = np.asarray(close, float)
    score = ((_nz(rsi(c, 26), 50.0) - 50.0) / 50.0 + _nz(zsq(roc(c, 9), 100)) + _nz(zsq(mom(c, 10), 100))) / 3.0
    line = np.cumsum(score)
    sig = ema(line, 9)
    return np.where(np.isfinite(sig), line > sig, False)


def sma(x, n: int) -> np.ndarray:
    """Pine ta.sma: NaN while the window holds a NaN."""
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).mean().to_numpy()


def stoch_rsi(close, rsi_len: int = 14, stoch_len: int = 11, k_len: int = 4, d_len: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """TradingView 'Stoch RSI': k = sma(stoch(rsi, rsi, rsi, stoch_len), k_len), d = sma(k, d_len); NaN where the
    stochastic's range is 0 (Pine: x / 0 is na)."""
    r = rsi(close, rsi_len)
    s = pd.Series(r)
    lo = s.rolling(stoch_len, min_periods=stoch_len).min().to_numpy()
    hi = s.rolling(stoch_len, min_periods=stoch_len).max().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        st = np.where(hi > lo, 100.0 * (r - lo) / (hi - lo), np.nan)
    k = sma(st, k_len)
    return k, sma(k, d_len)


def supertrend(high, low, close, atr_len: int, factor: float) -> tuple[np.ndarray, np.ndarray]:
    """Pine v5 ta.supertrend(factor, atr_len), TradingView's built-in 'Supertrend': (line, up), up = True where
    TradingView's direction is -1 (the line under the price). The bands start from nz(...) = 0 as Pine's do."""
    h, l, c = (np.asarray(a, float) for a in (high, low, close))
    a = atr(h, l, c, atr_len)
    hl2 = (h + l) / 2.0
    n = len(c)
    line, up = np.full(n, np.nan), np.zeros(n, dtype=bool)
    lb_prev = ub_prev = st_prev = math.nan
    for i in range(n):
        lb, ub = hl2[i] - factor * a[i], hl2[i] + factor * a[i]
        pl = 0.0 if math.isnan(lb_prev) else lb_prev
        pu = 0.0 if math.isnan(ub_prev) else ub_prev
        c1 = c[i - 1] if i > 0 else math.nan
        lb = lb if (lb > pl or c1 < pl) else pl                      # comparisons with na are false
        ub = ub if (ub < pu or c1 > pu) else pu
        if i == 0 or math.isnan(a[i - 1]):
            d = 1
        elif st_prev == pu:
            d = -1 if c[i] > ub else 1
        else:
            d = 1 if c[i] < lb else -1
        st = lb if d == -1 else ub
        line[i], up[i] = st, d == -1
        lb_prev, ub_prev, st_prev = lb, ub, st
    return line, up


# ====================================================================== the decision at one 30m close
@dataclass
class Coin:
    symbol: str
    h1_buf: float
    sl_atr: float
    roe_act: float
    leverage: int
    enabled: bool = True


def bars_frame(rows: list, tf_ms: int, upto_ms: int) -> pd.DataFrame:
    """Binance kline rows -> bars CLOSED by ``upto_ms`` (open + tf <= upto), oldest first, one row per open time."""
    if not rows:
        return pd.DataFrame(columns=["open_ms", "open", "high", "low", "close"])
    df = pd.DataFrame([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows],
                      columns=["open_ms", "open", "high", "low", "close"])
    df = df[df.open_ms + tf_ms <= upto_ms].drop_duplicates("open_ms", keep="last").sort_values("open_ms")
    return df.reset_index(drop=True)


def evaluate(coin: Coin, b30: pd.DataFrame, b1h: pd.DataFrame, close_ms: int) -> dict:
    """The design's decision on the 30m bar closing at ``close_ms`` (b30 / b1h: closed bars only). Returns the values
    (for the log and the comparison with TradingView) and ``side`` = 1 / -1 / 0 with ``why`` when 0."""
    out = {"symbol": coin.symbol, "close_ms": int(close_ms), "side": 0, "why": "", "rule": "mix"}
    if b30.empty or int(b30.open_ms.iloc[-1]) + MIN30 != close_ms:
        out["why"] = "30분봉이 아직 없음"
        return out
    if len(b30) < 300 or len(b1h) < 300:
        out["why"] = "지난 봉이 모자람"
        return out
    c = b30.close.to_numpy(float)
    g = line_gold(c)
    ar = avg_rsi(c)
    at = atr(b30.high.to_numpy(float), b30.low.to_numpy(float), c, 14)
    t_ar = avg_rsi(b1h.close.to_numpy(float))
    h_close = b1h.open_ms.to_numpy(np.int64) + H1
    j = int(np.searchsorted(h_close, close_ms, side="right")) - 1     # the last 1h bar closed by this 30m close
    if j < 0 or int(h_close[j]) != close_ms // H1 * H1:
        out["why"] = "1시간봉이 아직 없음"
        return out
    to_cyan, to_purp = bool(g[-1] and not g[-2]), bool((not g[-1]) and g[-2])
    are, art = float(ar[-1]), (float(t_ar[j]) if np.isfinite(t_ar[j]) else 50.0)
    px, a = float(c[-1]), float(at[-1])
    dist = a * coin.sl_atr
    liq_ok = dist < px * (1.0 / coin.leverage - MMR_PCT / 100.0)
    out.update({"close": px, "gold": bool(g[-1]), "to_cyan": to_cyan, "to_purple": to_purp, "avg_rsi_30m": round(are, 2),
                "avg_rsi_1h": round(art, 2), "trend_close_ms": int(h_close[j]), "atr": a,
                "stop_dist": dist, "stop_pct": round(dist / px * 100, 3), "liq_ok": bool(liq_ok)})
    if not (to_cyan or to_purp):
        out["why"] = "색 변화 없음"
        return out
    if not coin.enabled:
        out["why"] = "이 코인 꺼짐"
        return out
    want = 1 if to_cyan else -1
    ok_e = are > 50 if want > 0 else are < 50
    ok_t = art > 50 - coin.h1_buf if want > 0 else art < 50 + coin.h1_buf
    if not (ok_e and ok_t):
        out["why"] = ("30분 평균 RSI " if not ok_e else "") + ("1시간 평균 RSI " if not ok_t else "") + "조건 안 맞음"
        return out
    if not liq_ok:
        out["why"] = f"손절 폭 {dist / px * 100:.2f}%가 {coin.leverage}배 청산가보다 멂"
        return out
    out["side"] = want
    return out


RULE_KO = {"mix": "친구 매매법", "st": "슈퍼트렌드·스톡RSI"}
RULES = tuple(RULE_KO)


def evaluate_st(coin: Coin, b30: pd.DataFrame, b1h: pd.DataFrame, close_ms: int) -> dict:
    """The owners' second rule (10-26, changed 10-27) on the 30m bar closing at ``close_ms`` (b30 / b1h: closed bars
    only): side = 1 / -1 / 0 with ``why`` when 0, and its values (the log, the message). Long = supertrend 14/3 and 14/6
    up, Stoch RSI ``ST_STOCH`` %K crossing above %D, RSI26 of the 30m and of the last closed 1h above 50, MOM(``ST_MOM``)
    of the 30m above 0; short = the mirror. Stop and liquidation guard as evaluate()."""
    out = {"symbol": coin.symbol, "close_ms": int(close_ms), "side": 0, "why": "", "rule": "st"}
    if b30.empty or int(b30.open_ms.iloc[-1]) + MIN30 != close_ms:
        out["why"] = "30분봉이 아직 없음"
        return out
    if len(b30) < 300 or len(b1h) < 300:
        out["why"] = "지난 봉이 모자람"
        return out
    h, l, c = (b30[k].to_numpy(float) for k in ("high", "low", "close"))
    h_close = b1h.open_ms.to_numpy(np.int64) + H1
    j = int(np.searchsorted(h_close, close_ms, side="right")) - 1     # the last 1h bar closed by this 30m close
    if j < 0 or int(h_close[j]) != close_ms // H1 * H1:
        out["why"] = "1시간봉이 아직 없음"
        return out
    _l3, up3 = supertrend(h, l, c, 14, 3.0)
    _l6, up6 = supertrend(h, l, c, 14, 6.0)
    k, d = stoch_rsi(c, *ST_STOCH)
    m30 = float(mom(c, ST_MOM)[-1])
    r30 = float(rsi(c, 26)[-1])
    r1h = float(rsi(b1h.close.to_numpy(float), 26)[j])
    at = float(atr(h, l, c, 14)[-1])
    px = float(c[-1])
    gold = bool(k[-1] > d[-1] and k[-2] <= d[-2])                     # NaN compares false: no cross
    dead = bool(k[-1] < d[-1] and k[-2] >= d[-2])
    dist = at * coin.sl_atr
    liq_ok = dist < px * (1.0 / coin.leverage - MMR_PCT / 100.0)
    rnd = lambda x: round(float(x), 2) if np.isfinite(x) else None   # noqa: E731
    out.update({"close": px, "st3_up": bool(up3[-1]), "st6_up": bool(up6[-1]), "k": rnd(k[-1]), "d": rnd(d[-1]),
                "cross": "gold" if gold else ("dead" if dead else ""), "rsi26_30m": rnd(r30), "rsi26_1h": rnd(r1h),
                "mom": float(f"{m30:.6g}") if np.isfinite(m30) else None,
                "trend_close_ms": int(h_close[j]), "atr": at, "stop_dist": dist, "stop_pct": round(dist / px * 100, 3),
                "liq_ok": bool(liq_ok)})
    if not (gold or dead):
        out["why"] = "스톡RSI 크로스 없음"
        return out
    if not coin.enabled:
        out["why"] = "이 코인 꺼짐"
        return out
    want = 1 if gold else -1
    miss = []
    if not (bool(up3[-1]) == (want > 0) and bool(up6[-1]) == (want > 0)):
        miss.append("슈퍼트렌드 14/3·14/6 " + ("상승" if want > 0 else "하락") + " 아님")
    if not (r30 > 50 if want > 0 else r30 < 50):
        miss.append("30분 RSI26")
    if not (r1h > 50 if want > 0 else r1h < 50):
        miss.append("1시간 RSI26")
    if not (m30 > 0 if want > 0 else m30 < 0):                      # NaN compares false: not met
        miss.append("30분 MOM")
    if miss:
        out["why"] = " · ".join(miss) + " 조건 안 맞음"
        return out
    if not liq_ok:
        out["why"] = f"손절 폭 {dist / px * 100:.2f}%가 {coin.leverage}배 청산가보다 멂"
        return out
    out["side"] = want
    return out


def ladder_stop(side: int, entry: float, best: float, stop: float, roe_act: float, lev: float,
                lock_roe: float = LOCK_ROE) -> tuple[float, int]:
    """BOT_FORMULAS 3: (new stop, step) after a 30m close; the stop never moves the unfavourable way. step 0 = not yet
    locked; k + 1 = the lock k steps past the first."""
    lock_d = entry * lock_roe / 100.0 / lev
    act_d = entry * roe_act / 100.0 / lev
    step_d = act_d - lock_d
    gain = side * (best - entry)
    if step_d <= 0 or gain < act_d:
        return stop, 0
    k = int(math.floor((gain - act_d) / step_d + 1e-12))
    new = entry + side * (lock_d + k * step_d)
    if (side > 0 and new > stop) or (side < 0 and new < stop):
        return new, k + 1
    return stop, -1                                 # reached, but no better than the stop already there


def net_ladder_stop(side: int, entry: float, best: float, stop: float, lev: float, trigger: float, lock: float,
                    step: float, fee: float) -> tuple[float, int]:
    """Owners 10-26: the ladder on NET ROE (% of the margin, the taker ``fee`` on both sides, at leverage ``lev``):
    best at ``trigger`` or more -> the stop at ``lock``, one ``step`` more for each further ``step`` reached (12 -> 10,
    17 -> 15, 22 -> 20 ...). The answers of ladder_stop: (new stop, step); step 0 = not yet, -1 = reached but no better
    than the stop already there; the stop never moves the unfavourable way."""
    roe = (side * (best - entry) / entry - 2 * fee) * lev * 100.0
    if roe < trigger - 1e-9:
        return stop, 0
    k = int(math.floor((roe - trigger) / step + 1e-9))
    new = entry * (1 + side * ((lock + step * k) / 100.0 / lev + 2 * fee))
    if (side > 0 and new > stop) or (side < 0 and new < stop):
        return new, k + 1
    return stop, -1


def reason_words(ev: dict, side: int, name: bool = False) -> str:
    """The entry's 근거 line: the friend's colour change and averaged RSIs, or the second rule's supertrends, Stoch RSI
    cross and RSI26s; ``name``: the rule's name first (two rules)."""
    head = f"근거({RULE_KO.get(ev.get('rule', 'mix'), '')}): " if name else "근거: "
    if ev.get("rule") == "st":
        return (head + f"슈퍼트렌드 14/3·14/6 {'상승' if side > 0 else '하락'} · 스톡RSI {'골든' if side > 0 else '데드'}크로스"
                f"(K {ev.get('k')} / D {ev.get('d')}) · RSI26 30분 {ev.get('rsi26_30m')} · 1시간 {ev.get('rsi26_1h')} "
                f"· MOM {ev.get('mom')} ({kst(ev['close_ms'])} 봉)")
    return (head + f"{'하늘색' if side > 0 else '보라색'}으로 바뀜 · 30분 평균 RSI {ev.get('avg_rsi_30m')} · 1시간 평균 RSI "
            f"{ev.get('avg_rsi_1h')} ({kst(ev['close_ms'])} 봉)")


def plan_words(c: "Config", short: bool = False) -> str:
    """The size and the ladder of a config in words (the start message, the site, the checks); ``short`` for a card."""
    if c.margin_frac > 0:
        size = f"증거금 잔고의 {c.margin_frac:.0%}" if short else f"진입마다 증거금 = 잔고의 {c.margin_frac:.0%}"
    else:
        size = f"손절 1번 잔고의 {c.risk_pct:g}%" if short else f"손절 1번 = 잔고의 {c.risk_pct:g}%"
    if c.ladder:
        t, lk, st = c.ladder["trigger"], c.ladder["lock"], c.ladder["step"]
        lad = (f"계단 {t:g}→{lk:g}·{t + st:g}→{lk + st:g}…" if short else
               f"계단 순ROE +{t:g}%→+{lk:g}%, +{t + st:g}%→+{lk + st:g}%, +{t + 2 * st:g}%→+{lk + 2 * st:g}% (그 뒤 {st:g}%마다)")
    else:
        lad = "계단 코인별" if short else "계단 코인별 ROE +roe_act%→+10%"
    every = "" if short or c.ladder_every_s <= 0 else f" · 손절·계단 {c.ladder_every_s:g}초마다(1분봉)"
    extra = ""
    if tuple(c.rules) != ("mix",):
        extra += " · 매매법 " + " + ".join(RULE_KO[r] for r in c.rules) + ("" if short or len(c.rules) < 2 else
                                                                           f"(같은 봉이면 {RULE_KO[c.rules[0]]} 먼저)")
    if c.stop_atr:
        extra += f" · 손절 ATR {c.stop_atr:g}배" + ("" if short else "(모든 코인)")
    return f"{size} · {lad}{every}{extra}"


# ====================================================================== config and state
@dataclass
class Config:
    mode: str                                   # "paper" | "mainnet"
    state: str                                  # the state file (JSON)
    log: str                                    # the decision / trade log (JSON lines)
    coins: list
    risk_pct: float = 0.25
    equity_floor_frac: float = 0.7
    start_equity: Optional[float] = None        # paper: the starting equity; mainnet: read at the first start
    kill_file: str = "/var/lib/paperbot/STOP"     # the shared emergency file (the executors close everything on it)
    own_stop_file: str = "/var/lib/paperbot/exec/mixchop.STOP"   # this bot only: no new entries
    max_notional_usd: float = 2000.0
    taker_fee: float = 0.00042                  # WOO X Pro's taker fee: paper charges it on both sides; ``ladder``'s net ROE
    telegram: bool = True
    binance_base: str = "https://fapi.binance.com"
    no_weekend: bool = False                    # entry blocks (owners' rules; off in the friend's design)
    us_open_pre_min: int = 0
    us_open_pause_min: int = 0
    macro_blackout_min: int = 0
    margin_frac: float = 0.0                    # > 0: each entry's margin = equity x this (owners 10-26); 0: risk_pct sizing
    ladder: Optional[dict] = None               # {"trigger", "lock", "step"} net ROE %; None: the coins' roe_act ladder
    ladder_every_s: float = 0.0                 # > 0: the open position on closed 1m bars this often between the closes
    rules: tuple = ("mix",)                     # the entry rules in their order (owners 10-26: ("mix", "st"))
    stop_atr: Optional[float] = None            # > 0: every coin's stop = ATR14 x this, both rules (owners 10-26: 3)

    @property
    def symbols(self) -> list:
        return [c.symbol for c in self.coins]


def load_config(path: str) -> Config:
    with open(path) as f:
        raw = json.load(f)
    mode = raw.get("mode")
    if mode not in ("paper", "mainnet"):
        raise MixError(f"\"mode\"는 \"paper\" 또는 \"mainnet\"이어야 합니다(지금 {mode!r})")
    coins = []
    for sym, v in (raw.get("coins") or {}).items():
        if not sym.endswith("USDT"):
            raise MixError(f"코인 이름은 BTCUSDT 꼴이어야 합니다: {sym!r}")
        base = dict(DEFAULT_COINS.get(sym, {}))
        base.update({k: v[k] for k in ("h1_buf", "sl_atr", "roe_act", "leverage") if k in v})
        missing = [k for k in ("h1_buf", "sl_atr", "roe_act", "leverage") if k not in base]
        if missing:
            raise MixError(f"{sym}: 설정 {missing}이 없습니다")
        co = Coin(sym, float(base["h1_buf"]), float(base["sl_atr"]), float(base["roe_act"]), int(base["leverage"]),
                  bool(v.get("enabled", True)))
        if not (0 <= co.h1_buf <= 50 and 0.3 <= co.sl_atr <= 10 and LOCK_ROE < co.roe_act <= 1000 and 1 <= co.leverage <= 50):
            raise MixError(f"{sym}: 설정 값이 범위 밖입니다 {asdict(co)}")
        coins.append(co)
    if not coins:
        raise MixError("\"coins\"가 비어 있습니다")
    cfg = Config(mode=mode, state=raw.get("state") or "", log=raw.get("log") or "", coins=coins,
                 risk_pct=float(raw.get("risk_pct", 0.25)), equity_floor_frac=float(raw.get("equity_floor_frac", 0.7)),
                 start_equity=raw.get("start_equity"), kill_file=raw.get("kill_file", "/var/lib/paperbot/STOP"),
                 own_stop_file=raw.get("own_stop_file", "/var/lib/paperbot/exec/mixchop.STOP"),
                 max_notional_usd=float(raw.get("max_notional_usd", 2000.0)),
                 taker_fee=float(raw.get("taker_fee", 0.00042)), telegram=bool(raw.get("telegram", True)),
                 binance_base=raw.get("binance_base", "https://fapi.binance.com"),
                 no_weekend=bool(raw.get("no_weekend", False)), us_open_pre_min=int(raw.get("us_open_pre_min", 0)),
                 us_open_pause_min=int(raw.get("us_open_pause_min", 0)), macro_blackout_min=int(raw.get("macro_blackout_min", 0)),
                 margin_frac=float(raw.get("margin_frac", 0) or 0), ladder_every_s=float(raw.get("ladder_every_s", 0) or 0))
    lad = raw.get("ladder")
    if lad is not None:
        try:
            cfg.ladder = {k: float(lad[k]) for k in ("trigger", "lock", "step")}
        except (TypeError, KeyError, ValueError):
            raise MixError("\"ladder\"는 {\"trigger\": 12, \"lock\": 10, \"step\": 5} 꼴이어야 합니다(순ROE %)") from None
        t, lk, st = cfg.ladder["trigger"], cfg.ladder["lock"], cfg.ladder["step"]
        if not (0 < lk < t <= 1000 and 0 < st <= 1000):
            raise MixError(f"\"ladder\" 값이 범위 밖입니다(0 < lock < trigger <= 1000, 0 < step): {cfg.ladder}")
    if not (0 <= cfg.margin_frac <= 1):
        raise MixError(f"\"margin_frac\"는 0 ~ 1 사이여야 합니다(지금 {cfg.margin_frac})")
    if not (cfg.ladder_every_s == 0 or 30 <= cfg.ladder_every_s <= 600):
        raise MixError(f"\"ladder_every_s\"는 0(끔) 또는 30 ~ 600초여야 합니다(지금 {cfg.ladder_every_s})")
    rules = raw.get("rules", ["mix"])
    if (not isinstance(rules, list) or not rules or len(set(rules)) != len(rules)
            or any(r not in RULES for r in rules)):
        raise MixError(f"\"rules\"는 {list(RULES)} 중에서 고른 목록이어야 합니다(앞의 것이 먼저, 지금 {rules!r})")
    cfg.rules = tuple(rules)
    sa = raw.get("stop_atr")
    if sa is not None:
        if isinstance(sa, bool) or not isinstance(sa, (int, float)) or not 0.3 <= sa <= 10:
            raise MixError(f"\"stop_atr\"는 0.3 ~ 10(ATR 배수) 또는 null이어야 합니다(지금 {sa!r})")
        cfg.stop_atr = float(sa)
        for co in cfg.coins:                     # both rules read the coin's multiple
            co.sl_atr = float(sa)
    if not cfg.state or not cfg.log:
        raise MixError("\"state\"와 \"log\" 파일 경로가 필요합니다")
    if not (0 < cfg.risk_pct <= 5):
        raise MixError(f"\"risk_pct\"는 0 ~ 5(%) 사이여야 합니다(지금 {cfg.risk_pct})")
    if not (0 <= cfg.equity_floor_frac < 1):
        raise MixError("\"equity_floor_frac\"는 0 이상 1 미만이어야 합니다")
    if not all(0 <= m <= 240 for m in (cfg.us_open_pre_min, cfg.us_open_pause_min, cfg.macro_blackout_min)):
        raise MixError("진입 금지 분(us_open_pre_min, us_open_pause_min, macro_blackout_min)은 0 ~ 240이어야 합니다")
    if cfg.binance_base.rstrip("/") != "https://fapi.binance.com":
        raise MixError("신호 캔들은 바이낸스 USDT 선물(https://fapi.binance.com)에서만 읽습니다")
    return cfg


@dataclass
class Position:
    symbol: str
    side: int
    qty: float
    entry: float
    stop_dist: float
    stop: float
    best: float
    step: int
    opened_ms: int
    signal_close_ms: int
    signal_close: float
    last_bar_ms: int                            # the end of the last bar (30m, or 1m with ladder_every_s) used for best / the ladder
    stop_id: Optional[str] = None
    equity_before: Optional[float] = None
    leverage: int = 40
    roe_act: float = 150.0

    def roe(self, px: float) -> float:
        return self.side * (px - self.entry) / self.entry * self.leverage * 100.0


def read_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def write_state(path: str, st: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def kst(ms: int) -> str:
    return time.strftime("%m/%d %H:%M", time.gmtime((int(ms) + KST_MS) / 1000))


def entry_block(cfg: "Config", ts: int) -> str:
    """"" or why an entry in minute ``ts`` (ms) is not made: weekend (KST), the NYSE open window, a US release."""
    if cfg.no_weekend and ((int(ts) + 9 * 3_600_000) // 86_400_000 + 3) % 7 >= 5:   # 1970-01-01 was a Thursday
        return "주말(한국 시간 토·일) 진입 안 함"
    if cfg.us_open_pre_min or cfg.us_open_pause_min:
        from datetime import datetime, timezone
        from .sessions import NY, NYSE_HOLIDAYS
        local = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).astimezone(NY)
        if local.weekday() < 5 and local.strftime("%Y-%m-%d") not in NYSE_HOLIDAYS:
            since = (local - local.replace(hour=9, minute=30, second=0, microsecond=0)).total_seconds()
            if -cfg.us_open_pre_min * 60 <= since < cfg.us_open_pause_min * 60:
                return f"나스닥 개장 앞 {cfg.us_open_pre_min}분·뒤 {cfg.us_open_pause_min}분 진입 안 함 (뉴욕 09:30 개장)"
    if cfg.macro_blackout_min:
        from . import events as EV
        w = cfg.macro_blackout_min * 60_000
        near = EV.near(int(ts), w, w)
        if near:
            e = near[0]
            return f"경제 발표 앞뒤 {cfg.macro_blackout_min}분 진입 안 함: {EV.KIND_KO.get(e.kind, e.kind)} {e.ts_utc}"
    return ""


def coin_ko(symbol: str) -> str:
    return symbol.replace("USDT", "")


# ====================================================================== brokers
class PaperBroker:
    """Trades nothing: fills at the signal close, exits on the 30m bars like the indicator (stop price, or the open
    when the bar opens past it), fees ``taker_fee`` on both sides."""
    live = False

    def __init__(self, equity: float, fee: float, spec_fn: Optional[Callable[[str], dict]] = None):
        self.eq = float(equity)
        self.fee = float(fee)
        self.pos: dict = {}                     # symbol -> signed qty
        self.spec_fn = spec_fn                  # WOO X Pro's public contract sizes, so paper skips what live skips
        self._specs: dict = {}

    def equity(self) -> float:
        return self.eq

    def foreign_positions(self, mine: Optional[str]) -> list:
        return []

    def setup(self, coins) -> list:
        return [(True, "모의: 거래소 설정 없음")]

    def spec(self, symbol: str) -> dict:
        if self.spec_fn is not None and symbol not in self._specs:
            try:
                self._specs[symbol] = dict(self.spec_fn(symbol))
            except Exception:
                pass
        return self._specs.get(symbol) or {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": 0.0}

    def restore(self, p: "Position") -> None:
        self.pos[p.symbol] = p.side * p.qty

    def open(self, symbol: str, side: int, qty: float, ref: float, lev: int) -> tuple[float, float]:
        self.pos[symbol] = side * qty
        self.eq -= qty * ref * self.fee
        return ref, qty

    def place_stop(self, symbol: str, side: int, price: float, qty: float) -> Optional[str]:
        return "paper"

    def move_stop(self, symbol: str, side: int, price: float, qty: float, old_id) -> tuple[str, Optional[str]]:
        return "moved", "paper"

    def is_open(self, symbol: str) -> Optional[bool]:
        return symbol in self.pos

    def stop_ok(self, symbol: str, qty: float) -> bool:
        return True

    def close_market(self, symbol: str, side: int, qty: float) -> None:
        self.pos.pop(symbol, None)

    def paper_exit(self, p: Position, px: float) -> float:
        pnl = p.side * (px - p.entry) * p.qty - p.qty * px * self.fee
        self.eq += pnl
        self.pos.pop(p.symbol, None)
        return pnl


class WooBroker:
    """WOO X Pro, the second account (keys in its own root-only file). Every order and stop goes through
    paperbot/wooxpro.py's client and the shared stop protocol (place -> confirmed resting; move = new one confirmed,
    then the old one cancelled)."""
    live = True

    def __init__(self, client, coins):
        from . import testnet as TN
        self.c = client
        self.TN = TN
        self.coins = {c.symbol: c for c in coins}

    def equity(self) -> float:
        a = self.c.account()
        return float(a["totalMarginBalance"])

    def foreign_positions(self, mine: Optional[str]) -> list:
        """Every open position on the account except the bot's own (symbol, signed qty)."""
        out = []
        for p in self.c.positions():
            amt = float(p.get("positionAmt") or 0)
            if amt != 0 and p.get("symbol") != mine:
                out.append((p.get("symbol"), amt))
        return out

    def setup(self, coins) -> list:
        """One-way mode, then each coin isolated at its leverage (read back). Lines (ok, text)."""
        out = []
        self.c.one_way()
        out.append((True, "포지션 모드: 단방향"))
        for co in coins:
            try:
                self.c.leverage(co.symbol, co.leverage)
                out.append((True, f"{co.symbol}: 격리 {co.leverage}배"))
            except Exception as e:                       # a coin that cannot be set is not traded
                out.append((False, f"{co.symbol}: 레버리지를 못 맞춤 ({e})"))
        return out

    def spec(self, symbol: str) -> dict:
        return self.c.spec(symbol)

    def open(self, symbol: str, side: int, qty: float, ref: float, lev: int) -> tuple[float, float]:
        self.c.leverage(symbol, lev)
        o = self.c.market(symbol, "BUY" if side > 0 else "SELL", qty,
                          client_id=f"mx{uuid.uuid4().hex[:20]}")
        filled = float(o.get("executedQty") or 0)
        px = float(o.get("avgPrice") or 0)
        try:                                             # the position is the truth (the answer may be a partial fill)
            pos = self.c.position(symbol)
            amt = float(pos.get("positionAmt") or 0)
            if amt * side > 0:
                filled = max(filled, abs(amt))
                px = px or float(pos.get("entryPrice") or 0)
        except Exception:
            pass
        return px or ref, filled

    def place_stop(self, symbol: str, side: int, price: float, qty: float) -> Optional[str]:
        sp = self.c.spec(symbol)
        trig = self.TN.round_stop(price, float(sp["tick"]), side)
        o = self.TN.place_stop(self.c, symbol, "SELL" if side > 0 else "BUY", trig, qty,
                               client_id=f"ms{uuid.uuid4().hex[:20]}")
        return str(o.get("algoId") or "")

    def move_stop(self, symbol: str, side: int, price: float, qty: float, old_id) -> tuple[str, Optional[str]]:
        sp = self.c.spec(symbol)
        trig = self.TN.round_stop(price, float(sp["tick"]), side)
        olds = [old_id] if old_id else [o.get("algoId") for o in self.TN.live_stops(self.c, symbol)]
        r = self.TN.move_stop(self.c, symbol, "SELL" if side > 0 else "BUY", trig, qty, olds,
                              client_id=f"ms{uuid.uuid4().hex[:20]}", close_id=f"mc{uuid.uuid4().hex[:20]}")
        if r.get("result") == "moved":
            new = r.get("stop") or {}
            return "moved", str(new.get("algoId") or "")
        return str(r.get("result") or "?"), None

    def is_open(self, symbol: str) -> Optional[bool]:
        amt = float(self.c.position(symbol)["positionAmt"])
        return amt != 0

    def amount(self, symbol: str) -> float:
        """The signed position size on the exchange."""
        return float(self.c.position(symbol)["positionAmt"])

    def liq_room(self, symbol: str, notional: float, lev: int) -> Optional[float]:
        """How far (a fraction of the price) a ``notional`` position at ``lev`` is from WOO X Pro's liquidation, less
        LIQ_ROOM; None when the brackets cannot be read."""
        try:
            mmr = self.c.maint_margin_ratio(symbol, notional)
        except Exception:
            return None
        return -1.0 if mmr is None else 1.0 / float(lev) - float(mmr) - LIQ_ROOM

    def stop_ok(self, symbol: str, qty: float) -> bool:
        amt = float(self.c.position(symbol)["positionAmt"])
        return any(self.TN.covers(o, amt) for o in self.TN.live_stops(self.c, symbol))

    def close_market(self, symbol: str, side: int, qty: float) -> None:
        self.c.market(symbol, "SELL" if side > 0 else "BUY", qty, reduce_only=True,
                      client_id=f"mc{uuid.uuid4().hex[:20]}")

    def cancel_stops(self, symbol: str) -> None:
        self.c.cancel_all_algo(symbol)


# ====================================================================== the bot
def _not_read(ev: dict) -> bool:
    """An answer that could not be made from the bars (not there yet, or not read): tried again, then logged."""
    return ev["why"].endswith("아직 없음") or ev["why"].startswith("캔들 읽기 실패")


class Bot:
    def __init__(self, cfg: Config, broker, fetch: Callable[[str, str, int], list], clock_ms: Callable[[], int],
                 notify: Optional[Callable[[str, str], None]] = None, sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.b, self.fetch, self.now, self.sleep = cfg, broker, fetch, clock_ms, sleep
        self.notify = notify or (lambda level, text: None)
        self.coins = {c.symbol: c for c in cfg.coins}
        st = read_state(cfg.state)
        self.pos: Optional[Position] = Position(**st["position"]) if st.get("position") else None
        self.start_equity = st.get("start_equity") or cfg.start_equity
        self.last_close_ms = int(st.get("last_close_ms") or 0)
        self.halt_reason = ""
        self.stop = False
        self._last_stop_check = 0.0
        self._flat_reads = 0
        self._unprotected = False               # live: open without a confirmed stop -> poll() works on it every POLL_S
        self._said: dict = {}                   # alert key -> monotonic time last sent (repeats at most ALERT_EVERY_S)
        self._entry_try: Optional[tuple] = None  # (symbol, side, until_ms, ref, dist): an entry whose fill was not seen
        self._unknown_told = ""                  # the unknown positions last told (coins)
        self._last_minute_ms = 0                 # ladder_every_s: when the open position was last followed on 1m bars

    # ---------------------------------------------------------------- persistence and log
    def save(self) -> None:
        write_state(self.cfg.state, {"position": asdict(self.pos) if self.pos else None, "start_equity": self.start_equity,
                                     "last_close_ms": self.last_close_ms, "saved_ms": self.now(), "mode": self.cfg.mode})

    def log(self, kind: str, **kv) -> None:
        row = {"ts": self.now(), "kind": kind, **kv}
        with open(self.cfg.log, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=float) + "\n")

    def say(self, level: str, text: str) -> None:
        prefix = f"[{NAME}{' 모의' if not self.b.live else ''}] "
        try:
            self.notify(level, prefix + text)
        except Exception:
            pass

    def say_once(self, key: str, level: str, text: str) -> None:
        """An alert that may come every POLL_S (still no stop, an unknown position): at most every ALERT_EVERY_S."""
        t = time.monotonic()
        if key in self._said and t - self._said[key] < ALERT_EVERY_S:
            return
        self._said[key] = t
        self.say(level, text)

    # ---------------------------------------------------------------- bars
    def bars(self, symbol: str, close_ms: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        r30 = self.fetch(symbol, "30m", BARS)
        if not any(int(r[0]) >= close_ms for r in r30[-3:]):     # Binance has not opened the next bar: not closed there
            raise MixError("바이낸스에서 30분봉 마감이 아직 없음")
        b30 = bars_frame(r30, MIN30, close_ms)
        b1h = bars_frame(self.fetch(symbol, "1h", BARS), H1, close_ms)
        return b30, b1h

    # ---------------------------------------------------------------- start
    def start(self) -> None:
        eq = self.b.equity()
        if not self.start_equity:
            self.start_equity = eq
        lines = self.b.setup(self.cfg.coins)
        bad = [t for ok, t in lines if not ok]
        for co in self.cfg.coins:
            if any(co.symbol in t for t in bad):
                co.enabled = False
        problem = ""
        if self.pos is not None:
            problem = self.reconcile_open()
        self.save()
        coins = " · ".join(f"{coin_ko(c.symbol)}{'' if c.enabled else '(꺼짐)'}" for c in self.cfg.coins)
        held = f"\n보유 중: {coin_ko(self.pos.symbol)} {'롱' if self.pos.side > 0 else '숏'} 손절 {self.pos.stop:.6g}" \
            if self.pos else ""
        self.say("INFO", f"▶️ 시작 · 잔고 ${eq:,.2f} (시작 잔고 ${self.start_equity:,.2f})\n코인 {coins}\n"
                         f"{self.plan_text()} · 한 번에 1포지션 · 30분봉 마감마다 판단{held}"
                 + ("".join(f"\n⚠ {t}" for t in bad)))
        self.log("start", equity=eq, start_equity=self.start_equity, setup=lines, position=asdict(self.pos) if self.pos else None)
        if problem:
            self.say("CRITICAL", problem)
        if self.b.live:
            self.check_unknown()

    def reconcile_open(self) -> str:
        """The saved position against the exchange (live) / back into the paper broker. A problem text, or ""."""
        p = self.pos
        if not self.b.live:
            self.b.restore(p)
            return ""
        try:
            self.protect("closed_while_down", "다시 켜면서")
        except Exception as e:
            self.log("reconcile_failed", symbol=p.symbol, error=str(e))
            self._unprotected = True
            return f"🚨 다시 켜면서 {coin_ko(p.symbol)} 포지션·손절을 확인하지 못했습니다: {e}\n봇이 15초마다 다시 해 봅니다. 거래소에서 확인하세요"
        return ""

    def plan_text(self) -> str:
        """The size and the ladder in words (start message)."""
        return plan_words(self.cfg)

    def ladder_for(self, p: "Position") -> tuple[float, int]:
        """(new stop, step) for the position's best: the config's net-ROE ladder, else the coin's roe_act ladder."""
        lad = self.cfg.ladder
        if lad:
            return net_ladder_stop(p.side, p.entry, p.best, p.stop, p.leverage, lad["trigger"], lad["lock"], lad["step"],
                                   self.cfg.taker_fee)
        return ladder_stop(p.side, p.entry, p.best, p.stop, p.roe_act, p.leverage)

    def roe_text(self, p: "Position", px: float) -> str:
        if self.cfg.ladder:
            return f"순ROE {(p.side * (px - p.entry) / p.entry - 2 * self.cfg.taker_fee) * p.leverage * 100:+.1f}%"
        return f"ROE {p.roe(px):+.1f}%"

    # ---------------------------------------------------------------- protection (live)
    def protect(self, flat_why: str, where: str) -> None:
        """The open position must rest under a stop for all of it. The exchange's size and side are the truth: a
        different size is adopted, a wrong side is closed. A missing or short stop is placed again (new one first,
        then the old ones cancelled); one that cannot be placed closes the position at market (the design: no position
        without a stop). Actions first, alerts after. Raises when the exchange cannot be read."""
        p = self.pos
        amt = self.b.amount(p.symbol)
        if amt == 0:
            if self.confirm_flat(p.symbol):
                self._unprotected = False
                self.finish(p, None, flat_why)
            else:                                       # the two reads disagree: not known to be protected
                self._unprotected = True
            return
        s = 1 if amt > 0 else -1
        if s != p.side:                                 # never protect a side the bot did not open: close it
            self.b.close_market(p.symbol, s, abs(amt))
            p.side, p.qty = s, abs(amt)
            if self.b.is_open(p.symbol) is False and self.confirm_flat(p.symbol):
                self._unprotected = False
                self.finish(p, None, "wrong_side")
            else:
                self._unprotected = True
            self.say("CRITICAL", f"🚨 {where} {coin_ko(p.symbol)} 포지션 방향이 봇 기록과 달라 시장가로 닫았습니다 ({amt:g})")
            return
        if abs(abs(amt) - p.qty) > 1e-12:
            self.log("qty_adopted", symbol=p.symbol, old=p.qty, new=abs(amt))
            p.qty = abs(amt)
            self.save()
        if self.b.stop_ok(p.symbol, p.qty):
            self._unprotected = False
            return
        try:
            res, sid = self.b.move_stop(p.symbol, p.side, p.stop, p.qty, None)
            err = ""
        except Exception as e:
            res, sid, err = "error", None, str(e)
        if res == "moved":
            p.stop_id = sid
            self._unprotected = False
            self.save()
            self.log("stop_replaced", symbol=p.symbol, stop=p.stop, qty=p.qty, where=where)
            self.say("WARN", f"⚠ {where} {coin_ko(p.symbol)} 손절이 없거나 모자라 다시 걸었습니다 ({p.stop:.6g}, {p.qty:g}개)")
            return
        self.log("stop_failed", symbol=p.symbol, result=res, error=err, where=where)
        if res not in ("closed", "triggered"):          # could not be placed: close at market
            try:
                self.b.close_market(p.symbol, p.side, p.qty)
            except Exception as e2:
                self.log("protect_close_failed", symbol=p.symbol, error=str(e2))
        if self.b.is_open(p.symbol) is False and self.confirm_flat(p.symbol):
            self._unprotected = False
            self.finish(p, None, "protect" if res not in ("closed", "triggered") else ("ladder" if p.step > 0 else "stop"))
            if res not in ("closed", "triggered"):
                self.say("CRITICAL", f"🚨 {where} {coin_ko(p.symbol)} 손절을 다시 못 걸어 시장가로 닫았습니다: {err}")
            return
        self._unprotected = True
        self.say_once("unprotected", "CRITICAL", f"🚨 {coin_ko(p.symbol)} 포지션이 열려 있고 손절이 없습니다 ({err or res}). "
                                                 f"봇이 15초마다 손절·청산을 다시 해 봅니다. 거래소에서 바로 확인하세요")

    def check_unknown(self) -> None:
        """Flat by its own record: a position on one of its coins right after an entry it could not see filled is its
        own (adopted, stopped); any other position is told once (it blocks entries, halts())."""
        try:
            other = self.b.foreign_positions(self.pos.symbol if self.pos else None)
        except Exception as e:
            self.log("read_failed", error=str(e))
            return
        if not other:
            self._unknown_told = ""
            return
        et = self._entry_try
        if self.pos is None and et and self.now() <= et[2]:
            for sym, amt in other:
                if sym == et[0] and amt * et[1] > 0:
                    self._entry_try = None
                    self.adopt(sym, et[3], et[4], self.coins[sym])
                    return
        self.tell_unknown(other)

    def tell_unknown(self, other: list) -> None:
        """Positions the bot does not know (they block entries): told once per set of coins, again when it changes."""
        key = ",".join(sorted(sym for sym, _ in other))
        if key == self._unknown_told:
            return
        self._unknown_told = key
        self.say("CRITICAL", "🚨 봇이 모르는 포지션이 있습니다: " + ", ".join(f"{s} {q:g}" for s, q in other)
                 + "\n새 진입을 멈춥니다. 거래소에서 확인하고 직접 정리하세요")

    # ---------------------------------------------------------------- every 30m close
    def on_close(self, close_ms: int) -> None:
        if self.pos is not None:
            self.manage(close_ms)
        self.halt_reason = self.halts()
        cands = []
        for co in self.cfg.coins:
            for attempt in range(3):
                try:
                    b30, b1h = self.bars(co.symbol, close_ms)
                    evs = [self.judge(rule, co, b30, b1h, close_ms) for rule in self.cfg.rules]
                except Exception as e:
                    evs = [{"symbol": co.symbol, "close_ms": close_ms, "side": 0, "why": f"캔들 읽기 실패: {e}"}]
                if not any(_not_read(ev) for ev in evs):
                    break
                self.sleep(3.0)
            for ev in evs:
                if _not_read(ev):
                    self.log("bars_missing", **ev)
                if ev.get("to_cyan") or ev.get("to_purple") or ev.get("cross") or ev["side"]:
                    self.log("signal", **ev)
            ev = next((e for e in evs if e["side"]), None)          # the config's rule order decides on one coin
            if ev is not None:
                cands.append((co, ev))
        self.last_close_ms = close_ms
        self.save()
        if not cands:
            return
        block = entry_block(self.cfg, self.now()) if self.pos is None and not self.halt_reason else ""
        if self.pos is not None or self.halt_reason or block:
            for co, ev in cands:
                why = "보유 중" if self.pos is not None else (self.halt_reason or block)
                self.log("skip", symbol=co.symbol, side=ev["side"], why=why, rule=ev.get("rule", "mix"))
            return
        co, ev = cands[0]                               # the config's coin order decides between coins
        for other, oev in cands[1:]:
            self.log("skip", symbol=other.symbol, side=oev["side"], why=f"같은 봉에 {coin_ko(co.symbol)} 먼저",
                     rule=oev.get("rule", "mix"))
        self.enter(co, ev)

    @staticmethod
    def judge(rule: str, co: Coin, b30: pd.DataFrame, b1h: pd.DataFrame, close_ms: int) -> dict:
        """One entry rule's answer at this close (``rule``: "mix" the friend's, "st" the owners' second)."""
        return evaluate(co, b30, b1h, close_ms) if rule == "mix" else evaluate_st(co, b30, b1h, close_ms)

    def halts(self) -> str:
        for f in (self.cfg.kill_file, self.cfg.own_stop_file):
            if f and os.path.exists(f):
                return f"정지 파일({f})"
        try:
            eq = self.b.equity()
        except Exception as e:
            return f"잔고를 못 읽음({e})"
        if self.start_equity and eq < self.start_equity * self.cfg.equity_floor_frac:
            return f"잔고 ${eq:,.2f}가 시작 잔고의 {self.cfg.equity_floor_frac:.0%} 아래"
        try:
            other = self.b.foreign_positions(self.pos.symbol if self.pos else None)
        except Exception as e:
            return f"포지션을 못 읽음({e})"
        et = self._entry_try
        if other and self.pos is None and et and self.now() <= et[2] and all(sym == et[0] for sym, _ in other):
            return "진입 체결 확인 중"                    # poll() adopts it (check_unknown)
        if other:
            self.tell_unknown(other)
            return "봇이 모르는 포지션: " + ", ".join(f"{s} {q:g}" for s, q in other)
        return ""

    # ---------------------------------------------------------------- entry
    def enter(self, co: Coin, ev: dict) -> None:
        sym, side = co.symbol, ev["side"]
        eq = self.b.equity()
        dist = float(ev["stop_dist"])
        ref = float(ev["close"])
        if self.cfg.margin_frac > 0:                    # owners 10-26: margin = equity x margin_frac
            qty = eq * self.cfg.margin_frac * co.leverage / ref
        else:
            qty = eq * self.cfg.risk_pct / 100.0 / dist
        if qty * ref > self.cfg.max_notional_usd:
            qty = self.cfg.max_notional_usd / ref
        sp = self.b.spec(sym)
        if sp.get("qty_step"):
            qty = math.floor(qty / float(sp["qty_step"]) + 1e-9) * float(sp["qty_step"])
        need = max(float(sp.get("min_qty") or 0), float(sp.get("min_notional") or 0) / ref)
        risk = qty * dist                               # the loss at the stop (fees aside)
        if qty <= 0 or qty + 1e-12 < need:
            self.log("skip", symbol=sym, side=side, why="최소 주문보다 작음", qty=qty, need=need, equity=eq,
                     rule=ev.get("rule", "mix"))
            self.say("WARN", f"⚠ {coin_ko(sym)} {'롱' if side > 0 else '숏'} 신호를 건너뜀: 크기 {qty:g}가 최소 {need:g}보다 작음 "
                             f"(손절 1번 ${risk:.3f}, 손절 폭 {ev['stop_pct']}%)")
            return
        if self.b.live:                                 # WOO X Pro's own liquidation, from its brackets
            room = self.b.liq_room(sym, qty * ref, co.leverage)
            if room is not None and dist / ref >= room:
                self.log("skip", symbol=sym, side=side, why="손절이 WOO X Pro 청산가에 너무 가까움", stop_frac=dist / ref, room=room,
                         rule=ev.get("rule", "mix"))
                self.say("WARN", f"⚠ {coin_ko(sym)} {'롱' if side > 0 else '숏'} 신호를 건너뜀: 손절 폭 {dist / ref:.2%}가 "
                                 f"WOO X Pro 청산까지({max(room, 0):.2%}, 여유 {LIQ_ROOM:.1%} 뺌)보다 멂")
                return
        self._entry_try = (sym, side, self.now() + ADOPT_WINDOW_MS, ref, dist)
        try:
            fill, filled = self.b.open(sym, side, qty, ref, co.leverage)
        except Exception as e:
            self.log("entry_failed", symbol=sym, side=side, error=str(e))
            if not self.b.live or not self.look_for_fill(sym, side, ref, dist, co):
                self.say("CRITICAL", f"🚨 {coin_ko(sym)} 진입 주문 결과를 모릅니다: {e}\n포지션이 생기면 봇이 10분 안에는 "
                                     f"찾아서 손절을 겁니다. 거래소에서도 확인하세요")
            return
        if filled <= 0:
            self.log("entry_none", symbol=sym, side=side)
            if not self.b.live or not self.look_for_fill(sym, side, ref, dist, co):
                self.say("WARN", f"⚠ {coin_ko(sym)} 진입 주문이 체결된 것이 안 보입니다. 10분 동안 계속 살펴봅니다")
            return
        self._entry_try = None
        stop = fill - side * dist
        p = Position(symbol=sym, side=side, qty=filled, entry=fill, stop_dist=dist, stop=stop, best=fill, step=0,
                     opened_ms=self.now(), signal_close_ms=int(ev["close_ms"]), signal_close=ref,
                     last_bar_ms=int(ev["close_ms"]), equity_before=eq, leverage=co.leverage, roe_act=co.roe_act)
        self.pos = p
        self.save()
        try:
            p.stop_id = self.b.place_stop(sym, side, stop, filled)
        except Exception as e:
            self.log("stop_failed", symbol=sym, error=str(e), where="entry")
            try:
                self.protect("protect", "진입 직후")        # one more try (new stop), else closed at market
            except Exception as e2:
                self.log("protect_failed", symbol=sym, error=str(e2))
                self._unprotected = True
                self.say_once("unprotected", "CRITICAL", f"🚨 {coin_ko(sym)} 진입 뒤 손절을 못 걸었고 거래소도 못 읽습니다: {e2}\n"
                                                         f"봇이 15초마다 다시 해 봅니다. 거래소에서 바로 확인하세요")
            if self.pos is not p:                       # closed at market (finish() told it)
                return
            filled, stop = p.qty, p.stop
        self.save()
        self.log("entry", **asdict(p), why=ev)
        lad = self.cfg.ladder
        if lad:
            fee2 = 2 * self.cfg.taker_fee
            act_px = fill * (1 + side * (lad["trigger"] / 100 / co.leverage + fee2))
            lock_px = fill * (1 + side * (lad["lock"] / 100 / co.leverage + fee2))
            ladder_line = (f"계단: {act_px:.6g}(순ROE +{lad['trigger']:g}%) 가면 손절을 {lock_px:.6g}(순ROE +{lad['lock']:g}%)로, "
                           f"그 뒤 {lad['step']:g}%마다 한 칸")
        else:
            lock_px = fill + side * fill * LOCK_ROE / 100 / co.leverage
            act_px = fill + side * fill * co.roe_act / 100 / co.leverage
            ladder_line = (f"계단: {act_px:.6g}(ROE +{co.roe_act:.0f}%) 가면 손절을 {lock_px:.6g}(ROE +{LOCK_ROE:.0f}%)로")
        loss_pct = filled * dist / eq * 100 if eq else 0.0
        size_words = (f"증거금 잔고의 {self.cfg.margin_frac:.0%}, 손절 1번 약 잔고의 {loss_pct:.1f}%" if self.cfg.margin_frac > 0
                      else f"잔고의 {self.cfg.risk_pct}%")
        self.say("CRITICAL" if self._unprotected else "INFO",
                 ("🚨 손절을 아직 확인하지 못했습니다. 봇이 15초마다 다시 겁니다. 거래소에서 확인하세요\n" if self._unprotected else "")
                 + f"{'🟢' if side > 0 else '🔴'} {coin_ko(sym)} {'롱' if side > 0 else '숏'} 진입 {fill:.6g} ({co.leverage}배, "
                         f"{filled:g}개 ≈ ${filled * fill:,.2f})\n손절 {stop:.6g} (ROE −{dist / fill * co.leverage * 100:.1f}%, "
                         f"{size_words})\n{ladder_line}\n{reason_words(ev, side, len(self.cfg.rules) > 1)}")

    def look_for_fill(self, sym: str, side: int, ref: float, dist: float, co: Coin) -> bool:
        """An entry whose answer was lost or empty: read the position a few times; adopt it if it is there."""
        for i in range(3):
            try:
                amt = self.b.amount(sym)
            except Exception as e:
                self.log("read_failed", symbol=sym, error=str(e))
                amt = 0.0
            if amt * side > 0:
                self._entry_try = None
                self.adopt(sym, ref, dist, co)
                return True
            self.sleep(2.0)
        return False

    def adopt(self, sym: str, ref: float, dist: float, co: Coin) -> None:
        """A position of the bot's own entry that it did not see filled: the design's stop from its entry price."""
        pos = self.b.c.position(sym)
        amt = float(pos.get("positionAmt") or 0)
        entry = float(pos.get("entryPrice") or 0) or ref
        s = 1 if amt > 0 else -1
        p = Position(symbol=sym, side=s, qty=abs(amt), entry=entry, stop_dist=dist, stop=entry - s * dist, best=entry, step=0,
                     opened_ms=self.now(), signal_close_ms=self.last_close_ms, signal_close=ref,
                     last_bar_ms=self.last_close_ms, leverage=co.leverage, roe_act=co.roe_act)
        try:
            p.equity_before = self.b.equity()
        except Exception:
            pass
        self.pos = p
        self.save()
        self.log("adopted", **asdict(p))
        try:
            self.protect("protect", "진입 확인 뒤")
        except Exception as e:
            self.log("protect_failed", symbol=sym, error=str(e))
            self._unprotected = True
        if self.pos is p and not self._unprotected:
            self.say("WARN", f"⚠ {coin_ko(sym)} 진입 체결을 늦게 확인했습니다: {'롱' if s > 0 else '숏'} {abs(amt):g}개 {entry:.6g}, "
                             f"손절 {p.stop:.6g}")

    # ---------------------------------------------------------------- the open position
    def manage(self, close_ms: int) -> None:
        """At a 30m close: is it still open; then best from the closed 30m bars since the last update, and the ladder."""
        p = self.pos
        if not self.b.live:
            self.paper_bars(close_ms)
            return
        try:
            if self.b.is_open(p.symbol) is False:
                if self.confirm_flat(p.symbol):
                    self.finish(p, None, "ladder" if p.step > 0 else "stop")
                    return
        except Exception as e:
            self.log("read_failed", symbol=p.symbol, error=str(e))
            return
        self.live_bars(p, close_ms)

    def bars_since(self, p: "Position", upto_ms: int) -> tuple[pd.DataFrame, int]:
        """The closed bars after the last one used, up to ``upto_ms``: 1m bars with ladder_every_s (30m when more than
        MINUTE_MAX minutes are missing: the bot was down), else 30m bars as the design. Returns (bars, bar length)."""
        tf = MIN30
        if self.cfg.ladder_every_s > 0 and (upto_ms - p.last_bar_ms) // MIN1 <= MINUTE_MAX:
            tf = MIN1
        rows = (self.fetch(p.symbol, "1m", int(max(3, (upto_ms - p.last_bar_ms) // MIN1 + 3))) if tf == MIN1
                else self.fetch(p.symbol, "30m", 50))
        b = bars_frame(rows, tf, upto_ms)
        return b[b.open_ms + tf > p.last_bar_ms], tf

    def live_bars(self, p: "Position", upto_ms: int) -> None:
        """Live: best from the closed bars since the last one used, then the ladder (the resting stop moved)."""
        try:
            new_bars, tf = self.bars_since(p, upto_ms)
        except Exception as e:
            self.log("bars_failed", symbol=p.symbol, error=str(e))
            return
        if new_bars.empty:
            return
        if p.side > 0:
            p.best = max(p.best, float(new_bars.high.max()))
        else:
            p.best = min(p.best, float(new_bars.low.min()))
        p.last_bar_ms = int(new_bars.open_ms.iloc[-1]) + tf
        new, step = self.ladder_for(p)
        self.save()
        if step > 0 and new != p.stop:
            try:
                res, sid = self.b.move_stop(p.symbol, p.side, new, p.qty, p.stop_id)
            except Exception as e:
                self.log("move_failed", symbol=p.symbol, to=new, error=str(e))
                self.say("WARN", f"⚠ {coin_ko(p.symbol)} 계단 손절을 {new:.6g}로 못 옮김 (지금 손절 {p.stop:.6g} 그대로): {e}")
                return
            if res == "moved":
                old = p.stop
                p.stop, p.step, p.stop_id = new, step, sid
                self.save()
                self.log("ladder", symbol=p.symbol, old=old, new=new, step=step, best=p.best)
                self.say("INFO", f"🪜 {coin_ko(p.symbol)} 계단 {step}단계: 손절 {old:.6g} → {new:.6g} ({self.roe_text(p, new)})")
            else:                                       # "closed" (price already past) / "triggered" (fired at once)
                self.log("ladder_closed", symbol=p.symbol, result=res, to=new)
                if self.b.is_open(p.symbol) is False and self.confirm_flat(p.symbol):
                    self.finish(p, None, "ladder")

    def paper_bars(self, close_ms: int) -> None:
        """Paper: the indicator's own exit on each closed bar since the last one used (30m; 1m with ladder_every_s)."""
        p = self.pos
        new_bars, tf = self.bars_since(p, close_ms)
        for _, bar in new_bars.iterrows():
            hit = bar.low <= p.stop if p.side > 0 else bar.high >= p.stop
            if hit:
                px = min(bar.open, p.stop) if p.side > 0 else max(bar.open, p.stop)
                self.finish(p, px, "ladder" if p.step > 0 else "stop")
                return
            p.best = max(p.best, bar.high) if p.side > 0 else min(p.best, bar.low)
            p.last_bar_ms = int(bar.open_ms) + tf
            new, step = self.ladder_for(p)
            if step > 0 and new != p.stop:
                self.log("ladder", symbol=p.symbol, old=p.stop, new=new, step=step, best=p.best)
                self.say("INFO", f"🪜 {coin_ko(p.symbol)} 계단 {step}단계: 손절 {p.stop:.6g} → {new:.6g}")
                p.stop, p.step = new, step
        self.save()

    def confirm_flat(self, symbol: str) -> bool:
        """Two readings a few seconds apart must both say flat (a single 0 is never trusted)."""
        self.sleep(3.0)
        return self.b.is_open(symbol) is False

    def poll(self) -> None:
        """Between closes (live): did the stop fire; is the stop still resting."""
        p = self.pos
        if not self.b.live:
            return
        due = time.monotonic() - self._last_stop_check > STOP_CHECK_S
        if p is None:
            if due or (self._entry_try and self.now() <= self._entry_try[2]):
                self._last_stop_check = time.monotonic()
                self.check_unknown()
            return
        try:
            if self.b.is_open(p.symbol) is False and self.confirm_flat(p.symbol):
                self._unprotected = False
                self.finish(p, None, "ladder" if p.step > 0 else "stop")
                return
            if due or self._unprotected:
                self._last_stop_check = time.monotonic()
                self.protect("ladder" if p.step > 0 else "stop", "점검 중")
        except Exception as e:
            self.log("poll_failed", error=str(e))
            if self._unprotected:
                self.say_once("unprotected", "CRITICAL", f"🚨 {coin_ko(p.symbol)} 손절이 없는데 거래소를 못 읽습니다: {e}\n"
                                                         f"봇이 15초마다 다시 해 봅니다. 거래소에서 바로 확인하세요")

    def minute_update(self) -> None:
        """Between the closes (ladder_every_s > 0): every ladder_every_s the open position on the closed 1m bars since
        the last one used: best, the ladder and the resting stop (paper: its stop judged on the same bars). Errors are
        logged; the exchange's stop stays as it is."""
        p = self.pos
        if p is None or self.cfg.ladder_every_s <= 0 or self._unprotected:
            return
        now = self.now()
        if now - self._last_minute_ms < self.cfg.ladder_every_s * 1000:
            return
        self._last_minute_ms = now
        try:
            if self.b.live:
                self.live_bars(p, now)
            else:
                self.paper_bars(now)
        except Exception as e:
            self.log("minute_failed", symbol=p.symbol, error=str(e))

    def finish(self, p: Position, px: Optional[float], why: str) -> None:
        """The position is closed: P&L (paper: the exit price; live: the equity change), log, message, clear."""
        if self.b.live:
            try:
                self.b.cancel_stops(p.symbol)
            except Exception as e:
                self.log("cancel_failed", symbol=p.symbol, error=str(e))
            try:
                eq = self.b.equity()
            except Exception:
                eq = None
            pnl = (eq - p.equity_before) if (eq is not None and p.equity_before is not None) else None
        else:
            pnl = self.b.paper_exit(p, px if px is not None else p.stop)
            eq = self.b.equity()
        roe = p.roe(px) if px is not None else (pnl / (p.qty * p.entry / p.leverage) * 100 if pnl is not None and p.qty else None)
        self.log("exit", symbol=p.symbol, side=p.side, why=why, price=px, pnl=pnl, equity=eq, step=p.step, entry=p.entry,
                 stop=p.stop, opened_ms=p.opened_ms)
        mark = "✅" if (pnl or 0) > 0 else "❌"
        self.say("INFO", f"{mark} {coin_ko(p.symbol)} {'롱' if p.side > 0 else '숏'} 청산 · {EXIT_KO.get(why, why)}"
                         + (f" {px:.6g}" if px is not None else "")
                         + (f"\n손익 ${pnl:+,.3f}" if pnl is not None else "") + (f" (ROE {roe:+.1f}%)" if roe is not None else "")
                         + (f"\n잔고 ${eq:,.2f}" if eq is not None else ""))
        self.pos = None
        self.save()

    # ---------------------------------------------------------------- loop
    def run(self) -> None:
        self.start()
        while not self.stop:
            now = self.now()
            nxt = (now // MIN30 + 1) * MIN30
            if self.last_close_ms and nxt - MIN30 > self.last_close_ms and now < nxt - MIN30 + 120_000:
                nxt = nxt - MIN30                       # a close not handled yet (just started): handle it now
            if nxt <= self.last_close_ms:               # the clock stepped back: never handle a close twice
                nxt = self.last_close_ms + MIN30
            while not self.stop and self.now() < nxt + SETTLE_S * 1000:
                self.poll()
                self.minute_update()
                self.sleep(min(POLL_S, max(0.5, (nxt + SETTLE_S * 1000 - self.now()) / 1000)))
            if self.stop:
                break
            for i in range(READ_TRIES):
                try:
                    self.on_close(nxt)
                    break
                except Exception as e:
                    self.log("close_failed", close_ms=nxt, error=str(e), attempt=i)
                    if i == READ_TRIES - 1:
                        self.say("WARN", f"⚠ {kst(nxt)} 봉 처리를 못 했습니다: {e}")
                    self.sleep(5.0)
        self.save()
        self.say("INFO", "⏹ 멈춤" + (f" · 보유 중 {coin_ko(self.pos.symbol)} (거래소 손절은 그대로 걸려 있음)" if self.pos else ""))


# ====================================================================== wiring
def binance_fetch(base: str):
    from .binance import BinanceREST, urllib_fetch
    rest = BinanceREST(base_url=base, fetch=lambda u, h: urllib_fetch(u, h, timeout=8.0), max_retries=2, backoff=1.0)
    return lambda symbol, tf, n: rest.klines(symbol, tf, limit=n)


def make_notify(cfg: Config):
    if not cfg.telegram or not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        return lambda level, text: print(f"{level}: {text}", flush=True)
    from .notify import TelegramNotifier
    tg = TelegramNotifier()

    def send(level: str, text: str) -> None:
        print(f"{level}: {text}", flush=True)
        tg.send(level, text)
    return send


def live_broker(cfg: Config):
    """The WOO X Pro client of the second account, through the same key gates as the executor (keys from the
    environment: /etc/paperbot/executor-wooxpro2.env)."""
    from . import wooxpro as WX
    from .mainnet import MODE_MAINNET, check_permissions
    env = dict(os.environ)
    client, keycheck = WX.clients(MODE_MAINNET, env)
    WX.refuse_unless_allowed(MODE_MAINNET, client)
    WX.check_executor_keys(MODE_MAINNET, client, keycheck, env, None)
    perm = keycheck.api_restrictions()
    if perm is None:
        raise MixError("WOO X Pro 키로 선물 계정을 읽지 못했습니다")
    problems = check_permissions(perm)
    if problems:
        raise MixError("키 확인 실패: " + " / ".join(problems))
    client.sync_time()
    return WooBroker(client, cfg.coins)


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    if cfg.mode == "mainnet" and cfg.telegram and not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_CRITICAL")):
        raise MixError("텔레그램 설정(/etc/paperbot/live-telegram.env)이 없어 실거래를 켜지 않습니다")
    lock = open(cfg.state + ".lock", "a")              # one bot per state file (a second `run` would trade the same account)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise MixError(f"이미 다른 {NAME}가 {cfg.state}로 돌고 있습니다")
    notify = make_notify(cfg)
    if cfg.mode == "mainnet":
        broker = live_broker(cfg)
        from .testnet import hide_process_memory
        hide_process_memory()
    else:
        st = read_state(cfg.state)
        try:
            from . import wooxpro as WX
            spec_fn = WX.public_client().spec
        except Exception:
            spec_fn = None
        broker = PaperBroker(float(st.get("paper_equity") or cfg.start_equity or 50.0), cfg.taker_fee, spec_fn)
    bot = Bot(cfg, broker, binance_fetch(cfg.binance_base), lambda: int(time.time() * 1000), notify)

    def _stop(*_):
        bot.stop = True
    _signal.signal(_signal.SIGTERM, _stop)
    _signal.signal(_signal.SIGINT, _stop)
    if not broker.live:                                  # paper equity survives restarts
        orig = bot.save

        def save_with_equity():
            orig()
            st = read_state(cfg.state)
            st["paper_equity"] = broker.equity()
            write_state(cfg.state, st)
        bot.save = save_with_equity
    bot.run()
    return 0


def cmd_signals(args) -> int:
    """The last colour changes of each coin with their values (Binance bars), to put next to TradingView."""
    cfg = load_config(args.config)
    fetch = binance_fetch(cfg.binance_base)
    now = int(time.time() * 1000)
    last_close = now // MIN30 * MIN30
    for co in cfg.coins:
        b30 = bars_frame(fetch(co.symbol, "30m", BARS), MIN30, last_close)
        b1h = bars_frame(fetch(co.symbol, "1h", BARS), H1, last_close)
        rows = []
        g = line_gold(b30.close.to_numpy(float))
        for i in range(len(b30) - 1, max(len(b30) - 400, 300), -1):
            if g[i] != g[i - 1]:
                ce = int(b30.open_ms.iloc[i]) + MIN30
                ev = evaluate(co, b30.iloc[:i + 1].reset_index(drop=True), b1h[b1h.open_ms + H1 <= ce].reset_index(drop=True), ce)
                rows.append(ev)
                if len(rows) >= args.n:
                    break
        lad = (f"순ROE {cfg.ladder['trigger']:g} → {cfg.ladder['lock']:g}" if cfg.ladder else f"ROE {co.roe_act:.0f} → 10")
        print(f"== {co.symbol} (여유 {co.h1_buf} · 손절 ATR × {co.sl_atr} · {lad} · {co.leverage}배"
              f"{'' if co.enabled else ' · 꺼짐'})")
        for ev in reversed(rows):
            what = "하늘(롱)" if ev.get("to_cyan") else "보라(숏)"
            res = ("롱 진입" if ev["side"] > 0 else "숏 진입") if ev["side"] else f"X ({ev['why']})"
            print(f"  {kst(ev['close_ms'])} KST 마감  {what}  종가 {ev.get('close', 0):.6g}  30분 평균RSI {ev.get('avg_rsi_30m')}"
                  f"  1시간 평균RSI {ev.get('avg_rsi_1h')}  손절폭 {ev.get('stop_pct')}%  → {res}")
        if "st" in cfg.rules:                    # the second rule: its last Stoch RSI crosses (owners 10-26)
            k, d = stoch_rsi(b30.close.to_numpy(float), *ST_STOCH)
            lines = []
            print(f"  -- {RULE_KO['st']}: 스톡RSI {'/'.join(map(str, ST_STOCH))} 크로스 (슈퍼트렌드 14/3·14/6, RSI26 30분·1시간, "
                  f"MOM {ST_MOM})")
            for i in range(len(b30) - 1, max(len(b30) - 400, 300), -1):
                if (k[i] > d[i]) != (k[i - 1] > d[i - 1]) and np.isfinite(k[i]) and np.isfinite(d[i - 1]):
                    ce = int(b30.open_ms.iloc[i]) + MIN30
                    ev = evaluate_st(co, b30.iloc[:i + 1].reset_index(drop=True),
                                     b1h[b1h.open_ms + H1 <= ce].reset_index(drop=True), ce)
                    if not ev.get("cross"):
                        continue
                    res = ("롱 진입" if ev["side"] > 0 else "숏 진입") if ev["side"] else f"X ({ev['why']})"
                    lines.append(f"  {kst(ev['close_ms'])} KST 마감  {'골든' if ev['cross'] == 'gold' else '데드'}  종가 "
                          f"{ev.get('close', 0):.6g}  ST14/3 {'상승' if ev['st3_up'] else '하락'} · 14/6 "
                          f"{'상승' if ev['st6_up'] else '하락'}  K {ev['k']} D {ev['d']}  RSI26 30분 {ev['rsi26_30m']} "
                          f"1시간 {ev['rsi26_1h']}  MOM {ev.get('mom')}  손절폭 {ev.get('stop_pct')}%  → {res}")
                    if len(lines) >= args.n:
                        break
            for ln in reversed(lines):                   # oldest first, as the colour changes above
                print(ln)
    return 0


def cmd_check(args) -> int:
    """Reads only: WOO X Pro contract specs of the coins (public), and with keys the account, the position mode, the
    positions, and what a stop-out would size to now."""
    cfg = load_config(args.config)
    from . import wooxpro as WX
    pub = WX.public_client()
    fetch = binance_fetch(cfg.binance_base)
    eq = None
    if cfg.mode == "mainnet":
        b = live_broker(cfg)
        eq = b.equity()
        print(f"잔고(WOO X Pro 2): ${eq:,.2f} · 포지션 모드 {b.c.position_mode()}")
        for s, q in b.foreign_positions(None):
            print(f"  열린 포지션: {s} {q:g}")
    eq = eq or float(cfg.start_equity or 50.0)
    now = int(time.time() * 1000)
    print("크기·계단: " + (f"진입마다 증거금 = 잔고의 {cfg.margin_frac:.0%} (한 번 최대 ${cfg.max_notional_usd:,.0f})"
                          if cfg.margin_frac > 0 else f"손절 1번 = 잔고의 {cfg.risk_pct}%")
          + (f" · 계단 순ROE +{cfg.ladder['trigger']:g}%→+{cfg.ladder['lock']:g}%, 그 뒤 {cfg.ladder['step']:g}%마다"
             if cfg.ladder else " · 계단 코인별 roe_act")
          + (f" · 손절·계단 {cfg.ladder_every_s:g}초마다(1분봉)" if cfg.ladder_every_s > 0 else ""))
    if tuple(cfg.rules) != ("mix",) or cfg.stop_atr:          # owners 10-26: the second rule, one stop multiple
        print("매매법·손절: " + " + ".join(RULE_KO[r] for r in cfg.rules)
              + (f"(같은 봉이면 {RULE_KO[cfg.rules[0]]} 먼저)" if len(cfg.rules) > 1 else "")
              + (f" · 손절 ATR {cfg.stop_atr:g}배(모든 코인)" if cfg.stop_atr else " · 손절 코인별 ATR 배수"))
    for co in cfg.coins:
        try:
            sp = pub.spec(co.symbol)
        except Exception as e:
            print(f"✘ {co.symbol}: WOO X Pro 계약을 못 읽음 ({e})")
            continue
        b30 = bars_frame(fetch(co.symbol, "30m", 100), MIN30, now // MIN30 * MIN30)
        c = b30.close.to_numpy(float)
        a = float(atr(b30.high.to_numpy(float), b30.low.to_numpy(float), c, 14)[-1])
        dist = a * co.sl_atr
        qty = (eq * cfg.margin_frac * co.leverage / c[-1]) if cfg.margin_frac > 0 else eq * cfg.risk_pct / 100 / dist
        qty = min(qty, cfg.max_notional_usd / c[-1])
        step = float(sp["qty_step"])
        qty_f = math.floor(qty / step + 1e-9) * step
        ok = qty_f >= float(sp["min_qty"]) and qty_f * c[-1] >= float(sp.get("min_notional") or 0)
        print(f"{'✔' if ok else '✘'} {co.symbol}: 상태 {sp.get('status')}, 최대 {sp.get('max_leverage')}배, 1계약 {sp['contract_size']}, "
              f"최소 {sp['min_qty']:g}개 · 지금 손절 폭 {dist / c[-1] * 100:.2f}% → 크기 {qty_f:g}개 ≈ ${qty_f * c[-1]:,.2f} "
              f"(증거금 ${qty_f * c[-1] / co.leverage:,.2f}){'' if ok else ' → 최소 주문보다 작아 건너뜀'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.mixchop", description=NAME)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "check", "signals"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        if name == "signals":
            p.add_argument("-n", type=int, default=6)
    args = ap.parse_args(argv)
    try:
        return {"run": cmd_run, "check": cmd_check, "signals": cmd_signals}[args.cmd](args)
    except MixError as e:
        print(f"멈춤: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        from .mainnet import Refused
        if isinstance(e, Refused):                       # a key / mode / host gate: restarting cannot fix it
            print(f"멈춤: {e}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
