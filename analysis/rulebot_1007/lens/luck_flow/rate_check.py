"""Live SUBMITTED signal rate vs the 5-year rate per strategy x tf (cells with >= 10 expected signals), with Poisson
tails and BH; and the exhaustive coin flip MFE for comparison with the 15m coin-flip accounts."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
from scipy.stats import poisson
O, W = sys.argv[1], sys.argv[2]
F = pd.read_csv(os.path.join(W, "flow.csv"))
f = F[F.kind.isin(["strategy", "ds200"]) & F.ref5y_per_day.notna() & (F.timeframe != "5m")].copy()
f["expected"] = f["ref5y_per_day"] * f["days"]
f = f[f.expected >= 10]
f["ratio"] = f["sig_SUBMITTED"] / f["expected"]
p2 = 2 * np.minimum(poisson.cdf(f["sig_SUBMITTED"], f["expected"]), poisson.sf(f["sig_SUBMITTED"] - 1, f["expected"]))
f["p_two"] = np.minimum(p2, 1)
o = np.argsort(f["p_two"].to_numpy()); n = len(f)
q = f["p_two"].to_numpy()[o] * n / np.arange(1, n + 1); q = np.minimum.accumulate(q[::-1])[::-1]
qq = np.empty(n); qq[o] = np.minimum(q, 1); f["bh_q"] = qq
print("cells", len(f), "median ratio", round(f.ratio.median(), 3), "IQR", f.ratio.quantile([.25, .75]).round(3).tolist(),
      "corr log rates", round(np.corrcoef(np.log(f.sub_per_day_pooled + 0.1), np.log(f.ref5y_per_day + 0.1))[0, 1], 3))
print("BH q<0.05 (rate unusual vs 5y):", int((f.bh_q < 0.05).sum()))
print(f[f.bh_q < 0.05][["kind", "strategy", "timeframe", "sig_SUBMITTED", "expected", "ratio", "bh_q"]]
      .sort_values("ratio").round(3).to_string())
print(f.groupby(["kind", "timeframe"]).ratio.median().round(2))
f.to_csv(os.path.join(W, "rate_vs_5y.csv"), index=False)
X = pd.read_csv(os.path.join(W, "cf_exhaustive_rows.csv"), low_memory=False)
X = X[X.status == "TRADED"]
print("exhaustive mean MFE R by tf:", X.groupby("timeframe")["mfe_R"].mean().round(3).to_dict(),
      "lock share:", X.groupby("timeframe")["exit_reason"].apply(lambda s: (s == "LOCK").mean()).round(3).to_dict())
