"""Markdown tables for REPORT_KO.md, printed from the CSVs of this folder (so the report numbers are not typed by hand).
    python3 report_tables.py > /tmp/... (read and paste)"""
import os
import pandas as pd
import numpy as np

H = os.path.dirname(os.path.abspath(__file__))
P = lambda x: "" if pd.isna(x) else f"{x * 100:+.2f}"
PP = lambda x: "" if pd.isna(x) else f"{x * 100:.0f}%"


def t1():
    E = pd.read_csv(os.path.join(H, "general_effect.csv"))
    L = pd.read_csv(os.path.join(H, "luck_table.csv"))
    print("| 추세 소스 | 진입 → 추세 봉 | 매매법 수 | 중앙 효과 고르기 | 확인 | 2026 | 19일 | 좋아진 매매법 비율 고르기 / 확인 | 거래당(추세 쪽) 확인 | 거래당(거르기 전) 확인 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k, s, ko in (("j", "DIR", "추세판단 봇 판단(3/4, 유지)"), ("j", "V4OF4", "판단 4개 모두 같은 쪽"),
                     ("c", "OBV_S", "OBV vs 30봉 평균")):
        for etf, htf in (("15m", "1h"), ("30m", "1h"), ("1h", "4h"), ("4h", "1d")):
            r = E[(E.kind == k) & (E.source == s) & (E.etf == etf) & (E.htf == htf)].iloc[0]
            l = L[(L.source == f"{k}:{s}") & (L.etf == etf) & (L.htf == htf) & (L.per == "CONF")].iloc[0]
            print(f"| {ko} | {etf} → {htf} | {int(r.cells_SEL)} | {P(r.med_effW_SEL)} | {P(r.med_effW_CONF)} | "
                  f"{P(r.med_effW_LATE)} | {P(r.med_effW_FWD)} | {PP(r.share_up_SEL)} / {PP(r.share_up_CONF)} | "
                  f"{P(l.mW)}% | {P(l.mALL)}% |")


def t_year():
    Y = pd.read_csv(os.path.join(H, "effect_by_year.csv"))
    blocks = ["Y21", "Y22", "Y23", "Y24", "Y25", "Y26a", "F1", "F2"]
    ko = {"Y21": "2021", "Y22": "2022", "Y23": "2023", "Y24": "2024", "Y25": "2025", "Y26a": "2026.1~9",
          "F1": "10/06~10/22", "F2": "10/23~10/24"}
    print("| 추세 소스 | 진입 → 추세 봉 | " + " | ".join(ko[b] for b in blocks) + " |")
    print("|---|---|" + "---|" * len(blocks))
    for src in ("j:V4OF4", "j:DIR"):
        for mp in ("15m->1h", "30m->1h", "1h->4h", "4h->1d"):
            q = Y[(Y.source == src) & (Y["map"] == mp)].set_index("block")
            print(f"| {src} | {mp.replace('->', ' → ')} | " + " | ".join(P(q.eff.get(b, np.nan)) for b in blocks) + " |")


def t_role():
    R = pd.read_csv(os.path.join(H, "role_effect.csv"))
    R["mp"] = R.etf + "->" + R.htf
    ko = {"range": "횡보 자리", "pullback": "눌림", "breakout": "돌파", "reversal": "반전", "timing": "타이밍(오실레이터)",
          "other": "기타", "trend": "추세형(비교용)"}
    for src in ("j:DIR", "j:V4OF4"):
        print(f"\n{src}: 중앙 효과(추세 쪽 − 거르기 전), ROE %p, 고르기 / 확인 / 19일")
        print("| 종류 | 15m → 1h | 30m → 1h | 1h → 4h | 4h → 1d |")
        print("|---|---|---|---|---|")
        for role in ("range", "pullback", "breakout", "reversal", "timing", "trend"):
            cells = []
            for mp in ("15m->1h", "30m->1h", "1h->4h", "4h->1d"):
                v = {per: R[(R.source == src) & (R.mp == mp) & (R.role == role) & (R.per == per)].med_effW
                     for per in ("SEL", "CONF", "FWD")}
                g = lambda per: P(v[per].iloc[0]) if len(v[per]) else ""
                cells.append(f"{g('SEL')} / {g('CONF')} / {g('FWD')}")
            print(f"| {ko[role]} | " + " | ".join(cells) + " |")
    print("\n보류(neutral) − 거르기 전, j:DIR, 고르기 / 확인")
    print("| 종류 | 15m → 1h | 30m → 1h | 1h → 4h | 4h → 1d |")
    print("|---|---|---|---|---|")
    for role in ("range", "pullback", "breakout", "reversal", "timing"):
        cells = []
        for mp in ("15m->1h", "30m->1h", "1h->4h", "4h->1d"):
            v = {per: R[(R.source == "j:DIR") & (R.mp == mp) & (R.role == role) & (R.per == per)].med_effN
                 for per in ("SEL", "CONF")}
            cells.append(f"{P(v['SEL'].iloc[0])} / {P(v['CONF'].iloc[0])}")
        print(f"| {ko[role]} | " + " | ".join(cells) + " |")


