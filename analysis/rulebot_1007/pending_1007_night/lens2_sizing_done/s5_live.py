"""Live paper trades (all runs): realised loss per stop-out as % of equity by tf x leverage (rule bot: margin = L%),
what the same stop-outs would have cost at risk 2% per stop, and the live leverage mix / rejections.
    python3 -I -B s5_live.py <workdir> <out_real_dir> <out_dir>"""
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1]); sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
import common as C
O, OUT = sys.argv[2], sys.argv[3]
T = pd.read_csv(os.path.join(O, "trades_enriched.csv"))
T = T[T.kind.isin(["strategy", "ds200", "random"]) & T.tf.isin(["5m", "15m", "30m", "1h", "4h"])]
T["loss_pct_eq"] = T.pnl / T.eq_before
lpn = C.loss_per_notional(T.stop_frac.values, T.side.values)
T["risk2_pct_eq"] = 0.02 * T.R.values * T.stop_frac.values / lpn
T["loss_at_stop_planned"] = (T.qty * T.entry_price) * lpn / T.eq_before
rows = []
for (tf, lev), g in T.groupby(["tf", "leverage"]):
    sl = g[g.exit_reason == "SL"]
    rows.append(dict(tf=tf, lev=lev, n=len(g), n_sl=len(sl), planned_loss_at_stop_med=g.loss_at_stop_planned.median(),
                     sl_loss_pct_med=sl.loss_pct_eq.median() if len(sl) else np.nan,
                     sl_loss_pct_min=sl.loss_pct_eq.min() if len(sl) else np.nan,
                     sl_R_med=sl.R.median() if len(sl) else np.nan, sl_R_min=sl.R.min() if len(sl) else np.nan,
                     all_mean_pct_eq=g.loss_pct_eq.mean(), all_mean_R=g.R.mean(),
                     risk2_mean_pct_eq=g.risk2_pct_eq.mean(), stop_med=g.stop_frac.median(),
                     margin_frac_med=g.margin_frac.median(), fee_pct_eq_med=(g.cost_usd / g.eq_before).median()))
out = pd.DataFrame(rows)
out.to_csv(os.path.join(OUT, "s5_live_stopouts.csv"), index=False)
pd.set_option("display.width", 250)
print(out.round(4).to_string(index=False))
# by coin (15m/30m, strategy+ds200)
c = T[T.tf.isin(["15m", "30m"])].groupby(["tf", "symbol"]).agg(n=("R", "size"), stop_med=("stop_frac", "median"),
        planned_loss_med=("loss_at_stop_planned", "median"), lev_mix=("leverage", lambda x: " ".join(f"{k}:{v}" for k, v in x.value_counts().sort_index().items()))).reset_index()
c.to_csv(os.path.join(OUT, "s5_live_by_coin.csv"), index=False)
print(c.to_string(index=False))
# realised account drawdowns on live: per account-run min equity / start
A = pd.read_csv(os.path.join(O, "account_stats.csv"))
print(A.columns.tolist()[:60])
