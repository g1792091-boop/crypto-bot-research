"""Parity: my tier-walk rerun vs research/strategy_profiles/out_binance/profiles.json (mean_roe, signals, win)."""
import json
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

out_dir, prof_path = sys.argv[1], sys.argv[2]
prof = json.load(open(prof_path))["profiles"]
rows = []
for tf in ("5m", "15m", "30m", "1h", "4h"):
    d = pd.read_pickle(os.path.join(out_dir, f"fy36_{tf}.pkl.gz"))
    for st, g in d.groupby("strategy", observed=True):
        p = prof.get(st, {}).get(tf)
        if p is None:
            continue
        m = (g["tw_lev"] > 0) & g["tw_done"]
        rows.append(dict(strategy=st, tf=tf, n_sig=len(g), prof_sig=p["signals"], mean_roe=float(g.loc[m, "tw_roe"].astype(float).mean()),
                         prof_mean_roe=p["mean_roe"], win=float((g.loc[m, "tw_roe"] > 0).mean()), prof_win=p["win_rate"],
                         sized=float((g["tw_lev"] > 0).mean()), prof_sized=p["sized_share"]))
r = pd.DataFrame(rows)
r["d_roe"] = r["mean_roe"] - r["prof_mean_roe"]
r["d_sig"] = r["n_sig"] - r["prof_sig"]
r.to_csv(os.path.join(out_dir, "fy36_parity.csv"), index=False)
print(len(r), "cells; max |d_roe|", np.nanmax(np.abs(r["d_roe"])), "; cells with sig diff", int((r["d_sig"] != 0).sum()),
      "; max |d_win|", np.nanmax(np.abs(r["win"] - r["prof_win"])), "; max |d_sized|", np.nanmax(np.abs(r["sized"] - r["prof_sized"])))
print(r.sort_values("d_roe", key=np.abs, ascending=False).head(5).to_string())
