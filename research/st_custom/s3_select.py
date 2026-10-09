"""Stage 3: selection on SEARCH only (PREREG 'Selection'), for every strategy x timeframe x variant.

Pooled over coins: combos with >= 200 SEARCH trades; score = unweighted mean of the combo means (mean net R) over the
combo and its +-1-step neighbours (Moore neighbourhood) that have >= 1 SEARCH trade; top 3 = plateau picks.
Per coin: the same with >= 100 trades on that coin, top 1.
Also writes, for every combo, the pooled and per-coin totals of every period (combo_totals_*.csv.gz is NOT written to
out/: too big; it stays in the work folder as an npz for later stages).

    python3 -B research/st_custom/s3_select.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import s2_signals as S2  # noqa: E402

MIN_POOLED, MIN_COIN, TOPN = 200, 100, 3
AGG = os.path.join(C.WORK, "agg_totals.npz")


def load_totals():
    """T[strat]: array (tf, period, coin, variant, combo, stat)."""
    out = {}
    for strat in C.STRATS:
        A = np.zeros((len(C.TFS), len(C.PERIOD_ORDER), len(C.COINS), S2.NV, C.NCOMBO[strat], len(S2.STATS)))
        for ti, tf in enumerate(C.TFS):
            for pi, per in enumerate(C.PERIOD_ORDER):
                for ci, coin in enumerate(C.COINS):
                    p = S2.tot_path(coin, tf, per)
                    if not os.path.exists(p):
                        raise SystemExit(f"missing {p}")
                    A[ti, pi, ci] = np.load(p)[f"{strat}__tot"]
        out[strat] = A
    return out


def plateau(n, mean, nb_mat, min_n):
    """score per combo (NaN if not eligible)."""
    has = (n >= 1).astype(np.float32)
    m0 = np.where(n >= 1, mean, 0.0)
    num = nb_mat @ m0
    den = nb_mat @ has
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = num / den
    return np.where(n >= min_n, sc, np.nan)


def top(score, k):
    ok = np.flatnonzero(np.isfinite(score))
    if not len(ok):
        return []
    order = ok[np.lexsort((ok, -score[ok]))]
    return [int(x) for x in order[:k]]


def main():
    C.check_prereg()
    T = load_totals()
    np.savez_compressed(AGG, **T)
    rows = []
    for strat in C.STRATS:
        NB = C.neighbour_matrix(strat)
        A = T[strat]
        for ti, tf in enumerate(C.TFS):
            for v, vname in enumerate(S2.VARIANTS):
                srch = A[ti, 0, :, v]          # (coin, combo, stat)
                n = srch[..., 0].sum(0)
                s = srch[..., 2].sum(0)
                with np.errstate(invalid="ignore", divide="ignore"):
                    mean = s / n
                sc = plateau(n, mean, NB, MIN_POOLED)
                for rank, c in enumerate(top(sc, TOPN), 1):
                    rows.append(dict(strategy=strat, tf=tf, variant=vname, scope="pooled", coin="ALL", rank=rank,
                                     combo=c, label=C.combo_label(strat, c), score=sc[c], search_n=int(n[c]),
                                     search_meanR=mean[c], eligible=int(np.isfinite(sc).sum())))
                for ci, coin in enumerate(C.COINS):
                    nc_ = srch[ci, :, 0]
                    with np.errstate(invalid="ignore", divide="ignore"):
                        mc = srch[ci, :, 2] / nc_
                    scc = plateau(nc_, mc, NB, MIN_COIN)
                    for rank, c in enumerate(top(scc, 1), 1):
                        rows.append(dict(strategy=strat, tf=tf, variant=vname, scope="coin", coin=coin, rank=rank,
                                         combo=c, label=C.combo_label(strat, c), score=scc[c], search_n=int(nc_[c]),
                                         search_meanR=mc[c], eligible=int(np.isfinite(scc).sum())))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(C.OUT, "picks.csv"), index=False)
    C.log(df[(df.variant == "main") & (df.scope == "pooled")].to_string())
    return df


if __name__ == "__main__":
    main()
