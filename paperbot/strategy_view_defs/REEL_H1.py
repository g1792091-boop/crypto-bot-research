"""Chart view for REEL_H1 (the Instagram reel "5분봉 단타, 선 두 개로 끝내는 법",
research/reel5m/PREREG_REEL5M.md section 5, H1 = 5m / BB_SMA200_CLOSE_LONG): what a trader draws for it and its
entry conditions, worded for the owners.

Long only. Filter on = the Bollinger(20, 2, population std) middle line above SMA200. A bar closing below the lower
band while the filter is on arms a setup; the setup waits (the breach bar itself is never the signal) for the first
green bar closing inside the band, at most 12 bars after the last breach bar (a new breach restarts the 12 bars);
a bar with the filter off cancels it. The signal bar is that green bar. The chart draws the bands, SMA200, the
setup's lowest low since its first breach bar and the stop line under it (lowest low - 0.05 x ATR14), and after a
signal the PREREG's trade (entry at the next bar's open plus 0.02%, skipped when the stop or the first target is
already passed): the fixed stop and the target, a resting limit at the PREVIOUS closed bar's upper band, until the
stop (first when both are touched), the target or the 96th bar. Those trade lines are a drawing of the rule; the
live account's real position lines come from the account (one position across the six coins).

The machine is lib_reel5m.simulate(trade=False), the position-independent machine the live signal runs
(paperbot/reelsig.py, owners' D3), started flat on the frame's first bar. The short list is empty: the reel never
goes short (AND over a side's conditions is read only for a side that has conditions; lib_reel5m with sides "LONG"
gives no short signal).

Checked against the research signal (lib_reel5m.simulate(trade=False) of research/reel5m/lib_reel5m.py on
lib_reel5m.indicators, H1 = SMA200 / CLOSE / LONG, loaded by path inside entry_marks._contained(), so sys.path and
the warnings filters are restored; one placeholder bar is appended so that simulate, which needs the entry bar s+1,
also reads the frame's last bar): AND of the long conditions equals the H1 signal on every checked bar. Checks: {"BTC5m_long_recall": 1, "BTC5m_long_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "SOL5m_long_recall": 1, "SOL5m_long_precision": 1, "DOGE5m_long_recall": 1, "DOGE5m_long_precision": 1, "LTC5m_long_recall": 1, "LTC5m_long_precision": 1, "BCH5m_long_recall": 1, "BCH5m_long_precision": 1}
Series: the full Binance USDT-M 5m bar files 2021-01..2026-09 of the six coins (604,177 bars each; signals checked:
BTC 8,244, ETH 8,282, SOL 7,712, DOGE 7,781, LTC 8,225, BCH 7,844) and live-service windows (the last
config.REEL_WINDOW_5M = 5,000 closed 5m bars, indicators and machine started again on each window): the latest
and 100 random end dates for BTC and ETH (signals checked 6,593 / 6,515), the latest and 30 for SOL, DOGE, LTC,
BCH (1,876 / 1,932 / 2,017 / 1,854): 0 differing bars, and the last bar of every window equals the full series'
(the 5,000-bar start changes nothing). On every signal bar the drawn lowest low and stop equal lib's ``extreme``
and ``stop_px``; each drawn trade's target line covers exactly the bars of lib_reel5m.exit_trade (last 150,000
BTC and SOL bars). tests/test_strategy_views_ds_reel.py repeats the check.
"""

import numpy as np
import fg_indicators as fg
import pine_indicators as pi

_BB_LEN, _BB_K = 20, 2.0       # Bollinger(20, 2), population std (lib_reel5m.BB_LEN, BB_K)
_MA_LEN = 200                  # SMA200 (H1: pine_sma)
_WAIT = 12                     # the signal comes at most 12 bars after the last breach bar
_STOP_BUF = 0.05               # stop = lowest low since the first breach bar - 0.05 x ATR14 of the signal bar
_MAX_HOLD = 96                 # bars at risk, entry bar included (drawing only)
_SLIP = 0.0002                 # 0.02% on the market entry (PREREG section 5 item 4; drawing only: the skip rules)


def _indicators(df):
    """lib_reel5m.indicators: bands from fg.bollinger_bands on the close, SMA200 (pine_sma), ATR14 (fg.atr)."""
    n = len(df)
    o, h, l, c = (np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))
    up, mid, dn, _bw = fg.bollinger_bands(df["close"].astype(float), _BB_LEN, _BB_K)
    atr = fg.atr(df, 14).to_numpy(dtype=float) if n else np.zeros(0)
    return o, h, l, c, up.to_numpy(dtype=float), mid.to_numpy(dtype=float), dn.to_numpy(dtype=float), \
        pi.pine_sma(c, _MA_LEN), atr


