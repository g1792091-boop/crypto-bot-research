"""Sweep 2 (10/25): every entry cell (121 coded strategies x 15m/30m/1h/4h) x side mode (both / short / long) x trend
judge (each of the 52 trend sources' condition state and own-signal latch on the last closed 1h / 4h / 1d bar, the trend
bot's judgment and 4-of-4 votes on 1h / 4h / 1d, or none: 311) x 24 exits, 2020-03 .. 2026-10-24 on the 1m grid, BTC
40x / alts 30x, margin 40 %, Bybit cost, one wallet one position. Scored per KST calendar month: did the month reach x5
before -50 % (the goal), was it positive; and the forward 19 days (10/06-10/24 KST) with its halves. The same with the
direction of every signal a coin flip (2 seeds; the trend judge is read against the flipped side) for the luck count.
Writes out/R_<run>.npy (float16; forward multiples as logs) + out/meta.npz."""
import os, sys, time
import numpy as np, pandas as pd
from numba import njit, prange

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); os.makedirs(OUTD, exist_ok=True)
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/hunt1025")
import hb_build as HB                                    # noqa: E402  (walk_all, LADS, COST, MARGIN, MAXK, LEVC)
from hb_common import RD                                 # noqa: E402
from common import COINS, TFS, TF_MIN, MIN, ms, grid, drop   # noqa: E402

T0 = time.time()
A = ms("2020-03-01"); Z = ms("2026-10-24 14:12")
FWD_A = ms("2026-10-05 15:00"); MID = ms("2026-10-15 03:00")
KST = 9 * 3600 * 1000


def log(*a):
    print(f"[{time.time() - T0:6.0f}s]", *a, flush=True)


