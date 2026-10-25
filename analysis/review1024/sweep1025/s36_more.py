"""Owners 10/25 night, more families for the month's return (no hold limit, fixed rules, one position, weekday entries,
DeepCoin 0.14 % / 0.08 %, the owners' two ladders L5 / L10 with stops ROE -25 / -35 / -50 / -75 %):
  D  trend only in loud markets: always-in along a trend judge (V3.9 4h / 1d, trend-bot direction 4h, EMA50/200 4h,
     Supertrend 4h, Donchian 55 1d) only while BTC's 1-day realized volatility is above its 90-day 70th / 90th percentile
  F  agreement: the price model's picks (thresholds 0 / 0.005 / 0.01) only when the V3.9 4h or the trend-bot 4h
     direction points the same way
  G  funding extremes: the settled funding above its 90-day 95th (99th) percentile or below the 5th (1st): against the
     crowd (short when longs pay a lot) and with it
  J  big candles: a closed 1h / 4h candle longer than 2 / 3 ATR(14) closing in its top (bottom) quarter: follow it, fade it
  K  big 4h moves: the coin up (down) more than 4 % / 7 % over the last 4 h: follow it, fade it
each on every coin alone and on the 6 coins together (the coin with the largest 4h move first)."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import COINS, MIN, TF_MIN, grid, bars, ms   # noqa: E402
T00 = time.time()


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


D = FC.Data()
Q = FC.q15()
log("data ready")
CO = list(range(6)) + ["6개"]


def nm(co):
    return "6개" if co == "6개" else COINS[co].replace("USDT", "")


def coins_of(co):
    return range(6) if co == "6개" else [co]


SETS = {}
# ---------------------------------------------------------------- D: trend in loud markets
bt = Q[0]["T"]; bc = Q[0]["c"]
rv = pd.Series(np.r_[np.nan, np.diff(np.log(bc))]).rolling(96).std()
VOLQ = {q: (rv >= rv.rolling(8640, min_periods=2000).quantile(q)).to_numpy() for q in (0.7, 0.9)}
for ci in range(6):
    j = np.clip(np.searchsorted(bt, Q[ci]["T"]), 0, len(bt) - 1); okj = bt[j] == Q[ci]["T"]
    Q[ci]["vol"] = {q: okj & v[j] for q, v in VOLQ.items()}
for jn in ("j_V39@4h", "j_dir@4h", "c_T1_EMA50_200@4h", "c_T5_ST10_3@4h", "c_T6_DON55@1d", "j_V39@1d"):
    for q in (0.7, 0.9):
        for co in CO:
            SETS[f"D 변동성 상위 {int(100 - q * 100)}%에서 추세 / {jn} / {nm(co)}"] = FC.cand(
                Q, lambda ci, jn=jn, q=q: np.where(Q[ci]["vol"][q], Q[ci]["st"][jn], 0), coins_of(co))
log("D", len(SETS))
# ---------------------------------------------------------------- F: price model + trend agreement
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
pl, ps = P[:, 0, 2], P[:, 1, 2]; best = np.fmax(pl, ps); sd_ = np.where(pl >= ps, 1, -1)
for jn in ("j_V39@4h", "j_dir@4h"):
    agree = np.zeros(len(TT), bool)
    for ci in range(6):
        m = CC == ci; T = Q[ci]["T"]; j = np.clip(np.searchsorted(T, TT[m]), 0, len(T) - 1)
        agree[m] = (T[j] == TT[m]) & (Q[ci]["st"][jn][j] == sd_[m])
    for thr in (0.0, 0.005, 0.01):
        mm = np.isfinite(best) & (best > thr) & FC.wk(TT) & agree
        SETS[f"F 가격모델 {thr} + {jn} 같은 방향"] = (TT[mm], CC[mm], sd_[mm], best[mm])
log("F", len(SETS))
# ---------------------------------------------------------------- G: funding extremes
for ci, cn in enumerate(COINS):
    g = grid(cn); fr = np.nan_to_num(g["fund"]); fi = np.flatnonzero(fr != 0)
    ft = FC.GT0 + fi.astype(np.int64) * MIN; fs = pd.Series(fr[fi])
    qs = {p: fs.rolling(270, min_periods=90).quantile(p).to_numpy() for p in (0.01, 0.05, 0.95, 0.99)}
    T = Q[ci]["T"]; j = np.searchsorted(ft, T, side="right") - 1; ok = (j >= 0) & (T < ft[-1] + 9 * 3600 * 1000)
    jj = np.clip(j, 0, None); f_ = np.where(ok, fr[fi][jj], np.nan)
    Q[ci]["fx"] = {}
    for lo, hi in ((0.05, 0.95), (0.01, 0.99)):
        qlo = np.where(ok, qs[lo][jj], np.nan); qhi = np.where(ok, qs[hi][jj], np.nan)
        Q[ci]["fx"][hi] = np.where(f_ > qhi, -1, np.where(f_ < qlo, 1, 0)).astype(np.int64)
for hi in (0.95, 0.99):
    for mode, sg in (("군중 반대", 1), ("군중 따라", -1)):
        for co in CO:
            SETS[f"G 펀딩 극단 {int(hi * 100)}% {mode} / {nm(co)}"] = FC.cand(Q, lambda ci, hi=hi, sg=sg: sg * Q[ci]["fx"][hi], coins_of(co))
log("G", len(SETS))
# ---------------------------------------------------------------- J: big candles
for ci, cn in enumerate(COINS):
    Q[ci]["big"] = {}
    for tf in ("1h", "4h"):
        b = bars(cn, tf); o_, h_, l_, c_ = (b[k].to_numpy() for k in ("open", "high", "low", "close"))
        pc = np.r_[c_[0], c_[:-1]]; tr = np.maximum(h_ - l_, np.maximum(np.abs(h_ - pc), np.abs(l_ - pc)))
        atr_prev = np.r_[np.nan, pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()[:-1]]
        rng_ = h_ - l_; cp = (c_ - l_) / np.maximum(rng_, 1e-12)
        close = b.ts.to_numpy(np.int64) + TF_MIN[tf] * MIN
        T = Q[ci]["T"]; j = np.searchsorted(close, T); jj = np.clip(j, 0, len(close) - 1); at = close[jj] == T
        for k in (2.0, 3.0):
            dirn = np.where((rng_ > k * atr_prev) & (cp >= 0.75) & (c_ > o_), 1,
                            np.where((rng_ > k * atr_prev) & (cp <= 0.25) & (c_ < o_), -1, 0))
            Q[ci]["big"][(tf, k)] = np.where(at, dirn[jj], 0).astype(np.int64)
for tf in ("1h", "4h"):
    for k in (2.0, 3.0):
        for mode, sg in (("따라", 1), ("반대", -1)):
            for co in CO:
                SETS[f"J 큰 봉 {tf} {k:g}ATR {mode} / {nm(co)}"] = FC.cand(Q, lambda ci, tf=tf, k=k, sg=sg: sg * Q[ci]["big"][(tf, k)], coins_of(co))
log("J", len(SETS))
# ---------------------------------------------------------------- K: big 4h moves
for x in (0.04, 0.07):
    for mode, sg in (("따라", 1), ("반대", -1)):
        for co in CO:
            SETS[f"K 4시간 {int(x * 100)}% 넘는 움직임 {mode} / {nm(co)}"] = FC.cand(
                Q, lambda ci, x=x, sg=sg: sg * np.where(np.nan_to_num(Q[ci]["r16"]) > x, 1, np.where(np.nan_to_num(Q[ci]["r16"]) < -x, -1, 0)),
                coins_of(co))
log("sets", len(SETS))
res = {}
for n, (lab, (t, coin, side, prio)) in enumerate(SETS.items()):
    res[lab] = {}
    for cost in (0.0014, 0.0008):
        res[lab][f"{cost * 100:.2f}%"] = FC.run(D, np.asarray(t, np.int64), np.asarray(coin), np.asarray(side),
                                                np.asarray(prio, float), cost)
    if n % 20 == 0:
        log(n, "/", len(SETS), lab)
json.dump(res, open(os.path.join(OUTD, "more36.json"), "w"), ensure_ascii=False, default=float)
log("saved")
rows = []
for lab, byc in res.items():
    for cst_, byx in byc.items():
        for xn, r in byx.items():
            rows.append((lab, cst_, xn, r))
for cst_ in ("0.14%", "0.08%"):
    rr = [x for x in rows if x[1] == cst_]
    print(f"\n== {cst_}: top 15 by the pick period's geometric mean month (2022-01..2024-12), then the check period")
    for lab, _, xn, r in sorted(rr, key=lambda x: -x[3]["고르기"]["기하평균"])[:15]:
        p, c, f = r["고르기"], r["확인"], r["10월"];
        print(f"{lab} | {xn} | 고르기 기하 ×{p['기하평균']} 중간 ×{p['중간값']} x3+ {p['x3+']} x5+ {p['x5+']} -50% {p['-50%']} /월 {p['달 진입']}"
              f" || 확인 기하 ×{c['기하평균']} 중간 ×{c['중간값']} x3+ {c['x3+']} x5+ {c['x5+']} -50% {c['-50%']} || 10월 ×{f['중간값']}")
    print("count with check median >= x3:", sum(1 for x in rr if x[3]["확인"]["중간값"] >= 3), "/ check geometric >= x2:",
          sum(1 for x in rr if x[3]["확인"]["기하평균"] >= 2), "of", len(rr))
log("done")
