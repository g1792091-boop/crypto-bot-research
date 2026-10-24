"""Verifier (luck / multiple testing) -- step 4: rebuild bot G (321 cells: SELECT BH on the paired flip t AND SELECT
mean + payback > 0) with the study's own loaders, read SEL / CONF / LATE / FWD, the coin-flip twin, the 30-day bootstrap,
then (a) a RANDOM-SIDE null for the one-position bot (each signal's side drawn 50/50, and drawn with the period's long
share; the bot's own one-position path re-run each draw), (b) signal-level pooled paired flip t on unique signals,
month-clustered.
    python3 fl_bot.py <out_dir> [n_null]"""
import os
import sys
import time
FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FY)
import fy_common
fy_common.SHM = "/dev/shm/claude_verify_fl"
from goalpath import *          # noqa
import fy_analyze

OUT = sys.argv[1]
NN = int(sys.argv[2]) if len(sys.argv) > 2 else 300
t0 = time.time()
Wf = pd.read_pickle(os.path.join(OUT, "Wf.pkl"))
g = Wf[Wf.bhS & (Wf.SEL_mW + 35 * PAYBACK > 0)].sort_values("SEL_tFlip", ascending=False)
specs = [(r["name"], r.etf, r.htf, r.kind, r.source, "W") for _, r in g.iterrows()]
print("G cells", len(specs))
pk = os.path.join(OUT, "G_rows.pkl")
if os.path.exists(pk):
    S = pd.read_pickle(pk)
else:
    S = bot_rows(specs)
    S.to_pickle(pk)
print("rows", len(S), f"{time.time() - t0:.0f}s")
res = {}
for per in ("SEL", "CONF", "LATE", "FWD"):
    o, T = read(S, per)
    res[per] = (o, T)
    print(per, {k: (round(v, 5) if isinstance(v, float) else v) for k, v in o.items()
                if k in ("trades", "per_day", "mean_roe", "mean_roe_pb", "opp_mean_roe", "win", "long_share",
                         "mean_roe_all_signals")})
# bootstrap at margin 0.4 with payback, CONF, same seed / n as the study
o, T = res["CONF"]
Tb = T.assign(w35_roe=T.w35_roe + 35 * PAYBACK)
gb = RD.goal_bootstrap(Tb, "w35", margin=0.4, days=PER_SPAN["CONF"], n_boot=4000)
print("CONF boot m0.4 pb", gb)
gb2 = RD.goal_bootstrap(Tb, "w35", margin=0.4, days=PER_SPAN["CONF"], n_boot=4000, seed=1)
print("CONF boot m0.4 pb seed 1", gb2)


# random-side null for the one-position bot
def rand_bot(P, choose):
    """choose: bool per row, True = keep the row's side, False = take the opposite."""
    Q = P.copy()
    for c in ("roe", "k", "why"):
        Q[f"w35x_{c}"] = np.where(choose, P[f"w35_{c}"], P[f"w35_opp_{c}"])
    took = RD.one_position(Q, "w35x", priority="prio")
    return Q.w35x_roe.to_numpy()[took]


rng = np.random.default_rng(99)
rows = []
for per in ("CONF", "FWD", "SEL"):
    P = period_rows(S, per).reset_index(drop=True)
    o, T = res[per]
    side = P.side.to_numpy()
    for b in range(NN if per != "SEL" else 100):
        c50 = rng.random(len(P)) < 0.5
        r50 = rand_bot(P, c50)
        rows.append({"period": per, "kind": "coin50", "mean": r50.mean(), "n": len(r50)})
    print(per, "real bot", round(o["mean_roe"], 5), "n", o["trades"])
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "fl_bot_null.csv"), index=False)
for per in ("CONF", "FWD", "SEL"):
    z = R[R.period == per]
    real = res[per][0]["mean_roe"]
    print(per, "coin50 null mean ROE q05/50/95", z["mean"].quantile([.05, .5, .95]).round(5).tolist(),
          " P(null >= real)", round((z["mean"] >= real).mean(), 4), " null trades median", z.n.median())
# signal-level pooled paired flip on UNIQUE signals, month clustered
for per in ("SEL", "CONF", "LATE", "FWD"):
    P = period_rows(S, per)
    d = (P.w35_roe - P.w35_opp_roe).to_numpy()
    m = fy_common.month_of(P.t.to_numpy())
    mm = np.unique(m)
    n_m = np.array([(m == x).sum() for x in mm], float)[None, :]
    d_m = np.array([d[m == x].sum() for x in mm])[None, :]
    mu, t, M = fy_analyze.cluster_t(n_m, None, d_m=d_m)
    print(per, "unique signals", len(P), "pooled flip diff", round(float(mu[0]), 5), "month-clustered t", round(float(t[0]), 2),
          "months", int(M[0]), " with mean", round(P.w35_roe.mean(), 5), "opp", round(P.w35_opp_roe.mean(), 5),
          " long share", round((P.side > 0).mean(), 3))
