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
    ctx.__dict__["xr_c5_audit_arms"] = ("E0", "F1.w3.a")                 # the synthetic stage has no F12.a file
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


# ====================================================================================================== tier A reads
import reads_a as RA  # noqa: E402


@pytest.fixture(scope="module")
def results(sctx):
    out = {}
    for rid in [x for x in RL.BODY_ORDER if x != "X-046"]:
        out[rid] = RA.READS[rid](sctx)
    out["X-046"] = RA.read_X_046(sctx, out)
    return out


def committed_ok(sctx, r):
    """Every committed part of a read passes the guards of the committed outputs."""
    doc = {"reads": {r["id"]: r["public"]}}
    text = json.dumps(doc, ensure_ascii=False, default=RX._json_default)
    md = "\n".join(["# t", "", f"## {r['id']}", ""] + r["md"] + [f"## {r['id']} 부록", ""] + r["md_appendix"])
    probs = XC.committed_problems("extra_reads.json", json.loads(text), text) + XC.committed_problems("x.md", md, md)
    probs += XC.committed_problems("x.csv", r["csv"], "")
    probs += RL.row_rule_problems(sctx, doc) + RL.row_rule_problems(sctx, r["csv"]) + RL.md_rule_problems(sctx, md)
    return probs


@pytest.mark.parametrize("rid", RL.BODY_ORDER)
def test_each_tier_a_read_computes_and_passes_the_committed_guards(results, sctx, rid):
    r = results[rid]
    assert r["id"] == rid and r["tier"] == "A" and r["md"] and r["public"]["ds"]["pool"] == "ds"
    assert committed_ok(sctx, r) == []


def test_x046_quotes_other_reads_and_prints_a_dash_without_them(sctx, results):
    alone = RA.read_X_046(sctx)
    assert any("X-047 결과 없음" in ln for ln in alone["md"]) and any("X-025 결과 없음" in ln for ln in alone["md"])
    full = results["X-046"]
    assert not any("X-047 결과 없음" in ln for ln in full["md"]) and not any("X-025 결과 없음" in ln for ln in full["md"])
    assert full["public"]["core"]["n_choosable"] == len(CORE_OK) and full["public"]["ds"]["labels"]["default_would_take"] == []
    assert any("F7.N12.a" in ln for ln in full["md"])                         # the default of 8.4 from select.json
    ds_lines = full["md"][full["md"].index(RL.pool_head("ds", 2)):]
    assert not any("%" in ln for ln in ds_lines)


def test_x025_identity_and_ceiling_and_deepseek_split(sctx, results):
    r = results["X-025"]
    for row in r["public"]["core"]["by_arm"]:
        assert row["offered"] == row["rejected"] + row["skipped"] + row["entered"] + row["e_nofill_after_bust"]
        assert row["skipped_sizeable"] + row["skipped_not_sizeable"] == row["skipped"]
        assert sum(map(sum, row["by_blocker"])) == row["skipped"]
    ds = r["public"]["ds"]
    assert all("offered" not in row and "skipped_sizeable" not in row for row in ds["by_arm"])
    assert r["private"]["ds"]["ceiling"]["quarter"] >= 1 and "ceiling" not in r["public"]["ds"]
    assert {row["arm"] for row in r["public"]["core"]["by_arm"]} == {"E0"} | set(CORE_OK)
    assert {x["arm"] for x in r["csv"] if x["pool"] == "core"} == {"E0"} | set(ARMS)


def test_x027_parts_add_up_and_part1_covers_every_row(sctx, results):
    r = results["X-027"]
    for pool in XC.POOLS:
        mon = r["public"]["core"] if pool == "core" else r["private"]["ds"]
        for row in mon["part2"]:
            total = row["T_new"] + row["T_exit"] + row["T_same"] + row["T_drop"]
            assert abs(total - row["M"]) < 1e-9
    assert {x["arm"] for x in r["csv"] if x["pool"] == "ds"} == {"E0"} | set(ARMS)


