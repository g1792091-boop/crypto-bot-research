import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
for lab in RUNS:
    s=load(lab,"signal_log"); a=load(lab,"accounts")
    s=s.merge(a[["strategy","timeframe","kind"]].drop_duplicates(),on=["strategy","timeframe"],how="left")
    print(lab); print(pd.crosstab([s.kind,s.status],s.symbol))
    t=load(lab,"trades"); print("trades by symbol",t.symbol.value_counts().to_dict())
    if lab!="v3a":
        lb=load(lab,"live_bars"); print("live_bars cols",lb.columns.tolist(), lb.iloc[:,1].unique()[:10] if lb.shape[1]>1 else '')
