"""Stage 2 of the five-year role study: from the accumulators of build_acc.py, the cell table and the general reads.

A cell = (mapping pair, trend source, entry strategy sid, condition with / against / neutral / all). For each period
(SEL, CONF, LATE, FWD): n, mean net ROE per trade under w35 (35x, -50 % net stop, ladder) and the coin-flip twin
(the opposite side on the same entries), month-clustered t statistics (SEL / CONF), the alternative exits (w30,
w35s20, a2), long share, the trend-only baseline (the source's side at EVERY bar of the entry timeframe) and the
drift-matched coin flip (long share x all-bar long ROE + short share x all-bar short ROE of the same period).

Outputs (this folder): general_effect.csv (per pair x source: median / pooled effect of alignment across entry
strategies, SEL and CONF), role_effect.csv (per role x pair for the main judges), source_rank.csv, cells_with_sel.csv.gz
(every with-cell with SEL n >= 30: SEL + CONF + LATE + FWD reads), selection.csv (the cells picked on SEL and their one
CONF read), friend_cells.csv (the friend's own example and the trend bot's 18 members).

    python3 fy_analyze.py"""
import json
from scipy import stats as sst
from fy_common import *

MIN_N = 30          # a cell is read only with at least this many trades in the period
SEL_MIN = 60        # cells eligible for selection need this many SEL trades
Q = 0.10            # BH false discovery rate


def load():
    meta = json.load(open(os.path.join(SHM, "meta.json")))
    A = np.load(os.path.join(SHM, "acc.npy"), mmap_mode="r")
    AM = np.load(os.path.join(SHM, "accm.npy"), mmap_mode="r")
    B = np.load(os.path.join(SHM, "base.npy"))
    B0 = np.load(os.path.join(SHM, "base0.npy"))
    BARS = np.load(os.path.join(SHM, "bars.npy"))
    nsid = len(meta["sid_name"])
    P, NS = A.shape[0], A.shape[1]
    A = np.asarray(A).reshape(P, NS, 3, nsid, NB, K)
    AM = np.asarray(AM).reshape(P, NS, 3, nsid, NMON, 3)
    return meta, A, AM, B, B0, BARS


def months_of(per):
    a, b = {"SEL": ("2021-01-01", "2024-01-01"), "CONF": ("2024-01-01", "2026-10-01"),
            "LATE": ("2026-01-01", "2026-10-23"), "FWD": ("2026-10-01", "2026-11-01")}[per]
    ma = (pd.Timestamp(a).year - 2021) * 12 + pd.Timestamp(a).month - 1
    mb = (pd.Timestamp(b).year - 2021) * 12 + pd.Timestamp(b).month - 1
    return slice(ma, min(mb, NMON))


