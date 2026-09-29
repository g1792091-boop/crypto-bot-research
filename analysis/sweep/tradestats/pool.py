import pandas as pd, numpy as np, glob
rows = []
for f in sorted(glob.glob("trades_*.csv.gz")):
    T = pd.read_csv(f, parse_dates=["ets"])
    for (tf, st, ex), g in T.groupby(["tf", "strategy", "exit"]):
        g = g.sort_values("ets"); net = g.net.to_numpy(); gr = g.gross.to_numpy()
        w = net > 0; lo = g.side.to_numpy() > 0
        c = np.cumsum(net); mdd = (np.maximum.accumulate(np.r_[0, c])[1:] - c).max()
        rows.append(dict(tf=tf, strategy=st, exit=ex, trades=len(g), long_share=lo.mean(),
            win_rate=w.mean(), win_rate_gross=(gr > 0).mean(), avg_win=net[w].mean() * 100, avg_loss=net[~w].mean() * 100,
            payoff=abs(net[w].mean() / net[~w].mean()), pf_net=net[w].sum() / -net[~w].sum(),
            pf_gross=gr[gr > 0].sum() / -gr[gr <= 0].sum(), exp_gross=gr.mean() * 100, exp_net=net.mean() * 100,
            cost=(gr - net).mean() * 100, sum_net=net.sum() * 100, sum_gross=gr.sum() * 100, mdd=mdd * 100,
            exp_net_long=net[lo].mean() * 100, exp_net_short=net[~lo].mean() * 100,
            exp_gross_long=gr[lo].mean() * 100, exp_gross_short=gr[~lo].mean() * 100,
            years_pos=int((g.groupby(g.ets.dt.year).net.sum() > 0).sum()), years=g.ets.dt.year.nunique()))
P = pd.DataFrame(rows); P.to_csv("pooled_5y.csv", index=False)
TFO = ["5m", "15m", "30m", "1h", "4h", "1d"]
for ex in ["ATR_SL2_TP3", "TIME_H"]:
    q = P[P.exit == ex]
    agg = q.groupby("tf").agg(n=("strategy", "size"), trades_med=("trades", "median"), wr_med=("win_rate", "median"),
        payoff_med=("payoff", "median"), pfg_med=("pf_gross", "median"), pfn_med=("pf_net", "median"),
        pfn_max=("pf_net", "max"), gross_med=("exp_gross", "median"), net_med=("exp_net", "median"),
        cost_med=("cost", "median"), n_net_pos=("sum_net", lambda x: int((x > 0).sum())),
        mdd_med=("mdd", "median"), long_med=("exp_net_long", "median"), short_med=("exp_net_short", "median")).reindex(TFO)
    print("==", ex); print(agg.round(3).to_string())
