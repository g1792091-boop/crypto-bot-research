"""Owners 10/25 night: for every strategy (121: rule bot 36, DeepSeek 44, library 41) x timeframe: alone or not, as a
trend judge or as an entry, which coins, which market states (not only up / down / range: BTC and the coin's own 4h
trend in 5 steps, the coin's daily trend, volatility level and whether it expands, position in the 1-day / 7-day range,
24 h momentum, funding, session, and a combined state), and which judges to pair it with.
Every claim is made on 2021-06 .. 2024-12 (pick) and read again on 2025-01 .. 2026-09 (check); the final
"each strategy only in its own market states" bot is compared with the same procedure on shuffled states (control).
Fixed rules (BTC 40x / alts 30x, margin 40 %), owners' ladder L5, stop ROE -35 % (bot also -25 / -50 %), no hold limit,
weekday entries, DeepCoin 0.14 %."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, COINS, MIN, TF_MIN, ms, bars, KST, DAY, GT0   # noqa: E402
sys.path.insert(0, "/home/user/crypto-bot-research")
from paperbot.rmember import regimes                     # noqa: E402
T00 = time.time()


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


D = FC.Data()
S = RD.signals(period=(ms("2021-06-01"), ms("2026-09-30 15:00")))
S = S[FC.wk(S.t.to_numpy(np.int64))].reset_index(drop=True)
t = S.t.to_numpy(np.int64); coin = S.coin.to_numpy(np.int64); side = S.side.to_numpy(np.int8)
start = D.off[coin] + S.e.to_numpy(np.int64); send = D.off[coin + 1]
good = (start < send - 1) & np.isfinite(D.o[np.minimum(start, len(D.o) - 1)])
STOPS = (0.25, 0.35, 0.50)
W, K, Y = HB.walk_all(D.o, D.h, D.l, D.c, np.where(good, start, 0), send, side, HB.LEVC[coin], np.full(len(S), 0.01),
                      np.ones(3, np.int8), np.array(STOPS), np.zeros(3, np.int8), np.zeros(3), np.full(3, 0.12),
                      np.full(3, 0.10), np.full(3, 0.05), 0.0014, HB.MARGIN, 10 ** 12)
W = W.astype(np.float32); W[~good] = np.nan
del K, Y
log("signals", len(S), "walked")
ym = FC.ym_of(t)
PER = np.where((ym >= 202106) & (ym <= 202412), 0, np.where((ym >= 202501) & (ym <= 202609), 1, 2)).astype(np.int8)
# ---------------------------------------------------------------- market states at the signal time (closed bars only)
A = {}
R5MAP = np.array([4, 3, 0, 1, 2], np.int8)                  # rmember.regimes reg5: 0 strong up, 1 weak up, 2 strong down, 3 weak down, 4 range -> 0 strong down .. 4 strong up
b4 = bars("BTCUSDT", "4h"); _, RB5 = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
CB = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000
j = np.searchsorted(CB, t, side="right") - 1
A["BTC 장세5"] = R5MAP[np.where(j >= 0, RB5[np.clip(j, 0, None)], 4)]
for k in ("코인 장세5", "코인 하루봉 추세", "변동성", "변동성 변화", "하루 범위 위치", "7일 범위 위치", "24시간 모멘텀", "펀딩"):
    A[k] = np.full(len(S), 1, np.int8)
for ci, cn in enumerate(COINS):
    m = coin == ci; tm = t[m]
    bc = bars(cn, "4h"); _, R5 = regimes(bc.high.to_numpy(), bc.low.to_numpy(), bc.close.to_numpy())
    cc = bc.ts.to_numpy(np.int64) + 4 * 3600 * 1000; jj = np.searchsorted(cc, tm, side="right") - 1
    A["코인 장세5"][m] = R5MAP[np.where(jj >= 0, R5[np.clip(jj, 0, None)], 4)]
    bd = bars(cn, "1d"); cd = bd.close.to_numpy(); e50 = pd.Series(cd).ewm(span=50, adjust=False).mean().to_numpy()
    cdt = bd.ts.to_numpy(np.int64) + DAY; jj = np.searchsorted(cdt, tm, side="right") - 1; jc = np.clip(jj, 0, None)
    A["코인 하루봉 추세"][m] = np.where(jj < 50, 1, np.where(cd[jc] > e50[jc] * 1.02, 2, np.where(cd[jc] < e50[jc] * 0.98, 0, 1)))
    b15 = bars(cn, "15m"); c15 = b15.close.to_numpy(); h15 = b15.high.to_numpy(); l15 = b15.low.to_numpy()
    T15 = b15.ts.to_numpy(np.int64) + 15 * MIN; jj = np.clip(np.searchsorted(T15, tm, side="right") - 1, 0, None)
    rv = pd.Series(np.r_[np.nan, np.diff(np.log(c15))]).rolling(96).std()
    q1 = rv.rolling(8640, min_periods=2000).quantile(1 / 3).to_numpy(); q2 = rv.rolling(8640, min_periods=2000).quantile(2 / 3).to_numpy()
    rv = rv.to_numpy(); rvp = np.r_[np.full(96, np.nan), rv[:-96]]
    A["변동성"][m] = np.where(rv[jj] < q1[jj], 0, np.where(rv[jj] > q2[jj], 2, 1))
    ratio = rv[jj] / np.maximum(rvp[jj], 1e-12)
    A["변동성 변화"][m] = np.where(ratio < 0.8, 0, np.where(ratio > 1.25, 2, 1))
    for nwin, key in ((96, "하루 범위 위치"), (672, "7일 범위 위치")):
        hi = pd.Series(h15).rolling(nwin).max().to_numpy(); lo = pd.Series(l15).rolling(nwin).min().to_numpy()
        pos = (c15[jj] - lo[jj]) / np.maximum(hi[jj] - lo[jj], 1e-12)
        A[key][m] = np.where(pos < 0.25, 0, np.where(pos > 0.75, 2, 1))
    r96 = np.log(c15) - np.log(np.r_[np.full(96, np.nan), c15[:-96]])
    qa = pd.Series(r96).rolling(8640, min_periods=2000).quantile(0.2).to_numpy(); qb = pd.Series(r96).rolling(8640, min_periods=2000).quantile(0.8).to_numpy()
    A["24시간 모멘텀"][m] = np.where(r96[jj] < qa[jj], 0, np.where(r96[jj] > qb[jj], 2, 1))
    g = FC.grid(cn); fr = np.nan_to_num(g["fund"]); fi = np.flatnonzero(fr != 0); ft = GT0 + fi.astype(np.int64) * MIN
    fs = fr[fi]; fq = pd.Series(fs).rolling(270, min_periods=90).quantile(0.9).to_numpy()
    jf = np.searchsorted(ft, tm, side="right") - 1; jfc = np.clip(jf, 0, None)
    A["펀딩"][m] = np.where(jf < 0, 1, np.where(fs[jfc] < 0, 0, np.where(fs[jfc] > fq[jfc], 2, 1)))
hr = ((t + KST) // 3600_000) % 24
A["시간대"] = np.where((hr >= 9) & (hr < 16), 0, np.where((hr >= 16) & (hr < 22), 1, np.where((hr >= 22) | (hr < 2), 2, 3))).astype(np.int8)
A["코인"] = coin.astype(np.int8)
TR3 = np.select([A["BTC 장세5"] <= 1, A["BTC 장세5"] == 2], [0, 1], 2)
A["복합 장세"] = (TR3 * 9 + A["변동성"] * 3 + A["하루 범위 위치"]).astype(np.int8)   # 3 trend x 3 vol x 3 pos
LAB = {"BTC 장세5": ["강한 하락", "약한 하락", "횡보", "약한 상승", "강한 상승"], "코인 장세5": ["강한 하락", "약한 하락", "횡보", "약한 상승", "강한 상승"],
       "코인 하루봉 추세": ["하루봉 EMA50 아래", "EMA50 근처", "EMA50 위"], "변동성": ["낮음", "중간", "높음"],
       "변동성 변화": ["줄어드는 중", "그대로", "커지는 중"], "하루 범위 위치": ["저점 근처", "가운데", "고점 근처"],
       "7일 범위 위치": ["저점 근처", "가운데", "고점 근처"], "24시간 모멘텀": ["급락 뒤", "보통", "급등 뒤"],
       "펀딩": ["마이너스", "보통", "과열(상위 10%)"], "시간대": ["아시아 09-16", "유럽 16-22", "미국 22-02", "새벽 02-09"],
       "코인": [c.replace("USDT", "") for c in COINS],
       "복합 장세": [f"{a}·변동{b}·{c}" for a in ("하락쪽", "횡보", "상승쪽") for b in ("낮음", "중간", "높음") for c in ("저점", "가운데", "고점")]}
log("states")
# check: regimes() REG5 order (0 = strong down?) -> derived from paperbot.rmember; print the mean 24 h move by REG5 value
for v in range(5):
    mm = (A["BTC 장세5"] == v) & (coin == 0)
    log("BTC 장세5", v, "signals", int(mm.sum()))
names = S.name.astype(str).to_numpy(); tfs = S.tf.astype(str).to_numpy(); sets = S.set.astype(str).to_numpy(); roles = S.role.astype(str).to_numpy()
cellname = pd.Series(names).str.cat(tfs, sep=" ").to_numpy()
cell, CELLS = pd.factorize(cellname)
NC = len(CELLS)
w = W[:, 1].astype(float); ok = good & np.isfinite(w)
sd01 = (side > 0).astype(np.int64)                         # 0 short, 1 long
log("cells", NC)
GRP = cell * 2 + sd01
ORD = np.argsort(GRP, kind="stable"); BND = np.searchsorted(GRP[ORD], np.arange(NC * 2 + 1))
CIX = np.split(np.argsort(cell, kind="stable"), np.searchsorted(np.sort(cell), np.arange(1, NC)))


def gix(g):
    return ORD[BND[g]:BND[g + 1]]


def agg(key, nk):
    """sums / counts per (key, period) for ok signals; returns mean and n arrays shape (nk, 2)."""
    out_s = np.zeros((nk, 2)); out_n = np.zeros((nk, 2))
    for p in (0, 1):
        mm = ok & (PER == p)
        out_s[:, p] = np.bincount(key[mm], w[mm], nk); out_n[:, p] = np.bincount(key[mm], minlength=nk)
    with np.errstate(invalid="ignore", divide="ignore"):
        return out_s / out_n, out_n


# ---------------------------------------------------------------- (A) cards: cell x side, and cell x side x each state value
base_m, base_n = agg(cell * 2 + sd01, NC * 2)
cards = {}
NMIN_P, NMIN_C = 40, 15
for dim, labs in LAB.items():
    nv = len(labs); key = (cell * 2 + sd01) * nv + A[dim].astype(np.int64)
    mmean, mn = agg(key, NC * 2 * nv)
    mmean = mmean.reshape(NC, 2, nv, 2); mn = mn.reshape(NC, 2, nv, 2)
    for c in range(NC):
        for s_ in (0, 1):
            for v in range(nv):
                if mn[c, s_, v, 0] >= NMIN_P and mmean[c, s_, v, 0] > 0:
                    cards.setdefault(CELLS[c], {}).setdefault("맞는 장 (고르기 기간 플러스)", []).append({
                        "기준": dim, "값": labs[v], "방향": "롱" if s_ else "숏", "고르기 신호당": round(float(mmean[c, s_, v, 0]), 4),
                        "고르기 신호": int(mn[c, s_, v, 0]), "확인 신호당": None if mn[c, s_, v, 1] < NMIN_C else round(float(mmean[c, s_, v, 1]), 4),
                        "확인 신호": int(mn[c, s_, v, 1])})
    log("dim", dim)
for c in range(NC):
    nm, tf_ = CELLS[c].split(" ")
    cd = cards.setdefault(CELLS[c], {})
    cd["매매법"] = nm; cd["봉"] = tf_; cd["세트"] = sets[cell == c][0]; cd["유형"] = roles[cell == c][0]
    for s_, sn in ((1, "롱"), (0, "숏")):
        cd[f"단독 {sn}"] = {"고르기 신호당": None if base_n[c * 2 + s_, 0] < 1 else round(float(base_m[c * 2 + s_, 0]), 4), "고르기 신호": int(base_n[c * 2 + s_, 0]),
                          "확인 신호당": None if base_n[c * 2 + s_, 1] < 1 else round(float(base_m[c * 2 + s_, 1]), 4), "확인 신호": int(base_n[c * 2 + s_, 1])}
    fits = cd.get("맞는 장 (고르기 기간 플러스)", [])
    conf = [f for f in fits if f["확인 신호당"] is not None]
    cd["맞는 장 개수"] = len(fits); cd["확인 기간에도 플러스"] = sum(1 for f in conf if f["확인 신호당"] > 0); cd["확인 가능한 것"] = len(conf)
# how often does "fits on pick" stay positive on check? (all strategies) vs the base rate of positive cells on check
allfits = [f for cdd in cards.values() for f in cdd.get("맞는 장 (고르기 기간 플러스)", []) if f["확인 신호당"] is not None]
rate_fit = float(np.mean([f["확인 신호당"] > 0 for f in allfits])) if allfits else float("nan")
log("fits", len(allfits), "kept positive on check", rate_fit)
# base rate: any (cell, side, dim, value) bin on check positive regardless of pick
# ---------------------------------------------------------------- (B) judges: 52 sources' condition state on 1h / 4h agreeing with the signal side
J = {}
JA = {}
SRC = [k[2:] for k in RD._states("BTCUSDT", "4h").keys() if k.startswith("c_")]
for htf in ("1h", "4h"):
    for src in SRC:
        st = np.zeros(len(S), np.int8)
        for ci, cn in enumerate(COINS):
            m = coin == ci
            Zs = RD._states(cn, htf); cz = Zs["ts"] + TF_MIN[htf] * MIN
            jz = np.searchsorted(cz, t[m], side="right") - 1; okz = jz >= 0; jz = np.clip(jz, 0, None)
            st[m] = np.where(okz & (Zs["nb"][jz] >= 300), Zs[f"c_{src}"][jz], 0)
        agree = st == side; against = (st == -side) & (st != 0)
        r = {}
        for p, pn in ((0, "고르기"), (1, "확인")):
            mm = ok & (PER == p)
            r[pn] = {"같은 방향 신호당": round(float(w[mm & agree].mean()), 4), "반대 방향 신호당": round(float(w[mm & against].mean()), 4),
                     "같은 방향 비율": round(float(agree[mm].mean()), 3)}
            r[pn]["차이"] = round(r[pn]["같은 방향 신호당"] - r[pn]["반대 방향 신호당"], 4)
        J[f"{src} @{htf}"] = r
        JA[f"{src} @{htf}"] = (st == side).astype(np.int8) - ((st == -side) & (st != 0)).astype(np.int8)
log("judges")
JR = sorted(J.items(), key=lambda kv: -kv[1]["고르기"]["차이"])
# per entry cell: best judge chosen on pick (agree mean, >= 40 signals), read on check; control: a random judge
rng = np.random.default_rng(45)
JK = list(J.keys())
pairs = {}
for c in range(NC):
    ix = CIX[c]; ix = ix[ok[ix]]
    pc = PER[ix]; wc_all = w[ix]
    if (pc == 0).sum() < 200:
        continue
    best = None
    for jk in JK:
        a = JA[jk][ix] == 1
        wp = wc_all[a & (pc == 0)]
        if len(wp) < 40:
            continue
        mp_ = float(wp.mean())
        if best is None or mp_ > best[1]:
            wc = wc_all[a & (pc == 1)]
            best = (jk, mp_, float(wc.mean()) if len(wc) >= 15 else None, len(wp), len(wc))
    if best:
        jr = JK[rng.integers(len(JK))]; a = JA[jr][ix] == 1
        wc_r = wc_all[a & (pc == 1)]
        pairs[CELLS[c]] = {"가장 좋은 판단 (고르기)": best[0], "고르기 신호당": round(best[1], 4), "확인 신호당": None if best[2] is None else round(best[2], 4),
                           "고르기 신호": best[3], "확인 신호": best[4], "그대로 확인 신호당": round(float(wc_all[pc == 1].mean()), 4) if (pc == 1).any() else None,
                           "무작위 판단 확인 신호당": round(float(wc_r.mean()), 4) if len(wc_r) else None}
    if c % 100 == 0:
        log("pairs", c, "/", NC)
log("pairs done")
# ---------------------------------------------------------------- (D) the bot: each cell x side only in its pick-period market states
def build_mask(dims, shuffle=False, bar=0.0, nmin=NMIN_P, keep_frac=0.3):
    """per cell x side: the single state dimension (of dims) whose positive values (pick mean > bar, n >= nmin) give the
    best pick mean while keeping >= keep_frac of the pick signals; allowed = signals in those values. shuffle: the states
    permuted within each cell x side (the control)."""
    allow = np.zeros(len(S), bool); chosen = {}
    rs = np.random.default_rng(7)
    for g in range(NC * 2):
        ix = gix(g); ix = ix[ok[ix]]
        pg = PER[ix]; wg = w[ix]; mp = pg == 0
        npick = int(mp.sum())
        if npick < 100:
            continue
        best = None
        for dim in dims:
            v = A[dim][ix].astype(np.int64)
            if shuffle:
                v = v[rs.permutation(len(v))]
            nv = len(LAB[dim])
            sm = np.bincount(v[mp], wg[mp], nv); nn = np.bincount(v[mp], minlength=nv)
            with np.errstate(invalid="ignore", divide="ignore"):
                mean = sm / nn
            good_v = np.flatnonzero((nn >= nmin) & (mean > bar))
            if not len(good_v):
                continue
            kn = nn[good_v].sum()
            if kn < keep_frac * npick:
                continue
            km = sm[good_v].sum() / kn
            if best is None or km > best[1]:
                best = (dim, km, good_v, v)
        if best and best[1] > 0:
            dim, km, gv, v = best
            allow[ix[np.isin(v, gv)]] = True
            c, s_ = divmod(g, 2)
            chosen[f"{CELLS[c]} {'롱' if s_ else '숏'}"] = {"기준": dim, "값": [LAB[dim][i] for i in gv], "고르기 신호당": round(float(km), 4)}
    return allow, chosen


def bot(m, stop):
    ix = np.flatnonzero(m & ok); ix = ix[np.lexsort((coin[ix], t[ix]))]
    tt, cc, ss = t[ix], coin[ix], side[ix].astype(np.int64)
    cst = D.off[cc] + ((tt - GT0) // MIN); csend = D.off[cc + 1]
    ti, ww, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, ss, tt, csend, HB.LEVC[cc].astype(float), stop, 0, 0.0, 0.12, 0.10, 0.05, 0.0014, HB.MARGIN)
    t2 = tt[ti]
    return {"고르기": FC.read(t2, ww, 202106, 202412), "확인": FC.read(t2, ww, 202501, 202609)}


DIMS_ALL = list(LAB.keys())
BOT = {}
for lab, dims in (("3개 장세만 (BTC 장세5)", ["BTC 장세5"]), ("자세한 장세 전부", DIMS_ALL), ("코인 제외 자세한 장세", [d for d in DIMS_ALL if d != "코인"])):
    for shuffle in (False, True):
        allow, chosen = build_mask(dims, shuffle=shuffle)
        mpick = allow & (PER == 0) & ok; mchk = allow & (PER == 1) & ok
        r = {"고른 칸": len(chosen), "고르기 신호당": round(float(w[mpick].mean()), 4) if mpick.any() else None,
             "확인 신호당": round(float(w[mchk].mean()), 4) if mchk.any() else None, "확인 신호": int(mchk.sum())}
        for stop in (0.25, 0.35, 0.50):
            b = bot(allow, stop); r[f"봇 손절 -{int(stop * 100)}%"] = {"고르기 기하평균": b["고르기"]["기하평균"], "확인 기하평균": b["확인"]["기하평균"],
                                                                 "확인 -50% 달": b["확인"]["-50%"], "확인 달 진입": b["확인"]["달 진입"]}
        if not shuffle:
            r["고른 칸 목록 (앞 60)"] = dict(list(sorted(chosen.items(), key=lambda kv: -kv[1]["고르기 신호당"]))[:60])
        BOT[f"{lab} / {'대조: 장세 섞음' if shuffle else '실제'}"] = r
        log("bot", lab, shuffle, r["고르기 신호당"], r["확인 신호당"])
OUT = {"읽는 법": __doc__, "맞는 장이 확인 기간에도 플러스로 남은 비율": rate_fit, "맞는 장 수": len(allfits),
       "판단용 순위 (고르기 기간 차이 순)": dict(JR), "매매법별 가장 좋은 판단 짝": pairs, "봇": BOT, "카드": cards}
json.dump(OUT, open(os.path.join(OUTD, "roles45.json"), "w"), ensure_ascii=False, default=float)
log("done")
