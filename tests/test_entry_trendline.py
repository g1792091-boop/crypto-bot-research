"""Trendline entry study (research/entry_study/trendline.py and analysis_trendline.py, PREREG_TRENDLINE.md).

Synthetic data only, no network. The slow reference below follows the pre-registration text with plain
loops over the bars 0..i of each signal bar i (swings, A scan, break, touches), so it also checks
causality independently of the garbage test."""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))

import trendline as TL  # noqa: E402

TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def synth(n: int, seed: int, px: float = 100.0, vol: float = 0.004, start: str = "2024-01-03 00:00",
          tf: str = "1h", with_atr: bool = True) -> pd.DataFrame:
    """Random walk, 2-decimal prices (equal highs / lows happen), ATR = 14-bar mean true range."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, vol / 3, n // 50 + 1), 50)[:n]       # trending stretches
    r = rng.normal(0, vol, n) + drift
    c = np.round(px * np.exp(np.cumsum(r)), 2)
    o = np.r_[px, c[:-1]]
    h = np.round(np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n))), 2)
    lo = np.round(np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n))), 2)
    ts = pd.date_range(start, periods=n, freq=f"{TF_MIN[tf]}min", tz="UTC")
    df = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c})
    if with_atr:
        tr = np.maximum(h - lo, np.maximum(np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(lo - np.r_[np.nan, c[:-1]])))
        df["atr"] = pd.Series(tr).rolling(14).mean().to_numpy()
    return df


# ------------------------------------------------------------------ slow reference (PREREG 2-1 .. 2-4)
def ref_line(df: pd.DataFrame, i: int, kind: str, P: TL.Params = TL.DEFAULT):
    """The line of bar i from bars 0..i only, by plain loops. kind 'sup' (rising, lows) or 'res'."""
    K, W = P.k, P.window
    hi = [float(x) for x in df["high"].to_numpy()[:i + 1]]
    lo = [float(x) for x in df["low"].to_numpy()[:i + 1]]
    cl = [float(x) for x in df["close"].to_numpy()[:i + 1]]
    at = [float(x) for x in df["atr"].to_numpy()[:i + 1]]
    sup = kind == "sup"
    ref = lo if sup else hi
    piv = []
    for j in range(max(K, i - W + 1), i - K + 1):          # usable (j + K <= i) and inside the window
        win = ref[j - K:j + K + 1]
        if (ref[j] == min(win)) if sup else (ref[j] == max(win)):
            piv.append(j)
    # B = the most recent usable swing; it must be inside the window. A swing older than the window
    # cannot be B unless no newer swing exists, in which case there is no line either way.
    last_any = None
    for j in range(i - K, K - 1, -1):
        win = ref[j - K:j + K + 1]
        if (ref[j] == min(win)) if sup else (ref[j] == max(win)):
            last_any = j
            break
    if last_any is None or last_any < i - W + 1:
        return None
    B = last_any
    A = m = None
    for p in reversed([x for x in piv if x < B]):
        if not ((ref[p] < ref[B]) if sup else (ref[p] > ref[B])):
            continue
        mm = (ref[B] - ref[p]) / (B - p)
        r = mm / at[B]
        if not ((0 < r <= P.slope_max) if sup else (-P.slope_max <= r < 0)):
            continue
        y = lambda t, p=p, mm=mm: ref[p] + mm * (t - p)   # noqa: E731
        if sup:
            good = all(cl[t] >= y(t) - P.delta * at[t] for t in range(p + 1, B))
        else:
            good = all(cl[t] <= y(t) + P.delta * at[t] for t in range(p + 1, B))
        if good:
            A, m = p, mm
            break
    if A is None:
        return None

    def y(t):
        return ref[A] + m * (t - A)

    brk = -1
    for t in range(B + 1, i + 1):
        if (cl[t] < y(t) - P.delta * at[t]) if sup else (cl[t] > y(t) + P.delta * at[t]):
            brk = t
            break
    touch, prev = 0, False
    for t in range(A, i):
        if sup:
            tt = lo[t] <= y(t) + P.eps * at[t] and cl[t] >= y(t) - P.delta * at[t]
        else:
            tt = hi[t] >= y(t) - P.eps * at[t] and cl[t] <= y(t) + P.delta * at[t]
        if tt and not prev:
            touch += 1
        prev = tt
    return dict(A=A, B=B, m=m, slope=m / at[B], y=y(i), brk=brk, touch=touch)


def ref_features(df: pd.DataFrame, i: int, s: int, P: TL.Params = TL.DEFAULT) -> dict:
    sup, res = ref_line(df, i, "sup", P), ref_line(df, i, "res", P)
    c = float(df["close"].iloc[i])
    a = float(df["atr"].iloc[i])
    if not (a > 0):
        return {k: np.nan for k in TL.FEATURES}
    ahead, behind = (res, sup) if s == 1 else (sup, res)
    live = lambda x: x is not None and x["brk"] < 0    # noqa: E731
    d_ah = min(max(s * (ahead["y"] - c) / a, 0.0), P.cap) if live(ahead) else P.cap
    d_bh = min(max(s * (c - behind["y"]) / a, 0.0), P.cap) if live(behind) else P.cap
    trend = 3 if live(sup) and live(res) else 1 if live(sup) else 2 if live(res) else 0
    brk_ah = ahead["brk"] if ahead is not None else -1
    return dict(
        tl_ahead=d_ah, tl_behind=d_bh,
        tl_break_now=float(brk_ah == i),
        tl_against=float(live(ahead) and d_ah < P.near),
        tl_support=float(live(behind) and d_bh < P.near),
        tl_aligned=float((s == 1 and trend == 1) or (s == -1 and trend == 2)),
        tl_touch_ahead=float(ahead["touch"]) if live(ahead) else np.nan,
        tl_touch_behind=float(behind["touch"]) if live(behind) else np.nan,
        tl_slope_ahead=ahead["slope"] if live(ahead) else np.nan,
        tl_slope_behind=behind["slope"] if live(behind) else np.nan,
        tl_age_ahead=float(i - ahead["A"]) if live(ahead) else np.nan,
        tl_age_behind=float(i - behind["A"]) if live(behind) else np.nan,
        tl_break_3=float(brk_ah >= 0 and brk_ah >= i - 2),
        tl_break_10=float(brk_ah >= 0 and brk_ah >= i - 9),
        tl_trend=float(trend))


def _state(ln: dict, kind: str, i: int):
    s = ln[kind]
    if not s["has"][i]:
        return None
    return dict(A=int(s["A"][i]), B=int(s["B"][i]), m=float(s["m"][i]), slope=float(s["slope"][i]),
                y=float(s["y"][i]), brk=int(s["brk"][i]), touch=int(s["touch"][i]))


@pytest.mark.parametrize("n,seed,P", [
    (900, 1, TL.DEFAULT),
    (700, 2, TL.DEFAULT),
    (600, 3, TL.Params(k=3, window=80, slope_max=0.25, delta=0.1, eps=0.5)),
    (500, 4, TL.Params(k=8, window=150, slope_max=1.0, delta=0.5, eps=0.1)),
])
def test_lines_match_reference_on_every_bar(n, seed, P):
    df = synth(n, seed)
    ln = TL.lines_for(df["high"], df["low"], df["close"], df["atr"], P)
    seen = {"sup": 0, "res": 0, "brk": 0, "touch3": 0}
    for i in range(n):
        for kind in ("sup", "res"):
            want = ref_line(df, i, kind, P)
            got = _state(ln, kind, i)
            assert (want is None) == (got is None), (kind, i, want, got)
            if want is None:
                continue
            for k in ("A", "B", "brk", "touch"):
                assert got[k] == want[k], (kind, i, k, got, want)
            for k in ("m", "slope", "y"):
                assert got[k] == want[k], (kind, i, k, got[k], want[k])   # exact, also for the mirrored line
            seen[kind] += 1
            seen["brk"] += want["brk"] >= 0
            seen["touch3"] += want["touch"] >= 3
    assert min(seen.values()) > 10, seen      # not vacuous: lines, breaks and multi-touch lines all occur


@pytest.mark.parametrize("n,seed", [(800, 5), (650, 6)])
def test_features_match_reference(n, seed):
    df = synth(n, seed)
    rng = np.random.default_rng(seed)
    idx = np.r_[rng.choice(np.arange(n), 120, replace=False), 0, 13, 14, n - 1]
    for s in (1, -1):
        f = TL.features_for(df, idx, np.full(len(idx), s))
        for k, i in enumerate(idx):
            want = ref_features(df, int(i), s)
            for key, val in want.items():
                got = f[key][k]
                assert (np.isnan(val) and np.isnan(got)) or got == val, (i, s, key, got, val)
    full = TL.features_for(df, np.arange(n), np.ones(n, int))
    assert np.nansum(full["tl_break_now"]) > 0 and np.nansum(full["tl_against"]) > 0
    assert np.nansum(full["tl_support"]) > 0 and np.nansum(full["tl_aligned"]) > 0


def test_subset_of_bars_equals_all_bars():
    df = synth(700, 9)
    idx = np.array([5, 99, 300, 301, 650, 699])
    side = np.array([1, -1, 1, -1, -1, 1])
    a = TL.features_for(df, idx, side)
    b = TL.features_for(df, np.arange(700), np.ones(700, int))
    c = TL.features_for(df, np.arange(700), -np.ones(700, int))
    for k in TL.FEATURES:
        want = np.where(side == 1, b[k][idx], c[k][idx])
        np.testing.assert_array_equal(a[k], want, err_msg=k)


# ------------------------------------------------------------------ causality
def _garbage(df: pd.DataFrame, i: int, seed: int) -> pd.DataFrame:
    g = df.copy()
    rng = np.random.default_rng(seed)
    m = len(df) - i - 1
    if m <= 0:
        return g
    x = rng.uniform(1.0, 1000.0, (m, 4))
    rows = g.index[i + 1:]
    g.loc[rows, "open"] = x[:, 0]
    g.loc[rows, "close"] = x[:, 1]
    g.loc[rows, "high"] = x.max(axis=1)
    g.loc[rows, "low"] = x.min(axis=1)
    if "atr" in g:
        g.loc[rows, "atr"] = rng.uniform(0.0, 50.0, m)
    return g


@pytest.mark.parametrize("n,seed,with_atr", [(700, 7, True), (600, 8, False)])
def test_causality_every_feature(n, seed, with_atr):
    """Replace every bar after the signal bar with garbage: no feature of the signal bar may change.
    with_atr=False: the ATR is computed inside with the backtest's fg.atr (also causal)."""
    df = synth(n, seed, with_atr=with_atr)
    rng = np.random.default_rng(seed + 1)
    base_all = {s: TL.features_for(df, np.arange(n), np.full(n, s)) for s in (1, -1)}
    # bars where something happens (a break now, a live line, a fresh swing) plus random bars
    eventful = np.flatnonzero((base_all[1]["tl_break_now"] == 1) | (base_all[-1]["tl_break_now"] == 1))[:6]
    idx = np.unique(np.r_[rng.choice(np.arange(20, n - 1), 14, replace=False), eventful, 299, 300])
    changed = False
    for i in idx:
        g = _garbage(df, int(i), seed=int(i))
        for s in (1, -1):
            f = TL.features_for(g, [i], [s])
            for key in TL.FEATURES:
                np.testing.assert_array_equal(f[key], base_all[s][key][i:i + 1], err_msg=f"bar {i} side {s} {key}")
        if i + 40 < n and not changed:
            later = TL.features_for(g, [i + 40], [1])
            ref = TL.features_for(df, [i + 40], [1])
            changed = any(not np.array_equal(later[k], ref[k], equal_nan=True) for k in TL.FEATURES)
    assert changed, "garbage did not change later features: the test would be vacuous"


