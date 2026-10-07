"""91-day-window drawdowns at a fixed 2% risk per trade (raw and with each strategy's mean R removed = the noise a
zero-edge trader would still see). python3 -I -B dd_quarter.py <core_sig_dir> <res_dir> <out_csv>"""
import os, sys
sys.path[:0] = ['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
core, res, out = sys.argv[1:4]
ts15 = np.load(os.path.join(core, "sig_15m_BTCUSD.npz"))["ts"]
START = pd.Timestamp("2021-08-01").value
W = 91 * 86400 * 10**9
COMBOS = ["A|FC", "A|SWH", "A|SW", "A|LTF", "HI|SWH", "ALL|FC", "ALL|LTF", "ALL|SWH", "ALL|SW", "HI|FC", "T15|FC", "T30|FC", "T1h|FC", "T4h|FC", "ALLINF|FC"]
def mdd(R, risk=0.02):
    if not len(R): return np.nan
    eq = np.concatenate([[1.0], np.cumprod(np.maximum(1 + risk * R, 1e-9))])
    return float(np.max(1 - eq / np.maximum.accumulate(eq)))
rows = []
for fn in sorted(os.listdir(res)):
    name = fn[:-4].replace("__", ":", 1)
    z = np.load(os.path.join(res, fn))
    for cb in COMBOS:
        if f"{cb}|tr|R" not in z.files: continue
        R = z[f"{cb}|tr|R"].astype(float); e = z[f"{cb}|tr|e"]; xe = z[f"{cb}|tr|xe"]
        o = np.argsort(xe, kind="stable"); R, e = R[o], e[o]
        w = (ts15[e] - START) // W
        mu = R.mean()
        sd = R.std()
        for k in np.unique(w):
            m = w == k
            if m.sum() < 5: continue
            rows.append(dict(strategy=name, grp="core" if name.startswith("C:") else "ds", combo=cb, window=int(k),
                             n=int(m.sum()), sumR=float(R[m].sum()), dd_raw=mdd(R[m]), dd_demeaned=mdd(R[m] - mu), dd1_raw=mdd(R[m], 0.01), dd1_demeaned=mdd(R[m] - mu, 0.01), sdR=sd))
d = pd.DataFrame(rows); d.to_csv(out, index=False)
g = d.groupby(["grp", "combo"]).agg(windows=("n", "size"), trades_per_window=("n", "median"), sumR_median=("sumR", "median"),
    dd_raw_median=("dd_raw", "median"), dd_raw_p90=("dd_raw", lambda x: x.quantile(0.9)),
    dd_demeaned_median=("dd_demeaned", "median"), dd_demeaned_p90=("dd_demeaned", lambda x: x.quantile(0.9)),
    share_windows_pos=("sumR", lambda x: (x > 0).mean()), dd1_raw_median=("dd1_raw", "median"), dd1_demeaned_median=("dd1_demeaned", "median"), dd1_demeaned_p90=("dd1_demeaned", lambda x: x.quantile(0.9)), dd1_demeaned_gt25=("dd1_demeaned", lambda x: (x > 0.25).mean()), sdR=("sdR", "median"))
print(g.round(3).to_string())
g.to_csv(out.replace(".csv", "_summary.csv"))
