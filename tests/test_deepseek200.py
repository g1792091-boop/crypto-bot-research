"""Deepseek-200 new-family test: PREREG hash, configuration count, look-ahead, hand-built micro examples.

Synthetic data only, no network, no real bars. Fast (about a minute).
"""
import datetime as dt
import hashlib
import importlib.util
import os
import re
import sys
import zoneinfo

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = os.path.join(ROOT, "research", "deepseek200")
sys.path.insert(0, DS)

spec = importlib.util.spec_from_file_location("lib_c", os.path.join(DS, "lib_c.py"))
C = importlib.util.module_from_spec(spec)
sys.modules["lib_c"] = C
spec.loader.exec_module(C)


# ------------------------------------------------------------------ helpers
def frame(rows, start="2021-01-01", tf="1h", warm=60):
    """Alternating-flat warm-up (close 100 / 100.1, range +-0.3) then the given (o, h, l, c) rows; volume 1."""
    w = [(100.0 if i % 2 == 0 else 100.1,) for i in range(warm)]
    base = []
    for i in range(warm):
        cl = 100.0 if i % 2 == 0 else 100.1
        op = 100.1 if i % 2 == 0 else 100.0
        base.append((op, max(op, cl) + 0.3, min(op, cl) - 0.3, cl))
    allr = base + list(rows)
    ts = pd.date_range(start, periods=len(allr), freq=f"{C.TF_MIN[tf]}min", tz="UTC")
    a = np.array(allr, float)
    return pd.DataFrame({"ts": ts, "open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": 1.0})


def idx_of(sig, side):
    return list(np.flatnonzero(sig[side]))


def flat(c, rng=0.3):
    return (c, c + rng, c - rng, c)


# ------------------------------------------------------------------ pre-registration and counts
def test_prereg_hash():
    with open(os.path.join(DS, "PREREG_DEEPSEEK200.sha256")) as fh:
        want, name = fh.read().split()
    assert name == "PREREG_DEEPSEEK200.md"
    with open(os.path.join(DS, name), "rb") as fh:
        got = hashlib.sha256(fh.read()).hexdigest()
    assert got == want, "PREREG changed after the hash was recorded: a change is a new pre-registration"


def test_config_count_and_prereg_consistency():
    cfg = C.config_list()
    assert len(cfg) == 342 and len(set(cfg)) == 342
    assert len(C.DEFS) == 44
    assert {d[1] for d in C.DEFS} == {f"F{i}" for i in range(1, 18)}
    assert set(C.TFS) == {"15m", "30m", "1h", "4h"} and len(C.EXIT_NAMES) == 2
    # 39 definitions on four timeframes + 5 ET-session definitions on three
    assert sum(1 for t, d, x in cfg if d.startswith("F15_")) == (5 * 3 + 4) * 2
    et5 = {"F15_ASIA_BRK", "F15_ASIA_SWEEP", "F15_LON_BRK", "F15_OPEN0930", "F15_OPEN0000"}
    assert not any(t == "4h" and d in et5 for t, d, x in cfg)
    assert {d for t, d, x in cfg if t == "4h" and d.startswith("F15_")} == {"F15_ORB"}
    assert {d for t, d, x in cfg if t == "4h" and d.startswith("F11_")} == {"F11_TSOUP", "F11_RAID", "F11_PO3"}
    with open(os.path.join(DS, "PREREG_DEEPSEEK200.md"), encoding="utf-8") as fh:
        text = fh.read()
    for d in C.DEF_IDS:
        assert d in text, f"{d} missing from the PREREG"
    assert "N = 171 × 2 = 342" in text
    # every B item (66) is either mapped to a definition or listed as not tested in section 6
    b = [2, 15, 18, 23, 24, 30, 32, 34, 39, 40, 45, 49, 51, 52, 53, 58, 62, 63, 65, 67, 72, 74, 79, 80, 81, 82, 83, 84, 85, 86, 87,
         88, 89, 90, 91, 92, 96, 97, 98, 100, 103, 104, 105, 106, 107, 108, 112, 129, 130, 133, 134, 135, 136, 137, 151, 152, 168,
         169, 170, 171, 172, 173, 180, 181, 182, 184]
    assert len(b) == 66
    sec6 = text.split("## 6.")[1].split("## 7.")[0]
    not_tested = {49, 79, 85, 89, 97, 98, 104, 171, 173, 184}
    for k in not_tested:
        assert re.search(rf"\|\s*{k}\s*\|", sec6), k
    # the section-6 summary names each remaining item with an arrow
    for k in set(b) - not_tested:
        assert re.search(rf"(?<![0-9]){k}(?![0-9])", text.split("## 5.")[1].split("## 7.")[0]), k