# ------------------------------------------------------------------ hand-made series
def hand(n: int, lows: dict, closes: dict | None = None, atr: float = 0.5, base: float = 99.0) -> pd.DataFrame:
    """Lows rise by 0.01 per bar from ``base`` (no swing lows), highs = low + 1 (rising: no swing highs),
    closes = low + 0.5; ``lows`` / ``closes`` set single bars (a set low also lowers that bar's close
    to low + 0.5 unless ``closes`` gives it)."""
    lo = base + 0.01 * np.arange(n)
    cl = lo + 0.5
    for j, v in lows.items():
        lo[j] = v
        cl[j] = v + 0.5
    for j, v in (closes or {}).items():
        cl[j] = v
        lo[j] = min(lo[j], v)
    hi = np.maximum(lo + 1.0, cl)
    return pd.DataFrame({"high": hi, "low": lo, "close": cl, "atr": np.full(n, atr)})


def line_at(df, i, kind="sup", P=TL.DEFAULT):
    ln = TL.lines_for(df["high"], df["low"], df["close"], df["atr"], P)
    return _state(ln, kind, i)


def test_prereg_example_2_5():
    # A = bar 100 (low 95.0), B = bar 140 (low 97.0): m = 0.05 / bar, ATR 0.5 -> 0.1 ATR per bar
    df = hand(170, {100: 95.0, 140: 97.0}, closes={160: 98.6})
    s = line_at(df, 160)
    assert (s["A"], s["B"]) == (100, 140)
    assert s["slope"] == pytest.approx(0.1) and s["y"] == pytest.approx(98.0) and s["brk"] == -1
    assert s["touch"] == 2                                   # A and B
    f = {k: v[0] for k, v in TL.features_for(df, [160], [1]).items()}
    assert f["tl_behind"] == pytest.approx(1.2) and f["tl_support"] == 1
    assert f["tl_ahead"] == 10 and f["tl_against"] == 0      # no resistance line (highs only rise)
    assert f["tl_aligned"] == 1 and f["tl_trend"] == 1       # only a live support line: trend up
    assert f["tl_age_behind"] == 60 and f["tl_touch_behind"] == 2
    g = {k: v[0] for k, v in TL.features_for(df, [160], [-1]).items()}
    assert g["tl_ahead"] == pytest.approx(1.2) and g["tl_against"] == 1 and g["tl_aligned"] == 0
    assert g["tl_behind"] == 10 and g["tl_support"] == 0


