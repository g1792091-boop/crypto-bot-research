import os, numpy as np, pandas as pd
G=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(p):
    d=pd.read_csv(p); d["ts"]=pd.to_datetime(d.timestamp,utc=True); return d.set_index("ts")[["open","high","low","close","volume"]]
for sym in ("btcusd","ethusd","solusd"):
    m=load(f"{G}/data1m/{sym}-1m-ohlcv.csv")
    for tf,mins in (("5m",5),("15m",15)):
        ref=load(f"{G}/data/{sym}-{tf}-ohlcv.csv")
        r=m.resample(f"{mins}min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last"})
        j=r.join(ref,rsuffix="_ref",how="inner")
        hd=(j.high/j.high_ref-1); ld=(j.low/j.low_ref-1)
        print(f"{sym} {tf}: high 1m>ref {int((hd>0).sum())} 1m<ref {int((hd<0).sum())} (mean |d| when !=0: {hd[hd!=0].abs().mean()*100 if (hd!=0).any() else 0:.4f}%, p95 {hd[hd!=0].abs().quantile(.95)*100 if (hd!=0).any() else 0:.4f}%) | low 1m<ref {int((ld<0).sum())} 1m>ref {int((ld>0).sum())} (mean |d| {ld[ld!=0].abs().mean()*100 if (ld!=0).any() else 0:.4f}%)")
        # by date: where are differences concentrated
        dd=(hd!=0)|(ld!=0)
        byday=dd.groupby(j.index.date).mean()
        print("   share of bars with H/L diff by day (top5):", byday.sort_values(ascending=False).head(5).round(3).to_dict())
