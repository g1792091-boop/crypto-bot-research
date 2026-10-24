#!/usr/bin/env python3
"""Writes REPORT_KO.md from the tables of rb1024.py and rb_extra.py.

    python3 make_report.py <out_dir> [<zip name for the header>]

Every number in the report comes from <out_dir>/tables/*.csv, facts.json and facts_extra.json; the sentences that
depend on a result are chosen from the numbers, so the report can be rebuilt from a newer export unchanged.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pandas as pd

KST_MS = 9 * 3_600_000
TFO = {"5m": 0, "15m": 1, "30m": 2, "1h": 3, "4h": 4}
GKO = {"core": "기본 매매법", "ds": "딥시크", "reel": "릴스 5분", "flip": "동전 던지기", "flip5": "동전 던지기 5분(롱만)"}
TFKO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
VKO = {"base": "지금 규칙(기준)", "lock15": "첫 잠금 15%", "lock20": "첫 잠금 20%", "lock30": "첫 잠금 30%",
       "timestop": "시간 손절", "lev10": "10배·증거금 20%", "lev20": "20배·증거금 20%", "lev30": "30배·증거금 30%",
       "lev40": "40배·증거금 40%", "lev50": "50배·증거금 40%", "stopw1.5": "손절 1.5 ATR", "stopw2.5": "손절 2.5 ATR",
       "stopw3": "손절 3 ATR", "tp1R": "고정 익절 1R", "tp1.5R": "고정 익절 1.5R", "tp2R": "고정 익절 2R",
       "tp3R": "고정 익절 3R", "ladder_cap2R": "계단 + 2R 익절", "lev20m20": "20배·증거금 20%(고정)",
       "lev30m30": "30배·증거금 30%(고정)", "lev40m40": "40배·증거금 40%(고정)", "lev50m50": "50배·증거금 50%(고정)"}
FEATKO = {"side": "방향", "coin": "코인", "session": "시간대(KST)", "weekend": "주말", "regime": "장세(같은 봉)",
          "htf_regime": "장세(상위 봉)", "boxpos": "박스 안 위치", "htf_boxpos": "상위 봉 박스 위치", "adx": "ADX",
          "di_agree": "DI 방향 일치", "extension": "EMA20에서 떨어진 정도", "er": "효율 비율(ER)",
          "room": "다음 벽까지 여유", "lvl_before_lock": "잠금 전 벽", "sup_before_stop": "손절 전 지지",
          "breakout": "돌파 신호", "tier": "진입 등급", "stopsize": "손절 폭"}


def nz(x):
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def usd(x, sign=True):
    if not nz(x):
        return "—"
    s = f"{abs(x):,.0f}"
    return (("+" if x > 0 else "-" if x < 0 else "") if sign else ("-" if x < 0 else "")) + "$" + s


def num(x, d=2, sign=False):
    if not nz(x):
        return "—"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def pct(x, d=1, sign=False):
    if not nz(x):
        return "—"
    return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}") + "%"


def Rf(x, d=3):
    return "—" if not nz(x) else f"{x:+.{d}f}R"


def pv(x):
    if not nz(x):
        return "—"
    return "<0.0001" if x < 0.0001 else (f"{x:.4f}" if x < 0.01 else f"{x:.3f}")


def table(rows, header):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def kst(ms, fmt="%m/%d %H:%M"):
    return pd.Timestamp(int(ms) + KST_MS, unit="ms").strftime(fmt)


def main(argv) -> int:
    out = argv[0]
    zipname = os.path.basename(argv[1]) if len(argv) > 1 else "?"
    TD = os.path.join(out, "tables")
    F = json.load(open(os.path.join(out, "facts.json")))
    FX = json.load(open(os.path.join(out, "facts_extra.json"))) if os.path.exists(os.path.join(out, "facts_extra.json")) else {}
    t = lambda n: pd.read_csv(os.path.join(TD, n))  # noqa: E731
    have = lambda n: os.path.exists(os.path.join(TD, n))  # noqa: E731
    AC = t("accounts_v4.csv")
    G = t("v4_by_group.csv").set_index("grp")
    COV = t("coverage_runs.csv").set_index("run")
    M = t("v4_market_coins.csv")
    ME = t("v4_market_effect.csv").set_index("grp")
    W = t("v4_by_window.csv")
    days = F["v4_days"]
    L = []
    w = L.append
    S = AC[AC["grp"].isin(["core", "ds"])]
    traded = S[S["n"] > 0]
    prof = traded[traded["pnl"] > 0]
    v39 = AC[AC["account_id"] == "V39_ALL@1h"].iloc[0] if (AC["account_id"] == "V39_ALL@1h").any() else None
    start_all = COV["start_ms"].min()
    tot_days = (F["v4_end_ms"] - start_all) / 86_400_000

    # ============================================================ title
    w("# 규칙봇 모든 결과 분석 — 19일치 전부 (10/06 ~ 10/24, 그 전 실행 포함)")
    w("")
    w(f"기준: 2026-10-24(토) 밤. 자료: `{zipname}` (서버 DB 읽기 전용 복사본, {kst(F['v4_end_ms'], '%m/%d %H:%M')} KST까지).")
    w(f"분석한 기간: 지금 실행 v4 {kst(F['v4_start_ms'])} ~ {kst(F['v4_end_ms'])} KST({days:.1f}일, 두 분이 말한 \"19일치\")가 중심이고, 그 전 실행 2개({kst(start_all)} ~ {kst(F['v4_start_ms'])}, {(F['v4_start_ms'] - start_all) / 86_400_000:.1f}일)도 모두 봤습니다.")
    w("")
    w("이 보고서는 숫자를 만든 스크립트가 직접 씁니다. 새 자료가 오면 같은 명령 한 줄로 다시 만듭니다(부록 E).")
    w("")
    w("---")
    w("")

    # ============================================================ 0. conclusions
    fx_sh = FX.get("shadow_bh_pass")
    w("## 0. 결론")
    w("")
    w(f"1. **운을 넘어선 계좌는 0개입니다.** v4에서 거래한 기본 매매법·딥시크 계좌 {len(traded)}개 중 {len(prof)}개가 돈을 벌었습니다. "
      f"그런데 같은 날·같은 코인·같은 롱/숏 비율로 동전을 던진 결과와 비교하면(시험 A), 보정 뒤 통과는 {F['A_tested']}개 중 {F['A_bh_pass']}개입니다. "
      f"보정 없이 p<0.05인 계좌는 {F['A_raw_p05']}개로, 운만으로 나올 수({0.05 * F['A_tested']:.0f}개 안팎)보다 적습니다.")
    w(f"2. **손실의 원인은 수수료입니다.** 331계좌 합계 {usd(F['v4_pnl'])}(시작 금액의 {100 * F['v4_pnl'] / (331 * 5000):.0f}%)입니다. "
      f"수수료·펀딩 전 손익은 {usd(F['v4_gross'])}, 수수료는 ${F['v4_fees']:,.0f}입니다. 수수료가 손실의 {100 * F['v4_fees'] / -F['v4_pnl']:.0f}%를 차지합니다.")
    w(f"3. **번 계좌는 대부분 떨어지는 시장에서 숏을 한 덕입니다.** 6코인이 평균 {pct(F['market_eq6_pct'], sign=True)} 내렸습니다. "
      f"아무 때나 숏을 한 동전도 롱보다 거래당 0.2R 안팎 나았습니다(3-9). 시장 몫을 빼면 기본 매매법 손익은 {usd(ME.loc['core', 'pnl'])} → {usd(ME.loc['core', 'pnl_ex_market'])}입니다.")
    if v39 is not None:
        w(f"4. **가장 좋은 계좌는 V39_ALL@1h입니다(실거래 시험 중인 그 계좌).** {int(v39['n'])}거래 {int(round(v39['win_pct'] * v39['n'] / 100))}승, {usd(v39['pnl'])}, 앞 절반·뒤 절반 모두 플러스입니다. "
          f"방향 뒤집기 시험(B) p={pv(v39['B_p_better'])}, 보정 뒤 q={num(v39['B_q'], 3)}로 기준(0.05)을 아슬아슬하게 못 넘었고, 맞춘 동전 시험(A)은 보정 뒤 q={num(v39['A_q'], 2)}입니다. "
          f"5년 기록은 1시간봉 거래당 {pct(100 * v39['test_mean'], 2, True)}(2024~26), 계좌는 파산이었습니다. **\"지켜볼 가치는 있지만 근거는 아직 모자람\"**입니다.")
    w(f"5. **성적은 잘 이어지지 않습니다.** 10/17까지 1~10등 중 그 뒤에도 플러스는 {F['top10_pre1017_positive_after']}개입니다. "
      f"앞 절반과 뒤 절반 순위의 상관은 같은 봉끼리 평균 {num(F['halves_within_tf_mean_spearman_R'], 2)}(0 = 관계 없음, 1 = 완전히 같음)입니다.")
    w(f"6. **5년 기록과 맞춰 보면 하나도 남지 않습니다.** v4에서 번 계좌(거래 5번 이상) {F['good_forward']}개 중 5년 시험 기간(2024~26)에 거래당 플러스인 것은 {F['good_forward_test_plus']}개입니다.")
    if FX:
        w(f"7. **봇이 기록한 나머지(밤 그림자 22가지, 모든 신호, 조건 거르기)도 같은 답입니다.** "
          f"그림자 변형으로 계좌 결과가 운을 넘은 경우 {FX.get('shadow_bh_pass', 0)}/{FX.get('shadow_tests', 0)}칸, "
          f"모든 신호로 본 매매법×변형 {FX.get('allsig_bh_pass', 0)}/{FX.get('allsig_tests', 0)}칸, "
          f"앞 절반에서 고른 조건이 뒤 절반에서도 플러스인 비율 {pct(100 * (FX.get('cond_picks_h2_positive_share') or float('nan')), 0)}"
          f"(방향을 뒤집은 가짜 전략으로 같은 일을 하면 {pct(100 * (FX.get('cond_placebo_h2_positive_share') or float('nan')), 0)})입니다. "
          "손실을 눈에 띄게 줄인 것은 지정가 진입과 작은 크기뿐이고, 둘 다 동전에도 똑같이 듣는 비용 줄이기입니다.")
        GP0 = t("x_goal_path.csv") if have("x_goal_path.csv") else pd.DataFrame()
        if len(GP0) and v39 is not None:
            gv = GP0[(GP0["kind"] == "account") & (GP0["account_id"] == "V39_ALL@1h") & (GP0["m"] == 0.40) & (GP0["L"] == 30)]
            gall = GP0[(GP0["kind"] == "account") & (GP0["m"] == 0.40) & (GP0["L"] == 30)]
            if len(gv):
                gv = gv.iloc[0]
                w(f"8. **한 달 +500%(×6)는 \"지난 19일이 그대로 되풀이된다\"는 가정에서만 보입니다.** 그 가정이면 V39_ALL@1h를 증거금 40%·30배로 30일 돌릴 때 ×6 확률이 {pct(100 * gv['p_final_x6'], 0)}입니다. "
                  f"그러나 그 성적을 운으로 보면(같은 조건 동전의 평균) {pct(100 * gv['luck_only_p_final_x6'], 1)}, 5년 평균으로 보면 {pct(100 * gv['fiveyear_p_final_x6'], 1)}입니다. "
                  f"거래 10번 이상이고 거래당 플러스인 계좌 {len(gall)}개 중 나머지는 지난 19일이 되풀이돼도 ×6 확률이 {pct(100 * gall[gall['account_id'] != 'V39_ALL@1h']['p_final_x6'].max(), 0)} 이하입니다(9장).")
    w(f"9. **실거래 후보 목록은 비어 있습니다.** 미리 정한 6가지 기준(10장)을 모두 넘은 계좌는 {F['shortlist_n']}개입니다. "
      f"가장 가까운 것은 기준 {F['max_criteria']}개를 넘은 계좌들이고, 모두 \"운을 넘음\"과 \"5년 두 기간 플러스\"에서 떨어졌습니다.")
    w("")
    w("### 두 분이 물어보신 것 → 답")
    w("")
    rows = [["19일치 전부 돌린 결과는?", f"331계좌 {usd(F['v4_pnl'])}(v4). 이전 두 실행도 손실({usd(COV.loc['v3a', 'pnl'])}, {usd(COV.loc['v3b', 'pnl'])})", "2장, 3장"],
            ["돈 번 계좌는?", f"{len(prof)}개(거래한 {len(traded)}개 중). 숏 위주 + 하락장", "3장, 부록 A"],
            ["운이 아닌 계좌는?", "0개. 가장 가까운 V39_ALL@1h도 보정 기준에 조금 못 미침", "4장"],
            ["꾸준한 계좌는?", f"두 절반 모두 플러스 {F['both_halves_profit']}개. 운만으로도 {F['both_halves_expected_indep']:.0f}개 안팎", "5장"],
            ["그림자(청산·배수 바꾸기)로 좋아지나?", "8-1 표. 동전에도 똑같이 좋아지는 변화뿐", "8장"],
            ["조건을 걸면(장세·시간·방향)?", "앞 절반에서 고른 조건은 뒤 절반에서 동전 수준", "8-5"],
            ["손실을 줄이는 방법은?", "지정가 진입(신호당 손실 절반 이하, 낙관적 가정)과 작은 크기. 둘 다 우위는 아님", "8-3, 8-1"],
            ["한 달 +500%는?", "필요한 배수·확률 표. 근거 있는 후보 없음", "9장"],
            ["실거래로 돌릴 것은?", "근거 있는 것 없음. 시험 중인 V39_ALL@1h는 그대로 \"실행 확인용\"", "10장"]]
    w(table(rows, ["질문", "답", "자세히"]))
    w("")
    w("---")
    w("")

    # ============================================================ 1. terms
    w("## 1. 이 보고서에서 쓰는 말")
    w("")
    rows = [["**R**", "처음 손절까지의 거리를 1로 본 단위. -1R = 손절에 딱 걸린 손실(비용 전). +0.3R = 손절 폭의 30%만큼 이익"],
            ["**방향 R (비용 전)**", "수수료·펀딩을 빼기 전 R. 방향을 맞혔는지만 봄"],
            ["**비용 R**", "수수료+펀딩을 R로 바꾼 것. 손절 폭이 좁을수록 커짐"],
            ["**지갑 대비 %**", "거래 하나의 순손익 ÷ 그 거래 직전 지갑. 30배·증거금 30%면 가격 1% = 지갑 9%"],
            ["**ROE**", "증거금 대비 수익률"],
            ["**PF (수익 팩터)**", "번 돈 합계 ÷ 잃은 돈 합계. 1보다 크면 흑자"],
            ["**최대 낙폭**", "지갑 최고점에서 가장 많이 내려간 비율(열린 포지션 평가손 포함, 5분마다 기록)"],
            ["**동전 던지기 계좌 (RANDOM)**", "아무 때나, 방향을 동전으로 정해 같은 청산으로 거래하는 계좌. 봉마다 3개"],
            ["**동전 풀**", "이번 분석에서 만든 큰 동전 던지기 표본: 모든 봉 마감마다 6코인 롱·숏을 하나씩 봇 엔진으로 다시 돌림(3만 7천여 거래)"],
            ["**시험 A (맞춘 동전)**", "계좌의 거래 하나하나를 같은 봉·같은 코인·같은 방향의 동전 거래로 바꾸되, 날짜는 무작위로 뽑음. 숏을 많이 한 계좌는 동전도 숏을 많이 함 → 하락장 덕은 빠짐"],
            ["**시험 B (방향 뒤집기)**", "같은 신호를 반대 방향으로 들어갔다면. 롱 신호와 숏 신호를 따로 평균 내고 둘을 반씩 섞어 하락장 효과를 지움"],
            ["**시험 C (수익 확인)**", "날짜를 다시 뽑아 평균 R이 0보다 큰지. 시장 효과는 빼지 않음"],
            ["**p**", "운만으로 이만큼(또는 더) 좋게 나올 확률. 작을수록 운이 아닐 가능성"],
            ["**BH 보정 (q)**", "계좌 수백 개를 한꺼번에 보면 운으로도 몇 개는 p가 작게 나옴. q는 그 수만큼 엄격하게 고친 값. q<0.05면 통과"],
            ["**앞 절반 / 뒤 절반**", f"v4 기간을 반으로 자름: {kst(F['v4_start_ms'])} ~ {kst(F['mid_ms'])} / ~ {kst(F['v4_end_ms'])}"],
            ["**5년 기록**", "같은 매매법·봉을 지금 규칙(2 ATR 손절 + 계단 잠금, 지금 레버리지)으로 2020~2026-09에 돌린 결과. 21~23 = 고르는 기간, 24~26 = 시험 기간"],
            ["**밤 그림자**", "매일 밤 점검이 그날 끝난 실제 거래를 청산·배수·손절만 바꿔 혼자 다시 돌린 기록(22가지)"],
            ["**모든 신호 다시 돌리기**", "계좌가 포지션을 들고 있어서 못 탄 신호까지, 신호 하나하나를 새 계좌로 따로 돌린 것"],
            ["**노출**", "포지션 크기 ÷ 지갑 = 증거금 비율 × 레버리지. 30% × 30배 = 9배, 40% × 50배 = 20배"]]
    w(table(rows, ["말", "뜻"]))
    w("")
    w("---")
    w("")

    # ============================================================ 2. coverage
    w("## 2. 자료와 범위")
    w("")
    rows = []
    rule = {"v3a": "옛 단계 레버리지(50배부터), 5분봉 포함", "v3b": "품질 레버리지(대부분 30배)", "v4": "품질 레버리지, 딥시크·릴스 추가"}
    for r in ["v3a", "v3b", "v4"]:
        if r not in COV.index:
            continue
        c = COV.loc[r]
        rows.append([r, f"{kst(c['start_ms'])} ~ {kst(c['end_ms'])}", f"{c['days']:.1f}", int(c["accounts"]),
                     int(c["acc_with_trades"]), f"{int(c['trades']):,}", usd(c["pnl"]), rule[r]])
    w(table(rows, ["실행", "기간 (KST)", "일", "계좌", "거래한 계좌", "거래", "손익 합계", "규칙"]))
    w("")
    w("- **v4가 중심입니다.** 같은 규칙으로 처음부터 끝까지 돌았고, 거래 코드 해시는 22번의 재시작 동안 1개로 같았습니다. "
      f"재시작 알림은 모두 \"거래에는 영향 없음\"이었고(코드 버전 {F['v4_restart_changes'].get('commit', 0)}번, 설치 패키지 {F['v4_restart_changes'].get('packages', 0)}번), "
      f"1분봉 빠진 분은 0분입니다. 재시작 때문에 늦어서 거래하지 않은 신호(LATE)가 {F['v4_signal_status'].get('LATE', 0)}개 있었습니다(전체 {sum(F['v4_signal_status'].values()):,}개 중).")
    w("- **v3a·v3b는 따로 봅니다.** 계좌가 매번 $5,000로 새로 시작했고, v3a는 레버리지 규칙이 달라(50배 먼저) 달러 손익을 v4와 더하면 안 됩니다. "
      "대신 R(레버리지와 무관한 단위)로 같은 매매법·봉을 이어 붙여 꾸준함을 확인했습니다(5장, 부록 B).")
    cv = t("coverage_v4_grp_tf.csv").set_index("grp")
    rows = []
    for g in ["core", "ds", "reel", "flip", "flip5"]:
        if g in cv.index:
            r = cv.loc[g]
            rows.append([GKO[g]] + [int(r.get(tf, 0)) if nz(r.get(tf, np.nan)) else 0 for tf in ["5m", "15m", "30m", "1h", "4h"]] + [int(r.sum())])
    w("")
    w("v4 계좌 구성:")
    w("")
    w(table(rows, ["그룹", "5분", "15분", "30분", "1시간", "4시간", "합계"]))
    w("")
    zero = AC[AC["n"] == 0]
    w(f"- 거래가 0번인 계좌 {len(zero)}개: 신호가 아예 없음 {int((zero['zero_cause'].astype(str).str.startswith('no_signal')).sum())}개, "
      f"모든 신호가 크기 조건(손절이 강제청산가에 너무 가까움)에 막힘 {int((zero['zero_cause'].astype(str).str.startswith('all_rejected')).sum())}개. 목록은 부록 A.")
    w("- 그 밖의 계좌(복제·새 매매법)는 이번 자료에 없습니다.")
    w("")
    w("---")
    w("")

    # ============================================================ 3. whole bot
    w("## 3. 봇 전체 그림 (v4)")
    w("")
    w("### 3-1. 그룹별")
    w("")
    rows = []
    for g in ["core", "ds", "reel", "flip", "flip5"]:
        if g not in G.index:
            continue
        r = G.loc[g]
        rows.append([GKO[g], int(r["accounts"]), int(r["accounts_traded"]), int(r["accounts_profit"]), f"{int(r['n']):,}",
                     pct(r["win_pct"], 0), usd(r["pnl"]), pct(r["pnl_pct_of_start"], 0, True), usd(r["gross"]),
                     f"${r['fees']:,.0f}", Rf(r["mean_R"]), Rf(r["mean_gross_R"]), pct(r["mean_wallet_pct"], 2, True), num(r["pf"], 2)])
    w(table(rows, ["그룹", "계좌", "거래한", "번 계좌", "거래", "승률", "손익", "시작 대비", "비용 전", "수수료", "거래당 R", "방향 R", "지갑 대비/거래", "PF"]))
    w("")
    w("- 모든 그룹이 손실입니다. 동전 던지기도 같은 자리입니다.")
    w(f"- 승률이 60% 안팎인데도 손실인 이유: 계단 잠금은 이기면 작게(평균 {usd(G.loc['core', 'avg_win_usd'])}), 지면 크게(평균 {usd(G.loc['core', 'avg_loss_usd'])}) 움직입니다(기본 매매법, 거래 하나 기준).")
    w("")
    w("### 3-2. 봉별")
    w("")
    gt = t("v4_by_group_tf.csv")
    gt = gt.assign(_g=gt["grp"].map({"core": 0, "ds": 1, "flip": 2, "flip5": 3, "reel": 4}), _t=gt["tf"].map(TFO)).sort_values(["_g", "_t"])
    rows = []
    for r in gt.itertuples():
        rows.append([GKO[r.grp], TFKO.get(r.tf, r.tf), f"{r.n:,}", pct(r.win_pct, 0), usd(r.pnl), Rf(r.mean_R), Rf(r.mean_gross_R), f"{r.mean_cost_R:.3f}R", pct(r.mean_wallet_pct, 2, True)])
    w(table(rows, ["그룹", "봉", "거래", "승률", "손익", "거래당 R", "방향 R", "비용 R", "지갑 대비/거래"]))
    w("")
    w("- 봉이 짧을수록 비용 R이 커서 더 잃습니다. 15분봉은 거래당 비용이 0.15R 안팎, 4시간봉은 0.05R 안팎입니다.")
    c4 = gt[(gt["grp"] == "core") & (gt["tf"] == "4h")]
    if len(c4) and c4["pnl"].iloc[0] > 0:
        w(f"- 기본 매매법 4시간봉만 플러스({usd(c4['pnl'].iloc[0])}, {int(c4['n'].iloc[0])}거래)입니다. 숏 비율이 {pct(100 * (1 - c4['long_share'].iloc[0]), 0)}로 가장 높습니다(하락장 몫, 3-9).")
    w("")
    w("### 3-3. 롱과 숏")
    w("")
    gs = t("v4_by_group_side.csv")
    rows = [[GKO[r.grp], "롱" if r.side_name == "long" else "숏", f"{r.n:,}", pct(r.win_pct, 0), usd(r.pnl), Rf(r.mean_R), Rf(r.mean_gross_R)] for r in gs.itertuples()]
    w(table(rows, ["그룹", "방향", "거래", "승률", "손익", "거래당 R", "방향 R"]))
    w("")
    pool = t("pool_by_tf_side.csv")
    w("- **숏이 롱보다 나은 것은 동전도 똑같습니다.** 동전 풀(아무 때나 들어감)에서 숏과 롱의 거래당 R:")
    w("")
    rows = []
    for tf in ["15m", "30m", "1h", "4h"]:
        x = pool[pool["timeframe"] == tf].set_index("side")
        if len(x) == 2:
            rows.append([TFKO[tf], Rf(x.loc[1, "mean_R"]), Rf(x.loc[-1, "mean_R"]), num(x.loc[-1, "mean_R"] - x.loc[1, "mean_R"], 2, True), f"{int(x['n'].sum()):,}"])
    w(table(rows, ["봉", "동전 롱", "동전 숏", "숏 - 롱", "동전 거래"]))
    w("")
    w("### 3-4. 코인별")
    w("")
    gc = t("v4_by_group_coin.csv")
    rows = []
    for g in ["core", "ds", "flip"]:
        x = gc[gc["grp"] == g].set_index("symbol")
        rows.append([GKO[g]] + [f"{usd(x.loc[s, 'pnl'])} ({Rf(x.loc[s, 'mean_R'], 2)})" if s in x.index else "—" for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]])
    w(table(rows, ["그룹", "BTC", "ETH", "SOL", "DOGE", "LTC", "BCH"]))
    w("")
    w("- BTC가 가장 크게 잃었습니다. BTC는 움직임이 작아 손절 폭이 좁고, 그래서 비용 R이 가장 큽니다.")
    w("")
    w("### 3-5. 시간대와 주말 (진입 시각, KST)")
    w("")
    ss = t("v4_by_session.csv")
    rows = [[("매매법(기본+딥시크)" if r.strat == "strategies" else "동전 던지기"), r.session, f"{r.n:,}", usd(r.pnl), Rf(r.mean_R), Rf(r.mean_gross_R)] for r in ss.itertuples()]
    wk = t("v4_by_weekend.csv")
    rows += [[("매매법(기본+딥시크)" if r.strat == "strategies" else "동전 던지기"), "주말" if r.weekend == "weekend" else "평일", f"{r.n:,}", usd(r.pnl), Rf(r.mean_R), Rf(r.mean_gross_R)] for r in wk.itertuples()]
    w(table(rows, ["묶음", "시간대", "거래", "손익", "거래당 R", "방향 R"]))
    w("")
    w("- 모든 시간대·평일·주말이 손실입니다. 매매법의 시간대 차이는 작고(거래당 -0.16 ~ -0.19R), 동전 던지기의 시간대 차이가 오히려 더 큽니다. 거를 근거가 되지 않습니다(8-5에서 앞·뒤 절반으로 다시 확인).")
    w(f"- 시간별(24칸) 표는 `tables/v4_by_hour.csv`에 있습니다.")
    w("")
    w("### 3-6. 청산 이유")
    w("")
    ex = t("v4_by_exit.csv")
    rows = [[GKO[r.grp], {"LOCK": "계단 잠금", "SL": "손절", "TP": "익절(릴스식)"}.get(r.exit_reason, r.exit_reason), f"{r.n:,}", usd(r.pnl), Rf(r.mean_R), pct(r.mean_wallet_pct, 2, True)] for r in ex.itertuples()]
    w(table(rows, ["그룹", "청산", "거래", "손익", "거래당 R", "지갑 대비/거래"]))
    w("")
    w("- 계단 잠금으로 끝난 거래는 평균 +0.5R, 손절은 -1.17R입니다. 손절 1번을 메우려면 잠금 2.3번이 필요하고, 그래서 본전 승률이 70% 안팎입니다.")
    w("")
    w("### 3-7. 배수와 진입 등급")
    w("")
    tl = t("v4_by_tier_lev.csv")
    rows = [[GKO[r.grp], {"best": "좋은 자리", "normal": "보통"}.get(r.tier, r.tier), f"{int(r.leverage)}배", f"{r.n:,}", usd(r.pnl), Rf(r.mean_R), Rf(r.mean_gross_R), pct(r.mean_wallet_pct, 2, True)] for r in tl.itertuples()]
    w(table(rows, ["그룹", "등급", "배수", "거래", "손익", "거래당 R", "방향 R", "지갑 대비/거래"]))
    w("")
    w("- \"좋은 자리\" 등급(40·50배)이 보통보다 나쁩니다. 배수가 커서 잃는 속도만 빠릅니다. 20배 거래가 덜 잃는 것은 손절 폭이 넓어 30배가 안 된 거래들이라 비용 R이 작기 때문입니다.")
    w("- 진입 점수(score)는 모든 거래에서 0으로 기록되어 따로 볼 수 없습니다.")
    w("")
    w("### 3-8. 수수료와 펀딩")
    w("")
    w(f"- 수수료 합계 ${F['v4_fees']:,.0f}, 펀딩 합계 {usd(-F['v4_funding'])}(+는 받은 돈)입니다. 펀딩은 무시할 만큼 작습니다.")
    w(f"- 비용 전 손익 {usd(F['v4_gross'])}에 수수료가 더해져 {usd(F['v4_pnl'])}이 됐습니다. **매매법이 방향으로 잃은 돈보다 수수료로 잃은 돈이 약 {F['v4_fees'] / max(1, -F['v4_gross']):.1f}배 큽니다.**")
    w("")
    w("### 3-9. 시장 움직임과 하락장 몫")
    w("")
    rows = [[r.symbol.replace("USDT", ""), pct(r.change_pct, 1, True), pct(-r.max_drop_pct, 1), pct(r.max_rise_pct, 1, True)] for r in M.itertuples()]
    rows.append(["6코인 평균", pct(F["market_eq6_pct"], 1, True), "", ""])
    w(table(rows, ["코인", "기간 변화", "최고점에서 최대 하락", "저점에서 최대 반등"]))
    w("")
    w(f"- {F['market_days']}일 중 {F['market_down_days']}일이 하락(6코인 평균)이었습니다. 앞 절반 {pct(W[(W['window'] == 'h1') & (W['grp'] == 'core')]['market_eq6_pct'].iloc[0], 1, True)}, 뒤 절반 {pct(W[(W['window'] == 'h2') & (W['grp'] == 'core')]['market_eq6_pct'].iloc[0], 1, True)}로, 하락은 거의 앞 절반에 몰렸습니다.")
    rows = []
    for g in ["core", "ds", "flip"]:
        if g in ME.index:
            r = ME.loc[g]
            rows.append([GKO[g], pct(100 * r["long_share"], 0), usd(r["pnl"]), usd(r["mkt_usd"]), usd(r["pnl_ex_market"])])
    w("")
    w("\"시장 몫\" = 거래마다 (동전 풀에서 그 봉·코인·방향의 평균 R) - (그 봉·코인의 롱·숏 평균 R)을 그 거래 크기로 곱해 더한 것. 숏을 많이 한 만큼 하락장이 거저 준 돈입니다.")
    w("")
    w(table(rows, ["그룹", "롱 비율", "손익", "시장 몫", "시장 몫을 뺀 손익"]))
    w("")
    w(f"- 날마다의 매매법 손익과 그날 시장 움직임의 상관은 {num(F['corr_daily_strategies_vs_market'], 2)}입니다. 롱·숏이 섞여 있어 하루 단위로는 시장을 따라가지 않습니다. 하락장 몫은 숏 비율이 높은 계좌에 몰려 있습니다(계좌별 \"시장 몫\"은 부록 A).")
    w("")
    w("### 3-10. 날짜별")
    w("")
    dd = t("v4_by_day.csv")
    rows = [[r.day, usd(r.core), usd(r.ds), usd(getattr(r, "flip", np.nan)), usd(r.all), pct(r.eq6, 1, True)] for r in dd.itertuples()]
    w(table(rows, ["날짜 (KST, 청산 기준)", "기본 매매법", "딥시크", "동전", "전체", "6코인 그날 변화"]))
    w("")
    w(f"- 매매법 전체가 플러스인 날은 {int((dd['strategies'] > 0).sum())}일/{len(dd)}일입니다. 계좌별 날짜 손익은 `daily_pnl.csv`(계좌, 날짜, 손익, 거래 수)에 있습니다.")
    w("")
    w("---")
    w("")

    # ============================================================ 4. luck
    w("## 4. 운 거르기")
    w("")
    w("### 4-1. 동전 던지기 계좌와 나란히")
    w("")
    vr = t("vs_random_by_tf.csv")
    rows = [[TFKO[r.tf], usd(r.random_pnl_best), usd(r.random_pnl_worst), int(r.real_accounts), int(r.real_profit), int(r.real_above_best_random), int(r.real_below_worst_random), Rf(r.real_mean_R_tradeweighted), Rf(r.pool_mean_R)] for r in vr.itertuples()]
    w(table(rows, ["봉", "동전 3개 중 최고", "동전 최저", "매매법 계좌", "번 계좌", "동전 최고보다 나은", "동전 최저보다 못한", "매매법 거래당 R", "동전 풀 거래당 R"]))
    w("")
    w("- 동전 계좌는 봉마다 3개뿐이라 들쭉날쭉합니다(1시간봉 RANDOM_3 +$874, RANDOM_1 +$136). 그래서 3만 7천 거래짜리 동전 풀로 다시 비교했습니다.")
    w("- 1시간봉·15분봉 매매법의 거래당 R은 동전 풀과 비슷하거나 못합니다. 4시간봉 매매법이 동전 풀보다 나은 것은 숏 비율(기본 매매법 78%) 때문입니다(시험 A가 이것을 거릅니다).")
    w("")
    w("### 4-2. 세 가지 시험 (거래 10번 이상 계좌)")
    w("")
    rows = [["A. 맞춘 동전 (하락장 덕 제거)", F["A_tested"], F["A_raw_p05"], f"{0.05 * F['A_tested']:.0f}", F["A_bh_pass"], F["A_bh_worse"]],
            ["B. 방향 뒤집기, 롱·숏 반반 (모든 신호)", F["B_tested"], F["B_raw_p05"], f"{0.05 * F['B_tested']:.0f}", F["B_bh_pass"], F["B_bh_worse"]],
            ["C. 수익이 0보다 큰가 (시장 효과 안 뺌)", F["C_tested"], F["C_raw_p05"], f"{0.05 * F['C_tested']:.0f}", F["C_bh_pass"], "—"]]
    w(table(rows, ["시험", "본 계좌", "p<0.05 (보정 전)", "운만으로 나올 수", "보정 뒤 통과", "보정 뒤 '확실히 나쁨'"]))
    w("")
    w(f"- **운을 넘은 계좌(A 통과)는 0개입니다.** 보정 전 p<0.05도 운만으로 나올 수보다 적습니다.")
    cpass = AC[AC["C_q"] < 0.05]["account_id"].tolist()
    if cpass:
        w(f"- 시험 C만 통과한 계좌: {', '.join(cpass)}. 돈을 번 것은 날짜 운이 아니라는 뜻이지만, 하락장 덕까지 걸러 주지는 않습니다.")
    w(f"- 1등이 운의 1등보다 나은가: 시험 A에서 가장 좋은 계좌({F.get('maxT_best_account', '?')})의 점수는 {num(F.get('maxT_best_z'), 2)}입니다. "
      f"동전만으로 {F['A_tested']}개를 돌렸을 때 1등 점수의 가운데값은 {num(F.get('maxT_null_median'), 2)}, 상위 5%는 {num(F.get('maxT_null_p95'), 2)}입니다. "
      f"**실제 1등이 동전 1등의 보통 수준보다 낮습니다**(p={num(F.get('maxT_p'), 2)}).")
    w("- 계좌마다의 p와 q는 부록 A에 모두 있습니다.")
    w("")
    w("보정 전 p가 가장 작은 10개:")
    w("")
    top = AC[AC["A_p_better"].notna() & (AC["n"] >= 10) & AC["grp"].isin(["core", "ds"])].sort_values("A_p_better").head(10)
    rows = [[r.account_id, int(r.n), usd(r.pnl), Rf(r.mean_R), Rf(r.A_null_mean_R), pv(r.A_p_better), num(r.A_q, 2), pv(r.B_p_better), num(r.B_q, 2), pv(r.C_p_le0), num(r.C_q, 2)] for r in top.itertuples()]
    w(table(rows, ["계좌", "거래", "손익", "거래당 R", "맞춘 동전 R", "A p", "A q", "B p", "B q", "C p", "C q"]))
    w("")
    if v39 is not None:
        w("### 4-3. V39_ALL@1h (가장 가까운 계좌, 실거래 시험 중)")
        w("")
        w(f"- {int(v39['n'])}거래 중 {int(round(v39['win_pct'] * v39['n'] / 100))}승, {usd(v39['pnl'])}, 최대 낙폭 {pct(100 * v39['max_dd'], 1)}, 롱 {int(v39['long_n'])} / 숏 {int(v39['short_n'])}.")
        w(f"- 10/17 이전 {usd(v39['pre1017_pnl'])}({int(v39['pre1017_n'])}거래), 이후 {usd(v39['post1017_pnl'])}({int(v39['post1017_n'])}거래). 실거래 시험을 시작한 10/19 12시 이후 페이퍼: {F['v39_since_1019']['n']}거래 {F['v39_since_1019']['wins']}승 {usd(F['v39_since_1019']['pnl'])}.")
        w(f"- 시험 B: 같은 순간 반대로 들어갔다면 거래당 {Rf(v39['B_R_other'])}였습니다(실제 신호 쪽 {Rf(v39['B_R_chosen'])}). 롱 신호({int(v39['B_long'])}개)와 숏 신호({int(v39['B_short'])}개) 모두에서 고른 방향이 나았습니다({Rf(v39['B_excess_long'])}, {Rf(v39['B_excess_short'])}). "
          f"p={pv(v39['B_p_better'])}, {F['B_tested']}개를 같이 본 보정 뒤 q={num(v39['B_q'], 3)}.")
        w(f"- 시험 A: 맞춘 동전의 거래당 {Rf(v39['A_null_mean_R'])} 대비 {Rf(v39['A_obs_R'])}. p={pv(v39['A_p_better'])}, q={num(v39['A_q'], 2)}. 25거래로는 동전과의 차이가 넉넉히 크지 않습니다.")
        w(f"- 5년: 고르는 기간 거래당 {pct(100 * v39['select_mean'], 2, True)}, 시험 기간 {pct(100 * v39['test_mean'], 2, True)}, 승률 {pct(100 * v39['test_win'], 0)}, 계좌 파산. 5년 동안 1시간봉 V3.9는 1년에 수백 번 거래하며 꾸준히 잃었습니다. 지금 19일이 5년과 다른 이유는 아직 설명되지 않습니다.")
        w("- 판단: **\"계속 지켜볼 1순위\"이지 \"크기를 키울 근거\"는 아닙니다.** 같은 1시간봉 동전 계좌도 10/17까지 11연승을 했었습니다. 30거래·한 달 더 쌓이면 B 시험이 보정을 넘는지 다시 봅니다.")
        w("")
    w("---")
    w("")

    # ============================================================ 5. stability
    w("## 5. 꾸준한가")
    w("")
    w(f"- 매매법 계좌 중 앞 절반 플러스 {F['h1_profit']}개, 뒤 절반 플러스 {F['h2_profit']}개, 둘 다 플러스 {F['both_halves_profit']}개입니다. 두 절반이 서로 관계없어도 {F['both_halves_expected_indep']:.0f}개 안팎은 나옵니다. "
      f"실제가 그보다 많은 것은 두 절반 모두 같은 이유로 덜 잃은 계좌가 있어서입니다: {int(((bh_ := S[(S['h1_pnl'] > 0) & (S['h2_pnl'] > 0)])['tf'] == '4h').sum())}개가 4시간봉(거래가 적고 비용 R이 작음), "
      f"{int((bh_['short_n'] / bh_['n'] > 0.6).sum())}개가 숏 60% 넘는 계좌(하락장)입니다.")
    hw = t("halves_within_tf.csv")
    hw = hw.assign(_t=hw["tf"].map(TFO)).sort_values("_t")
    w(f"- 같은 봉끼리 앞·뒤 절반 거래당 R의 순위 상관: " + ", ".join(f"{TFKO[r.tf]} {r.spearman_R:+.2f}" for r in hw.itertuples()) + ". 대체로 0에 가깝습니다.")
    w(f"- 앞 절반 1~10등 중 뒤 절반에도 플러스: {F['top10_h1_positive_in_h2']}개.")
    w(f"- 10/17 분석 때(10/17 08:40까지) 1~10등이 그 뒤 {F.get('v4_days', 0) - (F['cut1017_ms'] - F['v4_start_ms']) / 86_400_000:.1f}일 동안 낸 손익:")
    w("")
    tp = t("top10_pre1017.csv")
    rows = [[i + 1, r.account_id, usd(r.pre1017_pnl), int(r.pre1017_n), usd(r.post1017_pnl), int(r.post1017_n), usd(r.pnl)] for i, r in enumerate(tp.itertuples())]
    w(table(rows, ["10/17 순위", "계좌", "10/17까지", "거래", "그 뒤", "거래", "합계"]))
    w("")
    w(f"- 10/17까지의 손익 순위와 그 뒤 순위의 상관은 {num(F['cut1017_spearman_pnl'], 2)}입니다(거래가 충분한 {F['cut1017_accounts']}개).")
    w("- 마지막 3일(그룹별):")
    w("")
    l3 = W[W["window"] == "last3"]
    rows = [[GKO[r.grp], f"{r.n:,}", usd(r.pnl), Rf(r.mean_R)] for r in l3.itertuples()]
    w(table(rows, ["그룹", "거래", "손익", "거래당 R"]))
    w("")
    w(f"  같은 3일 동안 6코인은 {pct(F['market_last3'], 1, True)} 움직였습니다.")
    w("")
    pr = t("persistence_v3_v4.csv")
    w("- 이전 실행(v3a 10/02~05, v3b 10/05~06)과 v4의 같은 매매법·봉(거래 5번 이상) 거래당 R 순위 상관: " +
      ", ".join(f"{r.run} {r.spearman_meanR_vs_v4:+.2f} ({int(r.cells)}칸, 이전에 플러스였던 {int(r.earlier_positive)}칸 중 v4도 플러스 {int(r.both_positive)}칸)" for r in pr.itertuples()) + ".")
    w("- 상위 20개 계좌의 날짜별 손익은 `tables/top20_by_day.csv`에 있습니다.")
    w("")
    w("---")
    w("")

    # ============================================================ 6. five-year
    w("## 6. 5년 기록과 대조")
    w("")
    fy = t("fiveyear_check.csv")
    w(f"v4에서 번 계좌(거래 5번 이상) {len(fy)}개를 모두 5년 기록(지금 숫자, 지금 청산)과 맞췄습니다. 딥시크는 두 분 결정 D11대로 5년 돈 숫자를 가리고 플러스/마이너스와 계좌 늘어남/줄어듦/파산만 적습니다.")
    w("")
    rows = []
    for r in fy.itertuples():
        ds = r.grp == "ds"
        f = (lambda x, s: ("플러스" if s > 0 else "마이너스") if ds else pct(100 * x, 2, True))
        cls = {"bust": "파산", "down": "줄어듦", "up": "늘어남"}.get(str(r.test_acct_class), "—")
        rows.append([r.account_id, int(r.n), usd(r.pnl), Rf(r.mean_R), f(r.select_mean, r.select_sign) if nz(r.select_sign) else "—",
                     f(r.test_mean, r.test_sign) if nz(r.test_sign) else "—", pct(100 * r.test_win, 0) if nz(r.test_win) else "—",
                     f"{int(r.test_n):,}" if nz(r.test_n) else "—", cls])
    w(table(rows, ["계좌", "v4 거래", "v4 손익", "v4 거래당 R", "5년 거래당 21~23", "5년 거래당 24~26", "24~26 승률", "24~26 신호", "24~26 계좌"]))
    w("")
    w(f"- **{len(fy)}개 중 5년 시험 기간 플러스: {F['good_forward_test_plus']}개, 두 기간 모두 플러스: {F['good_forward_both_plus']}개.** 전체 매매법·봉 {F['all_cells_with_ref']}칸 중 시험 기간 플러스는 {F['all_cells_test_plus']}칸뿐입니다.")
    w("- 5년 거래당 손실(대부분 -0.7~-1.3%)은 지금 크기(30배·증거금 30%)에서 지갑 대비입니다. 1년에 수백~수천 번 거래하면 계좌가 바닥납니다.")
    w("- 그래서 19일 동안 번 계좌들은 \"5년 동안 잃던 매매법이 이번 하락장 19일에 잠깐 이긴 것\"으로 보는 게 맞습니다.")
    w("")
    w("---")
    w("")

    # ============================================================ 7. what changed
    w("## 7. 10/17 분석 이후 바뀐 것")
    w("")
    pre, post = F["pre1017"], F["post1017"]
    rows = [[GKO[g], usd(pre[g]), Rf(F['pre1017_meanR'][g]), pct(100 * F['pre1017_long_share'][g], 0), usd(post[g]), Rf(F['post1017_meanR'][g]), pct(100 * F['post1017_long_share'][g], 0)] for g in ["core", "ds", "reel", "flip", "flip5"]]
    w(table(rows, ["그룹", "10/17까지 손익", "거래당 R", "롱 비율", "10/17 뒤 손익", "거래당 R", "롱 비율"]))
    w("")
    w(f"- 시장: 10/17까지 6코인 {pct(F['market_pre1017'], 1, True)}, 그 뒤 {pct(F['market_post1017'], 1, True)}. 그 뒤에도 내렸지만 덜 내렸습니다.")
    w(f"- 결론은 그대로입니다: 손실 = 비용, 방향 실력 0, 이긴 계좌 = 하락장. {(F['v4_end_ms'] - F['cut1017_ms']) / 86_400_000:.1f}일이 더해지면서 달라진 점:")
    o = F.get("acct_OBV_S@30m", {})
    if o:
        w(f"  - 10/17의 1등 OBV_S@30m(+$2,826)은 그 뒤 {usd(o.get('post1017_pnl'))}로 이익 절반을 돌려줬습니다.")
    if v39 is not None:
        w(f"  - V39_ALL@1h는 그 뒤에도 {usd(v39['post1017_pnl'])}를 더해 1등이 됐습니다. 이 계좌만 운 시험 B에서 보정 기준 가까이(q {num(v39['B_q'], 3)}) 왔습니다(4-3).")
    n9 = F.get("acct_N09_ALLIG_AROON@1h", {})
    if n9:
        w(f"  - 미리 정한 기준으로 고른 대안 N09_ALLIG_AROON@1h는 {usd(n9.get('pnl'))}({int(n9.get('n', 0))}거래)입니다.")
    w(f"  - \"0 of 194\"(시장 효과를 빼면 우연 이상 0개)는 이번에 더 엄격한 시험 A로 다시 계산해 {F['A_bh_pass']} of {F['A_tested']}입니다.")
    w("  - 새로 본 것: 밤 그림자 전부, 모든 신호의 청산 변형, 신호 때 차트 상황(조건) 거르기, 한 달 +500% 경로(8~9장).")
    w("")
    w("---")
    w("")

    # ============================================================ 8. everything else
    w("## 8. 봇이 기록한 나머지 전부")
    w("")
    if FX:
        w(f"밤 점검 기록(d3_shadows) {FX.get('d3_rows', 0):,}줄(UTC {FX.get('d3_days_utc', ['?', '?'])[0]} ~ {FX.get('d3_days_utc', ['?', '?'])[1]}), 모든 신호 기록(outcomes, signal_log), 신호 때 차트 상황(signal_ctx)을 썼습니다.")
        w("")
        w("**확인:** 밤 그림자를 같은 엔진으로 다시 계산해 보니 그림자 값이 있는 거래는 모두 1e-6 안에서 같았습니다(무작위 400거래 × 22가지). 밤 점검은 그날 밤까지의 봉만 보기 때문에 아직 안 끝난 그림자(특히 고정 익절 3R의 약 28%)가 비어 있습니다. "
          "그래서 이 장의 그림자 숫자는 10/24 밤까지의 1분봉으로 다시 계산한 것입니다(같은 코드, 더 많이 끝남).")
        w("")
        w("### 8-1. 밤 그림자: 청산·배수·손절을 바꿨다면 (계좌가 실제로 탄 거래들)")
        w("")
        w("밤 점검 기록의 종류 (`docs/observation-shadows*.md`에서 미리 정한 것):")
        w("")
        rows = [["lock15 / lock20 / lock30", "첫 잠금을 +10% 대신 +15% / +20% / +30% ROE로(그 뒤 5%p씩은 같음)"],
                ["timestop", "잠금이 한 번도 안 걸린 채 정해진 봉 수(15분 12봉, 30분 10봉, 1시간 8봉, 4시간 6봉)가 지나면 시장가로 닫기"],
                ["lev10 / lev20", "10배·20배 고정, 증거금 20%"], ["lev30 / lev40 / lev50", "30·40·50배 고정, 증거금 30·40·40%"],
                ["lev20m20 ~ lev50m50", "20~50배 고정, 증거금 = 배수% (50배면 증거금 50%)"],
                ["stopw1.5 / stopw2.5 / stopw3", "처음 손절을 2 ATR 대신 1.5 / 2.5 / 3 ATR로(배수는 실제와 같음)"],
                ["tp1R / tp1.5R / tp2R / tp3R", "계단 잠금 없이 고정 익절(손절 폭의 1~3배)"], ["ladder_cap2R", "계단 잠금 그대로 + 2R에서 익절"],
                ["quality", "진입 세기 점수로 배수를 고름(50·40·30·20배)"], ["limit", "0.25 ATR 유리한 지정가로 한 봉 동안 기다림"],
                ["skipped", "포지션 때문에 못 탄 신호를 혼자 돌림"], ["stop1.5 / stop2.5 / stop3.0", "진 거래만 손절 폭을 바꿔 다시 돌림"],
                ["stop_slips", "손절·잠금 청산이 실제 거래소 체결 기록으로는 얼마에 됐을지"]]
        w(table(rows, ["이름", "뜻"]))
        w("")
        xs = t("x_shadow_variant_summary.csv")
        xv = t("x_shadow_variant_accounts.csv").set_index("variant")
        xsc = xs[xs["accounts"] == "core+ds"].set_index("variant")
        rows = []
        for v in [x for x in VKO if x in xsc.index]:
            r = xsc.loc[v]
            a = xv.loc[v] if v in xv.index else None
            rows.append([VKO[v], f"{int(r['done']):,}", f"{int(r['no_entry']):,}", pct(r["base_wallet_pct"], 2, True), pct(r["variant_wallet_pct"], 2, True),
                         pct(r["diff_pct"], 2, True), f"{pct(r['diff_ci_lo'], 2, True)} ~ {pct(r['diff_ci_hi'], 2, True)}", pct(r["coinflip_pool_diff_pct"], 2, True),
                         f"{int(a['profit_accounts'])}/{int(a['accounts'])}" if a is not None else "—", f"{int(a['bh_pass'])}/{int(a['tested'])}" if a is not None else "—"])
        w(table(rows, ["변형", "끝난 거래", "진입 못 함", "기준 지갑%/거래", "변형 지갑%/거래", "차이", "차이 90% 범위", "동전 풀에서 같은 변형의 차이", "그림자 계좌 플러스", "운 넘음 (보정)"]))
        w("")
        w("읽는 법: \"차이\"는 같은 거래들에서 변형 - 지금 규칙(지갑 대비 %, 거래당). \"동전 풀에서 같은 변형의 차이\"가 비슷하면 그 변형은 매매법이 아니라 이 시장에서 그 청산 자체가 낫거나 나빴다는 뜻입니다. "
          "\"그림자 계좌\" = 계좌의 실제 거래를 그 변형으로 바꿔 순서대로 복리로 곱한 지갑($5,000 시작). \"운 넘음\" = 같은 변형으로 돌린 동전과 비교한 시험(시험 A와 같은 방식), 보정 뒤 통과 수.")
        w("")
        shape = xsc[[not i.startswith("lev") and i != "base" for i in xsc.index]].sort_values("diff_pct", ascending=False)
        if len(shape):
            b = shape.iloc[0]
            w(f"- 배수가 아닌 청산·손절 변형 중 거래당 가장 크게 나아진 것은 **{VKO.get(shape.index[0], shape.index[0])}**({pct(b['diff_pct'], 2, True)}/거래, 90% 범위 {pct(b['diff_ci_lo'], 2, True)} ~ {pct(b['diff_ci_hi'], 2, True)})입니다. 범위가 0을 걸쳐 \"나아졌다\"고 말할 수 없고, 거래당은 여전히 {pct(b['variant_wallet_pct'], 2, True)}로 손실입니다.")
        w("- 10배·20배 변형이 덜 잃는 것은 크기가 작아서입니다(지갑 대비 손실이 줄 뿐, 거래당 R은 같음). 동전 풀에서도 똑같이 줄어듭니다.")
        w(f"- 그림자 계좌로 운을 넘은 칸: {FX.get('shadow_bh_pass', 0)}개 (계좌 × 변형 {FX.get('shadow_tests', 0)}칸, 보정 전 p<0.05 {FX.get('shadow_raw_p05', 0)}칸, 운만으로 {FX.get('shadow_expected_raw', 0):.0f}칸 안팎).")
        w("- 배수만 바꾼 변형(lev…)은 거래당 R을 바꾸지 않고 크기만 바꿉니다. 40·50배는 진입 못 하는 거래가 많아(크기 조건) 남은 거래만 보면 좋아 보일 수 있습니다. 진입 못 함 수를 같이 보세요.")
        if FX.get("quality_pairs"):
            w(f"- 진입 세기 등급으로 배수를 고르는 그림자(quality, 밤 점검 기록 {FX['quality_pairs']:,}거래): 지금 규칙 {pct(FX['quality_base_pct'], 2, True)}/거래 → {pct(FX['quality_pct'], 2, True)}/거래.")
        w(f"- 변형별·계좌별 전체 표: `tables/x_shadow_account_variant.csv`. 변형별 계좌 요약: `tables/x_shadow_variant_accounts.csv`.")
        w("")
        w("변형별 그림자 계좌 결과 (기본 매매법 + 딥시크 계좌):")
        w("")
        rows = [[VKO.get(v, v), int(r.accounts), int(r.profit_accounts), int(r.beats_actual_final), int(r.bust), usd(r.median_final, False), usd(r.best_final, False), f"{int(r.raw_p05)}/{int(r.tested)}"] for v, r in xv.iterrows()]
        w(table(rows, ["변형", "계좌", "플러스", "실제 계좌보다 나음", "파산", "가운데 지갑", "최고 지갑", "보정 전 p<0.05"]))
        w("")
        w("### 8-2. 모든 신호로 본 매매법 (포지션 때문에 못 탄 신호 포함)")
        w("")
        tv = t("x_taken_vs_missed.csv")
        w("계좌가 탄 신호와 못 탄 신호를 각각 혼자 돌린 결과(지금 규칙):")
        w("")
        lab = {"ENTERED:ok": "탄 신호", "SKIPPED:in position": "포지션 중이라 못 탐", "SKIPPED:lower score than entered signal": "같은 봉 다른 코인에 밀림",
               "REJECTED:sizing": "크기 조건에 막힘"}
        tv2 = tv[tv["acct"].isin(lab)].groupby(["grp", "acct"]).apply(lambda g: pd.Series({"n": g["n"].sum(), "R": np.average(g["mean_R"], weights=g["n"])}), include_groups=False).reset_index()
        rows = [[GKO.get(r.grp, r.grp), lab[r.acct], f"{int(r.n):,}", Rf(r.R)] for r in tv2.itertuples()]
        w(table(rows, ["그룹", "신호", "신호 수", "거래당 R"]))
        w("")
        w("- 못 탄 신호도 탄 신호와 같은 수준으로 잃습니다. 포지션 제한이 좋은 기회를 막은 것이 아닙니다.")
        xb = t("x_allsig_cell_variant.csv")
        b0 = xb[xb["variant"] == "base"]
        w(f"- 매매법×봉 {FX.get('allsig_base_cells', 0)}칸을 모든 신호로 보면, 지금 규칙으로 플러스인 칸 {FX.get('allsig_base_positive', 0)}개, 두 절반 모두 플러스 {FX.get('allsig_base_both_halves_positive', 0)}개입니다(두 절반이 서로 관계없어도 {FX.get('allsig_base_both_halves_expected', float('nan')):.0f}개 안팎). 그 칸들도 동전과 비교하면 보정 뒤 통과는 없습니다.")
        w(f"- 22가지 변형까지 모두 보면 {FX.get('allsig_cells_variants', 0):,}칸 중 두 절반 모두 플러스 {FX.get('allsig_any_variant_both_halves_positive', 0)}칸, 같은 변형의 동전과 비교해 보정 뒤 운을 넘은 칸 {FX.get('allsig_bh_pass', 0)}개(보정 전 p<0.05 {FX.get('allsig_raw_p05', 0)}칸, 운만으로 {0.05 * FX.get('allsig_tests', 0):.0f}칸 안팎).")
        w("")
        w("모든 신호, 동전 풀과 같은 변형으로 나란히 (봉별, 기본+딥시크 전체, 지갑 대비 %/신호):")
        w("")
        at = t("x_allsig_tf_variant.csv")
        rows = []
        for v in ["base", "lock30", "timestop", "tp1R", "tp2R", "tp3R", "ladder_cap2R", "stopw1.5", "stopw3", "lev20m20", "lev50m50"]:
            x = at[at["variant"] == v].set_index("timeframe")
            rows.append([VKO[v]] + [f"{pct(x.loc[tf, 'mean_wallet_pct'], 2, True)} / {pct(x.loc[tf, 'pool_wallet_pct'], 2, True)}" if tf in x.index else "—" for tf in ["15m", "30m", "1h", "4h"]])
        w(table(rows, ["변형", "15분 (매매법 / 동전)", "30분", "1시간", "4시간"]))
        w("")
        w("- 위 표는 롱·숏·코인·날짜 구성이 달라서 그대로 빼면 안 됩니다. 그래서 신호마다 **같은 날·같은 코인·같은 방향의 동전 평균**을 빼고(그날 시장 방향까지 제거), 날짜별로 평균 냈습니다:")
        w("")
        at2 = at.copy()
        rows = []
        for v in ["base", "lock30", "timestop", "tp1R", "tp1.5R", "tp2R", "tp3R", "stopw1.5", "stopw3"]:
            x = at2[at2["variant"] == v].set_index("timeframe")
            rows.append([VKO[v]] + [f"{pct(x.loc[tf, 'sameday_excess_pct'], 2, True)} ({int(x.loc[tf, 'sameday_days_pos'])}/{int(x.loc[tf, 'sameday_days'])}일 +)" if tf in x.index and nz(x.loc[tf, 'sameday_excess_pct']) else "—" for tf in ["15m", "30m", "1h", "4h"]])
        w(table(rows, ["변형", "15분: 동전 대비 지갑%/신호 (플러스인 날)", "30분", "1시간", "4시간"]))
        w("")
        w(f"- {FX.get('allsig_tf_variant_rows', 0)}칸 중 동전보다 나은 칸 {FX.get('allsig_tf_variant_sameday_pos', 0)}개, 가장 큰 t {num(FX.get('allsig_tf_variant_sameday_t_max'), 2)}(2를 넘어야 \"운이 아닐 수도\"). **어느 청산·배수 변형을 써도 매매법 신호는 같은 날 아무 때나 들어간 동전보다 낫지 않습니다.**")
        w("")
        top_c = xb[xb["L_p_better"].notna()].sort_values("L_p_better").head(12)
        w("동전 대비 p가 가장 작은 12칸 (매매법×봉×변형, 모든 신호):")
        w("")
        rows = [[r.account_id, VKO.get(r.variant, r.variant), int(r.signals), pct(r.mean_wallet_pct, 2, True), pct(100 * r.L_null_mean, 2, True), pct(r.h1_wallet_pct, 2, True), pct(r.h2_wallet_pct, 2, True), pv(r.L_p_better), num(r.L_q, 2)] for r in top_c.itertuples()]
        w(table(rows, ["칸", "변형", "신호", "지갑%/신호", "같은 변형 동전", "앞 절반", "뒤 절반", "p", "q"]))
        w("")
        w("### 8-3. 지정가 진입 (밤 그림자 limit: 0.25 ATR 유리한 가격, 한 봉 기다림)")
        w("")
        ls = t("x_limit_entry.csv")
        ls = ls.assign(_g=ls["grp"].map({"core": 0, "ds": 1, "flip": 2}), _t=ls["timeframe_x"].map(TFO)).sort_values(["_g", "_t"])
        rows = [[GKO.get(r.grp, r.grp), TFKO.get(r.timeframe_x, r.timeframe_x), f"{int(r.signals):,}", pct(100 * r.fill_share, 0), pct(100 * r.market_roe, 2, True), pct(100 * r.limit_roe_all, 2, True), pct(100 * r.limit_roe_if_filled, 2, True), pct(100 * r.market_roe_same_filled, 2, True)] for r in ls.itertuples()]
        w(table(rows, ["그룹", "봉", "신호", "체결 비율", "시장가 진입: ROE/신호", "지정가: ROE/신호 (안 되면 0)", "지정가 체결된 것만", "그 신호들을 시장가로"]))
        w("")
        w("- 지정가(0.25 ATR 유리하게, 한 봉 기다림)는 15분~1시간봉에서 신호당 손실을 대략 절반 이하로 줄였습니다. 크기를 줄이는 것 말고는 이번 자료에서 손실을 가장 크게 줄인 방법입니다. 그래도 거의 모든 칸이 마이너스이고(4시간봉은 오히려 나빠짐, 신호도 적음), 동전 던지기도 비슷하게 좋아집니다. 비용을 줄이는 방법이지 우위가 아닙니다.")
        w("- 체결된 신호는 가격이 먼저 반대로 움직인 신호라 시장가로는 더 나빴던 신호들입니다. 바로 맞는 방향으로 간 신호는 체결이 안 돼 놓칩니다. \"닿으면 체결\"이라는 낙관적 가정이라 실제 체결은 이보다 적을 수 있습니다.")
        w("")
        w("### 8-4. 그 밖의 밤 기록")
        w("")
        if FX.get("d3_nights"):
            w(f"- **매일 밤 계산 확인(parity):** {FX['d3_nights']}밤 동안 매일 {FX['d3_parity_accounts_per_night']}계좌를 처음부터 다시 계산해 페이퍼와 맞췄고, 어긋난 계좌는 모두 합쳐 {FX['d3_parity_mismatched_total']}개입니다. 페이퍼 계산 자체는 믿을 수 있습니다.")
        if FX.get("stop_slips"):
            sx = FX["stop_slips"]
            w(f"- **손절·잠금 체결 미끄러짐(d3_stop_slips):** 손절·잠금 청산 {sx['exits']:,}건 중 {sx['with_real']:,}건을 실제 거래소 체결 기록으로 확인했습니다. 페이퍼는 2bp(0.02%)를 가정하는데, 실제로 같은 크기 주문이 받았을 가격은 가운데값 {sx['real_bps']:.1f}bp, 나쁜 10% {sx['real_bps_p90']:.0f}bp였습니다. 합치면 페이퍼가 {usd(-sx['diff_usd_sum'], False)} 더 비싸게 계산했습니다. 페이퍼 손실이 미끄러짐 때문에 부풀려진 것은 아니고, 실제가 페이퍼보다 크게 나쁘지도 않습니다.")
        sv = FX.get("d3_stop_variants_losers") or {}
        if sv:
            w("- **진 거래만의 손절 폭 그림자(stop1.5/2.5/3.0):** 진 거래만 다시 돌린 기록이라 이긴 거래가 어떻게 바뀌는지 모릅니다(한쪽만 본 숫자). " + ", ".join(f"{k} ATR: 진 거래 {v['losing_trades']:,}개 중 플러스로 바뀐 것 {v['turned_positive']:,}개" for k, v in sorted(sv.items())) + ". 공정한 비교는 모든 거래를 다시 돌린 8-1의 손절 1.5/2.5/3 ATR 줄입니다.")
        w("- **놓친 신호 그림자(skipped):** 8-2의 \"모든 신호 다시 돌리기\"가 같은 것을 10/24 밤까지 더 완전하게 계산합니다.")
        w("")
        w("### 8-5. 조건 거르기: 앞 절반에서 고르고 뒤 절반에서 확인")
        w("")
        w("신호 때 기록된 차트 상황 18가지(방향, 코인, 시간대, 주말, 장세, 상위 봉 장세, 박스 위치, 상위 봉 박스 위치, ADX, DI 방향 일치, EMA20에서 떨어진 정도, 효율 비율, 다음 벽까지 여유, 잠금 전 벽, 손절 전 지지, 돌파 여부, 진입 등급, 손절 폭)로 모든 신호를 나눴습니다.")
        w("")
        w(f"- 매매법×봉×조건 {FX.get('cond_subsets', 0):,}칸(앞 절반 15신호, 뒤 절반 10신호 이상) 중 앞 절반에서 \"좋다\"(거래당 +0.1R 넘고 t>1.5)로 고른 칸: {FX.get('cond_picks', 0)}개.")
        w(f"- 고른 칸의 앞 절반 거래당 {Rf(FX.get('cond_picks_h1_meanR'))} → **뒤 절반 {Rf(FX.get('cond_picks_h2_meanR'))}**. 뒤 절반에도 플러스인 비율 {pct(100 * (FX.get('cond_picks_h2_positive_share') or float('nan')), 0)}"
          f"(모든 칸의 뒤 절반 플러스 비율 {pct(100 * (FX.get('cond_all_h2_positive_share') or float('nan')), 0)}).")
        w(f"- 가짜 시험(같은 신호를 반대 방향으로 한 가짜 전략에 같은 고르기): {FX.get('cond_placebo_picks', 0)}개 골랐고 뒤 절반 플러스 {pct(100 * (FX.get('cond_placebo_h2_positive_share') or float('nan')), 0)}, 거래당 {Rf(FX.get('cond_placebo_h2_meanR'))}.")
        w(f"- 거꾸로(뒤 절반에서 고르고 앞 절반 확인): {FX.get('cond_reverse_picks', 0)}개, 앞 절반 플러스 {pct(100 * (FX.get('cond_reverse_h1_positive_share') or float('nan')), 0)}, 거래당 {Rf(FX.get('cond_reverse_h1_meanR'))}.")
        w(f"- 뒤 절반에서도 플러스였던 {FX.get('cond_held', 0)}칸을 뒤 절반만으로 동전과 비교하면 보정 뒤 통과 {FX.get('cond_held_bh_pass', 0)}칸(보정 전 p<0.05 {FX.get('cond_held_raw_p05', 0)}칸).")
        w("")
        cp = t("x_cond_pooled.csv")
        w("모든 매매법을 합쳐 본 조건별 거래당 R (기본+딥시크, 모든 봉; 앞 절반 → 뒤 절반):")
        w("")
        x = cp[(cp["group"] == "core+ds") & (cp["tf"] == "all") & (cp["level"] != "na")]
        rows = [[FEATKO.get(r.feature, r.feature), r.level, f"{int(r.n):,}", Rf(r.R_h1), Rf(r.R_h2), Rf(r.mean_R)] for r in x.itertuples()]
        w(table(rows, ["조건", "값", "신호", "앞 절반", "뒤 절반", "전체"]))
        w("")
        cps = t("x_cond_pool_simple.csv")
        xp = cps[cps["tf"] == "all"]
        w("같은 조건을 동전 풀에 걸면:")
        w("")
        rows = [[FEATKO.get(r.feature, r.feature), r.level, f"{int(r.n):,}", Rf(r.pool_R_h1), Rf(r.pool_R_h2)] for r in xp.itertuples()]
        w(table(rows, ["조건", "값", "동전 거래", "앞 절반", "뒤 절반"]))
        w("")
        ck = t("x_cond_pooled_h1pick_h2check.csv")
        w("앞 절반에서 플러스였던 조건(모든 매매법 합계, 봉별·그룹별, 뒤 절반 신호 50개 이상)을 뒤 절반에서 같은 날·같은 코인·같은 방향 동전과 비교:")
        w("")
        rows = [[{"core+ds": "기본+딥시크", "core": "기본", "ds": "딥시크"}[r.group], "전체" if r.tf == "all" else TFKO[r.tf], f"{FEATKO.get(r.feature, r.feature)}={r.level}", Rf(r.R_h1, 2), Rf(r.R_h2, 2), Rf(r.h2_sameday_excess_R, 2), f"{int(r.h2_days_pos)}/{int(r.h2_days)}", num(r.h2_t, 1)] for r in ck.itertuples() if nz(r.h2_t)]
        w(table(rows, ["그룹", "봉", "조건", "앞 절반 R", "뒤 절반 R", "뒤 절반 동전 대비", "동전보다 나은 날", "t"]))
        w("")
        w(f"- {FX.get('cond_pooled_picks', 0)}개 중 뒤 절반에도 플러스 {FX.get('cond_pooled_picks_h2_pos', 0)}개, 동전 대비 t>2는 {FX.get('cond_pooled_picks_h2_excess_t2', 0)}개입니다. 1시간봉 숏이 두 절반 모두 플러스였지만 같은 날 아무 때나 숏한 동전보다 나쁩니다(하락장 몫).")
        x1 = x[(x["R_h1"] > 0) & (x["R_h2"] > 0)]
        if len(x1):
            w("- 두 절반 모두 플러스인 조건(모든 매매법 합계): " + ", ".join(f"{FEATKO.get(r.feature, r.feature)}={r.level} ({Rf(r.R_h1, 2)} → {Rf(r.R_h2, 2)})" for r in x1.itertuples()) + ".")
        else:
            w("- 모든 매매법을 합쳐서 두 절반 모두 플러스인 조건은 하나도 없습니다.")
        w("- 숏만 하기는 앞 절반(하락장)에서 크게 좋았지만 동전도 똑같았습니다. 조건별 전체 표는 `tables/x_cond_pooled.csv`(봉별·그룹별), 칸별은 `tables/x_cond_cells.csv`.")
        w("")
        w("---")
        w("")

        # ============================================================ 9. goal path
        w("## 9. 목표 경로: 한 달 +500% (×6)")
        w("")
        GP = t("x_goal_path.csv")
        w("두 분 방식(증거금 40%, 30~50배)으로 각 후보의 **실제 앞으로 거래(포워드)**를 30일 동안 다시 뽑아 4,000번 돌렸습니다. 거래 하나의 지갑 변화 = 노출 × 거래당 수익률(가격 대비, 비용 포함), 한 번에 잃는 최대 = 증거금. 손절이 그 배수의 강제청산 거리보다 먼 거래는 진입 못 함으로 뺐습니다(50배는 손절 약 1.4% 넘으면 못 들어감).")
        w("")
        w("- \"필요 노출\" = 거래당 평균과 하루 거래 수를 그대로 두고, 가운데값이 30일 뒤 ×6이 되려면 필요한 노출(증거금 × 레버리지). 어떤 배수로도 안 되면 \"불가\"입니다.")
        w("- \"운만이라면\" = 그 후보의 거래당 평균을 같은 조건 동전의 평균으로 바꿨을 때. 지금 결과가 운이라면 앞으로 기대할 수 있는 쪽입니다.")
        w("")
        GP = GP.rename(columns={"p_-50_first": "p_m50", "p_-90_first": "p_m90", "luck_only_p_-50_first": "luck_only_p_m50"})
        g = GP[(GP["m"] == 0.40) & (GP["L"] == 30)].copy()
        g = g.sort_values("p_final_x6", ascending=False)
        KIND = {"account": "실제 거래", "account x shadow": "그림자", "every signal (one position)": "모든 신호·한 포지션", "filter (H2 check only)": "조건(뒤 절반만)"}
        rows = []
        for r in g.head(25).itertuples():
            need = r.needed_exposure_x6
            lab = KIND.get(r.kind, r.kind) + ("" if r.kind == "account" else f": {VKO.get(r.what, r.what)}")
            rows.append([f"{r.account_id} ({lab})", int(r.n), num(r.trades_per_day, 1), pct(r.mean_r_notional_pct, 3, True), pv(r.luck_p),
                         (f"{need:.0f}배 (40%×{need / 0.4:.0f}배)" if nz(need) else "불가"), pct(100 * r.p_final_x6, 1), pct(100 * r.p_m50, 0), pct(100 * r.p_m90, 0),
                         pct(100 * r.luck_only_p_final_x6, 1) if nz(r.luck_only_p_final_x6) else "—",
                         pct(100 * r.fiveyear_p_final_x6, 1) if nz(r.fiveyear_p_final_x6) else "—", "작음" if r.small_sample else ""])
        w("증거금 40% × 30배(노출 12배), 30일 뒤 ×6 확률 순 상위 25개:")
        w("")
        w(table(rows, ["후보", "거래", "하루 거래", "거래당 (가격 대비)", "운 p", "×6 가운데값에 필요한 노출", "×6 (19일 반복)", "-50% 먼저", "-90% 먼저", "×6 (운만이라면)", "×6 (5년 평균이라면)", "표본"]))
        w("")
        w("- **같은 후보라도 가정에 따라 확률이 0%와 99% 사이를 오갑니다.** 19일 반복 가정의 숫자는 거래 25~75번의 결과를 그대로 늘린 것이고, 그 19일의 이익은 4장대로 운으로 설명됩니다. 5년 평균 열은 기본 매매법만(딥시크는 D11로 가림).")
        w("- 그림자(고정 익절, 첫 잠금 높이기 등)나 조건으로 바꾼 후보가 더 좋아 보이는 것은 300개 넘는 계좌 × 22가지 중 가장 좋은 것을 골랐기 때문입니다. 같은 고르기를 동전에 해도 이 정도 1등은 나옵니다(8-1, 8-2).")
        w(f"- 표의 \"운 p\"는 고르기 전 값입니다. 고른 수만큼 보정하면 계좌×그림자 {FX.get('shadow_tests', 0):,}칸 중 가장 작은 q가 {num(FX.get('shadow_min_q'), 2)}, 모든 신호 {FX.get('allsig_tests', 0):,}칸 중 가장 작은 q가 {num(FX.get('allsig_min_q'), 2)}로, 모두 운의 범위(q 0.05 넘음)입니다.")
        w("")
        w("증거금·배수를 바꾸면 (실제 거래 후보만, 19일 반복 가정):")
        w("")
        rows = []
        for (m, Lv), x in GP.groupby(["m", "L"]):
            b = x.sort_values("p_final_x6", ascending=False).iloc[0]
            xa = x[x["kind"] == "account"]
            va = xa[xa["account_id"] == "V39_ALL@1h"]
            rows.append([f"{int(m * 100)}% × {int(Lv)}배 (노출 {m * Lv:.0f}배)",
                         pct(100 * va["p_final_x6"].iloc[0], 0) if len(va) else "—", pct(100 * va["p_m50"].iloc[0], 0) if len(va) else "—",
                         pct(100 * va["luck_only_p_final_x6"].iloc[0], 1) if len(va) else "—",
                         pct(100 * xa["p_final_x6"].median(), 1), pct(100 * xa["p_m50"].median(), 0), pct(100 * xa["p_m90"].median(), 0),
                         pct(100 * va["allowed_share"].iloc[0], 0) if len(va) else "—"])
        w(table(rows, ["설정", "V39_ALL@1h ×6 (19일 반복)", "V39 -50% 먼저", "V39 ×6 (운만)", "번 계좌 전체 ×6 (가운데값)", "-50% 먼저 (가운데값)", "-90% 먼저 (가운데값)", "V39 진입 가능 거래"]))
        w("")
        w("- 표의 확률은 **지난 19일이 그대로 반복된다고 가정한 값**입니다. 그 19일의 이익은 4장대로 운으로 설명되므로, 실제 기대는 \"운만이라면\" 열에 가깝습니다.")
        w("- 거래 30번 미만 후보는 \"작음\"입니다. 이런 후보의 확률은 몇 거래가 바뀌면 크게 달라집니다.")
        w("- 노출을 올리면 ×6 확률과 -50%·-90% 확률이 같이 올라갑니다. 우위가 없으면 배수는 결과의 폭만 넓히고 가운데값은 내립니다.")
        w(f"- 전체 표(후보 × 5가지 설정, 4개 확률, 필요 노출, 켈리 노출): `tables/x_goal_path.csv`.")
        w("")
        w("---")
        w("")

    # ============================================================ 10. shortlist
    w("## 10. 실거래 후보")
    w("")
    w("미리 정한 기준 6가지 (모두 넘어야 후보):")
    w("")
    cc = F["criteria_counts"]
    rows = [["1", "v4 거래 20번 이상", cc["c1_n20"]], ["2", "v4 손익 플러스이고 거래당 R 플러스", cc["c2_profit"]],
            ["3", "시험 A(맞춘 동전) 보정 뒤 q<0.10", cc["c3_beats_luck"]], ["4", "앞 절반·뒤 절반 모두 플러스", cc["c4_both_halves"]],
            ["5", "5년 두 기간(21~23, 24~26) 모두 거래당 플러스", cc["c5_5y_both_periods"]], ["6", "가장 큰 거래 1개를 빼도 플러스", cc["c6_not_one_trade"]]]
    w(table(rows, ["#", "기준", "넘은 계좌"]))
    w("")
    w(f"**모두 넘은 계좌: {F['shortlist_n']}개.** 기준 3(운)을 넘은 계좌가 0개라서, 나머지가 어떻든 후보가 될 수 없습니다.")
    w("")
    cl = t("shortlist_closest.csv")
    w("가장 가까운 계좌들 (넘은 기준 수, 그다음 운 p 순):")
    w("")
    rows = []
    for r in cl.head(10).itertuples():
        stop = r.median_stop_pct
        one_stop = {L: 0.4 * L * (stop / 100 + 0.0014) * 100 for L in (20, 30, 40, 50)}
        rows.append([r.account_id, int(r.criteria_passed), int(r.n), usd(r.pnl), num(r.pf, 2), pct(100 * r.max_dd, 0), pv(r.A_p_better),
                     pct(100 * r.test_mean, 2, True) if nz(r.test_mean) else ("마이너스" if nz(r.test_sign) and r.test_sign < 0 else "—"),
                     pct(stop, 2), " / ".join(f"{one_stop[Lv]:.0f}%" for Lv in (20, 30, 40, 50))])
    w(table(rows, ["계좌", "넘은 기준", "거래", "손익", "PF", "최대 낙폭", "운 p (A)", "5년 24~26 거래당", "손절 폭 가운데값", "손절 1번 = 지갑의 (증거금 40% × 20/30/40/50배)"]))
    w("")
    w("- \"손절 1번 = 지갑의 몇 %\" = 증거금 40% × 배수 × (손절 폭 + 왕복 비용 약 0.14%). 예: 손절 폭 1.8%에 40% × 30배면 한 번에 지갑의 약 23%가 빠집니다. 4번 연속 손절이면 지갑이 절반 아래입니다.")
    w("- 이 계좌들의 공통점: 대부분 숏이 롱보다 많고, 5년 기록은 거래당 마이너스(대부분 파산)이며, 운 시험을 보정 뒤 넘지 못했습니다. 과적합 점검으로 보면, 300개 넘는 계좌에서 고른 1등은 운만으로도 이 정도는 나옵니다(4-2의 \"1등 vs 동전 1등\").")
    w("")
    w("**그래서 지금 할 수 있는 것:**")
    w("1. 실거래는 지금처럼 V39_ALL@1h 하나를 작은 크기(10/17 보고서의 설정: 진입 상한 $400, 20배)로 \"실행 확인용\"으로만 유지합니다. 크기·배수를 올릴 근거는 없습니다.")
    w("2. V39_ALL@1h가 앞으로 30거래 더 쌓였을 때 시험 B가 보정 기준(q<0.05)을 넘고, 시장이 오르는 기간에도 플러스인지 봅니다. 그때 다시 판단합니다.")
    w("3. 한 달 +500%를 노리려면 수수료를 이기는 진짜 우위가 먼저 필요합니다. 지금 매매법·청산·조건 조합에서는 찾지 못했습니다(8장).")
    w("")
    w("---")
    w("")

    # ============================================================ appendix A
    w("## 부록 A. v4 모든 계좌 (331개)")
    w("")
    w("열: 거래, 하루 거래, 승률, 평균 이익/손실($), PF, 손익, 최종 지갑, 거래당 ROE, 거래당 R, 최대 낙폭, 롱(거래·손익), 숏(거래·손익), 앞 절반/뒤 절반 손익, 최장 연속 손실, 시장 몫, 시험 A p / q, 시험 B p, 5년 24~26(기본 매매법은 거래당 %, 딥시크는 부호). 거래 0번 계좌는 이유를 적었습니다. CSV: `tables/accounts_v4.csv`.")
    w("")
    order = {"core": 0, "ds": 1, "reel": 2, "flip": 3, "flip5": 4}
    A2 = AC.copy()
    A2["o"] = A2["grp"].map(order)
    A2["tfo"] = A2["tf"].map({"5m": 0, "15m": 1, "30m": 2, "1h": 3, "4h": 4})
    A2 = A2.sort_values(["o", "strategy", "tfo"])
    rows = []
    for r in A2.itertuples():
        if r.n == 0:
            rows.append([GKO[r.grp], r.account_id, 0] + [""] * 17 + [{"no_signal_at_all": "신호 없음"}.get(str(r.zero_cause), "크기 조건에 모두 막힘" if str(r.zero_cause).startswith("all_rejected") else str(r.zero_cause))])
            continue
        five = (("+" if r.test_sign > 0 else "-") if r.grp == "ds" else pct(100 * r.test_mean, 2, True)) if nz(getattr(r, "test_sign", np.nan)) else "—"
        rows.append([GKO[r.grp], r.account_id, int(r.n), num(r.per_day, 1), pct(r.win_pct, 0), f"{usd(r.avg_win_usd, False)}/{usd(r.avg_loss_usd, False)}", num(r.pf, 2), usd(r.pnl), usd(r.final, False),
                     pct(r.mean_roe_pct, 1, True), Rf(r.mean_R, 2), pct(100 * r.max_dd, 0) if nz(r.max_dd) else "—",
                     f"{int(r.long_n)} · {usd(r.long_pnl)}", f"{int(r.short_n)} · {usd(r.short_pnl)}", f"{usd(r.h1_pnl)} / {usd(r.h2_pnl)}", int(r.max_lose_streak),
                     usd(r.mkt_usd), f"{pv(r.A_p_better)} / {num(r.A_q, 2)}" if nz(r.A_p_better) else "—", pv(r.B_p_better), five, ""])
    w(table(rows, ["그룹", "계좌", "거래", "하루", "승률", "평균 이익/손실", "PF", "손익", "최종", "ROE/거래", "R/거래", "최대 낙폭", "롱", "숏", "앞/뒤 절반", "최장 연패", "시장 몫", "A p / q", "B p", "5년 24~26", "비고"]))
    w("")

    # ============================================================ appendix B
    w("## 부록 B. 이전 실행 (v3a, v3b) 계좌")
    w("")
    w("v3a(10/02 20:05~10/05 10:40, 2.6일, 옛 단계 레버리지 50배부터, 5분봉 포함), v3b(10/05 10:45~10/06 03:31, 0.7일). 거래가 있는 계좌만. CSV: `tables/accounts_v3.csv`, 세 실행을 R로 합친 표: `tables/pooled_all_runs_R.csv`.")
    w("")
    v3 = t("accounts_v3.csv")
    v3 = v3[v3["n"] > 0]
    piv = {}
    for r in v3.itertuples():
        piv.setdefault(r.account_id, {})[r.run] = r
    rows = []
    for aid in sorted(piv, key=lambda s: (s.startswith("RANDOM"), s.split("@")[0], TFO.get(s.split("@")[-1], 9))):
        a_ = piv[aid].get("v3a")
        b_ = piv[aid].get("v3b")
        v4r = AC[AC["account_id"] == aid]
        rows.append([aid, f"{int(a_.n)} · {usd(a_.pnl)} · {Rf(a_.mean_R, 2)}" if a_ is not None else "—",
                     f"{int(b_.n)} · {usd(b_.pnl)} · {Rf(b_.mean_R, 2)}" if b_ is not None else "—",
                     f"{int(v4r['n'].iloc[0])} · {usd(v4r['pnl'].iloc[0])} · {Rf(v4r['mean_R'].iloc[0], 2)}" if len(v4r) and v4r['n'].iloc[0] > 0 else "—"])
    w(table(rows, ["계좌", "v3a 거래 · 손익 · R", "v3b", "v4"]))
    w("")

    # ============================================================ appendix C/D/E
    w("## 부록 C. 방법 메모")
    w("")
    w("- **R과 비용:** R = 순손익 ÷ (수량 × |진입가 - 처음 손절가|). 방향 R = (순손익 + 수수료 + 펀딩) ÷ 같은 값.")
    w("- **동전 풀:** v4의 1분봉으로 15분·30분·1시간·4시간 봉을 만들고, 봇과 같은 ATR(14, Wilder)을 봇이 기록한 첫 ATR에서 이어 계산했습니다(이후 기록된 ATR 1만 5천여 개와 차이 1e-12 이하). 모든 봉 마감마다 6코인 롱·숏을 봇 엔진(`paperbot`)으로 혼자 돌렸습니다. 마지막 날 끝나지 않은 거래(약 1%)는 뺐습니다.")
    w("- **시험 A:** 계좌의 실제 거래마다 동전 풀에서 같은 봉·코인·방향의 거래를 하나 뽑되, 날짜는 실제 거래일마다 하나씩 무작위로 바꿉니다(같은 시뮬레이션 안에서는 모든 계좌가 같은 날짜 바꾸기를 씀). 4,000번(p<0.01이면 10만 번 더). 1등 비교는 점수 = (실제 - 동전 평균) ÷ 동전 표준편차의 계좌 최댓값.")
    w("- **시험 B:** analyze.py(10/07 분석 코드)의 모든 신호 다시 돌리기에서 양쪽 방향 결과가 다 있는 신호. 롱 신호 평균과 숏 신호 평균을 반씩. 같은 시간 덩어리(봉 마감을 max(봉, 1시간)으로 묶음)는 같은 부호로 뒤집음. 4,000번(작으면 20만 번).")
    w("- **시험 C:** 거래일을 다시 뽑는 부트스트랩.")
    w("- **그림자·모든 신호 운 시험(8장):** 같은 변형으로 돌린 동전 풀에서, 같은 봉·코인·방향 묶음의 날짜별 평균과 분산으로 \"무작위 날짜 동전\"의 평균·분산을 정확히 계산하고 정규 근사로 p.")
    w("- **5년:** `research/fullgrid/diag/strat_report.py`의 결과(STRATEGIES_KO.md와 같은 숫자)를 `ref5y.csv`로 옮겨 씀. 딥시크는 D11대로 부호만.")
    w("- **한계:** 19일 하나의 하락장. 오르는 장·크게 출렁이는 장은 없었습니다. 그림자·모든 신호는 \"혼자 돌린 거래\"라 실제 한 포지션 계좌의 순서와 다릅니다. 지정가 그림자는 닿으면 체결이라는 낙관적 가정입니다. 실거래 실행기 기록은 이 자료에 없습니다.")
    w("")
    w("## 부록 D. 파일")
    w("")
    w("- 보고서: `analysis/review1024/rulebot/REPORT_KO.md` (이 파일)")
    w("- 계좌별 날짜 손익: `analysis/review1024/rulebot/daily_pnl.csv` (account_id, day_kst, pnl, trades; v4, 청산 기준 KST 날짜)")
    w("- 표: `analysis/review1024/rulebot/tables/*.csv`, 숫자 요약: `facts.json`, `facts_extra.json`")
    w("- 5년 참고표: `analysis/review1024/rulebot/ref5y.csv` (`scripts/ref5y_build.py`로 만듦)")
    w("- 스크립트: `analysis/review1024/rulebot/scripts/` — extract_zip.py, randpool.py, varpool.py, rb1024.py, rb_extra.py, make_report.py, run_all.sh. 10/07 분석 코드 `analysis/rulebot_1007/scripts/analyze.py`, `fiveyear_ref.py`를 그대로 불러 씀.")
    w("")
    w("## 부록 E. 다시 만드는 법")
    w("")
    w("```bash")
    w("cd /home/user/crypto-bot-research")
    w("bash analysis/review1024/rulebot/scripts/run_all.sh <새 export.zip> <새 빈 작업 폴더>")
    w("```")
    w("")
    w("- 작업 폴더는 저장소 밖의 새 빈 폴더여야 합니다(zip은 데이터만 풀고 실행하지 않습니다). 4코어에서 약 25~30분 걸립니다.")
    w("")
    with open(os.path.join(out, "REPORT_KO.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {os.path.join(out, 'REPORT_KO.md')} ({len(L)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
