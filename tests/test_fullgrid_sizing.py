"""research/fullgrid/sizing.py: sizes, weekly multiples, drawn months, and the size rule."""

from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "fullgrid"))

import sizing as Z  # noqa: E402


def test_size_vector_scales_margin_only():
    base = Z.K.settings_vector()
    half, big = Z.size_vector(0.5), Z.size_vector(2.0)
    assert list(half[[11, 13, 15, 17]]) == [0.25, 0.2, 0.15, 0.1]
    assert list(big[[11, 13, 15, 17]]) == [Z.MAX_MARGIN, 0.8, 0.6, 0.4]
    assert list(half[[12, 14, 16, 18]]) == list(base[[12, 14, 16, 18]]) == [50, 40, 30, 20]
    assert np.array_equal(np.delete(half, [11, 13, 15, 17]), np.delete(base, [11, 13, 15, 17]))


def test_weekly_growth_compounds_within_a_week():
    lo = Z.R.MONDAY0 + 10 * Z.R.WEEK_MS
    hi = lo + 3 * Z.R.WEEK_MS
    ex = np.array([lo + 1, lo + 2, lo + 2 * Z.R.WEEK_MS + 5])
    g = Z.weekly_growth(ex, np.array([0.1, -0.5, -2.0]), lo, hi)
    assert np.allclose(g, [1.1 * 0.5, 1.0, 0.0])          # a loss past the wallet ends at zero


def test_months_and_summary():
    G = np.array([2.0, 0.5])                                # one candidate: a doubling week, a halving week
    m = Z.months(G, draws=4000, weeks=4, seed=1)
    assert set(np.round(np.unique(m), 6)) <= {16.0, 4.0, 1.0, 0.25, 0.0625}
    s = Z.month_summary(m)
    assert abs(s["x10"] - 1 / 16) < 0.02 and abs(s["under_half"] - 5 / 16) < 0.03 and s["median"] == 1.0
    B = Z.months(np.column_stack([G, G[::-1]]), draws=2000, weeks=1, seed=1)    # opposite weeks: always 1.25
    assert np.allclose(B, 1.25)


def test_choose_the_fastest_safe_size():
    def v(med, half):
        return {"select": {"month": {"median": med, "under_half": half}}}
    assert Z.choose({0.25: v(1.01, 0.0), 0.5: v(1.03, 0.01), 1.0: v(1.08, 0.04), 2.0: v(1.2, 0.3)}) == 1.0
    assert Z.choose({1.0: v(1.1, 0.2), 2.0: v(1.3, 0.4)}) is None
