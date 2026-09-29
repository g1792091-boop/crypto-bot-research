"""Independent minimal verifier (own code; does not import ../sim).
Event-driven, one position at a time, exits resolved trade-by-trade on 5m sub-bars.
IS data only (sweep/data/is, bars < 2024-07-01)."""
import sys, time, json
import numpy as np, pandas as pd

IS = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/is"
COINS = ["btcusd", "ethusd", "solusd", "xrpusd", "dogeusd", "ltcusd", "bchusd"]
TFM = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
LAM = {"5m": 6.0, "15m": 4.0, "1h": 1.5, "4h": 3 / 7}
H = 64
W0 = int(pd.Timestamp("2021-08-01", tz="UTC").timestamp()); W1 = int(pd.Timestamp("2024-07-01", tz="UTC").timestamp())
FEE, SLIP, MMR, F8 = 0.0005, 0.0002, 0.005, 0.0001
CIN = FEE + SLIP
import os as _os
TPFEE = float(_os.environ.get('TPFEE', FEE))

tf = sys.argv[1]; S = int(sys.argv[2]); HE = int(sys.argv[3]); ORDER = sys.argv[4] if len(sys.argv) > 4 else "adv"
BASE = int(sys.argv[5]) if len(sys.argv) > 5 else 777
TAG = f"_b{BASE}" if BASE != 777 else ""
tfs = TFM[tf] * 60; m = TFM[tf] // 5; W = H * m
t0 = time.time()

def load(c, t):
    p = f"{IS}/{c}-{t}.csv"; assert "/data/is/" in p
    df = pd.read_csv(p)
    ts = pd.to_datetime(df["ts"], utc=True).astype("int64").to_numpy() // 10**9
    k = ts < W1
    return ts[k], df[["open", "high", "low", "close"]].to_numpy(float)[k]

