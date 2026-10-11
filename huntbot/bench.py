"""Runtime measurement on synthetic bars (no real price) and the batch replay of stored bars.

    python -m huntbot bench [--coins 22] [--procs N] [--warmup 2025-01-01] [--at 2026-10-12] [--cells all|f1]
                            [--dir DIR] [--out timing.json]
        A synthetic store (seeded random walks, research/hunt/hunt.py ``synth_coin`` / ``synth_funding``) from the
        warm-up start to --at, then the runner: the catch-up cycle from 10/01, and cycles that end on a 5m bar, a 15m,
        a 30m, a 1h and a 4h close (the last is the worst case: every timeframe has a new bin). Times per phase.

    python -m huntbot replay --from 2026-10-01 --to 2026-11-15 [--systems ID,ID] [--procs N] [--out FILE]
        hunt.py's batch backtest (``run_system``) on the stored bars of the window (the H 15 review check: the replay
        of the same days must give the forward record's positions; with the runner's data, exactly).
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time

import numpy as np

from research.hunt import hunt as H

from . import config as CFG

FIVE, DAY = CFG.FIVE, CFG.DAY


# ---------------------------------------------------------------- synthetic store
def synth_arrays(syms: list, start_ms: int, end_ms: int, seed: int = 0) -> dict:
    out = {}
    for i, s in enumerate(syms):
        c = H.synth_coin(s, start_ms, end_ms, 1000 + seed * 97 + i, 10.0 * (1 + i))
        ft, fr = H.synth_funding(start_ms, end_ms, 2000 + seed * 97 + i)
        out[s] = {"ts": c.ts, "o": c.o.astype(np.float64), "h": c.h.astype(np.float64), "l": c.l.astype(np.float64),
                  "c": c.c.astype(np.float64), "v": c.v.astype(np.float64), "qv": c.qv.astype(np.float64),
                  "fts": ft, "frate": fr}
    return out


def store_insert(store, arrays: dict, from_ms: int, to_ms: int) -> None:
    """Bars with from_ms <= open < to_ms and funding with from_ms <= time <= to_ms - 5m ... as the feed would."""
    for s, a in arrays.items():
        k = (a["ts"] >= from_ms) & (a["ts"] < to_ms)
        if k.any():
            store.insert_bars(s, zip(a["ts"][k].tolist(), a["o"][k].tolist(), a["h"][k].tolist(), a["l"][k].tolist(),
                                     a["c"][k].tolist(), a["v"][k].tolist(), a["qv"][k].tolist()))
        kf = (a["fts"] >= from_ms) & (a["fts"] < to_ms)
        if kf.any():
            store.insert_funding(s, zip(a["fts"][kf].tolist(), a["frate"][kf].tolist()))
        store.set_coin(s, status="TRADING", trading=1)
        store.commit()
    store.put("complete_ms", int(to_ms))
    store.commit()


def make_store(path: str, syms: list, arrays: dict, warmup_ms: int, to_ms: int):
    from .store import Store
    st = Store(path)
    store_insert(st, arrays, warmup_ms, to_ms)
    return st


class FakeClock:
    def __init__(self, ms: int):
        self.ms = ms

    def __call__(self) -> float:
        return self.ms / 1000.0


def make_test_runner(data_dir: str, store, syms: list, warmup_ms: int, clock, systems=None, procs: int = 1,
                     lineup_path=None, notifier=None, fwd_ms: int = CFG.FORWARD_START_MS, keep_all: bool = True):
    """A Runner over ``store`` with its outputs under ``data_dir`` (tests and the bench)."""
    from . import runner as RN
    from .ledger import Ledger
    led = Ledger(os.path.join(data_dir, "events.db"), RN.signal_hash(), "bench", clock=clock)
    rdb = RN.open_run_db(os.path.join(data_dir, "run.db"))
    r = RN.Runner(store, led, rdb, syms, lineup_path or os.path.join(data_dir, "lineup.json"),
                  os.path.join(data_dir, "snap"), os.path.join(data_dir, "private"), procs=procs, warmup_ms=warmup_ms,
                  fwd_ms=fwd_ms, clock=clock, log=lambda m: None, notifier=notifier,
                  engine={"hunt_sha256": "bench"}, universe_info={"source": "synthetic"}, syms=syms)
    r.keep_all_trades = keep_all
    if systems is not None:
        from . import systems as S
        r.systems = systems
        r.by_id = {s["id"]: s for s in systems}
        r.cells = S.cells_of(systems)
        r.cell_of_sys = {s["id"]: cid for cid, c in r.cells.items() for s in c.systems}
    return r


def bench_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m huntbot bench")
    ap.add_argument("--coins", type=int, default=22)
    ap.add_argument("--procs", type=int, default=CFG.procs())
    ap.add_argument("--warmup", default=CFG.WARMUP_START)
    ap.add_argument("--at", default="2026-10-12")
    ap.add_argument("--cells", default="all", choices=("all", "f1", "f1f2"))
    ap.add_argument("--dir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--disk", dest="memory", action="store_false", help="keep the synthetic store on disk")
    a = ap.parse_args(argv)
    from . import systems as S
    H._compile_probe()
    t_all = time.perf_counter()
    syms = ["BTCUSDT"] + [f"C{i:02d}USDT" for i in range(1, a.coins)]
    warm, at = CFG.day_ms(a.warmup), CFG.day_ms(a.at)
    end = at + 5 * 3_600_000
    res = {"what": "synthetic bars only (seeded random walks), no real price", "coins": a.coins, "procs": a.procs,
           "cpu_count": os.cpu_count(), "warmup": a.warmup, "at": a.at, "cells": a.cells}
    t0 = time.perf_counter()
    arrays = synth_arrays(syms, warm, end)
    d = a.dir or tempfile.mkdtemp(prefix="huntbot_bench_")
    os.makedirs(d, exist_ok=True)
    for f in ("store.db", "events.db", "run.db"):
        for x in (f, f + "-wal", f + "-shm"):
            if os.path.exists(os.path.join(d, x)):
                os.remove(os.path.join(d, x))
    store = make_store(":memory:" if a.memory else os.path.join(d, "store.db"), syms, arrays, warm, at)
    res["store_build_s"] = round(time.perf_counter() - t0, 1)
    res["bars_per_coin"] = int(((arrays[syms[0]]["ts"] >= warm) & (arrays[syms[0]]["ts"] < at)).sum())
    systems, _ = S.system_list()
    if a.cells == "f1":
        systems = [s for s in systems if s["family"] == "F1"]
    elif a.cells == "f1f2":
        systems = [s for s in systems if s["family"] in ("F1", "F2")]
    res["systems"] = len(systems)
    clock = FakeClock(at + 60_000)
    r = make_test_runner(d, store, syms, warm, clock, systems=systems if a.cells != "all" else None, procs=a.procs,
                         keep_all=False)
    res["cells_n"] = len(r.cells)
    cycles = []
    steps = [("catch_up_10_01_to_at", at), ("5m", at + FIVE), ("5m", at + 2 * FIVE), ("15m", at + 3 * FIVE),
             ("5m", at + 5 * FIVE), ("30m", at + 6 * FIVE), ("5m", at + 11 * FIVE), ("1h", at + 12 * FIVE),
             ("5m", at + 47 * FIVE), ("4h", at + 48 * FIVE)]
    prev = at
    for label, comp in steps:
        if comp > prev:
            store_insert(store, arrays, prev, comp)
            prev = comp
        clock.ms = comp + 60_000
        t1 = time.perf_counter()
        info = r.cycle(comp)
        cycles.append({"label": label, "complete": CFG.ms_str(comp), "seconds": round(time.perf_counter() - t1, 2),
                       "phase": info.get("phase"), "pairs": (info.get("events_lineup") or {}).get("pairs", 0)
                       + (info.get("events_rest") or {}).get("pairs", 0), "errors": len(info.get("errors") or [])})
        print(json.dumps(cycles[-1]), flush=True)
    res["cycles"] = cycles
    res["total_s"] = round(time.perf_counter() - t_all, 1)
    res["snapshot_bytes"] = {f: os.path.getsize(os.path.join(d, "snap", f)) for f in os.listdir(os.path.join(d, "snap"))}
    res["dir"] = d
    out = json.dumps(res, indent=1)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(out + "\n")
    print(out)
    return 0


# ---------------------------------------------------------------- batch replay of stored bars
_RP: dict = {}


def _replay_task(task):
    cid_key, specs = task
    mk = _RP["mk"]
    H._EVENTS.clear()
    H._SIGS.clear()
    out = {}
    for spec in specs:
        out[spec["id"]] = H.run_system(mk, spec, H.R_BASE, "base", detail=True, days=True)
    return out


def replay_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m huntbot replay")
    ap.add_argument("--from", dest="from_", default=CFG.FORWARD_START)
    ap.add_argument("--to", required=True)
    ap.add_argument("--systems", default="")
    ap.add_argument("--procs", type=int, default=CFG.procs())
    ap.add_argument("--warmup", default=None, help="history start (default HUNTBOT_WARMUP_START): the runner's own")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    from . import runner as RN
    from . import systems as S
    from .store import Store
    H._compile_probe()
    lo, hi = CFG.day_ms(a.from_), CFG.day_ms(a.to)
    store = Store(CFG.path("store.db"), readonly=True)
    uni = CFG.load_universe()["symbols"]
    syms_all, aliases = S.system_list()
    pick = [x.strip() for x in a.systems.split(",") if x.strip()]
    specs = [s for s in syms_all if not pick or s["id"] in {aliases.get(p, p) for p in pick}]
    r = RN.Runner(store, _NullLedger(), RN.open_run_db(os.path.join(tempfile.mkdtemp(), "run.db")), uni, "",
                  tempfile.mkdtemp(), tempfile.mkdtemp(),
                  warmup_ms=CFG.day_ms(a.warmup) if a.warmup else CFG.warmup_start_ms(), fwd_ms=lo)
    r.load_data()
    r.sync_data()
    coins, fund = r.build_coins(hi)
    H.install(coins, fund)
    H.prepare_series(r.syms, H.TF_ORDER)
    mk = H.Market(r.syms, (lo, hi), name="replay")
    _RP["mk"] = mk
    groups = {}
    for s in specs:
        groups.setdefault(H.cell_key(s), []).append(s)
    res = {}
    for part in H.pmap(_replay_task, list(groups.items()), a.procs, label="replay"):
        res.update(part)
    doc = {"from": a.from_, "to": a.to, "syms": r.syms, "systems": len(res), "results": res}
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(doc, fh, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    print(f"replay {a.from_}..{a.to}: {len(res)} systems on {len(r.syms)} coins" + (f" -> {a.out}" if a.out else ""))
    return 0


class _NullLedger:
    gen = 0

    def load_book(self):
        return {}
