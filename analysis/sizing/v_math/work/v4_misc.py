"""Verifier part 4: MAE-based liquidation odds, time-of-day dependence of the zero-edge baseline,
stop-0.5 variant, 100-trade binomial medians and Kelly thresholds."""
import numpy as np, pandas as pd, sys
from scipy.stats import binom
sys.path.insert(0, ".")
from v2_sim import load, COINS, MMR, C, FR, sim_one, cluster_boot

# 1) P(adverse excursion >= d_liq within H bars), entry at open, both directions (pandas rolling, own code)
def p_liq(tf, L, H):
    dl = 1/L - MMR; hits = []
    for s in COINS:
        df = load(s, tf)
        lo = df.low[::-1].rolling(H, min_periods=H).min()[::-1].values
        hi = df.high[::-1].rolling(H, min_periods=H).max()[::-1].values
        o = df.open.values; m = ~np.isnan(lo)
        hits.append(np.r_[(1 - lo[m]/o[m]) >= dl, (hi[m]/o[m] - 1) >= dl])
    return np.concatenate(hits).mean()
print("1d H=1: 20x", round(p_liq("1d",20,1),4), " 50x", round(p_liq("1d",50,1),4))
print("4h H=16 20x", round(p_liq("4h",20,16),4), " 1h H=16 20x", round(p_liq("1h",20,16),4))
for L in (20,21,22,23,24,25):
    print(f"30m L={L}: P(liq within 16 bars)={p_liq('30m',L,16):.4f}  TP/ATR={0.1/L/0.007626:.3f}  liq/ATR={(1/L-MMR)/0.007626:.2f}  fee/TP={0.014*L:.3f}")

# 2) time-of-day: daily entries at 00/06/12/18 UTC, 5m paths, 20x
rows = []
for hr in (0, 6, 12, 18):
    rec = []
    for s in COINS:
        df = load(s, "5m")
        o,h,l,c = (df[k].values.astype(float) for k in ["open","high","low","close"])
        ts = df.ts.values.astype("datetime64[s]")
        hh = df.ts.dt.hour.values; mm = df.ts.dt.minute.values
        idx = np.where((hh == hr) & (mm == 0))[0]; idx = idx[idx + 25920 <= len(o)]
        for e in idx:
            for d in (1,-1):
                r = sim_one(o,h,l,c,ts,int(e),d,20,5)
                if r: rec.append((COINS.index(s)*100000 + int(ts[e].astype(np.int64))//604800, r[0], r[2]))
    R = np.array(rec)
    rows.append(dict(hour=hr, n=len(R), pTP=(R[:,1]==0).mean(), EROE=100*R[:,2].mean(), se=100*cluster_boot(R[:,2], R[:,0], 300)))
    print(rows[-1], flush=True)

# 3) stop at 0.5 x d_liq, 20x, 5m random entries (own quick loop)
rs = np.random.default_rng(99); rec = []
L = 20; ds = 0.5*(1/L - MMR); tp = 0.10/L
for s in COINS:
    df = load(s, "5m"); o,h,l = (df[k].values.astype(float) for k in ["open","high","low"])
    t = df.ts.values.astype("datetime64[s]").astype(np.int64)
    for e in rs.choice(len(o)-25920, 2000, replace=False):
        for d in (1,-1):
            P = o[e]; up, dn = (P*(1+tp), P*(1-ds)) if d==1 else (P*(1+ds), P*(1-tp))
            a, w = e, 32
            while True:
                b = a + w; x = np.nonzero((h[a:b] >= up) | (l[a:b] <= dn))[0]
                if len(x): break
                a, w = b, w*4
            j = a + x[0]; nf = (t[j]+150)//28800 - t[e]//28800
            tp_t = h[j] >= up if d==1 else l[j] <= dn; st_t = l[j] <= dn if d==1 else h[j] >= up
            gst = j > e and ((o[j] <= dn) if d==1 else (o[j] >= up))
            if (not gst) and tp_t and not st_t:
                rec.append((1, 0.1 - L*C - L*C*(1+d*tp) - L*FR*nf))
            else:
                fill = (min(dn, o[j]) if d==1 else max(up, o[j])) if gst else (dn if d==1 else up)
                r = (fill/P - 1) if d==1 else (1 - fill/P)
                roe = -1 - L*C - L*FR*nf if r < -(1/L-MMR) else L*r - L*C - L*C*fill/P - L*FR*nf
                rec.append((0, roe))
R = np.array(rec); print(f"stop0.5 20x 5m: n={len(R)} pTP={R[:,0].mean():.4f} EROE={100*R[:,1].mean():.3f}%")

# 4) binomial 100-trade medians / Kelly using independently measured class means (5m 20x/50x from v2)
def summ(p, w, lo, M, N=100):
    k = np.arange(N+1); pk = binom.pmf(k, N, 1-p)
    fin = (1+M*w)**(N-k) * (1+M*lo)**k
    # median: smallest k_m with P(K<=k_m)>=0.5 -> median losses
    km = int(binom.median(N, 1-p)); cdfk = binom.cdf(np.arange(N+1), N, 1-p)
    return dict(p=p, M=M, med_losses=km, P_K_le_med=float(cdfk[km]), median_mult=float((1+M*w)**(N-km)*(1+M*lo)**km),
                p_below_half=float(pk[fin<0.5].sum()), kelly_f=p/(-lo) - (1-p)/w,
                p_full=(M + 1/w)/(1/(-lo) + 1/w), p_half=(2*M + 1/w)/(1/(-lo) + 1/w),
                p_log0=-np.log1p(M*lo)/(np.log1p(M*w)-np.log1p(M*lo)))
for (L, p, w, lo, pstar) in ((20, 0.9002, 0.070723, -1.019036, 0.9351), (50, 0.8838, 0.029431, -1.036892, 0.9724)):
    for M in (0.2, 0.4):
        print(L, {k:(round(v,4) if isinstance(v,float) else v) for k,v in summ(p,w,lo,M).items()})
        print(L, "breakeven", {k:(round(v,4) if isinstance(v,float) else v) for k,v in summ(pstar,w,lo,M).items() if k in ("med_losses","P_K_le_med","median_mult")})
