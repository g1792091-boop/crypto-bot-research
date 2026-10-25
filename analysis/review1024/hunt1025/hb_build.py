"""Hunt 10/25 step 1: every forward signal (121 coded strategies x 15m/30m/1h/4h x 6 coins, bar close 10-05 15:00 ..
10-24 14:00 UTC) walked on the 1m grid with 330 exits at the owners' fixed sizing (BTC 40x, alts 30x, margin 40 %).
Also the higher-bar trend states used as direction filters. Output: OUT/fwd.npz + OUT/sig.pkl.gz."""
import os, sys, time
import numpy as np, pandas as pd
from numba import njit, prange

RD_DIR = "/home/user/crypto-bot-research/analysis/review1024/roles/data"
sys.path.insert(0, RD_DIR)
import rolesdata as RD          # noqa: E402
from common import *            # noqa: E402,F401,F403

HERE = os.path.dirname(os.path.abspath(__file__))
OUTD = os.path.join(HERE, "out"); os.makedirs(OUTD, exist_ok=True)
COST = 0.0012                   # round trip (Bybit measured 4.41 + 1.39 bp per side ~ 5.8 bp; market orders only)
MARGIN = 0.40
LEVC = np.array([40.0 if c == "BTCUSDT" else 30.0 for c in COINS])
MAXK = 72 * 60                  # time exit after 72 h at the close

# ---------------------------------------------------------------- exits (net ROE at the coin's leverage, or ATR)
STOPS = [("atr", k) for k in (0.5, 1.0, 1.5, 2.0, 3.0)] + [("roe", s) for s in (0.10, 0.20, 0.35, 0.50, 0.75)]
TPS = [("none", 0.0)] + [("roe", t) for t in (0.05, 0.10, 0.20, 0.30, 0.50, 1.00)] + [("atr", m) for m in (0.5, 1.0, 2.0, 3.0)]
LADS = {"none": (0.0, 0.0, 0.0), "house": (0.12, 0.10, 0.05), "tight": (0.06, 0.04, 0.03)}   # trigger, lock, step (net ROE)
EXITS = [(s, t, l) for s in STOPS for t in TPS for l in LADS]


def exit_name(x):
    (sk, sv), (tk, tv), l = x
    st = f"손절 {sv:g}ATR" if sk == "atr" else f"손절 ROE -{sv*100:g}%"
    tp = "익절 없음" if tk == "none" else (f"익절 {tv:g}ATR" if tk == "atr" else f"익절 ROE +{tv*100:g}%")
    lad = {"none": "계단 없음", "house": "계단 12→10 / 5", "tight": "계단 6→4 / 3"}[l]
    return f"{st} · {tp} · {lad}"


@njit(parallel=True, cache=True)
def walk_all(o, h, l, c, start, stop_end, side, lev, atrf, ex_sk, ex_sv, ex_tk, ex_tv, ex_lg, ex_ll, ex_ls,
             cost, margin, maxk):
    n = len(start); m = len(ex_sk)
    W = np.zeros((n, m), np.float32); K = np.zeros((n, m), np.int32); Y = np.zeros((n, m), np.int8)
    for i in prange(n):
        e0 = start[i]; e1 = min(stop_end[i], e0 + maxk); sd = side[i]; L = lev[i]; p0 = o[e0]
        dliq = 1.0 / L - 0.005
        for x in range(m):
            d = ex_sv[x] * atrf[i] if ex_sk[x] == 0 else ex_sv[x] / L - cost
            if d <= 0.0005:
                d = 0.0005
            liq = d >= dliq
            if liq:
                d = dliq
            u = 1e9
            if ex_tk[x] == 1:
                u = ex_tv[x] / L + cost
            elif ex_tk[x] == 2:
                u = ex_tv[x] * atrf[i]
            g1 = ex_lg[x] / L + cost if ex_lg[x] > 0 else 1e9
            l1 = ex_ll[x] / L + cost; stp = ex_ls[x] / L
            lock = -1e9; best = 0.0; mv = 0.0; why = 3; kk = e1 - e0
            for j in range(e0, e1):
                if sd > 0:
                    oj = o[j] / p0 - 1; lj = l[j] / p0 - 1; hj = h[j] / p0 - 1
                else:
                    oj = 1 - o[j] / p0; lj = 1 - h[j] / p0; hj = 1 - l[j] / p0
                floor = max(-d, lock)
                if oj <= floor:
                    mv = oj; why = 0 if lock < -d + 1e-12 or lock == -1e9 else 1; kk = j - e0; break
                if lj <= floor:
                    mv = floor; why = 0 if lock == -1e9 else 1; kk = j - e0; break
                if hj >= u:
                    mv = max(u, oj); why = 2; kk = j - e0; break
                if hj > best:
                    best = hj
                    if best >= g1:
                        nl = l1 + np.floor((best - g1) / stp + 1e-9) * stp
                        if nl > lock:
                            lock = nl
                if j == e1 - 1:
                    mv = c[j] / p0 - 1 if sd > 0 else 1 - c[j] / p0
                    why = 4 if e1 < stop_end[i] else 3; kk = j - e0
            if why == 0 and liq and mv <= -d + 1e-12:
                w = -margin
            else:
                w = margin * L * (mv - cost)
                if w < -margin:
                    w = -margin
            W[i, x] = w; K[i, x] = kk + 1; Y[i, x] = why
    return W, K, Y


