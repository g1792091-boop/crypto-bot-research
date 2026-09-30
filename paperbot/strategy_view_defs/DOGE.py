"""Chart view for DOGE: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import math
import numpy as np
import pandas as pd
import doge_strategy as ds


_TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440, "1w": 10080}
_DOGE_LEN_KEYS = ["ema_fast", "ema_slow", "ema_trend", "ema_short", "stoch_rsi_len", "stoch_len", "k_smooth",
                  "d_smooth", "rsi_len", "chop_len"]


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


def _doge_params(tf):
    """Same rule as sweep_lib.doge_params: length / (tf minutes / 5), round half up, min 2."""
    ratio = _TF_MIN[tf] / 5.0
    p = {}
    for k in _DOGE_LEN_KEYS:
        p[k] = max(2, int(math.floor(ds.DEFAULT[k] / ratio + 0.5))) if ratio > 1 else ds.DEFAULT[k]
    return p


def view_DOGE(df, tf):
    if len(df) == 0:
        return _no_bars_v45doge(view_DOGE, tf)
    p = _doge_params(tf)
    P = ds._p(p)
    d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[["open", "high", "low", "close", "volume"]]
    ind = ds.compute_indicators(d, p)
    c = d["close"].to_numpy(dtype=float)
    f, s, t, e = (ind[k].to_numpy() for k in ("ema_fast", "ema_slow", "ema_trend", "ema_short"))
    sp, ch, K, D, r = (ind[k].to_numpy() for k in ("spread_pct", "chop", "K", "D", "rsi26"))
    xa = ds.cross_above(ind["K"], ind["D"], P["cross"])
    xb = ds.cross_below(ind["K"], ind["D"], P["cross"])
    kmax, rmin, smin, cmax = P["k_max"], P["rsi_min"], P["spread_min"], P["chop_max"]
    with np.errstate(invalid="ignore"):
        long = [
            ("빠른선이 느린선 위(0.15%↑)", (f > s) & (sp > smin)),
            ("가격이 추세선·단기선 위", (c > t) & (c > e)),
            ("횡보지수 61.8 미만", ch < cmax),
            ("K가 D 위로 교차(K<45)", xa & (K < kmax)),
            ("RSI 52 초과", r > rmin),
        ]
        short = [
            ("빠른선이 느린선 밑(0.15%↓)", (f < s) & (sp < -smin)),
            ("가격이 추세선·단기선 아래", (c < t) & (c < e)),
            ("횡보지수 61.8 미만", ch < cmax),
            ("K가 D 아래로 교차(K>55)", xb & (K > 100 - kmax)),
            ("RSI 48 미만", r < 100 - rmin),
        ]
    return {
        "overlays": [
            {"name": f"EMA{p['ema_fast']} (빠른선)", "values": f},
            {"name": f"EMA{p['ema_slow']} (느린선)", "values": s},
            {"name": f"EMA{p['ema_trend']} (추세선)", "values": t},
            {"name": f"EMA{p['ema_short']} (단기선)", "values": e},
        ],
        "panes": [
            {"name": f"스토캐스틱 RSI {p['stoch_rsi_len']}", "series": [
                {"name": "K", "values": K},
                {"name": "D", "values": D}], "levels": [45, 55]},
            {"name": f"RSI {p['rsi_len']} · 횡보지수 {p['chop_len']}", "series": [
                {"name": f"RSI {p['rsi_len']}", "values": r},
                {"name": "횡보지수", "values": ch}], "levels": [48, 52, 61.8]},
        ],
        "long": [(lab, np.asarray(v, bool)) for lab, v in long],
        "short": [(lab, np.asarray(v, bool)) for lab, v in short],
    }
