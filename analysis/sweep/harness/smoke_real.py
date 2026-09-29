"""Smoke test on REAL bars allowed for the harness agent: BTCUSD 15m from
/home/user/crypto-bot-research/data/btcusd-15m-ohlcv.csv, bars >= 2025-08-07 only (FINAL window).
Purposes: (1) look-ahead truncation tests on real data at 15m/30m/1h/4h/1d (5m: synthetic, no
real 5m bars are allowed here), (2) per-strategy signal runtime per bar, (3) exit-stage runtime.
No gate decision is computed from these bars.
usage: python3 smoke_real.py [trunc|timing|exits|all]"""
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

OUT = os.path.join(HERE, "out")
SRC = "/home/user/crypto-bot-research/data/btcusd-15m-ohlcv.csv"
what = sys.argv[1] if len(sys.argv) > 1 else "all"

raw = L.read_ohlcv(SRC)
raw = raw[raw["ts"] >= pd.Timestamp("2025-08-07", tz="UTC")].reset_index(drop=True)
assert raw["ts"].min() >= pd.Timestamp("2025-08-07", tz="UTC")
print(f"real BTC 15m bars used: {len(raw)} {raw.ts.iloc[0]} .. {raw.ts.iloc[-1]}", flush=True)
frames = {"15m": raw}
for tf in ("30m", "1h", "4h", "1d"):
    frames[tf] = L.resample_ohlcv(raw, tf)

if what in ("trunc", "all"):
    rows = []
    for tf, df in frames.items():
        t0 = time.time()
        r = L.truncation_test(df, tf, n_even=4, n_at_signal=4, seed=7, min_start_frac=0.35)
        r["data"] = "real_btc15m_ge_2025-08-07"
        rows.append(r)
        reg = r[~r.canary]
        bad = reg[~reg.identical_prefix]
        fired = reg[reg["mode"].isin(["plain", "explicit", "resample"])].groupby("strategy")["sig_full"].max()
        can = r[r.canary].groupby(["strategy", "mode"])["identical_prefix"].apply(lambda x: (~x).any())
        print(f"[trunc {tf}] bars={len(df)} checks={len(reg)} failures={sorted(bad.strategy.unique())} "
              f"vacuous={sorted(fired[fired == 0].index)} canaries_detected={ {f'{a}|{b}': bool(v) for (a, b), v in can.items()} } "
              f"{time.time() - t0:.0f}s", flush=True)
    pd.concat(rows, ignore_index=True).to_csv(os.path.join(OUT, "truncation_real_btc15m.csv"), index=False)

if what in ("timing", "all"):
    tm = []
    for tf, df in frames.items():
        L.compute_signals({"BTCUSD": df}, tf, timings=tm)
    # 5m: no real 5m bars allowed -> synthetic 5m of the same length as the 15m sample x3
    s5 = L.synth_ohlcv(3 * len(raw), "5m", seed=5)
    L.compute_signals({"BTCUSD": s5}, "5m", timings=tm)
    t = pd.DataFrame(tm)
    t["us_per_bar"] = t["sec"] / t["bars"] * 1e6
    t.to_csv(os.path.join(OUT, "timing_signals.csv"), index=False)
    piv = t.pivot_table(index="strategy", columns="tf", values="us_per_bar")
    pd.set_option("display.width", 200)
    print(piv.round(1).to_string())
    print("sum us/bar per tf:", piv.sum().round(0).to_dict())

if what in ("exits", "all"):
    tf = "15m"
    panel = {"BTCUSD": frames[tf]}
    sigs = L.compute_signals(panel, tf, ["N17_KC_RSI", "S2_ST_ROC", "V39_ALL"])
    rows = []
    for name in sigs:
        for H in (4, 16, 64):
            t0 = time.time()
            ex = L.exits(tf, name, H, panel, sigs, split="final", B=10)
            dt = time.time() - t0
            n_sig = int(np.abs(sigs[name]["BTCUSD"]).sum())
            rows.append(dict(strategy=name, H=H, signals=n_sig, trades_timeH=int(ex.loc[ex.exit == "TIME_H", "trades"].iloc[0]),
                             sec_total_B10=dt, sec_per_pass=dt / 11, bars=len(frames[tf])))
            print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "timing_exits.csv"), index=False)
