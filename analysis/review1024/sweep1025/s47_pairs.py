"""Owners 10/25 night: "did you test the rule bot's strategies and the DeepSeek strategies combined?"
Part 1, two entries that confirm each other: strategy A's signal is taken only when strategy B (a different strategy,
any of the rule bot's 36 and DeepSeek's 44 on 15m / 30m / 1h / 4h) signalled the same coin and side within the last
1 h or 4 h. Every ordered pair (320 x 320 cells, both windows) is read on the three 2021-06 .. 2024-12 blocks (pick),
2025-01 .. 2026-09 (check) and the rule bot's 20 live days (10/05 15:00 .. 10/24 14:12 UTC). Control: B's signals
from 300 days earlier (the same strategies and density, no link to the moment).
Part 2, several strategies in one bot: cells (strategy x timeframe x side) added one at a time to a one-position bot,
each time the cell that most raises the pick period's monthly geometric mean; read on check and
October. Control: the same with coin-flip sides.
Fixed rules (BTC 40x / alts 30x, margin 40 %), owners' ladder L5, stop ROE -35 %, no hold limit, weekday entries,
DeepCoin 0.14 % (and 0.08 % with payback)."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, COINS, MIN, ms, DAY, GT0   # noqa: E402
T00 = time.time()
SMOKE = os.environ.get("S47_SMOKE") == "1"


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
D = FC.Data()
S = RD.signals(period=(ms("2021-06-01"), FWD_B))
S = S[FC.wk(S.t.to_numpy(np.int64)) & S.set.isin(["core", "ds"])].reset_index(drop=True)
if SMOKE:
    S = S[S.name.isin(["V39_ALL", "S2_ST_ROC", "S3_CMO_SANDWICH", "N05_PSAR_POC", "OBV_S", "N12_ICHI_AO"])].reset_index(drop=True)
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
PB = np.full(N, -1, np.int8)                               # 0..2 pick blocks, 3 check, 4 October live days
PB[(ym >= 202106) & (ym <= 202206)] = 0; PB[(ym >= 202207) & (ym <= 202309)] = 1; PB[(ym >= 202310) & (ym <= 202412)] = 2
PB[(ym >= 202501) & (ym <= 202609)] = 3; PB[(t >= FWD_A) & (t < FWD_B)] = 4
NPB = 5
log("signals", N, "walked")
names = S.name.astype(str).to_numpy(); tfs = S.tf.astype(str).to_numpy(); sets = S.set.astype(str).to_numpy()
cellname = pd.Series(names).str.cat(tfs, sep=" ").to_numpy()
cell, CELLS = pd.factorize(cellname)
NC = len(CELLS)
CSTRAT = np.array([c.split(" ")[0] for c in CELLS]); SIDX, _SN = pd.factorize(names); CSI = np.array([SIDX[cell == c][0] for c in range(NC)]); CSET = np.array([sets[cell == c][0] for c in range(NC)])
G = cell * 2 + (side > 0)                                  # cell x side
NG = NC * 2
KEY = coin * 2 + (side > 0)
SH = np.int64(2) ** 42
ENC = KEY.astype(np.int64) * SH + (t - ms("2019-01-01"))
WINS = (3600_000, 4 * 3600_000)
SHIFT = 300 * DAY
okk = ok & (PB >= 0)
gk = G[okk].astype(np.int64) * NPB + PB[okk]; wk_ = w[okk]
SUM = np.zeros((2, len(WINS), NC, NG, NPB), np.float32); CNT = np.zeros((2, len(WINS), NC, NG, NPB), np.float32)
CIX = [np.flatnonzero(cell == c) for c in range(NC)]
for b in range(NC):
    ib = CIX[b]
    for ci_, shift in ((0, 0), (1, SHIFT)):
        eb = np.sort(KEY[ib].astype(np.int64) * SH + (t[ib] + shift - ms("2019-01-01")))
        j = np.searchsorted(eb, ENC, side="right") - 1
        hit = j >= 0; jj = np.clip(j, 0, None)
        same = hit & ((eb[jj] // SH) == KEY)
        dt = np.where(same, ENC - eb[jj], np.int64(1) << 60)
        own = SIDX == CSI[b]                               # never confirm a strategy with itself
        for wi, W_ in enumerate(WINS):
            conf = (dt <= W_) & ~own
            cm = conf[okk]
            SUM[ci_, wi, b] = np.bincount(gk[cm], wk_[cm], NG * NPB).reshape(NG, NPB)
            CNT[ci_, wi, b] = np.bincount(gk[cm], minlength=NG * NPB).reshape(NG, NPB)
    if b % 40 == 0:
        log("pairs B", b, "/", NC)
BASE_S = np.bincount(gk, wk_, NG * NPB).reshape(NG, NPB); BASE_N = np.bincount(gk, minlength=NG * NPB).reshape(NG, NPB)
log("pairs done")
NMIN, NBMIN = 90, 20
with np.errstate(invalid="ignore", divide="ignore"):
    MB = SUM / CNT                                          # (ctrl, win, B, g, pb)
    PICKN = CNT[..., :3].sum(-1); PICKM = SUM[..., :3].sum(-1) / PICKN
    WORST = np.where(CNT[..., :3].min(-1) >= NBMIN, MB[..., :3].min(-1), np.nan)
    WORST = np.where(PICKN >= NMIN, WORST, np.nan)
CHKM = MB[..., 3]; CHKN = CNT[..., 3]; FWM = MB[..., 4]; FWN = CNT[..., 4]
gc = np.arange(NG) // 2; gs = np.where(np.arange(NG) % 2, "롱", "숏")
OUT = {"읽는 법": __doc__}
# ---------------------------------------------------------------- every pair: how many look good on pick, and how many of those hold
summ = {}
for ci_, cn in ((0, "실제"), (1, "대조: B는 300일 전 신호")):
    v = np.isfinite(WORST[ci_]) & (CHKN[ci_] >= 15)
    good_p = v & (WORST[ci_] > 0)
    hold = good_p & (CHKM[ci_] > 0)
    cross = (CSET[:, None] != CSET[gc][None, :])[None, :, :] & np.ones((len(WINS), 1, 1), bool)
    summ[cn] = {"읽을 수 있는 짝": int(v.sum()), "고르기 세 구간 모두 플러스": int(good_p.sum()), "그중 확인에도 플러스": int(hold.sum()),
                "비율": round(float(hold.sum() / max(good_p.sum(), 1)), 3),
                "규칙봇 x 딥시크 짝: 고르기 세 구간 플러스": int((good_p & cross).sum()), "그중 확인 플러스": int((hold & cross).sum()),
                "세 구간 플러스 짝의 확인 신호당 (평균)": round(float(np.nanmean(CHKM[ci_][good_p])), 4) if good_p.any() else None}
    log(cn, summ[cn])
OUT["모든 짝"] = summ


def pair_row(ci_, wi, b, g):
    return {"A (진입)": f"{CELLS[gc[g]]} {gs[g]}", "B (확인)": CELLS[b], "창": "1시간" if wi == 0 else "4시간",
            "고르기 신호당": round(float(PICKM[ci_, wi, b, g]), 4), "고르기 가장 나쁜 구간": None if not np.isfinite(WORST[ci_, wi, b, g]) else round(float(WORST[ci_, wi, b, g]), 4),
            "고르기 신호": int(PICKN[ci_, wi, b, g]), "확인 신호당": None if CHKN[ci_, wi, b, g] < 1 else round(float(CHKM[ci_, wi, b, g]), 4),
            "확인 신호": int(CHKN[ci_, wi, b, g]), "10월 신호당": None if FWN[ci_, wi, b, g] < 1 else round(float(FWM[ci_, wi, b, g]), 4),
            "10월 신호": int(FWN[ci_, wi, b, g]),
            "A 그대로 확인 신호당": round(float(BASE_S[g, 3] / BASE_N[g, 3]), 4) if BASE_N[g, 3] else None}


# top pairs by the worse of pick-worst-block and check (both must be readable), real and control
for ci_, cn in ((0, "실제"), (1, "대조")):
    sc = np.minimum(WORST[ci_], np.where(CHKN[ci_] >= 30, CHKM[ci_], np.nan))      # NaN when either is unreadable
    flat = np.argsort(np.where(np.isfinite(sc), -sc, np.inf), axis=None)[:40]
    rows = []
    for f in flat:
        wi, b, g = np.unravel_index(f, sc.shape)
        if not np.isfinite(sc[wi, b, g]):
            break
        rows.append(pair_row(ci_, wi, b, g))
    OUT[f"두 기간 모두 좋은 짝 상위 40 ({cn})"] = rows
    log(cn, "top pair", rows[0] if rows else None)
# the owners' examples
EX = []
for a in ("S2_ST_ROC 30m", "S3_CMO_SANDWICH 30m", "N05_PSAR_POC 30m", "OBV_S 30m", "N12_ICHI_AO 30m", "V39_ALL 1h"):
    for b_ in ("V39_ALL 1h", "V39_ALL 4h", "S2_ST_ROC 30m", "S3_CMO_SANDWICH 30m"):
        if a == b_ or a not in set(CELLS) or b_ not in set(CELLS) or a.split(" ")[0] == b_.split(" ")[0]:
            continue
        ca = list(CELLS).index(a); cb = list(CELLS).index(b_)
        for s_ in (1, 0):
            for wi in range(len(WINS)):
                EX.append(pair_row(0, wi, cb, ca * 2 + s_))
OUT["두 분 예시"] = EX
# ---------------------------------------------------------------- the bot: each cell x side with its best B (pick worst block > bar)


def conf_mask(b, wi, shift):
    ib = CIX[b]
    eb = np.sort(KEY[ib].astype(np.int64) * SH + (t[ib] + shift - ms("2019-01-01")))
    j = np.searchsorted(eb, ENC, side="right") - 1; jj = np.clip(j, 0, None)
    same = (j >= 0) & ((eb[jj] // SH) == KEY)
    return same & (ENC - eb[jj] <= WINS[wi]) & (SIDX != CSI[b])


def sim(m, prio, stop=0.35, cost=0.0014, sd=None):
    ix = np.flatnonzero(m & ok)
    if not len(ix):
        return None
    ix = ix[np.lexsort((-prio[ix], t[ix]))]
    tt, cc = t[ix], coin[ix]; ss = (side if sd is None else sd)[ix].astype(np.int64)
    cst = D.off[cc] + ((tt - GT0) // MIN); csend = D.off[cc + 1]
    ti, ww, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, ss, tt, csend, HB.LEVC[cc].astype(float), stop, 0, 0.0, 0.12, 0.10, 0.05, cost, HB.MARGIN)
    return tt[ti], ww


def read(r):
    if r is None:
        return None
    t2, ww = r; fw = (t2 >= FWD_A) & (t2 < FWD_B)
    rp = FC.read(t2, ww, 202106, 202412); rc = FC.read(t2, ww, 202501, 202609)
    return {"고르기 한 달 기하평균": rp["기하평균"], "고르기 x3+ 달": rp["x3+"], "확인 한 달 기하평균": rc["기하평균"], "확인 중간값": rc["중간값"],
            "확인 x3+ 달": rc["x3+"], "확인 -50% 달": rc["-50%"], "확인 달 진입": rc["달 진입"], "확인 최고 달": rc["최고"],
            "10월 20일 배수": round(float(np.prod(1 + ww[fw])), 3), "10월 20일 거래": int(fw.sum())}


BOTS = {}
for ci_, cn, shift in ((0, "실제", 0), (1, "대조", SHIFT)):
    best = {}
    for g in range(NG):
        sc = WORST[ci_, :, :, g]
        if not np.isfinite(sc).any():
            continue
        wi, b = np.unravel_index(np.nanargmax(sc), sc.shape)
        if sc[wi, b] > 0:
            best[g] = (wi, b, float(sc[wi, b]))
    keep = np.zeros(N, bool); prio = np.zeros(N)
    cache = {}
    for g, (wi, b, sc) in best.items():
        if (b, wi) not in cache:
            cache[(b, wi)] = conf_mask(b, wi, shift)
        m = cache[(b, wi)] & (G == g)
        keep |= m; prio[m] = np.maximum(prio[m], sc)
        if len(cache) > 60:
            cache.clear()
    for bar in (0.0, 0.005, 0.01, 0.015):
        for cost in (0.0014, 0.0008):
            r = read(sim(keep & (prio > bar), prio, 0.35, cost))
            if r:
                r["칸"] = int(sum(1 for v in best.values() if v[2] > bar))
                BOTS[f"짝 봇 {cn} / 가장 나쁜 구간 > {bar * 100:.1f}% / 비용 {cost * 100:.2f}%"] = r
                log("pair bot", cn, bar, cost, r["고르기 한 달 기하평균"], r["확인 한 달 기하평균"], r["10월 20일 배수"])
# survivors: pairs positive in all three pick blocks AND on check (>= 30 check signals). Chosen with the check period,
# so only the 20 live days of October are unseen here.
for ci_, cn, shift in ((0, "실제", 0), (1, "대조", SHIFT)):
    v = np.isfinite(WORST[ci_]) & (WORST[ci_] > 0) & (CHKN[ci_] >= 30) & (CHKM[ci_] > 0)
    keep = np.zeros(N, bool); prio = np.zeros(N); npair = 0
    for wi, b, g in zip(*np.nonzero(v)):
        m = conf_mask(b, wi, shift) & (G == g)
        keep |= m; prio[m] = np.maximum(prio[m], min(WORST[ci_, wi, b, g], CHKM[ci_, wi, b, g])); npair += 1
    for cost in (0.0014, 0.0008):
        r = read(sim(keep, prio, 0.35, cost))
        if r:
            r["짝"] = npair
            BOTS[f"두 기간 통과 짝 봇 {cn} (10월만 처음 보는 기간) / 비용 {cost * 100:.2f}%"] = r
            log("survivor bot", cn, cost, npair, r["고르기 한 달 기하평균"], r["확인 한 달 기하평균"], r["10월 20일 배수"], r["10월 20일 거래"])
OUT["짝 봇"] = BOTS
del SUM, CNT, MB
# ---------------------------------------------------------------- part 2: greedy portfolio of cells x sides in one one-position bot
PCK = (PB >= 0) & (PB <= 2)
rng = np.random.default_rng(47)
FLIP = np.where(rng.random(N) < 0.5, 1, -1).astype(np.int8)
GIX = [np.flatnonzero((G == g) & ok) for g in range(NG)]
PZ = np.zeros(N)


def block_geo(t2, ww):
    """the pick period's monthly geometric mean (2021-06 .. 2024-12): the most generous objective."""
    return FC.read(t2, ww, 202106, 202412)["기하평균"]


