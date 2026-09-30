"""Statistics helpers of the entry study part A (research/entry_study/analysis_sr.py).

Synthetic inputs only: period bounds, the random-entry null draw, the week-block bootstrap p and
Benjamini-Hochberg."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))

A = pytest.importorskip("analysis_sr")


def _ts(start: str, n: int, minutes: int) -> np.ndarray:
    return pd.date_range(start, periods=n, freq=f"{minutes}min").as_unit("ns").asi8


def test_period_bounds_warmup_and_next_bar():
    ts = _ts("2024-06-30 00:00", 96, 60)          # 2024-06-30 00:00 .. 2024-07-03 23:00
    lo, hi = A.period_bounds(ts, 1, warm=10)
    assert lo == 10 and ts[hi - 1] == pd.Timestamp("2024-06-30 23:00").value and hi == 24
    lo2, hi2 = A.period_bounds(ts, 2, warm=10)
    assert lo2 == 24 and hi2 == len(ts) - 1      # the last bar has no next bar to enter on
    lo3, hi3 = A.period_bounds(ts, 3, warm=10)
    assert hi3 == lo3                             # no period-3 bars in this series


def test_random_bars_count_unique_and_seeded():
    i1, s1 = A.random_bars(100, 50_100, 5, 0, 1)
    i2, s2 = A.random_bars(100, 50_100, 5, 0, 1)
    assert len(i1) == A.RANDOM_N and len(np.unique(i1)) == len(i1)
    assert i1.min() >= 100 and i1.max() < 50_100
    assert np.array_equal(i1, i2) and np.array_equal(s1, s2)
    assert set(np.unique(s1)) == {-1, 1} and abs((s1 > 0).mean() - 0.5) < 0.02
    i3, _ = A.random_bars(100, 50_100, 5, 1, 1)
    assert not np.array_equal(i1, i3)             # other coin, other stream
    small, ss = A.random_bars(7, 507, 240, 2, 3)
    assert np.array_equal(small, np.arange(7, 507)) and len(ss) == 500   # fewer bars than 20,000: all


def _weeks(rng, W, n_per, mu0, mu1, share1=0.5):
    n1 = rng.binomial(n_per, share1, W).astype(float)
    n0 = n_per - n1
    s0 = rng.normal(mu0 * n0, np.sqrt(np.maximum(n0, 1)) * 0.3)
    s1 = rng.normal(mu1 * n1, np.sqrt(np.maximum(n1, 1)) * 0.3)
    return n0, s0, n1, s1


def test_week_block_test_direction_and_p():
    rng = np.random.default_rng(0)
    W = 120
    C = A.boot_counts(W, 2000, 1)
    assert C.shape == (2000, W) and (C.sum(axis=1) == W).all()
    n0, s0, n1, s1 = _weeks(rng, W, 20, 0.05, -0.05)
    p1 = A.week_block_test("P1", n0, s0, n1, s1, C)          # P1 = mean(g0) - mean(g1) > 0: true here
    assert p1["status"] == "ok" and p1["diff"] > 0 and p1["p"] == pytest.approx(1 / 2001)
    p2 = A.week_block_test("P2", n0, s0, n1, s1, C)          # P2 = mean(g1) - mean(g0): negative here
    assert p2["diff"] == pytest.approx(-p1["diff"]) and p2["p"] > 0.99
    assert p1["n0"] + p1["n1"] == 20 * W


def test_week_block_test_null_roughly_uniform():
    ps = []
    for seed in range(60):
        rng = np.random.default_rng(100 + seed)
        n0, s0, n1, s1 = _weeks(rng, 80, 10, 0.0, 0.0)
        ps.append(A.week_block_test("P1", n0, s0, n1, s1, A.boot_counts(80, 400, seed))["p"])
    ps = np.array(ps)
    assert 0.3 < ps.mean() < 0.7 and (ps < 0.05).mean() < 0.2


def test_week_block_test_insufficient():
    n0 = np.array([10.0, 10.0, 9.0])
    n1 = np.array([10.0, 10.0, 10.0])
    r = A.week_block_test("P1", n0, n0 * 0.1, n1, n1 * 0.0, A.boot_counts(3, 100, 0))
    assert r["status"] == "insufficient" and np.isnan(r["p"]) and r["n0"] == 29
    assert r["diff"] == pytest.approx(0.1)


def test_week_block_counts_undefined_resamples_as_failures():
    # group 1 lives in a single week: resamples missing that week have no group-1 trades
    W = 4
    n0 = np.array([30.0, 30.0, 30.0, 30.0]); s0 = n0 * 0.1
    n1 = np.array([40.0, 0.0, 0.0, 0.0]); s1 = n1 * -0.5
    C = A.boot_counts(W, 1000, 3)
    r = A.week_block_test("P1", n0, s0, n1, s1, C)
    miss = int((C[:, 0] == 0).sum())
    assert r["undefined_resamples"] == miss and r["p"] == pytest.approx((1 + miss) / 1001)


def test_bh_matches_definition():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.059, 0.074, 0.205, 0.212, 0.216])
    rej, rank, adj = A.bh(p, 0.05)
    assert rej.tolist() == [True, True] + [False] * 8
    assert rank.tolist() == list(range(1, 11))
    assert adj[0] == pytest.approx(0.01) and adj[1] == pytest.approx(0.04)
    rej10, _, _ = A.bh(p, 0.10)
    assert rej10.sum() == 6                      # 0.059 <= 0.1 * 6 / 10 < 0.074 / 7 * 10 ...
    shuffled = np.random.default_rng(0).permutation(10)
    r2, _, a2 = A.bh(p[shuffled], 0.10)
    assert np.array_equal(r2, rej10[shuffled]) and np.allclose(a2, A.bh(p, 0.10)[2][shuffled])


def test_room_bucket_edges():
    b = A.room_bucket(np.array([0.0, 0.49, 0.5, 0.99, 1.0, 1.99, 2.0, 3.99, 4.0, 10.0, np.nan]))
    assert b.tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, -1]
