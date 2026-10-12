"""Tests TW-T1 .. TW-T12 of research/exitflex/PREREG_EXITFLEX_EXTRA.md section TW, on SYNTHETIC data (seeded random walks and
hand-built paths from research/exitflex/test_exitflex.py). TW-T1 reads candidates.json and code only, no market data.

    python -m pytest -q research/exitflex/extra/test_twins.py

They print nothing but pass / fail and counts of cases; no real price is used, so no performance figure exists here.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import copy  # noqa: E402
import hashlib  # noqa: E402
import importlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
XDIR = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(XDIR))
for _p in (HERE, XDIR, ROOT, os.path.join(ROOT, "research", "fullgrid")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_exitflex as TX  # noqa: E402  (A's synthetic world builders and the plain-Python reference ref_trade)
import twins as TW  # noqa: E402

DX, KX, MT, RX = TX.DX, TX.KX, TX.MT, TW.RX
K = KX.K
SPEC = os.path.join(XDIR, "PREREG_EXITFLEX_EXTRA.md")


@pytest.fixture(scope="module", autouse=True)
def _clean_temp(tmp_path_factory):
    """Disk is tight: the synthetic folders are removed when the module is done."""
    yield
    shutil.rmtree(str(tmp_path_factory.getbasetemp()), ignore_errors=True)


@pytest.fixture(scope="module")
def vendor():
    from paperbot import sweepsig
    sweepsig.lib()
    return True


@pytest.fixture()
def f11_on():
    KX.register_f11(lambda *a, **k: None)
    yield
    KX.clear_f11()


def league():
    return importlib.import_module("candleague.league")


# ====================================================================================================== the synthetic universe
class SynProv(TX.Prov):
    """Test provider whose signals depend on the unit's combo (so a default-combo twin differs from its pick); DeepSeek units are
    always 'normal' (as data_x.RealProvider)."""

    def signals(self, pick, sym):
        df, _ = self.frame(sym, pick["tf"])
        c = pick["combo"]
        f = df["close"].ewm(span=c["fast"], adjust=False).mean()
        s = df["close"].ewm(span=c["slow"], adjust=False).mean()
        return ((f > s) & (f.shift(1) <= s.shift(1))).to_numpy(bool), ((f < s) & (f.shift(1) >= s.shift(1))).to_numpy(bool)

    def best(self, pick, sym):
        df, _ = self.frame(sym, pick["tf"])
        if pick["kind"] == "ds":
            return np.zeros(len(df), bool), np.zeros(len(df), bool)
        r = ((df["high"] - df["low"]) / df["close"]).to_numpy(float)          # core: flags that differ by side
        return r > np.nanquantile(r, 0.4), r > np.nanquantile(r, 0.7)


def syn_f11(pick, sym, df, close, sl, ss):
    """A synthetic own exit: F7_RF_ONLY-like (the opposite raw flag as a state component, no level: F11 = F3) or A's causal_f11."""
    if pick["name"] in TW.F3_SAME_NAMES:
        return {"comp_long": [("state", np.asarray(ss, float))], "comp_short": [("state", np.asarray(sl, float))]}
    return TX.causal_f11(pick, sym, df, close, sl, ss)


def spick(kind, name, tf, exit_name, combo):
    return {"id": f"{kind}-{name}-{tf}-1", "kind": kind, "pool": kind, "name": name, "tf": tf, "combo": combo, "exit": exit_name,
            "exit_index": [e[0] for e in K.EXITS].index(exit_name), "rank": 1}


PICKS = [spick("core", "SYNA", "1h", "tp3R|4", {"fast": 5, "slow": 20}), spick("core", "SYNB", "4h", "tp3R|2", {"fast": 4, "slow": 12}),
         spick("ds", "SYNC", "1h", "tp3R|4", {"fast": 6, "slow": 18}), spick("ds", "F7_RF_ONLY", "30m", "tp3R|3", {"fast": 5, "slow": 15})]
DEFAULTS = {"SYNA": {"fast": 8, "slow": 30}, "SYNB": {"fast": 6, "slow": 20}, "SYNC": {"fast": 9, "slow": 26}, "F7_RF_ONLY": {"fast": 7, "slow": 21}}
ELIG = {"core": ["F13.a", "F3.a", "F11.a", "F12.b", "F1.w3.a"], "ds": ["F11.b", "F3.a"]}
PLANTED = 777777777777                                 # the figures of every 선택 불가 row of the synthetic select.json
META = {"o7_commit": "", "extra_pin_sha256": "", "select_json": {}, "select_ko": {}, "run_start_utc": None, "run_end_utc": None,
        "results_dir": "results", "o8_breach": False, "fix": None}


def syn_world(tmp, days=60, seed=81):
    start = DX.PERIOD_MS["select"][0]
    coins = {TX.SYMS[i]: TX.synth_coin(seed + i, days, (100.0, 3000.0)[i], vol=0.0004, drop=0.003, start_ms=start, open_gap_p=0.0002,
                                       outages=2) for i in range(2)}
    folder = TX.write_folder(str(tmp / "data"), coins)
    mk = DX.Market.from_arrays([coins[s] for s in TX.SYMS[:2]], TX.EX, symbols=TX.SYMS[:2])
    return mk, SynProv(folder, TX.SYMS[:2], warm=False)


def syn_ctx(tmp, removed=(), native_check=None, world=None):
    mk, prov = world or syn_world(tmp)
    KX.register_f11(syn_f11)
    lay = RX.Layout(base=str(tmp / "repo" / "exitflex"), root=str(tmp / "repo"), required=())     # $WORK lies outside the 'repository'
    os.makedirs(lay.out, exist_ok=True)
    tl = TW.TLayout(lay)
    pin = {"work": str(tmp / "work"), "data_dir": prov.data_dir}
    vs = [v for v in KX.variants() if v.id in set(TX.SYN_VARIANTS)]

    def make(unit, with_f11):
        return DX.PickData(mk, unit, prov, f11=syn_f11 if with_f11 else None)
    ctx = TW.Ctx(tl, pin, "cd" * 32, mk, PICKS, vs, make, lambda kind, name: dict(DEFAULTS[name]), 1, False, removed, None, None,
                 native_check, league().flip_side)
    ctx.prov = prov
    return ctx


def a_side(ctx, elig):
    """A's select-stage result files of the synthetic picks (E0 at both sizes, the choosable ids at 0.25, core also at 1.0)."""
    for p in ctx.picks:
        pdata = ctx.make_pickdata(p, True)
        for vid in ["E0"] + elig[p["pool"]]:
            for s in ((0.25, 1.0) if (vid == "E0" or p["pool"] == "core") else (0.25,)):
                res = KX.simulate(ctx.market, pdata, KX.variant_by_id(vid), s, "select")
                path = TW.a_file(ctx, p, vid, TW.TAG[s])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                np.savez_compressed(path, **{k: np.asarray(x) for k, x in {**MT.summarize(res, ctx.edges), "scale": s}.items()})


