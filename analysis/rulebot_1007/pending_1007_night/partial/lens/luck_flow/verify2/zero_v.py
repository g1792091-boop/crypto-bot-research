import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
A=pd.read_csv(f"{OUT}/flow_accounts_v.csv")
Z=A[A.trades==0].copy()
def cause(r):
    if r["sub"]==0: return "record_only(XRP)" if r["rec"]>0 else "no_signal"
    if r.get("ENTERED:ok",0)>0: return "entered_open_at_end"
    if r.get("REJECTED:sizing",0)==r["sub"]: return "all_rejected_sizing"
    return "other:"+",".join(f"{c}={int(r[c])}" for c in A.columns if (":" in c) and r[c]>0)
Z["cause"]=Z.apply(cause,axis=1)
# check open positions: entered count vs trades
A["ent"]=A.get("ENTERED:ok",0)
print("accounts where ENTERED > trades (positions open at end):")
X=A[A.ent>A.trades]; print(X.groupby(["run","kind"]).size().to_dict())
# no-signal: did they have RECORD (XRP) rows?
Z["has_xrp_record"]=Z.rec>0
print(Z.groupby(["run","kind","cause"]).size().to_string())
print(Z.groupby(["run","kind","timeframe"]).size().unstack(fill_value=0))
print("no_signal accounts with XRP record rows:",Z[(Z.cause=="no_signal")].shape[0], "of which rec>0 ->", ((Z["sub"]==0)&(Z.rec>0)).sum())
Z[["run","account_id","kind","strategy","timeframe","sub","rec","ENTERED:ok","REJECTED:sizing","cause"]].to_csv(f"{OUT}/zero_trade_v.csv",index=False)
print(Z[Z.cause!="no_signal"][["run","account_id","sub","rec","ENTERED:ok","REJECTED:sizing","cause"]].to_string())
