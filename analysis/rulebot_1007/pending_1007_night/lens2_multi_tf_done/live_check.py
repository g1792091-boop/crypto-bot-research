"""Live cross-check on the v4 run (10/06 03:35 - 10/07 15:40 KST, 1.5 days): every SUBMITTED signal replayed alone by
rb_analyze (replay_signals.csv, status TRADED; REJECTED_SIZING counted; UNRESOLVED dropped), merged per strategy into
one first-come account over a scope. python3 -I -B live_check.py <replay_signals.csv>"""
import sys
sys.path[:0] = ['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
d = pd.read_csv(sys.argv[1])
d = d[(d.run == "current") & d.kind.isin(["strategy", "ds200"])]
rej = d[d.status == "REJECTED_SIZING"].groupby(["kind", "timeframe"]).size()
tot = d[d.status != "UNRESOLVED"].groupby(["kind", "timeframe"]).size()
print("live sizing-rejected share:\n", (rej / tot).round(3).to_string())
(rej / tot).rename("rejected_share").reset_index().to_csv("summ/live_rejected.csv", index=False)
t = d[d.status == "TRADED"].copy()
TFR = {"15m": 0, "30m": 1, "1h": 2, "4h": 3}
CP = {s: i for i, s in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"])}
t["tfr"] = t.timeframe.map(TFR); t["cp"] = t.symbol.map(CP)
days = 1.5
rows = []
for (kind, strat), g in t.groupby(["kind", "strategy"]):
    for sc, tfs in {"A": (0, 1), "ALL": (0, 1, 2, 3), "HI": (2, 3)}.items():
        s = g[g.tfr.isin(tfs)].sort_values(["entry_time", "cp", "tfr"])
        free, taken, blocked = -np.inf, [], []
        for r in s.itertuples():
            if r.entry_time > free:
                taken.append(r.R); free = r.exit_time
            else:
                blocked.append(r.R)
        rows.append(dict(kind=kind, strategy=strat, scope=sc, signals=len(s), trades=len(taken), blocked=len(blocked),
                         sumR=float(np.sum(taken)), blk_sumR=float(np.sum(blocked))))
r = pd.DataFrame(rows)
g = r.groupby(["kind", "scope"]).sum(numeric_only=True)
g["blocked_share"] = g.blocked / g.signals; g["meanR_taken"] = g.sumR / g.trades; g["meanR_blocked"] = g.blk_sumR / g.blocked
g["trades_per_day_per_trader"] = g.trades / days / r.groupby(["kind", "scope"]).size()
print(g.round(3).to_string())
r.to_csv("summ/live_check.csv", index=False)
g.to_csv("summ/live_check_summary.csv")
