"""New method 5 (10/25 night, owners: "all market types, x5 month after month"): re-pick every month.

At the start of every KST month, for EACH BTC 4h regime (up / down / range), rank every member gated to that regime by
its own result over the previous L months and take the best K (different strategies); the month is traded with those
3K members in one position (each only in its regime). Every month is chosen from the past only, so every month read
is unseen. Members: 484 cells x 8 exits (ladder 12->10/5 with stop 1 ATR, 2 ATR, ROE -50 %, ROE -75 %; fixed take
profit: 2 ATR stop / ROE +100 %, 2 ATR / 3 ATR, ROE -75 % / ROE +100 %, ROE -75 % / 3 ATR) x side (both, short, long).
Rank by the sum of log(1 + wallet result) (R "log") or the mean per trade with at least 15 trades (R "mean");
L 3 / 6 / 12 months, K 1 / 2 / 3. Months 2021-03 .. 2026-09 (+ October to the 24th). Read: x5 months (x5 before -50 %),
x5 months in a row, -50 % months, median month, per regime. Coin flip: the same with seeded random directions
(argv 1 = seed)."""
import os, sys, json, time
import numpy as np, pandas as pd
import numba as nb
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
T00 = time.time()
SEED = None if len(sys.argv) < 2 else int(sys.argv[1])
XS = [0, 2, 5, 6, 16, 18, 21, 23]
MODES = ("B", "S", "L")
KST = 9 * 3600 * 1000


def log(*a):
    print(f"[{time.time() - T00:7.0f}s]", *a, flush=True)


@nb.njit(cache=False)
def one_pos(t, k):
    keep = np.zeros(len(t), np.bool_); free = -1
    for i in range(len(t)):
        if t[i] >= free:
            keep[i] = True; free = t[i] + k[i] * 60000
    return keep


def mon_idx(t):
    d = pd.to_datetime(t + KST, unit="ms")
    return ((d.year - 2020) * 12 + d.month - 1).to_numpy()


NM = 82                                         # 2020-01 .. 2026-10
cells = [str(c) for c in np.load(os.path.join(OUTD, "meta.npz"), allow_pickle=True)["cells"]]
STORE = {}
for n, cell in enumerate(cells):
    for x in XS:
        try:
            T = SM.trades(cell, "none", "양방향", x, flip_seed=SEED)
        except IndexError:
            break
        if not len(T):
            continue
        t = T.t.to_numpy(np.int64)
        STORE[(cell, x)] = (t, T.w.to_numpy(np.float64), T.k.to_numpy(np.int64), T.side.to_numpy(np.int8),
                            reg_at(t).astype(np.int8), int(T.tfo.iloc[0]))
    SM._S.pop(cell, None)
    if n % 100 == 0:
        log("walked", n, "/", len(cells))
log("walks done", len(STORE))


def member(key):
    cell, x, mode, gate = key
    t, w, k, side, reg, tfo = STORE[(cell, x)]
    m = reg == gate
    if mode == "S":
        m &= side < 0
    elif mode == "L":
        m &= side > 0
    o = np.argsort(t[m], kind="stable")
    tt, ww, kk = t[m][o], w[m][o], k[m][o]
    keep = one_pos(tt, kk)
    return tt[keep], ww[keep], kk[keep], np.full(int(keep.sum()), tfo)


KEYS = [(c, x, md, g) for (c, x) in STORE for md in MODES for g in (0, 1, 2)]
SL = np.zeros((len(KEYS), NM), np.float32); SW = np.zeros_like(SL); CN = np.zeros_like(SL)
for i, key in enumerate(KEYS):
    tt, ww, _, _ = member(key)
    if not len(tt):
        continue
    mi = mon_idx(tt)
    np.add.at(SL[i], mi, np.log1p(np.maximum(ww, -0.999)))
    np.add.at(SW[i], mi, ww); np.add.at(CN[i], mi, 1)
log("member months", len(KEYS))
GATE = np.array([k[3] for k in KEYS]); CELLN = np.array([k[0].split("@")[0] for k in KEYS])
CSL = np.c_[np.zeros(len(KEYS)), np.cumsum(SL, 1)]; CSW = np.c_[np.zeros(len(KEYS)), np.cumsum(SW, 1)]
CCN = np.c_[np.zeros(len(KEYS)), np.cumsum(CN, 1)]


