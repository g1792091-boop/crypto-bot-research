"""Owners 10/25 night: the rule bot's 20-day live demo ranking (top 20 of the 36 core strategies x timeframe) as a
reference. Questions: (1) were today's live winners also good over 5 years? (2) V3.9 as an entry alone, as the trend
judge for other entries, or together with CMO sandwich / the other live leaders? (3) does "good in the last 20 days AND
good in the years before" pick strategies that stay good in the next 20 days (tested over 2022-2026)? (4) the DeepSeek
44 the same way. Fixed rules (BTC 40x / alts 30x, margin 40 %, one position), owners' ladder L5, stops ROE -25 / -35 /
-50 / -75 %, no hold limit, DeepCoin 0.14 %. Periods: 2021-06 .. 2024-12 (past), 2025-01 .. 2026-09 (recent), the live
window 2026-10-05 15:00 .. 10-24 14:12 UTC (= the rule bot's 20 days)."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, RD, COINS, MIN, TF_MIN, ms, KST, DAY, GT0   # noqa: E402
T00 = time.time()


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


LIVE = [("V39_ALL", "1h", "V3.9", 82.3, "25승 1패"), ("S3_CMO_SANDWICH", "30m", "CMO·샌드위치 캔들", 56.1, "18승 4패"),
        ("N05_PSAR_POC", "30m", "PSAR·POC 캔들", 42.5, "20승 6패"), ("OBV_S", "30m", "OBV 추세형", 39.2, "27승 6패"),
        ("N12_ICHI_AO", "30m", "일목·AO", 25.0, "30승 10패"), ("S3_CMO_SANDWICH", "1h", "CMO·샌드위치 캔들", 23.6, "13승 2패"),
        ("S2_ST_ROC", "30m", "슈퍼트렌드·ROC", 21.6, "66승 26패"), ("N13_3OUTSIDE", "30m", "쓰리 아웃사이드", 20.2, "27승 10패"),
        ("V39_ALL", "30m", "V3.9", 18.6, "37승 13패"), ("OBV_S", "4h", "OBV 추세형", 15.6, "4승 0패"),
        ("S6_EMA_DMI_ADX", "4h", "EMA·DMI·ADX", 14.2, "6승 0패"), ("S5_DONCHIAN_MFI", "15m", "돈치안·MFI", 14.1, "8승 4패"),
        ("N20_EMA9_CHOP", "4h", "EMA9·초피", 13.5, "2승 0패"), ("N06_MACD_ORB", "15m", "MACD·시가범위", 13.1, "23승 12패"),
        ("N24_DMI", "4h", "DMI", 12.5, "8승 1패"), ("N03_ADX_GC", "30m", "ADX·골든크로스", 12.1, "5승 1패"),
        ("N04_ST_KLINGER", "4h", "슈퍼트렌드·클링거", 10.9, "10승 2패"), ("N25_DST_CCI", "4h", "더블 슈퍼트렌드", 10.7, "4승 0패"),
        ("N22_VORTEX_PSAR", "4h", "볼텍스·PSAR", 10.3, "10승 2패"), ("N06_MACD_ORB", "1h", "MACD·시가범위", 8.3, "14승 6패")]
FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
D = FC.Data()
S = RD.signals(period=(ms("2021-06-01"), FWD_B))
for c in ("tf", "set", "name", "role", "symbol"):
    S[c] = S[c].astype("category")
t = S.t.to_numpy(np.int64); coin = S.coin.to_numpy(np.int64); side = S.side.to_numpy(np.int8)
WK = FC.wk(t)
start = D.off[coin] + S.e.to_numpy(np.int64); send = D.off[coin + 1]
good = (start < send - 1) & np.isfinite(D.o[np.minimum(start, len(D.o) - 1)])
STOPS = (0.25, 0.35, 0.50, 0.75)
W, K, Y = HB.walk_all(D.o, D.h, D.l, D.c, np.where(good, start, 0), send, side, HB.LEVC[coin], np.full(len(S), 0.01),
                      np.ones(4, np.int8), np.array(STOPS), np.zeros(4, np.int8), np.zeros(4), np.full(4, 0.12),
                      np.full(4, 0.10), np.full(4, 0.05), 0.0014, HB.MARGIN, 10 ** 12)
W = W.astype(float); W[~good] = np.nan
log("signals", len(S), "walked")
ym = FC.ym_of(t)
PER = {"과거 2021-06~2024-12": (ym >= 202106) & (ym <= 202412), "최근 2025-01~2026-09": (ym >= 202501) & (ym <= 202609),
       "실시간 20일 구간 10/06~10/24": (t >= FWD_A) & (t < FWD_B)}
# V3.9 state on the last closed 1h / 4h bar of the signal's coin
V39 = {tf_: np.zeros(len(S), np.int8) for tf_ in ("1h", "4h")}
for ci, cn in enumerate(COINS):
    mc = coin == ci
    for tf_ in ("1h", "4h"):
        Zs = RD._states(cn, tf_); cz = Zs["ts"] + TF_MIN[tf_] * MIN
        jz = np.searchsorted(cz, t[mc], side="right") - 1; ok = jz >= 0; jz = np.clip(jz, 0, None)
        V39[tf_][mc] = np.where(ok & (Zs["nb"][jz] >= 300), Zs["j_V39"][jz], 0)
names = S.name.astype(str).to_numpy(); tfs = S.tf.astype(str).to_numpy(); sets = S.set.astype(str).to_numpy()
log("states")
OUT, txt = {}, []


def per_signal(m, j=1):
    r = {}
    for pn, pm in PER.items():
        mm = m & pm & good
        r[pn] = {"신호": int(mm.sum()), "신호당": round(float(np.nanmean(W[mm, j])), 4) if mm.any() else None,
                 "승률": round(float((W[mm, j] > 0).mean()), 3) if mm.any() else None}
    return r


def bot(m, stop=0.35, weekday=True):
    """one-position bot over the candidates m (time order, ties by coin), L5, no hold limit."""
    mm = m & good & (WK if weekday else True)
    ix = np.flatnonzero(mm); ix = ix[np.lexsort((coin[ix], t[ix]))]
    tt, cc, ss = t[ix], coin[ix], side[ix].astype(np.int64)
    cst = D.off[cc] + ((tt - GT0) // MIN); csend = D.off[cc + 1]
    ti, w, _k = FC.seq_sim(D.o, D.h, D.l, D.c, cst, ss, tt, csend, HB.LEVC[cc].astype(float), stop, 0, 0.0, 0.12, 0.10, 0.05,
                           0.0014, HB.MARGIN)
    t2 = tt[ti]; fw = (t2 >= FWD_A) & (t2 < FWD_B)
    return {"과거 한 달 기하평균": FC.read(t2, w, 202106, 202412)["기하평균"], "최근 한 달 기하평균": FC.read(t2, w, 202501, 202609)["기하평균"],
            "과거 −50% 달": FC.read(t2, w, 202106, 202412)["-50%"], "최근 −50% 달": FC.read(t2, w, 202501, 202609)["-50%"],
            "실시간 20일 배수": round(float(np.prod(1 + w[fw])), 3), "실시간 20일 거래": int(fw.sum()),
            "실시간 20일 승률": round(float((w[fw] > 0).mean()), 3) if fw.any() else None}


# ---------------------------------------------------------------- (1) the live top 20 over 5 years
rows = []
for nm, tf_, ko, ret, wl in LIVE:
    m = (names == nm) & (tfs == tf_)
    ps = per_signal(m, 1); b = bot(m, 0.35)
    rows.append({"순위표": f"{ko} {tf_}", "실시간 수익": ret, "실시간 승패": wl,
                 **{f"{k} 신호당": v["신호당"] for k, v in ps.items()}, **{f"{k} 신호": v["신호"] for k, v in ps.items()},
                 **{f"봇 {k}": v for k, v in b.items()}})
R1 = pd.DataFrame(rows)
OUT["1 실시간 상위 20의 5년"] = json.loads(R1.to_json(orient="records", force_ascii=False))
txt.append("## 1. 실시간 상위 20개의 5년 (손절 -35%, L5, 신호 하나씩 / 한 포지션 봇 평일)\n" + R1.to_string())
log("part 1")
# ---------------------------------------------------------------- (2) V3.9 roles
R2 = {}
for tf_ in ("15m", "30m", "1h", "4h"):
    m = (names == "V39_ALL") & (tfs == tf_)
    for stop in (0.25, 0.35, 0.50):
        R2[f"V3.9 {tf_} 단독 / 손절 -{int(stop * 100)}%"] = {"신호당": per_signal(m, STOPS.index(stop)), "봇": bot(m, stop)}
LEAD = [("S3_CMO_SANDWICH", "30m"), ("S3_CMO_SANDWICH", "1h"), ("N05_PSAR_POC", "30m"), ("OBV_S", "30m"), ("N12_ICHI_AO", "30m"),
        ("S2_ST_ROC", "30m"), ("N13_3OUTSIDE", "30m")]
for nm, tf_ in LEAD:
    m = (names == nm) & (tfs == tf_)
    for jt in ("1h", "4h"):
        mf = m & (V39[jt] == side)
        R2[f"{nm} {tf_} · V3.9 {jt} 같은 방향만"] = {"신호당": per_signal(mf), "봇": bot(mf), "그대로 신호당": per_signal(m), "그대로 봇": bot(m)}
allm = np.ones(len(S), bool)
for jt in ("1h", "4h"):
    R2[f"121개 전체 신호 · V3.9 {jt} 같은 방향 / 반대 방향 / 없음"] = {
        "같은 방향": per_signal(allm & (V39[jt] == side)), "반대 방향": per_signal(allm & (V39[jt] == -side)), "없음": per_signal(allm & (V39[jt] == 0))}
v1h = (names == "V39_ALL") & (tfs == "1h")
cmo = (names == "S3_CMO_SANDWICH") & np.isin(tfs, ["30m", "1h"])
top5 = np.zeros(len(S), bool)
for nm, tf_, *_ in LIVE[:5]:
    top5 |= (names == nm) & (tfs == tf_)
top10 = np.zeros(len(S), bool)
for nm, tf_, *_ in LIVE[:10]:
    top10 |= (names == nm) & (tfs == tf_)
for lab, m in (("V3.9 1h + CMO 샌드위치 30m·1h", v1h | cmo), ("실시간 상위 5개 합치기", top5), ("실시간 상위 10개 합치기", top10)):
    for stop in (0.25, 0.35, 0.50):
        R2[f"{lab} / 손절 -{int(stop * 100)}%"] = {"봇": bot(m, stop), "봇 + V3.9 4h 같은 방향만": bot(m & (V39["4h"] == side), stop)}
OUT["2 V3.9 쓰는 법"] = R2
txt.append("\n## 2. V3.9 쓰는 법")
for k, v in R2.items():
    txt.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
log("part 2")
# ---------------------------------------------------------------- (3) does "good now AND good before" carry over to the next 20 days?
cell = pd.factorize(pd.Series(names).str.cat(tfs, sep="@"))[0]
ncell = cell.max() + 1
day = (t + KST) // DAY
w35 = W[:, 1]
res3 = []
ends = np.arange((ms("2022-01-01") + KST) // DAY, (ms("2026-09-10") + KST) // DAY, 10)
for d_end in ends:
    look = (day > d_end - 28) & (day <= d_end) & good          # last 20 trading days ~ 28 calendar days
    past = (day <= d_end - 28) & (day > d_end - 28 - 3 * 365) & good
    nxt = (day > d_end) & (day <= d_end + 28) & good
    s_l = np.bincount(cell[look], w35[look], ncell); n_l = np.bincount(cell[look], minlength=ncell)
    s_p = np.bincount(cell[past], w35[past], ncell); n_p = np.bincount(cell[past], minlength=ncell)
    s_n = np.bincount(cell[nxt], w35[nxt], ncell); n_n = np.bincount(cell[nxt], minlength=ncell)
    with np.errstate(invalid="ignore", divide="ignore"):
        m_l, m_p, m_n = s_l / n_l, s_p / n_p, s_n / n_n
    ok = (n_l >= 10) & (n_p >= 100) & (n_n >= 5)
    if ok.sum() < 30:
        continue
    order = np.argsort(-np.where(ok, m_l, -np.inf))
    top_now = order[:10]
    both = [c for c in order if ok[c] and m_p[c] > 0][:10]
    res3.append({"끝": int(d_end), "전체 다음 20일": float(np.nansum(s_n[ok]) / n_n[ok].sum()),
                 "지금 상위 10 다음 20일": float(s_n[top_now].sum() / max(n_n[top_now].sum(), 1)),
                 "지금 상위 10 지금 20일": float(s_l[top_now].sum() / max(n_l[top_now].sum(), 1)),
                 "지금 상위 + 과거 플러스 10 다음 20일": float(s_n[both].sum() / max(n_n[both].sum(), 1)) if both else np.nan,
                 "과거만 상위 10 다음 20일": float(s_n[np.argsort(-np.where(ok, m_p, -np.inf))[:10]].sum() /
                                         max(n_n[np.argsort(-np.where(ok, m_p, -np.inf))[:10]].sum(), 1))})
R3 = pd.DataFrame(res3)
summ = {k: round(float(R3[k].mean()), 4) for k in R3.columns if k != "끝"}
summ["지금 상위 + 과거 플러스가 전체보다 나은 구간 비율"] = round(float((R3["지금 상위 + 과거 플러스 10 다음 20일"] > R3["전체 다음 20일"]).mean()), 3)
summ["지금 상위 10이 전체보다 나은 구간 비율"] = round(float((R3["지금 상위 10 다음 20일"] > R3["전체 다음 20일"]).mean()), 3)
summ["구간 수"] = len(R3)
OUT["3 지금 좋은 매매법이 다음 20일에도 좋은가"] = summ
txt.append("\n## 3. 지금 좋은 매매법이 다음 20일에도 좋은가 (2022-01 ~ 2026-09, 10일마다, 신호당 평균, 손절 -35%, L5)\n" + json.dumps(summ, ensure_ascii=False, indent=1))
log("part 3")
# ---------------------------------------------------------------- (4) all cells: good in the live window and before (core + DeepSeek)
g = pd.DataFrame({"cell": pd.Series(names).str.cat(tfs, sep=" "), "set": sets, "w": w35, "per": np.select(
    [PER["과거 2021-06~2024-12"], PER["최근 2025-01~2026-09"], PER["실시간 20일 구간 10/06~10/24"]], ["과거", "최근", "실시간"], "기타")})
g = g[g.per != "기타"].dropna()
P = g.groupby(["cell", "set", "per"]).w.agg(["mean", "size"]).unstack("per")
P.columns = [f"{a}_{b}" for a, b in P.columns]
P = P.reset_index()
both = P[(P["mean_실시간"] > 0) & (P["size_실시간"] >= 10) & (P["mean_과거"] > 0) & (P["mean_최근"] > 0)].sort_values("mean_실시간", ascending=False)
OUT["4 실시간도 과거도 최근도 플러스인 칸"] = json.loads(both.round(4).to_json(orient="records", force_ascii=False))
txt.append("\n## 4. 실시간 20일 · 과거 · 최근 모두 신호당 플러스인 칸 (손절 -35%, L5, 실시간 신호 10개 이상)\n" + both.round(4).to_string())
txt.append(f"\n전체 칸 {len(P)}개 중 {len(both)}개. 세트별: {both.set.value_counts().to_dict()}")
json.dump(OUT, open(os.path.join(OUTD, "live20_44.json"), "w"), ensure_ascii=False, indent=1, default=float)
open(os.path.join(OUTD, "live20_44.txt"), "w").write("\n".join(txt))
print("\n".join(txt))
log("done")
