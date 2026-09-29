import sys, numpy as np, pandas as pd
sys.path.insert(0,"."); sys.path.insert(0,"../bt")
from posctrl3 import load_tf, exits, run_cell
from engine import ExitCfg
dfs=load_tf("5m")
cfgs=[c for c in exits() if c.name in ("L50_sl15","L50_sl20","F_sl2.0_tp3.0","TIME64")]
rows=[]
for seed in range(8):
    r,T=run_cell("5m",dfs,"sign",6,0.8,seed,0.045,20,cfgs)
    # measure fwd6 hit on taken TIME64 trades is not needed; record rows
    rows+=r
d=pd.DataFrame(rows)
g=d.groupby("exit").agg(pf_mean=("pf","mean"),pf_min=("pf","min"),pf_max=("pf","max"),pass_rate=("passed","mean"),net=("exp_net","mean"),trades=("trades","mean"))
print(g.round(3).to_string()); print("fwd16",d.fwd16_pct.mean().round(3),"fwd64",d.fwd64_pct.mean().round(3))
d.to_csv("../out/k6q08.csv",index=False)
