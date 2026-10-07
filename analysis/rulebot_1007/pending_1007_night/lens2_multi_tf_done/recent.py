"""Cost and R of the last 91 days of the 5-year data (entries 2026-07-01..09-29) vs the whole window.
python3 -I -B recent.py <core_sig_dir> <res_dir>"""
import os, sys
sys.path[:0] = ['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
core, res = sys.argv[1:3]
ts15 = np.load(os.path.join(core, "sig_15m_BTCUSD.npz"))["ts"]
cut = pd.Timestamp("2026-07-01").value
acc = {}
for fn in sorted(os.listdir(res)):
    grp = "core" if fn.startswith("C__") else "ds"
    z = np.load(os.path.join(res, fn))
    for cb in ["A|FC", "A|SWH", "ALL|FC", "ALL|SWH", "HI|FC", "T15|FC", "T30|FC", "T1h|FC", "T4h|FC"]:
        if f"{cb}|tr|R" not in z.files: continue
        R = z[f"{cb}|tr|R"].astype(float); G = z[f"{cb}|tr|gross"].astype(float); e = z[f"{cb}|tr|e"]
        m = ts15[e] >= cut
        a = acc.setdefault((grp, cb), [0, 0.0, 0.0, 0, 0.0, 0.0])
        a[0] += m.sum(); a[1] += R[m].sum(); a[2] += (G[m] - R[m]).sum()
        a[3] += len(R); a[4] += R.sum(); a[5] += (G - R).sum()
rows = [dict(grp=k[0], combo=k[1], n_recent=v[0], meanR_recent=v[1] / v[0], cost_recent=v[2] / v[0],
             n_all=v[3], meanR_all=v[4] / v[3], cost_all=v[5] / v[3]) for k, v in acc.items()]
d = pd.DataFrame(rows); print(d.round(3).to_string()); d.to_csv("summ/recent_cost.csv", index=False)
