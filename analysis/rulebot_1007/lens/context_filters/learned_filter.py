#!/usr/bin/env python3
"""Can a filter LEARNED on one run's signal contexts pick better signals in another run?

Ridge regression of R on one-hot buckets of the pre-registered features (+ tf, kind dummies), ridge lambda chosen
by blocked CV inside the training run (4 folds of contiguous time). Applied to the other run: keep the top third
(and top half) of signals by predicted R within each run x tf; uplift = mean R(kept) - mean R(all).
CI: 2h block bootstrap of the test run (prediction fixed). Null: refit on training R circularly shifted in time
(200 draws) -> distribution of the test uplift when the training contexts carry no information.

    python3 -I learned_filter.py <lens_dir> <out_dir>
"""
from __future__ import annotations

import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
sys.path.insert(0, sys.argv[1])

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import features as F  # noqa: E402

LENS, OUT = sys.argv[1:3]
HOUR = 3_600_000
D = pd.read_csv(os.path.join(OUT, "signals_bucketed.csv.gz"), low_memory=False)
D = D[D["timeframe"].isin(["15m", "30m"])].copy()
FEATS_ALL = [f for f in F.FEATURES]
FEATS_CHART = [f for f in F.FEATURES if f not in ("side", "coin", "session")]


def design(x, feats, cols=None):
    parts = []
    for f in feats:
        c = F.bucket_col(f)
        parts.append(pd.get_dummies(x[c].fillna("NA").astype(str), prefix=f, dtype=float))
    parts.append(pd.get_dummies(x["timeframe"], prefix="tf", dtype=float))
    parts.append(pd.get_dummies(x["kind"], prefix="kind", dtype=float))
    X = pd.concat(parts, axis=1)
    if cols is not None:
        X = X.reindex(columns=cols, fill_value=0.0)
    return X


def ridge_fit(X, y, lam):
    mu = X.mean(0)
    Xc = X - mu
    ym = y.mean()
    A = Xc.T @ Xc + lam * np.eye(X.shape[1])
    w = np.linalg.solve(A, Xc.T @ (y - ym))
    return w, mu, ym


def ridge_pred(model, X):
    w, mu, ym = model
    return (X - mu) @ w + ym


def choose_lambda(X, y, t, lams=(1, 10, 100, 1000, 10000)):
    order = np.argsort(t)
    folds = np.array_split(order, 4)
    best, bl = None, None
    for lam in lams:
        err = 0.0
        for k in range(4):
            te = folds[k]
            tr = np.concatenate([folds[j] for j in range(4) if j != k])
            m = ridge_fit(X[tr], y[tr], lam)
            err += float(((ridge_pred(m, X[te]) - y[te]) ** 2).sum())
        if best is None or err < best:
            best, bl = err, lam
    return bl


def uplift(test, pred, frac):
    """mean R of the top `frac` by prediction within each run x tf, minus mean R of all (n-weighted)."""
    test = test.assign(pred=pred)
    keep = np.zeros(len(test), bool)
    for _, g in test.groupby(["run", "timeframe"]):
        thr = g["pred"].quantile(1 - frac)
        keep[test.index.get_indexer(g.index[g["pred"] >= thr])] = True
    return keep


def boot_uplift(test, keep, B=2000, seed=3):
    rng = np.random.default_rng(seed)
    y = test["R"].to_numpy(float)
    est = y[keep].mean() - y.mean()
    boots = []
    parts = []
    for run, g in test.reset_index(drop=True).groupby("run"):
        idx = g.index.to_numpy()
        cl = (g["bar_close"] // (2 * HOUR)).to_numpy()
        u, inv = np.unique(cl, return_inverse=True)
        G = len(u)
        parts.append((np.bincount(inv, weights=y[idx] * keep[idx], minlength=G),
                      np.bincount(inv, weights=keep[idx].astype(float), minlength=G),
                      np.bincount(inv, weights=y[idx], minlength=G), np.bincount(inv, minlength=G).astype(float), G))
    for _ in range(B):
        a = b = c = d = 0.0
        for sk, nk, sa, na, G in parts:
            i = rng.integers(0, G, G)
            a += sk[i].sum(); b += nk[i].sum(); c += sa[i].sum(); d += na[i].sum()
        boots.append(a / b - c / d)
    boots = np.array(boots)
    return est, float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)), float(np.std(boots, ddof=1))


