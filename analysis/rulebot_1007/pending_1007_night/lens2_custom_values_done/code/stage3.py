"""Stage 3: OOS evaluation, day-cluster bootstrap, gates, persistence, time-to-confirm. Writes ../out/*.csv, *.json."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvlib as C  # noqa: E402
import stage2 as S2  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

METRIC = os.environ.get("CV_METRIC", "R")
WF = os.path.join(C.WORK, "work", "wf" if METRIC == "R" else "wf_" + METRIC)
OUT = os.path.join(C.WORK, "out" if METRIC == "R" else "out_" + METRIC)
B = 1000
SEED = 20261007
DEF = S2.DEFAULT
NWO = S2.NWEEK - S2.T0
SPLIT_DAY = int((S2.SPLIT_AB - (S2.WEEK0 + S2.T0 * S2.NS_WEEK)) // S2.NS_DAY)
DIMS = {"P": [S2.combo(p, 0, 1, 0) for p in range(1, 5)], "F": [S2.combo(0, f, 1, 0) for f in range(1, 5)],
        "S": [S2.combo(0, 0, 0, 0), S2.combo(0, 0, 2, 0)], "X": [S2.combo(0, 0, 1, 1), S2.combo(0, 0, 1, 2)]}
LEVEL_NAME = {}
for i, c in enumerate(DIMS["P"]):
    LEVEL_NAME[c] = f"P{i + 1}"
for i, c in enumerate(DIMS["F"]):
    LEVEL_NAME[c] = f"F_{C.FILTERS[i + 1]}"
LEVEL_NAME[DIMS["S"][0]], LEVEL_NAME[DIMS["S"][1]] = "stop1.5", "stop2.5"
LEVEL_NAME[DIMS["X"][0]], LEVEL_NAME[DIMS["X"][1]] = "exit_rladder", "exit_tp1.5R_be1R"


def decode(c):
    x = c % 3
    s = (c // 3) % 3
    pf = c // 9
    return f"P{pf // 5}|{C.FILTERS[pf % 5]}|stop{C.STOPS[s]}|{C.EXITS[x]}"


def r(x, d=4):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


def bh(p, q=0.10):
    p = np.asarray(p, float)
    m = len(p)
    o = np.argsort(p)
    thr = q * np.arange(1, m + 1) / m
    ok = p[o] <= thr
    k = np.flatnonzero(ok).max() + 1 if ok.any() else 0
    out = np.zeros(m, bool)
    out[o[:k]] = True
    return out


def main():
    C.check_prereg()
    os.makedirs(OUT, exist_ok=True)
    cells = [f"{s}_{tf}" for s in C.STRATS for tf in C.TFS]
    Z = {c: np.load(os.path.join(WF, c + ".npz")) for c in cells}
    keys = list(Z[cells[0]]["sel_keys"])
    nday = Z[cells[0]]["Dn"].shape[0]
    wk = np.arange(nday) // 7
    rng = np.random.default_rng(SEED)
    Wt = np.stack([np.bincount(rng.integers(0, nday, nday), minlength=nday) for _ in range(B)]).astype(np.float64)
    halfA = np.arange(nday) < SPLIT_DAY
    # default streams per cell
    dd = {}
    for c in cells:
        z = Z[c]
        dd[c] = dict(n=z["Dn"][:, DEF].astype(float), S=z["DS"][:, DEF].astype(float), P=z["DP"][:, DEF].astype(float),
                     G=z["DG"][:, DEF].astype(float), Q=z["DQ"][:, DEF].astype(float))
    rows, cell_rows = [], []
    ar = np.arange(nday)
    for key in keys:
        scheme, meth = key.split("|")
        step = int(scheme.split("_")[0][1:])
        per_cell = {}
        Mn, MS, MDn, MDS, SW = (np.zeros((nday, len(cells))) for _ in range(5))
        MP, MDP, MG, MDG = (np.zeros((nday, len(cells))) for _ in range(4))
        noise_steps = switched_steps = 0
        for j, c in enumerate(cells):
            z = Z[c]
            sel = z["sel"][keys.index(key)].astype(int)
            cd = sel[wk]
            Mn[:, j] = z["Dn"][ar, cd]
            MS[:, j] = z["DS"][ar, cd]
            MP[:, j] = z["DP"][ar, cd]
            MG[:, j] = z["DG"][ar, cd]
            MDn[:, j], MDS[:, j], MDP[:, j], MDG[:, j] = dd[c]["n"], dd[c]["S"], dd[c]["P"], dd[c]["G"]
            SW[:, j] = cd != DEF
            # noise rate per decision block
            Wn, WS = z["Wn"], z["WS"]
            for k in range(0, NWO, step):
                blk = slice(k, min(k + step, NWO))
                cc = sel[k]
                if cc == DEF:
                    continue
                ns_, nd_ = Wn[blk, cc].sum(), Wn[blk, DEF].sum()
                if ns_ < 1 or nd_ < 1:
                    continue
                switched_steps += 1
                if WS[blk, cc].sum() / ns_ <= WS[blk, DEF].sum() / nd_:
                    noise_steps += 1
        # pooled point estimates
        def diff(n1, s1, n0, s0):
            return s1.sum() / max(n1.sum(), 1e-12) - s0.sum() / max(n0.sum(), 1e-12)
        d_all = diff(Mn, MS, MDn, MDS)
        d_A = diff(Mn[halfA], MS[halfA], MDn[halfA], MDS[halfA])
        d_B = diff(Mn[~halfA], MS[~halfA], MDn[~halfA], MDS[~halfA])
        d_pct = diff(Mn, MP, MDn, MDP)
        d_gross = diff(Mn, MG, MDn, MDG)
        # bootstrap (days jointly across cells)
        bn, bS, bdn, bdS = Wt @ Mn, Wt @ MS, Wt @ MDn, Wt @ MDS        # B x cells
        with np.errstate(invalid="ignore", divide="ignore"):
            cell_d = bS / bn - bdS / bdn
            pooled_b = bS.sum(1) / bn.sum(1) - bdS.sum(1) / bdn.sum(1)
            eq_b = np.nanmean(cell_d, axis=1)
            cell_pt = MS.sum(0) / Mn.sum(0) - MDS.sum(0) / MDn.sum(0)
        p_cell = np.nanmean(cell_d <= 0, axis=0)
        sig = bh(np.nan_to_num(p_cell, nan=1.0))
        # switched-only (gates)
        sw = SW.astype(bool)
        n_sw_sel, n_sw_def = (Mn * sw).sum(), (MDn * sw).sum()
        if n_sw_sel > 0 and n_sw_def > 0:
            d_sw = (MS * sw).sum() / n_sw_sel - (MDS * sw).sum() / n_sw_def
            bsw = (Wt @ (MS * sw)).sum(1) / (Wt @ (Mn * sw)).sum(1) - (Wt @ (MDS * sw)).sum(1) / (Wt @ (MDn * sw)).sum(1)
            ci_sw = np.nanpercentile(bsw, [2.5, 97.5])
            gained = d_sw * n_sw_sel
        else:
            d_sw, ci_sw, gained = np.nan, [np.nan, np.nan], 0.0
        tr = None
        if meth == "naive":
            ti = [list(Z[c]["trimp_keys"]).index(scheme) for c in cells]
            allt = np.concatenate([Z[c]["trimp"][i] for c, i in zip(cells, ti)])
            tr = float(np.nanmean(allt))
        row = dict(scheme=scheme, step_weeks=step, window_weeks=int(scheme.split("_w")[1]), method=meth,
                   pooled_delta_R=r(d_all), ci_lo=r(np.nanpercentile(pooled_b, 2.5)), ci_hi=r(np.nanpercentile(pooled_b, 97.5)),
                   p_le0=r(float(np.mean(pooled_b <= 0))), delta_halfA=r(d_A), delta_halfB=r(d_B),
                   cells_positive=int(np.sum(cell_pt > 0)), cells_bh_sig=int(sig.sum()),
                   eqw_cell_delta=r(float(np.nanmean(cell_pt))), eqw_ci_lo=r(np.nanpercentile(eq_b, 2.5)),
                   eqw_ci_hi=r(np.nanpercentile(eq_b, 97.5)),
                   trades_sel=int(Mn.sum()), trades_def=int(MDn.sum()), trade_ratio=r(Mn.sum() / MDn.sum()),
                   delta_netpct_per_trade=r(d_pct * 100, 5), delta_gross_R=r(d_gross),
                   switch_share_cellweeks=r(float(SW.mean() / 1.0)), switched_steps=switched_steps,
                   noise_rate=r(noise_steps / switched_steps if switched_steps else np.nan),
                   delta_R_when_switched=r(d_sw), sw_ci_lo=r(ci_sw[0]), sw_ci_hi=r(ci_sw[1]),
                   total_R_gained_when_switched=r(gained, 1), mean_train_improvement_of_pick=r(tr))
        # pre-registered verdicts
        row["beats_default"] = bool(row["ci_lo"] is not None and row["ci_lo"] > 0 and d_A > 0 and d_B > 0
                                    and row["cells_positive"] >= 0.6 * len(cells))
        row["gate_keeps_real"] = bool(meth.startswith("gate") and np.isfinite(d_sw) and d_sw > 0
                                      and ci_sw[0] > 0 and SW.mean() >= 0.05)
        rows.append(row)
        if meth in ("naive", "naive_P", "naive_F", "naive_S", "naive_X") or key.endswith("gate_100_0.15_2.0") \
                or key.endswith("gate_30_0.05_0.0"):
            for j, c in enumerate(cells):
                cell_rows.append(dict(cell=c, scheme=scheme, method=meth, delta_R=r(cell_pt[j]),
                                      p_le0=r(p_cell[j]), bh10=bool(sig[j]),
                                      switch_share=r(float(SW[:, j].mean()))))
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "wf_methods.csv"), index=False)
    pd.DataFrame(cell_rows).to_csv(os.path.join(OUT, "wf_cells.csv"), index=False)

    # ---------------- per-cell descriptives, random benchmark, oracle, persistence, time to confirm
    desc, pers, lev_rows = [], [], []
    for c in cells:
        z = Z[c]
        n = z["Dn"].sum(0).astype(float)
        S = z["DS"].sum(0).astype(float)
        Q = z["DQ"].sum(0).astype(float)
        P = z["DP"].sum(0).astype(float)
        G = z["DG"].sum(0).astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            m = S / n
        md = m[DEF]
        sd = np.sqrt(Q[DEF] / n[DEF] - md * md)
        dn_, dS_ = z["Dn"][:, DEF].astype(float), z["DS"][:, DEF].astype(float)
        var_cl = np.sum((dS_ - md * dn_) ** 2) / n[DEF] ** 2
        deff = var_cl / (sd * sd / n[DEF])
        tpw = n[DEF] / NWO
        ok = n >= 30
        rand = float(np.nanmean(np.where(ok, m, np.nan)) - md)
        orc = int(np.nanargmax(np.where(ok, m, -np.inf)))
        conf = {}
        for dlt in (0.05, 0.10, 0.20):
            need = ((1.645 + 0.842) * sd / dlt) ** 2 * deff
            conf[f"trades_needed_{dlt}"] = int(need)
            conf[f"weeks_needed_{dlt}"] = r(need / tpw, 1)
        desc.append(dict(cell=c, strategy=c.rsplit("_", 1)[0], tf=c.rsplit("_", 1)[1], default_n=int(n[DEF]),
                         default_mean_R=r(md), default_gross_R=r(G[DEF] / n[DEF]), default_cost_R=r((G[DEF] - S[DEF]) / n[DEF]),
                         default_netpct=r(P[DEF] / n[DEF] * 100, 5), sd_R=r(sd), deff=r(deff, 2), trades_per_week=r(tpw, 1),
                         random_combo_delta=r(rand), oracle_combo=decode(orc), oracle_delta=r(m[orc] - md),
                         combos_mean_positive=int(np.sum(ok & (m > 0))), best_combo_mean=r(m[orc]), **conf))
        # persistence halves A/B
        abn, abS, abP = z["abn"].astype(float), z["abS"].astype(float), z["abP"].astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            mA, mB = abS[0] / abn[0], abS[1] / abn[1]
            pA, pB = abP[0] / abn[0], abP[1] / abn[1]
        okc = (abn[0] >= 30) & (abn[1] >= 30)
        dA, dB = mA - mA[DEF], mB - mB[DEF]
        ii = np.flatnonzero(okc & (np.arange(225) != DEF))
        rho = pd.Series(dA[ii]).rank().corr(pd.Series(dB[ii]).rank()) if len(ii) > 5 else np.nan
        top = ii[np.argsort(-dA[ii])[:10]]
        pers.append(dict(cell=c, combos=len(ii), spearman_dA_dB=r(rho), top10A_mean_dA=r(np.mean(dA[top])),
                         top10A_mean_dB=r(np.mean(dB[top])), share_combos_dA_pos=r(np.mean(dA[ii] > 0)),
                         share_combos_dB_pos=r(np.mean(dB[ii] > 0)),
                         default_A=r(mA[DEF]), default_B=r(mB[DEF])))
        for dim, cs in DIMS.items():
            for cc in cs:
                lev_rows.append(dict(cell=c, dim=dim, level=LEVEL_NAME[cc], nA=int(abn[0][cc]), nB=int(abn[1][cc]),
                                     dA=r(dA[cc]), dB=r(dB[cc]), dpctA=r((pA[cc] - pA[DEF]) * 100, 5),
                                     dpctB=r((pB[cc] - pB[DEF]) * 100, 5)))
    pd.DataFrame(desc).to_csv(os.path.join(OUT, "cell_desc.csv"), index=False)
    pd.DataFrame(pers).to_csv(os.path.join(OUT, "persistence.csv"), index=False)
    lv = pd.DataFrame(lev_rows)
    lv.to_csv(os.path.join(OUT, "levels_AB.csv"), index=False)
    # level summary across cells
    ls = []
    for (dim, level), g in lv.groupby(["dim", "level"]):
        g = g[(g.nA >= 30) & (g.nB >= 30)]
        ls.append(dict(dim=dim, level=level, cells=len(g), mean_dA=r(g.dA.mean()), mean_dB=r(g.dB.mean()),
                       cells_dA_pos=int((g.dA > 0).sum()), cells_dB_pos=int((g.dB > 0).sum()),
                       cells_same_sign=int((np.sign(g.dA) == np.sign(g.dB)).sum()),
                       cells_pos_both=int(((g.dA > 0) & (g.dB > 0)).sum()),
                       mean_dpctA=r(g.dpctA.mean(), 5), mean_dpctB=r(g.dpctB.mean(), 5)))
    pd.DataFrame(ls).to_csv(os.path.join(OUT, "levels_summary.csv"), index=False)
    print(res[res.method == "naive"][["scheme", "pooled_delta_R", "ci_lo", "ci_hi", "delta_halfA", "delta_halfB",
                                      "cells_positive", "noise_rate", "mean_train_improvement_of_pick"]].to_string())


if __name__ == "__main__":
    main()
