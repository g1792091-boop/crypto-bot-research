"""Direction-skill verifier, part 3b: bot G with the study's EXACT priority order (the rebuilt cells.pkl sorted by the
unrounded SELECT paired t, as goalpath.py does), then the same 321 cells under 30 random priority orders (one position
at a time: the priority decides which of the many same-minute signals is taken), to see how much of the one-position
numbers (CONFIRM, last 19 days) depend on that arbitrary order.

    python3 dsk_gbot_prio.py      (needs /dev/shm/claude_verify_dsk/cells.pkl from dsk_family.py)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsk_gbot as GB             # noqa: E402
from dsk_gbot import *            # noqa: E402,F401

FYD = "/home/user/crypto-bot-research/analysis/review1024/roles/fiveyear"
sys.path.insert(0, FYD)
from fy_analyze import bh, pval   # noqa: E402


def exact_cells():
    fam = pd.read_pickle("/dev/shm/claude_verify_dsk/cells.pkl")
    Wf = fam[(fam.SEL_nW >= 60) & (fam.SEL_MW >= 12)].copy()
    Wf["bh"] = bh(pval(Wf.SEL_tFlip.to_numpy(), Wf.SEL_MW.to_numpy()))
    g = Wf[Wf.bh & (Wf.SEL_mW + 35 * PAYBACK > 0)].sort_values("SEL_tFlip", ascending=False)
    return g[["name", "etf", "htf", "kind", "source"]].reset_index(drop=True)


def run(A, prio):
    A = A.assign(prio=prio[A.cell_i.to_numpy()])
    A = A.sort_values("prio", kind="stable").drop_duplicates(["coin", "e", "side", "name", "tf"])
    A = A.sort_values(["e", "prio"], kind="stable").reset_index(drop=True)
    res = {}
    for per in ("CONF", "FWD"):
        a, b = EDG[per]
        P = A[(A.t >= a) & (A.t < b)].reset_index(drop=True)
        T = P[one_pos(P)]
        To = P[one_pos(P, opp=True)]
        res[per] = (len(T), 35 * T.w35_r.mean(), 35 * To.w35_opp_r.mean())
    return res


def main():
    G = exact_cells()
    parts = []
    for p, r in G.iterrows():
        S = rows_of(r["name"], r.etf, r.htf, r.kind, r.source)
        if len(S):
            S["cell_i"] = p
            parts.append(S)
    A = pd.concat(parts, ignore_index=True)
    lines = []
    base = run(A, np.arange(len(G)))
    lines.append(f"exact study order: CONF trades {base['CONF'][0]} mean {base['CONF'][1]:.5f} flip {base['CONF'][2]:.5f};"
                 f" FWD trades {base['FWD'][0]} mean {base['FWD'][1]:.5f} flip {base['FWD'][2]:.5f}")
    rng = np.random.default_rng(5)
    R = []
    for b in range(30):
        res = run(A, rng.permutation(len(G)))
        R.append({"CONF_n": res["CONF"][0], "CONF_m": res["CONF"][1], "CONF_flip": res["CONF"][2],
                  "FWD_n": res["FWD"][0], "FWD_m": res["FWD"][1], "FWD_flip": res["FWD"][2]})
    R = pd.DataFrame(R)
    lines.append("30 random priority orders (same 321 cells, same signals):")
    lines.append(R.describe().loc[["mean", "std", "min", "50%", "max"]].round(5).to_string())
    lines.append(f"FWD mean below the coin flip in {int((R.FWD_m < R.FWD_flip).sum())} of 30 orders;"
                 f" CONF mean above the coin flip in {int((R.CONF_m > R.CONF_flip).sum())} of 30")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(GB.HERE, "dsk_gbot_prio.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    main()
