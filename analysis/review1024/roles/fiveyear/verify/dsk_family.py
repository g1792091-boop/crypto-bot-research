"""Direction-skill verifier (lens: look-ahead / alignment / data errors), part 1: rebuild the study's accumulators into
a RAM scratch of our own and re-derive the direction-skill family numbers of the claim:
  374 of 108,391 with-cells pass SELECT BH on the month-clustered paired t (with side minus its coin-flip twin),
  83 % of them beat their twin on CONFIRM vs 56 % of the other cells, none pass BH on CONFIRM,
  cell-average CONFIRM -3.3 % vs -4.4 % for the twin, 321 of them with SELECT mean + payback > 0 (bot G).
Nothing in the study folder is written (fy_analyze.main is NOT called).

    python3 dsk_family.py        (from this folder, no -I)"""
import os
import sys

FY = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
MY = "/dev/shm/claude_verify_dsk"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, FY)
os.makedirs(MY, exist_ok=True)

import fy_common                         # noqa: E402
fy_common.SHM = MY
import build_acc                         # noqa: E402
build_acc.SHM = MY
import fy_analyze                        # noqa: E402
fy_analyze.SHM = MY
from fy_analyze import bh, pval, np, pd, PAYBACK   # noqa: E402


def main():
    if not os.path.exists(os.path.join(MY, "meta.json")):
        build_acc.main()
    p = os.path.join(MY, "cells.pkl")
    if os.path.exists(p):
        D = pd.read_pickle(p)
    else:
        meta, A, AM, B, B0, BARS = fy_analyze.load()
        D = fy_analyze.cell_table(meta, A, AM, B, BARS)
        side_n = D.groupby(["pair", "src"]).apply(lambda z: (z.SEL_nW + z.SEL_nA + z.CONF_nW + z.CONF_nA).sum())
        dead = set(side_n[side_n == 0].index)
        D = D[[(a, b) not in dead for a, b in zip(D.pair, D.src)]].reset_index(drop=True)
        D.to_pickle(p)
    Wf = D[(D.SEL_nW >= 60) & (D.SEL_MW >= 12)].copy()
    Wf["pS"] = pval(Wf.SEL_tFlip.to_numpy(), Wf.SEL_MW.to_numpy())
    Wf["bh"] = bh(Wf.pS.to_numpy())
    pk = Wf[Wf.bh]
    ot = Wf[~Wf.bh]
    print("eligible with-cells", len(Wf), "BH pass on SELECT paired t", len(pk))
    for lab, z in (("picked", pk), ("others", ot)):
        c = z[z.CONF_nW > 0]
        c30 = z[z.CONF_nW >= 30]
        print(f"{lab}: cells {len(z)}, with CONF n>0 {len(c)}: CONF beats twin {np.mean(c.CONF_mW > c.CONF_mWo):.4f};"
              f" n>=30 {len(c30)}: {np.mean(c30.CONF_mW > c30.CONF_mWo):.4f};"
              f" cell-avg CONF {c.CONF_mW.mean():.5f} twin {c.CONF_mWo.mean():.5f};"
              f" trade-weighted {np.average(c.CONF_mW, weights=c.CONF_nW):.5f} twin {np.average(c.CONF_mWo, weights=c.CONF_nW):.5f}")
    pC = pval(pk.CONF_tFlip.to_numpy(), pk.CONF_MW.to_numpy())
    print("CONF BH among picked:", int(bh(pC).sum()), " CONF one-sided p<0.05:", int(np.nansum(pC < 0.05)))
    g = pk[pk.SEL_mW + 35 * PAYBACK > 0]
    print("G cells (SEL mean + payback > 0):", len(g))
    # compare with the study's flip_picked.csv
    F = pd.read_csv(os.path.join(FY, "flip_picked.csv"))
    key = lambda d: set(zip(d["name"], d.etf, d.htf, d.kind, d.source))   # noqa: E731
    a, b = key(pk), key(F)
    print("picked set == flip_picked.csv:", a == b, "only mine", len(a - b), "only study", len(b - a))
    M = pk.merge(F, on=["name", "etf", "htf", "kind", "source"], suffixes=("", "_st"))
    for c in ("SEL_nW", "SEL_mW", "SEL_mWo", "SEL_tFlip", "CONF_nW", "CONF_mW", "CONF_mWo", "FWD_mW"):
        print(f"  max |{c} - study| = {np.nanmax(np.abs(M[c] - M[c + '_st'])):.3g}")
    # drift-only expectation of (with - twin) for a random side with the cell's long share: (2 ls - 1)(barL - barS)
    for per in ("SEL", "CONF"):
        exp = (2 * pk[f"{per}_lsW"] - 1) * (pk[f"{per}_barL"] - pk[f"{per}_barS"])
        act = pk[f"{per}_mW"] - pk[f"{per}_mWo"]
        print(f"{per}: picked mean (with - twin) {act.mean():.5f}; drift-only expectation {exp.mean():.5f};"
              f" share of cells where actual > drift-only {np.mean(act > exp):.3f}")
    pk[["name", "role", "etf", "htf", "kind", "source", "SEL_nW", "SEL_mW", "SEL_mWo", "SEL_tFlip", "pS", "CONF_nW",
        "CONF_mW", "CONF_mWo", "CONF_tFlip", "SEL_lsW", "CONF_lsW"]].to_csv(os.path.join(HERE, "dsk_family_picked.csv"),
                                                                          index=False, float_format="%.6g")


if __name__ == "__main__":
    main()
