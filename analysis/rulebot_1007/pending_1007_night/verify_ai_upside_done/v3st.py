"""verify3 stats. python3 -I v3st.py <v3sig.csv> <replay_signals.csv>"""
import sys, site
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd

MIN = 60_000
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
rng = np.random.default_rng(7)


def ctest(d, cl, B=4000):
    d = np.asarray(d, float); cl = np.asarray(cl)
    u, inv = np.unique(cl, return_inverse=True)
    s = np.bincount(inv, d); n = len(d); obs = d.mean()
    flips = rng.choice([-1, 1], size=(B, len(u)))
    p2 = (np.abs(flips @ s / n) >= abs(obs) - 1e-12).mean()
    bs = [s[ix].sum() / np.bincount(inv, minlength=len(u))[ix].sum()
          for ix in (rng.integers(0, len(u), len(u)) for _ in range(2000))]
    return obs, np.percentile(bs, 2.5), np.percentile(bs, 97.5), p2, len(u)


def bh(p):
    p = np.asarray(p, float); n = len(p); o = np.argsort(p)
    q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n); out[o] = np.minimum(q, 1); return out


R = pd.read_csv(sys.argv[1])
RP = pd.read_csv(sys.argv[2], usecols=["sig_id", "run", "status", "R", "mark_R"])
RP["run"] = np.where(RP["run"].str.startswith("run-20261005T18"), "v3b", "v4")
RP["Rref"] = RP["R"].fillna(RP["mark_R"])
m = R.merge(RP[["run", "sig_id", "Rref"]], on=["run", "sig_id"], how="left")
ok = R["base_st"].isin(["T", "U"])
print("parity n", ok.sum(), "maxdiff", np.nanmax(np.abs(m.loc[ok, "base_R"] - m.loc[ok, "Rref"])))
R = R[ok & (R["kind"].isin(["strategy", "ds200"]))].copy()
R["cl"] = R["run"] + "|" + (R["bar_close"] // (np.maximum(R["timeframe"].map(TFM), 60) * MIN)).astype(str)
R["PART1_R"] = 0.5 * (R["base_R"] + R["TP1_R"])
open4 = R["base_u4"].notna()
R["DEEP4_R"] = np.where(open4 & (R["base_u4"] <= -0.5), R["X4_R"], R["base_R"])
rows = []
for (k, tf), g in R.groupby(["kind", "timeframe"]):
    for r in ["CUT05", "CUT05C", "NP4", "NP8", "BE05", "TP1", "PART1", "OPP", "OPPH", "DEEP4"]:
        d = (g[f"{r}_R"] - g["base_R"]).to_numpy()
        f = np.isfinite(d)
        obs, lo, hi, p, nc = ctest(d[f], g["cl"].to_numpy()[f])
        rows.append(dict(kind=k, tf=tf, rule=r, n=f.sum(), base=g["base_R"].mean(), diff=obs, lo=lo, hi=hi, p=p, ncl=nc,
                         v3b=(g[f"{r}_R"] - g["base_R"])[g.run == "v3b"].mean(),
                         v4=(g[f"{r}_R"] - g["base_R"])[g.run == "v4"].mean()))
T = pd.DataFrame(rows)
fam = T["rule"] != "DEEP4"
T.loc[fam, "q"] = bh(T.loc[fam, "p"])
T.to_csv(sys.argv[1].replace("v3sig.csv", "v3rules.csv"), index=False)
pd.set_option("display.width", 200)
print(T[T.tf.isin(["15m", "30m", "1h"])].round(3).to_string(index=False))
