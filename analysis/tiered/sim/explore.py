import sys, time, json, numpy as np
from lib import *
out = {}
for tf in sys.argv[1:]:
    t0 = time.time()
    P = Panel(tf)
    rng = np.random.default_rng(1)
    gi, ci, ti = P.draw_candidates(rng)
    pp = P.paths(ci, ti, 1)
    atr = pp["atr"]
    res = dict(n_cand=len(gi), cand_per_day=len(gi) / P.ndays)
    res["Eabs"] = {h: P.fwd_abs(h) for h in (1, 2, 4, 8, 16, 32, 64)}
    res["atr_med"] = {c: float(np.median(atr[ci == k])) for k, c in enumerate(COINS)}
    side = np.where(rng.random(len(gi)) < 0.5, 1, -1)
    hold = {}
    for L in (20, 30, 50):
        for sm in (1.5, 1.0):
            ks = []; cs = []; gs = []
            for sg in (1, -1):
                m = side == sg
                mv = prep_moves({k: (v[m] if hasattr(v, "shape") and v.shape[0] == len(gi) else v) for k, v in pp.items()}, sg)
                k, cc, g, cost, y = exits(mv, L, sm * atr[m], np.full(m.sum(), 0.10 / L), P.tfm)
                ks.append(k); cs.append(cc); gs.append(g)
            k = np.concatenate(ks); cc = np.concatenate(cs); g = np.concatenate(gs)
            hold[f"L{L}_s{sm}"] = dict(med_hold=float(np.median(k)), mean_hold=float(np.mean(k)),
                                     share=dict(tp=float(np.mean(cc == 1)), stop=float(np.mean(cc == 2)), liq=float(np.mean(cc == 3)), time=float(np.mean(cc == 4))),
                                     liq_first=float(np.mean(sm * atr >= 1.0 / L - MMR)), mean_g=float(np.mean(g)))
    res["ref"] = hold
    res["t"] = time.time() - t0
    out[tf] = res
    print(tf, json.dumps(res, indent=None)[:3000], flush=True)
json.dump(out, open("out/explore_" + "_".join(sys.argv[1:]) + ".json", "w"), indent=1)
