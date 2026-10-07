#!/usr/bin/env python3
"""How much did the nightly d3 pairing (unresolved rows dropped) bias each variant? v4 trades only.

    python3 -I d3_bias.py <variants_rows.csv> <exitlab_rows.csv> <out_dir>

For the v4 trades the nightly job shadowed (d3), take the exitlab rows of the same signal (same account = strategy@tf,
coin, bar close; flip 0; re-run on live_bars to 10/07 15:40 KST; still-open rows marked). Compare the variant - base
difference (base-stop R) on (a) d3's resolved pairs, (b) exitlab on ALL d3 trades. (b) - (a) = the pairing bias.
Also the same for the v3a d3 rows cannot be re-run (no live_bars in that export).
"""
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from statsutil import cluster_boot  # noqa: E402


def main():
    V = pd.read_csv(sys.argv[1])
    X = pd.read_csv(sys.argv[2], low_memory=False)
    out = sys.argv[3]
    V = V[V.run == "current"].copy()
    V["strategy"] = V["aid"].str.split("@").str[0]
    V = V.rename(columns={"bc": "bar_close"})
    X = X[(X.run == "current") & (X.flip == 0)].copy()
    b = X[X.variant == "base"][["sig_id", "entry_price", "stop_initial", "pnl", "qty", "status"]].rename(
        columns={"entry_price": "b_entry", "stop_initial": "b_stop", "pnl": "b_pnl", "qty": "b_qty", "status": "b_status"})
    X = X.merge(b, on="sig_id")
    X["dist"] = (X.b_entry - X.b_stop).abs()
    ent = X.status.isin(["CLOSED", "OPEN_END"])
    X["R"] = np.where(ent, X.pnl / (X.qty * X.dist), np.nan)
    X["Rb"] = X.b_pnl / (X.b_qty * X.dist)
    keys = ["strategy", "timeframe", "symbol", "bar_close"]
    # one exitlab signal per account-signal (duplicates of the same account signal are identical)
    X = X.drop_duplicates(keys + ["variant"])
    j = V.merge(X[keys + ["variant", "R", "Rb", "status"]], left_on=keys + ["kind"], right_on=keys + ["variant"],
                how="left")
    rows = []
    for (tf, var), g in j.groupby(["timeframe", "kind"]):
        if var == "base" or tf not in ("15m", "30m", "1h", "4h"):
            continue
        a = g[g.roe.notna() & g.b_roe.notna() & np.isfinite(g.v_R) & np.isfinite(g.b_R)]
        bb = g[g.R.notna() & g.Rb.notna()]
        ca = cluster_boot((a.v_R - a.b_R).to_numpy(), (a.bar_close // 3_600_000).to_numpy())
        cb = cluster_boot((bb.R - bb.Rb).to_numpy(), (bb.bar_close // 3_600_000).to_numpy())
        un = g[g.resolved == 0]
        rows.append({"tf": tf, "variant": var, "d3_rows": len(g), "d3_unresolved": len(un),
                     "n_d3_pairs": len(a), "diff_R_d3_pairs": ca["mean"], "lo_d3": ca["lo"], "hi_d3": ca["hi"],
                     "n_all_rerun": len(bb), "diff_R_all_rerun": cb["mean"], "lo_all": cb["lo"], "hi_all": cb["hi"],
                     "bias_d3_minus_all": ca["mean"] - cb["mean"],
                     "still_open_in_rerun": int((g.status == "OPEN_END").sum()),
                     "diff_R_on_d3_unresolved_rows": (un.R - un.Rb).mean() if len(un) else np.nan})
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(out, "d3_bias_v4.csv"), index=False)
    pd.set_option("display.width", 250)
    print(D.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
