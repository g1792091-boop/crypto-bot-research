import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
RUNL = {"run-20261005T183457Z": "v3b", "current": "v4"}

def load_xl(path, variants=None):
    cols = ["run","sig_id","bar_close","timeframe","strategy","symbol","kind","side","flip","variant","status",
            "entry_price","stop_initial","qty","leverage","margin","pnl","fees","funding","exit_reason","exit_time","entry_time","mfe_price","bars_end","atr","ref_price"]
    X = pd.read_csv(path, low_memory=False, usecols=cols)
    if variants is not None:
        X = X[X.variant.isin(variants)]
    b = X[X.variant=="base"][["run","sig_id","flip","status","entry_price","stop_initial","qty"]].rename(
        columns={"status":"b_status","entry_price":"b_entry","stop_initial":"b_stop","qty":"b_qty"})
    X = X.merge(b, on=["run","sig_id","flip"], how="left")
    X = X[X.b_status.isin(["CLOSED","OPEN_END"])].copy()
    X["dist"] = (X.b_entry - X.b_stop).abs()
    ent = X.status.isin(["CLOSED","OPEN_END"])
    X["R"] = np.where(ent, X.pnl/(X.qty*X.dist), np.nan)
    # cost split: fees + funding + slippage (0.02% each side on the raw prices)
    X["feeR"] = np.where(ent, X.fees/(X.qty*X.dist), np.nan)
    X["fundR"] = np.where(ent, X.funding/(X.qty*X.dist), np.nan)
    X["runl"] = X.run.map(RUNL)
    X["open_end"] = (X.status=="OPEN_END").astype(int)
    return X

def cboot(x, cl, B=4000, seed=1):
    x = np.asarray(x, float); cl = np.asarray(cl)
    ok = np.isfinite(x); x = x[ok]; cl = cl[ok]
    if len(x)==0: return dict(n=0,G=0,mean=np.nan,lo=np.nan,hi=np.nan,p=np.nan)
    u, inv = np.unique(cl, return_inverse=True); G = len(u)
    s = np.bincount(inv, weights=x, minlength=G); c = np.bincount(inv, minlength=G).astype(float)
    m = x.mean()
    if G < 3: return dict(n=len(x),G=G,mean=m,lo=np.nan,hi=np.nan,p=np.nan)
    rng = np.random.default_rng(seed)
    w = rng.multinomial(G, np.full(G,1/G), size=B).astype(float)
    bm = (w@s)/(w@c)
    lo, hi = np.percentile(bm, [2.5, 97.5])
    # two-sided bootstrap p (percentile of 0 under recentred distribution)
    bc = bm - bm.mean()
    p = float(np.mean(np.abs(bc) >= abs(m)))
    return dict(n=len(x), G=G, mean=m, lo=lo, hi=hi, p=max(p, 1.0/B))

def bh(p):
    p = np.asarray(p, float); n = len(p); o = np.argsort(p)
    r = p[o]*n/np.arange(1,n+1); q = np.minimum.accumulate(r[::-1])[::-1]
    out = np.empty(n); out[o] = np.minimum(q,1); return out
