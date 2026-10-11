"""research/hunt/entries_wide.py: the WIDE study's entry events (PREREG_HUNT_WIDE W2-W4). Synthetic bars only.

- bar building: UTC bins of 5m bars (PREREG_HUNT 4), partial first / last bin dropped, gaps, fill index; equal to the
  full grid's run.build_frame on the same minutes (1m -> 5m -> timeframe)
- the F2/F3 adapter equals research/fullgrid/run.signals on the full grid's own frame (core, DeepSeek, BTC context)
- the event rule (true on t, false on t-1) and the F1 entries against a slow bar-by-bar reading of PREREG_HUNT 5
- no look-ahead: every entry cell's events at bar t are unchanged when the 5m bars after t are cut or replaced
  (BTC context too)
- the system list: 762 systems (730 + the 32 F5 famous-rule systems), unique and stable ids, F4 = the candidate
  league's 38 watch picks
- F5: the turtle and time-series momentum states equal research/famous/famous.py on daily bars; the event is the
  first bar the state turns on (both bars defined); day lengths in bars of each timeframe; weekly rebalance only
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import entries_wide as EW  # noqa: E402

DAY = 86_400_000
T0 = int(np.datetime64("2021-03-01", "ms").astype(np.int64))


def synth(n: int, seed: int, step: int = 300_000, t0: int = T0, gaps: bool = False) -> dict:
    """Random walk with volatility clusters and trending / ranging stretches (synthetic only)."""
    rng = np.random.default_rng(seed)
    per = max(1, 300_000 // step)
    ts = t0 + np.arange(n, dtype=np.int64) * step
    reg = np.repeat(rng.choice([-1, 0, 0, 1], size=n // (2000 * per) + 1), 2000 * per)[:n]
    sig = 0.002 / np.sqrt(per) * np.exp(np.repeat(rng.normal(0, 0.4, n // (500 * per) + 1), 500 * per)[:n])
    ret = rng.normal(0, 1, n) * sig + reg * 0.08 * sig
    jump = rng.random(n) < 0.003
    ret[jump] *= 5
    c = 100 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 1, n) * sig)
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 1, n) * sig)
    v = rng.lognormal(0, 1, n) * 100 * np.where(rng.random(n) < 0.01, 6.0, 1.0)
    d = dict(ts=ts, o=o, h=h, l=lo, c=c, v=v, qv=v * c)
    if gaps:
        keep = np.ones(n, bool)
        for a in rng.integers(100, n - 100, 6):
            keep[a:a + rng.integers(1, 40)] = False
        d = {k: x[keep] for k, x in d.items()}
    return d


def bars_of(d: dict, tf: str) -> EW.Bars:
    return EW.build_bars(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"], tf, d.get("qv"))


def cut5(d: dict, k: int) -> dict:
    return {key: x[:k].copy() for key, x in d.items()}


def junk5(d: dict, k: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    e = {key: x.copy() for key, x in d.items()}
    m = len(e["ts"]) - k
    f = rng.uniform(0.6, 1.6, m)
    for key in ("o", "c"):
        e[key][k:] = e[key][k:] * f
    e["h"][k:] = np.maximum(e["o"][k:], e["c"][k:]) * (1 + rng.uniform(0, 0.02, m))
    e["l"][k:] = np.minimum(e["o"][k:], e["c"][k:]) * (1 - rng.uniform(0, 0.02, m))
    e["v"][k:] = rng.lognormal(0, 2, m) * 100
    e["qv"][k:] = e["v"][k:] * e["c"][k:]
    return e


# ------------------------------------------------------------------ bars
def test_build_bars_bins_gaps_and_edges():
    d = synth(3000, 1, gaps=True)
    # start inside a 1h bin and end inside one: both partial bins dropped
    d = {k: x[2:-3] for k, x in d.items()}
    ts = d["ts"]
    for tf in EW.TFS:
        b = bars_of(d, tf)
        step = EW.TF_MS[tf]
        assert np.all(b.open_ms % step == 0) and np.all(np.diff(b.open_ms) > 0)
        assert np.array_equal(b.close_ms, b.open_ms + step)
        assert b.open_ms[0] >= ts[0] and b.close_ms[-1] <= ts[-1] + EW.FIVE_MS
        for i in range(len(b)):
            m = (ts >= b.open_ms[i]) & (ts < b.close_ms[i])
            assert m.any() and m.sum() == b.n5[i]
            assert b.o[i] == d["o"][m][0] and b.c[i] == d["c"][m][-1]
            assert b.h[i] == d["h"][m].max() and b.l[i] == d["l"][m].min()
            assert np.isclose(b.v[i], d["v"][m].sum(), rtol=1e-12) and np.isclose(b.qv[i], d["qv"][m].sum(), rtol=1e-12)
            j = b.first5[i]
            assert ts[j] >= b.close_ms[i] if j < len(ts) else True
            assert j == 0 or ts[j - 1] < b.close_ms[i]
        # every complete bin with at least one 5m bar is a bar; a bin with none is not
        bins = np.unique(ts // step) * step
        inner = bins[(bins >= ts[0]) & (bins + step - EW.FIVE_MS <= ts[-1])]
        assert np.array_equal(b.open_ms, inner)
    assert len(bars_of(d, "1h")) < len(bars_of(d, "15m"))
    with pytest.raises(ValueError):
        EW.build_bars(ts[::-1], d["o"], d["h"], d["l"], d["c"], d["v"], "1h")
    with pytest.raises(ValueError):
        EW.build_bars(ts + 60_000, d["o"], d["h"], d["l"], d["c"], d["v"], "1h")


def _fake_minutes(R, monkeypatch, coins: dict):
    monkeypatch.setattr(R, "minute_data", lambda data_dir, sym: coins[sym])
    R.frame.cache_clear()


def test_bars_equal_full_grid_frame(monkeypatch):
    """1m -> 5m (resample_1m_to_5m) -> timeframe gives run.build_frame's bars (the 1m data starts and ends mid-bin and
    has gaps)."""
    R = EW.fullgrid_run()
    m = synth(60_000, 7, step=60_000, t0=T0 + 7 * 60_000, gaps=True)
    m = {k: x[:-11] for k, x in m.items()}
    _fake_minutes(R, monkeypatch, {"ETHUSDT": m})
    f5 = EW.resample_1m_to_5m(m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"])
    for tf in EW.TFS:
        df, close = R.build_frame("x", "ETHUSDT", tf)
        b = EW.build_bars(*f5, tf)
        # the only possible difference is at the data's end: the 1m data stops inside the bin's last 5m slot, so the
        # 5m bars have that slot (a partial 5m bar) and keep the bin, the full grid drops it (archive 5m bars are
        # whole intervals, so this cannot happen on archive data)
        extra = len(b) - len(df)
        assert extra in (0, 1)
        if extra:
            assert b.open_ms[-1] + EW.TF_MS[tf] - EW.FIVE_MS <= int(m["ts"][-1]) < b.close_ms[-1] - 60_000
        n = len(df)
        mine = b.df.iloc[:n]
        assert np.array_equal(b.close_ms[:n], close)
        for k in ("open", "high", "low", "close"):
            assert np.array_equal(mine[k].to_numpy(), df[k].to_numpy()), (tf, k)
        assert np.allclose(mine["volume"].to_numpy(), df["volume"].to_numpy(), rtol=1e-12, atol=0)
        assert (mine["ts"] == df["ts"]).all() and mine.attrs["tf"] == df.attrs["tf"] == tf


# ------------------------------------------------------------------ adapter = run.signals
@pytest.mark.parametrize("kind,name,sym", [
    ("core", "N01_ST_EMA", "ETHUSDT"), ("core", "S5_DONCHIAN_MFI", "ETHUSDT"), ("core", "OBV_S", "ETHUSDT"),
    ("core", "V45_AMB", "ETHUSDT"), ("ds", "F14_SMT", "ETHUSDT"), ("ds", "F14_SMT", "BTCUSDT"),
    ("ds", "F15_ASIA_BRK", "ETHUSDT"), ("ds", "F9_FVG", "SOLUSDT"), ("ds", "F11_PO3", "ETHUSDT"),
])
def test_adapter_equals_run_signals(monkeypatch, kind, name, sym):
    R = EW.fullgrid_run()
    t0 = T0  # whole bins: the two builds then have the same bars
    coins = {s: synth(80_000, 30 + i, step=60_000, t0=t0) for i, s in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT"))}
    _fake_minutes(R, monkeypatch, coins)
    R._LAST_SERIES[0] = None
    combo = R.default_combo(kind, name)
    tfs = ("15m", "1h") if kind == "core" else tuple(t for t in ("15m", "1h") if t in R.ds_module().TFS_OF[name])
    for tf in tfs:
        want_l, want_s = R.signals("x", kind, name, sym, tf, combo)
        five = {s: EW.resample_1m_to_5m(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"]) for s, d in coins.items()}
        b = EW.build_bars(*five[sym], tf)
        btc = EW.build_bars(*five["BTCUSDT"], tf)
        spec = {"id": "t", "family": "F2" if kind == "core" else "F3", "name": name, "kind": kind, "tf": tf,
                "gate": "NONE", "combo": combo}
        ev = EW.events_on(spec, b, sym, btc)
        assert len(b) == len(want_l)
        assert np.array_equal(ev["raw_long"], want_l) and np.array_equal(ev["raw_short"], want_s), (name, tf)
        el, es = EW.rising(want_l), EW.rising(want_s)
        el[:R.WARMUP_BARS] = False                    # the full grid's warm-up (PREREG_HUNT_WIDE 3.1)
        es[:R.WARMUP_BARS] = False
        assert np.array_equal(ev["long"], el) and np.array_equal(ev["short"], es)
        assert not (ev["long"] & ev["short"]).any()
    R._LAST_SERIES[0] = None


def test_ds_needs_btc_context():
    d = synth(20_000, 3)
    b = bars_of(d, "1h")
    spec = {"id": "t", "family": "F3", "name": "F14_SMT", "kind": "ds", "tf": "1h", "gate": "NONE", "combo": {"smt_len": 20}}
    with pytest.raises(ValueError):
        EW.events_on(spec, b, "ETHUSDT", None)
    EW.events_on(spec, b, "BTCUSDT", None)            # BTC itself takes no context (as run.signals)
    with pytest.raises(ValueError):
        EW.events_on(dict(spec, tf="4h"), b, "BTCUSDT", None)


# ------------------------------------------------------------------ events
def test_rising_and_classify():
    x = np.array([1, 1, 0, 1, 0, 0, 1, 1, 1, 0], bool)
    assert EW.rising(x).tolist() == [0, 0, 0, 1, 0, 0, 1, 0, 0, 0]          # the first bar gives none
    assert EW.rising(np.zeros(0, bool)).shape == (0,)
    z = np.zeros(10, bool)
    assert EW.classify(x, z)["kind"] == "state" and EW.classify(x, z)["continuation"] == 3     # 3 of 6: half
    y = np.array([1, 1, 0, 1, 0, 0, 1, 0, 1, 0], bool)
    assert EW.classify(y, z)["kind"] == "mixed" and EW.classify(z, y)["continuation"] == 1
    assert EW.classify(EW.rising(x), z)["kind"] == "event"
    assert EW.classify(np.r_[False, np.ones(9, bool)], z)["kind"] == "state"


def _slow_hunt(name: str, b: EW.Bars, value) -> tuple[np.ndarray, np.ndarray]:
    """PREREG_HUNT 5 read bar by bar (cond true on t and false on t-1, every needed value defined on both bars)."""
    h, l, c, qv = b.h, b.l, b.c, b.qv
    n = len(c)

    def cond(t):
        if name == "E1":
            if t < value or t < EW.E1_VOL_LEN:
                return None
            hh, ll = h[t - value:t].max(), l[t - value:t].min()
            vm = qv[t - EW.E1_VOL_LEN:t].mean()
            vok = qv[t] >= 2 * vm
            return (c[t] > hh and vok, c[t] < ll and vok)
        if name == "E2":
            def band(i):
                w = c[i - 19:i + 1]
                m, s = w.mean(), w.std()
                return m + 2 * s, m - 2 * s, 4 * s / m
            if t - value < 19 or t < 20:
                return None
            bws = np.array([band(i)[2] for i in range(t - value, t)])
            sq = band(t - 1)[2] <= np.percentile(bws, 20)
            up, lo, _ = band(t)
            up1, lo1, _ = band(t - 1)
            return (sq and c[t] > up and c[t - 1] <= up1, sq and c[t] < lo and c[t - 1] >= lo1)
        if name == "E3":
            a14, a100 = EW.wilder_atr(h, l, c, 14), EW.wilder_atr(h, l, c, 100)
            r = a14 / a100
            if t < 20 or not (np.isfinite(r[t]) and np.isfinite(r[t - 1])):
                return None
            x = r[t] >= value and r[t - 1] < value
            return (x and c[t] > c[t - 20], x and c[t] < c[t - 20])
        raise AssertionError

    lg, sh = np.zeros(n, bool), np.zeros(n, bool)
    prev = None
    for t in range(n):
        cur = cond(t)
        if cur is not None and prev is not None:
            lg[t] = cur[0] and not prev[0]
            sh[t] = cur[1] and not prev[1]
        prev = cur
    return lg, sh


@pytest.mark.parametrize("name,value", [("E1", 55), ("E1", 44), ("E2", 120), ("E2", 96), ("E3", 1.5), ("E3", 1.4)])
def test_hunt_entries_match_prereg(name, value):
    d = synth(30_000, 11)
    b = bars_of(d, "1h" if name != "E3" else "15m")
    if name == "E3":
        b = EW.Bars(b.tf, b.open_ms[:1200], b.o[:1200], b.h[:1200], b.l[:1200], b.c[:1200], b.v[:1200], b.qv[:1200],
                    b.n5[:1200], b.first5[:1200], b.n_five)
    got = EW.hunt_raw(name, b, value)
    want = _slow_hunt(name, b, value)
    assert np.array_equal(got[0], want[0]) and np.array_equal(got[1], want[1])
    assert got[0].sum() + got[1].sum() > 0, "no event at all: the test would be empty"
    assert not (got[0] & got[1]).any()
    assert np.array_equal(EW.rising(got[0]), got[0]) and np.array_equal(EW.rising(got[1]), got[1])


def test_e1_uses_quote_volume_and_e1_handmade():
    n = 80
    ts = T0 + np.arange(n * 12, dtype=np.int64) * EW.FIVE_MS
    c = np.full(n * 12, 100.0)
    c[-12:] = 103.0                                   # last hour closes above every earlier high
    o, h, l = c.copy(), c + 0.5, c - 0.5
    v = np.full(n * 12, 10.0)
    qv = v * c
    qv[-12:] *= 2.5                                   # quote volume x2.5 in the breakout hour, base volume flat
    b = EW.build_bars(ts, o, h, l, c, v, "1h", qv)
    lg, sh = EW.hunt_raw("E1", b)
    assert lg[-1] and lg.sum() == 1 and not sh.any()
    b2 = EW.build_bars(ts, o, h, l, c, v, "1h", v * c)
    assert not EW.hunt_raw("E1", b2)[0].any()         # the same bars with flat quote volume: no event
    with pytest.raises(ValueError):                   # no quote volume given: refused, not silently empty
        EW.hunt_raw("E1", EW.build_bars(ts, o, h, l, c, v, "1h"))


# ------------------------------------------------------------------ no look-ahead
def test_no_lookahead_every_entry_cell():
    """Each entry cell's events at a bar closing at or before the cut are the same on the cut series and on the full
    series whose 5m bars after the cut are junk (the coin's and BTC's)."""
    n = 48_000
    eth, btc = synth(n, 21), synth(n, 22)
    k = 41_003                                        # inside a bin of every timeframe
    variants = [(cut5(eth, k), cut5(btc, k)), (junk5(eth, k, 1), junk5(btc, k, 2))]
    cut_ms = int(eth["ts"][k])
    checked = 0
    cells = EW.entry_cells()
    by_tf = {}
    for tf in EW.TFS:
        full = (bars_of(eth, tf), bars_of(btc, tf))
        vs = [(bars_of(a, tf), bars_of(bb, tf)) for a, bb in variants]
        by_tf[tf] = (full, vs)
    for cell in cells:
        spec = dict(cell, id="t", gate="NONE")
        (fb, fbtc), vs = by_tf[cell["tf"]]
        want = EW.events_on(spec, fb, "ETHUSDT", fbtc)
        for vb, vbtc in vs:
            got = EW.events_on(spec, vb, "ETHUSDT", vbtc)
            m = vb.close_ms <= cut_ms
            j = np.searchsorted(fb.open_ms, vb.open_ms[m])
            assert np.array_equal(fb.open_ms[j], vb.open_ms[m])
            for side in ("long", "short", "raw_long", "raw_short"):
                assert np.array_equal(got[side][m], want[side][j]), (cell["family"], cell["name"], cell["tf"], side)
            checked += int(got["long"][m].sum() + got["short"][m].sum())
    assert checked > 5000
    # the bars themselves: a complete bin never changes, the bin holding the cut is dropped from the cut series
    for tf in EW.TFS:
        (fb, _), vs = by_tf[tf]
        vb = vs[0][0]
        assert vb.close_ms[-1] <= cut_ms and np.array_equal(vb.c, fb.c[:len(vb)])


# ------------------------------------------------------------------ gate
def test_gate():
    d = synth(140_000, 5)
    b = bars_of(d, "4h")
    from paperbot.dash.tools import regime5y as Y
    code = Y.regimes(b.h, b.l, b.c, 240)["code"]
    assert np.array_equal(EW.gate_ok(b, "G1"), code == Y.TREND)
    assert EW.gate_ok(b, "NONE").all()
    with pytest.raises(ValueError):
        EW.gate_ok(b, "G2")
    assert np.array_equal(EW.atr14(b), Y.adx_atr(b.h, b.l, b.c, 14)[1], equal_nan=True)


# ------------------------------------------------------------------ systems
def test_systems_count_ids_stable():
    S = EW.systems()
    assert len(S) == EW.N_SYSTEMS == 762
    ids = [s["id"] for s in S]
    assert len(set(ids)) == len(ids)
    assert ids == [s["id"] for s in EW.systems()]
    fam = {f: sum(s["family"] == f for s in S) for f in EW.FAMILIES}
    assert fam == {"F1": 24, "F2": 288, "F3": 342, "F4": 76, "F5": 32}
    assert sum(s["family"] != "F4" for s in S) == 686                # the candidates (owners 2026-10-11 (a))
    assert len({s["strategy"] for s in S if s["family"] != "F4"}) == 87
    f5 = [s for s in S if s["family"] == "F5"]
    assert {s["name"] for s in f5} == set(EW.FAMOUS_NAMES) and {s["kind"] for s in f5} == {"famous"}
    assert all(s["combo"] == EW.FAMOUS_COMBO[s["name"]] for s in f5)
    assert {s["gate"] for s in S} == {"G1", "NONE"}
    for s in S:
        want = f"{s['family']}:{s['name']}:{s['tf']}:{s['gate']}" + (f":r{s['rank']}" if s["family"] == "F4" else "")
        assert s["id"] == want and s["strategy"] == s["name"]
        assert s["tf"] in EW.TFS
    R = EW.fullgrid_run()
    D = R.ds_module()
    assert sum(len(D.TFS_OF[n]) for n in D.DEFS) == 171            # 39 x 4 + 5 x 3: F15 sessions have no 4h
    assert {s["name"] for s in S if s["family"] == "F2"} == set(R.core_names())
    assert {s["name"] for s in S if s["family"] == "F3"} == set(D.DEFS)
    for s in S:
        if s["family"] == "F2":
            assert s["combo"] == {k: (list(v) if isinstance(v, tuple) else v)
                                  for k, v in R.default_combo("core", s["name"]).items()}
    # pinned id list: a change of the system list shows here
    digest = hashlib.sha256("\n".join(ids).encode()).hexdigest()
    assert digest == PINNED_IDS_SHA, digest
    # the 730 systems of the reviewed list keep their ids and order; F5 is appended
    assert hashlib.sha256("\n".join(ids[:730]).encode()).hexdigest() == PINNED_IDS_SHA_730
    assert len(EW.entry_cells()) == 381


PINNED_IDS_SHA = "b0b9e2b5337f530cb2ece762000753956d6d4df6e81788f9634acce6d71c76db"
PINNED_IDS_SHA_730 = "2c470bf319f61da3ccb5b4091c7f6c286764991fb9768e4527e6685222a8e658"


def test_f4_is_the_league_watch_list():
    picks = EW.watch_picks()
    assert len(picks) == 38
    if not os.path.exists(EW.LEAGUE_CANDIDATES):
        pytest.skip("candleague/data/candidates.json absent")
    with open(EW.LEAGUE_CANDIDATES) as fh:
        league = {c["id"]: c for c in json.load(fh)["candidates"]}
    for p in picks:
        c = league[p["cand_id"]]
        assert (c["kind"], c["name"], c["tf"]) == (p["kind"], p["name"], p["tf"])
        assert c["combo"] == p["combo"]
    S = [s for s in EW.systems() if s["family"] == "F4"]
    assert sorted({s["cand_id"] for s in S}) == sorted(p["cand_id"] for p in picks)


# ------------------------------------------------------------------ parity on the hunt files (review finding)
def test_parity_reads_hunt_files_as_the_run_does(tmp_path):
    """parity_wide --five used every stored row; select / test drop zero-volume (and duplicate, off-grid) rows, so a
    1h bin made only of zero-volume bars existed in the parity and not in the run. Now both read the same bars."""
    from research.hunt import hunt as H
    from research.hunt import parity_wide as PW
    d = synth(3 * 288, 31)
    qv = d["qv"].astype(np.float64)
    qv[24:36] = 0                                     # one whole 1h bin of zero-volume bars
    ts = d["ts"].copy()
    ts[100] = ts[99]                                  # duplicate open time
    (tmp_path / "5m").mkdir()
    np.savez_compressed(tmp_path / "5m" / "AUSDT.npz", ts=ts, **{k: d[k].astype(np.float64) for k in
                                                                  ("o", "h", "l", "c", "v")}, qv=qv)
    (t5, o, h, lo, c, v), counts = PW.five_of(None, None, "AUSDT", str(tmp_path))
    assert counts["zero_volume"] == 12 and counts["duplicates"] == 1 and len(t5) == len(ts) - 13
    # review finding: parity.json names the data it ran on (the H 2 content hash the wide pin compares, W 8)
    assert counts["content_sha256"] == H.file_content_sha(str(tmp_path / "5m" / "AUSDT.npz"), "5m")
    with np.load(tmp_path / "5m" / "AUSDT.npz") as z:
        (want_ts, *_), _ = H.clean_5m(z["ts"], z["o"], z["h"], z["l"], z["c"], z["v"], z["qv"])
    assert np.array_equal(t5, want_ts) and o.dtype == np.float64
    with np.load(tmp_path / "5m" / "AUSDT.npz") as z:                 # float64 as stored: no narrowing on the way
        keep = np.isin(z["ts"], t5) & (z["qv"] > 0)
        keep[99] = False                                               # the duplicate: the later row is kept
        assert np.array_equal(o, z["o"][keep]) and np.array_equal(v, z["v"][keep])
    b = EW.build_bars(t5, o, h, lo, c, v, "1h")
    assert (int(d["ts"][24]) // 3_600_000) * 3_600_000 not in set(b.open_ms.tolist())   # the zero bin is no bar


# ------------------------------------------------------------------ F5: famous trend rules (owners 2026-10-11 (a))
def _famous():
    import importlib.util
    spec = importlib.util.spec_from_file_location("famous_ref", os.path.join(ROOT, "research", "famous", "famous.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _daily(n: int, seed: int):
    import pandas as pd
    rng = np.random.default_rng(seed)
    reg = np.repeat(rng.choice([-1, 0, 1], size=n // 40 + 1), 40)[:n]
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n) + reg * 0.01))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.02, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.02, n))
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c}, index=idx)


@pytest.mark.parametrize("n,m", [(20, 10), (55, 20)])
def test_turtle_state_equals_famous_donchian(n, m):
    F = _famous()
    d = _daily(900, 3)
    want = F.donchian(d, n, m).to_numpy()
    pos, defined = EW.turtle_state(d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy(), n, m)
    assert np.array_equal(pos, want.astype(np.int8))
    assert not defined[:n].any() and defined[n:].all()
    assert (pos == 1).sum() > 50 and (pos == -1).sum() > 50


@pytest.mark.parametrize("lb", [7, 28])
def test_tsmom_state_equals_famous_tsmom(lb):
    """famous.tsmom rebalances at the close of each UTC Sunday (daily bar dated Sunday); on intraday bars that is the
    bar closing at Monday 00:00 UTC."""
    F = _famous()
    d = _daily(700, 5)
    want = F.tsmom(d, lb).to_numpy()
    close_ms = (d.index.asi8 // 1_000_000) + DAY                    # a daily bar closes at the next 00:00
    pos, defined = EW.tsmom_state(close_ms, d["close"].to_numpy(), lb)
    assert np.array_equal(pos, want.astype(np.int8))
    first = int(np.flatnonzero(defined)[0])
    assert d.index[first].dayofweek == 6 and first >= lb and not defined[:first].any()


def _slow_events(pos, defined):
    lg, sh = np.zeros(len(pos), bool), np.zeros(len(pos), bool)
    for t in range(1, len(pos)):
        if defined[t] and defined[t - 1]:
            lg[t] = pos[t] > 0 and not pos[t - 1] > 0
            sh[t] = pos[t] < 0 and not pos[t - 1] < 0
    return lg, sh


@pytest.mark.parametrize("name", EW.FAMOUS_NAMES)
@pytest.mark.parametrize("tf", ["15m", "1h", "4h"])
def test_famous_events_are_first_bars_of_the_state(name, tf):
    """W 3.3: an F5 event = the rule's long (short) position turns on at bar t (both bars defined); the lengths are
    days x bars per day of the timeframe."""
    d = synth(288 * 150, 41)
    b = bars_of(d, tf)
    el, es = EW.famous_raw(name, b)
    bpd = EW.BARS_PER_DAY[tf]
    assert bpd == {"15m": 96, "1h": 24, "4h": 6}[tf]
    combo = EW.FAMOUS_COMBO[name]
    if name.startswith("TURTLE"):
        pos, defined = EW.turtle_state(b.h, b.l, b.c, combo["entry_days"] * bpd, combo["exit_days"] * bpd)
    else:
        pos, defined = EW.tsmom_state(b.close_ms, b.c, combo["lookback_days"] * bpd)
    want = _slow_events(pos, defined)
    assert np.array_equal(el, want[0]) and np.array_equal(es, want[1])
    assert el.sum() + es.sum() > 0 and not (el & es).any()
    if name.startswith("TSMOM"):                                  # events only at the weekly rebalance close
        cm = b.close_ms[el | es]
        assert np.all(cm % DAY == 0) and np.all(((cm // DAY) + 3) % 7 == 0)
    spec = {"id": "t", "family": "F5", "name": name, "kind": "famous", "tf": tf, "gate": "NONE", "combo": combo}
    ev = EW.events_on(spec, b, "ETHUSDT")
    assert np.array_equal(ev["long"], el) and np.array_equal(ev["short"], es)


def test_tsmom_events_are_the_same_moments_on_every_timeframe():
    """The weekly rule is decided at the Monday 00:00 UTC close on every timeframe with the same day lookback, so on a
    gap-free series its events fall on the same moments (only the stop, chandelier and gate timeframe differ)."""
    d = synth(288 * 120, 43, t0=int(np.datetime64("2021-03-01", "ms").astype(np.int64)))
    seen = {}
    for tf in EW.TFS:
        b = bars_of(d, tf)
        el, es = EW.famous_raw("TSMOM7", b)
        seen[tf] = (tuple(b.close_ms[el]), tuple(b.close_ms[es]))
    assert len(set(seen.values())) == 1 and sum(len(x) for x in seen["1h"]) > 0