# ------------------------------------------------------------------ ET / DST rule
def test_et_offset_matches_iana():
    ts = pd.date_range("2019-12-01", "2027-01-31", freq="30min", tz="UTC")
    arr = ts.tz_localize(None).to_numpy().astype("datetime64[ns]")
    ours = C.et_offset_minutes(arr)
    ny = zoneinfo.ZoneInfo("America/New_York")
    want = np.array([int(t.astimezone(ny).utcoffset().total_seconds() // 60) for t in ts.to_pydatetime()])
    assert np.array_equal(ours, want)
    # the documented examples: 09:30 ET = 13:30 UTC in summer, 14:30 UTC in winter
    d, m = C.et_wall(np.array(["2021-07-13T13:30", "2021-01-12T14:30"], "datetime64[ns]"))
    assert list(m) == [9 * 60 + 30, 9 * 60 + 30]
    for y in range(2020, 2027):
        assert C._nth_sunday(y, 3, 2).weekday() == 6 and C._nth_sunday(y, 11, 1).weekday() == 6


# ------------------------------------------------------------------ look-ahead
@pytest.mark.parametrize("tf,n", [("1h", 2600), ("15m", 2600), ("4h", 2600), ("30m", 2200)])
def test_no_lookahead_every_definition(tf, n):
    C.lookahead_check(tf, n=n)


def test_lookahead_check_detects_a_leak(monkeypatch):
    """The comparison used above must catch a definition that peeks one bar ahead (or at a changed future)."""
    real = C.entries

    def leaky(df, tf, ctx=None, coin=""):
        out = real(df, tf, ctx, coin)
        cc = df["close"].to_numpy()
        out["LEAK"] = (np.r_[cc[1:] > cc[:-1], False], np.zeros(len(cc), bool))
        return out
    monkeypatch.setattr(C, "entries", leaky)
    with pytest.raises(AssertionError, match="lookahead"):
        C.lookahead_check("1h", n=1500)


def test_determinism_bool_and_exclusive():
    df, btc = C.synth(3000, "1h", 21), C.synth(3000, "1h", 22)
    a = C.entries(df, "1h", {"BTCUSD": btc}, "ETHUSD")
    b = C.entries(df, "1h", {"BTCUSD": btc}, "ETHUSD")
    assert set(a) == set(C.DEF_IDS)
    for k in a:
        assert a[k][0].dtype == bool and a[k][1].dtype == bool
        assert np.array_equal(a[k][0], b[k][0]) and np.array_equal(a[k][1], b[k][1])
        assert not (a[k][0] & a[k][1]).any()
    df4 = C.synth(1500, "4h", 23)
    a4 = C.entries(df4, "4h", {"BTCUSD": C.synth(1500, "4h", 24)}, "ETHUSD")
    assert set(a4) == {d for d, _f, tfs in C.DEFS if "4h" in tfs} and len(a4) == 39


def test_pipeline_finite_and_one_position(monkeypatch):
    monkeypatch.setattr(C, "PERIODS", {"is": ("2021-02-15", "2021-07-01"), "oos": ("2021-07-01", "2021-12-01"), "pre": ("2020-03-01", "2020-12-01")})
    df = C.synth(9000, "1h", 31, start="2021-01-01")
    pre = C.synth(9000, "1h", 32, start="2020-01-01")
    btc, btc_pre = C.synth(9000, "1h", 33, start="2021-01-01"), C.synth(9000, "1h", 34, start="2020-01-01")
    tr = pd.concat([C.run_series(df, "1h", "ETHUSD", ["is", "oos"], {"BTCUSD": btc}),
                    C.run_series(pre, "1h", "ETHUSD", ["pre"], {"BTCUSD": btc_pre})], ignore_index=True)
    assert len(tr) > 500
    for col in ("net", "gross", "mae", "sl_dist"):
        assert np.isfinite(tr[col].astype(float)).all(), col
    assert set(tr["exit"]) == set(C.EXIT_NAMES) and set(tr["split"]) == {"is", "oos", "pre"}
    for (_e, _x, _s), g in tr.groupby(["entry", "exit", "split"]):
        g = g.sort_values("entry_ts")
        assert (g["entry_ts"].to_numpy()[1:] > g["exit_ts"].to_numpy()[:-1]).all()      # one position at a time
    # statistics + gauntlet + decision rule on the synthetic trades, then padded to all N rows
    tr["symbol"] = tr["symbol"].astype("category")
    rows = C.extra_rows(tr, 200)
    t = C.finish(rows)
    assert len(t) == 342 and t["p12"].between(0, 1).all()
    assert (t["candidate"] <= t["stage3"]).all() and (t["candidate_20x"] <= t["candidate"]).all()
    assert t.attrs.get("top_k", 0) <= 30


# ------------------------------------------------------------------ micro examples (each definition's core detection)
def test_pivot_confirmation_lag():
    h = np.array([5, 5, 5, 5, 9, 5, 5, 5, 5, 5, 5], float)
    l = h - 1
    ph, pl = C.pivots_conf(h, l)
    assert list(np.flatnonzero(ph)) == [7]               # pivot at bar 4 is known at bar 7
    h2 = h.copy()
    h2[5] = 9                                            # equal highs next to it: not a strict pivot
    assert not C.pivots_conf(h2, h2 - 1)[0].any()
    l3 = np.array([5, 5, 5, 5, 1, 5, 5, 5, 5, 5, 5], float)
    assert list(np.flatnonzero(C.pivots_conf(l3 + 1, l3)[1])) == [7]


def test_fvg_zone_retest_exact_bar():
    rows = [(100, 100.5, 99.5, 100),                    # 60  A: high 100.5
            (100, 104, 100, 103.8),                      # 61  B: displacement
            (103.8, 104.5, 102.0, 104.2)]                # 62  C: low 102 > high of A: gap [100.5, 102], 1.5 >= 0.5 ATR
    rows += [(104, 104.5, 103.5, 104)] * 3               # 63-65 no touch (lows 103.5 > 102)
    rows += [(104, 104.2, 101.8, 102.5)]                 # 66 first touch, close 102.5 >= mid 101.25 -> long
    rows += [(102.5, 103.6, 101.9, 102.8)] * 3
    df = frame(rows)
    s = C.entries(df, "1h", None, "ETHUSD")["F9_FVG"]
    assert idx_of(s, 0) == [66] and idx_of(s, 1) == []
    rows[6] = (104, 104.2, 101.8, 101.0)                 # first touch closes below the midpoint: zone spent, no trade
    s = C.entries(frame(rows), "1h", None, "ETHUSD")["F9_FVG"]
    assert idx_of(s, 0) == []
    rows2 = list(rows)
    rows2[6] = (104, 104.2, 101.8, 102.5)
    rows2[2] = (103.8, 104.5, 100.8, 104.2)              # gap only 0.3 < 0.5 ATR: no zone
    s = C.entries(frame(rows2), "1h", None, "ETHUSD")["F9_FVG"]
    assert idx_of(s, 0) == []
    # bearish mirror: reflect every price around 100 (the warm-up level)
    ref = [(200 - o, 200 - lo, 200 - h, 200 - c) for o, h, lo, c in
           [(100, 100.5, 99.5, 100), (100, 104, 100, 103.8), (103.8, 104.5, 102.0, 104.2)] + [(104, 104.5, 103.5, 104)] * 3
           + [(104, 104.2, 101.8, 102.5)] + [(102.5, 103.6, 101.9, 102.8)] * 3]
    s = C.entries(frame(ref), "1h", None, "ETHUSD")["F9_FVG"]
    assert idx_of(s, 1) == [66] and idx_of(s, 0) == []


def test_inverted_fvg_and_ob_breaker():
    # bullish FVG, then a close below its low (inversion), then a retest from below that closes under the midpoint
    rows = [(100, 100.5, 99.5, 100), (100, 104, 100, 103.8), (103.8, 104.5, 102.0, 104.2),
            (104.2, 104.3, 100.0, 100.2),                 # 63: close 100.2 < lo 100.5 -> inverted (short zone [100.5, 102])
            (100.2, 100.4, 99.6, 99.8), (99.8, 100.0, 99.4, 99.7),
            (99.7, 101.0, 99.5, 99.9),                    # 66: high 101 >= lo 100.5 touch, close 99.9 <= mid 101.25 -> short
            (99.9, 100.2, 99.4, 99.8)]
    s = C.entries(frame(rows), "1h", None, "ETHUSD")["F9_IFVG"]
    assert idx_of(s, 1) == [66] and idx_of(s, 0) == []
    # order block: bearish candle k, bullish close above its high, next low above its high; retest holds
    rows = [(100.0, 100.3, 99.0, 99.2),                  # 60 k: bearish [99.0, 100.3]
            (99.2, 102.5, 99.1, 102.2),                  # 61 close 102.2 > 100.3
            (102.2, 103.0, 100.5, 102.8),                # 62 low 100.5 > 100.3 -> OB zone born at 62
            (103, 103.4, 102.6, 103.2), (103.2, 103.5, 102.7, 103.1),
            (103.1, 103.3, 99.8, 100.9),                 # 65: touches high of k (100.3), close 100.9 >= mid 99.65 -> long
            (100.9, 101.5, 100.5, 101.2)]
    s = C.entries(frame(rows), "1h", None, "ETHUSD")["F9_OB"]
    assert idx_of(s, 0) == [65]
    # breaker: the OB is broken by a close below its low instead, then retested from below -> short
    rows = [(100.0, 100.3, 99.0, 99.2), (99.2, 102.5, 99.1, 102.2), (102.2, 103.0, 100.5, 102.8),
            (102.8, 103.0, 98.0, 98.5),                  # 63: close 98.5 < lo 99.0 -> breaker short zone [99.0, 100.3]
            (98.5, 98.9, 97.8, 98.2), (98.2, 98.7, 97.9, 98.0),
            (98.0, 99.6, 97.9, 98.4),                    # 66: high 99.6 >= 99.0 touch, close 98.4 <= mid 99.65 -> short
            (98.4, 98.8, 98.0, 98.3)]
    s = C.entries(frame(rows), "1h", None, "ETHUSD")["F9_BREAKER"]
    assert idx_of(s, 1) == [66]


def _sweep_rows(close_back):
    return [(100, 100.5, 99.5, 100)] * 4 + [(99.5, 99.6, 97.0, 99.0)] + [(100, 100.5, 99.5, 100)] * 5 + \
           [(99.5, 100.0, 96.5, close_back)]


def test_sweep_and_reclaim():
    rows = _sweep_rows(98.0)                              # pivot low 97.0 at bar 64 (known 67); bar 70 sweeps 96.5 and closes at 98
    ent = C.entries(frame(rows), "1h", None, "ETHUSD")
    assert idx_of(ent["F11_RAID"], 0) == [70] and idx_of(ent["F11_RAID"], 1) == []
    assert idx_of(ent["F11_TSOUP"], 0) == [70]            # 20-bar low 97.0 set 6 bars earlier (>= 4), reclaimed in the same bar
    ent = C.entries(frame(_sweep_rows(96.8)), "1h", None, "ETHUSD")      # closes below the old low: a breakdown, not a sweep
    assert idx_of(ent["F11_RAID"], 0) == [] and idx_of(ent["F11_TSOUP"], 0) == []
    # Turtle Soup needs the old low to be at least 4 bars old
    rows = [(100, 100.5, 99.5, 100)] * 4 + [(99.5, 99.6, 97.0, 99.0)] + [(100, 100.5, 99.5, 100)] * 2 + [(99.5, 100.0, 96.5, 98.0)]
    ent = C.entries(frame(rows), "1h", None, "ETHUSD")
    assert idx_of(ent["F11_TSOUP"], 0) == []              # only 3 bars after the old low
    # mirror: sweep of a swing high
    mir = [(200 - o, 200 - lo, 200 - h, 200 - c) for o, h, lo, c in _sweep_rows(98.0)]
    mir = [(a[0] - 100 + 100, a[1], a[2], a[3]) for a in mir]
    # build the mirrored path around 100 instead of 200 so it joins the warm-up
    mir = [(o - 100, h - 100, lo - 100, c - 100) for o, h, lo, c in mir]
    mir = [(100 + o, 100 + h, 100 + lo, 100 + c) for o, h, lo, c in mir]
    ent = C.entries(frame(mir), "1h", None, "ETHUSD")
    assert idx_of(ent["F11_RAID"], 1) == [70] and idx_of(ent["F11_TSOUP"], 1) == [70]


def _zigzag(points, n_after=0):
    """Closes interpolated linearly between (bar, price) turning points; high/low = close +- 0.2."""
    xs, ys = zip(*points)
    c = np.interp(np.arange(xs[0], xs[-1] + 1 + n_after), xs, ys)
    out = []
    for i in range(len(c)):
        o_ = float(c[i - 1]) if i else float(c[0])
        hi_, lo_ = max(o_, float(c[i])) + 0.2, min(o_, float(c[i])) - 0.2
        if 0 < i < len(c) - 1 and c[i] > c[i - 1] and c[i] > c[i + 1]:
            hi_ += 0.3                                   # turning points get a wick so equal highs do not hide the pivot
        if 0 < i < len(c) - 1 and c[i] < c[i - 1] and c[i] < c[i + 1]:
            lo_ -= 0.3
        out.append((o_, hi_, lo_, float(c[i])))
    return out


def test_structure_bos_mss():
    # H1=110 (bar 10), L1=104 (20), H2=114 (30), L2=106 (40), H3=118 (50), then down to 100 (60)
    pts = [(0, 100), (10, 110), (20, 104), (30, 114), (40, 106), (50, 118), (60, 100)]
    rows = _zigzag(pts)
    df = frame(rows, warm=10)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    S = C.structure(o, h, l, c)
    off = 10
    # first break above the first swing high (state 0): not an event; break above 114 later: BOS up; below 106: MSS down
    first_up = off + int(np.flatnonzero(c[off:] > h[off + 10])[0])
    assert not S["bos_up"][first_up] and not S["mss_up"][first_up]
    up2 = [i for i in range(off + 33, len(c)) if c[i] > h[off + 30]][0]
    assert list(np.flatnonzero(S["bos_up"])) == [up2]
    dn = [i for i in range(off + 53, len(c)) if c[i] < l[off + 40]][0]
    assert list(np.flatnonzero(S["mss_dn"])) == [dn]
    assert not S["mss_up"].any() and not S["bos_dn"].any()
    ent = C.entries(df, "1h", None, "ETHUSD")
    assert idx_of(ent["F3_BOS"], 0) == [up2] and idx_of(ent["F3_BOS"], 1) == []
    assert idx_of(ent["F12_MSS"], 1) == [dn]
    # displacement: the same MSS bar must have a body of at least 1.2 ATR; the slow zigzag has none
    assert idx_of(ent["F12_MSS_DISP"], 1) == [] or ent["F12_MSS_DISP"][1][dn]


def test_structure_matches_naive_reference():
    """The state machine equals a deliberately naive re-implementation on random data."""
    rng = np.random.default_rng(7)
    c = 100 + np.cumsum(rng.normal(0, 1, 800))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 1, 800)
    l = np.minimum(o, c) - rng.uniform(0, 1, 800)
    S = C.structure(o, h, l, c)
    n = len(c)
    hi_lvl = lo_lvl = None
    hi_act = lo_act = False
    state = 0
    bos_up, mss_up, bos_dn, mss_dn = set(), set(), set(), set()
    raid_l, raid_s = set(), set()
    hr = lr = False
    for t in range(n):
        p = t - 3
        if p >= 3:
            if all(h[p] > h[p - j] for j in (1, 2, 3)) and all(h[p] > h[p + j] for j in (1, 2, 3)):
                hi_lvl, hi_act, hr = h[p], True, True
            if all(l[p] < l[p - j] for j in (1, 2, 3)) and all(l[p] < l[p + j] for j in (1, 2, 3)):
                lo_lvl, lo_act, lr = l[p], True, True
        up = hi_act and c[t] > hi_lvl
        dn = lo_act and c[t] < lo_lvl
        if up and not dn:
            (bos_up if state == 1 else mss_up if state == -1 else set()).add(t)
            state, hi_act = 1, False
        elif dn and not up:
            (bos_dn if state == -1 else mss_dn if state == 1 else set()).add(t)
            state, lo_act = -1, False
        if hr and h[t] > hi_lvl:
            hr = False
            if c[t] < hi_lvl:
                raid_s.add(t)
        if lr and l[t] < lo_lvl:
            lr = False
            if c[t] > lo_lvl:
                raid_l.add(t)
    assert set(np.flatnonzero(S["bos_up"])) == bos_up and set(np.flatnonzero(S["mss_up"])) == mss_up
    assert set(np.flatnonzero(S["bos_dn"])) == bos_dn and set(np.flatnonzero(S["mss_dn"])) == mss_dn
    assert set(np.flatnonzero(S["raid_long"])) == raid_l and set(np.flatnonzero(S["raid_short"])) == raid_s
    assert len(bos_up) + len(mss_up) + len(bos_dn) + len(mss_dn) > 10


def test_divergence_uses_confirmed_pivots():
    # strong rally into pivot high a (bar 64, RSI high), pullback, weaker rally to a higher pivot high b (bar 76, lower RSI)
    pts = [(60, 100.1), (64, 110), (68, 102), (76, 110.4), (82, 106)]
    rows = _zigzag(pts)
    rows = [(r[0], r[1] + 0.1, r[2], r[3]) for r in rows]
    df = frame(rows)
    ent = C.entries(df, "1h", None, "ETHUSD")
    h = df["high"].to_numpy()
    assert h[76 + 0] > h[64]
    assert idx_of(ent["F1_RSI_DIV"], 1) == [79]            # b is confirmed 3 bars later: bar 79 is the first bar that can know
    assert idx_of(ent["F1_RSI_DIV"], 0) == []
    assert idx_of(ent["F1_MOM_DIV"], 1) == [79]
    # the same path with the second high lower than the first is not a divergence of this kind
    pts = [(60, 100.1), (64, 110), (68, 102), (76, 107), (82, 104)]
    rows = _zigzag(pts)
    ent = C.entries(frame(rows), "1h", None, "ETHUSD")
    assert idx_of(ent["F1_RSI_DIV"], 1) == []


def test_fibonacci_levels_exact_bars():
    L0, H0 = 95.5, 108.3                                   # impulse low (bar 70) and high (bar 80), range 12.8 >= 3 ATR
    rows = [flat(100.0)] * 0
    path = {60: (100, 100.3, 99.7, 99.8), 61: (99.8, 100, 99, 99.2), 62: (99.2, 99.4, 98.5, 98.7), 63: (98.7, 98.9, 97.8, 98.0),
            64: (98.0, 98.2, 97.0, 97.4), 65: (97.4, 97.6, 96.5, 96.8), 66: (96.8, 97.0, 96.2, 96.4), 67: (96.4, 96.6, 96.0, 96.2),
            68: (96.2, 96.5, 95.9, 96.3), 69: (96.3, 96.8, 96.0, 96.6), 70: (96.6, 97.0, 95.5, 96.9)}
    for k, i in enumerate(range(71, 81)):                 # rally to the high at bar 80
        c = 96.9 + (108.0 - 96.9) * (k + 1) / 10
        path[i] = (path[i - 1][3], c + 0.3, c - 0.3, c)
    path[80] = (path[79][3], H0, 106.8, 107.9)
    path[81] = (107.9, 107.9, 106.0, 106.2)
    path[82] = (106.2, 106.4, 104.4, 104.6)
    path[83] = (104.6, 104.8, 103.6, 104.2)               # swing high confirmed here; no touch of 38.2% (103.41)
    path[84] = (104.2, 104.4, 102.9, 103.8)               # first touch of 38.2%, closes above it
    path[85] = (103.8, 104.0, 99.9, 100.9)                # touches 50% (101.9) and 61.8% (100.39), closes above 61.8 only
    path[86] = (100.9, 101.2, 98.0, 99.5)                 # touches 76.4% (98.52) and closes above it
    path[87] = (99.5, 100.0, 99.0, 99.6)
    path[88] = (99.6, 100.0, 99.2, 99.7)
    rows = [path[i] for i in range(60, 89)]
    df = frame(rows)
    ent = C.entries(df, "1h", None, "ETHUSD")
    span = H0 - L0
    r = {f: H0 - f * span for f in (0.382, 0.5, 0.618, 0.764)}
    assert r[0.382] > 103.4 and r[0.5] > 101.8 and 100.3 < r[0.618] < 100.5 and 98.4 < r[0.764] < 98.6
    assert idx_of(ent["F16_FIB382"], 0) == [84]
    assert idx_of(ent["F16_FIB500"], 0) == []              # first touch (bar 85) closes below the 50% level: no trade
    assert idx_of(ent["F16_FIB618"], 0) == [85]
    assert idx_of(ent["F16_FIB764"], 0) == [86]
    assert idx_of(ent["F10_OTE"], 0) == [85]               # touch of the 62% line, close above the 79% line (98.18)
    for k in ("F16_FIB382", "F16_FIB500", "F16_FIB618", "F16_FIB764", "F10_OTE"):
        assert idx_of(ent[k], 1) == []


def test_zone_killed_by_new_high_before_touch():
    # leg high exceeded before any retracement: the zone dies and later touches do not trade
    n = 20
    h = np.full(n, 10.0)
    l = np.full(n, 9.0)
    c = np.full(n, 9.5)
    h[5] = 12.0                                           # exceeds kill = 11
    l[8] = 8.5
    zones = [(2, 8.8, 8.8, 1, 11.0)]
    lg, sh = C.resolve_zones(n, h, l, zones, lambda s, lo, hi, d: True)
    assert not lg.any()
    zones = [(2, 8.8, 8.8, 1, 13.0)]                      # kill level not reached: the touch at bar 8 trades
    lg, sh = C.resolve_zones(n, h, l, zones, lambda s, lo, hi, d: True)
    assert list(np.flatnonzero(lg)) == [8]
    zones = [(2, 8.8, 8.8, 1, 13.0)]                      # touch beyond the 50-bar life is ignored
    l2 = np.full(120, 9.0)
    l2[70] = 8.0
    lg, sh = C.resolve_zones(120, np.full(120, 10.0), l2, zones, lambda s, lo, hi, d: True)
    assert not lg.any()


def test_session_range_break_dst_aware():
    def day(date, tf_min, bar_changes):
        ts = pd.date_range(date, periods=int(24 * 60 / tf_min * 4), freq=f"{tf_min}min", tz="UTC")
        df = pd.DataFrame({"ts": ts, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0})
        for t_utc, vals in bar_changes.items():
            i = int(np.flatnonzero(ts == pd.Timestamp(t_utc, tz="UTC"))[0])
            for k, v in vals.items():
                df.loc[i, k] = v
        return df
    # winter (EST = UTC-5): Asia range = 01:00-05:00 UTC on Jan 12; the first close above it at 03:00 ET = 08:00 UTC
    df = day("2021-01-10", 60, {"2021-01-12T08:00": {"close": 101.0, "high": 101.2}, "2021-01-12T09:00": {"close": 102.0, "high": 102.2}})
    ent = C.entries(df, "1h", None, "ETHUSD")
    hits = [df["ts"][i].strftime("%Y-%m-%dT%H:%M") for i in idx_of(ent["F15_ASIA_BRK"], 0)]
    assert hits == ["2021-01-12T08:00"]
    assert idx_of(ent["F15_ASIA_BRK"], 1) == []
    # summer (EDT = UTC-4): the same ET time is one hour earlier in UTC
    df = day("2021-07-11", 60, {"2021-07-13T07:00": {"close": 101.0, "high": 101.2}})
    ent = C.entries(df, "1h", None, "ETHUSD")
    assert [df["ts"][i].strftime("%H:%M") for i in idx_of(ent["F15_ASIA_BRK"], 0)] == ["07:00"]
    # a close below the Asia low shorts
    df = day("2021-01-10", 60, {"2021-01-12T06:00": {"close": 98.0, "low": 97.8}})
    ent = C.entries(df, "1h", None, "ETHUSD")
    assert [df["ts"][i].strftime("%H:%M") for i in idx_of(ent["F15_ASIA_BRK"], 1)] == ["06:00"]
    # a bar before the window (22:00 ET of the previous day = Asia range itself) never signals; no signal without a full range
    df2 = df.drop(index=int(np.flatnonzero(df["ts"] == pd.Timestamp("2021-01-12T03:00", tz="UTC"))[0])).reset_index(drop=True)
    ent = C.entries(df2, "1h", None, "ETHUSD")
    assert idx_of(ent["F15_ASIA_BRK"], 1) == []            # range bar missing: that day is skipped
    # sweep and reclaim: high above the Asia high but close back inside -> short; low below the Asia low and close back -> long
    df = day("2021-01-10", 60, {"2021-01-12T07:00": {"high": 101.5, "close": 100.2}})
    ent = C.entries(df, "1h", None, "ETHUSD")
    assert [df["ts"][i].strftime("%H:%M") for i in idx_of(ent["F15_ASIA_SWEEP"], 1)] == ["07:00"]
    assert idx_of(ent["F15_ASIA_BRK"], 0) == []
    df = day("2021-01-10", 60, {"2021-01-12T07:00": {"low": 98.5, "close": 99.9}})
    ent = C.entries(df, "1h", None, "ETHUSD")
    assert [df["ts"][i].strftime("%H:%M") for i in idx_of(ent["F15_ASIA_SWEEP"], 0)] == ["07:00"]
    # London range 02:00-05:00 ET = 07:00-10:00 UTC (winter); first close above it at 06:00 ET = 11:00 UTC
    df = day("2021-01-10", 60, {"2021-01-12T08:00": {"high": 100.9}, "2021-01-12T11:00": {"close": 101.0, "high": 101.1}})
    ent = C.entries(df, "1h", None, "ETHUSD")
    assert [df["ts"][i].strftime("%H:%M") for i in idx_of(ent["F15_LON_BRK"], 0)] == ["11:00"]


def test_session_open_bias_reference_and_judging_bars():
    def mk(date, tf_min, ch):
        ts = pd.date_range(date, periods=int(24 * 60 / tf_min * 3), freq=f"{tf_min}min", tz="UTC")
        df = pd.DataFrame({"ts": ts, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0})
        for t_utc, vals in ch.items():
            i = int(np.flatnonzero(ts == pd.Timestamp(t_utc, tz="UTC"))[0])
            for k, v in vals.items():
                df.loc[i, k] = v
        return df
    # winter 2021-01-12: 09:30 ET = 14:30 UTC. 1h: reference = 14:00 UTC bar (09:00 ET), judged on the 15:00 UTC bar
    df = mk("2021-01-11", 60, {"2021-01-12T14:00": {"open": 100.0}, "2021-01-12T15:00": {"close": 100.8}})
    ts = lambda df, ix: [df["ts"][i].strftime("%H:%M") for i in ix]
    assert ts(df, idx_of(C.entries(df, "1h", None, "X")["F15_OPEN0930"], 0)) == ["15:00"]
    # 30m: reference 14:30 bar, judged on the 15:00 bar (closes 15:30 UTC = 10:30 ET)
    df = mk("2021-01-11", 30, {"2021-01-12T14:30": {"open": 100.0}, "2021-01-12T15:00": {"close": 99.2}})
    assert ts(df, idx_of(C.entries(df, "30m", None, "X")["F15_OPEN0930"], 1)) == ["15:00"]
    # 15m: reference 14:30 bar, judged on the 15:15 bar
    df = mk("2021-01-11", 15, {"2021-01-12T14:30": {"open": 100.0}, "2021-01-12T15:15": {"close": 100.4}})
    assert ts(df, idx_of(C.entries(df, "15m", None, "X")["F15_OPEN0930"], 0)) == ["15:15"]
    # summer: the same ET time is 13:30 UTC; judged one hour later
    df = mk("2021-07-12", 15, {"2021-07-13T13:30": {"open": 100.0}, "2021-07-13T14:15": {"close": 100.4}})
    assert ts(df, idx_of(C.entries(df, "15m", None, "X")["F15_OPEN0930"], 0)) == ["14:15"]
    # midnight ET (05:00 UTC winter): 1h judges on the reference bar itself (it closes 60 minutes after midnight)
    df = mk("2021-01-11", 60, {"2021-01-12T05:00": {"open": 100.0, "close": 100.6}})
    assert ts(df, idx_of(C.entries(df, "1h", None, "X")["F15_OPEN0000"], 0)) == ["05:00"]
    df = mk("2021-01-11", 15, {"2021-01-12T05:00": {"open": 100.0}, "2021-01-12T05:45": {"close": 99.4}})
    assert ts(df, idx_of(C.entries(df, "15m", None, "X")["F15_OPEN0000"], 1)) == ["05:45"]
    # not defined on 4h bars
    assert "F15_OPEN0930" not in C.entries(C.synth(1200, "4h", 1), "4h", None, "ETHUSD")


def test_smt_needs_btc_new_extreme_and_coin_failing():
    n = 80
    rows_b = [(100, 100.5, 99.5, 100)] * 30 + [(100, 101.5, 99.8, 101.2)] + [(101, 101.2, 100.6, 101)] * 10
    rows_e = [(100, 100.5, 99.5, 100)] * 30 + [(100, 100.4, 99.8, 100.1)] + [(100, 100.4, 99.6, 100)] * 10
    btc, eth = frame(rows_b, warm=30), frame(rows_e, warm=30)
    ent = C.entries(eth, "1h", {"BTCUSD": btc}, "ETHUSD")
    assert [60 - 30 + i for i in range(0)] == []
    k = 60                                                  # bar index of the BTC breakout (30 warm + 30 flat)
    assert idx_of(ent["F14_SMT"], 1) == [k] and idx_of(ent["F14_SMT"], 0) == []
    # ETH also breaks out: no divergence; BTC itself is never traded
    rows_e2 = list(rows_e)
    rows_e2[30] = (100, 101.6, 99.8, 101.3)
    ent = C.entries(frame(rows_e2, warm=30), "1h", {"BTCUSD": btc}, "ETHUSD")
    assert idx_of(ent["F14_SMT"], 1) == []
    assert not C.entries(btc, "1h", {"BTCUSD": btc}, "BTCUSD")["F14_SMT"][1].any()
    # timestamps must match: shift ETH by one bar and the BTC value is missing
    eth2 = frame(rows_e, start="2021-01-01T00:30:00", warm=30)
    assert not C.entries(eth2, "1h", {"BTCUSD": btc}, "ETHUSD")["F14_SMT"][1].any()


def test_demark_levels_from_previous_utc_day():
    ts = pd.date_range("2021-03-01", periods=48, freq="1h", tz="UTC")
    o = np.full(48, 100.0)
    h = np.full(48, 101.0)
    l = np.full(48, 99.0)
    c = np.full(48, 100.0)
    o[0], c[23], h[5], l[7] = 100.0, 105.0, 110.0, 95.0   # day 1: O=100 H=110 L=95 C=105 (C > O)
    s1, r1 = C.demark_levels(ts.tz_localize(None).to_numpy().astype("datetime64[ns]"), o, h, l, c)
    X = 2 * 110 + 95 + 105
    assert np.isnan(s1[:24]).all() and np.allclose(s1[24:], X / 2 - 110) and np.allclose(r1[24:], X / 2 - 95)
    assert (X / 2 - 110, X / 2 - 95) == (100.0, 115.0)
    # C < O and C == O branches
    c2 = c.copy()
    c2[23] = 98.0
    s1b, r1b = C.demark_levels(ts.tz_localize(None).to_numpy().astype("datetime64[ns]"), o, h, l, c2)
    assert np.isclose(s1b[30], (110 + 2 * 95 + 98) / 2 - 110)
    c3 = c.copy()
    c3[23] = 100.0
    s1c, _ = C.demark_levels(ts.tz_localize(None).to_numpy().astype("datetime64[ns]"), o, h, l, c3)
    assert np.isclose(s1c[30], (110 + 95 + 200) / 2 - 110)
    # a missing day: no levels
    keep = np.r_[np.arange(24), np.arange(30, 48)]
    s1d, _ = C.demark_levels(ts[keep].tz_localize(None).to_numpy().astype("datetime64[ns]"), o[keep], h[keep], l[keep], c[keep])
    assert np.isnan(s1d[24:]).all() or len(s1d) == 42


def test_demark_entry_touch_and_reclaim():
    base = pd.date_range("2021-03-01", periods=72, freq="1h", tz="UTC")
    o = np.full(72, 100.0)
    h = np.full(72, 100.5)
    l = np.full(72, 99.5)
    c = np.full(72, 100.0)
    h[5], l[7], c[23] = 110.0, 95.0, 105.0                # previous day: S1 = 100, R1 = 115
    l[30], c[30] = 99.8, 100.2                            # day 2 bar 6: touches S1 (low <= 100) and closes above -> long
    c[31], l[31] = 99.9, 99.7                             # touches but closes below S1: no signal
    df = pd.DataFrame({"ts": base, "open": o, "high": h, "low": l, "close": c, "volume": 1.0})
    ent = C.entries(df, "1h", None, "ETHUSD")["F2_DEMARK"]
    assert idx_of(ent, 0)[:1] == [30]
    assert 31 not in idx_of(ent, 0)


def test_vwap_cross_and_failed_retest():
    n = 24
    ts = pd.date_range("2021-04-05", periods=n, freq="1h", tz="UTC")
    tsn = ts.tz_localize(None).to_numpy().astype("datetime64[ns]")
    c = np.array([100, 100, 100, 99, 98, 98, 99, 101, 103, 104, 104, 103.5, 103, 102.9, 103.2, 103.1] + [103] * 8, float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.2
    l = np.minimum(o, c) - 0.2
    df = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0})
    vw, day = C.daily_vwap(tsn, h, l, c, np.ones(n))
    tp = (h + l + c) / 3
    assert np.allclose(vw, np.cumsum(tp) / np.arange(1, n + 1))
    assert c[6] <= vw[6] and c[7] > vw[7]
    cross_up = idx_of(C.entries(df, "1h", None, "ETHUSD")["F6_VWAP_CROSS"], 0)
    assert cross_up == [7]
    # VWAP resets at 00:00 UTC: the first bar of day 2 never counts as a cross
    df2 = pd.concat([df, df.assign(ts=df["ts"] + pd.Timedelta(days=1))], ignore_index=True)
    e2 = C.entries(df2, "1h", None, "ETHUSD")["F6_VWAP_CROSS"]
    assert 24 not in idx_of(e2, 0) and 24 not in idx_of(e2, 1)
    # failed retest (short): close crosses below VWAP at bar 7, bar 10 pushes back above VWAP intrabar but closes below it
    c = np.array([100, 100, 100, 100.5, 101, 101, 101, 99, 98.5, 98.4, 98.3, 98.0] + [98] * 12, float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.1
    l = np.minimum(o, c) - 0.1
    h[10] = 100.6                                          # high above VWAP; open 98.4 > close 98.3: a down candle
    o[10] = 98.4
    df = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0})
    vw, _ = C.daily_vwap(tsn, h, l, c, np.ones(n))
    assert c[6] >= vw[6] and c[7] < vw[7] and h[10] >= vw[10] and c[10] < vw[10] and c[10] < o[10]
    e = C.entries(df, "1h", None, "ETHUSD")["F6_VWAP_FAIL"]
    assert idx_of(e, 1) == [10] and idx_of(e, 0) == []
    # the retest bar closing UP through VWAP kills the short (no signal)
    c2 = c.copy()
    c2[10] = 101.0
    o2 = o.copy()
    o2[10] = 98.4
    h2 = np.maximum(o2, c2) + 0.1
    l2 = np.minimum(o2, c2) - 0.1
    df = pd.DataFrame({"ts": ts, "open": o2, "high": h2, "low": l2, "close": c2, "volume": 1.0})
    assert idx_of(C.entries(df, "1h", None, "ETHUSD")["F6_VWAP_FAIL"], 1) == []


