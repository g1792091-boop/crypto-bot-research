"""Owners 10/25 night: "look at every loss and why". Loss autopsy of the best entry so far, the price-only model's picks
(the three exits' predictions agree, causal 30-day quantile, 1 / 2 / 3 a day; and E5 above 0.01), as the one-position
bot trades them (owners' ladder L5, stop ROE -25 / -35 %, no hold limit, weekday entries, DeepCoin 0.14 %):
per trade, split by BTC 4h regime x side, the coin's own 4h regime x side, coin, KST session, volatility (low / mid /
high), how it ended and how fast. Then the fixes: drop the groups that lost on 2022-01 .. 2024-12 (pick period only) and
read 2025-01 .. 2026-09 (unseen) against dropping as many random groups."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, COINS, MIN, bars, KST, DAY, GT0  # noqa: E402
sys.path.insert(0, "/home/user/crypto-bot-research")
from paperbot.rmember import regimes                     # noqa: E402
D = FC.Data()
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
# attributes at every sample time
b4 = bars("BTCUSDT", "4h"); RB, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
CB = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000


def attrs(t, coin):
    j = np.searchsorted(CB, t, side="right") - 1
    btc = np.where(j >= 0, RB[np.clip(j, 0, None)], 2)
    own = np.full(len(t), 2); vol = np.full(len(t), 1)
    for ci, cn in enumerate(COINS):
        m = coin == ci
        if not m.any():
            continue
        bc = bars(cn, "4h"); R_, _ = regimes(bc.high.to_numpy(), bc.low.to_numpy(), bc.close.to_numpy())
        cc = bc.ts.to_numpy(np.int64) + 4 * 3600 * 1000; jj = np.searchsorted(cc, t[m], side="right") - 1
        own[m] = np.where(jj >= 0, R_[np.clip(jj, 0, None)], 2)
        b15 = bars(cn, "15m"); c15 = b15.close.to_numpy(); T15 = b15.ts.to_numpy(np.int64) + 15 * MIN
        rv = pd.Series(np.r_[np.nan, np.diff(np.log(c15))]).rolling(96).std()
        lo_ = rv.rolling(8640, min_periods=2000).quantile(1 / 3).to_numpy(); hi_ = rv.rolling(8640, min_periods=2000).quantile(2 / 3).to_numpy()
        rv = rv.to_numpy(); jj = np.clip(np.searchsorted(T15, t[m], side="right") - 1, 0, None)
        vol[m] = np.where(rv[jj] < lo_[jj], 0, np.where(rv[jj] > hi_[jj], 2, 1))
    hr = ((t + KST) // 3600_000) % 24
    ses = np.where((hr >= 9) & (hr < 16), 0, np.where((hr >= 16) & (hr < 22), 1, np.where((hr >= 22) | (hr < 2), 2, 3)))
    return btc, own, vol, ses


SETS = {}
agg = np.nanmin(P, axis=2)
best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
te = np.flatnonzero(np.isfinite(best) & FC.wk(TT)); te = te[np.argsort(TT[te], kind="stable")]
day = (TT[te] + KST) // DAY; ud, st = np.unique(day, return_index=True); bd = list(st) + [len(te)]
b = best[te]
for per_day in (1, 2, 3):
    q = 1 - per_day / 576.0; keep = np.zeros(len(te), bool)
    for i, d in enumerate(ud):
        lo = np.searchsorted(day, d - 30); hi = bd[i]
        if hi - lo < 2000:
            continue
        keep[bd[i]:bd[i + 1]] = b[bd[i]:bd[i + 1]] > np.quantile(b[lo:hi], q)
    k = te[keep]
    SETS[f"세 예측 동의 · 하루 {per_day}개"] = (TT[k], CC[k], side[k], best[k])
e5 = np.fmax(P[:, 0, 2], P[:, 1, 2]); s5 = np.where(P[:, 0, 2] >= P[:, 1, 2], 1, -1)
mm = np.isfinite(e5) & (e5 > 0.01) & FC.wk(TT)
SETS["E5 기준 0.01"] = (TT[mm], CC[mm], s5[mm], e5[mm])
DIMS = {"btc": ["상승", "하락", "횡보"], "own": ["상승", "하락", "횡보"], "vol": ["낮음", "중간", "높음"],
        "ses": ["아시아 09-16", "유럽 16-22", "미국 22-02", "새벽 02-09"]}
OUT, txt = {}, []
rng = np.random.default_rng(41)


def sim(t, c, s, p, stop):
    o_ = np.lexsort((-p, t)); t, c, s, p = t[o_], c[o_], s[o_], p[o_]
    cst = D.off[c] + ((t - GT0) // MIN); csend = D.off[c + 1]
    ti, w, k = FC.seq_sim(D.o, D.h, D.l, D.c, cst, s.astype(np.int64), t, csend, HB.LEVC[c].astype(float), stop, 0, 0.0,
                          0.12, 0.10, 0.05, 0.0014, HB.MARGIN)
    return t[ti], c[ti], s[ti], w, k


for lab, (t, c, s, p) in SETS.items():
    t = np.asarray(t, np.int64); c = np.asarray(c, np.int64); s = np.asarray(s, np.int64); p = np.asarray(p, float)
    btc, own, vol, ses = attrs(t, c)
    G = {"btc": btc, "own": own, "vol": vol, "ses": ses}
    for stop in (0.25, 0.35):
        tt, cc, ss, w, k = sim(t, c, s, p, stop)
        ym = FC.ym_of(tt); P_ = (ym >= 202201) & (ym <= 202412); C_ = (ym >= 202501) & (ym <= 202609)
        a_ = attrs(tt, cc)
        df = pd.DataFrame({"w": w, "k": k, "side": np.where(ss > 0, "롱", "숏"), "coin": np.asarray(COINS)[cc],
                           "btc": np.asarray(DIMS["btc"])[a_[0]], "own": np.asarray(DIMS["own"])[a_[1]],
                           "vol": np.asarray(DIMS["vol"])[a_[2]], "ses": np.asarray(DIMS["ses"])[a_[3]],
                           "per": np.where(P_, "고르기", np.where(C_, "확인", "기타"))})
        df = df[df.per != "기타"]
        key = f"{lab} / 손절 ROE -{int(stop * 100)}%"
        txt.append(f"\n### {key}: 거래 {len(df)}, 거래당 {df.w.mean():.4f}, 승률 {(df.w > 0).mean():.3f}, "
                   f"진 거래 평균 {df.w[df.w <= 0].mean():.4f}, 이긴 거래 평균 {df.w[df.w > 0].mean():.4f}")
        OUT[key] = {}
        for by in (["btc", "side"], ["own", "side"], ["coin"], ["side"], ["ses"], ["vol"]):
            g = df.groupby(by + ["per"]).w.agg(["size", "mean", lambda v: (v > 0).mean()]).round(4)
            g.columns = ["거래", "거래당", "승률"]
            g = g.unstack("per")
            txt.append(f"-- {' x '.join(by)}\n" + g.to_string())
            OUT[key][" x ".join(by)] = json.loads(g.reset_index().to_json(orient="records", force_ascii=False))
        # fixes picked on the pick period: drop the (dim value x side) groups whose pick-period mean < 0 with >= 15 trades
        cand_all = np.ones(len(t), bool)
        sdn = np.where(s > 0, "롱", "숏")
        fixes = {}
        for dim in ("btc", "own", "vol", "ses", "coin"):
            col = df[dim] if dim != "coin" else df.coin
            gg = df[df.per == "고르기"].groupby([col, df.side]).w.agg(["mean", "size"])
            bad = [ix for ix, r in gg.iterrows() if r["mean"] < 0 and r["size"] >= 15]
            vals = (np.asarray(DIMS[dim])[G[dim]] if dim != "coin" else np.asarray(COINS)[c])
            drop = np.zeros(len(t), bool)
            for v_, sd_ in bad:
                drop |= (vals == v_) & (sdn == sd_)
            fixes[dim] = (drop, len(bad), len(gg))
        for dim, (drop, nb_, ng_) in fixes.items():
            res = {}
            for tag, dmask in (("손실 칸 빼기", drop), ("무작위 칸 빼기", None)):
                if dmask is None:
                    vals = (np.asarray(DIMS[dim])[G[dim]] if dim != "coin" else np.asarray(COINS)[c])
                    groups = sorted(set(zip(vals, sdn)))
                    pick = [groups[i] for i in rng.choice(len(groups), size=min(nb_, len(groups)), replace=False)]
                    dmask = np.zeros(len(t), bool)
                    for v_, sd_ in pick:
                        dmask |= (vals == v_) & (sdn == sd_)
                kk = ~dmask
                t2, c2, s2, w2, _ = sim(t[kk], c[kk], s[kk], p[kk], stop)
                res[tag] = {"고르기": FC.read(t2, w2, 202201, 202412), "확인": FC.read(t2, w2, 202501, 202609)}
            base = {"고르기": FC.read(tt, w, 202201, 202412), "확인": FC.read(tt, w, 202501, 202609)}
            OUT[key][f"고치기: {dim}"] = {"뺀 칸": f"{nb_}/{ng_}", "그대로": base, **res}
            b_, f_, r_ = base, res["손실 칸 빼기"], res["무작위 칸 빼기"]
            txt.append(f"고치기 {dim} (뺀 칸 {nb_}/{ng_}): 그대로 ×{b_['고르기']['기하평균']} → ×{b_['확인']['기하평균']} | "
                       f"손실 칸 빼기 ×{f_['고르기']['기하평균']} → ×{f_['확인']['기하평균']} (월 {f_['확인']['달 진입']}) | "
                       f"무작위 빼기 ×{r_['고르기']['기하평균']} → ×{r_['확인']['기하평균']}")
json.dump(OUT, open(os.path.join(OUTD, "pmautopsy41.json"), "w"), ensure_ascii=False, indent=1, default=float)
open(os.path.join(OUTD, "pmautopsy41.txt"), "w").write("\n".join(txt))
print("\n".join(txt))
