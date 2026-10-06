"""The shadow league's vendored zone-flip detector and exit simulation against the study's own code (lib_zoneflip.py,
the file that produced the 5-year result): same text, same signals, same stops and targets bit for bit, same returns.
Plus hand-made bars with one known answer, and the look-ahead tests (no signal at or before bar t reads a later bar)."""

import ast
import hashlib
import inspect
import json
import os

import numpy as np
import pandas as pd
import pytest

import shadowleague_original as SO
from shadowleague_world import hand_made, load_fixture, series_arrays
from paperbot.shadowleague import sim as SM
from paperbot.shadowleague import zoneflip as ZF

ROOT = SO.ROOT
MANIFEST = os.path.join(ROOT, "paperbot", "shadowleague", "vendor_manifest.json")
needs_original = pytest.mark.skipif(not SO.available(), reason="the study's environment (locked engine, library) cannot be loaded here")


def man():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def _segments(path: str, names) -> dict:
    src = open(path, encoding="utf-8").read()
    lines = src.split("\n")
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            out[node.name] = ("\n".join(lines[node.lineno - 1:node.end_lineno]), node)
    return out


def _module_path(mod) -> str:
    return inspect.getsourcefile(mod)


# ------------------------------------------------------------------------------------------------ the manifest
def test_manifest_hashes_match_the_files():
    m = man()
    src = {s["id"]: s for s in m["sources"]}
    assert SO.sha256_of(SO.ORIGINAL) == src["lib_zoneflip"]["sha256"] == SO.ORIGINAL_SHA256
    assert src["lib_zoneflip"]["prereg_sha256"] == SO.PREREG_SHA256
    for key, rel in (("lib_reel5m", "research/reel5m/lib_reel5m.py"),
                     ("fg_indicators", "third_party/sweep/harness/vendor/fg_indicators.py"),
                     ("sweep_lib", "third_party/sweep/harness/sweep_lib.py"),
                     ("search_owners_book", "research/search/search.py")):
        assert SO.sha256_of(os.path.join(ROOT, rel)) == src[key]["sha256"], key


def test_every_verbatim_function_has_the_originals_exact_text():
    m = {s["id"]: s for s in man()["sources"]}
    orig_names = set(m["lib_zoneflip"]["copied"]["paperbot/shadowleague/zoneflip.py"]["verbatim_functions"])
    orig_names |= set(m["lib_zoneflip"]["copied"]["paperbot/shadowleague/sim.py"]["verbatim_functions"])
    orig = _segments(SO.ORIGINAL, orig_names | {"simulate", "setups"})
    reel = _segments(SO.REEL_LIB, {"exit_trade"})
    for mod, rel in ((ZF, "paperbot/shadowleague/zoneflip.py"), (SM, "paperbot/shadowleague/sim.py")):
        want = m["lib_zoneflip"]["copied"][rel]["verbatim_functions"]
        mine = _segments(_module_path(mod), set(want))
        for name, sha in want.items():
            assert hashlib.sha256(orig[name][0].encode()).hexdigest() == sha, f"manifest hash of {name}"
            assert mine[name][0] == orig[name][0], f"{rel}:{name} differs from the original's text"
    mine = _segments(_module_path(SM), {"exit_trade"})
    assert mine["exit_trade"][0] == reel["exit_trade"][0]
    assert hashlib.sha256(reel["exit_trade"][0].encode()).hexdigest() == m["lib_reel5m"]["copied"]["paperbot/shadowleague/sim.py"][
        "verbatim_functions"]["exit_trade"]


