#!/usr/bin/env python3
"""strategy_notes JSON (one per definition x tf) from cards_deepseek.csv.   python3 -I make_notes.py <cards_deepseek.csv> <out_json>"""
import json
import math
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import pandas as pd  # noqa: E402

GN = {"A": "A (AI trader on evidence)", "W": "W (watch: exploratory AI slot at most)", "C": "C (rule account only)",
      "D": "D (drop for AI)", "X": "X (merged duplicate)", "N": "N (no live evidence)"}


def f(x, fmt="{:+.2f}"):
    return "na" if x is None or (isinstance(x, float) and math.isnan(x)) else fmt.format(x)


def main(src, dst):
    C = pd.read_csv(src)
    out = []
    for r in C.itertuples(index=False):
        s1 = []
        if isinstance(r.y_stage1_per_results_csv, str) and r.y_stage1_per_results_csv:
            s1.append(f"results.csv stage1 {r.y_stage1_per_results_csv}")
        if isinstance(r.y_stage1_per_results_md, str) and r.y_stage1_per_results_md:
            s1.append(f"RESULTS md stage1 {r.y_stage1_per_results_md}")
        if bool(r.y_any_all3_positive):
            s1.append("5y all-3-periods-positive (one exit)")
        n = int(r.rp_traded)
        y = f"5y {r.y_best_exit[:2]} {r.y_best_mean12_pct:+.3f}%/tr r{int(r.y_rank_in_tf)}/{int(r.y_defs_in_tf)}"
        if n < 5:
            nums = (f"sig/d {r.live_signals_per_day:.1f}; acct n{int(r.acct_n) if r.acct_n == r.acct_n else 0}; replay n{n}"
                    f"{'' if n == 0 else ' ' + f(r.rp_mean_R) + 'R'}; {y}" + (f"; {'; '.join(s1)}" if s1 else ""))
        else:
            nums = (f"sig/d {r.live_signals_per_day:.1f}; acct n{int(r.acct_n) if r.acct_n == r.acct_n else 0} {f(r.acct_mean_R)}R; "
                    f"replay n{n} G{int(r.rp_G)} {f(r.rp_mean_R)}R [{f(r.rp_lo)},{f(r.rp_hi)}] qPos {f(r.bh_q_gt0_testable, '{:.2f}')}; "
                    f"sideBal {f(r.rp_side_balanced_R)}; peers {f(r.rp_mean_R_vs_peers)}; exBest {f(r.rp_mean_R_ex_best)}; "
                    f"long {f(r.rp_long_share, '{:.2f}')}; gross {f(r.rp_mean_gross_R)}; flip {f(r.sf_excess_R)}; "
                    f"lev10/30 {f(r.lev10_mean_R)}/{f(r.lev30_mean_R)}; {y}" + (f"; {'; '.join(s1)}" if s1 else ""))
        note = r.grade_reason if r.grade != "N" else ("no live signal" if r.live_signals == 0 else f"{n} replayed trades: judged on the 5-year line only")
        if r.grade == "X":
            note += f" (overlap partner {r.dup_partner}, overlap {f(r.dup_overlap_min, '{:.2f}')})" if isinstance(r.dup_partner, str) else ""
        if not r.ai_entry_tf:
            note += "; not an AI entry tf (rule account)"
        out.append({"strategy": r.definition, "timeframe": r.timeframe, "grade": GN[r.grade], "numbers": nums, "note": note})
    with open(dst, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=0)
    print(len(out), sum(len(json.dumps(o)) for o in out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
