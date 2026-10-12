"""research/hiwr/hiwr.py (PREREG_HIWR.md 17.1 tests of the command line): the control groups of section 11 (joint
flips per signal bar and side; random-time clusters moved whole, without replacement, with the at-least-one fallback),
the seeds and the p_boot bootstrap against slow loops, BH and Holm, the selection rules of 10.2-10.5 on synthetic sums,
the picks-hash ordering guard (no TEST byte before the picks line), D11 on every public output, pinlist determinism
(fresh processes), and an end-to-end datapin -> datacheck -> select -> test -> reads -> report on SYNTHETIC coins and
short synthetic periods (monkeypatched). No real price is read anywhere in this file."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
pytest.importorskip("numba")

from research.hiwr import acct as A  # noqa: E402
from research.hiwr import data as D  # noqa: E402
from research.hiwr import hiwr as H  # noqa: E402
from research.hiwr import walk as W  # noqa: E402

R = D.fg_run()
MIN = 60_000
HOUR = 3_600_000


# ------------------------------------------------------------------ control (a): coin flips per (bar, side)
def _toy_candidates(seed, n=400, bars=60):
    rng = np.random.default_rng(seed)
    close = D.ms("2024-02-05") + rng.integers(0, bars, n) * 4 * HOUR
    side = rng.integers(0, 2, n)
    rk = np.where(rng.random(n) < 0.8, rng.normal(0.001, 0.004, n), np.nan)
    rv = np.where(rng.random(n) < 0.8, rng.normal(-0.001, 0.004, n), np.nan)
    return close, side, rk, rv


def test_coin_flips_are_joint_per_signal_bar_and_side():
    close, side, rk, rv = _toy_candidates(1)
    grp, G = H.flip_groups(close, side)
    assert G == len({(int(c), int(s)) for c, s in zip(close, side)})
    flipped_any = set()
    for s in range(1, 30):
        sides = H.flip_sides(grp, side, G, "TEST", "x|4h|0|L30|TP0.39|1ATR|maker", s)
        flip = sides != side
        for g in range(G):
            m = grp == g
            assert flip[m].all() or not flip[m].any()            # a group flips whole
            flipped_any.add(bool(flip[m][0]))
        # the same bar, other side: an independent coin (not always equal over seeds)
    assert flipped_any == {True, False}
    # two groups at one bar (long and short) differ in some seed
    bar = int(close[0])
    gl = {int(grp[i]) for i in np.flatnonzero((close == bar) & (side == 0))}
    gs = {int(grp[i]) for i in np.flatnonzero((close == bar) & (side == 1))}
    if gl and gs:
        g1, g2 = gl.pop(), gs.pop()
        d = [H.flip_draw(G, "TEST", "p", s)[[g1, g2]] for s in range(1, 40)]
        assert any(a != b for a, b in d)


def test_flip_control_matches_a_slow_loop_and_the_seed_formula():
    close, side, rk, rv = _toy_candidates(2)
    grp, G = H.flip_groups(close, side)
    pid = "S4_BB_BBP|4h|17|L30|TP0.44|1%|maker"
    fl = H.flip_control(rk, rv, grp, G, "TEST", pid, range(1, 301))
    import hashlib
    for s in (1, 7, 300):
        seed = int.from_bytes(hashlib.sha256(f"hiwr|a|TEST|{pid}|{s}".encode()).digest()[:8], "little")
        F = np.random.Generator(np.random.PCG64(seed)).integers(0, 2, G)
        r = np.where(F[grp] == 1, rv, rk)
        ok = np.isfinite(r)
        assert abs(fl["mean"][s - 1] - r[ok].mean()) < 1e-12
        assert abs(fl["win"][s - 1] - (r[ok] > 0).mean()) < 1e-12
        assert fl["n"][s - 1] == ok.sum()
    assert abs(fl["obs"] - np.nanmean(rk)) < 1e-12
    p = H.p_seeds(fl["mean"], fl["obs"])
    assert p == (1 + int((fl["mean"] >= fl["obs"]).sum())) / 301
    # a seed with no trade is never counted as >= the pick
    assert H.p_seeds(np.array([np.nan, np.nan, 0.5]), 0.1) == 2 / 4


# ------------------------------------------------------------------ control (b): random times, whole clusters
def _toy_time(seed, ncoins=4, G=300, pmiss=0.3):
    rng = np.random.default_rng(seed)
    take = rng.random((2 * ncoins, G)) > pmiss
    take[2 * (ncoins - 1)] = rng.random(G) < 0.03          # one sparse coin-side: fallback lists
    rr = np.where(take, rng.normal(0.0, 0.004, take.shape), np.nan)
    clusters = []
    for _ in range(40):
        k = int(rng.integers(1, 4))
        clusters.append(sorted(set(rng.choice(2 * ncoins, k, replace=False).tolist())))
    clusters.append([2 * (ncoins - 1), 0])                 # a cluster that needs the fallback
    return take, rr, clusters


def test_random_time_clusters_move_whole_without_replacement():
    take, rr, clusters = _toy_time(3)
    setup = H.time_setup(clusters, take)
    assert setup["fallback_clusters"] >= 1
    pid = "N20_EMA9_CHOP|1h|3|L50|TP0.42|1ATR|maker"
    tc = H.time_control(setup, take, rr, "TEST", pid, range(1, 201), keep_chosen=200)
    for i in range(200):
        ch = tc["chosen"][i]
        got = ch[ch >= 0]
        assert len(set(got.tolist())) == len(got)            # no bar twice within a seed
        s = n = w = dm = 0
        for j, (mem, g) in enumerate(zip(clusters, ch)):
            key = tuple(sorted(mem))
            strict = np.flatnonzero(take[list(key)].all(axis=0))
            if g < 0:
                dm += len(mem)
                continue
            if len(strict) >= H.TIME_MIN_BARS:
                assert take[mem, g].all()                    # every member takeable at the drawn bar
            else:
                assert take[mem, g].any()                    # fallback: at least one
            for m in mem:                                    # the whole cluster moves to one bar
                if take[m, g]:
                    s += rr[m, g]
                    n += 1
                    w += rr[m, g] > 0
                else:
                    dm += 1
        assert n == tc["n"][i] and dm == tc["dropped_members"][i]
        assert abs(tc["mean"][i] - s / n) < 1e-12 and abs(tc["win"][i] - w / n) < 1e-12
    # deterministic, and the first draw of each seed is uniform over its list
    tc2 = H.time_control(setup, take, rr, "TEST", pid, range(1, 201), keep_chosen=200)
    assert np.array_equal(tc["chosen"], tc2["chosen"]) and np.allclose(tc["mean"], tc2["mean"], equal_nan=True)


def test_random_time_stream_extension_keeps_the_draws(monkeypatch):
    """A seed whose uniform stream runs out is redrawn with a longer stream from the same seed; PCG64's longer stream
    starts with the same numbers, so the result does not depend on the first stream length."""
    g = A.rng_for("b", "TEST", "x", 5)
    a = g.random(10)
    b = A.rng_for("b", "TEST", "x", 5).random(1000)
    assert np.array_equal(a, b[:10])
    take = np.ones((2, 25), bool)
    rr = np.ones((2, 25)) * 0.001
    clusters = [[0]] * 25                                    # 25 clusters over 25 bars: many rejections at the end
    setup = H.time_setup(clusters, take)
    t1 = H.time_control(setup, take, rr, "TEST", "x", range(1, 50), keep_chosen=49)
    for row in t1["chosen"]:
        assert sorted(row.tolist()) == list(range(25))       # every bar once
    assert (t1["dropped_clusters"] == 0).all()


# ------------------------------------------------------------------ p_boot, BH, Holm
def test_p_boot_matches_a_slow_loop():
    rng = np.random.default_rng(4)
    n = 300
    close = np.sort(D.ms("2024-01-01") + rng.integers(0, 100 * 7 * 86_400_000, n))
    r = rng.normal(0.0004, 0.004, n)
    pid = "S4|4h|0|L30|TP0.39|1ATR|maker"
    p = H.p_boot(close, r, "TEST", pid, n_boot=3000)
    wk = (close - W.MONDAY0) // W.WEEK
    weeks = np.unique(wk)
    g = A.rng_for("boot", "TEST", pid, "boot")
    idx = g.integers(0, len(weeks), size=(3000, len(weeks)))
    bad = 0
    for row in idx:
        sel = np.concatenate([np.flatnonzero(wk == weeks[k]) for k in row])
        bad += not (r[sel].mean() > 0)
    assert p == (1 + bad) / 3001
    assert H.p_boot(close, np.abs(r) + 1e-6, "TEST", pid, n_boot=500) == 1 / 501       # floor
    assert H.p_boot([], [], "TEST", pid) == 1.0


def test_bh_and_holm():
    rng = np.random.default_rng(6)
    for _ in range(50):
        m = int(rng.integers(1, 30))
        p = list(np.where(rng.random(m) < 0.3, rng.random(m) * 0.01, rng.random(m)))
        if m > 2:
            p[0] = None
        got = H.bh(p, 0.10)
        ix = [i for i, x in enumerate(p) if x is not None]
        srt = sorted(ix, key=lambda i: p[i])
        k = max([r for r, i in enumerate(srt, 1) if p[i] <= 0.10 * r / len(ix)] or [0])
        assert got == [i in srt[:k] for i in range(m)]
    assert H.holm([0.01, 0.04, 0.03, None], 0.05) == [True, False, False, False]
    assert H.holm([0.01, 0.02, 0.025], 0.05) == [True, True, True]
    # T0 failures enter BH with p = 1
    blocks = [{"id": f"p{i}", "p": 1e-5, "checks": {"T0": i != 1, "T1": True, "T2": True, "T3": True, "T4": True,
                                                    "T5": True}, "test": {"mean": 0.001},
               "seed_means": {"a": -0.001, "b": -0.001}} for i in range(3)]
    vd = H.verdict(blocks)
    assert vd["passing"] == ["p0", "p2"] and not blocks[1]["checks"]["PASS"]


# ------------------------------------------------------------------ selection rules on synthetic sums (10.2-10.5)
def _sums(n, w, s, s2):
    return np.stack([n, w, s, n, s2, w], axis=-1).astype(float)


def test_exit_neighbours_and_thinned_rule():
    cfgs = W.exit_configs()
    nb = H.exit_neighbours(cfgs)
    c0 = next(i for i, c in enumerate(cfgs) if c["L"] == 30 and c["step"] == 1 and c["k"] == 0 and c["fill"] == 1)
    got = sorted((cfgs[j]["step"], cfgs[j]["k"]) for j in nb[c0])
    assert got == [(0, 0), (1, 1), (2, 0)]                   # TP up/down, ATR 1 -> 1.5 only (family edge)
    c4 = next(i for i, c in enumerate(cfgs) if c["L"] == 30 and c["step"] == 0 and c["k"] == 4 and c["fill"] == 0)
    assert sorted((cfgs[j]["step"], cfgs[j]["k"]) for j in nb[c4]) == [(0, 5), (1, 4)]   # 0.60% has no narrower
    for i, c in enumerate(cfgs):
        for j in nb[i]:
            assert (cfgs[j]["Li"], cfgs[j]["fill"]) == (c["Li"], c["fill"])
    # one combo, every pair passes B except the neighbours we thin
    nc = len(cfgs)
    n = np.full((3, nc), 200.0)
    w = n * 0.8
    s = n * 0.001
    s2 = n * 0.0004
    S = _sums(n, w, s, s2)
    cnb = [np.array([-1, 0, 1]), np.array([1, 2, -1])]
    out = H.cell_pairs(S, cnb, cfgs)
    assert out["pass_abc"] == 3 * nc
    j = nb[c0][0]
    for nn, ss2, wr, ok in ((100.0, 0.0001, 0.6, True), (100.0, -0.0001, 0.9, False), (40.0, -0.01, 0.5, True),
                            (160.0, 0.0001, 0.6, False), (160.0, 0.0001, 0.9, True)):
        S2 = S.copy()
        S2[1, j] = _sums(np.array(nn), np.array(nn * wr), np.array(nn * 0.001), np.array(nn * ss2))
        o = H.cell_pairs(S2, cnb, cfgs)
        ids = {(p["row"], p["ci"]) for p in o["abc"]}
        assert ((1, c0) in ids) == ok, (nn, ss2, wr)


def test_number_plateau_and_plateau_score():
    cfgs = W.exit_configs()
    nc = len(cfgs)
    n = np.full((5, nc), 200.0)
    S = _sums(n, n * 0.8, n * 0.001, n * 0.0004)
    S[4, :, 2] = -1.0                                        # combo 4 fails B (mean < 0) on every exit
    S[3, :, 0] = S[3, :, 3] = 120.0                         # combo 3 has 120 trades: fails B, counts 0 in the score
    S[3, :, 1] = S[3, :, 5] = 100.0
    cnb = [np.array([-1, 0, 1, 2, 3]), np.array([1, 2, 3, 4, -1])]
    out = H.cell_pairs(S, cnb, cfgs)
    assert {p["row"] for p in out["abc"]} == {0, 1, 2}      # combo 2: 1 of 2 neighbours passes = half
    ex = H.exit_neighbours(cfgs)[0]
    p2 = next(p for p in out["abc"] if p["row"] == 2 and p["ci"] == 0)
    assert p2["plateau"] == pytest.approx(np.median([0.001] * (2 + len(ex)) + [0.0]))
    p0 = next(p for p in out["abc"] if p["row"] == 0 and p["ci"] == 0)
    assert p0["plateau"] == pytest.approx(0.001)
    # one combo of five: (c) with no number neighbour at all holds
    one = H.cell_pairs(S[:1], [], cfgs)
    assert one["pass_abc"] == one["pass_B"] == nc


def test_choose_pick_ties():
    rs = [{"row": 3, "ci": 5, "plateau": 0.002, "eligible": True, "d": {"mean_ln": 0.01}},
          {"row": 1, "ci": 9, "plateau": 0.002, "eligible": True, "d": {"mean_ln": 0.02}},
          {"row": 0, "ci": 0, "plateau": 0.002, "eligible": True, "d": {"mean_ln": 0.02}},
          {"row": 0, "ci": 1, "plateau": 0.003, "eligible": False, "d": {"mean_ln": 0.5}}]
    assert (H.choose_pick(rs)["row"], H.choose_pick(rs)["ci"]) == (0, 0)
    assert H.choose_pick([dict(rs[3])]) is None


# ------------------------------------------------------------------ D11
def test_d11_checker():
    ds = {"F17_Z|1h|3|L30|TP0.39|1ATR|maker"}
    good = {"cells": [{"kind": "ds", "name": "F17_Z", "pass_B": 4, "pick": "F17_Z|1h|3|L30|TP0.39|1ATR|maker",
                       "pick_counts": {"n": 200, "win": 0.81}}],
            "picks": [{"id": next(iter(ds)), "kind": "ds", "exit": {"t": 0.0039, "roe": 0.09}, "combo": {"a": 1.5},
                       "cap": 0.3, "sel": "private (D11)"}]}
    assert H.d11_problems(good, ds) == []
    bad = json.loads(json.dumps(good))
    bad["cells"][0]["pick_counts"]["mean"] = 0.001
    bad["picks"][0]["f_star"] = 3.2
    assert len(H.d11_problems(bad, ds)) == 2
    assert H.d11_problems({"results": {next(iter(ds)): {"p": 0.01}}}, ds) == ["out.results." + next(iter(ds)) + ".p"]
    assert H.d11_problems({"kind": "ds", "lnM": [0.1, 0.2]}, ds)
    line_ok = "| F17_Z (딥시크) | 1시간 | 실패 | 120 | 71.0% | 비공개 | 비공개 | 못 넘음 |"
    assert H.report_d11_problems(line_ok) == []
    assert H.report_d11_problems(line_ok.replace("| 비공개 | 비공개 |", "| 0.10% | 12.0% |"))


# ------------------------------------------------------------------ pinlist (17.3)
def test_pinlist_is_deterministic_in_fresh_processes():
    a = H.required_files()
    H._REQUIRED.clear()
    b = H.required_files()
    assert a == b and a == sorted(a)
    __import__("importlib").import_module("research.hunt")    # an extra module loaded here changes nothing
    H._REQUIRED.clear()
    assert H.required_files() == a
    cli = subprocess.run([sys.executable, "-m", "research.hiwr.hiwr", "pinlist"], cwd=ROOT, capture_output=True,
                         text=True, timeout=900)
    assert cli.returncode == 0 and cli.stdout.split() == a
    must = {"research/hiwr/PREREG_HIWR.md", "research/hiwr/hiwr.py", "research/hiwr/data.py", "research/hiwr/walk.py",
            "research/hiwr/acct.py", "research/fullgrid/run.py", "research/fullgrid/exchange.json",
            "research/fullgrid/ds_defs.py", "research/entry_study/DEFS_BC.sha256", "research/hunt/universe30.json",
            "research/hunt/exchange30.json", "research/hiwr/data_manifest_sel.json",
            "research/hiwr/data_check_sel.json", "tests/test_hiwr_cli.py", "tests/test_hiwr_core.py"}
    assert must <= set(a)
    assert "research/hiwr/reads.py" not in a and not [p for p in a if p.startswith("tests/") and "hiwr" not in p]
    assert any(p.startswith("research/entry_study/param_defs/") for p in a)
    assert "paperbot/margin.py" in a


# ------------------------------------------------------------------ the end-to-end world (synthetic)
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
PRICE = {"BTCUSDT": 30000.0, "ETHUSDT": 2000.0, "SOLUSDT": 50.0}
UP_HOURS, DOWN_HOURS = (4, 10, 16, 22), (1, 7, 13, 19)
T_START, T_SPLIT, T_END = D.ms("2020-11-02"), D.ms("2021-03-01"), D.ms("2021-04-26")


def _coin(sym, k):
    """1m bars with a planted move: +1% over the 90 minutes after every 1h close at 04/10/16/22 UTC and -1% after
    01/07/13/19 UTC, small noise, 8 h funding."""
    rng = np.random.default_rng(100 + k)
    ts = np.arange(T_START, T_END, MIN, dtype=np.int64)
    n = len(ts)
    mod = (ts // MIN) % 1440
    drift = np.zeros(n)
    for hh in UP_HOURS:
        drift[(mod >= hh * 60) & (mod < hh * 60 + 90)] = 0.01 / 90
    for hh in DOWN_HOURS:
        drift[(mod >= hh * 60) & (mod < hh * 60 + 90)] = -0.01 / 90
    lr = drift + rng.normal(0, 0.0003, n)
    c = PRICE[sym] * np.exp(np.cumsum(lr))
    o = np.r_[PRICE[sym], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.00015, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.00015, n)))
    fund = np.where(ts % (8 * HOUR) == 0, 1e-4, 0.0)
    return {"ts": ts, "o": o, "h": h, "l": lo, "c": c, "v": np.ones(n), "qv": c.copy(), "mo": o.copy(),
            "mh": h.copy(), "ml": lo.copy(), "mc": c.copy(), "fund": fund}


def _write_kit(d, arrays_of, months):
    os.makedirs(os.path.join(d, "1m"), exist_ok=True)
    rows = []
    for s, a in arrays_of.items():
        np.savez(os.path.join(d, "1m", f"{s}.npz"), **a)
        rows.append({"symbol": s, "months": list(months), "minutes": int(len(a["ts"])), "first": H.iso(a["ts"][0]),
                     "last": H.iso(a["ts"][-1]), "last_ms": int(a["ts"][-1]), "ended": False,
                     "content_sha256": D.content_sha(a), "problems": []})
    with open(os.path.join(d, "build.json"), "w") as fh:
        json.dump({"months": list(months), "symbols": rows, "problems": []}, fh)


def _fake_grid():
    ps = ({"name": "w", "default": 3, "kind": "length"},)
    return ps, ((2, 3, 4),), ({"w": 2}, {"w": 3}, {"w": 4})


def _fake_signals(kind, name, sym, tf, combo):
    df, close = H.frame(sym, tf)
    hour = (close // HOUR) % 24
    up = np.isin(hour, UP_HOURS) & (close > 0) & (combo["w"] > 0)
    dn = np.isin(hour, DOWN_HOURS)
    if kind == "core":
        return up, np.zeros(len(close), bool)
    return np.zeros(len(close), bool), dn


class Args:
    def __init__(self, **kw):
        self.__dict__.update(dict(kit=None, kit_test=None, fg1m=None, hunt5m=None, work=None, private=None, procs=2,
                                  eligibility="lazy", ledger_extra=None, hunt_private=None, no_reads=False,
                                  reads_hours=None))
        self.__dict__.update(kw)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("hiwr_e2e")
    mp = pytest.MonkeyPatch()
    t0 = time.time()
    state = str(base / "state")
    os.makedirs(os.path.join(state, "research", "hiwr"), exist_ok=True)
    mp.setattr(H, "STATE", [state])
    mp.setattr(H, "PIN_REL", "research/hiwr/pin_e2e.txt")
    mp.setattr(H, "SYMBOLS", SYMS)
    mp.setattr(H, "TFS", ("1h",))
    mp.setitem(D.PERIODS, "SEL", (D.ms("2021-01-04"), T_SPLIT))
    mp.setitem(D.PERIODS, "TEST", (T_SPLIT, T_END))
    mp.setitem(D.PERIODS, "EXTRA", (D.ms("2020-12-07"), D.ms("2021-01-04")))
    mp.setattr(D, "KIT_SEL", ("2020-11", "2021-02"))
    mp.setattr(D, "KIT_TEST", ("2021-03", "2021-04"))
    mp.setattr(R, "WARMUP_BARS", 60)
    mp.setattr(R, "CHUNK", 2)                            # two grid tasks per cell
    mp.setattr(H, "ELIG_PAIRS", {"1h": 150})
    l30 = [c for c in W.exit_configs() if c["L"] == 30 and c["fill"] == 1]     # 27 exits (30x, maker): fewer pairs
    mp.setattr(H, "exit_configs", lambda: [dict(c) for c in l30])
    mp.setattr(H, "N_SEEDS", 2000)
    mp.setattr(H, "N_ACCT_SEEDS", 20)
    mp.setattr(H, "N_PBOOT", 2000)
    mp.setattr(H, "N_F95", 200)
    mp.setattr(H, "cells_all", lambda: [("core", "SYN_A", "1h"), ("ds", "SYN_DS", "1h")])
    mp.setattr(H, "cell_grid", lambda kind, name: _fake_grid())
    mp.setattr(H, "combo_neighbours", lambda kind, name: [np.array([-1, 0, 1]), np.array([1, 2, -1])])
    mp.setattr(H, "raw_signals", _fake_signals)
    hman = str(base / "hunt_manifest.json")
    mp.setattr(H, "HUNT_MANIFEST_REL", hman)
    mp.setattr(H, "HUNT_TESTS", ())
    H._FRAMES[0] = None
    prereg = "research/hiwr/out/PREREG_copy.md"               # a copy: editing the real file mid-run changes nothing
    os.makedirs(os.path.dirname(os.path.join(state, prereg)), exist_ok=True)
    with open(os.path.join(ROOT, H.PREREG_REL)) as src, open(os.path.join(state, prereg), "w") as dst:
        dst.write(src.read())
    mp.setattr(H, "PREREG_REL", prereg)
    req = [H.PREREG_REL, H.MANIFEST_SEL_REL, H.CHECK_SEL_REL]
    mp.setattr(H, "required_files", lambda: list(req))
    calls = []
    arrays = {s: _coin(s, k) for k, s in enumerate(SYMS)}
    sel_kit, test_kit = str(base / "kit"), str(base / "kit_test")
    cut = {s: {k: v[a["ts"] < T_SPLIT] for k, v in a.items()} for s, a in arrays.items()}
    _write_kit(sel_kit, cut, D.KIT_SEL)

    def fake_fetch(d, syms):
        listed = [p for _h, p in H.read_pin()]
        calls.append({"dir": d, "syms": list(syms), "picks_pinned": H.PICKS_REL in listed,
                      "marker": os.path.exists(os.path.join(d, H.TEST_KIT_MARK))})
        _write_kit(d, {s: {k: v[arrays[s]["ts"] >= T_SPLIT] for k, v in arrays[s].items()} for s in syms},
                   D.KIT_TEST)
    mp.setattr(H, "fetch_test_kit", fake_fetch)
    work, private = str(base / "work"), str(base / "private")
    # datapin, datacheck (fg1m = the same bars; the hunt's 5m = the bars resampled, with their pinned hash)
    assert H.main(["datapin", "--kit", sel_kit]) == 0
    fg = str(base / "fg1m")
    _write_kit(fg, cut, D.KIT_SEL)
    h5 = str(base / "hunt")
    os.makedirs(os.path.join(h5, "5m"))
    content = {}
    for s, a in cut.items():
        r5 = D.resample_5m(a)
        f5 = {k: np.asarray(r5[k]) for k in ("ts", "o", "h", "l", "c", "v", "qv")}
        np.savez(os.path.join(h5, "5m", f"{s}.npz"), **f5)
        content[s] = {"5m": D.content_sha(f5, ("ts", "o", "h", "l", "c", "v", "qv"))["all"]}
    with open(hman, "w") as fh:
        json.dump({"content": content}, fh)
    assert H.main(["datacheck", "--kit", sel_kit, "--fg1m", fg, "--hunt5m", h5]) == 0
    # the pin (a test file name, never a *.sha256)
    with open(H.rpath(H.PIN_REL), "w") as fh:
        for rel in req:
            fh.write(f"{H.sha256_file(H.rpath(rel))}  {rel}\n")
    # guard: test before select refuses and fetches nothing
    rc_early = H.main(["test", "--kit", sel_kit, "--kit-test", test_kit, "--work", work, "--private", private])
    fetched_early = list(calls)
    t1 = time.time()
    assert H.main(["select", "--kit", sel_kit, "--work", work, "--private", private, "--procs", "2",
                   "--eligibility", "all"]) == 0
    t_select = time.time() - t1
    pin_after_select = H.read_pin()
    t2 = time.time()
    assert H.main(["test", "--kit", sel_kit, "--kit-test", test_kit, "--work", work, "--private", private,
                   "--procs", "2"]) == 0
    t_test = time.time() - t2
    assert H.main(["report"]) == 0
    out = {"base": str(base), "state": state, "sel_kit": sel_kit, "test_kit": test_kit, "work": work,
           "private": private, "calls": calls, "rc_early": rc_early, "fetched_early": fetched_early,
           "pin_after_select": pin_after_select, "seconds": {"select": t_select, "test_reads": t_test,
                                                              "total": time.time() - t0}}
    print(f"\n[hiwr e2e] select {t_select:.0f}s, test+reads {t_test:.0f}s, total {time.time() - t0:.0f}s")
    yield out
    mp.undo()
    H._FRAMES[0] = None
    R.frame.cache_clear()
    H.CTX.clear()


def _load(world, name):
    return json.load(open(os.path.join(world["state"], H.OUT_REL, name)))


def test_e2e_select_picks_and_counts(world):
    sel = _load(world, "select.json")
    cells = {c["name"]: c for c in sel["cells"]}
    assert set(cells) == {"SYN_A", "SYN_DS"}
    for c in cells.values():
        assert c["combos"] == 3 and c["pass_B"] > 0 and c["pass_abc"] > 0 and c["eligible"] > 0
        assert c["evaluated_d_e"] == c["pass_abc"] and not c["counts_partial"]
        assert c["pick"] != "none"
        assert c["candidates_weekend_dropped"] > 0
    priv_cells = json.load(open(os.path.join(world["private"], "select_private.json")))["cells"]
    for pc in priv_cells:
        el = [r for r in pc["results"] if r["eligible"]]
        top = max(r["plateau"] for r in el)
        best = sorted([r for r in el if r["plateau"] == top], key=lambda r: (-r["d"]["mean_ln"], r["row"], r["ci"]))
        assert pc["pick"] == best[0]["id"] == H.choose_pick(pc["results"])["id"]
        assert all(r["d"]["f_star"] <= r["d"]["f_path"] + 1e-12 for r in pc["results"] if r["d"].get("f_star"))
    picks = json.load(open(os.path.join(world["state"], H.PICKS_REL)))["picks"]
    assert [p["id"] for p in picks] == sel["picks"]
    core = next(p for p in picks if p["kind"] == "core")
    ds = next(p for p in picks if p["kind"] == "ds")
    assert core["f_star"] > 0 and 0 < core["sel"]["f_star"] <= core["exit"]["L"] ** 2 / 100
    assert ds["f_star"] is None and ds["private"] and ds["sel"] == "private (D11)"
    priv = json.load(open(os.path.join(world["private"], "picks_private.json")))["picks"]
    assert priv[ds["id"]]["sel"]["f_star"] > 0
    # the picks line was appended by select, once, last
    rows = world["pin_after_select"]
    assert rows[-1][1] == H.PICKS_REL and sum(1 for _h, p in rows if p == H.PICKS_REL) == 1


def test_e2e_grid_sums_equal_a_direct_recount(world):
    work = [os.path.join(world["work"], d) for d in os.listdir(world["work"]) if d.startswith("select_")][0]
    S, fails, metas = H.cell_sums(work, "core", "SYN_A", "1h")
    assert not fails and len(metas) == 2
    cfgs = H.exit_configs()
    H.CTX["dirs"] = {"frames_SEL": os.path.join(work, "frames"), "tables_SEL": os.path.join(work, "tables")}
    H.use_frames(H.CTX["dirs"]["frames_SEL"])
    tot = {ci: [0, 0.0, 0] for ci in (0, 1, 13, 26)}
    for c, sym in enumerate(SYMS):
        T = H.load_tables(H.table_dir(H.CTX["dirs"]["tables_SEL"], sym, "1h"))
        lo, sh = _fake_signals("core", "SYN_A", sym, "1h", {"w": 3})
        rows, sides = H.cand_rows(T, lo, sh)
        assert not T.weekend[rows].any()
        for ci in tot:
            x = W.trade_list(T, rows, sides, cfgs[ci])
            ok = x["skip"] == 0
            tot[ci][0] += ok.sum()
            tot[ci][1] += x["r"][ok].sum()
            tot[ci][2] += (x["r"][ok] > 0).sum()
    for ci, (n, s, w) in tot.items():
        assert S[1, ci, 0] == n and abs(S[1, ci, 2] - s) < 1e-12 and S[1, ci, 1] == w


def test_e2e_lazy_and_all_give_the_same_pick(world):
    work = [os.path.join(world["work"], d) for d in os.listdir(world["work"]) if d.startswith("select_")][0]
    sel = _load(world, "select.json")
    cfgs = H.exit_configs()
    for kind, name in (("core", "SYN_A"), ("ds", "SYN_DS")):
        S, _f, _m = H.cell_sums(work, kind, name, "1h")
        pr = H.cell_pairs(S, H.combo_neighbours(kind, name), cfgs)
        res = []
        for t in H.elig_tasks(os.path.join(world["base"], "lazy"), [((kind, name, "1h"), pr)], "lazy"):
            assert H._elig_job(t) .startswith(f"{kind} {name}")
            res += json.load(open(H.elig_path(t)))["results"]
        assert len(res) < pr["pass_abc"]                     # lazy stops at the pick's plateau group
        assert H.choose_pick(res)["id"] == next(c["pick"] for c in sel["cells"] if c["name"] == name)


def test_e2e_test_verdict_controls_and_pin_order(world):
    assert world["rc_early"] == 2 and world["fetched_early"] == []        # refused before the picks line
    calls = world["calls"]
    assert len(calls) == 1 and calls[0]["picks_pinned"] and calls[0]["marker"]
    rows = H.read_pin()
    names = [p for _h, p in rows]
    i_p, i_m, i_r = names.index(H.PICKS_REL), names.index(H.MANIFEST_TEST_REL), names.index("research/hiwr/reads.py")
    assert i_p < i_m < i_r == len(names) - 1                  # 17.3 order: picks, confirm manifest, reads
    test = _load(world, "test.json")
    vd = test["verdict"]
    assert vd["picks"] == 2 and sorted(vd["passing"]) == sorted(test["picks"])      # the planted edges pass
    priv = json.load(open(os.path.join(world["private"], "test_private.json")))["results"]
    for pid, b in priv.items():
        assert b["checks"]["T0"] and b["test"]["n"] >= 100 and b["test"]["win"] >= 0.7
        assert b["p_a"] == 1 / (H.N_SEEDS + 1) and b["p_b"] == 1 / (H.N_SEEDS + 1)
        assert b["p"] == max(b["p_a"], b["p_b"], b["p_boot"])
        assert b["controls"]["a"]["seed_mean"] < 0 and b["controls"]["b"]["seed_mean"] < b["test"]["mean"]
        assert b["controls"]["a"]["accounts"]["seeds"] == H.N_ACCT_SEEDS
        assert b["account"]["trades"] > 0 and b["account"]["dd"] <= b["cap"]
    # a second confirm look is refused
    with pytest.raises(SystemExit):
        H.main(["test", "--kit", world["sel_kit"], "--kit-test", world["test_kit"], "--work", world["work"],
                "--private", world["private"]])


def test_e2e_d11_on_every_public_output(world):
    picks = json.load(open(os.path.join(world["state"], H.PICKS_REL)))
    ds_ids = {p["id"] for p in picks["picks"] if p["kind"] == "ds"}
    assert ds_ids
    for name in ("select.json", "test.json", "ledger.json", "reads.json"):
        doc = _load(world, name)
        assert H.d11_problems(doc, ds_ids) == [], name
        assert doc.get("private_sha256")
    assert H.d11_problems(picks, ds_ids) == []
    test = _load(world, "test.json")
    dsb = test["results"][next(iter(ds_ids))]
    assert set(dsb["test"]) == {"n", "win", "liq", "candidates"} and "p" not in dsb
    led = _load(world, "ledger.json")
    assert all("p" not in r for r in led["rows"] if r["deepseek"]) and led["hypotheses"] == 2
    # no hunt file and no list of the other hypotheses here: incomplete, no count from a smaller family (13)
    assert led["status"] == "incomplete" and led["bh_rejections"] is None and led["holm_rejections"] is None
    assert all(r["bh_q10"] is None and r["holm_005"] is None for r in led["rows"]) and led["missing_sources"]
    assert "장부 미완성" in open(os.path.join(world["state"], H.OUT_REL, "RESULTS_KO.md")).read()
    priv = json.load(open(os.path.join(world["private"], "ledger_private.json")))
    assert H.sha256_file(os.path.join(world["private"], "ledger_private.json")) == led["private_sha256"]
    assert all(r["p"] is not None for r in priv["rows"])
    text = open(os.path.join(world["state"], H.OUT_REL, "RESULTS_KO.md")).read()
    assert "(딥시크)" in text and H.report_d11_problems(text) == []
    assert "같은 확인 기간" in text


def test_e2e_reads(world):
    rd = _load(world, "reads.json")
    priv = json.load(open(os.path.join(world["private"], "reads_private.json")))["picks"]
    core = next(p for p in priv.values() if p["kind"] == "core")
    assert core["R9"]["f_star_same"]                          # f* recomputed on SEL equals the registered one
    for k in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12", "R13", "R14"):
        assert k in core
    assert core["R1"]["TEST"]["list"]["n"] > 0 and core["R6"]["list"]["n"] > 0
    assert core["R5"]["old_six"]["TEST"]["n"] == core["R11"]["TEST"]["per_side"]["long"]["n"] + \
        core["R11"]["TEST"]["per_side"]["short"]["n"]
    assert rd["R14_sha256"][core["id"]] == core["R14_sha256"]
    assert len(rd["summary_ko"]) == 2


def test_select_refuses_a_changed_pin(world, monkeypatch):
    monkeypatch.setattr(H, "STATE", [world["state"]])
    monkeypatch.setattr(H, "PIN_REL", "research/hiwr/pin_e2e.txt")
    monkeypatch.setattr(H, "PREREG_REL", "research/hiwr/out/PREREG_copy.md")
    monkeypatch.setattr(H, "required_files", lambda: [H.PREREG_REL, H.MANIFEST_SEL_REL, H.CHECK_SEL_REL])
    with pytest.raises(H.PinError, match="already pinned"):
        H.check_pin("select")
    p = H.rpath(H.CHECK_SEL_REL)
    doc = json.load(open(p))
    doc["pass"] = False
    with open(p, "w") as fh:
        json.dump(doc, fh)
    with pytest.raises(H.PinError, match="changed"):
        H.check_pin("test")


def test_test_kit_folder_with_files_is_refused(tmp_path):
    d = tmp_path / "kit_test"
    (d / "1m").mkdir(parents=True)
    (d / "1m" / "BTCUSDT.npz").write_bytes(b"x")
    with pytest.raises(H.PinError, match="before the picks"):
        H.ensure_test_kit(str(d), "a" * 64, {"pin_sha256": "b" * 64}, {"coins": {}})


def test_pin_lines_cannot_be_superseded_except_reads(tmp_path, monkeypatch):
    state = str(tmp_path)
    os.makedirs(os.path.join(state, "research", "hiwr"))
    monkeypatch.setattr(H, "STATE", [state])
    monkeypatch.setattr(H, "PIN_REL", "research/hiwr/pin_t.txt")
    monkeypatch.setattr(H, "READS_RELS", ("research/hiwr/out/fake_reads.py",))
    monkeypatch.setattr(H, "required_files", lambda: [H.MANIFEST_SEL_REL])
    monkeypatch.setattr(H, "content_problems", lambda: [])
    man = H.rpath(H.MANIFEST_SEL_REL)
    with open(man, "w") as fh:
        fh.write("{}")
    rd = H.rpath("research/hiwr/out/fake_reads.py")
    os.makedirs(os.path.dirname(rd))
    with open(rd, "w") as fh:
        fh.write("a = 1\n")
    with open(H.rpath(H.PIN_REL), "w") as fh:
        fh.write(f"{H.sha256_file(man)}  {H.MANIFEST_SEL_REL}\n")
    H.append_pin("research/hiwr/out/fake_reads.py")
    assert H.check_pin("select")["lines"] == 2
    with open(rd, "w") as fh:
        fh.write("a = 2\n")                                   # a fixed reads module, appended again: superseded
    with pytest.raises(H.PinError, match="changed"):
        H.check_pin("select")
    H.append_pin("research/hiwr/out/fake_reads.py")
    assert H.check_pin("select")["superseded_reads_lines"] == ["research/hiwr/out/fake_reads.py"]
    with open(man, "w") as fh:
        fh.write('{"x": 1}')                                   # any other file: an appended line does not help
    H.append_pin(H.MANIFEST_SEL_REL)
    with pytest.raises(H.PinError, match="changed research/hiwr/data_manifest_sel.json"):
        H.check_pin("select")


# ------------------------------------------------------------------ fixes after the 2026-10-12 review
def test_e2e_proxy_labels_and_wallet_mean(world):
    """Section 4: the proxy coins are labelled in every output; 8.1: the mean in % of the wallet at f* is reported."""
    for name in ("select.json", "test.json", "reads.json"):
        doc = _load(world, name)
        assert "proxy_coins" in doc["data"] and doc["data"]["brackets_sha256"], name
    picks = json.load(open(os.path.join(world["state"], H.PICKS_REL)))
    assert picks["data"]["proxy_table_of"] == "SANDUSDT" and "proxy_coins" in picks["data"]
    assert H.coin_labels(["BTCUSDT", "TOMOUSDT", "WAVESUSDT"])["proxy_coins"] == ["TOMOUSDT", "WAVESUSDT"]
    core = next(p for p in picks["picks"] if p["kind"] == "core")
    assert core["sel"]["mean_wallet_at_f_star"] == pytest.approx(core["sel"]["f_star"] * core["sel"]["mean"])
    test = _load(world, "test.json")
    b = test["results"][core["id"]]
    assert b["test"]["mean_wallet_at_f_star"] == pytest.approx(b["f_star"] * b["test"]["mean"])
    ds = next(p for p in picks["picks"] if p["kind"] == "ds")
    assert "mean_wallet_at_f_star" not in test["results"][ds["id"]]["test"]          # D11


def test_eligibility_files_are_kept_apart_by_mode(world, tmp_path, monkeypatch):
    """A select resumed in the other eligibility mode never reads the first mode's files (it picked another pair and
    lost or doubled pairs before)."""
    monkeypatch.setattr(H, "ELIG_PAIRS", {"1h": 20})
    work = [os.path.join(world["work"], d) for d in os.listdir(world["work"]) if d.startswith("select_")][0]
    cfgs = H.exit_configs()
    S, _f, _m = H.cell_sums(work, "core", "SYN_A", "1h")
    pr = H.cell_pairs(S, H.combo_neighbours("core", "SYN_A"), cfgs)
    cell = [(("core", "SYN_A", "1h"), pr)]
    w2 = str(tmp_path / "w")
    t_all = H.elig_tasks(w2, cell, "all")
    t_lazy = H.elig_tasks(w2, cell, "lazy")
    assert len(t_all) > 1 and len(t_lazy) == 1
    assert H.elig_path(t_all[0]) != H.elig_path(t_lazy[0]) and "elig_all" in H.elig_path(t_all[0])
    assert all(len(t[5]) <= H.ELIG_PAIRS["1h"] for t in t_all)
    # 'all' interrupted after one task, then resumed as 'lazy': lazy computes its own task and picks like a fresh run
    k0 = next(t for t in t_all if t[4] == 0)
    assert H._elig_job(k0).startswith("core SYN_A")
    assert not os.path.exists(H.elig_path(t_lazy[0]))
    assert H._elig_job(t_lazy[0]).startswith("core SYN_A")
    fresh = str(tmp_path / "fresh")
    tf_ = H.elig_tasks(fresh, cell, "lazy")[0]
    H._elig_job(tf_)
    assert H.choose_pick(H.elig_load(t_lazy[0]))["id"] == H.choose_pick(H.elig_load(tf_))["id"]
    # a file made for other pairs or another mode is refused, never mixed in
    doc = json.load(open(H.elig_path(k0)))
    doc["mode"] = "lazy"
    with open(H.elig_path(k0), "w") as fh:
        json.dump(doc, fh)
    with pytest.raises(SystemExit, match="another eligibility mode"):
        H.elig_load(k0)


def test_memory_errors_are_never_a_failed_combo(world, monkeypatch, tmp_path):
    """A MemoryError (or an OS error) inside the signal code stops the task, writes nothing, and is redone; it is never
    recorded as a combo that fails on every coin."""
    work = [os.path.join(world["work"], d) for d in os.listdir(world["work"]) if d.startswith("select_")][0]
    H.CTX["dirs"] = {"frames_SEL": os.path.join(work, "frames"), "tables_SEL": os.path.join(work, "tables")}
    calls = []

    def boom(kind, name, sym, tf, combo):
        calls.append(sym)
        if len(calls) == 2:
            raise MemoryError("cannot allocate")
        return _fake_signals(kind, name, sym, tf, combo)
    monkeypatch.setattr(H, "raw_signals", boom)
    w2 = str(tmp_path / "grid")
    t = ("core", "SYN_A", "1h", 0, 2)
    msg = H._grid_job((w2, t))
    assert msg.startswith("ERROR") and "MemoryError" in msg
    assert not os.path.exists(H.sums_path(w2, t) + ".json")
    monkeypatch.setattr(H, "raw_signals", lambda *a: (_ for _ in ()).throw(ValueError("window too long")))
    msg = H._grid_job((w2, t))                                   # a rule that cannot compute: recorded, no trades
    assert not msg.startswith("ERROR") and json.load(open(H.sums_path(w2, t) + ".json"))["fails"]
    with pytest.raises(MemoryError):
        monkeypatch.setattr(H, "raw_signals", lambda *a: (_ for _ in ()).throw(MemoryError("x")))
        H.eval_pairs("core", "SYN_A", "1h", [{"row": 0, "ci": 0, "n": 1, "mean": 0.0, "plateau": 0.0}])


def test_trade_list_mismatch_message_has_no_figures(world, monkeypatch):
    """The eval_pairs consistency error reaches run.log (published): counts only, never a mean (D11)."""
    work = [os.path.join(world["work"], d) for d in os.listdir(world["work"]) if d.startswith("select_")][0]
    H.CTX["dirs"] = {"frames_SEL": os.path.join(work, "frames"), "tables_SEL": os.path.join(work, "tables")}
    S, _f, _m = H.cell_sums(work, "ds", "SYN_DS", "1h")
    pr = H.cell_pairs(S, H.combo_neighbours("ds", "SYN_DS"), H.exit_configs())
    p = dict(pr["abc"][0], mean=pr["abc"][0]["mean"] + 0.0123)
    with pytest.raises(RuntimeError) as e:
        H.eval_pairs("ds", "SYN_DS", "1h", [p])
    import re
    assert not re.search(r"\d\.\d", str(e.value).split("|maker")[-1].split("|taker")[-1])


def test_select_never_runs_after_the_confirm_look(world, monkeypatch, tmp_path):
    state = str(tmp_path)
    os.makedirs(os.path.join(state, "research", "hiwr", "out"))
    monkeypatch.setattr(H, "STATE", [state])
    monkeypatch.setattr(H, "PIN_REL", "research/hiwr/pin_t.txt")
    monkeypatch.setattr(H, "required_files", lambda: [H.MANIFEST_SEL_REL])
    monkeypatch.setattr(H, "content_problems", lambda: [])
    man = H.rpath(H.MANIFEST_SEL_REL)
    with open(man, "w") as fh:
        fh.write("{}")
    with open(H.rpath(H.PIN_REL), "w") as fh:
        fh.write(f"{H.sha256_file(man)}  {H.MANIFEST_SEL_REL}\n")
    assert H.check_pin("select")["lines"] == 1
    with open(H.out_path("test.json"), "w") as fh:
        fh.write("{}")
    with pytest.raises(H.PinError, match="confirm look happened"):
        H.check_pin("select")
    os.remove(H.out_path("test.json"))
    with open(H.rpath(H.MANIFEST_TEST_REL), "w") as fh:
        fh.write("{}")
    with pytest.raises(H.PinError, match="confirm look happened"):
        H.check_pin("select")


def test_a_pick_without_test_trades_gets_p_1_and_no_T5():
    assert H.p_seeds(np.array([0.1, -0.2, np.nan]), float("nan")) == 1.0
    assert H.p_seeds(np.array([0.1, -0.2]), None) == 1.0
    assert H._pct(float("nan")) == "-" and H._pct(None) == "-" and H._pct(0.123) == "12.3%"
    fl = H.flip_control(np.array([np.nan, np.nan]), np.array([np.nan, np.nan]), np.array([0, 1]), 2, "TEST", "x",
                        range(1, 11))
    assert not np.isfinite(fl["obs"]) and H.p_seeds(fl["mean"], fl["obs"]) == 1.0
    none = {"n": 0, "win": float("nan"), "mean": float("nan"), "mean_x2": float("nan")}
    c = H.confirm_checks(none, {"dd": 0.0, "bust": False}, 0.3, 1 / 1001, 1 / 1001)       # the old floor p: still no T5
    assert not any(c[k] for k in ("T0", "T1", "T3", "T4", "T5")) and c["T2"]
    some = {"n": 150, "win": 0.8, "mean": 0.001, "mean_x2": 0.0005}
    assert all(H.confirm_checks(some, {"dd": 0.1, "bust": False}, 0.3, 0.001, 0.002).values())


def test_grid_tasks_keep_memo_cells_whole_and_split_memo_poor_ones(monkeypatch):
    """17.2: a task is the whole cell (the memo serves it per coin) except the full grid's split cells and the three
    memo-poor cells of GRID_CHUNK_OF; the split never changes a sum (test_e2e_grid_sums_equal_a_direct_recount runs a
    split cell)."""
    monkeypatch.setattr(R, "CHUNK", 10 ** 6)                  # the real grid, whatever an e2e fixture patched
    monkeypatch.setattr(H, "cell_grid", lambda kind, name: R.cell_grid(kind, name))
    monkeypatch.setattr(H, "cells_all", lambda: [c for c in R.cells() if c[2] in ("15m", "30m", "1h", "4h")])
    tasks = H.grid_tasks([("core", "N01_ST_EMA", "15m"), ("core", "N22_VORTEX_PSAR", "15m"), ("core", "V39_ALL", "1h"),
                          ("core", "N04_ST_KLINGER", "4h")])
    by = {}
    for kind, name, tf, c0, c1 in tasks:
        by.setdefault(name, []).append(c1 - c0)
    n01 = len(H.cell_grid("core", "N01_ST_EMA")[2])
    assert by["N01_ST_EMA"] == [n01]
    assert max(by["N22_VORTEX_PSAR"]) == 729 and sum(by["N22_VORTEX_PSAR"]) == len(H.cell_grid("core",
                                                                                                 "N22_VORTEX_PSAR")[2])
    assert max(by["V39_ALL"]) == 729 and max(by["N04_ST_KLINGER"]) == 2187
    assert len(H.grid_tasks(H.cells_all())) < 1000


def _hunt_test_files(root, v1_p=0.03, wide=(("W1", 0.2), ("W2", 0.4)), ds=("WDS",)):
    """Test files laid out as the hunt's push publishes them (research/hunt/results/hunt/<study>/test.json)."""
    v1 = {"pick": {"id": "V1PICK"}, "result": {"checks": {"P0": True, "p": v1_p}}}
    res = {pid: {"checks": {"PASS": False, "p": p}} for pid, p in wide}
    res.update({pid: {"checks": {"PASS": False}} for pid in ds})            # DeepSeek: p left out (D11)
    paths = {}
    for st, doc in (("v1", v1), ("wide", {"picks": [], "results": res})):
        d = os.path.join(root, "research", "hunt", "results", "hunt", st)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "test.json"), "w") as fh:
            json.dump(doc, fh)
        paths[st] = os.path.join(d, "test.json")
    return paths


