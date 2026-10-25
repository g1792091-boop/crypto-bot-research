"""Hunt 10/25 step 4: one bot (one wallet, one position) from several members. Members come from groups whose result
holds over many exits (plateau). Two ways to pick: top-K by plateau (no search over combinations) and greedy merge.
Every way is also run as a procedure on one half and read on the other half (the honest check).
Tier A = runs in the combined bot today (core / DeepSeek / friend strategies, no member trend filter, ladder exits);
tier B = needs a member trend filter in code (any of the tested filters), still ladder exits only."""
import os, sys, json
import numpy as np, pandas as pd
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
R = np.load(os.path.join(OUTD, "single_R.npy"), mmap_mode="r")
Gp = pd.read_csv(os.path.join(OUTD, "groups.csv")); EX = pd.read_csv(os.path.join(OUTD, "exits.csv"))
Z_ = np.load(os.path.join(OUTD, "groups_idx.npz")); ptr, IDX, order = Z_["ptr"], Z_["IDX"], Z_["order"]
S = pd.read_pickle(os.path.join(OUTD, "sig.pkl.gz")).iloc[order].reset_index(drop=True)
F = np.load(os.path.join(OUTD, "fwd.npz")); W = F["W"][order]; K = F["K"][order]
t = S.t.to_numpy(np.int64); tfo = S.tf.map({"15m": 0, "30m": 1, "1h": 2, "4h": 3}).to_numpy()
A, Zend = 1791212400000, 1792851120000
Q = np.linspace(A, Zend, 5).astype(np.int64)
NAMES = pd.read_csv("/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/"
                    "review1024_roles/data/signals/names.csv")
SET = dict(zip(NAMES.name, NAMES.set))
Gp["set"] = Gp.cell.str.split("@").str[0].map(SET)
LAD = EX.index[EX.name.str.contains("익절 없음") & EX.name.str.contains("계단 12→10")].to_numpy()   # the bot's ladder
TIER = {"A": (Gp.set.isin(["core", "ds", "friend"]) & (Gp["filter"] == "none")).to_numpy(),
        "B": np.ones(len(Gp), bool)}


@njit(cache=True)
def run(ts, tf, w, k, a, b):
    o = np.argsort(ts * 8 - tf)          # time, then the longer timeframe first
    free = -1; eq = 1.0; peak = 1.0; dd = 0.0; n = 0; wn = 0
    for p in range(len(o)):
        i = o[p]
        if ts[i] < a or ts[i] >= b or ts[i] < free:
            continue
        eq *= 1 + w[i]; n += 1
        if w[i] > 0:
            wn += 1
        peak = max(peak, eq); dd = min(dd, eq / peak - 1)
        free = ts[i] + k[i] * 60000
    return eq, dd, n, wn


def member_arrays(mem):
    ts, tf, w, k = [], [], [], []
    for g, x in mem:
        ii = IDX[ptr[g]:ptr[g + 1]]
        ts.append(t[ii]); tf.append(tfo[ii]); w.append(W[ii, x].astype(np.float64)); k.append(K[ii, x].astype(np.int64))
    return np.concatenate(ts), np.concatenate(tf), np.concatenate(w), np.concatenate(k)


def bot(mem, a, b):
    if not mem:
        return 1.0, 0.0, 0, 0
    return run(*member_arrays(mem), a, b)


def pool(a, b, tier, top=300):
    """Groups of the tier with their best ladder exit inside [a, b): plateau = share of ladder exits with both
    sub-halves of the window >= x1 (>= 2 trades each); best exit = the highest weaker sub-half."""
    m = (a + b) // 2
    cand = np.flatnonzero(TIER[tier])
    rows = []
    for g in cand:
        ii = IDX[ptr[g]:ptr[g + 1]]
        inw = (t[ii] >= a) & (t[ii] < b)
        if inw.sum() < 6:
            continue
        best = None; good = 0
        for x in LAD:
            e1, _, n1, _ = run(t[ii], tfo[ii], W[ii, x].astype(np.float64), K[ii, x].astype(np.int64), a, m)
            e2, _, n2, _ = run(t[ii], tfo[ii], W[ii, x].astype(np.float64), K[ii, x].astype(np.int64), m, b)
            ok = n1 >= 2 and n2 >= 2
            if ok and e1 >= 1 and e2 >= 1:
                good += 1
            if ok and (best is None or min(e1, e2) > best[0]):
                best = (min(e1, e2), x, e1 * e2)
        if best is not None:
            rows.append((g, good / len(LAD), best[1], best[0], best[2]))
    P = pd.DataFrame(rows, columns=["g", "plat", "x", "weak", "eq"])
    P["cell"] = Gp.cell.to_numpy()[P.g]
    P = P.sort_values(["plat", "weak"], ascending=False).drop_duplicates("cell").head(top)
    return P.reset_index(drop=True)


