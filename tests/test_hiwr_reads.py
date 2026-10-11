"""research/hiwr/reads.py helpers (PREREG_HIWR.md section 14) against the core modules: the plain-Python trade
(R7's wait-for-a-later-minute and R10's Saturday close) equals walk.trade_one and the trade list's r; the Saturday
split of the minute store; the R8 month bootstrap; streaks and the R14 band; the datacheck (ii) fallback months.
Synthetic prices only."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
pytest.importorskip("numba")

from research.hiwr import acct as A  # noqa: E402
from research.hiwr import data as D  # noqa: E402
from research.hiwr import hiwr as H  # noqa: E402
from research.hiwr import reads as RD  # noqa: E402
from research.hiwr import walk as W  # noqa: E402

R = D.fg_run()
MIN = 60_000
T0 = D.ms("2021-01-04")                      # a Monday


def synth(n, seed, price=100.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0007, n)
    jump = rng.random(n) < 0.002
    r[jump] += rng.normal(0, 0.02, int(jump.sum()))
    c = price * np.exp(np.cumsum(r))
    o = np.r_[price, c[:-1]] * np.exp(np.where(rng.random(n) < 0.004, rng.normal(0, 0.006, n), 0.0))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0008, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0008, n)))
    mo = o * (1 + rng.normal(0, 0.0002, n))
    mh = np.maximum(hi * (1 + np.where(rng.random(n) < 0.002, 0.025, 0.0)), mo)
    ml = np.minimum(lo * (1 - np.where(rng.random(n) < 0.002, 0.025, 0.0)), mo)
    ts = T0 + np.arange(n, dtype=np.int64) * MIN
    fund = np.where((ts % (8 * 3_600_000)) == 0, rng.choice([-1, 1], n) * rng.uniform(1e-5, 2e-3, n), 0.0)
    return dict(ts=ts, o=o, h=hi, l=lo, c=c, v=np.ones(n), mo=mo, mh=mh, ml=ml, mc=c, fund=fund)


def test_trade_py_equals_trade_one_and_the_wait_option():
    a = synth(20_000, 1)
    rng = np.random.default_rng(2)
    n_tp_in = 0
    for _ in range(1500):
        e = int(rng.integers(1, 19_000))
        sg = 1.0 if rng.random() < 0.5 else -1.0
        F = a["o"][e] * (1 + sg * W.SLIP)
        S = a["o"][e] - sg * a["o"][e] * rng.uniform(0.003, 0.02)
        T = F * (1 + sg * rng.uniform(0.0005, 0.006))
        Q = F * (1 - sg * rng.uniform(0.01, 0.03))
        maker = bool(rng.random() < 0.5)
        pierce = float(rng.choice([0.0, 0.0001]))
        end = int(rng.integers(e + 1, 20_000))
        ce = bool(rng.random() < 0.5)
        want = W.trade_one(a["o"], a["h"], a["l"], a["c"], a["mo"], a["mh"], a["ml"], e, end, ce, sg, S, T, Q, W.SLIP,
                           maker, pierce, F)
        got = RD.trade_py(a, e, end, ce, sg, S, T, Q, W.SLIP, maker, pierce, F, e)
        assert int(want[0]) == got[0] and abs(want[1] - got[1]) < 1e-15
        if got[0] >= 0 and got[0] // 8 == e and got[0] % 8 == 5:
            n_tp_in += 1
            later = RD.trade_py(a, e, end, ce, sg, S, T, Q, W.SLIP, maker, pierce, F, e + 1)
            assert later[0] < 0 or later[0] // 8 > e
        elif got[0] >= 0:
            assert RD.trade_py(a, e, end, ce, sg, S, T, Q, W.SLIP, maker, pierce, F, e + 1) == got
    assert n_tp_in > 0


def test_outcome_r_equals_the_trade_list():
    a = synth(30_000, 3)
    df, close = D.build_frame(a, "1h")
    atr = R._vendor_fg().atr(df, 14).to_numpy(float)
    br = A.exchange30()["BTCUSDT"]["br"]
    T = W.build_tables(a, close, atr, (T0, int(a["ts"][-1]) + MIN), False, br, warmup=30)
    fc = np.cumsum(a["mo"] * a["fund"])
    rows = np.arange(len(T.bars))
    n = 0
    for cfg in [c for c in W.exit_configs() if c["step"] == 1 and c["k"] in (0, 6) and c["L"] in (30, 50)]:
        for s in (0, 1):
            x = W.trade_list(T, rows, np.full(len(rows), s), cfg)
            sg = 1.0 if s == 0 else -1.0
            for q in np.flatnonzero(x["skip"] == 0):
                e = int(T.ent[q])
                F = T.x[1]["F"][q, s]
                Dst = W.stop_distance(cfg["k"], T.atr[q], T.p0[q])
                Tl = F * (1 + sg * cfg["t"])
                Q = F * (1 - sg * T.liqd[s, cfg["Li"]])
                code, g = RD.trade_py(a, e, T.end, False, sg, T.p0[q] - sg * Dst, Tl, Q, W.SLIP, cfg["fill"] == 1,
                                      0.0, F, e)
                r = RD.outcome_r(fc, e, code, g, sg, F, float(cfg["L"]), cfg["fill"] == 1, W.TAKER, W.MAKER)
                assert code == x["code"][q] and abs(r - x["r"][q]) < 1e-14
                n += 1
    assert n > 500


class _Mk:
    def __init__(self, arrs, ended):
        self.syms = ["BTCUSDT"] * len(arrs)
        self._a = arrs
        self.ended = ended

    def arrays(self, c):
        return self._a[c]


def test_saturday_store_splits_at_saturday_midnight():
    a = synth(20 * 1440, 4)                    # Monday 2021-01-04 .. 20 days
    store, owner, starts = RD.saturday_store(H, _Mk([a], [False]))
    ts = store.ts
    ends = ts[store.off[1:] - 1]
    sat = D.ms("2021-01-09")
    assert ends[0] == sat - MIN and ts[store.off[1]] == sat           # the first segment ends at Friday 23:59
    assert list(store.kind[:-1]) == [1] * (len(store.kind) - 1) and store.kind[-1] == 0
    assert (owner == 0).all() and starts[0] == 0
    assert RD.next_saturday(H, D.ms("2021-01-08") + 5) == sat and RD.next_saturday(H, sat) == sat + 7 * 86_400_000


def test_goal_board_streaks_and_band():
    res = {"exit_ms": np.array([T0 + 86_400_000, T0 + 8 * 86_400_000]), "feff": np.array([2.0, 2.0]),
           "r": np.array([0.01, -0.005]), "final": 1000 * 1.02 * 0.99, "w0": 1000.0}
    g = RD.weekly_growth(H, res["exit_ms"], res["feff"] * res["r"], (T0, T0 + 14 * 86_400_000))
    assert np.allclose(g, [1.02, 0.99])
    gb = RD.goal_board(H, res, (T0, T0 + 14 * 86_400_000))
    assert gb["share_month_x2"] == 0.0 and abs(gb["period_multiple"] - 1.0098) < 1e-12
    st = RD.streaks([0.1, -1, -1, 0.2, -1, -1, -1, 0.1, -1])
    assert st == {"streaks": 3, "max": 3, "counts": {"1": 1, "2": 1, "3": 1}}
    rng = np.random.default_rng(5)
    n = 300
    tr = {"skip": np.zeros(n, np.int8), "side": np.zeros(n, np.int64), "coin": np.zeros(n, np.int64),
          "entry_ms": T0 + np.arange(n) * 3_600_000, "r": rng.normal(0.001, 0.004, n)}
    acc = {"n": 0, "w0": 1000.0}
    b = RD.band(H, tr, acc, (T0, T0 + 60 * 86_400_000))
    w50 = np.convolve(tr["r"], np.ones(50) / 50, "valid")
    assert abs(b["trades_50"]["mean"]["q50"] - np.percentile(w50, 50)) < 1e-12
    assert b["account_30d_multiple"]["q50"] == 1.0


def test_datacheck_fallback_months_are_seeded():
    m1 = H.archive_5m_months("SANDUSDT", D.ms("2021-01-25"))
    m2 = H.archive_5m_months("SANDUSDT", D.ms("2021-01-25"))
    assert m1 == m2 and len(m1) == 3 and all("2021-01" <= m <= "2023-12" for m in m1)
    assert all(m >= "2021-01" for m in H.archive_5m_months("BTCUSDT", D.ms("2020-01-01")))
    assert H.archive_5m_months("TOMOUSDT", D.ms("2023-12-20")) == ["2023-12"]
