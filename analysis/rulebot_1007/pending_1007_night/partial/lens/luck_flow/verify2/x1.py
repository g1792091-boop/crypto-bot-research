import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
for lab in RUNS:
    s=load(lab,"signal_log")
    print("=====",lab,len(s))
    print(pd.crosstab(s.timeframe,s.status))
    print("bar_close span KST", kst(s.bar_close.min()), kst(s.bar_close.max()))
    k=["bar_close","timeframe","strategy","symbol"]
    print("dups(key incl side)",s.duplicated(k+["side"]).sum(),"dups(no side)",s.duplicated(k).sum(), "dup status", s[s.duplicated(k,keep=False)].status.value_counts().to_dict())
    print("dup ids", s.duplicated(["id"]).sum())
    ru=load(lab,"runs")
    for _,x in ru.iterrows():
        dd=json.loads(x.data); print(" run",x.id,kst(x.started_ts), {k:v for k,v in dd.items() if k not in('commit','trading_code','settings','brackets','signal_code','packages','brackets_src','dirty','tag')})
