"""Hunt round 2 core (research/hunt_r2, PREREG_HUNT_R2.md sections 2-6, 11). Synthetic bars and hand-made tables only;
no real price, no round-1 output, never the repository's own pin state.

- lattice (3.1-3.6): the 85 names, the order rules, coarse values = grid.values' values, the appendix table and the
  totals (3,784 / 3,950 / 166 / 15,121 / 4,032 / 8,316 / 4,369 / 670), the fixed-size one-step positions, the box
  blocks (factor nearest 1x), system ids, the two-name rule
- entries (3.1, 3.2, 11): F1 combo function = entries_wide.hunt_raw bit for bit at the defaults and v1's neighbours;
  F2 / F3 / F5 defaults = entries_wide.events_on; the memo / cache kept across combos = fresh per combo
- event store (11, 3.7): layout, the gate flag, both-sides bars, raising combos removed (a raising default stops)
- the engine (11): store signals through hunt.run_signals are bit-identical to hunt.run_system's direct run; non-default
  F1 combos reach every engine entry point round 2 uses; round 1's engine digest unchanged
- the rules of 4.0-4.4 on hand-made tables; the nulls (b′) and (a′); CSCV; determinism; the engine pin check
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)

from research.hunt import entries_wide as EW  # noqa: E402
from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import entries_r2 as E  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import pin_r2 as PN  # noqa: E402
from research.hunt_r2 import pretest_r2 as PT  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402
from research.hunt_r2 import store_r2 as ST  # noqa: E402

DAY = H.DAY_MS
S0 = H.day_ms("2022-01-01")
SYMS = ("BTCUSDT", "ETHUSDT", "AAAUSDT", "BBBUSDT")
SPAN_DAYS, MK_FROM = 230, 190                  # labels need 180 days of history (regime5y); market = last 40 days
NAMES = ("E1", "N20_EMA9_CHOP", "F3_BOS", "TSMOM7", "TSMOM28")
PREREG = os.path.join(ROOT, "research", "hunt_r2", "PREREG_HUNT_R2.md")


# ------------------------------------------------------------------ synthetic world (installed coins, a market, a store)
_W: dict = {}


def _install():
    coins = _W["coins"]
    if len(H._COINS) != len(coins) or any(H._COINS.get(s) is not c for s, c in coins.items()):
        H.install(coins, _W["fund"])


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if "mk" not in _W:
        _W["coins"] = {s: H.synth_coin(s, S0, S0 + SPAN_DAYS * DAY, 50 + i, 10.0 * (i + 1)) for i, s in enumerate(SYMS)}
        _W["fund"] = {s: H.synth_funding(S0, S0 + SPAN_DAYS * DAY, 60 + i) for i, s in enumerate(SYMS)}
        H.install(_W["coins"], _W["fund"])
        _W["mk"] = H.Market(list(SYMS), (S0 + MK_FROM * DAY, S0 + SPAN_DAYS * DAY), name="r2t")
        root = str(tmp_path_factory.mktemp("r2store"))
        for nm in NAMES:
            lat = L.coarse(nm)
            for tf in L.tfs_of(nm):
                for s in SYMS:
                    ST.build(root, "coarse", nm, tf, s, lat.combos, _W["mk"].start, _W["mk"].end)
        _W["root"] = root
    _install()
    return SR.Ctx(_W["mk"], _W["root"])


# ------------------------------------------------------------------ lattice (3.1-3.6)
def test_names_families_and_timeframes():
    nm = L.names()
    assert len(nm) == 85
    fam = [f for f, _ in nm]
    assert (fam.count("F1"), fam.count("F2"), fam.count("F3"), fam.count("F5")) == (3, 36, 42, 4)
    names = [n for _, n in nm]
    assert "F2_DEMARK" not in names and "F6_VWAP_CROSS" not in names
    for n in ("F15_ASIA_BRK", "F15_ASIA_SWEEP", "F15_LON_BRK", "F15_OPEN0930", "F15_OPEN0000"):
        assert L.tfs_of(n) == ("15m", "30m", "1h")
    assert L.tfs_of("E1") == L.TFS and L.tfs_of("F15_ORB") == L.TFS


def test_totals_match_the_prereg():
    t = L.counts()["totals"]
    assert t["coarse"] == 3784 and t["defaults"] == 85 and t["new_coarse"] == 3699
    assert t["grid_valid_only"] == 3950 and t["order_rule_removed"] == 166
    assert t["cells"] == 15121 and t["largest_box"] == 4032 and t["tries"] == 8316
    assert t["selectable"] == 4369 and t["stage0"] == 670


def _fmt(v):
    if isinstance(v, list):
        return "(" + ",".join(str(x) for x in v) + ")"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return repr(v)


def test_appendix_table_row_by_row():
    """Every row of appendix A: numbers, kinds, defaults, coarse values in factor order, coarse, box, tries."""
    import re
    with open(PREREG) as fh:
        txt = fh.read().split("## Appendix A")[1]
    rows = [r for r in txt.splitlines() if r.startswith("| F")]
    seen = 0
    for r in rows:
        fam, name, _tf, nums, co, bx, tr = [c.strip() for c in r.strip("|").split("|")]
        if co == "-":
            assert name in L.OUT_F3
            continue
        seen += 1
        lat = L.coarse(name)
        assert L.family_of(name) == fam
        largest = max(len(L.box(name, c)) for c in lat.combos)
        tries = 2 * len(L.tfs_of(name)) + len(lat) - 1 + largest - 1
        assert (int(co), int(bx), int(tr)) == (len(lat), largest, tries), name
        for j, part in enumerate(p.strip() for p in nums.split(";")):
            pname, kind, _d, vals = re.match(r"(\w+) \((\w+)\) (.+?): (.+)$", part).groups()
            assert lat.params[j] == pname
            spec = L.params_of(name)[j]
            assert {"len": "length", "mult": "mult", "abs": "threshold_abs", "neu": "threshold_neutral"}[kind] \
                == spec["kind"]
            order = sorted(range(len(lat.values[j])), key=lambda i: lat.factors[j][i])
            assert " / ".join(_fmt(lat.values[j][i]) for i in order) == vals, (name, pname)
    assert seen == 85


def test_coarse_and_box_values_are_grid_values():
    G = EW.fullgrid_run().G
    for _f, name in L.names():
        lat = L.coarse(name)
        for j, spec in enumerate(L.params_of(name)):
            gv = [L.hkey(v) for v in G.values(name, spec)]
            for v in lat.values[j]:
                assert L.hkey(v) in gv, (name, spec["name"], v)
            for fi in set(lat.factors[j]):
                for v in L.block_values(name, spec, fi):
                    assert L.hkey(v) in gv, (name, spec["name"], v)
        assert lat.combos[lat.default] == L.default_combo(name) or \
            L.canon(lat.combos[lat.default]) == L.canon(L.default_combo(name))


def test_order_rules_and_defaults():
    for name, chains in L.ORDER_RULES.items():
        pn = [p["name"] for p in L.params_of(name)]
        for ch in chains:
            assert all(x in pn for x in ch), (name, ch)
    for _f, name in L.names():
        assert L.valid_r2(name, L.default_combo(name)), name
    d = L.default_combo("N07_ICHI_CMO")
    assert not L.valid_r2("N07_ICHI_CMO", {**d, "tenkan_len": 26})          # tenkan < kijun strict
    assert not L.valid_r2("N07_ICHI_CMO", {**d, "kijun_len": 52})           # kijun < senkou_b strict
    assert not L.valid_r2("TURTLE20", {"entry_days": 10, "exit_days": 10})
    assert L.valid_r2("TURTLE20", {"entry_days": 20, "exit_days": 5})
    assert not L.valid_r2("E3", {**L.default_combo("E3"), "fast": 28, "slow": 28})
    # grid.valid's own rules are kept (SAR caps, two bodies)
    d = L.default_combo("N10_HA_PSAR")
    assert not L.valid_r2("N10_HA_PSAR", {**d, "sar_af_start": 0.4, "sar_af_max": 0.1})
    d = L.default_combo("N11_BREAKAWAY")
    assert not L.valid_r2("N11_BREAKAWAY", {**d, "small_body": 0.8, "big_body": 0.8})


def test_one_step_positions_have_fixed_size():
    lat = L.coarse("N07_ICHI_CMO")                     # order rules remove points: some positions do not exist
    assert lat.nb.shape == (len(lat), 2 * lat.k)
    for i, key in enumerate(lat.keys):
        for j in range(lat.k):
            for d, col in ((-1, 2 * j), (1, 2 * j + 1)):
                kk = key[:j] + (key[j] + d,) + key[j + 1:]
                want = lat.keys.index(kk) if kk in lat.keys else -1
                assert lat.nb[i, col] == want
    corner = lat.keys.index((0, 0, 0, 0)) if (0, 0, 0, 0) in lat.keys else None
    assert corner is not None and (lat.nb[corner, ::2] == -1).all()
    assert lat.edge[corner] and not lat.edge[lat.default]


def test_box_block_factor_nearest_one_x():
    lat = L.coarse("F15_ORB")                          # orb_bars 2: 1/2x and 1x both round to 2
    assert lat.values == [[2, 4]] and lat.factors == [[4, 7]]
    assert L.box("F15_ORB", {"orb_bars": 2}).values == [[2, 3]]
    assert L.box("F15_ORB", {"orb_bars": 4}).values == [[3, 4, 6]]
    b = L.box("N15_KC_AO", L.default_combo("N15_KC_AO"))
    assert len(b) <= 81 and L.default_combo("N15_KC_AO") in b.combos   # the centre is the coarse peak
    assert b.values[0] == [16, 20, 25]                 # kc_len 20 x (0.8, 1, 1.25)
    b2 = L.box("E3", {**L.default_combo("E3"), "threshold": 1.75})
    assert b2.values[0] == [1.625, 1.75, 2.0]           # neutral f in (1.25, 1.5, 2)


def test_combo_sha_and_system_id():
    c = {"b": 1.0, "a": [1, 2], "c": 3}
    assert L.canon(c) == '{"a":[1,2],"b":1.0,"c":3}'
    assert L.combo_sha(c) == hashlib.sha256(b'{"a":[1,2],"b":1.0,"c":3}').hexdigest()[:12]
    assert L.system_id("F2", "N01_ST_EMA", "1h", "G1", c) == f"R2:F2:N01_ST_EMA:1h:G1:{L.combo_sha(c)}"


def test_two_names_one_system():
    order = [n for _f, n in L.names()]
    assert L.owner_of_shared("tsmom", {"lookback_days": 14}, order) == "TSMOM7"      # tie -> the earlier name
    assert L.owner_of_shared("tsmom", {"lookback_days": 56}, order) == "TSMOM28"
    i14 = L.coarse("TSMOM28").index({"lookback_days": 14})
    same = SR.foreign_masks(order, {"TSMOM7": ("4h", "G1"), "TSMOM28": ("4h", "G1")})
    other = SR.foreign_masks(order, {"TSMOM7": ("1h", "G1"), "TSMOM28": ("4h", "G1")})
    assert same["TSMOM28"][i14] and same["TSMOM28"].sum() == 1 and not same["TSMOM7"].any()
    assert not other["TSMOM28"].any()                  # TSMOM7 does not reach 14 days at 4h G1 then
    assert not same["TURTLE20"].any() and not same["TURTLE55"].any()


def test_counts_json_is_the_code_count():
    p = os.path.join(ROOT, L.COUNTS_REL)
    if not os.path.exists(p):
        pytest.skip("counts.json not written yet")
    with open(p) as fh:
        assert json.load(fh) == json.loads(json.dumps(L.counts()))


# ------------------------------------------------------------------ entries (3.1, 3.2, 11)
def _bars(days, seed, tf):
    from test_hunt_entries import bars_of, synth
    return bars_of(synth(days * 288, seed), tf)


@pytest.mark.parametrize("tf", L.TFS)
def test_f1_equals_hunt_raw_at_defaults_and_v1_neighbours(tf):
    b = _bars(70, 3, tf)
    for name, (par, main, nbrs) in H.V1_ENTRIES.items():
        for v in (main,) + tuple(nbrs):
            combo = {**L.default_combo(name), par: v}
            a, r = EW.hunt_raw(name, b, v), E.f1_raw(name, b, combo)
            assert np.array_equal(a[0], r[0]) and np.array_equal(a[1], r[1]), (name, v)


@pytest.mark.parametrize("tf", ["15m", "4h"])
def test_defaults_equal_round_one_events(tf):
    b, btc = _bars(50 if tf == "15m" else 120, 5, tf), _bars(50 if tf == "15m" else 120, 6, tf)
    R = EW.fullgrid_run()
    for fam, name in L.names():
        if tf not in L.tfs_of(name):
            continue
        kind = L.KIND_OF[fam]
        combo = (EW.HUNT_MAIN[name] if fam == "F1" else EW.FAMOUS_COMBO[name] if fam == "F5"
                 else R.default_combo(kind, name))
        ev = EW.events_on({"id": "t", "name": name, "kind": kind, "tf": tf, "combo": combo}, b, "ETHUSDT", btc)
        el, es = E.SeriesEvents(name, b, "ETHUSDT", btc).events(L.default_combo(name))
        assert np.array_equal(el, ev["long"]) and np.array_equal(es, ev["short"]), name


def test_memo_and_cache_kept_across_combos_equal_fresh():
    """11: every F2 / F3 name over a lattice sample (coarse and box combos) gives the same events with the memo and
    the DeepSeek cache kept across combos as with a fresh one per combo (also on BTCUSDT, no context)."""
    b, btc = _bars(30, 7, "15m"), _bars(30, 8, "15m")
    bad = []
    for fam, name in L.names():
        if fam not in ("F2", "F3"):
            continue
        lat = L.coarse(name)
        rng = np.random.default_rng(len(name))
        idx = sorted({lat.default, *rng.choice(len(lat), size=min(4, len(lat)), replace=False).tolist()})
        combos = [lat.combos[i] for i in idx]
        bx = L.box(name, lat.combos[idx[-1]])
        combos += [bx.combos[i] for i in rng.choice(len(bx), size=min(2, len(bx)), replace=False)]
        for sym, ctx in (("ETHUSDT", btc), ("BTCUSDT", None)):
            kept = E.SeriesEvents(name, b, sym, ctx, fresh=False)
            k1 = [kept.events(c) for c in combos]
            k2 = [E.SeriesEvents(name, b, sym, ctx, fresh=True).events(c) for c in combos]
            if not all(np.array_equal(x[0], y[0]) and np.array_equal(x[1], y[1]) for x, y in zip(k1, k2)):
                bad.append((name, sym))
    assert not bad and not (set(E.FRESH_PER_COMBO) - {n for _f, n in L.names()})


# ------------------------------------------------------------------ event store (11, 3.7)
def test_store_holds_ungated_select_events_with_g1_flag(world):
    ctx = world
    name, tf, sym = "N20_EMA9_CHOP", "1h", "ETHUSDT"
    lat = L.coarse(name)
    u = ST.StoreUnit(ST.unit_dir(ctx.root, "coarse", name, tf, sym))
    ser = H.series(sym, tf)
    se = E.SeriesEvents(name, ser.bars, sym, None)
    cm = ser.bars.close_ms
    inper = (cm >= ctx.start) & (cm < ctx.end)
    for ci in (lat.default, 0, len(lat) - 1):
        el, es = se.events(lat.combos[ci])
        both = el & es & inper
        j, side, g1 = u.events(ci)
        want = np.r_[np.flatnonzero(el & inper & ~both), np.flatnonzero(es & inper & ~both)]
        assert np.array_equal(j, want) and j.dtype == np.int32 and side.dtype == np.int8 and g1.dtype == np.int8
        assert np.array_equal(g1, (ser.code[j] == H.TREND).astype(np.int8))
        assert u.n_both[ci] == both.sum() and set(np.unique(side)) <= {-1, 1}
    assert u.meta["combo_sha"] == [L.combo_sha(c) for c in lat.combos]
    assert ST.unit_complete(u.path, lat.combos, ctx.start, ctx.end, ser)
    assert not ST.unit_complete(u.path, lat.combos[:-1], ctx.start, ctx.end, ser)


def test_raising_combo_is_removed_and_a_raising_default_stops(world, tmp_path, monkeypatch):
    ctx = world
    name = "F3_BOS"
    lat = L.coarse(name)
    bad = L.canon(lat.combos[0])
    orig = E.SeriesEvents.events

    def ev(self, combo):
        if L.canon(combo) == bad and self.sym == "AAAUSDT":
            raise ZeroDivisionError("synthetic")
        return orig(self, combo)
    monkeypatch.setattr(E.SeriesEvents, "events", ev)
    root = str(tmp_path)
    for tf in L.tfs_of(name):
        for s in SYMS:
            ST.build(root, "coarse", name, tf, s, lat.combos, ctx.start, ctx.end)
    units = [ST.StoreUnit(ST.unit_dir(root, "coarse", name, "1h", s)) for s in SYMS]
    rem = ST.removed_of(units)
    assert list(rem) == [0] and rem[0].startswith("AAAUSDT: ZeroDivisionError")
    u = SR.name_unit(SR.Ctx(ctx.mk, root), name, real=False)
    assert not u["exists"][0] and np.isnan(u["S"][0]) and u["exists"][1:].all()
    assert SR.point_values(np.asarray([0.5]), np.asarray([100]), np.asarray([False]))[0] == 0.0
    bad = L.canon(lat.combos[lat.default])
    for s in SYMS:
        ST.build(root, "coarse", name, "1h", s, lat.combos, ctx.start, ctx.end)    # complete: skipped
    os.rename(ST.unit_dir(root, "coarse", name, "1h", "AAAUSDT"), str(tmp_path / "old"))
    ST.build(root, "coarse", name, "1h", "AAAUSDT", lat.combos, ctx.start, ctx.end)
    SR._UNITS.clear()
    with pytest.raises(RuntimeError, match="default combo raises"):
        SR.name_unit(SR.Ctx(ctx.mk, root), name)
    SR._UNITS.clear()


# ------------------------------------------------------------------ engine identity (11)
def _spec(fam, name, tf, gate):
    kind = L.KIND_OF[fam]
    combo = (EW.HUNT_MAIN[name] if fam == "F1" else EW.FAMOUS_COMBO[name] if fam == "F5"
             else EW.fullgrid_run().default_combo(kind, name))
    return {"id": f"{fam}:{name}:{tf}:{gate}", "family": fam, "name": name, "strategy": name, "kind": kind, "tf": tf,
            "gate": gate, "combo": combo}


@pytest.mark.parametrize("fam,name,tf", [("F1", "E1", "15m"), ("F2", "N20_EMA9_CHOP", "30m"), ("F3", "F3_BOS", "1h"),
                                         ("F5", "TSMOM7", "4h")])
def test_store_signals_through_the_engine_equal_a_direct_hunt_run(world, fam, name, tf):
    ctx = world
    lat = L.coarse(name)
    units = SR.load_units(ctx.root, "coarse", name, tf, ctx.syms)
    for gate in ("G1", "NONE"):
        H._EVENTS.clear()
        H._SIGS.clear()
        spec = _spec(fam, name, tf, gate)
        direct_sig = H.system_signals(ctx.mk, spec)
        sig = SR.store_sig(ctx, units, lat.default, gate, tf)
        for x in ("k", "j", "side"):
            assert np.array_equal(sig[x], direct_sig[x]), (name, gate, x)
        a = H.run_system(ctx.mk, spec, H.R_BASE, "base", detail=True, days=False)
        b = H.run_signals(ctx.mk, [(sig, 0)], H.R_BASE, "base", detail=True, days=False)
        a.pop("signal_counts")
        assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
        assert SR.run_sig(ctx.mk, sig)["S"] == a["mean_lnM"]
        if gate == "G1" and name in ("E1", "F3_BOS"):
            assert len(sig["k"]) > 0                      # the gate path is exercised on these


def test_non_default_f1_combos_reach_every_engine_entry_point(world):
    """11 integration: E1 vol_len 40 / vol_mult 2.5 and E3 slow 200 give round 2's events (not hunt_raw(channel)'s)
    through run_signals, run_engine([(sig, src)]), control_a and control_b."""
    ctx = world
    mk = ctx.mk
    for name, over in (("E1", {"vol_len": 40, "vol_mult": 2.5}), ("E3", {"slow": 200})):
        combo = {**L.default_combo(name), **over}
        tf = "15m"
        K, J, S, Jd = [], [], [], []
        for k, s in enumerate(SYMS):
            ser = H.series(s, tf)
            el, es = E.SeriesEvents(name, ser.bars, s).events(combo)
            dl = EW.events_on({"id": "x", "name": name, "kind": "hunt", "tf": tf,
                               "combo": EW.HUNT_MAIN[name]}, ser.bars, s)["long"]
            ok = ctx.ok(tf, k) & (ser.bars.close_ms >= mk.start) & (ser.bars.close_ms < mk.end)
            for side, ev in ((1, el), (-1, es)):
                jj = np.flatnonzero(ev & ok & ~(el & es))
                K.append(np.full(len(jj), k))
                J.append(jj)
                S.append(np.full(len(jj), side))
            Jd.append(np.flatnonzero(dl & ok))
        sig = SR.canon_sig(tf, np.concatenate(K), np.concatenate(J), np.concatenate(S))
        assert len(sig["k"]) > 0
        r2_long = sig["j"][sig["side"] > 0]
        assert not np.array_equal(np.sort(r2_long), np.sort(np.concatenate(Jd)))     # not hunt_raw(channel)'s events
        a = H.run_signals(mk, [(sig, 0)], H.R_BASE, "base")
        b = H.run_engine([(sig, 3)], mk.start, mk.end, mk=mk)
        assert a["candidates"] == len(sig["k"]) == b["candidates"]
        assert b["metrics"]["mean_lnM"] == a["mean_lnM"] and b["metrics"]["n_positions"] == a["n_positions"]
        ca = H.control_a(mk, sig, H.rng_of("hunt-r2", "t", "a", 1))
        cb = H.control_b(sig, H.rng_of("hunt-r2", "t", "b", 1))
        assert np.array_equal(cb["k"], sig["k"]) and np.array_equal(cb["j"], sig["j"])
        for k in range(len(SYMS)):
            assert (ca["k"] == k).sum() == (sig["k"] == k).sum()
        assert H.boot_p(np.asarray(a["lnM"]), 7, 1000) == H.boot_p(np.asarray(a["lnM"]), 7, 1000)


def test_round_one_engine_digest_unchanged():
    from test_hunt import GOLDEN_DIGEST, GOLDEN_DIGEST_F64, _golden_digest
    try:
        assert _golden_digest(f32_values=True) == GOLDEN_DIGEST
        assert _golden_digest() == GOLDEN_DIGEST_F64
    finally:
        if "coins" in _W:
            _install()


# ------------------------------------------------------------------ the rules of 4.0-4.4 on hand-made tables
class _Lat:
    def __init__(self, keys, nvals, default=0):
        self.keys = keys
        self.nb = L._neighbours(keys, nvals)
        self.default = default
        self.k = len(nvals)


def _grid(nv):
    import itertools
    keys = list(itertools.product(*[range(n) for n in nv]))
    return _Lat(keys, nv, default=keys.index(tuple(n // 2 for n in nv)))


def test_position_values_and_fixed_size_plateau():
    lat = _grid([3])                                       # points 0, 1, 2 (default 1)
    S = np.array([0.4, -0.2, 0.3])
    n = np.array([100, 100, 10])
    ex = np.array([True, True, True])
    v = SR.point_values(S, n, ex)
    assert list(v) == [0.4, -0.2, 0.0 + min(0.3, 0)]          # n < 72 -> min(S, 0)
    P = SR.plateau(S, n, lat.nb, ex)
    assert P[0] == pytest.approx(np.median([0.4, 0.0, -0.2]))  # outside the lattice counts 0
    assert P[1] == pytest.approx(np.median([-0.2, 0.4, 0.0]))
    assert P[2] == pytest.approx(np.median([0.3, -0.2, 0.0]))
    ex2 = np.array([True, False, True])                       # removed (3.7) or invalid: counts 0, no P of its own
    P2 = SR.plateau(S, n, lat.nb, ex2)
    assert np.isnan(P2[1]) and P2[0] == pytest.approx(np.median([0.4, 0.0, 0.0]))
    bust_nb = SR.point_values(np.array([0.7]), np.array([80]), np.array([True]))    # a busted neighbour keeps its S
    assert bust_nb[0] == 0.7


def test_corner_needs_itself_and_its_neighbours_positive():
    """4.2: a corner with e missing positions has P_c > 0 only if at most k - e of its 2k + 1 - e real values are
    <= 0 (k = 2, e = 2: none of its 3 real values may be <= 0)."""
    lat = _grid([3, 3])
    corner = lat.keys.index((0, 0))
    S = np.full(9, 0.5)
    n = np.full(9, 100)
    ex = np.ones(9, bool)
    assert SR.plateau(S, n, lat.nb, ex)[corner] > 0
    S2 = S.copy()
    S2[lat.keys.index((1, 0))] = -0.1
    assert not SR.plateau(S2, n, lat.nb, ex)[corner] > 0
    centre = lat.keys.index((1, 1))
    S3 = S.copy()
    S3[lat.keys.index((0, 1))] = -0.1
    S3[lat.keys.index((2, 1))] = -0.1
    assert SR.plateau(S3, n, lat.nb, ex)[centre] > 0         # 2 of 5 values <= 0: still a plateau


def _st(lat, S, S2=None, n=None, bust=None, ex=None, **kw):
    m = len(lat.keys)
    return SR.stage_a(lat, np.asarray(S, float), np.full(m, 100) if n is None else np.asarray(n),
                      np.zeros(m, bool) if bust is None else np.asarray(bust), np.ones(m, bool) if ex is None else ex,
                      S2=None if S2 is None else np.asarray(S2, float), **kw)


def test_eligibility_peak_and_candidate_rules():
    lat = _grid([3, 3])                                    # 2 numbers: every existing neighbour S > 0 and S2 > 0
    S = np.array([0.1, 0.2, 0.1, 0.2, 0.3, 0.2, 0.1, 0.6, 0.5])
    S2 = np.full(9, 0.1)
    r = _st(lat, S, S2)
    # (2, 1): median(.6, .3, 0 (outside), .1, .5) = .3 beats the default (1, 1): median(.3, .2, .6, .2, .2) = .2
    assert r["eligible"].all() and r["peak"] == 7 and r["candidate"]
    assert r["P_peak"] == pytest.approx(0.3) and r["P_default"] == pytest.approx(0.2)
    S2b = S2.copy()
    S2b[lat.keys.index((2, 0))] = -0.1                     # a neighbour of the peak with S2 <= 0 (2 numbers)
    r = _st(lat, S, S2b)
    assert not r["eligible"][7] and r["peak"] != 7
    nn = np.full(9, 100)
    nn[[lat.keys.index((1, 1)), lat.keys.index((2, 0))]] = 50  # 2 of the 3 existing neighbours of (2, 1) under 72
    r = _st(lat, S, S2, n=nn)
    assert not r["eligible"][7]                            # fewer than half with n >= 72 and no bust
    bb = np.zeros(9, bool)
    bb[lat.keys.index((2, 0))] = True
    r = _st(lat, S, S2, bust=bb)
    assert r["eligible"][7]                                # 2 of 3 fine: at least half
    r = _st(lat, S, None)                                  # null: no S2 conditions, ties by S
    assert r["P2"] is None and r["peak"] >= 0
    # 4.2: the default stays in the peak search; when it is the peak the name is no candidate
    S4 = np.full(9, 0.3)
    S4[4] = 0.9
    r = _st(lat, S4, np.full(9, 0.1))
    assert r["peak"] == 4 and r["peak_is"] == "the default" and not r["candidate"]
    # a default in effect that is the best plateau blocks the name (4.2), it is not skipped for the next point
    deff = np.zeros(9, bool)
    deff[7] = True
    r = _st(lat, S, S2, default_eff=deff)
    assert r["peak"] == 7 and r["peak_is"] == "a default in effect" and not r["candidate"]
    # a point another name owns (3.6 two names) is never this name's peak: the next point is
    r = _st(lat, S, S2, foreign=deff)
    assert r["peak"] != 7 and r["peak_is"] is None
    # ties: P, then P2, then S, then lattice order
    lat1 = _grid([5])
    S5 = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    r = _st(lat1, S5, np.array([0.1, 0.1, 0.3, 0.3, 0.3]))
    assert r["peak"] == 2 and r["peak_is"] == "the default" and not r["candidate"]   # P equal; P2 .3 at 2-4: order
    r = _st(lat1, np.array([0.2, 0.25, 0.2, 0.2, 0.2]), np.full(5, 0.1))
    assert r["peak"] == 1                                  # P and P2 equal; the higher S
    r = _st(lat1, S5, np.full(5, 0.1))
    assert r["peak"] == 0                                  # P, P2, S equal: the earlier lattice point


def test_one_or_two_number_rule_only_for_small_k():
    lat3 = _grid([3, 3, 3])
    S = np.full(27, 0.3)
    S[lat3.keys.index((1, 1, 0))] = -0.05                  # one neighbour of (1, 1, 1)... and of (2, 1, 0)
    r = _st(lat3, S, np.full(27, 0.1))
    assert r["eligible"][lat3.keys.index((1, 1, 1))]        # 3 numbers: a negative neighbour is allowed
    lat2 = _grid([3, 3])
    S2 = np.full(9, 0.3)
    S2[lat2.keys.index((1, 0))] = -0.05
    r = _st(lat2, S2, np.full(9, 0.1))
    assert not r["eligible"][lat2.keys.index((1, 1))]


def test_anchor_rule():
    rows = [{"tf": tf, "gate": g, "S": 0.0, "n": 100, "bust": False, "median_M": 1.0} for tf in H.TF_ORDER
            for g in ("G1", "NONE")]
    rows[3]["S"], rows[5]["S"] = 0.5, 0.5
    rows[5]["median_M"] = 1.1
    assert SR.anchor_slot(rows) == 5                       # tie on S -> higher median M
    rows[5]["median_M"] = 1.0
    assert SR.anchor_slot(rows) == 3                       # then the faster timeframe
    rows[7]["S"], rows[7]["n"] = 9.0, 10                   # n < 72 never the anchor while one qualifies
    rows[6]["S"], rows[6]["bust"] = 8.0, True
    assert SR.anchor_slot(rows) == 3
    for r in rows:
        r["n"] = 10
    assert SR.anchor_slot(rows) == 7                       # none qualifies: the highest S overall
    rows2 = [{"tf": "1h", "gate": "NONE", "S": 0.1, "n": 100, "bust": False, "median_M": 1.0},
             {"tf": "1h", "gate": "G1", "S": 0.1, "n": 100, "bust": False, "median_M": 1.0}]
    assert SR.anchor_slot(rows2) == 1                      # G1 before NONE


def test_ranking_and_step_down_hurdle():
    c = [{"name": "Z", "family": "F2", "P": 0.3, "P2": 0.1}, {"name": "A", "family": "F3", "P": 0.3, "P2": 0.1},
         {"name": "B", "family": "F2", "P": 0.3, "P2": 0.2}, {"name": "C", "family": "F1", "P": 0.5, "P2": 0.0}]
    assert [x["name"] for x in SR.rank_candidates(c)] == ["C", "B", "Z", "A"]
    reps = [[0.1, 0.05], [0.2], []] + [[0.01]] * 197
    sc = SR.null_rank_scores(reps, 3)
    assert sc.shape == (200, 3) and list(sc[0]) == [0.1, 0.05, 0.0] and list(sc[2]) == [0, 0, 0]
    rng = np.random.default_rng(1)
    na, nb_ = rng.uniform(0, 1, (200, 4)), rng.uniform(0, 1, (200, 4))
    qa = [np.percentile(na[:, r], 95) for r in range(4)]
    qb = [np.percentile(nb_[:, r], 95) for r in range(4)]
    real = [max(qa[0], qb[0]) + 0.01, max(qa[1], qb[1]) + 0.01, (qa[2] + 0.0) if qa[2] > qb[2] else qb[2], 2.0]
    out = SR.step_down(real, na, nb_)
    assert [o["taken"] for o in out] == [True, True, False, False]
    assert out[2]["label"] in ("failed (a′)", "failed (b′)") and out[3]["label"] == "not taken (below a failed rank)"
    assert out[0]["thr_a"] == pytest.approx(qa[0])
    out = SR.step_down([0.0], na, nb_)
    assert out[0]["label"] == "failed both"


def test_box_plateau_and_box_best():
    S = np.array([0.1, 0.2, -0.3, 0.1, 0.05])
    S2 = np.array([0.1, 0.1, -0.2, 0.05, 0.01])
    n = np.array([100, 100, 100, 50, 100])
    ex = np.ones(5, bool)
    r = SR.box_check(S, S2, n, np.zeros(5, bool), ex)
    assert r["plateau"] and r["good"] == 4
    r = SR.box_check(S, S2, np.array([100, 100, 50, 50, 100]), np.zeros(5, bool), ex)
    assert not r["plateau"] and r["label"] == "spike between coarse points"      # 3 of 5 < 2/3
    r = SR.box_check(S, -S2, n, np.zeros(5, bool), ex)
    assert not r["plateau"] and "median S2" in r["why"]
    lat = _grid([5])
    best = SR.box_best(lat, np.array([0.1, 0.5, 0.6, 0.55, 0.1]), np.full(5, 100), ex)
    assert best == 2


# ------------------------------------------------------------------ nulls (4.3)
def test_flip_b_one_coin_per_close_shared_by_coins_and_systems(world):
    ctx = world
    ft = SR.FlipTable(3, ctx.start, ctx.end)
    for q in range(0, 300, 37):
        t = ctx.start + q * SR.GRID_MS
        want = hashlib.sha256(f"hunt-r2-null|b|3|{t}".encode()).digest()[0] % 2 == 0
        assert SR.flip_heads(3, t) == want and ft.reverse[q] == (not want)
    assert 0.4 < ft.reverse.mean() < 0.6
    tf = "1h"
    cm = H.series("ETHUSDT", tf).bars.close_ms
    j0 = np.flatnonzero((cm >= ctx.start) & (cm < ctx.end))[:50]
    jb = np.flatnonzero((H.series("AAAUSDT", tf).bars.close_ms >= ctx.start))[:50]
    sig = SR.canon_sig(tf, np.r_[np.full(50, 1), np.full(50, 2)], np.r_[j0, jb], np.ones(100))
    out, cnt = ft.apply(ctx, sig)
    side_by_close = {}
    for k, j, s in zip(out["k"], out["j"], out["side"]):
        c = int(H.series(SYMS[k], tf).bars.close_ms[j])
        assert side_by_close.setdefault(c, s) == s          # one coin per close, shared across coins
        assert s == (-1 if ft.reverse[(c - ctx.start) // SR.GRID_MS] else 1)
    assert cnt["events"] == 100
    out2, _ = SR.FlipTable(3, ctx.start, ctx.end).apply(ctx, sig)
    assert all(np.array_equal(out[x], out2[x]) for x in ("k", "j", "side"))   # deterministic


def test_a_shift_formula_range_and_redraws(world, monkeypatch):
    days = [SR.delta_days(i) for i in range(1, 201)]
    assert all(d % 7 == 0 and 63 <= d <= 1036 for d in days)
    u = int.from_bytes(hashlib.sha256(b"hunt-r2-null|a|5|2").digest()[:8], "little")
    assert SR.delta_days(5, 2) == 7 * (9 + u % 140)
    assert len(set(days)) > 100
    assert SR.redraw_needed({"events": 100, "dropped": 10}) == (0.10, False)       # "more than 10%"
    assert SR.redraw_needed({"events": 100, "dropped": 11})[1]
    # 4.3: the share is the replicate's own (every system its search ran, all coins); a replicate above 10% is
    # replayed whole at the next draw, the others are not
    ctx = world
    calls = []
    drops = {(5, 0): 50, (5, 1): 12, (5, 2): 2, (6, 0): 3}

    def fake_units(null, todo, order, procs, parts):
        calls.append(dict(todo))
        out = {}
        for i, j in todo.items():
            out[i] = {nm: {"name": nm, "family": L.family_of(nm), "anchor_tf": "1h", "anchor_gate": "G1",
                           "counts": {"events": 50, "dropped": drops[(i, j)] // 2, "collided": 0, "flipped": 0},
                           "runs": 1, "S": np.zeros(len(L.coarse(nm))), "n": np.zeros(len(L.coarse(nm))),
                           "bust": np.zeros(len(L.coarse(nm)), bool), "exists": np.ones(len(L.coarse(nm)), bool),
                           "default_eff": np.zeros(len(L.coarse(nm)), bool), "anchor": 0, "stage0": []}
                     for nm in order}
        return out
    monkeypatch.setattr(SR, "_null_units", fake_units)
    monkeypatch.setitem(SR._RUN, "ctx", ctx)
    res = SR.null_replicates("a", [5, 6], ["E1", "TSMOM7"], 1, None)
    assert calls == [{5: 0, 6: 0}, {5: 1}, {5: 2}]
    sh = res[5]["shift"]
    assert sh["j"] == 2 and sh["days"] == SR.delta_days(5, 2) and [d["j"] for d in sh["draws"]] == [0, 1, 2]
    assert sh["draws"][0]["share_dropped"] == pytest.approx(0.5) and res[6]["shift"]["j"] == 0
    assert SR.null_part("/p", "a", 5, "E1", 2).endswith("null_a/005_j2/E1.json")
    assert SR.null_part("/p", "a", 5, "E1", 0).endswith("null_a/005/E1.json")


def test_a_shift_whole_weeks_per_coin_wrap(world):
    ctx = world
    tf = "15m"
    k = 1
    sp = ctx.span(tf, k)
    assert sp["L"] % SR.WEEK_MS == 0 and sp["L"] > 0 and sp["s"] >= ctx.start and sp["e"] < ctx.end
    cm = sp["cm"]
    j = np.flatnonzero(sp["land"])[::7]
    side = np.where(np.arange(len(j)) % 2 == 0, 1, -1)
    sig = SR.canon_sig(tf, np.full(len(j), k), j, side)
    d = SR.delta_days(11)
    out, cnt = SR.shift_sig(ctx, sig, d * DAY)
    assert cnt["events"] == len(j) and len(out["j"]) <= len(j) - cnt["dropped"]
    tn = cm[out["j"]]
    assert ((tn - sp["s"]) >= 0).all() and ((tn - sp["s"]) < sp["L"]).all()
    assert sp["land"][out["j"]].all()                       # landing bars valid
    # time of day and weekday kept: every event moved by a whole number of weeks
    orig = {int(t): s for t, s in zip(cm[j], side)}
    for t, s in zip(tn, out["side"]):
        cands = [o for o in orig if (int(t) - o) % SR.WEEK_MS == 0 and orig[o] == s]
        assert cands
    # the mapping: s + ((t - s + D) mod L)
    t0 = int(cm[j[0]])
    want = sp["s"] + (t0 - sp["s"] + d * DAY) % sp["L"]
    one = SR.canon_sig(tf, [k], [j[0]], [1])
    o1, c1 = SR.shift_sig(ctx, one, d * DAY)
    if c1["dropped"] == 0:
        assert int(cm[o1["j"][0]]) == want
    # an invalid landing bar is dropped and counted
    sp2 = dict(sp)
    sp2["land"] = np.zeros_like(sp["land"])
    ctx._spans[(tf, k)] = sp2
    try:
        o2, c2 = SR.shift_sig(ctx, sig, d * DAY)
        assert len(o2["j"]) == 0 and c2["dropped"] == len(j)
    finally:
        ctx._spans[(tf, k)] = sp
    # collisions (W 3.2): two events landing on one bar: same side -> one event, opposite sides -> none
    jv = next(int(x) for x in j if SR.landing(sp, cm[[x]], d * DAY)[1][0])
    two = SR.canon_sig(tf, [k, k], [jv, jv], [1, 1])
    o3, c3 = SR.shift_sig(ctx, two, d * DAY)
    assert len(o3["j"]) == 1 and c3["collided"] == 1 and c3["dropped"] == 0
    opp = SR.canon_sig(tf, [k, k], [jv, jv], [1, -1])
    o4, c4 = SR.shift_sig(ctx, opp, d * DAY)
    assert len(o4["j"]) == 0 and c4["collided"] == 2


def test_near_zero_listing(world):
    ctx = world
    tf, k = "1h", 2
    sp = ctx.span(tf, k)
    for days in (SR.delta_days(1), 7, sp["L"] // DAY - 7):
        near = SR.near_zero(ctx, days)
        eff = (days * DAY) % sp["L"]
        listed = SYMS[k] in near.get(tf, [])
        assert listed == (eff < 8 * SR.WEEK_MS or sp["L"] - eff < 8 * SR.WEEK_MS)


# ------------------------------------------------------------------ Stage 0 + A on the store, nulls replayed, determinism
def test_name_unit_real_and_null_replays_are_deterministic(world):
    ctx = world
    for name in ("N20_EMA9_CHOP", "E1"):
        a = SR.name_unit(ctx, name, real=True)
        b = SR.name_unit(ctx, name, real=True)
        assert a["anchor"] == b["anchor"] and np.array_equal(a["S"], b["S"], equal_nan=True)
        assert np.array_equal(a["S2"], b["S2"], equal_nan=True) and a["lnM"] == b["lnM"]
        assert len(a["stage0"]) == 2 * len(L.tfs_of(name)) and all(len(r["lnM"]) == len(ctx.mk.months)
                                                                   for r in a["stage0"])
        assert a["S"][L.coarse(name).default] == a["stage0"][a["anchor"]]["S"]        # the default run reused
        nb = SR.name_unit(ctx, name, transform=SR.FlipTable(2, ctx.start, ctx.end))
        nb2 = SR.name_unit(ctx, name, transform=SR.FlipTable(2, ctx.start, ctx.end))
        assert np.array_equal(nb["S"], nb2["S"], equal_nan=True) and nb["anchor"] == nb2["anchor"]
        assert nb["counts"]["events"] > 0 and "S2" not in nb
        na = SR.name_unit(ctx, name, transform=SR.ShiftA(2, SR.delta_days(2)))
        na2 = SR.name_unit(ctx, name, transform=SR.ShiftA(2, SR.delta_days(2)))
        assert np.array_equal(na["S"], na2["S"], equal_nan=True)
        # the replicate's own Stage 0: its anchor comes from the null's default runs
        rows = na["stage0"]
        assert na["anchor"] == SR.anchor_slot(rows)


def test_null_stage0_is_replayed_not_reused(world, monkeypatch):
    """4.3: a replicate chooses its own anchors (a shortcut of Stage 0 is not allowed)."""
    ctx = world
    real = SR.name_unit(ctx, "E1", real=False)
    calls = []
    orig = SR.anchor_slot

    def spy(rows):
        calls.append([r["S"] for r in rows])
        return orig(rows)
    monkeypatch.setattr(SR, "anchor_slot", spy)
    nb = SR.name_unit(ctx, "E1", transform=SR.FlipTable(9, ctx.start, ctx.end))
    assert len(calls) == 1 and len(calls[0]) == 8
    assert [r["S"] for r in nb["stage0"]] == calls[0] != [r["S"] for r in real["stage0"]]


def test_default_in_effect_shares_the_default_run(world, monkeypatch):
    ctx = world
    name = "TSMOM7"
    lat = L.coarse(name)
    orig = SR.store_sig

    def same(c, units, ci, gate, tf):                     # every combo gives the default's events
        return orig(c, units, lat.default, gate, tf)
    og = SR.gated_hash
    monkeypatch.setattr(SR, "store_sig", same)
    monkeypatch.setattr(SR, "gated_hash", lambda units, ci, gate: og(units, lat.default, gate))
    u = SR.name_unit(ctx, name, real=True)
    assert u["default_eff"].sum() == len(lat) - 1 and not u["default_eff"][lat.default]
    assert np.all(u["S"] == u["S"][lat.default])
    st = SR.stage_a(lat, u["S"], u["n"], u["bust"], u["exists"], S2=u["S2"], default_eff=u["default_eff"])
    assert not st["candidate"] and (st["peak"] == -1 or st["peak_is"] in ("the default", "a default in effect"))


def test_default_in_effect_is_the_gated_list_before_the_atr_and_fill_filters(world):
    """3.6: identity = the gated event list (coin, bar, side); a list that differs only at a bar without ATR14 or a fill
    bar is another list."""
    ctx = world
    name, tf, gate = "E1", "1h", "NONE"
    lat = L.coarse(name)
    units = SR.load_units(ctx.root, ctx.part, name, tf, ctx.syms)
    g0 = SR.gated_hash(units, lat.default, gate)
    assert g0 == SR.gated_hash(units, lat.default, gate)
    u0 = units[0]
    j, side, g1 = u0.events(lat.default)
    bad = np.flatnonzero(~ctx.ok(tf, 0))                    # a bar the engine never sees (no ATR14 / no fill)
    assert len(bad)

    class Fake:
        def __init__(self, base, extra):
            self.base, self.extra = base, extra

        def events(self, ci):
            jj, ss, gg = self.base.events(ci)
            return (np.r_[jj, self.extra].astype(np.int32), np.r_[ss, 1].astype(np.int8),
                    np.r_[gg, 1].astype(np.int8))
    fake = [Fake(units[0], int(bad[-1]))] + list(units[1:])
    assert SR.gated_hash(fake, lat.default, gate) != g0       # another gated list
    s1 = SR.store_sig(ctx, fake, lat.default, gate, tf)
    s0 = SR.store_sig(ctx, units, lat.default, gate, tf)
    assert SR.sig_hash(s1) == SR.sig_hash(s0)                 # the same signal list after the filters


def test_search_and_results_do_not_depend_on_worker_count(world):
    assert world.root == _W["root"]
    order = [n for _f, n in L.names() if n in NAMES]
    one = H.pmap(_unit_task, [(n, 4) for n in order], 1)
    two = H.pmap(_unit_task, [(n, 4) for n in order], 2)
    for a, b in zip(one, two):
        assert np.array_equal(a["S"], b["S"], equal_nan=True) and a["anchor"] == b["anchor"]
    res = SR.search({u["name"]: u for u in one}, order, real=False, min_pos=5)
    assert set(res["per_name"]) == set(order)
    assert [c["P"] for c in res["ranked"]] == sorted((c["P"] for c in res["ranked"]), reverse=True)


def _unit_task(task):
    name, i = task
    ctx = SR.Ctx(_W["mk"], _W["root"])
    return SR.name_unit(ctx, name, transform=SR.FlipTable(i, ctx.start, ctx.end))


# ------------------------------------------------------------------ CSCV (6)
def test_cscv_splits():
    sp = PT.splits()
    assert sp.shape == (924, 36) and (sp.sum(axis=1) == 18).all()
    blocks = sp.reshape(924, 12, 3)
    assert ((blocks.all(axis=2)) | (~blocks.any(axis=2))).all()
    assert len({row.tobytes() for row in sp}) == 924
    assert PT.omega(5.0, np.array([1.0, 5.0, 9.0])) == pytest.approx(2.0 / 4.0)


def _fake_unit(name, rng, anchor, edge=0.0):
    lat = L.coarse(name)
    npt = len(lat)
    rows = []
    for tf in L.tfs_of(name):
        for g in ("G1", "NONE"):
            rows.append({"tf": tf, "gate": g, "lnM": list(rng.normal(0.0, 0.02, 36)), "pos_month": [5] * 36,
                         "bust_month": -1})
    rows[anchor]["lnM"] = list(rng.normal(0.01, 0.02, 36))
    lnM = [list(rng.normal(edge, 0.02, 36)) for _ in range(npt)]
    return {"name": name, "family": lat.family, "anchor": anchor, "anchor_tf": rows[anchor]["tf"],
            "anchor_gate": rows[anchor]["gate"], "stage0": rows, "exists": np.ones(npt, bool),
            "default_eff": np.zeros(npt, bool), "lnM": lnM, "lnM2": [list(np.asarray(x) - 0.001) for x in lnM],
            "pos_month": [[5] * 36] * npt, "bust_month": np.full(npt, -1)}


def _fake_slots(name, u, rng, edge=0.0):
    """Stage A at every slot of a hand-made unit (the real anchor's slot is the unit itself)."""
    lat = L.coarse(name)
    out = {u["anchor"]: u}
    for a in range(len(u["stage0"])):
        if a != u["anchor"]:
            lnM = [list(rng.normal(edge, 0.02, 36)) for _ in range(len(lat))]
            out[a] = dict(u, anchor=a, lnM=lnM, lnM2=[list(np.asarray(x) - 0.001) for x in lnM])
    return out


def test_cscv_on_hand_made_units():
    rng = np.random.default_rng(4)
    order = ["E1", "N20_EMA9_CHOP", "F3_BOS"]
    units = {n: _fake_unit(n, rng, 5) for n in order}
    slots = {n: _fake_slots(n, units[n], rng) for n in order}
    a = PT.cscv(units, order, slots)
    b = PT.cscv(units, order, slots)
    assert a["pbo"] == b["pbo"] and a["splits"] == 924
    assert a["systems"] == sum(len(u["stage0"]) + len(L.coarse(n)) - 1 for n, u in units.items())
    assert 0.0 <= a["pbo"] <= 1.0 and a["splits_with_candidate"] > 0 and not a["slots_missing"]
    assert sum(a["anchor_moved"].values()) > 0                # the IS anchor moves in some splits ...
    assert a["rank1_at_another_slot"] >= 0                     # ... and Stage A then runs at that IS anchor
    only = PT.cscv(units, order)                               # without the other slots: those splits are listed
    assert sum(only["slots_missing"].values()) == sum(only["anchor_moved"].values()) > 0
    # a lattice with a strong real edge on every month at its anchor: the IS-best is also good OOS (PBO low)
    units2 = {n: _fake_unit(n, np.random.default_rng(9), 5) for n in order}
    lat = L.coarse("E1")
    for i in range(len(lat)):
        units2["E1"]["lnM"][i] = list(np.full(36, 0.05) + np.random.default_rng(i).normal(0, 0.001, 36))
    units2["E1"]["lnM2"] = [list(np.asarray(x) - 0.001) for x in units2["E1"]["lnM"]]
    units2["E1"]["stage0"][5]["lnM"] = list(np.full(36, 0.04))
    c = PT.cscv(units2, order, {n: _fake_slots(n, units2[n], np.random.default_rng(3)) for n in order})
    assert c["pbo"] is not None and c["pbo"] < 0.2


def test_cscv_replay_rechooses_the_anchor_in_sample():
    """6: an IS half whose best default slot is another one runs Stage A at that slot (not at the full-period
    anchor)."""
    rng = np.random.default_rng(12)
    order = ["E1"]
    u = _fake_unit("E1", rng, 5)
    lnm = np.full(36, -0.01)
    lnm[:18] = 0.03                                            # slot 2's default is best in the first half only
    u["stage0"][2]["lnM"] = list(lnm)
    u["stage0"][5]["lnM"] = list(np.r_[np.full(18, 0.0), np.full(18, 0.05)])
    slots = _fake_slots("E1", u, rng)
    IS = np.zeros((1, 36), bool)
    IS[0, :18] = True
    prep, _ = PT._prep({"E1": u}, order, IS, {"E1": slots})
    rp = PT.replay(prep, order, 0, 3)
    assert rp["per"]["E1"]["slot"] == 2 and rp["moved"] == ["E1"] and not rp["missing"]


# ------------------------------------------------------------------ the engine pin (2, 11): a temporary tree only
def test_engine_pin_check_on_a_temporary_tree(tmp_path):
    files = {"research/hunt/hunt.py": b"engine", "research/hunt/entries_wide.py": b"entries",
             "paperbot/dash/tools/regime5y.py": b"labels"}
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    sha = {rel: hashlib.sha256(d).hexdigest() for rel, d in files.items()}
    pin = tmp_path / PN.R1_PIN
    lines = [f"{'0' * 64}  research/hunt/hunt.py"] + [f"{sha[r]}  {r}" for r in files] + \
        [f"{'f' * 64}  research/hunt/out/wide/never_opened.json"]
    pin.write_text("\n".join(lines) + "\n")
    r1 = PN.round1_lines(str(tmp_path))
    assert r1["research/hunt/hunt.py"] == sha["research/hunt/hunt.py"]                # the last line counts
    assert not any(p.startswith("research/hunt/out/") for p in r1)
    assert PN.engine_problems(list(files), root=str(tmp_path)) == []
    assert PN.engine_problems(list(files), r2_lines=dict(sha), root=str(tmp_path)) == []
    bad = PN.engine_problems(list(files) + ["research/fullgrid/memo.py"], r2_lines={**sha, files and
                                                                                     "research/hunt/hunt.py": "x"},
                             root=str(tmp_path))
    assert any("not pinned by round 1: research/fullgrid/memo.py" in b for b in bad)
    assert any("round 2's pin line differs" in b and "hunt.py" in b for b in bad)
    (tmp_path / "research/hunt/hunt.py").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed since round 1's pin: research/hunt/hunt.py"):
        PN.check_engine(list(files), root=str(tmp_path))


# ------------------------------------------------------------------ the whole select step on synthetic bars
def test_select_step_end_to_end_and_resume(world, tmp_path):
    ctx = world
    order = [n for _f, n in L.names() if n in NAMES]
    parts = str(tmp_path / "parts")
    res = SR.select_run(ctx.mk, ctx.root, parts, 2, names_order=order, n_rep=3)
    assert set(res["real_units"]) == set(order)
    for nm in order:
        u = res["real_units"][nm]
        assert (u["anchor_tf"], u["anchor_gate"]) == (u["stage0"][u["anchor"]]["tf"], u["stage0"][u["anchor"]]["gate"])
    for null in ("a", "b"):
        assert sorted(res["nulls"][null]) == [1, 2, 3]
        for v in res["nulls"][null].values():
            assert v["P"] == sorted(v["P"], reverse=True) and v["runs"] > 0
    assert sum(v["counts"]["flipped"] for v in res["nulls"]["b"].values()) > 0
    assert sum(v["counts"]["events"] for v in res["nulls"]["a"].values()) > 0
    assert len(res["hurdle"]["steps"]) == len(res["real"]["ranked"])
    assert set(res["box"]["boxes"]) == {c["name"] for c, s in zip(res["real"]["ranked"], res["hurdle"]["steps"])
                                        if s["taken"]}
    pub, priv = SR.picks_doc(order, res["real_units"], res["real"], res["hurdle"], res["box"], res["nulls"])
    assert [r["name"] for r in pub["names"]] == order and SR.d11_problems(pub) == []
    f3 = next(r for r in pub["names"] if r["name"] == "F3_BOS")
    assert "P_c_peak" not in f3 and any(r["name"] == "F3_BOS" for r in priv["rows"])
    e1 = next(r for r in pub["names"] if r["name"] == "E1")
    assert "P_c_default" in e1 and e1["default"] == L.default_combo("E1")
    assert "old six not blind" in e1["labels"]
    json.dumps(pub)
    res2 = SR.select_run(ctx.mk, ctx.root, parts, 1, names_order=order, n_rep=3)        # resumes from the parts
    for nm in order:
        assert np.array_equal(res2["real_units"][nm]["S"], res["real_units"][nm]["S"], equal_nan=True)
    assert res2["nulls"]["a"] == res["nulls"]["a"] or all(
        res2["nulls"]["a"][i]["P"] == res["nulls"]["a"][i]["P"] for i in (1, 2, 3))


def test_box_stage_runs_the_box_at_the_anchor(world):
    ctx = world
    real = SR.name_unit(ctx, "E1", real=True)
    lat = L.coarse("E1")
    peak = int(np.flatnonzero(np.arange(len(lat)) != lat.default)[0])
    out = SR.box_stage(ctx, {"E1": real}, [{"name": "E1", "peak": peak}], [{"taken": True}], 1)
    b = out["boxes"]["E1"]
    bx = L.box("E1", lat.combos[peak])
    assert b["points"] == int(b["exists"].sum()) <= len(bx) and b["centre"] == bx.index(lat.combos[peak])
    assert out["picks"] == (["E1"] if b["plateau"] else [])
    S_centre = SR.run_sig(ctx.mk, SR.store_sig(ctx, SR.load_units(ctx.root, "coarse", "E1", real["anchor_tf"], ctx.syms),
                                               peak, real["anchor_gate"], real["anchor_tf"]))["S"]
    assert b["S"][b["centre"]] == S_centre                  # the centre is the coarse peak's own run


def test_d11_writer_refuses_a_float_under_a_deepseek_row():
    ok = {"names": [{"family": "F3", "name": "X", "rank": 1, "peak": {"swing_k": 2, "disp_atr": 2.4},
                     "default": {"disp_atr": 1.2}, "box": {"box_best": {"numbers": {"disp_atr": 1.5}}}}]}
    assert SR.d11_problems(ok) == []                       # numbers (combos) are public, also floats
    bad = SR.d11_problems({"names": [{"family": "F3", "name": "X", "box": {"median_S": 0.1}}]})
    assert bad == ["picks.names[0].box.median_S"]
    assert SR.d11_problems({"names": [{"family": "F2", "name": "Y", "P_c_peak": 0.1}]}) == []


# ------------------------------------------------------------------ round 2's own pin (11): a temporary tree only
def _r2_tree(tmp_path):
    files = {PN.DESIGN: b"design", PN.COUNTS: b"{}", PN.BENCH: b"{}", "research/hunt_r2/lattice.py": b"code",
             "tests/test_hunt_r2_core.py": b"tests", "research/hunt/hunt.py": b"engine"}
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    sha = {rel: hashlib.sha256(d).hexdigest() for rel, d in files.items()}
    (tmp_path / PN.R1_PIN).write_text(f"{sha['research/hunt/hunt.py']}  research/hunt/hunt.py\n")
    order = [PN.DESIGN] + [r for r in files if r != PN.DESIGN]
    (tmp_path / PN.R2_PIN).write_text("".join(f"{sha[r]}  {r}\n" for r in order))
    return sha


def test_round_two_pin_check_and_refusals(tmp_path):
    root = str(tmp_path)
    eng = ["research/hunt/hunt.py"]
    sha = _r2_tree(tmp_path)
    assert PN.check_pin("select", root, eng)["files"] == 6
    lines = PN.pinlist(root, eng)
    assert f"{sha['research/hunt/hunt.py']}  research/hunt/hunt.py" in lines and \
        f"{sha['research/hunt_r2/lattice.py']}  research/hunt_r2/lattice.py" in lines
    with pytest.raises(RuntimeError, match="not pinned"):
        PN.check_pin("test", root, eng)                     # test needs the picks line
    (tmp_path / "research/hunt_r2/out").mkdir(parents=True)
    (tmp_path / PN.PICKS).write_text("{}")
    PN.append_line(PN.PICKS, root)
    assert PN.check_pin("test", root, eng)
    with pytest.raises(RuntimeError, match="already pinned"):
        PN.check_pin("select", root, eng)
    (tmp_path / "research/hunt_r2/new.py").write_text("x")
    with pytest.raises(RuntimeError, match="not pinned research/hunt_r2/new.py"):
        PN.check_pin("test", root, eng)
    os.remove(tmp_path / "research/hunt_r2/new.py")
    (tmp_path / "research/hunt/hunt.py").write_bytes(b"engine2")
    with pytest.raises(RuntimeError, match="changed"):
        PN.check_pin("test", root, eng)
    sha2 = _r2_tree(tmp_path)
    txt = (tmp_path / PN.R2_PIN).read_text().splitlines()
    (tmp_path / PN.R2_PIN).write_text("\n".join(txt[1:] + txt[:1]) + "\n")
    with pytest.raises(RuntimeError, match="first line is not the design hash"):
        PN.check_pin("select", root, eng)
    (tmp_path / PN.R2_PIN).write_text("\n".join(t for t in txt if PN.BENCH not in t) + "\n")
    with pytest.raises(RuntimeError, match="bench_r2.json"):
        PN.check_pin("select", root, eng)
    assert sha2 == sha
