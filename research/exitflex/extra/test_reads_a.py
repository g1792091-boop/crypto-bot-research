"""Tests of research/exitflex/extra/reads_lib.py, reads_a.py and reads.py on SYNTHETIC data only (PREREG_EXITFLEX_EXTRA.md E.6).

    python -m pytest -q research/exitflex/extra/test_reads_a.py

The synthetic pinned select stage is test_common's ``xw`` fixture (A's own code on a two-coin, four-pick world with E0 and three
variants). Nothing here reads a real result, the real work folder or A's out/ folder, and nothing prints a figure.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
XDIR = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(XDIR))
for _p in (HERE, XDIR, ROOT, os.path.join(ROOT, "research", "fullgrid")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common as XC  # noqa: E402
import data_x as DX  # noqa: E402
import kernel_x as KX  # noqa: E402
import metrics as MT  # noqa: E402
import reads_lib as RL  # noqa: E402
import runner_x as RX  # noqa: E402
from test_common import ARMS, CORE_OK, DS_OK, xw  # noqa: E402,F401  (the synthetic pinned select stage)
from test_exitflex import vendor  # noqa: E402,F401


def prep(ctx, xw):  # noqa: F811
    """The synthetic world's market and chart builder (the real run uses the cut and the pinned providers)."""
    ctx.__dict__["market"] = xw.cfg.market
    ctx.__dict__["make_pickdata"] = xw.cfg.make_pickdata
    return ctx


@pytest.fixture(scope="module")
def sctx(xw):  # noqa: F811
    return prep(XC.load_ctx(xw.lay, allow_select=True), xw)


def all_accounts(xw):  # noqa: F811
    for p in xw.cfg.picks:
        for arm in ["E0"] + ARMS:
            for size in (0.25, 1.0):
                yield p, arm, size


# ====================================================================================================== C5
def test_c5_status_rebuilds_the_kernels_status_of_every_signal(xw, sctx):  # noqa: F811
    n = 0
    for p, arm, size in all_accounts(xw):
        st = RL.c5_status(sctx, p, arm, size)
        res = KX.simulate(xw.cfg.market, xw.cfg.make_pickdata(p), KX.variant_by_id(arm), size, "select")
        assert np.array_equal(st["status"], res.status) and np.array_equal(st["q"], np.flatnonzero(res.status == 1))
        acc = XC.account(sctx, p, arm, size)
        assert np.array_equal(st["t_fill"][st["q"]], acc["tr_fill"]) and not st["rerun"]
        n += 1
    assert n == 32


def test_c5_walk_frees_the_rule_exit_minute_and_stops_after_a_bust():
    # two coins; trade 0 on coin 0 exits by RULE at minute 10 (free from 10), trade 1 fills at 10; then a bust
    sig_coin = np.array([0, 1, 0, 0, 1, 0], np.int64)
    t_fill = np.array([1, 5, 10, 20, 30, 40], np.int64)
    nofill = np.array([False, False, False, False, False, True])
    tr = dict(tr_coin=np.array([0, 0], np.int64), tr_fill=np.array([1, 10], np.int64), tr_exit=np.array([10, 25], np.int64),
              tr_free=np.array([True, False]), tr_open=np.array([False, False]), tr_pnl=np.array([0.0, -4995.0]))
    st, q, k = RL._c5_walk(sig_coin, t_fill, nofill, tr["tr_coin"], tr["tr_fill"], tr["tr_exit"], tr["tr_free"], tr["tr_open"], tr["tr_pnl"],
                           5000.0, 10.0)
    assert st.tolist() == [1, 0, 1, 4, 4, 3] and q.tolist() == [0, 2] and k == 2


def test_c5_status_refuses_a_file_it_cannot_match(xw, sctx):  # noqa: F811
    p = xw.core[0]
    acc = dict(XC.account(sctx, p, "E0", 0.25))
    acc["tr_fill"] = np.asarray(acc["tr_fill"]) + 60_000
    with pytest.raises(AssertionError):
        RL.c5_status(sctx, p, "E0", 0.25, acc=acc)


def test_c5_duplicate_coin_fill_minutes_use_a_real_rerun(xw, sctx):  # noqa: F811
    p = xw.core[0]
    pdata = xw.cfg.make_pickdata(p)
    off = pdata.offered("select", xw.cfg.market)
    idx = np.r_[np.arange(len(off["coin"])), [3]]                     # signal 3 offered twice: same coin and fill minute
    idx.sort(kind="stable")
    off2 = XC.mask_offered(off, np.ones(len(off["coin"]), bool))
    off2 = {k: v[idx] for k, v in off2.items()}
    res = KX.simulate(xw.cfg.market, pdata, KX.E0, 0.25, "select", offered=off2)
    acc = {**MT.summarize(res, sctx.edges), "arm": "E0", "size": 0.25, "money_ok": True}
    st = RL.c5_status(sctx, p, "E0", 0.25, acc=acc, off=off2)
    assert st["rerun"] and np.array_equal(st["status"], res.status)


