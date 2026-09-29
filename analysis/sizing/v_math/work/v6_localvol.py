"""Verifier part 6: break-even drift when the injected drift scales with LOCAL volatility
(trailing 1-day sd of 5m log returns, known at entry), IR measured against that local vol.
Compared with a constant drift measured against the pooled sd (the author's definition)."""
import numpy as np, pandas as pd, sys
sys.path.insert(0, ".")
from v2_sim import load, COINS, MMR, C, FR
YEAR_S = 365*86400; BPY = 365*288
data, lr = {}, []
for s in COINS:
    df = load(s, "5m")
    r = np.log(df.close).diff()
    sl = r.rolling(288, min_periods=200).std().shift(1).values    # known before the entry bar opens
    data[s] = (df.open.values.astype(float), df.high.values.astype(float), df.low.values.astype(float),
               df.ts.values.astype("datetime64[s]").astype(np.int64), sl)
    lr.append(r.values[1:])
sd5 = float(np.std(np.concatenate(lr)))

def trade(o,h,l,t,e,d,L,mu_s):
    P = o[e]; dl = 1/L - MMR; tp = 0.10/L
    up, dn = (P*(1+tp), P*(1-dl)) if d == 1 else (P*(1+dl), P*(1-tp))
    w = 32; a = e; end = min(len(h), e + 25920)
    while a < end:
        b = min(a + w, end); sc = np.exp(d*mu_s*(t[a:b]-t[e])); hh, ll = h[a:b]*sc, l[a:b]*sc
        hit = np.nonzero((hh >= up) | (ll <= dn))[0]
        if len(hit):
            j = a + hit[0]; i = hit[0]; oo = o[j]*sc[i]
            tp_t = (hh[i] >= up) if d == 1 else (ll[i] <= dn); st_t = (ll[i] <= dn) if d == 1 else (hh[i] >= up)
            gap_st = j > e and ((oo <= dn) if d == 1 else (oo >= up)); gap_tp = j > e and ((oo >= up) if d == 1 else (oo <= dn))
            nf = (t[j] + 150)//28800 - t[e]//28800
            if (not gap_st) and (gap_tp or (tp_t and not st_t)):
                return 1, 0.10 - L*C - L*C*((1+tp) if d == 1 else (1-tp)) - L*FR*nf
            return 0, -1.0 - L*C - L*FR*nf
        a = b; w *= 4
    return None

rs = np.random.default_rng(5150)
ent = {}
for s in COINS:
    o,h,l,t,sl = data[s]
    cand = np.where(np.isfinite(sl))[0]; cand = cand[cand < len(o) - 25920]
    ent[s] = np.sort(rs.choice(cand, 2000, replace=False))

def run(L, ir, mode):
    rec = []
    for s in COINS:
        o,h,l,t,sl = data[s]
        for e in ent[s]:
            sig = sd5 if mode == "pooled" else sl[e]
            mu_s = ir*sig/np.sqrt(BPY)/300.0
            for d in (1,-1):
                r = trade(o,h,l,t,int(e),d,L,mu_s)
                if r: rec.append(r)
    R = np.array(rec); return R[:,0].mean(), 100*R[:,1].mean()

for L, grid in ((20, [0, 3, 4, 5, 6, 8, 10]),):
    for mode in ("pooled", "local"):
        xs, ys, ps = [], [], []
        for ir in grid:
            p, er = run(L, ir, mode); xs.append(ir); ys.append(er); ps.append(p)
            print(mode, L, ir, round(p,4), round(er,3), flush=True)
        xs, ys = np.array(xs), np.array(ys)
        k = np.where((ys[:-1] < 0) & (ys[1:] >= 0))[0]
        if len(k):
            k = k[0]; ir0 = xs[k] + (0-ys[k])*(xs[k+1]-xs[k])/(ys[k+1]-ys[k])
            print(f"==> L={L} mode={mode}: break-even IR {ir0:.2f}")
