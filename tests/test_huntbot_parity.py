"""huntbot replay paper = research/hunt/hunt.py's batch backtest (synthetic 5m bars only, no real price).

- the runner stepped through a window bar by bar reproduces the batch backtest's trades, equity and month figures
  exactly (same systems, same window, same data);
- appending bars never changes a trade that had already closed (no look-ahead, no repaint), also across a restart;
- the hourly marking (the same engine on an hour axis) changes nothing and the month figures read from it are exact;
- the stop in force read by the probe is the price a later bar falling through it exits at;
- a definition that repaints its past is caught (ledger ``repaints``) and cannot change the record.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402

from huntbot import bench as B  # noqa: E402
from huntbot import config as CFG  # noqa: E402
from huntbot import engine as E  # noqa: E402

FIVE, DAY = H.FIVE, H.DAY_MS
FWD = CFG.FORWARD_START_MS
WARM = CFG.day_ms("2026-08-20")
END = FWD + 3 * DAY
SYMS = ["BTCUSDT", "AAAUSDT", "BBBUSDT"]
ORIG_EVENTS = H.entry_events


def fake_events(spec, sym, ser, btc):
    """F1 cells: the real E1-E3 code. 'core' cells: a causal stand-in (a bar's event depends on that bar only) with
    many events, so the caps, adds and the coin-busy rule are exercised. 'leaky' cells: NOT causal (bar t looks at bar
    t + 1), to show the ledger freezing it."""
    if spec["kind"] == "hunt":
        return ORIG_EVENTS(spec, sym, ser, btc)
    c, o = ser.bars.c, ser.bars.o
    seed = sum(map(ord, spec["name"] + sym))
    frac = (np.abs(np.sin(ser.bars.open_ms / 7.3e5 + seed)) * 1e4) % 1.0
    if spec["kind"] == "leaky":
        nxt = np.r_[c[1:], c[-1]]
        return (nxt > c * 1.004), (nxt < c * 0.996)
    return (frac < 0.06) & (c > o), (frac > 0.94) & (c < o)


def specs():
    out = []
    for name, par, v in (("E1", "channel", 55), ("E2", "window", 120), ("E3", "threshold", 1.5)):
        for tf in ("15m", "1h"):
            for g in ("G1", "NONE"):
                out.append({"id": f"F1:{name}:{tf}:{g}", "family": "F1", "name": name, "strategy": name, "kind": "hunt",
                            "tf": tf, "gate": g, "combo": {par: v}})
    for tf in ("15m", "30m", "4h"):
        for g in ("G1", "NONE"):
            out.append({"id": f"F2:FAKE:{tf}:{g}", "family": "F2", "name": "FAKE", "strategy": "FAKE", "kind": "core",
                        "tf": tf, "gate": g, "combo": {}})
    return out


@pytest.fixture()
def patched(monkeypatch):
    monkeypatch.setattr(H, "entry_events", fake_events)
    yield


def _cycles():
    out = [FWD + 18 * 3_600_000]                                    # catch-up from 10/01 00:00
    t = out[0]
    while t < FWD + 21 * 3_600_000:                                 # every 5m bar for 3 hours
        t += FIVE
        out.append(t)
    while t < END:                                                  # then every 95 minutes (odd: crosses every tf)
        t = min(END, t + 19 * FIVE)
        out.append(t)
    return out


def _run(tmp_path, arrays, cycles, systems, restart_at=None, data_dir=None):
    d = str(data_dir or tmp_path)
    store = B.make_store(os.path.join(d, "store.db"), SYMS, arrays, WARM, cycles[0])
    clock = B.FakeClock(cycles[0] + 60_000)
    r = B.make_test_runner(d, store, SYMS, WARM, clock, systems=systems)
    seen, prev = [], cycles[0]
    for i, comp in enumerate(cycles):
        if comp > prev:
            B.store_insert(store, arrays, prev, comp)
            prev = comp
        clock.ms = comp + 60_000
        if restart_at is not None and i == restart_at:
            r = B.make_test_runner(d, store, SYMS, WARM, clock, systems=systems)
        info = r.cycle(comp)
        assert not info["errors"], info["errors"]
        seen.append((comp, {sid: res["trades"] for sid, res in r.last_results.items()}, r))
    return r, seen


def batch(arrays, end_ms, systems):
    """The backtest's own path on the same bars: clean_5m -> Coin -> install -> Market -> run the systems."""
    coins, fund = {}, {}
    for s in SYMS:
        a = arrays[s]
        k = (a["ts"] >= WARM) & (a["ts"] < end_ms)
        (ts, o, h, lo, c, v, qv), cnt = H.clean_5m(a["ts"][k], a["o"][k], a["h"][k], a["l"][k], a["c"][k], a["v"][k],
                                                   a["qv"][k])
        coins[s] = H.Coin(s, ts, o, h, lo, c, v, qv, last_ms=2 ** 62, counts=cnt)
        g = ((a["fts"] + 30_000) // FIVE) * FIVE
        kf = (a["fts"] >= FWD - DAY) & (g <= end_ms)
        fund[s] = (a["fts"][kf], a["frate"][kf])
    H.install(coins, fund)
    mk = H.Market(SYMS, (FWD, -(-end_ms // DAY) * DAY), name="batch")
    out = {}
    for spec in systems:
        sig = H.system_signals(mk, spec)
        bank = H.bank_for(mk, (spec["tf"],))
        cands = H.build_cands(mk, bank, [(sig, 0)])
        raw = H.simulate(mk, bank, cands)
        out[spec["id"]] = {"raw": raw, "cands": cands, "summary": H.summarize(mk, raw, detail=False, days=True),
                           "run_system": H.run_system(mk, spec, H.R_BASE, "base", detail=False, days=True)}
    return mk, out


STRIP = ("stop_now",)


def _same_trade(a: dict, b: dict) -> bool:
    return {k: v for k, v in a.items() if k not in STRIP} == {k: v for k, v in b.items() if k not in STRIP}


def test_runner_equals_batch_and_never_repaints(tmp_path, patched):
    arrays = B.synth_arrays(SYMS, WARM, END + DAY, seed=3)
    systems = specs()
    cycles = _cycles()
    r, seen = _run(tmp_path, arrays, cycles, systems)
    # (1) the last cycle = the batch backtest on the same bars, exactly
    mk, bt = batch(arrays, END, systems)
    total = 0
    for spec in systems:
        res = r.last_results[spec["id"]]
        b = bt[spec["id"]]
        want = E.trades_of(mk, b["cands"], b["raw"], H.params())
        assert len(res["trades"]) == len(want), spec["id"]
        for got, w in zip(res["trades"], want):
            assert _same_trade(got, w), (spec["id"], got, w)
        total += len(want)
        assert res["equity_now"] == float(b["raw"][10][4])
        for k in ("M", "day_eq", "end_multiple", "max_dd", "n_positions", "bust", "skipped", "signal_counts",
                  "candidates"):
            assert k in b["summary"] or k in b["run_system"]
            if k in b["summary"]:
                assert res["summary"][k] == b["summary"][k], (spec["id"], k)
            if k in b["run_system"]:
                assert res["summary"][k] == b["run_system"][k], (spec["id"], k)
    assert total > 40                                         # the comparison is not empty
    # (2) a trade closed at some cycle is identical in every later cycle
    n_checked = 0
    for i, (comp, by_sys, _) in enumerate(seen):
        for sid, trades in by_sys.items():
            closed = {(t["coin"], t["in_ms"]): t for t in trades if not t["open"]}
            for comp2, by2, _ in seen[i + 1:]:
                later = {(t["coin"], t["in_ms"]): t for t in by2[sid]}
                for key, t in closed.items():
                    assert key in later and _same_trade(t, later[key]), (sid, comp, comp2, key)
                    n_checked += 1
    assert n_checked > 1000
    assert r.ledger.counts()["repaints"] == 0


def test_restart_continues_the_same_record(tmp_path, patched):
    arrays = B.synth_arrays(SYMS, WARM, END + DAY, seed=5)
    systems = specs()
    cycles = _cycles()[:20]
    r1, seen1 = _run(tmp_path / "a", arrays, cycles, systems)
    r2, seen2 = _run(tmp_path / "b", arrays, cycles, systems, restart_at=10)
    for (c1, a, _), (c2, b, _) in zip(seen1, seen2):
        assert c1 == c2
        for sid in a:
            assert len(a[sid]) == len(b[sid])
            for x, y in zip(a[sid], b[sid]):
                assert _same_trade(x, y)
    assert r2.ledger.counts()["repaints"] == 0
    assert r2.ledger.counts()["events"] == r1.ledger.counts()["events"] > 0


def test_hourly_marks_change_nothing(patched):
    arrays = B.synth_arrays(SYMS, WARM, END + DAY, seed=7)
    systems = [s for s in specs() if s["gate"] == "NONE"]
    mk, bt = batch(arrays, END - 7 * 3_600_000, systems)        # a window that ends inside a day
    for spec in systems:
        b = bt[spec["id"]]
        bank = H.bank_for(mk, (spec["tf"],))
        raw_h, raw_m = E.simulate_hourly(mk, bank, b["cands"], H.params())
        for x, y in zip(raw_m, b["raw"]):
            assert np.array_equal(np.asarray(x), np.asarray(y)), spec["id"]
        assert len(raw_h[0]) == mk.T // 12
        assert raw_h[0][-1] == b["raw"][0][-1]


def _one_long_market(extra_low=None):
    """One coin: flat, then a rising stretch (the long is open), then optionally one bar falling to ``extra_low``."""
    s0 = CFG.day_ms("2022-03-01")
    n_pre, n = 288, 288
    px = [100.0] * n_pre + list(100.0 + 0.02 * np.arange(n))
    bars = [(p, p * 1.001, p * 0.999, p) for p in px]
    if extra_low is not None:
        p = px[-1]
        bars.append((p, p, extra_low, p))
    arr = np.asarray(bars)
    ts = s0 - n_pre * FIVE + np.arange(len(bars), dtype=np.int64) * FIVE
    c = H.Coin("AUSDT", ts, arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], np.full(len(bars), 1e6), np.full(len(bars), 1e9),
               last_ms=2 ** 62)
    H.install({"AUSDT": c}, {})
    mk = H.Market(["AUSDT"], (s0, s0 + 2 * DAY), name="probe")
    seg = mk.b_t[mk.b_off[0]:mk.b_off[1]]
    i = int(np.searchsorted(seg, 10))
    cands = {"t": np.array([10]), "bi": np.array([mk.b_off[0] + i]), "coin": np.array([0]), "side": np.array([1]),
             "d0": np.array([1.5]), "s0": np.array([0]), "s1": np.array([0]), "prio": np.array([0.0]),
             "src": np.array([0]), "close": np.array([s0 + 10 * FIVE]), "j": np.array([0])}
    bank = type("Bk", (), {"s_ct": np.zeros(0, np.int64), "s_h": np.zeros(0), "s_l": np.zeros(0),
                           "s_atr": np.zeros(0)})()
    return mk, bank, cands, s0, n


def test_probe_reads_the_stop_a_falling_bar_exits_at():
    mk, bank, cands, s0, n = _one_long_market()
    prm = H.params()
    raw = H.simulate(mk, bank, cands, prm=prm)
    assert int(raw[4][0, H.RI_REASON]) == H.EX_END and int(raw[4][0, H.RI_ADDS]) >= 1
    st = E.probe_stops(mk, bank, cands, prm, raw, n - 1)[0]
    assert st["kind"] == "stop" and st["source"] == "add_moved_stop"
    mk2, bank2, cands2, _, _ = _one_long_market(extra_low=50.0)
    raw2 = H.simulate(mk2, bank2, cands2, prm=prm)
    assert int(raw2[4][0, H.RI_REASON]) == H.EX_STOP and int(raw2[4][0, H.RI_TOUT]) == n
    assert raw2[3][0, H.RF_XPX] == pytest.approx(st["stop"] * (1 - H.COSTS["base"][1]), rel=1e-12)
    # the probe never changes the account it reads
    again = H.simulate(mk, bank, cands, prm=prm)
    for x, y in zip(again, raw):
        assert np.array_equal(np.asarray(x), np.asarray(y))


def test_a_repainting_definition_is_frozen_and_reported(tmp_path, patched):
    arrays = B.synth_arrays(SYMS, WARM, END + DAY, seed=11)
    leaky = [{"id": f"F2:LEAK:15m:{g}", "family": "F2", "name": "LEAK", "strategy": "LEAK", "kind": "leaky",
              "tf": "15m", "gate": g, "combo": {}} for g in ("G1", "NONE")]
    cycles = _cycles()[:16]
    r, seen = _run(tmp_path, arrays, cycles, leaky)
    assert r.ledger.counts()["repaints"] > 0                  # the next bar changed what the last bar "said"
    for i, (comp, by_sys, _) in enumerate(seen):              # the record still never changes after the fact
        closed = {(t["coin"], t["in_ms"]): t for t in by_sys["F2:LEAK:15m:NONE"] if not t["open"]}
        for _, by2, _ in seen[i + 1:]:
            later = {(t["coin"], t["in_ms"]): t for t in by2["F2:LEAK:15m:NONE"]}
            for k, t in closed.items():
                assert k in later and _same_trade(t, later[k])
