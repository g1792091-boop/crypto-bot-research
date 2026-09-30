"""Chart view for V45_AMB: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import pine_indicators as pi


_TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440, "1w": 10080}
_HTF_OF = {"5m": "15m", "15m": "1h", "30m": "2h", "1h": "4h", "4h": "1d", "1d": "1w"}
_RULE = {"15m": "15min", "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D", "1w": "W-MON"}
_KO_TF = {"15m": "15분", "1h": "1시간", "2h": "2시간", "4h": "4시간", "1d": "1일", "1w": "1주"}


def _utc_ns(s):
    s = pd.to_datetime(pd.Series(s), utc=True)
    return s.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]")


def _resample(df, tf_out):
    """Same as sweep_lib.resample_ohlcv: UTC, open-labelled, left-closed bins, empty bins dropped,
    partial bins kept."""
    x = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[["open", "high", "low", "close", "volume"]]
    agg = x.resample(_RULE[tf_out], label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    agg = agg.dropna(subset=["close"])
    agg.index.name = "ts"
    return agg.reset_index()


def _no_bars_v45doge(fn, tf):
    """0 bars: same lines and labels with length-0 arrays (the indicator code cannot run on 0 bars)."""
    one = pd.DataFrame({"ts": [pd.Timestamp("2020-01-06", tz="UTC")], "open": [1.0], "high": [1.0],
                        "low": [1.0], "close": [1.0], "volume": [0.0]})
    v = fn(one, tf)
    cut = lambda a: np.asarray(a)[:0]
    return {"overlays": [dict(o, values=cut(o["values"])) for o in v["overlays"]],
            "panes": [dict(p, series=[dict(s, values=cut(s["values"])) for s in p["series"]]) for p in v["panes"]],
            "long": [(k, cut(a)) for k, a in v["long"]],
            "short": [(k, cut(a)) for k, a in v["short"]]}


def view_V45_AMB(df, tf):
    if len(df) == 0:
        return _no_bars_v45doge(view_V45_AMB, tf)
    h = np.asarray(df["high"], dtype=float)
    l = np.asarray(df["low"], dtype=float)
    c = np.asarray(df["close"], dtype=float)
    n = len(c)
    htf = _HTF_OF[tf]
    hk = _KO_TF.get(htf, htf)

    # chart timeframe: two SuperTrends (ATR 14, x6 main / x3 strict)
    st_main, dm = pi.exchange_supertrend(h, l, c, 14, 6.0)
    st_str, dsx = pi.exchange_supertrend(h, l, c, 14, 3.0)

    # higher timeframe built from the chart bars; value of the last HTF bar CLOSED by this bar's open
    dfh = _resample(df, htf)
    hh, lh, ch = (np.asarray(dfh[k], dtype=float) for k in ("high", "low", "close"))
    if len(ch):
        st_h, dh = pi.exchange_supertrend(hh, lh, ch, 14, 6.0)
        stc_h = pi.stc(ch, 12, 26, 50, 0.5)
        key = _utc_ns(dfh["ts"]) + np.timedelta64(_TF_MIN[htf], "m")
        idx = np.searchsorted(key, _utc_ns(df["ts"]), side="right") - 1
        ok = idx >= 0
        ic = np.clip(idx, 0, len(ch) - 1)
        dhm = np.where(ok, dh[ic], 0)
        stc_hm = np.where(ok, stc_h[ic], np.nan)
        st_hm = np.where(ok, st_h[ic], np.nan)
    else:
        dhm, stc_hm, st_hm = np.zeros(n), np.full(n, np.nan), np.full(n, np.nan)

    # MACD(12,26,9) histogram, AO(5,34) / AC(5), chop-zone angle (EMA34), STC(12,26,50)
    _ml, _ms, hist = pi.pine_macd(c, 12, 26, 9)
    hp = pi.shift1(hist)
    ao, ac = pi.ao_ac(h, l, 5, 34, 5)
    aop, acp = pi.shift1(ao), pi.shift1(ac)
    chop = pi.chop_angle(h, l, c, 34, 30, 25.0)
    ema34 = pi.pine_ema(c, 34)
    stc_c = pi.stc(c, 12, 26, 50, 0.5)

    # three stochastics: (14,3,3), (14,4,3), StochRSI(14,14,5,3)
    raw = pi.pine_stoch(c, h, l, 14)
    k33 = pi.pine_sma(raw, 3); d33 = pi.pine_sma(k33, 3)
    k43 = pi.pine_sma(raw, 4); d43 = pi.pine_sma(k43, 3)
    kr, dr = pi.stoch_rsi_kd(c, 14, 14, 5, 3)

    with np.errstate(invalid="ignore"):
        opposite = ((dm == 1) & (dsx == -1)) | ((dm == -1) & (dsx == 1))
        ready = np.isfinite(stc_c) & np.isfinite(stc_hm)
        htf_long = (dhm == 1) & ready & ~(stc_c >= 75.0) & ~(stc_hm >= 75.0)
        htf_short = (dhm == -1) & ready & ~(stc_c <= 25.0) & ~(stc_hm <= 25.0)
        chop_bear, chop_bull = chop <= -0.71, chop >= 0.71
        g = [pi.crossover(k, d) & ((k <= 50) | (d <= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
        dd = [pi.crossunder(k, d) & ((k >= 50) | (d >= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
        trig_long = np.logical_or.reduce(g) & (hist < 0.0) & (hist > hp)
        trig_short = np.logical_or.reduce(dd) & (hist > 0.0) & (hist < hp)
        not_c_long = ~((ac < 0) & (ac > acp) & (ao < 0) & (ao < aop))
        not_c_short = ~((ac > 0) & (ac < acp) & (ao > 0) & (ao > aop))

    return {
        "overlays": [
            {"name": "슈퍼트렌드 14·6", "values": st_main},
            {"name": "슈퍼트렌드 14·3", "values": st_str},
            {"name": f"{hk} 슈퍼트렌드", "values": st_hm},
            {"name": "EMA34 (기울기 기준)", "values": ema34},
        ],
        "panes": [
            {"name": "STC 과열 필터", "series": [
                {"name": "STC", "values": stc_c},
                {"name": f"STC {hk}", "values": stc_hm}], "levels": [25, 75]},
            {"name": "MACD·AO·AC", "series": [
                {"name": "MACD 히스토그램", "values": hist},
                {"name": "AO", "values": ao},
                {"name": "AC", "values": ac}], "levels": [0]},
        ],
        "long": [
            (f"{hk} 상승·STC 75 미만", np.asarray(htf_long, bool)),
            ("두 슈퍼트렌드 엇갈림", np.asarray(opposite, bool)),
            ("EMA34 기울기 하락", np.asarray(chop_bear, bool)),
            ("스토캐스틱 저점교차·MACD 반등", np.asarray(trig_long, bool)),
            ("AO 하락+AC 반등 제외", np.asarray(not_c_long, bool)),
        ],
        "short": [
            (f"{hk} 하락·STC 25 초과", np.asarray(htf_short, bool)),
            ("두 슈퍼트렌드 엇갈림", np.asarray(opposite, bool)),
            ("EMA34 기울기 상승", np.asarray(chop_bull, bool)),
            ("스토캐스틱 고점교차·MACD 둔화", np.asarray(trig_short, bool)),
            ("AO 상승+AC 하락 제외", np.asarray(not_c_short, bool)),
        ],
    }
