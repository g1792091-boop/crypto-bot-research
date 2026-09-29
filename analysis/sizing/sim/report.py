"""Min-edge search and compact tables from out/<tag>/<tf>_metrics.csv."""
import argparse, os, glob
import numpy as np
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="base")
args = ap.parse_args()
d = os.path.join("out", args.tag)
TFS = [tf for tf in ["5m", "15m", "1h", "4h", "1d"] if os.path.exists(os.path.join(d, f"{tf}_metrics.csv"))]
M = pd.concat([pd.read_csv(os.path.join(d, f"{tf}_metrics.csv")) for tf in TFS], ignore_index=True)


def crossing(x, y, thr):
    """smallest x where y >= thr and stays >= thr for all larger x (linear interpolation). None if never."""
    ok = y >= thr
    if not ok[-1]:
        return None
    # last index that fails
    fail = np.where(~ok)[0]
    if len(fail) == 0:
        return x[0]
    i = fail[-1]
    x0, x1, y0, y1 = x[i], x[i + 1], y[i], y[i + 1]
    return x0 + (thr - y0) * (x1 - x0) / (y1 - y0)


def min_edge(g):
    g = g.sort_values("edge_pct")
    x = g["edge_pct"].values
    a = crossing(x, np.log(g["1y_median_mult"].values), 0.0)
    b = crossing(x, -g["1y_p_ruin"].values, -0.10)
    if a is None or b is None:
        return None, a, b
    return max(a, b), a, b


rows = []
for (tf, combo), g in M.groupby(["tf", "combo"]):
    me, a, b = min_edge(g)
    rows.append(dict(tf=tf, combo=combo, min_edge_pct=me, edge_for_median_gt1=a, edge_for_pruin_lt10=b,
                     max_edge_tested=g["edge_pct"].max()))
ME = pd.DataFrame(rows)
ME.to_csv(os.path.join(d, "min_edge.csv"), index=False)

def fmt(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "none<=max"
    return f"{v:.3f}"

order = ["P0|A|10", "P0|B|10", "P1|B|10", "P2|B|10", "P2|C|10", "P3|A|10", "P3|B|10", "P3|C|10", "P3|B|30", "P3|B|100",
         "P4|A|10", "P4|B|10", "P4|C|10", "P4|B|100", "P5|A|10", "P5|B|10", "P5|C|10", "P5|B|100", "P5c|A|10", "P5c|B|10", "P5c|C|10", "P6|B|none", "P6h|B|none", "P6|B|10"]
with open(os.path.join(d, "min_edge_table.txt"), "w") as f:
    hdr = "combo".ljust(12) + "".join(tf.rjust(22) for tf in TFS)
    f.write("Min planted drift at H (% per trade, gross) for median 1y multiple > 1 AND P(ruin<10% within 1y) < 10%\n")
    f.write("cell = min_edge [edge for median>1 / edge for P(ruin)<10%]; 'none' = not reached at the largest feasible edge\n")
    f.write(hdr + "\n")
    for c in order:
        line = c.ljust(12)
        for tf in TFS:
            r = ME[(ME.tf == tf) & (ME.combo == c)]
            if len(r) == 0:
                line += "".rjust(22); continue
            r = r.iloc[0]
            cell = f"{fmt(r.min_edge_pct)} [{fmt(r.edge_for_median_gt1)}/{fmt(r.edge_for_pruin_lt10)}]"
            line += cell.rjust(22)
        f.write(line + "\n")
print(open(os.path.join(d, "min_edge_table.txt")).read())

cols = ["edge_pct", "trades_per_30d", "mean_N", "mean_L", "liq_share", "tp_share", "drift_H_pct", "gross_pct", "net_notional_pct",
        "eq_ret_pct", "30d_median_mult", "30d_p_loss", "30d_mdd_median", "1y_median_mult", "1y_p_below50", "1y_p_ruin", "IS_median_mult"]
with open(os.path.join(d, "tables.txt"), "w") as f:
    for tf in TFS:
        for c in order:
            g = M[(M.tf == tf) & (M.combo == c)].sort_values("edge_pct")
            if len(g) == 0:
                continue
            f.write(f"\n=== {tf} {c}\n")
            f.write(g[cols].to_string(index=False, float_format=lambda v: f"{v:.4g}") + "\n")
print("tables ->", os.path.join(d, "tables.txt"))
