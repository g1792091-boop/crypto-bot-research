"""Verifier -- step 6: per-cell SELECT / CONFIRM reads of the 20 B cells recomputed from the signal rows (own month-
clustered t), compared with shortlist.csv, to confirm the membership numbers are SELECT-only and match the rows.
    python3 tz_b_cells.py <workdir>"""
import os
import sys
import numpy as np
import pandas as pd
WD = sys.argv[1]
VH = os.path.dirname(os.path.abspath(__file__))
S = pd.read_pickle(os.path.join(WD, "B_rows.pkl"))
SL = pd.read_csv(os.path.join(os.path.dirname(VH), "shortlist.csv"))
SL = SL[SL.cond == "W"].reset_index(drop=True)
ms = lambda s: int(pd.Timestamp(s, tz="UTC").value // 10**6)
P = {"SEL": (ms("2021-01-01"), ms("2024-01-01")), "CONF": (ms("2024-01-01"), ms("2026-10-01"))}
d = pd.to_datetime(S.t, unit="ms", utc=True)
S["mon"] = (d.dt.year - 2021) * 12 + d.dt.month - 1
print("dup signals across cells:", int(S.duplicated(["coin", "e", "side", "name", "tf"]).sum()))


def ct(x, g):
    N = len(x)
    mu = x.mean()
    u = pd.Series(x - mu).groupby(g).sum().to_numpy()
    M = len(u)
    var = (u ** 2).sum() / N ** 2 * M / max(M - 1, 1)
    return mu, mu / np.sqrt(var), M


rows = []
for i, r in SL.iterrows():
    cell = f"{r['name']}@{r.etf}|{r.source}@{r.htf}|W"
    o = {"cell": cell}
    for per, (a, b) in P.items():
        q = S[(S.cell == cell) & (S.t >= a) & (S.t < b)]
        mu, t, M = ct(q.w35_roe.to_numpy(), q.mon.to_numpy())
        o.update({f"{per}_n": len(q), f"{per}_n_sl": r[f"{per}_n"], f"{per}_m": round(mu, 5),
                  f"{per}_m_sl": r[f"{per}_m"], f"{per}_t": round(t, 3), f"{per}_t_sl": r[f"{per}_t"],
                  f"{per}_M": M, f"{per}_M_sl": r[f"{per}_M"]})
    rows.append(o)
D = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(D.to_string())
for per in P:
    print(per, "n equal", int((D[f"{per}_n"] == D[f"{per}_n_sl"]).sum()), "/20; mean equal",
          int(np.isclose(D[f"{per}_m"], D[f"{per}_m_sl"], atol=1e-4).sum()), "/20; t equal",
          int(np.isclose(D[f"{per}_t"], D[f"{per}_t_sl"], atol=2e-3).sum()), "/20")
