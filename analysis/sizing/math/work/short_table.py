"""Condensed markdown version of compact_table.csv (for NOTES.md)."""
import pandas as pd
from common import OUT
T = pd.read_csv(f"{OUT}/compact_table.csv")
def md(df):
    cols = list(df.columns); s = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    for _, r in df.iterrows(): s += "| " + " | ".join(str(r[c]) for c in cols) + " |\n"
    return s
o = pd.DataFrame({
    "TF": T["TF"], "L": T["L"].astype(str) + "x",
    "TP/ATR": T["tp/ATR"].map("{:.2f}".format), "liq/ATR": T["liq/ATR"].map("{:.2f}".format),
    "P(liq) if held 16 bars": T["P(liq) hold 16 bars"].map("{:.1%}".format),
    "ends in entry bar": T["exit in entry bar"].map("{:.0%}".format),
    "P(TP first) own-bar adv / fav": T.apply(lambda r: f"{r['P(TP1st) own-bar adv']:.3f} / {r['P(TP1st) own-bar fav']:.3f}", axis=1),
    "P(TP first) 5m path": T["P(TP1st) 5m-path"].map("**{:.3f}**".format),
    "E[ROE] own-bar adv / fav": T.apply(lambda r: f"{r['E[ROE] own adv %']:.1f}% / {r['E[ROE] own fav %']:.1f}%", axis=1),
    "E[ROE] 5m path (se)": T.apply(lambda r: f"**{r['E[ROE] 5m-path %']:.2f}%** ({r['se %']:.2f})", axis=1),
    "required P(TP first)": T.apply(lambda r: f"{r['req P(TP1st)']:.3f} (+{r['req edge dp (pp)']:.1f}pp)", axis=1),
    "required drift, ann. IR": T["req drift IR (inject)"].map("{:.1f}".format),
})
open(f"{OUT}/compact_table_short.md", "w").write(md(o))
print(md(o))
