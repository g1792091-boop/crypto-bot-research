"""Luck / multiple-testing verifier, step 2 (cell level), on the rebuilt cell table (/dev/shm/claude_verify_lm/cells.pkl).

1. Re-run select_cells' family + BH + shortlist rule for the with-condition (no file of the study is written) and compare
   the 20 with-cells with the study's shortlist.csv (membership + SELECT / CONFIRM numbers).
2. BH re-check on the whole family (W, A, N, ALL) with and without the payback.
3. Selection premium vs chance: the CONFIRM cell-average of the 20 picked with-cells against 20 cells drawn at random
   (a) from every eligible with-cell, (b) from eligible with-cells with SELECT mean > 0, (c) from (b) matched to the
   picked cells' (entry tf, trend tf) mix; one cell per (strategy, entry tf), as the rule does. 20,000 draws each.
4. Does SELECT t predict CONFIRM at all? Spearman of SELECT t vs CONFIRM mean over eligible with-cells, and the
   CONFIRM mean by SELECT-t decile.

    python3 lm_select.py    -> lm_select.txt (printed), lm_select_null.csv"""
import os
import sys

FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
MY = "/dev/shm/claude_verify_lm"
sys.path.insert(0, FY)
import fy_common                         # noqa: E402
fy_common.SHM = MY
from fy_analyze import bh, pval, SEL_MIN   # noqa: E402
from fy_common import *                  # noqa: E402,F401
from scipy import stats as sst           # noqa: E402

OUTD = os.path.dirname(os.path.abspath(__file__))
PB = 35.0 * PAYBACK


def family(D, tp=""):
    rows = []
    for cn in ("W", "A", "N"):
        q = D[(D[f"SEL_n{cn}"] >= SEL_MIN) & (D[f"SEL_M{cn}"] >= 12)]
        if cn == "N":
            q = q[q.kind != "l"]
        rows.append(pd.DataFrame({"cond": cn, "idx": q.index, "t": q[f"SEL_t{cn}{tp}"].to_numpy(),
                                  "M": q[f"SEL_M{cn}"].to_numpy(), "m": q[f"SEL_m{cn}"].to_numpy()
                                  + (PB if tp else 0.0)}))
    U = D[(D.htf == "1d")].drop_duplicates(["sid", "etf"])
    U = U[(U.SEL_nALL >= SEL_MIN) & (U.SEL_MALL >= 12)]
    rows.append(pd.DataFrame({"cond": "ALL", "idx": U.index, "t": U[f"SEL_tALL{tp}"].to_numpy(),
                              "M": U.SEL_MALL.to_numpy(), "m": U.SEL_mALL.to_numpy() + (PB if tp else 0.0)}))
    F = pd.concat(rows, ignore_index=True)
    F["p"] = pval(F.t.to_numpy(), F.M.to_numpy())
    F["bh"] = bh(F.p.to_numpy())
    return F


