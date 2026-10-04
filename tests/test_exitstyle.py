"""Five-year exit-style comparison (research/exitstyle): pre-registration hash, the ladder arm reproducing the levstop
baseline (tiers|2.0), and the fixed take-profit exit on synthetic paths (same-bar stop/TP = stop first)."""

import hashlib
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "exitstyle"))
sys.path.insert(0, os.path.join(ROOT, "research", "levstop"))
import exitstyle as ES  # noqa: E402
import levstop as LV  # noqa: E402

HERE = os.path.join(ROOT, "research", "exitstyle")
OUT_JSON = os.path.join(HERE, "out", "exitstyle.json")
LEVSTOP_JSON = os.path.join(ROOT, "research", "levstop", "out", "levstop.json")
RB = LV._profiles().RB
SLIP, FEE = RB.SETTINGS.slippage_frac, RB.SETTINGS.taker_fee


# ---------------------------------------------------------------- pre-registration
def test_preregistration_hash_matches():
    line = open(os.path.join(HERE, "PREREG_EXITSTYLE.sha256")).read().split()
    body = open(os.path.join(HERE, "PREREG_EXITSTYLE.md"), "rb").read()
    assert line[1] == "PREREG_EXITSTYLE.md" and hashlib.sha256(body).hexdigest() == line[0]


def test_arms_are_the_preregistered_ones():
    assert ES.ARMS == {"ladder": (True, None), "tp1R": (False, 1.0), "tp1.5R": (False, 1.5), "tp2R": (False, 2.0),
                       "tp3R": (False, 3.0), "ladder_tp2R": (True, 2.0)}
    assert ES.K == 2.0 and ES.PRIMARY == ("15m", "30m", "1h", "4h") and ES.CONTEXT == ("5m",) and ES.MIN_PAIRED == 30
    assert ES.BASE == "ladder" and LV.CURRENT == "tiers|2.0"


# ---------------------------------------------------------------- ladder arm == levstop tiers|2.0
def _atr(h, lo, c):
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    out = np.full(len(tr), np.nan)
    a = float(np.mean(tr[:14]))
    out[13] = a
    for i in range(14, len(tr)):
        a += (tr[i] - a) / 14.0
        out[i] = a
    return out