def run_one(train, test, feats, label, null_draws=200, seed=0):
    rng = np.random.default_rng(seed)
    Xtr_df = design(train, feats)
    cols = Xtr_df.columns
    Xtr = Xtr_df.to_numpy(float)
    ytr = train["R"].to_numpy(float)
    ttr = train["bar_close"].to_numpy()
    lam = choose_lambda(Xtr, ytr, ttr)
    m = ridge_fit(Xtr, ytr, lam)
    test = test.reset_index(drop=True)
    Xte = design(test, feats, cols).to_numpy(float)
    p = ridge_pred(m, Xte)
    yte = test["R"].to_numpy(float)
    corr = float(np.corrcoef(p, yte)[0, 1])
    from scipy.stats import spearmanr
    rho = float(spearmanr(p, yte).correlation)
    out = {"model": label, "lambda": lam, "n_train": len(train), "n_test": len(test), "features": len(cols),
           "test_corr": corr, "test_spearman": rho}
    # in-sample (same run) uplift for reference
    keep_is = uplift(train.reset_index(drop=True), ridge_pred(m, Xtr), 1 / 3)
    out["insample_uplift_top3rd"] = float(ytr[keep_is].mean() - ytr.mean())
    for frac, tag in ((1 / 3, "top3rd"), (1 / 2, "top half")):
        keep = uplift(test, p, frac)
        est, lo, hi, se = boot_uplift(test, keep)
        out[f"uplift_{tag}"] = est
        out[f"ci95_{tag}"] = f"{lo:.3f} {hi:.3f}"
        out[f"mean_R_kept_{tag}"] = float(yte[keep].mean())
    out["mean_R_all_test"] = float(yte.mean())
    # null: circular shift of training R within run x tf
    nulls = []
    tr = train.reset_index(drop=True)
    for _ in range(null_draws):
        ysh = ytr.copy()
        for _, g in tr.groupby(["run", "timeframe"]):
            idx = g.sort_values("bar_close").index.to_numpy()
            k = int(rng.integers(len(idx) // 6, 5 * len(idx) // 6))
            ysh[idx] = np.roll(ytr[idx], k)
        mn = ridge_fit(Xtr, ysh, lam)
        keep = uplift(test, ridge_pred(mn, Xte), 1 / 3)
        nulls.append(yte[keep].mean() - yte.mean())
    nulls = np.array(nulls)
    out["null_uplift_top3rd_mean"] = float(nulls.mean())
    out["null_uplift_top3rd_p95"] = float(np.percentile(nulls, 95))
    out["p_uplift_vs_null"] = float(np.mean(nulls >= out["uplift_top3rd"]))
    return out


def main():
    core = D[D["kind"] == "strategy"]
    rows = []
    for feats, fl in ((FEATS_ALL, "all features"), (FEATS_CHART, "chart only (no side/coin/session)")):
        rows.append(run_one(core[core["run"] == "v3a"], core[core["run"].isin(["v3b", "v4"])], feats,
                            f"train v3a core -> test v3b+v4 core | {fl}", seed=1))
        rows.append(run_one(core[core["run"] == "v3a"], D[(D["run"] == "v4") & (D["kind"] == "ds200")], feats,
                            f"train v3a core -> test v4 ds200 | {fl}", seed=2))
        rows.append(run_one(D[(D["run"] == "v4")], core[core["run"].isin(["v3a", "v3b"])], feats,
                            f"train v4 core+ds200 -> test v3a+v3b core | {fl}", seed=3))
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(OUT, "learned_filter.csv"), index=False)
    pd.set_option("display.width", 250)
    print(R.round(3).T.to_string())


if __name__ == "__main__":
    main()
