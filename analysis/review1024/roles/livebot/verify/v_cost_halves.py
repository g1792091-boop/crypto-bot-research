"""Per-half check of the 'vs B0' per-trade gap (confirm 2024-01..2025-06 vs late 2025-07..2026-10-05) and the account
view (mean daily log growth at 40 % margin, all calendar days) from the study's trade files, base costs.
Run: python3 verify/v_cost_halves.py <trades_dir>"""
import os
import sys

import numpy as np
import pandas as pd

TD = sys.argv[1]
DAY = 86_400_000
PB = 2 * 0.9 * 0.00042


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


H = {"confirm": (ms("2024-01-01"), ms("2025-07-01")), "late": (ms("2025-07-01"), ms("2026-10-05 15:00")),
     "both": (ms("2024-01-01"), ms("2026-10-05 15:00"))}
V = ["B0", "B3", "B4", "B5", "B6", "B9", "W3"]
T = {v: pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")) for v in V}
rows = []
for hn, (a, b) in H.items():
    nd = int((b - a) // DAY) + 1
    pk = np.random.default_rng(7).integers(0, nd, (5000, nd))
    sub = {v: T[v][(T[v].t >= a) & (T[v].t < b)] for v in V}

    def daily(D, col="tb_roe", pb=False):
        r = np.maximum(D[col].to_numpy(float), -1)
        if pb:
            r = r + np.where(D.coin.to_numpy() == 0, 40, 30) * PB
        di = (D.t.to_numpy(np.int64) // DAY - a // DAY).astype(int)
        return (np.bincount(di, D[col].to_numpy(float), nd), np.bincount(di, minlength=nd),
                np.bincount(di, np.log(np.maximum(1 + 0.4 * r, 1e-9)), nd))
    s0, c0, l0 = daily(sub["B0"])
    for v in V:
        sV, cV, lV = daily(sub[v])
        _, _, lVp = daily(sub[v], pb=True)
        _, _, l0p = daily(sub["B0"], pb=True)
        d = sV[pk].sum(1) / np.maximum(cV[pk].sum(1), 1) - s0[pk].sum(1) / np.maximum(c0[pk].sum(1), 1)
        rows.append(dict(half=hn, variant=v, n=int(cV.sum()), roe=sV.sum() / cV.sum(), vs_b0=sV.sum() / cV.sum() - s0.sum() / c0.sum(),
                         vs_b0_p=np.nan if v == "B0" else (d <= 0).mean(), daylog=lV.mean(), daylog_pb=lVp.mean(),
                         final_x_40=float(np.exp(lV.sum())), final_x_40_pb=float(np.exp(lVp.sum()))))
R = pd.DataFrame(rows)
R.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "v_cost_halves.csv"), index=False, float_format="%.5g")
with pd.option_context("display.width", 200):
    print(R.to_string())