def pick(m, L, K, rank):
    a, b = m - L, m
    lg = CSL[:, b] - CSL[:, a]; n = CCN[:, b] - CCN[:, a]; mw = (CSW[:, b] - CSW[:, a]) / np.maximum(n, 1)
    score = lg if rank == "log" else np.where(n >= 15, mw, -9)
    chosen = []
    for g in (0, 1, 2):
        idx = np.flatnonzero((GATE == g) & (n >= 5))
        idx = idx[np.argsort(-score[idx], kind="stable")]
        names = set()
        for i in idx:
            if score[i] <= 0 or len(names) >= K:
                break
            if CELLN[i] in names:
                continue
            names.add(CELLN[i]); chosen.append(KEYS[i])
    return chosen


def month_bounds(m):
    y, mo = 2020 + m // 12, m % 12 + 1
    a = pd.Timestamp(year=y, month=mo, day=1).value // 1_000_000 - KST
    y2, mo2 = (y + (mo == 12), mo % 12 + 1)
    b = pd.Timestamp(year=y2, month=mo2, day=1).value // 1_000_000 - KST
    return a, min(b, SM.Z)


def run_month(keys, m):
    if not keys:
        return {"x": 1.0, "r": "거래없음", "n": 0, "reg": [0, 0, 0]}
    parts = [member(k) for k in keys]
    t = np.concatenate([p[0] for p in parts]); w = np.concatenate([p[1] for p in parts])
    k = np.concatenate([p[2] for p in parts]); tf = np.concatenate([p[3] for p in parts])
    rg = np.concatenate([np.full(len(p[0]), kk[3]) for p, kk in zip(parts, keys)])
    a, b = month_bounds(m)
    s = (t >= a) & (t < b)
    t, w, k, tf, rg = t[s], w[s], k[s], tf[s], rg[s]
    o = np.lexsort((-tf, t)); t, w, k, rg = t[o], w[o], k[o], rg[o]
    keep = one_pos(t, k); w, rg = w[keep], rg[keep]
    eq = 1.0; r = "그대로"
    for v in w:
        eq *= 1 + v
        if eq >= 5:
            r = "x5"; break
        if eq <= 0.5:
            r = "-50%"; break
    full = float(np.prod(1 + w))
    regs = [round(float(np.prod(1 + w[rg == g])), 3) for g in (0, 1, 2)]
    return {"x": round(eq, 3), "끝": round(full, 3), "r": r, "n": int(len(w)), "reg": regs}


M0 = (2021 - 2020) * 12 + 2                    # 2021-03
res = {}
for rank in ("log", "mean"):
    for L in (3, 6, 12):
        for K in (1, 2, 3):
            out = []
            for m in range(M0, NM):
                out.append(run_month(pick(m, L, K, rank), m))
            rs = [o["r"] for o in out[:-1]]               # without October (partial)
            hits = [r == "x5" for r in rs]
            two = sum(1 for i in range(1, len(hits)) if hits[i] and hits[i - 1])
            regp = np.array([o["reg"] for o in out[:-1]])
            summ = {"달": len(rs), "x5달": int(sum(hits)), "연속 x5": two, "-50%달": rs.count("-50%"),
                    "달 중간값": round(float(np.median([o["끝"] for o in out[:-1]])), 3),
                    "장세별 달 중간값(상승/하락/횡보)": [round(float(np.median(regp[:, g])), 3) for g in range(3)],
                    "2026 1~9월": [o["끝"] for o in out[-10:-1]], "10월(24일까지)": out[-1]["끝"],
                    "x5달 목록": [f"{2020 + (M0 + i) // 12}-{(M0 + i) % 12 + 1:02d}" for i, h in enumerate(hits) if h]}
            res[f"{rank}/L{L}/K{K}"] = summ
            log(rank, L, K, json.dumps(summ, ensure_ascii=False))
lab = "real" if SEED is None else f"flip{SEED}"
json.dump(res, open(os.path.join(OUTD, f"rotate16_{lab}.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
