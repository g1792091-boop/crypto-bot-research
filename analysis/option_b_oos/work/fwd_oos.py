"""Descriptive (post-hoc): forward.py's forward_stats for V45_EXACT_AMB (+G1) on OOS vs IS 5m data."""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bt"))
import strategies as S
from run import load_csv
from forward import forward_stats, HORIZONS
rows=[]
for tag,dd in (("IS","../data_is"),("OOS","../data_oos")):
    for sym in ("BTCUSD","ETHUSD","SOLUSD"):
        d5=load_csv(f"{dd}/{sym.lower()}-5m-ohlcv.csv",5); d15=load_csv(f"{dd}/{sym.lower()}-15m-ohlcv.csv",15)
        for name,fn in (("V45_EXACT_AMB",S.v45_exact_amb),("V45_EXACT_AMB_G1",S.v45_exact_amb_g1)):
            l,s=fn(d5,d15); l=np.asarray(l,bool); s=np.asarray(s,bool)&~l
            r=forward_stats(d5,l,s,0,len(d5)); r.update(window=tag,symbol=sym,strategy=name); rows.append(r)
R=pd.DataFrame(rows)
g=R.groupby(["window","strategy"])
out=pd.DataFrame({"signals":g.signals.sum(),**{f"fwd{h}":g.apply(lambda x,h=h: np.average(x[f"fwd{h}_mean_pct"],weights=x.signals)) for h in HORIZONS}})
pd.set_option("display.width",200); print(out.round(4).to_string())
print(R[R.strategy=="V45_EXACT_AMB"][["window","symbol","signals","fwd16_mean_pct","fwd64_mean_pct","fwd64_t"]].round(3).to_string(index=False))
R.to_csv("../out/fwd_is_oos.csv",index=False)