def test_range_filter_heikin_and_triple():
    c = np.r_[np.full(300, 100.0), np.linspace(100, 130, 120), np.full(80, 130.0)]
    rf = C.range_filter_dir(c + np.random.default_rng(0).normal(0, 0.05, len(c)))
    assert rf[:300].max() <= 1 and (rf[330:420] == 1).mean() > 0.9
    assert rf.min() >= -1
    # Heikin-Ashi recursion against the textbook definition
    o, h, l, cc = (np.random.default_rng(1).uniform(1, 2, 50) for _ in range(4))
    ha = C.heikin_bull(o, h, l, cc)
    hac = (o + h + l + cc) / 4
    hao = np.zeros(50)
    hao[0] = (o[0] + cc[0]) / 2
    for i in range(1, 50):
        hao[i] = (hao[i - 1] + hac[i - 1]) / 2
    assert np.array_equal(ha == 1.0, hac > hao)
    # the triple definition fires only on the first bar where all three agree
    df = C.synth(6000, "1h", 41)
    ent = C.entries(df, "1h", None, "ETHUSD")
    lg = ent["F7_RF_TRIPLE"][0]
    assert lg.any() and not (lg & np.r_[False, lg[:-1]]).any()


def test_ema_fan_box_and_zscore():
    # EMA ribbon: a steady climb makes 8>13>21>34>55 true from some bar on; the signal is the first such bar only
    c = np.r_[np.full(80, 100.0), 100 + np.arange(1, 121) * 0.5]
    df = frame([(c[i], c[i] + 0.2, c[i] - 0.2, c[i]) for i in range(len(c))], warm=0)
    ent = C.entries(df, "1h", None, "ETHUSD")["F4_FAN"]
    idx = idx_of(ent, 0)
    assert len(idx) == 1 and idx[0] >= 80
    # z-score: first bar with z < -2 only; gate F17_Z_HL needs fast mean reversion (phi <= 0.966)
    rng = np.random.default_rng(5)
    base = 100 + np.cumsum(rng.normal(0, 0.1, 400))
    x = base.copy()
    x[300] -= 6                                             # a sharp one-bar drop
    df = frame([(x[i - 1] if i else x[0], x[i] + 0.1, x[i] - 0.1, x[i]) for i in range(400)], warm=0)
    ent = C.entries(df, "1h", None, "ETHUSD")
    z = (pd.Series(x) - pd.Series(x).rolling(20).mean()) / pd.Series(x).rolling(20).std(ddof=0)
    first = int(np.flatnonzero((z < -2) & (z.shift(1) >= -2))[0])
    assert first in idx_of(ent["F17_Z"], 0)
    assert set(idx_of(ent["F17_Z_HL"], 0)) <= set(idx_of(ent["F17_Z"], 0))
    # range box: a quiet, wide, flat range with ADX < 20: a bullish bar in the bottom 15% buys, one in the top 15% sells
    df = C.synth(12000, "1h", 11)
    ent = C.entries(df, "1h", None, "ETHUSD")
    assert ent["F5_BOX"][0].any() and ent["F5_BOX"][1].any()
    # a trending ADX > 20 market never trades the box; the RSI variant is a subset of the position rule
    d = df
    # signals respect the bottom/top 15% rule
    d = df
    hi48 = d["high"].rolling(48).max().shift(1).to_numpy()
    lo48 = d["low"].rolling(48).min().shift(1).to_numpy()
    pos = (d["close"].to_numpy() - lo48) / (hi48 - lo48)
    assert (pos[ent["F5_BOX"][0]] <= 0.15).all() and (pos[ent["F5_BOX"][1]] >= 0.85).all()
    E = C.env()
    adx = E["fg"].dmi_adx(d, 14, 14)[2].to_numpy(float)
    atr = E["fg"].atr(d, 14).to_numpy(float)
    for side in (0, 1):
        m = ent["F5_BOX"][side]
        assert (adx[m] < 20).all() and ((hi48 - lo48)[m] >= 3 * atr[m]).all()
        assert (ent["F5_BOX_HTF"][side] & ~m).sum() == 0          # the multi-timeframe variant is a subset of the box signal
    rsi = E["pi"].pine_rsi(d["close"].to_numpy(float), 14)
    assert (rsi[ent["F5_BOX_RSI"][0]] < 30).all() and (rsi[ent["F5_BOX_RSI"][1]] > 70).all()