def test_ledger_reads_the_published_hunt_files_and_never_shrinks_the_family(tmp_path, monkeypatch):
    own = [{"id": f"hiwr{i}", "kind": "core", "p": p, "checks": {"T0": True}} for i, p in
           enumerate((0.004, 0.011, 0.02))]
    paths = _hunt_test_files(str(tmp_path))
    monkeypatch.setattr(H, "HUNT_TESTS", (("hunt v1", (paths["v1"], "nowhere/v1.json")),
                                          ("hunt wide", (paths["wide"],))))
    monkeypatch.setattr(H, "LEDGER_EXTRA_REL", "research/hiwr/no_such_ledger_extra.json")
    extra = str(tmp_path / "extra.json")
    with open(extra, "w") as fh:
        json.dump([{"id": "O1", "p": 0.5}], fh)
    # the hunt's DeepSeek p is hidden: incomplete, nothing rejected or passed
    pub, priv = H.ledger(own, extra)
    assert pub["status"] == "incomplete" and pub["missing_p"] == ["WDS"] and pub["bh_rejections"] is None
    assert {r["source"] for r in pub["rows"]} >= {paths["v1"], paths["wide"]}
    # with the hunt's private file every row has a p: complete, BH and Holm over all 3 + 1 + 3 + 1 = 8 rows
    hp = str(tmp_path / "wide_test_private.json")
    with open(hp, "w") as fh:
        json.dump({"results": {"WDS": {"checks": {"p": 0.9}}}}, fh)
    pub, priv = H.ledger(own, extra, hp)
    assert pub["status"] == "complete" and pub["hypotheses"] == 8 and pub["missing_sources"] == []
    pv = [r["p"] for r in priv["rows"]]
    assert pub["holm_rejections"] == sum(H.holm(pv)) and pub["bh_rejections"] == sum(H.bh(pv))
    assert all("p" not in r for r in pub["rows"] if r["deepseek"])
    # a missing hunt file or no list of the other hypotheses: incomplete, never counted over the smaller family
    monkeypatch.setattr(H, "HUNT_TESTS", (("hunt v1", ("nowhere/v1.json",)), ("hunt wide", (paths["wide"],))))
    pub, _ = H.ledger(own, extra, hp)
    assert pub["status"] == "incomplete" and any("hunt v1" in m for m in pub["missing_sources"])
    assert pub["holm_rejections"] is None and all(r["holm_005"] is None for r in pub["rows"])
    pub, _ = H.ledger(own, None, hp)
    assert pub["status"] == "incomplete" and any("O1-O4" in m for m in pub["missing_sources"])