def test_swing_usable_only_from_j_plus_5():
    df = hand(170, {100: 95.0, 140: 97.0})
    assert line_at(df, 144) is None                          # B = 140 not usable yet; 100 alone is no line
    assert line_at(df, 145)["B"] == 140


def test_slope_cap_inclusive_and_falls_back_to_an_older_swing():
    # B = 132 (97.0), candidate A = 124 (95.0): m = 0.25 / bar = 0.5 ATR / bar, exactly at the cap: accepted
    df = hand(160, {100: 94.0, 124: 95.0, 132: 97.0})
    assert line_at(df, 150)["A"] == 124
    # 94.99 at 124: 0.5025 ATR / bar is too steep -> the older swing at 100 (94.0 -> 97.0 over 32 bars)
    df = hand(160, {100: 94.0, 124: 94.99, 132: 97.0}, closes={124: 96.5})   # close above y(124) = 96.25
    s = line_at(df, 150)
    assert s["A"] == 100 and s["slope"] == pytest.approx(3.0 / 32 / 0.5)


def test_closes_between_a_and_b():
    # A = 100 (95.0), B = 132 (97.0): m = 0.0625 exactly; y(124) = 96.5, limit 96.5 - 0.125 = 96.375.
    # Bar 124 is a swing low too (94.0) but too steep as an A (3 / 8 = 0.75 ATR / bar).
    df = hand(160, {100: 95.0, 124: 94.0, 132: 97.0}, closes={124: 96.375})
    s = line_at(df, 150)
    assert (s["A"], s["B"]) == (100, 132)                    # a close exactly at the limit is allowed
    assert s["touch"] == 3                                   # A, the wick at 124, B
    df = hand(160, {100: 95.0, 124: 94.0, 132: 97.0}, closes={124: 96.37})
    assert line_at(df, 150) is None                          # one close too far below: no line


