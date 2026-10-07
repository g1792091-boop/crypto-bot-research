"""Verifier: censoring of 1h/4h live outcomes and 4h coins.
    python3 -I vcensor.py <out_real_dir> <v_live_es.csv>"""
import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
O, ES = sys.argv[1:3]
RP = pd.read_csv(O + "/replay_signals.csv", low_memory=False)
RP = RP[(RP.kind == "strategy") & RP.timeframe.isin(["1h", "4h"])]
for (run, tf), g in RP.groupby(["run", "timeframe"]):
    tr = g[g.status == "TRADED"]; un = g[g.status == "UNRESOLVED"]
    allv = np.concatenate([tr.R.to_numpy(float), un.mark_R.to_numpy(float)])
    print(run, tf, "traded", len(tr), round(tr.R.mean(), 3), "unres", len(un), round(un.mark_R.mean(), 3),
          "incl", round(np.nanmean(allv), 3), "unres mark NaN", un.mark_R.isna().sum(),
          "traded coins", tr.symbol.str.replace("USDT", "").value_counts().to_dict(),
          "unres coins", un.symbol.str.replace("USDT", "").value_counts().to_dict())
T = pd.read_csv(O + "/trades_enriched.csv", low_memory=False)
t4 = T[(T.kind == "strategy") & (T.tf == "4h")]
print("4h account trades:", len(t4), "mean R", round(t4.R.mean(), 3), t4.groupby("run").R.agg(["size", "mean"]).round(3).to_dict(),
      "coins", t4.symbol.str.replace("USDT", "").value_counts().to_dict())
print(" by coin mean R", t4.groupby("symbol").R.agg(["size", "mean"]).round(3).to_dict())
E = pd.read_csv(ES)
x = E[E.tf.isin(["1h", "4h", "30m", "15m"]) & (E.run == "run-20261005T014624Z")]
print("v3a every-signal by tf/status:", x.groupby(["tf", "status"]).size().unstack().to_dict())
e4 = E[(E.tf == "4h") & (E.status == "TRADED")]
print("4h every-signal traded by run x coin:", e4.groupby(["run", "symbol"]).R.agg(["size", "mean"]).round(3).to_string())