def test_ledger_command_rebuilds_without_touching_the_verdict(world, tmp_path, monkeypatch):
    monkeypatch.setattr(H, "STATE", [world["state"]])
    monkeypatch.setattr(H, "PIN_REL", "research/hiwr/pin_e2e.txt")
    monkeypatch.setattr(H, "PREREG_REL", "research/hiwr/out/PREREG_copy.md")
    monkeypatch.setattr(H, "required_files", lambda: [H.PREREG_REL, H.MANIFEST_SEL_REL, H.CHECK_SEL_REL])
    test_before = H.sha256_file(H.out_path("test.json"))
    v_before = _load(world, "ledger.json").get("version", 1)
    extra = str(tmp_path / "extra.json")
    with open(extra, "w") as fh:
        json.dump([], fh)                                            # "no other hypothesis"
    assert H.main(["ledger", "--private", world["private"], "--ledger-extra", extra]) == 0
    led = _load(world, "ledger.json")
    assert led["version"] == v_before + 1 and led["status"] == "complete" and led["hypotheses"] == 2
    assert os.path.exists(H.out_path(f"ledger_v{v_before}.json"))
    assert led["test_json_sha256"] == test_before == H.sha256_file(H.out_path("test.json"))
    assert H.d11_problems(led, {r["id"] for r in led["rows"] if r["deepseek"]}) == []