def syn_select(ctx, elig):
    """A synthetic select.json: choosable rows as A writes them; every 선택 불가 row carries planted figures that must never be read."""
    doc = {"pools": {}}
    for pool in ("core", "ds"):
        picks = [p for p in ctx.picks if p["pool"] == pool]
        pools = {p["id"]: pool for p in picks}

        def ld(arm, tag, picks=picks):
            return {p["id"]: TW.load(TW.a_file(ctx, p, arm, tag)) for p in picks}
        e0q, e0l = ld("E0", "q25"), ld("E0", "q100")
        e0_ps = MT.pool_summary(e0q, e0q, pools)[pool]
        rows = []
        for v in ctx.variants:
            if v.id in elig[pool]:
                ps = MT.pool_summary(ld(v.id, "q25"), e0q, pools)[pool]
                row = {"id": v.id, "name_ko": RX.FAMILY_KO[v.famname], "eligible": True, "label": "선택 가능", "hold": ps["hold"],
                       "entered": ps["entered"], "entered_e0": ps["entered_e0"]}
                if pool == "core":
                    lv = MT.pool_summary(ld(v.id, "q100"), e0l, pools)[pool]
                    row.update(M=ps["M"], M_pct_month=100.0 * (math.exp(ps["M"]) - 1.0), Mp=dict(zip(ps["ids"], ps["Mp"])),
                               live={"M": lv["M"], "M_pct_month": 100.0 * (math.exp(lv["M"]) - 1.0), "busts": lv["busts"], "entered": lv["entered"]})
            else:
                row = {"id": v.id, "name_ko": "PLANTED", "eligible": False, "label": "선택 불가", "entered": PLANTED, "entered_e0": PLANTED,
                       "hold": {"median": float(PLANTED), "p90": 1.0, "share_gt4": 0.5, "share_gt8": 0.5, "share_gt18": 0.5},
                       "M": float(PLANTED), "M_pct_month": float(PLANTED), "Mp": {}, "live": {"M_pct_month": float(PLANTED)}}
            rows.append(row)
        doc["pools"][pool] = {"e0": {"hold": e0_ps["hold"], "entered": e0_ps["entered"]}, "variants": rows,
                              "eligible_ids": list(reversed(elig[pool]))}           # reversed: the report puts them in canonical order
    return doc


@pytest.fixture(scope="module")
def syn(tmp_path_factory, vendor):
    """check (on the synthetic universe, with a synthetic TW-C2 failure of core:SYNA), run and report, end to end."""
    tmp = tmp_path_factory.mktemp("tw")
    ctx = syn_ctx(tmp, native_check=lambda unit: unit["name"] != "SYNA")
    a_side(ctx, ELIG)
    sel = syn_select(ctx, ELIG)
    before = TW.listing(ctx.tl, ctx.paths)
    chk = TW.run_checks(ctx, c4=False)
    ctx.removed, ctx.f11_mark = set(chk["removed"]), chk["f11_mark"]
    TW.write_committed(ctx.tl, "twins_check.json", TW.dumps({**chk, "hashes": {}}))
    made = TW.run_all(ctx, quiet=True)
    doc = TW.write_report(ctx, sel, META)
    after = TW.listing(ctx.tl, ctx.paths)
    yield {"ctx": ctx, "sel": sel, "chk": chk, "doc": doc, "made": made, "before": before, "after": after, "tmp": tmp}
    KX.clear_f11()


def md_of(ctx, sfx=""):
    return open(ctx.tl.out_file(f"TWINS_KO{sfx}.md"), encoding="utf-8").read()


def section(md, pool):
    head = "## 코어 풀" if pool == "core" else "## 딥시크 풀"
    body = md.split(head, 1)[1]
    return body.split("\n## ", 1)[0] if pool == "core" else body


def rows_by(P):
    return {(r["id"], r["kind"]): r for r in P["rows"]}


# ====================================================================================================== TW-T1 league definitions
def test_tw_t1_league_definitions_equal_the_twins():
    C, X, L, N = (importlib.import_module(f"candleague.{m}") for m in ("candidates", "exits", "league", "notify"))
    accts = {a["id"]: a for a in C.accounts(C.load())}
    picks = DX.picks()
    assert len(picks) == 38 and K.EXITS[0][0] == "ladder|2" == X.LIVE_EXIT
    for p in picks:
        combo = DX._tup(DX.fg().default_combo(p["kind"], p["name"]))
        xa, ba, fa = accts[TW.x_id(p)], accts[TW.base_id(p)], accts[TW.flip_id(p, 0)]
        assert (xa["role"], xa["kind"], xa["name"], xa["tf"], xa["exit"]) == ("exitonly", p["kind"], p["name"], p["tf"], p["exit"])
        assert DX._tup(xa["combo"]) == combo == TW.twin_pick(p, combo)["combo"]
        house = TW.house_pick(p, combo)
        assert (ba["role"], ba["exit"], DX._tup(ba["combo"])) == ("base", X.LIVE_EXIT, combo)
        assert ba["id"] == house["id"] and K.EXITS[house["exit_index"]][0] == ba["exit"] == house["exit"]
        assert (fa["role"], fa["exit"], DX._tup(fa["combo"])) == ("flip", p["exit"], p["combo"])
        assert KX.exit_of_pick(TW.twin_pick(p, combo), KX.E0) == K.exit_args(p["exit_index"])
    names = sorted({(p["kind"], p["name"]) for p in picks})
    assert len(names) == 16
    for kind, name in names:
        assert DX._tup(DX.fg().default_combo(kind, name)) == DX._tup(C.default_combo(kind, name))
    ids = [u for p in picks for u in [TW.x_id(p), TW.base_id(p)] + [TW.flip_id(p, s) for s in range(TW.N_SEEDS)]]
    assert len(ids) == len(set(ids)) == 38 * 22
    assert not any(TW.flip_id(p, s) in accts for p in picks for s in range(1, TW.N_SEEDS))
    # the twins' own copies equal the league's (TW.3)
    assert list(TW.ROLE_KO.items()) == list(N.ROLE_KO.items())
    ret = lambda f: [ln.strip() for ln in inspect.getsource(f).splitlines() if ln.strip().startswith("return")]   # noqa: E731
    assert ret(TW.flip_side) == ret(L.flip_side) and len(ret(TW.flip_side)) == 1


# ====================================================================================================== TW-T2 flip side and leverage group
def test_tw_t2_flipped_offer_side_best_and_the_rest_unchanged(syn):
    ctx = syn["ctx"]
    n_core_diff = 0
    for p in ctx.picks:
        pdata = ctx.make_pickdata(p, True)
        off = pdata.offered("select", ctx.market)
        snap = {k: v.copy() for k, v in off.items()}
        fo = TW.flipped(pdata, off, TW.flip_id(p, 3))
        assert fo is not off and set(fo) == set(off) and len(off["coin"]) > 20
        want = np.array([1 if hashlib.sha256(f"{TW.flip_id(p, 3)}|{int(c)}".encode()).digest()[0] & 1 else -1
                         for c in off["close"]])
        assert np.array_equal(fo["side"], want) and fo["side"].dtype == np.int64 and set(np.unique(want)) == {-1, 1}
        bl, bs = pdata.best_l[off["tp_idx"]], pdata.best_s[off["tp_idx"]]
        assert fo["best"].dtype == np.bool_ and np.array_equal(fo["best"], np.where(want > 0, bl, bs))
        if p["pool"] == "ds":
            assert not fo["best"].any()
        else:
            n_core_diff += int((bl != bs).sum())
        assert fo["lvl"].dtype == np.float64 and np.isnan(fo["lvl"]).all()
        for k in off:
            if k not in ("side", "best", "lvl"):
                assert fo[k] is off[k]
        assert pdata._off["select"] is off and all(np.array_equal(off[k], snap[k], equal_nan=True) for k in off)
        for vid in TW.NO_FLIP:
            with pytest.raises(ValueError, match="flipped"):
                TW.sim(ctx, pdata, KX.variant_by_id(vid), 0.25, fo)
    assert n_core_diff > 0                                 # the core offers carry best flags that differ by side