def main():
    t0 = time.time()
    A = ms("2026-10-05 15:00"); Z = ms("2026-10-24 14:12")
    S = RD.signals(period=(A, Z))
    # ATR14 of the signal bar on its own timeframe, entry = open of the minute after the bar close
    atr = np.full(len(S), np.nan)
    for ci, coin in enumerate(COINS):
        G = RD._grid(coin)
        for tf in TFS:
            m = (S.coin.to_numpy() == ci) & (S.tf.to_numpy() == tf)
            j = S.e.to_numpy()[m] // TF_MIN[tf] - 1
            atr[m] = G[f"atr14_{tf}"][j]
    S["atr"] = atr
    # trend states of the last closed higher bar
    SRC = ["V39_ALL", "S6_EMA_DMI_ADX", "N12_ICHI_AO", "OBV_S", "VO1_OBV_X_MA20", "O2_RSI14_X50", "O8_ROC21",
           "O9_CMO14", "F7_RF_TRIPLE", "T1_EMA50_200", "T5_ST10_3", "N24_DMI"]
    for htf in ("1h", "4h", "1d"):
        S = RD.add_states(S, htf, SRC, kind="c")
        S = RD.add_states(S, htf, ["V39_ALL", "OBV_S", "N24_DMI"], kind="l")
        idx = RD.htf_index(S, htf)
        for k in ("dir", "raw3", "V39", "S6", "OBV", "N12"):
            col = np.zeros(len(S), np.int8)
            for ci, coin in enumerate(COINS):
                m = (S.coin.to_numpy() == ci) & (idx >= 0)
                Zs = RD._states(coin, htf)
                v = np.nan_to_num(Zs[f"j_{k}"][idx[m]].astype(float))
                col[m] = np.where(Zs["nb"][idx[m]] >= 120, v, 0).astype(np.int8)
            S[f"j{htf}_{k}"] = col
    print("signals + states", len(S), round(time.time() - t0), "s", flush=True)
    # minute arrays (slice from the first entry of each coin to the data end), concatenated
    O, H, Lo, C = [], [], [], []; start = np.zeros(len(S), np.int64); send = np.zeros(len(S), np.int64); p0 = np.zeros(len(S))
    off = 0
    for ci, coin in enumerate(COINS):
        g = grid(coin); m = S.coin.to_numpy() == ci
        e = S.e.to_numpy()[m].astype(np.int64); a = int(e.min()); b = g["n"]
        O.append(g["o"][a:b]); H.append(g["h"][a:b]); Lo.append(g["l"][a:b]); C.append(g["c"][a:b])
        start[m] = off + e - a; send[m] = off + (b - a); off += b - a
        drop(coin)
    o = np.concatenate(O); h = np.concatenate(H); lo = np.concatenate(Lo); c = np.concatenate(C)
    p0 = o[start]; S["p0"] = p0
    ok = np.isfinite(p0) & np.isfinite(S.atr.to_numpy()) & (S.atr.to_numpy() > 0)
    S = S[ok].reset_index(drop=True); start = start[ok]; send = send[ok]
    print("minutes", len(o), "signals", len(S), round(time.time() - t0), "s", flush=True)
    sk = np.array([0 if s[0] == "atr" else 1 for s, _, _ in EXITS], np.int8)
    sv = np.array([s[1] for s, _, _ in EXITS]); tk = np.array([{"none": 0, "roe": 1, "atr": 2}[t[0]] for _, t, _ in EXITS], np.int8)
    tv = np.array([t[1] for _, t, _ in EXITS]); lg = np.array([LADS[x][0] for _, _, x in EXITS])
    ll = np.array([LADS[x][1] for _, _, x in EXITS]); ls = np.array([max(LADS[x][2], 1e-9) for _, _, x in EXITS])
    lev = LEVC[S.coin.to_numpy(int)]; atrf = S.atr.to_numpy() / S.p0.to_numpy()
    W, K, Y = walk_all(o, h, lo, c, start, send, S.side.to_numpy(np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls,
                       COST, MARGIN, MAXK)
    print("walks", W.shape, round(time.time() - t0), "s", flush=True)
    # coin-flip twin of every signal (same entry, other side) for the luck read
    W2, K2, Y2 = walk_all(o, h, lo, c, start, send, (-S.side.to_numpy()).astype(np.int8), lev, atrf, sk, sv, tk, tv,
                          lg, ll, ls, COST, MARGIN, MAXK)
    S["x_ms"] = 0
    np.savez(os.path.join(OUTD, "fwd.npz"), W=W, K=K, Y=Y, W2=W2, K2=K2, Y2=Y2)
    S.to_pickle(os.path.join(OUTD, "sig.pkl.gz"))
    pd.DataFrame({"exit": range(len(EXITS)), "name": [exit_name(x) for x in EXITS]}).to_csv(
        os.path.join(OUTD, "exits.csv"), index=False)
    print("done", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
