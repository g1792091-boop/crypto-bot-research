"""DOGE is the friend's long/short bot: the account goes long on DOGE_L and SHORT on DOGE_S.

The locked compute_signals already stores DOGE_S as -1 on its short bars, so the correct join is the
sum (paperbot.sigservice.doge_join). The first run of entry study A used DOGE_L - DOGE_S, which turned
every short into a long; the caches were rebuilt and the study re-run. These tests keep it fixed."""

from __future__ import annotations

import glob
import os
import sys

import numpy as np
import pytest

from paperbot.sigservice import doge_join

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))

A = pytest.importorskip("analysis_sr")

CACHES = (A.SIG12, A.SIG3)


def test_join_keeps_shorts_short():
    doge_l = np.array([0, 1, 0, 0, 1], np.int8)
    doge_s = np.array([0, 0, -1, 0, -1], np.int8)      # compute_signals: doge_short -> (zeros, short) -> -1
    assert doge_join(doge_l, doge_s).tolist() == [0, 1, -1, 0, 0]


@pytest.mark.parametrize("cache", CACHES, ids=("periods_1_2", "period_3"))
def test_cached_doge_signal_has_both_sides(cache):
    files = [f for f in sorted(glob.glob(os.path.join(cache, "sig_*_*.npz"))) if "_1d_" not in f]
    if not files:
        pytest.skip(f"no signal cache in {cache}")
    pos = neg = 0
    for f in files:
        with np.load(f) as z:
            s = np.asarray(z["s__DOGE"])
        assert set(np.unique(s)) <= {-1, 0, 1}, os.path.basename(f)
        pos += int((s > 0).sum())
        neg += int((s < 0).sum())
    assert pos > 0 and neg > 0, "s__DOGE must carry short signals (-1); the cache still has the old long-only join"


def test_doge_disclosure_present():
    assert "DOGE" in A.STRATEGY_NOTES and "short" in A.STRATEGY_NOTES["DOGE"]
    assert any(a.startswith("DOGE join corrected") for a in A.AMBIGUITIES)
