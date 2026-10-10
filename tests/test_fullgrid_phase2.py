"""research/fullgrid/checks.py and teams.py (PHASE2_PREREG.md): the pure pieces on hand-made numbers: cost scaling and
labels, years / coins / sides labels, losing runs, worst month, time under water, entry overlap, daily correlation,
bad-day overlap, the forward band, the data check, home states, the persistence bootstrap and the team test."""

from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "fullgrid"))

import checks as CK  # noqa: E402
import run as R  # noqa: E402
import teams as TM  # noqa: E402

DAY = 86_400_000


def ms(y, m=6, d=15):
    return int(np.datetime64(f"{y:04d}-{m:02d}-{d:02d}", "ms").astype(np.int64))


def test_cost_vector_and_label():
    S1, S2 = R.K.settings_vector(), CK.cost_vector(2.0)
    for i in range(len(S1)):
        assert S2[i] == (2 * S1[i] if i in CK.COST_IDX else S1[i])
    assert CK.cost_label(0.01, 0.002) == "비용 3배에도 남음"
    assert CK.cost_label(0.01, -0.001) == "비용 2배에도 남음"
    assert CK.cost_label(-0.001, 0.0) == "비용에 약함" and CK.cost_label(None, None) == "비용에 약함"


def _T(closes, x, coin=None, side=None):
    n = len(x)
    return {"close": np.asarray(closes, np.int64), "x": np.asarray(x, float),
            "coin": np.zeros(n, int) if coin is None else np.asarray(coin), "side": np.ones(n, int) if side is None
            else np.asarray(side), "pid": np.zeros(n, int)}


def test_years_labels():
    closes = [ms(y) for y in range(2020, 2027) for _ in range(25)]
    x = [0.01] * 25 * 7
    y = CK.years(_T(closes, x))
    assert y["plus"] == 7 and y["counted"] == 7 and y["steady"] and not y["lumpy"]
    x2 = [0.001] * 25 * 6 + [0.5] * 25                         # 2026 carries everything
    y2 = CK.years(_T(closes, x2))
    assert y2["lumpy"] and not y2["steady"]


def test_coins_and_sides():
    closes = [ms(2022)] * 120
    coin = [i % 6 for i in range(120)]
    side = [1 if i % 2 else -1 for i in range(120)]
    x = [0.01 if c < 4 else -0.002 for c in coin]
    cs = CK.coins_sides(_T(closes, x, coin, side))
    assert cs["spread"] and cs["good_coins"] == 4 and not cs["one_coin"]
    x2 = [0.05 if c == 0 else 0.0001 for c in coin]
    assert CK.coins_sides(_T(closes, x2, coin, side))["one_coin"]
    x3 = [0.02 if s > 0 else -0.001 for s in side]
    assert CK.coins_sides(_T(closes, x3, coin, side))["one_side"]


def test_worst_stretch_pieces():
    assert CK.longest_losing_run(np.array([0.1, -0.1, -0.1, 0.2, -0.1, -0.1, -0.1])) == 3
    t = np.array([ms(2022, 1, 5), ms(2022, 1, 20), ms(2022, 2, 3), ms(2022, 3, 1)])
    w = CK.worst_month(t, np.array([0.1, -0.2, -0.1, 0.05]))
    assert w["month"] == "2022-01" and abs(w["change"] - (1.1 * 0.8 - 1)) < 1e-12
    uw = CK.under_water(t, np.array([0.1, -0.2, 0.2, 0.1]), ms(2022, 1, 1), ms(2022, 4, 1))
    assert abs(uw["days"] - (t[3] - t[0]) / DAY) < 1e-9 and not uw["open"]   # back above 1.1 only at the 4th close
    uw2 = CK.under_water(t, np.array([0.1, -0.5, 0.1, 0.1]), ms(2022, 1, 1), ms(2022, 6, 1))
    assert uw2["open"] and abs(uw2["days"] - (ms(2022, 6, 1) - t[0]) / DAY) < 1e-9


