"""More replay-paper parity cases (synthetic 5m bars only, no real price), from the parity review:

- the G1 gate (추세장) really trades: a warm-up of 200+ days gives the 장세 label its 180 days, and the runner equals
  hunt.py's batch backtest at several cycles, not only the last
- a window that crosses a month (Oct -> Nov): every checked cycle equals the batch at the same cut
- a coin that stops trading inside the window: the runner equals hunt.py's own loader (``load_study_data``: npz files
  and the manifest's coin end)
- BTC's bars late while another coin's arrive (the feed releases its mark): the DeepSeek F14_SMT cell, the one entry
  that reads BTC's bars, waits for BTC's bin instead of freezing a wrong event; the record equals the batch
- a coin's bars stalled while another coin's trade opens and closes: the replay changes that closed trade when the
  stalled bars arrive (sizing reads every coin), and the change is recorded (run.db), never silent
- a feed pass committing between the runner's two reads skips no row
"""

from __future__ import annotations

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

import test_huntbot_parity as T  # noqa: E402
from research.hunt import hunt as H  # noqa: E402

from huntbot import bench as B  # noqa: E402
from huntbot import config as CFG  # noqa: E402
from huntbot import engine as E  # noqa: E402
from huntbot.feed import Feed  # noqa: E402
from huntbot.store import Store  # noqa: E402

FIVE, DAY, FWD, HOUR = T.FIVE, T.DAY, T.FWD, 3_600_000
SYMS = T.SYMS
ms = CFG.ms_str


