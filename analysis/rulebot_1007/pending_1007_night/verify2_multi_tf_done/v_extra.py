"""Paired diffs with week-cluster bootstrap, R/day, switch decomposition, wide-stop-first tie rule.
python3 -I -B v_extra.py <verify_dir> <sig_dir>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v_sim as M  # loads outc.csv, bars
import numpy as np, pandas as pd

V = M.V
tr = pd.read_csv(os.path.join(V, "v_trades.csv.gz"))
# extra tie rule: widest stop (largest ATR%) first
ext = []
for nm, g0 in M.d.groupby("strat"):
    g0 = g0.assign(ntf=-g0.tf)
    for sc in ("A", "ALL"):
        g = g0[g0.tf.isin(M.SCOPES[sc]) & (g0.lev > 0)]
        for rule in ("FC", "SWH"):
            t, bl, nsw = M.account(g, rule, "wide_first")
            ext.append(t.assign(strat=nm, combo=f"{sc}|{rule}|wide_first"))
tr = pd.concat([tr, pd.concat(ext)[tr.columns]])
tr["grp"] = np.where(tr.strat.str.startswith("F"), "ds", "core")
tr["wk"] = tr.e // (96 * 7)
tr["cost"] = tr.gross - tr.R
rng = np.random.default_rng(1)


def paired(a, b, grp):
    x = tr[(tr.combo == a) & (tr.grp == grp)]; y = tr[(tr.combo == b) & (tr.grp == grp)]
    ps = x.groupby("strat").R.mean() - y.groupby("strat").R.mean()
    wk = np.union1d(x.wk.unique(), y.wk.unique())
    xs = x.groupby("wk").R.agg(["sum", "count"]).reindex(wk, fill_value=0)
    ys = y.groupby("wk").R.agg(["sum", "count"]).reindex(wk, fill_value=0)
    bs = []
    for _ in range(1000):
        i = rng.integers(0, len(wk), len(wk))
        bs.append(xs["sum"].values[i].sum() / xs["count"].values[i].sum() - ys["sum"].values[i].sum() / ys["count"].values[i].sum())
    dg = x.gross.mean() - y.gross.mean(); dc = x.cost.mean() - y.cost.mean()
    return f"{grp} {a} - {b}: {x.R.mean() - y.R.mean():+.4f} [{np.percentile(bs, 2.5):+.4f},{np.percentile(bs, 97.5):+.4f}] better {int((ps > 0).sum())}/{len(ps)} | dgross {dg:+.4f} dcost {dc:+.4f}"


for grp in ("core", "ds"):
    for a, b in [("ALL|SWH|long_first", "A|FC|coin_short"), ("ALL|FC|coin_short", "A|FC|coin_short"),
                 ("HI|FC|coin_short", "A|FC|coin_short"), ("ALL|SW|coin_short", "ALL|FC|coin_short"),
                 ("A|SW|coin_short", "A|FC|coin_short"), ("ALL|SWH|long_first", "ALL|FC|coin_short"),
                 ("ALL|SWH|long_first", "ALL|FC|long_first"), ("ALL|FC|long_first", "ALL|FC|coin_short"),
                 ("ALL|FC|random", "ALL|FC|coin_short"), ("A|FC|random", "A|FC|coin_short"),
                 ("A|FC|wide_first", "A|FC|coin_short"), ("ALL|SWH|wide_first", "ALL|SWH|long_first"),
                 ("ALL|SWH|wide_first", "A|FC|coin_short")]:
        print(paired(a, b, grp))
DAYS = M.DAYS
print("\nper-day totals (mean over strategies): R/day, cost/day, trades/day")
pd_ = tr.groupby(["grp", "combo", "strat"]).agg(R=("R", "sum"), c=("cost", "sum"), n=("R", "size")) / DAYS
print(pd_.groupby(["grp", "combo"]).mean().round(3).to_string())
# switch decomposition: switched-out trades R at switch vs alone R
s = tr[tr.sw == 1]
print("\nswitched-out trades: n", len(s), "R at switch %.4f vs alone %.4f; cost %.4f" % (s.R.mean(), s.aloneR.mean(), s.cost.mean()))
for c, g in s.groupby("combo"):
    print(c, len(g), "R_sw %.4f alone %.4f diff %+.4f" % (g.R.mean(), g.aloneR.mean(), (g.R - g.aloneR).mean()))
