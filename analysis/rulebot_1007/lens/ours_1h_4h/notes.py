"""Compact per-cell notes from cards_1h_4h.csv -> strategy_notes.json (for the report).
    python3 -I notes.py <work_dir>"""
import site, sys, json
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
W = sys.argv[1]
C = pd.read_csv(f"{W}/cards_1h_4h.csv")
GN = {"A": "A (candidate)", "B": "B (5y gross edge replicates)", "C": "C (no edge; net = minus cost)",
      "D": "D (negative)", "U": "U (untestable / near-silent)"}
def f(x, d=3, sign=True):
    if x != x: return "na"
    return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}")
out = []
for r in C.to_dict("records"):
    nums = (f"acct n v3a/v3b/v4 {int(r['acct_v3a_n'])}/{int(r['acct_v3b_n'])}/{int(r['acct_v4_n'])} meanR "
            f"{f(r['acct_v3a_mean_R'],2)}/{f(r['acct_v3b_mean_R'],2)}/{f(r['acct_v4_mean_R'],2)}; "
            f"every-signal n {int(r['es_n'])} meanR {f(r['es_mean_R'])} CI [{f(r['es_ci95_lo'],2)},{f(r['es_ci95_hi'],2)}]; "
            f"sideflip {f(r['sideflip_excess_R'],2)} (n {r['sideflip_n_pairs'] if r['sideflip_n_pairs']==r['sideflip_n_pairs'] else 0:.0f}, p {f(r['sideflip_p_better'],2,False)}); "
            f"5y(current rules) n {0 if r['fy_n']!=r['fy_n'] else int(r['fy_n'])} net {f(r['fy_mean_R'])} t {f(r['fy_t_R'],1)} "
            f"(IS {f(r['fy_is_mean_R'])}, CF {f(r['fy_cf_mean_R'])}), gross {f(r['fy_gross_R'])} t {f(r['fy_gross_t'],1)}; "
            f"sized {f(r['fy_sized_share'],2,False)} = {f(r['fy_sized_per_day'],2,False)}/day; live sig/day {f(r['live_signals_per_day'],1,False)}; "
            f"live sizing rejects {int(r['rp_n_rej_sizing'])}+{int(r['acct_rej_n'])} ({r['rp_rej_by_coin'] if isinstance(r['rp_rej_by_coin'], str) else '-'}); "
            f"cost {f(r['live_cost_R_median'],2,False)}R; vs 15m/30m: live {f(r['live_htf_minus_ltf_R'],2)}, 5y net {f(r['fy_htf_minus_ltf_R'],3)} gross {f(r['fy_htf_minus_ltf_gross_R'],3)}")
    g = r["grade"]
    if g == "U":
        note = "Too few signals to judge (5y sized n < 100 and live < 10)."
        if r["fy_n"] == r["fy_n"] and r["fy_n"] > 0:
            note += f" 5y: {int(r['fy_n'])} sized signals, net {f(r['fy_mean_R'])}R."
        note += " Keep only as a free rule account, never an AI trader."
    elif g == "D":
        why = []
        if r["fy_t_R"] <= -2 and r["fy_gross_R"] <= -0.02:
            why.append(f"5y net {f(r['fy_mean_R'])}R (t {f(r['fy_t_R'],1)}) and even gross {f(r['fy_gross_R'])}R: direction no better than nothing")
        if r["es_n"] >= 8 and r["es_ci95_hi"] < 0:
            why.append(f"live every-signal CI below 0 ({f(r['es_ci95_lo'],2)}..{f(r['es_ci95_hi'],2)}, n {int(r['es_n'])})")
        note = "; ".join(why) + ". Not an AI-trader candidate at this timeframe."
        if r["es_mean_R"] == r["es_mean_R"] and r["es_mean_R"] > 0:
            note += f" Live every-signal is positive ({f(r['es_mean_R'])}, n {int(r['es_n'])}) but too small to outweigh 5 years."
    elif g == "C":
        note = (f"No directional edge: 5y gross {f(r['fy_gross_R'])}R (t {f(r['fy_gross_t'],1)}), so the net "
                f"{f(r['fy_mean_R'])}R is roughly the cost ({f(r['fy_cost_R'],2,False)}R).")
        if isinstance(r["flags"], str) and "borderline" in r["flags"]:
            note = ("Best 1h/4h cell: 5y gross +0.086R, 72-cell BH q 0.004, positive in IS (+0.069, t 2.00) and CF "
                    "(+0.103, t 3.62); net +0.024R (t 1.08, not significant); 3 of 6 years positive; only ~19% of "
                    "signals sizable at 20x (BTC/ETH mostly) = 0.73 sized/day; live n=4. Misses the preset B bar by "
                    "t 0.0004. Keep as rule account and watch; the only 1h/4h cell worth a shadow AI view.")
        elif r["es_n"] >= 20:
            note += f" Live every-signal {f(r['es_mean_R'])} (n {int(r['es_n'])}) has a CI spanning 0."
        if not (isinstance(r["flags"], str) and "borderline" in r["flags"]):
            note += " Rule account only."
    else:
        note = "See numbers."
    out.append({"strategy": r["strategy"], "timeframe": r["tf"], "grade": GN[g], "numbers": nums, "note": note})
json.dump(out, open(f"{W}/strategy_notes.json", "w"), indent=0)
print(len(out)); print(out[0]); print([o for o in out if o['strategy']=='N23_HA_ST'])
