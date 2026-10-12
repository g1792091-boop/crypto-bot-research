"""Hunt round 2 bench (PREREG_HUNT_R2.md section 11, 12): ``hunt_r2 bench`` writes research/hunt_r2/bench_r2.json,
listed in the code pin. Synthetic bars only (seeded random walks, ``hunt.synth_coin``); no real price is read.

* Seconds per signal combo for the heaviest names on a full-length synthetic series (one coin, 15m; N05_PSAR_POC,
  V45_AMB, V39_ALL, F16_FIB618, F10_M2022, plus E1 and TURTLE55 as light names), the default and one other coarse
  combo, timed with the indicator memo kept across the two combos as the event store does (11).
* Seconds per engine run on synthetic signals at the real densities (5, 10 and 15 events per day per coin on 15m,
  scaled by the timeframe: 30m / 2, 1h / 4, 4h / 16) on the 30-coin, 36-month select market.
* The select step's extrapolation: event store (15,121 cells x 30 coins), real Stage 0 + A, 400 null replicates, the
  worst-case box checks; wall hours at 18 and 27 effective cores. If select extrapolates beyond 15 hours wall at 18
  effective cores, the owners are told before renting; nothing is cut (11, 16 #10).
"""

from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import entries_r2 as E  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402

HEAVY = ("N05_PSAR_POC", "V45_AMB", "V39_ALL", "F16_FIB618", "F10_M2022", "E1", "TURTLE55")
DENSITIES = (5.0, 10.0, 15.0)               # events per day per coin on 15m
TF_SCALE = {"15m": 1.0, "30m": 2.0, "1h": 4.0, "4h": 16.0}
LINE_H, LINE_CORES = 15.0, 18               # 11: tell the owners when select extrapolates beyond this
CORES = (18, 27)
NULL_REPS = 400
REAL_RUNS = 8_700                           # 12: real Stage 0 + A, base and cost x2
SELECTABLE = 4_369
BOX_RUNS_MAX = 85 * 80 * 2


def synth_world(n_coins: int, months: int, warm_months: int = 6, seed: int = 1000) -> tuple:
    """Synthetic coins ending at the select period's end, ``months`` of select period after ``warm_months``."""
    end = H.day_ms(H.PERIODS["select"][1])
    start_sel = end - int(months * 30.4375) * H.DAY_MS
    start_sel -= start_sel % H.DAY_MS
    a = start_sel - int(warm_months * 30.4375) * H.DAY_MS
    a -= a % H.DAY_MS
    syms = ["BTCUSDT"] + [f"C{i:02d}USDT" for i in range(1, n_coins)]
    coins = {s: H.synth_coin(s, a, end, seed + i, 10.0 * (1 + i)) for i, s in enumerate(syms)}
    fund = {s: H.synth_funding(a, end, seed + 500 + i) for i, s in enumerate(syms)}
    H.install(coins, fund)
    return syms, (start_sel, end)


def time_signals(names, sym: str, tf: str = "15m", combos: int = 2) -> dict:
    out = {}
    ser = H.series(sym, tf)
    btc = H.series("BTCUSDT", tf).bars if sym != "BTCUSDT" else None
    for nm in names:
        lat = L.coarse(nm)
        idx = [lat.default] + [i for i in range(len(lat)) if i != lat.default][:max(0, combos - 1)]
        if tf not in L.tfs_of(nm):
            continue
        se = E.SeriesEvents(nm, ser.bars, sym, btc if L.KIND_OF[L.family_of(nm)] == "ds" else None)
        t0 = time.perf_counter()
        for i in idx:
            se.events(lat.combos[i])
        out[nm] = round((time.perf_counter() - t0) / len(idx), 4)
    return out