# ====================================================================================================== TW-T3 seed 0 is the league's flip
def test_tw_t3_flip_side_equals_the_leagues_for_every_unit_id_and_seed():
    fs = league().flip_side
    closes = np.random.default_rng(3).integers(1_609_459_200_000, 1_704_067_200_000, 1000) // 60_000 * 60_000
    n = 0
    for p in DX.picks():
        for s in range(TW.N_SEEDS):
            acct = TW.flip_id(p, s)
            assert all(TW.flip_side(acct, int(c)) == fs(acct, int(c)) for c in closes)
            n += len(closes)
    assert n == 38 * 20 * 1000


def test_tw_t3_offered_close_is_the_bar_open_plus_the_timeframe(syn):
    ctx = syn["ctx"]
    for p in ctx.picks:
        pdata = ctx.make_pickdata(p, False)
        off = pdata.offered("select", ctx.market)
        for c in range(len(ctx.market.symbols)):
            df = pdata.frames[c][0]
            opens = df["ts"].astype("int64").to_numpy() // 1_000_000
            sel = off["coin"] == c
            assert sel.any() and np.array_equal(off["close"][sel], opens[off["i0"][sel]] + DX.TF_MS[p["tf"]])


# ====================================================================================================== TW-T4 F3 on side'
@pytest.mark.parametrize("mir", [False, True])
@pytest.mark.parametrize("mode", ["a", "b"])
def test_tw_t4_f3_closes_a_flip_on_the_raw_flag_opposite_to_its_own_side(tmp_path, vendor, mir, mode):
    s = TX.Scen(tmp_path, TX.H(*([100] * 10)), longs=[2, 6], shorts=[4], side_mirror=mir)
    raw = s.off["side"].copy()
    assert len(raw) == 3 and raw[0] == raw[2] == -raw[1]
    v = KX.variant_by_id(f"F3.{mode}")
    for third in (-raw[0], raw[0]):                       # the bar-6 signal reverses (side' = raw) or re-enters on the same side
        side = np.array([-raw[0], -raw[0], third])        # the first flip has side' = -raw: its own entry bar's raw flag is opposite
        r = KX.simulate(s.mk, s.pd, v, 0.25, "select", offered=TW.flip_offer(s.pd, s.off, side))
        t0 = TX.START + 180 * TX.MIN
        assert r.status[0] == 1 and r.entry_ts[0] == t0
        # bar 4's raw flag is of the position's own side: no exit there; bar 6's is opposite: exit at its close (offset 420)
        assert r.reason[0] == KX.R_RULE and r.exit_ts[0] == TX.START + 420 * TX.MIN
        assert r.status[1] == 0
        assert r.status[2] == 1 and r.entry_ts[2] == r.exit_ts[0]               # the freed minute, with its own side'
        reversed_ = third != side[0]
        assert reversed_ == (third == raw[0]) and r.sig["side"][2] == third
    # side' = raw: the long closes on bar 4's raw short flag (the pick's own F3)
    r = KX.simulate(s.mk, s.pd, v, 0.25, "select", offered=TW.flip_offer(s.pd, s.off, raw))
    assert r.reason[0] == KX.R_RULE and r.exit_ts[0] == TX.START + 300 * TX.MIN


# ====================================================================================================== TW-T5 flip identity
def test_tw_t5_raw_side_flip_is_the_pick_and_minus_raw_takes_the_other_leverage_group(tmp_path, vendor, f11_on):
    mk, prov, pd_ = TX.diff_world(tmp_path, "1h")
    off = pd_.offered("select", mk)
    ctx = TW.Ctx(None, {"work": str(tmp_path / "w")}, "ab" * 32, mk, [pd_.pick], KX.variants(), None, None)
    flip_arms = TW.arms(ctx, "flip", {**pd_.pick, "pool": "core"})
    assert len(flip_arms) == 85 and not any(v.id in TW.NO_FLIP for v in flip_arms)
    raw = TW.flip_offer(pd_, off, off["side"])
    assert np.array_equal(raw["best"], off["best"])
    n = 0
    for v in flip_arms:
        for scale in TW.SIZES:
            a, b = KX.simulate(mk, pd_, v, scale, "select"), TW.sim(ctx, pd_, v, scale, raw)
            assert TW.same_result(a, b), (v.id, scale)
            n += 1
    assert n == 170
    neg = TW.flip_offer(pd_, off, -off["side"])
    other = np.where(off["side"] > 0, pd_.best_s[off["tp_idx"]], pd_.best_l[off["tp_idx"]])
    assert np.array_equal(neg["best"], other) and (other != off["best"]).any()


# ====================================================================================================== TW-T6 translation onto ladder|2
def test_tw_t6a_exit_tuples_charts_and_f13_on_the_house(syn):
    ctx = syn["ctx"]
    lock = (0.10, 0.05, 0.02)
    p = ctx.picks[1]
    xd, hd = TW.unit_data(ctx, p)
    house = hd.pick
    assert house["exit_index"] == 0 and house["id"] == "base-core-SYNB-4h"
    for v in [KX.E0] + KX.variants():
        got = KX.exit_of_pick(house, v)
        if v.fam == KX.F13 or v.id == "E0" or (v.mode == "a" and v.fam != KX.F13):
            want = (2.0, KX.TP_NONE, 0.0, True) + lock
        elif v.fam in (KX.F11, KX.F12):
            want = (2.0, KX.TP_STRUCT, 0.0, False) + lock
        else:
            want = (2.0, KX.TP_NONE, 0.0, False) + lock
        assert got == want, v.id
    assert KX.exit_of_pick(house, KX.variant_by_id("F13.a")) == KX.exit_of_pick(house, KX.variant_by_id("F13.b")) \
        == KX.exit_of_pick(house, KX.E0) == tuple(K.exit_args(0))
    c0 = hd.chart(KX.E0)
    for vid in TW.F13_IDS:
        c = hd.chart(KX.variant_by_id(vid))
        assert len(c) == 8 and all(np.array_equal(a, b) for a, b in zip(c, c0))
    runs = [KX.simulate(ctx.market, hd, KX.variant_by_id(v), 0.25, "select") for v in ("E0", "F13.a", "F13.b")]
    assert TW.same_result(runs[0], runs[1]) and TW.same_result(runs[0], runs[2]) and runs[0].trades().size > 5
    # the twin code runs neither F13 arm on the house and copies the house E0 figures to their rows
    assert not any(v.id in TW.F13_IDS for v in TW.arms(ctx, "house", p))
    for q in ctx.picks:
        d = os.path.dirname(TW.twin_file(ctx, q, "house", "E0", "q25"))
        assert not any(f.startswith("F13") for f in os.listdir(d))
    I = rows_by(syn["doc"]["pools"]["core"])
    r, e = I[("F13.a", "house")], I[("E0", "house")]
    assert r["mark"] == TW.MARK_HOUSE_F13 and r["M"] == 0.0 and all(r[k] == e[k] for k in ("entered", "hold", "skipped", "rejected", "G"))