PORT = {}
for pn, sd in (("실제", None), ("대조: 동전 방향", FLIP)):
    cand = [g for g in range(NG) if len(GIX[g]) and PCK[GIX[g]].sum() >= 150]
    chosen, cur = [], np.zeros(N, bool); hist = []
    best_obj = -1.0
    for step in range(12):
        bestg, bobj = None, best_obj
        for g in cand:
            if g in chosen:
                continue
            m = cur.copy(); m[GIX[g]] = True
            r = sim(m & PCK, PZ, 0.35, 0.0014, sd)
            if r is None:
                continue
            o = block_geo(*r)
            if o > bobj + 0.002:
                bestg, bobj = g, o
        if bestg is None:
            break
        chosen.append(bestg); cur[GIX[bestg]] = True; best_obj = bobj
        rr = read(sim(cur, PZ, 0.35, 0.0014, sd)); rr8 = read(sim(cur, PZ, 0.35, 0.0008, sd))
        hist.append({"더한 칸": f"{CELLS[bestg // 2]} {'롱' if bestg % 2 else '숏'}", "고르기 한 달 (고를 때)": round(bobj, 3),
                     "0.14%": rr, "0.08%": rr8})
        log("portfolio", pn, step, hist[-1]["더한 칸"], round(bobj, 3), rr["확인 한 달 기하평균"], rr["10월 20일 배수"])
    PORT[pn] = hist
OUT["여러 매매법 한 봇 (하나씩 더하기)"] = PORT
json.dump(OUT, open(os.path.join(OUTD, "pairs47" + ("_smoke" if SMOKE else "") + ".json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
