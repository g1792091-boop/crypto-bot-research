"""Entry study parts B and C (research/entry_study/analysis_bc.py).

Synthetic inputs only (no data files): side selection of strength values, the Spearman sign handling and the
exact resampled Spearman, the week-block bootstrap p on a known case, BH, the B period-3 rule, the C mean / SE and
shape rules, the random-entry and no-edge odds, the strategy-wide C exclusion, the refusal on a definition or
manifest hash mismatch, the code / data signatures of checkpoints and bases, merging of saved aggregations, and
checkpoint resume."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "entry_study"))

BC = pytest.importorskip("analysis_bc")
stats = pytest.importorskip("scipy.stats")


# ------------------------------------------------------------------ B: side selection and sign
def test_side_values_takes_the_traded_side():
    long_v = np.array([10.0, 11.0, 12.0, 13.0, np.nan])
    short_v = np.array([-10.0, -11.0, -12.0, -13.0, -14.0])
    idx = np.array([0, 1, 3, 4, 4])
    side = np.array([1, -1, 1, 1, -1], np.int8)
    got = BC.side_values(long_v, short_v, idx, side)
    assert np.array_equal(got, np.array([10.0, -11.0, 13.0, np.nan, -14.0]), equal_nan=True)
    with pytest.raises(ValueError):
        BC.side_values(long_v, short_v, [0], [0])


def test_to_signal_short_never_overrides_long():
    long = np.array([1, 0, 1, 0], bool)
    short = np.array([0, 1, 1, 0], bool)
    assert BC.to_signal(long, short).tolist() == [1, -1, 1, 0]


def test_spearman_sign_handling():
    rng = np.random.default_rng(0)
    x = rng.normal(size=400)
    roe = -x + rng.normal(scale=0.5, size=400)       # smaller value -> better trade
    rho_raw = BC.spearman(x, roe)
    assert rho_raw < -0.5
    # declared 'smaller is stronger': signed so that stronger = higher -> positive rho, same magnitude
    rho_signed = BC.spearman(BC.signed(x, higher_is_stronger=False), roe)
    assert rho_signed == pytest.approx(-rho_raw, abs=1e-12) and rho_signed > 0.5
    assert BC.spearman(BC.signed(x, True), roe) == pytest.approx(rho_raw, abs=1e-12)


def test_spearman_matches_scipy_with_ties():
    rng = np.random.default_rng(1)
    x = rng.integers(0, 6, 300).astype(float)         # heavy ties
    y = np.round(rng.normal(size=300) + 0.3 * x, 1)
    assert BC.spearman(x, y) == pytest.approx(stats.spearmanr(x, y)[0], abs=1e-12)


def test_resampled_spearman_equals_spearman_of_the_expanded_sample():
    rng = np.random.default_rng(2)
    n = 120
    x = rng.integers(0, 10, n).astype(float)
    y = np.round(rng.normal(size=n), 1)
    W = rng.integers(0, 4, size=(5, n)).astype(float)
    got = BC._wspearman(W, BC._ties(x), BC._ties(y))
    for k in range(5):
        rep = W[k].astype(int)
        want = stats.spearmanr(np.repeat(x, rep), np.repeat(y, rep))[0]
        assert got[k] == pytest.approx(want, abs=1e-10)


# ------------------------------------------------------------------ B: bootstrap p on known cases
def test_bootstrap_p_one_week_is_deterministic():
    x = np.arange(10.0)
    week = np.zeros(10, int)
    up = BC.spearman_boot(x, x, week, seed=[1, 2, 3])
    down = BC.spearman_boot(x, -x, week, seed=[1, 2, 3])
    assert up["rho"] == pytest.approx(1.0) and up["p_pos"] == pytest.approx(1 / (BC.BOOT_B + 1))
    assert down["rho"] == pytest.approx(-1.0) and down["p_pos"] == pytest.approx(1.0)
    assert down["p_neg"] == pytest.approx(1 / (BC.BOOT_B + 1))


def test_bootstrap_p_two_weeks_known_distribution():
    """Week A: perfectly positive, week B: strongly negative. Resampling 2 weeks: {A, A} -> rho = +1 (prob 1/4),
    {B, B} -> -1 (1/4), {A, B} -> the pooled sample, rho < 0 (1/2). So P(rho_b <= 0) = 3/4."""
    x = np.array([1, 2, 3, 4, 5, 6], float)
    y = np.array([1, 2, 0, -1, -2, -3], float)
    week = np.array([0, 0, 1, 1, 1, 1])
    assert BC.spearman(x, y) < 0
    r = BC.spearman_boot(x, y, week, seed=[20260930, 99])
    assert r["weeks"] == 2
    assert r["p_pos"] == pytest.approx(0.75, abs=0.04)
    assert r["p_neg"] == pytest.approx(0.25, abs=0.04)         # rho_b >= 0 only for {A, A}


def test_week_D_matches_brute_force():
    rng = np.random.default_rng(5)
    n, W = 60, 4
    v = rng.integers(0, 5, n).astype(float)
    inv = rng.integers(0, W, n)
    order = np.argsort(inv, kind="stable")
    D = BC._week_D(v, inv, W, order)
    for r, i in enumerate(order):
        for w in range(W):
            vw = v[inv == w]
            assert D[r, w] == ((vw < v[i]).sum() - (vw > v[i]).sum()) / 2


def test_tensor_and_direct_bootstrap_agree():
    rng = np.random.default_rng(6)
    n = 900
    x = rng.integers(0, 8, n).astype(float)                 # ties in x
    y = np.round(0.2 * x + rng.normal(size=n), 1)           # ties in y
    week = rng.integers(0, 25, n)
    uw, inv = np.unique(week, return_inverse=True)
    C = BC.boot_counts(len(uw), 300, [11])
    rt = BC._boot_rho_tensor(x, y, inv, len(uw), C)
    rd = BC._boot_rho_direct(x, y, inv, C)
    assert np.allclose(rt, rd, atol=1e-12, rtol=0)
    a = BC.spearman_boot(x, y, week, seed=[3], method="tensor")
    b = BC.spearman_boot(x, y, week, seed=[3], method="direct")
    assert a["p_pos"] == b["p_pos"] and a["p_neg"] == b["p_neg"] and a["rho"] == b["rho"]


def test_bootstrap_p_is_seeded_and_chunking_does_not_matter():
    rng = np.random.default_rng(3)
    n = 500
    x = rng.normal(size=n)
    y = 0.1 * x + rng.normal(size=n)
    week = rng.integers(0, 40, n)
    a = BC.spearman_boot(x, y, week, seed=[7])
    b = BC.spearman_boot(x, y, week, seed=[7], chunk_elems=n * 7)   # different chunk size, same draws
    assert a["p_pos"] == b["p_pos"] and a["rho"] == b["rho"]


# ------------------------------------------------------------------ BH
def test_bh_known_example():
    p = np.array([0.01, 0.04, 0.03, 0.02, 0.5])
    rej, rank, adj = BC.bh(p, 0.10)
    assert rej.tolist() == [True, True, True, True, False]
    assert rank.tolist() == [1, 4, 3, 2, 5]
    rej2, _, _ = BC.bh(np.array([0.2, 0.3, 0.9]), 0.10)
    assert not rej2.any()
    assert adj.min() == pytest.approx(0.05)


# ------------------------------------------------------------------ C: SE, shapes, random odds
def test_mean_se_boot():
    r = BC.mean_se_boot([1.0, 2.0, 3.0], [5, 5, 5], seed=[1])
    assert r["mean"] == pytest.approx(2.0) and r["weeks"] == 1 and np.isnan(r["se"])   # one week: no SE
    r = BC.mean_se_boot([0.5] * 10, np.arange(10), seed=[1])
    assert r["se"] == pytest.approx(0.0)
    rng = np.random.default_rng(4)
    roe = rng.normal(0, 1, 2000)
    r = BC.mean_se_boot(roe, np.arange(2000) // 10, seed=[2])            # iid weeks: SE ~ sd / sqrt(n)
    assert r["se"] == pytest.approx(1 / np.sqrt(2000), rel=0.15)


def test_classify_shape():
    se = 0.01
    flat = {0.5: 0.105, 0.75: 0.095, 1.25: 0.1, 1.5: 0.109}
    assert BC.classify_shape(0.1, se, flat)[0] == "flat"
    spike = {0.5: 0.2, 0.75: 0.07, 1.25: 0.079, 1.5: 0.0}
    assert BC.classify_shape(0.1, se, spike)[0] == "spike"
    one_side = {0.5: 0.1, 0.75: 0.07, 1.25: 0.095, 1.5: 0.0}          # beats x0.75 by 3 SE but x1.25 by 0.5
    assert BC.classify_shape(0.1, se, one_side)[0] == "smooth"
    exactly_2se = {0.5: 0.5, 0.75: 0.25, 1.25: 0.25, 1.5: 0.5}         # '> 2 SE' is strict (exact binary values)
    assert BC.classify_shape(0.5, 0.125, exactly_2se)[0] == "smooth"
    no_trades = {0.5: np.nan, 0.75: 0.1, 1.25: 0.1, 1.5: 0.1}
    shape, note = BC.classify_shape(0.1, se, no_trades)
    assert shape == "smooth" and "x0.5" in note
    assert BC.classify_shape(0.1, np.nan, flat)[0] == "insufficient"
    assert BC.classify_shape(0.1, se, flat, min_ok=False)[0] == "insufficient"


def test_prob_random_all():
    pos = {p: {"BTCUSD": np.full(50, 0.1), "ETHUSD": np.full(50, 0.2)} for p in (1, 2, 3)}
    neg = {p: {"BTCUSD": np.full(50, -0.1), "ETHUSD": np.full(50, -0.2)} for p in (1, 2, 3)}
    counts = {p: {"BTCUSD": 5, "ETHUSD": 3} for p in (1, 2, 3)}
    assert BC.prob_random_all(counts, pos, seed=[1]) == 1.0
    assert BC.prob_random_all(counts, neg, seed=[1]) == 0.0
    coin = {p: {"BTCUSD": np.array([-1.0, 1.0])} for p in (1, 2, 3)}   # one trade per period: P(> 0) = 1/2 each
    got = BC.prob_random_all({p: {"BTCUSD": 1} for p in (1, 2, 3)}, coin, seed=[5])
    assert got == pytest.approx(0.125, abs=0.03)
    assert np.isnan(BC.prob_random_all({1: {"BTCUSD": 0}}, pos, seed=[1]))


def test_random_all_reports_the_hit_count_and_stops_when_no_draw_is_left():
    pos = {p: {"BTCUSD": np.full(50, 0.1)} for p in (1, 2, 3)}
    mixed = {1: {"BTCUSD": np.full(50, -0.1)}, 2: {"BTCUSD": np.full(50, 0.1)}, 3: {"BTCUSD": np.full(50, 0.1)}}
    counts = {p: {"BTCUSD": 4} for p in (1, 2, 3)}
    assert BC.random_all(counts, pos, [1]) == dict(prob=1.0, k=2000, draws=2000)
    r = BC.random_all(counts, mixed, [1])
    assert r["k"] == 0 and r["prob"] == 0.0 and BC.prob_text(r["k"]) == "< 1/2000"
    coin = {p: {"BTCUSD": np.array([-1.0, 1.0])} for p in (1, 2, 3)}
    r = BC.random_all({p: {"BTCUSD": 1} for p in (1, 2, 3)}, coin, [5])
    assert r["prob"] == r["k"] / 2000 and BC.prob_text(r["k"]) == f"{r['k']}/2000"
    assert r["prob"] == BC.prob_random_all({p: {"BTCUSD": 1} for p in (1, 2, 3)}, coin, [5])
    assert np.isnan(BC.random_all({1: {"BTCUSD": 3}}, {1: {}}, [1])["prob"])       # no random pool for that coin


def test_noedge_block_keeps_the_variant_clustering_but_not_its_edge():
    rng = np.random.default_rng(8)
    week = np.repeat(np.arange(40), 25)
    roe = 0.5 + rng.normal(0, 0.1, 40)[week] + rng.normal(0, 0.01, len(week))    # large edge, week-clustered
    units = {p: (roe, week) for p in (1, 2, 3)}
    seeds = {p: [3, p] for p in (1, 2, 3)}
    # centred on a clearly negative random-entry mean: the variant's own +0.5 edge does not count
    assert BC.noedge_block_all(units, {p: -0.2 for p in (1, 2, 3)}, seeds) == 0.0
    assert BC.noedge_block_all(units, {p: 0.2 for p in (1, 2, 3)}, seeds) == 1.0
    # centred on 0: each period ~1/2, all three ~1/8
    assert BC.noedge_block_all(units, {p: 0.0 for p in (1, 2, 3)}, seeds) == pytest.approx(0.125, abs=0.04)
    # random entries lose a little (mu0 < 0): the week clustering widens the no-edge spread, so a clustered no-edge
    # variant is positive in all three periods far more often than the same trades treated as independent
    mu0 = {p: -0.01 for p in (1, 2, 3)}
    clustered = BC.noedge_block_all(units, mu0, seeds)
    iid = BC.noedge_block_all({p: (roe, np.arange(len(roe))) for p in (1, 2, 3)}, mu0, seeds)
    assert clustered > 0.005 and iid < 0.001 and clustered > 5 * iid


# ------------------------------------------------------------------ hash refusal
def _write_manifest(base):
    lines = []
    for kind in ("strength_defs", "param_defs"):
        data = (base / kind / "XX.py").read_bytes()
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {kind}/XX.py")
    (base / "DEFS.sha256").write_text("\n".join(lines) + "\n")
    return str(base / "DEFS.sha256")


def _defs_dir(tmp_path):
    base = tmp_path / "entry"
    for kind in ("strength_defs", "param_defs"):
        (base / kind).mkdir(parents=True)
        (base / kind / "XX.py").write_text(f"NAME = 'XX'\nKIND = '{kind}'\n")
    return base, _write_manifest(base)


def test_hash_check_passes_then_refuses_a_changed_definition(tmp_path):
    base, man = _defs_dir(tmp_path)
    pin = dict(manifest_sha=None)                               # a temporary manifest: no pinned hash
    assert BC.verify_defs(["XX"], man, str(base), **pin)["ok"]
    BC.require_defs(["XX"], man, str(base), **pin)
    mod = BC.load_def("strength_defs", "XX", man, str(base), **pin)
    assert mod.NAME == "XX" and mod.KIND == "strength_defs"
    (base / "param_defs" / "XX.py").write_text("NAME = 'XX'\nKIND = 'tampered'\n")
    r = BC.verify_defs(["XX"], man, str(base), **pin)
    assert not r["ok"] and [f["path"] for f in r["mismatched"]] == ["param_defs/XX.py"]
    with pytest.raises(SystemExit):
        BC.require_defs(["XX"], man, str(base), **pin)
    with pytest.raises(SystemExit):
        BC.load_def("param_defs", "XX", man, str(base), **pin)


def test_hash_check_refuses_a_strategy_missing_from_the_manifest(tmp_path):
    base, man = _defs_dir(tmp_path)
    with pytest.raises(SystemExit):
        BC.require_defs(["XX", "YY"], man, str(base), manifest_sha=None)


def test_hash_check_refuses_a_definition_changed_and_re_hashed_in_the_manifest(tmp_path):
    """Editing a definition AND its manifest line must still be refused: the manifest itself is pinned."""
    base, man = _defs_dir(tmp_path)
    pinned = hashlib.sha256(open(man, "rb").read()).hexdigest()
    assert BC.verify_defs(["XX"], man, str(base), manifest_sha=pinned)["ok"]
    (base / "param_defs" / "XX.py").write_text("NAME = 'XX'\nKIND = 'tampered'\n")
    _write_manifest(base)                                       # re-hash the edited file into the manifest
    assert BC.verify_defs(["XX"], man, str(base), manifest_sha=None)["ok"]      # the unpinned check is fooled
    r = BC.verify_defs(["XX"], man, str(base), manifest_sha=pinned)
    assert not r["ok"] and not r["manifest_ok"] and not r["mismatched"]
    with pytest.raises(SystemExit, match="pinned"):
        BC.require_defs(["XX"], man, str(base), manifest_sha=pinned)
    with pytest.raises(SystemExit, match="pinned"):
        BC.load_def("param_defs", "XX", man, str(base), manifest_sha=pinned)    # workers load without require_defs


def test_locked_manifest_covers_every_strategy_and_is_the_committed_one():
    r = BC.verify_defs(BC.strategy_names())
    assert r["ok"] and r["manifest_ok"] and r["files_checked"] == 72 and not r["not_in_manifest"]
    assert r["manifest_sha256"] == BC.DEFS_BC_MANIFEST_SHA256
    g = BC.manifest_git_check()
    assert g["git_sha256"] in (None, BC.DEFS_BC_MANIFEST_SHA256)   # None only without git / the commit


# ------------------------------------------------------------------ B: decision rules (period 3)
def _b_row(feature, **kw):
    r = dict(strategy="N17_KC_RSI", tf="4h", feature=feature, tested=True, status_p1="ok", p_p1=1e-4, rho_p1=0.2,
             status_p2="ok", p_p2=0.01, rho_p2=0.1, status_p3="ok", rho_p3=0.1, n_signals_p3=500, n_finite_p3=200,
             random_rho_p1=0.0, random_p_pos_p1=0.5, random_p_neg_p1=0.5)
    r.update(kw)
    return r


def test_period3_verdict_needs_30_trades_not_signal_bars():
    cells = pd.DataFrame([
        _b_row("ok"),
        # many period-3 signal bars but only 5 trades with a finite value: status 'insufficient' -> no verdict
        _b_row("few_trades", status_p3="insufficient", n_signals_p3=500, n_finite_p3=5, rho_p3=0.9),
        _b_row("opposite", rho_p3=-0.1),
        # >= 30 trades is enough even with few signal bars (the gate counts trades with a finite value)
        _b_row("few_signals", n_signals_p3=40, n_finite_p3=35),
    ])
    out = BC.decide_B(cells).set_index("feature")
    assert bool(out.loc["ok", "pass_p2"]) and out.loc["ok", "verdict_p3"] == "same sign"
    assert bool(out.loc["ok", "candidate"])
    assert out.loc["few_trades", "verdict_p3"] == "no data" and not bool(out.loc["few_trades", "candidate"])
    assert bool(out.loc["few_trades", "pass_p2"])
    assert out.loc["opposite", "verdict_p3"] == "opposite sign" and not bool(out.loc["opposite", "candidate"])
    assert out.loc["few_signals", "verdict_p3"] == "same sign"
    assert not hasattr(BC, "MIN_P3_SIGNALS")


# ------------------------------------------------------------------ resume
CALLS: list = []


def _square(job):
    CALLS.append(job)
    return dict(job=job, value=job * job)


def test_run_jobs_resumes_from_checkpoints(tmp_path):
    path_of = lambda j: str(tmp_path / "ckpt" / f"{j}.pkl")   # noqa: E731
    CALLS.clear()
    BC.save_ckpt(path_of(2), dict(job=2, value=4), "sig1")      # finished before the 'kill'
    r = BC.run_jobs([1, 2, 3], _square, path_of, lambda j: "sig1", procs=1, log=None)
    assert sorted(CALLS) == [1, 3] and r["run"] == 2 and r["resumed"] == 1
    assert BC.load_ckpt(path_of(3), "sig1") == dict(job=3, value=9)
    CALLS.clear()
    r = BC.run_jobs([1, 2, 3], _square, path_of, lambda j: "sig1", procs=1, log=None)
    assert CALLS == [] and r["run"] == 0
    # a checkpoint written under another signature (changed definitions / data) is recomputed
    r = BC.run_jobs([1, 2, 3], _square, path_of, lambda j: "sig2" if j == 1 else "sig1", procs=1, log=None)
    assert CALLS == [1] and r["run"] == 1
    # a truncated file (killed mid-write without the atomic rename) is not trusted
    with open(path_of(3), "wb") as fh:
        fh.write(b"\x80\x05garbage")
    CALLS.clear()
    BC.run_jobs([1, 2, 3], _square, path_of, lambda j: "sig2" if j == 1 else "sig1", procs=1, log=None)
    assert CALLS == [3]


def test_outcome_table_lookup_and_missing_pairs():
    keys = BC.pair_key(np.array([3, 5]), np.array([1, -1]))
    cols = {k: np.array([1.0, 2.0]) for k in BC.OC_COLS}
    cols.update(ok=np.array([True, True]), sized=np.array([True, False]), done=np.array([True, True]))
    tab = BC.OutcomeTable(np.sort(keys), {k: v[np.argsort(keys)] for k, v in cols.items()})
    got = tab.get(np.array([5, 3]), np.array([-1, 1]))
    assert got["roe"].tolist() == [2.0, 1.0] and got["valid"].tolist() == [False, True]
    with pytest.raises(KeyError):
        tab.get(np.array([3]), np.array([-1]))


# ------------------------------------------------------------------ C aggregation on synthetic checkpoints
def _synthetic_C(tmp_path, monkeypatch, mismatch=None):
    """Synthetic C checkpoints of N17_KC_RSI on 15m / 1h (every variant losing a little, trades in all periods) and
    synthetic random pools; mismatch = (tf, coin) with 5 post-warm-up default mismatches."""
    ck = str(tmp_path / "ckpt")
    monkeypatch.setattr(BC, "ckpt_path", lambda part, name, tf, coin, ckpt_dir=ck:
                        os.path.join(ckpt_dir, part, f"{name}__{tf}__{coin}.pkl"))
    monkeypatch.setattr(BC, "job_signature", lambda tf, coin: "sig")
    pools_rng = np.random.default_rng(1)

    def fake_base(tf, coin, src, keys=None):
        out = {}
        for p in dict(BC.SOURCES)[src]:
            out[f"r_valid_p{p}"] = np.ones(400, bool)
            out[f"r_roe_p{p}"] = pools_rng.normal(-0.02, 0.3, 400)
            out[f"r_week_p{p}"] = np.arange(400) // 10
        return out
    monkeypatch.setattr(BC, "load_base", fake_base)
    name = "N17_KC_RSI"
    variants = [{k: v for k, v in x.items() if k != "overrides"}
                for x in BC.variant_list(BC.load_def("param_defs", name))]
    rng = np.random.default_rng(0)
    for tf in ("15m", "1h"):
        for c in BC.COINS:
            per = {p: {v["vid"]: dict(n_signals=100, n_sized=60, n_open=0, n_trades=60, changed_signal_bars=0,
                                      week=rng.integers(0, 50, 60), roe=-np.abs(rng.normal(0.1, 0.05, 60)))
                       for v in variants} for p in (1, 2, 3)}
            mism = 5 if (tf, c) == mismatch else 0
            data = dict(part="C", name=name, tf=tf, coin=c, excluded=None, variants=variants, periods=per,
                        default_check={"p12": dict(mismatch_post_warmup=mism, mismatch_warmup=0,
                                                   signals_post_warmup=100),
                                       "p3": dict(mismatch_post_warmup=0, mismatch_warmup=0, signals_post_warmup=100)},
                        seconds={"total": 0.0})
            BC.save_ckpt(BC.ckpt_path("C", name, tf, c), data, "sig")
    return name


def test_default_mismatch_on_one_timeframe_excludes_the_strategy_from_all_of_C(tmp_path, monkeypatch):
    name = _synthetic_C(tmp_path, monkeypatch, mismatch=("15m", "BTCUSD"))
    r = BC.aggregate_C([name], ["15m", "1h"], 1, log=None)
    assert sorted(e["tf"] for e in r["excluded"]) == ["15m", "1h"]
    by_tf = {e["tf"]: e["reason"] for e in r["excluded"]}
    assert "BTCUSD_p12" in by_tf["15m"] and by_tf["1h"].startswith("strategy excluded from C (PREREG 4)")
    assert "15m" in by_tf["1h"]
    assert len(r["variants"]) == 0 and len(r["shapes"]) == 0
    doc = BC.candidates_doc({"C": r})["C"]
    assert doc["variants"] == 0 and len(doc["excluded"]) == 2


def test_chance_is_computed_for_every_variant_with_trades_not_only_passers(tmp_path, monkeypatch):
    name = _synthetic_C(tmp_path, monkeypatch)
    r = BC.aggregate_C([name], ["15m", "1h"], 1, log=None)
    v = r["variants"]
    assert not r["excluded"] and len(v) == 2 * (1 + 4 * 4)
    assert not v["positive_all3"].any()                         # every synthetic variant loses
    assert v["prob_random_all3"].notna().all() and v["prob_noedge_block_all3"].notna().all()
    k = v["prob_random_all3_k"].astype(float)
    assert np.allclose(v["prob_random_all3"], k / BC.BOOT_B)
    zero = k == 0
    assert (v.loc[zero, "prob_random_all3_text"] == "< 1/2000").all()
    assert np.allclose(v.loc[zero, "prob_random_all3_upper"], 1 / (BC.BOOT_B + 1))
    assert v.loc[~zero, "prob_random_all3_upper"].isna().all()
    doc = BC.candidates_doc({"C": r})["C"]
    var = v[~v["is_default"]]
    assert doc["expected_positive_all3_under_random"] == pytest.approx(var["prob_random_all3"].sum())
    assert doc["expected_positive_all3_noedge_block"] == pytest.approx(var["prob_noedge_block_all3"].sum())
    assert doc["variants_with_chance_estimate"] == len(var)
    trials = BC.trials_table({"C": r})
    assert {"prob_random_all3", "prob_random_all3_k", "prob_noedge_block_all3"} <= set(trials.columns)


# ------------------------------------------------------------------ code / data signatures
def test_code_hash_covers_the_code_that_runs(tmp_path):
    files = [str(p) for p in BC._DEP_FILES]
    assert all(os.path.exists(p) for p in files)
    names = {os.path.basename(p) for p in files}
    assert {"analysis_bc.py", "analysis_sr.py", "sr.py", "profiles.py", "rules_bt.py", "sweepsig.py", "sizing.py",
            "ladder.py", "margin.py", "config.py", "sigservice.py", "PREREG.sha256", "DEFS_BC.sha256"} <= names
    assert len(BC.CODE_HASH) == 64 and BC.code_signature() == BC.CODE_HASH[:16]
    assert set(BC.CODE_FILES) == {os.path.relpath(p, ROOT) for p in files}
    copies = []
    for i, p in enumerate(files):
        dst = tmp_path / f"{i}_{os.path.basename(p)}"
        shutil.copyfile(p, dst)
        copies.append(str(dst))
    h0 = BC._code_hash(copies)
    data = bytearray(open(copies[1], "rb").read())             # one byte of analysis_sr.py
    data[len(data) // 2] ^= 1
    open(copies[1], "wb").write(bytes(data))
    assert BC._code_hash(copies) != h0


def test_changed_code_invalidates_checkpoints_and_bases(tmp_path, monkeypatch):
    monkeypatch.setattr(BC, "source_fingerprint", lambda tf, coin, src: [["x.npz", 10, 1]])
    meta = dict(version=BC.BASE_VERSION, code=BC.CODE_HASH, fingerprint=[["x.npz", 10, 1]])
    monkeypatch.setattr(BC, "read_base_meta", lambda path: dict(meta))
    assert BC.base_ok("1h", "BTCUSD", "p12")
    sig0 = BC.job_signature("1h", "BTCUSD")
    path = str(tmp_path / "ck.pkl")
    BC.save_ckpt(path, {"x": 1}, sig0)
    assert BC.load_ckpt(path, BC.job_signature("1h", "BTCUSD")) == {"x": 1}
    monkeypatch.setattr(BC, "CODE_HASH", hashlib.sha256(b"one byte changed").hexdigest())
    assert BC.code_signature() != sig0.split(":")[0]
    assert BC.load_ckpt(path, BC.job_signature("1h", "BTCUSD")) is None
    assert not BC.base_ok("1h", "BTCUSD", "p12")               # a base built by the old code is rebuilt


def test_refuses_analysis_sr_data_overrides(monkeypatch):
    monkeypatch.setattr(BC.A, "overrides", lambda: {"sig12": "/elsewhere/signals"}, raising=False)
    with pytest.raises(SystemExit, match="pre-registered data"):
        BC.require_default_data()
    monkeypatch.setattr(BC.A, "overrides", lambda: {"cache": "/elsewhere/cache"}, raising=False)
    assert BC.require_default_data()["overrides_ignored"] == {"cache": "/elsewhere/cache"}
    assert BC.OUT == os.path.join(ROOT, "research", "entry_study", "out")


def test_job_signature_uses_the_current_source_files(tmp_path, monkeypatch):
    fp = {"v": [["x.npz", 10, 1]]}
    monkeypatch.setattr(BC, "source_fingerprint", lambda tf, coin, src: fp["v"])
    monkeypatch.setattr(BC, "read_base_meta", lambda path: dict(code=BC.CODE_HASH, fingerprint=[["x.npz", 10, 1]]))
    sig0 = BC.job_signature("4h", "ETHUSD")
    fp["v"] = [["x.npz", 10, 2]]                                # the source file changed after the base was built
    assert BC.job_signature("4h", "ETHUSD") != sig0
    assert not BC.base_ok("4h", "ETHUSD", "p3") and BC.stale_bases(["4h"])


# ------------------------------------------------------------------ combining saved aggregations
def test_saved_aggregation_is_merged_only_when_current(tmp_path, monkeypatch):
    sigs = {"cur": "s1"}
    monkeypatch.setattr(BC, "job_signature", lambda tf, coin: sigs["cur"])
    names = ["N17_KC_RSI"]
    res = dict(selection=dict(strategies=names, tfs=list(BC.TFS_C)),
               ckpt_sigs={f"{tf} {c}": "s1" for tf in BC.TFS_C for c in BC.COINS}, variants=pd.DataFrame())
    path = str(tmp_path / "subset_C.pkl")
    BC.save_agg(path, res)
    got, why = BC.load_agg_compatible(path, "C", names, list(BC.TFS))
    assert why is None and got["selection"] == res["selection"]
    assert BC.load_agg_compatible(path, "C", ["N17_KC_RSI", "DOGE"], list(BC.TFS))[0] is None   # other strategies
    assert BC.load_agg_compatible(path, "C", names, ["1h"])[0] is None                          # other timeframes
    sigs["cur"] = "s2"                                          # checkpoints / data changed since
    assert "changed" in BC.load_agg_compatible(path, "C", names, list(BC.TFS))[1]
    sigs["cur"] = "s1"
    monkeypatch.setattr(BC, "CODE_HASH", "0" * 64)              # made by other code
    assert "other code" in BC.load_agg_compatible(path, "C", names, list(BC.TFS))[1]
    import pickle
    with open(path, "wb") as fh:                                # the older format (no code hash)
        pickle.dump(res, fh)
    assert BC.load_agg_compatible(path, "C", names, list(BC.TFS))[0] is None


def test_write_outputs_removes_files_of_a_part_not_in_the_outputs(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for f in BC.PART_FILES["B"] + BC.PART_FILES["C"]:
        (out / f).write_text("old\n")
    removed = BC.write_outputs({}, str(out), dict(run="test"))
    assert sorted(os.path.basename(p) for p in removed) == sorted(BC.PART_FILES["B"] + BC.PART_FILES["C"])
    assert not any((out / f).exists() for f in BC.PART_FILES["B"] + BC.PART_FILES["C"])
    assert (out / "bc_run_meta.json").exists()