def rand_f11(pick, sym, df, close, sl, ss):
    """Random own-exit components, levels and targets (the shape of A's F11 differential test)."""
    n = len(df)
    rng = np.random.default_rng(len(df))
    c = df["close"].to_numpy(float)
    ema = df["close"].ewm(span=12, adjust=False).mean().to_numpy(float)
    st_l = np.where(rng.random(n) < 0.03, np.nan, (c < ema).astype(float))
    st_s = np.where(rng.random(n) < 0.03, np.nan, (c > ema).astype(float))
    lvl_l, lvl_s, tg_l, tg_s = (np.full(n, np.nan) for _ in range(4))
    lvl_l[sl], lvl_s[ss] = c[sl] * 0.994, c[ss] * 1.006
    tg_l[sl], tg_s[ss] = c[sl] * 1.004, c[ss] * 0.996
    return {"comp_long": [("state", st_l), ("event", (rng.random(n) < 0.04).astype(float))],
            "comp_short": [("state", st_s), ("event", (rng.random(n) < 0.04).astype(float))],
            "lvl_long": lvl_l, "lvl_short": lvl_s, "tgt_long": tg_l, "tgt_short": tg_s}


def middle_variants():
    """Every family at its middle parameter (runner_x.MIDDLE_VARIANTS), in modes a and b where the family has both."""
    mid = set(RX.MIDDLE_VARIANTS)
    return [v for v in KX.variants() if v.id in mid or v.id.replace(".b", ".a", 1) in mid]


@pytest.mark.parametrize("tf", ["15m", "1h"])
def test_tw_t6b_rule_x_lock_differential_against_the_plain_python_reference(tmp_path, vendor, f11_on, tf):
    """KX.simulate on picks with exit index 0 (ladder|2) equals A's ref_trade trade for trade, with the lock on in mode a and off in
    mode b: minute, reason, price, leverage and wallet change."""
    w = TX.DIFF_WORLDS[tf]
    coins = {TX.SYMS[i]: TX.synth_coin(51 + i, w["days"], (100.0, 3000.0)[i], vol=w["vol"] * 1.6, drop=0.003, open_gap_p=0.0004, outages=3)
             for i in range(2)}
    coins = {k: TX.carve_merge_holes(v, {"15m": 15, "1h": 60}[tf], 6, 9 + i) for i, (k, v) in enumerate(coins.items())}
    mk, prov, pd_ = TX.build_world(coins, tmp_path, pick=TX.make_pick(tf, "ladder|2"), prov_kw=dict(warm=False), f11=rand_f11)
    off = pd_.offered("select", mk)
    vs = middle_variants()
    assert len(vs) == 31 and {v.mode for v in vs} == {"a", "b"}
    seen, sides, n = set(), set(), 0
    for v in vs:
        r = KX.simulate(mk, pd_, v, 0.25, "select")
        wallet = r.w0
        for q in (int(x) for x in r.trades()):                    # every entered trade, at the wallet the account had then
            d, j, rr, lev, px, _rec = TX.call_ref(mk, prov, pd_, v, off, q, equity=wallet)
            wallet += r.pnl[q]
            ts = mk.ts(int(off["coin"][q]))
            assert abs(d - r.pnl[q]) <= 1e-9 * max(1.0, abs(d)) and ts[j] == r.exit_ts[q] and rr == r.reason[q], (v.id, q)
            assert lev == r.lev[q] and abs(px - r.xpx[q]) <= 1e-9 * max(1.0, abs(px)), (v.id, q)
            seen.add((int(rr), v.mode, v.id))
            sides.add(int(off["side"][q]))
            n += 1
    reasons = {x[0] for x in seen}
    assert {KX.R_LOCK, KX.R_RULE, KX.R_SL, KX.R_END} <= reasons and sides == {-1, 1} and n >= 1000
    assert (KX.R_TP, "b", "F11.b") in seen                             # the strategy's own target on the house
    assert any(x[0] == KX.R_LOCK and x[1] == "a" and x[2] not in ("E0",) for x in seen)       # a rule with the lock on (mode a)


# ====================================================================================================== TW-T7 E0 parity
def test_tw_t7_x_twin_and_house_e0_equal_kernel_account(syn):
    ctx = syn["ctx"]
    n = 0
    for p in ctx.picks:
        xd, hd = TW.unit_data(ctx, p)
        assert xd.pick["combo"] == DEFAULTS[p["name"]] and len(xd.offered("select", ctx.market)["coin"]) > 10
        for pdata, ex in ((xd, p["exit_index"]), (hd, 0)):
            for s in TW.SIZES:
                assert TW.e0_parity(ctx, pdata, ex, s)
                n += 1
    assert n == 16


# ====================================================================================================== TW-T8 metrics and marks
def fake(g, hold_min, counts=None, w_end=5000.0, max_dd=0.1):
    c = np.zeros(11, np.int64) if counts is None else np.asarray(counts, np.int64)
    if counts is None:
        c[1] = c[2] = len(hold_min)
    return {"g": np.asarray(g, float), "hold_min": np.asarray(hold_min, np.int32), "counts": c, "reasons": np.zeros(12, np.int64),
            "w_end": w_end, "w0": 5000.0, "max_dd": max_dd}


def test_tw_t8_growth_mp_hold_and_marks_by_hand():
    g1, g0 = np.array([0.01, -0.02, 0.03]), np.array([0.0, 0.01, 0.0])
    h1, h2 = np.array([30, 300, 600]), np.array([1200])
    d = TW.fig([fake(g1, h1), fake(g1 * 2, h2)], [fake(g0, h2), fake(g0, h2)])
    assert d["G"] == pytest.approx((g1.mean() + 2 * g1.mean()) / 2)
    mp = [float(np.mean(g1 - g0)), float(np.mean(2 * g1 - g0))]
    assert d["M"] == pytest.approx(np.mean(mp)) and d["M_pct_month"] == pytest.approx(100 * (math.exp(np.mean(mp)) - 1))
    hours = np.r_[h1, h2] / 60.0
    assert d["hold"] == MT.hold_stats(hours)
    assert d["hold"]["median"] == pytest.approx(7.5) and d["hold"]["share_gt4"] == pytest.approx(0.75) and d["hold"]["share_gt18"] == 0.25
    assert d["dir_hold"] == "짧아짐" and d["dir_entries"] == "늘어남" and d["n_pos"] == 2
    z = TW.fig([fake(np.zeros(36), [])], [fake(np.zeros(36), [])])            # a unit with no offered signal: G = 0, M_p = 0
    assert z["M"] == 0.0 and z["G"] == 0.0 and z["dir_growth"] == "같음" and math.isnan(z["hold"]["median"])
    assert TW.thin(29) and not TW.thin(30)
    assert [TW.same_side(a, b) for a, b in ((0.0, 1.0), (1e-9, 2.0), (-1.0, 1.0), (1.0, 0.0), (float("nan"), 1.0), (-2.0, -1.0))] == \
        ["0", "같은 쪽", "반대 쪽", "0", "0", "같은 쪽"]


def stacked(gs, holds):
    items = [{**fake(g, h), "num": np.zeros((KX.N_AGE, 2, 2), np.int64), "den": np.zeros((KX.N_AGE, 2, 2), np.int64),
              "hold": np.zeros(5), "pnl_sum": 0.0} for g, h in zip(gs, holds)]
    return TW.stack(items)


