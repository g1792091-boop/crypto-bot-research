#!/usr/bin/env python3
"""Validation of exitlab rows.

    python3 -I validate.py <exitlab_rows.csv> <replay_signals.csv> <variants_rows.csv> <out_dir>

1. base (flip 0) vs rb_analyze replay (same engine, same live_bars): ROE equality where both closed.
2. exitlab variants vs the nightly d3 shadows (Binance final klines) on the v4 trades both resolved: ROE agreement.
3. geoL at the trade's own leverage must equal base exactly; ladder_cap2R vs base.
"""
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def main():
    X = pd.read_csv(sys.argv[1])
    RP = pd.read_csv(sys.argv[2])
    V = pd.read_csv(sys.argv[3])
    out = sys.argv[4]
    X["roe"] = X["pnl"] / X["margin"]
    lines = []
    b = X[(X.variant == "base") & (X.flip == 0)]
    m = b.merge(RP[["run", "sig_id", "status", "roe", "exit_reason", "leverage"]], on=["run", "sig_id"],
                suffixes=("", "_rp"))
    both = m[(m.status == "CLOSED") & (m.status_rp == "TRADED")]
    d = (both.roe - both.roe_rp).abs()
    lines.append(f"[1] base vs rb_analyze replay: closed in both {len(both)}; |dROE| max {d.max():.3g}, "
                 f"share < 1e-9 {np.mean(d < 1e-9):.4f}; same exit reason {np.mean(both.exit_reason == both.exit_reason_rp):.4f}")
    for run, g in both.groupby("run"):
        dd = (g.roe - g.roe_rp).abs()
        lines.append(f"    {run}: n {len(g)}, share equal {np.mean(dd < 1e-9):.4f}, max {dd.max():.3g}")
    un = m[m.status_rp == "UNRESOLVED"]
    lines.append(f"    rb_analyze UNRESOLVED {len(un)} -> exitlab status {un.status.value_counts().to_dict()}")
    rej = m[m.status_rp == "REJECTED_SIZING"]
    lines.append(f"    rb_analyze REJECTED_SIZING {len(rej)} -> exitlab {rej.status.value_counts().to_dict()}")
    # 2. d3 shadows (v4 only has the extra variants)
    V4 = V[(V.run == "current") & (V.resolved == 1) & V.roe.notna()].copy()
    V4["bar_close"] = V4["bc"]
    V4["strategy"] = V4["aid"].str.split("@").str[0]
    xx = X[(X.flip == 0) & (X.run == "current") & (X.status == "CLOSED")]
    j = V4.merge(xx[["strategy", "timeframe", "symbol", "bar_close", "variant", "roe", "exit_reason"]],
                 left_on=["strategy", "timeframe", "symbol", "bar_close", "kind"],
                 right_on=["strategy", "timeframe", "symbol", "bar_close", "variant"], suffixes=("_d3", "_x"))
    rows = []
    for var, g in j.groupby("kind"):
        dd = (g.roe_d3 - g.roe_x).abs()
        rows.append({"variant": var, "n": len(g), "share_abs_dROE_lt_0.001": np.mean(dd < 1e-3),
                     "share_lt_0.01": np.mean(dd < 0.01), "median_abs": dd.median(),
                     "mean_d3": g.roe_d3.mean(), "mean_exitlab": g.roe_x.mean(),
                     "same_reason": np.mean(g.exit_reason_d3 == g.exit_reason_x)})
    A = pd.DataFrame(rows)
    A.to_csv(os.path.join(out, "validate_vs_d3.csv"), index=False)
    lines.append("[2] exitlab vs nightly d3 shadows (v4 trades, both resolved):\n" + A.round(4).to_string())
    # 3. geo at own leverage
    xb = X[X.variant == "base"].set_index(["run", "sig_id", "flip"])
    for L in (10, 20, 50):
        g = X[X.variant == f"geo{L}"].set_index(["run", "sig_id", "flip"])
        jj = xb.join(g, rsuffix="_g", how="inner")
        own = jj[jj.leverage == L]
        if len(own):
            dd = (own.pnl - own.pnl_g).abs()
            lines.append(f"[3] geo{L} on trades whose base leverage is {L}x: n {len(own)}, max |dpnl| {dd.max():.3g}")
    txt = "\n".join(lines)
    print(txt)
    with open(os.path.join(out, "validate.txt"), "w") as fh:
        fh.write(txt + "\n")


if __name__ == "__main__":
    main()
