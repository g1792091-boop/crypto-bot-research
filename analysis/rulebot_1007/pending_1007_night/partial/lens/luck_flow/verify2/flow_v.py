import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
rows=[];acct_rows=[]
DAYS={}
for lab in RUNS:
    s=load(lab,"signal_log"); a=load(lab,"accounts"); o=load(lab,"outcomes")
    b=np.sort(s[s.timeframe=="15m"].bar_close.unique()); days=len(b)*15/1440; DAYS[lab]=days
    sub=s[s.status=="SUBMITTED"]
    cnt=sub.groupby(["strategy","timeframe"]).size().rename("sub")
    rec=s[s.status=="RECORD"].groupby(["strategy","timeframe"]).size().rename("rec")
    A=a.set_index(["strategy","timeframe"]).join(cnt).join(rec).fillna({"sub":0,"rec":0}).reset_index()
    o["key"]=o.status+":"+o.reason.str.slice(0,14)
    oc=o.pivot_table(index="account_id",columns="key",values="id",aggfunc="count",fill_value=0)
    A=A.merge(oc,left_on="account_id",right_index=True,how="left").fillna(0)
    t=load(lab,"trades"); tn=t.groupby("account_id").size().rename("trades")
    A=A.merge(tn,left_on="account_id",right_index=True,how="left").fillna({"trades":0})
    A["run"]=lab; A["days"]=days; acct_rows.append(A)
    for (k,tf),g in A.groupby(["kind","timeframe"]):
        S=g["sub"].sum()
        d=dict(run=lab,kind=k,tf=tf,acc=len(g),days=round(days,4),sub=int(S),sub_acct_day_mean=S/len(g)/days,
               sub_acct_day_median=(g["sub"]/days).median(), acc_with_sig=(g["sub"]>0).sum(),
               sub_per_active_acct_day=S/max((g["sub"]>0).sum(),1)/days)
        for c in oc.columns:
            if c in g: d["sh_"+c]=g[c].sum()/S if S else np.nan
        rows.append(d)
R=pd.DataFrame(rows); pd.set_option("display.width",300); pd.set_option("display.max_columns",30)
print({k:round(v,4) for k,v in DAYS.items()})
print(R.round(3).to_string())
R.to_csv(f"{OUT}/flow_kind_tf_v.csv",index=False)
pd.concat(acct_rows).to_csv(f"{OUT}/flow_accounts_v.csv",index=False)
