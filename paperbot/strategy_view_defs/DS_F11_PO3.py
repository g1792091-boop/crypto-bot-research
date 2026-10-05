"""Chart view for DS_F11_PO3 (DeepSeek-200 F11_PO3, research/deepseek200/PREREG_DEEPSEEK200.md section 5):
what a trader draws for it and its entry conditions, worded for the owners.

Power of 3 (accumulation, manipulation, distribution) per UTC day (= 09:00 KST to 09:00 KST): the range of the bars
starting 00:00-08:00 UTC (09:00-17:00 KST; all of them must be there); a bar starting 08:00-20:00 UTC (17:00-05:00
KST) that pierces only one side; the first close back inside the range on that bar or within the next 3 bars (no
gap) is the signal, against the sweep. One signal a day, the earliest; none if both sides come back on that bar.
The chart draws the range high / low (while being built, then for the rest of the day).

Checked against the research signal (lib_c.entries of research/deepseek200/lib_c.py, loaded by path inside
entry_marks._contained(), so sys.path and the warnings filters are restored): AND of the long (short) conditions
equals the F11_PO3 long (short) signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1}
Series: the full Binance USDT-M bar files 2021-01..2026-09 (BTC 15m 201,398 bars, ETH 1h 50,351, SOL 4h
12,588, DOGE 30m 100,701; signals checked: long 3,132, short 3,457) and 12 live-service frames
built from 5m bars as paperbot.dssig.frame does (config.DS_WINDOW_5M; BTC 15m, ETH 1h, LTC 4h, BCH 30m at
three end dates each; signals checked: long 662, short 719): recall = precision = 1 on all
24 live-frame sides too, 0 differing bars. tests/test_strategy_views_ds_f9_f11.py repeats the check.
"""

import numpy as np
import pandas as pd


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


_TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}
_RANGE_END, _WINDOW_END, _BACK = 8 * 60, 20 * 60, 3      # minutes of the UTC day; reversal bars


def _days(day):
    """(start, end) of each run of equal UTC dates."""
    if len(day) == 0:
        return []
    cut = np.flatnonzero(np.diff(day) != 0) + 1
    return list(zip(np.r_[0, cut].tolist(), np.r_[cut, len(day)].tolist()))


def view_DS_F11_PO3(df, tf):
    """F11_PO3: one-sided sweep of the 00-08 UTC range in 08-20 UTC, first close back inside within 3 bars, the day's
    first such bar. Exact (lib_c.utc_day_signals)."""
    o, h, l, c = _cols(df)
    n = len(c)
    tfm = _TF_MIN.get(tf, 0)
    nr = _RANGE_END // tfm if tfm else 0
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    dayd = ts.astype("datetime64[D]")
    mins = ((ts - dayd.astype("datetime64[ns]")) // np.timedelta64(1, "m")).astype(np.int64)
    ready, inside = np.zeros(n, bool), np.zeros(n, bool)
    wait_l, wait_s = np.zeros(n, bool), np.zeros(n, bool)
    first_l, first_s = np.ones(n, bool), np.ones(n, bool)
    rh_a, rl_a = np.full(n, np.nan), np.full(n, np.nan)
    for a, b in (_days(dayd.astype(np.int64)) if nr >= 1 else []):
        m, hh, ll, cc = mins[a:b], h[a:b], l[a:b], c[a:b]
        m_len = b - a
        k = 0
        while k < min(nr, m_len) and m[k] == k * tfm:      # the range while it is being built (chart only)
            k += 1
        if k:
            rh_a[a:a + k] = np.maximum.accumulate(hh[:k])
            rl_a[a:a + k] = np.minimum.accumulate(ll[:k])
        if not (m_len >= nr and np.array_equal(m[:nr], np.arange(nr) * tfm)):
            continue
        rh, rl = hh[:nr].max(), ll[:nr].min()
        rh_a[a + nr:b], rl_a[a + nr:b] = rh, rl
        ready[a + nr - 1:b] = True
        # causal: before the range is complete (bars 00-08 UTC) the full day's range is not known yet
        inside[a + nr:b] = (rl <= cc[nr:]) & (cc[nr:] <= rh)
        back = {1: [], -1: []}                         # side traded -> bars where a sweep closed back inside
        for k in np.flatnonzero((m >= _RANGE_END) & (m < _WINDOW_END)):
            up, dn = hh[k] > rh, ll[k] < rl
            if up == dn:
                continue
            wait = wait_s if up else wait_l
            for t in range(k, min(k + _BACK + 1, m_len)):
                if m[t] - m[k] != (t - k) * tfm:
                    break
                wait[a + t] = True
                if rl <= cc[t] <= rh:
                    back[-1 if up else 1].append(t)
                    break
        allb = back[1] + back[-1]
        tmin = min(allb) if allb else m_len
        idx = np.arange(m_len)
        first_l[a:b] = (idx <= tmin) & ~np.isin(idx, back[-1])
        first_s[a:b] = (idx <= tmin) & ~np.isin(idx, back[1])
    return {
        "overlays": [
            {"name": "축적 범위 고가(한국 09~17시)", "values": rh_a},
            {"name": "축적 범위 저가(한국 09~17시)", "values": rl_a},
        ],
        "panes": [],
        "long": [
            ("오늘 축적 범위 완성(한국 09~17시)", ready),
            ("범위 아래쪽만 찌름(한국 17시~다음날 05시 봉) 뒤 3봉 안", wait_l),
            ("종가가 범위 안으로 복귀", inside),
            ("오늘 첫 신호(같은 봉 숏 없음)", first_l),
        ],
        "short": [
            ("오늘 축적 범위 완성(한국 09~17시)", ready),
            ("범위 위쪽만 찌름(한국 17시~다음날 05시 봉) 뒤 3봉 안", wait_s),
            ("종가가 범위 안으로 복귀", inside),
            ("오늘 첫 신호(같은 봉 롱 없음)", first_s),
        ],
    }
