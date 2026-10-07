import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
rs = pd.read_csv(sys.argv[1], low_memory=False)
my = pd.read_csv(sys.argv[2])
xl = pd.read_csv(sys.argv[3], low_memory=False, usecols=["run","sig_id","flip","variant","status","entry_price","stop_initial","qty","pnl","fees","funding","exit_reason","kind","timeframe"])
# 1. base vs replay (TRADED)
b = my[(my.variant=="base")&(my.flip==0)].merge(rs[["run","sig_id","status","R","funding","exit_reason","kind","timeframe","qty","entry_price","stop_initial"]], on=["run","sig_id"])
t = b[b.status=="TRADED"]
d = (t.R_x - t.R_y).abs()
print("base vs replay TRADED n", len(t), "max|dR|", d.max(), "share<1e-6", (d<1e-6).mean(), "n with funding!=0", (t.funding!=0).sum())
print(" mismatches without funding:", ((d>1e-6)&(t.funding==0)).sum())
print(" reason agreement (SL/LOCK):", (t.reason.str.replace("STOPGAP","X") == t.exit_reason).mean())
print(t[(d>1e-6)&(t.funding==0)][["run","sig_id","R_x","R_y","reason","exit_reason"]].head())
u = b[b.status=="UNRESOLVED"]
print("UNRESOLVED in replay -> my reason", u.reason.value_counts().to_dict())
# 2. my variants vs exitlab variants (R in base-stop units, exitlab: pnl/(qty*|entry-stop|) of base)
xb = xl[xl.variant=="base"][["run","sig_id","flip","entry_price","stop_initial"]].rename(columns={"entry_price":"be","stop_initial":"bs"})
xl = xl.merge(xb, on=["run","sig_id","flip"])
xl["Rx"] = xl.pnl/(xl.qty*(xl.be-xl.bs).abs())
xl["Rx_nofund"] = (xl.pnl+xl.funding)/(xl.qty*(xl.be-xl.bs).abs())
m = my.merge(xl[["run","sig_id","flip","variant","Rx","Rx_nofund","status","exit_reason"]], on=["run","sig_id","flip","variant"], how="inner")
for v,g in m.groupby(["variant","flip"]):
    dd = (g.R - g.Rx_nofund).abs()
    print(f"{v[0]:12s} flip{v[1]} n {len(g):5d} share|dR|<1e-6 {np.mean(dd<1e-6):.4f} <0.01 {np.mean(dd<0.01):.4f} max {dd.max():.3g}  mean my {g.R.mean():+.4f} xl {g.Rx.mean():+.4f}")
