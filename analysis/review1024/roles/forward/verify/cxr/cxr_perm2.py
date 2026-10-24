"""Verifier (costs lens): redo the a2 FAMILY search of fw_search.py (H1 pick by mean - SE, TOP5 pooled read on H2) and
its whole-search permutation with every a2 outcome re-walked at a given cost multiple (both sides, frloss.walk2, the
grid's kernel; funding 0 as in the study). Null = the study's (coin, UTC day) side flips, same seed; plus 'day' flips
(all coins of a UTC day together).

    python3 cxr_perm2.py <cost multiple> <n_perm>      (run from this folder without -I)"""
import os
import sys
import json
import time

FW = "/home/user/crypto-bot-research/analysis/review1024/roles/forward"
sys.path.insert(0, FW)
_argv = sys.argv
sys.argv = [sys.argv[0]]
from fw_lib import *  # noqa: F401,F403,E402
import fw_search as FS  # noqa: E402
sys.argv = _argv
from cxr_costs import rewalk  # noqa: E402

HERE_V = os.path.dirname(os.path.abspath(__file__))


def main():
    mult = float(sys.argv[1])
    nperm = int(sys.argv[2])
    t0 = time.time()
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    ok = np.isfinite(S.a2_r.to_numpy()) & (S.a2_k.to_numpy() >= 0)
    for lab, flip in (("", 1), ("_opp", -1)):
        X = S.loc[ok, ["coin", "e", "tf"]].copy()
        X["side"] = S.side.to_numpy()[ok] * flip
        r, k, w = rewalk(X, mult * COST, None)
        R = np.full(len(S), np.nan)
        K = np.full(len(S), -1, np.int64)
        W = np.full(len(S), -1, np.int8)
        R[ok], K[ok], W[ok] = r, k, w
        if mult == 1.0:
            print("sanity", lab, float(np.nanmax(np.abs(R[ok] - S[f"a2{lab}_r"].to_numpy()[ok]))))
        S[f"a2{lab}_r"], S[f"a2{lab}_k"], S[f"a2{lab}_why"] = R, K, W
    print("rewalk done", round(time.time() - t0, 1), flush=True)
    eng = FS.Engine(S)
    cells = eng.run()
    T = eng.table(cells, "a2", "F")
    T["key"] = eng.fams[T.id.to_numpy()]
    T["tf"] = [eng.blocks[b]["tf"] for b in T.block]
    T["htf"] = [eng.blocks[b]["htf"] for b in T.block]
    top1, topk = FS.pick(T, "F", eng)
    actual = {"topk": topk[["key", "htf", "src", "n1", "m1", "score", "n2", "m2"]].to_dict("records"),
              "top1_h2": float(top1.m2.iloc[0]), "topk_h2_pooled": FS.pooled(topk),
              "topk_h2_eq": float(np.nanmean(topk.m2)), "best_score": float(top1.score.iloc[0])}
    # same five cells as the study (picked at cost x1), read at this cost
    P = pd.read_csv(os.path.join(FW, "search_picks.csv"))
    P = P[(P.exit == "a2") & (P.level == "F")]
    J = T.merge(P[["key", "htf", "src"]], on=["key", "htf", "src"])
    actual["study_cells_h2_pooled"] = float(J.s2.sum() / J.n2.sum())
    actual["study_cells_n2"] = int(J.n2.sum())
    print(json.dumps(actual, indent=1, default=float), flush=True)
    nulls = {"coinday": [], "day": []}
    rng = np.random.default_rng(20261024)
    rng2 = np.random.default_rng(7)
    # day of each coin-day cluster (coinday = coin * 1000 + day offset)
    cd_day = eng.cd_u % 1000
    days_u, cd_day_inv = np.unique(cd_day, return_inverse=True)
    for i in range(nperm):
        for mode in ("coinday", "day"):
            if mode == "coinday":
                flip = rng.choice(np.array([-1, 1], np.int8), len(eng.cd_u))
            else:
                fd = rng2.choice(np.array([-1, 1], np.int8), len(days_u))
                flip = fd[cd_day_inv]
            c = eng.run(flip)
            Tn = eng.table(c, "a2", "F")
            t1, tk = FS.pick(Tn, "F", eng)
            nulls[mode].append((float(t1.score.iloc[0]), float(t1.m2.iloc[0]), FS.pooled(tk),
                                float(np.nanmean(tk.m2))))
        if i % 100 == 0:
            print("perm", i, round(time.time() - t0, 1), flush=True)
    res = {"cost_multiple": mult, "n_perm": nperm, "actual": actual}
    for mode, L in nulls.items():
        N = np.array(L)
        res[mode] = {"p_best": float(np.mean(N[:, 0] >= actual["best_score"])),
                     "p_top1_h2": float(np.mean(N[:, 1] >= actual["top1_h2"])),
                     "p_topk_h2": float(np.mean(N[:, 2] >= actual["topk_h2_pooled"])),
                     "p_topk_h2_eq": float(np.mean(N[:, 3] >= actual["topk_h2_eq"])),
                     "null_topk_h2_med": float(np.median(N[:, 2])), "null_topk_h2_p95": float(np.quantile(N[:, 2], .95))}
    json.dump(res, open(os.path.join(HERE_V, f"cxr_perm2_x{mult:g}.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k != "actual"}, indent=1))


if __name__ == "__main__":
    main()
