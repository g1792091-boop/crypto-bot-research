#!/usr/bin/env python3
"""Follow-ups on the scan (descriptive / robustness; not part of the pre-registered family):
 a) side-stratified contrasts (is a 'momentum' context just the run's market direction?)
 b) side-flip decomposition (v3b + v4 replay): context effect on R, on the other side's R, on the
    any-direction average (timing) and on the half-difference (direction skill)
 c) episode table for the session contrast (one row per run x KST evening)
 d) power: MDE80 by tf x scope and the days of data needed to detect 0.10 / 0.15 / 0.20 R

    python3 -I analysis2.py <lens_dir> <out_dir>
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
from scipy import stats  # noqa: E402

import features as F  # noqa: E402
from stats_util import contrast  # noqa: E402

LENS, OUT = sys.argv[1:3]
HOUR = 3_600_000
D = pd.read_csv(os.path.join(OUT, "signals_bucketed.csv.gz"), low_memory=False)
B = 2000
RUN_DAYS = {"v3a": None, "v3b": 0.699, "v4": 1.5}

MOM = [("ema_s", "with"), ("ema_s", "fade"), ("di_s", "with"), ("boxpos_s", "far_edge"), ("boxpos_s", "cheap_edge"),
       ("rangepos_s", "far_edge"), ("adx_b", "ge30"), ("brk", "yes"), ("session", "europe"), ("htfpos_s", "middle"),
       ("consensus", "many"), ("stop_t", "wide"), ("qtier", "best")]


def strat_contrast(x, col, bucket, strata, hours=2.0, seed=0, outcome="R"):
    """Within-stratum differences (strata = list of column names, e.g. ['run', 'side']), n-weighted, with time
    blocks resampled jointly per run (all strata of a run use the same block draw)."""
    rng = np.random.default_rng(seed)
    x = x[x[col].notna() & x[outcome].notna()]
    ests, ws, boots = [], [], []
    for run, g in x.groupby("run"):
        cl = (g["bar_close"] // int(hours * HOUR)).to_numpy()
        u, inv = np.unique(cl, return_inverse=True)
        G = len(u)
        idx = rng.integers(0, G, size=(B, G))
        for _, h in g.groupby([c for c in strata if c != "run"] or [lambda _: 0]):
            m = g.index.isin(h.index)
            inb = (g[col] == bucket).to_numpy() & m
            outb = (g[col] != bucket).to_numpy() & m
            if inb.sum() < 5 or outb.sum() < 5:
                continue
            y = g[outcome].to_numpy(float)
            si = np.bincount(inv, weights=np.where(inb, y, 0), minlength=G)
            ni = np.bincount(inv, weights=inb.astype(float), minlength=G)
            so = np.bincount(inv, weights=np.where(outb, y, 0), minlength=G)
            no = np.bincount(inv, weights=outb.astype(float), minlength=G)
            ests.append(si.sum() / ni.sum() - so.sum() / no.sum())
            ws.append(m.sum())
            with np.errstate(invalid="ignore", divide="ignore"):
                boots.append(si[idx].sum(1) / ni[idx].sum(1) - so[idx].sum(1) / no[idx].sum(1))
    if not ests:
        return np.nan, np.nan, 0
    ws = np.array(ws, float)
    d = float(np.dot(ws, ests) / ws.sum())
    bm = np.vstack(boots)
    bm = np.where(np.isfinite(bm), bm, np.nan)
    bd = np.nansum(ws[:, None] * bm, 0) / ws.sum()
    return d, float(np.std(bd, ddof=1)), int(ws.sum())


def part_a():
    rows = []
    k = 0
    for tf in ["15m", "30m"]:
        for kind, runs in (("strategy", ["v3a", "v3b", "v4"]), ("ds200", ["v4"])):
            x = D[(D["timeframe"] == tf) & (D["kind"] == kind) & D["run"].isin(runs)]
            for f, b in MOM:
                col = F.bucket_col(f)
                k += 1
                d0, se0, n0 = strat_contrast(x, col, b, ["run"], seed=k)
                d1, se1, n1 = strat_contrast(x, col, b, ["run", "side"], seed=k + 1000)
                # share of longs in the bucket vs out (per run) to show the direction mix
                mix = []
                for run in runs:
                    g = x[(x["run"] == run) & x[col].notna()]
                    if len(g):
                        mix.append(f"{run}:{(g[g[col] == b]['side'] > 0).mean():.2f}/{(g[g[col] != b]['side'] > 0).mean():.2f}")
                rows.append({"tf": tf, "kind": kind, "feature": f, "bucket": b, "d_run_only": d0, "se_run_only": se0,
                             "d_within_side": d1, "se_within_side": se1, "z_within_side": d1 / se1 if se1 else np.nan,
                             "long_share_in/out": " ".join(mix)})
    return pd.DataFrame(rows)


def part_b():
    rows = []
    k = 0
    x0 = D[D["run"].isin(["v3b", "v4"]) & D["flip_R"].notna()].copy()
    x0["any_dir"] = (x0["R"] + x0["flip_R"]) / 2
    x0["dir_skill"] = (x0["R"] - x0["flip_R"]) / 2
    for tf in ["15m", "30m"]:
        for kind in ("strategy", "ds200"):
            x = x0[(x0["timeframe"] == tf) & (x0["kind"] == kind)]
            for f, b in F.contrasts():
                col = F.bucket_col(f)
                r = {"tf": tf, "kind": kind, "feature": f, "bucket": b}
                for oc in ("R", "flip_R", "any_dir", "dir_skill"):
                    k += 1
                    rl = []
                    for run in ("v3b", "v4"):
                        g = x[(x["run"] == run) & x[col].notna()]
                        if len(g):
                            rl.append({"y": g[oc].to_numpy(float), "inb": (g[col] == b).to_numpy(),
                                       "bc": g["bar_close"].to_numpy(np.int64), "name": run})
                    c = contrast(rl, hours=2.0, B=B, seed=k)
                    r["n_in"] = c["n_in"]
                    r[f"d_{oc}"] = c["d"]
                    r[f"se_{oc}"] = c["se"]
                    r[f"p_{oc}"] = c["p_two"]
                rows.append(r)
    T = pd.DataFrame(rows)
    T["testable"] = T["n_in"] >= 30
    return T


def part_c():
    x = D[D["kind"].isin(["strategy", "ds200"]) & D["timeframe"].isin(["15m", "30m"])].copy()
    x["kst_date"] = pd.to_datetime((x["bar_close"] + 9 * HOUR), unit="ms").dt.strftime("%m-%d")
    rows = []
    for (run, kind, tf, day), g in x.groupby(["run", "kind", "timeframe", "kst_date"]):
        e = g[g["session"] == "europe"]
        o = g[g["session"] != "europe"]
        if len(e) >= 5 and len(o) >= 5:
            rows.append({"run": run, "kind": kind, "tf": tf, "kst_date": day, "n_europe": len(e), "R_europe": e["R"].mean(),
                         "n_other": len(o), "R_other": o["R"].mean(), "diff": e["R"].mean() - o["R"].mean(),
                         "R_europe_flip": e["flip_R"].mean(), "sessions_present": " ".join(sorted(g["session"].unique()))})
    E = pd.DataFrame(rows)
    return E


def part_d(T):
    """Power: MDE80 of every testable bucket contrast by tf x scope, and days of data needed."""
    span = {}
    for run in ("v3a", "v3b", "v4"):
        g = D[D["run"] == run]
        span[run] = (g["bar_close"].max() - g["bar_close"].min()) / (24 * HOUR)
    scope_days = {"v3a": span["v3a"], "v3b": span["v3b"], "v4": span["v4"], "v3b+v4": span["v3b"] + span["v4"],
                  "v3a+v3b": span["v3a"] + span["v3b"], "all": sum(span.values())}
    x = T[T["testable"]].copy()
    rows = []
    for (tf, kind, sc), g in x.groupby(["tf", "kind", "scope"]):
        mde = g["mde80"].median()
        days = scope_days[sc]
        r = {"tf": tf, "kind": kind, "scope": sc, "days_of_signals": days, "contrasts": len(g),
             "median_mde80_R": mde, "p25_mde80": g["mde80"].quantile(.25), "p75_mde80": g["mde80"].quantile(.75),
             "median_se": g["se"].median(), "median_n_in": g["n_in"].median()}
        for tgt in (0.10, 0.15, 0.20):
            r[f"days_needed_{tgt:.2f}R"] = days * (mde / tgt) ** 2
        # with a BH family of 60 contrasts the per-test alpha is ~0.05/60 for the first discovery
        z = stats.norm.ppf(1 - 0.05 / 60 / 2) + stats.norm.ppf(0.8)
        r["median_mde80_bonf60_R"] = g["se"].median() * z
        rows.append(r)
    return pd.DataFrame(rows), scope_days


def main():
    A = part_a()
    A.to_csv(os.path.join(OUT, "side_stratified.csv"), index=False)
    print(A.round(3).to_string())
    Bt = part_b()
    Bt.to_csv(os.path.join(OUT, "sideflip_by_context.csv"), index=False)
    T = pd.read_csv(os.path.join(OUT, "scan_full.csv"))
    P, sd = part_d(T)
    P.to_csv(os.path.join(OUT, "power_by_scope.csv"), index=False)
    print(sd)
    print(P.round(3).to_string())
    E = part_c()
    E.to_csv(os.path.join(OUT, "session_episodes.csv"), index=False)
    print(E.round(3).to_string())


if __name__ == "__main__":
    main()