def cluster_t(n_m, s_m, n2_m=None, s2_m=None, d_m=None):
    """Month-clustered t of a ratio mean (s / n), of a difference of two ratio means (s/n - s2/n2), or of a paired
    difference (d_m = monthly sums of w - opposite over the same trades n_m). Arrays [..., months]. Returns (est, t, M)."""
    N = n_m.sum(-1)
    M = (n_m > 0).sum(-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        if d_m is not None:
            mu = d_m.sum(-1) / N
            u = (d_m - mu[..., None] * n_m) / N[..., None]
        elif n2_m is None:
            mu = s_m.sum(-1) / N
            u = (s_m - mu[..., None] * n_m) / N[..., None]
        else:
            N2 = n2_m.sum(-1)
            mu1, mu2 = s_m.sum(-1) / N, s2_m.sum(-1) / N2
            mu = mu1 - mu2
            u = (s_m - mu1[..., None] * n_m) / N[..., None] - (s2_m - mu2[..., None] * n2_m) / N2[..., None]
        var = (u ** 2).sum(-1) * M / np.maximum(M - 1, 1)
        t = mu / np.sqrt(var)
    return mu, t, M


def pval(t, M):
    with np.errstate(invalid="ignore"):
        return sst.t.sf(t, np.maximum(M - 1, 1))


def bh(p, q=Q):
    """Benjamini-Hochberg: boolean pass array (NaN p never passes)."""
    p = np.asarray(p, float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    if not ok.any():
        return out
    pp = p[ok]
    o = np.argsort(pp)
    m = len(pp)
    thr = q * np.arange(1, m + 1) / m
    passed = pp[o] <= thr
    if passed.any():
        kmax = np.max(np.flatnonzero(passed))
        sel = np.zeros(m, bool)
        sel[o[:kmax + 1]] = True
        out[np.flatnonzero(ok)] = sel
    return out


def per_sum(X, per, axis):
    return np.take(X, PER[per], axis=axis).sum(axis=axis)


def cell_table(meta, A, AM, B, BARS):
    """Long table: one row per (pair, src, sid) with with / against / neutral / all reads per period."""
    N = RD.names().set_index("sid")
    SRC = meta["src"]
    rows = []
    out = {}
    P, NS = A.shape[0], A.shape[1]
    nsid = A.shape[3]
    pi_g, s_g, sid_g = np.meshgrid(np.arange(P), np.arange(NS), np.arange(nsid), indexing="ij")
    out["pair"] = pi_g.ravel()
    out["src"] = s_g.ravel()
    out["sid"] = sid_g.ravel()
    for per in ("SEL", "CONF", "LATE", "FWD"):
        X = per_sum(A, per, axis=4)                    # [P, NS, 3, nsid, K]
        allx = X.sum(axis=2)                           # all conditions
        for ci, cn in ((2, "W"), (0, "A"), (1, "N"), (None, "ALL")):
            Y = allx if ci is None else X[:, :, ci]
            n = Y[..., SI["n"]]
            with np.errstate(invalid="ignore", divide="ignore"):
                out[f"{per}_n{cn}"] = n.ravel()
                out[f"{per}_m{cn}"] = (Y[..., SI["w35"]] / n).ravel()
                if cn == "W":
                    m = Y[..., SI["w35"]] / n
                    out[f"{per}_sd{cn}"] = np.sqrt(np.maximum(Y[..., SI["w35_2"]] / n - m ** 2, 0)).ravel()
                    out[f"{per}_mWo"] = (Y[..., SI["w35o"]] / n).ravel()
                    out[f"{per}_winW"] = (Y[..., SI["win"]] / n).ravel()
                    out[f"{per}_lsW"] = (Y[..., SI["nlong"]] / n).ravel()
                    for v in ("w30", "s20", "a2"):
                        out[f"{per}_{v}W"] = (Y[..., SI[v]] / n).ravel()
                        out[f"{per}_{v}Wo"] = (Y[..., SI[v + "o"]] / n).ravel()
                if cn == "A":
                    out[f"{per}_mAo"] = (Y[..., SI["w35o"]] / n).ravel()
        # trend-only baseline of the pair x source (every bar of the entry tf, the source's side)
        Bp = per_sum(B, per, axis=2)                   # [P, NS, K]
        with np.errstate(invalid="ignore", divide="ignore"):
            mT = Bp[..., SI["w35"]] / Bp[..., SI["n"]]
            lsT = Bp[..., SI["nlong"]] / Bp[..., SI["n"]]
        out[f"{per}_mT"] = np.broadcast_to(mT[:, :, None], (P, NS, nsid)).ravel()
        out[f"{per}_lsT"] = np.broadcast_to(lsT[:, :, None], (P, NS, nsid)).ravel()
        # drift-matched coin flip for the with-cell: all bars of the entry tf, long / short mean in the period
        Bt = per_sum(BARS, per, axis=1)                # [tf, 2, K]
        with np.errstate(invalid="ignore", divide="ignore"):
            mL = Bt[:, 0, SI["w35"]] / Bt[:, 0, SI["n"]]
            mS = Bt[:, 1, SI["w35"]] / Bt[:, 1, SI["n"]]
        tfi = np.array([TFS.index(PAIRS[p][0]) for p in range(P)])
        ls = out[f"{per}_lsW"].reshape(P, NS, nsid)
        out[f"{per}_mDrift"] = (ls * mL[tfi][:, None, None] + (1 - ls) * mS[tfi][:, None, None]).ravel()
        out[f"{per}_barL"] = np.broadcast_to(mL[tfi][:, None, None], (P, NS, nsid)).ravel()
        out[f"{per}_barS"] = np.broadcast_to(mS[tfi][:, None, None], (P, NS, nsid)).ravel()
    # month-clustered t (SEL and CONF): with mean > 0, with - all, with - its coin-flip twin
    for per in ("SEL", "CONF"):
        sl = months_of(per)
        Wm = AM[:, :, 2, :, sl, :]
        ALLm = AM[:, :, :, :, sl, :].sum(axis=2)
        mu, t, M = cluster_t(Wm[..., 0], Wm[..., 1])
        out[f"{per}_tW"], out[f"{per}_MW"] = t.ravel(), M.ravel()
        mu, t, M = cluster_t(Wm[..., 0], Wm[..., 1], ALLm[..., 0], ALLm[..., 1])
        out[f"{per}_tEff"] = t.ravel()
        mu, t, M = cluster_t(Wm[..., 0], None, d_m=Wm[..., 1] - Wm[..., 2])
        out[f"{per}_tFlip"] = t.ravel()
        for ci, cn in ((0, "A"), (1, "N")):
            Cm = AM[:, :, ci, :, sl, :]
            mu, t, M = cluster_t(Cm[..., 0], Cm[..., 1])
            out[f"{per}_t{cn}"], out[f"{per}_M{cn}"] = t.ravel(), M.ravel()
            mu, t, M = cluster_t(Cm[..., 0], None, d_m=Cm[..., 1] - Cm[..., 2])
            out[f"{per}_tFlip{cn}"] = t.ravel()
        mu, t, M = cluster_t(ALLm[..., 0], ALLm[..., 1])
        out[f"{per}_tALL"], out[f"{per}_MALL"] = t.ravel(), M.ravel()
        # the same t with the TetherMax payback added to every trade (35 x 0.0756 % = +2.65 ROE points)
        pb = 35.0 * PAYBACK
        for ci, cn in ((2, "W"), (0, "A"), (1, "N"), (None, "ALL")):
            Cm = ALLm if ci is None else AM[:, :, ci, :, sl, :]
            mu, t, M = cluster_t(Cm[..., 0], Cm[..., 1] + pb * Cm[..., 0])
            out[f"{per}_t{cn}pb"] = t.ravel()
    D = pd.DataFrame(out)
    D["etf"] = [PAIRS[p][0] for p in D.pair]
    D["htf"] = [PAIRS[p][1] for p in D.pair]
    D["kind"] = [SRC[s][0] for s in D.src]
    D["source"] = [SRC[s][1] for s in D.src]
    D["name"] = N.name.reindex(D.sid).to_numpy()
    D["role"] = N.role.reindex(D.sid).to_numpy()
    # drop impossible cells (entry tf != pair's entry tf -> no rows) and sources that never have a side
    D = D[(D.SEL_nALL + D.CONF_nALL + D.FWD_nALL) > 0].reset_index(drop=True)
    return D


ENTRY_ROLES = ["range", "pullback", "breakout", "reversal", "timing", "other"]


def effects(D, per, min_n=MIN_N, roles=ENTRY_ROLES, by=("pair", "src")):
    """Per pair x source: across entry strategies (cells with n_with >= min_n): median of with - all, with - against,
    neutral - all, share improved, and the pooled numbers."""
    q = D[D.role.isin(roles)]
    q = q.assign(effW=q[f"{per}_mW"] - q[f"{per}_mALL"], effWA=q[f"{per}_mW"] - q[f"{per}_mA"],
                 effN=q[f"{per}_mN"] - q[f"{per}_mALL"], flipW=q[f"{per}_mW"] - q[f"{per}_mWo"])
    okW = q[f"{per}_nW"] >= min_n
    okA = okW & (q[f"{per}_nA"] >= min_n)
    okN = q[f"{per}_nN"] >= min_n
    g = []
    for key, z in q.groupby(list(by)):
        zW, zA, zN = z[okW.loc[z.index]], z[okA.loc[z.index]], z[okN.loc[z.index]]
        nW, nAll = z[f"{per}_nW"].sum(), z[f"{per}_nALL"].sum()
        sW = (z[f"{per}_mW"].fillna(0) * z[f"{per}_nW"]).sum()
        sAll = (z[f"{per}_mALL"].fillna(0) * z[f"{per}_nALL"]).sum()
        nA = z[f"{per}_nA"].sum()
        sA = (z[f"{per}_mA"].fillna(0) * z[f"{per}_nA"]).sum()
        g.append(dict(zip(by, key if isinstance(key, tuple) else (key,)), **{
            "cells": len(zW), "med_effW": zW.effW.median(), "share_up": (zW.effW > 0).mean() if len(zW) else np.nan,
            "med_effWA": zA.effWA.median(), "med_flipW": zW.flipW.median(), "cellsN": len(zN),
            "med_effN": zN.effN.median(), "keep": nW / max(nAll, 1), "pool_mW": sW / max(nW, 1),
            "pool_mALL": sAll / max(nAll, 1), "pool_mA": sA / max(nA, 1), "pool_nW": nW}))
    return pd.DataFrame(g)


def pooled_cluster(AM, D, roles=ENTRY_ROLES):
    """Month-clustered t of the POOLED effect (all entry signals of the roles together): with - all, per pair x src."""
    N = RD.names()
    sids = N.sid[N.role.isin(roles)].to_numpy()
    res = {}
    for per in ("SEL", "CONF"):
        sl = months_of(per)
        X = AM[:, :, :, sids][:, :, :, :, sl, :].sum(axis=3)       # [P, NS, 3, months, 3]
        W, ALL = X[:, :, 2], X.sum(axis=2)
        mu, t, M = cluster_t(W[..., 0], W[..., 1], ALL[..., 0], ALL[..., 1])
        res[f"{per}_pool_eff"], res[f"{per}_pool_t"] = mu, t
        mu2, t2, _ = cluster_t(W[..., 0], None, d_m=W[..., 1] - W[..., 2])
        res[f"{per}_pool_flip"], res[f"{per}_pool_tflip"] = mu2, t2
    return res


def main():
    meta, A, AM, B, B0, BARS = load()
    SRC = meta["src"]
    D = cell_table(meta, A, AM, B, BARS)
    log("cells", len(D))
    # sources that never take a side on a higher tf (undefined there) are dropped from the reads
    side_n = D.groupby(["pair", "src"]).apply(lambda z: (z.SEL_nW + z.SEL_nA + z.CONF_nW + z.CONF_nA).sum())
    dead = set(side_n[side_n == 0].index)
    D = D[[(p, s) not in dead for p, s in zip(D.pair, D.src)]].reset_index(drop=True)
    log("cells after dropping undefined sources", len(D), "dead pair x src", len(dead))

    # ---------------- 1. general effect of alignment per pair x source (median across entry strategies)
    E = effects(D, "SEL").merge(effects(D, "CONF"), on=["pair", "src"], suffixes=("_SEL", "_CONF"))
    E = E.merge(effects(D, "LATE"), on=["pair", "src"]).rename(columns=lambda c: c if c.endswith(("_SEL", "_CONF"))
                                                               or c in ("pair", "src") else c + "_LATE")
    E = E.merge(effects(D, "FWD", min_n=5), on=["pair", "src"]).rename(
        columns=lambda c: c if c.endswith(("_SEL", "_CONF", "_LATE")) or c in ("pair", "src") else c + "_FWD")
    PC = pooled_cluster(AM, D)
    for k, v in PC.items():
        E[k] = v[E.pair.to_numpy(), E.src.to_numpy()]
    E["etf"] = [PAIRS[p][0] for p in E.pair]
    E["htf"] = [PAIRS[p][1] for p in E.pair]
    E["kind"] = [SRC[s][0] for s in E.src]
    E["source"] = [SRC[s][1] for s in E.src]
    E["friend_map"] = [(a, b) in FRIEND_PAIRS for a, b in zip(E.etf, E.htf)]
    # trend-only baseline per pair x source and the drift baseline
    for per in ("SEL", "CONF", "LATE", "FWD"):
        Bp = per_sum(B, per, axis=2)
        with np.errstate(invalid="ignore", divide="ignore"):
            E[f"mT_{per}"] = (Bp[..., SI["w35"]] / Bp[..., SI["n"]])[E.pair, E.src]
            E[f"mTo_{per}"] = (Bp[..., SI["w35o"]] / Bp[..., SI["n"]])[E.pair, E.src]
            E[f"lsT_{per}"] = (Bp[..., SI["nlong"]] / Bp[..., SI["n"]])[E.pair, E.src]
    E["pass_bh_SEL"] = bh(pval(E.SEL_pool_t.to_numpy(), np.full(len(E), 36)))
    E["pass_bh_CONF"] = bh(pval(E.CONF_pool_t.to_numpy(), np.full(len(E), 33)))
    cols = ["etf", "htf", "kind", "source", "friend_map", "cells_SEL", "med_effW_SEL", "share_up_SEL", "med_effW_CONF",
            "share_up_CONF", "med_effW_LATE", "med_effW_FWD", "med_effWA_SEL", "med_effWA_CONF", "med_flipW_SEL",
            "med_flipW_CONF", "med_effN_SEL", "med_effN_CONF", "keep_SEL", "keep_CONF", "pool_mW_SEL", "pool_mALL_SEL",
            "pool_mW_CONF", "pool_mALL_CONF", "pool_mW_FWD", "pool_mALL_FWD", "SEL_pool_eff", "SEL_pool_t",
            "CONF_pool_eff", "CONF_pool_t", "SEL_pool_flip", "SEL_pool_tflip", "CONF_pool_flip", "CONF_pool_tflip",
            "pass_bh_SEL", "pass_bh_CONF", "mT_SEL", "mT_CONF", "mT_FWD", "lsT_SEL", "lsT_CONF", "lsT_FWD"]
    E[cols].sort_values("med_effW_SEL", ascending=False).to_csv(os.path.join(HERE, "general_effect.csv"),
                                                               index=False, float_format="%.5g")
    log("general_effect.csv", len(E))

    # ---------------- 2. by role (main judges and a few named sources), every pair
    main_src = [i for i, (k, s) in enumerate(SRC) if (k == "j" and s in ("DIR", "RAW3", "DIR_ADX20", "V4OF4", "TB22"))
                or (k == "c" and s in ("V39_ALL", "S6_EMA_DMI_ADX", "OBV_S", "N12_ICHI_AO", "T1_EMA50_200", "F4_FAN"))]
    R = []
    for per in ("SEL", "CONF", "LATE", "FWD"):
        e = effects(D[D.src.isin(main_src)], per, min_n=MIN_N if per != "FWD" else 5,
                    roles=ENTRY_ROLES + ["trend"], by=("pair", "src", "role"))
        e["per"] = per
        R.append(e)
    R = pd.concat(R)
    R["etf"] = [PAIRS[p][0] for p in R.pair]
    R["htf"] = [PAIRS[p][1] for p in R.pair]
    R["source"] = [f"{SRC[s][0]}:{SRC[s][1]}" for s in R.src]
    R.drop(columns=["pair", "src"]).to_csv(os.path.join(HERE, "role_effect.csv"), index=False, float_format="%.5g")

    # ---------------- 3. the cell table (with condition) for reading, and the selection
    D.to_pickle(os.path.join(SHM, "cells.pkl"))
    keep = ["etf", "htf", "kind", "source", "name", "role"] + [c for c in D.columns if c.startswith(("SEL_", "CONF_",
                                                                                                    "LATE_", "FWD_"))]
    W = D[D.SEL_nW >= MIN_N][keep]
    if os.environ.get("FY_DUMP") == "1":          # ~30 MB: off by default (the disk is nearly full)
        W.to_csv(os.path.join(SCR, "fiveyear_cells_with_sel.csv.gz"), index=False, float_format="%.4g")
    log("cells (SEL n_with >= 30)", len(W))


if __name__ == "__main__":
    main()
