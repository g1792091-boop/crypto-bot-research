"""Entry signals of the new-strategy lab (docs/newlab-prereg.md, section 2): grammar tables and the
causal signal computation. No AI calls, no I/O.

Triggers are the 40 entries of research/library/lib.py ``entries`` (same indicator code from the
locked vendor modules, same parameter values, same long/short clean-up: a bar that is both long and
short is long). tests/test_newlab.py checks every one against lib.entries bar for bar.

Five of the library's indicators are slow in pure pandas on 600k 5-minute bars (Parabolic SAR ~50 s,
CCI's rolling mean deviation, Aroon's and HMA's rolling ``apply``, the SuperTrend loop over numpy
scalars). They are re-implemented below with the same arithmetic (plain-float loops or sliding
windows); the tests compare them with the vendor originals.

Signal convention (as the locked strategies): the signal is known on the bar's close, int8 +1 long /
-1 short / 0; the lab enters at the next bar's open.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import lfilter

from .. import sweepsig
from ..context import HTF

TFS = ("5m", "15m", "30m", "1h", "4h")
DIRECTIONS = ("long", "short", "both")

# family -> (param names, allowed value tuples (in that order), needs volume, group, Korean)
FAMILIES: dict = {
    "ema_cross": (("fast", "slow"), ((9, 21), (20, 50), (50, 200)), False, "trend", "EMA 빠른선·느린선 교차"),
    "sma_cross": (("fast", "slow"), ((10, 30), (50, 200)), False, "trend", "SMA 빠른선·느린선 교차"),
    "macd_cross": (("fast", "slow", "signal"), ((12, 26, 9), (8, 21, 5)), False, "trend", "MACD선·시그널선 교차"),
    "macd_hist_zero": ((), ((),), False, "trend", "MACD(12/26/9) 히스토그램 0선 교차"),
    "supertrend_flip": (("length", "mult"), ((10, 2.0), (10, 3.0), (14, 4.0)), False, "trend", "슈퍼트렌드 방향 전환"),
    "donchian_break": (("length",), ((20,), (55,)), False, "trend", "종가가 직전 N봉 최고가 위로 / 최저가 아래로"),
    "keltner_break": ((), ((),), False, "trend", "켈트너(EMA20, ATR10 x 2) 돌파"),
    "psar_flip": ((), ((),), False, "trend", "파라볼릭 SAR 방향 전환"),
    "dmi_cross": ((), ((),), False, "trend", "+DI/-DI 교차 + ADX(14) > 25"),
    "ichimoku_tk": ((), ((),), False, "trend", "일목 전환선·기준선 교차"),
    "aroon_cross": ((), ((),), False, "trend", "아룬(25) 업·다운 교차"),
    "hma_turn": (("length",), ((21,), (55,)), False, "trend", "HMA 기울기 전환"),
    "rsi_reversal": (("length", "low", "high"), ((14, 30, 70), (7, 20, 80)), False, "oscillator",
                     "RSI가 과매도선 위로(롱) / 과매수선 아래로(숏)"),
    "rsi_cross50": ((), ((),), False, "oscillator", "RSI(14) 50선 교차"),
    "stoch_zone": ((), ((),), False, "oscillator", "스토캐스틱(14,3,3) K·D 교차, 20 아래 롱 / 80 위 숏"),
    "stochrsi_zone": ((), ((),), False, "oscillator", "스토캐스틱 RSI(14,14,3,3) K·D 교차, 20 아래 롱 / 80 위 숏"),
    "cci_extreme": ((), ((),), False, "oscillator", "CCI(20)가 -100 위로(롱) / +100 아래로(숏)"),
    "williams_r": ((), ((),), False, "oscillator", "윌리엄스 %R(14)이 -80 위로 / -20 아래로"),
    "mfi_reversal": ((), ((),), True, "oscillator", "MFI(14)가 20 위로 / 80 아래로"),
    "roc_zero": (("length",), ((9,), (21,)), False, "oscillator", "ROC 0선 교차"),
    "cmo_zero": ((), ((),), False, "oscillator", "CMO(14) 0선 교차"),
    "bb_break": ((), ((),), False, "volatility", "종가가 볼린저(20, 2) 밴드 밖으로 돌파"),
    "bb_revert": ((), ((),), False, "volatility", "종가가 볼린저 밴드 안으로 복귀"),
    "squeeze_break": ((), ((),), False, "volatility", "6봉 스퀴즈(볼린저가 켈트너 안) 뒤 밴드 돌파"),
    "obv_cross": ((), ((),), True, "volume", "OBV가 OBV 20봉 평균 교차"),
    "volume_spike": ((), ((),), True, "volume", "거래량 > 직전 20봉 평균 x 3, 캔들 방향으로"),
    "engulfing": ((), ((),), False, "candle", "장악형 캔들"),
    "hammer_star": ((), ((),), False, "candle", "망치형(롱) / 유성형(숏)"),
    "inside_break": ((), ((),), False, "candle", "인사이드바 다음 봉의 엄마 봉 돌파"),
    "three_same": ((), ((),), False, "candle", "같은 색 캔들 3연속"),
}

# filter kind -> {param: allowed values}, Korean
FILTERS: dict = {
    "trend_ema": ({"length": (50, 100, 200)}, "롱은 종가 > EMA(length), 숏은 종가 < EMA(length)"),
    "adx": ({"mode": ("above", "below"), "level": (20, 25, 30)}, "ADX(14)가 level 위(above) / 아래(below)일 때만"),
    "htf_trend": ({"length": (20, 50)}, "위 시간봉의 닫힌 봉 종가가 그 EMA(length) 위면 롱만, 아래면 숏만"),
    "vol_regime": ({"mode": ("high", "low"), "lookback": (100, 500)},
                   "ATR14/종가가 최근 lookback봉 중앙값보다 높을 때(high) / 낮을 때(low)만"),
    "session": ({"window": ("asia", "europe", "us")}, "진입 시각(UTC) 아시아 00~08 / 유럽 08~16 / 미국 16~24시만"),
}
SESSIONS = {"asia": (0, 8), "europe": (8, 16), "us": (16, 24)}
MAX_FILTERS = 2


def needs_volume(spec: dict) -> bool:
    return bool(FAMILIES[spec["entry"]["family"]][2])


# ---------------------------------------------------------------------------------------------
# fast equivalents of slow vendor indicators (same arithmetic; compared in the tests)
# ---------------------------------------------------------------------------------------------
def _recursive_ma(x: np.ndarray, length: int, alpha: float) -> np.ndarray:
    """pine_indicators._recursive_ma with the recursion in scipy's lfilter: the same two products and
    one sum per bar (bit-identical, checked in the tests); the vendor loop when a value after the seed
    is missing (its nz() carry-forward)."""
    pi = sweepsig.lib().pi
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    s = pi._first_full_window(x, length)
    if s < 0:
        return out
    tail = x[s + 1:]
    if not np.isfinite(tail).all():
        return pi._recursive_ma(x, length, alpha)
    out[s] = np.mean(x[s - length + 1:s + 1])
    if len(tail):
        out[s + 1:] = lfilter([alpha], [1.0, -(1.0 - alpha)], tail, zi=[(1.0 - alpha) * out[s]])[0]
    return out


def pine_ema(x, length: int) -> np.ndarray:
    return _recursive_ma(np.asarray(x, dtype=float), int(length), 2.0 / (length + 1.0))


def pine_rma(x, length: int) -> np.ndarray:
    return _recursive_ma(np.asarray(x, dtype=float), int(length), 1.0 / float(length))


def pine_macd(close, fast: int, slow: int, signal: int):
    close = np.asarray(close, dtype=float)
    line = pine_ema(close, fast) - pine_ema(close, slow)
    sig = pine_ema(line, signal)
    return line, sig, line - sig


def pine_rsi(close, length: int) -> np.ndarray:
    """pine_indicators.pine_rsi with the fast RMA."""
    close = np.asarray(close, dtype=float)
    delta = np.diff(close, prepend=np.nan)
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    up[0] = np.nan
    down[0] = np.nan
    au = pine_rma(up, length)
    ad = pine_rma(down, length)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        out = np.where(ad == 0.0, 100.0, np.where(au == 0.0, 0.0, 100.0 - 100.0 / (1.0 + rs)))
    return np.where(np.isfinite(au) & np.isfinite(ad), out, np.nan)


def stoch_rsi_kd(close, rsi_length: int, stoch_length: int, k_smooth: int, d_smooth: int):
    """pine_indicators.stoch_rsi_kd with the fast RSI."""
    pi = sweepsig.lib().pi
    r = pine_rsi(close, rsi_length)
    lo = pi.pine_lowest(r, stoch_length)
    hi = pi.pine_highest(r, stoch_length)
    rng = hi - lo
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(rng != 0.0, 100.0 * (r - lo) / rng, 0.0)
    raw = np.where(np.isfinite(rng), raw, np.nan)
    k = pi.pine_sma(raw, k_smooth)
    d = pi.pine_sma(k, d_smooth)
    return k, d


def psar_direction(high: np.ndarray, low: np.ndarray, close: np.ndarray, acceleration: float = 0.02,
                   acceleration_step: float = 0.02, acceleration_max: float = 0.2) -> np.ndarray:
    """Direction (+1/-1, NaN on bar 0) of fg_indicators.parabolic_sar, plain-float loop."""
    n = len(close)
    direction = np.full(n, np.nan)
    if n < 2:
        return direction
    hi, lo, c = (np.asarray(x, float).tolist() for x in (high, low, close))
    uptrend = bool(c[1] >= c[0])
    ep = float(max(hi[0], hi[1]) if uptrend else min(lo[0], lo[1]))
    cur = float(min(lo[0], lo[1]) if uptrend else max(hi[0], hi[1]))
    af = float(acceleration)
    d = [math.nan] * n
    d[1] = 1.0 if uptrend else -1.0
    amax, astep, a0 = float(acceleration_max), float(acceleration_step), float(acceleration)
    for i in range(2, n):
        cur = cur + af * (ep - cur)
        if uptrend:
            cur = min(cur, lo[i - 1], lo[i - 2])
            if lo[i] < cur:
                uptrend = False
                cur = ep
                ep = lo[i]
                af = a0
            elif hi[i] > ep:
                ep = hi[i]
                af = min(amax, af + astep)
        else:
            cur = max(cur, hi[i - 1], hi[i - 2])
            if hi[i] > cur:
                uptrend = True
                cur = ep
                ep = hi[i]
                af = a0
            elif lo[i] < ep:
                ep = lo[i]
                af = min(amax, af + astep)
        d[i] = 1.0 if uptrend else -1.0
    return np.asarray(d, float)


def _windows(x: np.ndarray, n: int):
    x = np.asarray(x, float)
    if len(x) < n:
        return None
    return sliding_window_view(x, n)


def cci(df: pd.DataFrame, length: int = 20) -> np.ndarray:
    """fg_indicators.cci with the rolling mean deviation computed on sliding windows."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    mean = typical.rolling(length, min_periods=length).mean()
    md = np.full(len(typical), np.nan)
    W = _windows(typical.to_numpy(float), length)
    if W is not None:
        for s in range(0, len(W), 200_000):
            w = W[s:s + 200_000]
            md[s + length - 1:s + length - 1 + len(w)] = np.abs(w - w.mean(axis=1)[:, None]).mean(axis=1)
    md = pd.Series(md, index=typical.index).replace(0, np.nan)
    return ((typical - mean) / (0.015 * md)).to_numpy(float)


