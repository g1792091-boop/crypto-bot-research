import sys, os, pandas as pd, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bt"))
from portfolio import single_account
R="/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
t=pd.read_csv(os.path.join(R,"trades_ALL_5m_v45g1.csv"))
res=[]
for strat in ("V45_EXACT_AMB_G1","V45_EXACT_AMB"):
  for ex in ("L50_sl15",):
    g0=t[(t.strategy==strat)&(t.exit==ex)].copy(); g0["entry_ts"]=pd.to_datetime(g0.entry_ts,utc=True)
    for sh in range(0,48,1):
      for eh in range(0,48,1):
        a=pd.Timestamp("2026-09-04T00:00",tz="UTC")+pd.Timedelta(hours=sh)
        b=pd.Timestamp("2026-09-12T12:00",tz="UTC")+pd.Timedelta(hours=eh)
        g=g0[(g0.entry_ts>=a)&(g0.entry_ts<b)]
        for mode in ("per_symbol","single"):
          if mode=="per_symbol":
            n=len(g); wr=(g.net>0).mean(); sa=single_account(g,50.0); fin=sa["final"]
          else:
            sa=single_account(g,50.0); n=sa["taken"]; fin=sa["final"]; wr=np.nan
          res.append((strat,mode,str(a),str(b),n,wr,fin))
r=pd.DataFrame(res,columns=["strat","mode","a","b","n","wr","final"])
hit=r[(r.n==59)]
print(hit.sort_values("final").to_string(max_rows=60))
