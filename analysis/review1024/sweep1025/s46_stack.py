"""Owners 10/25 night: "put together the judges that suit each strategy and run that as the bot".
For every strategy x timeframe x side (121 strategies, 4 timeframes): stack up to four filters chosen greedily on
2021-06 .. 2024-12 (pick) from 104 trend judges (52 sources on 1h / 4h, enter only when the judge agrees) and the
market-state exclusions that matter (BTC 4h trend 5 steps, the coin's own 4h trend, volatility, session, coin).
The objective is the worst of three pick sub-blocks (2021-06 .. 2022-06, 2022-07 .. 2023-09, 2023-10 .. 2024-12), so a
filter only counts when it helps in all three. Then every cell whose stack is positive in all three blocks goes into
one one-position bot (owners' L5 ladder, stops ROE -25 / -35 / -50 %, no hold limit, weekday entries, DeepCoin 0.14 %
and 0.08 % with payback), read on 2025-01 .. 2026-09 (check, unseen) and on the rule bot's 20 live days (10/05 15:00 ..
10/24 14:12 UTC).
Controls: the same greedy with every judge's state taken 300 days earlier (same judges, same amount of agreement, no link
to the moment) and the market states shuffled inside each cell.
Also the plain vote: enter only when the top K judges (ranked on pick) all agree, or 3 of 4 agree."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, COINS, MIN, TF_MIN, ms, bars, KST, DAY, GT0   # noqa: E402
sys.path.insert(0, "/home/user/crypto-bot-research")
from paperbot.rmember import regimes                     # noqa: E402
T00 = time.time()
SMOKE = os.environ.get("S46_SMOKE") == "1"


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
D = FC.Data()
S = RD.signals(period=(ms("2021-06-01"), FWD_B))
S = S[FC.wk(S.t.to_numpy(np.int64))].reset_index(drop=True)
if SMOKE:
    S = S[S.name.isin(["V39_ALL", "S2_ST_ROC", "S3_CMO_SANDWICH", "F12_MSS_DISP"])].reset_index(drop=True)
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
PER = np.full(N, 3, np.int8)
PER[(ym >= 202106) & (ym <= 202412)] = 0; PER[(ym >= 202501) & (ym <= 202609)] = 1; PER[(t >= FWD_A) & (t < FWD_B)] = 2
BLK = np.full(N, -1, np.int8)
BLK[(ym >= 202106) & (ym <= 202206)] = 0; BLK[(ym >= 202207) & (ym <= 202309)] = 1; BLK[(ym >= 202310) & (ym <= 202412)] = 2
log("signals", N, "walked")
# ---------------------------------------------------------------- market states (closed bars only), as in s45
R5MAP = np.array([4, 3, 0, 1, 2], np.int8)
b4 = bars("BTCUSDT", "4h"); _, RB5 = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
CB = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000
j = np.searchsorted(CB, t, side="right") - 1
ST_ = {"BTC 장세5": R5MAP[np.where(j >= 0, RB5[np.clip(j, 0, None)], 4)], "코인 장세5": np.full(N, 2, np.int8), "변동성": np.full(N, 1, np.int8)}
for ci, cn in enumerate(COINS):
    m = coin == ci; tm = t[m]
    if not m.any():
        continue
    bc = bars(cn, "4h"); _, R5 = regimes(bc.high.to_numpy(), bc.low.to_numpy(), bc.close.to_numpy())
    cc = bc.ts.to_numpy(np.int64) + 4 * 3600 * 1000; jj = np.searchsorted(cc, tm, side="right") - 1
    ST_["코인 장세5"][m] = R5MAP[np.where(jj >= 0, R5[np.clip(jj, 0, None)], 4)]
    b15 = bars(cn, "15m"); c15 = b15.close.to_numpy(); T15 = b15.ts.to_numpy(np.int64) + 15 * MIN
    jj = np.clip(np.searchsorted(T15, tm, side="right") - 1, 0, None)
    rv = pd.Series(np.r_[np.nan, np.diff(np.log(c15))]).rolling(96).std()
    q1 = rv.rolling(8640, min_periods=2000).quantile(1 / 3).to_numpy(); q2 = rv.rolling(8640, min_periods=2000).quantile(2 / 3).to_numpy()
    rv = rv.to_numpy()
    ST_["변동성"][m] = np.where(rv[jj] < q1[jj], 0, np.where(rv[jj] > q2[jj], 2, 1))
hr = ((t + KST) // 3600_000) % 24
ST_["시간대"] = np.where((hr >= 9) & (hr < 16), 0, np.where((hr >= 16) & (hr < 22), 1, np.where((hr >= 22) | (hr < 2), 2, 3))).astype(np.int8)
ST_["코인"] = coin.astype(np.int8)
LAB = {"BTC 장세5": ["강한 하락", "약한 하락", "횡보", "약한 상승", "강한 상승"], "코인 장세5": ["강한 하락", "약한 하락", "횡보", "약한 상승", "강한 상승"],
       "변동성": ["낮음", "중간", "높음"], "시간대": ["아시아 09-16", "유럽 16-22", "미국 22-02", "새벽 02-09"],
       "코인": [c.replace("USDT", "") for c in COINS]}
EXC = [(dim, v) for dim, labs in LAB.items() for v in range(len(labs))]          # "not in this state" filters
log("states")
# ---------------------------------------------------------------- judges: raw state (+1 up / -1 down / 0) now and 300 days earlier
SRC = [k[2:] for k in RD._states("BTCUSDT", "4h").keys() if k.startswith("c_")]
JN = [f"{s} @{h}" for h in ("1h", "4h") for s in SRC]
NJ = len(JN)
JS = np.zeros((NJ, N), np.int8); JC = np.zeros((NJ, N), np.int8)
SHIFT = 300 * DAY
for hi, htf in enumerate(("1h", "4h")):
    for ci, cn in enumerate(COINS):
        m = np.flatnonzero(coin == ci)
        if not len(m):
            continue
        Zs = RD._states(cn, htf); cz = Zs["ts"] + TF_MIN[htf] * MIN; nb = Zs["nb"]
        for arr, tt in ((JS, t[m]), (JC, t[m] - SHIFT)):
            jz = np.searchsorted(cz, tt, side="right") - 1; okz = jz >= 0; jz = np.clip(jz, 0, None); okz &= nb[jz] >= 300
            for si, src in enumerate(SRC):
                arr[hi * len(SRC) + si, m] = np.where(okz, Zs[f"c_{src}"][jz], 0)
log("judges", NJ)
names = S.name.astype(str).to_numpy(); tfs = S.tf.astype(str).to_numpy()
cellname = pd.Series(names).str.cat(tfs, sep=" ").to_numpy()
cell, CELLS = pd.factorize(cellname)
NC = len(CELLS)
GRP = cell * 2 + (side > 0)
ORD = np.argsort(GRP, kind="stable"); BND = np.searchsorted(GRP[ORD], np.arange(NC * 2 + 1))


def blocks(M, wv, bv):
    """M (k, n) bool; returns count (k,), mean (k,), worst block mean (k,), worst block count (k,) over pick blocks."""
    Mf = M.astype(np.float32)
    cnt = Mf.sum(1); sm = Mf @ wv.astype(np.float32)
    bm = np.full((M.shape[0], 3), np.nan); bn = np.zeros((M.shape[0], 3))
    for b in range(3):
        sel = bv == b
        cb = Mf[:, sel].sum(1); sb = Mf[:, sel] @ wv[sel].astype(np.float32)
        bn[:, b] = cb
        with np.errstate(invalid="ignore", divide="ignore"):
            bm[:, b] = sb / cb
    with np.errstate(invalid="ignore", divide="ignore"):
        return cnt, sm / cnt, bm.min(1), bn.min(1)


NMIN, NBMIN, MAXF, MINIMP = 90, 20, 4, 0.0005


def stack(g, JX, shuffle_states, rs):
    """greedy stack for one cell x side; returns (kept mask over the group's ok signals, filters, pick mean, worst block)."""
    ix = ORD[BND[g]:BND[g + 1]]; ix = ix[ok[ix]]
    if len(ix) == 0:
        return None
    P = PER[ix] == 0
    if P.sum() < 150:
        return None
    sg = side[ix]
    AG = JX[:, ix] == sg                                          # (NJ, n) judge agrees with the signal side
    EX = []
    for dim, v in EXC:
        vals = ST_[dim][ix]
        if shuffle_states:
            vals = vals[rs.permutation(len(vals))]
        EX.append(vals != v)
    CAND = np.vstack([AG, np.array(EX)])
    cname = JN + [f"{dim} {LAB[dim][v]} 빼기" for dim, v in EXC]
    wv = w[ix][P]; bv = BLK[ix][P]
    cur = np.ones(len(ix), bool)
    c0, m0, wb0, _ = blocks(cur[None, P], wv, bv)
    best_obj = wb0[0]; chosen = []
    for _step in range(MAXF):
        M = CAND[:, P] & cur[P]
        cnt, mean, wb, bn = blocks(M, wv, bv)
        valid = (cnt >= NMIN) & (bn >= NBMIN) & np.isfinite(wb)
        if chosen:
            valid[[cname.index(c) for c in chosen]] = False
        if not valid.any():
            break
        k = int(np.nanargmax(np.where(valid, wb, -np.inf)))
        if wb[k] < best_obj + MINIMP:
            break
        best_obj = wb[k]; chosen.append(cname[k]); cur &= CAND[k]
    cP = cur & P
    return ix, cur, chosen, float(w[ix][cP].mean()), float(best_obj), int(cP.sum())


def run_all(JX, shuffle_states, tag):
    rs = np.random.default_rng(46)
    keep = np.zeros(N, bool); prio = np.zeros(N); cards = {}
    for g in range(NC * 2):
        r = stack(g, JX, shuffle_states, rs)
        if r is None:
            continue
        ix, cur, chosen, pm, wb, npk = r
        c, s_ = divmod(g, 2)
        sel = ix[cur]; ch = sel[PER[sel] == 1]; fw = sel[PER[sel] == 2]
        base_c = ix[PER[ix] == 1]
        cards[f"{CELLS[c]} {'롱' if s_ else '숏'}"] = {
            "겹친 필터": chosen, "고르기 신호당": round(pm, 4), "고르기 가장 나쁜 구간": round(wb, 4), "고르기 신호": npk,
            "확인 신호당": round(float(w[ch].mean()), 4) if len(ch) >= 15 else None, "확인 신호": int(len(ch)),
            "그대로 확인 신호당": round(float(w[base_c].mean()), 4) if len(base_c) else None,
            "10월 신호당": round(float(w[fw].mean()), 4) if len(fw) else None, "10월 신호": int(len(fw))}
        if wb > 0 and chosen:
            keep[sel] = True; prio[sel] = wb
        if g % 200 == 0:
            log(tag, "group", g, "/", NC * 2)
    return keep, prio, cards


def bot(m, prio, stop, cost=0.0014, bar=None):
    mm = m & ok
    if bar is not None:
        mm &= prio > bar
    ix = np.flatnonzero(mm)
    if not len(ix):
        return None
    ix = ix[np.lexsort((-prio[ix], t[ix]))]
    tt, cc, ss = t[ix], coin[ix], side[ix].astype(np.int64)
    cst = D.off[cc] + ((tt - GT0) // MIN); csend = D.off[cc + 1]
    ti, ww, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, ss, tt, csend, HB.LEVC[cc].astype(float), stop, 0, 0.0, 0.12, 0.10, 0.05, cost, HB.MARGIN)
    t2 = tt[ti]; fw = (t2 >= FWD_A) & (t2 < FWD_B)
    rp = FC.read(t2, ww, 202106, 202412); rc = FC.read(t2, ww, 202501, 202609)
    return {"고르기 한 달 기하평균": rp["기하평균"], "고르기 중간값": rp["중간값"], "고르기 x3+ 달": rp["x3+"], "고르기 -50% 달": rp["-50%"], "고르기 달 진입": rp["달 진입"],
            "확인 한 달 기하평균": rc["기하평균"], "확인 중간값": rc["중간값"], "확인 x3+ 달": rc["x3+"], "확인 -50% 달": rc["-50%"], "확인 달 진입": rc["달 진입"],
            "확인 최고 달": rc["최고"], "10월 20일 배수": round(float(np.prod(1 + ww[fw])), 3), "10월 20일 거래": int(fw.sum()),
            "10월 20일 승률": round(float((ww[fw] > 0).mean()), 3) if fw.any() else None}


OUT = {"읽는 법": __doc__}
BOTS = {}
for tag, JX, shuf in (("실제", JS, False), ("대조: 판단 300일 전 · 장세 섞음", JC, True)):
    keep, prio, cards = run_all(JX, shuf, tag)
    kc = [v for v in cards.values() if v["고르기 가장 나쁜 구간"] > 0 and v["겹친 필터"]]
    chk = [v["확인 신호당"] for v in kc if v["확인 신호당"] is not None]
    OUT[f"칸 {tag}"] = {"세 구간 모두 플러스인 칸": len(kc), "그중 확인 플러스": int(sum(x > 0 for x in chk)), "확인 읽힌 칸": len(chk),
                       "확인 신호당 (평균)": round(float(np.mean(chk)), 4) if chk else None,
                       "고른 신호 확인 신호당": round(float(w[keep & ok & (PER == 1)].mean()), 4) if (keep & ok & (PER == 1)).any() else None,
                       "고른 신호 10월 신호당": round(float(w[keep & ok & (PER == 2)].mean()), 4) if (keep & ok & (PER == 2)).any() else None}
    log(tag, OUT[f"칸 {tag}"])
    if tag == "실제":
        OUT["카드"] = cards
    for bar in (0.0, 0.003, 0.006, 0.01):
        for stop in (0.25, 0.35, 0.50):
            for cost in (0.0014, 0.0008):
                b = bot(keep, prio, stop, cost, bar)
                if b:
                    BOTS[f"{tag} / 가장 나쁜 구간 > {bar * 100:.1f}% / 손절 -{int(stop * 100)}% / 비용 {cost * 100:.2f}%"] = b
    log(tag, "bots")
    del keep, prio
# ---------------------------------------------------------------- the plain vote of the top judges (ranked on pick, all entries)
P0 = ok & (PER == 0)
diff = np.zeros(NJ)
for k in range(NJ):
    ag = JS[k] == side; ag_ = (JS[k] == -side) & (JS[k] != 0)
    diff[k] = w[P0 & ag].mean() - w[P0 & ag_].mean()
rank = np.argsort(-diff)
VOTE = {}
for KK in (4, 8, 12):
    for JX, jt in ((JS, "실제"), (JC, "대조 300일 전")):
        top = rank[:KK]
        nag = np.zeros(N, np.int16)
        for k in top:
            nag += (JX[k] == side)
        for need, nl in ((KK, "전부 같은 방향"), (int(np.ceil(KK * 0.75)), "75% 이상 같은 방향")):
            m = nag >= need
            r = {"판단": [JN[k] for k in top], "고르기 신호당": round(float(w[P0 & m].mean()), 4), "확인 신호당": round(float(w[ok & (PER == 1) & m].mean()), 4),
                 "10월 신호당": round(float(w[ok & (PER == 2) & m].mean()), 4) if (ok & (PER == 2) & m).any() else None,
                 "남는 신호 비율": round(float(m[ok].mean()), 3)}
            # bot: every cell x side whose voted signals are positive in all three pick blocks
            keepv = np.zeros(N, bool); prv = np.zeros(N)
            for g in range(NC * 2):
                ix = ORD[BND[g]:BND[g + 1]]; ix = ix[ok[ix] & m[ix]]
                P = PER[ix] == 0
                if P.sum() < NMIN:
                    continue
                bm = [w[ix][P & (BLK[ix] == b)] for b in range(3)]
                if min(len(x) for x in bm) < NBMIN:
                    continue
                wb = min(float(x.mean()) for x in bm)
                if wb > 0:
                    keepv[ix] = True; prv[ix] = wb
            r["세 구간 모두 플러스인 칸"] = int(len(np.unique(GRP[keepv])))
            for stop in (0.25, 0.35):
                b = bot(keepv, prv, stop)
                r[f"봇 손절 -{int(stop * 100)}%"] = b
            VOTE[f"상위 {KK}개 판단 {nl} / {jt}"] = r
            log("vote", KK, nl, jt, r["고르기 신호당"], r["확인 신호당"])
OUT["봇"] = BOTS
OUT["판단 투표"] = VOTE
json.dump(OUT, open(os.path.join(OUTD, "stack46" + ("_smoke" if SMOKE else "") + ".json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
