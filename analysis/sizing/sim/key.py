import sys, os, pandas as pd, numpy as np
tag = sys.argv[1]; tfs = sys.argv[2:]
combos = ["P0|B|10","P1|B|10","P2|B|10","P3|A|10","P3|B|10","P3|C|10","P4|A|10","P4|B|10","P4|C|10","P5|A|10","P5|B|10","P5|C|10","P5c|B|10","P6|B|none","P6h|B|none","P6|B|10"]
edges = [0.0, 0.05, 0.1, 0.2, 0.4]
for tf in tfs:
    p = f"out/{tag}/{tf}_metrics.csv"
    if not os.path.exists(p): continue
    M = pd.read_csv(p)
    print(f"\n##### {tf}  (cells: 30d median x | 1y median x | 1y P(ruin) | 1y P(<50%) | liq% | trades/30d)")
    print("combo".ljust(11) + "".join(f"D={e:.2f}%".rjust(36) for e in edges))
    for c in combos:
        line = c.ljust(11)
        for e in edges:
            r = M[(M.combo == c) & (np.isclose(M.edge_pct, e))]
            if len(r) == 0: line += "n/a".rjust(36); continue
            r = r.iloc[0]
            cell = f"{r['30d_median_mult']:.3f}|{r['1y_median_mult']:.3g}|{r['1y_p_ruin']:.2f}|{r['1y_p_below50']:.2f}|{100*r.liq_share:.1f}|{r.trades_per_30d:.0f}"
            line += cell.rjust(36)
        print(line)
