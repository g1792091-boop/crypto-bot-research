"""Compare the independent rebuild (indep_rows.csv) with the study's rows (study_rows.csv) and summarise the look-ahead
variants per period, with and without the TetherMax payback."""
import numpy as np, pandas as pd, json
MIN = 60_000
T0 = int(pd.Timestamp("2020-01-01", tz="UTC").value // 10**6)
def ms(s): return int(pd.Timestamp(s, tz="UTC").value // 10**6)
GRID_END = ms("2026-10-23")
P = {"PRE": (ms("2020-03-01"), ms("2021-01-01")), "SEL": (ms("2021-01-01"), ms("2024-01-01")),
     "CONF": (ms("2024-01-01"), GRID_END), "YTD": (ms("2026-01-01"), GRID_END),
     "FWD": (ms("2026-10-05 15:00"), ms("2026-10-24 15:00")), "FIVE": (ms("2020-03-01"), GRID_END)}
PB = 2 * 0.9 * 0.00042 * 30
I = pd.read_csv("indep_rows.csv")
S = pd.read_csv("study_rows.csv")
S["t_ms"] = T0 + S.e * MIN
ok = I[I["var"] == "ok"].copy()
key = ["coin", "t_ms", "side"]
M = S.merge(ok, on=key, how="outer", suffixes=("_s", "_i"), indicator=True)
M = M[M.t_ms >= ms("2020-03-01")]
print("match counts (from 2020-03):", M._merge.value_counts().to_dict())
both = M[M._merge == "both"]
d = (both.roe_s - both.roe_i).abs()
print("ROE abs diff: max %.2e, >1e-4: %d, >1e-2: %d of %d" % (d.max(), (d > 1e-4).sum(), (d > 1e-2).sum(), len(both)))
print(both.loc[d > 1e-4, key + ["roe_s", "roe_i", "w", "why"]].head(20).to_string())
print("only study:", M[M._merge == "left_only"][key + ["roe_s"]].head(10).to_string())
print("only indep:", M[M._merge == "right_only"][key + ["roe_i"]].head(10).to_string())
out = {}
for var in ("ok", "la4h", "la1h", "d1", "d5"):
    X = I[(I["var"] == var) & (I.why != 3) & (I.why_opp != 3)]
    for per, (a, b) in P.items():
        Y = X[(X.t_ms >= a) & (X.t_ms < b)]
        out[f"{var}|{per}"] = {"n": len(Y), "mean": round(Y.roe.mean() * 100, 3), "mean_pb": round((Y.roe.mean() + PB) * 100, 3),
                               "opp": round(Y.roe_opp.mean() * 100, 3)}
T = pd.DataFrame(out).T
print(T.to_string())
json.dump(out, open("compare.json", "w"), indent=1)
