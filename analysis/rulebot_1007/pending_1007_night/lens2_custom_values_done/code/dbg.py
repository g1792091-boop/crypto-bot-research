import os,sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvlib as C, numpy as np
L=C._lc()
b,z=C.load_npz('1h','BTCUSD'); df=C.frame(b,'1h')
E=L.entries(df.copy(),'1h',coin='BTCUSD')
mine=C.strategy_signal('F6_VWAP_CROSS',0,df,'1h'); lg,sh=E['F6_VWAP_CROSS']; ref=np.where(lg,1,np.where(sh,-1,0))
bad=np.flatnonzero(mine!=ref); print(bad, mine[bad], ref[bad], b['ts'][bad].astype('datetime64[ns]'), b['atr'][bad])
import pandas as pd
fg=L.env()['fg']; atr=fg.atr(df,14).to_numpy(float); print(atr[bad])
sys.path.insert(0, os.path.join(C.REPO, "research", "exitstyle")); sys.path.insert(0, os.path.join(C.REPO, "research", "levstop"))
import exitstyle as XS
for tf in C.TFS:
    b, z = C.load_npz(tf, "ETHUSD"); sg = z["s__N23_HA_ST"]; idx = np.flatnonzero(sg != 0); idx = idx[(idx > 5000) & (idx < len(sg) - 5000)][:3000]
    side = sg[idx].astype(np.int64); n=len(b['ts']); f_bar = C.FUNDING_8H * C.TF_MIN[tf] / 480.0
    r = XS.scan(b, idx, side, np.full(len(idx), 20.0), np.full(len(idx), 0.999), 4096, n, f_bar, 2.0, tp_r=None, ladder=True)
    dn, held, rn, rg, npct = C.outcomes(b, idx, side, tf, 2.0, "house")
    ok = r["done"] & dn & (r['roe']>-0.999)
    print(tf, ok.sum(), np.max(np.abs(r["roe"][ok] - 20 * npct[ok])), (20*npct[dn]<-1).sum())
