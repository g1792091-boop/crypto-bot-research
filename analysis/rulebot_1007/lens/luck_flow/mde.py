"""What a 30-day AI-trader verdict can detect: per-trade spread (R) and the paired side-flip spread (h) from the
replay of real signals, day-level design effect from the live single-account trades, MDE at 80% power (one-sided
5%) for n trades, and the false-pass rate of a naive iid test when trades are clustered.

    python3 -I mde.py <out_real_dir> <work_dir>
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
from scipy.stats import norm
O, W = sys.argv[1], sys.argv[2]
RP = pd.read_csv(os.path.join(O, "replay_signals.csv"), low_memory=False)
P = RP[(RP.status == "TRADED") & (RP.flip_status == "TRADED") & RP.kind.isin(["strategy", "ds200"])].copy()
P["h"] = 0.5 * (P["R"] - P["flip_R"])
T = pd.read_csv(os.path.join(O, "trades_enriched.csv"), low_memory=False)
T = T[T.kind.isin(["strategy", "ds200"]) & T.tf.isin(["15m", "30m"])]
# day-level design effect inside single accounts (one position at a time): var of account-day sums vs iid
rows = []
for tf in ("15m", "30m", "1h", "4h"):
    g = P[P.timeframe == tf]
    rows.append({"timeframe": tf, "sd_R_signal": g["R"].std(), "sd_h_sideflip": g["h"].std(), "n": len(g)})
SD = pd.DataFrame(rows)
# within-account clustering by KST day: ICC-style deff = 1 + (m-1)*rho, rho from one-way ANOVA on account-days
T["acct_day"] = T["run"] + T["account_id"] + T["entry_day"].astype(str)
grp = T.groupby("acct_day")["R"]
k = grp.ngroups
n = len(T)
m_bar = n / k
msb = (grp.size() * (grp.mean() - T["R"].mean()) ** 2).sum() / (k - 1)
msw = ((T["R"] - grp.transform("mean")) ** 2).sum() / (n - k)
n0 = (n - (grp.size() ** 2).sum() / n) / (k - 1)
rho = max((msb - msw) / (msb + (n0 - 1) * msw), 0)
print(f"within-account day clustering (15m+30m live trades): n {n}, account-days {k}, rho {rho:.3f}, "
      f"deff at 5 trades/day {1 + 4 * rho:.2f}")
# cross-account same-minute correlation already gives deff 1.2-2.7 for pooled cells (neff_kind_tf.csv)
out = []
z = norm.ppf(0.95) + norm.ppf(0.80)
for _, r in SD.iterrows():
    for ntr in (30, 60, 150, 300):
        for deff in (1.0, 1 + 4 * rho, 2.0):
            out.append({"timeframe": r.timeframe, "n_trades": ntr, "deff": round(deff, 2),
                        "mde_mean_R_vs_zero": z * r.sd_R_signal * np.sqrt(deff / ntr),
                        "mde_sideflip_excess": z * r.sd_h_sideflip * np.sqrt(deff / ntr)})
M = pd.DataFrame(out)
M.to_csv(os.path.join(W, "mde_verdict.csv"), index=False)
pd.set_option("display.width", 200)
print(SD.round(3).to_string())
print(M[M.timeframe.isin(["15m", "30m"])].round(3).to_string())
for deff in (1.5, 2.0, 2.7, 10.0):
    fp = 1 - norm.cdf(norm.ppf(0.95) / np.sqrt(deff))
    print(f"naive iid one-sided 5% test, true deff {deff}: false-pass rate {fp:.3f}")
