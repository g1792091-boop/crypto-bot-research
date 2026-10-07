import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
for lab in RUNS:
    a=load(lab,"accounts")
    print("=====",lab,len(a)); print(pd.crosstab(a.kind,a.timeframe))
    print("parent nonnull",a.parent.notna().sum(), "dup acct ids", a.account_id.duplicated().sum())
    print("acct strategy@tf != id:", (a.strategy+"@"+a.timeframe!=a.account_id).sum(), a[a.strategy+"@"+a.timeframe!=a.account_id].account_id.head(5).tolist())
    print(a.data.str.slice(0,80).value_counts().head(8))
    o=load(lab,"outcomes")
    print(pd.crosstab(o.status+":"+o.reason, o.sig_timeframe))
    print("outcome dup (acct,sig_ts,symbol,strategy)", o.duplicated(["account_id","sig_ts","sig_symbol","sig_strategy_id","sig_timeframe"]).sum())