def test_300_bar_window_and_new_low_and_ties():
    df = hand(460, {100: 95.0, 140: 97.0})
    assert line_at(df, 399)["A"] == 100                      # A = i - 299: inside
    assert line_at(df, 400) is None                          # A = i - 300: outside
    df = hand(170, {100: 97.0, 140: 97.0})
    assert line_at(df, 160) is None                          # equal lows: A must be lower than B
    df = hand(170, {100: 95.0, 140: 94.0})
    assert line_at(df, 160) is None                          # B is a new low: no rising line
    df = hand(170, {100: 95.0, 101: 95.0, 140: 97.0})        # two equal lows next to each other: both swings
    assert line_at(df, 160)["A"] == 101                      # the most recent one is tried first
    P = TL.Params(window=150)
    df = hand(300, {100: 95.0, 140: 97.0})
    assert line_at(df, 249, P=P)["A"] == 100 and line_at(df, 250, P=P) is None


def test_break_and_features_after_it():
    # line A = 100 (95.0), B = 140 (97.0); closes 97.9 on 145..149 sit 0.9 .. 1.3 ATR above it;
    # y(150) = 97.5, break limit 97.375: the close 97.3 at 150 breaks it
    closes = {t: 97.9 for t in range(145, 150)}
    closes[150] = 97.3
    df = hand(170, {100: 95.0, 140: 97.0}, closes=closes)
    assert line_at(df, 149)["brk"] == -1
    for i in range(150, 155):                                # until the dip at 150 becomes a swing (155)
        s = line_at(df, i)
        assert (s["A"], s["B"], s["brk"]) == (100, 140, 150)
    f = TL.features_for(df, np.arange(148, 155), np.full(7, -1))   # short: the support line is ahead
    assert f["tl_ahead"][0] == pytest.approx(1.0)            # (97.9 - y(148) = 97.4) / 0.5
    assert f["tl_break_now"].tolist() == [0, 0, 1, 0, 0, 0, 0]
    assert f["tl_break_3"].tolist() == [0, 0, 1, 1, 1, 0, 0]
    assert f["tl_break_10"].tolist() == [0, 0, 1, 1, 1, 1, 1]
    assert f["tl_against"].tolist() == [1, 1, 0, 0, 0, 0, 0]  # broken: no longer against
    assert (f["tl_ahead"][2:] == 10).all() and np.isnan(f["tl_touch_ahead"][2:]).all()
    assert f["tl_aligned"].tolist() == [0] * 7
    g = TL.features_for(df, np.arange(148, 155), np.full(7, 1))    # long: the broken support is behind
    assert g["tl_support"].tolist() == [1, 1, 0, 0, 0, 0, 0] and (g["tl_behind"][2:] == 10).all()
    assert (g["tl_break_now"] == 0).all()                    # a break against the trade is not T1
    assert g["tl_aligned"].tolist() == [1, 1, 0, 0, 0, 0, 0]  # after the break: no live line, trend none
    s = line_at(df, 155)                                     # the dip at 150 is now the latest swing low:
    assert (s["A"], s["B"], s["brk"]) == (140, 150, -1)      # a new line, its breaks counted after its own B