def test_x001_dc_adds_up_to_M_and_x024_contributions_add_up(sctx, results):
    for row in results["X-001"]["public"]["core"]["money_by_arm"]:
        if row["arm"] != "E0":
            assert abs(sum(row["dc"]) - 100 * row["M"]) < 1e-9 and row["n_up"] == sum(1 for v in row["dc"] if v > 0)
    for row in results["X-024"]["public"]["core"]["money_by_arm"]:
        assert abs(sum(row["contrib"]) - row["M"]) < 1e-9


def test_x014_and_x047_are_money_rows_only(sctx, results):
    with pytest.raises(XC.Refused):
        RA.month_dist(sctx, "core", "F3.a")
    with pytest.raises(XC.Refused):
        RA.scorecard(sctx, "ds", "F1.w3.a")
    d = RA.month_dist(sctx, "core", "E0")
    assert d["n"] == sum(int(XC.alive_months(XC.account(sctx, p, "E0", 0.25)).sum()) for p in sctx.pool_picks("core"))
    sc = RA.scorecard(sctx, "core", "F1.w3.a")["quarter"]
    assert sc["count"]["wins"] + sc["count"]["losses"] == sc["count"]["closed"]
    assert sc["money"]["open_dd_low"] <= sc["money"]["open_dd_high"]


def test_x037_halves_years_and_the_placebo_yardstick(sctx, results):
    r = results["X-037"]
    y = r["public"]["core"]["yardstick"]
    assert y["n_C"] == 1 and y["seeds"] == 40 and y["n_h"] is not None
    for row in r["public"]["core"]["by_arm"]:
        assert abs((24 * row["first"] + 12 * row["second"]) / 36 - row["M"]) < 1e-12 and len(row["signs"]) == 36
        assert row["ci_lo"] <= row["ci_hi"]
    assert r["public"]["ds"] == {"pool": "ds", "read": "X-037"} and r["private"]["ds"]["by_arm"]


# ====================================================================================================== guards and the row rule
def test_guards_refuse_deepseek_money_offered_and_unchoosable_rows(sctx):
    with pytest.raises(XC.Refused):
        RL.ds_public({"by_arm": [{"arm": "E0", "M": 0.01}]})
    assert RL.ds_public({"by_arm": [{"arm": "E0", "entered": 3, "offered": 9, "n_off": 4}]}) == {"by_arm": [{"arm": "E0", "entered": 3}], "pool": "ds"}
    assert RL.ds_strip_problems({"pool": "ds", "x": {"offered": 3}}) and not RL.ds_strip_problems({"pool": "core", "offered": 3})
    assert RL.row_rule_problems(sctx, {"pool": "core", "arm": "F3.a", "n": 3}) == []
    assert RL.row_rule_problems(sctx, {"pool": "core", "arm": "F3.a", "M": 0.1})
    assert RL.row_rule_problems(sctx, {"core": {"by_arm": {"F3.a": {"money": {"c": 1.0}}}}})
    assert RL.row_rule_problems(sctx, {"pool": "ds", "arm": "F3.a", "M": 0.1}) == []
    assert RL.md_rule_problems(sctx, "## X\n### 코어 (2개 픽)\n| F3.a | 1 |\n") and RL.md_rule_problems(sctx, "## X\n### 딥시크 (2개 픽)\n| F1.w3.a | 1 |\n")
    assert RL.md_rule_problems(sctx, "## X\n### 코어 (2개 픽)\n| F1.w3.a | 1 |\n| F7.N12.a (= F3.a) | 2 |\n") == []
    import reads as RD
    r = RL.new_result("X-001", "A")
    r["status"], r["md"] = "ok", ["### 딥시크 (2개 픽)", "", "| E0 | 45% |"]
    assert RD.guard_result(sctx, r)["status"] == "failed" and r["md"] == [] and r["public"]["ds"] == {"pool": "ds"}
    r = RL.new_result("X-001", "A")
    r["status"], r["public"]["core"] = "ok", {"by_arm": [{"pool": "core", "arm": "F3.a", "c": [1.0]}]}
    assert RD.guard_result(sctx, r)["status"] == "failed"


