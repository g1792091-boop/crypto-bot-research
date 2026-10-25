"""Owners 10/25 night, "keep searching": the pair-confirmed entries of s47 (strategy A's signal taken only when another
strategy B signalled the same coin and side within 1 h / 4 h; rule bot 36 + DeepSeek 44 on 15m / 30m / 1h / 4h) chosen
again every month from what worked BEFORE that month only ("good now and good in the past", the owners' idea for the
live ranking): at each KST month start, the top K pairs by their mean over the trailing L months (at least n signals,
mean above a floor), optionally also positive over all earlier months; traded during that month in one one-position
bot. Nothing is chosen with data from the month it trades, so every month from 2022-06 on is unseen when traded.
Fixed rules (BTC 40x / alts 30x, margin 40 %), owners' ladder L5, stop ROE -35 %, no hold limit, weekday entries,
DeepCoin 0.14 % (and 0.08 %). Control: B's signals from 300 days earlier, chosen the same way."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, COINS, MIN, ms, DAY, GT0   # noqa: E402
T00 = time.time()


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
D = FC.Data()
S = RD.signals(period=(ms("2021-06-01"), FWD_B))
S = S[FC.wk(S.t.to_numpy(np.int64)) & S.set.isin(["core", "ds"])].reset_index(drop=True)
N = len(S)
t = S.t.to_numpy(np.int64); coin = S.coin.to_numpy(np.int64); side = S.side.to_numpy(np.int8)
start = D.off[coin] + S.e.to_numpy(np.int64); send = D.off[coin + 1]
good = (start < send - 1) & np.isfinite(D.o[np.minimum(start, len(D.o) - 1)])
W, K_, Y_ = HB.walk_all(D.o, D.h, D.l, D.c, np.where(good, start, 0), send, side, HB.LEVC[coin], np.full(N, 0.01),
                        np.ones(1, np.int8), np.array([0.35]), np.zeros(1, np.int8), np.zeros(1), np.full(1, 0.12),
                        np.full(1, 0.10), np.full(1, 0.05), 0.0014, HB.MARGIN, 10 ** 12)
w = W[:, 0].astype(np.float64); del W, K_, Y_
ok = good & np.isfinite(w)
ym = FC.ym_of(t)
MONTHS = FC.months(202106, 202610)
NM = len(MONTHS)
MI = np.searchsorted(np.array(MONTHS), ym)
log("signals", N, "walked")
names = S.name.astype(str).to_numpy(); tfs = S.tf.astype(str).to_numpy()
cellname = pd.Series(names).str.cat(tfs, sep=" ").to_numpy()
cell, CELLS = pd.factorize(cellname)
NC = len(CELLS)
SIDX, _ = pd.factorize(names); CSI = np.array([SIDX[cell == c][0] for c in range(NC)])
G = cell * 2 + (side > 0); NG = NC * 2
KEY = coin * 2 + (side > 0)
SH = np.int64(2) ** 42; T0E = ms("2019-01-01")
ENC = KEY.astype(np.int64) * SH + (t - T0E)
WINS = (3600_000, 4 * 3600_000)
SHIFT = 300 * DAY
CIX = [np.flatnonzero(cell == c) for c in range(NC)]


EBC = {}


def enc_b(b, shift):
    if (b, shift) not in EBC:
        ib = CIX[b]
        EBC[(b, shift)] = np.sort(KEY[ib].astype(np.int64) * SH + (t[ib] + shift - T0E))
    return EBC[(b, shift)]


def conf_dt(b, shift, idx=None):
    """time since B's last same-coin same-side signal (ms) at every signal (or at idx); huge when none."""
    eb = enc_b(b, shift)
    e = ENC if idx is None else ENC[idx]; k = KEY if idx is None else KEY[idx]; si = SIDX if idx is None else SIDX[idx]
    j = np.searchsorted(eb, e, side="right") - 1; jj = np.clip(j, 0, None)
    same = (j >= 0) & ((eb[jj] // SH) == k) & (si != CSI[b])
    return np.where(same, e - eb[jj], np.int64(1) << 60)


okm = ok
gk = G[okm].astype(np.int64) * NM + MI[okm]; wk_ = w[okm]
SUM = np.zeros((2, len(WINS), NC, NG, NM), np.float32); CNT = np.zeros((2, len(WINS), NC, NG, NM), np.float32)
for b in range(NC):
    for ci_, shift in ((0, 0), (1, SHIFT)):
        dt = conf_dt(b, shift)[okm]
        for wi, W_ in enumerate(WINS):
            cm = dt <= W_
            SUM[ci_, wi, b] = np.bincount(gk[cm], wk_[cm], NG * NM).reshape(NG, NM)
            CNT[ci_, wi, b] = np.bincount(gk[cm], minlength=NG * NM).reshape(NG, NM)
    if b % 50 == 0:
        log("B", b, "/", NC)
log("monthly pair table")
CS = np.cumsum(SUM, axis=-1); CN = np.cumsum(CNT, axis=-1)            # cumulative over months


def trailing(arr_c, m, L):
    """sum over months [m-L, m-1] from the cumulative array (last axis)."""
    hi = arr_c[..., m - 1]
    lo = arr_c[..., m - L - 1] if m - L - 1 >= 0 else 0.0
    return hi - lo


def sim(m, prio, stop=0.35, cost=0.0014):
    ix = np.flatnonzero(m & ok)
    if not len(ix):
        return np.zeros(0, np.int64), np.zeros(0)
    ix = ix[np.lexsort((-prio[ix], t[ix]))]
    tt, cc, ss = t[ix], coin[ix], side[ix].astype(np.int64)
    cst = D.off[cc] + ((tt - GT0) // MIN); csend = D.off[cc + 1]
    ti, ww, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, ss, tt, csend, HB.LEVC[cc].astype(float), stop, 0, 0.0, 0.12, 0.10, 0.05, cost, HB.MARGIN)
    return tt[ti], ww


def read(t2, ww):
    fw = (t2 >= FWD_A) & (t2 < FWD_B)
    out = {}
    for lab, a, z in (("2022-06~2024-12", 202206, 202412), ("2025-01~2026-09", 202501, 202609)):
        r = FC.read(t2, ww, a, z)
        out[lab] = {k: r[k] for k in ("기하평균", "중간값", "x3+", "-50%", "달 진입", "최고")}
    out["10월 20일"] = {"배수": round(float(np.prod(1 + ww[fw])), 3), "거래": int(fw.sum())}
    return out


M0 = MONTHS.index(202206)
GM = G.astype(np.int64) * NM + MI
GM = np.where(ok, GM, NG * NM)                               # unusable signals go to a dead bucket
ORDg = np.argsort(GM, kind="stable"); BNDg = np.searchsorted(GM[ORDg], np.arange(NG * NM + 2))
RES = {}
for ci_, cn, shift in ((0, "실제", 0), (1, "대조: B는 300일 전", SHIFT)):
    for L in (6, 12):
        for K in (10, 30, 100):
            for need_all in (False, True):
                floor = 0.005
                picks = {}                                     # (b, wi) -> list of (g, month index, score)
                for m in range(M0, NM):
                    s_ = trailing(CS[ci_], m, L); n_ = trailing(CN[ci_], m, L)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        mean = s_ / n_
                    okp = (n_ >= 20) & (mean > floor)
                    if need_all:
                        with np.errstate(invalid="ignore", divide="ignore"):
                            allm = CS[ci_][..., m - 1] / CN[ci_][..., m - 1]
                        okp &= (CN[ci_][..., m - 1] >= 60) & (allm > 0)
                    sc = np.where(okp, mean, -np.inf).ravel()
                    top = np.argpartition(-sc, min(K, len(sc) - 1))[:K]
                    top = top[np.isfinite(sc[top])]
                    for f in top:
                        wi, b, g = np.unravel_index(f, (len(WINS), NC, NG))
                        picks.setdefault((int(b), int(wi)), []).append((int(g), m, float(sc[f])))
                keep = np.zeros(N, bool); prio = np.zeros(N)
                for (b, wi), lst in picks.items():
                    for g, m, scv in lst:
                        q = g * NM + m; idx = ORDg[BNDg[q]:BNDg[q + 1]]
                        if not len(idx):
                            continue
                        sel = idx[conf_dt(b, shift, idx) <= WINS[wi]]
                        keep[sel] = True; prio[sel] = np.maximum(prio[sel], scv)
                npairs = sum(len(v) for v in picks.values())
                for cost in (0.0014, 0.0008):
                    r = read(*sim(keep, prio, 0.35, cost))
                    r["달마다 고른 짝 (평균)"] = round(npairs / (NM - M0), 1)
                    key = f"{cn} / 지난 {L}달 상위 {K}짝{' · 그 전 전체도 플러스' if need_all else ''} / 비용 {cost * 100:.2f}%"
                    RES[key] = r
                    log(key, r["2022-06~2024-12"]["기하평균"], r["2025-01~2026-09"]["기하평균"], r["10월 20일"])
json.dump({"읽는 법": __doc__, "결과": RES}, open(os.path.join(OUTD, "rollpairs49.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
