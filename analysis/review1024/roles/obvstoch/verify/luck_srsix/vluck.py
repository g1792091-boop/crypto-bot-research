"""Verifier (luck / multiple testing) for the claim about OBV30@4h>SRSI_X@1h|a2, the friend family's best cell of the
last 19 days. Uses my own rebuild of the study cache (/dev/shm/claude_verify_srsix, built by vbuild.py with the study's
build_coin) and recomputes, independently of the study's CSVs:
  A. last-19-day ranking of the 160 family cells and all 1,080 cells (n, mean ROE, payback mean)
  B. per-cell p-values (day-clustered t) -> BH over 160 and over the 1,080 (n >= 30)
  C. day-block bootstrap max-t (Romano-Wolf style, recentred) over the 160 and the 1,080
  D. coin-flip null for the MAX: random absolute side per (coin, tf, entry bar) shared by every cell holding that bar,
     and a coarser version per (coin, UTC day); statistic = best family / best overall mean (n >= 30)
  E. side-mix decomposition of the cell: what the same long/short mix with random choice of which signal goes long
     would give (market-direction luck vs selection)
Writes vluck.json. Run from this folder: python3 vluck.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O  # noqa: E402
from oscore import *  # noqa: E402,F401,F403

O.CACHE = "/dev/shm/claude_verify_srsix"
HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = "OBV30@4h>SRSI_X@1h|a2"
rng = np.random.default_rng(777)


def fam(c):
    return c[2] in O.OBV_TRENDS and c[3] in O.SRSI


def clt(x, day):
    n, m, se, t = O.cl_stats(x, day)
    return n, m, se, t


if __name__ == "__main__":
    from scipy.stats import norm
    D = O.load_all()
    CELLS = O.cells()
    ids = [O.cell_id(*c) for c in CELLS]
    isA = np.array([fam(c) for c in CELLS])
    TFI = {"15m": 0, "30m": 1, "1h": 2}
    R = {}
    for c, cid in zip(CELLS, ids):
        R[cid] = O.rows(D, *c, "FWD")
    out = {}
    # ---------------- A. ranking
    tab = []
    for c, cid in zip(CELLS, ids):
        r = R[cid]
        n, m, se, t = clt(r["roe"], r["day"])
        tab.append({"cell": cid, "famA": fam(c), "n": n, "mean": m, "se": se, "t": t,
                    "p": float(norm.sf(t)) if np.isfinite(t) else np.nan, "opp": float(r["opp"].mean()) if n else np.nan,
                    "pb": m + PAYBACK * O.LEVX[c[4]] if n else np.nan,
                    "long_share": float((r["side"] > 0).mean()) if n else np.nan})
    T = pd.DataFrame(tab)
    TA = T[T.famA].sort_values("mean", ascending=False)
    out["A_top5_family"] = TA.head(5)[["cell", "n", "mean", "t", "p", "opp", "pb", "long_share"]].round(5).to_dict("records")
    out["A_target_rank_in_family"] = int(list(TA.cell).index(TARGET) + 1)
    T30 = T[T.n >= 30].sort_values("mean", ascending=False)
    out["A_target_rank_all_n30"] = int(list(T30.cell).index(TARGET) + 1)
    out["A_top3_all_n30"] = T30.head(3)[["cell", "n", "mean", "t", "p"]].round(5).to_dict("records")
    out["A_family_cells_pos"] = int((TA["mean"] > 0).sum())
    out["A_all_n30_pos"] = int((T30["mean"] > 0).sum())
    out["A_all_n30_cells"] = int(len(T30))
    # ---------------- B. BH
    pa = TA.p.to_numpy()
    qa = O.bh(pa)
    out["B_family_min_p"] = float(np.nanmin(pa))
    out["B_family_min_q"] = float(np.nanmin(qa))
    out["B_family_target_q"] = float(qa[list(TA.cell).index(TARGET)])
    out["B_family_bonferroni_target"] = float(min(1, pa[list(TA.cell).index(TARGET)] * len(pa)))
    q30 = O.bh(T30.p.to_numpy())
    out["B_all_n30_min_q"] = float(np.nanmin(q30))
    out["B_all_n30_target_q"] = float(q30[list(T30.cell).index(TARGET)])
    out["B_all_n30_count_q_le_0.10"] = int((q30 <= 0.10).sum())
    # ---------------- C. day-block bootstrap max-t (recentred), family and all n>=30
    days = np.unique(np.concatenate([R[c]["day"] for c in ids]))
    di_of = {d: i for i, d in enumerate(days)}
    nd = len(days)
    sel_all = [c for c in T30.cell]
    sel_A = list(TA[TA.n >= 30].cell)
    S = np.zeros((len(sel_all), nd))
    Q = np.zeros((len(sel_all), nd))
    N = np.zeros((len(sel_all), nd))
    for i, cid in enumerate(sel_all):
        r = R[cid]
        di = np.array([di_of[d] for d in r["day"]])
        S[i] = np.bincount(di, weights=r["roe"], minlength=nd)
        N[i] = np.bincount(di, minlength=nd)
    mean0 = S.sum(1) / N.sum(1)
    tobs = T30.set_index("cell").loc[sel_all, "t"].to_numpy()
    idxA = np.array([sel_all.index(c) for c in sel_A])
    B = 4000
    mx_all, mx_A, mx_mean_A = np.empty(B), np.empty(B), np.empty(B)
    for b in range(B):
        w = np.bincount(rng.integers(0, nd, nd), minlength=nd).astype(float)
        Sb = S @ w
        Nb = N @ w
        with np.errstate(invalid="ignore", divide="ignore"):
            mb = Sb / Nb
            # cluster SE of the resampled mean around its own mean
            dev = (S - mb[:, None] * N)                     # per-day deviation sums
            G = (w > 0).sum()
            se = np.sqrt(((dev ** 2) @ w) * G / max(G - 1, 1)) / Nb
            tb = (mb - mean0) / se
        mx_all[b] = np.nanmax(tb)
        mx_A[b] = np.nanmax(tb[idxA])
        mx_mean_A[b] = np.nanmax((mb - mean0)[idxA])
    t_target = float(T.set_index("cell").loc[TARGET, "t"])
    out["C_target_t"] = t_target
    out["C_maxt_family_p"] = float(np.mean(mx_A >= t_target))
    out["C_maxt_all_p"] = float(np.mean(mx_all >= t_target))
    out["C_maxt_family_95"] = float(np.quantile(mx_A, 0.95))
    out["C_maxt_all_95"] = float(np.quantile(mx_all, 0.95))
    # ---------------- D. coin-flip null for the best cell
    # rows -> keys
    keyR, keyD = {}, {}
    for c, cid in zip(CELLS, ids):
        r = R[cid]
        keyR[cid] = (r["coin"].astype(np.int64) * 3 + TFI[c[0]]) * 10**9 + r["e"].astype(np.int64)
        keyD[cid] = r["coin"].astype(np.int64) * 10**6 + r["day"].astype(np.int64)
    allk = np.unique(np.concatenate([keyR[c] for c in ids]))
    allkd = np.unique(np.concatenate([keyD[c] for c in ids]))
    pos = {c: np.searchsorted(allk, keyR[c]) for c in ids}
    posd = {c: np.searchsorted(allkd, keyD[c]) for c in ids}
    obs_A = float(TA[TA.n >= 30]["mean"].max())
    obs_all = float(T30["mean"].max())
    obs_target = float(T.set_index("cell").loc[TARGET, "mean"])
    BB = 4000
    setA = set(sel_A)
    cidx = np.concatenate([np.full(len(R[c]["roe"]), i) for i, c in enumerate(sel_all)])
    sideC = np.concatenate([R[c]["side"] for c in sel_all]).astype(np.int64)
    roeC = np.concatenate([R[c]["roe"] for c in sel_all])
    oppC = np.concatenate([R[c]["opp"] for c in sel_all])
    nC = np.bincount(cidx, minlength=len(sel_all)).astype(float)
    iT = sel_all.index(TARGET)
    for lab, P_, K in (("per_bar", pos, len(allk)), ("per_coin_day", posd, len(allkd))):
        PC = np.concatenate([P_[c] for c in sel_all])
        mA, mAll, mT = np.empty(BB), np.empty(BB), np.empty(BB)
        for b in range(BB):
            side = rng.integers(0, 2, K) * 2 - 1
            v = np.where(side[PC] == sideC, roeC, oppC)
            cm = np.bincount(cidx, weights=v, minlength=len(sel_all)) / nC
            mA[b], mAll[b], mT[b] = cm[idxA].max(), cm.max(), cm[iT]
        out[f"D_{lab}_p_family_best_ge_obs"] = float(np.mean(mA >= obs_A))
        out[f"D_{lab}_p_all_best_ge_obs"] = float(np.mean(mAll >= obs_all))
        out[f"D_{lab}_p_target_ge_obs"] = float(np.mean(mT >= obs_target))
        out[f"D_{lab}_family_best_median"] = float(np.median(mA))
        out[f"D_{lab}_family_best_95"] = float(np.quantile(mA, 0.95))
        out[f"D_{lab}_all_best_median"] = float(np.median(mAll))
        out[f"D_{lab}_all_best_95"] = float(np.quantile(mAll, 0.95))
        out[f"D_{lab}_target_mean_null"] = float(np.mean(mT))
    out["D_obs_family_best"] = obs_A
    out["D_obs_all_best_n30"] = obs_all
    # ---------------- E. side mix of the target
    r = R[TARGET]
    L = np.where(r["side"] > 0, r["roe"], r["opp"])
    Sx = np.where(r["side"] < 0, r["roe"], r["opp"])
    pL = float((r["side"] > 0).mean())
    out["E_target_long_share"] = pL
    out["E_target_all_long_mean"] = float(L.mean())
    out["E_target_all_short_mean"] = float(Sx.mean())
    out["E_same_mix_random_pick"] = float(pL * L.mean() + (1 - pL) * Sx.mean())
    out["E_actual"] = float(r["roe"].mean())
    out["E_coinflip_50_50"] = float(0.5 * L.mean() + 0.5 * Sx.mean())
    out["E_actual_long_mean"] = float(r["roe"][r["side"] > 0].mean())
    out["E_actual_short_mean"] = float(r["roe"][r["side"] < 0].mean())
    out["E_n_long"] = int((r["side"] > 0).sum())
    out["E_n_short"] = int((r["side"] < 0).sum())
    out["E_days_with"] = int(len(np.unique(r["day"])))
    # day concentration
    dd = pd.Series(r["roe"]).groupby(r["day"]).sum().sort_values(ascending=False)
    out["E_top_day_sum_share_of_total"] = float(dd.iloc[0] / r["roe"].sum())
    out["E_mean_without_best_day"] = float((r["roe"].sum() - dd.iloc[0]) / (len(r["roe"]) - int((r["day"] == dd.index[0]).sum())))
    out["E_mean_without_best2_days"] = float((r["roe"].sum() - dd.iloc[:2].sum()) / (len(r["roe"]) - int(np.isin(r["day"], dd.index[:2]).sum())))
    json.dump(out, open(os.path.join(HERE, "vluck.json"), "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))
