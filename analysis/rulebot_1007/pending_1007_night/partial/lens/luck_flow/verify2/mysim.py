"""Independent minimal re-implementation of the house exit (2 ATR stop + ROE ladder) on 1m live_bars.
Funding and liquidation ignored. R = (side*(exit-fill) - taker*(fill+exit)) / |fill - stop|."""
import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
TAKER, SLIP = 0.0005, 0.0002
RT = 2*(TAKER+SLIP)
MIN=60000
def bars_by_symbol(lab):
    b=load(lab,"live_bars").sort_values(["symbol","ts"])
    out={}
    for s,g in b.groupby("symbol"):
        out[s]=(g.ts.to_numpy(np.int64),g.open.to_numpy(),g.high.to_numpy(),g.low.to_numpy(),g.close.to_numpy())
    return out
def lock_for(best):
    if best < 0.12-1e-12: return None
    n=np.floor((best-0.12)/0.05+1e-9); return 0.10+0.05*n
def sim(B, sym, bc, side, ref, stop_dist, lev):
    ts,o,h,l,c=B[sym]
    i=np.searchsorted(ts,bc)
    if i>=len(ts) or ts[i]!=bc: return None
    fill=ref*(1+side*SLIP); stop=ref-side*stop_dist; sd=abs(fill-stop)
    mfe=fill; lock=None; mfe_R=0; mae_R=0
    for j in range(i,len(ts)):
        entry_bar=(j==i)
        if side>0: mfe=max(mfe,h[j])
        else: mfe=min(mfe,l[j])
        ex=None
        if not entry_bar and (o[j]-stop)*side<=0: ex=(o[j]*(1-side*SLIP),ts[j])
        elif (l[j]<=stop if side>0 else h[j]>=stop): ex=(stop*(1-side*SLIP),ts[j]+MIN-1)
        fav=(h[j]-fill) if side>0 else (fill-l[j]); adv=(fill-l[j]) if side>0 else (h[j]-fill)
        mfe_R=max(mfe_R,fav/sd); mae_R=min(mae_R,-adv/sd)
        if ex:
            px,t=ex
            R=(side*(px-fill)-TAKER*(fill+px))/sd
            return dict(status="TRADED",R=R,exit_time=t,exit_px=px,reason="LOCK" if lock is not None else "SL",
                        hold_min=(t-bc)/MIN,mfe_R=mfe_R,mae_R=mae_R,cost_R=(TAKER*(fill+px)+SLIP*ref+SLIP*px)/sd)
        if not entry_bar:
            best=lev*(side*(mfe/fill-1)-RT); lk=lock_for(best)
            if lk is not None and (lock is None or lk>lock+1e-12):
                cand=fill*(1+side*(lk/lev+RT))
                stop=max(stop,cand) if side>0 else min(stop,cand); lock=lk
    px=c[-1]
    return dict(status="UNRESOLVED",R=(side*(px-fill)-TAKER*(fill+px))/sd,exit_time=np.nan,reason="OPEN",
                hold_min=(ts[-1]+MIN-bc)/MIN,mfe_R=mfe_R,mae_R=mae_R,cost_R=np.nan)