def test_reads_stop_starting_picks_after_the_deadline(world, tmp_path, monkeypatch):
    """The reads write one file per pick; with a deadline already passed no pick starts and reads.json lists every
    pick as missing (the verdict is untouched); a later run with time left does them."""
    monkeypatch.setattr(H, "STATE", [world["state"]])
    monkeypatch.setattr(H, "PIN_REL", "research/hiwr/pin_e2e.txt")
    picks = H.load_picks(Args(private=world["private"]))
    kits = {"kit": world["sel_kit"], "man_sel": json.load(open(H.rpath(H.MANIFEST_SEL_REL))),
            "kit_test": world["test_kit"], "man_test": json.load(open(H.rpath(H.MANIFEST_TEST_REL)))}
    rd = H.reads_module()
    args = Args(kit=world["sel_kit"], kit_test=world["test_kit"], work=str(tmp_path / "w"), private=world["private"],
                procs=2, reads_hours=0.0)
    ctx = {"H": H, "picks": picks, "kits": kits, "args": args, "pin": {}, "log": H.log}
    H.CTX.pop("SEL", None)
    H.CTX.pop("TEST", None)
    pub, _priv = rd.run(ctx)
    assert sorted(pub["missing"]) == sorted(p["id"] for p in picks) and pub["not_started_after_deadline"] == len(picks)
    args.reads_hours = None
    pub, priv = rd.run(ctx)
    assert pub["missing"] == [] and set(priv["picks"]) == {p["id"] for p in picks}
    full = json.load(open(os.path.join(world["private"], "reads_private.json")))["picks"]
    core = next(p["id"] for p in picks if p["kind"] == "core")
    assert priv["picks"][core]["R14_sha256"] == full[core]["R14_sha256"]
