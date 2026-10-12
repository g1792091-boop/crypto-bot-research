"""Tests of research/exitflex/extra/common.py on SYNTHETIC data only (PREREG_EXITFLEX_EXTRA.md E.6).

    python -m pytest -q research/exitflex/extra/test_common.py

A synthetic A select stage is built in a temporary folder with A's own code (test_exitflex.syn_cfg, runner_x.run_pick_step1 /
run_pick_step2, data_x.write_cut): a pinned layout, result files under results/select/ and ds_private/results/select/, placebo blocks,
a cut folder and a pinned select.json. Nothing here reads a real result, the real work folder or A's out/ folder, and nothing prints a
figure.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import shutil
import sys
import types

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
import runner_x as RX  # noqa: E402
from test_exitflex import SYMS, Prov, causal_f11, syn_cfg, vendor  # noqa: E402,F401  (synthetic world builders and fixture)

CORE_OK, DS_OK = ["F1.w3.a", "F7.N12.a"], ["F3.a"]
ARMS = ["F1.w3.a", "F3.a", "F7.N12.a"]


def ms(*a) -> int:
    return int(dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp() * 1000)


def sha_line(path: str, root) -> str:
    return f"{RX.sha256_file(path)}  {os.path.relpath(path, str(root))}"


def write_text(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.fixture(scope="module")
def xw(tmp_path_factory, vendor):  # noqa: F811
    """A synthetic, pinned A select stage: 2 coins, 2 core and 2 DeepSeek picks, E0 and three variants at both sizes, 40 placebo seeds (2
    blocks) of one choosable variant per pool, the cut folder, a pinned select.json, the extra pin file, and decoys the loader refuses."""
    tmp = tmp_path_factory.mktemp("xc")
    cfg = syn_cfg(tmp, variants=ARMS, n_seeds=40)
    root = tmp / "repo"
    base = root / "research" / "exitflex"
    os.makedirs(base / "extra", exist_ok=True)
    lay = RX.Layout(base=str(base), root=str(root), required=())
    os.makedirs(lay.out, exist_ok=True)
    data = cfg.pin["data_dir"]
    write_text(os.path.join(data, "build.json"), "{}")
    work = str(tmp / "work")
    pin = DX.make_pin(data, work, symbols=SYMS[:2])
    write_text(lay.pin_file, json.dumps(pin))
    ph = DX.pin_sha(lay.pin_file)
    cfg.pin, cfg.pin_hash, cfg.lay, cfg.store = pin, ph, lay, RX.Store(work, ph, "select")
    for p in cfg.picks:
        RX.run_pick_step1(cfg, p)
        RX.run_pick_step2(cfg, p, CORE_OK[:1] if p["pool"] == "core" else DS_OK)
    DX.write_cut(data, work, ph, DX.SELECT_CUT_MS, symbols=SYMS[:2])
    w8 = os.path.join(work, DX.pin8(ph))
    core0 = cfg.picks[0]
    for name in ("results/select/core_not_choosable.json", "ds_private/select_ds.json", "ds_private/owner_report_select.md"):
        write_text(os.path.join(w8, name), "{}")
    for st in ("confirm", "select_r2"):
        d = os.path.join(w8, "results", st, core0["id"])
        os.makedirs(d, exist_ok=True)
        shutil.copy(cfg.store.path(core0, "E0", "q25"), os.path.join(d, "E0__q25.npz"))
    sel = {"pin": ph, "n_seeds": 40, "pools": {
        "core": {"eligible_ids": CORE_OK, "default_ids": ["F7.N12.a"], "variants": [{"id": i} for i in CORE_OK + ["F3.a"]]},
        "ds": {"eligible_ids": DS_OK, "default_ids": [], "variants": [{"id": i} for i in DS_OK + ["F1.w3.a", "F7.N12.a"]]}}}
    write_text(lay.out_file("select.json"), json.dumps(sel))
    write_text(lay.out_file("SELECT_KO.md"), "# decoy\n")
    sha_lines = [sha_line(lay.pin_file, root), sha_line(lay.out_file("select.json"), root)]
    write_text(lay.sha_file, "\n".join(sha_lines) + "\n")
    write_text(XC.extra_sha_file(lay), sha_line(lay.pin_file, root) + "\n")
    mp = pytest.MonkeyPatch()
    orig_picks = DX.picks
    mp.setattr(DX, "picks", lambda *a, **k: list(cfg.picks))
    yield types.SimpleNamespace(cfg=cfg, lay=lay, ph=ph, work=work, w8=w8, tmp=tmp, root=root, base=base, orig_picks=orig_picks,
                                sha_lines=sha_lines, core=[p for p in cfg.picks if p["pool"] == "core"],
                                ds=[p for p in cfg.picks if p["pool"] == "ds"])
    mp.undo()
    KX.clear_f11()
    shutil.rmtree(str(tmp), ignore_errors=True)


@pytest.fixture(scope="module")
def ctx(xw):
    return XC.load_ctx(xw.lay)


@pytest.fixture(scope="module")
def sctx(xw):
    return XC.load_ctx(xw.lay, allow_select=True)


# ====================================================================================================== load_ctx and Ctx
def test_load_ctx_without_select_has_the_folders_menu_and_no_choosable_ids(xw, ctx, capsys):
    assert ctx.pin8 == xw.ph[:8] and ctx.work == xw.work and ctx.stage == "extra" and ctx.sel_stage == "select"
    assert ctx.out_dir == os.path.join(str(xw.base), "extra", "out")
    assert ctx.work_extra == os.path.join(xw.w8, "extra") and ctx.private_dir == os.path.join(xw.w8, "ds_private", "extra")
    assert ctx.ds_private_root == os.path.join(xw.w8, "ds_private")
    assert len(ctx.variants) == 88 and ctx.vids[-2:] == ["F13.a", "F13.b"] and KX.F11_REGISTRY["provider"] is not None
    assert len(ctx.edges) == 37 and ctx.pools == ("core", "ds") and [p["id"] for p in ctx.picks] == [p["id"] for p in xw.cfg.picks]
    assert ctx.choosable == {"core": set(), "ds": set()} and ctx.select_doc is None and ctx.n_seeds is None and not ctx.allow_select
    assert os.path.exists(os.path.join(ctx.cut_dir, "cut.json")) and os.path.isdir(os.path.join(ctx.work_extra, "cache"))
    assert XC.rows_order(ctx, "core") == ["E0"] + ctx.vids
    capsys.readouterr()
    XC.load_ctx(xw.lay)                                                   # one console line, ours; gate_pin's own line is captured
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("[extra pin ok] commit") and f"pin {xw.ph[:8]}" in out[0]


def test_load_ctx_with_select_reads_the_choosable_ids_seeds_and_order(sctx):
    assert sctx.allow_select and sctx.choosable == {"core": set(CORE_OK), "ds": set(DS_OK)} and sctx.n_seeds == 40
    assert sctx.default_ids == {"core": ["F7.N12.a"], "ds": []}
    assert XC.rows_order(sctx, "core") == ["E0", "F1.w3.a", "F7.N12.a", "F3.a"] and XC.rows_order(sctx, "ds")[:2] == ["E0", "F3.a"]


def _restore(path: str, text: str | None):
    if text is None:
        if os.path.exists(path):
            os.remove(path)
    else:
        write_text(path, text)


def test_load_ctx_refusals(xw):
    lay, xs = xw.lay, XC.extra_sha_file(xw.lay)
    sha_text, xs_text, sel_text = open(lay.sha_file).read(), open(xs).read(), open(lay.out_file("select.json")).read()
    cut = DX.cut_dir(xw.work, xw.ph, DX.SELECT_CUT_MS)
    cases = 0
    try:
        os.remove(xs)                                                     # no extra pin file
        with pytest.raises(SystemExit, match="pin file missing"):
            XC.load_ctx(lay)
        write_text(xs, xs_text + f"{'0' * 64}  {os.path.relpath(lay.pin_file, str(xw.root))}\n")     # the last line of a path counts
        with pytest.raises(SystemExit, match="extra pin: hash mismatch"):
            XC.load_ctx(lay)
        write_text(xs, xs_text)
        loose = write_text(os.path.join(str(xw.base), "extra", "sub", "x.py"), "x = 1\n")             # an unlisted .py file (os.walk)
        with pytest.raises(SystemExit, match="not pinned"):
            XC.load_ctx(lay)
        write_text(xs, xs_text + sha_line(loose, xw.root) + "\n")
        XC.load_ctx(lay)
        os.remove(loose)
        write_text(xs, xs_text)
        os.rename(cut, cut + ".away")                                    # no cut: refused, never made here
        with pytest.raises(SystemExit, match="select cut"):
            XC.load_ctx(lay)
        os.rename(cut + ".away", cut)
        write_text(lay.sha_file, xw.sha_lines[0] + "\n")                 # select.json not pinned: refused only with allow_select
        with pytest.raises(SystemExit, match="not pinned with its present hash"):
            XC.load_ctx(lay, allow_select=True)
        XC.load_ctx(lay)
        write_text(lay.out_file("select.json"), sel_text.replace(xw.ph, "ab" * 32))   # another pin
        write_text(lay.sha_file, "\n".join([xw.sha_lines[0], sha_line(lay.out_file("select.json"), xw.root)]) + "\n")
        with pytest.raises(SystemExit, match="another pin"):
            XC.load_ctx(lay, allow_select=True)
        cases = 6
    finally:
        _restore(lay.sha_file, sha_text)
        _restore(xs, xs_text)
        _restore(lay.out_file("select.json"), sel_text)
        if os.path.exists(cut + ".away"):
            os.rename(cut + ".away", cut)
        shutil.rmtree(os.path.join(str(xw.base), "extra", "sub"), ignore_errors=True)
    assert cases == 6
    XC.load_ctx(lay, allow_select=True)


def test_ctx_guards_market_and_pickdata(xw, monkeypatch):
    lay = xw.lay
    with pytest.raises(XC.Refused):                                      # outputs never go to A's out/
        XC.Ctx(RX.Layout(base=lay.base, root=lay.root, out=os.path.join(lay.base, "extra", "out"), required=()), xw.cfg.pin, xw.ph)
    with pytest.raises(XC.Refused):
        XC.Ctx(lay, xw.cfg.pin, xw.ph).market
    c = XC.Ctx(lay, xw.cfg.pin, xw.ph, picks=xw.cfg.picks, rprov=Prov(xw.cfg.pin["data_dir"], SYMS[:2], warm=False))
    c.__dict__["market"] = xw.cfg.market
    monkeypatch.setitem(KX.F11_REGISTRY, "provider", causal_f11)
    a, b = c.pickdata(xw.core[0]["id"]).offered("select"), xw.cfg.make_pickdata(xw.core[0]).offered("select")
    assert list(a) == list(b) and all(np.array_equal(a[k], b[k], equal_nan=True) for k in a) and len(a["coin"]) > 10

    class FakeMarket:
        symbols = ("BTCUSDT",)

        def __init__(self, last):
            self.last = last

        def ts(self, i):
            return np.array([DX.PERIOD_MS["select"][0], self.last], np.int64)
    XC.a5_check(FakeMarket(DX.SELECT_CUT_MS - 60_000))
    with pytest.raises(AssertionError):
        XC.a5_check(FakeMarket(DX.SELECT_CUT_MS))


# ====================================================================================================== account, placebo, row rule, M_P
def test_account_is_the_result_file_plus_the_derived_trade_arrays(xw, sctx):
    n_tr = 0
    for p in xw.cfg.picks:
        for size, tag in RX.SIZE_TAG.items():
            for arm in ["E0"] + ARMS:
                a = XC.account(sctx, p if arm != "F3.a" else p["id"], arm, size)
                f = xw.cfg.store.load(p, arm, tag)
                assert all(np.array_equal(a[k], f[k]) for k in f)
                pnl, w0, fi, ex = f["tr_pnl"], float(f["w0"]), f["tr_fill"], f["tr_exit"]
                wb = a["wallet_before"]
                assert len(wb) == len(pnl) and (not len(wb) or wb[0] == w0)
                assert np.allclose(wb, w0 + np.r_[0.0, np.cumsum(pnl)[:-1]], rtol=0, atol=1e-9)
                assert np.array_equal(a["ret"], pnl / wb) and np.array_equal(a["win"], pnl > 0)
                assert abs(a["l"].sum() - math.log(float(f["w_end"]) / w0)) < 1e-9
                assert np.array_equal(a["entry_dt"].astype(np.int64), fi) and np.array_equal(a["exit_dt"].astype(np.int64), ex)
                assert a["weekday"].tolist() == [dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).weekday() for t in fi]
                assert a["session"].tolist() == [dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).hour // 8 for t in fi]
                assert np.array_equal(a["month"], np.searchsorted(sctx.edges, ex, side="right") - 1) and (a["month"] >= 0).all()
                assert np.allclose(a["hold_h"], (ex - fi) / 3_600_000.0)
                assert a["pick"] == p["id"] and a["pool"] == p["pool"] and a["arm"] == arm and a["size"] == size
                assert a["money_ok"] == XC.money_allowed(sctx, p["pool"], arm)
                n_tr += len(pnl)
    assert n_tr > 200
    a = XC.account(sctx, xw.core[0], "E0", 0.25)
    with pytest.raises(ValueError):
        a["tr_pnl"][0] = 1.0                                              # read only
    assert a is not XC.account(sctx, xw.core[0], "E0", 0.25)
    assert "ds_private" in sctx.store.path(xw.ds[0], "E0", "q25")       # DeepSeek files under ds_private, as A's Store
    with pytest.raises(ValueError):
        XC.account(sctx, xw.core[0], "E0", 0.5)


def test_reads_outside_results_select_are_refused(xw, ctx, sctx):
    w8, p0 = xw.w8, xw.core[0]
    bad = [os.path.join(w8, "results", "select", "core_not_choosable.json"), os.path.join(w8, "ds_private", "select_ds.json"),
           os.path.join(w8, "ds_private", "owner_report_select.md"), os.path.join(w8, "results", "confirm", p0["id"], "E0__q25.npz"),
           os.path.join(w8, "results", "select_r2", p0["id"], "E0__q25.npz"), xw.lay.out_file("SELECT_KO.md"),
           os.path.join(xw.work, "deadbeef", "results", "select", p0["id"], "E0__q25.npz"),
           os.path.join(w8, "results", "select", p0["id"], "..", "..", "confirm", p0["id"], "E0__q25.npz"),
           os.path.join(w8, "extra", "x.npz"), os.path.join(w8, "results", "select", p0["id"], "E0__q25.json")]
    for c in (ctx, sctx):
        for path in bad:
            with pytest.raises(XC.Refused):
                XC.check_read(c, path)
    with pytest.raises(XC.Refused):
        XC.check_read(ctx, xw.lay.out_file("select.json"))              # select.json only when the context allows it
    assert XC.check_read(sctx, xw.lay.out_file("select.json")) == os.path.realpath(xw.lay.out_file("select.json"))
    assert XC.check_read(ctx, os.path.join(w8, "ds_private", "results", "select", xw.ds[0]["id"], "E0__q25.npz"))
    with pytest.raises(XC.Refused):                                      # a pick id that walks out of results/select/
        XC.account(ctx, {**p0, "id": os.path.join("..", "..", "confirm", p0["id"])}, "E0", 0.25)
    r2 = XC.Ctx(xw.lay, xw.cfg.pin, xw.ph, "extra_r2", picks=xw.cfg.picks)    # after an A select rerun: select_r2/ only
    assert r2.sel_stage == "select_r2" and XC.account(r2, p0, "E0", 0.25)["tr_pnl"].shape == XC.account(ctx, p0, "E0", 0.25)["tr_pnl"].shape
    with pytest.raises(XC.Refused):
        XC.check_read(r2, xw.cfg.store.path(p0, "E0", "q25"))


def test_placebo_stacks_every_seed_block_of_a_choosable_row(xw, ctx, sctx):
    for p, vid in ((xw.core[0], "F1.w3.a"), (xw.ds[1], "F3.a")):
        P = XC.placebo(sctx, p, vid)
        blocks = [xw.cfg.store.load(p, vid, RX.plc_tag(a, b)) for a, b in RX.seed_blocks(40)]
        assert P["n_seeds"] == 40 and P["g"].shape == (40, 36) and np.array_equal(P["seeds"], np.arange(40))
        assert np.array_equal(P["g"], np.concatenate([b["g"] for b in blocks])) and P["counts"].shape == (40, len(MT.COUNT_NAMES))
        assert np.array_equal(P["num"], blocks[0]["num"] + blocks[1]["num"]) and np.array_equal(P["den"], blocks[0]["den"] + blocks[1]["den"])
        c = XC.Ctx(xw.lay, xw.cfg.pin, xw.ph, picks=xw.cfg.picks)      # without select.json: the blocks found on disk
        c.choosable[p["pool"]] = {vid}
        assert all(np.array_equal(XC.placebo(c, p, vid)[k], P[k]) for k in XC.PLC_KEYS)
    with pytest.raises(XC.Refused):
        XC.placebo(sctx, xw.core[0], "F3.a")                             # not choosable in core
    with pytest.raises(XC.Refused):
        XC.placebo(ctx, xw.core[0], "F1.w3.a")                           # no select.json: nothing is choosable
    with pytest.raises(XC.Refused):
        XC.placebo(sctx, xw.core[0], "F7.N12.a")                         # choosable, but no placebo blocks (F7 has none)
    c = XC.Ctx(xw.lay, xw.cfg.pin, xw.ph, picks=xw.cfg.picks)
    c.set_select({"n_seeds": 60, "pools": {"core": {"eligible_ids": ["F1.w3.a"]}}})
    with pytest.raises(FileNotFoundError):
        XC.placebo(c, xw.core[0], "F1.w3.a")                             # a missing block stops the read


def test_money_allowed_is_e0_house_and_the_pools_choosable_ids(ctx, sctx):
    for c in (ctx, sctx):
        assert all(XC.money_allowed(c, pool, arm) for pool in XC.POOLS for arm in ("E0", "HOUSE", "H"))
    assert XC.money_allowed(sctx, "core", "F1.w3.a") and XC.money_allowed(sctx, "ds", "F3.a")
    assert not XC.money_allowed(sctx, "core", "F3.a") and not XC.money_allowed(sctx, "ds", "F1.w3.a")
    assert not XC.money_allowed(ctx, "core", "F1.w3.a") and not XC.money_allowed(sctx, "core", "F5.P1.g25.a")


def test_pooled_M_is_As_M_P_and_masks_recompute_g(xw, ctx, sctx):
    gates = RX.step1_gates(xw.cfg)
    for pool, vid in (("core", "F1.w3.a"), ("core", "F7.N12.a"), ("ds", "F3.a")):
        M = XC.pooled_M(sctx, pool, vid)
        assert M == pytest.approx(gates[(vid, pool)]["M"], abs=1e-15)
        assert XC.pooled_M(sctx, pool, vid, mask_fn=lambda a: np.ones(len(a["tr_pnl"]), bool)) == pytest.approx(M, abs=1e-15)
        assert XC.pooled_M(sctx, pool, vid, size=1.0) == pytest.approx(
            np.mean([MT.pick_Mp(xw.cfg.store.load(p, vid, "q100"), xw.cfg.store.load(p, "E0", "q100")) for p in xw.cfg.pool_picks(pool)]))
        wk = lambda a: a["weekday"] < 5                                      # noqa: E731
        want = []
        for p in xw.cfg.pool_picks(pool):
            g = []
            for arm in (vid, "E0"):
                a = XC.account(sctx, p, arm, 0.25)
                m = a["weekday"] < 5
                g.append(MT.monthly_g(a["tr_exit"][m], a["tr_pnl"][m], float(a["w0"]), sctx.edges)[0])
            want.append(np.mean(g[0] - g[1]))
        assert XC.pooled_M(sctx, pool, vid, mask_fn=wk) == pytest.approx(float(np.mean(want)), abs=1e-15)
    assert XC.pooled_M(sctx, "core", "E0") == 0.0
    for c, pool, vid in ((sctx, "core", "F3.a"), (sctx, "ds", "F1.w3.a"), (ctx, "core", "F1.w3.a")):
        with pytest.raises(XC.Refused):
            XC.pooled_M(c, pool, vid)


# ====================================================================================================== C2 re-runs and reduced files
def test_an_all_true_mask_and_an_unchanged_S_copy_reproduce_step1(xw, ctx):
    ctx.__dict__["market"] = xw.cfg.market
    mk = xw.cfg.market
    n = 0
    for p in (xw.core[0], xw.ds[1]):
        pdata = xw.cfg.make_pickdata(p)
        off = pdata.offered("select", mk)
        full = XC.mask_offered(off, np.ones(len(off["coin"]), bool))
        assert list(full) == list(off) and full is not off
        for arm in ("E0", "F1.w3.a"):
            res = XC.rerun(ctx, pdata, arm, 0.25, offered=full, S=XC.settings_copy(mk, 0.25))
            s = MT.summarize(res, ctx.edges)
            f = xw.cfg.store.load(p, arm, "q25")
            assert all(np.array_equal(np.asarray(s[k]), f[k]) for k in s)
            n += 1
        half = off["side"] > 0
        part = XC.mask_offered(off, half)
        assert len(pdata.offered("select", mk)["coin"]) == len(off["coin"]) and len(part["coin"]) == int(half.sum())
        res = XC.rerun(ctx, pdata, KX.E0, 0.25, offered=part)
        assert MT.summarize(res, ctx.edges)["counts"][0] == int(half.sum())
    S = XC.settings_copy(mk, 0.25, {10: 1000.0})
    assert S[10] == 1000.0 and mk.S(0.25)[10] != 1000.0 and np.array_equal(np.delete(S, 10), np.delete(mk.S(0.25), 10))
    assert n == 4


def test_reduced_files_lie_under_extra_or_ds_private_extra(xw, ctx):
    c0, d0 = xw.core[0], xw.ds[0]
    pc = XC.save_reduced(ctx, c0, "weekend", 0.25, {"g": np.arange(3.0)})
    pd_ = XC.save_reduced(ctx, d0, "weekend", 1.0, {"g": np.arange(2.0)}, part="s01")
    assert pc == os.path.join(ctx.work_extra, "reduced", "weekend", f"{c0['id']}__q25.npz")
    assert pd_ == os.path.join(ctx.private_dir, "reduced", "weekend", f"{d0['id']}__q100__s01.npz")
    assert np.array_equal(XC.load_reduced(ctx, c0, "weekend", 0.25)["g"], np.arange(3.0)) and not os.path.exists(pc + ".part.npz")
    for read in ("../x", "a/b", ".x"):
        with pytest.raises(XC.Refused):
            XC.reduced_path(ctx, c0, read, 0.25)
    r2 = XC.Ctx(xw.lay, xw.cfg.pin, xw.ph, "extra_r2", picks=xw.cfg.picks)
    assert os.sep + "reduced_r2" + os.sep in XC.reduced_path(r2, c0, "weekend", 0.25)


# ====================================================================================================== week bootstrap
def test_week_index_and_the_week_bootstrap(sctx):
    lo, hi = DX.PERIOD_MS["select"]
    assert XC.N_WEEKS == 157 and XC.week_index(lo) == 0 and XC.week_index(ms(2021, 1, 4)) == 1 and XC.week_index(hi - 1) == 156
    assert XC.week_index(lo, True) == 0 and XC.week_index(ms(2021, 1, 4), True) == 0 and XC.week_index(hi - 1, True) == 155
    x = np.random.default_rng(3).normal(0.01, 1.0, 157)
    ci = XC.week_bootstrap_ci(x, n=2000, seed=XC.seed_c11("X-004", "core", "E0"))
    lo_, hi_ = ci
    assert lo_ < x.mean() < hi_ and ci.n_used == 2000 and ci.n_dropped == 0 and ci.contains_zero == (lo_ <= 0 <= hi_)
    assert tuple(XC.week_bootstrap_ci(x, seed=5)) == tuple(XC.week_bootstrap_ci(x, seed=5)) != tuple(XC.week_bootstrap_ci(x, seed=6))
    wide, narrow = XC.week_bootstrap_ci(x, q=(0.005, 0.995)), XC.week_bootstrap_ci(x, q=(0.25, 0.75))
    assert wide[0] < narrow[0] < narrow[1] < wide[1]
    t = np.array([lo + 3_600_000 * k for k in range(0, 26_000, 7)], np.int64)        # trades in every week, weekend in some
    l = np.random.default_rng(4).normal(0.0, 0.01, len(t))
    agg = XC.week_aggregates(t, l, XC.is_weekend(t))
    assert agg.shape == (157, 2, 2) and agg[..., 1].sum() == len(t) and np.isclose(agg[..., 0].sum(), l.sum())
    assert np.isclose(agg[:, 1, 0].sum(), l[XC.is_weekend(t)].sum())
    ci = XC.week_bootstrap_ci(agg, stat=XC.lam_diff, seed=1)
    assert ci[0] < ci[1] and ci.n_dropped == 0
    rare = np.zeros((157, 2, 2))
    rare[:, 0] = (0.01, 3.0)
    rare[7, 1] = (0.02, 1.0)                                              # the bucket exists in one week only: most draws lack it
    ci = XC.week_bootstrap_ci(rare, stat=XC.lam_diff, n=500, seed=2)
    assert ci.n_dropped > 0 and ci.n_used + ci.n_dropped == 500
    with pytest.raises(ValueError):
        XC.week_bootstrap_ci(agg, n=10)                                  # the default statistic needs one value per week


# ====================================================================================================== C8 DeepSeek rows
DS_ROW_A = {"id": "F3.a", "pool": "ds", "name_ko": "반대 신호", "label": "선택 가능", "gates": {"g1": "pass", "g2": "fail", "g3": "not_run", "g4": "pass"},
            "hold": {"median": 3.0, "p90": 9.0, "share_gt4": 0.3, "share_gt8": 0.1, "share_gt18": 0.0}, "entered": 120, "entered_e0": 110,
            "entered_change_pct": 9.1, "skipped": 30, "rejected": 2, "closed": 120, "win_share": 0.45, "reasons": {"SL": 3, "TP": 4, "LIQ": 0},
            "hold_by_state": {"추세장": {"n": 5, "median": 2.0, "few": True}}, "comp_by_tf": {"1h": {"fired": {"F1": 2}, "alone": {"F1": 1}, "n_picks": 3}},
            "hazard": {"num": [[1, 2]], "den": [[3, 4]]}, "same_as_f3": None}
DS_ROW_X = {"read": "X-001", "pool": "ds", "arm": "E0", "coin": "BTCUSDT", "n": 50, "n_off": 400, "n_ent": 50, "n_skip": 20, "n_rej": 1,
            "offered": 400, "wins": 20, "losses": 30, "win_share": 0.4, "hold_median": 3.1, "share_gt8h": 0.1, "reasons_e0": {"END": 1},
            "dN": 0.1, "flag": "건수 적음", "k_of_n": "3/15", "by_coin": {"BTC": {"n": 3}, "DOGEUSDT": {"n": 1}},
            "by_session": {"Asia": {"n": 3, "win_share": 0.3}}, "by_weekday": {"0": {"n": 1}, "토": {"n": 2}}, "by_year": {2021: {"n": 4}},
            "by_arm": {"F1.w3.a": {"entered": 3}, "E0": {"entered": 4}}, "by_pick": {"ds-F10_OTE-1h-1": {"closed": 5}},
            "cells": [{"bucket": "weekend", "n": 3, "few": True}], "tf": "15m", "note": "4h 봉은 첫 시간에 몰림", "dir_hold": 1, "n_units": 15}


def test_ds_row_check_allows_count_class_rows(xw):
    XC.ds_row_check(DS_ROW_A)
    XC.ds_row_check(DS_ROW_X)
    assert XC.ds_guard is XC.ds_row_check
    assert not (XC.DS_EXTRA_ALLOWED & XC.DS_MONEY_KEYS) and not any(XC._money_key(k) for k in XC.DS_EXTRA_ALLOWED)
    assert set(MT.DS_ALLOWED) <= XC.DS_EXTRA_ALLOWED


@pytest.mark.parametrize("key", ["M", "g", "G", "D", "Mp", "pnl_sum", "n_bust", "busts", "after_bust", "n_after_bust", "no_fill", "max_dd",
                                 "growth_pct", "c_k", "dc", "lam", "dlam", "n_pos", "share_pos", "ci_lo", "final_multiple", "mean_R", "roe_mean",
                                 "x_mean", "w_end", "chance_label", "funding_paid", "lev_tier", "cost_month", "rank_by_M", "wallet_share",
                                 "share_growth", "foo", "median"])
def test_ds_row_check_refuses_money_and_unknown_fields(key):
    with pytest.raises(XC.Refused):
        XC.ds_row_check({**DS_ROW_X, key: 1.0})
    if key != "median":                                                  # 'median' is a nested hold statistic, never a row field
        with pytest.raises(XC.Refused):
            XC.ds_row_check({**DS_ROW_X, "by_coin": {"BTC": {"n": 3, key: 1.0}}})


def test_ds_row_check_refuses_nested_and_text_figures():
    for row in ({"hold": {"median": 1.0, "pnl": 2.0}}, {"cells": [{"n": 1, "M": 0.1}]}, {"label": "+3.2%/월"}, {"note": "월 2.5x"},
                {"note": "성장 3"}, {"flag": "45%"}, {"by_coin": {"BTC": {"wallet": 1}}}, {"by_arm": {"F1.w3.a": {"g": [0.1]}}}, [1, 2]):
        with pytest.raises(XC.Refused):
            XC.ds_row_check(row)
    assert XC.ds_key_ok("BTCUSDT", nested=True) and not XC.ds_key_ok("BTCUSDT") and not XC.ds_key_ok(3)


# ====================================================================================================== outputs
def test_write_out_writes_committed_outputs_atomically_and_checks_them(xw, ctx):
    doc = {"run": {"stage": "extra-reads"}, "rows": [dict(DS_ROW_X), {"pool": "core", "arm": "F1.w3.a", "M": 0.001}]}
    p = XC.write_out(ctx, "extra_reads.json", doc)
    assert p == os.path.join(ctx.out_dir, "extra_reads.json") and json.load(open(p))["rows"][1]["M"] == 0.001
    p = XC.write_out(ctx, "extra_reads_rows.csv", [{"pool": "core", "arm": "E0", "n": 3}, {"pool": "ds", "arm": "E0", "n": 4, "wins": 1}])
    assert open(p).read().splitlines() == ["pool,arm,n,wins", "core,E0,3,", "ds,E0,4,1"]
    p = XC.write_out(ctx, "figs/a.svg", "<svg/>")
    assert p == os.path.join(ctx.out_dir, "figs", "a.svg")
    md = f"# 읽기\n\n{XC.TAG_TABLE}\n\n## 코어\n\n| E0 | 120 | 45% |\n\n## 딥시크\n\n| E0 | 120 | 45/120 |\n"
    assert XC.write_out(ctx, "EXTRA_READS_KO.md", md).endswith("EXTRA_READS_KO.md")
    assert not [f for d, _n, fs in os.walk(ctx.out_dir) for f in fs if f.endswith(".tmp")]
    for name in ("select_extra.json", "SELECT_KO_x.md", "confirm.md", "REPORT_KO.md", "figs/select.svg", "../x.json", "/tmp/x.json",
                 "a//b.json", "x.pdf"):
        with pytest.raises(XC.Refused):
            XC.write_out(ctx, name, {} if name.endswith(".json") else "x")
    for name, obj in (("a.json", {"rows": [{"pool": "ds", "arm": "E0", "M": 0.01}]}),
                      ("a.csv", [{"pool": "ds", "arm": "E0", "w_end": 1.0}]),
                      ("a.json", {"note": "ds-F10_OTE-1h-1 grew 3.2%"}),
                      ("a.md", "# x\n\n딥시크 E0 월 3.2%\n"),
                      ("a.md", "# x\n\n## 딥시크\n\n| E0 | 45% |\n"),
                      ("a.md", "# x\n\n| ds-F10_OTE-1h-1 | 12 |\n")):
        with pytest.raises(XC.Refused):
            XC.write_out(ctx, name, obj)
    assert not os.path.exists(os.path.join(ctx.out_dir, "a.json")) and not os.path.exists(os.path.join(ctx.out_dir, "a.md"))


def test_write_out_private_goes_to_ds_private_and_never_into_the_repository(xw, ctx):
    p = XC.write_out(ctx, "extra_reads_ds.json", {"rows": [{"pool": "ds", "arm": "E0", "M": 0.01}]}, private=True)
    assert p == os.path.join(ctx.ds_private_root, "extra_reads_ds.json")
    p = XC.write_out(ctx, "x/y.json", {"M": 1}, private=True)
    assert p == os.path.join(ctx.private_dir, "x", "y.json")
    inrepo = XC.Ctx(xw.lay, {"work": os.path.join(str(xw.root), "w")}, xw.ph)
    with pytest.raises(XC.Refused):
        XC.write_out(inrepo, "a.json", {}, private=True)
    with pytest.raises(XC.Refused):
        XC.write_out(ctx, "select_ds_extra.json", {}, private=True)


def test_the_private_extra_report_passes_A8_3_and_ends_with_the_owners_line(xw, ctx):
    twins = write_text(os.path.join(ctx.private_dir, "twins", "owner_report_extra_twins.md"), "## [비공개] 쌍둥이\n\n[비공개] 둘째 부분\n")
    sha = XC.write_owner_report_extra(ctx, "# 딥시크 금액 보고서 (추가 읽기), 비공개\n\n## 핵심\n\n| E0 | 선택 가능 |\n", twins)
    path = os.path.join(ctx.ds_private_root, "owner_report_extra.md")
    text = open(path, encoding="utf-8").read()
    assert sha == RX.sha256_file(path) and text.endswith(RX.OWNER_REPORT_LAST_LINE + "\n") and "[비공개] 둘째 부분" in text
    assert XC.private_report_problems(ctx, path) == []
    assert XC.private_report_problems(ctx, path + ".none") == ["missing"]
    bad = write_text(os.path.join(ctx.private_dir, "bad.md"), "p = 0.03\n마지막 줄\n")
    assert {"p value", "last line"} <= set(XC.private_report_problems(ctx, bad))
    same = "이 줄은 공개 파일에도 똑같이 있는 아주 긴 줄입니다 12345"
    XC.write_out(ctx, "same.md", f"# x\n\n{same}\n")
    bad = write_text(os.path.join(ctx.private_dir, "bad2.md"), f"{same}\n{RX.OWNER_REPORT_LAST_LINE}\n")
    assert XC.private_report_problems(ctx, bad) == ["a line equals a line of a committed file"]
    with pytest.raises(XC.Refused):
        XC.write_owner_report_extra(ctx, "# x\n\np값 0.01\n")
    os.remove(os.path.join(ctx.out_dir, "same.md"))


def test_run_record_disk_rules_and_parts(xw, ctx, monkeypatch):
    free = {"b": int(1.6 * XC.GB)}
    monkeypatch.setattr(XC.shutil, "disk_usage", lambda _p: types.SimpleNamespace(total=0, used=0, free=free["b"]))
    rec = XC.run_record(ctx, "extra-reads", {"need_bytes": 1, "procs": 3})
    assert rec["stage"] == "extra-reads" and rec["pin8"] == xw.ph[:8] and rec["procs"] == 3 and rec["end_utc"] is None
    assert rec["start_utc"].endswith("Z") and "head" in rec and rec["extra_pin8"] == RX.sha256_file(XC.extra_sha_file(xw.lay))[:8]
    rec.part("X-001", seconds=1.5, accounts=0, bytes=0, dropped=[])
    rec["dropped"].append("X-022 fixed leverage")
    rec.check_disk(0.5 * XC.GB)                                           # 1.6 GB free: writing 0.5 GB leaves 1.1 GB
    with pytest.raises(XC.Refused):
        rec.check_disk(0.7 * XC.GB)                                       # would leave less than 1 GB
    assert rec.finish()["end_utc"] and json.loads(json.dumps(rec))["parts"]["X-001"]["seconds"] == 1.5
    with XC.run_record(ctx, "twins", {}) as r2:
        assert r2["need_bytes"] == XC.DISK_NEED_DEFAULT
    assert r2["end_utc"] is not None
    free["b"] = int(1.4 * XC.GB)                                          # under 1 GB + 0.5 GB: refused at the start
    with pytest.raises(XC.Refused):
        XC.run_record(ctx, "extra-reads", {})
    assert XC.run_record(ctx, "extra-reads", {"need_bytes": 0.8 * XC.GB})["free_bytes_start"] == free["b"]
    assert XC.DISK_NEED_DEFAULT + XC.DISK_MARGIN == 1.5 * XC.GB and XC.DISK_STOP == 1.0 * XC.GB and len(XC.CAP_DROP_ORDER) == 6


# ====================================================================================================== conventions C1-C17
def test_c1_scope_and_c5_status(xw):
    XC.c1_check(xw.orig_picks())
    with pytest.raises(AssertionError):
        XC.c1_check(xw.cfg.picks)
    assert XC.COINS == DX.SYMBOLS and XC.COIN_SHORT == ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH") and XC.N_MONTHS == 36
    assert XC.STATUS.index("after_bust") == 4 and XC.STATUS.index("entered") == 1


def test_c10_time_and_c11_seeds(sctx):
    assert XC.dow(ms(2021, 1, 4)) == 0 and XC.dow(ms(2021, 1, 3, 23, 59)) == 6
    assert XC.is_weekend(ms(2021, 1, 2)) and XC.is_weekend(ms(2021, 1, 3, 23, 59)) and not XC.is_weekend(ms(2021, 1, 1, 23, 59))
    assert not XC.is_weekend(ms(2021, 1, 4))
    assert XC.session_of(ms(2021, 1, 4, 7, 59)) == 0 and XC.session_of(ms(2021, 1, 4, 8)) == 1 and XC.session_of(ms(2021, 1, 4, 16)) == 2
    assert XC.block4(ms(2021, 1, 4, 4)) == 1 and XC.block4(ms(2021, 1, 4, 23, 59)) == 5
    t = np.random.default_rng(1).integers(DX.PERIOD_MS["select"][0], DX.PERIOD_MS["select"][1], 500)
    assert XC.dow(t).tolist() == [dt.datetime.fromtimestamp(int(x) / 1000, dt.timezone.utc).weekday() for x in t]
    assert XC.month_index(DX.PERIOD_MS["select"][0], sctx.edges) == 0 and XC.month_index(DX.PERIOD_MS["select"][1] - 1, sctx.edges) == 35
    assert XC.utc_kst(ms(2021, 1, 1, 15)) == "2021-01-01 15:00 UTC (KST 00:00)"
    assert XC.seed_c11("X-004", "core", "E0") == DX.seed_of("exitflex-extra", "X-004", "core", "E0")
    assert XC.seed_c11("X-004", "ds", "F3.a", "b") == DX.seed_of("exitflex-extra", "X-004", "ds", "F3.a", "b")


def test_c6_c7_c9_pooling_flags_and_split_columns():
    assert XC.k_of_n(3, 23) == "3/23" and XC.per_account_month(23 * 36, 23) == 1.0
    g = np.zeros(36)
    g[:11] = 0.01
    assert XC.alive_months({"g": g, "w_end": 100.0}).all()
    assert XC.alive_months({"g": g, "w_end": 5.0}).tolist() == [True] * 11 + [False] * 25
    assert not XC.alive_months({"g": np.zeros(36), "w_end": 1.0}).any()
    assert XC.c7_mark(0) == "-" and XC.c7_mark(50) == "건수 적음" and XC.c7_mark(150) == "" and XC.c7_mark(150, 2) == "픽 2개"
    assert XC.c7_mark(50, 1) == "건수 적음 · 픽 1개" and XC.c7_mark(30, min_n=20) == "" and XC.c7_mark(150, 3) == ""
    assert XC.se([1.0, 2.0, 3.0]) == pytest.approx(1.0 / math.sqrt(3)) and math.isnan(XC.se([1.0]))
    assert XC.c9_contrib([0.36, 0.72]) == pytest.approx(1.5)


def test_c12_to_c17_units_marks_lines_and_shares():
    assert XC.pct_month(0.0) == 0.0 and XC.pct_month(math.log(1.05)) == pytest.approx(5.0)
    assert np.allclose(XC.pct_month(np.array([0.0, math.log(1.1)])), [0.0, 10.0]) and XC.contrib_pct(0.01) == 1.0
    assert XC.bust_cell(2, 23) == "파산 2/23" and XC.U_CONTRIB == "%/월 기여(근사)" and XC.U_GROWTH == "%/월"
    f7 = {"name": "F7_RF_ONLY", "id": "ds-F7_RF_ONLY-1h-3"}
    assert XC.c13_mark(f7, "F11.a") == "= F3.a" and XC.c13_mark(f7, "F11.b") == "= F3.b" and XC.c13_mark(f7, "F3.a") == ""
    assert XC.c13_mark({"name": "F9_FVG"}, "F11.a") == ""
    assert XC.c15_line(18, 3) == "이 표의 칸은 18개, 그중 건수 적음 3개입니다."
    line = XC.c15_line(18, 3, 2)
    assert line.startswith("이 표의 칸은 18개, 그중 건수 적음 3개입니다.") and "약 0.9개" in line and line.endswith("실제로 벗어난 칸은 2개입니다.")
    assert XC.c16_note(-0.1) == XC.W["W12"] and XC.c16_note(0.0) == XC.W["W12"] and XC.c16_note(0.2) == ""
    assert XC.own_growth_log([{"w_end": 5000 * math.exp(0.36), "w0": 5000.0}, {"w_end": 5000.0, "w0": 5000.0}]) == pytest.approx(0.005)
    assert np.allclose(XC.c17_shares([0.001, 0.001], 0.002), [0.5, 0.5])
    assert XC.c17_shares([0.0005, 0.0004], 0.0009) is None and XC.c17_shares([0.008, -0.006], 0.002) is None
    assert np.allclose(XC.c17_shares([0.006, -0.004], 0.002), [3.0, -2.0])
    assert XC.W["W15"].startswith("이득이 작아") and XC.TAG_TABLE == "참고용 · 고르는 데 안 씀"


def test_c14_deepseek_layout_on_korean_pages():
    ok = "# 읽기\n\n## 코어\n\n| E0 | 120 | 45% |\n\n## 딥시크\n\n### 코인별\n\n| E0 | 120 | 45/120 |\n\n## 코어 부록\n\n| E0 | 45% |\n"
    assert XC.c14_problems(ok) == []
    for bad in ("# x\n\n딥시크 쪽은 15개 픽\n", "# x\n\n| ds-F10_OTE-1h-1 | 12 |\n", "# x\n\n## 딥시크\n\n| E0 | 45% |\n",
                "# x\n\n## 딥시크\n\n### 장세\n\n| E0 | 7% |\n", "# x\n\n## DeepSeek 2021\n", "# x\n\n## 딥시크\n\n| E0 | 낙폭 3 |\n"):
        assert XC.c14_problems(bad), bad