def _synthetic_bars(n=3000, seed=1, vol=0.004, start="2021-09-01T00:00"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.concatenate([[100.0], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    t0 = np.datetime64(start, "ns").astype(np.int64)
    ts = t0 + np.arange(n, dtype=np.int64) * 3_600_000_000_000
    return {"ts": ts, "o": o, "h": h, "l": lo, "c": c, "atr": _atr(h, lo, c)}


def test_scan_without_tp_is_profiles_scan_bit_for_bit():
    P = LV._profiles()
    b = _synthetic_bars()
    rng = np.random.default_rng(3)
    idx = np.sort(rng.choice(np.arange(20, 2900), 300, replace=False))
    side = np.where(rng.random(300) < 0.5, 1, -1)
    lev, liq = ES.sizing(idx, side, b)
    s = lev > 0
    n, f_bar = len(b["ts"]), RB.FUNDING_8H / 8
    for H in (64, 512):
        ref = P._scan(b, idx[s], side[s], lev[s], liq[s], H, n, f_bar, k_stop=2.0)
        got = ES.scan(b, idx[s], side[s], lev[s], liq[s], H, n, f_bar, 2.0, tp_r=None, ladder=True)
        for x in ("done", "held", "roe", "reason"):
            assert np.array_equal(got[x], ref[x]), x


def test_ladder_arm_reproduces_levstop_outcomes_and_cell_row():
    b = _synthetic_bars(n=4000, seed=5)
    rng = np.random.default_rng(6)
    idx = np.sort(rng.choice(np.arange(20, 3900), 400, replace=False))
    side = np.where(rng.random(400) < 0.5, 1, -1)
    ref = LV.outcomes(b, idx, side, "1h", "tiers", 2.0)
    got = ES.outcomes(b, idx, side, "1h", "ladder")
    assert ES.same_arrays(got, ref) and got["done"].sum() > 300
    # every TP arm: same signals sized the same way, so the paired set is (nearly) everything
    for arm in ES.CANDIDATES:
        o = ES.outcomes(b, idx, side, "1h", arm)
        assert np.array_equal(o["lev"], ref["lev"]) and (o["done"] & ref["done"]).sum() >= 0.98 * ref["done"].sum()
        assert np.all(o["roe"][o["done"]] >= -1.0)
        if arm.startswith("tp"):
            assert (o["reason"][o["done"]] == 1).sum() == 0 and (o["reason"][o["done"]] == 4).any()


def test_run_on_a_tiny_synthetic_cache_ladder_row_is_levstops(tmp_path):
    rng = np.random.default_rng(4)
    for ci, c in enumerate(LV.COINS[:2]):
        b = _synthetic_bars(n=26_500, seed=10 + ci, vol=0.003, start="2021-07-25T00:00")
        n = len(b["ts"])
        sig = {f"s__{s}": np.where(rng.random(n) < 0.01, np.where(rng.random(n) < 0.5, 1, -1), 0).astype(np.int8)
               for s in ("AAA", "BBB")}
        np.savez_compressed(tmp_path / f"sig_1h_{c}.npz", **b, **sig)
    lv = LV.run(str(tmp_path), str(tmp_path / "lv.json"), procs=1, n_boot=200, tfs=("1h",))
    doc = ES.run(str(tmp_path), str(tmp_path / "es.json"), procs=1, n_boot=200, tfs=("1h",),
                 summary_path=str(tmp_path / "s.md"))
    assert set(doc["cells"]) == {"AAA|1h", "BBB|1h"} and doc["self_test"]["scan_all_identical"]
    ci = {c: i for i, c in enumerate(ES.COLUMNS)}
    li = {c: i for i, c in enumerate(LV.COLUMNS)}
    for key in doc["cells"]:
        lad, ref = doc["cells"][key]["ladder"], lv["cells"][key]["tiers|2.0"]
        for col in ("trades", "mean_eq", "mean_eq_p1", "mean_eq_p2", "win_rate", "bust_p1", "bust_p2", "mult_p1", "mult_p2"):
            assert lad[ci[col]] == pytest.approx(ref[li[col]], rel=1e-4), col
        assert lad[ci["diff"]] == 0.0 and lad[ci["p_better"]] is None
        tp = doc["cells"][key]["tp2R"]
        assert tp[ci["paired_n"]] > 100 and 0 < tp[ci["p_better"]] <= 1 and tp[ci["tp_share"]] > 0
    s = doc["summary"]
    assert set(s["primary"]) == set(ES.ARMS) and s["primary"]["ladder"]["accounts"] == 4
    assert s["decision"]["recommend"] in ES.ARMS and set(s["decision"]["arms"]) == set(ES.CANDIDATES)
    assert s["context_5m"] == {}
    md = (tmp_path / "s.md").read_text()
    assert "판정" in md and "계단 잠금" in md


@pytest.mark.skipif(not os.environ.get("EXITSTYLE_SIGNALS"), reason="set EXITSTYLE_SIGNALS to the 5-year signal cache")
def test_real_slice_ladder_reproduces_committed_levstop_rows():
    sig = os.environ["EXITSTYLE_SIGNALS"]
    want = json.load(open(LEVSTOP_JSON))
    LV._BARS.clear()               # levstop caches one timeframe's bars per process by timeframe, not by folder
    for strategy, tf in (("DOGE", "1h"), ("N15_KC_AO", "4h")):
        s, t, rows, sums, lv_row, ok, _sec = ES.job((sig, strategy, tf, want["n_boot"]))
        assert ok and json.loads(json.dumps(lv_row)) == want["cells"][f"{strategy}|{tf}"]["tiers|2.0"]


# ---------------------------------------------------------------- fixed TP on synthetic paths
LEV, LIQ, FBAR = 10.0, 0.09, 0.0001


def _path(rows, atr=1.0):
    """Bars from (o, h, l, c) rows; the signal is bar 0, entry at the open of bar 1 (100), ATR(bar 0) = ``atr``."""
    o, h, lo, c = (np.array(x, float) for x in zip(*rows))
    n = len(o)
    return {"ts": np.arange(n, dtype=np.int64), "o": o, "h": h, "l": lo, "c": c, "atr": np.full(n, atr)}


def _run(b, side, tp_r, ladder=False):
    r = ES.scan(b, np.array([0]), np.array([side]), np.array([LEV]), np.array([LIQ]), len(b["o"]) - 1, len(b["o"]),
                FBAR, 2.0, tp_r=tp_r, ladder=ladder)
    return {k: v[0] for k, v in r.items()}


def _roe(side, exit_raw, held):
    fill = 100.0 * (1 + side * SLIP)
    px = exit_raw * (1 - side * SLIP)
    return LEV * (side * (px / fill - 1) - FEE * (1 + px / fill) - FBAR * held)


FLAT = (100.0, 100.4, 99.6, 100.0)


def test_long_tp_hit_exits_at_the_tp_price():
    # stop 98, TP 1R = 102, touched on the 3rd bar after the signal
    b = _path([FLAT, (100, 101, 99.5, 100.5), (100.5, 101.5, 99.8, 101), (101, 102.5, 100.8, 102.2), FLAT])
    r = _run(b, 1, 1.0)
    assert r["done"] and r["reason"] == 4 and r["held"] == 3
    assert r["roe"] == pytest.approx(_roe(1, 102.0, 3), rel=1e-12) and r["roe"] > 0
    # 1.5R = 103 is never touched: no exit inside the path
    assert not _run(b, 1, 1.5)["done"]


def test_same_bar_stop_and_tp_is_a_stop():
    b = _path([FLAT, (100, 101, 99.5, 100.5), (100.5, 102.5, 97.9, 101), FLAT])     # bar touches 98 and 102
    r = _run(b, 1, 1.0)
    assert r["reason"] == 0 and r["held"] == 2 and r["roe"] == pytest.approx(_roe(1, 98.0, 2), rel=1e-12)
    # the same with the ladder on: still the stop
    assert _run(b, 1, 1.0, ladder=True)["reason"] == 0
    # short mirror: stop 102, TP 98
    r = _run(b, -1, 1.0)
    assert r["reason"] == 0 and r["roe"] == pytest.approx(_roe(-1, 102.0, 2), rel=1e-12)


def test_short_tp_and_no_favourable_gap_credit():
    # short: TP 1R = 98; the 3rd bar opens at 97 (beyond the TP): exit is still booked at 98
    b = _path([FLAT, (100, 100.5, 99, 99.5), (99.5, 99.8, 98.5, 99), (97, 97.5, 96.5, 97), FLAT])
    r = _run(b, -1, 1.0)
    assert r["reason"] == 4 and r["held"] == 3 and r["roe"] == pytest.approx(_roe(-1, 98.0, 3), rel=1e-12)
    # long on the same path: stop 98 gapped through at the open 97 -> exit at the open (as profiles._scan)
    r = _run(b, 1, 1.0)
    assert r["reason"] == 0 and r["roe"] == pytest.approx(_roe(1, 97.0, 3), rel=1e-12)


def test_stop_stays_at_2_atr_without_ladder_and_ladder_tp_cap():
    # rises to +1.6% (net ROE at 10x ~ +14% -> lock 10% armed), dips to 101.0, then runs to 104.5
    path = [FLAT, (100, 101.0, 99.8, 100.8), (100.8, 101.6, 100.7, 101.4), (101.4, 101.5, 101.0, 101.2),
            (101.2, 104.5, 101.1, 104.2), FLAT]
    b = _path(path)
    lad = _run(b, 1, None, ladder=True)
    assert lad["reason"] == 1 and lad["held"] == 3                        # the lock (from the next bar) takes it
    assert _run(b, 1, 2.0, ladder=True)["reason"] == 1                   # ladder_tp2R: the lock comes first here
    r = _run(b, 1, 2.0)                                                   # tp2R: no lock, stop still 98 -> TP 104
    assert r["reason"] == 4 and r["held"] == 4 and r["roe"] == pytest.approx(_roe(1, 104.0, 4), rel=1e-12)
    # ladder_tp2R on a straight run to 104: the cap takes it
    b2 = _path([FLAT, (100, 101, 99.9, 100.9), (100.9, 104.3, 100.8, 104.1), FLAT])
    r = _run(b2, 1, 2.0, ladder=True)
    assert r["reason"] == 4 and r["roe"] == pytest.approx(_roe(1, 104.0, 2), rel=1e-12)
    assert _run(b2, 1, None, ladder=True)["reason"] != 4


# ---------------------------------------------------------------- the committed result
def test_committed_result_is_full_small_pre_registered_and_self_checked():
    if not os.path.exists(OUT_JSON):
        pytest.skip("no committed result")
    assert os.path.getsize(OUT_JSON) < 2_000_000
    doc = json.load(open(OUT_JSON))
    line = open(os.path.join(HERE, "PREREG_EXITSTYLE.sha256")).read().split()
    assert doc["version"] == 1 and doc["prereg"]["sha256"] == line[0]
    assert doc["grid"].startswith("full") and len(doc["cells"]) == 180
    st = doc["self_test"]
    assert st["scan_all_identical"] and st["levstop_rows_compared"] >= 170
    assert st["levstop_rows_identical"] == st["levstop_rows_compared"] and not st["levstop_mismatch"]
    dec = doc["summary"]["decision"]
    assert set(dec["arms"]) == set(ES.CANDIDATES) and dec["recommend"] in ES.ARMS
    assert doc["runtime_s"]["total"] < 30 * 60
    assert os.path.exists(os.path.join(HERE, "out", "SUMMARY_KO.md"))
