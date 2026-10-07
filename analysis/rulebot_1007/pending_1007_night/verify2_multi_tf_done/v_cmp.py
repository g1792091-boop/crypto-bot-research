import os, sys
sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
V, res, sig = sys.argv[1:4]
ts15=np.load(os.path.join(sig,"sig_15m_BTCUSD.npz"))["ts"]
lo=np.searchsorted(ts15,pd.Timestamp("2023-11-01").value); hi=np.searchsorted(ts15,pd.Timestamp("2026-09-01").value)
mine=pd.read_csv(os.path.join(V,"v_trades.csv.gz"))
MAP={"A|FC":"A|FC|coin_short","ALL|SWH":"ALL|SWH|long_first","HI|FC":"HI|FC|coin_short","ALL|SW":"ALL|SW|coin_short","ALL|LTF":"ALL|FC|long_first"}
for fn in sorted(os.listdir(res)):
    nm=fn[:-4].split("__",1)[1]
    if nm not in mine.strat.unique(): continue
    z=np.load(os.path.join(res,fn))
    out=[]
    for c,mc in MAP.items():
        e=z[f"{c}|tr|e"]; R=z[f"{c}|tr|R"]; m=(e>=lo)&(e<hi)
        q=mine[(mine.strat==nm)&(mine.combo==mc)]; q=q[(q.e>=lo)&(q.e<hi)]
        a=pd.Series(R[m],index=e[m]); b=q.set_index("e").R
        common=a.index.intersection(b.index)
        out.append(f"{c}: n {m.sum()}/{len(q)} R {R[m].mean():+.4f}/{q.R.mean():+.4f} same-entry {len(common)/max(len(a),1):.3f}")
    print(nm, " | ".join(out))