# ------------------------------------------------------------------ signals (all strategies, all timeframes)
NM = RD.names()
cols = {k: [] for k in ("sid", "tfi", "coin", "side", "e")}
for ci, coin in enumerate(COINS):
    z = RD._sigfile(coin)
    for ti, tf in enumerate(TFS):
        n = int(z[f"{tf}_n"]); e0 = int(z[f"{tf}_e0"]); tfm = TF_MIN[tf]; step = tfm * MIN
        lo = max(300, -(-(A - RD.T0 - e0 * MIN) // step), 0); hi = min(n, -(-(Z - RD.T0 - e0 * MIN) // step))
        for sid in NM.sid.to_numpy():
            for lab, sd in (("L", 1), ("S", -1)):
                key = f"{tf}_{sid}_{lab}"
                if key not in z.files:
                    continue
                nb = np.flatnonzero(np.unpackbits(z[key])[lo:hi]) + lo
                if not len(nb):
                    continue
                cols["sid"].append(np.full(len(nb), sid, np.int16)); cols["tfi"].append(np.full(len(nb), ti, np.int8))
                cols["coin"].append(np.full(len(nb), ci, np.int8)); cols["side"].append(np.full(len(nb), sd, np.int8))
                cols["e"].append(e0 + nb.astype(np.int64) * tfm)
sid, tfi, coin, side, e = (np.concatenate(cols[k]) for k in ("sid", "tfi", "coin", "side", "e")); del cols
t = RD.T0 + e * MIN
cell = sid.astype(np.int32) * 4 + tfi
o_ = np.lexsort((coin, t, cell)); sid, tfi, coin, side, e, t, cell = (x[o_] for x in (sid, tfi, coin, side, e, t, cell))
log("signals", len(t))

# ATR14 of the signal bar on its own timeframe
atr = np.full(len(t), np.nan)
for ci, c in enumerate(COINS):
    G = RD._grid(c)
    for ti, tf in enumerate(TFS):
        m = (coin == ci) & (tfi == ti)
        atr[m] = G[f"atr14_{tf}"][e[m] // TF_MIN[tf] - 1]
    RD._GR.pop(c, None)

# ------------------------------------------------------------------ trend-judge bits (agree with the side, and with -side)
FN = ["none"]; specs = []
for htf in ("1h", "4h", "1d"):
    Zs = RD._states(COINS[0], htf)
    for k in sorted(Zs.keys()):
        if k.startswith(("c_", "l_")):
            FN.append(f"{k[0]}|{k[2:]}|{htf}"); specs.append((htf, k))
    FN += [f"jdir|{htf}", f"j4|{htf}"]; specs += [(htf, "jdir"), (htf, "j4")]
NF = len(FN); NW = (NF + 63) // 64
BITS = np.zeros((len(t), NW), np.uint64); BITSX = np.zeros((len(t), NW), np.uint64)


def setbit(B, f, mask):
    B[mask, f // 64] |= np.uint64(1) << np.uint64(f % 64)


setbit(BITS, 0, np.ones(len(t), bool)); setbit(BITSX, 0, np.ones(len(t), bool))
for ci, c in enumerate(COINS):
    mc = np.flatnonzero(coin == ci)
    for htf in ("1h", "4h", "1d"):
        Zs = RD._states(c, htf)
        close = Zs["ts"] + TF_MIN[htf] * MIN
        idx = np.searchsorted(close, t[mc], side="right") - 1
        ok = idx >= 0; ii = np.clip(idx, 0, None)
        w300 = ok & (Zs["nb"][ii] >= 300); w120 = ok & (Zs["nb"][ii] >= 120)
        sd = side[mc]
        for f, (h, k) in enumerate(specs, 1):
            if h != htf:
                continue
            if k == "jdir":
                st = np.nan_to_num(Zs["j_dir"][ii].astype(float)); wm = w120
            elif k == "j4":
                v = sum(np.nan_to_num(Zs[f"j_{q}"][ii].astype(float)) for q in ("V39", "S6", "OBV", "N12"))
                st = np.where(np.abs(v) == 4, np.sign(v), 0); wm = w120
            else:
                st = Zs[k][ii].astype(float); wm = w300
            setbit(BITS, f, mc[wm & (st == sd)]); setbit(BITSX, f, mc[wm & (st == -sd)])
        RD._STATES.pop((c, htf), None)
log("trend bits", NF, "filters")

# ------------------------------------------------------------------ walks: 24 exits, own side and the other side
EX = []
for lad in ("house", "tight"):
    for s in (("atr", 1.0), ("atr", 1.5), ("atr", 2.0), ("atr", 3.0), ("roe", 0.35), ("roe", 0.50), ("roe", 0.75)):
        EX.append((s, ("none", 0.0), lad))
for s in (("atr", 2.0), ("roe", 0.75)):
    for tp in (("roe", 0.30), ("roe", 0.50), ("roe", 1.00), ("atr", 2.0), ("atr", 3.0)):
        EX.append((s, tp, "none"))
XN = [HB.exit_name(x) for x in EX]
O, H, L, C, off = [], [], [], [], [0]
for c in COINS:
    g = grid(c); O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); off.append(off[-1] + g["n"]); drop(c)
o = np.concatenate(O); h = np.concatenate(H); l = np.concatenate(L); cl = np.concatenate(C); del O, H, L, C
off = np.array(off)
start = off[coin.astype(int)] + e; send = off[coin.astype(int) + 1]
p0 = o[start]
good = np.isfinite(p0) & np.isfinite(atr) & (atr > 0)
log("grid", len(o), "valid signals", int(good.sum()))
sk = np.array([0 if s[0] == "atr" else 1 for s, _, _ in EX], np.int8); sv = np.array([s[1] for s, _, _ in EX])
tk = np.array([{"none": 0, "roe": 1, "atr": 2}[q[0]] for _, q, _ in EX], np.int8); tv = np.array([q[1] for _, q, _ in EX])
lg = np.array([HB.LADS[x][0] for _, _, x in EX]); ll = np.array([HB.LADS[x][1] for _, _, x in EX])
ls = np.array([max(HB.LADS[x][2], 1e-9) for _, _, x in EX])
lev = HB.LEVC[coin.astype(int)]; atrf = np.where(good, atr / np.where(good, p0, 1), 0.01)
st2 = np.where(good, start, 0)
W, K, _ = HB.walk_all(o, h, l, cl, st2, send, side, lev, atrf, sk, sv, tk, tv, lg, ll, ls, HB.COST, HB.MARGIN, HB.MAXK)
K = K.astype(np.int16); W[~good] = np.nan
log("walks own side")
W2, K2, _ = HB.walk_all(o, h, l, cl, st2, send, (-side).astype(np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls,
                        HB.COST, HB.MARGIN, HB.MAXK)
K2 = K2.astype(np.int16); W2[~good] = np.nan
del o, h, l, cl
log("walks other side")

# ------------------------------------------------------------------ months and forward flags
dk = pd.to_datetime(t + KST, unit="ms")
mo = ((dk.year - 2020) * 12 + dk.month - 3).to_numpy().astype(np.int16)        # 0 = 2020-03
MO26 = (2026 - 2020) * 12 + 1 - 3; MOOCT = (2026 - 2020) * 12 + 10 - 3
fw = np.where(t < FWD_A, 0, np.where(t < MID, 1, 2)).astype(np.int8)
NC = 121 * 4
cptr = np.searchsorted(cell, np.arange(NC + 1)).astype(np.int64)


@njit(parallel=True, cache=True)
def score(cptr, t, mo, fw, side, BITS, W, K, W2, K2, flip, NF, MO26, MOOCT):
    NC = len(cptr) - 1; X = W.shape[1]
    R = np.zeros((NC, NF, 3, X, 13), np.float32)
    for job in prange(NC * NF):
        c = job // NF; f = job % NF
        a = cptr[c]; b = cptr[c + 1]
        if b - a < 10:
            continue
        buf = np.empty(b - a, np.int64)
        wd = f // 64; bt = np.uint64(1) << np.uint64(f % 64)
        for mode in range(3):
            nb = 0
            for i in range(a, b):
                s = -side[i] if flip[i] else side[i]
                if mode == 1 and s > 0:
                    continue
                if mode == 2 and s < 0:
                    continue
                if (BITS[i, wd] & bt) == 0:
                    continue
                buf[nb] = i; nb += 1
            if nb < 10:
                continue
            for x in range(X):
                free = -1; cur = -1; mprod = 1.0; done = False; mhit = 0
                nh = 0.0; act = 0.0; hit = 0.0; pos = 0.0; act6 = 0.0; hit6 = 0.0; pos6 = 0.0; slog = 0.0
                feq = 1.0; f1 = 1.0; f2 = 1.0; fn = 0.0; fwn = 0.0
                for p in range(nb):
                    i = buf[p]
                    if t[i] < free:
                        continue
                    w = W2[i, x] if flip[i] else W[i, x]
                    if w != w:
                        continue
                    k = K2[i, x] if flip[i] else K[i, x]
                    free = t[i] + np.int64(k) * 60000
                    if fw[i] > 0:
                        feq *= 1 + w; fn += 1
                        if w > 0:
                            fwn += 1
                        if fw[i] == 1:
                            f1 *= 1 + w
                        else:
                            f2 *= 1 + w
                        continue
                    if mo[i] != cur:
                        if cur >= 0 and cur < MOOCT:
                            slog += np.log(max(mprod, 1e-12))
                            if cur < MO26:
                                act += 1; hit += mhit; pos += 1 if mprod >= 1 else 0
                            else:
                                act6 += 1; hit6 += mhit; pos6 += 1 if mprod >= 1 else 0
                        cur = mo[i]; mprod = 1.0; done = False; mhit = 0
                    mprod *= 1 + w; nh += 1
                    if not done:
                        if mprod >= 5:
                            mhit = 1; done = True
                        elif mprod <= 0.5:
                            done = True
                if cur >= 0 and cur < MOOCT:
                    slog += np.log(max(mprod, 1e-12))
                    if cur < MO26:
                        act += 1; hit += mhit; pos += 1 if mprod >= 1 else 0
                    else:
                        act6 += 1; hit6 += mhit; pos6 += 1 if mprod >= 1 else 0
                r = R[c, f, mode, x]
                r[0] = nh; r[1] = act; r[2] = hit; r[3] = pos; r[4] = act6; r[5] = hit6; r[6] = pos6; r[7] = slog
                r[8] = np.log(max(feq, 1e-12)); r[9] = np.log(max(f1, 1e-12)); r[10] = np.log(max(f2, 1e-12))
                r[11] = fn; r[12] = fwn
    return R


np.savez(os.path.join(OUTD, "meta.npz"), FN=np.array(FN), XN=np.array(XN), cells=np.array(
    [f"{NM.name[NM.sid == s // 4].iloc[0] if (NM.sid == s // 4).any() else s // 4}@{TFS[s % 4]}" for s in range(NC)]),
    sets=np.array([NM.set[NM.sid == s // 4].iloc[0] if (NM.sid == s // 4).any() else "" for s in range(NC)]))
for run, seed in (("real", None), ("null1", 1), ("null2", 2)):
    flip = np.zeros(len(t), np.bool_) if seed is None else np.random.default_rng(seed).random(len(t)) < 0.5
    B = BITS if seed is None else np.where(flip[:, None], BITSX, BITS)
    R = score(cptr, t, mo, fw, side, B, W, K, W2, K2, flip, NF, MO26, MOOCT)
    np.save(os.path.join(OUTD, f"R_{run}.npy"), R.astype(np.float16))
    log("scored", run, R.shape)
    del R, B
log("done")
