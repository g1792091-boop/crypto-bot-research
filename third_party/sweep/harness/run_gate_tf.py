"""Discover-phase runner: signals (cached) + gate statistics for one timeframe.
usage: python3 run_gate_tf.py --tf 15m --out DIR [--split is] [--names A,B] [--data_root ROOT]
writes DIR/signals_<split>_<tf>.npz, DIR/gate_<split>_<tf>.csv, DIR/timings_<split>_<tf>.csv
Set OMP_NUM_THREADS=1 (the harness counts one process = one core)."""
import argparse
import hashlib
import os
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--tf", required=True, choices=list(L.TFS))
ap.add_argument("--split", default="is", choices=["is", "oos", "final"])
ap.add_argument("--out", required=True)
ap.add_argument("--names", default="")
ap.add_argument("--data_root", default=None)
ap.add_argument("--B", type=int, default=L.B_GATE)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
names = a.names.split(",") if a.names else L.NAMES
t0 = time.time()
panel = L.load_panel(a.tf, a.split, root=a.data_root)
print(f"loaded {len(panel)} coins: " + ", ".join(
    f"{c}:{len(d)} {d['ts'].iloc[0]:%Y-%m-%d}..{d['ts'].iloc[-1]:%Y-%m-%d %H:%M} gaps={d.attrs['gaps']} misaligned={d.attrs['misaligned']}"
    for c, d in panel.items()), flush=True)
tag = ("_sub" + hashlib.md5(",".join(names).encode()).hexdigest()[:8]) if a.names else ""
cache = os.path.join(a.out, f"signals_{a.split}_{a.tf}{tag}.npz")
tm = []
if os.path.exists(cache):
    sigs = L.load_signals(cache)
else:
    sigs = L.compute_signals(panel, a.tf, names, timings=tm, verbose=True)
    L.save_signals(cache, sigs)
    pd.DataFrame(tm).to_csv(os.path.join(a.out, f"timings_{a.split}_{a.tf}{tag}.csv"), index=False)
t1 = time.time()
g = L.gate_from_signals(panel, sigs, a.tf, a.split, L.HS, a.B, names)
fn = os.path.join(a.out, f"gate_{a.split}_{a.tf}{tag}.csv")
g.to_csv(fn, index=False)
print(f"signals {t1 - t0:.0f}s, gate {time.time() - t1:.0f}s -> {fn} ({len(g)} rows)")
