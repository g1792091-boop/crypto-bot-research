"""Compare the study's cache (rebuilt with its own oscore.build_coin into /dev/shm/claude_verify_la) with the independent
rebuild (indep.py) element by element, then recompute the claim's numbers from the independent arrays only, plus a
look-ahead probe (higher bar still open at the signal) and a one-bar-lag probe.

    python3 compare.py      (writes compare.json, family_indep.csv)
"""
import os
import sys
import json

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import oscore as O  # noqa: E402

O.CACHE = "/dev/shm/claude_verify_la"
SH = "/dev/shm/claude_verify_la"
COINS = O.COINS
T0, MIN, DAY = O.T0, O.MIN, O.DAY
LEVX = O.LEVX
MAPS = O.MAPS
OBV_T = ("OBV20", "OBV30", "OBV50", "OBVSL10")
SR = {"SRSI_KD": "kd", "SRSI_X": "x"}
EXITS = O.EXITS
P = dict(O.P)
YEARS = {str(y): (O.ms(f"{y}-01-01") if y > 2020 else O.ms("2020-03-01"),
                  O.ms(f"{y + 1}-01-01") if y < 2026 else O.GRID_END) for y in range(2020, 2027)}

D = {c: O.load(c) for c in COINS}
I = {c: dict(np.load(os.path.join(SH, f"indep_{c}.npz"))) for c in COINS}

# ---------------------------------------------------------------- 1. element-by-element
cmp = {}
for c in COINS:
    Z, M = D[c], I[c]
    for tf in O.ENTRY_TFS:
        pre = f"{tf}_"
        n1, n2 = len(Z[pre + "e"]), len(M[pre + "e"])
        cmp[f"{c}_{tf}_len"] = [n1, n2]
        n = min(n1, n2)
        cmp[f"{c}_{tf}_e_equal"] = bool((Z[pre + "e"][:n] == M[pre + "e"][:n]).all())
        for tm, mk in SR.items():
            a, b = Z[pre + "sig_" + tm][:n], M[pre + mk][:n]
            cmp[f"{c}_{tf}_{tm}_agree"] = float((a == b).mean())
            cmp[f"{c}_{tf}_{tm}_nsig_study_mine"] = [int((a != 0).sum()), int((b != 0).sum())]
        for htf in O.HTF_OF[tf]:
            for T in OBV_T:
                a, b = Z[f"{pre}st_{htf}_{T}"][:n], M[f"{pre}{htf}_{T}"][:n]
                cmp[f"{c}_{tf}_{htf}_{T}_agree"] = float((a == b).mean())
                cmp[f"{c}_{tf}_{htf}_{T}_agree_LA"] = float((a == M[f"{pre}{htf}_{T}_LA"][:n]).mean())
        for X in EXITS:
            for lab in ("L", "S"):
                a, b = Z[f"{pre}{X}_{lab}_r"][:n], M[f"{pre}{X}_{lab}_r"][:n]
                both = np.isfinite(a) & np.isfinite(b)
                cmp[f"{c}_{tf}_{X}_{lab}_finite_study_mine_both"] = [int(np.isfinite(a).sum()), int(np.isfinite(b).sum()),
                                                                     int(both.sum())]
                cmp[f"{c}_{tf}_{X}_{lab}_r_close"] = float(np.isclose(a[both], b[both], atol=2e-6, rtol=0).mean())
                cmp[f"{c}_{tf}_{X}_{lab}_r_maxabs"] = float(np.abs(a[both] - b[both]).max()) if both.any() else 0.0
                wa, wb = Z[f"{pre}{X}_{lab}_w"][:n], M[f"{pre}{X}_{lab}_w"][:n]
                cmp[f"{c}_{tf}_{X}_{lab}_why_equal"] = float((wa[both] == wb[both]).mean())


def summary(name, ok_keys):
    v = [cmp[k] for k in cmp if k.endswith(ok_keys)]
    return {"n": len(v), "min": min(v), "mean": float(np.mean(v))}


agg = {k: summary(k, k) for k in ("_SRSI_KD_agree", "_SRSI_X_agree", "_r_close", "_why_equal")}
agg["htf_agree"] = summary("htf", "_agree")
agg["htf_agree_LA"] = {"min": min(v for k, v in cmp.items() if k.endswith("_agree_LA")),
                       "mean": float(np.mean([v for k, v in cmp.items() if k.endswith("_agree_LA")]))}
agg["r_maxabs"] = max(v for k, v in cmp.items() if k.endswith("_r_maxabs"))
agg["e_equal_all"] = all(v for k, v in cmp.items() if k.endswith("_e_equal"))
agg["len_equal_all"] = all(v[0] == v[1] for k, v in cmp.items() if k.endswith("_len"))
print(json.dumps(agg, indent=1))