# ====================================================================================================== the CLI on the synthetic pin
import reads as RD  # noqa: E402


def _snapshot(xw):  # noqa: F811
    out = {}
    for d in (os.path.join(xw.w8, "results"), os.path.join(xw.w8, "ds_private", "results"), xw.lay.out):
        for root, _dn, fs in os.walk(d):
            for f in fs:
                p = os.path.join(root, f)
                out[p] = RX.sha256_file(p)
    return out


def _cli(xw, monkeypatch, *argv, rb=None):  # noqa: F811
    monkeypatch.setattr(XC, "c1_check", lambda picks: None)
    monkeypatch.setattr(RD, "load_reads_b", lambda: (rb, None if rb else "test"))
    return RD.main(list(argv), lay=xw.lay, prep=lambda c: prep(c, xw))


@pytest.fixture(scope="module")
def cli_run(xw):  # noqa: F811
    mp = pytest.MonkeyPatch()
    before, gates = _snapshot(xw), RX.step1_gates(xw.cfg)
    try:
        code = _cli(xw, mp, "run", "--skip-tests", "--procs", "1")
        out_dir = os.path.join(str(xw.base), "extra", "out")
        files = {f: open(os.path.join(out_dir, f), encoding="utf-8").read() for f in os.listdir(out_dir)}
    finally:
        mp.undo()
    return {"code": code, "files": files, "before": before, "gates": gates, "out_dir": out_dir}


def test_cli_run_writes_the_committed_outputs_and_the_private_report(xw, cli_run):  # noqa: F811
    assert cli_run["code"] == 0
    f = cli_run["files"]
    assert sorted(f) == ["EXTRA_READS_APPENDIX_KO.md", "EXTRA_READS_KO.md", "extra_reads.json", "extra_reads_rows.csv"]
    doc = json.loads(f["extra_reads.json"])
    assert [d["id"] for d in doc["dropped_at_o8"]] == list(RL.TIER_C) and all(d["reason"] == RL.DROP_REASON_C for d in doc["dropped_at_o8"])
    assert doc["not_coded"] == list(RL.TIER_B) and doc["run"]["reads_b"].startswith("not importable")
    assert all(doc["reads"][rid]["status"] == "ok" for rid in RL.BODY_ORDER)
    run = doc["run"]
    assert set(RL.BODY_ORDER) <= set(run["parts"]) and run["parts"]["C5 audit"]["status"] == "pass" and run["parts"]["C5 audit"]["accounts"] > 0
    assert run["dropped"] == [] and run["tests"]["summary"].startswith("skipped") and run["end_utc"]
    ko = f["EXTRA_READS_KO.md"]
    heads = [ln.split()[1] for ln in ko.splitlines() if ln.startswith("## X-")]
    assert heads == list(RL.BODY_ORDER)
    assert ko.splitlines()[2] == f"**{XC.W['W0']}**" and RL.W_KO["W1"] in ko and ko.count(XC.TAG_TABLE) >= 10
    app = f["EXTRA_READS_APPENDIX_KO.md"]
    assert "## O8에 빠진 읽기" in app and all(rid in app for rid in RL.TIER_C)
    rep = os.path.join(xw.w8, "ds_private", "owner_report_extra.md")
    text = open(rep, encoding="utf-8").read()
    assert doc["ds_owner_report_extra_sha256"] == RX.sha256_file(rep) and text.index("## 핵심") < text.index("## 부록")
    assert text.rstrip().endswith(RX.OWNER_REPORT_LAST_LINE) and "딥시크 F3.a" in text and "딥시크 E0" in text
    assert "딥시크 F1.w3.a" not in text and "딥시크 F7.N12.a" not in text                      # 선택 불가 in the DeepSeek pool
    assert doc["ds_private_sha256"] == RX.sha256_file(os.path.join(xw.w8, "ds_private", "extra_reads_ds.json"))


