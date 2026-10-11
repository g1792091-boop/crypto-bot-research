"""research/newinfo (PREREG_NEWINFO.md) on synthetic data only.

- no look-ahead: cutting every input at a time X leaves every signal of a bar closing at or before X unchanged, for
  every rule, timeframe and combination (PREREG 10 test 1);
- timing: a metrics row is never used before its stamp + 5 minutes (nor after 30 minutes), a settlement never before its
  floored calc time, a higher-timeframe bar never before its close (test 2);
- every grid has exactly the size of section 3 (test 3);
- each idea's signal on a hand-made series;
- on synthetic outcome tables: the plateau with section 4's neighbours, the coin-flip (and its seeding) and same-side
  means and the BH family equal a direct computation (test 4);
- the data parsers (metrics, funding, cache) and the whole pipeline grid -> select -> confirm -> report on synthetic
  1m bars of the six coins.
No real market data is read anywhere here.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import itertools
import os
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_577_836_800_000            # 2020-01-01 00:00 UTC
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def RN():
    pytest.importorskip("numba")
    return _load("newinfo_run", os.path.join(ROOT, "research", "newinfo", "run.py"))


@pytest.fixture(scope="module")
def D():
    return _load("newinfo_defs", os.path.join(ROOT, "research", "newinfo", "defs.py"))


@pytest.fixture(scope="module")
def NI():
    return _load("newinfo_data", os.path.join(ROOT, "research", "newinfo", "data.py"))


# ------------------------------------------------------------------ helpers
def coin(D, tf, c, o=None, v=None, sym="BTCUSDT", start=T0, **kw):
    """A coin from hand-made closes: open = previous close unless given, high / low 0.1% around."""
    c = np.asarray(c, float)
    o = np.r_[c[0], c[:-1]] if o is None else np.asarray(o, float)
    h = np.maximum(o, c) * 1.001
    lo = np.minimum(o, c) * 0.999
    v = np.ones(len(c)) if v is None else np.asarray(v, float)
    open_ms = start + np.arange(len(c), dtype=np.int64) * D.TF_MS[tf]
    return D.Coin(sym, tf, open_ms, o, h, lo, c, v, **kw)


def bar_metrics(cn, col, vals):
    """One metrics row per bar, stamped 5 minutes before the bar's close (usable at that close)."""
    t = cn.close_ms - 5 * MIN
    other = "oi" if col == "ls" else "ls"
    return {"t": t, col: np.asarray(vals, float), other: np.full(len(t), np.nan)}


def funding_dict(NI, calc_ms, rate, hours=8.0):
    x = pd.DataFrame({"calc_time": np.asarray(calc_ms, np.int64), "funding_interval_hours": hours,
                      "last_funding_rate": np.asarray(rate, float)})
    return NI.parse_funding(x)


