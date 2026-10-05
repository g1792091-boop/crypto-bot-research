"""Chart view for DS_F17_Z (DeepSeek-200 F17_Z, research/deepseek200/PREREG_DEEPSEEK200.md section 5):
what a trader draws for it and its entry conditions, worded for the owners.

Z-score mean reversion: Z = (close - SMA20) / population std of the last 20 closes. Long on the first bar
with Z < -2 (the bar before had Z >= -2), short on the first bar with Z > +2. Z = -2 / +2 are the Bollinger(20, 2)
bands, so the chart draws the 20-bar mean and those two lines, and a pane with Z and its -2 / 0 / +2 levels.
Z < -2 and Z > +2 cannot hold on one bar, so lib_c's same-bar long/short rule never removes a signal here.

Checked against the research signal (lib_c.entries of research/deepseek200/lib_c.py, loaded by path inside
entry_marks._contained(), so sys.path and the warnings filters are restored): AND of the long (short) conditions
equals the F17_Z long (short) signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1}
Series: the full Binance USDT-M bar files 2021-01..2026-09 (BTC 15m 201,398 bars, ETH 1h 50,351, SOL 4h
12,588, DOGE 30m 100,701; signals checked: long 11,485, short 10,944) and 12 live-service frames
built from 5m bars as paperbot.dssig.frame does (config.DS_WINDOW_5M; BTC 15m, ETH 1h, LTC 4h, BCH 30m at
three end dates each; signals checked: long 1,280, short 1,261): recall = precision = 1 on all
24 live-frame sides too, 0 differing bars. tests/test_strategy_views_ds_f16_f17.py repeats the check.
"""

import numpy as np
import pandas as pd

_LEN = 20                      # Z = (close - SMA20) / population std of the last 20 closes (PREREG F17)
_Z = 2.0


def _prev(x):
    """The previous bar's value (NaN on the first bar), the same as lib_c._prev but for any length."""
    out = np.full(len(x), np.nan)
    out[1:] = x[:-1]
    return out


def _zscore(c):
    """lib_c's Z-score with the same pandas calls (rolling(20).mean, rolling(20).std(ddof=0)): identical floats.
    Also the price lines Z = +2 / -2 for the chart (SMA20 +- 2 population std, the Bollinger(20, 2) bands)."""
    s = pd.Series(c)
    sma = s.rolling(_LEN).mean()
    sd = s.rolling(_LEN).std(ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = ((s - sma) / sd).to_numpy()
    return z, sma.to_numpy(dtype=float), (sma + _Z * sd).to_numpy(dtype=float), (sma - _Z * sd).to_numpy(dtype=float)


def view_DS_F17_Z(df, tf):
    """F17_Z: the first bar beyond Z = -2 (long) / +2 (short). Exact."""
    c = np.asarray(df["close"], dtype=float)
    z, sma, up2, dn2 = _zscore(c)
    zp = _prev(z)
    with np.errstate(invalid="ignore"):
        long = [
            ("종가가 20봉 평균보다 표준편차 2배 넘게 아래 (Z < −2)", z < -_Z),
            ("직전 봉은 Z −2 이상 (이번 봉에 처음 내려옴)", zp >= -_Z),
        ]
        short = [
            ("종가가 20봉 평균보다 표준편차 2배 넘게 위 (Z > +2)", z > _Z),
            ("직전 봉은 Z +2 이하 (이번 봉에 처음 올라옴)", zp <= _Z),
        ]
    return {
        "overlays": [
            {"name": "20봉 평균", "values": sma},
            {"name": "평균 + 표준편차 2배 (Z = +2)", "values": up2},
            {"name": "평균 − 표준편차 2배 (Z = −2)", "values": dn2},
        ],
        "panes": [
            {"name": "Z점수 (20봉)", "series": [{"name": "Z점수", "values": z}], "levels": [-2, 0, 2]},
        ],
        "long": [(k, np.asarray(a, bool)) for k, a in long],
        "short": [(k, np.asarray(a, bool)) for k, a in short],
    }