def _machine(l, filt, breach, sig):
    """lib_reel5m.simulate(trade=False) for the long side, bar by bar. Returns (alive, signal, armed_at, low):
    alive[t] = the setup is waiting when bar t closes (armed on an earlier bar, not cancelled, signalled or expired
    before t); signal[t] = bar t is the signal; armed_at[t] = the setup's first breach bar on the bars it covers (its
    arming bar included); low[t] = the lowest low from that first breach bar through bar t."""
    n = len(l)
    alive, signal = np.zeros(n, bool), np.zeros(n, bool)
    armed_at, low = np.full(n, -1), np.full(n, np.nan)
    armed, ext, b_first, b_last = False, np.nan, -1, -1
    for t in range(n):
        if armed:
            alive[t] = True
            if not filt[t]:                              # filter off: the setup is cancelled on this bar
                armed = False
                continue
            if l[t] < ext:
                ext = l[t]
            armed_at[t], low[t] = b_first, ext
            if sig[t]:                                   # green, inside the band, filter on: the signal
                signal[t] = True
                armed = False
            elif breach[t]:                              # a new breach: still armed, the 12 bars start again
                b_last = t
            elif t - b_last >= _WAIT:                    # 12 bars after the last breach without a signal
                armed = False
        elif breach[t] and filt[t]:                      # a close below the lower band with the filter on arms
            armed, ext, b_first, b_last = True, l[t], t, t
            armed_at[t], low[t] = t, ext
    return alive, signal, armed_at, low


def _trades(o, h, l, up, atr, signal, low):
    """The drawing of the PREREG's trade after each signal s (lib_reel5m.exit_trade order): entry at the open of s+1
    (+0.02%); skipped when the stop is at or above it or it is at or above the first target UP[s]; during bar j the
    stop is fixed and the target is UP[j-1]; it ends on the first bar touching the stop (first) or the target, or on
    the 96th bar. Returns (stop, target, low) lines over each trade's bars (NaN elsewhere)."""
    n = len(o)
    stop_l, tgt_l, low_l = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    for s in np.flatnonzero(signal):
        e = s + 1
        stop = low[s] - _STOP_BUF * atr[s]
        if e >= n or not np.isfinite(stop):
            continue
        entry = o[e] * (1.0 + _SLIP)
        if not entry > stop or not up[s] > entry:
            continue
        for j in range(e, min(n, e + _MAX_HOLD)):
            stop_l[j], tgt_l[j], low_l[j] = stop, up[j - 1], low[s]
            if l[j] <= stop or h[j] >= up[j - 1]:
                break
    return stop_l, tgt_l, low_l


def view_REEL_H1(df, tf):
    """REEL_H1: filter on, a setup armed by a close below the lower band in the last 12 bars, green bar closing
    inside the band. Exact."""
    o, h, l, c, up, mid, dn, ma, atr = _indicators(df)
    with np.errstate(invalid="ignore"):
        filt = mid > ma                                  # NaN (first 199 bars) = off
        breach = c < dn
        inside = (c > dn) & (c < up)
        green = c > o
    alive, signal, _armed_at, low = _machine(l, filt, breach, green & inside & filt)
    stop_setup = low - _STOP_BUF * atr                   # the stop if this bar were the signal
    stop_tr, tgt_tr, low_tr = _trades(o, h, l, up, atr, signal, low)
    setup = np.isfinite(low)
    return {
        "overlays": [
            {"name": "볼린저 상단(20, 2)", "values": up},
            {"name": "볼린저 중심선(20봉 평균)", "values": mid},
            {"name": "볼린저 하단(20, 2)", "values": dn},
            {"name": "200봉 평균선", "values": ma},
            {"name": "눌림 최저점(하단 이탈 뒤)", "values": np.where(setup, low, low_tr)},
            {"name": "손절선(최저점 − ATR 0.05배)", "values": np.where(setup, stop_setup, stop_tr)},
            {"name": "익절 목표(직전 봉 상단)", "values": tgt_tr},
        ],
        "panes": [],
        "long": [
            ("필터 켜짐(중심선 > 200선)", np.asarray(filt, bool)),
            ("하단 이탈 후 12봉 이내(기다리는 중)", alive),
            ("양봉", np.asarray(green, bool)),
            ("밴드 안에서 마감", np.asarray(inside, bool)),
        ],
        "short": [],
    }
