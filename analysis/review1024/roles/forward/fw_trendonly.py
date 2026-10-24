"""Trend luck without any entry strategy: follow a trend source's side at EVERY bar close of the entry timeframe
(one trade per bar per coin, each a separate trade), for every (tf -> htf) mapping and all 109 trend sources.
Pick the best (mapping, source) on H1 (exit before the split; score = mean - SE), read once on H2; null = trend
state flipped by (coin, UTC day) clusters, whole search redone (1,000 permutations).
Writes trendonly_cells.csv, trendonly.json.  Run: python3 fw_trendonly.py [n_perm]"""
import json
from fw_lib import *  # noqa: F401,F403

NPERM = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
SRCS = list(JUDGES) + [f"c_{x}" for x in SOURCES] + [f"l_{x}" for x in SOURCES]
SPLIT_E = (SPLIT - T0) // MIN


def main():
    B = load("base")
    dd = (B.day - B.day.min()).to_numpy()
    cd = B.coin.to_numpy(np.int64) * 1000 + dd
    cd_u, cd_inv = np.unique(cd, return_inverse=True)
    h1 = B.t.to_numpy() < SPLIT
    e = B.e.to_numpy(np.int64)
    blocks = []
    for tf, htf in MAPS:
        rows = np.flatnonzero(B.tf.to_numpy() == tf)
        St = np.stack([state(B.iloc[rows], s, htf) for s in SRCS], 1).astype(np.int8)
        blocks.append((tf, htf, rows, St))
    out = {}
    for v in ("w35", "a2"):
        L, Sx = roe(B, v), roe(B, v, True)
        kL, kS = B[f"{v}_k"].to_numpy(np.int64), B[f"{v}_opp_k"].to_numpy(np.int64)
        wL, wS = B[f"{v}_why"].to_numpy(), B[f"{v}_opp_why"].to_numpy()

        def run(flip):
            res = []
            for tf, htf, rows, St in blocks:
                s = St * (flip[cd_inv[rows]][:, None] if flip is not None else 1)
                r = np.where(s > 0, L[rows, None], np.where(s < 0, Sx[rows, None], np.nan))
                k = np.where(s > 0, kL[rows, None], kS[rows, None])
                w = np.where(s > 0, wL[rows, None], wS[rows, None])
                ok1 = h1[rows, None] & (e[rows, None] + k <= SPLIT_E) & np.isfinite(r)
                ok2 = ~h1[rows, None] & (w != 3) & np.isfinite(r)
                r0 = np.nan_to_num(r)
                n1, n2 = ok1.sum(0), ok2.sum(0)
                m1 = (r0 * ok1).sum(0) / np.maximum(n1, 1)
                q1 = (r0 ** 2 * ok1).sum(0) / np.maximum(n1, 1)
                se = np.sqrt(np.maximum(q1 - m1 ** 2, 0) / np.maximum(n1 - 1, 1))
                m2 = (r0 * ok2).sum(0) / np.maximum(n2, 1)
                res.append(pd.DataFrame({"tf": tf, "htf": htf, "src": SRCS, "n1": n1, "m1": m1, "se1": se,
                                         "n2": n2, "m2": m2, "s2": (r0 * ok2).sum(0)}))
            T = pd.concat(res, ignore_index=True)
            T["score"] = T.m1 - T.se1
            return T[T.n1 >= 100]

        T = run(None)
        T.to_csv(os.path.join(HERE, f"trendonly_cells_{v}.csv"), index=False, float_format="%.5g")
        T = T.sort_values("score", ascending=False)
        a_top1, a_top5 = float(T.m2.iloc[0]), float(T.head(5).s2.sum() / T.head(5).n2.sum())
        rng = np.random.default_rng(7)
        nb, n1_, n5_ = [], [], []
        for i in range(NPERM):
            f = rng.choice(np.array([-1, 1], np.int8), len(cd_u))
            N = run(f).sort_values("score", ascending=False)
            nb.append(float(N.score.iloc[0]))
            n1_.append(float(N.m2.iloc[0]))
            n5_.append(float(N.head(5).s2.sum() / N.head(5).n2.sum()))
        out[v] = {"top5": T.head(5)[["tf", "htf", "src", "n1", "m1", "score", "n2", "m2"]].to_dict("records"),
                  "best_score": float(T.score.iloc[0]), "top1_h2": a_top1, "top5_h2": a_top5,
                  "p_best": float(np.mean(np.array(nb) >= T.score.iloc[0])),
                  "p_top1_h2": float(np.mean(np.array(n1_) >= a_top1)),
                  "p_top5_h2": float(np.mean(np.array(n5_) >= a_top5)),
                  "null_top1_h2_med": float(np.median(n1_)), "null_top5_h2_med": float(np.median(n5_))}
        log(v, json.dumps(out[v], default=float)[:600])
    json.dump(out, open(os.path.join(HERE, "trendonly.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
