"""Owners 10/25 night: "why does each loss happen? by up / down / range market, by coin, by timeframe, by each strategy's
type and entry". Loss autopsy of every signal of the 121 coded strategies (15m / 30m / 1h / 4h, both sides, 6 coins,
weekday entries, 2021-06 .. 2026-10), each walked alone with the owners' ladder L5 (12->10, then +5) and stops ROE
-25 / -35 / -50 %, no hold limit, DeepCoin 0.14 % round trip, fixed rules (BTC 40x / alts 30x, margin 40 %).

Part 1, where the losses come from (2022-01 .. 2026-09, stop -35 %): mean wallet result per signal, win rate, how the
trade ended (stop / ladder lock) and how fast the stops come, split by BTC 4h regime (up / down / range) x side, the coin's
own 4h regime, coin, timeframe, strategy type (trend / pullback / reversal / breakout / range / timing), KST session,
volatility (the coin's 1-day realized volatility against its 90 days: low / mid / high), year; the best and worst
strategies x timeframe x side.
Part 2, keep only what made money: cells (strategy x timeframe x side, + BTC regime, + coin) whose mean on 2022-01 ..
2024-12 is above a bar with enough signals; then the same cells on 2025-01 .. 2026-09 (unseen) per signal and as a
one-position bot by KST month (no hold limit, L5); control: as many cells drawn at random."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, COINS, MIN, bars, ms, KST, DAY, GT0   # noqa: E402
sys.path.insert(0, "/home/user/crypto-bot-research")
from paperbot.rmember import regimes                     # noqa: E402
T00 = time.time()


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


D = FC.Data()
SMOKE = os.environ.get("S40_SMOKE") == "1"
S = RD.signals(period=(ms("2021-06-01"), ms("2026-10-24 14:12")), **({"coins": ["BTCUSDT"], "tfs": ("4h",)} if SMOKE else {}))
S = S[FC.wk(S.t.to_numpy(np.int64))].reset_index(drop=True)
for c in ("tf", "set", "name", "role", "symbol"):
    S[c] = S[c].astype("category")
log("signals", len(S))
t = S.t.to_numpy(np.int64); coin = S.coin.to_numpy(np.int64); side = S.side.to_numpy(np.int8)
start = D.off[coin] + S.e.to_numpy(np.int64); send = D.off[coin + 1]
good = (start < send - 1) & np.isfinite(D.o[np.minimum(start, len(D.o) - 1)])
STOPS = (0.25, 0.35, 0.50)
sk = np.ones(3, np.int8); sv = np.array(STOPS); tk = np.zeros(3, np.int8); tv = np.zeros(3)
lg = np.full(3, 0.12); ll = np.full(3, 0.10); ls = np.full(3, 0.05)
W, K, Y = HB.walk_all(D.o, D.h, D.l, D.c, np.where(good, start, 0), send, side, HB.LEVC[coin], np.full(len(S), 0.01),
                      sk, sv, tk, tv, lg, ll, ls, 0.0014, HB.MARGIN, 10 ** 12)
W = W.astype(float); W[~good] = np.nan
log("walked")
# ---------------------------------------------------------------- attributes
b4 = bars("BTCUSDT", "4h"); RB, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
CB = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000
j = np.searchsorted(CB, t, side="right") - 1
S["btc장세"] = np.where(j >= 0, RB[np.clip(j, 0, None)], 2).astype(np.int8)
own = np.full(len(S), 2, np.int8); vol = np.full(len(S), 1, np.int8)
for ci, cn in enumerate(COINS):
    m = coin == ci
    bc = bars(cn, "4h"); R_, _ = regimes(bc.high.to_numpy(), bc.low.to_numpy(), bc.close.to_numpy())
    cc = bc.ts.to_numpy(np.int64) + 4 * 3600 * 1000
    jj = np.searchsorted(cc, t[m], side="right") - 1
    own[m] = np.where(jj >= 0, R_[np.clip(jj, 0, None)], 2)
    b15 = bars(cn, "15m"); c15 = b15.close.to_numpy(); T15 = b15.ts.to_numpy(np.int64) + 15 * MIN
    rv = pd.Series(np.r_[np.nan, np.diff(np.log(c15))]).rolling(96).std()
    lo_ = rv.rolling(8640, min_periods=2000).quantile(1 / 3).to_numpy(); hi_ = rv.rolling(8640, min_periods=2000).quantile(2 / 3).to_numpy()
    rv = rv.to_numpy()
    jj = np.clip(np.searchsorted(T15, t[m], side="right") - 1, 0, None)
    vol[m] = np.where(rv[jj] < lo_[jj], 0, np.where(rv[jj] > hi_[jj], 2, 1))
S["코인장세"] = own; S["변동성"] = vol
hr = ((t + KST) // 3600_000) % 24
S["시간대"] = pd.Categorical(np.where((hr >= 9) & (hr < 16), "아시아 09-16", np.where((hr >= 16) & (hr < 22), "유럽 16-22",
                      np.where((hr >= 22) | (hr < 2), "미국 22-02", "새벽 02-09"))))
ym = FC.ym_of(t); S["ym"] = ym; S["해"] = ym // 100
S["w25"], S["w35"], S["w50"] = W[:, 0], W[:, 1], W[:, 2]
S["why35"] = Y[:, 1]; S["k35"] = K[:, 1]
# ---------------------------------------------------------------- extra dimensions (not asked; needed for the goal)
from numba import njit                                    # noqa: E402
from free_core import TF_MIN                              # noqa: E402
tfs = S.tf.astype(str).to_numpy()
big = np.full(len(S), np.nan); pos1 = np.full(len(S), np.nan); htf = np.zeros(len(S), np.int8); fund = np.full(len(S), np.nan)
for ci, cn in enumerate(COINS):
    mc = coin == ci
    for tf_ in ("15m", "30m", "1h", "4h"):
        m = mc & (tfs == tf_)
        if not m.any():
            continue
        b = bars(cn, tf_); h_, l_, c_ = b.high.to_numpy(), b.low.to_numpy(), b.close.to_numpy()
        pc = np.r_[c_[0], c_[:-1]]; tr = np.maximum(h_ - l_, np.maximum(np.abs(h_ - pc), np.abs(l_ - pc)))
        atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy(); atrp = np.r_[np.nan, atr[:-1]]
        close = b.ts.to_numpy(np.int64) + TF_MIN[tf_] * MIN
        jj = np.clip(np.searchsorted(close, t[m]), 0, len(close) - 1); ok = close[jj] == t[m]
        big[m] = np.where(ok, (h_ - l_)[jj] / np.maximum(atrp[jj], 1e-12), np.nan)
    b15 = bars(cn, "15m"); c15 = b15.close.to_numpy()
    hi = pd.Series(b15.high.to_numpy()).rolling(96).max().to_numpy(); lo = pd.Series(b15.low.to_numpy()).rolling(96).min().to_numpy()
    T15 = b15.ts.to_numpy(np.int64) + 15 * MIN; jj = np.clip(np.searchsorted(T15, t[mc], side="right") - 1, 0, None)
    pos1[mc] = (c15[jj] - lo[jj]) / np.maximum(hi[jj] - lo[jj], 1e-12)
    Zs = RD._states(cn, "4h"); cz = Zs["ts"] + TF_MIN["4h"] * MIN
    jz = np.searchsorted(cz, t[mc], side="right") - 1; okz = jz >= 0; jz = np.clip(jz, 0, None)
    htf[mc] = np.where(okz & (Zs["nb"][jz] >= 300), Zs["j_V39"][jz], 0)
    g = FC.grid(cn); fr = np.nan_to_num(g["fund"]); fi = np.flatnonzero(fr != 0); ft = GT0 + fi.astype(np.int64) * MIN
    jf = np.searchsorted(ft, t[mc], side="right") - 1
    fund[mc] = np.where(jf >= 0, fr[fi][np.clip(jf, 0, None)], np.nan)
S["신호봉"] = pd.Categorical(np.where(big < 1, "1 ATR 미만", np.where(big < 2, "1~2 ATR", np.where(big < 3, "2~3 ATR", np.where(big >= 3, "3 ATR 이상", "?")))))
chase = np.where(side > 0, pos1, 1 - pos1)
S["하루 범위 위치"] = pd.Categorical(np.where(chase > 0.8, "진입 방향 끝 (추격)", np.where(chase < 0.2, "반대 끝 (되돌림)", np.where(np.isfinite(chase), "가운데", "?"))))
S["4시간 V3.9"] = pd.Categorical(np.where(htf == 0, "없음", np.where(htf == side, "같은 방향", "반대 방향")))
S["펀딩"] = pd.Categorical(np.where(~np.isfinite(fund) | (fund == 0), "?", np.where(fund * side > 0, "내는 쪽", "받는 쪽")))
o_c = np.lexsort((t, side, coin)); same = np.zeros(len(S), np.int64)
key_cs = coin[o_c] * 2 + (side[o_c] > 0)
for kv in np.unique(key_cs):
    ix = o_c[key_cs == kv]; tt = t[ix]
    same[ix] = np.searchsorted(tt, tt, side="right") - np.searchsorted(tt, tt - 60 * MIN, side="right") - 1
S["1시간 안 같은 방향 신호"] = pd.Categorical(np.where(same == 0, "0개", np.where(same <= 2, "1~2개", np.where(same <= 5, "3~5개", "6개 이상"))))
S["요일"] = pd.Categorical(np.asarray(["월", "화", "수", "목", "금", "토", "일"])[((((t + KST) // DAY) + 3) % 7)])


@njit(cache=True)
def after_stop(o, h, l, start, k, side, lev, why, cost, lg, look):
    """for stop-outs: did the price reach the ladder's first step (net ROE +12 %) within ``look`` minutes after the
    stop, measured from the entry price? (a stop by a wick / noise, the direction was right)"""
    n = len(start); out = np.zeros(n, np.int8)
    for i in range(n):
        if why[i] != 0:
            continue
        e0 = start[i]; p0 = o[e0]
        if not (p0 > 0):
            continue
        g1 = lg / lev[i] + cost; es = e0 + k[i]
        for j in range(es, min(es + look, len(h))):
            fav = h[j] / p0 - 1 if side[i] > 0 else 1 - l[j] / p0
            if fav >= g1:
                out[i] = 1; break
    return out


@njit(cache=True)
def walk_close_stop(o, h, l, c, start, send, side, lev, offc, sv, lg, ll, ls, cost, margin, every):
    """L5 ladder, ROE stop checked on candle closes only (every = 1: 1m closes, 15: 15m closes), the liquidation
    distance still intrabar (the exchange does that), no hold limit."""
    n = len(start); W = np.zeros(n); WHY = np.zeros(n, np.int8)
    for i in range(n):
        e0 = start[i]; e1 = send[i]; L = lev[i]; sd = side[i]; p0 = o[e0]
        if not (p0 > 0) or e0 >= e1 - 1:
            W[i] = np.nan; continue
        dliq = 1.0 / L - 0.005; d = min(sv / L - cost, dliq)
        g1 = lg / L + cost; l1 = ll / L + cost; stp = ls / L
        lock = -1e9; best = 0.0; mv = 0.0; why = 3; liqd = False
        for j in range(e0, e1):
            if sd > 0:
                oj = o[j] / p0 - 1; lj = l[j] / p0 - 1; hj = h[j] / p0 - 1; cj = c[j] / p0 - 1
            else:
                oj = 1 - o[j] / p0; lj = 1 - h[j] / p0; hj = 1 - l[j] / p0; cj = 1 - c[j] / p0
            if lock > -1e8 and oj <= lock:
                mv = oj; why = 1; break
            if lj <= -dliq:
                liqd = True; why = 0; break
            if lock > -1e8 and lj <= lock:
                mv = lock; why = 1; break
            if (j - offc[i] + 1) % every == 0 and cj <= -d:
                mv = cj; why = 0; break
            if hj > best:
                best = hj
                if best >= g1:
                    nl = l1 + np.floor((best - g1) / stp + 1e-9) * stp
                    if nl > lock:
                        lock = nl
            if j == e1 - 1:
                mv = cj
        if liqd:
            W[i] = -margin
        else:
            W[i] = max(margin * L * (mv - cost), -margin)
        WHY[i] = why
    return W, WHY


st0 = np.where(good, start, 0)
S["손절 뒤 4시간 안 익절자리 도달"] = after_stop(D.o, D.h, D.l, st0, K[:, 1].astype(np.int64), side, HB.LEVC[coin].astype(float), Y[:, 1],
                                       0.0014, 0.12, 240)
offc = D.off[coin].astype(np.int64)
for every, nm_ in ((1, "1분봉 종가 손절"), (15, "15분봉 종가 손절")):
    wc, yc = walk_close_stop(D.o, D.h, D.l, D.c, st0, send, side, HB.LEVC[coin].astype(float), offc, 0.35, 0.12, 0.10, 0.05,
                             0.0014, HB.MARGIN, every)
    wc[~good] = np.nan; S[f"w35 {nm_}"] = wc
log("extra dims")
REGN = {0: "상승", 1: "하락", 2: "횡보"}; SIDEN = {1: "롱", -1: "숏"}; VOLN = {0: "낮음", 1: "중간", 2: "높음"}
A_ = (ym >= 202201) & (ym <= 202609)
X = S.loc[A_ & good].copy()
log("attributes", len(X))


def tab(df, by, w="w35"):
    d = df[(by if isinstance(by, list) else [by]) + [w, "why35", "k35"]].assign(_win=(df[w] > 0).astype(float), _stop=(df.why35 == 0).astype(float))
    g = d.groupby(by, observed=True)
    r = pd.DataFrame({"신호": g[w].size(), "거래당": g[w].mean(), "승률": g["_win"].mean(), "손절로 끝": g["_stop"].mean(),
                      "손절까지 중간(분)": d[d.why35 == 0].groupby(by, observed=True).k35.median()})
    return r.round(4)


OUT = {}
txt = []


def show(title, r):
    txt.append(f"\n## {title}\n" + r.to_string())
    OUT[title] = json.loads(r.reset_index().to_json(orient="records", force_ascii=False))


X = X.assign(btc=pd.Categorical(X["btc장세"].map(REGN)), 코인=pd.Categorical(X["코인장세"].map(REGN)), 방향=pd.Categorical(X.side.map(SIDEN)), 변동=pd.Categorical(X["변동성"].map(VOLN)))
show("전체", tab(X.assign(all=pd.Categorical(np.full(len(X), "전체"))), "all"))
show("BTC 4시간 장세 x 방향", tab(X, ["btc", "방향"]))
show("코인 자기 4시간 장세 x 방향", tab(X, ["코인", "방향"]))
show("코인", tab(X, "symbol"))
show("타임프레임", tab(X, "tf"))
show("매매법 유형", tab(X, "role"))
show("매매법 유형 x BTC 장세 x 방향", tab(X, ["role", "btc", "방향"]))
show("시간대", tab(X, "시간대"))
show("변동성", tab(X, "변동"))
show("해", tab(X, "해"))
st = tab(X, ["name", "tf", "방향"]); st = st[st["신호"] >= 200]
show("매매법 x 봉 x 방향: 가장 좋은 25", st.sort_values("거래당", ascending=False).head(25))
show("매매법 x 봉 x 방향: 가장 나쁜 25", st.sort_values("거래당").head(25))
show("손절 크기별 전체", pd.DataFrame({f"손절 {int(s * 100)}%": [X[f"w{int(s * 100)}"].mean(), (X[f"w{int(s * 100)}"] > 0).mean()]
                                    for s in STOPS}, index=["거래당", "승률"]).round(4))
for dim in ("신호봉", "하루 범위 위치", "4시간 V3.9", "펀딩", "1시간 안 같은 방향 신호", "요일"):
    show(f"{dim} x 방향", tab(X, [dim, "방향"]))
ws = X[X.why35 == 0]
show("손절된 거래 중 4시간 안에 익절 자리까지 다시 간 비율 (유형별)",
     ws.groupby("role", observed=True)["손절 뒤 4시간 안 익절자리 도달"].agg(["size", "mean"]).round(4))
show("손절 방식 비교: 꼬리(지금) / 1분봉 종가 / 15분봉 종가 (손절 ROE -35%, L5)",
     pd.DataFrame({k: [X[c_].mean(), (X[c_] > 0).mean()] for k, c_ in (("꼬리 닿으면 (지금)", "w35"), ("1분봉 종가", "w35 1분봉 종가 손절"),
                                                                         ("15분봉 종가", "w35 15분봉 종가 손절"))}, index=["거래당", "승률"]).round(4))
show("손절 방식 비교 x 유형", X.groupby("role", observed=True)[["w35", "w35 1분봉 종가 손절", "w35 15분봉 종가 손절"]].mean().round(4))
show("손절 방식 비교 x 봉", X.groupby("tf", observed=True)[["w35", "w35 1분봉 종가 손절", "w35 15분봉 종가 손절"]].mean().round(4))
show("손절 방식 비교 x 코인", X.groupby("symbol", observed=True)[["w35", "w35 1분봉 종가 손절", "w35 15분봉 종가 손절"]].mean().round(4))
log("part 1 done")
# ---------------------------------------------------------------- part 2: keep only the cells that made money (pick 2022-24)
P_ = (ym >= 202201) & (ym <= 202412); C_ = (ym >= 202501) & (ym <= 202609)
CELLS = {"매매법·봉·방향": ["name", "tf", "side"], "매매법·봉·방향·BTC장세": ["name", "tf", "side", "btc장세"],
         "매매법·봉·방향·BTC장세·코인": ["name", "tf", "side", "btc장세", "coin"],
         "매매법·봉·방향·코인장세": ["name", "tf", "side", "코인장세"]}
rng = np.random.default_rng(40)
res2 = {}
KID = {cn_: S.groupby(keys, observed=True, sort=False).ngroup().to_numpy() for cn_, keys in CELLS.items()}
for wcol in ("w35", "w50"):
    for cn_, keys in CELLS.items():
        kid = KID[cn_]
        dfp = pd.DataFrame({"kid": kid[P_ & good], "w": S[wcol].to_numpy()[P_ & good]})
        gp = dfp.groupby("kid").w.agg(["mean", "size"])
        for bar_, nmin in ((0.0, 30), (0.005, 30), (0.01, 50), (0.02, 50)):
            sel = gp.index[(gp["mean"] > bar_) & (gp["size"] >= nmin)].to_numpy()
            if not len(sel):
                continue
            pool = gp.index[gp["size"] >= nmin].to_numpy()
            rnd = rng.choice(pool, size=min(len(sel), len(pool)), replace=False)
            for tag, cells in (("고른 칸", sel), ("무작위 칸", rnd)):
                m_ = np.isin(kid, cells) & good
                prio = pd.Series(gp["mean"]).reindex(kid[m_]).to_numpy()
                wc = S[wcol].to_numpy()
                r = {"칸 수": int(len(cells)),
                     "고르기 신호당": round(float(np.nanmean(wc[m_ & P_])), 4), "확인 신호당": round(float(np.nanmean(wc[m_ & C_])), 4) if (m_ & C_).any() else None,
                     "확인 신호 수": int((m_ & C_).sum())}
                sv_ = float(wcol[1:]) / 100
                tt_ = t[m_]; o_ = np.lexsort((-np.nan_to_num(prio), tt_))
                tt_, c_, s_ = tt_[o_], coin[m_][o_], side[m_][o_]
                cst = D.off[c_] + ((tt_ - GT0) // MIN); csend = D.off[c_ + 1]
                ti, w_, _k = FC.seq_sim(D.o, D.h, D.l, D.c, cst, s_.astype(np.int64), tt_, csend, HB.LEVC[c_].astype(float),
                                        sv_, 0, 0.0, 0.12, 0.10, 0.05, 0.0014, HB.MARGIN)
                r["한 포지션 고르기"] = FC.read(tt_[ti], w_, 202201, 202412); r["한 포지션 확인"] = FC.read(tt_[ti], w_, 202501, 202609)
                r["10월"] = FC.read(tt_[ti], w_, 202610, 202610)
                res2[f"{wcol} / {cn_} / 고르기 평균 > {bar_} (신호 {nmin}개 이상) / {tag}"] = r
        log(wcol, cn_, "done")
OUT["2부: 돈 번 칸만"] = res2
json.dump(OUT, open(os.path.join(OUTD, "autopsy40_smoke.json" if SMOKE else "autopsy40.json"), "w"), ensure_ascii=False, indent=1, default=float)
txt.append("\n## 2부: 돈 번 칸만 (2022-24에서 고르고 2025-01 .. 2026-09에서 확인)")
for k, r in res2.items():
    a, b = r["한 포지션 고르기"], r["한 포지션 확인"]
    txt.append(f"{k} | 칸 {r['칸 수']} | 신호당 고르기 {r['고르기 신호당']} → 확인 {r['확인 신호당']} (확인 신호 {r['확인 신호 수']}) | "
               f"한 포지션 고르기 ×{a['기하평균']}/×{a['중간값']} 월 {a['달 진입']} → 확인 ×{b['기하평균']}/×{b['중간값']} 월 {b['달 진입']} -50% {b['-50%']} | 10월 ×{r['10월']['중간값']}")
open(os.path.join(OUTD, "autopsy40_smoke.txt" if SMOKE else "autopsy40.txt"), "w").write("\n".join(txt))
print("\n".join(txt))
log("done")
