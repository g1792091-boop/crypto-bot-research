"""research/fullgrid/run.py end to end on synthetic 1m bars of the six coins (short periods, one timeframe, two
cells): outcomes -> grid -> select -> confirm -> report -> pack, and the grid statistics equal a direct recount."""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
pytest.importorskip("numba")

MIN = 60_000
T0 = 1_577_836_800_000            # 2020-01-01


def _run_module():
    spec = importlib.util.spec_from_file_location("fullgrid_run", os.path.join(ROOT, "research", "fullgrid", "run.py"))
    R = importlib.util.module_from_spec(spec)
    sys.modules["fullgrid_run"] = R
    spec.loader.exec_module(R)
    return R


def _synth(d: str, days: int = 100) -> None:
    os.makedirs(os.path.join(d, "1m"), exist_ok=True)
    for k, sym in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")):
        rng = np.random.default_rng(k)
        n = days * 1440
        r = rng.normal(0, 0.0006, n) + 0.0002 * np.sin(np.arange(n) / 3000)
        c = (100.0 * (k + 1)) * np.exp(np.cumsum(r))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0005, n)))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0005, n)))
        ts = T0 + np.arange(n, dtype=np.int64) * MIN
        fund = np.where(ts % (8 * 3_600_000) == 0, 1e-4, 0.0)
        np.savez(os.path.join(d, "1m", f"{sym}.npz"), ts=ts, o=o, h=h, l=lo, c=c, v=rng.uniform(1, 10, n),
                 mo=o, mh=h, ml=lo, mc=c, fund=fund)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("fg")
    data, out = str(base / "data"), str(base / "out")
    _synth(data)
    R = _run_module()
    R.TFS = ("1h",)
    R.WARMUP_BARS = 60
    day = 86_400_000
    R.PERIOD_MS = [("select", T0 + 30 * day, T0 + 65 * day), ("test", T0 + 65 * day, T0 + 100 * day),
                   ("extra", T0 + 3 * day, T0 + 30 * day)]
    R.MIN_SELECT, R.MIN_TEST, R.MIN_EXTRA, R.N_BOOT = 10, 10, 1, 200
    R.FRAME_DIR[0] = os.path.join(out, "frames")
    full = R.cell_grid

    def small(kind, name):
        ps, vals, combos = full(kind, name)
        if name == "S2_ST_ROC":
            combos = tuple(c for c in combos if c["st_atr_len"] == 10)
        return ps, vals, combos
    R.cell_grid = small
    R.cells = lambda only="": [("core", "S2_ST_ROC", "1h"), ("ds", "F17_Z", "1h")]
    ex = R.exchange(None, True)
    R.stage_outcomes(data, out, 2, ex)
    R.stage_grid(data, out, 2)
    sel = R.stage_select(out)
    con = R.stage_confirm(data, out, ex)
    rep = R._load("fullgrid_report", os.path.join(R.HERE, "report.py"))
    text = rep.write(out)
    dest = rep.pack(out, R)
    return R, data, out, sel, con, text, dest


def test_every_stage_writes_its_files(world):
    R, data, out, sel, con, text, dest = world
    assert len([f for f in os.listdir(os.path.join(out, "outcomes")) if f.endswith(".npz")]) == 6
    assert not sel["missing"] and len(sel["cells"]) == 2
    for f in ("RESULTS_KO.md", "select.json", "confirm.json", "candidates.csv", "cells.csv", "grid_stats.npz", "grids.json"):
        assert os.path.exists(os.path.join(dest, f)), f
    assert "## 결론" in text and "규칙봇 36개" in text
    assert con["family"] == len(sel["picks"])
    for r in con["rows"]:
        assert set(r["checks"]) == {"test_trades", "test_positive", "test_beats_default", "test_fdr", "extra_trades",
                                    "extra_positive"}
        assert r["pass"] == all(r["checks"].values())
        if r["pass"]:
            assert r["account"]["pick"]["trades"] > 0


def test_grid_stats_equal_a_direct_recount(world):
    R, data, out, *_ = world
    E = len(R.K.EXITS)
    for kind, name in (("core", "S2_ST_ROC"), ("ds", "F17_Z")):
        st = R.cell_stats(out, kind, name, "1h")
        assert st.shape[1:] == (E, 3, 4)
        combos = R.cell_grid(kind, name)[2]
        for r in (0, R.default_row(kind, name), len(combos) - 1):
            for e in (0, 1, 13, E - 1):
                T = R.combo_trades(data, out, kind, name, "1h", combos[r], e)
                for k in range(3):
                    x = T["x"][T["pid"] == k]
                    assert st[r, e, k, 0] == len(x)
                    assert abs(st[r, e, k, 1] - x.sum()) < 1e-5
                    assert st[r, e, k, 3] == (x > 0).sum()


def test_exit_variants_differ(world):
    R, data, out, *_ = world
    st = R.cell_stats(out, "core", "S2_ST_ROC", "1h")
    r0 = R.default_row("core", "S2_ST_ROC")
    sums = st[r0, :, 0, 1]
    assert len(set(np.round(sums, 9))) > 20          # 36 exit rules give different results


def test_plateau_is_the_neighbourhood_median(world):
    R, data, out, sel, *_ = world
    kind, name = "core", "S2_ST_ROC"
    st = R.cell_stats(out, kind, name, "1h")
    mean, plat = R.plateau_scores(kind, name, st)
    ps, vals, combos = R.cell_grid(kind, name)
    ok = st[:, :, 0, 0] >= R.MIN_SELECT
    if not np.isfinite(plat).any():
        pytest.skip("no pair with enough trades on the synthetic series")
    r, e = np.unravel_index(np.nanargmax(np.where(np.isfinite(plat), plat, -np.inf)), plat.shape)
    c = combos[r]
    idx = [vals[j].index(R._hashable(c[p["name"]])) for j, p in enumerate(ps)]
    xs = [mean[r, e]]
    for j in range(len(ps)):
        for d in (-1, 1):
            k = idx[j] + d
            if 0 <= k < len(vals[j]):
                q = [i for i, cc in enumerate(combos) if all(
                    R._hashable(cc[p["name"]]) == (vals[jj][k] if jj == j else R._hashable(c[p["name"]]))
                    for jj, p in enumerate(ps))]
                if q:
                    xs.append(mean[q[0], e] if ok[q[0], e] else 0.0)
    _n, k_stop, m, lk = R.K.EXITS[e]
    stops = sorted(kk for _nn, kk, mm, ll in R.K.EXITS if mm == m and ll == lk)
    i = stops.index(k_stop)
    for d in (-1, 1):
        if 0 <= i + d < len(stops):
            f = [jj for jj, (_nn, kk, mm, ll) in enumerate(R.K.EXITS) if mm == m and ll == lk and kk == stops[i + d]][0]
            xs.append(mean[r, f] if ok[r, f] else 0.0)
    assert abs(plat[r, e] - np.median(xs)) < 1e-12
    picks = [p for p in sel["picks"] if p["name"] == name]
    assert all(p["plateau"] > 0 for p in picks)
    assert all(p["exit"] == R.K.EXITS[p["exit_index"]][0] for p in picks)


def test_rerun_skips_finished_work(world):
    R, data, out, *_ = world
    assert all(os.path.exists(R.task_path(out, t)) for t in R.plan())
    assert R.grid_job((data, out, R.plan()[0])) == ""
