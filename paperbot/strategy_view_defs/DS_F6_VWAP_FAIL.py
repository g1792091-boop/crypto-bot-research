"""Chart view for DS_F6_VWAP_FAIL: DeepSeek-200 definition F6_VWAP_FAIL (F6 VWAP), its lines and entry conditions.

Rule (PREREG_DEEPSEEK200.md section 5, F6): VWAP anchored to the UTC day (starts again at 00:00 UTC = 09:00 KST), as
F6_VWAP_CROSS. Short: on bar k of a day the close breaks below VWAP (close[k-1] >= VWAP[k-1], close[k] < VWAP[k],
same day). In the next 10 bars of that day (k+1 .. k+10) the FIRST bar whose high reaches VWAP and that closes back
below VWAP as a red candle (high >= VWAP, close < VWAP, close < open) is the short: the retest failed. A close above
VWAP in between cancels that break. Long mirrored (break above, low <= VWAP, close > VWAP, green candle).

Checklist: it reads the most recent break of the last 10 bars of the same day. That is exact: any bar that cancels or
uses up the newest break lies after every older break too, so some break is still waiting exactly when the newest is.
The chart shows VWAP and, for each side, VWAP again only on the bars where a break is waiting for its retest.

Same rules as research/deepseek200/lib_c.py ``entries()`` / ``daily_vwap()`` (the live signal is paperbot/dssig.py),
written again with numpy / pandas; lib_c is not imported here. lib_c drops both sides when long and short fire on
one bar; here the sides exclude each other (close above vs below VWAP), so that rule never acts and is not a line.

Checked against the research signal: AND of the long (short) conditions equals the lib_c long (short) signal on every
checked bar (lib_c loaded by path inside entry_marks._contained(): sys.path and the warnings filters restored).
Bars: Binance USDT-M 2021-01..2026-09 from the 5-year bar files, (a) the full series BTC 15m (201,398 bars),
ETH 1h (50,351), SOL 4h (12,588), DOGE 30m (100,701), and (b) the live DeepSeek frames: the last
config.DS_WINDOW_5M[tf] closed 5m bars resampled by paperbot.dssig.frame, at 24 evenly spaced bar closes
per series (first full window .. 2026-09) for BTC 15m, ETH 1h, LTC 4h, BCH 30m, SOL 1h, DOGE 15m (144 frames).
Signals checked: full series long 8,754 / short 8,684; live frames long 14,537 / short 14,497; 0 differing bars.
Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "ETH1h_long_recall": 1, "ETH1h_long_precision": 1, "ETH1h_short_recall": 1, "ETH1h_short_precision": 1, "SOL4h_long_recall": 1, "SOL4h_long_precision": 1, "SOL4h_short_recall": 1, "SOL4h_short_precision": 1, "DOGE30m_long_recall": 1, "DOGE30m_long_precision": 1, "DOGE30m_short_recall": 1, "DOGE30m_short_precision": 1, "BTC15m_live_long_recall": 1, "BTC15m_live_long_precision": 1, "BTC15m_live_short_recall": 1, "BTC15m_live_short_precision": 1, "ETH1h_live_long_recall": 1, "ETH1h_live_long_precision": 1, "ETH1h_live_short_recall": 1, "ETH1h_live_short_precision": 1, "LTC4h_live_long_recall": 1, "LTC4h_live_long_precision": 1, "LTC4h_live_short_recall": 1, "LTC4h_live_short_precision": 1, "BCH30m_live_long_recall": 1, "BCH30m_live_long_precision": 1, "BCH30m_live_short_recall": 1, "BCH30m_live_short_precision": 1, "SOL1h_live_long_recall": 1, "SOL1h_live_long_precision": 1, "SOL1h_live_short_recall": 1, "SOL1h_live_short_precision": 1, "DOGE15m_live_long_recall": 1, "DOGE15m_live_long_precision": 1, "DOGE15m_live_short_recall": 1, "DOGE15m_live_short_precision": 1}
tests/test_strategy_views_ds_f4_f7.py repeats the check (synthetic bars always, real bars with DS_BARS_DIR).
"""

import numpy as np
import pandas as pd

_WAIT = 10          # bars k+1 .. k+10 after the break (PREREG F6_VWAP_FAIL)


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


def _waiting(day, brk, kill, cand):
    """Per bar t, about the newest break k in t-10 .. t-1 on t's UTC day: (there is one, no cancelling close in
    k+1 .. t-1, no earlier retest signal in k+1 .. t-1)."""
    n = len(day)
    has, alive, first = np.zeros(n, bool), np.zeros(n, bool), np.zeros(n, bool)
    dl, bl, kl, cl = day.tolist(), brk.tolist(), kill.tolist(), cand.tolist()
    last, killed, used = -1, False, False
    for t in range(n):
        if last >= 0 and t - last <= _WAIT and dl[last] == dl[t]:
            has[t], alive[t], first[t] = True, not killed, not used
        if bl[t]:
            last, killed, used = t, False, False
        else:
            killed = killed or kl[t]
            used = used or cl[t]
    return has, alive, first


def view_DS_F6_VWAP_FAIL(df, tf):
    """F6_VWAP_FAIL: after a close through the day's VWAP, the first retest within 10 bars that fails. Exact."""
    o, h, l, c = (np.asarray(df[k], dtype=float) for k in ("open", "high", "low", "close"))
    vw, day = _daily_vwap(df)
    n = len(c)
    same = np.zeros(n, bool)
    same[1:] = day[1:] == day[:-1]
    c1, vw1 = _prev(c), _prev(vw)
    with np.errstate(invalid="ignore"):
        brk_dn = same & (c1 >= vw1) & (c < vw)
        brk_up = same & (c1 <= vw1) & (c > vw)
        rt_s, back_s = h >= vw, (c < vw) & (c < o)          # retest of VWAP from below that closes back below, red
        rt_l, back_l = l <= vw, (c > vw) & (c > o)
        hs, al_s, fs = _waiting(day, brk_dn, c > vw, rt_s & back_s)
        hl, al_l, fl = _waiting(day, brk_up, c < vw, rt_l & back_l)
    wait_s = np.where(hs & al_s & fs, vw, np.nan)
    wait_l = np.where(hl & al_l & fl, vw, np.nan)
    return {
        "overlays": [
            {"name": "VWAP (매일 오전 9시 시작)", "values": vw},
            {"name": "숏 대기: VWAP 이탈 뒤 재시험 구간", "values": wait_s},
            {"name": "롱 대기: VWAP 돌파 뒤 재시험 구간", "values": wait_l},
        ],
        "panes": [],
        "long": [
            ("최근 10봉 안에 VWAP 위로 돌파(같은 날)", hl),
            ("돌파 뒤 VWAP 아래 마감 없음", ~hl | al_l),
            ("돌파 뒤 첫 재시험(앞선 신호 없음)", ~hl | fl),
            ("저가가 VWAP까지 눌림", np.asarray(rt_l, bool)),
            ("종가는 다시 VWAP 위·양봉", np.asarray(back_l, bool)),
        ],
        "short": [
            ("최근 10봉 안에 VWAP 아래로 이탈(같은 날)", hs),
            ("이탈 뒤 VWAP 위 마감 없음", ~hs | al_s),
            ("이탈 뒤 첫 재시험(앞선 신호 없음)", ~hs | fs),
            ("고가가 VWAP까지 반등", np.asarray(rt_s, bool)),
            ("종가는 다시 VWAP 아래·음봉", np.asarray(back_s, bool)),
        ],
    }
