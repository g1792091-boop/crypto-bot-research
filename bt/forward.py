"""Exit-independent signal quality: mean signed forward return (gross, no costs)
N bars after each signal, plus hit-rate of positive forward return."""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

import strategies as S
from run import DATA, OUT, load_csv, window_bounds

HORIZONS = (1, 4, 8, 16, 32, 64)


def forward_stats(df: pd.DataFrame, long_sig, short_sig, lo: int, hi: int, warmup: int = 1000):
    o = df["open"].to_numpy(dtype=float)
    n = len(o)
    rows = {}
    idx = np.where((long_sig | short_sig)[max(lo, warmup):hi])[0] + max(lo, warmup)
    idx = idx[idx + 1 < n]
    side = np.where(long_sig[idx], 1.0, -1.0)
    entry = o[idx + 1]
    rows["signals"] = int(len(idx))
    rows["long_share"] = float((side > 0).mean()) if len(idx) else float("nan")
    for hz in HORIZONS:
        j = np.minimum(idx + 1 + hz, n - 1)
        r = side * (o[j] / entry - 1.0)
        rows[f"fwd{hz}_mean_pct"] = float(r.mean() * 100) if len(r) else float("nan")
        rows[f"fwd{hz}_hit"] = float((r > 0).mean()) if len(r) else float("nan")
        rows[f"fwd{hz}_t"] = float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 2 else float("nan")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="IS")
    ap.add_argument("--symbols", default="BTCUSD,ETHUSD,SOLUSD,LTCUSD,BCHUSD")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    out = []
    for sym in args.symbols.split(","):
        path = os.path.join(DATA, f"{sym.lower()}-15m-ohlcv.csv")
        if not os.path.exists(path):
            continue
        df = load_csv(path, 15)
        lo, hi = window_bounds(df, args.window)
        for name, fn in S.CANDIDATES_15M.items():
            l, s = fn(df)
            l = np.asarray(l, dtype=bool); s = np.asarray(s, dtype=bool) & ~np.asarray(l, dtype=bool)
            r = forward_stats(df, l, s, lo, hi)
            r.update(symbol=sym, strategy=name)
            out.append(r)
        print(sym, "done", flush=True)
    res = pd.DataFrame(out)
    tag = f"_{args.tag}" if args.tag else ""
    res.to_csv(os.path.join(OUT, f"forward_{args.window}{tag}.csv"), index=False)
    # pooled by strategy (signal-weighted)
    g = res.groupby("strategy")
    pooled = pd.DataFrame({
        "signals": g["signals"].sum(),
        **{f"fwd{hz}_mean_pct": g.apply(lambda x, hz=hz: np.average(x[f"fwd{hz}_mean_pct"], weights=x["signals"]) if x["signals"].sum() else np.nan)
           for hz in HORIZONS},
    }).sort_values("fwd16_mean_pct", ascending=False)
    pd.set_option("display.width", 200)
    print(pooled.round(3).to_string())


if __name__ == "__main__":
    main()
