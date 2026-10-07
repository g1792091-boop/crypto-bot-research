"""Parity: repl_sim.job on the 5y Binance core signal cache vs the verified lens pickle fy36_<tf>.pkl.gz (v4n columns).
    python3 -I -B parity_5y.py <binance_signals_dir> <lens_out_dir> <tf>
"""
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa
import pandas as pd  # noqa
import repl_sim as S  # noqa

sig, lens, tf = sys.argv[1:4]
T = pd.read_pickle(os.path.join(lens, f"fy36_{tf}.pkl.gz"))
T = T[["strategy", "coin", "ts", "side", "stop_frac", "v4n_lev", "v4n_done", "v4n_R", "v4n_gross"]]
rows = []
for coin in S.COINS:
    _, _, df, _ = S.job((sig, "core", tf, coin, "2021-08-01", "2026-09-30", 0))
    t = T[T.coin == coin]
    m = df.merge(t, on=["strategy", "ts", "side"], how="outer", suffixes=("", "_t"), indicator=True)
    both = m[m._merge == "both"]
    ok = both.v4n_R.notna() & both.v4n_R_t.notna()
    rows.append(dict(coin=coin, mine=len(df), theirs=len(t), both=len(both), lev_agree=(both.v4n_lev == both.v4n_lev_t).mean(),
                     maxdR=float(np.abs(both.v4n_R - both.v4n_R_t)[ok].max()),
                     maxdG=float(np.nanmax(np.abs(both.v4n_gross - both.v4n_gross_t)))))
    print(rows[-1], flush=True)
