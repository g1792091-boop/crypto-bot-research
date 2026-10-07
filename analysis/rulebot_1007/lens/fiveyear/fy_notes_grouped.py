"""Grouped notes for the final answer: one entry per A/B/C cell, one entry per strategy for its D/F/thin cells.
python3 -I -B fy_notes_grouped.py <work_out_dir>"""
import json, os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
W = sys.argv[1]
T = pd.read_csv(os.path.join(W, "fiveyear_vs_live.csv"), keep_default_na=False, na_values=[""])
TFO = {"5m": 0, "15m": 1, "30m": 2, "1h": 3, "4h": 4}
def f(x, d=2):
    try:
        x = float(x)
    except Exception:
        return "na"
    return "na" if not np.isfinite(x) else f"{x:+.{d}f}"
def cellnum(r, long=True):
    live = f"{r['live_sample']}{int(r['live_sample_n'])} {f(r['live_sample_mean_R'])}" + (f"±{float(r['live_sample_se_R']):.2f}" if np.isfinite(float(r['live_sample_se_R'])) else "")
    if not np.isfinite(float(r["fy_mean_R"])):
        return f"5y thin | live {live}"
    s = f"5y {f(r['fy_mean_R'])} t{float(r['fy_t']):.0f}"
    if long:
        s += f" IS{f(r['fy_is_mean_R'])} CF{f(r['fy_cf_mean_R'])} g{f(r['fy_gross_R'],3)} now{f(r['fy_nowvol_mean_R'])} {float(r['fy_sized_per_day']):.1f}/d"
    else:
        s += f" g{f(r['fy_gross_R'],3)}"
    return s + f" | live {live}"
out = []
T["_o"] = T["tf"].map(TFO)
for _, r in T[T["grade"].isin(["A", "B", "C"])].sort_values(["kind", "_o", "grade"]).iterrows():
    ex = [f"{r['fy_class']}/{r['live_class']}"]
    if r["tf"] != "5m" and float(r.get("live_v3a_n") or 0) >= 10 and float(r.get("live_rp_n") or 0) >= 10 and np.sign(float(r["live_v3a_mean_R"])) != np.sign(float(r["live_rp_mean_R"])):
        ex.append(f"v3a {f(r['live_v3a_mean_R'])} opp. sign")
    if float(r["fy_sized_per_day"]) < 1:
        ex.append("rare")
    out.append({"strategy": r["strategy"], "timeframe": r["tf"], "grade": r["grade"], "numbers": cellnum(r), "note": "; ".join(ex)})
for (k, s), g in T[~T["grade"].isin(["A", "B", "C"])].groupby(["kind", "strategy"]):
    g = g.sort_values("_o")
    out.append({"strategy": s, "timeframe": "/".join(g["tf"]), "grade": "/".join(g["grade"]),
                "numbers": " ; ".join(f"{r['tf']}: " + cellnum(r, long=False) for _, r in g.iterrows()),
                "note": " ".join(f"{r['tf']}:{r['fy_class']}/{r['live_class']}" for _, r in g.iterrows())})
json.dump(out, open(os.path.join(W, "strategy_notes_grouped.json"), "w"), separators=(",", ":"), ensure_ascii=False)
print(len(out), sum(len(json.dumps(x, separators=(",", ":"), ensure_ascii=False)) for x in out))
