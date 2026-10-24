"""Data-error check: re-walk every 'ok' trade of OBV20@4h>RSI@1h|a2 on the MARK price 1m bars (fg1m mo/mh/ml/mc, to
2026-09-30) instead of the last price, same entry minute, side and ATR stop distance. A trade made by a bad last-price
print would change a lot. Only trades entered before 2026-09-29 (so the walk ends inside fg1m)."""
import numpy as np, pandas as pd, json
import indep as IN
I = pd.read_csv("indep_rows.csv")
X = I[(I["var"] == "ok") & (I.t_ms < IN.ms("2026-09-29"))].copy()
out = []
for coin in IN.COINS:
    z = np.load(f"{IN.FG}/{coin}.npz")
    ts = z["ts"]
    first, end = int(ts[0]), int(ts[-1]) + IN.MIN
    full = np.arange(first, end, IN.MIN, dtype=np.int64)
    df = pd.DataFrame({k: z[k] for k in ("mo", "mh", "ml", "mc", "fund")}, index=ts).reindex(full)
    miss = df.mc.isna()
    pc = df.mc.ffill()
    for k in ("mo", "mh", "ml", "mc"):
        df[k] = df[k].where(~miss, pc)
    df["fund"] = df.fund.fillna(0)
    o, h, l, c = (df[k].to_numpy(float) for k in ("mo", "mh", "ml", "mc"))
    cumf = np.cumsum(df.fund.to_numpy(float))
    n = len(full)
    for r in X[X.coin == coin].itertuples():
        e = int((r.t_ms - first) // IN.MIN)
        atrd = 2 * r.atr / r.p0
        roe, k, why, best = IN.walk(o, h, l, c, cumf, e, int(r.side), atrd, n)
        out.append((coin, r.t_ms, r.side, r.roe, roe, why))
R = pd.DataFrame(out, columns=["coin", "t_ms", "side", "roe_last", "roe_mark", "why_mark"])
R["d"] = R.roe_mark - R.roe_last
R["t"] = pd.to_datetime(R.t_ms, unit="ms")
P = {"SEL": (IN.ms("2021-01-01"), IN.ms("2024-01-01")), "CONF<=09-28": (IN.ms("2024-01-01"), IN.ms("2026-09-29")),
     "FIVE<=09-28": (IN.ms("2020-03-01"), IN.ms("2026-09-29"))}
PB = 2 * 0.9 * 0.00042 * 30
s = {}
for k, (a, b) in P.items():
    Y = R[(R.t_ms >= a) & (R.t_ms < b)]
    s[k] = {"n": len(Y), "last": round(Y.roe_last.mean() * 100, 3), "mark": round(Y.roe_mark.mean() * 100, 3),
            "last_pb": round((Y.roe_last.mean() + PB) * 100, 3), "mark_pb": round((Y.roe_mark.mean() + PB) * 100, 3),
            "n_absdiff_gt_20pp": int((Y.d.abs() > 0.2).sum())}
print(json.dumps(s, indent=1))
print(R.reindex(R.d.abs().sort_values(ascending=False).index).head(10)[["coin", "t", "side", "roe_last", "roe_mark"]].to_string())
json.dump(s, open("markcheck.json", "w"), indent=1)
