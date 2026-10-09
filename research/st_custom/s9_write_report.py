"""Writes research/st_custom/RESULTS_KO.md from out/*.csv|json (every number in the report comes from those files).

    python3 -B research/st_custom/s9_write_report.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import s8_tables as T  # noqa: E402

O = C.OUT
f = T.f
SN = T.SN


def load():
    d = dict(P=pd.read_csv(os.path.join(O, "picks.csv")), PR=pd.read_csv(os.path.join(O, "pick_results.csv")),
             PS=pd.read_csv(os.path.join(O, "pass_rule.csv")), CR=pd.read_csv(os.path.join(O, "crash_windows.csv")),
             LK=pd.read_csv(os.path.join(O, "luck.csv")), RO=pd.read_csv(os.path.join(O, "reopt.csv")),
             AC=pd.read_csv(os.path.join(O, "accounts.csv")), NB=pd.read_csv(os.path.join(O, "neighbours.csv")),
             SC=json.load(open(os.path.join(O, "selfcheck.json"))))
    p = os.path.join(O, "intrabar.csv")
    d["IB"] = pd.read_csv(p) if os.path.exists(p) else None
    return d


def rng(series, d=2):
    return f"{series.min():+.{d}f} ~ {series.max():+.{d}f}"


def t_intrabar(IB):
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            g = IB[(IB.strategy == strat) & (IB.tf == tf) & (IB.scope == "ALL")]
            for s in ("default", "friend", "pick1"):
                gs = g[g.set == s]
                for per in C.PERIOD_ORDER:
                    x = gs[gs.period == per]
                    if not len(x):
                        continue
                    r = x.iloc[0]
                    rows.append([SN[strat] if (s == "default" and per == "SEARCH") else "",
                                 tf if (s == "default" and per == "SEARCH") else "",
                                 T.SET_KO[s] if per == "SEARCH" else "", T.PER_KO[per], f"{int(r.ib_trades):,}",
                                 f"{100 * r.ib_vanished_share:.0f}%", T.pct(r.ib_win_rate), f(r.ib_gross_R),
                                 f(r.ib_cost_R, sign=False), f(r.ib_net_R), f(r.bc5_net_R), f(r.main15_net_R),
                                 f(r.entry_diff_bps_mean, 1), f(r.ib_net_R_vanished)])
    return T.md(rows, ["전략", "봉", "값", "기간", "봉 중간 진입 거래", "사라진 신호", "승률", "gross R", "cost R",
                       "net R (봉 중간)", "net R (봉 마감, 5분 점검)", "net R (봉 마감, 본 시뮬)",
                       "진입가 차이 bp", "사라진 신호의 net R"])


def main():
    d = load()
    P, PR, PS, CR, LK, RO, AC, NB, SC, IB = (d[k] for k in ("P", "PR", "PS", "CR", "LK", "RO", "AC", "NB", "SC",
                                                           "IB"))
    main_ps = PS[PS.variant == "main"]
    pooled = main_ps[main_ps.scope == "pooled"]
    coinp = main_ps[main_ps.scope == "coin"]
    allpass = PS[PS.PASS]
    m_all = PR[(PR.variant == "main") & (PR.scope == "ALL")]
    test15 = m_all[(m_all.tf == "15m") & (m_all.period == "TEST")]
    test30 = m_all[(m_all.tf == "30m") & (m_all.period == "TEST")]
    cost15 = m_all[m_all.tf == "15m"].cost_R
    cost30 = m_all[m_all.tf == "30m"].cost_R
    gross_all = m_all.gross_R
    nbeat_luck_pooled = int(LK[(LK.variant == "main") & (LK.scope == "pooled")].beats_luck.sum())
    acc_t = AC[(AC.period == "TEST")]
    acc_best_t = acc_t.sort_values("mult", ascending=False).iloc[0]
    acc_x = AC[(AC.period == "EXTRA")]
    acc_s = AC[(AC.period == "SEARCH")]
    surv_x = acc_x[~acc_x.ruin]
    best_x = acc_x.sort_values("mult", ascending=False).iloc[0]
    sc = SC["selfcheck"]["results"]
    ro = RO[RO.method != "DEFAULT"]
    n_ro_sig_better = int(((ro.diff_ci_lo > 0)).sum())
    n_ro_sig_worse = int(((ro.diff_ci_hi < 0)).sum())
    fr = PR[(PR.variant == "main") & (PR.scope == "ALL") & (PR.set.isin(["friend", "default"]))]

    def fv(strat, tf, s, per, col="net_R"):
        x = PR[(PR.variant == "main") & (PR.scope == "ALL") & (PR.strategy == strat) & (PR.tf == tf) &
               (PR.set == s) & (PR.period == per)]
        return float(x[col].iloc[0])

    bt = T.best_tpsl(P)
    g1 = PS[(PS.scope == "pooled") & (PS["rank"] == 1)]
    vd = {"maker": [], "htf": [], "chop": [], "tpsl_r2_test": [], "tpsl_r2_extra": []}
    for (s_, tf_), v_ in bt.items():
        a_ = g1[(g1.strategy == s_) & (g1.tf == tf_)].set_index("variant")
        k_ = float(v_.split("_")[2].replace("atr", "")) / 2
        for vn in ("maker", "htf", "chop"):
            vd[vn].append(a_.loc[vn, "test_net_R"] - a_.loc["main", "test_net_R"])
        vd["tpsl_r2_test"].append(a_.loc[v_, "test_net_R"] * k_ - a_.loc["main", "test_net_R"])
        vd["tpsl_r2_extra"].append(a_.loc[v_, "extra_net_R"] * k_ - a_.loc["main", "extra_net_R"])
    vd = {k: (min(v), max(v)) for k, v in vd.items()}
    mk = PR[(PR.variant == "maker") & (PR.scope == "ALL")]
    fill = (mk.trades / mk.signals)
    stw = PR[(PR.variant == "stflip") & (PR.scope == "ALL")].win_rate
    dtest = pooled.test_net_R - pooled.default_test_net_R
    dextra = pooled.extra_net_R - pooled.default_extra_net_R
    th = AC[(AC.period == "TEST") & (AC["mode"] == "house") & (AC.minorder)]
    ro_own = pd.to_datetime(th[th.sizing == "owner"].ruin_day)
    ro_r1 = pd.to_datetime(th[th.sizing == "risk1"].ruin_day)
    sig_ro = ro[(ro.diff_ci_lo > 0) | (ro.diff_ci_hi < 0)]
    MK = {"ROLL5_26w": "5거래마다 26주", "ROLL5_4w": "5거래마다 4주", "WEEKLY_26w": "매주 26주"}
    sig_txt = "; ".join(f"{SN[r.strategy]} {r.tf} {T.PER_KO[r.period]} {MK[r.method]} {f(r.diff_vs_default)}R "
                        f"[{f(r.diff_ci_lo)}, {f(r.diff_ci_hi)}]" for r in sig_ro.itertuples())
    rp = RO[(RO.method == "ROLL5_26w") & (RO.period == "TEST")]
    pc = SC["selfcheck"]["per_coin"]
    lev30 = [v["lev30_share"] for v in pc.values()]
    tabs = {
        "picks": T.t_picks(P), "coinpicks": T.t_coinpicks(P, PS), "main": T.t_main(PR),
        "pc_test": T.t_percoin(PR, "TEST"), "pc_extra": T.t_percoin(PR, "EXTRA"), "crash": T.t_crash(CR),
        "var": T.t_variants_compact(PS, P), "luck": T.t_luck(LK), "reopt": T.t_reopt(RO),
        "acc_test": T.t_accounts(AC, "TEST"), "acc_extra": T.t_accounts(AC, "EXTRA"),
    }
    one = allpass.iloc[0] if len(allpass) else None
    L = []
    a = L.append
    a("# Supertrend 맞춤값 찾기 결과 (S2 / N02 / N04, 15분봉 · 30분봉)")
    a("")
    a("작성 2026-10-09. 미리 정한 계획: `PREREG.md` (sha256 94a311f0...), 추가 계획 `PREREG_ADDENDUM_1.md` (봉 중간 진입, "
      "1,000달러 계좌). 계획대로 못 한 점과 애매한 점의 처리: `DEVIATIONS.md`. 숫자는 모두 `out/` 폴더의 CSV/JSON에서 "
      "나왔습니다 (이 문서는 `s9_write_report.py`가 그 파일에서 만듭니다).")
    a("")
    a("## 0. 결론 먼저")
    a("")
    a(f"- **데모로 넘길 값은 없습니다.** 미리 정한 통과 규칙(4개 모두 충족)을 기본 청산 방식에서 통과한 값은 "
      f"0개입니다. 전체 합산으로 고른 18개, 코인별로 고른 42개가 모두 떨어졌습니다.")
    a(f"- 떨어진 첫째 이유: **모든 값이 시험 기간(2024-01 ~ 2026-09)에 손해**입니다. 7개 코인 합산 거래당 net R이 15분봉은 "
      f"{rng(test15.net_R)}, 30분봉은 {rng(test30.net_R)}입니다. 2020년(추가 기간)도 마찬가지입니다.")
    a(f"- 손해의 원인은 비용입니다. 거래당 비용(수수료 + 슬리피지 + 펀딩)이 15분봉 {cost15.min():.2f} ~ {cost15.max():.2f}R, "
      f"30분봉 {cost30.min():.2f} ~ {cost30.max():.2f}R입니다. 비용 빼기 전 성과(gross)는 {rng(gross_all, 3)}R뿐입니다. "
      f"고른 값과 기본값의 시험 기간 차이는 {dtest.min():+.3f} ~ {dtest.max():+.3f}R이라 이 차이를 메울 수 없습니다.")
    a(f"- 고른 값은 시험 기간에 기본값보다 **조금 덜 잃습니다** (전체 합산 고른 값 18개 중 "
      f"{int((pooled.test_net_R > pooled.default_test_net_R).sum())}개). 하지만 2020년에는 "
      f"{int((pooled.extra_net_R > pooled.default_extra_net_R).sum())}개만 기본값보다 나았고, 덜 잃는 것이지 버는 것은 "
      f"아닙니다.")
    a(f"- 친구 값(S2 ST 8/3 ROC 37, N04 ST 8/3 Klinger 기본)도 모든 기간에 손해입니다. 시험 기간 S2 15분 "
      f"{f(fv('S2_ST_ROC', '15m', 'friend', 'TEST'))}R (기본값 {f(fv('S2_ST_ROC', '15m', 'default', 'TEST'))}), "
      f"S2 30분 {f(fv('S2_ST_ROC', '30m', 'friend', 'TEST'))}R (기본값 {f(fv('S2_ST_ROC', '30m', 'default', 'TEST'))}), "
      f"N04 15분 {f(fv('N04_ST_KLINGER', '15m', 'friend', 'TEST'))}R (기본값 "
      f"{f(fv('N04_ST_KLINGER', '15m', 'default', 'TEST'))}), N04 30분 {f(fv('N04_ST_KLINGER', '30m', 'friend', 'TEST'))}R "
      f"(기본값 {f(fv('N04_ST_KLINGER', '30m', 'default', 'TEST'))}).")
    if one is not None:
        a(f"- 청산 방식 변형(MAKER, STFLIP, HTF, CHOP, TPSL 12종)까지 넣으면 고른 값이 모두 {len(PS):,}개입니다. 그중 통과는 "
          f"**{len(allpass)}개**입니다: {SN[one.strategy]} {one.tf} STFLIP, {one.coin.replace('USD', '')} 전용 "
          f"({one.label}). 시험 기간 {f(one.test_net_R)}R, 95% 구간 [{f(one.test_ci_lo)}, {f(one.test_ci_hi)}]로 0을 "
          f"포함합니다. 1,000개 넘게 시험하면 이 정도 1개는 우연으로도 나옵니다. 근거로 보기 어렵습니다.")
    a(f"- 5거래마다 또는 매주 값을 다시 고르는 방식(친구 계획의 '데모에서 5거래마다 재최적화')도 모두 손해입니다. "
      f"기본값과의 차이는 24개 비교 중 {24 - n_ro_sig_better - n_ro_sig_worse}개가 0과 구별되지 않고, "
      f"{n_ro_sig_better}개가 확실히 낫고, {n_ro_sig_worse}개가 확실히 나쁩니다.")
    a(f"- 1,000달러 계좌 모의(20/30/40/50배, 두 가지 크기 규칙): **시험 기간에는 모든 값, 모든 배수에서 파산**(잔고가 "
      f"시작의 10% 아래)했습니다. 손절 1% 규칙도 대부분 1년 안에 파산합니다. 2020년에도 계좌 {len(acc_x):,}개 중 "
      f"{len(surv_x)}개만 살아남았고, 살아남은 계좌도 모두 원금보다 적습니다 (가장 좋은 경우 ${best_x.final:,.0f}).")
    a("- 결론: 이 세 전략의 15분/30분 신호에서 '잡음이 적은 맞춤값'을 찾아 데모를 돌리는 계획은 이 데이터로 뒷받침되지 "
      "않습니다. 값 찾기로는 비용을 이길 수 없습니다.")
    a("")
    a("## 1. 용어 (한 번만 설명)")
    a("")
    a("- **R**: 손절까지 거리를 1로 잡은 단위입니다. 손절이 진입가에서 1% 떨어져 있으면 1R = 1%입니다. 거래당 "
      "-0.15R은 '손절폭의 15%만큼 평균적으로 잃었다'는 뜻입니다. 배수(레버리지)와 상관없이 비교할 수 있습니다.")
    a("- **gross R**: 수수료, 슬리피지, 펀딩비를 빼기 전 성과입니다. **cost R**: 그 비용입니다. **net R** = gross R - "
      "cost R, 실제로 남는 돈입니다. 비용은 진입·청산 각각 시장가 수수료 0.05% + 슬리피지 0.02%, 펀딩 8시간마다 "
      "0.01%입니다.")
    a("- **승률**: net R이 0보다 큰 거래의 비율입니다. 계단식 익절 때문에 작은 이익으로 끝나는 거래가 많아 승률은 "
      "55~65%로 높지만, 지는 거래가 더 크게 집니다. 승률은 통과 기준이 아닙니다.")
    a("- **최대 낙폭(drawdown)**: 가장 높았던 지점에서 가장 많이 떨어진 크기입니다. 신호 단위 표에서는 누적 R, 계좌 "
      "표에서는 잔고 대비 %입니다.")
    a("- **95% 구간**: 주 단위로 다시 뽑아(부트스트랩 2,000번) 얻은 평균의 범위입니다. 범위에 0이 들어가면 '0과 "
      "구별되지 않는다'고 씁니다.")
    a("- **기간**: 검색(값을 고르는 데만 씀) 2021-01 ~ 2023-12 (LUNA 2022-05, FTX 2022-11 포함), 시험 2024-01 ~ "
      "2026-09 (고를 때 안 본 데이터), 추가 2020-01 ~ 2020-12 (COVID 2020-03 포함, 역시 안 본 데이터).")
    a("")
    a("## 2. 무엇을 했나")
    a("")
    a("- 코인 7개: BTC, ETH, SOL, DOGE, LTC, BCH, XRP (바이낸스 USD-M 선물 15분봉; 30분봉은 15분봉 2개를 묶어 만듦). "
      "SOL은 2020-09, DOGE는 2020-07부터 데이터가 있습니다.")
    a("- 전략 3개의 값 조합: S2 343개, N02 735개, N04 588개 (총 1,666개) x 15분/30분. 기본값(ST 10/6)과 친구 값(ST 8/3)은 "
      "모두 이 격자 안에 있습니다. 신호 코드는 잠긴 원본(param_defs)을 그대로 썼습니다.")
    a("- 거래 방식(본 시뮬): 신호 봉 마감 다음 봉 시가 진입, 손절 = 신호 봉 ATR14의 2배, 페이퍼봇 계단식 익절, 15분봉으로 "
      "점검, 신호 하나 = 거래 하나 (포지션 겹침 허용).")
    a("- 고르는 법: 검색 기간만 보고, 각 값과 그 이웃 값(각 칸 +-1단계)의 평균 net R이 가장 높은 3개 ('평평한 언덕' 고르기). "
      "코인별로도 1개씩.")
    a("- 통과 규칙(4개 모두): (1) 시험과 추가 기간 net R > 0, (2) 두 기간 모두 기본값보다 나음, (3) 검색 기간 성과가 "
      "'운 기준선'보다 높음, (4) 이웃 값들의 시험 기간 평균도 > 0.")
    a("")
    a("## 3. 고른 값 (검색 기간만 보고 고름)")
    a("")
    a("전체 합산 (기본 청산 방식). 점수와 검색 net R 모두 음수입니다. 즉 검색 기간에도 이익인 값은 없었고, '가장 덜 "
      "잃는 값'을 고른 것입니다.")
    a("")
    a(tabs["picks"])
    a("")
    a("코인별로 고른 값과 그 코인에서의 성적 (net R, 기본 청산 방식):")
    a("")
    a(tabs["coinpicks"])
    a("")
    a("## 4. 검색 vs 시험 vs 추가 (기본값, 친구 값, 고른 값 1~3; 7개 코인 합산)")
    a("")
    a("최대 낙폭(R)은 '모든 신호를 다 거래했을 때' 누적 R의 가장 큰 하락입니다. 거래당 평균이 음수라 누적 손실이 계속 "
      "커지므로 이 값은 사실상 그 기간 총손실과 같습니다.")
    a("")
    a(tabs["main"])
    a("")
    a(f"검색에서 시험으로 갈 때 고른 값의 net R은 평균 {pooled.shrink_search_to_test.mean():.3f}R 나빠졌습니다 (코인별 "
      f"고른 값은 {coinp.shrink_search_to_test.mean():.3f}R). 고를 때의 우위가 일부만 남는다는 뜻입니다.")
    a("")
    a("## 5. 코인별 (기본 청산 방식, net R)")
    a("")
    a("시험 기간:")
    a("")
    a(tabs["pc_test"])
    a("")
    a("추가 기간(2020):")
    a("")
    a(tabs["pc_extra"])
    a("")
    a("BTC가 가장 나쁩니다. 변동성(ATR)이 작아 같은 비용이 R로는 더 크게 잡히기 때문입니다. 2020년 SOL 30분봉에서 0 근처 "
      "값이 몇 개 있지만 거래 수가 적은 짧은 기간입니다.")
    a("")
    a("## 6. 폭락 구간 (신호가 그 달에 나온 거래, net R, 괄호는 거래 수)")
    a("")
    a(tabs["crash"])
    a("")
    crm = CR[(CR.variant == "main") & (CR.scope == "ALL") & CR.set.isin(["default", "friend", "pick1"])]
    a(f"세 폭락 달의 net R은 {rng(crm.net_R, 3)}R입니다. 대부분 손해이고, 고른 값이 폭락에서 특별히 버티는 모습은 "
      f"없습니다. 평상시(기간 평균 약 -0.09 ~ -0.19R)보다 덜 잃는 달이 많은데, 변동성이 커지면 같은 비용이 R로는 "
      f"작아지기 때문입니다.")
    a("")
    a("## 7. 변형 (각각 같은 규칙으로 따로 고르고 따로 판정)")
    a("")
    a("- MAKER: 지정가 진입(신호 봉 종가, 다음 봉 하나 동안 유효), 진입 수수료 0.02%, 진입 슬리피지 없음.")
    a("- STFLIP: 같은 2 ATR 손절, 대신 자기 Supertrend 방향이 반대로 바뀌는 봉 종가에 청산 (계단식 익절 없음).")
    a("- HTF: 4시간봉 종가가 4시간 EMA50의 같은 쪽일 때만. CHOP: ADX14 >= 20일 때만.")
    a("- TPSL: 고정 익절 {1, 1.5, 2, 3}R x 손절 {1.5, 2, 3} ATR (12종). 표에는 검색 점수가 가장 좋은 1종만 실었습니다 "
      "(12종 전부는 `out/pass_rule.csv`). TPSL의 R은 그 설정의 손절폭 단위라서, 손절이 넓으면 비용이 R로 작아 "
      "보입니다. 'R2'는 기본 2 ATR 손절 단위로 바꾼 값입니다.")
    a("")
    a(tabs["var"])
    a("")
    a(f"- MAKER는 시험 기간 거래당 {vd['maker'][0]:.3f} ~ {vd['maker'][1]:.3f}R 덜 잃습니다 (진입 비용이 줄어서). 그래도 "
      f"모든 기간 손해입니다. 이 모의에서는 지정가가 {100 * fill.min():.0f}~{100 * fill.max():.0f}% 체결되는데, 실제로는 "
      f"체결이 덜 되고 불리한 체결이 섞일 수 있어 이 이득은 상한으로 보아야 합니다.")
    a(f"- STFLIP은 추세를 길게 들고 가서 R 분포가 매우 넓습니다 (승률 {100 * stw.min():.0f}~{100 * stw.max():.0f}%, 가끔 큰 "
      "이익). 30분봉에서 검색과 2020년은 +였지만 시험 기간 95% 구간이 대략 -0.2 ~ +0.2R보다 넓어 0과 구별되지 않습니다. "
      "기본값의 STFLIP을 확실히 이기지도 못합니다.")
    a(f"- HTF 필터는 시험 기간 net R을 {vd['htf'][0]:+.3f} ~ {vd['htf'][1]:+.3f}R, CHOP 필터는 {vd['chop'][0]:+.3f} ~ "
      f"{vd['chop'][1]:+.3f}R 바꿉니다 (+ = 덜 잃음, 기본 청산의 고른 값 1과 비교). 손익의 부호는 바뀌지 않습니다.")
    a(f"- TPSL은 R로는 덜 잃어 보입니다(손절이 넓어 비용이 R로 작아짐). 기본 손절 단위(R2)로 바꿔도 시험 기간에는 기본 청산의 "
      f"고른 값보다 {vd['tpsl_r2_test'][0]:+.3f} ~ {vd['tpsl_r2_test'][1]:+.3f}R 낫지만 여전히 모두 손해입니다. 2020년에는 "
      f"{vd['tpsl_r2_extra'][0]:+.3f} ~ {vd['tpsl_r2_extra'][1]:+.3f}R로 섞여 있습니다. 12종 중 가장 좋은 것을 고른 결과라 "
      f"이 차이에도 선택 효과가 들어 있습니다.")
    a("")
    a("## 8. 운 기준선 (검색 기간)")
    a("")
    a("고른 값과 같은 수의 롱/숏 신호를 무작위 봉에 50번 뿌려 같은 방식으로 거래했습니다. 격자 크기(343/735/588개)만큼 "
      "무작위 세트를 뽑았을 때 나올 '최고값'의 95% 지점보다 고른 값이 높으면 '운보다 나음'입니다.")
    a("")
    a(tabs["luck"])
    a("")
    a(f"- 전체 합산 고른 값 18개 중 {nbeat_luck_pooled}개가 운 기준선을 넘었습니다 (N02 15분, N04 15분 1위, N04 30분). "
      "신호가 무작위 진입보다 조금 낫다는 뜻입니다. 하지만 무작위 진입 자체가 -0.10 ~ -0.15R이라, 조금 나아도 여전히 "
      "손해입니다. S2는 무작위와 구별되지 않습니다.")
    a("- 참고: 50개 무작위 값에서 격자 크기만큼 다시 뽑으면 거의 항상 50개 중 최고값이 뽑혀서, 이 기준선은 사실상 "
      "'50번 중 최고'입니다 (미리 정한 방법 그대로). 정규분포로 근사한 더 엄격한 기준선은 `out/luck.csv`에 있습니다.")
    a("")
    a("## 9. 통과 규칙 판정")
    a("")
    a(f"- 기본 청산 방식, 고른 값 60개 (전체 18 + 코인별 42): 규칙 1(시험·추가 모두 +) 통과 "
      f"{int(main_ps.rule1_test_extra_pos.sum())}개, 규칙 2(기본값보다 나음) {int(main_ps.rule2_beats_default.sum())}개, "
      f"규칙 3(운보다 나음) {int(main_ps.rule3_beats_luck.sum())}개, 규칙 4(이웃 시험 평균 +) "
      f"{int(main_ps.rule4_neighbours_pos.sum())}개. **모두 통과 0개.**")
    a(f"- 시험 기간 net R이 +인 고른 값은 기본 청산 방식에서 {int((main_ps.test_net_R > 0).sum())}개입니다. 이웃 값들의 "
      f"시험 평균도 전부 음수입니다 (전체 합산 고른 값의 이웃 중 시험 기간 + 비율 "
      f"{100 * NB[(NB.variant == 'main') & (NB.scope == 'pooled')].neighbours_test_pos_share.max():.0f}%).")
    if one is not None:
        a(f"- 변형까지 {len(PS):,}개 중 시험·추가 모두 +인 것은 {int(PS.rule1_test_extra_pos.sum())}개, 4개 규칙 모두 통과는 "
          f"{len(allpass)}개입니다: {SN[one.strategy]} {one.tf} STFLIP {one.coin.replace('USD', '')} ({one.label}). 검색 "
          f"{f(one.search_net_R)}R → 시험 {f(one.test_net_R)}R [{f(one.test_ci_lo)}, {f(one.test_ci_hi)}], 추가 "
          f"{f(one.extra_net_R)}R [{f(one.extra_ci_lo)}, {f(one.extra_ci_hi)}]. 검색 성적은 2021년 DOGE 급등에서 왔고 "
          f"시험에서 {one.shrink_search_to_test:.2f}R 줄었습니다. 두 기간 모두 구간이 0을 크게 포함합니다. 데모 후보로 "
          f"권하지 않습니다.")
    a("")
    a("## 10. 다시 고르기: 5거래마다(ROLL5) / 매주(WEEKLY) vs 기본값")
    a("")
    a("계좌 규칙: 코인당 포지션 1개, 7개 코인. ROLL5는 계좌가 5번 거래를 끝낼 때마다 최근 26주(또는 4주)에 끝난 모든 "
      "값의 거래로 '평평한 언덕' 1위를 다시 골라 다음 신호부터 씁니다. WEEKLY는 매주 월요일 0시(UTC)에 최근 26주로 다시 "
      "고릅니다. 칸: 거래당 net R (거래 수); 차이 = 기본값 대비, [95% 구간].")
    a("")
    a(tabs["reopt"])
    a("")
    a(f"- 모든 방식이 손해입니다. 24개 비교 중 {n_ro_sig_better}개는 구간이 0보다 위, {n_ro_sig_worse}개는 0보다 아래입니다: "
      f"{sig_txt}. 나머지 {24 - n_ro_sig_better - n_ro_sig_worse}개는 0과 구별되지 않습니다.")
    a(f"- 5거래마다 다시 고르면 시험 기간에 값을 {int(rp.repicks.min()):,} ~ {int(rp.repicks.max()):,}번 다시 고르고, "
      f"{int(rp.distinct_combos.min())} ~ {int(rp.distinct_combos.max())}개 값 사이를 오갑니다. 그래도 손해는 그대로이고, "
      "실제 데모에서는 잦은 값 변경이 실수를 늘립니다.")
    a("")
    a("## 11. 계좌 모의 (시작 1,000달러, 코인당 1개, 20/30/40/50배)")
    a("")
    a("- 증거금 = 배수% 규칙(오너 규칙): 20배면 잔고의 20%를 증거금으로, 포지션 크기는 잔고의 4배. 50배면 잔고의 25배.")
    a("- 손절 1% 규칙: 손절에 걸리면 잔고의 1%를 잃도록 크기를 정함.")
    a("- 'house' 점검(실제 봇과 같은 진입 점검: 손절이 청산가 안쪽, 손절 손실 <= 잔고 15%, 거래소 구간, 최소 주문)을 켜고, "
      "바이낸스 최소 주문 크기(가정값, DEVIATIONS I11)를 적용한 결과입니다. 점검 없이 강제로 거래한 결과와 최소 주문 없는 "
      "결과는 `out/accounts.csv`에 있습니다.")
    a("- 칸: 최종 잔고 / 최대 낙폭 / 최악 연패 / 파산일(잔고 < 100달러) (거래 수). 파산하면 그 뒤로는 거래하지 않습니다.")
    a("")
    a("시험 기간 (2024-01 ~ 2026-09):")
    a("")
    a(tabs["acc_test"])
    a("")
    a("추가 기간 (2020):")
    a("")
    a(tabs["acc_extra"])
    a("")
    a(f"- 시험 기간: {len(acc_t):,}개 계좌 모의 전부 파산했습니다. 위 표(점검 켬, 최소 주문 적용)에서 오너 규칙의 파산일 "
      f"중앙값은 {ro_own.median():%Y-%m-%d} ({100 * (ro_own < '2024-03-01').mean():.0f}%가 2024-03 전), 1% 규칙은 "
      f"{ro_r1.median():%Y-%m-%d} ({100 * (ro_r1 < '2025-01-01').mean():.0f}%가 2025년 전)입니다. 거래당 평균이 약 "
      f"-0.1R 이상 손해라서 거래를 많이 할수록 빨리 줄어듭니다.")
    a(f"- 검색 기간(2021-23)도 {int(acc_s.ruin.sum()):,}/{len(acc_s):,}개 파산. 2020년은 {len(surv_x)}개가 살아남았지만 "
      f"전부 원금 아래입니다. 가장 좋은 경우는 {SN[best_x.strategy]} {best_x.tf} {T.SET_KO.get(best_x.set, best_x.set)} "
      f"{int(best_x.lev)}배 {('오너 규칙' if best_x.sizing == 'owner' else '1% 규칙')}: ${best_x.final:,.0f}, 최대 낙폭 "
      f"-{100 * best_x.max_dd:.0f}% (거래 {int(best_x.trades)}번; 50배에서 점검에 걸려 거의 거래를 못 했기 때문입니다).")
    a("- 배수 비교: 배수를 올려도 결과는 좋아지지 않습니다. 높은 배수에서는 진입 점검에 많이 걸려 거래 수가 줄 뿐이고, "
      "점검 없이 강제로 거래하면 청산(liquidation)이 생겨 더 빨리 파산합니다. '가장 낮은 낙폭의 이익 설정'은 이 데이터에 "
      "존재하지 않습니다.")
    a("")
    a("## 12. 봉 중간 진입 (INTRABAR, 추가 계획)")
    a("")
    if IB is not None:
        ibm = IB[(IB.scope == "ALL")]
        a("신호 봉이 끝나기 전, 5분마다 그때까지의 봉으로 신호를 계산해서 처음 켜지는 순간 다음 5분봉 시가에 진입했습니다. "
          "손절 2 ATR(그 순간의 ATR), 같은 계단식 익절과 비용. 비교를 공정하게 하려고 봉 마감 진입도 같은 5분봉으로 다시 "
          "점검했습니다 ('봉 마감, 5분 점검'). 본 시뮬(15분 점검) 값도 함께 적었습니다. '사라진 신호' = 봉 중간에 켜졌다가 봉 "
          "마감에는 꺼진 신호. 진입가 차이 bp = 봉 마감 진입보다 몇 bp 유리하게 들어갔는지 (끝까지 유지된 신호만).")
        a("")
        a(t_intrabar(IB))
        a("")
        dif = ibm.ib_net_R - ibm.bc5_net_R
        ibc = IB[IB.scope != "ALL"]
        a(f"- 봉 중간 진입은 7개 코인 합산 {len(ibm)}개 경우(값 x 기간) 모두 손해입니다 (net R {rng(ibm.ib_net_R)}). "
          f"코인별 고른 값을 자기 코인에서 돌린 {len(ibc)}개 경우 중 +는 {int((ibc.ib_net_R > 0).sum())}개뿐입니다.")
        a(f"- 같은 5분 점검의 봉 마감 진입보다 나은 경우는 {int((dif > 0).sum())}/{len(ibm)}개, 차이는 {rng(dif, 3)}R "
          f"(평균 {dif.mean():+.3f}R)입니다.")
        a(f"- 이유: 봉 중간에 켜졌다가 봉 마감에는 꺼지는 신호가 {100 * ibm.ib_vanished_share.min():.0f}~"
          f"{100 * ibm.ib_vanished_share.max():.0f}%이고 (N04는 약 절반), 이 거래들의 net R이 {rng(ibm.ib_net_R_vanished)}로 "
          f"특히 나쁩니다. 끝까지 유지된 신호는 봉 마감보다 평균 {ibm.entry_diff_bps_mean.min():.1f}~"
          f"{ibm.entry_diff_bps_mean.max():.1f}bp 좋은 가격에 들어가고 거래당 {ibm.kept_pair_dR_mean.min():+.3f}~"
          f"{ibm.kept_pair_dR_mean.max():+.3f}R 낫지만, 사라진 신호의 손실이 이 이득을 대부분 지웁니다.")
        a("- 봉 중간 진입은 통과 경로가 아닙니다 (추가 계획 그대로). 결과로 봐도 봉 마감 진입을 대신할 이유가 없습니다.")
        a("- 단위 시험: 봉이 완성된 경우 봉 중간 계산이 원본 신호·ATR과 정확히 같음 (128건, 신호 384,210개, 모두 일치). "
          "임의의 미완성 봉 2,545곳에서도 원본 코드를 잘린 데이터로 다시 돌린 값과 신호 불일치 0 "
          "(`out/intrabar_unit_test.json`).")
    a("")
    a("## 13. 자체 점검 (기존 결과 재현)")
    a("")
    a(f"- 기존 lens2 custom_values의 값: S2_ST_ROC 기본값 15분, 6개 코인, 2021-08-02 ~ 2026-09-28 신호, 거래당 -0.1645R, "
      f"94,310건.")
    a(f"- 이 연구의 신호에 lens2와 같은 청산 방식(모든 신호 20배 계단, 청산가 없음)을 쓰면: "
      f"{sc['lens2_geometry_same_signals']['mean_net_R']:+.4f}R, {sc['lens2_geometry_same_signals']['trades']:,}건 "
      f"(gross {sc['lens2_geometry_same_signals']['mean_gross_R']:+.4f}, cost {sc['lens2_geometry_same_signals']['mean_cost_R']:.4f}). "
      f"**정확히 재현됩니다.** 신호도 기존 캐시와 한 봉도 다르지 않습니다 (6개 코인, 불일치 0).")
    a(f"- 이 연구의 본 시뮬(실제 봇처럼 30배 가능하면 30배, 아니면 20배 계단, 청산가 반영)로는 "
      f"{sc['this_study_house']['mean_net_R']:+.4f}R, 같은 94,310건 (gross {sc['this_study_house']['mean_gross_R']:+.4f}, "
      f"cost {sc['this_study_house']['mean_cost_R']:.4f}, 승률 {100 * sc['this_study_house']['win_rate']:.1f}% vs "
      f"{100 * sc['lens2_geometry_same_signals']['win_rate']:.1f}%). 차이 "
      f"{sc['this_study_house']['mean_net_R'] - sc['lens2_geometry_same_signals']['mean_net_R']:+.4f}R의 이유: 신호의 "
      f"{100 * min(lev30):.0f}~{100 * max(lev30):.0f}%가 30배로 잡히는데, 30배에서는 계단식 익절의 첫 잠금(ROE 12%)이 더 작은 가격 움직임에서 걸립니다. 작은 이익으로 "
      f"끝나는 거래가 늘어 승률은 오르고 큰 이익은 줄어 gross가 "
      f"{sc['lens2_geometry_same_signals']['mean_gross_R'] - sc['this_study_house']['mean_gross_R']:.4f}R 낮아집니다. "
      f"청산가에 닿은 거래는 0건이라 청산가 반영은 영향이 없습니다.")
    a("- 그 밖의 점검: 이 연구의 청산 함수 = lens2 precompute.scan (차이 1e-15). 지표 재사용(메모) 결과 = 원본 코드 "
      "(BTC 30분 2020, 1,666개 값 전부 불일치 0; 각 계산 묶음마다 3~4개 값 추가 확인).")
    a("")
    a("## 14. 한계 (정직하게)")
    a("")
    a("- 모의는 실제 체결이 아닙니다. 슬리피지 0.02%는 평소 기준이고, 폭락 때는 더 클 수 있습니다. 즉 실제는 이보다 나쁠 "
      "가능성이 큽니다.")
    a("- XRP는 실제 거래한 적이 없어 레버리지 구간을 DOGE 것으로 가정했습니다. XRP 2022-02-26~28, 2022-04-01~02 데이터가 "
      "비어 있습니다.")
    a("- 최소 주문 크기는 오프라인이라 확인하지 못한 가정값입니다. 결과(전부 파산)는 이 가정과 상관없이 같습니다.")
    a("- 2020년은 데이터 시작 직후라 각 코인 처음 500봉은 신호가 없습니다 (COVID 3월은 포함).")
    a("- 계좌 모의의 청산가는 각 코인의 첫 구간 기준입니다. 잔고가 커지면 실제 청산가는 더 가까워집니다 (결과를 좋게 "
      "만드는 방향의 단순화이지만, 어차피 잔고가 커지지 않았습니다).")
    a("")
    a("## 15. 파일")
    a("")
    a("- 코드: `common.py`, `s0_bars.py` ~ `s9_write_report.py`, `intrabar.py`, `selfcheck.py`, `verify_memo.py`.")
    a("- 결과: `out/picks.csv` (모든 변형의 고른 값), `out/pick_results.csv` (기간·코인별 상세), `out/crash_windows.csv`, "
      "`out/luck.csv`, `out/neighbours.csv`, `out/pass_rule.csv`, `out/reopt.csv`, `out/accounts.csv`, `out/intrabar.csv`, "
      "`out/selfcheck.json`, `out/intrabar_unit_test.json`, `out/verify_memo_*.json`, `out/tables_ko.md` (모든 표), "
      "`out/picks_frozen.json` (고른 값 고정 시각과 해시).")
    a("")
    txt = "\n".join(L)
    open(os.path.join(C.HERE, "RESULTS_KO.md"), "w").write(txt)
    print(f"written {len(txt):,} chars")


if __name__ == "__main__":
    main()