# ---------------------------------------------------------------- 2. the claim's numbers from my arrays only
def rows(tf, htf, T, tm, X, per, mode="with", st_kind=""):
    """mode: with / against / trend_only / opp (coin-flip twin of 'with'). st_kind: '' closed bar, '_LA' look-ahead
    (bar still open), '_LAG' one more bar back."""
    a, b = per
    out_r, out_o, out_d = [], [], []
    lev = LEVX[X]
    for c in COINS:
        M = I[c]
        pre = f"{tf}_"
        e = M[pre + "e"]
        t = T0 + e * MIN
        mt = (t >= a) & (t < b)
        st = M[f"{pre}{htf}_{T}{st_kind}"]
        if mode == "trend_only":
            side = st
            m = mt & (st != 0)
        else:
            sig = M[pre + SR[tm]]
            side = sig
            m = mt & (sig != 0) & ((st == sig) if mode != "against" else (st == -sig))
        rL, rS = M[f"{pre}{X}_L_r"], M[f"{pre}{X}_S_r"]
        wL, wS = M[f"{pre}{X}_L_w"], M[f"{pre}{X}_S_w"]
        sd = side[m]
        r = np.where(sd > 0, rL[m], rS[m])
        ro = np.where(sd > 0, rS[m], rL[m])
        w = np.where(sd > 0, wL[m], wS[m])
        wo = np.where(sd > 0, wS[m], wL[m])
        keep = np.isfinite(r) & np.isfinite(ro) & (w != 3) & (wo != 3)
        out_r.append(lev * r[keep].astype(float))
        out_o.append(lev * ro[keep].astype(float))
        out_d.append((t[m][keep] // DAY))
    return np.concatenate(out_r), np.concatenate(out_o), np.concatenate(out_d)


res = {}
lit = {"L1": ("30m", "1h", "OBV30", "SRSI_KD", "w35"), "L2": ("1h", "4h", "OBV30", "SRSI_KD", "w35")}
for lab, (tf, htf, T, tm, X) in lit.items():
    for pn, per in list(P.items()) + list(YEARS.items()):
        r, o, _ = rows(tf, htf, T, tm, X, per)
        ra, _, _ = rows(tf, htf, T, tm, X, per, "against")
        rt, _, _ = rows(tf, htf, T, tm, X, per, "trend_only")
        res[f"{lab}_{pn}"] = {"n": len(r), "mean": float(r.mean()) if len(r) else None,
                              "opp": float(o.mean()) if len(o) else None,
                              "against": float(ra.mean()) if len(ra) else None,
                              "trend_only": float(rt.mean()) if len(rt) else None,
                              "win": float((r > 0).mean()) if len(r) else None}
    for kind in ("_LA", "_LAG"):
        r, _, _ = rows(tf, htf, T, tm, X, P["FIVE"], st_kind=kind)
        ra, _, _ = rows(tf, htf, T, tm, X, P["FIVE"], "against", st_kind=kind)
        res[f"{lab}_FIVE{kind}"] = {"n": len(r), "mean": float(r.mean()), "against": float(ra.mean())}
print(pd.DataFrame(res).T.round(4).to_string())

fam = []
for (tf, htf) in MAPS:
    for T in OBV_T:
        for tm in SR:
            for X in EXITS:
                for pn in ("SEL", "CONF", "FIVE", "FWD", "PRE", "YTD"):
                    for kind in ("", "_LA", "_LAG"):
                        if kind and pn not in ("FIVE", "CONF", "FWD"):
                            continue
                        r, o, _ = rows(tf, htf, T, tm, X, P[pn], st_kind=kind)
                        ra, _, _ = rows(tf, htf, T, tm, X, P[pn], "against", st_kind=kind)
                        rt, _, _ = rows(tf, htf, T, tm, X, P[pn], "trend_only", st_kind=kind)
                        fam.append({"tf": tf, "htf": htf, "trend": T, "timing": tm, "exit": X, "period": pn,
                                    "kind": kind or "closed", "n": len(r), "mean_roe": r.mean(), "mean_opp": o.mean(),
                                    "n_against": len(ra), "mean_against": ra.mean(), "trend_only": rt.mean()})
F = pd.DataFrame(fam)
F.to_csv(os.path.join(HERE, "family_indep.csv"), index=False, float_format="%.6g")
F["d"] = F.mean_roe - F.mean_against
F["tim"] = F.mean_roe - F.trend_only
g = F.groupby(["kind", "period"]).agg(cells=("d", "size"), with_minus_against=("d", "mean"),
                                       share_pos=("d", lambda x: float((x > 0).mean())), fam_mean=("mean_roe", "mean"),
                                       opp=("mean_opp", "mean"), trend_only=("trend_only", "mean"),
                                       timing_minus_trend_only=("tim", "mean"))
print(g.round(4).to_string())
# compare with the study's all_cells (family A rows)
A = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(HERE)), "all_cells.csv.gz"))
A = A[A.trend.isin(OBV_T) & A.timing.isin(list(SR))]
Fm = F[F.kind == "closed"].merge(A, on=["tf", "htf", "trend", "timing", "exit", "period"], suffixes=("_mine", "_study"))
dd = {"cells_matched": len(Fm), "n_equal_share": float((Fm.n_mine == Fm.n_study).mean()),
      "max_abs_mean_diff": float((Fm.mean_roe_mine - Fm.mean_roe_study).abs().max()),
      "max_abs_against_diff": float((Fm.mean_against_mine - Fm.mean_against_study).abs().max()),
      "max_abs_trend_only_diff": float((Fm.trend_only_mine - Fm.trend_only_study).abs().max())}
print(json.dumps(dd, indent=1))
json.dump({"elementwise": agg, "elementwise_detail": cmp, "literal": res, "family_vs_study": dd,
           "family_summary": g.reset_index().to_dict(orient="records")},
          open(os.path.join(HERE, "compare.json"), "w"), indent=1, default=float)
