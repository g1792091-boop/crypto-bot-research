"""Build the per-strategy notes (AI unit = strategy x 15m+30m) from grades_15m30m.csv as JSON."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
W = sys.argv[1]
G = pd.read_csv(os.path.join(W, "grades_15m30m.csv"))
DUP = {"F11_RAID": "15m signals identical to F11_TSOUP / F13_RAID_PD", "F11_TSOUP": "15m identical to F11_RAID / F13_RAID_PD",
       "F13_RAID_PD": "15m identical to F11_RAID / F11_TSOUP", "F17_Z_HL": ">=90% same signals as F17_Z",
       "F17_Z": ">=90% same signals as F17_Z_HL", "F5_BOX_HTF": "identical to F5_BOX at 15m/30m",
       "F5_BOX": "identical to F5_BOX_HTF at 15m/30m", "F15_OPEN0000": "one signal stream copied to 15m/30m/1h",
       "F15_OPEN0930": "15m = 30m signals"}
def f(x, d=2):
    return "na" if x != x else f"{x:+.{d}f}"
out = []
for r in G.itertuples():
    nums = (f"sig/day 15m+30m {r.sub_per_day:.1f} (5y {r.ref5y_per_day:.1f}); AI trades/day {r.ai_trades_per_day:.1f} "
            f"(5y-rate est {r.ai_trades_per_day_5y:.1f}); replay pairs n={r.n_pairs} ({r.clusters_1h} 1h-clusters), "
            f"long share {r.long_share:.2f}; R chosen {f(r.chosen_R)} vs side-flip CF {f(r.coinflip_R)} -> excess {f(r.excess)} "
            f"(p {r.p_better:.2f}, BH q {r.bh_q_better:.2f}); vs same-side random-time CF {f(r.cf_same_side_R)} -> timing {f(r.timing_excess)}; "
            f"excess v3b/v4 {f(r.excess_v3b)}/{f(r.excess_v4)}; live trades n={r.live_n} R {f(r.live_R)} (v3a n={r.live_n_v3a} R {f(r.live_R_v3a)}); "
            f"profitable acct-runs {r.profitable_account_runs}, gone w/o best trade {r.of_which_gone_wo_best_trade}")
    nums = nums.replace("(p nan, BH q nan)", "(untested)")
    notes = []
    g = r.grade
    if g == "X":
        notes.append("Too few signals for an AI trader (< 1 trade/day at 15m+30m live and at the 5-year rate); keep as rule account / drop.")
    elif g == "?":
        notes.append("Fewer than 15 replayed signals or fewer than 10 independent 1h moments in v3b+v4: no coin-flip verdict possible.")
    if r.kind == "ds200" and g in ("B", "C", "D"):
        notes.append("ds200 = v4 only (1.5 days, one run): in-sample, no out-of-sample replication.")
    if r.long_share == r.long_share and (r.long_share <= 0.15 or r.long_share >= 0.85) and r.n_pairs >= 10:
        notes.append(f"One-sided ({'short' if r.long_share <= 0.15 else 'long'}) in a falling market: side-flip excess is market direction, judge by the same-side random-time coin flip.")
    if r.excess == r.excess and r.timing_excess == r.timing_excess:
        if r.excess >= 0.1 and r.timing_excess < 0.05:
            notes.append("Beats the side flip only via direction (short tilt in a falling market); timing vs same-side random entries ~0 or negative.")
        if r.excess < 0.05 and r.timing_excess >= 0.25:
            notes.append("Timing within its side looks good but its side choice lost to the market drift (long tilt in a falling market).")
    if isinstance(r.direction_luck_flags, str) and r.direction_luck_flags:
        notes.append(f"Direction-luck flag on account(s) {r.direction_luck_flags}.")
    if r.profitable_account_runs and r.of_which_gone_wo_best_trade == r.profitable_account_runs and r.profitable_account_runs > 0:
        notes.append("Every profitable account-run turns negative without its best trade.")
    if r.strategy in DUP:
        notes.append("Duplicate: " + DUP[r.strategy] + ".")
    if g == "B":
        notes.append("Beats both coin flips in every run/tf with >= 8 signals, but not significant after BH; at most a candidate to watch.")
    if g == "C" and not notes:
        notes.append("Indistinguishable from a coin flip at the same moments.")
    if g == "D":
        notes.append("Loses to both coin flips by >= 0.10R everywhere it traded.")
    if r.ai_busy_share == r.ai_busy_share and r.ai_busy_share >= 0.75:
        notes.append(f"An AI trader would be in a position {r.ai_busy_share:.0%} of the time (signals arrive faster than trades close).")
    out.append({"strategy": f"{r.strategy} ({r.kind})", "timeframe": "15m+30m (AI unit)", "grade": g, "numbers": nums,
                "note": " ".join(notes)})
H = pd.read_csv(os.path.join(W, "grades_1h4h.csv"))
for s, tf in (("N20_EMA9_CHOP", "1h"), ("F14_SMT", "1h")):
    r = H[(H.strategy == s) & (H.tfs == tf)].iloc[0]
    out.append({"strategy": f"{s} ({r.kind})", "timeframe": tf, "grade": "C",
                "numbers": f"replay pairs n={r.n_pairs}, long {r.long_share:.2f}, side-flip excess {r.excess:+.3f} (p {r.p_better:.3f}, BH q {r.bh_q_better:.2f}), "
                           f"timing vs same-side random entries {r.timing_excess:+.3f} {r.timing_excess_ci}",
                "note": "Lowest side-flip p of all 1h/4h cells, but it is (almost) only shorts in a falling market: zero timing edge over random shorts."})
json.dump(out, open(os.path.join(W, "strategy_notes.json"), "w"), indent=1)
print(len(out))
print(json.dumps(out[:3], indent=1))
