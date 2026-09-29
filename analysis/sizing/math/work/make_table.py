"""Builds the compact TF x L table and the compatibility verdict from the CSVs (no new simulation)."""
import numpy as np
import pandas as pd
from common import *

br = pd.read_csv(f"{OUT}/bracket_zero_edge.csv")
dist = pd.read_csv(f"{OUT}/tf_L_distances.csv")
dr = pd.read_csv(f"{OUT}/drift_breakeven_5m.csv")
eq = pd.read_csv(f"{OUT}/equity_100trades.csv")

liq = br[br.variant == "liq"]
own = liq[liq.res == liq.tf].set_index(["tf", "L"])
r5 = liq[liq.res == "5m"].set_index(["tf", "L"])
dd = dist.set_index(["tf", "L"])
drl = dr[dr.variant == "liq"].set_index("L")

rows = []
for tf in TFS:
    for L in LEVS:
        a, b, d = own.loc[(tf, L)], r5.loc[(tf, L)], dd.loc[(tf, L)]
        rows.append({
            "TF": tf, "L": L,
            "tp%": round(100 * tp_dist(L), 3), "liq%": round(100 * d_liq(L), 3),
            "tp/ATR": round(d.tp_over_atr, 2), "liq/ATR": round(d.liq_over_atr, 2),
            "P(liq) hold 16 bars": round(d.p_liq_hold16, 3),
            "exit in entry bar": round(a.p_exit_entrybar, 3),
            "P(TP1st) own-bar adv": round(a.pTP_adv, 3), "P(TP1st) own-bar fav": round(a.pTP_fav, 3),
            "P(TP1st) 5m-path": round(b.pTP_adv, 3),
            "E[ROE] own adv %": round(100 * a.EROE_adv, 2), "E[ROE] own fav %": round(100 * a.EROE_fav, 2),
            "E[ROE] 5m-path %": round(100 * b.EROE_adv, 2), "se %": round(100 * b.EROE_se_adv, 2),
            "req P(TP1st)": round(b.pstar_adv, 3), "req edge dp (pp)": round(100 * (b.pstar_adv - b.pTP_adv), 1),
            "req drift IR (inject)": round(drl.loc[L, "breakeven_ir_injected"], 1),
            "E[dEq] M20 %": round(100 * 0.20 * b.EROE_adv, 2), "E[dEq] M40 %": round(100 * 0.40 * b.EROE_adv, 2),
        })
T = pd.DataFrame(rows)
T.to_csv(f"{OUT}/compact_table.csv", index=False)

# compatibility verdict for L >= 20 (thresholds are judgement calls, stated in NOTES.md)
V = []
for _, r in T[T.L >= 20].iterrows():
    fails = []
    if r["liq/ATR"] < 3: fails.append("liq<3ATR")
    if r["tp/ATR"] < 0.5: fails.append("TP<0.5ATR")
    if r["exit in entry bar"] >= 0.5: fails.append("entry-bar>=50%")
    if r["P(liq) hold 16 bars"] >= 0.10: fails.append("P(liq16)>=10%")
    fee_share = RT / tp_dist(r.L)
    if fee_share > 1 / 3: fails.append("fees>1/3 TP")
    V.append(dict(TF=r.TF, L=r.L, fee_share_of_tp=round(fee_share, 2), fails=";".join(fails) or "-",
                  n_fail=len(fails)))
V = pd.DataFrame(V)
V.to_csv(f"{OUT}/compat_verdict.csv", index=False)
piv = V.pivot(index="TF", columns="L", values="fails").loc[TFS]


def md(df):
    cols = list(df.columns)
    s = "| " + " | ".join(map(str, cols)) + " |\n|" + "---|" * len(cols) + "\n"
    for _, r in df.iterrows():
        s += "| " + " | ".join(str(r[c]) for c in cols) + " |\n"
    return s


with open(f"{OUT}/compact_table.md", "w") as f:
    f.write(md(T[["TF", "L", "tp%", "liq%", "tp/ATR", "liq/ATR", "P(liq) hold 16 bars", "exit in entry bar",
                  "P(TP1st) own-bar adv", "P(TP1st) own-bar fav", "P(TP1st) 5m-path",
                  "E[ROE] own adv %", "E[ROE] own fav %", "E[ROE] 5m-path %", "se %",
                  "req P(TP1st)", "req edge dp (pp)", "req drift IR (inject)"]]))
    f.write("\n")
    f.write(md(piv.reset_index()))
    e = eq[(eq.variant == "liq") & (eq.scenario == "zero_edge")]
    f.write("\n")
    f.write(md(e.pivot(index="L", columns="M", values="median_mult").round(3).reset_index()))
    f.write("\n")
    f.write(md(e.pivot(index="L", columns="M", values="p_below_half").round(3).reset_index()))
    f.write("\n")
    f.write(md(e.pivot(index="L", columns="M", values="p_win_needed_log").round(3).reset_index()))
pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 40)
print(T.to_string(index=False))
print(piv.to_string())
