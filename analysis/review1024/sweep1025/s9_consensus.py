"""New method 1 (10/25): consensus signals. At every 15m close, count the signals of all 121 coded strategies (every
timeframe) on each coin and side whose bar closed in the last hour; enter when one side has at least k of them and at
least twice the other side. Same sizing / cost / walker, one position across the 6 coins. Read per year, months with a
fresh start (x5 before -50 %), 2026 start days, the forward 19 days; coin-flip directions for luck."""
import os, sys, json, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
src = open(os.path.join(HERE, "s2.py")).read()
_pre = src.split("# ------------------------------------------------------------------ trend-judge bits")[0]
exec(_pre.replace("cache=True", "cache=False"))          # signals sid/tfi/coin/side/e/t, NM, HB, RD, log, FWD_A, MID, KST
from common import grid, drop                            # noqa: E402

G15 = 15
n15 = int((Z - RD.T0) // (G15 * MIN)) + 2
cnt = np.zeros((6, 2, n15), np.int32)                     # coin, side (0 long, 1 short), 15m close index
gi = (e // G15).astype(np.int64)
np.add.at(cnt, (coin.astype(np.int64), (side < 0).astype(np.int64), gi), 1)
win = np.zeros_like(cnt)
for lag in range(4):                                      # bars closed in the last hour: this close and the 3 before
    win[:, :, lag:] += cnt[:, :, :n15 - lag]
log("consensus counts; long-window quantiles", np.percentile(win[:, 0][win[:, 0] > 0], [50, 90, 99, 99.9]).tolist())

# candidate entries: every 15m close where one side dominates with at least KMIN signals
KMIN = 6
rows = []
for c in range(6):
    L = win[c, 0]; S = win[c, 1]
    for sd, a, b in ((1, L, S), (-1, S, L)):
        g = np.flatnonzero((a >= KMIN) & (a >= 2 * b))
        rows.append(np.c_[np.full(len(g), c), np.full(len(g), sd), g, a[g], b[g]])
C = np.concatenate(rows).astype(np.int64)
ce = C[:, 2] * G15                                         # entry minute (= the 15m close)
ct = RD.T0 + ce * MIN
ok = (ct >= A) & (ct < Z)
C = C[ok]; ce = ce[ok]; ct = ct[ok]
log("candidate entries", len(C))

O, H, L_, Cl, off = [], [], [], [], [0]
atr = np.full(len(C), np.nan)
for ci, cn in enumerate(COINS):
    g = grid(cn); O.append(g["o"]); H.append(g["h"]); L_.append(g["l"]); Cl.append(g["c"]); off.append(off[-1] + g["n"])
    Gq = RD._grid(cn); m = C[:, 0] == ci
    atr[m] = Gq["atr14_15m"][ce[m] // 15 - 1]; RD._GR.pop(cn, None); drop(cn)
o = np.concatenate(O); h = np.concatenate(H); l = np.concatenate(L_); cl = np.concatenate(Cl); off = np.array(off)
del O, H, L_, Cl
start = off[C[:, 0]] + ce; send = off[C[:, 0] + 1]
p0 = o[start]; good_ = np.isfinite(p0) & np.isfinite(atr) & (atr > 0)
EXC = [(("roe", 0.75), ("none", 0.0), "house"), (("atr", 2.0), ("none", 0.0), "house"),
       (("roe", 0.75), ("roe", 1.0), "none"), (("roe", 0.75), ("atr", 3.0), "none"), (("atr", 2.0), ("atr", 2.0), "none")]
XN = [HB.exit_name(x) for x in EXC]
sk = np.array([0 if s_[0] == "atr" else 1 for s_, _, _ in EXC], np.int8); sv = np.array([s_[1] for s_, _, _ in EXC])
tk = np.array([{"none": 0, "roe": 1, "atr": 2}[q[0]] for _, q, _ in EXC], np.int8); tv = np.array([q[1] for _, q, _ in EXC])
lg = np.array([HB.LADS[x][0] for _, _, x in EXC]); ll = np.array([HB.LADS[x][1] for _, _, x in EXC])
ls = np.array([max(HB.LADS[x][2], 1e-9) for _, _, x in EXC])
lev = HB.LEVC[C[:, 0]]; atrf = np.where(good_, atr / np.where(good_, p0, 1), 0.01); st2 = np.where(good_, start, 0)
sdv = C[:, 1].astype(np.int8)
Wc, Kc, _ = HB.walk_all(o, h, l, cl, st2, send, sdv, lev, atrf, sk, sv, tk, tv, lg, ll, ls, HB.COST, HB.MARGIN, HB.MAXK)
Wf, Kf, _ = HB.walk_all(o, h, l, cl, st2, send, (-sdv).astype(np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls, HB.COST,
                        HB.MARGIN, HB.MAXK)
Wc[~good_] = np.nan; Wf[~good_] = np.nan
log("walks done")
dk2 = pd.to_datetime(ct + KST, unit="ms"); yy = dk2.year.to_numpy(); ymk = (dk2.year * 100 + dk2.month).to_numpy()


def one_pos(mask, x, Wm, Km):
    ii = np.flatnonzero(mask & good_)
    ii = ii[np.argsort(ct[ii], kind="stable")]
    keep = []; free = -1
    for i in ii:
        if ct[i] >= free:
            keep.append(i); free = ct[i] + int(Km[i, x]) * 60000
    return np.array(keep, np.int64)


def read(idx, x, Wm):
    w = Wm[idx, x]; t_ = ct[idx]; out = {"거래": len(idx)}
    for y in range(2020, 2027):
        m = (yy[idx] == y) & (t_ < FWD_A)
        out[str(y)] = round(float(w[m].mean()), 4) if m.any() else None
    f = t_ >= FWD_A
    out["10월19일"] = round(float(np.prod(1 + w[f])), 2); out["10월 거래"] = int(f.sum())
    hit = bust = 0; mon = 0
    for k in np.unique(ymk[idx]):
        if k >= 202610:
            continue
        eq = np.cumprod(1 + w[ymk[idx] == k]); mon += 1
        for v in eq:
            if v >= 5:
                hit += 1; break
            if v <= 0.5:
                bust += 1; break
    out["x5달"] = hit; out["-50%달"] = bust; out["달"] = mon
    res = []
    for s0 in range(ms("2026-01-01"), ms("2026-09-25"), 86_400_000):
        i = np.searchsorted(t_, s0); eq = 1.0; r = 0
        while i < len(t_) and t_[i] < s0 + 30 * 86_400_000:
            eq *= 1 + w[i]; i += 1
            if eq >= 5:
                r = 1; break
            if eq <= 0.5:
                r = -1; break
        res.append(r)
    res = np.array(res); out["2026 30일 x5/-50%"] = [round(float((res == 1).mean()), 3), round(float((res == -1).mean()), 3)]
    return out


res = {}
for k in (6, 8, 10, 14, 20):
    for dom in (2, 4):
        base = (C[:, 3] >= k) & (C[:, 3] >= dom * C[:, 4])
        for x in range(len(EXC)):
            idx = one_pos(base, x, Wc, Kc)
            r = read(idx, x, Wc)
            # coin flip: the same entries (same one-position path), the other side
            rf = read(one_pos(base, x, Wf, Kf), x, Wf)
            res[f"k{k}/dom{dom}/{XN[x]}"] = {"real": r, "flip": rf}
            print(f"k>={k} dom x{dom} | {XN[x]} | real", json.dumps(r, ensure_ascii=False), "| flip x5달", rf["x5달"],
                  "2026", rf["2026"], "10월", rf["10월19일"], flush=True)
json.dump(res, open(os.path.join(OUTD, "consensus9.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