def test_resistance_is_the_mirror_of_support():
    df = synth(700, 11)
    C = 300.0
    mir = pd.DataFrame({"high": C - df["low"], "low": C - df["high"], "close": C - df["close"], "atr": df["atr"]})
    a = TL.lines_for(df["high"], df["low"], df["close"], df["atr"])
    b = TL.lines_for(mir["high"], mir["low"], mir["close"], mir["atr"])
    np.testing.assert_array_equal(a["sup"]["has"], b["res"]["has"])
    np.testing.assert_array_equal(a["sup"]["A"], b["res"]["A"])
    np.testing.assert_array_equal(a["sup"]["brk"], b["res"]["brk"])
    np.testing.assert_array_equal(a["sup"]["touch"], b["res"]["touch"])
    np.testing.assert_allclose(C - a["sup"]["y"], b["res"]["y"], rtol=0, atol=1e-9)
    np.testing.assert_allclose(a["sup"]["slope"], -b["res"]["slope"], rtol=1e-9)
    fa = TL.features_for(df, np.arange(700), np.ones(700, int))
    fb = TL.features_for(mir, np.arange(700), -np.ones(700, int))
    for k in TL.FEATURES:
        if k.startswith("tl_slope"):
            np.testing.assert_allclose(fa[k], -fb[k], rtol=1e-9, err_msg=k)
        elif k == "tl_trend":
            np.testing.assert_array_equal(fa[k], np.select([fb[k] == 1, fb[k] == 2], [2.0, 1.0], fb[k]))
        else:
            np.testing.assert_allclose(fa[k], fb[k], rtol=0, atol=1e-7, err_msg=k)
    assert np.nansum(fa["tl_support"]) > 0 and np.nansum(fa["tl_against"]) > 0


