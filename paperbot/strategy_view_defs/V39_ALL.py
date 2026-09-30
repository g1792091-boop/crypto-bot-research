"""Chart view for V39_ALL: its indicators (same parameters as the locked code) and entry conditions.

Checked against the locked signal: AND of the long (short) conditions equals the locked long (short)
signal on every checked bar. Checks: {"BTC15m_long_recall": 1, "BTC15m_long_precision": 1, "BTC15m_short_recall": 1, "BTC15m_short_precision": 1, "SOL1h_long_recall": 1, "SOL1h_long_precision": 1, "SOL1h_short_recall": 1, "SOL1h_short_precision": 1, "ETH5m_long_recall": 1, "ETH5m_long_precision": 1, "ETH5m_short_recall": 1, "ETH5m_short_precision": 1}
"""

import numpy as np
import pandas as pd
import pine_indicators as pi
from strategies import _f, shift_bool


def _bool(x):
    return np.asarray(x, dtype=bool)


def _empty_view_obvb(view):
    """Same layout with zero-length arrays (used for an empty frame)."""
    return {
        "overlays": [dict(o, values=o["values"][:0]) for o in view["overlays"]],
        "panes": [dict(p, series=[dict(s, values=s["values"][:0]) for s in p["series"]]) for p in view["panes"]],
        "long": [(lab, c[:0]) for lab, c in view["long"]],
        "short": [(lab, c[:0]) for lab, c in view["short"]],
    }


def _one_nan_bar():
    return pd.DataFrame({c: [np.nan] for c in ("open", "high", "low", "close", "volume")})


