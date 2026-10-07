#!/usr/bin/env python3
"""Paired rule-minus-base statistics from rules_signals.csv (PREREG.md test).

    python3 -I rules_stats.py <out_dir>
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
sys.path.append(site.getusersitepackages())
import os  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
TFM = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
RULES = ["BE05", "BE10", "NP4", "NP8", "TP1", "PART1", "CUT05", "OPP", "OPPH"]
RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
B = 10_000


def bh(p):
    p = np.asarray(p, float)
    q = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    if ok.sum() == 0:
        return q
    pv = p[ok]
    o = np.argsort(pv)
    m = len(pv)
    r = pv[o] * m / np.arange(1, m + 1)
    r = np.minimum.accumulate(r[::-1])[::-1]
    qq = np.empty(m)
    qq[o] = np.minimum(r, 1)
    q[ok] = qq
    return q


def cluster_test(diff: np.ndarray, cl: np.ndarray, rng) -> dict:
    """Sign-flip with one sign per cluster (p_better one-sided, p_two), cluster-bootstrap 95% CI of the mean."""
    n = len(diff)
    if n < 3:
        return {}
    u, inv = np.unique(cl, return_inverse=True)
    sums = np.bincount(inv, weights=diff)
    cnt = np.bincount(inv)
    obs = diff.mean()
    k = len(u)
    signs = rng.choice([-1.0, 1.0], size=(B, k))
    null = signs @ sums / n
    p_better = (np.sum(null >= obs - 1e-15) + 1) / (B + 1)
    p_two = (np.sum(np.abs(null) >= abs(obs) - 1e-15) + 1) / (B + 1)
    idx = rng.integers(0, k, size=(2000, k))
    bs = sums[idx].sum(1) / cnt[idx].sum(1)
    return {"n": n, "clusters": k, "mean_diff": obs, "ci_lo": np.percentile(bs, 2.5), "ci_hi": np.percentile(bs, 97.5),
            "p_better": p_better, "p_two": p_two, "share_better": float(np.mean(diff > 1e-9)),
            "share_worse": float(np.mean(diff < -1e-9))}


def main():
    out = sys.argv[1]
    R = pd.read_csv(os.path.join(out, "rules_signals.csv"))
    R = R[R["base_status"].isin(["TRADED", "UNRESOLVED"])].copy()
    R["PART1_R"] = 0.5 * (R["base_R"] + R["TP1_R"])
    R["run_s"] = R["run"].map(RUNS)
    R["tf_min"] = R["timeframe"].map(TFM)
    R["cl"] = R["run_s"] + "|" + (R["bar_close"] // (np.maximum(R["tf_min"], 60) * MIN)).astype(str)
    R["resolved"] = R["base_status"] == "TRADED"
    rng = np.random.default_rng(20261007)
    rows = []
    for incl in ("all", "resolved_only"):
        D0 = R if incl == "all" else R[R["resolved"]]
        for kind in ("strategy", "ds200", "random", "ALL_NONRANDOM"):
            Dk = D0[D0["kind"] != "random"] if kind == "ALL_NONRANDOM" else D0[D0["kind"] == kind]
            for tf in ["15m", "30m", "1h", "4h", "ALL"]:
                Dt = Dk if tf == "ALL" else Dk[Dk["timeframe"] == tf]
                if not len(Dt):
                    continue
                for rule in RULES:
                    row = {"incl": incl, "kind": kind, "timeframe": tf, "rule": rule,
                           "mean_R_base": Dt["base_R"].mean(), "mean_R_rule": Dt[f"{rule}_R"].mean()}
                    for rs in ("v3b", "v4"):
                        g = Dt[Dt["run_s"] == rs]
                        d = (g[f"{rule}_R"] - g["base_R"]).to_numpy(float)
                        row[f"n_{rs}"] = len(d)
                        row[f"diff_{rs}"] = d.mean() if len(d) else np.nan
                    d = (Dt[f"{rule}_R"] - Dt["base_R"]).to_numpy(float)
                    ok = np.isfinite(d)
                    row.update(cluster_test(d[ok], Dt["cl"].to_numpy()[ok], rng))
                    row["same_sign_pos"] = bool(row.get("diff_v3b", np.nan) > 0 and row.get("diff_v4", np.nan) > 0)
                    row["same_sign_neg"] = bool(row.get("diff_v3b", np.nan) < 0 and row.get("diff_v4", np.nan) < 0)
                    rows.append(row)
    S = pd.DataFrame(rows)
    # BH over the pre-declared family: rule x (kind in strategy/ds200) x (tf in 15m/30m/1h/4h), incl == all
    fam = (S["incl"] == "all") & S["kind"].isin(["strategy", "ds200"]) & (S["timeframe"] != "ALL")
    S["bh_q_better"] = np.nan
    S.loc[fam, "bh_q_better"] = bh(S.loc[fam, "p_better"])
    S["bh_q_two"] = np.nan
    S.loc[fam, "bh_q_two"] = bh(S.loc[fam, "p_two"])
    S["verdict"] = np.where(fam & S["same_sign_pos"] & (S["bh_q_better"] < 0.05), "HELPS (prereg pass)",
                   np.where(S["same_sign_pos"], "same sign +, unproven",
                   np.where(S["same_sign_neg"], "hurts in both runs", "mixed sign")))
    S.to_csv(os.path.join(out, "rules_stats.csv"), index=False)

    # strategy x tf cells (description only), incl all
    cells = []
    for (kind, strat, tf), g in R[R["kind"] != "random"].groupby(["kind", "strategy", "timeframe"]):
        for rule in RULES:
            d = (g[f"{rule}_R"] - g["base_R"]).to_numpy(float)
            row = {"kind": kind, "strategy": strat, "timeframe": tf, "rule": rule, "n": len(d),
                   "mean_R_base": g["base_R"].mean(), "mean_R_rule": g[f"{rule}_R"].mean()}
            for rs in ("v3b", "v4"):
                gg = g[g["run_s"] == rs]
                row[f"n_{rs}"] = len(gg)
                row[f"diff_{rs}"] = (gg[f"{rule}_R"] - gg["base_R"]).mean() if len(gg) else np.nan
            if len(d) >= 8:
                row.update({k: v for k, v in cluster_test(d, g["cl"].to_numpy(), rng).items() if k != "n"})
            else:
                row["mean_diff"] = d.mean()
            cells.append(row)
    C = pd.DataFrame(cells)
    C["bh_q_two"] = np.nan
    m = C["p_two"].notna() if "p_two" in C else pd.Series(False, index=C.index)
    C.loc[m, "bh_q_two"] = bh(C.loc[m, "p_two"])
    C.to_csv(os.path.join(out, "rules_cells.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    show = S[(S["incl"] == "all") & S["kind"].isin(["strategy", "ds200"])]
    print(show[["kind", "timeframe", "rule", "n", "clusters", "mean_R_base", "mean_diff", "ci_lo", "ci_hi", "diff_v3b",
                "diff_v4", "n_v3b", "n_v4", "p_better", "p_two", "bh_q_two", "verdict"]].round(4).to_string())
    print("cells with bh_q_two<0.1:")
    print(C[C["bh_q_two"] < 0.1].round(4).to_string())


if __name__ == "__main__":
    main()
