#!/usr/bin/env python3
"""Real trades that reached +1R but exited on the FIRST ladder rung (lock_roe 0.10) or at the stop, per run x kind x tf.
    python3 -I first_rung.py <trades_enriched.csv> <out_dir>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import os
import pandas as pd
T = pd.read_csv(sys.argv[1]); out = sys.argv[2]
T = T[T["kind"].isin(["strategy", "ds200"]) & (T["exits"] == "house") & T["tf"].isin(["15m", "30m", "1h", "4h"])]
RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
T["run_s"] = T["run"].map(RUNS)
rows = []
for (rs, kind, tf), g in T.groupby(["run_s", "kind", "tf"]):
    m1 = g["mfe_R"] >= 1
    fr = m1 & (g["exit_reason"] == "LOCK") & (g["lock_roe"].round(3) == 0.10)
    sl = m1 & (g["exit_reason"] == "SL")
    m05 = (g["mfe_R"] >= 0.5) & (g["exit_reason"] == "SL")
    rows.append({"run": rs, "kind": kind, "tf": tf, "n": len(g), "lev_mix": g["leverage"].value_counts().to_dict(),
                 "share_mfe_ge_1R": m1.mean(), "share_mfe1_first_rung": fr.mean(), "share_mfe1_SL": sl.mean(),
                 "mean_R_first_rung_after_1R": g.loc[fr, "R"].mean(), "mean_mfe_first_rung_after_1R": g.loc[fr, "mfe_R"].mean(),
                 "giveback_R_per_trade_first_rung": ((g["mfe_R"] - g["R"]) * fr).sum() / len(g),
                 "share_mfe05_SL": m05.mean(), "mean_R_mfe05_SL": g.loc[m05, "R"].mean(),
                 "giveback_R_per_trade_mfe05_SL": ((g["mfe_R"] - g["R"]) * m05).sum() / len(g)})
D = pd.DataFrame(rows)
D.to_csv(os.path.join(out, "giveback_first_rung.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20)
print(D.drop(columns=["lev_mix"]).round(3).to_string())
