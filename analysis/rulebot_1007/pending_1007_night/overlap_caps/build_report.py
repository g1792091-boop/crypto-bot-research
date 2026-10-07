"""Assemble overlap_caps.json and overlap_caps_KO.md from the ovl5 outputs (every number comes from out/*.csv).

    python3 -I -B build_report.py <ovl5_dir>
"""
import json
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common5 as C  # noqa: E402

D = sys.argv[1]
O = os.path.join(D, "out")
P = pd.read_csv(os.path.join(O, "pairs_all.csv"))
PS = pd.read_csv(os.path.join(O, "pair_shares.csv"))
KH = pd.read_csv(os.path.join(O, "kappa_halves.csv"))
B = pd.read_csv(os.path.join(O, "runs_book.csv"))
T = pd.read_csv(os.path.join(O, "runs_trader.csv"))
CR = pd.read_csv(os.path.join(O, "crowding.csv"))
DS = pd.read_csv(os.path.join(O, "daily_stop.csv"))
RATES = pd.read_csv(os.path.join(O, "rates.csv"))
DIST = pd.read_csv(os.path.join(O, "distinct_vs_T17.csv"))
HUBB = pd.read_csv(os.path.join(O, "runs_book_hub.csv"))
HUBT = pd.read_csv(os.path.join(O, "runs_trader_hub.csv"))
HUBB["dtr"] = HUBB.dTrades / (HUBB.trades - HUBB.dTrades)
T17S_LIST = C.WAVE1 + ["F16_FIB500", "F7_RF_TRIPLE", "N09_ALLIG_AROON", "F9_IFVG", "N07_ICHI_CMO", "DOGE", "N13_3OUTSIDE"]
PP = P[(P.k_card_1h >= 0.5) & (P.r_sig >= 0.5)]
PP17 = PP[PP.A.isin(C.WAVE1 + C.WAVE2) & PP.B.isin(C.WAVE1 + C.WAVE2)]
PP17S = PP[PP.A.isin(T17S_LIST) & PP.B.isin(T17S_LIST)]
B["dtr"] = B.dTrades / (B.trades - B.dTrades)
B["cfg"] = B.cs_cap.astype(str) + "/" + B.cluster + "/" + B.book_cap.astype(str)
T["cfg"] = T.cs_cap.astype(str) + "/" + T.cluster + "/" + T.book_cap.astype(str)


def pair(a, b):
    a, b = sorted([a, b])
    return P[(P.A == a) & (P.B == b)].iloc[0]


def dshare(a, b, col):
    return float(PS[(PS.A == a) & (PS.B == b)][col].iloc[0])


def half(a, b):
    a, b = sorted([a, b])
    r = KH[(KH.A == a) & (KH.B == b)].iloc[0]
    return float(r.k_1h_IS), float(r.k_1h_CF)


def f(x, n=3, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{n}f}" if sign else f"{x:.{n}f}"


