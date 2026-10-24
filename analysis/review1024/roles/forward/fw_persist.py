"""Does a cell's first-half result say anything about its second half? (persistence over the WHOLE search, not only
the picks). For entry cells and family cells with n >= 10 (family 30) in BOTH halves: Spearman correlation of H1 mean
and H2 mean, and the H2 mean of the top / bottom 10 % by H1 score; the same under 300 side-flip permutations
(coin-day clusters, as fw_search.py). Writes persist.json.  Run: python3 fw_persist.py [n_perm]"""
import json
from scipy.stats import spearmanr
from fw_search import Engine, MIN_N, MIN_D, FMIN_N, FMIN_D
from fw_lib import *  # noqa: F401,F403

NPERM = int(sys.argv[1]) if len(sys.argv) > 1 else 300


def stats(eng, cells):
    o = {}
    for v in ("w35", "a2"):
        for lab in ("E", "F"):
            T = eng.table(cells, v, lab)
            mn, md = (MIN_N, MIN_D) if lab == "E" else (FMIN_N, FMIN_D)
            X = T[(T.n1 >= mn) & (T.d1 >= md) & (T.n2 >= mn)]
            rho = spearmanr(X.m1, X.m2).correlation if len(X) > 10 else np.nan
            q = X.score.quantile([0.1, 0.9])
            top = X[X.score >= q[0.9]]
            bot = X[X.score <= q[0.1]]
            o[f"{v}_{lab}"] = {"n_cells": int(len(X)), "rho": float(rho),
                               "h2_top10pct": float(top.s2.sum() / top.n2.sum()),
                               "h2_bottom10pct": float(bot.s2.sum() / bot.n2.sum()),
                               "h2_all": float(X.s2.sum() / X.n2.sum()),
                               "share_pos_both": float(np.mean((X.m1 > 0) & (X.m2 > 0))),
                               "share_pos_h2_given_pos_h1": float(np.mean(X.m2[X.m1 > 0] > 0)) if (X.m1 > 0).any() else np.nan,
                               "share_pos_h2_given_neg_h1": float(np.mean(X.m2[X.m1 <= 0] > 0)) if (X.m1 <= 0).any() else np.nan}
    return o


def main():
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    eng = Engine(S)
    act = stats(eng, eng.run())
    rng = np.random.default_rng(99)
    null = []
    for i in range(NPERM):
        f = rng.choice(np.array([-1, 1], np.int8), len(eng.cd_u))
        null.append(stats(eng, eng.run(f)))
        if i % 50 == 0:
            log("perm", i)
    out = {}
    for k, a in act.items():
        nn = pd.DataFrame([x[k] for x in null])
        out[k] = {**a, "p_rho": float(np.mean(nn.rho >= a["rho"])), "null_rho_med": float(nn.rho.median()),
                  "null_rho_p95": float(nn.rho.quantile(0.95)),
                  "p_top10pct": float(np.mean(nn.h2_top10pct >= a["h2_top10pct"])),
                  "null_top10pct_med": float(nn.h2_top10pct.median()),
                  "p_spread": float(np.mean((nn.h2_top10pct - nn.h2_bottom10pct) >= a["h2_top10pct"] - a["h2_bottom10pct"]))}
    json.dump({"n_perm": NPERM, "out": out}, open(os.path.join(HERE, "persist.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