def test_missing_atr_means_no_line_and_no_features():
    df = hand(170, {100: 95.0, 140: 97.0})
    df.loc[140, "atr"] = np.nan                              # ATR at B missing: no line
    assert line_at(df, 160) is None
    df = hand(170, {100: 95.0, 140: 97.0})
    df.loc[160, "atr"] = 0.0                                 # signal bar ATR not positive: features NaN
    f = TL.features_for(df, [160], [1])
    assert all(np.isnan(f[k][0]) for k in TL.FEATURES)


def test_side_validation():
    df = hand(50, {})
    with pytest.raises(ValueError):
        TL.features_for(df, [10, 11], [1])
    with pytest.raises(ValueError):
        TL.features_for(df, [10], [0])


# ------------------------------------------------------------------ analysis: helpers and a smoke run
AN = pytest.importorskip("analysis_trendline")


def test_test_directions_and_bootstrap_size():
    rng = np.random.default_rng(0)
    W = 100
    n0 = np.full(W, 20.0); n1 = np.full(W, 20.0)
    s0 = rng.normal(0.02 * n0, 0.1); s1 = rng.normal(-0.02 * n1, 0.1)       # group 0 better
    C = AN.boot(W, 1000, "5m", 1)
    assert C.shape == (10_000, W)
    t2 = AN.wb_test("T2", n0, s0, n1, s1, C)                 # T2: mean0 - mean1 > 0 -> true here
    t1 = AN.wb_test("T1", n0, s0, n1, s1, C)                 # T1: mean1 - mean0 -> negative
    assert t2["diff"] > 0 and t2["p"] == pytest.approx(1 / 10_001)
    assert t1["diff"] == pytest.approx(-t2["diff"]) and t1["p"] > 0.99
    assert AN.boot(W, 1000, "5m", 2).shape == (2000, W)
    np.testing.assert_array_equal(AN.boot(W, 7, "1h", 3), AN.boot(W, 7, "1h", 3))   # seeded


def test_prereg_hash_check(tmp_path, monkeypatch):
    assert AN.check_prereg()["prereg_hash_ok"]
    bad = tmp_path / "bad.sha256"
    bad.write_text("0" * 64 + "  research/entry_study/PREREG_TRENDLINE.md\n")
    assert not AN.check_prereg(AN.PREREG, str(bad))["prereg_hash_ok"]
    monkeypatch.setattr(AN, "PREREG_SHA", str(bad))
    with pytest.raises(SystemExit, match="does not match"):
        AN.main(["x", "stage2"])


