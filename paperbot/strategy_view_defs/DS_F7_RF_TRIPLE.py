"""Chart view for DS_F7_RF_TRIPLE: DeepSeek-200 definition F7_RF_TRIPLE (F7 Range Filter 3중 일치), its lines and entry
conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F7): three things agree for the first time (the previous bar they did not):
the Range Filter direction (DonovanWall, close, 100 / 3.0, as F7_RF_ONLY) is +1, this bar's Heikin-Ashi candle is up,
and the Heikin-Ashi candle of the last higher-timeframe bar closed at or before this bar's close is up -> long. All
three down -> short. Heikin-Ashi: HAc = (O+H+L+C)/4, HAo[0] = (O[0]+C[0])/2, HAo[t] = (HAo[t-1]+HAc[t-1])/2, up =
HAc > HAo, down = HAc < HAo. Higher timeframe (lib_c.HTF_OF): 15m -> 1h, 30m -> 2h, 1h -> 4h, 4h -> 1d, built from
the chart bars with the locked resample_ohlcv and matched as research/search/search.htf_series does.

The chart shows the filter with its upper and lower lines (as F7_RF_ONLY) and a pane with the agreement score: filter
direction + this bar's Heikin-Ashi (+1 up, -1 down) + the higher-timeframe Heikin-Ashi (+3 = all up, -3 = all down).

Same rules as research/deepseek200/lib_c.py ``entries()`` / ``range_filter_dir()`` / ``heikin_bull()`` /
``htf_value()`` (the live signal is paperbot/dssig.py), written again with numpy / pandas and the locked sweep_lib;
lib_c is not imported here. lib_c drops both sides when long and short fire on one bar; here the sides exclude each
other (direction +1 vs -1), so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 21,059 / short 20,079; live frames long 31,445 / short 31,036; 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f4_f7.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pandas as pd
import sweep_lib as L

_HTF_OF = {"15m": "1h", "30m": "2h", "1h": "4h", "4h": "1d"}           # lib_c.HTF_OF
_KO_HTF = {"1h": "1시간봉", "2h": "2시간봉", "4h": "4시간봉", "1d": "일봉"}


def _prev(x, k=1):
    """Value of the bar k bars back (NaN where there is none)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _prevb(x, k=1):
    """Boolean value of the bar k bars back (False where there is none)."""
    x = np.asarray(x, bool)
    out = np.zeros(len(x), bool)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _range_filter(c):
    """(filter, range, direction) exactly as lib_c.range_filter_dir (which returns the direction only)."""
    c = np.asarray(c, float)
    n = len(c)
    d = pd.Series(c).diff().abs().fillna(0.0)
    avr = d.ewm(span=100, adjust=False).mean()
    rng = (3.0 * avr.ewm(span=199, adjust=False).mean()).to_numpy(dtype=float)
    filt, out = np.full(n, np.nan), np.zeros(n)
    if not n:
        return filt, rng, out
    x, r = c.tolist(), rng.tolist()
    f, dr = x[0], 0
    filt[0] = f
    for i in range(1, n):
        xi, ri = x[i], r[i]
        if xi - ri > f:
            nf = xi - ri
        elif xi + ri < f:
            nf = xi + ri
        else:
            nf = f
        if nf > f:
            dr = 1
        elif nf < f:
            dr = -1
        f = nf
        filt[i] = f
        out[i] = dr
    return filt, rng, out


def _heikin(o, h, l, c):
    """1.0 where the Heikin-Ashi candle is up, 0.0 down, 0.5 flat (lib_c.heikin_bull)."""
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    hac = (o + h + l + c) / 4
    hao = np.empty(len(c))
    if len(c):
        hao[0] = (o[0] + c[0]) / 2
        b = hac.tolist()
        prev = hao[0]
        for i in range(1, len(c)):
            prev = (prev + b[i - 1]) / 2
            hao[i] = prev
    return np.where(hac > hao, 1.0, np.where(hac < hao, 0.0, 0.5))


def _htf_heikin(df, tf):
    """Heikin-Ashi colour of the last higher-timeframe bar closed at or before each chart bar's close (NaN before)."""
    n = len(df)
    if not n:
        return np.zeros(0)
    htf = _HTF_OF[tf]
    dh = L.resample_ohlcv(df, htf)
    vals = np.asarray(_heikin(*(dh[k].to_numpy(float) for k in ("open", "high", "low", "close"))), dtype=float)
    hclose = L.htf_close_ns(dh["ts"], htf)
    cclose = L._utc_ns(df["ts"]) + np.timedelta64(L.tf_minutes(tf), "m")
    j = np.searchsorted(hclose, cclose, side="right") - 1
    return np.where(j >= 0, vals[np.clip(j, 0, len(vals) - 1)], np.nan)


def view_DS_F7_RF_TRIPLE(df, tf):
    """F7_RF_TRIPLE: first bar where Range Filter direction, Heikin-Ashi and higher-timeframe Heikin-Ashi agree.
    Exact."""
    o, h, l, c = (np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))
    filt, rng, rf = _range_filter(c)
    f1 = _prev(filt)
    ha = _heikin(o, h, l, c)
    hha = _htf_heikin(df, tf)
    hk = _KO_HTF.get(_HTF_OF.get(tf, ""), "상위봉")
    with np.errstate(invalid="ignore"):
        all_up = (rf == 1) & (ha == 1) & (hha == 1)
        all_dn = (rf == -1) & (ha == 0) & (hha == 0)
        score = rf + (2 * ha - 1) + np.nan_to_num(2 * hha - 1)
    return {
        "overlays": [
            {"name": "범위 필터선", "values": filt},
            {"name": "위쪽 경계(종가가 넘으면 필터 상승)", "values": f1 + rng},
            {"name": "아래쪽 경계(종가가 밑돌면 필터 하락)", "values": f1 - rng},
        ],
        "panes": [
            {"name": f"3중 일치 점수(필터·하이킨아시·{hk}: +3 롱 · -3 숏)",
             "series": [{"name": "일치 점수", "values": np.asarray(score, float)}], "levels": [-3, 0, 3]},
            {"name": f"하이킨아시 방향(+1 양봉 · -1 음봉 · 0 같음): 이 봉과 {hk}",
             "series": [{"name": "하이킨아시(이 봉)", "values": 2 * np.asarray(ha, float) - 1},
                        {"name": f"{hk} 하이킨아시(마감된 봉)", "values": 2 * np.asarray(hha, float) - 1}],
             "levels": [-1, 0, 1]},
        ],
        "long": [
            ("범위 필터 방향 상승(+1)", rf == 1),
            ("하이킨아시 양봉", ha == 1),
            (f"{hk} 하이킨아시 양봉(마감된 봉)", hha == 1),
            ("직전 봉엔 셋이 다 맞지 않음(이번 봉에 처음 일치)", ~_prevb(all_up)),
        ],
        "short": [
            ("범위 필터 방향 하락(-1)", rf == -1),
            ("하이킨아시 음봉", ha == 0),
            (f"{hk} 하이킨아시 음봉(마감된 봉)", hha == 0),
            ("직전 봉엔 셋이 다 맞지 않음(이번 봉에 처음 일치)", ~_prevb(all_dn)),
        ],
    }