def test_c5_audit_reruns_and_saves_reduced_files(xw, sctx):  # noqa: F811
    out = RL.c5_audit(sctx, arms=("E0", "F1.w3.a"))
    assert out["accounts"] == 4 * 2 * 2 and out["bad"] == [] and out["bytes"] > 0
    assert os.path.exists(XC.reduced_path(sctx, xw.ds[0], "c5audit", 0.25, "E0"))
    assert XC.reduced_path(sctx, xw.ds[0], "c5audit", 0.25, "E0").startswith(sctx.private_dir)


# ====================================================================================================== C4
def test_c4_trade_frame_reproduces_sizing_and_the_log_identity(xw, sctx):  # noqa: F811
    n = 0
    for p, arm, size in all_accounts(xw):
        acc = XC.account(sctx, p, arm, size)
        fr = RL.c4_trade_frame(sctx, p, acc)
        off = RL.offered(sctx, p)
        assert np.array_equal(fr["t_sig"], off["close"][fr["q"]]) and np.all(fr["e"] < fr["x"] + 1)
        ts = [RL.coin_ts(sctx, c) for c in range(2)]
        assert all(ts[c][e] == f for c, e, f in zip(fr["coin"], fr["e"], acc["tr_fill"]))
        assert all(ts[c][x] == t for c, x, t in zip(fr["coin"], fr["x"], acc["tr_exit"]))
        if not acc["money_ok"]:
            assert "l" not in fr and "R" not in fr and "ROE" not in fr
            continue
        assert np.allclose(fr["Wb"], acc["wallet_before"], rtol=0, atol=1e-6) and np.array_equal(fr["lev"], acc["tr_lev"])
        assert abs(fr["l"].sum() - math.log(acc["w_end"] / acc["w0"])) < 1e-9
        assert np.allclose(fr["R"] * fr["qty"] * fr["Rd"], acc["tr_pnl"]) and np.allclose(fr["ROE"] * fr["margin"], acc["tr_pnl"])
        S = xw.cfg.market.S(size)
        assert np.allclose(fr["fill"], fr["raw"] * (1 + fr["side"] * S[1]))
        n += len(fr["l"])
    assert n > 200


def test_excursions_bound_the_exit_and_never_read_the_exit_minute(xw, sctx):  # noqa: F811
    p = xw.core[0]
    acc = XC.account(sctx, p, "E0", 0.25)
    fr = RL.c4_trade_frame(sctx, p, acc)
    ex = RL.excursions(sctx, p, fr)
    S = xw.cfg.market.S(0.25)
    rn_exit = (fr["side"] * (fr["xpx"] - fr["fill"]) - fr["fill"] * S[5]) / fr["Rd"]
    liq = fr["reason"] == KX.R_LIQ
    assert np.all(ex["R_best"][~liq] >= rn_exit[~liq] - 1e-12) and np.all(ex["R_worst"][~liq] <= rn_exit[~liq] + 1e-12)
    assert np.all(ex["ROE_best"] >= ex["ROE_worst"])
    mk = xw.cfg.market
    i = int(np.argmax(fr["x"] - fr["e"]))
    a = mk.starts[fr["coin"][i]]
    h = mk.cat["h"][a + fr["e"][i]:a + fr["x"][i]]
    l = mk.cat["l"][a + fr["e"][i]:a + fr["x"][i]]
    fav = h.max() if fr["side"][i] > 0 else l.min()
    assert ex["fav_px"][i] == fav
    h2, l2 = mk.cat["h"].copy(), mk.cat["l"].copy()                     # changing the exit minute's own range changes nothing
    mk.cat["h"][a + fr["x"][i]] = 1e9
    mk.cat["l"][a + fr["x"][i]] = 1e-9
    try:
        ex2 = RL.excursions(sctx, p, fr)
    finally:
        mk.cat["h"][:], mk.cat["l"][:] = h2, l2
    assert all(np.array_equal(ex[k], ex2[k], equal_nan=True) for k in ex)
    lo, hi = RL.open_dd_range(fr, ex, acc["w0"])
    assert 0 <= lo <= hi <= 1
    with pytest.raises(XC.Refused):
        RL.excursions(sctx, p, RL.c4_trade_frame(sctx, xw.core[0], XC.account(sctx, xw.core[0], "F3.a", 0.25)))