def t_src():
    E = pd.read_csv(os.path.join(H, "general_effect.csv"))
    E["mp"] = E.etf + " → " + E.htf
    print("| 진입 → 추세 봉 | 소스 수 | 두 기간 모두 도움 | 중앙 효과 고르기 | 확인 | 19일 | 고르기·확인 순위 상관 |")
    print("|---|---|---|---|---|---|---|")
    for mp, z in E.groupby("mp", sort=False):
        pass
    order = ["15m → 1h", "15m → 4h", "15m → 1d", "30m → 1h", "30m → 4h", "30m → 1d", "1h → 4h", "1h → 1d", "4h → 1d"]
    for mp in order:
        z = E[E.mp == mp]
        both = int(((z.med_effW_SEL > 0) & (z.med_effW_CONF > 0)).sum())
        rho = z[["med_effW_SEL", "med_effW_CONF"]].corr("spearman").iloc[0, 1]
        print(f"| {mp} | {len(z)} | {both} | {P(z.med_effW_SEL.median())} | {P(z.med_effW_CONF.median())} | "
              f"{P(z.med_effW_FWD.median())} | {rho:.2f} |")
    E["minmed"] = E[["med_effW_SEL", "med_effW_CONF"]].min(axis=1)
    q = E[(E.med_effW_SEL > 0) & (E.med_effW_CONF > 0)].sort_values("minmed", ascending=False).head(15)
    print("\n| 소스 | 진입 → 추세 봉 | 남는 신호 | 중앙 효과 고르기 | 확인 | 2026 | 19일 | 좋아진 비율 확인 | 묶음 t 고르기 / 확인 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for _, r in q.iterrows():
        print(f"| {r.kind}:{r.source} | {r.mp} | {PP(r.keep_SEL)} | {P(r.med_effW_SEL)} | {P(r.med_effW_CONF)} | "
              f"{P(r.med_effW_LATE)} | {P(r.med_effW_FWD)} | {PP(r.share_up_CONF)} | {r.SEL_pool_t:.1f} / {r.CONF_pool_t:.1f} |")


def t_luck():
    L = pd.read_csv(os.path.join(H, "luck_table.csv"))
    print("| 소스 | 진입 → 추세 봉 | 기간 | 거르기 전 | 추세 쪽 | 그 진입의 반대 쪽(동전) | 추세만(모든 봉) | 롱 비율 | 같은 롱 비율 동전 | 진입이 더한 것 | 추세가 더한 것 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for src in ("j:V4OF4", "j:DIR"):
        for etf, htf in (("15m", "1h"), ("30m", "1h"), ("1h", "4h")):
            for per, pk in (("SEL", "고르기"), ("CONF", "확인"), ("FWD", "19일")):
                r = L[(L.source == src) & (L.etf == etf) & (L.htf == htf) & (L.per == per)].iloc[0]
                print(f"| {src} | {etf} → {htf} | {pk} | {P(r.mALL)} | {P(r.mW)} | {P(r.mWo)} | {P(r.mT)} | "
                      f"{PP(r.lsW)} | {P(r.mDrift)} | {P(r.timing_gain)} | {P(r.dir_gain)} |")


def t_bots():
    G = pd.concat([pd.read_csv(os.path.join(H, f)) for f in ("goalpath.csv", "goalpath_G.csv", "goalpath_H.csv",
                                                              "goalpath_X_S4.csv")], ignore_index=True)
    B = pd.concat([pd.read_csv(os.path.join(H, f)) for f in ("goal_boot.csv", "goal_boot_G.csv", "goal_boot_H.csv",
                                                              "goal_boot_X_S4.csv")], ignore_index=True)
    G = G[G.blk0 == False]                                                    # noqa: E712
    names = ["A_sel_portfolio", "B_sel_with20", "G_flip_portfolio", "H_friendmap_dir_sel", "F_role_top3",
             "C_friend_15m", "C_friend_30m", "C_friend_1h", "D_trendbot18", "E_timing_v4of4",
             "X_S4_BB_BBP@1h|j:DIR@4h", "X_F12_MSS_DISP@4h|l:T4_MACDHIST0@1d", "X_T5_ST14_4@4h|l:T12_HMA21@1d"]
    print("| 봇 | 고르기 거래당 | 확인 거래당 (페이백 포함) | 확인 하루 거래 | 확인 동전 | 확인 승률 | 2026 거래당 | 19일 거래당 (거래 수) | 19일 동전 | 확인 최대 낙폭(증거금 40%) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for b in names:
        z = G[G.bot == b].set_index("period")
        if "CONF" not in z.index:
            continue
        s, c, l = z.loc["SEL"], z.loc["CONF"], z.loc["LATE"]
        f = z.loc["FWD"] if "FWD" in z.index else None
        fw = f"{P(f.mean_roe)}% ({int(f.trades)})" if f is not None else "-"
        fo = f"{P(f.opp_mean_roe)}%" if f is not None else "-"
        print(f"| {b} | {P(s.mean_roe)}% | {P(c.mean_roe)}% ({P(c.mean_roe_pb)}%) | {c.per_day:.2f} | {P(c.opp_mean_roe)}% | "
              f"{PP(c.win)} | {P(l.mean_roe)}% | {fw} | {fo} | {PP(c['max_dd_m0.4'])} |")
    print("\n30일 부트스트랩 (확인 기간 거래, 하루 단위 뽑기 4,000번)")
    print("| 봇 | 증거금 | 페이백 | 30일 ×6 확률 | −50% 먼저 | −90% 먼저 | 30일 뒤 가운데 배수 |")
    print("|---|---|---|---|---|---|---|")
    for b in ["B_sel_with20", "G_flip_portfolio", "H_friendmap_dir_sel", "C_friend_30m", "D_trendbot18", "E_timing_v4of4",
              "X_F12_MSS_DISP@4h|l:T4_MACDHIST0@1d"]:
        for m in (0.1, 0.4):
            for pb in (False, True):
                r = B[(B.bot == b) & (B.period == "CONF") & (B.blk0 == False) & (B.margin == m) & (B.payback == pb)]  # noqa
                if not len(r):
                    continue
                r = r.iloc[0]
                print(f"| {b} | {int(m * 100)}% (노출 {35 * m:.1f}배) | {'포함' if pb else '없음'} | {r.p_target * 100:.1f}% | "
                      f"{r.p_lose50_first * 100:.0f}% | {r.p_lose90_first * 100:.0f}% | ×{r.median_final_x:.2f} |")
    D = pd.read_csv(os.path.join(H, "goal_gap_delta.csv"))
    print("\n| 봇 | 확인 하루 거래 | 확인 거래당 | 30일 ×6(가운데)에 필요한 거래당 더하기 | 그때 거래당 | 증거금 | 페이백 포함 시 필요한 더하기 |")
    print("|---|---|---|---|---|---|---|")
    for _, r in D.iterrows():
        print(f"| {r.bot} | {r.per_day:.2f} | {r.mean_roe * 100:+.2f}% | +{r.need_shift_roe_pts:.2f}%p | {r.need_mean_roe:+.2f}% | "
              f"{r.margin_at_need * 100:.0f}% | +{r.need_shift_with_payback_pts:.2f}%p |")


def t_friend():
    F = pd.read_csv(os.path.join(H, "friend_example.csv"))
    F = F[F.source == "c:OBV_S"]
    print("| 진입(스토캐스틱 RSI) | OBV 추세 봉 | 기간 | 추세 쪽 거래당 (신호 수) | 그 진입의 반대 쪽 | 추세 반대 신호 | 거르기 전 |")
    print("|---|---|---|---|---|---|---|")
    for _, r in F.iterrows():
        if r.per not in ("SEL", "CONF", "FWD"):
            continue
        pk = {"SEL": "고르기", "CONF": "확인", "FWD": "19일"}[r.per]
        print(f"| {r.entry.split('@')[1]} | {r.htf} | {pk} | {P(r.mW)}% ({int(r.nW)}) | {P(r.mWo)}% | {P(r.mA)}% | {P(r.mALL)}% |")


def t_exits():
    X = pd.read_csv(os.path.join(H, "exits_table.csv"))
    print("| 진입 → 추세 봉 | 거르기 | 기간 | w35 (주인님 청산 35배) | w30 (30배) | s20 (35배 −20% 손절) | a2 (2 ATR + 계단, 30배) | 비용 전 가격 기대(w35) |")
    print("|---|---|---|---|---|---|---|---|")
    for _, r in X.iterrows():
        if r["map"] not in ("15m->1h", "30m->1h") or r.per not in ("SEL", "CONF", "FWD"):
            continue
        if "DIR" in r["filter"]:
            continue
        pk = {"SEL": "고르기", "CONF": "확인", "FWD": "19일"}[r.per]
        print(f"| {r['map'].replace('->', ' → ')} | {r['filter']} | {pk} | {P(r.w35_roe)}% | {P(r.w30_roe)}% | {P(r.s20_roe)}% | "
              f"{P(r.a2_roe)}% | {r.w35_gross_price_pct:+.3f}% |")


if __name__ == "__main__":
    for f in (t1, t_year, t_role, t_src, t_luck, t_bots, t_friend, t_exits):
        print(f"\n===== {f.__name__}")
        f()
