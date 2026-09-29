"""Markdown tables for NOTES.md from out/<tag>/*.csv."""
import json, os, sys
import numpy as np
import pandas as pd

TAG = sys.argv[1] if len(sys.argv) > 1 else "base"
d = os.path.join("out", TAG)
TFS = [tf for tf in ["5m", "15m", "1h", "4h", "1d"] if os.path.exists(os.path.join(d, f"{tf}_metrics.csv"))]
M = pd.concat([pd.read_csv(os.path.join(d, f"{tf}_metrics.csv")) for tf in TFS], ignore_index=True)
out = []
P = out.append

# ---------------------------------------------------------------- setup
P("### Setup per TF (measured)\n")
P("| TF | H (bars) | hold cap | signals/day tried | trades/30d taken (P0 A / P3 A / P4 A) | E\\|r_H\\| pooled | median ATR% (BTC..DOGE range) | q at D=0.10% (min-max over coins) | P5 mean L / M / notional | P6 mean L / M / notional |")
P("|---|---|---|---|---|---|---|---|---|---|")
for tf in TFS:
    m = json.load(open(os.path.join(d, f"{tf}_meta.json")))
    g = M[(M.tf == tf) & np.isclose(M.edge_pct, 0.10)]
    def row(c):
        return g[g.combo == c].iloc[0]
    atr = m["atr_med"]; e = m["edges"]
    qi = e.index(0.001) if 0.001 in e else None
    q = np.array(m["q"][qi]) if qi is not None else None
    hold = f"{m['H'] * m['tfm'] / 60:.3g} h"
    P(f"| {tf} | {m['H']} | {hold} | {m['lam']:.2f} | {row('P0|A|10').trades_per_30d:.0f} / {row('P3|A|10').trades_per_30d:.0f} / {row('P4|A|10').trades_per_30d:.0f} | "
      f"{100 * m['Eabs_pooled']:.2f}% | {100 * min(atr.values()):.2f}-{100 * max(atr.values()):.2f}% | "
      f"{q.min():.3f}-{q.max():.3f} | {row('P5|A|10').mean_L:.1f}x / {100 * row('P5|A|10').mean_M:.0f}% / {row('P5|A|10').mean_N:.1f}x | "
      f"{row('P6|B|none').mean_L:.1f}x / {100 * row('P6|B|none').mean_M:.1f}% / {row('P6|B|none').mean_N:.2f}x |")

# ---------------------------------------------------------------- main tables
SHOW = [("P0|B|10", "P0 1x, 1.5ATR stop"), ("P1|B|10", "P1 25%x5, 1.5ATR stop"), ("P2|B|10", "P2 25%x10, 1.5ATR stop"),
        ("P3|A|10", "P3 20%x20, no stop"), ("P3|C|10", "P3 20%x20, stop 0.5 d_liq"),
        ("P4|A|10", "P4 40%x50, no stop"), ("P4|C|10", "P4 40%x50, stop 0.5 d_liq"),
        ("P5|A|10", "P5 adaptive 20-40%, 20-50x, no stop"), ("P5|C|10", "P5 adaptive, stop 0.5 d_liq"),
        ("P5c|C|10", "P5c perfect-confidence margin, stop 0.5 d_liq"),
        ("P6|B|none", "P6 risk 1% to 1.5ATR stop, <=10x"), ("P6h|B|none", "P6h risk 0.5%")]
EDS = [0.0, 0.10, 0.20, 0.40]
for tf in TFS:
    P(f"\n### {tf}: 30-day median multiple / P(30-day loss) / P(equity < 50% within 1y) / P(ruin < 10% within 1y)\n")
    P("TP = +10% ROE (price 10%/L) for P0-P5; P6 has no TP. Last two columns at D = 0.10%.\n")
    P("| policy | " + " | ".join(f"D={e:.2f}%" for e in EDS) + " | liq % of trades | 30d max DD (median) |")
    P("|---|" + "---|" * (len(EDS) + 2))
    for c, lab in SHOW:
        cells = []
        for e in EDS:
            r = M[(M.tf == tf) & (M.combo == c) & np.isclose(M.edge_pct, e)]
            if len(r) == 0:
                cells.append("n/a"); continue
            r = r.iloc[0]
            cells.append(f"{r['30d_median_mult']:.2f} / {r['30d_p_loss']:.2f} / {r['1y_p_below50']:.2f} / {r['1y_p_ruin']:.2f}")
        r = M[(M.tf == tf) & (M.combo == c) & np.isclose(M.edge_pct, 0.10)].iloc[0]
        P(f"| {lab} | " + " | ".join(cells) + f" | {100 * r.liq_share:.1f} | {100 * r['30d_mdd_median']:.0f}% |")

# ---------------------------------------------------------------- IS span
P("\n### Whole IS span (2021-08 to 2024-06, ~35 months, one path per seed): median final multiple across seeds [share of seeds ruined]\n")
P("| policy | TF | " + " | ".join(f"D={e:.2f}%" for e in EDS) + " |")
P("|---|---|" + "---|" * len(EDS))
for c, lab in [("P0|B|10", "P0 1x"), ("P3|A|10", "P3 20%x20"), ("P4|A|10", "P4 40%x50"), ("P5|A|10", "P5 adaptive"), ("P6|B|none", "P6 1% risk"), ("P6h|B|none", "P6h 0.5% risk")]:
    for tf in TFS:
        cells = []
        for e in EDS:
            r = M[(M.tf == tf) & (M.combo == c) & np.isclose(M.edge_pct, e)]
            if len(r) == 0:
                cells.append("n/a"); continue
            r = r.iloc[0]
            cells.append(f"{r.IS_median_mult:.3g} [{r.IS_p_ruin:.2f}]")
        P(f"| {lab} | {tf} | " + " | ".join(cells) + " |")