# ------------------------------------------------------------------ test 3: grids
def test_grid_sizes_order_and_neighbours(D):
    assert sum(len(D.grid(r)) for r in D.ORDER) == 153
    assert sum(len(D.grid(r)) * len(D.RULES[r]["tfs"]) for r in D.ORDER) * 6 == 1836
    assert sum(len(D.RULES[r]["tfs"]) for r in D.ORDER) == 14
    for r in D.ORDER:
        g = D.grid(r)
        assert len(g) == D.GRID_SIZE[r]
        ps = D.RULES[r]["params"]
        assert g == [dict(zip([p[0] for p in ps], v)) for v in itertools.product(*[p[1] for p in ps])]
        for p in ps:                                         # values ascending, off before on
            assert list(p[1]) == sorted(p[1]) and p[2] in p[1]
        nb = D.neighbours(r)
        for i, row in enumerate(g):
            for j in nb[i]:
                diff = [k for k in row if row[k] != g[j][k]]
                assert len(diff) == 1
                vals = dict((p[0], p[1]) for p in ps)[diff[0]]
                assert abs(vals.index(row[diff[0]]) - vals.index(g[j][diff[0]])) == 1
        assert sum(len(x) for x in nb) == sum(2 * (len(p[1]) - 1) * len(g) // len(p[1]) for p in ps)
    assert D.RULES["D10_VWAP_REVERT"]["tfs"] == ("30m", "1h")
    assert all(D.RULES[r]["tfs"] == ("1h", "4h") for r in D.ORDER if r != "D10_VWAP_REVERT")


def test_section4_exits_and_neighbours(RN):
    assert RN.SEC4 == ("ladder|2", "tp2R|2", "tp3R|1.5", "tp3R|2", "tp3R|3", "tp3R|4")
    assert [RN.K.EXITS[i][0] for i in RN.EXIT_GLOBAL] == list(RN.SEC4)
    names = list(RN.SEC4)
    for e, nb in enumerate(RN.SEC4_NB):
        rule, k = names[e].split("|")
        same = sorted(float(n.split("|")[1]) for n in names if n.startswith(rule + "|"))
        i = same.index(float(k))
        want = {f"{rule}|{same[i + d]:g}" for d in (-1, 1) if 0 <= i + d < len(same)} if rule == "tp3R" else set()
        assert {names[f] for f in nb} == want                     # tp3R|2's wider neighbour is tp3R|3, not 2.5


# ------------------------------------------------------------------ building blocks
def test_trailing_rank_matches_the_definition(D):
    rng = np.random.default_rng(1)
    x = rng.integers(0, 6, 400).astype(float)                  # many ties
    x[rng.random(400) < 0.08] = np.nan
    n = 50
    got = D.trailing_rank(x, n)
    for i in range(len(x)):
        w = x[max(0, i - n + 1):i + 1]
        w = w[np.isfinite(w)]
        if not np.isfinite(x[i]) or len(w) < 45:
            assert np.isnan(got[i])
            continue
        a, e = (w < x[i]).sum(), (w == x[i]).sum()
        assert got[i] == pytest.approx((a + (e + 1) / 2) / len(w), abs=1e-12)


def test_trailing_z_uses_the_rows_before(D):
    rng = np.random.default_rng(2)
    x = rng.normal(size=300)
    x[rng.random(300) < 0.05] = np.nan
    n = 40
    z = D.trailing_z(x, n)
    for i in range(len(x)):
        w = x[max(0, i - n):i]
        w = w[np.isfinite(w)]
        if i < n or len(w) < 36 or not np.isfinite(x[i]):
            assert not np.isfinite(z[i]) or len(w) >= 36
            continue
        assert z[i] == pytest.approx((x[i] - w.mean()) / w.std(ddof=1), rel=1e-9)
    assert D.need(336) == 303 and D.need(720) == 648 and D.need(84) == 76


def test_first_in_episode(D):
    cond = np.array([0, 1, 1, 1, 0, 1, 1, 0, 1], bool)
    assert np.flatnonzero(D.first_in_episode(cond)).tolist() == [1, 5, 8]
    qual = np.array([0, 0, 1, 1, 0, 0, 0, 1, 1], bool)
    assert np.flatnonzero(D.first_in_episode(cond, qual)).tolist() == [2, 8]   # episode 5-6 never qualifies


def test_bars_equal_the_full_grid_frames(tmp_path, D):
    R = _load("fullgrid_run", os.path.join(ROOT, "research", "fullgrid", "run.py"))
    rng = np.random.default_rng(3)
    n = 3 * 1440 + 77
    ts = T0 + 13 * MIN + np.arange(n, dtype=np.int64) * MIN            # starts mid-bar, ends mid-bar
    ts = np.delete(ts, rng.choice(n, 300, replace=False))              # holes
    c = 100 * np.exp(np.cumsum(rng.normal(0, 1e-3, len(ts))))
    o = np.r_[c[0], c[:-1]]
    h, lo, v = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999, rng.uniform(1, 2, len(ts))
    os.makedirs(tmp_path / "1m")
    np.savez(tmp_path / "1m" / "BTCUSDT.npz", ts=ts, o=o, h=h, l=lo, c=c, v=v, mo=o, mh=h, ml=lo, mc=c,
             fund=np.zeros(len(ts)))
    for tf in ("30m", "1h", "4h"):
        df, close = R.build_frame(str(tmp_path), "BTCUSDT", tf)
        b = D.bars(ts, o, h, lo, c, v, D.TF_MS[tf])
        assert np.array_equal(df["ts"].astype("int64").to_numpy() // 1_000_000, b["open_ms"])
        assert np.array_equal(close, b["open_ms"] + D.TF_MS[tf])
        for k, col in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
            assert np.array_equal(df[col].to_numpy(float), b[k])


# ------------------------------------------------------------------ test 2: timing
def test_metric_row_used_from_stamp_plus_5_until_30_minutes(D):
    t = np.array([T0, T0 + 5 * MIN, T0 + 60 * MIN], np.int64)
    v = np.array([1.0, np.nan, 3.0])
    at = np.array([T0 + 4 * MIN, T0 + 5 * MIN, T0 + 9 * MIN, T0 + 10 * MIN, T0 + 35 * MIN, T0 + 36 * MIN,
                   T0 + 64 * MIN, T0 + 65 * MIN], np.int64)
    got = D.metric_asof(t, v, at)
    # 4 min: nothing yet; 5 min: row 0; 9 min: row 0 (row 1 not yet usable); 10 min: row 1, its value missing;
    # 35 min: row 1 (missing); 36 min: row 1 is 31 minutes old -> missing; 64: row 1 stale; 65: row 2
    want = [np.nan, 1.0, 1.0, np.nan, np.nan, np.nan, np.nan, 3.0]
    assert np.array_equal(got, np.array(want), equal_nan=True)
    t2 = np.array([T0], np.int64)
    got = D.metric_asof(t2, np.array([7.0]), np.array([T0 + 30 * MIN, T0 + 31 * MIN]))
    assert got[0] == 7.0 and np.isnan(got[1])          # exactly 30 minutes old: kept; 31: missing


def test_h3a_ignores_a_row_stamped_at_the_bar_close(D):
    n = 200
    cn = coin(D, "4h", np.full(n, 100.0))
    ls = np.ones(n)
    m = bar_metrics(cn, "ls", ls)
    # a spike row stamped exactly at bar 150's close: bar 150 cannot use it, bar 151 can
    m = {"t": np.r_[m["t"], cn.close_ms[150]], "ls": np.r_[m["ls"], 9.0], "oi": np.r_[m["oi"], np.nan]}
    o = np.argsort(m["t"], kind="stable")
    cn.metrics = {k: v[o] for k, v in m.items()}
    lo, sh = D.h3a(cn, 0.05, 14, False)
    assert not sh[150] and not sh[151]                 # bar 151 sees its own row (stamped at close - 5 min)
    # the same spike stamped 5 minutes before bar 150's close is bar 150's value
    ls2 = ls.copy()
    ls2[150] = 9.0
    cn2 = coin(D, "4h", np.full(n, 100.0))
    cn2.metrics = bar_metrics(cn2, "ls", ls2)
    lo2, sh2 = D.h3a(cn2, 0.05, 14, False)
    assert sh2[150] and not sh2[151]


def test_settlement_used_from_its_floored_calc_time(D, NI):
    n = 24 * 60
    cn = coin(D, "1h", np.full(n, 100.0))
    k = np.arange(3 * 60)
    calc = T0 + k * 8 * HOUR + 400                     # 0.4 s after the minute: floored onto the bar close
    rate = np.full(len(k), 0.0001)
    rate[150] = 0.003
    cn.funding = funding_dict(NI, calc, rate)
    lo, sh = D.d04(cn, 0.05, 45, False)
    j = 150 * 8 - 1                                    # the bar closing at T0 + 1200 h
    assert cn.close_ms[j] == T0 + 150 * 8 * HOUR
    assert np.flatnonzero(sh).tolist() == [j] and not lo.any()
    calc2 = calc.copy()
    calc2[150] += MIN                                  # one minute later: the next bar closing at or after it
    cn2 = coin(D, "1h", np.full(n, 100.0))
    cn2.funding = funding_dict(NI, calc2, rate)
    assert np.flatnonzero(D.d04(cn2, 0.05, 45, False)[1]).tolist() == [j + 1]


def test_higher_timeframe_bar_only_after_its_close(D):
    n4 = 160
    hc = np.full(n4, 100.0)
    hc[150:] = 200.0
    h_close = T0 + (np.arange(n4) + 1) * 4 * HOUR
    cn = coin(D, "1h", np.full(n4 * 4, 100.0), htf={"close_ms": h_close, "c": hc})
    up, dn = D._htf_trend(cn, 100)
    i_at = int(np.flatnonzero(cn.close_ms == h_close[150])[0])
    assert not up[i_at - 1] and up[i_at]               # the 1h bar closing at the 4h close sees it, not before
    assert not dn.any()


# ------------------------------------------------------------------ hand-made series per idea
def test_h3a_crowd_fade_hand_made(D):
    n = 400
    o = np.full(n, 100.0)
    c = np.full(n, 100.0)
    ls = np.ones(n)
    ls[200:203] = 5.0                                  # crowd long extreme: ranks 1.0, 0.994, 0.988
    ls[300] = 0.1                                      # crowd short extreme
    c[200], c[201], c[202] = 101, 101, 99              # green, green, red
    o[302] = 99                                        # bar 302 green (for the confirm long)
    cn = coin(D, "4h", c, o=o)
    cn.metrics = bar_metrics(cn, "ls", ls)
    lo, sh = D.h3a(cn, 0.05, 14, False)
    assert np.flatnonzero(sh).tolist() == [200]        # once per episode
    assert np.flatnonzero(lo).tolist() == [300]
    lo, sh = D.h3a(cn, 0.05, 14, True)
    assert np.flatnonzero(sh).tolist() == [202]        # first red bar of the episode
    assert not lo.any()                                 # the long episode (bar 300 alone) has no green bar
    ls2 = ls.copy()
    ls2[201] = np.nan                                  # a missing value ends the episode
    cn2 = coin(D, "4h", c, o=o)
    cn2.metrics = bar_metrics(cn2, "ls", ls2)
    assert np.flatnonzero(D.h3a(cn2, 0.05, 14, False)[1]).tolist() == [200, 202]
    ls3 = np.ones(n)
    ls3[50] = 5.0                                      # before 76 present samples: no rank
    cn3 = coin(D, "4h", c, o=o)
    cn3.metrics = bar_metrics(cn3, "ls", ls3)
    assert not D.h3a(cn3, 0.05, 14, False)[1].any()


def test_d04_funding_fade_hand_made(D, NI):
    n = 24 * 120
    o = np.full(n, 100.0)
    c = np.full(n, 100.0)
    k = np.arange(3 * 120)
    calc = T0 + k * 8 * HOUR + 3
    rate = np.full(len(k), 0.0001)
    rate[200], rate[250] = 0.002, -0.002
    j_hi, j_lo = 200 * 8 - 1, 250 * 8 - 1
    c[j_hi + 1] = 99                                   # the bar after the high settlement is red
    c[j_lo + 1] = 99                                   # the bar after the low settlement is red too (long fails)
    cn = coin(D, "1h", c, o=o)
    cn.funding = funding_dict(NI, calc, rate)
    lo, sh = D.d04(cn, 0.05, 45, False)
    assert np.flatnonzero(sh).tolist() == [j_hi] and np.flatnonzero(lo).tolist() == [j_lo]
    lo, sh = D.d04(cn, 0.05, 45, True)
    assert np.flatnonzero(sh).tolist() == [j_hi + 1] and not lo.any()
    rate_early = rate.copy()
    rate_early[100] = 0.002                            # day 33: fewer than 2.7 x 45 settlements in its window
    cn.funding = funding_dict(NI, calc, rate_early)
    cn.memo.clear()
    assert 100 * 8 - 1 not in np.flatnonzero(D.d04(cn, 0.05, 45, False)[1]).tolist()
    # extreme rank but not beyond the neutral rate: no signal
    rate_n = np.full(len(k), 0.00005)
    rate_n[200] = 0.00008
    cn.funding = funding_dict(NI, calc, rate_n)
    cn.memo.clear()
    assert not D.d04(cn, 0.05, 45, False)[1].any()
    # a 2-hour interval: 0.0005 per 2 hours is 0.002 per 8 hours
    f = funding_dict(NI, [T0], [0.0005], hours=2.0)
    assert f["f8"][0] == pytest.approx(0.002)


def test_d04_two_settlements_on_one_bar_the_later_decides(D, NI):
    n = 6 * 120
    calc = list(T0 + np.arange(3 * 100) * 8 * HOUR)
    base = [0.0001] * len(calc)
    s0 = T0 + 100 * DAY                                 # a 4h bar opening at s0 closes at s0 + 4h
    for extra, want in (([(1, 0.003), (3, 0.0001)], False), ([(1, 0.0001), (3, 0.003)], True)):
        cc = calc + [s0 + h * HOUR + 5 for h, _r in extra]
        rr = base + [r for _h, r in extra]
        o = np.argsort(cc)
        cn = coin(D, "4h", np.full(n, 100.0))
        cn.funding = funding_dict(NI, np.array(cc)[o], np.array(rr)[o])
        sh = D.d04(cn, 0.05, 45, False)[1]
        j = int(np.flatnonzero(cn.close_ms == s0 + 4 * HOUR)[0])
        assert bool(sh[j]) is want


def test_d05_funding_trend_hand_made(D, NI):
    n = 700
    base = 100 * np.exp(0.001 * np.arange(n))
    c = base.copy()
    c[600:603] = base[599] * 0.97                      # pullback below EMA20, then back above at 603
    cn_kw = {}
    h_close = T0 + (np.arange(n // 4) * 4 + 4) * HOUR
    cn_kw["htf"] = {"close_ms": h_close, "c": c[3::4][:n // 4]}
    k = np.arange(-100 * 3, n // 8 + 1)
    calc = T0 + k * 8 * HOUR + 1
    rng = np.random.default_rng(5)
    rate = rng.uniform(0, 0.0002, len(k))
    last = int(np.searchsorted(calc // MIN * MIN, T0 + 604 * HOUR, side="right") - 1)   # latest seen at bar 603
    for f_last, want in ((0.0, [603]), (0.001, [])):
        r2 = rate.copy()
        r2[last] = f_last
        cn = coin(D, "1h", c, **cn_kw)
        cn.funding = funding_dict(NI, calc, r2)
        lo, sh = D.d05(cn, 100, 20, 50)
        assert np.flatnonzero(lo).tolist() == want and not sh.any()
    # the percentile window needs 243 settlements: with funding from day -10 only, no signal
    keep = calc >= T0 - 10 * DAY
    cn = coin(D, "1h", c, **cn_kw)
    cn.funding = funding_dict(NI, calc[keep], np.where(np.arange(len(k)) == last, 0.0, rate)[keep])
    assert not D.d05(cn, 100, 20, 50)[0].any()


def test_d06_oi_divergence_hand_made(D):
    n = 600
    c = 100 + 0.1 * np.where(np.arange(n) % 2 == 0, 1, -1)
    c[550] = 101.0                                      # new 12-bar high
    cn = coin(D, "1h", c)
    t = np.arange(T0 - DAY, cn.close_ms[-1], 5 * MIN, dtype=np.int64)
    oi = 1e5 * (1 + 0.01 * np.sin((t - T0) / (5 * HOUR)))
    drop = (t > cn.close_ms[539]) & (t <= cn.close_ms[550])
    oi = np.where(drop, oi * (1 - 0.2 * (t - cn.close_ms[539]) / (cn.close_ms[550] - cn.close_ms[539])), oi)
    oi = np.where(t > cn.close_ms[550], oi * 0.8, oi)
    cn.metrics = {"t": t, "oi": oi, "ls": np.full(len(t), np.nan)}
    lo, sh = D.d06(cn, 12, 1.0, 15)
    assert np.flatnonzero(sh).tolist() == [550] and not lo.any()
    c2 = c.copy()
    c2[550] = 98.0                                      # new 12-bar low instead: long
    cn2 = coin(D, "1h", c2)
    cn2.metrics = cn.metrics
    lo2, sh2 = D.d06(cn2, 12, 1.0, 15)
    assert np.flatnonzero(lo2).tolist() == [550] and not sh2.any()


def test_d08_cross_coin_hand_made(D):
    def market(g, starts=None, n=600):
        cs = []
        for j, sym in enumerate(SYMS):
            s = 0 if starts is None else starts[j]
            i = np.arange(s, n)
            cs.append(coin(D, "1h", 100 * np.exp(g[j] * i), sym=sym, start=T0 + s * HOUR))
        return D.Market("1h", cs)
    m = market([0.001, 0.002, -0.001, 0.003, 0.0, -0.002])
    out = D.d08(m, 12, 3, False)
    times = m.coins["BTCUSDT"].close_ms
    want = np.flatnonzero((np.arange(600) >= 300) & ((times // HOUR) % 3 == 0))
    assert np.array_equal(np.flatnonzero(out["DOGEUSDT"][0]), want)
    assert np.array_equal(np.flatnonzero(out["BCHUSDT"][1]), want)
    assert sum(out[s][0].sum() + out[s][1].sum() for s in SYMS) == 2 * len(want)
    m = market([0.001, 0.002, 0.0005, 0.003, 0.0015, 0.0001])
    out = D.d08(m, 12, 3, True)                         # the weakest still rose: no short with abs_filter
    assert out["DOGEUSDT"][0].sum() == len(want) and not any(out[s][1].any() for s in SYMS)
    m = market([0.001, 0.003, -0.001, 0.003, 0.0, -0.002])
    out = D.d08(m, 12, 3, False)                        # tie for the strongest: ETH before DOGE
    assert out["ETHUSDT"][0].sum() == len(want) and not out["DOGEUSDT"][0].any()
    m = market([0.001, 0.002, -0.001, 0.003, 0.0, -0.002], starts=[0, 0, 200, 200, 200, 0])
    out = D.d08(m, 12, 3, False)                        # SOL, DOGE, LTC past warm-up from bar 500 only
    first = min(int(m.coins[s].close_ms[np.flatnonzero(out[s][0] | out[s][1])[0]]) for s in SYMS
                if (out[s][0] | out[s][1]).any())
    assert first >= T0 + 501 * HOUR


def _minutes_from_bars(po, pc, step_min, wick=0.05):
    rows = []
    for b, (a, z) in enumerate(zip(po, pc)):
        path = np.linspace(a, z, step_min + 1)
        for k in range(step_min):
            rows.append((T0 + (b * step_min + k) * MIN, path[k], max(path[k], path[k + 1]) + wick,
                         min(path[k], path[k + 1]) - wick, path[k + 1]))
    x = np.array(rows)
    return {"ts": x[:, 0].astype(np.int64), "o": x[:, 1], "h": x[:, 2], "l": x[:, 3], "c": x[:, 4],
            "v": np.ones(len(x))}


def test_d10_vwap_revert_hand_made(D):
    nb = 3 * 48
    po, pc = np.full(nb, 100.0), np.full(nb, 100.0)
    k = 48 + 6                                          # day 2, the bar 03:00-03:30: a drop
    po[k], pc[k] = 100.0, 98.0
    po[k + 1], pc[k + 1] = 98.0, 98.5                   # 03:30-04:00: green, still below the VWAP
    po[k + 2:], pc[k + 2:] = 98.5, 98.5
    m = _minutes_from_bars(po, pc, 30)
    b = D.bars(m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], D.TF_MS["30m"])
    mk = lambda: D.Coin("BTCUSDT", "30m", b["open_ms"], b["o"], b["h"], b["l"], b["c"], b["v"], minutes=m)  # noqa: E731
    cn = mk()
    vw = cn.vwap()
    want = np.average((m["h"] + m["l"] + m["c"])[48 * 30:(k + 2) * 30] / 3)       # day 2 minutes before 04:00
    assert vw[k + 1] == pytest.approx(want)
    assert np.flatnonzero(D.d10(cn, 1.5, 2, 1)[0]).tolist() == [k + 1]
    assert not D.d10(mk(), 1.5, 4, 1)[0].any()            # closes exactly 4 h after the day's start: never signals
    assert not D.d10(mk(), 1.5, 2, 1)[1].any()


def test_d01_vol_spike_hand_made(D):
    n = 300
    c = 100 * np.exp(0.001 * np.arange(n))
    o = np.r_[c[0], c[:-1]]
    v = np.full(n, 10.0)
    v[100] = 35.0                                       # green (rising), > 3 x 10
    v[150] = 25.0
    o[150] = c[150] * 1.01                              # red, > 2 x but not 3 x
    v[250] = 50.0
    o[250] = c[250] * 1.01                              # red above EMA200
    cn = coin(D, "1h", c, o=o, v=v)
    lo, sh = D.d01(cn, 3.0, 10, False)
    assert np.flatnonzero(lo).tolist() == [100] and np.flatnonzero(sh).tolist() == [250]
    lo, sh = D.d01(cn, 2.0, 10, False)
    assert np.flatnonzero(sh).tolist() == [150, 250]
    lo, sh = D.d01(cn, 3.0, 10, True)
    assert not sh.any()                                 # the short is above EMA200
    assert np.flatnonzero(lo).tolist() == []            # bar 100 has no EMA200 yet


# ------------------------------------------------------------------ test 1: no look-ahead
class World:
    """Synthetic six-coin world: 1m bars with trending stretches and volume bursts, 5-minute metrics with a hole,
    stale stretches and missing values, 8-hourly settlements (2-hourly for SOL for 10 days)."""

    def __init__(self, NI, days=330, seed=7):
        rng = np.random.default_rng(seed)
        n = days * 1440
        ts = T0 + np.arange(n, dtype=np.int64) * MIN
        self.min, self.met, self.fund = {}, {}, {}
        for j, sym in enumerate(SYMS):
            drift = np.repeat(rng.normal(0, 4e-5, days // 10 + 1), 14400)[:n]
            r = drift + rng.normal(0, 6e-4, n)
            c = 100 * (j + 1) * np.exp(np.cumsum(r))
            o = np.r_[c[0], c[:-1]]
            h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 3e-4, n)))
            lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 3e-4, n)))
            v = rng.lognormal(0, 0.5, n) * np.where(rng.random(n) < 2e-4, 40.0, 1.0)
            v *= np.repeat(np.where(rng.random(n // 60 + 1) < 0.02, 4.0, 1.0), 60)[:n]      # busy hours
            v *= np.repeat(np.where(rng.random(n // 240 + 1) < 0.02, 5.0, 1.0), 240)[:n]    # busy 4-hour blocks
            self.min[sym] = {"ts": ts, "o": o, "h": h, "l": lo, "c": c, "v": v}
            t = np.arange(T0 - 2 * DAY, T0 + days * DAY, 5 * MIN, dtype=np.int64)
            ls = np.exp(np.cumsum(rng.normal(0, 0.02, len(t))) * 0.3) * 1.5
            oi = 1e5 * np.exp(np.cumsum(rng.normal(0, 0.002, len(t))))
            ls[(t > T0 + 40 * DAY) & (t < T0 + 42 * DAY)] = np.nan          # a hole of one column
            keep = ~((t > T0 + 90 * DAY) & (t < T0 + 90 * DAY + 3 * HOUR))  # rows missing: stale values
            keep &= rng.random(len(t)) > 0.01
            self.met[sym] = {"t": t[keep], "ls": ls[keep], "oi": oi[keep]}
            k = np.arange(-60 * 3, days * 3)
            calc = T0 + k * 8 * HOUR + rng.integers(0, 1000, len(k))
            hours = np.full(len(k), 8.0)
            if sym == "SOLUSDT":
                extra = T0 + 100 * DAY + np.arange(1, 10 * 12) * 2 * HOUR + 7
                extra = extra[(extra - T0) % (8 * HOUR) != 7]
                calc = np.r_[calc, extra]
                hours = np.r_[hours, np.full(len(extra), 2.0)]
            rate = rng.normal(1e-4, 3e-4, len(calc))
            self.fund[sym] = NI.parse_funding(pd.DataFrame({"calc_time": calc, "funding_interval_hours": hours,
                                                            "last_funding_rate": rate}))

    def market(self, D, rule, tf, cut=None):
        coins = []
        for sym in SYMS:
            m = self.min[sym]
            if cut is not None:
                keep = m["ts"] + MIN <= cut
                m = {k: v[keep] for k, v in m.items()}
            b = D.bars(m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], D.TF_MS[tf])
            kw = {}
            if rule in ("H3A_CROWD_FADE", "D06_OI_DIVERGENCE"):
                me = self.met[sym]
                keep = np.ones(len(me["t"]), bool) if cut is None else me["t"] + 5 * MIN <= cut
                kw["metrics"] = {k: v[keep] for k, v in me.items()}
            if rule in ("D04_FUNDING_FADE", "D05_FUNDING_TREND"):
                f = self.fund[sym]
                keep = np.ones(len(f["t"]), bool) if cut is None else f["t"] <= cut
                kw["funding"] = {k: v[keep] for k, v in f.items()}
            if rule == "D05_FUNDING_TREND":
                h = D.HTF_OF[tf]
                hb = D.bars(m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], D.TF_MS[h])
                kw["htf"] = {"close_ms": hb["open_ms"] + D.TF_MS[h], "c": hb["c"]}
            if rule == "D10_VWAP_REVERT":
                kw["minutes"] = m
            coins.append(D.Coin(sym, tf, b["open_ms"], b["o"], b["h"], b["l"], b["c"], b["v"], **kw))
        return D.Market(tf, coins)


@pytest.fixture(scope="module")
def world(NI):
    return World(NI)


def cut_mismatches(D, world, rule, tf, n_signal_cuts=4, n_random_cuts=2, seed=0):
    """Cut every input at times X and compare each cut's signals with the full data's on the bars closing at or
    before X. The cuts: the closes of bars where the full data signal (so the cut bar is the last bar the rule sees)
    and random times. Returns (mismatches, signals seen before the cuts)."""
    rng = np.random.default_rng(seed)
    full = world.market(D, rule, tf)
    combos = D.grid(rule)
    fs = [D.signals(rule, full, c) for c in combos]
    ends = [(r, sym, i) for r, f in enumerate(fs) for sym in SYMS
            for i in np.flatnonzero(f[sym][0] | f[sym][1]) if i >= D.WARMUP_BARS]
    span = full.coins["BTCUSDT"].close_ms
    cuts = [int(full.coins[ends[k][1]].close_ms[ends[k][2]])
            for k in rng.choice(len(ends), min(n_signal_cuts, len(ends)), replace=False)] if ends else []
    cuts += [int(x) + 7 * MIN for x in rng.choice(span[len(span) // 2:], n_random_cuts, replace=False)]
    bad, seen = [], len(ends)
    for cut in cuts:
        part = world.market(D, rule, tf, cut)
        for r, combo in enumerate(combos):
            b = D.signals(rule, part, combo)
            for sym in SYMS:
                n = part.coins[sym].n
                assert np.array_equal(full.coins[sym].open_ms[:n], part.coins[sym].open_ms)
                assert part.coins[sym].close_ms[-1] <= cut
                for k in (0, 1):
                    if not np.array_equal(fs[r][sym][k][:n], b[sym][k]):
                        bad.append((cut, combo, sym, k))
                assert not (b[sym][0] & b[sym][1]).any()
    return bad, seen


@pytest.mark.parametrize("rule", ["H3A_CROWD_FADE", "D04_FUNDING_FADE", "D05_FUNDING_TREND", "D06_OI_DIVERGENCE",
                                  "D08_CROSS_COIN", "D10_VWAP_REVERT", "D01_VOL_SPIKE"])
def test_cutting_the_data_never_changes_earlier_signals(D, world, rule):
    for tf in D.RULES[rule]["tfs"]:
        bad, seen = cut_mismatches(D, world, rule, tf)
        assert not bad, (rule, tf, bad[:3])
        assert seen > 0, (rule, tf)                      # the check is not empty


# ------------------------------------------------------------------ test 4: selection and controls
def test_plateau_with_section4_neighbours_equals_a_direct_computation(RN, D):
    rng = np.random.default_rng(11)
    rule = "D05_FUNDING_TREND"
    g = D.grid(rule)
    st = np.zeros((len(g), 6, 3, 4))
    st[:, :, 0, 0] = rng.integers(100, 260, (len(g), 6))
    st[:, :, 0, 1] = rng.normal(0, 0.002, (len(g), 6)) * st[:, :, 0, 0]
    n, mean, plat = RN.plateau(rule, st)
    ps = D.RULES[rule]["params"]
    names = RN.SEC4
    for r, row in enumerate(g):
        for e in range(6):
            if n[r, e] < 150:
                assert np.isnan(plat[r, e])
                continue
            xs = [mean[r, e]]
            for p, vals, _ref in ps:                    # numbers one step up / down, same exit
                i = vals.index(row[p])
                for d in (-1, 1):
                    if 0 <= i + d < len(vals):
                        q = g.index({**row, p: vals[i + d]})
                        xs.append(mean[q, e] if n[q, e] >= 150 else 0.0)
            rule_e, k = names[e].split("|")
            if rule_e == "tp3R":                         # the next narrower / wider stop among section 4's
                ks = [1.5, 2.0, 3.0, 4.0]
                i = ks.index(float(k))
                for d in (-1, 1):
                    if 0 <= i + d < len(ks):
                        f = names.index(f"tp3R|{ks[i + d]:g}")
                        xs.append(mean[r, f] if n[r, f] >= 150 else 0.0)
            assert plat[r, e] == pytest.approx(float(np.median(xs)))
    picks = RN.choose(n, mean, plat)
    good = sorted(((-plat[r, e], -mean[r, e], r, e) for r in range(len(g)) for e in range(6)
                   if np.isfinite(plat[r, e]) and plat[r, e] > 0))[:3]
    assert picks == [(x[2], x[3]) for x in good]


def test_flip_seeding_and_controls_equal_a_direct_computation(RN):
    rule, tf = "D01_VOL_SPIKE", "1h"
    work = "/synthetic-work"
    test_start = RN._ms("2024-01-01")
    rng = np.random.default_rng(12)
    nb = 2000
    saved = dict(RN._TABLE)
    try:
        for sym in SYMS:
            close = test_start - 400 * HOUR + np.arange(nb, dtype=np.int64) * HOUR
            P = rng.normal(0, 0.01, (6, nb, 2)).astype(np.float32)
            P[rng.random((6, nb, 2)) < 0.1] = np.nan
            RN._TABLE[(work, sym, tf)] = {"close": close, "atr": np.ones(nb), "P": P, "sha256": "x", "file": sym}
        ctx = RN.Ctx("/synthetic-data", work, None, "/synthetic-out", ex={})
        p = {"id": RN.pick_id(rule, tf, 4, 3), "rule": rule, "tf": tf, "row": 4, "exit": RN.SEC4[3], "exit_index": 3}
        coins = rng.integers(0, 6, 300)
        idx = rng.integers(300, nb, 300)
        side = np.where(rng.random(300) < 0.7, 1, -1).astype(np.int8)
        sig = {"coin": coins, "idx": idx, "side": side,
               "close": np.array([RN._TABLE[(work, SYMS[c], tf)]["close"][i] for c, i in zip(coins, idx)]),
               "x": np.array([RN._TABLE[(work, SYMS[c], tf)]["P"][3, i, 0 if s > 0 else 1]
                              for c, i, s in zip(coins, idx, side)], float)}
        sig["pid"] = np.where(sig["close"] >= test_start, 1, 0).astype(np.int8)
        # the seeding formula
        h = hashlib.sha256(f"newinfo-flip|3|{p['id']}|ETHUSDT|{test_start}".encode()).hexdigest()
        assert RN.flip_side(3, p["id"], "ETHUSDT", test_start) == (1 if int(h[:8], 16) % 2 == 0 else -1)
        flips = RN.flip_means(ctx, p, sig)
        assert len(flips) == 10
        for s in range(10):
            xs = []
            for q in np.flatnonzero(sig["pid"] == 1):
                sym = SYMS[sig["coin"][q]]
                hh = hashlib.sha256(f"newinfo-flip|{s}|{p['id']}|{sym}|{sig['close'][q]}".encode()).hexdigest()
                col = 0 if int(hh[:8], 16) % 2 == 0 else 1
                xs.append(RN._TABLE[(work, sym, tf)]["P"][3, sig["idx"][q], col])
            xs = np.array(xs, float)
            assert flips[s] == pytest.approx(np.nanmean(xs))
        vals = []
        for q in np.flatnonzero((sig["pid"] == 1) & np.isfinite(sig["x"])):
            T = RN._TABLE[(work, SYMS[sig["coin"][q]], tf)]
            m = (T["close"] >= test_start) & (T["close"] < RN._ms("2026-10-01"))
            m[:RN.WARMUP_BARS] = False
            vals.append(np.nanmean(T["P"][3, m, 0 if sig["side"][q] > 0 else 1].astype(float)))
        assert RN.same_side_mean(ctx, p, sig) == pytest.approx(np.mean(vals))
    finally:
        RN._TABLE.clear()
        RN._TABLE.update(saved)


def _bh_direct(ps, q):
    m = len(ps)
    order = np.argsort(ps, kind="stable")
    k = 0
    for r, i in enumerate(order, 1):
        if ps[i] <= q * r / m:
            k = r
    out = np.zeros(m, bool)
    out[order[:k]] = True
    return out


def test_bh_family_includes_every_pick(RN):
    rng = np.random.default_rng(13)
    rows = []
    for i in range(42):
        n = int(rng.integers(50, 400))
        p = float(rng.uniform(0, 0.02)) if i % 3 == 0 else float(rng.uniform(0, 1))
        rows.append({"test": {"n": n, "mean": 0.001}, "extra": {"n": 30, "mean": 0.001}, "test_p": p,
                     "flip_mean": 0.0, "same_side_mean": 0.0, "cost": {"x2": {"mean": 0.001}}})
    RN.judge(rows)
    ps = [r["test_p"] if r["test"]["n"] >= 100 else 1.0 for r in rows]
    want = _bh_direct(np.array(ps), 0.10)
    assert [r["checks"]["test_fdr"] for r in rows] == want.tolist()
    assert all(not r["checks"]["test_fdr"] for r in rows if r["test"]["n"] < 100)
    for r in rows:
        assert r["pass"] == all(r["checks"].values())
    assert sum(r["pass"] for r in rows) == sum(w and r["test"]["n"] >= 100 for w, r in zip(want, rows))


def test_period_ids(RN):
    close = np.array([RN._ms(d) for d in ("2020-03-01", "2020-10-01", "2021-06-01", "2021-12-15", "2024-02-01",
                                          "2026-09-30", "2026-10-01")], np.int64)
    close = np.r_[np.zeros(RN.WARMUP_BARS, np.int64), close]
    p = RN.period_ids("D01_VOL_SPIKE", "ETHUSDT", close)[RN.WARMUP_BARS:]
    assert p.tolist() == [2, 2, 0, 0, 1, 1, -1]
    p = RN.period_ids("H3A_CROWD_FADE", "BTCUSDT", close)[RN.WARMUP_BARS:]
    assert p.tolist() == [-1, 2, 2, 0, 1, 1, -1]
    p = RN.period_ids("D06_OI_DIVERGENCE", "ETHUSDT", close)[RN.WARMUP_BARS:]
    assert p.tolist() == [-1, -1, -1, 0, 1, 1, -1]         # extra period: BTC alone
    assert (RN.period_ids("D01_VOL_SPIKE", "BTCUSDT", np.full(400, RN._ms("2022-01-01")))[:RN.WARMUP_BARS] == -1).all()


def test_pins_required_before_a_real_run(RN, tmp_path):
    rc = RN.main(["grid", "--out", str(tmp_path / "o")]) if RN.pin_problems() else None
    if rc is not None:
        assert rc == 2 and not os.path.exists(tmp_path / "o")


# ------------------------------------------------------------------ data parsers
def test_parse_metrics(NI):
    x = pd.DataFrame({"create_time": ["2024-01-01 00:10:00", "2024-01-01 00:00:00", "2024-01-01 00:05:00",
                                      "2024-01-01 00:05:00", "2024-01-01 00:07:00"],
                      "count_long_short_ratio": ["1.5", "0", "abc", "2.5", "-1"],
                      "sum_open_interest": ["10", "11", "", "13", "14"]})
    m = NI.parse_metrics(x)
    t0 = RN_ms("2024-01-01")
    assert m["t"].tolist() == [t0, t0 + 5 * MIN, t0 + 7 * MIN, t0 + 10 * MIN]
    assert np.array_equal(m["ls"], [np.nan, 2.5, np.nan, 1.5], equal_nan=True)       # repeated stamp: the last row
    assert np.array_equal(m["oi"], [11, 13, 14, 10], equal_nan=True)
    assert m["info"] == {"rows": 5, "repeated": 1, "off_mark": 1}


def RN_ms(day):
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


def _metrics_csv(rows):
    head = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
            "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n")
    return head + "".join(f"{t},BTCUSDT,{oi},1,1,1,{ls},1\n" for t, oi, ls in rows)


def test_metrics_sources_and_cache(NI, tmp_path, monkeypatch):
    of = tmp_path / "orderflow"
    of.mkdir()
    monkeypatch.setattr(NI, "ORDERFLOW", str(of))
    with gzip.open(of / "btc_metrics_5m.csv.gz", "wt") as fh:
        fh.write(_metrics_csv([("2026-09-28 23:50:00", 5, 1.1), ("2026-09-28 23:55:00", 6, 1.2)]))
    d = tmp_path / "ni"
    for day, rows in (("2026-09-29", [("2026-09-28 23:55:00", 7, 1.3), ("2026-09-29 00:00:00", 8, 1.4)]),
                      ("2026-09-30", [("2026-09-30 00:00:00", 9, 1.5)])):
        p = d / "raw" / NI.rel_daily_metrics("BTCUSDT", day)
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(f"BTCUSDT-metrics-{day}.csv", _metrics_csv(rows))
    m = NI.metrics(str(d), "BTCUSDT")
    assert m["oi"].tolist() == [5, 7, 8, 9]                 # the daily file wins on a repeated stamp
    assert os.path.exists(d / "metrics" / "BTCUSDT.npz")
    assert NI.metrics(str(d), "BTCUSDT")["oi"].tolist() == [5, 7, 8, 9]    # from the cache
    with zipfile.ZipFile(d / "raw" / NI.rel_daily_metrics("BTCUSDT", "2026-09-30"), "w") as z:
        z.writestr("x.csv", _metrics_csv([("2026-09-30 00:00:00", 10, 1.5)]))
    assert NI.metrics(str(d), "BTCUSDT")["oi"].tolist() == [5, 7, 8, 10]   # a changed source rebuilds it


def test_funding_zip_needs_the_interval_column(NI, tmp_path):
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as z:
        z.writestr("a.csv", "calc_time,funding_interval_hours,last_funding_rate\n"
                            "1704067200001,8,0.0001\n1704067200001,8,0.0003\n1704074400000,2,0.0005\n")
    f = NI.parse_funding(NI.read_funding_zip(str(good)))
    assert f["t"].tolist() == [1704067200000, 1704074400000]
    assert f["calc"].tolist() == [1704067200001, 1704074400000]
    assert np.allclose(f["f8"], [0.0003, 0.002])            # repeated calc time: the last row
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("a.csv", "calc_time,last_funding_rate\n1704067200001,0.0001\n")
    with pytest.raises(SystemExit):
        NI.read_funding_zip(str(bad))
    assert NI.funding_header(str(bad)) == ["calc_time", "last_funding_rate"]


# ------------------------------------------------------------------ the pipeline on synthetic 1m bars
@pytest.fixture(scope="module")
def pipeline(RN, NI, tmp_path_factory):
    base = tmp_path_factory.mktemp("newinfo")
    data, work, out = str(base / "data"), str(base / "work"), str(base / "out")
    os.makedirs(os.path.join(data, "1m"))
    days = 150
    w = World(NI, days=days, seed=21)
    for sym in SYMS:
        m = w.min[sym]
        fund = np.zeros(len(m["ts"]))
        f = w.fund[sym]
        j = np.searchsorted(m["ts"], f["t"])
        ok = (j < len(m["ts"])) & (f["t"] >= m["ts"][0])
        np.add.at(fund, j[ok], f["rate"][ok])
        np.savez(os.path.join(data, "1m", f"{sym}.npz"), ts=m["ts"], o=m["o"], h=m["h"], l=m["l"], c=m["c"],
                 v=m["v"], mo=m["o"], mh=m["h"], ml=m["l"], mc=m["c"], fund=fund)
    R = RN.R
    old = {k: getattr(RN, k) for k in ("PERIODS", "WARMUP_BARS", "MIN_SELECT", "MIN_TEST", "MIN_EXTRA", "N_BOOT",
                                       "metrics", "funding")}
    old_frame = R.FRAME_DIR[0]
    RN.PERIODS = {"price": (("select", "2020-02-15", "2020-04-10"), ("test", "2020-04-10", "2020-05-30"),
                            ("extra", "2020-01-10", "2020-02-15")),
                  "metrics": (("select", "2020-02-20", "2020-04-10"), ("test", "2020-04-10", "2020-05-30"),
                              ("extra", "2020-01-10", "2020-02-20"))}
    RN.WARMUP_BARS = 60
    RN.MIN_SELECT, RN.MIN_TEST, RN.MIN_EXTRA, RN.N_BOOT = 20, 10, 2, 200
    RN.metrics = lambda ctx, sym: w.met[sym]
    RN.funding = lambda ctx, sym: w.fund[sym]
    R.FRAME_DIR[0] = os.path.join(out, "frames")
    RN._COIN.clear()
    RN._TABLE.clear()
    ex = R.exchange(None, True)
    S = R.K.settings_vector()
    names = np.array([e[0] for e in R.K.EXITS])
    os.makedirs(os.path.join(work, "outcomes"))
    for sym in SYMS:                                   # outcome tables: section 4's exits computed, the rest NaN
        d = R.minute_data(data, sym)
        for tf in RN.TFS:
            df, close = R.frame(data, sym, tf)
            atr = R._vendor_fg().atr(df, 14).to_numpy(float)
            n = len(close)
            P = np.full((len(names), n, 2), np.nan, np.float32)
            f = np.zeros(n, bool)
            nan = np.full(n, np.nan)
            br, step, mn = ex[sym]
            for e in RN.EXIT_GLOBAL:
                p, _x, _r, _l = R.K.outcomes(S, br, d["ts"], d["o"], d["h"], d["l"], d["mo"], d["mh"], d["ml"],
                                             d["fund"], close.astype(np.int64), atr, f, f, R.EQUITY, step, mn,
                                             *R.K.exit_args(e), nan, nan)
                P[e] = p
            np.savez(R.outcome_path(work, sym, tf), close=close, atr=atr, exits=names, pnl_normal=P)
    ctx = RN.Ctx(data, work, None, out, ex=ex)
    os.makedirs(out, exist_ok=True)
    RN.stage_grid(ctx, 1)
    sel = RN.stage_select(out)
    con = RN.stage_confirm(ctx)
    text = RN.write_report(out)
    yield RN, ctx, sel, con, text, w
    for k, v in old.items():
        setattr(RN, k, v)
    R.FRAME_DIR[0] = old_frame
    RN._COIN.clear()
    RN._TABLE.clear()


def test_pipeline_writes_every_file(pipeline):
    RN, ctx, sel, con, text, _w = pipeline
    assert len([f for f in os.listdir(os.path.join(ctx.out, "cells")) if f.endswith(".npz")]) == 14
    assert not sel["missing"] and len(sel["cells"]) == 14
    assert all(len(c["picks"]) <= 3 for c in sel["cells"])
    assert con["family"] == len(sel["picks"]) > 0
    for f in ("select.json", "confirm.json", "RESULTS_KO.md"):
        assert os.path.exists(os.path.join(ctx.out, f))
    assert "## 결론" in text and "## 고른 조합과 판정" in text
    for r in con["rows"]:
        assert set(r["checks"]) == {"test_trades", "test_positive", "beats_flip", "beats_same_side", "test_fdr",
                                    "cost_x2_positive", "extra_trades", "extra_positive"}
        assert r["pass"] == all(r["checks"].values())
        assert len(r["flip_means"]) == 10
        assert set(r["account"]) == {"normal_span", "normal_test", "quarter_span", "quarter_test"}
        assert r["id"] in text


def test_pipeline_grid_stats_equal_a_recount(pipeline):
    RN, ctx, sel, *_ = pipeline
    for rule, tf in (("D01_VOL_SPIKE", "1h"), ("D08_CROSS_COIN", "4h"), ("H3A_CROWD_FADE", "1h")):
        with np.load(RN.cell_path(ctx.out, rule, tf)) as z:
            st = z["stats"]
        combos = RN.D.grid(rule)
        m = RN.market(ctx, rule, tf)
        for r in (0, len(combos) // 2, len(combos) - 1):
            for e in (0, 3, 5):
                sig = RN.pick_signals(ctx, rule, tf, combos[r], e, m)
                for k in range(3):
                    x = sig["x"][(sig["pid"] == k) & np.isfinite(sig["x"])]
                    assert st[r, e, k, 0] == len(x)
                    assert st[r, e, k, 1] == pytest.approx(x.sum(), abs=1e-6)
                    assert st[r, e, k, 3] == (x > 0).sum()


def test_pipeline_recompute_at_cost_x1_equals_the_table(pipeline):
    RN, ctx, sel, con, *_ = pipeline
    p = sel["picks"][0]
    sig = RN.pick_signals(ctx, p["rule"], p["tf"], p["combo"], p["exit_index"])
    for ci, sym in enumerate(SYMS):
        q = np.flatnonzero(sig["coin"] == ci)[:40]
        if len(q):
            got = RN.recompute(ctx, sym, p["tf"], sig["idx"][q], sig["side"][q], p["exit_index"], RN.settings())
            assert np.array_equal(got.astype(np.float32), sig["x"][q].astype(np.float32), equal_nan=True)
    assert RN.verify_table(ctx, "ETHUSDT", "1h", RN.K.settings_vector())
    T = RN.table(ctx.work, "ETHUSDT", "1h")
    saved = T["P"].copy()
    try:
        T["P"][:] = np.where(np.isfinite(T["P"]), T["P"] + np.float32(1e-3), T["P"])
        assert not RN.verify_table(ctx, "ETHUSDT", "1h", RN.K.settings_vector())
    finally:
        T["P"][:] = saved


def test_pipeline_quarter_and_cost_settings(pipeline):
    RN, *_ = pipeline
    S, S2, Sq = RN.settings(), RN.settings("normal", 2.0), RN.settings("quarter")
    for i in range(len(S)):
        assert S2[i] == (2 * S[i] if i in (0, 1, 5, 19) else S[i])
        assert Sq[i] == (S[i] / 4 if i in (11, 13, 15, 17) else S[i])


def test_worst_month(RN):
    ms = np.array([RN_ms("2024-01-05"), RN_ms("2024-01-20"), RN_ms("2024-02-03")], np.int64)
    walk = np.array([5000.0, 5500.0, 4400.0, 4840.0])
    wm = RN.worst_month(ms, walk)
    assert wm["month"] == "2024-01" and wm["change"] == pytest.approx(4400 / 5000 - 1)
    assert RN.worst_month(np.zeros(0, np.int64), np.array([5000.0])) is None
