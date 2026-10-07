"""Verifier: paired exit variants at 1h/4h from own sims (tf bars and 5m bars).
    python3 -I vexits.py <v_tf_htf_var.pkl> <v_5m_htf.pkl> <out_csv>"""
import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
A, B, OUT = sys.argv[1:4]
DAY = 86_400_000
rows = []
for lab, f in (("tfbars", A), ("5mbars", B)):
    D = pd.read_pickle(f)
    D = D[(D.lev > 0) & D.R.notna()].copy()
    D["tf"] = D.tf.astype(str)
    D["day"] = D.close_ms // DAY
    for tf, g in D.groupby("tf"):
        for v in ("R_lev10", "R_lock30", "R_tp1R", "R_tp2R"):
            for w, wl in ((None, "all"), (0, "is"), (1, "cf")):
                gg = g if w is None else g[g.win == w]
                d = (gg[v] - gg.R).to_numpy(float)
                ok = np.isfinite(d)
                d, day = d[ok], gg.day.to_numpy()[ok]
                m = d.mean()
                s = pd.Series(d - m).groupby(day).sum().to_numpy(); G = len(s)
                se = np.sqrt(G / (G - 1) * (s ** 2).sum()) / len(d)
                rows.append(dict(res=lab, tf=tf, var=v, win=wl, n=len(d), base=gg.R.mean(), variant=gg[v].mean(), diff=m, t=m / se))
P = pd.DataFrame(rows)
P.to_csv(OUT, index=False)
pd.set_option("display.width", 200)
print(P.pivot_table(index=["res", "tf", "var"], columns="win", values=["diff", "t"]).round(3).to_string())
