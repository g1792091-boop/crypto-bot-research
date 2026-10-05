"""Chart view for DS_F7_RF_ONLY: DeepSeek-200 definition F7_RF_ONLY (F7 Range Filter), its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F7): DonovanWall Range Filter on the close, 100 / 3.0:
avr = EMA(|C - C[-1]|, 100), range = 3.0 x EMA(avr, 199) (ewm span, adjust=False); filter[0] = C[0]; then with
f = filter[t-1]: C - range > f -> filter = C - range; C + range < f -> filter = C + range; else filter = f. Direction:
+1 when the filter rose, -1 when it fell, else unchanged (0 before the first move). Long on the bar the direction
turns from -1 to +1, short from +1 to -1.

Checklist: with the direction -1 on the previous bar it turns +1 exactly when the close minus the range is above the
previous filter (the close clears the upper line), and mirrored for the short, so the two lines are the definition.
The chart shows the filter, its upper line (previous filter + this bar's range: a close above it lifts the filter)
and lower line (previous filter - range), and the direction in a pane.

Same rules as research/deepseek200/lib_c.py ``entries()`` / ``range_filter_dir()`` (the live signal is
paperbot/dssig.py), written again with numpy / pandas; lib_c is not imported here. lib_c drops both sides when long and
short fire on one bar; here the sides exclude each other (previous direction -1 vs +1), so that rule never acts.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 5,331 / short 5,334; live frames long 9,993 / short 9,988; 0 differing bars.
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


def view_DS_F7_RF_ONLY(df, tf):
    """F7_RF_ONLY: the Range Filter direction turns (-1 -> +1 long, +1 -> -1 short). Exact."""
    c = np.asarray(df["close"], dtype=float)
    filt, rng, rf = _range_filter(c)
    f1, rf1 = _prev(filt), _prev(rf)
    with np.errstate(invalid="ignore"):
        lift = c - rng > f1          # the filter rises on this bar
        drop = c + rng < f1          # the filter falls on this bar
    return {
        "overlays": [
            {"name": "범위 필터선", "values": filt},
            {"name": "위쪽 경계(종가가 넘으면 필터 상승)", "values": f1 + rng},
            {"name": "아래쪽 경계(종가가 밑돌면 필터 하락)", "values": f1 - rng},
        ],
        "panes": [
            {"name": "범위 필터 방향(+1 상승 · -1 하락)", "series": [{"name": "방향", "values": rf}], "levels": [0]},
        ],
        "long": [
            ("직전 봉까지 범위 필터 하락(-1)", rf1 == -1),
            ("종가가 위쪽 경계 돌파(상승으로 전환)", np.asarray(lift, bool)),
        ],
        "short": [
            ("직전 봉까지 범위 필터 상승(+1)", rf1 == 1),
            ("종가가 아래쪽 경계 이탈(하락으로 전환)", np.asarray(drop, bool)),
        ],
    }