def test_tw_t8_flip_seed_statistics_and_direction_rules_by_hand():
    # three seeds, one unit. V's medians: 2 h, 10 h, 1 h; E0's: 1 h, 1 h, 1.5 h: per-seed differences +1, +9, -0.5 h, median +1 h
    # (길어짐); growth: per-seed M = -0.01, +0.02, +0.03
    fv = stacked([np.full(36, -0.01), np.full(36, 0.02), np.full(36, 0.03)], [[120], [600], [60]])
    fe = stacked([np.zeros(36)] * 3, [[60], [60], [90]])
    d = TW.fig_flip([fv], [fe])
    assert d["M"] == {"seed_median": pytest.approx(0.02), "seed_min": pytest.approx(-0.01), "seed_max": pytest.approx(0.03)}
    assert d["n_pos"] == 2 and d["dir_growth"] == "나아짐"
    assert d["hold"]["seed_median"]["median"] == 2.0 and d["hold"]["seed_min"]["median"] == 1.0 and d["hold"]["seed_max"]["median"] == 10.0
    assert d["dir_hold"] == "길어짐" and d["dir_entries"] == "같음" and d["entered"]["seed_median"] == 1
    # the rule is the median over seeds of the per-seed difference, not the difference of the medians
    fv2 = stacked([np.zeros(36)] * 3, [[60], [61], [600]])
    fe2 = stacked([np.zeros(36)] * 3, [[120], [10], [10]])
    d2 = TW.fig_flip([fv2], [fe2])                     # differences -1, +0.85, +9.83 h: median +0.85 -> 길어짐; medians 61 vs 10 min agree
    assert d2["dir_hold"] == "길어짐"
    fv3 = stacked([np.zeros(36)] * 3, [[60], [62], [64]])
    fe3 = stacked([np.zeros(36)] * 3, [[100], [10], [63]])
    d3 = TW.fig_flip([fv3], [fe3])                     # differences -40, +52, +1 min: median +1 -> 길어짐; medians 62 vs 63 -> would be 짧아짐
    assert d3["dir_hold"] == "길어짐"


def test_tw_t8_no_offered_signal_gives_mp_zero_through_the_kernel(syn):
    ctx = syn["ctx"]
    pdata = ctx.make_pickdata(ctx.picks[0], False)
    off = pdata.offered("select", ctx.market)
    empty = {k: v[:0] for k, v in off.items()}
    a = TW.light(KX.simulate(ctx.market, pdata, KX.E0, 0.25, "select", offered=empty), ctx.edges)
    b = TW.light(KX.simulate(ctx.market, pdata, KX.variant_by_id("F9.a"), 0.25, "select", offered=empty), ctx.edges)
    d = TW.fig([b], [a])
    assert d["M"] == 0.0 and d["G"] == 0.0 and d["n_pos"] == 0 and len(a["g"]) == 36


# ====================================================================================================== TW-T9 report rules
def spec_quotes(start, stop):
    text = open(SPEC, encoding="utf-8").read()
    part = text.split(start, 1)[1].split(stop, 1)[0]
    return re.findall(r'^\s*\* "(.*)"\s*$', part, re.M)


def test_tw_t9_fixed_lines_glossary_and_last_line_are_the_spec_verbatim(syn):
    md = md_of(syn["ctx"])
    lines = md.splitlines()
    fixed = spec_quotes("1. **Fixed lines** (verbatim):", "2. **Glossary**")
    gloss = spec_quotes("2. **Glossary** (verbatim):", "3. **Per pool")
    assert tuple(fixed) == TW.FIXED_LINES and tuple(gloss) == TW.GLOSSARY
    assert all(md.count(t) == 1 and t in lines for t in fixed + gloss)
    spec = open(SPEC, encoding="utf-8").read()
    assert f'**Last line** (verbatim): "{TW.LAST_LINE}"' in spec and lines[-1] == TW.LAST_LINE
    for t in (TW.CARD_A_LINE, TW.THIN_HEAD, TW.DS_LINE, TW.O8_BREACH_LINE, *TW.TABLE1_LINES, *TW.CARD_D_LINES, *TW.TABLE4_LINES):
        assert f'"{t}"' in spec
    assert lines.index(fixed[0]) < lines.index(gloss[0]) < lines.index("## 코어 풀") < lines.index("## 딥시크 풀")


def test_tw_t9_rows_order_pick_column_and_no_not_choosable_figure(syn):
    ctx, sel, doc = syn["ctx"], syn["sel"], syn["doc"]
    order = [v.id for v in ctx.variants]
    for pool in ("core", "ds"):
        P = doc["pools"][pool]
        assert P["eligible_ids"] == sorted(ELIG[pool], key=order.index)
        assert [r["id"] for r in P["rows"] if r["kind"] == "pick"] == ["E0"] + P["eligible_ids"]
        I = rows_by(P)
        srow = {r["id"]: r for r in sel["pools"][pool]["variants"]}
        for vid in P["eligible_ids"]:
            assert I[(vid, "pick")]["hold"] == srow[vid]["hold"] and I[(vid, "pick")]["entered"] == srow[vid]["entered"]
            if pool == "core":
                assert I[(vid, "pick")]["M_pct_month"] == srow[vid]["M_pct_month"]
        assert I[("E0", "pick")]["hold"] == sel["pools"][pool]["e0"]["hold"]
    text = TW.dumps(doc) + md_of(ctx) + open(ctx.paths.ds_json).read() + open(ctx.paths.private_md).read()
    assert str(PLANTED) not in text and "PLANTED" not in text
    # a figure of a 선택 불가 id, planted in any kind, is refused
    planted = copy.deepcopy(doc["pools"])
    planted["core"]["rows"].append({**planted["core"]["rows"][-1], "id": "F9.a", "kind": "x"})
    assert TW.rows_guard(planted, {p: ELIG[p] for p in ELIG}) == ["core: F9.a"]
    order_d = {v.id: i for i, v in enumerate(ctx.variants)}
    F = TW.Files(ctx, {pool: {"E0"} | set(ELIG[pool]) for pool in ELIG})
    with pytest.raises(ValueError, match="never read"):
        F.a(ctx.picks[0], "F9.a")
    assert TW.select_rows(sel, "core", order_d)[1].keys() == set(ELIG["core"])


def test_tw_t9_parts_in_order_special_cells_and_the_deepseek_section(syn):
    ctx = syn["ctx"]
    md = md_of(ctx)
    core, ds = section(md, "core"), section(md, "ds")
    heads = [ln[4:6] for ln in core.splitlines() if ln.startswith("### ")]
    assert heads == ["a.", "b.", "c.", "d.", "e.", "f.", "g.", "h."]
    first_growth = min(core.index(w) for w in ("%/월",))
    assert core.index("### c.") < core.index("### d.") <= first_growth
    assert [ln[4:6] for ln in ds.splitlines() if ln.startswith("### ")] == ["a.", "b.", "c.", "h.", "i."]
    assert "%/월" not in ds and "나아" not in ds and TW.DS_LINE in ds
    # special cells: flips under F11 / F12, the house under F13, the TW-C2 removal (core:SYNA), the F11 = F3 note (DeepSeek F7_RF_ONLY)
    I = rows_by(syn["doc"]["pools"]["core"])
    assert I[("F11.a", "flip")]["mark"] == TW.MARK_NO_FLIP and I[("F12.b", "flip")]["mark"] == TW.MARK_NO_FLIP
    assert I[("F13.a", "house")]["mark"] == TW.MARK_HOUSE_F13
    for kind in ("x", "house"):
        r = I[("F11.a", kind)]
        assert r["mark"] == TW.MARK_REMOVED and r["n_units"] == 1
    row_b = next(ln for ln in core.splitlines() if ln.startswith("| F11.a"))
    assert row_b.count(TW.MARK_NO_FLIP) == 1 and row_b.count(TW.MARK_REMOVED + " 1칸") == 2
    assert next(ln for ln in core.splitlines() if ln.startswith("| F13.a")).count(TW.MARK_HOUSE_F13) == 1
    assert syn["chk"]["TW-C2"]["removed"] == ["core:SYNA"] and syn["chk"]["TW-C5"] == {"x": True, "house": True, "accounts": 4}
    J = rows_by(syn["doc"]["pools"]["ds"])
    assert J[("F11.b", "pick")]["same_as_f3"] == "F3.b" and J[("F11.b", "x")]["same_as_f3"] == "F3.b"
    assert J[("F3.a", "pick")]["same_as_f3"] is None
    assert any(TW.F11_NOTE in ln and ln.startswith("| F11.b") for ln in ds.splitlines())
    assert "## 딥시크 풀" in md and "23칸" not in md          # n/N is the pool's own unit count


