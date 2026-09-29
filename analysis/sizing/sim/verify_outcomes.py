"""Independent per-trade loop implementation of the exit rules; compare with vectorised outcomes()."""
import numpy as np
from simlib import *

def slow(O, Hh, Lw, C, E, s, M, L, N, dl, sd, td, tfm, advall=False):
    Hn = len(O)
    for j in range(Hn):
        om = s * (O[j] / E - 1)
        # gaps at the open
        if -om >= dl: code, g, k = 3, -dl, j + 1; break
        if sd < dl and -om >= sd: code, g, k = 2, om, j + 1; break
        if om >= td: code, g, k = 1, om, j + 1; break
        fav = (Hh[j] / E - 1) if s > 0 else (1 - Lw[j] / E)
        adv = (1 - Lw[j] / E) if s > 0 else (Hh[j] / E - 1)
        bull = C[j] >= O[j]
        advfirst = True if advall else (bull if s > 0 else not bull)
        adv_ev = None
        if sd < dl and adv >= sd: adv_ev = (2, -sd)
        elif adv >= dl: adv_ev = (3, -dl)
        tp_ev = (1, td) if fav >= td else None
        ev = None
        if advfirst:
            ev = adv_ev or tp_ev
        else:
            ev = tp_ev or adv_ev
        if ev:
            code, g = ev; k = j + 1; break
    else:
        code, g, k = 4, s * (C[-1] / E - 1), Hn
    fund = FUND_8H * k * tfm / 480
    cout = C_OUT_TP if code == 1 else C_OUT_MKT
    if code == 3:
        r = -M - N * (C_IN + fund)
    else:
        r = N * (g - C_IN - cout - fund)
    return k, code, g, r

rng = np.random.default_rng(1)
tot = 0; bad = 0
for tf in ["15m", "4h"]:
    P = Panel(tf)
    gi, ci, ti = P.draw_candidates(rng)
    sel = rng.choice(len(gi), 400, replace=False)
    pp = P.paths(ci[sel], ti[sel])
    for cname in ["P0|A|10", "P3|A|10", "P3|B|10", "P4|A|10", "P4|C|10", "P5|B|30", "P5|A|100", "P6|B|none", "P6|B|10", "P2|C|10"]:
        M, L, N, dl, sd, td = policy_params(cname, pp["atr"])
        for sgn in (1, -1):
            for advall in (False, True):
                k, cc, gg, r, y = outcomes(pp, np.full(len(sel), sgn), M, L, N, dl, sd, td, P.tfm, adverse_first_all=advall)
                for i in range(len(sel)):
                    ks, cs, gs, rs_ = slow(pp["O"][i], pp["H"][i], pp["L"][i], pp["C"][i], pp["E"][i], sgn, M[i], L[i], N[i], dl[i], sd[i], td[i], P.tfm, advall)
                    tot += 1
                    if not (ks == k[i] and cs == cc[i] and abs(gs - gg[i]) < 1e-12 and abs(rs_ - r[i]) < 1e-12):
                        bad += 1
                        if bad < 5: print("MISMATCH", tf, cname, sgn, i, (ks, cs, gs, rs_), (k[i], cc[i], gg[i], r[i]))
print("checked", tot, "mismatches", bad)
