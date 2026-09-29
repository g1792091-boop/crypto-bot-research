"""Documented structural stops (31-set report, doc_31set.txt lines 219-330) for the 19
31-set strategies stage 1 DID test, wrapped around the unchanged stage-1 signal functions.
Only the initial stop is modelled (native-lite: no trailing, no strategy-specific exit;
opposite signal CONFIRM_2 only)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import fg_indicators as fg
import fg_fast
import strategies as ST
from strategies import _b, _f
from ports12 import _roll_min, _roll_max, _base, _pack


def _bar(df, nL, k):  # recent-n low/high -/+ k*ATR
    o, h, l, c, a = _base(df)
    return _roll_min(l, nL) - k * a, _roll_max(h, nL) + k * a


def wrap17():
    out = {}

    def mk(name, fn, stopfn):
        def f(df, variant=0):
            L, S = fn(df)
            sl, ss = stopfn(df)
            return _pack(L, S, sl, ss)
        out[name] = f

    def st_line(df, length=10, mult=6.0):
        line, d, _u, _l = fg_fast.supertrend(df, length, mult)
        return _f(line)

    mk("S2_ST_ROC", ST.s2_supertrend_roc, lambda d: (st_line(d), st_line(d)))
    mk("S5_DONCHIAN_MFI", ST.s5_donchian_mfi, lambda d: _bar(d, 1, 0.1))
    mk("S6_EMA_DMI_ADX", ST.s6_ema_dmi_adx, lambda d: _bar(d, 1, 0.1))

    def n01_stop(df):
        sl, ss = _bar(df, 3, 0.1); line = st_line(df)
        return np.fmax(sl, line), np.fmin(ss, line)
    mk("N01_ST_EMA", ST.n01_supertrend_ema, n01_stop)
    mk("N02_ST_KST", ST.n02_supertrend_kst, lambda d: (st_line(d), st_line(d)))
    mk("N03_ADX_GC", ST.n03_adx_golden_cross, lambda d: _bar(d, 5, 0.1))
    for nm, fn in (("N07_ICHI_CMO", ST.n07_ichimoku_cmo), ("N08_ICHI_WR", ST.n08_ichimoku_williams),
                   ("N12_ICHI_AO", ST.n12_ichimoku_ao), ("N09_ALLIG_AROON", ST.n09_alligator_aroon)):
        mk(nm, fn, lambda d: _bar(d, 4, 0.1))
    mk("N10_HA_PSAR", ST.n10_heikin_psar, lambda d: _bar(d, 3, 0.1))

    def n17_stop(df):
        o, h, l, c, a = _base(df)
        mid = _f(fg.ema(df["close"], 20))
        return np.fmin(_roll_min(l, 6), mid - 2 * a) - 0.25 * a, np.fmax(_roll_max(h, 6), mid + 2 * a) + 0.25 * a
    mk("N17_KC_RSI", ST.n17_keltner_rsi, n17_stop)

    def n18_stop(df):
        o, h, l, c, a = _base(df)
        v = _f(fg.vwma(df, 20))
        return np.fmin(_roll_min(l, 8), v) - 0.25 * a, np.fmax(_roll_max(h, 8), v) + 0.25 * a
    mk("N18_VWMA_MACD", ST.n18_vwma_macd, n18_stop)

    def n22_stop(df):
        o, h, l, c, a = _base(df)
        ps, _d = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2); ps = _f(ps)
        return np.fmin(_roll_min(l, 8), ps) - 0.25 * a, np.fmax(_roll_max(h, 8), ps) + 0.25 * a
    mk("N22_VORTEX_PSAR", ST.n22_vortex_psar, n22_stop)

    def n23_stop(df):
        o, h, l, c, a = _base(df)
        ha = fg_fast.heikin_ashi(df)
        red = _f(ha["ha_close"]) < _f(ha["ha_open"]); grn = _f(ha["ha_close"]) > _f(ha["ha_open"])
        last_red_low = pd.Series(np.where(red, l, np.nan)).ffill().to_numpy()
        last_grn_high = pd.Series(np.where(grn, h, np.nan)).ffill().to_numpy()
        return (np.fmin(last_red_low, _roll_min(l, 8) - 0.25 * a),
                np.fmax(last_grn_high, _roll_max(h, 8) + 0.25 * a))
    mk("N23_HA_ST", ST.n23_heikin_supertrend, n23_stop)

    def n24_stop(df):
        o, h, l, c, a = _base(df)
        return np.fmin(l, _roll_min(l, 8) - 0.25 * a), np.fmax(h, _roll_max(h, 8) + 0.25 * a)
    mk("N24_DMI", ST.n24_dmi, n24_stop)

    def n25_stop(df):
        o, h, l, c, a = _base(df)
        c10, c20 = st_line(df, 10, 6.0), st_line(df, 20, 6.0)
        candL = np.vstack([_roll_min(l, 13) - 0.25 * a, c10, c20])
        candS = np.vstack([_roll_max(h, 13) + 0.25 * a, c10, c20])
        with np.errstate(invalid="ignore"):
            sl = np.where(candL < c, candL, np.inf).min(axis=0)
            ss = np.where(candS > c, candS, -np.inf).max(axis=0)
        sl[~np.isfinite(sl)] = np.nan; ss[~np.isfinite(ss)] = np.nan
        return sl, ss
    mk("N25_DST_CCI", ST.n25_double_supertrend_cci, n25_stop)
    return out


TESTED17 = wrap17()
