"""Integrity of Astral 1m files + agreement of 1m->5m/15m resamples with the delivered 5m/15m CSVs."""
import os, numpy as np, pandas as pd
G=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(p):
    d=pd.read_csv(p); d["ts"]=pd.to_datetime(d.timestamp,utc=True); return d.set_index("ts")[["open","high","low","close","volume"]]
rows=[]
for sym in ("btcusd","ethusd","solusd"):
    m=load(f"{G}/data1m/{sym}-1m-ohlcv.csv")
    dt=m.index.to_series().diff().dt.total_seconds().div(60).dropna()
    bad=((m.high<m[["open","close"]].max(axis=1))|(m.low>m[["open","close"]].min(axis=1))).sum()
    print(f"{sym}: n={len(m)} {m.index[0]} -> {m.index[-1]} gaps(!=1min)={(dt!=1).sum()} maxgap={dt.max():.0f} dup={m.index.duplicated().sum()} ohlc_viol={bad} flat(o=h=l=c)={((m.high==m.low)).sum()} vol0={(m.volume<=0).sum()}")
    for tf,mins in (("5m",5),("15m",15)):
        ref=load(f"{G}/data/{sym}-{tf}-ohlcv.csv")
        r=m.resample(f"{mins}min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
        cnt=m.resample(f"{mins}min",label="left",closed="left").size()
        r=r[cnt==mins]  # only complete buckets
        j=r.join(ref,rsuffix="_ref",how="inner")
        out=dict(sym=sym,tf=tf,complete_buckets=len(r),matched=len(j),ref_bars_in_span=int(((ref.index>=r.index[0])&(ref.index<=r.index[-1])).sum()))
        for k in ("open","high","low","close"):
            rel=(j[k]/j[k+"_ref"]-1).abs()
            out[f"{k}_exact"]=float((rel==0).mean()); out[f"{k}_maxrel"]=float(rel.max())
        out["vol_ratio_median"]=float((j.volume/j.volume_ref).median())
        rows.append(out)
df=pd.DataFrame(rows); pd.set_option("display.width",250); print(df.to_string(index=False))
