"""Pre-registered splits (per pull, first 9.2 months) + post-hoc descriptives from the frozen primary trade file."""
import json, numpy as np, pandas as pd
T=pd.read_csv("../out/OOS_primary_primary_trades.csv"); R=json.load(open("../out/OOS_primary_result.json"))
IS=json.load(open("../out/IS_validation_result.json")); TI=pd.read_csv("../out/IS_validation_primary_trades.csv")
T["ts"]=pd.to_datetime(T.signal_ts,utc=True)
def st(x):
    x=np.asarray(x); loss=-x[x<=0].sum()
    return dict(n=len(x), exp_pct=round(x.mean()*100,4), pf=round(x[x>0].sum()/loss,3), t=round(x.mean()/(x.std(ddof=1)/np.sqrt(len(x))),2))
def pos(df): return int(sum(g.net.sum()>0 for _,g in df.groupby("symbol")))
b1=pd.Timestamp("2025-08-06T05:15Z"); b2=pd.Timestamp("2025-12-23T02:35Z")
print("== pre-registered splits ==")
for name,m in (("p3 2025-03-20..08-06",T.ts<b1),("p2 2025-08-06..12-23",(T.ts>=b1)&(T.ts<b2)),("p1 2025-12-23..2026-05-12",T.ts>=b2),("first 9.2 months p1+p2",T.ts>=b1),("ALL",T.ts>=T.ts.min())):
    d=T[m]; print(f"{name:28s}", st(d.net), "pos", pos(d), "/3")
print("== side split (descriptive) ==")
for s in (1,-1): print("OOS side",s, st(T.net[T.side==s])); 
for s in (1,-1): print("IS  side",s, st(TI.net[TI.side==s]))
print("long share OOS", round((T.side>0).mean(),3), "IS", round((TI.side>0).mean(),3))
print("== post-hoc: excluding 2025-03/04 (tariff crash) ==", st(T.net[T.ts>=pd.Timestamp('2025-05-01T00:00Z')]), "pos", pos(T[T.ts>=pd.Timestamp('2025-05-01T00:00Z')]))
print("months positive:", sum(g.net.sum()>0 for _,g in T.groupby(T.signal_ts.str[:7])), "/", T.signal_ts.str[:7].nunique())
# effect-size inference (excess over the common-shift null mean, SD from null reps)
oos_x=R["primary"]["exp_pct"]-R["null_mean_exp"]; oos_sd=R["null_sd_exp"]
is_x=IS["primary"]["exp_pct"]-IS["null_mean_exp"]; is_sd=IS["null_sd_exp"]
print(f"IS excess {is_x:+.4f} (sd {is_sd:.4f});  OOS excess {oos_x:+.4f} (sd {oos_sd:.4f})")
print(f"OOS rejects full IS excess at z={(is_x-oos_x)/oos_sd:.2f}; half IS excess at z={(is_x/2-oos_x)/oos_sd:.2f}")
print(f"OOS 95% one-sided upper bound on excess: {oos_x+1.645*oos_sd:+.4f}%  -> net/trade upper bound {R['null_mean_exp']+oos_x+1.645*oos_sd:+.4f}%")
w1,w2=1/is_sd**2,1/oos_sd**2; pooled=(w1*is_x+w2*oos_x)/(w1+w2); psd=(w1+w2)**-0.5
print(f"inverse-variance pooled IS+OOS excess {pooled:+.4f} +- {psd:.4f}  z={pooled/psd:.2f}")
print(f"IS-vs-OOS difference z={(is_x-oos_x)/np.hypot(is_sd,oos_sd):.2f}")
# forward drift comparison
print("fwd64 pooled IS", round(IS['secondary']['forward64']['pooled_fwd64_mean_pct'],4), "OOS", round(R['secondary']['forward64']['pooled_fwd64_mean_pct'],4))
print("signals/30d IS", round(1641/ (40000*5/1440/30),1), " OOS", round(sum(v['signals'] for k,v in R['secondary']['forward64'].items() if k!='pooled_fwd64_mean_pct')/(120000*5/1440/30),1))
print("meta", json.dumps({k:{kk:v[kk] for kk in ('n','first','last','gaps5','signals_after_warmup','long_share')} for k,v in R['meta'].items()}))
