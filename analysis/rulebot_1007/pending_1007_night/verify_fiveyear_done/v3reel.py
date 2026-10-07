import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
TR, RD = sys.argv[1:3]
T = pd.read_csv(TR)
T = T[T.split.isin(["is", "oos"])]
d = (pd.Timestamp("2026-09-30") - pd.Timestamp("2021-08-01")).days
print("5y n", len(T), "per day", round(len(T) / d, 2), "net%", round(T.net.mean() * 100, 4), "gross IS%", round(T[T.split == "is"].gross.mean() * 100, 4),
      "gross CF%", round(T[T.split == "oos"].gross.mean() * 100, 4), "r_net", round(T.r_net.mean(), 3), "win", round((T.net > 0).mean(), 3),
      "span", T.signal_ts.min(), T.signal_ts.max())
E = pd.read_csv(os.path.join(RD, "trades_enriched.csv"))
k = [c for c in E.columns if c in ("kind", "account_kind")]
r = E[E[k[0]] == "reel"] if k else E[E.account_id.str.contains("reel", case=False)]
print("live reel trades", len(r), "mean R", round(r.R.mean(), 3), "win", round((r.R > 0).mean(), 3),
      "mean ret notional %", round((r.pnl / (r.qty * r.entry_price)).mean() * 100, 4) if "qty" in r else "")
ts = pd.to_datetime(T.signal_ts).astype("int64").to_numpy(); o = np.argsort(ts); ts = ts[o]; v = T.net.to_numpy()[o] * 100
cs = np.r_[0, np.cumsum(v)]; L = int(1.5035 * 86400e9); rng = np.random.default_rng(3)
st = rng.uniform(ts[0], ts[-1] - L, 4000).astype(np.int64); a, b = np.searchsorted(ts, st), np.searchsorted(ts, st + L); n = b - a; ok = n > 0
m = (cs[b] - cs[a])[ok] / n[ok]
print("1.5d window mean net% p5/p50/p95", np.round(np.percentile(m, [5, 50, 95]), 3), "pct of -0.156:", round((m < -0.156).mean(), 3), "pct of -0.019:", round((m < -0.019).mean(), 3),
      "window n median", np.median(n))
