#!/usr/bin/env python3
"""Trend persistence per 6 h block (efficiency ratio of 15m closes, mean over the 6 coins) next to the wide-minus-house
exit difference of that block (regime_blocks_6h.csv).

    python3 -I trend_blocks.py <export_dir> <regime_blocks_6h.csv> <out_dir>

ER = |close_end - close_start| / sum |15m close changes| within the block (1 = straight line, ~0 = chop).
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
    exp, blocks, out = sys.argv[1], sys.argv[2], sys.argv[3]
    bars = pd.concat([pd.read_csv(os.path.join(exp, r, "live_bars.csv"), usecols=["ts", "symbol", "close"])
                      for r in ("run-20261005T183457Z", "current")]).drop_duplicates(["ts", "symbol"])
    bars = bars[bars.ts % 900_000 == 840_000]           # last minute of each 15m bar -> its close
    bars["blk"] = (bars.ts // (6 * 3_600_000)).astype("int64")
    rows = []
    for (blk, sym), g in bars.sort_values("ts").groupby(["blk", "symbol"]):
        c = g.close.to_numpy()
        if len(c) < 8:
            continue
        er = abs(c[-1] - c[0]) / np.sum(np.abs(np.diff(c))) if np.sum(np.abs(np.diff(c))) > 0 else np.nan
        rows.append({"blk": blk, "symbol": sym, "er": er, "ret_pct": 100 * (c[-1] / c[0] - 1)})
    E = pd.DataFrame(rows).groupby("blk").agg(er=("er", "mean"), abs_ret_pct=("ret_pct", lambda s: s.abs().mean()),
                                              n_coins=("er", "size")).reset_index()
    B = pd.read_csv(blocks)
    B = B[B.tfg == "15m+30m"].merge(E, on="blk", how="left")
    B = B[B.n >= 100]
    B.to_csv(os.path.join(out, "trend_blocks_6h.csv"), index=False)
    print(B[["start_utc", "n", "R_base", "d_geo10", "d_RL2_1", "d_tp1R", "er", "abs_ret_pct"]].round(3).to_string(index=False))
    for v in ("d_geo10", "d_RL2_1", "d_RL1_0.5", "d_tp3R", "d_tp1R"):
        ok = B[[v, "er"]].dropna()
        print(v, "corr with ER:", round(np.corrcoef(ok[v], ok["er"])[0, 1], 3),
              "| with |ret|:", round(np.corrcoef(B[v], B["abs_ret_pct"])[0, 1], 3), "blocks", len(ok))


if __name__ == "__main__":
    main()
