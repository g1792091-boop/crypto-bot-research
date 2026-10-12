"""Tests of research/exitflex/extra/reads_b.py (the tier B extra reads, PREREG_EXITFLEX_EXTRA.md E.3) on SYNTHETIC data only.

    python -m pytest -q research/exitflex/extra/test_reads_b.py

The synthetic pinned select stage is test_common's ``xw`` fixture (A's own code on a two-coin, four-pick synthetic world). Nothing here
reads a real result, the real work folder or A's out/ folder, and nothing prints a figure.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
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
import kernel_x as KX  # noqa: E402
import metrics as MT  # noqa: E402
import reads_b as RB  # noqa: E402
import runner_x as RX  # noqa: E402
from test_common import CORE_OK, DS_OK, xw, vendor  # noqa: E402,F401  (the synthetic pinned select stage)

TIER_B = ["X-002", "X-004", "X-005", "X-008", "X-011", "X-015", "X-016", "X-017", "X-018", "X-021", "X-026", "X-028", "X-029", "X-030",
          "X-031", "X-033", "X-034", "X-038", "X-039", "X-041", "X-043"]
COUNT_ALL_ROWS = ("X-004", "X-008", "X-011", "X-021", "X-028", "X-029", "X-033")      # count columns over every row of the select table
DS_FORBIDDEN = {"offered", "n_off", "no_fill", "after_bust", "offered_weekend", "share_offered_weekend"}


# ====================================================================================================== fixtures
def rich_select(xw) -> dict:
    """The fixture's select.json with the fields A's real select.json carries (gates, labels, closed, hold, reasons; E0's entry), built
    from the synthetic result files with A's own metrics.pool_summary."""
    doc = json.load(open(xw.lay.out_file("select.json"), encoding="utf-8"))
    for pool in XC.POOLS:
        P = doc["pools"][pool]
        picks = [p for p in xw.cfg.picks if p["pool"] == pool]
        e0 = {p["id"]: xw.cfg.store.load(p, "E0", "q25") for p in picks}
        s0 = MT.pool_summary(e0, e0)["all"]
        P["e0"] = {"hold": s0["hold"], "reasons": dict(zip(MT.REASONS, s0["reasons"])), "closed": s0["closed"]}
        if pool == "core":
            P["e0"]["max_dd_median"] = s0["max_dd_median"]
        for row in P["variants"]:
            sv = {p["id"]: xw.cfg.store.load(p, row["id"], "q25") for p in picks}
            s = MT.pool_summary(sv, e0)["all"]
            ok = row["id"] in P["eligible_ids"]
            row.update(gates={"g1": "pass" if ok else "fail", "g2": "pass", "g3": "n/a", "g4": "pass"}, label="선택 가능" if ok else "선택 불가",
                       closed=s["closed"], hold=s["hold"], reasons=dict(zip(MT.REASONS, s["reasons"])))
    return doc


def make_ctx(xw, doc=None):
    ctx = XC.load_ctx(xw.lay, allow_select=True)
    ctx.__dict__["market"] = xw.cfg.market
    ctx.pickdata = xw.cfg.make_pickdata                  # the synthetic world's PickData (causal test signals)
    ctx.make_pickdata = xw.cfg.make_pickdata             # the name reads_lib and reads.py look for
    if doc is not None:
        ctx.set_select(doc)
    return ctx


@pytest.fixture(scope="module")
def rdoc(xw):
    return rich_select(xw)


@pytest.fixture(scope="module")
def bctx(xw, rdoc):
    return make_ctx(xw, copy.deepcopy(rdoc))


def listing(xw) -> dict:
    """(path -> sha256) of A's folders: the work folder outside extra/ and ds_private/extra/, and research/exitflex/ outside extra/."""
    out = {}
    for base, skip in ((xw.w8, (os.path.join(xw.w8, "extra"), os.path.join(xw.w8, "ds_private", "extra"))),
                       (str(xw.base), (os.path.join(str(xw.base), "extra"),))):
        for d, _dn, fs in os.walk(base):
            if any(d == s or d.startswith(s + os.sep) for s in skip):
                continue
            for f in fs:
                p = os.path.join(d, f)
                out[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


@pytest.fixture(scope="module")
def run(xw, bctx):
    before = listing(xw)
    res = RB.run_b(bctx)
    return {"res": res, "before": before, "after": listing(xw)}


@pytest.fixture(scope="module")
def results(run):
    return run["res"]


def committed(results: dict) -> dict:
    return {k: {kk: vv for kk, vv in r.items() if kk != "private"} for k, r in results.items()}


def walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


def ds_sections(md: str) -> list:
    out, inside = [], False
    for ln in md.splitlines():
        if ln.startswith("## "):
            inside = "딥시크" in ln
        if inside:
            out.append(ln)
    return out


# ====================================================================================================== the list, every read computes
def test_reads_are_the_21_tier_b_reads_in_order():
    assert RB.READS == TIER_B and len(RB.READS) == 21
    assert set(RB.FUNCS) == set(RB.TITLES) == set(RB.MD) == set(TIER_B)
    assert set(RB.FALLBACKS_USED) <= set(RB.LIB_NAMES) and RB.DROPPED_AT_O8 == {}
    assert RB.USE_LIB == (RB.RL is not None and not RB.FALLBACKS_USED)
    if RB.RL is not None:
        assert tuple(RB.RL.TIER_B) == tuple(TIER_B)                       # the shared library's list of tier B reads


def test_reads_lib_and_the_private_fallbacks_give_identical_results(xw, rdoc, results, monkeypatch):
    if not RB.USE_LIB:
        pytest.skip("reads_lib is not importable: only the fallbacks exist")
    monkeypatch.setattr(RB, "USE_LIB", False)
    fb = RB.run_b(make_ctx(xw, copy.deepcopy(rdoc)))
    assert not any("error" in r for r in fb.values())
    for rid in TIER_B:
        assert json.dumps(fb[rid], ensure_ascii=False) == json.dumps(results[rid], ensure_ascii=False), rid
    assert RB.appendix_md(fb) == RB.appendix_md(results)


def test_every_read_computes_on_the_synthetic_stage(results):
    assert list(results) == TIER_B
    bad = {k: r["error"] for k, r in results.items() if "error" in r}
    assert bad == {}
    for rid, r in results.items():
        assert r["read"] == rid and r["title"] == RB.TITLES[rid]
        assert r["core"]["pool"] == "core" and r["ds"]["pool"] == "ds"
        json.dumps(r, allow_nan=False)                              # plain JSON, no nan / inf


def test_count_columns_cover_every_row_and_money_only_e0_and_choosable(results, bctx):
    for rid in COUNT_ALL_ROWS:
        for pool in XC.POOLS:
            assert results[rid][pool]["order"] == XC.rows_order(bctx, pool), rid
    for rid, r in results.items():
        for pool in XC.POOLS:
            assert r[pool]["label_choosable"] == [a for a in XC.rows_order(bctx, pool) if a in bctx.choosable[pool]]
        for arm, row in r["core"]["by_arm"].items():
            if arm not in ("E0",) and arm not in bctx.choosable["core"]:
                assert "money" not in row, (rid, arm)
                assert not any(k == "money" for _p, k in walk_keys(row)), (rid, arm)
        assert set(r["private"]["ds"]["by_arm"]) <= {"E0"} | bctx.choosable["ds"], rid
        assert not any("money" in row for row in r["ds"]["by_arm"].values()), rid
    # the core money rows of the money reads are exactly E0 and the core choosable rows
    for rid in ("X-015", "X-016", "X-018", "X-026", "X-030", "X-031", "X-034", "X-038", "X-041", "X-043", "X-005", "X-002"):
        assert {a for a, row in results[rid]["core"]["by_arm"].items() if "money" in row} == {"E0"} | set(CORE_OK), rid
        assert set(results[rid]["private"]["ds"]["by_arm"]) == {"E0"} | set(DS_OK), rid


def test_the_c4_record_and_money_refuse_a_not_choosable_row(bctx, xw):
    st = RB._st(bctx)
    for pick, arm in ((xw.core[0], "F3.a"), (xw.ds[0], "F1.w3.a"), (xw.ds[1], "F7.N12.a")):
        with pytest.raises(XC.Refused):
            st.c4(pick, arm)
        with pytest.raises(XC.Refused):
            RB._c4_trade_frame(bctx, pick, XC.account(bctx, pick, arm, 0.25))
        with pytest.raises(XC.Refused):
            st.acc_money(pick, arm)
        with pytest.raises(XC.Refused):
            st.M(pick["pool"], arm)
        with pytest.raises(XC.Refused):
            RB._put(st, RB._new("X-016"), pick["pool"], arm, {"n": 1}, {"a": 0.1})
    assert st.tk(xw.core[0], "F3.a")["q"].shape == st.tk(xw.core[0], "F3.a")["coin"].shape    # count keys are fine on every row


# ====================================================================================================== DeepSeek privacy (D11, C8, C14)
def test_committed_outputs_pass_the_c8_guard_the_free_text_check_and_c14(results):
    doc = committed(results)
    for rid, r in doc.items():
        XC.ds_row_check(r["ds"])
        RB.ds_check(r["ds"])
        for path, k in walk_keys(r["ds"]):
            assert k not in DS_FORBIDDEN, (rid, path)
    text = json.dumps(doc, ensure_ascii=False, default=RX._json_default)
    assert XC.committed_problems("extra_reads.json", doc, text) == []
    md = RB.appendix_md(results)
    assert XC.committed_problems("EXTRA_READS_APPENDIX_KO.md", md, md) == []
    assert XC.c14_problems(md) == [] and MT.ds_text_problems(md) == [] and MT.audit_text(md) == []


def test_the_stage_guards_of_reads_lib_pass(results, bctx, xw, rdoc):
    if RB.RL is None:
        pytest.skip("reads_lib is not importable")
    RL = RB.RL
    doc = json.loads(json.dumps(committed(results), ensure_ascii=False))
    assert RL.row_rule_problems(bctx, doc) == [] and RL.ds_strip_problems(doc) == []
    for r in doc.values():
        RL.ds_public(r["ds"])
    md = RB.appendix_md(results)
    assert RL.md_rule_problems(bctx, md) == []
    bad = copy.deepcopy(doc)
    bad["X-016"]["core"]["by_arm"]["F3.a"] = {"money": {"a": 0.01}}       # a planted money figure on a 선택 불가 row
    assert RL.row_rule_problems(bctx, bad)
    assert RL.md_rule_problems(bctx, md.replace("## X-016 목표까지 필요한 것 · 코어 풀", "## X-016 목표까지 필요한 것 · 코어 풀\n\n| F3.a | 1 |"))
    doc39 = copy.deepcopy(rdoc)
    doc39["pools"]["core"]["variants"] += [{"id": "F1.w2.a", "gates": {"g1": "pass"}, "label": "선택 불가", "closed": 50}]
    ctx39 = make_ctx(xw, doc39)
    r39 = RB.run_b(ctx39, reads=["X-039"])
    assert RL.md_rule_problems(ctx39, RB.appendix_md(r39)) == []


PLANTS = [("M", 0.0123), ("lam", 0.002), ("G_weekend", 1.2), ("offered", 400), ("no_fill", 2), ("after_bust", 1), ("busts", 1),
          ("n_off", 50), ("R_mean", 0.3), ("margin_p50", 0.4), ("w_end", 5100.0), ("max_dd", 0.2), ("share_roe_ge_60", 0.1)]


@pytest.mark.parametrize("key,val", PLANTS)
def test_planted_deepseek_figures_are_refused(results, key, val):
    for rid in ("X-004", "X-008", "X-016", "X-028", "X-033", "X-041"):
        ds = copy.deepcopy(results[rid]["ds"])
        XC.ds_row_check(ds)
        arm = ds["order"][0]
        RB.ds_check(ds)
        for where in ("pool", "row", "cell"):
            bad = copy.deepcopy(ds)
            tgt = bad if where == "pool" else bad["by_arm"][arm]
            if where == "cell":
                tgt = next((v for v in tgt.values() if isinstance(v, dict)), tgt)
            tgt[key] = val
            with pytest.raises(XC.Refused):
                RB.ds_check(bad)
        bad = copy.deepcopy(ds)
        bad["by_arm"][arm]["label"] = "+3.2%/월"
        with pytest.raises(XC.Refused):
            RB.ds_check(bad)


def test_planted_deepseek_money_lines_in_the_appendix_are_refused(results):
    md = RB.appendix_md(results)
    lines = md.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("## X-016 · 딥시크"))
    for plant in ("| E0 | 3.2% |", "E0 월 +2.1%/월", "| E0 | 최대 낙폭 0.3 |", "| E0 | 파산 1/15 |", "| E0 | 최종 배수 2.1 |"):
        bad = "\n".join(lines[:i + 1] + [plant] + lines[i + 1:])
        assert XC.c14_problems(bad) or MT.ds_text_problems(bad), plant
    assert MT.audit_text("딥시크 E0 성장 3.2%") and XC.c14_problems("# x\n\n| ds-F10_OTE-1h-1 | 12 |\n")


def planted_account(orig, factor: float):
    """A wrapper of common.account that moves every DeepSeek P&L by ``factor`` (signs, entries and busts unchanged) and recomputes the
    derived fields consistently: a planted DeepSeek money change."""
    def acc(ctx, pick, arm, size):
        a = orig(ctx, pick, arm, size)
        if ctx.pick(pick)["pool"] != "ds":
            return a
        a = dict(a)
        pnl = np.asarray(a["tr_pnl"], float) * factor
        w0 = float(a["w0"])
        wb = np.cumsum(np.r_[w0, pnl])[:-1]
        g, W = MT.monthly_g(np.asarray(a["tr_exit"]), pnl, w0, ctx.edges)
        eq = w0 + np.cumsum(pnl)
        peak = np.maximum.accumulate(np.r_[w0, eq])
        a.update(tr_pnl=pnl, w_end=np.float64(w0 + pnl.sum()), wallet_before=wb, ret=pnl / wb, l=np.log(np.maximum(wb + pnl, 1e-12) / wb),
                 g=g, W=W, max_dd=np.float64(np.max(1 - np.r_[w0, eq] / peak)) if len(eq) else np.float64(0.0))
        return a
    return acc


def test_committed_deepseek_parts_do_not_move_when_deepseek_money_moves(xw, rdoc, results, monkeypatch):
    monkeypatch.setattr(XC, "account", planted_account(XC.account, 1.0 + 1e-6))
    ctx = make_ctx(xw, copy.deepcopy(rdoc))
    moved = RB.run_b(ctx)
    # X-034 checks every trade's P&L against its prices (fees, slippage, funding), so a planted P&L is refused there
    assert "cost identity" in moved["X-034"]["error"]
    moved["X-034"] = results["X-034"]
    assert not any("error" in r for r in moved.values())
    for rid in TIER_B:
        assert json.dumps(moved[rid]["ds"], ensure_ascii=False) == json.dumps(results[rid]["ds"], ensure_ascii=False), rid
        assert json.dumps(moved[rid]["core"], ensure_ascii=False) == json.dumps(results[rid]["core"], ensure_ascii=False), rid
    assert ds_sections(RB.appendix_md(moved)) == ds_sections(RB.appendix_md(results))
    changed = [rid for rid in TIER_B if json.dumps(moved[rid]["private"]) != json.dumps(results[rid]["private"])]
    assert {"X-015", "X-016", "X-018", "X-029", "X-038", "X-004"} <= set(changed)


def test_the_private_appendix_is_marked_and_never_equals_a_committed_line(results):
    priv = RB.private_md(results)
    pub = set(ln.strip() for ln in RB.appendix_md(results).splitlines())
    lines = [ln for ln in priv.splitlines() if ln.strip()]
    assert lines and all(ln.startswith(("## [비공개]", "### [비공개]", "[비공개] ", "| 비공개 |", "|---|")) for ln in lines)
    assert "%/월" in priv and "| 비공개 | E0 |" in priv and "| 비공개 | F3.a |" in priv           # money in the core table format
    assert "F1.w3.a" not in priv and "F7.N12.a" not in priv                                        # 선택 불가 in the DeepSeek pool
    assert not [ln for ln in lines if len(ln.strip()) >= 20 and re.search(r"[0-9A-Za-z가-힣]", ln) and ln.strip() in pub]
    assert not XC._P_VALUE.search(priv)
    for rid in ("X-015", "X-016", "X-017", "X-018", "X-026", "X-030", "X-031", "X-038"):
        assert f"[비공개] {rid}" in priv


def test_the_pages_pass_the_writers_of_common(results, bctx):
    md = RB.appendix_md(results)
    path = XC.write_out(bctx, "EXTRA_READS_APPENDIX_KO.md", md)                 # the committed writer's checks (C8, A8 tripwire, C14)
    try:
        sha = XC.write_owner_report_extra(bctx, RB.private_md(results))        # A8 (3): outside the repo, no p value, no shared line
        priv = os.path.join(bctx.ds_private_root, "owner_report_extra.md")
        assert sha == RX.sha256_file(priv) and XC.private_report_problems(bctx, priv) == []
        os.remove(priv)
    finally:
        os.remove(path)


# ====================================================================================================== determinism and isolation
def test_two_runs_give_identical_results_and_pages(xw, rdoc, results):
    again = RB.run_b(make_ctx(xw, copy.deepcopy(rdoc)))
    assert json.dumps(again, ensure_ascii=False) == json.dumps(results, ensure_ascii=False)
    assert RB.appendix_md(again) == RB.appendix_md(results) and RB.private_md(again) == RB.private_md(results)


def test_reruns_leave_As_files_untouched_and_write_reduced_files_only_under_extra(run, xw, bctx):
    assert run["before"] == run["after"] and len(run["before"]) > 20
    for rid, d in RB.REDUCED_DIR.items():
        for p in xw.cfg.picks:
            base = os.path.join(xw.w8, "ds_private", "extra") if p["pool"] == "ds" else os.path.join(xw.w8, "extra")
            path = os.path.join(base, "reduced", d, f"{p['id']}__q25.npz")
            assert os.path.exists(path), (rid, p["id"])
            with pytest.raises(XC.Refused):
                XC.check_read(bctx, path)                    # a reduced file is never an A result file
    with np.load(os.path.join(xw.w8, "extra", "reduced", "weekend", f"{xw.core[0]['id']}__q25.npz")) as z:
        assert {"E0__noweekend__w_end", "F1.w3.a__noweekend__tr_pnl"} <= set(z.files) and not any(k.startswith("F3.a") for k in z.files)


def test_cost_and_start_settings_change_only_their_entries(bctx):
    mk = bctx.market
    S0 = mk.S(0.25)
    S1 = RB._cost_S(mk, 1.0)
    assert np.array_equal(S1, S0) and S1 is not S0
    S3 = RB._cost_S(mk, 3.0)
    ch = np.flatnonzero(S3 != S0)
    assert set(ch.tolist()) == {0, 1, 5, 19} and np.allclose(S3[ch], 3 * S0[ch])
    for s in (0.25, 1.0):
        Ss = RB._small_S(mk, s)
        assert float(mk.S(s)[10]) == 5000.0 and Ss[10] == 1000.0 and Ss[9] == 10.0
        assert np.array_equal(np.delete(Ss, 10), np.delete(mk.S(s), 10))


def test_a_failing_read_is_returned_as_an_error_and_the_others_go_on(xw, rdoc, monkeypatch):
    def boom(st):
        raise ValueError("planted failure")
    monkeypatch.setitem(RB.FUNCS, "X-033", boom)
    monkeypatch.setitem(RB.PRE, "X-043", lambda *a: (_ for _ in ()).throw(RuntimeError("planted pre-pass failure")))
    res = RB.run_b(make_ctx(xw, copy.deepcopy(rdoc)), reads=["X-033", "X-043", "X-039", "X-016"])
    assert res["X-033"]["error"].startswith("ValueError") and "pre-pass" in res["X-043"]["error"]
    assert "error" not in res["X-039"] and "error" not in res["X-016"]
    md = RB.appendix_md(res)
    assert RB.ERROR_KO in md and XC.committed_problems("a.md", md, md) == []
    with pytest.raises(KeyError):
        RB.run_b(make_ctx(xw), reads=["X-001"])


def test_cap_drops_remove_only_their_parts(xw, rdoc):
    res = RB.run_b(make_ctx(xw, copy.deepcopy(rdoc)), dropped=("X-041 c = 1.5", "X-043 live size", "X-002"),
                   reads=["X-002", "X-041", "X-043"])
    assert res["X-002"]["dropped"] == "E.5 cap"
    row = res["X-041"]["core"]["by_arm"]["F1.w3.a"]
    assert "entered_c15" not in row and "entered_c2" in row and "c15" not in row["money"]["M"]
    assert set(res["X-043"]["core"]["by_arm"]["E0"]["money"]) == {"q25"}
    assert RB.DROPPED_KO in RB.appendix_md(res)


# ====================================================================================================== C5, C4, excursions, C9
def test_c5_status_rebuild_matches_a_real_rerun_and_the_duplicate_rule(xw, bctx):
    st = RB._st(bctx)
    n = 0
    for p in xw.cfg.picks:
        pdata = xw.cfg.make_pickdata(p)
        for arm in ["E0"] + RB._arms_all(bctx, p["pool"])[1:]:
            for size in (0.25, 1.0):
                res = KX.simulate(xw.cfg.market, pdata, KX.variant_by_id(arm), size, "select")
                assert np.array_equal(st.c5(p, arm, size), res.status), (p["id"], arm, size)
                assert np.array_equal(RB._c5_status(bctx, p, arm, size), res.status), (p["id"], arm, size)
                n += 1
    assert n == 32
    p = xw.core[0]
    st.dup.add(p["id"])
    with pytest.raises(RB.DupFill):
        RB._c5_status(bctx, p, "E0", 0.25)
    st2 = RB._State(bctx)
    st2.set_off(p, xw.cfg.make_pickdata(p))
    RB._dup_statuses(st2, p, xw.cfg.make_pickdata(p))
    assert np.array_equal(st2.c5(p, "F1.w3.a", 0.25), st.c5(p, "F1.w3.a", 0.25))
    st.dup.discard(p["id"])


def test_c4_record_reproduces_the_kernel_and_the_excursions_by_hand(xw, bctx):
    st = RB._st(bctx)
    mk = bctx.market
    checked = 0
    for p in xw.cfg.picks:
        for arm in RB._arms_money(bctx, p["pool"]):
            for size in (0.25, 1.0):
                f = st.c4(p, arm, size)
                a = XC.account(bctx, p, arm, size)
                g = RB._excursions(bctx, p, RB._c4_trade_frame(bctx, p, a))            # the private fallback gives the same record
                for k in ("q", "t_sig", "coin", "side", "e", "x", "raw", "fill", "Rd", "Wb", "lev", "margin", "qty", "pnl", "ret", "l", "R", "ROE",
                          "reason", "hold_h", "best", "best_R", "worst_R", "best_ROE", "worst_ROE"):
                    assert np.allclose(np.asarray(f[k], float), np.asarray(g[k], float), rtol=0, atol=1e-12, equal_nan=True), (p["id"], arm, k)
                assert np.allclose(f["Wb"], a["wallet_before"]) and np.allclose(f["ret"], a["ret"]) and np.allclose(f["l"], a["l"])
                assert np.array_equal(mk.cat["ts"][f["e"]], a["tr_fill"]) and np.array_equal(mk.cat["ts"][f["x"]], a["tr_exit"])
                assert np.allclose(f["R"] * f["qty"] * f["Rd"], a["tr_pnl"]) and np.allclose(f["ROE"] * f["margin"], a["tr_pnl"])
                for i in range(len(f["R"])):
                    e, x, s = int(f["e"][i]), int(f["x"][i]), int(f["side"][i])
                    S = f["S"]

                    def rn(P):
                        return (s * (P - f["fill"][i]) - f["fill"][i] * S[5]) / f["Rd"][i]
                    ex = f["R"][i] if f["reason"][i] == KX.R_LIQ else rn(f["xpx"][i])
                    if x > e:
                        hi, lo = mk.cat["h"][e:x].max(), mk.cat["l"][e:x].min()
                        b, w = (rn(hi), rn(lo)) if s > 0 else (rn(lo), rn(hi))
                        assert math.isclose(f["best_R"][i], max(b, ex), rel_tol=1e-12, abs_tol=1e-12)
                        assert math.isclose(f["worst_R"][i], min(w, ex), rel_tol=1e-12, abs_tol=1e-12)
                    else:
                        assert f["best_R"][i] == f["worst_R"][i] == ex
                    checked += 1
    assert checked > 300


def test_c4_match_and_the_c9_split(bctx, xw):
    a, b = XC.account(bctx, xw.core[0], "F1.w3.a", 0.25), XC.account(bctx, xw.core[0], "E0", 0.25)
    m = RB._c4_match(a, b)
    assert len(m) == len(a["tr_pnl"]) and ((m == -1) | ((b["tr_fill"][np.maximum(m, 0)] == a["tr_fill"]))).all()
    assert np.array_equal(RB._c4_match(b, b), np.arange(len(b["tr_pnl"])))
    for arm in ("E0", "F1.w3.a", "F3.a"):
        cells = RB._c9_split(bctx, "core", arm, RB._key_side, 0.25, buckets=RB.SIDE_LABELS)
        st = RB._st(bctx)
        stat = [st.c5(p, arm, 0.25) for p in xw.core]
        assert sum(c["n_ent"] for c in cells.values()) == sum(int((s == 1).sum()) for s in stat)
        assert sum(c["n_skip"] for c in cells.values()) == sum(int((s == 0).sum()) for s in stat)
        assert sum(c["n_off"] for c in cells.values()) == sum(len(s) for s in stat)
        assert sum(c["n"] for c in cells.values()) == sum(len(st.tk(p, arm)["q"]) for p in xw.core)
        if arm == "F3.a":
            assert not any("money" in c for c in cells.values())
        else:
            assert abs(sum(c["money"]["dc"] for c in cells.values()) - 100 * st.M("core", arm)) < 1e-9


# ====================================================================================================== read by read (fixed synthetic inputs)
def test_x004_weekend_counts_growth_split_and_chance_range(results, bctx, xw):
    r = results["X-004"]
    st = RB._st(bctx)
    offs = [st.off(p) for p in xw.core]
    assert r["core"]["offered"] == sum(len(o["coin"]) for o in offs)
    assert r["core"]["offered_weekend"] == sum(int(XC.is_weekend(o["close"]).sum()) for o in offs)
    assert "offered" in r["private"]["ds"] and "offered" not in r["ds"]
    for arm in CORE_OK:
        row = r["core"]["by_arm"][arm]
        recs = [st.c4(p, arm) for p in xw.core]
        wk = [XC.is_weekend(f["t_sig"]) for f in recs]
        assert row["n_weekend"] == sum(int(w.sum()) for w in wk)
        m = row["money"]
        G1 = XC.c9_contrib([float(f["l"][w].sum()) for f, w in zip(recs, wk)])
        assert math.isclose(m["G_weekend"], G1, abs_tol=1e-12) and math.isclose(m["G_weekend"] + m["G_weekday"], m["G_all"], abs_tol=1e-9)
        assert math.isclose(m["G_all"], 100 * st.L("core", arm), abs_tol=1e-9)
        for dim in ("side", "coin", "year", "state", "tf"):
            assert sum(c["weekend"]["n"] + c["weekday"]["n"] for c in row["by_" + dim].values()) == row["n"]
            assert math.isclose(sum(c["G_weekend"] + c["G_weekday"] for c in m["by_" + dim].values()), m["G_all"], abs_tol=1e-9)
        assert m["n_draws_used"] + m["n_draws_dropped"] == RB.N_BOOT
        if m["range_lo"] is not None:
            assert m["range_lo"] <= m["range_hi"] and m["label_chance"] in ("우연 가능", "")


def test_cells_over_a_subset_of_picks_carry_the_pick_count_and_the_c13_mark(results, bctx, xw):
    for pool in XC.POOLS:
        for arm, row in results["X-004"][pool]["by_arm"].items():
            for b, cell in row["by_tf"].items():
                assert cell["n_picks"] == sum(1 for p in bctx.pool_picks(pool) if p["tf"] == b)
                assert cell["label_c13"] == ""                          # the synthetic picks are not F7_RF_ONLY
    for arm, row in results["X-030"]["core"]["by_arm"].items():
        assert row["money"]["by_bar"]["short"]["n_picks"] == 0 and row["money"]["by_bar"]["long"]["n_picks"] == 2
    assert RB._pick_mark({"n_picks": 1, "label_c13": "= F3.a"}) == " (픽 1개) = F3.a" and RB._pick_mark({"n_picks": 4}) == ""
    f7 = {"name": "F7_RF_ONLY", "id": "ds-F7_RF_ONLY-30m-1", "tf": "30m"}
    assert XC.c13_mark(f7, "F11.b") == "= F3.b"
    md = RB.appendix_md(results)
    assert "1시간 (픽 1개)" in md and "15분 (픽 0개)" in md


def test_x005_identity_of_new_dropped_and_removed_trades(results):
    for pool in XC.POOLS:
        for arm, row in results["X-005"][pool]["by_arm"].items():
            assert row["entered"] == row["entered_full"] - row["n_removed_weekend"] - row["n_dropped"] + row["n_new"], (pool, arm)
    m = results["X-005"]["core"]["by_arm"]["E0"]["money"]
    assert m["interval_lo"] <= m["interval_hi"] and m["n_months"] == 36


def test_x002_masked_rerun_by_hand(results, bctx, xw):
    p = xw.core[1]
    pdata = xw.cfg.make_pickdata(p)
    off = pdata.offered("select", bctx.market)
    res = KX.simulate(bctx.market, pdata, KX.E0, 0.25, "select", offered=XC.mask_offered(off, off["coin"] != 0))
    walls = []
    for q in xw.core:
        pd_ = xw.cfg.make_pickdata(q)
        o = pd_.offered("select", bctx.market)
        walls.append(KX.simulate(bctx.market, pd_, KX.E0, 0.25, "select", offered=XC.mask_offered(o, o["coin"] != 0)).wallet)
    want = np.mean([math.log(w / 5000.0) for w in walls]) / 36
    m = results["X-002"]["core"]["by_arm"]["E0"]["money"]
    assert math.isclose(m["own_without"]["BTC"], want, rel_tol=1e-12, abs_tol=1e-15) and res.wallet > 0
    v = results["X-002"]["core"]["by_arm"]["F1.w3.a"]["money"]
    assert v["n_coins"] == 2 and 0 <= v["n_hold"] <= 2 and set(v["picks_pos"]) == {"BTC", "ETH"}


def test_x015_windows_by_hand(bctx, xw):
    a = XC.account(bctx, xw.core[0], "E0", 0.25)
    D, R, P, half, bust = RB._windows(a, 30, bctx.edges)
    assert len(D) == 1066
    ex, pnl, w0 = a["tr_exit"], a["tr_pnl"], float(a["w0"])

    def W(t):
        return w0 + float(pnl[ex <= t].sum())
    for j in (0, 5, 17, 40, 400, 1065):
        t0, t1 = int(D[j]), int(D[j]) + 30 * XC.DAY_MS
        assert math.isclose(R[j], W(t1) / W(t0), rel_tol=1e-12)
        inside = [W(t) for t in ex[(ex > t0) & (ex <= t1)]]
        assert math.isclose(P[j], max([1.0] + [x / W(t0) for x in inside]), rel_tol=1e-12)
        assert half[j] == any(x <= 0.5 * W(t0) for x in inside) and bust[j] == any(x < 10 for x in inside)
    assert len(RB._windows(a, 92, bctx.edges)[0]) == 1004 and len(RB._windows(a, 365, bctx.edges)[0]) == 731
    dead = dict(a, w_end=5.0, g=np.r_[np.full(3, 0.01), np.zeros(33)])
    assert len(RB._windows(dead, 30, bctx.edges)[0]) == 31 + 28 + 31
    h = RB._hits(np.array([RB.LO_MS, RB.LO_MS + 40 * XC.DAY_MS, RB.LO_MS + 41 * XC.DAY_MS]), np.array([True, True, True]))
    assert h["k"] == 3 and h["n_months"] == 2 and math.isclose(h["top_month_share"], 2 / 3)


def test_x016_goal_formulas(results):
    m = results["X-016"]["core"]["by_arm"]["F1.w3.a"]["money"]
    row = results["X-016"]["core"]["by_arm"]["F1.w3.a"]
    w, a, b, n = row["win_share"], m["a"], m["b"], row["n_entries_per_account_month"]
    for t, (T, lab) in zip(m["targets"], RB.TARGETS):
        assert t["target"] == lab
        g = math.log(T)
        assert math.isclose(n * (t["win_share_need"] * a + (1 - t["win_share_need"]) * b), g, abs_tol=1e-12)
        if t["typical_win_need"] is not None:
            assert math.isclose(n * (w * math.log1p(t["typical_win_need"]) + (1 - w) * b), g, abs_tol=1e-12)
    rows = RB._goal_rows(0.5, 0.02, -0.01, 10.0, 1.0)
    x5 = rows[4]
    assert x5["label_win"] == "불가능" and x5["label_entries"] == "신호가 모자람"
    assert RB._goal_rows(0.5, 0.01, -0.03, 5.0, 2.0)[2]["label_entries"] == "불가능: 거래당 평균이 0 이하"
    assert RB._months_to(1.0) == {"x5": "도달 안 함", "x100": "도달 안 함"} and RB._months_to(1.5)["x5"] == math.ceil(math.log(5) / math.log(1.5))
    c = results["X-016"]["constants"]
    assert [x["months"] for x in c] == [1, 3, 6, 12, 36] and math.isclose(c[1]["x5_per_month"], 5 ** (1 / 3))
    assert 0 < results["X-016"]["core"]["entries_ceiling_per_account_month"]


def test_x016_entry_ceiling_walk(bctx, xw):
    st = RB._st(bctx)
    for p in xw.cfg.picks:                                     # 1h / 4h picks: freeing at C0 + 15 min never takes fewer signals
        n_tf, n_15 = RB._ceiling_count(st, p), RB._ceiling_count(st, p, q15=True)
        assert 0 < n_tf <= n_15 <= len(st.off(p)["coin"])
        if RB.RL is not None:                                  # the same walk as X-025's (reads_lib.entry_ceiling)
            assert n_tf == RB.RL.entry_ceiling(bctx, p) and n_15 == RB.RL.entry_ceiling(bctx, p, plus_ms=900_000)
            for arm in RB._arms_money(bctx, p["pool"]):
                r = RB.RL.sizeable(bctx, p, arm)
                acc = XC.account(bctx, p, arm, 0.25)
                q = np.flatnonzero(st.c5(p, arm, 0.25) == 0)
                W = RB._wallet_before(acc, st.off(p)["fill"][q])
                ok = RB._sizeable(bctx.market, bctx.market.S(0.25), st.off(p), q, W, KX.exit_of_pick(p, KX.variant_by_id(arm))[0])
                assert np.array_equal(r["q"], q) and np.allclose(r["W"], W, rtol=0, atol=1e-9) and np.array_equal(r["sizeable"], ok)


def test_x017_candidates_hold_e0s_own_exit_and_the_time_stop_exit(xw, bctx):
    st = RB._st(bctx)
    mk = bctx.market
    n_e0 = n_f7 = 0
    for p in xw.cfg.picks[:2]:
        pdata = xw.cfg.make_pickdata(p)
        off = pdata.offered("select", mk)
        r0 = RB.hind_run(st, p, pdata, 0.25)
        idx = [int(i) for i in np.flatnonzero(r0["take"])[:12]]
        for i in idx:
            r = RB.hind_run(st, p, pdata, 0.25, collect=i, buf_rows=400_000)
            cands = r["cands"]
            assert len(cands) and cands[-1, 4] in (RB.CK_SL, RB.CK_LIQ, RB.CK_END)
            out = KX.simulate_trade(mk, pdata, KX.E0, off, i, 0.25, "select", equity=5000.0)[0]
            c = int(off["coin"][i])
            tsp = mk.cat["ts"][mk.starts[c]:mk.period_end("select")[c]]
            t_ex, val = int(tsp[int(out[1])]), math.log(1 + float(out[0]) / 5000.0)
            hit = cands[(cands[:, 0] == t_ex) & np.isclose(cands[:, 2], val, rtol=0, atol=1e-12)]
            assert len(hit) and (int(hit[0, 3]) & 1), (p["id"], i)                  # in horizon (i)
            n_e0 += 1
            for vid in ("F7.N12.b", "F7.N24.a"):
                o7 = KX.simulate_trade(mk, pdata, KX.variant_by_id(vid), off, i, 0.25, "select", equity=5000.0)[0]
                if int(o7[2]) == KX.R_RULE:
                    t7, v7 = int(tsp[int(o7[1])]), math.log(1 + float(o7[0]) / 5000.0)
                    ok = cands[(cands[:, 0] == t7) & (cands[:, 4] == RB.CK_CHECK)]
                    assert len(ok) and math.isclose(ok[0, 2], v7, abs_tol=1e-12), (p["id"], i, vid)
                    n_f7 += 1
    assert n_e0 >= 20 and n_f7 >= 5


def test_x017_dp_equals_a_plain_recursion_over_the_candidates(xw, bctx):
    st = RB._st(bctx)
    p = xw.cfg.picks[1]
    pdata = xw.cfg.make_pickdata(p)
    r0 = RB.hind_run(st, p, pdata, 0.25)
    n = len(r0["take"])
    cands = {i: RB.hind_run(st, p, pdata, 0.25, collect=i, buf_rows=400_000)["cands"] for i in range(n) if r0["take"][i]}
    V = np.zeros((RB.NH, n + 1))
    for i in range(n - 1, -1, -1):
        for k in range(RB.NH):
            if not r0["take"][i]:
                V[k, i] = V[k, i + 1]
                continue
            c = cands[i]
            ok = (c[:, 3].astype(int) >> k) & 1 == 1
            allowed = c[:, 4] != RB.CK_LIMIT if k < 4 else np.ones(len(c), bool)
            tot = c[:, 2] + V[k, c[:, 5].astype(int)]
            sel = ok & allowed
            V[k, i] = tot[sel].max() if sel.any() else tot[allowed][0]
    assert np.allclose(V[:, 0], r0["G"], rtol=0, atol=1e-12)
    G = r0["G"]
    assert G[1] <= G[2] + 1e-12 <= G[3] + 2e-12 and G[3] <= G[4] + 1e-12 and G[0] <= G[3] + 1e-12
    fill = st.off(p)["fill"]
    for i, c in cands.items():                                                # the next index is the first one filling after busy-until
        for row in c:
            j = int(row[5])
            assert j > i and (j == n or fill[j] > row[1]) and (j == i + 1 or fill[j - 1] <= row[1])


def test_x017_pooled_ceiling_and_capture(results):
    c = results["X-017"]["core"]["ceiling"]
    for tag in ("q25", "q100"):
        p = c[tag]
        assert set(p["pooled_month_log"]) == set(RB.H_KEYS) and p["path_trades"] > 0
        assert all(math.isclose(p["month_multiple"][k], math.exp(p["pooled_month_log"][k])) for k in RB.H_KEYS)
        assert set(p["capture"]) == {"E0"} | set(CORE_OK)
    assert "ceiling" not in results["X-017"]["ds"] and "ceiling" in results["X-017"]["private"]["ds"]


def test_x018_basket_streaks_and_correlation(bctx, xw, monkeypatch):
    accs = [XC.account(bctx, p, "E0", 0.25) for p in xw.core]
    b = RB._basket(accs, bctx.edges)
    assert 0 <= b["max_dd"] < 1 and b["n_months"] == 36 and 0 <= b["months_fell"] <= 36 and b["final"] > 0
    t = np.array([0, 10, 20, 30, 40], np.int64) * XC.DAY_MS
    assert RB._underwater(t, np.array([1.0, 0.9, 0.95, 1.0, 1.1]), int(t[-1]) + XC.DAY_MS)[0] == 20.0
    assert RB._underwater(t, np.array([1.0, 1.2, 1.1, 1.0, 1.05]), int(t[-1]) + XC.DAY_MS)[2] is None
    assert RB._runs(np.array([1, 1, 0, 1, 1, 1, 0, 0, 1], bool)).tolist() == [2, 3, 1]
    s = RB._streaks([{"tr_pnl": np.array([-1.0, -1, 2, -1, -1, -1, -1, -1, 3])}])
    assert s["longest_max"] == 5 and math.isclose(s["share_in_runs_ge5"], 5 / 9)
    tg = RB._together([{"g": np.arange(36.0)}, {"g": np.arange(36.0) * 2}, {"g": -np.arange(36.0)}])
    assert math.isclose(tg["rho_mean"], (1 - 1 - 1) / 3) and tg["n_pairs"] == 3
    monkeypatch.setattr(RB, "BASKET_MIN", 1)
    res = RB.run_b(make_ctx(xw, rich_select(xw)), reads=["X-018"])
    assert res["X-018"]["core"]["by_arm"]["E0"]["money"]["q25"]["basket"]["n_months"] == 36
    assert res["X-018"]["core"]["by_arm"]["E0"]["money"]["label_e0_max_dd"] == "select.json과 같음"


def test_x021_concurrency_by_hand(bctx):
    st = RB._st(bctx)
    grid = RB.LO_MS + np.arange(8, dtype=np.int64) * RB.GRID_MS
    a = {"fill_ts": np.array([grid[1], grid[4]]), "exit_ts": np.array([grid[3], grid[6]]), "coin": np.array([0, 1]), "side": np.array([1, -1])}
    b = {"fill_ts": np.array([grid[2]]), "exit_ts": np.array([grid[5]]), "coin": np.array([0]), "side": np.array([1])}
    c = RB._concurrency(st, [a, b], grid)
    # m = [0, 1, 2, 1, 2, 1, 0, 0]
    assert math.isclose(c["share_open_ge1"], 5 / 8) and c["n_open_max"] == 2 and math.isclose(c["n_open_mean"], 7 / 8)
    assert c["n_max_same"] == 2 and c["label_max_same_date"] == RB._date(grid[2])
    assert c["by_coin"]["BTC"]["n_points"] == 4 and math.isclose(c["by_coin"]["BTC"]["share_two_plus"], 1 / 4)
    assert math.isclose(c["share_pairs_mean"], (1 + 0.5 + 1 + 1 + 1) / 5)


def test_x026_missed_signals_are_skipped_sizeable_and_their_trades_are_the_kernels(results, bctx, xw):
    st = RB._st(bctx)
    for pool in XC.POOLS:
        for arm in RB._arms_money(bctx, pool):
            m = (results["X-026"]["core"]["by_arm"][arm]["money"] if pool == "core" else results["X-026"]["private"]["ds"]["by_arm"][arm]["money"])
            stat = [st.c5(p, arm, 0.25) for p in st.picks(pool)]
            assert m["n_skipped"] == sum(int((s == 0).sum()) for s in stat) and m["missed"]["n"] == m["n_sizeable"] <= m["n_skipped"]
            assert m["entered"]["n"] == sum(int((s == 1).sum()) for s in stat)
    p, arm = xw.core[0], "F1.w3.a"
    pdata = xw.cfg.make_pickdata(p)
    off = pdata.offered("select", bctx.market)
    acc = XC.account(bctx, p, arm, 0.25)
    q = int(np.flatnonzero(st.c5(p, arm, 0.25) == 0)[0])
    W = float(RB._wallet_before(acc, [off["fill"][q]])[0])
    assert W == float(acc["w0"]) + float(acc["tr_pnl"][acc["tr_exit"] < off["fill"][q]].sum())


def test_x028_reasons_equal_select_json_and_a_wrong_count_is_an_error(results, xw, rdoc):
    r = results["X-028"]
    assert any("checked against select.json reasons: 8" in n for n in r["notes"])
    for pool in XC.POOLS:
        for arm, row in r[pool]["by_arm"].items():
            assert sum(row["reasons"].values()) == row["n"] and row["label_select"] == "select.json과 같음"
            assert sum(c["n"] for c in row["by_coin"].values()) == row["n"]
    doc = copy.deepcopy(rdoc)
    doc["pools"]["core"]["variants"][0]["reasons"]["SL"] += 1
    res = RB.run_b(make_ctx(xw, doc), reads=["X-028"])
    assert "differs from select.json" in res["X-028"]["error"]


def test_x029_x030_x031_shapes(results):
    for arm, row in results["X-029"]["core"]["by_arm"].items():
        if arm in ("E0", *CORE_OK):
            assert sum(c["n"] for c in row["by_tier"].values()) == row["n"]
        else:
            assert "by_tier" not in row                    # leverage tiers are money class (C8): never on a 선택 불가 row
    assert all("by_tier" not in row for row in results["X-029"]["ds"]["by_arm"].values())
    assert set(results["X-029"]["private"]["ds"]["by_arm"]) == {"E0", *DS_OK}
    m = results["X-029"]["core"]["by_arm"]["E0"]["money"]
    if m["payoff"] is not None:
        assert math.isclose(m["breakeven_win_share"], 1 / (1 + m["payoff"]))
    for arm, row in results["X-030"]["core"]["by_arm"].items():
        c = row["money"]["all"]
        assert c["n"] == sum(row["money"]["by_tier"][str(t)]["n"] for t in RB.TIERS) == sum(row["money"]["by_bar"][g]["n"] for g, _t, _k in RB.BAR_GROUPS)
        assert c["reach_1R"] >= c["reach_2R"] >= c["reach_3R"]
    for arm, row in results["X-031"]["core"]["by_arm"].items():
        c = row["money"]["all"]
        assert c["n"] >= sum(x["n"] for x in row["money"]["by_class"].values())


def test_x033_hold_tails_years_and_the_select_json_p90(results, rdoc):
    r = results["X-033"]
    for pool in XC.POOLS:
        for arm, row in r[pool]["by_arm"].items():
            sel = rdoc["pools"][pool]["e0"] if arm == "E0" else next(x for x in rdoc["pools"][pool]["variants"] if x["id"] == arm)
            assert row["label_p90"] == "select.json과 같음" and row["hold_p90"] == sel["hold"]["p90"]
            assert sum(c["n"] for c in row["by_year"].values()) == row["n"]
            assert row["label_entered_years"].startswith("E0 이상 진입 ") and row["label_entered_years"].endswith("/3해")


def test_x034_cost_ledger_identity_and_buckets(results, bctx, xw):
    st = RB._st(bctx)
    f = st.c4(xw.core[0], "E0")
    c = RB._cost_parts(st, f)
    assert (c["fee_in"] > 0).all() and (c["slip"] > 0).all() and (c["fee_out"] >= 0).all() and (c["nset"] >= 0).all()
    for arm, row in results["X-034"]["core"]["by_arm"].items():
        assert sum(b["n"] for b in row["by_hold"].values()) == row["n"] == sum(s["n"] for s in row["by_side"].values())
    bad = dict(f, pnl=f["pnl"] + 1.0)
    with pytest.raises(AssertionError):
        RB._cost_parts(st, bad)


def test_x038_top_trades_removed_by_hand(results, bctx, xw):
    m = results["X-038"]["core"]["by_arm"]["F1.w3.a"]["money"]
    want = []
    for p in xw.core:
        lv, le = np.sort(XC.account(bctx, p, "F1.w3.a", 0.25)["l"]), np.sort(XC.account(bctx, p, "E0", 0.25)["l"])
        want.append(((lv.sum() - lv[-5:].sum()) - (le.sum() - le[-5:].sum())) / 36)
    assert math.isclose(m["M5"], float(np.mean(want)), abs_tol=1e-15) and m["n_picks"] == 2


def test_x039_neighbour_census_and_labels(xw, rdoc, bctx):
    allv = list(bctx.variants)
    assert len(allv) == 88 and RB.neighbour_census(allv) == {"none": 12, 1: 32, 2: 34, 3: 10}
    byid = {v.id: v for v in allv}
    assert RB.neighbours(byid["F1.w3.a"], allv) == ["F1.w2.a", "F1.w5.a"] and RB.neighbours(byid["F9.a"], allv) is None
    assert sorted(RB.neighbours(byid["F5.P1.5.g25.a"], allv)) == ["F5.P1.5.g50.a", "F5.P1.g25.a", "F5.P2.g25.a"]
    assert RB.neighbours(byid["F1.w3.a.q15"], allv) == ["F1.w2.a.q15", "F1.w5.a.q15"] and RB._edge(byid["F8.w3.P1.a"])
    assert not RB._edge(byid["F1.w3.a"]) and RB._edge(byid["F7.N12.a"])
    doc = copy.deepcopy(rdoc)
    doc["pools"]["core"]["variants"] += [{"id": "F1.w2.a", "gates": {"g1": "pass"}, "label": "선택 불가", "closed": 50},
                                         {"id": "F1.w5.a", "gates": {"g1": "fail"}, "label": "선택 불가", "closed": 500}]
    res = RB.run_b(make_ctx(xw, doc), reads=["X-039"])
    row = res["X-039"]["core"]["by_arm"]["F1.w3.a"]
    assert row["n_neighbours"] == 2 and row["n_pass_g1"] == 1 and row["n_choosable"] == 0 and row["label"] == "이웃 일부 탈락"
    assert row["by_arm"]["F1.w2.a"]["few"] and not row["by_arm"]["F1.w5.a"]["few"]
    assert res["X-039"]["ds"]["by_arm"]["F3.a"]["label"] == "이웃 없음"
    XC.ds_row_check(res["X-039"]["ds"])


def test_x041_x043_columns_and_the_crossing(results, bctx, xw):
    r = results["X-041"]["core"]["by_arm"]["F1.w3.a"]
    st = RB._st(bctx)
    assert r["entered_c1"] == sum(MT.count(XC.account(bctx, p, "F1.w3.a", 0.25), "entered") for p in xw.core)
    assert math.isclose(r["money"]["M"]["c1"], st.M("core", "F1.w3.a"), abs_tol=1e-15)
    assert RB.crossing({1.0: -0.1, 1.5: 0.2}) == "1 미만" and RB.crossing({1.0: 0.1, 1.5: 0.05, 2.0: 0.01, 3.0: 0.001}) == "3 이상"
    assert math.isclose(RB.crossing({0.0: 0.3, 1.0: 0.2, 1.5: 0.1, 2.0: -0.1, 3.0: -0.3}), 1.75)
    assert math.isclose(RB.crossing({1.0: 0.2, 2.0: -0.2, 3.0: -0.4}), 1.5)
    v = results["X-043"]
    assert v["core"]["label_verdict"].startswith(("1,000달러도", "다릅니다")) and "label_verdict" in v["ds"]
    assert v["private"]["ds"]["label_verdict"].startswith(("1,000달러도", "다릅니다"))
    row = v["core"]["by_arm"]["F1.w3.a"]
    assert {"entered_q25_w1000", "entered_q100_w5000"} <= set(row) and {"q25", "q100"} <= set(row["money"])


def test_x008_x011_state_and_side_cards(results):
    for arm, row in results["X-008"]["core"]["by_arm"].items():
        assert list(row["by_state"]) == list(RB.STATE_LABELS)
        if "money" in row:
            assert abs(row["money"]["dc_sum"] - row["money"]["M100"]) < 1e-9
    for arm, row in results["X-008"]["ds"]["by_arm"].items():
        assert all("n_off" not in c for c in row["by_state"].values())
    for arm, row in results["X-011"]["core"]["by_arm"].items():
        assert list(row["by_side"]) == ["long", "short"] and set(row["by_side_state"]) == {"long", "short"}
        assert sum(c["n"] for s in row["by_side_coin"].values() for c in s.values()) == sum(c["n"] for c in row["by_side"].values())


# ====================================================================================================== the Korean page
def test_appendix_has_every_read_both_pools_tags_and_warnings(results):
    md = RB.appendix_md(results)
    for rid in TIER_B:
        assert f"## {rid} {RB.TITLES[rid]} · 코어 풀" in md and f"## {rid} · 딥시크 풀" in md
    assert md.count(XC.TAG_TABLE) >= 2 * len(TIER_B)
    for w in ("W3", "W4", "W5", "W6", "W7", "W9", "W13", "W14"):
        assert XC.W[w] in md, w
    ds = "\n".join(ds_sections(md))
    assert "%" not in ds and "%/월" not in ds and "파산" not in ds
    dsl = set(ds_sections(md))
    for ln in md.splitlines():                                  # C12: a core money row at live size carries '파산 k/N' in its cells
        if ln.startswith("| ") and "| 1/1 크기 |" in ln and ln not in dsl:
            assert "파산 " in ln, ln[:80]
    assert XC.CONTRIB_NOTE_KO in md and RB.R_DEF_KO in md


def test_x028_deepseek_label_holds_no_figure_and_core_label_is_unchanged():
    for v in [KX.E0] + KX.variants():
        lab = RB._label_rule("ds", v)
        XC.ds_row_check({"label_rule": lab})          # C8: no figure in a DeepSeek row
        assert RB._label_rule("core", v) == (RX.FAMILY_KO.get(v.famname, "") if v.famname != "E0" else "")
    f13 = KX.variant_by_id("F13.a")
    assert RB._label_rule("ds", f13) == "규칙봇 계단 잠금"
    assert RB._label_rule("ds", KX.variant_by_id("F4.m2.a")) == RX.FAMILY_KO["F4"]      # a parenthesis without a digit stays
