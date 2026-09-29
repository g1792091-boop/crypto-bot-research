"""Cross-tag comparison of minimum edges (planted D*, and the realised gross move per trade at D*)."""
import os, subprocess
import numpy as np
import pandas as pd

TAGS = [t for t in ["base", "sub", "mark", "adv", "fav", "front", "maker"] if os.path.isdir(os.path.join("out", t))]
DESC = {"base": "base (raw wicks, O-L-H-C/O-H-L-C by bar colour, taker entry, edge at H)",
        "mark": "liquidation checked on a de-spiked price (wick parts > 0.5 ATR beyond the neighbouring bars removed; mark-price proxy); stops/TPs on raw bars", "adv": "adverse move first inside every bar",
        "fav": "favourable move first inside every bar", "front": "edge planted at H/4 bars (front-loaded; 1 bar on 4h/1d)",
        "maker": "maker (limit) entry 0.02 %, always filled",
        "sub": "exits resolved on the 5m bars inside each TF bar (15m/1h/4h/1d); the preferred check of intrabar order"}
COMB = [("P0|B|10", "P0 1x 1.5ATR"), ("P3|A|10", "P3 20%x20 TP10 no stop"), ("P3|C|10", "P3 TP10 stop .5dliq"),
        ("P4|A|10", "P4 40%x50 TP10 no stop"), ("P4|B|100", "P4 TP100 1.5ATR"), ("P5|A|10", "P5 TP10 no stop"),
        ("P5|C|10", "P5 TP10 stop .5dliq"), ("P6|B|none", "P6 1% risk"), ("P6h|B|none", "P6h 0.5% risk")]
TFS = ["5m", "15m", "1h", "4h", "1d"]
data = {}
for t in TAGS:
    d = os.path.join("out", t)
    tfs = [tf for tf in TFS if os.path.exists(os.path.join(d, f"{tf}_metrics.csv"))]
    if not tfs:
        continue
    subprocess.run(["python3", "report.py", "--tag", t], capture_output=True)
    M = pd.concat([pd.read_csv(os.path.join(d, f"{tf}_metrics.csv")) for tf in tfs], ignore_index=True)
    ME = pd.read_csv(os.path.join(d, "min_edge.csv"))
    data[t] = (M, ME, tfs)
out = ["| policy | variant | " + " | ".join(TFS) + " |", "|---|---|" + "---|" * len(TFS)]
for c, lab in COMB:
    for t in data:
        M, ME, tfs = data[t]
        cells = []
        for tf in TFS:
            r = ME[(ME.tf == tf) & (ME.combo == c)]
            if tf not in tfs or len(r) == 0:
                cells.append("-"); continue
            r = r.iloc[0]
            if pd.isna(r.min_edge_pct):
                cells.append(f">{r.max_edge_tested:.2f}"); continue
            g = M[(M.tf == tf) & (M.combo == c)].sort_values("edge_pct")
            gr = np.interp(r.min_edge_pct, g.edge_pct, g.gross_pct)
            cells.append(f"{r.min_edge_pct:.2f} ({gr:+.2f})")
        out.append(f"| {lab} | {t} | " + " | ".join(cells) + " |")
txt = "Cell = D* planted drift (%) for median 1y > 1 and P(ruin 1y) < 10%; in brackets the realised gross move per trade (%) at D*.\n\n" + \
      "\n".join(f"- {t}: {DESC[t]}" for t in data) + "\n\n" + "\n".join(out)
print(txt)
open("out/sens_table.md", "w").write(txt + "\n")
