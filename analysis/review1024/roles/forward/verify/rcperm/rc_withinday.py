"""Verifier: within-day matched control for the a2 family TOP5 H2 pool. For each (cell, UTC day, side) draw at random
the same number of that cell's own H2 signals of that day and side (unfiltered by the trend source); pooled mean;
20,000 draws. Shows whether the trend filter picked better trades than the same cells' other signals on the same days.
Also the same for the two named 1h cells only. Run: python3 rc_withinday.py"""
import os, sys, json
FW = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, FW)
from fw_lib import *  # noqa

OUTD = os.path.dirname(os.path.abspath(__file__))
S = load("sig"); S = S[S.role != "trend"].reset_index(drop=True)
P = pd.read_csv(os.path.join(FW, "search_picks.csv")); P = P[(P.exit == "a2") & (P.level == "F")].sort_values("rank")
r = roe(S, "a2"); k = S["a2_k"].to_numpy(np.int64); why = S["a2_why"].to_numpy()
ok2 = (S.t.to_numpy() >= SPLIT) & (why != 3) & np.isfinite(r) & (k >= 0)
sd = S.side.to_numpy(); day = S.day.to_numpy()
out = {}
for label, ranks in (("top5", [1, 2, 3, 4, 5]), ("named_1h_pair", [4, 5])):
    groups, asum, an = [], 0.0, 0
    for _, c in P[P["rank"].isin(ranks)].iterrows():
        role, tf = c.key.split("|")
        m = (S.role.to_numpy() == role) & (S.tf.to_numpy() == tf) & ok2
        al = m & (state(S, c.src, c.htf) * sd == 1)
        asum += r[al].sum(); an += int(al.sum())
        for d in np.unique(day[al]):
            for s_ in (-1, 1):
                na = int((al & (day == d) & (sd == s_)).sum())
                if na:
                    groups.append((r[m & (day == d) & (sd == s_)], na))
    act = asum / an
    rng = np.random.default_rng(9)
    sims = np.array([sum(rng.choice(x, n, replace=False).sum() for x, n in groups) / an for _ in range(20000)])
    out[label] = {"actual": act, "n": an, "null_mean": float(sims.mean()), "null_p95": float(np.quantile(sims, .95)),
                  "p": float(np.mean(sims >= act)), "groups": len(groups),
                  "share_of_pool_already_aligned": float(sum(n for _, n in groups) / sum(len(x) for x, _ in groups))}
json.dump(out, open(os.path.join(OUTD, "rc_withinday.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
