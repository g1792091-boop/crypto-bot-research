"""Verifier part 2: independent zero-edge bracket simulation (loop-based first passage, own funding
count by 8h settlement stamps, cluster bootstrap), own-bar vs 5m-path, and break-even p*."""
import sys, numpy as np, pandas as pd
D = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/is"
OUT = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sizing/v_math/out"
COINS = ["btcusd","ethusd","solusd","xrpusd","dogeusd","ltcusd","bchusd"]
MMR=0.005; C=0.0007; FR=0.0001; TFMIN={"5m":5,"1h":60,"4h":240,"1d":1440}
rng = np.random.default_rng(777)

def load(s, tf):
    df = pd.read_csv(f"{D}/{s}-{tf}.csv", parse_dates=["ts"])
    assert df.ts.max() < pd.Timestamp("2024-07-01", tz="UTC")
    return df

def first_hit(h, l, e, up, dn, cap):
    w = 32
    while True:
        a, b = e, min(e + w, len(h), e + cap)
        hit = np.nonzero((h[a:b] >= up) | (l[a:b] <= dn))[0]
        if len(hit): return a + hit[0]
        if b >= min(len(h), e + cap): return -1
        w *= 4

def sim_one(o,h,l,c,ts,e,d,L,tfmin,mu=0.0):
    """returns (outcome, roe, hours, amb, entrybar). outcome 0=TP 2=liq 3=timeout; adv & fav both."""
    P = o[e]; dl = 1/L - MMR; tp = 0.10/L
    cap = int(90*1440/tfmin)
    if mu != 0.0:
        n = min(cap, len(h)-e)
        k = np.arange(n)
        sc = np.exp(d*mu*k)
        hh = h[e:e+n]*sc; ll = l[e:e+n]*sc; oo = o[e:e+n]*sc
        base = 0
    else:
        hh, ll, oo, base = h, l, o, e
    if d == 1: up, dn = P*(1+tp), P*(1-dl)
    else:      up, dn = P*(1+dl), P*(1-tp)
    j = first_hit(hh, ll, base, up, dn, cap)
    if j < 0:
        return None
    jabs = e + (j - base)
    t_exit = ts[jabs] + np.timedelta64(int(tfmin*30), 's')
    hours = (t_exit - ts[e]) / np.timedelta64(1, 'h')
    # funding stamps 00/08/16 UTC crossed in (entry, exit]
    t0 = ts[e].astype('datetime64[s]').astype(np.int64); t1 = t_exit.astype('datetime64[s]').astype(np.int64)
    nf = t1 // 28800 - t0 // 28800
    fund = L*FR*nf
    upt, dnt = hh[j] >= up, ll[j] <= dn
    tp_t = upt if d == 1 else dnt; st_t = dnt if d == 1 else upt
    gap_st = gap_tp = False
    if jabs > e:
        gap_st = (oo[j] <= dn) if d == 1 else (oo[j] >= up)
        gap_tp = (oo[j] >= up) if d == 1 else (oo[j] <= dn)
    amb = tp_t and st_t and not gap_st and not gap_tp
    ex_tp_rel = (1+tp) if d == 1 else (1-tp)
    roe_tp = 0.10 - L*C - L*C*ex_tp_rel - fund
    roe_liq = -1.0 - L*C - fund
    if gap_st: adv = fav = 2
    elif gap_tp: adv = fav = 0
    elif amb: adv, fav = 2, 0
    elif tp_t: adv = fav = 0
    else: adv = fav = 2
    r = lambda oc: roe_tp if oc == 0 else roe_liq
    return adv, fav, r(adv), r(fav), hours, amb, jabs == e, roe_tp, roe_liq

def cluster_boot(x, g, B=400):
    dfg = pd.DataFrame({"x": x, "g": g}).groupby("g")["x"].agg(["sum","count"])
    s, n = dfg["sum"].values, dfg["count"].values
    idx = rng.integers(0, len(s), size=(B, len(s)))
    return float(np.std(s[idx].sum(1)/n[idx].sum(1)))

def run(entry_tf, path_tf, L_list, nbars_per_coin, mu_by_L=None, tag=""):
    rows = []
    for L in L_list:
        recs = []
        for s in COINS:
            de = load(s, entry_tf)
            dp = de if path_tf == entry_tf else load(s, path_tf)
            o,h,l,c = (dp[k].values.astype(float) for k in ["open","high","low","close"])
            ts = dp.ts.values.astype("datetime64[s]")
            cap = int(90*1440/TFMIN[path_tf])
            elig = np.arange(max(0, len(de) - int(90*1440/TFMIN[entry_tf])))
            rs = np.random.default_rng(hash((s, entry_tf)) % 2**32)
            pick = elig if nbars_per_coin is None or nbars_per_coin >= len(elig) else np.sort(rs.choice(elig, nbars_per_coin, replace=False))
            ets = de.ts.values.astype("datetime64[s]")[pick]
            eidx = np.searchsorted(ts, ets)
            ok = (eidx < len(ts)) & (ts[np.minimum(eidx, len(ts)-1)] == ets) & (eidx + cap <= len(ts))
            for e in eidx[ok]:
                for d in (1, -1):
                    mu = 0.0 if mu_by_L is None else mu_by_L
                    res = sim_one(o,h,l,c,ts,int(e),d,L,TFMIN[path_tf],mu)
                    if res is None: continue
                    wk = int(ts[e].astype(np.int64) // (7*86400))
                    recs.append((COINS.index(s)*100000 + wk,) + res)
        R = pd.DataFrame(recs, columns=["g","adv","fav","roe_adv","roe_fav","hours","amb","entrybar","roe_tp","roe_liq"])
        row = dict(tag=tag, entry_tf=entry_tf, path_tf=path_tf, L=L, n=len(R),
                   pTP_adv=(R.adv==0).mean(), pTP_fav=(R.fav==0).mean(), p_brown=(1/L-MMR)/(1.1/L-MMR),
                   EROE_adv=100*R.roe_adv.mean(), se_adv=100*cluster_boot(R.roe_adv.values, R.g.values),
                   EROE_fav=100*R.roe_fav.mean(), p_amb=R.amb.mean(), p_entrybar=R.entrybar.mean(),
                   mean_h=R.hours.mean(), win=100*R.roe_adv[R.adv==0].mean(), loss=100*R.roe_adv[R.adv==2].mean())
        row["pstar"] = -row["loss"]/(row["win"]-row["loss"])
        rows.append(row)
        print({k:(round(v,4) if isinstance(v,float) else v) for k,v in row.items()}, flush=True)
    return rows

if __name__ == "__main__":
    allrows = []
    allrows += run("5m","5m",[20,50],2500,tag="5m own")
    allrows += run("1h","1h",[20,50],2500,tag="1h own")
    allrows += run("1h","5m",[20,50],2500,tag="1h entries on 5m")
    allrows += run("1d","1d",[20],None,tag="1d own (00UTC only)")
    allrows += run("1d","5m",[20],None,tag="1d entries on 5m (00UTC only)")
    allrows += run("4h","4h",[20],None,tag="4h own")
    pd.DataFrame(allrows).to_csv(f"{OUT}/v2_zero_edge.csv", index=False)
