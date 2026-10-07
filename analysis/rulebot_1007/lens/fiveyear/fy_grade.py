"""Final combined grade (live + 5-year) per kind x strategy x tf, candidate lists, strategy notes.

    python3 -I -B fy_grade.py <work_out_dir>

Reads fiveyear_vs_live.csv (fy_compare.py) and fy_cells_is_cf.csv (fy_extra.py); rewrites fiveyear_vs_live.csv with the
final grade columns; writes fy_candidates.csv and strategy_notes.json.

5-year class (house exits, v4 'normal' leverage, every signal alone, 2021-08..2026-09, week-clustered t):
  P   net mean R > 0 in both halves (IS 2021-08..2024-06 and CF 2024-07..2026-09)
  Z+  not P, net t > -2, gross R > 0        Z-  not P, net t > -2, gross R <= 0
  N+  net t <= -2 (loses after costs), gross R > 0 (some direction content, killed by costs)
  NN  net t <= -2 and gross R <= 0 (no direction content)
  thin  fewer than 30 sized 5-year signals
Live class (every-signal sample: v3b + v4 replay for 15m..4h, v3a entered + skipped shadows for 5m; cluster SE):
  L++ mean - 2 SE > 0, L+ mean > 0, L- mean <= 0, L-- mean + 2 SE < 0, L_thin n < 15
Grade: A = P & L+/L++;  B = P & L-/thin, Z+ & L+/L++;  C = P & L--, Z+ & L-/thin, N+ & L+/L++, Z- & L+/L++;
       D = Z+ & L--, Z- & L-/thin, N+ & L-/thin, NN & L+/L++;  F = N+ & L--, Z- & L--, NN & L-/L--/thin.
"""
import json
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

W = sys.argv[1]
T = pd.read_csv(os.path.join(W, "fiveyear_vs_live.csv"))
C = pd.read_csv(os.path.join(W, "fy_cells_is_cf.csv"))
T = T.drop(columns=[c for c in T.columns if c in ("fy_is_gross_R", "fy_cf_gross_R", "fy_gross_t")], errors="ignore")
T = T.merge(C[["kind", "strategy", "tf", "is_gR", "cf_gR", "gross_t"]].rename(
    columns={"is_gR": "fy_is_gross_R", "cf_gR": "fy_cf_gross_R", "gross_t": "fy_gross_t"}), on=["kind", "strategy", "tf"], how="left")


def fy_class(r):
    if not np.isfinite(r.get("fy_mean_R", np.nan)) or (r.get("fy_n", 0) or 0) < 30:
        return "thin"
    if r["fy_mean_R"] > 0 and r["fy_is_mean_R"] > 0 and r["fy_cf_mean_R"] > 0:
        return "P"
    g = r["fy_gross_R"] > 0
    if np.isfinite(r["fy_t"]) and r["fy_t"] <= -2:
        return "N+" if g else "NN"
    return "Z+" if g else "Z-"


def live_sample(r):
    if r["tf"] == "5m":
        return r.get("live_v3a_n", 0) or 0, r.get("live_v3a_mean_R", np.nan), r.get("live_v3a_se_R", np.nan), "v3a"
    return r.get("live_rp_n", 0) or 0, r.get("live_rp_mean_R", np.nan), r.get("live_rp_se_R", np.nan), "rp"


def live_class(r):
    n, mu, se, _ = live_sample(r)
    if not n or n < 15 or not np.isfinite(mu):
        return "L_thin"
    if np.isfinite(se) and mu + 2 * se < 0:
        return "L--"
    if np.isfinite(se) and mu - 2 * se > 0:
        return "L++"
    return "L+" if mu > 0 else "L-"


G = {}
for a, gr in (("P", {"L++": "A", "L+": "A", "L-": "B", "L_thin": "B", "L--": "C"}),
              ("Z+", {"L++": "B", "L+": "B", "L-": "C", "L_thin": "C", "L--": "D"}),
              ("N+", {"L++": "C", "L+": "C", "L-": "D", "L_thin": "D", "L--": "F"}),
              ("Z-", {"L++": "C", "L+": "C", "L-": "D", "L_thin": "D", "L--": "F"}),
              ("NN", {"L++": "D", "L+": "D", "L-": "F", "L_thin": "F", "L--": "F"})):
    for b, g in gr.items():
        G[(a, b)] = g
T["fy_class"] = T.apply(fy_class, axis=1)
T["live_class"] = T.apply(live_class, axis=1)
T["grade"] = [G.get((a, b), "thin") for a, b in zip(T["fy_class"], T["live_class"])]
ls = [live_sample(r) for _, r in T.iterrows()]
T["live_sample"] = [x[3] for x in ls]
T["live_sample_n"] = [x[0] for x in ls]
T["live_sample_mean_R"] = [x[1] for x in ls]
T["live_sample_se_R"] = [x[2] for x in ls]
T["fy_breakeven_gap_R_nowvol"] = -T["fy_nowvol_mean_R"]           # extra R per trade an AI would have to add at today's volatility
T["fy_sized_per_day"] = T["fy_n"] / (T["fy_signals"] / T["fy_per_day"])   # signals the v4 sizing rule can enter, per day
T["ai_freq_ok"] = T["fy_sized_per_day"] >= 1.0                    # >= 1 enterable signal / day over the six coins on average
order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4, "thin": 5}
T["_o"] = T["grade"].map(order)
T = T.sort_values(["kind", "tf", "_o", "fy_mean_R"], ascending=[True, True, True, False]).drop(columns="_o")
lead = ["kind", "strategy", "tf", "grade", "fy_class", "live_class", "fy_signals", "fy_per_day", "fy_sized_per_day", "live_signals_per_day", "freq_ratio_live_vs_5y",
        "fy_n", "fy_mean_R", "fy_t", "fy_is_mean_R", "fy_cf_mean_R", "fy_last12_mean_R", "fy_gross_R", "fy_is_gross_R", "fy_cf_gross_R",
        "fy_gross_t", "fy_cost_R", "fy_nowvol_mean_R", "fy_breakeven_gap_R_nowvol", "fy_mean_ret", "fy_win_pct", "live_sample", "live_sample_n",
        "live_sample_mean_R", "live_sample_se_R", "win_rp_pct_live", "win_rp_p_two", "win_rp_q_bh", "win_v3a_pct_live", "win_v3a_p_two",
        "live_entered_n", "live_entered_mean_R", "ai_freq_ok"]