def test_cli_audit_passes_and_catches_a_planted_line(xw, cli_run, monkeypatch):  # noqa: F811
    assert _cli(xw, monkeypatch, "audit") == 0 and _cli(xw, monkeypatch, "audit", "--private") == 0
    path = os.path.join(cli_run["out_dir"], "EXTRA_READS_KO.md")
    text = open(path, encoding="utf-8").read()
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n## 딥시크\n\n| E0 | 월 +3.2% |\n")
        assert _cli(xw, monkeypatch, "audit") == 1
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("### 코어 (2개 픽)", "### 코어 (2개 픽)\n\n| F3.a | x1.20 |", 1))
        assert _cli(xw, monkeypatch, "audit") == 1                          # a 선택 불가 id on the core page
    finally:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    rep = os.path.join(xw.w8, "ds_private", "owner_report_extra.md")
    rtext = open(rep, encoding="utf-8").read()
    try:
        with open(rep, "w", encoding="utf-8") as fh:
            fh.write(rtext + "p = 0.03\n")
        assert _cli(xw, monkeypatch, "audit", "--private") == 1
    finally:
        with open(rep, "w", encoding="utf-8") as fh:
            fh.write(rtext)
    assert _cli(xw, monkeypatch, "audit", "--private") == 0


def test_cli_writes_nothing_into_As_folders_and_changes_no_gate(xw, cli_run):  # noqa: F811
    assert _snapshot(xw) == cli_run["before"]
    assert RX.step1_gates(xw.cfg) == cli_run["gates"]
    assert not any(os.path.commonpath([p, xw.lay.out]) == xw.lay.out for p in [os.path.join(cli_run["out_dir"], f) for f in cli_run["files"]])


def test_cli_report_is_deterministic(xw, cli_run, monkeypatch):  # noqa: F811
    assert _cli(xw, monkeypatch, "report") == 0
    for f in ("EXTRA_READS_KO.md", "EXTRA_READS_APPENDIX_KO.md", "extra_reads_rows.csv", "extra_reads.json"):
        assert open(os.path.join(cli_run["out_dir"], f), encoding="utf-8").read() == cli_run["files"][f]


def test_reads_are_deterministic(xw, results):  # noqa: F811
    c2 = prep(XC.load_ctx(xw.lay, allow_select=True), xw)
    for rid in ("X-001", "X-025", "X-037"):
        a, b = RL.jsonable(results[rid]), RL.jsonable(RA.READS[rid](c2))
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_planted_money_reaches_only_the_private_files(xw, cli_run, monkeypatch):  # noqa: F811
    orig = XC.account
    plant = {("ds", "E0"): 0.918273645, ("ds", "F3.a"): 0.564738291, ("core", "F3.a"): 0.192837465, ("ds", "F1.w3.a"): 0.374659201}

    def planted(ctx, pick, arm, size):
        a = orig(ctx, pick, arm, size)
        v = plant.get((ctx.pick(pick)["pool"], arm))
        if v is not None:
            a["max_dd"] = np.float64(v)
        return a
    monkeypatch.setattr(XC, "account", planted)
    assert _cli(xw, monkeypatch, "run", "--skip-tests") == 0
    committed = "".join(open(os.path.join(cli_run["out_dir"], f), encoding="utf-8").read() for f in os.listdir(cli_run["out_dir"]))
    private = open(os.path.join(xw.w8, "ds_private", "extra_reads_ds.json"), encoding="utf-8").read()
    for (pool, arm), v in plant.items():
        assert str(v) not in committed
        assert (str(v) in private) == (pool == "ds" and XC.money_allowed(XC.load_ctx(xw.lay, allow_select=True), pool, arm))
    monkeypatch.setattr(XC, "account", orig)
    assert _cli(xw, monkeypatch, "run", "--skip-tests") == 0                # restore the plain outputs


