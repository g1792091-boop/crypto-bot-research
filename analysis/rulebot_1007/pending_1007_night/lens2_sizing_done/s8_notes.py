"""Per strategy x tfset sizing notes (for lens2_sizing.json strategy_notes).
    python3 -I -B s8_notes.py <out_dir>"""
import json, os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import pandas as pd
O = sys.argv[1]
p = pd.read_csv(os.path.join(O, "s3_paths.csv"))
q = pd.read_csv(os.path.join(O, "s3_sequences.csv"))
notes = []
for tfset in ("15m+30m", "15m", "30m", "1h", "4h"):
    for s in sorted(q.strategy.unique()):
        k = q[(q.strategy == s) & (q.tfset == tfset) & (q.policy == "K30")]
        if not len(k):
            continue
        k = k.iloc[0]
        def g(pol, size, edge, H=76, col="ruin50"):
            v = p[(p.strategy == s) & (p.tfset == tfset) & (p.policy == pol) & (p["size"] == size) & (p.edge == edge) & (p.H == H)]
            return float(v[col].iloc[0]) if len(v) else float("nan")
        r1c, r2c, r2n, m30n = g("K30", "r1", "mcost"), g("K30", "r2", "mcost"), g("K30", "r2", "net0"), g("M30", "L%", "net0")
        f2c = g("K30", "r2", "mcost", col="final_med")
        pd_ = k.per_day
        grade = "cost-drag high" if pd_ * k.mean_cR >= 0.4 else ("cost-drag medium" if pd_ * k.mean_cR >= 0.15 else "cost-drag low")
        notes.append(dict(strategy=s, timeframe=tfset, grade=grade,
                          numbers=(f"5y one-position K30: {pd_:.2f} trades/day, house mean R {k.mean_R:+.3f} (gross {k.mean_gR:+.3f}, cost {k.mean_cR:.3f}R), "
                                   f"cost drag {pd_ * k.mean_cR:.2f}R/day; to 12/31 (76 d) edge=-cost: P(eq<50%) r1 {r1c:.2f} r2 {r2c:.2f} "
                                   f"(median end x{f2c:.2f}); edge 0 net: r2 {r2n:.2f}, margin 30x rule {m30n:.2f}"),
                          note="Size by risk per stop; with the 5-year cost drag this cell needs >= "
                               f"{k.mean_cR:.2f}R/trade of AI-added edge just to break even; ruin numbers are bootstrap (7-day blocks) of 5y days."))
json.dump(notes, open(os.path.join(O, "strategy_notes.json"), "w"), indent=1)
print(len(notes)); print(json.dumps(notes[:2], indent=1))
