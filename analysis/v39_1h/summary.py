#!/usr/bin/env python3
"""Collect the V3.9 1h study's tables into TABLES_KO.md (every table, Korean headers) and facts.json (key numbers).

    python3 -I summary.py <out_dir>

<out_dir> holds window/, fiveyear/, extras/ (and window_cut/ when run_all.sh was given COMPARE_CUT_MS). Writes
<out_dir>/TABLES_KO.md and <out_dir>/facts.json. Reads only this study's own outputs.
"""
from __future__ import annotations

import json
import os
import site
import sys

sys.dont_write_bytecode = True
_us = site.getusersitepackages()
if _us not in sys.path:
    sys.path.append(_us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SMALL = 10


def rd(d, name):
    p = os.path.join(d, name)
    return pd.read_csv(p) if os.path.exists(p) else None


def fnum(v, nd=1):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    if isinstance(v, (bool, np.bool_)):
        return "예" if v else "아니오"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        return f"{v:,.{nd}f}"
    return str(v)


def md(df: pd.DataFrame, cols: list, nd: dict | None = None) -> str:
    """Markdown table of ``cols`` = [(source column, header)], numbers with ``nd[col]`` decimals (default 1)."""
    nd = nd or {}
    head = "| " + " | ".join(h for _c, h in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    lines = [head, sep]
    for _i, r in df.iterrows():
        lines.append("| " + " | ".join(fnum(r.get(c), nd.get(c, 1)) for c, _h in cols) + " |")
    return "\n".join(lines)


def five_join(rows: pd.DataFrame, fy: pd.DataFrame | None) -> pd.DataFrame:
    if fy is None:
        return rows
    keep = ["variant", "pick_per_trade_pct", "pick_win_pct", "check_per_trade_pct", "check_win_pct",
            "pick_delta_paired_pct", "check_delta_paired_pct", "pick_delta_paired_t", "check_delta_paired_t",
            "pick_trades", "check_trades", "pick_acct_final", "check_acct_final", "pick_acct_days", "check_acct_days"]
    keep = [c for c in keep if c in fy.columns]
    return rows.merge(fy[keep], on="variant", how="left")


def main(argv) -> int:
    out = argv[0]
    W, Fd, X = (os.path.join(out, k) for k in ("window", "fiveyear", "extras"))
    fw = json.load(open(os.path.join(W, "facts_window.json")))
    fy_sig = json.load(open(os.path.join(Fd, "fy_signals.json"))) if os.path.exists(os.path.join(Fd, "fy_signals.json")) else {}
    fy = rd(Fd, "fy_variants.csv")
    T = rd(W, "trades.csv")
    src = os.path.join(out, "source.txt")
    src = open(src).read().strip() if os.path.exists(src) else os.path.basename(str(fw.get("export")))
    fw["export"] = src
    parts = ["# V3.9 1시간 — 모든 표 (자동 생성)", "",
             f"자료: `{src}` · 1분봉 {fw['replay']['bars_first_kst']} ~ {fw['replay']['bars_last_kst']} (한국 시각)",
             "숫자는 `analysis/v39_1h/run_all.sh`가 다시 만듭니다. 설명과 판단은 `REPORT_KO.md`에 있습니다.",
             "'5년 고르는 기간' = 2021-01 ~ 2023-12, '5년 시험 기간' = 2024-01 ~ 2026-09. 5년 숫자는 신호 하나를 $5,000 "
             "계좌 하나로 따로 계산한 '거래당 계좌 대비 %'입니다(전체 조합 연구와 같은 단위). 거래 10번 미만 칸은 '적음'.", ""]
    rp = fw["replay"]
    parts += ["## 1. 재현 확인", "",
              f"- 페이퍼 거래 {rp['paper_trades']}개 중 봇 엔진 재계산 일치 {rp['engine_same']}개, 이 연구의 계산기 일치 "
              f"{rp['kernel_same']}개 (진입·청산 시각, 이유, 배수). 손익 차이 최대 ${rp['max_abs_pnl_diff_kernel']:.1e}.",
              f"- 최종 잔고: 페이퍼 ${rp['paper_final']:,.2f} = 재계산 ${rp['engine_final']:,.2f}, 최대 낙폭(열린 손실 포함) "
              f"{rp['engine_max_dd_pct']:.1f}%.",
              f"- 신호: 제출 {rp['signals_submitted']}개, 포지션 보유 중이라 건너뜀 {rp['skipped_in_position']}개, 같은 시각 "
              f"다른 코인을 타서 건너뜀 {rp['skipped_lower_score']}개, 늦어서 안 냄 {rp['signals_late_not_submitted']}개.",
              f"- 이 연구의 V3.9 코드를 공개 1시간봉에 돌린 신호: 봇 신호 {fw['signal_check']['bot_submitted']}개 중 "
              f"{fw['signal_check']['in_both']}개 같음, ATR 최대 상대 오차 {fw['signal_check']['atr_max_rel_err']:.1e}.", ""]
    if fy_sig.get("fullgrid_now"):
        g = fy_sig["fullgrid_now"]
        base = fy[fy["variant"] == "now"].iloc[0]
        parts += [f"- 5년(5분봉) 지금 규칙: 고르는 기간 거래 {int(base['pick_trades']):,}개 거래당 {base['pick_per_trade_pct']:.2f}% "
                  f"(승률 {base['pick_win_pct']:.1f}%), 시험 기간 {int(base['check_trades']):,}개 {base['check_per_trade_pct']:.2f}% "
                  f"({base['check_win_pct']:.1f}%). 전체 조합 연구(1분봉): {int(g['fg_pick_trades']):,}개 {g['fg_pick_per_trade_pct']:.2f}% "
                  f"({g['fg_pick_win_pct']:.1f}%), {int(g['fg_check_trades']):,}개 {g['fg_check_per_trade_pct']:.2f}% ({g['fg_check_win_pct']:.1f}%).", ""]
    # trades
    parts += ["## 2. 거래 하나씩", ""]
    T = T.assign(after24=T.get("after24h_best_move_pct"))
    parts.append(md(T, [("n", "번"), ("symbol", "코인"), ("side", "방향"), ("entry_kst", "진입"), ("hold_min", "보유(분)"),
                        ("reason", "청산"), ("leverage", "배수"), ("roe_pct", "ROE %"), ("ret_pct", "계좌 대비 %"),
                        ("stop_dist_pct", "손절 거리 %"), ("mae_roe_gross_pct", "가장 깊이 물림 (ROE %)"),
                        ("mae_atr", "물림 (ATR)"), ("min_to_mae", "바닥까지 (분)"), ("red_minutes", "마이너스였던 분"),
                        ("mfe_roe_net_pct", "최고 ROE (순) %"), ("after24", "청산 뒤 24시간 더 간 % (최대)")],
                    {"n": 0, "hold_min": 0, "leverage": 0, "min_to_mae": 0, "red_minutes": 0, "mae_atr": 2,
                     "stop_dist_pct": 2, "after24": 2}))
    parts.append("")
    # variant tables
    def var_table(title, name, extra_cols=(), group=None):
        R = rd(W, name)
        if R is None:
            return
        R = five_join(R, fy)
        parts.extend([f"## {title}", ""])
        cols = [("label", "변형"), ("wins", "20일 같은 진입: 이김"), ("losses", "짐"), ("sum_ret_pct", "거래 합계 %"),
                ("overlaps", "다음 진입과 겹침"), *extra_cols, ("acct_trades", "20일 계좌: 거래"), ("acct_wins", "이김"),
                ("acct_losses", "짐"), ("acct_final", "최종 $ (시작 5,000)"),
                ("pick_per_trade_pct", "5년 고르는 기간 거래당 %"), ("pick_win_pct", "승률 %"),
                ("check_per_trade_pct", "5년 시험 기간 거래당 %"), ("check_win_pct", "승률 %")]
        parts.append(md(R, cols, {"pick_per_trade_pct": 2, "check_per_trade_pct": 2, "acct_final": 0, "overlaps": 0}))
        parts.append("")
    var_table("3. 익절 바꾸기 (진입·손절 그대로)", "tp_variants.csv")
    var_table("4. 손절 바꾸기", "sl_variants.csv", (("worst_roe_pct", "가장 나쁜 거래 ROE %"),))
    var_table("5. 레버리지·증거금", "lev_variants.csv", (("worst_ret_pct", "가장 나쁜 거래 (계좌 %)"),
                                                     ("deepest_open_pct", "가장 깊은 열린 손실 (계좌 %)")))
    E = rd(W, "entry_variants.csv")
    if E is not None:
        E = five_join(E, fy)
        parts += ["## 6. 진입 시점 (시장가만)", ""]
        parts.append(md(E, [("label", "방법"), ("entered", "20일: 들어감"), ("skipped_paper_wins", "놓친 이긴 거래"),
                            ("wins", "이김"), ("losses", "짐"), ("sum_ret_pct", "거래 합계 %"), ("acct_final", "20일 계좌 최종 $"),
                            ("pick_trades", "5년 고르는 기간 거래"), ("pick_per_trade_pct", "거래당 %"),
                            ("check_trades", "5년 시험 기간 거래"), ("check_per_trade_pct", "거래당 %")],
                        {"pick_per_trade_pct": 2, "check_per_trade_pct": 2, "acct_final": 0, "pick_trades": 0,
                         "check_trades": 0}))
        parts.append("")
    FG = rd(Fd, "fy_fullgrid_exits.csv")
    FW = rd(W, "fullgrid_exits_window.csv")
    if FG is not None and FW is not None:
        M = FW[["variant", "wins", "losses", "acct_final"]].merge(FG, on="variant", how="left")
        parts += ["## 7. 전체 조합 연구의 청산 72가지 (손절 × 익절)", "",
                  "fg_ = 전체 조합 연구 원래 숫자(1분봉). 나머지는 이 연구(5분봉). 같은 청산이면 두 숫자가 거의 같습니다.", ""]
        parts.append(md(M, [("variant", "청산"), ("wins", "20일 같은 진입 이김"), ("losses", "짐"), ("acct_final", "20일 계좌 최종 $"),
                            ("pick_per_trade_pct", "5년 고르는 기간 %"), ("fg_pick_per_trade_pct", "fg 고르는 기간 %"),
                            ("check_per_trade_pct", "5년 시험 기간 %"), ("fg_check_per_trade_pct", "fg 시험 기간 %"),
                            ("fg_check_win_pct", "fg 시험 승률 %")],
                        {"pick_per_trade_pct": 2, "fg_pick_per_trade_pct": 2, "check_per_trade_pct": 2,
                         "fg_check_per_trade_pct": 2, "acct_final": 0}))
        parts.append("")
    RW, RF = rd(W, "rules_window.csv"), rd(Fd, "fy_rules.csv")
    if RW is not None:
        R = RW.merge(RF, on=["rule", "label"], how="left") if RF is not None else RW
        parts += ["## 8. 손실을 피하는 간단한 규칙 (\"이럴 땐 안 들어감\")", ""]
        parts.append(md(R, [("label", "규칙"), ("removes_losses", "20일: 손실 빠짐"), ("wins_removed", "이긴 거래 빠짐"),
                            ("acct_final", "20일 계좌 최종 $"), ("pick_skip_share_pct", "5년 고르는 기간: 빠지는 신호 %"),
                            ("pick_kept_per_trade_pct", "남은 거래당 %"), ("pick_removed_per_trade_pct", "빠진 거래당 %"),
                            ("check_kept_per_trade_pct", "시험 기간 남은 거래당 %"),
                            ("check_removed_per_trade_pct", "빠진 거래당 %")],
                        {k: 2 for k in ("pick_kept_per_trade_pct", "pick_removed_per_trade_pct",
                                        "check_kept_per_trade_pct", "check_removed_per_trade_pct")} | {"acct_final": 0}))
        parts.append("")
    S = rd(X, "splits.csv")
    if S is not None:
        S = S.assign(small=np.where(S["trades"] < SMALL, "적음", ""))
        parts += ["## 9. 이긴 거래는 어디서 나왔나 (20일 vs 5년)", ""]
        parts.append(md(S, [("split", "나눔"), ("group", "칸"), ("trades", "20일 거래"), ("wins", "이김"), ("losses", "짐"),
                            ("mean_ret_pct", "거래당 계좌 %"), ("small", ""), ("pick_trades", "5년 고르는 기간 거래"),
                            ("pick_mean_ret_pct", "거래당 %"), ("pick_win_pct", "승률 %"), ("check_trades", "시험 기간 거래"),
                            ("check_mean_ret_pct", "거래당 %"), ("check_win_pct", "승률 %")],
                        {"mean_ret_pct": 2, "pick_mean_ret_pct": 2, "check_mean_ret_pct": 2, "pick_trades": 0,
                         "check_trades": 0}))
        parts.append("")
    for name, title, cols in (
            ("other_timeframes.csv", "10. 같은 V3.9, 다른 봉 (같은 20일, 페이퍼 계좌)",
             [("account", "계좌"), ("trades", "거래"), ("wins", "이김"), ("losses", "짐"), ("shorts", "숏"), ("pnl", "손익 $"),
              ("final", "최종 $"), ("max_dd_closed_pct", "최대 낙폭 %")]),
            ("tie_break_window.csv", "11. 같은 시각 신호가 여럿일 때 어느 코인을 타나 (20일 계좌)",
             [("label", "고르는 법"), ("trades", "거래"), ("wins", "이김"), ("losses", "짐"), ("final", "최종 $"),
              ("final_min", "무작위 최저 $"), ("final_max", "무작위 최고 $")]),
            ("tie_break_5y.csv", "12. 같은 질문, 5년 (한 번에 한 포지션, 거래마다 $5,000)",
             [("label", "고르는 법"), ("pick_trades", "고르는 기간 거래"), ("pick_per_trade_pct", "거래당 %"),
              ("check_trades", "시험 기간 거래"), ("check_per_trade_pct", "거래당 %")]),
            ("skipped_signals.csv", "13. 계좌가 타지 않은 V3.9 신호 (하나씩 따로 탔다면, $5,000)",
             [("signal_kst", "신호"), ("symbol", "코인"), ("side", "방향"), ("why_skipped", "안 탄 이유"), ("reason", "청산"),
              ("roe_pct", "ROE %"), ("bot_shadow_roe_pct", "봇 그림자 ROE %")]),
            ("shadow_check_summary.csv", "14. 봇이 매일 밤 계산한 그림자 vs 이 연구의 계산 (같은 거래)",
             [("kind", "그림자"), ("resolved_rows", "끝난 행"), ("compared", "비교"), ("within_1pt", "1%p 안"),
              ("max_abs_diff_pct", "최대 차이 %p"), ("both_rejected", "둘 다 진입 거절"), ("bot_mean_roe_pct", "봇 평균 ROE %"),
              ("my_mean_roe_pct", "이 연구 평균 ROE %")])):
        R = rd(X, name)
        if R is not None:
            parts += [f"## {title}", "", md(R, cols, {"pick_per_trade_pct": 2, "check_per_trade_pct": 2, "final": 0,
                                                      "final_min": 0, "final_max": 0, "pnl": 0, "max_abs_diff_pct": 2}), ""]
    C = rd(X, "costs_plan.csv")
    if C is not None:
        C = C[C["steps"].isin(["A", "binance"])]
        parts += ["## 15. 실제 계획의 비용 ($50, Toobit 수수료 가정)", "",
                  "Toobit 주문 단위는 이 작업 공간에서 확인할 수 없어 가정입니다 (A = 바이낸스와 같은 단위). 단위 B(더 굵음)는 "
                  "`extras/costs_plan.csv`에 있고 결과 차이는 1%p 안팎입니다.", ""]
        parts.append(md(C, [("plan_label", "크기"), ("cost", "비용"), ("taker_pct", "수수료 %/한쪽"), ("slip_pct", "미끄러짐 %"),
                            ("start", "시작 $"), ("trades", "거래"), ("wins", "이김"), ("losses", "짐"), ("final", "최종 $"),
                            ("ret_pct", "수익 %"), ("dd_closed_pct", "최대 낙폭 %"), ("worst_trade_pct", "가장 나쁜 거래 %")],
                        {"taker_pct": 3, "slip_pct": 2, "final": 2, "start": 0}))
        parts.append("")
    O = rd(X, "outlook_30d.csv")
    if O is not None:
        parts += ["## 16. 30일 전망 (몬테카를로)", "",
                  "w27 = 이번 27거래를 다시 뽑아 한 달(약 41거래)을 만든 것. check_boot = 5년 시험 기간 거래를 다시 뽑은 것. "
                  "check_real = 2024~26년의 실제 30일 구간 전부. 배수 = 30일 뒤 잔고 ÷ 시작 잔고.", ""]
        cols = [("label", "계획")]
        for src, k in (("w27", "27거래"), ("check_boot", "5년 시험 (다시 뽑기)"), ("check_real", "5년 시험 (실제 30일)")):
            cols += [(f"{src}_median_x", f"{k}: 가운데 배수"), (f"{src}_p_x2", "×2 확률"), (f"{src}_p_x6", "×6 확률"),
                     (f"{src}_p_half_any", "−50% 닿을 확률"), (f"{src}_p_ruin_any", "−90% 닿을 확률")]
        parts.append(md(O, cols, {c: 2 if "median" in c else 3 for c, _h in cols}))
        parts.append("")
    st = rd(Fd, "fy_streaks.csv")
    if st is not None:
        parts += ["## 17. 5년 동안 연속으로 이긴 횟수 (지금 규칙, 한 번에 한 포지션)", ""]
        parts.append(md(st, [("period", "기간"), ("trades", "거래"), ("win_pct", "승률 %"), ("longest_win_streak", "가장 긴 연승"),
                             ("streaks_ge_10", "10연승 이상"), ("streaks_ge_20", "20연승 이상"), ("streaks_ge_26", "26연승 이상"),
                             ("streaks_ge_50", "50연승"), ("trades_per_day", "하루 거래")], {"trades_per_day": 2}))
        parts.append("")
    wd = rd(Fd, "fy_windows20d.csv")
    facts = {"window": fw, "fiveyear": fy_sig}
    if wd is not None:
        s = wd[wd["ret_pct"] >= 50].copy()
        s["d"] = pd.to_datetime(s["start"])
        ep = (s["d"].diff().dt.days.fillna(99) > 20).cumsum()
        epi = s.groupby(ep).agg(start=("start", "first"), best=("ret_pct", "max"), next20=("next20_ret_pct", "median"))
        facts["windows20d"] = {"windows": int(len(wd)), "median_ret_pct": float(wd["ret_pct"].median()),
                               "share_positive": float((wd["ret_pct"] > 0).mean()), "max_ret_pct": float(wd["ret_pct"].max()),
                               "episodes_ge50": epi.to_dict("records"),
                               "windows_le1_loss_ge20_trades": int(((wd["losses"] <= 1) & (wd["trades"] >= 20)).sum())}
        parts += ["## 18. 5년의 20일 구간 (지금 규칙, 한 번에 한 포지션, 20일 안에서 복리)", "",
                  f"- 20일 구간 {len(wd):,}개(하루씩 밀며): 가운데 {wd['ret_pct'].median():.1f}%, 플러스인 구간 "
                  f"{100 * (wd['ret_pct'] > 0).mean():.1f}%, 가장 좋은 구간 {wd['ret_pct'].max():.1f}%.",
                  f"- 손실 1번 이하이면서 20거래 이상인 구간: {facts['windows20d']['windows_le1_loss_ge20_trades']}개.", "",
                  md(epi.reset_index(drop=True), [("start", "+50% 넘은 시기 (시작)"), ("best", "가장 좋은 20일 %"),
                                                  ("next20", "바로 다음 20일 % (가운데)")]), ""]
    for k, name in (("extras", "facts_extras.json"),):
        p = os.path.join(X, name)
        if os.path.exists(p):
            facts[k] = json.load(open(p))
    cut = os.path.join(out, "window_cut", "facts_window.json")
    if os.path.exists(cut):
        facts["window_cut"] = json.load(open(cut))
    with open(os.path.join(out, "TABLES_KO.md"), "w") as fh:
        fh.write("\n".join(parts) + "\n")
    with open(os.path.join(out, "facts.json"), "w") as fh:
        json.dump(facts, fh, indent=1, ensure_ascii=False, default=str)
    print(f"wrote {out}/TABLES_KO.md and facts.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
