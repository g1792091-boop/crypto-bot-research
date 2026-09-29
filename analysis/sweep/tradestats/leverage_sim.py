"""Replay each strategy's real 5-year trades (exit A: stop 2 ATR / target 3 ATR, longs and shorts) on a $1,000
isolated-margin account at the user's leverage / margin settings. Descriptive only.
- margin = M x current equity at each trade, notional = L x margin (compounding).
- liquidation if the trade's worst adverse excursion (MAE, bar extremes) reaches 1/L - 0.5%: the margin is lost
  plus the entry fee; otherwise equity changes by M x L x net return (net of fees, slippage, funding).
- trades are applied one after another in entry-time order (overlapping positions on different coins are not
  netted against each other; real margin use would be higher)."""
import pandas as pd, numpy as np, glob
POL = [("20x x 20%", 20, 0.20), ("30x x 30%", 30, 0.30), ("50x x 40%", 50, 0.40), ("1x x 100%", 1, 1.00)]
rows = []
for f in sorted(glob.glob("trades_*.csv.gz")):
    T = pd.read_csv(f, parse_dates=["ets"]); T = T[T.exit == "ATR_SL2_TP3"]
    for (tf, st), g in T.groupby(["tf", "strategy"]):
        g = g.sort_values("ets"); net = g.net.to_numpy(); mae = g.mae.to_numpy(); ts = g.ets.to_numpy()
        t0 = ts[0]
        for lab, L, M in POL:
            dl = 1.0 / L - 0.005
            liq = mae <= -dl
            r = np.where(liq, -M * (1 + L * 0.0007), M * L * net)
            r = np.maximum(r, -1.0)
            eq = 1000 * np.cumprod(1 + r)
            ruin = np.nonzero(eq < 10)[0]
            one_year = eq[np.searchsorted(ts, t0 + np.timedelta64(365, "D")) - 1] if len(eq) else np.nan
            rows.append(dict(tf=tf, strategy=st, policy=lab, trades=len(net), liq=int(liq.sum()), liq_rate=liq.mean(),
                             win_rate=(r > 0).mean(), final=eq[-1], after_1y=one_year, min_eq=eq.min(), max_eq=eq.max(),
                             days_to_ruin=float((ts[ruin[0]] - t0) / np.timedelta64(1, "D")) if len(ruin) else np.nan))
D = pd.DataFrame(rows); D.to_csv("leverage_sim.csv", index=False)
TFO = ["5m", "15m", "30m", "1h", "4h", "1d"]
for lab, _, _ in POL:
    q = D[D.policy == lab]
    a = q.groupby("tf").agg(n=("strategy", "size"), liq_rate=("liq_rate", "median"), wr=("win_rate", "median"),
        after_1y_med=("after_1y", "median"), final_med=("final", "median"), final_best=("final", "max"),
        profitable=("final", lambda x: int((x > 1000).sum())), ruined=("days_to_ruin", lambda x: int(x.notna().sum())),
        days_ruin_med=("days_to_ruin", "median")).reindex(TFO)
    print("==", lab); print(a.round(3).to_string())
