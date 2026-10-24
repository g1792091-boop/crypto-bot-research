"""Verifier: re-run the WHOLE search of fw_search.py (H1 pick -> H2 read) under side-flip nulls with different cluster
units, to see how much the a2 family TOP5 p = 0.008 depends on treating the six coins of a day as independent.

modes
  coinday  the original null (each (coin, UTC day) flips on its own); with the original seed the first rows must equal
           search_perm.csv (reproduction check)
  day      every coin of a UTC day flips together (crypto coins move together; keeps the cross-coin dependence)
  day2     two-day global blocks (coarser still)
Writes rc_perm_<mode>.csv and prints p-values for all four searches.  Run: python3 rc_perm.py <mode> <n_perm>"""
import os
import sys
import json
import time

FW = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, FW)
from fw_lib import *  # noqa: F401,F403,E402
_argv = sys.argv
sys.argv = [sys.argv[0]]
import fw_search as FS  # noqa: E402
sys.argv = _argv

OUTD = os.path.dirname(os.path.abspath(__file__))


def main():
    mode = sys.argv[1]
    nperm = int(sys.argv[2])
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    eng = FS.Engine(S)
    cells = eng.run()
    actual = {}
    for v in ("w35", "a2"):
        for lab in ("E", "F"):
            T = eng.table(cells, v, lab)
            top1, topk = FS.pick(T, lab, eng)
            actual[f"{v}_{lab}"] = {"best": float(top1.score.iloc[0]), "top1_h2": float(top1.m2.iloc[0]),
                                    "topk_h2": FS.pooled(topk), "topk_h2_eq": float(np.nanmean(topk.m2))}
    print("actual", json.dumps(actual))
    cd_day = (eng.cd_u % 1000).astype(np.int64)          # day index (0..nd-1) of each coin-day cluster
    seed = 20261024 if mode == "coinday" else {"day": 11, "day2": 12}[mode]
    rng = np.random.default_rng(seed)
    rows = []
    t0 = time.time()
    for i in range(nperm):
        if mode == "coinday":
            flip = rng.choice(np.array([-1, 1], np.int8), len(eng.cd_u))
        elif mode == "day":
            fd = rng.choice(np.array([-1, 1], np.int8), eng.nd)
            flip = fd[cd_day]
        else:
            fd = rng.choice(np.array([-1, 1], np.int8), eng.nd // 2 + 1)
            flip = fd[cd_day // 2]
        c = eng.run(flip)
        row = {"perm": i}
        for v in ("w35", "a2"):
            for lab in ("E", "F"):
                T = eng.table(c, v, lab)
                top1, topk = FS.pick(T, lab, eng)
                k = f"{v}_{lab}"
                row[f"{k}_best"] = float(top1.score.iloc[0])
                row[f"{k}_top1_h2"] = float(top1.m2.iloc[0])
                row[f"{k}_topk_h2"] = FS.pooled(topk)
                row[f"{k}_topk_h2_eq"] = float(np.nanmean(topk.m2))
                if k == "a2_F":
                    row["a2_F_picks"] = ";".join(f"{eng.fams[r.id]}@{eng.blocks[r.block]['htf']}:{r.src}"
                                                  for _, r in topk.iterrows())
        rows.append(row)
        if i % 100 == 0:
            print("perm", i, round(time.time() - t0, 1), flush=True)
    N = pd.DataFrame(rows)
    N.to_csv(os.path.join(OUTD, f"rc_perm_{mode}.csv"), index=False, float_format="%.6g")
    summ = {}
    for k, a in actual.items():
        summ[k] = {s: {"actual": a[s], "p": float(np.mean(N[f"{k}_{s}"] >= a[s])),
                       "p_plus1": float((np.sum(N[f"{k}_{s}"] >= a[s]) + 1) / (len(N) + 1)),
                       "null_med": float(N[f"{k}_{s}"].median()), "null_p95": float(N[f"{k}_{s}"].quantile(0.95))}
                   for s in ("best", "top1_h2", "topk_h2", "topk_h2_eq")}
    json.dump({"mode": mode, "n_perm": nperm, "summary": summ}, open(os.path.join(OUTD, f"rc_perm_{mode}.json"), "w"),
              indent=1)
    print(json.dumps(summ["a2_F"], indent=1))
    if mode == "coinday":
        O = pd.read_csv(os.path.join(FW, "search_perm.csv"))
        m = min(len(O), len(N))
        for col in ("a2_F_topk_h2", "a2_F_best", "w35_E_top1_h2"):
            print("repro", col, float(np.max(np.abs(O[col].to_numpy()[:m] - N[col].to_numpy()[:m]))))


if __name__ == "__main__":
    main()
