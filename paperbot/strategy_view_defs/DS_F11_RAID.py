"""Chart view for DS_F11_RAID (DeepSeek-200 F11_RAID, research/deepseek200/PREREG_DEEPSEEK200.md section 5):
what a trader draws for it and its entry conditions, worded for the owners.

Liquidity raid: the last confirmed swing low (3 bars each side, known 3 bars later) is pierced by a low for the
first time and the same bar closes back above it (short mirrored on the swing high). A level counts once; a newly
confirmed swing becomes the new level. The chart draws the swing high / low while they are not pierced yet.

Checked against the research signal (lib_c.entries of research/deepseek200/lib_c.py, loaded by path inside
entry_marks._contained(), so sys.path and the warnings filters are restored): AND of the long (short) conditions
equals the F11_RAID long (short) signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1}
Series: the full Binance USDT-M bar files 2021-01..2026-09 (BTC 15m 201,398 bars, ETH 1h 50,351, SOL 4h
12,588, DOGE 30m 100,701; signals checked: long 8,266, short 8,404) and 12 live-service frames
built from 5m bars as paperbot.dssig.frame does (config.DS_WINDOW_5M; BTC 15m, ETH 1h, LTC 4h, BCH 30m at
three end dates each; signals checked: long 976, short 1,027): recall = precision = 1 on all
24 live-frame sides too, 0 differing bars. tests/test_strategy_views_ds_f9_f11.py repeats the check.
"""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

_SW = 3            # swing pivot: 3 bars on each side, known 3 bars later (PREREG section 4)


def _cols(df):
    return tuple(np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))


def _pivots(h, l, k=_SW):
    """lib_c.pivots_conf: True at bar t when the swing high / low of bar t-3 is confirmed (strictly above / below the
    3 bars on each side)."""
    n = len(h)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    if n >= 2 * k + 1:
        wh = sliding_window_view(np.asarray(h, float), 2 * k + 1)
        wl = sliding_window_view(np.asarray(l, float), 2 * k + 1)
        with np.errstate(invalid="ignore"):
            okh = (wh[:, k] > wh[:, :k].max(1)) & (wh[:, k] > wh[:, k + 1:].max(1))
            okl = (wl[:, k] < wl[:, :k].min(1)) & (wl[:, k] < wl[:, k + 1:].min(1))
        ph[2 * k:] = okh
        pl[2 * k:] = okl
    return ph, pl


def _structure(h, l, c):
    """lib_c.structure, one causal pass: last confirmed swing levels, BOS / MSS breaks, liquidity raids. Also the
    raid state each bar is checked with (a swing level not pierced yet) for the checklist and the chart."""
    n = len(c)
    ph, pl = _pivots(h, l)
    nan = float("nan")
    hi_a, lo_a = np.full(n, nan), np.full(n, nan)
    hi_i, lo_i = np.full(n, -1), np.full(n, -1)
    mss_up, mss_dn = np.zeros(n, bool), np.zeros(n, bool)
    raid_long, raid_short = np.zeros(n, bool), np.zeros(n, bool)
    hi_open, lo_open = np.zeros(n, bool), np.zeros(n, bool)
    hl, ll, cl = np.asarray(h, float).tolist(), np.asarray(l, float).tolist(), np.asarray(c, float).tolist()
    phc, plc = ph.tolist(), pl.tolist()
    hi_lvl = lo_lvl = nan
    hi_idx = lo_idx = -1
    hi_bos = lo_bos = hi_raid = lo_raid = False
    state = 0
    for t in range(n):
        if phc[t]:
            hi_lvl, hi_idx = hl[t - _SW], t - _SW
            hi_bos = hi_raid = True
        if plc[t]:
            lo_lvl, lo_idx = ll[t - _SW], t - _SW
            lo_bos = lo_raid = True
        hi_a[t], lo_a[t], hi_i[t], lo_i[t] = hi_lvl, lo_lvl, hi_idx, lo_idx
        ct = cl[t]
        up = hi_bos and ct > hi_lvl
        dn = lo_bos and ct < lo_lvl
        if up and not dn:
            if state == -1:
                mss_up[t] = True
            state = 1
            hi_bos = False
        elif dn and not up:
            if state == 1:
                mss_dn[t] = True
            state = -1
            lo_bos = False
        hi_open[t], lo_open[t] = hi_raid, lo_raid
        if hi_raid and hl[t] > hi_lvl:
            hi_raid = False
            if ct < hi_lvl:
                raid_short[t] = True
        if lo_raid and ll[t] < lo_lvl:
            lo_raid = False
            if ct > lo_lvl:
                raid_long[t] = True
    return dict(ph_conf=ph, pl_conf=pl, hi=hi_a, lo=lo_a, hi_idx=hi_i, lo_idx=lo_i, mss_up=mss_up, mss_dn=mss_dn,
                raid_long=raid_long, raid_short=raid_short, hi_open=hi_open, lo_open=lo_open)


def view_DS_F11_RAID(df, tf):
    """F11_RAID: first pierce of the last confirmed swing level, closed back on the other side. Exact."""
    o, h, l, c = _cols(df)
    st = _structure(h, l, c)
    with np.errstate(invalid="ignore"):
        lo_hit, lo_back = l < st["lo"], c > st["lo"]
        hi_hit, hi_back = h > st["hi"], c < st["hi"]
    return {
        "overlays": [
            {"name": "아직 안 찔린 스윙 고점", "values": np.where(st["hi_open"], st["hi"], np.nan)},
            {"name": "아직 안 찔린 스윙 저점", "values": np.where(st["lo_open"], st["lo"], np.nan)},
        ],
        "panes": [],
        "long": [
            ("아직 아무 봉도 찌르지 않은 스윙 저점 있음", st["lo_open"]),
            ("저가가 스윙 저점 아래로 찌름", lo_hit),
            ("종가는 스윙 저점 위로 회복", lo_back),
            ("같은 봉 숏 신호 없음", ~st["raid_short"]),
        ],
        "short": [
            ("아직 아무 봉도 찌르지 않은 스윙 고점 있음", st["hi_open"]),
            ("고가가 스윙 고점 위로 찌름", hi_hit),
            ("종가는 스윙 고점 아래로 복귀", hi_back),
            ("같은 봉 롱 신호 없음", ~st["raid_long"]),
        ],
    }
