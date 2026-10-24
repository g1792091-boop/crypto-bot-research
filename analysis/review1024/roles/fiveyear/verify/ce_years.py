"""Add-on to ce_costs.py: B_sel_with20 CONF taken trades (study path, base costs) per year with/without payback,
compounded account final multiple with payback at margins 0.05-0.4, growth-optimal margin with payback.
    python3 ce_years.py"""
import os, sys
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FY)
import fy_common
fy_common.SHM = "/dev/shm/claude_verify_ce"
import goalpath as GP
from cellsig import *
from ce_costs import specs_B
PBR = 35.0 * PAYBACK
S = GP.bot_rows(specs_B())
o, T = GP.read(S, "CONF")
print("CONF trades", len(T), "mean", round(T.w35_roe.mean(), 5), "pb", round(T.w35_roe.mean() + PBR, 5))
y = pd.to_datetime(T.t, unit="ms", utc=True).dt.year
g = T.assign(y=y).groupby("y").w35_roe.agg(["size", "mean"])
g["mean_pb"] = g["mean"] + PBR
print(g.round(4).to_string())
for m in (0.05, 0.1, 0.2, 0.4):
    a = RD.account(T.assign(w35_roe=T.w35_roe + PBR), "w35", margin=m)
    b = RD.account(T, "w35", margin=m)
    print(f"margin {m}: final x with payback {a['final_x']:.4g} (max dd {a['max_dd']:.2f}); raw {b['final_x']:.4g}")
print("growth-opt margin with payback:", GP.growth_opt(T.w35_roe.to_numpy() + PBR, o["per_day"]))
x = T.w35_roe.to_numpy() + PBR
print("mean log growth per trade at margin 0.4 with payback:", np.mean(np.log1p(0.4 * np.maximum(x, -1))))
print("ROE distribution (raw): stops -50%:", round((T.w35_roe <= -0.4999).mean(), 4), " quantiles",
      np.round(np.quantile(T.w35_roe, [0.1, 0.25, 0.5, 0.75, 0.9]), 3))