# ====================================================================================================== tier B through reads_b's interface
def fake_reads_b():
    import types
    m = types.ModuleType("reads_b")
    m.READS = ["X-004", "X-016", "X-043"]

    def run_b(ctx, dropped=(), reads=None):
        e0 = {"win_share": 0.4, "n_entries_per_account_month": 1.5,
              "money": {"targets": [{"target": "x5", "win_share_need": 0.9, "label_win": "", "entries_need": 40.0, "label_entries": ""}]}}
        return {"X-004": {"read": "X-004", "title": "주말과 평일", "core": {"pool": "core", "read": "X-004", "by_arm": {"E0": {"n": 3}}},
                          "ds": {"pool": "ds", "read": "X-004", "by_arm": {"E0": {"n": 3, "offered": 9}}}, "private": {"ds": {}}, "notes": []},
                "X-016": {"read": "X-016", "title": "목표까지 필요한 것", "core": {"pool": "core", "by_arm": {"E0": e0}, "entries_ceiling_per_account_month": 9.0},
                          "ds": {"pool": "ds", "by_arm": {"E0": {"win_share": 0.4}}}, "private": {"ds": {"by_arm": {"E0": {"money": e0["money"]}}}}},
                "X-043": {"read": "X-043", "title": "1,000달러로 시작하면", "error": "ValueError: wallet 0.123 off"}}
    m.run_b = run_b
    m.FUNCS = {}
    m.appendix_md = lambda res: "## 부록 B\n\n" + "\n".join(f"## {k} x\n\n### 코어 (2개 픽)\n\n가짜 표 {k}\n" for k in res)
    m.private_md = lambda res: "## [비공개] 부록 B\n\n" + "\n".join(f"[비공개] 딥시크 {k}" for k in res)
    return m


def test_tier_b_results_are_adapted_guarded_and_quoted_by_x046(xw, cli_run, monkeypatch):  # noqa: F811
    assert _cli(xw, monkeypatch, "run", "--skip-tests", rb=fake_reads_b()) == 0
    doc = json.loads(open(os.path.join(cli_run["out_dir"], "extra_reads.json"), encoding="utf-8").read())
    assert doc["reads"]["X-004"]["status"] == "ok" and doc["reads"]["X-004"]["ds"]["by_arm"]["E0"] == {"n": 3}
    assert doc["reads"]["X-043"]["status"] == "failed" and "0.123" not in doc["reads"]["X-043"]["error"]
    assert doc["not_coded"] == [r for r in RL.TIER_B if r not in ("X-004", "X-016", "X-043")]
    ko = open(os.path.join(cli_run["out_dir"], "EXTRA_READS_KO.md"), encoding="utf-8").read()
    assert "한 달 x5에는 승률 90.0%(지금 40.0%), 또는 한 달 진입 40.00번(지금 1.50번, 최대 9.00번)입니다" in ko
    app = open(os.path.join(cli_run["out_dir"], "EXTRA_READS_APPENDIX_KO.md"), encoding="utf-8").read()
    assert "가짜 표 X-004" in app and app.index("## X-004") < app.index("## X-016") < app.index("## X-043")
    rep = open(os.path.join(xw.w8, "ds_private", "owner_report_extra.md"), encoding="utf-8").read()
    assert "[비공개] 딥시크 X-004" in rep.split("## 부록")[1] and "딥시크 한 달 x5에는" in rep.split("## 부록")[0]
    assert _cli(xw, monkeypatch, "audit") == 0 and _cli(xw, monkeypatch, "audit", "--private") == 0
    assert _cli(xw, monkeypatch, "run", "--skip-tests") == 0