def test_hhhl_and_virgin_wick_and_pd_filter():
    # higher highs and higher lows: the HL pivot confirmation bar is the long signal
    pts = [(0, 100), (10, 110), (20, 104), (30, 114), (40, 108), (50, 118), (60, 112)]
    df = frame(_zigzag(pts), warm=10)
    S = C.structure(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    ent = C.entries(df, "1h", None, "ETHUSD")["F3_HHHL"]
    got = idx_of(ent, 0)
    assert got and all(S["pl_conf"][i] for i in got)       # only on bars where a swing low is confirmed
    assert idx_of(ent, 1) == []
    # virgin wick: a big-body bullish candle, later price comes back to its low and holds it
    rows = [(100, 100.2, 99.9, 100.1)] * 3 + [(100.0, 103.2, 99.9, 103.0)]       # body 3.0 >= 70% of range 3.3 and >= 1.3 ATR
    rows += [(103, 103.5, 102.5, 103.2)] * 6 + [(103.2, 103.4, 99.8, 100.5)] + [(100.5, 101, 100, 100.6)] * 3
    df = frame(rows)
    ent = C.entries(df, "1h", None, "ETHUSD")["F8_VWICK"]
    assert idx_of(ent, 0) == [60 + 3 + 7]                   # first touch: low 99.8 <= wick tip 99.9, close 100.5 above it
    # premium/discount: a long raid is allowed only below the 50% of the last swing range
    S2 = C.structure(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    eq = (S2["hi"] + S2["lo"]) / 2
    pd_ent = C.entries(C.synth(4000, "1h", 9), "1h", None, "ETHUSD")
    d = C.synth(4000, "1h", 9)
    S3 = C.structure(*(d[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    eq3 = (S3["hi"] + S3["lo"]) / 2
    cc = d["close"].to_numpy()
    lgr = pd_ent["F13_RAID_PD"][0]
    assert lgr.any() and (cc[lgr] < eq3[lgr]).all() and (pd_ent["F11_RAID"][0] | ~lgr).all()
    sh = pd_ent["F13_RAID_PD"][1]
    assert (cc[sh] > eq3[sh]).all()


def test_m2022_requires_sweep_displacement_and_fvg():
    d = C.synth(12000, "1h", 14)
    ent = C.entries(d, "1h", None, "ETHUSD")
    m, f = ent["F10_M2022"], ent["F9_FVG"]
    assert m[0].sum() > 0 and m[0].sum() < f[0].sum()      # strictly rarer than the plain FVG retest
    S = C.structure(*(d[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    atr = C.env()["fg"].atr(d, 14).to_numpy(float)
    disp = S["mss_up"] & ((d["close"] - d["open"]).to_numpy() >= 1.2 * atr)
    # every long M2022 signal has a displacement MSS within the 50 + 2 bars before it and a raid before that
    for s in np.flatnonzero(m[0])[:20]:
        lo = max(0, s - EXP_PLUS)
        assert disp[lo:s].any()
        assert S["raid_long"][max(0, lo - 21):s].any()


EXP_PLUS = C.EXP + 2


def test_bos_zone_wait_variant_exact_bar():
    # H1=110 (bar 10), L1=104 (20), H2=114 (30), L2=106 (40), H3=118 (50): the close above H2 is a BOS up (state already +1)
    # and creates a demand zone = the range of the swing-low bar L2. Price falls back into the zone's reach, then a
    # bullish candle closing above the previous high touches the zone: that bar is the long signal (EMA200 needs 200 bars).
    W = 210
    pts = [(0, 100), (10, 110), (20, 104), (30, 114), (40, 106), (50, 118), (56, 106.6)]
    rows = _zigzag(pts)
    rows.append((106.6, 109.0, 105.9, 108.9))
    df = frame(rows, warm=W)
    ent = C.entries(df, "1h", None, "ETHUSD")
    S = C.structure(*(df[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    assert S["bos_up"].sum() == 1
    b = int(np.flatnonzero(S["bos_up"])[0])
    assert np.isclose(S["dem_lo"][b], df["low"][W + 40]) and np.isclose(S["dem_hi"][b], df["high"][W + 40])      # swing-low bar L2
    assert idx_of(ent["F3_BOS_ZONE"], 0) == [len(df) - 1]
    # the same bar without the reversal shape (closes below the previous high) gives nothing
    rows2 = list(rows)
    rows2[-1] = (106.6, 107.0, 105.9, 106.8)
    assert idx_of(C.entries(frame(rows2, warm=W), "1h", None, "ETHUSD")["F3_BOS_ZONE"], 0) == []
    # a close below the zone's low first kills the zone: a later reversal candle gives nothing
    rows3 = list(rows)
    rows3[-2] = (106.6, 106.7, 104.9, 105.0)
    rows3[-1] = (105.0, 109.0, 104.95, 108.9)
    assert idx_of(C.entries(frame(rows3, warm=W), "1h", None, "ETHUSD")["F3_BOS_ZONE"], 0) == []


def test_ema_pullback_touch_and_recover():
    c = 100 + np.arange(260) * 0.3
    pi = C.env()["pi"]
    e50 = pi.pine_ema(c, 50)
    k = 240
    rows = [(c[i - 1] if i else c[0], c[i] + 0.15, c[i] - 0.15, c[i]) for i in range(260)]
    rows[k] = (c[k - 1], c[k] + 0.15, e50[k] - 0.2, c[k])            # dips below EMA50, closes far above it
    df = frame(rows, warm=0)
    e = C.entries(df, "1h", None, "ETHUSD")["F4_PULL"]
    assert idx_of(e, 0) == [k] and idx_of(e, 1) == []


def test_sessions_across_dst_changes_only_fire_in_their_windows():
    for start in ("2021-03-10", "2021-10-31", "2021-11-04"):
        df = C.synth(960, "15m", 7, start=start)
        ent = C.entries(df, "15m", None, "ETHUSD")
        ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
        _day, mins = C.et_wall(ts)
        for side in (0, 1):
            assert ((mins[ent["F15_ASIA_BRK"][side]] < 480)).all()
            assert ((mins[ent["F15_ASIA_SWEEP"][side]] < 480)).all()
            m = mins[ent["F15_LON_BRK"][side]]
            assert ((m >= 300) & (m < 720)).all()
        assert ent["F15_ASIA_BRK"][0].any() or ent["F15_ASIA_BRK"][1].any()


def _utc_day_frame(tf_min, date, changes=None, days=2):
    ts = pd.date_range(date, periods=int(24 * 60 / tf_min * days), freq=f"{tf_min}min", tz="UTC")
    df = pd.DataFrame({"ts": ts, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0})
    for t_utc, vals in (changes or {}).items():
        i = int(np.flatnonzero(ts == pd.Timestamp(t_utc, tz="UTC"))[0])
        for k, v in vals.items():
            df.loc[i, k] = v
    return df


def _hhmm(df, ix):
    return [df["ts"][i].strftime("%d %H:%M") for i in ix]


def _none(df, tf, name):
    e = C.entries(df, tf, None, "ETHUSD")[name]
    return not e[0].any() and not e[1].any()


def test_power_of_3_sweep_then_back_inside():
    # accumulation range 00:00-08:00 UTC = [99.5, 100.5]; the sweep bar must start in 08:00-20:00 UTC
    # 1h: bar 09:00 spikes above the range high and closes back inside -> short on that bar
    df = _utc_day_frame(60, "2021-05-10", {"2021-05-10T09:00": {"high": 101.2, "close": 100.2}})
    e = C.entries(df, "1h", None, "ETHUSD")["F11_PO3"]
    assert _hhmm(df, idx_of(e, 1)) == ["10 09:00"] and idx_of(e, 0) == []
    # the sweep bar closes outside, the next bar closes back inside: the signal is on the later bar
    df = _utc_day_frame(60, "2021-05-10", {"2021-05-10T09:00": {"high": 101.2, "close": 100.9},
                                           "2021-05-10T10:00": {"high": 101.0, "close": 100.3}})
    e = C.entries(df, "1h", None, "ETHUSD")["F11_PO3"]
    assert _hhmm(df, idx_of(e, 1)) == ["10 10:00"]
    # the price stays outside the range for the rest of the day: no close back inside, no signal
    ch = {f"2021-05-10T{hh:02d}:00": {"high": 101.2, "close": 100.9} for hh in range(9, 24)}
    assert _none(_utc_day_frame(60, "2021-05-10", ch), "1h", "F11_PO3")
    # a return on the third bar after the first sweep bar (12:00) is still in time
    ch = {f"2021-05-10T{hh}:00": {"high": 101.2, "close": 100.9} for hh in (9, 10, 11)}
    ch["2021-05-10T12:00"] = {"high": 100.4, "close": 100.1}
    df = _utc_day_frame(60, "2021-05-10", ch)
    assert _hhmm(df, idx_of(C.entries(df, "1h", None, "ETHUSD")["F11_PO3"], 1)) == ["10 12:00"]
    # long mirror: sweep of the range low
    df = _utc_day_frame(60, "2021-05-10", {"2021-05-10T14:00": {"low": 98.8, "close": 99.9}})
    e = C.entries(df, "1h", None, "ETHUSD")["F11_PO3"]
    assert _hhmm(df, idx_of(e, 0)) == ["10 14:00"] and idx_of(e, 1) == []
    # a spike inside the accumulation window (before 08:00) or at/after 20:00 is not a manipulation
    assert _none(_utc_day_frame(60, "2021-05-10", {"2021-05-10T06:00": {"high": 101.2, "close": 100.2}}), "1h", "F11_PO3")
    assert _none(_utc_day_frame(60, "2021-05-10", {"2021-05-10T20:00": {"high": 101.2, "close": 100.2}}), "1h", "F11_PO3")
    # a bar that pierces both sides is ignored; a day with a missing accumulation bar is skipped
    assert _none(_utc_day_frame(60, "2021-05-10", {"2021-05-10T09:00": {"high": 101.2, "low": 98.8, "close": 100.2}}), "1h", "F11_PO3")
    df = _utc_day_frame(60, "2021-05-10", {"2021-05-10T09:00": {"high": 101.2, "close": 100.2}}).drop(index=3).reset_index(drop=True)
    assert _none(df, "1h", "F11_PO3")
    # only the earliest event of the day: the later low sweep is not traded
    df = _utc_day_frame(60, "2021-05-10", {"2021-05-10T09:00": {"high": 101.2, "close": 100.2},
                                           "2021-05-10T15:00": {"low": 98.8, "close": 99.9}})
    e = C.entries(df, "1h", None, "ETHUSD")["F11_PO3"]
    assert _hhmm(df, idx_of(e, 1)) == ["10 09:00"] and idx_of(e, 0) == []
    # 15m: accumulation = 32 bars; 4h: accumulation = two bars, sweep candidates are the 08:00, 12:00, 16:00 bars
    df = _utc_day_frame(15, "2021-05-10", {"2021-05-10T10:15": {"high": 101.2, "close": 100.4}})
    assert _hhmm(df, idx_of(C.entries(df, "15m", None, "ETHUSD")["F11_PO3"], 1)) == ["10 10:15"]
    df = _utc_day_frame(30, "2021-05-10", {"2021-05-10T10:30": {"low": 98.9, "close": 99.8}})
    assert _hhmm(df, idx_of(C.entries(df, "30m", None, "ETHUSD")["F11_PO3"], 0)) == ["10 10:30"]
    df = _utc_day_frame(240, "2021-05-10", {"2021-05-10T08:00": {"high": 101.2, "close": 100.2}}, days=3)
    assert _hhmm(df, idx_of(C.entries(df, "4h", None, "ETHUSD")["F11_PO3"], 1)) == ["10 08:00"]
    assert _none(_utc_day_frame(240, "2021-05-10", {"2021-05-10T04:00": {"high": 101.2, "close": 100.2}}, days=3), "4h", "F11_PO3")


def test_opening_range_breakout_first_bars_of_utc_day():
    # N = 2: the range is the first two bars of the UTC day (00:00 and 00:00 + bar length): [99.2, 100.8]
    base = {"2021-05-10T00:00": {"high": 100.8, "low": 99.6}, "2021-05-10T01:00": {"high": 100.4, "low": 99.2}}
    df = _utc_day_frame(60, "2021-05-10", {**base, "2021-05-10T05:00": {"close": 101.0, "high": 101.1},
                                          "2021-05-10T06:00": {"close": 102.0, "high": 102.1}})
    e = C.entries(df, "1h", None, "ETHUSD")["F15_ORB"]
    assert _hhmm(df, idx_of(e, 0)) == ["10 05:00"] and idx_of(e, 1) == []             # first close above 100.8 only
    df = _utc_day_frame(60, "2021-05-10", {**base, "2021-05-10T03:00": {"close": 98.9, "low": 98.8}})
    e = C.entries(df, "1h", None, "ETHUSD")["F15_ORB"]
    assert _hhmm(df, idx_of(e, 1)) == ["10 03:00"] and idx_of(e, 0) == []
    # wicks do not count, closes inside the range do not count, the range bars themselves never trigger
    assert _none(_utc_day_frame(60, "2021-05-10", {**base, "2021-05-10T04:00": {"high": 105.0, "close": 100.7}}), "1h", "F15_ORB")
    assert idx_of(C.entries(_utc_day_frame(60, "2021-05-10", {"2021-05-10T01:00": {"close": 103.0, "high": 103.1}}),
                            "1h", None, "ETHUSD")["F15_ORB"], 0) == []
    # a new UTC day starts a new range
    df = _utc_day_frame(60, "2021-05-10", {**base, "2021-05-10T05:00": {"close": 101.0, "high": 101.1},
                                          "2021-05-11T04:00": {"close": 98.0, "low": 97.9}})
    e = C.entries(df, "1h", None, "ETHUSD")["F15_ORB"]
    assert _hhmm(df, idx_of(e, 0)) == ["10 05:00"] and _hhmm(df, idx_of(e, 1)) == ["11 04:00"]
    # a day whose opening bars are not both there is skipped
    df = _utc_day_frame(60, "2021-05-10", {"2021-05-10T05:00": {"close": 101.0, "high": 101.1}}).drop(index=1).reset_index(drop=True)
    assert _none(df, "1h", "F15_ORB")
    # 15m: the range is the first 30 minutes; 30m: the first hour; 4h: the first 8 hours (signal from the 08:00 bar on)
    df = _utc_day_frame(15, "2021-05-10", {"2021-05-10T00:15": {"high": 100.7}, "2021-05-10T00:30": {"close": 100.9, "high": 101.0}})
    assert _hhmm(df, idx_of(C.entries(df, "15m", None, "ETHUSD")["F15_ORB"], 0)) == ["10 00:30"]
    df = _utc_day_frame(30, "2021-05-10", {"2021-05-10T01:00": {"close": 100.9, "high": 101.0}})
    assert _hhmm(df, idx_of(C.entries(df, "30m", None, "ETHUSD")["F15_ORB"], 0)) == ["10 01:00"]
    df = _utc_day_frame(240, "2021-05-10", {"2021-05-10T12:00": {"close": 100.9, "high": 101.0}}, days=3)
    assert _hhmm(df, idx_of(C.entries(df, "4h", None, "ETHUSD")["F15_ORB"], 0)) == ["10 12:00"]
    assert _none(_utc_day_frame(240, "2021-05-10", {"2021-05-10T04:00": {"close": 100.9, "high": 101.0}}, days=3), "4h", "F15_ORB")
