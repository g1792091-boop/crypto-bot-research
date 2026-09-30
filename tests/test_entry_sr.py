"""Support / resistance features of the entry study (research/entry_study/sr.py, PREREG_ENTRY.md s.2).

Synthetic data only, no network. The brute-force reference below recomputes every level with plain
loops from the bars up to the signal bar only, so it also checks causality independently."""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))

import sr  # noqa: E402
from paperbot.ladder import net_roe  # noqa: E402

TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
HTF_RULE = {"5m": "30min", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1D"}
HTF_MIN = {"5m": 30, "15m": 60, "30m": 240, "1h": 240, "4h": 1440}


def synth(n: int, tf: str, seed: int, start: str = "2024-01-03 00:00", px: float = 99.0, vol: float = 0.004,
          with_atr: bool = True) -> pd.DataFrame:
    """Random walk around ``px`` (crosses 100, where the round-number step changes), 2-decimal
    prices so that equal highs / lows (pivot ties) happen."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0, vol, n)
    c = np.round(px * np.exp(np.cumsum(r)), 2)
    o = np.r_[px, c[:-1]]
    h = np.round(np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n))), 2)
    lo = np.round(np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n))), 2)
    ts = pd.date_range(start, periods=n, freq=f"{TF_MIN[tf]}min", tz="UTC")
    df = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c,
                       "volume": rng.lognormal(3, 1, n)})
    if with_atr:
        tr = np.maximum(h - lo, np.maximum(np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(lo - np.r_[np.nan, c[:-1]])))
        df["atr"] = pd.Series(tr).rolling(14).mean().to_numpy()
    return df


# ------------------------------------------------------------------ brute-force reference
def _pivots_upto(h, l, last, lookback=300, keep=10):
    """Swing highs / lows usable once bar ``last`` has closed, from bars 0..last only."""
    hs, ls = [], []
    for j in range(5, last - 5 + 1):
        if j < last - lookback + 1:
            continue
        if h[j] == max(h[j - 5:j + 6]):
            hs.append(h[j])
        if l[j] == min(l[j - 5:j + 6]):
            ls.append(l[j])
    return hs[-keep:] + ls[-keep:]


def _vp_ref(h, l, c, v, i, bars=200, bins=50, share=0.7):
    if i < bars - 1:
        return []
    k0 = i - bars + 1
    lo, hi = min(l[k0:i + 1]), max(h[k0:i + 1])
    w = (hi - lo) / bins
    if not w > 0:
        return []
    hist = [0.0] * bins
    for k in range(k0, i + 1):
        tp = (h[k] + l[k] + c[k]) / 3.0
        b = min(max(math.floor((tp - lo) / w), 0), bins - 1)
        hist[b] += v[k]
    tot = sum(hist)
    if tot <= 0:
        return []
    poc = max(range(bins), key=lambda b: (hist[b], -b))
    a, b_, acc = poc, poc, hist[poc]
    while acc < share * tot * (1 - 1e-12):
        up = hist[b_ + 1] if b_ < bins - 1 else -1.0
        dn = hist[a - 1] if a > 0 else -1.0
        if up >= dn and b_ < bins - 1:
            b_ += 1
            acc += up
        else:
            a -= 1
            acc += dn
    return [lo + (poc + 0.5) * w, lo + (b_ + 1) * w, lo + a * w]


def _round_ref(ci: float) -> list[float]:
    """Round-number levels around ci as exact decimals (Decimal of the quoted price), as floats."""
    d = Decimal(repr(float(ci)))
    step = Decimal(5) * Decimal(10) ** (d.adjusted() - 1)
    k0 = int((d / step).to_integral_value(rounding="ROUND_FLOOR"))
    return [float(k * step) for k in range(k0 - 1, k0 + 3)]


def ref_levels(df: pd.DataFrame, tf: str, i: int) -> list[tuple[float, int]]:
    """Every level of bar i as (price, family), using bars 0..i only."""
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    t = [x.to_pydatetime() for x in df["ts"]]
    out = [(x, 1) for x in _pivots_upto(h, l, i)]
    day = t[i].date()
    pd_sel = [k for k in range(i + 1) if t[k].date() == day - dt.timedelta(days=1)]
    if pd_sel:
        out += [(max(h[pd_sel]), 2), (min(l[pd_sel]), 2)]
    mon = day - dt.timedelta(days=day.weekday())
    pw_sel = [k for k in range(i + 1) if mon - dt.timedelta(days=7) <= t[k].date() < mon]
    if pw_sel:
        out += [(max(h[pw_sel]), 3), (min(l[pw_sel]), 3)]
    ci = c[i]
    out += [(x, 4) for x in _round_ref(ci)]
    out += [(x, 5) for x in _vp_ref(h, l, c, v, i)]
    x = df.iloc[:i + 1].set_index("ts")[["open", "high", "low", "close", "volume"]]
    hb = x.resample(HTF_RULE[tf], label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    closed = hb.index + pd.Timedelta(minutes=HTF_MIN[tf]) <= df["ts"].iloc[i] + pd.Timedelta(minutes=TF_MIN[tf])
    hb = hb[closed]
    if len(hb):
        out += [(y, 6) for y in _pivots_upto(hb["high"].to_numpy(float), hb["low"].to_numpy(float), len(hb) - 1)]
    return out


def ref_features(df, tf, i, s, lev):
    lv = ref_levels(df, tf, i)
    c = df["close"].iloc[i]
    a = df["atr"].iloc[i]
    prev = df["close"].iloc[i - 1]
    ahead = sorted((s * (x - c), f) for x, f in lv if s * (x - c) >= 0)
    behind = sorted((s * (c - x), f) for x, f in lv if s * (c - x) > 0)
    lock = c * (0.12 / lev + 0.0014)
    return dict(
        room=min(ahead[0][0] / a, 10.0) if ahead else 10.0,
        floor=min(behind[0][0] / a, 10.0) if behind else 10.0,
        room_type=ahead[0][1] if ahead else 0,
        floor_type=behind[0][1] if behind else 0,
        level_before_lock=float(bool(ahead) and ahead[0][0] < lock),
        support_before_stop=float(bool(behind) and behind[0][0] < 2 * a),
        breakout=float(any((prev <= x < c) if s == 1 else (c < x <= prev) for x, _ in lv)),
    )


@pytest.mark.parametrize("tf,n,seed", [("5m", 2600, 1), ("1h", 1400, 2), ("4h", 700, 3)])
def test_matches_brute_force(tf, n, seed):
    df = synth(n, tf, seed)
    rng = np.random.default_rng(seed + 100)
    idx = np.sort(rng.choice(np.arange(20, n), 30, replace=False))
    idx = np.r_[idx, 199, 200, 305, n - 1]
    for s in (1, -1):
        f = sr.features_for(df, tf, None, idx, np.full(len(idx), s), np.full(len(idx), 25.0))
        for k, i in enumerate(idx):
            want = ref_features(df, tf, int(i), s, 25.0)
            for key, val in want.items():
                assert f[key][k] == pytest.approx(val, rel=1e-12, abs=1e-12), (tf, i, s, key)


def test_levels_subset_equals_full():
    df = synth(1500, "15m", 5)
    full = sr.levels_for(df, "15m")
    at = np.array([0, 3, 199, 250, 777, 1499])
    sub = sr.levels_for(df, "15m", at=at)
    for k in sr.REDUCTIONS:
        np.testing.assert_array_equal(full[k][at], sub[k])
        np.testing.assert_array_equal(full[k + "_kind"][at], sub[k + "_kind"])


# ------------------------------------------------------------------ causality
def _garbage(df: pd.DataFrame, i: int, seed: int) -> pd.DataFrame:
    g = df.copy()
    rng = np.random.default_rng(seed)
    m = len(df) - i - 1
    if m <= 0:
        return g
    x = rng.uniform(1.0, 1000.0, (m, 4))
    g.loc[g.index[i + 1:], "open"] = x[:, 0]
    g.loc[g.index[i + 1:], "close"] = x[:, 1]
    g.loc[g.index[i + 1:], "high"] = x.max(axis=1)
    g.loc[g.index[i + 1:], "low"] = x.min(axis=1)
    g.loc[g.index[i + 1:], "volume"] = rng.uniform(0, 1e9, m)
    return g


@pytest.mark.parametrize("tf,n", [("5m", 2600), ("1h", 1400), ("4h", 700)])
def test_causality_every_feature(tf, n):
    df = synth(n, tf, 7, with_atr=False)   # ATR computed inside with the backtest's fg.atr
    rng = np.random.default_rng(8)
    step = HTF_MIN[tf] // TF_MIN[tf]
    aligned = [i for i in range(300, n - 50) if (i + 1) % step == 0][:3]   # bar closing with an HTF bar
    idx = np.r_[rng.choice(np.arange(30, n - 1), 10, replace=False), aligned, 199, 200]
    sides = np.r_[np.ones(len(idx), int), -np.ones(len(idx), int)]
    both = np.r_[idx, idx]
    base = sr.features_for(df, tf, None, both, sides)
    changed = False
    for k, i in enumerate(both):
        g = _garbage(df, int(i), seed=int(i))
        f = sr.features_for(g, tf, None, [i], [sides[k]])
        for key, arr in base.items():
            np.testing.assert_array_equal(f[key], arr[k:k + 1], err_msg=f"{tf} bar {i} {key}")
        if i + 30 < n and not changed:
            later = sr.features_for(g, tf, None, [i + 30], [sides[k]])
            ref = sr.features_for(df, tf, None, [i + 30], [sides[k]])
            changed = any(not np.array_equal(later[x], ref[x], equal_nan=True) for x in ("room", "floor", "atr"))
    assert changed, "garbage did not change later features: the test would be vacuous"


# ------------------------------------------------------------------ L1 pivots
def test_pivot_confirmation_delay_and_window():
    n = 400
    h = np.full(n, 100.0) - np.arange(n) * 1e-3       # gently falling: no interior swing highs
    l = h - 1.0
    h[50] = 120.0
    ph, pl = sr.pivot_flags(h, l)
    assert ph[50] and ph.sum() == 1
    one = lambda last: sr.swing_matrix(h, l, np.array([last]))[0][0]   # noqa: E731
    assert 120.0 not in one(54)                      # j + 5 = 55 not yet closed
    assert 120.0 in one(55)                          # usable from bar j + 5 on
    assert 120.0 in one(50 + 299)                    # j = i - 299: inside the last 300 bars
    assert 120.0 not in one(50 + 300)                # j = i - 300: outside


def test_pivot_ties_edges_and_ten_most_recent():
    h = np.full(30, 100.0)
    l = np.full(30, 90.0)
    ph, pl = sr.pivot_flags(h, l)
    assert not ph[:5].any() and not ph[-5:].any()    # needs the full j-5..j+5 window
    assert ph[5:25].all() and pl[5:25].all()         # ties count as swing points
    n = 300                                          # all 12 inside the last 300 bars of bar 299
    h = np.full(n, 100.0)
    l = np.full(n, 90.0)
    peaks = np.arange(20, 20 + 12 * 20, 20)          # 12 swing highs, 20 bars apart
    h[peaks] = 101.0 + np.arange(12)
    l[peaks + 10] = 89.0 - np.arange(12)             # 12 swing lows
    h[:] = np.where(np.isin(np.arange(n), peaks), h, 100.0 - np.arange(n) * 1e-4)
    l[:] = np.where(np.isin(np.arange(n), peaks + 10), l, 90.0 + np.arange(n) * 1e-4)
    vals, kinds = sr.swing_matrix(h, l, np.array([n - 1]))
    highs = vals[0, kinds == 1]
    lows = vals[0, kinds == 2]
    np.testing.assert_array_equal(highs, 101.0 + np.arange(2, 12))
    np.testing.assert_array_equal(lows, 89.0 - np.arange(2, 12))


# ------------------------------------------------------------------ L4 round numbers
def test_round_numbers():
    c = np.array([84000.0, 3000.0, 0.15, 1000.0, 999.99, 10.0, 1.0, 0.2, 99.99, 100.0])
    np.testing.assert_allclose(sr.round_step(c), [5000, 500, 0.05, 500, 50, 5, 0.5, 0.05, 5, 50], rtol=1e-15)
    r = sr.round_nearest(np.array([84000.0, 85000.0, 0.15, 3120.0]))
    np.testing.assert_allclose(r["up_ge"], [85000, 85000, 0.15, 3500])
    np.testing.assert_allclose(r["up_gt"], [85000, 90000, 0.20, 3500])
    np.testing.assert_allclose(r["dn_le"], [80000, 85000, 0.15, 3000])
    np.testing.assert_allclose(r["dn_lt"], [80000, 80000, 0.10, 3000])
    assert r["up_ge"][2] == 0.15 and r["dn_le"][1] == 85000.0    # a close on a multiple is on it exactly


def test_round_numbers_are_exact_decimals():
    # k * step in floats gives 6 * 0.05 = 0.30000000000000004; the level must be the float of 0.3
    r = sr.round_nearest(np.array([0.3125662, 0.2995, 0.0047, 0.0062099, 0.1501, 0.00034]))
    assert r["dn_lt"][0] == 0.3 and r["up_gt"][1] == 0.3 and r["dn_lt"][2] == 0.0045
    assert r["up_ge"][3] == 0.0065 and r["dn_le"][4] == 0.15 and r["up_gt"][5] == 0.00035
    rng = np.random.default_rng(0)
    c = np.concatenate([np.round(10 ** rng.uniform(-4, 5.3, 4000), d) for d in range(0, 9)])
    c = np.r_[c[c > 0], [float(k * Decimal(5) * Decimal(10) ** e) for e in range(-6, 5) for k in range(2, 20)]]
    r = sr.round_nearest(c)
    for q, x in enumerate(c):
        lv = _round_ref(x)                                          # 4 consecutive multiples
        want = (min(y for y in lv if y >= x), min(y for y in lv if y > x),
                max(y for y in lv if y <= x), max(y for y in lv if y < x))
        got = (r["up_ge"][q], r["up_gt"][q], r["dn_le"][q], r["dn_lt"][q])
        assert got == want, (x, got, want)
    assert np.isnan(sr.round_nearest(np.array([np.nan, 0.0, -1.0]))["up_ge"]).all()


def _one_day_5m(c, h=None, l=None, atr=0.002):
    n = len(c)
    c = np.asarray(c, float)
    h = c + 0.0001 if h is None else np.asarray(h, float)
    l = c - 0.0001 if l is None else np.asarray(l, float)
    ts = pd.date_range("2024-01-03 00:00", periods=n, freq="5min", tz="UTC")   # one UTC day: no L2/L3
    return pd.DataFrame({"ts": ts, "open": c, "high": h, "low": l, "close": c, "volume": np.ones(n),
                         "atr": np.full(n, atr)})


def test_round_number_ties_exactly_with_a_swing_at_the_same_price():
    # a swing high at exactly 0.3 below a close of 0.3125: the round level 0.3 ties with it and the
    # tie goes to the lower family (L1); with k * step the round level was 0.30000000000000004 (L4)
    n = 100
    c = np.r_[np.full(60, 0.285), np.round(np.linspace(0.301, 0.3125, 40), 6)]
    h = np.r_[np.full(60, 0.29), c[60:] + 0.001]
    l = np.r_[np.full(60, 0.28), c[60:] - 0.001]
    h[50] = 0.3
    df = _one_day_5m(c, h, l)
    f = sr.features_for(df, "5m", None, [n - 1], [1], [20.0])
    assert f["behind_px"][0] == 0.3 and f["floor_type"][0] == 1 and f["floor_kind"][0] == 11
    assert f["behind_L4"][0] == f["behind_L1"][0] == pytest.approx((0.3125 - 0.3) / 0.002)


def test_breakout_with_previous_close_exactly_on_a_round_number():
    # short: previous close exactly 0.3, close 0.2995 -> the level 0.3 was passed (c < 0.3 <= prev)
    c = np.r_[np.round(np.linspace(0.33, 0.3, 59), 6), 0.2995]
    assert c[-2] == 0.3
    df = _one_day_5m(c)
    f = sr.features_for(df, "5m", None, [59], [-1], [20.0])
    assert f["behind_px"][0] == 0.3 and f["floor_type"][0] == 4
    assert f["breakout"][0] == 1


# ------------------------------------------------------------------ L2 / L3 prior day / week
def test_prior_day_and_week_boundaries():
    ts = pd.date_range("2024-01-06 00:00", "2024-01-22 23:00", freq="1h", tz="UTC")   # Sat 6th .. Mon 22nd
    ts = ts[ts.date != dt.date(2024, 1, 10)]                                          # a missing day
    rng = np.random.default_rng(3)
    h = rng.uniform(100, 200, len(ts))
    l = h - rng.uniform(1, 50, len(ts))
    t = sr.ts_ns(pd.Series(ts))

    def at(s):
        return int(np.flatnonzero(ts == pd.Timestamp(s, tz="UTC"))[0])

    def hl(mask):
        return [h[mask].max(), l[mask].min()]

    d = np.array(ts.date)
    cases = {
        "2024-01-07 23:00": (d == dt.date(2024, 1, 6), None),                      # Sunday: week before has no data
        "2024-01-08 00:00": (d == dt.date(2024, 1, 7), (d >= dt.date(2024, 1, 6)) & (d <= dt.date(2024, 1, 7))),
        "2024-01-14 23:00": (d == dt.date(2024, 1, 13), (d >= dt.date(2024, 1, 6)) & (d <= dt.date(2024, 1, 7))),
        "2024-01-15 00:00": (d == dt.date(2024, 1, 14), (d >= dt.date(2024, 1, 8)) & (d <= dt.date(2024, 1, 14))),
        "2024-01-11 05:00": (None, (d >= dt.date(2024, 1, 6)) & (d <= dt.date(2024, 1, 7))),  # day before missing
    }
    idx = np.array([at(s) for s in cases])
    day = sr.prior_period_hl(t, h, l, idx, "day")
    week = sr.prior_period_hl(t, h, l, idx, "week")
    for k, (dmask, wmask) in enumerate(cases.values()):
        if dmask is None:
            assert np.isnan(day[k]).all()
        else:
            np.testing.assert_array_equal(day[k], hl(dmask))
        if wmask is None:
            assert np.isnan(week[k]).all()
        else:
            np.testing.assert_array_equal(week[k], hl(wmask))
    # the prior day's last bar (23:00) is part of it; the signal day's own bars are not
    k = list(cases).index("2024-01-08 00:00")
    h2 = h.copy()
    h2[at("2024-01-07 23:00")] = 999.0
    h2[at("2024-01-08 00:00")] = 1999.0
    assert sr.prior_period_hl(t, h2, l, idx, "day")[k, 0] == 999.0


# ------------------------------------------------------------------ L5 volume profile
def _vp_bars(vols: dict, extra: tuple | None = None):
    """201 bars; window of bar 200 = bars 1..200 spans [0, 50] (bin width 1)."""
    n = 201
    h = np.full(n, 30.5)
    l = np.full(n, 30.5)
    c = np.full(n, 30.5)
    v = np.zeros(n)
    h[0], l[0], c[0], v[0] = 1000.0, 900.0, 950.0, 1e9           # outside the window of bar 200
    h[1], l[1], c[1], v[1] = 1.5, 0.0, 0.75, 1.0                 # tp 0.75 -> bin 0; sets min low 0
    h[2], l[2], c[2], v[2] = 50.0, 48.5, 49.25, 1.0              # tp 49.25 -> bin 49; sets max high 50
    k = 3
    for b, vol in vols.items():
        h[k] = l[k] = c[k] = b + 0.5
        v[k] = vol
        k += 1
    if extra:
        h[k], l[k], c[k], v[k] = extra
    return h, l, c, v


def test_volume_profile_hand_example():
    # bins 20..23 flat bars; bin 24 gets a bar whose CLOSE is in bin 22 but typical price
    # (26 + 22 + 24.9) / 3 = 24.3 is in bin 24
    h, l, c, v = _vp_bars({20: 10.0, 21: 30.0, 22: 50.0, 23: 20.0}, extra=(26.0, 22.0, 24.9, 5.0))
    # total 117, 70% = 81.9; POC bin 22 (50); up 20 < down 30 -> add 21 (80); up 20 > down 10 -> add 23 (100)
    out = sr.volume_profile(h, l, c, v, np.array([200, 198]))
    np.testing.assert_allclose(out[0], [22.5, 24.0, 21.0])
    assert np.isnan(out[1]).all()                                 # fewer than 200 bars


def test_volume_profile_tie_goes_up_and_signal_bar_included():
    h, l, c, v = _vp_bars({21: 20.0, 22: 50.0, 23: 20.0})
    out = sr.volume_profile(h, l, c, v, np.array([200]))          # total 92, 70% = 64.4: tie -> up
    np.testing.assert_allclose(out[0], [22.5, 24.0, 22.0])
    h[200] = l[200] = c[200] = 10.5                               # the signal bar itself counts
    v[200] = 1000.0
    out = sr.volume_profile(h, l, c, v, np.array([200]))
    np.testing.assert_allclose(out[0], [10.5, 11.0, 10.0])


# ------------------------------------------------------------------ features on hand-made levels
def _levels(close, prev, up=(), dn=()):
    """levels dict for one bar: ``up`` / ``dn`` = [(family, price)] above / below the close."""
    lv = {"at": np.array([0]), "close": np.array([close]), "prev_close": np.array([prev])}
    for k in sr.REDUCTIONS:
        lv[k] = np.full((1, 6), np.nan)
        lv[k + "_kind"] = np.zeros((1, 6), np.int16)
    for f, x in up:
        for k in ("up_ge", "up_gt"):
            lv[k][0, f - 1] = x
            lv[k + "_kind"][0, f - 1] = 10 * f + 1
    for f, x in dn:
        for k in ("dn_le", "dn_lt"):
            lv[k][0, f - 1] = x
            lv[k + "_kind"][0, f - 1] = 10 * f + 2
    return lv


def _feat(lv, side, lev=20.0, atr=1.0):
    df = pd.DataFrame({"ts": [0], "close": lv["close"]})
    return {k: v[0] for k, v in sr.features_for(df, "1h", None, [0], [side], [lev], levels=lv,
                                                 atr=np.array([atr])).items()}


def test_constants():
    assert sr.ROUND_TRIP == pytest.approx(0.0014)
    assert sr.LOCK_ROE == pytest.approx(0.12)
    assert sr.K_STOP == 2.0


@pytest.mark.parametrize("side", [1, -1])
def test_lock_and_stop_hand_examples(side):
    # c = 100, lev 20: lock distance = 100 * (0.12 / 20 + 0.0014) = 0.74; stop distance = 2 ATR = 2
    def lv(ahead, behind):
        a, b = 100 + side * ahead, 100 - side * behind
        up, dn = ((2, a),), ((3, b),)
        return _levels(100.0, 100.0, *((up, dn) if side == 1 else (dn, up)))

    f = _feat(lv(0.70, 1.5), side)
    assert f["level_before_lock"] == 1 and f["support_before_stop"] == 1
    assert f["room"] == pytest.approx(0.70) and f["floor"] == pytest.approx(1.5)
    assert f["room_type"] == 2 and f["floor_type"] == 3
    assert f["lock_px"] == pytest.approx(100 + side * 0.74)
    assert net_roe(side, 100.0, f["lock_px"], 20, 0.0014) == pytest.approx(0.12)
    assert f["stop_px"] == pytest.approx(100 - side * 2.0)
    f = _feat(lv(0.80, 2.1), side)
    assert f["level_before_lock"] == 0 and f["support_before_stop"] == 0
    f = _feat(lv(0.74 + 1e-9, 2.0), side)                          # strictly closer only
    assert f["level_before_lock"] == 0 and f["support_before_stop"] == 0
    f = _feat(lv(0.80, 1.5), side, lev=50.0)                       # lev 50: lock distance 0.38
    assert f["level_before_lock"] == 0
    f = _feat(lv(0.30, 1.5), side, lev=50.0)
    assert f["level_before_lock"] == 1


@pytest.mark.parametrize("side", [1, -1])
def test_room_floor_caps_and_missing(side):
    f = _feat(_levels(100.0, 100.0, up=((4, 150.0),), dn=((4, 50.0),)), side, atr=1.0)
    assert f["room"] == 10.0 and f["floor"] == 10.0
    assert f["dist_ahead_atr"] == pytest.approx(50.0)               # uncapped distance kept
    f = _feat(_levels(100.0, 100.0), side)                          # no level at all
    assert f["room"] == 10.0 and f["floor"] == 10.0
    assert f["room_type"] == 0 and f["level_before_lock"] == 0 and f["support_before_stop"] == 0
    f = _feat(_levels(100.0, 100.0, up=((1, 100.3),), dn=((1, 99.6),)), side, atr=float("nan"))
    assert np.isnan(f["room"]) and np.isnan(f["floor"]) and np.isnan(f["support_before_stop"])


def test_nearest_type_and_tie_goes_to_lower_family():
    lv = _levels(100.0, 100.0, up=((5, 100.5), (2, 100.5), (6, 100.2)), dn=((4, 99.0), (1, 99.0)))
    f = _feat(lv, 1)
    assert f["room_type"] == 6 and f["room_kind"] == 61
    assert f["floor_type"] == 1
    assert f["ahead_L2"] == pytest.approx(0.5) and f["ahead_L5"] == pytest.approx(0.5)
    assert np.isnan(f["ahead_L3"])
    lv = _levels(100.0, 100.0, up=((5, 100.5), (2, 100.5)))
    assert _feat(lv, 1)["room_type"] == 2


def test_level_exactly_at_close_is_ahead_not_behind():
    df = synth(400, "1h", 11)
    df.loc[df.index[-1], "close"] = 100.0                            # on a round number (step 50)
    for s in (1, -1):
        f = sr.features_for(df, "1h", None, [399], [s], [20.0])
        assert f["room"][0] == 0.0
        assert f["floor"][0] > 0.0


@pytest.mark.parametrize("side", [1, -1])
def test_breakout(side):
    def lv(prev, behind):
        b = ((2, behind),)
        return _levels(100.0, prev, *(((), b) if side == 1 else (b, ())))
    assert _feat(lv(100 - side * 0.5, 100 - side * 0.2), side)["breakout"] == 1
    assert _feat(lv(100 - side * 0.5, 100 - side * 0.5), side)["breakout"] == 1   # level at prev close
    assert _feat(lv(100 - side * 0.5, 100 - side * 0.6), side)["breakout"] == 0
    assert _feat(lv(100 + side * 0.5, 100 - side * 0.2), side)["breakout"] == 0   # moved against
    f = sr.features_for(synth(50, "1h", 1), "1h", None, [0], [side], [20.0])
    assert np.isnan(f["breakout"][0])                                              # no previous bar


def test_default_leverage_from_paper_sizer():
    lv = _levels(100.0, 100.0, up=((2, 101.0),), dn=((3, 99.0),))
    df = pd.DataFrame({"ts": [0], "close": [100.0]})
    got = sr.features_for(df, "1h", None, [0], [1], None, levels=lv, atr=np.array([1.0]))["lev"][0]
    assert got == sr.PR._sizer()(1, 0.01)[0] == 20
    assert np.isnan(sr.leverage_at_close([1], [np.nan], [100.0])[0])
    assert sr.leverage_at_close([-1, 1], [0.1, 0.05], [100.0, 100.0]).tolist() == [50.0, 50.0]
