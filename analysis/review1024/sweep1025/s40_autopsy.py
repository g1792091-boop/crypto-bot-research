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
S["시간대"] = np.where((hr >= 9) & (hr < 16), "아시아 09-16", np.where((hr >= 16) & (hr < 22), "유럽 16-22",
                      np.where((hr >= 22) | (hr < 2), "미국 22-02", "새벽 02-09")))
ym = FC.ym_of(t); S["ym"] = ym; S["해"] = ym // 100
S["w25"], S["w35"], S["w50"] = W[:, 0], W[:, 1], W[:, 2]
S["why35"] = Y[:, 1]; S["k35"] = K[:, 1]
REGN = {0: "상승", 1: "하락", 2: "횡보"}; SIDEN = {1: "롱", -1: "숏"}; VOLN = {0: "낮음", 1: "중간", 2: "높음"}
A_ = (ym >= 202201) & (ym <= 202609)
X = S[A_ & good]
log("attributes", len(X))


def tab(df, by, w="w35"):
    g = df.groupby(by, observed=True)
    r = pd.DataFrame({"신호": g[w].size(), "거래당": g[w].mean(), "승률": g[w].apply(lambda v: (v > 0).mean()),
                      "손절로 끝": g["why35"].apply(lambda v: (v == 0).mean()),
                      "손절까지 중간(분)": g.apply(lambda d: float(np.median(d.k35[d.why35 == 0])) if (d.why35 == 0).any() else np.nan)})
    return r.round(4)


OUT = {}
txt = []


def show(title, r):
    txt.append(f"\n## {title}\n" + r.to_string())
    OUT[title] = json.loads(r.reset_index().to_json(orient="records", force_ascii=False))


X = X.assign(btc=X["btc장세"].map(REGN), 코인=X["코인장세"].map(REGN), 방향=X.side.map(SIDEN), 변동=X["변동성"].map(VOLN))
show("전체", tab(X.assign(all="전체"), "all"))
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