# ---------------------------------------------------------------- min edge
ME = pd.read_csv(os.path.join(d, "min_edge.csv"))
P("\n### Minimum planted gross drift per trade (%, at horizon H) for median 1-year multiple > 1 AND P(ruin within 1y) < 10%\n")
P("'>X' = not reached up to the largest feasible planted drift X (q <= 1 on every coin).\n")
ROWS = [("P0|A|10", "P0 1x, no stop (time exit)"), ("P0|B|10", "P0 1x, 1.5ATR stop"), ("P2|C|10", "P2 25%x10, stop 0.5 d_liq"),
        ("P3|A|10", "P3 20%x20 TP10 no stop"), ("P3|B|10", "P3 TP10 1.5ATR stop"), ("P3|C|10", "P3 TP10 stop 0.5 d_liq"),
        ("P3|B|30", "P3 TP30 1.5ATR stop"), ("P3|B|100", "P3 TP100 1.5ATR stop"),
        ("P4|A|10", "P4 40%x50 TP10 no stop"), ("P4|B|10", "P4 TP10 1.5ATR"), ("P4|C|10", "P4 TP10 stop 0.5 d_liq"), ("P4|B|100", "P4 TP100 1.5ATR"),
        ("P5|A|10", "P5 adaptive TP10 no stop"), ("P5|B|10", "P5 TP10 1.5ATR"), ("P5|C|10", "P5 TP10 stop 0.5 d_liq"), ("P5|B|100", "P5 TP100 1.5ATR"),
        ("P5c|C|10", "P5c perfect confidence, stop 0.5 d_liq"),
        ("P6|B|none", "P6 risk 1%, <=10x"), ("P6h|B|none", "P6h risk 0.5%, <=10x")]
P("| policy | " + " | ".join(TFS) + " |")
P("|---|" + "---|" * len(TFS))
for c, lab in ROWS:
    cells = []
    for tf in TFS:
        r = ME[(ME.tf == tf) & (ME.combo == c)]
        if len(r) == 0:
            cells.append("n/a"); continue
        r = r.iloc[0]
        cells.append(f">{r.max_edge_tested:.2f}" if pd.isna(r.min_edge_pct) else f"{r.min_edge_pct:.2f}")
    P(f"| {lab} | " + " | ".join(cells) + " |")

# ---------------------------------------------------------------- capture + kelly
P("\n### Edge capture (slope of realised gross move per trade vs planted drift, edges <= 0.40%) and liquidation share at D=0\n")
P("| policy | " + " | ".join(TFS) + " |")
P("|---|" + "---|" * len(TFS))
for c, lab in [("P0|A|10", "P0 time exit"), ("P0|B|10", "P0 1.5ATR stop"), ("P3|A|10", "P3 TP10 (0.5% price)"), ("P3|B|100", "P3 TP100 (5% price)"),
               ("P4|A|10", "P4 TP10 (0.2% price)"), ("P5|A|10", "P5 TP10"), ("P6|B|none", "P6")]:
    cells = []
    for tf in TFS:
        g = M[(M.tf == tf) & (M.combo == c) & (M.edge_pct <= 0.4001)]
        sl = np.polyfit(g.edge_pct, g.gross_pct, 1)[0]
        l0 = M[(M.tf == tf) & (M.combo == c) & np.isclose(M.edge_pct, 0)].iloc[0].liq_share
        cells.append(f"{sl:.2f} (liq {100 * l0:.1f}%)")
    P(f"| {lab} | " + " | ".join(cells) + " |")

P("\n### Growth-optimal (full Kelly) notional for the reference exit (1.5 ATR stop + time exit, cross margin, realistic costs)\n")
P("Planted drift at which full Kelly notional reaches 1x / 4x (= P3's floor, M 20% x L 20) / 8x (P3 = half Kelly) / 20x (P4). "
  "'never' = not reached at any feasible planted drift (exact Kelly is also capped at 1/|worst trade|).\n")
P("| TF | net mean per trade at D=0 | Kelly N at D=0.10% | Kelly N at D=0.20% | Kelly N at D=0.40% | D for N*=1x | D for N*=4x | D for N*=8x | D for N*=20x | Kelly cap (1/worst) |")
P("|---|---|---|---|---|---|---|---|---|---|")
for tf in TFS:
    k = pd.read_csv(os.path.join(d, f"{tf}_kelly.csv"))
    def at(e):
        r = k[np.isclose(k.edge_pct, e)]
        return f"{r.iloc[0].kelly_N:.2f}" if len(r) else "n/a"
    def cross(t):
        x, y = k.edge_pct.values, k.kelly_N.values
        idx = np.where(y >= t)[0]
        if len(idx) == 0:
            return "never"
        i = idx[0]
        if i == 0:
            return f"{x[0]:.2f}"
        return f"{x[i - 1] + (t - y[i - 1]) * (x[i] - x[i - 1]) / (y[i] - y[i - 1]):.2f}"
    cap = k.kelly_N.max()
    P(f"| {tf} | {k.iloc[0].mean_y_pct:.3f}% | {at(0.10)} | {at(0.20)} | {at(0.40)} | {cross(1)} | {cross(4)} | {cross(8)} | {cross(20)} | {cap:.2f} |")

open(os.path.join(d, "summary.md"), "w").write("\n".join(out) + "\n")
print("\n".join(out))