def view_V39_ALL(df, tf):
    # locked (strategies.v39_all = v39_signals(stc_filter=False)): chart-TF V3.9.
    # Two entry types share a 2-bar cooldown (a new entry needs 3+ bars since the last one, same side):
    #  A type: ST(10,3) & ST(10,6) up, DMI20 +DI-(-DI) >= 2, chop angle(34,30,25) >= 2, ADX(20,20) 10..60,
    #          MACD(12,26,9) hist < 0 and rising, AO/AC condition, trigger = armed stochastic
    #          golden cross (Stoch 14 K4/D2, Stoch 14 K5/D2, StochRSI 14/14/3/3; cross at/under 50,
    #          remembered 4 bars) or DMI16 +DI crossing above -DI.
    #  B type: ST(10,3) up, ADX >= 10, |DI gap| >= 2, |chop angle| >= 2, first bar of AC < 0 rising,
    #          AO < 0 falling.
    # Conditions below are an exact AND decomposition: common parts, then (A part OR B) twice.
    if len(df) == 0:  # pi.shift1 / true_range cannot index an empty array (the locked v39_all fails too)
        return _empty_view_obvb(view_V39_ALL(_one_nan_bar(), tf))
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    n = len(close)
    st3_line, d3 = pi.exchange_supertrend(high, low, close, 10, 3.0)
    st6_line, d6 = pi.exchange_supertrend(high, low, close, 10, 6.0)
    st3_bull, st3_bear = d3 == 1, d3 == -1
    st6_bull, st6_bear = d6 == 1, d6 == -1
    _ml, _ms, hist = pi.pine_macd(close, 12, 26, 9)
    hist_prev = pi.shift1(hist)
    ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    ao_p, ac_p = pi.shift1(ao), pi.shift1(ac)
    chop = pi.chop_angle(high, low, close, 34, 30, 25.0)
    plus20, minus20 = pi.dmi(high, low, close, 20)
    plus16, minus16 = pi.dmi(high, low, close, 16)
    adx20 = pi.adx(high, low, close, 20, 20)
    raw = pi.pine_stoch(close, high, low, 14)
    k42 = pi.pine_sma(raw, 4); d42 = pi.pine_sma(k42, 2)
    k52 = pi.pine_sma(raw, 5); d52 = pi.pine_sma(k52, 2)
    kr, dr = pi.stoch_rsi_kd(close, 14, 14, 3, 3)
    with np.errstate(invalid="ignore"):
        macd_weak_neg = (hist < 0.0) & (hist > hist_prev)
        macd_weak_pos = (hist > 0.0) & (hist < hist_prev)
        ao_below, ao_above = ao < 0.0, ao > 0.0
        ac_below, ac_above = ac < 0.0, ac > 0.0
        ao_up, ao_down = ao > ao_p, ao < ao_p
        ac_up, ac_down = ac > ac_p, ac < ac_p
        ao_ac_long = (ao_above & ao_down & ac_below & ac_up) | (ao_below & ac_below)
        ao_ac_short = (ao_below & ao_up & ac_above & ac_down) | (ao_above & ac_above)
        gap = np.abs(plus20 - minus20)
        adx_min_ok = adx20 >= 10.0
        adx_max_ok = adx20 <= 60.0
        chop_abs = np.abs(chop) >= 2.0
        # A-type trend alignment (ST(10,3) is its own condition; +DI>-DI and chop>=0.71 are implied)
        align_long = (st6_bull & ((plus20 - minus20) >= 2.0) & (chop >= 2.0) & adx_max_ok
                      & macd_weak_neg & ao_ac_long)
        align_short = (st6_bear & ((minus20 - plus20) >= 2.0) & (chop <= -2.0) & adx_max_ok
                       & macd_weak_pos & ao_ac_short)
        d16_up = pi.crossover(plus16, minus16)
        d16_down = pi.crossunder(plus16, minus16)
    # B type: first bar of AC below 0 and rising, AO below 0 and falling (mirror for short)
    ac_neg_up_state = ac_below & ac_up
    ac_pos_down_state = ac_above & ac_down
    b_long = ac_neg_up_state & ~shift_bool(ac_neg_up_state, 1) & ao_below & ao_down
    b_short = ac_pos_down_state & ~shift_bool(ac_pos_down_state, 1) & ao_above & ao_up
    common_long = st3_bull & adx_min_ok & (gap >= 2.0) & chop_abs
    common_short = st3_bear & adx_min_ok & (gap >= 2.0) & chop_abs
    a_ok_long = common_long & align_long      # everything of type A except cooldown and trigger
    a_ok_short = common_short & align_short

    # sequential part (same as the locked loop): stochastic cross memory (4 bars) + 2-bar cooldown
    oscs = [(k42, d42), (k52, d52), (kr, dr)]
    with np.errstate(invalid="ignore"):
        od = [dict(gc=pi.crossover(k, d), dc=pi.crossunder(k, d),
                   lc=(k <= 50.0) | (d <= 50.0), sc=(k >= 50.0) | (d >= 50.0),
                   gs=k > d, ds=k < d,
                   ba=(k > 50.0) & (d > 50.0), bb=(k < 50.0) & (d < 50.0)) for k, d in oscs]
    arm_l = [False] * 3; arm_s = [False] * 3
    bar_l = [-1] * 3; bar_s = [-1] * 3
    last_l, last_s = -10**9, -10**9
    cd_long = np.zeros(n, dtype=bool); cd_short = np.zeros(n, dtype=bool)
    trig_long = np.zeros(n, dtype=bool); trig_short = np.zeros(n, dtype=bool)
    for i in range(n):
        lcd = (i - last_l) > 2
        scd = (i - last_s) > 2
        cd_long[i], cd_short[i] = lcd, scd
        for j, o in enumerate(od):
            if o["gc"][i]:
                arm_l[j] = bool(o["lc"][i]); bar_l[j] = i if arm_l[j] else -1
                arm_s[j] = False; bar_s[j] = -1
            elif o["dc"][i]:
                arm_s[j] = bool(o["sc"][i]); bar_s[j] = i if arm_s[j] else -1
                arm_l[j] = False; bar_l[j] = -1
            if arm_l[j] and bar_l[j] >= 0 and i - bar_l[j] > 4:
                arm_l[j] = False; bar_l[j] = -1
            if arm_s[j] and bar_s[j] >= 0 and i - bar_s[j] > 4:
                arm_s[j] = False; bar_s[j] = -1
            if o["ba"][i]:
                arm_l[j] = False; bar_l[j] = -1
            if o["bb"][i]:
                arm_s[j] = False; bar_s[j] = -1
        tl = bool(d16_up[i]); ts = bool(d16_down[i])
        fire_a_l = lcd and a_ok_long[i]
        fire_a_s = scd and a_ok_short[i]
        for j, o in enumerate(od):
            if arm_l[j] and o["gs"][i] and o["lc"][i]:
                tl = True
                if fire_a_l:
                    arm_l[j] = False; bar_l[j] = -1
            if arm_s[j] and o["ds"][i] and o["sc"][i]:
                ts = True
                if fire_a_s:
                    arm_s[j] = False; bar_s[j] = -1
        trig_long[i], trig_short[i] = tl, ts
        if (fire_a_l and tl) or (lcd and common_long[i] and b_long[i]):
            last_l = i
        if (fire_a_s and ts) or (scd and common_short[i] and b_short[i]):
            last_s = i

    return {
        "overlays": [
            {"name": "슈퍼트렌드 (10, 3)", "values": _f(st3_line)},
            {"name": "슈퍼트렌드 (10, 6)", "values": _f(st6_line)},
        ],
        "panes": [
            {"name": "스토캐스틱 14 (4·2)",
             "series": [{"name": "K", "values": _f(k42)},
                        {"name": "D", "values": _f(d42)}],
             "levels": [50]},
            {"name": "AO · AC 모멘텀",
             "series": [{"name": "AO", "values": _f(ao)},
                        {"name": "AC", "values": _f(ac)}],
             "levels": [0]},
        ],
        "long": [
            ("직전 롱 후 3봉 지남", _bool(cd_long)),
            ("슈퍼트렌드(10·3) 상승", _bool(st3_bull)),
            ("추세 힘·기울기 충분", _bool(adx_min_ok & (gap >= 2.0) & chop_abs)),
            ("상승 정렬 또는 AC 첫반등", _bool(align_long | b_long)),
            ("골든크로스 또는 AC 첫반등", _bool(trig_long | b_long)),
        ],
        "short": [
            ("직전 숏 후 3봉 지남", _bool(cd_short)),
            ("슈퍼트렌드(10·3) 하락", _bool(st3_bear)),
            ("추세 힘·기울기 충분", _bool(adx_min_ok & (gap >= 2.0) & chop_abs)),
            ("하락 정렬 또는 AC 첫하락", _bool(align_short | b_short)),
            ("데드크로스 또는 AC 첫하락", _bool(trig_short | b_short)),
        ],
    }
