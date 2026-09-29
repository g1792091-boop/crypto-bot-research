"""Independent re-implementation: planted-edge single-account sim + 1y block bootstrap + min-edge search.
usage: python3 minedge.py <tf> <seeds> <edges comma list in %>"""
import sys, time
import numpy as np
import pandas as pd
from common import *

tf = sys.argv[1]; S = int(sys.argv[2]); EDGES = [float(x) / 100 for x in sys.argv[3].split(",")]
t0 = time.time()
D = load(tf)
H = HB[tf]; tfm = TFMIN[tf]
coin = {}
for ci, c in enumerate(COINS):
    df = D[c]
    ok = admissible(df, tf)
    o, h, l, cl = (df[k].values.astype(float) for k in ("open", "high", "low", "close"))
    n = len(df)
    t = np.arange(n)
    rH = np.full(n, np.nan)
    rH[ok] = cl[t[ok] + H] / o[t[ok] + 1] - 1
    tsm = df.ts.values.astype("datetime64[m]").astype(np.int64)
    coin[c] = dict(o=o, h=h, l=l, c=cl, ok=ok, rH=rH, ts=tsm, atr=df.atrp.values, Eabs=np.nanmean(np.abs(rH[ok])))
Eabs = np.array([coin[c]["Eabs"] for c in COINS])
EDGES = [e for e in EDGES if e <= Eabs.min() + 1e-12]
print(tf, "Eabs %:", np.round(100 * Eabs, 3), "edges:", EDGES, flush=True)

# union grid of admissible signal times, per-time list of admissible coins
alltimes = np.unique(np.concatenate([coin[c]["ts"][coin[c]["ok"]] for c in COINS]))
tidx = np.full((len(alltimes), 7), -1)
for ci, c in enumerate(COINS):
    d = coin[c]
    pos = np.where(d["ok"])[0]
    tidx[np.searchsorted(alltimes, d["ts"][pos]), ci] = pos
