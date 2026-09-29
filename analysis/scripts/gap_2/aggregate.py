import os, glob, numpy as np, pandas as pd
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")
pd.set_option("display.width", 320); pd.set_option("display.max_rows", 2000); pd.set_option("display.max_columns", 60)
D = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(OUT, "sign_*.csv")) + glob.glob(os.path.join(OUT, "drift_*.csv")))], ignore_index=True)
D["fwdk"] = np.where(D.k == 16, D.fwd16_pct, D.fwd64_pct)
D["zk"] = np.where(D.k == 16, D.fwd16_z, D.fwd64_z)
BARMIN = {"5m": 5, "15m": 15, "1h": 60}
D["cost_k"] = 0.14 + 0.01 * D.k * D.tf.map(BARMIN) / 480
FAM = ["LADDER2", "TRAIL2", "FIXED9", "TIME16", "TIME64"]

# ---- cell level (seed-averaged)
cell = D.groupby(["tf", "oracle", "k", "dial"]).agg(fwdk=("fwdk", "mean"), fwd16=("fwd16_pct", "mean"), fwd64=("fwd64_pct", "mean"),
                                                     zk=("zk", "mean"), cost_k=("cost_k", "first")).reset_index()
# family-any pass per seed
fam_seed = D.groupby(["tf", "oracle", "k", "dial", "seed", "family"]).agg(anypass=("passed", "max"), maxpf=("pf", "max")).reset_index()
fam = fam_seed.groupby(["tf", "oracle", "k", "dial", "family"]).agg(passrate=("anypass", "mean"), maxpf=("maxpf", "mean")).reset_index()
wide_pr = fam.pivot_table(index=["tf", "oracle", "k", "dial"], columns="family", values="passrate").reset_index()
wide_pf = fam.pivot_table(index=["tf", "oracle", "k", "dial"], columns="family", values="maxpf").reset_index()
W = cell.merge(wide_pr, on=["tf", "oracle", "k", "dial"]).merge(wide_pf, on=["tf", "oracle", "k", "dial"], suffixes=("", "_pf"))
W = W.sort_values(["oracle", "tf", "k", "dial"])
W.to_csv(os.path.join(OUT, "agg_cells.csv"), index=False)
cols = ["tf", "oracle", "k", "dial", "fwdk", "fwd16", "fwd64", "zk", "cost_k"] + FAM + [f + "_pf" for f in FAM]
print("=== seed-averaged cells: family pass rate (any exit of family passes) and mean of family-best PF")
print(W[cols].round(3).to_string(index=False))


# ---- thresholds: smallest dial (as planted fwdk drift) where family pass rate >= 0.5 ; and PF=1.2 crossing
def crossing(x, y, lvl):
    x = np.asarray(x); y = np.asarray(y)
    for i in range(1, len(x)):
        if y[i - 1] < lvl <= y[i]:
            return x[i - 1] + (lvl - y[i - 1]) * (x[i] - x[i - 1]) / (y[i] - y[i - 1])
    if len(y) and y[0] >= lvl:
        return x[0]
    return np.nan


rows = []
for (tf, orc, k), g in W.groupby(["tf", "oracle", "k"]):
    g = g.sort_values("dial")
    r = dict(tf=tf, oracle=orc, k=k, cost_k=g.cost_k.iloc[0], max_fwdk_tested=g.fwdk.max())
    for f in FAM:
        ok = g[g[f] >= 0.5]
        r[f"{f}_first50"] = ok.fwdk.iloc[0] if len(ok) else np.nan
        ok1 = g[g[f] > 0]
        r[f"{f}_firstany"] = ok1.fwdk.iloc[0] if len(ok1) else np.nan
        r[f"{f}_pf12x"] = crossing(g.fwdk.values, g[f + "_pf"].values, 1.2)
    # gate: mean z >= 3.2 (~Bonferroni 0.05/60) and fwdk > cost
    okz = g[g.zk >= 3.2]
    r["gate_z3.2_first"] = okz.fwdk.iloc[0] if len(okz) else np.nan
    r["z_at_dial0"] = g[g.dial == 0].zk.mean() if (g.dial == 0).any() else np.nan
    rows.append(r)
T = pd.DataFrame(rows)
T.to_csv(os.path.join(OUT, "agg_thresholds.csv"), index=False)
print("\n=== thresholds expressed as planted forward drift at horizon k (%), seed-averaged")
print(T.round(3).to_string(index=False))

# ---- null calibration: dial==0
Z = D[D.dial == 0].groupby(["tf", "oracle", "k", "seed"]).agg(z16=("fwd16_z", "first"), z64=("fwd64_z", "first"), anypass=("passed", "max")).reset_index()
print("\n=== dial=0 (no edge): z values and any-pass (should be ~N(0,1) and False)")
print(Z.round(2).to_string(index=False))
# per-exit pass count at dial 0 across all
print("dial0 per-exit passes:", D[(D.dial == 0) & D.passed].groupby(["tf", "exit"]).size().to_dict())
