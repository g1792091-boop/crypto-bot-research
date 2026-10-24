"""Adversarial check of the 'rebuild loses ~1 ROE point less per trade than B0' claim.
Reads only ../trades/trades_<v>.csv.gz. Run: python3 v_luck.py <trades_dir>"""
import sys, os
import numpy as np, pandas as pd

TD = sys.argv[1]
DAY = 86_400_000
V = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "W0", "W3"]
def ms(s): return int(pd.Timestamp(s, tz="UTC").timestamp() * 1000)
SEL = (ms("2020-03-01"), ms("2024-01-01")); CON = (ms("2024-01-01"), ms("2025-07-01"))
T = {v: pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz")) for v in V}
LATE_END = T["B0"][T["B0"].period == "fwd"].t.min()
print("fwd start (first fwd trade)", pd.Timestamp(LATE_END, unit="ms"))
# period column already in file: use it
def sub(df, periods): return df[df.period.isin(periods)]

def bh(p):
    p = np.asarray(p, float); m = len(p); o = np.argsort(p)
    adj = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    q = np.empty(m); q[o] = np.minimum(adj, 1); return q

def joint_boot(dfs, block_ms, n=5000, seed=3, col="tb_roe"):
    """resample blocks jointly for all variants; returns array (n, len(dfs)) of per-trade means"""
    blocks = [df.t.to_numpy() // block_ms for df in dfs]
    ub = np.unique(np.concatenate(blocks))
    S, C = [], []
    for df, b in zip(dfs, blocks):
        i = np.searchsorted(ub, b)
        S.append(np.bincount(i, df[col].to_numpy(), len(ub))); C.append(np.bincount(i, minlength=len(ub)))
    rng = np.random.default_rng(seed); pk = rng.integers(0, len(ub), (n, len(ub)))
    return np.stack([S[k][pk].sum(1) / np.maximum(C[k][pk].sum(1), 1) for k in range(len(dfs))], 1)

out = []
for label, per in [("confirm+late", ["confirm", "late"]), ("select", ["select"]), ("confirm", ["confirm"]),
                   ("late", ["late"]), ("all_2020_2026-10-05", ["select", "confirm", "late"])]:
    dfs = [sub(T[v], per) for v in V]
    means = np.array([d.tb_roe.mean() for d in dfs])
    for bname, bms in [("day", DAY), ("week", 7 * DAY), ("month", 30 * DAY)]:
        B = joint_boot(dfs, bms)
        diff = B[:, 1:] - B[:, [0]]
        obs = means[1:] - means[0]
        p = (diff <= 0).mean(0)
        q = bh(p)
        # max-T style simultaneous lower bound: centre the bootstrap, take the max over variants
        cen = diff - obs
        sd = cen.std(0)
        tmax = np.max(cen / sd, 1)
        c95 = np.quantile(tmax, 0.95)
        simlo = obs - c95 * sd
        # family-wise p: P(max over 12 of centred t >= observed t_v)
        tobs = obs / sd
        pfw = np.array([(tmax >= x).mean() for x in tobs])
        for k, v in enumerate(V[1:]):
            out.append(dict(window=label, block=bname, variant=v, n=len(dfs[k + 1]), n_b0=len(dfs[0]),
                            mean=means[k + 1], b0=means[0], vs_b0=obs[k], p=p[k], q12=q[k],
                            lo95_marg=np.quantile(diff[:, k], 0.05), sim_lo95=simlo[k], p_fwer=pfw[k]))
R = pd.DataFrame(out)
R.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "v_vs_b0.csv"), index=False, float_format="%.5g")
pd.set_option("display.width", 250)
for w in R.window.unique():
    print("\n==", w)
    X = R[(R.window == w)].pivot_table(index="variant", columns="block", values=["vs_b0", "p", "q12", "sim_lo95", "p_fwer"])
    X = X.reindex(V[1:])
    print((X * 1).round(4).to_string())

# coin-flip version of B0 entries: per trade (own+opp)/2 ; distribution under random sides
print("\n== coin-flip null on B0 entries (confirm+late)")
b0 = sub(T["B0"], ["confirm", "late"])
own, opp = b0.tb_roe.to_numpy(), b0.tb_opp_roe.to_numpy()
cf_mean = ((own + opp) / 2).mean()
rng = np.random.default_rng(7)
sims = np.array([np.where(rng.random(len(own)) < .5, own, opp).mean() for _ in range(20000)])
print("B0 own", own.mean(), "opp", opp.mean(), "coin-flip expected", cf_mean, "coin 5-95%", np.quantile(sims, [.05, .95]))
print("P(coin-flip B0 <= B0 own)", (sims <= own.mean()).mean())
for v in ["B4", "B5", "B6", "B9", "B3", "W3"]:
    d = sub(T[v], ["confirm", "late"])
    m = d.tb_roe.mean()
    print(v, "mean", round(m, 5), "own-minus-coinflipB0", round(m - cf_mean, 5), "P(coin-flip B0 >= v)", (sims >= m).mean(),
          "own coin-flip level", round(((d.tb_roe + d.tb_opp_roe) / 2).mean(), 5))
# B0's direction harm by period
for per in ["select", "confirm", "late"]:
    d = sub(T["B0"], [per]); print("B0", per, "own", round(d.tb_roe.mean(), 5), "opp", round(d.tb_opp_roe.mean(), 5),
                                  "coin", round(((d.tb_roe + d.tb_opp_roe) / 2).mean(), 5))
# account-level: sum of ROE (margin-weighted ~ log-equity) per day for confirm+late
print("\n== total ROE per calendar day (confirm+late), more trades => more loss")
days = (sub(T['B0'], ['confirm','late']).t.max() - CON[0]) / DAY
for v in V:
    d = sub(T[v], ["confirm", "late"])
    lg = np.log1p(0.4 * d.tb_roe.clip(lower=-0.999)).sum()
    print(v, "n", len(d), "sumROE/day", round(d.tb_roe.sum() / days, 4), "log-equity change @40% margin", round(lg, 1))