def test_tw_t9_a_pool_without_choosable_ids_shows_e0_only(syn):
    ctx = syn["ctx"]
    sel = copy.deepcopy(syn["sel"])
    sel["pools"]["ds"]["eligible_ids"] = []
    for r in sel["pools"]["ds"]["variants"]:
        r["eligible"] = False
    doc, md, _ds, private = TW.build_report(ctx, sel, META)
    P = doc["pools"]["ds"]
    assert {r["id"] for r in P["rows"]} == {"E0"} and P["eligible_ids"] == []
    assert "선택 가능한 청산이 없어 지금 청산(E0) 줄만 있습니다." in section(md, "ds")
    assert "[비공개] 선택 가능한 청산이 없어 지금 청산(E0) 줄만 있습니다." in private


def test_tw_t9_o8_breach_line_and_fix_files(syn):
    ctx = syn["ctx"]
    _doc, md, _ds, _p = TW.build_report(ctx, syn["sel"], {**META, "o8_breach": True})
    lines = md.splitlines()
    assert TW.FIXED_LINES[3] not in lines and lines.index(TW.O8_BREACH_LINE) < lines.index(TW.FIXED_LINES[0])
    assert all(t in lines for i, t in enumerate(TW.FIXED_LINES) if i != 3) and lines[-1] == TW.LAST_LINE
    fix = {"n": 1, "note": "표 2의 진입 변화 계산을 고쳤습니다", "utc": "2026-10-13 01:02 UTC"}
    doc, md, _ds, _p = TW.build_report(ctx, syn["sel"], {**META, "fix": fix})
    assert md.splitlines()[:2] == [f"{fix['utc']} 고친 판: {fix['note']}", TW.FIX_RULE_LINE] and "?" not in md
    try:
        TW.write_committed(ctx.tl, "twins_fix1.json", TW.dumps(doc))
        TW.write_committed(ctx.tl, "TWINS_KO_fix1.md", md)
        assert not TW.a6_problems(ctx, json.load(open(ctx.tl.out_file("twins.json"), encoding="utf-8")))
    finally:
        for n in ("twins_fix1.json", "TWINS_KO_fix1.md"):
            if os.path.exists(ctx.tl.out_file(n)):
                os.remove(ctx.tl.out_file(n))


# ====================================================================================================== TW-T10 D11
def test_tw_t10_planted_deepseek_money_is_refused_and_counts_pass(syn):
    ctx, doc = syn["ctx"], syn["doc"]
    tl = ctx.tl
    assert not TW.ds_doc_problems(doc) and all(TW.ds_row_ok(r) for r in doc["pools"]["ds"]["rows"] + doc["pools"]["ds"]["table1"])
    assert not TW.committed_problems("TWINS_KO.md", md_of(ctx))       # counts, win shares, hold hours, reasons, hold / entry words
    for key in ("G", "M", "bust", "busts", "after_bust", "offered", "no_fill", "n_pos", "same_side", "dir_growth", "w_end", "max_dd"):
        bad = copy.deepcopy(doc)
        bad["pools"]["ds"]["rows"][3][key] = 1
        with pytest.raises(SystemExit, match="D11"):
            TW.write_committed(tl, "twins_r2.json", TW.dumps(bad))
    bad = copy.deepcopy(doc)
    bad["pools"]["ds"]["rows"][3]["hold"]["M"] = 0.1                  # a money key nested in an allowed one
    with pytest.raises(SystemExit, match="D11"):
        TW.write_committed(tl, "twins_r2.json", TW.dumps(bad))
    bad = copy.deepcopy(doc)
    bad["pools"]["ds"]["G_P"] = 0.1
    with pytest.raises(SystemExit, match="D11"):
        TW.write_committed(tl, "twins_r2.json", TW.dumps(bad))
    bad = copy.deepcopy(doc)
    bad["pools"]["ds"]["rows"][3]["mark"] = "딥시크 성장 +1.2%"         # free text: the tripwire of A8 (2)
    with pytest.raises(SystemExit, match="D11"):
        TW.write_committed(tl, "twins_r2.json", TW.dumps(bad))
    md = md_of(ctx)
    for planted in ("| E0 | 월 +1.2% |", "파산 2", "p=0.03", "- F3.a: 15칸 중 나아진 칸 9", "최대 낙폭 30%", "G_P 0.1", "같은 쪽 3/15"):
        with pytest.raises(SystemExit, match="D11"):
            TW.write_committed(tl, "TWINS_KO_r2.md", md.replace(TW.DS_LINE, TW.DS_LINE + "\n" + planted))
    with pytest.raises(SystemExit, match="D11"):
        TW.write_committed(tl, "TWINS_KO_r2.md", md.replace(TW.LAST_LINE, "딥시크 지갑 1.5배\n" + TW.LAST_LINE))
    assert not os.path.exists(tl.out_file("twins_r2.json")) and not os.path.exists(tl.out_file("TWINS_KO_r2.md"))
    with pytest.raises(SystemExit, match="not a committed"):
        TW.write_committed(tl, "select.json", "{}")


def test_tw_t10_private_files_only_under_ds_private_extra_and_outside_the_repository(syn):
    ctx = syn["ctx"]
    for path in (os.path.join(ctx.paths.root, "ds_private", "x.md"), os.path.join(ctx.paths.root, "extra", "x.md"),
                 os.path.join(ctx.tl.root, "x.md"), os.path.join(ctx.tl.out, "x.md")):
        with pytest.raises(SystemExit, match="private file"):
            TW.write_private(ctx, path, "x")
    inner = copy.copy(ctx)
    inner.tl = TW.TLayout(RX.Layout(base=os.path.join(ctx.paths.root, "exitflex"), root=ctx.paths.root, required=()))
    with pytest.raises(SystemExit, match="private file"):              # a 'repository' that contains $WORK: refused there too
        TW.write_private(inner, ctx.paths.private_md, "x")
    assert not any(os.path.exists(p) for p in (os.path.join(ctx.paths.root, "ds_private", "x.md"), os.path.join(ctx.tl.root, "x.md")))