def aroon(high: np.ndarray, low: np.ndarray, length: int = 25):
    """fg_indicators.aroon (latest extreme wins a tie), on sliding windows."""
    length = max(2, int(length))
    out = []
    for x, fn in ((high, np.argmax), (low, np.argmin)):
        r = np.full(len(x), np.nan)
        W = _windows(x, length)
        if W is not None:
            k = fn(W[:, ::-1], axis=1)
            v = 100.0 * (length - k) / length
            v[~np.isfinite(W).all(axis=1)] = np.nan
            r[length - 1:] = v
        out.append(r)
    return out[0], out[1]


def wma(x: np.ndarray, n: int) -> np.ndarray:
    """research/library/lib._wma (dot with weights 1..n over the window / sum of weights)."""
    x = np.asarray(x, float)
    w = np.arange(1, n + 1, dtype=float)
    out = np.full(len(x), np.nan)
    W = _windows(x, n)
    if W is not None:
        out[n - 1:] = np.einsum("ij,j->i", W, w) / w.sum()
    return out


def hma(x: np.ndarray, n: int) -> np.ndarray:
    return wma(2 * wma(x, n // 2) - wma(x, n), int(np.sqrt(n)))


def supertrend_direction(high, low, close, atr_length: int, multiplier: float) -> np.ndarray:
    """Direction of pine_indicators.exchange_supertrend, plain-float loop."""
    pi = sweepsig.lib().pi
    high, low, close = (np.asarray(x, float) for x in (high, low, close))
    n = len(close)
    tr = pi.true_range(high, low, close)
    atr = pine_rma(tr, atr_length)
    hl2 = (high + low) / 2.0
    BL = (hl2 - multiplier * atr).tolist()
    BU = (hl2 + multiplier * atr).tolist()
    c = close.tolist()
    fin = math.isfinite
    lower = [math.nan] * n
    upper = [math.nan] * n
    out = [1] * n
    d = 1
    for i in range(n):
        bl, bu = BL[i], BU[i]
        pl = lower[i - 1] if i > 0 and fin(lower[i - 1]) else bl
        pu = upper[i - 1] if i > 0 and fin(upper[i - 1]) else bu
        pc = c[i - 1] if i > 0 else math.nan
        if fin(bl):
            lower[i] = max(bl, pl) if (i > 0 and pc > pl) else bl
        if fin(bu):
            upper[i] = min(bu, pu) if (i > 0 and pc < pu) else bu
        d = out[i - 1] if i > 0 else 1
        if d == -1 and fin(pu) and c[i] > pu:
            d = 1
        elif d == 1 and fin(pl) and c[i] < pl:
            d = -1
        out[i] = d
    return np.asarray(out, np.int8)


# ---------------------------------------------------------------------------------------------
# triggers (research/library/lib.py entries, one family at a time)
# ---------------------------------------------------------------------------------------------
def _cross_up(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (a > b) & (np.r_[np.nan, a[:-1]] <= np.r_[np.nan, b[:-1]])


def _cross_dn(a, b):
    return _cross_up(b, a)


def frame(o, h, lo, c, v=None) -> pd.DataFrame:
    n = len(c)
    return pd.DataFrame({"open": np.asarray(o, float), "high": np.asarray(h, float), "low": np.asarray(lo, float),
                         "close": np.asarray(c, float),
                         "volume": np.asarray(v, float) if v is not None else np.zeros(n)})


def trigger(family: str, params: dict, df: pd.DataFrame):
    """(long, short) boolean arrays of one entry family, exactly as lib.entries."""
    L = sweepsig.lib()
    fg, pi = L.fg, L.pi
    o, h, lo, c, v = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    ca, ha, la, oa = c.to_numpy(), h.to_numpy(), lo.to_numpy(), o.to_numpy()
    n = len(ca)
    z = np.zeros(n)
    p = params
    with np.errstate(invalid="ignore", divide="ignore"):
        if family == "ema_cross":
            a, b = pine_ema(ca, p["fast"]), pine_ema(ca, p["slow"])
            lg, sh = _cross_up(a, b), _cross_dn(a, b)
        elif family == "sma_cross":
            a, b = pi.pine_sma(ca, p["fast"]), pi.pine_sma(ca, p["slow"])
            lg, sh = _cross_up(a, b), _cross_dn(a, b)
        elif family == "macd_cross":
            m, sg, _hist = pine_macd(ca, p["fast"], p["slow"], p["signal"])
            lg, sh = _cross_up(m, sg), _cross_dn(m, sg)
        elif family == "macd_hist_zero":
            _m, _sg, hist = pine_macd(ca, 12, 26, 9)
            lg, sh = _cross_up(hist, z), _cross_dn(hist, z)
        elif family == "supertrend_flip":
            d = supertrend_direction(ha, la, ca, p["length"], float(p["mult"]))
            dp = np.r_[0, d[:-1]]
            lg, sh = (d == 1) & (dp == -1), (d == -1) & (dp == 1)
        elif family == "donchian_break":
            hh, ll = pi.shift1(pi.pine_highest(ha, p["length"])), pi.shift1(pi.pine_lowest(la, p["length"]))
            lg, sh = _cross_up(ca, hh), _cross_dn(ca, ll)
        elif family == "keltner_break":
            up, _mid, dn = fg.keltner_channel(df, 20, 10, 2.0)
            lg, sh = _cross_up(ca, up.to_numpy()), _cross_dn(ca, dn.to_numpy())
        elif family == "psar_flip":
            sd = psar_direction(ha, la, ca)
            sdp = np.r_[np.nan, sd[:-1]]
            lg, sh = (sd == 1) & (sdp == -1), (sd == -1) & (sdp == 1)
        elif family == "dmi_cross":
            pdi, mdi, adx = fg.dmi_adx(df, 14, 14)
            strong = adx.to_numpy() > 25
            lg = _cross_up(pdi.to_numpy(), mdi.to_numpy()) & strong
            sh = _cross_dn(pdi.to_numpy(), mdi.to_numpy()) & strong
        elif family == "ichimoku_tk":
            ten, kij, _sa, _sb = fg.ichimoku(df)
            lg, sh = _cross_up(ten.to_numpy(), kij.to_numpy()), _cross_dn(ten.to_numpy(), kij.to_numpy())
        elif family == "aroon_cross":
            au, ad = aroon(ha, la, 25)
            lg, sh = _cross_up(au, ad), _cross_dn(au, ad)
        elif family == "hma_turn":
            hm = hma(ca, p["length"])
            sl = np.sign(np.r_[np.nan, np.diff(hm)])
            slp = np.r_[np.nan, sl[:-1]]
            lg, sh = (sl > 0) & (slp < 0), (sl < 0) & (slp > 0)
        elif family == "rsi_reversal":
            r = pine_rsi(ca, p["length"])
            lg, sh = _cross_up(r, np.full(n, float(p["low"]))), _cross_dn(r, np.full(n, float(p["high"])))
        elif family == "rsi_cross50":
            r = pine_rsi(ca, 14)
            lg, sh = _cross_up(r, np.full(n, 50.0)), _cross_dn(r, np.full(n, 50.0))
        elif family == "stoch_zone":
            k, d = pi.stoch_kd(ca, ha, la, 14, 3, 3)
            lg, sh = _cross_up(k, d) & (k < 20), _cross_dn(k, d) & (k > 80)
        elif family == "stochrsi_zone":
            k, d = stoch_rsi_kd(ca, 14, 14, 3, 3)
            lg, sh = _cross_up(k, d) & (k < 20), _cross_dn(k, d) & (k > 80)
        elif family == "cci_extreme":
            cc = cci(df, 20)
            lg, sh = _cross_up(cc, np.full(n, -100.0)), _cross_dn(cc, np.full(n, 100.0))
        elif family == "williams_r":
            wr = fg.williams_r(df, 14).to_numpy()
            lg, sh = _cross_up(wr, np.full(n, -80.0)), _cross_dn(wr, np.full(n, -20.0))
        elif family == "mfi_reversal":
            mf = fg.mfi(df, 14).to_numpy()
            lg, sh = _cross_up(mf, np.full(n, 20.0)), _cross_dn(mf, np.full(n, 80.0))
        elif family == "roc_zero":
            rc = fg.roc(c, p["length"]).to_numpy()
            lg, sh = _cross_up(rc, z), _cross_dn(rc, z)
        elif family == "cmo_zero":
            cm = fg.cmo(c, 14).to_numpy()
            lg, sh = _cross_up(cm, z), _cross_dn(cm, z)
        elif family in ("bb_break", "bb_revert", "squeeze_break"):
            bu, _bm, bl, _bw = fg.bollinger_bands(c, 20, 2.0)
            bu, bl = bu.to_numpy(), bl.to_numpy()
            if family == "bb_break":
                lg, sh = _cross_up(ca, bu), _cross_dn(ca, bl)
            elif family == "bb_revert":
                lg, sh = _cross_up(ca, bl), _cross_dn(ca, bu)
            else:
                ku, _km, kl = fg.keltner_channel(df, 20, 20, 1.5)
                sq = (bu < ku.to_numpy()) & (bl > kl.to_numpy())
                sq6 = pd.Series(sq.astype(float)).shift(1).rolling(6).min().to_numpy() == 1
                lg, sh = sq6 & (ca > bu), sq6 & (ca < bl)
        elif family == "obv_cross":
            ob = pi.obv(ca, v.to_numpy())
            obm = pi.pine_sma(ob, 20)
            lg, sh = _cross_up(ob, obm), _cross_dn(ob, obm)
        elif family == "volume_spike":
            vs = v.to_numpy() > 3 * pi.shift1(pi.pine_sma(v.to_numpy(), 20))
            lg, sh = vs & (ca > oa), vs & (ca < oa)
        elif family == "engulfing":
            op, cp = np.r_[np.nan, oa[:-1]], np.r_[np.nan, ca[:-1]]
            lg = (cp < op) & (ca > oa) & (ca >= op) & (oa <= cp)
            sh = (cp > op) & (ca < oa) & (ca <= op) & (oa >= cp)
        elif family == "hammer_star":
            body = np.abs(ca - oa)
            rng = ha - la
            low_wick = np.minimum(ca, oa) - la
            up_wick = ha - np.maximum(ca, oa)
            lg = (low_wick >= 2 * body) & (up_wick <= 0.3 * rng) & (rng > 0)
            sh = (up_wick >= 2 * body) & (low_wick <= 0.3 * rng) & (rng > 0)
        elif family == "inside_break":
            inside_prev = np.r_[False, (ha[1:] < ha[:-1]) & (la[1:] > la[:-1])]
            hpp, lpp = np.r_[np.nan, np.nan, ha[:-2]], np.r_[np.nan, np.nan, la[:-2]]
            lg, sh = inside_prev & (ca > hpp), inside_prev & (ca < lpp)
        elif family == "three_same":
            lg = pd.Series(ca > oa).rolling(3).sum().to_numpy() == 3
            sh = pd.Series(ca < oa).rolling(3).sum().to_numpy() == 3
        else:
            raise KeyError(family)
    lg = np.nan_to_num(np.asarray(lg, float)) != 0
    sh = (np.nan_to_num(np.asarray(sh, float)) != 0) & ~lg
    return lg, sh


# ---------------------------------------------------------------------------------------------
# filters: (long allowed, short allowed) per bar, known on the bar's close
# ---------------------------------------------------------------------------------------------
def htf_values(ts_ns: np.ndarray, df: pd.DataFrame, tf: str, htf: str, fn) -> np.ndarray:
    """fn(htf frame) mapped to each bar: the value of the last higher-timeframe bar CLOSED at or before
    the bar's close (research/search/search.py htf_series, on int64 ns timestamps)."""
    L = sweepsig.lib()
    x = df.copy()
    x["ts"] = pd.to_datetime(np.asarray(ts_ns, np.int64), utc=True)
    dh = L.resample_ohlcv(x, htf)
    vals = np.asarray(fn(dh), dtype=float)
    hclose = (pd.to_datetime(dh["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
              .astype(np.int64) + L.tf_minutes(htf) * 60_000_000_000)
    cclose = np.asarray(ts_ns, np.int64) + L.tf_minutes(tf) * 60_000_000_000
    j = np.searchsorted(hclose, cclose, side="right") - 1
    return np.where(j >= 0, vals[np.clip(j, 0, max(len(vals) - 1, 0))], np.nan) if len(vals) else \
        np.full(len(cclose), np.nan)


def filter_mask(f: dict, df: pd.DataFrame, ts_ns: np.ndarray, tf: str, atr: np.ndarray):
    L = sweepsig.lib()
    fg = L.fg
    ca = df["close"].to_numpy(float)
    k = f["kind"]
    with np.errstate(invalid="ignore", divide="ignore"):
        if k == "trend_ema":
            e = pine_ema(ca, f["length"])
            return ca > e, ca < e
        if k == "adx":
            _p, _m, adx = fg.dmi_adx(df, 14, 14)
            a = adx.to_numpy(float)
            ok = a > f["level"] if f["mode"] == "above" else a < f["level"]
            return ok, ok
        if k == "htf_trend":
            htf = HTF[tf]
            hc = htf_values(ts_ns, df, tf, htf, lambda d: d["close"].to_numpy(float))
            he = htf_values(ts_ns, df, tf, htf, lambda d: pine_ema(d["close"].to_numpy(float), f["length"]))
            return hc > he, hc < he
        if k == "vol_regime":
            x = np.asarray(atr, float) / ca
            med = pd.Series(x).rolling(f["lookback"], min_periods=f["lookback"]).median().to_numpy()
            ok = x > med if f["mode"] == "high" else x < med
            return ok, ok
        if k == "session":
            a, b = SESSIONS[f["window"]]
            hour = ((np.asarray(ts_ns, np.int64) + L.tf_minutes(tf) * 60_000_000_000) // 3_600_000_000_000) % 24
            ok = (hour >= a) & (hour < b)
            return ok, ok
    raise KeyError(k)


def signals(spec: dict, ts_ns: np.ndarray, o, h, lo, c, v=None, atr=None) -> np.ndarray:
    """int8 +1/-1/0 per bar for a canonical spec (newlab.normalize_spec), causal: bar i uses bars <= i
    (and higher-timeframe bars closed by bar i's close). ``atr``: ATR14 per bar (default fg.atr 14,
    which is how the lab caches were built)."""
    tf = spec["timeframe"]
    df = frame(o, h, lo, c, v)
    if atr is None:
        atr = sweepsig.lib().fg.atr(df, 14).to_numpy(float)
    lg, sh = trigger(spec["entry"]["family"], spec["entry"]["params"], df)
    for f in spec.get("filters", []):
        ml, ms = filter_mask(f, df, ts_ns, tf, atr)
        lg, sh = lg & ml, sh & ms
    if spec["direction"] == "long":
        sh = np.zeros_like(sh)
    elif spec["direction"] == "short":
        lg = np.zeros_like(lg)
    out = np.zeros(len(c), np.int8)
    out[lg] = 1
    out[sh & ~lg] = -1
    return out


def signals_for_frame(spec: dict, df: pd.DataFrame, atr: Optional[np.ndarray] = None) -> np.ndarray:
    """Same, from an OHLCV frame with a ``ts`` column (bar open, UTC) - for a live/paper implementation."""
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)
    v = df["volume"].to_numpy(float) if "volume" in df else None
    return signals(spec, ts, df["open"].to_numpy(float), df["high"].to_numpy(float), df["low"].to_numpy(float),
                   df["close"].to_numpy(float), v, atr)
