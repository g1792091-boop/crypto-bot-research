"""Verifier: fw_trendonly.py's whole search with the trend state flipped by global UTC day (all coins together)
instead of by (coin, day). Same pick rule (H1 score = mean - SE, n1 >= 100), same H2 reads. Only the a2 / w35 p-values
of top1 and top5 are reported. Run: python3 rc_trendonly_day.py <n_perm>"""
import os, sys, json
FW = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, FW)
from fw_lib import *  # noqa

OUTD = os.path.dirname(os.path.abspath(__file__))
NPERM = int(sys.argv[1])
SRCS = list(JUDGES) + [f"c_{x}" for x in SOURCES] + [f"l_{x}" for x in SOURCES]
SPLIT_E = (SPLIT - T0) // MIN
B = load("base")
dd = (B.day - B.day.min()).to_numpy()
nd = int(dd.max() + 1)
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

    def run(fday):
        res = []
        for tf, htf, rows, St in blocks:
            s = St * (fday[dd[rows]][:, None] if fday is not None else 1)
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

    T = run(None).sort_values("score", ascending=False)
    a1, a5 = float(T.m2.iloc[0]), float(T.head(5).s2.sum() / T.head(5).n2.sum())
    rng = np.random.default_rng(21)
    n1_, n5_ = [], []
    for i in range(NPERM):
        f = rng.choice(np.array([-1, 1], np.int8), nd)
        N = run(f).sort_values("score", ascending=False)
        n1_.append(float(N.m2.iloc[0])); n5_.append(float(N.head(5).s2.sum() / N.head(5).n2.sum()))
    out[v] = {"top1_h2": a1, "top5_h2": a5, "p_top1_h2": float(np.mean(np.array(n1_) >= a1)),
              "p_top5_h2": float(np.mean(np.array(n5_) >= a5)), "null_top5_med": float(np.median(n5_)),
              "null_top1_med": float(np.median(n1_))}
    print(v, out[v], flush=True)
json.dump(out, open(os.path.join(OUTD, "rc_trendonly_day.json"), "w"), indent=1)
