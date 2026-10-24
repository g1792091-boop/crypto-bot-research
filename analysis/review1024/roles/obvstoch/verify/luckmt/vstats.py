"""Verifier (luck / multiple testing) for the claim 'with-trend Stoch RSI signals lose less than against-trend ones
(OBV only), timing hurts by 0.33 points'. Uses the study's own oscore.rows on a cache rebuilt by vbuild.py.

For every cell (tf, htf, T, O, X) and period it stores per-UTC-day sums so that family means get day-clustered SEs
that include the correlation between cells, and day/week-level trend-flip permutations can be run.
  W  = signals with the trend (the study's cell), A = signals against the trend (study's 'against'),
  TO = trend-only (every bar in the trend direction).
Quantities per cell:
  dwa  = mean roe_W - mean roe_A                       (the claim's metric)
  te   = mean over W u A of roe(trend side) - roe(counter side), SAME bars (direction effect of the trend)
  comp = mean c_W - mean c_A, c = (roe + opp)/2       (side-independent part: volatility / composition)
  tim  = mean roe_W - mean roe_TO                      (the '0.33 points' claim)
  dW   = mean(roe_W - opp_W)                           (coin-flip twin of the cell)
Writes verify/vcell.csv.gz and verify/vday_<period>.npz (per-day sums)."""
import os, sys
VH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import oscore as O
from oscore import *  # noqa

O.CACHE = "/dev/shm/claude_verify_obvstoch"
D = O.load_all()
D0 = T0 // DAY
ND = int((ext_end() // DAY) - D0 + 2)
PERS = ("SEL", "CONF", "FIVE", "FWD", "PRE")


def bc(day, w):
    return np.bincount(day - D0, weights=w, minlength=ND)


_TO = {}


def trend_only(tf, htf, T, X, per):
    k = (tf, htf, T, X, per)
    if k not in _TO:
        R = O.rows(D, tf, htf, T, None, X, per, trend_only=True)
        _TO[k] = (bc(R["day"], R["roe"]), bc(R["day"], np.ones(len(R["roe"]))))
    return _TO[k]


def one(args):
    tf, htf, T, Ot, X = args
    out = []
    for per in PERS:
        W = O.rows(D, tf, htf, T, Ot, X, per)
        A = O.rows(D, tf, htf, T, Ot, X, per, against=True)
        sTO, nTO = trend_only(tf, htf, T, X, per)
        rec = dict(cell=O.cell_id(tf, htf, T, Ot, X), tf=tf, htf=htf, trend=T, timing=Ot, exit=X, period=per,
                   nW=len(W["roe"]), nA=len(A["roe"]), nTO=int(nTO.sum()))
        days = {
            "SW": bc(W["day"], W["roe"]), "NW": bc(W["day"], np.ones(len(W["roe"]))),
            "SWo": bc(W["day"], W["opp"]),
            "SA": bc(A["day"], A["roe"]), "NA": bc(A["day"], np.ones(len(A["roe"]))),
            "SAo": bc(A["day"], A["opp"]),
            "STO": sTO, "NTO": nTO,
        }
        out.append((rec, {k: v.astype(np.float32) for k, v in days.items()}))
    return out


if __name__ == "__main__":
    from multiprocessing import get_context
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    cl = O.cells()
    recs = []
    dd = {p: {k: [] for k in ("SW", "NW", "SWo", "SA", "NA", "SAo", "STO", "NTO")} for p in PERS}
    with get_context("fork").Pool(4) as pool:
        for res in pool.imap(one, cl, chunksize=4):
            for rec, days in res:
                recs.append(rec)
                for k, v in days.items():
                    dd[rec["period"]][k].append(v)
    R = pd.DataFrame(recs)
    R.to_csv(os.path.join(VH, "vcell.csv.gz"), index=False)
    for p in PERS:
        np.savez(os.path.join(HERE if False else "/dev/shm/claude_verify_obvstoch", f"vday_{p}.npz"),
                 **{k: np.stack(v) for k, v in dd[p].items()})
    print("done", len(R))
