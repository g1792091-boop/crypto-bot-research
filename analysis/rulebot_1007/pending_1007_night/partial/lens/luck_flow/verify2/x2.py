import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
for lab in RUNS:
    s=load(lab,"signal_log")
    for tf,step in [("15m",15),("30m",30),("1h",60)]:
        b=np.sort(s[s.timeframe==tf].bar_close.unique())
        full=np.arange(b.min(),b.max()+1,step*60000)
        miss=np.setdiff1d(full,b)
        print(lab,tf,"bars with rows",len(b),"of",len(full),"missing",len(miss), [str(kst(m)) for m in miss[:12]])
    eq=load(lab,"equity_hourly"); print(eq.columns.tolist()[:8]); 
    tcol=[c for c in eq.columns if 'ts' in c or 'time' in c or c=='hour']
    print(tcol, kst(eq[tcol[0]].min()), kst(eq[tcol[0]].max()), eq[tcol[0]].nunique())
    o=load(lab,"outcomes"); print("outcomes span",kst(o.step_ts.min()),kst(o.step_ts.max()))
    t=load(lab,"trades"); print("trades exit max", kst(pd.to_numeric(t.exit_time,errors='coerce').max()), "entry max", kst(t.entry_time.max()))