def test_tw_t10_the_private_section_markers_no_p_value_no_not_choosable_row_no_shared_line(syn):
    ctx = syn["ctx"]
    text = open(ctx.paths.private_md, encoding="utf-8").read()
    assert not TW.P_VALUE.search(text) and "선택 불가" not in text and "F9.a" not in text
    for ln in text.splitlines():
        if ln.startswith("#"):
            assert re.match(r"^#+ \[비공개\] ", ln)
        elif ln.startswith("|"):
            assert re.match(r"^\| 비공개 \|", ln) or re.match(r"^\|(---\|)+$", ln)
        elif ln.strip():
            assert ln.startswith("[비공개] ")
    committed = {ln.strip() for f in TW.committed_outputs(ctx.tl) for ln in open(f, encoding="utf-8").read().splitlines()}
    assert TW.private_lines(text) and not any(ln in committed for ln in TW.private_lines(text))
    assert "### [비공개] d." in text and "### [비공개] e." in text and "### [비공개] f." in text and "### [비공개] g." in text
    assert "2칸 중 나아진 칸" in text and "20번 중 나아진 번" in text
    assert not any(t in text for t in TW.GLOSSARY + TW.FIXED_LINES)


# ====================================================================================================== TW-T11 isolation, period and cut
def test_tw_t11_a_run_writes_only_the_twins_paths_and_leaves_a_unchanged(syn):
    ctx = syn["ctx"]
    assert syn["before"] == syn["after"] and syn["before"]           # A's folders: equal listings (path, size, sha256)
    assert any("/results/select/" in p for p in syn["before"]) and any("/ds_private/results/select/" in p for p in syn["before"])
    allowed = [ctx.paths.tw, ctx.paths.ptw, ctx.tl.out]
    for top in (ctx.paths.root, ctx.tl.root):
        for dp, _dn, fns in os.walk(top):
            for f in fns:
                p = os.path.join(dp, f)
                assert p in syn["before"] or any(TW.inside(p, a) for a in allowed), p
    assert sorted(os.listdir(ctx.tl.out)) == ["TWINS_KO.md", "twins.json", "twins_check.json"]
    assert sorted(os.listdir(ctx.paths.ptw)) == ["owner_report_extra_twins.md", "results", "twins_ds.json"]
    core_units = set(os.listdir(ctx.paths.results["core"]))
    ds_units = set(os.listdir(ctx.paths.results["ds"]))
    assert all(u.startswith(("core-", "base-core-")) for u in core_units) and all(u.startswith(("ds-", "base-ds-")) for u in ds_units)
    assert len(core_units) == len(ds_units) == 6
    assert syn["made"] == len(TW.expected(ctx)) and all(os.path.exists(f) for f in TW.expected(ctx))
    assert not os.path.exists(ctx.paths.check_tmp)


def test_tw_t11_confirm_is_refused_and_a_minute_at_or_after_2024_stops_the_run(syn, tmp_path):
    ctx = syn["ctx"]
    pdata = ctx.make_pickdata(ctx.picks[0], False)
    with pytest.raises(ValueError, match="select period only"):
        TW.sim(ctx, pdata, KX.E0, 0.25, period="confirm")
    late = TX.path_coin([(180, 101.0)], start_ms=DX.SELECT_CUT_MS - 60 * TX.MIN)
    bad = copy.copy(ctx)
    bad.market = DX.Market.from_arrays([late], TX.EX, symbols=TX.SYMS[:1])
    bad.picks = []
    with pytest.raises(AssertionError, match="at or after the cut"):
        TW.run_all(bad, quiet=True)


def test_tw_t11_a_missing_cut_is_a_refusal_and_the_cut_is_never_made(tmp_path):
    lay, pin = TX.pin_layout(tmp_path)
    tl = TW.TLayout(lay)
    ph = DX.pin_sha(lay.pin_file)
    with pytest.raises(SystemExit, match="cut is missing"):
        TW.real_ctx(tl, pin, ph)
    assert not os.path.exists(DX.cut_dir(pin["work"], ph, DX.SELECT_CUT_MS))


# ====================================================================================================== TW-T12 gate, resume and determinism
def gate_layout(tmp):
    """A temporary A layout (pin file, data, PREREG_EXITFLEX.sha256) plus extra/ code, a league file and PREREG_EXITFLEX_EXTRA.sha256."""
    lay, pin = TX.pin_layout(tmp)
    tl = TW.TLayout(lay)
    os.makedirs(tl.extra_dir, exist_ok=True)
    os.makedirs(os.path.join(lay.root, "candleague"), exist_ok=True)
    for path, text in ((os.path.join(tl.extra_dir, "twins.py"), "x = 1\n"), (os.path.join(lay.root, "candleague", "league.py"), "y = 2\n"),
                       (tl.extra_md, "extra prereg\n")):
        open(path, "w").write(text)
    lines = [f"{DX.sha256_file(p)}  {os.path.relpath(p, lay.root)}" for p in
             (tl.extra_md, os.path.join(tl.extra_dir, "twins.py"), os.path.join(lay.root, "candleague", "league.py"))]
    lines += open(lay.sha_file).read().splitlines()                     # a copy of A's lines
    open(tl.extra_sha, "w").write("\n".join(lines) + "\n")
    return tl, pin


def pin_extra(tl, path):
    with open(tl.extra_sha, "a") as fh:
        fh.write(f"{DX.sha256_file(path)}  {os.path.relpath(path, tl.root)}\n")


def test_tw_t12_gate_prints_its_own_line_and_refuses_each_change(tmp_path, capsys, monkeypatch):
    tl, pin = gate_layout(tmp_path / "ok")
    TW.gate(tl)
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1 and out[0].startswith("[twins pin ok] commit ") and " pin " in out[0] and " extra " in out[0]
    assert not any(ln.startswith("[pin ok]") for ln in out)
    # A's gate and pin lines ignore extra/ (os.listdir of the top folder only)
    RX.gate_pin(tl.a)
    assert not any("extra" in ln for ln in RX.pin_lines(tl.a))
    capsys.readouterr()                                                # A's own [pin ok] line of this direct call
    cases = {"A line": lambda t: open(os.path.join(t.a.base, "PREREG_EXITFLEX.md"), "w").write("changed"),
             "extra file": lambda t: open(os.path.join(t.extra_dir, "twins.py"), "w").write("x = 2\n"),
             "league file": lambda t: open(os.path.join(t.root, "candleague", "league.py"), "w").write("y = 3\n"),
             "unlisted py": lambda t: open(os.path.join(t.extra_dir, "more.py"), "w").write("z = 1\n")}
    for name, change in cases.items():
        t, _pin = gate_layout(tmp_path / name.replace(" ", "_"))
        TW.gate(t)
        change(t)
        with pytest.raises(SystemExit, match="hash mismatch|not pinned"):
            TW.gate(t)
    # an unpinned select.json; then pinned
    t, _pin = gate_layout(tmp_path / "sel")
    for n in ("select.json", "SELECT_KO.md"):
        open(t.a.out_file(n), "w").write("{}" if n.endswith("json") else "x")
    with pytest.raises(SystemExit, match="not pinned"):
        TW.require_select(t, False)
    for n in ("select.json", "SELECT_KO.md"):
        TX.pin_add(t.a, os.path.join("out", n))
    assert TW.require_select(t, False) == {}
    # twins_check.json: unpinned, not pass, recorded hashes that differ from the present ones; then good
    os.makedirs(t.out, exist_ok=True)
    good = {"pass": True, "need_gb": 0.8, "removed": [], "hashes": {os.path.relpath(p, t.root): h for p, h in RX.read_sha_file(t.xlay()).items()}}
    for doc, why in (({**good, "pass": False}, "does not say pass"), ({**good, "hashes": {"exitflex/extra/twins.py": "0" * 64}}, "changed since")):
        open(t.out_file("twins_check.json"), "w").write(json.dumps(doc))
        with pytest.raises(SystemExit, match="not pinned"):
            TW.require_check(t)
        pin_extra(t, t.out_file("twins_check.json"))
        with pytest.raises(SystemExit, match=why):
            TW.require_check(t)
    open(t.out_file("twins_check.json"), "w").write(json.dumps(good))
    pin_extra(t, t.out_file("twins_check.json"))
    assert TW.require_check(t)["pass"]
    # a rerun of check (TW.10): the pin file already lists the earlier twins_check.json, whose old hash the new file may carry
    again = {**good, "hashes": {os.path.relpath(p, t.root): h for p, h in RX.read_sha_file(t.xlay()).items()}, "rerun": True}
    assert "exitflex/extra/out/twins_check.json" in again["hashes"] or any(k.endswith("twins_check.json") for k in again["hashes"])
    open(t.out_file("twins_check.json"), "w").write(json.dumps(again))
    pin_extra(t, t.out_file("twins_check.json"))
    assert TW.require_check(t)["pass"]
    assert TW.is_check_file(t.out_file("twins_check.json")) and TW.is_check_file("x/twins_check_r2.json")
    assert not TW.is_check_file(os.path.join(t.extra_dir, "twins.py"))
    # free disk below need + 0.5 GB (simulated); then enough: the run gets to the cut, finds none and refuses without making it
    monkeypatch.setattr(TW, "free_bytes", lambda path: int(1.2e9))
    with pytest.raises(SystemExit, match="free disk"):
        TW.require_disk(0.8, str(tmp_path))
    with pytest.raises(SystemExit, match="free disk"):
        TW.cmd_run(t)
    monkeypatch.setattr(TW, "free_bytes", lambda path: int(1.4e9))
    TW.require_disk(0.8, str(tmp_path))
    ph = DX.pin_sha(t.a.pin_file)
    with pytest.raises(SystemExit, match="cut is missing"):
        TW.cmd_run(t)
    assert not os.path.exists(DX.cut_dir(_pin["work"], ph, DX.SELECT_CUT_MS))
    out = capsys.readouterr().out
    assert "[twins pin ok]" in out and not re.search(r"^\[pin ok\]", out, re.M)