def test_c4_match_classes_add_up_to_the_contracts_changed_trades(xw, sctx):  # noqa: F811
    for p in xw.cfg.picks:
        e0 = XC.account(sctx, p, "E0", 0.25)
        m0 = RL.c4_match(e0, e0)
        assert m0["n_same"] == m0["n_v"] and m0["n_drop"] == 0
        for arm in ARMS:
            v = XC.account(sctx, p, arm, 0.25)
            m = RL.c4_match(v, e0)
            assert m["n_same"] + m["n_exit"] + m["n_new"] == m["n_v"] == len(v["tr_pnl"])
            assert m["n_exit"] + m["n_new"] == MT.changed_trades(v, e0)
            assert m["n_drop"] == m["n_e0"] - (m["n_same"] + m["n_exit"])
            j = m["e0_idx"][m["cls"] == RL.SAME]
            assert np.array_equal(e0["tr_exit"][j], v["tr_exit"][m["cls"] == RL.SAME])


def test_cut_column_reads_the_close_and_checks_the_cut(xw, sctx):  # noqa: F811
    c = RL.cut_column(sctx, DX.SYMBOLS[0], "c")
    ts = RL.cut_column(sctx, DX.SYMBOLS[0], "ts")
    assert len(c) == len(ts) > 1000 and ts[-1] < DX.SELECT_CUT_MS and not c.flags.writeable


# ====================================================================================================== X-025 helpers
def test_realised_wallet_counts_rule_exits_at_the_fill_minute():
    acc = {"w0": 100.0, "tr_exit": np.array([10, 20, 30]), "tr_pnl": np.array([1.0, 2.0, 4.0]),
           "tr_reason": np.array([KX.R_SL, KX.R_RULE, KX.R_TP])}
    assert RL.realised_wallet(acc, [5, 10, 11, 20, 21, 30, 31]).tolist() == [100, 100, 101, 103, 103, 103, 107]


def test_sizeable_and_the_entry_ceiling(xw, sctx):  # noqa: F811
    for p in xw.cfg.picks:
        sz = RL.sizeable(sctx, p, "E0", 0.25)
        st = RL.c5_status(sctx, p, "E0", 0.25)
        assert len(sz["q"]) == int((st["status"] == 0).sum()) and sz["sizeable"].dtype == bool
        ceil = RL.entry_ceiling(sctx, p, 0.25)
        assert ceil >= int((st["status"] == 1).sum()) * 0 and ceil >= 1
        assert RL.entry_ceiling(sctx, p, 0.25, 15 * 60_000) >= ceil
    with pytest.raises(XC.Refused):
        RL.sizeable(sctx, xw.core[0], "F3.a", 0.25)                      # 선택 불가 in core: money (C8)


# ====================================================================================================== C9
def test_c9_split_by_coin_adds_up_and_keeps_money_off_unchoosable_rows(xw, sctx):  # noqa: F811
    key = lambda c: c["coin"]  # noqa: E731
    for pool, arm in (("core", "F1.w3.a"), ("core", "E0"), ("ds", "F3.a")):
        t = RL.c9_split(sctx, pool, arm, key, 0.25, buckets=[0, 1])
        assert t["signal_level"] and [c["bucket"] for c in t["cells"]] == [0, 1]
        n_tr = sum(len(XC.account(sctx, p, arm, 0.25)["tr_pnl"]) for p in sctx.pool_picks(pool))
        assert sum(c["n"] for c in t["cells"]) == n_tr == sum(c["n_ent"] for c in t["cells"])
        offered_n = sum(MT.count(XC.account(sctx, p, arm, 0.25), "offered") for p in sctx.pool_picks(pool))
        assert sum(c["n_off"] for c in t["cells"]) == offered_n
        assert abs(sum(m["dc"] for m in t["money"]) - 100 * XC.pooled_M(sctx, pool, arm)) < 1e-9
    t = RL.c9_split(sctx, "core", "F3.a", key, 0.25)
    assert t["money"] is None
    t = RL.c9_split(sctx, "core", "E0", lambda c: c["hold_h"] > 8)     # a trade-level key
    assert not t["signal_level"] and all(c["n_off"] is None for c in t["cells"])
    with pytest.raises(ValueError):
        RL.c9_split(sctx, "core", "E0", key, 0.25, buckets=[0])