def test_simulate_and_setups_differ_from_the_original_only_as_listed():
    orig = _segments(SO.ORIGINAL, {"simulate", "setups"})

    class Sub(ast.NodeTransformer):
        def visit_Attribute(self, node):                # R.exit_trade -> exit_trade
            self.generic_visit(node)
            if isinstance(node.value, ast.Name) and node.value.id == "R" and node.attr == "exit_trade":
                return ast.copy_location(ast.Name(id="exit_trade", ctx=ast.Load()), node)
            return node
    want = ast.dump(Sub().visit(orig["simulate"][1]))
    assert ast.dump(_segments(_module_path(SM), {"simulate"})["simulate"][1]) == want
    # setups: the same function with the optional b_min (default None) added: remove it and the dumps are equal
    mine = _segments(_module_path(ZF), {"setups"})["setups"][1]

    class Strip(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            node.args.args = [a for a in node.args.args if a.arg != "b_min"]
            node.args.defaults = []
            self.generic_visit(node)
            return node

        def visit_If(self, node):
            self.generic_visit(node)
            if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == "b_min":
                return None
            return node
    assert ast.dump(Strip().visit(mine)) == ast.dump(orig["setups"][1])


def test_the_preregistered_numbers_are_the_originals():
    tree = ast.parse(open(SO.ORIGINAL, encoding="utf-8").read())
    consts = {t.targets[0].id: ast.literal_eval(t.value) for t in tree.body
              if isinstance(t, ast.Assign) and isinstance(t.targets[0], ast.Name) and t.targets[0].id.isupper()
              and isinstance(t.value, (ast.Constant, ast.Tuple))}
    for name in m_names():
        assert getattr(ZF, name) == consts[name], name
    assert (ZF.VP_BARS, ZF.N_BUCKETS, ZF.PCTL, ZF.BREAK_ATR, ZF.MIN_TOUCHES, ZF.TOUCH_GAP, ZF.RETEST_BARS, ZF.STOP_BUF_ATR,
            ZF.MAX_STOP_ATR, ZF.MIN_RR, ZF.MAX_HOLD, ZF.ATR_LEN) == (200, 50, 80.0, 0.25, 3, 3, 20, 0.25, 3.0, 2.0, 48, 14)
    assert SM.MAX_HOLD == ZF.MAX_HOLD == 48


def m_names():
    return man()["sources"][0]["copied"]["paperbot/shadowleague/zoneflip.py"]["verbatim_constants"]


# ------------------------------------------------------------------------------------------------ ATR14
def test_atr14_is_pandas_ewm_bit_for_bit():
    rng = np.random.default_rng(4)
    for trial in range(40):
        n = int(rng.integers(20, 2500))
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        o = np.r_[c[0], c[:-1]] * (1 + rng.normal(0, 0.002, n))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
        if trial % 9 == 0:
            h = l = c = np.full(n, 5.0)                       # a flat series stays flat
        df = pd.DataFrame({"high": h, "low": l, "close": c})
        tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(),
                        (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
        ref = tr.ewm(alpha=1.0 / 14, adjust=False, min_periods=14).mean().to_numpy(float)
        assert np.array_equal(ZF.atr14(h, l, c), ref, equal_nan=True)


@needs_original
def test_atr14_is_the_locked_fg_indicators_atr():
    fg = SO.load_original().env()["fg"]
    for seed in (10, 1, 24):
        a = load_fixture(seed)
        df = pd.DataFrame({"high": a["h"], "low": a["l"], "close": a["c"]})
        assert np.array_equal(ZF.atr14(a["h"], a["l"], a["c"]), fg.atr(df, 14).to_numpy(float), equal_nan=True)


def test_atr_next_continues_the_series_exactly():
    a = load_fixture(10)
    full = ZF.atr14(a["h"], a["l"], a["c"])
    w, got = full[1999], []
    for i in range(2000, 2600):
        w = ZF.atr_next(w, a["c"][i - 1], a["h"][i], a["l"][i])
        got.append(w)
    assert np.array_equal(np.array(got), full[2000:2600])


# ------------------------------------------------------------------------------------------------ parity on a fixture
def _same(a, b, path="") -> None:
    """Exactly equal: floats by bits (NaN == NaN), arrays element by element, dicts by keys."""
    if isinstance(a, dict):
        assert isinstance(b, dict) and a.keys() == b.keys(), (path, a.keys() ^ b.keys())
        for k in a:
            _same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            _same(x, y, f"{path}[{i}]")
    elif isinstance(a, np.ndarray):
        assert np.array_equal(a, np.asarray(b), equal_nan=a.dtype.kind == "f"), path
    elif isinstance(a, float) or isinstance(b, float):
        assert (a == b) or (np.isnan(a) and np.isnan(b)), (path, a, b)
    else:
        assert a == b, (path, a, b)


def _frame(a: dict, tf: str) -> pd.DataFrame:
    n = len(a["o"])
    ts = pd.date_range("2022-01-01", periods=n, freq=f"{SM.TF_MINUTES[tf]}min", tz="UTC")
    df = pd.DataFrame({"ts": ts, "open": a["o"], "high": a["h"], "low": a["l"], "close": a["c"], "volume": a["v"]})
    df.attrs["tf"] = tf
    return df


def _compare_everything(a: dict, tf: str, lo: int) -> int:
    """Signals, setups, same-bar choice and the simulated trades of both variants against the original. Returns the
    number of trades compared."""
    orig = SO.load_original()
    L = orig.env()["L"]
    S = orig.signals(_frame(a, tf))
    N = ZF.signals_from_arrays(a["o"], a["h"], a["l"], a["c"], a["v"])
    _same(S["atr"], N["atr"])
    _same(S["setups"], N["setups"])
    _same(S["sigs"], N["sigs"])
    _same(S["chosen"], N["chosen"])
    cost_o, cost_n = L._cost(tf, 48), SM.cost_for(tf)
    assert (cost_o.fee_side, cost_o.slip_side, cost_o.funding_8h, cost_o.bar_minutes, cost_o.max_hold) == (
        cost_n.fee_side, cost_n.slip_side, cost_n.funding_8h, cost_n.bar_minutes, cost_n.max_hold)
    total = 0
    for var in ZF.VARIANTS:
        tr_o, cnt_o = orig.simulate(S["chosen"][var], a["o"], a["h"], a["l"], a["c"], cost_o, lo, len(a["c"]) - 1)
        tr_n, cnt_n = SM.simulate(N["chosen"][var], a["o"], a["h"], a["l"], a["c"], cost_n, lo, len(a["c"]) - 1)
        assert cnt_o == cnt_n
        _same(tr_o, tr_n)
        for x, y in zip(tr_o, tr_n):                              # the returns, to 1e-12 (they are in fact equal)
            for k in ("net", "gross", "gross_raw", "fee", "funding", "mae", "mfe"):
                assert abs(x[k] - y[k]) <= 1e-12, k
        total += len(tr_o)
    return total


@needs_original
@pytest.mark.parametrize("seed,tf", [(10, "1h"), (1, "15m"), (24, "4h")])
def test_the_vendored_detector_equals_the_original_on_the_committed_fixture(seed, tf):
    n = _compare_everything(load_fixture(seed), tf, lo=300)
    assert n > 0                                                   # the comparison saw real trades


@needs_original
def test_exit_fixed_batch_equals_exit_trade_bit_for_bit():
    a = load_fixture(10)
    o, h, l, c = a["o"], a["h"], a["l"], a["c"]
    rng = np.random.default_rng(3)
    m = 1500
    e = rng.integers(400, len(c) - 1, m)                           # some trades run into the end of the series
    side = rng.choice([-1, 1], m)
    entry = o[e] * (1 + side * 0.0002)
    sld, tpd = rng.uniform(0.002, 0.05, m), rng.uniform(0.004, 0.12, m)
    stop, tgt = entry * (1 - side * sld), entry * (1 + side * tpd)
    for tf in ("15m", "4h"):
        cost = SM.cost_for(tf)
        vec = SM.exit_fixed_batch(side, e, entry, stop, tgt, o, h, l, c, cost, chunk=400)
        ref = np.array([SM.exit_trade(int(side[i]), int(e[i]), entry[i], stop[i], tgt[i], o, h, l, c, cost)["net"] for i in range(m)])
        assert np.array_equal(vec, ref)
        orig = SO.load_original().exit_fixed_batch(side, e, entry, stop, tgt, o, h, l, c, SO.load_original().env()["L"]._cost(tf, 48))
        assert np.array_equal(vec, orig)


# ------------------------------------------------------------------------------------------------ parity on real bars
PRE = os.path.join(ROOT, "data", "pre2021")


def _real(path: str, n: int, skip: int = 0) -> dict:
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True).iloc[skip:skip + n]
    return {"o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float), "l": df["low"].to_numpy(float),
            "c": df["close"].to_numpy(float), "v": df["volume"].to_numpy(float)}


REAL = [(os.path.join(PRE, "btcusd-1h.csv.gz"), "1h", 6000), (os.path.join(PRE, "ethusd-15m.csv.gz"), "15m", 5000),
        (os.path.join(PRE, "solusd-4h.csv.gz"), "4h", 3000),
        # other coins and later stretches than the three above (a reviewer's addition)
        (os.path.join(PRE, "dogeusd-1h.csv.gz"), "1h", 6000, 3000), (os.path.join(PRE, "ltcusd-15m.csv.gz"), "15m", 5000, 20000),
        (os.path.join(PRE, "bchusd-4h.csv.gz"), "4h", 3000, 0)]
_bd = os.environ.get("BINANCE_DIR")
if _bd:
    REAL.append((os.path.join(_bd, "bars", "btcusd-1h.csv.gz"), "1h", 4000))


@needs_original
@pytest.mark.parametrize("path,tf,n,skip", [(p + (0,) if len(p) == 3 else p) for p in REAL],
                         ids=[os.path.basename(p[0]) + (f"+{p[3]}" if len(p) > 3 and p[3] else "") for p in REAL])
def test_the_vendored_detector_equals_the_original_on_real_bars(path, tf, n, skip):
    if not os.path.exists(path):
        pytest.skip(f"{path} is not on this machine")
    a = _real(path, n, skip) if "pre2021" in path else None
    if a is None:                                                  # the study's own loader for the 2021-2026 bar files
        L = SO.load_original().env()["L"]
        df = L.read_ohlcv(path).iloc[:n]
        a = {"o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float), "l": df["low"].to_numpy(float),
             "c": df["close"].to_numpy(float), "v": df["volume"].to_numpy(float)}
    assert len(a["c"]) > 2000, "too few real bars for the comparison"
    n = _compare_everything(a, tf, lo=400)
    if tf == "1h":
        assert n > 0                                               # the comparison saw real trades


# ------------------------------------------------------------------------------------------------ hand-made bars
def _hand(**kw):
    a = hand_made(**kw)
    S = ZF.signals_from_arrays(a["o"], a["h"], a["l"], a["c"], a["v"])
    cost = SM.cost_for("1h")
    return a, S, cost


def test_hand_made_bars_give_exactly_one_short_with_the_expected_stop_and_target():
    a, S, cost = _hand()
    for var in ZF.VARIANTS:
        tr, _ = SM.simulate(S["chosen"][var], a["o"], a["h"], a["l"], a["c"], cost, ZF.VP_BARS + 1, 299)
        assert len(tr) == 1
        t = tr[0]
        assert (t["side"], t["break_idx"], t["signal_idx"], t["entry_idx"]) == (-1, 270, 273, 274)
        assert (t["zone_lo"], t["zone_hi"]) == (100.0, 101.0) and t["n_touch"] == 3
        assert t["stop_px"] == 101.0 + 0.25 * S["atr"][273]
        assert t["target_px"] == 94.5 and t["reason"] == "TP" and t["exit_idx"] == 276 and t["exit_px"] == 94.5
        assert t["entry_px"] == a["o"][274] * (1 - cost.slip_side)
        assert t["tp_dist"] == (t["entry_px"] - 94.5) / t["entry_px"]
    su = [s for s in S["setups"] if s["b"] == 270]
    assert len(su) == 1 and su[0]["touches"] == [150, 200, 240]    # the touch at 152 is 2 bars after 150: not counted
    # the member's own detector says the same
    recs = ZF.ZoneFlipDetector().detect(a["o"], a["h"], a["l"], a["c"], a["v"], S["atr"], 0)
    assert [(r["r"], r["side"], r["chosen"], r["skip"], r["touches"]) for r in recs] == [(273, -1, True, "", 3)]
    assert recs[0]["stop"] == 101.0 + 0.25 * S["atr"][273] and recs[0]["target"] == 94.5
    risk = recs[0]["stop"] - recs[0]["ref"]
    assert recs[0]["rr"] == pytest.approx((recs[0]["ref"] - 94.5) / risk)


def test_the_mirrored_long():
    a, S, cost = _hand(mirror=True)
    tr, _ = SM.simulate(S["chosen"]["ZF_MAIN"], a["o"], a["h"], a["l"], a["c"], cost, ZF.VP_BARS + 1, 299)
    assert len(tr) == 1
    t = tr[0]
    assert (t["side"], t["signal_idx"], t["entry_idx"]) == (1, 273, 274)
    assert (t["zone_lo"], t["zone_hi"]) == (104.0, 105.0) and t["n_touch"] == 3
    assert t["stop_px"] == 104.0 - 0.25 * S["atr"][273]
    assert t["target_px"] == 110.5 and t["reason"] == "TP" and t["exit_px"] == 110.5
    assert t["entry_px"] == a["o"][274] * (1 + cost.slip_side)


def test_no_trade_when_reward_to_risk_is_below_two():
    a, S, cost = _hand(target_zone=(96.0, 98.0))                   # the target zone is too close: reward 1.5, risk ~1.8
    for var in ZF.VARIANTS:
        tr, _ = SM.simulate(S["chosen"][var], a["o"], a["h"], a["l"], a["c"], cost, ZF.VP_BARS + 1, 299)
        assert not tr
    assert any(s["r"] == 273 and s["skip"] == "rr" for s in S["sigs"])
    recs = ZF.ZoneFlipDetector().detect(a["o"], a["h"], a["l"], a["c"], a["v"], S["atr"], 0)
    assert [(r["r"], r["skip"], r["chosen"]) for r in recs] == [(273, "rr", False)]
    assert recs[0]["rr"] < 2.0


def test_the_main_rule_needs_three_touches_and_a_real_break_and_retest():
    a, S, cost = _hand(touch_bars=(150, 152, 200))                 # two counted touches only
    assert not S["chosen"]["ZF_MAIN"] and len(S["chosen"]["ZF_CTRL"]) == 1
    assert ZF.ZoneFlipDetector().detect(a["o"], a["h"], a["l"], a["c"], a["v"], S["atr"], 0) == []
    a, S, cost = _hand(break_close=99.9)                           # a break smaller than 0.25 ATR is no break
    assert not [s for s in S["setups"] if s["b"] == 270]
    a, S, cost = _hand(retest_close=100.25)                        # the retest closes back inside the zone: break failed
    assert not S["chosen"]["ZF_MAIN"] and not S["chosen"]["ZF_CTRL"]


@needs_original
def test_the_hand_made_bars_are_the_studys_own():
    orig = SO.load_original()
    for kw in ({}, {"mirror": True}, {"target_zone": (96.0, 98.0)}, {"touch_bars": (150, 152, 200)}):
        a, df = hand_made(**kw), orig.handmade(**kw)
        for k, col in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
            assert np.array_equal(a[k], df[col].to_numpy(float)), (kw, k)


# ------------------------------------------------------------------------------------------------ no look-ahead
def _key(S: dict, cut: int) -> list:
    out = [(s["r"], s["b"], s["side"], s["zlo"], s["zhi"], s["n_touch"], tuple(s["touches"]), s["stop"],
            s["target"] if np.isfinite(s["target"]) else None, s["skip"]) for s in S["sigs"] if s["r"] < cut]
    for var in ZF.VARIANTS:
        out += [(var, r, x["b"], x["side"], x["stop"], x["target"]) for r, x in sorted(S["chosen"][var].items()) if r < cut]
    out += [(s["b"], s["side"], s["zlo"], s["zhi"], tuple(s["touches"])) for s in S["setups"] if s["b"] < cut]
    return out


def _n(rec: dict) -> dict:
    """A signal record with NaN made comparable (a record without a target has target and rr NaN)."""
    return {k: ("nan" if isinstance(v, float) and v != v else (_n(v) if isinstance(v, dict) else v)) for k, v in rec.items()}


def _future_variants(a: dict, cut: int, rng) -> dict:
    n = len(a["c"])
    junk = {k: v.copy() for k, v in a.items()}
    for k in ("o", "h", "l", "c"):
        junk[k][cut:] = a[k][cut:] * rng.uniform(0.5, 1.5, n - cut)
    junk["h"] = np.maximum.reduce([junk["o"], junk["h"], junk["l"], junk["c"]])
    junk["l"] = np.minimum.reduce([junk["o"], junk["h"], junk["l"], junk["c"]])
    junk["v"][cut:] = rng.lognormal(0, 2, n - cut) * 100
    perm = rng.permutation(np.arange(cut, n))
    shuf = {k: v.copy() for k, v in a.items()}
    for k in shuf:
        shuf[k][cut:] = a[k][perm]
    removed = {k: v[:cut].copy() for k, v in a.items()}
    return {"removed": removed, "junk": junk, "shuffled": shuf}


@pytest.mark.parametrize("seed", [10, 1])
def test_no_signal_at_or_before_bar_t_reads_a_later_bar(seed):
    a = load_fixture(seed)
    full = ZF.signals_from_arrays(a["o"], a["h"], a["l"], a["c"], a["v"])
    rng = np.random.default_rng(1)
    compared = 0
    for cut in (1800, 2800, 3700):
        ref = _key(full, cut)
        compared += len(ref)
        for name, b in _future_variants(a, cut, rng).items():
            got = _key(ZF.signals_from_arrays(b["o"], b["h"], b["l"], b["c"], b["v"]), cut)
            assert got == ref, f"look-ahead ({name}) cut={cut}"
    assert compared > 50


def test_one_decision_never_depends_on_later_bars():
    """Cut right after a signal bar r (so r is the last bar): the member's detector finds the same record for r with
    only bars <= r as with the whole series, also when everything after r is replaced by junk."""
    a = load_fixture(10)
    det = ZF.ZoneFlipDetector()
    atr = ZF.atr14(a["h"], a["l"], a["c"])
    full = det.detect(a["o"], a["h"], a["l"], a["c"], a["v"], atr, 400)
    assert len(full) >= 5
    rng = np.random.default_rng(2)
    for rec in full[:12]:
        r = rec["r"]
        for b in (_future_variants(a, r + 1, rng)["removed"], _future_variants(a, r + 1, rng)["junk"]):
            at = ZF.atr14(b["h"], b["l"], b["c"])
            got = [_n(x) for x in det.detect(b["o"], b["h"], b["l"], b["c"], b["v"], at, r) if x["r"] == r]
            want = [_n(x) for x in full if x["r"] == r]
            assert got == want, r


def test_chunked_detection_equals_one_batch():
    """The league feeds bars in chunks (arrays end at the newest closed bar): every signal found, in whatever chunks,
    is the batch's."""
    a = load_fixture(1)
    det = ZF.ZoneFlipDetector()
    atr = ZF.atr14(a["h"], a["l"], a["c"])
    full = det.detect(a["o"], a["h"], a["l"], a["c"], a["v"], atr, 1000)
    got, edges = [], list(range(1000, 4000, 173)) + [4000]
    for lo, hi in zip(edges[:-1], edges[1:]):
        got += det.detect(a["o"][:hi], a["h"][:hi], a["l"][:hi], a["c"][:hi], a["v"][:hi], atr[:hi], lo)
    assert len(full) > 10
    # a signal on the last bar of a chunk has the same-bar rule applied with all that bar's signals
    key = lambda x: (x["r"], x["b"], x["extra"]["zone_lo"])           # noqa: E731
    assert [_n(x) for x in sorted(full, key=key)] == [_n(x) for x in sorted(got, key=key)]


def test_the_volume_profile_does_not_depend_on_which_bars_are_computed_together():
    a = series_arrays("BTC", "1h")
    at = np.arange(250, 3900, 3)
    whole = ZF.profiles(a["h"], a["l"], a["v"], at, chunk=512)
    for chunk in (7, 64):
        part = ZF.profiles(a["h"], a["l"], a["v"], at, chunk=chunk)
        for x, y in zip(whole, part):
            assert np.array_equal(x, y)
    one = [ZF.profiles(a["h"], a["l"], a["v"], np.array([x]))[0][0] for x in at[:60]]
    assert all(np.array_equal(whole[0][i], one[i]) for i in range(60))
