"""Owners 10/25 night: "combinations that show promise are fine; nothing always works in backtests; the current market
matters". Every strategy x timeframe (121 strategies: rule bot 36, DeepSeek 44, library 41; 15m / 30m / 1h / 4h) as a
one-position bot, both sides / long only / short only, with the owners' L10 ladder (12 -> 10, 22 -> 20, ...) and stop
ROE -25 / -35 %, fixed rules (BTC 40x / alts 30x, margin 40 %), weekday entries, no hold limit, DeepCoin 0.14 %.
Ranked by the current market: the rule bot's 20 live days (10/05 15:00 .. 10/24 14:12 UTC) and the last three months
(2026-07 .. 09); the longer past (2026-01 .. 09, 2025-01 .. 2026-09, 2021-06 .. 2024-12) is shown next to it.
Then small combinations: the top 3 / 5 / 8 cells by October among those not losing over 2026, in one bot.
Also how well "good in the last 20 days" carried into the next 20 days in the past (persistence), for the same ranking."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, MIN, ms, DAY, GT0, KST     # noqa: E402
sys.path.insert(0, "/home/user/crypto-bot-research")
T00 = time.time()


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
D = FC.Data()
S = RD.signals(period=(ms("2021-06-01"), FWD_B))
S = S[FC.wk(S.t.to_numpy(np.int64))].reset_index(drop=True)
t = S.t.to_numpy(np.int64); coin = S.coin.to_numpy(np.int64); side = S.side.to_numpy(np.int8)
names = S.name.astype(str).to_numpy(); tfs = S.tf.astype(str).to_numpy(); sets = S.set.astype(str).to_numpy()
cellname = pd.Series(names).str.cat(tfs, sep=" ").to_numpy()
cell, CELLS = pd.factorize(cellname)
NC = len(CELLS)
ORDc = np.argsort(cell, kind="stable"); BNDc = np.searchsorted(cell[ORDc], np.arange(NC + 1))
KO = {k: v["name_ko"] for k, v in json.load(open("/home/user/crypto-bot-research/research/newlive/classify.json")).items()}
SETN = {"core": "규칙봇", "ds": "딥시크", "lib": "라이브러리", "friend": "친구분"}
log("signals", len(S), "cells", NC)


def bot(ix, stop, cost=0.0014):
    if not len(ix):
        return None
    ix = ix[np.lexsort((coin[ix], t[ix]))]
    tt, cc, ss = t[ix], coin[ix], side[ix].astype(np.int64)
    cst = D.off[cc] + ((tt - GT0) // MIN); csend = D.off[cc + 1]
    ti, w, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, ss, tt, csend, HB.LEVC[cc].astype(float), stop, 0, 0.0, 0.12, 0.10, 0.10, cost, HB.MARGIN)
    return tt[ti], w


def read(r):
    if r is None:
        return None
    t2, w = r
    fw = (t2 >= FWD_A) & (t2 < FWD_B)
    out = {"10월 20일": round(float(np.prod(1 + w[fw])), 3), "10월 거래": int(fw.sum()),
           "10월 승률": round(float((w[fw] > 0).mean()), 2) if fw.any() else None}
    for lab, a, b in (("최근 3달 (7~9월)", 202607, 202609), ("2026 1~9월", 202601, 202609), ("2025~26", 202501, 202609), ("2021~24", 202106, 202412)):
        rr = FC.read(t2, w, a, b)
        out[lab] = rr["기하평균"]
        if lab == "최근 3달 (7~9월)":
            e, _, _ = FC.month_ends(t2, w, a, b)
            out["7·8·9월"] = [round(float(x), 2) for x in e]
        if lab == "2025~26":
            out["2025~26 ×2 이상 달"] = rr["x2+"]; out["2025~26 -50% 달"] = rr["-50%"]; out["2025~26 달 진입"] = rr["달 진입"]
    return out


ROWS = []
for c in range(NC):
    ix_all = ORDc[BNDc[c]:BNDc[c + 1]]
    for sd_name, sel in (("양방향", None), ("롱만", 1), ("숏만", -1)):
        ix = ix_all if sel is None else ix_all[side[ix_all] == sel]
        if len(ix) < 50:
            continue
        for stop in (0.25, 0.35):
            r = read(bot(ix, stop))
            if r is None:
                continue
            nm, tf = CELLS[c].split(" ")
            ROWS.append({"매매법": nm, "이름": KO.get(nm, nm), "세트": SETN.get(sets[ix_all[0]], sets[ix_all[0]]), "봉": tf, "방향": sd_name,
                         "손절": f"-{int(stop * 100)}%", **r})
    if c % 50 == 0:
        log("cell", c, "/", NC)
R = pd.DataFrame(ROWS)
R.to_csv(os.path.join(OUTD, "now55_cells.csv"), index=False)
log("cells done", len(R))
# ---------------------------------------------------------------- combinations of the October leaders (not losing over 2026)
COMB = {}
for stop in (0.25, 0.35):
    sub = R[(R["손절"] == f"-{int(stop * 100)}%") & (R["10월 거래"] >= 5) & (R["2026 1~9월"] >= 1.0)].sort_values("10월 20일", ascending=False)
    sub = sub.drop_duplicates(["매매법", "봉"])
    for n in (3, 5, 8):
        top = sub.head(n)
        ix = []
        for _, rw in top.iterrows():
            cc_ = list(CELLS).index(f"{rw['매매법']} {rw['봉']}")
            ii = ORDc[BNDc[cc_]:BNDc[cc_ + 1]]
            if rw["방향"] == "롱만":
                ii = ii[side[ii] > 0]
            elif rw["방향"] == "숏만":
                ii = ii[side[ii] < 0]
            ix.append(ii)
        ix = np.unique(np.concatenate(ix))
        for cost in (0.0014, 0.0008):
            r = read(bot(ix, stop, cost))
            COMB[f"10월 상위 {n}개 (2026 손실 아님) / 손절 -{int(stop * 100)}% / 비용 {cost * 100:.2f}%"] = {
                "구성": [f"{rw['이름']} {rw['봉']} {rw['방향']}" for _, rw in top.iterrows()], **r}
            log("comb", n, stop, cost, r["10월 20일"], r["최근 3달 (7~9월)"], r["2026 1~9월"], r["2025~26"])
# ---------------------------------------------------------------- persistence: the top cells of a past 20-day window, next 20 days
# (one-position bots per cell, L10, stop -35 %, both sides): per 20-day window from 2022-01 on, rank by the window,
# read the next window for the top 10 and for all.
PER = {}
W20 = 20 * DAY
starts = np.arange(ms("2022-01-03"), ms("2026-09-01"), 10 * DAY)
cell_tw = {}
for c in range(NC):
    ix = ORDc[BNDc[c]:BNDc[c + 1]]
    r = bot(ix, 0.35)
    if r is not None:
        cell_tw[c] = r
log("persistence bots", len(cell_tw))
nxt_top, nxt_all, nxt_top2 = [], [], []
for s0 in starts:
    cur, nxt = {}, {}
    for c, (t2, w) in cell_tw.items():
        a = (t2 >= s0) & (t2 < s0 + W20); b = (t2 >= s0 + W20) & (t2 < s0 + 2 * W20)
        if a.sum() >= 5:
            cur[c] = float(np.prod(1 + w[a])); nxt[c] = float(np.prod(1 + w[b])) if b.any() else 1.0
    if len(cur) < 20:
        continue
    order = sorted(cur, key=lambda c: -cur[c])
    nxt_top.append(np.median([nxt[c] for c in order[:10]])); nxt_all.append(np.median(list(nxt.values())))
    hot = [c for c in order if cur[c] >= 2.0]
    if hot:
        nxt_top2.append(np.median([nxt[c] for c in hot]))
PER = {"구간 수": len(nxt_top), "지난 20일 상위 10칸의 다음 20일 (중간값의 중간값)": round(float(np.median(nxt_top)), 3),
       "전체 칸의 다음 20일": round(float(np.median(nxt_all)), 3),
       "지난 20일 ×2 이상 칸의 다음 20일": round(float(np.median(nxt_top2)), 3) if nxt_top2 else None,
       "상위 10칸이 다음 20일 ×1 이상인 구간 비율": round(float(np.mean(np.array(nxt_top) >= 1)), 3)}
log("persistence", PER)
TOP = R.sort_values("10월 20일", ascending=False)
json.dump({"읽는 법": __doc__, "10월 상위 40": json.loads(TOP.head(40).to_json(orient="records", force_ascii=False)),
           "최근 3달 상위 40": json.loads(R[R["10월 거래"] >= 1].sort_values("최근 3달 (7~9월)", ascending=False).head(40).to_json(orient="records", force_ascii=False)),
           "조합": COMB, "지금 좋은 것이 이어지나": PER},
          open(os.path.join(OUTD, "now55.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