D = {}
agg_bad = 0
for c in COINS:
    ts, x = load(c, tf); ts5, y = load(c, "5m")
    o, h, l, cl = x.T
    pc = np.r_[cl[0], cl[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy() / cl   # own ATR (EWM seeded at first TR)
    n = len(ts)
    p5 = np.searchsorted(ts5, ts + tfs)          # first 5m bar of TF bar t+1
    t = np.arange(n)
    ok = (t >= 50) & (ts >= W0) & (t + H < n)
    ok &= np.where(t + H < n, ts[np.minimum(t + H, n - 1)] - ts, 0) == H * tfs
    ok &= (p5 + W - 1 < len(ts5))
    pp = np.minimum(p5, len(ts5) - 1); pe = np.minimum(p5 + W - 1, len(ts5) - 1)
    ok &= (ts5[pp] == ts + tfs) & (ts5[pe] - ts5[pp] == (W - 1) * 300)
    # aggregation spot check: TF bar t+1 vs its m 5m bars
    idx = np.where(ok)[0][::97]
    for i in idx:
        s = slice(p5[i], p5[i] + m)
        if not (abs(y[s][0, 0] - o[i + 1]) < 1e-9 * o[i + 1] and abs(y[s][:, 1].max() - h[i + 1]) < 1e-9 * h[i + 1]
                and abs(y[s][:, 2].min() - l[i + 1]) < 1e-9 * l[i + 1] and abs(y[s][-1, 3] - cl[i + 1]) < 1e-9 * cl[i + 1]):
            agg_bad += 1
    rhe = np.full(n, np.nan)
    j = np.where(ok)[0]
    rhe[j] = cl[j + HE] / o[j + 1] - 1
    D[c] = dict(ts=ts, o=o, c=cl, atr=atr, ok=ok, p5=p5, o5=y[:, 0].copy(), h5=y[:, 1].copy(), l5=y[:, 2].copy(),
                c5=y[:, 3].copy(), ts5=ts5, rhe=rhe, Eabs=float(np.nanmean(np.abs(rhe[j]))))
print(f"[{tf}] loaded {time.time()-t0:.0f}s; aggregation mismatches in spot check: {agg_bad}", flush=True)
EAB = np.array([D[c]["Eabs"] for c in COINS])
grid = np.unique(np.concatenate([D[c]["ts"][D[c]["ok"]] for c in COINS]))
admt = np.full((len(grid), 7), -1)
for k, c in enumerate(COINS):
    j = np.where(D[c]["ok"])[0]
    admt[np.searchsorted(grid, D[c]["ts"][j]), k] = j
ND = (W1 - W0) // 86400

def trade(ci, t, side, L, sd, td, order):
    d = D[COINS[ci]]; p = d["p5"][t]; E = d["o5"][p]
    s = slice(p, p + W)
    if side > 0:
        fav = d["h5"][s] / E - 1; adv = 1 - d["l5"][s] / E; om = d["o5"][s] / E - 1
    else:
        fav = 1 - d["l5"][s] / E; adv = d["h5"][s] / E - 1; om = 1 - d["o5"][s] / E
    dl = 1 / L - MMR
    A, acode = (sd, 2) if sd < dl else (dl, 3)
    ha = adv >= A; ht = fav >= td
    ia = int(np.argmax(ha)) if ha.any() else W
    it = int(np.argmax(ht)) if ht.any() else W
    if ia == W and it == W:
        j = W - 1; code = 4; g = side * (d["c5"][p + W - 1] / E - 1)
    elif it < ia:
        j = it; code = 1; g = max(td, om[j])
    elif ia < it:
        j = ia; code = acode
        if code == 2 and -om[j] >= dl: code = 3
        g = min(-sd, om[j]) if code == 2 else -dl
    else:
        j = ia
        if om[j] >= td: code = 1; g = om[j]
        elif -om[j] >= A or order == "adv":
            code = acode
            if code == 2 and -om[j] >= dl: code = 3
            g = min(-sd, om[j]) if code == 2 else -dl
        else: code = 1; g = td
    fund = F8 * (j + 1) * 5 / 480
    if code == 3:
        y = -1 / L - CIN - fund; cost = CIN + fund
    else:
        cost = CIN + (TPFEE if code == 1 else FEE + SLIP) + fund; y = g - cost
    return d["ts5"][p + j] + 300, g, code, cost, y, j // m + 1

import os
SC = [("S0", 0.0, False), ("S1", 0.0005, False), ("S3", 0.0005, True), ("S4", 0.0010, True)]
if os.environ.get("SCEN"): SC = [tuple(x) for x in json.loads(os.environ["SCEN"])]
POLS_ENV = os.environ.get("POLS")
POL = ["tiered", "rec", "flat20"]
if os.environ.get("POLS"): POL = os.environ["POLS"].split(",")
res = {}
cal = {nm: [] for nm, _, _ in SC}
holdchk = []
for seed in range(S):
    rng = np.random.default_rng([BASE, TFM[tf], seed])
    fire = rng.random(len(grid)) < LAM[tf] * tfs / 86400
    gi = np.where(fire)[0]
    ci = np.array([rng.choice(np.where(admt[g] >= 0)[0]) for g in gi])
    ti = admt[gi, ci]
    n = len(gi)
    score = rng.random(n); tier = (score >= 0.7).astype(int) + (score >= 0.9).astype(int)
    rside = np.where(rng.random(n) < 0.5, 1, -1); uo = rng.random(n)
    sig_close = grid[gi] + tfs
    rhe = np.array([D[COINS[c]]["rhe"][t] for c, t in zip(ci, ti)])
    orc = np.where(rhe > 0, 1, np.where(rhe < 0, -1, rside))
    atr = np.array([D[COINS[c]]["atr"][t] for c, t in zip(ci, ti)])
    sd = 1.5 * atr
    cache = {}
    def get(i, side, L, td):
        key = (i, side, L)
        if key not in cache: cache[key] = trade(ci[i], ti[i], side, L, sd[i], td, ORDER)
        return cache[key]
    if seed < 4:   # edge-horizon check: mean hold (TF bars) of the 20x normal trade on random sides, all candidates
        holdchk += [get(i, rside[i], 20.0, 0.10 / 20)[5] for i in range(n)]
    for nm, Dd, conc in SC:
        qb = Dd / EAB[ci]
        if conc == "top1": q = np.where(tier == 2, 1.0, 0.0)      # perfect foresight on the top decile, random otherwise
        else: q = np.minimum(qb * (np.where(tier == 2, 3.0, 0.7 / 0.9) if conc else 1.0), 1.0)
        side = np.where(uo < q, orc, rside)
        dr = side * rhe
        cal[nm].append((dr.mean(), dr[tier == 2].mean(), dr[tier < 2].mean()))
        for pol in POL:
            nxt = -1; tr = []
            for i in range(n):
                if sig_close[i] < nxt: continue
                if pol == "tiered": L = [20., 30., 50.][tier[i]]; N = [4., 9., 20.][tier[i]]
                elif pol == "flat20": L, N = 20., 4.
                else: L = 10.; N = min([0.01, 0.01, 0.02][tier[i]] / sd[i], 10.)
                ex, g, code, cost, y, hb = get(i, int(side[i]), L, max(0.10 / L, 2 * sd[i]) if _os.environ.get('TPMODE') == '2x' else 0.10 / L)
                f = 1 + N * y
                assert f > 0
                tr.append((ex, np.log(f), code, g, N * cost, tier[i], dr[i], N))
                nxt = ex
            res.setdefault((nm, pol), []).append(np.array(tr))
    if seed % 6 == 0: print(f"  seed {seed} n={n} t={time.time()-t0:.0f}s", flush=True)

out = dict(tf=tf, HE=HE, order=ORDER, S=S, Eabs=dict(zip(COINS, EAB.tolist())), hold_mean_20x=float(np.mean(holdchk)))
print(f"[{tf}] E|r_he| {EAB.min()*100:.3f}-{EAB.max()*100:.3f}%  measured mean hold of 20x normal trade (5m-resolved) = {np.mean(holdchk):.2f} TF bars")
for nm in cal:
    a = np.array(cal[nm]).mean(0)
    print(f"  calib {nm}: realised drift all {a[0]*100:+.3f}%  top10 {a[1]*100:+.3f}%  rest {a[2]*100:+.3f}%")
# ---- Monte Carlo from per-seed daily log returns
NP, T, BLK = 5000, 365, 20
mrng = np.random.default_rng(12345)
bs_s = mrng.integers(0, S, (NP, T // BLK + 1)); bs_d = mrng.integers(0, ND - BLK, (NP, T // BLK + 1))
rows = []
for (nm, pol), lst in res.items():
    daily = np.zeros((S, ND)); allt = np.concatenate(lst)
    for s, tr in enumerate(lst):
        day = np.clip((tr[:, 0] - W0) // 86400, 0, ND - 1).astype(int)
        daily[s] = np.bincount(day, weights=tr[:, 1], minlength=ND)
    cum = np.cumsum(daily, 1)
    # A: rolling 365-day windows of the actual simulated histories (start every 7 days)
    starts = np.arange(0, ND - 365, 7)
    prev = np.c_[np.zeros(S), cum][:, starts]
    endA = (1000 * np.exp(cum[:, starts + 364] - prev)).ravel()
    # B: fixed 20-day block bootstrap (own implementation)
    blocks = daily[bs_s[:, :, None], bs_d[:, :, None] + np.arange(BLK)[None, None, :]].reshape(NP, -1)[:, :T]
    endB = 1000 * np.exp(blocks.sum(1))
    # C: iid trade bootstrap, Poisson trade count per year
    ny = len(allt) / S / (ND / 365)
    k = mrng.poisson(ny, NP); lr = allt[:, 1]
    endC = np.array([1000 * np.exp(lr[mrng.integers(0, len(lr), kk)].sum()) for kk in k])
    nt = len(allt)
    rows.append(dict(scen=nm, pol=pol, trades_pm=nt / S / (ND / 30.4375), liq_pm=(allt[:, 2] == 3).sum() / S / (ND / 30.4375),
                     liq_rate_t2=((allt[:, 2] == 3) & (allt[:, 5] == 2)).sum() / max((allt[:, 5] == 2).sum(), 1),
                     mean_N=allt[:, 7].mean(), cost_eq_pt=allt[:, 4].mean(), gross_pt=allt[:, 3].mean(), drift_taken=allt[:, 6].mean(),
                     gross_t2=allt[allt[:, 5] == 2, 3].mean(), drift_t2=allt[allt[:, 5] == 2, 6].mean(),
                     mean_lr_pt=lr.mean(),
                     A_med=np.median(endA), A_P500=np.mean(endA < 500), B_med=np.median(endB), B_P500=np.mean(endB < 500),
                     B_p10=np.percentile(endB, 10), B_p90=np.percentile(endB, 90),
                     C_med=np.median(endC), C_P500=np.mean(endC < 500),
                     full_hist_med_end=float(np.median(1000 * np.exp(cum[:, -1]))), fee_yr_pct_eq_simple=allt[:, 4].mean() * ny * 100))
R = pd.DataFrame(rows)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
fmt = R.copy()
for col in ["cost_eq_pt", "gross_pt", "drift_taken", "gross_t2", "drift_t2", "mean_lr_pt", "liq_rate_t2"]:
    fmt[col] = (fmt[col] * 100).round(3)
print(fmt.round(3).to_string(index=False))
R.to_csv(f"v_{tf}_{ORDER}{TAG}{os.environ.get('OTAG','')}.csv", index=False)
json.dump(out, open(f"v_{tf}_{ORDER}{TAG}{os.environ.get('OTAG','')}.json", "w"), indent=1)
print(f"done {time.time()-t0:.0f}s")
