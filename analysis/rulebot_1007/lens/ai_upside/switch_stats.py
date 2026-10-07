#!/usr/bin/env python3
"""Summaries of switch_accounts.csv: final equity of each policy minus base, per run x kind x timeframe.

    python3 -I switch_stats.py <out_dir>
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
sys.path.append(site.getusersitepackages())
import os  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}


def main():
    out = sys.argv[1]
    D = pd.read_csv(os.path.join(out, "switch_accounts.csv"))
    D["run_s"] = D["run"].map(RUNS)
    b = D[D["policy"] == "base"].set_index(["run", "account_id"])
    rows = []
    rng = np.random.default_rng(11)
    for pol in ["SW_ANY", "SW_UNDER", "SW_STALE", "SW_OPP"]:
        p = D[D["policy"] == pol].set_index(["run", "account_id"])
        j = p.join(b[["final_equity", "n_trades", "sum_R"]], rsuffix="_base")
        j["d_eq"] = j["final_equity"] - j["final_equity_base"]
        j = j.reset_index()
        for run_s in ["v3b", "v4", "ALL"]:
            jr = j if run_s == "ALL" else j[j["run_s"] == run_s]
            for kind in ["strategy", "ds200", "random"]:
                for tf in ["15m", "30m", "1h", "4h", "ALL"]:
                    g = jr[(jr["kind"] == kind) & ((jr["timeframe"] == tf) if tf != "ALL" else True)]
                    g = g[g["n_switch"].notna()]
                    if not len(g):
                        continue
                    d = g["d_eq"].to_numpy(float)
                    sw = g["n_switch"].sum()
                    # sign-flip across accounts (accounts are not independent in time; descriptive only)
                    if len(d) >= 5 and np.any(d != 0):
                        null = (rng.choice([-1.0, 1.0], size=(5000, len(d))) * d).mean(1)
                        p2 = (np.sum(np.abs(null) >= abs(d.mean()) - 1e-12) + 1) / 5001
                    else:
                        p2 = np.nan
                    rows.append({"policy": pol, "run": run_s, "kind": kind, "tf": tf, "accounts": len(g),
                                 "accounts_switching": int((g["n_switch"] > 0).sum()), "switches": int(sw),
                                 "trades_base": int(g["n_trades_base"].sum()), "trades_policy": int(g["n_trades"].sum()),
                                 "sum_d_equity_usd": d.sum(), "mean_d_equity_usd": d.mean(),
                                 "d_equity_per_switch_usd": d.sum() / sw if sw else np.nan,
                                 "share_accounts_better": float(np.mean(d > 0.01)),
                                 "share_accounts_worse": float(np.mean(d < -0.01)),
                                 "p_two_signflip_accounts": p2,
                                 "mean_R_switch_exits": (g["R_switch_exits"].sum() / g["n_switch_exits"].sum())
                                 if g["n_switch_exits"].sum() else np.nan})
    S = pd.DataFrame(rows)
    S.to_csv(os.path.join(out, "switch_summary.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(S[S["tf"].isin(["15m", "30m", "1h", "ALL"]) & (S["kind"] != "random")].round(3).to_string())


if __name__ == "__main__":
    main()