def greedy(P, a, b, kmax=12):
    mem = []; best = 1.0
    for _ in range(kmax):
        top = None
        for r in P.itertuples():
            if any(Gp.cell[g] == r.cell for g, _ in mem):
                continue
            eq = bot(mem + [(r.g, r.x)], a, b)[0]
            if eq > best * 1.02 and (top is None or eq > top[0]):
                top = (eq, (r.g, r.x))
        if top is None:
            break
        best = top[0]; mem.append(top[1])
    return mem


def describe(mem):
    return [f"{Gp.cell[g]} {'숏만' if Gp['mode'][g] == 'S' else '롱만' if Gp['mode'][g] == 'L' else '양방향'} · "
            f"{Gp['filter'][g]} · {EX.name[x]}" for g, x in mem]


def read(mem):
    out = {}
    for lab, (a, b) in {"19일": (A, Zend), "앞절반": (A, Q[2]), "뒤절반": (Q[2], Zend), "Q1": (Q[0], Q[1]),
                        "Q2": (Q[1], Q[2]), "Q3": (Q[2], Q[3]), "Q4": (Q[3], Q[4])}.items():
        eq, dd, n, wn = bot(mem, a, b)
        out[lab] = {"x": round(float(eq), 2), "dd": round(float(dd), 2), "n": int(n), "win": round(wn / n, 2) if n else None}
    return out


if __name__ == "__main__":
    res = {}
    for tier in ("A", "B"):
        Pall = pool(A, Zend, tier)
        P1 = pool(A, Q[2], tier); P2 = pool(Q[2], Zend, tier)
        print(f"tier {tier}: pool all {len(Pall)} / H1 {len(P1)} / H2 {len(P2)}", flush=True)
        for K_ in (3, 5, 10, 20):
            for lab, P, (a, b), (c, d) in (("전체로 고름", Pall, (A, Zend), (A, Zend)),
                                           ("앞절반으로 고름→뒤절반", P1, (A, Q[2]), (Q[2], Zend)),
                                           ("뒤절반으로 고름→앞절반", P2, (Q[2], Zend), (A, Q[2]))):
                mem = [(r.g, r.x) for r in P.head(K_).itertuples()]
                eq, dd, n, wn = bot(mem, c, d)
                res[f"{tier}/top{K_}/{lab}"] = {"x": round(float(eq), 2), "dd": round(float(dd), 2), "n": int(n),
                                                "win": round(wn / max(n, 1), 2)}
                if lab == "전체로 고름":
                    res[f"{tier}/top{K_}/{lab}"].update(read=read(mem), members=describe(mem))
        for lab, P, (a, b), (c, d) in (("전체로 고름", Pall, (A, Zend), (A, Zend)),
                                       ("앞절반으로 고름→뒤절반", P1, (A, Q[2]), (Q[2], Zend)),
                                       ("뒤절반으로 고름→앞절반", P2, (Q[2], Zend), (A, Q[2]))):
            mem = greedy(P, a, b)
            eq, dd, n, wn = bot(mem, c, d)
            insample = bot(mem, a, b)[0]
            res[f"{tier}/greedy/{lab}"] = {"x": round(float(eq), 2), "dd": round(float(dd), 2), "n": int(n),
                                           "win": round(wn / max(n, 1), 2), "picked_window_x": round(float(insample), 2),
                                           "members": describe(mem)}
            if lab == "전체로 고름":
                res[f"{tier}/greedy/{lab}"]["read"] = read(mem)
        for k_, v in res.items():
            if k_.startswith(tier):
                print(k_, {kk: vv for kk, vv in v.items() if kk not in ("members", "read")}, flush=True)
    json.dump(res, open(os.path.join(OUTD, "combo.json"), "w"), ensure_ascii=False, indent=1)