def test_overlaps_and_correlation():
    H = 3_600_000
    a = {"close": np.array([0, 10 * H, 20 * H]), "coin": np.array([0, 0, 1]), "side": np.array([1, 1, -1])}
    b = {"close": np.array([H, 30 * H, 20 * H]), "coin": np.array([0, 0, 1]), "side": np.array([1, 1, 1])}
    assert CK.overlap_share(a, b, H) == 1 / 3                  # the 3rd has the wrong side, the 2nd is 20 h away
    assert CK.overlap_share(a, b, 0) == 0.0 and CK.overlap_share({"close": np.zeros(0)}, b, H) is None
    d1 = {1: 1.0, 2: -1.0, 3: 2.0, 4: -3.0}
    assert abs(CK.corr_daily(d1, d1) - 1) < 1e-12 and CK.corr_daily({1: 1.0}, {2: 1.0}) is None
    big = {k: (-1.0 - k if k < 40 else 1.0) for k in range(100)}
    assert CK.bad_day_overlap(big, big) == 1.0
    other = {k + 1000: v for k, v in big.items()}
    assert CK.bad_day_overlap(big, other) == 0.0


def test_band_is_reproducible_and_ordered():
    x = np.random.default_rng(1).normal(0.002, 0.03, 500)
    b1, b2 = CK.band(x, "core-A-15m-1"), CK.band(x, "core-A-15m-1")
    assert b1 == b2 and list(b1) == ["10", "20", "30", "50", "100"]
    assert all(v["p5"] < v["median"] for v in b1.values())
    assert b1["100"]["p5"] > b1["10"]["p5"]                     # more trades, narrower band
    assert CK.band(np.zeros(0), "x") == {}


def test_data_check(tmp_path):
    res, data = tmp_path / "res", tmp_path / "data"
    res.mkdir(), data.mkdir()
    syms = [{"symbol": s, "sha256": "h" + s} for s in R.SYMBOLS]
    (res / "data_build.json").write_text(json.dumps({"symbols": syms}))
    (data / "build.json").write_text(json.dumps({"symbols": syms}))
    assert CK.data_mismatch(str(res), str(data)) == []
    syms[2]["sha256"] = "other"
    (data / "build.json").write_text(json.dumps({"symbols": syms}))
    assert CK.data_mismatch(str(res), str(data)) == [R.SYMBOLS[2]]


def test_home_states():
    st = np.array(["추세장"] * 40 + ["횡보장"] * 40 + ["보통"] * 10)
    x = np.r_[np.full(40, 0.02), np.full(40, -0.01), np.full(10, 0.05)]
    assert TM.home_states(x, st) == ["추세장"]                  # 보통 has < 30 trades
    assert TM.home_states(np.r_[np.full(40, 0.02), np.full(40, 0.02), np.zeros(10)], st) is None   # no state > overall
    assert TM.home_states(np.full(90, -0.01), st) is None


def test_persistence_bootstrap_and_team():
    rng = np.random.default_rng(3)
    n = 400
    close = R.PERIOD_MS[R.P_TEST][1] + np.sort(rng.integers(0, 600 * DAY, n))
    inside = rng.random(n) < 0.5
    x = np.where(inside, 0.02, -0.01) + rng.normal(0, 0.005, n)
    p = TM.boot_diff_p(TM.week_of(close), x, inside, "t")
    assert p < 0.01
    assert TM.boot_diff_p(TM.week_of(close), -x, inside, "t") > 0.9
    w = TM.weekly_sums(close, x, R.PERIOD_MS[R.P_TEST][1], R.PERIOD_MS[R.P_TEST][2])
    assert abs(w.sum() - x.sum()) < 1e-9

    def mb(st, xx, home):
        return {"T": {"pid": np.full(n, R.P_TEST), "close": close, "x": xx}, "state": st, "xf": -xx, "home": home}
    sa = np.where(inside, "추세장", "횡보장")
    a = mb(sa, np.where(inside, 0.02, -0.01), ["추세장"])
    b = mb(sa, np.where(inside, -0.01, 0.02), ["횡보장"])
    t = TM.team_test(a, b, "team")
    assert all(t["beats"].values()) and t["p"] < 0.01 and t["n"] == n