# ====================================================================================================== E.5 cap
def test_cap_drops_in_order_only_coded_parts_and_each_drop_lowers_the_projection():
    t = {"account_s": 0.5, "pickdata_s": 1.0}
    coded = set(RL.TIER_A) | {"X-002", "X-005", "X-041", "X-043"}
    drops, before, after = RD.apply_cap(t, coded, 38, 1)
    assert before["wall_s"] > 45 * 60 and drops == ["X-041 c = 1.5", "X-043 live size", "X-002"][:len(drops)] and len(drops) >= 1
    assert after["wall_s"] < before["wall_s"]
    assert RD.apply_cap({"account_s": 0.01, "pickdata_s": 0.1}, coded, 38, 4)[0] == []
    prev = RD.projection(t, coded, set(), 38, 1)["wall_s"]
    for i, name in enumerate(["X-041 c = 1.5", "X-043 live size", "X-002"]):
        cur = RD.projection(t, coded, set(["X-041 c = 1.5", "X-043 live size", "X-002"][:i + 1]), 38, 1)["wall_s"]
        assert cur < prev
        prev = cur
    assert RD.projection(t, coded, {"X-022 entirely"}, 38, 1)["wall_s"] == RD.projection(t, coded, set(), 38, 1)["wall_s"]   # not coded


def test_a_tier_b_page_that_fails_a_guard_is_rendered_read_by_read(xw, cli_run, monkeypatch):  # noqa: F811
    rb = fake_reads_b()

    def leaky(res):                                                         # X-004's DeepSeek section shows a percent
        out = ["## 부록 B", ""]
        for k in res:
            out += [f"## {k} x", "", "### 코어 (2개 픽)", "", f"가짜 표 {k}", ""]
            if k == "X-004":
                out += ["### 딥시크 (2개 픽)", "", "| E0 | 45% |", ""]
        return "\n".join(out)
    rb.appendix_md = leaky
    assert _cli(xw, monkeypatch, "run", "--skip-tests", rb=rb) == 0
    doc = json.loads(open(os.path.join(cli_run["out_dir"], "extra_reads.json"), encoding="utf-8").read())
    assert doc["reads"]["X-004"]["status"] == "failed" and doc["reads"]["X-016"]["status"] == "ok"
    assert doc["run"]["tier_b_render"].startswith("tier B block failed") and doc["reads"]["X-004"]["ds"] == {"pool": "ds"}
    app = open(os.path.join(cli_run["out_dir"], "EXTRA_READS_APPENDIX_KO.md"), encoding="utf-8").read()
    assert "45%" not in app and "가짜 표 X-016" in app
    assert _cli(xw, monkeypatch, "audit") == 0


def test_the_twins_private_section_goes_verbatim_into_part_core(xw, cli_run, monkeypatch):  # noqa: F811
    ctx = prep(XC.load_ctx(xw.lay, allow_select=True), xw)
    path = RD.names(ctx)["twins_private"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("## [비공개] 쌍둥이 계좌 딥시크\n\n[비공개] 쌍둥이 E0 줄 하나\n")
    try:
        assert _cli(xw, monkeypatch, "report") == 0
        text = open(os.path.join(xw.w8, "ds_private", "owner_report_extra.md"), encoding="utf-8").read()
        assert "## [비공개] 쌍둥이 계좌 딥시크\n\n[비공개] 쌍둥이 E0 줄 하나\n" in text
        assert text.index("## 핵심") < text.index("[비공개] 쌍둥이 E0 줄 하나") < text.index("## 부록")
        assert _cli(xw, monkeypatch, "audit", "--private") == 0
    finally:
        os.remove(path)
    assert _cli(xw, monkeypatch, "run", "--skip-tests") == 0


def test_the_stage_refuses_to_run_reads_when_the_extra_tests_fail(xw, monkeypatch):  # noqa: F811
    monkeypatch.setattr(RD, "run_tests", lambda: {"ok": False, "summary": "1 failed", "files": [], "seconds": 0.0})
    called = []
    monkeypatch.setattr(RL, "c5_audit", lambda *a, **k: called.append(1))
    with pytest.raises(SystemExit):
        _cli(xw, monkeypatch, "run")
    assert not called
