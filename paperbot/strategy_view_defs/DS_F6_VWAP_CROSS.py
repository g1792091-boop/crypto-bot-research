"""Chart view for DS_F6_VWAP_CROSS: DeepSeek-200 definition F6_VWAP_CROSS (F6 VWAP), its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F6): VWAP anchored to the UTC day (it starts again at 00:00 UTC = 09:00 KST):
typical price (H+L+C)/3 times volume, summed from the day's first bar up to and including this bar, over the
summed volume (no value while the day's volume is 0). Long when the previous close was at or below VWAP and this
close is above it, both bars on the same UTC day (never on a day's first bar); short mirrored. The chart shows the
day's VWAP.

Same rules as research/deepseek200/lib_c.py ``entries()`` / ``daily_vwap()`` (the live signal is paperbot/dssig.py),
written again with numpy / pandas; lib_c is not imported here. lib_c drops both sides when long and short fire on
one bar; here the sides exclude each other (close above vs below VWAP), so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 23,952 / short 23,999; live frames long 39,587 / short 39,723; 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f4_f7.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pandas as pd


def _prev(x, k=1):
    """Value of the bar k bars back (NaN where there is none)."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _daily_vwap(df):
    """(VWAP anchored at 00:00 UTC each day including the bar, UTC day number) exactly as lib_c.daily_vwap."""
    h, l, c, v = (np.asarray(df[k], dtype=float) for k in ("high", "low", "close", "volume"))
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    day = np.asarray(ts, "datetime64[ns]").astype("datetime64[D]").astype(np.int64)
    tp = (h + l + c) / 3
    g = pd.DataFrame({"d": day, "pv": tp * v, "v": v}).groupby("d")
    cpv, cv = g["pv"].cumsum().to_numpy(dtype=float), g["v"].cumsum().to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(cv > 0, cpv / cv, np.nan)
    return vw, day


def view_DS_F6_VWAP_CROSS(df, tf):
    """F6_VWAP_CROSS: the close crosses the UTC-day VWAP, both bars on the same day. Exact."""
    c = np.asarray(df["close"], dtype=float)
    vw, day = _daily_vwap(df)
    same = np.zeros(len(c), bool)
    same[1:] = day[1:] == day[:-1]
    c1, vw1 = _prev(c), _prev(vw)
    with np.errstate(invalid="ignore"):
        long = [
            ("하루 첫 봉 아님(VWAP는 매일 오전 9시 새로 시작)", same),
            ("직전 봉 종가가 VWAP 이하", c1 <= vw1),
            ("이번 봉 종가가 VWAP 위로 돌파", c > vw),
        ]
        short = [
            ("하루 첫 봉 아님(VWAP는 매일 오전 9시 새로 시작)", same),
            ("직전 봉 종가가 VWAP 이상", c1 >= vw1),
            ("이번 봉 종가가 VWAP 아래로 이탈", c < vw),
        ]
    return {
        "overlays": [{"name": "VWAP (매일 오전 9시 시작)", "values": vw}],
        "panes": [],
        "long": [(k, np.asarray(a, bool)) for k, a in long],
        "short": [(k, np.asarray(a, bool)) for k, a in short],
    }
