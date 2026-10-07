"""Compact strategy notes from fiveyear_vs_live.csv (final grades).   python3 -I -B fy_notes.py <work_out_dir>"""
import json, os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
W = sys.argv[1]
T = pd.read_csv(os.path.join(W, "fiveyear_vs_live.csv"))
DUP = {("F11_TSOUP", "15m"): "=F11_RAID=F13_RAID_PD", ("F11_RAID", "15m"): "=F11_TSOUP=F13_RAID_PD", ("F13_RAID_PD", "15m"): "=F11_RAID=F11_TSOUP",
       ("F17_Z_HL", "1h"): "=F17_Z", ("F17_Z", "1h"): "=F17_Z_HL", ("F5_BOX_HTF", "15m"): "=F5_BOX", ("F5_BOX", "15m"): "=F5_BOX_HTF",
       ("F5_BOX_HTF", "30m"): "=F5_BOX", ("F5_BOX", "30m"): "=F5_BOX_HTF", ("F11_RAID", "1h"): "=F13_RAID_PD", ("F13_RAID_PD", "1h"): "=F11_RAID",
       ("F10_OTE", "4h"): "=F16_FIB618", ("F16_FIB618", "4h"): "=F10_OTE"}
CLS = {"P": "5y net>0 both halves (t<1)", "Z+": "5y ~0 net (low power), gross>0", "Z-": "5y ~0 net (low power), gross<=0",
       "N+": "5y loses after cost, tiny gross edge", "NN": "5y loses, no gross edge", "thin": "5y too rare"}
LC = {"L++": "live clearly +", "L+": "live + (noise)", "L-": "live - (noise)", "L--": "live clearly -", "L_thin": "live too thin"}
def f(x, d=2):
    return "na" if x is None or not np.isfinite(x) else f"{x:+.{d}f}"
notes = []
for _, r in T.iterrows():
    num = (f"5y R{f(r['fy_mean_R'])} t{r['fy_t']:.0f} IS/CF{f(r['fy_is_mean_R'])}/{f(r['fy_cf_mean_R'])} g{f(r['fy_gross_R'],3)} now{f(r['fy_nowvol_mean_R'])} "
           f"{r['fy_sized_per_day']:.1f}/d | live {r['live_sample']} n{int(r['live_sample_n'])} R{f(r['live_sample_mean_R'])}"
           + (f"±{r['live_sample_se_R']:.2f}" if np.isfinite(r['live_sample_se_R']) else "")) if np.isfinite(r.get('fy_mean_R', np.nan)) else \
          f"5y n{int(r['fy_n']) if np.isfinite(r['fy_n']) else 0} | live {r['live_sample']} n{int(r['live_sample_n'])} R{f(r['live_sample_mean_R'])}"
    ex = [f"{r['fy_class']}/{r['live_class']}"]
    if r["tf"] != "5m" and (r.get("live_v3a_n", 0) or 0) >= 10 and (r.get("live_rp_n", 0) or 0) >= 10 and np.sign(r["live_v3a_mean_R"]) != np.sign(r["live_rp_mean_R"]):
        ex.append(f"v3a R{f(r['live_v3a_mean_R'])} opp. sign")
    if np.isfinite(r.get("fy_sized_per_day", np.nan)) and r["fy_sized_per_day"] < 1:
        ex.append("rare")
    if np.isfinite(r.get("win_rp_p_two", np.nan)) and r["win_rp_p_two"] < 0.05:
        ex.append(f"outside 5y window band p{r['win_rp_p_two']:.2f}, BH ns")
    d = DUP.get((r["strategy"], r["tf"]))
    if d:
        ex.append("dup" + d)
    notes.append({"strategy": f"{r['strategy']}" + (" [DS]" if r["kind"] == "ds200" else ""), "timeframe": r["tf"], "grade": r["grade"],
                  "numbers": num, "note": "; ".join(ex)})
json.dump(notes, open(os.path.join(W, "strategy_notes.json"), "w"), separators=(",", ":"))
print(len(notes), sum(len(json.dumps(x, separators=(",", ":"))) for x in notes))