T = T[lead + [c for c in T.columns if c not in lead]]
T.to_csv(os.path.join(W, "fiveyear_vs_live.csv"), index=False)

# ---------------- candidates (best of what exists; nothing here is 5-year net positive unless fy_class == P)
cand = []
for kind in ("strategy", "ds200"):
    for grp, tfs in (("15m/30m", ("15m", "30m")), ("1h/4h", ("1h", "4h"))):
        x = T[(T["kind"] == kind) & T["tf"].isin(tfs) & T["grade"].isin(["A", "B", "C"])].copy()
        x["gross_both_halves_pos"] = (x["fy_is_gross_R"] > 0) & (x["fy_cf_gross_R"] > 0)
        x = x.sort_values(["grade", "gross_both_halves_pos", "fy_mean_R"], ascending=[True, False, False])
        for _, r in x.iterrows():
            cand.append(dict(kind=kind, group=grp, strategy=r["strategy"], tf=r["tf"], grade=r["grade"], fy_class=r["fy_class"],
                             live_class=r["live_class"], fy_per_day=r["fy_per_day"], fy_sized_per_day=r["fy_sized_per_day"], fy_mean_R=r["fy_mean_R"], fy_t=r["fy_t"],
                             fy_is_mean_R=r["fy_is_mean_R"], fy_cf_mean_R=r["fy_cf_mean_R"], fy_gross_R=r["fy_gross_R"],
                             fy_is_gross_R=r["fy_is_gross_R"], fy_cf_gross_R=r["fy_cf_gross_R"], fy_gross_t=r["fy_gross_t"],
                             fy_nowvol_mean_R=r["fy_nowvol_mean_R"], live_n=r["live_sample_n"], live_mean_R=r["live_sample_mean_R"],
                             live_se_R=r["live_sample_se_R"], gross_both_halves_pos=r["gross_both_halves_pos"], ai_freq_ok=r["ai_freq_ok"]))
CA = pd.DataFrame(cand)
CA.to_csv(os.path.join(W, "fy_candidates.csv"), index=False)


# ---------------- notes
def f(x, d=3, sign=True):
    if x is None or not np.isfinite(x):
        return "na"
    return (f"{x:+.{d}f}" if sign else f"{x:.{d}f}")


notes = []
for _, r in T.iterrows():
    n, mu, se, lab = r["live_sample_n"], r["live_sample_mean_R"], r["live_sample_se_R"], r["live_sample"]
    num = (f"5y n={int(r['fy_n']) if np.isfinite(r['fy_n']) else 0} ({f(r['fy_sized_per_day'], 2, False)}/d enterable) R={f(r['fy_mean_R'])} t={f(r['fy_t'], 1)} "
           f"IS/CF {f(r['fy_is_mean_R'], 2)}/{f(r['fy_cf_mean_R'], 2)} gross {f(r['fy_gross_R'])} nowvol {f(r['fy_nowvol_mean_R'], 2)} | "
           f"live {lab} n={int(n)} R={f(mu, 2)} se={f(se, 2, False)} entered n={int(r['live_entered_n']) if np.isfinite(r.get('live_entered_n', np.nan)) else 0} "
           f"| freq x{f(r['freq_ratio_live_vs_5y'], 2, False)}")
    fc, lc = r["fy_class"], r["live_class"]
    txt = {"P": "5y net positive both halves (weak t)", "Z+": "5y net not distinguishable from 0, gross>0 (low power)",
           "Z-": "5y not distinguishable from 0 but gross<=0 (low power)", "N+": "5y loses after costs; small gross edge",
           "NN": "5y loses; no gross edge", "thin": "too few 5y signals"}[fc]
    ltxt = {"L++": "live clearly positive", "L+": "live positive (noise-level)", "L-": "live negative (noise-level)",
            "L--": "live clearly negative", "L_thin": "live too thin"}[lc]
    extra = []
    if np.isfinite(r.get("fy_sized_per_day", np.nan)) and r["fy_sized_per_day"] < 1:
        extra.append("rare (<1 enterable signal/day)")
    q = r.get("win_rp_q_bh", np.nan)
    if np.isfinite(r.get("win_rp_p_two", np.nan)) and r["win_rp_p_two"] < 0.05:
        extra.append(f"live outside 5y window 95% band (raw p {r['win_rp_p_two']:.3f}, BH q {q:.2f})")
    notes.append(dict(strategy=f"{r['strategy']} ({r['kind']})", timeframe=r["tf"], grade=r["grade"], numbers=num,
                      note="; ".join([txt, ltxt] + extra)))
json.dump(notes, open(os.path.join(W, "strategy_notes.json"), "w"), indent=0)
print(T["grade"].value_counts().to_dict())
print(pd.crosstab([T["kind"], T["tf"]], T["grade"]))
print(pd.crosstab([T["kind"], T["tf"]], T["fy_class"]))
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)
print(CA.round(3).to_string())