def pct(x, n=1, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{100 * x:+.{n}f}%" if sign else f"{100 * x:.{n}f}%"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def brow(st, cfg, scope="CARD", thin=1.0):
    x = B[(B.set == st) & (B.scope == scope) & (B.thin == thin) & (B.cfg == cfg)]
    return x.iloc[0] if len(x) else None


def wave_tag(s, swapped=False):
    if swapped and s in ("N09_ALLIG_AROON", "F9_IFVG"):
        return "예비→W2"
    return {"W1": "W1", "W2": "W2", "R": "예비"}[C.WAVE[s]]


# ---------------------------------------------------------------- step 1 numbers
n_pairs = len(P)
same15_med, same15_p90, same15_max = P["15m_bar"].median(), P["15m_bar"].quantile(.9), P["15m_bar"].max()
k1h_med, k1h_p90 = P.k_card_1h.median(), P.k_card_1h.quantile(.9)
rsig_med, rsig_p90, rsig_max = P.r_sig.median(), P.r_sig.quantile(.9), P.r_sig.max()
rtr_med, rtr_p90, rtr_max = P.r_tr.median(), P.r_tr.quantile(.9), P.r_tr.max()
card4h_obs, card4h_ch = PS.card_4h.median(), PS.card_4h_chance.median()
kh_corr = float(np.corrcoef(KH.k_1h_IS, KH.k_1h_CF)[0, 1])

top = P.sort_values("k_card_1h", ascending=False).head(26)
rows_top = []
for _, r in top.iterrows():
    a, b = r.A, r.B
    is_, cf_ = half(a, b)
    rows_top.append([
        f"{a} ({wave_tag(a)})", f"{b} ({wave_tag(b)})",
        f"{f(dshare(a, b, '15m_bar'), 2)} / {f(dshare(b, a, '15m_bar'), 2)}",
        f(r["30m_bar"], 2), f(r["1h_bar"], 2), f(r["15m_1bar"], 2),
        f"{f(max(dshare(a, b, '15m_4h'), dshare(b, a, '15m_4h')), 2)} ({f(max(dshare(a, b, '15m_4h_chance'), dshare(b, a, '15m_4h_chance')), 2)})",
        f"{f(r.card_1h, 2)}", f"**{f(r.k_card_1h, 2)}** ({f(is_, 2)}/{f(cf_, 2)})", f(r.k_card_same15, 2),
        f(r.r_sig, 2), f(r.r_sig_g, 2), f(r.r_tr, 2), f(r.coheld_lift, 1)])

# proposed cluster check
prop_rows = []
for cl, mem in C.CLUSTERS_PROPOSED.items():
    for i, a in enumerate(mem):
        for b in mem[i + 1:]:
            r = pair(a, b)
            same = (r.k_card_1h >= 0.5) and (r.r_sig >= 0.5)
            prop_rows.append([cl, a, b, f(r["15m_bar"], 2), f(r.k_card_same15, 2), f(r.k_card_1h, 2), f(r.r_sig, 2),
                              f(r.r_tr, 2), "두 조건 통과" if same else ("진입만 겹침" if r.k_card_1h >= 0.5 else "아님")])

# 4h saturation illustration
sat_rows = []
for a, b in (("N01_ST_EMA", "N23_HA_ST"), ("N02_ST_KST", "N23_HA_ST"), ("N04_ST_KLINGER", "N23_HA_ST"),
             ("N23_HA_ST", "S2_ST_ROC"), ("N10_HA_PSAR", "N23_HA_ST"), ("DOGE", "S2_ST_ROC"), ("F16_FIB382", "F9_FVG")):
    o = max(dshare(a, b, "card_4h"), dshare(b, a, "card_4h"))
    c = max(dshare(a, b, "card_4h_chance"), dshare(b, a, "card_4h_chance"))
    o1 = max(dshare(a, b, "card_same15"), dshare(b, a, "card_same15"))
    c1 = max(dshare(a, b, "card_same15_chance"), dshare(b, a, "card_same15_chance"))
    sat_rows.append([a, b, f(o, 2), f(c, 2), f(o / c, 2), f(o1, 2), f(c1, 3), f(o1 / c1, 1)])

# final clusters
REC = {"ST": ["N23_HA_ST", "S2_ST_ROC", "N02_ST_KST", "N01_ST_EMA"], "RF": ["DOGE", "F7_RF_TRIPLE"]}
WATCH = [("N07_ICHI_CMO", "N22_VORTEX_PSAR"), ("F4_FAN", "F7_RF_TRIPLE"), ("N04_ST_KLINGER", "N23_HA_ST"),
         ("F12_MSS", "S4_BB_BBP"), ("F6_VWAP_CROSS", "N09_ALLIG_AROON"), ("F16_FIB382", "F16_FIB500"),
         ("N10_HA_PSAR", "N23_HA_ST")]
rec_rows = []
for cl, mem in REC.items():
    for i, a in enumerate(mem):
        for b in mem[i + 1:]:
            r = pair(a, b)
            is_, cf_ = half(a, b)
            rec_rows.append([cl, f"{a} ({wave_tag(a)})", f"{b} ({wave_tag(b)})", f(r.k_card_1h, 2),
                             f"{f(is_, 2)}/{f(cf_, 2)}", f(r.r_sig, 2), f(r.r_tr, 2), f(r.coheld_lift, 1)])
watch_rows = []
for a, b in WATCH:
    r = pair(a, b)
    watch_rows.append([a, b, f(r["15m_bar"], 2), f(r.k_card_same15, 2), f(r.k_card_1h, 2), f(r.r_sig, 2),
                       f(r.r_tr, 2), f(r.coheld_lift, 1)])

# ---------------------------------------------------------------- step 2 numbers
GRID = ["0/off/0", "4/off/0", "3/off/0", "2/off/0", "0/REC/0", "0/PROP/0", "0/off/10", "0/off/8", "0/off/6",
        "3/off/8", "3/PROP/8", "3/REC/8", "2/REC/8", "4/REC/0", "3/REC/10", "4/REC/10", "4/off/10"]


def grid_rows(st, scope="CARD", thin=1.0):
    rows = []
    for cfg in GRID:
        r = brow(st, cfg, scope, thin)
        if r is None:
            continue
        base = cfg == "0/off/0"
        rows.append([cfg, f(r.trades_per_day, 1), pct(r.blocked_share), f"{pct(r.blocked_share_IS)}/{pct(r.blocked_share_CF)}",
                     "-" if base else pct(r.dtr, 1, True), f"{int(r.same_dir_max)} ({f(r.same_dir_max_R_1p5, 1)})",
                     f(r.same_dir_p99, 0), f(r.same_dir_p50, 0), int(r.cs_max), pct(r.share_time_cs_ge5),
                     f(r.book_sd_day, 1), f(r.diversification_ratio, 2), f(r.worst_day_demeaned, 1),
                     f(r.meanR, 3, True), f(r.meanG, 4, True), "-" if base else f(r.blocked_meanG, 4, True),
                     "-" if base else f"{f(r.dG_book, 0, True)} [{f(r.dG_book_ci_lo, 0, True)}, {f(r.dG_book_ci_hi, 0, True)}]",
                     "-" if base else f"{f(r.dR_book, 0, True)}"])
    return rows


GH = ["캡 (코인-방향/클러스터/북 방향)", "거래/일", "막힌 시도 비율", "IS/CF", "거래 수 변화", "동시 같은 방향 최대 (1h 1.5% 가중 R)",
      "p99", "중앙값", "코인-방향 최대", "코인-방향 5+ 시간 비율", "북 일간 SD (R)", "분산비", "최악의 날 (평균 제거, R)",
      "평균 순R/거래", "평균 총R/거래", "막힌 진입 총R", "북 총R 변화 5년 [95% 주 블록]", "북 순R 변화 5년"]


def trader_rows(st, cfgs, scope="CARD", thin=1.0):
    x = T[(T.set == st) & (T.scope == scope) & (T.thin == thin)]
    names = list(x[x.cfg == cfgs[0]].trader)
    rows = []
    for s in names:
        row = [s, wave_tag(s, st == "T17S")]
        b0 = x[(x.cfg == cfgs[0]) & (x.trader == s)].iloc[0]
        row += [int(b0.trades_base), f(b0.meanR_base, 3, True)]
        for cfg in cfgs:
            y = x[(x.cfg == cfg) & (x.trader == s)].iloc[0]
            row += [int(y.intended), pct(y.blocked_share), pct(y.d_trades_pct, 1, True), f(y.dR, 0, True),
                    f(y.meanR - y.meanR_base, 3, True)]
        rows.append(row)
    tot = [B[(B.set == st) & (B.scope == scope) & (B.thin == thin) & (B.cfg == c)].iloc[0] for c in cfgs]
    row = ["합계", "", int(tot[0].trades - tot[0].dTrades), f(B[(B.set == st) & (B.scope == scope) & (B.thin == thin) & (B.cfg == '0/off/0')].iloc[0].meanR, 3, True)]
    for r in tot:
        row += [int(r.intended), pct(r.blocked_share), pct(r.dtr, 1, True), f(r.dR_book, 0, True), f(r.dR_per_trade_taken, 3, True)]
    rows.append(row)
    return rows


def TH(cfgs):
    h = ["트레이더", "웨이브", "기준 거래 수 (5y)", "기준 평균 순R"]
    for c in cfgs:
        h += [f"[{c}] 시도", "막힘", "거래 수 변화", "순R 합 변화", "순R/거래 변화"]
    return h


# wants / exposure (uncapped)
want_rows = []
for st, scope, thin, lab in (("T10", "CARD", 1.0, "웨이브1 10명"), ("T17", "CARD", 1.0, "웨이브1+2 17명 (본안)"),
                             ("T17S", "CARD", 1.0, "17명, 교체안"), ("T23", "CARD", 1.0, "23명 (예비 포함)"),
                             ("T17", "U", 1.0, "17명, 전원 15m/30m/1h(+4h)"), ("T17", "CARD", 0.5, "17명, AI가 신호 절반 건너뜀")):
    d = DS[(DS.set == st) & (DS.scope == scope) & (DS.thin == thin)].iloc[0]
    r = brow(st, "0/off/0", scope, thin)
    want_rows.append([lab, f(r.trades_per_day, 1), f(d.want_raw15_ge5_per_year, 0), f(d.want_raw1h_ge5_per_year, 0),
                      f(d.want_free15_ge5_per_year, 1), f(d.want_free1h_ge5_per_year, 0),
                      pct(d.hold_cs_ge5_share_time), f(d.hold_cs_ge5_episodes_per_year, 0), int(d.hold_cs_max),
                      f"{int(r.same_dir_max)} ({f(r.same_dir_max_R_1p5, 1)})", f(r.same_dir_p99, 0), f(r.same_dir_p50, 0),
                      pct(r.share_time_same_dir_ge8)])

# crowding
cr_rows = []
for st in ("T17", "T17S"):
    x = CR[(CR.set == st) & (CR.scope == "CARD") & (CR.thin == 1.0) & (CR.measure == "coin_side_open")]
    for _, r in x.iterrows():
        cr_rows.append([st, f"{int(r.level)}{'+' if r.level == 4 else ''}", int(r.n), f(r.meanR, 3, True), f(r.meanG, 4, True),
                        f(r.meanG - r.meanR, 3)])
crd = {}
for st in ("T17", "T17S"):
    for m in ("coin_side_open", "same_dir_open"):
        r = CR[(CR.set == st) & (CR.scope == "CARD") & (CR.thin == 1.0) & (CR.measure == m + "_diff_gross_hi_minus_lo")].iloc[0]
        crd[(st, m)] = (float(r.meanR), float(r.meanG), float(r.ci_hi))

# sensitivity
SENS = ["3/PROP/8", "3/REC/8", "4/REC/10", "0/off/8", "3/off/0", "0/REC/0"]
sens_rows = []
for st, scope, thin, lab in (("T10", "CARD", 1.0, "웨이브1 10명"), ("T17", "CARD", 1.0, "17명 본안"),
                             ("T17S", "CARD", 1.0, "17명 교체안"), ("T23", "CARD", 1.0, "23명"),
                             ("T17", "U", 1.0, "17명, U 범위"), ("T17", "CARD", 0.5, "17명, 절반 건너뜀"),
                             ("T17S", "CARD", 0.5, "교체안, 절반 건너뜀")):
    row = [lab]
    for cfg in SENS:
        r = brow(st, cfg, scope, thin)
        row.append(f"{pct(r.blocked_share)} / {pct(r.dtr, 1, True)}" if r is not None else "-")
    sens_rows.append(row)

# daily stops
stop_rows = []
for st, cfg in (("T10", "0/off/0"), ("T17", "0/off/0"), ("T17", "3/PROP/8"), ("T17", "3/REC/8"), ("T17S", "0/off/0"),
                ("T17S", "4/REC/10"), ("T17S", "3/REC/8"), ("T23", "0/off/0")):
    r = brow(st, cfg)
    stop_rows.append([st, cfg, f(r.book_mean_day, 1, True), f(r.book_sd_day, 1), pct(r.share_book_days_le_m12R),
                      pct(r.share_book_days_le_m20R), pct(r.share_book_days_le_m30R), pct(r.share_trader_days_le_m3R),
                      pct(r.share_trader_days_le_m4R)])

# distinctness of reserves
dist_rows = []
for _, r in DIST.iterrows():
    dist_rows.append([r.strategy, wave_tag(r.strategy), f"{f(r.max_k_card_1h, 2)} ({r.with_k_card_1h})",
                      f"{f(r.max_r_sig, 2)} ({r.with_r_sig})", f"{f(r.max_r_tr, 2)} ({r.with_r_tr})", f(r.mean_r_tr, 3),
                      f(float(RATES[RATES.strategy == r.strategy].per_day.iloc[0]), 1)])

# key numbers for the text
b0 = brow("T17", "0/off/0"); bP = brow("T17", "3/PROP/8"); bR8 = brow("T17", "3/REC/8"); bR10 = brow("T17", "4/REC/10")
s0 = brow("T17S", "0/off/0"); sR10 = brow("T17S", "4/REC/10"); sR8 = brow("T17S", "3/REC/8"); sREC = brow("T17S", "0/REC/0")
s5R10 = brow("T17S", "4/REC/10", thin=0.5); t5P = brow("T17", "3/PROP/8", thin=0.5)
b8 = brow("T17", "0/off/8"); b10 = brow("T17", "0/off/10"); c3 = brow("T17", "3/off/0"); c4 = brow("T17", "4/off/0")
c2 = brow("T17", "2/off/0"); clR = brow("T17", "0/REC/0"); clP = brow("T17", "0/PROP/0")
t10P = brow("T10", "3/PROP/8"); t10R = brow("T10", "4/REC/10"); t10_8 = brow("T10", "0/off/8")
TP = T[(T.set == "T17") & (T.scope == "CARD") & (T.thin == 1.0) & (T.cfg == "3/PROP/8")].set_index("trader")
TR10 = T[(T.set == "T17") & (T.scope == "CARD") & (T.thin == 1.0) & (T.cfg == "4/REC/10")].set_index("trader")
TS10 = T[(T.set == "T17S") & (T.scope == "CARD") & (T.thin == 1.0) & (T.cfg == "4/REC/10")].set_index("trader")
TREC = T[(T.set == "T17") & (T.scope == "CARD") & (T.thin == 1.0) & (T.cfg == "0/REC/0")].set_index("trader")
d17 = DS[(DS.set == "T17") & (DS.scope == "CARD") & (DS.thin == 1.0)].iloc[0]
d17s = DS[(DS.set == "T17S") & (DS.scope == "CARD") & (DS.thin == 1.0)].iloc[0]
ns2, nn02, nn23 = pair("N23_HA_ST", "S2_ST_ROC"), pair("N02_ST_KST", "N23_HA_ST"), pair("N10_HA_PSAR", "N23_HA_ST")
ndf = pair("DOGE", "F7_RF_TRIPLE"); nf = pair("F16_FIB382", "F9_FVG"); nff = pair("F16_FIB382", "F16_FIB500")
n0722 = pair("N07_ICHI_CMO", "N22_VORTEX_PSAR"); nf47 = pair("F4_FAN", "F7_RF_TRIPLE")
dI = DIST.set_index("strategy")

# ---------------------------------------------------------------- markdown
md = []
A = md.append
A("# AI 트레이더 5년 진입 단위 겹침 지도와 노출 캡 차단율 (2021-08 ~ 2026-09)")
A("")
A("작성: ovl5 에이전트, 2026-10-08 KST. 모든 숫자는 `scratchpad/ovl5/` 스크립트가 만든 `out/*.csv`에서 나왔다 (표마다 출처 표시). "
  "레포는 읽기만 했다.")
A("")
A("## 0. 한눈에 보기")
A("")
A(f"1. **진입 단위 겹침은 생각보다 작다.** 23개 전략 253쌍에서 \"같은 코인, 같은 방향, 같은 15분봉\" 비율의 중앙값은 {pct(same15_med)}, "
  f"상위 10%가 {pct(same15_p90)}, 최대 {pct(same15_max)} (N10_HA_PSAR↔N23_HA_ST). 라이브 4.8일로 잰 \"4시간 창 87-98% 동시 발생\"은 신호가 촘촘해서 생긴 착시다: "
  f"4시간 창 일치율의 중앙값 {pct(card4h_obs)}는 신호를 7일 밀어도 {pct(card4h_ch)}가 나온다 (우연 수준).")
A(f"2. **같은 베팅 묶음(클러스터)은 둘뿐이다.** 규칙(우연 보정 1시간 동시 진입 κ ≥ 0.5 평균 연결 + 묶음 안 모든 쌍의 일별 every-signal R 상관 ≥ 0.5)으로 "
  f"남는 것은 **ST = {{N23_HA_ST, S2_ST_ROC, N02_ST_KST, N01_ST_EMA}}**와 **RF = {{DOGE, F7_RF_TRIPLE}}**. "
  f"제안서의 pullback 묶음 (F16_FIB382↔F9_FVG κ {f(nf.k_card_1h, 2)}, 같은 봉 {pct(nf['15m_bar'])})과 DeepSeek 추세 묶음 (F6는 F4/F7과 κ 0.16-0.31)은 같은 베팅이 아니다. "
  f"N10_HA_PSAR도 ST에 넣을 근거가 약하다 (κ {f(nn23.k_card_1h, 2)}, 트레이더 일별 R 상관 {f(nn23.r_tr, 2)}). κ는 두 반기에서 거의 같다 (IS/CF 상관 {f(kh_corr, 3)}): 전략 정의의 성질이다.")
A(f"3. **한 포지션 트레이더 사이의 상관은 낮다.** 트레이더 일별 순R 상관 중앙값 {f(rtr_med, 2)}, 최대 {f(rtr_max, 2)} (DOGE↔V39_ALL). 반면 every-signal 일별 R 상관은 중앙값 {f(rsig_med, 2)}, "
  f"최대 {f(rsig_max, 2)} (N23↔S2). 신호 흐름은 비슷해도 한 번에 한 코인만 드는 트레이더들은 서로 다른 거래를 한다.")
A(f"4. **제안 캡(코인-방향 3 / 클러스터 1 / 같은 방향 8)은 17명 규칙 프록시에서 진입 시도의 {pct(bP.blocked_share)}를 막고 거래 수를 {pct(bP.dtr, 1, True)} 줄인다.** "
  f"차단은 고르게 오지 않는다: DOGE {pct(TP.loc['DOGE'].d_trades_pct, 1, True)}, N02_ST_KST {pct(TP.loc['N02_ST_KST'].d_trades_pct, 1, True)}, "
  f"N07_ICHI_CMO {pct(TP.loc['N07_ICHI_CMO'].d_trades_pct, 1, True)}, F16_FIB500 {pct(TP.loc['F16_FIB500'].d_trades_pct, 1, True)} (웨이브2가 대부분 맞는다). "
  f"가장 많이 막는 것은 북 방향 8이다: 17명이 거의 늘 포지션을 들고 있어서 같은 방향 보유 수의 중앙값이 이미 {f(b0.same_dir_p50, 0)}이다 (8 이상인 시간 {pct(b0.share_time_same_dir_ge8)}).")
A(f"5. **캡은 엣지를 만들지 않는다.** 막힌 진입의 평균 총R(비용 전)은 {f(bP.blocked_meanG, 4, True)}로 실제 진입({f(bP.meanG, 4, True)})보다 오히려 높았고, "
  f"북 총R은 5년에 {f(bP.dG_book, 0, True)}R [{f(bP.dG_book_ci_lo, 0, True)}, {f(bP.dG_book_ci_hi, 0, True)}] 줄었다. 순R이 좋아 보이는 것은 거래가 줄어 비용이 줄었기 때문이다. "
  f"붐빈 진입(같은 코인-방향에 이미 3명 이상)의 총R은 붐비지 않은 진입보다 {f(crd[('T17','coin_side_open')][0], 3, True)}R [{f(crd[('T17','coin_side_open')][1], 3, True)}, {f(crd[('T17','coin_side_open')][2], 3, True)}]: 붐빈 진입이 더 나쁘다는 증거는 없다.")
A(f"6. **캡이 하는 일은 꼬리 위험 축소다.** 17명 무캡: 같은 방향 동시 최대 {int(b0.same_dir_max)}R (1h 1.5% 위험 가중 {f(b0.same_dir_max_R_1p5, 1)}R), p99 {f(b0.same_dir_p99, 0)}R, "
  f"북 일간 SD {f(b0.book_sd_day, 1)}R, 분산비 {f(b0.diversification_ratio, 2)} (트레이더들이 독립이면 1.0). 제안 캡은 최대 8R, SD {f(bP.book_sd_day, 1)}R, 분산비 {f(bP.diversification_ratio, 2)}.")
A(f"7. **5명 이상이 같은 코인-방향을 원하는 일:** 17명 무캡에서 비어 있는 트레이더 5명 이상이 같은 15분봉에 같은 코인-방향으로 진입하려는 일은 연 {f(d17.want_free15_ge5_per_year, 0)}회, "
  f"같은 1시간 안이면 연 {f(d17.want_free1h_ge5_per_year, 0)}회. 5명 이상이 같은 코인-방향을 동시에 들고 있는 시간은 {pct(d17.hold_cs_ge5_share_time)} (연 {f(d17.hold_cs_ge5_episodes_per_year, 0)}구간).")
A(f"8. **권고:** 클러스터는 ST와 RF 둘만. 웨이브2의 **S2_ST_ROC → N09_ALLIG_AROON**, **N02_ST_KST → F9_IFVG**로 교체 (둘 다 N23의 같은 베팅; 교체 후보는 남은 예비 중 가장 독립적인 두 개). "
  f"DOGE와 F7_RF_TRIPLE은 둘 다 두되 RF 클러스터 캡으로 묶는다. 판정 기간 캡은 **코인-방향 4 / 클러스터 1 (ST, RF) / 같은 방향 10**: 교체안 17명에서 시도의 {pct(sR10.blocked_share)}를 막고 "
  f"거래 수 {pct(sR10.dtr, 1, True)}, 같은 방향 최대 10R (가중 {f(sR10.same_dir_max_R_1p5, 1)}R). 제안값 3/1/8은 실돈 단계에서 (그때 트레이더 수에 맞춰) 쓴다.")
A(f"9. **부수 발견 (같은 리스크 매니저):** 규칙 프록시 17명의 북은 하루 평균 {f(b0.book_mean_day, 1, True)}R (거래당 비용 때문). 그래서 제안된 북 일일 정지 -12R은 날의 {pct(b0.share_book_days_le_m12R)}에 걸린다 "
  f"(평균을 빼도 {pct(d17.share_book_days_le_m12R_demeaned)}). 트레이더별 -3R/일은 트레이더-일의 {pct(b0.share_trader_days_le_m3R)}. 북 정지는 -30R 근처로 다시 잡아야 한다 (무캡 {pct(b0.share_book_days_le_m30R)}, 권고 캡 교체안 {pct(sR10.share_book_days_le_m30R)}).")
A("")
A("## 1. 데이터와 방법")
A("")
A("- **신호와 결과:** 검증된 lens2/multi_tf precompute (`lens2/multi_tf/outc/out_<tf>_<coin>.npz`): 36 core + 44 DeepSeek 정의의 모든 신호를 혼자 돌린 결과. "
  "2 ATR 손절 + ROE 래더, taker 0.05% + 슬리피지 0.02% 양쪽, 펀딩, 손절/래더는 15분봉으로 확인, 진입은 신호봉 종가 다음 15분봉 시가. 2021-08-01 ~ 2026-09-30, 6코인, "
  "Binance USD-M 봉 (`binance/signals`, 6코인 15분봉 시각 동일 확인). 23개 전략을 `ovl5/build_sig.py`로 추출 (2,202,218행, 비유한 R 0행). 재생성은 필요 없었다.")
A("- **트레이더 진입 범위 (CARD):** select_portfolio.json 카드에 적힌 진입 타임프레임; 카드가 없는 전략은 같은 규칙(5년 every-signal 총R ≥ 0인 15m/30m/1h 셀만, sel_tp/fy_side.json)을 기계적으로 적용. "
  "4h는 카드에 4h가 있는 N23_HA_ST, F6_VWAP_CROSS만, 20x(또는 30x)로 사이징되는 신호만. 범위는 `common5.py` CARD 표. 민감도: U = 전원 15m/30m/1h + 사이징되는 4h.")
A("- **겹침 지표 (단계 1, `overlap.py`):** A→B 비율 = A의 신호(코인, 방향, 진입 15분봉) 중 같은 코인-방향의 B 신호가 창 안에 있는 비율. 창: 같은 봉, ±1봉 (그 타임프레임 기준), ±4시간; "
  "카드 범위 전체(타임프레임 섞음)로는 같은 15분 진입 시점, ±1시간, ±4시간. **우연 수준** = B를 ±7일 밀었을 때 같은 비율 (두 방향 평균). "
  "**κ = (관측 - 우연) / (1 - 우연)**, 두 방향 중 큰 값 (희소한 쪽이 촘촘한 쪽에 얼마나 들어가는지). 일별 R 상관 = 카드 범위 every-signal 순R(과 총R)의 일별 합의 피어슨 상관.")
A("- **트레이더 단위 지표 (`coholding.py`):** 무캡 동시 실행에서 A의 진입 순간 B가 같은 코인-방향을 들고 있던 비율과 그 우연 대비 배수(lift), 트레이더 일별 순R 상관 (청산일 기준).")
A("- **한 포지션 트레이더 (단계 2, `capsim.py`):** 셋업 B. 비어 있는 트레이더는 같은 순간 신호 중 긴 타임프레임 → 넓은 손절 → 코인 순서로 고른다. 전환 없음, 보유 중 신호 무시. "
  "포지션은 진입봉 e ~ 청산 15분봉 x를 차지하고 e' > x부터 다시 진입 가능. 1% 위험 → R = 그 트레이더 자본의 %. 캡은 진입 순간 전체 트레이더의 열린 포지션으로 확인; "
  "첫 선택이 막히면 같은 순간의 다음 신호를 시도, 없으면 계속 비어 있다(다음 신호에서 다시 시도). 같은 순간 트레이더 간 순서: 긴 타임프레임, 넓은 손절, 날짜별 트레이더 번호 회전 (제안서의 사전 등록 규칙). "
  "\"막힌 시도 비율\" = 비어 있는 트레이더의 첫 선택 중 캡에 걸린 비율 (같은 트레이더가 여러 번 걸릴 수 있음). 거래 수 변화가 실제 손실이다.")
A("- **검증 (`verify.py`, out/verify.log):** 무캡 동시 실행 = 17명 각자 단독 실행과 거래 단위로 동일; 독립 구현한 셋업 B와 N10 13,237거래 일치; "
  "캡 3/REC/8, 2/REC/6, 4/REC/10에서 모든 15분봉에 캡 위반 0, 트레이더 자기 겹침 0, 시도 = 진입 + 막혀서 빈 채로 남음.")
A("- **불확실성:** 겹침은 전략 정의에서 결정적으로 나오는 성질이라 표본오차가 거의 없다 (반기 간 κ 상관 0.996). 캡의 R 효과는 주 블록 부트스트랩 95% 구간 (2,000회).")
A("")
A("## 2. 단계 1: 5년 진입 단위 겹침")
A("")
A(f"253쌍 요약 (`out/pairs_all.csv`): 15m 같은 봉 비율(두 방향 중 큰 값) 중앙값 {pct(same15_med)}, p90 {pct(same15_p90)}; 카드 범위 κ(1시간) 중앙값 {f(k1h_med, 2)}, p90 {f(k1h_p90, 2)}; "
  f"every-signal 일별 순R 상관 중앙값 {f(rsig_med, 2)}, p90 {f(rsig_p90, 2)}; 트레이더 일별 순R 상관 중앙값 {f(rtr_med, 2)}, p90 {f(rtr_p90, 2)}.")
A("")
A("### 2.1 겹침 상위 26쌍 (카드 범위 κ 1시간 순)")
A("")
A("15m 같은 봉은 A→B / B→A. 나머지 비율은 두 방향 중 큰 값. 괄호 안 ±4h는 우연 수준. κ 괄호는 IS(2021-08~2024-06)/CF(2024-07~2026-09). 출처: out/pair_shares.csv, pairs_all.csv, kappa_halves.csv, "
  "daily_R_corr.csv, daily_gross_corr.csv, trader_daily_R_corr_CARD.csv, entry_coheld_CARD.csv.")
A("")
A(table(["A", "B", "15m 같은 봉 A→B / B→A", "30m 같은 봉", "1h 같은 봉", "15m ±1봉", "15m ±4h (우연)", "카드 ±1h", "κ 1h (IS/CF)",
         "κ 같은 15분", "every-signal 일별 순R 상관", "같은 총R 상관", "트레이더 일별 순R 상관", "트레이더 동시 보유 lift"], rows_top))
A("")
A("### 2.2 4시간 창 지표는 촘촘한 신호에서 포화된다")
A("")
A("라이브 4.8일 분석의 \"같은 코인-방향 4시간 창 87-98%\"를 5년 데이터로 다시 재면 비슷한 숫자가 나오지만, 신호를 7일 밀어도 대부분 나온다. 같은 15분 진입 시점 지표는 우연 대비 훨씬 크게 갈린다. (out/pair_shares.csv)")
A("")
A(table(["A", "B", "카드 4h 창 관측", "우연 (±7일)", "배수", "같은 15분 관측", "우연", "배수"], sat_rows))
A("")
A("### 2.3 제안된 클러스터의 검증")
A("")
A("쌍 판정: \"두 조건 통과\" = κ 1h ≥ 0.5 그리고 every-signal 일별 순R 상관 ≥ 0.5 (클러스터의 필요조건; 묶음은 2.4의 평균 연결로 정한다). \"진입만 겹침\" = κ ≥ 0.5이나 결과 상관 < 0.5. (out/pairs_all.csv)")
A("")
A(table(["제안 클러스터", "A", "B", "15m 같은 봉 (큰 쪽)", "κ 같은 15분", "κ 1h", "every-signal R 상관", "트레이더 R 상관", "판정"], prop_rows))
A("")
A("### 2.4 클러스터 규칙과 최종 정의")
A("")
A("**규칙:** (1) 카드 범위 κ(1시간 안 같은 코인-방향 진입, 우연 보정, 두 방향 중 큰 값)로 평균 연결 계층 군집, 0.5에서 자른다. "
  "(2) 묶음 안 모든 쌍의 every-signal 일별 순R 상관이 0.5 이상일 때만 클러스터로 인정한다 (진입 시점과 결과가 함께 겹쳐야 같은 베팅). "
  "단일 연결은 N23처럼 촘촘한 흐름을 통해 모두를 한 덩어리로 잇기 때문에 쓰지 않는다. 0.6에서 자르면 ST가 {N01, N23, S2}로 줄고 N02가 빠진다 (N02의 평균 κ는 0.596). (`clus.py`)")
A("")
A(table(["클러스터", "A", "B", "κ 1h", "IS/CF", "every-signal R 상관", "트레이더 R 상관", "동시 보유 lift"], rec_rows))
A("")
A("**관찰 목록 (클러스터 아님, 같이 배치하면 숫자를 다시 볼 쌍):**")
A("")
A(table(["A", "B", "15m 같은 봉", "κ 같은 15분", "κ 1h", "every-signal R 상관", "트레이더 R 상관", "동시 보유 lift"], watch_rows))
A("")
A(f"- N07_ICHI_CMO↔N22_VORTEX_PSAR: 진입은 크게 겹치지만 (κ {f(n0722.k_card_1h, 2)}) 결과 상관은 {f(n0722.r_sig, 2)}, 트레이더 상관 {f(n0722.r_tr, 2)}. N22를 배치하면 다시 판단.")
A(f"- F4_FAN↔F7_RF_TRIPLE: κ {f(nf47.k_card_1h, 2)} (경계), 결과 상관 {f(nf47.r_sig, 2)}, 트레이더 상관 {f(nf47.r_tr, 2)}. 평균 연결에서는 F7이 DOGE와 먼저 묶여 F4는 빠진다.")
A(f"- F16_FIB382↔F16_FIB500: 진입은 거의 독립 (κ {f(nff.k_card_1h, 2)}, 같은 봉 {pct(nff['15m_bar'])})이지만 같은 정의 계열이라 판정의 다중검정 가족으로는 하나로 센다 (캡 클러스터는 아님).")
A(f"- N10_HA_PSAR↔N23_HA_ST: N10의 15m 신호 {pct(dshare('N10_HA_PSAR','N23_HA_ST','15m_bar'))}가 N23과 같은 봉 (HA 반전 시점이 같다). 그러나 1시간 κ {f(nn23.k_card_1h, 2)}, 트레이더 상관 {f(nn23.r_tr, 2)}, 동시 보유 lift {f(nn23.coheld_lift, 1)}로 노출은 대체로 따로 움직인다.")
A("- N04_ST_KLINGER (예비): N23과의 쌍은 두 조건을 넘지만 (κ 0.53, 결과 상관 0.77) ST의 다른 멤버들과 평균 κ가 0.5 아래라 평균 연결로는 빠진다. 사실상 ST 사촌이므로 배치하면 ST에 넣는다.")
A("")
A("### 2.4b 쌍 단위로는 더 많이 겹친다: N23 중심의 추세 허브")
A("")
A(f"253쌍 중 {len(PP)}쌍이 두 조건을 모두 넘는다. 웨이브1+2 17명 안에서 {len(PP17)}쌍, 교체안 17명 안에서 {len(PP17S)}쌍. 교체 뒤 남는 쌍은 모두 신호가 촘촘한 추세 흐름 "
  "(N23_HA_ST 108개/일, F7 46개/일, N18 76개/일)을 중심으로 이어진 느슨한 추세 합의다: κ 0.55-0.72, 트레이더 일별 상관 0.21-0.35. 평균 연결은 이들을 하나로 묶지 않는다.")
A("")
A(table(["A", "B", "κ 1h", "every-signal R 상관", "트레이더 R 상관", "동시 보유 lift"],
        [[r.A, r.B, f(r.k_card_1h, 2), f(r.r_sig, 2), f(r.r_tr, 2), f(r.coheld_lift, 1)] for _, r in PP17S.iterrows()]))
A("")
hb = HUBB.set_index(HUBB.cs_cap.astype(str) + "/" + HUBB.cluster + "/" + HUBB.book_cap.astype(str))
ht = HUBT[(HUBT.cluster == "HUB") & (HUBT.cs_cap == 0) & (HUBT.book_cap == 0)].set_index("trader")
A(f"이 허브 {{N23, F4, F7, N18, DOGE, V39}}를 통째로 한 클러스터로 막으면 (교체안, out/runs_book_hub.csv): 클러스터 캡만으로 시도의 {pct(hb.loc['0/HUB/0'].blocked_share)}, 거래 {pct(hb.loc['0/HUB/0'].dtr, 1, True)}; "
  f"DOGE {pct(ht.loc['DOGE'].d_trades_pct, 1, True)}, F4 {pct(ht.loc['F4_FAN'].d_trades_pct, 1, True)}, V39 {pct(ht.loc['V39_ALL'].d_trades_pct, 1, True)}, N18 {pct(ht.loc['N18_VWMA_MACD'].d_trades_pct, 1, True)}. "
  f"4/HUB/10은 {pct(hb.loc['4/HUB/10'].blocked_share)} / {pct(hb.loc['4/HUB/10'].dtr, 1, True)} (권고 4/REC/10은 {pct(hb.loc['4/REC/10'].blocked_share)} / {pct(hb.loc['4/REC/10'].dtr, 1, True)}). "
  f"막힌 진입의 총R은 {f(hb.loc['0/HUB/0'].blocked_meanG, 4, True)}로 진입 평균({f(hb.loc['0/off/0'].meanG, 4, True)})보다 높았다. 느슨한 추세 합의는 클러스터가 아니라 코인-방향 캡과 같은 방향 캡이 맡는 것이 맞다.")
A("")
A("### 2.5 각 전략이 웨이브1+2 17명과 얼마나 겹치는가 (교체 후보 판단용)")
A("")
A("17명 중 자기 자신을 뺀 상대들과의 최대값. (out/distinct_vs_T17.csv, rates.csv)")
A("")
A(table(["전략", "웨이브", "최대 κ 1h (상대)", "최대 every-signal R 상관 (상대)", "최대 트레이더 R 상관 (상대)", "평균 트레이더 R 상관", "카드 범위 신호/일"], dist_rows))
A("")
A("## 3. 단계 2: 17명 동시 실행과 노출 캡")
A("")
A("### 3.1 캡 설정 비교 (웨이브1+2 17명, CARD 범위, 규칙 프록시)")
A("")
A("R 단위: 1R = 한 트레이더 자본의 1%; 북 R = 트레이더 계정들의 합. \"동시 같은 방향 최대\"는 1% 위험 기준 R (괄호: 1h/4h를 1.5%로 둔 경우). "
  "\"분산비\" = 북 일간 SD / √(트레이더 일간 분산의 합). \"막힌 진입 총R\" = 막힌 첫 선택들의 평균 총R. 북 총R 변화의 구간은 주 블록 부트스트랩. 출처: out/runs_book.csv (전체 80개 설정은 json).")
A("")
A(table(GH, grid_rows("T17")))
A("")
A(f"읽는 법: 코인-방향 3은 시도의 {pct(c3.blocked_share)} (거래 {pct(c3.dtr, 1, True)}), 4는 {pct(c4.blocked_share)} ({pct(c4.dtr, 1, True)}), 2는 {pct(c2.blocked_share)} ({pct(c2.dtr, 1, True)}). "
  f"클러스터 캡만: 권고(REC) {pct(clR.blocked_share)} ({pct(clR.dtr, 1, True)}), 제안(PROP) {pct(clP.blocked_share)} ({pct(clP.dtr, 1, True)}). "
  f"북 방향 캡만: 8 → {pct(b8.blocked_share)} ({pct(b8.dtr, 1, True)}), 10 → {pct(b10.blocked_share)} ({pct(b10.dtr, 1, True)}). "
  f"17명이 거의 늘 포지션을 들고 있어 같은 코인-방향에 3명 이상인 시간이 무캡에서 {pct(b0.share_time_cs_ge3)}이다: 3이라는 상한은 드문 쏠림이 아니라 평소 상태를 자른다.")
A("")
A("### 3.2 트레이더별 차단 (제안 3/PROP/8 vs 권고 4/REC/10, 본안 17명)")
A("")
A("\"시도\" = 비어 있을 때의 첫 선택 수 (막히면 다시 시도하므로 무캡 거래 수보다 많다). \"순R 합 변화\"는 5년 합 (대부분 거래 감소로 줄어든 비용). 출처: out/runs_trader.csv.")
A("")
A(table(TH(["3/PROP/8", "4/REC/10"]), trader_rows("T17", ["3/PROP/8", "4/REC/10"])))
A("")
A("### 3.3 교체안 (S2_ST_ROC → N09_ALLIG_AROON, N02_ST_KST → F9_IFVG) 17명")
A("")
A(table(GH, grid_rows("T17S")))
A("")
A(table(TH(["0/REC/0", "4/REC/10", "3/REC/8"]), trader_rows("T17S", ["0/REC/0", "4/REC/10", "3/REC/8"])))
A("")
A("### 3.4 5명 이상이 같은 코인-방향을 원할 때와 최대 노출 (무캡)")
A("")
A("\"신호\" = 그 트레이더 범위의 신호가 있는 경우 (보유 중이어도), \"빈 트레이더 진입\" = 무캡 실행에서 실제 첫 선택 진입. 출처: out/daily_stop.csv, runs_book.csv.")
A("")
A(table(["구성", "거래/일", "신호 5+ 같은 15분봉 (연)", "신호 5+ 같은 1시간 (연)", "빈 트레이더 진입 5+ 같은 15분봉 (연)", "같은 1시간 (연)",
         "5+ 동시 보유 시간 비율", "5+ 보유 구간 (연)", "코인-방향 동시 보유 최대", "같은 방향 최대 R (가중)", "p99", "중앙값", "같은 방향 8+ 시간"], want_rows))
A("")
A("### 3.5 붐빈 진입이 더 나쁜가 (무캡, 진입 순간 같은 코인-방향을 이미 든 다른 트레이더 수별)")
A("")
A(f"출처: out/crowding.csv. 3명 이상 vs 0명의 평균 총R 차이: 본안 {f(crd[('T17','coin_side_open')][0], 4, True)} [{f(crd[('T17','coin_side_open')][1], 4, True)}, {f(crd[('T17','coin_side_open')][2], 4, True)}], "
  f"교체안 {f(crd[('T17S','coin_side_open')][0], 4, True)} [{f(crd[('T17S','coin_side_open')][1], 4, True)}, {f(crd[('T17S','coin_side_open')][2], 4, True)}]; "
  f"같은 방향 8명 이상 vs 4명 이하: 본안 {f(crd[('T17','same_dir_open')][0], 4, True)} [{f(crd[('T17','same_dir_open')][1], 4, True)}, {f(crd[('T17','same_dir_open')][2], 4, True)}] (주 블록 부트스트랩). "
  "붐빈 진입은 총R이 같거나 약간 높고, 순R이 낮은 것은 손절폭이 좁아 R 단위 비용이 커서다.")
A("")
A(table(["구성", "이미 든 다른 트레이더", "진입 수", "평균 순R", "평균 총R", "평균 비용 R"], cr_rows))
A("")
A("### 3.6 민감도 (막힌 시도 비율 / 거래 수 변화)")
A("")
A("U = 전원 15m/30m/1h + 사이징되는 4h. \"절반 건너뜀\" = 각 트레이더가 신호의 50%를 무작위로 보지 않는 경우 (AI가 더 많이 건너뛰는 상황의 근사). 출처: out/runs_book.csv.")
A("")
A(table(["구성"] + SENS, sens_rows))
A("")
A(f"웨이브1 10명만 돌 때 (10/17~10/31) 제안 캡 3/PROP/8은 시도의 {pct(t10P.blocked_share)} (거래 {pct(t10P.dtr, 1, True)}), 북 8만은 {pct(t10_8.blocked_share)}, 권고 4/REC/10은 {pct(t10R.blocked_share)}. "
  "캡이 의미를 갖는 것은 웨이브2가 붙은 뒤다.")
A("")
A("### 3.7 부수 발견: 일일 정지 값 (같은 리스크 매니저)")
A("")
A("출처: out/runs_book.csv. 규칙 프록시의 거래당 순R ≈ -0.11R이라 북은 매일 비용만큼 잃는다. AI가 이보다 훨씬 덜 거래하거나 훨씬 잘하지 않으면 -12R 북 정지는 이틀에 한 번 걸린다.")
A("")
A(table(["구성", "캡", "북 평균 R/일", "북 SD R/일", "-12R 이하 날", "-20R 이하", "-30R 이하", "트레이더-일 -3R 이하", "-4R 이하"], stop_rows))
A("")
A("## 4. 권고")
A("")
A("### 4.1 클러스터 (최종)")
A("")
A("- **ST (Supertrend/HA):** N23_HA_ST (W1), S2_ST_ROC (W2), N02_ST_KST (W2), N01_ST_EMA (예비). N04_ST_KLINGER를 배치하면 여기에 넣는다.")
A("- **RF (Range Filter):** DOGE (W2), F7_RF_TRIPLE (W2).")
A("- 해제: pullback {F16_FIB382, F9_FVG}, DeepSeek 추세 {F7, F4_FAN, F6_VWAP_CROSS}, N10_HA_PSAR의 ST 포함. 진입 단위 근거가 없다 (2.3).")
A("- F16_FIB382/F16_FIB500은 캡 클러스터는 아니지만 판정의 가족(동시 통과 시 하나로 해석)으로 둔다.")
A("- 클러스터 규칙은 위 2.4의 두 조건으로 고정하고, 새 전략을 배치할 때 같은 스크립트(`overlap.py` → `look3.py` → `clus.py`)로 다시 계산한다.")
A("")
A("### 4.2 캡 값")
A("")
A(f"- **판정 기간 (10/17~12/31, 페이퍼):** 코인-방향 **4**, 클러스터 **1** (ST, RF), 같은 방향 **10**. 교체안 17명 규칙 프록시에서 시도의 {pct(sR10.blocked_share)}, 거래 {pct(sR10.dtr, 1, True)}, "
  f"가장 많이 맞는 트레이더 DOGE {pct(TS10.loc['DOGE'].d_trades_pct, 1, True)} (RF 클러스터), N07 {pct(TS10.loc['N07_ICHI_CMO'].d_trades_pct, 1, True)}; 같은 방향 최대 10R (1h 1.5% 가중 {f(sR10.same_dir_max_R_1p5, 1)}R), 코인-방향 최대 4R, "
  f"북 SD {f(sR10.book_sd_day, 1)}R (무캡 {f(s0.book_sd_day, 1)}R). AI가 신호의 절반을 건너뛰면 {pct(s5R10.blocked_share)} / {pct(s5R10.dtr, 1, True)}. 페이퍼에서는 각 트레이더가 별도 계정이라 "
  "코인-방향/북 캡이 막는 실제 돈 위험은 없다: 이 단계의 캡은 리스크 매니저 리허설과 같은 베팅 중복 계산 방지가 목적이므로 드물게 걸리게 둔다.")
A(f"- **제안값 3 / 1 / 8을 판정 기간에 그대로 쓰면:** 본안 17명에서 시도 {pct(bP.blocked_share)}, 거래 {pct(bP.dtr, 1, True)}, DOGE·N02는 4분의 1 넘게 거래가 준다. 막힌 진입이 더 나빴다는 근거도 없다 "
  f"(막힌 진입 총R {f(bP.blocked_meanG, 4, True)} vs 진입 {f(bP.meanG, 4, True)}). 막힌 진입은 반드시 REJECTED_CAP + 그림자 결과로 남겨 짝 비교에 넣는다.")
A("- **실돈 단계:** 그때 살아 있는 트레이더 수 N에 맞춰 코인-방향 3, 클러스터 1, 같은 방향 ≈ 0.5N (최소 2). 통과자가 1~3명이면 캡은 거의 걸리지 않는다.")
A("- 같은 방향 캡을 트레이더 수에 연동: 웨이브1 10명은 무캡 같은 방향 p99가 9라 8도 거의 안 걸린다 (위 3.6); 17명은 p99 13-14라 10이 같은 정도의 꼬리만 자른다.")
A("- **북 일일 정지:** -12R은 규칙 프록시 17명에서 날의 약 절반에 걸린다. -30R 근처 (또는 트레이더 수 × -1.75R)로 다시 정하고, 트레이더별 -3R/일은 트레이더-일 약 10%에 걸린다는 점을 알고 쓴다.")
A("")
A("### 4.3 교체/병합")
A("")
A(f"- **S2_ST_ROC (W2) → N09_ALLIG_AROON (예비):** S2는 N23의 가장 가까운 복제다 (every-signal 일별 R 상관 {f(ns2.r_sig, 2)}로 253쌍 중 1위, κ {f(ns2.k_card_1h, 2)}, 트레이더 상관 {f(ns2.r_tr, 2)}). "
  f"N09는 17명 대비 최대 κ {f(dI.loc['N09_ALLIG_AROON'].max_k_card_1h, 2)}, 최대 결과 상관 {f(dI.loc['N09_ALLIG_AROON'].max_r_sig, 2)}, 최대 트레이더 상관 {f(dI.loc['N09_ALLIG_AROON'].max_r_tr, 2)}; 5년 총R은 15m/30m/1h 모두 양수 (+0.010/+0.012/+0.016, sel_tp/fy_side.json).")
A(f"- **N02_ST_KST (W2) → F9_IFVG (예비):** N02는 N23과 κ {f(nn02.k_card_1h, 2)} (253쌍 중 2위), 결과 상관 {f(nn02.r_sig, 2)}; ST 클러스터 캡만으로 시도의 {pct(TREC.loc['N02_ST_KST'].blocked_share)}가 막히고 거래 {pct(TREC.loc['N02_ST_KST'].d_trades_pct, 1, True)}. "
  f"F9_IFVG는 23개 중 가장 독립적 (최대 κ {f(dI.loc['F9_IFVG'].max_k_card_1h, 2)}, 최대 결과 상관 {f(dI.loc['F9_IFVG'].max_r_sig, 2)}, 최대 트레이더 상관 {f(dI.loc['F9_IFVG'].max_r_tr, 2)}); F9_FVG와 같은 ICT 계열이지만 진입은 거의 안 겹친다 "
  f"(κ {f(pair('F9_FVG','F9_IFVG').k_card_1h, 2)}). 판정에서는 F9 가족으로 함께 해석한다.")
A(f"- **DOGE + F7_RF_TRIPLE (둘 다 W2):** κ {f(ndf.k_card_1h, 2)}, 결과 상관 {f(ndf.r_sig, 2)}로 같은 베팅. DOGE는 운영자 전략이라 둘 다 두고 RF 클러스터 캡으로 묶는다 "
  f"(교체안에서 클러스터 캡만으로 DOGE 시도 {pct(T[(T.set=='T17S')&(T.scope=='CARD')&(T.thin==1.0)&(T.cfg=='0/REC/0')].set_index('trader').loc['DOGE'].blocked_share)}). "
  "하나를 빼야 한다면 F7을 규칙 계정으로 돌린다. 남은 예비 중 F7 자리를 채울 독립 전략은 없다 (F12_MSS는 F7과 κ 0.60, S4와 lift 4.8; N01/N04는 ST; N22는 N07과 κ 0.71).")
A("- 그대로 둔다: N10_HA_PSAR, F16_FIB382/F16_FIB500, F9_FVG, F4_FAN, F6_VWAP_CROSS, N18, S4, N25, V39, N07, N13. F4/N18/V39/F7은 N23·DOGE와 쌍 단위로 느슨하게 겹치지만 (2.4b) 허브 전체를 묶으면 DOGE·F4·V39·N18의 거래가 13-28% 줄고 막힌 진입이 더 나빴다는 근거가 없어 클러스터로 막지 않는다.")
A(f"- 교체 효과: 클러스터 캡만으로 막히는 시도가 {pct(clR.blocked_share)} → {pct(sREC.blocked_share)}, 무캡 분산비 {f(b0.diversification_ratio, 2)} → {f(s0.diversification_ratio, 2)}, 권고 캡 4/REC/10에서 {pct(bR10.blocked_share)} → {pct(sR10.blocked_share)}.")
A("")
A("## 5. 이 데이터가 말하지 못하는 것")
A("")
A("- 규칙 프록시다. AI는 더 건너뛰고, 일찍 청산하고, 근처 진입을 한다. 점유율(늘 포지션 보유)이 낮아지면 차단율이 내려간다 (절반 건너뜀 민감도 참고). 실제 차단율은 웨이브0/1 로그로 다시 잰다.")
A("- 결과 R은 every-signal 단독 하우스 청산 (30x/20x 노멀 체인의 ROE 래더, 15분봉 손절 확인)이다. 1% 위험 사이징 + R 단위 청산이면 래더 잠금 위치가 달라 R이 조금 다르다. 15m/30m/1h는 사이징 불가 신호도 포함 (코드가 낮은 레버리지를 고른다고 가정).")
A("- 겹침은 정의의 성질이라 안정적이지만 (반기 κ 상관 0.996), 엣지에 대해서는 아무 말도 하지 않는다. 캡의 총R 효과 구간은 전략 간 의존 때문에 다소 낙관적일 수 있다.")
A("- 같은 순간 트레이더 간 순서는 사전 등록 규칙(긴 tf → 넓은 손절 → 날짜 회전)으로 흉내 냈다. 실제로는 AI 응답 순서가 정하므로 누가 막히는지는 달라질 수 있다 (총 차단율은 비슷).")
A("- 북 R은 따로 있는 페이퍼 계정들의 합이다. 실돈에서 한 계정으로 합치면 같은 방향 노출이 그대로 손익 변동이 된다.")
A("- 6코인만 봤다. 코인이 늘면 코인-방향 캡은 덜 걸린다.")
A("")
A("## 6. 파일")
A("")
A("- 스크립트: `ovl5/build_sig.py`, `common5.py`, `overlap.py`, `overlap_half.py`, `look1.py`, `look3.py`, `clus.py`, `coholding.py`, `distinct.py`, `capsim.py`, `runcaps.py`, `runcaps_extra.py`, `verify.py`, `build_report.py`")
A("- 표: `ovl5/out/pair_shares.csv` (506 방향쌍 × 모든 창/우연), `pairs_all.csv` (253쌍 요약), `kappa_halves.csv`, `daily_R_corr.csv`, `daily_gross_corr.csv`, `daily_count_corr.csv`, "
  "`trader_daily_R_corr_CARD.csv`, `trader_daily_gross_corr_CARD.csv`, `entry_coheld_CARD.csv`, `entry_coheld_chance_CARD.csv`, `time_coheld_CARD.csv`, `wants_CARD.json` (23명), `distinct_vs_T17.csv`, "
  f"`runs_book.csv` ({len(B)}개 실행), `runs_trader.csv`, `runs_book_hub.csv`, `runs_trader_hub.csv`, `crowding.csv`, `daily_stop.csv`, `rates.csv`, `verify.log`")
A("- 입력 캐시 `ovl5/sig23.npz`는 작업 끝에 지웠다 (`build_sig.py`로 6초에 재생성).")
open(os.path.join(D, "overlap_caps_KO.md"), "w").write("\n".join(md) + "\n")

# ---------------------------------------------------------------- json


def rec(df):
    return json.loads(df.to_json(orient="records", double_precision=5))


def mat(path):
    m = pd.read_csv(os.path.join(O, path), index_col=0)
    return {"names": list(m.index), "values": np.round(m.values, 3).tolist()}


kappa = pd.DataFrame(np.eye(len(C.ALL)), index=C.ALL, columns=C.ALL)
same15 = pd.DataFrame(np.nan, index=C.ALL, columns=C.ALL)
for _, r in P.iterrows():
    kappa.loc[r.A, r.B] = kappa.loc[r.B, r.A] = r.k_card_1h
for _, r in PS.iterrows():
    same15.loc[r.A, r.B] = r["15m_bar"]

J = {
    "title": "5-year entry-level overlap map and exposure-cap blocking for the AI traders",
    "created": "2026-10-08 KST",
    "headline": [
        f"Entry-level overlap is small: median same coin/side/15m-bar share {same15_med:.3f} over 253 pairs (max {same15_max:.3f}, N10_HA_PSAR/N23_HA_ST). The live 4h-window co-occurrence (87-98%) is mostly density: 4h-window share median {card4h_obs:.3f} vs {card4h_ch:.3f} with B shifted 7 days.",
        "Only two same-bet clusters pass the rule (kappa_1h >= 0.5 average linkage AND every pair's every-signal daily R corr >= 0.5): ST = {N23_HA_ST, S2_ST_ROC, N02_ST_KST, N01_ST_EMA}; RF = {DOGE, F7_RF_TRIPLE}. The proposed pullback (F16/F9) and DeepSeek-trend (F4/F6/F7) clusters and N10-in-ST are not supported.",
        f"One-position traders are weakly correlated: trader daily net R corr median {rtr_med:.2f}, max {rtr_max:.2f}; every-signal daily R corr median {rsig_med:.2f}, max {rsig_max:.2f}.",
        f"Proposed caps 3/1/8 on the 17 staffed traders (rule proxy): {bP.blocked_share:.3f} of intended entries blocked, trades {bP.dtr:+.3f}; DOGE {TP.loc['DOGE'].d_trades_pct:+.3f}, N02 {TP.loc['N02_ST_KST'].d_trades_pct:+.3f}. The book-direction cap 8 does most of it: uncapped median same-direction count is already {b0.same_dir_p50:.0f}.",
        f"Caps cut tail exposure but not edge: blocked entries' gross R {bP.blocked_meanG:+.4f} vs taken {bP.meanG:+.4f}; book gross R change {bP.dG_book:+.0f}R [{bP.dG_book_ci_lo:+.0f}, {bP.dG_book_ci_hi:+.0f}] over 5 years.",
        f"Uncapped 17: peak same-direction 17R (20.5R with 1.5% at 1h), p99 {b0.same_dir_p99:.0f}R; 5+ free traders entering the same coin-side in the same 15m bar {d17.want_free15_ge5_per_year:.0f}/yr, same hour {d17.want_free1h_ge5_per_year:.0f}/yr; 5+ holding the same coin-side {d17.hold_cs_ge5_share_time:.3f} of the time.",
        f"Recommendation: swap S2_ST_ROC -> N09_ALLIG_AROON and N02_ST_KST -> F9_IFVG; keep DOGE+F7 under the RF cluster cap; paper-phase caps coin-side 4 / cluster 1 / same-direction 10 ({sR10.blocked_share:.3f} blocked, trades {sR10.dtr:+.3f} on the swapped 17); 3/1/8 scaled to the live count for real money.",
        f"Side finding: the -12R book daily stop fires on {b0.share_book_days_le_m12R:.3f} of days for 17 rule-proxy traders (book mean {b0.book_mean_day:+.1f}R/day); recalibrate near -30R.",
    ],
    "method": {
        "signals": "lens2/multi_tf/outc every-signal ALONE outcomes (house exit, 15m-bar stop checks), 2021-08-01..2026-09-30, 6 coins; extracted by ovl5/build_sig.py (2,202,218 rows)",
        "scope_CARD": {k: [C.TF_NAMES[t] for t in v] for k, v in C.CARD.items()},
        "scope_note": "4h only for N23_HA_ST and F6_VWAP_CROSS and only signals sizable at 30x/20x; U scope = 15m/30m/1h + sizable 4h for all",
        "share": "A->B = share of A's (coin, side, entry bar) with a same coin-side B entry within the window; windows: same bar, +-1 bar of that tf, +-4h; card scope: same 15m moment, +-1h, +-4h",
        "chance": "B shifted by +-7 days (672 15m bars), averaged",
        "kappa": "(obs - chance)/(1 - chance), max over the two directions",
        "daily_R_corr": "Pearson corr of daily sums of every-signal net R (and gross R) on the card scope",
        "trader": "setup B one-position trader: longer tf, widest stop, coin order; no switching; occupies e..x; 1% risk",
        "caps": "checked at entry vs all open positions; blocked first choice -> next signal at same e, else stays flat; same-moment order: longer tf, widest stop, daily rotation of trader ids",
        "uncertainty": "week-block bootstrap (2,000) for book R changes; kappa IS/CF corr " + f"{kh_corr:.3f}",
        "verification": open(os.path.join(O, "verify.log")).read().strip().splitlines(),
    },
    "step1_overlap": {
        "summary": dict(pairs=n_pairs, same15m_bar_median=same15_med, same15m_bar_p90=same15_p90, same15m_bar_max=same15_max,
                        kappa_1h_median=k1h_med, kappa_1h_p90=k1h_p90, r_sig_median=rsig_med, r_sig_max=rsig_max,
                        r_trader_median=rtr_med, r_trader_max=rtr_max, card_4h_obs_median=card4h_obs,
                        card_4h_chance_median=card4h_ch, kappa_IS_CF_corr=kh_corr),
        "pairs": rec(P.round(4)),
        "kappa_1h_matrix": {"names": C.ALL, "values": np.round(kappa.values, 3).tolist()},
        "same_15m_bar_share_matrix_row_in_col": {"names": C.ALL, "values": np.round(same15.values.astype(float), 3).tolist()},
        "every_signal_daily_R_corr": mat("daily_R_corr.csv"),
        "trader_daily_R_corr": mat("trader_daily_R_corr_CARD.csv"),
        "proposed_cluster_check": [dict(cluster=r[0], A=r[1], B=r[2], same15m_bar=float(r[3]), kappa_same15=float(r[4]),
                                        kappa_1h=float(r[5]), r_sig=float(r[6]), r_trader=float(r[7]), verdict=r[8]) for r in prop_rows],
        "distinctness_vs_T17": rec(DIST),
    },
    "clusters": {
        "rule": "average-linkage on kappa_1h (card scope, chance-corrected same coin-side entry within 1h, max over directions), cut 0.5; a cluster is kept only if every pair inside has every-signal daily net R corr >= 0.5",
        "final": REC,
        "dropped_from_proposals": {"PULLBACK": ["F16_FIB382", "F16_FIB500", "F9_FVG", "F9_IFVG"],
                                   "DS_TREND": ["F7_RF_TRIPLE", "F4_FAN", "F6_VWAP_CROSS"], "ST_HA": ["N10_HA_PSAR", "N04_ST_KLINGER (outcome cousin: add if staffed)", "DOGE (moved to RF)"]},
        "watch_pairs": [dict(A=a, B=b) for a, b in WATCH],
        "pairs_passing_both_conditions": {"all_253": rec(PP[["A", "B", "k_card_1h", "r_sig", "r_tr", "coheld_lift"]].round(4)),
                                          "within_T17": len(PP17), "within_T17S": len(PP17S)},
        "hub_cluster_sensitivity_T17S": {"hub": ["N23_HA_ST", "F4_FAN", "F7_RF_TRIPLE", "N18_VWMA_MACD", "DOGE", "V39_ALL"],
                                         "runs": rec(HUBB.round(5)), "per_trader": rec(HUBT[HUBT.cluster == "HUB"].round(4))},
        "verdict_family_not_cap": [["F16_FIB382", "F16_FIB500"], ["F9_FVG", "F9_IFVG"]],
    },
    "step2_caps": {
        "sets": {"T17": C.WAVE1 + C.WAVE2, "T10": C.WAVE1, "T23": C.ALL,
                 "T17S": C.WAVE1 + ["F16_FIB500", "F7_RF_TRIPLE", "N09_ALLIG_AROON", "F9_IFVG", "N07_ICHI_CMO", "DOGE", "N13_3OUTSIDE"]},
        "cluster_sets": {"PROP": C.CLUSTERS_PROPOSED, "REC": REC,
                         "D60": {"ST": ["N01_ST_EMA", "N23_HA_ST", "S2_ST_ROC"], "RF": ["DOGE", "F7_RF_TRIPLE"], "ICHV": ["N07_ICHI_CMO", "N22_VORTEX_PSAR"]},
                         "D50": "REC + ICHV {N07,N22} + BB {F12_MSS,S4_BB_BBP} + VW {F6_VWAP_CROSS,N09_ALLIG_AROON}"},
        "runs_book": rec(B.drop(columns=["maxDD_R"]).round(5)),
        "per_trader_key_configs": rec(T[T.cfg.isin(["3/PROP/8", "3/REC/8", "4/REC/10", "0/REC/0", "0/PROP/0", "3/off/0", "0/off/8"])
                                        & (T.scope == "CARD")].round(4)),
        "crowding": rec(CR.round(5)),
        "wants_and_daily_stops": rec(DS.round(4)),
    },
    "recommendations": {
        "clusters": REC,
        "caps_paper_phase": {"coin_side": 4, "cluster": 1, "same_direction_book": 10,
                             "effect_T17S": dict(blocked_share=float(sR10.blocked_share), trades_change=float(sR10.dtr),
                                                 peak_same_dir_R=int(sR10.same_dir_max), peak_weighted_R=float(sR10.same_dir_max_R_1p5),
                                                 book_sd_day=float(sR10.book_sd_day)),
                             "effect_T17_unswapped": dict(blocked_share=float(bR10.blocked_share), trades_change=float(bR10.dtr))},
        "caps_real_money": "coin-side 3, cluster 1, same-direction about 0.5 x live traders (min 2)",
        "proposed_3_1_8_on_T17": dict(blocked_share=float(bP.blocked_share), trades_change=float(bP.dtr),
                                      dG_book=float(bP.dG_book), dG_ci=[float(bP.dG_book_ci_lo), float(bP.dG_book_ci_hi)]),
        "swaps": [{"out": "S2_ST_ROC", "in": "N09_ALLIG_AROON", "why": "S2 = closest duplicate of N23 (every-signal daily R corr 0.82, kappa 0.75)"},
                  {"out": "N02_ST_KST", "in": "F9_IFVG", "why": "N02 kappa 0.83 with N23; F9_IFVG most distinct of all 23"}],
        "merge": {"RF": ["DOGE", "F7_RF_TRIPLE"], "note": "keep both under one cluster cap; if one must go, F7 becomes a rule account"},
        "book_daily_stop": "-12R fires on about half of days for 17 rule-proxy traders; recalibrate near -30R (or traders x -1.75R)",
        "logging": "every cap-blocked entry as REJECTED_CAP with its shadow outcome, included in the paired AI-minus-rule verdict",
    },
    "limits": [
        "rule proxies: an AI that skips more holds less and is blocked less (thin 0.5 sensitivity)",
        "outcomes = every-signal alone house exits (ROE ladder at 30x/20x normal chain), not R exits under 1% risk sizing",
        "15m/30m/1h infeasible signals included (code would pick lower leverage); 4h only where sizable",
        "overlap is a property of the definitions (stable across halves) and says nothing about edge",
        "same-moment order between traders emulated by a pre-registered rule; live order is AI response time",
        "book R sums separate paper accounts",
    ],
    "files": {"folder": D, "report": os.path.join(D, "overlap_caps_KO.md"),
              "scripts": [os.path.join(D, x) for x in ("build_sig.py", "common5.py", "overlap.py", "overlap_half.py", "look1.py", "look3.py", "clus.py",
                                                        "coholding.py", "distinct.py", "capsim.py", "runcaps.py", "runcaps_extra.py", "verify.py", "build_report.py")],
              "tables": sorted(os.path.join(O, x) for x in os.listdir(O))},
}
json.dump(J, open(os.path.join(D, "overlap_caps.json"), "w"), indent=1, ensure_ascii=False, default=float)
print("ok", len("\n".join(md)), os.path.getsize(os.path.join(D, "overlap_caps.json")))
