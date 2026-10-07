#!/usr/bin/env python3
"""Per strategy x tf (15m, 30m): live every-signal R by run, side-flip excess, and the three pre-registered
per-strategy context contrasts (features.PER_STRATEGY_FEATURES: hi bucket vs lo bucket), BH across all cells.

    python3 -I per_strategy.py <lens_dir> <out_dir>
"""
from __future__ import annotations

import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
sys.path.insert(0, sys.argv[1])

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import features as F  # noqa: E402
from stats_util import bh, contrast  # noqa: E402

LENS, OUT = sys.argv[1:3]
D = pd.read_csv(os.path.join(OUT, "signals_bucketed.csv.gz"), low_memory=False)
D = D[D["timeframe"].isin(["15m", "30m"])]


def mean_se(g, hours=2.0):
    """n-weighted mean R over runs with a 2h block CR1 SE."""
    num = den = var = 0.0
    for run, h in g.groupby("run"):
        y = h["R"].to_numpy(float)
        cl = (h["bar_close"] // int(hours * 3_600_000)).to_numpy()
        u, inv = np.unique(cl, return_inverse=True)
        G = len(u)
        s = np.bincount(inv, weights=y, minlength=G)
        c = np.bincount(inv, minlength=G).astype(float)
        m = s.sum() / c.sum()
        infl = (s - m * c) / c.sum()
        v = G / max(G - 1, 1) * float((infl ** 2).sum())
        w = len(y)
        num += w * m
        den += w
        var += w * w * v
    return num / den, np.sqrt(var) / den


def main():
    rows = []
    k = 0
    for (kind, strat, tf), g in D.groupby(["kind", "strategy", "timeframe"]):
        r = {"kind": kind, "strategy": strat, "tf": tf, "family": g["family"].iloc[0], "n": len(g)}
        for run in ("v3a", "v3b", "v4"):
            h = g[g["run"] == run]
            r[f"n_{run}"] = len(h)
            r[f"R_{run}"] = h["R"].mean() if len(h) else np.nan
        m, se = mean_se(g)
        r["R_pooled"] = m
        r["se_pooled"] = se
        r["win_pct"] = 100 * (g["R"] > 0).mean()
        fl = g[g["flip_R"].notna()]
        r["n_flip"] = len(fl)
        r["sideflip_excess_R"] = ((fl["R"] - fl["flip_R"]) / 2).mean() if len(fl) else np.nan
        for f, hi, lo in F.PER_STRATEGY_FEATURES:
            col = F.bucket_col(f)
            rl = []
            for run, h in g.groupby("run"):
                h = h[h[col].isin([hi, lo])]
                if len(h):
                    rl.append({"y": h["R"].to_numpy(float), "inb": (h[col] == hi).to_numpy(),
                               "bc": h["bar_close"].to_numpy(np.int64), "name": run})
            k += 1
            c = contrast(rl, hours=2.0, B=1000, seed=k, min_each=5)
            tag = f"{f}:{hi}-{lo}"
            r[f"n_hi[{tag}]"] = c["n_in"]
            r[f"n_lo[{tag}]"] = c["n_out"]
            r[f"d[{tag}]"] = c["d"]
            r[f"p[{tag}]"] = c["p_two"] if (c["n_in"] >= 10 and c["n_out"] >= 10) else np.nan
            r[f"runs[{tag}]"] = c["runs_used"]
        rows.append(r)
    T = pd.DataFrame(rows)
    pcols = [c for c in T.columns if c.startswith("p[")]
    allp = T[pcols].to_numpy().ravel()
    q, rej = bh(allp)
    qm = q.reshape(T[pcols].shape)
    for j, c in enumerate(pcols):
        T["q" + c[1:]] = qm[:, j]
    T["n_tests_cell"] = T[pcols].notna().sum(1)
    T.to_csv(os.path.join(OUT, "per_strategy_live.csv"), index=False)
    tested = int(np.isfinite(allp).sum())
    print("per-strategy context tests:", tested, "raw p<0.05:", int((allp < 0.05).sum()), "BH q<0.05:",
          int(np.nansum(q < 0.05)), "q<0.10:", int(np.nansum(q < 0.10)))
    pd.set_option("display.width", 250)
    show = T[T["n"] >= 40].sort_values(["tf", "R_pooled"], ascending=[True, False])
    print(show[["kind", "strategy", "tf", "family", "n", "n_v3a", "n_v3b", "n_v4", "R_v3a", "R_v3b", "R_v4", "R_pooled",
                "se_pooled", "sideflip_excess_R", "n_tests_cell"]].round(3).to_string())
    low = []
    for c in pcols:
        x = T[T[c] < 0.05][["kind", "strategy", "tf", c, "q" + c[1:], "d" + c[1:], "runs" + c[1:]]]
        for _, rr in x.iterrows():
            low.append({"kind": rr["kind"], "strategy": rr["strategy"], "tf": rr["tf"], "test": c[2:-1], "p": rr[c],
                        "q": rr["q" + c[1:]], "d": rr["d" + c[1:]], "runs": rr["runs" + c[1:]]})
    print(pd.DataFrame(low).round(3).to_string())


if __name__ == "__main__":
    main()
