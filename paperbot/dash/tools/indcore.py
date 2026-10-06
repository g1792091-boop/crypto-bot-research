"""좋은 수치 찾기: the market numbers at an entry and their ranges (pure numpy / pandas; no file, no database).

Shared by the offline 5-year generator (tools/indranges.py) and the dashboard's paper-forward part
(dash/more/indranges.py), so a paper entry lands in the same range as a 5-year one. The indicator math is the locked
library's (paperbot/sweepsig.lib().fg: rsi, ema, atr, adx_dmi, bollinger_bands, sma; imported, never changed), so the
numbers are the ones the strategies themselves see.

Numbers on the SIGNAL bar (its close; the entry is the next bar's open), from that bar and earlier bars only:

    rsi       RSI(14) of the close, side-relative: a short reads 100 - RSI (high = already moved far in the trade's way)
    atr_pct   ATR(14) / close (the bar's average range as a share of the price)
    adx       ADX(14) (trend strength, direction-free)
    ema200    (close - EMA200) / ATR(14), side-relative: x side (+ = price already on the trade's side of EMA200)
    vol       volume / mean volume of the 20 bars before the signal bar
    bbw       Bollinger band width (20, 2): (upper - lower) / middle, in percent
    funding   funding rate at the entry (the last settlement at most 9 hours before), raw sign (+ = longs pay)
    session   the entry's hour in Korea time: 아시아 09-16, 유럽 16-22, 미국 22-05, 새벽 05-09 (paperbot/sessions.py)

Ranges: the first six are quintiles (Q1 lowest 20% .. Q5 highest 20%) whose four edges are fixed per timeframe from the
5-year entries of all 36 strategies on that timeframe (``edges``); funding has three fixed ranges (entrymoment's: 음수 /
0~0.01% / 0.01% 초과) and session four. A missing number is no range (-1), never a guess.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

QUINT = ("rsi", "atr_pct", "adx", "ema200", "vol", "bbw")
FIXED = {"funding": ("neg", "base", "high"), "session": ("asia", "europe", "us", "dawn")}
INDICATORS = QUINT + tuple(FIXED)
SIDED = ("rsi", "ema200")                     # read in the trade's direction
N_Q = 5
FUNDING_BASE = 0.0001                         # entrymoment.FUNDING_BASE (0.01% per 8 h: Binance's base rate)
FUNDING_MAX_AGE_MS = 9 * 3_600_000
KST_MS = 9 * 3_600_000
VOL_N = 20
EMA_N = 200
WARMUP_BARS = 600                             # bars before the first entry a paper series should start (EMA200 settles)


def _fg():
    from ... import sweepsig
    return sweepsig.lib().fg


def series(o, h, lo, c, v, atr: Optional[np.ndarray] = None) -> dict:
    """{key: array} of the raw (not side-relative) numbers on every bar: rsi, atr, atr_pct, adx, ema200 (distance in
    ATR), vol, bbw. ``atr`` given (the signal cache's own fg.atr(df, 14)) is used as it is."""
    import pandas as pd
    fg = _fg()
    df = pd.DataFrame({"open": np.asarray(o, float), "high": np.asarray(h, float), "low": np.asarray(lo, float),
                       "close": np.asarray(c, float)})
    close = df["close"]
    a = np.asarray(atr, float) if atr is not None else fg.atr(df, 14).to_numpy(float)
    cl = close.to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        atr_pct = np.where(cl > 0, a / cl, np.nan)
        ema = fg.ema(close, EMA_N).to_numpy(float)
        ema_d = np.where(a > 0, (cl - ema) / a, np.nan)
        vv = pd.Series(np.asarray(v, float))
        prev = vv.shift(1).rolling(VOL_N, min_periods=VOL_N).mean().to_numpy(float)
        vol = np.where(prev > 0, vv.to_numpy(float) / prev, np.nan)
    adx = fg.adx_dmi(df, 14)[0].to_numpy(float)
    bbw = fg.bollinger_bands(close, 20, 2.0)[3].to_numpy(float)
    rsi = fg.rsi(close, 14).to_numpy(float)
    return {"rsi": rsi, "atr": a, "atr_pct": atr_pct, "adx": adx, "ema200": ema_d, "vol": vol, "bbw": bbw}


def sided(key: str, value, side) -> np.ndarray:
    """The value as the bucket reads it: rsi / ema200 in the trade's direction, the rest as they are."""
    x = np.asarray(value, float)
    s = np.asarray(side, float)
    if key == "rsi":
        return np.where(s > 0, x, 100.0 - x)
    if key == "ema200":
        return x * np.sign(s)
    return x


def session_of_hour(hour_kst: int) -> int:
    """Index into FIXED['session'] (paperbot/sessions.session_of's hours)."""
    if 9 <= hour_kst < 16:
        return 0
    if 16 <= hour_kst < 22:
        return 1
    if 5 <= hour_kst < 9:
        return 3
    return 2


def session_idx(entry_ms) -> np.ndarray:
    """Session index of every entry time (ms, UTC)."""
    hours = ((np.asarray(entry_ms, np.int64) + KST_MS) // 3_600_000) % 24
    return np.array([session_of_hour(int(x)) for x in hours], dtype=np.int8)


def funding_idx(rate) -> np.ndarray:
    """Index into FIXED['funding']: <0 neg, 0..0.01% base, >0.01% high; -1 when unknown (NaN)."""
    r = np.asarray(rate, float)
    out = np.full(r.shape, -1, dtype=np.int8)
    ok = np.isfinite(r)
    out[ok & (r < -1e-9)] = 0
    out[ok & (r >= -1e-9) & (r <= FUNDING_BASE + 1e-9)] = 1
    out[ok & (r > FUNDING_BASE + 1e-9)] = 2
    return out


def funding_at(times: np.ndarray, rates: np.ndarray, entry_ms) -> np.ndarray:
    """The last settled rate at or before each entry, at most 9 hours old (NaN otherwise). ``times`` ascending."""
    e = np.asarray(entry_ms, np.int64)
    if not len(times):
        return np.full(e.shape, np.nan)
    j = np.searchsorted(times, e, side="right") - 1
    ok = (j >= 0)
    jj = np.clip(j, 0, len(times) - 1)
    age = e - np.asarray(times, np.int64)[jj]
    return np.where(ok & (age <= FUNDING_MAX_AGE_MS), np.asarray(rates, float)[jj], np.nan)


def edges_of(values) -> Optional[list]:
    """The four quintile edges of the finite values (None when fewer than 50)."""
    x = np.asarray(values, float)
    x = x[np.isfinite(x)]
    if len(x) < 50:
        return None
    return [float(v) for v in np.quantile(x, (0.2, 0.4, 0.6, 0.8))]


def q_idx(values, edges: Optional[list]) -> np.ndarray:
    """Quintile index 0..4 by ``edges`` (a value equal to an edge goes up); -1 for NaN or no edges."""
    x = np.asarray(values, float)
    out = np.full(x.shape, -1, dtype=np.int8)
    if not edges:
        return out
    ok = np.isfinite(x)
    out[ok] = np.searchsorted(np.asarray(edges, float), x[ok], side="right").astype(np.int8)
    return out


def r4(x, n: int = 4):
    """A rounded finite float, else None (JSON has no NaN)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None
