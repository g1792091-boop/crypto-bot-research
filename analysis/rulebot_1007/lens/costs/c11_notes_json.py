#!/usr/bin/env python3
"""Strategy notes (cost lens) as JSON from c09_strategy_cost_grades.csv: core36 15m / 30m one row each, DeepSeek
15m / 30m individually when not D, the D ones as one row per timeframe.

    python3 -I c11_notes_json.py <c09_strategy_cost_grades.csv> <out_json>
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import pandas as pd  # noqa: E402


def f(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{d}f}"


def main():
    N = pd.read_csv(sys.argv[1])
    out = []
    C = N[(N["grp"] == "core36") & N["tf"].isin(["15m", "30m"])].sort_values(["tf", "grade", "strategy"])
    for r in C.itertuples():
        ci = f"[{f(r.live_gross_ci_lo, 2)}, {f(r.live_gross_ci_hi, 2)}]" if r.live_gross_ci_lo == r.live_gross_ci_lo else "[n<5]"
        nums = (f"live every-signal n={r.live_n}: net {f(r.live_net_R, 2)}R, gross {f(r.live_gross_R, 2)}R {ci}, real cost "
                f"{r.live_cost_R_real:.2f}R (stop {r.live_median_stop_pct:.2f}%); 5y n={int(r.y5_n)}: net {r.y5_net_bps:+.1f} bp, "
                f"gross {r.y5_gross_bps:+.1f} bp = {f(r.y5_gross_R)}R [{f(r.y5_gross_ci_lo)}, {f(r.y5_gross_ci_hi)}], "
                f"P1 {f(r.y5_gross_R_p1)} / P2 {f(r.y5_gross_R_p2)}; AI must add {r.ai_edge_needed_R_real:.2f}R/trade")
        flag = ""
        if r.live_gross_ci_lo == r.live_gross_ci_lo and r.live_gross_ci_lo > 0 and r.grade in ("C", "D"):
            flag = " Live gross CI above 0 is contradicted by 5 years: treat as regime luck."
        if r.grade == "B":
            note = (f"Small real pre-cost edge over 5y (both periods > 0) but it covers only "
                    f"{max(r.y5_gross_bps, 0) / 14 * 100:.0f}% of a 14 bp round trip; among 108 core cells ~3 such are "
                    f"expected by chance. Usable as an AI base only if the AI adds ~{r.ai_edge_needed_R_real:.2f}R/trade.")
        elif r.grade == "C":
            note = (f"Coin flip before costs over 5y; the AI would have to supply the whole cost "
                    f"(~{r.ai_edge_needed_R_real:.2f}R/trade at live volatility, real taker).")
        else:
            note = ("Loses before costs over 5y (gross < 0); an AI would first have to undo a negative edge. "
                    "Not a cost-viable base.")
        out.append({"strategy": r.strategy, "timeframe": r.tf, "grade": r.grade, "numbers": nums, "note": note + flag})
    D = N[(N["grp"] == "ds200") & N["tf"].isin(["15m", "30m"])]
    for r in D[D["grade"] != "D"].sort_values(["tf", "strategy"]).itertuples():
        ci = f"[{f(r.live_gross_ci_lo, 2)}, {f(r.live_gross_ci_hi, 2)}]" if r.live_gross_ci_lo == r.live_gross_ci_lo else "[n<5]"
        nums = (f"live n={r.live_n}: net {f(r.live_net_R, 2)}R, gross {f(r.live_gross_R, 2)}R {ci}, real cost "
                f"{r.live_cost_R_real:.2f}R; 5y (own PREREG exits, unlevered) gross IS {r.y5_gross_bps:+.1f} bp / CF "
                f"{r.y5_gross_bps_cf:+.1f} bp vs cost {r.y5_cost_bps:.1f} bp")
        out.append({"strategy": f"{r.strategy} (DeepSeek)", "timeframe": r.tf, "grade": "C",
                    "numbers": nums, "note": "Gross positive in only one of the two 5y periods: no stable pre-cost edge; "
                                             f"AI must supply ~{r.ai_edge_needed_R_real:.2f}R/trade."})
    for tf, g in D[D["grade"] == "D"].groupby("tf"):
        nums = (f"{len(g)} definitions; live n={int(g['live_n'].sum())}, pooled live gross "
                f"{(g['live_n'] * g['live_gross_R']).sum() / g['live_n'].sum():+.2f}R; 5y gross median IS "
                f"{g['y5_gross_bps'].median():+.1f} bp / CF {g['y5_gross_bps_cf'].median():+.1f} bp vs cost "
                f"{g['y5_cost_bps'].median():.1f} bp")
        out.append({"strategy": "DeepSeek ds200: all other definitions (" + ", ".join(sorted(g["strategy"])[:60]) + ")",
                    "timeframe": tf, "grade": "D", "numbers": nums,
                    "note": "Gross negative in both 5y periods under their own exits: they lose before costs. Live winners "
                            "here (e.g. F15_ORB, F1_RSI_DIV, F12_MSS) are contradicted by 5 years."})
    with open(sys.argv[2], "w") as fh:
        json.dump(out, fh, indent=1)
    print(len(out))


if __name__ == "__main__":
    main()
