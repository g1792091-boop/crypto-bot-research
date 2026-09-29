import sys, os, pandas as pd, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bt"))
from portfolio import single_account
R="/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
t=pd.read_csv(os.path.join(R,"trades_ALL_5m_v45g1.csv"))
g0=t[(t.strategy=="V45_EXACT_AMB_G1")&(t.exit=="L50_sl15")].copy(); g0["entry_ts"]=pd.to_datetime(g0.entry_ts,utc=True)
best=[]
for sh in range(0,72):
  for eh in range(0,72):
    a=pd.Timestamp("2026-09-04T00:00",tz="UTC")+pd.Timedelta(hours=sh); b=pd.Timestamp("2026-09-12T00:00",tz="UTC")+pd.Timedelta(hours=eh)
    g=g0[(g0.entry_ts>=a)&(g0.entry_ts<b)]
    for fee in (0.0005,0.0001):
      gg=g.copy(); gg["net"]=gg.net+2*(0.0005-fee)
      sa=single_account(gg,50.0)
      best.append((str(a),str(b),fee,len(g),(gg.net>0).mean(),sa["taken"],sa["final"]))
r=pd.DataFrame(best,columns=["a","b","fee","n","wr","taken","final"])
print(r[(r.final.between(370,390))].head(20).to_string())
print(r[(r.n==59)&(r.final.between(300,460))].head(20).to_string())
