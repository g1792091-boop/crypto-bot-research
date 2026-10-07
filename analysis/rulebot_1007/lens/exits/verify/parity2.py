import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
my = pd.read_csv(sys.argv[1])
xl = pd.read_csv(sys.argv[2], low_memory=False, usecols=["run","sig_id","flip","variant","status","entry_price","stop_initial","qty","pnl","fees","funding","exit_reason","exit_time","entry_time","lock","timeframe","symbol"])
xb = xl[xl.variant=="base"][["run","sig_id","flip","entry_price","stop_initial"]].rename(columns={"entry_price":"be","stop_initial":"bs"})
xl = xl.merge(xb, on=["run","sig_id","flip"])
xl["Rx_nofund"] = (xl.pnl+xl.funding)/(xl.qty*(xl.be-xl.bs).abs())
m = my.merge(xl, on=["run","sig_id","flip","variant"])
m["d"] = (m.R-m.Rx_nofund).abs()
for v in ["base","geo10","lock30","stopw3","timestop"]:
    g = m[(m.variant==v)&(m.flip==0)]
    f = g.funding!=0
    print(v, "mismatch>0.01 with funding", ((g.d>0.01)&f).sum(), "without funding", ((g.d>0.01)&~f).sum(), "n funding", f.sum())
g = m[(m.variant=="base")&(m.flip==0)&(m.d>0.01)&(m.funding==0)]
print(g[["run","sig_id","timeframe","symbol","R","Rx_nofund","reason","exit_reason","status","hold_min","lock"]].head(15).to_string())