def _write_cache(d, coin_i, coin, start, end, names, rng, dense):
    ts = pd.date_range(start, end, freq="240min")
    n = len(ts)
    r = rng.normal(0, 0.012, n) + np.repeat(rng.normal(0, 0.004, n // 60 + 1), 60)[:n]
    c = 100.0 * (1 + coin_i) * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    tr = np.maximum(h - lo, np.maximum(np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(lo - np.r_[np.nan, c[:-1]])))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().to_numpy()
    z = dict(ts=ts.as_unit("ns").asi8, o=o, h=h, l=lo, c=c, v=np.ones(n), atr=atr)
    for k, nm in enumerate(names):
        prob = 0.04 if dense[k] else 0.002
        u = rng.random(n)
        z["s__" + nm] = np.where(u < prob / 2, 1, np.where(u < prob, -1, 0)).astype(np.int8)
    np.savez(os.path.join(d, f"sig_4h_{coin}.npz"), **z)


def test_analysis_smoke_on_synthetic_caches(tmp_path, monkeypatch):
    L = AN._lib()
    names = AN.A.strategy_names(L)
    sig12, sig3 = tmp_path / "sig12", tmp_path / "sig3"
    sig12.mkdir(); sig3.mkdir()
    rng = np.random.default_rng(42)
    dense = np.arange(len(names)) % 6 != 5                   # every 6th strategy too sparse to test
    for ci, coin in enumerate(AN.COINS):
        _write_cache(sig12, ci, coin, "2021-01-01", "2026-09-29 20:00", names, rng, dense)
        _write_cache(sig3, ci, coin, "2020-01-01", "2021-08-31 20:00", names, rng, dense)
    for k in ("TL_SIG12", "TL_SIG3", "TL_OUT", "TL_CACHE", "TL_TFS"):
        monkeypatch.setenv(k, "")
    for k in ("SIG12", "SIG3", "OUT", "CACHE", "TFS"):
        monkeypatch.setattr(AN, k, getattr(AN, k))
    out, cache = tmp_path / "out", tmp_path / "cache"
    AN.main(["x", "run", "1", "--sig12", str(sig12), "--sig3", str(sig3), "--out", str(out), "--cache", str(cache),
             "--tfs", "4h"])
    trials = pd.read_csv(out / "trendline_trials.csv")
    cells = pd.read_csv(out / "trendline_cells.csv")
    meta = json.load(open(out / "trendline_run_meta.json"))
    cand = json.load(open(out / "trendline_candidates.json"))
    rnd = pd.read_csv(out / "trendline_random.csv")
    n_tested = int(cells["tested"].sum())
    assert 0 < n_tested < len(names) == len(cells)
    assert len(trials) == 4 * n_tested + 4 and trials["trial_id"].is_unique
    assert (trials["kind"] == "random").sum() == 4
    assert meta["prereg_hash_ok"] is True and "robustness_rerun" in meta and cand["robustness_rerun"]
    assert meta["code_sha256"] and meta["headline"]["trials"] == len(trials)
    ok1 = trials["status_p1"] == "ok"
    assert ok1.sum() > 0
    assert (trials.loc[ok1, "p_p1"] >= 1 / 10_001 - 1e-15).all() and (trials.loc[ok1, "p_p1"] <= 1).all()
    np.testing.assert_allclose(trials["p_for_bh"], np.where(ok1, trials["p_p1"], 1.0))
    assert trials.loc[trials["candidate"], "pass_p1_bh"].all()
    # T2's difference is mean(=0) - mean(=1), the others mean(=1) - mean(=0)
    for t in AN.TESTS:
        x = trials[(trials["test"] == t) & ok1]
        want = np.where(AN.GOOD[t] == 1, x["mean1_p1"] - x["mean0_p1"], x["mean0_p1"] - x["mean1_p1"])
        np.testing.assert_allclose(x["diff_p1"], want, rtol=1e-12)
    # the random entries are part A's draw: n0 + n1 of a random test = random trades (pooled)
    rp = rnd[(rnd["scope"] == "pooled") & (rnd["period"] == 1)].iloc[0]
    rt = trials[(trials["kind"] == "random") & (trials["test"] == "T1")].iloc[0]
    assert rt["n0_p1"] + rt["n1_p1"] == rp["n_trades"] > 0
    desc = json.load(open(out / "trendline_descriptive.json"))
    blk = desc["by_tf_period"]["4h"]["1"]["strategies_pooled"]
    assert sum(r["n"] for r in blk["ahead_bucket"]) == blk["n_trades"] > 0
    # the per-pair cache holds what the checks need
    z = np.load(cache / "tl_4h_BTCUSD_p12.npz")
    assert {"roe", "lev", "week", "valid", "tl_break_now", f"u__{names[0]}__p1", "u__" + AN.RANDOM_UNIT + "__p2"} <= set(z.files)
    # checks run on whatever candidates there are (usually none on noise) and write their files
    doc = AN.checks(str(tmp_path / "no_binance"))
    assert doc["candidates"] == int(trials["candidate"].sum())
    assert (out / "trendline_checks.json").exists() and (out / "trendline_trials_checks.csv").exists()