def time_engine(mk, reps: int = 3) -> dict:
    out = {}
    for d in DENSITIES:
        for tf, sc in TF_SCALE.items():
            per_days = sc / d
            ts = []
            for s in range(reps):
                sig = H.synth_signals(mk, tf, per_days, 100 + s)
                t0 = time.perf_counter()
                H.run_signals(mk, [(sig, 0)], H.R_BASE)
                ts.append(time.perf_counter() - t0)
            out[f"{d:g}/day@15m:{tf}"] = round(float(np.median(ts)), 4)
    return out


def extrapolate(sig_s: dict, eng: dict, n_coins_real: int = 30) -> dict:
    """CPU-hours and wall hours of the select step from the synthetic timings (assumptions written out)."""
    light = [v for k, v in sig_s.items() if k not in ("N05_PSAR_POC", "V45_AMB", "V39_ALL")]
    light_s = float(np.median(light)) if light else float(np.median(list(sig_s.values()) or [0.1]))
    store_s = 0.0
    for _fam, nm in L.names():
        per15 = sig_s.get(nm, light_s)
        for tf in L.tfs_of(nm):
            store_s += len(L.coarse(nm)) * n_coins_real * per15 / TF_SCALE[tf]
    run_s = float(np.mean(list(eng.values()))) if eng else 0.3
    nulls_s = NULL_REPS * (SELECTABLE + 8) * run_s
    real_s = REAL_RUNS * run_s
    box_s = BOX_RUNS_MAX * run_s
    total = store_s + nulls_s + real_s + box_s
    wall = {str(c): round(total / c / 3600, 2) for c in CORES}
    return {"cpu_h": {"event_store": round(store_s / 3600, 1), "real": round(real_s / 3600, 2),
                      "nulls": round(nulls_s / 3600, 1), "box_worst": round(box_s / 3600, 1),
                      "select_total": round(total / 3600, 1)},
            "select_wall_h_at_effective_cores": wall,
            "above_the_line": bool(total / LINE_CORES / 3600 > LINE_H),
            "line": f"select above {LINE_H:g} h wall at {LINE_CORES} effective cores: tell the owners before renting; "
                    "nothing is cut (11)",
            "notes": ["signal seconds per combo per coin measured on 15m; other timeframes scaled by bar count "
                      "(30m / 2, 1h / 4, 4h / 16); names not timed use the median of the timed light names",
                      "engine seconds per run = the mean over the densities and timeframes (no density mix of the real "
                      "names is assumed)", "nulls: 400 replicates x (4,369 + 8) runs, base cost only",
                      "box: the worst case, every one of the 85 names taken at 15m (80 points x base and cost x2)",
                      "parallel efficiency 100% at the effective core count (18-27 effective of 32 vCPU)"]}


def bench(out_path: str | None, n_coins: int = 30, months: int = 36, combos: int = 2, names=HEAVY,
          engine_reps: int = 3) -> dict:
    t_all = time.perf_counter()
    res = {"what": "PREREG_HUNT_R2 11 bench: synthetic bars only (seeded random walks), no real price",
           "machine": {"cpu_count": os.cpu_count()}, "coins": n_coins, "select_months": months}
    t0 = time.perf_counter()
    syms, period = synth_world(n_coins, months)
    res["synth_build_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    mk = H.Market(syms, period, name="bench_r2")
    H._G["mk"][mk.key] = mk
    H.prepare_series(syms, H.TF_ORDER)
    res["market_and_series_s"] = round(time.perf_counter() - t0, 2)
    res["signal_s_per_combo_per_coin_15m"] = time_signals(names, syms[1] if len(syms) > 1 else syms[0], "15m", combos)
    res["engine_s_per_run"] = time_engine(mk, engine_reps)
    res["extrapolation"] = extrapolate(res["signal_s_per_combo_per_coin_15m"], res["engine_s_per_run"])
    res["seconds"] = round(time.perf_counter() - t_all, 1)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        tmp = f"{out_path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(res, fh, indent=1)
            fh.write("\n")
        os.replace(tmp, out_path)
    return res