day0 = np.datetime64(T0.tz_localize(None), "m").astype(np.int64)
ND = int((np.datetime64(T1.tz_localize(None), "m").astype(np.int64) - day0) // 1440)

POL = ["P0|B", "P3|A", "P3|C", "P4|A", "P5|A", "P5|C", "P5c|C", "P6h|B"]


def params(p, atr):
    n = len(atr)
    P, st = p.split("|")
    if P == "P0": M, L = np.ones(n), np.ones(n)
    elif P == "P3": M, L = np.full(n, .2), np.full(n, 20.)
    elif P == "P4": M, L = np.full(n, .4), np.full(n, 50.)
    elif P in ("P5", "P5c"):
        L = np.clip(np.floor(1 / (3 * atr + MMR)), 20, 50)
        M = np.clip(0.06 / (L * atr), 0.2, 0.4)
    elif P == "P6h":
        N = np.minimum(0.005 / (1.5 * atr + 2 * (TAKER + SLIP)), 3.0)
        L = np.clip(np.floor(1 / (3 * atr + MMR)), 1, 10)
        M = np.minimum(N / L, 1.0)
    dl = 1 / L - MMR
    sd = {"A": np.full(n, np.inf), "B": 1.5 * atr, "C": 0.5 * dl}[st]
    td = np.full(n, np.inf) if P == "P6h" else 0.10 / L
    return M, L, dl, sd, td


daily = np.zeros((len(EDGES), len(POL), S, ND))
dmin = np.zeros((len(EDGES), len(POL), S, ND))
tradestat = {}
for s in range(S):
    rng = np.random.default_rng([99, tfm, s])
    p_fire = LAM[tf] * tfm / 1440
    gi = np.where(rng.random(len(alltimes)) < p_fire)[0]
    ci = np.empty(len(gi), int); ti = np.empty(len(gi), int)
    for k, g in enumerate(gi):
        adm = np.where(tidx[g] >= 0)[0]
        ci[k] = adm[rng.integers(len(adm))]
        ti[k] = tidx[g, ci[k]]
    n = len(gi)
    O = np.empty((n, H)); Hh = np.empty((n, H)); Lw = np.empty((n, H)); C = np.empty((n, H))
    TS = np.empty((n, H), np.int64); atr = np.empty(n); rH = np.empty(n)
    for k, c in enumerate(COINS):
        m = ci == k
        d = coin[c]; j = ti[m][:, None] + np.arange(1, H + 1)[None, :]
        O[m] = d["o"][j]; Hh[m] = d["h"][j]; Lw[m] = d["l"][j]; C[m] = d["c"][j]; TS[m] = d["ts"][j]
        atr[m] = d["atr"][ti[m]]; rH[m] = d["rH"][ti[m]]
    cand_ts = alltimes[gi]
    oracle = np.where(rH > 0, 1, np.where(rH < 0, -1, 0))
    rnd = np.where(rng.random(n) < 0.5, 1, -1)
    oracle = np.where(oracle == 0, rnd, oracle)
    u = rng.random(n)
    # outcomes for both sides
    OUT = {}
    for p in POL:
        M, L, dl, sd, td = params(p, atr)
        for sg in (1, -1):
            jx, code, g = exits(O, Hh, Lw, C, np.full(n, sg), dl, sd, td, "colour")
            r = equity_ret(code, g, jx, M, L, tfm)
            OUT[(p, sg)] = (jx, code, g, r)
    qc = np.array([[e / Eabs[k] for k in range(7)] for e in EDGES])
    for ei, e in enumerate(EDGES):
        side = np.where(u < qc[ei][ci], oracle, rnd)
        for pi, p in enumerate(POL):
            jl, cl_, gl, rl = OUT[(p, 1)]; js, cs, gs, rs = OUT[(p, -1)]
            lg = side > 0
            jx = np.where(lg, jl, js); code = np.where(lg, cl_, cs); r = np.where(lg, rl, rs)
            if p.startswith("P5c"):
                M5, L5, _, _, _ = params(p, atr)
                Mnew = np.where(u < qc[ei][ci], 0.4, 0.2)
                r = r * Mnew / M5
            ex_ts = TS[np.arange(n), jx]
            nxt = np.searchsorted(cand_ts, ex_ts, side="left")   # first candidate whose signal bar >= exit bar
            taken = []
            i = 0
            while i < n:
                taken.append(i); i = nxt[i]
            taken = np.array(taken)
            lr = np.log1p(np.maximum(r[taken], -0.999999))
            day = np.clip((ex_ts[taken] - day0) // 1440, 0, ND - 1)
            np.add.at(daily[ei, pi, s], day, lr)
            # intraday min of cumulative log relative to start of day
            cum = np.cumsum(lr)
            start = cum - lr
            assert np.all(np.diff(day) >= 0)
            gs0 = np.r_[0, np.nonzero(np.diff(day))[0] + 1]
            dmin[ei, pi, s, day[gs0]] = np.minimum(np.minimum.reduceat(cum, gs0) - start[gs0], 0.0)
            key = (ei, pi)
            st = tradestat.setdefault(key, dict(n=0, liq=0, tp=0, drift=0.0, eq=0.0, gross=0.0, N=0.0, L=0.0, M=0.0, win=0))
            st["n"] += len(taken); st["liq"] += int((code[taken] == 3).sum()); st["tp"] += int((code[taken] == 1).sum())
            st["drift"] += float((side[taken] * rH[taken]).sum()); st["eq"] += float(r[taken].sum())
            gx = np.where(lg, OUT[(p, 1)][2], OUT[(p, -1)][2])
            Mx, Lx, _, _, _ = params(p, atr)
            if p.startswith("P5c"): Mx = np.where(u < qc[ei][ci], 0.4, 0.2)
            st["gross"] += float(gx[taken].sum()); st["N"] += float((Mx * Lx)[taken].sum()); st["L"] += float(Lx[taken].sum()); st["M"] += float(Mx[taken].sum()); st["win"] += int((r[taken] > 0).sum())
    if s % 10 == 0: print(" seed", s, "cands", n, f"{time.time()-t0:.0f}s", flush=True)

# block bootstrap (own code): 1y = 365 days of 10-day blocks, random seed + random start (circular)
rng = np.random.default_rng(4242)
NP, B, T = 4000, 10, 365
nb = -(-T // B)
sb = rng.integers(0, S, (NP, nb)); db = rng.integers(0, ND, (NP, nb))
SI = np.repeat(sb, B, 1)[:, :T]
DI = ((db[:, :, None] + np.arange(B)) % ND).reshape(NP, -1)[:, :T]
sb30 = rng.integers(0, S, (NP, 3)); db30 = rng.integers(0, ND, (NP, 3))
SI30 = np.repeat(sb30, B, 1)[:, :30]; DI30 = ((db30[:, :, None] + np.arange(B)) % ND).reshape(NP, -1)[:, :30]
rows = []
for ei, e in enumerate(EDGES):
    for pi, p in enumerate(POL):
        X = daily[ei, pi][SI, DI]; Mn = dmin[ei, pi][SI, DI]
        cum = X.cumsum(1)
        low = np.minimum((cum - X + Mn).min(1), 0)
        X30 = daily[ei, pi][SI30, DI30]
        st = tradestat[(ei, pi)]
        rows.append(dict(tf=tf, edge_pct=100 * e, policy=p, trades_30d=st["n"] / S / ND * 30, liq=st["liq"] / st["n"], tp=st["tp"] / st["n"],
                         drift_pct=100 * st["drift"] / st["n"], eq_ret_pct=100 * st["eq"] / st["n"], gross_pct=100 * st["gross"] / st["n"],
                         mean_N=st["N"] / st["n"], mean_L=st["L"] / st["n"], mean_M=st["M"] / st["n"], win=st["win"] / st["n"],
                         med30=float(np.exp(np.median(X30.sum(1)))), med1y=float(np.exp(np.median(cum[:, -1]))),
                         p_ruin1y=float(np.mean(low < np.log(0.1))), p_below50=float(np.mean(low < np.log(0.5)))))
R = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print(R.to_string(index=False, float_format=lambda v: f"{v:.4g}"))
R.to_csv(f"out_minedge_{tf}.csv", index=False)


def crossing(x, y, thr):
    ok = y >= thr
    if not ok[-1]: return None
    f = np.where(~ok)[0]
    if len(f) == 0: return x[0]
    i = f[-1]
    return x[i] + (thr - y[i]) * (x[i + 1] - x[i]) / (y[i + 1] - y[i])


print("\nmin edge (%): max(edge med1y>1, edge pruin<0.10)")
for p in POL:
    g = R[R.policy == p].sort_values("edge_pct")
    a = crossing(g.edge_pct.values, np.log(g.med1y.values), 0.0)
    b = crossing(g.edge_pct.values, -g.p_ruin1y.values, -0.10)
    me = None if (a is None or b is None) else max(a, b)
    print(f"  {tf} {p}: min_edge={me}  [med>1 at {a}, pruin<10% at {b}]")
print("\nedge capture slope (gross vs planted D, D<=0.40%):")
for p in POL:
    g = R[(R.policy == p) & (R.edge_pct <= 0.4001)]
    print(f"  {tf} {p}: slope={np.polyfit(g.edge_pct, g.gross_pct, 1)[0]:.3f}  mean L/M/N at D=0: {g.mean_L.iloc[0]:.1f}/{g.mean_M.iloc[0]:.3f}/{g.mean_N.iloc[0]:.2f}  win@D0={g.win.iloc[0]:.3f}")
print(f"done {time.time()-t0:.0f}s")