def batch(arrays, end_ms, systems, warm, syms=SYMS):
    """hunt.py's backtest path on the same bars (as T.batch, with the warm-up start as a parameter)."""
    coins, fund = {}, {}
    for s in syms:
        a = arrays[s]
        k = (a["ts"] >= warm) & (a["ts"] < end_ms)
        (ts, o, h, lo, c, v, qv), cnt = H.clean_5m(a["ts"][k], a["o"][k], a["h"][k], a["l"][k], a["c"][k], a["v"][k],
                                                   a["qv"][k])
        coins[s] = H.Coin(s, ts, o, h, lo, c, v, qv, last_ms=2 ** 62, counts=cnt)
        g = ((a["fts"] + 30_000) // FIVE) * FIVE
        kf = (a["fts"] >= FWD - DAY) & (g <= end_ms)
        fund[s] = (a["fts"][kf], a["frate"][kf])
    H.install(coins, fund)
    mk = H.Market(list(syms), (FWD, -(-end_ms // DAY) * DAY), name="batch")
    out = {}
    for spec in systems:
        sig = H.system_signals(mk, spec)
        bank = H.bank_for(mk, (spec["tf"],))
        cands = H.build_cands(mk, bank, [(sig, 0)])
        raw = H.simulate(mk, bank, cands)
        out[spec["id"]] = (E.trades_of(mk, cands, raw, H.params()), float(raw[10][4]),
                           H.summarize(mk, raw, detail=False, days=True))
    return mk, out


def same(r, want: dict, systems, keys=("M", "day_eq", "max_dd")) -> list:
    bad = []
    for spec in systems:
        res = r.last_results[spec["id"]]
        tr, eq, summ = want[spec["id"]]
        ok = len(res["trades"]) == len(tr) and all(T._same_trade(x, y) for x, y in zip(res["trades"], tr)) \
            and res["equity_now"] == eq and all(res["summary"].get(k) == summ.get(k) for k in keys)
        if not ok:
            bad.append(spec["id"])
    return bad


def runner_at(tmp_path, arrays, warm, start, systems, syms=SYMS):
    store = B.make_store(os.path.join(str(tmp_path), "store.db"), syms, arrays, warm, start)
    clock = B.FakeClock(start + 60_000)
    r = B.make_test_runner(str(tmp_path), store, syms, warm, clock, systems=systems)
    return store, clock, r


# ---------------------------------------------------------------- G1 trades, several cycles
def test_g1_systems_trade_and_checked_cycles_equal_the_batch(tmp_path, patched):
    warm = CFG.day_ms("2026-03-10")                       # > 180 days before 10/01: the 장세 label is known
    systems = [s for s in T.specs() if s["gate"] == "G1"]
    arrays = B.synth_arrays(SYMS, warm, T.END + DAY, seed=3)
    cycles = T._cycles()[::3] + [T.END]
    store, clock, r = runner_at(tmp_path, arrays, warm, cycles[0], systems)
    prev, checked, g1_trades = cycles[0], 0, 0
    for i, comp in enumerate(cycles):
        if comp > prev:
            B.store_insert(store, arrays, prev, comp)
            prev = comp
        clock.ms = comp + 60_000
        info = r.cycle(comp)
        assert not info["errors"], info["errors"]
        if i % 6 == 0 or comp == cycles[-1]:
            mk, want = batch(arrays, comp, systems, warm)
            assert same(r, want, systems) == [], ms(comp)
            checked += 1
            g1_trades = sum(len(w[0]) for w in want.values())
    assert checked >= 4 and g1_trades >= 5                 # the G1 gate let trades through (not an empty comparison)
    assert r.ledger.counts()["repaints"] == 0 and r.trade_change_counts()["changed"] == 0


@pytest.fixture()
def patched(monkeypatch):
    monkeypatch.setattr(H, "entry_events", T.fake_events)
    yield


# ---------------------------------------------------------------- a month boundary
def test_october_to_november_every_checked_cycle_equals_the_batch(tmp_path, patched):
    nov = CFG.day_ms("2026-11-01")
    systems = [s for s in T.specs() if s["gate"] == "NONE"]
    arrays = B.synth_arrays(SYMS, T.WARM, nov + 3 * DAY, seed=9)
    cycles = [nov - 2 * HOUR] + [nov - 2 * HOUR + i * 7 * FIVE for i in range(1, 40)]
    store, clock, r = runner_at(tmp_path, arrays, T.WARM, cycles[0], systems)
    prev, n = cycles[0], 0
    for i, comp in enumerate(cycles):
        if comp > prev:
            B.store_insert(store, arrays, prev, comp)
            prev = comp
        clock.ms = comp + 60_000
        r.cycle(comp)
        if i % 3 == 0:
            mk, want = batch(arrays, comp, systems, T.WARM)
            assert same(r, want, systems, keys=("M", "day_eq", "max_dd", "months")) == [], ms(comp)
            n += 1
    assert mk.months[-1] == "2026-11" and len(mk.months) == 2 and n >= 12
    assert sum(len(t["trades"]) for t in r.last_results.values()) > 20


# ---------------------------------------------------------------- a coin end, hunt.py's own loader
def test_coin_end_matches_hunt_load_study_data(tmp_path, patched):
    systems = [s for s in T.specs() if s["gate"] == "NONE"]
    arrays = B.synth_arrays(SYMS, T.WARM, T.END + DAY, seed=3)
    stop = FWD + DAY + 7 * HOUR + 35 * 60_000                    # BBB's last bar with volume: 10/02 07:35
    a = arrays["BBBUSDT"]
    dead = a["ts"] > stop
    a["v"][dead] = 0.0
    a["qv"][dead] = 0.0
    d = str(tmp_path / "npz")
    os.makedirs(os.path.join(d, "5m"))
    os.makedirs(os.path.join(d, "funding"))
    man = {"symbols": []}
    for s, x in arrays.items():                              # the 5m files are float64 (H 2, W 9), as the feed's bars
        np.savez(os.path.join(d, "5m", f"{s}.npz"), ts=x["ts"], **{k: x[k].astype(np.float64)
                                                                   for k in ("o", "h", "l", "c", "v", "qv")})
        np.savez(os.path.join(d, "funding", f"{s}.npz"), ts=x["fts"], rate=x["frate"])
        nz = x["ts"][x["qv"] > 0]
        man["symbols"].append({"symbol": s, "last_bar": ms(int(x["ts"][-1])),
                               "last_nonzero_volume_bar": ms(int(nz[-1]))})
    with open(os.path.join(d, "manifest.json"), "w") as fh:
        json.dump(man, fh)
    H.load_study_data(d, SYMS, T.END)
    mk = H.Market(SYMS, (FWD, T.END), name="batch")
    want = {}
    for spec in systems:
        sig = H.system_signals(mk, spec)
        bank = H.bank_for(mk, (spec["tf"],))
        c = H.build_cands(mk, bank, [(sig, 0)])
        raw = H.simulate(mk, bank, c)
        want[spec["id"]] = (E.trades_of(mk, c, raw, H.params()), float(raw[10][4]), {})
    assert int(mk.coin_end_t[SYMS.index("BBBUSDT")]) >= 0                 # the batch closes BBB at its end
    cycles = T._cycles()[::2] + [T.END]
    store, clock, r = runner_at(tmp_path / "run", arrays, T.WARM, cycles[0], systems)
    prev = cycles[0]
    for comp in cycles:
        if comp > prev:
            B.store_insert(store, arrays, prev, comp)
            prev = comp
        if comp >= stop + 3 * HOUR:                     # the feed ends the coin a few hours after it stopped
            end = store.conn.execute("SELECT MAX(open_ms) FROM bars_5m WHERE symbol = 'BBBUSDT' AND qv > 0"
                                     ).fetchone()[0]
            store.set_coin("BBBUSDT", trading=0, end_ms=end)
            store.commit()
        clock.ms = comp + 60_000
        assert not r.cycle(comp)["errors"]
    assert same(r, want, systems, keys=()) == []
    assert any(t["reason"] == "coin_end" for res in r.last_results.values() for t in res["trades"])


# ---------------------------------------------------------------- BTC late: the DeepSeek cell that reads BTC
def _stalled_run(tmp_path, arrays, syms, warm, start, stop_at, systems, stall_sym, a, b, step_after=FIVE):
    """Bars arrive every 5 minutes, but ``stall_sym``'s are held back from a to b; the feed's own rule decides the
    mark (released after MAX_WAIT_MS). Returns the runner and [(mark, {system: trades})] per cycle."""
    store, clock, r = runner_at(tmp_path, arrays, warm, start, systems, syms)
    feed = Feed(store, client=None, universe=syms, warmup_ms=warm, clock=clock)
    held = {s: start for s in syms}
    seen, t, last = [], start, start
    r.cycle(start)
    while t < stop_at:
        t += FIVE if t < b else step_after
        for s in syms:
            upto = held[s] if (s == stall_sym and a <= t < b) else t
            if upto > held[s]:
                B.store_insert(store, {s: arrays[s]}, held[s], upto)
                held[s] = upto
        store.put("complete_ms", last)
        clock.ms = t + 11_000
        comp = feed.compute_complete()
        store.commit()
        if comp == last:
            continue
        last = comp
        clock.ms = t + 30_000
        info = r.cycle(comp)
        assert not info["errors"], info["errors"]
        seen.append((comp, {sid: [dict(x) for x in res["trades"]] for sid, res in r.last_results.items()}))
    return r, store, seen, last


def test_btc_late_deepseek_cell_waits_for_btc(tmp_path):
    from huntbot import systems as S
    syms = ["BTCUSDT", "AAAUSDT"]
    warm, end = CFG.day_ms("2026-08-01"), CFG.day_ms("2026-10-05")
    systems_all, _ = S.system_list()
    specs = [s for s in systems_all if s["id"] == "F3:F14_SMT:15m:NONE"]
    assert specs, "the DeepSeek F14_SMT cell (the one entry that reads BTC's bars) is in the wide list"
    arrays = B.synth_arrays(syms, warm, end, seed=21)
    mk0, want0 = batch(arrays, end, specs, warm, syms)
    traded = [t["signal_close_ms"] for t in want0[specs[0]["id"]][0]
              if t["signal_close_ms"] > FWD + DAY and t["coin"] == "AAAUSDT"]
    assert traded, "no F14_SMT trade on AAA in the window (synthetic seed)"
    e0 = int(traded[0])
    a, b = e0 - HOUR, e0 + HOUR                                  # BTC's bars late around the event
    start = e0 - 3 * HOUR
    r, store, seen, last = _stalled_run(tmp_path, arrays, syms, warm, start, b + 2 * HOUR, specs, "BTCUSDT", a, b,
                                        step_after=3 * FIVE)
    assert any(c > a + 30 * 60_000 for c, _ in seen if c < b)  # the mark moved on without BTC (the feed's rule)
    _, want = batch(arrays, last, specs, warm, syms)
    assert same(r, want, specs, keys=()) == []
    assert r.ledger.counts()["repaints"] == 0                    # nothing frozen wrong, nothing re-found later


# ---------------------------------------------------------------- a stalled coin: a closed trade changes, recorded
def _find_pair(arrays, systems):
    mk, want = batch(arrays, FWD + 2 * DAY, systems, T.WARM)
    for spec in systems:
        tr = want[spec["id"]][0]
        for y in tr:
            if y["open"] or y["in_ms"] < FWD + 19 * HOUR:
                continue
            for x in tr:
                if x["coin"] != y["coin"] and x["in_ms"] < y["in_ms"] - 30 * 60_000 and \
                        (x["open"] or x["out_ms"] > y["out_ms"] + 30 * 60_000):
                    return spec, x, y
    return None


def test_a_closed_trade_changed_by_a_stalled_coin_is_recorded(tmp_path, patched):
    systems = [s for s in T.specs() if s["id"] == "F1:E2:15m:NONE"]
    arrays = B.synth_arrays(SYMS, T.WARM, T.END + DAY, seed=1)
    found = _find_pair(arrays, systems)
    assert found, "seed 1 has an X position open around a whole Y trade"
    spec, x, y = found
    a, b = y["in_ms"] - 20 * 60_000, y["out_ms"] + 30 * 60_000
    r, store, seen, last = _stalled_run(tmp_path, arrays, SYMS, T.WARM, FWD + 18 * HOUR, b + 2 * HOUR, [spec],
                                        x["coin"], a, b, step_after=3 * FIVE)
    key = (y["coin"], y["in_ms"])
    shown = [t for c, by in seen for t in by[spec["id"]] if (t["coin"], t["in_ms"]) == key and not t["open"]]
    assert shown
    changed = not T._same_trade(shown[0], shown[-1])
    _, want = batch(arrays, last, [spec], T.WARM)
    assert same(r, want, [spec], keys=()) == []                  # the record ends equal to the batch
    rows = r.rdb.execute("SELECT tkey, kind FROM trade_changes WHERE account = ?", (spec["id"],)).fetchall()
    keyed = [k for k, kind in rows if k.startswith(f"{y['coin']}|{y['side']}|{y['in_ms']}|")]
    if changed:                                                  # the change was shown, so it must be recorded
        assert keyed and r.trade_change_counts()["changed"] >= 1
    assert all(kind in ("changed", "gone", "back") for _, kind in rows)
    assert changed, "the scenario no longer changes Y (the test would not test anything)"


def test_without_a_stall_no_trade_change_is_recorded(tmp_path, patched):
    systems = [s for s in T.specs() if s["gate"] == "NONE"]
    arrays = B.synth_arrays(SYMS, T.WARM, T.END + DAY, seed=3)
    r, seen = T._run(tmp_path, arrays, T._cycles()[:30], systems)
    assert r.trade_change_counts() == {"changed": 0, "gone": 0, "last": []}
    assert r.rdb.execute("SELECT COUNT(*) FROM trades_seen").fetchone()[0] > 0


# ---------------------------------------------------------------- a feed commit between the runner's two reads
def test_a_feed_commit_between_the_runner_reads_skips_no_row(tmp_path, patched):
    systems = [s for s in T.specs() if s["gate"] == "NONE"]
    arrays = B.synth_arrays(SYMS, T.WARM, T.END + DAY, seed=3)
    c0 = FWD + 18 * HOUR
    store, clock, r = runner_at(tmp_path, arrays, T.WARM, c0, systems)
    feed_conn = Store(os.path.join(str(tmp_path), "store.db"))      # the feed process: its own connection
    r.cycle(c0)
    c1, c2 = c0 + 2 * FIVE, c0 + 3 * FIVE
    B.store_insert(feed_conn, arrays, c0, c1)
    orig_since, orig_max = r.store.bars_since, r.store.max_ins

    def max_ins_then_feed_commits():                                # the feed commits right after one of the reads
        out = orig_max()
        B.store_insert(feed_conn, arrays, c1, c2)
        return out
    r.store.max_ins = max_ins_then_feed_commits
    r.cycle(c1)
    r.store.max_ins = orig_max

    def since_then_feed_commits(ins, upto=None):
        out = orig_since(ins, upto)
        B.store_insert(feed_conn, arrays, c2, c2 + FIVE)
        return out
    r.store.bars_since = since_then_feed_commits
    clock.ms = c2 + 60_000
    r.cycle(c2)
    r.store.bars_since = orig_since
    t = c2 + FIVE
    while t < c0 + 2 * HOUR:
        B.store_insert(feed_conn, arrays, t, t + FIVE)
        t += FIVE
        clock.ms = t + 60_000
        info = r.cycle(t)
        assert not info["errors"], info["errors"]
    for s in SYMS:
        st = store.load_bars(s, T.WARM)["ts"]
        assert np.array_equal(r.data[s]["ts"][r.data[s]["ts"] < t], st[st < t]), s
    _, want = batch(arrays, t, systems, T.WARM)
    assert same(r, want, systems, keys=()) == []


def test_a_hole_in_memory_is_found_and_reloaded(tmp_path, patched):
    systems = [s for s in T.specs() if s["id"] == "F2:FAKE:15m:NONE"]
    arrays = B.synth_arrays(SYMS, T.WARM, T.END + DAY, seed=3)
    c0 = FWD + 18 * HOUR
    store, clock, r = runner_at(tmp_path, arrays, T.WARM, c0, systems)
    r.cycle(c0)
    d = r.data["AAAUSDT"]                                          # one bar lost in memory (any cause)
    k = len(d["ts"]) - 5
    for col in list(d):
        d[col] = np.delete(d[col], k)
    B.store_insert(store, arrays, c0, c0 + FIVE)
    clock.ms = c0 + FIVE + 60_000
    info = r.cycle(c0 + FIVE)
    assert info["sync"]["reloaded"] == ["AAAUSDT"] and any("hole" in e for e in info["errors"])
    st = store.load_bars("AAAUSDT", T.WARM)["ts"]
    assert np.array_equal(r.data["AAAUSDT"]["ts"], st)
