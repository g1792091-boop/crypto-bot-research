#!/usr/bin/env python3
"""Pre-registered context scan (protocol: out/prereg.json).

    python3 -I scan.py <lens_dir> <signals_master.csv.gz> <out_dir>
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
from stats_util import bh, contrast, cr_contrast, one_sided  # noqa: E402

LENS, MASTER, OUT = sys.argv[1:4]
B = 2000
TFS = ["15m", "30m", "1h"]


def load():
    D = pd.read_csv(MASTER, low_memory=False)
    D = D[(D["has_ctx"] == 1) & D["kind"].isin(["strategy", "ds200"]) & D["timeframe"].isin(TFS)].copy()
    # v3a: only the window the nightly skipped shadows cover (later skipped signals have no outcome -> biased)
    v3a = D["run"] == "v3a"
    cut = D.loc[v3a & (D["R_src"] == "shadow"), "bar_close"].max()
    D["in_window"] = ~v3a | (D["bar_close"] <= cut)
    D = D[D["in_window"] & D["R"].notna()].copy()
    D = F.add_buckets(D)
    D["Rw"] = D["R"].clip(-2, 3)
    D["win"] = (D["R"] > 0).astype(float)
    D["gross"] = D["R"] + D["cost_R_est"]
    return D, cut


def runs_list(D, scope, tf, kind, col, bucket, outcome="R", lo=None):
    out = []
    for run in scope:
        x = D[(D["run"] == run) & (D["timeframe"] == tf) & (D["kind"] == kind) & D[col].notna()]
        if lo is not None:
            x = x[x[col].isin([bucket, lo])]
        if not len(x):
            continue
        out.append({"y": x[outcome].to_numpy(float), "inb": (x[col] == bucket).to_numpy(),
                    "bc": x["bar_close"].to_numpy(np.int64), "name": run})
    return out


SCOPES = {"v3a": ["v3a"], "v3b": ["v3b"], "v4": ["v4"], "v3b+v4": ["v3b", "v4"], "v3a+v3b": ["v3a", "v3b"],
          "all": ["v3a", "v3b", "v4"]}


def full_table(D):
    rows = []
    k = 0
    for tf in TFS:
        for kind, scopes in (("strategy", list(SCOPES)), ("ds200", ["v4"])):
            for f, b in F.contrasts():
                col = F.bucket_col(f)
                for sc in scopes:
                    rl = runs_list(D, SCOPES[sc], tf, kind, col, b)
                    k += 1
                    r = contrast(rl, hours=2.0, B=B, seed=k)
                    r4 = contrast(rl, hours=4.0, B=B, seed=k + 10_000_000)
                    row = {"tf": tf, "kind": kind, "feature": f, "bucket": b, "scope": sc, **r,
                           "se_4h": r4["se"], "df_4h": r4["df"], "t_4h": r4["t"], "p_two_4h": r4["p_two"],
                           "G_4h": r4["G"]}
                    for oc in ("Rw", "win", "gross"):
                        d, se, df = cr_contrast(runs_list(D, SCOPES[sc], tf, kind, col, b, outcome=oc), hours=2.0)
                        row[f"d_{oc}"] = d
                        row[f"se_{oc}"] = se
                    rows.append(row)
    T = pd.DataFrame(rows)
    T["testable"] = (T["n_in"] >= 30) & (T["n_out"] >= 30) & T["se"].notna()
    return T


def directional(T, disc_scope, test_scope, disc_kind="strategy", test_kind="strategy", name=""):
    a = T[(T["scope"] == disc_scope) & (T["kind"] == disc_kind)].set_index(["tf", "feature", "bucket"])
    b = T[(T["scope"] == test_scope) & (T["kind"] == test_kind)].set_index(["tf", "feature", "bucket"])
    J = a.join(b, lsuffix="_disc", rsuffix="_test", how="left").reset_index()
    J["direction"] = name
    J["disc_testable"] = J["testable_disc"].fillna(False).astype(bool)
    J["test_testable"] = J["testable_test"].fillna(False).astype(bool)
    J["primary"] = J["tf"].isin(["15m", "30m"])
    # discovery BH (two-sided) within family (primary / secondary)
    J["disc_q"] = np.nan
    for prim in (True, False):
        m = J["primary"] == prim
        m2 = m & J["disc_testable"]
        q, _ = bh(J.loc[m2, "p_two_disc"].to_numpy())
        J.loc[m2, "disc_q"] = q
    J["carried"] = J["disc_testable"] & (J["p_two_disc"] < 0.05)
    sign = np.sign(J["d_disc"])
    J["p_test_1s"] = [one_sided(t, df, s) if c and tt else np.nan for t, df, s, c, tt in
                      zip(J["t_test"], J["df_test"], sign, J["carried"], J["test_testable"])]
    J["p_test_1s_4h"] = [one_sided(t, df, s) if c and tt else np.nan for t, df, s, c, tt in
                         zip(J["t_4h_test"], J["df_4h_test"], sign, J["carried"], J["test_testable"])]
    J["test_q"] = np.nan
    for prim in (True, False):
        m = (J["primary"] == prim) & J["carried"] & J["test_testable"]
        q, _ = bh(J.loc[m, "p_test_1s"].to_numpy())
        J.loc[m, "test_q"] = q
    J["same_sign"] = np.sign(J["d_disc"]) == np.sign(J["d_test"])
    J["replicated"] = (J["test_q"] < 0.05) & (J["p_test_1s_4h"] < 0.05) & J["same_sign"]
    return J


def omnibus(D, T, draws=1000, seed=7):
    """Correlation across contrasts of the v3a effect and the v4 effect (core 36), per tf; circular-shift null."""
    rng = np.random.default_rng(seed)
    out = []
    contr = F.contrasts()
    for tf in ["15m", "30m"]:
        a = T[(T["scope"] == "v3a") & (T["kind"] == "strategy") & (T["tf"] == tf) & T["testable"]]
        b = T[(T["scope"] == "v4") & (T["kind"] == "strategy") & (T["tf"] == tf) & T["testable"]]
        J = a.merge(b, on=["feature", "bucket"], suffixes=("_a", "_b"))
        keys = list(zip(J["feature"], J["bucket"]))
        ea, eb = J["d_a"].to_numpy(), J["d_b"].to_numpy()
        za, zb = J["t_a"].to_numpy(), J["t_b"].to_numpy()
        obs_r = float(np.corrcoef(ea, eb)[0, 1])
        obs_rz = float(np.corrcoef(za, zb)[0, 1])
        obs_agree = float(np.mean(np.sign(ea) == np.sign(eb)))
        # null: circular shift of R within each run (sorted by time) -> recompute point effects
        X = {}
        for run in ("v3a", "v4"):
            x = D[(D["run"] == run) & (D["timeframe"] == tf) & (D["kind"] == "strategy")].sort_values(
                ["bar_close", "sig_id"])
            masks = [(x[F.bucket_col(f)].notna().to_numpy(), (x[F.bucket_col(f)] == bkt).to_numpy()) for f, bkt in keys]
            X[run] = (x["R"].to_numpy(float), x["bar_close"].to_numpy(np.int64), masks)
        nulls_r, nulls_rz, nulls_ag = [], [], []
        for _ in range(draws):
            eff = {}
            zz = {}
            for run, (y0, bc, masks) in X.items():
                n = len(y0)
                k = int(rng.integers(n // 6, 5 * n // 6))
                y = np.roll(y0, k)
                ev, zv = [], []
                for m, inb in masks:
                    d, se, df = cr_contrast([{"y": y[m], "inb": inb[m], "bc": bc[m]}], hours=2.0)
                    ev.append(d)
                    zv.append(d / se if se == se and se > 0 else np.nan)
                eff[run] = np.array(ev)
                zz[run] = np.array(zv)
            ok = np.isfinite(eff["v3a"]) & np.isfinite(eff["v4"])
            nulls_r.append(np.corrcoef(eff["v3a"][ok], eff["v4"][ok])[0, 1])
            ok2 = np.isfinite(zz["v3a"]) & np.isfinite(zz["v4"])
            nulls_rz.append(np.corrcoef(zz["v3a"][ok2], zz["v4"][ok2])[0, 1])
            nulls_ag.append(np.mean(np.sign(eff["v3a"][ok]) == np.sign(eff["v4"][ok])))
        nr, nz, na = np.array(nulls_r), np.array(nulls_rz), np.array(nulls_ag)
        out.append({"tf": tf, "contrasts_both_testable": len(J), "corr_effects": obs_r,
                    "p_corr_gt_null": float(np.mean(nr >= obs_r)), "null_corr_p5_p95": f"{np.percentile(nr, 5):.3f} {np.percentile(nr, 95):.3f}",
                    "corr_t": obs_rz, "p_corr_t_gt_null": float(np.mean(nz >= obs_rz)),
                    "sign_agree": obs_agree, "p_agree_gt_null": float(np.mean(na >= obs_agree)),
                    "null_agree_mean": float(na.mean()), "draws": draws})
    return pd.DataFrame(out)


def hypotheses(D):
    rows = []
    k = 0
    for hid, fam, f, hi, lo, sgn in F.HYP:
        col = F.bucket_col(f)
        for tf in ["15m", "30m", "1h"]:
            for kind, scopes in (("strategy", ["v3a", "v3b", "v4", "all"]), ("ds200", ["v4"])):
                x = D if fam == "*" else D[D["family"] == fam]
                for sc in scopes:
                    k += 1
                    rl = runs_list(x, SCOPES[sc], tf, kind, col, hi, lo=lo)
                    r = contrast(rl, hours=2.0, B=B, seed=500_000 + k)
                    r4 = contrast(rl, hours=4.0, B=B, seed=900_000 + k)
                    rows.append({"hyp": hid, "family": fam, "feature": f, "hi": hi, "lo": lo, "expected_sign": sgn,
                                 "tf": tf, "kind": kind, "scope": sc, **r,
                                 "p_1s": one_sided(r["t"], r["df"], sgn), "p_1s_4h": one_sided(r4["t"], r4["df"], sgn)})
    H = pd.DataFrame(rows)
    H["testable"] = (H["n_in"] >= 20) & (H["n_out"] >= 20)
    # BH over the confirmatory family: every hypothesis x tf(15m,30m) x {strategy all-runs, ds200 v4}
    m = H["testable"] & H["tf"].isin(["15m", "30m"]) & (((H["kind"] == "strategy") & (H["scope"] == "all"))
                                                         | (H["kind"] == "ds200"))
    q, _ = bh(H.loc[m, "p_1s"].to_numpy())
    H["q_confirm"] = np.nan
    H.loc[m, "q_confirm"] = q
    # DiD: (trend: high ER - low ER) - (revert: high ER - low ER)
    return H


def did(D, draws=2000, seed=11):
    """Difference in differences of the ER effect between trend and revert families, per tf, all runs, cluster
    bootstrap by run x 2h block (both families resampled together)."""
    rng = np.random.default_rng(seed)
    rows = []
    for tf in ["15m", "30m"]:
        for kind, runs in (("strategy", ["v3a", "v3b", "v4"]), ("ds200", ["v4"])):
            x = D[(D["timeframe"] == tf) & (D["kind"] == kind) & D["family"].isin(["trend", "revert"])
                  & D["er_t"].isin(["high", "low"])]
            ests, boots, ws = [], [], []
            for run in runs:
                g = x[x["run"] == run]
                if g.groupby(["family", "er_t"]).size().reindex(
                        pd.MultiIndex.from_product([["trend", "revert"], ["high", "low"]])).fillna(0).min() < 5:
                    continue
                cl = (g["bar_close"] // (2 * 3_600_000)).to_numpy()
                u, inv = np.unique(cl, return_inverse=True)
                G = len(u)
                cells = {}
                for fam in ("trend", "revert"):
                    for e in ("high", "low"):
                        m = ((g["family"] == fam) & (g["er_t"] == e)).to_numpy()
                        cells[(fam, e)] = (np.bincount(inv, weights=np.where(m, g["R"], 0.0), minlength=G),
                                           np.bincount(inv, weights=m.astype(float), minlength=G))

                def est(idx=None):
                    v = {}
                    for kk, (s, n) in cells.items():
                        v[kk] = (s.sum() / n.sum()) if idx is None else (s[idx].sum(1) / n[idx].sum(1))
                    return (v[("trend", "high")] - v[("trend", "low")]) - (v[("revert", "high")] - v[("revert", "low")])
                ests.append(est())
                boots.append(est(rng.integers(0, G, size=(draws, G))))
                ws.append(len(g))
            if not ests:
                continue
            ws = np.array(ws, float)
            d = float(np.dot(ws, ests) / ws.sum())
            bd = (ws[:, None] * np.vstack(boots)).sum(0) / ws.sum()
            bd = bd[np.isfinite(bd)]
            se = float(np.std(bd, ddof=1))
            rows.append({"tf": tf, "kind": kind, "runs": len(ests), "n": int(ws.sum()), "did_R": d, "se": se,
                         "z": d / se if se else np.nan, "p_1s_trend_more_ER_sensitive": float(np.mean(bd <= 0))})
    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    D, cut = load()
    D.to_csv(os.path.join(OUT, "signals_bucketed.csv.gz"), index=False)
    n = D.groupby(["run", "kind", "timeframe"]).size().rename("n").reset_index()
    n.to_csv(os.path.join(OUT, "scan_sample_sizes.csv"), index=False)
    print(n.to_string(), "\nv3a cut (last shadow bar_close)", cut)
    T = full_table(D)
    T.to_csv(os.path.join(OUT, "scan_full.csv"), index=False)
    A = directional(T, "v3a", "v3b+v4", name="A_v3a_to_v3b+v4")
    Bd = directional(T, "v4", "v3a+v3b", name="B_v4_to_v3a+v3b")
    X = directional(T, "v3a", "v4", test_kind="ds200", name="T_v3a_core_to_v4_ds200")
    DT = pd.concat([A, Bd, X], ignore_index=True)
    DT.to_csv(os.path.join(OUT, "scan_directional.csv"), index=False)
    H = hypotheses(D)
    H.to_csv(os.path.join(OUT, "hypotheses.csv"), index=False)
    DD = did(D)
    DD.to_csv(os.path.join(OUT, "did_er_family.csv"), index=False)
    O = omnibus(D, T)
    O.to_csv(os.path.join(OUT, "omnibus_corr.csv"), index=False)
    print(O.to_string())
    print(DD.to_string())


if __name__ == "__main__":
    main()