def main():
    D = pd.read_pickle(os.path.join(MY, "cells.pkl"))
    out = []

    def say(*a):
        s = " ".join(str(x) for x in a)
        print(s)
        out.append(s)

    for tp in ("", "pb"):
        F = family(D, tp)
        g = F.groupby("cond").agg(cells=("t", "size"), pos=("m", lambda x: int((x > 0).sum())),
                                  t2=("t", lambda x: int((x > 2).sum())), t3=("t", lambda x: int((x > 3).sum())),
                                  bh=("bh", "sum"), tmax=("t", "max"), pmin=("p", "min"))
        say(f"--- family {'with payback' if tp else 'raw'}: total {len(F)}, BH pass {int(F.bh.sum())}")
        say(g.to_string())
        # the smallest p needed for one BH pass
        say("BH threshold for rank 1:", 0.10 / len(F), " smallest p:", F.p.min())

    # ---- the study's shortlist (with) vs our re-run
    F = family(D, "")
    F = F.join(D[["name", "etf", "htf", "kind", "source", "role"]], on="idx")
    z = F[(F.cond == "W") & (F.m > 0)].sort_values("t", ascending=False).drop_duplicates(["name", "etf"]).head(20)
    SL = pd.read_csv(os.path.join(FY, "shortlist.csv"))
    SW = SL[SL.cond == "W"].reset_index(drop=True)
    mine = [(r["name"], r.etf, r.htf, f"{r.kind}:{r.source}") for _, r in z.iterrows()]
    theirs = [(r["name"], r.etf, r.htf, r.source) for _, r in SW.iterrows()]
    say("--- shortlist W membership identical (same order):", mine == theirs, " same set:", set(mine) == set(theirs))
    Dz = D.loc[z.idx]
    cmp = pd.DataFrame({"cell": [f"{a}@{b}|{d}@{c}" for a, b, c, d in mine], "SEL_t_mine": Dz.SEL_tW.to_numpy(),
                        "SEL_t_study": SW.SEL_t.to_numpy(), "CONF_m_mine": Dz.CONF_mW.to_numpy(),
                        "CONF_m_study": SW.CONF_m.to_numpy(), "CONF_n": Dz.CONF_nW.to_numpy(),
                        "CONF_mALL": Dz.CONF_mALL.to_numpy(), "CONF_t": Dz.CONF_tW.to_numpy(),
                        "CONF_tFlip": Dz.CONF_tFlip.to_numpy(), "CONF_mWo": Dz.CONF_mWo.to_numpy()})
    say(cmp.round(4).to_string())
    say("max |SEL_t diff|", np.nanmax(np.abs(cmp.SEL_t_mine - cmp.SEL_t_study)),
        " max |CONF_m diff|", np.nanmax(np.abs(cmp.CONF_m_mine - cmp.CONF_m_study)))
    say("picked 20: etf mix", z.etf.value_counts().to_dict(), " htf mix", z.htf.value_counts().to_dict(),
        " role mix", z.role.value_counts().to_dict())
    pick_conf = Dz.CONF_mW.mean()
    pick_conf_w = np.nansum(Dz.CONF_mW * Dz.CONF_nW) / Dz.CONF_nW.sum()
    say(f"picked 20 CONF cell-average {pick_conf:.5f}, trade-weighted {pick_conf_w:.5f};"
        f" their unfiltered entries (CONF_mALL) cell-average {Dz.CONF_mALL.mean():.5f};"
        f" coin-flip twin of the with-trades {Dz.CONF_mWo.mean():.5f}")
    say("picked 20: CONF positive", int((Dz.CONF_mW > 0).sum()), " CONF positive with payback",
        int((Dz.CONF_mW + PB > 0).sum()), " CONF one-sided p<0.05", int((pval(Dz.CONF_tW, Dz.CONF_MW) < 0.05).sum()))

    # ---- chance draws (cell level)
    E = D.loc[F[F.cond == "W"].idx].copy()           # eligible with-cells (SEL n >= 60, months >= 12)
    E = E[np.isfinite(E.CONF_mW) & (E.CONF_nW > 0)]
    say(f"eligible with-cells with a CONF read: {len(E)};  trade-weighted CONF mean {np.average(E.CONF_mW, weights=E.CONF_nW):.5f};"
        f" cell-average {E.CONF_mW.mean():.5f}")
    Epos = E[E.SEL_mW > 0]
    say(f"  of them SELECT mean > 0: {len(Epos)}, CONF cell-average {Epos.CONF_mW.mean():.5f}")
    rng = np.random.default_rng(1024)
    NDRAW = 10000
    res = {}
    for lab, pool in (("all_eligible", E), ("sel_pos", Epos)):
        vals = np.empty(NDRAW)
        keys = (pool["name"] + "@" + pool.etf).to_numpy()
        cm = pool.CONF_mW.to_numpy()
        uk, inv = np.unique(keys, return_inverse=True)
        members = [np.flatnonzero(inv == u) for u in range(len(uk))]
        for b in range(NDRAW):
            ks = rng.choice(len(uk), 20, replace=False)          # 20 distinct (strategy, entry tf)
            pick = [members[k][rng.integers(len(members[k]))] for k in ks]   # one random cell of each
            vals[b] = cm[pick].mean()
        res[lab] = vals
    # composition-matched: same (etf, htf) counts as the picked 20, from SELECT-positive cells
    comp = z.groupby(["etf", "htf"]).size().to_dict()
    vals = np.empty(NDRAW)
    keys_all = (Epos["name"] + "@" + Epos.etf).to_numpy()
    groups = {k: np.flatnonzero((Epos.etf.to_numpy() == k[0]) & (Epos.htf.to_numpy() == k[1])) for k in comp}
    cm = Epos.CONF_mW.to_numpy()
    for b in range(NDRAW):
        used, pick = set(), []
        for k, c in comp.items():
            g = groups[k][rng.permutation(len(groups[k]))]
            got = 0
            for j in g:
                if keys_all[j] in used:
                    continue
                used.add(keys_all[j])
                pick.append(j)
                got += 1
                if got == c:
                    break
        vals[b] = cm[pick].mean()
    res["sel_pos_mix_matched"] = vals
    # composition-matched from ALL eligible (no SELECT sign filter)
    keysE = (E["name"] + "@" + E.etf).to_numpy()
    groupsE = {k: np.flatnonzero((E.etf.to_numpy() == k[0]) & (E.htf.to_numpy() == k[1])) for k in comp}
    cmE = E.CONF_mW.to_numpy()
    vals = np.empty(NDRAW)
    for b in range(NDRAW):
        used, pick = set(), []
        for k, c in comp.items():
            g = groupsE[k][rng.permutation(len(groupsE[k]))]
            got = 0
            for j in g:
                if keysE[j] in used:
                    continue
                used.add(keysE[j])
                pick.append(j)
                got += 1
                if got == c:
                    break
        vals[b] = cmE[pick].mean()
    res["all_eligible_mix_matched"] = vals
    rows = []
    for lab, v in res.items():
        r = {"null": lab, "draws": NDRAW, "null_mean": v.mean(), "null_p05": np.quantile(v, 0.05),
             "null_p50": np.quantile(v, 0.5), "null_p95": np.quantile(v, 0.95), "picked": pick_conf,
             "p_null_ge_picked": (v >= pick_conf).mean(), "premium_vs_null_mean": pick_conf - v.mean()}
        rows.append(r)
    R = pd.DataFrame(rows)
    say("--- picked 20 with-cells (CONF cell-average) vs 20 random cells")
    say(R.round(5).to_string())
    R.to_csv(os.path.join(OUTD, "lm_select_null.csv"), index=False, float_format="%.6g")

    # ---- SELECT t as a predictor of CONFIRM
    rho = sst.spearmanr(E.SEL_tW, E.CONF_mW, nan_policy="omit")
    say(f"--- eligible with-cells: Spearman(SEL t, CONF mean) = {rho.correlation:.3f} (n={len(E)})")
    rho2 = sst.spearmanr(Epos.SEL_tW, Epos.CONF_mW, nan_policy="omit")
    say(f"    SELECT-positive only: {rho2.correlation:.3f} (n={len(Epos)})")
    # within (etf, htf) groups: does SEL t still predict? (removes the timeframe-composition part)
    E2 = E.assign(dec=pd.qcut(E.SEL_tW.rank(method="first"), 10, labels=False))
    say("CONF mean (cell-average) and etf mix by SELECT-t decile (0 = lowest):")
    say(E2.groupby("dec").agg(SEL_t=("SEL_tW", "mean"), SEL_m=("SEL_mW", "mean"), CONF_m=("CONF_mW", "mean"),
                              share4h=("etf", lambda x: (x == "4h").mean()),
                              share15m=("etf", lambda x: (x == "15m").mean())).round(4).to_string())
    part = []
    for (a, b), g in E.groupby(["etf", "htf"]):
        if len(g) > 50:
            r = sst.spearmanr(g.SEL_tW, g.CONF_mW).correlation
            part.append((a, b, len(g), round(r, 3), round(g.CONF_mW.mean(), 5)))
    say("Spearman within (etf, htf):", part)
    open(os.path.join(OUTD, "lm_select.txt"), "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
