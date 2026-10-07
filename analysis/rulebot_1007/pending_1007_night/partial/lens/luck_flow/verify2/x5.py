import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
A=pd.read_csv(f"{OUT}/flow_accounts_v.csv")
A["d"]=A["ENTERED:ok"]-A["trades"]; print(A.groupby(["run","d"]).size())
M=pd.read_csv(f"{OUT}/rate_vs5y_v.csv")
z=M[(M["sub"]==0)]
print(z.sort_values("p_le")[["kind","strategy","timeframe","days","per_day","n_signals","p_le"]].round(4).to_string())
# per run no-signal accounts with Poisson p
Z=pd.read_csv(f"{OUT}/zero_trade_v.csv")
ref=M[["kind","strategy","timeframe","per_day"]]
Zs=Z[Z.cause=="no_signal"].merge(ref,on=["kind","strategy","timeframe"],how="left")
Zs["days"]=Zs.run.map({"v3a":2.5938,"v3b":0.6979,"v4":1.5})
Zs["p0"]=np.exp(-Zs.per_day*Zs.days)
print("no-signal account-runs with P(0)<0.1:"); print(Zs[Zs.p0<0.1][["run","account_id","per_day","p0"]].round(4).to_string())
print("min p0 by kind", Zs.groupby("kind").p0.min())
