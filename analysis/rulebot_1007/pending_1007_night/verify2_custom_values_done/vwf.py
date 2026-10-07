"""Own compact walk-forward: 4 strategies x 15m, monthly re-tune, windows 13 and 26 weeks, naive / filter-only /
stop-only search, metrics R, R2 (analyst: R*k/2), R2x (exact: net pct / default-stop pct) and NP (net pct).
usage: python3 -I vwf.py <scratchpad>"""
import sys, os, json
sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np
import pandas as pd

SCR = sys.argv[1]
CELLS = os.path.join(SCR, "lens2/custom_values/work/cells")
HERE = os.path.dirname(os.path.abspath(__file__))
NSD = 86400 * 10**9
NSW = 7 * NSD
W0 = np.datetime64("2021-02-01", "ns").astype(np.int64)
T0W = 26
END = np.datetime64("2026-09-30", "ns").astype(np.int64)
NW = int((END - W0) // NSW)
NWO = NW - T0W
SPLIT = np.datetime64("2024-07-01", "ns").astype(np.int64)
DEF = 3  # P0 F0 stop2.0 house -> (0*5+0)*9 + 1*3 + 0
CELLS4 = ["S2_ST_ROC_15m", "N17_KC_RSI_15m", "OBV_B_15m", "F5_BOX_15m"]


def cid(p, f, s, x):
    return (p * 5 + f) * 9 + s * 3 + x


RESTR = {"naive": np.arange(225), "naive_F": np.array([cid(0, f, 1, 0) for f in range(5)]),
         "naive_S": np.array([cid(0, 0, s, 0) for s in range(3)]), "naive_P": np.array([cid(p, 0, 1, 0) for p in range(5)])}


def metrics(a):
    rn = np.nan_to_num(a["rnet"].astype(float))
    k = np.repeat([0.75, 1.0, 1.25], 3)[None, :]
    npct = np.nan_to_num(a["npct"].astype(float))
    sp2 = a["stop_pct"][:, 1].astype(float)[:, None]
    return {"R": rn, "R2": rn * k, "R2x": npct / sp2, "NP": npct * 100}


def pfmat(a):
    pf = np.zeros((len(a["ts"]), 25))
    for p in range(5):
        for f in range(5):
            pf[:, p * 5 + f] = a["pmask"][:, p] if f == 0 else a["pmask"][:, p] & a["fmask"][:, f - 1]
    return pf


def stats(pf, w, v):
    return (pf.T @ w).reshape(-1), (pf.T @ (w * v)).reshape(-1)


def pick(n, S, cands, nmin=10):
    ok = n[cands] >= nmin
    if not ok.any():
        return DEF
    m = np.where(ok, S[cands] / np.maximum(n[cands], 1), -np.inf)
    best = m.max()
    if DEF in cands:
        di = int(np.flatnonzero(cands == DEF)[0])
        if ok[di] and m[di] >= best:
            return DEF
    return int(cands[int(np.argmax(m))])


out_rows = []
day_store = {}
for cell in CELLS4:
    z = np.load(os.path.join(CELLS, cell + ".npz"))
    a = {k: z[k] for k in ("ts", "pmask", "fmask", "done", "rnet", "npct", "stop_pct", "exit_close")}
    ts, ec, done = a["ts"], a["exit_close"], a["done"].astype(float)
    pf = pfmat(a)
    M = metrics(a)
    olo = W0 + T0W * NSW
    ohi = W0 + NW * NSW
    oo = (ts >= olo) & (ts < ohi)
    day = np.where(oo, (ts - olo) // NSD, -1)
    nday = NWO * 7
    for selm in ("R", "R2", "R2x", "NP"):
        v = M[selm]
        for W in (13, 26):
            sels = {mk: np.full(NWO, DEF) for mk in RESTR}
            for k in range(0, NWO, 4):
                T = W0 + (T0W + k) * NSW
                i0, i1 = np.searchsorted(ts, [T - W * NSW, T])
                w = done[i0:i1] * (ec[i0:i1] < T)
                n, S = stats(pf[i0:i1], w, v[i0:i1])
                for mk, cs in RESTR.items():
                    sels[mk][k:k + 4] = pick(n, S, cs)
            for mk, sel in sels.items():
                # evaluate in every metric: per-day sums of selected vs default
                cday = sel[np.clip(day, 0, None) // 7]
                row = dict(cell=cell, select_on=selm, window=W, method=mk,
                           share_switched=float(np.mean(sel != DEF)))
                for evm in ("R", "R2", "R2x", "NP"):
                    ve = M[evm]
                    # membership of each signal in the combo selected for its week
                    c = cday
                    pfc = pf[np.arange(len(ts)), c // 9]
                    j = c % 9
                    ins = oo & (pfc > 0) & (done[np.arange(len(ts)), j] > 0)
                    ind = oo & (pf[:, 0] > 0) & (done[:, 4 - 1] > 0)
                    vs = ve[np.arange(len(ts)), j]
                    vd = ve[:, 3]
                    Dn = np.bincount(day[ins], minlength=nday); DS = np.bincount(day[ins], vs[ins], minlength=nday)
                    En = np.bincount(day[ind], minlength=nday); ES = np.bincount(day[ind], vd[ind], minlength=nday)
                    hA = np.arange(nday) < (SPLIT - olo) // NSD
                    row[f"d_{evm}"] = DS.sum() / Dn.sum() - ES.sum() / En.sum()
                    row[f"dA_{evm}"] = DS[hA].sum() / Dn[hA].sum() - ES[hA].sum() / En[hA].sum()
                    row[f"dB_{evm}"] = DS[~hA].sum() / Dn[~hA].sum() - ES[~hA].sum() / En[~hA].sum()
                    day_store[(cell, selm, W, mk, evm)] = (Dn, DS, En, ES)
                row["trade_ratio"] = float(Dn.sum() / En.sum())
                out_rows.append(row)
    print(cell, flush=True)

df = pd.DataFrame(out_rows)
# pooled over the 4 cells with a joint day-cluster bootstrap
rng = np.random.default_rng(11)
nday = NWO * 7
Wt = np.stack([np.bincount(rng.integers(0, nday, nday), minlength=nday) for _ in range(1000)]).astype(float)
pool = []
for (selm, W, mk), _ in df.groupby(["select_on", "window", "method"]):
    r = dict(select_on=selm, window=W, method=mk)
    for evm in ("R", "R2", "R2x", "NP"):
        arr = [day_store[(c, selm, W, mk, evm)] for c in CELLS4]
        Dn, DS, En, ES = (np.stack([x[i] for x in arr], 1) for i in range(4))
        pt = DS.sum() / Dn.sum() - ES.sum() / En.sum()
        bt = (Wt @ DS).sum(1) / (Wt @ Dn).sum(1) - (Wt @ ES).sum(1) / (Wt @ En).sum(1)
        r[f"pool_{evm}"] = round(float(pt), 5)
        r[f"ci_{evm}"] = [round(float(x), 5) for x in np.percentile(bt, [2.5, 97.5])]
    pool.append(r)
pdf = pd.DataFrame(pool)
df.to_csv(os.path.join(HERE, "vwf_cells.csv"), index=False)
pdf.to_csv(os.path.join(HERE, "vwf_pooled.csv"), index=False)
pd.set_option("display.width", 250)
print(pdf.to_string())
# compare with analyst cells
for metr, sub in (("R", "out"), ("R2", "out_R2")):
    th = pd.read_csv(os.path.join(SCR, "lens2/custom_values", sub, "wf_cells.csv"))
    th = th[th.cell.isin(CELLS4) & th.scheme.isin(["s4_w13", "s4_w26"]) & th.method.isin(list(RESTR))]
    th["window"] = th.scheme.str.split("_w").str[1].astype(int)
    mine = df[df.select_on == metr][["cell", "window", "method", f"d_{metr}"]]
    mm = th.merge(mine, on=["cell", "window", "method"])
    mm["absdiff"] = (mm.delta_R - mm[f"d_{metr}"]).abs()
    print(metr, "max abs diff vs analyst wf_cells:", mm.absdiff.max(), "rows", len(mm))