def test_tw_t12_resume_gives_identical_arrays_and_two_reports_identical_files(syn):
    ctx = syn["ctx"]
    p = ctx.picks[1]
    victims = [TW.twin_file(ctx, p, "x", "F3.a", "q100"), TW.twin_file(ctx, p, "house", "F9.a", "q25"),
               TW.twin_file(ctx, p, "flip", "F5.P1.g50.a", TW.FLIP_TAG), TW.twin_file(ctx, p, "flip", "E0", TW.FLIP_LIVE_TAG),
               TW.twin_file(ctx, ctx.picks[0], "x", "E0", "q25")]
    keep = {f: TW.load(f) for f in victims}
    for f in victims:
        os.remove(f)
    assert TW.run_all(ctx, quiet=True) == 5
    for f in victims:
        z = TW.load(f)
        assert z.keys() == keep[f].keys() and all(np.array_equal(z[k], keep[f][k]) for k in z)
    assert TW.run_all(ctx, quiet=True) == 0
    for f in victims:                                  # the same with two forked workers
        os.remove(f)
    two = copy.copy(ctx)
    two.procs, two.picks = 2, ctx.picks[:2]
    two.by_id = {q["id"]: q for q in two.picks}
    assert TW.run_all(two, quiet=True) == 5
    for f in victims:
        z = TW.load(f)
        assert all(np.array_equal(z[k], keep[f][k]) for k in keep[f])
    files = [ctx.tl.out_file("twins.json"), ctx.tl.out_file("TWINS_KO.md"), ctx.paths.ds_json, ctx.paths.private_md]
    first = [open(f, "rb").read() for f in files]
    TW.write_report(ctx, syn["sel"], META)
    assert [open(f, "rb").read() for f in files] == first


# ====================================================================================================== audits and the private check on the synthetic run
def test_audits_pass_on_the_synthetic_run_and_catch_a_changed_file(syn):
    ctx, sel = syn["ctx"], syn["sel"]
    res = TW.run_audits(ctx, sel)
    assert res == {k: True for k in ("TW-A1", "TW-A2", "TW-A3", "TW-A4", "TW-A5", "TW-A6", "TW-A8")}
    # audit-file (runner_x's A8 + A9) on the committed outputs, as the main session runs it at TW.7 step 6
    for f in TW.committed_outputs(ctx.tl):
        assert not RX.audit_a8_file(f) and not RX.audit_a9_file(f)
    md = ctx.tl.out_file("TWINS_KO.md")
    text = open(md, encoding="utf-8").read()
    try:
        open(md, "w", encoding="utf-8").write(text.replace("시간 /", "시간 /", 1).replace("| 1/4 |", "| 1/4  |", 1))
        assert TW.run_audits(ctx, sel)["TW-A8"] is False
    finally:
        open(md, "w", encoding="utf-8").write(text)


def test_audit_private_checks_the_assembled_owner_report(syn):
    ctx = syn["ctx"]
    part = open(ctx.paths.private_md, encoding="utf-8").read()
    report = "# 딥시크 추가 보고서 [비공개]\n\n" + part + "\n" + RX.OWNER_REPORT_LAST_LINE + "\n"
    path = ctx.paths.owner_extra
    open(path, "w", encoding="utf-8").write(report)
    rec = ctx.tl.out_file("extra_reads.json")
    try:
        assert TW.audit_private(ctx.tl, ctx.paths, False) == {"TW-A9": False}           # its sha256 is not recorded yet
        open(rec, "w").write(json.dumps({"ds_owner_report_extra_sha256": DX.sha256_file(path)}))
        assert TW.audit_private(ctx.tl, ctx.paths, False) == {"TW-A9": True}
        open(path, "w", encoding="utf-8").write(report.replace(RX.OWNER_REPORT_LAST_LINE, "끝"))
        open(rec, "w").write(json.dumps({"ds_owner_report_extra_sha256": DX.sha256_file(path)}))
        assert TW.audit_private(ctx.tl, ctx.paths, False) == {"TW-A9": False}
    finally:
        os.remove(path)
        os.remove(rec)


def test_checks_on_the_synthetic_universe(syn):
    chk = syn["chk"]
    assert chk["pass"] and chk["TW-C1"] == {"pass": True, "accounts": 16} and chk["TW-C3"]["pass"]
    assert chk["TW-C3"]["accounts"] == 4 * 15 and chk["TW-C3"]["signals"] > 100 and chk["need_gb"] == 0.8
    assert TW.account_counts(syn["ctx"])["total"] == syn["doc"]["meta"]["accounts"]["total"]


def test_same_arrays_counts_nan_hold_stats_as_equal_and_still_catches_a_difference():
    nan5 = np.full(5, np.nan)
    a = {"hold": nan5.copy(), "w_end": np.float64(5000.0), "counts": np.zeros(7, np.int64), "hold_min": np.zeros(0, np.int32)}
    b = {k: np.array(v, copy=True) for k, v in a.items()}
    assert TW.same_arrays(a, b)                        # an account with no trade: NaN hold stats on both sides
    b["counts"][1] = 1
    assert not TW.same_arrays(a, b)
    c = {k: np.array(v, copy=True) for k, v in a.items()}
    c["hold"][0] = 1.0
    assert not TW.same_arrays(a, c)
    assert not TW.same_arrays(a, {k: v for k, v in a.items() if k != "hold_min"})
