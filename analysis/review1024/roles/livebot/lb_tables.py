"""Compact tables for REPORT_KO.md: the 13 variants (11 planned + 2 extra) per period, the tests with BH over all 13,
and the goal rows. Writes variants_compact.csv and tests_all13.csv; prints markdown. Run: python3 lb_tables.py"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def bh(p):
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    q = np.full(len(p), np.nan)
    m = ok.sum()
    if m:
        o = np.argsort(p[ok])
        adj = np.minimum.accumulate((p[ok][o] * m / np.arange(1, m + 1))[::-1])[::-1]
        qq = np.empty(m)
        qq[o] = np.minimum(adj, 1)
        q[ok] = qq
    return q


def main():
    S = pd.concat([pd.read_csv(os.path.join(HERE, "variants_summary.csv")),
                   pd.read_csv(os.path.join(HERE, "variants_summary_wait.csv"))])
    T = pd.concat([pd.read_csv(os.path.join(HERE, "variants_tests.csv")),
                   pd.read_csv(os.path.join(HERE, "variants_tests_wait.csv"))]).reset_index(drop=True)
    T["dir_q13"] = bh(T.dir_p)
    T["dir_neg_p"] = 1 - T.dir_p                      # p of "the opposite side is better" (one-sided)
    T["dir_neg_q13"] = bh(T.dir_neg_p)
    T["vs_b0_q13"] = bh(T.vs_b0_p)
    T.to_csv(os.path.join(HERE, "tests_all13.csv"), index=False, float_format="%.4g")
    W = S.pivot_table(index=["variant", "ko"], columns="period",
                      values=["own_n", "own_roe", "paired_opp_roe", "own_per_weekday", "own_roe_pb", "own_short"])
    W.columns = [f"{a}_{b}" for a, b in W.columns]
    W = W.reset_index()
    W.to_csv(os.path.join(HERE, "variants_compact.csv"), index=False, float_format="%.4g")
    order = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "W0", "W3"]
    W["o"] = W.variant.map({v: i for i, v in enumerate(order)})
    W = W.sort_values("o")
    print("| 변형 | 내용 | 고르기 2020-23 | 확인 2024-25.6 | 늦은 2025.7-26.10 | 10월 19일 | 10/23~ | 평일 하루 거래(확인) |")
    print("|---|---|---|---|---|---|---|---|")
    for _, r in W.iterrows():
        cell = lambda p: (f"{100 * r[f'own_roe_{p}']:+.2f}% ({int(r[f'own_n_{p}'])}) / 반대 {100 * r[f'paired_opp_roe_{p}']:+.2f}%"
                          if np.isfinite(r.get(f"own_roe_{p}", np.nan)) else "-")
        print(f"| {r.variant} | {r.ko} | {cell('select')} | {cell('confirm')} | {cell('late')} | {cell('fwd')} | "
              f"{cell('oos1022')} | {r['own_per_weekday_confirm']:.1f} |")
    print()
    print("| 변형 | 거래(확인+늦은) | 거래당 | 95% 범위 | 같은 진입 반대 | 방향 차이 | p(반대가 더 나음) | q13 | B0 대비 | p | q13 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    T["o"] = T.variant.map({v: i for i, v in enumerate(order)})
    for _, r in T.sort_values("o").iterrows():
        vb = f"{100 * r.vs_b0:+.2f}%p | {r.vs_b0_p:.3f} | {r.vs_b0_q13:.3f}" if np.isfinite(r.get("vs_b0", np.nan)) else "- | - | -"
        print(f"| {r.variant} | {int(r.n)} | {100 * r.mean_roe:+.2f}% | {100 * r.mean_ci_lo:+.2f} ~ {100 * r.mean_ci_hi:+.2f} | "
              f"{100 * r.mean_opp_paired:+.2f}% | {100 * r.dir_diff:+.2f}%p | {r.dir_neg_p:.3f} | {r.dir_neg_q13:.3f} | {vb} |")


if __name__ == "__main__":
    main()
