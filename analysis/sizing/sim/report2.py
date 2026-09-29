"""Realised per-trade economics at the minimum planted edge, and cross-tag comparison of min edges."""
import os, sys
import numpy as np
import pandas as pd

TAGS = sys.argv[1:] or ["base"]
COMB = [("P0|B|10", "P0 1x 1.5ATR"), ("P3|A|10", "P3 20%x20 TP10 no stop"), ("P3|C|10", "P3 TP10 stop .5dliq"), ("P3|B|100", "P3 TP100 1.5ATR"),
        ("P4|A|10", "P4 40%x50 TP10"), ("P4|B|100", "P4 TP100 1.5ATR"), ("P5|A|10", "P5 TP10 no stop"), ("P5|C|10", "P5 TP10 stop .5dliq"),
        ("P5|B|100", "P5 TP100 1.5ATR"), ("P6|B|none", "P6 1% risk"), ("P6h|B|none", "P6h 0.5% risk")]
out = []
for tag in TAGS:
    d = os.path.join("out", tag)
    TFS = [tf for tf in ["5m", "15m", "1h", "4h", "1d"] if os.path.exists(os.path.join(d, f"{tf}_metrics.csv"))]
    if not TFS:
        continue
    M = pd.concat([pd.read_csv(os.path.join(d, f"{tf}_metrics.csv")) for tf in TFS], ignore_index=True)
    os.system(f"python3 report.py --tag {tag} > /dev/null")
    ME = pd.read_csv(os.path.join(d, "min_edge.csv"))
    out.append(f"\n#### tag={tag}: min planted drift D* (%) -> realised gross / net per unit notional (%) per trade at D*")
    out.append("| policy | " + " | ".join(TFS) + " |")
    out.append("|---|" + "---|" * len(TFS))
    for c, lab in COMB:
        cells = []
        for tf in TFS:
            r = ME[(ME.tf == tf) & (ME.combo == c)]
            if len(r) == 0:
                cells.append("n/a"); continue
            r = r.iloc[0]
            if pd.isna(r.min_edge_pct):
                cells.append(f">{r.max_edge_tested:.2f}"); continue
            g = M[(M.tf == tf) & (M.combo == c)].sort_values("edge_pct")
            gr = np.interp(r.min_edge_pct, g.edge_pct, g.gross_pct)
            ne = np.interp(r.min_edge_pct, g.edge_pct, g.net_notional_pct)
            cells.append(f"{r.min_edge_pct:.2f} -> {gr:+.3f} / {ne:+.3f}")
        out.append(f"| {lab} | " + " | ".join(cells) + " |")
txt = "\n".join(out)
print(txt)
open(os.path.join("out", "min_edge_realised_" + "_".join(TAGS) + ".md"), "w").write(txt + "\n")
